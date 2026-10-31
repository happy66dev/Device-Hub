"""让 `python -m app` 直接启动服务端喵。

为什么不直接用 uvicorn 命令行：监听地址与端口写在 config.yaml 里，
用这个入口可以保证"配置在哪启动都一样"，避免命令行参数与配置打架喵。
"""

from __future__ import annotations

import uvicorn

from .config import load_config
from .main import create_app

if __name__ == "__main__":
    # 先读配置，拿到监听地址、端口与日志级别喵
    server_config = load_config()
    # 用配置创建应用实例，避免重复读取配置文件喵
    application = create_app(server_config)
    # 启动 ASGI 服务器喵
    uvicorn.run(
        application,
        host=server_config.server.host,
        port=server_config.server.port,
        log_level=server_config.server.log_level,
    )
