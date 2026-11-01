# 上报协议 v1

客户端把采集结果通过 HTTP 推给服务端，服务端只做校验、入库和整理，不在服务端做采集。

## 端点

```
POST /api/v1/report
Content-Type: application/json
X-Ingest-Token: <config.yaml 里的 ingest.token>
```

成功返回 `200 {"ok": true, "device_id": "...", "accepted_at": "..."}`；
校验失败返回 `4xx {"ok": false, "error": "机器可读错误码", "detail": "中文说明"}`。

## 请求体字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `device_id` | string | 是 | 设备唯一标识，见下方命名规则，长度 1–64 |
| `platform` | string | 是 | `android` 或 `windows` |
| `reported_at` | string | 是 | 客户端采集时刻，ISO 8601 带时区，如 `2026-10-29T17:40:00+08:00` |
| `display_name` | string | 否 | 人类可读设备名，如「客厅台式机」，缺省用 `device_id` |
| `battery` | object | 否 | 仅 Android 有意义，`{"percent": 0-100, "charging": bool}` |
| `hardware` | object | 否 | 键值均为字符串的硬件信息表，渲染时按顺序展示 |
| `current_app` | object | 否 | `{"name": "应用名", "package": "包名或进程名", "since": "ISO 8601"}` |
| `usage_delta` | array | 否 | **增量**使用时长，见下方语义说明，单条上限 500 个元素 |
| `client_version` | string | 否 | 客户端版本号，便于排查旧版本问题 |
| `role` | string | 否 | `workstation`（默认）或 `server`，服务器角色只在 RDP 连接时统计，见下方门控规则 |
| `tag` | string | 否 | 设备标签，最长 64 字符；安卓端用它和服务器的 scrcpy 窗口标题匹配 |
| `rdp_connected` | bool | 否 | 仅服务器角色有意义：当前 RDP 是否处于活动连接 |
| `mirror_windows` | array | 否 | 仅服务器角色有意义：投屏工具（scrcpy）当前窗口标题列表，最多 16 条，单条 ≤120 字符 |
| `rdp_client_ip` | string | 否 | 仅服务器角色：连进来的 RDP 客户端 IP（WTSClientAddress），最长 45 字符 |
| `rdp_client_name` | string | 否 | 仅服务器角色：连进来的 RDP 客户端机器名（WTSClientName），最长 64 字符 |
| `rdp_target` | string | 否 | 前台是远程桌面客户端时连过去的目标地址，最长 200 字符 |

> 窗口标题由采集端先做清洗：去掉零宽字符（Edge 会在 `Microsoft\u200b Edge` 里插）、浏览器配置名（`- 用户配置 1`）和
> 「和另外 N 个页面」尾巴，只保留页面/文档标题，最长 120 字符。

### `usage_delta` 元素

```json
{ "app": "微信", "package": "com.tencent.mm", "seconds": 42 }
```

- `app`：展示名，1–128 字符。
- `package`：可选包名（Android 用包名，Windows 用进程名），≤200 字符；带上它排行榜才能稳定区分同名应用。
- `seconds`：**自上次上报以来**该应用新增的前台秒数，整数，0–86400。

> 关键语义：服务端把每次上报的 `usage_delta` 当作增量累加，而不是「最近 24 小时快照」。
> 因此客户端必须只上报**尚未上报过**的那部分时长；重复上报同一段时间会导致统计翻倍。

### 硬件信息建议键名

| 平台 | 建议键 |
| --- | --- |
| windows | `os_version`、`cpu`、`ram_gb`、`gpu`、`disk`、`hostname` |
| android | `manufacturer`、`model`、`android_version`、`sdk_int`、`screen` |

服务端不强制键名，仅按传入顺序渲染，最多展示 8 项。

## 设备 ID 命名规则

客户端首次启动时自动生成，并写入本地配置长期复用：

```
windows:  win-<主机名小写>-<4 位十六进制随机>
android:  and-<型号小写去空格>-<4 位十六进制随机>
```

示例：`win-9700x-1a2b`、`and-pixel7-9f3c`。

## 示例：Windows 上报

```json
{
  "device_id": "win-9700x-1a2b",
  "platform": "windows",
  "reported_at": "2026-10-29T17:40:00+08:00",
  "display_name": "9700X 台式机",
  "hardware": {
    "os_version": "Windows 10 1607 (10.0.14393)",
    "cpu": "AMD Ryzen 7 9700X",
    "ram_gb": "32",
    "gpu": "NVIDIA RTX 4070",
    "disk": "C: 17.4GB 可用 / D: 52GB 可用"
  },
  "current_app": { "name": "Visual Studio Code", "package": "Code.exe", "since": "2026-10-29T17:12:03+08:00" },
  "usage_delta": [
    { "app": "Visual Studio Code", "seconds": 60 },
    { "app": "Microsoft Edge", "seconds": 0 }
  ],
  "client_version": "0.1.0"
}
```

## 示例：Android 上报

```json
{
  "device_id": "and-pixel7-9f3c",
  "platform": "android",
  "reported_at": "2026-10-29T17:40:00+08:00",
  "display_name": "Pixel 7",
  "battery": { "percent": 76, "charging": false },
  "hardware": {
    "manufacturer": "Google",
    "model": "Pixel 7",
    "android_version": "14",
    "sdk_int": "34"
  },
  "current_app": { "name": "微信", "package": "com.tencent.mm", "since": "2026-10-29T17:39:10+08:00" },
  "tag": "23113RKC6C",
  "usage_delta": [
    { "app": "微信", "package": "com.tencent.mm", "seconds": 45 },
    { "app": "哔哩哔哩", "package": "tv.danmaku.bili", "seconds": 15 }
  ],
  "client_version": "0.1.0"
}
```

## 示例：服务器角色上报

```json
{
  "device_id": "win-srv-1a2b",
  "platform": "windows",
  "reported_at": "2026-10-29T17:40:00+08:00",
  "display_name": "客厅主机",
  "role": "server",
  "rdp_connected": true,
  "mirror_windows": ["23113RKC6C"],
  "hardware": { "os_version": "Windows 10 1607 (10.0.14393)", "cpu": "AMD Ryzen 7 9700X" },
  "usage_delta": [
    { "app": "scrcpy", "package": "scrcpy.exe", "seconds": 60 }
  ],
  "client_version": "0.1.0"
}
```

## 设备角色与统计门控

服务器（`role = "server"`）通常是"用 RDP 远程操作 + 用 scrcpy 投屏手机"的机器，
所以统计口径按下面的规则收紧：

| 场景 | 是否统计使用时长 | 暂停原因码 |
| --- | --- | --- |
| 服务器角色，RDP 已连接（WTSActive） | 统计 | — |
| 服务器角色，RDP 未连接或状态过期 | 暂停 | `rdp_disconnected` |
| 安卓设备标签命中某台服务器的 `mirror_windows`，该服务器 RDP 已连接，且投屏窗口在前台 | 统计 | — |
| 安卓设备标签命中某台服务器的 `mirror_windows`，该服务器 RDP 已连接，但投屏窗口在后台 | 暂停 | `mirror_background` |
| 安卓设备标签命中某台服务器的 `mirror_windows`，但所有宿主 RDP 都未连接 | 暂停（窗口在前台也暂停） | `mirror_rdp_disconnected` |
| 安卓设备标签命中的宿主服务器**状态全都过期**（掉线超过 `rdp_stale_seconds`） | 统计（等于没连着） | — |
| 安卓设备标签没有命中任何服务器（说明是直接拿着手机用） | 统计 | — |
| 服务器角色，RDP 客户端是陌生机器 | 统计（照常计时） | — |
| 工作站前台是 `mstsc.exe` / `msrdc.exe`，`rdp_target` 指向受监控设备 | 暂停（改由那台设备计时） | `rdp_target_monitored` |
| 工作站前台是 `mstsc.exe` / `msrdc.exe`，目标认不出来（frp / tailscale 地址等） | 统计（记成远程桌面客户端的使用） | — |

补充约定：

- 暂停只影响使用时长，**心跳、电量、当前应用照常上报**，群里会显示「RDP 未连接，统计暂停」。
- `rdp_connected` 超过 `gating.rdp_stale_seconds`（默认 180 秒）没更新即视为过期，按未连接处理。
- **宿主 RDP 断开时投屏窗口在前台也照样暂停**：RDP 一断就摸不到那台服务器的键鼠，前台残留的 scrcpy 窗口
  只是一张静态画面，不代表有人在操作手机。此时原因码报 `mirror_rdp_disconnected` 而不是 `mirror_background`，
  方便在看板上区分「人没盯着」和「根本连不上」。
- 多台宿主同时投屏时逐台判断：只要存在一台 **RDP 已连接** 且投屏窗口在前台的服务器就统计；掉线那台的
  前台状态不参与判定，不会把另一台「连着但窗口在后台」的情况救回来。
- 过期状态对投屏门控同样生效：命中的宿主服务器全部过期时，说明投屏早就结束，手机按"直接使用"照常统计，
  不会因为一条几天前的残留投屏记录被一直挂着「投屏窗口不在前台」。
- 角色以服务端配置 `roles.servers` / `roles.workstations` 为准，其次才看客户端上报的 `role`；
  Web 看板也能直接改角色。
- 标签匹配忽略大小写与首尾空白，命中规则为"窗口标题包含标签"或"完全相等"。
- 陌生客户端 RDP 连进服务器**不会**暂停统计：那台服务器确实在被使用，照常计时。
- 反向的门控在客户端侧：只有「远程桌面连过去的目标是受监控设备」才暂停，避免同一段时间被两台设备重复统计；
  目标识别支持 IP、机器名与 `gating.rdp_allowed_clients` 手动放行名单，端口会忽略。
- AFK 判定阈值默认 **60 秒**（`afk_threshold_seconds`），键鼠空闲超过 1 分钟即暂停统计。
- **上报失败不丢数据**：断网、服务端没起、口令填错、组装异常都只算「这一批没发出去」——客户端把待上报数据还回累加器并立刻落盘
  （Windows `usage-state.json`，Android SharedPreferences 的 `pending_usage_state`），下一次上报连同新数据一起补发；
  进程被杀后重启也会从磁盘恢复。单应用最多累计 24 小时，超过按上限截断，避免断网几天把内存和请求体撑爆。
- 上报节奏可调：Windows `report_interval_seconds` / `--report-interval`、Android 界面里的「上报频率」，范围都是 **10–60 秒**（默认 60）。
  上限 60 秒是给服务端 60 秒心跳超时留余量；下限 10 秒是避免把服务端打成高频轮询。上报快慢只影响数据新鲜度，
  不影响统计口径——使用时长按真实流逝时间累计，色块按 `usage_ended_at` 落位。

## 上报响应

```json
{
  "ok": true,
  "device_id": "win-srv-1a2b",
  "duplicate": false,
  "usage_rows_written": 1,
  "stats_paused": false,
  "stats_paused_reason": null,
  "mirrored_tags": ["23113RKC6C"],
  "received_at": "2026-10-29T09:40:01Z"
}
```

- `stats_paused` / `stats_paused_reason`：本次是否被门控、原因码（`rdp_disconnected`、`mirror_rdp_disconnected`、`mirror_background`、`mirror_foreground`、`rdp_target_monitored`、`afk`）。
- `mirrored_tags`：服务端从本次 `mirror_windows` 里识别出的安卓标签，便于客户端自查匹配是否生效。

## 查询与管理接口

以下接口都需要 `X-Ingest-Token`：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/time` | 服务端授时时间：`server_now`、`source`（如 `ntp:ntp.aliyun.com`）、`offset_seconds`、`synced` |
| GET | `/api/v1/devices` | 设备列表（概要） |
| GET | `/api/v1/dashboard` | 看板数据：每台设备的状态、电量、当前应用、近 24 小时合计与排行 |
| GET | `/api/v1/rankings` | 应用排行，参数 `hours`（1–720，默认 24）、`limit`（1–200，默认 20）与 `scope`（`all` / `device` / `group`，默认 `all`，非法值按 `all`） |
| GET | `/api/v1/devices/{device_id}` | 单台详情：硬件、电量曲线、小时级使用时间轴、应用排行 |
| POST | `/api/v1/devices/{device_id}/role` | 改角色，请求体 `{"role": "server"}` 或 `{"role": "workstation"}` |
| POST | `/api/v1/bot/command` | 命令测试：不经过 QQ，直接把一条命令跑完整条处理链 |
| GET | `/api/v1/bot/status` | 机器人通道状态：`channels`（逐通道 `name` / `connected`）、`qqbot`（`enabled` / `app_id` / 白名单 openid） |
| POST | `/api/v1/bot/test` | 真连一次通道验凭据，请求体 `{"channel": "napcat"}` 或 `{"channel": "qqbot"}` |
| GET | `/api/v1/settings` | 设置页可编辑的配置项（读磁盘、密钥只回 `********`） |
| PATCH | `/api/v1/settings` | 把改动写回 `config.yaml` 并热更新生效，请求体 `{"changes": {"acl.whitelist_groups": [123456]}}` |
| POST | `/api/v1/server/restart` | 重启服务端进程，先回 202 再由后台任务退出并拉起新进程 |

`/api/v1/rankings` 响应示例：

```json
{"ok": true, "hours": 24, "entries": [
  {"app": "微信", "package": "com.tencent.mm", "seconds": 3600, "device_count": 2}
]}
```

`/api/v1/bot/command` 请求体：

```json
{"text": "/看看happy 全部 排行榜", "channel": "napcat", "group_id": 123456789, "user_id": 10001, "mention": true, "role": "member"}
```

- `text` 必填，没写斜杠会自动补一个；
- `channel` 可选，`napcat`（默认）或 `qqbot`，决定用哪套白名单命名空间；
- `group_id` 可选：`napcat` 下必须是整数群号，`qqbot` 下是 `group_openid` 字符串；
- `user_id` 可选：`napcat` 下是 QQ 号，`qqbot` 下是 `member_openid`；
- `mention` 可选，默认 `true`，官方通道的免 @ 群可以传 `false` 看会不会被忽略；
- `role` 可选，`member` / `admin` / `owner`，用来验免 @ 的角色门槛。

响应示例：

```json
{"ok": true, "replied": true, "reason": "ok", "reason_text": "会正常回复",
 "command_text": "使用 win-1 图", "command_name": "使用", "text": "",
 "image_data_uri": "data:image/png;base64,...", "image_bytes": 24590, "elapsed_ms": 41,
 "channel": "napcat"}
```

`reason` 取值：`ok` / `empty_command` / `group_not_whitelisted` / `user_blacklisted` /
`not_mentioned` / `not_command` / `role_too_low` / `not_group` / `not_message` / `bad_ids`。
和真实机器人一样，能出图时只发图、`text` 为空串。

浏览器打开 `http://<服务器>:8080/` 就是看板页面（白色主题，顶部功能栏分概览 / 设备 / 应用排行 / 设置），口令在页面右上角填写，只存在浏览器本地。

## 错误码

| HTTP | error | 含义 |
| --- | --- | --- |
| 401 | `invalid_token` | `X-Ingest-Token` 缺失或不匹配 |
| 422 | `invalid_payload` | 字段缺失、类型错误、数值越界（响应含 `detail`） |
| 413 | `payload_too_large` | 请求体超过 256KB |
| 500 | `internal_error` | 服务端异常，已记录日志 |

## 时间与时区

所有时间必须是带时区的 ISO 8601 字符串，服务端统一转换为 UTC 存储。

**落库时间以服务端为准**：服务端启动时向阿里云 NTP（`ntp.aliyun.com`，失败退到 `ntp1`–`ntp4`，再失败退到官网 HTTP `Date`）对齐时钟，之后心跳、电量、使用时长、窗口快照的时间戳全部用**服务端收到上报的时刻**。客户端自报的 `reported_at` 只用于上报去重与排查时钟偏差，写成 2035 年也不会把数据画到别处。

### 排行口径

`GET /api/v1/rankings` 除了扁平的总排行，还能按设备或按设备组拆开看：

```json
{
  "ok": true, "hours": 24, "scope": "group",
  "entries": [ {"app": "Code.exe", "package": "code.exe", "seconds": 3600, "device_count": 2, "devices": ["本机 Windows", "手机"]} ],
  "groups": [
    {"key": "group:工作", "label": "工作", "kind": "group", "seconds": 5400,
     "entries": [ {"app": "Code.exe", "package": "code.exe", "seconds": 3600, "device_count": 2, "devices": ["本机 Windows", "手机"]} ]},
    {"key": "ungrouped", "label": "未分组", "kind": "group", "seconds": 600, "entries": [ ... ]}
  ]
}
```

- `scope=all` 时 `groups` 是空列表，`entries` 就是总排行；
- `scope=device` 时每组是一台设备（`key` 是设备 ID，`label` 是展示名）；
- `scope=group` 时组来自 `people.groups`（`key` 形如 `group:组名`），没归到任何组的设备进「未分组」桶；
- 组内条目按组内时长倒序、组与组之间按组合计倒序，`limit` 是**每组**的条数上限，`seconds` 是组内合计（不受 `limit` 截断影响）；
- 每条记录都带 `device_seconds`：`[{"device": "手机", "seconds": 1265}, ...]`，按秒数倒序、同长按设备名升序，各设备之和恒等于该条的 `seconds`。看板用它在一条条形里按设备切成几段、每段一种深浅。

查询「近 24 小时」时按服务端当前时间向前推 24 小时；时间轴按请求里的 `tz_offset_minutes` 分桶（看板会自动带上服务端的时区值），因此浏览器所在时区不影响显示。

所有时间必须是带时区的 ISO 8601 字符串。服务端统一转换为 UTC 存储，
查询「近 24 小时」时按 UTC 时间向前推 24 小时，与客户端时区无关。

## 时间轴接口

按天取 0-24 点的应用使用，供看板「时间轴」页画色块喵。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/devices/{device_id}/timeline` | 某一天的连续使用段，参数 `date`（YYYY-MM-DD，缺省为今天）、`tz_offset_minutes`（默认 480，即东八区）、`merge_gap_seconds`（默认 5） |

```json
{
  "ok": true,
  "device_id": "win-1",
  "date": "2026-10-30",
  "tz_offset_minutes": 480,
  "merge_gap_seconds": 5,
  "start": "2026-10-29T16:00:00Z",
  "end": "2026-10-30T16:00:00Z",
  "total_seconds": 25800,
  "idle_seconds": 3600,
  "afk_seconds": 3600,
  "offline_seconds": 17400,
  "heartbeat_timeout_seconds": 180,
  "server_now": "2026-10-30T05:12:34.567Z",
  "clock": { "source": "ntp:ntp.aliyun.com", "offset_seconds": 0.014, "synced": true },
  "states": [
    {
      "kind": "offline",
      "start": "2026-10-29T16:00:00Z",
      "end": "2026-10-30T00:50:00Z",
      "seconds": 17400
    },
    {
      "kind": "afk",
      "start": "2026-10-30T02:00:00Z",
      "end": "2026-10-30T03:00:00Z",
      "seconds": 3600
    }
  ],
  "hours": [0, 0, 0, 0, 0, 0, 0, 0, 0, 2700, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "segments": [
    {
      "app": "Code.exe",
      "package": "code.exe",
      "icon_key": "6332a6f2bbddef98",
      "start": "2026-10-30T01:00:00Z",
      "end": "2026-10-30T01:45:00Z",
      "seconds": 2700,
      "device_name": "书房主机"
    }
  ],
  "title_spans": [
    {
      "app": "Code.exe",
      "title": "app.js - device-hub - Visual Studio Code",
      "start": "2026-10-30T01:00:00Z",
      "end": "2026-10-30T01:20:00Z"
    }
  ]
}
```

- `segments` 按时间升序、互不重叠；同一时刻上报的多条应用采样会按累计时长**从上报时刻往前铺**，铺完正好落在上报时刻上。
- 每段的 `end` 就是那条采样的时间（服务端收到上报的时刻），`start = end - seconds`：即「上报时刻 − 这段使用时长 → 上报时刻」，不做插值，也不会把空闲时间涂成应用，更不会画到「现在」之后。
- `merge_gap_seconds` 内的同应用相邻采样会合并成一段，默认 5 秒（只用来抹平采样抖动；真实空档不会被涂成应用色块）。
- `hours` 固定 24 个元素，按 `tz_offset_minutes` 的本地小时分桶。
- `idle_seconds` 与 `afk_seconds` 同值，都表示**空档**：设备有心跳，但这一分钟没有任何使用记录。
  注意空档**不等于**「上报里 `afk` 为真」——手机亮屏（`afk=false`）却因门控暂停计时时同样没有使用记录，也算空档。
- `offline_seconds` 表示**离线**：连续 `heartbeat_timeout_seconds`（默认 60 秒）没有任何上报的分钟。
- `states` 是合并后的状态区间（只有 `offline` 与 `afk` 两种），看板据此画斜纹块；超出心跳保留期（`retention.detail_days`）的日期返回空数组。
- **空档两端用客户端给的精确边界对齐**（`afk_since` / `active_since`，见「AFK 口径」）：客户端在切换那一刻就算出
  「停表时刻」与「恢复时刻」随上报送上来，服务端只把斜纹边界挪到这两个时刻上，**不改任何使用时长数字**；
  只有全部覆盖这一分钟的客户端都给出精确边界、且偏移不超过 180 秒时才挪，否则按整分钟算（老客户端的行为）。
- **短空档也画得出来**：客户端给的精确空档区间扣掉同分钟里的使用采样后仍有剩余，就把那一段补成空档，
  不再要求"整分钟全 AFK"。实测「离开 85 秒」这种夹在两条上报之间的短空档，以前一分钟都判不出来、色块之间留一条空白，
  现在会正常画出斜纹喵。
- **色块按客户端最后一次计时的时刻落位**（`usage_ended_at`）：上报慢一点、采集循环卡一下，色块也不会整体后移；
  没带这个字段的旧客户端仍按服务端接收时刻落位。
- 旧的「按容差把空档回补到相邻色块」方案（A 方案）已停用并移除配置项：空档边界改由客户端上报的
  `afk_since` / `active_since` 决定。A 方案的实现保留在 `app/presence.py`（`_bridge_afk_gaps`），
  调用处已注释，需要时改一行就能恢复。
- 多设备（设备组 / `devices=a,b`）按组判断：只要有一台设备有心跳就不算离线；只要有设备在线、这一分钟又没有使用记录，就算空档。
- `device_name` 是这一段的设备展示名，多设备合并时泳道标题会标出来。
- **色块颜色优先取应用图标的混合色**：看板在前端把图标缩到 24×24 画进离屏 canvas，按 alpha 加权平均三个通道
  （alpha < 32 的透明边缘跳过），再按感知亮度修正——太亮压暗、太暗提亮，保证白底上看得清；取不到图标（无 `icon_key`、
  跨域被污染、解码失败）时才退回原来的哈希色板，同一屏撞色会按次序微调明度。颜色按 `icon_key` 缓存在页面里。
- **多设备同应用不拆泳道，用深浅区分**：只有**真的在多台设备上都出现过**的应用才分深浅——同一条泳道里不同设备的色块
  保持同一个色相，明度按该应用自己的设备次序偏移（原色 / 深 16% / 浅 14% / 深 28% / 浅 24% …，超过 5 台后幅度收敛），
  所以「同一应用的家族色」不变、又能一眼看出是谁在用；只在单台设备跑的应用（手机独占的哔哩哔哩、Windows 独占的 cmd 等）
  一律用原始图标色，不会被别的设备的次序无端压暗。指针悬浮时浮层直接写出设备名，合并视图里**存在多设备应用时**
  才补设备深浅的对照，同屏有几个跨设备应用就列几组（多个时每组带应用名，各自按自己的设备次序取色）。
  色块之间的合并只发生在同一台设备内，跨设备的段绝不会被并成一块。
- `title_spans` 是「同一应用 + 同一窗口标题」的连续区间（超过 20 秒的才保留，单应用最多 120 段、总数最多 1200 段，标题截到 60 字），
  右端不会越过「现在」；看板指针悬浮时据此显示那一刻的窗口标题，**不会**把同一应用按标题拆成多条泳道。
- 看板每 15 秒静默增量刷新一次时间轴（仅当停在时间轴页、页面可见、自动刷新开着），数据没变化时不重画色块，只挪「现在」竖线。

## AFK（无操作）口径

对齐 patina / ActivityWatch 的做法：**Windows 采集端用 `GetLastInputInfo` 判断键鼠空闲，空闲超过 `afk_threshold_seconds`（默认 60 秒）就停止计时**，人回来后再继续累计。因此：

- 挂机、看视频睡着、锁屏离开这些时间不会计入应用使用；
- 时间轴上表现为一段空档（45° 斜纹），设备仍然算在线；
- 采集端彻底没跑（没心跳）时是另一种状态：离线（135° 斜纹），两者不混用。

Android 端的判定口径与 Windows 对齐，但信号源不同：**息屏（`PowerManager.isInteractive()` 为 false）持续满 60 秒即上报 `afk=true`**，
亮屏立刻恢复 `afk=false`。手机息屏后系统会进入 Doze 暂停采集线程，所以时间轴上通常是「先一段空档，之后转成离线」，
两者都表示这段时间没有使用，不会被涂成应用色块。

两个客户端现在都允许 **`afk=true` 与使用时长同批上报**：服务端只把「这一分钟里没有任何使用采样」的分钟算成空档，
所以同批的秒数照常入库，不会因为 `afk=true` 被丢掉；这样 AFK 起点就不必等到下一次上报才送达（旧口径会晚整整一拍）。

### 空档边界：客户端给出精确时刻

采集端**停止计时**的那一刻（Windows 空闲满 60 秒 / 锁屏瞬间 / 手机息屏满 60 秒）才是空档真正开始的时刻，
但 `afk=true` 要等到下一次上报才送出去。实测（2026-10-31 本机数据）17 次 AFK 起始事件，
最后一段使用结束到第一条 `afk=true` 上报的间隔：

```
65 秒 × 15 次，66 / 67 秒各 1 次 → 中位数 65 秒
```

所以客户端在上报里额外带上两个时刻（都可选，老服务端会忽略）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `afk_since` | string（ISO 8601，必须带时区） | **停止计时**的精确时刻：Windows 为「最后一次输入 + `afk_threshold_seconds`」，锁屏为锁屏那一刻；Android 为息屏那一刻（60 秒只是防抖，不往后挪） |
| `active_since` | string（ISO 8601，必须带时区） | **恢复计时**的精确时刻：Windows 为最后一次输入的时刻，Android 为亮屏那一刻 |
| `usage_ended_at` | string（ISO 8601，必须带时区） | 这一批 `usage_delta` 里**最后一秒**真实发生的时刻，服务端按它给色块落位；必须不晚于 `reported_at`，且早于接收时间 3600 秒以上时会被忽略 |
| `foreground_missing_seconds` | int（0–86400） | 本轮「抓不到前台应用」的秒数，纯观测字段，服务端只记日志、不参与统计 |

两个字段与 `afk` 独立：即使这一批还带着使用时长，边界时刻照样送出去，
服务端把空档起点回溯到真正停表的那一刻，斜纹与色块之间不再有空白。
两个字段都不带时服务端按整分钟处理（老客户端行为不变）。

### 多设备合并与优先级

`server_now` 是服务端授时后的当前时间，看板用它画「现在」线；`clock` 是授时状态（来源、本机快慢多少秒、是否已对齐）。

`GET /api/v1/timeline?devices=a,b,c` 里的**顺序就是优先级**：自用时各设备时间一般不会重叠，真重叠时靠前的设备保留完整时长，靠后的设备被裁掉重叠部分（秒数按剩余长度等比例折算）。

## 黑名单接口

被拉黑的人在群里 @ 机器人也不会有任何回复。名单存 `data/acl.json`，
**改完立刻生效，不需要重启**；`config.yaml` 里 `acl.blacklist_users` /
`acl.blacklist_member_openids` 写死的条目仍然有效，两者取并集喵。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/acl/blocklist` | 读取名单，`source` 标出 `runtime`（可删）或 `config`（只能改配置文件） |
| POST | `/api/v1/acl/blocklist` | 拉黑，body 为 `{"channel":"napcat\|qqbot","target":"...","note":"可选"}` |
| DELETE | `/api/v1/acl/blocklist/{channel}/{target}` | 解除拉黑 |
| GET | `/api/v1/acl/seen-users` | 最近成功执行过命令的人，用来反查 openid |

```json
{
  "ok": true,
  "entries": [
    { "channel": "napcat", "target": "123456", "note": "刷屏",
      "created_at": "2026-11-01T05:31:07Z", "source": "runtime" }
  ]
}
```

- `channel` 决定标识的命名空间：`napcat` 填 QQ 号，`qqbot` 填 member_openid，两者互不干扰。
- 重复拉黑同一个人返回 `added: false`，不会产生多条记录。
- 拉黑只影响机器人响应，设备上报接口不受影响。

### 最近发言（反查 openid）

想在 WebUI 里一键拉黑，得先知道对方的 openid，但它不是能背下来的东西，
所以服务端会记下「成功执行过命令的人」：

```json
{
  "ok": true,
  "users": [
    { "channel": "napcat", "user_key": "222333", "display_name": "小黑本黑",
      "label": "小黑本黑", "group_key": "111", "role": "member",
      "command_count": 3,
      "first_seen_at": "2026-11-01T05:49:20Z", "last_seen_at": "2026-11-01T06:12:03Z" }
  ]
}
```

- 存在 `bot_seen_users` 表，每人一行，按 `(channel, user_key)` 唯一，用 upsert 维护计数。
- **只记 ACL 通过、真正执行了命令的人**；闲聊与被拦截的消息都不记。
- 昵称来源：NapCat 读 `sender.card` 优先、其次 `sender.nickname`；
  **官方通道平台只给 openid，拿不到昵称**，此时 `display_name` 为空，`label` 退化成标识前 8 位。
- 保留期跟随 `retention.detail_days`，由机器人原有的清理循环一并删除。

## 设备组（人）接口

把多台设备归到一个人名下，组内顺序即优先级；数据存在 `data/people.json`，前端可编辑喵。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/people` | 读取设备组 |
| PUT | `/api/v1/people` | 覆盖保存设备组（整组替换） |

```json
{
  "ok": true,
  "groups": [
    { "name": "主人", "devices": ["win-1", "and-1"] },
    { "name": "服务器", "devices": ["win-srv-1"] }
  ]
}
```

- 组名 1–64 字，组数上限 32，每组设备上限 32 台。
- 设备列表会去重、去空白，**顺序保持原样**（就是优先级）。
- 文件损坏时按"没有设备组"处理并记日志，不影响看板打开。

## 应用图标接口

看板上的应用图标由采集端上传，服务端按「应用名 + 包名 + 图标内容」算键存进 SQLite（`app_icons` 表）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/icons` | 上传一张 PNG 图标 |
| GET | `/api/v1/icons` | 列出已有图标与 `content_hash`（客户端据此比对要不要重传） |
| GET | `/api/v1/icons/{key}` | 取回 PNG，`<img>` 可用 `?token=` 传口令 |

```json
POST /api/v1/icons
{
  "app": "微信",
  "package": "com.tencent.mm",
  "png_base64": "iVBORw0KGgoAAAANSUhEUg..."
}
→ { "ok": true, "key": "6332a6f2bbddef98" }
```

- 只接受 PNG（按文件头校验），单张不超过 32 KB，建议 32–48px。
- 键由 `sha1(应用名 + \x00 + 包名 + \x00 + sha1(PNG))` 取前 16 位，**图标内容一变键就变**。
- 同一 (应用名, 包名) 只保留最新一行，换图标时旧行会被删掉；代价是历史时间轴回看会用新图标。
- `GET /api/v1/icons` 每行返回 `content_hash`（PNG 字节的 `sha1` 取前 16 位），供采集端与本地图标比对。
- 图标响应头是 `Cache-Control: public, max-age=2592000`（30 天）；键随内容变，换图标后 URL 会变，浏览器缓存自然失效。
- 时间轴段与排行条目里会带上 `icon_key`，前端拼 `/api/v1/icons/<key>?token=...` 显示，取不到就退回色块；
  库里没有该应用的图标时 `icon_key` 是空串，不会返回一个查不到的键。

## 统计口径相关的上报字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rdp_connected` | bool | 服务器角色专用，RDP 是否处于活动连接 |
| `mirror_windows` | string[] | 服务器上投屏窗口的标题，用于匹配安卓标签 |
| `mirror_foreground` | bool | 投屏窗口是否在前台（前台时人其实在看手机） |
| `afk` | bool | 键鼠是否空闲（客户端按 `afk_threshold_seconds` 判定） |
| `afk_since` | string | 停止计时的精确时刻（ISO 8601 带时区），见「AFK 口径」 |
| `active_since` | string | 恢复计时的精确时刻（ISO 8601 带时区），见「AFK 口径」 |
| `usage_ended_at` | string | 使用时长最后一秒的真实时刻（ISO 8601 带时区），色块按它落位 |
| `foreground_missing_seconds` | int | 抓不到前台应用的秒数，观测用 |

服务端据此判定：

- `afk=true` → 本机不计时，正在被投屏的手机也不计时；
- 服务器角色：`rdp_connected=false` → 暂停；`mirror_foreground=true` → 本机暂停（人在看手机）；
- 安卓设备被投屏时：投屏窗口在前台才计时，缩到后台就暂停；没被任何服务器投屏时照常计时。

## 窗口上报

Windows 端每次上报会带上「当前所有已打开的窗口」，用于后续窗口维度的分析（安卓端不上报）。

```json
POST /api/v1/report
{
  "current_app": { "name": "Chrome", "package": "chrome.exe", "title": "看板 - device-hub", "since": "..." },
  "open_windows": [
    { "app": "Chrome", "package": "chrome.exe", "title": "看板 - device-hub", "minimized": false, "foreground": true },
    { "app": "记事本", "package": "notepad.exe", "title": "笔记.txt", "minimized": true, "foreground": false }
  ]
}
```

- 单次最多 80 个窗口；没有窗口时整个字段省略。
- 采集规则：只看可见的顶层窗口，跳过空标题、系统壳层窗口（`Program Manager` 等）与采集端自身。
- 服务端**按上报逐次追加**写入 `window_samples` 表，历史默认不删，清理见下。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/devices/{device_id}/windows` | 最近一次上报的窗口列表（前台优先，`limit` 默认 80） |

## 存储统计与清理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/storage` | 库文件大小、WAL 大小、各表行数与时间范围 |
| POST | `/api/v1/storage/cleanup` | 删除早于 N 天的历史数据，可选表 |

```json
POST /api/v1/storage/cleanup
{ "before_days": 30, "targets": ["window_samples", "usage_samples"] }
→ { "ok": true, "deleted": { "window_samples": 120 }, "deleted_total": 120, "stats": { ... } }
```

- `before_days` 取值 1–3650，不传默认 30；`targets` 不传表示清全部可清理表。
- 可清理表：`usage_samples`、`battery_samples`、`window_samples`、`reports`。
- 清理后会执行 `VACUUM`，文件才会真的变小。

## 配置读写、连接测试与重启

看板「配置」页用的三个接口，都要带 `X-Ingest-Token`。

`GET /api/v1/settings` 返回可编辑项（白名单字段表，密钥只给 `********`）：

```json
{"ok": true, "config_path": "D:\\device-hub\\server\\config.yaml", "restart_required": false,
 "fields": [
   {"name": "napcat.ws_url", "section": "napcat", "key": "ws_url", "kind": "str",
    "label": "NapCat 正向 WS 地址", "hint": "例如 ws://127.0.0.1:7999", "value": "ws://127.0.0.1:7999"},
   {"name": "napcat.token", "kind": "secret", "value": "********"}
 ]}
```

`PATCH /api/v1/settings` 只改传进来的键，**保存即热更新生效**：

```json
{ "changes": { "acl.whitelist_groups": [123456], "napcat.reconnect_seconds": 10 } }
→ { "ok": true, "changed": ["acl.whitelist_groups"], "restart_required": false,
    "restart_fields": [], "applied": true }
```

- `kind` 支持 `bool` / `int` / `str` / `secret` / `str_list` / `int_list`；列表可以传数组，也可以传换行或逗号分隔的字符串。
- 改配置走**文本替换**：只重写目标那一行，注释与排版保持不变；缺键补在段尾，缺段追加到文件末尾。
- 写盘前会先写同目录临时文件并跑一遍完整校验（`load_config`），校验不过返回 400 且原文件不变。
- 密钥传 `********` 表示「没改」，不会覆盖成星号。
- **热更新**：写盘成功后立刻重新加载并换掉内存里的配置，同一个请求内就生效——
  机器人相关配置（`napcat` / `qqbot` / `acl`）有变化时会取消旧任务、按新配置重建通道并重连；
  其它阈值（心跳超时、保留天数、AFK 阈值）每次请求现取，改完立即生效。
- 只有绑在进程上的 `server.port` / `server.db_path` 需要重启，`restart_fields` 会列出它们（当前设置页不允许改这两项，所以一般是空数组）。
- `GET` 读的是**磁盘上的文件**而不是内存，所以保存后刷新页面看到的就是刚存进去的值，不会被旧配置"重置"回去。

`POST /api/v1/bot/test` 真连一次通道（用磁盘上的最新配置，改完不用先重启就能验证）：

```json
{ "channel": "napcat" }
→ { "ok": true, "channel": "napcat", "connected": true, "latency_ms": 12, "detail": "昵称（QQ号）", "error": "" }
```

- `napcat`：连 `napcat.ws_url`（带 `access_token`）并调 `get_login_info`，`retcode` 非 0 时提示口令不一致；
- `qqbot`：用 `app_id` / `app_secret` 换一次 `access_token` 再取网关地址，凭据缺失直接返回原因；
- 单次测试总超时 8 秒，`connected` 为 `false` 时 `error` 一定有内容。

`POST /api/v1/server/restart` 先回 `202 {"restarting": true, "port": 8080}`，再由后台任务起一个分离进程：
启动器等端口释放后用 `python -m app.main` 重新拉起服务，日志追加到 `server/data/server.log`。
