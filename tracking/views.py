from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CategoryForm, ImportTargetsForm, MonthlyUploadForm, TargetItemForm
from .models import Category, MonthlyUpload, SalesRow, TargetItem
from .services.export import build_workbook
from .services.parsing import WorkbookFormatError, parse_sales_workbook, parse_target_workbook
from .services.reporting import compute_report

BULK_CHUNK = 2000


def upload_list(request):
    uploads = MonthlyUpload.objects.all()
    return render(request, "tracking/upload_list.html", {"uploads": uploads})


def upload_create(request):
    if request.method == "POST":
        form = MonthlyUploadForm(request.POST, request.FILES)
        if form.is_valid():
            sales_file = form.cleaned_data["sales_file"]
            targets_file = form.cleaned_data.get("targets_file")
            clone_from = form.cleaned_data.get("clone_from")

            try:
                sales_records = parse_sales_workbook(sales_file)
            except WorkbookFormatError as exc:
                form.add_error("sales_file", str(exc))
                return render(request, "tracking/upload_form.html", {"form": form})

            target_records = None
            if targets_file:
                try:
                    target_records = parse_target_workbook(targets_file)
                except WorkbookFormatError as exc:
                    form.add_error("targets_file", str(exc))
                    return render(request, "tracking/upload_form.html", {"form": form})

            with transaction.atomic():
                upload = form.save(commit=False)
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

                if target_records:
                    _import_target_records(upload, target_records)

            messages.success(
                request,
                f"تم رفع الملف بنجاح: {len(sales_records):,} سطر مبيعات.".replace(",", "،"),
            )
            return redirect("tracking:upload_detail", pk=upload.pk)
    else:
        form = MonthlyUploadForm()
    return render(request, "tracking/upload_form.html", {"form": form})


def _clone_categories(source_upload, target_upload):
    for cat in source_upload.categories.prefetch_related("target_items"):
        new_cat = Category.objects.create(upload=target_upload, name=cat.name, order=cat.order)
        TargetItem.objects.bulk_create(
            [TargetItem(category=new_cat, item_name=ti.item_name) for ti in cat.target_items.all()]
        )


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


def upload_detail(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
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


@require_POST
def category_add(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    form = CategoryForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["name"].strip()
        max_order = upload.categories.order_by("-order").values_list("order", flat=True).first() or 0
        Category.objects.get_or_create(upload=upload, name=name, defaults={"order": max_order + 1})
    return _dashboard_partial(request, upload)


@require_POST
def category_rename(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    category = get_object_or_404(Category, pk=cat_id, upload=upload)
    new_name = (request.POST.get("name") or "").strip()
    if new_name:
        category.name = new_name
        category.save(update_fields=["name"])
    return _dashboard_partial(request, upload)


@require_POST
def category_delete(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    Category.objects.filter(pk=cat_id, upload=upload).delete()
    return _dashboard_partial(request, upload)


@require_POST
def item_add(request, pk, cat_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    category = get_object_or_404(Category, pk=cat_id, upload=upload)
    form = TargetItemForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["item_name"].strip()
        if name:
            TargetItem.objects.get_or_create(category=category, item_name=name)
    return _dashboard_partial(request, upload)


@require_POST
def item_delete(request, pk, item_id):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    TargetItem.objects.filter(pk=item_id, category__upload=upload).delete()
    return _dashboard_partial(request, upload)


@require_POST
def import_targets(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
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


@require_POST
def upload_delete(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    upload.delete()
    messages.success(request, "تم حذف الدفعة.")
    return redirect("tracking:upload_list")


def export_excel(request, pk):
    upload = get_object_or_404(MonthlyUpload, pk=pk)
    report = compute_report(upload)
    buf = build_workbook(upload, report)
    filename = f"نتيجة-{upload.name}.xlsx".replace(" ", "-")
    return FileResponse(buf, as_attachment=True, filename=filename)
