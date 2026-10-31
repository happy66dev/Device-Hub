package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 上报状态模型与界面文案的单元测试喵。 */
class ReportStatusTest {

    // 测试用的"当前时刻"喵
    private val nowMillis = 1_000_000L

    @Test
    fun `从未上报时显示从未上报`() {
        // 服务在跑但还没发过任何上报喵
        val status = ServiceStatus(running = true, report = ReportStatus.never())
        // 文案就是四个字，不编造时间喵
        assertEquals("从未上报", status.reportText(nowMillis))
    }

    @Test
    fun `上报成功时显示多少秒之前`() {
        // 30 秒前成功过一次喵
        val status = ServiceStatus(running = true, report = ReportStatus.success(nowMillis - 30_000L))
        // 界面文案带上秒数喵
        assertEquals("上报成功（30 秒前）", status.reportText(nowMillis))
    }

    @Test
    fun `上报失败时带错误摘要`() {
        // 5 秒前失败，错误来自上报客户端喵
        val status = ServiceStatus(running = true, report = ReportStatus.failure(nowMillis - 5_000L, "HTTP 500 boom"))
        // 文案里既有时间也有原因喵
        assertEquals("上报失败（5 秒前）：HTTP 500 boom", status.reportText(nowMillis))
    }

    @Test
    fun `服务未运行时优先显示未运行`() {
        // 即使上次成功过，服务没跑也要先说没跑喵
        val status = ServiceStatus(running = false, report = ReportStatus.success(nowMillis - 10_000L))
        // 第四种取值喵
        assertEquals("服务未运行，未在上报", status.reportText(nowMillis))
    }

    @Test
    fun `成功状态超过一分钟按分钟显示`() {
        // 125 秒前成功，按分钟口径说 2 分钟喵
        val status = ServiceStatus(running = true, report = ReportStatus.success(0L))
        assertEquals("上报成功（2 分钟前）", status.reportText(125_000L))
    }

    @Test
    fun `成功状态超过一小时按小时显示`() {
        // 两小时前成功喵
        val status = ServiceStatus(running = true, report = ReportStatus.success(0L))
        assertEquals("上报成功（2 小时前）", status.reportText(2 * 3_600_000L))
    }

    @Test
    fun `时钟回拨时不显示负数`() {
        // 喵~防御：上报时刻比当前时刻还晚，按 0 秒处理喵
        val status = ServiceStatus(running = true, report = ReportStatus.success(nowMillis + 5_000L))
        assertEquals("上报成功（0 秒前）", status.reportText(nowMillis))
    }

    @Test
    fun `错误摘要只取第一行并压掉空白`() {
        // 多行错误只保留第一行，连续空白压成一个空格喵
        val status = ServiceStatus(running = true, report = ReportStatus.failure(nowMillis, "  HTTP 500\n  服务端异常  "))
        assertEquals("上报失败（0 秒前）：HTTP 500", status.reportText(nowMillis))
    }

    @Test
    fun `超长错误摘要会被截断`() {
        // 一百个字符的错误只保留前 60 个再加省略号喵
        val status = ServiceStatus(running = true, report = ReportStatus.failure(nowMillis, "错".repeat(100)))
        // 取渲染后的摘要部分喵
        val summary = status.report.errorSummary ?: ""
        // 长度是 60 个字符加一个省略号喵
        assertTrue(summary.length == ReportStatusText.MAX_ERROR_LENGTH + 1)
        // 结尾必须是省略号，界面才知道被截断了喵
        assertTrue(summary.endsWith("…"))
    }

    @Test
    fun `失败但没有原因时给兜底文案`() {
        // 空白错误文本也要有可读原因喵
        val status = ServiceStatus(running = true, report = ReportStatus.failure(nowMillis, "   "))
        assertEquals("上报失败（0 秒前）：未知错误", status.reportText(nowMillis))
    }

    @Test
    fun `状态标记能区分三种结果`() {
        // 从未上报喵
        val never = ReportStatus.never()
        assertTrue(never.isNever)
        assertFalse(never.isSuccess)
        assertFalse(never.isFailure)
        // 成功喵
        val success = ReportStatus.success(nowMillis)
        assertTrue(success.isSuccess)
        // 成功状态不能残留错误摘要喵
        assertNull(success.errorSummary)
        // 失败喵
        val failure = ReportStatus.failure(nowMillis, "boom")
        assertTrue(failure.isFailure)
    }
}
