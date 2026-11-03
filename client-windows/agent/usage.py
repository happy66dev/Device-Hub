"""使用时长增量累计。

设计要点：
- 每采样到一次前台应用，就给该应用累加采样间隔秒数；
- 上报成功后清空待发数据；
- 上报失败时**不把数据并回累加器**，而是冻结成一个「待重发批次」原样重发，
  理由见 `PendingBatch` 的注释喵；
- 只累计"还没上报过"的部分，符合服务端"usage_delta 是增量"的语义喵。
"""

from __future__ import annotations

import logging

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 单次上报允许的最大应用条数，与服务端 500 条上限保持一致喵
MAX_APPS_PER_REPORT = 500

# 单个应用单次允许上报的最大秒数，一天喵
MAX_SECONDS_PER_APP = 86400

# 应用名与包名的分隔符，用 NUL 保证不会和应用名撞车喵
KEY_SEPARATOR = "\u0000"


class PendingBatch:
    """一次上报失败后冻结下来的批次：数据 + 它原始的 reported_at喵。

    为什么需要这个类型：服务端用 `(device_id, reported_at)` 做幂等键，
    同一个键重复上报只更新设备状态、**不会重复累加秒数**。
    原来客户端失败后把这批秒数并回累加器，下一批就变成「旧数据 + 新数据」的
    超集、而且重新取了当前时刻 → 服务端认为这是全新的一批，
    把旧数据又加了一遍，使用时长**永久翻倍**喵。

    正确做法是把失败的那一批**原封不动**留着（同样的秒数、同样的 reported_at），
    下一轮优先重发它；送成功之后才把这一批清掉，再去发新攒的数据。
    这样即使重试十次，服务端也只会认第一次的键，秒数只加一次喵。

    喵~注意：`reported_at` 必须**只在批次创建时取一次**，
    重试时原样带着走，不能在每次发送前重新取当前时刻——那正是原来的 bug喵。
    """

    def __init__(self, seconds: dict[str, int], reported_at: str) -> None:
        """记下这一批的秒数与它固定的上报时刻喵。

        输入：应用键到秒数的字典、这一批的 reported_at 文本（ISO 8601）。
        输出：无。
        边界：两者都按只读语义使用，调用方不要再改动传进来的字典喵。
        """
        # 复制一份，避免调用方后续改动影响已经冻结的批次喵
        self._seconds = dict(seconds)
        # 这一批固定使用的上报时刻，重试期间绝不变喵
        self._reported_at = reported_at

    @property
    def seconds(self) -> dict[str, int]:
        """返回这一批的秒数副本喵。"""
        # 返回副本，防止外部改到内部状态喵
        return dict(self._seconds)

    @property
    def reported_at(self) -> str:
        """返回这一批固定的上报时刻喵。"""
        # 直接返回字符串，重试期间保持不变喵
        return self._reported_at

    def total_seconds(self) -> int:
        """返回这一批的总秒数，用于日志与界面文案喵。"""
        # 求和喵
        return sum(self._seconds.values())

    def is_empty(self) -> bool:
        """这一批是否已经没有数据可发喵。"""
        # 没有任何应用就算空喵
        return not self._seconds



def make_key(app_name: str, package: str) -> str:
    """把应用名与包名拼成内部键喵。

    输入：应用名、包名（可为空串）。
    输出：内部使用的复合键。
    """
    # 包名统一小写，避免 MsEdge.exe 与 msedge.exe 被当成两个应用喵
    return f"{app_name}{KEY_SEPARATOR}{package.strip().lower()}"


def split_key(key: str) -> tuple[str, str]:
    """把内部键拆回应用名与包名喵。

    输入：复合键（也兼容没有分隔符的旧格式）。
    输出：(应用名, 包名)。
    """
    # 喵~防御：旧版本存的是纯应用名，没有分隔符喵
    if KEY_SEPARATOR not in key:
        return key, ""
    # 按第一个分隔符拆开喵
    name, _, package = key.partition(KEY_SEPARATOR)
    return name, package


def to_delta_list(items: dict[str, int]) -> list[dict[str, int | str]]:
    """把累计数据转成协议要求的数组格式喵。

    输入：复合键到秒数的字典。
    输出：形如 [{"app": "Code.exe", "package": "code.exe", "seconds": 60}] 的列表。
    边界：超过 500 条时按秒数从多到少截断，避免服务端拒收喵。
    """
    # 按秒数倒序排列，保证重要数据先发喵
    sorted_items = sorted(items.items(), key=lambda pair: pair[1], reverse=True)
    # 截断到服务端允许的条数喵
    limited_items = sorted_items[:MAX_APPS_PER_REPORT]
    # 喵~防御：截断时记录日志，提示主人有数据未上报喵
    if len(sorted_items) > MAX_APPS_PER_REPORT:
        LOGGER.warning("本次待上报应用数 %s 超过上限 %s，已截断", len(sorted_items), MAX_APPS_PER_REPORT)
    # 组装协议数组，包名一起带上，服务端才能匹配应用图标喵
    deltas: list[dict[str, int | str]] = []
    for key, seconds in limited_items:
        name, package = split_key(key)
        deltas.append({"app": name, "package": package, "seconds": int(seconds)})
    return deltas


class UsageTracker:
    """在内存里累计各应用的前台秒数喵。"""

    def __init__(self) -> None:
        # 待上报的累计秒数，键是应用展示名喵
        self._pending_seconds: dict[str, int] = {}

    def add_seconds(self, app_name: str, seconds: int, package: str = "") -> None:
        """给某个应用累加秒数喵。

        输入：应用名、秒数、包名（Windows 是 exe 名，安卓是包名）。
        输出：无。
        边界：应用名为空、秒数非正数时直接忽略喵。
        """
        # 喵~防御：空应用名无法归属，直接忽略喵
        if not app_name or not app_name.strip():
            return
        # 喵~防御：非正数秒数没有信息量喵
        if seconds <= 0:
            return
        # 去掉首尾空白，避免同一应用因空格被拆成两条喵
        cleaned_name = app_name.strip()[:128]
        # 包名也截断，防止异常数据把键撑爆喵
        cleaned_package = (package or "").strip()[:200]
        # 拼成内部键喵
        key = make_key(cleaned_name, cleaned_package)
        # 累加到已有值上喵
        accumulated = self._pending_seconds.get(key, 0) + int(seconds)
        # 喵~防御：单应用累计超过一天时截断，防止异常数据污染统计喵
        self._pending_seconds[key] = min(accumulated, MAX_SECONDS_PER_APP)

    def drain(self) -> dict[str, int]:
        """取出全部待上报数据并清空内部状态喵。

        输出：应用名到秒数的字典副本。
        """
        # 复制一份返回，避免调用方改动内部状态喵
        drained = dict(self._pending_seconds)
        # 清空内部累计喵
        self._pending_seconds.clear()
        # 返回副本喵
        return drained

    def restore(self, items: dict[str, int]) -> None:
        """把未成功上报的数据还回累加器喵。

        输入：应用名到秒数的字典。
        输出：无。
        """
        # 喵~防御：空数据无需处理喵
        if not items:
            return
        # 逐项累加回内部状态，键可能是复合键也可能是旧格式喵
        for key, seconds in items.items():
            name, package = split_key(key)
            self.add_seconds(name, seconds, package)

    def clear(self) -> None:
        """清空待上报数据喵。"""
        # 直接清空字典喵
        self._pending_seconds.clear()

    def snapshot(self) -> dict[str, int]:
        """返回待上报数据的副本，但不影响内部状态喵。

        用途：把数据落盘做崩溃保护，同时保留内存里的累计值喵。

        输出：应用名到秒数的字典副本。
        """
        # 复制一份返回，调用方改动不会影响内部状态喵
        return dict(self._pending_seconds)

    def pending_total_seconds(self) -> int:
        """返回当前待上报的总秒数，用于日志与测试喵。"""
        # 求和喵
        return sum(self._pending_seconds.values())

    def to_delta_list(self) -> list[dict[str, int | str]]:
        """把待上报数据转成协议要求的数组格式喵。

        输出：形如 [{"app": "Code.exe", "seconds": 60}] 的列表。
        边界：超过 500 条时按秒数从多到少截断，避免服务端拒收喵。
        """
        # 复用模块级实现，带上包名喵
        return to_delta_list(self._pending_seconds)
