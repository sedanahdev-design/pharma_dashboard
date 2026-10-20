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

# Render (and most PaaS hosts) assign the port through $PORT and route to
# it; hardcoding one works only as long as the host happens to probe for
# it. Falling back to 8060 keeps docker-compose unchanged.
PORT="${PORT:-8060}"

# Two workers, not three. Uploading a month means parsing tens of
# thousands of rows, and on a 512MB instance three worker processes plus
# one upload is enough to cross the memory limit - at which point the
# worker is killed and the browser is shown a bare HTTP 502 with no
# explanation. Override with GUNICORN_WORKERS on a larger instance.
WORKERS="${GUNICORN_WORKERS:-2}"

# A month import legitimately takes a minute or more, so the worker
# timeout has to exceed it or gunicorn kills a healthy request mid-way
# and the result is the same 502.
TIMEOUT="${GUNICORN_TIMEOUT:-300}"

echo "==> تشغيل الخادم على المنفذ ${PORT} بـ ${WORKERS} عامل (مهلة ${TIMEOUT}ث)..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --timeout "${TIMEOUT}" \
    --graceful-timeout 30 \
    --max-requests 200 \
    --max-requests-jitter 40 \
    --worker-tmp-dir /dev/shm \
    --access-logfile - \
    --error-logfile -
