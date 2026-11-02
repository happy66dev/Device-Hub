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
