package io.github.happy66dev.devicehub.collect

import android.content.Context
import android.os.PowerManager

/**
 * 屏幕状态读取器。
 *
 * 息屏时用户并不在看手机，按 patina / ActivityWatch 的口径这段时间不该计入使用时长喵。
 */
class ScreenState(private val context: Context) {

    // 电源服务，懒加载避免重复获取喵
    private val powerManager: PowerManager? by lazy {
        context.getSystemService(Context.POWER_SERVICE) as? PowerManager
    }

    /**
     * 判断屏幕是否点亮。
     *
     * 输出：true 表示屏幕亮着、可以计时；false 表示息屏。
     * 边界：拿不到电源服务或调用异常时返回 true，宁可多算也不要因为探测失败静默停止统计喵。
     */
    fun isInteractive(): Boolean {
        return try {
            // isInteractive 同时覆盖息屏与 Doze 休眠喵
            powerManager?.isInteractive ?: true
        } catch (error: Exception) {
            // 喵~防御：个别 ROM 会抛异常，异常时按"亮屏"处理，避免静默丢数据喵
            true
        }
    }
}
