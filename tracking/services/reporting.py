"""Core business logic: for a monthly upload, work out - per category you
decided to track that month - how much quantity pharmacies sold from the
exact product(s) you told them to sell (target items) versus how much they
sold from something else tagged under the same category (alternatives).

This mirrors the "أصناف الأورانج" report style: the highlighted / target
rows are exactly the products listed for that category in the target-items
workbook, everything else sharing the same "الشروحات 5" tag is an
alternative the pharmacy chose instead.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ItemStat:
    item_name: str
    quantity: float = 0.0
    is_target: bool = False


@dataclass
class PharmacyStat:
    pharmacy_name: str
    target_qty: float = 0.0
    alt_qty: float = 0.0

    @property
    def total_qty(self):
        return self.target_qty + self.alt_qty

    @property
    def target_pct(self):
        return (self.target_qty / self.total_qty * 100) if self.total_qty else 0.0


@dataclass
class CategoryStat:
    category: object  # Category model instance
    target_qty: float = 0.0
    alt_qty: float = 0.0
    items: dict = field(default_factory=dict)  # item_name -> ItemStat
    pharmacies: dict = field(default_factory=dict)  # pharmacy_name -> PharmacyStat
    items_by_pharmacy: dict = field(default_factory=lambda: defaultdict(dict))  # pharmacy -> {item_name: ItemStat}

    @property
    def total_qty(self):
        return self.target_qty + self.alt_qty

    @property
    def target_pct(self):
        return (self.target_qty / self.total_qty * 100) if self.total_qty else 0.0

    def sorted_items(self):
        return sorted(self.items.values(), key=lambda i: i.quantity, reverse=True)

    def sorted_pharmacies(self):
        return sorted(self.pharmacies.values(), key=lambda p: p.total_qty, reverse=True)

    def sorted_items_for_pharmacy(self, pharmacy_name):
        items = self.items_by_pharmacy.get(pharmacy_name, {})
        return sorted(items.values(), key=lambda i: i.quantity, reverse=True)


@dataclass
class ReportResult:
    categories: list  # list[CategoryStat], sorted by total quantity desc
    total_target_qty: float
    total_alt_qty: float
    total_tracked_qty: float
    total_untracked_qty: float
    grand_total_qty: float
    untagged_target_sales: list  # diagnostics: target items sold but never tagged in the sheet

    @property
    def target_pct(self):
        return (self.total_target_qty / self.total_tracked_qty * 100) if self.total_tracked_qty else 0.0


def compute_report(upload) -> ReportResult:
    categories = list(upload.categories.prefetch_related("target_items").order_by("order", "name"))
    category_by_name = {c.name.strip(): c for c in categories}

    # item_name -> category name it is a *target* for, this month.
    target_item_to_category: dict[str, str] = {}
    for cat in categories:
        for ti in cat.target_items.all():
            target_item_to_category[ti.item_name.strip()] = cat.name.strip()

    stats: dict[str, CategoryStat] = {
        name: CategoryStat(category=cat) for name, cat in category_by_name.items()
    }

    grand_total_qty = 0.0
    total_tracked_qty = 0.0
    untagged_target_rows = defaultdict(float)  # (item_name) -> qty, sold but raw_category blank/other

    rows = upload.sales_rows.values_list("item_name", "pharmacy_name", "quantity", "raw_category")
    for item_name, pharmacy_name, quantity, raw_category in rows:
        grand_total_qty += quantity
        item_name = (item_name or "").strip()
        pharmacy_name = (pharmacy_name or "").strip() or "(بدون اسم صيدلية)"
        raw_category = (raw_category or "").strip()

        resolved_category = None
        is_target = False

        if item_name in target_item_to_category:
            resolved_category = target_item_to_category[item_name]
            is_target = True
            if not raw_category or raw_category not in category_by_name:
                untagged_target_rows[item_name] += quantity
        elif raw_category and raw_category in category_by_name:
            resolved_category = raw_category
            is_target = False

        if resolved_category is None:
            continue

        total_tracked_qty += quantity
        cat_stat = stats[resolved_category]

        if is_target:
            cat_stat.target_qty += quantity
        else:
            cat_stat.alt_qty += quantity

        item_stat = cat_stat.items.get(item_name)
        if item_stat is None:
            item_stat = ItemStat(item_name=item_name, is_target=is_target)
            cat_stat.items[item_name] = item_stat
        item_stat.quantity += quantity
        item_stat.is_target = item_stat.is_target or is_target

        ph_stat = cat_stat.pharmacies.get(pharmacy_name)
        if ph_stat is None:
            ph_stat = PharmacyStat(pharmacy_name=pharmacy_name)
            cat_stat.pharmacies[pharmacy_name] = ph_stat
        if is_target:
            ph_stat.target_qty += quantity
        else:
            ph_stat.alt_qty += quantity

        ph_items = cat_stat.items_by_pharmacy[pharmacy_name]
        ph_item_stat = ph_items.get(item_name)
        if ph_item_stat is None:
            ph_item_stat = ItemStat(item_name=item_name, is_target=is_target)
            ph_items[item_name] = ph_item_stat
        ph_item_stat.quantity += quantity
        ph_item_stat.is_target = ph_item_stat.is_target or is_target

    ordered = sorted(stats.values(), key=lambda c: c.total_qty, reverse=True)

    total_target_qty = sum(c.target_qty for c in ordered)
    total_alt_qty = sum(c.alt_qty for c in ordered)

    untagged_target_sales = sorted(
        ({"item_name": k, "quantity": v} for k, v in untagged_target_rows.items()),
        key=lambda d: d["quantity"],
        reverse=True,
    )

    return ReportResult(
        categories=ordered,
        total_target_qty=total_target_qty,
        total_alt_qty=total_alt_qty,
        total_tracked_qty=total_tracked_qty,
        total_untracked_qty=grand_total_qty - total_tracked_qty,
        grand_total_qty=grand_total_qty,
        untagged_target_sales=untagged_target_sales,
    )
