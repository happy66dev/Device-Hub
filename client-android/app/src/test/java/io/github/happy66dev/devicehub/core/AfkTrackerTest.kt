package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * AFK 判定器的单元测试喵。
 *
 * 喵~注意：口径是「息屏即 AFK」——短息屏也要报，否则时间轴上会留一条
 * 既不是离线也不是空档的空白。主人要求「离线必须绝对真实，空档可以不那么精确」喵。
 */
class AfkTrackerTest {

    @Test
    fun `亮屏时永远不算 AFK`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 连续亮屏采样都应为 false 喵
        assertFalse(tracker.update(screenOn = true, nowMillis = 0L))
        assertFalse(tracker.update(screenOn = true, nowMillis = 600_000L))
    }

    @Test
    fun `息屏第一帧就算 AFK`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 喵~注意：不再等 60 秒阈值，第一次看到息屏就返回 true 喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 1_000L))
    }

    @Test
    fun `短息屏也要算 AFK`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 息屏 5 秒就亮回来，这一段也要报 AFK，否则时间轴留白喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 0L))
        assertTrue(tracker.update(screenOn = false, nowMillis = 5_000L))
        // 亮屏后立刻退出 AFK 喵
        assertFalse(tracker.update(screenOn = true, nowMillis = 6_000L))
    }

    @Test
    fun `持续息屏一直是 AFK`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 长时间息屏每帧都应为 true 喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 0L))
        assertTrue(tracker.update(screenOn = false, nowMillis = 60_000L))
        assertTrue(tracker.update(screenOn = false, nowMillis = 120_000L))
    }

    @Test
    fun `中途亮屏后再次息屏重新记起点`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 第一次息屏起点是 0 喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 0L))
        assertEquals(0L, tracker.afkSinceMillis())
        // 亮屏清掉边界喵
        assertFalse(tracker.update(screenOn = true, nowMillis = 50_000L))
        assertEquals(null, tracker.afkSinceMillis())
        // 喵~注意：再次息屏要用新起点，不能沿用上一次的 0 秒喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 52_000L))
        assertEquals(52_000L, tracker.afkSinceMillis())
    }

    @Test
    fun `reset 之后回到未判定状态`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 先进入 AFK 喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 0L))
        // 重置后边界消失喵
        tracker.reset()
        assertEquals(null, tracker.afkSinceMillis())
        // 喵~注意：重置后仍是息屏的话，下一帧依旧算 AFK，只是起点换成新时刻喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 61_000L))
        assertEquals(61_000L, tracker.afkSinceMillis())
    }

    @Test
    fun `AFK 起点等于息屏那一刻`() {
        // 新建判定器喵
        val tracker = AfkTracker()
        // 亮屏时没有边界喵
        assertEquals(null, tracker.afkSinceMillis())
        // 第 5 秒看到息屏，起点就是 5 秒喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 5_000L))
        assertEquals(5_000L, tracker.afkSinceMillis())
        // 持续息屏时边界不随采样时刻漂移喵
        assertTrue(tracker.update(screenOn = false, nowMillis = 70_000L))
        assertEquals(5_000L, tracker.afkSinceMillis())
        // 亮屏后边界消失喵
        assertFalse(tracker.update(screenOn = true, nowMillis = 80_000L))
        assertEquals(null, tracker.afkSinceMillis())
    }
}
