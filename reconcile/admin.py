from django.contrib import admin

from .models import Memo, MemoItem, MovementBatch, Pharmacy


@admin.register(Pharmacy)
class PharmacyAdmin(admin.ModelAdmin):
    list_display = ("cost_center", "short_name", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("cost_center", "short_name")


class MemoItemInline(admin.TabularInline):
    model = MemoItem
    extra = 0
    fields = ("row_order", "code", "item_name", "quantity", "price", "expiry_text")


@admin.register(Memo)
class MemoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "number", "pharmacy", "owner", "item_count", "uploaded_at")
    list_filter = ("owner", "pharmacy")
    inlines = [MemoItemInline]


@admin.register(MovementBatch)
class MovementBatchAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "row_count", "uploaded_at")
    list_filter = ("owner",)
