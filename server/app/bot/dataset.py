"""模板的数据层：把查询结果摊平成模板能直接取用的记录。

职责边界：
- 定义数据集（设备 / 排行 / 总排行 / 电量 / 当前）的字段与可用筛选；
- 执行 `{查询 …}` 里的筛选、排序、截断与聚合；
- 不负责排版，也不产生任何 QQ 可见文案（文案都在 commands 模块里）喵。

「当前」数据集是个特殊入口：它把作用域里已经算好的列表（例如帮助行、分页后的排行）
当成数据集来筛排序截断，这样模板只有一种循环写法，不用记两套语法喵。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .. import queries
from ..db import parse_utc_text, utc_now
from ..gating import reason_text
from . import expr

# 设备数据集喵
DATASET_DEVICES = "设备"
# 单设备排行数据集喵
DATASET_RANKING = "排行"
# 跨设备总排行数据集喵
DATASET_GLOBAL = "总排行"
# 电量采样数据集喵
DATASET_BATTERY = "电量"
# 作用域里现成列表的入口喵
DATASET_SCOPE = "当前"

# 支持的数据集，写错时提示里会列出这几项喵
DATASETS: tuple[str, ...] = (
    DATASET_DEVICES,
    DATASET_RANKING,
    DATASET_GLOBAL,
    DATASET_BATTERY,
    DATASET_SCOPE,
)

# 平台英文值到中文展示名喵
PLATFORM_LABELS: dict[str, str] = {"windows": "Windows", "android": "Android"}

# 设备角色到中文说明喵
ROLE_LABELS: dict[str, str] = {"workstation": "工作站", "server": "服务器"}

# 硬件字段到中文标签，与老版本 render 里的映射保持一致喵
HARDWARE_LABELS: dict[str, str] = {
    "os_version": "系统版本",
    "cpu": "处理器",
    "ram_gb": "内存(GB)",
    "gpu": "显卡",
    "disk": "磁盘",
    "hostname": "主机名",
    "manufacturer": "厂商",
    "model": "型号",
    "android_version": "Android 版本",
    "sdk_int": "SDK 版本",
    "screen": "屏幕",
}

# 布尔筛选值的中文写法喵
TRUE_WORDS = frozenset({"是", "1", "true", "yes", "on", "有"})


class DatasetError(expr.QueryError):
    """查询参数不合法（数据集名、筛选键、排序键写错等）喵。"""


# 模板行的类型别名：字段名是英文键，值可以是任意类型喵
DeviceRow = dict[str, Any]


@dataclass(frozen=True)
class QueryContext:
    """一次查询需要的上下文喵。"""

    # 数据库连接，只读使用喵
    connection: sqlite3.Connection
    # 基准时间，保证同一条命令里所有查询的时间口径一致喵
    now: datetime


def _as_bool_text(value: str) -> bool:
    """把中文布尔写法转成布尔值喵。"""
    # 统一小写并去掉空白喵
    return value.strip().lower() in TRUE_WORDS


def list_device_rows(
    connection: sqlite3.Connection,
    now: datetime,
    max_hardware_fields: int = 8,
) -> list[dict[str, Any]]:
    """把全部设备转成模板行喵。

    输入：连接、基准时间、硬件字段展示上限。
    输出：每台设备一个字典，字段名与 expr.ALIASES 对应。
    边界：没有设备时返回空列表喵。
    """
    # 喵~防御：设备数很少，逐台取详情可以接受；将来设备多了再改成批量查询喵
    return [
        row
        for row in (
            device_detail_row(connection, summary.device_id, now, max_hardware_fields)
            for summary in queries.list_devices(connection)
        )
        if row is not None
    ]


def device_detail_row(
    connection: sqlite3.Connection,
    device_id: str,
    now: datetime,
    max_hardware_fields: int = 8,
) -> dict[str, Any] | None:
    """把一台设备摊平成模板行喵。

    输入：连接、设备 ID、基准时间、硬件字段展示上限。
    输出：模板行字典；设备不存在时返回 None。
    边界：电量与当前应用缺失时用「有*」布尔字段标记，模板据此走 {若} 分支喵。
    """
    # 取设备详情喵
    detail = queries.get_device(connection, device_id)
    # 喵~防御：设备可能刚被清理掉喵
    if detail is None:
        return None
    # 复用对象摊平逻辑，避免两处字段各写一遍喵
    return device_row_from_detail(detail, now, max_hardware_fields)


def ranking_rows(
    connection: sqlite3.Connection,
    device_id: str,
    hours: int,
    seconds: int,
    now: datetime,
    device_name: str = "",
) -> list[dict[str, Any]]:
    """取一台设备在窗口内的应用排行行喵。

    输入：连接、设备 ID、窗口小时数、窗口秒数、基准时间、设备展示名。
    输出：模板行列表，含占比与序号。
    边界：没有数据时返回空列表喵。
    """
    # 取窗口内的应用排行喵
    entries = queries.usage_ranking_window(connection, device_id, hours=hours, seconds=seconds, now=now)
    # 合计秒数用于算占比，喵~防御：0 会让除法炸掉，这里至少取 1 喵
    total_seconds = max(1, sum(entry.seconds for entry in entries))
    # 逐条转成模板行喵
    return [
        {
            "rank": index,
            "app": entry.app,
            "package": entry.package,
            "seconds": entry.seconds,
            "percent": entry.seconds * 100.0 / total_seconds,
            "device": device_name,
        }
        for index, entry in enumerate(entries, start=1)
    ]


def global_ranking_rows(
    connection: sqlite3.Connection,
    hours: int,
    seconds: int,
    limit: int,
    now: datetime,
    device_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """取跨设备总排行行喵。

    输入：连接、窗口小时数、窗口秒数、条数上限、基准时间、可选设备范围。
    输出：模板行列表，含设备台数与设备名列表。
    边界：纯秒级窗口走另一条聚合路径，保证「最近 1 分钟」也能用；
          device_ids 为 None 表示全部设备，为空列表表示没有设备可查喵。
    """
    # 喵~防御：条数上限夹到合法范围，避免一次拉爆喵
    safe_limit = max(1, min(200, int(limit)))
    # 有设备范围时走限定范围的聚合路径喵
    if device_ids is not None:
        return _global_rows_scoped(connection, device_ids, hours, seconds, safe_limit, now)
    # 纯秒级窗口不能直接用按小时的口径，单独聚合喵
    if hours <= 0 and seconds > 0:
        return _global_rows_by_seconds(connection, seconds, safe_limit, now)
    # 按小时口径直接复用现成查询喵
    entries = queries.global_usage_ranking(connection, hours=hours, limit=safe_limit, now=now)
    # 合计秒数用于算占比喵
    total_seconds = max(1, sum(entry.seconds for entry in entries))
    # 逐条转成模板行喵
    return [
        {
            "rank": index,
            "app": entry.app,
            "package": entry.package,
            "seconds": entry.seconds,
            "percent": entry.seconds * 100.0 / total_seconds,
            "device_count": entry.device_count,
            "devices": list(entry.devices),
            "device_seconds": list(entry.device_seconds),
        }
        for index, entry in enumerate(entries, start=1)
    ]


def _global_rows_scoped(
    connection: sqlite3.Connection,
    device_ids: Sequence[str],
    hours: int,
    seconds: int,
    limit: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """只在给定设备范围内聚合跨设备排行喵。

    输入：连接、设备 ID 列表、窗口小时数、窗口秒数、条数上限、基准时间。
    输出：模板行列表，结构与非限定范围版本一致。
    边界：设备列表为空时返回空列表；同名应用跨设备合并成一行喵。
    """
    # 喵~防御：没有设备可查时直接返回空列表喵
    ids = [str(item) for item in device_ids if str(item)]
    if not ids:
        return []
    # 计算窗口起点文本喵
    if hours > 0:
        window_start = queries.usage_window_start(hours, 0, now)
    else:
        window_start = queries.usage_window_start(0, max(1, seconds), now)
    # 按设备占位符喵
    placeholders = ",".join("?" for _ in ids)
    # 按「应用 + 设备」聚合，方便后面切段喵
    rows = connection.execute(
        f"""
        SELECT app_name, package, device_id, SUM(seconds) AS total_seconds
        FROM usage_samples
        WHERE sampled_at >= ? AND device_id IN ({placeholders})
        GROUP BY app_name, package, device_id
        HAVING total_seconds > 0
        """,
        (window_start, *ids),
    ).fetchall()
    # 设备 ID 到展示名映射喵
    name_map = queries.device_name_map(connection)
    # 先按应用合并喵
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        # 应用键：名称 + 包名喵
        key = (str(row["app_name"]), str(row["package"] or ""))
        # 取或建条目喵
        item = merged.setdefault(key, {"app": key[0], "package": key[1], "seconds": 0, "per_device": {}})
        # 累加总秒数喵
        item["seconds"] += int(row["total_seconds"])
        # 记下这台设备的秒数喵
        device_id = str(row["device_id"])
        item["per_device"][device_id] = item["per_device"].get(device_id, 0) + int(row["total_seconds"])
    # 按总时长倒序排序喵
    ordered = sorted(merged.values(), key=lambda item: (-int(item["seconds"]), str(item["app"])))
    # 截断到上限喵
    ordered = ordered[:limit]
    # 合计秒数用于算占比喵
    total_seconds = max(1, sum(int(item["seconds"]) for item in ordered))
    # 逐条组装模板行喵
    result: list[dict[str, Any]] = []
    for index, item in enumerate(ordered, start=1):
        # 每台设备的秒数按倒序排列，供画图切段喵
        per_device = sorted(item["per_device"].items(), key=lambda pair: (-pair[1], pair[0]))
        result.append(
            {
                "rank": index,
                "app": item["app"],
                "package": item["package"],
                "seconds": int(item["seconds"]),
                "percent": int(item["seconds"]) * 100.0 / total_seconds,
                "device_count": len(per_device),
                "devices": [name_map.get(device_id, device_id) for device_id, _ in per_device],
                "device_seconds": [(name_map.get(device_id, device_id), value) for device_id, value in per_device],
            }
        )
    return result


def _global_rows_by_seconds(
    connection: sqlite3.Connection,
    seconds: int,
    limit: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """按秒级窗口聚合跨设备排行喵。"""
    # 计算窗口起点喵
    window_start = queries.usage_window_start(0, seconds, now)
    # 分组求和，同时统计设备台数喵
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
        (window_start, limit),
    ).fetchall()
    # 设备 ID 到展示名映射，一次查完喵
    name_map = queries.device_name_map(connection)
    # 合计秒数用于算占比喵
    total_seconds = max(1, sum(int(row["total_seconds"]) for row in rows))
    # 逐行组装喵
    return [
        {
            "rank": index,
            "app": str(row["app_name"]),
            "package": str(row["package"] or ""),
            "seconds": int(row["total_seconds"]),
            "percent": int(row["total_seconds"]) * 100.0 / total_seconds,
            "device_count": int(row["device_count"]),
            "devices": [
                name_map.get(item.strip(), item.strip())
                for item in str(row["device_ids"] or "").split(",")
                if item.strip()
            ],
        }
        for index, row in enumerate(rows, start=1)
    ]


def battery_rows(
    connection: sqlite3.Connection,
    device_id: str,
    limit: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """取一台设备最近的电量采样行喵。

    输入：连接、设备 ID、条数上限、基准时间。
    输出：模板行列表，按时间倒序。
    边界：没有电量记录（Windows 设备）时返回空列表喵。
    """
    # 按时间倒序取若干条喵
    rows = connection.execute(
        "SELECT percent, charging, sampled_at FROM battery_samples WHERE device_id = ? ORDER BY sampled_at DESC LIMIT ?",
        (device_id, max(1, min(200, int(limit)))),
    ).fetchall()
    # 逐行组装喵
    return [
        {
            "rank": index,
            "percent": int(row["percent"]),
            "charging": bool(row["charging"]),
            "battery_text": "充电中" if bool(row["charging"]) else "未充电",
            "sampled_at": parse_utc_text(str(row["sampled_at"])),
            "device": device_id,
        }
        for index, row in enumerate(rows, start=1)
    ]


def devices_with_usage(
    connection: sqlite3.Connection,
    hours: int = 0,
    seconds: int = 0,
    now: datetime | None = None,
) -> set[str]:
    """列出窗口内有使用记录的设备 ID 喵。"""
    # 直接复用查询层实现喵
    return queries.devices_with_usage(connection, hours=hours, seconds=seconds, now=now)


def device_usage_totals(
    connection: sqlite3.Connection,
    hours: int = 0,
    seconds: int = 0,
    now: datetime | None = None,
) -> dict[str, int]:
    """按设备汇总窗口内的使用总秒数喵。"""
    # 直接复用查询层实现喵
    return queries.device_usage_totals(connection, hours=hours, seconds=seconds, now=now)


def device_row_from_detail(
    detail: "queries.DeviceDetail",
    now: datetime,
    max_hardware_fields: int = 8,
) -> DeviceRow:
    """把已经取到的详情对象摊平成模板行，避免重复查库喵。

    输入：设备详情对象、基准时间、硬件字段展示上限。
    输出：模板行字典。
    边界：仅供兼容层与图片渲染使用；正常命令路径请用 device_detail_row喵。
    """
    # 概要信息喵
    summary = detail.summary
    # 在线状态喵
    online = queries.is_online(summary.last_seen_at, now)
    # 电量快照喵
    battery = detail.battery
    # 当前应用快照喵
    current_app = detail.current_app
    # 当前应用已持续秒数喵
    current_seconds = 0
    if current_app is not None and current_app.since is not None:
        # 喵~防御：时钟回拨时可能为负，按 0 处理喵
        current_seconds = max(0, int((now - current_app.since).total_seconds()))
    # 硬件信息转成中文行喵
    hardware_lines: list[str] = []
    for key, value in list(detail.hardware.items())[: max(1, max_hardware_fields)]:
        # 已知键名换中文标签，未知键名原样展示喵
        hardware_lines.append(f"{HARDWARE_LABELS.get(key, key)}：{value}")
    # 组装模板行喵
    return {
        "id": summary.device_id,
        "name": summary.display_name,
        "platform": PLATFORM_LABELS.get(summary.platform, summary.platform),
        "platform_raw": summary.platform,
        "os_version": summary.os_version or "未知",
        "online": online,
        "status": "在线" if online else "离线",
        "role": summary.role,
        "role_text": ROLE_LABELS.get(summary.role, summary.role),
        "rdp_text": "已连接" if summary.rdp_connected else "未连接",
        "paused_text": reason_text(summary.stats_paused_reason) if summary.stats_paused_reason else "",
        "last_seen": summary.last_seen_at,
        "has_battery": battery is not None,
        "battery_percent": battery.percent if battery is not None else 0,
        "battery_text": ("充电中" if battery.charging else "未充电") if battery is not None else "",
        "has_current_app": current_app is not None,
        "current_app": current_app.name if current_app is not None else "",
        "current_app_seconds": current_seconds,
        "has_hardware": bool(hardware_lines),
        "hardware": hardware_lines,
        "usage_total": detail.usage_total_seconds,
        "mirrored": list(detail.mirrored_tags),
        "mirror_foreground": detail.mirror_foreground,
        # 列表里的序号由调用方补齐，这里是占位喵
        "rank": 0,
    }


def _match_devices(devices: Sequence[dict[str, Any]], token: str) -> list[dict[str, Any]]:
    """按设备 ID 或唯一前缀筛选设备行喵。

    输入：全部设备行、用户输入的标识。
    输出：匹配的设备行；前缀命中多台时返回全部，交给调用方决定怎么提示。
    边界：空标识返回空列表喵。
    """
    # 喵~防御：空标识不匹配任何设备喵
    cleaned = token.strip().lower()
    if not cleaned:
        return []
    # 先做精确匹配喵
    exact = [row for row in devices if str(row["id"]).lower() == cleaned]
    if exact:
        return exact
    # 再做前缀匹配喵
    return [row for row in devices if str(row["id"]).lower().startswith(cleaned)]


def _parse_window(options: Mapping[str, str]) -> tuple[int, int]:
    """从选项里解析时间窗口，返回 (小时, 秒)喵。

    输入：查询选项。
    输出：(小时, 秒)。
    边界：支持 `最近=90秒`、`窗口=2小时`、`小时=24` 三种写法喵。
    """
    # 优先看「最近」与「窗口」两个中文键喵
    for key in ("最近", "窗口"):
        raw = options.get(key, "").strip()
        if not raw:
            continue
        # 纯数字按秒处理，写「1分钟」这类带单位的按单位换算喵
        parsed = expr.parse_duration_text(raw)
        # 喵~防御：写法不对时明确报错，不要静默当成 24 小时喵
        if parsed is None:
            raise DatasetError(f"{key} 的写法看不懂：{raw}（例：1分钟 / 90秒 / 2小时）")
        return 0, parsed
    # 兼容按小时写窗口喵
    raw_hours = options.get("小时", "").strip()
    if raw_hours:
        try:
            return max(0, int(raw_hours)), 0
        except ValueError as error:
            raise DatasetError(f"小时 必须是整数，收到 {raw_hours}") from error
    # 默认 24 小时，与看板口径一致喵
    return 24, 0


def _sort_rows(rows: list[dict[str, Any]], options: Mapping[str, str], default_key: str) -> list[dict[str, Any]]:
    """按选项排序喵。

    输入：行列表、查询选项、默认排序键。
    输出：排好序的新列表。
    边界：排序键不存在时改按默认键；默认倒序，写「正序」反转喵。
    """
    # 排序键，缺省用调用方给的默认键喵
    key = options.get("按", default_key).strip() or default_key
    # 中文列名先翻译成真实字段名喵
    key = expr.ALIASES.get(key, key)
    # 喵~防御：排序键不认识时退回默认键，不让整条命令失败喵
    if rows and key not in rows[0]:
        key = default_key
    # 升序标志喵
    ascending = "正序" in options or "升序" in options

    def sort_key(row: dict[str, Any]) -> tuple[int, Any]:
        """把值转成可比较的键，避免 int 与 str 混排抛 TypeError喵。"""
        value = row.get(key)
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))
        if isinstance(value, datetime):
            return (0, value.timestamp())
        return (1, str(value))

    return sorted(rows, key=sort_key, reverse=not ascending)


def _limit_rows(rows: list[dict[str, Any]], options: Mapping[str, str]) -> list[dict[str, Any]]:
    """按「前=」截断行数喵。"""
    # 取条数参数喵
    raw_limit = options.get("前", "").strip()
    # 没写就不截断喵
    if not raw_limit:
        return rows
    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise DatasetError(f"前 必须是整数，收到 {raw_limit}") from error
    # 喵~防御：0 表示不限，负数按空结果处理喵
    if limit == 0:
        return rows
    if limit < 0:
        return []
    return rows[:limit]


def _aggregate(rows: Sequence[dict[str, Any]], options: Mapping[str, str]) -> Any:
    """处理聚合关键字，没有聚合时返回 None 喵。

    输入：行列表、查询选项。
    输出：聚合值；没有聚合关键字时返回 None。
    边界：合计/最大/平均需要 `合计=字段` 这种写法指明字段；字段不存在时报错喵。
    """
    # 计数最常用，允许简写喵
    if "计数" in options:
        return len(rows)
    # 其余聚合都要指明字段喵
    for keyword, reducer in (
        ("合计", lambda values: sum(values)),
        ("最大", lambda values: max(values) if values else 0.0),
        ("平均", lambda values: (sum(values) / len(values)) if values else 0.0),
    ):
        # 没写这个关键字就跳过喵
        if keyword not in options:
            continue
        # 取字段名，中文列名同样翻译一次喵
        raw_field = options.get(keyword, "").strip()
        # 喵~防御：写了关键字却没写字段，属于模板写错喵
        if not raw_field:
            raise DatasetError(f"{keyword} 需要在等号后写字段名，例如 {keyword}=时长")
        field_name = expr.ALIASES.get(raw_field, raw_field)
        # 收集数值喵
        values: list[float] = []
        for row in rows:
            value = row.get(field_name)
            if isinstance(value, bool):
                values.append(1.0 if value else 0.0)
                continue
            if isinstance(value, (int, float)):
                values.append(float(value))
        # 取整返回，避免出现 3600.0 这种写法喵
        result = reducer(values)
        return int(result) if float(result) == int(result) else result
    return None


def _query_scope_list(
    options: Mapping[str, str],
    scopes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """从作用域里取现成列表喵。

    输入：查询选项、作用域链。
    输出：行列表，自动补上序号。
    边界：列表名不存在或不是列表时抛 DatasetError喵。
    """
    # 列表名必填喵
    list_name = options.get("列表", "").strip()
    if not list_name:
        raise DatasetError("当前 数据集需要用 列表=<变量名> 指明要遍历哪个列表")
    # 中文列表名先翻译成作用域里的英文键喵
    list_name = expr.ALIASES.get(list_name, list_name)
    # 在作用域链上取列表喵
    value = expr.resolve(list_name, scopes)
    # 喵~防御：取不到或不是列表时明确报错喵
    if value is expr.MISSING:
        raise DatasetError(f"作用域里没有列表 {list_name}")
    if not isinstance(value, (list, tuple)):
        raise DatasetError(f"{list_name} 不是列表，不能遍历")
    # 统一转成字典行，并补上序号喵
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        row = dict(item) if isinstance(item, Mapping) else {"值": item}
        row.setdefault("rank", index)
        rows.append(row)
    return rows


def run_query(
    context: QueryContext,
    dataset_name: str,
    options: Mapping[str, str],
    scopes: Sequence[Mapping[str, Any]] = (),
) -> Any:
    """执行一次查询，返回行列表或聚合值喵。

    输入：查询上下文、数据集名、选项键值对、作用域链（当前数据集要用）。
    输出：模板行列表，或聚合标量。
    边界：数据集名、筛选键、排序键写错时抛 DatasetError喵。
    """
    # 去掉键与值的空白喵
    normalized = {key.strip(): value.strip() for key, value in options.items()}
    # 计算时间窗口喵
    hours, seconds = _parse_window(normalized)
    # 按数据集分派喵
    if dataset_name == DATASET_SCOPE:
        rows = _query_scope_list(normalized, scopes)
    elif dataset_name == DATASET_DEVICES:
        rows = _query_devices(context, normalized)
    elif dataset_name == DATASET_RANKING:
        rows = _query_ranking(context, normalized, hours, seconds)
    elif dataset_name == DATASET_GLOBAL:
        rows = _query_global(context, normalized, hours, seconds)
    elif dataset_name == DATASET_BATTERY:
        rows = _query_battery(context, normalized)
    else:
        raise DatasetError(f"不认识的数据集：{dataset_name}（可用：{'、'.join(DATASETS)}）")
    # 聚合优先于排序与截断喵
    aggregated = _aggregate(rows, normalized)
    if aggregated is not None:
        return aggregated
    # 排序后截断喵
    default_key = "最近上报" if dataset_name == DATASET_DEVICES else "时长"
    return _limit_rows(_sort_rows(rows, normalized, expr.ALIASES.get(default_key, default_key)), normalized)


def _query_devices(
    context: QueryContext,
    options: Mapping[str, str],
) -> list[dict[str, Any]]:
    """执行设备数据集查询喵。"""
    # 取全部设备行喵
    rows = list_device_rows(context.connection, context.now)
    # 按设备标识筛选喵
    token = options.get("设备", "").strip()
    if token:
        rows = _match_devices(rows, token)
    # 按平台筛选喵
    platform = options.get("平台", "").strip().lower()
    if platform:
        rows = [row for row in rows if str(row["platform_raw"]).lower() == platform]
    # 按角色筛选喵
    role = options.get("角色", "").strip().lower()
    if role:
        rows = [row for row in rows if str(row["role"]).lower() == role]
    # 按在线状态筛选喵
    online_text = options.get("在线", "").strip()
    if online_text:
        want_online = _as_bool_text(online_text)
        rows = [row for row in rows if bool(row["online"]) is want_online]
    # 按「活跃」筛选：最近上报时间在窗口内喵
    active_text = options.get("活跃", "").strip()
    if active_text:
        window_seconds = expr.parse_duration_text(active_text)
        # 喵~防御：窗口写法不对时明确报错喵
        if window_seconds is None:
            raise DatasetError(f"活跃 的写法看不懂：{active_text}（例：1分钟）")
        rows = [row for row in rows if (context.now - row["last_seen"]).total_seconds() <= window_seconds]
    # 按「有使用」筛选：窗口内有使用记录喵
    usage_text = options.get("有使用", "").strip()
    if usage_text:
        window_seconds = expr.parse_duration_text(usage_text)
        # 喵~防御：窗口写法不对时明确报错喵
        if window_seconds is None:
            raise DatasetError(f"有使用 的写法看不懂：{usage_text}（例：1分钟）")
        # 取窗口内有使用记录的设备 ID 集合喵
        active_ids = queries.devices_with_usage(context.connection, seconds=window_seconds, now=context.now)
        rows = [row for row in rows if str(row["id"]) in active_ids]
        # 顺便把这批设备在窗口内的使用时长算好，模板里直接用 {使用时长} 喵
        totals = queries.device_usage_totals(context.connection, seconds=window_seconds, now=context.now)
        for row in rows:
            row["usage_total"] = totals.get(str(row["id"]), 0)
    # 按名称或 ID 模糊匹配喵
    keyword = options.get("匹配", "").strip()
    if keyword:
        lowered = keyword.lower()
        rows = [
            row for row in rows if lowered in str(row["name"]).lower() or lowered in str(row["id"]).lower()
        ]
    # 喵~注意：设备数据集的时间筛选由 活跃= 与 有使用= 各自指定，不吃全局窗口喵
    return rows


def _query_ranking(
    context: QueryContext,
    options: Mapping[str, str],
    hours: int,
    seconds: int,
) -> list[dict[str, Any]]:
    """执行单设备排行查询喵。"""
    # 设备标识是必填项，没有就不知道该查谁喵
    token = options.get("设备", "").strip()
    if not token:
        raise DatasetError("排行 需要用 设备=<设备ID> 指定一台设备")
    # 按前缀找设备喵
    matched = _match_devices(list_device_rows(context.connection, context.now), token)
    # 喵~防御：找不到或多台时给出明确提示喵
    if not matched:
        raise DatasetError(f"未找到设备 {token}")
    if len(matched) > 1:
        raise DatasetError(f"设备前缀 {token} 匹配到 {len(matched)} 台设备，请输入更完整的 ID")
    # 取真实设备 ID 与展示名喵
    device_id = str(matched[0]["id"])
    # 取排行行喵
    rows = ranking_rows(
        context.connection, device_id, hours, seconds, context.now, device_name=str(matched[0]["name"])
    )
    # 按应用名筛选喵
    app_filter = options.get("应用", "").strip()
    if app_filter:
        lowered = app_filter.lower()
        rows = [row for row in rows if lowered in str(row["app"]).lower()]
    # 按最短时长筛选喵
    minimum_text = options.get("至少", "").strip()
    if minimum_text:
        minimum_seconds = expr.parse_duration_text(minimum_text)
        # 喵~防御：写法不对时明确报错喵
        if minimum_seconds is None:
            raise DatasetError(f"至少 的写法看不懂：{minimum_text}")
        rows = [row for row in rows if int(row["seconds"]) >= minimum_seconds]
    return rows


def _query_global(
    context: QueryContext,
    options: Mapping[str, str],
    hours: int,
    seconds: int,
) -> list[dict[str, Any]]:
    """执行总排行查询喵。"""
    # 条数上限先取一个足够大的值，真正的截断交给 _limit_rows 统一处理喵
    rows = global_ranking_rows(context.connection, hours, seconds, 200, context.now)
    # 按设备台数筛选喵
    min_devices = options.get("设备数", "").strip()
    if min_devices:
        try:
            threshold = int(min_devices)
        except ValueError as error:
            raise DatasetError(f"设备数 必须是整数，收到 {min_devices}") from error
        rows = [row for row in rows if int(row["device_count"]) >= threshold]
    # 按应用名筛选喵
    app_filter = options.get("应用", "").strip()
    if app_filter:
        lowered = app_filter.lower()
        rows = [row for row in rows if lowered in str(row["app"]).lower()]
    return rows


def _query_battery(
    context: QueryContext,
    options: Mapping[str, str],
) -> list[dict[str, Any]]:
    """执行电量采样查询喵。"""
    # 设备标识是必填项喵
    token = options.get("设备", "").strip()
    if not token:
        raise DatasetError("电量 需要用 设备=<设备ID> 指定一台设备")
    # 按前缀找设备喵
    matched = _match_devices(list_device_rows(context.connection, context.now), token)
    # 喵~防御：找不到或多台时明确提示喵
    if not matched:
        raise DatasetError(f"未找到设备 {token}")
    if len(matched) > 1:
        raise DatasetError(f"设备前缀 {token} 匹配到 {len(matched)} 台设备，请输入更完整的 ID")
    # 取条数上限喵
    try:
        limit = int(options.get("前", "").strip() or 20)
    except ValueError as error:
        raise DatasetError("前 必须是整数") from error
    return battery_rows(context.connection, str(matched[0]["id"]), limit, context.now)


class TemplateEnv:
    """渲染环境：持有片段表与查询能力，供 expr.render 调用喵。"""

    def __init__(
        self,
        fragments: Mapping[str, Sequence[Any]],
        context: QueryContext,
    ) -> None:
        # 片段名到节点树的映射喵
        self._fragments = dict(fragments)
        # 查询上下文喵
        self._context = context

    def fragment(self, name: str) -> tuple[Any, ...] | None:
        """按名字取片段节点树喵。"""
        # 取不到时返回 None，由 expr 层报错喵
        found = self._fragments.get(name)
        return None if found is None else tuple(found)

    def query(
        self,
        dataset_name: str,
        options: Mapping[str, str],
        scopes: Sequence[Mapping[str, Any]],
        depth: int,
    ) -> Any:
        """执行查询喵。"""
        # 合并作用域里的变量到选项，支持 `设备={参数1}` 这种动态筛选喵
        resolved: dict[str, str] = {}
        for key, value in options.items():
            # 喵~防御：值里带占位符时先渲染一次，支持动态参数喵
            if "{" in value:
                value = expr.render(expr.parse(value).nodes, scopes, self, depth + 1)
            resolved[key] = value
        # 交给数据集层执行喵
        return run_query(self._context, dataset_name, resolved, scopes)


def make_context(connection: sqlite3.Connection, now: datetime | None = None) -> QueryContext:
    """构造查询上下文喵。"""
    # 基准时间统一在这里兜底喵
    return QueryContext(connection=connection, now=now or utc_now())
