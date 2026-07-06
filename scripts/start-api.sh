#!/usr/bin/env bash
# 本地开发：启动 FastAPI（云端化版本，无需 demo）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export REMINDER_ENABLED="${REMINDER_ENABLED:-1}"

echo "Starting FastAPI on :8000 (cloud-only mode)"
# 优先使用项目内 venv 的 Python，避免系统 python3 缺依赖（No module named uvicorn）
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
exec "$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
