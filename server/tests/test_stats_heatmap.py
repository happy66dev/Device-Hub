"""统计页热力图的测试：按本地日期聚合、时区切分、接口返回结构喵。

为什么要单独测时区：热力图的行列是「本地日历天」，而库里存的是 UTC 时刻。
切分线错了会出现「明明昨晚用过、今天的格子却是空的」这种看着像丢数据的现象喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main, queries
from app.config import AppConfig
from app.db import to_utc_text

# 基准时间固定，避免跟着真实时钟漂移喵
BASE_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

# 测试用的设备 ID 喵
DEVICE_A = "win-stats-0001"
DEVICE_B = "and-stats-0002"


def _stamp(moment: datetime) -> str:
    """转成库里存的文本格式喵。"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_device(connection: sqlite3.Connection, device_id: str, name: str) -> None:
    """插一台设备喵。"""
    connection.execute(
        "INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,"
        " current_app_json, client_version, first_seen_at, last_seen_at, role, afk)"
        " VALUES (?, 'windows', ?, '', '{}', NULL, '0.1.0', ?, ?, 'workstation', 0)",
        (device_id, name, _stamp(BASE_NOW), _stamp(BASE_NOW)),
    )
    connection.commit()


def _seed_usage(connection: sqlite3.Connection, device_id: str, moment: datetime, seconds: int) -> None:
    """插一条使用采样喵。"""
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, sampled_at, seconds, package)"
        " VALUES (?, 'Code.exe', ?, ?, 'code')",
        (device_id, _stamp(moment), seconds),
    )
    connection.commit()


# ==================== 按天聚合 ====================


def test_daily_usage_groups_by_local_day(connection: sqlite3.Connection) -> None:
    """同一个本地日里的采样要合并成一行喵。"""
    # 造两台设备、同一天的两笔记录喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_device(connection, DEVICE_B, "手机")
    _seed_usage(connection, DEVICE_A, datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc), 600)
    _seed_usage(connection, DEVICE_B, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), 900)
    # 按 UTC+8 算，这两个时刻都还是 11-01 喵
    rows = queries.daily_usage_totals(connection, days=30, tz_offset_minutes=480, now=BASE_NOW)
    assert rows == [("2026-11-01", 1500)]


def test_daily_usage_splits_by_device_filter(connection: sqlite3.Connection) -> None:
    """指定设备时只统计那几台喵。"""
    # 两台设备各一笔喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_device(connection, DEVICE_B, "手机")
    _seed_usage(connection, DEVICE_A, datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc), 600)
    _seed_usage(connection, DEVICE_B, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), 900)
    # 只统计手机喵
    rows = queries.daily_usage_totals(
        connection, device_ids=[DEVICE_B], days=30, tz_offset_minutes=480, now=BASE_NOW
    )
    assert rows == [("2026-11-01", 900)]


def test_daily_usage_respects_timezone_boundary(connection: sqlite3.Connection) -> None:
    """跨零点的那笔记录会随偏移量归到不同日期喵。

    喵~注意：UTC 11-01 17:00 在东八区是 11-02 01:00，在 UTC 还是 11-01，
    这条正好卡在切分线上，最适合验证时区有没有真的生效喵。
    """
    # 卡边界的这笔记录喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_usage(connection, DEVICE_A, datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc), 3600)
    # 东八区算成 11-02 喵
    east = queries.daily_usage_totals(connection, days=30, tz_offset_minutes=480, now=BASE_NOW)
    assert east == [("2026-11-02", 3600)]
    # UTC 算成 11-01 喵
    utc = queries.daily_usage_totals(connection, days=30, tz_offset_minutes=0, now=BASE_NOW)
    assert utc == [("2026-11-01", 3600)]


def test_daily_usage_empty_returns_list(connection: sqlite3.Connection) -> None:
    """没有数据时返回空列表，不能返回 None喵。"""
    # 什么都不造喵
    rows = queries.daily_usage_totals(connection, days=30, tz_offset_minutes=480, now=BASE_NOW)
    assert rows == []


def test_daily_usage_skips_zero_seconds(connection: sqlite3.Connection) -> None:
    """秒数为 0 的采样不该把那天算成「有记录」喵。"""
    # 造一笔 0 秒的喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_usage(connection, DEVICE_A, datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc), 0)
    rows = queries.daily_usage_totals(connection, days=30, tz_offset_minutes=480, now=BASE_NOW)
    assert rows == []


def test_daily_usage_window_cuts_old_days(connection: sqlite3.Connection) -> None:
    """超出回溯窗口的老数据不该出现在结果里喵。"""
    # 一条很老的、一条新鲜的喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=40), 600)
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=1), 900)
    # 只看最近七天，老的那条要被切掉喵
    rows = queries.daily_usage_totals(connection, days=7, tz_offset_minutes=480, now=BASE_NOW)
    assert [day for day, _seconds in rows] == ["2026-11-01"]


# ==================== 热力图接口 ====================


def test_heatmap_endpoint_shape(client: TestClient, connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """接口要给出 dates、devices 与 totals 三块喵。"""
    # 造两台设备与两天的数据喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_device(connection, DEVICE_B, "手机")
    _seed_usage(connection, DEVICE_A, datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc), 600)
    _seed_usage(connection, DEVICE_B, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), 900)
    # 请求接口喵
    response = client.get(
        "/api/v1/stats/heatmap?days=30&tz_offset_minutes=480",
        headers={"X-Ingest-Token": app_config.ingest.token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # 按天明细喵
    assert body["days"] == [{"date": "2026-11-01", "seconds": 1500}]
    # 设备明细按秒数倒序喵
    assert [item["name"] for item in body["devices"]] == ["手机", "本机 Windows"]
    # 汇总数字喵
    assert body["totals"]["seconds"] == 1500
    assert body["totals"]["active_days"] == 1
    assert body["totals"]["busiest_date"] == "2026-11-01"
    assert body["totals"]["average_seconds"] == 1500


def test_heatmap_endpoint_requires_token(client: TestClient) -> None:
    """没有口令时要 401，统计同样不能裸奔喵。"""
    # 不带口令请求喵
    response = client.get("/api/v1/stats/heatmap")
    assert response.status_code == 401


def test_heatmap_endpoint_filters_devices(
    client: TestClient, connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """带上 devices 时按天数据只算指定的设备喵。"""
    # 两台设备各一笔，分在不同的日子，方便看出过滤效果喵
    _seed_device(connection, DEVICE_A, "本机 Windows")
    _seed_device(connection, DEVICE_B, "手机")
    _seed_usage(connection, DEVICE_A, datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc), 600)
    _seed_usage(connection, DEVICE_B, datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), 900)
    # 只查手机喵
    response = client.get(
        f"/api/v1/stats/heatmap?days=30&devices={DEVICE_B}",
        headers={"X-Ingest-Token": app_config.ingest.token},
    )
    assert response.status_code == 200
    body = response.json()
    # 喵~注意：按天数据只剩手机那天，本机 Windows 的 10-30 不该出现喵
    assert [item["date"] for item in body["days"]] == ["2026-11-01"]
    assert body["totals"]["seconds"] == 900
    # 喵~注意：设备明细故意不过滤——统计页的切换按钮要靠它换回全部设备喵
    assert [item["name"] for item in body["devices"]] == ["手机", "本机 Windows"]


def test_heatmap_endpoint_clamps_days(
    client: TestClient, connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """离谱的天数要夹到合法范围，不能因为参数把库扫穿喵。"""
    # 请求一个荒谬的天数喵
    response = client.get(
        "/api/v1/stats/heatmap?days=99999",
        headers={"X-Ingest-Token": app_config.ingest.token},
    )
    # 夹到上限后仍然是 200喵
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_stats_ignores_archive_table_entirely(connection: sqlite3.Connection) -> None:
    """统计页的长程数据不该碰归档表喵。

    喵~注意：热力图只看 `usage_samples`，这张表**不进归档**。
    归档只压 `reports` 与 `window_samples`，所以统计页的
    「一年长程」数据必须完全不受归档影响。

    这条测试把「碰巧成立」变成「有保证」：往归档表里塞脏块，
    统计结果一个字都不能变——万一以后有人手滑让统计走了归档路径，
    这里会立刻红喵。
    """
    # 造设备与两条使用时长喵
    _seed_device(connection, DEVICE_A, "统计机")
    for days_ago, seconds in ((1, 600), (10, 1200), (40, 1800)):
        _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=days_ago), seconds)
    connection.commit()
    # 归档前的统计结果喵
    before = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    # 喵~注意：塞一个「覆盖全部日期」的脏归档块，内容都是无效字节喵
    connection.execute(
        "INSERT INTO archives (device_id, kind, month, row_count, codec, body, created_at)"
        " VALUES (?, 'windows', '2026-10', 999, 'zlib', ?, ?)",
        (DEVICE_A, b"not-a-valid-zlib-stream", _stamp(BASE_NOW)),
    )
    connection.commit()
    # 归档表有脏数据，统计结果仍然一模一样喵
    after = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert after == before
    # 长程数据确实跨了 40 天，不是空集喵
    assert len(after) == 3
    # 总计秒数也对得上喵
    assert sum(value for _, value in after) == 3600


def test_stats_survives_archive_and_prune(connection: sqlite3.Connection) -> None:
    """真跑一遍归档 + 清理，统计页**不受归档影响**喵。

    喵~注意：这条盯的是「归档会不会顺手把统计要的数据删掉」。
    归档只动 reports 与 window_samples，`usage_samples` 完全不进归档，
    所以这里断言的是「归档前后统计结果一致」，而不是「数据能活过保留期」喵。

    喵~注意：聚合保留期（默认 30 天）比热力图的请求范围（365 天）短，
    超过保留期的使用时长本来就会被清理删掉，热力图那几天自然是空的。
    这是保留期配置的取舍，不是归档的锅，所以测试数据都留在保留期内喵。
    """
    from app import archive

    # 造设备喵
    _seed_device(connection, DEVICE_A, "统计机")
    # 两条都落在 30 天聚合保留期内，确保清理不会删它们喵
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=20), 900)
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=1), 300)
    connection.commit()
    # 归档前的长程统计喵
    before = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert len(before) == 2
    # 喵~注意：归档与清理都用 BASE_NOW 做基准。往后推 60 天的话，
    # 20 天前那条会被当成 80 天前，直接按聚合口径删掉，断言就没意义了喵
    archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=BASE_NOW)
    # 归档后按同一个基准再查，结果必须一致喵
    after = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert after == before


def test_heatmap_backfills_old_days_from_daily_usage(connection: sqlite3.Connection) -> None:
    """明细过期后，热力图的长程数据靠 daily_usage 汇总表补上喵。

    喵~注意：这是「明细 30 天、热力图 365 天」那个矛盾的解法。
    明细（`usage_samples`）按聚合保留期删掉之后，那几天的总量已经
    固化进 `daily_usage`，所以热力图照样能画出一年的颜色喵。
    """
    # 造设备喵
    _seed_device(connection, DEVICE_A, "统计机")
    # 一条 20 天内、一条 40 天前喵
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=20), 600)
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=40), 900)
    connection.commit()
    # 喵~注意：先跑汇总再清理——顺序反了明细已被删，40 天前那天就永远补不上喵
    written = queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW)
    assert written == 2
    # 按 30 天聚合口径清理，40 天前的明细会消失喵
    queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=BASE_NOW)
    assert connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"] == 1
    # 但热力图两天都在，靠的是汇总表喵
    rows = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert len(rows) == 2
    # 两天的秒数都对得上喵
    assert dict(rows) == {rows[0][0]: 900, rows[1][0]: 600}


def test_rebuild_daily_usage_is_idempotent(connection: sqlite3.Connection) -> None:
    """汇总表重复生成不会把秒数越加越多喵。"""
    # 造设备与一条采样喵
    _seed_device(connection, DEVICE_A, "统计机")
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=1), 600)
    connection.commit()
    # 连跑三次喵
    for _ in range(3):
        queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW)
    # 秒数必须还是 600，不能翻倍喵
    row = connection.execute("SELECT seconds FROM daily_usage").fetchone()
    assert row["seconds"] == 600
    # 也不能多出行喵
    assert connection.execute("SELECT COUNT(*) AS c FROM daily_usage").fetchone()["c"] == 1


def test_rebuild_daily_usage_window_starts_at_local_midnight(connection: sqlite3.Connection) -> None:
    """重算窗口的起点必须落在本地日零点，不能停在一天中间喵。

    喵~注意：这是 `prune_expired` 对齐之后剩下的另一半坑。
    清理侧对齐只管「删除不切半天」，可**重算时的读取窗口**同样是精确时刻：
    `WHERE sampled_at >= ?` 会把边界那天零点到起点之间的明细排除掉，
    SUM 只剩后半截，再覆盖写回，那天就凭空缩水了。
    等那天滑出窗口，错误值永久留存，热力图上再也看不出来喵。
    """
    # 本地时区喵
    tz8 = timezone(timedelta(hours=8))
    # 本地 2026-06-15 这一整天，共 86400 秒喵
    day_start = datetime(2026, 6, 15, 0, 0, tzinfo=tz8).astimezone(timezone.utc)
    _seed_device(connection, DEVICE_A, "统计机")
    # 每 5 分钟一条、每条 300 秒，跑满整天喵
    for index in range(288):
        _seed_usage(connection, DEVICE_A, day_start + timedelta(minutes=5 * index), 300)
    connection.commit()
    # 让窗口起点分别落在这天的 0 点、12 点、18 点、23 点喵
    for offset_hours in (0, 12, 18, 23):
        # 先清空汇总，保证每轮都是「只靠明细重算」喵
        connection.execute("DELETE FROM daily_usage")
        connection.commit()
        # 窗口起点 = 这一天 + offset_hours 喵
        window_start = day_start + timedelta(hours=offset_hours)
        # 回溯 400 天，正好从 window_start 开始喵
        moment = window_start + timedelta(days=400)
        # 重算喵
        queries.rebuild_daily_usage(connection, 480, 400, moment)
        # 不管起点落在几点，都必须还是完整的一整天喵
        rows = dict(connection.execute("SELECT local_day, seconds FROM daily_usage").fetchall())
        assert rows == {"2026-06-15": 86400}, f"起点偏移 {offset_hours} 小时时缩水成 {rows}"


def test_rebuild_daily_usage_splits_by_device(connection: sqlite3.Connection) -> None:
    """汇总按设备分开记，热力图才能按设备过滤喵。"""
    # 两台设备各一条喵
    _seed_device(connection, DEVICE_A, "甲机")
    _seed_device(connection, DEVICE_B, "乙机")
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=1), 600)
    _seed_usage(connection, DEVICE_B, BASE_NOW - timedelta(days=1), 900)
    connection.commit()
    # 生成汇总喵
    assert queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW) == 2
    # 全部设备合计喵
    all_rows = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert sum(value for _, value in all_rows) == 1500
    # 只看甲机喵
    one_rows = queries.daily_usage_totals(connection, [DEVICE_A], 365, 480, BASE_NOW)
    assert sum(value for _, value in one_rows) == 600


def test_daily_usage_prefers_detail_over_summary(connection: sqlite3.Connection) -> None:
    """明细和汇总都有那天时，明细优先（汇总是旧的、可能是半截数据）喵。"""
    # 造设备与明细喵
    _seed_device(connection, DEVICE_A, "统计机")
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(days=1), 600)
    connection.commit()
    # 手工塞一条过时的汇总，秒数故意写错喵
    day = (BASE_NOW - timedelta(days=1)).astimezone(timezone(timedelta(minutes=480))).strftime("%Y-%m-%d")
    connection.execute(
        "INSERT INTO daily_usage (device_id, local_day, seconds, updated_at) VALUES (?, ?, 9999, ?)",
        (DEVICE_A, day, _stamp(BASE_NOW)),
    )
    connection.commit()
    # 查询要返回明细的 600，不是汇总的 9999 喵
    rows = queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW)
    assert dict(rows)[day] == 600


def test_heatmap_day_does_not_shrink_after_prune(connection: sqlite3.Connection) -> None:
    """反复清理不能让热力图上某一天的秒数变小喵。

    喵~注意：这是真实踩过的坑。清理按 `now - N 天` 的精确时刻切，
    边界那天只删掉前半段；下一轮 `rebuild_daily_usage` 用这半截明细重算，
    把 `daily_usage` 里已经算对的 86400 秒覆盖成了 40200 秒，
    而前半段明细已经删掉、再也算不回来。热力图上就是那一天凭空缩水喵。
    """
    # 东八区口径，与热力图默认一致喵
    tz8 = timezone(timedelta(hours=8))
    # 造一台设备喵
    _seed_device(connection, DEVICE_A, "缩水测试机")
    # 造「刚好压线」那一天：本地日 00:00 起每 10 分钟一条 600 秒，整 24 小时喵
    target_day = (BASE_NOW - timedelta(days=30)).astimezone(tz8).date()
    day_start = datetime(target_day.year, target_day.month, target_day.day, tzinfo=tz8).astimezone(timezone.utc)
    for index in range(144):
        _seed_usage(connection, DEVICE_A, day_start + timedelta(minutes=10 * index), 600)
    # 整天合计 86400 秒喵
    assert connection.execute("SELECT SUM(seconds) AS s FROM usage_samples").fetchone()["s"] == 86400
    # 模拟维护循环连跑三轮：先固化汇总、再清理、再固化喵
    for _ in range(3):
        queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW)
        queries.prune_expired(connection, detail_days=7, aggregate_days=30, now=BASE_NOW)
    # 最后一轮再固化一次，模拟「清理之后再算」的顺序喵
    queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW)
    # 热力图里那一天必须还是 86400，绝不能缩水喵
    rows = dict(queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW))
    assert rows[target_day.strftime("%Y-%m-%d")] == 86400


def test_device_totals_match_overall_totals_after_detail_expires(
    connection: sqlite3.Connection,
) -> None:
    """明细过期后，「合计」和「按设备合计」必须是同一个数喵。

    喵~注意：统计页上这两个数字是并排显示的。原来「合计」走
    `daily_usage_totals`（含汇总表），「按设备」只读明细表，
    明细一过保留期就变成「合计 4200 / 设备合计 600」这种自相矛盾的画面喵。
    """
    # 造一台设备喵
    _seed_device(connection, DEVICE_A, "统计机")
    # 40 天前那天只剩汇总（明细已被清掉）喵
    old_local = (BASE_NOW - timedelta(days=40)).astimezone(timezone(timedelta(hours=8)))
    connection.execute(
        "INSERT INTO daily_usage (device_id, local_day, seconds, updated_at) VALUES (?, ?, 3600, ?)",
        (DEVICE_A, old_local.strftime("%Y-%m-%d"), to_utc_text(BASE_NOW)),
    )
    # 今天还有明细喵
    _seed_usage(connection, DEVICE_A, BASE_NOW - timedelta(hours=1), 600)
    connection.commit()
    # 总和喵
    overall = sum(value for _, value in queries.daily_usage_totals(connection, None, 365, 480, BASE_NOW))
    # 按设备喵（带上时区偏移才会去读汇总表）喵
    per_device = queries.device_usage_totals(
        connection, seconds=365 * 86400, now=BASE_NOW, tz_offset_minutes=480
    )
    # 两个数字必须相等喵
    assert overall == 4200
    assert sum(per_device.values()) == overall
    # 不带时区时保持旧行为：只读明细喵
    detail_only = queries.device_usage_totals(connection, seconds=365 * 86400, now=BASE_NOW)
    assert sum(detail_only.values()) == 600


@pytest.mark.parametrize("hour_utc", list(range(24)))
def test_totals_agree_at_every_hour_of_day(
    connection: sqlite3.Connection, hour_utc: int
) -> None:
    """一天 24 个整点里，「合计」都必须等于「按设备合计」喵。

    喵~注意：这是真实缺陷，而且上一轮只修了一半。
    `daily_usage.local_day` 存的是**本地日期**（写入时用
    `date(sampled_at, '+480 minutes')` 切的），但拿它做过滤时用的是
    `local_day_start(...).strftime("%Y-%m-%d")`——`local_day_start` 的返回值
    已经换算回 UTC，再取日期得到的是 **UTC 日期**，恒定比本地日期早一天。
    于是「今天 00:00–08:00」和「窗口边界那一天」的汇总会整天被漏掉或多算。

    之前那个用例只测了 `BASE_NOW`（本地 20:00）一个点，恰好落在不出错的时段，
    所以 19 个测试全绿也测不出来。这里把 24 个整点全部钉死喵。
    """
    # 逐个整点构造「现在」喵
    now = datetime(2026, 11, 3, hour_utc, 0, tzinfo=timezone.utc)
    # 造设备喵
    _seed_device(connection, DEVICE_A, "整点机")
    tz8 = timezone(timedelta(minutes=480))
    # 喵~注意：关键是**把数据放在两个口径会分歧的那一天**。
    # 旧口径的截止日是 `(now-1天)` 的 UTC 日期，新口径是它的本地日期；
    # 本地 00:00–08:00 时两者差一天。把汇总放在「旧口径的截止日」上：
    # 旧口径会把它算进窗口（多算），新口径会正确排除喵
    window_moment = now - timedelta(days=1)
    boundary_day = window_moment.strftime("%Y-%m-%d")
    connection.execute(
        "INSERT INTO daily_usage (device_id, local_day, seconds, updated_at) VALUES (?, ?, 3600, ?)",
        (DEVICE_A, boundary_day, to_utc_text(now)),
    )
    # 窗口内还有一条明细，保证两个函数都非空喵
    _seed_usage(connection, DEVICE_A, now - timedelta(hours=1), 600)
    connection.commit()
    # 两个口径的合计喵
    overall = sum(value for _, value in queries.daily_usage_totals(connection, None, 1, 480, now))
    per_device = queries.device_usage_totals(
        connection, seconds=86400, now=now, tz_offset_minutes=480
    )
    # 必须完全相等，一天 24 个整点不许有例外喵
    assert sum(per_device.values()) == overall, f"UTC {hour_utc:02d}:00 两个合计对不上"
    # 而且边界那一天必须被正确排除：合计只能是窗口内那条明细的 600 喵
    boundary_local = (window_moment.astimezone(tz8)).strftime("%Y-%m-%d")
    if boundary_day != boundary_local:
        # 只有落入分歧时段的整点才有这个额外断言喵
        assert overall == 600, f"UTC {hour_utc:02d}:00 边界日 {boundary_day} 的汇总被错误算进窗口"
