"""服务端的定期维护任务：归档历史数据 + 清理过期数据喵。

喵~注意：这个循环**刻意不挂在机器人上**。
以前它长在 `BotRunner` 里，结果「不接 QQ 通道的纯服务端部署」时
`main.py` 压根不会创建 BotRunner，归档和清理就永远不跑，
数据会一直涨而且日志里一个字都不打——这种静默失效最难发现喵。

现在它由 `main.py` 的 lifespan 无条件启动，跟有没有接 bot 无关喵。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import archive, db, queries
from .config import AppConfig
from .bot import users
from .db import utc_now

# 轮询周期的秒数喵
MAINTENANCE_INTERVAL_SECONDS = 3600

# 每月几号凌晨做归档喵
#
# 喵~注意：选 8 号是因为热保留期是 7 天。这时本月 1 号起的数据
# 正好还没过保（是热数据），上月整月又已经全部过保，
# 一次就能把上个月压得干干净净，中间不会出现半新半旧的月份喵。
ARCHIVE_DAY_OF_MONTH = 8

# 日志喵
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaintenanceResult:
    """一次维护的成果喵。"""

    # 归档了多少个块喵
    archived_blocks: int
    # 归档了多少行原始数据喵
    archived_rows: int
    # 归档后压缩块的总字节数喵
    archived_bytes: int
    # 各表清理掉的行数喵
    deleted: dict[str, int]


def is_archive_window(moment: datetime) -> bool:
    """判断此刻是否该做归档喵。

    输入：当前时刻。
    输出：每月 8 号当天返回 True，其它日子 False。
    边界：只看日期，不看具体几点——轮询每小时一次，8 号那天总会命中喵。
    """
    return moment.day == ARCHIVE_DAY_OF_MONTH


def prune_once(config: AppConfig) -> dict[str, int]:
    """只做清理，不动归档喵。

    输入：服务端配置。
    输出：各表删除行数。
    边界：数据库出错时异常向上抛，由调用方决定怎么记日志喵。
    """
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 清理超过保留期的数据喵
        deleted = queries.prune_expired(
            connection,
            detail_days=config.retention.detail_days,
            aggregate_days=config.retention.aggregate_days,
        )
        # 喵~注意：发言人名单也按明细保留期清理，不然会无限长喵
        stale_cutoff = db.days_ago_text(config.retention.detail_days)
        deleted["bot_seen_users"] = users.prune_seen_users(connection, stale_cutoff)
        return deleted
    finally:
        # 关闭连接喵
        connection.close()


def archive_once(config: AppConfig, now: datetime | None = None) -> archive.ArchiveResult:
    """只做归档，不动清理喵。

    输入：服务端配置、可选的基准时刻（测试用）。
    输出：ArchiveResult。
    边界：数据库出错时异常向上抛，由调用方决定怎么记日志喵。

    喵~注意：顺序上必须先归档后清理。先清理的话，超过明细保留期的行
    会被直接删掉，永远等不到归档，那就真的丢数据了喵。
    """
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 把整月都过完的数据压进归档块喵
        return archive.archive_cold_rows(connection, hot_days=archive.DEFAULT_HOT_DAYS, now=now)
    finally:
        # 关闭连接喵
        connection.close()


def run_once(config: AppConfig, include_archive: bool = True) -> MaintenanceResult:
    """跑一次维护：先归档、再清理喵。

    输入：服务端配置、是否顺带归档。
    输出：MaintenanceResult。
    边界：数据库出错时异常向上抛，由调用方决定是记日志还是重试喵。
    """
    # 归档结果先占个位喵
    archived = archive.ArchiveResult(blocks=0, rows=0, bytes_written=0)
    # 需要归档就先归档喵
    if include_archive:
        archived = archive_once(config)
    # 再清理喵
    deleted = prune_once(config)
    return MaintenanceResult(
        archived_blocks=archived.blocks,
        archived_rows=archived.rows,
        archived_bytes=archived.bytes_written,
        deleted=deleted,
    )


def log_result(result: MaintenanceResult) -> None:
    """把一次维护的结果写进日志喵。"""
    # 归档有内容才记，避免每小时刷一条空的喵
    if result.archived_rows:
        LOGGER.info(
            "归档历史数据：%s 个块，%s 行，压缩后 %.1f MB",
            result.archived_blocks,
            result.archived_rows,
            result.archived_bytes / 1024 / 1024,
        )
    # 喵~注意：四张表都要打出来。以前日志只打三项，
    # window_samples 漏了清理也看不出来，白白涨了几十 MB 都没人发现喵
    LOGGER.info(
        "清理过期数据：原始上报 %s 条，窗口快照 %s 条，使用时长 %s 条，电量 %s 条",
        result.deleted.get("reports", 0),
        result.deleted.get("window_samples", 0),
        result.deleted.get("usage_samples", 0),
        result.deleted.get("battery_samples", 0),
    )


async def maintenance_loop(
    config: AppConfig,
    interval_seconds: int = MAINTENANCE_INTERVAL_SECONDS,
    clock=None,
) -> None:
    """定期跑维护，直到被取消喵。

    输入：配置、轮询间隔秒数、可选的时钟函数（测试用）。
    输出：无（长驻协程）。
    边界：单次失败只记警告，不退出循环；被取消时正常结束喵。

    喵~注意：这里用「每小时醒一次、判断该不该干活」而不是「一觉睡到下个月 8 号」。
    睡整月的话，进程中途重启就错过了这一轮，而且授时校正后
    原来那个 sleep 时长也跟着失真喵。
    """
    # 喵~防御：轮询间隔太短会白耗 CPU，下限给一分钟喵
    safe_interval = max(60, int(interval_seconds))
    # 造时钟，测试可以注入假的喵
    moment_clock = clock or utc_now
    # 记下上次归档是哪个「年-月」，同一个月只归档一次喵
    last_archive_key: str | None = None
    while True:
        # 先等一个周期再干活，避免刚启动就抢数据库喵
        await asyncio.sleep(safe_interval)
        try:
            # 现在几点喵
            now = moment_clock()
            # 这一轮的归档结果先占个位喵
            archived = archive.ArchiveResult(blocks=0, rows=0, bytes_written=0)
            # 喵~注意：归档必须排在清理前面！反过来的话，超过明细保留期的行
            # 会先被 prune_expired 直接删掉，永远等不到归档，那就真丢数据了喵
            if is_archive_window(now):
                # 这个月的标记喵
                window_key = f"{now.year:04d}-{now.month:02d}"
                # 同一个月只归档一次，重启后也会因为块已存在而自动跳过喵
                if last_archive_key != window_key:
                    # 喵~注意：把这一轮的时刻传下去，别让归档自己再取一次时钟，
                    # 否则判断窗口用的时间和归档用的时间可能差到跨天喵
                    archived = await asyncio.to_thread(archive_once, config, now)
                    # 记下这个月已经跑过喵
                    last_archive_key = window_key
            # 归档完再清理，这样超期数据先入库、再删原始行喵
            deleted = await asyncio.to_thread(prune_once, config)
            # 记日志喵
            log_result(
                MaintenanceResult(
                    archived_blocks=archived.blocks,
                    archived_rows=archived.rows,
                    archived_bytes=archived.bytes_written,
                    deleted=deleted,
                )
            )
        except sqlite3.Error as maintenance_error:
            # 喵~防御：维护失败不影响服务，下一个周期继续尝试喵
            LOGGER.warning("定期维护失败：%s", maintenance_error)
