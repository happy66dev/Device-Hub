package io.github.happy66dev.devicehub.core

/**
 * 待补报时长的界面文案，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 为什么单独抽出来：上报失败后这一批数据会被还回累加器，
 * 界面需要告诉用户「还有多少秒没发出去」，而不是只显示一句失败原因喵。
 */
object ReportBacklog {

    // 一小时的秒数，用于拆分时分秒喵
    private const val SECONDS_PER_HOUR = 3_600L

    // 一分钟的秒数，用于拆分时分秒喵
    private const val SECONDS_PER_MINUTE = 60L

    /**
     * 把待补报秒数渲染成界面文案。
     *
     * 输入：待补报的总秒数，可能为负数或 0。
     * 输出：例如「待补报 3 分 20 秒」；0 秒（含负数）时返回空字符串。
     * 边界：整分钟/整小时不补「0 秒」「0 分」，避免出现「1 小时 0 分 0 秒」这种啰嗦文案喵。
     */
    fun pendingText(seconds: Long): String {
        // 喵~防御：时钟回拨或脏数据可能传进负数，按 0 处理喵
        val safeSeconds = seconds.coerceAtLeast(0L)
        // 喵~防御：没有积压就不显示这一行，交给调用方决定要不要兜底文案喵
        if (safeSeconds == 0L) return ""
        // 拆出小时部分喵
        val hours = safeSeconds / SECONDS_PER_HOUR
        // 拆出分钟部分，去掉整小时之后再看喵
        val minutes = (safeSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE
        // 拆出秒部分喵
        val remainingSeconds = safeSeconds % SECONDS_PER_MINUTE
        // 按从大到小拼非零单位，读起来最自然喵
        val parts = buildList {
            // 有整小时才写小时喵
            if (hours > 0L) add("$hours 小时")
            // 有整分钟才写分钟喵
            if (minutes > 0L) add("$minutes 分")
            // 有零头秒才写秒喵
            if (remainingSeconds > 0L) add("$remainingSeconds 秒")
        }
        // 统一加上「待补报」前缀，界面直接整行显示喵
        return "待补报 " + parts.joinToString(" ")
    }
}
