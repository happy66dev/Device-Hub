"""最近发言记录的测试：写入、去重、昵称兜底与接口喵。

喵~注意：这张表的作用是「让人能在看板里认出该拉黑谁」，
所以昵称能不能拿到、拿不到时显示什么，都要钉死喵。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db
from app.bot import users
from app.config import AppConfig
from conftest import TEST_INGEST_TOKEN

# 统一请求头喵
AUTH_HEADERS = {"X-Ingest-Token": TEST_INGEST_TOKEN}

# 固定基准时间喵
BASE_NOW = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)


def test_record_seen_inserts_row(connection: sqlite3.Connection) -> None:
    """第一次出现应插入一行，计数为 1 喵。"""
    users.record_seen(
        connection, "napcat", "123456",
        display_name="小明", group_key="111", now=BASE_NOW,
    )
    rows = users.list_seen_users(connection)
    assert len(rows) == 1
    assert rows[0].user_key == "123456"
    assert rows[0].display_name == "小明"
    assert rows[0].command_count == 1


def test_record_seen_increments_count(connection: sqlite3.Connection) -> None:
    """同一个人再来一次只累加计数，不会新增行喵。"""
    for offset in range(3):
        users.record_seen(
            connection, "napcat", "123456", now=BASE_NOW + timedelta(minutes=offset)
        )
    rows = users.list_seen_users(connection)
    assert len(rows) == 1
    assert rows[0].command_count == 3
    # 最后活跃时间跟着更新喵
    assert rows[0].last_seen_at == db.to_utc_text(BASE_NOW + timedelta(minutes=2))


def test_record_seen_keeps_old_name_when_new_is_blank(connection: sqlite3.Connection) -> None:
    """后一次拿不到昵称时不能把之前记下的名字冲掉喵。"""
    users.record_seen(connection, "napcat", "123", display_name="小明", now=BASE_NOW)
    # 第二次没带昵称喵
    users.record_seen(connection, "napcat", "123", display_name="", now=BASE_NOW)
    rows = users.list_seen_users(connection)
    assert rows[0].display_name == "小明"


def test_record_seen_updates_name_when_provided(connection: sqlite3.Connection) -> None:
    """昵称变了要跟着更新，群里改名能反映出来喵。"""
    users.record_seen(connection, "napcat", "123", display_name="小明", now=BASE_NOW)
    users.record_seen(connection, "napcat", "123", display_name="小明改", now=BASE_NOW)
    assert users.list_seen_users(connection)[0].display_name == "小明改"


def test_record_seen_ignores_blank_key(connection: sqlite3.Connection) -> None:
    """标识为空时不写库，避免污染名单喵。"""
    users.record_seen(connection, "napcat", "", now=BASE_NOW)
    assert users.list_seen_users(connection) == []


def test_channels_are_separate_rows(connection: sqlite3.Connection) -> None:
    """同一串标识出现在两个通道时是两个人喵。"""
    users.record_seen(connection, "napcat", "999", now=BASE_NOW)
    users.record_seen(connection, "qqbot", "999", now=BASE_NOW)
    assert len(users.list_seen_users(connection)) == 2


def test_list_orders_by_last_seen_desc(connection: sqlite3.Connection) -> None:
    """最近活跃的排最前面喵。"""
    users.record_seen(connection, "napcat", "old", now=BASE_NOW - timedelta(hours=2))
    users.record_seen(connection, "napcat", "new", now=BASE_NOW)
    rows = users.list_seen_users(connection)
    assert [row.user_key for row in rows] == ["new", "old"]


def test_list_respects_limit(connection: sqlite3.Connection) -> None:
    """limit 生效，且 0 或负数返回空喵。"""
    for index in range(5):
        users.record_seen(
            connection, "napcat", str(index), now=BASE_NOW + timedelta(seconds=index)
        )
    assert len(users.list_seen_users(connection, limit=3)) == 3
    assert users.list_seen_users(connection, limit=0) == []


def test_display_label_falls_back_to_prefix(connection: sqlite3.Connection) -> None:
    """没有昵称时用标识前缀，长 openid 要截断加省略号喵。"""
    long_key = "A" * 32
    users.record_seen(connection, "qqbot", long_key, now=BASE_NOW)
    user = users.list_seen_users(connection)[0]
    # 喵~注意：官方通道没有昵称，只能给前 8 位加省略号喵
    assert users.display_label(user) == "AAAAAAAA…"
    # 短标识不加省略号喵
    short = users.SeenUser(
        channel="napcat", user_key="12345", display_name="",
        group_key="", role="member", command_count=1,
        first_seen_at="", last_seen_at="",
    )
    assert users.display_label(short) == "12345"


def test_display_label_prefers_nickname(connection: sqlite3.Connection) -> None:
    """有昵称就显示昵称喵。"""
    users.record_seen(connection, "napcat", "123", display_name="小明", now=BASE_NOW)
    user = users.list_seen_users(connection)[0]
    assert users.display_label(user) == "小明"


def test_name_is_truncated(connection: sqlite3.Connection) -> None:
    """超长昵称截断，别把表格撑爆喵。"""
    users.record_seen(connection, "napcat", "123", display_name="喵" * 200, now=BASE_NOW)
    assert len(users.list_seen_users(connection)[0].display_name) == users.MAX_NAME_LENGTH


def test_prune_removes_stale(connection: sqlite3.Connection) -> None:
    """很久没说话的人应被清理喵。"""
    users.record_seen(connection, "napcat", "stale", now=BASE_NOW - timedelta(days=30))
    users.record_seen(connection, "napcat", "fresh", now=BASE_NOW)
    # 保留 7 天喵
    cutoff = db.days_ago_text(7, now=BASE_NOW)
    removed = users.prune_seen_users(connection, cutoff)
    assert removed == 1
    assert [row.user_key for row in users.list_seen_users(connection)] == ["fresh"]


# ==================== 通道解析：昵称从哪来 ====================


def test_onebot_event_reads_card_first() -> None:
    """NapCat 事件里群名片优先于昵称喵。"""
    from app.bot.channel import from_onebot_event

    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 111,
        "user_id": 222,
        "self_id": 999,
        "message": [{"type": "text", "data": {"text": "/happy帮助"}}],
        "sender": {"nickname": "昵称甲", "card": "群名片乙"},
    }
    result = from_onebot_event(event, "999")
    assert result.message is not None
    assert result.message.display_name == "群名片乙"


def test_onebot_event_falls_back_to_nickname() -> None:
    """没有群名片时退回昵称喵。"""
    from app.bot.channel import from_onebot_event

    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 111,
        "user_id": 222,
        "self_id": 999,
        "message": [{"type": "text", "data": {"text": "/happy帮助"}}],
        "sender": {"nickname": "昵称甲", "card": ""},
    }
    result = from_onebot_event(event, "999")
    assert result.message.display_name == "昵称甲"


def test_onebot_event_without_sender_is_blank() -> None:
    """事件里没有 sender 时不能崩，昵称留空喵。"""
    from app.bot.channel import from_onebot_event

    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 111,
        "user_id": 222,
        "self_id": 999,
        "message": [{"type": "text", "data": {"text": "/happy帮助"}}],
    }
    result = from_onebot_event(event, "999")
    assert result.message.display_name == ""


def test_qqbot_event_has_no_nickname() -> None:
    """官方通道只给 openid，昵称恒为空——这是平台限制喵。"""
    from app.bot.channel import from_qqbot_event

    event = {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "msg-1",
            "content": "/happy帮助",
            "group_openid": "G1",
            "author": {"member_openid": "M1", "member_role": "member"},
        },
    }
    result = from_qqbot_event(event, "bot")
    assert result.message.user_key == "M1"
    # 喵~注意：这条断言是「平台不给昵称」的事实记录，将来平台补字段会在这里失败喵
    assert result.message.display_name == ""


def test_qqbot_event_picks_up_name_if_platform_provides() -> None:
    """万一平台下发昵称字段，要能自动用上喵。"""
    from app.bot.channel import from_qqbot_event

    event = {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "msg-1",
            "content": "/happy帮助",
            "group_openid": "G1",
            "author": {"member_openid": "M1", "username": "官方昵称"},
        },
    }
    result = from_qqbot_event(event, "bot")
    assert result.message.display_name == "官方昵称"


# ==================== HTTP 接口 ====================


def test_api_lists_seen_users(client: TestClient, app_config: AppConfig) -> None:
    """接口要给出完整 openid 与昵称喵。"""
    connection = db.connect(app_config.server.db_path)
    try:
        users.record_seen(
            connection, "napcat", "123456",
            display_name="小明", group_key="111", now=db.utc_now(),
        )
    finally:
        connection.close()
    response = client.get("/api/v1/acl/seen-users", headers=AUTH_HEADERS)
    assert response.status_code == 200
    rows = response.json()["users"]
    assert len(rows) == 1
    assert rows[0]["user_key"] == "123456"
    assert rows[0]["display_name"] == "小明"
    assert rows[0]["label"] == "小明"


def test_api_seen_users_requires_token(client: TestClient) -> None:
    """不带口令应 401 喵。"""
    assert client.get("/api/v1/acl/seen-users").status_code == 401


def test_api_seen_users_empty(client: TestClient) -> None:
    """没人发过命令时返回空数组而不是报错喵。"""
    response = client.get("/api/v1/acl/seen-users", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["users"] == []
