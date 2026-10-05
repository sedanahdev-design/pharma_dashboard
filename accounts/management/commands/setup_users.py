"""Create (or update) the two working accounts, idempotently.

Run automatically on every container start by docker-entrypoint.sh, and
safe to run again at any time: it never resets a password that already
exists unless you explicitly pass one, so restarting the stack can't
silently undo a password the owner changed from the admin.

Usernames and passwords come from environment variables so nothing is
hardcoded in the image:

    APP_OWNER_USERNAME       default "admin"     - gets BOTH services
    APP_OWNER_PASSWORD       (set once, first run)
    APP_SECOND_USERNAME      default "user2"     - gets the categories service only
    APP_SECOND_PASSWORD      (set once, first run)

When a password variable is absent on first creation the account is
created *disabled* (unusable password) and the command says so, instead
of inventing a default password that would sit there forever as an open
door. Set the variable and re-run, or use:

    docker compose exec web python manage.py changepassword <username>
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts.models import Profile


class Command(BaseCommand):
    help = "ينشئ حسابي الاستخدام ويضبط الخدمات المتاحة لكل منهما."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="أعد ضبط كلمة المرور من متغيرات البيئة حتى لو كان الحساب موجوداً.",
        )

    def handle(self, *args, **options):
        reset = options["reset_passwords"]
        specs = [
            (
                os.environ.get("APP_OWNER_USERNAME", "admin").strip() or "admin",
                os.environ.get("APP_OWNER_PASSWORD"),
                {"can_use_tracking": True, "can_use_reconcile": True},
                True,  # superuser: this is the owner account
                "متابعة التصنيفات + مطابقة المذكرات",
            ),
            (
                os.environ.get("APP_SECOND_USERNAME", "user2").strip() or "user2",
                os.environ.get("APP_SECOND_PASSWORD"),
                {"can_use_tracking": True, "can_use_reconcile": False},
                False,
                "متابعة التصنيفات فقط",
            ),
        ]

        for username, password, flags, is_owner, label in specs:
            user, created = User.objects.get_or_create(username=username)
            if created:
                if password:
                    user.set_password(password)
                else:
                    user.set_unusable_password()
            elif reset and password:
                user.set_password(password)
            user.is_staff = is_owner
            user.is_superuser = is_owner
            user.is_active = True
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            for field, value in flags.items():
                setattr(profile, field, value)
            profile.save()

            state = "أُنشئ" if created else "محدَّث"
            self.stdout.write(self.style.SUCCESS(f"{state}: {username} ← {label}"))
            if created and not password:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! الحساب {username} بلا كلمة مرور بعد. "
                        f"نفّذ: python manage.py changepassword {username}"
                    )
                )
