#!/bin/bash
# 数据质控与预处理可视化工作台 — Linux / macOS 启动脚本
# （Windows 请双击 start.bat，本 .sh 在 Windows 上双击不会用 bash 运行）
cd "$(dirname "$0")"
PORT="${PORT:-8877}"
pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt
echo "Open http://127.0.0.1:${PORT}"

# 后台：等端口就绪后再打开浏览器（避免开太早连接被拒）
(
  for _ in $(seq 1 120); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then
      exec 3>&- 3<&-
      (xdg-open "http://127.0.0.1:${PORT}" || open "http://127.0.0.1:${PORT}") >/dev/null 2>&1
      break
    fi
    sleep 0.5
  done
) &

exec python -m uvicorn server.app:app --host 0.0.0.0 --port "${PORT}" --app-dir "$(pwd)"
