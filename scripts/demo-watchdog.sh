#!/usr/bin/env bash
# 仅当 demo 进程不存在时拉起；绝不因 health 超时杀正在录音/唤醒的 demo
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

DEMO_DIR="${DEMO_DIR:-$HOME/Qwen_test}"
DEMO_BIN="${DEMO_BIN:-$DEMO_DIR/demo}"
DEMO_ENCODER="${DEMO_ENCODER:-qwen2_vl_2b_vision_rk3588.rknn}"
DEMO_LLM="${DEMO_LLM:-Qwen2-VL-2B-Instruct.rkllm}"
DEMO_MAX_TOKENS="${DEMO_MAX_TOKENS:-180}"
DEMO_MAX_CONTEXT="${DEMO_MAX_CONTEXT:-1024}"
DEMO_CONTROL_PORT="${DEMO_CONTROL_PORT:-8765}"
INTERVAL="${DEMO_WATCHDOG_INTERVAL:-20}"

log() {
  echo "[demo-watchdog] $(date '+%F %T') $*" >> "$ROOT/logs/demo.log"
}

demo_running() {
  pgrep -f "Qwen_test/demo" >/dev/null 2>&1 || pgrep -f "${DEMO_BIN}" >/dev/null 2>&1
}

start_demo_once() {
  if demo_running; then
    return
  fi
  log "starting demo..."
  local wake_daemon="${DEMO_WAKE_DAEMON:-1}"
  if [[ -f "$ROOT/logs/.photo_mode_active" ]]; then
    wake_daemon=0
  fi
  (
    cd "$DEMO_DIR"
    export DEMO_CONTROL_PORT
    export DEMO_DAEMON=1
    export DEMO_WAKE_DAEMON="$wake_daemon"
    export CAMERA_DEVICE_INDEX="${CAMERA_DEVICE_INDEX:-11}"
    export CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-640}"
    export CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-480}"
    export CAMERA_WARMUP_FRAMES="${CAMERA_WARMUP_FRAMES:-10}"
    export CAMERA_WARMUP_SLEEP_MS="${CAMERA_WARMUP_SLEEP_MS:-30}"
    export CAMERA_AF_STEP="${CAMERA_AF_STEP:-8}"
    export CAMERA_AF_SETTLE_MS="${CAMERA_AF_SETTLE_MS:-120}"
    export CAMERA_AF_EARLY_EXIT="${CAMERA_AF_EARLY_EXIT:-1}"
    export VAD_MIN_SILENCE_SEC="${VAD_MIN_SILENCE_SEC:-1.4}"
    export ASR_SILENCE_END_MS="${ASR_SILENCE_END_MS:-2200}"
    export ASR_MAX_AFTER_SPEECH_SEC="${ASR_MAX_AFTER_SPEECH_SEC:-25}"
    export DEMO_SKIP_NPU="${DEMO_SKIP_NPU:-1}"
    nohup "$DEMO_BIN" "$DEMO_ENCODER" "$DEMO_LLM" "$DEMO_MAX_TOKENS" "$DEMO_MAX_CONTEXT" \
      >> "$ROOT/logs/demo.log" 2>&1 </dev/null &
  )
}

offline_streak=0

while true; do
  if demo_running; then
    offline_streak=0
  else
    offline_streak=$((offline_streak + 1))
    if (( offline_streak >= 2 )); then
      start_demo_once
      offline_streak=0
      sleep 12
    fi
  fi
  sleep "$INTERVAL"
done
