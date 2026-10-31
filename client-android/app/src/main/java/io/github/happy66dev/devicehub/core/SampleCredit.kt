package io.github.happy66dev.devicehub.core

/**
 * 采样计时的「整秒 + 余数」拆分，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 为什么单独抽出来：采样间隔在真机上很难刚好是整秒（设 5 秒，实测一轮 4.8 秒），
 * 每轮都把毫秒直接截成整秒会系统性少记，实测每分钟少 2～6 秒（约 5%～10%）。
 * 这里把不足 1 秒的余数留给下一轮，长期平均下来一秒都不会丢喵。
 */
object SampleCredit {

    // 一秒的毫秒数，余数就在这里取模喵
    private const val MILLIS_PER_SECOND = 1_000L

    /**
     * 把「这一轮经过的毫秒 + 上一轮留下的余数」拆成整秒与新余数。
     *
     * 输入：elapsedMillis 本轮经过的毫秒（负数按 0），carryMillis 上一轮剩下的毫秒（负数按 0）。
     * 输出：Pair(本轮该记的整秒, 要留给下一轮的余数毫秒)，余数恒在 0..999。
     * 边界：两段都不到 1 秒时返回 (0, 合计毫秒)，调用方据此跳过 0 秒的脏条目喵。
     */
    fun split(elapsedMillis: Long, carryMillis: Long): Pair<Long, Long> {
        // 喵~防御：时钟回拨或脏数据可能给出负数，按 0 处理喵
        val elapsed = elapsedMillis.coerceAtLeast(0L)
        // 喵~防御：余数理论上不会为负，这里也兜一下喵
        val carry = carryMillis.coerceAtLeast(0L)
        // 两段毫秒先加在一起，避免余数被截断两次喵
        val totalMillis = elapsed + carry
        // 整秒部分就是这一轮真正要记的秒数喵
        val seconds = totalMillis / MILLIS_PER_SECOND
        // 剩下的毫秒留到下一轮，凑够 1 秒再记喵
        val nextCarry = totalMillis % MILLIS_PER_SECOND
        return seconds to nextCarry
    }
}
