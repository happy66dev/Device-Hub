package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 上报频率规则与到期判定的单元测试喵。 */
class ReportIntervalTest {

    @Test
    fun `默认值与取值范围符合约束`() {
        // 默认保持旧版本的 60 秒喵
        assertEquals(60, ReportInterval.DEFAULT_SECONDS)
        // 区间是 10 到 60 秒喵
        assertEquals(10, ReportInterval.MIN_SECONDS)
        assertEquals(60, ReportInterval.MAX_SECONDS)
        // 喵~注意：上限乘 2 仍要小于服务端 180 秒心跳超时，否则连丢两轮就会被误判离线喵
        assertTrue(ReportInterval.MAX_SECONDS * 2 < ReportInterval.HEARTBEAT_TIMEOUT_SECONDS)
    }

    @Test
    fun `区间内的整数原样保留`() {
        // 逐个试一遍常见值喵
        for (seconds in listOf(10, 11, 30, 59, 60)) {
            assertEquals(seconds, ReportInterval.normalize(seconds))
        }
    }

    @Test
    fun `越界值被夹到边界`() {
        // 小于 10 一律夹到 10 喵
        assertEquals(10, ReportInterval.normalize(0))
        assertEquals(10, ReportInterval.normalize(9))
        assertEquals(10, ReportInterval.normalize(-30))
        // 大于 60 一律夹到 60 喵
        assertEquals(60, ReportInterval.normalize(61))
        assertEquals(60, ReportInterval.normalize(999))
    }

    @Test
    fun `解析文本时去掉空白并夹取`() {
        // 带空格也能用喵
        assertEquals(30, ReportInterval.parse(" 30 "))
        // 越界同样夹取，用户不会白填喵
        assertEquals(10, ReportInterval.parse("3"))
        assertEquals(60, ReportInterval.parse("90"))
        // 喵~注意：超出 Int 范围的超大数字也要夹到 60，不能因为溢出就当没填喵
        assertEquals(60, ReportInterval.parse("999999999999"))
    }

    @Test
    fun `非整数文本返回空`() {
        // 空、乱码、小数都算没填喵
        assertNull(ReportInterval.parse(null))
        assertNull(ReportInterval.parse(""))
        assertNull(ReportInterval.parse("   "))
        assertNull(ReportInterval.parse("abc"))
        assertNull(ReportInterval.parse("10.5"))
    }

    @Test
    fun `秒数换算成毫秒时同样夹取`() {
        // 正常值直接换算喵
        assertEquals(60_000L, ReportInterval.intervalMillis(60))
        // 非法值先夹到 10 秒再换算喵
        assertEquals(10_000L, ReportInterval.intervalMillis(1))
    }

    @Test
    fun `说明文案与实际生效值一致`() {
        // 越界值也要按夹取后的值写文案喵
        assertEquals("每 60 秒上报一次", ReportInterval.describe(60))
        assertEquals("每 10 秒上报一次", ReportInterval.describe(5))
    }

    @Test
    fun `没到间隔不上报`() {
        // 9 秒还没到 10 秒，不报喵
        assertFalse(ReportInterval.isDue(nowMillis = 9_000L, anchorMillis = 0L, intervalSeconds = 10))
        // 刚好 10 秒就报喵
        assertTrue(ReportInterval.isDue(nowMillis = 10_000L, anchorMillis = 0L, intervalSeconds = 10))
    }

    @Test
    fun `间隔改小后下一轮立刻生效`() {
        // 锚点在 0，已经过去 30 秒喵
        val nowMillis = 30_000L
        // 旧间隔 60 秒还没到点喵
        assertFalse(ReportInterval.isDue(nowMillis, 0L, 60))
        // 主人改成 10 秒后，下一轮（同一次判定）就该发喵
        assertTrue(ReportInterval.isDue(nowMillis, 0L, 10))
    }

    @Test
    fun `间隔改大后按新间隔等待`() {
        // 锚点在 0，已经过去 30 秒喵
        val nowMillis = 30_000L
        // 10 秒间隔早就该发喵
        assertTrue(ReportInterval.isDue(nowMillis, 0L, 10))
        // 改成 60 秒后要等到满 60 秒喵
        assertFalse(ReportInterval.isDue(nowMillis, 0L, 60))
        assertTrue(ReportInterval.isDue(60_000L, 0L, 60))
    }

    @Test
    fun `AFK 状态变化时无视间隔立刻上报`() {
        // 刚上报过 1 秒，正常要等 60 秒喵
        assertFalse(ReportInterval.isDue(nowMillis = 1_000L, anchorMillis = 0L, intervalSeconds = 60))
        // 但 AFK 边界一变就要立刻发，保证斜纹起点不迟到喵
        assertTrue(ReportInterval.isDue(nowMillis = 1_000L, anchorMillis = 0L, intervalSeconds = 60, afkChanged = true))
    }

    @Test
    fun `时钟回拨时按到期处理`() {
        // 喵~防御：now 比锚点还早说明时钟被改了，宁可多发一次也不要永远不上报喵
        assertTrue(ReportInterval.isDue(nowMillis = 0L, anchorMillis = 10_000L, intervalSeconds = 60))
    }
}
