"""泳道时间轴查询测试：设备间保留重叠、总量按并集去重。

这里同时守住老行为：`day_usage_segments(resolve_overlaps=True)` 仍然按优先级裁剪喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app import queries
from app.db import to_utc_text

# 测试统一使用的窗口起点，固定成常量避免依赖真实时钟喵
WINDOW_START = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)
# 测试统一使用的窗口长度，三小时足够放下几段互不干扰的采样喵
WINDOW_LENGTH = timedelta(hours=3)


def _window() -> tuple[datetime, datetime]:
    """返回测试用窗口 (start, end) 喵。"""
    # 起点用固定常量喵
    start = WINDOW_START
    # 右端按固定长度推算喵
    end = WINDOW_START + WINDOW_LENGTH
    # 一起返回喵
    return start, end


def _insert_usage(
    connection: sqlite3.Connection,
    device_id: str,
    app_name: str,
    seconds: int,
    sampled_at: datetime,
    package: str = "",
) -> None:
    """插入一条使用时长采样（顺手补齐设备行，满足外键约束）喵。"""
    # usage_samples 有外键约束，先按需补一条最小设备记录喵
    connection.execute(
        """
        INSERT OR IGNORE INTO devices (device_id, platform, display_name, os_version, hardware_json,
                                       current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, 'windows', ?, '', '{}', NULL, '', ?, ?)
        """,
        (device_id, device_id, to_utc_text(sampled_at), to_utc_text(sampled_at)),
    )
    # 时间统一转成 UTC 文本再入库喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
        (device_id, app_name, package, to_utc_text(sampled_at), seconds),
    )
    # 提交事务喵
    connection.commit()


def test_lanes_keep_overlapping_same_app(connection: sqlite3.Connection) -> None:
    """两台设备同一时刻用同一个应用：两段都保留，合计只算一份时长喵。"""
    # 采样时刻取窗口内的 01:10，采样时刻就是段的右端喵
    sampled = WINDOW_START + timedelta(hours=1, minutes=10)
    # A 设备上报 600 秒 Chrome，覆盖 01:00-01:10 喵
    _insert_usage(connection, "dev-a", "Chrome", 600, sampled, package="chrome.exe")
    # B 设备在同一时刻上报同样的 600 秒 Chrome，区间完全重叠喵
    _insert_usage(connection, "dev-b", "Chrome", 600, sampled, package="chrome.exe")
    # 取泳道明细，不做优先级裁剪喵
    segments = queries.day_usage_lanes(connection, ["dev-a", "dev-b"], *_window())
    # 两台设备各一段，一共两段，不能因为重叠被裁掉喵
    assert len(segments) == 2
    # 两段应用相同喵
    assert {item.app for item in segments} == {"Chrome"}
    # 两段区间都应覆盖 01:00-01:10 喵
    assert [item.start for item in segments] == [sampled - timedelta(seconds=600)] * 2
    # 两段的右端都落在采样时刻上喵
    assert [item.end for item in segments] == [sampled] * 2
    # 排序键是 (start, app, device_id)，所以设备顺序是 a 在前 b 在后喵
    assert [item.device_id for item in segments] == ["dev-a", "dev-b"]
    # 合计只算一份 600 秒，重叠部分不重复计喵
    assert queries.union_seconds(segments) == 600


def test_lanes_keep_disjoint_devices(connection: sqlite3.Connection) -> None:
    """两台设备时间完全不重叠：两段都在，合计等于两者之和喵。"""
    # A 设备 01:10 上报 600 秒，覆盖 01:00-01:10 喵
    _insert_usage(connection, "dev-a", "Chrome", 600, WINDOW_START + timedelta(hours=1, minutes=10))
    # B 设备 01:30 上报 300 秒，覆盖 01:25-01:30，与 A 完全错开喵
    _insert_usage(connection, "dev-b", "WeChat", 300, WINDOW_START + timedelta(hours=1, minutes=30))
    # 取泳道明细喵
    segments = queries.day_usage_lanes(connection, ["dev-a", "dev-b"], *_window())
    # 两段都在喵
    assert len(segments) == 2
    # 按开始时间升序，A 的段在前喵
    assert [item.device_id for item in segments] == ["dev-a", "dev-b"]
    # 两段时间不重叠，合计就是 600 + 300 = 900 秒喵
    assert queries.union_seconds(segments) == 900


def test_lanes_partial_overlap_union_dedupes(connection: sqlite3.Connection) -> None:
    """部分重叠：两段都保留，合计等于并集长度而不是简单相加喵。"""
    # A 设备 01:20 上报 1200 秒，覆盖 01:00-01:20 喵
    _insert_usage(connection, "dev-a", "Chrome", 1200, WINDOW_START + timedelta(hours=1, minutes=20))
    # B 设备 01:30 上报 1200 秒，覆盖 01:10-01:30，与 A 在 01:10-01:20 重叠喵
    _insert_usage(connection, "dev-b", "Chrome", 1200, WINDOW_START + timedelta(hours=1, minutes=30))
    # 取泳道明细喵
    segments = queries.day_usage_lanes(connection, ["dev-a", "dev-b"], *_window())
    # 重叠部分不裁剪，两段都要在喵
    assert len(segments) == 2
    # 两段各自的秒数保持原样喵
    assert [item.seconds for item in segments] == [1200, 1200]
    # 并集是 01:00-01:30 共 1800 秒（重叠的 10 分钟只算一次，不是 1200 + 1200 = 2400）喵
    assert queries.union_seconds(segments) == 1800


def test_lanes_merge_within_single_device(connection: sqlite3.Connection) -> None:
    """单台设备内部相邻采样仍按 merge_gap_seconds 合并成一段喵。"""
    # 三条采样每分钟一条，每条 60 秒，采样时刻就是各段的右端喵
    for offset_minutes in (1, 2, 3):
        # 逐条写入同一台设备的微信采样喵
        _insert_usage(
            connection,
            "dev-solo",
            "WeChat",
            60,
            WINDOW_START + timedelta(minutes=offset_minutes),
            package="wechat.exe",
        )
    # 取泳道明细喵
    segments = queries.day_usage_lanes(connection, "dev-solo", *_window())
    # 三条采样首尾相接，默认 5 秒阈值下应合并成一段喵
    assert len(segments) == 1
    # 合并后覆盖 01:00-01:03 喵
    assert segments[0].start == WINDOW_START + timedelta(minutes=0)
    # 右端落在最后一次采样时刻 01:03 喵
    assert segments[0].end == WINDOW_START + timedelta(minutes=3)
    # 秒数是三条之和 180 秒喵
    assert segments[0].seconds == 180
    # 设备 ID 必须填成来源设备喵
    assert segments[0].device_id == "dev-solo"


def test_lanes_respect_merge_gap(connection: sqlite3.Connection) -> None:
    """merge_gap_seconds 语义没坏：真实空档不合并，负数按 0 处理喵。"""
    # 第一条采样 00:00:20 上报 20 秒，覆盖 00:00:00-00:00:20 喵
    _insert_usage(connection, "dev-gap", "Code.exe", 20, WINDOW_START + timedelta(seconds=20))
    # 第二条采样 00:00:43 上报 20 秒，覆盖 00:00:23-00:00:43，中间空出 3 秒喵
    _insert_usage(connection, "dev-gap", "Code.exe", 20, WINDOW_START + timedelta(seconds=43))
    # 阈值给 0 时 3 秒空档不能合并，应是两段喵
    strict = queries.day_usage_lanes(connection, "dev-gap", *_window(), merge_gap_seconds=0)
    # 两段各自独立，秒数各为 20 喵
    assert [item.seconds for item in strict] == [20, 20]
    # 负阈值按 0 处理，段数应与阈值 0 时完全一致喵
    negative = queries.day_usage_lanes(connection, "dev-gap", *_window(), merge_gap_seconds=-10)
    # 段数与阈值 0 时相同喵
    assert [item.seconds for item in negative] == [20, 20]
    # 默认 5 秒阈值下 3 秒空档算抖动，会被合并成一段喵
    relaxed = queries.day_usage_lanes(connection, "dev-gap", *_window())
    # 只应剩一段喵
    assert len(relaxed) == 1
    # 合并后秒数是两条之和 40 秒喵
    assert relaxed[0].seconds == 40


def test_lanes_empty_device_list(connection: sqlite3.Connection) -> None:
    """空设备列表或空字符串都返回空列表，不能去查全表喵。"""
    # 先塞一条数据，防止"空列表返回空"是因为库里本来就没数据喵
    _insert_usage(connection, "dev-a", "Chrome", 600, WINDOW_START + timedelta(hours=1))
    # 空列表喵
    assert queries.day_usage_lanes(connection, [], *_window()) == []
    # 空字符串（等价于单台设备但 ID 是空）也应返回空列表喵
    assert queries.day_usage_lanes(connection, "", *_window()) == []
    # 全是空白的 ID 列表同样返回空列表喵
    assert queries.day_usage_lanes(connection, ["", "   "], *_window()) == []


def test_union_seconds_empty_returns_zero() -> None:
    """空列表的并集长度是 0 秒喵。"""
    # 直接传空列表喵
    assert queries.union_seconds([]) == 0


def test_union_seconds_handles_unordered_and_adjacent() -> None:
    """乱序输入、首尾相接、零宽段都要算对喵。"""
    # 直接手搓三段：01:00-01:30、01:10-01:20（被包含）、01:30-01:40（首尾相接）喵
    base = WINDOW_START + timedelta(hours=1)
    # 构造乱序的段列表喵
    segments = [
        queries.UsageSegment(
            start=base + timedelta(minutes=30),
            end=base + timedelta(minutes=40),
            app="A",
            package="",
            seconds=600,
        ),
        queries.UsageSegment(
            start=base,
            end=base + timedelta(minutes=30),
            app="B",
            package="",
            seconds=1800,
        ),
        queries.UsageSegment(
            start=base + timedelta(minutes=10),
            end=base + timedelta(minutes=20),
            app="C",
            package="",
            seconds=600,
        ),
    ]
    # 乱序也应按区间合并成 01:00-01:40 共 2400 秒喵
    assert queries.union_seconds(segments) == 2400
    # 零宽段不贡献长度喵
    assert queries.union_seconds([queries.UsageSegment(start=base, end=base, app="D", package="", seconds=0)]) == 0


def test_lanes_stay_inside_window(connection: sqlite3.Connection) -> None:
    """输出段不能越过 [start, end) 窗口喵。"""
    # 窗口左端附近的一条采样故意给足 60 秒，可用区间不够会被压缩喵
    _insert_usage(connection, "dev-left", "Chrome", 600, WINDOW_START + timedelta(seconds=10))
    # 窗口右端前 1 秒的一条采样，段尾只能落在采样时刻上喵
    _insert_usage(connection, "dev-right", "Code.exe", 300, WINDOW_START + WINDOW_LENGTH - timedelta(seconds=1))
    # 取泳道明细喵
    segments = queries.day_usage_lanes(connection, ["dev-left", "dev-right"], *_window())
    # 两段都在喵
    assert len(segments) == 2
    # 逐段检查窗口边界喵
    for segment in segments:
        # 起点不能早于窗口起点喵
        assert segment.start >= WINDOW_START
        # 终点不能晚于窗口右端喵
        assert segment.end <= WINDOW_START + WINDOW_LENGTH
        # 段的宽度不能为负喵
        assert segment.end > segment.start


def test_day_usage_segments_still_trims_lower_priority(connection: sqlite3.Connection) -> None:
    """老行为没被改坏：resolve_overlaps=True 时低优先级设备的重叠段仍被裁掉喵。"""
    # 两台设备在 01:00-01:10 完全重叠喵
    sampled = WINDOW_START + timedelta(hours=1, minutes=10)
    # 高优先级设备 A 上报 600 秒喵
    _insert_usage(connection, "dev-a", "Chrome", 600, sampled)
    # 低优先级设备 B 上报 600 秒喵
    _insert_usage(connection, "dev-b", "WeChat", 600, sampled)
    # 老接口按优先级裁剪喵
    trimmed = queries.day_usage_segments(connection, ["dev-a", "dev-b"], *_window(), resolve_overlaps=True)
    # 只剩高优先级那段喵
    assert len(trimmed) == 1
    # 留下的必须是 A 设备喵
    assert trimmed[0].device_id == "dev-a"
    # 秒数是完整的 600 秒喵
    assert trimmed[0].seconds == 600
    # 同样数据换成泳道接口则两段都在，证明新老口径各走各路喵
    lanes = queries.day_usage_lanes(connection, ["dev-a", "dev-b"], *_window())
    # 泳道保留两段喵
    assert len(lanes) == 2
    # 但合计只算一份 600 秒喵
    assert queries.union_seconds(lanes) == 600


def test_day_usage_segments_keeps_only_high_priority_for_same_app(connection: sqlite3.Connection) -> None:
    """两台设备同时用同一个应用：总轴仍只渲染高优先级那段，泳道才两段都留喵。"""
    # 两台设备在 01:00-01:10 同时用了 Chrome，采样时刻即段右端喵
    sampled = WINDOW_START + timedelta(hours=1, minutes=10)
    # 高优先级设备 A 的 Chrome 采样喵
    _insert_usage(connection, "dev-a", "Chrome", 600, sampled, package="chrome.exe")
    # 低优先级设备 B 的 Chrome 采样，与 A 完全重叠喵
    _insert_usage(connection, "dev-b", "Chrome", 600, sampled, package="chrome.exe")
    # 总轴口径按优先级裁剪，只剩高优先级设备那一段喵
    merged = queries.day_usage_segments(connection, ["dev-a", "dev-b"], *_window(), resolve_overlaps=True)
    # 总轴只有一段喵
    assert len(merged) == 1
    # 这一段必须来自高优先级设备 A 喵
    assert merged[0].device_id == "dev-a"
    # 总轴时间轴上不能出现低优先级设备的段喵
    assert "dev-b" not in {item.device_id for item in merged}
    # 泳道口径则为每台设备各保留一段，重叠不被裁剪喵
    lanes = queries.day_usage_lanes(connection, ["dev-a", "dev-b"], *_window())
    # 正好两段，一台一段喵
    assert len(lanes) == 2
    # 两台设备都出现在泳道里，低优先级那台没有消失喵
    assert {item.device_id for item in lanes} == {"dev-a", "dev-b"}
    # 两段都是同一个应用 Chrome 喵
    assert {item.app for item in lanes} == {"Chrome"}
    # 合计去重后仍是 600 秒，不因两段而翻倍喵
    assert queries.union_seconds(lanes) == 600

