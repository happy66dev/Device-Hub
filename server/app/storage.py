"""存储占用统计与历史清理。

自用场景下历史不自动删，但库会一直长，所以给设置页提供两个能力：
看清各表占了多少行、按天数手动清理喵。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import archive, db, queries
from .db import to_utc_text, utc_now

# 模块日志喵
LOGGER = logging.getLogger(__name__)

# 生成每日使用时长汇总时用的时区偏移喵
# 喵~注意：和接口默认值保持一致，否则汇总表里的日期和看板请求的日期会错开一天喵
DAILY_USAGE_TZ_MINUTES = 480

# 需要「先归档、再删」的两张明细表喵
#
# 喵~注意：这两张表不进「按天数硬删」的路径，而是交给归档压缩。
# 硬删 = 用户点一下清理就永久丢数据，归档还没来得及压，不可恢复喵
_ARCHIVABLE_TABLES: frozenset[str] = frozenset({"reports", "window_samples"})

# 允许清理的表，以及各自的时间列喵
#
# 喵~注意：`reports` 有两列时间（reported_at 客户端、received_at 服务端），
# 归档和查询都按 `received_at` 切分，清理必须跟着用同一列，
# 否则两边口径不一致，客户端时钟一偏就会删掉不该删的行喵
CLEANABLE_TABLES: dict[str, str] = {
    "usage_samples": "sampled_at",
    "battery_samples": "sampled_at",
    "window_samples": "reported_at",
    "reports": "received_at",
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


def cleanup(
    connection: sqlite3.Connection,
    before_days: int,
    targets: tuple[str, ...],
) -> dict[str, int]:
    """删除早于 N 天的历史数据，能归档的先归档再删喵。

    输入：连接、保留天数、目标表。
    输出：各表删除行数。
    边界：只处理时间列早于阈值的行，绝不动最近的数据喵。

    喵~注意：这里**不是**简单 DELETE。`reports` 和 `window_samples` 会先压进
    归档块，再删已归档的行——和自动维护走同一套语义。
    以前这里是硬删，用户点一下设置页的清理就把明细永久丢了（归档还没来得及压），
    时间轴的历史跟着消失，而且不可恢复喵。

    `usage_samples` 删之前会先固化进 `daily_usage` 日汇总，
    保证统计页的一年视图不会因为清理而出现空洞喵。

    喵~注意：明细表的删除范围由**归档**决定（只压整月已过完的月份），
    不是按 before_days 精确切。这是刻意的——归档必须按整月分块，
    否则同一个月会被切成好几段，块内的数据也不连续喵。

    喵~注意：聚合表的截止时刻对齐到本地日零点，理由同 `queries.prune_expired`。
    不对齐的话，边界那天只会删掉前半段明细，而那天已经按整天
    算进 `daily_usage` 了，下次重算就会用半截明细把真值改小喵。
    """
    # 计算阈值，对齐到本地日零点喵
    base_moment = utc_now()
    threshold = db.local_day_start_text(
        base_moment - timedelta(days=before_days), DAILY_USAGE_TZ_MINUTES
    )
    # 结果字典喵
    deleted: dict[str, int] = {}
    # 归档前后各表行数，用来精确统计「这张表被删了多少」喵
    # 喵~注意：归档一次会把两张明细表一起处理，所以必须在**归档之前**
    # 把两张表的行数都记下来，事后再各算差值，否则后处理的那张表
    # 会显示 0 行（它的数据已经在上一张表触发归档时被删掉了）喵
    archivable_in_targets = [t for t in targets if t in _ARCHIVABLE_TABLES]
    rows_before: dict[str, int] = {}
    for table in archivable_in_targets:
        rows_before[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    # 喵~注意：归档的 hot_days 必须用用户选的天数，不能写死 0喵。
    # 写死的话「保留 365 天」也会把上个月压掉，清理的保留期参数就成了摆设喵
    # 喵~注意：还要把 `targets` 传下去。归档默认两张明细表一起处理，
    # 不看 targets 的话「只勾了原始上报」会连窗口快照一起清掉，
    # 用户没勾的表被删了，而接口返回的 deleted 里又没有它，等于静默丢数据喵
    if archivable_in_targets and any(rows_before.values()):
        archive.archive_cold_rows(
            connection, hot_days=before_days, now=None, tables=archivable_in_targets
        )
    # 时间列按清理阈值切喵
    for table in targets:
        time_column = CLEANABLE_TABLES[table]
        # 喵~注意：明细表的删除已经由归档完成了，这里只核算行数喵
        if table in _ARCHIVABLE_TABLES:
            after = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            deleted[table] = max(0, rows_before.get(table, after) - after)
            continue
        # 聚合表直接按天数删，但使用时长要先固化汇总喵
        if table == "usage_samples":
            _backfill_daily_usage(connection, threshold, time_column)
        # 执行删除喵
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE {time_column} < ?", (threshold,)
        )
        deleted[table] = int(cursor.rowcount if cursor.rowcount > 0 else 0)
    # 删完提交喵
    connection.commit()
    # 喵~注意：VACUUM 不能在事务里跑，必须在 commit 之后喵
    # 喵~防御：VACUUM 撞上并发写入会抛 `database is locked`。
    # 这时候数据**已经删完并提交了**，再把异常抛给调用方，
    # 用户看到的就是「清理失败」——但数据其实早没了，谁也说不清到底成没成。
    # 所以这里只把「没回收成磁盘」当降级处理，绝不假装整体失败喵
    _vacuum_quietly(connection)
    return deleted


def _vacuum_quietly(connection: sqlite3.Connection) -> None:
    """尽力回收磁盘空间，失败时只记日志、不抛异常喵。

    输入：数据库连接。
    输出：无。
    边界：只吞 `sqlite3.OperationalError`（锁/忙），其它异常照旧往外抛喵。
    """
    # 喵~注意：VACUUM 在「有别的连接正在写」时必然失败，重试几次能覆盖
    # 维护和上报恰好撞车的那一小段时间喵
    for attempt in range(3):
        try:
            connection.execute("VACUUM")
            connection.commit()
            return
        except sqlite3.OperationalError as error:
            # 还在忙就退一步再试，不要立刻放弃喵
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            # 喵~注意：这里不能抛，删除已经提交了，抛出去会让用户误判喵
            LOGGER.info("暂时无法回收磁盘空间（有写入正在进行）：%s", error)


def _backfill_daily_usage(connection: sqlite3.Connection, threshold: str, time_column: str) -> None:
    """删使用时长之前，先把它固化进每日汇总表喵。

    输入：连接、阈值文本、时间列名。
    输出：无。
    边界：没有任何明细时直接返回，不会白建表喵。

    喵~注意：回溯天数必须按**库里最老的那条明细**算，不能按阈值算。
    按阈值算的话，即将被删的那些（比阈值还老）正好落在窗口外，
    汇总永远是空的——这正是第一版写错的地方喵。
    """
    # 取库里最老那条的时间喵
    row = connection.execute(f"SELECT MIN({time_column}) FROM usage_samples").fetchone()
    oldest = row[0] if row else None
    # 喵~防御：没有明细就不用汇总喵
    if not oldest:
        return
    # 从最老那条到今天的天数，多留 7 天余量喵
    window_days = _days_since(str(oldest)) + 7
    queries.rebuild_daily_usage(
        connection, tz_offset_minutes=DAILY_USAGE_TZ_MINUTES, days=window_days
    )


def _days_since(threshold: str) -> int:
    """算阈值文本距今有多少天，算不出来时给个保守值喵。"""
    # 解析阈值喵
    try:
        moment = datetime.strptime(threshold, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        # 喵~防御：格式对不上就按一年算，宁可多算喵
        return 365
    # 差值天数喵
    return max(1, int((utc_now() - moment).total_seconds() // 86400))


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


