@echo off
rem device-hub Windows 采集端启动脚本：双击即可常驻上报
setlocal
cd /d "%~dp0"

rem 优先用虚拟环境里的 Python，没有就退回系统 Python
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo 正在启动 device-hub 采集端，Ctrl+C 停止
"%PY%" -m agent %*
endlocal