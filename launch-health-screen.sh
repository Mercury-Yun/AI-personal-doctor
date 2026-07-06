#!/usr/bin/env bash
# 桌面双击：启动服务 + 全屏打开健康屏（带日志与桌面通知）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs/launcher.log"
mkdir -p "$ROOT/logs"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

exec >>"$LOG" 2>&1
echo "===== $(date -Is) launch-health-screen pid=$$ DISPLAY=$DISPLAY ====="

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "AI私人医生" "$1" "$2" 2>/dev/null || true
  fi
}

on_err() {
  echo "[launcher] 失败: $*"
  notify "启动失败" "请查看 logs/launcher.log"
}
trap 'on_err line $LINENO' ERR

notify "正在启动" "AI私人医生服务与全屏界面…"

export OPEN_BROWSER=1
export KIOSK=1
bash "$ROOT/scripts/start-board.sh"

notify "已启动" "健康屏应已全屏显示；若无窗口请再点一次图标"
