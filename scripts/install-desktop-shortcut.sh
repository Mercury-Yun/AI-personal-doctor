#!/usr/bin/env bash
# 在板端桌面安装「AI私人医生」快捷方式
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/desktop/AI-Personal-Doctor.desktop"
DESKTOP_CANDIDATES=(
  "${DESKTOP_DIR:-$HOME/Desktop}"
  "$HOME/Desktop"
  "$HOME/桌面"
)
APP_DIR="$HOME/.local/share/applications"

install_one() {
  local dir="$1"
  local target="$dir/AI-Personal-Doctor.desktop"
  mkdir -p "$dir"
  sed "s|@HOME@|$HOME|g" "$SOURCE" > "$target"
  chmod +x "$target"

  if command -v gio >/dev/null 2>&1; then
    gio set "$target" metadata::trusted true 2>/dev/null || true
  fi
  echo "  → $target"
}

echo "安装 AI私人医生 桌面快捷方式…"
for dir in "${DESKTOP_CANDIDATES[@]}"; do
  [[ -d "$dir" || "$dir" == "$HOME/Desktop" || "$dir" == "$HOME/桌面" ]] || continue
  install_one "$dir"
done
install_one "$APP_DIR"

echo ""
echo "若双击仍无反应：在图标上右键 →「允许启动」/ Allow Launching"
echo "或终端执行: bash $ROOT/scripts/launch-health-screen.sh"
echo "日志: $ROOT/logs/launcher.log"
