package io.github.happy66dev.devicehub.ui

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.Bundle
import android.provider.Settings
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import io.github.happy66dev.devicehub.core.AgentLog
import io.github.happy66dev.devicehub.core.ReportBacklog
import io.github.happy66dev.devicehub.core.ReportInterval
import io.github.happy66dev.devicehub.core.SampleInterval
import io.github.happy66dev.devicehub.core.ServiceStatus
import io.github.happy66dev.devicehub.collect.UsageReader
import io.github.happy66dev.devicehub.data.AgentPrefs
import io.github.happy66dev.devicehub.service.KeepAliveJob
import io.github.happy66dev.devicehub.service.UploadService

/**
 * 主界面：配置服务端、引导授予权限、启停上报。
 *
 * 界面全部用代码创建，不写 XML：本工程刻意不依赖 AndroidX，
 * 少一层依赖，构建更快，也少一类兼容问题喵。
 */
class MainActivity : Activity() {

    // 本地配置喵
    private lateinit var prefs: AgentPrefs

    // 前台应用读取器，只用来查权限与展示状态喵
    private val usageReader: UsageReader by lazy { UsageReader(this) }

    // 状态展示文本喵
    private lateinit var statusView: TextView

    // 顶部服务状态徽标喵
    private lateinit var serviceBadgeView: TextView

    // 上报状态行：从未上报 / 成功多久前 / 失败原因喵
    private lateinit var reportStatusView: TextView

    // 状态区模板：含「待补报」占位符，每秒只替换这一行喵
    private var statusTemplate: String = ""

    // 界面刷新用的主线程 Handler 喵
    private val uiHandler = Handler(Looper.getMainLooper())

    // 每秒刷一次服务状态的定时任务喵
    private val statusTicker = object : Runnable {
        override fun run() {
            // 只刷新徽标与上次上报，开销很小喵
            refreshServiceViews()
            // 状态区里的「待补报」秒数每秒都可能变，单独刷这一行喵
            refreshPendingStatus()
            // 继续排队，界面不可见时会被移除喵
            uiHandler.postDelayed(this, TICKER_INTERVAL_MILLIS)
        }
    }

    // 配置输入框喵
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var nameInput: EditText
    private lateinit var tagInput: EditText
    private lateinit var sampleIntervalInput: EditText
    // 上报频率输入框喵
    private lateinit var reportIntervalInput: EditText

    /** 界面创建入口喵。 */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 初始化配置对象喵
        prefs = AgentPrefs(this)
        // 设置界面喵
        setContentView(buildContentView())
        // 把已保存的配置填进输入框喵
        fillInputs()
        // 支持用 adb / 其它应用带参数拉起，方便批量部署喵
        applyIntentOverrides(intent)
        // 申请通知权限（Android 13 起必须）喵
        requestNotificationPermissionIfNeeded()
    }

    /** 界面被再次拉起时也要处理配置参数喵。 */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // 更新当前 Intent，保证 getIntent 拿到最新值喵
        setIntent(intent)
        // 应用参数喵
        applyIntentOverrides(intent)
    }

    /**
     * 从 Intent 里读取配置参数并应用。
     *
     * 用途：批量部署时不用手点界面，例如
     * `adb shell am start -n io.github.happy66dev.devicehub/.ui.MainActivity --es server_url http://x:8080 --es ingest_token xxx --ez autostart true`。
     * 边界：参数为空时忽略，不会把已保存的配置清空喵。
     */
    private fun applyIntentOverrides(intent: Intent?) {
        // 喵~防御：没有 Intent 直接返回喵
        if (intent == null) return
        // 读取可选参数喵
        val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL)
        val ingestToken = intent.getStringExtra(EXTRA_INGEST_TOKEN)
        val deviceName = intent.getStringExtra(EXTRA_DEVICE_NAME)
        val deviceTag = intent.getStringExtra(EXTRA_DEVICE_TAG)
        // 采集频率也可以用启动参数指定喵
        val sampleInterval = intent.getIntExtra(EXTRA_SAMPLE_INTERVAL, 0)
        // 上报频率同样可以用启动参数指定喵
        val reportInterval = intent.getIntExtra(EXTRA_REPORT_INTERVAL, 0)
        // 标记是否有变化喵
        var changed = false
        // 喵~防御：只有非空参数才覆盖，避免误清配置喵
        if (!serverUrl.isNullOrBlank()) {
            prefs.serverUrl = serverUrl
            changed = true
        }
        if (!ingestToken.isNullOrBlank()) {
            prefs.ingestToken = ingestToken
            changed = true
        }
        if (!deviceName.isNullOrBlank()) {
            prefs.displayName = deviceName
            changed = true
        }
        // 喵~防御：标签同样只在非空时覆盖喵
        if (!deviceTag.isNullOrBlank()) {
            prefs.tag = deviceTag
            changed = true
        }
        // 喵~防御：0 表示参数没带，正数才覆盖并夹到合法区间喵
        if (sampleInterval > 0) {
            prefs.sampleIntervalSeconds = sampleInterval
            changed = true
        }
        // 喵~防御：上报频率同理，0 表示没带，越界值由 AgentPrefs 夹到 10-60 喵
        if (reportInterval > 0) {
            prefs.reportIntervalSeconds = reportInterval
            changed = true
        }
        // 有变化时回填输入框并刷新状态喵
        if (changed) {
            fillInputs()
            refreshStatus()
            Toast.makeText(this, "已应用启动参数中的配置", Toast.LENGTH_SHORT).show()
        }
        // 参数里要求立即开始上报时直接启动喵
        if (intent.getBooleanExtra(EXTRA_AUTOSTART, false)) {
            startReporting()
        }
    }

    /** 每次回到界面都刷新一次状态，权限是用户去设置页改的喵。 */
    override fun onResume() {
        super.onResume()
        refreshStatus()
        // 喵~注意：用户之前开着上报、但服务被系统杀掉时，回到界面自动补上喵
        ensureServiceRunning()
        // 界面可见期间每秒刷新一次服务状态喵
        uiHandler.removeCallbacks(statusTicker)
        uiHandler.post(statusTicker)
    }

    /** 界面不可见时停掉状态刷新，省电喵。 */
    override fun onPause() {
        super.onPause()
        // 移除定时任务，避免后台空转喵
        uiHandler.removeCallbacks(statusTicker)
    }

    /** 构造界面：一个可滚动的纵向布局喵。 */
    private fun buildContentView(): ScrollView {
        // 外层滚动容器喵
        val scrollView = ScrollView(this)
        // 纵向布局喵
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(24))
        }
        // 标题喵
        container.addView(TextView(this).apply {
            text = "Device Hub 设备状态上报"
            textSize = 20f
        })
        // 服务状态徽标：绿点=在跑，红点=没跑，一眼就能看到喵
        serviceBadgeView = TextView(this).apply {
            textSize = 16f
            setPadding(0, dp(10), 0, dp(4))
        }
        container.addView(serviceBadgeView)
        // 上报状态行：从未上报 / 成功多久前 / 失败原因，跟着徽标一起每秒刷新喵
        reportStatusView = TextView(this).apply {
            textSize = 13f
            setPadding(0, 0, 0, dp(12))
        }
        container.addView(reportStatusView)
        // 说明文案喵
        container.addView(TextView(this).apply {
            text = "填写服务端地址与上报口令，授予使用情况权限后点击开始上报。"
            textSize = 13f
            setPadding(0, dp(8), 0, dp(16))
        })
        // 状态区喵
        statusView = TextView(this).apply {
            textSize = 13f
            setPadding(0, 0, 0, dp(16))
        }
        container.addView(statusView)
        // 服务端地址输入框喵
        serverInput = addLabeledInput(container, "服务端地址（含端口）", "http://192.168.2.245:8080")
        // 上报口令输入框喵
        tokenInput = addLabeledInput(container, "上报口令", "与 server/config.yaml 的 ingest.token 一致")
        // 设备名输入框喵
        nameInput = addLabeledInput(container, "设备名称（可留空）", "例如 小米 14")
        // 设备标签输入框，用于和服务器 scrcpy 窗口标题匹配喵
        tagInput = addLabeledInput(container, "设备标签（匹配投屏用，可留空）", "默认用手机型号，例如 23113RKC6C")
        // 采集频率输入框：1 到 60 秒的整数喵
        sampleIntervalInput = addLabeledInput(container, "采集频率（秒，1-60）", "默认 5 秒一次，填 1 到 60 之间的整数")
        // 上报频率输入框：10 到 60 秒的整数喵
        reportIntervalInput = addLabeledInput(container, "上报频率（秒，10-60）", "默认 60 秒一次，填 10 到 60 之间的整数")
        // 保存按钮喵
        container.addView(primaryButton("保存配置") { saveInputs() })
        // 启动按钮喵
        container.addView(primaryButton("开始上报") { startReporting() })
        // 停止按钮喵
        container.addView(primaryButton("停止上报") { stopReporting() })
        // 使用情况权限按钮喵
        container.addView(primaryButton("授予使用情况访问权限") { openUsageAccessSettings() })
        // 电池优化白名单按钮喵
        container.addView(primaryButton("忽略电池优化") { requestIgnoreBatteryOptimizations() })
        // 通知权限：Android 13 起没有它就看不到前台服务通知喵
        container.addView(primaryButton("通知权限设置") { openNotificationSettings() })
        // 应用详情页：各家 ROM 的自启动/后台限制开关都藏在这里喵
        container.addView(primaryButton("应用详情 / 自启动设置") { openAppDetailsSettings() })
        // 运行日志入口喵
        container.addView(primaryButton("查看运行日志") { openLogPage() })
        // 返回容器喵
        scrollView.addView(container)
        return scrollView
    }

    /** 添加"标签 + 输入框"组合，返回输入框喵。 */
    private fun addLabeledInput(container: LinearLayout, label: String, hint: String): EditText {
        // 标签喵
        container.addView(TextView(this).apply {
            text = label
            textSize = 14f
            setPadding(0, dp(8), 0, dp(4))
        })
        // 输入框喵
        val input = EditText(this).apply {
            this.hint = hint
            textSize = 14f
            setSingleLine(true)
        }
        // 加进容器并设置宽度喵
        container.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return input
    }

    /** 添加一个整宽按钮喵。 */
    private fun primaryButton(label: String, onClick: () -> Unit): Button {
        // 创建按钮喵
        val button = Button(this).apply {
            text = label
            setOnClickListener { onClick() }
        }
        // 上下留白喵
        val params = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        params.topMargin = dp(8)
        button.layoutParams = params
        return button
    }

    /** 把已保存的配置回填到输入框喵。 */
    private fun fillInputs() {
        serverInput.setText(prefs.serverUrl)
        tokenInput.setText(prefs.ingestToken)
        nameInput.setText(prefs.displayName)
        tagInput.setText(prefs.tag)
        sampleIntervalInput.setText(prefs.sampleIntervalSeconds.toString())
        // 回填上报频率，主人一眼能看到当前生效值喵
        reportIntervalInput.setText(prefs.reportIntervalSeconds.toString())
    }

    /** 保存输入框内容到本地配置喵。 */
    private fun saveInputs() {
        // 写入配置喵
        prefs.serverUrl = serverInput.text.toString()
        prefs.ingestToken = tokenInput.text.toString()
        prefs.displayName = nameInput.text.toString()
        prefs.tag = tagInput.text.toString()
        // 采集频率：填了非法内容就保持原值，填了越界值就夹到边界喵
        val typedInterval = SampleInterval.parse(sampleIntervalInput.text.toString())
        val previousInterval = prefs.sampleIntervalSeconds
        if (typedInterval != null) {
            prefs.sampleIntervalSeconds = typedInterval
        }
        // 回填实际生效值，让主人一眼看到真实频率喵
        sampleIntervalInput.setText(prefs.sampleIntervalSeconds.toString())
        // 上报频率：先记下用户原始输入，回填之后就看不出来了喵
        val typedReportText = reportIntervalInput.text.toString()
        val typedReportInterval = ReportInterval.parse(typedReportText)
        val previousReportInterval = prefs.reportIntervalSeconds
        // 喵~防御：非整数保持原值，越界值由 ReportInterval 夹到 10 或 60 喵
        if (typedReportInterval != null) {
            prefs.reportIntervalSeconds = typedReportInterval
        }
        // 回填实际生效值，避免输入框里留着 999 而实际是 60 喵
        reportIntervalInput.setText(prefs.reportIntervalSeconds.toString())
        // 提示结果喵
        val baseText = if (prefs.isConfigured()) "配置已保存" else "配置已保存，但地址或口令不合法"
        val intervalText = if (typedInterval == null && sampleIntervalInput.text.toString().isNotBlank()) {
            "；采集频率填的不是整数，保持 ${SampleInterval.describe(previousInterval)}"
        } else {
            "；${SampleInterval.describe(prefs.sampleIntervalSeconds)}"
        }
        // 上报频率的提示：非整数说明保持了原值，合法值直接说新频率喵
        val reportText = if (typedReportInterval == null && typedReportText.isNotBlank()) {
            "；上报频率填的不是整数，保持 ${ReportInterval.describe(previousReportInterval)}"
        } else {
            "；${ReportInterval.describe(prefs.reportIntervalSeconds)}"
        }
        Toast.makeText(this, baseText + intervalText + reportText, Toast.LENGTH_SHORT).show()
        // 刷新状态喵
        refreshStatus()
    }

    /** 保存配置并启动前台服务喵。 */
    private fun startReporting() {
        // 先保存，避免用户忘了点保存喵
        saveInputs()
        // 喵~防御：配置不合法就不启动，否则服务会立刻退出，用户以为坏了喵
        if (!prefs.isConfigured()) {
            Toast.makeText(this, "请先填写 http(s) 地址与至少 8 位的口令", Toast.LENGTH_LONG).show()
            return
        }
        // 喵~防御：缺权限一律不让启动，否则服务跑起来也采不到任何数据喵
        if (!checkPermissionsBeforeStart()) return
        // 记录用户意图，供开机自启判断喵
        prefs.reportingEnabled = true
        // 排上保活任务，ROM 吞掉自启或杀掉服务时还能兜住喵
        KeepAliveJob.schedule(this)
        try {
            // 启动前台服务喵
            val intent = Intent(this, UploadService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            Toast.makeText(this, "已开始上报", Toast.LENGTH_SHORT).show()
        } catch (error: Exception) {
            // 喵~防御：Android 12 起前台服务启动可能被系统拒绝，提示用户稍后再试喵
            Toast.makeText(this, "启动失败：${error.message}", Toast.LENGTH_LONG).show()
        }
        // 刷新状态喵
        refreshStatus()
    }

    /**
     * 启动前的权限闸门。
     *
     * 输出：true 表示权限齐全可以启动；false 表示缺权限，已提示并跳到对应设置页。
     * 边界：电池优化只做提示不拦截，它不是权限，挡着不让用反而更烦喵。
     */
    private fun checkPermissionsBeforeStart(): Boolean {
        // 喵~防御：没有使用情况权限就采不到前台应用，直接拦住喵
        if (!usageReader.hasUsageAccess()) {
            Toast.makeText(this, "缺少「使用情况访问」权限，无法采集应用使用数据", Toast.LENGTH_LONG).show()
            openUsageAccessSettings()
            return false
        }
        // 喵~防御：Android 13 起没有通知权限时前台服务通知会被隐藏，先申请再让用户重试喵
        if (!isNotificationGranted()) {
            Toast.makeText(this, "缺少「通知」权限，请授予后再点开始上报", Toast.LENGTH_LONG).show()
            requestNotificationPermissionIfNeeded()
            return false
        }
        // 喵~注意：电池优化没忽略只提示不拦截，免得用户被挡在门外喵
        if (!isBatteryOptimizationIgnored()) {
            Toast.makeText(this, "建议顺手忽略电池优化，否则后台可能被系统杀掉", Toast.LENGTH_LONG).show()
        }
        return true
    }

    /**
     * 服务不在跑但用户之前开着上报时，自动补拉一次。
     *
     * 用途：手机重启后系统吞掉自启广播、或服务被 ROM 杀掉时，
     * 用户只要打开一次界面就能恢复上报喵。
     */
    private fun ensureServiceRunning() {
        // 喵~防御：用户没开启上报就不要自作主张喵
        if (!prefs.reportingEnabled) return
        // 喵~防御：配置不完整时拉起也没用喵
        if (!prefs.isConfigured()) return
        // 喵~防御：权限不齐时拉起也采不到数据，等用户补授权喵
        if (!usageReader.hasUsageAccess() || !isNotificationGranted()) return
        // 喵~防御：服务已经在跑就不要再拉一次喵
        if (UploadService.isRunning) return
        try {
            // 静默拉起前台服务喵
            val intent = Intent(this, UploadService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            // 补排一次保活任务，避免任务被 ROM 清掉喵
            KeepAliveJob.schedule(this)
            AgentLog.info("界面检测到上报未运行，已自动恢复")
        } catch (error: Exception) {
            // 喵~防御：后台启动被拒时只记日志，等用户手动点开始上报喵
            AgentLog.warn("自动恢复上报失败：${error.message}")
        }
    }

    /** 停止上报并清除自启标记喵。 */
    private fun stopReporting() {
        // 清除意图标记喵
        prefs.reportingEnabled = false
        // 取消保活任务，避免停了又被拉起来喵
        KeepAliveJob.cancel(this)
        // 发送停止指令喵
        startService(Intent(this, UploadService::class.java).setAction(UploadService.ACTION_STOP))
        // 提示喵
        Toast.makeText(this, "已停止上报", Toast.LENGTH_SHORT).show()
        // 刷新状态喵
        refreshStatus()
    }

    /** 跳转到系统的使用情况访问设置页喵。 */
    private fun openUsageAccessSettings() {
        try {
            // 该页面没有公开的精确 Intent，只能跳到列表页让用户自己找喵
            startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
        } catch (error: Exception) {
            // 喵~防御：个别 ROM 没有这个页面，退回到应用详情页喵
            startActivity(Intent(Settings.ACTION_SETTINGS))
        }
    }

    /** 请求把自己加入电池优化白名单喵。 */
    private fun requestIgnoreBatteryOptimizations() {
        // 喵~防御：只有 Android 6 以上才有这个机制喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        try {
            // 直接弹出系统的"是否忽略电池优化"对话框喵
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = Uri.parse("package:$packageName")
            startActivity(intent)
        } catch (error: Exception) {
            // 喵~防御：部分 ROM 不允许直接弹窗，退回到电池优化列表页喵
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (innerError: Exception) {
                Toast.makeText(this, "请在系统设置中手动允许后台运行", Toast.LENGTH_LONG).show()
            }
        }
    }

    /** 打开系统通知设置页，方便用户补授通知权限喵。 */
    private fun openNotificationSettings() {
        try {
            // 先尝试直接跳本应用的通知设置喵
            val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            intent.putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            startActivity(intent)
        } catch (error: Exception) {
            // 喵~防御：老 ROM 没有这个页面，退回到应用详情页喵
            openAppDetailsSettings()
        }
    }

    /** 打开本应用详情页：自启动、后台限制、权限都在这里喵。 */
    private fun openAppDetailsSettings() {
        try {
            // 系统应用详情页喵
            val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            intent.data = Uri.parse("package:$packageName")
            startActivity(intent)
        } catch (error: Exception) {
            // 喵~防御：连详情页都打不开时退到设置首页喵
            Toast.makeText(this, "请手动在系统设置里找到本应用", Toast.LENGTH_LONG).show()
            startActivity(Intent(Settings.ACTION_SETTINGS))
        }
    }

    /** 打开运行日志页喵。 */
    private fun openLogPage() {
        // 直接拉起日志页喵
        startActivity(Intent(this, LogActivity::class.java))
    }

    /** 判断当前是否已加入电池优化白名单喵。 */
    private fun isBatteryOptimizationIgnored(): Boolean {
        // 喵~防御：低版本没有这个机制，按"已忽略"处理免得误导喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        return try {
            // 取电源服务查询白名单喵
            val manager = getSystemService(Context.POWER_SERVICE) as PowerManager
            manager.isIgnoringBatteryOptimizations(packageName)
        } catch (error: Exception) {
            // 喵~防御：个别 ROM 不实现该接口，按未知处理喵
            false
        }
    }

    /** 判断通知权限是否已授予喵。 */
    private fun isNotificationGranted(): Boolean {
        // 喵~防御：Android 13 以下发通知不需要运行时权限喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED
    }

    /** Android 13 起申请通知权限，否则前台服务通知不显示喵。 */
    private fun requestNotificationPermissionIfNeeded() {
        // 喵~防御：低版本没有运行时通知权限喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        // 申请权限，结果不影响采集逻辑喵
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATION)
    }

    /**
     * 刷新顶部的服务状态徽标与上次上报结果。
     *
     * 用途：界面可见时每秒调用一次，主人能立刻看到服务是活着还是被系统杀掉了喵。
     */
    private fun refreshServiceViews() {
        // 读取服务运行状态喵
        val running = UploadService.isRunning
        // 运行中显示绿点，未运行显示红点喵
        serviceBadgeView.text = if (running) "● 服务运行中，正在采集" else "● 服务未运行，未在采集"
        serviceBadgeView.setTextColor(if (running) COLOR_RUNNING else COLOR_STOPPED)
        // 喵~注意：运行状态与上报状态取同一时刻的快照，避免两行文案互相矛盾喵
        val status = ServiceStatus(running = running, report = UploadService.lastReportStatus)
        // 上报状态行：服务未运行 / 从未上报 / 成功多久前 / 失败原因喵
        reportStatusView.text = "上报状态：${status.reportText(System.currentTimeMillis())}"
        // 颜色跟着结果走，一眼就能看出上报是不是真的在发喵
        reportStatusView.setTextColor(
            when {
                // 服务没跑时用灰色，别用红色冒充"上报失败"喵
                !running -> COLOR_REPORT_IDLE
                // 上次成功用绿色喵
                status.report.isSuccess -> COLOR_REPORT_OK
                // 上次失败用红色喵
                status.report.isFailure -> COLOR_REPORT_FAIL
                // 从未上报用灰色喵
                else -> COLOR_REPORT_IDLE
            },
        )
    }

    /** 刷新状态区文案喵。 */
    private fun refreshStatus() {
        // 读取权限状态喵
        val usageGranted = usageReader.hasUsageAccess()
        // 读取配置状态喵
        val configured = prefs.isConfigured()
        // 先刷新顶部徽标喵
        refreshServiceViews()
        // 拼装多行状态喵
        val lines = buildList {
            add("设备 ID：${prefs.deviceId()}")
            add("设备名：${prefs.displayName.ifBlank { prefs.defaultDisplayName() }}")
            add("设备标签：${prefs.effectiveTag()}")
            add("采集频率：${SampleInterval.describe(prefs.sampleIntervalSeconds)}")
            add("上报频率：${ReportInterval.describe(prefs.reportIntervalSeconds)}")
            add("配置：${if (configured) "完整" else "不完整"}")
            add("使用情况权限：${if (usageGranted) "已授予" else "未授予（缺少时无法开始上报）"}")
            add("通知权限：${if (isNotificationGranted()) "已授予" else "未授予（缺少时无法开始上报）"}")
            add("电池优化：${if (isBatteryOptimizationIgnored()) "已忽略（可后台运行）" else "未忽略（可能被杀）"}")
            add("上报开关：${if (prefs.reportingEnabled) "已开启" else "已关闭"}")
            add("上报服务：${if (UploadService.isRunning) "运行中" else "未运行"}")
            // 上报状态与服务徽标同一口径，四种取值都能在这里看到喵
            add(
                "上报状态：" + ServiceStatus(UploadService.isRunning, UploadService.lastReportStatus)
                    .reportText(System.currentTimeMillis()),
            )
            add("上次上报：${UploadService.lastReportText}")
            // 待补报行先用占位符，交给每秒刷新替换，避免整块状态区重复计算喵
            add(PENDING_PLACEHOLDER)
            add("日志行数：${AgentLog.size()}（最多 ${AgentLog.MAX_LINES} 行）")
        }
        // 保存状态区模板，供每秒刷新只替换「待补报」行喵
        statusTemplate = lines.joinToString("\n")
        // 立刻渲染一次，界面刚打开就能看到当前待补报秒数喵
        refreshPendingStatus()
    }

    /**
     * 只刷新状态区里的「待补报」行。
     *
     * 输入：无，直接读 UploadService 的进程内快照。
     * 输出：无。
     * 边界：状态模板还没生成时直接返回，避免把状态区覆盖成半截喵。
     */
    private fun refreshPendingStatus() {
        // 喵~防御：状态区模板还没生成时先跳过喵
        if (statusTemplate.isEmpty()) return
        // 读取服务维护的待补报总秒数快照喵
        val pendingSeconds = UploadService.lastPendingSeconds
        // 0 秒时纯函数返回空串，界面仍显示「待补报 0 秒」，主人一眼能确认没有积压喵
        val pendingLine = ReportBacklog.pendingText(pendingSeconds).ifBlank { "待补报 0 秒" }
        // 只替换占位符，静态行不重新计算，省掉每秒重复查权限的开销喵
        statusView.text = statusTemplate.replace(PENDING_PLACEHOLDER, pendingLine)
    }

    /** dp 转像素，保证不同屏幕密度下间距一致喵。 */
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        // 通知权限请求码喵
        private const val REQUEST_NOTIFICATION = 1001
        // 启动参数：服务端地址喵
        const val EXTRA_SERVER_URL = "server_url"
        // 启动参数：上报口令喵
        const val EXTRA_INGEST_TOKEN = "ingest_token"
        // 启动参数：设备名喵
        const val EXTRA_DEVICE_NAME = "device_name"
        // 启动参数：设备标签喵
        const val EXTRA_DEVICE_TAG = "device_tag"
        // 启动参数：采集频率（秒）喵
        const val EXTRA_SAMPLE_INTERVAL = "sample_interval"
        // 启动参数：上报频率（秒）喵
        const val EXTRA_REPORT_INTERVAL = "report_interval"
        // 启动参数：是否立即开始上报喵
        const val EXTRA_AUTOSTART = "autostart"
        // 状态徽标刷新间隔，1 秒喵
        private const val TICKER_INTERVAL_MILLIS = 1_000L
        // 状态区里「待补报」行的占位符，每秒只替换它喵
        private const val PENDING_PLACEHOLDER = "__pending_backlog__"
        // 运行中的徽标颜色（绿）喵
        private val COLOR_RUNNING = Color.rgb(10, 125, 50)
        // 未运行的徽标颜色（红）喵
        private val COLOR_STOPPED = Color.rgb(179, 38, 30)
        // 上报成功的状态行颜色（绿）喵
        private val COLOR_REPORT_OK = Color.rgb(10, 125, 50)
        // 上报失败的状态行颜色（红）喵
        private val COLOR_REPORT_FAIL = Color.rgb(179, 38, 30)
        // 未运行或从未上报的状态行颜色（灰）喵
        private val COLOR_REPORT_IDLE = Color.rgb(96, 96, 96)
    }
}
