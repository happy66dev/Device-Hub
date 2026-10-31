"""统计门控的单元测试：投屏标签匹配与 RDP 状态判定喵。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db
from app.gating import (
    REASON_AFK,
    REASON_MIRROR_BACKGROUND,
    REASON_MIRROR_FOREGROUND,
    REASON_MIRROR_RDP_DISCONNECTED,
    REASON_RDP_DISCONNECTED,
    REASON_RDP_TARGET_MONITORED,
    GatingSettings,
    decide_stats_enabled,
    match_mirrored_tags,
    reason_text,
)

# 测试基准时间，固定下来避免依赖真实时钟喵
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)


def _insert_device(
    connection,
    device_id: str,
    platform: str = "windows",
    role: str = "workstation",
    tag: str = "",
    rdp_connected: int = 0,
    rdp_updated_at: str | None = None,
    mirrored_tags: list[str] | None = None,
    mirror_foreground: int = 0,
    afk: int = 0,
    last_ip: str = "",
) -> None:
    """往设备表插一行测试数据喵。"""
    # 统一用固定时间，避免 last_seen 影响判定喵
    timestamp = "2026-10-29T11:59:00Z"
    connection.execute(
        """
        INSERT INTO devices (
            device_id, platform, display_name, os_version, hardware_json, current_app_json,
            client_version, first_seen_at, last_seen_at, role, tag, rdp_connected,
            rdp_updated_at, mirror_windows_json, mirrored_tags_json, stats_paused_reason,
            mirror_foreground, afk, last_ip
        ) VALUES (?, ?, ?, ?, '{}', NULL, '', ?, ?, ?, ?, ?, ?, '[]', ?, '', ?, ?, ?)
        """,
        (
            device_id,
            platform,
            device_id,
            "",
            timestamp,
            timestamp,
            role,
            tag,
            rdp_connected,
            rdp_updated_at,
            json.dumps(mirrored_tags or [], ensure_ascii=False),
            mirror_foreground,
            afk,
            last_ip,
        ),
    )
    connection.commit()


def test_match_mirrored_tags_exact_and_substring() -> None:
    """窗口标题包含标签或完全相等都应命中喵。"""
    # 三种命中方式喵
    assert match_mirrored_tags(["23113RKC6C"], ["23113RKC6C"]) == ["23113RKC6C"]
    assert match_mirrored_tags(["scrcpy 23113RKC6C"], ["23113RKC6C"]) == ["23113RKC6C"]
    # 大小写不敏感喵
    assert match_mirrored_tags(["Redmi Note 12"], ["redmi note 12"]) == ["redmi note 12"]


def test_match_mirrored_tags_no_match_and_empty() -> None:
    """对不上或数据为空时返回空列表喵。"""
    # 完全不相关喵
    assert match_mirrored_tags(["Pixel 7"], ["23113RKC6C"]) == []
    # 空标题喵
    assert match_mirrored_tags([], ["23113RKC6C"]) == []
    # 空标签不能匹配所有标题喵
    assert match_mirrored_tags(["Pixel 7"], [""]) == []


def test_gating_disabled_allows_everything(connection) -> None:
    """门控关掉后服务器设备也照常统计喵。"""
    # 关闭门控喵
    settings = GatingSettings(enabled=False)
    # 服务器角色且 RDP 未连接喵
    decision = decide_stats_enabled(connection, "win-srv-0001", "server", "", False, settings, now=NOW)
    # 仍然允许统计喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_server_without_rdp_is_paused(connection) -> None:
    """服务器角色在 RDP 未连接时应暂停统计喵。"""
    # 默认配置喵
    settings = GatingSettings()
    # 判定喵
    decision = decide_stats_enabled(connection, "win-srv-0001", "server", "", False, settings, now=NOW)
    # 应暂停且原因是 RDP 未连接喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_RDP_DISCONNECTED


def test_server_with_rdp_is_enabled(connection) -> None:
    """服务器角色在 RDP 连接时正常统计喵。"""
    # 判定喵
    decision = decide_stats_enabled(connection, "win-srv-0001", "server", "", True, GatingSettings(), now=NOW)
    # 应允许统计喵
    assert decision.stats_enabled is True


def test_android_not_mirrored_keeps_stats(connection) -> None:
    """没有任何服务器投屏它时，安卓设备照常统计喵。"""
    # 插一台没连投屏的服务器喵
    _insert_device(connection, "win-srv-0001", role="server", rdp_connected=1, mirrored_tags=["别的设备"])
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应允许统计（人是直接在用手机）喵
    assert decision.stats_enabled is True


def test_android_without_tag_is_not_gated(connection) -> None:
    """没有标签的安卓设备无法被识别，按直接使用处理喵。"""
    # 插一台正在投屏的服务器喵
    _insert_device(connection, "win-srv-0001", role="server", rdp_connected=0, mirrored_tags=["我的手机"])
    # 判定（标签为空）喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "", False, GatingSettings(), now=NOW)
    # 应允许统计喵
    assert decision.stats_enabled is True


def test_android_mirrored_with_foreground_window_is_enabled(connection) -> None:
    """被投屏且投屏窗口在前台时，安卓设备照常统计喵。"""
    # 服务器 RDP 已连接、投屏窗口在前台，正连着这台手机喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=1,
    )
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应允许统计喵
    assert decision.stats_enabled is True


def test_android_mirrored_without_foreground_is_paused(connection) -> None:
    """被投屏但投屏窗口在后台时，安卓设备应暂停统计喵。"""
    # 服务器 RDP 已连，但投屏窗口缩在后台喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=0,
    )
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应暂停喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_MIRROR_BACKGROUND


def test_android_with_stale_host_keeps_stats(connection) -> None:
    """宿主服务器状态过期说明投屏早结束了，手机应照常统计喵。"""
    # 状态是 10 分钟前的，超过 180 秒有效期喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:50:00Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=1,
    )
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 过期服务器等于没连着，必须照常统计喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_android_with_only_stale_hosts_keeps_stats(connection) -> None:
    """多台宿主全都过期时也要照常统计，不能一直挂着"投屏窗口不在前台"喵。"""
    # 两台都是几天前的残留记录喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-27T08:00:00Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=0,
    )
    _insert_device(
        connection,
        "win-srv-0002",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-27T09:00:00Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=0,
    )
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应照常统计喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_android_stale_host_ignored_when_fresh_host_pauses(connection) -> None:
    """一台过期一台新鲜时，只看新鲜那台，结果仍是暂停喵。"""
    # 过期那台投屏窗口在前台（不该影响结果）喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-27T08:00:00Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=1,
    )
    # 新鲜那台投屏窗口在后台喵
    _insert_device(
        connection,
        "win-srv-0002",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["我的手机"],
        mirror_foreground=0,
    )
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应暂停喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_MIRROR_BACKGROUND


def test_android_mirrored_on_multiple_servers_any_active(connection) -> None:
    """多台服务器同时投屏时，只要有一台的投屏窗口在前台就统计喵。"""
    # 第一台投屏窗口在后台喵
    _insert_device(connection, "win-srv-0001", role="server", rdp_connected=1, rdp_updated_at="2026-10-29T11:59:30Z", mirrored_tags=["我的手机"], mirror_foreground=0)
    # 第二台投屏窗口在前台喵
    _insert_device(connection, "win-srv-0002", role="server", rdp_connected=1, rdp_updated_at="2026-10-29T11:59:30Z", mirrored_tags=["我的手机"], mirror_foreground=1)
    # 判定喵
    decision = decide_stats_enabled(connection, "and-phone-0001", "workstation", "我的手机", False, GatingSettings(), now=NOW)
    # 应允许统计喵
    assert decision.stats_enabled is True


def test_reason_text_translation() -> None:
    """暂停原因应能翻译成中文文案喵。"""
    # 两种已知原因喵
    assert "RDP" in reason_text(REASON_RDP_DISCONNECTED)
    assert "投屏" in reason_text(REASON_MIRROR_RDP_DISCONNECTED)
    # 未知原因也有兜底文案喵
    assert reason_text("unknown_reason") == "统计已暂停"


def test_server_with_mirror_foreground_is_paused(connection) -> None:
    """场景 2 前半：投屏窗口在前台时，服务器自己不该计时喵。"""
    # 服务器已连 RDP，但 scrcpy 抢了前台喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirror_foreground=1,
    )
    decision = decide_stats_enabled(
        connection,
        device_id="win-srv-0001",
        role="server",
        tag="",
        rdp_connected=True,
        settings=GatingSettings(),
        now=NOW,
        mirror_foreground=True,
    )
    # 应当暂停，并给出"投屏窗口在前台"的原因喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_MIRROR_FOREGROUND


def test_server_without_mirror_foreground_is_enabled(connection) -> None:
    """投屏窗口在后台时，服务器照常计时喵。"""
    # 服务器已连 RDP，scrcpy 在后台喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
    )
    decision = decide_stats_enabled(
        connection,
        device_id="win-srv-0001",
        role="server",
        tag="",
        rdp_connected=True,
        settings=GatingSettings(),
        now=NOW,
        mirror_foreground=False,
    )
    assert decision.stats_enabled is True


def test_android_mirrored_with_foreground_mirror_is_enabled(connection) -> None:
    """场景 2 后半：投屏窗口在前台时，只统计手机喵。"""
    # 宿主服务器：RDP 已连 + 投屏窗口在前台喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["小米14"],
        mirror_foreground=1,
    )
    # 安卓设备上报同样的标签喵
    _insert_device(connection, "and-0001", platform="android", tag="小米14")
    decision = decide_stats_enabled(
        connection,
        device_id="and-0001",
        role="workstation",
        tag="小米14",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
    )
    # 手机应当计时喵
    assert decision.stats_enabled is True


def test_android_mirrored_with_background_mirror_is_paused(connection) -> None:
    """场景 2：投屏窗口缩到后台时，手机不该计时喵。"""
    # 宿主服务器：RDP 已连但投屏窗口在后台喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["小米14"],
        mirror_foreground=0,
    )
    _insert_device(connection, "and-0001", platform="android", tag="小米14")
    decision = decide_stats_enabled(
        connection,
        device_id="and-0001",
        role="workstation",
        tag="小米14",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
    )
    # 手机应当暂停喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_MIRROR_BACKGROUND


def test_android_mirrored_with_stale_foreground_state_keeps_stats(connection) -> None:
    """宿主服务器状态过期说明投屏早结束了，手机照常统计喵。"""
    # 状态时间很旧喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T08:00:00Z",
        mirrored_tags=["小米14"],
        mirror_foreground=1,
    )
    _insert_device(connection, "and-0001", platform="android", tag="小米14")
    decision = decide_stats_enabled(
        connection,
        device_id="and-0001",
        role="workstation",
        tag="小米14",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
    )
    # 过期状态等于没连着，必须照常统计喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_reason_text_covers_new_reasons() -> None:
    """新增的两种暂停原因都要有中文文案喵。"""
    # 逐个检查喵
    assert reason_text(REASON_MIRROR_FOREGROUND) == "投屏窗口在前台，本机不计时"
    assert reason_text(REASON_MIRROR_BACKGROUND) == "投屏窗口不在前台，统计已暂停"

def test_afk_pauses_any_device(connection) -> None:
    """场景 1/4：键鼠空闲时，任何角色都不计时喵。"""
    # 服务器角色，RDP 已连接，但人离开了喵
    _insert_device(connection, "win-srv-0001", role="server", rdp_connected=1, rdp_updated_at="2026-10-29T11:59:30Z", afk=1)
    decision = decide_stats_enabled(
        connection,
        device_id="win-srv-0001",
        role="server",
        tag="",
        rdp_connected=True,
        settings=GatingSettings(),
        now=NOW,
        afk=True,
    )
    # 应暂停并给出 AFK 原因喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_AFK


def test_afk_pauses_workstation_too(connection) -> None:
    """工作站 AFK 时同样不计时喵。"""
    # 普通工作站喵
    _insert_device(connection, "win-ws-0001", role="workstation", afk=1)
    decision = decide_stats_enabled(
        connection,
        device_id="win-ws-0001",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
        afk=True,
    )
    assert decision.stats_enabled is False
    assert decision.reason == REASON_AFK


def test_mirrored_android_paused_when_host_afk(connection) -> None:
    """宿主机器 AFK 时，投屏中的手机也不再计时喵。"""
    # 投屏窗口在前台，但服务器 AFK 喵
    _insert_device(
        connection,
        "win-srv-0001",
        role="server",
        rdp_connected=1,
        rdp_updated_at="2026-10-29T11:59:30Z",
        mirrored_tags=["小米14"],
        mirror_foreground=1,
        afk=1,
    )
    _insert_device(connection, "and-0001", platform="android", tag="小米14")
    decision = decide_stats_enabled(
        connection,
        device_id="and-0001",
        role="workstation",
        tag="小米14",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
    )
    # 应暂停喵
    assert decision.stats_enabled is False


def test_reason_text_for_afk() -> None:
    """AFK 原因要有中文文案喵。"""
    assert reason_text(REASON_AFK) == "键鼠空闲，统计已暂停"


def test_server_counts_even_with_unknown_rdp_client(connection) -> None:
    """陌生客户端连进来也照常计时，主人说过不该暂停喵。"""
    # 服务器角色，RDP 已连接喵
    _insert_device(connection, "win-srv-unknown-1", role="server", rdp_connected=1)
    # 客户端身份是个没见过的 IP 与机器名喵
    decision = decide_stats_enabled(
        connection,
        device_id="win-srv-unknown-1",
        role="server",
        tag="",
        rdp_connected=True,
        settings=GatingSettings(),
        now=NOW,
        rdp_client_ip="100.88.1.9",
        rdp_client_name="FRIEND-PC",
    )
    # 认不出来也不暂停喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_mstsc_to_monitored_device_pauses_locally(connection) -> None:
    """远程桌面连到自己人时，本机不计时，改由那台设备计时喵。"""
    # 目标设备在设备表里，最近上报 IP 是 192.168.2.9 喵
    _insert_device(connection, "win-target-0001", role="server", rdp_connected=1, last_ip="192.168.2.9")
    # 本机是工作站，前台是 mstsc，目标是那个 IP 喵
    _insert_device(connection, "win-client-0001")
    decision = decide_stats_enabled(
        connection,
        device_id="win-client-0001",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
        current_package="mstsc.exe",
        rdp_target="192.168.2.9:3389",
    )
    # 目标是自己人 → 本机暂停喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_RDP_TARGET_MONITORED


def test_mstsc_to_unknown_target_counts_as_usage(connection) -> None:
    """连到不认识的目标（frp / tailscale 地址）时，本机照常记 mstsc 的使用喵。"""
    # 只有本机在设备表里喵
    _insert_device(connection, "win-client-0002")
    decision = decide_stats_enabled(
        connection,
        device_id="win-client-0002",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
        current_package="mstsc.exe",
        rdp_target="100.101.102.103",
    )
    # 认不出来就当作本机在使用远程桌面喵
    assert decision.stats_enabled is True
    assert decision.reason == ""


def test_mstsc_without_target_counts_as_usage(connection) -> None:
    """解析不出目标地址时也照常计时，避免时间凭空消失喵。"""
    # 只有本机在设备表里喵
    _insert_device(connection, "win-client-0003")
    decision = decide_stats_enabled(
        connection,
        device_id="win-client-0003",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
        current_package="mstsc.exe",
    )
    assert decision.stats_enabled is True


def test_mstsc_target_matches_hostname(connection) -> None:
    """目标写的是机器名时也要能认出是自己人喵。"""
    # 目标设备的展示名就是机器名喵
    _insert_device(connection, "win-target-0002", role="server", rdp_connected=1)
    connection.execute("UPDATE devices SET display_name = ? WHERE device_id = ?", ("HAPPYPC", "win-target-0002"))
    connection.commit()
    # 本机前台是 mstsc，目标写机器名喵
    _insert_device(connection, "win-client-0004")
    decision = decide_stats_enabled(
        connection,
        device_id="win-client-0004",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(),
        now=NOW,
        current_package="MSTSC.EXE",
        rdp_target="HAPPYPC",
    )
    # 机器名大小写不同也能认出来喵
    assert decision.stats_enabled is False
    assert decision.reason == REASON_RDP_TARGET_MONITORED


def test_allowed_clients_bypass_target_check(connection) -> None:
    """手动放行名单里的目标按自己人处理喵。"""
    # 只有本机在设备表里喵
    _insert_device(connection, "win-client-0005")
    decision = decide_stats_enabled(
        connection,
        device_id="win-client-0005",
        role="workstation",
        tag="",
        rdp_connected=False,
        settings=GatingSettings(rdp_allowed_clients=("10.8.0.2",)),
        now=NOW,
        current_package="mstsc.exe",
        rdp_target="10.8.0.2",
    )
    assert decision.stats_enabled is False
    assert decision.reason == REASON_RDP_TARGET_MONITORED


