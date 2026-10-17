"""The comparison itself: one كشف حركات against every pharmacy's مذكرة.

Output shape and every rule below follow the owner's approved reference
report (تقرير حركة ورصيد كل الصيدليات). Per مذكرة row the report answers
four things - how much was SOLD, how much was TRANSFERRED OUT, what is
LEFT, and whether the item moved at all (متحرك) or not (راكد).

The rules, and why each is what it is:

1. **Matching: code first, name second.** The nine real مذكرة files are
   not uniform - two of them (رانيا، احلام) carry no item-code column at
   all. A code-only join silently returns zero for every row of those
   files, which reads as "this branch sold nothing" rather than as "this
   file could not be matched". So a row joins on its code when it has one
   AND that code exists in the movements; otherwise it joins on the item
   name. Checked against the real data: where both keys exist they select
   exactly the same movement rows, so the fallback costs no accuracy.

2. **Sale and transfer are different questions and stay in different
   columns.** Selling an item and shipping it to another branch both
   empty the shelf, but only one of them is a sale. Netting them into a
   single figure - which an earlier version did - destroys the only
   number that says whether the branch is actually selling.

3. **Returns reduce the sale.** The export writes مردود مبيع with a
   negative quantity, so the net sale is a plain signed sum.

4. **الكمية المتبقية = العدد − المباع − المتناقل.** Taken from the
   reference, and it can legitimately go negative when more moved than
   the مذكرة lists; such rows are flagged rather than clamped.

5. **راكد vs متحرك:** an item is متحرك if it sold OR transferred, and
   راكد only when neither happened. راكد is the figure the owner acts on,
   so it means "nothing happened to this stock at all".

6. **كلفة اجمالية = العدد × الكلفة الوسطية**, always computed. The
   reference workbook leaves this column empty for four of the nine
   pharmacies even though it has both inputs, which zeroes their value
   totals and understates the group total; computing it restores them.

Nothing is persisted: a report is recomputed from the stored rows every
time it is opened, so correcting a مذكرة fixes every report that uses it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from ..models import MovementRow, Pharmacy

RETURN_HINTS = ("مردود", "مرتجع", "راجع")
# Stems, not whole words. The live export writes the type as "مناقلات"
# (plural), and neither "مناقلة" nor "نقل" is a substring of it - the
# plural drops the ـة and keeps an alef between the ن and the ق. Matching
# on the stem "مناق" covers مناقلة / مناقله / مناقلات / المناقلات alike,
# and getting this wrong is silent: an unrecognised type falls through to
# the sales bucket and the transfer column stays zero.
TRANSFER_HINTS = ("مناق", "ناقل", "نقل", "تحويل", "ترحيل")
SALE_HINTS = ("مبيع", "بيع", "فاتورة")

TATWEEL = "ـ"
_DIACRITICS = re.compile(r"[ً-ْٰ]")
_PUNCT = re.compile(r"[^\w؀-ۿ/%.+]+")


def normalize_name(value) -> str:
    """Key used when an item has to be matched by name.

    Kept deliberately light: whitespace, tatweel and diacritics collapse,
    and the alef/ya/hamza families fold together, because those vary
    between the two exports for the same product. Nothing else is
    touched - dose numbers, slashes and percent signs are what tell two
    strengths of the same drug apart, and folding them would merge
    products that must stay separate."""
    text = str(value or "").replace(TATWEEL, "")
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه")
    text = text.replace("\\", "/")
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def classify_type(invoice_type: str) -> str:
    """Bucket a movement into sale / return / transfer.

    An unrecognised type keeps its own name rather than being forced into
    a bucket, so a type nobody anticipated shows up in the report as
    itself instead of quietly inflating sales."""
    text = (invoice_type or "").strip()
    if not text:
        return "غير محدد"
    if any(h in text for h in RETURN_HINTS):
        return "مردود"
    if any(h in text for h in TRANSFER_HINTS):
        return "مناقلة"
    if any(h in text for h in SALE_HINTS):
        return "مبيع"
    return text


@dataclass
class Bucket:
    """Aggregated movements for one item at one pharmacy."""
    sold: float = 0.0          # net of returns
    transfer_out: float = 0.0  # left the branch
    transfer_in: float = 0.0   # arrived at the branch
    rows: int = 0
    types: dict = field(default_factory=dict)

    def add(self, qty: float, invoice_type: str):
        kind = classify_type(invoice_type)
        self.rows += 1
        self.types[kind] = self.types.get(kind, 0.0) + qty
        if kind == "مناقلة":
            # Direction comes from the sign the export itself writes: a
            # movement that reduces the branch's stock is "خارج". Both
            # directions are kept so an inbound transfer can never be
            # mistaken for stock that left.
            if qty < 0:
                self.transfer_out += -qty
            else:
                self.transfer_in += qty
        else:
            # Sales and returns (negative) net against each other.
            self.sold += qty


@dataclass
class ResultRow:
    row_order: int
    code: str
    item_name: str
    quantity: float          # العدد / الكمية الحالية بالصيدلية
    price: float             # الكلفة الوسطية
    expiry_text: str
    sold: float              # الكمية المباعة (صافي)
    transfer_out: float      # الكمية المتناقلة (خارج)
    transfer_in: float = 0.0
    matched_rows: int = 0
    matched_by: str = ""     # "code" | "name" | ""
    is_duplicate: bool = False
    breakdown: dict = field(default_factory=dict)

    @property
    def total_cost(self) -> float:
        return self.quantity * self.price

    @property
    def moved_qty(self) -> float:
        """عدد العبوات المتحركة: how many packages of this item actually
        left the shelf, sold and transferred together.

        Kept distinct from the item COUNT used for راكد/متحرك: one is "how
        many products moved at all", this is "how much stock moved", and
        reading one as the other is the easiest mistake to make on this
        report."""
        return round(self.sold + self.transfer_out, 6)

    @property
    def remaining_raw(self) -> float:
        """The arithmetic as it falls out: العدد − المباع − المتناقل.

        Can go below zero when more moved than the مذكرة lists. Kept
        internally because it is the ONLY evidence that happened - it is
        never reported."""
        return round(self.quantity - self.sold - self.transfer_out + self.transfer_in, 6)

    @property
    def remaining(self) -> float:
        """الكمية المتبقية as reported: never negative.

        A shelf cannot hold less than nothing, so once an item has sold or
        transferred more than the مذكرة lists, the honest remainder is
        zero, not a negative count.

        Clamping hides the discrepancy from the number but NOT from the
        report: `oversold` and `shortfall` still read the raw value, the
        row is still coloured and still carries «المتحرك أكبر من الموجود»
        with the exact shortfall in its ملاحظة, and the branch's warning
        still counts it. The figure is cleaned up; the problem is not
        swept away."""
        return max(0.0, self.remaining_raw)

    @property
    def shortfall(self) -> float:
        """How many packages moved beyond what the مذكرة listed."""
        return round(-self.remaining_raw, 6) if self.remaining_raw < 0 else 0.0

    @property
    def sold_flag(self) -> str:
        return "نعم" if self.sold > 0 else "لا"

    @property
    def transfer_flag(self) -> str:
        return "نعم" if self.transfer_out > 0 else "لا"

    @property
    def moved(self) -> bool:
        return self.sold > 0 or self.transfer_out > 0

    @property
    def state(self) -> str:
        return "متحرك" if self.moved else "راكد"

    @property
    def oversold(self) -> bool:
        # Reads the raw value on purpose: `remaining` is clamped at zero,
        # so testing it here would make this flag permanently false.
        return self.remaining_raw < 0

    @property
    def remaining_value(self) -> float:
        return self.remaining * self.price

    @property
    def state_key(self) -> str:
        """Row styling, worst first - a number that cannot be trusted
        outranks one that is merely bad."""
        if self.oversold:
            return "bad"
        if self.is_duplicate:
            return "warn"
        if not self.moved:
            return "idle"
        if self.remaining == 0:
            return "done"
        return ""

    @property
    def note(self) -> str:
        bits = []
        # "راكد" is deliberately absent: the الحالة column already says it,
        # and repeating it would bury the exceptions this column exists for.
        if self.oversold:
            # The clamped column now reads 0, so the size of the gap is
            # stated here or it is lost entirely.
            bits.append(f"المتحرك أكبر من الموجود بـ {self.shortfall:g} (المتبقي صُفِّر)")
        if self.is_duplicate:
            bits.append("مكرر بالمذكرة")
        if self.moved and not self.oversold and self.remaining == 0:
            bits.append("نفد بالكامل")
        if self.transfer_in:
            bits.append(f"وارد مناقلة {self.transfer_in:g}")
        if self.quantity and not self.price:
            bits.append("بلا كلفة بالمذكرة")
        return " · ".join(bits)


@dataclass
class ExtraRow:
    """Something that moved at this branch and its مذكرة never listed."""
    code: str
    item_name: str
    sold: float
    transfer_out: float

    @property
    def moved_qty(self) -> float:
        return round(self.sold + self.transfer_out, 6)


@dataclass
class PharmacyResult:
    pharmacy: Pharmacy
    memo = None
    rows: list[ResultRow] = field(default_factory=list)
    extras: list[ExtraRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    has_memo: bool = True
    in_movements: bool = True
    matched_by_code: int = 0
    matched_by_name: int = 0

    # -- counts -----------------------------------------------------------
    @property
    def item_count(self):
        return len(self.rows)

    @property
    def stagnant(self):
        return [r for r in self.rows if not r.moved]

    @property
    def moving(self):
        return [r for r in self.rows if r.moved]

    @property
    def stagnant_count(self):
        return len(self.stagnant)

    @property
    def moving_count(self):
        return len(self.moving)

    @property
    def stagnant_qty(self):
        """Packages sitting dead: the مذكرة quantity of every راكد item.
        Counting items answers "how many products are stuck", this answers
        "how much stock is stuck" - and a branch can look fine on one and
        bad on the other."""
        return sum(r.quantity for r in self.stagnant)

    @property
    def moving_qty(self):
        """مذكرة quantity of the items that moved - NOT how much of them
        moved. That figure is `total_moved_qty` (مباع + متناقل)."""
        return sum(r.quantity for r in self.moving)

    @property
    def stagnant_value(self):
        return sum(r.total_cost for r in self.stagnant)

    @property
    def moving_value(self):
        return sum(r.total_cost for r in self.moving)

    @property
    def total_value(self):
        return sum(r.total_cost for r in self.rows)

    @property
    def stagnant_pct(self):
        return (self.stagnant_count / self.item_count * 100) if self.item_count else 0.0

    # -- quantities --------------------------------------------------------
    @property
    def total_pieces(self):
        return sum(r.quantity for r in self.rows)

    @property
    def total_sold(self):
        return sum(r.sold for r in self.rows)

    @property
    def total_transfer(self):
        return sum(r.transfer_out for r in self.rows)

    @property
    def total_moved_qty(self):
        """Packages moved at this branch - the sum of المباع and المتناقل.
        Deliberately NOT the same number as `moving_count`, which counts
        items rather than packages."""
        return sum(r.moved_qty for r in self.rows)

    @property
    def total_remaining(self):
        """Sum of the clamped remainders, so a single over-moved item can
        no longer eat into another item's genuine stock in the total."""
        return sum(r.remaining for r in self.rows)

    @property
    def total_shortfall(self):
        """Packages that moved beyond what the مذكرة listed, across the
        branch - the quantity the clamp removed from view."""
        return sum(r.shortfall for r in self.rows)

    @property
    def oversold_count(self):
        return sum(1 for r in self.rows if r.oversold)

    @property
    def duplicate_count(self):
        return sum(1 for r in self.rows if r.is_duplicate)

    @property
    def no_price_count(self):
        return sum(1 for r in self.rows if r.quantity and not r.price)

    @property
    def status(self):
        if not self.has_memo:
            return "no-memo"
        if not self.in_movements:
            return "no-movements"
        if self.oversold_count or self.duplicate_count:
            return "warn"
        if self.item_count and self.stagnant_pct >= 70:
            return "slow"
        return "ok"

    @property
    def sorted_rows(self):
        """The reference orders every sheet راكد first then متحرك, each
        block by total cost descending - most expensive dead stock at the
        top, which is the order the owner reads it in."""
        return sorted(self.rows, key=lambda r: (r.moved, -r.total_cost, r.item_name))


@dataclass
class Report:
    batch = None
    has_transfers = True
    results: list[PharmacyResult] = field(default_factory=list)
    unknown_centers: list[tuple] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def with_memo(self):
        return [r for r in self.results if r.has_memo]

    @property
    def ranked(self):
        """Pharmacies ordered by the share of their stock that is dead -
        worst first, which is the reference's own ordering."""
        return sorted(self.with_memo, key=lambda r: -r.stagnant_pct)

    @property
    def total_items(self):
        return sum(r.item_count for r in self.with_memo)

    @property
    def total_stagnant(self):
        return sum(r.stagnant_count for r in self.with_memo)

    @property
    def total_moving(self):
        return sum(r.moving_count for r in self.with_memo)

    @property
    def total_stagnant_value(self):
        return sum(r.stagnant_value for r in self.with_memo)

    @property
    def total_moving_value(self):
        return sum(r.moving_value for r in self.with_memo)

    @property
    def total_sold(self):
        return sum(r.total_sold for r in self.with_memo)

    @property
    def total_transfer(self):
        return sum(r.total_transfer for r in self.with_memo)

    @property
    def total_moved_qty(self):
        return sum(r.total_moved_qty for r in self.with_memo)

    @property
    def total_pieces(self):
        return sum(r.total_pieces for r in self.with_memo)

    @property
    def total_stagnant_qty(self):
        return sum(r.stagnant_qty for r in self.with_memo)

    @property
    def total_moving_qty(self):
        return sum(r.moving_qty for r in self.with_memo)

    @property
    def total_remaining(self):
        return sum(r.total_remaining for r in self.with_memo)

    @property
    def total_shortfall(self):
        return sum(r.total_shortfall for r in self.with_memo)

    @property
    def stagnant_pct(self):
        return (self.total_stagnant / self.total_items * 100) if self.total_items else 0.0

    @property
    def problem_count(self):
        return len(self.problems) + sum(len(r.problems) for r in self.results)


def compute_report(batch, pharmacies=None) -> Report:
    owner = batch.owner
    if pharmacies is None:
        pharmacies = list(
            Pharmacy.objects.filter(owner=owner).prefetch_related("memos__items")
        )

    # ---- pass 1: aggregate every movement, by code and by name ----------
    by_code: dict[tuple, Bucket] = defaultdict(Bucket)
    by_name: dict[tuple, Bucket] = defaultdict(Bucket)
    code_names: dict[tuple, str] = {}
    branch_rows: dict[str, int] = defaultdict(int)

    rows = MovementRow.objects.filter(batch=batch).values_list(
        "code", "cost_center", "quantity", "invoice_type", "item_name"
    )
    for code, center, qty, invoice_type, item_name in rows.iterator(chunk_size=5000):
        branch_rows[center] += 1
        qty = qty or 0.0
        if code:
            key = (center, str(code))
            by_code[key].add(qty, invoice_type)
            code_names.setdefault(key, item_name)
        name_key = normalize_name(item_name)
        if name_key:
            by_name[(center, name_key)].add(qty, invoice_type)

    # ---- pass 2: walk each pharmacy's memo -------------------------------
    results: list[PharmacyResult] = []
    for pharmacy in sorted(pharmacies, key=lambda p: (0 if p.current_memo else 1, p.label)):
        result = PharmacyResult(pharmacy=pharmacy)
        memo = pharmacy.current_memo
        result.memo = memo
        center = pharmacy.cost_center
        result.in_movements = branch_rows.get(center, 0) > 0

        if memo is None:
            result.has_memo = False
            result.problems.append("لا توجد مذكرة مرفوعة لهذه الصيدلية - لم تتم أي مطابقة لها.")
            results.append(result)
            continue

        if not result.in_movements:
            result.problems.append(
                f"مركز الكلفة «{center}» غير موجود إطلاقاً في كشف الحركات - تحقق من تطابق "
                "الاسم حرفياً، وإلا ستظهر كل بنود المذكرة وكأنها راكدة."
            )

        items = list(memo.items.all())
        seen_codes: dict[str, int] = defaultdict(int)
        seen_names: dict[str, int] = defaultdict(int)
        for item in items:
            if item.code:
                seen_codes[item.code] += 1
            seen_names[normalize_name(item.item_name)] += 1

        used_code_keys, used_name_keys = set(), set()
        for item in items:
            name_key = normalize_name(item.item_name)
            bucket, matched_by = Bucket(), ""
            if item.code and (center, item.code) in by_code:
                bucket = by_code[(center, item.code)]
                matched_by = "code"
                used_code_keys.add((center, item.code))
                used_name_keys.add((center, name_key))
            elif (center, name_key) in by_name:
                bucket = by_name[(center, name_key)]
                matched_by = "name"
                used_name_keys.add((center, name_key))

            duplicate = (
                (item.code and seen_codes[item.code] > 1)
                or (not item.code and seen_names[name_key] > 1)
            )
            if matched_by == "code":
                result.matched_by_code += 1
            elif matched_by == "name":
                result.matched_by_name += 1

            result.rows.append(
                ResultRow(
                    row_order=item.row_order,
                    code=item.code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    price=item.price,
                    expiry_text=item.expiry_text,
                    sold=round(bucket.sold, 6),
                    transfer_out=round(bucket.transfer_out, 6),
                    transfer_in=round(bucket.transfer_in, 6),
                    matched_rows=bucket.rows,
                    matched_by=matched_by,
                    is_duplicate=bool(duplicate),
                    breakdown={k: round(v, 6) for k, v in bucket.types.items()},
                )
            )

        # Movements at this branch with no memo row to land on.
        for (branch, code), bucket in by_code.items():
            if branch != center or (branch, code) in used_code_keys:
                continue
            name = code_names.get((branch, code), "")
            if (branch, normalize_name(name)) in used_name_keys:
                continue
            if bucket.sold == 0 and bucket.transfer_out == 0:
                continue
            result.extras.append(
                ExtraRow(code=code, item_name=name,
                         sold=round(bucket.sold, 6), transfer_out=round(bucket.transfer_out, 6))
            )
        result.extras.sort(key=lambda e: -(abs(e.sold) + abs(e.transfer_out)))

        _add_problems(result, items)
        results.append(result)

    # The quietest way this report can mislead: a sales-only export makes
    # every "متناقل" figure zero, which reads as "nothing was transferred"
    # when it actually means "this file has no transfers in it". Said out
    # loud, at the top, rather than left to be inferred.
    types = {t for t, _ in batch.movement_types if t}
    if not any(classify_type(t) == "مناقلة" for t in types):
        report_no_transfers = (
            "الملفات المرفوعة لهذا الكشف لا تحتوي أي حركة مناقلة - أنواع الحركات الموجودة فيها: "
            + "، ".join(sorted(types) or ["لا شيء"])
            + ". لذلك عمود «الكمية المتناقلة (خارج)» صفر في كل الأسطر، وهذا ليس نتيجة بل غياب "
            "بيانات: ملف الموسع يصدّر المبيع والمردود فقط. أضف كشف المناقلات من برنامج البيان "
            "وارفعه مع الموسع لتظهر المناقلات."
        )
    else:
        report_no_transfers = None

    report = Report(results=results)
    report.batch = batch
    report.has_transfers = report_no_transfers is None
    if report_no_transfers:
        report.problems.append(report_no_transfers)

    known = {p.cost_center for p in pharmacies}
    report.unknown_centers = sorted(
        ((c, n) for c, n in branch_rows.items() if c and c not in known), key=lambda p: -p[1]
    )
    if report.unknown_centers:
        names = "، ".join(f"{c} ({n} حركة)" for c, n in report.unknown_centers[:12])
        report.problems.append(
            f"{len(report.unknown_centers)} مركز كلفة موجود في كشف الحركات وليس له صيدلية "
            f"معرَّفة عندك (ولا مذكرة): {names}"
        )
    missing = [r.pharmacy.label for r in results if not r.has_memo]
    if missing:
        report.problems.append(
            f"{len(missing)} صيدلية بلا مذكرة مرفوعة - غير محسوبة إطلاقاً في هذا التقرير: "
            + "، ".join(missing)
        )
    if not any(r.has_memo for r in results):
        report.problems.append("لم تُرفع أي مذكرة بعد - ارفع مذكرة واحدة على الأقل لتظهر النتيجة.")
    return report


def _add_problems(result: PharmacyResult, items):
    unmatched = [r for r in result.rows if not r.matched_by]
    if result.in_movements and len(unmatched) == len(result.rows) and result.rows:
        result.problems.append(
            "لم يُطابَق أي بند من المذكرة مع حركات هذه الصيدلية رغم وجود حركات لها في الكشف - "
            "غالباً المذكرة مرفوعة تحت الصيدلية الخطأ، أو أسماء/أرقام الأصناف من نظام مختلف."
        )
    if result.oversold_count:
        result.problems.append(
            f"{result.oversold_count} صنفاً كميته المتحركة (مبيع + مناقلة) أكبر من عدده "
            f"بالمذكرة بمجموع {result.total_shortfall:g} عبوة - المتبقي لهذه الأصناف "
            "مُصفَّر في التقرير (لا يُعرض بالسالب)، والسبب إما حركة من دفعة غير مذكورة "
            "أو خطأ بالعدد. الأصناف مؤشَّرة بعمود الملاحظة مع مقدار الفرق."
        )
    if result.duplicate_count:
        result.problems.append(
            f"{result.duplicate_count} سطراً مكرراً داخل المذكرة نفسها (نفس الصنف أكثر من مرة) - "
            "كل سطر منها يعرض كامل حركة الصنف، لذا مجاميع هذه الأصناف مضخّمة."
        )
    if result.no_price_count:
        result.problems.append(
            f"{result.no_price_count} صنفاً بلا كلفة في المذكرة - كميته محسوبة لكن قيمته تظهر صفراً."
        )
    inbound = sum(1 for r in result.rows if r.transfer_in)
    if inbound:
        result.notes.append(
            f"{inbound} صنفاً وصلته مناقلة واردة (زيادة على عدد المذكرة) - محسوبة ضمن المتبقي."
        )
    if result.matched_by_name and not result.matched_by_code:
        result.notes.append(
            "مذكرة هذه الصيدلية بلا عمود رقم صنف، فتمت المطابقة باسم الصنف."
        )
    if result.extras:
        result.notes.append(
            f"{len(result.extras)} صنفاً تحرّك في هذه الصيدلية وغير مذكور في مذكرتها "
            "(طبيعي: المذكرة دفعة محددة لا كل ما تبيعه الصيدلية)."
        )
