"""面向命令层的只读查询。

这一层只做"取数据 + 转成简单对象"，不做任何文字排版；
排版交给 render 模块，方便单独测试喵。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import presence
from .db import days_ago_text, hours_ago_text, parse_utc_text, to_utc_text, utc_now
from .people import PersonGroup

# 判定设备在线的时长阈值：心跳 30 秒一次，超过 3 个周期没上报就算离线喵
ONLINE_WINDOW_SECONDS = 90


@dataclass(frozen=True)
class DeviceSummary:
    """设备概要，用于列表展示喵。"""

    # 设备 ID 喵
    device_id: str
    # 平台类型喵
    platform: str
    # 展示名喵
    display_name: str
    # 系统版本喵
    os_version: str
    # 最近一次上报时间喵
    last_seen_at: datetime
    # 设备角色：workstation 或 server 喵
    role: str = "workstation"
    # 设备自定义标签喵
    tag: str = ""
    # 服务器设备当前 RDP 是否连接喵
    rdp_connected: bool = False
    # 暂停原因代码，未暂停时为空串喵
    stats_paused_reason: str = ""


@dataclass(frozen=True)
class BatterySnapshot:
    """最近一次电量快照喵。"""

    # 电量百分比喵
    percent: int
    # 是否在充电喵
    charging: bool
    # 采样时间喵
    sampled_at: datetime


@dataclass(frozen=True)
class CurrentAppSnapshot:
    """最近一次上报里的当前前台应用喵。"""

    # 应用展示名喵
    name: str
    # 包名或进程名，可能为空喵
    package: str | None
    # 进入前台时间，可能为空喵
    since: datetime | None


@dataclass(frozen=True)
class UsageEntry:
    """一条应用使用时长汇总喵。"""

    # 应用名喵
    app: str
    # 窗口内累计秒数喵
    seconds: int
    # 包名或进程名，可能为空喵
    package: str = ""


@dataclass(frozen=True)
class DeviceDetail:
    """设备详情，供 /设备 <id> 与 /使用 <id> 使用喵。"""

    # 概要信息喵
    summary: DeviceSummary
    # 硬件信息键值表喵
    hardware: dict[str, str]
    # 最近电量，可能为空喵
    battery: BatterySnapshot | None
    # 当前前台应用，可能为空喵
    current_app: CurrentAppSnapshot | None
    # 近 24 小时使用总时长秒数喵
    usage_total_seconds: int
    # 该服务器当前投屏中的安卓标签喵
    mirrored_tags: tuple[str, ...] = ()
    # 该服务器的投屏窗口是否在前台喵
    mirror_foreground: bool = False


@dataclass(frozen=True)
class BatteryPoint:
    """电量曲线上的一个点喵。"""

    # 采样时间喵
    sampled_at: datetime
    # 电量百分比喵
    percent: int
    # 是否充电喵
    charging: bool


@dataclass(frozen=True)
class UsageBucket:
    """使用时长时间轴上的一个桶（默认按小时）喵。"""

    # 桶起始时间喵
    bucket_start: datetime
    # 桶内累计秒数喵
    seconds: int


@dataclass(frozen=True)
class GlobalUsageEntry:
    """跨设备汇总的一条应用使用时长喵。"""

    # 应用名喵
    app: str
    # 包名或进程名，可能为空喵
    package: str
    # 窗口内所有设备累计秒数喵
    seconds: int
    # 有多少台设备用过这个应用喵
    device_count: int
    # 用过这个应用的设备名（按名称排序，便于看板展示）喵
    devices: tuple[str, ...]
    # 每台设备各自的秒数，按秒数倒序；看板据此把一条时间条切成几段喵
    device_seconds: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class UsageRankingGroup:
    """按设备或设备组拆分的一组应用排行喵。"""

    # 分组标识：设备口径是设备 ID，设备组口径是 group:组名，未分组固定为 ungrouped 喵
    key: str
    # 展示标签：设备展示名或设备组名喵
    label: str
    # 分组口径：device（按设备）或 group（按设备组）喵
    kind: str
    # 组内全部应用的合计秒数，不受 limit 截断影响喵
    seconds: int
    # 组内应用条目，按总时长倒序喵
    entries: tuple[GlobalUsageEntry, ...]


@dataclass(frozen=True)
class UsageSegment:
    """时间轴上的一段连续使用喵。"""

    # 起始时间喵
    start: datetime
    # 结束时间喵
    end: datetime
    # 应用名喵
    app: str
    # 包名或进程名，可能为空喵
    package: str
    # 段内累计秒数喵
    seconds: int
    # 这段来自哪台设备，聚合页面据此标设备名喵
    device_id: str = ""


@dataclass(frozen=True)
class DashboardDevice:
    """看板用的设备卡片数据喵。"""

    # 概要喵
    summary: DeviceSummary
    # 最近电量喵
    battery: BatterySnapshot | None
    # 当前应用喵
    current_app: CurrentAppSnapshot | None
    # 近 24 小时使用总时长喵
    usage_total_seconds: int
    # 近 24 小时前 5 个应用喵
    usage_top: tuple[UsageEntry, ...]


def _row_to_summary(row: sqlite3.Row) -> DeviceSummary:
    """把数据库行转换成设备概要对象喵。"""
    # 逐字段映射，时间文本还原成 datetime 喵
    return DeviceSummary(
        device_id=row["device_id"],
        platform=row["platform"],
        display_name=row["display_name"],
        os_version=row["os_version"],
        last_seen_at=parse_utc_text(row["last_seen_at"]),
        role=str(row["role"]) if "role" in row.keys() and row["role"] else "workstation",
        tag=str(row["tag"]) if "tag" in row.keys() and row["tag"] else "",
        rdp_connected=bool(row["rdp_connected"]) if "rdp_connected" in row.keys() else False,
        stats_paused_reason=str(row["stats_paused_reason"]) if "stats_paused_reason" in row.keys() and row["stats_paused_reason"] else "",
    )


def is_online(last_seen_at: datetime, now: datetime | None = None) -> bool:
    """判断设备是否在线喵。"""
    # 基准时间缺省取当前 UTC 时间喵
    base_moment = now or utc_now()
    # 喵~防御：时钟回拨导致 last_seen_at 在未来时，差值可能为负，这里也视为在线喵
    elapsed_seconds = (base_moment - last_seen_at).total_seconds()
    # 差值在阈值内（含负数）都算在线喵
    return elapsed_seconds <= ONLINE_WINDOW_SECONDS


def list_devices(connection: sqlite3.Connection) -> list[DeviceSummary]:
    """列出所有设备，最近上报的排在前面喵。"""
    # 按最近上报时间倒序，主人在群里最常看的就是最新设备喵
    rows = connection.execute(
        """
        SELECT device_id, platform, display_name, os_version, last_seen_at,
               role, tag, rdp_connected, stats_paused_reason
        FROM devices ORDER BY last_seen_at DESC
        """
    ).fetchall()
    # 逐行转换成对象喵
    return [_row_to_summary(row) for row in rows]


def get_device(connection: sqlite3.Connection, device_id: str) -> DeviceDetail | None:
    """查询单台设备的完整详情，设备不存在时返回 None 喵。"""
    # 主表查询喵
    row = connection.execute(
        """
        SELECT device_id, platform, display_name, os_version, hardware_json, current_app_json, last_seen_at,
               role, tag, rdp_connected, stats_paused_reason, mirrored_tags_json, mirror_foreground
        FROM devices WHERE device_id = ?
        """,
        (device_id,),
    ).fetchone()
    # 喵~防御：查不到设备时返回 None，由命令层给出友好提示喵
    if row is None:
        return None
    # 硬件 JSON 解析，解析失败时退回空字典而不是崩掉整个命令喵
    try:
        hardware_data = json.loads(row["hardware_json"] or "{}")
    except json.JSONDecodeError:
        hardware_data = {}
    # 喵~防御：库里存的不是字典（例如手工改坏）时同样退回空字典喵
    if not isinstance(hardware_data, dict):
        hardware_data = {}
    # 当前应用 JSON 解析喵
    current_app_snapshot: CurrentAppSnapshot | None = None
    raw_current_app = row["current_app_json"]
    if raw_current_app:
        try:
            # 解析成字典后逐字段取值喵
            current_app_data = json.loads(raw_current_app)
        except json.JSONDecodeError:
            # 喵~防御：坏数据按"没有当前应用"处理喵
            current_app_data = None
        if isinstance(current_app_data, dict) and current_app_data.get("name"):
            # since 可能是 None 或 ISO 字符串喵
            since_value = current_app_data.get("since")
            # 解析进入前台时间喵
            since_moment = datetime.fromisoformat(since_value) if isinstance(since_value, str) else None
            # 喵~防御：客户端可能传来不带时区的时间，补上 UTC 避免后续相减报错喵
            if since_moment is not None and since_moment.tzinfo is None:
                since_moment = since_moment.replace(tzinfo=timezone.utc)
            # 组装对象喵
            current_app_snapshot = CurrentAppSnapshot(
                name=str(current_app_data["name"]),
                package=current_app_data.get("package"),
                since=since_moment,
            )
    # 汇总近 24 小时使用总时长喵
    usage_rows = usage_ranking(connection, device_id, hours=24)
    # 总秒数等于各应用之和喵
    total_seconds = sum(entry.seconds for entry in usage_rows)
    # 解析该服务器投屏中的标签喵
    mirrored_tags: list[str] = []
    raw_mirrored = row["mirrored_tags_json"]
    if raw_mirrored:
        try:
            parsed_mirrored = json.loads(raw_mirrored)
        except json.JSONDecodeError:
            # 喵~防御：坏 JSON 按"没有投屏设备"处理喵
            parsed_mirrored = []
        if isinstance(parsed_mirrored, list):
            mirrored_tags = [item for item in parsed_mirrored if isinstance(item, str) and item.strip()]
    # 返回完整详情喵
    return DeviceDetail(
        summary=_row_to_summary(row),
        hardware={str(key): str(value) for key, value in hardware_data.items()},
        battery=latest_battery(connection, device_id),
        current_app=current_app_snapshot,
        usage_total_seconds=total_seconds,
        mirrored_tags=tuple(mirrored_tags),
        mirror_foreground=bool(row["mirror_foreground"]) if "mirror_foreground" in row.keys() else False,
    )


def latest_battery(connection: sqlite3.Connection, device_id: str) -> BatterySnapshot | None:
    """取最近一次电量采样，没有记录时返回 None 喵。"""
    # 按采样时间倒序取第一条喵
    row = connection.execute(
        "SELECT percent, charging, sampled_at FROM battery_samples WHERE device_id = ? ORDER BY sampled_at DESC LIMIT 1",
        (device_id,),
    ).fetchone()
    # 喵~防御：没有电量记录（Windows 设备或刚接入）时返回 None 喵
    if row is None:
        return None
    # 组装快照对象，charging 从 0/1 还原成布尔喵
    return BatterySnapshot(
        percent=int(row["percent"]),
        charging=bool(row["charging"]),
        sampled_at=parse_utc_text(row["sampled_at"]),
    )


def usage_ranking(
    connection: sqlite3.Connection,
    device_id: str,
    hours: int = 24,
    now: datetime | None = None,
) -> list[UsageEntry]:
    """按应用汇总时间窗口内的使用时长，从多到少排序喵。

    输入：连接、设备 ID、窗口小时数、可选的基准时间。
    输出：UsageEntry 列表，秒数为 0 的应用不返回。
    边界：hours 为负数时按 0 处理，等价于只统计"此刻之后"的数据（通常为空）。
    """
    # 计算窗口起点文本喵
    window_start = hours_ago_text(hours, now)
    # 分组求和并按总时长倒序，时长相同按应用名排序保证结果稳定喵
    rows = connection.execute(
        """
        SELECT app_name, package, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE device_id = ? AND sampled_at >= ?
        GROUP BY app_name, package
        HAVING total_seconds > 0
        ORDER BY total_seconds DESC, app_name ASC
        """,
        (device_id, window_start),
    ).fetchall()
    # 逐行转换成对象喵
    return [
        UsageEntry(app=row["app_name"], seconds=int(row["total_seconds"]), package=str(row["package"] or ""))
        for row in rows
    ]


def usage_window_start(hours: int = 0, seconds: int = 0, now: datetime | None = None) -> str:
    """算出使用时长查询的窗口起点文本喵。

    输入：窗口小时数、窗口秒数（两者相加）、可选基准时间。
    输出：UTC 文本，可直接用于 `sampled_at >= ?`。
    边界：两个窗口都省略时等价于 0 秒窗口，只统计"此刻之后"（通常为空）喵。
    """
    # 基准时间缺省取当前时间喵
    base_moment = now or utc_now()
    # 喵~防御：负数窗口按 0 处理，避免算出未来时间喵
    total_seconds = max(0, hours) * 3600 + max(0, seconds)
    # 统一走 UTC 文本，与库里的格式一致喵
    return to_utc_text(base_moment - timedelta(seconds=total_seconds))


def usage_ranking_window(
    connection: sqlite3.Connection,
    device_id: str,
    hours: int = 0,
    seconds: int = 0,
    now: datetime | None = None,
) -> list[UsageEntry]:
    """按应用汇总任意窗口（小时 + 秒）内的使用时长喵。

    输入：连接、设备 ID、窗口小时数、窗口秒数、可选基准时间。
    输出：UsageEntry 列表，按时长倒序、同长按应用名升序。
    边界：窗口为 0 时多半返回空列表，调用方要准备好空文案喵。
    """
    # 计算窗口起点喵
    window_start = usage_window_start(hours, seconds, now)
    # 分组求和喵
    rows = connection.execute(
        """
        SELECT app_name, package, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE device_id = ? AND sampled_at >= ?
        GROUP BY app_name, package
        HAVING total_seconds > 0
        ORDER BY total_seconds DESC, app_name ASC
        """,
        (device_id, window_start),
    ).fetchall()
    # 逐行转成对象喵
    return [
        UsageEntry(app=row["app_name"], seconds=int(row["total_seconds"]), package=str(row["package"] or ""))
        for row in rows
    ]


def device_usage_totals(
    connection: sqlite3.Connection,
    hours: int = 0,
    seconds: int = 0,
    now: datetime | None = None,
) -> dict[str, int]:
    """按设备汇总窗口内的使用总秒数喵。

    输入：连接、窗口小时数、窗口秒数、可选基准时间。
    输出：设备 ID 到总秒数的映射，没有数据的设备不出现在结果里。
    边界：只返回大于 0 的合计喵。
    """
    # 计算窗口起点喵
    window_start = usage_window_start(hours, seconds, now)
    # 一台设备一行，直接聚合喵
    rows = connection.execute(
        """
        SELECT device_id, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE sampled_at >= ?
        GROUP BY device_id
        HAVING total_seconds > 0
        """,
        (window_start,),
    ).fetchall()
    # 转成字典喵
    return {str(row["device_id"]): int(row["total_seconds"]) for row in rows}


def devices_with_usage(
    connection: sqlite3.Connection,
    hours: int = 0,
    seconds: int = 0,
    now: datetime | None = None,
) -> set[str]:
    """列出窗口内有使用记录的设备 ID 喵。

    输入：连接、窗口小时数、窗口秒数、可选基准时间。
    输出：设备 ID 集合，用于「最近 1 分钟谁在用」这类筛选。
    边界：没有数据时返回空集合喵。
    """
    # 计算窗口起点喵
    window_start = usage_window_start(hours, seconds, now)
    # 去重查询喵
    rows = connection.execute(
        "SELECT DISTINCT device_id FROM usage_samples WHERE sampled_at >= ?",
        (window_start,),
    ).fetchall()
    # 收集成集合喵
    return {str(row["device_id"]) for row in rows}


def _build_device_segments(
    rows: Sequence[sqlite3.Row],
    merge_gap_seconds: int,
    device_id: str = "",
    floor_start: datetime | None = None,
) -> list[UsageSegment]:
    """把一台设备的采样按时间顺序合成互不重叠的连续段喵。

    输入：该设备的采样行（按时间升序）、同应用合并间隔秒数、设备 ID、窗口起点下限。
    输出：UsageSegment 列表，段之间不重叠，且每段都不晚于它所属的采样时刻。
    边界：一次上报里的多个应用按累计时长从采样时刻往前铺，这样时间轴永远不会画到「现在」之后喵。
    """
    # 结果列表喵
    segments: list[UsageSegment] = []
    # 已铺到的右端，保证段之间不重叠喵
    cursor: datetime | None = None
    # 先按时间解析一遍，脏数据直接丢掉喵
    ordered: list[tuple[datetime, sqlite3.Row]] = []
    for row in rows:
        try:
            # 时间文本坏了就跳过，别让一条脏数据毁掉整天的时间轴喵
            ordered.append((parse_utc_text(row["sampled_at"]), row))
        except ValueError:
            continue
    # 同一 sampled_at 的多条采样是一次上报的累计量，要当成一组往前铺喵
    index = 0
    while index < len(ordered):
        sampled_at = ordered[index][0]
        group: list[sqlite3.Row] = []
        while index < len(ordered) and ordered[index][0] == sampled_at:
            group.append(ordered[index][1])
            index += 1
        # 这一组的总时长喵
        total = sum(max(0, int(item["seconds"])) for item in group)
        # 可用区间：上一次铺到的位置到这次采样时刻喵
        lower = cursor if cursor is not None else floor_start
        # 喵~防御：可用区间比累计时长短时按比例压缩，宁可画窄也不越过采样时刻喵
        if lower is None:
            scale = 1.0
        else:
            available = max(0.0, (sampled_at - lower).total_seconds())
            scale = 1.0 if total <= 0 else min(1.0, available / total)
        # 从采样时刻往前铺，铺完正好落在采样时刻上喵
        position = sampled_at
        group_segments: list[UsageSegment] = []
        for row in reversed(group):
            seconds = max(0, int(row["seconds"]))
            width = seconds * scale
            start = position - timedelta(seconds=width)
            # 喵~防御：压缩后可能触到下限，夹住避免负宽度喵
            if lower is not None and start < lower:
                start = lower
            # 宽度为 0 的段没有绘制价值喵
            if start < position:
                group_segments.append(
                    UsageSegment(
                        start=start,
                        end=position,
                        app=str(row["app_name"]),
                        package=str(row["package"] or ""),
                        seconds=seconds,
                        device_id=device_id,
                    )
                )
            position = start
        # 组内是倒着生成的，翻转回升序喵
        group_segments.reverse()
        # 按升序并进结果，同应用相邻就合并喵
        for segment in group_segments:
            if segments:
                last = segments[-1]
                # 同应用且间隔不超过阈值时并进上一段喵
                if (
                    last.app == segment.app
                    and last.package == segment.package
                    and (segment.start - last.end).total_seconds() <= merge_gap_seconds
                ):
                    segments[-1] = UsageSegment(
                        start=last.start,
                        end=max(last.end, segment.end),
                        app=segment.app,
                        package=segment.package,
                        seconds=last.seconds + segment.seconds,
                        device_id=last.device_id,
                    )
                    continue
            # 否则另起一段喵
            segments.append(segment)
        # 这一组铺到采样时刻为止喵
        cursor = sampled_at
    # 返回合并结果喵
    return segments


def _subtract_blocked(segment: UsageSegment, blocked: Sequence[tuple[datetime, datetime]]) -> list[UsageSegment]:
    """从一段里扣掉已被高优先级设备占用的时间喵。

    输入：待裁剪的段、已被占用的时间区间（无需有序）。
    输出：剩下的若干段；秒数按剩余长度等比例折算。
    """
    # 剩余片段列表，初始就是整段喵
    pieces: list[tuple[datetime, datetime]] = [(segment.start, segment.end)]
    for blocked_start, blocked_end in blocked:
        next_pieces: list[tuple[datetime, datetime]] = []
        for piece_start, piece_end in pieces:
            # 完全不重叠就原样保留喵
            if blocked_end <= piece_start or blocked_start >= piece_end:
                next_pieces.append((piece_start, piece_end))
                continue
            # 左边剩一截喵
            if blocked_start > piece_start:
                next_pieces.append((piece_start, blocked_start))
            # 右边剩一截喵
            if blocked_end < piece_end:
                next_pieces.append((blocked_end, piece_end))
        pieces = next_pieces
        # 喵~防御：全被占满就直接返回，省得继续算喵
        if not pieces:
            return []
    # 原段跨度，用于按比例折算秒数喵
    span = max(1.0, (segment.end - segment.start).total_seconds())
    result: list[UsageSegment] = []
    for piece_start, piece_end in pieces:
        length = (piece_end - piece_start).total_seconds()
        # 喵~防御：小于一秒的碎片直接丢掉，画出来也看不见喵
        if length < 1:
            continue
        result.append(
            UsageSegment(
                start=piece_start,
                end=piece_end,
                app=segment.app,
                package=segment.package,
                seconds=max(0, int(round(segment.seconds * length / span))),
                device_id=segment.device_id,
            )
        )
    return result


def _merge_blocked(intervals: Sequence[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """把占用区间排序合并，减少后续裁剪的计算量喵。"""
    # 先按起点排序喵
    ordered = sorted(intervals, key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            # 有交集就并成一段喵
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            continue
        merged.append((start, end))
    return merged


def _parse_optional_moment(value: object) -> datetime | None:
    """解析上报体里的可选时刻（ISO 8601 且必须带时区）喵。

    输入：上报体里的原始值，可能是字符串、空值或垃圾数据。
    输出：UTC 的 datetime；解析不了就返回 None，让调用方退回粗粒度逻辑喵。
    边界：不带时区、格式不对、类型不对都按"没传"处理，绝不让一条脏数据毁掉整天时间轴喵。
    """
    # 喵~防御：不是非空字符串就当没传喵
    if not isinstance(value, str) or not value.strip():
        return None
    # 交给标准库解析，顺便容忍 Z 结尾喵
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # 喵~防御：不带时区的时刻没法比较喵
    if parsed.tzinfo is None:
        return None
    # 统一换算到 UTC 喵
    return parsed.astimezone(timezone.utc)


def day_heartbeats(
    connection: sqlite3.Connection,
    device_ids: str | Sequence[str],
    start: datetime,
    end: datetime,
) -> list[presence.Heartbeat]:
    """取窗口内每台设备的上报心跳，供时间轴判定在线/离线喵。

    输入：连接、设备 ID（可多台）、窗口起止（UTC）。
    输出：按时间升序的 Heartbeat 列表，afk 取自上报体里的字段。
    边界：没有上报记录时返回空列表；上报体坏 JSON 时按「非 AFK」处理喵。
    """
    # 允许单台或多台喵
    ids = [device_ids] if isinstance(device_ids, str) else list(device_ids)
    # 喵~防御：没有设备直接返回喵
    if not ids:
        return []
    # 拼占位符喵
    placeholders = ",".join("?" for _ in ids)
    # 只取时间和上报体，顺便带上设备角色喵
    rows = connection.execute(
        f"""
        SELECT r.device_id, r.received_at AS reported_at, r.payload_json, COALESCE(d.role, '') AS role
        FROM reports AS r
        LEFT JOIN devices AS d ON d.device_id = r.device_id
        WHERE r.device_id IN ({placeholders}) AND r.received_at >= ? AND r.received_at < ?
        ORDER BY r.received_at ASC
        """,
        [*ids, to_utc_text(start), to_utc_text(end)],
    ).fetchall()
    # 逐条解析喵
    heartbeats: list[presence.Heartbeat] = []
    for row in rows:
        # 解析上报体拿 afk 标记喵
        afk = False
        # 空档边界时刻，旧客户端不带就是 None 喵
        afk_since: datetime | None = None
        active_since: datetime | None = None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            # 喵~防御：坏 JSON 不影响心跳本身喵
            payload = {}
        if isinstance(payload, dict):
            afk = bool(payload.get("afk", False))
            # 喵~注意：这两个时刻让空档边界精确到秒，坏值一律当没传喵
            afk_since = _parse_optional_moment(payload.get("afk_since"))
            active_since = _parse_optional_moment(payload.get("active_since"))
        # 记一条心跳喵
        heartbeats.append(
            presence.Heartbeat(
                reported_at=parse_utc_text(str(row["reported_at"])),
                afk=afk,
                device_id=str(row["device_id"]),
                is_server=str(row["role"] or "") == "server",
                afk_since=afk_since,
                active_since=active_since,
            )
        )
    return heartbeats


def day_usage_segments(
    connection: sqlite3.Connection,
    device_ids: str | Sequence[str],
    start: datetime,
    end: datetime,
    merge_gap_seconds: int = 5,
    resolve_overlaps: bool = True,
) -> list[UsageSegment]:
    """把窗口内的使用采样合并成连续段，用于画 0-24 点时间轴喵。

    输入：连接、设备 ID（可多台，**顺序即优先级，靠前的优先**）、窗口起止（UTC）、
          同应用相邻采样的最大合并间隔秒数、是否按优先级裁剪重叠。
    输出：按起始时间升序的 UsageSegment 列表。
    边界：合并间隔小于 0 时按 0 处理；没有任何采样时返回空列表；
          多设备重叠时高优先级设备保留完整时长，低优先级设备被裁掉重叠部分喵。
    """
    # 喵~防御：合并间隔取非负值喵
    safe_gap = max(0, int(merge_gap_seconds))
    # 允许传单台设备或多台设备（合并成一个人的时间轴）喵
    ids = [device_ids] if isinstance(device_ids, str) else list(device_ids)
    # 喵~防御：没有设备时直接返回空列表喵
    if not ids:
        return []
    # 按设备数量拼占位符喵
    placeholders = ",".join("?" for _ in ids)
    # 按采样时间升序取窗口内的采样喵
    rows = connection.execute(
        f"""
        SELECT device_id, app_name, package, sampled_at, seconds
        FROM usage_samples
        WHERE device_id IN ({placeholders}) AND sampled_at >= ? AND sampled_at < ?
        ORDER BY sampled_at ASC, device_id ASC
        """,
        (*ids, to_utc_text(start), to_utc_text(end)),
    ).fetchall()
    # 按设备分组，保持各自的采样顺序喵
    grouped: dict[str, list[sqlite3.Row]] = {device_id: [] for device_id in ids}
    for row in rows:
        grouped.setdefault(str(row["device_id"]), []).append(row)
    # 汇总结果喵
    segments: list[UsageSegment] = []
    # 已被高优先级设备占用的时间喵
    blocked: list[tuple[datetime, datetime]] = []
    # 按优先级顺序逐台处理喵
    for device_id in ids:
        device_segments = _build_device_segments(
            grouped.get(device_id, []), safe_gap, device_id, floor_start=start
        )
        if not resolve_overlaps:
            segments.extend(device_segments)
            continue
        # 裁剪掉高优先级已经占用的时段喵
        for segment in device_segments:
            segments.extend(_subtract_blocked(segment, blocked))
        # 把这台设备占用的时段记下来，供后面的低优先级设备裁剪喵
        blocked = _merge_blocked(blocked + [(segment.start, segment.end) for segment in device_segments])
    # 按时间排序后返回喵
    segments.sort(key=lambda item: (item.start, item.app))
    return segments


def _clip_segment_to_window(segment: UsageSegment, start: datetime, end: datetime) -> UsageSegment | None:
    """把一段夹进窗口 [start, end) 里，越界部分按比例折算秒数喵。

    输入：待夹的段、窗口起止（UTC）。
    输出：夹好的段；整段落在窗口外或夹完没有宽度时返回 None。
    边界：完全不越界时原样返回，秒数保持不变，避免浮点折算引入误差喵。
    """
    # 喵~防御：右端不晚于左端的段没有绘制价值喵
    if segment.end <= segment.start:
        return None
    # 左端与右端都夹到窗口里喵
    clipped_start = max(segment.start, start)
    # 右端用窗口右界收口，窗口是左闭右开喵
    clipped_end = min(segment.end, end)
    # 喵~防御：夹完没有宽度说明整段在窗口外喵
    if clipped_end <= clipped_start:
        return None
    # 没有越界时直接返回原段，保持秒数精确喵
    if clipped_start == segment.start and clipped_end == segment.end:
        return segment
    # 原段跨度，用于按比例折算秒数喵
    span = max(1.0, (segment.end - segment.start).total_seconds())
    # 夹完的长度喵
    length = (clipped_end - clipped_start).total_seconds()
    # 组装夹好的段，秒数等比例折算喵
    return UsageSegment(
        start=clipped_start,
        end=clipped_end,
        app=segment.app,
        package=segment.package,
        seconds=max(0, int(round(segment.seconds * length / span))),
        device_id=segment.device_id,
    )


def day_usage_lanes(
    connection: sqlite3.Connection,
    device_ids: str | Sequence[str],
    start: datetime,
    end: datetime,
    merge_gap_seconds: int = 5,
) -> list[UsageSegment]:
    """取多台设备在窗口内的使用段，保留设备间的时间重叠，不做优先级裁剪。

    用途：给「每台设备一条泳道」的时间轴出图，泳道口径下不允许丢段。
    对照：合并成一个人的总轴（全部设备 / 设备组）仍要用 day_usage_segments(resolve_overlaps=True)，
          那里高优先级设备占满重叠时段、低优先级被裁掉，本函数不改变也不参与那个口径。

    输入：连接、设备 ID（单台或序列，顺序不影响结果）、窗口起止（UTC）、
          同设备同应用相邻采样的最大合并间隔秒数。
    输出：按 (start, app, device_id) 升序的 UsageSegment 列表，每段的 device_id 指向来源设备。
    边界：设备列表为空（含空字符串）时返回空列表；合并间隔为负时按 0 处理；
          每台设备内部仍由 _build_device_segments 合并，不跨设备合并，
          多台设备同一时刻用同一个应用时各自保留一段喵。
    """
    # 喵~防御：合并间隔取非负值，与 day_usage_segments 语义保持一致喵
    safe_gap = max(0, int(merge_gap_seconds))
    # 允许传单台设备或多台设备喵
    ids = [device_ids] if isinstance(device_ids, str) else list(device_ids)
    # 喵~防御：空串、纯空白的 ID 直接丢掉，避免拼出无意义的 IN 条件喵
    ids = [item for item in ids if str(item).strip()]
    # 喵~防御：没有设备时直接返回空列表喵
    if not ids:
        return []
    # 去重但保留原始顺序，防止同一台设备被算两次喵
    unique_ids = list(dict.fromkeys(ids))
    # 按设备数量拼占位符喵
    placeholders = ",".join("?" for _ in unique_ids)
    # 按采样时间升序取窗口内的采样，设备间不排序也没关系，下面按设备自行分组喵
    rows = connection.execute(
        f"""
        SELECT device_id, app_name, package, sampled_at, seconds
        FROM usage_samples
        WHERE device_id IN ({placeholders}) AND sampled_at >= ? AND sampled_at < ?
        ORDER BY sampled_at ASC, device_id ASC
        """,
        (*unique_ids, to_utc_text(start), to_utc_text(end)),
    ).fetchall()
    # 按设备分组，单台设备内部才会用到合并语义喵
    grouped: dict[str, list[sqlite3.Row]] = {device_id: [] for device_id in unique_ids}
    for row in rows:
        # 库里出现未请求的设备时补一个桶，保持数据不丢喵
        grouped.setdefault(str(row["device_id"]), []).append(row)
    # 汇总结果喵
    segments: list[UsageSegment] = []
    # 逐台设备独立成段，这里刻意不做任何跨设备裁剪喵
    for device_id in unique_ids:
        # 同一台设备内部照旧合并相邻采样喵
        device_segments = _build_device_segments(
            grouped.get(device_id, []), safe_gap, device_id, floor_start=start
        )
        # 喵~防御：_build_device_segments 不会越过 sampled_at，但这里再夹一次窗口右界更稳妥喵
        for segment in device_segments:
            # 夹进窗口，整段越界时返回 None 喵
            clipped = _clip_segment_to_window(segment, start, end)
            # 喵~防御：没有有效区间的段不进入结果喵
            if clipped is None:
                continue
            # 收进结果喵
            segments.append(clipped)
    # 按 (start, app, device_id) 排序，保证输出稳定可测试喵
    segments.sort(key=lambda item: (item.start, item.app, item.device_id))
    # 返回保留重叠的明细喵
    return segments


def union_seconds(segments: Sequence[UsageSegment]) -> int:
    """把若干时间段按时间轴合并后计算总秒数，重叠部分只算一次。

    输入：任意设备的 UsageSegment 序列（可乱序、可重叠，应用与设备都不参与计算）。
    输出：并集总秒数，取整方式为「先 round 四舍五入到最近整数再转 int」，
          避免浮点误差累积成 1 秒偏差。
    边界：空列表返回 0；零宽或倒挂的段被忽略；首尾相接视为不重叠，直接相连但长度不变喵。
    """
    # 收集有效区间，右端不晚于左端的段不参与并集喵
    intervals: list[tuple[datetime, datetime]] = []
    for segment in segments:
        # 喵~防御：零宽或倒挂的段无法贡献长度喵
        if segment.end <= segment.start:
            continue
        # 记下区间喵
        intervals.append((segment.start, segment.end))
    # 先按起点排序，后面一次线性扫描就够喵
    intervals.sort(key=lambda item: item[0])
    # 累加并集长度（浮点秒，最后统一取整）喵
    total = 0.0
    # 当前正在累积的并集区间喵
    current_start: datetime | None = None
    # 当前并集区间的右端喵
    current_end: datetime | None = None
    for span_start, span_end in intervals:
        # 第一个区间直接开张喵
        if current_start is None or current_end is None:
            current_start = span_start
            current_end = span_end
            continue
        # 与当前区间有交集或首尾相接（start == end）就并进去喵
        if span_start <= current_end:
            current_end = max(current_end, span_end)
            continue
        # 断开时先结算上一段喵
        total += (current_end - current_start).total_seconds()
        # 再从这一段重新开张喵
        current_start = span_start
        current_end = span_end
    # 收尾最后一段喵
    if current_start is not None and current_end is not None:
        total += (current_end - current_start).total_seconds()
    # 先 round 再转 int，避免浮点误差累积出 1 秒偏差喵
    return int(round(total))


def device_name_map(connection: sqlite3.Connection) -> dict[str, str]:
    """取「设备 ID → 展示名」映射喵。

    输入：连接。
    输出：字典；没有展示名的设备用 device_id 兜底。
    边界：设备表为空时返回空字典喵。
    """
    # 一次查完所有设备，供聚合页面标注设备名喵
    rows = connection.execute(
        "SELECT device_id, COALESCE(NULLIF(display_name, ''), device_id) AS name FROM devices"
    ).fetchall()
    # 组装成字典喵
    return {str(row["device_id"]): str(row["name"]) for row in rows}

# 窗口采样的上报周期秒数，用来给标题区间补一个尾巴喵
TITLE_SAMPLE_SECONDS = 60
# 标题最多保留多少字，长标题截断后仍然认得出来喵
TITLE_MAX_CHARS = 60

@dataclass(frozen=True)
class TitleSpan:
    """同一应用同一窗口标题的连续区间，用于时间轴指针显示标题喵。"""

    # 应用名喵
    app: str
    # 窗口标题喵
    title: str
    # 区间起点喵
    start: datetime
    # 区间终点喵
    end: datetime


def day_title_spans(
    connection: sqlite3.Connection,
    device_ids: str | Sequence[str],
    start: datetime,
    end: datetime,
    merge_gap_seconds: int = 300,
    min_seconds: int = 20,
    max_spans: int = 1200,
    max_per_app: int = 120,
    clamp_end: datetime | None = None,
) -> list[TitleSpan]:
    """把窗口采样压成「应用 + 标题」的连续区间喵。

输入：连接、设备 ID（单个或列表）、窗口起止时间、同标题合并的容差秒数、最短保留秒数、
      区间总数上限、单应用区间上限、可选的区间右端上限（一般传「现在」）。
    输出：TitleSpan 列表，按起点排序。
边界：空标题的采样会被跳过；短于 min_seconds 的区间丢掉；
      超上限时保留最长的区间，按应用名截断会让排在后面的应用整段丢标题喵。
    """
    # 统一成设备 ID 列表喵
    if isinstance(device_ids, str):
        # 单个 ID 也要包成列表，方便拼 SQL 占位符喵
        id_list = [device_ids]
    else:
        # 已经是序列，转成列表避免后面多次迭代喵
        id_list = list(device_ids)
    # 喵~防御：没有设备就不用查了喵
    if not id_list:
        return []
    # 拼出 IN 子句的占位符喵
    placeholders = ",".join("?" for _ in id_list)
    # 按应用与时间排序取窗口采样喵
    rows = connection.execute(
        f"""
        SELECT app_name, title, reported_at
        FROM window_samples
        WHERE device_id IN ({placeholders}) AND reported_at >= ? AND reported_at <= ?
        ORDER BY app_name, reported_at
        """,
        (*id_list, to_utc_text(start), to_utc_text(end)),
    ).fetchall()
    # 结果列表喵
    spans: list[TitleSpan] = []
    # 当前正在累积的区间：应用、标题、起点、上一次出现时间喵
    current: dict[str, object] | None = None
    for row in rows:
        # 应用名与标题都去空白喵
        app_name = str(row["app_name"] or "").strip()
        title = str(row["title"] or "").strip()[:TITLE_MAX_CHARS]
        # 喵~防御：没有应用名或标题的采样无法展示，直接跳过喵
        if not app_name or not title:
            continue
        # 解析采样时间喵
        moment = parse_utc_text(str(row["reported_at"]))
        if moment is None:
            continue
        # 同一个应用同一标题且间隔不超过容差就延长当前区间喵
        if (
            current is not None
            and current["app"] == app_name
            and current["title"] == title
            and (moment - current["last"]).total_seconds() <= merge_gap_seconds
        ):
            current["last"] = moment
            continue
        # 否则先收尾上一段喵
        if current is not None:
            spans.append(
                TitleSpan(
                    app=str(current["app"]),
                    title=str(current["title"]),
                    start=current["start"],
                    end=current["last"] + timedelta(seconds=TITLE_SAMPLE_SECONDS),
                )
            )
        # 再开新的一段喵
        current = {"app": app_name, "title": title, "start": moment, "last": moment}
    # 收尾最后一段喵
    if current is not None:
        spans.append(
            TitleSpan(
                app=str(current["app"]),
                title=str(current["title"]),
                start=current["start"],
                end=current["last"] + timedelta(seconds=TITLE_SAMPLE_SECONDS),
            )
        )
    # 喵~防御：太短的区间没有展示价值，但阈值要低，否则切个标签页的短会话就没标题了喵
    kept = [item for item in spans if (item.end - item.start).total_seconds() >= min_seconds]
    # 喵~防御：单个应用来回切标题时按应用限流，避免一份响应被一个应用撑爆喵
    if max_per_app > 0:
        by_app: dict[str, list[TitleSpan]] = {}
        for item in kept:
            by_app.setdefault(item.app, []).append(item)
        trimmed: list[TitleSpan] = []
        for items in by_app.values():
            # 没超限就整组保留喵
            if len(items) <= max_per_app:
                trimmed.extend(items)
                continue
            # 超限时留最长的那些，短碎片属于来回切换喵
            items.sort(key=lambda span: (span.end - span.start), reverse=True)
            trimmed.extend(items[:max_per_app])
        kept = trimmed
    # 喵~防御：区间右端不能越过「现在」，否则指针能查到还没发生的标题喵
    if clamp_end is not None:
        clamped: list[TitleSpan] = []
        for item in kept:
            if item.start >= clamp_end:
                continue
            clamped.append(
                item if item.end <= clamp_end else TitleSpan(app=item.app, title=item.title, start=item.start, end=clamp_end)
            )
        kept = clamped
    # 喵~防御：超上限时保留最长的区间，按应用名截断会让排在后面的应用整段丢标题喵
    if len(kept) > max_spans:
        kept.sort(key=lambda item: (item.end - item.start), reverse=True)
        del kept[max_spans:]
    # 按起点排序后返回喵
    kept.sort(key=lambda item: item.start)
    return kept


def global_usage_ranking(
    connection: sqlite3.Connection,
    hours: int = 24,
    limit: int = 20,
    now: datetime | None = None,
) -> list[GlobalUsageEntry]:
    """跨设备汇总时间窗口内的应用使用时长，用于看板的应用排行喵。

    输入：连接、窗口小时数、返回条数上限、可选基准时间。
    输出：GlobalUsageEntry 列表，按总时长倒序。
    边界：limit 会被夹到 1–200；没有数据时返回空列表喵。
    """
    # 计算窗口起点文本喵
    window_start = hours_ago_text(hours, now)
    # 喵~防御：条数上限做个夹取，避免一次拉爆前端喵
    safe_limit = max(1, min(200, int(limit)))
    # 分组求和，同时统计有多少台设备用过喵
    rows = connection.execute(
        """
        SELECT app_name, package, SUM(seconds) AS total_seconds,
               COUNT(DISTINCT device_id) AS device_count,
               GROUP_CONCAT(DISTINCT device_id) AS device_ids
        FROM usage_samples
        WHERE sampled_at >= ?
        GROUP BY app_name, package
        HAVING total_seconds > 0
        ORDER BY total_seconds DESC, app_name ASC
        LIMIT ?
        """,
        (window_start, safe_limit),
    ).fetchall()
    # 设备 ID 到展示名的映射，一次查完避免逐行查询喵
    name_map = device_name_map(connection)
    # 上榜的应用与包名，拆分查询只关心这几个喵
    picked = {(str(row["app_name"]), str(row["package"] or "")) for row in rows}
    # 「应用 + 包名」到「设备名 -> 秒数」的映射，看板要把时间条切成几段喵
    per_device: dict[tuple[str, str], dict[str, int]] = {}
    if picked:
        # 再查一次按设备拆开的秒数，窗口与上面完全一致，求和必然对得上喵
        for detail in connection.execute(
            """
            SELECT app_name, package, device_id, SUM(seconds) AS total_seconds
            FROM usage_samples
            WHERE sampled_at >= ?
            GROUP BY app_name, package, device_id
            HAVING total_seconds > 0
            """,
            (window_start,),
        ).fetchall():
            # 只保留上榜的那几个应用喵
            key = (str(detail["app_name"]), str(detail["package"] or ""))
            if key not in picked:
                continue
            # 设备展示名可能撞车（重复改名），同名就累加喵
            name = name_map.get(str(detail["device_id"]), str(detail["device_id"]))
            bucket = per_device.setdefault(key, {})
            bucket[name] = bucket.get(name, 0) + int(detail["total_seconds"])
    # 逐行转换成对象喵
    return [
        GlobalUsageEntry(
            app=row["app_name"],
            package=str(row["package"] or ""),
            seconds=int(row["total_seconds"]),
            device_count=int(row["device_count"]),
            devices=tuple(
                sorted(
                    name_map.get(item.strip(), item.strip())
                    for item in str(row["device_ids"] or "").split(",")
                    if item.strip()
                )
            ),
            # 按设备拆开的秒数，顺序按秒数倒序喵
            device_seconds=_device_seconds_tuple(
                per_device.get((str(row["app_name"]), str(row["package"] or "")), {})
            ),
        )
        for row in rows
    ]


# 未归入任何设备组的桶键与标签喵
UNGROUPED_GROUP_KEY = "ungrouped"
UNGROUPED_GROUP_LABEL = "未分组"


def _clamp_ranking_limit(limit: int) -> int:
    """把排行条数上限夹到 1–200 喵。

    输入：调用方传入的条数上限。
    输出：夹取后的整数。
    边界：不是整数时按 1 处理，避免脏参数炸掉查询喵。
    """
    try:
        # 先转成整数喵
        value = int(limit)
    except (TypeError, ValueError):
        # 喵~防御：脏参数按最小条数处理喵
        return 1
    # 夹到合法范围喵
    return max(1, min(200, value))


def _device_seconds_tuple(per_device: dict[str, int]) -> tuple[tuple[str, int], ...]:
    """把「设备名 -> 秒数」整理成按秒数倒序、同长按名字升序的元组喵。

    输入：设备展示名到秒数的映射。
    输出：((设备名, 秒数), ...)，只保留秒数大于 0 的设备。
    边界：空映射返回空元组，序列化后就是空列表喵。
    """
    # 先过滤掉 0 秒的设备，避免看板画出零宽度的段喵
    items = [(name, seconds) for name, seconds in per_device.items() if seconds > 0]
    # 秒数倒序、同长按设备名升序，保证每次请求顺序一致喵
    items.sort(key=lambda item: (-item[1], item[0]))
    return tuple(items)


def _usage_rows_by_device(
    connection: sqlite3.Connection,
    window_start: str,
    device_ids: Sequence[str] | None = None,
) -> list[sqlite3.Row]:
    """按设备与应用聚合窗口内的使用时长喵。

    输入：连接、窗口起点 UTC 文本、可选设备范围（None 表示全部设备）。
    输出：按设备与应用汇总的查询行，每行带 device_id 与 total_seconds。
    边界：只返回总时长大于 0 的组合，没有数据时返回空列表；
          device_ids 传空列表表示限定范围内没有设备，直接返回空喵。
    """
    # 没有设备范围时按全部设备聚合喵
    if device_ids is None:
        return connection.execute(
            """
            SELECT device_id, app_name, package, SUM(seconds) AS total_seconds
            FROM usage_samples
            WHERE sampled_at >= ?
            GROUP BY device_id, app_name, package
            HAVING total_seconds > 0
            ORDER BY total_seconds DESC, app_name ASC
            """,
            (window_start,),
        ).fetchall()
    # 喵~防御：限定范围但没有设备时不必查库喵
    ids = [str(item) for item in device_ids if str(item)]
    if not ids:
        return []
    # 按设备数量拼占位符喵
    placeholders = ",".join("?" for _ in ids)
    # 一台设备一个应用一行，只取限定范围内的设备喵
    return connection.execute(
        f"""
        SELECT device_id, app_name, package, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE sampled_at >= ? AND device_id IN ({placeholders})
        GROUP BY device_id, app_name, package
        HAVING total_seconds > 0
        ORDER BY total_seconds DESC, app_name ASC
        """,
        (window_start, *ids),
    ).fetchall()


def device_usage_ranking(
    connection: sqlite3.Connection,
    hours: int = 24,
    limit: int = 20,
    now: datetime | None = None,
    device_ids: Sequence[str] | None = None,
) -> list[UsageRankingGroup]:
    """按设备分别汇总时间窗口内的应用使用时长喵。

    输入：连接、窗口小时数、每组条数上限、可选基准时间、可选设备范围。
    输出：UsageRankingGroup 列表，组内条目与组间都按总时长倒序。
    边界：limit 夹到 1–200；没有数据时返回空列表；device_ids 为 None 表示全部设备喵。
    """
    # 计算窗口起点文本喵
    window_start = hours_ago_text(hours, now)
    # 喵~防御：条数上限做个夹取，避免一次拉爆前端喵
    safe_limit = _clamp_ranking_limit(limit)
    # 按设备与应用汇总，限定范围时只查指定的设备喵
    rows = _usage_rows_by_device(connection, window_start, device_ids)
    # 设备 ID 到展示名的映射，一次查完避免逐行查询喵
    name_map = device_name_map(connection)
    # 先按设备收集条目与合计喵
    grouped: dict[str, list[GlobalUsageEntry]] = {}
    totals: dict[str, int] = {}
    for row in rows:
        # 设备 ID 与展示名喵
        device_id = str(row["device_id"])
        label = name_map.get(device_id, device_id)
        # 组装单台设备的一条应用排行喵
        entry = GlobalUsageEntry(
            app=str(row["app_name"]),
            package=str(row["package"] or ""),
            seconds=int(row["total_seconds"]),
            device_count=1,
            devices=(label,),
            # 单设备口径下这条时长全属于这台设备喵
            device_seconds=((label, int(row["total_seconds"])),),
        )
        # 收进对应设备喵
        grouped.setdefault(device_id, []).append(entry)
        # 累加设备总时长喵
        totals[device_id] = totals.get(device_id, 0) + entry.seconds
    # 逐台设备组装分组对象喵
    result: list[UsageRankingGroup] = []
    for device_id in sorted(grouped):
        # 组内条目按总时长倒序，同长按应用名稳定排序喵
        entries = sorted(grouped[device_id], key=lambda entry: (-entry.seconds, entry.app))
        # 组装分组喵
        result.append(
            UsageRankingGroup(
                key=device_id,
                label=name_map.get(device_id, device_id),
                kind="device",
                seconds=totals[device_id],
                entries=tuple(entries[:safe_limit]),
            )
        )
    # 组与组之间按总时长倒序，同长保留设备 ID 顺序喵
    result.sort(key=lambda group: group.seconds, reverse=True)
    return result


def group_usage_ranking(
    connection: sqlite3.Connection,
    groups: Sequence[PersonGroup],
    hours: int = 24,
    limit: int = 20,
    now: datetime | None = None,
    device_ids: Sequence[str] | None = None,
) -> list[UsageRankingGroup]:
    """按设备组分别汇总时间窗口内的应用使用时长喵。

    输入：连接、设备组列表（顺序即优先级）、窗口小时数、每组条数上限、可选基准时间、
          可选设备范围（None 表示全部，给了就只统计范围内的设备）。
    输出：UsageRankingGroup 列表，组内条目与组间都按总时长倒序；未归组设备放进「未分组」桶。
    边界：同一设备出现在多个组时按先出现的组算；没有数据的组不出现；limit 夹到 1–200 喵。
    """
    # 计算窗口起点文本喵
    window_start = hours_ago_text(hours, now)
    # 喵~防御：条数上限做个夹取，避免一次拉爆前端喵
    safe_limit = _clamp_ranking_limit(limit)
    # 按设备与应用汇总，限定范围时只查指定的设备喵
    rows = _usage_rows_by_device(connection, window_start, device_ids)
    # 设备 ID 到展示名的映射，一次查完避免逐行查询喵
    name_map = device_name_map(connection)
    # 设备 ID 到组键的映射，先出现的组优先，避免同一台设备被算两次喵
    device_group: dict[str, str] = {}
    # 组键到展示名的映射喵
    group_labels: dict[str, str] = {}
    # 组键的同长排序位置：people.json 里的组顺序，未分组排最后喵
    group_order: dict[str, int] = {}
    for index, group in enumerate(groups):
        # 组键带上组名，看板可以拿它做稳定标识喵
        group_key = f"group:{group.name}"
        # 记下组名给后面做标签喵
        group_labels[group_key] = group.name
        # 记下组顺序用于同长时排序喵
        group_order[group_key] = index
        for device_id in group.devices:
            # 喵~防御：同一设备重复出现在多个组时只认第一个组喵
            device_group.setdefault(device_id, group_key)
    # 同长时未分组桶排在所有组后面喵
    group_order[UNGROUPED_GROUP_KEY] = len(groups)
    # 桶键 -> (应用, 包名) -> 累计秒数喵
    bucket_seconds: dict[str, dict[tuple[str, str], int]] = {}
    # 桶键 -> (应用, 包名) -> 用过它的设备集合喵
    bucket_devices: dict[str, dict[tuple[str, str], set[str]]] = {}
    # 桶键 -> (应用, 包名) -> (设备 ID -> 秒数)，看板要用它切时间条喵
    bucket_device_seconds: dict[str, dict[tuple[str, str], dict[str, int]]] = {}
    for row in rows:
        # 找出这条采样属于哪个桶，没归组就进未分组喵
        device_id = str(row["device_id"])
        bucket_key = device_group.get(device_id, UNGROUPED_GROUP_KEY)
        # 应用与包名作为组内聚合键喵
        app_key = (str(row["app_name"]), str(row["package"] or ""))
        # 累加组内该应用的秒数喵
        seconds_map = bucket_seconds.setdefault(bucket_key, {})
        seconds_map[app_key] = seconds_map.get(app_key, 0) + int(row["total_seconds"])
        # 记下用过该应用的设备喵
        bucket_devices.setdefault(bucket_key, {}).setdefault(app_key, set()).add(device_id)
        # 按设备累加秒数，同一台设备的多次采样在这里合并喵
        device_map = bucket_device_seconds.setdefault(bucket_key, {}).setdefault(app_key, {})
        device_map[device_id] = device_map.get(device_id, 0) + int(row["total_seconds"])
    # 逐桶组装分组对象喵
    result: list[UsageRankingGroup] = []
    for bucket_key, apps in bucket_seconds.items():
        # 桶内应用条目喵
        entries: list[GlobalUsageEntry] = []
        for (app, package), seconds in apps.items():
            # 取出设备集合并换成展示名喵
            device_ids = bucket_devices[bucket_key][(app, package)]
            # 设备名可能撞车（重复改名），同名设备在这里合并喵
            per_device: dict[str, int] = {}
            for device_id, value in bucket_device_seconds[bucket_key][(app, package)].items():
                name = name_map.get(device_id, device_id)
                per_device[name] = per_device.get(name, 0) + value
            entries.append(
                GlobalUsageEntry(
                    app=app,
                    package=package,
                    seconds=seconds,
                    device_count=len(device_ids),
                    devices=tuple(sorted(name_map.get(item, item) for item in device_ids)),
                    # 按设备拆开的秒数，顺序按秒数倒序喵
                    device_seconds=_device_seconds_tuple(per_device),
                )
            )
        # 组内条目按总时长倒序，同长按应用名稳定排序喵
        entries.sort(key=lambda entry: (-entry.seconds, entry.app))
        # 未分组桶用固定标签，其它桶用组名喵
        label = group_labels.get(bucket_key, UNGROUPED_GROUP_LABEL)
        # 组总时长按全部应用求和，不受 limit 截断影响喵
        total_seconds = sum(entry.seconds for entry in entries)
        # 组装分组喵
        result.append(
            UsageRankingGroup(
                key=bucket_key,
                label=label,
                kind="group",
                seconds=total_seconds,
                entries=tuple(entries[:safe_limit]),
            )
        )
    # 组与组之间按总时长倒序，同长按 people.json 的组顺序排喵
    result.sort(key=lambda group: (-group.seconds, group_order.get(group.key, len(groups))))
    return result


def scoped_usage_ranking(
    connection: sqlite3.Connection,
    scope: str = "all",
    groups: Sequence[PersonGroup] = (),
    hours: int = 24,
    limit: int = 20,
    now: datetime | None = None,
    device_ids: Sequence[str] | None = None,
) -> tuple[list[GlobalUsageEntry], list[UsageRankingGroup]]:
    """按口径汇总应用排行，返回总排行与分组明细喵。

    输入：连接、口径（all/device/group）、设备组列表、窗口小时数、每组条数上限、
          可选基准时间、可选设备范围（None 表示全部设备）。
    输出：(总排行, 分组列表)；all 口径的分组列表为空，其它口径的总排行仍是范围内全部设备合起来的排行。
    边界：非法口径按 all 处理；limit 夹到 1–200；没有数据时两个列表都为空喵。
    """
    # 统一口径文本，非法值退回 all，避免前端写错就整页报错喵
    safe_scope = scope if scope in {"all", "device", "group"} else "all"
    # 给了设备范围时，总排行也只统计这些设备，图里才不会混进没指定的设备喵
    if device_ids is None:
        # 总排行始终按全部设备汇总，其它口径下前端仍可展示它喵
        entries = global_usage_ranking(connection, hours=hours, limit=limit, now=now)
    else:
        # 限定范围的排行复用按设备拆分的结果再合并喵
        entries = _scoped_global_entries(connection, device_ids, hours, limit, now)
    # all 口径不需要分组明细喵
    if safe_scope == "all":
        return entries, []
    # 设备口径按设备拆组喵
    if safe_scope == "device":
        return entries, device_usage_ranking(connection, hours=hours, limit=limit, now=now, device_ids=device_ids)
    # 设备组口径按 people.groups 拆组，未归组设备单独成桶喵
    return entries, group_usage_ranking(
        connection, groups, hours=hours, limit=limit, now=now, device_ids=device_ids
    )


def _scoped_global_entries(
    connection: sqlite3.Connection,
    device_ids: Sequence[str],
    hours: int,
    limit: int,
    now: datetime | None,
) -> list[GlobalUsageEntry]:
    """只在限定设备范围内汇总跨设备总排行喵。

    输入：连接、设备范围、窗口小时数、条数上限、可选基准时间。
    输出：GlobalUsageEntry 列表，按总时长倒序。
    边界：设备范围为空时返回空列表；同名应用跨设备合并成一条喵。
    """
    # 计算窗口起点文本喵
    window_start = hours_ago_text(hours, now)
    # 喵~防御：条数上限夹到合法范围喵
    safe_limit = _clamp_ranking_limit(limit)
    # 取范围内的按设备明细喵
    rows = _usage_rows_by_device(connection, window_start, device_ids)
    # 设备展示名映射喵
    name_map = device_name_map(connection)
    # 应用 -> 总秒数与按设备秒数喵
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        # 应用键：名称 + 包名喵
        key = (str(row["app_name"]), str(row["package"] or ""))
        # 取或建条目喵
        item = merged.setdefault(key, {"seconds": 0, "per_device": {}})
        # 累加总秒数喵
        item["seconds"] = int(item["seconds"]) + int(row["total_seconds"])  # type: ignore[arg-type]
        # 记下这台设备的秒数喵
        device_id = str(row["device_id"])
        per_device = item["per_device"]
        assert isinstance(per_device, dict)
        per_device[device_id] = int(per_device.get(device_id, 0)) + int(row["total_seconds"])
    # 按总时长倒序喵
    ordered = sorted(merged.items(), key=lambda pair: (-int(pair[1]["seconds"]), pair[0][0]))  # type: ignore[arg-type]
    # 逐条组装对象喵
    result: list[GlobalUsageEntry] = []
    for (app, package), item in ordered[:safe_limit]:
        # 按设备秒数倒序，图里切段要用喵
        per_device = sorted(item["per_device"].items(), key=lambda pair: (-pair[1], pair[0]))  # type: ignore[union-attr]
        # 组装条目喵
        result.append(
            GlobalUsageEntry(
                app=app,
                package=package,
                seconds=int(item["seconds"]),  # type: ignore[arg-type]
                device_count=len(per_device),
                devices=tuple(name_map.get(device_id, device_id) for device_id, _ in per_device),
                device_seconds=tuple(
                    (name_map.get(device_id, device_id), value) for device_id, value in per_device
                ),
            )
        )
    return result


def battery_series(
    connection: sqlite3.Connection,
    device_id: str,
    hours: int = 24,
    now: datetime | None = None,
) -> list[BatteryPoint]:
    """取时间窗口内的电量采样序列，用于看板画曲线喵。

    输入：连接、设备 ID、窗口小时数、可选基准时间。
    输出：按时间升序的 BatteryPoint 列表，没有数据时为空列表。
    """
    # 计算窗口起点喵
    window_start = hours_ago_text(hours, now)
    # 按采样时间升序取点喵
    rows = connection.execute(
        """
        SELECT sampled_at, percent, charging FROM battery_samples
        WHERE device_id = ? AND sampled_at >= ?
        ORDER BY sampled_at ASC
        """,
        (device_id, window_start),
    ).fetchall()
    # 逐行转换成对象喵
    return [
        BatteryPoint(
            sampled_at=parse_utc_text(row["sampled_at"]),
            percent=int(row["percent"]),
            charging=bool(row["charging"]),
        )
        for row in rows
    ]


def usage_timeline(
    connection: sqlite3.Connection,
    device_id: str,
    hours: int = 24,
    now: datetime | None = None,
) -> list[UsageBucket]:
    """按小时汇总使用时长，用于看板画时间轴喵。

    输入：连接、设备 ID、窗口小时数、可选基准时间。
    输出：按时间升序的 UsageBucket 列表。
    边界：时间文本被改坏的行会被跳过，不影响其它数据喵。
    """
    # 计算窗口起点喵
    window_start = hours_ago_text(hours, now)
    # 用时间文本前 13 个字符（YYYY-MM-DDTHH）作为小时桶喵
    rows = connection.execute(
        """
        SELECT substr(sampled_at, 1, 13) AS bucket, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE device_id = ? AND sampled_at >= ?
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        (device_id, window_start),
    ).fetchall()
    # 收集结果喵
    buckets: list[UsageBucket] = []
    for row in rows:
        try:
            # 桶文本还原成带时区的时间喵
            bucket_start = datetime.strptime(str(row["bucket"]), "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        except ValueError:
            # 喵~防御：坏数据跳过，不让一个异常拖垮整个看板喵
            continue
        # 组装对象喵
        buckets.append(UsageBucket(bucket_start=bucket_start, seconds=int(row["total_seconds"])))
    return buckets


def dashboard_devices(connection: sqlite3.Connection, now: datetime | None = None) -> list[DashboardDevice]:
    """组装看板所需的设备卡片列表喵。

    输入：连接、可选基准时间。
    输出：按最近上报排序的 DashboardDevice 列表。
    """
    # 结果列表喵
    cards: list[DashboardDevice] = []
    # 逐台设备组装，设备数量有限，多几次查询换代码清晰喵
    for summary in list_devices(connection):
        # 取近 24 小时排行喵
        ranking = usage_ranking(connection, summary.device_id, hours=24, now=now)
        # 取详情里的电量与当前应用喵
        detail = get_device(connection, summary.device_id)
        # 喵~防御：详情查询失败时跳过这台设备喵
        if detail is None:
            continue
        # 组装卡片喵
        cards.append(
            DashboardDevice(
                summary=summary,
                battery=detail.battery,
                current_app=detail.current_app,
                usage_total_seconds=sum(item.seconds for item in ranking),
                usage_top=tuple(ranking[:5]),
            )
        )
    return cards


def set_device_role(connection: sqlite3.Connection, device_id: str, role: str) -> bool:
    """修改设备角色（看板里标记服务器/工作站）喵。

    输入：连接、设备 ID、目标角色。
    输出：是否更新到了设备；设备不存在时返回 False。
    """
    # 直接更新角色列喵
    cursor = connection.execute("UPDATE devices SET role = ? WHERE device_id = ?", (role, device_id))
    # 提交事务喵
    connection.commit()
    # rowcount 为 0 说明没有这台设备喵
    return cursor.rowcount > 0


def prune_expired(
    connection: sqlite3.Connection,
    detail_days: int,
    aggregate_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """删除过期数据，返回各表删除行数喵。

    输入：连接、明细保留天数、聚合保留天数。
    输出：形如 {"reports": 3, "usage_samples": 10, "battery_samples": 2} 的字典。
    边界：两个天数参数都会先做下限保护，避免传 0 时把当天数据全删喵。
    """
    # 明细截止时间：早于这个时间的原始上报会被删除喵
    detail_cutoff = days_ago_text(detail_days, now)
    # 聚合截止时间喵
    aggregate_cutoff = days_ago_text(aggregate_days, now)
    # 记录各表删除行数喵
    deleted_counts: dict[str, int] = {}
    # 删除过期原始上报喵
    cursor = connection.execute("DELETE FROM reports WHERE reported_at < ?", (detail_cutoff,))
    deleted_counts["reports"] = cursor.rowcount if cursor.rowcount > 0 else 0
    # 删除过期使用时长喵
    cursor = connection.execute("DELETE FROM usage_samples WHERE sampled_at < ?", (aggregate_cutoff,))
    deleted_counts["usage_samples"] = cursor.rowcount if cursor.rowcount > 0 else 0
    # 删除过期电量采样喵
    cursor = connection.execute("DELETE FROM battery_samples WHERE sampled_at < ?", (aggregate_cutoff,))
    deleted_counts["battery_samples"] = cursor.rowcount if cursor.rowcount > 0 else 0
    # 提交删除事务喵
    connection.commit()
    return deleted_counts


def touch_last_seen(connection: sqlite3.Connection, device_id: str, moment: datetime) -> None:
    """把设备最近上报时间更新到指定时刻（仅用于内部维护与测试）喵。"""
    # 直接更新，不存在的设备不会报错喵
    connection.execute("UPDATE devices SET last_seen_at = ? WHERE device_id = ?", (to_utc_text(moment), device_id))
    # 提交事务喵
    connection.commit()
