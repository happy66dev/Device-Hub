// app 模块构建脚本：只依赖 Kotlin 标准库与 JUnit，尽量不引入第三方库喵
plugins {
    // Android 应用插件喵
    id("com.android.application")
    // Kotlin 支持喵
    id("org.jetbrains.kotlin.android")
}

android {
    // 包名遵循规则 14：io.github.happy66dev.<模块名> 喵
    namespace = "io.github.happy66dev.devicehub"
    // 编译用的 SDK 版本喵
    compileSdk = 34

    defaultConfig {
        // 应用 ID，与包名保持一致喵
        applicationId = "io.github.happy66dev.devicehub"
        // 最低支持 Android 8.0，前台服务与 java.time 都可用喵
        minSdk = 26
        // 目标 SDK 版本喵
        targetSdk = 34
        // 版本号与版本名喵
        versionCode = 6
        versionName = "0.5.1"
    }

    buildTypes {
        release {
            // 先不开混淆，方便主人排查崩溃堆栈喵
            isMinifyEnabled = false
        }
    }

    compileOptions {
        // 使用 Java 17 语法与字节码喵
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        // Kotlin 目标字节码版本喵
        jvmTarget = "17"
    }

    testOptions {
        // 单元测试里调用 Android API 时返回默认值而不是抛异常喵
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    // 只用于 JVM 单元测试，不打进 APK 喵
    testImplementation("junit:junit:4.13.2")
}
