#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
if [[ -e .local/m2-pg-name || -e .local/m2-pg.env ]]; then
  echo 'Owned fixture files already exist; inspect/stop that fixture first.' >&2
  exit 1
fi
name="kat-m2-$(date +%s)-$$"
printf '%s\n' "$name" > .local/m2-pg-name
python3 - <<'PY'
from pathlib import Path
from secrets import token_urlsafe
Path('.local/m2-pg.env').write_text('POSTGRES_USER=kat_fixture\nPOSTGRES_DB=kat_fixture\nPOSTGRES_PASSWORD=' + token_urlsafe(32) + '\n')
PY
if ! docker run --detach --name "$name" --label kat.m2.fixture=owned \
    --publish 127.0.0.1::5432 --env-file .local/m2-pg.env \
    --memory 512m --cpus 2 postgres:16.14-alpine >/dev/null; then
  rm -f .local/m2-pg-name .local/m2-pg.env
  exit 1
fi
for _ in $(seq 1 30); do
  # The image's temporary initialization server accepts Unix sockets before
  # the final TCP server is ready; wait for the published service instead.
  if docker exec "$name" pg_isready -h 127.0.0.1 -U kat_fixture -d kat_fixture >/dev/null 2>&1; then
    docker port "$name" 5432/tcp
    exit 0
  fi
  sleep 1
done
echo 'Owned fixture did not become ready; inspect only this container.' >&2
exit 1
