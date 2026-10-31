"""OneBot 11 正向 WebSocket 客户端。

协议要点：
- 我们作为客户端连接 NapCat 的 websocketServers；
- 鉴权用 URL 查询参数 access_token，避免不同 websockets 版本对 header 参数名支持不一致；
- 发消息属于"动作调用"，需要带 echo 字段，NapCat 用同一个 echo 回包；
- 事件处理放到独立队列里串行执行，保证"接收循环"永远不被业务逻辑阻塞喵。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed

from ..config import AppConfig
from .channel import CHANNEL_NAPCAT, SCOPE_GROUP, NormalizedMessage, from_onebot_event

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot")

# 事件处理函数的类型：接收一个事件字典，异步返回喵
EventHandler = Callable[[dict[str, Any]], Awaitable[None]]

# 事件队列最大长度，超出说明消费端卡住了喵
MAX_EVENT_QUEUE_SIZE = 200

# 单条动作调用等待回包的最长秒数喵
ACTION_TIMEOUT_SECONDS = 10.0

# 单条 WebSocket 消息允许的最大字节数，防止异常大包撑爆内存喵
MAX_FRAME_BYTES = 8 * 1024 * 1024


class NapCatClient:
    """负责连接、重连、收事件、发动作的客户端喵。"""

    def __init__(
        self,
        ws_url: str,
        access_token: str,
        reconnect_seconds: int,
        event_handler: EventHandler,
    ) -> None:
        # 目标 WebSocket 地址喵
        self._ws_url = ws_url
        # 访问口令喵
        self._access_token = access_token
        # 断线重连间隔秒数喵
        self._reconnect_seconds = max(1, reconnect_seconds)
        # 业务事件处理函数喵
        self._event_handler = event_handler
        # 当前连接对象，未连接时为 None 喵
        self._connection: Any = None
        # 是否已连上 NapCat，供看板显示机器人状态喵
        self.connected = False
        # 等待回包的 future 表，键是 echo 喵
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # 自增的 echo 序号喵
        self._echo_counter = 0
        # 停止标志，用于优雅退出喵
        self._stopping = False
        # 事件队列，串行消费喵
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_EVENT_QUEUE_SIZE)

    def _build_connect_url(self) -> str:
        """拼接带 access_token 的连接地址喵。"""
        # 喵~防御：口令为空时不拼参数，避免出现 access_token= 的空值喵
        if not self._access_token:
            return self._ws_url
        # 地址里已经有查询参数时用 & 连接喵
        separator = "&" if "?" in self._ws_url else "?"
        # 喵~防御：口令里可能出现 + & = 这类特殊字符，必须转义，否则会被当成参数分隔符喵
        encoded_token = quote(self._access_token, safe="")
        return f"{self._ws_url}{separator}access_token={encoded_token}"

    async def run(self) -> None:
        """主循环：连接、收消息、断线后按间隔重连，直到被取消喵。"""
        # 启动事件消费任务喵
        worker_task = asyncio.create_task(self._consume_events())
        try:
            # 喵~防御：只要没收到停止指令就持续重连，保证 NapCat 重启后能自动恢复喵
            while not self._stopping:
                try:
                    # 尝试建立一次连接并进入收包循环喵
                    await self._connect_once()
                except asyncio.CancelledError:
                    # 取消信号必须原样抛出，否则无法优雅退出喵
                    raise
                except (OSError, ConnectionClosed, asyncio.TimeoutError) as connection_error:
                    # 喵~防御：网络类错误只记录日志并等待重连，不让整个进程崩掉喵
                    LOGGER.warning("与 NapCat 的连接中断：%s", connection_error)
                except Exception as unexpected_error:  # noqa: BLE001
                    # 喵~防御：兜底捕获未知异常，记录完整堆栈便于排查喵
                    LOGGER.exception("NapCat 客户端发生未预期异常：%s", unexpected_error)
                # 喵~防御：停止标志已置位时不再等待重连间隔喵
                if self._stopping:
                    break
                # 等待重连间隔喵
                await asyncio.sleep(self._reconnect_seconds)
        finally:
            # 退出前取消消费任务喵
            worker_task.cancel()
            # 等待任务真正结束，忽略取消异常喵
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        """请求停止客户端喵。"""
        # 置位停止标志，主循环会在下一轮检查时退出喵
        self._stopping = True
        # 主动关闭连接，让收包循环立即结束喵
        if self._connection is not None:
            await self._connection.close()

    async def _connect_once(self) -> None:
        """建立一次连接并持续接收消息，连接结束时返回喵。"""
        # 拼接鉴权后的地址喵
        connect_url = self._build_connect_url()
        # 建立连接，设置心跳与超时，避免半开连接一直挂着喵
        async with websockets.connect(
            connect_url,
            max_size=MAX_FRAME_BYTES,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as connection:
            # 保存连接引用，供发动作使用喵
            self._connection = connection
            # 标记已连接，看板据此显示状态喵
            self.connected = True
            # 记录连接成功，方便主人看日志确认喵
            LOGGER.info("已连接 NapCat：%s", self._ws_url)
            try:
                # 持续接收消息喵
                async for raw_message in connection:
                    # 解析并分发喵
                    await self._dispatch(raw_message)
            finally:
                # 连接断开后清空引用喵
                self._connection = None
                # 标记断开，看板据此显示状态喵
                self.connected = False
                # 喵~防御：连接断了以后未完成的动作调用永远不会回包，必须主动失败掉喵
                self._fail_pending_actions(ConnectionError("与 NapCat 的连接已断开"))
                # 记录断开日志喵
                LOGGER.info("NapCat 连接已关闭")

    def _fail_pending_actions(self, error: Exception) -> None:
        """把所有等待回包的动作标记为失败喵。"""
        # 逐个设置异常喵
        for echo_key, future in list(self._pending_actions.items()):
            # 喵~防御：已经完成的 future 不再重复设置异常喵
            if not future.done():
                future.set_exception(error)
            # 从表中移除喵
            self._pending_actions.pop(echo_key, None)

    async def _dispatch(self, raw_message: Any) -> None:
        """解析一条原始消息，区分"动作回包"与"事件推送"喵。"""
        # 喵~防御：二进制帧无法解析，直接忽略喵
        if isinstance(raw_message, (bytes, bytearray)):
            LOGGER.debug("收到二进制帧，已忽略")
            return
        try:
            # 解析 JSON 喵
            payload = json.loads(raw_message)
        except json.JSONDecodeError as json_error:
            # 喵~防御：协议异常时只记日志，不中断连接喵
            LOGGER.warning("无法解析 NapCat 消息：%s", json_error)
            return
        # 喵~防御：顶层必须是字典喵
        if not isinstance(payload, dict):
            LOGGER.warning("NapCat 消息顶层不是对象，已忽略")
            return
        # 带 echo 的是动作回包喵
        echo_value = payload.get("echo")
        if echo_value is not None:
            # 找到对应的 future 并唤醒喵
            pending_future = self._pending_actions.pop(str(echo_value), None)
            if pending_future is not None and not pending_future.done():
                pending_future.set_result(payload)
            return
        # 没有 post_type 的不是事件喵
        if "post_type" not in payload:
            return
        # 喵~防御：队列满时丢弃事件并告警，避免无限堆积吃光内存喵
        try:
            self._event_queue.put_nowait(payload)
        except asyncio.QueueFull:
            LOGGER.warning("事件队列已满，丢弃一条事件：%s", payload.get("post_type"))

    async def _consume_events(self) -> None:
        """串行消费事件队列，保证命令按到达顺序处理喵。"""
        while True:
            # 取出一个事件喵
            event = await self._event_queue.get()
            try:
                # 交给业务处理喵
                await self._event_handler(event)
            except asyncio.CancelledError:
                # 取消信号必须原样抛出喵
                raise
            except Exception as handler_error:  # noqa: BLE001
                # 喵~防御：单条事件处理失败不能影响后续事件喵
                LOGGER.exception("处理事件失败：%s", handler_error)
            finally:
                # 标记该事件已处理完喵
                self._event_queue.task_done()

    async def call_action(self, action: str, params: dict[str, Any], timeout: float = ACTION_TIMEOUT_SECONDS) -> dict[str, Any]:
        """调用 OneBot 动作并等待回包喵。

        输入：动作名、参数字典、超时秒数。
        输出：NapCat 的响应字典（含 status/retcode/data）。
        边界：未连接、超时、连接断开都会抛异常，由调用方决定如何兜底喵。
        """
        # 喵~防御：没连接时直接失败，避免调用方一直等喵
        if self._connection is None:
            raise ConnectionError("尚未连接到 NapCat，动作无法发送")
        # 生成自增 echo 喵
        self._echo_counter += 1
        echo_key = str(self._echo_counter)
        # 创建等待回包的 future 喵
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        # 登记到等待表喵
        self._pending_actions[echo_key] = future
        # 组装请求体喵
        request_payload = {"action": action, "params": params, "echo": echo_key}
        try:
            # 发送请求喵
            await self._connection.send(json.dumps(request_payload, ensure_ascii=False))
            # 等待回包喵
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            # 喵~防御：超时后必须清理登记，否则会一直占着内存喵
            self._pending_actions.pop(echo_key, None)
            raise
        finally:
            # 无论成功失败都确保登记被清掉喵
            self._pending_actions.pop(echo_key, None)

    async def send_group_text(self, group_id: int, text: str, at_qq: int | None = None) -> None:
        """向群聊发送纯文本消息，可选地先 @ 某个人喵。

        输入：群号、文本、可选被 @ 的 QQ 号。
        输出：无返回值。
        边界：文本为空时不发送；超长文本会被截断并追加提示喵。
        """
        # 喵~防御：空文本不发送，避免 QQ 侧报错喵
        if not text or not text.strip():
            return
        # 组装消息段喵
        message_segments: list[dict[str, Any]] = []
        # 需要 @ 时先插入 at 段喵
        if at_qq is not None:
            message_segments.append({"type": "at", "data": {"qq": str(at_qq)}})
            # 追加一个空格，避免 @ 与正文黏在一起喵
            message_segments.append({"type": "text", "data": {"text": " "}})
        # 喵~防御：QQ 单条消息有长度上限，超长时截断并提示喵
        safe_text = text
        if len(safe_text) > 3500:
            safe_text = safe_text[:3400] + "\n……内容过长已截断，请用更精确的页码查看。"
        # 追加正文段喵
        message_segments.append({"type": "text", "data": {"text": safe_text}})
        # 调用发送动作喵
        response = await self.call_action(
            "send_group_msg",
            {"group_id": group_id, "message": message_segments},
        )
        # 喵~防御：NapCat 返回失败时记录日志，便于排查 token 或权限问题喵
        if response.get("status") != "ok":
            LOGGER.warning("发送群消息失败：%s", response)

    async def send_group_image(self, group_id: int, image_bytes: bytes, caption: str | None = None) -> None:
        """向群聊发送图片，图片以 base64 内联传输喵。

        输入：群号、PNG 字节流、可选图片说明文字。
        输出：无返回值。
        边界：图片为空时直接返回；NapCat 拒绝时记录日志喵。
        """
        # 喵~防御：空图片不发送，避免 QQ 侧报错喵
        if not image_bytes:
            return
        # 编码成 base64 字符串，NapCat 支持 base64:// 前缀喵
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        # 组装图片消息段喵
        message_segments: list[dict[str, Any]] = [
            {"type": "image", "data": {"file": f"base64://{encoded_image}"}}
        ]
        # 有说明文字时追加文本段喵
        if caption:
            # 换行后再放说明，避免与图片挤在一起喵
            message_segments.append({"type": "text", "data": {"text": f"\n{caption}"}})
        # 调用发送动作喵
        response = await self.call_action(
            "send_group_msg",
            {"group_id": group_id, "message": message_segments},
        )
        # 喵~防御：失败时记录日志便于排查喵
        if response.get("status") != "ok":
            LOGGER.warning("发送群图片失败：%s", response)


class NapCatChannel:
    """把 OneBot 客户端包成统一通道接口，业务层只认归一化消息喵。"""

    # 通道名喵
    name = CHANNEL_NAPCAT

    def __init__(self, config: AppConfig, event_handler: "EventHandler") -> None:
        # 配置引用，取 self_qq 判断是否 @ 了机器人喵
        self._config = config
        # 业务层处理函数喵
        self._handler = event_handler
        # 底层 OneBot 客户端喵
        self._client = NapCatClient(
            ws_url=config.napcat.ws_url,
            access_token=config.napcat.token,
            reconnect_seconds=config.napcat.reconnect_seconds,
            event_handler=self._on_event,
        )

    async def _on_event(self, event: dict[str, Any]) -> None:
        """把 OneBot 事件归一化后交给业务层喵。"""
        # 转成协议无关结构喵
        normalized = from_onebot_event(event, self._config.napcat.self_qq)
        # 喵~防御：非群消息事件（心跳、通知）直接丢弃喵
        if normalized.message is None:
            return
        # 交给业务层喵
        await self._handler(normalized.message)

    async def run(self) -> None:
        """启动客户端主循环喵。"""
        # 直接转发给底层客户端喵
        await self._client.run()

    async def stop(self) -> None:
        """请求停止客户端喵。"""
        # 直接转发给底层客户端喵
        await self._client.stop()

    def is_connected(self) -> bool:
        """是否已连上 NapCat 喵。"""
        # 直接读客户端的连接标记喵
        return self._client.connected

    async def send_text(
        self,
        group_key: str,
        text: str,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        mention_user_key: str | None = None,
    ) -> None:
        """发群文本，能 @ 就把提问的人 @ 上喵。"""
        # 喵~防御：群号必须是整数，异常时抛给上层记录日志喵
        group_id = int(group_key)
        # 需要 @ 时把字符串转回整数喵
        at_qq = int(mention_user_key) if mention_user_key else None
        # 调用底层发送喵
        await self._client.send_group_text(group_id, text, at_qq=at_qq)

    async def send_image(
        self,
        group_key: str,
        image_bytes: bytes,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        caption: str | None = None,
    ) -> None:
        """发群图片，OneBot 支持 base64 内联喵。"""
        # 喵~防御：群号必须是整数喵
        group_id = int(group_key)
        # 调用底层发送喵
        await self._client.send_group_image(group_id, image_bytes, caption=caption)
