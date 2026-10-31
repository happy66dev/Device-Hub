package io.github.happy66dev.devicehub.net

import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

/**
 * 上报客户端：只用 JDK 自带的 HttpURLConnection，不引第三方网络库。
 *
 * 为什么不用 OkHttp：只发一个 POST，省下一个依赖能少下载几十 MB 喵。
 */
class ReportClient {

    // 连接超时，单位毫秒喵
    private val connectTimeoutMillis = 10_000

    // 读取超时，单位毫秒喵
    private val readTimeoutMillis = 15_000

    /**
     * 发送一条上报。
     *
     * 输入：服务端基地址、上报口令、JSON 文本。
     * 输出：是否成功，以及给用户看的说明。
     * 边界：网络异常、超时、非 2xx 都返回失败而不是抛异常。
     */
    fun send(serverUrl: String, ingestToken: String, payloadJson: String): SendResult {
        // 喵~防御：地址为空说明没配置，直接返回可读的失败原因喵
        if (serverUrl.isBlank()) return SendResult(false, "未配置服务端地址")
        // 拼出上报接口地址，去掉结尾多余的斜杠喵
        val endpoint = serverUrl.trimEnd('/') + REPORT_PATH
        var connection: HttpURLConnection? = null
        return try {
            // 建立连接对象喵
            connection = URL(endpoint).openConnection() as HttpURLConnection
            // 设置方法与超时喵
            connection.requestMethod = "POST"
            connection.connectTimeout = connectTimeoutMillis
            connection.readTimeout = readTimeoutMillis
            // 声明请求体类型喵
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            // 带上上报口令喵
            connection.setRequestProperty(TOKEN_HEADER, ingestToken)
            // 需要写入请求体喵
            connection.doOutput = true
            // 写请求体喵
            val bodyBytes = payloadJson.toByteArray(StandardCharsets.UTF_8)
            connection.setFixedLengthStreamingMode(bodyBytes.size)
            connection.outputStream.use { outputStream: OutputStream ->
                outputStream.write(bodyBytes)
                outputStream.flush()
            }
            // 读取响应码喵
            val statusCode = connection.responseCode
            // 喵~防御：非 2xx 时把服务端返回体带回去，方便排查字段错误喵
            if (statusCode !in 200..299) {
                val errorBody = connection.errorStream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() } ?: ""
                return SendResult(false, "HTTP $statusCode $errorBody".trim())
            }
            SendResult(true, "上报成功")
        } catch (error: Exception) {
            // 喵~防御：断网、DNS 失败、超时都走这里，返回可读原因而不是崩溃喵
            SendResult(false, "网络请求失败：${error.message ?: error.javaClass.simpleName}")
        } finally {
            // 关闭连接，释放底层 socket 喵
            connection?.disconnect()
        }
    }

    /**
     * 上传一张应用图标。
     *
     * 输入：服务端基地址、口令、应用名、包名、PNG 的 base64。
     * 输出：SendResult，失败时带可读原因。
     * 边界：图标只是锦上添花，失败也不影响上报，所以不抛异常。
     */
    fun uploadIcon(serverUrl: String, ingestToken: String, app: String, pkg: String, pngBase64: String): SendResult {
        // 喵~防御：地址为空说明没配置，直接返回可读原因喵
        if (serverUrl.isBlank()) return SendResult(false, "未配置服务端地址")
        // 拼出图标接口地址喵
        val endpoint = serverUrl.trimEnd('/') + ICON_PATH
        var connection: HttpURLConnection? = null
        return try {
            // 建立连接对象喵
            connection = URL(endpoint).openConnection() as HttpURLConnection
            // 设置方法与超时喵
            connection.requestMethod = "POST"
            connection.connectTimeout = connectTimeoutMillis
            connection.readTimeout = readTimeoutMillis
            // 声明请求体类型喵
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            // 带上口令喵
            connection.setRequestProperty(TOKEN_HEADER, ingestToken)
            // 需要写请求体喵
            connection.doOutput = true
            // 拼请求体，手写 JSON 省掉一个序列化库喵
            val body = """{"app":${quote(app)},"package":${quote(pkg)},"png_base64":${quote(pngBase64)}}"""
            // 写请求体喵
            val bodyBytes = body.toByteArray(StandardCharsets.UTF_8)
            connection.setFixedLengthStreamingMode(bodyBytes.size)
            connection.outputStream.use { outputStream: OutputStream ->
                outputStream.write(bodyBytes)
                outputStream.flush()
            }
            // 喵~防御：非 2xx 时带回响应体方便排查喵
            val statusCode = connection.responseCode
            if (statusCode !in 200..299) {
                val errorBody = connection.errorStream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() } ?: ""
                return SendResult(false, "HTTP $statusCode $errorBody".trim())
            }
            SendResult(true, "图标上传成功")
        } catch (error: Exception) {
            // 喵~防御：图标失败不影响采集，返回可读原因即可喵
            SendResult(false, "图标上传失败：${error.message ?: error.javaClass.simpleName}")
        } finally {
            // 关闭连接喵
            connection?.disconnect()
        }
    }

    /** 把字符串转成 JSON 字面量，转义引号与反斜杠喵。 */
    private fun quote(value: String): String {
        // 先转义反斜杠再转义引号喵
        val escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
        // 去掉换行，JSON 里不该出现裸换行喵
        val flattened = escaped.replace("\n", " ").replace("\r", " ")
        return "\"$flattened\""
    }

    companion object {
        // 上报接口路径，与服务端保持一致喵
        private const val REPORT_PATH = "/api/v1/report"
        // 应用图标接口路径喵
        private const val ICON_PATH = "/api/v1/icons"
        // 上报口令请求头喵
        private const val TOKEN_HEADER = "X-Ingest-Token"
    }
}

/** 上报结果喵。 */
data class SendResult(val success: Boolean, val message: String)
