"""Readers for the two workbook shapes this service compares.

Both are real exports from the pharmacy's own systems, not files anyone
fills in by hand for us, so the readers are deliberately tolerant:

* The كشف حركات has a title row above the real header, headers written
  with a tatweel ("الرقــم") and a stray trailing blank row, and its
  column order is not guaranteed between exports - so the header row is
  *found* by keyword rather than assumed to be row 1.

* The مذكرة has no header row at all. Its columns are identified by what
  the data in them looks like (a short integer code, a long Arabic name,
  a date-like string, two numeric columns) rather than by position, so a
  مذكرة exported with an extra leading column still reads correctly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

import openpyxl

TATWEEL = "ـ"
ARABIC_DIACRITICS = re.compile(r"[ً-ْٰ]")


class WorkbookFormatError(ValueError):
    """Raised when a file clearly isn't the workbook we were promised."""


def _norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm_header(value) -> str:
    """Headers are matched after stripping tatweel, diacritics and runs of
    whitespace, because the same column is spelled "الرقــم" in one export
    and "الرقم" in the next."""
    text = _norm(value).replace(TATWEEL, "")
    text = ARABIC_DIACRITICS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _to_float(value, default=0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    # Arabic-Indic digits appear in a few hand-edited files.
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    try:
        return float(text)
    except ValueError:
        return default


def _looks_numeric(value) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip().replace(",", "")
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    try:
        float(text)
        return True
    except ValueError:
        return False


DATE_LIKE = re.compile(r"^\s*\d{3,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,2}\s*$")


def _looks_like_date(value) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    return bool(DATE_LIKE.match(str(value))) if value not in (None, "") else False


def _date_text(value) -> str:
    """Expiry dates in the مذكرة are written "2026/9/0" - a real month and
    year with a deliberately meaningless day. They are kept as text,
    exactly as written, because converting them would either invent a day
    the pharmacy never wrote or fail outright on day 0."""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y/%m/%d")
    return _norm(value)


def _excel_serial_to_text(value) -> str:
    """Date cells in the كشف حركات title row come through as raw serials
    (46254) when the sheet was written without a number format."""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, (int, float)) and 20000 < float(value) < 80000:
        try:
            from openpyxl.utils.datetime import from_excel

            return from_excel(float(value)).strftime("%Y/%m/%d")
        except Exception:  # pragma: no cover - defensive only
            return _norm(value)
    return _norm(value)


# --------------------------------------------------------------------------
# كشف حركات  (the one global movements file)
# --------------------------------------------------------------------------

ITEM_KEYWORDS = ["اسم المادة", "اسم الصنف", "الصنف", "المادة"]
TYPE_KEYWORDS = ["نوع الفاتورة", "نوع الحركة", "الحركة", "نوع"]
CENTER_KEYWORDS = ["مركز الكلفة", "مركز التكلفة", "الصيدلية", "الفرع"]
QTY_KEYWORDS = ["عبوة", "الكمية", "الكميه", "كمية"]
CODE_KEYWORDS = ["الرقم", "رقم الصنف", "رقم المادة", "كود"]
PRICE_KEYWORDS = ["السعر", "سعر"]


@dataclass
class MovementRecord:
    code: str
    item_name: str
    invoice_type: str
    cost_center: str
    quantity: float
    price: float


@dataclass
class MovementFile:
    period_text: str = ""
    records: list[MovementRecord] = field(default_factory=list)


def _find_col(header: list[str], keywords: list[str], exclude: set[int] | None = None):
    """First column whose header contains a keyword. Longer keywords are
    tried first so "مركز الكلفة" wins over a bare "الصيدلية" elsewhere in
    the row, and already-claimed columns can be excluded so that "السعر"
    doesn't steal the column "سعر الجرد" already took."""
    exclude = exclude or set()
    for kw in keywords:
        for idx, cell in enumerate(header):
            if idx in exclude:
                continue
            if kw in cell:
                return idx
    return None


def _find_header_row(ws, required: list[list[str]], max_scan=12):
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1
    ):
        header = [_norm_header(c) for c in (row or [])]
        if not any(header):
            continue
        if all(_find_col(header, kws) is not None for kws in required):
            return row_idx, header
    return None, None


def detect_workbook_kind(file_obj) -> str:
    """Tell the three file shapes apart without asking anyone to label
    them. Returns "transfers", "movements", "memo" or "unknown".

    Transfers are checked first: a مناقلات export also carries an item, a
    quantity and a centre, so it satisfies the movements test too, and
    whichever is checked first wins."""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            if _transfer_layout(ws) is not None:
                return "transfers"
        for ws in wb.worksheets:
            row_idx, _ = _find_header_row(ws, [ITEM_KEYWORDS, CENTER_KEYWORDS, QTY_KEYWORDS])
            if row_idx is not None:
                return "movements"
        for ws in wb.worksheets:
            if _memo_layout(ws) is not None:
                return "memo"
        return "unknown"
    finally:
        wb.close()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


FROM_KEYWORDS = ["من مركز", "المركز المرسل", "مركز الارسال", "من صيدلية", "المصدر", "من مستودع", "من فرع"]
TO_KEYWORDS = ["الى مركز", "إلى مركز", "المركز المستلم", "مركز الاستلام", "الى صيدلية",
               "إلى صيدلية", "الوجهة", "الى مستودع", "الى فرع", "إلى فرع"]


def _transfer_layout(ws):
    """A مناقلات export names BOTH ends of the move - where the stock left
    and where it arrived - in two separate columns. That pair is what
    distinguishes it from a sales export, which has only one centre.

    Returns the column map, or None when this sheet is not that shape."""
    row_idx, header = _find_header_row(ws, [ITEM_KEYWORDS, FROM_KEYWORDS, TO_KEYWORDS, QTY_KEYWORDS])
    if row_idx is None:
        return None
    claimed: set[int] = set()
    out = {}
    for key, words in (("item", ITEM_KEYWORDS), ("from", FROM_KEYWORDS),
                       ("to", TO_KEYWORDS), ("qty", QTY_KEYWORDS)):
        col = _find_col(header, words, claimed)
        if col is None:
            return None
        claimed.add(col)
        out[key] = col
    out["code"] = _find_col(header, CODE_KEYWORDS, claimed)
    if out["code"] is not None:
        claimed.add(out["code"])
    out["price"] = _find_col(header, PRICE_KEYWORDS, claimed)
    out["header_row"] = row_idx
    return out


def parse_transfers_workbook(file_obj) -> MovementFile:
    """Read a مناقلات export into movement rows.

    Each transfer becomes TWO rows - a negative one at the branch the
    stock left and a positive one at the branch it reached - so the rest
    of the program needs no special case: the sign already says which
    direction the stock went, exactly as the sales export does for
    returns."""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            layout = _transfer_layout(ws)
            if layout is None:
                continue
            records: list[MovementRecord] = []
            for row in ws.iter_rows(min_row=layout["header_row"] + 1, values_only=True):
                if row is None:
                    continue
                item = _norm(row[layout["item"]]) if layout["item"] < len(row) else ""
                src = _norm(row[layout["from"]]) if layout["from"] < len(row) else ""
                dst = _norm(row[layout["to"]]) if layout["to"] < len(row) else ""
                if not item or (not src and not dst):
                    continue
                qty = abs(_to_float(row[layout["qty"]])) if layout["qty"] < len(row) else 0.0
                if not qty:
                    continue
                code = (normalize_code(row[layout["code"]])
                        if layout["code"] is not None and layout["code"] < len(row) else "")
                price = (_to_float(row[layout["price"]])
                         if layout["price"] is not None and layout["price"] < len(row) else 0.0)
                if src:
                    records.append(MovementRecord(code=code, item_name=item, invoice_type="مناقلة",
                                                  cost_center=src, quantity=-qty, price=price))
                if dst:
                    records.append(MovementRecord(code=code, item_name=item, invoice_type="مناقلة",
                                                  cost_center=dst, quantity=qty, price=price))
            if records:
                return MovementFile(period_text=_read_period(ws, layout["header_row"]),
                                    records=records)
        raise WorkbookFormatError(
            "لم أتمكن من قراءة هذا الملف ككشف مناقلات. الكشف المتوقع يحتوي لكل سطر: "
            "اسم المادة، والمركز المرسل، والمركز المستلم، والكمية."
        )
    finally:
        wb.close()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


def parse_movements_workbook(file_obj) -> MovementFile:
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    try:
        target_ws = None
        header_row_idx = None
        header = None
        for ws in wb.worksheets:
            header_row_idx, header = _find_header_row(
                ws, [ITEM_KEYWORDS, CENTER_KEYWORDS, QTY_KEYWORDS]
            )
            if header_row_idx is not None:
                target_ws = ws
                break
        if target_ws is None:
            raise WorkbookFormatError(
                "لم أتمكن من العثور على أعمدة (اسم المادة / مركز الكلفة / عبوة) في الملف. "
                "تأكد من أنك ترفع كشف الحركات العام وليس مذكرة صيدلية."
            )

        claimed: set[int] = set()
        item_col = _find_col(header, ITEM_KEYWORDS, claimed)
        claimed.add(item_col)
        center_col = _find_col(header, CENTER_KEYWORDS, claimed)
        claimed.add(center_col)
        qty_col = _find_col(header, QTY_KEYWORDS, claimed)
        claimed.add(qty_col)
        type_col = _find_col(header, TYPE_KEYWORDS, claimed)
        if type_col is not None:
            claimed.add(type_col)
        code_col = _find_col(header, CODE_KEYWORDS, claimed)
        if code_col is not None:
            claimed.add(code_col)
        price_col = _find_col(header, PRICE_KEYWORDS, claimed)

        if code_col is None:
            raise WorkbookFormatError(
                "كشف الحركات لا يحتوي عمود (الرقم) الخاص برقم الصنف - وهو العمود الوحيد "
                "الذي تُربط به حركات الصيدلية ببنود مذكرتها. أعد تصدير الكشف مع هذا العمود."
            )

        period_text = _read_period(target_ws, header_row_idx)

        records: list[MovementRecord] = []
        for row in target_ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
            if row is None:
                continue
            code = _norm(row[code_col]) if code_col < len(row) else ""
            item_name = _norm(row[item_col]) if item_col < len(row) else ""
            center = _norm(row[center_col]) if center_col < len(row) else ""
            if not code and not item_name and not center:
                continue
            records.append(
                MovementRecord(
                    code=code,
                    item_name=item_name,
                    invoice_type=_norm(row[type_col]) if type_col is not None and type_col < len(row) else "",
                    cost_center=center,
                    quantity=_to_float(row[qty_col]) if qty_col < len(row) else 0.0,
                    price=_to_float(row[price_col]) if price_col is not None and price_col < len(row) else 0.0,
                )
            )
        if not records:
            raise WorkbookFormatError("كشف الحركات لا يحتوي أي سطر بيانات.")
        return MovementFile(period_text=period_text, records=records)
    finally:
        wb.close()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


def _read_period(ws, header_row_idx) -> str:
    """The rows above the header carry the period as "من تاريخ … الى تاريخ …".

    The labels and their values are not reliably adjacent - in an RTL
    sheet one date sits before its label and the other after it - so
    pairing them by position produces nonsense. Every date-looking value
    in those rows is collected instead and the range is taken from the
    earliest and latest, which is the same answer however the cells are
    ordered. Purely cosmetic (it labels the batch on screen), so anything
    unreadable just yields an empty string."""
    if not any("تاريخ" in _norm(c) for row in ws.iter_rows(
        min_row=1, max_row=max(header_row_idx - 1, 0), values_only=True) for c in (row or [])):
        return ""

    dates = []
    for row in ws.iter_rows(min_row=1, max_row=max(header_row_idx - 1, 0), values_only=True):
        for cell in row or []:
            if isinstance(cell, (datetime, date)) or (
                isinstance(cell, (int, float))
                and not isinstance(cell, bool)
                and 20000 < float(cell) < 80000
            ):
                text = _excel_serial_to_text(cell)
                if text:
                    dates.append(text)
    if not dates:
        return ""
    if len(dates) == 1:
        return f"بتاريخ {dates[0]}"
    return f"من {min(dates)} إلى {max(dates)}"


# --------------------------------------------------------------------------
# مذكرة  (one per pharmacy)
# --------------------------------------------------------------------------

MEMO_NUMBER_RE = re.compile(r"(?:رقم\s*المذكرة|مذكرة)\s*[:#]?\s*(\d+)")


@dataclass
class MemoItemRecord:
    row_order: int
    code: str
    item_name: str
    quantity: float
    price: float
    expiry_text: str


@dataclass
class MemoFile:
    number: str = ""
    items: list[MemoItemRecord] = field(default_factory=list)
    #: Some مذكرة exports carry the branch name in a column of their own.
    #: When present it is offered as a cross-check that the file is being
    #: attached to the right pharmacy - a مذكرة filed under the wrong
    #: branch produces a confidently wrong report rather than an error.
    cost_center: str = ""


def _column_profile(rows, width):
    """Per-column statistics used to identify what each column really is."""
    stats = []
    for col in range(width):
        values = [r[col] for r in rows if col < len(r) and r[col] not in (None, "")]
        texts = [_norm(v) for v in values if not _looks_numeric(v) and not _looks_like_date(v)]
        numbers = [_to_float(v) for v in values if _looks_numeric(v)]
        dates = [v for v in values if _looks_like_date(v)]
        counts = {}
        for t in texts:
            counts[t] = counts.get(t, 0) + 1
        stats.append({
            "i": col,
            "texts": len(texts),
            "numbers": len(numbers),
            "dates": len(dates),
            "avg_len": (sum(len(t) for t in texts) / len(texts)) if texts else 0.0,
            "top_share": (max(counts.values()) / len(texts)) if texts else 0.0,
            "distinct_ratio": (len(set(numbers)) / len(numbers)) if numbers else 0.0,
            "int_share": (sum(1 for v in numbers if float(v).is_integer()) / len(numbers)) if numbers else 0.0,
            "mean": (sum(numbers) / len(numbers)) if numbers else 0.0,
        })
    return stats


def _memo_layout(ws, sample_limit=400):
    """Identify every column of a مذكرة from the shape of its own data.

    Real مذكرة files share almost nothing. Across the nine in use: some
    carry an item-code column and two carry none at all; the word "الرقم"
    heads the item code in one file and the QUANTITY in another; one file
    puts a cost-centre column between the name and the numbers; the
    total-cost column sits before the expiry date in one file and after it
    in the next; and two files have no header row whatsoever. Matching on
    header words, or on position, breaks on at least three of them.

    So each column is classified by what its data looks like:

      * cost centre - a text column where ONE value repeats on nearly
        every row. A genuine item name never does that.
      * name        - the remaining text column with the longest values.
      * expiry      - the column shaped like a date.
      * code        - integers that are nearly all distinct. Quantities
        repeat endlessly (1, 1, 2, 1...), item codes do not.
      * qty/price/total - resolved by finding which ordered triple
        satisfies ``total == qty x price`` on nearly every row. That
        identity is self-verifying: it either holds across hundreds of
        rows or it does not, so it settles the mapping far more reliably
        than any header word could. Files with no total column fall back
        to header keywords, then to magnitude (quantities are small and
        often fractional, prices are not).

    Returns a dict of column indexes, or None when the sheet is not a
    مذكرة at all."""
    rows = []
    for row in ws.iter_rows(min_row=1, max_row=sample_limit, values_only=True):
        if row and sum(1 for c in row if c not in (None, "")) >= 3:
            rows.append(list(row))
    if len(rows) < 3:
        return None
    width = max(len(r) for r in rows)
    stats = _column_profile(rows, width)

    center_col = None
    for s in stats:
        if s["texts"] >= 5 and s["top_share"] > 0.9 and s["avg_len"] >= 8:
            center_col = s["i"]
            break

    candidates = [s for s in stats if s["i"] != center_col and s["texts"] >= 3]
    if not candidates:
        return None
    name_col = max(candidates, key=lambda s: (s["avg_len"], s["texts"]))["i"]

    date_stat = max(stats, key=lambda s: s["dates"])
    date_col = date_stat["i"] if date_stat["dates"] >= 3 else None

    claimed = {c for c in (center_col, name_col, date_col) if c is not None}
    numeric = [s for s in stats if s["i"] not in claimed and s["numbers"] >= 3]

    code_col = None
    for s in sorted(numeric, key=lambda s: -s["distinct_ratio"]):
        if s["int_share"] > 0.98 and s["distinct_ratio"] > 0.85:
            code_col = s["i"]
            break

    rest = [s["i"] for s in numeric if s["i"] != code_col]
    qty_col = price_col = None
    best = 0.0
    for total in rest:
        for qty in rest:
            for price in rest:
                if len({total, qty, price}) != 3:
                    continue
                hits = tested = 0
                for r in rows:
                    if not all(i < len(r) and _looks_numeric(r[i]) for i in (qty, price, total)):
                        continue
                    tested += 1
                    if abs(_to_float(r[qty]) * _to_float(r[price]) - _to_float(r[total])) < 0.02:
                        hits += 1
                score = (hits / tested) if tested >= 5 else 0.0
                if score > best:
                    best, qty_col, price_col = score, qty, price
    if best < 0.8:
        qty_col = price_col = None

    if qty_col is None and rest:
        header = {}
        for r in rows[:4]:
            for i, v in enumerate(r):
                text = _norm_header(v)
                if text and i not in header:
                    header[i] = text

        def by_header(words, pool):
            for w in words:
                for i in pool:
                    if w in header.get(i, ""):
                        return i
            return None

        qty_col = by_header(["العدد", "الكمية", "الكميه", "عدد"], rest)
        price_col = by_header(["سعر", "كلفة", "الكلفة"], [i for i in rest if i != qty_col])
        if qty_col is None or price_col is None:
            ordered = sorted(rest, key=lambda i: stats[i]["mean"])
            if len(ordered) >= 2:
                qty_col, price_col = ordered[0], ordered[-1]
            elif len(ordered) == 1:
                qty_col = ordered[0]

    if name_col is None:
        return None
    return {
        "code": code_col, "name": name_col, "qty": qty_col,
        "price": price_col, "date": date_col, "center": center_col,
    }


def parse_memo_workbook(file_obj) -> MemoFile:
    """Read one مذكرة into rows, preserving the file's own order.

    A row is kept whenever it has a name - even with a blank quantity or
    a missing price. The owner's own reference report keeps those rows
    too, and dropping them silently is worse than carrying a zero: a row
    that vanishes between the مذكرة and the report looks like an item that
    was never delivered."""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            layout = _memo_layout(ws)
            if layout is None:
                continue
            name_col = layout["name"]
            code_col, qty_col = layout["code"], layout["qty"]
            price_col, date_col = layout["price"], layout["date"]
            center_col = layout["center"]

            number = ""
            center_name = ""
            items: list[MemoItemRecord] = []
            order = 0
            for row in ws.iter_rows(values_only=True):
                if row is None:
                    continue
                if not number:
                    for cell in row:
                        match = MEMO_NUMBER_RE.search(_norm(cell))
                        if match:
                            number = match.group(1)
                            break
                name = _norm(row[name_col]) if name_col < len(row) else ""
                if not name or _looks_numeric(name) or _looks_like_date(name):
                    continue
                # Skip the header row itself, which also holds text in the
                # name column ("الاسم", "الصنف", ...).
                if _norm_header(name) in _MEMO_HEADER_WORDS:
                    continue
                # Skip title banners ("رقم المذكرة 204", "تواريخ قريبة من
                # الانتهاء"). They sit in the name column like an item, so
                # the only thing separating them from a real row is that a
                # real row always carries at least one number of its own -
                # a code, a quantity or a price.
                if MEMO_NUMBER_RE.search(name):
                    continue
                has_number = any(
                    col is not None and col < len(row) and _looks_numeric(row[col])
                    for col in (code_col, qty_col, price_col)
                )
                if not has_number:
                    continue
                if center_col is not None and center_col < len(row) and not center_name:
                    center_name = _norm(row[center_col])
                order += 1
                items.append(
                    MemoItemRecord(
                        row_order=order,
                        code=normalize_code(row[code_col]) if code_col is not None and code_col < len(row) else "",
                        item_name=name,
                        quantity=_to_float(row[qty_col]) if qty_col is not None and qty_col < len(row) else 0.0,
                        price=_to_float(row[price_col]) if price_col is not None and price_col < len(row) else 0.0,
                        expiry_text=_date_text(row[date_col]) if date_col is not None and date_col < len(row) else "",
                    )
                )
            if items:
                return MemoFile(number=number, items=items, cost_center=center_name)
        raise WorkbookFormatError(
            "لم أتمكن من قراءة هذا الملف كمذكرة. المذكرة المتوقعة تحتوي لكل سطر على الأقل: "
            "اسم المادة والعدد والسعر (ورقم الصنف وتاريخ الصلاحية إن وُجدا)."
        )
    finally:
        wb.close()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


#: Words that head a column rather than name a product - a row whose name
#: cell holds one of these is the sheet's header row, not an item.
_MEMO_HEADER_WORDS = {
    "الاسم", "اسم المادة", "اسم الصنف", "الصنف", "المادة", "البيان",
    "الرقم", "العدد", "الكمية", "السعر", "الكلفة", "كلفة", "التاريخ",
    "تاريخ الصلاحية", "تواريخ صلاحية", "ملاحظات", "مركز كلفة", "مركز الكلفة",
}


def normalize_code(value) -> str:
    """The single join key between the two files. The same code arrives as
    2786 from one export and 2786.0 from the other, so both sides are put
    through this before they are ever compared."""
    text = _norm(value)
    if not text:
        return ""
    num = _to_float(text, default=None) if _looks_numeric(text) else None
    if num is None:
        return text
    return str(int(num)) if float(num).is_integer() else str(num)
