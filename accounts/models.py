"""Who may open which service, and nothing else.

The app now hosts two independent services that happen to share a login:

  1. متابعة التصنيفات  - the original monthly موسع / target-category dashboard.
  2. مطابقة المذكرات   - the new مذكرة vs كشف حركات reconciliation.

Every user gets an explicit yes/no per service instead of relying on
is_staff or on group names, because the rule here is a business rule
("this account is allowed to see the reconciliation"), not a Django admin
permission, and it has to be obvious at a glance in the admin which
account can see what. A user with neither flag can log in but sees an
empty home page telling them to contact the owner - they never see a
broken menu or a 500.

Data ownership is deliberately NOT modelled here: every data model in
tracking/ and reconcile/ carries its own `owner` FK to the user who
uploaded it, and every queryset in every view filters on it. That is
what keeps the two accounts' data apart - the flags below only decide
which *pages* exist for an account, never which rows it can read.
"""

from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField("الاسم الظاهر", max_length=150, blank=True, default="")
    can_use_tracking = models.BooleanField(
        "خدمة متابعة التصنيفات", default=True,
        help_text="لوحة متابعة التزام الصيدليات بالأصناف المستهدفة (ملف موسع).",
    )
    can_use_reconcile = models.BooleanField(
        "خدمة مطابقة المذكرات", default=False,
        help_text="مطابقة مذكرات الصيدليات مع كشف الحركات العام.",
    )

    class Meta:
        verbose_name = "صلاحيات مستخدم"
        verbose_name_plural = "صلاحيات المستخدمين"

    def __str__(self):
        return self.display_name or self.user.get_username()

    @property
    def service_count(self):
        return int(self.can_use_tracking) + int(self.can_use_reconcile)


def profile_for(user):
    """Return this user's Profile, creating it on first use.

    Deliberately lazy rather than a post_save signal on User. A signal
    would insert the Profile row the instant the user is created, and the
    Django admin's "add user" page then tries to insert its own row from
    the inline formset in the same request - which fails outright with a
    UNIQUE violation on user_id. Creating the row at first access instead
    lets the admin inline own it, and still guarantees that no code path
    (a shell-created user, an account predating this table) ever meets a
    user without a profile.

    A new profile follows the field defaults - the categories service on,
    the reconciliation off - except for superusers, who get everything,
    since the only reason to create one is to administer the whole app.
    """
    if not user.is_authenticated:
        return None
    profile, _ = Profile.objects.get_or_create(
        user=user, defaults={"can_use_reconcile": bool(user.is_superuser)}
    )
    return profile
