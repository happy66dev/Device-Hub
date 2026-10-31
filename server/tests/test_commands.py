"""数据层与命令模板的测试：查询筛选、排序截断、聚合、内置命令输出喵。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

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
) -> None:
    """插入一台设备及其使用记录，时间全部相对当前喵。"""
    # 上报时间喵
    reported_at = datetime.now(timezone.utc) - timedelta(seconds=seen_seconds_ago)
    # 默认给一条使用记录喵
    usage_items = usage if usage is not None else {"Code.exe": 60}
    # 构造上报体喵
    payload = ReportPayload.model_validate(
        make_payload(
            device_id=device_id,
            platform=platform,
            display_name=display_name or device_id,
            reported_at=reported_at.isoformat(),
            hardware=hardware if hardware is not None else {"cpu": "Ryzen 7 9700X"},
            usage_delta=[{"app": name, "seconds": seconds} for name, seconds in usage_items.items()],
        )
    )
    # 落库喵
    ingest.save_report(connection, payload, datetime.now(timezone.utc))


def _set_group(config: AppConfig, device_ids: tuple[str, ...]) -> None:
    """把设备写进看板里的「主人」组，happy 系列命令才认喵。"""
    # 直接复用 people 模块的保存函数喵
    people.save_people(config.server.db_path, [people.PersonGroup(name="主人", devices=device_ids)])


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
    # 喵~注意：帮助里不该再出现「主人」这个内部组名喵
    assert "主人" not in text


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
    """很久没用时应走「挂机/不在」分支喵。"""
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
    # 应说明可能在处理事情，而不是「正在使用」喵
    assert "可能在处理事情" in text
    assert "happy正在使用" not in text


def test_build_reply_active_command_without_group(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """没有主人组时应给出可操作的提示而不是崩溃喵。"""
    # 只造设备、不建组喵
    _seed(connection, "win-live", display_name="活跃机")
    # 渲染命令喵
    text = router.build_reply(connection, app_config, "happy在干嘛")
    # 应提示去建组喵
    assert "主人" in text
    assert "设备组" in text


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
    assert "主人 · 本机、平板" in text


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
