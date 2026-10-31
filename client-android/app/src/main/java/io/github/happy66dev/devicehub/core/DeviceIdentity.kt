package io.github.happy66dev.devicehub.core

import kotlin.random.Random

/**
 * 设备 ID 生成器，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 规则与服务端 `models.py` 的 DEVICE_ID_PATTERN 保持一致：
 * 小写字母数字开头，只含 a-z0-9._-，最长 64 位。
 */
object DeviceIdentity {

    // 型号里不允许出现的字符，统一替换成短横线喵
    private val INVALID_MODEL_CHARS = Regex("[^a-z0-9]+")

    // 型号清洗后为空时的兜底值喵
    const val FALLBACK_MODEL = "android"

    // 型号部分的最大长度，给前缀和后缀留足空间喵
    const val MAX_MODEL_LENGTH = 32

    /**
     * 把型号清洗成可用于设备 ID 的片段。
     *
     * 输入：原始型号，例如 "Pixel 7 Pro"。
     * 输出：小写、仅含小写字母数字与短横线的字符串。
     * 边界：空白、全中文、清洗后为空时返回 [FALLBACK_MODEL]。
     */
    fun sanitizeModel(rawModel: String): String {
        // 喵~防御：空白型号没有可用信息，直接用兜底值喵
        if (rawModel.isBlank()) return FALLBACK_MODEL
        // 转小写并把非法字符替换成短横线喵
        var cleaned = rawModel.trim().lowercase().replace(INVALID_MODEL_CHARS, "-").trim('-')
        // 喵~防御：全中文型号清洗后可能只剩数字（如 "小米 14" → "14"），没有可读性，用兜底值喵
        if (cleaned.isEmpty() || cleaned.none { it in 'a'..'z' }) return FALLBACK_MODEL
        // 超长时截断，避免拼出的 ID 超过 64 位喵
        if (cleaned.length > MAX_MODEL_LENGTH) {
            cleaned = cleaned.substring(0, MAX_MODEL_LENGTH).trim('-')
        }
        // 喵~防御：截断后可能又变空，再兜底一次喵
        if (cleaned.isEmpty()) return FALLBACK_MODEL
        return cleaned
    }

    /**
     * 拼出完整设备 ID，例如 and-pixel-7-pro-9f3c。
     *
     * 输入：原始型号、4 位十六进制后缀。
     * 输出：符合服务端规则的设备 ID。
     */
    fun build(model: String, suffix: String): String {
        // 前缀固定 and-，便于在 QQ 群里一眼看出是安卓设备喵
        return "and-${sanitizeModel(model)}-$suffix"
    }

    /**
     * 生成 4 位十六进制随机后缀。
     *
     * 输入：可选随机源，测试时可传入固定种子。
     * 输出：形如 "9f3c" 的字符串。
     */
    fun randomSuffix(random: Random = Random.Default): String {
        // 取 0 到 65535 之间的整数喵
        val randomValue = random.nextInt(0, 0x10000)
        // 转十六进制并补齐 4 位喵
        return randomValue.toString(16).padStart(4, '0')
    }
}
