"""官方 QQ Bot（api.bot.qq.com）通道实现喵。

协议要点（详见 docs/qqbot.md）：
- 先用 AppID + AppSecret 换 access_token，再取 wss 网关地址；
- 连上先收 op=10 Hello，然后发 op=2 Identify（断线优先 op=6 Resume）；
- 心跳必须应用层自己发 op=1，漏发会被服务端踢下线；
- 发群消息走 POST /v2/groups/{group_openid}/messages，被动回复必须带 msg_id；
- 图片必须先上传拿 file_info，再用 msg_type=7 发；
- 身份是 openid 字符串，不是 QQ 号，跨 Bot 不通用喵。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import OrderedDict, deque
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from ..config import AppConfig
from .channel import (
    CHANNEL_QQBOT,
    COMMAND_PREFIXES,
    SCOPE_GROUP,
    SCOPE_PRIVATE,
    ChannelError,
    NormalizedMessage,
    from_qqbot_event,
)

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot")

# 官方接口根地址，沙箱环境可换成 sandbox.api.sgroup.qq.com 喵
DEFAULT_API_BASE = "https://api.bot.qq.com"

# 群聊单条文本上限，超了官方会回 40054007 喵
MAX_TEXT_LENGTH = 1800

# 事件队列长度，超出说明消费端卡住了喵
MAX_EVENT_QUEUE_SIZE = 200

# 单帧最大字节数喵
MAX_FRAME_BYTES = 8 * 1024 * 1024

# 单次 HTTP 请求超时秒数喵
DEFAULT_TIMEOUT_SECONDS = 10.0

# 主动消息本地限流：单会话每分钟最多发这么多条喵
ACTIVE_MESSAGES_PER_MINUTE = 20

# 主动消息限流窗口秒数喵
ACTIVE_WINDOW_SECONDS = 60.0

# 换票失败后的退避秒数，避免把开放平台刷成 429 喵
TOKEN_FAILURE_BACKOFF_SECONDS = 60.0

# 服务端没下发心跳周期时的兜底值（毫秒）喵
DEFAULT_HEARTBEAT_MS = 45000

# 这些关闭码表示会话不可恢复，下次要重新 Identify 喵
SESSION_INVALID_CODES = frozenset({4006, 4007})

# 这些关闭码表示可以继续 Resume 喵
RESUMABLE_CODES = frozenset({4008, 4009})

# 这些关闭码说明鉴权或权限不对，重连也没用，要长时间退避喵
FATAL_CODES = frozenset({4010, 4011, 4013, 4014, 4914, 4915})

# 事件处理函数：接收一条归一化消息喵
MessageHandler = Callable[[NormalizedMessage], Awaitable[None]]


class QQBotError(ChannelError):
    """官方接口返回的业务错误喵。"""

    def __init__(self, code: int, message: str, scope: str = "api") -> None:
        # 平台错误码喵
        self.code = code
        # 平台给的描述，仅用于日志，不用于分支判断喵
        self.message = message
        # 出错环节：token / http / business 喵
        self.scope = scope
        # 拼一条可读信息喵
        super().__init__(f"{scope} 调用失败：code={code} message={message}")


class ReplyCounter:
    """同一 msg_id 的回复序号，避免 40054005 去重失败喵。"""

    def __init__(self, capacity: int = 2048) -> None:
        # 用有序字典做 LRU，防止 msg_id 无限堆积喵
        self._seq: OrderedDict[str, int] = OrderedDict()
        # 最多记住多少条消息喵
        self._capacity = capacity

    def next(self, msg_id: str) -> int:
        """取下一个回复序号，同一 msg_id 从 1 开始递增喵。"""
        # 喵~防御：没有凭据时按第一条处理喵
        if not msg_id:
            return 1
        # 递增并记录喵
        current = self._seq.pop(msg_id, 0) + 1
        self._seq[msg_id] = current
        # 超出容量时丢掉最老的记录喵
        while len(self._seq) > self._capacity:
            self._seq.popitem(last=False)
        return current


class SeenMessages:
    """按消息 ID 去重，防止同一事件从两个事件类型各回一次喵。"""

    def __init__(self, capacity: int = 2048) -> None:
        # 有序字典当 LRU 用喵
        self._seen: OrderedDict[str, None] = OrderedDict()
        # 最多记住多少条消息喵
        self._capacity = capacity

    def first_time(self, msg_id: str) -> bool:
        """第一次见到返回 True，重复返回 False 喵。"""
        # 喵~防御：没有 ID 时无法去重，一律放行喵
        if not msg_id:
            return True
        # 见过就返回 False 喵
        if msg_id in self._seen:
            return False
        # 记录并控制容量喵
        self._seen[msg_id] = None
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return True


class ActiveMessageLimiter:
    """主动消息本地限流，避免触发平台频控喵。"""

    def __init__(self, limit: int = ACTIVE_MESSAGES_PER_MINUTE, window_seconds: float = ACTIVE_WINDOW_SECONDS) -> None:
        # 每个会话最近发送的时间戳喵
        self._history: dict[str, deque[float]] = {}
        # 窗口内允许的条数喵
        self._limit = max(1, limit)
        # 窗口长度秒数喵
        self._window = max(1.0, window_seconds)

    def acquire(self, key: str) -> None:
        """登记一次主动消息，超限时抛 ChannelError 喵。"""
        # 当前时间喵
        now = time.monotonic()
        # 取出该会话的历史喵
        history = self._history.setdefault(key, deque())
        # 丢掉窗口外的旧记录喵
        while history and now - history[0] > self._window:
            history.popleft()
        # 喵~防御：超过本地额度就不发，交给调用方记录日志喵
        if len(history) >= self._limit:
            raise ChannelError(f"主动消息超出本地限流（{self._limit} 条/分钟）")
        # 记录本次发送喵
        history.append(now)


class QQBotApi:
    """官方 HTTP API 封装：换票、取网关、发消息、传文件喵。"""

    def __init__(
        self,
        api_base: str,
        app_id: str,
        app_secret: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        refresh_margin_seconds: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # 接口根地址，去掉结尾斜杠避免拼出双斜杠喵
        self._api_base = api_base.rstrip("/") or DEFAULT_API_BASE
        # 开放平台 AppID 喵
        self._app_id = app_id
        # 开放平台 AppSecret 喵
        self._app_secret = app_secret
        # 请求超时秒数喵
        self._timeout = timeout_seconds
        # 提前刷新窗口秒数喵
        self._margin = max(0, refresh_margin_seconds)
        # 外部注入的 httpx 客户端，测试用 MockTransport 喵
        self._client = client
        # 是否由自己创建的客户端，退出时要负责关闭喵
        self._owns_client = client is None
        # 缓存的 access_token 喵
        self._token: str | None = None
        # token 到期时刻（monotonic）喵
        self._token_expire_at = 0.0

    def _ensure_client(self) -> httpx.AsyncClient:
        """懒创建 httpx 客户端喵。"""
        # 喵~防御：第一次调用时才建连接池，避免导入期就建喵
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """关闭自建的 HTTP 客户端喵。"""
        # 只关自己建的，外部注入的交给调用方喵
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def access_token(self) -> str:
        """取 access_token，命中缓存时不重复请求喵。

        输入：无（凭据来自构造参数）。
        输出：可用的 access_token。
        边界：平台失败时 HTTP 仍是 200，必须看 body 里的 code 喵。
        """
        # 当前时间喵
        now = time.monotonic()
        # 喵~防御：缓存还在有效期内就直接用喵
        if self._token and now < self._token_expire_at:
            return self._token
        # 喵~防御：缺凭据时提前失败，别去平台上白跑一趟喵
        if not self._app_id or not self._app_secret:
            raise QQBotError(100007, "qqbot.app_id / app_secret 未配置", scope="token")
        # 请求换票接口喵
        payload = await self._request(
            "POST",
            "/app/getAppAccessToken",
            json_body={"appId": self._app_id, "clientSecret": self._app_secret},
            auth=False,
        )
        # 取出 token 与有效期喵
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in") or 0)
        # 喵~防御：没有 token 说明凭据不对或被封禁喵
        if not token:
            raise QQBotError(int(payload.get("code") or -1), str(payload.get("message") or ""), scope="token")
        # 缓存并算好提前刷新的时刻喵
        self._token = str(token)
        self._token_expire_at = now + max(0, expires_in - self._margin)
        # 记录刷新日志方便排查喵
        LOGGER.info("QQ Bot access_token 已刷新，有效期 %s 秒", expires_in)
        return self._token

    async def gateway_url(self) -> str:
        """取 WebSocket 网关地址喵。"""
        # 调网关接口喵
        payload = await self._request("GET", "/gateway/bot")
        # 取 wss 地址喵
        url = payload.get("url")
        # 喵~防御：没有地址说明鉴权或权限不对喵
        if not url:
            raise QQBotError(int(payload.get("code") or -1), "网关接口没有返回 url", scope="gateway")
        return str(url)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        """发一次 HTTP 请求并统一处理错误喵。

        输入：方法、路径、请求体、是否需要鉴权。
        输出：解析后的 JSON 字典。
        边界：HTTP 4xx/5xx 与 body 里的 err_code 都会抛 QQBotError 喵。
        """
        # 组装请求头喵
        headers: dict[str, str] = {}
        # 需要鉴权时先拿 token 喵
        if auth:
            headers["Authorization"] = f"QQBot {await self.access_token()}"
        # 取客户端喵
        client = self._ensure_client()
        try:
            # 发请求喵
            response = await client.request(
                method,
                f"{self._api_base}{path}",
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as transport_error:
            # 喵~防御：网络类错误统一转成 ChannelError，方便上层退回文本喵
            raise ChannelError(f"请求 {path} 失败：{transport_error}") from transport_error
        # 解析响应体，空包体按空字典处理喵
        try:
            payload = response.json() if response.content else {}
        except ValueError as json_error:
            # 喵~防御：平台偶尔返回 HTML，不能直接崩喵
            raise QQBotError(response.status_code, f"响应不是 JSON：{json_error}", scope="http") from json_error
        # 喵~防御：顶层必须是对象喵
        if not isinstance(payload, dict):
            raise QQBotError(response.status_code, "响应顶层不是对象", scope="http")
        # HTTP 层错误喵
        if response.status_code >= 400:
            raise QQBotError(
                int(payload.get("code") or payload.get("err_code") or response.status_code),
                str(payload.get("message") or ""),
                scope="http",
            )
        # 业务层错误喵
        error_code = payload.get("err_code")
        if error_code:
            raise QQBotError(int(error_code), str(payload.get("message") or ""), scope="business")
        return payload

    def _message_path(self, scope: str, target: str) -> str:
        """按会话类型拼发消息路径喵。"""
        # 单聊与群聊接口不通用，必须分开喵
        if scope == SCOPE_PRIVATE:
            return f"/v2/users/{quote(target, safe='')}/messages"
        return f"/v2/groups/{quote(target, safe='')}/messages"

    def _files_path(self, scope: str, target: str) -> str:
        """按会话类型拼上传路径喵。"""
        # 单聊与群聊上传同样不通用喵
        if scope == SCOPE_PRIVATE:
            return f"/v2/users/{quote(target, safe='')}/files"
        return f"/v2/groups/{quote(target, safe='')}/files"

    async def send_text(
        self,
        scope: str,
        target: str,
        content: str,
        *,
        msg_id: str | None = None,
        msg_seq: int = 1,
    ) -> dict[str, Any]:
        """发文本消息；带 msg_id 时算被动回复喵。"""
        # 组装请求体喵
        body: dict[str, Any] = {"msg_type": 0, "content": content}
        # 被动回复必须带凭据与序号喵
        if msg_id:
            body["msg_id"] = msg_id
            body["msg_seq"] = msg_seq
        # 发请求喵
        return await self._request("POST", self._message_path(scope, target), json_body=body)

    async def upload_image(self, scope: str, target: str, image_bytes: bytes, file_name: str = "usage.png") -> str:
        """上传图片并返回 file_info 喵。

        输入：会话类型、目标 openid、PNG 字节、文件名。
        输出：file_info 字符串，供 msg_type=7 使用。
        边界：file_info 有 ttl，过期必须重传喵。
        """
        # 官方只收 JSON，二进制要 base64 后放 file_data 喵
        body = {
            "file_type": 1,
            "file_data": base64.b64encode(image_bytes).decode("ascii"),
            "srv_send_msg": False,
            "file_name": file_name,
        }
        # 调上传接口喵
        payload = await self._request("POST", self._files_path(scope, target), json_body=body)
        # 取 file_info 喵
        file_info = payload.get("file_info")
        # 喵~防御：没拿到凭据就无法发图喵
        if not file_info:
            raise QQBotError(int(payload.get("code") or -1), "上传接口没有返回 file_info", scope="upload")
        return str(file_info)

    async def send_image(
        self,
        scope: str,
        target: str,
        file_info: str,
        *,
        msg_id: str | None = None,
        msg_seq: int = 1,
    ) -> dict[str, Any]:
        """发富媒体消息（msg_type=7）喵。"""
        # 组装请求体喵
        body: dict[str, Any] = {"msg_type": 7, "media": {"file_info": file_info}}
        # 被动回复必须带凭据与序号喵
        if msg_id:
            body["msg_id"] = msg_id
            body["msg_seq"] = msg_seq
        # 发请求喵
        return await self._request("POST", self._message_path(scope, target), json_body=body)


def _truncate(text: str) -> str:
    """按官方长度上限截断文本喵。"""
    # 喵~防御：没超长就原样返回喵
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    # 截断并补一句提示，避免用户以为数据丢了喵
    return text[: MAX_TEXT_LENGTH - 30] + "\n……内容过长已截断。"


def _default_connector(url: str) -> Any:
    """默认的 WebSocket 连接工厂喵。"""
    # 关掉库自带 ping，心跳统一走 op=1，避免关闭码混淆喵
    return websockets.connect(url, max_size=MAX_FRAME_BYTES, open_timeout=10, ping_interval=None)


class QQBotClient:
    """官方网关长连接客户端：握手、心跳、断线恢复、事件投递喵。"""

    def __init__(
        self,
        config: AppConfig,
        api: QQBotApi,
        event_handler: MessageHandler,
        connector: Callable[[str], Any] | None = None,
    ) -> None:
        # 配置引用，取 intents 与免 @ 群喵
        self._config = config
        # HTTP 封装喵
        self._api = api
        # 业务处理函数喵
        self._handler = event_handler
        # 连接工厂，测试可替换成假网关喵
        self._connector = connector or _default_connector
        # 是否已收到 READY/RESUMED，供看板显示喵
        self.connected = False
        # 停止标志喵
        self._stopping = False
        # 当前连接喵
        self._ws: Any = None
        # 会话 ID，Resume 时要用喵
        self._session_id: str | None = None
        # 最新事件序号，心跳与 Resume 都要带喵
        self._seq: int | None = None
        # 机器人自身 ID，全量模式探测 @ 用喵
        self._bot_id: str | None = None
        # 事件队列，串行消费喵
        self._queue: asyncio.Queue[NormalizedMessage] = asyncio.Queue(maxsize=MAX_EVENT_QUEUE_SIZE)
        # 消息去重喵
        self._seen = SeenMessages()
        # 心跳任务喵
        self._heartbeat_task: asyncio.Task[None] | None = None

    def is_connected(self) -> bool:
        """当前是否已就绪喵。"""
        # 直接返回标记喵
        return self.connected

    async def run(self) -> None:
        """主循环：连网关、收事件、断线重连，直到被取消喵。"""
        # 启动事件消费任务喵
        worker_task = asyncio.create_task(self._consume_events(), name="qqbot-worker")
        try:
            # 喵~防御：只要没收到停止指令就持续重连喵
            while not self._stopping:
                try:
                    # 尝试建立一次会话喵
                    await self._session_once()
                except asyncio.CancelledError:
                    # 取消信号必须原样抛出喵
                    raise
                except QQBotError as api_error:
                    # 喵~防御：换票失败多半是凭据问题，长退避避免把平台刷成 429 喵
                    LOGGER.warning("QQ Bot 接口调用失败：%s", api_error)
                    if api_error.scope == "token":
                        await self._sleep(TOKEN_FAILURE_BACKOFF_SECONDS)
                        continue
                except (OSError, ConnectionClosed, asyncio.TimeoutError, ChannelError) as connection_error:
                    # 喵~防御：网络类错误只记日志并等待重连喵
                    LOGGER.warning("QQ Bot 连接中断：%s", connection_error)
                except Exception as unexpected_error:  # noqa: BLE001
                    # 喵~防御：兜底捕获未知异常，记录堆栈便于排查喵
                    LOGGER.exception("QQ Bot 客户端发生未预期异常：%s", unexpected_error)
                # 停止时不再等待喵
                if self._stopping:
                    break
                # 等待重连间隔喵
                await self._sleep(max(1, self._config.qqbot.reconnect_seconds))
        finally:
            # 退出前取消消费任务喵
            worker_task.cancel()
            # 等待任务真正结束喵
            await asyncio.gather(worker_task, return_exceptions=True)

    async def _sleep(self, seconds: float) -> None:
        """可被停止打断的等待喵。"""
        # 分片等待，保证 stop() 能及时生效喵
        await asyncio.sleep(seconds)

    async def stop(self) -> None:
        """请求停止客户端喵。"""
        # 置位停止标志喵
        self._stopping = True
        # 关闭心跳任务喵
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        # 主动关闭连接，让收包循环立刻结束喵
        if self._ws is not None:
            await self._ws.close()

    async def _session_once(self) -> None:
        """建立一次网关会话并持续收包喵。"""
        # 取网关地址喵
        url = await self._api.gateway_url()
        # 建立连接喵
        async with self._connector(url) as ws:
            # 保存连接引用喵
            self._ws = ws
            # 第一条必须是 op=10 Hello 喵
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            hello = json.loads(hello_raw)
            # 取心跳周期，单位毫秒喵
            interval_ms = int((hello.get("d") or {}).get("heartbeat_interval") or DEFAULT_HEARTBEAT_MS)
            # 发起 Identify 或 Resume 喵
            await self._handshake(ws)
            # 启动心跳任务喵
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws, interval_ms), name="qqbot-heartbeat")
            try:
                # 持续接收事件喵
                async for raw_message in ws:
                    await self._dispatch(raw_message)
            finally:
                # 连接结束，回收心跳任务喵
                heartbeat_task = self._heartbeat_task
                self._heartbeat_task = None
                # 喵~防御：任务可能已经自己退出了，取消前先判空喵
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                # 清空引用并标记断开喵
                self._ws = None
                self.connected = False
                LOGGER.info("QQ Bot 网关连接已关闭")

    async def _handshake(self, ws: Any) -> None:
        """按是否有会话决定 Identify 还是 Resume 喵。"""
        # 取 token 喵
        token = await self._api.access_token()
        # 有会话且有序号时优先 Resume，能补发漏掉的事件喵
        if self._session_id and self._seq is not None:
            await ws.send(
                json.dumps({"op": 6, "d": {"token": f"QQBot {token}", "session_id": self._session_id, "seq": self._seq}})
            )
            LOGGER.info("QQ Bot 已发起 Resume（seq=%s）", self._seq)
            return
        # 没有会话就重新 Identify 喵
        await ws.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": int(self._config.qqbot.intents),
                        "shard": [0, 1],
                        "properties": {"$os": "windows", "$browser": "device-hub", "$device": "device-hub"},
                    },
                }
            )
        )
        LOGGER.info("QQ Bot 已发起 Identify（intents=%s）", self._config.qqbot.intents)

    async def _heartbeat_loop(self, ws: Any, interval_ms: int) -> None:
        """按服务端给的周期发 op=1 心跳喵。"""
        # 周期留一点余量，避免刚好卡在边界上喵
        interval = max(1.0, interval_ms / 1000.0 - max(0, self._config.qqbot.heartbeat_slack_seconds))
        while True:
            # 先等一个周期喵
            await asyncio.sleep(interval)
            try:
                # 带最新序号发心跳喵
                await ws.send(json.dumps({"op": 1, "d": self._seq}))
            except (ConnectionClosed, OSError):
                # 喵~防御：连接已经没了就直接退出，重连由主循环负责喵
                return

    async def _dispatch(self, raw_message: Any) -> None:
        """解析一条网关消息并按 op 分发喵。"""
        # 二进制帧按 UTF-8 解码喵
        if isinstance(raw_message, (bytes, bytearray)):
            raw_message = raw_message.decode("utf-8", errors="ignore")
        try:
            # 解析 JSON 喵
            payload = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError) as json_error:
            # 喵~防御：协议异常只记日志，不中断连接喵
            LOGGER.warning("无法解析 QQ Bot 消息：%s", json_error)
            return
        # 喵~防御：顶层必须是对象喵
        if not isinstance(payload, dict):
            return
        # 取操作码喵
        op_code = payload.get("op")
        # op=0 是事件推送喵
        if op_code == 0:
            # 记录最新序号喵
            sequence = payload.get("s")
            if isinstance(sequence, int):
                self._seq = sequence
            # 事件类型喵
            event_type = payload.get("t")
            # 就绪事件喵
            if event_type == "READY":
                data = payload.get("d") or {}
                self._session_id = str(data.get("session_id") or "") or None
                user = data.get("user") or {}
                self._bot_id = str(user.get("id") or "") or None
                self.connected = True
                LOGGER.info("QQ Bot 已就绪：bot_id=%s", self._bot_id)
                return
            # 会话恢复完成喵
            if event_type == "RESUMED":
                self.connected = True
                LOGGER.info("QQ Bot 会话已恢复")
                return
            # 其余事件交给归一化层喵
            self._enqueue_event(payload)
            return
        # op=7 服务端要求重连喵
        if op_code == 7:
            LOGGER.info("QQ Bot 收到重连指令")
            await self._reconnect(ws=self._ws)
            return
        # op=9 会话无效，必须重新 Identify 喵
        if op_code == 9:
            LOGGER.warning("QQ Bot 会话无效，将重新 Identify")
            self._session_id = None
            self._seq = None
            self.connected = False
            return
        # op=11 心跳回执，无需处理喵
        if op_code == 11:
            return
        # op=10 Hello 已在建连阶段处理喵
        return

    async def _reconnect(self, ws: Any) -> None:
        """主动断开当前连接，让主循环重连喵。"""
        # 喵~防御：连接已经没了就不用管喵
        if ws is None:
            return
        await ws.close()

    def _enqueue_event(self, payload: dict[str, Any]) -> None:
        """归一化、预过滤、去重后放进队列喵。"""
        # 喵~注意：开着 debug_events 时把原始事件整条打出来，排查 @ 不回复全靠它喵
        if self._config.qqbot.debug_events:
            LOGGER.info(
                "QQ Bot 原始事件：t=%s msg_id=%s content=%r 全文=%s",
                payload.get("t"),
                (payload.get("d") or {}).get("id"),
                (payload.get("d") or {}).get("content"),
                json.dumps(payload, ensure_ascii=False),
            )
        # 转成归一化消息喵
        result = from_qqbot_event(payload, self._bot_id)
        # 喵~防御：非消息事件直接丢弃喵
        if result.message is None:
            # 喵~注意：debug 时也要说明为什么丢，否则看起来像「没收到」喵
            if self._config.qqbot.debug_events:
                LOGGER.info("QQ Bot 事件被丢弃：t=%s 原因=%s", payload.get("t"), result.reason)
            return
        message = result.message
        # 喵~防御：需要采集 openid 时把标识打进日志，白名单靠它填喵
        if self._config.qqbot.log_openids:
            LOGGER.info(
                "QQ Bot 事件：group_openid=%s member_openid=%s role=%s",
                message.group_key or "(单聊)",
                message.user_key,
                message.role,
            )
        # 喵~注意：debug 时把清洗后的文本与 @ 判定一并输出，能直接看出前缀有没有丢喵
        if self._config.qqbot.debug_events:
            LOGGER.info(
                "QQ Bot 归一化：text=%r mentioned=%s reply_token=%s 入队前=%s",
                message.text,
                message.mentioned,
                message.reply_token,
                self._should_enqueue(message),
            )
        # 全量模式下先在通道层做廉价预过滤，别把闲聊灌进有界队列喵
        if not self._should_enqueue(message):
            return
        # 按消息 ID 去重，防止 AT 事件与全量事件各回一次喵
        if not self._seen.first_time(message.reply_token or ""):
            LOGGER.info("QQ Bot 重复事件已丢弃：%s", message.reply_token)
            return
        try:
            # 入队，交给串行消费者喵
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # 喵~防御：队列满时丢弃并告警，避免无限堆积喵
            LOGGER.warning("QQ Bot 事件队列已满，丢弃一条事件")

    def _should_enqueue(self, message: NormalizedMessage) -> bool:
        """判断这条消息有没有可能触发命令喵。"""
        # 单聊量小，直接放行交给 ACL 判定喵
        if message.scope == SCOPE_PRIVATE:
            return True
        # @ 机器人的消息一律放行喵
        if message.mentioned:
            return True
        # 免 @ 只对配置里列出的群开放喵
        if message.group_key not in self._config.qqbot.free_command_group_openids:
            return False
        # 要求前缀时做一次廉价字符串判断喵
        if self._config.qqbot.free_command_require_prefix:
            return message.text.lstrip().startswith(COMMAND_PREFIXES)
        return True

    async def _consume_events(self) -> None:
        """串行消费事件队列，保证命令按到达顺序处理喵。"""
        while True:
            # 取一条消息喵
            message = await self._queue.get()
            try:
                # 交给业务层喵
                await self._handler(message)
            except asyncio.CancelledError:
                # 取消信号必须原样抛出喵
                raise
            except Exception as handler_error:  # noqa: BLE001
                # 喵~防御：单条消息失败不能影响后续消息喵
                LOGGER.exception("处理 QQ Bot 消息失败：%s", handler_error)
            finally:
                # 标记处理完成喵
                self._queue.task_done()


class QQBotChannel:
    """官方 QQ Bot 通道：把客户端与发送能力组装成统一接口喵。"""

    # 通道名喵
    name = CHANNEL_QQBOT

    def __init__(
        self,
        config: AppConfig,
        event_handler: MessageHandler,
        *,
        api: QQBotApi | None = None,
        connector: Callable[[str], Any] | None = None,
    ) -> None:
        # 配置引用喵
        self._config = config
        # HTTP 封装，测试可注入 MockTransport 客户端喵
        self._api = api or QQBotApi(
            api_base=config.qqbot.api_base,
            app_id=config.qqbot.app_id,
            app_secret=config.qqbot.app_secret,
            timeout_seconds=config.qqbot.request_timeout_seconds,
            refresh_margin_seconds=config.qqbot.token_refresh_margin_seconds,
        )
        # 网关客户端喵
        self._client = QQBotClient(config, self._api, event_handler, connector=connector)
        # 回复序号计数喵
        self._replies = ReplyCounter()
        # 主动消息限流喵
        self._limiter = ActiveMessageLimiter()

    async def run(self) -> None:
        """启动通道喵。"""
        # 直接跑客户端主循环喵
        await self._client.run()

    async def stop(self) -> None:
        """停止通道并关闭 HTTP 客户端喵。"""
        # 先停网关喵
        await self._client.stop()
        # 再关连接池喵
        await self._api.close()

    def is_connected(self) -> bool:
        """是否已就绪喵。"""
        # 转发客户端状态喵
        return self._client.is_connected()

    async def send_text(
        self,
        group_key: str,
        text: str,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        mention_user_key: str | None = None,
    ) -> None:
        """发文本；官方接口没有 at 字段，mention_user_key 被忽略喵。"""
        # 喵~防御：空文本不发送喵
        if not text or not text.strip():
            return
        # 截断到官方长度上限喵
        safe_text = _truncate(text)
        # 有凭据就是被动回复，序号必须递增喵
        if reply_token:
            await self._api.send_text(
                scope,
                group_key,
                safe_text,
                msg_id=reply_token,
                msg_seq=self._replies.next(reply_token),
            )
            return
        # 没有凭据属于主动消息，先过本地限流喵
        self._limiter.acquire(f"{scope}:{group_key}")
        await self._api.send_text(scope, group_key, safe_text)

    async def send_image(
        self,
        group_key: str,
        image_bytes: bytes,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        caption: str | None = None,
    ) -> None:
        """先上传再发富媒体，官方不支持内联 base64 喵。"""
        # 喵~防御：空图片不发送喵
        if not image_bytes:
            return
        # 上传拿 file_info 喵
        file_info = await self._api.upload_image(scope, group_key, image_bytes)
        # 被动回复要带凭据与递增序号喵
        if reply_token:
            await self._api.send_image(
                scope,
                group_key,
                file_info,
                msg_id=reply_token,
                msg_seq=self._replies.next(reply_token),
            )
        else:
            # 主动消息先过限流喵
            self._limiter.acquire(f"{scope}:{group_key}")
            await self._api.send_image(scope, group_key, file_info)
        # 有说明文字时补一条文本喵
        if caption:
            await self.send_text(group_key, caption, scope=scope, reply_token=reply_token)
