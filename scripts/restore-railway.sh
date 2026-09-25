#!/usr/bin/env bash
#
# Rebuild the Contexto Railway deployment from scratch, from the backup
# taken 2026-09-25 before the original project was deleted.
#
#   ./scripts/restore-railway.sh
#
# Needs: railway CLI (logged in), the backup folder, PostgreSQL 18 client.
# Everything is idempotent-ish but assumes a FRESH project — run it once.
#
# NOT fully automatic: Railway's CLI cannot set a service's Root Directory
# or Config-as-code Path. After this script runs you must set 4 fields in
# the dashboard (see MANUAL STEPS at the end) and redeploy. That is the
# whole of the manual work.

set -euo pipefail

BACKUP="${BACKUP:-$HOME/Desktop/contexto-final-backup}"
PROJECT_NAME="${PROJECT_NAME:-Contexto}"
DEFAULT_WORKSPACE="Vatsa Patel's Projects"   # apostrophe is safe here,
WORKSPACE="${WORKSPACE:-$DEFAULT_WORKSPACE}"  # but not inside ${x:-...}
REPO="${REPO:-VatsaPatel9/contexto-ai}"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@18/bin}"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

# Read one saved variable out of the backup, e.g. `get Backend OPENAI_API_KEY`
get() {
  local file="$BACKUP/vars-$1.txt"
  [ -f "$file" ] || { echo "missing $file" >&2; exit 1; }
  grep -m1 "^$2=" "$file" | cut -d= -f2-
}

# ---------------------------------------------------------------- preflight
say "Preflight"
command -v railway >/dev/null || { echo "railway CLI not installed"; exit 1; }
railway whoami >/dev/null || { echo "run: railway login"; exit 1; }
[ -f "$BACKUP/railway.dump" ] || { echo "no railway.dump in $BACKUP"; exit 1; }
[ -x "$PG_BIN/pg_restore" ] || { echo "need PG18 client: brew install postgresql@18"; exit 1; }
echo "backup: $BACKUP"

# ------------------------------------------------------------------ project
say "Creating project '$PROJECT_NAME'"
railway init -n "$PROJECT_NAME" -w "$WORKSPACE"

# ---------------------------------------------------------------- databases
# Railway provisions each of these WITH its own volume automatically, so we
# do not create volumes by hand (the originals were postgres-volume at
# /var/lib/postgresql/data and redis-volume at /data).
say "Adding Postgres + Redis"
railway add --database postgres
railway add --database redis

# --------------------------------------------------------------- supertokens
# Self-hosted SuperTokens core, sharing the same Postgres database as the app.
say "Adding Supertoken (docker image)"
railway add --service Supertoken \
  --image registry.supertokens.io/supertokens/supertokens-postgresql:latest \
  --variables 'POSTGRESQL_CONNECTION_URI=${{Postgres.DATABASE_URL}}' \
  --variables "API_KEYS=$(get Supertoken API_KEYS)" \
  --variables 'PASSWORD_RESET_TOKEN_LIFETIME=7200000'

# ------------------------------------------------------------------- backend
# Cross-service values use Railway reference syntax, NOT the literal values
# from the backup -- the old internal hostnames are dead.
say "Adding Backend"
railway add --service Backend --repo "$REPO" \
  --variables 'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --variables 'SUPERTOKENS_CONNECTION_URI=http://${{Supertoken.RAILWAY_PRIVATE_DOMAIN}}:3567' \
  --variables 'AUTH_API_DOMAIN=https://${{RAILWAY_PUBLIC_DOMAIN}}' \
  --variables 'AUTH_WEBSITE_DOMAIN=https://${{Frontend.RAILWAY_PUBLIC_DOMAIN}}' \
  --variables 'CORS_ALLOW_ORIGINS=https://${{Frontend.RAILWAY_PUBLIC_DOMAIN}}' \
  --variables "SUPERTOKENS_API_KEY=$(get Backend SUPERTOKENS_API_KEY)" \
  --variables "OPENAI_API_KEY=$(get Backend OPENAI_API_KEY)" \
  --variables "R2_ACCOUNT_ID=$(get Backend R2_ACCOUNT_ID)" \
  --variables "R2_ACCESS_KEY_ID=$(get Backend R2_ACCESS_KEY_ID)" \
  --variables "R2_SECRET_ACCESS_KEY=$(get Backend R2_SECRET_ACCESS_KEY)" \
  --variables "R2_BUCKET=$(get Backend R2_BUCKET)" \
  --variables "SMTP_HOST=$(get Backend SMTP_HOST)" \
  --variables "SMTP_PORT=$(get Backend SMTP_PORT)" \
  --variables "SMTP_USERNAME=$(get Backend SMTP_USERNAME)" \
  --variables "SMTP_PASSWORD=$(get Backend SMTP_PASSWORD)" \
  --variables "SMTP_FROM_EMAIL=$(get Backend SMTP_FROM_EMAIL)" \
  --variables "SMTP_FROM_NAME=$(get Backend SMTP_FROM_NAME)" \
  --variables "RESTRICT_EMAIL_DOMAIN=$(get Backend RESTRICT_EMAIL_DOMAIN)"

# ------------------------------------------------------------------ frontend
say "Adding Frontend"
railway add --service Frontend --repo "$REPO" \
  --variables 'BACKEND_URL=https://${{Backend.RAILWAY_PUBLIC_DOMAIN}}'

# ------------------------------------------------------------------- domains
say "Generating public domains"
railway domain --service Backend  || echo "(set the Backend domain in the dashboard)"
railway domain --service Frontend || echo "(set the Frontend domain in the dashboard)"

# --------------------------------------------------------------- restore data
say "Restoring the database (this is the part that matters)"
NEW_DB="$(railway variables --service Postgres --kv 2>/dev/null \
          | grep -m1 '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)"
if [ -z "$NEW_DB" ]; then
  echo "Could not read the new DATABASE_PUBLIC_URL. Grab it from the"
  echo "dashboard and run:"
  echo "  $PG_BIN/pg_restore --no-owner --no-acl -d '<url>' $BACKUP/railway.dump"
else
  "$PG_BIN/psql" "$NEW_DB" -c 'CREATE EXTENSION IF NOT EXISTS vector;'
  "$PG_BIN/pg_restore" --no-owner --no-acl --disable-triggers \
      -d "$NEW_DB" "$BACKUP/railway.dump"
  "$PG_BIN/psql" "$NEW_DB" -Atc \
      "select 'users='||(select count(*) from all_auth_recipe_users)
            ||' conversations='||(select count(*) from conversations)
            ||' messages='||(select count(*) from messages);"
fi

# ------------------------------------------------------------- R2 re-upload
say "Re-uploading R2 documents"
if [ -d "$BACKUP/r2-documents" ]; then
  echo "run:  ./scripts/restore-r2.sh"
else
  echo "no r2-documents/ in backup -- skipping"
fi

cat <<'EOF'

============================ MANUAL STEPS ============================
Railway's CLI cannot set these. In the dashboard, for BOTH the Backend
and Frontend services -> Settings -> Build:

  Backend :  Root Directory = /backend    Config Path = /backend/railway.toml
  Frontend:  Root Directory = /frontend   Config Path = /frontend/railway.toml

Then Deploy on each. Until this is done the builds fail, because both
services default to the repo root.

Optional: re-point askcontexto.com at the new Frontend service
  railway domain askcontexto.com --service Frontend
and update the CNAME at Namecheap to the value it prints.

Note: restored SuperTokens session keys mean everyone is logged out once.
Accounts, passwords, conversations and documents all survive.
======================================================================
EOF
