#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .local/m2-pg-name ]]; then
  echo 'No recorded owned fixture.' >&2
  exit 1
fi
name=$(<.local/m2-pg-name)
if [[ ! "$name" =~ ^kat-m2-[0-9]+-[0-9]+$ ]]; then
  echo 'Refusing to stop an unrecognized container.' >&2
  exit 1
fi
image=$(docker inspect "$name" --format '{{.Config.Image}}')
if [[ "$image" != 'postgres:16.14-alpine' ]]; then
  echo 'Refusing to stop a container with a different image.' >&2
  exit 1
fi
docker stop "$name" >/dev/null
docker rm "$name" >/dev/null
rm .local/m2-pg-name .local/m2-pg.env
printf 'Stopped only %s; backup and deletion journal retained.\n' "$name"
