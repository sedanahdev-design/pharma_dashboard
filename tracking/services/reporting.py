"""Core business logic: for a monthly upload, work out - per category you
decided to track that month - how much quantity (and, when prices are
known, value in ل.س.ج) pharmacies sold from the exact product(s) you told
them to sell (target items) versus how much they sold from something else
tagged under the same category (alternatives).

This mirrors the "أصناف الأورانج" report style: the highlighted / target
rows are exactly the products listed for that category in the target-items
workbook, everything else sharing the same "الشروحات 5" tag is an
alternative the pharmacy chose instead.

A sales row only counts toward anything here when its own "الشروحات 5" tag
matches a category you're tracking this month - a row with no tag, or a
tag that doesn't match any tracked category, is excluded entirely, even
when its item name happens to be a designated target item somewhere. A
target item sold on an untagged row is still surfaced separately (see
untagged_target_sales below) so you can go have finance fix the tagging,
but it does not move any total on its own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from tracking.models import ItemPrice


@dataclass
class ItemStat:
    item_name: str
    quantity: float = 0.0
    value: float = 0.0
    unit_price: float = 0.0
    has_price: bool = False
    is_target: bool = False


@dataclass
class PharmacyStat:
    pharmacy_name: str
    target_qty: float = 0.0
    alt_qty: float = 0.0
    target_value: float = 0.0
    alt_value: float = 0.0

    @property
    def total_qty(self):
        return self.target_qty + self.alt_qty

    @property
    def total_value(self):
        return self.target_value + self.alt_value

    @property
    def target_pct(self):
        return (self.target_qty / self.total_qty * 100) if self.total_qty else 0.0


@dataclass
class CategoryStat:
    category: object  # Category model instance
    target_qty: float = 0.0
    alt_qty: float = 0.0
    target_value: float = 0.0
    alt_value: float = 0.0
    items: dict = field(default_factory=dict)  # item_name -> ItemStat
    pharmacies: dict = field(default_factory=dict)  # pharmacy_name -> PharmacyStat
    items_by_pharmacy: dict = field(default_factory=lambda: defaultdict(dict))  # pharmacy -> {item_name: ItemStat}

    @property
    def total_qty(self):
        return self.target_qty + self.alt_qty

    @property
    def total_value(self):
        return self.target_value + self.alt_value

    @property
    def target_pct(self):
        return (self.target_qty / self.total_qty * 100) if self.total_qty else 0.0

    @property
    def target_value_pct(self):
        return (self.target_value / self.total_value * 100) if self.total_value else 0.0

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
    total_target_value: float
    total_alt_value: float
    total_tracked_value: float
    has_prices: bool
    has_own_prices: bool  # this upload has at least one of its own imported/entered prices
    inherited_price_item_count: int  # unique item names priced via inheritance from another month
    untagged_target_sales: list  # diagnostics: target items sold but never tagged in the sheet
    items_missing_price: list  # diagnostics: tracked items with no known unit price

    @property
    def target_pct(self):
        return (self.total_target_qty / self.total_tracked_qty * 100) if self.total_tracked_qty else 0.0

    @property
    def target_value_pct(self):
        return (self.total_target_value / self.total_tracked_value * 100) if self.total_tracked_value else 0.0


def compute_report(upload) -> ReportResult:
    categories = list(upload.categories.prefetch_related("target_items").order_by("order", "name"))
    category_by_name = {c.name.strip(): c for c in categories}

    # item_name -> category name it is a *target* for, this month.
    target_item_to_category: dict[str, str] = {}
    for cat in categories:
        for ti in cat.target_items.all():
            target_item_to_category[ti.item_name.strip()] = cat.name.strip()

    # Prices are stored per-upload (they can drift month to month), but a
    # brand-new upload usually has none yet. Rather than force a re-upload
    # of the price report every single month, fall back to the most
    # recently known price for the same item name from any other upload -
    # "استيراد أسعار" always overrides this for the items it covers.
    own_price_map: dict[str, float] = {
        name.strip(): price for name, price in upload.item_prices.values_list("item_name", "unit_price")
    }
    fallback_price_map: dict[str, float] = {}
    for name, price in (
        ItemPrice.objects.exclude(upload=upload)
        .order_by("item_name", "-upload__uploaded_at", "-created_at")
        .values_list("item_name", "unit_price")
    ):
        name = name.strip()
        fallback_price_map.setdefault(name, price)

    price_map: dict[str, float] = {**fallback_price_map, **own_price_map}
    has_prices = bool(price_map)
    has_own_prices = bool(own_price_map)
    inherited_item_names: set[str] = set()

    stats: dict[str, CategoryStat] = {
        name: CategoryStat(category=cat) for name, cat in category_by_name.items()
    }

    grand_total_qty = 0.0
    total_tracked_qty = 0.0
    total_tracked_value = 0.0
    untagged_target_rows = defaultdict(float)  # item_name -> qty, sold but raw_category blank/other
    missing_price_rows = defaultdict(float)  # item_name -> qty, tracked but no known price

    rows = upload.sales_rows.values_list("item_name", "pharmacy_name", "quantity", "raw_category")
    for item_name, pharmacy_name, quantity, raw_category in rows:
        grand_total_qty += quantity
        item_name = (item_name or "").strip()
        pharmacy_name = (pharmacy_name or "").strip() or "(بدون اسم صيدلية)"
        raw_category = (raw_category or "").strip()

        # A row only counts at all when its own "الشروحات 5" tag matches a
        # category you track this month - matching by item name alone
        # (regardless of tag) used to also count a designated target item
        # even on an untagged row, but that silently pulled in sales
        # finance simply forgot to tag, which you'd rather not have mixed
        # into the numbers at all. The mismatch is still surfaced below
        # via untagged_target_rows, so you can go have finance fix the
        # tagging - it just no longer affects any total on its own.
        target_category_for_item = target_item_to_category.get(item_name)
        if target_category_for_item and raw_category != target_category_for_item:
            untagged_target_rows[item_name] += quantity

        if raw_category and raw_category in category_by_name:
            resolved_category = raw_category
            is_target = target_category_for_item == raw_category
        else:
            resolved_category = None
            is_target = False

        if resolved_category is None:
            continue

        unit_price = price_map.get(item_name)
        has_price = unit_price is not None
        value = quantity * unit_price if has_price else 0.0
        if not has_price:
            missing_price_rows[item_name] += quantity
        elif item_name not in own_price_map:
            inherited_item_names.add(item_name)

        total_tracked_qty += quantity
        total_tracked_value += value
        cat_stat = stats[resolved_category]

        if is_target:
            cat_stat.target_qty += quantity
            cat_stat.target_value += value
        else:
            cat_stat.alt_qty += quantity
            cat_stat.alt_value += value

        item_stat = cat_stat.items.get(item_name)
        if item_stat is None:
            item_stat = ItemStat(item_name=item_name, is_target=is_target, unit_price=unit_price or 0.0)
            cat_stat.items[item_name] = item_stat
        item_stat.quantity += quantity
        item_stat.value += value
        item_stat.has_price = item_stat.has_price or has_price
        item_stat.is_target = item_stat.is_target or is_target

        ph_stat = cat_stat.pharmacies.get(pharmacy_name)
        if ph_stat is None:
            ph_stat = PharmacyStat(pharmacy_name=pharmacy_name)
            cat_stat.pharmacies[pharmacy_name] = ph_stat
        if is_target:
            ph_stat.target_qty += quantity
            ph_stat.target_value += value
        else:
            ph_stat.alt_qty += quantity
            ph_stat.alt_value += value

        ph_items = cat_stat.items_by_pharmacy[pharmacy_name]
        ph_item_stat = ph_items.get(item_name)
        if ph_item_stat is None:
            ph_item_stat = ItemStat(item_name=item_name, is_target=is_target, unit_price=unit_price or 0.0)
            ph_items[item_name] = ph_item_stat
        ph_item_stat.quantity += quantity
        ph_item_stat.value += value
        ph_item_stat.has_price = ph_item_stat.has_price or has_price
        ph_item_stat.is_target = ph_item_stat.is_target or is_target

    ordered = sorted(stats.values(), key=lambda c: c.total_qty, reverse=True)

    total_target_qty = sum(c.target_qty for c in ordered)
    total_alt_qty = sum(c.alt_qty for c in ordered)
    total_target_value = sum(c.target_value for c in ordered)
    total_alt_value = sum(c.alt_value for c in ordered)

    untagged_target_sales = sorted(
        ({"item_name": k, "quantity": v} for k, v in untagged_target_rows.items()),
        key=lambda d: d["quantity"],
        reverse=True,
    )
    items_missing_price = sorted(
        ({"item_name": k, "quantity": v} for k, v in missing_price_rows.items()),
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
        total_target_value=total_target_value,
        total_alt_value=total_alt_value,
        total_tracked_value=total_tracked_value,
        has_prices=has_prices,
        has_own_prices=has_own_prices,
        inherited_price_item_count=len(inherited_item_names),
        untagged_target_sales=untagged_target_sales,
        items_missing_price=items_missing_price,
    )
