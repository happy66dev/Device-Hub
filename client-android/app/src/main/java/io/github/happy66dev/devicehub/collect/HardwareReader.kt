package io.github.happy66dev.devicehub.collect

import android.os.Build

/**
 * 硬件与系统信息采集，只读 Build 字段，不需要任何权限。
 */
object HardwareReader {

    /**
     * 采集硬件信息。
     *
     * 输出：键名到值的映射，键名与协议文档一致。
     */
    fun collect(): Map<String, String> {
        // 用 LinkedHashMap 保证键顺序稳定，方便看日志喵
        val hardware = LinkedHashMap<String, String>()
        // 厂商喵
        hardware["manufacturer"] = (Build.MANUFACTURER ?: "").trim()
        // 型号喵
        hardware["model"] = (Build.MODEL ?: "").trim()
        // 品牌喵
        hardware["brand"] = (Build.BRAND ?: "").trim()
        // Android 版本号，例如 14 喵
        hardware["android_version"] = (Build.VERSION.RELEASE ?: "").trim()
        // SDK 版本号，例如 34 喵
        hardware["sdk_int"] = Build.VERSION.SDK_INT.toString()
        // 设备代号喵
        hardware["device"] = (Build.DEVICE ?: "").trim()
        // 喵~防御：过滤掉空值，避免服务端渲染出 "型号：" 这种空行喵
        return hardware.filterValues { it.isNotBlank() }
    }
}
