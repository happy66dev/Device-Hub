"""访问控制与命令分发。

职责边界：
- 判断一条群消息该不该响应（白名单群、黑名单用户、是否 @ 机器人）；
- 把文本解析成命令名与参数；
- 按命令名查命令表，跑数据准备 + 模板渲染得到回复。
不负责网络收发，网络部分在 napcat 模块喵。

喵~注意：本模块不再拼任何文案，所有用户可见文字都在 commands.FRAGMENTS 与
commands.COMMANDS 的模板里；这里只做「决策 + 兜底」喵。
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from .. import acl as acl_module, db, queries
from ..config import AppConfig
from . import commands, dataset, expr, happy
from .channel import (
    CHANNEL_QQBOT,
    COMMAND_PREFIXES,
    REASON_BAD_IDS,
    REASON_GROUP_NOT_WHITELISTED,
    REASON_NOT_COMMAND,
    REASON_NOT_GROUP,
    REASON_NOT_MENTIONED,
    REASON_NOT_MESSAGE,
    REASON_OK,
    REASON_ROLE_TOO_LOW,
    REASON_UNKNOWN_COMMAND,
    REASON_USER_BLACKLISTED,
    ROLE_ORDER,
    normalize_command_text,
    SCOPE_PRIVATE,
    NormalizedMessage,
    extract_onebot_text,
    from_onebot_event,
)

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot")

# 参数分隔用的空白正则，包含全角空格喵
WHITESPACE_PATTERN = re.compile(r"[\s\u3000]+")

# 命令参数里出现这个字就渲染成图片喵
IMAGE_FLAG = "图"

# 渲染环境缓存：片段表是模块常量，解析一次就够喵
_FRAGMENTS_CACHE: dict[str, tuple[Any, ...]] | None = None


def _fragments() -> dict[str, tuple[Any, ...]]:
    """取解析好的片段表，首次调用时解析喵。"""
    # 喵~注意：片段是硬编常量，进程内不会变，缓存是安全的喵
    global _FRAGMENTS_CACHE
    if _FRAGMENTS_CACHE is None:
        _FRAGMENTS_CACHE = commands.fragment_nodes()
    return _FRAGMENTS_CACHE


@dataclass(frozen=True)
class ParsedCommand:
    """解析后的命令喵。"""

    # 命令名，不含前缀，例如 "设备" 喵
    name: str
    # 命令参数元组，按空白切分喵
    args: tuple[str, ...]


def extract_text_and_mention(message: Any, self_qq: str) -> tuple[str, bool]:
    """从消息体里提取纯文本，并判断是否 @ 了机器人喵。

    输入：OneBot 消息体（数组或纯字符串）、机器人 QQ 号。
    输出：(文本, 是否 @ 机器人)。
    边界：消息体为空、结构异常时返回 ("", False)喵。
    """
    # 复用归一化层的实现，保证两条路径永不漂移喵
    return extract_onebot_text(message, self_qq)


def _has_prefix(text: str) -> bool:
    """文本是否以命令前缀开头喵。"""
    # 喵~注意：再洗一次，防止调用方传进来的文本带零宽字符或前导空白喵
    return normalize_command_text(text).startswith(COMMAND_PREFIXES)


def _match_prefix(text: str) -> tuple[bool, str, str]:
    """命中前缀时返回去掉前缀的命令文本喵。"""
    # 喵~注意：统一走清洗函数，零宽空格与全角空格都会被吃掉喵
    stripped = normalize_command_text(text)
    # 逐个前缀尝试喵
    for prefix in COMMAND_PREFIXES:
        if stripped.startswith(prefix):
            return True, stripped[len(prefix) :].strip(), REASON_OK
    # 喵~防御：没有前缀视为闲聊喵
    return False, "", REASON_NOT_COMMAND


def inspect_normalized(message: NormalizedMessage, config: AppConfig) -> tuple[bool, str, str]:
    """归一化消息的准入判断，语义与 inspect_event_detail 完全对齐喵。

    输入：归一化消息、服务端配置。
    输出：(是否响应, 命令文本, 原因码)。
    边界：单聊走独立白名单；群聊按通道取 openid 或群号命名空间喵。
    """
    # 取该通道生效的访问控制喵
    acl = config.acl.for_channel(message.channel)
    # 单聊没有群概念，用独立白名单喵
    if message.scope == SCOPE_PRIVATE:
        # 喵~防御：私聊默认一律不响应，必须显式配置 user_openid 喵
        if message.user_key not in acl.private_users:
            return False, "", REASON_GROUP_NOT_WHITELISTED
        # 喵~防御：黑名单对私聊同样生效喵
        # 喵~注意：这里原来直接 return，**跳过了黑名单检查**——
        # 同一个用户在群里被拉黑后不响应，私聊却照样能查数据，
        # WebUI 里那个「拉黑」按钮对私聊看起来生效、实际无效。
        # 《docs/qqbot.md》写明黑名单是两道闸门之一，群聊与单聊都必须过喵
        if message.user_key in acl_module.effective_blacklist(config, message.channel):
            return False, "", REASON_USER_BLACKLISTED
        # 私聊本身就是对机器人说话，不需要 @ 喵
        return _match_prefix(message.text)
    # 喵~防御：白名单为空时任何群都不响应，这是安全默认值喵
    if message.group_key not in acl.whitelist_groups:
        return False, "", REASON_GROUP_NOT_WHITELISTED
    # 喵~防御：黑名单用户即使 @ 了机器人也不响应喵
    # 喵~注意：这里是「配置名单 + WebUI 运行时名单」的并集，后者改完即生效喵
    if message.user_key in acl_module.effective_blacklist(config, message.channel):
        return False, "", REASON_USER_BLACKLISTED
    # 官方通道允许指定群免 @ 触发喵
    free_mode = message.channel == CHANNEL_QQBOT and message.group_key in config.qqbot.free_command_group_openids
    # 非免 @ 群沿用原有行为：必须 @ 机器人才响应喵
    if not free_mode:
        # 喵~防御：没 @ 机器人就不响应，避免刷屏喵
        if not message.mentioned:
            return False, "", REASON_NOT_MENTIONED
        return _match_prefix(message.text)
    # 免 @ 群仍要求命令前缀，否则群里闲聊会误触发喵
    if config.qqbot.free_command_require_prefix and not _has_prefix(message.text):
        return False, "", REASON_NOT_COMMAND
    # 角色门槛，any 表示不限制喵
    required_role = config.qqbot.free_command_min_role
    if ROLE_ORDER.get(message.role, 0) < ROLE_ORDER.get(required_role, 0):
        return False, "", REASON_ROLE_TOO_LOW
    # 通过全部闸门后按前缀解析命令喵
    return _match_prefix(message.text)


def inspect_event_detail(event: dict[str, Any], config: AppConfig) -> tuple[bool, str, int, int, str]:
    """判断事件是否该响应，并返回原因码喵。

    输入：OneBot 事件字典、服务端配置。
    输出：(是否响应, 命令文本, 群号, 发送者 QQ 号, 原因码)。
    边界：非群消息、非白名单群、黑名单用户、未 @ 机器人、非命令前缀一律不响应喵。
    """
    # 先归一化成协议无关结构喵
    normalized = from_onebot_event(event, config.napcat.self_qq)
    # 喵~防御：不是群消息时原样返回原因码喵
    if normalized.message is None:
        return False, "", 0, 0, normalized.reason
    # 复用归一化准入判断，保证两套逻辑不漂移喵
    handled, command_text, reason = inspect_normalized(normalized.message, config)
    # 老签名要整数群号与 QQ 号喵
    return handled, command_text, int(normalized.message.group_key), int(normalized.message.user_key), reason


def inspect_event(event: dict[str, Any], config: AppConfig) -> tuple[bool, str, int, int]:
    """判断事件是否该响应，并返回去掉前缀的命令文本喵。

    输入：OneBot 事件字典、服务端配置。
    输出：(是否响应, 命令文本, 群号, 发送者 QQ 号)。
    边界：非群消息、非白名单群、黑名单用户、未 @ 机器人、非命令前缀一律不响应喵。
    """
    # 复用带原因码的实现，这里只要四元组喵
    handled, command_text, group_id, user_id, _reason = inspect_event_detail(event, config)
    # 返回老签名喵
    return handled, command_text, group_id, user_id


def parse_command(text: str) -> ParsedCommand | None:
    """把命令文本解析成命令名与参数喵。

    输入：已去掉前缀的文本，例如 "使用 win-1 2"。
    输出：ParsedCommand，文本为空时返回 None。
    边界：多个连续空白会被合并，全角空格同样支持喵。
    """
    # 喵~注意：先清洗，零宽空格、BOM、全角空格都会在这里被吃掉喵
    cleaned = normalize_command_text(text)
    # 喵~防御：清洗后为空说明没有命令可解析喵
    if not cleaned:
        return None
    # 按空白切分喵
    parts = [piece for piece in WHITESPACE_PATTERN.split(cleaned) if piece]
    # 喵~防御：切分后为空说明只有空白字符喵
    if not parts:
        return None
    # 第一个是命令名，其余是参数喵
    return ParsedCommand(name=parts[0], args=tuple(parts[1:]))


def _strip_optional_prefix(command_text: str) -> str:
    """把可能存在的命令前缀剥掉喵。

    输入：调用方传来的命令文本，可能带 "/" 也可能不带。
    输出：去掉前缀并清洗过的文本。
    边界：没有前缀时原样返回清洗后的文本喵。

    喵~注意：入站消息在准入阶段已经剥过前缀，但看板「命令测试」页、
    接口调试、脚本调用都会直接把 "/happy设备" 传进来，
    这一步保证三条入口对前缀的容忍度一致喵。
    """
    # 复用前缀匹配，命中就取剥好的文本喵
    hit, stripped, _reason = _match_prefix(command_text)
    # 没有前缀时仍要清洗，把零宽字符与多余空白去掉喵
    return stripped if hit else normalize_command_text(command_text)


def resolve_command(command_text: str) -> tuple[ParsedCommand | None, commands.Command | None]:
    """把命令文本解析成「命令名 + 参数」并查命令表喵。

    输入：命令文本，允许带 "/" 前缀，也容忍零宽字符与全角空白。
    输出：(解析结果, 命中的命令)；纯空白文本返回 (None, None)，
          命令名查不到时返回 (解析结果, None)。
    边界：前缀剥除、清洗、查表三条入口共用这一份实现，保证口径不漂移喵。
    """
    # 喵~注意：允许调用方带前缀，这里统一剥掉再解析喵
    cleaned = _strip_optional_prefix(command_text)
    # 解析命令喵
    parsed = parse_command(cleaned)
    # 喵~防御：没有命令可解析时两条都空，由调用方决定要不要回帮助喵
    if parsed is None:
        return None, None
    # 查命令表喵
    return parsed, commands.command_by_name(parsed.name)


def is_silent_command(command_text: str) -> bool:
    """判断这条命令是否应当完全静默（一个字都不回）喵。

    输入：命令文本，允许带 "/" 前缀。
    输出：命令名不在命令表里时返回 True；解析不出命令（纯空白）时返回 False，
          因为「只 @ 机器人不说话」仍走帮助，那是原有行为。

    喵~注意：这是「未知命令静默」的唯一判定点，runner 与 simulate 都调它，
    免得真实机器人与看板「命令测试」对同一条消息给出两种结论喵。
    """
    # 解析并查表喵
    parsed, command = resolve_command(command_text)
    # 喵~防御：连命令名都没有，交回原有逻辑（空命令 → 帮助）喵
    if parsed is None:
        return False
    # 命令名对不上任何已注册命令：静默喵
    return command is None


def build_reply(connection: sqlite3.Connection, config: AppConfig, command_text: str) -> str:
    """根据命令文本生成回复文本喵。

    输入：数据库连接、配置、已去掉前缀的命令文本。
    输出：要发到群里的文本；未知命令返回空串表示「什么都不发」。
    边界：模板渲染失败、设备找不到、参数写错都会退回可读的中文提示，
          只有「命令名不在命令表里」这一种情况返回空串静默喵。
    """
    # 解析并查表喵
    parsed, command = resolve_command(command_text)
    # 喵~防御：只 @ 了机器人却没写命令时返回帮助，避免主人以为机器人没反应喵
    if parsed is None:
        return _render_command(connection, config, commands.command_by_name("happy帮助"), (), "")
    # 喵~防御：未知命令完全静默，不回文本也不回图片，避免在群里刷屏喵
    if command is None:
        LOGGER.debug("未知命令 %r，静默忽略", parsed.name)
        return ""
    # 渲染命令喵
    return _render_command(connection, config, command, parsed.args, _strip_optional_prefix(command_text))


def _render_command(
    connection: sqlite3.Connection,
    config: AppConfig,
    command: commands.Command | None,
    args: tuple[str, ...],
    raw_text: str,
) -> str:
    """跑一条命令的数据准备与模板渲染喵。

    输入：连接、配置、命令定义、参数、原始命令文本。
    输出：渲染结果；任何异常都转成可读提示。
    边界：命令定义为 None 时返回空串，由调用方决定兜底文案喵。
    """
    # 喵~防御：命令不存在时没有模板可渲染喵
    if command is None:
        return ""
    # 基准时间统一取一次，保证一条命令内所有查询口径一致喵
    now = db.utc_now()
    # 组装命令上下文喵
    context = commands.CommandContext(
        connection=connection,
        config=config,
        name=command.name,
        args=args,
        now=now,
        raw_text=raw_text,
    )
    try:
        # 数据准备喵
        scope = command.handler(context)
        # 渲染环境喵
        env = dataset.TemplateEnv(_fragments(), dataset.make_context(connection, now))
        # 按作用域挑模板（部分命令带参数时换一份文案）喵
        return expr.render_text(command.pick_template(scope), (scope,), env).strip()
    except commands.DeviceLookupError as lookup_error:
        # 设备找不到这类提示本身就是给用户看的中文，直接回喵
        return str(lookup_error)
    except happy.HappyError as happy_error:
        # 喵~防御：设备组缺失时同样直接回提示，别让机器人静默喵
        return str(happy_error)
    except expr.TemplateError as template_error:
        # 喵~防御：模板写错属于开发期错误，记日志并给一句可读提示喵
        LOGGER.exception("命令 %s 的模板有语法错误：%s", command.name, template_error)
        return "命令模板配置有误，已记录到服务端日志。"
    except (expr.QueryError, dataset.DatasetError) as query_error:
        # 喵~防御：查询参数写错同样只影响这一条命令喵
        LOGGER.exception("命令 %s 的查询参数有误：%s", command.name, query_error)
        return "命令查询条件有误，已记录到服务端日志。"
    except sqlite3.Error as database_error:
        # 喵~防御：数据库异常时给用户一句可读提示，同时把堆栈写进日志喵
        LOGGER.exception("处理命令 %s 时数据库出错：%s", command.name, database_error)
        return "服务端查询数据时出错，请稍后再试。"


def build_image(connection: sqlite3.Connection, config: AppConfig, command_text: str) -> bytes | None:
    """按命令生成图片，不支持或不需要图片时返回 None 喵。

    只有 `/看看happy <范围> <排行榜/时间轴>` 会出图，两分支都截真实看板喵。
    输入：数据库连接、配置、已去掉前缀的命令文本。
    输出：PNG 字节流或 None。
    边界：配置关闭图片、命令不支持、参数不足、截图失败时都返回 None，
          由调用方退回文本回复喵。
    """
    # 喵~防御：配置关闭图片时直接放弃，避免无谓的渲染开销喵
    if not config.render.image_enabled:
        return None
    # 喵~注意：与文本入口保持一致，允许带前缀喵
    command_text = _strip_optional_prefix(command_text)
    # 解析命令喵
    parsed = parse_command(command_text)
    # 喵~防御：空命令没有图片可画喵
    if parsed is None:
        return None
    # 查命令定义喵
    command = commands.command_by_name(parsed.name)
    # 喵~防御：未知命令走文本路径喵
    if command is None:
        return None
    # 喵~防御：只有看看happy 会出图，其它命令一律走文本喵
    if command.name != "看看happy":
        return None
    # 截真实看板喵
    return _snapshot_command(connection, config, command, parsed.args)


def snapshot_base_url(config: AppConfig) -> str:
    """拼出截图要访问的服务端根地址喵。

    输入：服务端配置。
    输出：形如 http://127.0.0.1:8080 的地址。
    边界：监听在 0.0.0.0 或 :: 时换成回环地址，否则浏览器连不上喵。
    """
    # 取监听地址，通配地址换成回环喵
    host = (config.server.host or "").strip()
    if host in ("", "0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    # 取端口喵
    port = int(config.server.port)
    return f"http://{host}:{port}"


def _snapshot_command(
    connection: sqlite3.Connection,
    config: AppConfig,
    command: commands.Command,
    args: tuple[str, ...],
) -> bytes | None:
    """跑图类命令并截取对应看板页喵。

    输入：连接、配置、命令定义、参数。
    输出：PNG 字节流；参数不合法或截图失败时返回 None，由文本路径给出提示喵。
    边界：文本路径与图片路径共用同一套参数解析，保证两边口径一致喵。
    """
    # 延迟导入，缺 node 时不影响其它命令喵
    from . import snapshot

    # 喵~防御：没配服务地址时没法截喵
    base_url = snapshot_base_url(config)
    if not base_url:
        LOGGER.warning("配置里没有服务端地址，无法生成截图")
        return None
    # 先用文本路径的解析器算一遍参数，参数错时由文本给出提示喵
    try:
        context = commands.CommandContext(
            connection=connection,
            config=config,
            name=command.name,
            args=args,
            now=db.utc_now(),
        )
        scope = command.handler(context)
    except (commands.DeviceLookupError, happy.HappyError):
        # 喵~防御：参数有问题就退回文本，让它把提示发出去喵
        return None
    # 拼截图参数喵
    params: dict[str, str] = {}
    # 时间轴分支由作用域里的 is_timeline 标记决定喵
    if scope.get("is_timeline"):
        # 时间轴页签，按天定位喵
        tab = "timeline"
        params["from"] = str(scope["start_text"])
        params["to"] = str(scope.get("end_text") or scope["start_text"])
        # 起止时刻：换成看板自定义窗口的写法，前端把这段铺满并居中喵
        moment_start = str(scope.get("moment_start") or "")
        moment_end = str(scope.get("moment_end") or "")
        if moment_start and moment_end:
            params["from_time"] = moment_start
            params["to_time"] = moment_end
            # 倍率按窗口反算，和 /时间轴图 的口径一致喵
            zoom_value = commands.zoom_for_window(moment_start, moment_end)
            if zoom_value > 1:
                params["zoom"] = str(zoom_value)
    else:
        # 排行榜页签，窗口换算成小时喵
        tab = "rankings"
        # 喵~注意：看板的 hours 参数只接受**整数小时**，所以一小时以内的窗口
        # 没法精确表达。这里改成向上取整而不是四舍五入——四舍五入会把
        # 30 分钟画成 1 小时（图上写着 1h、文字却说「最近 30 分钟」），
        # 45 分钟也画成 1 小时；向上取整至少保证「图上显示的窗口 ⊇ 文字说的窗口」，
        # 宁可多看一点也不能让人少看数据喵。
        # 真要精确到分钟，得给看板加一个 hours 的小数/分钟参数，属于接口改动喵
        hours = max(1, math.ceil(int(scope["window_seconds"]) / 3600))
        params["hours"] = str(hours)
        # 看板按设备分组展示，这样单设备与多设备都能只显示指定范围喵
        params["scope"] = "device"
    # 设备范围：只放命令参数指定的那几台喵
    device_ids = [str(item) for item in scope["device_ids"]]
    if device_ids:
        params["devices"] = ",".join(device_ids)
        # 时间轴用单台或组的写法，多台时退回「全部合并」由 devices 过滤喵
        params["device"] = device_ids[0] if len(device_ids) == 1 else "__all__"
    try:
        # 截图喵
        return snapshot.capture_dashboard(base_url, config.ingest.token, tab, params)
    except snapshot.ShotError as shot_error:
        # 喵~防御：截图失败只记日志并退回文本，不让命令彻底没反应喵
        LOGGER.warning("截图失败，退回文本回复：%s", shot_error)
        return None
