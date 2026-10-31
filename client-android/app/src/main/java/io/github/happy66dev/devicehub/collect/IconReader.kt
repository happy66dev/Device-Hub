package io.github.happy66dev.devicehub.collect

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.util.Base64
import java.io.ByteArrayOutputStream

/**
 * 应用图标读取器。
 *
 * 服务端只存一张 32–48px 的 PNG，看板上按图标键取用；
 * 采集端每个包只上传一次，之后靠本地记录跳过喵。
 */
class IconReader(private val context: Context) {

    // 图标边长，48px 在高分屏下也够清楚喵
    private val iconSize = 48

    /**
     * 读取某个包的图标并转成 PNG 的 base64。
     *
     * 输入：包名，例如 com.tencent.mm。
     * 输出：base64 文本；包不存在、图标是自适应图标转换失败时返回 null。
     * 边界：任何异常都吞掉并返回 null，图标不该影响上报喵。
     */
    fun iconBase64(packageName: String): String? {
        return try {
            // 取应用图标喵
            val drawable = context.packageManager.getApplicationIcon(packageName)
            // 画到固定尺寸的位图上喵
            val bitmap = Bitmap.createBitmap(iconSize, iconSize, Bitmap.Config.ARGB_8888)
            // 建画布喵
            val canvas = Canvas(bitmap)
            // 铺满整个位图喵
            drawable.setBounds(0, 0, iconSize, iconSize)
            // 真正绘制喵
            drawable.draw(canvas)
            // 编码成 PNG 喵
            val output = ByteArrayOutputStream()
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)
            // 及时回收位图，避免占着内存喵
            bitmap.recycle()
            // 转 base64 喵
            Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
        } catch (error: Exception) {
            // 喵~防御：图标只是锦上添花，异常时返回 null 让上层跳过喵
            null
        }
    }
}
