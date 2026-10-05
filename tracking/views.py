from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import tracking_required

from .forms import (
    CategoryForm,
    ImportTargetsForm,
    MonthlyUploadForm,
    TargetItemForm,
)
from .models import Category, ItemPrice, MonthlyUpload, SalesRow, TargetItem
from .services.export import build_workbook
from .services.parsing import (
    WorkbookFormatError,
    detect_workbook_kind,
    extract_embedded_prices,
    parse_price_report_workbook,
    parse_sales_workbook,
    parse_target_workbook,
)
from .services.reporting import compute_report

BULK_CHUNK = 2000


@tracking_required
def upload_list(request):
    uploads = MonthlyUpload.objects.filter(owner=request.user)
    return render(request, "tracking/upload_list.html", {"uploads": uploads})


@tracking_required
def upload_create(request):
    if request.method == "POST":
        form = MonthlyUploadForm(request.POST, request.FILES, owner=request.user)
        if form.is_valid():
            # Files can arrive two ways: the dedicated "sales_file" slot
            # (usually just the موسع file) and/or the dedicated
            # "price_file" slot, OR someone selected several files
            # together in the "sales_file" multi-select (Ctrl/Cmd-click)
            # without using "price_file" at all. Pool every file from
            # both slots and sniff each one's actual columns rather than
            # trusting which slot it landed in - so it still works
            # whichever way the person selected their files, or even if
            # they got sales/price backwards.
            candidate_files = list(form.cleaned_data["sales_file"])
            explicit_price_file = form.cleaned_data.get("price_file")
            if explicit_price_file:
                candidate_files.append(explicit_price_file)
            targets_file = form.cleaned_data.get("targets_file")
            clone_from = form.cleaned_data.get("clone_from")
            clone_prices_too = form.cleaned_data.get("clone_prices_too")

            sales_file = None
            price_file = None
            for f in candidate_files:
                kind = detect_workbook_kind(f)
                if kind == "sales" and sales_file is None:
                    sales_file = f
                elif kind == "prices" and price_file is None:
                    price_file = f

            if sales_file is None:
                form.add_error(
                    "sales_file",
                    "لم أجد بين الملفات المختارة ملف مبيعات (موسع) صالح - تأكد من أنه يحتوي على "
                    "أعمدة اسم المادة / مركز الكلفة / عبوة.",
                )
                return render(request, "tracking/upload_form.html", {"form": form})

            try:
                sales_records = parse_sales_workbook(sales_file)
            except WorkbookFormatError as exc:
                form.add_error("sales_file", str(exc))
                return render(request, "tracking/upload_form.html", {"form": form})

            # Prices for this exact month can come from two places: a
            # separate price report (تقرير أصناف الأورانج) selected
            # alongside the sales file, and/or a "السعر" column embedded
            # right inside the موسع file itself (present in some months).
            # Neither is required - either one alone is enough, and if
            # both are present the explicit report wins per item since it
            # was deliberately chosen, while the embedded prices still
            # fill in any item the report happens to miss.
            embedded_price_records = extract_embedded_prices(sales_file)

            explicit_price_records = None
            if price_file is not None:
                try:
                    explicit_price_records = parse_price_report_workbook(price_file)
                except WorkbookFormatError as exc:
                    form.add_error("sales_file", str(exc))
                    return render(request, "tracking/upload_form.html", {"form": form})

            price_records = None
            embedded_count = 0
            if embedded_price_records or explicit_price_records:
                merged = {rec.item_name: rec for rec in embedded_price_records}
                embedded_count = len(merged)
                for rec in explicit_price_records or []:
                    merged[rec.item_name] = rec
                price_records = list(merged.values())

            target_records = None
            if targets_file:
                try:
                    target_records = parse_target_workbook(targets_file)
                except WorkbookFormatError as exc:
                    form.add_error("targets_file", str(exc))
                    return render(request, "tracking/upload_form.html", {"form": form})

            with transaction.atomic():
                upload = form.save(commit=False)
                upload.owner = request.user
                upload.source_filename = getattr(sales_file, "name", "")
                upload.save()

                rows = [
                    SalesRow(
                        upload=upload,
                        item_name=r.item_name,
                        pharmacy_name=r.pharmacy_name,
                        quantity=r.quantity,
                        raw_category=r.raw_category,
                    )
                    for r in sales_records
                ]
                SalesRow.objects.bulk_create(rows, batch_size=BULK_CHUNK)

                if clone_from:
                    _clone_categories(clone_from, upload)
                    if clone_prices_too:
                        _clone_prices(clone_from, upload)

                if target_records:
                    _import_target_records(upload, target_records)

                # ملف موسع نفسه يوسم كل سطر بعمود "الشروحات 5" - وهذا الوسم
                # هو مصدر الحقيقة لأي تصنيف موجود فعلياً هذا الشهر، بصرف
                # النظر عمّا إذا ذُكر هذا التصنيف في ملف تارغيت+كاتيغوري أم
                # لا (قد لا يكون له صنف مستهدف معيّن إطلاقاً، وتكون كل
                # مبيعاته "بديل"). بدون هذه الخطوة، أي تصنيف لم يُذكر في
                # ملف التارغيت يُستبعد بصمت من كل الإحصائيات - وهذا كان
                # يُنتج نقصاً حقيقياً بإجمالي الكمية المتتبعة.
                auto_created_categories = _auto_create_missing_categories(upload, sales_records)

                # A price report selected alongside the sales file always
                # wins over anything cloned from a previous month - it's
                # this month's own, exact prices.
                if price_records:
                    _import_price_records(upload, price_records)

            message = f"تم رفع الملف بنجاح: {len(sales_records):,} سطر مبيعات.".replace(",", "،")
            if price_records:
                message += f" وتم اشتقاق أسعار {len(price_records):,} صنف لهذا الشهر تحديداً".replace(",", "،")
                if embedded_count and not explicit_price_records:
                    message += " مباشرة من عمود السعر في ملف موسع - لم تكن هناك حاجة لملف أسعار منفصل."
                elif embedded_count:
                    message += " (من عمود السعر في ملف موسع وتقرير الأسعار معاً)."
                else:
                    message += "."
            if auto_created_categories:
                message += (
                    f" وتم اكتشاف {auto_created_categories:,} تصنيفاً إضافياً من عمود الشروحات 5 "
                    "لم يكن معرَّفاً مسبقاً (لا صنف مستهدف له بعد - كل مبيعاته تُحتسب بديلاً)."
                ).replace(",", "،")
            messages.success(request, message)
            return redirect("tracking:upload_detail", pk=upload.pk)
    else:
        form = MonthlyUploadForm(owner=request.user)
    return render(request, "tracking/upload_form.html", {"form": form})


def _clone_categories(source_upload, target_upload):
    for cat in source_upload.categories.prefetch_related("target_items"):
        new_cat = Category.objects.create(upload=target_upload, name=cat.name, order=cat.order)
        TargetItem.objects.bulk_create(
            [TargetItem(category=new_cat, item_name=ti.item_name) for ti in cat.target_items.all()]
        )


def _auto_create_missing_categories(upload, sales_records):
    """Every distinct, non-blank "الشروحات 5" tag found in the sales file
    is a real category as far as موسع is concerned, even if the target+
    كاتيغوري workbook never listed an official target item for it (a
    category with no designated target product still exists - all of its
    sales just count as "بديل"). Any tag that doesn't already match a
    Category for this upload gets created here (with no target items) so
    its quantity/value isn't silently dropped from every total - matching
    what you'd get by filtering موسع on a non-blank الشروحات 5 column
    yourself. Returns how many categories were auto-created this way."""
    existing_names = {c.name for c in upload.categories.all()}
    max_order = max((c.order for c in upload.categories.all()), default=0)
    seen_tags = []
    for r in sales_records:
        tag = (r.raw_category or "").strip()
        if tag and tag not in existing_names and tag not in seen_tags:
            seen_tags.append(tag)
    for tag in seen_tags:
        max_order += 1
        Category.objects.create(upload=upload, name=tag, order=max_order)
        existing_names.add(tag)
    return len(seen_tags)


def _import_target_records(upload, target_records):
    existing = {c.name: c for c in upload.categories.all()}
    max_order = max([c.order for c in existing.values()], default=0)
    created_items = 0
    for rec in target_records:
        cat = existing.get(rec.category_name)
        if cat is None:
            max_order += 1
            cat = Category.objects.create(upload=upload, name=rec.category_name, order=max_order)
            existing[rec.category_name] = cat
        _, created = TargetItem.objects.get_or_create(category=cat, item_name=rec.item_name)
        if created:
            created_items += 1
    return created_items


def _clone_prices(source_upload, target_upload):
    ItemPrice.objects.bulk_create(
        [
            ItemPrice(upload=target_upload, item_name=ip.item_name, unit_price=ip.unit_price)
            for ip in source_upload.item_prices.all()
        ]
    )


def _import_price_records(upload, price_records):
    updated = 0
    created = 0
    for rec in price_records:
        _, was_created = ItemPrice.objects.update_or_create(
            upload=upload, item_name=rec.item_name, defaults={"unit_price": rec.unit_price}
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated


@tracking_required
def upload_detail(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    return render(request, "tracking/upload_detail.html", _detail_context(upload))


def _detail_context(upload):
    categories = upload.categories.prefetch_related("target_items").order_by("order", "name")
    report = compute_report(upload)
    return {
        "upload": upload,
        "categories": categories,
        "report": report,
        "category_form": CategoryForm(),
        "item_form": TargetItemForm(),
        "import_form": ImportTargetsForm(),
    }


def _dashboard_partial(request, upload):
    return render(request, "tracking/_dashboard_content.html", _detail_context(upload))


@tracking_required
@require_POST
def category_add(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    form = CategoryForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["name"].strip()
        max_order = upload.categories.order_by("-order").values_list("order", flat=True).first() or 0
        Category.objects.get_or_create(upload=upload, name=name, defaults={"order": max_order + 1})
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def category_rename(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    category = get_object_or_404(Category, pk=cat_id, upload=upload)
    new_name = (request.POST.get("name") or "").strip()
    if new_name:
        category.name = new_name
        category.save(update_fields=["name"])
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def category_delete(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    Category.objects.filter(pk=cat_id, upload=upload).delete()
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def item_add(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    category = get_object_or_404(Category, pk=cat_id, upload=upload)
    form = TargetItemForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["item_name"].strip()
        if name:
            TargetItem.objects.get_or_create(category=category, item_name=name)
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def item_delete(request, pk, item_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    TargetItem.objects.filter(pk=item_id, category__upload=upload).delete()
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def import_targets(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    form = ImportTargetsForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            records = parse_target_workbook(form.cleaned_data["targets_file"])
            created = _import_target_records(upload, records)
            messages.success(request, f"تم استيراد {created} صنف مستهدف جديد.")
        except WorkbookFormatError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "تعذر قراءة الملف.")
    return _dashboard_partial(request, upload)


@tracking_required
@require_POST
def upload_delete(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    upload.delete()
    messages.success(request, "تم حذف الدفعة.")
    return redirect("tracking:upload_list")


@tracking_required
def export_excel(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk, owner=request.user)
    report = compute_report(upload)
    buf = build_workbook(upload, report)
    filename = f"نتيجة-{upload.name}.xlsx".replace(" ", "-")
    return FileResponse(buf, as_attachment=True, filename=filename)
