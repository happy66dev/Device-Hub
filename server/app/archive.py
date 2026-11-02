"""把超出热保留期的历史数据压成月块喵。

喵~注意：归档是「换个存法」，不是「删数据」——
原始行压进 archives 表之后才删除，数据一条不少，解压就能完整还原喵。

设计要点：
1. 按 **(设备, 月份, 类型)** 分块，块数随月份增长，不会爆炸喵
2. 归档是 **幂等扫描**：每次只处理「比热窗口老、且还没归档」的行，
   停机几天再启动也能自己补上，不依赖「跨天」这个触发点喵
3. 删除和归档在同一个事务里，中途失败不会出现「删了没存」喵
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import archive_codec
from .db import to_utc_text, utc_now
from .payload_codec import decode_payload

# 默认热保留天数：这段时间内的数据保持原始行，可以 SQL 直查喵
DEFAULT_HOT_DAYS = 7


@dataclass(frozen=True)
class ArchiveResult:
    """一次归档的成果喵。"""

    # 归档了多少个块喵
    blocks: int
    # 归档了多少行原始数据喵
    rows: int
    # 归档后压缩块的总字节数喵
    bytes_written: int


def _month_of(moment_text: str) -> str:
    """从 UTC 时间文本里截出月份，形如 2026-11喵。"""
    # 前 7 个字符就是年月喵
    return moment_text[:7]


def _month_bounds(month: str) -> tuple[str, str]:
    """给一个月份算出它的起止 UTC 文本，供分页查询用喵。"""
    # 解析年月喵
    year_text, month_text = month.split("-")
    year = int(year_text)
    month_number = int(month_text)
    # 起点是当月 1 号零点喵
    start = datetime(year, month_number, 1, tzinfo=timezone.utc)
    # 终点是下月 1 号零点喵
    if month_number == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
    return to_utc_text(start), to_utc_text(end)


def _list_months(connection: sqlite3.Connection, table: str, column: str, cutoff_date: str) -> list[tuple[str, str]]:
    """列出「整月都已经过了热保留期」的 (设备, 月份)喵。

    输入：连接、表名、时间列名、热保留期的截止日期（YYYY-MM-DD）。
    输出：(device_id, month) 列表，按月份升序。
    边界：没有可归档数据时返回空列表喵。

    喵~注意：判断的是**整月**，不是单行。这个月的最后一天 <= 截止日期才算过完。
    按单行判断的话，同一个月的块会先装一部分、以后再追加，
    那样块里是几段不连续的数据，而且重写会覆盖掉先前的内容喵。
    """
    # 喵~注意：表名和列名是代码里写死的常量，不是外部输入，可以拼进 SQL 喵
    # 月末日期用 SQLite 的日期函数算：月初 + 1 个月 - 1 天喵
    rows = connection.execute(
        f"""
        SELECT DISTINCT device_id, substr({column}, 1, 7) AS month
        FROM {table}
        WHERE date(substr({column}, 1, 7) || '-01', '+1 month', '-1 day') <= ?
        ORDER BY month ASC, device_id ASC
        """,
        (cutoff_date,),
    ).fetchall()
    # 转成元组列表喵
    return [(str(row["device_id"]), str(row["month"])) for row in rows]


def _fetch_heartbeats(
    connection: sqlite3.Connection, device_id: str, start: str, end: str
) -> list[tuple[str, bool, str, str, str, int]]:
    """取某设备某月的心跳原始行，转成归档用的元组喵。

    喵~注意：带上原始 rowid，查询时要靠它复原与 SQL 一致的并列行顺序喵。
    """
    # 喵~注意：这里必须用 decode_payload，库里可能同时有压缩和明文两种格式喵
    rows = connection.execute(
        "SELECT id, payload_json, received_at FROM reports"
        " WHERE device_id = ? AND received_at >= ? AND received_at < ?"
        " ORDER BY received_at ASC, id ASC",
        (device_id, start, end),
    ).fetchall()
    # 结果列表喵
    records: list[tuple[str, bool, str, str, str, int]] = []
    for row in rows:
        try:
            # 解出上报体喵
            body = decode_payload(row["payload_json"])
        except (TypeError, ValueError):
            # 喵~防御：坏数据也要归档，用默认值占位，绝不丢行喵
            body = {}
        records.append(
            (
                str(row["received_at"]),
                bool(body.get("afk", False)),
                str(body.get("afk_since") or ""),
                str(body.get("active_since") or ""),
                device_id,
                int(row["id"]),
            )
        )
    return records


def _fetch_windows(
    connection: sqlite3.Connection, device_id: str, start: str, end: str
) -> list[tuple[str, str, str, str, bool, bool, int]]:
    """取某设备某月的窗口采样原始行喵。

    喵~注意：带上原始 rowid，用来在归档后复原与 SQL 一致的并列行顺序喵。
    """
    rows = connection.execute(
        "SELECT id, reported_at, app_name, package, title, minimized, foreground FROM window_samples"
        " WHERE device_id = ? AND reported_at >= ? AND reported_at < ?"
        " ORDER BY reported_at ASC, app_name ASC, id ASC",
        (device_id, start, end),
    ).fetchall()
    # 转成元组列表喵
    return [
        (
            str(row["reported_at"]),
            str(row["app_name"]),
            str(row["package"] or ""),
            str(row["title"] or ""),
            bool(row["minimized"]),
            bool(row["foreground"]),
            int(row["id"]),
        )
        for row in rows
    ]


def _store_block(
    connection: sqlite3.Connection,
    device_id: str,
    kind: str,
    month: str,
    body: bytes,
    row_count: int,
) -> None:
    """把压缩块写进 archives 表，同一 (设备, 类型, 月份) 只写一次喵。

    喵~注意：这里**不能**用「row_count 累加 + body 覆盖」的 upsert。
    那样第二次归档同一个月时行数涨了但内容只剩最后一次的，
    前面归档的数据白白丢掉，是最隐蔽的一种丢数据喵。
    月份块的语义是「一个完整自然月，只写一次」，重复调用直接跳过喵。
    """
    # 已经有这个月的块就说明归档过了，直接不动喵
    existing = connection.execute(
        "SELECT 1 FROM archives WHERE device_id = ? AND kind = ? AND month = ?",
        (device_id, kind, month),
    ).fetchone()
    # 喵~防御：已存在就跳过，宁可不动也不要覆盖喵
    if existing is not None:
        return
    # 首次归档，直接插入喵
    connection.execute(
        "INSERT INTO archives (device_id, kind, month, row_count, codec, body, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (device_id, kind, month, row_count, archive_codec.CODEC_ZLIB, body, to_utc_text(utc_now())),
    )


def has_block(connection: sqlite3.Connection, device_id: str, kind: str, month: str) -> bool:
    """判断某设备某月的归档块是否已经存在喵。"""
    # 只查是否存在，不取 body，省内存喵
    row = connection.execute(
        "SELECT 1 FROM archives WHERE device_id = ? AND kind = ? AND month = ?",
        (device_id, kind, month),
    ).fetchone()
    return row is not None


def _delete_rows(
    connection: sqlite3.Connection, table: str, column: str, device_id: str, start: str, end: str
) -> int:
    """删掉已经归档成功的原始行，返回删除行数喵。"""
    # 只在归档写成功之后才调用，顺序不能反喵
    cursor = connection.execute(
        f"DELETE FROM {table} WHERE device_id = ? AND {column} >= ? AND {column} < ?",
        (device_id, start, end),
    )
    # rowcount 可能是 -1，统一成非负喵
    return cursor.rowcount if cursor.rowcount > 0 else 0


def _ensure_archive_table(connection: sqlite3.Connection) -> None:
    """确保 archives 表存在，老库没跑过迁移时也能归档喵。

    喵~注意：老库可能建于归档功能之前，`init_db` 没在它上面跑过，
    这里补一次建表，避免归档任务一上来就报 no such table 喵。
    """
    # 建表语句与 db.SCHEMA_STATEMENTS 里的定义保持一致喵
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS archives (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
            kind        TEXT NOT NULL,
            month       TEXT NOT NULL,
            row_count   INTEGER NOT NULL,
            codec       TEXT NOT NULL DEFAULT 'zlib',
            body        BLOB NOT NULL,
            created_at  TEXT NOT NULL,
            UNIQUE (device_id, kind, month)
        )
        """
    )
    # 提交，避免后续删除语句触发隐式事务问题喵
    connection.commit()


def archive_cold_rows(
    connection: sqlite3.Connection,
    hot_days: int = DEFAULT_HOT_DAYS,
    now: datetime | None = None,
    batch_months: int | None = None,
) -> ArchiveResult:
    """把已经过完的整月数据压成月块，返回归档摘要喵。

    输入：连接、热保留天数（下限）、基准时刻、可选的单次处理批数（测试用）。
    输出：ArchiveResult。
    边界：只归档「上个月及更早」的完整月份，当月永不归档；
          同一月份只会被写一次，重复跑不会重复计数也不会覆盖丢数据喵。

    喵~注意：归档范围用「now - hot_days」算截止日期，再要求**整月**都过完。
    不能用「本月 1 号 - hot_days」——那样截止日期在整个月内固定不动，
    上个月的最后几天永远迈不过门槛，那个月就永远归档不了喵。
    """
    # 喵~防御：热窗口太短会让刚写入的数据立刻被归档，下限给 1 天喵
    safe_hot_days = max(1, int(hot_days))
    # 喵~防御：老库可能还没有归档表，先补上再干活喵
    _ensure_archive_table(connection)
    # 基准时刻喵
    moment = now or utc_now()
    # 喵~注意：热保留期的截止日期。早于这一天的数据才有资格归档喵
    cutoff_date = (moment - timedelta(days=safe_hot_days)).strftime("%Y-%m-%d")
    # 累计统计喵
    blocks = 0
    archived_rows = 0
    bytes_written = 0
    # 逐张表处理喵
    for table, column, kind, fetcher, encoder in (
        ("reports", "received_at", archive_codec.KIND_HEARTBEATS, _fetch_heartbeats, archive_codec.encode_heartbeats),
        (
            "window_samples",
            "reported_at",
            archive_codec.KIND_WINDOWS,
            _fetch_windows,
            archive_codec.encode_windows,
        ),
    ):
        # 找出这张表里「整月都过完」的 (设备, 月份)喵
        targets = _list_months(connection, table, column, cutoff_date)
        # 测试时只处理前几批，方便构造断言喵
        if batch_months is not None:
            targets = targets[: max(0, int(batch_months))]
        for device_id, month in targets:
            # 喵~注意：这个月已经归档过就整块跳过，绝不能走「写块 + 删行」——
            # _store_block 会拒绝覆盖，但删行照跑的话原始数据就白丢了喵
            if has_block(connection, device_id, kind, month):
                continue
            # 算出这个月的起止时刻喵
            start, end = _month_bounds(month)
            # 取原始行喵
            records = fetcher(connection, device_id, start, end)
            # 喵~防御：没有数据就别写空块喵
            if not records:
                continue
            # 压成块喵
            body = encoder(records)
            # 喵~注意：先写块再删行，顺序反了会丢数据喵
            _store_block(connection, device_id, kind, month, body, len(records))
            # 喵~防御：块没写成功就绝不删行，宁可下次重来喵
            if not has_block(connection, device_id, kind, month):
                continue
            # 删掉已归档的原始行喵
            deleted = _delete_rows(connection, table, column, device_id, start, end)
            # 累计喵
            blocks += 1
            archived_rows += deleted
            bytes_written += len(body)
            # 每块单独提交，中途失败不会丢已经归档好的块喵
            connection.commit()
    return ArchiveResult(blocks=blocks, rows=archived_rows, bytes_written=bytes_written)


def load_heartbeat_block(
    connection: sqlite3.Connection, device_id: str, month: str
) -> bytes | None:
    """取某设备某月的心跳归档块，没有就返回 None喵。"""
    row = connection.execute(
        "SELECT body FROM archives WHERE device_id = ? AND kind = ? AND month = ?",
        (device_id, archive_codec.KIND_HEARTBEATS, month),
    ).fetchone()
    # 没有归档块就返回 None，让上层回退到原始表喵
    return bytes(row["body"]) if row is not None else None


def load_window_block(connection: sqlite3.Connection, device_id: str, month: str) -> bytes | None:
    """取某设备某月的窗口归档块，没有就返回 None喵。"""
    row = connection.execute(
        "SELECT body FROM archives WHERE device_id = ? AND kind = ? AND month = ?",
        (device_id, archive_codec.KIND_WINDOWS, month),
    ).fetchone()
    return bytes(row["body"]) if row is not None else None


def list_months_for_range(start: datetime, end: datetime) -> Iterable[str]:
    """列出 [start, end) 覆盖到哪些月份，按升序喵。"""
    # 从起点所在月开始喵
    cursor = datetime(start.year, start.month, 1, tzinfo=start.tzinfo)
    # 逐月推进喵
    while cursor < end:
        yield f"{cursor.year:04d}-{cursor.month:02d}"
        # 下个月喵
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=cursor.tzinfo)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=cursor.tzinfo)
