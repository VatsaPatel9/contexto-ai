#!/bin/bash
set -e

# Create the supertokens database if it doesn't already exist.
# This script runs automatically on first postgres container startup
# because it is mounted into /docker-entrypoint-initdb.d/.

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE supertokens'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'supertokens')\gexec

    GRANT ALL PRIVILEGES ON DATABASE supertokens TO ${POSTGRES_USER};
EOSQL
