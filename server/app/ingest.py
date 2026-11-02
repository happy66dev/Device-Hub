"""把一次上报写入数据库。

写入顺序：设备表 → 原始上报表 → 电量采样 → 使用时长采样。
上报表上的 (device_id, reported_at) 唯一约束是幂等性的关键：
同一个时间点的重复上报会被识别出来，从而避免使用时长被重复累加喵。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import to_utc_text
from .gating import (
    GatingSettings,
    REASON_AFK,
    ROLE_SERVER,
    ROLE_WORKSTATION,
    decide_stats_enabled,
    match_mirrored_tags,
)
from .models import ReportPayload
from .payload_codec import encode_payload

# 使用段落位时刻允许比上报时刻早多少秒，超了就认为客户端时钟不可信、退回上报时刻喵
MAX_USAGE_ANCHOR_SECONDS = 3600


@dataclass(frozen=True)
class IngestResult:
    """一次落库的结果摘要，便于接口回显和测试断言喵。"""

    # 设备 ID 喵
    device_id: str
    # 是否为重复上报（同一设备同一时间点已存在）喵
    duplicate: bool
    # 本次实际写入的使用时长记录条数喵
    usage_rows_written: int
    # 本次是否写入了电量采样喵
    battery_written: bool
    # 本次是否因为门控暂停了统计喵
    stats_paused: bool = False
    # 暂停原因代码，未暂停时为空串喵
    stats_paused_reason: str = ""
    # 服务器设备本次上报识别出的投屏标签喵
    mirrored_tags: tuple[str, ...] = ()
    # 本次写入的窗口快照条数喵
    windows_written: int = 0


def _extract_os_version(payload: ReportPayload) -> str:
    """从硬件信息里推导系统版本字符串喵。

    Windows 取 hardware.os_version；Android 用 android_version 拼成 "Android 14"。
    取不到时返回空串，渲染层会显示「未知」喵。
    """
    # 硬件信息可能没传喵
    hardware = payload.hardware or {}
    # Windows 直接读 os_version 键喵
    if payload.platform == "windows":
        # 取不到就返回空串喵
        return str(hardware.get("os_version", "")).strip()
    # Android 读 android_version 键喵
    android_version = str(hardware.get("android_version", "")).strip()
    # 喵~防御：版本号缺失时不硬拼，直接返回空串让上层显示「未知」喵
    if not android_version:
        return ""
    # 拼成人类可读的形式喵
    return f"Android {android_version}"


def _extract_display_name(payload: ReportPayload) -> str:
    """决定设备展示名，缺省时退回 device_id 喵。"""
    # 优先使用客户端给的名字喵
    if payload.display_name:
        # 去掉首尾空白后仍非空才采用喵
        cleaned = payload.display_name.strip()
        if cleaned:
            return cleaned
    # 兜底用设备 ID 喵
    return payload.device_id


def _load_existing_device(connection: sqlite3.Connection, device_id: str) -> sqlite3.Row | None:
    """读取设备已有行，用于"没传就沿用旧值"的字段喵。"""
    # 只取本函数需要的列喵
    return connection.execute(
        """
        SELECT role, tag, rdp_connected, rdp_updated_at, mirror_windows_json, mirrored_tags_json,
               mirror_foreground, afk
        FROM devices WHERE device_id = ?
        """,
        (device_id,),
    ).fetchone()


def _resolve_role(payload: ReportPayload, existing: sqlite3.Row | None, settings: GatingSettings) -> str:
    """决定设备角色，配置优先级最高喵。

    输入：上报体、设备已有行、门控配置。
    输出：ROLE_SERVER 或 ROLE_WORKSTATION。
    边界：配置里显式标记为工作站的设备，即使客户端自称服务器也会被纠正喵。
    """
    # 喵~防御：配置里标成工作站的最优先，用来纠正客户端误报喵
    if payload.device_id in settings.workstations:
        return ROLE_WORKSTATION
    # 其次看配置里的服务器列表喵
    if payload.device_id in settings.servers:
        return ROLE_SERVER
    # 再看客户端自报喵
    if payload.role is not None:
        return payload.role
    # 最后沿用库里已有角色喵
    if existing is not None and existing["role"]:
        return str(existing["role"])
    # 默认按工作站处理喵
    return ROLE_WORKSTATION


def _resolve_tag(payload: ReportPayload, existing: sqlite3.Row | None) -> str:
    """决定设备标签，客户端没传就沿用旧值喵。"""
    # 客户端传了非空标签就用它喵
    if payload.tag is not None and payload.tag.strip():
        return payload.tag.strip()[:64]
    # 否则沿用库里已有标签喵
    if existing is not None and existing["tag"]:
        return str(existing["tag"])
    # 都没有就给空串，表示这台设备不参与投屏匹配喵
    return ""


def _collect_android_tags(connection: sqlite3.Connection) -> list[str]:
    """取出所有安卓设备的非空标签，用于匹配投屏窗口喵。"""
    # 只查安卓平台且标签非空的设备喵
    rows = connection.execute(
        "SELECT tag FROM devices WHERE platform = 'android' AND tag != '' ORDER BY tag"
    ).fetchall()
    # 收集成字符串列表喵
    return [str(row["tag"]) for row in rows]


def _report_payload_body(payload: ReportPayload) -> dict[str, object]:
    """拼出要存进 reports 的上报体，去掉已有别处存放的字段喵。

    输入：校验过的上报对象。
    输出：可以直接压缩存储的字典。
    边界：只去掉 open_windows，其它字段一律保留，保证以后还能回溯解析喵。
    """
    # 先按模型序列化，日期时间等类型会被转成字符串喵
    body = payload.model_dump(mode="json")
    # 喵~注意：open_windows 逐行存在 window_samples 里，这里再存一份就是重复喵
    body.pop("open_windows", None)
    return body


def save_report(
    connection: sqlite3.Connection,
    payload: ReportPayload,
    received_at: datetime,
    settings: GatingSettings | None = None,
    client_ip: str = "",
) -> IngestResult:
    """把一次上报落库，返回写入摘要喵。

    输入：已打开的数据库连接、通过校验的上报对象、服务端接收时间、可选的门控配置。
    输出：IngestResult。
    边界：
      - 同一设备同一 reported_at 重复上报时，使用时长不会重复累加；
      - 被门控判定为暂停时只更新设备状态，不写入使用时长；
      - 任何 SQL 异常都会回滚，不会留下半条记录喵。
    """
    # 没传门控配置时用默认值（启用门控、无角色覆盖）喵
    active_settings = settings or GatingSettings()
    # 统一把时间转成 UTC 文本，保证排序与比较一致喵
    reported_text = to_utc_text(payload.reported_at)
    # 服务端接收时间同样转成 UTC 文本喵
    received_text = to_utc_text(received_at)
    # 喵~注意：使用段按"客户端最后一次计时"的时刻落位，而不是按上报时刻，
    # 这样上报慢一点、循环卡一下，色块也不会整体后移并在前面留出空白喵
    usage_text = received_text
    if payload.usage_ended_at is not None:
        # 只接受"不晚于接收时间、且不过分久远"的锚点喵
        anchor_gap = (received_at - payload.usage_ended_at).total_seconds()
        if 0 <= anchor_gap <= MAX_USAGE_ANCHOR_SECONDS:
            usage_text = to_utc_text(payload.usage_ended_at)
    # 硬件信息序列化成 JSON 字符串存库喵
    hardware_json = json.dumps(payload.hardware or {}, ensure_ascii=False, sort_keys=False)
    # 当前应用序列化成 JSON，没传就存 NULL 喵
    current_app_json = payload.current_app.model_dump_json() if payload.current_app else None
    # 读取设备已有行，用于"没传就沿用旧值"喵
    existing = _load_existing_device(connection, payload.device_id)
    # 决定角色与标签，配置优先级高于客户端自报喵
    role = _resolve_role(payload, existing, active_settings)
    tag = _resolve_tag(payload, existing)
    # RDP 状态：客户端传了才刷新时间戳，否则沿用旧值喵
    if payload.rdp_connected is None:
        # 喵~防御：老客户端不上报 RDP 状态，沿用库里旧值而不是清零喵
        rdp_connected = bool(existing["rdp_connected"]) if existing is not None else False
        rdp_updated_text = str(existing["rdp_updated_at"]) if existing is not None and existing["rdp_updated_at"] else None
    else:
        # 客户端明确上报，刷新状态与时间戳喵
        rdp_connected = bool(payload.rdp_connected)
        rdp_updated_text = reported_text
    # RDP 客户端身份：只有服务器角色会上报，用来确认连进来的是自己人喵
    rdp_client_ip = (payload.rdp_client_ip or "").strip()[:45]
    rdp_client_name = (payload.rdp_client_name or "").strip()[:64]
    # 投屏窗口：只有客户端明确上报时才重新匹配，避免旧数据被清空喵
    mirrored_tags: list[str] = []
    if payload.mirror_windows is not None:
        # 原样存窗口标题，便于排查匹配问题喵
        mirror_windows_json = json.dumps(payload.mirror_windows, ensure_ascii=False)
        # 用窗口标题去匹配现有安卓标签喵
        mirrored_tags = match_mirrored_tags(payload.mirror_windows, _collect_android_tags(connection))
        # 存匹配结果，门控判定直接读它喵
        mirrored_tags_json = json.dumps(mirrored_tags, ensure_ascii=False)
    else:
        # 没上报就沿用旧值喵
        mirror_windows_json = str(existing["mirror_windows_json"]) if existing is not None else "[]"
        mirrored_tags_json = str(existing["mirrored_tags_json"]) if existing is not None else "[]"

    # 投屏窗口是否在前台：决定本机与手机各自是否计时喵
    if payload.mirror_foreground is not None:
        # 客户端明确上报，直接用喵
        mirror_foreground = 1 if payload.mirror_foreground else 0
    else:
        # 没上报就沿用旧值，避免老客户端把状态冲成 0 喵
        mirror_foreground = int(existing["mirror_foreground"]) if existing is not None else 0

    # 键鼠是否空闲：决定本机与投屏手机是否继续计时喵
    if payload.afk is not None:
        # 客户端明确上报，直接用喵
        afk_flag = 1 if payload.afk else 0
    else:
        # 没上报（例如安卓端）就沿用旧值喵
        afk_flag = int(existing["afk"]) if existing is not None else 0

    # 设备表的 upsert 语句，角色、RDP 与投屏状态一并更新喵
    upsert_device_sql = """
        INSERT INTO devices (
            device_id, platform, display_name, os_version, hardware_json,
            current_app_json, client_version, first_seen_at, last_seen_at,
            role, tag, rdp_connected, rdp_updated_at, mirror_windows_json, mirrored_tags_json,
            mirror_foreground, afk, rdp_client_ip, rdp_client_name, last_ip
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            platform         = excluded.platform,
            display_name     = excluded.display_name,
            os_version       = CASE WHEN excluded.os_version = '' THEN devices.os_version ELSE excluded.os_version END,
            hardware_json    = CASE WHEN excluded.hardware_json = '{}' THEN devices.hardware_json ELSE excluded.hardware_json END,
            current_app_json = COALESCE(excluded.current_app_json, devices.current_app_json),
            client_version   = COALESCE(NULLIF(excluded.client_version, ''), devices.client_version),
            last_seen_at     = MAX(devices.last_seen_at, excluded.last_seen_at),
            role             = excluded.role,
            tag              = CASE WHEN excluded.tag = '' THEN devices.tag ELSE excluded.tag END,
            rdp_connected    = excluded.rdp_connected,
            rdp_updated_at   = excluded.rdp_updated_at,
            mirror_windows_json = excluded.mirror_windows_json,
            mirrored_tags_json  = excluded.mirrored_tags_json,
            mirror_foreground   = excluded.mirror_foreground,
            afk                 = excluded.afk,
            rdp_client_ip       = excluded.rdp_client_ip,
            rdp_client_name     = excluded.rdp_client_name,
            last_ip             = CASE WHEN excluded.last_ip = '' THEN devices.last_ip ELSE excluded.last_ip END
    """
    # 上报表插入语句，冲突时什么都不做，用于识别重复上报喵
    insert_report_sql = """
        INSERT INTO reports (device_id, reported_at, received_at, payload_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_id, reported_at) DO NOTHING
    """
    # 电量采样 upsert，同一时间点重复上报时覆盖为最新值喵
    upsert_battery_sql = """
        INSERT INTO battery_samples (device_id, sampled_at, percent, charging)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_id, sampled_at) DO UPDATE SET
            percent  = excluded.percent,
            charging = excluded.charging
    """
    # 使用时长采样 upsert，带上包名；同一时间点同一应用累加喵
    upsert_usage_sql = """
        INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT DO UPDATE SET
            seconds = usage_samples.seconds + excluded.seconds
    """

    # 窗口快照直接追加，不合并：历史要留着做窗口维度分析喵
    insert_window_sql = """
        INSERT INTO window_samples
            (device_id, app_name, package, title, minimized, foreground, reported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    try:
        # 先写设备表，保证后续外键引用成立喵
        connection.execute(
            upsert_device_sql,
            (
                payload.device_id,
                payload.platform,
                _extract_display_name(payload),
                _extract_os_version(payload),
                hardware_json,
                current_app_json,
                payload.client_version or "",
                received_text,
                received_text,
                role,
                tag,
                rdp_connected,
                rdp_updated_text,
                mirror_windows_json,
                mirrored_tags_json,
                mirror_foreground,
                afk_flag,
                rdp_client_ip,
                rdp_client_name,
                client_ip.strip()[:45],
            ),
        )
        # 喵~防御：设备状态已写入，此时再判定门控才能读到最新的 RDP 与投屏状态喵
        decision = decide_stats_enabled(
            connection,
            device_id=payload.device_id,
            role=role,
            tag=tag,
            rdp_connected=rdp_connected,
            mirror_foreground=bool(mirror_foreground),
            afk=bool(afk_flag),
            settings=active_settings,
            now=received_at,
            rdp_client_ip=rdp_client_ip,
            rdp_client_name=rdp_client_name,
            current_package=str(getattr(payload.current_app, "package", "") or ""),
            rdp_target=(payload.rdp_target or "").strip()[:200],
        )
        # 暂停原因写进设备表，看板与机器人直接读这一列喵
        connection.execute(
            "UPDATE devices SET stats_paused_reason = ? WHERE device_id = ?",
            ("" if decision.stats_enabled else decision.reason, payload.device_id),
        )
        # 再写原始上报表，并检查是否为重复上报喵
        # 喵~注意：这里存的是压缩后的 BLOB，而且刻意丢掉了 open_windows——
        # 那份列表已经逐行拆进 window_samples 了（实测内容完全一致），
        # 留着等于同一份数据存两遍，它一项就占了 payload 的 45%喵
        report_cursor = connection.execute(
            insert_report_sql,
            (
                payload.device_id,
                reported_text,
                received_text,
                encode_payload(_report_payload_body(payload)),
            ),
        )
        # 喵~防御：rowcount 为 0 说明这条上报已经处理过，后续采样必须跳过，否则统计翻倍喵
        is_duplicate = report_cursor.rowcount == 0
        if is_duplicate:
            # 重复上报只提交设备状态更新，直接返回喵
            connection.commit()
            return IngestResult(
                device_id=payload.device_id,
                duplicate=True,
                usage_rows_written=0,
                battery_written=False,
                stats_paused=not decision.stats_enabled,
                stats_paused_reason="" if decision.stats_enabled else decision.reason,
                mirrored_tags=tuple(mirrored_tags),
            )

        # 电量采样，只有客户端传了才写喵
        battery_written = False
        if payload.battery is not None:
            # charging 用 0/1 存，SQLite 没有布尔类型喵
            connection.execute(
                upsert_battery_sql,
                (payload.device_id, received_text, payload.battery.percent, 1 if payload.battery.charging else 0),
            )
            # 标记已写入，便于接口回显喵
            battery_written = True

        # 使用时长采样逐条写入喵
        usage_rows_written = 0
        # 喵~注意：AFK 只表示"人离开了"，这一批里还带着的秒数照样入库，
        # 否则客户端刚记下的最后几十秒会被当成空档丢掉，色块与斜纹之间就留出空白喵
        write_usage = decision.stats_enabled or (
            decision.reason == REASON_AFK and bool(payload.usage_delta)
        )
        # 喵~防御：其它门控原因（RDP / 投屏）暂停时仍然丢弃使用时长，只保留心跳与电量喵
        if write_usage:
            for usage_item in payload.usage_delta or []:
                # 喵~防御：0 秒的增量没有信息量，跳过以节省空间喵
                if usage_item.seconds <= 0:
                    continue
                # 按设备+应用+包名+时间点 upsert 喵
                connection.execute(
                    upsert_usage_sql,
                    (
                        payload.device_id,
                        usage_item.app.strip(),
                        (usage_item.package or "").strip()[:200],
                        usage_text,
                        usage_item.seconds,
                    ),
                )
                # 计数加一喵
                usage_rows_written += 1

        # 窗口快照：每次上报落一份，历史不删，清理交给设置页喵
        windows_written = 0
        for window_item in payload.open_windows or []:
            # 喵~防御：应用名为空的窗口没有分析价值，跳过喵
            app_name = window_item.app.strip()
            if not app_name:
                continue
            # 逐条写入快照喵
            connection.execute(
                insert_window_sql,
                (
                    payload.device_id,
                    app_name,
                    (window_item.package or "").strip()[:200],
                    window_item.title.strip()[:512],
                    1 if window_item.minimized else 0,
                    1 if window_item.foreground else 0,
                    received_text,
                ),
            )
            # 计数加一喵
            windows_written += 1

        # 全部成功后再提交，保证要么全写要么全不写喵
        connection.commit()
    except sqlite3.Error:
        # 喵~防御：任何 SQL 异常都回滚，避免留下不完整的数据喵
        connection.rollback()
        raise

    # 返回写入摘要喵
    return IngestResult(
        device_id=payload.device_id,
        duplicate=False,
        usage_rows_written=usage_rows_written,
        windows_written=windows_written,
        battery_written=battery_written,
        stats_paused=not decision.stats_enabled,
        stats_paused_reason="" if decision.stats_enabled else decision.reason,
        mirrored_tags=tuple(mirrored_tags),
    )
