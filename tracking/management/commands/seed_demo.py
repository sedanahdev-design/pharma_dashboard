from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from tracking.models import Category, MonthlyUpload, SalesRow, TargetItem
from tracking.services.parsing import parse_sales_workbook, parse_target_workbook

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "sample_data"


class Command(BaseCommand):
    help = "Seeds the database with the real July 2026 موسع + تارغيت كاتيغوري sample data."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="شهر 7 - 2026")

    def handle(self, *args, **options):
        name = options["name"]
        if MonthlyUpload.objects.filter(name=name).exists():
            self.stdout.write(self.style.WARNING(f"'{name}' موجودة مسبقاً - تم التخطي."))
            return

        sales_path = SAMPLE_DIR / "موسع شهر 7.xlsx"
        targets_path = SAMPLE_DIR / "تارغيت كاتيغوري.xlsx"
        if not sales_path.exists() or not targets_path.exists():
            self.stderr.write(self.style.ERROR(f"ملفات العينة غير موجودة في {SAMPLE_DIR}"))
            return

        with open(sales_path, "rb") as f:
            sales_records = parse_sales_workbook(f)
        with open(targets_path, "rb") as f:
            target_records = parse_target_workbook(f)

        with transaction.atomic():
            upload = MonthlyUpload.objects.create(
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

        self.stdout.write(
            self.style.SUCCESS(
                f"تم إنشاء '{name}': {len(sales_records)} سطر مبيعات، {len(categories)} تصنيف."
            )
        )
