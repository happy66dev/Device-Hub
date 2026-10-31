"""设备 ID 生成与校验的单元测试喵。"""

from __future__ import annotations

import re

from agent.device_id import DEVICE_ID_PATTERN, ensure_device_id, generate_device_id, sanitize_hostname


def test_generate_device_id_format() -> None:
    """生成的设备 ID 必须满足服务端的字符集要求喵。"""
    # 生成一个设备 ID 喵
    device_id = generate_device_id(hostname="My-PC", suffix="1a2b")
    # 应形如 win-my-pc-1a2b 喵
    assert device_id == "win-my-pc-1a2b"
    # 应符合正则喵
    assert DEVICE_ID_PATTERN.match(device_id)


def test_generate_device_id_random_suffix() -> None:
    """不指定后缀时应生成 4 位十六进制随机串喵。"""
    # 生成设备 ID 喵
    device_id = generate_device_id(hostname="pc")
    # 后缀应为 4 位十六进制喵
    assert re.fullmatch(r"win-pc-[0-9a-f]{4}", device_id)


def test_sanitize_chinese_hostname() -> None:
    """全中文主机名清洗后应回退为 windows 喵。"""
    # 中文主机名喵
    assert sanitize_hostname("我的电脑") == "windows"


def test_sanitize_hostname_with_symbols() -> None:
    """含空格与下划线的主机名应被替换成短横线喵。"""
    # 含非法字符的主机名喵
    assert sanitize_hostname("My PC_01") == "my-pc-01"


def test_sanitize_hostname_strips_win_prefix() -> None:
    """主机名自带 win- 前缀时不应重复拼接喵。"""
    # Windows 默认主机名风格喵
    assert sanitize_hostname("WIN-V77U51RT5C3") == "v77u51rt5c3"


def test_sanitize_empty_hostname() -> None:
    """空主机名应回退为 windows 喵。"""
    # 空字符串喵
    assert sanitize_hostname("") == "windows"


def test_ensure_device_id_keeps_valid() -> None:
    """合法设备 ID 应原样保留，保证多设备区分稳定喵。"""
    # 已有合法 ID 喵
    assert ensure_device_id("win-old-1234", hostname="newpc") == "win-old-1234"


def test_ensure_device_id_regenerates_invalid() -> None:
    """非法设备 ID 应被重新生成喵。"""
    # 含大写字母的非法 ID 喵
    regenerated = ensure_device_id("Win-Old-1234", hostname="newpc")
    # 应被替换成合法新 ID 喵
    assert regenerated != "Win-Old-1234"
    assert DEVICE_ID_PATTERN.match(regenerated)
