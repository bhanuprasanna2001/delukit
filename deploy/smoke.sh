#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: deploy/smoke.sh <public-hostname>" >&2
  exit 2
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

docker compose -f compose.prod.yaml config --quiet
running="$(docker compose -f compose.prod.yaml ps --status running --services)"
for service in delukit-daemon dagster-webserver delu caddy; do
  if ! grep -qx "$service" <<< "$running"; then
    echo "$service is not running" >&2
    exit 1
  fi
done

curl --fail --silent --show-error "https://$1/healthz" >/dev/null
curl --fail --silent --show-error "https://$1/api/options" >/dev/null
curl --fail --silent --show-error http://127.0.0.1:3000/ >/dev/null
echo "Containers, public API, HTTPS, and private Dagster respond."
