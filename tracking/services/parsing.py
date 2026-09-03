"""Tolerant .xlsx readers for the two workbook shapes this app understands:

1. The "موسع" monthly sales export - one row per sale, with the item name,
   the pharmacy (cost centre), the quantity, and (for some rows) an existing
   category tag (عمود "الشروحات 5").

2. The "تارغيت + كاتيغوري" workbook - a two column lookup of
   item name -> category name, listing the specific products the owner
   instructed pharmacies to sell for each category that month.

Column headers vary a little from month to month (extra spaces, a
trailing "5", Excel merged header rows, etc.), so headers are matched by
keyword rather than by exact string.
"""

from __future__ import annotations

from dataclasses import dataclass

import openpyxl


class WorkbookFormatError(ValueError):
    """Raised when a required column can't be found in the uploaded file."""


def _norm(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_column(header_cells: list[str], keywords: list[str]) -> int | None:
    """Return the index of the first header cell containing any keyword."""
    for kw in keywords:
        for idx, cell in enumerate(header_cells):
            if kw in cell:
                return idx
    return None


def _first_sheet_with_header(workbook, required_keyword_sets: list[list[str]], max_scan_rows=5):
    """Find a worksheet (and its header row) whose header contains at least
    one keyword from every required set. Falls back to the active sheet."""
    for ws in workbook.worksheets:
        for row_idx in range(1, max_scan_rows + 1):
            row = [_norm(c) for c in next(ws.iter_rows(min_row=row_idx, max_row=row_idx, values_only=True), [])]
            if not any(row):
                continue
            if all(_find_column(row, kws) is not None for kws in required_keyword_sets):
                return ws, row_idx, row
    return None, None, None


@dataclass
class SalesRecord:
    item_name: str
    pharmacy_name: str
    quantity: float
    raw_category: str


ITEM_KEYWORDS = ["اسم المادة", "اسم الصنف", "الصنف"]
PHARMACY_KEYWORDS = ["مركز الكلفة", "اسم الصيدلية", "الصيدلية"]
QUANTITY_KEYWORDS = ["عبوة", "الكمية", "الكميه"]
CATEGORY_KEYWORDS = ["الشروحات", "التصنيف", "المجموعة", "كاتيغوري", "كاتغوري"]


def parse_sales_workbook(file_obj) -> list[SalesRecord]:
    """Parse a موسع-style workbook into a flat list of SalesRecord rows."""
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    ws, header_row_idx, header = _first_sheet_with_header(
        wb, [ITEM_KEYWORDS, PHARMACY_KEYWORDS, QUANTITY_KEYWORDS]
    )
    if ws is None:
        raise WorkbookFormatError(
            "لم أتمكن من العثور على أعمدة (اسم المادة / مركز الكلفة / عبوة) في الملف. "
            "تأكد من أنك ترفع ملف موسع الشهر الصحيح."
        )

    item_col = _find_column(header, ITEM_KEYWORDS)
    pharmacy_col = _find_column(header, PHARMACY_KEYWORDS)
    qty_col = _find_column(header, QUANTITY_KEYWORDS)
    cat_col = _find_column(header, CATEGORY_KEYWORDS)

    records: list[SalesRecord] = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if row is None or len(row) <= item_col:
            continue
        item_name = _norm(row[item_col])
        if not item_name:
            continue
        pharmacy = _norm(row[pharmacy_col]) if pharmacy_col is not None and pharmacy_col < len(row) else ""
        raw_qty = row[qty_col] if qty_col is not None and qty_col < len(row) else 0
        try:
            quantity = float(raw_qty) if raw_qty not in (None, "") else 0.0
        except (TypeError, ValueError):
            quantity = 0.0
        raw_category = ""
        if cat_col is not None and cat_col < len(row):
            raw_category = _norm(row[cat_col])
        records.append(
            SalesRecord(
                item_name=item_name,
                pharmacy_name=pharmacy,
                quantity=quantity,
                raw_category=raw_category,
            )
        )
    wb.close()
    return records


@dataclass
class TargetRecord:
    item_name: str
    category_name: str


def parse_target_workbook(file_obj) -> list[TargetRecord]:
    """Parse a تارغيت+كاتيغوري style workbook: item -> category lookup."""
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    ws, header_row_idx, header = _first_sheet_with_header(wb, [ITEM_KEYWORDS, CATEGORY_KEYWORDS])
    if ws is None:
        raise WorkbookFormatError(
            "لم أتمكن من العثور على عمودي (الصنف / التصنيف) في الملف. "
            "تأكد من أنك تختار ملف التارغيت كاتيغوري الصحيح."
        )

    item_col = _find_column(header, ITEM_KEYWORDS)
    cat_col = _find_column(header, CATEGORY_KEYWORDS)

    records: list[TargetRecord] = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if row is None or len(row) <= max(item_col, cat_col):
            continue
        item_name = _norm(row[item_col])
        category_name = _norm(row[cat_col])
        if not item_name or not category_name:
            continue
        records.append(TargetRecord(item_name=item_name, category_name=category_name))
    wb.close()
    return records
