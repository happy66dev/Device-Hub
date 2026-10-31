r"""端到端验证：同一个应用换图标后，键会变、旧行会被删、看板能拿到新图。

用法：在 server 目录下执行
    .\.venv\Scripts\python.exe scripts\verify_icon_change.py
"""

from __future__ import annotations

import base64
import hashlib
import sys
import zlib
from pathlib import Path

# 把 server 目录加进模块搜索路径，脚本才能 import app 喵
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app import icons

# 服务端地址与本机口令喵
BASE_URL = "http://127.0.0.1:8080"
TOKEN = "change-me-device-hub-token"

# 用来端到端验证的应用名与包名喵
APP = "图标验证小程序"
PACKAGE = "verify-icon-change.exe"


def make_png(red: int, green: int, blue: int, size: int = 16) -> bytes:
    """生成一张纯色 PNG，颜色不同则字节不同喵。

    输入：RGB 三个通道值、边长。
    输出：完整 PNG 字节。
    """
    # 每行开头一个 0 表示不过滤，后面是 RGBA 像素喵
    raw = b"".join(
        b"\x00" + bytes([red, green, blue, 255]) * size for _ in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        """拼一个 PNG 数据块喵。"""
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return (
            len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")
        )

    # IHDR：宽、高、8 位深、RGBA 喵
    ihdr = size.to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def png_hash(png: bytes) -> str:
    """按三端统一的规则算内容哈希：SHA-1 取前 16 位十六进制喵。"""
    return hashlib.sha1(png).hexdigest()[:16]


def upload(png: bytes) -> str:
    """上传一张图标，返回服务端给的图标键喵。"""
    response = httpx.post(
        f"{BASE_URL}/api/v1/icons",
        headers={"X-Ingest-Token": TOKEN},
        json={
            "app": APP,
            "package": PACKAGE,
            "png_base64": base64.b64encode(png).decode("ascii"),
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["key"]


def list_rows() -> list[dict[str, str]]:
    """取服务端图标列表里属于本验证应用的行喵。"""
    response = httpx.get(
        f"{BASE_URL}/api/v1/icons",
        headers={"X-Ingest-Token": TOKEN},
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    # 接口可能直接返回列表，也可能包一层喵
    if isinstance(rows, dict):
        rows = rows.get("icons") or rows.get("items") or []
    return [row for row in rows if row.get("app") == APP]


def fetch_icon(key: str) -> bytes:
    """按图标键取回 PNG 字节喵。"""
    response = httpx.get(
        f"{BASE_URL}/api/v1/icons/{key}",
        params={"token": TOKEN},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.content


def main() -> int:
    """跑完整验证流程，返回进程退出码喵。"""
    # 第一张：红色喵
    first = make_png(220, 40, 40)
    key_one = upload(first)
    print(f"第一次上传：key={key_one} hash={png_hash(first)}")

    # 本地算的键必须和服务端一致喵
    local_one = icons.icon_key(APP, PACKAGE, first)
    if local_one != key_one:
        print(f"  失败：本地算的键 {local_one} 与服务端 {key_one} 不一致")
        return 1

    # 第二张：蓝色，模拟应用换了图标喵
    second = make_png(40, 80, 220)
    key_two = upload(second)
    print(f"换图标后：  key={key_two} hash={png_hash(second)}")

    # 键必须变喵
    if key_one == key_two:
        print("  失败：换了图标但键没变，缓存永远不会失效")
        return 1
    print("  通过：键随内容变化")

    # 同一应用只该留一行喵
    rows = list_rows()
    if len(rows) != 1:
        print(f"  失败：期望只留 1 行，实际 {len(rows)} 行")
        return 1
    print("  通过：旧行已删除，只留最新一张")

    # 那一行的键与哈希都要对应第二张喵
    if rows[0]["key"] != key_two:
        print(f"  失败：留下的行键是 {rows[0]['key']}，期望 {key_two}")
        return 1
    content_hash = rows[0].get("content_hash")
    if content_hash != png_hash(second):
        print(f"  失败：content_hash 是 {content_hash}，期望 {png_hash(second)}")
        return 1
    print("  通过：list_icons 返回的 content_hash 与实际内容一致")

    # 取回的字节必须就是第二张喵
    served = fetch_icon(key_two)
    if served != second:
        print("  失败：取回的图片不是最新那张")
        return 1
    print("  通过：按新键取回的是新图标")

    # 旧键应该已经取不到了喵
    old_status = httpx.get(
        f"{BASE_URL}/api/v1/icons/{key_one}",
        params={"token": TOKEN},
        timeout=10.0,
    ).status_code
    print(f"  旧键状态码：{old_status}")
    if old_status != 404:
        print("  注意：旧键仍可取，说明旧行没删干净")
        return 1
    print("  通过：旧键已 404")

    # 幂等：同一份内容再传一次，键与行数都不变喵
    key_again = upload(second)
    if key_again != key_two:
        print(f"  失败：同内容重传得到了不同的键 {key_again}")
        return 1
    if len(list_rows()) != 1:
        print("  失败：同内容重传产生了多余的行")
        return 1
    print("  通过：同内容重传幂等")

    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
