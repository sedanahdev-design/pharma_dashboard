"""Excel export of a reconciliation report.

The first twelve columns, their order, their wording, the sheet set and
the row ordering all follow the owner's approved reference workbook
(تقرير حركة ورصيد كل الصيدليات), so the output can be opened beside the
old file and read without relearning anything.

Three things are added rather than copied:

* **كلفة اجمالية is always computed** (العدد × الكلفة). The reference
  leaves that column empty for four of the nine pharmacies although it
  holds both inputs, which zeroes their value totals and understates the
  group total by roughly 235,000.
* **A ملاحظة column** that names, per row, what makes it worth a look -
  negative remainder, duplicate مذكرة line, missing cost, inbound
  transfer.
* **A المشاكل والتنبيهات sheet**, so a branch with no مذكرة or a cost
  centre nobody defined is stated outright instead of being absent.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

TITLE_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FILL = PatternFill("solid", fgColor="2F5496")
SUB_FILL = PatternFill("solid", fgColor="EBF5FB")
STAGNANT_FILL = PatternFill("solid", fgColor="F2F2F2")
MOVING_FILL = PatternFill("solid", fgColor="E8F5E9")
WARN_FILL = PatternFill("solid", fgColor="FDEBD0")
BAD_FILL = PatternFill("solid", fgColor="FADBD8")
EXTRA_FILL = PatternFill("solid", fgColor="FFF9C4")

WHITE_BOLD = Font(color="FFFFFF", bold=True, size=13)
HEADER_FONT = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# The reference's own twelve columns, in its own order and wording, plus
# two of ours: عدد العبوات المتحركة sits directly after the two columns it
# adds together, so the arithmetic is visible on the row rather than left
# to be done by hand, and ملاحظة closes the row.
COLUMNS = [
    "الصيدلية",
    "اسم الصنف",
    "تاريخ الصلاحية",
    "الكمية الحالية بالصيدلية",
    "كلفة وسطية",
    "كلفة اجمالية",
    "الكمية المباعة (صافي)",
    "الكمية المتناقلة (خارج)",
    "عدد العبوات المتحركة (مباع + متناقل)",   # added
    "الكمية المتبقية بعد البيع والمناقلة",
    "هل انباع؟",
    "هل تناقل؟",
    "الحالة",
    "ملاحظة",                                  # added
]
WIDTHS = [26, 46, 13, 11, 10, 12, 12, 12, 14, 14, 9, 9, 10, 30]
#: Columns written right-aligned (text); everything else is centred.
TEXT_COLS = {1, 2, 14}

STATE_FILLS = {"bad": BAD_FILL, "warn": WARN_FILL, "idle": STAGNANT_FILL, "done": MOVING_FILL}


def _sheet_name(label: str, used: set) -> str:
    """Excel tab names cannot exceed 31 characters or contain []:*?/\\ -
    and two branches can easily collide once truncated."""
    clean = "".join(ch for ch in label if ch not in "[]:*?/\\")[:28].strip() or "صيدلية"
    name, n = clean, 2
    while name in used:
        name = f"{clean[:26]}_{n}"
        n += 1
    used.add(name)
    return name


def _title(ws, text, subtitle, ncols):
    last = get_column_letter(ncols)
    ws.sheet_view.rightToLeft = True
    ws.merge_cells(f"A1:{last}1")
    ws["A1"] = text
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = WHITE_BOLD
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    if subtitle:
        ws.merge_cells(f"A2:{last}2")
        ws["A2"] = subtitle
        ws["A2"].fill = SUB_FILL
        ws["A2"].font = BOLD
        ws["A2"].alignment = Alignment(horizontal="center")


def _header(ws, row_idx, headers, widths=None):
    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    if widths:
        for col, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[row_idx].height = 30
    ws.freeze_panes = ws.cell(row=row_idx + 1, column=1)


def _row_values(result, row):
    return [
        result.pharmacy.cost_center,
        row.item_name,
        row.expiry_text,
        row.quantity,
        row.price,
        round(row.total_cost, 2),
        row.sold,
        row.transfer_out,
        row.moved_qty,
        row.remaining,
        row.sold_flag,
        row.transfer_flag,
        row.state,
        row.note,
    ]


def _write_rows(ws, result, start_row):
    row_idx = start_row
    for row in result.sorted_rows:
        fill = STATE_FILLS.get(row.state_key)
        for col, value in enumerate(_row_values(result, row), start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(
                horizontal="right" if col in TEXT_COLS else "center", vertical="center"
            )
            if fill is not None:
                cell.fill = fill
        row_idx += 1
    return row_idx


def build_workbook(report) -> io.BytesIO:
    wb = Workbook()
    _comparison_sheet(wb.active, report)
    _detail_sheet(wb.create_sheet("التقرير التفصيلي"), report)

    used = {wb.active.title, "التقرير التفصيلي"}
    for result in report.ranked + [r for r in report.results if not r.has_memo]:
        ws = wb.create_sheet(_sheet_name(result.pharmacy.label, used))
        _pharmacy_sheet(ws, result)

    _problems_sheet(wb.create_sheet("المشاكل والتنبيهات"), report)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _comparison_sheet(ws, report):
    ws.title = "مقارنة الصيدليات"
    # Every "عدد" column is immediately followed by its "كمية" column, so
    # the item count and the package count for the same group sit side by
    # side and can never be read as one another.
    headers = [
        "الصيدلية",
        "عدد الأصناف كامل", "كمية العبوات كاملة",
        "عدد الأصناف الراكدة", "كمية العبوات الراكدة", "قيمة الراكد",
        "عدد الأصناف المتحركة", "كمية عبوات الأصناف المتحركة", "قيمة المتحرك",
        "نسبة الراكد من العدد %",
        "إجمالي المباع", "إجمالي المتناقل", "إجمالي العبوات المتحركة",
        "الحالة",
    ]
    _title(
        ws,
        f"مقارنة الأصناف الراكدة والمتحركة - {report.batch.name}",
        report.batch.period_text or f"رُفع في {report.batch.uploaded_at:%Y/%m/%d}",
        len(headers),
    )
    _header(ws, 4, headers, [30, 13, 14, 14, 15, 13, 14, 16, 13, 13, 12, 13, 15, 18])

    status_text = {
        "no-memo": ("لا توجد مذكرة", BAD_FILL),
        "no-movements": ("لا حركات في الكشف", BAD_FILL),
        "warn": ("يحتاج مراجعة", WARN_FILL),
        "slow": ("ركود مرتفع", WARN_FILL),
        "ok": ("سليم", MOVING_FILL),
    }

    row_idx = 5
    for result in report.ranked + [r for r in report.results if not r.has_memo]:
        label, fill = status_text[result.status]
        values = [
            result.pharmacy.cost_center,
            result.item_count,
            round(result.total_pieces, 2),
            result.stagnant_count,
            round(result.stagnant_qty, 2),
            round(result.stagnant_value, 2),
            result.moving_count,
            round(result.moving_qty, 2),
            round(result.moving_value, 2),
            round(result.stagnant_pct, 1),
            round(result.total_sold, 2),
            round(result.total_transfer, 2),
            round(result.total_moved_qty, 2),
            label,
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="right" if col == 1 else "center")
            if col in (1, len(values)):
                cell.fill = fill
        row_idx += 1

    totals = [
        "الإجمالي",
        report.total_items, round(report.total_pieces, 2),
        report.total_stagnant, round(report.total_stagnant_qty, 2),
        round(report.total_stagnant_value, 2),
        report.total_moving, round(report.total_moving_qty, 2),
        round(report.total_moving_value, 2),
        round(report.stagnant_pct, 1),
        round(report.total_sold, 2), round(report.total_transfer, 2),
        round(report.total_moved_qty, 2), "",
    ]
    for col, value in enumerate(totals, start=1):
        cell = ws.cell(row=row_idx, column=col, value=value)
        cell.font = BOLD
        cell.fill = SUB_FILL
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="right" if col == 1 else "center")

    row_idx += 2
    for line in [
        "ملاحظات هامة:",
        "• «راكد» = لم يُبَع ولم يُناقل إطلاقاً خلال فترة الكشف. «متحرك» = بيع أو نوقل.",
        "• كل عمود «عدد …» يعدّ الأصناف، وبجانبه عمود «كمية …» يجمع العبوات - رقمان مختلفان عمداً.",
        "• «كمية عبوات الأصناف المتحركة» = ما تملكه الصيدلية من تلك الأصناف بالمذكرة. أما «إجمالي العبوات المتحركة» = ما تحرّك فعلاً منها (المباع + المتناقل).",
        "• الكمية المتبقية = العدد بالمذكرة − المباع − المتناقل. القيمة بالسالب تعني حركة أكبر من الموجود.",
        "• قيمة الراكد والمتحرك محسوبة = العدد × الكلفة الوسطية لكل سطر.",
        "• راجع ورقة «المشاكل والتنبيهات» قبل اعتماد الأرقام.",
    ]:
        ws.cell(row=row_idx, column=1, value=line).font = BOLD if line.endswith(":") else Font()
        row_idx += 1


def _detail_sheet(ws, report):
    _title(ws, f"التقرير التفصيلي - كل الصيدليات - {report.batch.name}", None, len(COLUMNS))
    _header(ws, 3, COLUMNS, WIDTHS)
    row_idx = 4
    for result in report.ranked:
        row_idx = _write_rows(ws, result, row_idx)
    ws.auto_filter.ref = f"A3:{get_column_letter(len(COLUMNS))}{max(row_idx - 1, 4)}"


def _pharmacy_sheet(ws, result):
    memo = result.memo
    bits = [result.pharmacy.cost_center]
    if memo:
        bits.append(f"مذكرة رقم {memo.number or '-'}")
        bits.append(f"رُفعت {memo.uploaded_at:%Y/%m/%d}")
    _title(ws, result.pharmacy.label, " | ".join(bits), len(COLUMNS))

    if not result.has_memo:
        ws.merge_cells(f"A4:{get_column_letter(len(COLUMNS))}4")
        cell = ws["A4"]
        cell.value = "لا توجد مذكرة مرفوعة لهذه الصيدلية - ارفع مذكرتها ثم أعد تحميل التقرير."
        cell.fill = BAD_FILL
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions["A"].width = 44
        return

    summary = (
        f"الأصناف: {result.item_count} | راكد: {result.stagnant_count} "
        f"({result.stagnant_pct:.1f}%) بقيمة {result.stagnant_value:,.0f} | "
        f"متحرك: {result.moving_count} بقيمة {result.moving_value:,.0f}"
    )
    ws.merge_cells(f"A3:{get_column_letter(len(COLUMNS))}3")
    ws["A3"] = summary
    ws["A3"].fill = SUB_FILL
    ws["A3"].font = BOLD
    ws["A3"].alignment = Alignment(horizontal="center")

    _header(ws, 4, COLUMNS, WIDTHS)
    row_idx = _write_rows(ws, result, 5)
    ws.auto_filter.ref = f"A4:{get_column_letter(len(COLUMNS))}{max(row_idx - 1, 5)}"

    if result.extras:
        row_idx += 1
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(COLUMNS))
        banner = ws.cell(row=row_idx, column=1)
        banner.value = f"أصناف تحرّكت في هذه الصيدلية وغير موجودة في مذكرتها ({len(result.extras)} صنف)"
        banner.fill = EXTRA_FILL
        banner.font = BOLD
        banner.alignment = Alignment(horizontal="center")
        row_idx += 1
        for extra in result.extras:
            values = [
                result.pharmacy.cost_center, extra.item_name, "", "", "", "",
                extra.sold, extra.transfer_out,
                round(extra.sold + extra.transfer_out, 6), "",
                "نعم" if extra.sold > 0 else "لا",
                "نعم" if extra.transfer_out > 0 else "لا",
                "خارج المذكرة", f"رقم الصنف {extra.code}" if extra.code else "",
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                cell.border = BORDER
                cell.fill = EXTRA_FILL
                cell.alignment = Alignment(horizontal="right" if col in TEXT_COLS else "center")
            row_idx += 1

    if result.problems or result.notes:
        row_idx += 1
        for text, fill in [(p, WARN_FILL) for p in result.problems] + [(n, SUB_FILL) for n in result.notes]:
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(COLUMNS))
            cell = ws.cell(row=row_idx, column=1, value=f"⚠ {text}")
            cell.fill = fill
            cell.alignment = Alignment(horizontal="right", wrap_text=True)
            row_idx += 1


def _problems_sheet(ws, report):
    headers = ["الصيدلية", "نوع الملاحظة", "التفصيل"]
    _title(ws, "كل ما يحتاج انتباهك في هذا الكشف", None, len(headers))
    _header(ws, 3, headers, [26, 24, 110])

    entries = [("- عام -", "تنبيه عام", p) for p in report.problems]
    for result in report.results:
        kind = "لا توجد مذكرة" if not result.has_memo else "يحتاج مراجعة"
        entries += [(result.pharmacy.label, kind, p) for p in result.problems]
    for result in report.results:
        entries += [(result.pharmacy.label, "للعلم", n) for n in result.notes]

    row_idx = 4
    if not entries:
        ws.cell(row=row_idx, column=1, value="لا توجد ملاحظات.").font = BOLD
        return
    for label, kind, text in entries:
        for col, value in enumerate((label, kind, text), start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="right", wrap_text=True, vertical="center")
            if col == 1:
                cell.fill = SUB_FILL
            elif col == 2:
                cell.fill = WARN_FILL if kind != "للعلم" else SUB_FILL
        row_idx += 1
