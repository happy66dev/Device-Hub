package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** 采集频率规则的单元测试喵。 */
class SampleIntervalTest {

    @Test
    fun `默认值是五秒`() {
        // 默认 5 秒一次喵
        assertEquals(5, SampleInterval.DEFAULT_SECONDS)
        // 区间是 1 到 60 喵
        assertEquals(1, SampleInterval.MIN_SECONDS)
        assertEquals(60, SampleInterval.MAX_SECONDS)
    }

    @Test
    fun `区间内的整数原样保留`() {
        // 逐个试一遍常见值喵
        for (seconds in listOf(1, 2, 5, 30, 59, 60)) {
            assertEquals(seconds, SampleInterval.normalize(seconds))
        }
    }

    @Test
    fun `越界值被夹到边界`() {
        // 太小夹到 1，太大夹到 60 喵
        assertEquals(1, SampleInterval.normalize(0))
        assertEquals(1, SampleInterval.normalize(-7))
        assertEquals(60, SampleInterval.normalize(61))
        assertEquals(60, SampleInterval.normalize(999))
    }

    @Test
    fun `解析文本时去掉空白`() {
        // 带空格的数字也能用喵
        assertEquals(7, SampleInterval.parse(" 7 "))
        assertEquals(60, SampleInterval.parse("60"))
    }

    @Test
    fun `解析文本时越界同样夹取`() {
        // 90 会被夹成 60，用户不会白填喵
        assertEquals(60, SampleInterval.parse("90"))
        assertEquals(1, SampleInterval.parse("0"))
    }

    @Test
    fun `非整数文本返回空`() {
        // 空、乱码、小数都算没填喵
        assertNull(SampleInterval.parse(null))
        assertNull(SampleInterval.parse(""))
        assertNull(SampleInterval.parse("   "))
        assertNull(SampleInterval.parse("abc"))
        assertNull(SampleInterval.parse("5.5"))
    }

    @Test
    fun `说明文案与实际生效值一致`() {
        // 越界值也要按夹取后的值写文案喵
        assertEquals("每 5 秒采集一次", SampleInterval.describe(5))
        assertEquals("每 60 秒采集一次", SampleInterval.describe(120))
    }
}
