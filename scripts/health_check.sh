#!/usr/bin/env bash
# ==============================================================================
# سكربت الفحص التشخيصي الشامل لخادم سند الذكي (System Health Check)
# ==============================================================================

set -u

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "  [${GREEN}✓${NC}] $1"; }
fail() { echo -e "  [${RED}✗${NC}] $1"; }
warn() { echo -e "  [${YELLOW}!${NC}] $1"; }

echo "=================================================="
echo "    تقرير الفحص التشخيصي الشامل لخادم سند الذكي   "
echo "=================================================="
echo "الوقت الحالي: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

echo "1. فحص حاويات Docker:"
for c in secretary-api-1 secretary-worker-1 omniroute omniroute-redis; do
    if sudo docker ps --format '{{.Names}}\t{{.Status}}' | grep -q "^${c}"; then
        STATUS=$(sudo docker ps --format '{{.Names}}\t{{.Status}}' | grep "^${c}" | cut -f2)
        pass "${c}: تعمل بنجاح (${STATUS})"
    else
        fail "${c}: غير مشغلة أو متوقفة!"
    fi
done

echo ""
echo "2. فحص نقاط النهاية HTTP:"
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/healthz || echo "000")
if [ "${HTTP_HEALTH}" = "200" ]; then
    pass "GET /healthz -> 200 OK (سليم)"
else
    fail "GET /healthz -> كود الاستجابة: ${HTTP_HEALTH}"
fi

HTTP_READY=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/readyz || echo "000")
if [ "${HTTP_READY}" = "200" ]; then
    pass "GET /readyz -> 200 OK (قاعدة البيانات جاهزة)"
else
    fail "GET /readyz -> كود الاستجابة: ${HTTP_READY}"
fi

echo ""
echo "3. فحص بوابة النماذج الذكية (OmniRoute):"
OMNI_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:20128/v1/models || echo "000")
if [ "${OMNI_CODE}" = "200" ] || [ "${OMNI_CODE}" = "401" ]; then
    pass "OmniRoute (Port 20128) يستجيب بنجاح (HTTP ${OMNI_CODE})"
else
    warn "OmniRoute لم يستجب على المنفذ 20128 (HTTP ${OMNI_CODE})"
fi

echo ""
echo "4. إحصائيات قاعدة البيانات (secretary.db):"
DB_FILE="/var/lib/docker/volumes/secretary_data/_data/secretary.db"
if sudo test -f "${DB_FILE}"; then
    DEV_COUNT=$(sudo sqlite3 "${DB_FILE}" "SELECT count(*) FROM devices;" 2>/dev/null || echo "0")
    EV_COUNT=$(sudo sqlite3 "${DB_FILE}" "SELECT count(*) FROM events;" 2>/dev/null || echo "0")
    ACT_COUNT=$(sudo sqlite3 "${DB_FILE}" "SELECT count(*) FROM actions;" 2>/dev/null || echo "0")
    BRF_COUNT=$(sudo sqlite3 "${DB_FILE}" "SELECT count(*) FROM briefings;" 2>/dev/null || echo "0")
    pass "عدد الأجهزة المقترنة: ${DEV_COUNT}"
    pass "إجمالي الأحداث المسجلة: ${EV_COUNT}"
    pass "إجمالي الإجراءات (Actions): ${ACT_COUNT}"
    pass "إجمالي الإيجازات والملخصات: ${BRF_COUNT}"
else
    warn "ملف قاعدة البيانات غير موجود في المسار الافتراضي ${DB_FILE}"
fi

echo ""
echo "5. المساحة التخزينية والذاكرة:"
DISK_FREE=$(df -h /DATA 2>/dev/null | tail -1 | awk '{print $4}' || df -h / | tail -1 | awk '{print $4}')
pass "المساحة المتاحة على القرص: ${DISK_FREE}"
MEM_FREE=$(free -h | awk '/^Mem:/ {print $4}')
pass "الذاكرة العشوائية الحرة: ${MEM_FREE}"

echo ""
echo "=================================================="
echo "             اكتمل الفحص بنجاح                    "
echo "=================================================="
