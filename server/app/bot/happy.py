"""happy 系列命令的数据准备：主人设备组的状态判定与优先级选择。

为什么单独一个模块：这一族命令共用一个「happy 是谁」的答案（固定是「主人」组），
判定规则（最近 3 分钟有行为 / 挂机 / 都不满足）又比普通命令复杂得多，
塞进 commands.py 会把它撑爆，所以单独放这里喵。

三条判据的方向说明：
- 「有行为」看 usage_samples 而不是心跳——心跳只证明设备开着，使用记录才证明人在用喵；
- 「挂机」看空档时长——设备在线、但距最后一次使用不到 10 分钟，就是时间轴上那段斜纹喵；
- 「不在」看空档超过 10 分钟，用最后一笔使用记录回答「最近一次上线」喵。

喵~注意：「空档」与客户端自报的 `afk` 标记不是一回事。空档的定义是「设备在线，
但这一分钟没有任何使用记录」，被门控暂停计时（投屏、RDP 未连接）时客户端 `afk=false`，
时间轴照样画斜纹，所以判定挂机不能看那个标记，只能看空档本身有多长喵。

喵~注意：所有判定都以调用方传进来的 now 为准，不在模块里读真实时钟，
否则单元测试没法把时间钉死喵。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import people, queries
from ..config import AppConfig
from ..db import parse_utc_text, to_utc_text

# happy 默认绑定的设备组名，真正生效的组名从配置读喵
# 喵~注意：保留这个常量只作默认值与错误提示用，实际判断一律走 resolve_group_name喵
HAPPY_GROUP_NAME = "happy"

# 「正在使用」的判定窗口：最近 3 分钟内有使用记录喵
ACTIVE_WINDOW_SECONDS = 3 * 60

# 「挂机」的判定窗口：在线但空档（无使用记录）不超过 10 分钟喵
AFK_WINDOW_SECONDS = 10 * 60

# 窗口内累计使用达到这么久（秒）才算「有行为」，避免一次误采样就点亮状态喵
MIN_ACTIVITY_SECONDS = 10

# 「当前应用已持续多久」的上限：超过就按取不到处理喵
# 喵~注意：since 只在应用切换时重置，长时间不换应用会一直累加；而 current_app_json
# 是 COALESCE 保留的快照，客户端偶尔不带时会留成几天前的旧值。上限用来挡住这两种
# 明显失真的情况，宁可少一行也不报「已持续 120 小时」这种数喵
MAX_CURRENT_APP_SECONDS = 24 * 3600

# 状态：正在使用喵
STATE_ACTIVE = "active"
# 状态：挂机喵
STATE_AFK = "afk"
# 状态：不在喵
STATE_AWAY = "away"


class HappyError(LookupError):
    """设备组缺失或配置不对，消息本身就是给用户看的中文提示喵。"""


@dataclass(frozen=True)
class HappyDevice:
    """happy 名下的一台设备及其实时状态喵。"""

    # 设备 ID 喵
    device_id: str
    # 展示名喵
    name: str
    # 平台原始值：windows / android 喵
    platform: str
    # 最近一次心跳喵
    last_seen: datetime | None
    # 现在是否在线（加载时按 now 算好）喵
    online: bool
    # 最近一次心跳里是否 AFK 喵
    # 喵~注意：这个标记只用来在「设备」列表里写「挂机」，判定三档状态不许看它喵
    afk: bool
    # 空档时长：距最后一次使用记录过了多少秒，从没用过时 None 喵
    # 喵~注意：这就是时间轴上那段斜纹的长度，是判定挂机/不在的唯一依据喵
    gap_seconds: int | None
    # 当前前台应用名喵
    current_app: str
    # 当前应用窗口标题，没有时为空串喵
    # 喵~注意：只有 Windows 端会采集标题，安卓端恒为空喵
    current_title: str
    # 当前应用已持续秒数喵
    current_seconds: int
    # 电量百分比，未知时 None 喵
    battery_percent: int | None
    # 是否充电中喵
    battery_charging: bool
    # 近 24 小时使用总秒数喵
    usage_24h_seconds: int
    # 最后一次有使用记录的时刻喵
    last_usage: datetime | None
    # 组内优先级，0 最优先喵
    priority: int


@dataclass(frozen=True)
class HappySnapshot:
    """主人的整体状态快照，模板直接取用喵。"""

    # 整体状态：active / afk / away 喵
    state: str
    # 当前该展示的那台设备，可能为 None 喵
    device: HappyDevice | None
    # 组内全部设备，按优先级排列喵
    devices: list[HappyDevice]
    # 最近一次有使用记录的时刻（跨设备取最大）喵
    last_usage_device: str
    # 最近一个有使用记录的设备名喵
    last_usage: datetime | None
    # 判定理由，写进日志便于排查喵
    reason: str


def resolve_group_name(config: AppConfig) -> str:
    """取出当前生效的 happy 设备组名喵。

    输入：服务端配置。
    输出：组名，缺配置时退回默认值。
    边界：配置里写了空白串时同样退回默认值，避免匹配到空组名喵。
    """
    # 喵~防御：老配置对象可能没有 bot 节，用 getattr 兜底喵
    section = getattr(config, "bot", None)
    name = getattr(section, "happy_group", "") if section is not None else ""
    return name.strip() or HAPPY_GROUP_NAME


def load_happy_devices(
    connection: sqlite3.Connection,
    config: AppConfig,
    now: datetime,
) -> list[HappyDevice]:
    """读出 happy 设备组里的全部设备，按组内顺序排列喵。

    输入：数据库连接、服务端配置、基准时间。
    输出：HappyDevice 列表，下标 0 优先级最高。
    边界：组不存在或组里没有任何已注册设备时抛 HappyError喵。
    """
    # 当前生效的组名喵
    group_name = resolve_group_name(config)
    # 读设备组喵
    groups = people.load_people(config.server.db_path)
    # 喵~防御：找不到目标组时给出可操作的提示喵
    target = next((group for group in groups if group.name.strip() == group_name), None)
    if target is None:
        available = "、".join(group.name for group in groups) or "（还没有任何设备组）"
        raise HappyError(
            f'没有叫「{group_name}」的设备组，happy 不知道该看谁。'
            f"请看板「设备组」里建一个名为「{group_name}」的组，"
            f"或改配置里的 bot.happy_group。可用：{available}"
        )
    # 喵~防御：组是空的同样没法回答喵
    if not target.devices:
        raise HappyError(f'设备组「{group_name}」里还没有设备，请先在看板里添加。')
    # 近 24 小时的使用总时长一次查完，避免逐台重复查库喵
    usage_totals = queries.device_usage_totals(connection, hours=24, now=now)
    # 逐台取详情，组内顺序即优先级喵
    devices: list[HappyDevice] = []
    for priority, device_id in enumerate(target.devices):
        # 取设备详情喵
        detail = queries.get_device(connection, device_id)
        # 喵~防御：设备可能已从库里清掉，跳过而不是整个报错喵
        if detail is None:
            continue
        # 应用名优先取最新使用采样，标题只能取上报快照喵
        reported_app = _latest_reported_app(connection, device_id)
        snapshot_app = detail.current_app.name if detail.current_app is not None else ""
        # 最终展示的应用名喵
        shown_app = reported_app or snapshot_app
        # 喵~注意：应用名和标题必须来自同一次上报，否则会出现「应用是 A、
        # 标题是 B 的窗口」这种自相矛盾的输出喵
        # 喵~防御：应用名对不上时直接丢掉标题，宁可少一行也不给错信息喵
        snapshot_title = detail.current_app.title if detail.current_app is not None else ""
        shown_title = snapshot_title if snapshot_title and snapshot_app == shown_app else ""
        # 喵~注意：「已持续多久」算的是快照里 since 到现在的差，而应用名取的是
        # 最新使用采样，两者不同源。对不上时会出现「应用是 A、时长是 B 的」，
        # 所以这里跟标题一样做同源校验，对不上就不报时长喵
        same_app = not reported_app or reported_app == snapshot_app
        # 最后一次使用记录，判定挂机/不在全靠它喵
        last_usage = _last_usage_moment(connection, device_id, now)
        # 组装一台设备喵
        devices.append(
            HappyDevice(
                device_id=device_id,
                name=detail.summary.display_name,
                platform=detail.summary.platform,
                last_seen=detail.summary.last_seen_at,
                online=queries.is_online(detail.summary.last_seen_at, now),
                afk=_latest_afk(connection, device_id),
                # 喵~注意：空档时长就是「现在减最后一次使用」，负数（时钟回拨）按 0 算喵
                gap_seconds=None if last_usage is None else max(0, int((now - last_usage).total_seconds())),
                current_app=shown_app,
                # 喵~注意：安卓端不采集标题，这里恒为空喵
                current_title=shown_title,
                # 喵~防御：应用名与快照对不上时说 0，模板就不显示「已持续」喵
                current_seconds=_current_app_seconds(detail, now) if same_app else 0,
                battery_percent=detail.battery.percent if detail.battery is not None else None,
                battery_charging=bool(detail.battery.charging) if detail.battery is not None else False,
                usage_24h_seconds=int(usage_totals.get(device_id, 0)),
                last_usage=last_usage,
                priority=priority,
            )
        )
    # 喵~防御：组里写着的设备全都不在库里喵
    if not devices:
        raise HappyError(f'设备组「{group_name}」里的设备都还没有上报过数据，请先启动客户端。')
    return devices


def _latest_reported_app(connection: sqlite3.Connection, device_id: str) -> str:
    """取这台设备最近一次上报里出现的应用名喵。

    输入：连接、设备 ID。
    输出：最近一条使用采样的应用名；没有采样时返回空串。

    喵~注意：为什么不用 devices.current_app_json——它是 upsert 时用 COALESCE
    写进去的快照，上报不带 current_app 时会保留上一次的旧值，可能很久没更新。
    主人要求「活跃软件取该设备最近上报的软件」，所以这里直接查使用采样的
    最新一条，它才是这台设备真正最后报上来的应用喵。
    """
    # 按采样时刻倒序取一条，同一时刻可能有多条，再按秒数多的优先喵
    row = connection.execute(
        """
        SELECT app_name FROM usage_samples
        WHERE device_id = ?
        ORDER BY sampled_at DESC, seconds DESC
        LIMIT 1
        """,
        (device_id,),
    ).fetchone()
    # 喵~防御：从没上报过使用记录时返回空串，模板会退回快照喵
    if row is None:
        return ""
    return str(row["app_name"])


def _current_app_seconds(detail: queries.DeviceDetail, now: datetime) -> int:
    """算当前应用已持续的秒数喵。

    输入：设备详情、基准时间。
    输出：秒数；没有当前应用、或数据明显不可信时返回 0。
    边界：时钟回拨导致负数时按 0 处理；超过 MAX_CURRENT_APP_SECONDS 时按 0 处理喵。

    喵~注意：`since` 是「这个应用切到前台的时刻」，只要应用不换就一直不重置，
    所以它能一直累加到几个小时。`current_app_json` 又是 upsert 时的 COALESCE 快照，
    客户端偶尔不带 current_app 时会保留几天前的旧值。这两种情况都不能直接把差值
    报给主人，否则会出现「已持续 120 小时」这种明显不对的文案喵。
    """
    # 喵~防御：没有当前应用就没有时长喵
    if detail.current_app is None or detail.current_app.since is None:
        return 0
    # 喵~防御：负值（客户端时钟快于服务端）按 0 处理喵
    seconds = int((now - detail.current_app.since).total_seconds())
    if seconds <= 0:
        return 0
    # 喵~防御：超过上限说明是陈旧快照，宁可不报也不报个离谱的数喵
    if seconds > MAX_CURRENT_APP_SECONDS:
        return 0
    return seconds


def _latest_afk(connection: sqlite3.Connection, device_id: str) -> bool:
    """取这台设备当前的 AFK 标记喵。

    输入：连接、设备 ID。
    输出：现在是否 AFK。
    边界：查不到设备记录时按非 AFK 处理喵。
    """
    # 喵~注意：afk 是 devices 表上的「当前值」，reports 表里只有历史上报体喵
    row = connection.execute(
        "SELECT afk FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    # 喵~防御：没有设备记录时按非 AFK 处理喵
    if row is None:
        return False
    return bool(row["afk"])


def _last_usage_moment(
    connection: sqlite3.Connection,
    device_id: str,
    now: datetime | None = None,
) -> datetime | None:
    """取这台设备最后一次有使用记录的时刻喵。

    输入：连接、设备 ID、可选基准时间（作为上界）。
    输出：UTC 时刻；从没用过时返回 None。
    边界：只认 seconds > 0 的采样，避免空采样点亮状态喵。
    """
    # 喵~防御：上界必须卡在基准时间，否则客户端时钟快于服务端时，
    # 未来时刻的采样会被当成「刚刚用过」，空档恒为 0、永远判成在用喵
    if now is None:
        # 取最大采样时刻喵
        row = connection.execute(
            "SELECT MAX(sampled_at) AS moment FROM usage_samples WHERE device_id = ? AND seconds > 0",
            (device_id,),
        ).fetchone()
    else:
        # 带上上界喵
        row = connection.execute(
            "SELECT MAX(sampled_at) AS moment FROM usage_samples "
            "WHERE device_id = ? AND seconds > 0 AND sampled_at <= ?",
            (device_id, to_utc_text(now)),
        ).fetchone()
    # 喵~防御：没有记录时返回 None 喵
    if row is None or row["moment"] is None:
        return None
    # 统一解析成 UTC 时刻喵
    return parse_utc_text(str(row["moment"]))


def usage_seconds_since(
    connection: sqlite3.Connection,
    device_id: str,
    since: datetime,
    until: datetime | None = None,
) -> int:
    """统计这台设备自某个时刻以来的使用秒数喵。

    输入：连接、设备 ID、起点时刻、可选的终点时刻（作为上界）。
    输出：累计秒数。
    边界：没有记录时返回 0 喵。
    """
    # 不带终点时只卡下界，兼容老的调用方式喵
    if until is None:
        # 直接按采样时刻汇总喵
        row = connection.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS total FROM usage_samples "
            "WHERE device_id = ? AND sampled_at >= ?",
            (device_id, to_utc_text(since)),
        ).fetchone()
    else:
        # 喵~防御：两端都卡住，未来时刻的采样不能算进任何一个窗口喵
        row = connection.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS total FROM usage_samples "
            "WHERE device_id = ? AND sampled_at >= ? AND sampled_at <= ?",
            (device_id, to_utc_text(since), to_utc_text(until)),
        ).fetchone()
    return int(row["total"]) if row is not None else 0


def judge_state(
    connection: sqlite3.Connection,
    devices: list[HappyDevice],
    now: datetime,
) -> tuple[str, HappyDevice | None, str]:
    """判定主人现在处于哪一档状态喵。

    输入：连接、按优先级排列的设备、基准时间。
    输出：(状态, 该展示的设备, 理由)。
    边界：规则按「在用 > 挂机 > 不在」短路，
          多台设备同时满足时一律取优先级最高的那台喵。
    """
    # 先看最近 3 分钟：在线且有足够长的使用记录就算在用喵
    for device in devices:
        # 窗口内的使用秒数喵
        # 喵~防御：上界卡在 now，未来时刻的采样不能点亮「在用」喵
        seconds = usage_seconds_since(
            connection, device.device_id, now - timedelta(seconds=ACTIVE_WINDOW_SECONDS), now
        )
        # 喵~注意：单次误采样不算，要求累计达到下限且设备在线喵
        if seconds >= MIN_ACTIVITY_SECONDS and device.online:
            return STATE_ACTIVE, device, f"{device.name} 最近 3 分钟使用了 {seconds} 秒"
    # 再看空档时长：在线但空档不超过 10 分钟，说明人还在，只是没在动喵
    for device in devices:
        # 喵~注意：判的是空档有多长（= 时间轴上那段斜纹），不是心跳里的 afk 标记；
        # 被门控暂停计时的设备 afk=false 但照样是空档，只看标记会漏掉它们喵
        if not device.online or device.gap_seconds is None:
            continue
        if device.gap_seconds <= AFK_WINDOW_SECONDS:
            return STATE_AFK, device, f"{device.name} 空档 {device.gap_seconds} 秒，还没到 10 分钟"
    # 其余一律算不在喵
    best = most_recent_usage(devices)
    # 喵~防御：从来没记录过时连设备都不给，让模板走「没有记录」分支喵
    if best is None:
        return STATE_AWAY, None, "组内设备都没有使用记录"
    return STATE_AWAY, best, f"最近一次使用是 {best.name}"


def most_recent_usage(devices: list[HappyDevice]) -> HappyDevice | None:
    """挑出最近有使用记录的那台设备喵。

    输入：设备列表。
    输出：最近使用的那台；全都没有记录时返回 None。
    边界：时刻相同时取优先级高的喵。
    """
    # 只看有记录的设备喵
    candidates = [device for device in devices if device.last_usage is not None]
    # 喵~防御：一台都没有时返回 None 喵
    if not candidates:
        return None
    # 时刻倒序，再按优先级正序，保证排序结果稳定喵
    candidates.sort(key=lambda device: (-device.last_usage.timestamp(), device.priority))  # type: ignore[union-attr]
    return candidates[0]


def active_device(
    connection: sqlite3.Connection,
    devices: list[HappyDevice],
    now: datetime,
    window_seconds: int,
) -> HappyDevice | None:
    """在给定窗口内挑出「最近有行为」的设备，按优先级喵。

    输入：连接、设备列表、基准时间、窗口秒数。
    输出：命中的设备；都没有时返回 None。
    边界：窗口内秒数不够下限的不算；不要求在线——离线前刚用过也算刚离开喵。
    """
    # 按优先级顺序找第一台达标的喵
    for device in devices:
        # 窗口内的使用秒数喵
        # 喵~防御：上界同样卡在 now，未来时刻的采样不算这个小窗口里的行为喵
        window_start = now - timedelta(seconds=window_seconds)
        if usage_seconds_since(connection, device.device_id, window_start, now) >= MIN_ACTIVITY_SECONDS:
            return device
    return None


def best_snapshot(connection: sqlite3.Connection, config: AppConfig, now: datetime) -> HappySnapshot:
    """一次性拿到主人状态与全部设备，供各命令复用喵。

    输入：连接、配置、基准时间。
    输出：HappySnapshot。
    边界：设备组缺失时抛 HappyError，由上层转成提示文案喵。
    """
    # 读设备喵
    devices = load_happy_devices(connection, config, now)
    # 判定状态喵
    state, device, reason = judge_state(connection, devices, now)
    # 跨设备取最近一次使用喵
    latest = most_recent_usage(devices)
    # 组装快照喵
    return HappySnapshot(
        state=state,
        device=device,
        devices=devices,
        last_usage_device=latest.name if latest is not None else "",
        last_usage=latest.last_usage if latest is not None else None,
        reason=reason,
    )
