"""未知命令静默的行为测试：不回复、不记账、不占忙位，其余命令照旧喵。

为什么单独开一个文件：这是主人 2026-11-02 明确要求的口径变更——
「未知命令 → 完全不回复」，和原来「未知命令 → 回帮助」正好相反。
变更点涉及 router / runner / simulate 三层，集中放一处免得后人改回去喵。
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db, ingest, people
from app.bot import router, simulate
from app.bot.channel import NormalizedMessage
from app.bot.runner import BotRunner
from app.config import AppConfig, QQBotSection
from app.models import ReportPayload
from conftest import make_payload

# 官方通道的假群 openid 喵
GROUP_OPENID = "GROUP_OPENID_A"

# 官方通道里两个不同的假成员喵
MEMBER_OPENID = "MEMBER_OPENID_X"

# 未知命令的各种写法，覆盖「闲聊」「不存在的命令」「只有前缀」喵
UNKNOWN_TEXTS = (
    "哈哈哈哈",
    "重启",
    "不存在的命令",
    "/不存在的命令",
    "/happy",
    "重启一下服务器",
)


def _seed_device(connection: sqlite3.Connection, device_id: str) -> None:
    """插入一台在线设备，供正常命令取数据喵。"""
    # 上报时间用当前时间，保证设备是在线状态喵
    reported_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    # 构造上报对象喵
    payload = ReportPayload.model_validate(
        make_payload(device_id=device_id, reported_at=reported_at.isoformat(), display_name="测试机")
    )
    # 落库喵
    ingest.save_report(connection, payload, datetime.now(timezone.utc))


def _set_happy_group(config: AppConfig, device_ids: tuple[str, ...]) -> None:
    """把设备写进看板里的 happy 组，happy 系列命令才认喵。"""
    # 直接复用 people 模块的保存函数喵
    people.save_people(config.server.db_path, [people.PersonGroup(name="happy", devices=device_ids)])


# ==================== 第一类：完全不匹配任何命令 → 静默 ====================


def test_unknown_command_reply_is_empty(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """未知命令的回复必须是空串，表示一个字都不发喵。"""
    # 直接问路由层要回复喵
    text = router.build_reply(connection, app_config, "哈哈哈哈")
    # 喵~注意：空串是「不发消息」的约定，runner 拿到空串会直接 return 喵
    assert text == ""
    # 也不许再塞帮助进来，否则等于换了个说法继续刷屏喵
    assert "帮助" not in text


def test_unknown_command_is_silent_for_many_spellings(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """多种未知写法都必须静默，不能只有一两种走通喵。"""
    # 逐个写法验证喵
    for text in UNKNOWN_TEXTS:
        # 取回复喵
        reply = router.build_reply(connection, app_config, text)
        # 一个字符都不许有喵
        assert reply == "", f"{text!r} 居然回了：{reply!r}"


def test_unknown_command_never_returns_image(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """未知命令也不许走图片路径，避免静默规则被图片绕过喵。"""
    # 打开图片渲染，让图类命令有出图可能喵
    config = dataclasses.replace(app_config, render=dataclasses.replace(app_config.render, image_enabled=True))
    # 喵~注意：build_image 对未知命令本来就走 None，这里把它钉住喵
    assert router.build_image(connection, config, "看看happy2 全部 排行榜") is None


def test_slash_prefixed_missing_command_is_silent(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """以 / 开头但命令不存在的文本同样静默，判定点在命令表而不是前缀喵。

    为什么按第一类静默：前缀闸门（ACL / @ 检测）只保证「用户想用命令」，
    它拦不住打错的命令名；真要在群里逐条纠正拼写错误，等于给每个手滑的人
    都发一段帮助，正是主人要避免的刷屏。参数错则不同——命令名对得上，
    说明用户确实在用这条命令，不告诉他参数错在哪，他会以为机器人坏了喵。
    """
    # 带前缀的未知命令喵
    assert router.build_reply(connection, app_config, "/不存在的命令") == ""
    # 判定函数也要给出同一个结论喵
    assert router.is_silent_command("/不存在的命令") is True


def test_bare_happy_is_treated_as_unknown(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """单独发 /happy 保持原有口径：命令表里没有它，因此静默喵。

    喵~注意：命令表里只有 happy帮助 / happy在干嘛 / happy干了什么 / happy设备 /
    看看happy 五条，没有裸 happy。改动前它走「未知命令 + 帮助」，改动后按新规则
    并入第一类（静默）；「/happy设备 不带参数」这种才是原有行为不变，见下面的用例喵。
    """
    # 裸 happy 不属于任何已注册命令喵
    assert router.resolve_command("/happy")[1] is None
    # 因此静默喵
    assert router.build_reply(connection, app_config, "/happy") == ""


# ==================== 第二类：命令名对但参数错 → 仍然提示 ====================


def test_param_error_still_replies(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """命令名对、参数认不出时仍要回错误提示喵。"""
    # 塞一台设备并归组，让命令能跑到参数校验那一步喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 第二个参数乱写喵
    text = router.build_reply(connection, app_config, "看看happy 全部 乱写")
    # 必须有提示，且指出是哪个参数错了喵
    assert "看不懂" in text
    assert "乱写" in text
    # 提示里要给出正确写法，用户才知道怎么改喵
    assert "排行榜" in text and "时间轴" in text


def test_param_error_still_replies_for_window(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """时间窗口写错时同样要提示，不能静默喵。"""
    # 塞一台设备并归组喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 时间窗口写成人话喵
    text = router.build_reply(connection, app_config, "看看happy 全部 排行榜 很久")
    # 应提示窗口看不懂喵
    assert "时间窗口看不懂" in text


def test_missing_args_still_replies(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """参数不足时给用法提示，仍属于「用户明确在用命令」喵。"""
    # 塞一台设备并归组喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 只写命令名，不写参数喵
    text = router.build_reply(connection, app_config, "看看happy")
    # 应给出用法喵
    assert "用法" in text
    assert "排行榜" in text and "时间轴" in text


# ==================== 第三类：正常命令与帮助 → 照旧 ====================


def test_normal_command_still_works(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """正常命令必须照常回复，静默规则不能误伤它们喵。"""
    # 塞一台设备并归组喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 跑设备清单命令喵
    text = router.build_reply(connection, app_config, "happy设备")
    # 回复里应有设备名喵
    assert "测试机" in text
    # 不能把正常命令也当成未知命令吞掉喵
    assert router.is_silent_command("happy设备") is False


def test_help_still_works(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """帮助命令本身不受影响，主名与别名都要能回喵。"""
    # 中文主名喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 五条命令都要列出来喵
    for name in ("/happy帮助", "/happy在干嘛", "/happy干了什么", "/happy设备", "/看看happy"):
        assert name in text
    # 英文别名同样能回喵
    assert "/happy帮助" in router.build_reply(connection, app_config, "happyhelp")
    # 帮助当然不属于静默喵
    assert router.is_silent_command("happy帮助") is False


def test_empty_command_still_returns_help(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """只 @ 机器人不说话时仍回帮助，这是原有行为，不在本次变更范围喵。"""
    # 空命令文本喵
    text = router.build_reply(connection, app_config, "")
    # 应返回帮助喵
    assert "/happy帮助" in text
    # 空文本不算未知命令，否则「只 @ 一下」就彻底没反应了喵
    assert router.is_silent_command("") is False
    assert router.is_silent_command("   ") is False


def test_product_copy_has_no_kitty(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """群可见文案里绝对不能出现「喵」喵。"""
    # 塞一台设备并归组，保证命令能走到渲染喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 逐条检查会真的发到群里的文案喵
    for text in ("happy帮助", "happy设备", "看看happy 全部 乱写", "看看happy"):
        reply = router.build_reply(connection, app_config, text)
        assert "喵" not in reply, f"{text!r} 的文案里混进了「喵」"


# ==================== 判定函数本身 ====================


def test_is_silent_command_matrix() -> None:
    """判定函数只认「命令名查不到」，其余一律不静默喵。"""
    # 已注册命令（含别名、大小写）都不静默喵
    for text in ("happy设备", "/happy设备", "HAPPYDEVICES", "看看happy", "/happy帮助", "lookhappy"):
        assert router.is_silent_command(text) is False, f"{text!r} 被误判成未知命令"
    # 未知命令静默喵
    for text in ("重启", "/重启", "哈哈哈哈", "/不存在的命令"):
        assert router.is_silent_command(text) is True, f"{text!r} 没被判定成未知命令"
    # 空文本不静默，保留「只 @ 一下 → 帮助」的原有行为喵
    assert router.is_silent_command("") is False


# ==================== runner 层：一条消息都不许发 ====================


class _RecordingChannel:
    """记录发送内容的假通道，用来确认「一条都没发」喵。"""

    def __init__(self) -> None:
        # 通道名喵
        self.name = "qqbot"
        # 已发送文本喵
        self.texts: list[tuple[str, str]] = []
        # 已发送图片喵
        self.images: list[str] = []

    async def run(self) -> None:
        """假通道不跑网络喵。"""
        return None

    async def stop(self) -> None:
        """假通道无需停止喵。"""
        return None

    def is_connected(self) -> bool:
        """假通道始终在线喵。"""
        return True

    async def send_text(self, group_key: str, text: str, **kwargs: Any) -> None:
        """记录文本喵。"""
        self.texts.append((group_key, text))

    async def send_image(self, group_key: str, image_bytes: bytes, **kwargs: Any) -> None:
        """记录图片喵。"""
        self.images.append(group_key)


def _runner_config(app_config: AppConfig) -> AppConfig:
    """打开官方通道并放行一个群，让消息能通过准入闸门喵。"""
    return dataclasses.replace(
        app_config,
        qqbot=QQBotSection(enabled=True, app_id="app-id", app_secret="app-secret"),
        acl=dataclasses.replace(app_config.acl, whitelist_group_openids=(GROUP_OPENID,)),
    )


def _message(text: str, user_key: str = MEMBER_OPENID) -> NormalizedMessage:
    """造一条官方通道的群 @ 消息喵。"""
    return NormalizedMessage(
        channel="qqbot",
        group_key=GROUP_OPENID,
        user_key=user_key,
        text=text,
        mentioned=True,
    )


def test_runner_sends_nothing_for_unknown_command(app_config: AppConfig) -> None:
    """未知命令：文本、图片、忙时提示一条都不许发喵。"""
    # 建机器人并换上假通道喵
    runner = BotRunner(_runner_config(app_config))
    channel = _RecordingChannel()
    runner._channels = {"qqbot": channel}  # noqa: SLF001

    # 跑一轮事件循环喵
    asyncio.run(runner._handle_message(_message("/不存在的命令")))  # noqa: SLF001

    # 喵~注意：这是本次改造的核心断言——群里什么都收不到喵
    assert channel.texts == []
    assert channel.images == []
    # 忙位必须没被占住，否则后面真正的命令会被挤掉喵
    assert runner._busy is False  # noqa: SLF001


def test_runner_does_not_record_unknown_command_sender(app_config: AppConfig) -> None:
    """未知命令的人不写进发言人名单，名单只留真正执行过命令的人喵。"""
    # 先建表喵
    db.init_db(app_config.server.db_path)
    # 建机器人并换上假通道喵
    runner = BotRunner(_runner_config(app_config))
    runner._channels = {"qqbot": _RecordingChannel()}  # noqa: SLF001
    # 跑一条未知命令喵
    asyncio.run(runner._handle_message(_message("哈哈哈哈", user_key="STRANGER")))  # noqa: SLF001
    # 查名单里有没有这个人喵
    connection = db.connect(app_config.server.db_path)
    try:
        rows = connection.execute(
            "SELECT user_key FROM bot_seen_users WHERE user_key = ?", ("STRANGER",)
        ).fetchall()
    finally:
        connection.close()
    # 喵~注意：静默命令连「记账」都不该发生，看板名单才不会被人名刷满喵
    assert rows == []


def test_runner_still_replies_to_normal_command(app_config: AppConfig) -> None:
    """正常命令照旧发出文本，别把静默规则做成全局静音喵。"""
    # 先建表并塞一台设备喵
    db.init_db(app_config.server.db_path)
    connection = db.connect(app_config.server.db_path)
    try:
        _seed_device(connection, "win-alpha-1111")
    finally:
        connection.close()
    # 归入 happy 组喵
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 建机器人并换上假通道喵
    runner = BotRunner(_runner_config(app_config))
    channel = _RecordingChannel()
    runner._channels = {"qqbot": channel}  # noqa: SLF001
    # 跑一条正常命令喵
    asyncio.run(runner._handle_message(_message("/happy设备")))  # noqa: SLF001
    # 应真的发出文本喵
    assert len(channel.texts) == 1
    assert "测试机" in channel.texts[0][1]
    # 忙位要释放喵
    assert runner._busy is False  # noqa: SLF001


def test_unknown_command_does_not_block_next_command(app_config: AppConfig) -> None:
    """未知命令不占忙位，紧跟着的正常命令仍然能跑喵。"""
    # 先建表并塞一台设备喵
    db.init_db(app_config.server.db_path)
    connection = db.connect(app_config.server.db_path)
    try:
        _seed_device(connection, "win-alpha-1111")
    finally:
        connection.close()
    # 归入 happy 组喵
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 建机器人并换上假通道喵
    runner = BotRunner(_runner_config(app_config))
    channel = _RecordingChannel()
    runner._channels = {"qqbot": channel}  # noqa: SLF001

    # 先发未知命令，再发正常命令喵
    async def run_both() -> None:
        """串行处理两条消息喵。"""
        await runner._handle_message(_message("哈哈哈哈"))  # noqa: SLF001
        await runner._handle_message(_message("/happy设备"))  # noqa: SLF001

    # 跑事件循环喵
    asyncio.run(run_both())
    # 只有正常命令那条有回复，且没被「稍等，正在处理」挡住喵
    assert len(channel.texts) == 1
    assert "测试机" in channel.texts[0][1]
    assert "稍等" not in channel.texts[0][1]


# ==================== simulate 层：看板结论必须与真实机器人一致 ====================


def test_simulate_unknown_command_is_silent(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """看板「命令测试」对未知命令也要显示「不会回复」喵。"""
    # 跑一次未知命令喵
    result = simulate.simulate_command(connection, app_config, "/不存在的命令")
    # 必须是不会回复喵
    assert result.replied is False
    # 原因码要能解释清楚为什么静默喵
    assert result.reason == router.REASON_UNKNOWN_COMMAND
    assert "静默" in result.reason_text
    # 文本与图片都为空喵
    assert result.text == ""
    assert result.image is None


def test_simulate_param_error_still_replies(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """看板里参数错的命令仍要显示回复内容喵。"""
    # 塞一台设备并归组喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 参数乱写喵
    result = simulate.simulate_command(connection, app_config, "/看看happy 全部 乱写")
    # 应判定为会回复喵
    assert result.replied is True
    # 回复里要有错误提示喵
    assert "看不懂" in result.text


def test_simulate_normal_command_still_works(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """看板里正常命令的结论不变喵。"""
    # 塞一台设备并归组喵
    _seed_device(connection, "win-alpha-1111")
    _set_happy_group(app_config, ("win-alpha-1111",))
    # 跑设备清单喵
    result = simulate.simulate_command(connection, app_config, "/happy设备")
    # 应正常回复喵
    assert result.replied is True
    assert result.reason == router.REASON_OK
    assert "测试机" in result.text
