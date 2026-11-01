"""机器人发言人的记录与查询。

为什么需要它：官方通道和 NapCat 黑名单都要填 32 位的 openid / QQ 号，
但主人平时看到的只有群里的昵称和头像，光看日志捞 openid 基本没法用。
所以把「成功执行过命令的人」记下来，看板里列出 openid + 昵称 + 时间，
再配一个一键拉黑按钮，形成闭环喵。

喵~注意：只记成功执行了命令的人，不记闲聊，也不记被拦截的消息——
被拦的人本来就不该占用存储；代价是拉黑某人后他会从列表里消失，
想复查请去 acl.json 或日志里找喵。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..db import to_utc_text

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot.users")

# 列表最多返回多少人喵
MAX_LISTED_USERS = 200

# 昵称最大长度，防止异常数据把界面撑爆喵
MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class SeenUser:
    """一个在群里发过命令的人喵。"""

    # 通道名：napcat / qqbot 喵
    channel: str
    # 该通道下的用户标识：QQ 号或 member_openid 喵
    user_key: str
    # 昵称，官方通道通常为空喵
    display_name: str
    # 最近一次发命令的群会话标识喵
    group_key: str
    # 群内角色喵
    role: str
    # 累计执行过多少条命令喵
    command_count: int
    # 第一次与最近一次出现的时间喵
    first_seen_at: str
    last_seen_at: str


def record_seen(
    connection: sqlite3.Connection,
    channel: str,
    user_key: str,
    *,
    display_name: str = "",
    group_key: str = "",
    role: str = "member",
    now: datetime,
) -> None:
    """记一次「这个人成功执行了命令」喵。

    输入：连接、通道、用户标识、昵称、群标识、角色、当前时间。
    输出：无。
    边界：同一人重复出现只更新最后时间并累加计数，不会新增行喵。
    """
    # 喵~防御：标识为空说明事件解析异常，写进去也没法用来拉黑喵
    if not channel or not user_key:
        return
    # 时间统一成 UTC 文本喵
    stamp = to_utc_text(now)
    # 昵称截断并去空白喵
    name = (display_name or "").strip()[:MAX_NAME_LENGTH]
    # 喵~注意：用 upsert 保证每人一行；昵称拿到新的就覆盖，
    # 拿不到（空串）时保留旧值，这样官方通道也不会把 NapCat 记下的名字冲掉喵
    connection.execute(
        """
        INSERT INTO bot_seen_users
            (channel, user_key, display_name, group_key, role,
             command_count, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT (channel, user_key) DO UPDATE SET
            display_name  = CASE WHEN excluded.display_name != ''
                                 THEN excluded.display_name
                                 ELSE bot_seen_users.display_name END,
            group_key     = CASE WHEN excluded.group_key != ''
                                 THEN excluded.group_key
                                 ELSE bot_seen_users.group_key END,
            role          = excluded.role,
            command_count = bot_seen_users.command_count + 1,
            last_seen_at  = excluded.last_seen_at
        """,
        (channel, user_key, name, group_key, role, stamp, stamp),
    )
    # 提交事务喵
    connection.commit()


def list_seen_users(
    connection: sqlite3.Connection,
    limit: int = MAX_LISTED_USERS,
) -> list[SeenUser]:
    """按最后活跃时间倒序取最近的发言人喵。

    输入：连接、最多取多少人。
    输出：SeenUser 列表。
    边界：limit 小于 1 时返回空列表喵。
    """
    # 喵~防御：非正的 limit 没有意义喵
    if limit < 1:
        return []
    # 最近活跃的排前面喵
    rows = connection.execute(
        """
        SELECT channel, user_key, display_name, group_key, role,
               command_count, first_seen_at, last_seen_at
        FROM bot_seen_users
        ORDER BY last_seen_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        SeenUser(
            channel=str(row["channel"]),
            user_key=str(row["user_key"]),
            display_name=str(row["display_name"] or ""),
            group_key=str(row["group_key"] or ""),
            role=str(row["role"] or "member"),
            command_count=int(row["command_count"]),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
        )
        for row in rows
    ]


def prune_seen_users(connection: sqlite3.Connection, cutoff_text: str) -> int:
    """删掉很久没发过命令的人，返回删除行数喵。

    输入：连接、截止时间文本（UTC）。
    输出：删掉的行数。
    边界：截止时间由调用方按保留期算好，本函数不做下限保护喵。
    """
    # 只删「最后一次活跃」早于截止时间的喵
    cursor = connection.execute(
        "DELETE FROM bot_seen_users WHERE last_seen_at < ?", (cutoff_text,)
    )
    # 提交事务喵
    connection.commit()
    return cursor.rowcount if cursor.rowcount > 0 else 0


def display_label(user: SeenUser) -> str:
    """给一个人拼一个列表里显示的名字喵。

    输入：SeenUser。
    输出：有昵称时「昵称」，否则退回标识前缀。
    边界：官方通道没有昵称，这里给出可辨认的短标识喵。
    """
    # 有昵称优先用昵称喵
    if user.display_name:
        return user.display_name
    # 喵~注意：openid 太长，列表里只显示前 8 位，完整值在 payload 里另给喵
    key = user.user_key
    return f"{key[:8]}…" if len(key) > 8 else key


def to_payload(user: SeenUser) -> dict[str, Any]:
    """转成前端要的字典喵。"""
    return {
        "channel": user.channel,
        "user_key": user.user_key,
        "display_name": user.display_name,
        # 前端直接用这个当标题，省得再拼一次喵
        "label": display_label(user),
        "group_key": user.group_key,
        "role": user.role,
        "command_count": user.command_count,
        "first_seen_at": user.first_seen_at,
        "last_seen_at": user.last_seen_at,
    }
