#!/usr/bin/env bash
# 快速恢复 Aw, snap! 崩溃后的全屏健康屏
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
pkill -f "chromium.*5173" 2>/dev/null || true
sleep 1
bash "$ROOT/scripts/open-dashboard.sh"
