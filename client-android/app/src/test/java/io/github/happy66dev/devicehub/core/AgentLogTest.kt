package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 运行日志环形缓冲的单元测试：追加、截断、清空喵。
 */
class AgentLogTest {

    /** 追加的日志应能按顺序读出来喵。 */
    @Test
    fun `keeps lines in order`() {
        // 清空避免受其它测试影响喵
        AgentLog.clear()
        // 追加两条喵
        AgentLog.info("第一条")
        AgentLog.warn("第二条")
        // 读出内容喵
        val lines = AgentLog.snapshot()
        // 顺序应保持插入顺序喵
        assertEquals(2, lines.size)
        assertTrue(lines[0].contains("第一条"))
        assertTrue(lines[1].contains("第二条"))
        // 级别字母要写进行首喵
        assertTrue(lines[1].contains(" W "))
    }

    /** 超过上限时应丢掉最旧的日志喵。 */
    @Test
    fun `drops oldest lines beyond limit`() {
        // 清空后塞满超过上限的行喵
        AgentLog.clear()
        repeat(AgentLog.MAX_LINES + 10) { index ->
            AgentLog.info("第 $index 行")
        }
        // 行数应被限制喵
        assertEquals(AgentLog.MAX_LINES, AgentLog.size())
        // 最旧的几行应已被丢弃喵
        val lines = AgentLog.snapshot()
        assertTrue(lines.first().contains("第 10 行"))
        assertTrue(lines.last().contains("第 ${AgentLog.MAX_LINES + 9} 行"))
    }

    /** 空消息与超长消息都要安全处理喵。 */
    @Test
    fun `ignores blank and truncates long messages`() {
        // 清空后写空消息喵
        AgentLog.clear()
        AgentLog.info("   ")
        assertEquals(0, AgentLog.size())
        // 写一条超长消息喵
        AgentLog.error("x".repeat(500))
        val line = AgentLog.snapshot().single()
        // 正文应被截断，避免撑坏界面喵
        assertTrue(line.endsWith("…"))
        assertTrue(line.length < 320)
    }

    /** 清空后应一行不剩喵。 */
    @Test
    fun `clear removes everything`() {
        // 先写一条再清空喵
        AgentLog.info("待清空")
        AgentLog.clear()
        assertEquals(0, AgentLog.size())
        assertTrue(AgentLog.snapshot().isEmpty())
    }
}
