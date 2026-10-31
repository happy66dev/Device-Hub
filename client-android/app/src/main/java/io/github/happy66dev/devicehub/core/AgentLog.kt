package io.github.happy66dev.devicehub.core

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 进程内日志环形缓冲：服务往里写，界面从里读。
 *
 * 为什么不直接读 logcat：普通用户不会开 adb，
 * 界面上有个「运行日志」才看得见上报到底成没成功喵。
 * 只保留最近若干行，内存占用可控，进程退出即清空喵。
 */
object AgentLog {

    // 最多保留的行数，够看几轮上报又不至于吃内存喵
    const val MAX_LINES = 500

    // 时间戳格式，只到秒，节省宽度喵
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.US)

    // 环形缓冲本体喵
    private val lines = ArrayDeque<String>()

    /**
     * 追加一行日志。
     *
     * 输入：正文、级别字母（I/W/E）。
     * 输出：无。
     * 边界：超过上限时丢掉最旧的一行喵。
     */
    @Synchronized
    fun add(message: String, level: String = "I") {
        // 喵~防御：空消息没有信息量喵
        if (message.isBlank()) return
        // 单行太长会撑坏界面，截断一下喵
        val body = if (message.length > 300) message.take(300) + "…" else message
        // 拼上时间戳与级别喵
        lines.addLast("${timeFormat.format(Date())} $level $body")
        // 喵~防御：超出上限时丢最旧的喵
        while (lines.size > MAX_LINES) {
            lines.removeFirst()
        }
    }

    /** 记录一条普通日志喵。 */
    @Synchronized
    fun info(message: String) = add(message, "I")

    /** 记录一条警告日志喵。 */
    @Synchronized
    fun warn(message: String) = add(message, "W")

    /** 记录一条错误日志喵。 */
    @Synchronized
    fun error(message: String) = add(message, "E")

    /** 取当前全部日志的副本喵。 */
    @Synchronized
    fun snapshot(): List<String> = lines.toList()

    /** 当前日志行数，界面用来判断要不要提示"暂无日志"喵。 */
    @Synchronized
    fun size(): Int = lines.size

    /** 清空日志喵。 */
    @Synchronized
    fun clear() = lines.clear()
}
