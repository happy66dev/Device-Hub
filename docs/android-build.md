# Android 端构建手册

本机工具链全部放在 `D:\android-toolchain`，不污染系统环境变量，用完可直接整个目录删除。

## 1. 目录布局

```
D:\android-toolchain\
├─ jdk17\jdk-17.0.20.1+1\      JDK 17（AGP 8.x 要求 17，本机自带的是 25）
├─ gradle-8.10.2\              Gradle 发行版（不依赖 gradle wrapper 下载）
├─ gradle-home\                Gradle 缓存与依赖（相当于 GRADLE_USER_HOME）
└─ sdk\                        Android SDK
   ├─ cmdline-tools\latest\
   ├─ platforms\android-34\
   ├─ build-tools\34.0.0\
   └─ platform-tools\          adb 等
```

## 2. 每次构建前设置的环境变量

```powershell
$env:JAVA_HOME        = 'D:\android-toolchain\jdk17\jdk-17.0.20.1+1'
$env:ANDROID_HOME     = 'D:\android-toolchain\sdk'
$env:ANDROID_SDK_ROOT = 'D:\android-toolchain\sdk'
$env:GRADLE_USER_HOME = 'D:\android-toolchain\gradle-home'
```

`client-android\local.properties` 里的 `sdk.dir` 已指向 `D:/android-toolchain/sdk`，该文件不进版本库。

## 3. 常用命令

```powershell
# 只跑 JVM 单元测试（不需要连手机，最快）
& 'D:\android-toolchain\gradle-8.10.2\bin\gradle.bat' --no-daemon -p D:\device-hub\client-android :app:testDebugUnitTest

# 打 debug 包
& 'D:\android-toolchain\gradle-8.10.2\bin\gradle.bat' --no-daemon -p D:\device-hub\client-android :app:assembleDebug

# 装到手机（需要先 adb devices 能看到设备）
& 'D:\android-toolchain\sdk\platform-tools\adb.exe' install -r D:\device-hub\client-android\app\build\outputs\apk\debug\app-debug.apk
```

产物路径：`client-android\app\build\outputs\apk\debug\app-debug.apk`。

## 4. 手机上的首次配置

1. 打开应用，填写服务端地址（例如 `http://192.168.2.245:8080`）与上报口令。
2. 点「保存配置」。
3. 点「授予使用情况访问权限」，在系统列表里找到 Device Hub 并允许。
4. 点「忽略电池优化」，允许后台常驻（国产 ROM 还需在系统设置里单独开自启动）。
5. 点「开始上报」，通知栏出现常驻通知即表示前台服务已运行。

## 5. 验证上报是否成功

```powershell
# 在电脑上查看设备列表，应能看到 and- 开头的设备
Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/v1/devices' -Headers @{ 'X-Ingest-Token' = '你的token' } -UseBasicParsing
```

也可以在群里 @机器人 发 `/设备` 查看。

## 6. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 使用情况权限显示"未授予" | 只在设置页打开了总开关，没勾选本应用 | 回到列表页勾选 Device Hub |
| 上报一直是"尚未上报" | 服务端地址或口令错 | 看通知栏文案里的错误信息 |
| 通知栏没有常驻通知 | 没给通知权限（Android 13+） | 系统设置里允许通知 |
| 锁屏一段时间后没数据 | 厂商省电策略杀了服务 | 开自启动、关电池优化、加后台白名单 |
| 构建报 `sdk.dir` 相关错误 | local.properties 丢失 | 重新写入 `sdk.dir=D:/android-toolchain/sdk` |
| 构建报 JDK 版本错误 | JAVA_HOME 指向了 JDK 25 | 按第 2 节重新设置 |
