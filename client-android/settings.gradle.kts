// 单模块工程：只有 app 一个模块，避免多模块带来的构建复杂度喵
pluginManagement {
    // 国内镜像优先，显著减少依赖下载时间喵
    repositories {
        maven("https://maven.aliyun.com/repository/gradle-plugin")
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/central")
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    // 统一在这里声明仓库，禁止子模块各自声明，避免版本混乱喵
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/central")
        google()
        mavenCentral()
    }
}

// 工程名喵
rootProject.name = "device-hub-android"
// 引入应用模块喵
include(":app")
