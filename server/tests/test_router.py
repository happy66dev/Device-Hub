"""命令路由的单元测试：访问控制、解析、设备匹配、命令分发喵。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app import ingest, people, queries
from app.bot import channel, commands, router
from app.config import AppConfig
from app.models import ReportPayload
from conftest import make_payload

# 机器人自己的 QQ 号，与 conftest 里的配置无关，测试里显式指定喵
BOT_QQ = 1000000001

# 白名单群号，与 conftest 的 app_config 保持一致喵
ALLOWED_GROUP = 111111

# 黑名单用户，与 conftest 的 app_config 保持一致喵
BLOCKED_USER = 222222

# 普通用户喵
NORMAL_USER = 333333


def _group_event(
    text: str,
    group_id: int = ALLOWED_GROUP,
    user_id: int = NORMAL_USER,
    at_self: bool = True,
    with_prefix: bool = True,
) -> dict[str, Any]:
    """构造一条群消息事件，默认 @ 机器人并带命令前缀喵。"""
    # 消息段列表，按需加入 @ 段喵
    segments: list[dict[str, Any]] = []
    if at_self:
        # @ 机器人喵
        segments.append({"type": "at", "data": {"qq": str(BOT_QQ)}})
    # 按需补上命令前缀喵
    full_text = "/" + text if with_prefix else text
    # 正文段喵
    segments.append({"type": "text", "data": {"text": full_text}})
    # 返回完整事件喵
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": user_id,
        "self_id": BOT_QQ,
        "message": segments,
    }


def test_parse_command_basic() -> None:
    """普通命令应被拆成命令名与参数喵。"""
    # 解析带两个参数的出图命令喵
    parsed = router.parse_command("看看happy 全部 排行榜 7天")
    # 命令名喵
    assert parsed is not None and parsed.name == "看看happy"
    # 参数元组喵
    assert parsed.args == ("全部", "排行榜", "7天")


def test_parse_command_fullwidth_space() -> None:
    """全角空格也应作为分隔符喵。"""
    # 使用全角空格分隔喵
    parsed = router.parse_command("看看happy　手机　时间轴")
    # 参数应被正确切分喵
    assert parsed is not None and parsed.args == ("手机", "时间轴")


def test_parse_command_empty() -> None:
    """空文本应返回 None 喵。"""
    # 空字符串喵
    assert router.parse_command("") is None
    # 只有空白喵
    assert router.parse_command("   ") is None


def test_extract_text_and_mention_array() -> None:
    """数组格式消息应能取出文本并识别 @ 喵。"""
    # 消息体喵
    message = [
        {"type": "at", "data": {"qq": str(BOT_QQ)}},
        {"type": "text", "data": {"text": " /happy设备"}},
    ]
    # 提取结果喵
    text, mentioned = router.extract_text_and_mention(message, str(BOT_QQ))
    # 文本应被去掉首尾空白喵
    assert text == "/happy设备"
    # 应识别到 @ 喵
    assert mentioned is True


def test_extract_text_and_mention_string_message() -> None:
    """字符串格式消息应兼容处理，且不识别 @ 喵。"""
    # 纯字符串消息喵
    text, mentioned = router.extract_text_and_mention("/happy设备", str(BOT_QQ))
    # 文本原样返回喵
    assert text == "/happy设备"
    # 字符串格式无法识别 @ 喵
    assert mentioned is False


def test_extract_text_and_mention_broken_segments() -> None:
    """结构异常的消息段应被安全忽略喵。"""
    # 混入非字典、缺字段的段喵
    message = [None, 42, {"type": "text"}, {"type": "text", "data": {"text": "ok"}}]
    # 提取结果喵
    text, mentioned = router.extract_text_and_mention(message, str(BOT_QQ))
    # 只有合法段的内容被保留喵
    assert text == "ok"
    # 没有 @ 段喵
    assert mentioned is False


def test_inspect_event_accepts_valid_command(app_config: AppConfig) -> None:
    """白名单群 + 非黑名单用户 + @机器人 + 命令前缀应被接受喵。"""
    # 构造事件喵
    event = _group_event("happy设备")
    # 判断结果喵
    should_reply, text, group_id, user_id = router.inspect_event(event, app_config)
    # 应响应喵
    assert should_reply is True
    # 前缀应被去掉喵
    assert text == "happy设备"
    # 群号与用户号应被回传喵
    assert group_id == ALLOWED_GROUP
    assert user_id == NORMAL_USER


def test_inspect_event_rejects_other_group(app_config: AppConfig) -> None:
    """非白名单群应被拒绝喵。"""
    # 使用其它群号喵
    event = _group_event("happy设备", group_id=999999)
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False


def test_inspect_event_rejects_blacklisted_user(app_config: AppConfig) -> None:
    """黑名单用户应被拒绝喵。"""
    # 使用黑名单用户喵
    event = _group_event("happy设备", user_id=BLOCKED_USER)
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False


def test_inspect_event_rejects_without_mention(app_config: AppConfig) -> None:
    """没有 @ 机器人时不应响应喵。"""
    # 不带 @ 段喵
    event = _group_event("happy设备", at_self=False)
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False


def test_inspect_event_rejects_without_prefix(app_config: AppConfig) -> None:
    """@ 了机器人但没写命令前缀应视为闲聊喵。"""
    # 只有普通聊天内容，不带命令前缀喵
    event = _group_event("今天天气不错", with_prefix=False)
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False


def test_inspect_event_strips_leading_invisible_chars(app_config: AppConfig) -> None:
    """命令前的零宽空格等不可见字符必须被吃掉喵。"""
    # 手机输入法常常带上这些看不见的字符喵
    for junk in (" ", "\u3000", "\u200b", "\ufeff", "\u2060", "\u00a0"):
        # 造一条带脏前缀的 @ 消息喵
        event = _group_event(f"{junk}/happy设备", with_prefix=False)
        # 清洗后必须仍能识别成命令喵
        should_reply, command_text, _role, reason = router.inspect_event(event, app_config)
        assert should_reply is True, f"{junk!r} 没被吃掉，reason={reason}"
        # 命令文本里不该残留脏字符喵
        assert command_text == "happy设备", f"{junk!r} 残留：{command_text!r}"


def test_normalize_command_text_collapses_inner_whitespace() -> None:
    """命令内部的连续空白收成一个空格喵。"""
    # 中间夹杂全角与零宽字符喵
    assert channel.normalize_command_text("看看happy \u3000 全部\u200b  排行榜") == "看看happy 全部 排行榜"
    # 空与非字符串都要安全喵
    assert channel.normalize_command_text("   ") == ""
    assert channel.normalize_command_text(None) == ""


def test_build_reply_tolerates_prefix_and_invisible_chars(
    connection: sqlite3.Connection, app_config: AppConfig
) -> None:
    """文本入口要容忍前缀与不可见字符喵。"""
    # 只造一台设备并归组喵
    _seed_device(connection, "win-a-0001")
    _seed_own_group(app_config, ("win-a-0001",))
    # 各种脏前缀都要能跑通喵（不含 "/"，否则拼出 "//happy设备" 双斜杠喵）
    for junk in ("", "\u200b", "\ufeff", "\u00a0", " ", "\u3000"):
        text = router.build_reply(connection, app_config, f"{junk}/happy设备")
        assert "win-a-0001" in text, f"{junk!r} 没被处理"
        assert "未知命令" not in text, f"{junk!r} 被当成未知命令"


def test_inspect_event_rejects_private_message(app_config: AppConfig) -> None:
    """私聊消息暂不处理喵。"""
    # 构造私聊事件喵
    event = _group_event("happy设备")
    event["message_type"] = "private"
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False



def test_private_scope_respects_blacklist(app_config: AppConfig) -> None:
    """拉黑必须对单聊同样生效喵。

    喵~注意：这是真实缺陷。单聊分支原来在白名单校验之后**直接 return**，
    跳过了黑名单检查——同一个用户在群里被拉黑后不响应，私聊却照样能查数据，
    WebUI 里那个「拉黑」按钮对私聊看起来生效、实际无效。
    《docs/qqbot.md》写明黑名单是两道闸门之一，群聊与单聊都必须过喵。
    """
    # 造一个既在私聊白名单、又在黑名单里的用户喵
    from dataclasses import replace

    from app.config import AclSection

    # 私聊白名单放行 openid，同时把这个号加进官方通道黑名单喵
    config = replace(
        app_config,
        acl=AclSection(
            whitelist_groups=app_config.acl.whitelist_groups,
            blacklist_users=app_config.acl.blacklist_users,
            blacklist_member_openids=("BLOCKED_OPENID",),
            private_user_openids=("BLOCKED_OPENID",),
        ),
    )
    # 清掉运行时名单缓存，避免其它用例污染喵
    from app import acl as acl_module

    acl_module._CACHE.clear()
    # 构造一条单聊消息喵
    message = channel.NormalizedMessage(
        channel=channel.CHANNEL_QQBOT,
        group_key="",
        user_key="BLOCKED_OPENID",
        text="/happy设备",
        mentioned=True,
        scope=channel.SCOPE_PRIVATE,
    )
    # 必须被黑名单挡住喵
    accepted, _text, reason = router.inspect_normalized(message, config)
    assert accepted is False
    assert reason == router.REASON_USER_BLACKLISTED


def test_private_scope_allows_whitelisted_user_without_blacklist(app_config: AppConfig) -> None:
    """没被拉黑的白名单用户，私聊照常能用喵。"""
    # 只放私聊白名单，不进黑名单喵
    from dataclasses import replace

    from app.config import AclSection

    config = replace(
        app_config,
        acl=AclSection(
            whitelist_groups=app_config.acl.whitelist_groups,
            blacklist_users=app_config.acl.blacklist_users,
            blacklist_member_openids=(),
            private_user_openids=("GOOD_OPENID",),
        ),
    )
    # 清缓存喵
    from app import acl as acl_module

    acl_module._CACHE.clear()
    # 构造单聊消息喵
    message = channel.NormalizedMessage(
        channel=channel.CHANNEL_QQBOT,
        group_key="",
        user_key="GOOD_OPENID",
        text="/happy设备",
        mentioned=True,
        scope=channel.SCOPE_PRIVATE,
    )
    # 应放行喵
    accepted, _text, _reason = router.inspect_normalized(message, config)
    assert accepted is True


def test_inspect_event_rejects_heartbeat(app_config: AppConfig) -> None:
    """心跳等非消息事件应被忽略喵。"""
    # 构造心跳事件喵
    event = {"post_type": "meta_event", "meta_event_type": "heartbeat"}
    # 应不响应喵
    assert router.inspect_event(event, app_config)[0] is False


def _seed_device(
    connection: sqlite3.Connection,
    device_id: str,
    minutes_ago: int = 0,
    *,
    platform: str = "windows",
    display_name: str = "",
) -> None:
    """插入一台设备，时间可控喵。"""
    # 计算上报时间喵
    reported_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    # 构造上报对象喵
    payload = ReportPayload.model_validate(
        make_payload(
            device_id=device_id,
            platform=platform,
            reported_at=reported_at.isoformat(),
            display_name=display_name or device_id,
        )
    )
    # 落库喵
    ingest.save_report(connection, payload, datetime.now(timezone.utc))


def _happy_context(
    connection: sqlite3.Connection,
    config: AppConfig,
    token: str,
) -> commands.CommandContext:
    """造一个「看看happy」的命令上下文，参数固定为「<范围> 排行榜」喵。"""
    # 基准时间用当前时间，和 save_report 落库口径一致喵
    return commands.CommandContext(
        connection=connection,
        config=config,
        name="看看happy",
        args=(token, "排行榜"),
        now=datetime.now(timezone.utc),
    )


def test_clock_minutes_rejects_bad_format() -> None:
    """时刻写法不对时必须是可捕获的 DeviceLookupError，不能抛裸 ValueError 喵。

    喵~注意：这条盯的是真实事故——`_clock_minutes` 以前是
    `hour_text, minute_text = text.split(":", 1)`，默认「调用方保证格式合法」，
    但调用方从来不校验。用户打「0900」「9点」「abc」直接
    `ValueError: not enough values to unpack`，而这个异常不在 router 的兜底链里，
    结果**群里一个字都不回**，`/api/v1/bot/command` 还返 500喵。
    """
    # 正常写法照常换算喵
    assert commands._clock_minutes("09:00") == 540
    assert commands._clock_minutes("9:05") == 545
    assert commands._clock_minutes("00:00") == 0
    assert commands._clock_minutes("23:59") == 1439
    # 缺冒号、中文、乱写都必须报可读的错喵
    for bad_format in ("0900", "9点", "abc", "", "9-00", "-1:00"):
        with pytest.raises(commands.DeviceLookupError) as error:
            commands._clock_minutes(bad_format)
        # 提示要告诉用户正确格式喵
        assert "格式" in str(error.value) or "看不懂" in str(error.value)


def test_clock_minutes_rejects_out_of_range() -> None:
    """25:00 / 12:60 这种越界时刻必须挡住喵。

    喵~注意：不挡的话 `09:00 99:99` 能通过全部检查，
    反算出的缩放倍数是 1，前端就截出一段**空白天**，
    而且提示还会说「截止要晚于起点」——指错方向喵。
    """
    # 小时越界喵
    for bad_hour in ("24:00", "25:00", "99:99"):
        with pytest.raises(commands.DeviceLookupError) as error:
            commands._clock_minutes(bad_hour)
        assert "范围" in str(error.value)
    # 分钟越界喵
    for bad_minute in ("12:60", "09:99"):
        with pytest.raises(commands.DeviceLookupError) as error:
            commands._clock_minutes(bad_minute)
        assert "范围" in str(error.value)


def test_resolve_scope_exact_name(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """完整设备名应精确命中喵。"""
    # 插入设备并归入主人组喵
    _seed_device(connection, "win-alpha-1111", display_name="本机 Windows")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 按展示名点名喵
    label, device_ids, note = commands._parse_happy_scope(
        "本机 Windows", _happy_context(connection, app_config, "本机 Windows")
    )
    # 应只剩那一台喵
    assert label == "本机 Windows"
    assert device_ids == ["win-alpha-1111"]
    assert note == "本机 Windows"


def test_resolve_scope_prefix_match(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """唯一设备 ID 前缀应命中喵。"""
    # 插入两台设备喵
    _seed_device(connection, "win-alpha-1111", display_name="本机 Windows")
    _seed_device(connection, "win-beta-2222", display_name="平板")
    _seed_own_group(app_config, ("win-alpha-1111", "win-beta-2222"))
    # 用唯一前缀点名喵
    label, device_ids, _note = commands._parse_happy_scope(
        "win-beta", _happy_context(connection, app_config, "win-beta")
    )
    # 应命中平板那台喵
    assert label == "平板"
    assert device_ids == ["win-beta-2222"]


def test_resolve_scope_ambiguous_prefix(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """前缀命中多台设备时应给出歧义提示喵。"""
    # 插入两台同前缀设备喵
    _seed_device(connection, "win-alpha-1111", display_name="本机 Windows")
    _seed_device(connection, "win-alpha-2222", display_name="本机 Windows 二号")
    _seed_own_group(app_config, ("win-alpha-1111", "win-alpha-2222"))
    # 用公共前缀点名喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._parse_happy_scope("win-alpha", _happy_context(connection, app_config, "win-alpha"))
    # 提示应说明匹配到多台并列出候选喵
    assert "匹配到 2 台设备" in str(error.value)


def test_resolve_scope_not_found(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """点名主人组里没有的设备时应给出提示喵。"""
    # 插入一台设备喵
    _seed_device(connection, "win-alpha-1111", display_name="本机 Windows")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 点名一台不存在的设备喵
    with pytest.raises(commands.DeviceLookupError) as error:
        commands._parse_happy_scope("win-ghost", _happy_context(connection, app_config, "win-ghost"))
    # 提示应说明找不到并列出可用范围喵
    assert "找不到" in str(error.value)
    assert "全部" in str(error.value)


def test_resolve_scope_empty_means_all(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """空范围应按整个 happy 组处理喵。"""
    # 插入两台设备喵
    _seed_device(connection, "win-alpha-1111", display_name="本机 Windows")
    _seed_device(connection, "and-beta-2222", display_name="手机", platform="android")
    _seed_own_group(app_config, ("win-alpha-1111", "and-beta-2222"))
    # 传空范围喵
    label, device_ids, note = commands._parse_happy_scope(
        "   ", _happy_context(connection, app_config, "   ")
    )
    # 应是 happy 组全体喵
    assert label == "happy"
    assert device_ids == ["win-alpha-1111", "and-beta-2222"]
    assert note.startswith("happy · ")


def _seed_own_group(config: AppConfig, device_ids: tuple[str, ...]) -> None:
    """把设备写进看板里的 happy 组，happy 系列命令才认喵。"""
    # 直接复用 people 模块的保存函数喵
    people.save_people(config.server.db_path, [people.PersonGroup(name="happy", devices=device_ids)])


def test_build_reply_help(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """happy 帮助命令应返回命令列表喵。"""
    # 生成回复喵
    text = router.build_reply(connection, app_config, "happy帮助")
    # 应包含命令标题喵
    assert "/happy帮助" in text
    # 五条新命令都要列出来喵
    for name in ("/happy帮助", "/happy在干嘛", "/happy干了什么", "/happy设备", "/看看happy"):
        assert name in text


def test_build_reply_empty_text_returns_help(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """只 @ 不说话时应返回帮助喵。"""
    # 空命令文本喵
    text = router.build_reply(connection, app_config, "")
    # 应返回 happy 帮助喵
    assert "/happy帮助" in text


def test_build_reply_unknown_command(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """未知命令应完全静默：不返回任何文本喵。"""
    # 未知命令喵
    text = router.build_reply(connection, app_config, "重启")
    # 喵~注意：未知命令一个字都不回，避免在群里刷屏喵
    assert text == ""
    # 更不许把帮助塞回去，那样和静默就自相矛盾了喵
    assert "未知命令" not in text
    assert "/happy帮助" not in text


def test_build_reply_device_list(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """不带参数的 /happy设备 应返回主人组设备列表喵。"""
    # 插入设备并归入主人组喵
    _seed_device(connection, "win-alpha-1111")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 生成回复喵
    text = router.build_reply(connection, app_config, "happy设备")
    # 应包含设备 ID 喵
    assert "win-alpha-1111" in text
    # 喵~注意：主人要求标题不带「组名 · N 台」这种统计喵
    assert "happy · " not in text
    assert "台）" not in text


def test_build_reply_device_detail(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """点名设备时应把范围收窄到那一台喵。"""
    # 插入两台设备并归入主人组喵
    _seed_device(connection, "win-alpha-1111")
    _seed_device(connection, "and-beta-2222", platform="android", display_name="手机")
    _seed_own_group(app_config, ("win-alpha-1111", "and-beta-2222"))
    # 点名手机看排行榜喵
    text = router.build_reply(connection, app_config, "看看happy and-beta 排行榜")
    # 喵~注意：标题在 2d492d5 里改成了「查看 happy 最近 X 的应用排行」，
    # 这里跟着改成新标题，别让断言继续对着已经不存在的旧文案喵
    assert "查看 happy 最近" in text
    # 应说明要出排行榜图喵
    assert "应用排行" in text


def test_build_reply_usage_requires_device(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """不带参数的 /看看happy 应给出用法提示喵。"""
    # 插入设备并归入主人组喵
    _seed_device(connection, "win-alpha-1111")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 生成回复喵
    text = router.build_reply(connection, app_config, "看看happy")
    # 应提示用法喵
    assert "用法" in text
    # 两种写法都要给出示例喵
    assert "排行榜" in text and "时间轴" in text


def test_build_reply_usage_invalid_window(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """看不懂的时间窗口应给出提示而不是崩溃喵。"""
    # 插入设备并归入主人组喵
    _seed_device(connection, "win-alpha-1111")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 用「很久」当时间窗口喵
    text = router.build_reply(connection, app_config, "看看happy 全部 排行榜 很久")
    # 应提示窗口看不懂喵
    assert "时间窗口看不懂" in text


def test_build_reply_usage_success(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """正常 /happy干了什么 应返回近 24 小时排行喵。"""
    # 插入设备（该设备已带一条 Code.exe 的增量记录）喵
    _seed_device(connection, "win-alpha-1111")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 再补一条另一个应用的使用记录，避免与已有记录的时间点冲突喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, sampled_at, seconds) VALUES (?, ?, ?, ?)",
        ("win-alpha-1111", "Edge.exe", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 120),
    )
    connection.commit()
    # 生成回复喵
    text = router.build_reply(connection, app_config, "happy干了什么")
    # 应包含排行标题与写入的应用喵
    assert "近24小时内 happy使用了下面的东西" in text
    assert "Edge.exe" in text


def test_build_reply_device_not_found(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """点名不存在的设备应返回提示而不是异常喵。"""
    # 先插入一台设备，保证走"有设备但匹配不到"的分支喵
    _seed_device(connection, "win-alpha-1111")
    _seed_own_group(app_config, ("win-alpha-1111",))
    # 点名一台不存在的设备喵
    text = router.build_reply(connection, app_config, "看看happy win-ghost 排行榜")
    # 应提示找不到并列出可用范围喵
    assert "找不到" in text
    assert "全部" in text

