#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo 'Run python3 scripts/configure.py once to create local settings.'
  exit 1
fi
exec docker compose up --build -d --wait
