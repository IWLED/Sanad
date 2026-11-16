#!/usr/bin/env bash
# ==============================================================================
# سكربت استعادة قاعدة بيانات خادم سند (Section 13.5 & ADR-005)
# الاستخدام: ./restore.sh /path/to/sanad_backup_YYYYMMDD_HHMMSS.tar.gz
# ==============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "الاستخدام: $0 <مسار_ملف_النسخة_الاحتياطية.tar.gz>" >&2
    exit 1
fi

ARCHIVE_PATH="$1"
DB_PATH="${DB_PATH:-/data/secretary.db}"
RESTORE_TMP="/tmp/sanad_restore_$$"

if [ ! -f "${ARCHIVE_PATH}" ]; then
    echo "خطأ: ملف النسخة الاحتياطية غير موجود: ${ARCHIVE_PATH}" >&2
    exit 1
fi

echo "=== [سند] بدء عملية استعادة قاعدة البيانات من: ${ARCHIVE_PATH} ==="

mkdir -p "${RESTORE_TMP}"
trap 'rm -rf "${RESTORE_TMP}"' EXIT

# 1. فك ضغط النسخة
echo "[1/4] جاري فك ضغط الأرشيف..."
tar -xzf "${ARCHIVE_PATH}" -C "${RESTORE_TMP}"
SQLITE_FILE=$(find "${RESTORE_TMP}" -name "*.sqlite" | head -n 1)

if [ -z "${SQLITE_FILE}" ] || [ ! -f "${SQLITE_FILE}" ]; then
    echo "خطأ: لم يتم العثور على ملف قاعدة بيانات .sqlite داخل الأرشيف!" >&2
    exit 2
fi

# 2. فحص سلامة الملف المستخرج
echo "[2/4] فحص سلامة الملف المستخرج..."
INTEGRITY=$(sqlite3 "${SQLITE_FILE}" "PRAGMA integrity_check;")
if [ "${INTEGRITY}" != "ok" ]; then
    echo "خطأ: ملف النسخة الاحتياطية تالف أو غير صالح: ${INTEGRITY}" >&2
    exit 3
fi

TABLE_COUNT=$(sqlite3 "${SQLITE_FILE}" "SELECT count(*) FROM sqlite_master WHERE type='table';")
echo "تم التحقق من سلامة الملف. عدد الجداول: ${TABLE_COUNT}"

# 3. أخذ نسخة أمان للحالية قبل الاستبدال إن وجدت
if [ -f "${DB_PATH}" ]; then
    SAFETY_BACKUP="${DB_PATH}.pre_restore_$(date +%s)"
    echo "[3/4] أخذ نسخة أمان احتياطية لقاعدة البيانات الحالية في: ${SAFETY_BACKUP}"
    cp "${DB_PATH}" "${SAFETY_BACKUP}"
fi

# 4. استبدال الملف وإعادة ضبط الصلاحيات
echo "[4/4] تطبيق الاستعادة على ${DB_PATH}..."
cp "${SQLITE_FILE}" "${DB_PATH}"
chmod 600 "${DB_PATH}"

echo "=== [سند] تمت الاستعادة بنجاح والتحقق من سلامة النظام! ==="
