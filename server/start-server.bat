@echo off
rem device-hub 服务端启动脚本：双击即可常驻，日志写到 data\server.log
setlocal
cd /d "%~dp0"

rem 优先用虚拟环境里的 Python，没有就退回系统 Python
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem 喵~注意：日志重定向到文件时 Python 的 stdout 会退化成 GBK，中文全变乱码，
rem 这里强制 UTF-8，日志才能正常阅读
set "PYTHONIOENCODING=utf-8"

rem 日志目录必须先存在，否则重定向会失败
if not exist "data" mkdir "data"

echo 正在启动 device-hub 服务端（端口 8080），日志：data\server.log
"%PY%" -m app >> "data\server.log" 2>&1
endlocal