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
  echo [错误] 未找到 python，请先安装 Python 3.10+ 并在安装时勾选「Add to PATH」。
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
echo   服务地址:  http://127.0.0.1:%PORT%
echo   就绪后会自动打开浏览器；停止服务请按 Ctrl+C 或关闭本窗口。
echo.

rem --- 后台轮询：等端口真正可连后再打开浏览器（避免开太早显示"拒绝连接"）---
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$p=%PORT%; for($i=0;$i -lt 120;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $c.Close(); Start-Process ('http://127.0.0.1:'+$p); break } catch { Start-Sleep -Milliseconds 500 } }"

rem --- 前台运行服务（工作目录已切到脚本所在目录，用 .）---
python -m uvicorn server.app:app --host 127.0.0.1 --port %PORT% --app-dir .

echo.
echo 服务已停止。
pause
