"""上报接口的集成测试：鉴权、校验、幂等、大小限制喵。"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from conftest import TEST_INGEST_TOKEN, make_payload

from app import presence
from app.db import to_utc_text
from app.main import _verify_token

# 统一的请求头喵
AUTH_HEADERS = {"X-Ingest-Token": TEST_INGEST_TOKEN}


def test_report_requires_token(client: TestClient) -> None:
    """不带口令应返回 401 喵。"""
    # 直接发一个合法负载但不带口令喵
    response = client.post("/api/v1/report", json=make_payload())
    # 状态码应为 401 喵
    assert response.status_code == 401
    # 错误码应明确喵
    assert response.json()["error"] == "invalid_token"


def test_report_rejects_wrong_token(client: TestClient) -> None:
    """口令错误应返回 401 喵。"""
    # 带一个错误口令喵
    response = client.post("/api/v1/report", json=make_payload(), headers={"X-Ingest-Token": "wrong-token-000"})
    # 状态码应为 401 喵
    assert response.status_code == 401


def test_non_ascii_token_header_is_401_not_500(client: TestClient) -> None:
    """口令含非 ASCII 字符时应是 401，不能让 compare_digest 抛 TypeError 变 500 喵。"""
    # 喵~注意：hmac.compare_digest 比 str 时遇到非 ASCII 会抛 TypeError。
    # 请求头是原始字节，Starlette 会按 latin-1 解码成含非 ASCII 的字符串，
    # 这里直接发字节头模拟攻击者，确认已经被编成 bytes 比较，鉴权失败要走 401 喵
    response = client.post(
        "/api/v1/report",
        json=make_payload(),
        headers={"X-Ingest-Token": b"\xe4\xb8\xad\xe6\x96\x87"},
    )
    # 必须是 401 而不是 500 喵
    assert response.status_code == 401
    # 错误码保持统一喵
    assert response.json()["error"] == "invalid_token"


def test_non_ascii_query_token_is_401_not_500(client: TestClient) -> None:
    """查询串里的非 ASCII 口令同样只能 401，不能 500 喵。"""
    # 图标接口允许 ?token=，这里故意塞中文喵
    response = client.get("/api/v1/icons/whatever?token=%E4%B8%AD%E6%96%87%E5%8F%A3%E4%BB%A4")
    # 喵~注意：以前这里会 500，因为 _verify_query_token 也直接比 str 喵
    assert response.status_code == 401
    # 错误码保持统一喵
    assert response.json()["error"] == "invalid_token"


def test_non_ascii_configured_token_still_matches() -> None:
    """主人真把口令配成中文时，正确的口令必须能通过校验喵。"""
    # 用最小替身代替 Request 与 AppConfig，只测比较逻辑喵
    secret = "中文口令九个字"
    # 请求头带正确的中文口令喵
    request = SimpleNamespace(headers={"x-ingest-token": secret})
    # 配置里的口令与之一致喵
    config = SimpleNamespace(ingest=SimpleNamespace(token=secret))
    # 喵~注意：编成 bytes 后非 ASCII 也能正常比较，不再抛 TypeError 喵
    assert _verify_token(request, config) is True
    # 不匹配时仍返回 False 喵
    assert _verify_token(SimpleNamespace(headers={"x-ingest-token": "别的口令"}), config) is False


def test_report_accepts_valid_payload(client: TestClient) -> None:
    """合法负载应返回 200 并回显写入摘要喵。"""
    # 发送合法负载喵
    response = client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    # 响应体应标记成功喵
    body = response.json()
    assert body["ok"] is True
    # 设备 ID 应被回显喵
    assert body["device_id"] == "win-test-0001"
    # 一条使用增量应被写入喵
    assert body["usage_rows_written"] == 1


def test_report_is_idempotent_for_same_timestamp(client: TestClient) -> None:
    """同一时间点重复上报应返回 duplicate=true 且不重复累计喵。"""
    # 固定时间点喵
    fixed_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    # 第一次上报喵
    first_response = client.post("/api/v1/report", json=make_payload(reported_at=fixed_time), headers=AUTH_HEADERS)
    # 第一次不应是重复喵
    assert first_response.json()["duplicate"] is False
    # 第二次上报喵
    second_response = client.post("/api/v1/report", json=make_payload(reported_at=fixed_time), headers=AUTH_HEADERS)
    # 第二次应被识别为重复喵
    assert second_response.json()["duplicate"] is True


def test_report_rejects_invalid_json(client: TestClient) -> None:
    """非法 JSON 应返回 422 喵。"""
    # 直接发一段坏 JSON 喵
    response = client.post("/api/v1/report", content=b"{not-json", headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422
    # 错误码应为 invalid_payload 喵
    assert response.json()["error"] == "invalid_payload"


def test_report_rejects_empty_body(client: TestClient) -> None:
    """空请求体应返回 422 喵。"""
    # 发送空内容喵
    response = client.post("/api/v1/report", content=b"", headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_report_rejects_missing_device_id(client: TestClient) -> None:
    """缺少设备 ID 应返回 422 并指出字段名喵。"""
    # 删掉 device_id 字段喵
    payload = make_payload()
    payload.pop("device_id")
    # 发送喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422
    # detail 应提到 device_id 喵
    assert "device_id" in response.json()["detail"]


def test_report_rejects_battery_out_of_range(client: TestClient) -> None:
    """电量超过 100 应返回 422 喵。"""
    # 电量写成 150 喵
    payload = make_payload(battery={"percent": 150, "charging": False})
    # 发送喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_report_rejects_future_timestamp(client: TestClient) -> None:
    """客户端时间快太多应返回 422 喵。"""
    # 时间设为 1 小时后喵
    future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    # 发送喵
    response = client.post("/api/v1/report", json=make_payload(reported_at=future_time), headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_report_rejects_naive_timestamp(client: TestClient) -> None:
    """不带时区的时间应返回 422 喵。"""
    # 构造不带时区的时间字符串喵
    naive_time = datetime.now().replace(microsecond=0).isoformat()
    # 发送喵
    response = client.post("/api/v1/report", json=make_payload(reported_at=naive_time), headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_report_rejects_extra_field(client: TestClient) -> None:
    """多余字段应被拒绝，避免协议悄悄漂移喵。"""
    # 塞入一个协议里不存在的字段喵
    payload = make_payload(unexpected_field="x")
    # 发送喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_report_rejects_oversized_body(client: TestClient) -> None:
    """超过 max_payload_bytes 的请求应返回 413 喵。"""
    # 构造 5000 字节的填充内容，测试配置上限是 4096 喵
    oversized_payload = {"padding": "x" * 5000}
    # 发送喵
    response = client.post(
        "/api/v1/report",
        content=json.dumps(oversized_payload).encode("utf-8"),
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
    )
    # 状态码应为 413 喵
    assert response.status_code == 413


def test_healthz(client: TestClient) -> None:
    """健康检查应返回版本与数据库路径喵。"""
    # 请求健康检查喵
    response = client.get("/healthz")
    # 状态码应为 200 喵
    assert response.status_code == 200
    # 响应应标记 ok 喵
    assert response.json()["ok"] is True


def test_devices_endpoint_requires_token(client: TestClient) -> None:
    """设备列表接口同样需要口令喵。"""
    # 不带口令请求喵
    response = client.get("/api/v1/devices")
    # 状态码应为 401 喵
    assert response.status_code == 401


def test_devices_endpoint_lists_reported_device(client: TestClient) -> None:
    """上报之后设备列表应能看到这台设备喵。"""
    # 先上报一次喵
    client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 再查列表喵
    response = client.get("/api/v1/devices", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    # 列表里应有刚才的设备喵
    device_ids = [item["device_id"] for item in response.json()["devices"]]
    assert "win-test-0001" in device_ids
    # 刚上报过的设备应显示在线喵
    assert response.json()["devices"][0]["online"] is True


def test_report_response_reports_paused_state(client: TestClient) -> None:
    """服务器角色在 RDP 未连接时，响应应标记统计暂停喵。"""
    # 构造服务器角色且 RDP 未连接的上报喵
    payload = make_payload(role="server", rdp_connected=False)
    # 发送喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    # 响应应说明暂停原因喵
    body = response.json()
    assert body["stats_paused"] is True
    assert body["stats_paused_reason"] == "rdp_disconnected"
    assert body["usage_rows_written"] == 0


def test_dashboard_requires_token(client: TestClient) -> None:
    """看板接口需要口令喵。"""
    # 不带口令请求喵
    response = client.get("/api/v1/dashboard")
    # 应返回 401 喵
    assert response.status_code == 401


def test_dashboard_lists_device_cards(client: TestClient) -> None:
    """看板应返回设备卡片、电量与近 24 小时排行喵。"""
    # 先上报一台安卓设备喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="and-board-0001",
            platform="android",
            battery={"percent": 66, "charging": True},
            hardware={"model": "23113RKC6C", "android_version": "14"},
            tag="看板手机",
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 120}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求看板喵
    response = client.get("/api/v1/dashboard", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    # 找到那台设备喵
    cards = {item["device_id"]: item for item in response.json()["devices"]}
    card = cards["and-board-0001"]
    # 电量与标签应正确喵
    assert card["battery"]["percent"] == 66
    assert card["tag"] == "看板手机"
    # 排行应带上包名喵
    assert card["usage_top"][0]["package"] == "com.tencent.mm"
    assert card["usage_total_seconds"] == 120


def test_device_detail_endpoint_returns_series(client: TestClient) -> None:
    """设备详情应返回电量曲线与使用时间轴喵。"""
    # 先上报一次喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="and-detail-0001",
            platform="android",
            battery={"percent": 80, "charging": False},
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求详情喵
    response = client.get("/api/v1/devices/and-detail-0001", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 电量曲线应有一个点喵
    assert len(body["battery_series"]) == 1
    assert body["battery_series"][0]["percent"] == 80
    # 时间轴应有一个小时桶喵
    assert len(body["usage_timeline"]) == 1
    assert body["usage_timeline"][0]["seconds"] == 60
    # 排行应带包名喵
    assert body["usage_ranking"][0]["package"] == "com.tencent.mm"


def test_device_detail_endpoint_unknown_returns_404(client: TestClient) -> None:
    """查询不存在的设备应返回 404 喵。"""
    # 请求一个不存在的设备喵
    response = client.get("/api/v1/devices/nope-0001", headers=AUTH_HEADERS)
    # 状态码应为 404 喵
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_role_endpoint_marks_server_and_gates(client: TestClient) -> None:
    """看板标记服务器后，该设备的下一次上报应被门控喵。"""
    # 先让设备以工作站身份上报一次喵
    client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 标记为服务器喵
    response = client.post("/api/v1/devices/win-test-0001/role", json={"role": "server"}, headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    assert response.json()["role"] == "server"
    # 再上报一次（RDP 未连接）喵
    second_time = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    report = client.post(
        "/api/v1/report",
        json=make_payload(reported_at=second_time, rdp_connected=False),
        headers=AUTH_HEADERS,
    )
    # 应被门控暂停喵
    assert report.json()["stats_paused"] is True


def test_role_endpoint_rejects_invalid_role(client: TestClient) -> None:
    """非法角色应返回 422 喵。"""
    # 先上报一次，保证设备存在喵
    client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 用非法角色请求喵
    response = client.post("/api/v1/devices/win-test-0001/role", json={"role": "master"}, headers=AUTH_HEADERS)
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_role_endpoint_requires_token(client: TestClient) -> None:
    """改角色需要口令喵。"""
    # 不带口令请求喵
    response = client.post("/api/v1/devices/win-test-0001/role", json={"role": "server"})
    # 应返回 401 喵
    assert response.status_code == 401


def test_web_dashboard_page_is_served(client: TestClient) -> None:
    """看板首页与静态资源应能被浏览器直接打开喵。"""
    # 请求首页喵
    page = client.get("/")
    # 状态码应为 200 喵
    assert page.status_code == 200
    # 页面应包含看板标题喵
    assert "device-hub 控制台" in page.text
    # 样式与脚本应可访问喵
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200

def test_rankings_requires_token(client: TestClient) -> None:
    """应用排行接口需要口令喵。"""
    # 不带口令请求喵
    assert client.get("/api/v1/rankings").status_code == 401


def test_rankings_returns_entries(client: TestClient) -> None:
    """应用排行应返回带包名与设备数的条目喵。"""
    # 两台设备各上报一次喵
    client.post(
        "/api/v1/report",
        json=make_payload(device_id="win-rank-0001", usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}]),
        headers=AUTH_HEADERS,
    )
    second_time = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-rank-0002",
            reported_at=second_time,
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 30}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求排行喵
    response = client.get("/api/v1/rankings?hours=24&limit=10", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 微信应合计 90 秒、2 台设备喵
    entry = body["entries"][0]
    assert entry["app"] == "微信"
    assert entry["package"] == "com.tencent.mm"
    assert entry["seconds"] == 90
    assert entry["device_count"] == 2


def test_rankings_lists_device_names(client: TestClient) -> None:
    """聚合排行要带上用过的设备名，方便区分同名应用喵。"""
    # 两台设备各上报一次同名应用喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-rank-name-1",
            display_name="书房主机",
            usage_delta=[{"app": "Code.exe", "package": "code.exe", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    second_time = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-rank-name-2",
            display_name="客厅主机",
            reported_at=second_time,
            usage_delta=[{"app": "Code.exe", "package": "code.exe", "seconds": 30}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求排行喵
    body = client.get("/api/v1/rankings?hours=24&limit=10", headers=AUTH_HEADERS).json()
    # 两台设备的展示名都要出现在条目里喵
    entry = body["entries"][0]
    assert sorted(entry["devices"]) == sorted(["书房主机", "客厅主机"])


def test_rankings_handles_bad_query_params(client: TestClient) -> None:
    """非法查询参数应退回默认值而不是报错喵。"""
    # 传一堆乱码喵
    response = client.get("/api/v1/rankings?hours=abc&limit=-5", headers=AUTH_HEADERS)
    # 状态码应为 200，hours 回落到 24 喵
    assert response.status_code == 200
    assert response.json()["hours"] == 24


def test_rankings_scope_all_matches_legacy(client: TestClient) -> None:
    """scope=all 应保持旧的 entries 结构，并补上 scope 与空 groups 喵。"""
    # 一台设备上报一次喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-all-1",
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求 all 口径喵
    body = client.get("/api/v1/rankings?hours=24&limit=10&scope=all", headers=AUTH_HEADERS).json()
    # 旧字段保持原样，新增 scope 与空 groups 喵
    assert body["scope"] == "all"
    assert body["groups"] == []
    assert body["entries"][0]["app"] == "微信"
    assert body["entries"][0]["seconds"] == 60


def test_rankings_scope_device_groups_by_device(client: TestClient) -> None:
    """scope=device 应每台设备一组，并带组总时长喵。"""
    # 两台设备各上报一次同名应用喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-dev-1",
            display_name="书房主机",
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    second_time = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-dev-2",
            display_name="客厅主机",
            reported_at=second_time,
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 30}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求设备口径喵
    body = client.get("/api/v1/rankings?hours=24&limit=10&scope=device", headers=AUTH_HEADERS).json()
    # 总排行仍是两台设备合计 90 秒喵
    assert body["scope"] == "device"
    assert body["entries"][0]["seconds"] == 90
    # 每台设备一组，按组总时长倒序喵
    assert [group["label"] for group in body["groups"]] == ["书房主机", "客厅主机"]
    assert body["groups"][0]["key"] == "win-scope-dev-1"
    assert body["groups"][0]["kind"] == "device"
    assert body["groups"][0]["seconds"] == 60
    assert body["groups"][0]["entries"][0]["devices"] == ["书房主机"]
    assert body["groups"][1]["seconds"] == 30


def test_rankings_scope_group_uses_people_and_ungrouped(client: TestClient) -> None:
    """scope=group 应按 people.groups 分组，未归组设备进未分组桶喵。"""
    # 保存一个只包含第一台设备的组喵
    saved = client.put(
        "/api/v1/people",
        headers=AUTH_HEADERS,
        json={"groups": [{"name": "主人", "devices": ["win-scope-grp-1"]}]},
    )
    assert saved.status_code == 200
    # 两台设备各上报一次同名应用喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-grp-1",
            display_name="书房主机",
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    second_time = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-grp-2",
            display_name="客厅主机",
            reported_at=second_time,
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 40}],
        ),
        headers=AUTH_HEADERS,
    )
    # 请求设备组口径喵
    body = client.get("/api/v1/rankings?hours=24&limit=10&scope=group", headers=AUTH_HEADERS).json()
    # 主人组在前，未分组桶在后喵
    assert body["scope"] == "group"
    assert [group["label"] for group in body["groups"]] == ["主人", "未分组"]
    owner = body["groups"][0]
    assert owner["key"] == "group:主人"
    assert owner["kind"] == "group"
    assert owner["seconds"] == 60
    assert owner["entries"][0]["devices"] == ["书房主机"]
    # 未分组桶只放第二台设备喵
    ungrouped = body["groups"][1]
    assert ungrouped["key"] == "ungrouped"
    assert ungrouped["label"] == "未分组"
    assert ungrouped["seconds"] == 40
    assert ungrouped["entries"][0]["devices"] == ["客厅主机"]
    # 总排行仍是两台设备合计 100 秒喵
    assert body["entries"][0]["seconds"] == 100


def test_rankings_empty_returns_empty_groups(client: TestClient) -> None:
    """空数据时 groups 应为空列表且不报错喵。"""
    # 三种口径都查一次喵
    for scope in ("all", "device", "group"):
        response = client.get(f"/api/v1/rankings?hours=24&scope={scope}", headers=AUTH_HEADERS)
        # 状态码应为 200，两个列表都为空喵
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == scope
        assert body["entries"] == []
        assert body["groups"] == []


def test_rankings_invalid_scope_falls_back_to_all(client: TestClient) -> None:
    """非法 scope 应退回 all 而不是 500 喵。"""
    # 一台设备上报一次喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-scope-bad-1",
            usage_delta=[{"app": "微信", "package": "com.tencent.mm", "seconds": 60}],
        ),
        headers=AUTH_HEADERS,
    )
    # 乱传口径喵
    response = client.get("/api/v1/rankings?scope=bogus", headers=AUTH_HEADERS)
    # 状态码应为 200，口径回落到 all 且没有分组喵
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "all"
    assert body["groups"] == []
    assert body["entries"][0]["app"] == "微信"


def test_bot_command_requires_token(client: TestClient) -> None:
    """命令测试接口需要口令喵。"""
    # 不带口令请求喵
    assert client.post("/api/v1/bot/command", json={"text": "/happy帮助"}).status_code == 401


def test_bot_command_returns_reply(client: TestClient) -> None:
    """命令测试应返回机器人回复文本喵。"""
    # 跑一次帮助命令喵
    response = client.post("/api/v1/bot/command", json={"text": "/happy帮助"}, headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 应判定为会回复并带命令说明喵
    assert body["replied"] is True
    assert body["reason"] == "ok"
    assert "/happy帮助" in body["text"]
    # 文本命令没有图片喵
    assert body["image_data_uri"] is None
    # 耗时字段应存在喵
    assert body["elapsed_ms"] >= 0


def test_bot_command_reports_acl_ignore(client: TestClient) -> None:
    """给了未授权群号时应说明被忽略的原因喵。"""
    # 用不在白名单的群号喵
    response = client.post("/api/v1/bot/command", json={"text": "/happy设备", "group_id": 999999}, headers=AUTH_HEADERS)
    # 状态码仍是 200，但标记为不回复喵
    assert response.status_code == 200
    body = response.json()
    assert body["replied"] is False
    assert body["reason"] == "group_not_whitelisted"
    assert "白名单" in body["reason_text"]


def test_bot_command_rejects_bad_payload(client: TestClient) -> None:
    """空命令与非法群号应返回 422 喵。"""
    # 只有空白字符喵
    assert client.post("/api/v1/bot/command", json={"text": "   "}, headers=AUTH_HEADERS).status_code == 422
    # 群号不是数字喵
    assert (
        client.post("/api/v1/bot/command", json={"text": "/happy设备", "group_id": "abc"}, headers=AUTH_HEADERS).status_code
        == 422
    )

def test_bot_status_requires_token(client: TestClient) -> None:
    """机器人状态接口需要口令喵。"""
    # 不带口令请求喵
    assert client.get("/api/v1/bot/status").status_code == 401


def test_bot_status_reports_disconnected(client: TestClient) -> None:
    """测试配置里机器人未启用，状态应如实反映喵。"""
    # 请求状态喵
    response = client.get("/api/v1/bot/status", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 测试配置关闭了机器人喵
    assert body["enabled"] is False
    assert body["connected"] is False
    # 白名单应来自测试配置喵
    assert body["whitelist_groups"] == [111111]
    assert body["blacklist_users"] == [222222]

def test_device_timeline_requires_token(client: TestClient) -> None:
    """时间轴接口需要口令喵。"""
    # 不带口令请求喵
    assert client.get("/api/v1/devices/any/timeline").status_code == 401


def test_device_timeline_rejects_bad_date(client: TestClient) -> None:
    """日期格式不对时返回 422 喵。"""
    # 传一个非法日期喵
    response = client.get("/api/v1/devices/any/timeline?date=2026-13-99", headers=AUTH_HEADERS)
    assert response.status_code == 422
    assert "invalid_payload" in response.text


def test_device_timeline_returns_empty_day(client: TestClient) -> None:
    """没有数据的日期返回空段与 24 个小时桶喵。"""
    # 请求一个肯定没数据的日期喵
    response = client.get("/api/v1/devices/any/timeline?date=2020-01-01", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    # 段列表为空，小时桶固定 24 个喵
    assert body["segments"] == []
    assert len(body["hours"]) == 24
    assert body["total_seconds"] == 0


def test_device_timeline_keeps_overlapping_segments(client: TestClient, connection) -> None:
    """单设备视图必须保留同一时刻的多条段，不能互相覆盖喵。"""
    # 造一台设备与两条时刻相同的采样喵
    now = datetime.now(timezone.utc)
    connection.execute(
        """
        INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                             current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?)
        """,
        ("win-overlap-solo", "windows", "单台", to_utc_text(now), to_utc_text(now)),
    )
    # 同一时刻两条不同应用，各 600 秒喵
    for app in ("Alpha.exe", "Beta.exe"):
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
            ("win-overlap-solo", app, app.lower(), to_utc_text(now - timedelta(minutes=5)), 600),
        )
    connection.commit()
    # 查这台设备的时间轴喵
    today = now.astimezone().strftime("%Y-%m-%d")
    body = client.get(f"/api/v1/devices/win-overlap-solo/timeline?date={today}", headers=AUTH_HEADERS).json()
    # 两个应用都要有段，谁也不该被裁掉喵
    apps = {segment["app"] for segment in body["segments"]}
    assert apps == {"Alpha.exe", "Beta.exe"}
    # 每段各自 600 秒，两段相加是 1200 秒喵
    assert sum(segment["seconds"] for segment in body["segments"]) == 1200


def test_timeline_total_uses_union_not_sum(client: TestClient, connection) -> None:
    """总时长要按时间轴并集算，不能把重叠时段重复计入喵。"""
    # 造两台设备，采样时间与时长完全相同喵
    now = datetime.now(timezone.utc)
    for index in range(2):
        device_id = f"win-union-{index}"
        connection.execute(
            """
            INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                                 current_app_json, client_version, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?)
            """,
            (device_id, "windows", f"机器{index}", to_utc_text(now), to_utc_text(now)),
        )
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
            (device_id, "Code.exe", "code.exe", to_utc_text(now - timedelta(minutes=5)), 600),
        )
    connection.commit()
    # 合并两台设备查喵
    today = now.astimezone().strftime("%Y-%m-%d")
    body = client.get(
        "/api/v1/timeline?devices=win-union-0,win-union-1&date=" + today, headers=AUTH_HEADERS
    ).json()
    # 喵~注意：合并口径按优先级裁剪，重叠只归靠前的设备，所以并集就是 600 秒喵
    assert body["total_seconds"] == 600


def test_timeline_lane_segments_keep_low_priority_usage(client: TestClient, connection) -> None:
    """重叠时顶层色块按优先级裁，但应用轴必须保留低优先级设备的记录喵。

    喵~注意：这是主人报的 issue——同一个时刻两台设备都有上报时，
    总轴只取优先级高的那台，低优先级设备的应用帧在图上整个消失了。
    修法是让后端额外下发 lane_segments（不裁剪），应用轴用它来画喵。
    """
    # 造两台设备，应用不同、采样时间完全重叠喵
    now = datetime.now(timezone.utc)
    apps = [("High.exe", "high.exe"), ("Low.exe", "low.exe")]
    for index, (app, package) in enumerate(apps):
        device_id = f"win-lane-pri-{index}"
        connection.execute(
            """
            INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                                 current_app_json, client_version, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?)
            """,
            (device_id, "windows", f"机器{index}", to_utc_text(now), to_utc_text(now)),
        )
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
            (device_id, app, package, to_utc_text(now - timedelta(minutes=5)), 600),
        )
    connection.commit()
    # 高优先级设备放前面喵
    today = now.astimezone().strftime("%Y-%m-%d")
    body = client.get(
        "/api/v1/timeline?devices=win-lane-pri-0,win-lane-pri-1&date=" + today,
        headers=AUTH_HEADERS,
    ).json()
    # 顶层色块只保留高优先级设备那一段喵
    top_apps = {segment["app"] for segment in body["segments"]}
    assert top_apps == {"High.exe"}, "顶层色块没有按优先级裁剪"
    # 喵~注意：这是本条的验收点——应用轴必须能看到低优先级设备的应用喵
    lane_apps = {segment["app"] for segment in body["lane_segments"]}
    assert lane_apps == {"High.exe", "Low.exe"}, "低优先级设备的应用帧丢了"


def test_device_timeline_separates_offline_and_afk(client: TestClient, connection) -> None:
    """时间轴要能区分离线（没心跳）与空档（在线但 AFK）喵。"""
    # 造三条心跳：9 分钟前、8 分钟前（AFK）、刚刚（AFK），中间留一段心跳空窗喵
    now = datetime.now(timezone.utc)
    beats = [
        (now - timedelta(minutes=9), False),
        (now - timedelta(minutes=8), True),
        (now, True),
    ]
    # 先建一台设备，外键才挂得上喵
    connection.execute(
        """
        INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                             current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            "win-presence-0001",
            "windows",
            "心跳测试机",
            "",
            "{}",
            "0.1.0",
            to_utc_text(now - timedelta(minutes=9)),
            to_utc_text(now),
        ),
    )
    for moment, afk in beats:
        # 直接写库，避开上报接口的时间校验喵
        connection.execute(
            "INSERT INTO reports (device_id, reported_at, received_at, payload_json) VALUES (?, ?, ?, ?)",
            ("win-presence-0001", to_utc_text(moment), to_utc_text(moment), json.dumps({"afk": afk})),
        )
    # 插一条使用记录，保证 total_seconds 不为 0 喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
        ("win-presence-0001", "Code.exe", "code.exe", to_utc_text(now - timedelta(minutes=1)), 60),
    )
    connection.commit()
    # 查今天的时间轴喵
    today = now.astimezone().strftime("%Y-%m-%d")
    response = client.get(
        f"/api/v1/devices/win-presence-0001/timeline?date={today}", headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    # 两种状态都要出现喵
    kinds = {item["kind"] for item in body["states"]}
    assert "offline" in kinds
    assert "afk" in kinds
    # 秒数要和状态区间对得上喵
    assert body["offline_seconds"] > 0
    assert body["afk_seconds"] > 0
    assert body["idle_seconds"] == body["afk_seconds"]
    # 心跳超时要带出去，看板据此写说明喵
    # 喵~注意：引用常量而不是写死数字，以后调整超时不会让这条断言失效喵
    assert body["heartbeat_timeout_seconds"] == presence.DEFAULT_HEARTBEAT_TIMEOUT_SECONDS


def test_timeline_segments_carry_device_name(client: TestClient, connection) -> None:
    """多设备合并时，每段要带设备名，泳道才能标出来喵。"""
    # 两台设备各写一条使用记录喵
    now = datetime.now(timezone.utc)
    for index, name in enumerate(("书房主机", "客厅主机")):
        connection.execute(
            """
            INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                                 current_app_json, client_version, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?)
            """,
            (f"win-seg-name-{index}", "windows", name, to_utc_text(now), to_utc_text(now)),
        )
        # 两台设备的采样错开，避免重叠段被优先级裁剪掉喵
        connection.execute(
            "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
            (
                f"win-seg-name-{index}",
                "Code.exe",
                "code.exe",
                to_utc_text(now - timedelta(minutes=8 - index * 3)),
                60,
            ),
        )
    connection.commit()
    # 合并两台设备查时间轴喵
    today = now.astimezone().strftime("%Y-%m-%d")
    body = client.get(
        f"/api/v1/timeline?devices=win-seg-name-0,win-seg-name-1&date={today}", headers=AUTH_HEADERS
    ).json()
    # 两段都要带各自的设备名喵
    names = {segment["device_name"] for segment in body["segments"]}
    assert names == {"书房主机", "客厅主机"}


def test_timeline_returns_title_spans(client: TestClient, connection) -> None:
    """同应用不同窗口标题要压成区间下发，指针悬浮时才能显示标题喵。"""
    # 造两台设备与几条窗口采样喵
    now = datetime.now(timezone.utc)
    connection.execute(
        """
        INSERT INTO devices (device_id, platform, display_name, os_version, hardware_json,
                             current_app_json, client_version, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, '', '{}', NULL, '0.1.0', ?, ?)
        """,
        ("win-title-0001", "windows", "标题测试机", to_utc_text(now), to_utc_text(now)),
    )
    # 同一应用先开 A 文件再开 B 文件，标题应该分成两段喵
    for offset, title in ((20, "a.py - Code"), (18, "a.py - Code"), (10, "b.py - Code"), (8, "b.py - Code")):
        connection.execute(
            "INSERT INTO window_samples (device_id, app_name, package, title, reported_at) VALUES (?, ?, ?, ?, ?)",
            ("win-title-0001", "Code.exe", "code.exe", title, to_utc_text(now - timedelta(minutes=offset))),
        )
    # 插一条使用记录，让时间轴有段喵
    connection.execute(
        "INSERT INTO usage_samples (device_id, app_name, package, sampled_at, seconds) VALUES (?, ?, ?, ?, ?)",
        ("win-title-0001", "Code.exe", "code.exe", to_utc_text(now - timedelta(minutes=15)), 60),
    )
    connection.commit()
    # 查今天的时间轴喵
    today = now.astimezone().strftime("%Y-%m-%d")
    body = client.get(f"/api/v1/devices/win-title-0001/timeline?date={today}", headers=AUTH_HEADERS).json()
    # 两段标题都要在，且按时间从早到晚排序喵
    titles = [span["title"] for span in body["title_spans"]]
    assert titles == ["a.py - Code", "b.py - Code"]
    assert body["title_spans"][0]["app"] == "Code.exe"


def test_people_endpoints_round_trip(client: TestClient) -> None:
    """设备组能存进去再读出来，顺序保持喵。"""
    # 初始应当是空列表喵
    assert client.get("/api/v1/people", headers=AUTH_HEADERS).json()["groups"] == []
    # 保存一组喵
    payload = {"groups": [{"name": "主人", "devices": ["win-1", "and-1"]}]}
    saved = client.put("/api/v1/people", headers=AUTH_HEADERS, json=payload)
    assert saved.status_code == 200
    assert saved.json()["groups"][0]["devices"] == ["win-1", "and-1"]
    # 再读一次喵
    assert client.get("/api/v1/people", headers=AUTH_HEADERS).json()["groups"][0]["name"] == "主人"


def test_people_requires_token(client: TestClient) -> None:
    """设备组接口需要口令喵。"""
    assert client.get("/api/v1/people").status_code == 401
    assert client.put("/api/v1/people", json={"groups": []}).status_code == 401


def test_people_rejects_bad_payload(client: TestClient) -> None:
    """组名为空时返回 422 喵。"""
    response = client.put("/api/v1/people", headers=AUTH_HEADERS, json={"groups": [{"name": "", "devices": []}]})
    assert response.status_code == 422
    assert "invalid_payload" in response.text

# 一张 32x32 的纯色 PNG，用作图标测试数据喵
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAL0lEQVR42u3OIQEAAAgDMOKQicS0ghg3E/Ornr2kEhAQEBAQEBAQEBAQEBAQSAceu3AkiGPmhpIAAAAASUVORK5CYII="
)


def test_icon_upload_requires_token(client: TestClient) -> None:
    """上传图标不带口令应返回 401 喵。"""
    # 不带口令直接传喵
    response = client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "com.tencent.mm", "png_base64": TINY_PNG_BASE64},
    )
    # 状态码应为 401 喵
    assert response.status_code == 401


def test_icon_upload_rejects_bad_base64(client: TestClient) -> None:
    """base64 坏了应返回 422 喵。"""
    # 传一段非法 base64 喵
    response = client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "", "png_base64": "!!!not-base64!!!"},
        headers=AUTH_HEADERS,
    )
    # 状态码应为 422 喵
    assert response.status_code == 422


def test_icon_upload_and_fetch(client: TestClient) -> None:
    """上传后应能按口令取回 PNG 喵。"""
    # 上传喵
    upload = client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "com.tencent.mm", "png_base64": TINY_PNG_BASE64},
        headers=AUTH_HEADERS,
    )
    # 状态码应为 200 喵
    assert upload.status_code == 200
    # 应返回图标键喵
    icon_key = upload.json()["key"]
    # 用请求头取图喵
    fetched = client.get(f"/api/v1/icons/{icon_key}", headers=AUTH_HEADERS)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    # 用查询串取图（给 <img> 用）喵
    fetched_by_query = client.get(f"/api/v1/icons/{icon_key}?token={TEST_INGEST_TOKEN}")
    assert fetched_by_query.status_code == 200
    # 不带口令应被拒绝喵
    assert client.get(f"/api/v1/icons/{icon_key}").status_code == 401


def test_icon_list_returns_entries(client: TestClient) -> None:
    """列表接口应带出应用名与包名喵。"""
    # 先传一张喵
    client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "com.tencent.mm", "png_base64": TINY_PNG_BASE64},
        headers=AUTH_HEADERS,
    )
    # 取列表喵
    response = client.get("/api/v1/icons", headers=AUTH_HEADERS)
    assert response.status_code == 200
    # 应有一条记录喵
    entries = response.json()["icons"]
    assert len(entries) == 1
    assert entries[0]["app"] == "微信"
    assert entries[0]["package"] == "com.tencent.mm"


def test_icon_missing_returns_404(client: TestClient) -> None:
    """不存在的图标键应返回 404 喵。"""
    # 直接查一个不存在的键喵
    response = client.get("/api/v1/icons/deadbeefdeadbeef", headers=AUTH_HEADERS)
    assert response.status_code == 404

def test_icon_upload_swaps_key_and_drops_old_row(client: TestClient) -> None:
    """换图标后键要变、旧行要删，列表里的 content_hash 对应新图喵。"""
    # 先传第一张喵
    first = client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "com.tencent.mm", "png_base64": TINY_PNG_BASE64},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 200
    key_one = first.json()["key"]
    # 再传一张不同的（末尾多一个字节，仍是合法 PNG）喵
    second_png = base64.b64decode(TINY_PNG_BASE64) + b"\x00"
    second = client.post(
        "/api/v1/icons",
        json={
            "app": "微信",
            "package": "com.tencent.mm",
            "png_base64": base64.b64encode(second_png).decode("ascii"),
        },
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    key_two = second.json()["key"]
    # 喵~注意：内容变了键必须变，浏览器才会按新 URL 丢掉旧缓存喵
    assert key_one != key_two
    # 列表只剩一行，哈希与键都对应第二张喵
    entries = client.get("/api/v1/icons", headers=AUTH_HEADERS).json()["icons"]
    assert len(entries) == 1
    assert entries[0]["key"] == key_two
    assert entries[0]["content_hash"] == hashlib.sha1(second_png).hexdigest()[:16]
    # 喵~防御：旧键取不到了，避免看板请求旧 URL 拿到旧图喵
    assert client.get(f"/api/v1/icons/{key_one}", headers=AUTH_HEADERS).status_code == 404
    # 新键能取到新图喵
    assert client.get(f"/api/v1/icons/{key_two}", headers=AUTH_HEADERS).content == second_png


def test_icon_response_is_cacheable_for_30_days(client: TestClient) -> None:
    """图标响应要放宽到 30 天缓存，靠键随内容变来失效喵。"""
    # 传一张喵
    upload = client.post(
        "/api/v1/icons",
        json={"app": "微信", "package": "com.tencent.mm", "png_base64": TINY_PNG_BASE64},
        headers=AUTH_HEADERS,
    )
    # 取图喵
    fetched = client.get(f"/api/v1/icons/{upload.json()['key']}", headers=AUTH_HEADERS)
    # 缓存头必须是 30 天喵
    assert fetched.headers["cache-control"] == "public, max-age=2592000"


def test_report_stores_open_windows(client: TestClient) -> None:
    """上报里的窗口列表要落库并能查回来喵。"""
    # 组装带窗口的负载喵
    payload = make_payload()
    payload["open_windows"] = [
        {"app": "Chrome", "package": "chrome.exe", "title": "看板 - device-hub", "minimized": False, "foreground": True},
        {"app": "记事本", "package": "notepad.exe", "title": "笔记.txt", "minimized": True, "foreground": False},
    ]
    # 先上报喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 200
    # 回显里应带窗口条数喵
    assert response.json()["windows_written"] == 2
    # 再查窗口接口喵
    windows = client.get("/api/v1/devices/win-test-0001/windows", headers=AUTH_HEADERS)
    assert windows.status_code == 200
    body = windows.json()
    assert len(body["windows"]) == 2
    # 前台窗口排在最前喵
    assert body["windows"][0]["app"] == "Chrome"
    assert body["windows"][0]["foreground"] is True
    # 喵~注意：还没上传过图标，键必须是空串，前端会退回色块而不是请求一个假键喵
    assert body["windows"][0]["icon_key"] == ""
    # 传一张 Chrome 的图标喵
    uploaded = client.post(
        "/api/v1/icons",
        json={"app": "Chrome", "package": "chrome.exe", "png_base64": TINY_PNG_BASE64},
        headers=AUTH_HEADERS,
    )
    assert uploaded.status_code == 200
    # 再查一次，这次应当带上真实存在的图标键喵
    body = client.get("/api/v1/devices/win-test-0001/windows", headers=AUTH_HEADERS).json()
    assert body["windows"][0]["icon_key"] == uploaded.json()["key"]
    # 密钥必须真的能取到图，否则前端 404 还是白板喵
    fetched = client.get(f"/api/v1/icons/{body['windows'][0]['icon_key']}?token={TEST_INGEST_TOKEN}")
    assert fetched.status_code == 200
    # 没传图标的那个应用仍然给空串喵
    assert body["windows"][1]["icon_key"] == ""


def test_windows_endpoint_requires_token(client: TestClient) -> None:
    """窗口接口不带口令应返回 401 喵。"""
    assert client.get("/api/v1/devices/win-test-0001/windows").status_code == 401


def test_windows_endpoint_404_for_unknown_device(client: TestClient) -> None:
    """不存在的设备应返回 404 喵。"""
    response = client.get("/api/v1/devices/win-none-9999/windows", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_storage_endpoint_reports_tables(client: TestClient) -> None:
    """存储接口应返回各表行数喵。"""
    # 先写一条上报喵
    client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 查存储喵
    response = client.get("/api/v1/storage", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    # 应有总量与表清单喵
    assert body["total_bytes"] > 0
    names = [table["name"] for table in body["tables"]]
    assert "usage_samples" in names
    assert "window_samples" in names


def test_storage_endpoint_requires_token(client: TestClient) -> None:
    """存储接口不带口令应返回 401 喵。"""
    assert client.get("/api/v1/storage").status_code == 401


def test_storage_cleanup_rejects_bad_days(client: TestClient) -> None:
    """清理天数非法应返回 422 喵。"""
    response = client.post("/api/v1/storage/cleanup", json={"before_days": 0}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_storage_cleanup_keeps_fresh_data(client: TestClient) -> None:
    """清理 30 天前的数据不该动刚写入的记录喵。"""
    # 写一条新数据喵
    client.post("/api/v1/report", json=make_payload(), headers=AUTH_HEADERS)
    # 清理喵
    response = client.post(
        "/api/v1/storage/cleanup",
        json={"before_days": 30, "targets": ["usage_samples"]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    # 新数据不该被删喵
    assert body["deleted"]["usage_samples"] == 0
    assert body["stats"]["total_rows"] > 0


def test_time_endpoint_returns_server_now(client: TestClient) -> None:
    """授时接口应返回服务端时间与来源，且需要口令喵。"""
    # 不带口令应被拒绝喵
    assert client.get("/api/v1/time").status_code == 401
    # 带口令应成功喵
    body = client.get("/api/v1/time", headers=AUTH_HEADERS).json()
    # 时间是 ISO 文本，能被解析喵
    parsed = datetime.fromisoformat(body["server_now"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    # 与本机时间差不超过 5 分钟，说明授时没跑偏喵
    assert abs((parsed - datetime.now(timezone.utc)).total_seconds()) < 300
    # 来源字段必须有值喵
    assert body["source"]


def test_timeline_reports_server_now_and_clock(client: TestClient) -> None:
    """时间轴响应要带服务端"现在"与授时信息，看板据此画现在线喵。"""
    # 造一台设备喵
    now = datetime.now(timezone.utc)
    body = client.get("/api/v1/devices/win-missing-9999/timeline", headers=AUTH_HEADERS).json()
    # 就算没数据也要带这两个字段喵
    assert "server_now" in body
    assert body["clock"]["source"]


def test_report_samples_use_server_time_not_client_time(client: TestClient, connection) -> None:
    """客户端时间离谱时，采样仍要落在服务端时间上喵。"""
    # 客户端谎报 30 天前喵
    bogus_time = (datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0).isoformat()
    payload = make_payload(reported_at=bogus_time)
    # 上报一次喵
    response = client.post("/api/v1/report", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 200
    # 使用时长采样应写在"现在"附近，而不是 30 天前喵
    row = connection.execute(
        "SELECT sampled_at FROM usage_samples WHERE device_id = ? ORDER BY id DESC LIMIT 1",
        (payload["device_id"],),
    ).fetchone()
    assert row is not None
    sampled_at = datetime.fromisoformat(row["sampled_at"].replace("Z", "+00:00"))
    assert abs((sampled_at - datetime.now(timezone.utc)).total_seconds()) < 300
    # 原始上报表仍保留客户端时间，方便排查时钟偏差喵
    report_row = connection.execute(
        "SELECT reported_at FROM reports WHERE device_id = ? ORDER BY id DESC LIMIT 1",
        (payload["device_id"],),
    ).fetchone()
    assert report_row["reported_at"].startswith(bogus_time[:10])


def test_bot_status_reports_channels_and_qqbot_block(client: TestClient) -> None:
    """状态接口要分别给出两个通道的状态与官方通道可见配置喵。"""
    # 请求状态喵
    response = client.get("/api/v1/bot/status", headers=AUTH_HEADERS)
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 测试配置两个通道都关着，所以通道列表为空喵
    assert body["channels"] == []
    # 官方通道配置块必须存在，且不泄露 AppSecret 喵
    assert body["qqbot"]["enabled"] is False
    assert "app_secret" not in body["qqbot"]
    assert body["qqbot"]["app_id"] == ""


def test_bot_command_supports_qqbot_channel(client: TestClient) -> None:
    """命令测试可以指定官方通道，不填群标识时只测渲染喵。"""
    # 指定官方通道跑帮助命令喵
    response = client.post(
        "/api/v1/bot/command",
        json={"text": "/happy帮助", "channel": "qqbot"},
        headers=AUTH_HEADERS,
    )
    # 状态码应为 200 喵
    assert response.status_code == 200
    body = response.json()
    # 应判定为会回复并回显通道名喵
    assert body["replied"] is True
    assert body["channel"] == "qqbot"
    assert "/happy帮助" in body["text"]


def test_bot_command_rejects_unknown_channel(client: TestClient) -> None:
    """通道名写错应直接 422，别让人对着错误结果排查喵。"""
    # 乱填通道名喵
    response = client.post(
        "/api/v1/bot/command",
        json={"text": "/happy帮助", "channel": "telegram"},
        headers=AUTH_HEADERS,
    )
    # 应被拒绝喵
    assert response.status_code == 422


def test_rankings_include_device_seconds(client: TestClient) -> None:
    """排行接口每条记录都要带按设备拆分的秒数，且和等于总时长喵。"""
    # 同一个包名在两台设备上各上报一次喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-split-1",
            display_name="书房主机",
            usage_delta=[{"app": "QQ", "package": "qq.exe", "seconds": 90}],
        ),
        headers=AUTH_HEADERS,
    )
    later = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="and-split-1",
            display_name="手机",
            reported_at=later,
            usage_delta=[{"app": "QQ", "package": "qq.exe", "seconds": 30}],
        ),
        headers=AUTH_HEADERS,
    )
    # 查总排行喵
    body = client.get("/api/v1/rankings?hours=24&limit=10", headers=AUTH_HEADERS).json()
    entry = body["entries"][0]
    # 字段结构固定成 [{"device": ..., "seconds": ...}]，按秒数倒序喵
    assert [item["device"] for item in entry["device_seconds"]] == ["书房主机", "手机"]
    assert [item["seconds"] for item in entry["device_seconds"]] == [90, 30]
    # 拆分之和必须等于总时长，否则条形比例会失真喵
    assert sum(item["seconds"] for item in entry["device_seconds"]) == entry["seconds"]


def test_rankings_groups_include_device_seconds(client: TestClient) -> None:
    """按设备口径的分组条目里也要有按设备拆分的秒数喵。"""
    # 两台设备各一条采样喵
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="win-split-2",
            display_name="书房主机",
            usage_delta=[{"app": "Code.exe", "package": "Code.exe", "seconds": 50}],
        ),
        headers=AUTH_HEADERS,
    )
    later = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    client.post(
        "/api/v1/report",
        json=make_payload(
            device_id="and-split-2",
            display_name="手机",
            reported_at=later,
            usage_delta=[{"app": "QQ", "package": "com.tencent.mobileqq", "seconds": 20}],
        ),
        headers=AUTH_HEADERS,
    )
    # 按设备口径查排行喵
    body = client.get("/api/v1/rankings?hours=24&limit=10&scope=device", headers=AUTH_HEADERS).json()
    # 每组里每条记录都要有拆分，且求和等于自身总时长喵
    for group in body["groups"]:
        for entry in group["entries"]:
            assert entry["device_seconds"], "分组条目缺 device_seconds"
            assert sum(item["seconds"] for item in entry["device_seconds"]) == entry["seconds"]
