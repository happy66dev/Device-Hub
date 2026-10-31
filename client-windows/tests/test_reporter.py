"""上报器单元测试：负载组装、成功与失败路径喵。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from agent.collector import ForegroundApp, WindowInfo
from agent.config import AgentConfig
from agent.reporter import MAX_USAGE_ITEMS, Reporter


def _config() -> AgentConfig:
    """构造一份测试配置喵。"""
    # 地址指向本地假服务端喵
    return AgentConfig(
        server_url="http://127.0.0.1:8080",
        ingest_token="test-token-12345678",
        device_id="win-test-0001",
        display_name="测试机",
    )


def _foreground_app() -> ForegroundApp:
    """构造一个前台应用快照喵。"""
    # 进入前台时间固定，便于断言喵
    return ForegroundApp(
        name="Code",
        package="Code.exe",
        title="main.py",
        since=datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc),
    )


def test_build_payload_includes_all_fields() -> None:
    """完整输入时负载应包含所有协议字段喵。"""
    # 创建上报器喵
    reporter = Reporter(_config())
    # 组装负载喵
    payload = reporter.build_payload(
        hardware={"cpu": "Ryzen 7 9700X"},
        battery=(88, True),
        current_app=_foreground_app(),
        usage_deltas=[{"app": "Code.exe", "seconds": 60}],
    )
    # 关键字段应齐全喵
    assert payload["device_id"] == "win-test-0001"
    assert payload["platform"] == "windows"
    assert payload["battery"] == {"percent": 88, "charging": True}
    assert payload["current_app"]["package"] == "Code.exe"
    assert payload["usage_delta"][0]["seconds"] == 60
    # 上报时间应带时区喵
    assert "+" in payload["reported_at"] or payload["reported_at"].endswith("Z")
    # 关闭连接喵
    reporter.close()


def test_build_payload_omits_missing_optional_fields() -> None:
    """没有电量与前台应用时不应出现对应字段喵。"""
    # 创建上报器喵
    reporter = Reporter(_config())
    # 只给必填信息喵
    payload = reporter.build_payload(hardware={}, battery=None, current_app=None, usage_deltas=[])
    # 可选字段应缺失喵
    assert "battery" not in payload
    assert "current_app" not in payload
    # 关闭连接喵
    reporter.close()


def test_build_payload_truncates_usage_list() -> None:
    """使用时长条目超过上限时应截断喵。"""
    # 创建上报器喵
    reporter = Reporter(_config())
    # 构造超过上限的列表喵
    usage_deltas = [{"app": f"app{index}", "seconds": 1} for index in range(MAX_USAGE_ITEMS + 10)]
    # 组装负载喵
    payload = reporter.build_payload(hardware={}, battery=None, current_app=None, usage_deltas=usage_deltas)
    # 条数应被截断喵
    assert len(payload["usage_delta"]) == MAX_USAGE_ITEMS
    # 关闭连接喵
    reporter.close()


def test_send_success() -> None:
    """服务端返回 200 时应判定成功喵。"""
    # 记录收到的请求，便于断言喵
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """假服务端：记录请求并返回成功喵。"""
        captured_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    # 用 MockTransport 创建客户端喵
    client = httpx.Client(transport=httpx.MockTransport(handler))
    # 创建上报器喵
    reporter = Reporter(_config(), client=client)
    # 发送喵
    succeeded, message = reporter.send({"device_id": "win-test-0001"})
    # 应成功喵
    assert succeeded is True
    assert message == "上报成功"
    # 请求地址与请求头应正确喵
    assert str(captured_requests[0].url) == "http://127.0.0.1:8080/api/v1/report"
    assert captured_requests[0].headers["X-Ingest-Token"] == "test-token-12345678"
    # 关闭喵
    reporter.close()


def test_send_returns_failure_on_401() -> None:
    """服务端返回 401 时应返回失败并带上状态码喵。"""
    # 假服务端固定返回 401 喵
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error": "invalid_token"})

    # 创建客户端与上报器喵
    client = httpx.Client(transport=httpx.MockTransport(handler))
    reporter = Reporter(_config(), client=client)
    # 发送喵
    succeeded, message = reporter.send({"device_id": "win-test-0001"})
    # 应失败并带状态码喵
    assert succeeded is False
    assert "401" in message
    # 关闭喵
    reporter.close()


def test_send_returns_failure_on_network_error() -> None:
    """网络异常时应返回失败而不是抛异常喵。"""
    # 假服务端直接抛连接错误喵
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("模拟断网", request=request)

    # 创建客户端与上报器喵
    client = httpx.Client(transport=httpx.MockTransport(handler))
    reporter = Reporter(_config(), client=client)
    # 发送喵
    succeeded, message = reporter.send({"device_id": "win-test-0001"})
    # 应失败并说明是网络问题喵
    assert succeeded is False
    assert "网络请求失败" in message
    # 关闭喵
    reporter.close()

def test_send_returns_failure_on_unexpected_exception() -> None:
    """非 httpx 的异常也要变成"失败"，绝不能抛给主循环把数据带走喵。"""
    # 假服务端抛一个和网络无关的异常喵
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("地址写错了")

    # 创建客户端与上报器喵
    client = httpx.Client(transport=httpx.MockTransport(handler))
    reporter = Reporter(_config(), client=client)
    # 发送喵
    succeeded, message = reporter.send({"device_id": "win-test-0001"})
    # 应失败并说明是请求异常喵
    assert succeeded is False
    assert "请求异常" in message
    assert "地址写错了" in message
    # 关闭喵
    reporter.close()


def test_payload_includes_gating_fields_for_server() -> None:
    """服务器角色应上报角色、标签、RDP 状态与投屏窗口喵。"""
    # 构造服务器角色配置喵
    config = _config()
    config.role = "server"
    config.tag = "我的手机"
    # 创建上报器喵
    reporter = Reporter(config)
    try:
        # 组装负载喵
        payload = reporter.build_payload({}, None, None, [], rdp_connected=True, mirror_windows=["23113RKC6C"])
    finally:
        # 关闭连接喵
        reporter.close()
    # 各字段应正确喵
    assert payload["role"] == "server"
    assert payload["tag"] == "我的手机"
    assert payload["rdp_connected"] is True
    assert payload["mirror_windows"] == ["23113RKC6C"]


def test_payload_omits_gating_fields_when_not_provided() -> None:
    """工作站不传 RDP 与投屏字段，避免服务端误判喵。"""
    # 默认工作站配置喵
    reporter = Reporter(_config())
    try:
        # 不传门控参数喵
        payload = reporter.build_payload({}, None, None, [])
    finally:
        # 关闭连接喵
        reporter.close()
    # 不应出现这些字段喵
    assert "rdp_connected" not in payload
    assert "mirror_windows" not in payload
    assert "tag" not in payload
    # 角色仍要上报喵
    assert payload["role"] == "workstation"


def test_payload_includes_afk_boundaries() -> None:
    """AFK 边界时刻要按 UTC ISO 输出，让服务端把空档量到秒喵。"""
    # 构造上报器喵
    reporter = Reporter(_config())
    try:
        # 进入 AFK：只带 afk_since 喵
        afk_payload = reporter.build_payload(
            {},
            None,
            None,
            [],
            afk=True,
            afk_since=datetime(2026, 10, 29, 9, 58, 30, tzinfo=timezone.utc),
        )
        # 恢复使用：只带 active_since 喵
        active_payload = reporter.build_payload(
            {},
            None,
            None,
            [],
            afk=False,
            active_since=datetime(2026, 10, 29, 9, 59, 40, tzinfo=timezone.utc),
        )
        # 两个都不带时字段应完全省略喵
        plain_payload = reporter.build_payload({}, None, None, [])
    finally:
        # 关闭连接喵
        reporter.close()
    assert afk_payload["afk"] is True
    assert afk_payload["afk_since"] == "2026-10-29T09:58:30+00:00"
    assert "active_since" not in afk_payload
    assert active_payload["afk"] is False
    assert active_payload["active_since"] == "2026-10-29T09:59:40+00:00"
    assert "afk_since" not in active_payload
    assert "afk" not in plain_payload
    assert "afk_since" not in plain_payload
    assert "active_since" not in plain_payload


def test_payload_includes_current_app_title() -> None:
    """当前应用的窗口标题要一起上报喵。"""
    # 造一个带标题的前台应用喵
    config = _config()
    reporter = Reporter(config, client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))))
    app = ForegroundApp(
        name="Chrome",
        package="chrome.exe",
        title="看板 - device-hub",
        since=datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc),
    )
    # 组装负载喵
    payload = reporter.build_payload(hardware={"os_version": "Windows"}, battery=None, current_app=app, usage_deltas=[])
    # 标题应在里面喵
    assert payload["current_app"]["title"] == "看板 - device-hub"


def test_payload_includes_open_windows() -> None:
    """已打开窗口列表要按协议字段序列化喵。"""
    # 造两个窗口喵
    config = _config()
    reporter = Reporter(config, client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))))
    windows = [
        WindowInfo(app="Chrome", package="chrome.exe", title="看板", minimized=False, foreground=True),
        WindowInfo(app="记事本", package="notepad.exe", title="笔记.txt", minimized=True, foreground=False),
    ]
    # 组装负载喵
    payload = reporter.build_payload(
        hardware={"os_version": "Windows"},
        battery=None,
        current_app=None,
        usage_deltas=[],
        open_windows=windows,
    )
    # 字段应完整喵
    assert payload["open_windows"] == [
        {"app": "Chrome", "package": "chrome.exe", "title": "看板", "minimized": False, "foreground": True},
        {"app": "记事本", "package": "notepad.exe", "title": "笔记.txt", "minimized": True, "foreground": False},
    ]


def test_payload_omits_open_windows_when_empty() -> None:
    """没有窗口时不带这个字段，避免服务端收到空数组喵。"""
    # 空列表喵
    config = _config()
    reporter = Reporter(config, client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))))
    payload = reporter.build_payload(
        hardware={"os_version": "Windows"},
        battery=None,
        current_app=None,
        usage_deltas=[],
        open_windows=[],
    )
    # 字段不该出现喵
    assert "open_windows" not in payload