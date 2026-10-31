"""device-hub 服务端应用包。

模块划分：
- config   读取并校验 config.yaml
- db       SQLite 连接、建表与时间工具
- models   上报数据的强类型定义
- ingest   把一次上报落库
- queries  面向命令层的只读查询
- main     FastAPI 应用与路由
"""
