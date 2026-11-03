"""服务端的定期维护任务：归档历史数据 + 清理过期数据喵。

喵~注意：本模块由 `main.py` 的 lifespan 无条件启动，与是否接 bot 无关。
放在机器人里的话，纯服务端部署时就不会跑，而且不会有任何报错喵。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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

# 生成每日使用时长汇总时用的时区偏移喵
#
# 喵~注意：热力图的行列是「本地日历天」，这里和接口默认值保持一致，
# 否则汇总表里的日期和看板请求的日期会错开一天喵
DAILY_USAGE_TZ_MINUTES = 480

# 判断归档窗口「8 号」时用的本地时区偏移喵
#
# 喵~注意：`is_archive_window` 的 `.day` 必须按本地日算。
# 直接用 UTC 的话，东八区要等到 8 号早上 8 点才进窗口，
# 主人要的「8 号凌晨归档」会整整晚 8 小时喵
ARCHIVE_TZ_MINUTES = 480

# 每日汇总回溯窗口的保守天数：算不出最老明细时用它喵
DEFAULT_USAGE_HISTORY_DAYS = 400

# 每日汇总回溯窗口的最大天数喵
#
# 喵~注意：这个上限要和查询侧对齐。热力图接口的 `days` 上限是 740，
# `retention.aggregate_days` 还可配得更长，所以窗口必须能覆盖到那么远，
# 否则早期的明细一被删，那几天就永久没有汇总、热力图上永远是空的喵
MAX_USAGE_HISTORY_DAYS = 3660

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

    输入：当前时刻（任何时区，函数内部先换成配置的本地时区）。
    输出：本地日期是每月 8 号时 True，其它日子 False。
    边界：只看日期，不看具体几点——轮询每小时一次，8 号那天总会命中喵。

    喵~注意：必须先把时刻换算到**本地时区**再取 `.day`。
    `utc_now()` 给的是 UTC，东八区下 UTC 的 8 号其实是本地 8 号 08:00 到 9 号 08:00，
    主人要的「8 号凌晨」会整整晚 8 小时才开始，日志上的日期也跟着差一天喵。
    """
    # 换到本地时区再取日期喵
    local = moment.astimezone(timezone(timedelta(minutes=ARCHIVE_TZ_MINUTES)))
    return local.day == ARCHIVE_DAY_OF_MONTH


def _oldest_usage_days(connection: sqlite3.Connection) -> int:
    """按库里最老的一条使用明细算需要回溯多少天喵。

    输入：数据库连接。
    输出：回溯天数；没有明细时给一个保守值。
    边界：时间文本解析不了、或算出的天数不合理时退回保守值喵。

    喵~注意：`rebuild_daily_usage` 的 `days` 是**读取窗口**的宽度。
    写死一个不够大的值，比它更早的日子就永远进不了汇总表，
    明细一过保留期被删，那几天在热力图上就永久缺一块，且无法恢复喵。
    """
    # 取最老的那条明细喵
    row = connection.execute("SELECT MIN(sampled_at) FROM usage_samples").fetchone()
    oldest = row[0] if row else None
    # 喵~防御：没有任何明细时，窗口宽度无关紧要，给个保守值喵
    if not oldest:
        return DEFAULT_USAGE_HISTORY_DAYS
    # 解析时间文本喵
    try:
        moment = datetime.strptime(str(oldest), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        # 喵~防御：格式对不上就按保守值，宁可多算几天喵
        return DEFAULT_USAGE_HISTORY_DAYS
    # 从那一刻到今天的天数，多留 7 天余量盖住跨日边界喵
    span_days = int((utc_now() - moment).total_seconds() // 86400) + 7
    # 夹到 [1, 最大可查范围] 之间，避免异常数据把窗口撑爆喵
    return max(1, min(MAX_USAGE_HISTORY_DAYS, span_days))


def prune_once(config: AppConfig) -> dict[str, int]:
    """只做清理，不动归档喵。

    输入：服务端配置。
    输出：各表删除行数。
    边界：数据库出错时异常向上抛，由调用方决定怎么记日志喵。
    """
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 喵~注意：清理之前先把每日时长固化进 daily_usage。
        # 顺序反了的话，超过聚合保留期的明细被删掉，那几天的汇总就永远补不上了喵
        #
        # 喵~注意：回溯天数必须按**库里最老的那条明细**算，不能写死 400 天。
        # 热力图最大能看 740 天（`/api/v1/stats/heatmap` 的 days 上限），
        # `retention.aggregate_days` 还能配到 3650 天——写死 400 的话，
        # 比 400 天更早的那几天的汇总永远算不出来，明细一删就永久缺一块喵。
        # `storage._backfill_daily_usage` 早就是按最老明细算的，这里跟上同一口径
        queries.rebuild_daily_usage(
            connection,
            tz_offset_minutes=DAILY_USAGE_TZ_MINUTES,
            days=_oldest_usage_days(connection),
        )
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


def vacuum_once(config: AppConfig) -> tuple[int, int]:
    """回收数据库空页，返回 (回收前字节, 回收后字节) 喵。

    输入：服务端配置。
    输出：(回收前大小, 回收后大小)，单位字节；回收失败时两个值相同。
    边界：VACUUM 需要独占锁，失败只记警告不影响维护流程喵。

    喵~注意：这一步不能省。SQLite 的 DELETE 只把页标成空闲，
    文件不会缩小——归档删掉几十万行后，库可能还占着原来那么大的磁盘。
    实测归档 29 万行后空页有 109 MB，VACUUM 完只剩 1.9 MB 喵。

    喵~注意：**失败是常态，不是异常**。采集端每 60 秒就写一次上报，
    VACUUM 要求独占锁，正在写的时候必然拿到 `database is locked`。
    所以这里重试几次，最终失败就安静地返回（两个值相同），
    绝不能把异常抛给维护循环——那会让日志里出现「定期维护失败」，
    可实际上清理和归档都已经成功了，只剩回收没做而已喵。
    """
    # 回收前的体积喵
    path = config.server.db_path
    before = path.stat().st_size if path.exists() else 0
    # 重试次数与间隔秒数喵
    attempts = 3
    for attempt in range(attempts):
        # 打开连接喵
        connection = db.connect(path)
        try:
            # 喵~注意：VACUUM 不能在事务里跑，先确保没有未提交的东西喵
            connection.commit()
            connection.execute("VACUUM")
            connection.commit()
        except sqlite3.OperationalError as vacuum_error:
            # 喵~防御：被写入挡住就退让一下再试，最后一次失败也不抛喵
            if attempt == attempts - 1:
                LOGGER.info("暂时无法回收磁盘空间（有写入正在进行）：%s", vacuum_error)
            else:
                connection.close()
                time.sleep(0.5 * (attempt + 1))
                continue
        finally:
            # 关闭连接喵
            connection.close()
        # 回收后的体积喵
        after = path.stat().st_size if path.exists() else 0
        return before, after
    # 全部重试都失败，如实返回「没变」喵
    return before, before


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
                # 这个月的标记，同样按本地月算，和窗口判断同一口径喵
                local_now = now.astimezone(timezone(timedelta(minutes=ARCHIVE_TZ_MINUTES)))
                window_key = f"{local_now.year:04d}-{local_now.month:02d}"
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
            # 喵~注意：这轮真的删过东西才 VACUUM。它要独占锁、还要重写整个文件，
            # 每轮都跑太浪费；没删东西时空页也不会变多喵
            if archived.rows or sum(deleted.values()) > 0:
                before, after = await asyncio.to_thread(vacuum_once, config)
                # 只有明显变小才值得记一笔，否则日志太吵喵
                if before - after > 1024 * 1024:
                    LOGGER.info(
                        "回收磁盘空间：%.1f MB → %.1f MB",
                        before / 1024 / 1024,
                        after / 1024 / 1024,
                    )
        except sqlite3.Error as maintenance_error:
            # 喵~防御：维护失败不影响服务，下一个周期继续尝试喵
            LOGGER.warning("定期维护失败：%s", maintenance_error)
        except Exception as maintenance_error:  # 喵~防御：非数据库异常也不能让后台任务整个死掉喵
            # 喵~注意：只捕获 sqlite3.Error 是不够的。
            # 归档那条链路里还会抛 OSError（磁盘满、文件被占）、
            # zlib.error（块损坏）、ValueError（时间格式不对）、
            # TypeError（配置字段类型错）等等；这些异常一旦逃出循环，
            # `maintenance_loop` 这个 task 就彻底结束了——
            # 而它是 `asyncio.create_task` 起的，没人 await，异常只会变成
            # 一条 "Task exception was never retrieved"，之后**再也不会归档与清理**，
            # 主人还以为是正常的。这里兜住并记录，保证下一轮继续喵
            LOGGER.exception("定期维护出现非数据库异常，本轮跳过：%s", maintenance_error)
