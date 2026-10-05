"""Builds a professional, styled .xlsx export of a computed report -
overall summary, a detailed sheet with every item (target items bold and
highlighted, exactly like the original أصناف الأورانج report style), and
one sheet per pharmacy so branch managers can be sent just their page.

Quantity is always shown; القيمة / اجمالي القيمة (بالليرة السورية الجديدة)
are included whenever the upload has at least one known item price."""

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
WARN_FILL = PatternFill("solid", fgColor="FDEBD0")
WHITE_FONT_BOLD = Font(color="FFFFFF", bold=True, size=13)
HEADER_FONT = Font(color="FFFFFF", bold=True)
CATEGORY_FONT = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CURRENCY_LABEL = "ل.س.ج"  # الليرة السورية الجديدة


def _detail_headers(has_prices):
    headers = ["#", "التصنيف", "الصنف", "الكمية", "% من التصنيف"]
    if has_prices:
        headers += [
            f"السعر ({CURRENCY_LABEL})",
            f"القيمة ({CURRENCY_LABEL})",
            "% القيمة من التصنيف",
        ]
    headers += ["مستهدف؟"]
    return headers


def _sheet_title(ws, title, subtitle=None, num_cols=6):
    last_col = get_column_letter(num_cols)
    ws.sheet_view.rightToLeft = True
    ws.merge_cells(f"A1:{last_col}1")
    ws["A1"] = title
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = WHITE_FONT_BOLD
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    if subtitle:
        ws.merge_cells(f"A2:{last_col}2")
        ws["A2"] = subtitle
        ws["A2"].fill = SUBTITLE_FILL
        ws["A2"].font = BOLD
        ws["A2"].alignment = Alignment(horizontal="center")

    note_row = 3
    ws.merge_cells(f"A{note_row}:{last_col}{note_row}")
    ws[f"A{note_row}"] = "الصفوف الملوّنة الغامقة هي الأصناف المستهدفة (التي طلبت من الصيدلية بيعها)"
    ws[f"A{note_row}"].fill = NOTE_FILL
    ws[f"A{note_row}"].alignment = Alignment(horizontal="center")


def _write_table(ws, start_row, rows_by_category, has_prices):
    headers = _detail_headers(has_prices)
    num_cols = len(headers)
    header_row = start_row
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=text)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = BORDER

    numeric_cols = {4, 5} if not has_prices else {4, 5, 6, 7, 8}
    last_col_letter = get_column_letter(num_cols)

    r = header_row + 1
    counter = 1
    for cat_name, cat_total_qty, cat_total_value, items in rows_by_category:
        ws.merge_cells(f"A{r}:{last_col_letter}{r}")
        band_text = f"  {cat_name}   |   الكمية: {cat_total_qty:g} عبوة"
        if has_prices:
            band_text += f"   |   إجمالي القيمة: {cat_total_value:,.0f} {CURRENCY_LABEL}"
        band_cell = ws.cell(row=r, column=1, value=band_text)
        band_cell.fill = CATEGORY_BAND_FILL
        band_cell.font = CATEGORY_FONT
        r += 1
        for i, item in enumerate(items):
            pct = (item.quantity / cat_total_qty * 100) if cat_total_qty else 0
            fill = TARGET_FILL if item.is_target else (STRIPE_FILL if i % 2 else PatternFill(fill_type=None))
            font = BOLD if item.is_target else Font()
            values = [counter, cat_name, item.item_name, round(item.quantity, 2), round(pct, 1)]
            if has_prices:
                value_pct = (item.value / cat_total_value * 100) if cat_total_value else 0
                values += [
                    round(item.unit_price, 2) if item.has_price else "—",
                    round(item.value, 0) if item.has_price else "—",
                    round(value_pct, 1) if item.has_price else "—",
                ]
            values += ["نعم" if item.is_target else ""]
            for col, val in enumerate(values, start=1):
                cell = ws.cell(row=r, column=col, value=val)
                cell.fill = fill
                cell.font = font
                cell.border = BORDER
                if col in numeric_cols:
                    cell.alignment = Alignment(horizontal="center")
            counter += 1
            r += 1

    widths = [6, 30, 42, 12, 13]
    if has_prices:
        widths += [14, 16, 16]
    widths += [10]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    return r


def _rows_for(report):
    """Build (category_name, total_qty, total_value, items[]) tuples for
    the full detail table."""
    out = []
    for cat in report.categories:
        if cat.total_qty <= 0:
            continue
        out.append((cat.category.name, cat.total_qty, cat.total_value, cat.sorted_items()))
    return out


def build_workbook(upload, report) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    has_prices = report.has_prices

    # --- Overall summary sheet -------------------------------------------------
    ws = wb.create_sheet("ملخص التصنيفات")
    ws.sheet_view.rightToLeft = True
    subtitle = (
        f"إجمالي الكمية المتتبعة: {report.total_tracked_qty:g} عبوة   |   "
        f"من الصنف المستهدف: {report.total_target_qty:g} ({report.target_pct:.1f}%)"
    )
    if has_prices:
        subtitle += (
            f"   |   إجمالي القيمة: {report.total_tracked_value:,.0f} {CURRENCY_LABEL}   |   "
            f"أصناف مستهدفة (ل.س.ج): {report.total_target_value:,.0f} ({report.target_value_pct:.1f}%)"
        )
        if not report.has_own_prices:
            subtitle += "   |   (الأسعار موروثة من دفعة شهر سابق)"
    headers = ["#", "التصنيف", "إجمالي الكمية", "% الكمية", "كمية الصنف المستهدف", "نسبة الالتزام % (كمية)"]
    if has_prices:
        headers += [
            f"إجمالي القيمة ({CURRENCY_LABEL})",
            "% القيمة",
            f"قيمة الصنف المستهدف ({CURRENCY_LABEL})",
            "نسبة الالتزام % (قيمة)",
        ]
    num_cols = len(headers)
    _sheet_title(ws, f"ملخص المبيعات حسب التصنيف  |  {upload.name}", subtitle, num_cols=num_cols)
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
        if has_prices:
            pct_value_total = (cat.total_value / report.total_tracked_value * 100) if report.total_tracked_value else 0
            values += [
                round(cat.total_value, 0),
                round(pct_value_total, 1),
                round(cat.target_value, 0),
                round(cat.target_value_pct, 1),
            ]
        fill = STRIPE_FILL if i % 2 == 0 else PatternFill(fill_type=None)
        for col, val in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.fill = fill
            cell.border = BORDER
            if col != 2:
                cell.alignment = Alignment(horizontal="center")
        r += 1
    widths = [6, 34, 15, 13, 18, 16]
    if has_prices:
        widths += [18, 12, 20, 16]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # --- Full detail sheet -------------------------------------------------
    ws2 = wb.create_sheet("الإجمالي العام")
    _sheet_title(ws2, f"التفصيل الكامل حسب الصنف  |  {upload.name}", subtitle, num_cols=len(_detail_headers(has_prices)))
    _write_table(ws2, 5, _rows_for(report), has_prices)

    # --- One sheet per pharmacy ---------------------------------------------
    pharmacy_names = set()
    for cat in report.categories:
        pharmacy_names.update(cat.pharmacies.keys())

    for pharmacy_name in sorted(pharmacy_names):
        safe_name = pharmacy_name[:31] or "صيدلية"
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
        ph_value_all = 0.0
        ph_target_value_all = 0.0
        for cat in report.categories:
            ph = cat.pharmacies.get(pharmacy_name)
            if ph is None or ph.total_qty == 0:
                continue
            ph_total_all += ph.total_qty
            ph_target_all += ph.target_qty
            ph_value_all += ph.total_value
            ph_target_value_all += ph.target_value
            items = cat.sorted_items_for_pharmacy(pharmacy_name)
            rows.append((cat.category.name, ph.total_qty, ph.total_value, items))
        ph_pct = (ph_target_all / ph_total_all * 100) if ph_total_all else 0
        ph_sub = f"إجمالي الكمية: {ph_total_all:g} عبوة   |   من الصنف المستهدف: {ph_target_all:g} ({ph_pct:.1f}%)"
        if has_prices:
            ph_value_pct = (ph_target_value_all / ph_value_all * 100) if ph_value_all else 0
            ph_sub += f"   |   إجمالي القيمة: {ph_value_all:,.0f} {CURRENCY_LABEL} ({ph_value_pct:.1f}% مستهدف)"
        _sheet_title(ws_p, f"{pharmacy_name}  |  {upload.name}", ph_sub, num_cols=len(_detail_headers(has_prices)))
        _write_table(ws_p, 5, rows, has_prices)

    # --- Missing-price diagnostics sheet -------------------------------------
    if has_prices and report.items_missing_price:
        ws3 = wb.create_sheet("أصناف بلا سعر")
        _sheet_title(
            ws3,
            f"أصناف مُتتبَّعة بلا سعر معروف  |  {upload.name}",
            "قيمتها احتُسبت صفراً في كل الجداول أعلاه حتى يُضاف سعرها",
            num_cols=2,
        )
        ws3.cell(row=5, column=1, value="الصنف").fill = HEADER_FILL
        ws3.cell(row=5, column=2, value="الكمية المباعة").fill = HEADER_FILL
        for col in (1, 2):
            c = ws3.cell(row=5, column=col)
            c.font = HEADER_FONT
            c.alignment = Alignment(horizontal="center")
            c.border = BORDER
        r = 6
        for i, row in enumerate(report.items_missing_price):
            fill = WARN_FILL if i % 2 == 0 else PatternFill(fill_type=None)
            c1 = ws3.cell(row=r, column=1, value=row["item_name"])
            c2 = ws3.cell(row=r, column=2, value=round(row["quantity"], 2))
            for c in (c1, c2):
                c.fill = fill
                c.border = BORDER
            c2.alignment = Alignment(horizontal="center")
            r += 1
        ws3.column_dimensions["A"].width = 45
        ws3.column_dimensions["B"].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
