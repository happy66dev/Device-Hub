# Android 采集端设计与实现

已实现并构建通过：`client-android/`，包名 `io.github.happy66dev.devicehub`。
构建命令与环境变量见 [android-build.md](android-build.md)。

工具链放在 `D:\android-toolchain`（JDK 17 + Gradle 8.10.2 + SDK 34），不进仓库。

## 1. 要采集什么

| 数据 | 来源 | 权限/限制 |
| --- | --- | --- |
| 厂商、型号 | `Build.MANUFACTURER`、`Build.MODEL` | 无 |
| Android 版本、SDK | `Build.VERSION.RELEASE`、`Build.VERSION.SDK_INT` | 无 |
| 电量、充电状态 | `BatteryManager` + `ACTION_BATTERY_CHANGED` | 无 |
| 当前前台应用 | `UsageStatsManager.queryEvents` 取最近 `ACTIVITY_RESUMED` | 需「使用情况访问」特殊权限 |
| 近 24 小时应用使用 | `UsageStatsManager.queryUsageStats` 的 `totalTimeInForeground` 做差分 | 同上 |

> Android 10 起 `getRunningTasks` 已不可用，拿当前前台应用只能靠 `UsageStatsManager` 事件流，
> 或无障碍服务（`AccessibilityService`）。前者权限更轻，优先用前者。

## 2. 上报映射（对应 `docs/protocol.md`）

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
  "current_app": { "name": "微信", "package": "com.tencent.mm", "since": "..." },
  "tag": "23113RKC6C",
  "afk": false,
  "usage_delta": [ { "app": "微信", "package": "com.tencent.mm", "seconds": 45 } ]
}
```

**关键点 1：`usage_delta` 必须是增量。**
`queryUsageStats` 返回的是"某个统计区间内的累计前台时长"，所以客户端要自己保存上一次的读数：

```
增量 = 本次 totalTimeInForeground - 上次 totalTimeInForeground
增量 < 0 说明跨天重置或应用被清数据，按 0 处理
```

差分表建议落 `SharedPreferences`（应用几十个，JSON 足够，不必上 Room）。

**关键点 2：每条使用时长都要带包名。**
展示名会被系统语言改掉（"微信" / "WeChat"），包名不会，
所以 `UsageDelta` 同时带 `appName` 与 `packageName`，服务端排行榜按 `(app_name, package)` 分组。

**关键点 3：`tag` 用来和服务器的 scrcpy 窗口标题匹配。**
界面上「设备标签」默认取手机型号（`Build.MODEL`），正好是 scrcpy 窗口标题里常见的内容。
当这台手机被某台服务器投屏、而那台服务器 RDP 没连接时，服务端会暂停统计这台手机的使用时长
（详见 `docs/protocol.md` 的「设备角色与统计门控」）。

**关键点 4：`afk` 用息屏判定，口径与 Windows 端一致。**
`AfkTracker` 记录连续息屏时长，**满 60 秒**才上报 `afk=true`，亮屏立刻恢复 `afk=false`；
服务端据此把这几天画成「空档」斜纹，而不是当成在用（详见 `docs/protocol.md` 的「AFK 口径」）。
另有两条保命规则：

- `afk=true` 可以与 `usage_delta` 同批上报：服务端只把「这一分钟里没有任何使用采样」的分钟算成空档，
  所以同批的秒数照常入库，AFK 起点不必再等下一拍（详见 `docs/protocol.md`）；
- 息屏时本来就不累计使用时长（`ScreenState`），所以长时间息屏只会先出现空档、之后因 Doze 停心跳转成离线。

**关键点 5：前台应用要缓存，不能只看一小段事件窗口。**
`UsageStatsManager.queryEvents` 给的是**点事件**：用户切到微信之后一直不动，事件流里就再也不会有新的
`ACTIVITY_RESUMED`。旧实现只查最近 10 秒，于是采样时窗口里几乎永远没有事件，`current_app` 恒为 null、
使用时长一秒都记不上。现在的做法是：

- 缓存为空时回看 5 分钟，尽量抓到两次采样之间的切换；之后**只查上次之后的新事件**（留 10 秒重叠），
  不再每轮扫 5 分钟（那会让采样周期从 5 秒涨到十几秒，见关键点 7）；
- 窗口里没有新事件时**沿用上一次的判定结果**（`pickForeground` 纯函数，有单元测试）；
- 前台是本应用自己时返回 null 并清空缓存，避免把配置界面算成使用时长；
- 息屏时清空缓存，避免上报里一直挂着息屏前那个应用；
- 包名到应用名的解析结果会缓存，别每轮都去问 `PackageManager`。

**关键点 6：采集日志与上报日志一样重要。**
`AgentLog` 里既记上报结果，也记采集动作（前台切换、亮屏息屏、AFK 变化、5 分钟摘要）。
只写上报日志时，"服务在跑但采不到数据"和"服务根本没跑"在日志里长得一模一样，
现在前者能看到「采集：前台切换到…」，后者只剩上一条启动记录，一眼能分开。

**关键点 7：使用时长按真实流逝时间累计，不按名义周期。**
旧实现每轮固定记 `采样间隔`（5 秒），然后 `Thread.sleep(5 秒)` —— 但一轮里还要查事件、抠图标、写盘，
实际周期是「干活耗时 + 5 秒」。在真机上实测周期能到 16 秒，于是一个上报周期（65 秒）里只记下 20 秒左右，
时间轴上就是"应用色块断成一截一截"。现在的做法：

- 每轮按 `System.currentTimeMillis()` 的真实差值累计，并 `coerceIn(1ms, 3×采样间隔)`，
  循环被系统冻结时最多补记 3 个周期，不凭空记上几个小时；
- 休眠改成睡**剩余时间**（`间隔 - 本轮耗时`），采样节奏稳定在 5 秒；
- 每轮不足 1 秒的零头不丢：`SampleCredit.split(本轮毫秒, 上一轮余数)` 把余数留到下一轮，
  否则每轮截断半秒、一分钟就少记 4~6 秒（0.4.0 实测 89.8%，0.5.1 起接近 100%）；
- 待上报数据每 30 秒落盘一次（旧实现每轮都写 SharedPreferences，那是循环变慢的主因之一）；
- AFK 状态一变立刻上报一次（不必等满 60 秒的周期），并带上 `afk_since` / `active_since`，
  服务端据此把空档边界量到秒（详见 `docs/protocol.md` 的「AFK 口径」）。

## 3. 复用开源基座的选择标准

保活是 Android 上最容易翻车的部分，所以优先"改一个能跑的项目"而不是从零写。
候选评估维度（按重要性排序）：

| 维度 | 要求 | 原因 |
| --- | --- | --- |
| 前台服务保活 | 已有 `startForeground` + 通知渠道 + 重启策略 | 这是最难写对的部分 |
| 开机自启 | 已有 `BOOT_COMPLETED` 接收器 | 免去自己处理 Android 8+ 限制 |
| 电量优化引导 | 已引导用户加入白名单 | 国产 ROM 杀后台严重 |
| 使用情况权限引导 | 已有跳转「使用情况访问」设置页的逻辑 | 该页面没有公开 Intent，只能跳列表页 |
| 许可证 | Apache-2.0 / MIT | 便于改造与分发 |
| 体量 | 单模块、无重型依赖 | 方便裁剪 |

**建议路线（待主人确认）**：

- 路线 A（推荐）：以 Google 官方示例 `googlearchive/android-AppUsageStatistics`（Apache-2.0）的
  `UsageStatsManager` 读取逻辑为参考，套用成熟的前台服务保活模板，只保留"采集 + 上报"两条链路。
- 路线 B：直接 fork 一个现成的"设备信息/用量统计"类开源 App，删掉 UI，保留服务与权限引导。
- 路线 C：从零写（不推荐，保活与各家 ROM 兼容会反复返工）。

选定后猫猫再动手，避免写一半发现基座不合适。

## 4. 模块划分

```
client-android/
├─ app/src/main/java/io/github/happy66dev/devicehub/
│  ├─ DeviceHubApp.kt          应用入口，创建通知渠道
│  ├─ ui/MainActivity.kt       配置界面、权限引导、启停上报
│  ├─ ui/SettingsActivity.kt   服务端地址、token、设备名配置
│  ├─ core/DeviceId.kt         生成并持久化 and-<型号>-<4hex>
│  ├─ core/BatteryReader.kt    电量与充电状态
│  ├─ core/HardwareReader.kt   Build.* 字段
│  ├─ core/UsageReader.kt      UsageStatsManager 查询 + 差分
│  ├─ core/UsageStore.kt       差分基线持久化
│  ├─ net/ReportApi.kt         OkHttp POST /api/v1/report
│  ├─ service/UploadService.kt 前台服务，定时采集与上报
│  └─ service/BootReceiver.kt  开机拉起前台服务
└─ app/src/main/AndroidManifest.xml
```

包名遵循规则 14：`io.github.happy66dev.devicehub`。

## 5. 保活策略（组合拳）

1. **前台服务**：`startForeground` + 常驻通知（低优先级渠道），Android 14 需声明
   `foregroundServiceType="dataSync"` 并在 manifest 里申请 `FOREGROUND_SERVICE_DATA_SYNC`。
2. **开机自启**：`BOOT_COMPLETED` + `MY_PACKAGE_REPLACED` 两个广播都拉起服务。
3. **电池优化白名单**：引导用户执行 `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`。
4. **周期兜底**：`WorkManager` 每 15 分钟跑一次"补报"，防止服务被杀后长时间无数据。
5. **自愈**：服务 `onDestroy` 里用 `AlarmManager` 设一个 1 分钟后的重试；上报失败指数退避。
6. **国产 ROM**：在引导页提示用户手动开启"自启动/后台运行"权限，无法代码绕过。

> 提醒：任何保活手段都不是 100%，服务端已有 90 秒在线判定与 24 小时窗口，
> 短暂离线不影响统计口径。

## 6. 构建与验证

```powershell
# 环境变量（每次构建前设置）
$env:JAVA_HOME        = 'D:\android-toolchain\jdk17\jdk-17.0.20.1+1'
$env:ANDROID_HOME     = 'D:\android-toolchain\sdk'
$env:ANDROID_SDK_ROOT = 'D:\android-toolchain\sdk'
$env:GRADLE_USER_HOME = 'D:\android-toolchain\gradle-home'

# 单元测试（不需要连手机）
& 'D:\android-toolchain\gradle-8.10.2\bin\gradle.bat' --no-daemon -p D:\device-hub\client-android :app:testDebugUnitTest

# 打 debug 包
& 'D:\android-toolchain\gradle-8.10.2\bin\gradle.bat' --no-daemon -p D:\device-hub\client-android :app:assembleDebug
```

详细步骤、安装与排错见 [android-build.md](android-build.md)。

## 7. 已实现清单

| 文件 | 职责 |
| --- | --- |
| `core/DeviceIdentity.kt` | 生成 `and-<型号>-<4hex>` 设备 ID，纯 Kotlin 可测 |
| `core/UsageDelta.kt` | 一条待上报使用时长：应用名 + 包名 + 秒数 |
| `core/UsageDeltaCalculator.kt` | 使用时长增量累加、包名记忆、失败回滚、截断 |
| `core/UsageStateCodec.kt` | 待上报数据的序列化（三段格式，兼容旧两段），供服务被杀后恢复 |
| `core/AfkTracker.kt` | AFK 判定：连续息屏满 60 秒才算人离开，纯 Kotlin 可测 |
| `core/ReportPayload.kt` | 手写 JSON 转义与上报体构造，纯 Kotlin 可测 |
| `collect/HardwareReader.kt` | 厂商/型号/品牌/Android 版本/SDK |
| `collect/BatteryReader.kt` | 电量与充电状态（粘性广播） |
| `collect/UsageReader.kt` | 前台应用（UsageStatsManager 事件流 + 缓存上一次结果）+ 应用名解析 |
| `data/AgentPrefs.kt` | 地址、口令、设备 ID、设备标签、上报开关、采集/上报频率、上次上报结果持久化 |
| `core/ReportInterval.kt` | 上报频率的取值范围（10–60 秒）、文本解析、是否到期判定 |
| `core/ReportStatus.kt` | 上报状态模型与界面文案（未运行 / 从未上报 / 成功多久前 / 失败原因） |
| `core/ReportBacklog.kt` | 待补报秒数的界面文案（0 秒为空、负数按 0、支持时分秒），纯 Kotlin 可测 |
| `net/ReportClient.kt` | HttpURLConnection 上报，超时与错误处理 |
| `service/UploadService.kt` | 前台服务：5 秒采样（带包名）、按设定间隔上报（10–60 秒）、失败回滚与异常兜底、上报状态/待补报秒数快照 |
| `service/BootReceiver.kt` | 开机与升级后按需拉起服务（含 `QUICKBOOT_POWERON`） |
| `service/KeepAliveJob.kt` | 持久化保活任务：每 15 分钟检查一次，服务没跑就重新拉起 |
| `ui/MainActivity.kt` | 配置界面（含设备标签）、权限引导与快捷入口、启停上报、Intent 参数部署 |
| `ui/LogActivity.kt` | 运行日志页：环形缓冲实时展示、复制、清空，2 秒自动刷新 |
| `core/AgentLog.kt` | 进程内日志环形缓冲（最多 500 行），服务写、界面读，纯 Kotlin 可测 |
| `DeviceHubApp.kt` | 通知渠道初始化 |

单元测试 101 例（`app/src/test`），覆盖设备 ID、增量计算与包名记忆、待补报文案与 restore 累加、采样整秒余数进位、JSON 转义、
上报体结构（含 `tag`、`afk`、`afk_since` / `active_since`、`usage_ended_at` 与 `usage_delta.package`）、采集频率夹取、
上报频率夹取与到期判定、上报状态四种文案、AFK 判定（含精确边界时刻）、前台应用缓存判定、
待上报数据序列化（含旧格式兼容）与日志环形缓冲。
其中 `SamplePayloadTest` 会把 App 真实会发的 JSON 导出到
`app/build/reports/sample-payload.json`，可直接喂给服务端联调。

## 7.5 与 Windows 端的功能对齐

| 能力 | Windows 端 | Android 端 |
| --- | --- | --- |
| 采集频率 1–60 秒（默认 5 秒） | 配置文件 `sample_interval_seconds` | 界面输入框，运行时每轮重读 |
| 上报频率 10–60 秒（默认 60 秒） | 配置文件 `report_interval_seconds` 或 `--report-interval` | 界面输入框，运行时每轮重读 |
| 当前应用（含包名） | 前台进程 + 窗口标题 | `UsageStatsManager` 事件流 |
| 近 24 小时使用数据 | 采样累加增量 | 采样累加增量（带包名） |
| 电量 | 有电池的机器才上报 | 始终上报 |
| 硬件信息 | CPU / 内存 / 磁盘 / 系统版本 | 厂商 / 型号 / 品牌 / Android 版本 / SDK |
| 应用图标上传 | 前台应用 + 所有窗口 | 前台应用（同包只传一次） |
| 设备标签 | 配置文件 `tag` | 界面「设备标签」，默认取型号 |
| AFK | `GetLastInputInfo` 空闲满 60 秒 / 锁屏立刻 | 息屏满 60 秒（`AfkTracker`） |
| 空档边界 | `afk_since` / `active_since` | 同名字段（息屏时刻 + 60 秒 / 亮屏时刻） |
| 计时口径 | 按真实流逝时间累计（上限 3 个周期） | 同左 |
| AFK 变化 | 立刻补一次上报 | 同左 |
| 窗口标题 / 已打开窗口 | 上报 `current_app.title` 与 `open_windows` | 不适用（系统不提供窗口枚举） |
| RDP 门控与投屏匹配 | 服务器角色上报 RDP 状态与投屏窗口 | 只上报 `tag`，门控由服务端判定 |
| 运行日志 | `--debug` 弹控制台 + 文件日志 | 界面「查看日志」页（环形缓冲） |
| 权限引导 | 无（桌面无需授权） | 使用情况 / 通知 / 电池优化快捷入口 |
| 开机自启 | 任务计划程序（见 deploy.md） | `BootReceiver` + `KeepAliveJob` 兜底 |

结论：协议字段层面两端已对齐（`afk` 是 2026-10-31 补上的最后一项），
窗口类字段是 Windows 独有概念，Android 端按协议省略。

## 8. 关于"复用开源基座"的说明

保活部分没有 fork 现成项目，而是按 AOSP 文档的官方做法实现了组合拳
（前台服务 + 开机自启 + 电池优化白名单 + 失败回滚），原因有两点：

1. 现成项目大多绑定自己的 UI 与账号体系，裁剪成本高于按标准写法重写；
2. 本工程刻意零第三方依赖（只用 Kotlin 标准库 + JDK 的 HttpURLConnection），
   依赖越少，国产 ROM 上出问题的概率越低。

如果后续发现某款 ROM 上保活不稳，再按第 3 节的标准挑一个基座替换服务层即可，
协议层（core 包）不用动。

## 8.5 界面：配置、权限与日志

主界面（`ui/MainActivity.kt`）从上到下是：状态徽标 → 输入框 → 按钮区。

最顶上是一个**实时服务徽标**，界面可见时每秒刷新一次（`Handler` 轮询，`onPause` 自动停）：

```
● 服务运行中，正在采集     ← 绿色
上次上报：上报成功 2026-10-31T11:12:00Z
```

服务没跑时变成红色的「● 服务未运行，未在采集」。状态区则直接告诉用户"卡在哪一步"：

```
设备 ID：and-23113RKC6C-1a2b
设备名：小米 14
设备标签：23113RKC6C
采集频率：每 5 秒采集一次
配置：完整
使用情况权限：已授予
通知权限：已授予
电池优化：未忽略（可能被杀）
上报开关：已开启
上报服务：运行中
待补报 0 秒
日志行数：23（最多 500 行）
```

按钮区依次是：保存配置 / 开始上报 / 停止上报 / 授予使用情况访问权限 / 忽略电池优化 /
通知权限设置 / 应用详情（自启动设置） / 查看运行日志。

- **开始上报的权限闸门**：缺「使用情况访问」或「通知」权限时**直接拦住不启动**，弹提示并跳到对应设置页；
  电池优化只提示不拦截（它不是权限，挡着不让用反而更烦）；
- **自动恢复上报**：`reportingEnabled` 为真时，界面每次回到前台都会检查服务是否还在跑，不在就静默拉起；
  开机自启（`BootReceiver`，含 `QUICKBOOT_POWERON`）也会拉起，并排一个 `setPersisted(true)` 的
  `KeepAliveJob`（15 分钟一次）兜底，ROM 吞掉自启或杀掉服务时还能救回来；点「停止上报」会取消该任务；
- **使用情况访问权限**：`ACTION_USAGE_ACCESS_SETTINGS`，采集的唯一硬前提，没授予就采不到前台应用；
- **忽略电池优化**：`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`，被国产 ROM 拒绝时自动退回电池优化列表页；
- **通知权限设置**：`ACTION_APP_NOTIFICATION_SETTINGS`，Android 13 起没有它前台服务通知不显示；
- **应用详情**：`ACTION_APPLICATION_DETAILS_SETTINGS`，小米/华为/OPPO 的"自启动""后台弹出界面"开关都在这里；
- **查看运行日志**：打开 `LogActivity`，显示服务写进 `AgentLog` 的最近 500 行，
  支持刷新 / 复制 / 清空，页面可见时每 2 秒自动刷新，切到后台自动停刷省电。
- **失败补报**：上报失败或上报过程中抛异常时，这一批数据会还回累加器并立即落盘，
  状态区的「待补报」行显示积压秒数，下一次上报一起补发（成功日志会标「含补报」）。

日志里**采集和上报都记**，不会只剩上报记录：

| 时机 | 日志示例 |
| --- | --- |
| 服务启动 | `服务已启动，设备 and-23113RKC6C-1a2b` |
| 前台应用切换 | `采集：前台切换到「微信」（com.tencent.mm）` |
| 亮屏 / 息屏 | `采集：亮屏，恢复计时` / `采集：息屏，暂停计时` |
| AFK 状态变化 | `采集：判定为离开（AFK），本段计入空档` / `采集：已回到使用中` |
| 每 5 分钟摘要 | `采集：近 5 分钟采样 60 次，待上报 240 秒` |
| 每次上报 | `上报成功，应用 3 个，共 65 秒（含补报）` / `上报失败：连接超时，已缓存 65 秒 / 2 个应用待补报` |
| 异常 | `上报异常，已缓存 65 秒待补报：…` / `采样异常：…` |

采集日志只在**状态变化**时写，每 5 分钟一条摘要，所以 500 行的环形缓冲够看一整天喵。

日志只存在内存里：进程被杀就清空，不会在手机上留文件，也就不涉及隐私留存。

## 9. 待办

- [x] 安装 Android SDK 命令行工具 + JDK 17
- [x] 生成工程骨架并通过编译
- [x] 单元测试覆盖核心逻辑
- [x] 上报体与服务端联调（样例 JSON 被服务端 200 接收）
- [ ] 真机安装：本机连着的 Redmi 设备被 MIUI 的"USB 安装"策略拦截，
      需要主人手动在开发者选项里打开「USB 调试（安全设置）」与「USB 安装」后再装
- [ ] 国产 ROM 上长时间后台稳定性观察
