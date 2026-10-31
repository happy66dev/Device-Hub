"""设置接口测试：读取、写回、热更新、测试连接、重启喵。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.main import _bot_signature, create_app

from conftest import TEST_INGEST_TOKEN
from test_settings import SAMPLE_CONFIG

# 统一的请求头喵
AUTH_HEADERS = {"X-Ingest-Token": TEST_INGEST_TOKEN}


def _posix(path: Path) -> str:
    """把 Windows 路径转成 YAML 里安全的正斜杠形式喵。"""
    # 喵~防御：反斜杠在双引号 YAML 里是转义符，必须换掉喵
    return str(path).replace("\\", "/")


def _sample_text(tmp_path: Path, qqbot_enabled: bool = False) -> str:
    """生成样例配置文本，数据库路径指向临时目录喵。"""
    # 数据库路径改成临时库，避免热更新之后接口读到真实库喵
    text = SAMPLE_CONFIG.replace('"data/device_hub.db"', f'"{_posix(tmp_path / "device_hub.db")}"')
    # 需要时把官方通道打开，并补上凭据（没有凭据时配置校验会直接报错）喵
    if qqbot_enabled:
        text = text.replace("qqbot:\n  enabled: false", "qqbot:\n  enabled: true")
        text = text.replace('app_id: ""', 'app_id: "1020000001"')
        text = text.replace('app_secret: ""', 'app_secret: "test-secret-abcdef"')
    return text


@pytest.fixture()
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把配置路径指到临时文件，避免测试碰到真实 config.yaml 喵。"""
    # 写一份样例配置喵
    path = tmp_path / "config.yaml"
    path.write_text(_sample_text(tmp_path), encoding="utf-8")
    # 服务端按这个环境变量找配置文件喵
    monkeypatch.setenv("DEVICE_HUB_CONFIG", str(path))
    return path


class _StubRunner:
    """替身机器人：只记录有没有被启动，不连真实网关喵。"""

    def __init__(self, config: object) -> None:
        # 记下配置，方便断言喵
        self.config = config
        # 是否真的跑起来了喵
        self.started = False

    def channel_names(self) -> list[str]:
        """替身只有官方通道喵。"""
        return ["qqbot"]

    def is_connected(self) -> bool:
        """替身永远没连上喵。"""
        return False

    def channel_status(self) -> list[dict[str, object]]:
        """状态接口要用的结构喵。"""
        return [{"name": "qqbot", "connected": False}]

    async def run(self) -> None:
        """一直挂着，直到被取消喵。"""
        self.started = True
        await asyncio.sleep(3600)


def test_get_settings_masks_secrets(client: TestClient, config_file: Path) -> None:
    """读取配置时密钥必须打码喵。"""
    # 取配置项喵
    response = client.get("/api/v1/settings", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    # 字段名齐全喵
    names = {item["name"] for item in body["fields"]}
    assert {"napcat.ws_url", "qqbot.app_secret", "acl.whitelist_groups"} <= names
    # 密钥只给占位符喵
    secret = next(item for item in body["fields"] if item["name"] == "qqbot.app_secret")
    assert secret["value"] == "********"
    # 路径要回显喵
    assert body["config_path"].endswith("config.yaml")


def test_get_settings_requires_token(client: TestClient, config_file: Path) -> None:
    """不带口令应 401喵。"""
    assert client.get("/api/v1/settings").status_code == 401


def test_patch_settings_writes_file(client: TestClient, config_file: Path) -> None:
    """保存配置应真的写进文件，并且立刻热更新生效喵。"""
    # 改白名单喵
    response = client.patch(
        "/api/v1/settings",
        json={"changes": {"acl.whitelist_groups": [111111]}},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == ["acl.whitelist_groups"]
    # 喵~注意：白名单属于能热更新的项，不需要重启喵
    assert body["restart_required"] is False
    assert body["applied"] is True
    # 文件内容更新了喵
    assert "  whitelist_groups: [111111]" in config_file.read_text(encoding="utf-8")


def test_patch_settings_hot_reloads_memory_config(client: TestClient, config_file: Path) -> None:
    """保存后再读一次必须拿到新值，不能是启动时的旧配置喵。"""
    # 先改白名单喵
    response = client.patch(
        "/api/v1/settings",
        json={"changes": {"acl.whitelist_groups": [111111, 222222]}},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    # 内存里的配置已经换掉了喵
    assert list(client.app.state.config.acl.whitelist_groups) == [111111, 222222]
    # 喵~注意：旧实现 GET 读的是内存旧配置，前端保存后看起来就像被"重置"了喵
    fields = {
        item["name"]: item["value"]
        for item in client.get("/api/v1/settings", headers=AUTH_HEADERS).json()["fields"]
    }
    assert fields["acl.whitelist_groups"] == [111111, 222222]


def test_patch_settings_restarts_bot_runner(
    client: TestClient, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打开官方通道后应立刻建出机器人任务（替身，不连网关）喵。"""
    # 用替身替换真实机器人，避免测试去连 QQ 网关喵
    monkeypatch.setattr("app.main.BotRunner", _StubRunner)
    # 打开官方通道（配置校验要求同时有凭据，否则写盘会被拒）喵
    response = client.patch(
        "/api/v1/settings",
        json={
            "changes": {
                "qqbot.enabled": True,
                "qqbot.app_id": "1020000001",
                "qqbot.app_secret": "test-secret-abcdef",
            }
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    # 机器人实例与任务都要就位喵
    assert isinstance(client.app.state.bot_runner, _StubRunner)
    assert client.app.state.bot_task is not None


def test_qqbot_only_config_starts_bot_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只开官方通道、关掉 NapCat 时也要起机器人任务喵。"""
    # 写一份只开官方通道的配置喵
    path = tmp_path / "config.yaml"
    path.write_text(_sample_text(tmp_path, qqbot_enabled=True), encoding="utf-8")
    monkeypatch.setenv("DEVICE_HUB_CONFIG", str(path))
    # 同样用替身，避免真的连网关喵
    monkeypatch.setattr("app.main.BotRunner", _StubRunner)
    # 用这份配置起应用喵
    with TestClient(create_app(load_config(path))) as client:
        # 喵~注意：以前只看 napcat.enabled，只开官方通道时机器人根本不会启动喵
        assert isinstance(client.app.state.bot_runner, _StubRunner)
        assert client.app.state.bot_task is not None


def test_bot_signature_detects_channel_switch(config_file: Path) -> None:
    """机器人配置签名要能区分通道开关，供热更新判断是否重建喵。"""
    # 读两份配置：一份关通道，一份开官方通道喵
    base = load_config(config_file)
    config_file.write_text(_sample_text(config_file.parent, qqbot_enabled=True), encoding="utf-8")
    opened = load_config(config_file)
    # 签名必须不同喵
    assert _bot_signature(base) != _bot_signature(opened)


def test_patch_settings_rejects_unknown_key(client: TestClient, config_file: Path) -> None:
    """白名单之外的键要 400喵。"""
    response = client.patch(
        "/api/v1/settings",
        json={"changes": {"server.port": 1234}},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_settings"


def test_patch_settings_rejects_non_object_changes(client: TestClient, config_file: Path) -> None:
    """changes 不是对象时 422喵。"""
    response = client.patch("/api/v1/settings", json={"changes": "nope"}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_patch_settings_requires_token(client: TestClient, config_file: Path) -> None:
    """写配置必须带口令喵。"""
    response = client.patch("/api/v1/settings", json={"changes": {"acl.whitelist_groups": [1]}})
    assert response.status_code == 401


def test_bot_test_reports_closed_port(client: TestClient, config_file: Path) -> None:
    """NapCat 端口没开时测试应返回未连通而不是报错喵。"""
    # 样例配置指向 7999，测试环境里没人监听喵
    response = client.post("/api/v1/bot/test", json={"channel": "napcat"}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["connected"] is False
    assert body["error"]


def test_bot_test_reports_missing_credentials(client: TestClient, config_file: Path) -> None:
    """官方通道没填凭据时应直接说明原因喵。"""
    response = client.post("/api/v1/bot/test", json={"channel": "qqbot"}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "AppID" in body["error"]


def test_bot_test_rejects_unknown_channel(client: TestClient, config_file: Path) -> None:
    """未知通道应 422喵。"""
    response = client.post("/api/v1/bot/test", json={"channel": "telegram"}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_restart_returns_202_and_schedules(
    client: TestClient, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重启接口应立刻回 202，并安排真正的重启动作喵。"""
    # 喵~防御：测试里绝不能真的退出进程，用记录器替换掉重启函数喵
    called: list[int] = []
    monkeypatch.setattr("app.main._restart_after_reply", lambda config: called.append(config.server.port))
    # 调用接口喵
    response = client.post("/api/v1/server/restart", headers=AUTH_HEADERS)
    assert response.status_code == 202
    assert response.json()["restarting"] is True
    # 后台任务确实被安排了喵
    assert called == [8080]


def test_restart_requires_token(client: TestClient, config_file: Path) -> None:
    """重启必须带口令喵。"""
    assert client.post("/api/v1/server/restart").status_code == 401
