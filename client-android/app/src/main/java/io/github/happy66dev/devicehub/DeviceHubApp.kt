package io.github.happy66dev.devicehub

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import io.github.happy66dev.devicehub.service.UploadService

/**
 * 应用入口。
 *
 * 只做一件事：尽早创建通知渠道，保证前台服务被系统拉起时通知能正常显示喵。
 */
class DeviceHubApp : Application() {

    /** 应用启动时创建通知渠道喵。 */
    override fun onCreate() {
        super.onCreate()
        // 喵~防御：Android 8 以下没有渠道概念喵
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        // 取通知管理器喵
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        // 已存在就不重复创建喵
        if (manager.getNotificationChannel(UploadService.CHANNEL_ID) != null) return
        // 建一个低优先级渠道，避免打扰用户喵
        val channel = NotificationChannel(
            UploadService.CHANNEL_ID,
            "设备状态上报",
            NotificationManager.IMPORTANCE_LOW,
        )
        // 渠道说明喵
        channel.description = "保持设备状态采集与上报运行"
        // 创建渠道喵
        manager.createNotificationChannel(channel)
    }
}
