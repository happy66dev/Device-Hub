"""模板表达式：占位符解析与求值。

职责边界：
- 把模板文本解析成节点树（纯函数，不碰数据库、不碰文件、不碰配置）；
- 在作用域链上求值，拼出最终文本；
- 提供格式化器（时长、百分比、相对时间……）。
取数据由 dataset 模块负责，这里只认普通字典与列表喵。

语法一览（全部写在代码里的模板字符串中）：
- {名称}           取变量；
- {名称|时长}      变量 + 格式化器，格式化器可带参数如 {名称|截断(8)}；
- {若 有电量}…{否则}…{/若}  条件，可嵌套；
- {>设备行}        引用片段，片段共享当前作用域；
- {查询 设备 有使用=1分钟 前=5 行=设备行 空=没有设备}  查询并循环；
- {{ 与 }}         转义成字面量花括号。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

# 模块日志器，用于提示模板里写错的占位符喵
LOGGER = logging.getLogger("device_hub.bot")

# 片段与嵌套查询的最大深度，防止写出互相引用的死循环喵
MAX_DEPTH = 6

# 已经告警过的占位符路径，同一个只提示一次，避免刷屏喵
_WARNED_PATHS: set[str] = set()

# 变量取值失败的哨兵，用来区分「值就是空串」与「这个变量不存在」喵
MISSING = object()

# 中文变量名到真实字段名的别名表，主人写中文、代码里存英文喵
ALIASES: dict[str, str] = {
    # 通用
    "现在": "now",
    "窗口": "window",
    # 设备行
    "名称": "name",
    "设备名": "name",
    "ID": "id",
    "设备ID": "id",
    "平台": "platform",
    "系统版本": "os_version",
    "状态": "status",
    "在线": "online",
    "角色": "role",
    "角色说明": "role_text",
    "RDP状态": "rdp_text",
    "暂停说明": "paused_text",
    "最近上报": "last_seen",
    "有电量": "has_battery",
    "电量": "battery_percent",
    "充电状态": "battery_text",
    "有当前应用": "has_current_app",
    "当前应用": "current_app",
    # 喵~注意：窗口标题只有 Windows 端会上报，安卓端恒为空喵
    "有标题": "has_current_title",
    "标题": "current_title",
    "有硬件": "has_hardware",
    "硬件": "hardware",
    "使用时长": "usage_total",
    "设备数": "device_count",
    # 排行行
    "应用": "app",
    "包名": "package",
    "时长": "seconds",
    "占比": "percent",
    "序号": "rank",
    "设备": "device",
    "设备列表": "devices",
    # 分页
    "页码": "page",
    "总页数": "total_pages",
    "总应用数": "total_apps",
    "有上一页": "has_prev",
    "有下一页": "has_next",
    "上一页页码": "prev_page",
    "下一页页码": "next_page",
    # 命令参数
    "参数": "args_text",
    "参数1": "arg1",
    "参数2": "arg2",
    "命令": "command",
    # 命令级汇总
    "总时长": "total_usage",
    "总应用数": "total_apps",
    # 帮助行
    "用法": "usage",
    "说明": "summary",
    "有说明": "has_summary",
    # 作用域里的现成列表，供 {查询 当前 列表=…} 使用喵
    "设备列表": "devices",
    "命令列表": "commands",
    "排行列表": "entries",
    "窗口应用": "top_apps",
    "有窗口应用": "has_top_apps",
    # 命令级汇总
    "有设备": "has_devices",
    "有排行": "has_entries",
    # 图命令用的范围与日期喵
    "范围说明": "range_note",
    "范围": "range_label",
    "起始日期": "start_text",
    "截止日期": "end_text",
    # 时间轴缩放与定位喵
    "缩放倍数": "zoom_text",
    "时刻": "clock",
    # 喵~注意：不能再叫「窗口」，那个名字已经被「谁在用」占用指向 window 喵
    "时间窗口": "window_text",
    # happy 系列喵
    "设备名": "device_name",
    "当前应用": "current_app",
    "当前应用时长": "current_seconds",
    "有当前应用": "has_current_app",
    # 喵~注意：这里的「标题」指当前应用窗口标题，安卓端不采集所以恒为空喵
    "有标题": "has_current_title",
    "标题": "current_title",
    "有电量": "has_battery",
    "电量": "battery_percent",
    "充电状态": "battery_charging",
    "电量标签": "battery_label",
    "是手机": "is_phone",
    "离线": "is_offline",
    "最近上报时间": "last_seen_text",
    "模式说明": "mode_text",
    "近24小时": "usage_24h",
    "状态": "status",
    "名称": "name",
    "设备组名": "group_name",
    "应用列表": "entries",
    "最近使用": "last_usage_device",
    "最近一次上线": "last_usage",
    "有最近一次上线": "has_last_usage",
    # 三档状态开关喵
    "正在使用": "is_active",
    "挂机": "is_afk",
    "不在": "is_away",
    # 空档时长：时间轴上那段斜纹有多长喵
    "空档": "gap_seconds",
    "空档时长": "gap_seconds",
    "有空档": "has_gap",
    # 命令计数喵
    "命令数": "command_count",
    "设备数": "device_count",
}

# 路径切分：按点与下标拆成一段一段喵
_PATH_PATTERN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

# 时长文本的切分，支持「1分钟」「30秒」「2小时」「7天」喵
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(天|小时|分钟|分|秒|周)")

# 各时间单位换算成秒喵
_DURATION_UNITS: dict[str, int] = {
    "周": 7 * 86400,
    "天": 86400,
    "小时": 3600,
    "分钟": 60,
    "分": 60,
    "秒": 1,
}


class TemplateError(ValueError):
    """模板语法错误，消息里带出错位置，方便主人一眼定位喵。"""

    def __init__(self, message: str, position: int = -1) -> None:
        # 带上字符位置，模板长了也能找到喵
        suffix = f"（第 {position + 1} 个字符附近）" if position >= 0 else ""
        super().__init__(f"{message}{suffix}")


class QueryError(ValueError):
    """查询占位符的参数不合法（数据集名错、字段名错等）喵。"""


class RenderEnv(Protocol):
    """渲染时需要的环境：片段表与查询执行器喵。"""

    def fragment(self, name: str) -> tuple[Any, ...] | None:
        """按名字取片段节点树，取不到返回 None 喵。"""
        ...

    def query(self, dataset: str, options: Mapping[str, str], scopes: Sequence[Mapping[str, Any]], depth: int) -> Any:
        """执行一次查询，返回列表或聚合值喵。"""
        ...


@dataclass(frozen=True)
class Template:
    """解析后的模板，节点树本身是不可变的喵。"""

    # 顶层节点喵
    nodes: tuple[Any, ...]
    # 原文本，报错与预览时用喵
    source: str = ""


@dataclass(frozen=True)
class Formatter:
    """格式化器：名字 + 可选参数喵。"""

    # 格式化器名，例如「时长」喵
    name: str
    # 参数原文，例如「8」；没有参数时为空串喵
    argument: str = ""


@dataclass(frozen=True)
class VarNode:
    """变量占位符 {名称|格式化器} 喵。"""

    # 变量路径喵
    path: str
    # 格式化器，没有时为空喵
    formatter: Formatter | None


@dataclass(frozen=True)
class IfNode:
    """条件块 {若 x}…{否则}…{/若} 喵。"""

    # 条件变量路径喵
    path: str
    # 条件成立时的节点喵
    body: tuple[Any, ...]
    # 条件不成立时的节点喵
    otherwise: tuple[Any, ...]


@dataclass(frozen=True)
class FragmentNode:
    """片段引用 {>片段名} 喵。"""

    # 片段名喵
    name: str


@dataclass(frozen=True)
class QueryNode:
    """查询占位符 {查询 数据集 键=值 …} 喵。"""

    # 数据集名喵
    dataset: str
    # 选项键值对，保留书写顺序喵
    options: tuple[tuple[str, str], ...]


def parse_duration_text(text: str) -> int | None:
    """把「1分钟」「30秒」「2小时」这类文本换成秒数喵。

    输入：时长文本，可能带空格。
    输出：秒数；解析不出来时返回 None。
    边界：多个单位相加，例如「1小时30分」= 5400 秒喵。
    """
    # 喵~防御：空文本没有可解析的内容喵
    if not isinstance(text, str) or not text.strip():
        return None
    # 逐个匹配单位并累加喵
    total_seconds = 0.0
    matched = False
    for amount, unit in _DURATION_PATTERN.findall(text):
        # 单位换算成秒喵
        total_seconds += float(amount) * _DURATION_UNITS[unit]
        matched = True
    # 喵~防御：一个单位都没匹配上说明写法不对喵
    if not matched:
        return None
    # 取整返回，向上取整避免「0.5 秒」变成 0 喵
    return max(0, int(total_seconds + 0.5))


def _flush(buffer: list[str], nodes: list[Any]) -> None:
    """把缓冲区里的文本收成一个文本节点喵。"""
    # 空缓冲不产生节点，免得节点树里全是空串喵
    if not buffer:
        return
    # 合并成一段文本喵
    nodes.append("".join(buffer))
    # 清空缓冲喵
    buffer.clear()


def _parse_variable(inner: str) -> VarNode:
    """解析变量占位符的内部内容喵。"""
    # 有竖线说明带格式化器喵
    if "|" in inner:
        path_text, formatter_text = inner.split("|", 1)
        # 格式化器名与参数喵
        formatter_text = formatter_text.strip()
        if "(" in formatter_text and formatter_text.endswith(")"):
            formatter_name, argument = formatter_text[:-1].split("(", 1)
            formatter = Formatter(name=formatter_name.strip(), argument=argument.strip())
        else:
            formatter = Formatter(name=formatter_text)
        # 喵~防御：格式化器名不能为空喵
        if not formatter.name:
            raise TemplateError("占位符的格式化器不能为空")
        # 返回带格式化器的变量节点喵
        return VarNode(path=path_text.strip(), formatter=formatter)
    # 没有格式化器喵
    return VarNode(path=inner.strip(), formatter=None)


def _split_options(text: str) -> list[str]:
    """按空白切分查询参数，双引号里的空格不切喵。"""
    # 收集当前片段喵
    tokens: list[str] = []
    buffer: list[str] = []
    quote = ""
    # 逐字符扫描喵
    for char in text:
        # 引号内原样收下喵
        if quote:
            if char == quote:
                quote = ""
            else:
                buffer.append(char)
            continue
        # 遇到引号开始引用喵
        if char in ("\"", "'"):
            quote = char
            continue
        # 空白作为分隔符，全角空格同样处理喵
        if char.isspace() or char == "\u3000":
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()
            continue
        # 普通字符收进缓冲喵
        buffer.append(char)
    # 喵~防御：引号没闭合说明模板写错了喵
    if quote:
        raise TemplateError("查询参数里的引号没有闭合")
    # 收尾喵
    if buffer:
        tokens.append("".join(buffer))
    return tokens


def _parse_query(inner: str) -> QueryNode:
    """解析查询占位符的内部内容喵。"""
    # 去掉关键字，剩下的第一个词是数据集名喵
    tokens = _split_options(inner[len("查询") :].strip())
    # 喵~防御：没写数据集名喵
    if not tokens:
        raise TemplateError("查询占位符缺少数据集名，例如 {查询 设备 前=5 行=设备行}")
    # 数据集名喵
    dataset = tokens[0]
    # 逐项解析键值对喵
    options: list[tuple[str, str]] = []
    for token in tokens[1:]:
        # 等号分隔键与值喵
        if "=" in token:
            key, value = token.split("=", 1)
            options.append((key.strip(), value.strip()))
            continue
        # 没有等号的是开关式关键字，例如 倒序 / 计数 喵
        options.append((token.strip(), ""))
    # 返回查询节点喵
    return QueryNode(dataset=dataset, options=tuple(options))


def _find_closing_brace(text: str, start: int) -> int:
    """从左侧花括号之后开始找配对的右花括号喵。

    输入：模板全文、左花括号的位置。
    输出：配对右花括号的下标；找不到时返回 -1。
    边界：允许占位符内部再嵌一层 `{变量}`（查询选项里常用），按层数配对喵。
    """
    depth = 0
    index = start + 1
    while index < len(text):
        char = text[index]
        # 嵌套的左花括号计数加一喵
        if char == "{":
            depth += 1
            index += 1
            continue
        # 右花括号优先抵消嵌套喵
        if char == "}":
            if depth == 0:
                return index
            depth -= 1
            index += 1
            continue
        index += 1
    # 喵~防御：走到结尾都没配上，交给调用方报错喵
    return -1


def _parse_nodes(text: str, start: int, depth: int) -> tuple[tuple[Any, ...], int, str]:
    """从 start 开始解析节点，返回 (节点, 新位置, 结束标记)喵。"""
    # 喵~防御：嵌套太深说明模板写成了递归引用喵
    if depth > MAX_DEPTH:
        raise TemplateError(f"模板嵌套超过 {MAX_DEPTH} 层")
    nodes: list[Any] = []
    buffer: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        # 转义的左花括号喵
        if text.startswith("{{", index):
            buffer.append("{")
            index += 2
            continue
        # 转义的右花括号喵
        if text.startswith("}}", index):
            buffer.append("}")
            index += 2
            continue
        # 普通右花括号当字面量喵
        if char == "}":
            buffer.append(char)
            index += 1
            continue
        # 不是左花括号就是普通文本喵
        if char != "{":
            buffer.append(char)
            index += 1
            continue
        # 找到配对的右花括号，支持在查询选项里再嵌一层占位符喵
        close = _find_closing_brace(text, index)
        if close < 0:
            raise TemplateError("占位符缺少右花括号 }", index)
        inner = text[index + 1 : close].strip()
        index = close + 1
        # 喵~防御：空的占位符没有意义喵
        if not inner:
            raise TemplateError("出现了空的占位符 {}", index)
        # 结束标记喵
        if inner.startswith("/"):
            _flush(buffer, nodes)
            tag = inner[1:].strip()
            if tag != "若":
                raise TemplateError(f"不认识的结束标记 {{/{tag}}}", index)
            return tuple(nodes), index, "若"
        # 否则分支喵
        if inner == "否则":
            _flush(buffer, nodes)
            return tuple(nodes), index, "否则"
        # 条件块喵
        if inner.startswith("若 ") or inner.startswith("若\u3000"):
            _flush(buffer, nodes)
            condition = inner[1:].strip()
            if not condition:
                raise TemplateError("条件块缺少变量名", index)
            body, index, terminator = _parse_nodes(text, index, depth + 1)
            otherwise: tuple[Any, ...] = ()
            if terminator == "否则":
                otherwise, index, terminator = _parse_nodes(text, index, depth + 1)
            if terminator != "若":
                raise TemplateError("{若 没有对应的 {/若}", index)
            nodes.append(IfNode(path=condition, body=body, otherwise=otherwise))
            continue
        # 片段引用喵
        if inner.startswith(">"):
            _flush(buffer, nodes)
            name = inner[1:].strip()
            if not name:
                raise TemplateError("片段引用缺少片段名", index)
            nodes.append(FragmentNode(name=name))
            continue
        # 查询喵
        if inner.startswith("查询 ") or inner.startswith("查询\u3000"):
            _flush(buffer, nodes)
            nodes.append(_parse_query(inner))
            continue
        # 其余都是变量喵
        _flush(buffer, nodes)
        nodes.append(_parse_variable(inner))
    # 正常读到结尾喵
    _flush(buffer, nodes)
    return tuple(nodes), index, ""


def parse(text: str) -> Template:
    """把模板文本解析成节点树喵。

    输入：模板文本。
    输出：Template。
    边界：语法错误抛 TemplateError，位置带在消息里喵。
    """
    # 喵~防御：非字符串直接拒绝，避免上游传错类型喵
    if not isinstance(text, str):
        raise TemplateError(f"模板必须是字符串，实际是 {type(text).__name__}")
    # 解析顶层节点喵
    nodes, _end, terminator = _parse_nodes(text, 0, 0)
    # 喵~防御：顶层出现结束标记说明 {若 没写喵
    if terminator:
        raise TemplateError("{否则 或 {/若} 没有对应的 {若}")
    return Template(nodes=nodes, source=text)


def _walk(value: Any, segments: list[str | int]) -> Any:
    """沿路径逐段取值喵。"""
    current = value
    for segment in segments:
        # 喵~防御：中途断了就返回哨兵，交给上层决定怎么显示喵
        if current is MISSING or current is None:
            return MISSING
        # 下标取值喵
        if isinstance(segment, int):
            if isinstance(current, (list, tuple)) and 0 <= segment < len(current):
                current = current[segment]
                continue
            return MISSING
        # 字典取值喵
        if isinstance(current, Mapping):
            current = current.get(segment, MISSING)
            continue
        # 对象取属性喵
        if hasattr(current, segment):
            current = getattr(current, segment)
            continue
        return MISSING
    return current


def _path_segments(path: str) -> list[str | int]:
    """把路径文本拆成段，支持 a.b 与 a[0] 两种写法喵。"""
    segments: list[str | int] = []
    for name_part, index_part in _PATH_PATTERN.findall(path):
        # 名字段喵
        if name_part:
            segments.append(name_part.strip())
            continue
        # 下标的段喵
        if index_part:
            segments.append(int(index_part))
    return segments


def resolve(path: str, scopes: Sequence[Mapping[str, Any]]) -> Any:
    """在作用域链上解析一个变量路径喵。

    输入：路径文本与作用域链（最内层在前）。
    输出：取到的值；取不到时返回 MISSING。
    边界：别名优先，中文名写错会逐层尝试后返回 MISSING 喵。
    """
    # 别名先翻译一次，中文写法与英文写法等价喵
    normalized = ALIASES.get(path, path)
    # 拆成段喵
    segments = _path_segments(normalized)
    # 喵~防御：空路径没有意义喵
    if not segments:
        return MISSING
    # 第一段在作用域链上找，内层优先喵
    head = segments[0]
    for scope in scopes:
        if isinstance(head, str) and isinstance(scope, Mapping) and head in scope:
            return _walk(scope[head], segments[1:])
    # 整条路径当成别名再试一次，支持「最近上报.小时」这种组合喵
    if normalized != path and path in ALIASES:
        return MISSING
    return MISSING


def format_duration(total_seconds: Any) -> str:
    """把秒数格式化成人类可读的时长喵。

    输入：秒数，允许为 0 或负数。
    输出：如 "45 秒"、"3 分 20 秒"、"2 小时 5 分"。
    边界：负数按 0 处理；不足 1 分钟不显示"0 分"喵。
    """
    # 喵~防御：负数或非数字输入统一按 0 处理，避免出现 "-5 秒" 这种怪结果喵
    try:
        safe_seconds = max(0, int(total_seconds))
    except (TypeError, ValueError):
        return "0 秒"
    # 不足一分钟只显示秒喵
    if safe_seconds < 60:
        return f"{safe_seconds} 秒"
    # 不足一小时显示分与秒喵
    if safe_seconds < 3600:
        minutes = safe_seconds // 60
        seconds = safe_seconds % 60
        # 秒数为 0 时省略，避免 "3 分 0 秒" 这种啰嗦写法喵
        if seconds == 0:
            return f"{minutes} 分"
        return f"{minutes} 分 {seconds} 秒"
    # 超过一小时显示小时与分喵
    hours = safe_seconds // 3600
    minutes = (safe_seconds % 3600) // 60
    # 分钟为 0 时只显示小时喵
    if minutes == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {minutes} 分"


def format_relative(moment: Any, now: datetime | None = None) -> str:
    """把时间点格式化成「多久之前」喵。

    输入：目标时间、可选基准时间。
    输出：如 "刚刚"、"12 秒前"、"5 分钟前"。
    边界：未来时间（时钟回拨）按"刚刚"展示喵。
    """
    # 喵~防御：不是时间类型就没有相对时间可言喵
    if not isinstance(moment, datetime):
        return ""
    # 基准时间缺省取当前 UTC 时间喵
    base_moment = now or datetime.now(timezone.utc)
    # 目标时间没带时区时补上 UTC，避免相减报错喵
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # 计算时间差秒数喵
    delta_seconds = (base_moment - moment).total_seconds()
    # 喵~防御：负数说明客户端时钟比服务端快，按"刚刚"展示喵
    if delta_seconds < 10:
        return "刚刚"
    # 一分钟内按秒显示喵
    if delta_seconds < 60:
        return f"{int(delta_seconds)} 秒前"
    # 一小时内按分钟显示喵
    if delta_seconds < 3600:
        return f"{int(delta_seconds // 60)} 分钟前"
    # 一天内按小时显示喵
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)} 小时前"
    # 超过一天按天显示喵
    return f"{int(delta_seconds // 86400)} 天前"


def _format_list(value: Any) -> str:
    """把列表或字典拼成一行中文喵。"""
    # 列表用顿号连接喵
    if isinstance(value, (list, tuple)):
        return "、".join(_format_plain(item) for item in value)
    # 字典用「键：值」连接喵
    if isinstance(value, Mapping):
        return "、".join(f"{key}：{_format_plain(item)}" for key, item in value.items())
    # 其它类型按普通值处理喵
    return _format_plain(value)


def _format_plain(value: Any) -> str:
    """默认格式化：不做任何修饰，但把 None 变成空串喵。"""
    # 喵~防御：空值统一成空串，避免模板里出现 "None" 喵
    if value is MISSING or value is None:
        return ""
    # 布尔用中文，比 True/False 自然喵
    if isinstance(value, bool):
        return "是" if value else "否"
    # 时间默认展示成相对时间，命令里最常用喵
    if isinstance(value, datetime):
        return format_relative(value)
    # 列表与字典拼成一行喵
    if isinstance(value, (list, tuple, Mapping)):
        return _format_list(value)
    # 其余直接转字符串喵
    return str(value)


def _to_number(value: Any) -> float | None:
    """把值转成数字，失败时返回 None 喵。"""
    # 喵~防御：布尔不是数字，避免 True 变成 1 喵
    if isinstance(value, bool):
        return None
    # 已经是数字喵
    if isinstance(value, (int, float)):
        return float(value)
    # 尝试解析文本喵
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _apply_formatter(value: Any, formatter: Formatter) -> str:
    """套用格式化器喵。"""
    # 喵~防御：空值不参与格式化，直接给空串，免得出现 "0 秒" 这种假数据喵
    if value is MISSING or value is None or value == "":
        return ""
    # 时长：把秒数变成人话喵
    if formatter.name == "时长":
        return format_duration(value)
    # 相对：把时间变成「多久之前」喵
    if formatter.name == "相对":
        return format_relative(value)
    # 百分比：默认一位小数，带参数时按参数控制小数位喵
    if formatter.name == "百分比":
        number = _to_number(value)
        if number is None:
            return ""
        digits = 1
        if formatter.argument.strip():
            try:
                digits = max(0, min(4, int(formatter.argument)))
            except ValueError:
                digits = 1
        return f"{number:.{digits}f}%"
    # 数字：整数不带小数点喵
    if formatter.name == "数字":
        number = _to_number(value)
        if number is None:
            return ""
        return str(int(number)) if number == int(number) else f"{number:g}"
    # 时间：绝对时间，精确到秒喵
    if formatter.name == "时间":
        if not isinstance(value, datetime):
            return _format_plain(value)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    # 秒：时长文本换成秒数喵
    if formatter.name == "秒":
        parsed = parse_duration_text(str(value))
        return "" if parsed is None else str(parsed)
    # 列表：用顿号连接喵
    if formatter.name == "列表":
        return _format_list(value)
    # 截断：超长文本加省略号喵
    if formatter.name == "截断":
        text = _format_plain(value)
        try:
            limit = max(1, int(formatter.argument))
        except ValueError:
            limit = 16
        return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"
    # 喵~防御：不认识的格式化器保留原值，不让整条命令变成空消息喵
    if formatter.name not in _WARNED_PATHS:
        _WARNED_PATHS.add(formatter.name)
        LOGGER.warning("模板里出现了未知格式化器：%s（已按原值输出）", formatter.name)
    return _format_plain(value)


def render(
    nodes: Sequence[Any],
    scopes: Sequence[Mapping[str, Any]],
    env: RenderEnv,
    depth: int = 0,
) -> str:
    """把节点树渲染成文本喵。

    输入：节点树、作用域链（内层在前）、渲染环境、当前嵌套深度。
    输出：渲染后的文本。
    边界：变量取不到时输出空串并告警一次；片段不存在时抛 TemplateError喵。
    """
    # 喵~防御：嵌套太深说明片段写成了互相引用喵
    if depth > MAX_DEPTH:
        raise TemplateError(f"模板嵌套超过 {MAX_DEPTH} 层")
    parts: list[str] = []
    for node in nodes:
        # 文本节点直接拼上喵
        if isinstance(node, str):
            parts.append(node)
            continue
        # 变量节点喵
        if isinstance(node, VarNode):
            value = resolve(node.path, scopes)
            # 变量不存在时告警一次，输出空串喵
            if value is MISSING:
                if node.path not in _WARNED_PATHS:
                    _WARNED_PATHS.add(node.path)
                    LOGGER.warning("模板里引用了不存在的变量：%s（已按空串输出）", node.path)
                continue
            parts.append(_format_plain(value) if node.formatter is None else _apply_formatter(value, node.formatter))
            continue
        # 条件节点喵
        if isinstance(node, IfNode):
            value = resolve(node.path, scopes)
            # 哨兵与空值都算假喵
            truthy = value is not MISSING and bool(value)
            branch = node.body if truthy else node.otherwise
            parts.append(render(branch, scopes, env, depth + 1))
            continue
        # 片段引用喵
        if isinstance(node, FragmentNode):
            fragment = env.fragment(node.name)
            # 喵~防御：片段名写错要立刻报出来，不能静默少一段喵
            if fragment is None:
                raise TemplateError(f"找不到片段：{node.name}")
            parts.append(render(fragment, scopes, env, depth + 1))
            continue
        # 查询节点喵
        if isinstance(node, QueryNode):
            parts.append(_render_query(node, scopes, env, depth))
            continue
        # 喵~防御：未知节点类型直接报错，避免悄悄丢内容喵
        raise TemplateError(f"未知模板节点：{type(node).__name__}")
    return "".join(parts)


def _render_query(node: QueryNode, scopes: Sequence[Mapping[str, Any]], env: RenderEnv, depth: int) -> str:
    """渲染一个查询占位符喵。"""
    # 选项转成字典，后写的覆盖先写的喵
    options: dict[str, str] = {}
    for key, value in node.options:
        # 喵~注意：选项值里允许再嵌占位符（例如 最近={窗口}），先渲染一次再交给数据层喵
        if "{" in value:
            value = render(parse(value).nodes, scopes, env, depth + 1)
        options[key] = value
    # 交给数据集层执行喵
    result = env.query(node.dataset, options, scopes, depth)
    # 聚合结果是标量，直接格式化喵
    if not isinstance(result, (list, tuple)):
        return _format_plain(result)
    # 喵~防御：空结果优先用「空=」文案，没有就用空串喵
    if not result:
        empty_text = options.get("空", "")
        return render(parse(empty_text).nodes, scopes, env, depth + 1) if empty_text else ""
    # 指定了行片段就逐行渲染喵
    row_fragment = options.get("行", "")
    if not row_fragment:
        raise TemplateError(f"{node.dataset} 的查询必须指定 行=片段 或聚合关键字")
    fragment = env.fragment(row_fragment)
    # 喵~防御：行片段不存在时立刻报错喵
    if fragment is None:
        raise TemplateError(f"找不到行片段：{row_fragment}")
    lines: list[str] = []
    for item in result:
        # 每行把当前项压到作用域最内层，片段里直接写 {名称} 就行喵
        item_scope = item if isinstance(item, Mapping) else {"值": item}
        lines.append(render(fragment, (item_scope, *scopes), env, depth + 1))
    return "\n".join(lines)


def render_text(text: str, scopes: Sequence[Mapping[str, Any]], env: RenderEnv) -> str:
    """解析并渲染一段模板文本，供命令层直接调用喵。

    输入：模板文本、作用域链、渲染环境。
    输出：渲染结果。
    边界：语法错误抛 TemplateError，由调用方决定回退文案喵。
    """
    # 先解析再渲染喵
    return render(parse(text).nodes, scopes, env)
