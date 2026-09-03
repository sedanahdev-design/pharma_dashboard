"""Builds a professional, styled .xlsx export of a computed report -
overall summary, a detailed sheet with every item (target items bold and
highlighted, exactly like the original أصناف الأورانج report style), and
one sheet per pharmacy so branch managers can be sent just their page."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

TITLE_FILL = PatternFill("solid", fgColor="1F3864")
SUBTITLE_FILL = PatternFill("solid", fgColor="EBF5FB")
NOTE_FILL = PatternFill("solid", fgColor="FFFDE7")
HEADER_FILL = PatternFill("solid", fgColor="2F5496")
CATEGORY_BAND_FILL = PatternFill("solid", fgColor="354F72")
TARGET_FILL = PatternFill("solid", fgColor="FFF2CC")
STRIPE_FILL = PatternFill("solid", fgColor="EBF5FB")
WHITE_FONT_BOLD = Font(color="FFFFFF", bold=True, size=13)
HEADER_FONT = Font(color="FFFFFF", bold=True)
CATEGORY_FONT = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HEADERS = ["#", "التصنيف", "الصنف", "الكمية", "% من التصنيف", "مستهدف؟"]


def _sheet_title(ws, title, subtitle=None):
    ws.sheet_view.rightToLeft = True
    ws.merge_cells("A1:F1")
    ws["A1"] = title
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = WHITE_FONT_BOLD
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    if subtitle:
        ws.merge_cells("A2:F2")
        ws["A2"] = subtitle
        ws["A2"].fill = SUBTITLE_FILL
        ws["A2"].font = BOLD
        ws["A2"].alignment = Alignment(horizontal="center")

    note_row = 3
    ws.merge_cells(f"A{note_row}:F{note_row}")
    ws[f"A{note_row}"] = "الصفوف الملوّنة الغامقة هي الأصناف المستهدفة (التي طلبت من الصيدلية بيعها)"
    ws[f"A{note_row}"].fill = NOTE_FILL
    ws[f"A{note_row}"].alignment = Alignment(horizontal="center")


def _write_table(ws, start_row, rows_by_category):
    """rows_by_category: list of (category_name, cat_total_qty, [ItemStat,...])"""
    header_row = start_row
    for col, text in enumerate(HEADERS, start=1):
        cell = ws.cell(row=header_row, column=col, value=text)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = BORDER

    r = header_row + 1
    counter = 1
    for cat_name, cat_total, items in rows_by_category:
        ws.merge_cells(f"A{r}:F{r}")
        band_cell = ws.cell(row=r, column=1, value=f"  {cat_name}   |   الكمية: {cat_total:g} عبوة")
        band_cell.fill = CATEGORY_BAND_FILL
        band_cell.font = CATEGORY_FONT
        r += 1
        for i, item in enumerate(items):
            pct = (item.quantity / cat_total * 100) if cat_total else 0
            fill = TARGET_FILL if item.is_target else (STRIPE_FILL if i % 2 else PatternFill(fill_type=None))
            font = BOLD if item.is_target else Font()
            values = [counter, cat_name, item.item_name, round(item.quantity, 2), round(pct, 1), "نعم" if item.is_target else ""]
            for col, val in enumerate(values, start=1):
                cell = ws.cell(row=r, column=col, value=val)
                cell.fill = fill
                cell.font = font
                cell.border = BORDER
                if col in (4, 5):
                    cell.alignment = Alignment(horizontal="center")
            counter += 1
            r += 1

    widths = [6, 30, 45, 12, 14, 10]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    return r


def _rows_for(report, pharmacy_name=None):
    """Build (category_name, total_qty, items[]) tuples, optionally scoped
    to a single pharmacy."""
    out = []
    for cat in report.categories:
        if pharmacy_name is None:
            items = cat.sorted_items()
            total = cat.total_qty
        else:
            # Re-aggregate items for just this pharmacy from the raw pharmacy stat
            # (falls back to 0 if the pharmacy had no sales in this category).
            ph = cat.pharmacies.get(pharmacy_name)
            if ph is None or ph.total_qty == 0:
                continue
            total = ph.total_qty
            items = None  # per-pharmacy per-item breakdown isn't tracked separately; show totals only
        if total <= 0:
            continue
        if items is not None:
            out.append((cat.category.name, total, items))
    return out


def build_workbook(upload, report) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)

    # --- Overall summary sheet -------------------------------------------------
    ws = wb.create_sheet("ملخص التصنيفات")
    ws.sheet_view.rightToLeft = True
    subtitle = (
        f"إجمالي الكمية المتتبعة: {report.total_tracked_qty:g} عبوة   |   "
        f"من الصنف المستهدف: {report.total_target_qty:g} ({report.target_pct:.1f}%)"
    )
    _sheet_title(ws, f"ملخص المبيعات حسب التصنيف  |  {upload.name}", subtitle)
    headers = ["#", "التصنيف", "إجمالي الكمية", "% من الإجمالي", "كمية الصنف المستهدف", "نسبة الالتزام %"]
    header_row = 5
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=text)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = BORDER
    r = header_row + 1
    for i, cat in enumerate(report.categories, start=1):
        if cat.total_qty <= 0:
            continue
        pct_total = (cat.total_qty / report.total_tracked_qty * 100) if report.total_tracked_qty else 0
        values = [i, cat.category.name, round(cat.total_qty, 2), round(pct_total, 1), round(cat.target_qty, 2), round(cat.target_pct, 1)]
        fill = STRIPE_FILL if i % 2 == 0 else PatternFill(fill_type=None)
        for col, val in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.fill = fill
            cell.border = BORDER
            if col != 2:
                cell.alignment = Alignment(horizontal="center")
        r += 1
    widths = [6, 34, 16, 14, 20, 16]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # --- Full detail sheet -------------------------------------------------
    ws2 = wb.create_sheet("الإجمالي العام")
    _sheet_title(ws2, f"التفصيل الكامل حسب الصنف  |  {upload.name}", subtitle)
    _write_table(ws2, 5, _rows_for(report))

    # --- One sheet per pharmacy ---------------------------------------------
    pharmacy_names = set()
    for cat in report.categories:
        pharmacy_names.update(cat.pharmacies.keys())

    for pharmacy_name in sorted(pharmacy_names):
        safe_name = pharmacy_name[:31] or "صيدلية"
        # Excel sheet names can't repeat or contain []:*?/\\
        for ch in "[]:*?/\\":
            safe_name = safe_name.replace(ch, "-")
        base_name = safe_name
        n = 1
        existing = set(wb.sheetnames)
        while safe_name in existing:
            n += 1
            safe_name = f"{base_name[:28]}-{n}"

        ws_p = wb.create_sheet(safe_name)
        rows = []
        ph_total_all = 0.0
        ph_target_all = 0.0
        for cat in report.categories:
            ph = cat.pharmacies.get(pharmacy_name)
            if ph is None or ph.total_qty == 0:
                continue
            ph_total_all += ph.total_qty
            ph_target_all += ph.target_qty
            items = cat.sorted_items_for_pharmacy(pharmacy_name)
            rows.append((cat.category.name, ph.total_qty, items))
        ph_pct = (ph_target_all / ph_total_all * 100) if ph_total_all else 0
        _sheet_title(
            ws_p,
            f"{pharmacy_name}  |  {upload.name}",
            f"إجمالي الكمية: {ph_total_all:g} عبوة   |   من الصنف المستهدف: {ph_target_all:g} ({ph_pct:.1f}%)",
        )
        _write_table(ws_p, 5, rows)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
