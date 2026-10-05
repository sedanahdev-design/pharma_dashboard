from django.contrib import messages
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import reconcile_required

from .forms import ImportPharmaciesForm, MemoUploadForm, MovementBatchForm, PharmacyForm
from .models import Memo, MemoItem, MovementBatch, MovementRow, Pharmacy
from .services.engine import compute_report
from .services.export import build_workbook
from .services.parsing import (
    WorkbookFormatError,
    detect_workbook_kind,
    parse_memo_workbook,
    parse_movements_workbook,
    parse_transfers_workbook,
)

BULK_CHUNK = 2000


def _owned_pharmacies(request):
    return Pharmacy.objects.filter(owner=request.user).prefetch_related("memos__items")


@reconcile_required
def batch_list(request):
    batches = MovementBatch.objects.filter(owner=request.user)
    return render(
        request,
        "reconcile/batch_list.html",
        {
            "batches": batches,
            "pharmacy_count": Pharmacy.objects.filter(owner=request.user).count(),
            "memo_count": Memo.objects.filter(owner=request.user).count(),
        },
    )


@reconcile_required
def batch_create(request):
    if request.method == "POST":
        form = MovementBatchForm(request.POST, request.FILES)
        if form.is_valid():
            uploads = form.cleaned_data["movements_file"]
            # Sales and transfers come out of the accounting system as two
            # separate exports, and either one alone is a legitimate
            # upload - so every selected file is sniffed and merged into
            # one batch rather than forcing the person to say which slot
            # each belongs in.
            records, names, periods, kinds = [], [], [], []
            try:
                for upload in uploads:
                    kind = detect_workbook_kind(upload)
                    if kind == "transfers":
                        parsed = parse_transfers_workbook(upload)
                    elif kind == "movements":
                        parsed = parse_movements_workbook(upload)
                    else:
                        raise WorkbookFormatError(
                            f"الملف «{getattr(upload, 'name', '')}» ليس كشف حركات ولا كشف مناقلات - "
                            "تأكد من أنه يحتوي أعمدة اسم المادة ومركز الكلفة والكمية."
                        )
                    records.extend(parsed.records)
                    names.append(getattr(upload, "name", ""))
                    kinds.append(kind)
                    if parsed.period_text:
                        periods.append(parsed.period_text)
            except WorkbookFormatError as exc:
                form.add_error("movements_file", str(exc))
                return render(request, "reconcile/batch_form.html", {"form": form})

            with transaction.atomic():
                batch = form.save(commit=False)
                batch.owner = request.user
                batch.source_filename = " + ".join(n for n in names if n)[:255]
                batch.period_text = " | ".join(dict.fromkeys(periods))[:200]
                batch.save()
                MovementRow.objects.bulk_create(
                    [
                        MovementRow(
                            batch=batch,
                            code=r.code,
                            item_name=r.item_name,
                            invoice_type=r.invoice_type,
                            cost_center=r.cost_center,
                            quantity=r.quantity,
                            price=r.price,
                        )
                        for r in records
                    ],
                    batch_size=BULK_CHUNK,
                )

            known = set(
                Pharmacy.objects.filter(owner=request.user).values_list("cost_center", flat=True)
            )
            new_centers = [c for c in batch.cost_centers if c not in known]
            msg = (f"تم رفع {len(uploads)} ملف: {len(records):,} حركة.").replace(",", "،")
            if "transfers" not in kinds:
                msg += (" تنبيه: لا يوجد ضمن الملفات المرفوعة أي كشف مناقلات، "
                        "لذلك سيبقى عمود «الكمية المتناقلة» صفراً.")
            if new_centers:
                msg += f" ووُجد {len(new_centers)} مركز كلفة غير معرَّف بعد - عرّفها لتظهر بالمطابقة."
            messages.success(request, msg)
            if new_centers:
                return redirect("reconcile:pharmacy_list")
            return redirect("reconcile:batch_detail", pk=batch.pk)
    else:
        form = MovementBatchForm()
    return render(request, "reconcile/batch_form.html", {"form": form})


@reconcile_required
def batch_detail(request, pk):
    batch = get_object_or_404(MovementBatch, pk=pk, owner=request.user)
    report = compute_report(batch, pharmacies=list(_owned_pharmacies(request)))
    selected_key = request.GET.get("p") or ""
    selected = None
    for result in report.results:
        if str(result.pharmacy.pk) == selected_key:
            selected = result
            break
    if selected is None:
        with_memo = [r for r in report.results if r.has_memo]
        selected = with_memo[0] if with_memo else (report.results[0] if report.results else None)
    return render(
        request,
        "reconcile/batch_detail.html",
        {"batch": batch, "report": report, "selected": selected},
    )


@reconcile_required
@require_POST
def batch_delete(request, pk):
    batch = get_object_or_404(MovementBatch, pk=pk, owner=request.user)
    batch.delete()
    messages.success(request, "تم حذف الكشف.")
    return redirect("reconcile:batch_list")


@reconcile_required
def batch_export(request, pk):
    batch = get_object_or_404(MovementBatch, pk=pk, owner=request.user)
    report = compute_report(batch, pharmacies=list(_owned_pharmacies(request)))
    buf = build_workbook(report)
    filename = f"مطابقة-{batch.name}.xlsx".replace(" ", "-")
    return FileResponse(buf, as_attachment=True, filename=filename)


@reconcile_required
def pharmacy_list(request):
    pharmacies = list(_owned_pharmacies(request))
    known = {p.cost_center for p in pharmacies}
    latest = MovementBatch.objects.filter(owner=request.user).first()
    suggested = [c for c in (latest.cost_centers if latest else []) if c not in known]
    return render(
        request,
        "reconcile/pharmacy_list.html",
        {
            "pharmacies": pharmacies,
            "form": PharmacyForm(owner=request.user),
            "memo_form": MemoUploadForm(),
            "suggested": suggested,
            "import_form": ImportPharmaciesForm(choices=suggested) if suggested else None,
            "latest_batch": latest,
        },
    )


@reconcile_required
@require_POST
def pharmacy_create(request):
    form = PharmacyForm(request.POST, owner=request.user)
    if form.is_valid():
        pharmacy = form.save(commit=False)
        pharmacy.owner = request.user
        pharmacy.save()
        messages.success(request, f"تمت إضافة {pharmacy.label}.")
    else:
        messages.error(request, "تعذر إضافة الصيدلية: " + "؛ ".join(
            f"{v[0]}" for v in form.errors.values()
        ))
    return redirect("reconcile:pharmacy_list")


@reconcile_required
@require_POST
def pharmacy_import(request):
    latest = MovementBatch.objects.filter(owner=request.user).first()
    choices = latest.cost_centers if latest else []
    form = ImportPharmaciesForm(request.POST, choices=choices)
    if form.is_valid():
        created = 0
        for center in form.cleaned_data["centers"]:
            _, was_created = Pharmacy.objects.get_or_create(
                owner=request.user,
                cost_center=center,
                defaults={"short_name": _short_name_for(center)},
            )
            created += int(was_created)
        messages.success(request, f"تمت إضافة {created} صيدلية من كشف الحركات.")
    else:
        messages.error(request, "لم يتم اختيار أي مركز كلفة.")
    return redirect("reconcile:pharmacy_list")


def _short_name_for(cost_center: str) -> str:
    """"صيدلية ليليان الفارس-شبعا" reads better on a tab as "ليليان الفارس".
    Purely cosmetic and always editable afterwards."""
    text = cost_center.replace("صيدلية", "").strip()
    for sep in ("-", "/", "–"):
        if sep in text:
            text = text.split(sep)[0]
            break
    return text.strip()[:120]


@reconcile_required
@require_POST
def pharmacy_delete(request, pk):
    pharmacy = get_object_or_404(Pharmacy, pk=pk, owner=request.user)
    label = pharmacy.label
    pharmacy.delete()
    messages.success(request, f"تم حذف {label} ومذكراتها.")
    return redirect("reconcile:pharmacy_list")


@reconcile_required
@require_POST
def memo_upload(request, pk):
    pharmacy = get_object_or_404(Pharmacy, pk=pk, owner=request.user)
    form = MemoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "اختر ملف المذكرة أولاً.")
        return redirect("reconcile:pharmacy_list")

    upload = form.cleaned_data["memo_file"]
    try:
        parsed = parse_memo_workbook(upload)
    except WorkbookFormatError as exc:
        messages.error(request, f"{pharmacy.label}: {exc}")
        return redirect("reconcile:pharmacy_list")

    with transaction.atomic():
        memo = form.save(commit=False)
        memo.owner = request.user
        memo.pharmacy = pharmacy
        memo.number = parsed.number
        memo.source_filename = getattr(upload, "name", "")
        memo.save()
        MemoItem.objects.bulk_create(
            [
                MemoItem(
                    memo=memo,
                    row_order=item.row_order,
                    code=item.code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    price=item.price,
                    expiry_text=item.expiry_text,
                )
                for item in parsed.items
            ],
            batch_size=BULK_CHUNK,
        )

    messages.success(
        request,
        f"تم رفع مذكرة {pharmacy.label}"
        + (f" رقم {parsed.number}" if parsed.number else "")
        + f": {len(parsed.items)} بند. هذه المذكرة هي المعتمدة الآن لهذه الصيدلية.",
    )
    return redirect("reconcile:pharmacy_list")


@reconcile_required
@require_POST
def memo_delete(request, pk):
    memo = get_object_or_404(Memo, pk=pk, owner=request.user)
    label = memo.pharmacy.label
    memo.delete()
    messages.success(request, f"تم حذف مذكرة {label}.")
    return redirect("reconcile:pharmacy_list")
