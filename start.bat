@echo off
setlocal
rem ============================================
rem  Data QC / Preprocess Workbench - launcher (Windows)
rem  Double-click to start; Ctrl+C or close window to stop.
rem  (ASCII-only on purpose: avoids codepage/encoding parse errors)
rem ============================================

cd /d "%~dp0"

if "%PORT%"=="" set PORT=8877

echo.
echo ============================================
echo   Data QC / Preprocess Workbench
echo ============================================
echo.

rem --- Check Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found. Install Python 3.10+ and tick "Add to PATH".
  echo.
  pause
  exit /b 1
)

rem --- Install / update deps (fast if already installed) ---
echo [1/2] Checking dependencies...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [WARN] dependency install may have failed; trying to start anyway...
)

echo [2/2] Starting server on port %PORT% ...
echo.
echo   URL:  http://127.0.0.1:%PORT%
echo   Browser opens automatically once the server is ready.
echo   Stop: press Ctrl+C here, or close this window.
echo.

rem --- Background: wait until the port accepts connections, then open browser ---
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$p=%PORT%; for($i=0;$i -lt 120;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $c.Close(); Start-Process ('http://127.0.0.1:'+$p); break } catch { Start-Sleep -Milliseconds 500 } }"

rem --- Run server in foreground (cwd already set to script dir) ---
python -m uvicorn server.app:app --host 127.0.0.1 --port %PORT% --app-dir .

echo.
echo Server stopped.
pause
