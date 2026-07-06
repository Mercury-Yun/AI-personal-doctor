#!/usr/bin/env bash
# 板端桌面：全屏 kiosk 打开健康屏（隐藏 Ubuntu 侧栏/顶栏）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_PORT="${WEB_PORT:-5173}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:${WEB_PORT}/dashboard}"
WAIT_SEC="${WAIT_SEC:-30}"
KIOSK="${KIOSK:-1}"
HIDE_DESKTOP_UI="${HIDE_DESKTOP_UI:-1}"
CHROMIUM_PROFILE="${CHROMIUM_PROFILE:-$HOME/.cache/chromium-health-kiosk}"
LOG="${LOG:-$ROOT/logs/launcher.log}"

if [[ -z "${DISPLAY:-}" ]]; then
  export DISPLAY=:0
fi

log() { echo "[open-dashboard] $*" | tee -a "$LOG"; }

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "AI私人医生" "$1" "$2" 2>/dev/null || true
  fi
}

hide_desktop_ui() {
  [[ "$HIDE_DESKTOP_UI" == "1" ]] || return 0
  if ! command -v gsettings >/dev/null 2>&1; then
    return 0
  fi
  log "隐藏 Ubuntu 侧栏/顶栏（自动收纳）"
  gsettings set org.gnome.shell.extensions.dash-to-dock autohide true 2>/dev/null || true
  gsettings set org.gnome.shell.extensions.dash-to-dock dock-fixed false 2>/dev/null || true
  gsettings set org.gnome.shell.extensions.dash-to-dock intellihide true 2>/dev/null || true
  gsettings set org.gnome.shell.extensions.dash-to-dock extend-height false 2>/dev/null || true
  gsettings set org.gnome.desktop.interface enable-hot-corners false 2>/dev/null || true
}

wait_for_web() {
  local i=0
  while (( i < WAIT_SEC )); do
    if curl -s -m 1 -o /dev/null "http://127.0.0.1:${WEB_PORT}/" 2>/dev/null; then
      return 0
    fi
    sleep 1
    (( i++ )) || true
  done
  log "警告: 前端 ${WEB_PORT} 暂未就绪，仍尝试打开浏览器"
}

find_chromium() {
  local bin
  for bin in chromium-browser chromium google-chrome; do
    if command -v "$bin" >/dev/null 2>&1; then
      echo "$bin"
      return 0
    fi
  done
  return 1
}

kiosk_running() {
  pgrep -f "chromium.*${WEB_PORT}.*dashboard" >/dev/null 2>&1 || \
    pgrep -f "chromium.*app=http://127.0.0.1:${WEB_PORT}/dashboard" >/dev/null 2>&1
}

focus_kiosk() {
  if ! command -v wmctrl >/dev/null 2>&1; then
    return 1
  fi
  wmctrl -a "AI私人医生" 2>/dev/null && return 0
  local wid
  wid=$(wmctrl -l 2>/dev/null | grep -F ":${WEB_PORT}/dashboard" | awk '{print $1}' | head -1)
  if [[ -n "$wid" ]]; then
    wmctrl -i -a "$wid" 2>/dev/null && return 0
  fi
  return 1
}

clear_stale_chromium_lock() {
  if kiosk_running; then
    return 0
  fi
  rm -f "$CHROMIUM_PROFILE/SingletonLock" \
        "$CHROMIUM_PROFILE/SingletonCookie" \
        "$CHROMIUM_PROFILE/SingletonSocket" 2>/dev/null || true
}

open_browser() {
  local url="$1"
  local browser

  if kiosk_running; then
    log "健康屏已在运行，尝试切到前台"
    if focus_kiosk; then
      notify "已在运行" "已将健康屏切到前台"
      return 0
    fi
    log "无法聚焦旧窗口，将重启浏览器"
    pkill -f "chromium.*${WEB_PORT}" 2>/dev/null || true
    sleep 1
  fi

  browser="$(find_chromium)" || {
    if command -v xdg-open >/dev/null 2>&1; then
      log "未找到 Chromium，使用 xdg-open"
      xdg-open "$url" >>"$LOG" 2>&1 &
      notify "已打开" "使用系统默认浏览器打开健康屏"
      return 0
    fi
    log "错误: 未找到浏览器"
    notify "打开失败" "未安装 Chromium，请查看 launcher.log"
    exit 1
  }

  mkdir -p "$CHROMIUM_PROFILE"
  clear_stale_chromium_lock

  local args=(
    --user-data-dir="$CHROMIUM_PROFILE"
    --no-first-run
    --no-default-browser-check
    --disable-infobars
    --disable-session-crashed-bubble
    --disable-translate
    --overscroll-history-navigation=0
    --check-for-update-interval=31536000
  )

  if [[ "$KIOSK" == "1" ]]; then
    args+=(--kiosk --start-fullscreen --app="$url")
    log "全屏 kiosk → $url"
  else
    args+=("--app=$url")
    log "窗口模式 → $url"
  fi

  if ! "$browser" "${args[@]}" >>"$LOG" 2>&1 & then
    log "浏览器启动命令失败"
    notify "打开失败" "Chromium 未能启动，请查看 launcher.log"
    exit 1
  fi

  sleep 1
  if ! kiosk_running; then
    log "警告: 浏览器进程未检测到，可能内存不足或配置异常"
    notify "打开异常" "浏览器可能未成功启动，请查看 launcher.log"
    exit 1
  fi

  notify "已打开" "AI私人医生全屏界面"
}

hide_desktop_ui
wait_for_web
open_browser "$DASHBOARD_URL"
log "已打开。退出全屏：Alt+F4 或关闭 Chromium 窗口"
