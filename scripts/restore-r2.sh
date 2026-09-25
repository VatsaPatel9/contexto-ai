#!/usr/bin/env bash
# Re-upload the backed-up course documents to a Cloudflare R2 bucket,
# preserving the users/<user_id>/<document_id>/<filename> key layout that
# backend/services/storage.py expects.
#
#   ./scripts/restore-r2.sh            # uses creds from the backup
#   BUCKET=new-bucket ./scripts/restore-r2.sh
set -euo pipefail

BACKUP="${BACKUP:-$HOME/Desktop/contexto-final-backup}"
PY="${PY:-backend/venv/bin/python}"
[ -x "$PY" ] || PY=python3

exec "$PY" - "$BACKUP" "${BUCKET:-}" <<'PY'
import os, pathlib, re, sys
import boto3
from botocore.client import Config

backup = pathlib.Path(sys.argv[1])
override = sys.argv[2] if len(sys.argv) > 2 else ""

cfg = {}
for line in (backup / "vars-Backend.txt").read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()

bucket = override or cfg["R2_BUCKET"]
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4"),
    region_name="auto",
)

root = backup / "r2-documents"
if not root.is_dir():
    sys.exit(f"nothing to upload: {root} missing")

n = 0
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    key = str(path.relative_to(root))
    s3.upload_file(str(path), bucket, key)
    n += 1
    print(f"  [{n:>3}] {re.sub(r'users/[^/]+/', 'users/<uid>/', key)}")

print(f"\nuploaded {n} objects to {bucket}")
PY
