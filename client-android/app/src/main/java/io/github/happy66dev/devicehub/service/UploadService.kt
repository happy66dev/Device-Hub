package io.github.happy66dev.devicehub.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Base64
import android.util.Log
import io.github.happy66dev.devicehub.collect.BatteryReader
import io.github.happy66dev.devicehub.collect.ForegroundApp
import io.github.happy66dev.devicehub.collect.HardwareReader
import io.github.happy66dev.devicehub.collect.IconReader
import io.github.happy66dev.devicehub.collect.ScreenState
import io.github.happy66dev.devicehub.collect.UsageReader
import io.github.happy66dev.devicehub.core.AfkTracker
import io.github.happy66dev.devicehub.core.IconHash
import io.github.happy66dev.devicehub.core.IsoTime
import io.github.happy66dev.devicehub.core.PendingBatch
import io.github.happy66dev.devicehub.core.ReportInterval
import io.github.happy66dev.devicehub.core.ReportPayload
import io.github.happy66dev.devicehub.core.ReportStatus
import io.github.happy66dev.devicehub.core.SampleCredit
import io.github.happy66dev.devicehub.core.SampleGapCap
import io.github.happy66dev.devicehub.core.ReportStatusText
import io.github.happy66dev.devicehub.core.SampleInterval
import io.github.happy66dev.devicehub.core.UsageDeltaCalculator
import io.github.happy66dev.devicehub.core.AgentLog
import io.github.happy66dev.devicehub.core.UsageStateCodec
import io.github.happy66dev.devicehub.data.AgentPrefs
import io.github.happy66dev.devicehub.net.ReportClient
import io.github.happy66dev.devicehub.ui.MainActivity
import java.time.Instant

/**
 * 采集与上报的前台服务。
 *
 * 为什么必须是前台服务：Android 8 起后台服务会被系统随时冻结，
 * 只有前台服务（带常驻通知）才能稳定地每几秒采样一次喵。
 */
class UploadService : Service() {

    // 日志标签喵
    private val logTag = "DeviceHub"

    // 本地配置喵
    private lateinit var prefs: AgentPrefs

    // 采集器喵
    private lateinit var usageReader: UsageReader
    private lateinit var batteryReader: BatteryReader
    private lateinit var screenState: ScreenState
    private lateinit var iconReader: IconReader
    // 本次运行已记录的「包名 → 图标内容哈希」，与服务端哈希不同才重传喵
    private val uploadedIconHashes = mutableMapOf<String, String>()

    // 上报客户端喵
    private val reportClient = ReportClient()

    // 使用时长累加器喵
    private val usageCalculator = UsageDeltaCalculator()

    // 是否还有失败后缓存的数据等着补报，成功日志据此标注「含补报」喵
    private var hasPendingBacklog = false

    // 待重发批次：失败的那一批原样留着，带着固定时刻重发，避免服务端重复累加喵
    //
    // 喵~注意：不能像以前那样失败就把秒数还回 usageCalculator。
    // 服务端用 (deviceId, reportedAt) 做幂等键，还回去会让下一批变成超集、
    // 且重新取当前时刻 → 被当成新批次再累加一遍，使用时长永久翻倍喵
    private var pendingBatch: PendingBatch? = null

    // 上一轮不足 1 秒的余数，留到下一轮一起记，避免每轮都少半秒喵
    private var carryMillis = 0L

    // AFK 判定器：只看屏幕是否点亮，息屏就算人离开了喵
    private val afkTracker = AfkTracker()

    // 采样循环线程喵
    private var workerThread: Thread? = null

    // 循环开关，用 volatile 保证跨线程可见喵
    @Volatile
    private var running = false

    /** 服务创建时初始化依赖并进入前台喵。 */
    override fun onCreate() {
        super.onCreate()
        // 初始化配置喵
        prefs = AgentPrefs(this)
        // 初始化采集器喵
        usageReader = UsageReader(this)
        batteryReader = BatteryReader(this)
        screenState = ScreenState(this)
        iconReader = IconReader(this)
        // 喵~防御：把上次已传图标的哈希恢复回来，图标没变就不用重传喵
        uploadedIconHashes.putAll(prefs.uploadedIconHashes)
        // 喵~注意：这里分两种情况，不能一刀切丢掉：
        // 1. **新格式**（带固定上报时刻）——我们确切知道这批秒数属于哪个时刻，
        //    服务端能靠 (deviceId, reportedAt) 认出是同一批，重发只会加一次，
        //    所以**必须重发**，否则那几十秒凭空消失喵。
        // 2. **旧格式**（只有应用名和秒数、没有时间戳）——重启后无法知道它们发生在
        //    哪段时间里，服务端只能铺在"上一次铺到的位置"之后；进程被杀且中断较久时，
        //    这堆秒数就会盖到离线时段上，让离线期显示出使用色块。
        //    主人要求「离线数据必须绝对真实」，所以这种**只能丢弃**喵。
        val restoredBatch = PendingBatch.decode(prefs.pendingUsageState)
        if (restoredBatch != null) {
            // 新格式：原样恢复成待重发批次，下一轮直接重发喵
            pendingBatch = restoredBatch
            Log.i(
                logTag,
                "恢复上次未上报的批次：${restoredBatch.items.size} 个应用共 ${restoredBatch.totalSeconds} 秒，将按原时刻重发",
            )
            AgentLog.info(
                "恢复待重发批次：${restoredBatch.items.size} 个应用共 ${restoredBatch.totalSeconds} 秒",
            )
        } else {
            // 老格式：读一下把日志写清楚，然后丢掉喵
            val staleState = UsageStateCodec.decode(prefs.pendingUsageState)
            if (staleState.isNotEmpty()) {
                Log.i(logTag, "丢弃上次未上报的残留时长：${staleState.size} 个应用（旧格式无时间戳，不再补报）")
                // 清掉持久化内容，避免下次启动又读到同一份陈旧数据喵
                prefs.pendingUsageState = ""
            }
        }
        // 界面上显示的欠账 = 待重发批次 + 累加器里新攒的（启动时后者是 0）喵
        updatePendingSeconds(pendingBatchSeconds())
        // 有没有补报批次决定日志要不要标"补报"喵
        hasPendingBacklog = pendingBatch != null
        // 喵~防御：把上次上报状态恢复回来，进程被杀后界面仍能看到上次结果喵
        val restoredReportStatus = prefs.readReportStatus()
        // 写进进程内快照，界面每秒读它显示"成功多久前 / 失败原因"喵
        updateReportStatus(restoredReportStatus)
        // 通知文案同步成恢复后的状态，避免通知写"尚未上报"而界面显示上次成功喵
        updateLastReport(ReportStatusText.describe(restoredReportStatus, true, System.currentTimeMillis()))
        // 创建通知渠道并进入前台喵
        ensureChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        // 标记为运行中，界面据此判断要不要再拉起喵
        markRunning(true)
        // 界面上的「运行日志」从这里开始有内容喵
        AgentLog.info("服务已启动，设备 ${prefs.deviceId()}")
    }

    /**
     * 处理启动与停止指令。
     *
     * 输出：START_STICKY 让系统在杀掉服务后尽量重启喵。
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 喵~防御：停止指令要能真正停掉循环喵
        if (intent?.action == ACTION_STOP) {
            AgentLog.info("收到停止指令，服务退出")
            stopSelf()
            return START_NOT_STICKY
        }
        // 喵~防御：配置不全时不要空转，记录日志后退出喵
        if (!prefs.isConfigured()) {
            Log.w(logTag, "配置不完整，服务不启动")
            AgentLog.warn("配置不完整（地址或口令），服务未启动")
            stopSelf()
            return START_NOT_STICKY
        }
        // 幂等启动采集循环喵
        startWorkerIfNeeded()
        return START_STICKY
    }

    /** 服务销毁时停止循环并移除通知喵。 */
    override fun onDestroy() {
        // 置位停止标记喵
        running = false
        // 标记为已停止喵
        markRunning(false)
        // 中断睡眠，让线程尽快退出喵
        workerThread?.interrupt()
        // 等待线程收尾，最多 2 秒喵
        workerThread?.join(2_000)
        workerThread = null
        // 移除前台通知喵
        stopForeground(STOP_FOREGROUND_REMOVE)
        AgentLog.info("服务已停止")
        super.onDestroy()
    }

    /** 本服务不支持绑定喵。 */
    override fun onBind(intent: Intent?): IBinder? = null

    /** 启动采集线程，重复调用无副作用喵。 */
    private fun startWorkerIfNeeded() {
        // 喵~防御：已有线程在跑就不要重复创建喵
        if (workerThread?.isAlive == true) return
        // 置位运行标记喵
        running = true
        // 创建并启动线程喵
        workerThread = Thread({ sampleLoop() }, "device-hub-worker").also { it.start() }
    }

    /**
     * 采样循环：按配置的采集频率采前台应用，按配置的上报频率发上报（10 到 60 秒，默认 60 秒）。
     *
     * 输出：无，循环直到 running 为 false。
     */
    private fun sampleLoop() {
        // 上一次上报的锚点时刻，按真实流逝时间判断该不该发喵
        var reportAnchorMillis = System.currentTimeMillis()
        // 上一轮采样结束的时刻，用来按真实流逝时间累计，而不是按名义周期喵
        var lastSampleAtMillis = System.currentTimeMillis()

    // 喵~注意：最后一次真正计入使用时长的时刻，上报时给色块落位喵
    var lastCountedAtMillis: Long? = null

    // 上一轮是不是"亮屏但拿不到前台应用"，决定这一轮要不要补记更长间隔喵
    var recoverGap = false
        // 亮屏起始时刻，用来上报"恢复计时"的精确边界喵
        var screenOnSinceMillis: Long? = null
        // 上一次写进日志的前台应用包名，只在切换时记一条喵
        var loggedPackage: String? = null
        // 上一次写进日志的亮屏状态喵
        var loggedScreenOn = true
        // 上一次写进日志的 AFK 状态喵
        var loggedAfk = false
        // 上一次落盘的时刻，避免每轮都写盘拖慢采样喵
        var lastPersistAtMillis = 0L
        // 本段窗口内的采样次数，用于写采集摘要喵
        var samplesInWindow = 0
        // 采集摘要的计时锚点喵
        var summaryAnchorMillis = System.currentTimeMillis()
        while (running) {
            // 本轮开始时刻，用来补偿采样耗时喵
            val loopStartedAtMillis = System.currentTimeMillis()
            // 每轮都重新读采集频率，主人改完配置下一轮就生效喵
            val sampleIntervalMillis = prefs.sampleIntervalSeconds * 1000L
            // 每轮都重新读上报频率，改完设置下一轮就按新间隔判定，不需要重启服务喵
            val reportIntervalSeconds = prefs.reportIntervalSeconds
            try {
                // 先看屏幕状态喵
                val screenOn = screenState.isInteractive()
                // 喵~注意：AFK 只看屏幕亮没亮——亮屏就算在用，不看有没有操作事件；
                // 息屏立刻算离开，服务端会把这段时间画成空档喵
                val afk = afkTracker.update(screenOn, System.currentTimeMillis())
                // 喵~注意：息屏时清掉前台缓存，避免上报里一直挂着息屏前那个应用喵
                val foregroundApp = if (screenOn) {
                    usageReader.currentForeground()
                } else {
                    usageReader.resetForeground()
                    null
                }
                // 记录亮屏起点，给"恢复计时"的精确边界用喵
                if (screenOn) {
                    if (screenOnSinceMillis == null) screenOnSinceMillis = loopStartedAtMillis
                } else {
                    screenOnSinceMillis = null
                }
                // 采集日志：亮屏/息屏变化时记一条，避免每轮刷屏喵
                if (screenOn != loggedScreenOn) {
                    loggedScreenOn = screenOn
                    AgentLog.info(if (screenOn) "采集：亮屏，恢复计时" else "采集：息屏，暂停计时")
                }
                // 采集日志：AFK 状态变化时记一条喵
                val afkChanged = afk != loggedAfk
                if (afkChanged) {
                    loggedAfk = afk
                    AgentLog.info(if (afk) "采集：判定为离开（AFK），本段计入空档" else "采集：已回到使用中")
                }
                // 采集日志：前台应用变化时记一条，主人能看到到底在统计谁喵
                if (foregroundApp != null && foregroundApp.packageName != loggedPackage) {
                    loggedPackage = foregroundApp.packageName
                    AgentLog.info("采集：前台切换到「${foregroundApp.name}」（${foregroundApp.packageName}）")
                }
                // 喵~注意：按真实流逝时间累计，循环被拖慢时不会凭空少记喵
                val nowMillis = System.currentTimeMillis()
                // 喵~注意：上一轮亮屏却拿不到前台应用时放宽上限，把那段秒数补回来喵
                // 喵~注意：上限按**实际配置的**采集间隔算，不能用手写常量，
                // 否则把采集间隔调到 60 秒后每轮只记 15 秒，会稳定丢时长喵
                val gapCap = SampleGapCap.capMillis(sampleIntervalMillis)
                val elapsedMillis = SampleGapCap.clampElapsed(nowMillis - lastSampleAtMillis, gapCap, recoverGap)
                // 喵~防御：没有前台应用（锁屏或系统没给事件）时也不计时喵
                if (foregroundApp != null && screenOn) {
                    // 喵~防御：新出现的应用顺手把图标传上去，同一个包只传一次喵
                    ensureIconUploaded(foregroundApp.packageName, foregroundApp.name)
                    // 喵~注意：整秒 + 余数拆分，余数留给下一轮，长期跑下来一秒都不会少喵
                    val (creditedSeconds, nextCarry) = SampleCredit.split(elapsedMillis, carryMillis)
                    // 余数先存好，下一轮凑够 1 秒再记喵
                    carryMillis = nextCarry
                    // 喵~防御：这一轮没凑够 1 秒就跳过，别产生 0 秒的脏条目喵
                    if (creditedSeconds > 0L) {
                        // 累加真实经过的秒数，同时带上包名供服务端排行与匹配喵
                        usageCalculator.addSeconds(
                            appName = foregroundApp.name,
                            seconds = creditedSeconds,
                            packageName = foregroundApp.packageName,
                        )
                        // 把最新待上报秒数同步给界面，主人能看到数字在涨喵
                        updatePendingSeconds(usageCalculator.totalSeconds())
                    }
                    // 喵~注意：记下"最后一秒"的真实时刻，上报时按它给色块落位喵
                    lastCountedAtMillis = nowMillis
                    // 这一轮真的计入了，下一轮不用补记喵
                    recoverGap = false
                    lastSampleAtMillis = nowMillis
                    // 喵~防御：定期落盘，服务被系统杀掉也能保住这段时间的数据喵
                    if (nowMillis - lastPersistAtMillis >= PERSIST_INTERVAL_MILLIS) {
                        lastPersistAtMillis = nowMillis
                        persistPendingUsage()
                    }
                }
                // 喵~注意：亮屏却拿不到前台应用时先不推进采样时刻，等下一次计入时一起补；
                // 息屏或 AFK 属于明确暂停，那段时间不能补，所以要推进喵
                if (screenOn && foregroundApp == null) {
                    recoverGap = true
                } else if (screenOn) {
                    lastSampleAtMillis = nowMillis
                } else {
                    recoverGap = false
                    lastSampleAtMillis = nowMillis
                    // 喵~注意：息屏 / AFK 那段本来就不计时，余数一起清掉，免得跨段累加喵
                    carryMillis = 0L
                }
                // 记一次采样，用于写采集摘要喵
                samplesInWindow += 1
                // 采集日志：每 5 分钟写一条摘要，证明采集循环还活着喵
                if (nowMillis - summaryAnchorMillis >= SUMMARY_INTERVAL_MILLIS) {
                    summaryAnchorMillis = nowMillis
                    val pendingSeconds = usageCalculator.totalSeconds()
                    AgentLog.info(
                        "采集：近 ${SUMMARY_INTERVAL_MILLIS / 60_000} 分钟采样 $samplesInWindow 次，" +
                            "待上报 $pendingSeconds 秒",
                    )
                    samplesInWindow = 0
                }
                // 喵~注意：AFK 状态一变就立刻上报一次（不受上报间隔拖累），服务端能马上拿到准确边界喵
                // 其余情况按主人设置的上报频率判定；间隔每轮重读，所以改完设置下一轮就生效喵
                if (ReportInterval.isDue(nowMillis, reportAnchorMillis, reportIntervalSeconds, afkChanged)) {
                    reportAnchorMillis = nowMillis
                    reportOnce(
                        foregroundApp = foregroundApp,
                        afk = afk,
                        afkSince = afkTracker.afkSinceMillis(),
                        activeSince = if (screenOn) screenOnSinceMillis else null,
                        usageEndedAtMillis = lastCountedAtMillis,
                    )
                }
            } catch (error: InterruptedException) {
                // 喵~防御：被中断说明服务在退出，直接结束循环喵
                Thread.currentThread().interrupt()
                return
            } catch (error: Exception) {
                // 喵~防御：任何异常都不能让循环退出，否则服务看起来"活着但不干活"喵
                Log.w(logTag, "采样异常：${error.message}")
                AgentLog.error("采样异常：${error.message}")
            }
            // 睡剩余时间，保证采样节奏稳定喵
            try {
                val workMillis = System.currentTimeMillis() - loopStartedAtMillis
                Thread.sleep((sampleIntervalMillis - workMillis).coerceAtLeast(0L))
            } catch (error: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            }
        }
    }

    /**
     * 组装并发送一次上报。
     *
     * 输入：本次采样到的前台应用（可为空）、AFK 判定结果、AFK 起点与恢复时刻（毫秒，可为空）。
     * 输出：无，结果记录在 lastReportText 与 lastReportStatus 并刷新通知。
     * 边界：失败时把这一批**冻结**成待重发批次（秒数 + 固定时刻）并落盘，绝不丢数据喵。
     *
     * 喵~注意：这里**不能**再按老办法「失败就把秒数还回累加器」。
     * 服务端用 (deviceId, reportedAt) 做幂等键，还回去会让下一批变成「旧+新」的超集
     * 并重新取当前时刻，服务端当成全新批次又加一遍，使用时长**永久翻倍**喵。
     * 现在改成：失败就冻结这一批，下一轮原样重发；成功后才去发新攒的数据喵。
     */
    private fun reportOnce(
        foregroundApp: ForegroundApp?,
        afk: Boolean = false,
        afkSince: Long? = null,
        activeSince: Long? = null,
        usageEndedAtMillis: Long? = null,
    ) {
        // 喵~注意：有上次没发出去的批次时优先重发它，这一轮不碰累加器喵
        val retryBatch = pendingBatch
        // 这一轮要发出去的增量喵
        val pendingDeltas: List<UsageDelta>
        // 这一批固定使用的上报时刻，重试期间绝不变喵
        val batchReportedAt: String
        if (retryBatch != null && !retryBatch.isEmpty) {
            // 重发上次冻结的那一批，秒数原样喵
            pendingDeltas = retryBatch.items
            // 时刻沿用第一次的，服务端才能认出是同一批喵
            batchReportedAt = retryBatch.reportedAt
        } else {
            // 正常路径：取走当前攒下的数据并清空累加器喵
            pendingDeltas = usageCalculator.drain()
            // 这一批的身份在这一刻定下来，之后重试都不再变喵
            batchReportedAt = IsoTime.nowUtc()
        }
        // 这一批的秒数与应用数先算好，日志与异常兜底都要用喵
        val pendingSeconds = pendingDeltas.sumOf { it.seconds }
        // 这一批涉及多少个应用喵
        val pendingApps = pendingDeltas.size
        // 喵~注意：重发期间累加器里的新数据原地留着，界面显示它还有多少没发喵
        updatePendingSeconds(usageCalculator.totalSeconds())
        // 这一批里是否含着上次失败留下的补报数据喵
        val includesBacklog = hasPendingBacklog && pendingDeltas.isNotEmpty()
        // 标记这一批是否已经冻结成待重发批次，避免 catch 重复处理喵
        var frozen = false
        try {
            // 喵~注意：afk 与使用时长可以同时上报——服务端会把这一批秒数照常入库，
            // 空档只从"没有使用的分钟"算起，所以不必再把 afk 压成 false（那会晚一整拍）喵
            val afkFlag = afk
            // 读取电量喵
            val battery = batteryReader.read()
            // 组装 JSON 喵
            val payload = ReportPayload.build(
                deviceId = prefs.deviceId(),
                // 喵~注意：把这一批的身份一起传下去，重试时服务端才能认出是同一批喵
                reportedAt = batchReportedAt,
                displayName = prefs.displayName.ifBlank { prefs.defaultDisplayName() },
                batteryPercent = battery?.percent,
                batteryCharging = battery?.charging,
                hardware = HardwareReader.collect(),
                currentAppName = foregroundApp?.name,
                currentAppPackage = foregroundApp?.packageName,
                currentAppSince = foregroundApp?.sinceIso,
                usageDelta = pendingDeltas,
                clientVersion = CLIENT_VERSION,
                tag = prefs.effectiveTag(),
                afk = afkFlag,
                // 喵~注意：边界时刻照旧带上，即使这一批因为还有使用量而报了 afk=false 喵
                afkSince = afkSince?.let { Instant.ofEpochMilli(it).toString() },
                activeSince = activeSince?.let { Instant.ofEpochMilli(it).toString() },
                // 喵~注意：色块按"最后一次计时"落位，上报慢一点也不会整体后移喵
                usageEndedAt = usageEndedAtMillis?.let { Instant.ofEpochMilli(it).toString() },
            )
            // 发送喵
            val result = reportClient.send(prefs.serverUrl, prefs.ingestToken, payload)
            // 记下本次上报时刻，状态与文案都用它，避免两处取到不同时间喵
            val reportAtMillis = System.currentTimeMillis()
            // 喵~注意：成功与失败都要更新上报状态，界面才知道上报到底有没有真的在发喵
            val reportStatus = if (result.success) {
                // 成功：只记结果与时刻喵
                ReportStatus.success(reportAtMillis)
            } else {
                // 失败：把错误摘要一起记下来，界面直接显示喵
                ReportStatus.failure(reportAtMillis, result.message)
            }
            // 先更新进程内快照，界面下一秒刷新就能看到喵
            updateReportStatus(reportStatus)
            // 再落盘，进程被杀后下次启动还能显示上次结果喵
            prefs.saveReportStatus(reportStatus)
            if (result.success) {
                // 成功就把磁盘上的待重发批次清掉，这一批到此为止喵
                updateLastReport("上报成功 ${IsoTime.nowUtc()}")
                pendingBatch = null
                prefs.pendingUsageState = ""
                // 喵~注意：这一批含着上次失败补报的数据时，日志里点出来，方便排查积压喵
                val backlogNote = if (includesBacklog) "（含补报）" else ""
                AgentLog.info("上报成功，应用 $pendingApps 个，共 $pendingSeconds 秒$backlogNote")
                // 补报已经发出去，标记清掉，下一批不再重复标注喵
                hasPendingBacklog = false
            } else {
                // 喵~防御：失败就把这一批**冻结**下来，秒数与时刻都原样，下一轮重发喵
                pendingBatch = PendingBatch(reportedAt = batchReportedAt, items = pendingDeltas)
                // 已经冻结好，catch 里不要再处理一次喵
                frozen = true
                // 喵~防御：冻结之后立刻落盘，避免这期间服务被杀又丢一次喵
                persistPendingUsage()
                // 界面上要同时显示「重发批次」与「新攒的数据」合起来的欠账喵
                updatePendingSeconds(pendingBatchSeconds() + usageCalculator.totalSeconds())
                // 喵~注意：把这一批记成补报，下一次成功日志里带一句「含补报」喵
                hasPendingBacklog = pendingDeltas.isNotEmpty()
                updateLastReport("上报失败：${result.message}")
                Log.w(logTag, lastReportText)
                // 喵~注意：失败日志写清冻结了多少秒、多少个应用，主人一眼知道积压规模喵
                AgentLog.warn(
                    "上报失败：${result.message}，已冻结 $pendingSeconds 秒 / $pendingApps 个应用待重发",
                )
            }
        } catch (error: Exception) {
            // 喵~防御：drain 之后的任何异常都要把这一批冻结住，绝不能因为异常丢数据喵
            if (!frozen) {
                // 把这一批冻起来，后面落盘失败也不会丢喵
                pendingBatch = PendingBatch(reportedAt = batchReportedAt, items = pendingDeltas)
                // 标记已经冻结，避免后续再处理一次喵
                frozen = true
            }
            // 喵~防御：不管异常发生在冻结之前还是之后，都再尝试落盘一次喵
            try {
                // 把当前待重发批次写回偏好，进程这时被杀也还能恢复喵
                persistPendingUsage()
            } catch (persistError: Exception) {
                // 写盘失败时数据还在内存里，至少本进程内还能重试喵
                Log.w(logTag, "缓存待重发批次失败：${persistError.message}")
                AgentLog.error("缓存待重发批次失败：${persistError.message}")
            }
            // 界面上的待补报秒数同步成冻结之后的欠账喵
            updatePendingSeconds(pendingBatchSeconds() + usageCalculator.totalSeconds())
            // 有数据才算补报，空批次失败不必虚报喵
            if (pendingDeltas.isNotEmpty()) {
                hasPendingBacklog = true
            }
            // 异常可能没有 message，用异常类名兜底，界面才不会出现"null"喵
            val errorText = error.message ?: error.javaClass.simpleName
            // 把这一轮记成失败状态，界面能看到失败原因与时刻喵
            val failedAtMillis = System.currentTimeMillis()
            val failureStatus = ReportStatus.failure(failedAtMillis, errorText)
            updateReportStatus(failureStatus)
            // 喵~防御：状态落盘失败也不能再抛，否则采集循环会误报成采样异常喵
            try {
                prefs.saveReportStatus(failureStatus)
            } catch (saveError: Exception) {
                Log.w(logTag, "保存上报状态失败：${saveError.message}")
            }
            // 通知文案同步成失败原因喵
            updateLastReport("上报失败：$errorText")
            // 写一条系统日志，方便 adb 排查喵
            Log.w(logTag, lastReportText)
            // 喵~注意：异常兜底日志写清缓存了多少秒待补报喵
            AgentLog.error("上报异常，已缓存 $pendingSeconds 秒待补报：$errorText")
        }
        // 刷新通知文案喵
        refreshNotification()
    }

    /** 把当前待上报数据写进偏好设置，供下次启动恢复喵。 */
    /**
     * 把待重发批次写进偏好设置。
     *
     * 喵~注意：这里存的是「批次」而不是裸的秒数字典——批次要带上固定的上报时刻，
     * 重启后才能原样重发、让服务端认出是同一批；只有秒数的话就没法保证幂等喵。
     */
    private fun persistPendingUsage() {
        // 编码后写入，编码本身会过滤非法数据喵
        prefs.pendingUsageState = pendingBatch?.let { batch -> PendingBatch.encode(batch) } ?: ""
    }

    /** 当前待重发批次的总秒数，没有批次时是 0喵。 */
    private fun pendingBatchSeconds(): Long {
        // 没有批次就没有欠账喵
        return pendingBatch?.totalSeconds ?: 0L
    }

    /** 创建通知渠道，Android 8 起必须先建渠道喵。 */
    private fun ensureChannel() {
        // 喵~防御：低版本没有渠道概念喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        // 取通知管理器喵
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        // 已存在就跳过喵
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        // 低优先级渠道，避免打扰用户喵
        val channel = NotificationChannel(CHANNEL_ID, "设备状态上报", NotificationManager.IMPORTANCE_LOW)
        // 渠道描述喵
        channel.description = "保持设备状态采集与上报运行"
        // 不显示角标喵
        channel.setShowBadge(false)
        // 创建渠道喵
        manager.createNotificationChannel(channel)
    }

    /** 构造前台服务通知喵。 */
    private fun buildNotification(): Notification {
        // 点击通知回到主界面喵
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        // minSdk 26，直接用带渠道的构造器，避免用到已废弃的无渠道版本喵
        val builder = Notification.Builder(this, CHANNEL_ID)
        return builder
            .setContentTitle("Device Hub 正在运行")
            .setContentText(lastReportText)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .build()
    }

    /** 用最新结果刷新通知文案喵。 */
    /**
     * 按需上传应用图标。
     *
     * 输入：包名、应用名。
     * 输出：无。
     * 边界：失败只记日志，下次采样会再试；成功后把「包名 → 内容哈希」记进本地喵。
     */
    private fun ensureIconUploaded(packageName: String, appName: String) {
        // 喵~防御：包名为空就没法归属图标喵
        if (packageName.isBlank()) return
        // 抠图标（拿到的是 PNG 的 base64）喵
        val pngBase64 = iconReader.iconBase64(packageName)
        if (pngBase64 == null) {
            // 喵~防御：抠不到就跳过，不要记哈希——否则换了图标也永远不重传喵
            return
        }
        // 把 base64 还原成 PNG 字节，喵~注意：哈希必须算在字节上，不能算在 base64 文本上喵
        val pngBytes = try {
            Base64.decode(pngBase64, Base64.NO_WRAP)
        } catch (error: IllegalArgumentException) {
            // 喵~防御：解码失败说明抠图结果坏了，跳过这一轮喵
            Log.d(logTag, "图标 base64 解码失败：$packageName ${error.message}")
            return
        }
        // 算本地图标的内容哈希喵
        val localHash = IconHash.contentHash(pngBytes)
        // 喵~注意：这里就是本次修复的核心——只有服务端记录的哈希与本地一致才跳过喵
        if (!IconHash.needsUpload(localHash, uploadedIconHashes[packageName])) return
        // 上传喵
        val result = reportClient.uploadIcon(
            serverUrl = prefs.serverUrl,
            ingestToken = prefs.ingestToken,
            app = appName,
            pkg = packageName,
            pngBase64 = pngBase64,
        )
        if (result.success) {
            // 记下新哈希，同一张图不再重传喵
            uploadedIconHashes[packageName] = localHash
            persistUploadedIcons()
            Log.i(logTag, "已上传应用图标：$packageName")
            AgentLog.info("已上传应用图标：$packageName")
        } else {
            Log.d(logTag, "上传图标失败：$packageName ${result.message}")
            AgentLog.warn("上传图标失败：$packageName ${result.message}")
        }
    }

    /** 把「包名 → 内容哈希」记录落盘喵。 */
    private fun persistUploadedIcons() {
        try {
            // 写回偏好，编码成「包名=哈希」的文本喵
            prefs.uploadedIconHashes = uploadedIconHashes.toMap()
        } catch (error: Exception) {
            // 喵~防御：写偏好失败不影响采集喵
            Log.w(logTag, "保存图标记录失败：${error.message}")
        }
    }

    private fun refreshNotification() {
        try {
            // 重新构造通知并更新喵
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.notify(NOTIFICATION_ID, buildNotification())
        } catch (error: Exception) {
            // 喵~防御：通知更新失败不影响采集，忽略喵
            Log.w(logTag, "刷新通知失败：${error.message}")
        }
    }

    companion object {
        // 停止服务的动作名喵
        const val ACTION_STOP = "io.github.happy66dev.devicehub.action.STOP"
        // 通知渠道 ID 喵
        const val CHANNEL_ID = "device_hub_status"
        // 前台通知 ID 喵
        const val NOTIFICATION_ID = 1001
        // 默认采样间隔，实际值取本地配置喵
        const val SAMPLE_INTERVAL_MILLIS = SampleInterval.DEFAULT_SECONDS * 1000L
        // 喵~注意：上报间隔不再写死，由本地配置 report_interval_seconds + ReportInterval 决定；
        // 上限 60 秒是硬约束——服务端心跳超时是 60 秒，间隔再大就会被判离线喵
        // 采集摘要的间隔，5 分钟写一条日志喵
        const val SUMMARY_INTERVAL_MILLIS = 5 * 60_000L
        // 单轮采样最多补记多久：循环被系统冻结后不要凭空记上几个小时喵
        //
        // 喵~注意：这是个**兜底常量**，真跑起来用 `SampleGapCap.capMillis(实际采集间隔)`。
        // 因为 `SampleInterval` 允许把采集间隔调到 60 秒，
        // 而这里按默认 5 秒乘 3 只有 15 秒——间隔调大后每轮只记 15 秒，
        // 会稳定丢掉大量使用时长且毫无日志痕迹喵
        const val MAX_SAMPLE_GAP_MILLIS = SampleGapCap.MIN_CAP_MILLIS

        // 喵~注意：上一轮拿不到前台应用时，这一段允许补记得更长，否则那几十秒直接消失喵
        // 喵~注意：这里同样是采样补记上限，与上报间隔无关，上报频率改到 10 秒也不会影响它喵
        const val MAX_RECOVER_MILLIS = 60_000L
        // 待上报数据落盘间隔，30 秒一次足够，避免每轮都写盘拖慢采样喵
        const val PERSIST_INTERVAL_MILLIS = 30_000L
        // 客户端版本，与服务端日志对齐喵
        const val CLIENT_VERSION = "0.5.1"

        // 服务是否正在运行，供界面与保活任务判断，避免重复拉起喵
        @Volatile
        var isRunning: Boolean = false
            private set

        // 最近一次上报结果，供通知展示喵
        @Volatile
        var lastReportText: String = "尚未上报"
            private set

        // 最近一次上报状态（结果/时刻/错误摘要），界面据此显示四种取值喵
        @Volatile
        var lastReportStatus: ReportStatus = ReportStatus.never()
            private set

        // 当前待补报的总秒数，界面每秒读它显示「待补报 N 分 N 秒」喵
        @Volatile
        var lastPendingSeconds: Long = 0L
            private set

        // 仅供本类内部改写的入口喵
        internal fun markRunning(value: Boolean) {
            // 直接写标记喵
            isRunning = value
        }

        // 更新最近一次上报结果，界面每秒读它显示状态喵
        internal fun updateLastReport(text: String) {
            // 直接写文本喵
            lastReportText = text
        }

        // 更新最近一次上报状态，服务与界面跨线程共享，用 volatile 保证可见性喵
        internal fun updateReportStatus(status: ReportStatus) {
            // 直接写快照喵
            lastReportStatus = status
        }

        /**
         * 更新待补报秒数快照。
         *
         * 输入：累加器当前的待上报总秒数。
         * 输出：无。
         * 边界：负数没有意义，按 0 处理喵。
         */
        internal fun updatePendingSeconds(seconds: Long) {
            // 喵~防御：脏数据不能把界面写成负数喵
            lastPendingSeconds = seconds.coerceAtLeast(0L)
        }
    }
}
