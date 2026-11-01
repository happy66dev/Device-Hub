"""运行时黑名单的测试：存储、校验、拦截与接口喵。

喵~注意：黑名单是「配置 + 运行中」的并集，配置里的删不掉，
运行中的改完立刻生效且不用重启——这几条行为都要钉死喵。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import acl, people
from app.bot import router
from app.config import AppConfig
from conftest import TEST_INGEST_TOKEN, make_payload

# 统一的请求头喵
AUTH_HEADERS = {"X-Ingest-Token": TEST_INGEST_TOKEN}

# 测试用的黑名单用户喵
BLOCKED_USER = 222222


def _clear_cache() -> None:
    """清掉模块级缓存，避免用例之间互相污染喵。"""
    # 喵~注意：缓存以绝对路径为键，测试用的是临时目录，但仍要清干净喵
    acl._CACHE.clear()


def test_acl_file_lives_next_to_database(app_config: AppConfig) -> None:
    """名单文件应与数据库同目录，备份时一起带走喵。"""
    # 数据库在临时目录里喵
    path = acl.acl_path(app_config.server.db_path)
    assert path.parent == app_config.server.db_path.parent
    assert path.name == "acl.json"


def test_load_blocklist_missing_file_returns_empty(app_config: AppConfig) -> None:
    """文件不存在时返回空列表，不能报错喵。"""
    _clear_cache()
    assert acl.load_blocklist(app_config.server.db_path) == []


def test_load_blocklist_ignores_broken_file(app_config: AppConfig) -> None:
    """文件损坏时按空处理，别让看板打不开喵。"""
    _clear_cache()
    # 写一段坏 JSON 喵
    acl.acl_path(app_config.server.db_path).write_text("{ 不是合法 json", encoding="utf-8")
    assert acl.load_blocklist(app_config.server.db_path) == []


def test_add_and_remove_roundtrip(app_config: AppConfig) -> None:
    """新增后能读到，删除后消失喵。"""
    _clear_cache()
    db_path = app_config.server.db_path
    # 新增一条喵
    assert acl.add_entry(db_path, "napcat", "123456", "刷屏") is True
    entries = acl.load_blocklist(db_path)
    assert len(entries) == 1
    assert entries[0].target == "123456"
    assert entries[0].note == "刷屏"
    # 拉黑时刻自动补上喵
    assert entries[0].created_at.endswith("Z")
    # 删除喵
    assert acl.remove_entry(db_path, "napcat", "123456") is True
    assert acl.load_blocklist(db_path) == []


def test_add_duplicate_returns_false(app_config: AppConfig) -> None:
    """同一个通道下拉黑同一个人两次，第二次不新增喵。"""
    _clear_cache()
    db_path = app_config.server.db_path
    assert acl.add_entry(db_path, "napcat", "123456") is True
    assert acl.add_entry(db_path, "napcat", "123456") is False
    # 名单里仍然只有一条喵
    assert len(acl.load_blocklist(db_path)) == 1


def test_same_target_different_channel_are_separate(app_config: AppConfig) -> None:
    """同一串标识出现在两个通道时算两条独立记录喵。"""
    _clear_cache()
    db_path = app_config.server.db_path
    assert acl.add_entry(db_path, "napcat", "999") is True
    assert acl.add_entry(db_path, "qqbot", "999") is True
    assert len(acl.load_blocklist(db_path)) == 2
    # 只删 NapCat 那条喵
    assert acl.remove_entry(db_path, "napcat", "999") is True
    remaining = acl.load_blocklist(db_path)
    assert [entry.channel for entry in remaining] == ["qqbot"]


def test_remove_missing_returns_false(app_config: AppConfig) -> None:
    """删一个不存在的人应返回 False，而不是报错喵。"""
    _clear_cache()
    assert acl.remove_entry(app_config.server.db_path, "napcat", "000") is False


def test_add_rejects_blank_target(app_config: AppConfig) -> None:
    """标识为空时必须拒绝喵。"""
    _clear_cache()
    with pytest.raises(acl.AclError):
        acl.add_entry(app_config.server.db_path, "napcat", "   ")


def test_add_rejects_unknown_channel(app_config: AppConfig) -> None:
    """通道名写错必须拒绝，别静默存成一条永远不生效的记录喵。"""
    _clear_cache()
    with pytest.raises(acl.AclError):
        acl.add_entry(app_config.server.db_path, "telegram", "123")


def test_parse_dedupes_same_channel_target(app_config: AppConfig) -> None:
    """解析时同通道重复项只保留第一条喵。"""
    entries = acl.parse_blocklist(
        [
            {"channel": "napcat", "target": "111", "note": "第一"},
            {"channel": "napcat", "target": "111", "note": "第二"},
            {"channel": "napcat", "target": "222"},
        ]
    )
    assert [entry.target for entry in entries] == ["111", "222"]
    # 保留的是第一条的备注喵
    assert entries[0].note == "第一"


def test_parse_rejects_too_many_entries() -> None:
    """条数超上限直接拒绝喵。"""
    raw = [{"channel": "napcat", "target": str(index)} for index in range(acl.MAX_ENTRIES + 1)]
    with pytest.raises(acl.AclError):
        acl.parse_blocklist(raw)


def test_parse_truncates_long_note() -> None:
    """备注超长时截断，不能把界面撑爆喵。"""
    entries = acl.parse_blocklist([{"channel": "napcat", "target": "1", "note": "喵" * 200}])
    assert len(entries[0].note) == acl.MAX_NOTE_LENGTH


def test_saved_file_is_readable_json(app_config: AppConfig) -> None:
    """落盘格式要稳定，方便主人手工检查与备份喵。"""
    _clear_cache()
    acl.add_entry(app_config.server.db_path, "napcat", "123", "备注")
    raw = json.loads(acl.acl_path(app_config.server.db_path).read_text(encoding="utf-8"))
    assert raw["entries"][0]["channel"] == "napcat"
    assert raw["entries"][0]["target"] == "123"


def test_effective_blacklist_merges_config_and_runtime(app_config: AppConfig) -> None:
    """配置里写死的和 WebUI 加的都要生效喵。"""
    _clear_cache()
    # 配置里已经有 222222 喵
    assert str(BLOCKED_USER) in acl.effective_blacklist(app_config, "napcat")
    # 再加一个运行中的喵
    acl.add_entry(app_config.server.db_path, "napcat", "333333")
    merged = acl.effective_blacklist(app_config, "napcat")
    assert str(BLOCKED_USER) in merged
    assert "333333" in merged


def test_effective_blacklist_keeps_channels_apart(app_config: AppConfig) -> None:
    """NapCat 的名单不能漏到官方通道去喵。"""
    _clear_cache()
    acl.add_entry(app_config.server.db_path, "napcat", "444444")
    # 官方通道只认 openid 名单，看不到 NapCat 那条喵
    assert "444444" not in acl.effective_blacklist(app_config, "qqbot")


def test_cached_blocklist_reloads_after_change(app_config: AppConfig) -> None:
    """改完之后缓存必须失效，否则拉黑不生效喵。"""
    _clear_cache()
    db_path = app_config.server.db_path
    # 先读一次建立缓存喵
    acl.cached_blocklist(db_path)
    # 新增一条喵
    acl.add_entry(db_path, "napcat", "555555")
    # 喵~注意：这里有 mtime 精度问题，直接把 mtime 往前推一点确保变化喵
    path = acl.acl_path(db_path)
    stat = path.stat()
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    napcat_targets, _ = acl.cached_blocklist(db_path)
    assert "555555" in napcat_targets


def test_router_blocks_runtime_blacklisted_user(connection: sqlite3.Connection, app_config: AppConfig) -> None:
    """运行中拉黑的人，下一条消息就该被拦下，不用重启喵。"""
    _clear_cache()
    from app.bot.channel import NormalizedMessage

    # 构造一条来自陌生人的群消息喵
    message = NormalizedMessage(
        channel="napcat",
        group_key="111111",
        user_key="777777",
        text="/happy帮助",
        mentioned=True,
        scope="group",
    )
    # 一开始能响应喵
    assert router.inspect_normalized(message, app_config)[0] is True
    # 拉黑后立刻被拦喵
    acl.add_entry(app_config.server.db_path, "napcat", "777777")
    handled, _, reason = router.inspect_normalized(message, app_config)
    assert handled is False
    assert reason == "user_blacklisted"


# ==================== HTTP 接口 ====================


def test_api_lists_runtime_and_config_entries(client: TestClient, app_config: AppConfig) -> None:
    """列表接口要同时给出运行中与配置里的条目，并标明来源喵。"""
    _clear_cache()
    acl.add_entry(app_config.server.db_path, "napcat", "888888", "测试")
    response = client.get("/api/v1/acl/blocklist", headers=AUTH_HEADERS)
    assert response.status_code == 200
    entries = response.json()["entries"]
    # 运行中的那条喵
    runtime = [entry for entry in entries if entry["source"] == "runtime"]
    assert [entry["target"] for entry in runtime] == ["888888"]
    # 配置里的那条（conftest 里 blacklist_users=(222222,)）喵
    config_entries = [entry for entry in entries if entry["source"] == "config"]
    assert "222222" in [entry["target"] for entry in config_entries]


def test_api_add_and_delete(client: TestClient, app_config: AppConfig) -> None:
    """拉黑与解除走接口全程生效喵。"""
    _clear_cache()
    # 新增喵
    response = client.post(
        "/api/v1/acl/blocklist",
        headers=AUTH_HEADERS,
        json={"channel": "napcat", "target": "121212", "note": "刷屏"},
    )
    assert response.status_code == 200
    assert response.json()["added"] is True
    # 重复新增喵
    again = client.post(
        "/api/v1/acl/blocklist",
        headers=AUTH_HEADERS,
        json={"channel": "napcat", "target": "121212"},
    )
    assert again.json()["added"] is False
    # 删除喵
    removed = client.delete("/api/v1/acl/blocklist/napcat/121212", headers=AUTH_HEADERS)
    assert removed.status_code == 200
    assert removed.json()["removed"] is True
    # 再删一次就没了喵
    twice = client.delete("/api/v1/acl/blocklist/napcat/121212", headers=AUTH_HEADERS)
    assert twice.json()["removed"] is False


def test_api_add_rejects_blank_target(client: TestClient) -> None:
    """空标识应返回 422 而不是写进去喵。"""
    _clear_cache()
    response = client.post(
        "/api/v1/acl/blocklist",
        headers=AUTH_HEADERS,
        json={"channel": "napcat", "target": "   "},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_payload"


def test_api_add_rejects_bad_channel(client: TestClient) -> None:
    """通道写错应返回 422 喵。"""
    _clear_cache()
    response = client.post(
        "/api/v1/acl/blocklist",
        headers=AUTH_HEADERS,
        json={"channel": "telegram", "target": "123"},
    )
    assert response.status_code == 422


def test_api_delete_rejects_bad_channel(client: TestClient) -> None:
    """删除时通道写错也要拒绝喵。"""
    _clear_cache()
    response = client.delete("/api/v1/acl/blocklist/telegram/123", headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_api_requires_token(client: TestClient) -> None:
    """三个接口都必须带口令喵。"""
    _clear_cache()
    assert client.get("/api/v1/acl/blocklist").status_code == 401
    assert client.post("/api/v1/acl/blocklist", json={"target": "1"}).status_code == 401
    assert client.delete("/api/v1/acl/blocklist/napcat/1").status_code == 401


def test_blocked_user_report_still_accepted(client: TestClient, app_config: AppConfig) -> None:
    """拉黑只影响机器人响应，不能把设备上报也挡掉喵。"""
    _clear_cache()
    # 拉黑一个 QQ 号喵
    acl.add_entry(app_config.server.db_path, "napcat", "131313")
    # 上报接口与 QQ 号无关，照常 200 喵
    response = client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    assert response.status_code == 200
