"""协议无关的消息归一化层：业务层只认 NormalizedMessage 喵。

职责边界：
- 定义归一化消息结构（通道名、会话标识、发送者标识、文本、是否 @、角色、被动回复凭据）；
- 定义通道接口 BotChannel，让 runner 不关心底层是 OneBot 还是官方 API；
- 提供两种协议到归一化结构的纯函数转换，测试可以直接构造事件验证。
不负责网络收发，也不碰数据库喵。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

# 通道名常量：写错字符串在运行期极难发现，统一在这里定义喵
CHANNEL_NAPCAT = "napcat"

# 官方 QQ Bot 通道名喵
CHANNEL_QQBOT = "qqbot"

# 会话类型：群聊与单聊，官方两个接口不通用喵
SCOPE_GROUP = "group"

# 单聊会话类型喵
SCOPE_PRIVATE = "private"

# 官方全量消息模式下 @ 会被替换成占位符，解析前必须清掉喵
MENTION_PLACEHOLDER = re.compile(r"<@!?[\w-]+>")

# 允许的命令前缀，半角与全角斜杠都接受，减少手机输入法带来的困扰喵
COMMAND_PREFIXES: tuple[str, ...] = ("/", "／")

# 喵~注意：这些字符肉眼看不见，但会让 "/happy设备" 不以 / 开头，
# 手机输入法、复制粘贴、系统输入法的联想词都可能带上它们喵
INVISIBLE_CHARS: frozenset[str] = frozenset(
    {
        "\u200b",  # 零宽空格，最常见
        "\u200c",  # 零宽非连接符
        "\u200d",  # 零宽连接符
        "\u2060",  # 词连接符
        "\ufeff",  # BOM / 零宽不换行空格
        "\u180e",  # 蒙古文元音分隔符，常被当空格用
    }
)

# 通道发送失败的统一异常，runner 靠它决定是否退回文本喵
class ChannelError(Exception):
    """通道层可预期的发送失败（限流、凭据过期、平台拒绝等）喵。"""
# 群内角色强弱顺序，用来比较免 @ 门槛喵
ROLE_ORDER: dict[str, int] = {"member": 0, "admin": 1, "owner": 2}

# 事件处理结果的原因码，供命令测试接口区分"为什么没回复"喵
REASON_OK = "ok"

# 不是消息事件喵
REASON_NOT_MESSAGE = "not_message"

# 不是群消息喵
REASON_NOT_GROUP = "not_group"

# 群号或 QQ 号字段异常喵
REASON_BAD_IDS = "bad_ids"

# 会话不在白名单喵
REASON_GROUP_NOT_WHITELISTED = "group_not_whitelisted"

# 用户在黑名单里喵
REASON_USER_BLACKLISTED = "user_blacklisted"

# 没有 @ 机器人喵
REASON_NOT_MENTIONED = "not_mentioned"

# @ 了但没有命令前缀喵
REASON_NOT_COMMAND = "not_command"

# 命令名不在命令表里，按静默处理（群里一个字都不回）喵
REASON_UNKNOWN_COMMAND = "unknown_command"

# 免 @ 模式下角色不够喵
REASON_ROLE_TOO_LOW = "role_too_low"

# 同一条消息已经回过，重复推送被丢弃喵
REASON_DUPLICATE = "duplicate_message"


@dataclass(frozen=True)
class NormalizedMessage:
    """归一化后的入站消息，业务层只认这个结构喵。"""

    # 通道名，取值见 CHANNEL_* 常量喵
    channel: str
    # 会话标识：群聊是群号或 group_openid，单聊是 user_openid 喵
    group_key: str
    # 发送者标识：QQ 号或 member_openid 喵
    user_key: str
    # 已清洗过的原始文本（@ 占位符被去掉）喵
    text: str
    # 是否 @ 了机器人，官方 @ 事件恒为 True 喵
    mentioned: bool
    # 会话类型，group 或 private 喵
    scope: str = SCOPE_GROUP
    # 群内角色：member / admin / owner，napcat 恒为 member 喵
    role: str = "member"
    # 发送者昵称，拿不到时为空串喵
    # 喵~注意：NapCat 能给 sender.nickname / card，官方通道完全拿不到，只能靠 openid 认人喵
    display_name: str = ""
    # 被动回复凭据：官方填事件 d.id，napcat 填 None 喵
    reply_token: str | None = None
    # 原始事件，排查问题用喵
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def send_target(self) -> str:
        """发送回复时该填的目标标识喵。

        输出：群聊返回 `group_key`；单聊返回 `user_key`（即 user_openid）喵。

        喵~注意：单聊的 `group_key` 是**故意留空**的（单聊没有群概念），
        而官方接口的单聊路径是 `/v2/users/{openid}/messages`，
        目标必须是 user_openid 而不是空串。之前调用方一律传 `group_key`，
        单聊就拼成了 `/v2/users//messages`，**私聊完全收不到回复**，
        而错误又被 `SEND_ERRORS` 吞成一条 warning，很难发现喵。
        统一从这里取目标，就不会再有人各自拼错喵。
        """
        # 单聊用发送者标识当目标喵
        if self.scope == SCOPE_PRIVATE:
            return self.user_key
        # 群聊用群标识喵
        return self.group_key


class BotChannel(Protocol):
    """所有通道实现同一套生命周期与发送能力喵。"""

    # 通道名，用于日志与 ACL 选择喵
    name: str

    async def run(self) -> None:
        """启动通道主循环，直到被取消喵。"""
        ...

    async def stop(self) -> None:
        """请求停止通道喵。"""
        ...

    def is_connected(self) -> bool:
        """当前是否已连上对端喵。"""
        ...

    async def send_text(
        self,
        group_key: str,
        text: str,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        mention_user_key: str | None = None,
    ) -> None:
        """发送文本；mention_user_key 只有支持的通道才会真的 @ 人喵。"""
        ...

    async def send_image(
        self,
        group_key: str,
        image_bytes: bytes,
        *,
        scope: str = SCOPE_GROUP,
        reply_token: str | None = None,
        caption: str | None = None,
    ) -> None:
        """发送图片，可附带一行说明喵。"""
        ...


@dataclass(frozen=True)
class NormalizedEvent:
    """归一化结果：成功时 message 有值，失败时带上原因码喵。"""

    # 归一化消息，失败时为 None 喵
    message: NormalizedMessage | None
    # 原因码，成功时是空串喵
    reason: str = ""


def strip_mention_placeholders(content: str) -> str:
    """去掉官方全量模式里的 <@openid> 占位符喵。

    输入：官方事件里的原始 content。
    输出：去掉占位符、清掉不可见字符后的文本。
    边界：非字符串一律当空串处理喵。
    """
    # 喵~防御：字段缺失或类型不对时不要抛异常，交给上层按空文本处理喵
    if not isinstance(content, str):
        return ""
    # 先剥掉占位符，再把不可见字符与多余空白清掉喵
    return normalize_command_text(MENTION_PLACEHOLDER.sub(" ", content))


def normalize_command_text(text: str) -> str:
    """把命令文本清洗成「可直接判断前缀」的形态喵。

    输入：任意原始文本。
    输出：去掉不可见字符、压缩空白、并丢掉首个非空白字符之前的一切空白。
    边界：非字符串返回空串喵。

    喵~注意：手机输入法与系统输入法常常插入零宽空格（U+200B）、BOM（U+FEFF）、
    词连接符（U+2060）、不换行空格（U+00A0）等字符，而 Python 的 lstrip()
    只认 isspace() 为真的字符，上面这些都不在其中，
    于是「/happy设备」会看起来不像以 / 开头，命令被当成闲聊丢掉喵。
    """
    # 喵~防御：非字符串一律按空文本处理喵
    if not isinstance(text, str):
        return ""
    # 先删掉所有不可见格式字符，它们不占显示宽度但会挡住前缀判断喵
    cleaned = "".join(char for char in text if char not in INVISIBLE_CHARS)
    # 再把各种空白收成一个半角空格，首尾去掉喵
    return " ".join(cleaned.split())


def detect_self_mention(content: str, bot_id: str | None) -> bool:
    """判断全量模式下的消息是否 @ 了机器人喵。

    输入：原始 content、机器人自身 ID（取自 READY 事件）。
    输出：是否 @ 了自己。
    边界：bot_id 缺失时一律返回 False，避免误判成免 @ 触发喵。
    """
    # 喵~防御：没有自身 ID 就无法判断，只能按未 @ 处理喵
    if not bot_id or not isinstance(content, str):
        return False
    # 两种占位符写法都要认喵
    return f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content


def _onebot_segment_text(segment: Any) -> str:
    """从 OneBot 单个消息段里取出文本喵。"""
    # 喵~防御：不是字典的段直接忽略喵
    if not isinstance(segment, dict) or segment.get("type") != "text":
        return ""
    # data 必须是字典喵
    data = segment.get("data")
    if not isinstance(data, dict):
        return ""
    # text 必须是字符串喵
    text_value = data.get("text")
    return text_value if isinstance(text_value, str) else ""


def _onebot_segment_at(segment: Any) -> str | None:
    """从 OneBot 单个消息段里取出被 @ 的 QQ 号喵。"""
    # 喵~防御：非 at 段直接跳过喵
    if not isinstance(segment, dict) or segment.get("type") != "at":
        return None
    # data 必须是字典喵
    data = segment.get("data")
    if not isinstance(data, dict):
        return None
    # qq 可能是整数也可能是字符串，统一转字符串喵
    qq_value = data.get("qq")
    return None if qq_value is None else str(qq_value)


def extract_onebot_text(message: Any, self_qq: str) -> tuple[str, bool]:
    """从 OneBot 消息体里取出文本与 @ 状态喵。

    输入：消息体（段数组或纯字符串）、机器人 QQ 号。
    输出：(文本, 是否 @ 机器人)。
    边界：结构异常时返回 ("", False)喵。
    """
    # 喵~防御：消息体缺失喵
    if message is None:
        return "", False
    # 兼容 NapCat 配置成字符串格式的情况喵
    if isinstance(message, str):
        return normalize_command_text(message), False
    # 喵~防御：既不是字符串也不是数组说明协议不对喵
    if not isinstance(message, list):
        return "", False
    # 收集文本片段喵
    text_parts: list[str] = []
    # 是否 @ 了机器人喵
    mentioned_self = False
    # 逐段解析喵
    for segment in message:
        # 拼接文本喵
        text_parts.append(_onebot_segment_text(segment))
        # 取被 @ 的 QQ 号喵
        at_qq = _onebot_segment_at(segment)
        # 喵~防御：self_qq 为空时无法判断是否 @ 了自己喵
        if at_qq is not None and self_qq and at_qq == self_qq:
            mentioned_self = True
    # 拼接并去掉首尾空白喵
    return normalize_command_text("".join(text_parts)), mentioned_self


def from_onebot_event(event: dict[str, Any], self_qq: str = "") -> NormalizedEvent:
    """把 OneBot 11 事件转成归一化消息喵。

    输入：OneBot 事件字典、配置里的机器人 QQ 号。
    输出：NormalizedEvent，非消息事件返回对应原因码。
    边界：群号或 QQ 号不是整数时返回 bad_ids 喵。
    """
    # 喵~防御：只处理消息事件喵
    if not isinstance(event, dict) or event.get("post_type") != "message":
        return NormalizedEvent(None, REASON_NOT_MESSAGE)
    # 喵~防御：只处理群消息，NapCat 侧不做单聊喵
    if event.get("message_type") != "group":
        return NormalizedEvent(None, REASON_NOT_GROUP)
    # 群号与发送者 QQ 号转整数喵
    try:
        group_id = int(event.get("group_id", 0))
        user_id = int(event.get("user_id", 0))
    except (TypeError, ValueError):
        # 喵~防御：字段类型异常说明协议对不上喵
        return NormalizedEvent(None, REASON_BAD_IDS)
    # 机器人 QQ 号优先用配置里的，缺省时回退到事件里的 self_id 喵
    bot_qq = self_qq or str(event.get("self_id", ""))
    # 提取文本与 @ 状态喵
    message_text, mentioned_self = extract_onebot_text(event.get("message"), bot_qq)
    # 喵~注意：群名片 card 优先于昵称 nickname，群里大家更认得名片喵
    sender = event.get("sender") or {}
    sender_name = str(sender.get("card") or sender.get("nickname") or "").strip()
    # 组装归一化消息喵
    message = NormalizedMessage(
        channel=CHANNEL_NAPCAT,
        group_key=str(group_id),
        user_key=str(user_id),
        text=message_text,
        mentioned=mentioned_self,
        scope=SCOPE_GROUP,
        role="member",
        reply_token=None,
        raw=event,
        # 喵~注意：OneBot 会带 sender.nickname，能拿到就顺手记下来喵
        display_name=sender_name,
    )
    # 返回成功结果喵
    return NormalizedEvent(message, "")


def _qqbot_author_name(author: dict[str, Any]) -> str:
    """尽力从官方事件的 author 里取一个可读名字喵。

    输入：官方事件里的 author 字典。
    输出：昵称；取不到时返回空串。
    边界：官方平台目前不下发昵称，这个函数多数情况下返回空串，
          留着是为了将来平台补字段时能自动生效喵。
    """
    # 按可能性从高到低试几个字段喵
    for key in ("username", "nickname", "nick", "name"):
        value = str(author.get(key) or "").strip()
        if value:
            return value
    # 喵~防御：一个都没有就是拿不到，交给上层按 openid 显示喵
    return ""


def from_qqbot_event(event: dict[str, Any], bot_id: str | None = None) -> NormalizedEvent:
    """把官方 QQ Bot 的 op=0 事件转成归一化消息喵。

    输入：官方事件信封、机器人自身 ID（用于全量模式探测 @）。
    输出：NormalizedEvent，非消息事件返回对应原因码。
    边界：群事件缺 group_openid、单聊事件缺 user_openid 时返回 bad_ids 喵。
    """
    # 喵~防御：只有 op=0 才是事件推送喵
    if not isinstance(event, dict) or event.get("op") != 0:
        return NormalizedEvent(None, REASON_NOT_MESSAGE)
    # 事件类型喵
    event_type = str(event.get("t") or "")
    # 事件体喵
    payload = event.get("d")
    # 喵~防御：事件体必须是字典喵
    if not isinstance(payload, dict):
        return NormalizedEvent(None, REASON_BAD_IDS)
    # 作者信息喵
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    # 原始文本，@ 占位符先留着，探测完再清洗喵
    raw_content = payload.get("content")
    # 群 @ 机器人与全量群消息都走群聊逻辑喵
    if event_type in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
        # 群标识喵
        group_openid = str(payload.get("group_openid") or "")
        # 喵~防御：没有群标识无法回复喵
        if not group_openid:
            return NormalizedEvent(None, REASON_BAD_IDS)
        # @ 事件天然代表 @ 了机器人，全量模式才需要探测喵
        mentioned = True if event_type == "GROUP_AT_MESSAGE_CREATE" else detect_self_mention(raw_content, bot_id)
        # 组装群消息喵
        message = NormalizedMessage(
            channel=CHANNEL_QQBOT,
            group_key=group_openid,
            user_key=str(author.get("member_openid") or author.get("id") or ""),
            text=strip_mention_placeholders(raw_content),
            mentioned=mentioned,
            scope=SCOPE_GROUP,
            role=str(author.get("member_role") or "member"),
            reply_token=str(payload.get("id") or "") or None,
            raw=event,
            # 喵~注意：官方通道的 author 通常只有 openid 与 role，昵称恒为空喵
            display_name=_qqbot_author_name(author),
        )
        # 返回成功结果喵
        return NormalizedEvent(message, "")
    # 单聊事件喵
    if event_type == "C2C_MESSAGE_CREATE":
        # 单聊标识喵
        user_openid = str(author.get("user_openid") or author.get("id") or "")
        # 喵~防御：没有用户标识无法回复喵
        if not user_openid:
            return NormalizedEvent(None, REASON_BAD_IDS)
        # 组装单聊消息，单聊没有群概念所以 group_key 留空喵
        message = NormalizedMessage(
            channel=CHANNEL_QQBOT,
            group_key="",
            user_key=user_openid,
            text=strip_mention_placeholders(raw_content),
            mentioned=True,
            scope=SCOPE_PRIVATE,
            role="member",
            reply_token=str(payload.get("id") or "") or None,
            raw=event,
            # 单聊同样只能尽力取，取不到就空着喵
            display_name=_qqbot_author_name(author),
        )
        # 返回成功结果喵
        return NormalizedEvent(message, "")
    # 其余事件（进群退群、按钮回调等）暂不处理喵
    return NormalizedEvent(None, REASON_NOT_MESSAGE)
