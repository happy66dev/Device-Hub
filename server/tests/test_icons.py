"""应用图标存取的单元测试喵。"""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from pathlib import Path

import pytest

from app import db, icons

# 一张 32x32 的纯色 PNG，用来当测试数据喵
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAL0lEQVR42u3OIQEAAAgDMOKQicS0ghg3E/Ornr2kEhAQEBAQEBAQEBAQEBAQSAceu3AkiGPmhpIAAAAASUVORK5CYII="
)


@pytest.fixture()
def connection(tmp_path: Path):
    """建一个临时库并返回连接喵。"""
    # 初始化表结构喵
    db_path = tmp_path / "icons.db"
    db.init_db(db_path)
    # 打开连接喵
    conn = db.connect(db_path)
    yield conn
    # 收尾关闭喵
    conn.close()


def test_icon_key_is_stable_and_distinct() -> None:
    """同 app+package+内容 永远同一个键，任一维度不同都要区分开喵。"""
    # 同参数两次调用结果相同，幂等喵
    assert icons.icon_key("微信", "com.tencent.mm", TINY_PNG) == icons.icon_key("微信", "com.tencent.mm", TINY_PNG)
    # 应用名不同要区分喵
    assert icons.icon_key("微信", "com.tencent.mm", TINY_PNG) != icons.icon_key("QQ", "com.tencent.mm", TINY_PNG)
    # 分隔符不能造成拼接歧义喵
    assert icons.icon_key("ab", "c", TINY_PNG) != icons.icon_key("a", "bc", TINY_PNG)


def test_icon_key_changes_with_content() -> None:
    """喵~注意：同 app+package 但图标内容不同，键必须不同，否则看板永远显示旧图喵。"""
    # 同一应用的两张不同 PNG 喵
    other_png = TINY_PNG + b"\x00"
    # 内容变了键就要变，浏览器缓存才会按新 URL 失效喵
    assert icons.icon_key("微信", "com.tencent.mm", TINY_PNG) != icons.icon_key(
        "微信", "com.tencent.mm", other_png
    )


def test_content_hash_matches_png_bytes() -> None:
    """content_hash 必须是「PNG 字节的 sha1 前 16 位」，三端口径一致喵。"""
    # 手算一遍对照喵
    expected = hashlib.sha1(TINY_PNG).hexdigest()[:16]
    # 函数结果要与手算一致喵
    assert icons.content_hash(TINY_PNG) == expected
    # 长度固定 16 位、全小写十六进制喵
    assert len(icons.content_hash(TINY_PNG)) == 16
    # 内容不同哈希不同喵
    assert icons.content_hash(TINY_PNG) != icons.content_hash(TINY_PNG + b"\x00")


def test_validate_icon_rejects_non_png() -> None:
    """不是 PNG 的字节要拒绝喵。"""
    with pytest.raises(icons.IconError):
        icons.validate_icon("微信", "com.tencent.mm", b"GIF89a-not-png")


def test_validate_icon_rejects_empty_app() -> None:
    """应用名为空要拒绝喵。"""
    with pytest.raises(icons.IconError):
        icons.validate_icon("   ", "", TINY_PNG)


def test_validate_icon_rejects_oversize() -> None:
    """超过 32KB 要拒绝喵。"""
    with pytest.raises(icons.IconError):
        icons.validate_icon("微信", "", icons.PNG_SIGNATURE + b"\x00" * (icons.MAX_ICON_BYTES + 1))


def test_save_and_load_round_trip(connection) -> None:
    """存进去能原样取出来喵。"""
    # 写入喵
    key = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 读回喵
    assert icons.load_icon(connection, key) == TINY_PNG


def test_save_overwrites_same_app(connection) -> None:
    """换图标后旧行要被删掉，同一 (app, package) 只留最新一行喵。"""
    # 先存一张喵
    first = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 再存一张不同内容的（仍是合法 PNG）喵
    second_png = TINY_PNG + b"\x00"
    second = icons.save_icon(connection, "微信", "com.tencent.mm", second_png)
    # 喵~注意：内容变了键也要变，否则前端拿旧 URL 读到浏览器缓存里的旧图喵
    assert first != second
    # 新键能取到新图喵
    assert icons.load_icon(connection, second) == second_png
    # 喵~防御：旧键必须失效，库里不留旧行喵
    assert icons.load_icon(connection, first) is None
    # 只剩一条记录喵
    assert len(icons.list_icons(connection)) == 1


def test_save_same_content_is_idempotent(connection) -> None:
    """同样的内容重复上传要幂等：键不变、还是只有一行喵。"""
    # 同一份 PNG 连传两次喵
    first = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    second = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 键相同、内容相同、只有一行喵
    assert first == second
    assert icons.load_icon(connection, first) == TINY_PNG
    assert len(icons.list_icons(connection)) == 1


def test_save_keeps_other_apps(connection) -> None:
    """换某个应用的图标不能误删别的应用的行喵。"""
    # 两个应用各存一张喵
    wechat = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    other = icons.save_icon(connection, "QQ", "com.tencent.mobileqq", TINY_PNG)
    # 只换微信的图标喵
    replaced = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG + b"\x00")
    # 微信换成新键，QQ 原样保留喵
    assert replaced != wechat
    assert icons.load_icon(connection, other) == TINY_PNG
    # 一共两行喵
    assert len(icons.list_icons(connection)) == 2


def test_load_missing_icon_returns_none(connection) -> None:
    """没有的键返回 None 喵。"""
    assert icons.load_icon(connection, "deadbeefdeadbeef") is None


def test_list_icons_reports_metadata(connection) -> None:
    """列表要带应用名、包名与内容哈希，客户端据此比对要不要重传喵。"""
    # 存一张喵
    key = icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 取列表喵
    entries = icons.list_icons(connection)
    assert entries == [
        {
            "key": key,
            "app": "微信",
            "package": "com.tencent.mm",
            # 喵~注意：content_hash 必须与实际存进去的 PNG 对得上，客户端只认它喵
            "content_hash": hashlib.sha1(TINY_PNG).hexdigest()[:16],
            "updated_at": entries[0]["updated_at"],
        }
    ]


def test_list_icons_content_hash_follows_new_icon(connection) -> None:
    """换图标后列表里的 content_hash 要跟着变成新内容的喵。"""
    # 先存一张喵
    icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 换一张不同内容的喵
    new_png = TINY_PNG + b"\x00"
    new_key = icons.save_icon(connection, "微信", "com.tencent.mm", new_png)
    # 只剩一行，且哈希与键都对应新内容喵
    entries = icons.list_icons(connection)
    assert len(entries) == 1
    assert entries[0]["content_hash"] == hashlib.sha1(new_png).hexdigest()[:16]
    assert entries[0]["key"] == new_key


def test_current_icon_keys_maps_identities(connection) -> None:
    """current_icon_keys 的映射键必须与 icon_key 的规范化规则一致喵。"""
    # 存一张，包名用大写喵
    key = icons.save_icon(connection, "Chrome", "Chrome.EXE", TINY_PNG)
    # 取映射喵
    mapping = icons.current_icon_keys(connection)
    # 用小写包名也要查得到，否则会出现「有记录却查不到」而反复重传喵
    assert mapping[("Chrome", "chrome.exe")] == key
    # 没存过的应用查不到，调用方会给空串喵
    assert ("Unknown", "unknown.exe") not in mapping


def test_icon_key_ignores_package_case() -> None:
    """包名大小写不同也要算出同一个键，否则图标对不上喵。"""
    # 采集端把 exe 名转小写，上传时可能是原始大小写喵
    assert icons.icon_key("Chrome", "Chrome.exe", TINY_PNG) == icons.icon_key("Chrome", "chrome.exe", TINY_PNG)
    # 空包名与 None 等价喵
    assert icons.icon_key("Chrome", None, TINY_PNG) == icons.icon_key("Chrome", "", TINY_PNG)
    # 包名首尾空白也要忽略喵
    assert icons.icon_key("Chrome", " chrome.exe ", TINY_PNG) == icons.icon_key("Chrome", "chrome.exe", TINY_PNG)


def test_validate_icon_rejects_tiny_png() -> None:
    """1x1 的占位图要拒收，避免看板上出现空白图标喵。"""
    # 一张 1x1 的合法 PNG 喵
    tiny = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    # 尺寸太小，应当抛 IconError 喵
    with pytest.raises(icons.IconError):
        icons.validate_icon("微信", "com.tencent.mm", tiny)


def test_png_size_reads_header() -> None:
    """能从头里读出宽高喵。"""
    assert icons.png_size(TINY_PNG) == (32, 32)
    # 喵~防御：长度不够时返回 0x0 喵
    assert icons.png_size(b"\x89PNG") == (0, 0)


def test_rekey_icons_migrates_legacy_keys(connection) -> None:
    """旧库里不含内容哈希的键，启动迁移要重建成新规则喵。"""
    # 喵~注意：手工塞一行「老规则」的键，模拟升级前的库喵
    legacy_key = hashlib.sha1("微信\x00com.tencent.mm".encode("utf-8")).hexdigest()[:16]
    connection.execute(
        "INSERT INTO app_icons (icon_key, app_name, package, png, updated_at) VALUES (?, ?, ?, ?, ?)",
        (legacy_key, "微信", "com.tencent.mm", sqlite3.Binary(TINY_PNG), "2026-01-01T00:00:00Z"),
    )
    connection.commit()
    # 跑一次迁移喵
    changed = icons.rekey_icons(connection)
    # 应该改了一行喵
    assert changed == 1
    # 新键就是按内容哈希算出来的那个喵
    expected = icons.icon_key("微信", "com.tencent.mm", TINY_PNG)
    assert expected != legacy_key
    assert icons.load_icon(connection, expected) == TINY_PNG
    # 旧键不再存在喵
    assert icons.load_icon(connection, legacy_key) is None
    # 再跑一次不再有改动，迁移是幂等的喵
    assert icons.rekey_icons(connection) == 0


def test_rekey_icons_is_noop_for_current_keys(connection) -> None:
    """用新规则存进去的行，迁移不该动它喵。"""
    # 正常存一张喵
    icons.save_icon(connection, "微信", "com.tencent.mm", TINY_PNG)
    # 迁移应当零改动喵
    assert icons.rekey_icons(connection) == 0
    # 行还在，内容没变喵
    assert len(icons.list_icons(connection)) == 1
