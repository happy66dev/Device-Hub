# client-android

Android 采集端（Kotlin）。包名 `io.github.happy66dev.devicehub`，遵循规则 14。

- 设计与实现说明：[../docs/android.md](../docs/android.md)
- 构建与安装手册：[../docs/android-build.md](../docs/android-build.md)

## 快速构建

```powershell
$env:JAVA_HOME        = 'D:\android-toolchain\jdk17\jdk-17.0.20.1+1'
$env:ANDROID_HOME     = 'D:\android-toolchain\sdk'
$env:GRADLE_USER_HOME = 'D:\android-toolchain\gradle-home'
& 'D:\android-toolchain\gradle-8.10.2\bin\gradle.bat' --no-daemon -p . :app:testDebugUnitTest :app:assembleDebug
```

产物：`app\build\outputs\apk\debug\app-debug.apk`。

## 当前状态

- 编译与 30 例单元测试通过。
- 待上报数据会持久化到偏好设置，服务被杀后重启可恢复（`core/UsageStateCodec.kt`）。
- 样例上报体已被服务端 200 接收（见 `docs/TODO.md`）。
- 真机安装待主人在手机上允许 USB 安装（MIUI 策略拦截）。
