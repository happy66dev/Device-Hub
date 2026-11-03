package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 单轮采样补记上限的单元测试喵。 */
class SampleGapCapTest {

    @Test
    fun `上限始终覆盖一个完整采集周期`() {
        // 喵~注意：这是真实缺陷的防线——上限以前按默认 5 秒算死 15 秒，
        // 而 SampleInterval 允许配到 60 秒，那时每轮真实过去 60 秒只记 15 秒，
        // 会稳定丢掉 75% 的使用时长，且日志里毫无痕迹喵
        for (seconds in listOf(1, 5, 10, 15, 20, 30, 45, 60)) {
            // 该间隔对应的毫秒数喵
            val intervalMillis = seconds * 1000L
            // 上限必须不小于一个完整周期，否则每轮都会截断喵
            val cap = SampleGapCap.capMillis(intervalMillis)
            assertTrue(
                "采集间隔 ${seconds}s 时上限只有 ${cap}ms，会丢数据",
                cap >= intervalMillis,
            )
            // 真跑一轮：正好过去一个周期，必须原样记满喵
            assertEquals(
                intervalMillis,
                SampleGapCap.clampElapsed(intervalMillis, cap, recovering = false),
            )
        }
    }

    @Test
    fun `默认间隔保持原来的十五秒下限`() {
        // 默认 5 秒间隔时，上限仍是 15 秒，行为和改之前一致喵
        val defaultIntervalMillis = SampleInterval.DEFAULT_SECONDS * 1000L
        assertEquals(15_000L, SampleGapCap.capMillis(defaultIntervalMillis))
        // 兜底常量本身也必须是 15 秒喵
        assertEquals(15_000L, SampleGapCap.MIN_CAP_MILLIS)
    }

    @Test
    fun `进程被冻结几小时时不会凭空记成使用时长`() {
        // 喵~防御：这是这个上限存在的根本理由喵
        // 冻结三小时（10800 秒）后，只能记到一个上限，不能真记三小时喵
        val threeHoursMillis = 3 * 60 * 60 * 1000L
        // 默认间隔下只记 15 秒喵
        assertEquals(
            15_000L,
            SampleGapCap.clampElapsed(threeHoursMillis, SampleGapCap.capMillis(5_000L), recovering = false),
        )
        // 60 秒间隔下记 180 秒，仍然远小于三小时喵
        assertEquals(
            180_000L,
            SampleGapCap.clampElapsed(threeHoursMillis, SampleGapCap.capMillis(60_000L), recovering = false),
        )
    }

    @Test
    fun `补偿态允许补得比普通轮次更久`() {
        // 上一轮没拿到前台应用时，放宽到至少 60 秒，否则那几十秒直接消失喵
        assertEquals(
            60_000L,
            SampleGapCap.clampElapsed(120_000L, SampleGapCap.capMillis(5_000L), recovering = true),
        )
    }

    @Test
    fun `脏间隔与零长度不会算出负数或零`() {
        // 喵~防御：间隔是 0 或负数时退回兜底下限喵
        assertEquals(SampleGapCap.MIN_CAP_MILLIS, SampleGapCap.capMillis(0L))
        assertEquals(SampleGapCap.MIN_CAP_MILLIS, SampleGapCap.capMillis(-5_000L))
        // 喵~防御：本轮真实经过为 0 时也要记 1 毫秒，避免 0 长度区间喵
        assertEquals(1L, SampleGapCap.clampElapsed(0L, 15_000L, recovering = false))
    }
}
