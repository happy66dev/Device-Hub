package io.github.happy66dev.devicehub.core

/**
 * 使用时长增量累加器，纯 Kotlin 实现。
 *
 * 语义与服务端一致：每次上报的是"自上次上报以来新增的前台秒数"，
 * 服务端只做累加，不做去重，所以客户端必须保证不重复上报同一段时间。
 *
 * 每个应用同时记录包名：应用名用于展示，包名用于服务端稳定匹配喵。
 */
class UsageDeltaCalculator {

    // 待上报的累计数据，键是应用展示名喵
    private val pendingItems = LinkedHashMap<String, UsageDelta>()

    /**
     * 给某个应用累加秒数。
     *
     * 输入：应用名、秒数、可选包名。
     * 输出：无。
     * 边界：应用名为空或秒数非正数时忽略；单应用累计超过一天时截断。
     */
    fun addSeconds(appName: String, seconds: Long, packageName: String? = null) {
        // 喵~防御：空应用名无法归属，直接忽略喵
        if (appName.isBlank()) return
        // 喵~防御：非正数秒数没有信息量喵
        if (seconds <= 0L) return
        // 去掉首尾空白并限制长度，避免异常长名字撑爆上报体喵
        val cleanedName = appName.trim().take(MAX_APP_NAME_LENGTH)
        // 包名同样清洗并限制长度喵
        val cleanedPackage = packageName?.trim()?.take(MAX_PACKAGE_LENGTH)?.takeIf { it.isNotEmpty() }
        // 已有记录时沿用旧包名，避免这次取不到包名就把好数据覆盖成空喵
        val existing = pendingItems[cleanedName]
        // 累加到已有值上，并做上限截断喵
        val accumulatedSeconds = ((existing?.seconds ?: 0L) + seconds).coerceAtMost(MAX_SECONDS_PER_APP)
        // 写回累加结果喵
        pendingItems[cleanedName] = UsageDelta(
            appName = cleanedName,
            packageName = cleanedPackage ?: existing?.packageName,
            seconds = accumulatedSeconds,
        )
    }

    /**
     * 取出全部待上报数据并清空内部状态。
     *
     * 输出：按秒数倒序、最多 500 条的列表。
     */
    fun drain(): List<UsageDelta> {
        // 取出排序后的列表喵
        val drained = toDeltaList()
        // 清空内部累计喵
        pendingItems.clear()
        // 返回副本喵
        return drained
    }

    /**
     * 把上报失败的数据还回累加器。
     *
     * 输入：待上报条目列表。
     * 输出：无。
     */
    fun restore(items: List<UsageDelta>) {
        // 喵~防御：空数据无需处理喵
        if (items.isEmpty()) return
        // 逐项累加回去喵
        items.forEach { item -> addSeconds(item.appName, item.seconds, item.packageName) }
    }

    /** 清空待上报数据喵。 */
    fun clear() {
        pendingItems.clear()
    }

    /**
     * 返回待上报数据的副本，但不影响内部累计。
     *
     * 用途：把数据落盘做崩溃保护喵。
     *
     * 输出：待上报条目列表。
     */
    fun snapshot(): List<UsageDelta> {
        // 复制一份返回，调用方改动不会影响内部状态喵
        return pendingItems.values.toList()
    }

    /** 返回当前待上报总秒数，用于日志与测试喵。 */
    fun totalSeconds(): Long {
        // 求和喵
        return pendingItems.values.sumOf { it.seconds }
    }

    /**
     * 转成按秒数倒序的列表，并限制条数。
     *
     * 输出：待上报条目列表。
     * 边界：超过 500 条时按秒数截断，避免服务端拒收。
     */
    fun toDeltaList(): List<UsageDelta> {
        // 按秒数倒序，保证重要数据先发喵
        return pendingItems.values
            .sortedByDescending { it.seconds }
            .take(MAX_APPS_PER_REPORT)
    }

    companion object {

        // 单应用单次允许上报的最大秒数，一天喵
        const val MAX_SECONDS_PER_APP = 86_400L

        // 单次上报允许的最大应用条数，与服务端一致喵
        const val MAX_APPS_PER_REPORT = 500

        // 应用名最大长度，与服务端字段限制一致喵
        const val MAX_APP_NAME_LENGTH = 128

        // 包名最大长度，与服务端字段限制一致喵
        const val MAX_PACKAGE_LENGTH = 200

        /**
         * 用两次"系统累计读数"算增量，供需要精确对齐系统统计的实现使用。
         *
         * 输入：上一次的系统累计读数、本次的系统累计读数。
         * 输出：仅包含正增量的映射。
         * 边界：本次读数小于上次（跨天重置或应用被清数据）时按 0 处理，不产生负值。
         */
        fun computeDelta(previousTotals: Map<String, Long>, currentTotals: Map<String, Long>): Map<String, Long> {
            // 结果按输入顺序保存，便于日志排查喵
            val delta = LinkedHashMap<String, Long>()
            // 逐个应用计算差值喵
            currentTotals.forEach { (appName, currentValue) ->
                // 没有历史读数时按 0 处理喵
                val previousValue = previousTotals[appName] ?: 0L
                // 计算差值喵
                val difference = currentValue - previousValue
                // 喵~防御：差值非正说明跨天重置或数据回退，不产生增量喵
                if (difference > 0L) delta[appName] = difference
            }
            return delta
        }
    }
}
