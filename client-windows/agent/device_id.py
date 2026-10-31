"""设备唯一标识的生成与校验。

格式：win-<主机名小写>-<4 位十六进制>
例：win-9700x-1a2b
这样在 QQ 群里输入 /设备 win-9700 就能前缀匹配到本机喵。
"""

from __future__ import annotations

import re
import secrets
import socket

# 设备 ID 允许的字符集，必须与服务端 models.py 里的规则一致喵
DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 主机名里不允许出现的字符，统一替换成短横线喵
INVALID_HOSTNAME_CHARS = re.compile(r"[^a-z0-9]+")


def sanitize_hostname(hostname: str) -> str:
    """把主机名清洗成可用于设备 ID 的形式喵。

    输入：原始主机名，可能包含中文、空格、大写字母。
    输出：小写、仅含小写字母数字与短横线的字符串。
    边界：清洗后为空时返回 "windows"，保证 ID 合法喵。
    """
    # 喵~防御：空主机名没有可用信息喵
    if not hostname:
        return "windows"
    # 转小写并把非法字符替换成短横线喵
    cleaned = INVALID_HOSTNAME_CHARS.sub("-", hostname.strip().lower())
    # 去掉首尾短横线喵
    cleaned = cleaned.strip("-")
    # 喵~防御：主机名本身常以 win- 开头，去掉它避免出现 win-win-xxx 这种重复前缀喵
    if cleaned.startswith("win-"):
        cleaned = cleaned[len("win-") :].strip("-")
    # 喵~防御：全中文主机名清洗后可能为空，用固定前缀兜底喵
    if not cleaned:
        return "windows"
    # 限制长度，给随机后缀留空间喵
    return cleaned[:40]


def generate_device_id(hostname: str | None = None, suffix: str | None = None) -> str:
    """生成一个新的设备 ID 喵。

    输入：可选主机名、可选 4 位随机后缀（测试用）。
    输出：形如 win-9700x-1a2b 的字符串。
    边界：生成结果一定满足 DEVICE_ID_PATTERN 喵。
    """
    # 主机名缺省取当前机器名喵
    raw_hostname = hostname if hostname is not None else socket.gethostname()
    # 清洗主机名喵
    safe_hostname = sanitize_hostname(raw_hostname)
    # 后缀缺省用 2 字节随机数，即 4 位十六进制喵
    safe_suffix = suffix if suffix is not None else secrets.token_hex(2)
    # 拼装设备 ID 喵
    return f"win-{safe_hostname}-{safe_suffix}"


def ensure_device_id(existing: str, hostname: str | None = None) -> str:
    """沿用已有设备 ID，缺失或非法时生成新的喵。

    输入：配置里已有的设备 ID、可选主机名。
    输出：合法可用的设备 ID。
    边界：已有 ID 非法时重新生成，避免服务端拒收喵。
    """
    # 喵~防御：已有 ID 不符合规则时不能将就，必须重新生成喵
    if existing and DEVICE_ID_PATTERN.match(existing):
        return existing
    # 生成新的设备 ID 喵
    return generate_device_id(hostname=hostname)
