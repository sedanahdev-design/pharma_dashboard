from django.conf import settings
from django.db import models
from django.urls import reverse


class MonthlyUpload(models.Model):
    """One monthly snapshot: a موسع sales workbook plus the set of target
    categories/items that were in force for that month.

    `owner` is the root of this service's data isolation: every other
    model here hangs off MonthlyUpload, so filtering uploads by owner is
    enough to keep two accounts' months, categories, targets, prices and
    sales rows completely apart. Every view filters on it - nothing
    relies on an unguessable primary key."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monthly_uploads",
        null=True,
        blank=True,
    )
    name = models.CharField(
        "اسم الشهر / الدفعة", max_length=200, help_text="مثال: شهر 7 - 2026"
    )
    source_filename = models.CharField(max_length=255, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField("ملاحظات", blank=True, default="")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "دفعة شهرية"
        verbose_name_plural = "الدفعات الشهرية"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("tracking:upload_detail", args=[self.pk])

    @property
    def total_rows(self):
        return self.sales_rows.count()

    @property
    def total_quantity(self):
        return self.sales_rows.aggregate(models.Sum("quantity"))["quantity__sum"] or 0

    @property
    def pharmacy_count(self):
        return (
            self.sales_rows.exclude(pharmacy_name="")
            .values("pharmacy_name")
            .distinct()
            .count()
        )


class Category(models.Model):
    """A تصنيف / مجموعة the owner decided to track for a given month, e.g.
    'بديل سيتامول تاميكو'. Matches the الشروحات 5 tag in the sales sheet."""

    upload = models.ForeignKey(
        MonthlyUpload, related_name="categories", on_delete=models.CASCADE
    )
    name = models.CharField("اسم المجموعة / التصنيف", max_length=255)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = ("upload", "name")
        verbose_name = "تصنيف"
        verbose_name_plural = "التصنيفات"

    def __str__(self):
        return self.name


class TargetItem(models.Model):
    """One specific product name the pharmacy was instructed to sell within
    a category, for this month. Sourced from تارغيت كاتيغوري or typed in
    manually / edited from the dashboard."""

    category = models.ForeignKey(
        Category, related_name="target_items", on_delete=models.CASCADE
    )
    item_name = models.CharField("اسم الصنف المستهدف", max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item_name"]
        unique_together = ("category", "item_name")
        verbose_name = "صنف مستهدف"
        verbose_name_plural = "الأصناف المستهدفة"

    def __str__(self):
        return self.item_name


class ItemPrice(models.Model):
    """Unit price (بالليرة السورية الجديدة) for one item, for a given month.
    Sourced from a price-reference workbook (e.g. the أصناف الأورانج report,
    which lists quantity + total value per item) or carried forward from a
    previous month and edited by hand."""

    upload = models.ForeignKey(
        MonthlyUpload, related_name="item_prices", on_delete=models.CASCADE
    )
    item_name = models.CharField(max_length=500, db_index=True)
    unit_price = models.FloatField("سعر الوحدة (ل.س.ج)", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("upload", "item_name")
        verbose_name = "سعر صنف"
        verbose_name_plural = "أسعار الأصناف"

    def __str__(self):
        return f"{self.item_name}: {self.unit_price}"


class SalesRow(models.Model):
    """One row from the موسع workbook: an item sold at a pharmacy, its
    quantity, and whatever category tag (الشروحات 5) it already carried."""

    upload = models.ForeignKey(
        MonthlyUpload, related_name="sales_rows", on_delete=models.CASCADE
    )
    item_name = models.CharField(max_length=500, db_index=True)
    pharmacy_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    quantity = models.FloatField(default=0)
    raw_category = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["upload", "raw_category"]),
            models.Index(fields=["upload", "item_name"]),
        ]

    def __str__(self):
        return f"{self.item_name} / {self.pharmacy_name} ({self.quantity})"
