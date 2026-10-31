"""命令测试用的模拟器：不经过 QQ，直接把一条命令跑完整条处理链喵。

职责边界：
- 构造一条归一化的群消息（NapCat 与官方通道都能模拟）；
- 复用 router 的白名单判断与命令处理；
- 返回文本、可选图片和命中信息，供 Web 看板「命令测试」页使用。
不负责网络收发，也不写数据库喵。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from ..config import AppConfig
from . import router
from .channel import (
    CHANNEL_NAPCAT,
    CHANNEL_QQBOT,
    COMMAND_PREFIXES,
    SCOPE_GROUP,
    NormalizedMessage,
)

# 不填 QQ 号时用的假发送者喵
DEFAULT_TEST_USER = 10001

# 官方通道模拟时用的假 member_openid 喵
DEFAULT_TEST_OPENID = "TEST_MEMBER_OPENID"

# 空命令的原因码喵
REASON_EMPTY = "empty_command"

# 原因码对应的中文说明，直接给前端展示喵
REASON_TEXTS: dict[str, str] = {
    router.REASON_OK: "会正常回复",
    router.REASON_NOT_MESSAGE: "不是消息事件，机器人不会响应",
    router.REASON_NOT_GROUP: "不是群消息，机器人只响应群聊",
    router.REASON_BAD_IDS: "群号或 QQ 号不是数字，机器人不会响应",
    router.REASON_GROUP_NOT_WHITELISTED: "会话不在白名单，机器人不会响应",
    router.REASON_USER_BLACKLISTED: "该用户在黑名单，机器人不会响应",
    router.REASON_NOT_MENTIONED: "没有 @ 机器人，机器人不会响应",
    router.REASON_NOT_COMMAND: "没有命令前缀，机器人当闲聊忽略",
    router.REASON_ROLE_TOO_LOW: "免 @ 模式下该用户角色不够，机器人不会响应",
    REASON_EMPTY: "命令不能为空",
}


@dataclass(frozen=True)
class SimulationResult:
    """一次命令测试的结果喵。"""

    # 机器人是否会真的回复喵
    replied: bool
    # 原因码，ok 表示会正常回复喵
    reason: str
    # 原因码的中文说明喵
    reason_text: str
    # 去掉前缀后的命令文本喵
    command_text: str
    # 解析出的命令名，可能为空喵
    command_name: str
    # 回复文本，被忽略时为空串喵
    text: str
    # 图片字节，没有图片时为 None 喵
    image: bytes | None
    # 处理耗时毫秒喵
    elapsed_ms: int
    # 本次模拟走的通道名喵
    channel: str = CHANNEL_NAPCAT


def _elapsed_ms(started: float) -> int:
    """把起始时刻换算成毫秒耗时喵。"""
    # 四舍五入到整毫秒喵
    return int(round((time.perf_counter() - started) * 1000))


def _strip_prefix(text: str) -> str:
    """去掉命令前缀与首尾空白喵。"""
    # 逐个前缀尝试喵
    for prefix in COMMAND_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    # 没有前缀时原样返回喵
    return text.strip()


def _build_message(
    channel: str,
    text: str,
    group_key: str,
    user_key: str,
    mentioned: bool,
    role: str,
) -> NormalizedMessage:
    """构造一条归一化的假群消息喵。"""
    # 两个通道只有标识格式不同，结构完全一致喵
    return NormalizedMessage(
        channel=channel,
        group_key=group_key,
        user_key=user_key,
        text=text,
        mentioned=mentioned,
        scope=SCOPE_GROUP,
        role=role,
        reply_token=None,
        raw={},
    )


def simulate_command(
    connection: sqlite3.Connection,
    config: AppConfig,
    raw_text: str,
    group_id: int | str | None = None,
    user_id: int | str | None = None,
    channel: str = CHANNEL_NAPCAT,
    mentioned: bool = True,
    role: str = "member",
) -> SimulationResult:
    """模拟一条群命令，返回机器人会怎么回喵。

    输入：数据库连接、配置、原始命令文本、可选群标识与用户标识、
          通道名、是否 @ 了机器人、群内角色。
    输出：SimulationResult，被忽略时 text 为空并带原因码。
    边界：不填群标识表示只测渲染，跳过白名单与黑名单检查喵。
    """
    # 记录起始时刻喵
    started = time.perf_counter()
    # 去掉首尾空白喵
    text = (raw_text or "").strip()
    # 喵~防御：空命令直接返回提示，别去查库喵
    if not text:
        return SimulationResult(
            replied=False,
            reason=REASON_EMPTY,
            reason_text=REASON_TEXTS[REASON_EMPTY],
            command_text="",
            command_name="",
            text="",
            image=None,
            elapsed_ms=_elapsed_ms(started),
            channel=channel,
        )
    # 主人少打斜杠时自动补一个，测试更顺手喵
    normalized = text if text.startswith(COMMAND_PREFIXES) else f"/{text}"
    # 不填群标识时只测渲染喵
    if group_id is None:
        command_text = _strip_prefix(normalized)
        replied = True
        reason = router.REASON_OK
    else:
        # 官方通道的标识是 openid 字符串，NapCat 是整数群号喵
        group_key = str(group_id)
        # 官方通道没填用户时用一个假 openid，方便测免 @ 分支喵
        user_key = str(user_id) if user_id is not None else (DEFAULT_TEST_OPENID if channel == CHANNEL_QQBOT else str(DEFAULT_TEST_USER))
        # 组装归一化消息喵
        message = _build_message(channel, normalized, group_key, user_key, mentioned, role)
        # 走完整准入判断喵
        replied, command_text, reason = router.inspect_normalized(message, config)
    # 只有会回复时才真的去生成内容喵
    text_reply = ""
    image: bytes | None = None
    if replied:
        # 先试图片，和真实机器人一样优先发图喵
        image = router.build_image(connection, config, command_text)
        # 喵~防御：有图片就不再发文本，避免主人在群里收到一条报错喵
        if image is None:
            text_reply = router.build_reply(connection, config, command_text)
    # 解析命令名，方便前端显示命中了哪个命令喵
    parsed = router.parse_command(command_text)
    # 组装结果喵
    return SimulationResult(
        replied=replied,
        reason=reason,
        reason_text=REASON_TEXTS.get(reason, reason),
        command_text=command_text,
        command_name=parsed.name if parsed is not None else "",
        text=text_reply,
        image=image,
        elapsed_ms=_elapsed_ms(started),
        channel=channel,
    )
