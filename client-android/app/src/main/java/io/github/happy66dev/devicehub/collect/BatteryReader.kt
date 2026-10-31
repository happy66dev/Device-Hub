package io.github.happy66dev.devicehub.collect

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager

/**
 * 电量读取器。
 *
 * 用粘性广播 ACTION_BATTERY_CHANGED 读取，不需要注册长期接收器，
 * 也不会产生额外耗电喵。
 */
class BatteryReader(private val context: Context) {

    /**
     * 读取当前电量与充电状态。
     *
     * 输出：电量百分比与是否充电；读取失败时返回 null。
     * 边界：部分模拟器或异常设备可能拿不到电量，此时返回 null 而不是 0。
     */
    fun read(): BatterySnapshot? {
        return try {
            // 传入 null 的接收器可以拿到粘性广播喵
            val batteryIntent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            // 喵~防御：个别 ROM 会返回空 Intent，此时无法判断电量喵
            if (batteryIntent == null) return null
            // 读取当前电量与满电量刻度喵
            val level = batteryIntent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val scale = batteryIntent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            // 喵~防御：level 或 scale 无效时算不出百分比喵
            if (level < 0 || scale <= 0) return null
            // 换算成百分比并夹紧到 0..100 喵
            val percent = (level * 100 / scale).coerceIn(0, 100)
            // 读取充电状态喵
            val status = batteryIntent.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN)
            // 充电中或已充满都算"接着电"喵
            val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                status == BatteryManager.BATTERY_STATUS_FULL
            BatterySnapshot(percent, charging)
        } catch (error: Exception) {
            // 喵~防御：注册接收器在极端情况下会抛异常，这里吞掉并返回 null，避免服务崩溃喵
            null
        }
    }
}

/** 电量快照，percent 取值 0..100 喵。 */
data class BatterySnapshot(val percent: Int, val charging: Boolean)
