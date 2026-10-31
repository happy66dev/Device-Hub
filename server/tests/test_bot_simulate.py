"""命令测试模拟器的单元测试喵。"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app import ingest, people
from app.bot import router, simulate
from app.config import AppConfig
from app.models import ReportPayload
from conftest import make_payload

# 白名单群号，与 conftest 的 app_config 保持一致喵
ALLOWED_GROUP = 111111

# 黑名单用户，与 conftest 的 app_config 保持一致喵
BLOCKED_USER = 222222

# 普通用户喵
NORMAL_USER = 333333

# PNG 文件头，用于确认输出真的是 PNG 喵
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _seed_device(connection: sqlite3.Connection, device_id: str) -> None:
    """插入一台设备，供命令测试取数据喵。"""
    # 上报时间用当前时间，保证在线喵
    reported_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    # 构造上报对象喵
    payload = ReportPayload.model_validate(
        make_payload(device_id=device_id, reported_at=reported_at.isoformat(), display_name="测试机")
    )
    # 落库喵
    ingest.save_report(connection, payload, datetime.now(timezone.utc))


def _set_group(config: AppConfig, device_ids: tuple[str, ...]) -> None:
    """把设备写进看板里的「主人」组，happy 系列命令才认喵。"""
    # 直接复用 people 模块的保存函数喵
    people.save_people(config.server.db_path, [people.PersonGroup(name="主人", devices=device_ids)])


def test_simulate_help_without_acl(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """不填群号时应跳过白名单，直接给出帮助文本喵。"""
    # 跑一次帮助命令喵
    result = simulate.simulate_command(connection, app_config, "/happy帮助")
    # 应判定为会回复喵
    assert result.replied is True
    assert result.reason == router.REASON_OK
    # 命令名应为 happy帮助喵
    assert result.command_name == "happy帮助"
    # 回复里应带命令说明喵
    assert "/happy帮助" in result.text
    assert "happy设备" in result.text and "happy在干嘛" in result.text


def test_simulate_auto_prefix(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """没写斜杠时自动补前缀，省得主人在页面上多打字喵。"""
    # 不带斜杠的设备命令喵
    result = simulate.simulate_command(connection, app_config, "happy设备")
    # 应正常回复喵
    assert result.replied is True
    assert result.command_name == "happy设备"


def test_simulate_device_list(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """设备清单应包含主人组里的设备名与 ID 喵。"""
    # 先塞一台设备并归入主人组喵
    _seed_device(connection, "win-sim-0001")
    _set_group(app_config, ("win-sim-0001",))
    # 跑设备清单命令喵
    result = simulate.simulate_command(connection, app_config, "/happy设备")
    # 回复里应有设备名喵
    assert "测试机" in result.text
    # 喵~注意：主人要求标题不再带「主人 · N 台」统计喵
    assert "主人" not in result.text


def test_simulate_look_happy_reports_wait_text(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """出图命令在模拟器里应给出「正在生成」的文本回复喵。"""
    # 塞一台设备并归入主人组喵
    _seed_device(connection, "win-sim-0002")
    _set_group(app_config, ("win-sim-0002",))
    # 打开图片渲染，模拟器会先试出图喵
    image_config = replace(app_config, render=replace(app_config.render, image_enabled=True))
    # 请求排行榜图喵
    result = simulate.simulate_command(connection, image_config, "/看看happy 全部 排行榜")
    # 应正常回复喵
    assert result.replied is True
    # 喵~注意：模拟器不出图时退回文本，提示正在生成排行榜图片喵
    if result.image is None:
        assert "正在生成排行榜图片" in result.text
    else:
        # 真出了图时不应再发文本，和真实机器人一致喵
        assert result.image[:8] == PNG_SIGNATURE
        assert result.text == ""


def test_simulate_look_happy_usage_error_hint(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """缺少子命令时应把用法提示当文本发出来喵。"""
    # 塞一台设备并归入主人组喵
    _seed_device(connection, "win-sim-0004")
    _set_group(app_config, ("win-sim-0004",))
    # 只写范围、不写排行榜/时间轴喵
    result = simulate.simulate_command(connection, app_config, "/看看happy 全部")
    # 应回复用法提示喵
    assert result.replied is True
    assert "用法" in result.text


def test_simulate_group_not_whitelisted(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """群号不在白名单时应报告被忽略及原因喵。"""
    # 用未授权群号喵
    result = simulate.simulate_command(connection, app_config, "/happy设备", group_id=999999)
    # 不应回复喵
    assert result.replied is False
    assert result.reason == router.REASON_GROUP_NOT_WHITELISTED
    # 原因说明应为中文提示喵
    assert "白名单" in result.reason_text


def test_simulate_blacklisted_user(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """黑名单用户即使群号正确也不回复喵。"""
    # 白名单群 + 黑名单用户喵
    result = simulate.simulate_command(
        connection, app_config, "/happy设备", group_id=ALLOWED_GROUP, user_id=BLOCKED_USER
    )
    # 应被忽略喵
    assert result.replied is False
    assert result.reason == router.REASON_USER_BLACKLISTED


def test_simulate_allowed_group_replies(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """白名单群 + 普通用户应正常回复喵。"""
    # 塞一台设备并归入主人组喵
    _seed_device(connection, "win-sim-0003")
    _set_group(app_config, ("win-sim-0003",))
    # 走完整 ACL 判断喵
    result = simulate.simulate_command(
        connection, app_config, "/happy设备", group_id=ALLOWED_GROUP, user_id=NORMAL_USER
    )
    # 应正常回复喵
    assert result.replied is True
    assert result.reason == router.REASON_OK
    assert "测试机" in result.text


def test_simulate_empty_command(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """空命令应返回明确原因而不是空回复喵。"""
    # 空字符串喵
    result = simulate.simulate_command(connection, app_config, "   ")
    # 应被判定为空命令喵
    assert result.replied is False
    assert result.reason == simulate.REASON_EMPTY
    assert result.text == ""
