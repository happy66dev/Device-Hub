package io.github.happy66dev.devicehub.core

/**
 * 一条待上报的应用使用时长。
 *
 * 为什么把包名单独带出来：服务端排行与匹配都需要稳定的包名，
 * 应用展示名可能被系统语言改掉，包名不会喵。
 *
 * @param appName 应用展示名，例如"微信"
 * @param packageName 包名，例如 com.tencent.mm；取不到时为 null
 * @param seconds 本次新增的前台秒数，必须为正数
 */
data class UsageDelta(
    // 应用展示名喵
    val appName: String,
    // 包名，可能为空喵
    val packageName: String?,
    // 新增秒数喵
    val seconds: Long,
)
