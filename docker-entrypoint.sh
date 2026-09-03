#!/bin/sh
set -e

echo "==> تطبيق ترحيلات قاعدة البيانات..."
python manage.py migrate --noinput

if [ "${SEED_DEMO:-1}" = "1" ]; then
    echo "==> استيراد بيانات شهر 7 - 2026 كمثال (إن لم تكن موجودة)..."
    python manage.py seed_demo || true
fi

echo "==> تشغيل الخادم على المنفذ 8060..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8060 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 120
