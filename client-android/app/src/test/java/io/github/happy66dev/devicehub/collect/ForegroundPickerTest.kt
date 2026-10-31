package io.github.happy66dev.devicehub.collect

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

/** 前台应用判定纯函数的单元测试喵。 */
class ForegroundPickerTest {

    // 测试用的本应用包名喵
    private val ownPackage = "io.github.happy66dev.devicehub"

    // 测试用的取名字函数喵
    private val labelOf: (String) -> String = { packageName -> "名称:$packageName" }

    @Test
    fun `窗口内没有新事件时沿用上一次结果`() {
        // 上一轮记的是微信喵
        val previous = ForegroundApp("微信", "com.tencent.mm", "2026-10-31T10:00:00Z")
        // 窗口内没有切前台事件喵
        val picked = pickForeground(previous, null, 0L, ownPackage, labelOf)
        // 必须沿用上一次，否则用户一直待在一个应用里就采不到喵
        assertSame(previous, picked)
    }

    @Test
    fun `空白包名也按没有事件处理`() {
        // 上一轮记的是哔哩哔哩喵
        val previous = ForegroundApp("哔哩哔哩", "tv.danmaku.bili", "2026-10-31T10:00:00Z")
        // 包名是空串喵
        assertSame(previous, pickForeground(previous, "", 0L, ownPackage, labelOf))
        // 包名是空白喵
        assertSame(previous, pickForeground(previous, "   ", 0L, ownPackage, labelOf))
    }

    @Test
    fun `出现新应用时更新为新的前台应用`() {
        // 上一轮是微信喵
        val previous = ForegroundApp("微信", "com.tencent.mm", "2026-10-31T10:00:00Z")
        // 这次切到了浏览器喵
        val picked = pickForeground(previous, "com.android.chrome", 1_760_000_000_000L, ownPackage, labelOf)
        // 包名与名字都要更新喵
        assertEquals("com.android.chrome", picked?.packageName)
        assertEquals("名称:com.android.chrome", picked?.name)
        // since 要取事件发生的时刻喵
        assertEquals("2025-10-09T08:53:20Z", picked?.sinceIso)
    }

    @Test
    fun `本应用自己在前台时也照常上报`() {
        // 上一轮是微信喵
        val previous = ForegroundApp("微信", "com.tencent.mm", "2026-10-31T10:00:00Z")
        // 这次前台是本应用自己喵
        val picked = pickForeground(previous, ownPackage, 1_760_000_000_000L, ownPackage, labelOf)
        // 主人要求把 DeviceHub 也当成一个安卓软件上报，不能返回 null 喵
        assertEquals(ownPackage, picked?.packageName)
        assertEquals("名称:$ownPackage", picked?.name)
    }

    @Test
    fun `没有上一轮结果时也能判定`() {
        // 冷启动第一轮就有事件喵
        val picked = pickForeground(null, "com.tencent.mm", 1_760_000_000_000L, ownPackage, labelOf)
        // 应直接给出这次的应用喵
        assertEquals("com.tencent.mm", picked?.packageName)
    }
}
