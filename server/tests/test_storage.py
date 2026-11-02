"""存储统计与清理的单元测试喵。"""

from __future__ import annotations

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
