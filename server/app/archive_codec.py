"""历史数据归档的编解码喵。

喵~注意：归档块里 **不是 JSON**，而是一种极简的行文本格式。
原因是 `window_samples` 一天十万行，JSON 的解析开销比解压本身还大
（实测整天解析 489 ms，紧凑行格式只要 162 ms，反而比直接查 SQL 还快）喵。

行格式（字段之间用 0x1F 分隔，行之间用 0x1E 分隔）：

    心跳块： 时间 0x1F afk 0x1F afk_since 0x1F active_since 0x1F 设备ID
    窗口块： 时间 0x1F 应用 0x1F 包名 0x1F 标题 0x1F minimized 0x1F foreground

时间放行首是有意为之：查询时可以直接用字节前缀筛掉整行，
连切字段都省了喵。
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable

# 字段分隔符，正文里不可能出现（控制字符）喵
FIELD_SEP = "\x1f"
# 行分隔符喵
LINE_SEP = "\x1e"
# 归档块编码名，写进 archives.codec 列，以后换算法好认喵
CODEC_ZLIB = "zlib"
# 压缩级别喵
COMPRESS_LEVEL = 6

# 块类型：心跳与窗口采样分别归档喵
KIND_HEARTBEATS = "heartbeats"
KIND_WINDOWS = "windows"

# 时间字符串长度（YYYY-MM-DDTHH:MM:SSZ 共 20 字符）喵
TIME_TEXT_LENGTH = 20


def _clean(value: object) -> str:
    """把任意值转成不含分隔符的文本，防止把块结构撑破喵。"""
    # 空值统一成空串喵
    text = "" if value is None else str(value)
    # 喵~防御：正文里万一真出现分隔符，替换成空格，否则切分会错位喵
    return text.replace(FIELD_SEP, " ").replace(LINE_SEP, " ")


def _flag(value: object) -> str:
    """布尔值存成单字符，比 true/false 省一半字节喵。"""
    return "1" if value else "0"


def encode_heartbeats(rows: Iterable[tuple[str, bool, str, str, str, int]]) -> bytes:
    """把心跳行压成归档块喵。

    输入：可迭代的 (时间, afk, afk_since, active_since, device_id, 原始 rowid) 元组。
    输出：zlib 压缩后的字节串。
    边界：空输入会压出一个空块，调用方应避免归档空数据喵。

    喵~注意：必须带原始 rowid。同一设备同一时刻可能有多条上报，
    查询按 `(received_at, id)` 排序，不存 rowid 归档后顺序会漂，
    AFK 标记就会错位喵。
    """
    # 逐行拼成文本喵
    lines = [
        FIELD_SEP.join(
            (
                _clean(moment),
                _flag(afk),
                _clean(afk_since),
                _clean(active_since),
                _clean(device_id),
                _clean(row_id),
            )
        )
        for moment, afk, afk_since, active_since, device_id, row_id in rows
    ]
    # 拼成一块再压缩，跨行冗余才能被吃掉喵
    return zlib.compress(LINE_SEP.join(lines).encode("utf-8"), COMPRESS_LEVEL)


def encode_windows(rows: Iterable[tuple[str, str, str, str, bool, bool, int]]) -> bytes:
    """把窗口采样压成归档块喵。

    输入：可迭代的 (时间, 应用, 包名, 标题, minimized, foreground, 原始 rowid) 元组。
    输出：zlib 压缩后的字节串。
    边界：标题里的分隔符会被替换掉，不影响切分喵。

    喵~注意：必须带上原始 rowid。同一时刻同一应用可能有多个窗口标题，
    `ORDER BY app_name, reported_at` 对并列行的先后由 rowid 决定，
    不存 rowid 的话归档后排序会漂，区间合并结果就和归档前对不上了喵。
    """
    # 逐行拼文本喵
    lines = [
        FIELD_SEP.join(
            (
                _clean(moment),
                _clean(app_name),
                _clean(package),
                _clean(title),
                _flag(minimized),
                _flag(foreground),
                _clean(row_id),
            )
        )
        for moment, app_name, package, title, minimized, foreground, row_id in rows
    ]
    # 压成一块喵
    return zlib.compress(LINE_SEP.join(lines).encode("utf-8"), COMPRESS_LEVEL)


def iter_lines(block: bytes) -> Iterable[bytes]:
    """解压归档块并逐行产出字节串，供上层按前缀过滤喵。"""
    # 先解压整块喵
    raw = zlib.decompress(block)
    # 喵~防御：空块解出来是空串，直接不产出任何行喵
    if not raw:
        return
    # 按行分隔符切开喵
    for line in raw.split(LINE_SEP.encode("utf-8")):
        # 跳过空行喵
        if line:
            yield line


def iter_month_prefix(block: bytes, month: str) -> Iterable[bytes]:
    """只产出属于某个月的行，避免解析无关行喵。

    输入：归档块、形如 "2026-11" 的月份。
    输出：该月的行（字节串）。
    边界：月份格式不对时按前缀匹配处理，可能产出空结果喵。
    """
    # 时间在行首，所以直接按字节前缀筛喵
    needle = month.encode("utf-8")
    for line in iter_lines(block):
        # 前 7 字节就是 YYYY-MM 喵
        if line[: len(needle)] == needle:
            yield line


def iter_day_prefix(block: bytes, date_text: str) -> Iterable[bytes]:
    """只产出属于某一天的行喵。

    输入：归档块、形如 "2026-11-01" 的日期。
    输出：该天的行（字节串）。
    边界：同上喵。
    """
    # 前 10 字节是 YYYY-MM-DD喵
    needle = date_text.encode("utf-8")
    for line in iter_lines(block):
        if line[: len(needle)] == needle:
            yield line


def decode_heartbeats(block: bytes) -> list[tuple[str, bool, str, str, str, int]]:
    """把心跳块整块解出来，返回全部元组喵。

    输出：(时间, afk, afk_since, active_since, 设备ID, 原始 rowid)。
    """
    # 结果列表喵
    records: list[tuple[str, bool, str, str, str, int]] = []
    for line in iter_lines(block):
        # 切字段喵
        parts = line.decode("utf-8").split(FIELD_SEP)
        # 喵~防御：字段数不对说明这行坏了，跳过而不是整块报错喵
        if len(parts) != 6:
            continue
        try:
            # rowid 可能被写成空串，兜底成 0 喵
            row_id = int(parts[5]) if parts[5] else 0
        except ValueError:
            # 坏 rowid 当 0，不影响其它字段喵
            row_id = 0
        records.append((parts[0], parts[1] == "1", parts[2], parts[3], parts[4], row_id))
    return records


def decode_windows(block: bytes) -> list[tuple[str, str, str, str, bool, bool, int]]:
    """把窗口块整块解出来，返回全部元组喵。

    输出：(时间, 应用, 包名, 标题, minimized, foreground, rowid)。
    """
    # 结果列表喵
    records: list[tuple[str, str, str, str, bool, bool, int]] = []
    for line in iter_lines(block):
        # 切字段喵
        parts = line.decode("utf-8").split(FIELD_SEP)
        # 字段数不对就跳过喵
        if len(parts) != 7:
            continue
        try:
            # rowid 可能被写成空串，兜底成 0 喵
            row_id = int(parts[6]) if parts[6] else 0
        except ValueError:
            # 喵~防御：坏 rowid 当 0，不影响其它字段喵
            row_id = 0
        records.append((parts[0], parts[1], parts[2], parts[3], parts[4] == "1", parts[5] == "1", row_id))
    return records
