"""上报体压缩编解码的单元测试喵。"""

from __future__ import annotations

import json
import sqlite3
import zlib

import pytest

from app.payload_codec import decode_payload, encode_payload, is_compressed


def test_encode_decode_roundtrip() -> None:
    """压缩再解压要能完整还原所有字段喵。"""
    # 造一份带各种类型字段的上报体喵
    body = {
        "afk": True,
        "afk_since": "2026-11-01T00:00:00Z",
        "active_since": None,
        "device_id": "win-test-0001",
        "role": "workstation",
        "hardware": {"cpu": "i7-9700", "mem": 32},
        "usage_delta": [{"app": "Code", "package": "code.exe", "seconds": 60}],
        "中文键": "中文值",
    }
    # 往返喵
    assert decode_payload(encode_payload(body)) == body


def test_encode_drops_no_fields_unless_caller_does() -> None:
    """编解码本身不丢字段，去重是调用方的事喵。"""
    # 带 open_windows 也必须原样回来喵
    body = {"open_windows": [{"app": "cmd", "title": "命令行"}]}
    assert decode_payload(encode_payload(body)) == body


def test_decode_reads_legacy_plain_json() -> None:
    """老库里存的明文 JSON 必须还能读，不能要求迁移喵。"""
    # 明文文本喵
    assert decode_payload('{"afk": false}') == {"afk": False}
    # 明文字节喵
    assert decode_payload(b'{"afk": true}') == {"afk": True}


def test_decode_reads_compressed_blob() -> None:
    """压缩后的 BLOB 要能解出来喵。"""
    # 先压一份喵
    packed = encode_payload({"afk": True})
    assert decode_payload(packed) == {"afk": True}
    # bytearray 也要支持喵
    assert decode_payload(bytearray(packed)) == {"afk": True}


def test_is_compressed_distinguishes_formats() -> None:
    """新老格式要能区分开喵。"""
    # 压缩过的是压缩格式喵
    assert is_compressed(encode_payload({"afk": True})) is True
    # 明文不是喵
    assert is_compressed('{"afk": true}') is False
    assert is_compressed(b'{"afk": true}') is False
    # 空值不算压缩喵
    assert is_compressed(b"") is False


def test_decode_rejects_broken_data() -> None:
    """坏数据要抛 ValueError，让调用方走兜底喵。"""
    # 空字节喵
    with pytest.raises(ValueError):
        decode_payload(b"")
    # 不是 JSON 的文本喵
    with pytest.raises(ValueError):
        decode_payload("这不是 JSON")
    # JSON 但不是对象喵
    with pytest.raises(ValueError):
        decode_payload("[1, 2, 3]")


def test_decode_does_not_confuse_plain_json_with_zlib() -> None:
    """明文 JSON 的首字节不能被误判成 zlib 头喵。

    喵~注意：明文必须以 `{` (0x7B) 开头，低 4 位是 0xB；
    zlib 的 deflate 方法位是 0x8，两者不会撞上喵。
    """
    # 造一份很短的明文，首字节就是 `{`喵
    for text in ('{"a": 1}', '{}', '{"afk": false, "x": "中文"}'):
        assert is_compressed(text) is False
        assert decode_payload(text) == json.loads(text)


def test_payload_stored_as_blob_in_text_column() -> None:
    """BLOB 能存进声明为 TEXT 的列并原样取回喵。"""
    # 建个内存库喵
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE t (payload_json TEXT NOT NULL)")
        # 写压缩后的字节喵
        body = {"afk": True, "device_id": "win-1"}
        connection.execute("INSERT INTO t VALUES (?)", (encode_payload(body),))
        connection.commit()
        # 取回来喵
        row = connection.execute("SELECT payload_json, typeof(payload_json) FROM t").fetchone()
        # 喵~防御：SQLite 的列类型是"亲和性"，BLOB 存进去还是 BLOB 喵
        assert row[1] == "blob"
        assert decode_payload(row[0]) == body
    finally:
        connection.close()


def test_compression_actually_shrinks_realistic_payload() -> None:
    """真实形状的上报体压缩后要明显变小喵。"""
    # 造一份接近线上平均体积（约 1600 字节）的上报体喵
    body = {
        "device_id": "win-v77u51rt5c3-de5b",
        "platform": "windows",
        "display_name": "服务器RDP",
        "role": "server",
        "afk": False,
        "afk_since": None,
        "active_since": "2026-11-01T00:00:00Z",
        "hardware": {"cpu": "Intel Core i7-9700", "memory_gb": 32, "disk": "512GB SSD"},
        "current_app": {"app": "Code", "package": "code.exe", "title": "app.js - device-hub"},
        "usage_delta": [{"app": "Code", "package": "code.exe", "seconds": 10} for _ in range(5)],
        "reported_at": "2026-11-01T00:00:00Z",
    }
    # 明文长度喵
    plain_size = len(json.dumps(body, ensure_ascii=False))
    # 压缩后长度喵
    packed_size = len(encode_payload(body))
    # 喵~注意：至少省一半，否则这个改动没意义喵
    assert packed_size < plain_size * 0.6, f"压缩率不够：{packed_size} vs {plain_size}"


def test_zlib_error_propagates_for_corrupt_stream() -> None:
    """压缩流被截断时要抛 zlib.error，调用方需要能捕获喵。"""
    # 正常压缩后砍掉一半喵
    packed = encode_payload({"afk": True, "data": "x" * 500})
    truncated = packed[: len(packed) // 2]
    # 首字节仍是 zlib 头，会走解压分支然后失败喵
    assert is_compressed(truncated) is True
    with pytest.raises(zlib.error):
        decode_payload(truncated)
