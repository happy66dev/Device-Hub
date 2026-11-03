package io.github.happy66dev.devicehub.core

/**
 * 上报频率（上报间隔）的取值规则与到期判定，纯 Kotlin 实现，方便在 JVM 单元测试里直接验证。
 *
 * 口径：10 到 60 之间的整数秒，默认 60 秒一次。
 * 喵~注意：服务端心跳超时是 **60 秒**（server/app/presence.py 的 DEFAULT_HEARTBEAT_TIMEOUT_SECONDS），
 * 所以上报间隔上限只能取 60 秒——正好等于超时，容错余量其实只有「同一分钟内的抖动」，
 * 把上限放宽到 90 秒以上会稳定出现「服务还在跑、服务端却画成离线」的假空档喵。
 */
object ReportInterval {

    // 默认上报频率：60 秒一次，与旧版本写死的值保持一致喵
    const val DEFAULT_SECONDS = 60

    // 允许的最小上报频率：10 秒，再小会让服务端心跳过密且更费电喵
    const val MIN_SECONDS = 10

    // 允许的最大上报频率：60 秒，不能超过服务端心跳超时（见类注释）喵
    const val MAX_SECONDS = 60

    // 服务端心跳超时（秒），必须和 server/app/presence.py 保持一致喵
    // 喵~注意：这里原来写的是 180，与服务端实际的 60 对不上，是纯文档性错误喵
    const val HEARTBEAT_TIMEOUT_SECONDS = 60

    /**
     * 把任意整数夹到合法区间。
     *
     * 输入：用户填写的秒数，可能是负数或很大的值。
     * 输出：10 到 60 之间的值。
     * 边界：超出范围时夹到边界，不抛异常，界面用 [describe] 提示实际生效值喵。
     */
    fun normalize(seconds: Int): Int {
        // 直接夹到合法区间，非法输入一律变成边界值喵
        return seconds.coerceIn(MIN_SECONDS, MAX_SECONDS)
    }

    /**
     * 解析用户输入的文本。
     *
     * 输入：输入框里的文本，可能是空串、带空白的数字、乱码。
     * 输出：合法区间内的秒数；文本不是整数时返回 null。
     * 边界：超出范围时会夹到边界，而不是返回 null，避免用户白填喵。
     */
    fun parse(text: String?): Int? {
        // 喵~防御：空文本说明用户没填，交给调用方保持原值喵
        if (text.isNullOrBlank()) return null
        // 喵~防御：只接受纯整数文本，小数与乱码一律当非法喵
        // 喵~注意：先按 Long 解析，避免超大数字直接溢出成 null、让"大于 60 要夹取"失效喵
        val seconds = text.trim().toLongOrNull() ?: return null
        // 用 Long 版区间夹取，超过 Int 范围的输入也会落到 60 秒喵
        return seconds.coerceIn(MIN_SECONDS.toLong(), MAX_SECONDS.toLong()).toInt()
    }

    /**
     * 生成给用户看的说明文案。
     *
     * 输入：生效的秒数。
     * 输出：例如「每 60 秒上报一次」。
     */
    fun describe(seconds: Int): String {
        // 统一走夹取后的值，避免文案与实际不符喵
        return "每 ${normalize(seconds)} 秒上报一次"
    }

    /**
     * 把秒换算成毫秒。
     *
     * 输入：配置里的秒数。
     * 输出：夹取后的毫秒间隔，调用方不必再夹一次喵。
     */
    fun intervalMillis(seconds: Int): Long {
        // 先夹取再换算，避免负间隔导致"每轮都上报"喵
        return normalize(seconds) * 1000L
    }

    /**
     * 判断这一轮循环该不该上报。
     *
     * 输入：当前时刻、上次上报锚点时刻、当前生效的上报间隔（秒）、AFK 状态是否刚变化。
     * 输出：true 表示本轮应当上报。
     * 边界：
     * - 间隔由调用方每轮重新读取配置后传入，所以改完设置下一轮就按新间隔判定，不需要重启服务；
     * - AFK 状态一变强制上报，保证息屏空档的起点不会因为间隔变长而迟到；
     * - 时钟回拨（now 小于 anchor）时按"已到期"处理，宁可多发一次也不要永远不上报喵。
     */
    fun isDue(
        nowMillis: Long,
        anchorMillis: Long,
        intervalSeconds: Int,
        afkChanged: Boolean = false,
    ): Boolean {
        // 喵~注意：AFK 边界优先——判定成立就立刻发，别等下一个上报周期喵
        if (afkChanged) return true
        // 取夹取后的间隔毫秒，非法配置不会让判定失控喵
        val interval = intervalMillis(intervalSeconds)
        // 算真实流逝时间喵
        val elapsed = nowMillis - anchorMillis
        // 喵~防御：时钟回拨会算出负数，按已到期处理，避免循环卡死不上报喵
        if (elapsed < 0L) return true
        // 真实流逝时间达到间隔就到期喵
        return elapsed >= interval
    }
}
