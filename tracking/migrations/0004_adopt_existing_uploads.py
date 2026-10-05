"""Give every pre-existing month an owner.

Before this release the app had no accounts at all, so the months
already in the database belong to nobody - and every view now filters on
owner, which would make them vanish from the interface the moment the
new build goes live. They are handed to the owner account (the first
superuser, falling back to the first user) so that upgrading is
invisible: log in as the owner and last month's data is exactly where it
was.

Reversing this migration only clears the field again; no data is lost
either way.
"""

from django.db import migrations


def adopt(apps, schema_editor):
    MonthlyUpload = apps.get_model("tracking", "MonthlyUpload")
    User = apps.get_model("auth", "User")

    orphans = MonthlyUpload.objects.filter(owner__isnull=True)
    if not orphans.exists():
        return
    user = (
        User.objects.filter(is_superuser=True).order_by("pk").first()
        or User.objects.order_by("pk").first()
    )
    if user is None:
        # Fresh install: there is no data to adopt and no one to give it
        # to. setup_users runs right after migrate and creates the
        # accounts, so leaving this as a no-op is correct.
        return
    orphans.update(owner=user)


def unadopt(apps, schema_editor):
    MonthlyUpload = apps.get_model("tracking", "MonthlyUpload")
    MonthlyUpload.objects.update(owner=None)


class Migration(migrations.Migration):
    dependencies = [("tracking", "0003_monthlyupload_owner")]
    operations = [migrations.RunPython(adopt, unadopt)]
