package io.github.happy66dev.devicehub.collect

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Process
import java.time.Instant

/**
 * 前台应用读取器。
 *
 * 数据来源：UsageStatsManager 的事件流里最近一条 ACTIVITY_RESUMED。
 * 这是 Android 5.0 之后官方允许的方式，需要用户在设置里授予"使用情况访问"权限喵。
 */
class UsageReader(private val context: Context) {

    // 系统服务，懒加载避免主线程之外重复获取喵
    private val usageStatsManager: UsageStatsManager? by lazy {
        context.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
    }

    // 查询事件的时间窗口：缓存为空时才回看这么久，避免第一次采样漏掉长时间不切换的应用喵
    private val coldWindowMillis = 5 * 60_000L

    // 增量查询的重叠时间：两次采样之间留点余量，防止事件刚好落在边界上被漏掉喵
    private val overlapMillis = 10_000L

    // 上一次查询的结束时刻，用来只查新增事件，别每次都扫 5 分钟喵
    private var lastQueryAtMillis = 0L

    // 包名到应用名的缓存，避免每轮都去问 PackageManager 喵
    private val nameCache = HashMap<String, String>()

    // 最近一次判定出来的前台应用，事件流里没有新事件时沿用它喵
    private var lastForeground: ForegroundApp? = null

    /**
     * 判断是否已授予"使用情况访问"权限。
     *
     * 输出：true 表示可读取事件流。
     */
    fun hasUsageAccess(): Boolean {
        return try {
            // 用 AppOps 检查更准确，部分 ROM 的 checkPermission 会误报喵
            val appOpsManager = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
                ?: return false
            // 读取当前模式喵
            val mode = appOpsManager.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName,
            )
            // 允许或默认都视为可用喵
            mode == AppOpsManager.MODE_ALLOWED || mode == AppOpsManager.MODE_DEFAULT
        } catch (error: Exception) {
            // 喵~防御：不同 ROM 的 AppOps 行为不一致，异常时按"未授权"处理，引导用户去设置页喵
            false
        }
    }

    /**
     * 读取当前前台应用。
     *
     * 输出：前台应用快照；无权限时返回 null。
     * 边界：事件窗口里没有新的切前台事件时，沿用上一次记住的应用（否则用户一直待在一个应用里就永远采不到）；
     * 本应用自身在前台时返回 null，避免把"配置界面"统计成使用时长喵。
     */
    fun currentForeground(): ForegroundApp? {
        // 喵~防御：没有权限时清空缓存并返回，避免抛 SecurityException 喵
        if (!hasUsageAccess()) {
            lastForeground = null
            return null
        }
        // 喵~防御：个别设备没有该服务喵
        val manager = usageStatsManager ?: return lastForeground
        return try {
            // 计算查询窗口：缓存为空时回看久一点，否则只查上次之后的新事件喵
            val endTime = System.currentTimeMillis()
            val startTime = if (lastForeground == null) {
                endTime - coldWindowMillis
            } else {
                (lastQueryAtMillis - overlapMillis).coerceAtLeast(endTime - coldWindowMillis)
            }
            // 记下这次查到的位置，下一轮从这里继续喵
            lastQueryAtMillis = endTime
            // 查询事件喵
            val events = manager.queryEvents(startTime, endTime) ?: return lastForeground
            // 复用事件对象，减少 GC 压力喵
            val event = UsageEvents.Event()
            // 记录窗口内最近一次进入前台的应用喵
            var lastPackage: String? = null
            var lastTimestamp = 0L
            // 遍历事件流喵
            while (events.hasNextEvent()) {
                events.getNextEvent(event)
                // 只关心"进入前台"事件喵
                if (event.eventType == UsageEvents.Event.ACTIVITY_RESUMED) {
                    lastPackage = event.packageName
                    lastTimestamp = event.timeStamp
                }
            }
            // 交给纯函数决定这次的前台应用喵
            lastForeground = pickForeground(
                previous = lastForeground,
                resumedPackage = lastPackage,
                resumedAtMillis = lastTimestamp,
                ownPackage = context.packageName,
                labelOf = ::resolveAppName,
            )
            lastForeground
        } catch (error: Exception) {
            // 喵~防御：权限被回收或系统服务异常时沿用上一次结果，不影响心跳上报喵
            lastForeground
        }
    }

    /**
     * 清空前台应用缓存。
     *
     * 用途：息屏时调用，避免上报里一直挂着息屏前那个应用喵。
     */
    fun resetForeground() {
        // 丢掉缓存，下次亮屏重新从事件流判定喵
        lastForeground = null
        // 喵~注意：同时把增量查询位置清掉，下次会用较长的窗口重新找回前台应用喵
        lastQueryAtMillis = 0L
    }

    /**
     * 把包名解析成应用展示名。
     *
     * 输入：包名，例如 com.tencent.mm。
     * 输出：应用名，解析失败时返回包名本身。
     */
    private fun resolveAppName(packageName: String): String {
        // 喵~注意：PackageManager 调用不便宜，同一个包只查一次喵
        nameCache[packageName]?.let { return it }
        return try {
            // 读取应用信息喵
            val applicationInfo = context.packageManager.getApplicationInfo(packageName, 0)
            // 取应用标签喵
            val label = context.packageManager.getApplicationLabel(applicationInfo)?.toString() ?: ""
            // 喵~防御：标签为空时退回包名，保证上报里一定有可读标识喵
            val resolved = label.ifBlank { packageName }
            // 记进缓存喵
            nameCache[packageName] = resolved
            resolved
        } catch (error: Exception) {
            // 喵~防御：应用被卸载或不可见时用包名兜底喵
            packageName
        }
    }
}

/** 前台应用快照喵。 */
data class ForegroundApp(
    val name: String,
    val packageName: String,
    val sinceIso: String,
)

/**
 * 根据一次事件查询的结果决定当前前台应用。
 *
 * 输入：上一次的判定结果、窗口内最近一次 ACTIVITY_RESUMED 的包名与时刻、本应用包名、包名取名字函数。
 * 输出：这次的前台应用快照；null 表示窗口里没有任何前台线索。
 * 边界：窗口里没有新的切前台事件时沿用上一次的结果，
 * 这样用户一直待在一个应用里也能持续统计（旧实现只看 10 秒窗口，几乎永远采不到）喵。
 *
 * 喵~注意：本应用自己在前台时也照常上报，不再返回 null。
 * 主人明确要求「DeviceHub 也要被当作一个安卓软件上报」，
 * 打开看板查数据的那段时间同样算使用时长，才不会凭空少一块喵。
 */
internal fun pickForeground(
    previous: ForegroundApp?,
    resumedPackage: String?,
    resumedAtMillis: Long,
    ownPackage: String,
    labelOf: (String) -> String,
): ForegroundApp? {
    // 喵~防御：窗口里没有新的切前台事件，说明还停在上一个应用里喵
    if (resumedPackage.isNullOrBlank()) return previous
    // 组装新的快照，since 用事件发生的时刻喵
    return ForegroundApp(
        name = labelOf(resumedPackage),
        packageName = resumedPackage,
        sinceIso = Instant.ofEpochMilli(resumedAtMillis).toString(),
    )
}
