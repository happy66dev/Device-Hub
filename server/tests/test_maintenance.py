"""定期维护任务的测试喵。

喵~注意：这里最要紧的一条是「不接 QQ 通道时维护依然会跑」。
以前归档和清理长在 BotRunner 里，纯服务端部署时 main 压根不创建
BotRunner，于是数据永远不清理、也不归档，日志里还一个字都不打喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import archive, db, maintenance
from app.config import (
    AclSection,
    AppConfig,
    GatingSection,
    IngestSection,
    NapCatSection,
    QQBotSection,
    RenderSection,
    RetentionSection,
    RolesSection,
    ServerSection,
)
from app.db import to_utc_text

# 基准时刻，固定下来免得测试跟着真实时间漂喵
BASE_NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)

# 测试用设备喵
DEVICE = "win-maint-0001"


def _config(tmp_path) -> AppConfig:
    """造一份指向临时库的配置，两个机器人通道都关掉喵。"""
    return AppConfig(
        server=ServerSection(host="127.0.0.1", port=8080, db_path=tmp_path / "device_hub.db"),
        ingest=IngestSection(token="test-token", max_payload_bytes=4096),
        retention=RetentionSection(detail_days=7, aggregate_days=30),
        napcat=NapCatSection(enabled=False, ws_url="ws://127.0.0.1:7999", token="", reconnect_seconds=1, self_qq=""),
        qqbot=QQBotSection(enabled=False),
        acl=AclSection(whitelist_groups=(), blacklist_users=()),
        render=RenderSection(max_hardware_fields=8, image_enabled=False),
        roles=RolesSection(servers=(), workstations=()),
        gating=GatingSection(),
        base_dir=tmp_path,
    )


def _seed(connection: sqlite3.Connection, moment: datetime) -> None:
    """插一条设备与一条上报喵。"""
    # 设备行喵
    connection.execute(
        "INSERT OR REPLACE INTO devices (device_id, platform, display_name, os_version,"
        " hardware_json, current_app_json, client_version, first_seen_at, last_seen_at, role)"
        " VALUES (?, 'windows', '维护测试机', '', '{}', NULL, '0.1.0', ?, ?, 'workstation')",
        (DEVICE, to_utc_text(moment), to_utc_text(moment)),
    )
    # 上报行喵
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
        (DEVICE, to_utc_text(moment), to_utc_text(moment), b'{"afk": false}'),
    )


def test_is_archive_window_only_on_eighth() -> None:
    """归档窗口只在每月 8 号那天喵。"""
    # 8 号该归档喵
    assert maintenance.is_archive_window(datetime(2026, 11, 8, 0, 5, tzinfo=timezone.utc)) is True
    assert maintenance.is_archive_window(datetime(2026, 11, 8, 23, 55, tzinfo=timezone.utc)) is True
    # 其它日子都不该归档喵
    for day in (1, 7, 9, 15, 28):
        assert maintenance.is_archive_window(datetime(2026, 11, day, 3, 0, tzinfo=timezone.utc)) is False


def test_archive_window_setting_is_eighth() -> None:
    """配置常量就是 8，改代码时别手滑喵。"""
    assert maintenance.ARCHIVE_DAY_OF_MONTH == 8


def test_prune_once_works_without_bot(tmp_path) -> None:
    """两个通道都关着，清理照样能跑喵。

    喵~注意：这条是防回归的核心。以前 main 只在「有通道启用」时创建
    BotRunner，而清理逻辑长在 BotRunner 里，纯服务端部署就永远不清理喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 一条很老的使用时长，超过聚合保留期喵
        # 喵~注意：用 usage_samples 而不是 reports——reports 现在只删已归档的喵
        _seed(connection, BASE_NOW)
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)"
            " VALUES (?, 'Old.exe', 'old.exe', ?, 60)",
            (DEVICE, to_utc_text(BASE_NOW - timedelta(days=40))),
        )
        connection.commit()
    finally:
        connection.close()
    # 直接调清理，不经过任何机器人对象喵
    deleted = maintenance.prune_once(config)
    # 超期的使用时长该被清掉喵
    assert deleted.get("usage_samples", 0) == 1


def test_archive_once_works_without_bot(tmp_path) -> None:
    """两个通道都关着，归档照样能跑喵。"""
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 上个月的数据，整月都过完热保留期了喵
        _seed(connection, datetime(2026, 10, 15, tzinfo=timezone.utc))
        connection.commit()
    finally:
        connection.close()
    # 直接调归档喵
    result = maintenance.archive_once(config, now=BASE_NOW)
    # 该压出一个块喵
    assert result.blocks == 1
    # 原始行该被取走喵
    assert result.rows == 1
    # 归档块确实存在喵
    connection = db.connect(config.server.db_path)
    try:
        assert archive.has_block(connection, DEVICE, archive.archive_codec.KIND_HEARTBEATS, "2026-10")
    finally:
        connection.close()


def test_run_once_prunes_but_skips_archive_when_asked(tmp_path) -> None:
    """run_once 能给「只清理、不归档」的模式用喵。"""
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 一条很老的使用时长喵
        _seed(connection, BASE_NOW)
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)"
            " VALUES (?, 'Old.exe', 'old.exe', ?, 60)",
            (DEVICE, to_utc_text(datetime(2026, 9, 15, tzinfo=timezone.utc))),
        )
        connection.commit()
    finally:
        connection.close()
    # 只清理不归档喵
    result = maintenance.run_once(config, include_archive=False)
    # 没有归档动作喵
    assert result.archived_blocks == 0
    assert result.archived_rows == 0
    # 但清理照常喵
    assert result.deleted.get("usage_samples", 0) == 1


@pytest.mark.asyncio()
async def test_maintenance_loop_archives_on_the_eighth(tmp_path) -> None:
    """8 号那一轮会归档，其它日子不会喵。"""
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 上个月的整月数据喵
        _seed(connection, datetime(2026, 10, 15, tzinfo=timezone.utc))
        connection.commit()
    finally:
        connection.close()
    # 假时钟：11-03 一轮（不该归档），11-08 两轮（第一次归档，第二次跳过）喵
    moments = [
        datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 8, 2, 0, tzinfo=timezone.utc),
    ]
    # 已经取到第几个时刻喵
    state = {"index": 0}

    def fake_clock() -> datetime:
        """按顺序吐预设时刻，取完就停在最后一个喵。"""
        index = min(state["index"], len(moments) - 1)
        state["index"] += 1
        return moments[index]

    # 替换 sleep，别真等一小时喵
    real_sleep = maintenance.asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        """立刻返回；跑够三轮就抛信号结束循环喵。"""
        # 喵~防御：跑够三轮，覆盖「3 号不归档 + 8 号归档 + 8 号重复跳过」喵
        if state["index"] >= 4:
            raise KeyboardInterrupt

    maintenance.asyncio.sleep = fast_sleep
    try:
        # 跑几轮，最后靠 KeyboardInterrupt 结束喵
        with pytest.raises(KeyboardInterrupt):
            await maintenance.maintenance_loop(config, interval_seconds=60, clock=fake_clock)
    finally:
        # 还原 sleep，别污染其它测试喵
        maintenance.asyncio.sleep = real_sleep
    # 喵~注意：3 号那轮不该归档，8 号那轮才归档喵
    connection = db.connect(config.server.db_path)
    try:
        # 10 月整月该被压成一块喵
        assert archive.has_block(connection, DEVICE, archive.archive_codec.KIND_HEARTBEATS, "2026-10")
        # 块里正好那一条喵
        block = archive.load_heartbeat_block(connection, DEVICE, "2026-10")
        assert len(archive.archive_codec.decode_heartbeats(block)) == 1
        # 原始行已经被取走（8 号那轮清理也会顺带删掉超期数据）喵
        remaining = connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
        assert remaining == 0
    finally:
        connection.close()


@pytest.mark.asyncio()
async def test_maintenance_loop_archives_before_pruning(tmp_path) -> None:
    """归档必须排在清理前面喵。

    喵~注意：现在清理只删「所在月份已经有块」的行，所以顺序反了也不会丢数据，
    但归档排前面仍是对的——它保证同一个周期里先入库再腾地方，
    库的体积峰值最小，而且万一清理写错条件也不会波及还没归档的数据喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 40 天前的数据：整月已经过完了喵
        _seed(connection, BASE_NOW - timedelta(days=40))
        connection.commit()
    finally:
        connection.close()
    # 假时钟停在 8 号，让归档窗口命中喵
    state = {"index": 0}

    def fake_clock() -> datetime:
        """永远返回 8 号喵。"""
        state["index"] += 1
        return BASE_NOW

    # 替换 sleep 喵
    real_sleep = maintenance.asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        """跑一轮就够喵。"""
        if state["index"] >= 2:
            raise KeyboardInterrupt

    maintenance.asyncio.sleep = fast_sleep
    try:
        with pytest.raises(KeyboardInterrupt):
            await maintenance.maintenance_loop(config, interval_seconds=60, clock=fake_clock)
    finally:
        maintenance.asyncio.sleep = real_sleep
    # 喵~注意：这条数据必须先被归档、再被清理，所以归档块里一定有它喵
    connection = db.connect(config.server.db_path)
    try:
        assert archive.has_block(connection, DEVICE, archive.archive_codec.KIND_HEARTBEATS, "2026-09")
        block = archive.load_heartbeat_block(connection, DEVICE, "2026-09")
        assert len(archive.archive_codec.decode_heartbeats(block)) == 1
        # 原始行已经被清理掉了喵
        remaining = connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
        assert remaining == 0
    finally:
        connection.close()
