package io.github.happy66dev.devicehub.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import io.github.happy66dev.devicehub.core.AgentLog
import io.github.happy66dev.devicehub.data.AgentPrefs

/**
 * 开机与升级后的自启接收器。
 *
 * 只有用户点过"启动上报"（reportingEnabled 为 true）才会拉起服务，
 * 避免装了应用就被强制常驻喵。
 */
class BootReceiver : BroadcastReceiver() {

    /** 收到开机或升级广播后按需拉起前台服务喵。 */
    override fun onReceive(context: Context, intent: Intent?) {
        // 读取动作名喵
        val action = intent?.action ?: return
        // 喵~防御：只处理开机/升级/快启这三类广播，其它一概忽略喵
        if (action !in BOOT_ACTIONS) return
        // 读取配置喵
        val prefs = AgentPrefs(context)
        // 喵~防御：用户没开启上报就不拉起，尊重用户意愿喵
        if (!prefs.reportingEnabled) {
            Log.i(TAG, "开机自启：用户未开启上报，跳过")
            return
        }
        // 喵~防御：配置不完整时拉起也没用，直接跳过喵
        if (!prefs.isConfigured()) {
            Log.i(TAG, "开机自启：配置不完整，跳过")
            return
        }
        // 顺手把保活任务排上，ROM 吞掉自启时它还能兜住喵
        KeepAliveJob.schedule(context)
        try {
            // 启动前台服务喵
            val serviceIntent = Intent(context, UploadService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
            // 写进环形日志，主人下次打开界面能看到这次自启有没有生效喵
            AgentLog.info("开机自启：已拉起上报服务（${action.substringAfterLast('.')}）")
            Log.i(TAG, "开机自启：已拉起上报服务")
        } catch (error: Exception) {
            // 喵~防御：Android 12 起后台启动前台服务有限制，被拒绝时记录日志即可喵
            AgentLog.warn("开机自启失败：${error.message}")
            Log.w(TAG, "开机自启服务失败：${error.message}")
        }
    }

    companion object {
        // 日志标签喵
        private const val TAG = "DeviceHub"

        // 认作"开机"的广播动作集合喵
        private val BOOT_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON",
        )
    }
}
