#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

if [[ $# -ne 1 ]]; then
  echo "Usage: deploy/backup.sh <rclone-crypt-remote:path>" >&2
  exit 2
fi

remote="$1"
command -v rclone >/dev/null
command -v docker >/dev/null
mkdir -p backups

slot="$(($(date -u +%s) / 604800 % 3))"
archive="backups/slot-${slot}.tar.gz"
temporary="${archive}.tmp"

finish() {
  status=$?
  docker compose -f compose.prod.yaml up -d delukit-daemon dagster-webserver delu >/dev/null || true
  if [[ $status -ne 0 ]]; then
    docker compose -f compose.prod.yaml exec -T delukit-daemon \
      python -m delukit.ops.alerts backup alert "Backup failed on $(date -u +%FT%TZ)" || true
  fi
  exit "$status"
}
trap finish EXIT

docker compose -f compose.prod.yaml stop delukit-daemon dagster-webserver delu
tar -C "$repo_dir" -czf "$temporary" data delu/data
mv "$temporary" "$archive"
(cd backups && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")

max_bytes=$((6 * 1024 * 1024 * 1024))
if [[ $(stat -c %s "$archive") -gt $max_bytes ]]; then
  echo "Backup exceeds the three-slot free-storage budget" >&2
  exit 1
fi

docker compose -f compose.prod.yaml up -d delukit-daemon dagster-webserver delu
rclone copyto "$archive" "${remote%/}/slot-${slot}.tar.gz"
rclone copyto "${archive}.sha256" "${remote%/}/slot-${slot}.tar.gz.sha256"
docker compose -f compose.prod.yaml exec -T delukit-daemon \
  python -m delukit.ops.alerts backup recovered "Backup slot ${slot} uploaded"
