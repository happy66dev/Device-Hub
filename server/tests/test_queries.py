"""查询层单元测试：排序、时间窗口、在线判定、过期清理喵。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app import db, queries
from app.db import to_utc_text
from app.people import PersonGroup


def _insert_device(connection: sqlite3.Connection, device_id: str, last_seen: datetime, platform: str = "windows") -> None:
    """插入一台最小可用的设备记录喵。"""
    # 其余非空字段用占位值填满，测试只关心时间与排序喵
    connection.execute(
        """
        INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                             current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, '', '{}', NULL, '', ?, ?)
        """,
        (device_id, platform, device_id, to_utc_text(last_seen), to_utc_text(last_seen)),
    )
    # 提交喵
    connection.commit()


def _insert_archive(connection: sqlite3.Connection, device_id: str, kind: str, month: str) -> None:
    """插一个空的归档块占位，用来测「已归档」的判定喵。"""
    # 喵~注意：body 给个能解压出来的空串就行，这些测试只看块存不存在喵
    import zlib

    connection.execute(
        "INSERT INTO archives (device_id, kind, month, row_count, codec, body, created_at)"
        " VALUES (?, ?, ?, 0, 'zlib', ?, ?)",
        (device_id, kind, month, zlib.compress(b""), to_utc_text(datetime.now(timezone.utc))),
    )


def _insert_usage(
    connection: sqlite3.Connection,
    device_id: str,
    app_name: str,
    seconds: int,
    sampled_at: datetime,
    package: str = "",
) -> None:
    """插入一条使用时长采样喵。"""
    # 喵~防御：usage_samples 有外键约束，先把设备补齐，避免测试因外键失败喵
    connection.execute(
        """
        INSERT OR IGNORE INTO devices (device_id, platform, display_name, os_version, hardware_json,
                                       current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, 'windows', ?, '', '{}', NULL, '', ?, ?)
        """,
        (device_id, device_id, to_utc_text(sampled_at), to_utc_text(sampled_at)),
    )
    # 时间统一转成 UTC 文本喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
        (device_id, app_name, package, to_utc_text(sampled_at), seconds),
    )
    # 提交喵
    connection.commit()


def test_list_devices_orders_by_last_seen(connection: sqlite3.Connection) -> None:
    """设备列表应按最近上报时间倒序喵。"""
    # 当前时间作为基准喵
    now = datetime.now(timezone.utc)
    # 两台设备，时间不同喵
    _insert_device(connection, "win-old", now - timedelta(minutes=10))
    _insert_device(connection, "win-new", now)
    # 查询列表喵
    devices = queries.list_devices(connection)
    # 最新的应排在第一位喵
    assert [item.device_id for item in devices] == ["win-new", "win-old"]


def test_get_device_unknown_returns_none(connection: sqlite3.Connection) -> None:
    """查询不存在的设备应返回 None 而不是抛异常喵。"""
    # 空库查询喵
    assert queries.get_device(connection, "not-exists") is None


def test_get_device_aggregates_fields(connection: sqlite3.Connection) -> None:
    """详情应包含硬件、电量、当前应用与 24 小时总时长喵。"""
    # 当前时间基准喵
    now = datetime.now(timezone.utc)
    # 插入设备与电量喵
    _insert_device(connection, "and-1", now, platform="android")
    connection.execute(
        "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, ?, ?)",
        ("and-1", to_utc_text(now), 66, 1),
    )
    # 写入当前应用 JSON 喵
    connection.execute(
        "UPDATE devices SET current_app_json = ? WHERE device_id = ?",
        ('{"name": "微信", "package": "com.tencent.mm", "since": null}', "and-1"),
    )
    # 写入两条使用时长喵
    _insert_usage(connection, "and-1", "微信", 100, now - timedelta(hours=1))
    _insert_usage(connection, "and-1", "哔哩哔哩", 40, now - timedelta(hours=2))
    # 提交喵
    connection.commit()
    # 查询详情喵
    detail = queries.get_device(connection, "and-1")
    # 详情不应为空喵
    assert detail is not None
    # 电量应被读取喵
    assert detail.battery is not None and detail.battery.percent == 66
    # 充电状态应为真喵
    assert detail.battery.charging is True
    # 当前应用应被解析喵
    assert detail.current_app is not None and detail.current_app.name == "微信"
    # 总时长应为两条之和喵
    assert detail.usage_total_seconds == 140


def test_usage_ranking_orders_and_sums(connection: sqlite3.Connection) -> None:
    """排行应按累计时长倒序，并合并同名应用喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 同一应用两条采样，另一应用一条喵
    _insert_usage(connection, "win-1", "Code.exe", 30, now - timedelta(minutes=30))
    _insert_usage(connection, "win-1", "Code.exe", 20, now - timedelta(minutes=10))
    _insert_usage(connection, "win-1", "Edge.exe", 40, now - timedelta(minutes=20))
    # 查询排行喵
    ranking = queries.usage_ranking(connection, "win-1", hours=24)
    # 第一名应是 Code.exe，累计 50 秒喵
    assert ranking[0].app == "Code.exe"
    assert ranking[0].seconds == 50
    # 第二名应是 Edge.exe 喵
    assert ranking[1].app == "Edge.exe"
    assert ranking[1].seconds == 40


def test_usage_ranking_excludes_old_samples(connection: sqlite3.Connection) -> None:
    """24 小时窗口外的采样不应计入喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 一条 1 小时前、一条 25 小时前喵
    _insert_usage(connection, "win-1", "Code.exe", 10, now - timedelta(hours=1))
    _insert_usage(connection, "win-1", "Old.exe", 999, now - timedelta(hours=25))
    # 查询近 24 小时喵
    ranking = queries.usage_ranking(connection, "win-1", hours=24, now=now)
    # 只应剩 Code.exe 喵
    assert [entry.app for entry in ranking] == ["Code.exe"]


def test_usage_ranking_negative_hours(connection: sqlite3.Connection) -> None:
    """窗口小时数为负时应按 0 处理，不能返回全部历史喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 一条 1 小时前的采样喵
    _insert_usage(connection, "win-1", "Code.exe", 10, now - timedelta(hours=1))
    # 传入负数小时喵
    ranking = queries.usage_ranking(connection, "win-1", hours=-5, now=now)
    # 未来窗口应查不到任何数据喵
    assert ranking == []


def test_is_online_boundary() -> None:
    """在线判定应在 90 秒阈值附近切换喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 正好 90 秒前应算在线喵
    assert queries.is_online(now - timedelta(seconds=90), now) is True
    # 91 秒前应算离线喵
    assert queries.is_online(now - timedelta(seconds=91), now) is False
    # 喵~防御：时钟回拨导致时间在未来时也视为在线喵
    assert queries.is_online(now + timedelta(seconds=30), now) is True


def test_latest_battery_none_when_missing(connection: sqlite3.Connection) -> None:
    """没有电量记录时应返回 None，Windows 设备就是这种情况喵。"""
    # 直接查询喵
    assert queries.latest_battery(connection, "win-1") is None


def test_prune_expired_keeps_unarchived_reports(connection: sqlite3.Connection) -> None:
    """没归档的原始上报再老也不能删，否则归档就捡不到东西了喵。

    喵~注意：这是「两条保留期打架」的防回归。以前这里按 7 天硬删，
    而归档只在每月 8 号做，结果到了归档窗口数据早被删光喵。
    """
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入一台设备喵
    _insert_device(connection, "win-1", now)
    # 一条 40 天前的原始上报，没有任何归档块喵
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, '{}')",
        ("win-1", to_utc_text(now - timedelta(days=40)), to_utc_text(now - timedelta(days=40))),
    )
    # 提交喵
    connection.commit()
    # 执行清理喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 喵~注意：没有归档块就一行都不许删喵
    assert deleted["reports"] == 0
    # 行还在喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1


def test_prune_expired_removes_archived_reports(connection: sqlite3.Connection) -> None:
    """已经归档的原始上报才该被清理喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入一台设备喵
    _insert_device(connection, "win-1", now)
    # 一条上个月的原始上报喵
    old = datetime(now.year, now.month, 1, tzinfo=timezone.utc) - timedelta(days=20)
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, '{}')",
        ("win-1", to_utc_text(old), to_utc_text(old)),
    )
    # 造一个对应的归档块喵
    _insert_archive(connection, "win-1", "heartbeats", old.strftime("%Y-%m"))
    connection.commit()
    # 执行清理喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 该删掉那一条喵
    assert deleted["reports"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0


def test_prune_expired_keeps_usage_samples_on_day_basis(connection: sqlite3.Connection) -> None:
    """使用时长不进归档，仍按聚合天数清理喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入一台设备喵
    _insert_device(connection, "win-1", now)
    # 一条新数据、一条 40 天前的旧数据喵
    _insert_usage(connection, "win-1", "New.exe", 10, now - timedelta(days=1))
    _insert_usage(connection, "win-1", "Old.exe", 10, now - timedelta(days=40))
    # 提交喵
    connection.commit()
    # 执行清理，聚合保留 30 天喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 使用时长应删掉 1 条喵
    assert deleted["usage_samples"] == 1
    # 剩下的应用应是 New.exe 喵
    remaining_apps = [row["app_name"] for row in connection.execute("SELECT app_name FROM usage_samples")]
    assert remaining_apps == ["New.exe"]


def test_prune_expired_keeps_unarchived_window_samples(connection: sqlite3.Connection) -> None:
    """没归档的窗口快照也不许删，理由同原始上报喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入设备喵
    _insert_device(connection, "win-1", now)
    # 一条 10 天前的窗口快照，没有归档块喵
    connection.execute(
        "INSERT INTO window_samples (device_id, app_name, package, title, minimized, foreground, reported_at)"
        " VALUES (?, 'cmd', 'cmd.exe', '旧窗口', 0, 1, ?)",
        ("win-1", to_utc_text(now - timedelta(days=10))),
    )
    # 提交喵
    connection.commit()
    # 执行清理喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 没有归档块就不删喵
    assert deleted["window_samples"] == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 1


def test_prune_expired_removes_archived_window_samples(connection: sqlite3.Connection) -> None:
    """已经归档的窗口快照才该被清理喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入设备喵
    _insert_device(connection, "win-1", now)
    # 一条上个月的窗口快照喵
    old = datetime(now.year, now.month, 1, tzinfo=timezone.utc) - timedelta(days=20)
    connection.execute(
        "INSERT INTO window_samples (device_id, app_name, package, title, minimized, foreground, reported_at)"
        " VALUES (?, 'cmd', 'cmd.exe', '旧窗口', 0, 1, ?)",
        ("win-1", to_utc_text(old)),
    )
    # 造一个对应的窗口归档块喵
    _insert_archive(connection, "win-1", "windows", old.strftime("%Y-%m"))
    connection.commit()
    # 执行清理喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 该删掉那一条喵
    assert deleted["window_samples"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 0


def test_prune_expired_reports_every_table(connection: sqlite3.Connection) -> None:
    """返回的字典要覆盖所有被清理的表，日志才不会漏报喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插设备喵
    _insert_device(connection, "win-1", now)
    # 空库也要有完整键，日志才稳定喵
    deleted = queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    assert set(deleted) == {"reports", "window_samples", "usage_samples", "battery_samples"}


def test_prune_expired_keeps_zero_day_safe(connection: sqlite3.Connection) -> None:
    """保留天数传 0 时应被下限保护，不能把当天数据删光喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入一台设备与一条刚产生的采样喵
    _insert_device(connection, "win-1", now)
    _insert_usage(connection, "win-1", "Code.exe", 10, now)
    # 传 0 天喵
    deleted = queries.prune_expired(connection, detail_days=0, aggregate_days=0, now=now)
    # 刚产生的数据不应被删喵
    assert deleted["usage_samples"] == 0
    # 数据库里仍应有一条采样喵
    assert connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"] == 1


def test_prune_expired_cuts_on_local_day_boundary(connection: sqlite3.Connection) -> None:
    """清理必须按整日切，不能把某一天删掉半截喵。

    喵~注意：这是热力图「那一天凭空缩水」的根因。
    如果按 `now - N 天` 这个精确时刻切，边界那天只会删掉前半段，
    后半段留在明细里；下一次 `rebuild_daily_usage` 用这半截明细重算，
    就会把 `daily_usage` 里已经算对的整天值覆盖小，
    而前半段明细已经删了、再也补不回来喵。
    """
    # 用东八区的当前时刻做基准，避免测试机时区影响结果喵
    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)
    # 一台设备喵
    _insert_device(connection, "win-1", now)
    # 造「刚好压线」那一天：本地日 00:00 起每 10 分钟一条 600 秒，整整 24 小时喵
    target_day = (now - timedelta(days=30)).astimezone(tz8).date()
    day_start = datetime(target_day.year, target_day.month, target_day.day, tzinfo=tz8).astimezone(timezone.utc)
    for index in range(144):
        _insert_usage(connection, "win-1", "Code.exe", 600, day_start + timedelta(minutes=10 * index))
    # 清理前应该正好 86400 秒喵
    assert connection.execute("SELECT SUM(seconds) AS s FROM usage_samples").fetchone()["s"] == 86400
    # 聚合保留 30 天，这一天的本地日零点正好落在边界上喵
    queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=now)
    # 喵~注意：那一天要么整天留着、要么整天删掉，绝不能只剩一半喵
    remaining = connection.execute("SELECT SUM(seconds) AS s FROM usage_samples").fetchone()["s"] or 0
    assert remaining in (0, 86400)


def test_local_day_start_trims_to_midnight() -> None:
    """本地日取整要把时刻压到当天 00:00，并且跨时区口径一致喵。"""
    # 东八区 2026-11-03 18:30 喵
    moment = datetime(2026, 11, 3, 10, 30, tzinfo=timezone.utc)
    # 取整后应是东八区 2026-11-03 00:00，也就是 UTC 的 11-02 16:00 喵
    trimmed = db.local_day_start(moment, 480)
    assert trimmed == datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
    # 文本形式要能和库里的格式对上喵
    assert db.local_day_start_text(moment, 480) == "2026-11-02T16:00:00Z"


def test_db_time_helpers_roundtrip() -> None:
    """时间工具应能无损往返，且统一为 UTC 文本喵。"""
    # 带 +08:00 时区的时间喵
    moment = datetime(2026, 10, 29, 17, 40, 0, tzinfo=timezone(timedelta(hours=8)))
    # 转成文本后应是 UTC 09:40 喵
    assert to_utc_text(moment) == "2026-10-29T09:40:00Z"
    # 再解析回来应与原时间相等喵
    assert db.parse_utc_text(to_utc_text(moment)) == moment


def test_usage_ranking_includes_package(connection: sqlite3.Connection) -> None:
    """排行应带上包名喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入两条带包名的采样喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-1", "Code.exe", 30, now, package="Code.exe")
    # 查询排行喵
    ranking = queries.usage_ranking(connection, "win-1", hours=24, now=now)
    # 第一条应是微信且带包名喵
    assert ranking[0].app == "微信"
    assert ranking[0].package == "com.tencent.mm"


def test_battery_series_orders_and_filters(connection: sqlite3.Connection) -> None:
    """电量曲线应按时间升序，并只返回窗口内的点喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 设备与三个电量点，其中一个在 24 小时窗口外喵
    _insert_device(connection, "and-1", now, platform="android")
    for offset_minutes, percent in ((30, 70), (10, 80), (1800, 50)):
        connection.execute(
            "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, ?, 0)",
            ("and-1", to_utc_text(now - timedelta(minutes=offset_minutes)), percent),
        )
    connection.commit()
    # 查询 24 小时窗口喵
    points = queries.battery_series(connection, "and-1", hours=24, now=now)
    # 应只返回两个点，且按时间升序（30 分钟前的 70% 在前）喵
    assert [point.percent for point in points] == [70, 80]


def test_usage_timeline_buckets_by_hour(connection: sqlite3.Connection) -> None:
    """时间轴应按小时聚合并升序返回喵。"""
    # 基准时间固定到整点，便于断言桶时间喵
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    # 同一小时两条、前一小时一条喵
    _insert_usage(connection, "win-1", "Code.exe", 30, now - timedelta(minutes=10))
    _insert_usage(connection, "win-1", "Code.exe", 15, now - timedelta(minutes=20))
    _insert_usage(connection, "win-1", "Code.exe", 60, now - timedelta(hours=2))
    # 查询时间轴喵
    buckets = queries.usage_timeline(connection, "win-1", hours=24, now=now)
    # 应有两个桶，按时间升序喵
    assert len(buckets) == 2
    assert buckets[0].seconds == 60
    assert buckets[1].seconds == 45


def test_dashboard_devices_returns_cards(connection: sqlite3.Connection) -> None:
    """看板卡片应包含电量、当前应用与排行喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入一台安卓设备与采样喵
    _insert_device(connection, "and-1", now, platform="android")
    connection.execute(
        "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, ?, 1)",
        ("and-1", to_utc_text(now), 55),
    )
    connection.execute(
        "UPDATE devices SET current_app_json = ? WHERE device_id = ?",
        ('{"name": "微信", "package": "com.tencent.mm"}', "and-1"),
    )
    connection.commit()
    _insert_usage(connection, "and-1", "微信", 90, now, package="com.tencent.mm")
    # 查询看板喵
    cards = queries.dashboard_devices(connection, now=now)
    # 应有一张卡片喵
    assert len(cards) == 1
    assert cards[0].summary.device_id == "and-1"
    assert cards[0].battery is not None and cards[0].battery.percent == 55
    assert cards[0].current_app is not None and cards[0].current_app.name == "微信"
    assert cards[0].usage_total_seconds == 90
    assert cards[0].usage_top[0].package == "com.tencent.mm"


def test_set_device_role_updates_and_reports_missing(connection: sqlite3.Connection) -> None:
    """标记角色应更新成功，设备不存在时返回 False 喵。"""
    # 插入一台设备喵
    _insert_device(connection, "win-1", datetime.now(timezone.utc))
    # 标记为服务器喵
    assert queries.set_device_role(connection, "win-1", "server") is True
    # 角色应已更新喵
    role = connection.execute("SELECT role FROM devices WHERE device_id = 'win-1'").fetchone()["role"]
    assert role == "server"
    # 不存在的设备返回 False 喵
    assert queries.set_device_role(connection, "nope-1", "server") is False

def test_global_usage_ranking_aggregates_across_devices(connection: sqlite3.Connection) -> None:
    """跨设备排行应把同名应用合并，并统计设备数喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备都用过微信，只有一台用过 Code.exe 喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-2", "微信", 40, now, package="com.tencent.mm")
    _insert_usage(connection, "win-1", "Code.exe", 30, now, package="Code.exe")
    # 查询排行喵
    entries = queries.global_usage_ranking(connection, hours=24, limit=10, now=now)
    # 微信应排第一，共 100 秒、2 台设备喵
    assert entries[0].app == "微信"
    assert entries[0].seconds == 100
    assert entries[0].device_count == 2
    # 第二条是 Code.exe 喵
    assert entries[1].app == "Code.exe"
    assert entries[1].device_count == 1


def test_global_usage_ranking_respects_limit(connection: sqlite3.Connection) -> None:
    """limit 应限制返回条数，非法值被夹到合法范围喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 插入 5 个应用喵
    for index in range(5):
        _insert_usage(connection, "win-1", f"App{index}", 10 * (index + 1), now)
    # 只要 2 条喵
    assert len(queries.global_usage_ranking(connection, hours=24, limit=2, now=now)) == 2
    # 传 0 会被夹到 1 条喵
    assert len(queries.global_usage_ranking(connection, hours=24, limit=0, now=now)) == 1


def test_global_usage_ranking_skips_old_samples(connection: sqlite3.Connection) -> None:
    """窗口外的采样不应计入排行喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 一条窗口内、一条 30 小时前喵
    _insert_usage(connection, "win-1", "新应用", 60, now - timedelta(hours=1))
    _insert_usage(connection, "win-1", "旧应用", 60, now - timedelta(hours=30))
    # 查询 24 小时排行喵
    entries = queries.global_usage_ranking(connection, hours=24, limit=10, now=now)
    # 只应有新应用喵
    assert [entry.app for entry in entries] == ["新应用"]


def test_scoped_usage_ranking_all_matches_global(connection: sqlite3.Connection) -> None:
    """scope=all 应与旧的跨设备排行完全一致喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备各用过一个应用喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-2", "微信", 40, now, package="com.tencent.mm")
    _insert_usage(connection, "win-1", "Code.exe", 30, now, package="Code.exe")
    # 旧口径与新口径各查一次喵
    legacy = queries.global_usage_ranking(connection, hours=24, limit=10, now=now)
    entries, groups = queries.scoped_usage_ranking(connection, scope="all", hours=24, limit=10, now=now)
    # 总排行应完全一致，分组应为空喵
    assert entries == legacy
    assert groups == []


def test_scoped_usage_ranking_device_groups(connection: sqlite3.Connection) -> None:
    """scope=device 应每台设备一组，组内条目与组总时长正确喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 给两台设备设置展示名喵
    _insert_device(connection, "win-1", now)
    _insert_device(connection, "win-2", now)
    connection.execute("UPDATE devices SET display_name = ? WHERE device_id = ?", ("书房主机", "win-1"))
    connection.execute("UPDATE devices SET display_name = ? WHERE device_id = ?", ("客厅主机", "win-2"))
    connection.commit()
    # 书房主机用微信 60 秒、Code 30 秒，客厅主机用微信 40 秒喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-1", "Code.exe", 30, now, package="Code.exe")
    _insert_usage(connection, "win-2", "微信", 40, now, package="com.tencent.mm")
    # 按设备查排行喵
    _, groups = queries.scoped_usage_ranking(connection, scope="device", hours=24, limit=10, now=now)
    # 两台设备各一组，书房主机总时长 90 秒排第一喵
    assert [group.key for group in groups] == ["win-1", "win-2"]
    assert groups[0].label == "书房主机"
    assert groups[0].kind == "device"
    assert groups[0].seconds == 90
    assert [entry.app for entry in groups[0].entries] == ["微信", "Code.exe"]
    assert groups[0].entries[0].devices == ("书房主机",)
    # 客厅主机只有微信 40 秒喵
    assert groups[1].label == "客厅主机"
    assert groups[1].seconds == 40
    assert groups[1].entries[0].seconds == 40
    assert groups[1].entries[0].device_count == 1


def test_scoped_usage_ranking_group_groups_ungrouped(connection: sqlite3.Connection) -> None:
    """scope=group 应按 people.groups 分组，未归组设备进未分组桶喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 三台设备，前两台归到「主人」组，第三台不归组喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-2", "微信", 40, now, package="com.tencent.mm")
    _insert_usage(connection, "win-2", "Code.exe", 20, now, package="Code.exe")
    _insert_usage(connection, "win-3", "微信", 10, now, package="com.tencent.mm")
    # 组里还放一台没有采样的设备，空组不应出现喵
    groups_config = [PersonGroup(name="主人", devices=("win-1", "win-2", "win-9"))]
    # 按设备组查排行喵
    _, ranking_groups = queries.scoped_usage_ranking(
        connection, scope="group", groups=groups_config, hours=24, limit=10, now=now
    )
    # 主人组合并两台设备的微信，共 100 秒、2 台设备喵
    assert [group.label for group in ranking_groups] == ["主人", "未分组"]
    owner = ranking_groups[0]
    assert owner.key == "group:主人"
    assert owner.kind == "group"
    assert owner.seconds == 120
    assert [entry.app for entry in owner.entries] == ["微信", "Code.exe"]
    assert owner.entries[0].seconds == 100
    assert owner.entries[0].device_count == 2
    assert sorted(owner.entries[0].devices) == ["win-1", "win-2"]
    # 未分组桶只放第三台设备喵
    ungrouped = ranking_groups[1]
    assert ungrouped.key == "ungrouped"
    assert ungrouped.label == "未分组"
    assert ungrouped.seconds == 10
    assert [entry.app for entry in ungrouped.entries] == ["微信"]


def test_scoped_usage_ranking_group_without_groups_uses_ungrouped(connection: sqlite3.Connection) -> None:
    """没有配置设备组时所有设备都应进未分组桶喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备各用一个应用喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    _insert_usage(connection, "win-2", "Code.exe", 30, now, package="Code.exe")
    # 设备组列表为空时查排行喵
    _, groups = queries.scoped_usage_ranking(connection, scope="group", groups=[], hours=24, limit=10, now=now)
    # 所有设备合成一个未分组桶，按总时长倒序喵
    assert len(groups) == 1
    assert groups[0].key == "ungrouped"
    assert groups[0].label == "未分组"
    assert groups[0].seconds == 90
    assert [entry.app for entry in groups[0].entries] == ["微信", "Code.exe"]


def test_scoped_usage_ranking_limit_applies_per_group(connection: sqlite3.Connection) -> None:
    """limit 应只截断每组条目，组总时长仍按全部应用累计喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 一台设备三个应用喵
    _insert_usage(connection, "win-1", "A", 30, now)
    _insert_usage(connection, "win-1", "B", 20, now)
    _insert_usage(connection, "win-1", "C", 10, now)
    # 每组只要一条，0 会被夹到 1 喵
    _, groups = queries.scoped_usage_ranking(connection, scope="device", hours=24, limit=0, now=now)
    # 组内只剩最长的一条，但组总时长仍是 60 秒喵
    assert len(groups) == 1
    assert groups[0].seconds == 60
    assert [entry.app for entry in groups[0].entries] == ["A"]


def test_scoped_usage_ranking_empty_returns_empty_groups(connection: sqlite3.Connection) -> None:
    """空数据时各口径都应返回空列表而不是报错喵。"""
    # 三种口径都查一次喵
    for scope in ("all", "device", "group"):
        entries, groups = queries.scoped_usage_ranking(connection, scope=scope, hours=24, limit=10)
        # 总排行与分组都应为空喵
        assert entries == []
        assert groups == []


def test_scoped_usage_ranking_invalid_scope_falls_back_to_all(connection: sqlite3.Connection) -> None:
    """非法 scope 应按 all 处理，不能抛异常喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 一台设备一条采样喵
    _insert_usage(connection, "win-1", "微信", 60, now, package="com.tencent.mm")
    # 乱传口径喵
    entries, groups = queries.scoped_usage_ranking(connection, scope="nope", hours=24, limit=10, now=now)
    # 结果应与 all 一致，且没有分组喵
    assert [entry.app for entry in entries] == ["微信"]
    assert groups == []


def test_day_usage_segments_merges_same_app(connection: sqlite3.Connection) -> None:
    """同一应用相邻采样要合并成一段喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0001", base)
    # 三条微信采样，间隔都在阈值内喵
    _insert_usage(connection, "win-seg-0001", "微信", 60, base, package="wechat.exe")
    _insert_usage(connection, "win-seg-0001", "微信", 60, base + timedelta(minutes=1), package="wechat.exe")
    _insert_usage(connection, "win-seg-0001", "微信", 60, base + timedelta(minutes=2), package="wechat.exe")
    # 查询整天喵
    segments = queries.day_usage_segments(
        connection, "win-seg-0001", base - timedelta(hours=1), base + timedelta(hours=1)
    )
    # 应当只剩一段，累计 180 秒喵
    assert len(segments) == 1
    assert segments[0].seconds == 180
    assert segments[0].app == "微信"


def test_day_usage_segments_splits_far_apart_samples(connection: sqlite3.Connection) -> None:
    """间隔超过阈值的同应用采样要分成两段喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0002", base)
    # 两条采样相隔两小时喵
    _insert_usage(connection, "win-seg-0002", "Code.exe", 60, base)
    _insert_usage(connection, "win-seg-0002", "Code.exe", 60, base + timedelta(hours=2))
    # 默认 15 分钟阈值下应当是两段喵
    segments = queries.day_usage_segments(
        connection, "win-seg-0002", base - timedelta(hours=1), base + timedelta(hours=3)
    )
    assert len(segments) == 2


def test_day_usage_segments_avoids_overlap_for_same_timestamp(connection: sqlite3.Connection) -> None:
    """同一时刻的多应用采样要按顺序排开，不能互相重叠喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0003", base)
    # 两条采样时间完全相同喵
    _insert_usage(connection, "win-seg-0003", "A", 30, base)
    _insert_usage(connection, "win-seg-0003", "B", 20, base)
    segments = queries.day_usage_segments(
        connection, "win-seg-0003", base - timedelta(hours=1), base + timedelta(hours=1)
    )
    # 两段首尾相接，不重叠喵
    assert len(segments) == 2
    assert segments[0].end == segments[1].start
    assert sum(item.seconds for item in segments) == 50


def test_day_usage_segments_ignores_outside_window(connection: sqlite3.Connection) -> None:
    """窗口外的采样不应出现在结果里喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0004", base)
    # 窗口外一条、窗口内一条喵
    _insert_usage(connection, "win-seg-0004", "窗口外", 60, base - timedelta(days=2))
    _insert_usage(connection, "win-seg-0004", "窗口内", 60, base)
    segments = queries.day_usage_segments(
        connection, "win-seg-0004", base - timedelta(hours=1), base + timedelta(hours=1)
    )
    assert [item.app for item in segments] == ["窗口内"]

def test_day_usage_segments_priority_trims_lower(connection: sqlite3.Connection) -> None:
    """重叠时高优先级设备保留完整时长，低优先级被裁掉喵。"""
    # 两台设备，同一时间段各用了一小时喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "dev-high", base)
    _insert_device(connection, "dev-low", base)
    _insert_usage(connection, "dev-high", "Code.exe", 3600, base)
    _insert_usage(connection, "dev-low", "微信", 3600, base)
    # 高优先级在前喵
    segments = queries.day_usage_segments(
        connection, ["dev-high", "dev-low"], base - timedelta(hours=1), base + timedelta(hours=3)
    )
    # 只剩高优先级那段喵
    assert len(segments) == 1
    assert segments[0].app == "Code.exe"
    assert segments[0].seconds == 3600


def test_day_usage_segments_priority_keeps_partial(connection: sqlite3.Connection) -> None:
    """低优先级只被裁掉重叠部分，剩下的照常保留喵。"""
    # 高优先级占 01:00-02:00，低优先级占 01:30-03:00 喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "dev-high2", base)
    _insert_device(connection, "dev-low2", base)
    # 采样时刻是区间的右端：02:00 的 3600 秒覆盖 01:00-02:00 喵
    _insert_usage(connection, "dev-high2", "Code.exe", 3600, base + timedelta(hours=1))
    # 03:00 的 5400 秒覆盖 01:30-03:00 喵
    _insert_usage(connection, "dev-low2", "微信", 5400, base + timedelta(hours=2))
    segments = queries.day_usage_segments(
        connection, ["dev-high2", "dev-low2"], base - timedelta(hours=1), base + timedelta(hours=4)
    )
    # 两段，低优先级那段从 02:00 开始，剩 3600 秒喵
    assert len(segments) == 2
    low = [item for item in segments if item.app == "微信"]
    assert len(low) == 1
    assert low[0].start == base + timedelta(hours=1)
    assert low[0].seconds == 3600


def test_day_usage_segments_stack_backwards_from_sample_time(connection: sqlite3.Connection) -> None:
    """同一时刻的多应用采样要往前铺，段尾不能越过采样时刻喵。"""
    # 一次上报里三个应用，累计 65 秒喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0009", base)
    _insert_usage(connection, "win-seg-0009", "msedge", 35, base, package="msedge.exe")
    _insert_usage(connection, "win-seg-0009", "DeepSeek Harness", 25, base)
    _insert_usage(connection, "win-seg-0009", "explorer", 5, base, package="explorer.exe")
    segments = queries.day_usage_segments(
        connection, "win-seg-0009", base - timedelta(hours=2), base + timedelta(hours=1)
    )
    # 三段首尾相接，最早一段从采样时刻往前 65 秒开始喵
    assert len(segments) == 3
    assert segments[-1].end == base
    assert segments[0].start == base - timedelta(seconds=65)
    for previous, following in zip(segments, segments[1:]):
        assert previous.end == following.start


def test_day_usage_segments_without_resolve_keeps_both(connection: sqlite3.Connection) -> None:
    """关掉优先级裁剪时两台设备的数据都要保留喵。"""
    # 两台设备重叠喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "dev-a", base)
    _insert_device(connection, "dev-b", base)
    _insert_usage(connection, "dev-a", "A", 600, base)
    _insert_usage(connection, "dev-b", "B", 600, base)
    segments = queries.day_usage_segments(
        connection, ["dev-a", "dev-b"], base - timedelta(hours=1), base + timedelta(hours=2), resolve_overlaps=False
    )
    assert {item.app for item in segments} == {"A", "B"}


def test_day_usage_segments_keeps_real_gaps(connection: sqlite3.Connection) -> None:
    """同应用相隔 30 秒（超过默认 5 秒阈值）不能合并，真实空档必须留出来喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0003", base)
    # 两条采样中间空了 30 秒喵
    _insert_usage(connection, "win-seg-0003", "Code.exe", 20, base)
    _insert_usage(connection, "win-seg-0003", "Code.exe", 20, base + timedelta(seconds=50))
    # 默认阈值下应是两段，中间 30 秒不涂色喵
    segments = queries.day_usage_segments(
        connection, "win-seg-0003", base - timedelta(hours=1), base + timedelta(hours=1)
    )
    assert len(segments) == 2
    # 两段的真实时长都只有 20 秒喵
    assert [segment.seconds for segment in segments] == [20, 20]


def test_day_usage_segments_merges_tiny_jitter(connection: sqlite3.Connection) -> None:
    """相邻采样只差 2 秒时仍要合并，避免抖出色块喵。"""
    # 准备一台设备喵
    base = datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)
    _insert_device(connection, "win-seg-0004", base)
    # 中间只隔 2 秒喵
    _insert_usage(connection, "win-seg-0004", "Code.exe", 30, base)
    _insert_usage(connection, "win-seg-0004", "Code.exe", 30, base + timedelta(seconds=32))
    # 默认阈值下应合并成一段喵
    segments = queries.day_usage_segments(
        connection, "win-seg-0004", base - timedelta(hours=1), base + timedelta(hours=1)
    )
    assert len(segments) == 1
    assert segments[0].seconds == 60


def test_global_usage_ranking_splits_seconds_by_device(connection: sqlite3.Connection) -> None:
    """总排行要把同一条应用按设备拆开秒数，加起来必须等于总时长喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备，一台改名一台默认喵
    _insert_device(connection, "win-1", now)
    _insert_device(connection, "win-2", now)
    connection.execute("UPDATE devices SET display_name = ? WHERE device_id = ?", ("书房主机", "win-1"))
    connection.commit()
    # 同一个包名在两台设备上各用一段时间喵
    _insert_usage(connection, "win-1", "QQ", 90, now, package="qq.exe")
    _insert_usage(connection, "win-2", "QQ", 30, now, package="qq.exe")
    # 查总排行喵
    entries = queries.global_usage_ranking(connection, hours=24, limit=10, now=now)
    # 只有一条记录，总时长 120 秒喵
    assert len(entries) == 1
    entry = entries[0]
    assert entry.seconds == 120
    assert entry.device_count == 2
    # 拆分按秒数倒序：书房主机 90 秒在前喵
    assert entry.device_seconds == (("书房主机", 90), ("win-2", 30))
    # 拆分之和必须等于总时长，否则看板的条形比例会失真喵
    assert sum(seconds for _, seconds in entry.device_seconds) == entry.seconds


def test_global_usage_ranking_keeps_packages_separate(connection: sqlite3.Connection) -> None:
    """同名不同包名算两条，各自只带自己那台设备的秒数喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备喵
    _insert_device(connection, "win-1", now)
    _insert_device(connection, "and-1", now)
    # 同一个 QQ 在两端包名不同喵
    _insert_usage(connection, "win-1", "QQ", 50, now, package="qq.exe")
    _insert_usage(connection, "and-1", "QQ", 70, now, package="com.tencent.mobileqq")
    # 查总排行喵
    entries = queries.global_usage_ranking(connection, hours=24, limit=10, now=now)
    # 两条记录，安卓那条更长排前面喵
    assert [entry.package for entry in entries] == ["com.tencent.mobileqq", "qq.exe"]
    assert entries[0].device_seconds == (("and-1", 70),)
    assert entries[1].device_seconds == (("win-1", 50),)


def test_scoped_usage_ranking_group_splits_seconds_by_device(connection: sqlite3.Connection) -> None:
    """按组口径也要带按设备拆分的秒数，组内合并多设备时条形才能切段喵。"""
    # 基准时间喵
    now = datetime.now(timezone.utc)
    # 两台设备归进同一个组喵
    _insert_device(connection, "win-1", now)
    _insert_device(connection, "win-2", now)
    connection.execute("UPDATE devices SET display_name = ? WHERE device_id = ?", ("书房主机", "win-1"))
    connection.commit()
    # 同一个包名两台设备各用一段喵
    _insert_usage(connection, "win-1", "Code.exe", 40, now, package="Code.exe")
    _insert_usage(connection, "win-2", "Code.exe", 60, now, package="Code.exe")
    # 两台设备放进同一个设备组喵
    groups_config = [PersonGroup(name="书房", devices=("win-1", "win-2"))]
    # 按组查排行喵
    _, ranking_groups = queries.scoped_usage_ranking(
        connection, scope="group", groups=groups_config, hours=24, limit=10, now=now
    )
    # 只有一组，条目里带上两台设备的秒数喵
    assert [group.label for group in ranking_groups] == ["书房"]
    entry = ranking_groups[0].entries[0]
    assert entry.seconds == 100
    assert entry.device_seconds == (("win-2", 60), ("书房主机", 40))
    # 拆分之和必须等于总时长喵
    assert sum(seconds for _, seconds in entry.device_seconds) == entry.seconds
