#!/usr/bin/env bash
# 检测 demo 8765 是否存活，挂掉则自动拉起（仅 demo，不动 API/前端）
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
INTERVAL="${DEMO_WATCHDOG_INTERVAL:-30}"

log() {
  echo "[demo-watchdog] $(date '+%F %T') $*" >> "$ROOT/logs/demo.log"
}

start_demo_once() {
  (
    cd "$DEMO_DIR"
    export DEMO_CONTROL_PORT
    export DEMO_DAEMON=1
    export CAMERA_DEVICE_INDEX="${CAMERA_DEVICE_INDEX:-11}"
    export CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-1280}"
    export CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-720}"
    export CAMERA_WARMUP_FRAMES="${CAMERA_WARMUP_FRAMES:-18}"
    export CAMERA_WARMUP_SLEEP_MS="${CAMERA_WARMUP_SLEEP_MS:-40}"
    export CAMERA_AF_STEP="${CAMERA_AF_STEP:-6}"
    export CAMERA_AF_SETTLE_MS="${CAMERA_AF_SETTLE_MS:-180}"
    export CAMERA_AF_EARLY_EXIT="${CAMERA_AF_EARLY_EXIT:-1}"
    export VAD_MIN_SILENCE_SEC="${VAD_MIN_SILENCE_SEC:-1.4}"
    export ASR_SILENCE_END_MS="${ASR_SILENCE_END_MS:-2200}"
    export ASR_MAX_AFTER_SPEECH_SEC="${ASR_MAX_AFTER_SPEECH_SEC:-25}"
    export DEMO_SKIP_NPU="${DEMO_SKIP_NPU:-1}"
    nohup "$DEMO_BIN" "$DEMO_ENCODER" "$DEMO_LLM" "$DEMO_MAX_TOKENS" "$DEMO_MAX_CONTEXT" \
      >> "$ROOT/logs/demo.log" 2>&1 </dev/null &
  )
}

while true; do
  if ! curl -sf --max-time 3 "http://127.0.0.1:${DEMO_CONTROL_PORT}/health" >/dev/null 2>&1; then
    if pgrep -f "${DEMO_BIN}" >/dev/null 2>&1; then
      # demo 仍在启动/忙碌，勿重复拉起（避免双进程抢内存、反复 snap）
      sleep "$INTERVAL"
      continue
    fi
    log "demo offline, restarting..."
    start_demo_once
  fi
  sleep "$INTERVAL"
done
