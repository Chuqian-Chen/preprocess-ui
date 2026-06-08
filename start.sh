#!/bin/bash
# 数据质控与预处理可视化工作台
cd "$(dirname "$0")"
PORT="${PORT:-8877}"
pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt
echo "Open http://127.0.0.1:${PORT}"
exec python -m uvicorn server.app:app --host 0.0.0.0 --port "${PORT}" --app-dir "$(pwd)"
