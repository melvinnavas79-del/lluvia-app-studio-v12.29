#!/bin/bash
# ============================================================
# BACKUP AUTOMÁTICO MONGODB · Lluvia App Studio
# ============================================================
# Corre via cron diario a las 04:00 UTC.
# Guarda dump comprimido en /var/backups/lluvia/mongo/ y retiene 14 días.
# Si DROPBOX_TOKEN o S3_BUCKET están en env, sube también a la nube.
# ============================================================

set -euo pipefail

# Cargar env de forma segura (evita parseo bash de valores con espacios)
if [ -f /app/backend/.env ]; then
  export MONGO_URL=$(python3 -c "
from dotenv import dotenv_values
v=dotenv_values('/app/backend/.env')
print(v.get('MONGO_URL',''))")
  export DB_NAME=$(python3 -c "
from dotenv import dotenv_values
v=dotenv_values('/app/backend/.env')
print(v.get('DB_NAME',''))")
  export BACKUP_S3_BUCKET=$(python3 -c "
from dotenv import dotenv_values
v=dotenv_values('/app/backend/.env')
print(v.get('BACKUP_S3_BUCKET',''))")
  export BACKUP_DROPBOX_TOKEN=$(python3 -c "
from dotenv import dotenv_values
v=dotenv_values('/app/backend/.env')
print(v.get('BACKUP_DROPBOX_TOKEN',''))")
fi

BACKUP_DIR="/var/backups/lluvia/mongo"
RETENTION_DAYS=14
TS=$(date -u +%Y%m%d_%H%M%S)
DUMP_DIR="${BACKUP_DIR}/${TS}"
ARCHIVE="${BACKUP_DIR}/lluvia_${TS}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u +%FT%TZ)] === Backup Lluvia iniciado ==="
echo "[$(date -u +%FT%TZ)] MONGO_URL: ${MONGO_URL:0:20}... DB: $DB_NAME"

# Dump
mongodump --uri="$MONGO_URL" --db="$DB_NAME" --out="$DUMP_DIR" --quiet
echo "[$(date -u +%FT%TZ)] mongodump OK ($DUMP_DIR)"

# Comprimir
tar czf "$ARCHIVE" -C "$BACKUP_DIR" "$TS"
rm -rf "$DUMP_DIR"
SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "[$(date -u +%FT%TZ)] archive OK ($ARCHIVE · $SIZE)"

# Retención: borrar backups > RETENTION_DAYS
find "$BACKUP_DIR" -type f -name "lluvia_*.tar.gz" -mtime "+$RETENTION_DAYS" -print -delete

# Upload opcional a la nube si las variables están configuradas
if [ -n "${BACKUP_S3_BUCKET:-}" ] && command -v aws >/dev/null; then
  aws s3 cp "$ARCHIVE" "s3://${BACKUP_S3_BUCKET}/lluvia/$(basename "$ARCHIVE")" --quiet \
    && echo "[$(date -u +%FT%TZ)] S3 upload OK"
fi

if [ -n "${BACKUP_DROPBOX_TOKEN:-}" ]; then
  curl -sS -X POST "https://content.dropboxapi.com/2/files/upload" \
    -H "Authorization: Bearer ${BACKUP_DROPBOX_TOKEN}" \
    -H "Dropbox-API-Arg: {\"path\":\"/lluvia/$(basename "$ARCHIVE")\",\"mode\":\"overwrite\"}" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${ARCHIVE}" > /dev/null \
    && echo "[$(date -u +%FT%TZ)] Dropbox upload OK"
fi

echo "[$(date -u +%FT%TZ)] === Backup completado ==="
