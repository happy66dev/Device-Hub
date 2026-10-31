package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** 上报体构造与 JSON 转义的单元测试喵。 */
class ReportPayloadTest {

    /** 构造一份字段齐全的样例喵。 */
    private fun buildFullPayload(): String = ReportPayload.build(
        deviceId = "and-pixel-7-9f3c",
        reportedAt = "2026-10-29T10:00:00Z",
        displayName = "Pixel 7",
        batteryPercent = 88,
        batteryCharging = true,
        hardware = linkedMapOf("manufacturer" to "Google", "model" to "Pixel 7"),
        currentAppName = "微信",
        currentAppPackage = "com.tencent.mm",
        currentAppSince = "2026-10-29T09:58:00Z",
        usageDelta = listOf(
            UsageDelta("微信", "com.tencent.mm", 60),
            UsageDelta("哔哩哔哩", "tv.danmaku.bili", 30),
        ),
        clientVersion = "0.1.0",
        tag = "23113RKC6C",
    )

    @Test
    fun `完整字段输出包含协议要求的所有键`() {
        // 生成上报体喵
        val payload = buildFullPayload()
        // 逐个断言关键片段喵
        assertTrue(payload.contains("\"device_id\":\"and-pixel-7-9f3c\""))
        assertTrue(payload.contains("\"platform\":\"android\""))
        assertTrue(payload.contains("\"reported_at\":\"2026-10-29T10:00:00Z\""))
        assertTrue(payload.contains("\"display_name\":\"Pixel 7\""))
        assertTrue(payload.contains("\"tag\":\"23113RKC6C\""))
        assertTrue(payload.contains("\"battery\":{\"percent\":88,\"charging\":true}"))
        assertTrue(payload.contains("\"hardware\":{\"manufacturer\":\"Google\",\"model\":\"Pixel 7\"}"))
        assertTrue(payload.contains("\"current_app\":{"))
        assertTrue(payload.contains("\"usage_delta\":["))
        // 使用时长条目必须带包名喵
        assertTrue(payload.contains("\"package\":\"com.tencent.mm\""))
        assertTrue(payload.contains("\"client_version\":\"0.1.0\""))
    }

    @Test
    fun `可选字段为空时整段省略`() {
        // 只给必填字段喵
        val payload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.1.0",
        )
        // 不应出现可选键喵
        assertFalse(payload.contains("\"display_name\""))
        assertFalse(payload.contains("\"tag\""))
        assertFalse(payload.contains("\"battery\""))
        assertFalse(payload.contains("\"current_app\""))
        // 空对象与空数组仍要输出喵
        assertTrue(payload.contains("\"hardware\":{}"))
        assertTrue(payload.contains("\"usage_delta\":[]"))
        // 结构必须仍然合法喵
        assertBalancedJson(payload)
    }

    @Test
    fun `AFK 字段按客户端判定结果输出`() {
        // 默认不传 afk 时不应出现该键喵
        val withoutAfk = buildFullPayload()
        assertFalse(withoutAfk.contains("\"afk\""))
        // 传 true 时输出 true 喵
        val afkPayload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.1.0",
            afk = true,
        )
        assertTrue(afkPayload.contains("\"afk\":true"))
        // 传 false 时明确输出 false，服务端据此恢复计时喵
        val activePayload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.1.0",
            afk = false,
        )
        assertTrue(activePayload.contains("\"afk\":false"))
        // 两种取值都必须是合法 JSON 喵
        assertBalancedJson(afkPayload)
        assertBalancedJson(activePayload)
    }

    @Test
    fun `AFK 边界时刻按客户端判定结果输出`() {
        // 进入 AFK 时带上停止计时的精确时刻喵
        val afkPayload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.2.0",
            afk = true,
            afkSince = "2026-10-29T09:58:30Z",
        )
        assertTrue(afkPayload.contains("\"afk_since\":\"2026-10-29T09:58:30Z\""))
        // 恢复计时时带上恢复时刻喵
        val activePayload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.2.0",
            afk = false,
            activeSince = "2026-10-29T09:59:40Z",
        )
        assertTrue(activePayload.contains("\"active_since\":\"2026-10-29T09:59:40Z\""))
        // 不传时不出现这两个键，旧服务端不受影响喵
        val plain = buildFullPayload()
        assertFalse(plain.contains("\"afk_since\""))
        assertFalse(plain.contains("\"active_since\""))
        // 两个新字段也必须是合法 JSON 喵
        assertBalancedJson(afkPayload)
        assertBalancedJson(activePayload)
    }

    @Test
    fun `使用段落位时刻按客户端给的时间输出`() {
        // 带上"最后一秒"的真实时刻喵
        val payload = ReportPayload.build(
            deviceId = "and-pixel-7-9f3c",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = "Pixel 7",
            batteryPercent = 80,
            batteryCharging = false,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.4.0",
            usageEndedAt = "2026-10-29T09:59:20Z",
        )
        // 键与值都要原样出现喵
        assertTrue(payload.contains("\"usage_ended_at\":\"2026-10-29T09:59:20Z\""))
        // 不传时整段省略，旧服务端不受影响喵
        val withoutAnchor = buildFullPayload()
        assertFalse(withoutAnchor.contains("usage_ended_at"))
    }

    @Test
    fun `特殊字符会被正确转义`() {
        // 构造带引号、反斜杠、换行与制表符的设备名喵
        val trickyName = "a\"b\\c\nd\te"
        // 生成上报体喵
        val payload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = trickyName,
            batteryPercent = 50,
            batteryCharging = false,
            hardware = mapOf("model" to "带\"引号\"的型号"),
            currentAppName = "应用\\路径",
            currentAppPackage = "com.example.app",
            currentAppSince = "2026-10-29T09:00:00Z",
            usageDelta = listOf(UsageDelta("应用", null, 5)),
            clientVersion = "0.1.0",
        )
        // 转义序列应出现在文本里喵
        assertTrue(payload.contains("\\\""))
        assertTrue(payload.contains("\\\\"))
        assertTrue(payload.contains("\\n"))
        assertTrue(payload.contains("\\t"))
        // 转义后结构仍然合法喵
        assertBalancedJson(payload)
    }

    @Test
    fun `控制字符会被转成 unicode 转义`() {
        // 用一个不可见的控制字符喵
        val controlChar = '\u0001'.toString()
        // 生成上报体喵
        val payload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = "名字${controlChar}结尾",
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = emptyList(),
            clientVersion = "0.1.0",
        )
        // 应出现 \u0001 转义喵
        assertTrue(payload.contains("\\u0001"))
        // 结构必须合法喵
        assertBalancedJson(payload)
    }

    @Test
    fun `非正秒数不会写进上报体`() {
        // 生成带 0 秒与负秒的上报体喵
        val payload = ReportPayload.build(
            deviceId = "and-test-0001",
            reportedAt = "2026-10-29T10:00:00Z",
            displayName = null,
            batteryPercent = null,
            batteryCharging = null,
            hardware = emptyMap(),
            currentAppName = null,
            currentAppPackage = null,
            currentAppSince = null,
            usageDelta = listOf(UsageDelta("零秒", null, 0), UsageDelta("负数", null, -10)),
            clientVersion = "0.1.0",
        )
        // 数组应为空喵
        assertTrue(payload.contains("\"usage_delta\":[]"))
    }

    @Test
    fun `时间工具输出可被解析的 UTC 文本`() {
        // 取当前时间喵
        val nowText = IsoTime.nowUtc()
        // 应能被 Instant 解析喵
        val parsed = java.time.Instant.parse(nowText)
        // 断言以 Z 结尾喵
        assertTrue(nowText.endsWith("Z"))
        // 断言解析结果可用喵
        assertTrue(parsed.toEpochMilli() > 0)
    }

    /**
     * 断言文本是括号与引号配平的 JSON 结构。
     *
     * 这里不追求完整语法解析，重点是抓出转义漏写导致的引号提前闭合喵。
     */
    private fun assertBalancedJson(text: String) {
        // 当前嵌套深度喵
        var depth = 0
        // 是否在字符串内喵
        var inString = false
        // 上一个字符是否是转义符喵
        var escaped = false
        // 逐字符扫描喵
        text.forEach { character ->
            if (inString) {
                when {
                    escaped -> escaped = false
                    character == '\\' -> escaped = true
                    character == '"' -> inString = false
                    character.code < 0x20 -> fail("字符串里出现未转义的控制字符")
                }
            } else {
                when (character) {
                    '"' -> inString = true
                    '{', '[' -> depth += 1
                    '}', ']' -> depth -= 1
                }
                // 喵~防御：出现负深度说明括号提前闭合喵
                assertTrue("括号提前闭合", depth >= 0)
            }
        }
        // 字符串必须闭合喵
        assertFalse("字符串没有闭合", inString)
        // 括号必须配平喵
        assertEquals("括号没有配平", 0, depth)
    }
}
