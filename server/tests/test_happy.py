"""happy 状态判定的测试：三档状态、优先级与设备组喵。

喵~注意：判定全部以传进去的 now 为准，这里把 now 钉死避免跟着真实时钟漂移喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import people
from app.bot import happy

# 基准时间固定喵
BASE_NOW = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)


def _stamp(moment: datetime) -> str:
    """转成库里用的 UTC 文本喵。"""
    # 统一成 Z 结尾喵
    return moment.isoformat().replace("+00:00", "Z")


def _seed_device(
    connection: sqlite3.Connection,
    device_id: str,
    name: str,
    *,
    last_seen: datetime | None = None,
    afk: bool = False,
    battery: int | None = None,
) -> None:
    """插一台设备喵。"""
    # 默认在线：最近上报等于基准时间喵
    seen = last_seen if last_seen is not None else BASE_NOW
    connection.execute(
        "INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json, "
        "first_seen_at, last_seen_at, role, afk) "
        "VALUES (?, ?, ?, '', '{}', ?, ?, 'workstation', ?)",
        (
            device_id,
            "android" if device_id.startswith("and-") else "windows",
            name,
            _stamp(seen),
            _stamp(seen),
            1 if afk else 0,
        ),
    )
    # 有电量时补一条采样喵
    if battery is not None:
        connection.execute(
            "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, ?, 0)",
            (device_id, _stamp(seen), battery),
        )
    connection.commit()


def _seed_usage(connection: sqlite3.Connection, device_id: str, seconds: int, ago: int, app: str = "Code.exe") -> None:
    """插一条使用采样喵。"""
    # 采样时刻由「多久之前」算出来喵
    moment = BASE_NOW - timedelta(seconds=ago)
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, '', ?, ?)",
        (device_id, app, _stamp(moment), seconds),
    )
    connection.commit()


def _set_group(config, devices: tuple[str, ...], name: str = "主人") -> None:
    """写设备组喵。"""
    # 直接用 people 保存喵
    people.save_people(config.server.db_path, [people.PersonGroup(name=name, devices=devices)])


# ==================== 设备组查找 ====================


def test_load_happy_devices_requires_group(connection: sqlite3.Connection, app_config) -> None:
    """没有主人组时要给出可操作的提示喵。"""
    # 造设备但不建组喵
    _seed_device(connection, "win-a", "本机 Windows")
    # 应报错并提示去建组喵
    with pytest.raises(happy.HappyError) as error:
        happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert "主人" in str(error.value)


def test_load_happy_devices_requires_members(connection: sqlite3.Connection, app_config) -> None:
    """组是空的同样没法回答喵。"""
    # 建一个空组喵
    _set_group(app_config, ())
    with pytest.raises(happy.HappyError) as error:
        happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert "还没有设备" in str(error.value)


def test_load_happy_devices_requires_registered(connection: sqlite3.Connection, app_config) -> None:
    """组里写着的设备全都没上报过时要提示启动客户端喵。"""
    # 组里写一个不存在的设备喵
    _set_group(app_config, ("ghost-device",))
    with pytest.raises(happy.HappyError) as error:
        happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert "还没有上报过数据" in str(error.value)


def test_load_happy_devices_keeps_group_order(connection: sqlite3.Connection, app_config) -> None:
    """组内顺序就是优先级喵。"""
    # 故意让手机排在前面喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_device(connection, "and-b", "手机")
    _set_group(app_config, ("and-b", "win-a"))
    # 读出来应是手机在前喵
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert [device.name for device in devices] == ["手机", "本机 Windows"]
    assert [device.priority for device in devices] == [0, 1]


def test_load_happy_devices_skips_missing(connection: sqlite3.Connection, app_config) -> None:
    """组里有的设备没上报过时应跳过而不是整体报错喵。"""
    # 一台有数据、一台没有喵
    _seed_device(connection, "win-a", "本机 Windows")
    _set_group(app_config, ("ghost", "win-a"))
    # 只应读出有数据的那台喵
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert [device.name for device in devices] == ["本机 Windows"]


# ==================== 三档状态 ====================


def test_state_active_needs_recent_usage(connection: sqlite3.Connection, app_config) -> None:
    """最近 3 分钟有使用记录且在线时判为正在使用喵。"""
    # 造设备与一分钟前的使用喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_usage(connection, "win-a", 60, 60)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 判定喵
    state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state == happy.STATE_ACTIVE
    assert device is not None and device.name == "本机 Windows"


def test_state_active_requires_online(connection: sqlite3.Connection, app_config) -> None:
    """设备离线时不算正在使用喵。"""
    # 造一台离线设备，但一分钟前有使用喵
    _seed_device(connection, "win-a", "本机 Windows", last_seen=BASE_NOW - timedelta(hours=2))
    _seed_usage(connection, "win-a", 60, 60)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 应不是 active 喵
    state, _device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state != happy.STATE_ACTIVE


def test_state_active_ignores_tiny_usage(connection: sqlite3.Connection, app_config) -> None:
    """一秒的误采样不该点亮状态喵。"""
    # 造一条只有一秒的采样喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_usage(connection, "win-a", 1, 30)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 不该判为 active 喵
    state, _device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state != happy.STATE_ACTIVE


def test_state_afk_needs_flag_and_usage(connection: sqlite3.Connection, app_config) -> None:
    """在线 + AFK + 十分钟内用过，判为挂机喵。"""
    # 造设备：AFK，五分钟前用过喵
    _seed_device(connection, "win-a", "本机 Windows", afk=True)
    _seed_usage(connection, "win-a", 120, 5 * 60)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 判定喵
    state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state == happy.STATE_AFK
    assert device is not None and device.name == "本机 Windows"


def test_state_afk_requires_usage(connection: sqlite3.Connection, app_config) -> None:
    """AFK 但十分钟内没用过就是没人用，不算挂机喵。"""
    # 造设备：AFK，但一小时前才用过喵
    _seed_device(connection, "win-a", "本机 Windows", afk=True)
    _seed_usage(connection, "win-a", 120, 60 * 60)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 不该是挂机喵
    state, _device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state != happy.STATE_AFK


def test_state_away_when_stale(connection: sqlite3.Connection, app_config) -> None:
    """很久没用过时判为不在，并给出最近一次设备喵。"""
    # 造设备：三小时前用过喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_usage(connection, "win-a", 300, 3 * 3600)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 判定喵
    state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state == happy.STATE_AWAY
    assert device is not None and device.name == "本机 Windows"
    assert device.last_usage is not None


def test_state_away_without_any_usage(connection: sqlite3.Connection, app_config) -> None:
    """从来没有使用记录时连设备都不给喵。"""
    # 造设备但不造使用记录喵
    _seed_device(connection, "win-a", "本机 Windows")
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 判定喵
    state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state == happy.STATE_AWAY
    assert device is None


# ==================== 优先级 ====================


def test_priority_picks_first_device(connection: sqlite3.Connection, app_config) -> None:
    """两台都符合条件时取组内顺序靠前的那台喵。"""
    # 两台设备都有近期使用喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_device(connection, "and-b", "手机")
    _seed_usage(connection, "win-a", 60, 60)
    _seed_usage(connection, "and-b", 60, 60)
    # 手机排在组内第一位喵
    _set_group(app_config, ("and-b", "win-a"))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    # 应选手机喵
    state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert state == happy.STATE_ACTIVE
    assert device is not None and device.name == "手机"


def test_priority_falls_through_to_second(connection: sqlite3.Connection, app_config) -> None:
    """第一台不符合条件时顺延到第二台喵。"""
    # 手机没有使用记录，本机有一分钟前的喵
    _seed_device(connection, "and-b", "手机")
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_usage(connection, "win-a", 60, 60)
    _set_group(app_config, ("and-b", "win-a"))
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    # 应选本机喵
    _state, device, _reason = happy.judge_state(connection, devices, BASE_NOW)
    assert device is not None and device.name == "本机 Windows"


def test_most_recent_usage_across_devices(connection: sqlite3.Connection, app_config) -> None:
    """跨设备取最近一次使用喵。"""
    # 本机一分钟前、手机十分钟前喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_device(connection, "and-b", "手机")
    _seed_usage(connection, "win-a", 60, 60)
    _seed_usage(connection, "and-b", 60, 600)
    _set_group(app_config, ("and-b", "win-a"))
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    # 快照里的最近设备应是本机喵
    snapshot_view = happy.best_snapshot(connection, app_config, BASE_NOW)
    assert snapshot_view.last_usage_device == "本机 Windows"
    assert snapshot_view.last_usage is not None


# ==================== 电量与时长 ====================


def test_battery_and_usage_totals(connection: sqlite3.Connection, app_config) -> None:
    """电量与近 24 小时总时长都要带出来喵。"""
    # 造手机：电量 30%，用了两次各 600 秒喵
    _seed_device(connection, "and-b", "手机", battery=30)
    _seed_usage(connection, "and-b", 600, 3600)
    _seed_usage(connection, "and-b", 600, 7200)
    _set_group(app_config, ("and-b",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    # 电量与时长都要对喵
    assert devices[0].battery_percent == 30
    assert devices[0].usage_24h_seconds == 1200


def test_windows_device_has_no_battery(connection: sqlite3.Connection, app_config) -> None:
    """没有电量采样的设备电量应为 None，模板据此走分支喵。"""
    # 造本机但不造电量喵
    _seed_device(connection, "win-a", "本机 Windows")
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    assert devices[0].battery_percent is None


def test_active_device_window(connection: sqlite3.Connection, app_config) -> None:
    """指定窗口内挑设备的函数要按窗口算喵。"""
    # 造设备：五小时前用过喵
    _seed_device(connection, "win-a", "本机 Windows")
    _seed_usage(connection, "win-a", 600, 5 * 3600)
    _set_group(app_config, ("win-a",))
    devices = happy.load_happy_devices(connection, app_config, BASE_NOW)
    _set_group(app_config, ("win-a",))
    # 十分钟窗口里没有喵
    assert happy.active_device(connection, devices, BASE_NOW, 600) is None
    # 六小时窗口里有喵
    found = happy.active_device(connection, devices, BASE_NOW, 6 * 3600)
    assert found is not None and found.name == "本机 Windows"
