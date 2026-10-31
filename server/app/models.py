"""上报数据的强类型定义。

所有校验都放在这一层：非法数据在进入数据库之前就被挡掉，
避免脏数据污染统计结果喵。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 授时时钟：未来时间校验与服务端落库口径保持一致喵
from .clock import get_clock

# 设备 ID 允许的字符集：小写字母数字开头，可含点、下划线、短横线，最长 64 位喵
DEVICE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"

# 允许的平台取值，其它值一律拒绝喵
PlatformName = Literal["android", "windows"]

# 设备角色：服务器会在 RDP 未连接时暂停统计喵
DeviceRole = Literal["workstation", "server"]

# 投屏窗口标题最多允许的条数，避免恶意撑爆请求体喵
MAX_MIRROR_WINDOWS = 16

# 单次上报最多带多少个窗口，够覆盖正常桌面又不至于把请求撑爆喵
MAX_OPEN_WINDOWS = 80

# 客户端时间最多允许比服务端快 10 分钟，超过视为时钟错乱喵
MAX_FUTURE_SKEW = timedelta(minutes=10)


class BatteryInfo(BaseModel):
    """电量信息，只有 Android 客户端会上报喵。"""

    # 禁止多余字段，客户端多传字段说明协议理解有偏差喵
    model_config = ConfigDict(extra="forbid")

    # 电量百分比，0 到 100 的整数喵
    percent: int = Field(ge=0, le=100)
    # 是否正在充电喵
    charging: bool = False


class CurrentAppInfo(BaseModel):
    """当前前台应用信息喵。"""

    # 禁止多余字段喵
    model_config = ConfigDict(extra="forbid")

    # 应用展示名，例如「微信」喵
    name: str = Field(min_length=1, max_length=128)
    # 包名或进程名，Windows 上是进程名，Android 上是包名喵
    package: str | None = Field(default=None, max_length=200)
    # 窗口标题，Windows 端会带，Android 端为空喵
    title: str | None = Field(default=None, max_length=512)
    # 该应用进入前台的时间，缺省表示客户端未提供喵
    since: datetime | None = None


class UsageDelta(BaseModel):
    """单个应用在两次上报之间新增的前台使用时长喵。"""

    # 禁止多余字段喵
    model_config = ConfigDict(extra="forbid")

    # 应用展示名喵
    app: str = Field(min_length=1, max_length=128)
    # 包名或进程名，Android 上必须带，方便看板区分同名应用喵
    package: str | None = Field(default=None, max_length=200)
    # 新增秒数，0 到 86400（一天），超出说明客户端算法有 bug 喵
    seconds: int = Field(ge=0, le=86400)


class OpenWindow(BaseModel):
    """一台设备上当前打开的一个窗口喵。"""

    # 禁止多余字段喵
    model_config = ConfigDict(extra="forbid")

    # 应用展示名喵
    app: str = Field(min_length=1, max_length=128)
    # 进程名或包名喵
    package: str | None = Field(default=None, max_length=200)
    # 窗口标题，可能为空（例如没有标题的工具窗口）喵
    title: str = Field(default="", max_length=512)
    # 是否最小化喵
    minimized: bool = False
    # 是否处于前台喵
    foreground: bool = False


class ReportPayload(BaseModel):
    """一次完整上报的请求体喵。"""

    # 禁止多余字段，避免客户端升级后悄悄塞入服务端不认识的字段喵
    model_config = ConfigDict(extra="forbid")

    # 设备唯一标识喵
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    # 平台类型喵
    platform: PlatformName
    # 客户端采集时刻，必须带时区喵
    reported_at: datetime
    # 人类可读的设备名，缺省时服务端用 device_id 兜底喵
    display_name: str | None = Field(default=None, max_length=64)
    # 电量信息，Windows 客户端留空喵
    battery: BatteryInfo | None = None
    # 硬件信息键值表，值统一为字符串便于直接渲染喵
    hardware: dict[str, str] | None = None
    # 当前前台应用喵
    current_app: CurrentAppInfo | None = None
    # 使用时长增量列表，单次最多 500 条喵
    usage_delta: list[UsageDelta] | None = Field(default=None, max_length=500)
    # 客户端版本号，方便排查旧版本问题喵
    client_version: str | None = Field(default=None, max_length=32)
    # 设备角色：workstation（默认）或 server，服务器角色只在 RDP 连接时统计喵
    role: DeviceRole | None = None
    # 设备自定义标签，用于把投屏窗口和安卓设备对上喵
    tag: str | None = Field(default=None, max_length=64)
    # 服务器设备专用：当前 RDP 是否处于活动连接喵
    rdp_connected: bool | None = None
    # 服务器设备专用：连进来的 RDP 客户端 IP，服务端据此确认是不是自己的设备喵
    rdp_client_ip: str | None = Field(default=None, max_length=45)
    # 服务器设备专用：连进来的 RDP 客户端机器名（Windows 计算机名）喵
    rdp_client_name: str | None = Field(default=None, max_length=64)
    # 远程桌面客户端连过去的目标地址，服务端据此判断该不该由本机计时喵
    rdp_target: str | None = Field(default=None, max_length=200)
    # 服务器设备专用：scrcpy 投屏窗口的标题列表，服务端据此匹配安卓标签喵
    mirror_windows: list[str] | None = Field(default=None, max_length=MAX_MIRROR_WINDOWS)
    # 投屏窗口是否在前台，服务器自己判定后上报，决定本机与手机各自是否计时喵
    mirror_foreground: bool | None = None
    # 键鼠是否空闲（AFK），客户端判定后上报，服务端据此暂停本机与投屏手机喵
    afk: bool | None = None
    # 当前处于 AFK 时，客户端"停止计时"的那一刻（带时区），用来把空档起点量到秒喵
    afk_since: datetime | None = None
    # 当前没在 AFK 时，客户端"恢复计时"的那一刻（带时区），用来把空档终点量到秒喵
    active_since: datetime | None = None
    # 喵~注意：这一批使用时长里"最后一秒"真实发生的时刻（带时区），
    # 服务端按它给色块落位，上报慢一点也不会整体后移喵
    usage_ended_at: datetime | None = None
    # 本轮"抓不到前台应用"的秒数，纯观测用，便于定位计时缺口喵
    foreground_missing_seconds: int | None = Field(default=None, ge=0, le=86400)
    # 当前打开的所有窗口，Windows 端采集，用于后续的窗口维度分析喵
    open_windows: list[OpenWindow] | None = Field(default=None, max_length=MAX_OPEN_WINDOWS)

    @field_validator("reported_at")
    @classmethod
    def _reported_at_must_have_timezone(cls, value: datetime) -> datetime:
        """要求上报时间带时区，否则无法和 24 小时窗口比较喵。"""
        # 喵~防御：不带时区的时间在不同时区的设备上会产生歧义喵
        if value.tzinfo is None:
            # 抛出明确的中文错误，客户端会看到 detail 喵
            raise ValueError("reported_at 必须带时区，例如 2026-10-29T17:40:00+08:00")
        return value

    @field_validator("afk_since", "active_since", "usage_ended_at")
    @classmethod
    def _boundary_must_have_timezone(cls, value: datetime | None) -> datetime | None:
        """空档边界时刻也必须带时区，否则没法直接拿来画时间轴喵。"""
        # 喵~防御：没传就放过，旧客户端不带这两个字段喵
        if value is None:
            return None
        # 不带时区的时刻直接判错，让客户端补上偏移喵
        if value.tzinfo is None:
            raise ValueError("afk_since / active_since 必须带时区，例如 2026-10-29T17:40:00+08:00")
        return value

    @field_validator("hardware")
    @classmethod
    def _limit_hardware_entries(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """限制硬件信息条数与键长度，防止恶意超长内容喵。"""
        # 喵~防御：没传硬件信息时直接放过喵
        if value is None:
            return None
        # 喵~防御：条数过多会让命令消息爆炸，限制 32 项喵
        if len(value) > 32:
            # 提示客户端裁剪喵
            raise ValueError("hardware 最多 32 项")
        # 逐项检查键名长度喵
        for key, item in value.items():
            # 喵~防御：空键名或超长键名无法渲染喵
            if not key or len(key) > 32:
                # 指出具体出错的键喵
                raise ValueError(f"hardware 的键名必须在 1 到 32 字符之间，实际是 {key!r}")
            # 喵~防御：值超长会撑爆消息，限制 200 字符喵
            if len(item) > 200:
                # 指出具体出错的键喵
                raise ValueError(f"hardware 的键 {key} 对应的值超过 200 字符")
        return value

    @field_validator("mirror_windows")
    @classmethod
    def _clean_mirror_windows(cls, value: list[str] | None) -> list[str] | None:
        """清洗投屏窗口标题，去掉空串与超长内容喵。"""
        # 喵~防御：没传就放过喵
        if value is None:
            return None
        # 逐条清洗喵
        cleaned: list[str] = []
        for item in value:
            # 喵~防御：非字符串说明客户端类型错了喵
            if not isinstance(item, str):
                raise ValueError("mirror_windows 的每一项都必须是字符串")
            # 去掉首尾空白喵
            text = item.strip()
            # 喵~防御：空标题没有匹配价值喵
            if not text:
                continue
            # 喵~防御：超长标题会撑爆响应，截断到 200 字符喵
            cleaned.append(text[:200])
        return cleaned

    @model_validator(mode="after")
    def _reject_future_timestamp(self) -> "ReportPayload":
        """拒绝明显来自未来的时间，避免污染 24 小时统计喵。"""
        # 换算到 UTC 后与当前时间比较喵
        reported_utc = self.reported_at.astimezone(timezone.utc)
        # 当前 UTC 时间（走授时时钟，和落库口径一致）喵
        now_utc = get_clock().now()
        # 喵~防御：时钟快太多会让"最近上报"排序错乱，直接拒绝喵
        if reported_utc - now_utc > MAX_FUTURE_SKEW:
            # 提示客户端校准时间喵
            raise ValueError("reported_at 比服务端时间快超过 10 分钟，请校准客户端时钟")
        return self
