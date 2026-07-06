#!/usr/bin/env bash
# 健康屏 kiosk 看门狗：Chromium 崩溃（Aw, snap!）后自动重开
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_PORT="${WEB_PORT:-5173}"
INTERVAL="${KIOSK_WATCHDOG_INTERVAL:-25}"
LOG="$ROOT/logs/kiosk-watchdog.log"

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

mkdir -p "$ROOT/logs"

kiosk_running() {
  pgrep -f "chromium.*${WEB_PORT}.*dashboard" >/dev/null 2>&1 || \
    pgrep -f "chromium.*app=http://127.0.0.1:${WEB_PORT}/dashboard" >/dev/null 2>&1
}

while true; do
  if curl -sf --max-time 3 "http://127.0.0.1:${WEB_PORT}/" >/dev/null 2>&1; then
    if ! kiosk_running; then
      log "kiosk 浏览器不在运行，正在重开…"
      if bash "$ROOT/scripts/open-dashboard.sh" >>"$LOG" 2>&1; then
        log "kiosk 已重开"
      else
        log "kiosk 重开失败"
      fi
    fi
  fi
  sleep "$INTERVAL"
done
