#!/usr/bin/env bash
# RK3588 板端首次安装（无 conda 时使用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/4] 创建 Python 虚拟环境（复用系统 torch/numpy）..."
python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/4] 安装 Python 依赖..."
pip install -U pip
pip install -r requirements-board.txt

echo "[3/4] 初始化 SQLite..."
python -m backend.init_db

echo "[4/4] 安装前端依赖 (Vite 4，兼容 Node 16)..."
if command -v npm >/dev/null 2>&1; then
  rm -rf node_modules package-lock.json
  npm install
else
  echo "警告: 未找到 npm，请手动安装 Node.js 后执行 npm install"
fi

echo ""
echo "完成。启动方式："
echo "  source .venv/bin/activate"
echo "  # 云端化版本已移除 DEMO_CONTROL_URL"
echo "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
echo "  npm run dev"
