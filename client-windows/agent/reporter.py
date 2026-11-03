"""组装上报数据并发送到服务端。

这一层只关心"协议对不对、发没发出去"，不关心采集细节喵。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import base64

import httpx

from .collector import MAX_MIRROR_WINDOWS, ForegroundApp
from .config import AgentConfig

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 客户端版本号，随上报一起发送，方便服务端排查旧版本喵
CLIENT_VERSION = "0.4.1"

# 上报接口路径喵
REPORT_PATH = "/api/v1/report"

# 单次上报最多带多少个窗口喵
MAX_OPEN_WINDOWS = 80

# 应用图标接口路径喵
ICON_PATH = "/api/v1/icons"

# 单次上报允许的最大应用条数，与服务端一致喵
MAX_USAGE_ITEMS = 500


class Reporter:
    """负责把采集结果按协议发出去喵。"""

    def __init__(self, config: AgentConfig, client: httpx.Client | None = None) -> None:
        # 保存配置引用喵
        self._config = config
        # 喵~防御：允许注入测试用客户端，避免单元测试真的发网络请求喵
        self._client = client or httpx.Client(
            timeout=config.request_timeout_seconds,
            verify=config.verify_tls,
        )

    def build_payload(
        self,
        hardware: dict[str, str],
        battery: tuple[int, bool] | None,
        current_app: ForegroundApp | None,
        usage_deltas: list[dict[str, Any]],
        rdp_connected: bool | None = None,
        mirror_windows: list[str] | None = None,
        open_windows: list[Any] | None = None,
        mirror_foreground: bool | None = None,
        afk: bool | None = None,
        afk_since: datetime | None = None,
        active_since: datetime | None = None,
        usage_ended_at: datetime | None = None,
        foreground_missing_seconds: int = 0,
        rdp_target: str | None = None,
        rdp_client_ip: str | None = None,
        rdp_client_name: str | None = None,
        reported_at: str | None = None,
    ) -> dict[str, Any]:
        """按协议组装上报字典喵。

        输入：硬件信息、电量、当前应用、使用时长增量数组、RDP 状态、投屏窗口标题、已打开窗口、
              AFK 标记与两个精确边界时刻、可选的固定上报时刻。
        输出：可直接 JSON 序列化的字典。
        边界：usage_deltas 超过 500 条会被截断；无电量时省略 battery 字段喵。

        喵~注意：`reported_at` 默认取当前时刻，但**重试时必须传入这一批第一次的
        时刻**。服务端拿 `(device_id, reported_at)` 当幂等键，重试时重新取当前
        时刻会被当成新的一批，把同一段秒数再加一遍喵。
        """
        # 组装基础字段喵
        payload: dict[str, Any] = {
            "device_id": self._config.device_id,
            "platform": "windows",
            # 带时区的 ISO 时间，服务端会统一换算成 UTC 喵
            # 喵~注意：给了就用给的，保证重试期间身份不变喵
            "reported_at": reported_at or datetime.now(timezone.utc).isoformat(),
            "hardware": hardware,
            "usage_delta": usage_deltas[:MAX_USAGE_ITEMS],
            "client_version": CLIENT_VERSION,
            # 设备角色交给服务端判定是否门控喵
            "role": self._config.role,
        }
        # 喵~防御：设备名为空时不传该字段，让服务端用 device_id 兜底喵
        if self._config.display_name:
            payload["display_name"] = self._config.display_name
        # 喵~防御：标签为空时不传，避免覆盖服务端已有标签喵
        if self._config.tag:
            payload["tag"] = self._config.tag
        # 喵~防御：台式机没有电池，不传 battery 字段喵
        if battery is not None:
            # 拆成百分比与充电状态喵
            payload["battery"] = {"percent": battery[0], "charging": battery[1]}
        # 喵~防御：没有前台应用时不传 current_app 字段喵
        if current_app is not None:
            payload["current_app"] = {
                "name": current_app.name,
                "package": current_app.package,
                "title": current_app.title,
                "since": current_app.since.isoformat(),
            }
        # 服务器设备才需要上报 RDP 状态与投屏窗口喵
        if rdp_connected is not None:
            payload["rdp_connected"] = bool(rdp_connected)
        if mirror_windows is not None:
            payload["mirror_windows"] = list(mirror_windows)[:MAX_MIRROR_WINDOWS]
        # 投屏窗口是否在前台，服务端据此决定本机与手机各自是否计时喵
        if mirror_foreground is not None:
            payload["mirror_foreground"] = bool(mirror_foreground)
        # 键鼠空闲状态，服务端据此暂停本机与投屏手机的统计喵
        if afk is not None:
            payload["afk"] = bool(afk)
        # 喵~注意：两个边界时刻让服务端把空档量到秒，不再靠整分钟猜喵
        if afk_since is not None:
            payload["afk_since"] = afk_since.astimezone(timezone.utc).isoformat()
        if active_since is not None:
            payload["active_since"] = active_since.astimezone(timezone.utc).isoformat()
        # 喵~注意：这一批使用时长"最后一秒"的真实时刻，服务端按它给色块落位，
        # 上报慢一点也不会整体后移、在前面留出空白喵
        if usage_ended_at is not None:
            payload["usage_ended_at"] = usage_ended_at.astimezone(timezone.utc).isoformat()
        # 喵~防御：抓不到前台的秒数只做观测，0 就不传喵
        if foreground_missing_seconds:
            payload["foreground_missing_seconds"] = int(foreground_missing_seconds)
        # 远程桌面客户端连的目标地址，服务端据此判断该不该由本机计时喵
        if rdp_target:
            payload["rdp_target"] = str(rdp_target)[:200]
        # 服务器角色：连进来的客户端 IP 与机器名，服务端用来确认是自己人喵
        if rdp_client_ip:
            payload["rdp_client_ip"] = str(rdp_client_ip)[:45]
        if rdp_client_name:
            payload["rdp_client_name"] = str(rdp_client_name)[:64]
        # 喵~防御：窗口列表按协议字段名序列化，取不到就整个字段省略喵
        if open_windows:
            payload["open_windows"] = [
                {
                    "app": item.app,
                    "package": item.package,
                    "title": item.title,
                    "minimized": item.minimized,
                    "foreground": item.foreground,
                }
                for item in open_windows[:MAX_OPEN_WINDOWS]
            ]
        return payload

    def send(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """发送一次上报喵。

        输入：已组装好的上报字典。
        输出：(是否成功, 可读说明)。
        边界：网络错误、超时、非 200 响应都返回失败，绝不抛异常给主循环喵。
        """
        # 拼接完整地址，去掉用户可能多写的结尾斜杠喵
        request_url = f"{self._config.server_url.rstrip('/')}{REPORT_PATH}"
        # 组装请求头喵
        request_headers = {
            "X-Ingest-Token": self._config.ingest_token,
            "Content-Type": "application/json",
        }
        try:
            # 发送 POST 请求喵
            response = self._client.post(request_url, json=payload, headers=request_headers)
        except httpx.HTTPError as request_error:
            # 喵~防御：断网、超时、DNS 失败等统一转成可读提示喵
            return False, f"网络请求失败：{request_error}"
        except Exception as error:  # 喵~防御：地址写错、序列化失败等也要变成"失败"而不是抛出喵
            # 抛出去会让主循环把这一批数据丢掉，所以这里一律转成失败喵
            return False, f"请求异常：{error}"
        # 喵~防御：服务端返回非 200 时把响应体前 200 字符带出来，方便排查喵
        if response.status_code != 200:
            return False, f"服务端返回 {response.status_code}：{response.text[:200]}"
        # 成功时记录一条调试日志喵
        LOGGER.debug("上报成功：%s", response.text[:200])
        return True, "上报成功"

    def upload_icon(self, app: str, package: str, png_bytes: bytes) -> tuple[bool, str]:
        """上传一张应用图标喵。

        输入：应用名、包名、PNG 字节。
        输出：(是否成功, 可读说明)。
        边界：网络异常与 4xx/5xx 都返回失败，不抛给调用方喵。
        """
        # 拼接图标接口地址喵
        request_url = f"{self._config.server_url.rstrip('/')}{ICON_PATH}"
        # 组装请求体，PNG 走 base64 塞进 JSON 喵
        payload = {
            "app": app,
            "package": package,
            "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }
        # 组装请求头喵
        request_headers = {"X-Ingest-Token": self._config.ingest_token}
        try:
            # 发送请求喵
            response = self._client.post(request_url, json=payload, headers=request_headers)
        except httpx.HTTPError as request_error:
            # 喵~防御：图标失败不能影响上报喵
            return False, f"网络请求失败：{request_error}"
        # 喵~防御：非 200 视为失败喵
        if response.status_code != 200:
            return False, f"服务端返回 {response.status_code}：{response.text[:200]}"
        return True, "图标上传成功"

    def list_icons(self) -> list[dict[str, Any]]:
        """拉取服务端已有图标列表喵。

        输出：条目列表，每项含 key/app/package。
        边界：网络或解析失败时抛异常，由调用方兜住喵。
        """
        # 拼接图标接口地址喵
        request_url = f"{self._config.server_url.rstrip('/')}{ICON_PATH}"
        # 发送查询请求喵
        response = self._client.get(
            request_url, headers={"X-Ingest-Token": self._config.ingest_token}
        )
        # 喵~防御：状态码不对时抛给调用方处理喵
        response.raise_for_status()
        # 取图标列表喵
        body = response.json()
        return list(body.get("icons", []))

    def close(self) -> None:
        """关闭底层 HTTP 客户端喵。"""
        # 释放连接池喵
        self._client.close()
