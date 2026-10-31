# 把 Windows 采集端打包成单个 exe，方便在没有 Python 的机器上跑喵
# 用法：在 client-windows 目录执行  .\build.ps1
$ErrorActionPreference = 'Stop'

# 切到脚本所在目录，保证相对路径正确喵
Set-Location $PSScriptRoot

# 喵~防御：虚拟环境不存在时先创建并装依赖喵
if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
    python -m venv .venv
    & '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
}

# 安装打包工具（只在打包时需要，不进运行时依赖）喵
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q -i https://mirrors.aliyun.com/pypi/simple/ pyinstaller

# 执行打包：单文件、窗口化（--noconsole），入口是 agent 包喵
# 喵~防御：窗口化后没有控制台，日志写 agent.log；运行时加 --debug 才会弹控制台窗口喵
& '.\.venv\Scripts\pyinstaller.exe' `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name 'device-hub-agent' `
    --paths . `
    'agent\__main__.py'

# 提示产物位置与两种启动方式喵
Write-Host '打包完成：dist\device-hub-agent.exe'
Write-Host '  静默运行：dist\device-hub-agent.exe'
Write-Host '  看日志：  dist\device-hub-agent.exe --debug'
Write-Host '  日志文件：dist\agent.log（与 exe 同目录）'
