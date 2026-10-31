package io.github.happy66dev.devicehub.core

import java.security.MessageDigest

/**
 * 应用图标内容哈希的口径与本地记录编解码。
 *
 * 为什么要哈希：服务端的图标键里带图标内容哈希，客户端只有算出同一个哈希，
 * 才能判断「本地图标换了没有、该不该重传」。三端统一口径：
 * 对 PNG 原始字节求 SHA-1，取十六进制前 16 位喵。
 */
object IconHash {

    /** 哈希长度：与服务端 icon_key() 里的 content_hash 完全一致喵。 */
    const val LENGTH = 16

    /** 记录里的键值分隔符，用 = 便于和旧格式（纯包名）区分喵。 */
    private const val SEPARATOR = "="

    /** 多条记录之间的分隔符，沿用旧格式的逗号喵。 */
    private const val ENTRY_SEPARATOR = ","

    /**
     * 算 PNG 字节的内容哈希。
     *
     * 输入：PNG 原始字节（不是 base64 文本）喵。
     * 输出：16 位小写十六进制字符串。
     * 边界：空数组也能算出一个合法值，不抛异常喵。
     */
    fun contentHash(pngBytes: ByteArray): String {
        // 喵~注意：必须对 PNG 字节求摘要，不能对 base64 文本求——base64 的 padding 可能有差异喵
        val digest = MessageDigest.getInstance("SHA-1").digest(pngBytes)
        // 转成十六进制再截取前 16 位，与服务端口径一致喵
        val hex = StringBuilder(digest.size * 2)
        // 逐字节补零成两位十六进制喵
        for (byte in digest) {
            // 喵~防御：Byte 是有符号的，必须先 and 0xFF 再格式化，否则负数会拼出超长串喵
            hex.append(String.format("%02x", byte.toInt() and 0xFF))
        }
        // 取前 16 位喵
        return hex.substring(0, LENGTH)
    }

    /**
     * 解析本地保存的「包名 → 内容哈希」记录。
     *
     * 输入：SharedPreferences 里的原始文本。
     * 输出：包名到哈希的映射；旧格式里的包名会映射成空串（表示"没有哈希"）。
     * 边界：空文本返回空映射；脏数据（空项、多余分隔符）一律跳过，不抛异常喵。
     */
    fun decode(raw: String?): Map<String, String> {
        // 喵~防御：空值直接当没有记录喵
        if (raw.isNullOrBlank()) return emptyMap()
        // 逐个条目解析喵
        val result = mutableMapOf<String, String>()
        // 按逗号切开喵
        for (entry in raw.split(ENTRY_SEPARATOR)) {
            // 去掉首尾空白喵
            val trimmed = entry.trim()
            // 喵~防御：空项（比如结尾多一个逗号）直接跳过喵
            if (trimmed.isEmpty()) continue
            // 找键值分隔符喵
            val separatorIndex = trimmed.indexOf(SEPARATOR)
            // 喵~注意：没有分隔符说明是旧格式的纯包名，当作"没有哈希"，首次会重传一遍喵
            if (separatorIndex < 0) {
                // 旧记录保留包名，哈希留空表示未知喵
                result[trimmed] = ""
                continue
            }
            // 拆出包名与哈希喵
            val packageName = trimmed.substring(0, separatorIndex).trim()
            val hash = trimmed.substring(separatorIndex + 1).trim()
            // 喵~防御：包名为空的条目没有意义，跳过喵
            if (packageName.isEmpty()) continue
            // 存进映射喵
            result[packageName] = hash
        }
        // 返回解析结果喵
        return result
    }

    /**
     * 把「包名 → 内容哈希」编码成可落盘的文本。
     *
     * 输入：包名到哈希的映射。
     * 输出：逗号分隔的 `包名=哈希` 文本；为空时返回空串。
     * 边界：哈希为空的条目照样写成 `包名=`，读回来仍是"没有哈希"喵。
     */
    fun encode(hashes: Map<String, String>): String {
        // 喵~防御：空映射写成空串，偏好里不留垃圾喵
        if (hashes.isEmpty()) return ""
        // 按包名排序保证输出稳定，方便排查喵
        return hashes.entries
            .sortedBy { it.key }
            .joinToString(ENTRY_SEPARATOR) { "${it.key}$SEPARATOR${it.value}" }
    }

    /**
     * 判断某个包的本地图标是否需要重新上传。
     *
     * 输入：本地算出的哈希、本地记录里该包的哈希（可能为空表示未知）。
     * 输出：true 表示要传；false 表示服务端已有同一张图，跳过。
     * 边界：记录为空（首次或旧格式）一律返回 true，宁可贵一次重传也不要漏传喵。
     */
    fun needsUpload(localHash: String, recordedHash: String?): Boolean {
        // 喵~防御：没有记录就上传，避免旧格式导致永远不传喵
        if (recordedHash.isNullOrBlank()) return true
        // 哈希一致说明服务端已经是这张图，跳过喵
        return recordedHash != localHash
    }
}
