from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "الخدمات المتاحة لهذا الحساب"
    fields = ("display_name", "can_use_tracking", "can_use_reconcile")


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "email", "is_active", "is_superuser", "services")
    list_select_related = ("profile",)

    @admin.display(description="الخدمات")
    def services(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "-"
        names = []
        if profile.can_use_tracking:
            names.append("متابعة التصنيفات")
        if profile.can_use_reconcile:
            names.append("مطابقة المذكرات")
        return " + ".join(names) or "لا شيء"


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.site_header = "إدارة لوحة الصيدليات"
admin.site.site_title = "إدارة لوحة الصيدليات"
