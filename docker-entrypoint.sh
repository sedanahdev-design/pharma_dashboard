#!/bin/sh
set -e

echo "==> تطبيق ترحيلات قاعدة البيانات..."
python manage.py migrate --noinput

# Accounts come before any data step: seed_demo needs an owner to attach
# its sample month to, and the whole app is unreachable without a login.
echo "==> إنشاء/تحديث حسابات المستخدمين وصلاحياتها..."
python manage.py setup_users

if [ "${SEED_DEMO:-1}" = "1" ]; then
    echo "==> استيراد بيانات شهر 7 - 2026 كمثال (إن لم تكن موجودة)..."
    python manage.py seed_demo || true
fi

# Render (and similar hosts) assign the port through $PORT.
echo "==> تشغيل الخادم على المنفذ ${PORT:-8060}..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8060}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-1}" \
    --timeout "${GUNICORN_TIMEOUT:-120}"
