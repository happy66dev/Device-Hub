package io.github.happy66dev.devicehub.data

import android.content.Context
import android.os.Build
import io.github.happy66dev.devicehub.core.DeviceIdentity
import io.github.happy66dev.devicehub.core.IconHash
import io.github.happy66dev.devicehub.core.ReportInterval
import io.github.happy66dev.devicehub.core.ReportOutcome
import io.github.happy66dev.devicehub.core.ReportStatus
import io.github.happy66dev.devicehub.core.SampleInterval
import kotlin.random.Random

/**
 * 本地配置存储：服务端地址、上报口令、设备 ID、设备名。
 *
 * 为什么用 SharedPreferences：只有四五个字段，不需要数据库；
 * 设备 ID 必须持久化，否则每次重启都会变成"新设备"喵。
 */
class AgentPrefs(context: Context) {

    // 偏好文件名喵
    private val preferences = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    // 应用上下文，用于读取型号喵
    private val appContext = context.applicationContext

    /** 服务端基地址，例如 http://192.168.2.245:8080 喵。 */
    var serverUrl: String
        get() = preferences.getString(KEY_SERVER_URL, "") ?: ""
        set(value) = preferences.edit().putString(KEY_SERVER_URL, value.trim()).apply()

    /** 上报口令，必须与服务端 ingest.token 一致喵。 */
    var ingestToken: String
        get() = preferences.getString(KEY_INGEST_TOKEN, "") ?: ""
        set(value) = preferences.edit().putString(KEY_INGEST_TOKEN, value.trim()).apply()

    /** 设备显示名，默认取厂商 + 型号喵。 */
    var displayName: String
        get() = preferences.getString(KEY_DISPLAY_NAME, "") ?: ""
        set(value) = preferences.edit().putString(KEY_DISPLAY_NAME, value.trim()).apply()

    /** 设备标签，用于和服务端 scrcpy 窗口标题匹配喵。 */
    var tag: String
        get() = preferences.getString(KEY_TAG, "") ?: ""
        set(value) = preferences.edit().putString(KEY_TAG, value.trim().take(MAX_TAG_LENGTH)).apply()

    /** 采集频率（秒），1 到 60 的整数，默认 5 秒一次喵。 */
    var sampleIntervalSeconds: Int
        // 读出来再夹一次，防止旧版本存进越界值喵
        get() = SampleInterval.normalize(preferences.getInt(KEY_SAMPLE_INTERVAL, SampleInterval.DEFAULT_SECONDS))
        // 写入前夹到合法区间，界面就不必反复判断喵
        set(value) = preferences.edit()
            .putInt(KEY_SAMPLE_INTERVAL, SampleInterval.normalize(value))
            .apply()

    /**
     * 上报频率（秒），10 到 60 的整数，默认 60 秒一次喵。
     *
     * 喵~注意：上限 60 秒是硬约束——服务端心跳超时 180 秒，
     * 再放宽重试余量就不够了，会出现"服务还在跑、服务端却画成离线"的假空档喵。
     */
    var reportIntervalSeconds: Int
        // 读出来再夹一次，防止旧版本或手工改文件存进越界值喵
        get() = ReportInterval.normalize(preferences.getInt(KEY_REPORT_INTERVAL, ReportInterval.DEFAULT_SECONDS))
        // 写入前夹到合法区间，非法值永远不会落盘喵
        set(value) = preferences.edit()
            .putInt(KEY_REPORT_INTERVAL, ReportInterval.normalize(value))
            .apply()

    /**
     * 已上传图标的「包名 → 内容哈希」记录，避免重复上传喵。
     *
     * 喵~注意：旧版本这里存的是逗号分隔的纯包名列表，读到时哈希为空，
     * 会被当作「没有哈希」，首次启动会把图标重传一遍——这是可接受的迁移代价喵。
     */
    var uploadedIconHashes: Map<String, String>
        get() = IconHash.decode(preferences.getString(KEY_UPLOADED_ICONS, "") ?: "")
        set(value) = preferences.edit()
            .putString(KEY_UPLOADED_ICONS, IconHash.encode(value))
            .apply()

    /** 是否已开启上报（用于开机自启后判断要不要拉起服务）喵。 */
    var reportingEnabled: Boolean
        get() = preferences.getBoolean(KEY_REPORTING_ENABLED, false)
        set(value) = preferences.edit().putBoolean(KEY_REPORTING_ENABLED, value).apply()

    /** 待上报使用时长序列化后的文本，用于服务被杀后恢复数据喵。 */
    var pendingUsageState: String
        get() = preferences.getString(KEY_PENDING_USAGE, "") ?: ""
        set(value) = preferences.edit().putString(KEY_PENDING_USAGE, value).apply()

    /**
     * 读取最近一次上报状态。
     *
     * 输出：进程重启后仍能显示的最近一次上报结果。
     * 边界：偏好里没有记录或枚举名无法识别时返回「从未上报」，不抛异常喵。
     */
    fun readReportStatus(): ReportStatus {
        // 先读结果枚举名，未知值一律当"从未上报"喵
        val outcome = when (preferences.getString(KEY_REPORT_OUTCOME, "")) {
            // 成功记录喵
            ReportOutcome.SUCCESS.name -> ReportOutcome.SUCCESS
            // 失败记录喵
            ReportOutcome.FAILURE.name -> ReportOutcome.FAILURE
            // 喵~防御：空值或旧版本遗留的未知值都按从未上报处理喵
            else -> ReportOutcome.NEVER
        }
        // 喵~防御：从未上报就不要读时刻与错误，避免界面显示"失败（1970 年前）"喵
        if (outcome == ReportOutcome.NEVER) return ReportStatus.never()
        // 读时刻，缺失时用 null 表示未知，界面会省略"多久之前"喵
        val atMillis = preferences.getLong(KEY_REPORT_AT_MILLIS, 0L).takeIf { it > 0L }
        // 只有失败才需要错误摘要喵
        val errorSummary = if (outcome == ReportOutcome.FAILURE) {
            preferences.getString(KEY_REPORT_ERROR, "")?.takeIf { it.isNotBlank() }
        } else {
            null
        }
        // 组装状态快照喵
        return ReportStatus(outcome = outcome, atMillis = atMillis, errorSummary = errorSummary)
    }

    /**
     * 保存最近一次上报状态。
     *
     * 输入：服务上报后构造的状态快照。
     * 边界：一次提交三个字段，避免写到一半被杀留下半套状态喵。
     */
    fun saveReportStatus(status: ReportStatus) {
        // 结果、时刻、错误一起写，读的时候才不会互相矛盾喵
        preferences.edit()
            .putString(KEY_REPORT_OUTCOME, status.outcome.name)
            .putLong(KEY_REPORT_AT_MILLIS, status.atMillis ?: 0L)
            .putString(KEY_REPORT_ERROR, status.errorSummary ?: "")
            .apply()
    }

    /** 读取设备 ID，不存在时按型号生成并落盘喵。 */
    fun deviceId(): String {
        // 先读已有值喵
        val stored = preferences.getString(KEY_DEVICE_ID, "") ?: ""
        // 喵~防御：已有合法值就直接复用，避免设备在群里"改名"喵
        if (stored.isNotBlank()) return stored
        // 生成新 ID 喵
        val generated = DeviceIdentity.build(modelName(), DeviceIdentity.randomSuffix(Random.Default))
        // 落盘喵
        preferences.edit().putString(KEY_DEVICE_ID, generated).apply()
        return generated
    }

    /** 型号名，优先用 Build.MODEL 喵。 */
    fun modelName(): String {
        // 喵~防御：个别机型 MODEL 为空，退回厂商名喵
        val model = Build.MODEL ?: ""
        if (model.isBlank()) return Build.MANUFACTURER ?: DeviceIdentity.FALLBACK_MODEL
        return model
    }

    /**
     * 实际生效的标签。
     *
     * 输出：用户填写的标签；没填时用型号名兜底，保证服务端总能匹配上喵。
     */
    fun effectiveTag(): String {
        // 先取用户填写的标签喵
        val configured = tag
        // 喵~防御：没填标签时用型号名，型号正是 scrcpy 窗口标题里常见的内容喵
        return configured.ifBlank { modelName().take(MAX_TAG_LENGTH) }
    }

    /** 默认设备名，形如 "Google Pixel 7" 喵。 */
    fun defaultDisplayName(): String {
        // 厂商名首字母大写，型号原样保留喵
        val manufacturer = (Build.MANUFACTURER ?: "").trim().replaceFirstChar { it.uppercase() }
        val model = (Build.MODEL ?: "").trim()
        // 喵~防御：两者都为空时用固定文案喵
        if (manufacturer.isBlank() && model.isBlank()) return "Android 设备"
        if (manufacturer.isBlank()) return model
        if (model.isBlank()) return manufacturer
        return "$manufacturer $model"
    }

    /** 判断配置是否齐全，决定能否启动上报喵。 */
    fun isConfigured(): Boolean {
        // 地址必须是 http(s) 开头，口令至少 8 位，与服务端校验保持一致喵
        val urlOk = serverUrl.startsWith("http://") || serverUrl.startsWith("https://")
        return urlOk && ingestToken.length >= 8
    }

    companion object {
        // 偏好文件名喵
        private const val PREF_NAME = "device_hub_prefs"
        // 各字段键名喵
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_INGEST_TOKEN = "ingest_token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DISPLAY_NAME = "display_name"
        // 设备标签键名喵
        private const val KEY_TAG = "device_tag"
        // 采集频率键名喵
        private const val KEY_SAMPLE_INTERVAL = "sample_interval_seconds"
        // 标签最大长度，与服务端字段限制一致喵
        const val MAX_TAG_LENGTH = 64
        private const val KEY_REPORTING_ENABLED = "reporting_enabled"
        // 喵~注意：键名沿用旧值不变，只是值格式从「包名列表」升级成「包名=哈希」喵
        private const val KEY_UPLOADED_ICONS = "uploaded_icon_packages"
        // 待上报使用时长键名喵
        private const val KEY_PENDING_USAGE = "pending_usage_state"
        // 上报频率键名，沿用现有 SharedPreferences 文件喵
        private const val KEY_REPORT_INTERVAL = "report_interval_seconds"
        // 最近一次上报结果的键名喵
        private const val KEY_REPORT_OUTCOME = "last_report_outcome"
        // 最近一次上报时刻的键名喵
        private const val KEY_REPORT_AT_MILLIS = "last_report_at_millis"
        // 最近一次上报错误的键名喵
        private const val KEY_REPORT_ERROR = "last_report_error"
    }
}
