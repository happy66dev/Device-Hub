"""存储统计与清理的单元测试喵。"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from app import db, storage
from app.db import to_utc_text, utc_now


@pytest.fixture()
def connection(tmp_path: Path):
    """建一个临时库喵。"""
    # 初始化表结构喵
    db_path = tmp_path / "storage.db"
    db.init_db(db_path)
    # 打开连接喵
    conn = db.connect(db_path)
    yield conn
    # 收尾喵
    conn.close()


def _insert_usage(connection, device_id: str, sampled_at: str, seconds: int = 60) -> None:
    """插一条使用记录，测试用喵。"""
    # 先插设备喵
    connection.execute(
        """
        INSERT OR IGNORE INTO devices (device_id, platform, display_name, os_version, first_seen_at, last_seen_at)
        VALUES (?, 'windows', '测试机', 'Windows', ?, ?)
        """,
        (device_id, sampled_at, sampled_at),
    )
    # 再插使用记录喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, 'Code', 'code.exe', ?, ?)",
        (device_id, sampled_at, seconds),
    )
    # 提交喵
    connection.commit()


def test_collect_stats_counts_rows(connection, tmp_path: Path) -> None:
    """统计要能数出行数并给出时间范围喵。"""
    # 插两条记录喵
    _insert_usage(connection, "win-1", "2026-10-01T00:00:00Z")
    _insert_usage(connection, "win-1", "2026-10-02T00:00:00Z")
    # 统计喵
    stats = storage.collect_stats(connection, tmp_path / "storage.db")
    # 找到使用表喵
    usage = next(item for item in stats["tables"] if item["name"] == "usage_samples")
    assert usage["rows"] == 2
    assert usage["oldest"] == "2026-10-01T00:00:00Z"
    assert usage["newest"] == "2026-10-02T00:00:00Z"
    # 总行数应当大于 0 喵
    assert stats["total_rows"] >= 2


def test_parse_cleanup_request_defaults(connection) -> None:
    """不传参数时默认保留 30 天并清全部表喵。"""
    days, targets = storage.parse_cleanup_request({})
    assert days == 30
    assert set(targets) == set(storage.CLEANABLE_TABLES)


def test_parse_cleanup_request_rejects_zero_days() -> None:
    """0 天会把今天的数据删掉，必须拒绝喵。"""
    with pytest.raises(storage.StorageError):
        storage.parse_cleanup_request({"before_days": 0})


def test_parse_cleanup_request_rejects_unknown_table() -> None:
    """不认识的表名要拒绝喵。"""
    with pytest.raises(storage.StorageError):
        storage.parse_cleanup_request({"targets": ["devices"]})


def test_parse_cleanup_request_rejects_empty_targets() -> None:
    """空数组要拒绝，避免"点了没反应"喵。"""
    with pytest.raises(storage.StorageError):
        storage.parse_cleanup_request({"targets": []})


def test_cleanup_removes_only_old_rows(connection) -> None:
    """只删阈值之前的数据，最近的数据必须留着喵。"""
    # 一条很老的、一条刚刚的喵
    old = to_utc_text(utc_now() - timedelta(days=60))
    fresh = to_utc_text(utc_now() - timedelta(hours=1))
    _insert_usage(connection, "win-1", old)
    _insert_usage(connection, "win-1", fresh)
    # 清 30 天前喵
    deleted = storage.cleanup(connection, 30, ("usage_samples",))
    assert deleted["usage_samples"] == 1
    # 剩下的应当是最新那条喵
    remaining = connection.execute("SELECT sampled_at FROM usage_samples").fetchall()
    assert [row["sampled_at"] for row in remaining] == [fresh]


def test_cleanup_keeps_everything_when_threshold_is_before_data(connection) -> None:
    """数据都在阈值之后时不该删任何东西喵。"""
    # 只插一条新数据喵
    _insert_usage(connection, "win-1", to_utc_text(utc_now()))
    deleted = storage.cleanup(connection, 365, ("usage_samples",))
    assert deleted["usage_samples"] == 0


def test_format_bytes_scales_units() -> None:
    """字节格式化要按 KB/MB 走喵。"""
    assert storage.format_bytes(0) == "0 B"
    assert storage.format_bytes(1536) == "1.5 KB"
    assert storage.format_bytes(1024 * 1024 * 3) == "3.0 MB"


def test_indexes_drop_redundant_duplicates(connection) -> None:
    """建库后不该再有与 UNIQUE 自动索引重复的手工索引喵。"""
    # 列出所有显式建的索引喵
    names = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    # 喵~注意：这两张表本身就有 UNIQUE(device_id, 时间)，自动索引已经覆盖，
    # 手工再建一份纯属浪费空间还拖慢插入喵
    assert "idx_reports_device_time" not in names
    assert "idx_battery_device_time" not in names
    # 原有的其它索引不能误删喵
    assert "idx_usage_device_time" in names
    assert "idx_window_device_time" in names


def test_redundant_indexes_are_dropped_on_upgrade(tmp_path: Path) -> None:
    """老库升级时已存在的冗余索引要被删掉喵。"""
    # 造一个库喵
    db_path = tmp_path / "upgrade.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        # 手工把旧索引建回去，模拟老版本遗留喵
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_device_time ON reports (device_id, reported_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_battery_device_time ON battery_samples (device_id, sampled_at)")
        conn.commit()
        # 确认建上了喵
        before = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_reports_device_time" in before
        # 再跑一次初始化，模拟启动时的迁移喵
        db.init_db(db_path)
        # 喵~防御：老库不能一直留着冗余索引喵
        after = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_reports_device_time" not in after
        assert "idx_battery_device_time" not in after
    finally:
        conn.close()


def _insert_report(connection, device_id: str, moment: str) -> None:
    """插一条上报记录，测试用喵。"""
    # 先插设备喵
    connection.execute(
        """
        INSERT OR IGNORE INTO devices (device_id, platform, display_name, os_version, first_seen_at, last_seen_at)
        VALUES (?, 'windows', '测试机', 'Windows', ?, ?)
        """,
        (device_id, moment, moment),
    )
    # 再插上报喵
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
        (device_id, moment, moment, b'{"afk": false}'),
    )
    connection.commit()


def _insert_window(connection, device_id: str, moment: str) -> None:
    """插一条窗口快照，测试用喵。"""
    # 设备已由上一步插好喵
    connection.execute(
        "INSERT INTO window_samples (device_id, app_name, package, title, minimized, foreground, reported_at)"
        " VALUES (?, 'Code', 'code.exe', 'app.js', 0, 1, ?)",
        (device_id, moment),
    )
    connection.commit()


def test_cleanup_reports_goes_through_archive(connection) -> None:
    """清上报记录时必须先归档再删，不能硬删喵。

    喵~注意：这是重构的核心保证。以前 `storage.cleanup` 直接 DELETE，
    用户点一下设置页的清理，明细就永久没了——归档还没来得及压，
    时间轴的历史跟着消失，而且不可恢复喵。
    """
    # 造一条整月都已过期的数据喵
    old = "2026-09-15T10:00:00Z"
    _insert_report(connection, "win-1", old)
    # 清 1 天前（这条远早于阈值）喵
    deleted = storage.cleanup(connection, 1, ("reports",))
    # 原始行删掉了喵
    assert deleted["reports"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0
    # 但归档里有一份，数据没丢喵
    row = connection.execute("SELECT kind, month, row_count FROM archives").fetchone()
    assert row is not None
    assert row["kind"] == "heartbeats"
    assert row["month"] == "2026-09"
    assert row["row_count"] == 1


def test_cleanup_windows_goes_through_archive(connection) -> None:
    """窗口快照同样要先归档再删喵。"""
    # 造一条过期的窗口喵
    old = "2026-09-15T10:00:00Z"
    _insert_report(connection, "win-1", old)
    _insert_window(connection, "win-1", old)
    # 清窗口喵
    deleted = storage.cleanup(connection, 1, ("window_samples",))
    assert deleted["window_samples"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 0
    # 归档里要有 windows 块喵
    # 喵~注意：归档会同时处理 reports 和 window_samples，
    # 所以必须按 kind 过滤，不能直接取第一行喵
    row = connection.execute(
        "SELECT month, row_count FROM archives WHERE kind = 'windows'"
    ).fetchone()
    assert row is not None
    assert row["row_count"] == 1


def test_cleanup_keeps_current_month_rows(connection) -> None:
    """当月数据不归档也不删，即使它比阈值早喵。

    喵~注意：归档只压「整月都过了热保留期」的月份。
    这个月的最后一天还没过，所以一块都不会生成，
    那些行也就不该被删——否则会开出「月份没压完就删了」的口子喵。
    """
    # 造一条本月很早、但仍在当月的上报喵
    now = utc_now()
    moment = to_utc_text(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    _insert_report(connection, "win-1", moment)
    # 即使清 0 天，也只清已归档的，本月行要留着喵
    deleted = storage.cleanup(connection, 1, ("reports",))
    assert deleted["reports"] == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1
    # 也不该生成任何块喵
    assert connection.execute("SELECT COUNT(*) AS c FROM archives").fetchone()["c"] == 0


def test_cleanup_usage_backfills_daily_usage(connection) -> None:
    """删使用时长前要先固化每日汇总，否则长程热力图会缺天喵。"""
    # 造一条 60 天前的使用时长喵
    old = to_utc_text(utc_now() - timedelta(days=60))
    _insert_usage(connection, "win-1", old, 900)
    # 清 30 天前喵
    deleted = storage.cleanup(connection, 30, ("usage_samples",))
    assert deleted["usage_samples"] == 1
    # 明细没了喵
    assert connection.execute("SELECT COUNT(*) AS c FROM usage_samples").fetchone()["c"] == 0
    # 但日汇总里那天的秒数还在喵
    row = connection.execute("SELECT seconds FROM daily_usage").fetchone()
    assert row is not None
    assert row["seconds"] == 900


def test_cleanup_threshold_uses_received_at_for_reports(connection) -> None:
    """上报记录的阈值按 received_at 算，和归档保持一致喵。

    喵~注意：`reports` 有 reported_at（客户端）和 received_at（服务端）两列。
    归档和查询都用 received_at，清理如果按 reported_at 删，
    客户端时钟一偏就会删掉不该删的行喵。
    """
    # 造一条：客户端时间很旧、服务端时间很新喵
    fresh = to_utc_text(utc_now() - timedelta(hours=1))
    old_client = to_utc_text(utc_now() - timedelta(days=90))
    connection.execute(
        """
        INSERT OR IGNORE INTO devices (device_id, platform, display_name, os_version, first_seen_at, last_seen_at)
        VALUES ('win-1', 'windows', '测试机', 'Windows', ?, ?)
        """,
        (fresh, fresh),
    )
    connection.execute(
        "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES ('win-1', ?, ?, ?)",
        (old_client, fresh, b'{"afk": false}'),
    )
    connection.commit()
    # 清 30 天前：按 received_at 算这条是新的，必须留着喵
    deleted = storage.cleanup(connection, 30, ("reports",))
    assert deleted["reports"] == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1


def test_cleanup_counts_each_table_separately(connection) -> None:
    """同时清两张明细表时，各自的删除行数要算准喵。

    喵~注意：归档一次会把 `reports` 和 `window_samples` 一起处理。
    如果按「归档后数一遍」来算，后处理的那张表会显示 0 行——
    它的数据早就被上一张表触发归档时删掉了。
    所以必须在归档前把两张表的行数都记下来，事后各算差值喵。
    """
    # 造两条月份不同、都已过期的数据喵
    for month in ("2026-08", "2026-09"):
        moment = f"{month}-15T10:00:00Z"
        _insert_report(connection, "win-1", moment)
    _insert_window(connection, "win-1", "2026-08-15T10:00:00Z")
    _insert_window(connection, "win-1", "2026-09-15T10:00:00Z")
    # 两张表一起清喵
    deleted = storage.cleanup(connection, 1, ("reports", "window_samples"))
    # 各自的行数都要对得上，不能有一个是 0 喵
    assert deleted["reports"] == 2
    assert deleted["window_samples"] == 2
    # 归档里两种块都在喵
    kinds = {row["kind"] for row in connection.execute("SELECT DISTINCT kind FROM archives")}
    assert kinds == {"heartbeats", "windows"}


def test_cleanup_respects_before_days_for_archivable_tables(connection) -> None:
    """保留天数对明细表同样生效，不能因为走归档就无视它喵。

    喵~注意：这条是一个真实 bug 的回归测试。重构时把归档的 hot_days
    写死成 0，结果无论用户选「保留 1 天」还是「保留 365 天」，
    上个月的数据都会被压掉——清理的保留期参数等于摆设喵。
    """
    # 造一条上个月的数据（整月已过完，够老但没老到 365 天）喵
    old = to_utc_text(utc_now() - timedelta(days=40))
    _insert_report(connection, "win-1", old)
    # 保留 365 天：这条远在保留期内，一行都不能动喵
    deleted = storage.cleanup(connection, 365, ("reports",))
    assert deleted["reports"] == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1
    # 也不该生成归档块——还没到该压缩的时候喵
    assert connection.execute("SELECT COUNT(*) AS c FROM archives").fetchone()["c"] == 0


def test_cleanup_only_touches_selected_tables(connection) -> None:
    """只勾选一张明细表时，另一张一行都不能动喵。

    喵~注意：这是真实 bug 的回归测试。归档内部一次处理两张明细表，
    而 `cleanup` 原来不看 `targets` 就调它，于是「只勾原始上报」
    会连窗口快照一起清掉——用户没勾的表被删了，返回的 `deleted` 里也没有它，
    属于静默丢数据喵。
    """
    # 两张明细表都造一条够老的数据喵
    old = to_utc_text(utc_now() - timedelta(days=60))
    _insert_report(connection, "win-1", old)
    _insert_window(connection, "win-1", old)
    # 只勾原始上报喵
    deleted = storage.cleanup(connection, 30, ("reports",))
    # 原始上报被清掉喵
    assert deleted["reports"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0
    # 窗口快照必须原封不动喵
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 1
    # 只该生成心跳块，不该顺手把窗口也压掉喵
    kinds = {row["kind"] for row in connection.execute("SELECT DISTINCT kind FROM archives")}
    assert kinds == {"heartbeats"}


def test_cleanup_selected_windows_leaves_reports_alone(connection) -> None:
    """反过来只勾窗口快照时，原始上报也必须留着喵。"""
    # 两张明细表各一条老数据喵
    old = to_utc_text(utc_now() - timedelta(days=60))
    _insert_report(connection, "win-1", old)
    _insert_window(connection, "win-1", old)
    # 只勾窗口快照喵
    deleted = storage.cleanup(connection, 30, ("window_samples",))
    # 窗口被清掉、原始上报留着喵
    assert deleted["window_samples"] == 1
    assert connection.execute("SELECT COUNT(*) AS c FROM window_samples").fetchone()["c"] == 0
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 1
    # 只该生成窗口块喵
    kinds = {row["kind"] for row in connection.execute("SELECT DISTINCT kind FROM archives")}
    assert kinds == {"windows"}


def test_cleanup_survives_vacuum_lock(connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """VACUUM 撞上并发写入时，清理不能报失败喵。

    喵~注意：这是真实缺陷。`VACUUM` 在删除**已经 commit 之后**才执行，
    撞锁抛 `database is locked` 时异常会一路冒到接口层 → 前端弹「清理失败」，
    但数据其实早就删掉了，用户根本分不清到底成没成。
    现在改成重试 + 静默降级：删掉就是删掉，只是没回收成磁盘喵。
    """
    # 造一条老数据喵
    old = to_utc_text(utc_now() - timedelta(days=60))
    _insert_report(connection, "win-1", old)
    connection.commit()
    # 让 VACUUM 每次都撞锁喵
    calls = {"count": 0}

    class _LockedVacuum:
        """包一层连接，只把 VACUUM 变成撞锁喵。

        喵~注意：`sqlite3.Connection.execute` 是只读属性，
        `monkeypatch.setattr(connection, "execute", ...)` 会报
        "'sqlite3.Connection' object attribute 'execute' is read-only"，
        所以只能包一个替身对象喵。
        """

        def __init__(self, inner):
            """记住真连接喵。"""
            self._inner = inner

        def execute(self, sql, *args, **kwargs):
            """VACUUM 抛锁异常，其余转发喵。"""
            if isinstance(sql, str) and sql.strip().upper() == "VACUUM":
                calls["count"] += 1
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *args, **kwargs)

        def commit(self):
            """转发提交喵。"""
            return self._inner.commit()

    # 清理必须正常返回，不能抛喵
    deleted = storage.cleanup(_LockedVacuum(connection), 30, ("reports",))
    # 数据确实删掉了喵
    assert deleted["reports"] == 1
    # 而且重试了三次才放弃喵
    assert calls["count"] == 3
    # 数据仍然是删掉的状态，说明删除确实已提交、没被回滚喵
    assert connection.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"] == 0
