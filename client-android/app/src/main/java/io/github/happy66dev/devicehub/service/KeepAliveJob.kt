package io.github.happy66dev.devicehub.service

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import io.github.happy66dev.devicehub.data.AgentPrefs

/**
 * 保活任务：定期检查上报服务是否还活着，没活着就重新拉起。
 *
 * 为什么需要：国产 ROM（尤其 MIUI）常常吞掉 BOOT_COMPLETED，
 * 或者把前台服务悄悄杀掉；`setPersisted(true)` 的任务在重启后依然存在，
 * 因此它可以兜住"自启动没生效"和"服务被杀"两种情况喵。
 */
class KeepAliveJob : JobService() {

    /** 任务被触发时检查并按需拉起服务喵。 */
    override fun onStartJob(params: JobParameters?): Boolean {
        // 读取配置喵
        val prefs = AgentPrefs(this)
        // 喵~防御：用户关掉了上报就不要自作主张喵
        if (!prefs.reportingEnabled) {
            Log.i(TAG, "保活检查：用户已关闭上报，跳过")
            return false
        }
        // 喵~防御：配置不完整时拉起也没用喵
        if (!prefs.isConfigured()) {
            Log.i(TAG, "保活检查：配置不完整，跳过")
            return false
        }
        // 喵~防御：服务还在跑就不用管喵
        if (UploadService.isRunning) {
            Log.i(TAG, "保活检查：服务运行中")
            return false
        }
        try {
            // 重新拉起前台服务喵
            val intent = Intent(this, UploadService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            Log.i(TAG, "保活检查：服务不在，已重新拉起")
        } catch (error: Exception) {
            // 喵~防御：Android 12 起后台启动前台服务可能被拒绝，记录后等下一次喵
            Log.w(TAG, "保活检查：拉起服务失败 ${error.message}")
        }
        // 本次任务已同步做完，不需要再回调喵
        return false
    }

    /** 任务被系统打断时不做重试，等下一个周期喵。 */
    override fun onStopJob(params: JobParameters?): Boolean {
        // 返回 true 表示希望尽快重排喵
        return true
    }

    companion object {
        // 日志标签喵
        private const val TAG = "DeviceHub"

        // 任务 ID，固定值避免重复排队喵
        private const val JOB_ID = 4101

        // 检查周期：15 分钟（系统允许的最小周期）喵
        private const val PERIOD_MINUTES = 15

        /**
         * 排一个持久化保活任务。
         *
         * 输入：任意 Context。
         * 输出：无；任务已存在时不会重复排队。
         * 边界：Android 5.0 以下没有 JobScheduler，直接跳过喵。
         */
        fun schedule(context: Context) {
            // 喵~防御：低版本没有 JobScheduler 喵
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return
            // 取任务调度器喵
            val scheduler = context.getSystemService(Context.JOB_SCHEDULER_SERVICE) as? JobScheduler ?: return
            // 构造任务：周期执行、重启后依然保留喵
            val builder = JobInfo.Builder(JOB_ID, ComponentName(context, KeepAliveJob::class.java))
                .setPeriodic(PERIOD_MINUTES * 60_000L)
                .setPersisted(true)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_NONE)
            try {
                // 提交任务喵
                scheduler.schedule(builder.build())
            } catch (error: Exception) {
                // 喵~防御：个别 ROM 限制任务数量，失败时只记日志喵
                Log.w(TAG, "保活任务排期失败：${error.message}")
            }
        }

        /** 取消保活任务，用户主动停止上报时调用喵。 */
        fun cancel(context: Context) {
            // 喵~防御：低版本没有 JobScheduler 喵
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return
            // 取任务调度器并取消喵
            val scheduler = context.getSystemService(Context.JOB_SCHEDULER_SERVICE) as? JobScheduler ?: return
            scheduler.cancel(JOB_ID)
        }
    }
}
