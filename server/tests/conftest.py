"""测试公共夹具：临时配置、临时数据库、测试用 HTTP 客户端喵。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import (
    AclSection,
    AppConfig,
    GatingSection,
    IngestSection,
    NapCatSection,
    RenderSection,
    RetentionSection,
    RolesSection,
    ServerSection,
)
from app.main import create_app

# 测试用上报口令，长度满足配置校验要求喵
TEST_INGEST_TOKEN = "test-token-12345678"


@pytest.fixture()
def app_config(tmp_path: Path) -> AppConfig:
    """构造一套指向临时目录的配置，避免污染真实数据库喵。"""
    # 数据库放在 pytest 提供的临时目录里，测试结束自动清理喵
    database_path = tmp_path / "device_hub.db"
    # 返回完整配置对象喵
    return AppConfig(
        server=ServerSection(host="127.0.0.1", port=8080, db_path=database_path, log_level="warning"),
        ingest=IngestSection(token=TEST_INGEST_TOKEN, max_payload_bytes=4096),
        retention=RetentionSection(detail_days=7, aggregate_days=30),
        napcat=NapCatSection(enabled=False, ws_url="ws://127.0.0.1:7999", token="", reconnect_seconds=1, self_qq=""),
        acl=AclSection(whitelist_groups=(111111,), blacklist_users=(222222,)),
        render=RenderSection(max_hardware_fields=8, image_enabled=False),
        roles=RolesSection(servers=(), workstations=()),
        gating=GatingSection(enabled=True, rdp_stale_seconds=180),
        base_dir=tmp_path,
    )


@pytest.fixture()
def client(app_config: AppConfig) -> Iterator[TestClient]:
    """启动带生命周期的测试客户端，退出时自动关闭喵。"""
    # 用 with 语句触发 lifespan，确保建表动作执行喵
    with TestClient(create_app(app_config)) as test_client:
        # 交给测试用例使用喵
        yield test_client


@pytest.fixture()
def connection(app_config: AppConfig):
    """提供一个已建表的数据库连接，供直接操作数据库的测试使用喵。"""
    # 先建表喵
    db.init_db(app_config.server.db_path)
    # 打开连接喵
    conn = db.connect(app_config.server.db_path)
    try:
        # 交给测试用例使用喵
        yield conn
    finally:
        # 测试结束关闭连接喵
        conn.close()


def make_payload(**overrides: Any) -> dict[str, Any]:
    """生成一份合法的上报字典，允许按需覆盖字段喵。"""
    # 默认使用当前时间，保证不会触发"未来时间"校验喵
    base_payload: dict[str, Any] = {
        "device_id": "win-test-0001",
        "platform": "windows",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "display_name": "测试台式机",
        "hardware": {"os_version": "Windows 10 1607", "cpu": "Ryzen 7 9700X"},
        "current_app": {"name": "Code.exe", "package": "Code.exe"},
        "usage_delta": [{"app": "Code.exe", "seconds": 60}],
        "client_version": "0.1.0",
    }
    # 覆盖调用方指定的字段喵
    base_payload.update(overrides)
    return base_payload
