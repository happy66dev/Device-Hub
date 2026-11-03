"""定期维护任务的测试喵。

喵~注意：这里最要紧的一条是「不接 QQ 通道时维护依然会跑」。
以前归档和清理长在 BotRunner 里，纯服务端部署时 main 压根不创建
BotRunner，于是数据永远不清理、也不归档，日志里还一个字都不打喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import archive, db, maintenance, queries
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
    # 喵~注意：这里传本地时区的 8 号。判断口径是「本地日」，
    # 传 UTC 的 8 号 23:55 在东八区已经是 9 号了，不该进窗口喵
    tz8 = timezone(timedelta(hours=8))
    # 8 号该归档喵
    assert maintenance.is_archive_window(datetime(2026, 11, 8, 0, 5, tzinfo=tz8)) is True
    assert maintenance.is_archive_window(datetime(2026, 11, 8, 23, 55, tzinfo=tz8)) is True
    # 其它日子都不该归档喵
    for day in (1, 7, 9, 15, 28):
        assert maintenance.is_archive_window(datetime(2026, 11, day, 3, 0, tzinfo=tz8)) is False


def test_archive_window_setting_is_eighth() -> None:
    """配置常量就是 8，改代码时别手滑喵。"""
    assert maintenance.ARCHIVE_DAY_OF_MONTH == 8


def test_archive_window_uses_local_day_not_utc() -> None:
    """归档窗口要按**本地日**算 8 号，不能直接用 UTC 的日期喵。

    喵~注意：这是真实踩过的坑。`utc_now()` 给的是 UTC，
    东八区下「UTC 8 号」其实是本地 8 号 08:00 到 9 号 08:00，
    主人要的「8 号凌晨归档」会整整晚 8 小时才开始喵。
    """
    # 东八区时区喵
    tz8 = timezone(timedelta(hours=8))
    # 本地 12-08 00:00 就是 UTC 12-07 16:00，必须已经进窗口喵
    assert maintenance.is_archive_window(datetime(2026, 12, 7, 16, 0, tzinfo=timezone.utc)) is True
    # 本地 12-07 23:59 还没到，不能提前跑喵
    assert maintenance.is_archive_window(datetime(2026, 12, 7, 15, 59, tzinfo=timezone.utc)) is False
    # 本地 12-08 23:59 仍在窗口内喵
    assert maintenance.is_archive_window(datetime(2026, 12, 8, 15, 59, tzinfo=timezone.utc)) is True
    # 本地 12-09 00:00 已经出窗口喵
    assert maintenance.is_archive_window(datetime(2026, 12, 8, 16, 0, tzinfo=timezone.utc)) is False
    # 反过来说：UTC 8 号在本地已经是 8 号下午，依然该归档喵
    assert maintenance.is_archive_window(datetime(2026, 12, 8, 12, 0, tzinfo=timezone.utc)) is True
    # 用本地时区直接构造也要一致喵
    assert maintenance.is_archive_window(datetime(2026, 12, 8, 0, 5, tzinfo=tz8)) is True


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


@pytest.mark.asyncio
async def test_maintenance_loop_survives_non_sqlite_error(tmp_path, monkeypatch) -> None:
    """非数据库异常也不能让维护任务整个死掉喵。

    喵~注意：这是曾经的隐患。`prune_once` 那条链路除了 sqlite3.Error，
    还会抛 OSError（磁盘满、文件被占）、zlib.error（块损坏）、
    ValueError（时间格式不对）等。原来 `maintenance_loop` 只捕获 sqlite3.Error，
    这些异常一旦逃出去，这个 task 就彻底结束了——再也不会归档与清理，
    而它没人 await，只会变成一条 "Task exception was never retrieved" 喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    # 前两轮抛非数据库异常，第三轮放行，用来证明循环没被打断喵
    state = {"calls": 0}

    def flaky_prune_once(_config):
        """前两次抛 OSError，之后正常返回喵。"""
        state["calls"] += 1
        # 喵~防御：模拟磁盘满这类不属于 sqlite3.Error 的异常喵
        if state["calls"] <= 2:
            raise OSError(28, "磁盘空间不足")
        return {"reports": 0}

    # 换上会抛非 sqlite 异常的 prune_once 喵
    monkeypatch.setattr(maintenance, "prune_once", flaky_prune_once)
    # 窗口外的日子不会触发归档，专注测清理那条路径喵
    moment = BASE_NOW - timedelta(days=20)

    def fake_clock() -> datetime:
        """固定时刻，不落在归档窗口上喵。"""
        return moment

    # 替换 sleep，跑够三轮就把循环用 KeyboardInterrupt 收掉喵
    real_sleep = maintenance.asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        """三轮之后退出喵。"""
        if state["calls"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(maintenance.asyncio, "sleep", fast_sleep)
    try:
        with pytest.raises(KeyboardInterrupt):
            await maintenance.maintenance_loop(config, interval_seconds=60, clock=fake_clock)
    finally:
        # 还原 sleep，避免影响别的用例喵
        maintenance.asyncio.sleep = real_sleep
    # 喵~注意：关键断言——异常之后循环还在继续，所以 prune_once 被调用了三轮喵
    assert state["calls"] == 3


def test_vacuum_once_shrinks_database(tmp_path) -> None:
    """删过数据后 VACUUM 要能真的把文件缩小喵。

    喵~注意：SQLite 的 DELETE 只把页标成空闲，文件不会变小。
    不跑 VACUUM 的话，归档删掉几十万行后磁盘一点没释放——
    实测空页能占到 109 MB，回收完只剩 1.9 MB 喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    # 灌一批数据把文件撑大喵
    # 喵~注意：不能循环调 _seed——它每次 INSERT OR REPLACE devices，
    # 而 REPLACE 是「删旧行再插新行」，会触发 ON DELETE CASCADE
    # 把先前灌的 reports 全连锁删掉，最后库还是空的喵
    connection = db.connect(config.server.db_path)
    try:
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        # 设备只插一次喵
        _seed(connection, base)
        # 再灌大量上报喵
        connection.executemany(
            "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
            [
                (
                    DEVICE,
                    to_utc_text(base + timedelta(seconds=index)),
                    to_utc_text(base + timedelta(seconds=index)),
                    b'{"afk": false}',
                )
                for index in range(1, 4001)
            ],
        )
        connection.commit()
    finally:
        connection.close()
    # 记下撑大后的体积喵
    before_delete = config.server.db_path.stat().st_size
    # 全删掉喵
    connection = db.connect(config.server.db_path)
    try:
        connection.execute("DELETE FROM reports")
        connection.commit()
    finally:
        connection.close()
    # 删完但没 VACUUM，文件应该还是原来那么大喵
    assert config.server.db_path.stat().st_size >= before_delete
    # 跑 VACUUM 喵
    before, after = maintenance.vacuum_once(config)
    # 文件必须真的变小喵
    assert after < before
    # 而且小得明显，不是只缩了一点点喵
    assert after < before / 2


def test_vacuum_once_does_not_raise_while_writes_are_going(tmp_path, monkeypatch) -> None:
    """VACUUM 撞上并发写入时只能安静放弃，不能把异常抛给维护循环喵。

    喵~注意：采集端每 60 秒写一次上报，VACUUM 要独占锁，
    真机上必然经常拿到 `database is locked`。以前这里不接这个异常，
    结果「清理和归档都成功了、只是没回收空间」会被记成「定期维护失败」，
    日志把一次成功误导成失败喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    # 真连接用来确认库还在，假连接只负责抛锁异常喵
    real_connect = db.connect

    class _LockedConnection:
        """只模拟「拿不到锁」的连接，其余方法都不需要喵。"""

        def commit(self):
            """提交是空操作喵。"""

        def execute(self, _sql, *_args, **_kwargs):
            """任何语句都当成撞锁喵。"""
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            """关连接是空操作喵。"""

    # 让 vacuum_once 用假连接喵
    monkeypatch.setattr(maintenance.db, "connect", lambda _path: _LockedConnection())
    # 别真的睡，测试要快喵
    monkeypatch.setattr(maintenance.time, "sleep", lambda _seconds: None)
    # 不许抛异常喵
    before, after = maintenance.vacuum_once(config)
    # 失败时如实返回「没变」喵
    assert before == after
    # 文件必须还在，别把库删了喵
    assert config.server.db_path.exists()
    # 恢复真连接，确认库本身没被这次失败搞坏喵
    monkeypatch.setattr(maintenance.db, "connect", real_connect)
    connection = db.connect(config.server.db_path)
    try:
        # 表还能正常查喵
        assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0
    finally:
        connection.close()


def test_prune_once_backfills_daily_usage(tmp_path) -> None:
    """清理之前要先固化每日汇总，否则删掉的明细永远补不回来喵。

    喵~注意：这条盯的是顺序。`prune_once` 里如果先清理再汇总，
    超过聚合保留期的明细已经被删，那几天的汇总就永远缺了喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 一条 40 天前的使用时长，会超出 30 天聚合保留期喵
        _seed(connection, BASE_NOW)
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)"
            " VALUES (?, 'Old.exe', 'old.exe', ?, 600)",
            (DEVICE, to_utc_text(BASE_NOW - timedelta(days=40))),
        )
        connection.commit()
    finally:
        connection.close()
    # 跑清理喵
    maintenance.prune_once(config)
    # 明细被删了喵
    connection = db.connect(config.server.db_path)
    try:
        assert connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"] == 0
        # 但汇总表里有那天的记录，长程热力图不会缺喵
        row = connection.execute("SELECT seconds FROM daily_usage").fetchone()
        assert row is not None
        assert row["seconds"] == 600
    finally:
        connection.close()


def test_oldest_usage_days_covers_very_old_detail(tmp_path) -> None:
    """回溯窗口必须盖住库里最老的那条明细，不能写死在 400 天喵。

    喵~注意：这是真实缺陷。`prune_once` 原来用 `rebuild_daily_usage` 的默认
    `days=400`，而热力图能看 740 天、`retention.aggregate_days` 还能配到 3650。
    比 400 天更早的那几天永远进不了汇总表，明细一删就永久缺一块、无法恢复喵。
    """
    # 建临时库喵
    db_path = tmp_path / "usage.db"
    db.init_db(db_path)
    connection = db.connect(db_path)
    try:
        # 造一台设备喵
        stamp = to_utc_text(BASE_NOW)
        connection.execute(
            "INSERT INTO devices (device_id, platform, display_name, first_seen_at, last_seen_at)"
            " VALUES (?, 'windows', '回溯机', ?, ?)",
            (DEVICE, stamp, stamp),
        )
        # 450 天前塞一条，正好超过旧的 400 天上限喵
        old_moment = BASE_NOW - timedelta(days=450)
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)"
            " VALUES (?, 'Old.exe', 'old.exe', ?, 5000)",
            (DEVICE, to_utc_text(old_moment)),
        )
        connection.commit()
        # 算出来的窗口必须盖住 450 天喵
        days = maintenance._oldest_usage_days(connection)
        assert days >= 450, f"只有 {days} 天，450 天前那条会被漏掉"
        # 按这个窗口重算，必须真的写出那条喵
        assert queries.rebuild_daily_usage(connection, 480, days, BASE_NOW) == 1
        row = connection.execute("SELECT seconds FROM daily_usage").fetchone()
        assert row is not None and row["seconds"] == 5000
        # 对照：旧口径写死 400 天时会漏掉喵
        connection.execute("DELETE FROM daily_usage")
        connection.commit()
        assert queries.rebuild_daily_usage(connection, 480, 400, BASE_NOW) == 0
    finally:
        connection.close()


def test_prune_once_backfills_detail_older_than_four_hundred_days(tmp_path) -> None:
    """走完整 `prune_once`：450 天前的明细也必须先进汇总再被删喵。

    喵~注意：这个用例故意从 `prune_once` 入口走，而不是只测辅助函数——
    写死 `days=400` 的地方就在 `prune_once` 里调用 `rebuild_daily_usage` 那一行，
    只测辅助函数的话，把那一行改回 400 测试照样全绿，等于没测喵。
    """
    # 造配置与库喵
    config = _config(tmp_path)
    db.init_db(config.server.db_path)
    connection = db.connect(config.server.db_path)
    try:
        # 造设备喵
        stamp = to_utc_text(BASE_NOW)
        connection.execute(
            "INSERT INTO devices (device_id, platform, display_name, first_seen_at, last_seen_at)"
            " VALUES (?, 'windows', '回溯机', ?, ?)",
            (DEVICE, stamp, stamp),
        )
        # 450 天前的一条明细喵
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds)"
            " VALUES (?, 'Old.exe', 'old.exe', ?, 5000)",
            (DEVICE, to_utc_text(BASE_NOW - timedelta(days=450))),
        )
        connection.commit()
    finally:
        connection.close()
    # 跑清理喵
    maintenance.prune_once(config)
    # 明细被删掉了喵
    connection = db.connect(config.server.db_path)
    try:
        assert connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"] == 0
        # 但那天的汇总必须已经固化下来，不能永久缺一块喵
        row = connection.execute(
            "SELECT local_day, seconds FROM daily_usage"
        ).fetchone()
        assert row is not None, "450 天前的明细被删了却没进汇总表"
        assert row["seconds"] == 5000
    finally:
        connection.close()


def test_oldest_usage_days_falls_back_without_detail(connection) -> None:
    """库里没有明细时给保守值，不要算出 0 天喵。"""
    # 空库喵
    assert maintenance._oldest_usage_days(connection) == maintenance.DEFAULT_USAGE_HISTORY_DAYS
