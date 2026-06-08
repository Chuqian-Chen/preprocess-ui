@echo off
chcp 65001 >nul
setlocal
rem ============================================
rem  数据质控 · 预处理工作台 — 一键启动 (Windows)
rem  双击本文件即可启动；关闭窗口或按 Ctrl+C 停止
rem ============================================

cd /d "%~dp0"

if "%PORT%"=="" set PORT=8877

echo.
echo ============================================
echo   数据质控 · 预处理工作台
echo ============================================
echo.

rem --- 检查 Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 3.10+ 并加入 PATH。
  echo.
  pause
  exit /b 1
)

rem --- 安装/更新依赖（已装会很快跳过）---
echo [1/2] 检查并安装依赖...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [警告] 依赖安装可能未完全成功，仍尝试启动...
)

echo [2/2] 启动服务 (端口 %PORT%)...
echo.
echo   浏览器打开:  http://127.0.0.1:%PORT%
echo   停止服务:    在本窗口按 Ctrl+C，或直接关闭窗口
echo.

rem --- 3 秒后自动打开浏览器（后台），然后前台运行服务 ---
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%PORT%"

python -m uvicorn server.app:app --host 127.0.0.1 --port %PORT% --app-dir "%~dp0"

echo.
echo 服务已停止。
pause
