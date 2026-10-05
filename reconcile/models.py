"""Data model for the مذكرة ↔ كشف حركات reconciliation service.

Shape of the real-world problem this mirrors:

* Each pharmacy has a **مذكرة** - a stock list it was given, one row per
  item batch (رقم الصنف، الاسم، عدد القطع، السعر، تاريخ الصلاحية). It is
  reissued only every few months, so it lives on as its own record and is
  replaced (not edited) when a new one arrives.
* Every so often the owner exports one big **كشف حركات** covering *all*
  pharmacies at once, one row per movement (مبيع / مردود مبيع / مناقلة …)
  carrying the pharmacy in the "مركز الكلفة" column.
* The question the service answers: for each pharmacy, how much of each
  مذكرة item actually moved, and what is left.

So a Memo belongs to a pharmacy and persists across periods, while a
MovementBatch is a one-off snapshot - and a report is simply
(one batch) × (each pharmacy's current memo), computed on demand rather
than stored, so re-uploading a corrected memo instantly fixes every past
batch's report without a re-run step to forget.

Every model carries `owner`: two accounts use this app and neither may
see the other's pharmacies, memos, batches or results.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse


class Pharmacy(models.Model):
    """One branch. `cost_center` must match the "مركز الكلفة" value in the
    كشف حركات *exactly* - that string is the only link between a memo and
    the movements that belong to it, so it is stored verbatim rather than
    normalised, and the upload screen offers the values found in the file
    itself instead of asking anyone to retype an Arabic branch name."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pharmacies"
    )
    cost_center = models.CharField(
        "مركز الكلفة (كما في كشف الحركات)", max_length=255, db_index=True
    )
    short_name = models.CharField(
        "الاسم المختصر", max_length=120, blank=True, default="",
        help_text="اسم قصير يظهر على التبويب وفي التقرير، مثال: ليليان فارس",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["cost_center"]
        unique_together = ("owner", "cost_center")
        verbose_name = "صيدلية"
        verbose_name_plural = "الصيدليات"

    def __str__(self):
        return self.short_name or self.cost_center

    @property
    def label(self):
        return self.short_name or self.cost_center

    @property
    def current_memo(self):
        return self.memos.order_by("-uploaded_at", "-pk").first()


class Memo(models.Model):
    """One uploaded مذكرة file for one pharmacy. Uploading a newer one does
    not delete the old: the most recent is the one used, and the history
    stays so an older report can still be explained."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memos"
    )
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="memos")
    number = models.CharField("رقم المذكرة", max_length=100, blank=True, default="")
    source_filename = models.CharField(max_length=255, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField("ملاحظة", max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "مذكرة"
        verbose_name_plural = "المذكرات"

    def __str__(self):
        return f"مذكرة {self.number or self.pk} - {self.pharmacy.label}"

    @property
    def item_count(self):
        return self.items.count()

    @property
    def total_pieces(self):
        return self.items.aggregate(models.Sum("quantity"))["quantity__sum"] or 0


class MemoItem(models.Model):
    """One line of a مذكرة. `row_order` preserves the file's own ordering,
    because the owner reads the result side by side with the original
    sheet and a re-sorted report is much harder to check by eye.

    The same `code` may legitimately appear on more than one row (the same
    drug in two expiry batches) - that is why the primary key is the row,
    not the code."""

    memo = models.ForeignKey(Memo, on_delete=models.CASCADE, related_name="items")
    row_order = models.PositiveIntegerField(default=0)
    code = models.CharField("رقم الصنف", max_length=50, db_index=True)
    item_name = models.CharField("اسم المادة", max_length=500)
    quantity = models.FloatField("عدد القطع", default=0)
    price = models.FloatField("السعر", default=0)
    expiry_text = models.CharField("التاريخ", max_length=50, blank=True, default="")

    class Meta:
        ordering = ["row_order", "pk"]
        indexes = [models.Index(fields=["memo", "code"])]
        verbose_name = "بند مذكرة"
        verbose_name_plural = "بنود المذكرات"

    def __str__(self):
        return f"{self.code} - {self.item_name}"


class MovementBatch(models.Model):
    """One uploaded كشف حركات covering every pharmacy for a period."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="movement_batches"
    )
    name = models.CharField(
        "اسم الكشف / الفترة", max_length=200, help_text="مثال: كشف حركات 9-2026"
    )
    source_filename = models.CharField(max_length=255, blank=True, default="")
    period_text = models.CharField("الفترة كما في الملف", max_length=200, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField("ملاحظات", blank=True, default="")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "كشف حركات"
        verbose_name_plural = "كشوف الحركات"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("reconcile:batch_detail", args=[self.pk])

    @property
    def row_count(self):
        return self.rows.count()

    @property
    def cost_centers(self):
        return list(
            self.rows.exclude(cost_center="")
            .values_list("cost_center", flat=True)
            .distinct()
            .order_by("cost_center")
        )

    @property
    def movement_types(self):
        """Every distinct نوع الفاتورة in this batch, with its row count.

        Shown on screen because the single most confusing failure this
        service can have is a silent one: a sales-only export produces a
        report whose "متناقل" column is all zeros, which reads as "nothing
        was transferred" when the truth is "this file contains no
        transfers at all"."""
        from django.db.models import Count

        return list(
            self.rows.values("invoice_type")
            .annotate(n=Count("id"))
            .order_by("-n")
            .values_list("invoice_type", "n")
        )

    @property
    def transfer_row_count(self):
        from .services.engine import classify_type

        return sum(n for t, n in self.movement_types if classify_type(t) == "مناقلة")

    @property
    def has_transfers(self):
        return self.transfer_row_count > 0


class MovementRow(models.Model):
    """One movement line out of the كشف حركات.

    `quantity` is stored exactly as the file has it, sign included: the
    export already writes returns (مردود مبيع) as negative عبوة, so the
    net movement for an item is a plain SUM with no per-type sign rules
    to get wrong. `invoice_type` is kept so the report can still break the
    net figure down into مبيع / مردود / مناقلة."""

    batch = models.ForeignKey(MovementBatch, on_delete=models.CASCADE, related_name="rows")
    code = models.CharField("الرقم", max_length=50, blank=True, default="", db_index=True)
    item_name = models.CharField(max_length=500, blank=True, default="")
    invoice_type = models.CharField(max_length=100, blank=True, default="", db_index=True)
    cost_center = models.CharField(max_length=255, blank=True, default="", db_index=True)
    quantity = models.FloatField(default=0)
    price = models.FloatField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["batch", "cost_center", "code"]),
            models.Index(fields=["batch", "code"]),
        ]
        verbose_name = "حركة"
        verbose_name_plural = "الحركات"

    def __str__(self):
        return f"{self.item_name} / {self.cost_center} ({self.quantity})"
