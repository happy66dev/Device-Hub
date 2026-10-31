package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Test

/** 待补报文案的单元测试喵。 */
class ReportBacklogTest {

    @Test
    fun `0 秒返回空串`() {
        // 没有积压时界面不显示这一行喵
        assertEquals("", ReportBacklog.pendingText(0L))
    }

    @Test
    fun `负数按 0 处理返回空串`() {
        // 喵~防御：时钟回拨或脏数据不能显示负数喵
        assertEquals("", ReportBacklog.pendingText(-30L))
    }

    @Test
    fun `59 秒只显示秒`() {
        // 不足一分钟时只写秒喵
        assertEquals("待补报 59 秒", ReportBacklog.pendingText(59L))
    }

    @Test
    fun `1 分 5 秒同时显示分与秒`() {
        // 一分零五秒要拆成两段喵
        assertEquals("待补报 1 分 5 秒", ReportBacklog.pendingText(65L))
    }

    @Test
    fun `1 小时 2 分同时显示小时与分`() {
        // 一小时零二分要拆成两段，且不出现 0 秒喵
        assertEquals("待补报 1 小时 2 分", ReportBacklog.pendingText(3_720L))
    }

    @Test
    fun `整分钟不显示多余的 0 秒`() {
        // 整分钟只显示分钟，读起来更干净喵
        assertEquals("待补报 1 分", ReportBacklog.pendingText(60L))
    }

    @Test
    fun `整小时不显示多余的 0 分`() {
        // 整小时只显示小时喵
        assertEquals("待补报 1 小时", ReportBacklog.pendingText(3_600L))
    }

    @Test
    fun `时分秒都有的情况按顺序拼完整`() {
        // 一小时一分一秒要把三个单位都写出来喵
        assertEquals("待补报 1 小时 1 分 1 秒", ReportBacklog.pendingText(3_661L))
    }
}
