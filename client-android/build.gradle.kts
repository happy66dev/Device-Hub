// 根构建脚本：只声明插件版本，不在这里配置模块喵
plugins {
    // Android Gradle Plugin 版本，需要 Gradle 8.9 以上喵
    id("com.android.application") version "8.7.3" apply false
    // Kotlin Android 插件版本喵
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
