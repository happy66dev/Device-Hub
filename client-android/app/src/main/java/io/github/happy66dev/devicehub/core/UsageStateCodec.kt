package io.github.happy66dev.devicehub.core

/**
 * 待上报使用时长的序列化工具，纯 Kotlin 实现，方便 JVM 单元测试。
 *
 * 为什么需要：前台服务随时可能被系统杀掉，内存里的累计秒数会丢；
 * 把数据存进 SharedPreferences 后，服务重启可以接着上报喵。
 *
 * 格式：每行 "秒数<TAB>包名<TAB>应用名"，应用名与包名里的反斜杠、制表符、换行会被转义喵。
 * 兼容：老版本的 "秒数<TAB>应用名" 两段格式仍能解析，只是包名为空喵。
 */
object UsageStateCodec {

    // 行内分隔符，用制表符避免与应用名里的空格冲突喵
    private const val FIELD_SEPARATOR = '\t'

    // 每行最多切成几段：秒数、包名、应用名喵
    private const val MAX_FIELDS = 3

    // 转义后的反斜杠喵
    private const val ESCAPED_BACKSLASH = "\\\\"

    // 转义后的制表符喵
    private const val ESCAPED_TAB = "\\t"

    // 转义后的换行喵
    private const val ESCAPED_NEWLINE = "\\n"

    /**
     * 把待上报数据编码成一行行的文本。
     *
     * 输入：待上报条目列表。
     * 输出：可直接存进偏好设置的文本；数据为空时返回空字符串。
     * 边界：空白应用名与非正秒数会被跳过。
     */
    fun encode(items: List<UsageDelta>): String {
        // 按应用名排序，保证同一份数据每次编码结果一致喵
        return items
            .asSequence()
            .filter { item -> item.appName.isNotBlank() && item.seconds > 0L }
            .sortedBy { item -> item.appName }
            .joinToString(separator = "\n") { item ->
                // 秒数在前，包名居中，应用名在最后喵
                val encodedPackage = escape(item.packageName ?: "")
                "${item.seconds}$FIELD_SEPARATOR$encodedPackage$FIELD_SEPARATOR${escape(item.appName)}"
            }
    }

    /**
     * 把文本解码回待上报条目列表。
     *
     * 输入：编码后的文本。
     * 输出：条目列表；文本为空或全部非法时返回空列表。
     * 边界：单行格式错误只跳过该行，不影响其它数据；两段旧格式按包名为空处理喵。
     */
    fun decode(raw: String): List<UsageDelta> {
        // 结果按应用名归并，避免同一应用出现多行时互相覆盖喵
        val restored = LinkedHashMap<String, UsageDelta>()
        // 喵~防御：空文本直接返回空列表喵
        if (raw.isBlank()) return emptyList()
        // 逐行解析喵
        raw.split('\n').forEach { line ->
            // 喵~防御：空行跳过喵
            if (line.isBlank()) return@forEach
            // 最多切成三段，应用名里若含制表符会在转义阶段被替换掉喵
            val fields = line.split(FIELD_SEPARATOR, limit = MAX_FIELDS)
            // 喵~防御：少于两段说明这行坏了喵
            if (fields.size < 2) return@forEach
            // 解析秒数喵
            val seconds = fields[0].toLongOrNull() ?: return@forEach
            // 喵~防御：非正秒数没有意义喵
            if (seconds <= 0L) return@forEach
            // 两段旧格式没有包名喵
            val rawPackage = if (fields.size >= MAX_FIELDS) fields[1] else ""
            // 应用名永远在最后一段喵
            val appName = unescape(fields[fields.size - 1])
            // 喵~防御：空白应用名跳过喵
            if (appName.isBlank()) return@forEach
            // 解析包名喵
            val packageName = unescape(rawPackage).takeIf { it.isNotBlank() }
            // 合并同一应用的秒数喵
            val existing = restored[appName]
            restored[appName] = UsageDelta(
                appName = appName,
                packageName = packageName ?: existing?.packageName,
                seconds = (existing?.seconds ?: 0L) + seconds,
            )
        }
        return restored.values.toList()
    }

    /** 转义应用名里的特殊字符喵。 */
    private fun escape(appName: String): String {
        // 先转义反斜杠，再转义控制字符，顺序不能反喵
        return appName
            .replace("\\", ESCAPED_BACKSLASH)
            .replace("\t", ESCAPED_TAB)
            .replace("\n", ESCAPED_NEWLINE)
    }

    /** 把转义序列还原成原始字符喵。 */
    private fun unescape(encoded: String): String {
        // 用 StringBuilder 逐字符扫描，避免多次 replace 把 \\t 误还原喵
        val builder = StringBuilder(encoded.length)
        var index = 0
        while (index < encoded.length) {
            val character = encoded[index]
            // 喵~防御：末尾单独一个反斜杠说明数据被截断，原样保留喵
            if (character == '\\' && index + 1 < encoded.length) {
                when (encoded[index + 1]) {
                    '\\' -> {
                        builder.append('\\')
                        index += 2
                    }
                    't' -> {
                        builder.append('\t')
                        index += 2
                    }
                    'n' -> {
                        builder.append('\n')
                        index += 2
                    }
                    else -> {
                        builder.append(character)
                        index += 1
                    }
                }
            } else {
                builder.append(character)
                index += 1
            }
        }
        return builder.toString()
    }
}
