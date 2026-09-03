from django.contrib import admin

from .models import Category, MonthlyUpload, SalesRow, TargetItem


class TargetItemInline(admin.TabularInline):
    model = TargetItem
    extra = 0


class CategoryInline(admin.TabularInline):
    model = Category
    extra = 0
    show_change_link = True


@admin.register(MonthlyUpload)
class MonthlyUploadAdmin(admin.ModelAdmin):
    list_display = ("name", "uploaded_at", "total_rows", "pharmacy_count")
    inlines = [CategoryInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "upload", "order")
    list_filter = ("upload",)
    inlines = [TargetItemInline]


@admin.register(SalesRow)
class SalesRowAdmin(admin.ModelAdmin):
    list_display = ("item_name", "pharmacy_name", "quantity", "raw_category", "upload")
    list_filter = ("upload", "pharmacy_name")
    search_fields = ("item_name", "raw_category")
