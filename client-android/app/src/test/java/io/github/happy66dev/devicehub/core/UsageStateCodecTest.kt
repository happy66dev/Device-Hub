package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 待上报数据序列化的单元测试喵。 */
class UsageStateCodecTest {

    @Test
    fun `编码后解码应还原原始数据`() {
        // 原始数据喵
        val original = listOf(
            UsageDelta("微信", "com.tencent.mm", 45),
            UsageDelta("Code.exe", null, 120),
        )
        // 编码再解码喵
        val restored = UsageStateCodec.decode(UsageStateCodec.encode(original))
        // 应完全一致喵
        assertEquals(original.toSet(), restored.toSet())
    }

    @Test
    fun `应用名里的特殊字符能被正确还原`() {
        // 带反斜杠、制表符与换行的应用名喵
        val tricky = listOf(
            UsageDelta("a\\b", null, 10),
            UsageDelta("tab\there", "pkg\ttab", 20),
            UsageDelta("line\nbreak", null, 30),
        )
        // 编码再解码喵
        val restored = UsageStateCodec.decode(UsageStateCodec.encode(tricky))
        // 三个应用都应还原喵
        assertEquals(tricky.toSet(), restored.toSet())
    }

    @Test
    fun `空数据编码成空字符串`() {
        // 空列表喵
        assertEquals("", UsageStateCodec.encode(emptyList()))
    }

    @Test
    fun `空字符串解码成空列表`() {
        // 空文本喵
        assertTrue(UsageStateCodec.decode("").isEmpty())
        // 只有空白喵
        assertTrue(UsageStateCodec.decode("   \n  ").isEmpty())
    }

    @Test
    fun `非法行会被跳过而不影响其它行`() {
        // 混入坏行的文本喵
        val raw = buildString {
            append("60\t\tCode.exe\n")
            append("不是数字\t\t坏行\n")
            append("没有分隔符\n")
            append("-5\t\t负数\n")
            append("30\tcom.tencent.mm\t微信\n")
        }
        // 解码结果只保留合法行喵
        val restored = UsageStateCodec.decode(raw)
        assertEquals(setOf("Code.exe", "微信"), restored.map { it.appName }.toSet())
        assertEquals(60L, restored.single { it.appName == "Code.exe" }.seconds)
        assertEquals(30L, restored.single { it.appName == "微信" }.seconds)
    }

    @Test
    fun `同一应用出现多行时会累加`() {
        // 同一应用两行喵
        val raw = "10\t\tCode.exe\n20\t\tCode.exe"
        // 解码应累加成 30 喵
        assertEquals(30L, UsageStateCodec.decode(raw).single().seconds)
    }

    @Test
    fun `旧的两段格式仍能解析且包名为空`() {
        // 老版本写入的两段格式喵
        val restored = UsageStateCodec.decode("15\t微信")
        // 应用名与秒数应正确，包名应为空喵
        assertEquals("微信", restored.single().appName)
        assertEquals(15L, restored.single().seconds)
        assertNull(restored.single().packageName)
    }

    @Test
    fun `编码会跳过空白应用名与非正秒数`() {
        // 混入非法项喵
        val items = listOf(
            UsageDelta("", null, 10),
            UsageDelta("   ", null, 5),
            UsageDelta("ok", null, 0),
            UsageDelta("good", "pkg.good", 7),
        )
        // 编码后只应包含合法项喵
        assertEquals("7\tpkg.good\tgood", UsageStateCodec.encode(items))
    }

    @Test
    fun `编码结果稳定有序`() {
        // 用不同的插入顺序构造同一份数据喵
        val first = listOf(UsageDelta("b", null, 2), UsageDelta("a", null, 1))
        val second = listOf(UsageDelta("a", null, 1), UsageDelta("b", null, 2))
        // 编码结果应一致喵
        assertEquals(UsageStateCodec.encode(first), UsageStateCodec.encode(second))
    }

    @Test
    fun `末尾孤立反斜杠不会导致崩溃`() {
        // 手工构造被截断的数据喵
        val restored = UsageStateCodec.decode("10\t\tabc\\")
        // 应用名应保留原样喵
        assertEquals("abc\\", restored.single().appName)
    }
}
