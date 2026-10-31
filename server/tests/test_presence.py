"""在线状态与空档判定的单元测试喵。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.presence import KIND_AFK, KIND_OFFLINE, Heartbeat, build_presence

# 测试用的窗口起点喵
BASE = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)


def _beat(minute: int, second: int = 30, afk: bool = False) -> Heartbeat:
    """造一条心跳喵。"""
    # 按分钟偏移构造时间喵
    return Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=second), afk=afk)


def test_no_heartbeat_means_all_offline() -> None:
    """一次心跳都没有时整段窗口都算离线喵。"""
    # 十分钟窗口，没有任何心跳喵
    intervals, offline, afk = build_presence([], BASE, BASE + timedelta(minutes=10))
    # 离线 600 秒、空档 0 秒喵
    assert offline == 600
    assert afk == 0
    # 只有一个连续区间喵
    assert len(intervals) == 1
    assert intervals[0].kind == KIND_OFFLINE
    assert intervals[0].seconds == 600


def test_regular_heartbeat_is_online() -> None:
    """每分钟都有心跳且不在 AFK 时既不算离线也不算空档喵。"""
    # 每分钟一条心跳喵
    beats = [_beat(minute) for minute in range(10)]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 两者都为 0，没有区间喵
    assert offline == 0
    assert afk == 0
    assert intervals == []


def test_afk_heartbeat_counts_as_gap() -> None:
    """在线但 AFK 的分钟应算成空档喵。"""
    # 每分钟一条 AFK 心跳喵
    beats = [_beat(minute, afk=True) for minute in range(10)]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 空档 600 秒，离线 0 秒喵
    assert afk == 600
    assert offline == 0
    assert len(intervals) == 1
    assert intervals[0].kind == KIND_AFK


def test_heartbeat_gap_becomes_offline() -> None:
    """心跳中断超过超时时间后应判为离线喵。"""
    # 前两分钟有心跳，第 8 分钟才回来，超时 180 秒喵
    beats = [_beat(0), _beat(1), _beat(8)]
    intervals, offline, afk = build_presence(
        beats, BASE, BASE + timedelta(minutes=10), timeout_seconds=180
    )
    # 第 2-4 分钟仍被最后一条心跳覆盖，第 5-7 分钟离线喵
    assert offline == 180
    assert afk == 0
    # 离线区间从第 5 分钟开始喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    assert len(offline_intervals) == 1
    assert offline_intervals[0].start == BASE + timedelta(minutes=5)
    assert offline_intervals[0].end == BASE + timedelta(minutes=8)


def test_usage_span_wins_over_afk() -> None:
    """已经计入使用的分钟不再重复算成空档喵。"""
    # 全程 AFK 心跳喵
    beats = [_beat(minute, afk=True) for minute in range(10)]
    # 第 2-5 分钟有使用记录喵
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE + timedelta(minutes=2), BASE + timedelta(minutes=5))],
    )
    # 只剩 7 分钟算空档喵
    assert afk == 420
    assert offline == 0


def test_intervals_split_when_state_changes() -> None:
    """状态在离线和空档之间切换时应切成两段喵。"""
    # 前五分钟离线（没心跳），后五分钟 AFK 心跳喵
    beats = [_beat(minute, afk=True) for minute in range(5, 10)]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 两段区间，类型不同喵
    assert offline == 300
    assert afk == 300
    assert [item.kind for item in intervals] == [KIND_OFFLINE, KIND_AFK]


def test_empty_window_returns_zero() -> None:
    """窗口为空时返回全 0，不抛异常喵。"""
    # 起止相同喵
    intervals, offline, afk = build_presence([_beat(0)], BASE, BASE)
    assert intervals == []
    assert offline == 0
    assert afk == 0


def test_group_with_one_active_device_is_not_gap() -> None:
    """组里只要有一台设备在正常用，这一分钟就不算空档喵。"""
    # 两台设备：A 一直 AFK，B 一直活跃喵
    beats: list[Heartbeat] = []
    for minute in range(10):
        beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=10), afk=True, device_id="dev-a"))
        beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=20), afk=False, device_id="dev-b"))
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 有 B 在活跃，既不算离线也不算空档喵
    assert offline == 0
    assert afk == 0
    assert intervals == []


def test_group_all_afk_counts_as_gap() -> None:
    """组里在线的设备全都 AFK 时才算空档喵。"""
    # 两台设备都在 AFK 喵
    beats: list[Heartbeat] = []
    for minute in range(10):
        beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=10), afk=True, device_id="dev-a"))
        beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=20), afk=True, device_id="dev-b"))
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 十分钟全算空档喵
    assert afk == 600
    assert offline == 0


def test_group_offline_device_does_not_block_gap() -> None:
    """一台设备离线、另一台 AFK 时，这一分钟仍算空档而不是离线喵。"""
    # 只有 A 有心跳且 AFK，B 完全没有心跳喵
    beats = [
        Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=10), afk=True, device_id="dev-a")
        for minute in range(10)
    ]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 有设备在线，所以不算离线，全算空档喵
    assert offline == 0
    assert afk == 600


# 喵~注意：A 方案（按容差回补空档两端）已被 B 方案的精确边界取代，
# 代码保留在 presence._bridge_afk_gaps 里备用，这几个用例先跳过喵
A_SKIP = pytest.mark.skip(reason="A 方案已停用，改用 afk_since / active_since 精确边界（B 方案）")


@A_SKIP
def test_afk_bridge_reaches_previous_usage() -> None:
    """空档起点应回补到上一段使用的结束时刻，消掉上报延迟的缝喵。"""
    # 前 4 分钟在用，之后 6 分钟 AFK 心跳喵
    beats = [_beat(minute, afk=minute >= 4) for minute in range(10)]
    # 使用段结束在第 4 分 10 秒，AFK 心跳到第 4 分 30 秒才被看见，缝 20 秒喵
    usage_end = BASE + timedelta(minutes=4, seconds=10)
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE + timedelta(minutes=3), usage_end)],
        bridge_seconds=120,
    )
    # 空档起点被拉到使用段结尾喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].start == usage_end
    # 补缝之后总时长按区间重算：从使用段结尾算到窗口末尾喵
    assert afk == 350
    assert offline == 0


@A_SKIP
def test_afk_bridge_reaches_next_usage() -> None:
    """空档终点应延伸到下一段使用的开始时刻喵。"""
    # 前 5 分钟 AFK，第 5 分钟起恢复心跳喵
    beats = [_beat(minute, afk=minute < 5) for minute in range(10)]
    # 恢复后的第一段使用从第 5 分 20 秒才开始喵
    usage_start = BASE + timedelta(minutes=5, seconds=20)
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(usage_start, BASE + timedelta(minutes=9))],
        bridge_seconds=120,
    )
    # 空档终点被推到使用段开头喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].end == usage_start
    # 总时长按区间重算喵
    assert afk == 320
    assert offline == 0


@A_SKIP
def test_afk_bridge_skips_gap_beyond_tolerance() -> None:
    """缝隙超过容差时不能补，否则会把真没数据的时间也说成空档喵。"""
    # 前 2 分钟在用，之后 AFK 喵
    beats = [_beat(minute, afk=minute >= 2) for minute in range(10)]
    # 使用段结束在第 1 分钟，离空档起点超过 60 秒喵
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE, BASE + timedelta(minutes=1))],
        bridge_seconds=30,
    )
    # 原样不动，仍是整分钟累加喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert afk_intervals[0].start == BASE + timedelta(minutes=2)
    assert afk == 480


@A_SKIP
def test_afk_bridge_disabled_keeps_minutes() -> None:
    """容差为 0 时完全不动区间，行为与旧版一致喵。"""
    # 同样的场景，但关掉补缝喵
    beats = [_beat(minute, afk=minute >= 4) for minute in range(10)]
    usage_end = BASE + timedelta(minutes=4, seconds=10)
    intervals, _, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE + timedelta(minutes=3), usage_end)],
        bridge_seconds=0,
    )
    # 起点仍是整分钟（第 5 分钟，因为第 4 分钟有使用记录）喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert afk_intervals[0].start == BASE + timedelta(minutes=5)
    assert afk == 300


@A_SKIP
def test_afk_bridge_never_touches_offline() -> None:
    """离线区间不参与补缝，离线留空的语义保持不变喵。"""
    # 前 3 分钟没心跳（离线），之后 AFK 喵
    beats = [_beat(minute, afk=True) for minute in range(3, 10)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE - timedelta(minutes=5), BASE - timedelta(minutes=4))],
        bridge_seconds=600,
    )
    # 离线段原样保留喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    assert offline_intervals[0].start == BASE
    assert offline_intervals[0].end == BASE + timedelta(minutes=3)
    assert offline == 180


def test_afk_since_snaps_interval_start() -> None:
    """客户端给了 afk_since 时，空档起点应精确到那一刻而不是整分钟喵。"""
    # 前 4 分钟在用，第 4 分钟起 AFK，客户端说"停止计时"发生在第 3 分 25 秒喵
    since = BASE + timedelta(minutes=3, seconds=25)
    beats = [_beat(minute) for minute in range(4)]
    beats += [
        Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=30), afk=True, afk_since=since)
        for minute in range(4, 10)
    ]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 空档从精确时刻开始喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].start == since
    assert afk_intervals[0].end == BASE + timedelta(minutes=10)
    # 总时长按精确边界算喵
    assert afk == 395
    assert offline == 0


def test_active_since_snaps_interval_end() -> None:
    """客户端给了 active_since 时，空档终点应精确到恢复计时那一刻喵。"""
    # 前 5 分钟 AFK，第 5 分钟恢复，恢复时刻是第 5 分 10 秒喵
    resumed = BASE + timedelta(minutes=5, seconds=10)
    beats = [
        Heartbeat(reported_at=BASE + timedelta(minutes=minute, seconds=30), afk=True)
        for minute in range(5)
    ]
    beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=5, seconds=30), afk=False, active_since=resumed))
    beats += [_beat(minute) for minute in range(6, 10)]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 终点精确，起点没有精确时刻所以保持整分钟喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].start == BASE
    assert afk_intervals[0].end == resumed
    # 从 0 点到 5 分 10 秒共 310 秒喵
    assert afk == 310
    assert offline == 0


def test_afk_since_ignored_when_too_far() -> None:
    """afk_since 与整分钟结果相差超出容差时不采用，保持整分钟喵。"""
    # 第 5 分钟起 AFK，但客户端说从第 0 分 30 秒就开始了，偏差 4 分半喵
    beats = [_beat(minute) for minute in range(5)]
    beats += [
        Heartbeat(
            reported_at=BASE + timedelta(minutes=minute, seconds=30),
            afk=True,
            afk_since=BASE + timedelta(seconds=30),
        )
        for minute in range(5, 10)
    ]
    intervals, _, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    # 边界保持整分钟喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert afk_intervals[0].start == BASE + timedelta(minutes=5)
    assert afk == 300


def test_afk_since_clipped_to_window_start() -> None:
    """afk_since 早于窗口起点时夹到窗口起点喵。"""
    # 窗口从 0 点开始，客户端说昨天就 AFK 了喵
    beats = [
        Heartbeat(
            reported_at=BASE + timedelta(minutes=minute, seconds=30),
            afk=True,
            afk_since=BASE - timedelta(minutes=30),
        )
        for minute in range(10)
    ]
    intervals, _, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert afk_intervals[0].start == BASE
    assert afk == 600


def test_old_client_without_boundaries_keeps_minutes() -> None:
    """旧客户端不带边界时刻时，结果必须和以前完全一致喵。"""
    # 只有 afk 标记，没有任何边界字段喵
    beats = [_beat(minute, afk=minute >= 4) for minute in range(10)]
    intervals, offline, afk = build_presence(beats, BASE, BASE + timedelta(minutes=10))
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert afk_intervals[0].start == BASE + timedelta(minutes=4)
    assert afk == 360
    assert offline == 0

def test_afk_since_leaves_no_blank_after_usage() -> None:
    """实测的 65 秒错位：使用结束到 afk=true 上报之间不应再出现空白分钟喵。"""
    # 使用一直记到第 4 分 03 秒喵
    usage_end = BASE + timedelta(minutes=4, seconds=3)
    # 前 4 分钟正常在用喵
    beats = [_beat(minute) for minute in range(4)]
    # 第 4 分 03 秒那次上报还带着使用时长，所以 afk=false 喵
    beats.append(Heartbeat(reported_at=usage_end, afk=False))
    # 之后每 65 秒上报一次（实测节奏），客户端把"停止计时"回溯到 usage_end 喵
    beats += [
        Heartbeat(
            reported_at=usage_end + timedelta(seconds=65 * index),
            afk=True,
            afk_since=usage_end,
        )
        for index in range(1, 6)
    ]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE, usage_end)],
    )
    # 空档正好从使用结束那一刻开始，中间不留任何空白喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].start == usage_end
    # 设备一直有心跳，不算离线喵
    assert offline == 0
    # 空档时长从使用结束算到窗口末尾喵
    assert afk == 357

def test_usage_minute_stays_active_even_if_heartbeat_says_afk() -> None:
    """这一分钟里有使用时长就算在用，哪怕同一条心跳已经写着 afk=true 喵。"""
    # 前 4 分钟在用，第 5 分钟心跳直接写着 afk=true 但同批还带着使用时长喵
    beats = [_beat(minute) for minute in range(4)]
    beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=4, seconds=30), afk=True))
    beats += [_beat(minute, afk=True) for minute in range(5, 10)]
    # 使用时长覆盖第 4 分 10 秒到第 4 分 50 秒喵
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE + timedelta(minutes=4, seconds=10), BASE + timedelta(minutes=4, seconds=50))],
    )
    # 第 4 分钟有使用，那 40 秒仍是色块；空档从使用结束那一刻开始，不留空白喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    assert afk_intervals[0].start == BASE + timedelta(minutes=4, seconds=50)
    # 从第 4 分 50 秒到第 10 分钟共 310 秒、离线 0 秒喵
    assert afk == 310
    assert offline == 0

def test_short_afk_between_reports_draws_hatch() -> None:
    """实测的 85 秒空白：整段 AFK 夹在两条上报之间时也要画出斜纹喵。"""
    # 第 1 分 30 秒那次上报还带着使用时长，所以 afk=false 喵
    beats = [_beat(0), Heartbeat(reported_at=BASE + timedelta(minutes=1, seconds=30), afk=False)]
    # 第 2 分 20 秒开始空闲，客户端把"停止计时"落在同一刻喵
    afk_start = BASE + timedelta(minutes=2, seconds=20)
    beats.append(Heartbeat(reported_at=afk_start, afk=True, afk_since=afk_start))
    # 第 3 分 25 秒仍在空闲，这是整段里唯一一条 afk=true 的心跳喵
    beats.append(
        Heartbeat(reported_at=BASE + timedelta(minutes=3, seconds=25), afk=True, afk_since=afk_start)
    )
    # 第 3 分 50 秒回来，恢复计时那一刻就是空档终点喵
    resume = BASE + timedelta(minutes=3, seconds=50)
    beats.append(Heartbeat(reported_at=resume, afk=False, active_since=resume))
    # 之后每 65 秒一次正常上报喵
    beats += [_beat(minute, second=55) for minute in range(4, 10)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        # 离开前记到第 2 分 20 秒，回来后又记了 5 秒（3 分 45 到 3 分 50）喵
        usage_spans=[
            (BASE + timedelta(minutes=1, seconds=30), afk_start),
            (resume - timedelta(seconds=5), resume),
        ],
    )
    # 空档必须真的存在，否则色块之间就是一条空白喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1
    # 两端都精确到客户端给的时刻喵
    assert afk_intervals[0].start == afk_start
    assert afk_intervals[0].end == resume
    # 2 分 20 秒到 3 分 50 秒共 90 秒喵
    assert afk == 90
    # 设备一直有心跳，不算离线喵
    assert offline == 0


def test_short_afk_survives_tail_usage_deduction() -> None:
    """实测缺陷：10 秒短空档被边界那 1 秒使用扣成 9 秒后不该被丢掉喵。

    真实上报是这样的：AFK 边界那一帧往往还带着 1-2 秒残留使用量，
    这 1-2 秒会从 AFK 碎片尾部扣掉。阈值原来是 10 秒，
    于是 10-11 秒的真实短空档只剩 8-9 秒被误判成噪声丢弃，
    时间轴上表现为两个使用色块之间留 6-10 秒空白喵。
    """
    # 第 1 分钟内一直在用喵
    beats = [_beat(0)]
    # 第 1 分 50 秒这一帧带 1 秒使用，afk=false 喵
    beats.append(Heartbeat(reported_at=BASE + timedelta(minutes=1, seconds=50), afk=False))
    # 同一刻进入空档，客户端把停表时刻精确回溯到这里喵
    afk_start = BASE + timedelta(minutes=1, seconds=50)
    beats.append(Heartbeat(reported_at=afk_start, afk=True, afk_since=afk_start))
    # 10 秒后（第 2 分钟整）就回来了喵
    resume = BASE + timedelta(minutes=2)
    beats.append(Heartbeat(reported_at=resume, afk=False, active_since=resume))
    # 之后正常上报喵
    beats += [_beat(minute, second=5) for minute in range(3, 10)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        # 喵~注意：关键在最后这一段——恢复那一刻带 1 秒使用，会从空档尾部扣掉 1 秒喵
        usage_spans=[
            (BASE, afk_start),
            (resume - timedelta(seconds=1), resume),
        ],
    )
    # 空档必须还在，否则时间轴上就是一条空白喵
    afk_intervals = [item for item in intervals if item.kind == KIND_AFK]
    assert len(afk_intervals) == 1, "短空档被当成噪声丢掉了"
    # 起点精确到客户端给的停表时刻喵
    assert afk_intervals[0].start == afk_start
    # 末尾被那 1 秒使用占掉，剩 9 秒仍然保留喵
    assert afk_intervals[0].end == resume - timedelta(seconds=1)
    # 空档时长 9 秒喵
    assert afk == 9
    # 设备一直有心跳，不算离线喵
    assert offline == 0


def test_usage_wins_over_offline_when_client_reports_late() -> None:
    """断网后补报历史时，使用段要盖过按心跳算出的离线喵。

    喵~注意：这是主人确认的口径——离线的依据只是"没收到心跳"，
    而使用记录是客户端逐轮累计的真实秒数，证据更强，所以使用优先喵。
    """
    # 只在开头有心跳，之后断网一小时，末尾才恢复喵
    beats = [_beat(0)]
    beats += [_beat(60 + index) for index in range(11)]
    # 客户端补报了断网这一小时的使用量喵
    usage = [(BASE, BASE + timedelta(hours=1))]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(hours=1, minutes=11),
        usage_spans=usage,
    )
    # 离线段必须被裁光，不能和使用段重叠喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    for item in offline_intervals:
        for usage_start, usage_end in usage:
            low = max(item.start, usage_start)
            high = min(item.end, usage_end)
            assert high <= low, f"离线段 {item.start}→{item.end} 与使用段重叠了"
    # 整段都有使用记录，离线时长应当是 0 喵
    assert offline == 0


def test_offline_kept_when_usage_only_covers_part() -> None:
    """断网期间只有一部分时间在用，剩下的部分仍要如实算离线喵。"""
    # 只在开头有心跳，之后断网，末尾恢复喵
    beats = [_beat(0)]
    beats += [_beat(60 + index) for index in range(11)]
    # 补报的使用只覆盖断网期的前 20 分钟喵
    usage = [(BASE, BASE + timedelta(minutes=20))]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(hours=1, minutes=11),
        usage_spans=usage,
    )
    # 断网期的后 40 分钟必须仍然算离线喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    assert offline_intervals, "没有被使用覆盖的那部分离线丢了"
    # 离线的起点要落在使用段结束之后喵
    usage_end = BASE + timedelta(minutes=20)
    for item in offline_intervals:
        assert item.start >= usage_end or item.end <= BASE, "离线段压到使用段上了"
    # 离线时长应当接近 40 分钟（按整分钟判定会略有出入）喵
    assert 30 * 60 <= offline <= 45 * 60


def test_residual_fill_never_turns_offline_into_afk() -> None:
    """心跳消失的时段必须判离线，兜底填充绝不能把它改成空档喵。

    喵~注意：这是主人最在意的一条——离线数据必须绝对真实。
    兜底填充只负责使用段之间的微小缝隙，一旦心跳停了就该是离线喵。
    """
    # 只在头两分钟有心跳，之后彻底消失喵
    beats = [_beat(0), _beat(1)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE, BASE + timedelta(minutes=1))],
    )
    # 必须有离线段喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    assert offline_intervals, "心跳消失却没有判出离线"
    # 离线必须一直延伸到窗口末尾附近喵
    assert max(item.end for item in offline_intervals) >= BASE + timedelta(minutes=8)
    # 心跳消失之后的时段里绝不允许出现空档喵
    for item in intervals:
        if item.kind == KIND_AFK:
            assert item.start < BASE + timedelta(minutes=5), "心跳消失后出现了空档"


def test_gap_before_offline_is_filled() -> None:
    """设备判离线时，判定时刻与最后一段使用之间不能留白喵。

    喵~注意：这就是主人报的那条 issue——客户端掉线后，
    "最后一段使用结束"和"离线判定起点"之间常常漏着一截没记录的空隙，
    时间轴上就是一条白线。这截必须被补上，按心跳归属成空档或离线喵。
    """
    # 心跳只到第 80 秒就断了喵
    beats = [_beat(0, second=0), _beat(1, second=20)]
    # 使用只记到第 40 秒喵
    usage_end = BASE + timedelta(seconds=40)
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        usage_spans=[(BASE, usage_end)],
    )
    # 把状态区间和使用段合起来，检查有没有漏白喵
    covered = sorted(
        [(item.start, item.end) for item in intervals] + [(BASE, usage_end)],
        key=lambda pair: pair[0],
    )
    cursor = BASE
    holes: list[tuple] = []
    for left, right in covered:
        if right <= cursor:
            continue
        if left > cursor:
            holes.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < BASE + timedelta(minutes=10):
        holes.append((cursor, BASE + timedelta(minutes=10)))
    # 喵~注意：这是本条的验收点——一处空隙都不许有喵
    assert not holes, f"最后使用与离线判定之间漏了 {len(holes)} 处空隙"
    # 离线段要紧接最后一段使用开始喵
    offline_intervals = [item for item in intervals if item.kind == KIND_OFFLINE]
    assert offline_intervals, "没有判出离线"
    assert min(item.start for item in offline_intervals) <= usage_end + timedelta(minutes=1)


def test_online_gap_without_offline_is_left_alone() -> None:
    """全程在线时中间没用应用的空窗不补，否则 afk 时长会被算多喵。

    喵~注意：这条是主人明确过的边界——在线期间"没开任何应用"是合法状态，
    不能为了消白线就一律填成空档喵。
    """
    # 每 30 秒一条心跳，全程在线喵
    beats = [_beat(minute, second=second) for minute in range(11) for second in (0, 30)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        # 第 4 分钟到第 4 分 10 秒之间留 10 秒空窗喵
        usage_spans=[
            (BASE, BASE + timedelta(minutes=4)),
            (BASE + timedelta(minutes=4, seconds=10), BASE + timedelta(minutes=10)),
        ],
    )
    # 全程有心跳，不该有离线喵
    assert offline == 0
    # 喵~注意：在线且没判离线时空窗保持原样，afk 必须是 0 喵
    assert afk == 0, "在线期间的空窗被误填成空档了"


def test_residual_fill_skips_gap_beyond_limit() -> None:
    """超过兜底上限的缝隙不补，交给整分钟判定，避免把大段空白说成空档喵。"""
    # 全程有心跳喵
    beats = [_beat(minute) for minute in range(11)]
    intervals, offline, afk = build_presence(
        beats,
        BASE,
        BASE + timedelta(minutes=10),
        # 留一条 100 秒的大缝，远超 RESIDUAL_AFK_SECONDS 喵
        usage_spans=[
            (BASE, BASE + timedelta(minutes=2)),
            (BASE + timedelta(minutes=3, seconds=40), BASE + timedelta(minutes=10)),
        ],
    )
    # 喵~注意：这里只验证不抛异常且不误判离线，缝隙归属由整分钟规则决定喵
    assert offline == 0
    assert afk >= 0
