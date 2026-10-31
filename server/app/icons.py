"""应用图标的存取。

服务端按「应用名 + 包名 + 图标内容」算短键存进 SQLite，看板用这个键拼
`<img src="/api/v1/icons/<key>?token=...">` 显示图标喵。
键里带内容哈希，所以换了图标键就会变：URL 变了浏览器缓存自然失效，
采集端也能靠 content_hash 比对出「本地图标变了，该重传」喵。
"""

from __future__ import annotations

import hashlib
import sqlite3

from .db import to_utc_text, utc_now

# 图标最小边长：小于这个尺寸基本是占位图或抠图失败喵
MIN_ICON_SIDE = 8

# 单张图标最大字节数，32x32 的 PNG 一般只有 1–3 KB 喵
MAX_ICON_BYTES = 32 * 1024

# PNG 文件头，用来挡住把别的格式硬塞进来的情况喵
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# 应用名最大长度，防止有人塞超长字符串把库撑大喵
MAX_APP_NAME_LENGTH = 128


class IconError(ValueError):
    """图标数据不合法时抛出喵。"""


def content_hash(png: bytes) -> str:
    """算图标内容的短哈希喵。

    输入：PNG 字节。
    输出：sha1 十六进制前 16 位，与安卓、Windows 采集端的口径完全一致。
    边界：空字节也算出一个合法哈希，不抛异常喵。
    """
    # 三端统一口径：对 PNG 原始字节求 sha1，取十六进制前 16 位喵
    return hashlib.sha1(png).hexdigest()[:16]


def icon_key(app: str, package: str, png: bytes) -> str:
    """用应用名、包名与图标内容算一个短键喵。

    输入：应用展示名、包名（可为空）、PNG 字节。
    输出：16 位十六进制键；内容一变键就变，浏览器缓存因此自动失效喵。
    边界：同 app+package+内容 永远得到同一个值，可安全重复调用喵。
    """
    # 包名统一小写：采集端上报的使用记录会把 exe 名转小写，图标键必须对齐喵
    normalized_package = (package or "").strip().lower()
    # 应用名按原样参与哈希，只做字符串化保证编码稳定喵
    app_bytes = str(app).encode("utf-8")
    # 包名同理转成字节喵
    package_bytes = normalized_package.encode("utf-8")
    # 喵~注意：先对 PNG 求摘要再拼进外层哈希，避免把几 KB 的图片整块复制进拼接串喵
    png_digest = hashlib.sha1(png).digest()
    # 用 \x00 分隔各段，避免「ab+c」和「a+bc」撞成同一个键喵
    return hashlib.sha1(app_bytes + b"\x00" + package_bytes + b"\x00" + png_digest).hexdigest()[:16]


def normalize_identity(app: str, package: str) -> tuple[str, str]:
    """把「应用名 + 包名」规范化成查表用的键喵。

    输入：应用名、包名（可为空）。
    输出：(应用名原样, 包名去空白并小写)。
    边界：这三个规则必须与 icon_key() 完全一致，否则会出现「有记录却查不到」喵。
    """
    # 应用名保持大小写敏感，只做字符串化喵
    # 包名去空白再小写，与 icon_key() 内部一致喵
    return str(app), (package or "").strip().lower()


def png_size(png: bytes) -> tuple[int, int]:
    """从 PNG 的 IHDR 里读出宽高喵。

    输入：PNG 字节。
    输出：(宽, 高)。
    边界：长度不够时返回 (0, 0)，由调用方当成非法处理喵。
    """
    # IHDR 固定从第 16 字节开始，宽高各 4 字节大端喵
    if len(png) < 24:
        return 0, 0
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    return width, height



def validate_icon(app: str, package: str, png: bytes) -> tuple[str, str, bytes]:
    """校验图标数据喵。

    输入：应用名、包名、PNG 字节。
    输出：清洗后的 (应用名, 包名, PNG 字节)。
    边界：应用名为空、不是 PNG、体积超限时抛 IconError。
    """
    # 应用名去空白并限长喵
    clean_app = str(app or "").strip()[:MAX_APP_NAME_LENGTH]
    if not clean_app:
        raise IconError("app 不能为空")
    # 包名同样清洗，允许为空（Windows 只有 exe 名）喵
    clean_package = str(package or "").strip()[:MAX_APP_NAME_LENGTH]
    # 喵~防御：必须是 PNG，且不能超过大小上限喵
    if not png.startswith(PNG_SIGNATURE):
        raise IconError("图标必须是 PNG 格式")
    # 喵~防御：图标尺寸太小说明抠图失败或上传了占位图，直接拒收喵
    width, height = png_size(png)
    if width < MIN_ICON_SIDE or height < MIN_ICON_SIDE:
        raise IconError(f"图标尺寸太小（{width}x{height}），至少 {MIN_ICON_SIDE}x{MIN_ICON_SIDE}")
    if len(png) > MAX_ICON_BYTES:
        raise IconError(f"图标不能超过 {MAX_ICON_BYTES // 1024} KB")
    return clean_app, clean_package, png


def save_icon(connection: sqlite3.Connection, app: str, package: str, png: bytes) -> str:
    """写入一张图标，同一 (app, package) 只保留最新一行，返回图标键喵。"""
    # 校验并清洗喵
    clean_app, clean_package, clean_png = validate_icon(app, package, png)
    # 算键，键里现在含图标内容哈希喵
    key = icon_key(clean_app, clean_package, clean_png)
    # 喵~防御：同名同包的其它行一律删掉（换图标后旧键的行、老版本算的行），只留最新一张喵
    connection.execute(
        """
        DELETE FROM app_icons
        WHERE lower(app_name) = lower(?) AND lower(package) = lower(?) AND icon_key != ?
        """,
        (clean_app, clean_package, key),
    )
    # 有则更新、无则插入；键含内容哈希，同内容重复上传天然幂等喵
    connection.execute(
        """
        INSERT INTO app_icons (icon_key, app_name, package, png, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(icon_key) DO UPDATE SET
            png = excluded.png,
            updated_at = excluded.updated_at
        """,
        (key, clean_app, clean_package, sqlite3.Binary(clean_png), to_utc_text(utc_now())),
    )
    # 提交喵
    connection.commit()
    return key


def load_icon(connection: sqlite3.Connection, key: str) -> bytes | None:
    """按图标键取 PNG 字节，没有时返回 None 喵。"""
    # 只取一列，够用就好喵
    row = connection.execute("SELECT png FROM app_icons WHERE icon_key = ?", (key,)).fetchone()
    # 喵~防御：查不到时返回 None，接口层回 404 喵
    return bytes(row["png"]) if row is not None else None


def current_icon_keys(connection: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """一次查全表，返回 (应用名, 小写包名) → 当前图标键的映射喵。

    输入：数据库连接。
    输出：字典；查不到的 (app, package) 由调用方当作「没有图标」处理。
    边界：图标表通常只有几十到几百行，一次全捞比逐个应用查库划算得多喵。
    """
    # 只取算映射需要的三列，PNG 不捞出来省内存喵
    rows = connection.execute("SELECT icon_key, app_name, package FROM app_icons").fetchall()
    # 组装映射，键的规范化规则与 icon_key() 保持一致喵
    return {
        normalize_identity(str(row["app_name"]), str(row["package"] or "")): str(row["icon_key"])
        for row in rows
    }


def list_icons(connection: sqlite3.Connection) -> list[dict[str, str]]:
    """列出已有图标的键、应用与内容哈希，供客户端比对后决定要不要重传喵。"""
    # 按应用名排序，输出稳定；png 一起取出来算 content_hash 喵
    rows = connection.execute(
        "SELECT icon_key, app_name, package, png, updated_at FROM app_icons ORDER BY app_name ASC"
    ).fetchall()
    # 转成简单字典喵
    return [
        {
            "key": str(row["icon_key"]),
            "app": str(row["app_name"]),
            "package": str(row["package"] or ""),
            # 喵~注意：content_hash 现算不落列，图标只有 1–3 KB，几十张也算得动喵
            "content_hash": content_hash(bytes(row["png"])),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def rekey_icons(connection: sqlite3.Connection) -> int:
    """把历史图标行按当前规则重算键，返回改动的行数喵。

    背景：早期版本的 icon_key 只由应用名与包名决定，不含图标内容，
    换图标后键不变、看板永远显示旧图。现在键里加了内容哈希，
    所以旧库里每一行的键都必然与新规则对不上，启动时靠这里一次性重建喵。
    """
    # 逐行检查，png 也要取出来参与重算喵
    rows = connection.execute("SELECT icon_key, app_name, package, png FROM app_icons").fetchall()
    changed = 0
    for row in rows:
        # 按当前规则重算，内容哈希用库里实际存的 PNG 喵
        expected = icon_key(str(row["app_name"]), str(row["package"] or ""), bytes(row["png"]))
        # 键一致就跳过喵
        if expected == row["icon_key"]:
            continue
        # 喵~防御：目标键可能已经被另一行占用，先删掉占位的那行再改名喵
        connection.execute("DELETE FROM app_icons WHERE icon_key = ?", (expected,))
        connection.execute(
            "UPDATE app_icons SET icon_key = ? WHERE icon_key = ?",
            (expected, row["icon_key"]),
        )
        changed += 1
    # 有改动才提交喵
    if changed:
        connection.commit()
    return changed
