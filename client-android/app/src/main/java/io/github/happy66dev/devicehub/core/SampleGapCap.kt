package io.github.happy66dev.devicehub.core

/**
 * 单轮采样「最多能补记多久」的规则，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 为什么单独抽出来：这个上限以前是拿默认采集间隔算死的常量
 * （`3 * SampleInterval.DEFAULT_SECONDS * 1000` = 15 秒），
 * 而 `SampleInterval` 允许把采集间隔调到 60 秒。
 * 一旦主人真把间隔调大，每轮真实过去 60 秒却只记 15 秒，
 * **会稳定丢掉 75% 的使用时长**，而且日志里一点异常都没有，
 * 事后完全分不清是「少记了」还是「本来就没在用」。
 *
 * 现在上限改为跟随实际配置的采集间隔，同时保留一个下限，
 * 既保证正常一轮能完整记上，又能在进程被系统冻结几小时后挡住凭空补记喵。
 */
object SampleGapCap {

    // 单轮补记的兜底下限（毫秒）：默认 5 秒间隔时取 15 秒，和原来的行为一致喵
    const val MIN_CAP_MILLIS = 3 * SampleInterval.DEFAULT_SECONDS * 1000L

    // 上限相对采集间隔的倍数：3 个周期，偶发慢两轮也补得回来喵
    private const val INTERVAL_MULTIPLIER = 3L

    /**
     * 按实际采集间隔算单轮补记上限。
     *
     * 输入：当前配置的采集间隔（毫秒）。
     * 输出：单轮最多计入的毫秒数，不小于 [MIN_CAP_MILLIS]。
     * 边界：间隔非正时退回兜底下限喵。
     */
    fun capMillis(intervalMillis: Long): Long {
        // 喵~防御：脏配置可能给出 0 或负数，退回兜底值喵
        if (intervalMillis <= 0L) return MIN_CAP_MILLIS
        // 至少保留兜底下限，间隔大时按倍数放宽喵
        return maxOf(MIN_CAP_MILLIS, intervalMillis * INTERVAL_MULTIPLIER)
    }

    /**
     * 算这一轮实际该计入的毫秒数。
     *
     * 输入：本轮真实经过的毫秒、上限毫秒、是否处于「上一轮没拿到前台」的补偿态。
     * 输出：夹到 [1, 上限] 之间的毫秒数。
     * 边界：上限非正时退回兜底下限；补偿态放宽到至少 60 秒喵。
     */
    fun clampElapsed(elapsedMillis: Long, capMillis: Long, recovering: Boolean): Long {
        // 喵~防御：上限不合法就退回兜底值喵
        val safeCap = if (capMillis <= 0L) MIN_CAP_MILLIS else capMillis
        // 补偿态允许补得更久，否则那几十秒会直接消失喵
        val effectiveCap = if (recovering) maxOf(safeCap, RECOVER_CAP_MILLIS) else safeCap
        // 至少记 1 毫秒，避免 0 长度区间喵
        return elapsedMillis.coerceIn(1L, effectiveCap)
    }

    // 补偿态专用下限（毫秒）喵
    private const val RECOVER_CAP_MILLIS = 60_000L
}
