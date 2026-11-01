"""`/happy设备` 输出格式的回归测试喵。

覆盖三条主人明确要求的格式：
1. 挂机与活跃应用都不加括号；
2. 文案是「设备近24小时使用 X」而不是「近24小时 X」；
3. 活跃时直接用最近上报的应用名替换「活跃软件」这个泛称喵。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conftest import TEST_INGEST_TOKEN

from app import people
from app.config import AppConfig
from app.db import to_utc_text


def _register(
    connection,
    device_id: str,
    name: str,
    platform: str,
    afk: bool = False,
    seen: datetime | None = None,
) -> None:
    """直接往 devices 表塞一台设备喵。"""
    # 默认「刚刚」见过，保证判为在线喵
    moment = seen or datetime.now(timezone.utc)
    connection.execute(
        "INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,"
        " current_app_json, client_version, first_seen_at, last_seen_at, role, afk) "
        "VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?, 'workstation', ?)",
        (device_id, platform, name, to_utc_text(moment), to_utc_text(moment), 1 if afk else 0),
    )
    connection.commit()


def _add_usage(connection, device_id: str, app: str, seconds: int, ago: int) -> None:
    """写一条使用采样，ago 是「多少秒之前」喵。"""
    moment = datetime.now(timezone.utc) - timedelta(seconds=ago)
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
        (device_id, app, f"{app.lower()}", to_utc_text(moment), seconds),
    )
    connection.commit()


def _set_group(app_config: AppConfig, devices: tuple[str, ...]) -> None:
    """写「主人」设备组喵。"""
    people.save_people(app_config.server.db_path, [people.PersonGroup(name="happy", devices=devices)])


def _render(client: TestClient) -> str:
    """通过模拟接口拿到 /happy设备 的回复文本喵。"""
    response = client.post(
        "/api/v1/bot/command",
        json={"text": "/happy设备"},
        headers={"X-Ingest-Token": TEST_INGEST_TOKEN},
    )
    assert response.status_code == 200, response.text
    return response.json()["text"]


def _active_device(client: TestClient, connection, app_config: AppConfig) -> str:
    """造一台在线、非挂机、刚用过 Notepad.exe 的设备喵。"""
    _register(connection, "win-fmt-0001", "格式机", "windows")
    _set_group(app_config, ("win-fmt-0001",))
    # 最近 30 秒内有使用，保证判为「在用」喵
    _add_usage(connection, "win-fmt-0001", "Notepad.exe", 120, 30)
    return "win-fmt-0001"


def test_device_block_has_no_parentheses(client: TestClient, connection, app_config) -> None:
    """设备行里的挂机/应用名都不能带括号喵。"""
    # 造一台在用设备喵
    _active_device(client, connection, app_config)
    # 渲染输出喵
    text = _render(client)
    # 喵~注意：全角与半角括号都不允许出现在状态行里喵
    assert "（活跃软件）" not in text
    assert "(活跃软件)" not in text
    assert "（挂机）" not in text
    assert "(挂机)" not in text


def test_device_block_uses_new_wording(client: TestClient, connection, app_config) -> None:
    """文案必须是「设备近24小时使用」喵。"""
    # 造一台在用设备喵
    _active_device(client, connection, app_config)
    # 渲染输出喵
    text = _render(client)
    # 新文案要在喵
    assert "设备近24小时使用" in text
    # 喵~注意：旧的「·近24小时 」不能残留，否则会和新文案并存喵
    assert "·近24小时 " not in text


def test_device_block_shows_latest_reported_app(client: TestClient, connection, app_config) -> None:
    """活跃时要用最近上报的应用名替换「活跃软件」喵。"""
    # 造一台在用设备喵
    _active_device(client, connection, app_config)
    # 渲染输出喵
    text = _render(client)
    # 应用名要在，泛称不能出现喵
    assert "Notepad.exe" in text
    assert "活跃软件" not in text


def test_device_block_keeps_afk_label(client: TestClient, connection, app_config) -> None:
    """挂机时仍然写「挂机」，不显示应用名喵。"""
    # 造一台在线但 AFK 的设备喵
    _register(connection, "win-fmt-0002", "挂机机", "windows", afk=True)
    _set_group(app_config, ("win-fmt-0002",))
    # 最近 10 分钟用过，但心跳 AFK，判为挂机喵
    _add_usage(connection, "win-fmt-0002", "QQ.exe", 60, 120)
    # 渲染输出喵
    text = _render(client)
    # 挂机标签要在，且不带括号喵
    assert "挂机" in text
    assert "（挂机）" not in text


def test_device_block_falls_back_when_no_usage(client: TestClient, connection, app_config) -> None:
    """没有任何使用记录时退回「活跃软件」，不能显示空白喵。"""
    # 只注册设备，不写使用记录喵
    _register(connection, "win-fmt-0003", "空机", "windows")
    _set_group(app_config, ("win-fmt-0003",))
    # 渲染输出喵
    text = _render(client)
    # 喵~注意：没有使用记录时要有兜底文案喵
    assert "设备近24小时使用" in text
    assert "活跃软件" in text


def test_offline_device_shows_last_seen_ago(client: TestClient, connection, app_config) -> None:
    """离线设备必须画出「上次在线 X 前」，不能只有两个字「离线」喵。"""
    # 造一台三小时前最后一次上报的设备喵
    _register(
        connection,
        "win-fmt-0004",
        "离线机",
        "windows",
        seen=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    _set_group(app_config, ("win-fmt-0004",))
    # 渲染输出喵
    text = _render(client)
    # 喵~注意：模板原来引用的是不存在的变量「最近上报时间」，渲染出来是空串喵
    assert "上次在线" in text
    assert "3 小时前" in text


def test_online_device_has_no_last_seen_line(client: TestClient, connection, app_config) -> None:
    """在线设备不该出现「上次在线」这个词喵。"""
    # 造一台刚上报过的设备喵
    _active_device(client, connection, app_config)
    # 渲染输出喵
    text = _render(client)
    # 在线时就只是「在线」两个字喵
    assert "上次在线" not in text
