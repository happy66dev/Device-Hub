"""机器人端到端测试：用假的 NapCat 服务端跑通"收事件 → 查库 → 回消息"。

为什么要有这层测试：真实 NapCat 需要重启 QQ 才能改配置，
用假服务端可以在不打扰主人的前提下验证协议字段与消息结构喵。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import pytest
import websockets

from app import db, ingest, people
from app.bot import happy
from app.bot.napcat import NapCatClient
from app.bot.runner import BotRunner
from app.bot.channel import NormalizedMessage
from app.config import AppConfig, NapCatSection, QQBotSection
from app.models import ReportPayload
from conftest import make_payload

# 机器人 QQ 号喵
BOT_QQ = "1000000001"

# 白名单群号，与 conftest 的配置一致喵
ALLOWED_GROUP = 111111

# 普通用户 QQ 号喵
NORMAL_USER = 333333


def _group_message_event(text: str) -> dict[str, Any]:
    """构造一条 @机器人 的群消息事件喵。"""
    # 返回 OneBot 11 事件结构喵
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": ALLOWED_GROUP,
        "user_id": NORMAL_USER,
        "self_id": int(BOT_QQ),
        "message": [
            {"type": "at", "data": {"qq": BOT_QQ}},
            {"type": "text", "data": {"text": text}},
        ],
    }


def _extract_reply_text(action_payload: dict[str, Any]) -> str:
    """从动作请求里取出要发送的文本喵。"""
    # 取出参数里的消息段喵
    message_segments = action_payload.get("params", {}).get("message", [])
    # 拼接所有文本段喵
    text_parts = [
        segment.get("data", {}).get("text", "")
        for segment in message_segments
        if isinstance(segment, dict) and segment.get("type") == "text"
    ]
    # 返回拼接结果喵
    return "".join(text_parts)


async def _wait_until(predicate, timeout_seconds: float = 10.0) -> None:
    """轮询等待条件成立，超时则断言失败喵。"""
    # 记录开始时间喵
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    # 轮询等待喵
    while loop.time() < deadline:
        # 条件成立就返回喵
        if predicate():
            return
        # 短暂让出事件循环喵
        await asyncio.sleep(0.05)
    # 喵~防御：超时说明链路没跑通，直接失败并给出提示喵
    raise AssertionError("等待条件超时，机器人链路可能没有跑通")


@pytest.mark.asyncio
async def test_client_receives_event_and_sends_action() -> None:
    """客户端应能收到事件并通过带 echo 的动作回包完成发送喵。"""
    # 记录服务端收到的动作喵
    received_actions: list[dict[str, Any]] = []

    async def fake_napcat(websocket, path: str | None = None) -> None:
        """假 NapCat：先推一条事件，再等待客户端发动作并回包喵。"""
        # 推送一条心跳事件，验证非消息事件被忽略且不报错喵
        await websocket.send(json.dumps({"post_type": "meta_event", "meta_event_type": "heartbeat"}))
        # 推送一条群消息事件喵
        await websocket.send(json.dumps(_group_message_event("/happy帮助")))
        # 等待客户端发动作喵
        raw_action = await asyncio.wait_for(websocket.recv(), timeout=10)
        # 记录动作内容喵
        action_payload = json.loads(raw_action)
        received_actions.append(action_payload)
        # 回包，必须带回同一个 echo 喵
        await websocket.send(
            json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": 1}, "echo": action_payload["echo"]})
        )
        # 保持连接一会儿，避免客户端立刻重连干扰断言喵
        await asyncio.sleep(0.3)

    # 启动假服务端，端口交给系统分配喵
    async with websockets.serve(fake_napcat, "127.0.0.1", 0) as server:
        # 取出实际端口喵
        port = server.sockets[0].getsockname()[1]
        # 记录收到的事件喵
        received_events: list[dict[str, Any]] = []

        async def on_event(event: dict[str, Any]) -> None:
            """把事件记下来，并对消息事件回一条文本喵。"""
            received_events.append(event)
            # 只对消息事件回复喵
            if event.get("post_type") == "message":
                await client.send_group_text(ALLOWED_GROUP, "pong", at_qq=NORMAL_USER)

        # 创建客户端喵
        client = NapCatClient(f"ws://127.0.0.1:{port}", "test-token", 1, on_event)
        # 启动客户端喵
        client_task = asyncio.create_task(client.run())
        try:
            # 等待动作发出喵
            await _wait_until(lambda: len(received_actions) >= 1)
        finally:
            # 停止客户端并回收任务喵
            await client.stop()
            client_task.cancel()
            await asyncio.gather(client_task, return_exceptions=True)

    # 客户端会把带 post_type 的事件都转给业务层，过滤由路由层负责喵
    assert len(received_events) == 2
    # 其中只有一条是消息事件喵
    message_events = [event for event in received_events if event.get("post_type") == "message"]
    assert len(message_events) == 1
    # 心跳事件也应原样转发，说明客户端不做业务判断喵
    assert any(event.get("post_type") == "meta_event" for event in received_events)
    # 动作名应为发送群消息喵
    assert received_actions[0]["action"] == "send_group_msg"
    # 群里收到的文本应为 pong 喵
    assert "pong" in _extract_reply_text(received_actions[0])


@pytest.mark.asyncio
async def test_bot_end_to_end_replies_with_device_info(app_config: AppConfig) -> None:
    """完整链路：群里 @机器人 发 /happy设备，应收到包含主人组设备的回复喵。"""
    # 先往临时库里写一台设备喵
    db.init_db(app_config.server.db_path)
    # 打开连接喵
    seed_connection = db.connect(app_config.server.db_path)
    try:
        # 构造上报对象喵
        payload = ReportPayload.model_validate(
            make_payload(
                device_id="win-alpha-1111",
                reported_at=datetime.now(timezone.utc).isoformat(),
                display_name="测试台式机",
            )
        )
        # 落库喵
        ingest.save_report(seed_connection, payload, datetime.now(timezone.utc))
        # 把这台设备归进「主人」组，happy 系列命令才认喵
        people.save_people(
            app_config.server.db_path,
            [people.PersonGroup(name=happy.HAPPY_GROUP_NAME, devices=("win-alpha-1111",))],
        )
    finally:
        # 关闭连接喵
        seed_connection.close()

    # 记录服务端收到的动作喵
    received_actions: list[dict[str, Any]] = []

    async def fake_napcat(websocket, path: str | None = None) -> None:
        """假 NapCat：推一条 /happy设备 命令，等待机器人回复喵。"""
        # 推送命令事件喵
        await websocket.send(json.dumps(_group_message_event("/happy设备")))
        # 等待机器人发消息喵
        raw_action = await asyncio.wait_for(websocket.recv(), timeout=10)
        # 解析并记录喵
        action_payload = json.loads(raw_action)
        received_actions.append(action_payload)
        # 回包确认喵
        await websocket.send(
            json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": 2}, "echo": action_payload["echo"]})
        )
        # 保持连接，等待测试结束喵
        await asyncio.sleep(0.3)

    # 启动假服务端喵
    async with websockets.serve(fake_napcat, "127.0.0.1", 0) as server:
        # 取出实际端口喵
        port = server.sockets[0].getsockname()[1]
        # 把配置里的机器人地址指向假服务端喵
        bot_config = dataclasses.replace(
            app_config,
            napcat=NapCatSection(
                enabled=True,
                ws_url=f"ws://127.0.0.1:{port}",
                token="test-token",
                reconnect_seconds=1,
                self_qq=BOT_QQ,
            ),
        )
        # 创建机器人任务喵
        runner = BotRunner(bot_config)
        runner_task = asyncio.create_task(runner.run())
        try:
            # 等待机器人发出回复喵
            await _wait_until(lambda: len(received_actions) >= 1)
        finally:
            # 取消任务并回收喵
            runner_task.cancel()
            await asyncio.gather(runner_task, return_exceptions=True)

    # 应收到一条发送动作喵
    assert len(received_actions) == 1
    # 回复文本里应包含设备名喵
    reply_text = _extract_reply_text(received_actions[0])
    assert "测试台式机" in reply_text
    # 喵~注意：主人要求标题不再带「组名 · N 台」统计喵
    assert f"{happy.HAPPY_GROUP_NAME} · " not in reply_text


async def _noop_handler(event: dict[str, Any]) -> None:
    """空事件处理函数，仅用于握手测试喵。"""
    # 什么都不做喵
    return None


def test_build_connect_url_encodes_token() -> None:
    """口令里的特殊字符必须被转义，否则会被当成参数分隔符喵。"""
    # 构造带特殊字符的口令喵
    client = NapCatClient("ws://127.0.0.1:7999", "a+b&c=d", 1, _noop_handler)
    # 断言转义结果喵
    assert client._build_connect_url() == "ws://127.0.0.1:7999?access_token=a%2Bb%26c%3Dd"


def test_build_connect_url_keeps_existing_query() -> None:
    """地址里已有查询参数时应使用 & 连接喵。"""
    # 构造带查询参数的地址喵
    client = NapCatClient("ws://127.0.0.1:7999?foo=1", "token", 1, _noop_handler)
    # 断言拼接结果喵
    assert client._build_connect_url() == "ws://127.0.0.1:7999?foo=1&access_token=token"


def test_build_connect_url_without_token() -> None:
    """口令为空时不应拼出空的 access_token 参数喵。"""
    # 构造空口令客户端喵
    client = NapCatClient("ws://127.0.0.1:7999", "", 1, _noop_handler)
    # 地址应保持原样喵
    assert client._build_connect_url() == "ws://127.0.0.1:7999"


@pytest.mark.asyncio
async def test_client_passes_access_token_in_handshake() -> None:
    """握手请求里必须带上 access_token，否则真实 NapCat 会拒绝连接喵。"""
    # 记录服务端看到的请求路径喵
    captured_paths: list[str] = []

    async def fake_napcat(websocket, path: str | None = None) -> None:
        """假 NapCat：记录握手路径后保持连接喵。"""
        # 兼容新旧两套 websockets API 取路径喵
        request_path = getattr(websocket, "path", None)
        if request_path is None:
            request = getattr(websocket, "request", None)
            request_path = getattr(request, "path", "") if request is not None else ""
        # 记录路径喵
        captured_paths.append(str(request_path))
        # 保持连接，等待测试结束喵
        await asyncio.sleep(0.5)

    # 启动假服务端喵
    async with websockets.serve(fake_napcat, "127.0.0.1", 0) as server:
        # 取出实际端口喵
        port = server.sockets[0].getsockname()[1]
        # 创建客户端并连接喵
        client = NapCatClient(f"ws://127.0.0.1:{port}", "secret-token-123", 1, _noop_handler)
        client_task = asyncio.create_task(client.run())
        try:
            # 等待握手发生喵
            await _wait_until(lambda: len(captured_paths) >= 1)
        finally:
            # 停止客户端并回收任务喵
            await client.stop()
            client_task.cancel()
            await asyncio.gather(client_task, return_exceptions=True)

    # 断言握手路径里带上了口令喵
    assert len(captured_paths) == 1
    assert "access_token=secret-token-123" in captured_paths[0]


class _StubChannel:
    """记录发送内容的假通道，用来验证 runner 的分发逻辑喵。"""

    def __init__(self, name: str) -> None:
        # 通道名喵
        self.name = name
        # 已发送的文本喵
        self.texts: list[tuple[str, str]] = []
        # 已发送的图片喵
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


@pytest.mark.asyncio
async def test_runner_dispatches_to_matching_channel(app_config: AppConfig) -> None:
    """官方通道的消息必须走官方通道回复，不能串到 NapCat 喵。"""
    # 打开官方通道喵
    config = dataclasses.replace(
        app_config,
        qqbot=QQBotSection(enabled=True, app_id="app-id", app_secret="app-secret"),
        acl=dataclasses.replace(app_config.acl, whitelist_group_openids=("GROUP_OPENID_A",)),
    )
    # 建机器人喵
    runner = BotRunner(config)
    # 用假通道替换真实通道，避免测试发网络请求喵
    napcat_stub = _StubChannel("napcat")
    qqbot_stub = _StubChannel("qqbot")
    runner._channels = {"napcat": napcat_stub, "qqbot": qqbot_stub}  # noqa: SLF001
    # 造一条官方群 @ 消息喵
    message = NormalizedMessage(
        channel="qqbot",
        group_key="GROUP_OPENID_A",
        user_key="MEMBER_OPENID_X",
        text="/happy帮助",
        mentioned=True,
    )
    # 交给 runner 处理喵
    await runner._handle_message(message)  # noqa: SLF001
    # 官方通道应收到回复，NapCat 一条都不该收到喵
    assert len(qqbot_stub.texts) == 1
    assert qqbot_stub.texts[0][0] == "GROUP_OPENID_A"
    assert "/happy帮助" in qqbot_stub.texts[0][1]
    assert napcat_stub.texts == []
    # 通道状态也要能分开看喵
    assert [item["name"] for item in runner.channel_status()] == ["napcat", "qqbot"]
