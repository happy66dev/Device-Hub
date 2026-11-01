"""数据层与命令模板的测试：查询筛选、排序截断、聚合、内置命令输出喵。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app import ingest, people
from app.bot import commands, dataset, expr, router
from app.config import AppConfig
from app.models import ReportPayload
from conftest import make_payload


def _seed(
    connection: sqlite3.Connection,
    device_id: str,
    *,
    display_name: str = "",
    platform: str = "windows",
    seen_seconds_ago: int = 5,
    usage: dict[str, int] | None = None,
    hardware: dict[str, str] | None = None,
    current_app: dict[str, Any] | None = None,
) -> None:
    """插入一台设备及其使用记录，时间全部相对当前喵。"""
    # 上报时间喵
    reported_at = datetime.now(timezone.utc) - timedelta(seconds=seen_seconds_ago)
    # 默认给一条使用记录喵
    usage_items = usage if usage is not None else {"Code.exe": 60}
    # 构造上报体喵
    overrides: dict[str, Any] = {
        "device_id": device_id,
        "platform": platform,
        "display_name": display_name or device_id,
        "reported_at": reported_at.isoformat(),
        "hardware": hardware if hardware is not None else {"cpu": "Ryzen 7 9700X"},
        "usage_delta": [{"app": name, "seconds": seconds} for name, seconds in usage_items.items()],
    }
    # 喵~注意：只有调用方显式给了 current_app 才覆盖，否则用默认值喵
    if current_app is not None:
        overrides["current_app"] = current_app
    payload = ReportPayload.model_validate(make_payload(**overrides))
    # 落库喵
    ingest.save_report(connection, payload, datetime.now(timezone.utc))


def _set_group(config: AppConfig, device_ids: tuple[str, ...], name: str = "happy") -> None:
    """把设备写进看板里的 happy 组，happy 系列命令才认喵。"""
    # 直接复用 people 模块的保存函数喵
    people.save_people(config.server.db_path, [people.PersonGroup(name=name, devices=device_ids)])


def test_list_device_rows_has_expected_fields(connection: sqlite3.Connection) -> None:
    """设备行应带上模板需要的全部字段喵。"""
    # 插入一台设备喵
    _seed(connection, "win-a", display_name="台式机")
    # 取设备行喵
    rows = dataset.list_device_rows(connection, datetime.now(timezone.utc))
    # 应有一台设备喵
    assert len(rows) == 1
    row = rows[0]
    # 关键字段齐全喵
    assert row["id"] == "win-a"
    assert row["name"] == "台式机"
    assert row["platform"] == "Windows"
    assert row["status"] == "在线"
    assert row["online"] is True
    assert row["has_battery"] is False
    assert row["hardware"] == ["处理器：Ryzen 7 9700X"]


def test_device_detail_row_missing_returns_none(connection: sqlite3.Connection) -> None:
    """设备不存在时应返回 None 喵。"""
    # 查一台不存在的设备喵
    assert dataset.device_detail_row(connection, "win-none", datetime.now(timezone.utc)) is None


def test_ranking_rows_have_percent(connection: sqlite3.Connection) -> None:
    """排行行应算好占比喵。"""
    # 一台设备两个应用，各 60 与 30 秒喵
    _seed(connection, "win-a", usage={"A.exe": 60, "B.exe": 30})
    # 取排行喵
    rows = dataset.ranking_rows(connection, "win-a", 24, 0, datetime.now(timezone.utc), "台式机")
    # 第一名是 60 秒的应用喵
    assert rows[0]["app"] == "A.exe"
    # 占比约 66.7%喵
    assert round(rows[0]["percent"], 1) == 66.7
    # 序号从 1 开始喵
    assert [row["rank"] for row in rows] == [1, 2]


def test_query_devices_filter_by_online(connection: sqlite3.Connection) -> None:
    """在线筛选应只留在线设备喵。"""
    # 一台在线、一台一天前喵
    _seed(connection, "win-online", seen_seconds_ago=5)
    _seed(connection, "win-offline", seen_seconds_ago=5)
    # 喵~注意：save_report 用调用方传的时间写 last_seen，这里直接把离线那台推回一天前喵
    connection.execute(
        "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "win-offline"),
    )
    connection.commit()
    # 只查在线的喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "设备", {"在线": "是"})
    # 只剩在线那台喵
    assert [row["id"] for row in rows] == ["win-online"]


def test_query_devices_filter_by_platform(connection: sqlite3.Connection) -> None:
    """平台筛选应为大小写不敏感喵。"""
    # 一台安卓一台 Windows 喵
    _seed(connection, "and-a", platform="android")
    _seed(connection, "win-b", platform="windows")
    # 查安卓喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "设备", {"平台": "ANDROID"})
    # 只剩安卓喵
    assert [row["id"] for row in rows] == ["and-a"]


def test_query_devices_filter_by_recent_usage(connection: sqlite3.Connection) -> None:
    """「有使用」应只留窗口内有使用记录的设备喵。"""
    # 一台刚用过、一台很久没用喵
    _seed(connection, "win-now", seen_seconds_ago=5)
    _seed(connection, "win-old", seen_seconds_ago=5, usage={"Old.exe": 60})
    # 把旧那台的使用记录推到两小时前喵
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ? WHERE device_id = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "win-old"),
    )
    connection.commit()
    # 查最近 1 分钟有使用的喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "设备", {"有使用": "1分钟"})
    # 只剩刚用过的那台喵
    assert [row["id"] for row in rows] == ["win-now"]
    # 窗口内使用时长也一并算好喵
    assert rows[0]["usage_total"] == 60


def test_query_devices_limit(connection: sqlite3.Connection) -> None:
    """前= 应截断结果条数喵。"""
    # 三台设备喵
    for index in range(3):
        _seed(connection, f"win-{index}")
    # 只取一台喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "设备", {"前": "1"})
    # 只剩一条喵
    assert len(rows) == 1


def test_query_devices_sort_ascending(connection: sqlite3.Connection) -> None:
    """写正序时应按升序排喵。"""
    # 两台设备，名称不同喵
    _seed(connection, "win-bbb", display_name="BBB")
    _seed(connection, "win-aaa", display_name="AAA")
    # 按名称正序喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "设备", {"按": "名称", "正序": ""})
    # 应是 AAA 在前喵
    assert [row["name"] for row in rows] == ["AAA", "BBB"]


def test_query_devices_count_aggregate(connection: sqlite3.Connection) -> None:
    """计数聚合应返回行数喵。"""
    # 两台设备喵
    _seed(connection, "win-a")
    _seed(connection, "win-b")
    # 计数喵
    context = dataset.make_context(connection)
    assert dataset.run_query(context, "设备", {"计数": ""}) == 2


def test_query_devices_sum_aggregate(connection: sqlite3.Connection) -> None:
    """合计聚合应把字段加起来喵。"""
    # 两台设备各有一条 60 秒记录喵
    _seed(connection, "win-a", usage={"A.exe": 60})
    _seed(connection, "win-b", usage={"B.exe": 60})
    # 合计使用时长喵
    context = dataset.make_context(connection)
    assert dataset.run_query(context, "设备", {"合计": "使用时长"}) == 120


def test_query_unknown_dataset_raises(connection: sqlite3.Connection) -> None:
    """数据集名写错应报错并列出可用项喵。"""
    # 查一个不存在的数据集喵
    context = dataset.make_context(connection)
    with pytest.raises(dataset.DatasetError) as error:
        dataset.run_query(context, "不存在", {})
    # 提示里应列出可用数据集喵
    assert "设备" in str(error.value)


def test_query_bad_window_raises(connection: sqlite3.Connection) -> None:
    """时间窗口写法不对应报错喵。"""
    # 写一个解析不出来的窗口喵
    context = dataset.make_context(connection)
    with pytest.raises(dataset.DatasetError):
        dataset.run_query(context, "设备", {"最近": "很久"})


def test_query_ranking_requires_device(connection: sqlite3.Connection) -> None:
    """排行查询必须给设备喵。"""
    # 不给设备喵
    context = dataset.make_context(connection)
    with pytest.raises(dataset.DatasetError):
        dataset.run_query(context, "排行", {})


def test_query_scope_list_reads_scope(connection: sqlite3.Connection) -> None:
    """「当前」数据集应能遍历作用域里的现成列表喵。"""
    # 准备一个列表喵
    scope = {"devices": [{"name": "甲"}, {"name": "乙"}]}
    # 遍历喵
    context = dataset.make_context(connection)
    rows = dataset.run_query(context, "当前", {"列表": "设备列表"}, (scope,))
    # 两行，序号自动补上喵
    assert [row["rank"] for row in rows] == [1, 2]


def test_query_scope_list_missing_raises(connection: sqlite3.Connection) -> None:
    """列表不存在时应报错喵。"""
    # 空作用域喵
    context = dataset.make_context(connection)
    with pytest.raises(dataset.DatasetError):
        dataset.run_query(context, "当前", {"列表": "设备列表"}, ({},))


def test_build_reply_help_lists_new_commands(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """帮助里应列出新的五条 happy 命令喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 五条命令都在喵
    for name in ("/happy帮助", "/happy在干嘛", "/happy干了什么", "/happy设备", "/看看happy"):
        assert name in text
    # 喵~注意：只比较整行命令名，否则「<全部/设备名>」里也会命中「/设备」喵
    command_lines = {line.strip() for line in text.splitlines() if line.strip().startswith("/")}
    # 被删掉的老命令不该再作为独立命令出现喵
    for gone in ("/帮助", "/设备", "/使用", "/谁在用", "/总排行", "/排行图", "/时间轴图"):
        assert gone not in command_lines


def test_help_first_summary_wording(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """帮助里第一条的说明按主人的措辞喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 第一条要说「可以查询哪些信息」喵
    assert "看看可以查询happy哪些信息" in text
    # 旧的措辞不该残留喵
    assert "看看 happy 能做什么" not in text


def test_help_explains_look_happy_params(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """看看happy 的参数格式要嵌在用法里，主人一眼能抄喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 设备范围要点明可写什么喵
    assert "设备：全部 / 本机 / 手机" in text
    # 排行榜的可选范围与上限都要写出来喵
    assert "排行榜 [时间范围]：" in text
    assert "上限 7 天" in text
    # 时间轴的三种写法都要给喵
    assert "时间轴 [起止时刻]：今天（默认，到此刻）" in text
    assert "/ 2026-11-01 / 2026-11-01 09:00 12:00" in text
    # 至少给两个能直接抄的例子喵
    assert "/看看happy 全部 排行榜 6小时" in text
    assert "/看看happy 手机 时间轴 09:00 12:00" in text
    # 喵~注意：参数行要跟在那条命令自己的用法下面，不能跑到别的命令下面喵
    head = text.index("/看看happy")
    assert head < text.index("设备：全部 / 本机 / 手机")
    # 用法里已经写全，不再单挂一行摘要喵
    assert "按设备范围看排行榜或时间轴" not in text


def test_help_has_no_count_header(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """帮助不再有「happy 能做的事（共 N 条）」这种抬头喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 抬头已删，直接从第一条命令开始喵
    assert not text.startswith("happy 能做的事")
    assert text.startswith("/happy帮助")
    # 条数统计也不该出现喵
    assert "共 5 条" not in text


def test_help_commands_keep_their_summary(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """只有看看happy 关掉摘要，其余四条仍要各有一行说明喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 这四条的说明都还在喵
    for summary in (
        "看看可以查询happy哪些信息",
        "看看 happy 现在在做什么",
        "看看 happy 近 24 小时用了什么",
        "看看 happy 名下各台设备的状态",
    ):
        assert summary in text, f"缺了说明：{summary}"


def test_help_has_no_group_footer(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """帮助结尾不再解释「主人」组，主人要求删掉喵。"""
    # 渲染帮助喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 那句结尾已经删了喵
    assert "认的是看板里名为" not in text
    assert "组内顺序就是优先级" not in text
    # 喵~注意：帮助里不该再出现「组名 · 设备」这种范围说明喵
    assert " · " not in text


def test_build_reply_active_command(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """happy在干嘛应说明正在用哪台设备喵。"""
    # 插入一台刚用过的设备并归入主人组喵
    _seed(connection, "win-live", display_name="活跃机")
    _set_group(app_config, ("win-live",))
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 应包含设备名与当前应用喵
    assert "活跃机" in text
    assert "Code.exe" in text
    # 正在使用时有专门的开头喵
    assert "happy正在使用" in text


def test_build_reply_active_command_empty(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """很久没用时应走「不在」分支，不能说自己正在使用喵。"""
    # 一台设备，但使用记录在两小时前喵
    _seed(connection, "win-quiet", display_name="安静机")
    _set_group(app_config, ("win-quiet",))
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    connection.commit()
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 喵~注意：空档两小时远超 10 分钟，必须走「不在」而不是「挂机」喵
    assert "happy不在诶" in text
    assert "happy正在使用" not in text
    assert "可能在处理事情" not in text
    # 不在时要带上最近一次使用的时间与空档长度喵
    assert "最近一次使用" in text
    assert "没有动静" in text


def test_build_reply_afk_when_gap_under_ten_minutes(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """空档不到 10 分钟走挂机分支，文案要说「可能在处理事情」喵。"""
    # 造一台五分钟前用过、现在没有新记录的设备喵
    _seed(connection, "win-afk", display_name="挂机机")
    _set_group(app_config, ("win-afk",))
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    connection.commit()
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 喵~注意：这一档的文案是「正在挂机」，以前它被错接到「不在」上了喵
    assert "happy正在挂机" in text
    assert "可能在处理事情" in text
    assert "happy正在使用" not in text
    assert "happy不在诶" not in text


def test_build_reply_afk_ignores_heartbeat_flag(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """门控暂停计时的设备 afk=false，空档短时仍要判挂机喵。"""
    # 造设备：心跳没报 AFK，但四分钟没有使用记录喵
    _seed(connection, "win-gated", display_name="门控机", current_app={"name": "Code.exe", "package": "Code.exe"})
    _set_group(app_config, ("win-gated",))
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    connection.execute("UPDATE devices SET afk = 0")
    connection.commit()
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 照样是挂机喵
    assert "happy正在挂机" in text


def test_build_reply_afk_has_no_duration(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """挂机档不显示「已持续多久」喵。

    喵~注意：那个数是「应用当台前的自然时间」，人走开多久它都在涨，
    在挂机档里报出来和「可能在处理事情」自相矛盾，所以整段不显示喵。
    """
    # 造一台挂机设备，快照里的 since 是三小时前（应用一直没切）喵
    _seed(
        connection,
        "win-afk2",
        display_name="挂机机2",
        current_app={
            "name": "Code.exe",
            "package": "Code.exe",
            "since": (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    _set_group(app_config, ("win-afk2",))
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    connection.commit()
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 确实是挂机档喵
    assert "happy正在挂机" in text
    # 喵~防御：不能出现「已持续 3 小时」这种误导人的数喵
    assert "已持续" not in text
    assert "3 小时" not in text


def test_build_reply_active_shows_duration(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """在用档要保留「已持续多久」，那里 since 是新鲜的喵。"""
    # 造一台正在用的设备，since 是两分钟前喵
    _seed(
        connection,
        "win-live2",
        display_name="活跃机2",
        current_app={
            "name": "Code.exe",
            "package": "Code.exe",
            "since": (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    _set_group(app_config, ("win-live2",))
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    assert "happy正在使用" in text
    # 在用档有时长喵
    assert "已持续" in text


def test_build_reply_three_states_are_exclusive(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """三档文案互斥，同一份回复里只能出现一种开头喵。"""
    # 逐档造数据并检查开头唯一喵
    for ago_minutes, expected in ((0, "happy正在使用"), (5, "happy正在挂机"), (120, "happy不在诶")):
        # 每轮清空重来喵
        connection.execute("DELETE FROM usage_samples")
        connection.execute("DELETE FROM devices")
        connection.commit()
        device_id = f"win-s{ago_minutes}"
        _seed(connection, device_id, display_name="状态机")
        _set_group(app_config, (device_id,))
        connection.execute(
            "UPDATE usage_samples SET sampled_at = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=ago_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
        )
        connection.commit()
        # 渲染并检查只有一个开头喵
        text = router.build_reply(connection, app_config, "happy在干嘛")
        openings = ("happy正在使用", "happy正在挂机", "happy不在诶")
        assert expected in text, text
        # 喵~防御：另外两个开头不能同时出现喵
        assert sum(opening in text for opening in openings) == 1, text


def test_build_reply_active_command_without_group(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """没有主人组时应给出可操作的提示而不是崩溃喵。"""
    # 只造设备、不建组喵
    _seed(connection, "win-live", display_name="活跃机")
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 应提示去建组喵
    assert "happy" in text
    assert "设备组" in text


def test_all_resolves_to_configured_group_name(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """「全部」应解析到配置里的组名，换组名后依然生效喵。"""
    from dataclasses import replace

    # 设备放进自定义组名的组喵
    _seed(connection, "win-live", display_name="活跃机", usage={"Code.exe": 60})
    _set_group(app_config, ("win-live",), name="我的组")
    # 把配置指向这个组喵
    custom = replace(app_config, bot=replace(app_config.bot, happy_group="我的组"))
    # 解析「全部」喵
    label, device_ids, note = commands._parse_happy_scope(
        "全部", commands.CommandContext(
            connection=connection,
            config=custom,
            name="看看happy",
            args=("全部", "排行榜"),
            now=datetime.now(timezone.utc),
        )
    )
    # 标签应为配置里的组名喵
    assert label == "我的组"
    assert device_ids == ["win-live"]
    assert note.startswith("我的组 · ")


def test_happy_device_empty_text_uses_group_name(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """设备清单为空时，「空=」文案里的组名占位符要能被替换喵。"""
    # 直接渲染模板里那段查询，只验证占位符替换喵
    scope = {"devices": [], "group_name": "我的组"}
    env = dataset.TemplateEnv(commands.fragment_nodes(), {})
    text = expr.render_text(
        '{查询 当前 列表=设备列表 行=happy设备块 空="{设备组名}组里还没有设备。"}',
        (scope,),
        env,
    )
    # 占位符应被替换成组名喵
    assert text == "我的组组里还没有设备。"


def test_build_reply_shows_window_title_under_current_app(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """有窗口标题时要在「当前应用:」下方多一行标题喵。"""
    # 造一台带标题的 Windows 设备喵
    _seed(
        connection,
        "win-live",
        display_name="活跃机",
        usage={"java": 60},
        current_app={"name": "java", "package": "java.exe", "title": "Minecraft 1.7.10"},
    )
    _set_group(app_config, ("win-live",))
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 当前应用那一行必须还在喵
    assert "当前应用: java" in text
    # 标题要单独占一行喵
    assert "\nMinecraft 1.7.10" in text
    # 喵~注意：标题行紧跟在「当前应用」之后，中间不能插别的内容喵
    app_line = next(line for line in text.splitlines() if line.startswith("当前应用:"))
    title_index = text.splitlines().index(app_line) + 1
    assert text.splitlines()[title_index] == "Minecraft 1.7.10"


def test_build_reply_omits_title_line_when_missing(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """取不到标题时不能多出一行空白喵。"""
    # 造一台没有标题的 Windows 设备喵
    _seed(
        connection,
        "win-notitle",
        display_name="无标题机",
        current_app={"name": "Code.exe", "package": "Code.exe"},
    )
    _set_group(app_config, ("win-notitle",))
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 当前应用行还在喵
    assert "当前应用: Code.exe" in text
    # 喵~注意：不能出现紧跟其后的空行喵
    assert "\n\n" not in text


def test_build_reply_omits_title_line_when_blank(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """标题是空串或纯空白时同样不展示，避免画出空行喵。"""
    # 三种"没标题"的写法都要被吃掉喵
    for index, blank_title in enumerate(("", "   ")):
        device_id = f"win-blank{index}"
        _seed(
            connection,
            device_id,
            display_name=f"空白机{index}",
            current_app={"name": "Code.exe", "package": "Code.exe", "title": blank_title},
        )
        _set_group(app_config, (device_id,))
        text = router.build_reply(connection, app_config, "happy在干嘛")
        assert "当前应用: Code.exe" in text
        # 喵~注意：空标题绝不能变成一行空白喵
        assert "\n\n" not in text


def test_android_current_app_has_no_title(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """安卓端不采集标题，解析后必须是空串喵。"""
    # 造一台安卓设备，客户端传的就是 null 标题喵
    _seed(
        connection,
        "and-title",
        display_name="手机",
        platform="android",
        usage={"QQ": 60},
        current_app={"name": "QQ", "package": "com.tencent.mobileqq", "title": None},
    )
    _set_group(app_config, ("and-title",))
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 当前应用行正常喵
    assert "当前应用: QQ" in text
    # 喵~注意：安卓不该有标题行，也不该留空行喵
    assert "\n\n" not in text
    assert "None" not in text


def test_title_dropped_when_app_mismatch(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """标题所属应用与当前应用对不上时丢掉标题，不能张冠李戴喵。"""
    # 喵~注意：应用名取最新使用采样、标题取上报快照，两者可能不同步；
    # 这种情况宁可少一行，也不能把 A 应用的窗口标题挂到 B 应用下面喵
    _seed(
        connection,
        "win-mismatch",
        display_name="错位机",
        usage={"Code.exe": 60},
        current_app={"name": "java", "package": "java.exe", "title": "Minecraft 1.7.10"},
    )
    _set_group(app_config, ("win-mismatch",))
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 应用名以使用采样为准喵
    assert "当前应用: Code.exe" in text
    # 喵~防御：Java 的标题绝不能出现在 Code.exe 下面喵
    assert "Minecraft" not in text


def test_build_reply_global_ranking(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """happy干了什么应列出应用与组内设备名喵。"""
    # 两台设备用同一个应用喵
    _seed(connection, "win-a", display_name="本机", usage={"QQ.exe": 60})
    _seed(connection, "win-b", display_name="平板", usage={"QQ.exe": 30})
    _set_group(app_config, ("win-a", "win-b"))
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy干了什么")
    # 应包含应用名与范围说明喵
    assert "QQ.exe" in text
    assert "happy · 本机、平板" in text


def test_build_reply_global_ranking_alias(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """英文别名应命中 happy干了什么 命令喵。"""
    # 先塞一台设备，保证主人组有内容喵
    _seed(connection, "win-a", display_name="本机", usage={"QQ.exe": 60})
    _set_group(app_config, ("win-a",))
    # 用英文别名发命令喵
    text = router.build_reply(connection, app_config, "happydone")
    # 应命中近 24 小时排行喵
    assert "近24小时内 happy使用了下面的东西" in text
    assert "QQ.exe" in text


def test_build_reply_global_ranking_empty(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """组内设备都没有使用记录时应给出空文案喵。"""
    # 一台设备，使用记录推到 24 小时以前喵
    _seed(connection, "win-idle", display_name="闲机")
    _set_group(app_config, ("win-idle",))
    connection.execute(
        "UPDATE usage_samples SET sampled_at = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    connection.commit()
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy干了什么")
    # 应说明没有使用记录喵
    assert "没有使用记录" in text


def test_fragment_nodes_parse_without_error() -> None:
    """所有内置片段都应能解析喵。"""
    # 解析片段表喵
    nodes = commands.fragment_nodes()
    # 三个片段都要在喵
    assert nodes["排行行"]
    assert nodes["帮助行"]
    assert nodes["happy设备块"]


def test_all_command_templates_parse() -> None:
    """所有命令模板都应能解析喵。"""
    # 逐条解析喵
    for command in commands.COMMANDS:
        expr.parse(command.template)
        # 分支模板有的话也要能解析喵
        if command.alternate_template:
            expr.parse(command.alternate_template)


def test_command_by_name_is_case_insensitive() -> None:
    """命令名匹配应忽略大小写喵。"""
    # 大写写法喵
    assert commands.command_by_name("HELP") is None
    # 英文别名大小写都认喵
    assert commands.command_by_name("happyhelp") is not None
    assert commands.command_by_name("HappyHelp") is not None
    # 中文命令名喵
    assert commands.command_by_name("happy设备") is not None
    # 被删掉的老命令喵
    assert commands.command_by_name("设备") is None
    # 不存在的命令喵
    assert commands.command_by_name("重启") is None
