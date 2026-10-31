package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** 设备 ID 生成的单元测试喵。 */
class DeviceIdentityTest {

    @Test
    fun `型号里的空格与大小写会被规范化`() {
        // 空格转短横线，字母转小写喵
        assertEquals("pixel-7-pro", DeviceIdentity.sanitizeModel("Pixel 7 Pro"))
    }

    @Test
    fun `型号里的符号会被合并成单个短横线`() {
        // 连续符号合并，首尾不留短横线喵
        assertEquals("redmi-note-12", DeviceIdentity.sanitizeModel("Redmi  Note_12!!"))
    }

    @Test
    fun `全中文型号回退到默认值`() {
        // 中文会被整体替换成短横线，只剩数字时也算不可读，应回退喵
        assertEquals(DeviceIdentity.FALLBACK_MODEL, DeviceIdentity.sanitizeModel("小米 14"))
    }

    @Test
    fun `空白型号回退到默认值`() {
        // 空字符串与纯空格都应回退喵
        assertEquals(DeviceIdentity.FALLBACK_MODEL, DeviceIdentity.sanitizeModel("   "))
    }

    @Test
    fun `超长型号会被截断`() {
        // 构造 100 个字母的型号喵
        val longModel = "a".repeat(100)
        // 截断到上限喵
        assertEquals(DeviceIdentity.MAX_MODEL_LENGTH, DeviceIdentity.sanitizeModel(longModel).length)
    }

    @Test
    fun `拼出的设备 ID 符合服务端规则`() {
        // 拼出完整 ID 喵
        val deviceId = DeviceIdentity.build("Pixel 7", "9f3c")
        // 断言完整形态喵
        assertEquals("and-pixel-7-9f3c", deviceId)
        // 断言符合服务端正则喵
        assertTrue(deviceId.matches(Regex("^[a-z0-9][a-z0-9._-]{0,63}$")))
    }

    @Test
    fun `随机后缀固定为四位十六进制`() {
        // 用固定种子保证可重复喵
        val suffix = DeviceIdentity.randomSuffix(Random(42))
        // 长度为 4 喵
        assertEquals(4, suffix.length)
        // 只含十六进制字符喵
        assertTrue(suffix.matches(Regex("^[0-9a-f]{4}$")))
    }
}
