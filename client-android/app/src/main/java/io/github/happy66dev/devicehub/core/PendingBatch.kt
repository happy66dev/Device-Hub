package io.github.happy66dev.devicehub.core

/**
 * 一次上报失败后冻结下来的批次：这一批的增量 + 它固定的上报时刻。
 *
 * 为什么需要它：服务端用 `(deviceId, reportedAt)` 做幂等键，
 * 同一个键重复上报只更新设备状态、**不会重复累加秒数**。
 * 原来客户端失败后把这批秒数还回累加器，下一批就变成「旧数据 + 新数据」的超集，
 * 而且重新取了当前时刻 → 服务端认为这是全新的一批，把旧数据又加了一遍，
 * 使用时长**永久翻倍**喵。
 *
 * 正确做法是把失败的那一批**原封不动**留着（同样的秒数、同样的上报时刻），
 * 下一轮优先重发它；送成功之后才清掉，再去发新攒的数据。
 * 这样即使重试十次，服务端也只会认第一次的键，秒数只加一次喵。
 *
 * 注意：`reportedAt` 必须**只在批次创建时取一次**，重试时原样带着走，
 * 不能在每次发送前重新取当前时刻——那正是原来的 bug喵。
 */
data class PendingBatch(
    // 这一批固定的上报时刻（ISO 8601 UTC），重试期间绝不变喵
    val reportedAt: String,
    // 这一批的增量条目喵
    val items: List<UsageDelta>,
) {

    // 这一批的总秒数，日志与界面文案都要用喵
    val totalSeconds: Long = items.sumOf { item -> item.seconds }

    // 是否已经没有数据可发喵
    val isEmpty: Boolean = items.isEmpty()

    /** 把这一批的秒数按应用名汇总，便于断言与日志喵。 */
    fun secondsByApp(): Map<String, Long> {
        // 同名应用把秒数加起来喵
        val merged = LinkedHashMap<String, Long>()
        items.forEach { item ->
            merged[item.appName] = (merged[item.appName] ?: 0L) + item.seconds
        }
        return merged
    }

    companion object {

        // 存储格式版本，老数据没有版本号会被当成无法保证幂等而丢弃喵
        const val STATE_VERSION = 2

        // 版本行前缀喵
        private const val VERSION_PREFIX = "v2\t"

        /**
         * 把批次编码成「版本行 + 若干增量行」的文本。
         *
         * 输入：待编码的批次。
         * 输出：可直接存进偏好设置的文本。
         * 边界：空批次返回空字符串，表示没有东西要重发喵。
         */
        fun encode(batch: PendingBatch): String {
            // 喵~防御：空批次不必写盘喵
            if (batch.isEmpty) return ""
            // 第一行放版本与固定时刻，后面复用现成的增量编解码喵
            return VERSION_PREFIX + batch.reportedAt + "\n" + UsageStateCodec.encode(batch.items)
        }

        /**
         * 从文本还原批次。
         *
         * 输入：编码后的文本。
         * 输出：批次对象；文本为空、版本不对、缺少时刻或没有数据时返回 null。
         * 边界：老格式（没有版本行）返回 null——它没有时刻，无法保证幂等，
         *      宁可不重发也不要冒着翻倍的风险发出去喵。
         */
        fun decode(raw: String): PendingBatch? {
            // 喵~防御：空文本没有批次喵
            if (raw.isBlank()) return null
            // 切成行，第一行是版本与时刻喵
            val lines = raw.split('\n')
            val header = lines.firstOrNull() ?: return null
            // 喵~防御：没有版本前缀就是老格式，不能用喵
            if (!header.startsWith(VERSION_PREFIX)) return null
            // 取固定时刻喵
            val reportedAt = header.removePrefix(VERSION_PREFIX).trim()
            // 喵~防御：时刻为空就没法保证幂等喵
            if (reportedAt.isEmpty()) return null
            // 剩余行按增量格式解析喵
            val items = UsageStateCodec.decode(lines.drop(1).joinToString("\n"))
            // 喵~防御：没有数据就不算批次喵
            if (items.isEmpty()) return null
            // 组装成批次喵
            return PendingBatch(reportedAt = reportedAt, items = items)
        }
    }
}
