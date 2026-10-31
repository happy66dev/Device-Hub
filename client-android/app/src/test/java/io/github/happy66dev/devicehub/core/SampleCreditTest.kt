package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 采样整秒与余数拆分的单元测试喵。 */
class SampleCreditTest {

    @Test
    fun `不到 1 秒只留余数不记秒`() {
        // 一轮只跑了 0.4 秒，这一轮不记，余数留到下一轮喵
        assertEquals(0L to 400L, SampleCredit.split(400L, 0L))
    }

    @Test
    fun `整秒留下不足 1 秒的零头`() {
        // 4.8 秒记 4 秒，800 毫秒留给下一轮喵
        assertEquals(4L to 800L, SampleCredit.split(4_800L, 0L))
    }

    @Test
    fun `上一轮的余数会和这一轮凑成整秒`() {
        // 800 + 4800 = 5600 毫秒，记 5 秒留 600 毫秒喵
        assertEquals(5L to 600L, SampleCredit.split(4_800L, 800L))
    }

    @Test
    fun `两段不足 1 秒合起来够 1 秒就记 1 秒`() {
        // 900 + 300 = 1200 毫秒，正好凑出 1 秒喵
        assertEquals(1L to 200L, SampleCredit.split(300L, 900L))
    }

    @Test
    fun `正好整秒不留余数`() {
        // 整 1 秒不该留下零头喵
        assertEquals(1L to 0L, SampleCredit.split(1_000L, 0L))
    }

    @Test
    fun `连续采样不会越记越少`() {
        // 真机上一轮 4.8 秒，跑 25 轮正好 120 秒，累计必须一分不差喵
        var carry = 0L
        var total = 0L
        repeat(25) {
            val (seconds, nextCarry) = SampleCredit.split(4_800L, carry)
            carry = nextCarry
            total += seconds
        }
        assertEquals(120L, total)
        // 25 轮 × 4.8 秒 = 120 秒整，余数应该正好是 0 喵
        assertEquals(0L, carry)
    }

    @Test
    fun `负数按 0 处理`() {
        // 喵~防御：时钟回拨或脏数据不能记出负数秒喵
        assertEquals(0L to 0L, SampleCredit.split(-5_000L, -200L))
    }

    @Test
    fun `余数永远小于 1 秒`() {
        // 余数只有可能落在 0..999，否则下一轮会被重复计算喵
        for (elapsed in listOf(1L, 999L, 1_001L, 4_800L, 15_000L)) {
            val (_, carry) = SampleCredit.split(elapsed, 700L)
            assertTrue("余数越界：$carry", carry in 0L..999L)
        }
    }
}
