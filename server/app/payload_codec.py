"""原始上报的压缩编解码喵。

喵~注意：`reports.payload_json` 现在存的是 **zlib 压缩后的 BLOB**，不是明文 JSON。
这个模块把「存」和「取」两个方向收在一处，避免各调用点各写一套解压逻辑喵。
"""

from __future__ import annotations

import json
import zlib
from typing import Any

# 压缩级别：6 是 zlib 默认值，压缩率与速度平衡得最好喵
COMPRESS_LEVEL = 6

# 喵~注意：老数据是明文 JSON，新数据是 zlib 压缩流。
# zlib 头的第一个字节低 4 位固定是 8（表示 deflate 方法），而明文 JSON 一定以
# `{` = 0x7B 开头（低 4 位是 B），所以用低位就能无歧义区分新旧格式喵
ZLIB_DEFLATE_NIBBLE = 0x08


def _looks_compressed(byte_value: int) -> bool:
    """按 zlib 头的 deflate 方法位判断这个字节像不像压缩流喵。"""
    # 空值不可能有头喵
    if byte_value <= 0:
        return False
    # 低 4 位为 8 才是 deflate，明文 `{` 是 0xB 不会撞上喵
    return byte_value & 0x0F == ZLIB_DEFLATE_NIBBLE


def encode_payload(payload: dict[str, Any]) -> bytes:
    """把上报体压成 BLOB，顺手丢掉重复的 open_windows 喵。

    输入：上报体的字典形式（已去掉不需要存的字段由调用方决定）。
    输出：zlib 压缩后的字节串，直接写进 payload_json 列。
    边界：字典里有无法序列化的值时抛 TypeError，由调用方处理喵。
    """
    # 喵~注意：紧凑分隔符能少几个字节，几千条下来也是省的喵
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 按固定级别压缩，保证同一份数据压出来一样大喵
    return zlib.compress(text.encode("utf-8"), COMPRESS_LEVEL)


def decode_payload(stored: bytes | str) -> dict[str, Any]:
    """把库里的 payload 还原成字典，新旧格式都能读喵。

    输入：payload_json 列的原始值（可能是 bytes 也可能是老的 str）。
    输出：解析后的字典。
    边界：坏数据抛 ValueError；JSON 不是对象时也抛 ValueError喵。
    """
    # 已经是字节就拿首字节判断格式喵
    if isinstance(stored, (bytes, bytearray)):
        raw = bytes(stored)
        # 喵~防御：空值没法判断，直接报错让上层决定怎么兜底喵
        if not raw:
            raise ValueError("payload 为空")
        # 首字节像 zlib 头就说明是压缩过的新数据喵
        if _looks_compressed(raw[0]):
            raw = zlib.decompress(raw)
        # 不是压缩流就当作明文 JSON 字节喵
        text = raw.decode("utf-8")
    else:
        # 字符串：老数据是明文，也有可能是被当文本处理过的压缩流喵
        text = str(stored)
        # 喵~防御：个别驱动会把 BLOB 交给文本接口，这里顺手兼容一下喵
        if text and _looks_compressed(ord(text[0])):
            try:
                # latin-1 能无损还原每个字节喵
                text = zlib.decompress(text.encode("latin-1")).decode("utf-8")
            except (zlib.error, UnicodeDecodeError):
                # 解不开就按原文继续，交给下面的 json.loads 报错喵
                pass
    # 统一走一次 JSON 解析喵
    value = json.loads(text)
    # 喵~防御：上报体必须是对象，数组和标量都当坏数据处理喵
    if not isinstance(value, dict):
        raise ValueError("payload 不是对象")
    return value


def is_compressed(stored: bytes | str) -> bool:
    """判断这条 payload 是不是压缩格式，供统计与迁移用喵。"""
    # 字节看首字节喵
    if isinstance(stored, (bytes, bytearray)):
        return bool(stored) and _looks_compressed(bytes(stored)[0])
    # 字符串按 latin-1 的码点看首字符喵
    return bool(stored) and _looks_compressed(ord(str(stored)[0]))
