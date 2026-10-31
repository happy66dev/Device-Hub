"""Windows 采集端。

模块划分：
- config     配置读写与校验
- device_id  设备唯一标识的生成与持久化
- collector  硬件信息、电量、前台窗口采集
- usage      使用时长增量累计
- reporter   组装并发送上报请求
- main       主循环与命令行入口
"""
