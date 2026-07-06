#!/usr/bin/env bash
# 防止 demo.log 等无限增长占满磁盘
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
MAX_MB="${LOG_MAX_MB:-32}"

rotate_one() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local size_mb
  size_mb=$(du -m "$file" | awk '{print $1}')
  if (( size_mb < MAX_MB )); then
    return 0
  fi
  local rotated="${file%.log}.$(date +%Y%m%d-%H%M%S).log"
  mv "$file" "$rotated"
  : >"$file"
  echo "[rotate-logs] rotated ${file} -> ${rotated} (${size_mb}MB)"
}

mkdir -p "$LOG_DIR"
rotate_one "$LOG_DIR/demo.log"
rotate_one "$LOG_DIR/api.log"
rotate_one "$LOG_DIR/web.log"

# 只保留最近 3 个归档
find "$LOG_DIR" -maxdepth 1 -name 'demo.*.log' -type f | sort -r | tail -n +4 | xargs -r rm -f
find "$LOG_DIR" -maxdepth 1 -name 'api.*.log' -type f | sort -r | tail -n +4 | xargs -r rm -f
find "$LOG_DIR" -maxdepth 1 -name 'web.*.log' -type f | sort -r | tail -n +4 | xargs -r rm -f
