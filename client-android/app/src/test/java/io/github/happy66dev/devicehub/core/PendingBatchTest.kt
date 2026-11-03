package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 待重发批次的编解码测试。
 *
 * 重点保护的是「重试时上报时刻不能变」这条不变式：
 * 服务端用 (deviceId, reportedAt) 做幂等键，时刻一变，同一段秒数就会被加两遍喵。
 */
class PendingBatchTest {

    /** 造一条增量条目喵。 */
    private fun delta(appName: String, seconds: Long, packageName: String? = null): UsageDelta {
        // 包名默认为空喵
        return UsageDelta(appName = appName, packageName = packageName, seconds = seconds)
    }

    /** 编码再解码之后，秒数与固定时刻都要原样回来喵。 */
    @Test
    fun encodeDecodeKeepsReportedAtAndSeconds() {
        // 造一个带两个应用的批次喵
        val batch = PendingBatch(
            reportedAt = "2026-11-03T05:00:00Z",
            items = listOf(delta("Code.exe", 30L), delta("QQ.exe", 12L)),
        )
        // 往返一次喵
        val restored = PendingBatch.decode(PendingBatch.encode(batch))
        // 喵~注意：时刻必须一模一样，否则幂等就失效了喵
        assertNotNull(restored)
        assertEquals("2026-11-03T05:00:00Z", restored!!.reportedAt)
        // 秒数也要原样喵
        assertEquals(mapOf("Code.exe" to 30L, "QQ.exe" to 12L), restored.secondsByApp())
        assertEquals(42L, restored.totalSeconds)
    }

    /** 老格式（只有秒数、没有版本行）要被判为不可用，不能拿去重发喵。 */
    @Test
    fun decodeRejectsLegacyFormatWithoutTimestamp() {
        // 老格式就是纯增量行，没有版本行喵
        val legacy = UsageStateCodec.encode(listOf(delta("Code.exe", 30L)))
        // 喵~注意：没有时刻就无法保证幂等，宁可返回 null 也不要冒险重发喵
        assertNull(PendingBatch.decode(legacy))
    }

    /** 空文本与空批次都要返回 null，调用方据此知道没有东西要重发喵。 */
    @Test
    fun decodeRejectsBlankAndEmpty() {
        // 空文本喵
        assertNull(PendingBatch.decode(""))
        // 全空白喵
        assertNull(PendingBatch.decode("   \n  "))
        // 只有版本行、没有数据喵
        assertNull(PendingBatch.decode("v2\t2026-11-03T05:00:00Z\n"))
    }

    /** 空批次编码出来是空字符串，表示没有欠账喵。 */
    @Test
    fun encodeEmptyBatchYieldsBlank() {
        // 没有任何条目喵
        val batch = PendingBatch(reportedAt = "2026-11-03T05:00:00Z", items = emptyList())
        // 空批次不必写盘喵
        assertEquals("", PendingBatch.encode(batch))
        // 自己也要认得出自己是空的喵
        assertTrue(batch.isEmpty)
        assertEquals(0L, batch.totalSeconds)
    }

    /** 版本行缺少时刻时视为坏数据，不能重发喵。 */
    @Test
    fun decodeRejectsMissingTimestamp() {
        // 版本行只有 "v2" 和一个制表符，时刻是空的喵
        val broken = "v2\t\n" + UsageStateCodec.encode(listOf(delta("Code.exe", 30L)))
        // 喵~防御：没有时刻就放弃喵
        assertNull(PendingBatch.decode(broken))
    }
}
