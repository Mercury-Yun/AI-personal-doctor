#!/usr/bin/env bash
# 检测 FastAPI 8000 是否存活，挂掉则自动拉起
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

API_PORT="${API_PORT:-8000}"
INTERVAL="${API_WATCHDOG_INTERVAL:-30}"
STARTUP_GRACE="${API_STARTUP_GRACE:-120}"
UVICORN_MATCH="uvicorn backend.main:app"

log() {
  echo "[api-watchdog] $(date '+%F %T') $*" >> "$ROOT/logs/api-watchdog.log"
}

start_api_once() {
  (
    cd "$ROOT"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    export REMINDER_ENABLED REMINDER_TZ TZ
    export CHAT_USE_CLOUD_LLM=1
    export DASHSCOPE_API_KEY DASHSCOPE_BASE_URL DASHSCOPE_MODEL DASHSCOPE_VISION_MODEL
    export DASHSCOPE_ENABLE_THINKING
    export TTS_USE_CLOUD COSYVOICE_MODEL COSYVOICE_VOICE COSYVOICE_FORMAT
    export COSYVOICE_SAMPLE_RATE COSYVOICE_SPEECH_RATE COSYVOICE_BATCH_MAX_CHARS
    export COSYVOICE_FIRST_BATCH_CHARS CLOUD_WARMUP TTS_PLAY_COMMAND
    export WAKE_ENABLED VOICE_WAKE_WORD
    nohup uvicorn backend.main:app --host 0.0.0.0 --port "$API_PORT" \
      >> "$ROOT/logs/api.log" 2>&1 </dev/null &
  )
}

api_healthy() {
  curl -sf --max-time 5 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1
}

api_process_age_sec() {
  local pid age
  pid=$(pgrep -f "$UVICORN_MATCH" 2>/dev/null | head -1 || true)
  if [[ -z "$pid" ]]; then
    echo 999999
    return
  fi
  age=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ' || echo 999999)
  echo "${age:-999999}"
}

stop_stale_api() {
  local pids
  pids=$(pgrep -f "$UVICORN_MATCH" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    log "stopping stale uvicorn: $pids"
    pkill -f "$UVICORN_MATCH" 2>/dev/null || true
    sleep 2
  fi
}

mkdir -p "$ROOT/logs"
PIDFILE="$ROOT/logs/api-watchdog.pid"
echo $$ >"$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

while true; do
  if ! api_healthy; then
    if pgrep -f "$UVICORN_MATCH" >/dev/null 2>&1; then
      age=$(api_process_age_sec)
      if [[ "$age" -lt "$STARTUP_GRACE" ]]; then
        log "api still starting (${age}s < ${STARTUP_GRACE}s), waiting..."
        sleep "$INTERVAL"
        continue
      fi
      log "api unhealthy but process alive, restarting..."
      stop_stale_api
    else
      log "api offline, starting..."
    fi
    start_api_once
    sleep 5
    if api_healthy; then
      log "api recovered"
    else
      log "api restart failed, will retry"
    fi
  fi
  sleep "$INTERVAL"
done
