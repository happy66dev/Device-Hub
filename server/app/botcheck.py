"""机器人通道连通性自检：设置页的「测试连接」按钮走这里喵。

只做一次性的短连接测试，不碰正在运行的机器人实例，
所以主人可以在改完配置、重启之前先确认凭据对不对喵。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect as ws_connect

from .bot.qqbot import QQBotApi
from .config import AppConfig

# 测试用的 echo 标记，用来在事件流里认出自己的回包喵
TEST_ECHO = "device-hub-settings-test"

# 单次测试的总超时秒数喵
TEST_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class ChannelTestResult:
    """一次通道测试的结果喵。"""

    # 通道名：napcat / qqbot 喵
    channel: str
    # 是否连通喵
    ok: bool
    # 耗时毫秒喵
    latency_ms: int
    # 成功时的补充信息（昵称、网关地址等）喵
    detail: str = ""
    # 失败原因喵
    error: str = ""


async def test_napcat(config: AppConfig, timeout: float = TEST_TIMEOUT_SECONDS) -> ChannelTestResult:
    """连一次 NapCat 正向 WS 并调 get_login_info 验证口令喵。

    输入：配置对象与超时秒数。
    输出：ChannelTestResult。
    边界：地址不通、口令错、NapCat 没开 OneBot 服务都会返回 ok=False喵。
    """
    # 计时起点喵
    started = time.monotonic()
    # 拼带口令的连接地址喵
    url = config.napcat.ws_url
    token = config.napcat.token
    if token:
        # 口令要转义，避免 + & = 被当成参数分隔符喵
        from urllib.parse import quote

        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}access_token={quote(token, safe='')}"
    try:
        # 喵~防御：整个测试套一层总超时，避免设置页卡死喵
        async with asyncio.timeout(timeout):
            async with ws_connect(url, open_timeout=timeout, close_timeout=1) as socket:
                # 发一条登录信息查询，NapCat 会回同样的 echo 喵
                await socket.send(json.dumps({"action": "get_login_info", "echo": TEST_ECHO}))
                # 循环收包，跳过事件推送，只等自己的回包喵
                while True:
                    raw = await socket.recv()
                    try:
                        payload = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    if payload.get("echo") != TEST_ECHO:
                        continue
                    # retcode 非 0 说明口令或权限有问题喵
                    if payload.get("retcode") not in (0, None):
                        return ChannelTestResult(
                            channel="napcat",
                            ok=False,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            error=f"NapCat 返回 retcode={payload.get('retcode')}，多半是访问口令不一致",
                        )
                    # 取昵称与 QQ 号喵
                    data: dict[str, Any] = payload.get("data") or {}
                    nickname = str(data.get("nickname") or "")
                    user_id = str(data.get("user_id") or "")
                    detail = f"{nickname}（{user_id}）" if nickname or user_id else "已连通"
                    return ChannelTestResult(
                        channel="napcat",
                        ok=True,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        detail=detail,
                    )
    except asyncio.TimeoutError:
        return ChannelTestResult(
            channel="napcat",
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"连接 {config.napcat.ws_url} 超时，检查 NapCat 是否开着 OneBot 正向 WS",
        )
    except Exception as error:  # noqa: BLE001
        # 喵~防御：连接被拒、握手失败等统一转成人话喵
        return ChannelTestResult(
            channel="napcat",
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"连接 {config.napcat.ws_url} 失败：{error}",
        )


async def test_qqbot(config: AppConfig, timeout: float = TEST_TIMEOUT_SECONDS) -> ChannelTestResult:
    """取一次 access_token 与网关地址，验证 AppID/AppSecret 喵。"""
    # 计时起点喵
    started = time.monotonic()
    # 喵~防御：凭据没填就不用白跑一趟喵
    if not config.qqbot.app_id or not config.qqbot.app_secret:
        return ChannelTestResult(
            channel="qqbot",
            ok=False,
            latency_ms=0,
            error="AppID 或 AppSecret 为空，先在设置页填好再测",
        )
    api = QQBotApi(
        config.qqbot.api_base,
        config.qqbot.app_id,
        config.qqbot.app_secret,
        timeout_seconds=timeout,
    )
    try:
        # 喵~防御：整个测试套一层总超时喵
        async with asyncio.timeout(timeout):
            # 换票成功说明凭据正确喵
            await api.access_token()
            # 再取网关地址，确认接口可达喵
            gateway = await api.gateway_url()
        return ChannelTestResult(
            channel="qqbot",
            ok=True,
            latency_ms=int((time.monotonic() - started) * 1000),
            detail=f"网关 {gateway}",
        )
    except asyncio.TimeoutError:
        return ChannelTestResult(
            channel="qqbot",
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"请求 {config.qqbot.api_base} 超时，检查网络能否访问开放平台",
        )
    except Exception as error:  # noqa: BLE001
        return ChannelTestResult(
            channel="qqbot",
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"鉴权失败：{error}",
        )
    finally:
        # 喵~防御：自建的 HTTP 客户端要关掉，否则会泄漏连接池喵
        await api.close()


async def test_channel(config: AppConfig, channel: str) -> ChannelTestResult:
    """按通道名分发到具体测试喵。"""
    if channel == "napcat":
        return await test_napcat(config)
    if channel == "qqbot":
        return await test_qqbot(config)
    # 喵~防御：未知通道直接报错喵
    return ChannelTestResult(channel=channel, ok=False, latency_ms=0, error=f"未知通道：{channel}")
