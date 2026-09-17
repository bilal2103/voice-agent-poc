#!/usr/bin/env sh
# Applies any pending migrations, then hands off to the container CMD.
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting: $*"
exec "$@"
