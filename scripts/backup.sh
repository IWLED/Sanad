#!/usr/bin/env bash
# ==============================================================================
# سكربت النسخ الاحتياطي المتسق لخادم سند (Section 13.5 & ADR-005)
# يقوم بأخذ نسخة متسقة من SQLite أثناء العمل (Online WAL Backup) والتحقق منها.
# ==============================================================================

set -euo pipefail

DB_PATH="${DB_PATH:-/data/secretary.db}"
BACKUP_DIR="${BACKUP_DIR:-/exports/backups}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/sanad_backup_${TIMESTAMP}.sqlite"
ARCHIVE_FILE="${BACKUP_DIR}/sanad_backup_${TIMESTAMP}.tar.gz"

echo "=== [سند] بدء عملية النسخ الاحتياطي: ${TIMESTAMP} ==="

mkdir -p "${BACKUP_DIR}"

if [ ! -f "${DB_PATH}" ]; then
    echo "خطأ: قاعدة البيانات غير موجودة في ${DB_PATH}" >&2
    exit 1
fi

# 1. أخذ نسخة متسقة من SQLite باستخدام أمر .backup المدمج (WAL Safe)
echo "[1/4] جاري إنشاء نسخة متسقة من قاعدة البيانات..."
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

# 2. التحقق من سلامة النسخة الاحتياطية (Integrity Check)
echo "[2/4] جاري فحص سلامة النسخة الاحتياطية..."
INTEGRITY=$(sqlite3 "${BACKUP_FILE}" "PRAGMA integrity_check;")
if [ "${INTEGRITY}" != "ok" ]; then
    echo "خطأ: فشل فحص سلامة قاعدة البيانات: ${INTEGRITY}" >&2
    rm -f "${BACKUP_FILE}"
    exit 2
fi

TABLE_COUNT=$(sqlite3 "${BACKUP_FILE}" "SELECT count(*) FROM sqlite_master WHERE type='table';")
echo "عدد الجداول المحفوظة بنجاح: ${TABLE_COUNT}"

# 3. ضغط النسخة الاحتياطية
echo "[3/4] جاري ضغط النسخة الاحتياطية..."
tar -czf "${ARCHIVE_FILE}" -C "${BACKUP_DIR}" "$(basename "${BACKUP_FILE}")"
rm -f "${BACKUP_FILE}"

# 4. تطبيق سياسة الاحتفاظ بالنسخ (Retention Policy: 7 أيام)
echo "[4/4] تطبيق سياسة الاحتفاظ بالنسخ..."
find "${BACKUP_DIR}" -name "sanad_backup_*.tar.gz" -type f -mtime +7 -delete || true

BACKUP_SIZE=$(ls -lh "${ARCHIVE_FILE}" | awk '{print $5}')
echo "=== [سند] اكتمل النسخ الاحتياطي بنجاح! الملف: ${ARCHIVE_FILE} (الحجم: ${BACKUP_SIZE}) ==="
