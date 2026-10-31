package io.github.happy66dev.devicehub.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 图标内容哈希与本地记录编解码的单元测试喵。 */
class IconHashTest {

    @Test
    fun `哈希口径是 PNG 字节的 sha1 前十六位`() {
        // PNG 文件头那八个字节喵
        val pngBytes = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        // 喵~注意：这个期望值是服务端 icons.content_hash() 对同一份字节算出来的，
        // 写死在这里就是为了钉住「三端口径一致」，谁改了算法这条测试立刻红喵
        assertEquals("4caece539b039b16", IconHash.contentHash(pngBytes))
        // 长度固定 16 位喵
        assertEquals(16, IconHash.contentHash(pngBytes).length)
    }

    @Test
    fun `内容不同哈希就不同`() {
        // 两份不同字节喵
        val first = IconHash.contentHash(byteArrayOf(1, 2, 3))
        val second = IconHash.contentHash(byteArrayOf(1, 2, 4))
        // 喵~注意：换图标后哈希必须变，否则客户端永远不会重传喵
        assertNotEquals(first, second)
    }

    @Test
    fun `相同内容哈希稳定`() {
        // 同一份字节两次求哈希结果必须相同喵
        val pngBytes = ByteArray(64) { (it % 251).toByte() }
        assertEquals(IconHash.contentHash(pngBytes), IconHash.contentHash(pngBytes))
    }

    @Test
    fun `编码解码往返一致`() {
        // 造一份记录喵
        val hashes = mapOf("com.tencent.mm" to "abcdef0123456789", "com.example.app" to "0000000000000000")
        // 编码再解码喵
        val decoded = IconHash.decode(IconHash.encode(hashes))
        // 内容必须原样回来喵
        assertEquals(hashes, decoded)
    }

    @Test
    fun `空映射编码成空串`() {
        // 空记录写空串，偏好里不留垃圾喵
        assertEquals("", IconHash.encode(emptyMap()))
        // 空串解出空映射喵
        assertTrue(IconHash.decode("").isEmpty())
        assertTrue(IconHash.decode(null).isEmpty())
    }

    @Test
    fun `旧格式纯包名列表被当作没有哈希`() {
        // 喵~注意：旧版本存的是逗号分隔的纯包名，读出来哈希必须为空表示未知喵
        val decoded = IconHash.decode("com.tencent.mm,com.example.app")
        // 两个包都在，哈希为空喵
        assertEquals("", decoded["com.tencent.mm"])
        assertEquals("", decoded["com.example.app"])
        // 哈希未知时首次会重传一遍，这是可接受的迁移代价喵
        assertTrue(IconHash.needsUpload("abcdef0123456789", decoded["com.tencent.mm"]))
    }

    @Test
    fun `脏数据不会抛异常`() {
        // 多余逗号、空项、只有等号、空包名都要安全跳过喵
        val decoded = IconHash.decode(" , ,=abc,com.ok=1111222233334444,, ")
        // 只有合法的那一条留下来喵
        assertEquals(mapOf("com.ok" to "1111222233334444"), decoded)
    }

    @Test
    fun `哈希相同就跳过上传`() {
        // 本地与服务端记录一致，不该重传喵
        assertFalse(IconHash.needsUpload("abcdef0123456789", "abcdef0123456789"))
    }

    @Test
    fun `哈希不同就要重传`() {
        // 喵~注意：换图标的核心断言——哈希对不上必须重传喵
        assertTrue(IconHash.needsUpload("abcdef0123456789", "0000000000000000"))
    }

    @Test
    fun `没有记录时要上传`() {
        // 首次遇到这个包，必须传一次喵
        assertTrue(IconHash.needsUpload("abcdef0123456789", null))
        // 空串同样当作没有记录喵
        assertTrue(IconHash.needsUpload("abcdef0123456789", ""))
    }
}
