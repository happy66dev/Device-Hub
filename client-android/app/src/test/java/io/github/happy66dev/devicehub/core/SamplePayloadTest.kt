package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * 导出样例上报体，供服务端联调使用。
 *
 * 为什么要这个测试：真机安装受厂商限制时，仍然可以把 App 会发出的 JSON
 * 原样喂给服务端，验证字段与类型是否被接受喵。
 */
class SamplePayloadTest {

    @Test
    fun `导出样例上报体到构建目录`() {
        // 构造与真机一致的样例喵
        val payload = ReportPayload.build(
            deviceId = "and-sample-0001",
            reportedAt = IsoTime.nowUtc(),
            displayName = "样例手机",
            batteryPercent = 76,
            batteryCharging = false,
            hardware = linkedMapOf(
                "manufacturer" to "Xiaomi",
                "model" to "23113RKC6C",
                "brand" to "Redmi",
                "android_version" to "14",
                "sdk_int" to "34",
            ),
            currentAppName = "微信",
            currentAppPackage = "com.tencent.mm",
            currentAppSince = IsoTime.nowUtc(),
            usageDelta = listOf(
                UsageDelta("微信", "com.tencent.mm", 45),
                UsageDelta("哔哩哔哩", "tv.danmaku.bili", 30),
            ),
            clientVersion = "0.1.0",
            tag = "23113RKC6C",
        )
        // 输出目录取模块下的 build/reports 喵
        val outputDir = File(System.getProperty("user.dir"), "build/reports")
        // 喵~防御：目录创建失败时让测试直接失败，避免静默跳过喵
        if (!outputDir.exists() && !outputDir.mkdirs()) {
            throw IllegalStateException("无法创建输出目录：${outputDir.absolutePath}")
        }
        // 写出样例文件喵
        val outputFile = File(outputDir, "sample-payload.json")
        outputFile.writeText(payload, Charsets.UTF_8)
        // 断言文件非空喵
        assertTrue(outputFile.length() > 0)
    }
}
