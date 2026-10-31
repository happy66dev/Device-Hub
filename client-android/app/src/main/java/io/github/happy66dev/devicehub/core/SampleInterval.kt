package io.github.happy66dev.devicehub.core

/**
 * 采集频率（采样间隔）的取值规则，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 口径：1 到 60 之间的任意整数秒，默认 5 秒一次喵。
 */
object SampleInterval {

    // 默认采集频率：5 秒一次喵
    const val DEFAULT_SECONDS = 5

    // 允许的最小采集频率喵
    const val MIN_SECONDS = 1

    // 允许的最大采集频率喵
    const val MAX_SECONDS = 60

    /**
     * 把任意整数夹到合法区间。
     *
     * 输入：用户填写的秒数。
     * 输出：1 到 60 之间的值。
     * 边界：超出范围时夹到边界，不抛异常，界面用 [describe] 提示实际生效值喵。
     */
    fun normalize(seconds: Int): Int {
        // 直接夹到合法区间喵
        return seconds.coerceIn(MIN_SECONDS, MAX_SECONDS)
    }

    /**
     * 解析用户输入的文本。
     *
     * 输入：输入框里的文本，可能是空串、带空白的数字、乱码。
     * 输出：合法区间内的秒数；文本不是整数时返回 null。
     * 边界：超出范围时会夹到边界，而不是返回 null，避免用户白填喵。
     */
    fun parse(text: String?): Int? {
        // 喵~防御：空文本说明用户没填，交给调用方用默认值喵
        if (text.isNullOrBlank()) return null
        // 喵~防御：只接受纯整数文本，小数与符号一律当非法喵
        val seconds = text.trim().toIntOrNull() ?: return null
        // 夹到合法区间喵
        return normalize(seconds)
    }

    /**
     * 生成给用户看的说明文案。
     *
     * 输入：生效的秒数。
     * 输出：例如「每 5 秒采集一次」。
     */
    fun describe(seconds: Int): String {
        // 统一走夹取后的值，避免文案与实际不符喵
        return "每 ${normalize(seconds)} 秒采集一次"
    }
}
