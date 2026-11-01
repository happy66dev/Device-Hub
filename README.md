# device-hub

把手机和电脑的运行状态汇总到一台 Windows 主机，并在 QQ 群里用 @机器人 + 命令查询。

## 组成

| 模块 | 语言 | 职责 |
| --- | --- | --- |
| `server/` | Python 3.12 + FastAPI + SQLite | 接收上报、整理入库、提供查询、驱动 QQ 机器人 |
| `client-windows/` | Python 3.12 + psutil | 采集系统版本/硬件信息/前台应用使用时长，定时上报 |
| `client-android/` | Kotlin | 采集机型/电量/应用使用情况，定时上报 |
| QQ 通道 | NapCat（OneBot 11） | 正向 WebSocket，服务端作为客户端连接 |
| 官方 QQ 通道（可选） | 官方 QQ Bot v2 | 平台 WebSocket + HTTPS，与 NapCat 并存，见 `docs/qqbot.md` |

## 数据流

```
Android / Windows 客户端
        │  HTTP POST /api/v1/report（共享 token）
        ▼
   FastAPI 服务端 ──► SQLite（设备、上报记录、使用时长、电量）
        │
        │  查询层
        ▼
   命令渲染（文本摘要 / 分页 / 图片）
        ▲
        │  归一化消息（NormalizedMessage）
    ┌───┴────────────┐
    │                │
 NapCat         官方 QQ Bot
（OneBot 11）    （WebSocket + HTTPS）
```

## 当前状态

| 部分 | 状态 |
| --- | --- |
| 服务端上报与查询 | 已完成，单元 + 集成测试 473 例（其中 5 例为已停用的 A 方案用例，跳过） |
| QQ 机器人（命令 / 分页 / 图片） | 已完成，用假 NapCat 服务端跑通端到端 |
| 官方 QQ Bot 通道 | 已完成，`test_qqbot.py` 28 例覆盖换票/网关/心跳/Resume/去重/发图/免 @ 门控 |
| Web 看板（白色主题 + 顶部功能栏：概览 / 设备 / 时间轴 / 应用排行 / 命令测试 / 配置 / 设置） | 已完成，零外部依赖，时间轴按图标混合色上色、真正跨设备的应用才用深浅区分（单设备应用保持原色），排行可切总排行 / 按设备 / 按组且同名软件跨设备合并成一行，截图见 `docs/dashboard-*.png` |
| 命令测试（QQ 掉线时在页面上验命令） | 已完成，`POST /api/v1/bot/command`，支持选择通道、模拟未 @ 与角色 |
| 配置页（改 config.yaml / 测连接 / 重启服务） | 已完成，`GET|PATCH /api/v1/settings`、`POST /api/v1/bot/test`、`POST /api/v1/server/restart`，改值保留注释 |
| 时间口径 | 服务端向阿里云 NTP 对齐，落库时间戳全用服务端收到的时刻；看板用 `/api/v1/time` 的 `server_now` 与 `tz_offset_minutes`，客户端和浏览器时钟都不参与 |
| 角色与 RDP 统计门控（含 scrcpy 投屏识别） | 已完成，`test_gating.py` 12 例 + 上报门控 8 例，并实测 scrcpy 窗口匹配成功 |
| 窗口上报 | 已完成，Windows 上报全部可见窗口（应用名/标题/最小化/前台），历史留存可清理 |
| 应用图标 | 已完成，三种 Win32 方式依次兜底抠 32×32 PNG，前台应用 + 窗口里所有应用都补图，服务端按应用名+小写包名存 PNG 并自动重算历史键 |
| 设备组（人） | 已完成，服务端持久化 + 前端可编辑，组内顺序即优先级，重叠时高优先级保留 |
| Windows 采集端 | 已完成，测试 143 例通过；exe 窗口化打包，`--debug` 弹控制台看日志 |
| Android 采集端 | 已完成并通过构建，单元测试 101 例通过；带极简界面（实时服务状态徽标 + 上报状态与待补报秒数 + 权限快捷入口 + 采集/上报日志 + 采集/上报频率），缺权限不让启动、开机自启失效时自动补拉，息屏不计时并按息屏满 1 分钟上报 AFK |
| 真实 NapCat 联调 | 待重启 NapCat 使 7999 端口生效 |
| Android 真机安装 | 待主人在手机上允许 USB 安装（MIUI 策略拦截） |

## 文档

- [部署与联调手册](docs/deploy.md)
- [上报协议](docs/protocol.md)
- [官方 QQ Bot 通道](docs/qqbot.md)
- [Android 端设计与实现](docs/android.md)
- [Android 构建手册](docs/android-build.md)
- [待补充清单](docs/TODO.md)

使用排行图片的样式示例：`docs/sample-usage.png`。
Web 看板截图：`docs/dashboard-overview.png`（概览）、`docs/dashboard-devices.png`（设备与详情）、
`docs/dashboard-timeline.png`（时间轴）、`docs/dashboard-rankings.png`（应用排行）、`docs/dashboard-windows.png`（窗口列表）、`docs/dashboard-storage.png`（存储清理）、`docs/dashboard-people.png`（设备组编辑）、`docs/dashboard-bot.png`（命令测试）、`docs/dashboard-config.png`（配置）、`docs/dashboard-settings.png`（设置）。

## 目录结构

```
device-hub/
├─ server/
│  ├─ app/            服务端业务代码（配置、数据库、上报、查询、机器人）
│  ├─ tests/          单元测试
│  ├─ config.example.yaml  服务端配置模板（复制成 config.yaml 再改）
│  ├─ config.yaml     本机真实配置，含密钥所以不进版本库
│  └─ requirements.txt
├─ client-windows/    Windows 采集端
├─ client-android/    Android 采集端（Kotlin + Gradle）
└─ docs/              协议与部署文档
```

## 快速开始

### 0. 本机一键跑起来（Windows）

服务端和采集端各有一个启动脚本，双击即可，也可以挂到开机启动：

| 脚本 | 作用 | 日志 |
| --- | --- | --- |
| `server\start-server.bat` | 启动服务端（`0.0.0.0:8080`） | `server\data\server.log` |
| `client-windows\start-agent.bat` | 启动采集端常驻上报 | 控制台 |

开机自启：把这两个 `.bat` 的快捷方式丢进 `shell:startup`（本机已放好两份，删掉即可取消）。

采集端的配置在同目录 `config.json`，最少要有 `server_url` 与 `ingest_token`，其余字段可缺省。
`afk_threshold_seconds` 默认 60 秒——键鼠空闲超过 1 分钟就停止计时，动一下鼠标立刻恢复；锁屏算立即停表，`afk` 一变就立刻补一次上报。
`report_interval_seconds` 是上报频率，可填 **10–60 秒**（默认 60），也可以临时用 `--report-interval 15` 覆盖；窗口快照另外按 30 秒节流，所以把上报调到 10 秒也不会把 CPU 拉满。上限 60 秒是因为服务端心跳超时是 180 秒，再慢就会被误判离线。

使用时长按**真实流逝时间**累计（不是名义采样周期），所以采样偶发变慢也不会少记；前台窗口一时抓不到（UAC 安全桌面、切换桌面、窗口重建）时沿用上一个应用，最多 2 分钟。
上报失败（断网、服务端没起、口令填错）时这一批数据不会丢：客户端把它缓存起来并落盘，下一次上报一起补发，进程重启也能恢复。

### 1. 服务端

```powershell
cd D:\device-hub\server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

默认监听 `0.0.0.0:8080`，数据库文件落在 `server/data/device_hub.db`。

### 2. Windows 客户端

```powershell
cd D:\device-hub\client-windows
pip install -r requirements.txt
python -m agent --server http://192.168.2.245:8080 --token 改成你的token
```

打包成 exe（单文件、窗口化，双击不弹黑窗口）：

```powershell
.\build.ps1
.\dist\device-hub-agent.exe            # 静默常驻，日志写 dist\agent.log
.\dist\device-hub-agent.exe --debug    # 弹出控制台窗口，日志实时滚
```

### 3. Android 客户端

用 Android Studio 打开 `client-android/`，或参考 `docs/android-build.md` 用命令行构建。

首次启动需要手动授予「使用情况访问权限」，否则无法读取应用使用记录。

App 里有个极简界面：状态区（配置/使用情况权限/通知权限/电池优化/日志行数）、
地址与口令输入框、启停按钮、四个权限快捷入口，以及「查看运行日志」页（最近 500 行，可复制清空）。
完整的模块划分、保活策略与复用方案见 [docs/android.md](docs/android.md)。

## 机器人命令

NapCat 通道下所有命令必须在白名单群里 @机器人 才会响应，且发送者不能在黑名单中。
官方通道默认同样要求 @，可以在 `qqbot.free_command_group_openids` 里指定免 @ 的群。

| 命令 | 说明 |
| --- | --- |
| `/happy在干嘛` | happy 现在在做什么：在用 / 挂机 / 不在 三档状态 |
| `/happy干了什么` | happy 近 24 小时用过的应用前 10 名 |
| `/happy设备` | happy 名下每台设备的在线状态、电量与近 24 小时时长 |
| `/happy帮助` | 显示命令列表 |
| `/看看happy <全部/设备名> <排行榜/时间轴> [时间范围/起止时刻]` | 把看板页面截成图片：排行榜支持 24小时（默认）/30分钟/2小时/6小时/1天/3天/7天，时间轴支持今天（默认）/日期/日期+起止时刻 |

happy 认的是 `bot.happy_group` 指定的设备组（默认 `happy`，可在看板「设置 → happy 命令」里改），
组内顺序就是优先级：判定状态时先按 3 分钟窗口找在用的设备，找不到再按挂机、不在逐级退让喵。

命令文案是「模板 + 占位符」，支持 `{名称}` 取值、`{时长|时长}` 格式化、
`{若 …}{否则}{/若}` 条件与 `{查询 设备 有使用=1分钟 行=设备行}` 这类伪代码查询，
模板硬编在 `app/bot/commands.py`，语法见 `docs/bot-templates.md`。

图片不是自己画的，而是用无头浏览器截真实看板（只截内容区，不带顶部功能栏），
所以图永远和 webui 一致。需要系统里有 Edge/Chrome 和 PATH 里的 `node`。

## 配置要点

- `server/config.yaml` 中的 `whitelist_groups` 是允许响应的 QQ 群号列表（NapCat 通道）。
- `whitelist_group_openids` 是官方通道的群白名单，标识不是群号而是 `group_openid`。
- `blacklist_users` / `blacklist_member_openids` 分别是两条通道的用户黑名单。
- `ingest.token` 是客户端上报用的共享口令，必须与客户端一致。
- `napcat.token` 必须与 NapCat 里为该 WebSocket 服务端配置的 token 一致。
- `qqbot.app_id` / `qqbot.app_secret` 是官方通道凭据，`qqbot.enabled` 默认关闭。

## 测试

```powershell
# 服务端（含机器人端到端测试）
cd D:\device-hub\server
.\.venv\Scripts\python.exe -m pytest -q

# Windows 采集端
cd D:\device-hub\client-windows
.\.venv\Scripts\python.exe -m pytest -q
```

## 隐私与安全

- 上报走明文 HTTP，仅建议在内网或 Tailscale 等加密隧道内使用。
- 未做设备与 QQ 号绑定：白名单群内任何成员都能查询任意设备的状态。
- 黑名单在 WebUI「配置 → 黑名单」里管理，拉黑后**立刻生效、不用重启**，全局生效；
  `config.yaml` 里写死的条目也照常生效，两者取并集。
- 不知道对方 openid 时看同一页的「最近发言」列表：NapCat 通道显示群名片或昵称，
  **官方通道平台只给 openid，只能显示前 8 位**，让对方再发一条命令即可按时间对上人。
- 服务端默认保留明细 7 天、聚合数据 30 天，可在配置中调整。

## 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

```
MIT License

Copyright (c) 2026 happy
```

允许自由使用、修改、分发与商用，唯一要求是保留版权声明与许可声明。软件按「原样」提供，不含任何担保。

第三方依赖各自遵循其原有许可证，详见 `server/requirements.txt`、`client-windows/requirements.txt` 与 `client-android/build.gradle.kts`。
