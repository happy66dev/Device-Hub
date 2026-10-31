"""官方 QQ Bot 通道的单元与集成测试喵。

覆盖点：
- access_token 换票、缓存与提前刷新；
- 网关握手（Identify / Resume）、应用层心跳、事件归一化与投递；
- 群消息发送（msg_id / msg_seq）、图片先上传再发；
- 全量模式的 @ 探测、前缀预过滤、消息去重；
- 免 @ 触发与角色门槛的准入判断。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

import httpx
import pytest
import websockets

from app.bot import router
from app.bot.channel import (
    CHANNEL_QQBOT,
    NormalizedMessage,
    detect_self_mention,
    from_qqbot_event,
    strip_mention_placeholders,
)
from app.bot.qqbot import (
    QQBotApi,
    QQBotChannel,
    QQBotClient,
    QQBotError,
    ReplyCounter,
    SeenMessages,
)
from app.config import AppConfig, QQBotSection

# 测试用机器人自身 ID 喵
BOT_ID = "BOT_OPENID_1"

# 测试用群 openid 喵
GROUP_OPENID = "GROUP_OPENID_A"

# 测试用成员 openid 喵
MEMBER_OPENID = "MEMBER_OPENID_X"


def _make_api(handler) -> QQBotApi:
    """用 MockTransport 造一个不发真实请求的 API 客户端喵。"""

    def wrapped(request: httpx.Request) -> httpx.Response:
        """换票接口自动返回 token，其余交给用例处理喵。"""
        # 喵~防御：每个用例都手写换票响应太啰嗦，这里统一兜住喵
        if request.url.path.endswith("/getAppAccessToken"):
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": "7200"})
        return handler(request)

    # 注入 MockTransport，所有请求都走本地处理函数喵
    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    # 返回封装好的 API 喵
    return QQBotApi("https://api.test", "app-id", "app-secret", client=client)


def _qqbot_config(app_config: AppConfig, **overrides: Any) -> AppConfig:
    """在测试配置上打开官方通道喵。"""
    # 默认开一个能跑的最小配置喵
    section = QQBotSection(
        enabled=True,
        app_id="app-id",
        app_secret="app-secret",
        api_base="https://api.test",
        intents=1 << 25,
        token_refresh_margin_seconds=60,
        heartbeat_slack_seconds=0,
        request_timeout_seconds=5.0,
        reconnect_seconds=1,
        log_openids=False,
    )
    # 允许用例覆盖单个字段喵
    section = dataclasses.replace(section, **overrides)
    # 同时把群 openid 白名单塞进 ACL 喵
    acl = dataclasses.replace(
        app_config.acl,
        whitelist_group_openids=(GROUP_OPENID,),
        blacklist_member_openids=("BLOCKED_OPENID",),
        private_user_openids=("PRIVATE_OPENID",),
    )
    # 返回替换后的配置喵
    return dataclasses.replace(app_config, qqbot=section, acl=acl)


def _group_event(content: str, *, event_type: str = "GROUP_AT_MESSAGE_CREATE", msg_id: str = "MSG1", role: str = "member") -> dict[str, Any]:
    """构造一条官方群消息事件喵。"""
    # 官方事件信封喵
    return {
        "id": f"EVENT_{msg_id}",
        "op": 0,
        "s": 7,
        "t": event_type,
        "d": {
            "id": msg_id,
            "content": content,
            "group_openid": GROUP_OPENID,
            "author": {"member_openid": MEMBER_OPENID, "member_role": role, "username": "小明"},
            "timestamp": "2026-10-31T12:00:00+08:00",
        },
    }


# ==================== HTTP API ====================


@pytest.mark.asyncio
async def test_access_token_is_cached() -> None:
    """token 有效期内应复用缓存，不要每次调用都换票喵。"""
    # 记录请求次数喵
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假换票接口喵。"""
        calls.append(request.url.path)
        return httpx.Response(200, json={"access_token": "TOKEN-1", "expires_in": "7200"})

    # 这个用例要自己控制换票响应，所以不走 _make_api 喵
    api = QQBotApi(
        "https://api.test",
        "app-id",
        "app-secret",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    # 连续取两次喵
    assert await api.access_token() == "TOKEN-1"
    assert await api.access_token() == "TOKEN-1"
    # 只应请求一次喵
    assert calls == ["/app/getAppAccessToken"]


@pytest.mark.asyncio
async def test_access_token_refreshes_when_expired() -> None:
    """过了刷新窗口应重新换票喵。"""
    # 每次返回不同 token 喵
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假换票接口喵。"""
        token = f"TOKEN-{len(issued) + 1}"
        issued.append(token)
        return httpx.Response(200, json={"access_token": token, "expires_in": "7200"})

    # 刷新窗口设成有效期本身，等价于立刻过期喵
    api = QQBotApi(
        "https://api.test",
        "app-id",
        "app-secret",
        refresh_margin_seconds=7200,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    # 两次调用应拿到不同 token 喵
    assert await api.access_token() == "TOKEN-1"
    assert await api.access_token() == "TOKEN-2"


@pytest.mark.asyncio
async def test_access_token_failure_raises() -> None:
    """换票失败时 HTTP 仍是 200，必须靠 body 的 code 判断喵。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """假失败响应喵。"""
        return httpx.Response(200, json={"code": 100007, "message": "appid invalid"})

    # 这个用例要自己控制换票响应，所以不走 _make_api 喵
    api = QQBotApi(
        "https://api.test",
        "app-id",
        "app-secret",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    # 应抛带错误码的异常喵
    with pytest.raises(QQBotError) as error:
        await api.access_token()
    assert error.value.code == 100007
    assert error.value.scope == "token"


@pytest.mark.asyncio
async def test_send_text_carries_msg_id_and_seq() -> None:
    """被动回复必须带 msg_id 与 msg_seq，否则平台当主动消息喵。"""
    # 记录请求体喵
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假发消息接口喵。"""
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "OUT-1"})

    # 造 API 喵
    api = _make_api(handler)
    # 发一条被动回复喵
    await api.send_text("group", GROUP_OPENID, "你好", msg_id="MSG1", msg_seq=2)
    # 断言请求体喵
    assert bodies[0] == {"msg_type": 0, "content": "你好", "msg_id": "MSG1", "msg_seq": 2}


@pytest.mark.asyncio
async def test_send_text_uses_user_path_for_private() -> None:
    """单聊要走 /v2/users 而不是 /v2/groups 喵。"""
    # 记录请求路径喵
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假发消息接口喵。"""
        paths.append(request.url.path)
        return httpx.Response(200, json={"id": "OUT-2"})

    # 造 API 喵
    api = _make_api(handler)
    # 发一条单聊消息喵
    await api.send_text("private", "USER_OPENID", "你好")
    # 断言路径喵
    assert paths == ["/v2/users/USER_OPENID/messages"]


@pytest.mark.asyncio
async def test_upload_image_sends_base64_and_returns_file_info() -> None:
    """官方不支持内联 base64，必须先上传拿 file_info 喵。"""
    # 记录请求体喵
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假上传接口喵。"""
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"file_info": "FILE-INFO-1", "ttl": 300})

    # 造 API 喵
    api = _make_api(handler)
    # 上传一张假 PNG 喵
    file_info = await api.upload_image("group", GROUP_OPENID, b"\x89PNG\r\n\x1a\n")
    # 断言返回与请求体喵
    assert file_info == "FILE-INFO-1"
    assert bodies[0]["file_type"] == 1
    assert bodies[0]["srv_send_msg"] is False
    assert bodies[0]["file_data"] == "iVBORw0KGgo="


@pytest.mark.asyncio
async def test_send_image_uses_msg_type_7() -> None:
    """富媒体消息的 msg_type 必须是 7 且带 media.file_info 喵。"""
    # 记录请求体喵
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假发消息接口喵。"""
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "OUT-3"})

    # 造 API 喵
    api = _make_api(handler)
    # 发一条富媒体消息喵
    await api.send_image("group", GROUP_OPENID, "FILE-INFO-1", msg_id="MSG1", msg_seq=1)
    # 断言请求体喵
    assert bodies[0]["msg_type"] == 7
    assert bodies[0]["media"] == {"file_info": "FILE-INFO-1"}
    assert bodies[0]["msg_id"] == "MSG1"


@pytest.mark.asyncio
async def test_business_error_code_raises() -> None:
    """业务错误要看 err_code，不能只看 HTTP 200 喵。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """假业务失败响应喵。"""
        return httpx.Response(200, json={"err_code": 40054005, "message": "消息被去重"})

    # 造 API 喵
    api = _make_api(handler)
    # 应抛业务异常喵
    with pytest.raises(QQBotError) as error:
        await api.send_text("group", GROUP_OPENID, "你好", msg_id="MSG1", msg_seq=1)
    assert error.value.code == 40054005
    assert error.value.scope == "business"


# ==================== 归一化 ====================


def test_strip_mention_placeholders() -> None:
    """全量模式下的 @ 占位符必须清掉喵。"""
    # 带两个占位符的文本喵
    assert strip_mention_placeholders("<@!ABC123> /设备 <@all>") == "/设备"
    # 非字符串按空串处理喵
    assert strip_mention_placeholders(None) == ""


def test_detect_self_mention() -> None:
    """全量模式靠占位符判断是否 @ 了机器人喵。"""
    # 命中自己的两种写法喵
    assert detect_self_mention(f"<@{BOT_ID}> /设备", BOT_ID) is True
    assert detect_self_mention(f"<@!{BOT_ID}> /设备", BOT_ID) is True
    # 没 @ 自己喵
    assert detect_self_mention("/设备", BOT_ID) is False
    # 没有自身 ID 时一律按未 @ 处理喵
    assert detect_self_mention(f"<@{BOT_ID}> /设备", None) is False


def test_from_qqbot_group_at_event() -> None:
    """群 @ 事件应转成群会话的归一化消息喵。"""
    # 转换喵
    result = from_qqbot_event(_group_event(" /设备 "), BOT_ID)
    # 断言字段喵
    assert result.message is not None
    message = result.message
    assert message.channel == CHANNEL_QQBOT
    assert message.group_key == GROUP_OPENID
    assert message.user_key == MEMBER_OPENID
    assert message.text == "/设备"
    assert message.mentioned is True
    assert message.scope == "group"
    assert message.reply_token == "MSG1"


def test_from_qqbot_full_mode_event_detects_mention() -> None:
    """全量模式要按占位符判断 @ 并清洗文本喵。"""
    # 带 @ 占位符的全量事件喵
    event = _group_event(f"<@{BOT_ID}> /设备", event_type="GROUP_MESSAGE_CREATE", role="admin")
    # 转换喵
    message = from_qqbot_event(event, BOT_ID).message
    # 断言喵
    assert message is not None
    assert message.mentioned is True
    assert message.text == "/设备"
    assert message.role == "admin"
    # 没 @ 自己的全量消息应标记为未 @ 喵
    plain = from_qqbot_event(_group_event("/设备", event_type="GROUP_MESSAGE_CREATE"), BOT_ID).message
    assert plain is not None and plain.mentioned is False


def test_from_qqbot_private_event() -> None:
    """单聊事件应转成 private 会话喵。"""
    # 单聊事件喵
    event = {
        "op": 0,
        "s": 1,
        "t": "C2C_MESSAGE_CREATE",
        "d": {"id": "C2C1", "content": "/帮助", "author": {"user_openid": "PRIVATE_OPENID"}},
    }
    # 转换喵
    message = from_qqbot_event(event, BOT_ID).message
    # 断言喵
    assert message is not None
    assert message.scope == "private"
    assert message.group_key == ""
    assert message.user_key == "PRIVATE_OPENID"


def test_from_qqbot_ignores_non_message_events() -> None:
    """进群退群等事件不参与命令处理喵。"""
    # 进群事件喵
    event = {"op": 0, "t": "GROUP_ADD_ROBOT", "d": {"group_openid": GROUP_OPENID}}
    # 应返回 None 与原因码喵
    result = from_qqbot_event(event, BOT_ID)
    assert result.message is None
    assert result.reason == router.REASON_NOT_MESSAGE


# ==================== 准入判断 ====================


def _message(text: str, **overrides: Any) -> NormalizedMessage:
    """构造一条官方群消息，方便测准入判断喵。"""
    # 默认白名单群 + 已 @ 喵
    base = NormalizedMessage(
        channel=CHANNEL_QQBOT,
        group_key=GROUP_OPENID,
        user_key=MEMBER_OPENID,
        text=text,
        mentioned=True,
    )
    # 允许用例覆盖字段喵
    return dataclasses.replace(base, **overrides)


def test_inspect_normalized_accepts_whitelisted_group(app_config: AppConfig) -> None:
    """白名单群 + 已 @ + 命令前缀应放行喵。"""
    # 用官方通道配置喵
    config = _qqbot_config(app_config)
    # 判定喵
    handled, command_text, reason = router.inspect_normalized(_message("/设备"), config)
    # 断言喵
    assert handled is True
    assert command_text == "设备"
    assert reason == router.REASON_OK


def test_inspect_normalized_rejects_unknown_group(app_config: AppConfig) -> None:
    """不在 openid 白名单的群应被拒绝喵。"""
    # 用官方通道配置喵
    config = _qqbot_config(app_config)
    # 换一个群标识喵
    handled, _text, reason = router.inspect_normalized(_message("/设备", group_key="OTHER_GROUP"), config)
    # 断言喵
    assert handled is False
    assert reason == router.REASON_GROUP_NOT_WHITELISTED


def test_inspect_normalized_rejects_blacklisted_member(app_config: AppConfig) -> None:
    """黑名单 member_openid 即使 @ 了也不响应喵。"""
    # 用官方通道配置喵
    config = _qqbot_config(app_config)
    # 换成黑名单成员喵
    handled, _text, reason = router.inspect_normalized(_message("/设备", user_key="BLOCKED_OPENID"), config)
    # 断言喵
    assert handled is False
    assert reason == router.REASON_USER_BLACKLISTED


def test_inspect_normalized_requires_mention_by_default(app_config: AppConfig) -> None:
    """没开免 @ 的群必须 @ 机器人才响应喵。"""
    # 用官方通道配置喵
    config = _qqbot_config(app_config)
    # 未 @ 喵
    handled, _text, reason = router.inspect_normalized(_message("/设备", mentioned=False), config)
    # 断言喵
    assert handled is False
    assert reason == router.REASON_NOT_MENTIONED


def test_inspect_normalized_free_mode_requires_prefix(app_config: AppConfig) -> None:
    """免 @ 群里不带前缀的闲聊必须忽略喵。"""
    # 打开免 @ 喵
    config = _qqbot_config(app_config, free_command_group_openids=(GROUP_OPENID,))
    # 闲聊喵
    handled, _text, reason = router.inspect_normalized(_message("今天天气不错", mentioned=False), config)
    # 断言喵
    assert handled is False
    assert reason == router.REASON_NOT_COMMAND
    # 带前缀就放行喵
    handled_ok, command_text, reason_ok = router.inspect_normalized(_message("/设备", mentioned=False), config)
    assert handled_ok is True
    assert command_text == "设备"
    assert reason_ok == router.REASON_OK


def test_inspect_normalized_free_mode_role_gate(app_config: AppConfig) -> None:
    """免 @ 模式下可以按角色收紧权限喵。"""
    # 要求管理员喵
    config = _qqbot_config(app_config, free_command_group_openids=(GROUP_OPENID,), free_command_min_role="admin")
    # 普通成员应被拒喵
    handled, _text, reason = router.inspect_normalized(_message("/设备", mentioned=False, role="member"), config)
    assert handled is False
    assert reason == router.REASON_ROLE_TOO_LOW
    # 管理员应放行喵
    handled_admin, _text2, reason_admin = router.inspect_normalized(
        _message("/设备", mentioned=False, role="admin"), config
    )
    assert handled_admin is True
    assert reason_admin == router.REASON_OK


def test_inspect_normalized_private_requires_whitelist(app_config: AppConfig) -> None:
    """单聊默认不响应，只有白名单里的 user_openid 能用喵。"""
    # 用官方通道配置喵
    config = _qqbot_config(app_config)
    # 白名单里的单聊喵
    allowed, _text, reason = router.inspect_normalized(
        _message("/帮助", scope="private", group_key="", user_key="PRIVATE_OPENID"), config
    )
    assert allowed is True
    assert reason == router.REASON_OK
    # 陌生人的单聊喵
    denied, _text2, reason_denied = router.inspect_normalized(
        _message("/帮助", scope="private", group_key="", user_key="STRANGER"), config
    )
    assert denied is False
    assert reason_denied == router.REASON_GROUP_NOT_WHITELISTED


# ==================== 计数器与去重 ====================


def test_reply_counter_increments_per_message() -> None:
    """同一 msg_id 的序号必须递增，不同消息各自从 1 开始喵。"""
    # 造计数器喵
    counter = ReplyCounter()
    # 同一消息连续三次喵
    assert [counter.next("A"), counter.next("A"), counter.next("A")] == [1, 2, 3]
    # 另一条消息重新从 1 开始喵
    assert counter.next("B") == 1


def test_seen_messages_deduplicates() -> None:
    """重复推送的同一条消息只放行一次喵。"""
    # 造去重器喵
    seen = SeenMessages(capacity=2)
    # 第一次放行喵
    assert seen.first_time("M1") is True
    # 第二次拒绝喵
    assert seen.first_time("M1") is False
    # 没有 ID 时一律放行喵
    assert seen.first_time("") is True


# ==================== 网关集成 ====================


class _FakeApi:
    """只提供网关地址与 token 的假 API，供网关测试用喵。"""

    def __init__(self, url: str) -> None:
        # 假网关地址喵
        self._url = url
        # 记录被取过几次 token 喵
        self.token_calls = 0

    async def gateway_url(self) -> str:
        """返回假网关地址喵。"""
        return self._url

    async def access_token(self) -> str:
        """返回假 token 喵。"""
        self.token_calls += 1
        return "TOKEN"


async def _noop_handler(message: Any) -> None:
    """不做事的事件处理器，探针测试只关心日志喵。"""
    # 探针测试不消费消息喵
    return None


async def _wait_until(predicate, timeout_seconds: float = 5.0) -> None:
    """轮询等待条件成立喵。"""
    # 记录截止时间喵
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    # 轮询喵
    while loop.time() < deadline:
        # 成立就返回喵
        if predicate():
            return
        # 让出事件循环喵
        await asyncio.sleep(0.02)
    # 超时直接失败喵
    raise AssertionError("等待条件超时")


@pytest.mark.asyncio
async def test_gateway_identifies_and_receives_event(app_config: AppConfig) -> None:
    """完整握手：Hello → Identify → READY → 事件投递 + 应用层心跳喵。"""
    # 记录客户端发来的帧喵
    received: list[dict[str, Any]] = []
    # 收到的归一化消息喵
    messages: list[NormalizedMessage] = []

    async def fake_gateway(websocket, path: str | None = None) -> None:
        """假官方网关喵。"""
        # 第一条必须发 Hello 喵
        await websocket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 1500}}))
        # 收 Identify 喵
        received.append(json.loads(await websocket.recv()))
        # 回 READY 喵
        await websocket.send(
            json.dumps({"op": 0, "s": 1, "t": "READY", "d": {"session_id": "S1", "user": {"id": BOT_ID}}})
        )
        # 推一条群 @ 消息喵
        await websocket.send(json.dumps(_group_event("/设备")))
        # 再等一会儿，收心跳喵
        try:
            while True:
                received.append(json.loads(await asyncio.wait_for(websocket.recv(), timeout=6.0)))
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            return

    async def handler(message: NormalizedMessage) -> None:
        """记录收到的消息喵。"""
        messages.append(message)

    # 起假网关喵
    async with websockets.serve(fake_gateway, "127.0.0.1", 0) as server:
        # 取实际端口喵
        port = server.sockets[0].getsockname()[1]
        # 造配置与客户端喵
        config = _qqbot_config(app_config)
        client = QQBotClient(
            config,
            _FakeApi(f"ws://127.0.0.1:{port}"),
            handler,
            connector=lambda url: websockets.connect(url),
        )
        # 启动客户端喵
        task = asyncio.create_task(client.run())
        try:
            # 等到消息投递喵
            await _wait_until(lambda: len(messages) >= 1)
            # 再等心跳喵
            await _wait_until(lambda: any(frame.get("op") == 1 for frame in received))
        finally:
            # 停掉客户端喵
            await client.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # 断言 Identify 内容喵
    identify = received[0]
    assert identify["op"] == 2
    assert identify["d"]["token"] == "QQBot TOKEN"
    assert identify["d"]["intents"] == 1 << 25
    # 断言消息内容喵
    assert messages[0].group_key == GROUP_OPENID
    assert messages[0].text == "/设备"
    # 心跳必须带最新序号喵
    heartbeats = [frame for frame in received if frame.get("op") == 1]
    assert heartbeats and heartbeats[0]["d"] == 7


@pytest.mark.asyncio
async def test_gateway_resumes_after_disconnect(app_config: AppConfig) -> None:
    """断线重连应发 op=6 Resume，而不是重新 Identify 喵。"""
    # 记录每次连接的握手帧喵
    handshakes: list[dict[str, Any]] = []
    # 连接次数喵
    connections = 0

    async def fake_gateway(websocket, path: str | None = None) -> None:
        """假网关：第一次连上后主动断开喵。"""
        nonlocal connections
        connections += 1
        # 发 Hello 喵
        await websocket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 60000}}))
        # 记录握手帧喵
        handshakes.append(json.loads(await websocket.recv()))
        # 第一次连接：回 READY 后立刻断开喵
        if connections == 1:
            await websocket.send(
                json.dumps({"op": 0, "s": 5, "t": "READY", "d": {"session_id": "S9", "user": {"id": BOT_ID}}})
            )
            await websocket.close()
            return
        # 第二次连接：回 RESUMED 并保持喵
        await websocket.send(json.dumps({"op": 0, "s": 6, "t": "RESUMED", "d": {}}))
        await asyncio.sleep(0.5)

    async def handler(message: NormalizedMessage) -> None:
        """本用例不关心消息喵。"""
        return None

    # 起假网关喵
    async with websockets.serve(fake_gateway, "127.0.0.1", 0) as server:
        # 取实际端口喵
        port = server.sockets[0].getsockname()[1]
        # 造配置与客户端喵
        config = _qqbot_config(app_config)
        client = QQBotClient(
            config,
            _FakeApi(f"ws://127.0.0.1:{port}"),
            handler,
            connector=lambda url: websockets.connect(url),
        )
        # 启动客户端喵
        task = asyncio.create_task(client.run())
        try:
            # 等到第二次握手喵
            await _wait_until(lambda: len(handshakes) >= 2)
        finally:
            # 停掉客户端喵
            await client.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # 第一次是 Identify，第二次必须是 Resume 喵
    assert handshakes[0]["op"] == 2
    assert handshakes[1]["op"] == 6
    assert handshakes[1]["d"]["session_id"] == "S9"
    assert handshakes[1]["d"]["seq"] == 5


@pytest.mark.asyncio
async def test_gateway_deduplicates_same_message(app_config: AppConfig) -> None:
    """同一条消息推两次也只能处理一次喵。"""
    # 收到的消息喵
    messages: list[NormalizedMessage] = []

    async def fake_gateway(websocket, path: str | None = None) -> None:
        """假网关：把同一条消息推两遍喵。"""
        await websocket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 60000}}))
        await websocket.recv()
        await websocket.send(
            json.dumps({"op": 0, "s": 1, "t": "READY", "d": {"session_id": "S2", "user": {"id": BOT_ID}}})
        )
        await websocket.send(json.dumps(_group_event("/设备", msg_id="DUP")))
        await websocket.send(json.dumps(_group_event("/设备", msg_id="DUP")))
        await asyncio.sleep(0.3)

    async def handler(message: NormalizedMessage) -> None:
        """记录消息喵。"""
        messages.append(message)

    # 起假网关喵
    async with websockets.serve(fake_gateway, "127.0.0.1", 0) as server:
        # 取端口喵
        port = server.sockets[0].getsockname()[1]
        # 造客户端喵
        client = QQBotClient(
            _qqbot_config(app_config),
            _FakeApi(f"ws://127.0.0.1:{port}"),
            handler,
            connector=lambda url: websockets.connect(url),
        )
        # 启动喵
        task = asyncio.create_task(client.run())
        try:
            # 等第一条消息喵
            await _wait_until(lambda: len(messages) >= 1)
            # 再等一会儿，确认第二条被丢弃喵
            await asyncio.sleep(0.2)
        finally:
            # 停止喵
            await client.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # 只应收到一条喵
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_gateway_filters_full_mode_chatter(app_config: AppConfig) -> None:
    """全量模式下不在免 @ 群的闲聊必须在入队前丢弃喵。"""
    # 收到的消息喵
    messages: list[NormalizedMessage] = []

    async def fake_gateway(websocket, path: str | None = None) -> None:
        """假网关：推一条闲聊与一条命令喵。"""
        await websocket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 60000}}))
        await websocket.recv()
        await websocket.send(
            json.dumps({"op": 0, "s": 1, "t": "READY", "d": {"session_id": "S3", "user": {"id": BOT_ID}}})
        )
        # 闲聊，未 @ 机器人喵
        await websocket.send(json.dumps(_group_event("今天吃什么", event_type="GROUP_MESSAGE_CREATE", msg_id="CHAT1")))
        # 正常 @ 命令喵
        await websocket.send(json.dumps(_group_event("/设备", msg_id="CMD1")))
        await asyncio.sleep(0.3)

    async def handler(message: NormalizedMessage) -> None:
        """记录消息喵。"""
        messages.append(message)

    # 起假网关喵
    async with websockets.serve(fake_gateway, "127.0.0.1", 0) as server:
        # 取端口喵
        port = server.sockets[0].getsockname()[1]
        # 造客户端喵
        client = QQBotClient(
            _qqbot_config(app_config),
            _FakeApi(f"ws://127.0.0.1:{port}"),
            handler,
            connector=lambda url: websockets.connect(url),
        )
        # 启动喵
        task = asyncio.create_task(client.run())
        try:
            # 等命令消息喵
            await _wait_until(lambda: len(messages) >= 1)
            # 多等一会儿确认闲聊没进来喵
            await asyncio.sleep(0.2)
        finally:
            # 停止喵
            await client.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # 只应收到 @ 命令那一条喵
    assert [message.text for message in messages] == ["/设备"]


@pytest.mark.asyncio
async def test_channel_sends_image_then_text_with_increasing_seq(app_config: AppConfig) -> None:
    """发图要先上传再发富媒体，序号必须递增喵。"""
    # 记录请求喵
    requests: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假接口喵。"""
        payload = json.loads(request.content) if request.content else {}
        requests.append((request.url.path, payload))
        # 上传接口返回 file_info 喵
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"file_info": "FILE-1"})
        # 发消息接口返回 id 喵
        return httpx.Response(200, json={"id": "OUT-9"})

    # 造通道喵
    channel = QQBotChannel(
        _qqbot_config(app_config),
        lambda message: asyncio.sleep(0),
        api=_make_api(handler),
    )
    # 发图并带说明喵
    await channel.send_image(GROUP_OPENID, b"\x89PNG\r\n\x1a\n", reply_token="MSG1", caption="说明")
    # 应有三条请求：上传、富媒体、说明文本喵
    assert [path for path, _payload in requests] == [
        f"/v2/groups/{GROUP_OPENID}/files",
        f"/v2/groups/{GROUP_OPENID}/messages",
        f"/v2/groups/{GROUP_OPENID}/messages",
    ]
    # 富媒体消息喵
    assert requests[1][1]["msg_type"] == 7
    assert requests[1][1]["msg_seq"] == 1
    # 说明文本的序号必须递增喵
    assert requests[2][1]["msg_type"] == 0
    assert requests[2][1]["msg_seq"] == 2


# ==================== 事件探针 ====================


def _at_event(content: str, msg_id: str = "MSG1") -> dict[str, Any]:
    """造一条群里 @ 机器人的官方事件喵。"""
    # 官方 @ 事件的信封结构喵
    return {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": msg_id,
            "content": content,
            "group_openid": GROUP_OPENID,
            "author": {"member_openid": "MEMBER1", "member_role": "member"},
        },
    }


def test_debug_events_logs_raw_payload(
    app_config: AppConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """开着 debug_events 时原始事件要能打进日志喵。"""
    # 打开调试开关喵
    config = _qqbot_config(app_config, debug_events=True)
    client = QQBotClient(config, _FakeApi("ws://127.0.0.1:1"), _noop_handler)
    # 抓 INFO 日志喵
    with caplog.at_level("INFO", logger="device_hub.bot"):
        client._enqueue_event(_at_event("<@!BOT> /happy在干嘛"))
    # 原始事件与归一化文本都要出现喵
    assert "QQ Bot 原始事件" in caplog.text
    assert "GROUP_AT_MESSAGE_CREATE" in caplog.text
    assert "归一化" in caplog.text
    # 喵~注意：正文原样打出来，才能看出前缀有没有被吃掉喵
    assert "/happy在干嘛" in caplog.text


def test_debug_events_off_by_default(app_config: AppConfig, caplog: pytest.LogCaptureFixture) -> None:
    """默认不打原始事件，避免日志被闲聊灌满喵。"""
    # 用默认配置喵
    config = _qqbot_config(app_config, debug_events=False)
    client = QQBotClient(config, _FakeApi("ws://127.0.0.1:1"), _noop_handler)
    # 抓日志喵
    with caplog.at_level("INFO", logger="device_hub.bot"):
        client._enqueue_event(_at_event("<@!BOT> /happy在干嘛"))
    # 不该出现原始事件那行喵
    assert "QQ Bot 原始事件" not in caplog.text


def test_debug_events_logs_drop_reason(
    app_config: AppConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """非消息事件被丢弃时也要说明原因喵。"""
    # 打开调试开关喵
    config = _qqbot_config(app_config, debug_events=True)
    client = QQBotClient(config, _FakeApi("ws://127.0.0.1:1"), _noop_handler)
    # 造一条心跳回执，不是消息喵
    with caplog.at_level("INFO", logger="device_hub.bot"):
        client._enqueue_event({"op": 11})
    # 应说明被丢弃喵
    assert "事件被丢弃" in caplog.text
    assert "not_message" in caplog.text
