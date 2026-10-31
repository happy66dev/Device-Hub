package io.github.happy66dev.devicehub.core

import java.time.Instant

/**
 * JSON 文本转义工具。
 *
 * 为什么手写：本工程刻意不引入 JSON 库，减少依赖与 APK 体积；
 * 上报体结构固定且字段很少，手写拼接足够可靠，关键是转义必须正确喵。
 */
object JsonText {

    /**
     * 转义字符串内容（不含外层引号）。
     *
     * 输入：任意文本。
     * 输出：可安全放进 JSON 字符串的文本。
     * 边界：控制字符、引号、反斜杠都会被转义；其它字符原样保留。
     */
    fun escape(raw: String): String {
        // 用 StringBuilder 逐字符处理，避免多次创建中间字符串喵
        val builder = StringBuilder(raw.length + 16)
        raw.forEach { character ->
            when (character) {
                // 双引号必须转义喵
                '"' -> builder.append("\\\"")
                // 反斜杠必须转义喵
                '\\' -> builder.append("\\\\")
                // 换行转成 \n 喵
                '\n' -> builder.append("\\n")
                // 回车转成 \r 喵
                '\r' -> builder.append("\\r")
                // 制表符转成 \t 喵
                '\t' -> builder.append("\\t")
                else -> {
                    // 喵~防御：控制字符（小于 0x20）直接放进 JSON 会破坏结构，统一转成 \u00XX 喵
                    if (character.code < 0x20) {
                        builder.append("\\u%04x".format(character.code))
                    } else {
                        builder.append(character)
                    }
                }
            }
        }
        return builder.toString()
    }

    /** 把文本包成带引号的 JSON 字符串喵。 */
    fun quote(raw: String): String = "\"" + escape(raw) + "\""
}

/** 时间格式工具，统一输出带 Z 的 UTC 时间喵。 */
object IsoTime {

    /**
     * 返回当前 UTC 时间文本，例如 2026-10-29T10:05:23.897Z。
     *
     * 输出：符合 ISO 8601 的 UTC 时间字符串。
     */
    fun nowUtc(): String = Instant.now().toString()
}

/**
 * 上报体构造器，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证输出。
 *
 * 字段与服务端 `docs/protocol.md` 一一对应，多余字段会被服务端拒绝，
 * 所以这里只输出协议里存在的键喵。
 */
object ReportPayload {

    /**
     * 构造上报 JSON 字符串。
     *
     * 输入：设备信息、电量、当前应用、使用时长增量、设备标签。
     * 输出：可直接作为 HTTP body 的 JSON 文本。
     * 边界：可选字段为空时整段省略，而不是输出 null。
     */
    fun build(
        deviceId: String,
        reportedAt: String,
        displayName: String?,
        batteryPercent: Int?,
        batteryCharging: Boolean?,
        hardware: Map<String, String>,
        currentAppName: String?,
        currentAppPackage: String?,
        currentAppSince: String?,
        usageDelta: List<UsageDelta>,
        clientVersion: String,
        tag: String? = null,
        afk: Boolean? = null,
        afkSince: String? = null,
        activeSince: String? = null,
        usageEndedAt: String? = null,
    ): String {
        // 用 StringBuilder 拼接，字段顺序固定便于阅读日志喵
        val builder = StringBuilder(512)
        // 开对象喵
        builder.append('{')
        // 设备 ID 喵
        builder.append("\"device_id\":").append(JsonText.quote(deviceId)).append(',')
        // 平台固定 android 喵
        builder.append("\"platform\":\"android\",")
        // 上报时间喵
        builder.append("\"reported_at\":").append(JsonText.quote(reportedAt)).append(',')
        // 喵~防御：设备名为空时省略字段，让服务端用 device_id 兜底喵
        if (!displayName.isNullOrBlank()) {
            builder.append("\"display_name\":").append(JsonText.quote(displayName)).append(',')
        }
        // 喵~防御：标签用于匹配投屏窗口标题，为空时省略喵
        if (!tag.isNullOrBlank()) {
            builder.append("\"tag\":").append(JsonText.quote(tag.trim())).append(',')
        }
        // 喵~注意：AFK 由客户端判定，服务端据此把这段时间画成空档而不是当作在用喵
        if (afk != null) {
            builder.append("\"afk\":").append(afk).append(',')
        }
        // 喵~注意：空档边界时刻让服务端把斜纹量到秒，不再靠整分钟猜喵
        if (!afkSince.isNullOrBlank()) {
            builder.append("\"afk_since\":").append(JsonText.quote(afkSince)).append(',')
        }
        // 恢复计时的时刻同理喵
        if (!activeSince.isNullOrBlank()) {
            builder.append("\"active_since\":").append(JsonText.quote(activeSince)).append(',')
        }
        // 喵~注意：这一批使用时长"最后一秒"的真实时刻，服务端按它给色块落位喵
        if (!usageEndedAt.isNullOrBlank()) {
            builder.append("\"usage_ended_at\":").append(JsonText.quote(usageEndedAt)).append(',')
        }
        // 喵~防御：电量缺失时整段省略喵
        if (batteryPercent != null) {
            builder.append("\"battery\":{")
            builder.append("\"percent\":").append(batteryPercent.coerceIn(0, 100)).append(',')
            builder.append("\"charging\":").append(batteryCharging ?: false)
            builder.append("},")
        }
        // 硬件信息对象喵
        builder.append("\"hardware\":{")
        var hardwareIndex = 0
        hardware.forEach { (key, value) ->
            // 喵~防御：空键名无法渲染，跳过喵
            if (key.isBlank()) return@forEach
            // 非首个元素前补逗号喵
            if (hardwareIndex > 0) builder.append(',')
            builder.append(JsonText.quote(key)).append(':').append(JsonText.quote(value))
            hardwareIndex += 1
        }
        builder.append("},")
        // 喵~防御：没有前台应用时省略字段喵
        if (!currentAppName.isNullOrBlank()) {
            builder.append("\"current_app\":{")
            builder.append("\"name\":").append(JsonText.quote(currentAppName))
            // 包名可能为空喵
            if (!currentAppPackage.isNullOrBlank()) {
                builder.append(",\"package\":").append(JsonText.quote(currentAppPackage))
            }
            // 进入前台时间可能为空喵
            if (!currentAppSince.isNullOrBlank()) {
                builder.append(",\"since\":").append(JsonText.quote(currentAppSince))
            }
            builder.append("},")
        }
        // 使用时长增量数组喵
        builder.append("\"usage_delta\":[")
        var usageIndex = 0
        usageDelta.forEach { item ->
            // 喵~防御：非正秒数不上报，避免产生无意义记录喵
            if (item.seconds <= 0L) return@forEach
            // 喵~防御：空白应用名无法归属喵
            if (item.appName.isBlank()) return@forEach
            // 非首个元素前补逗号喵
            if (usageIndex > 0) builder.append(',')
            builder.append('{')
            builder.append("\"app\":").append(JsonText.quote(item.appName)).append(',')
            // 包名可能为空，为空时省略该字段喵
            if (!item.packageName.isNullOrBlank()) {
                builder.append("\"package\":").append(JsonText.quote(item.packageName)).append(',')
            }
            builder.append("\"seconds\":").append(item.seconds.coerceAtMost(86_400L))
            builder.append('}')
            usageIndex += 1
        }
        builder.append("],")
        // 客户端版本号喵
        builder.append("\"client_version\":").append(JsonText.quote(clientVersion))
        // 关对象喵
        builder.append('}')
        return builder.toString()
    }
}
