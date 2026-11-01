"""落库逻辑的单元测试，重点验证幂等性与增量语义喵。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import db, ingest
from app.models import ReportPayload
from conftest import make_payload


def _payload(**overrides) -> ReportPayload:
    """把字典转换成校验后的上报对象喵。"""
    # pydantic 会在这里完成字段校验喵
    return ReportPayload.model_validate(make_payload(**overrides))


def test_save_report_writes_device_and_samples(connection: sqlite3.Connection) -> None:
    """一次正常上报应写入设备、原始记录、电量与使用时长喵。"""
    # 构造带电量与两条使用增量的上报喵
    payload = _payload(
        device_id="and-test-0001",
        platform="android",
        battery={"percent": 76, "charging": False},
        hardware={"model": "Pixel 7", "android_version": "14"},
        usage_delta=[{"app": "微信", "seconds": 45}, {"app": "哔哩哔哩", "seconds": 15}],
    )
    # 执行落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 不应被判定为重复喵
    assert result.duplicate is False
    # 两条增量都应写入喵
    assert result.usage_rows_written == 2
    # 电量应写入喵
    assert result.battery_written is True
    # 设备表应有一行喵
    device_count = connection.execute("SELECT COUNT(*) AS c FROM devices").fetchone()["c"]
    assert device_count == 1
    # Android 的系统版本应被拼成 "Android 14" 喵
    os_version = connection.execute("SELECT os_version FROM devices").fetchone()["os_version"]
    assert os_version == "Android 14"


def test_duplicate_report_is_idempotent(connection: sqlite3.Connection) -> None:
    """同一时间点重复上报不得让使用时长翻倍喵。"""
    # 固定上报时间，保证两次上报时间点一致喵
    fixed_time = datetime.now(timezone.utc).replace(microsecond=0)
    # 第一次上报喵
    first_payload = _payload(reported_at=fixed_time.isoformat())
    ingest.save_report(connection, first_payload, datetime.now(timezone.utc))
    # 第二次用完全相同的上报内容喵
    second_payload = _payload(reported_at=fixed_time.isoformat())
    second_result = ingest.save_report(connection, second_payload, datetime.now(timezone.utc))
    # 应被识别为重复喵
    assert second_result.duplicate is True
    # 重复上报不应再写使用时长喵
    assert second_result.usage_rows_written == 0
    # 总时长应保持 60 秒而不是 120 秒喵
    total_seconds = connection.execute("SELECT SUM(seconds) AS s FROM usage_samples").fetchone()["s"]
    assert total_seconds == 60


def test_zero_second_usage_is_skipped(connection: sqlite3.Connection) -> None:
    """0 秒增量没有信息量，应被跳过喵。"""
    # 一条 0 秒、一条 30 秒喵
    payload = _payload(usage_delta=[{"app": "空闲", "seconds": 0}, {"app": "Code.exe", "seconds": 30}])
    # 落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 只应写入 1 条喵
    assert result.usage_rows_written == 1


def test_empty_hardware_does_not_wipe_previous(connection: sqlite3.Connection) -> None:
    """后续上报没带硬件信息时，不能把已有硬件信息清空喵。"""
    # 第一次带硬件信息喵
    first_time = datetime.now(timezone.utc).replace(microsecond=0)
    ingest.save_report(connection, _payload(reported_at=first_time.isoformat()), datetime.now(timezone.utc))
    # 第二次不带硬件信息喵
    second_time = first_time + timedelta(seconds=30)
    ingest.save_report(
        connection,
        _payload(reported_at=second_time.isoformat(), hardware=None),
        datetime.now(timezone.utc),
    )
    # 硬件 JSON 应仍是第一次的内容喵
    hardware_json = connection.execute("SELECT hardware_json FROM devices").fetchone()["hardware_json"]
    assert "Ryzen 7 9700X" in hardware_json


def test_older_report_does_not_rewind_last_seen(connection: sqlite3.Connection) -> None:
    """迟到的旧上报不应把最近上报时间改小喵。"""
    # 较新的上报先到喵
    newer_time = datetime.now(timezone.utc).replace(microsecond=0)
    ingest.save_report(connection, _payload(reported_at=newer_time.isoformat()), datetime.now(timezone.utc))
    # 较旧的上报后到喵
    older_time = newer_time - timedelta(minutes=5)
    ingest.save_report(connection, _payload(reported_at=older_time.isoformat()), datetime.now(timezone.utc))
    # 最近上报时间应仍等于较新的时间喵
    last_seen = connection.execute("SELECT last_seen_at FROM devices").fetchone()["last_seen_at"]
    assert last_seen == db.to_utc_text(newer_time)


def test_save_report_rolls_back_on_sql_error(app_config) -> None:
    """数据库异常时应回滚，不能留下半条记录喵。"""
    # 单独开一个连接，避免影响其它测试的夹具喵
    db.init_db(app_config.server.db_path)
    # 打开连接喵
    standalone_connection = db.connect(app_config.server.db_path)
    try:
        # 用触发器强制让上报表插入失败，模拟磁盘错误或约束冲突喵
        standalone_connection.execute(
            "CREATE TRIGGER fail_reports BEFORE INSERT ON reports BEGIN SELECT RAISE(ABORT, '模拟写入失败'); END;"
        )
        # 提交触发器定义喵
        standalone_connection.commit()
        # 构造一条正常上报喵
        payload = _payload()
        # 期望抛 sqlite3 异常喵
        with pytest.raises(sqlite3.Error):
            ingest.save_report(standalone_connection, payload, datetime.now(timezone.utc))
        # 喵~防御：异常后设备表不应留下任何记录，证明事务已回滚喵
        device_count = standalone_connection.execute("SELECT COUNT(*) AS c FROM devices").fetchone()["c"]
        assert device_count == 0
    finally:
        # 关闭连接喵
        standalone_connection.close()


def test_afk_report_still_writes_usage(connection: sqlite3.Connection) -> None:
    """AFK 那一批里带着的秒数要照常入库，否则色块和斜纹之间会留出空白喵。"""
    # 构造"刚进入 AFK 但这一批还带着使用时长"的上报喵
    payload = _payload(
        device_id="win-afk-0001",
        afk=True,
        usage_delta=[{"app": "Code.exe", "seconds": 20}],
    )
    # 落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 判定仍然是暂停（人确实离开了），但时长不能丢喵
    assert result.stats_paused is True
    assert result.stats_paused_reason == "afk"
    assert result.usage_rows_written == 1
    # 库里确实有这条采样喵
    usage_row = connection.execute("SELECT app_name, seconds FROM usage_samples").fetchone()
    assert usage_row["app_name"] == "Code.exe"
    assert usage_row["seconds"] == 20


def test_server_role_pauses_usage_without_rdp(connection: sqlite3.Connection) -> None:
    """服务器角色在 RDP 未连接时只写心跳，不写使用时长喵。"""
    # 构造服务器角色、RDP 未连接、带两条使用增量的上报喵
    payload = _payload(
        device_id="win-srv-0001",
        role="server",
        rdp_connected=False,
        usage_delta=[{"app": "Code.exe", "seconds": 60}, {"app": "chrome.exe", "seconds": 30}],
    )
    # 落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 应判定为暂停喵
    assert result.stats_paused is True
    assert result.stats_paused_reason == "rdp_disconnected"
    # 使用时长不应写入喵
    assert result.usage_rows_written == 0
    usage_count = connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"]
    assert usage_count == 0
    # 设备表应记下角色与暂停原因喵
    device_row = connection.execute("SELECT role, stats_paused_reason FROM devices").fetchone()
    assert device_row["role"] == "server"
    assert device_row["stats_paused_reason"] == "rdp_disconnected"


def test_server_role_writes_usage_with_rdp(connection: sqlite3.Connection) -> None:
    """服务器角色在 RDP 连接时正常写使用时长喵。"""
    # 构造 RDP 已连接的上报喵
    payload = _payload(
        device_id="win-srv-0001",
        role="server",
        rdp_connected=True,
        usage_delta=[{"app": "Code.exe", "seconds": 60}],
    )
    # 落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 不应暂停喵
    assert result.stats_paused is False
    assert result.usage_rows_written == 1


def test_config_role_override_forces_server(connection: sqlite3.Connection) -> None:
    """配置里的服务器列表优先级高于客户端自报喵。"""
    # 客户端自称工作站，但配置里标记为服务器喵
    payload = _payload(device_id="win-test-0001", role="workstation")
    # 用带覆盖的配置落库喵
    result = ingest.save_report(
        connection,
        payload,
        datetime.now(timezone.utc),
        settings=ingest.GatingSettings(servers=("win-test-0001",)),
    )
    # 角色应变成服务器，且因没有 RDP 状态而暂停喵
    assert result.stats_paused is True
    assert connection.execute("SELECT role FROM devices").fetchone()["role"] == "server"


def test_mirror_windows_match_android_tag(connection: sqlite3.Connection) -> None:
    """服务器上报投屏窗口时应匹配到安卓标签并落库喵。"""
    # 先让安卓设备带着标签上报一次喵
    ingest.save_report(
        connection,
        _payload(
            device_id="and-phone-0001",
            platform="android",
            tag="23113RKC6C",
            hardware={"model": "23113RKC6C", "android_version": "14"},
        ),
        datetime.now(timezone.utc),
    )
    # 服务器上报 scrcpy 窗口标题喵
    server_result = ingest.save_report(
        connection,
        _payload(
            device_id="win-srv-0001",
            role="server",
            rdp_connected=False,
            mirror_windows=["scrcpy 23113RKC6C"],
            usage_delta=[],
        ),
        datetime.now(timezone.utc),
    )
    # 应匹配到那台安卓设备喵
    assert server_result.mirrored_tags == ("23113RKC6C",)
    # 库里应存下匹配结果喵
    stored = connection.execute("SELECT mirrored_tags_json FROM devices WHERE device_id = 'win-srv-0001'").fetchone()
    assert "23113RKC6C" in stored["mirrored_tags_json"]


def test_mirrored_android_paused_when_mirror_in_background(connection: sqlite3.Connection) -> None:
    """投屏窗口在后台时，被投屏的安卓设备暂停统计喵。"""
    # 固定两个时间点，避免同一秒内两次上报被判定为重复喵
    first_time = datetime.now(timezone.utc).replace(microsecond=0)
    second_time = first_time + timedelta(seconds=30)
    # 安卓设备先上报标签喵
    ingest.save_report(
        connection,
        _payload(device_id="and-phone-0001", platform="android", tag="23113RKC6C", reported_at=first_time.isoformat()),
        datetime.now(timezone.utc),
    )
    # 服务器在投屏，但投屏窗口在后台喵
    ingest.save_report(
        connection,
        _payload(
            device_id="win-srv-0001",
            role="server",
            rdp_connected=True,
            mirror_windows=["23113RKC6C"],
            mirror_foreground=False,
            usage_delta=[],
        ),
        datetime.now(timezone.utc),
    )
    # 安卓再上报使用时长喵
    android_result = ingest.save_report(
        connection,
        _payload(
            device_id="and-phone-0001",
            platform="android",
            tag="23113RKC6C",
            reported_at=second_time.isoformat(),
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 30}],
        ),
        datetime.now(timezone.utc),
    )
    # 应暂停且不写使用时长喵
    assert android_result.stats_paused is True
    assert android_result.stats_paused_reason == "mirror_background"
    assert android_result.usage_rows_written == 0


def test_mirrored_android_enabled_when_mirror_foreground(connection: sqlite3.Connection) -> None:
    """投屏窗口在前台时，被投屏的安卓设备照常统计喵。"""
    # 固定两个时间点，避免同一秒内两次上报被判定为重复喵
    first_time = datetime.now(timezone.utc).replace(microsecond=0)
    second_time = first_time + timedelta(seconds=30)
    # 安卓设备先上报标签喵
    ingest.save_report(
        connection,
        _payload(device_id="and-phone-0001", platform="android", tag="23113RKC6C", reported_at=first_time.isoformat()),
        datetime.now(timezone.utc),
    )
    # 服务器投屏且投屏窗口在前台喵
    ingest.save_report(
        connection,
        _payload(
            device_id="win-srv-0001",
            role="server",
            rdp_connected=True,
            mirror_windows=["23113RKC6C"],
            mirror_foreground=True,
            usage_delta=[],
        ),
        datetime.now(timezone.utc),
    )
    # 安卓上报使用时长喵
    android_result = ingest.save_report(
        connection,
        _payload(
            device_id="and-phone-0001",
            platform="android",
            tag="23113RKC6C",
            reported_at=second_time.isoformat(),
            usage_delta=[{"app": "微信", "seconds": 30}],
        ),
        datetime.now(timezone.utc),
    )
    # 应正常写入喵
    assert android_result.stats_paused is False
    assert android_result.usage_rows_written == 1


def test_mirrored_android_paused_when_mirror_foreground_but_host_rdp_off(connection: sqlite3.Connection) -> None:
    """宿主 RDP 没连时，投屏窗口在前台也要暂停手机统计喵。"""
    # 固定两个时间点，避免同一秒内两次上报被判定为重复喵
    first_time = datetime.now(timezone.utc).replace(microsecond=0)
    second_time = first_time + timedelta(seconds=30)
    # 安卓设备先上报标签喵
    ingest.save_report(
        connection,
        _payload(device_id="and-phone-0001", platform="android", tag="23113RKC6C", reported_at=first_time.isoformat()),
        datetime.now(timezone.utc),
    )
    # 喵~注意：服务器投屏窗口在前台，但 RDP 已经断开，人其实操作不了手机喵
    ingest.save_report(
        connection,
        _payload(
            device_id="win-srv-0001",
            role="server",
            rdp_connected=False,
            mirror_windows=["23113RKC6C"],
            mirror_foreground=True,
            usage_delta=[],
        ),
        datetime.now(timezone.utc),
    )
    # 安卓上报使用时长喵
    android_result = ingest.save_report(
        connection,
        _payload(
            device_id="and-phone-0001",
            platform="android",
            tag="23113RKC6C",
            reported_at=second_time.isoformat(),
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 30}],
        ),
        datetime.now(timezone.utc),
    )
    # 应暂停且不写使用时长，原因是 RDP 断开而不是投屏在后台喵
    assert android_result.stats_paused is True
    assert android_result.stats_paused_reason == "mirror_rdp_disconnected"
    assert android_result.usage_rows_written == 0


def test_android_not_mirrored_keeps_usage(connection: sqlite3.Connection) -> None:
    """没被投屏的安卓设备照常统计（人直接在用手机）喵。"""
    # 服务器投屏的是另一台设备喵
    ingest.save_report(
        connection,
        _payload(device_id="win-srv-0001", role="server", rdp_connected=False, mirror_windows=["别的手机"], usage_delta=[]),
        datetime.now(timezone.utc),
    )
    # 本机带标签但没被投屏喵
    result = ingest.save_report(
        connection,
        _payload(device_id="and-phone-0002", platform="android", tag="我的手机", usage_delta=[{"app": "微信", "seconds": 20}]),
        datetime.now(timezone.utc),
    )
    # 应正常写入喵
    assert result.stats_paused is False
    assert result.usage_rows_written == 1


def test_usage_package_is_stored(connection: sqlite3.Connection) -> None:
    """使用时长应带上包名，供看板区分同名应用喵。"""
    # 带包名的上报喵
    ingest.save_report(
        connection,
        _payload(usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 42}]),
        datetime.now(timezone.utc),
    )
    # 库里应存下包名喵
    row = connection.execute("SELECT app_name, package, seconds FROM usage_samples").fetchone()
    assert row["app_name"] == "微信"
    assert row["package"] == "com.tencent.mm"
    assert row["seconds"] == 42

def test_usage_ended_at_anchors_sample(connection: sqlite3.Connection) -> None:
    """客户端给了 usage_ended_at 时，采样时间点按它落位，而不是按上报时刻喵。"""
    # 上报时刻比"最后一秒"晚了 40 秒，模拟循环卡顿喵
    received_at = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    ended_at = received_at - timedelta(seconds=40)
    payload = _payload(
        device_id="win-anchor-0001",
        reported_at=ended_at.isoformat(),
        usage_ended_at=ended_at.isoformat(),
        usage_delta=[{"app": "Code.exe", "seconds": 65}],
    )
    # 落库喵
    ingest.save_report(connection, payload, received_at)
    # 采样时间点必须是 ended_at，否则色块会整体后移并留出空白喵
    sampled_at = connection.execute("SELECT sampled_at FROM usage_samples").fetchone()["sampled_at"]
    assert sampled_at.startswith("2026-10-31T12:00:00") is False
    assert sampled_at.startswith("2026-10-31T11:59:20")


def test_usage_ended_at_too_old_falls_back(connection: sqlite3.Connection) -> None:
    """锚点比上报早了一小时以上时认为时钟不可信，退回上报时刻喵。"""
    # 锚点比接收时间早两小时喵
    received_at = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    payload = _payload(
        device_id="win-anchor-0002",
        usage_ended_at=(received_at - timedelta(hours=2)).isoformat(),
        usage_delta=[{"app": "Code.exe", "seconds": 65}],
    )
    # 落库喵
    ingest.save_report(connection, payload, received_at)
    # 采样时间点退回接收时间喵
    sampled_at = connection.execute("SELECT sampled_at FROM usage_samples").fetchone()["sampled_at"]
    assert sampled_at.startswith("2026-10-31T12:00:00")


def test_foreground_missing_seconds_accepted(connection: sqlite3.Connection) -> None:
    """抓不到前台的秒数是观测字段，正常落库且不影响写入喵。"""
    # 带上观测字段的上报喵
    payload = _payload(
        device_id="win-anchor-0003",
        foreground_missing_seconds=17,
        usage_delta=[{"app": "Code.exe", "seconds": 10}],
    )
    # 落库喵
    result = ingest.save_report(connection, payload, datetime.now(timezone.utc))
    # 使用时长照常写入喵
    assert result.usage_rows_written == 1
