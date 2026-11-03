"""SQLite 连接、建表与时间工具。

时间统一以 UTC 的 `YYYY-MM-DDTHH:MM:SSZ` 文本存储：
这样按字符串比较就等于按时间比较，SQL 里不需要再做时区转换喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 授时时钟：所有「现在」都走它，避免依赖本机与客户端时钟喵
from .clock import get_clock

# 统一的时间文本格式，固定长度保证字符串排序等于时间排序喵
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# 建表语句集合，全部使用 IF NOT EXISTS，重复执行安全喵
SCHEMA_STATEMENTS: tuple[str, ...] = (
    # 设备表：每台设备一行，保存最近一次上报的概要信息喵
    """
    CREATE TABLE IF NOT EXISTS devices (
        device_id        TEXT PRIMARY KEY,
        platform         TEXT NOT NULL,
        display_name     TEXT NOT NULL,
        os_version       TEXT NOT NULL DEFAULT '',
        hardware_json    TEXT NOT NULL DEFAULT '{}',
        current_app_json TEXT,
        client_version   TEXT NOT NULL DEFAULT '',
        first_seen_at    TEXT NOT NULL,
        last_seen_at     TEXT NOT NULL,
        role             TEXT NOT NULL DEFAULT 'workstation',
        tag              TEXT NOT NULL DEFAULT '',
        rdp_connected    INTEGER NOT NULL DEFAULT 0,
        rdp_updated_at   TEXT,
        mirror_windows_json TEXT NOT NULL DEFAULT '[]',
        mirrored_tags_json  TEXT NOT NULL DEFAULT '[]',
        stats_paused_reason TEXT NOT NULL DEFAULT ''
    )
    """,
    # 原始上报表：保留完整 JSON，方便以后回溯和重新解析喵
    """
    CREATE TABLE IF NOT EXISTS reports (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id    TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
        reported_at  TEXT NOT NULL,
        received_at  TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE (device_id, reported_at)
    )
    """,
    # 电量采样表：只保留最近若干天，供命令展示最新电量喵
    """
    CREATE TABLE IF NOT EXISTS battery_samples (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id  TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
        sampled_at TEXT NOT NULL,
        percent    INTEGER NOT NULL,
        charging   INTEGER NOT NULL,
        UNIQUE (device_id, sampled_at)
    )
    """,
    # 应用使用时长表：每行是"某个时间点上报的一段增量时长"喵
    """
    CREATE TABLE IF NOT EXISTS usage_samples (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
        app_name  TEXT NOT NULL,
        package   TEXT NOT NULL DEFAULT '',
        sampled_at TEXT NOT NULL,
        seconds   INTEGER NOT NULL,
        UNIQUE (device_id, app_name, package, sampled_at)
    )
    """,
    # 窗口快照表：每次上报落一份"当前打开的窗口"，按时间留存供后续分析喵
    # 喵~注意：下面的 reported_at 列名有误导性，它存的**不是**客户端上报的时刻，
    # 而是服务端收到这次上报的时刻（等价于 reports.received_at）。
    # 之所以这样命名，是因为它和 reports.reported_at 用了同一套列名习惯，
    # 但写入时走的是 ingest 里的 received_text 喵。
    # 后果是：时间轴的心跳区间与窗口标题区间用的是同一个时间基准，
    # 不存在「一个按客户端时间、一个按服务端时间」的错位喵。
    """
    CREATE TABLE IF NOT EXISTS window_samples (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
        app_name    TEXT NOT NULL,
        package     TEXT NOT NULL DEFAULT '',
        title       TEXT NOT NULL DEFAULT '',
        minimized   INTEGER NOT NULL DEFAULT 0,
        foreground  INTEGER NOT NULL DEFAULT 0,
        reported_at TEXT NOT NULL
    )
    """,
    # 应用图标表：按 应用名+包名 存一张 32x32 PNG，客户端只传一次喵
    """
    CREATE TABLE IF NOT EXISTS app_icons (
        icon_key   TEXT PRIMARY KEY,
        app_name   TEXT NOT NULL,
        package    TEXT NOT NULL DEFAULT '',
        png        BLOB NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # 每日使用时长汇总：一天一台设备一行，给统计页的长程热力图用喵
    # 喵~注意：`usage_samples` 只保留 30 天，热力图却要看一年，
    # 中间必然是一大片空白。这张表按天固化「那天用了多少秒」，
    # 明细过期之后靠它补齐长程视图，一年 365 行/设备，体积可以忽略喵。
    # `local_day` 存的是**本地日期**（已按 tz_offset 换算过），
    # 因为热力图的行列本来就是本地日历天，存 UTC 还要再换算一次容易出错喵。
    """
    CREATE TABLE IF NOT EXISTS daily_usage (
        device_id   TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
        local_day   TEXT NOT NULL,
        seconds     INTEGER NOT NULL DEFAULT 0,
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (device_id, local_day)
    )
    """,
    # 机器人见过的发言人：只记成功执行了命令的人，供「最近发言」列表反查 openid 喵
    # 喵~注意：按 (通道, 标识) 唯一，每人一行，用 upsert 更新，不会随消息条数膨胀喵
    """
    CREATE TABLE IF NOT EXISTS bot_seen_users (
        channel     TEXT NOT NULL,
        user_key    TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        group_key   TEXT NOT NULL DEFAULT '',
        role        TEXT NOT NULL DEFAULT 'member',
        command_count INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        last_seen_at  TEXT NOT NULL,
        PRIMARY KEY (channel, user_key)
    )
    """,    # 按设备+时间建索引，近 24 小时聚合查询全靠它喵
    # 喵~注意：归档表存「压缩后的历史数据块」，按设备+自然月分块。
    # 超过保留窗口的原始行会被压进这里再删掉原行，数据本身一条不少，
    # 只是从「可 SQL 直查」变成「必须经归档层解压」喵
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
    """,
)

# 索引语句单独放一组，必须等老库补列之后再执行，否则会报 no such column 喵
# 喵~注意：reports 与 battery_samples 不再建 (device_id, 时间) 索引——
# 这两张表本身就有 UNIQUE(device_id, 时间)，SQLite 会自动建一份同列的索引，
# 再手工建一份完全重复，除了白占空间还让每次插入多维护一棵树喵
INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_usage_device_time ON usage_samples (device_id, sampled_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_package ON usage_samples (device_id, package)",
    "CREATE INDEX IF NOT EXISTS idx_window_device_time ON window_samples (device_id, reported_at)",
    # 最近发言列表按最后活跃时间倒序取，走这个索引喵
    "CREATE INDEX IF NOT EXISTS idx_bot_seen_last ON bot_seen_users (last_seen_at)",
)

# 喵~注意：早期版本建过的冗余索引，启动时要删掉，否则老库会一直留着喵
DROPPED_INDEXES: tuple[str, ...] = (
    "DROP INDEX IF EXISTS idx_reports_device_time",
    "DROP INDEX IF EXISTS idx_battery_device_time",
)

# 老版本数据库缺的列，启动时按需补齐喵
DEVICE_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("role", "TEXT NOT NULL DEFAULT 'workstation'"),
    ("tag", "TEXT NOT NULL DEFAULT ''"),
    ("rdp_connected", "INTEGER NOT NULL DEFAULT 0"),
    ("rdp_updated_at", "TEXT"),
    ("mirror_foreground", "INTEGER NOT NULL DEFAULT 0"),
    ("afk", "INTEGER NOT NULL DEFAULT 0"),
    ("mirror_windows_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("mirrored_tags_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("stats_paused_reason", "TEXT NOT NULL DEFAULT ''"),
    # RDP 客户端的 IP 与机器名，用来确认连进来的确实是受监控的客户端喵
    ("rdp_client_ip", "TEXT NOT NULL DEFAULT ''"),
    ("rdp_client_name", "TEXT NOT NULL DEFAULT ''"),
    # 设备最近一次上报的来源 IP，用于比对 RDP 客户端喵
    ("last_ip", "TEXT NOT NULL DEFAULT ''"),
)

# 使用时长表新增的包名列喵
USAGE_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("package", "TEXT NOT NULL DEFAULT ''"),
)


def utc_now() -> datetime:
    """返回当前 UTC 时间（走授时时钟）喵。"""
    # 统一走全局授时时钟，客户端与浏览器时钟都不参与喵
    return get_clock().now()


def to_utc_text(moment: datetime) -> str:
    """把带时区的时间转成统一的 UTC 文本喵。"""
    # 喵~防御：调用方忘了带时区时按 UTC 解释，而不是直接崩溃喵
    if moment.tzinfo is None:
        # 补上 UTC 时区喵
        moment = moment.replace(tzinfo=timezone.utc)
    # 统一换算到 UTC 再格式化喵
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def parse_utc_text(text: str) -> datetime:
    """把库里的时间文本还原成带时区的 datetime 喵。"""
    # 按固定格式解析喵
    parsed = datetime.strptime(text, TIME_FORMAT)
    # 补上 UTC 时区，保证和 utc_now() 可直接比较喵
    return parsed.replace(tzinfo=timezone.utc)


def hours_ago_text(hours: int, now: datetime | None = None) -> str:
    """返回"若干小时前"的 UTC 文本，用于时间窗口查询喵。"""
    # 喵~防御：小时数为负数时按 0 处理，避免算出未来时间导致查询为空喵
    safe_hours = max(0, hours)
    # 基准时间缺省取当前时间喵
    base_moment = now or utc_now()
    # 减去对应小时数后转成文本喵
    return to_utc_text(base_moment - timedelta(hours=safe_hours))


def seconds_ago_text(seconds: int, now: datetime | None = None) -> str:
    """返回"若干秒前"的 UTC 文本，用于「最近 1 分钟」这类短窗口查询喵。

    输入：秒数、可选基准时间。
    输出：UTC 文本。
    边界：负数按 0 处理，等价于"此刻之后"，通常查不到数据喵。
    """
    # 喵~防御：负数会让窗口落到未来，按 0 处理更符合直觉喵
    safe_seconds = max(0, seconds)
    # 基准时间缺省取当前时间喵
    base_moment = now or utc_now()
    # 减去对应秒数后转成文本喵
    return to_utc_text(base_moment - timedelta(seconds=safe_seconds))


def days_ago_text(days: int, now: datetime | None = None) -> str:
    """返回"若干天前"的 UTC 文本，用于清理过期数据喵。"""
    # 喵~防御：天数小于 1 时按 1 处理，防止误删全部历史喵
    safe_days = max(1, days)
    # 基准时间缺省取当前时间喵
    base_moment = now or utc_now()
    # 减去对应天数后转成文本喵
    return to_utc_text(base_moment - timedelta(days=safe_days))


def local_day_start(moment: datetime, tz_offset_minutes: int = 480) -> datetime:
    """把时刻向下取整到它所在的「本地日零点」，返回带时区的 datetime 喵。

    输入：任意带时区的时刻、本地时区偏移（分钟）。
    输出：同一本地日 00:00 对应的时刻（UTC 时区）。
    边界：偏移量会被夹到 -720..840，避免算出不存在的时区喵。

    喵~注意：这个函数专门给清理用。清理如果按「now - N 天」这个精确时刻切，
    落在边界上的那个本地日就只会被删掉前半段，明细从此变成半截。
    而热力图的每日汇总一旦用这半截明细重算，那一天就会凭空缩水，
    真值又已经随明细删掉、再也算不回来——所以要按**整日**切，
    让每个本地日的明细要么完整保留、要么整体清掉，不存在半截喵。
    """
    # 夹到合法偏移喵
    offset_minutes = max(-720, min(840, int(tz_offset_minutes)))
    # 换到本地时区再截掉时分秒喵
    offset = timezone(timedelta(minutes=offset_minutes))
    local = moment.astimezone(offset)
    # 本地日零点喵
    start_local = datetime(local.year, local.month, local.day, tzinfo=offset)
    # 统一换算回 UTC 喵
    return start_local.astimezone(timezone.utc)


def local_day_start_text(moment: datetime, tz_offset_minutes: int = 480) -> str:
    """同 `local_day_start`，但直接返回库里用的 UTC 文本喵。"""
    # 复用上面的实现再格式化喵
    return to_utc_text(local_day_start(moment, tz_offset_minutes))


def local_day_text(moment: datetime, tz_offset_minutes: int = 480) -> str:
    """把时刻换成「本地日的日期字符串」，格式与 `daily_usage.local_day` 一致喵。

    输入：任意带时区的时刻、本地时区偏移（分钟）。
    输出：`YYYY-MM-DD`，代表该时刻在本地时区属于哪一天。

    喵~注意：**不要**用 `local_day_start(...).strftime("%Y-%m-%d")` 取日期。
    `local_day_start` 的返回值已经换算回 UTC，再取 `.strftime` 得到的是
    **UTC 日期**，比本地日期恒定早一天（东八区下 24 个小时全错）。
    而 `daily_usage.local_day` 是用 `date(sampled_at, '+480 minutes')`
    切的**本地**日期。两边口径不同，拿 UTC 日期去比 `local_day`，
    就会把边界那天整天的汇总漏掉或多算，表现为
    「合计 4200 / 按设备合计 3900」这种自相矛盾喵。
    """
    # 夹到合法偏移喵
    offset_minutes = max(-720, min(840, int(tz_offset_minutes)))
    # 换到本地时区后直接取年月日喵
    local = moment.astimezone(timezone(timedelta(minutes=offset_minutes)))
    return local.strftime("%Y-%m-%d")


def connect(db_path: Path) -> sqlite3.Connection:
    """打开数据库连接并设置常用 PRAGMA 喵。

    输入：数据库文件路径（父目录不存在会自动创建）。
    输出：sqlite3.Connection，行结果可按列名访问。
    边界：目录不可写、文件被占用会抛 sqlite3.Error。
    """
    # 先把父目录建出来，首次运行时不至于因为目录缺失失败喵
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout 是获取写锁的最长等待秒数，避免并发写直接报 database is locked 喵
    connection = sqlite3.connect(str(db_path), timeout=15)
    # 让查询结果支持按列名取值，代码可读性更好喵
    connection.row_factory = sqlite3.Row
    # WAL 模式让读写互不阻塞，适合"写上报 + 读查询"同时发生的场景喵
    connection.execute("PRAGMA journal_mode=WAL")
    # 打开外键约束，删除设备时自动清理关联数据喵
    connection.execute("PRAGMA foreign_keys=ON")
    # 写锁竞争时最多等 15 秒再报错喵
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """读取某张表已有的列名集合喵。"""
    # PRAGMA 返回每列一行，第二列是列名喵
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    # 收集列名喵
    return {str(row[1]) for row in rows}


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[tuple[str, str], ...],
) -> None:
    """按需给老库补列，重复执行安全喵。

    输入：连接、表名、待补的 (列名, 列定义) 元组。
    输出：无。
    边界：表不存在时什么都不做（建表语句会先执行）喵。
    """
    # 读取现有列喵
    existing = _table_columns(connection, table_name)
    # 喵~防御：表都不存在说明建表失败，交给上层报错，这里不硬加列喵
    if not existing:
        return
    # 逐列检查喵
    for column_name, column_definition in columns:
        # 已经有这一列就跳过喵
        if column_name in existing:
            continue
        # 老库补列，SQLite 支持 ADD COLUMN 带默认值喵
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_db(db_path: Path) -> None:
    """建表并确保索引存在，可重复调用喵。"""
    # 打开连接喵
    connection = connect(db_path)
    try:
        # 逐条执行建表语句喵
        for statement in SCHEMA_STATEMENTS:
            # execute 对 IF NOT EXISTS 语句是幂等的喵
            connection.execute(statement)
        # 喵~防御：老版本数据库没有新列，这里补齐，避免升级后直接报 no such column 喵
        _ensure_columns(connection, "devices", DEVICE_MIGRATION_COLUMNS)
        _ensure_columns(connection, "usage_samples", USAGE_MIGRATION_COLUMNS)
        # 补列之后再建索引，顺序不能反喵
        for index_statement in INDEX_STATEMENTS:
            connection.execute(index_statement)
        # 喵~注意：删掉早期版本留下的冗余索引，老库升级后也能瘦下来喵
        for drop_statement in DROPPED_INDEXES:
            connection.execute(drop_statement)
        # 一次性提交所有建表动作喵
        connection.commit()
    finally:
        # 喵~防御：无论建表成功与否都要关连接，避免句柄泄漏喵
        connection.close()
