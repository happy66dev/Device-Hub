package io.github.happy66dev.devicehub.core

/**
 * AFK（人不在设备前）判定器。
 *
 * 口径：息屏即算 AFK，不再要求「息屏满 60 秒」。
 *
 * 喵~注意：原来的口径是息屏满 60 秒才算离开，理由是「熄屏看一眼时间不该算离开」。
 * 但这样短息屏（几十秒）既不计使用时长、又不报 AFK，时间轴上会留一条空白——
 * 那条空白既不是离线也不是空档，看起来像渲染漏了。主人明确要求
 * 「离线数据必须绝对真实，空档不那么精确没关系」，所以改成息屏即报 AFK，
 * 让时间轴连续：亮屏才有色块，息屏一定是斜纹喵。
 */
class AfkTracker {

    // 本次连续息屏的起始时刻，亮屏时为 null 喵
    private var screenOffSinceMillis: Long? = null

    /**
     * 用一次屏幕状态采样推进判定。
     *
     * 输入：本次屏幕是否点亮、当前时刻（毫秒）。
     * 输出：true 表示此刻应当上报 AFK。
     * 边界：第一次看到息屏就返回 true 并记下起点；时钟回拨不影响判定喵。
     */
    fun update(screenOn: Boolean, nowMillis: Long): Boolean {
        // 亮屏说明人在用，清空累计并立刻退出 AFK 喵
        if (screenOn) {
            screenOffSinceMillis = null
            return false
        }
        // 喵~注意：息屏第一帧就记下起点并直接返回 true，不再等 60 秒阈值喵
        if (screenOffSinceMillis == null) {
            screenOffSinceMillis = nowMillis
        }
        return true
    }

    /** 清空内部状态，服务重启时调用喵。 */
    fun reset() {
        // 丢掉起点，下一轮重新计时喵
        screenOffSinceMillis = null
    }

    /**
     * 取"停止计时"的精确时刻。
     *
     * 输出：处于 AFK 时返回息屏那一刻（停止计时）的毫秒时刻；亮屏时返回 null。
     * 用途：随上报送给服务端，让时间轴把空档起点量到秒，而不是靠整分钟猜喵。
     */
    fun afkSinceMillis(): Long? {
        // 只有真的进入 AFK 才有边界可言喵
        val since = screenOffSinceMillis ?: return null
        // 喵~注意：停止计时发生在息屏那一刻，不是"息屏满阈值"那一刻——
        // 阈值只是防抖，若把边界算成息屏 + 60 秒，斜纹前面会白白空出 60 秒喵
        return since
    }
}
