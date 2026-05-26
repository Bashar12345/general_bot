#!/usr/bin/env sh

set -eu

if [ "$#" -eq 0 ]; then
  exec docker compose exec valr-bot sh
fi

exec docker compose exec valr-bot sh -lc "$*"