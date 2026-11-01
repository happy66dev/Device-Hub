"""统计门控：决定一次上报里的使用时长要不要入库。

背景（主人定的规则）：
1. 被标记为服务器的设备，只在 RDP 会话处于活动状态时才统计；
2. 服务器上跑着 scrcpy 投屏时，被投屏的安卓设备也按这台服务器的 RDP 状态统计；
3. scrcpy 没连上时，人是直接拿着手机用，安卓设备照常统计，不能丢包。

识别"投屏连着哪台安卓设备"只依赖两样东西：服务器上报的 scrcpy 窗口标题，
以及安卓设备自己上报的标签（主人自定义名称）喵。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .db import parse_utc_text, utc_now

# 设备角色常量喵
ROLE_WORKSTATION = "workstation"
ROLE_SERVER = "server"

# 暂停原因：服务器自己的 RDP 没连喵
REASON_RDP_DISCONNECTED = "rdp_disconnected"

REASON_RDP_TARGET_MONITORED = "rdp_target_monitored"

# 远程桌面客户端进程名（小写），前台是它们时本机只负责显示喵
RDP_CLIENT_PACKAGES = frozenset({"mstsc.exe", "msrdc.exe"})
# 暂停原因：被投屏的安卓设备，其宿主服务器 RDP 没连喵
REASON_MIRROR_RDP_DISCONNECTED = "mirror_rdp_disconnected"

# 暂停原因：服务器自己的投屏窗口在前台，本机不该计时喵
REASON_MIRROR_FOREGROUND = "mirror_foreground"

# 暂停原因：安卓设备正被投屏，但投屏窗口不在前台喵
REASON_MIRROR_BACKGROUND = "mirror_background"

# 暂停原因：键鼠空闲，人不在机器前喵
REASON_AFK = "afk"

# 中文说明，供机器人回复与看板展示喵
REASON_TEXT = {
    REASON_RDP_DISCONNECTED: "RDP 未连接，统计已暂停",
REASON_RDP_TARGET_MONITORED: "远程连接到受监控的设备，本机不计时",
    REASON_MIRROR_RDP_DISCONNECTED: "通过服务器投屏中，RDP 未连接，统计已暂停",
    REASON_MIRROR_FOREGROUND: "投屏窗口在前台，本机不计时",
    REASON_MIRROR_BACKGROUND: "投屏窗口不在前台，统计已暂停",
    REASON_AFK: "键鼠空闲，统计已暂停",
}


@dataclass(frozen=True)
class GatingSettings:
    """门控相关配置喵。"""

    # 是否启用门控，关掉后一切按老逻辑统计喵
    enabled: bool = True
    # RDP 状态超过这个秒数没刷新就认为不可信（客户端可能已经挂了）喵
    rdp_stale_seconds: int = 180
    # 配置里强制标记为服务器的设备 ID 喵
    servers: tuple[str, ...] = ()
    # 配置里强制标记为工作站的设备 ID（优先级高于服务器列表）喵
    workstations: tuple[str, ...] = ()
    # 是否启用远程桌面目标校验（关闭后前台是 mstsc 也照常计时）喵
    rdp_require_known_client: bool = True
    # 手动放行的客户端 IP 或机器名（不在设备表里也认）喵
    rdp_allowed_clients: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    """一次门控判定的结果喵。"""

    # 是否允许写入使用时长喵
    stats_enabled: bool
    # 暂停原因代码，允许统计时为空串喵
    reason: str


def normalize_tag(text: str | None) -> str:
    """把标签归一化成可比较的形式喵。

    输入：原始标签文本。
    输出：去空白、转小写后的文本；空输入返回空串。
    """
    # 喵~防御：None 或非字符串按空处理，避免调用方到处判空喵
    if not isinstance(text, str):
        return ""
    # 统一小写并去掉首尾空白，让「小米 14」与「小米14」之外的差异都能对上喵
    return text.strip().casefold()


def match_mirrored_tags(window_titles: list[str], candidate_tags: list[str]) -> list[str]:
    """用 scrcpy 窗口标题匹配安卓标签喵。

    输入：投屏窗口标题列表、候选安卓标签列表。
    输出：命中的标签（保留标签原样大小写）。
    边界：空标题、空标签一律跳过；匹配采用"标题包含标签"或"标题与标签相等"。
    """
    # 预先归一化标题，避免每个标签都重复处理喵
    normalized_titles = [normalize_tag(title) for title in window_titles if normalize_tag(title)]
    # 喵~防御：没有标题就没有投屏会话喵
    if not normalized_titles:
        return []
    # 记录命中的标签，按原顺序返回喵
    matched: list[str] = []
    # 逐个候选标签比较喵
    for tag in candidate_tags:
        # 归一化标签喵
        normalized_tag = normalize_tag(tag)
        # 喵~防御：空标签会匹配到所有标题，必须跳过喵
        if not normalized_tag:
            continue
        # 标题包含标签即视为同一台设备（scrcpy 标题常带型号后缀）喵
        if any(normalized_tag in title for title in normalized_titles):
            matched.append(tag)
    return matched


def _is_fresh(updated_text: str | None, now: datetime, stale_seconds: int) -> bool:
    """判断 RDP 状态是否还在有效期内喵。"""
    # 喵~防御：没有更新时间说明客户端从没报过 RDP 状态喵
    if not updated_text:
        return False
    try:
        # 库里的时间文本转成 datetime 喵
        updated_at = parse_utc_text(updated_text)
    except ValueError:
        # 喵~防御：时间文本被改坏时按过期处理，宁可不统计也不要统计错喵
        return False
    # 超过有效期就认为状态不可信喵
    return (now - updated_at).total_seconds() <= stale_seconds


def load_server_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """取出所有服务器角色设备的状态行喵。"""
    # 只查服务器角色，数量很少，直接全取回来在 Python 里比较喵
    return connection.execute(
        """
        SELECT device_id, rdp_connected, rdp_updated_at, mirrored_tags_json, mirror_foreground, afk
        FROM devices WHERE role = ?
        """,
        (ROLE_SERVER,),
    ).fetchall()


def _parse_tags(raw_json: str | None) -> list[str]:
    """解析库里存的投屏标签 JSON 喵。"""
    # 喵~防御：空值或坏 JSON 都按空列表处理喵
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except ValueError:
        return []
    # 喵~防御：结构不是列表时同样按空处理喵
    if not isinstance(parsed, list):
        return []
    # 只保留非空字符串喵
    return [item for item in parsed if isinstance(item, str) and item.strip()]


def normalize_client_ip(value: str | None) -> str:
    """把 RDP 客户端 IP 归一化成可比较的形式喵。

    输入：原始 IP 文本，可能是 IPv4、IPv6 或 IPv4 映射的 IPv6。
    输出：小写、去掉映射前缀的 IP 文本；空输入返回空串。
    """
    # 喵~防御：非字符串按空处理喵
    if not isinstance(value, str):
        return ""
    # 去掉首尾空白并转小写喵
    text = value.strip().lower()
    # Windows 常把 IPv4 报成 ::ffff:192.168.2.5，剥掉前缀才好比对喵
    if text.startswith("::ffff:"):
        text = text[len("::ffff:") :]
    return text


def client_identity_sets(connection: sqlite3.Connection, device_id: str) -> tuple[set[str], set[str]]:
    """取「其它设备」的 IP 与机器名集合，用于确认 RDP 客户端身份喵。

    输入：连接、当前设备 ID（要排除自己，免得自己连自己也算数）。
    输出：(IP 集合, 机器名集合)，均已归一化。
    边界：设备表为空时返回两个空集合喵。
    """
    # IP 集合喵
    ips: set[str] = set()
    # 机器名集合，包含展示名与硬件信息里的 hostname 喵
    names: set[str] = set()
    rows = connection.execute(
        "SELECT device_id, display_name, hardware_json, last_ip FROM devices WHERE device_id != ?",
        (device_id,),
    ).fetchall()
    for row in rows:
        # 最近上报来源 IP 喵
        ip = normalize_client_ip(str(row["last_ip"] or ""))
        if ip:
            ips.add(ip)
        # 展示名喵
        display_name = normalize_tag(str(row["display_name"] or ""))
        if display_name:
            names.add(display_name)
        # 硬件信息里的 Windows 计算机名喵
        try:
            hardware = json.loads(str(row["hardware_json"] or "{}"))
        except ValueError:
            hardware = {}
        if isinstance(hardware, dict):
            hostname = normalize_tag(str(hardware.get("hostname") or ""))
            if hostname:
                names.add(hostname)
    return ips, names


def normalize_target(value: str | None) -> str:
    """把远程桌面目标地址归一化成可比较的形式喵。

    输入：目标地址文本，可能是「host」「host:3389」「host:3389/tcp」等形式。
    输出：小写主机名或 IP；空输入返回空串。
    """
    # 喵~防御：非字符串按空处理喵
    if not isinstance(value, str):
        return ""
    # 去空白转小写喵
    text = value.strip().lower()
    # 去掉协议前缀喵
    for prefix in ("rdp://", "mstsc://"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    # 去掉端口喵
    if ":" in text and text.count(":") == 1:
        text = text.split(":", 1)[0]
    # 去掉末尾的斜杠与路径喵
    text = text.split("/", 1)[0]
    return text.strip()


def is_known_target(
    connection: sqlite3.Connection,
    device_id: str,
    target: str | None,
    settings: GatingSettings,
) -> bool:
    """判断远程桌面连过去的目标是不是受监控的设备喵。

    输入：连接、当前设备 ID、目标地址、门控配置。
    输出：True 表示目标是自己人（那台设备自己会计时）。
    边界：手动放行名单里的地址也算自己人；目标解析不出来时返回 False 喵。
    """
    # 归一化目标喵
    normalized = normalize_target(target)
    # 喵~防御：空目标谈不上匹配喵
    if not normalized:
        return False
    # 手动放行名单喵
    allowed = {normalize_target(item) for item in settings.rdp_allowed_clients if normalize_target(item)}
    if normalized in allowed:
        return True
    # 设备表里的 IP 与机器名喵
    ips, names = client_identity_sets(connection, device_id)
    return normalized in ips or normalized in names


def decide_stats_enabled(
    connection: sqlite3.Connection,
    device_id: str,
    role: str,
    tag: str,
    rdp_connected: bool,
    settings: GatingSettings,
    now: datetime | None = None,
    mirror_foreground: bool = False,
    afk: bool = False,
    rdp_client_ip: str | None = None,
    rdp_client_name: str | None = None,
    current_package: str = "",
    rdp_target: str = "",
) -> GateDecision:
    """判断这台设备本次上报的使用时长是否应该入库喵。

    输入：连接、设备 ID、角色、标签、该设备自己上报的 RDP 状态、门控配置、基准时间。
    输出：GateDecision。
    边界：
      - 门控关闭时一律允许统计；
      - 键鼠空闲（AFK）时一律暂停，本机与投屏手机都停喵；
      - 服务器角色：RDP 未连接 → 暂停；投屏窗口在前台 → 也暂停（人其实在看手机）喵；
      - 安卓设备：被某台服务器投屏时，只有那台服务器 RDP 连着、且投屏窗口在前台才统计；
        宿主 RDP 没连（人摸不到键鼠，操作不了手机）→ 暂停，即使投屏窗口在前台；
        RDP 连着但投屏窗口缩到后台说明人没在看手机，暂停统计；
        没有任何服务器连着它，说明人在直接用手機，照常统计喵。
    """
    # 基准时间缺省取当前时间喵
    base_now = now or utc_now()
    # 喵~防御：门控被主人关掉时不做任何限制喵
    if not settings.enabled:
        return GateDecision(stats_enabled=True, reason="")

    # 喵~防御：人不在机器前（键鼠空闲）就一律不计时，服务器和手机都一样喵
    if afk:
        return GateDecision(stats_enabled=False, reason=REASON_AFK)

    # 服务器角色：先看 RDP，再看投屏窗口是否抢了前台喵
    if role == ROLE_SERVER:
        # 喵~防御：RDP 没连就不算在用这台服务器喵
        if not rdp_connected:
            return GateDecision(stats_enabled=False, reason=REASON_RDP_DISCONNECTED)
        # 主人注意：陌生客户端连进来也照常计时，因为那台机器确实在用这台服务器喵
        # 喵~防御：投屏窗口在前台时，人是在看手机，服务器自己的桌面不该计时喵
        if mirror_foreground:
            return GateDecision(stats_enabled=False, reason=REASON_MIRROR_FOREGROUND)
        # 两个条件都过才计时喵
        return GateDecision(stats_enabled=True, reason="")

    # 远程桌面客户端在前台：目标是自己人就由那台设备计时，本机改成记 mstsc 喵
    if normalize_tag(current_package) in RDP_CLIENT_PACKAGES:
        # 喵~防御：目标认不出来（frp / tailscale 地址等）就当作本机在使用远程桌面喵
        if settings.rdp_require_known_client and rdp_target and is_known_target(connection, device_id, rdp_target, settings):
            return GateDecision(stats_enabled=False, reason=REASON_RDP_TARGET_MONITORED)

    # 非服务器：看看有没有服务器正通过 scrcpy 连着它喵
    normalized_tag = normalize_tag(tag)
    # 喵~防御：没有标签就无法被识别，按"直接使用设备"处理喵
    if not normalized_tag:
        return GateDecision(stats_enabled=True, reason="")

    # 记录命中该标签的服务器喵
    hosts: list[sqlite3.Row] = []
    for row in load_server_rows(connection):
        # 解析这台服务器当前投屏中的标签喵
        mirrored = [normalize_tag(item) for item in _parse_tags(row["mirrored_tags_json"])]
        # 标签命中说明这台安卓正被那台服务器投屏喵
        if normalized_tag in mirrored:
            hosts.append(row)

    # 喵~防御：没有服务器连着它 → 人是在直接使用手机，照常统计喵
    if not hosts:
        return GateDecision(stats_enabled=True, reason="")

    # 喵~注意：只认状态新鲜的服务器，两天前留下的投屏记录不能拿来判定今天喵
    fresh_hosts = [
        host
        for host in hosts
        if _is_fresh(host["rdp_updated_at"], base_now, settings.rdp_stale_seconds)
    ]
    # 喵~防御：匹配到的服务器全都掉线了，说明投屏早就结束，按直接使用手机处理喵
    if not fresh_hosts:
        return GateDecision(stats_enabled=True, reason="")

    # 喵~注意：宿主服务器 RDP 没连时，人摸不到键盘鼠标，根本操作不了这台手机；
    # 此时投屏窗口哪怕摆在前台，也只是走之前留下的画面，不能算在用手机喵
    connected_hosts = [host for host in fresh_hosts if bool(host["rdp_connected"])]
    # 喵~防御：所有宿主都没连 RDP → 一律暂停，原因要和"投屏窗口在后台"分开，便于主人核对喵
    if not connected_hosts:
        return GateDecision(stats_enabled=False, reason=REASON_MIRROR_RDP_DISCONNECTED)

    # 只要有一台连着 RDP 的宿主服务器把投屏窗口摆在前台，就认为"人正盯着手机用"喵
    for host in connected_hosts:
        # 喵~防御：宿主机器上人已经离开了，手机也不该继续计时喵
        if bool(host["afk"]):
            continue
        # 投屏窗口在前台才统计手机喵
        if bool(host["mirror_foreground"]):
            return GateDecision(stats_enabled=True, reason="")
    # 连着的服务器投屏窗口都在后台，暂停统计喵
    return GateDecision(stats_enabled=False, reason=REASON_MIRROR_BACKGROUND)


def is_rdp_state_fresh(updated_text: str | None, settings: GatingSettings, now: datetime | None = None) -> bool:
    """对外暴露的"RDP 状态是否新鲜"判断，供查询层展示用喵。"""
    # 复用内部实现喵
    return _is_fresh(updated_text, now or utc_now(), settings.rdp_stale_seconds)


def reason_text(reason: str) -> str:
    """把暂停原因代码翻译成中文文案喵。"""
    # 未知原因给出兜底文案，避免界面出现空白喵
    return REASON_TEXT.get(reason, "统计已暂停")
