"""看看happy 出图命令的测试：两条分支与截图参数透传喵。

喵~注意：旧的 /排行图 与 /时间轴图 已随命令重构删除，
这里改成测 /看看happy 的排行榜与时间轴两条分支喵。
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import people
from app.bot import commands, router, snapshot

# 基准时间固定，避免测试跟真实时钟漂移喵
BASE_NOW = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)


def _seed(connection: sqlite3.Connection, device_id: str, name: str, *, online: bool = True) -> None:
    """插一台设备，默认在线喵。"""
    # 在线时最近上报就是基准时间，离线时往回推很久喵
    last_seen = BASE_NOW if online else BASE_NOW - timedelta(hours=5)
    stamp = last_seen.isoformat().replace("+00:00", "Z")
    connection.execute(
        "INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json, "
        "first_seen_at, last_seen_at, role) VALUES (?, ?, ?, '', '{}', ?, ?, 'workstation')",
        (
            device_id,
            "android" if device_id.startswith("and-") else "windows",
            name,
            stamp,
            stamp,
        ),
    )
    connection.commit()


def _set_group(config, groups: list[people.PersonGroup]) -> None:
    """把设备组写进临时 people.json 喵。"""
    # 直接用 people 模块的保存函数喵
    people.save_people(config.server.db_path, groups)


def _context(connection: sqlite3.Connection, config, args: tuple[str, ...], name: str = "看看happy"):
    """造一个命令上下文喵。"""
    # 基准时间固定喵
    return commands.CommandContext(
        connection=connection, config=config, name=name, args=args, now=BASE_NOW
    )


# ==================== 纯函数：窗口反算 ====================


def test_zoom_for_window_half_hour() -> None:
    """半小时窗口应算出 48 倍喵。"""
    # 1440 / 30 = 48 喵
    assert commands.zoom_for_window("00:00", "00:30") == 48


def test_zoom_for_window_one_hour() -> None:
    """一小时窗口应算出 24 倍喵。"""
    # 1440 / 60 = 24 喵
    assert commands.zoom_for_window("09:00", "10:00") == 24


def test_zoom_for_window_quarter_hour() -> None:
    """一刻钟窗口应算出 96 倍喵。"""
    # 1440 / 15 = 96 喵
    assert commands.zoom_for_window("00:40", "00:55") == 96


def test_zoom_for_window_capped() -> None:
    """窗口太短时倍数要夹到上限，非法窗口返回 0喵。"""
    # 一分钟窗口要 1440 倍，仍在 8640 上限内喵
    assert commands.zoom_for_window("00:00", "00:01") == 1440
    # 窗口为零或倒序时返回 0 表示不缩放喵
    assert commands.zoom_for_window("10:00", "10:00") == 0
    assert commands.zoom_for_window("12:00", "09:00") == 0


# ==================== 看看happy：排行榜分支 ====================


def test_look_rank_defaults_to_24h(connection: sqlite3.Connection, app_config) -> None:
    """不写窗口时默认 24 小时喵。"""
    # 造一台设备并放进主人组喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑排行榜分支喵
    scope = commands._look_happy_scope(_context(connection, app_config, ("全部", "排行榜")))
    # 窗口应是 24 小时喵
    assert scope["window_seconds"] == 24 * 3600
    assert scope["device_ids"] == ["win-a"]
    # 不是时间轴分支喵
    assert not scope.get("is_timeline")


def test_look_rank_window_capped_to_7_days(connection: sqlite3.Connection, app_config) -> None:
    """窗口超过 7 天要夹到 7 天，和保留期对齐喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写一个 30 天喵
    scope = commands._look_happy_scope(_context(connection, app_config, ("全部", "排行榜", "30天")))
    # 应被夹到 7 天喵
    assert scope["window_seconds"] == 7 * 24 * 3600


def test_look_rank_bad_window_raises(connection: sqlite3.Connection, app_config) -> None:
    """窗口写错时报错，不能静默按默认值跑喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写一个看不懂的窗口喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(_context(connection, app_config, ("全部", "排行榜", "很久")))
    assert "时间窗口看不懂" in str(error.value)


def test_look_rank_device_by_name(connection: sqlite3.Connection, app_config) -> None:
    """按设备名选范围时只给那一台喵。"""
    # 两台设备喵
    _seed(connection, "win-a", "本机 Windows")
    _seed(connection, "and-b", "手机")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("and-b", "win-a"))])
    # 点名手机喵
    scope = commands._look_happy_scope(_context(connection, app_config, ("手机", "排行榜")))
    # 只应包含手机喵
    assert scope["device_ids"] == ["and-b"]


def test_look_rank_device_by_prefix(connection: sqlite3.Connection, app_config) -> None:
    """设备名支持前缀匹配，ID 也支持喵。"""
    # 两台设备喵
    _seed(connection, "win-a", "本机 Windows")
    _seed(connection, "and-b", "手机")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("and-b", "win-a"))])
    # 名字前缀喵
    by_name = commands._look_happy_scope(_context(connection, app_config, ("本机", "排行榜")))
    assert by_name["device_ids"] == ["win-a"]
    # ID 前缀喵
    by_id = commands._look_happy_scope(_context(connection, app_config, ("and-", "排行榜")))
    assert by_id["device_ids"] == ["and-b"]


def test_look_rank_unknown_device_raises(connection: sqlite3.Connection, app_config) -> None:
    """拼不出设备时要把可用的列出来喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写一个不存在的名字喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(_context(connection, app_config, ("冰箱", "排行榜")))
    assert "在happy组里找不到" in str(error.value)


# ==================== 看看happy：时间轴分支 ====================


def test_look_timeline_defaults_to_today(connection: sqlite3.Connection, app_config) -> None:
    """不写日期时默认今天，不写时刻时给默认窗口喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑时间轴分支喵
    scope = commands._look_happy_scope(_context(connection, app_config, ("全部", "时间轴")))
    # 应标记为时间轴分支喵
    assert scope["is_timeline"]
    # 默认从 00:00 开始喵
    assert scope["moment_start"] == "00:00"
    # 终点应晚于起点喵
    assert commands._clock_minutes(scope["moment_end"]) > 0
    # 日期是今天喵
    assert scope["start_text"] == "2026-11-01"


def test_look_timeline_explicit_window(connection: sqlite3.Connection, app_config) -> None:
    """写了起止时刻就照抄喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 给一个窗口喵
    scope = commands._look_happy_scope(
        _context(connection, app_config, ("全部", "时间轴", "09:00", "12:00"))
    )
    assert scope["moment_start"] == "09:00"
    assert scope["moment_end"] == "12:00"


def test_look_timeline_explicit_date(connection: sqlite3.Connection, app_config) -> None:
    """写了日期就用那天喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 指定过去的一天喵
    scope = commands._look_happy_scope(
        _context(connection, app_config, ("全部", "时间轴", "2026-10-30"))
    )
    assert scope["start_text"] == "2026-10-30"
    # 过去的日期已经过完，默认终点应是 23:59 喵
    assert scope["moment_end"] == "23:59"


def test_look_timeline_rejects_reversed_window(connection: sqlite3.Connection, app_config) -> None:
    """起止写反时要报错喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写反喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(
            _context(connection, app_config, ("全部", "时间轴", "12:00", "09:00"))
        )
    assert "晚于起点" in str(error.value)


def test_look_timeline_rejects_three_moments(connection: sqlite3.Connection, app_config) -> None:
    """三个时刻没法判断意图，应报错喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写三个时刻喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(
            _context(connection, app_config, ("全部", "时间轴", "08:00", "09:00", "10:00"))
        )
    assert "最多写起止两个时刻" in str(error.value)


# ==================== 看看happy：子命令分流 ====================


def test_look_happy_requires_two_args(connection: sqlite3.Connection, app_config) -> None:
    """只写范围没写子命令时要给用法喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 只给一个参数喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(_context(connection, app_config, ("全部",)))
    assert "用法" in str(error.value)


def test_look_happy_rejects_unknown_subcommand(connection: sqlite3.Connection, app_config) -> None:
    """子命令认不出时要提示两种写法喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 写一个不存在的子命令喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._look_happy_scope(_context(connection, app_config, ("全部", "曲线")))
    assert "只能是" in str(error.value)


def test_look_happy_alias_subcommands(connection: sqlite3.Connection, app_config) -> None:
    """排行/时间轴 等简写也要认喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 排行榜简写喵
    rank_scope = commands._look_happy_scope(_context(connection, app_config, ("全部", "排行")))
    assert not rank_scope.get("is_timeline")
    # 时间轴简写喵
    timeline_scope = commands._look_happy_scope(_context(connection, app_config, ("全部", "timeline")))
    assert timeline_scope["is_timeline"]


# ==================== 截图参数透传 ====================


def _capture_params(monkeypatch: pytest.MonkeyPatch, text: str, connection, config) -> dict[str, str]:
    """跑一遍 build_image 并抓出传给截图函数的参数喵。"""
    # 记录参数喵
    captured: dict[str, object] = {}

    def fake_capture(base_url: str, token: str, tab: str, params: dict[str, str], **kwargs: object) -> bytes:
        """假的截图函数喵。"""
        captured["tab"] = tab
        captured["params"] = dict(params)
        return b"\x89PNG-fake"

    # 替换截图并放行可用性检查喵
    monkeypatch.setattr(snapshot, "capture_dashboard", fake_capture)
    monkeypatch.setattr(snapshot, "_node_available", lambda: True)
    # 跑命令喵
    router.build_image(connection, config, text)
    params = captured.get("params")
    assert isinstance(params, dict)
    return params


def test_build_image_rank_passes_hours(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """排行榜分支要把窗口换算成小时传下去喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 走 7 天喵
    params = _capture_params(monkeypatch, "看看happy 全部 排行榜 7天", connection, app_config)
    # 7 天 = 168 小时喵
    assert params["hours"] == "168"
    assert params["scope"] == "device"
    # 设备范围也要带上喵
    assert params["devices"] == "win-a"


def test_build_image_rank_hours_never_less_than_spoken_window(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """图上画的窗口不能比文字说的窗口**小**，否则会少显示数据喵。

    喵~注意：这是真实缺陷。看板的 `hours` 参数只接受整数小时，
    原来用 `round()` 换算，`70分钟`（1.17h）会四舍五入成 **1 小时**——
    文字说「最近 70 分钟」，图上只画 60 分钟，中间 10 分钟凭空消失。
    `150分钟`（2.5h）更糟，直接少画半小时喵。
    现在改成向上取整：宁可多看一点，也不能让人少看数据喵。
    """
    # 打开图片渲染喵
    config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备与分组喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 逐个窗口验证：图上的小时数覆盖的秒数必须 >= 文字窗口秒数喵
    for window_text, window_seconds in (
        ("70分钟", 70 * 60),
        ("75分钟", 75 * 60),
        ("85分钟", 85 * 60),
        ("130分钟", 130 * 60),
        ("150分钟", 150 * 60),
        ("2小时", 2 * 3600),
        ("7天", 7 * 24 * 3600),
    ):
        params = _capture_params(monkeypatch, f"看看happy 全部 排行榜 {window_text}", connection, config)
        # 图上的小时数喵
        hours = int(params["hours"])
        # 必须覆盖文字说的窗口喵
        assert hours * 3600 >= window_seconds, f"{window_text} 只画了 {hours} 小时"
        # 也不能多画超过一小时，否则就是另一种失真喵
        assert hours * 3600 - window_seconds < 3600, f"{window_text} 多画了太多"


def test_build_image_timeline_passes_window(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """时间轴分支要把起止时刻与反算倍数传下去喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑 09:00-12:00 喵
    params = _capture_params(monkeypatch, "看看happy 全部 时间轴 09:00 12:00", connection, app_config)
    # 窗口与倍率都要在喵
    assert params["from_time"] == "09:00"
    assert params["to_time"] == "12:00"
    # 三小时窗口 => 1440/180 = 8 倍喵
    assert params["zoom"] == "8"


def test_build_image_timeline_passes_date(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """时间轴分支要把日期传下去喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 指定日期喵
    params = _capture_params(monkeypatch, "看看happy 全部 时间轴 2026-10-30", connection, app_config)
    assert params["from"] == "2026-10-30"


def test_build_image_ignores_other_commands(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非看看happy 的命令不出图，一律走文本喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 设备清单与状态都不该出图喵
    assert router.build_image(connection, app_config, "happy设备") is None
    assert router.build_image(connection, app_config, "happy在干嘛") is None


def test_build_image_disabled_by_config(connection: sqlite3.Connection, app_config) -> None:
    """配置关掉图片时直接返回 None 喵。"""
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    # 默认配置就是关的喵
    assert router.build_image(connection, app_config, "看看happy 全部 排行榜") is None


def test_build_image_node_missing_falls_back(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没装 node 时退回文本，不能抛异常喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 假装没有 node 喵
    monkeypatch.setattr(snapshot, "_node_available", lambda: False)
    # 应返回 None 喵
    assert router.build_image(connection, app_config, "看看happy 全部 排行榜") is None


def test_build_image_shot_error_falls_back(
    connection: sqlite3.Connection, app_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """截图失败时退回文本，不能抛异常喵。"""
    # 喵~注意：测试默认配置关掉了图片，这里显式打开喵
    app_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 造设备喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 假装截图失败喵
    monkeypatch.setattr(snapshot, "_node_available", lambda: True)

    def broken(*args: object, **kwargs: object) -> bytes:
        """总是失败的截图函数喵。"""
        raise snapshot.ShotError("模拟失败")

    monkeypatch.setattr(snapshot, "capture_dashboard", broken)
    # 应返回 None 喵
    assert router.build_image(connection, app_config, "看看happy 全部 排行榜") is None


# ==================== 命令表本身 ====================


def test_all_commands_have_summary() -> None:
    """所有命令都要在帮助里露脸，说明或用法至少有一个喵。"""
    # 逐条查喵
    for command in commands.COMMANDS:
        # 喵~注意：看看happy 把参数写进用法里、关掉了摘要，所以两者有一个就够喵
        assert command.summary or command.usage, f"{command.name} 既没 summary 也没 usage"


def test_command_names_are_expected() -> None:
    """命令表就这 5 条，防止悄悄加回来喵。"""
    # 主名列表喵
    names = [command.aliases[0] for command in commands.COMMANDS]
    assert names == ["happy帮助", "happy在干嘛", "happy干了什么", "happy设备", "看看happy"]


def test_command_templates_parse() -> None:
    """每条命令的模板都要能解析喵。"""
    # 逐条解析喵
    for command in commands.COMMANDS:
        nodes = commands.expr.parse(command.template)
        assert nodes.nodes


def test_alternate_templates_parse() -> None:
    """分支模板同样要能解析喵。"""
    # 只有配了分支的命令才检查喵
    for command in commands.COMMANDS:
        if not command.alternate_flag:
            continue
        assert command.alternate_template
        nodes = commands.expr.parse(command.alternate_template)
        assert nodes.nodes


def test_fragment_nodes_parse() -> None:
    """片段表要能全部解析喵。"""
    # 解析结果应与片段数量一致喵
    parsed = commands.fragment_nodes()
    assert len(parsed) == len(commands.FRAGMENTS)


def test_command_by_name_case_insensitive() -> None:
    """命令名大小写不敏感，旧命令要彻底消失喵。"""
    # 大小写混写都要命中喵
    assert commands.command_by_name("HappyHelp") is not None
    assert commands.command_by_name("happydoing") is not None
    assert commands.command_by_name("看看HAPPY") is not None
    # 旧命令应彻底消失喵
    assert commands.command_by_name("设备") is None
    assert commands.command_by_name("排行图") is None


# ==================== happy设备：离线与电量分支 ====================


def test_happy_device_scope_online_phone(connection: sqlite3.Connection, app_config) -> None:
    """在线手机给「电量」，不给「最后电量」喵。"""
    # 造在线手机并带电量喵
    _seed(connection, "and-b", "手机")
    connection.execute(
        "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, 42, 0)",
        ("and-b", BASE_NOW.isoformat().replace("+00:00", "Z")),
    )
    connection.commit()
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("and-b",))])
    # 跑设备命令喵
    scope = commands._happy_device_scope(_context(connection, app_config, (), "happy设备"))
    row = scope["devices"][0]
    # 在线时标签是「电量」喵
    assert row["battery_label"] == "电量"
    assert row["battery_percent"] == 42
    assert row["is_offline"] is False


def test_happy_device_scope_offline_phone(connection: sqlite3.Connection, app_config) -> None:
    """离线手机给「最后电量」喵。"""
    # 造离线手机喵
    _seed(connection, "and-b", "手机", online=False)
    connection.execute(
        "INSERT INTO battery_samples (device_id, sampled_at, percent, charging) VALUES (?, ?, 17, 0)",
        ("and-b", (BASE_NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z")),
    )
    connection.commit()
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("and-b",))])
    # 跑设备命令喵
    scope = commands._happy_device_scope(_context(connection, app_config, (), "happy设备"))
    row = scope["devices"][0]
    # 离线时标签要变成「最后电量」喵
    assert row["battery_label"] == "最后电量"
    assert row["is_offline"] is True
    assert row["status"] == "离线"
    # 喵~注意：离线设备必须带上「上次在线」的时刻，否则模板那一行画不出来喵
    assert row["last_seen"] is not None


def test_happy_device_scope_windows_without_battery(connection: sqlite3.Connection, app_config) -> None:
    """没有电量的设备不该显示电量喵。"""
    # 造本机喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑设备命令喵
    scope = commands._happy_device_scope(_context(connection, app_config, (), "happy设备"))
    row = scope["devices"][0]
    # 没有电量标记喵
    assert row["has_battery"] is False


def test_happy_doing_scope_active_state(connection: sqlite3.Connection, app_config) -> None:
    """在干嘛的三档开关要互斥喵。"""
    # 造在线设备与一分钟前的使用喵
    _seed(connection, "win-a", "本机 Windows")
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, 'Code.exe', '', ?, 60)",
        ("win-a", (BASE_NOW - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")),
    )
    connection.commit()
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑在干嘛喵
    scope = commands._happy_doing_scope(_context(connection, app_config, (), "happy在干嘛"))
    # 三个开关只能亮一个喵
    assert scope["is_active"] is True
    assert scope["is_afk"] is False
    assert scope["is_away"] is False
    assert scope["device_name"] == "本机 Windows"


def test_happy_doing_scope_away_without_usage(connection: sqlite3.Connection, app_config) -> None:
    """从来没有使用记录时走「不在」分支且没有设备喵。"""
    # 造设备但不造使用记录喵
    _seed(connection, "win-a", "本机 Windows")
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑在干嘛喵
    scope = commands._happy_doing_scope(_context(connection, app_config, (), "happy在干嘛"))
    # 应该是 away 且没有最近上线喵
    assert scope["is_away"] is True
    assert scope["has_last_usage"] is False


def test_happy_done_scope_ranks_within_group(connection: sqlite3.Connection, app_config) -> None:
    """干了什么只在主人组范围内排行喵。"""
    # 主人组一台、组外一台喵
    _seed(connection, "win-a", "本机 Windows")
    _seed(connection, "out-x", "别人的机器")
    # 两台都有使用记录喵
    for device_id, app in (("win-a", "Code.exe"), ("out-x", "Game.exe")):
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, '', ?, 600)",
            (device_id, app, (BASE_NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")),
        )
    connection.commit()
    _set_group(app_config, [people.PersonGroup(name="happy", devices=("win-a",))])
    # 跑干了什么喵
    scope = commands._happy_done_scope(_context(connection, app_config, (), "happy干了什么"))
    # 只应出现主人组的应用喵
    apps = [row["app"] for row in scope["entries"]]
    assert "Code.exe" in apps
    assert "Game.exe" not in apps
