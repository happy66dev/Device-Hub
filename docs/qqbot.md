# 官方 QQ Bot 通道

服务端支持两条并存的 QQ 通道，业务逻辑完全相同，只是收发协议不一样：

| 通道 | 配置段 | 传输 | 群标识 | 能否 @ 人 |
| --- | --- | --- | --- | --- |
| NapCat（OneBot 11） | `napcat` | 本机 WebSocket，需跑 QQ 客户端 | 整数群号 | 能 |
| 官方 QQ Bot | `qqbot` | 平台 WebSocket + HTTPS | `group_openid` 字符串 | 不能 |

两条通道可以同时开启。想少维护一个 QQ 客户端就用官方通道；想要 @ 提醒、群号可读、
不受平台配额限制就继续用 NapCat。

## 1. 结构

```
QQ 群 ──┬─ NapCat ──WS──┐
        │                ├─→ channel.py 归一化 ─→ router.py 命令处理 ─→ queries.py
        └─ 官方网关 ─WS──┘                          │
                                                     └─→ 各通道 send_text / send_image
```

- `app/bot/channel.py`：协议无关的 `NormalizedMessage`、准入原因码、事件归一化函数；
- `app/bot/napcat.py`：OneBot 客户端 + `NapCatChannel` 适配器；
- `app/bot/qqbot.py`：官方 token/网关/发消息 + `QQBotChannel` 适配器；
- `app/bot/runner.py`：按配置启动通道，收到消息后统一走 `router.inspect_normalized`；
- `app/bot/router.py`：白名单、黑名单、@ 判断、前缀解析、命令实现。

业务层只认 `NormalizedMessage`，新增通道只要实现 `BotChannel` 协议即可。

## 2. 配置

```yaml
qqbot:
  enabled: true                 # 默认 false，没凭据时保持关闭
  app_id: "1020xxxx"
  app_secret: "你的 AppSecret"   # 等价于机器人密码，别提交进仓库
  api_base: "https://api.bot.qq.com"   # 沙箱用 https://sandbox.api.sgroup.qq.com
  intents: 33554432             # GROUP_AND_C2C_EVENT，群与单聊消息
  token_refresh_margin_seconds: 60
  heartbeat_slack_seconds: 5
  request_timeout_seconds: 10.0
  reconnect_seconds: 10
  log_openids: true             # 把收到的 openid 打进日志，方便配白名单
  debug_events: false           # 把原始事件与准入结论打进日志，排查「@ 了却不回复」
  free_command_group_openids: []
  free_command_require_prefix: true
  free_command_min_role: "any"  # any / admin / owner

acl:
  whitelist_group_openids: []   # 官方通道的群白名单
  blacklist_member_openids: []  # 官方通道的用户黑名单
  private_user_openids: []      # 允许单聊的 user_openid，留空表示单聊全禁
```

`napcat` 段的整数群号与 `qqbot` 段的 openid 是两套命名空间，`acl.for_channel()` 会按通道
取对应的那份，填错地方不会互相串用。

## 3. 鉴权与连接

1. `POST /app/getAppAccessToken`，body `{"appId": ..., "clientSecret": ...}`，返回
   `access_token` 与 `expires_in`（7200 秒）。**失败时 HTTP 仍是 200**，要看 body 里的 `code`。
2. 有效期剩 `token_refresh_margin_seconds` 时自动换票；换票失败会退避 60 秒再试。
3. `GET /gateway/bot` 拿 `wss://` 地址。
4. 连上后服务端先发 `op=10 Hello`（带 `heartbeat_interval` 毫秒），客户端回 `op=2 Identify`：

```json
{"op": 2, "d": {"token": "QQBot <access_token>", "intents": 33554432, "shard": [0, 1],
                "properties": {"$os": "linux", "$browser": "device-hub", "$device": "server"}}}
```

5. 收到 `op=0 t=READY` 后记下 `session_id`，之后每条下行都带自增 `s`（序号）。
6. 心跳是**应用层**的：按 `heartbeat_interval - heartbeat_slack_seconds` 定时发
   `{"op": 1, "d": <最后收到的 s>}`，不要用 WebSocket 自带的 ping。
7. 断线重连带 `session_id` 与最后序号发 `op=6 Resume`；会话过期（4006/4007）才重新 Identify。

关闭码处理：

| 码 | 含义 | 处理 |
| --- | --- | --- |
| 4006 / 4007 | 会话失效、token 无效 | 重新 Identify |
| 4008 / 4009 | 心跳超时、序号越界 | 用 Resume 重试，失败则 Identify |
| 4010–4014 | 参数或 intents 不合法 | 记日志后放弃，配置问题重启也没用 |
| 4914 / 4915 | 机器人已下架 / 被封禁 | 记日志后放弃 |

## 4. 收消息

订阅 `GROUP_AND_C2C_EVENT`（`1 << 25`）后能收到：

| 事件 | 场景 | 关键字段 |
| --- | --- | --- |
| `GROUP_AT_MESSAGE_CREATE` | 群里 @机器人（默认模式） | `group_openid`、`author.member_openid`、`content` |
| `GROUP_MESSAGE_CREATE` | 群里任意消息（仅全量模式） | 同上，`content` 里带 `<@!openid>` 占位符 |
| `C2C_MESSAGE_CREATE` | 单聊 | `author.user_openid`、`content` |

- 默认模式只能收到 @机器人的消息，`mentioned` 恒为 `true`；
- 全量模式下 `content` 里的 `<@!xxx>` 需要自己剥掉再判断是不是 @ 了自己
  （`channel.strip_mention_placeholders` / `detect_self_mention`）；
- 事件 `id` 用于去重：平台在重连或重试时可能重复推送同一条消息。

## 5. 发消息

```json
POST /v2/groups/{group_openid}/messages
{"msg_type": 0, "content": "回复文本", "msg_id": "被动回复必填", "msg_seq": 1}
```

- 带 `msg_id` 是**被动回复**，5 分钟内有效、同一条消息最多回 5 条；不带就是**主动消息**，
  受配额限制（每群每分钟 20 条、每天 1000 条，全局每分钟 60 条）。
- `msg_seq` 必须在同一条 `msg_id` 下递增，否则会被平台去重丢弃，`ReplyCounter` 负责这件事。
- 图片不能内联 base64：先 `POST /v2/groups/{openid}/files` 上传（`file_type=1`、
  `srv_send_msg=false`）拿 `file_info`，再发 `{"msg_type": 7, "media": {"file_info": "..."}}`。
- 文本上限 1800 字，超出会被截断并补省略号。
- 官方接口**没有 at 字段**，无法在回复里 @ 提问的人；`send_text(mention_user_key=...)`
  对官方通道是空操作，NapCat 通道则会真的 @。
- 错误要看 `err_code`（业务）而不是 HTTP 状态；429 表示限流，需要退避。

## 6. 准入规则

一条消息要被响应，必须同时满足：

1. 会话在白名单里：群聊看 `acl.whitelist_group_openids`，单聊看 `acl.private_user_openids`；
2. 用户不在 `acl.blacklist_member_openids`；
3. 群里 @ 了机器人，或该群在 `qqbot.free_command_group_openids` 里；
4. 免 @ 群里仍要求 `/` 或 `／` 前缀（`free_command_require_prefix`）；
5. 免 @ 群里角色不低于 `free_command_min_role`。

任一不满足就静默忽略，原因码可以在 `/api/v1/bot/command` 的响应里看到
（`group_not_whitelisted` / `user_blacklisted` / `not_mentioned` / `not_command` / `role_too_low`）。

## 7. 与 NapCat 的行为差异

| 项目 | NapCat | 官方通道 |
| --- | --- | --- |
| 群标识 | 整数群号，可读 | `group_openid`，不透明字符串 |
| @ 提问者 | 支持 | 不支持 |
| 免 @ 触发 | 不支持（必须 @） | 支持，按群开关 + 角色门槛 |
| 单聊 | 不支持 | 支持，需显式配 `private_user_openids` |
| 图片 | base64 内联 | 先上传再发富媒体 |
| 频率限制 | 取决于 QQ 客户端 | 主动消息有硬配额，被动回复 5 条/消息 |
| 去重 | 无 | 平台会重推，需要按事件 `id` 去重 |

## 8. 排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 日志 `token 调用失败 code=100007` | AppID 无效或 IP 未加白 | 核对凭据与开放平台的 IP 白名单 |
| 连上但一条消息都收不到 | `intents` 没开 `1 << 25` | 改 `qqbot.intents`，重启 |
| 收到消息但不回复 | openid 白名单为空/不匹配 | 开 `log_openids`，抄日志里 `QQ Bot 事件：group_openid=…` 那一行 |
| 某个命令就是没反应 | 命令前的零宽字符把 `/` 挡住了 | 开 `debug_events`，看 `QQ Bot 归一化：text=…` 里还有没有脏字符 |
| 回复被平台丢弃 | `msg_seq` 重复或超过 5 条 | 检查 `ReplyCounter`，避免对同一条消息连发 |
| 发图报错 | 没上传或 `file_info` 过期 | 图片走 `send_image`，它内部会先上传 |
| 频繁断线 | 心跳间隔不合法 | 保留 `heartbeat_slack_seconds`，别把间隔设得比 `heartbeat_interval` 大 |

## 8.5 命令文案与模板

命令说什么、按什么条件查数据，都不在 `router.py` 里拼字符串，而是
`app/bot/commands.py` 的模板常量 + `app/bot/expr.py` 的模板引擎。
文案改一次就不改了，所以没有做成配置文件，改措辞直接改代码即可，
语法与数据集说明见 `docs/bot-templates.md`。

## 8.6 图片输出

出图只有一条路线：`/看看happy …` 截真实看板。

| 命令 | 方式 |
| --- | --- |
| `/看看happy <全部/设备名> 排行榜 [时间范围]` | `app/bot/snapshot.py` 调 `scripts/shot_dashboard.js` 截「应用排行」页 |
| `/看看happy <全部/设备名> 时间轴 [日期] [起止时刻]` | 同上，截「时间轴」页 |

截图路线是为了「跟 webui 一模一样」：不重画，直接截。要点：

1. 只截 `main.page`，不带顶部功能栏；
2. 窗口、设备范围、日期都通过查询串传给前端，前端 `readShotParams()` 读它并同步按钮高亮；
3. `devices=` 会一路传到 `/api/v1/rankings`，按设备口径时只留指定的设备；
4. 时间轴给了起止时刻时，倍率按 `1440 / 窗口分钟数` 反算，把这一段铺满一屏；
5. 截图失败（缺 node、超时、脚本报错）只记 `WARNING` 并退回文本，不会让机器人沉默。

## 9. 代码入口

| 需求 | 位置 |
| --- | --- |
| 改准入规则 | `app/bot/router.py: inspect_normalized` |
| 改事件归一化 | `app/bot/channel.py: from_qqbot_event` |
| 改接口地址/请求体 | `app/bot/qqbot.py: QQBotApi` |
| 改重连/心跳 | `app/bot/qqbot.py: QQBotClient` |
| 改命令文案 | `app/bot/commands.py`（模板常量） |
| 改截图参数 | `app/bot/router.py: _snapshot_command` |
| 改截图行为 | `server/scripts/shot_dashboard.js` |
| 加新通道 | 实现 `channel.BotChannel`，在 `runner.BotRunner.__init__` 里注册 |

## 10. 与官方文档的对齐（2026-10 核对）

按开放平台 2026-08-10 起的变更记录逐条核对过：

- **域名统一**：所有 openapi 走 `https://api.bot.qq.com`（旧文档里的 `api.sgroup.qq.com` 是历史写法），
  取票同样是 `POST https://api.bot.qq.com/app/getAppAccessToken`，鉴权头是 `Authorization: QQBot <access_token>`；
  本工程 `qqbot.api_base` 默认值就是它，不用改。沙箱环境仍填 `https://sandbox.api.sgroup.qq.com`。
- **旧 Token 鉴权已废弃**：只支持 AppID + AppSecret 换 `access_token`，本工程没实现废弃路径。
- 平台新增能力（2026-10 前后）：图文卡片消息、`<qqbot-at-everyone />` @全员、素材管理（`qqbot-media://`）、
  群成员与黑名单管理、自定义菜单 / 指令面板。这些**本工程暂未接入**——现在只用到
  「收群 @ 消息 + 回文本 / 回图片」这一条链路，够用就不加复杂度。
- **启动条件**：`napcat.enabled` 与 `qqbot.enabled` 任一为真就会起机器人任务；
  只开官方通道、关掉 NapCat 是支持的组合（早期版本只看 `napcat.enabled`，会出现"配好了却完全不连"的坑）。
- 配置改动**不用重启**：看板保存后服务端会按新配置重建通道并重连（见 `docs/protocol.md` 的配置一节）。
