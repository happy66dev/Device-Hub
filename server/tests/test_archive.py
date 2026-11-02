"""历史数据归档的单元测试喵。

喵~注意：这些测试最核心的断言是「归档前后查出来的结果一模一样」——
归档是换存法不是丢数据，只要这个不变式成立，方案就安全喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import archive, archive_codec, db, queries
from app.db import to_utc_text

# 基准时刻，所有测试都围绕它构造数据喵
BASE_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
# 测试设备喵
DEVICE = "win-arch-0001"


def _seed_device(connection: sqlite3.Connection, device_id: str = DEVICE, role: str = "workstation") -> None:
    """插一台设备喵。"""
    # 设备表是外键父表，必须先有喵
    connection.execute(
        "INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,"
        " current_app_json, client_version, first_seen_at, last_seen_at, role, tag)"
        " VALUES (?, 'windows', '归档测试机', 'Windows 11', '{}', '{}', '0.1.0', ?, ?, ?, '')",
        (device_id, to_utc_text(BASE_NOW), to_utc_text(BASE_NOW), role),
    )


def _seed_report(
    connection: sqlite3.Connection,
    moment: datetime,
    device_id: str = DEVICE,
    afk: bool = False,
    afk_since: str = "",
    active_since: str = "",
) -> None:
    """插一条心跳原始上报喵。"""
    # 上报体的关键字段与线上一致喵
    body = (
        '{"afk": %s, "afk_since": %s, "active_since": %s}'
        % (
            "true" if afk else "false",
            f'"{afk_since}"' if afk_since else "null",
            f'"{active_since}"' if active_since else "null",
        )
    )
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
        (device_id, to_utc_text(moment), to_utc_text(moment), body),
    )


def _seed_window(
    connection: sqlite3.Connection,
    moment: datetime,
    app_name: str,
    title: str,
    device_id: str = DEVICE,
    minimized: bool = False,
    foreground: bool = True,
) -> None:
    """插一行窗口采样喵。"""
    connection.execute(
        "INSERT INTO window_samples"
        " (device_id, app_name, package, title, minimized, foreground, reported_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            device_id,
            app_name,
            f"{app_name.lower()}.exe",
            title,
            1 if minimized else 0,
            1 if foreground else 0,
            to_utc_text(moment),
        ),
    )


def test_encode_decode_heartbeats_roundtrip() -> None:
    """心跳块压缩再解出来要完整还原喵。"""
    # 三行数据（带原始 rowid）喵
    rows = [
        ("2026-11-01T10:00:00Z", False, "", "2026-11-01T09:00:00Z", "win-a", 11),
        ("2026-11-01T10:00:10Z", True, "2026-11-01T10:00:05Z", "", "win-a", 12),
        ("2026-11-01T10:00:20Z", False, "", "", "win-b", 13),
    ]
    # 往返喵
    assert archive_codec.decode_heartbeats(archive_codec.encode_heartbeats(rows)) == rows


def test_encode_decode_windows_roundtrip() -> None:
    """窗口块压缩再解出来要完整还原喵。"""
    # 两行数据（带原始 rowid）喵
    rows = [
        ("2026-11-01T10:00:00Z", "Code", "code.exe", "app.js - device-hub", False, True, 41),
        ("2026-11-01T10:00:00Z", "微信", "wechat.exe", "微信", True, False, 42),
    ]
    # 往返喵
    assert archive_codec.decode_windows(archive_codec.encode_windows(rows)) == rows


def test_archive_codec_survives_separator_in_title() -> None:
    """标题里混进分隔符也不能把块结构撑破喵。"""
    # 标题里塞控制字符喵
    nasty = f"标题{archive_codec.FIELD_SEP}带分隔符{archive_codec.LINE_SEP}还有换行"
    rows = [("2026-11-01T10:00:00Z", "App", "app.exe", nasty, False, True, 7)]
    # 解出来标题会被替换成空格，行数不能变喵
    decoded = archive_codec.decode_windows(archive_codec.encode_windows(rows))
    assert len(decoded) == 1
    # 分隔符必须已经被清掉喵
    assert archive_codec.FIELD_SEP not in decoded[0][3]
    assert archive_codec.LINE_SEP not in decoded[0][3]


def test_window_block_preserves_row_order_for_ties() -> None:
    """同一时刻并列的多行必须靠 rowid 保持原顺序喵。

    喵~注意：`ORDER BY app_name, reported_at` 对并列行的先后由 rowid 决定，
    不存 rowid 的话归档后区间合并结果会漂喵。
    """
    # 同一时刻两行不同标题喵
    rows = [
        ("2026-11-01T10:00:00Z", "App", "app.exe", "标题甲", False, True, 100),
        ("2026-11-01T10:00:00Z", "App", "app.exe", "标题乙", False, True, 99),
    ]
    # 解码后顺序要与写入时一致喵
    decoded = archive_codec.decode_windows(archive_codec.encode_windows(rows))
    assert [item[6] for item in decoded] == [100, 99]
    assert [item[3] for item in decoded] == ["标题甲", "标题乙"]


def test_prefix_filters_select_only_matching_rows() -> None:
    """按月份和日期前缀过滤要只命中对应行喵。"""
    # 跨两个月的行喵
    rows = [
        ("2026-10-31T23:59:59Z", False, "", "", "win-a", 1),
        ("2026-11-01T00:00:00Z", False, "", "", "win-a", 2),
        ("2026-11-02T08:00:00Z", True, "", "", "win-a", 3),
    ]
    block = archive_codec.encode_heartbeats(rows)
    # 十一月应命中两行喵
    november = list(archive_codec.iter_month_prefix(block, "2026-11"))
    assert len(november) == 2
    # 单日应命中一行喵
    one_day = list(archive_codec.iter_day_prefix(block, "2026-11-02"))
    assert len(one_day) == 1


def test_archive_moves_rows_into_block_without_losing_them(connection: sqlite3.Connection) -> None:
    """归档后原始行被删，但数据完整保存在块里喵。"""
    # 造一台设备喵
    _seed_device(connection)
    # 一条 40 天前、一条今天的数据喵
    _seed_report(connection, BASE_NOW - timedelta(days=40), afk=True, afk_since="2026-09-23T00:00:00Z")
    _seed_report(connection, BASE_NOW)
    connection.commit()
    # 归档，热窗口 7 天喵
    result = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 应该归档 1 个块、1 行喵
    assert result.blocks == 1
    assert result.rows == 1
    # 原始表只剩今天那条喵
    remaining = connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
    assert remaining == 1
    # 归档块里那条数据要能完整解出来喵
    block = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
    assert block is not None
    records = archive_codec.decode_heartbeats(block)
    assert len(records) == 1
    assert records[0][1] is True
    assert records[0][2] == "2026-09-23T00:00:00Z"


def test_archive_is_idempotent(connection: sqlite3.Connection) -> None:
    """重复跑归档不能把同一批数据算两遍喵。"""
    # 造数据喵
    _seed_device(connection)
    _seed_report(connection, BASE_NOW - timedelta(days=40))
    connection.commit()
    # 第一次归档喵
    first = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    assert first.rows == 1
    # 第二次已经没有可归档的行了喵
    second = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    assert second.blocks == 0
    assert second.rows == 0


def test_archive_keeps_hot_rows_untouched(connection: sqlite3.Connection) -> None:
    """热窗口内的数据不能被动，否则查询会变慢喵。"""
    # 造一条 6 天前（热窗口内）的数据喵
    _seed_device(connection)
    _seed_report(connection, BASE_NOW - timedelta(days=6))
    connection.commit()
    # 归档喵
    result = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 什么都不该归档喵
    assert result.blocks == 0
    # 原始行还在喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1


def test_archived_heartbeats_are_visible_to_queries(connection: sqlite3.Connection) -> None:
    """归档之后 day_heartbeats 仍要查出完整一天，调用方感知不到归档喵。"""
    # 造设备与三条历史心跳喵
    _seed_device(connection)
    day = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
    for index, afk in enumerate((False, True, False)):
        _seed_report(connection, day + timedelta(hours=index), afk=afk)
    connection.commit()
    # 归档前先查一次，留下基准喵
    before = queries.day_heartbeats(connection, [DEVICE], day, day + timedelta(days=1))
    assert len(before) == 3
    # 归档喵
    archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 原始表已经空了喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0
    # 归档后必须查出一样的三条喵
    after = queries.day_heartbeats(connection, [DEVICE], day, day + timedelta(days=1))
    assert len(after) == 3
    # 逐条比对时间与 afk 标记喵
    assert [item.reported_at for item in after] == [item.reported_at for item in before]
    assert [item.afk for item in after] == [item.afk for item in before]


def test_archived_windows_are_visible_to_title_spans(connection: sqlite3.Connection) -> None:
    """归档之后 day_title_spans 仍要给出完整标题区间喵。"""
    # 造设备与窗口采样喵
    _seed_device(connection)
    day = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
    # 同一个应用同一个标题连续 5 分钟，应合成一个区间喵
    for minute in range(5):
        _seed_window(connection, day + timedelta(minutes=minute), "Code", "app.js - device-hub")
    connection.commit()
    # 归档前基准喵
    before = queries.day_title_spans(connection, [DEVICE], day, day + timedelta(days=1))
    assert len(before) == 1
    # 归档喵
    archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 原始表空了喵
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 0
    # 归档后结果必须一致喵
    after = queries.day_title_spans(connection, [DEVICE], day, day + timedelta(days=1))
    assert len(after) == 1
    assert after[0].app == before[0].app
    assert after[0].title == before[0].title
    assert after[0].start == before[0].start
    assert after[0].end == before[0].end


def test_archive_preserves_details_fully(connection: sqlite3.Connection) -> None:
    """归档块解出来的每一条都要与原始行逐字段相同喵。"""
    # 造十条带各种 afk 组合的心跳喵
    _seed_device(connection)
    day = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    expected: list[tuple[str, bool, str, str]] = []
    for index in range(10):
        moment = day + timedelta(seconds=index * 10)
        afk = index % 3 == 0
        afk_since = "2026-09-15T02:00:00Z" if afk else ""
        active_since = "" if afk else "2026-09-15T02:30:00Z"
        _seed_report(connection, moment, afk=afk, afk_since=afk_since, active_since=active_since)
        expected.append((to_utc_text(moment), afk, afk_since, active_since))
    connection.commit()
    # 归档喵
    archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 解出块内容逐条比对喵
    block = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
    assert block is not None
    records = archive_codec.decode_heartbeats(block)
    assert len(records) == 10
    for record, want in zip(records, expected):
        assert record[0] == want[0]
        assert record[1] == want[1]
        assert record[2] == want[2]
        assert record[3] == want[3]


def test_archive_splits_by_month(connection: sqlite3.Connection) -> None:
    """跨月的数据要拆成不同的块，不能混在一起喵。"""
    # 造九月与十月各一条喵
    _seed_device(connection)
    _seed_report(connection, datetime(2026, 9, 10, tzinfo=timezone.utc))
    _seed_report(connection, datetime(2026, 10, 10, tzinfo=timezone.utc))
    connection.commit()
    # 归档喵
    archive.archive_cold_rows(connection, hot_days=0, now=BASE_NOW)
    # 应该有两个块喵
    months = [
        row["month"]
        for row in connection.execute("SELECT month FROM archives ORDER BY month")
    ]
    assert months == ["2026-09", "2026-10"]


def test_list_months_for_range_covers_boundaries() -> None:
    """跨月的日期范围要列出中间所有月份喵。"""
    # 从十月中到十二月初喵
    months = list(
        archive.list_months_for_range(
            datetime(2026, 10, 15, tzinfo=timezone.utc),
            datetime(2026, 12, 2, tzinfo=timezone.utc),
        )
    )
    assert months == ["2026-10", "2026-11", "2026-12"]


def test_archive_survives_broken_payload(connection: sqlite3.Connection) -> None:
    """坏 payload 也要归档，不能因为解析失败就丢行喵。"""
    # 造设备喵
    _seed_device(connection)
    # 手工插一条坏 JSON喵
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
        (DEVICE, "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", "这不是 JSON"),
    )
    connection.commit()
    # 归档喵
    result = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 喵~注意：坏数据也要归档，行数不能少喵
    assert result.rows == 1
    # 解出来是默认值喵
    block = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
    records = archive_codec.decode_heartbeats(block)
    assert len(records) == 1
    assert records[0][1] is False


def test_archive_deduplicates_when_both_copies_exist(connection: sqlite3.Connection) -> None:
    """归档块与原始行同时存在时，查询不能返回重复心跳喵。"""
    # 造数据并归档喵
    _seed_device(connection)
    day = datetime(2026, 9, 20, tzinfo=timezone.utc)
    _seed_report(connection, day)
    connection.commit()
    archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 手工把原始行插回去，模拟归档中途失败留下的双份喵
    _seed_report(connection, day)
    connection.commit()
    # 查出来只能有一条喵
    heartbeats = queries.day_heartbeats(connection, [DEVICE], day, day + timedelta(days=1))
    assert len(heartbeats) == 1


def test_same_month_is_archived_only_once(connection: sqlite3.Connection) -> None:
    """同一个月块只能写一次，第二次必须整块跳过喵。

    喵~注意：这是最容易丢数据的路径——如果第二次既写块又删行，
    块被拒绝覆盖、原始行却删了，那批数据就彻底没了喵。
    """
    # 造设备与上月的数据喵
    _seed_device(connection)
    old_month = datetime(2026, 9, 10, tzinfo=timezone.utc)
    _seed_report(connection, old_month, afk=True)
    _seed_report(connection, old_month + timedelta(hours=1))
    connection.commit()
    # 第一次归档喵
    first = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    assert first.blocks == 1
    assert first.rows == 2
    # 记下第一块的内容喵
    block_first = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
    assert block_first is not None
    records_first = archive_codec.decode_heartbeats(block_first)
    assert len(records_first) == 2
    # 喵~注意：手工往同一个月的原始表里补一条（模拟归档后又冒出数据）喵
    _seed_report(connection, old_month + timedelta(hours=2), afk=True)
    connection.commit()
    # 第二次归档必须完全跳过这个月喵
    second = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    assert second.blocks == 0
    assert second.rows == 0
    # 块内容不能被改喵
    block_second = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
    assert block_second == block_first
    # 新补的那条必须还在原始表里，绝不能被删喵
    remaining = connection.execute(
        "SELECT COUNT(*) AS c FROM reports WHERE device_id = ?", (DEVICE,)
    ).fetchone()["c"]
    assert remaining == 1


def test_current_month_is_never_archived(connection: sqlite3.Connection) -> None:
    """当月的热数据一条都不能归档喵。"""
    # 造设备喵
    _seed_device(connection)
    # 基准时刻是 11 月 2 日，当月的 1 号数据属于当月喵
    _seed_report(connection, datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc))
    connection.commit()
    # 归档喵
    result = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    # 当月不该被归档喵
    assert result.blocks == 0
    assert result.rows == 0
    # 原始行还在喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1


def test_month_is_archived_only_after_it_fully_ages_out(connection: sqlite3.Connection) -> None:
    """整月都过了热保留期才会归档，半新半旧的月份一律不动喵。

    喵~注意：这条盯的是「按月归档」的核心约束。基准是 11 月 2 日、热保留 7 天，
    截止日期是 10-26；10 月 31 日不早于 10-26，所以整个 10 月还不能归档。
    若按单行判断，10-20 那条会被先压进 10 月块，之后再追加就丢数据喵。
    """
    # 造设备喵
    _seed_device(connection)
    # 10 月 20 日的数据：已经 13 天，够旧喵
    _seed_report(connection, datetime(2026, 10, 20, tzinfo=timezone.utc))
    # 10 月 28 日的数据：只有 5 天，还热喵
    _seed_report(connection, datetime(2026, 10, 28, tzinfo=timezone.utc))
    connection.commit()
    # 这时归档：10 月还没整月过完，一块都不该出喵
    result = archive.archive_cold_rows(connection, hot_days=7, now=BASE_NOW)
    assert result.blocks == 0
    assert result.rows == 0
    # 两条都还在原始表喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 2
    # 换成 11 月 8 日凌晨再归档：10 月整月都过了 7 天，该整月压进去了喵
    later = datetime(2026, 11, 8, 0, 30, tzinfo=timezone.utc)
    result2 = archive.archive_cold_rows(connection, hot_days=7, now=later)
    # 整个 10 月的两条一起归档喵
    assert result2.blocks == 1
    assert result2.rows == 2
    # 块里正好两条，一条不少喵
    block = archive.load_heartbeat_block(connection, DEVICE, "2026-10")
    assert len(archive_codec.decode_heartbeats(block)) == 2
    # 原始表清空喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0


def test_archive_keeps_seven_days_hot_at_month_boundary(connection: sqlite3.Connection) -> None:
    """每月 8 号凌晨归档时，本月 1 号起的数据必须都还是热数据喵。"""
    # 造设备喵
    _seed_device(connection)
    # 11 月 1 日零点刚过一分钟的数据喵
    _seed_report(connection, datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc))
    connection.commit()
    # 11 月 8 日凌晨触发归档喵
    now = datetime(2026, 11, 8, 0, 30, tzinfo=timezone.utc)
    result = archive.archive_cold_rows(connection, hot_days=7, now=now)
    # 喵~防御：11-01 00:01 距离 11-08 00:30 才 7 天多一点，仍算热数据喵
    assert result.rows == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1
