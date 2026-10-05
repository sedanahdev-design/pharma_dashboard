from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from tracking.models import Category, ItemPrice, MonthlyUpload, SalesRow, TargetItem
from tracking.services.parsing import (
    parse_price_report_workbook,
    parse_sales_workbook,
    parse_target_workbook,
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "sample_data"


class Command(BaseCommand):
    help = "Seeds the database with the real July 2026 موسع + تارغيت كاتيغوري sample data."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="شهر 7 - 2026")
        parser.add_argument(
            "--owner",
            default=None,
            help="اسم المستخدم الذي تُنسب إليه بيانات المثال (الافتراضي: حساب المالك).",
        )

    def handle(self, *args, **options):
        from django.contrib.auth.models import User

        name = options["name"]
        if MonthlyUpload.objects.filter(name=name).exists():
            self.stdout.write(self.style.WARNING(f"'{name}' موجودة مسبقاً - تم التخطي."))
            return

        # Sample data has to belong to someone now that every page filters
        # by owner - otherwise it would be seeded into a month no account
        # can open, which looks exactly like a broken import.
        if options["owner"]:
            owner = User.objects.filter(username=options["owner"]).first()
            if owner is None:
                self.stderr.write(self.style.ERROR(f"لا يوجد مستخدم باسم {options['owner']}"))
                return
        else:
            owner = (
                User.objects.filter(is_superuser=True).order_by("pk").first()
                or User.objects.order_by("pk").first()
            )
        if owner is None:
            self.stderr.write(
                self.style.ERROR("لا يوجد أي مستخدم بعد - نفّذ setup_users أولاً.")
            )
            return

        sales_path = SAMPLE_DIR / "موسع شهر 7.xlsx"
        targets_path = SAMPLE_DIR / "تارغيت كاتيغوري.xlsx"
        prices_path = SAMPLE_DIR / "تقرير أصناف الأورانج.xlsx"
        if not sales_path.exists() or not targets_path.exists():
            self.stderr.write(self.style.ERROR(f"ملفات العينة غير موجودة في {SAMPLE_DIR}"))
            return

        with open(sales_path, "rb") as f:
            sales_records = parse_sales_workbook(f)
        with open(targets_path, "rb") as f:
            target_records = parse_target_workbook(f)
        price_records = []
        if prices_path.exists():
            with open(prices_path, "rb") as f:
                price_records = parse_price_report_workbook(f)

        with transaction.atomic():
            upload = MonthlyUpload.objects.create(
                owner=owner,
                name=name,
                source_filename=sales_path.name,
                notes="بيانات فعلية مستوردة تلقائياً كمثال عند إنشاء المشروع.",
            )
            SalesRow.objects.bulk_create(
                [
                    SalesRow(
                        upload=upload,
                        item_name=r.item_name,
                        pharmacy_name=r.pharmacy_name,
                        quantity=r.quantity,
                        raw_category=r.raw_category,
                    )
                    for r in sales_records
                ],
                batch_size=2000,
            )

            categories = {}
            order = 0
            for rec in target_records:
                cat = categories.get(rec.category_name)
                if cat is None:
                    order += 1
                    cat = Category.objects.create(upload=upload, name=rec.category_name, order=order)
                    categories[rec.category_name] = cat
                TargetItem.objects.get_or_create(category=cat, item_name=rec.item_name)

            if price_records:
                ItemPrice.objects.bulk_create(
                    [
                        ItemPrice(upload=upload, item_name=rec.item_name, unit_price=rec.unit_price)
                        for rec in price_records
                    ],
                    batch_size=2000,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"تم إنشاء '{name}': {len(sales_records)} سطر مبيعات، {len(categories)} تصنيف، "
                f"{len(price_records)} سعر صنف."
            )
        )
