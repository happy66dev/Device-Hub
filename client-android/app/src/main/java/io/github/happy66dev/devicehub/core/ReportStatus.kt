package io.github.happy66dev.devicehub.core

/**
 * 上报结果的三种基础取值。
 *
 * 第四种「服务未运行」不是上报结果，而是服务状态，由 [ServiceStatus] 结合运行标记得出喵。
 */
enum class ReportOutcome {
    // 本次进程还没成功或失败地上报过一次喵
    NEVER,
    // 最近一次上报成功喵
    SUCCESS,
    // 最近一次上报失败喵
    FAILURE,
}

/**
 * 上报状态模型：最近一次上报的结果、时刻与错误摘要。
 *
 * 为什么单独建模：以前界面只拿得到一句 UploadService.lastReportText 文本，
 * 既分不清"从未上报"和"上报失败"，也没法算"多久之前"；
 * 抽成纯数据类之后，文案计算可以在 JVM 单元测试里直接覆盖喵。
 */
data class ReportStatus(
    // 最近一次上报的结果喵
    val outcome: ReportOutcome = ReportOutcome.NEVER,
    // 最近一次上报发生的时刻（毫秒时间戳），从未上报时为 null 喵
    val atMillis: Long? = null,
    // 失败原因摘要，成功或从未上报时为 null 喵
    val errorSummary: String? = null,
) {
    // 是否从未上报喵
    val isNever: Boolean get() = outcome == ReportOutcome.NEVER

    // 是否最近一次成功喵
    val isSuccess: Boolean get() = outcome == ReportOutcome.SUCCESS

    // 是否最近一次失败喵
    val isFailure: Boolean get() = outcome == ReportOutcome.FAILURE

    companion object {
        // 从未上报的初始状态喵
        fun never(): ReportStatus = ReportStatus()

        /**
         * 构造"上报成功"状态。
         *
         * 输入：上报成功的时刻（毫秒）。
         * 输出：带时刻的成功状态喵。
         */
        fun success(atMillis: Long): ReportStatus {
            // 成功时清空错误摘要，避免界面残留上一次的失败原因喵
            return ReportStatus(outcome = ReportOutcome.SUCCESS, atMillis = atMillis, errorSummary = null)
        }

        /**
         * 构造"上报失败"状态。
         *
         * 输入：失败时刻（毫秒）、原始错误文本。
         * 输出：带错误摘要的失败状态喵。
         * 边界：错误文本会先压成单行短摘要，超长部分截断喵。
         */
        fun failure(atMillis: Long, message: String?): ReportStatus {
            // 摘要在这里就算好，界面只负责显示喵
            return ReportStatus(
                outcome = ReportOutcome.FAILURE,
                atMillis = atMillis,
                errorSummary = ReportStatusText.summarizeError(message),
            )
        }
    }
}

/**
 * 界面状态模型：服务是否在跑 + 最近一次上报状态。
 *
 * 为什么合并成一个快照：徽标和上报状态行必须基于同一时刻的状态，
 * 否则会出现「服务未运行」和「上报成功」同时显示的矛盾画面喵。
 */
data class ServiceStatus(
    // 服务是否正在运行喵
    val running: Boolean,
    // 最近一次上报状态喵
    val report: ReportStatus,
) {
    /**
     * 上报状态行的文案。
     *
     * 输入：当前时刻，用来算"多久之前"。
     * 输出：四种取值之一，见 [ReportStatusText.describe] 喵。
     */
    fun reportText(nowMillis: Long): String {
        // 直接交给文案工具，保持纯函数、可单测喵
        return ReportStatusText.describe(status = report, serviceRunning = running, nowMillis = nowMillis)
    }
}

/**
 * 上报状态文案渲染，纯函数集合，方便单元测试覆盖四种取值喵。
 *
 * 文案口径（产品界面不许出现「喵」）：
 * - 服务未运行：服务未运行，未在上报
 * - 从未上报：从未上报
 * - 上次成功：上报成功（N 秒前）
 * - 上次失败：上报失败（N 秒前）：错误摘要
 */
object ReportStatusText {

    // 服务未运行时的文案喵
    const val SERVICE_STOPPED = "服务未运行，未在上报"

    // 从未上报时的文案喵
    const val NEVER = "从未上报"

    // 错误摘要最大长度，太长会把状态行撑到换行喵
    const val MAX_ERROR_LENGTH = 60

    // 一分钟的毫秒数，用于选择"秒/分钟"口径喵
    private const val MINUTE_MILLIS = 60_000L

    // 一小时的毫秒数，用于选择"分钟/小时"口径喵
    private const val HOUR_MILLIS = 3_600_000L

    /**
     * 渲染上报状态文案。
     *
     * 输入：上报状态、服务是否在跑、当前时刻。
     * 输出：四种取值之一的中文文案。
     * 边界：服务没跑时优先说没跑，避免用户以为还在发；时刻缺失时省略"多久之前"喵。
     */
    fun describe(status: ReportStatus, serviceRunning: Boolean, nowMillis: Long): String {
        // 喵~注意：服务没跑时优先显示"未在上报"，这比上次结果更重要喵
        if (!serviceRunning) return SERVICE_STOPPED
        // 按最近一次结果分别拼文案喵
        return when (status.outcome) {
            // 从未上报：只说这四个字，不编造时间喵
            ReportOutcome.NEVER -> NEVER
            // 成功：带上"多久之前"喵
            ReportOutcome.SUCCESS -> {
                // 先算时间描述，时刻缺失时为 null 喵
                val age = ageText(status.atMillis, nowMillis)
                // 没有时刻就只写结果喵
                if (age == null) "上报成功" else "上报成功（$age）"
            }
            // 失败：带上"多久之前"和错误摘要喵
            ReportOutcome.FAILURE -> {
                // 先算时间描述喵
                val age = ageText(status.atMillis, nowMillis)
                // 没有时刻时只写结果喵
                val prefix = if (age == null) "上报失败" else "上报失败（$age）"
                // 喵~防御：摘要为空时不要留下孤零零的冒号喵
                val summary = status.errorSummary?.takeIf { it.isNotBlank() }
                if (summary == null) prefix else "$prefix：$summary"
            }
        }
    }

    /**
     * 把时刻差渲染成「N 秒前 / N 分钟前 / N 小时前」。
     *
     * 输入：事件时刻（可为空）、当前时刻。
     * 输出：时间描述；时刻为空时返回 null。
     * 边界：时钟回拨时按 0 处理，不显示负数喵。
     */
    fun ageText(atMillis: Long?, nowMillis: Long): String? {
        // 喵~防御：没有时刻就无法算"多久之前"喵
        if (atMillis == null) return null
        // 喵~防御：时钟回拨会算出负数，按 0 处理喵
        val elapsed = (nowMillis - atMillis).coerceAtLeast(0L)
        // 按跨度选择单位喵
        return when {
            // 一分钟内按秒说，用户能看出"刚刚还在发"喵
            elapsed < MINUTE_MILLIS -> "${elapsed / 1000L} 秒前"
            // 一小时内按分钟说喵
            elapsed < HOUR_MILLIS -> "${elapsed / MINUTE_MILLIS} 分钟前"
            // 更久按小时说喵
            else -> "${elapsed / HOUR_MILLIS} 小时前"
        }
    }

    /**
     * 把失败原因压成一行短摘要。
     *
     * 输入：上报客户端返回的原始错误文本，可能带换行或很长。
     * 输出：适合放在状态行里的短文本，最多 [MAX_ERROR_LENGTH] 个字符。
     * 边界：空文本返回「未知错误」，不会让界面出现"上报失败："这种残缺文案喵。
     */
    fun summarizeError(raw: String?): String {
        // 喵~防御：没有原因时给兜底文案喵
        if (raw.isNullOrBlank()) return "未知错误"
        // 只取第一条非空行，堆栈与多行响应会把界面撑坏喵
        val firstLine = raw.lineSequence().firstOrNull { it.isNotBlank() } ?: return "未知错误"
        // 压掉多余空白，日志里的制表符与连续空格不该带到界面上喵
        val flattened = firstLine.trim().replace(Regex("\\s+"), " ")
        // 喵~防御：超长错误截断，避免把状态行挤成两行喵
        return if (flattened.length > MAX_ERROR_LENGTH) {
            flattened.take(MAX_ERROR_LENGTH) + "…"
        } else {
            flattened
        }
    }
}
