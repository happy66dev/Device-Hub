"""命令定义：全部命令都是「数据准备 + 模板渲染」，没有一条在 Python 里拼字符串。

为什么要这样：主人明确说过文案「改一次就不改了」，所以模板直接硬编成模块常量，
不进配置文件、不做热加载。要改措辞、加一条新命令，改这个文件里的常量即可喵。

一条命令由三部分组成：
1. 匹配：命令名与别名（大小写不敏感）；
2. 数据：调用 dataset 拿到模板作用域；
3. 文案：模板文本，支持 expr 模块的全部语法喵。

作用域里的键一律用英文，模板里写中文，靠 expr.ALIASES 翻译，
这样代码与文案各用顺手的写法，又只有一个真相喵。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from .. import people
from ..config import AppConfig
from . import dataset, expr, happy

# 命令处理函数的签名：拿到上下文，返回模板作用域喵
Handler = Callable[["CommandContext"], Mapping[str, Any]]

# 前缀匹配歧义时最多列出的候选设备数喵
MAX_PREFIX_CANDIDATES = 5

# 时间轴最大缩放倍数，和看板前端的 TIMELINE_MAX_ZOOM 保持一致喵
MAX_TIMELINE_ZOOM = 8640

# 排行榜图允许的最大时间窗口：7 天，和 retention.detail_days 对齐喵
MAX_RANK_WINDOW_SECONDS = 7 * 24 * 3600


class DeviceLookupError(LookupError):
    """设备找不到或不唯一，消息本身就是给用户看的中文提示喵。"""


@dataclass(frozen=True)
class CommandContext:
    """一次命令执行的上下文喵。"""

    # 数据库连接喵
    connection: sqlite3.Connection
    # 服务端配置喵
    config: AppConfig
    # 命令名（已小写）喵
    name: str
    # 参数元组喵
    args: tuple[str, ...]
    # 基准时间喵
    now: datetime
    # 原始命令文本（已去掉前缀）喵
    raw_text: str = ""


@dataclass(frozen=True)
class Command:
    """一条命令的定义喵。"""

    # 命令标识，日志与测试里用喵
    name: str
    # 别名元组，第一个是主名喵
    aliases: tuple[str, ...]
    # 模板文本喵
    template: str
    # 数据准备函数，返回模板作用域喵
    handler: Handler
    # 帮助里的说明，空串表示不在帮助里列出喵
    summary: str = ""
    # 帮助里的用法示例喵
    usage: str = ""
    # 帮助里是否在用法下面再列一行说明，用法已写全时可以关掉喵
    show_summary: bool = True
    # 分支模板开关：作用域里这个键为真时改渲染下面那份模板喵
    alternate_flag: str = ""
    # 分支模板文本，配合 alternate_flag 使用喵
    alternate_template: str = ""

    def pick_template(self, scope: Mapping[str, Any]) -> str:
        """按作用域里的分支开关挑模板喵。

        输入：命令作用域。
        输出：要渲染的模板文本。
        边界：没配分支模板时永远返回主模板喵。
        """
        # 喵~防御：没配开关就没人能切换，直接给主模板喵
        if not self.alternate_flag:
            return self.template
        # 开关为真时走分支模板喵
        if scope.get(self.alternate_flag):
            return self.alternate_template
        return self.template


def _base_scope(context: CommandContext) -> dict[str, Any]:
    """构造所有命令共享的基础作用域喵。"""
    return {
        # 命令名与原始参数，模板里可以回显喵
        "command": context.name,
        "args": list(context.args),
        "args_text": " ".join(context.args),
        "arg1": context.args[0] if len(context.args) > 0 else "",
        "arg2": context.args[1] if len(context.args) > 1 else "",
        "now": context.now,
    }


def _parse_window_text(text: str, default_text: str) -> tuple[str, int]:
    """解析时间窗口参数，返回 (原文本, 秒数)喵。"""
    # 没给参数时用默认窗口喵
    window_text = text.strip() or default_text
    window_seconds = expr.parse_duration_text(window_text)
    # 喵~防御：写法看不懂时给明确提示，别静默按默认值跑喵
    if window_seconds is None:
        raise DeviceLookupError(f"时间窗口看不懂：{window_text}（例：1分钟 / 90秒 / 2小时）")
    # 正文里数字与单位之间留空格，读起来不挤喵
    display_text = re.sub(r"(\d)(天|小时|分钟|分|秒|周)", r"\1 \2", window_text)
    return display_text, window_seconds


# ==================== 各命令的数据准备 ====================


def _happy_help_scope(context: CommandContext) -> Mapping[str, Any]:
    """happy 帮助命令：把命令清单摊成行喵。"""
    scope = _base_scope(context)
    # 逐条命令组装帮助行喵
    rows: list[dict[str, Any]] = []
    for command in COMMANDS:
        # 喵~防御：完全不进帮助的命令（既没用法也没说明）才跳过喵
        if not command.summary and not command.usage:
            continue
        # 说明行可关：用法里已经写全参数时，再挂一行摘要就是重复喵
        summary = command.summary if command.show_summary else ""
        rows.append(
            {
                "name": command.aliases[0],
                # 用法前面留一个空格，没有用法时模板里的 {若 用法} 会整段省掉喵
                "usage": f" {command.usage}" if command.usage else "",
                "summary": summary,
                "has_summary": bool(summary),
            }
        )
    # 帮助按命令表顺序展示，不排序喵
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    scope["commands"] = rows
    scope["command_count"] = len(rows)
    return scope


def _happy_doing_scope(context: CommandContext) -> Mapping[str, Any]:
    """happy 在干嘛：三档状态各一份文案喵。"""
    scope = _base_scope(context)
    # 一次拿到状态与设备喵
    snapshot = happy.best_snapshot(context.connection, context.config, context.now)
    # 喵~注意：三档互斥，模板靠这三个开关挑分支喵
    scope["is_active"] = snapshot.state == happy.STATE_ACTIVE
    scope["is_afk"] = snapshot.state == happy.STATE_AFK
    scope["is_away"] = snapshot.state == happy.STATE_AWAY
    scope["state_reason"] = snapshot.reason
    # 该展示的设备摊平进作用域喵
    device = snapshot.device
    if device is not None:
        scope.update(
            {
                "device_name": device.name,
                "device_id": device.device_id,
                # 喵~注意：空档时长就是时间轴上那段斜纹，模板里写成「已 X 分钟没动静」喵
                "gap_seconds": device.gap_seconds or 0,
                "has_gap": bool(device.gap_seconds),
                "has_current_app": bool(device.current_app),
                "current_app": device.current_app,
                # 喵~注意：标题为空时不展示，模板靠这个布尔挑分支喵
                "has_current_title": bool(device.current_title),
                "current_title": device.current_title,
                "current_seconds": device.current_seconds,
                "has_battery": device.battery_percent is not None,
                "battery_percent": device.battery_percent or 0,
                "battery_charging": device.battery_charging,
                "is_phone": device.platform == "android",
            }
        )
    # 不在时的「最近一次上线」喵
    scope["last_usage_device"] = snapshot.last_usage_device
    scope["last_usage"] = snapshot.last_usage
    scope["has_last_usage"] = snapshot.last_usage is not None
    return scope


def _happy_done_scope(context: CommandContext) -> Mapping[str, Any]:
    """happy 干了什么：近 24 小时前 10 的应用排行喵。"""
    scope = _base_scope(context)
    # 读 happy 组喵
    devices = happy.load_happy_devices(context.connection, context.config, context.now)
    # 只在 happy 组范围内做总排行喵
    device_ids = [device.device_id for device in devices]
    rows = dataset.global_ranking_rows(
        context.connection, 0, 24 * 3600, 10, context.now, device_ids=device_ids
    )
    # 补上序号与占比，模板直接展开喵
    scope["entries"] = rows
    scope["has_entries"] = bool(rows)
    scope["entry_count"] = len(rows)
    scope["total_seconds"] = sum(int(row["seconds"]) for row in rows)
    # happy 组有几台设备也说一句喵
    scope["device_count"] = len(devices)
    scope["range_note"] = group_note(devices, happy.resolve_group_name(context.config))
    return scope


def group_note(devices: Sequence[happy.HappyDevice], group_name: str | None = None) -> str:
    """拼一句「组内有哪些设备」的说明喵。

    输入：happy 设备列表、可选组名。
    输出：形如「happy · 手机、本机 Windows」的说明。
    边界：空列表时只给组名；不传组名时用默认值喵。
    """
    # 组名缺省时退回默认值喵
    label = (group_name or happy.HAPPY_GROUP_NAME).strip() or happy.HAPPY_GROUP_NAME
    # 喵~防御：没有设备时只报组名喵
    if not devices:
        return label
    return f"{label} · " + "、".join(device.name for device in devices)


def _looks_like_time_window(text: str) -> bool:
    """判断一个参数是不是时长写法喵。

    输入：用户输入的单个参数。
    输出：形如 24小时 / 7d / 90分钟 时返回 True。
    边界：借用 expr 的时长解析，认不出就是 False喵。
    """
    # 带引号的形式先解析成秒，解析得出就算时长喵
    return expr.parse_duration_text(text.strip()) is not None


def _parse_happy_scope(text: str, context: CommandContext) -> tuple[str, list[str], str]:
    """解析「全部」或设备名/ID 前缀喵。

    输入：范围文本、执行上下文。
    输出：(展示文案, 设备 ID 列表, 范围说明)。
    边界：空文本与「全部」都表示 happy 组；找不到设备时抛 DeviceLookupError喵。
    """
    # 先读 happy 组，作为「全部」的答案喵
    devices = happy.load_happy_devices(context.connection, context.config, context.now)
    # 当前生效的组名喵
    group_name = happy.resolve_group_name(context.config)
    # 去掉空白喵
    cleaned = text.strip()
    # 喵~防御：没写或写了「全部」都按主人组处理喵
    if not cleaned or cleaned in ("全部", "所有", "all") or "全部".startswith(cleaned.lower()):
        return group_name, [device.device_id for device in devices], group_note(devices, group_name)
    # 先按设备名做精确匹配，再按设备名做前缀匹配喵
    for device in devices:
        if device.name.strip().lower() == cleaned.lower():
            return device.name, [device.device_id], device.name
    # 喵~注意：「本机」要能匹配到「本机 Windows」这种带后缀的名字喵
    name_candidates = [device for device in devices if device.name.strip().lower().startswith(cleaned.lower())]
    if len(name_candidates) == 1:
        return name_candidates[0].name, [name_candidates[0].device_id], name_candidates[0].name
    # 再按 ID 前缀匹配喵
    candidates = [device for device in devices if device.device_id.lower().startswith(cleaned.lower())]
    if len(candidates) == 1:
        return candidates[0].name, [candidates[0].device_id], candidates[0].name
    # 喵~防御：前缀命中多台时列出来，不能瞎猜喵
    ambiguous = name_candidates + [device for device in candidates if device not in name_candidates]
    if len(ambiguous) > 1:
        shown = "、".join(device.name for device in ambiguous[:MAX_PREFIX_CANDIDATES])
        raise DeviceLookupError(f"「{cleaned}」匹配到 {len(ambiguous)} 台设备：{shown}，请写完整一点。")
    # 都没命中时把可用设备列出来喵
    available = "、".join(device.name for device in devices)
    raise DeviceLookupError(f"「{cleaned}」在{group_name}组里找不到。可用：全部、{available}")


def _look_rank_scope(context: CommandContext) -> Mapping[str, Any]:
    """看看happy 排行榜：按时间窗口出图喵。"""
    scope = _base_scope(context)
    # 第一个参数是范围喵
    range_text = context.args[0] if context.args else ""
    range_label, device_ids, range_note = _parse_happy_scope(range_text, context)
    # 喵~注意：第二个参数是子命令名「排行榜」，时间窗口要从第三个开始找喵
    window_text, window_seconds = _parse_window_text(
        context.args[2] if len(context.args) > 2 else "", "24小时"
    )
    # 喵~防御：窗口夹到 7 天，和看板保留期对齐喵
    if window_seconds > MAX_RANK_WINDOW_SECONDS:
        window_seconds = MAX_RANK_WINDOW_SECONDS
        window_text = "7 天"
    # 组装作用域喵
    scope.update(
        {
            "window": window_text,
            "window_seconds": window_seconds,
            "range_label": range_label,
            "range_note": range_note,
            "device_ids": device_ids,
            "device_count": len(device_ids),
            # 模板里统一用「时间窗口」这个词喵
            "window_text": window_text,
        }
    )
    return scope


def _look_happy_scope(context: CommandContext) -> Mapping[str, Any]:
    """看看happy：按第二个参数分流到排行榜或时间轴喵。

    输入：执行上下文，参数形如 `<范围> <排行榜/时间轴> [更多]`。
    输出：对应分支的模板作用域，带 kind 标记供命令表挑模板。
    边界：第二个参数缺失或认不出时抛 DeviceLookupError，列出两种写法喵。
    """
    # 喵~防御：至少要有范围和子命令两个参数喵
    if len(context.args) < 2:
        raise DeviceLookupError(
            "用法：/看看happy <全部/设备名> <排行榜/时间轴> [参数]\n"
            "例如：/看看happy 全部 排行榜 7天\n"
            "例如：/看看happy 手机 时间轴 09:00 12:00"
        )
    # 第二个参数决定走哪条分支喵
    sub = context.args[1].strip().lower()
    # 排行榜分支喵
    if sub in ("排行榜", "排行", "rank", "ranking"):
        return _look_rank_scope(context)
    # 时间轴分支喵
    if sub in ("时间轴", "timeline"):
        return _look_timeline_scope(context)
    # 喵~防御：认不出的子命令要提示清楚喵
    raise DeviceLookupError(f"看不懂「{context.args[1]}」，第二个参数只能是「排行榜」或「时间轴」。")


def _look_timeline_scope(context: CommandContext) -> Mapping[str, Any]:
    """看看happy 时间轴：按日期或起止时刻出图喵。

    不支持跨天：看板时间轴一页就是一天，跨天要分两张图，
    与其悄悄只画第一天，不如直接报错让主人分开查喵。
    """
    scope = _base_scope(context)
    # 第一个参数是范围喵
    range_text = context.args[0] if context.args else ""
    range_label, device_ids, range_note = _parse_happy_scope(range_text, context)
    # 剩下的参数里挑日期与时刻喵，喵~注意跳过第二个参数（子命令名）喵
    rest = list(context.args[2:])
    day_text = ""
    moment_args: list[str] = []
    for argument in rest:
        # 喵~防御：只有长得像日期的才算日期喵
        if _looks_like_date(argument):
            day_text = argument
            continue
        moment_args.append(argument)
    # 起始日期，默认今天喵
    start = _parse_day_text(day_text, context)
    # 喵~防御：时刻最多两个喵
    if len(moment_args) > 2:
        raise DeviceLookupError("时间轴最多写起止两个时刻，例如 /看看happy 全部 时间轴 09:00 12:00")
    # 没写时刻时截到「当前时刻 +10 分钟」，但不越过当天末尾喵
    start_text = moment_args[0] if moment_args else ""
    end_text = moment_args[1] if len(moment_args) > 1 else ""
    # 喵~注意：不给窗口时也要有个默认终点，让图只画到今天为止喵
    if not start_text:
        moment_start = "00:00"
        moment_end = _default_timeline_end(context, start)
    else:
        moment_start = start_text
        moment_end = end_text or _default_timeline_end(context, start)
    # 喵~防御：截止必须晚于起点，否则画不出来喵
    if _clock_minutes(moment_end) <= _clock_minutes(moment_start):
        raise DeviceLookupError(
            f"时间轴截止要晚于起点：{moment_start} → {moment_end}（例：09:00 12:00）"
        )
    # 组装作用域喵
    scope.update(
        {
            "range_label": range_label,
            "range_note": range_note,
            "device_ids": device_ids,
            "device_count": len(device_ids),
            "start": start,
            "start_text": start.astimezone().strftime("%Y-%m-%d"),
            "moment_start": moment_start,
            "moment_end": moment_end,
            "has_window": bool(start_text),
            # 喵~注意：模板里「时间窗口」取的是 window_text，时间轴这边把起止时刻
            # 填进去，出错文案才能把「09:00-12:00」这段说出来喵
            "window_text": f"{moment_start}-{moment_end}" if start_text else "",
            # 标记走时间轴分支的文案喵
            "is_timeline": True,
        }
    )
    return scope


def _default_timeline_end(context: CommandContext, day_start: datetime) -> str:
    """算时间轴的默认截止时刻：当前时刻 +10 分钟，封顶 23:59喵。

    输入：执行上下文、当天的 UTC 零点。
    输出：HH:MM 文本。
    边界：查的日期不是今天时直接给 23:59，因为那天已经过完了喵。
    """
    # 服务器本地时区喵
    local_tz = context.now.astimezone().tzinfo or timezone.utc
    # 这一天的本地零点喵
    day_local = day_start.astimezone(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    # 现在时刻喵
    now_local = context.now.astimezone(local_tz)
    # 喵~防御：查的不是今天就画满一天喵
    if day_local.date() != now_local.date():
        return "23:59"
    # 当前时刻往后推 10 分钟喵
    target = now_local + timedelta(minutes=10)
    # 喵~防御：越过当天末尾就封顶喵
    if target.date() != now_local.date():
        return "23:59"
    return target.strftime("%H:%M")


def _happy_device_scope(context: CommandContext) -> Mapping[str, Any]:
    """happy 设备：happy 组每台设备一行喵。"""
    scope = _base_scope(context)
    # 读 happy 组喵
    devices = happy.load_happy_devices(context.connection, context.config, context.now)
    # 逐台组装展示行喵
    rows: list[dict[str, Any]] = []
    for device in devices:
        # 状态文字：在线/离线喵
        status = "在线" if device.online else "离线"
        # 喵~注意：手机离线时要给「最后电量」，在线时直接给电量喵
        has_battery = device.battery_percent is not None
        rows.append(
            {
                "rank": device.priority + 1,
                "name": device.name,
                "id": device.device_id,
                "status": status,
                "online": device.online,
                # 离线时模板要显示「上次在线」，用这个开关控制喵
                "is_offline": not device.online,
                "last_seen": device.last_seen,
                "has_battery": has_battery,
                "battery_percent": device.battery_percent or 0,
                "battery_charging": device.battery_charging,
                # 离线时电量要写成「最后电量」喵
                "battery_label": "电量" if device.online else "最后电量",
                # 喵~注意：挂机时写「挂机」，在用就直接写最近上报的应用名，
                # 不再统一显示「活跃软件」这个泛称，主人要看的是具体软件喵
                "mode_text": "挂机" if device.afk else (device.current_app or "活跃软件"),
                "usage_24h": device.usage_24h_seconds,
                "is_phone": device.platform == "android",
                "current_app": device.current_app,
                "current_seconds": device.current_seconds,
                "has_current_app": bool(device.current_app),
            }
        )
    scope["devices"] = rows
    scope["device_count"] = len(rows)
    scope["has_devices"] = bool(rows)
    # 组名从配置读，模板里用 {组名} 展示喵
    scope["group_name"] = happy.resolve_group_name(context.config)
    scope["range_note"] = group_note(devices, happy.resolve_group_name(context.config))
    return scope



def _looks_like_date(text: str) -> bool:
    """判断一个参数是不是日期写法喵。

    输入：用户输入的单个参数。
    输出：形如 2026-11-01 或 2026/11/01 时返回 True。
    边界：纯数字（例如页码）不算日期，避免误判喵。
    """
    # 只认带分隔符的三段式写法喵
    return re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text.strip()) is not None


def _parse_day_text(text: str, context: CommandContext) -> datetime:
    """把日期文本解析成当天零点（本地时区）喵。

    输入：`YYYY-MM-DD` 或空（表示今天）、执行上下文。
    输出：UTC 的窗口起点。
    边界：格式不对时抛 DeviceLookupError；也接受 `YYYY/MM/DD`喵。
    """
    # 服务器本地时区喵
    local_tz = context.now.astimezone().tzinfo or timezone.utc
    # 喵~防御：空文本表示今天喵
    cleaned = text.strip()
    if not cleaned:
        local_now = context.now.astimezone(local_tz)
        return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    # 解析 `YYYY-MM-DD`，也接受 `YYYY/MM/DD`喵
    normalized = cleaned.replace("/", "-")
    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as error:
        raise DeviceLookupError(f"日期看不懂：{cleaned}（格式：2026-11-01）") from error
    return parsed.replace(tzinfo=local_tz).astimezone(timezone.utc)


def _clock_minutes(text: str) -> int:
    """把 HH:MM 换算成当天第几分钟喵。

    输入：用户写的时刻文本（不保证合法）。
    输出：0–1439 的分钟数。
    边界：格式不对、时或分越界时抛 DeviceLookupError喵。

    喵~注意：这里原来是 `hour_text, minute_text = text.split(":", 1)`，
    默认「调用方保证格式合法」——但调用方**从来不校验**。
    用户打「0900」「9点」「abc」时这行直接 `ValueError: not enough values to unpack`，
    而这个异常不在 `router` 的兜底里，结果群里一个字都不回，
    `/api/v1/bot/command` 还返 500喵。所以校验必须做在这里。
    """
    # 去掉空白再拆喵
    cleaned = text.strip()
    # 喵~防御：只认 H:MM 或 HH:MM 这种带冒号的写法喵
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", cleaned)
    if match is None:
        raise DeviceLookupError(
            f"时刻看不懂：{cleaned}（格式：09:00，要带冒号）"
        )
    # 拆出时与分喵
    hour_value = int(match.group(1))
    minute_value = int(match.group(2))
    # 喵~防御：25:00 / 12:60 这种越界值必须挡住，否则会截出一段空白天喵
    if hour_value > 23 or minute_value > 59:
        raise DeviceLookupError(
            f"时刻超出范围：{cleaned}（小时 00–23，分钟 00–59）"
        )
    # 换算成当天第几分钟喵
    return hour_value * 60 + minute_value


def zoom_for_window(start_text: str, end_text: str) -> int:
    """按自定义窗口反算「铺满视口」需要的缩放倍数喵。

    看板时间轴一页固定是 24 小时，画布宽度 = 视口宽度 × 倍率。
    想让 [start, end] 这段正好占满一屏，倍率就是 1440 / 窗口分钟数。

    输入：起始与截止时刻（HH:MM）。
    输出：夹到 1–MAX_TIMELINE_ZOOM 的倍数；窗口不合法时返回 0 表示不缩放。
    边界：截止不晚于起始、或窗口不足 1 分钟时返回 0，由调用方报错喵。
    """
    # 换算成分钟喵
    start_minutes = _clock_minutes(start_text)
    end_minutes = _clock_minutes(end_text)
    # 喵~防御：窗口必须为正喵
    span = end_minutes - start_minutes
    if span <= 0:
        return 0
    # 一天 1440 分钟，窗口越短倍率越大喵
    return max(1, min(MAX_TIMELINE_ZOOM, round(1440 / span)))


# ==================== 片段：可复用的文案积木 ====================
FRAGMENTS: dict[str, str] = {
    # 排行榜里的一行喵
    "排行行": "{序号}. {应用} — {时长|时长}（{占比|百分比}）",
    # 帮助里的一行喵
    # 帮助里的一行：命令名 + 用法，有说明时再缩进一行喵
    "帮助行": "/{名称}{用法}{若 有说明}\n    {说明}{/若}",    # 设备清单里的一台设备喵
    "happy设备块": """{名称}·{状态}{若 离线}·上次在线 {最近上报|相对}{/若}{若 有电量}·{电量标签} {电量|数字}%{/若}
{模式说明}·设备近24小时使用 {近24小时|时长}""",
}


# ==================== 命令表 ====================


COMMANDS: tuple[Command, ...] = (
    Command(
        name="happy帮助",
        aliases=("happy帮助", "happyhelp"),
        summary="看看可以查询happy哪些信息",
        template="""{查询 当前 列表=命令列表 行=帮助行}""",
        handler=_happy_help_scope,
    ),
    Command(
        name="happy在干嘛",
        aliases=("happy在干嘛", "happydoing"),
        summary="看看 happy 现在在做什么",
        # 喵~注意：三档状态各一份文案，靠三个互斥开关挑分支。原来只有
        # 「主模板 + alternate」两个槽位，挂机那档会错走主模板说「正在使用」，
        # 「不在」那档的开头偏偏写的是「正在挂机」，两档口径全错喵
        # 喵~注意：三个 {若} 必须紧挨着写，中间不能换行，否则空档会多出空行喵
        template="""{若 正在使用}happy正在使用{设备名}
当前应用: {当前应用}{若 当前应用时长}（已持续 {当前应用时长|时长}）{/若}{若 有标题}
{标题}{/若}{若 有电量}
设备剩余电量：{电量|数字}%{/若}{/若}{若 挂机}happy正在挂机...? 可能在处理事情
最近使用: {设备名}
当前应用: {当前应用}{若 有标题}
{标题}{/若}{若 是手机}{若 有电量}
手机剩余电量：{电量|数字}%{/若}{/若}{/若}{若 不在}happy不在诶...
{若 有最近一次上线}最近一次使用: {最近使用} · {最近一次上线|相对}
已经 {空档时长|时长}没有动静{否则}组内设备都还没有使用记录，客户端还没报过使用时长{/若}{/若}""",
        handler=_happy_doing_scope,
    ),
    Command(
        name="happy干了什么",
        aliases=("happy干了什么", "happydone"),
        summary="看看 happy 近 24 小时用了什么",
        template="""近24小时内 happy使用了下面的东西（{范围说明}）

{查询 当前 列表=应用列表 行=排行行 空="近 24 小时没有使用记录。"}""",
        handler=_happy_done_scope,
    ),
    Command(
        name="happy设备",
        aliases=("happy设备", "happydevices"),
        summary="看看 happy 名下各台设备的状态",
        template="""happy 的设备

{查询 当前 列表=设备列表 行=happy设备块 空="{设备组名}组里还没有设备。"}""",
        handler=_happy_device_scope,
    ),
    Command(
        name="看看happy",
        aliases=("看看happy", "lookhappy"),
        # 喵~注意：用法里已经写明参数格式，帮助里不必再重复一行摘要喵
        summary="",
        show_summary=False,
        # 喵~注意：时间范围的写法直接嵌在用法里，参数格式要一眼能抄喵
        # 设备：全部 = happy 组所有设备合并；也可写设备名或名称前缀（本机、手机），
        #       或者设备 ID 前缀（win-、and-），只认 happy 组里的设备喵
        # 排行榜 [时间范围]：默认近 24 小时，可写 30分钟 / 2小时 / 6小时 / 1天 / 3天 / 7天，
        #       超过 7 天按 7 天算喵
        # 时间轴 [起止时刻]：默认今天全天到此刻；可只写日期（2026-11-01），
        #       也可再补起止时刻（09:00 12:00），给了时刻就自动放大到那一段喵
        usage=""" <全部/设备名> <排行榜/时间轴> [时间范围/起止时刻]
    设备：全部 / 本机 / 手机 / 设备 ID 前缀（win-、and-）
    排行榜 [时间范围]：24小时（默认）/ 30分钟 / 2小时 / 6小时 / 1天 / 3天 / 7天，上限 7 天
    时间轴 [起止时刻]：今天（默认，到此刻）/ 2026-11-01 / 2026-11-01 09:00 12:00
    例：/看看happy 全部 排行榜 6小时
        /看看happy 手机 时间轴 09:00 12:00""",
        template="""查看 happy 最近 {时间窗口} 的应用排行

这次排行图片没能生成出来，稍后再发一次试试吧。""",
        handler=_look_happy_scope,
        # 时间轴分支换一份文案，靠 kind 标记切换喵
        alternate_flag="is_timeline",
        alternate_template="""查看 happy {起始日期}{若 时间窗口} {时间窗口}{/若} 的时间轴

这次时间轴图片没能生成出来，稍后再发一次试试吧。""",
    ),
)


def command_by_name(name: str) -> Command | None:
    """按命令名或别名查找命令，大小写不敏感喵。

    输入：用户输入的命令名。
    输出：命中的 Command，找不到时返回 None。
    边界：全角问号等别名同样能命中喵。
    """
    # 统一小写比较喵
    lowered = name.strip().lower()
    for command in COMMANDS:
        if lowered in (alias.lower() for alias in command.aliases):
            return command
    return None


def fragment_nodes() -> dict[str, tuple[Any, ...]]:
    """把所有片段解析成节点树，供渲染环境使用喵。

    输入：无。
    输出：片段名到节点树的映射。
    边界：片段语法错误会在这里抛出 TemplateError，属于开发期错误喵。
    """
    # 逐条解析，解析失败时把片段名带进错误消息里喵
    parsed: dict[str, tuple[Any, ...]] = {}
    for name, text in FRAGMENTS.items():
        try:
            parsed[name] = expr.parse(text).nodes
        except expr.TemplateError as error:
            raise expr.TemplateError(f"片段「{name}」语法错误：{error}") from error
    return parsed
