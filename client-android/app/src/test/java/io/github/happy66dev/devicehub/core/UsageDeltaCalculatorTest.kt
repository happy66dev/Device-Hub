package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 使用时长累加器的单元测试喵。 */
class UsageDeltaCalculatorTest {

    @Test
    fun `同一应用多次累加会合并`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 累加两次喵
        calculator.addSeconds("微信", 5)
        calculator.addSeconds("微信", 5)
        // 应合并成 10 秒喵
        assertEquals(10L, calculator.drain().single { it.appName == "微信" }.seconds)
    }

    @Test
    fun `drain 之后内部状态被清空`() {
        // 创建累加器并写入喵
        val calculator = UsageDeltaCalculator()
        calculator.addSeconds("微信", 5)
        // 第一次取出应有数据喵
        assertEquals(1, calculator.drain().size)
        // 第二次取出应为空喵
        assertTrue(calculator.drain().isEmpty())
        // 总秒数应为 0 喵
        assertEquals(0L, calculator.totalSeconds())
    }

    @Test
    fun `restore 可以把失败的数据还回去`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 模拟上报失败后归还喵
        calculator.restore(
            listOf(
                UsageDelta("微信", "com.tencent.mm", 30),
                UsageDelta("哔哩哔哩", "tv.danmaku.bili", 20),
            )
        )
        // 总秒数应为 50 喵
        assertEquals(50L, calculator.totalSeconds())
        // 包名也应一起还回来喵
        assertEquals("com.tencent.mm", calculator.snapshot().single { it.appName == "微信" }.packageName)
    }

    @Test
    fun `非正秒数与空应用名会被忽略`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 写入各种非法输入喵
        calculator.addSeconds("微信", 0)
        calculator.addSeconds("微信", -5)
        calculator.addSeconds("   ", 10)
        // 应一条都没留下喵
        assertTrue(calculator.drain().isEmpty())
    }

    @Test
    fun `单应用累计超过一天时被截断`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 写入两天量喵
        calculator.addSeconds("微信", 100_000)
        // 应截断到 86400 喵
        assertEquals(UsageDeltaCalculator.MAX_SECONDS_PER_APP, calculator.drain().single().seconds)
    }

    @Test
    fun `转列表时按秒数倒序并限制条数`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 写入 3 条乱序数据喵
        calculator.addSeconds("A", 10)
        calculator.addSeconds("B", 30)
        calculator.addSeconds("C", 20)
        // 取出列表喵
        val deltaList = calculator.toDeltaList()
        // 第一条应是秒数最多的 B 喵
        assertEquals("B", deltaList[0].appName)
        // 顺序应为 B C A 喵
        assertEquals(listOf("B", "C", "A"), deltaList.map { it.appName })
    }

    @Test
    fun `包名会被记住且不会被空值覆盖`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 第一次带上包名喵
        calculator.addSeconds("微信", 10, "com.tencent.mm")
        // 第二次没带包名喵
        calculator.addSeconds("微信", 5)
        // 包名应保留，秒数应累加喵
        val entry = calculator.drain().single()
        assertEquals("com.tencent.mm", entry.packageName)
        assertEquals(15L, entry.seconds)
    }

    @Test
    fun `包名过长会被截断`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 写入超长包名喵
        calculator.addSeconds("应用", 5, "a".repeat(500))
        // 应截断到上限喵
        assertEquals(UsageDeltaCalculator.MAX_PACKAGE_LENGTH, calculator.drain().single().packageName?.length)
    }

    @Test
    fun `没有包名时条目包名为空`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 只写应用名喵
        calculator.addSeconds("应用", 5)
        // 包名应为 null 喵
        assertNull(calculator.drain().single().packageName)
    }

    @Test
    fun `computeDelta 忽略回退的读数`() {
        // 上一次读数喵
        val previous = mapOf("微信" to 100L, "哔哩哔哩" to 50L)
        // 本次读数：微信增加，哔哩哔哩被清零（跨天）喵
        val current = mapOf("微信" to 160L, "哔哩哔哩" to 10L, "新应用" to 5L)
        // 计算增量喵
        val delta = UsageDeltaCalculator.computeDelta(previous, current)
        // 微信应增加 60 秒喵
        assertEquals(60L, delta["微信"])
        // 喵~防御：回退的读数不应产生负值喵
        assertTrue(delta["哔哩哔哩"] == null)
        // 新应用应全额计入喵
        assertEquals(5L, delta["新应用"])
    }

    @Test
    fun `restore 之后总秒数与快照都包含补报数据`() {
        // 创建累加器并写入一批数据喵
        val calculator = UsageDeltaCalculator()
        calculator.addSeconds("微信", 30, "com.tencent.mm")
        // 模拟上报失败：先 drain 再 restore 喵
        val drained = calculator.drain()
        calculator.restore(drained)
        // 总秒数应把补报数据算进去喵
        assertEquals(30L, calculator.totalSeconds())
        // 快照里也应能看到补报条目与包名喵
        val snapshot = calculator.snapshot()
        assertEquals(1, snapshot.size)
        assertEquals("微信", snapshot.single().appName)
        assertEquals("com.tencent.mm", snapshot.single().packageName)
        assertEquals(30L, snapshot.single().seconds)
    }

    @Test
    fun `同一应用二次 restore 会累加而不是覆盖`() {
        // 创建累加器喵
        val calculator = UsageDeltaCalculator()
        // 同一批失败数据还回去两次喵
        val batch = listOf(UsageDelta("微信", "com.tencent.mm", 30))
        calculator.restore(batch)
        calculator.restore(batch)
        // 应累加成 60 秒，而不是停在 30 秒喵
        assertEquals(60L, calculator.totalSeconds())
        assertEquals(60L, calculator.snapshot().single().seconds)
    }
}
