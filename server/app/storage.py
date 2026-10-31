"""存储占用统计与历史清理。

自用场景下历史不自动删，但库会一直长，所以给设置页提供两个能力：
看清各表占了多少行、按天数手动清理喵。
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta, timezone
from pathlib import Path

from .db import to_utc_text, utc_now

# 允许清理的表，以及各自的时间列喵
CLEANABLE_TABLES: dict[str, str] = {
    "usage_samples": "sampled_at",
    "battery_samples": "sampled_at",
    "window_samples": "reported_at",
    "reports": "reported_at",
}

# 清理天数下限，避免误操作把当天的数据删了喵
MIN_CLEANUP_DAYS = 1

# 清理天数上限，十年足够了喵
MAX_CLEANUP_DAYS = 3650


class StorageError(ValueError):
    """清理参数不合法时抛出喵。"""


def _file_size(path: Path) -> int:
    """取单个文件字节数，不存在时算 0 喵。"""
    # 喵~防御：文件可能还没生成喵
    return path.stat().st_size if path.exists() else 0


def collect_stats(connection: sqlite3.Connection, db_path: Path) -> dict[str, object]:
    """统计库文件大小与各表行数喵。

    输入：数据库连接、库文件路径。
    输出：含 db_bytes / wal_bytes / tables 的字典。
    """
    # 主库与 WAL 文件都算进去，WAL 往往占大头喵
    db_bytes = _file_size(db_path)
    wal_bytes = _file_size(db_path.with_name(db_path.name + "-wal"))
    # 逐表统计行数与时间范围喵
    tables: list[dict[str, object]] = []
    for table, time_column in CLEANABLE_TABLES.items():
        try:
            # 行数喵
            row_count = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            # 时间范围喵
            bounds = connection.execute(
                f"SELECT MIN({time_column}), MAX({time_column}) FROM {table}"
            ).fetchone()
        except sqlite3.Error:
            # 喵~防御：老库可能没有这张表，跳过就好喵
            continue
        tables.append(
            {
                "name": table,
                "rows": row_count,
                "oldest": bounds[0] or "",
                "newest": bounds[1] or "",
            }
        )
    # 汇总行数喵
    total_rows = sum(int(entry["rows"]) for entry in tables)
    return {
        "db_bytes": db_bytes,
        "wal_bytes": wal_bytes,
        "total_bytes": db_bytes + wal_bytes,
        "total_rows": total_rows,
        "tables": tables,
        "generated_at": to_utc_text(utc_now()),
    }


def parse_cleanup_request(raw: object) -> tuple[int, tuple[str, ...]]:
    """解析清理请求喵。

    输入：请求体字典，可含 before_days 与 targets。
    输出：(保留天数, 目标表元组)。
    边界：天数越界、表名不认识时抛 StorageError。
    """
    # 喵~防御：请求体必须是对象喵
    if not isinstance(raw, dict):
        raise StorageError("请求体必须是对象")
    # 解析天数喵
    try:
        before_days = int(raw.get("before_days", 30))
    except (TypeError, ValueError) as error:
        raise StorageError("before_days 必须是整数") from error
    # 喵~防御：范围检查，避免 0 天把今天的数据删了喵
    if not MIN_CLEANUP_DAYS <= before_days <= MAX_CLEANUP_DAYS:
        raise StorageError(f"before_days 必须在 {MIN_CLEANUP_DAYS}–{MAX_CLEANUP_DAYS} 之间")
    # 解析目标表喵
    raw_targets = raw.get("targets")
    if raw_targets is None:
        # 不传就清全部可清理的表喵
        return before_days, tuple(CLEANABLE_TABLES)
    if not isinstance(raw_targets, list) or not raw_targets:
        raise StorageError("targets 必须是非空数组")
    # 逐个校验表名喵
    targets: list[str] = []
    for item in raw_targets:
        name = str(item)
        if name not in CLEANABLE_TABLES:
            raise StorageError(f"不支持清理的表：{name}")
        if name not in targets:
            targets.append(name)
    return before_days, tuple(targets)


def cleanup(connection: sqlite3.Connection, before_days: int, targets: tuple[str, ...]) -> dict[str, int]:
    """删除早于 N 天的历史数据喵。

    输入：连接、保留天数、目标表。
    输出：各表删除行数。
    边界：只删时间列早于阈值的行，绝不动最近的数据喵。
    """
    # 计算阈值喵
    threshold = to_utc_text(utc_now() - timedelta(days=before_days))
    # 逐表删除喵
    deleted: dict[str, int] = {}
    for table in targets:
        time_column = CLEANABLE_TABLES[table]
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE {time_column} < ?", (threshold,)
        )
        deleted[table] = int(cursor.rowcount if cursor.rowcount > 0 else 0)
    # 删完提交喵
    connection.commit()
    # 顺手把空页回收，文件才会真的变小喵
    connection.execute("VACUUM")
    connection.commit()
    return deleted


def format_bytes(value: int) -> str:
    """把字节数格式化成人类可读文本喵。"""
    # 按 1024 进制逐级换算喵
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def cleanup_threshold_text(before_days: int) -> str:
    """给清理结果生成一条可读的时间说明喵。"""
    # 用 UTC 文本便于与库里的时间对齐喵
    threshold = utc_now() - timedelta(days=before_days)
    return threshold.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


