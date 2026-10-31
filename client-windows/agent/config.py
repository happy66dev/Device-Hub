"""客户端配置：配置文件 + 命令行覆盖 + 严格校验。

优先级：命令行参数 > 配置文件 > 默认值。
任何不合法配置都会抛出 ConfigError，并在消息里说明怎么改喵。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 默认配置文件名，放在 client-windows 目录下喵
DEFAULT_CONFIG_FILENAME = "config.json"

# 允许的配置字段集合，出现未知字段时报错，避免拼写错误静默生效喵
ALLOWED_KEYS = {
    "server_url",
    "ingest_token",
    "device_id",
    "display_name",
    "sample_interval_seconds",
    "report_interval_seconds",
    "request_timeout_seconds",
    "verify_tls",
    "role",
    "tag",
    "mirror_process_names",
    "afk_threshold_seconds",
}

# 允许的设备角色喵
ALLOWED_ROLES = ("workstation", "server")

# 默认的投屏工具进程名，主人用的是 scrcpy 喵
DEFAULT_MIRROR_PROCESS_NAMES = ("scrcpy.exe",)

# 采集频率默认值（秒）：5 秒一次够准又不费电喵
DEFAULT_SAMPLE_INTERVAL_SECONDS = 5

# 采集频率下限（秒）：再快就是无意义的轮询，CPU 白烧喵
MIN_SAMPLE_INTERVAL_SECONDS = 1

# 采集频率上限（秒）：超过一分钟就分不清两个应用谁在用喵
MAX_SAMPLE_INTERVAL_SECONDS = 60

# 默认上报间隔（秒）：60 秒一批，正好是服务端心跳超时 180 秒的三分之一喵
DEFAULT_REPORT_INTERVAL_SECONDS = 60.0

# 上报间隔下限（秒）：再快就是拿网络换精度，服务端也会被高频请求拖慢喵
MIN_REPORT_INTERVAL_SECONDS = 10.0

# 上报间隔上限（秒）：服务端心跳超时是 180 秒，间隔超过 60 秒就可能被误判成离线喵
MAX_REPORT_INTERVAL_SECONDS = 60.0


class ConfigError(RuntimeError):
    """配置不合法时抛出喵。"""


@dataclass
class AgentConfig:
    """客户端运行配置喵。"""

    # 服务端地址，例如 http://192.168.2.245:8080 喵
    server_url: str = ""
    # 与服务端一致的共享上报口令喵
    ingest_token: str = ""
    # 设备唯一标识，首次启动自动生成后写回配置文件喵
    device_id: str = ""
    # 设备展示名，留空时由服务端用 device_id 兜底喵
    display_name: str = ""
    # 采集频率（秒），1 到 60 的整数，默认 5 秒采一次喵
    sample_interval_seconds: int = DEFAULT_SAMPLE_INTERVAL_SECONDS
    # 上报间隔秒数喵
    report_interval_seconds: float = DEFAULT_REPORT_INTERVAL_SECONDS
    # 单次 HTTP 请求超时秒数喵
    request_timeout_seconds: float = 10.0
    # 是否校验 HTTPS 证书，内网自签证书时可设为 false 喵
    verify_tls: bool = True
    # 设备角色：workstation 常统计；server 只在 RDP 连接时统计喵
    role: str = "workstation"
    # 设备标签，安卓端用来和 scrcpy 窗口标题对上喵
    tag: str = ""
    # 投屏工具进程名列表，用于识别 scrcpy 是否连着手机喵
    mirror_process_names: tuple[str, ...] = DEFAULT_MIRROR_PROCESS_NAMES
    # 无操作多久算离开（AFK），这段时间不计入应用使用喵
    afk_threshold_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        """转成可直接写入 JSON 的字典喵。"""
        # dataclasses.asdict 会递归处理嵌套结构，元组会变成列表喵
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentConfig":
        """从字典构造配置并校验喵。

        输入：配置文件解析出的字典。
        输出：AgentConfig 实例。
        边界：未知字段、类型错误、数值越界都会抛 ConfigError 喵。
        """
        # 喵~防御：配置文件顶层必须是对象喵
        if not isinstance(raw, dict):
            raise ConfigError("配置文件顶层必须是 JSON 对象")
        # 喵~防御：未知字段通常意味着拼写错误，直接报错喵
        unknown_keys = sorted(set(raw) - ALLOWED_KEYS)
        if unknown_keys:
            raise ConfigError(f"配置文件存在未知字段：{', '.join(unknown_keys)}")
        # 构造配置对象喵
        config = cls(
            server_url=str(raw.get("server_url", "")).strip(),
            ingest_token=str(raw.get("ingest_token", "")).strip(),
            device_id=str(raw.get("device_id", "")).strip(),
            display_name=str(raw.get("display_name", "")).strip(),
            sample_interval_seconds=_parse_sample_interval(raw.get("sample_interval_seconds", DEFAULT_SAMPLE_INTERVAL_SECONDS)),
            report_interval_seconds=float(raw.get("report_interval_seconds", DEFAULT_REPORT_INTERVAL_SECONDS)),
            request_timeout_seconds=float(raw.get("request_timeout_seconds", 10.0)),
            verify_tls=bool(raw.get("verify_tls", True)),
            role=str(raw.get("role", "workstation")).strip().lower(),
            tag=str(raw.get("tag", "")).strip()[:64],
            mirror_process_names=_parse_mirror_names(raw.get("mirror_process_names")),
            afk_threshold_seconds=float(raw.get("afk_threshold_seconds", 60.0)),
        )
        # 统一做一次校验喵
        config.validate()
        return config

    def validate(self) -> None:
        """校验关键字段，非法时抛 ConfigError 喵。"""
        # 喵~防御：地址必须带协议头，否则 httpx 无法请求喵
        if not self.server_url.startswith(("http://", "https://")):
            raise ConfigError("server_url 必须以 http:// 或 https:// 开头")
        # 喵~防御：口令太短等于没有保护，与服务端要求保持一致喵
        if len(self.ingest_token) < 8:
            raise ConfigError("ingest_token 至少需要 8 位字符，且必须与服务端一致")
        # 喵~防御：采样间隔过小会明显增加 CPU 占用，过大又会丢应用喵
        if not MIN_SAMPLE_INTERVAL_SECONDS <= self.sample_interval_seconds <= MAX_SAMPLE_INTERVAL_SECONDS:
            raise ConfigError(
                f"sample_interval_seconds 必须是 {MIN_SAMPLE_INTERVAL_SECONDS}–{MAX_SAMPLE_INTERVAL_SECONDS} 之间的整数秒，"
                f"实际是 {self.sample_interval_seconds}"
            )
        # 喵~防御：上报间隔夹在 10–60 秒，太短会压垮服务端、太长会被心跳超时误判离线喵
        if not MIN_REPORT_INTERVAL_SECONDS <= self.report_interval_seconds <= MAX_REPORT_INTERVAL_SECONDS:
            raise ConfigError(
                f"report_interval_seconds 必须是 {MIN_REPORT_INTERVAL_SECONDS:g}–{MAX_REPORT_INTERVAL_SECONDS:g} 秒之间，"
                f"实际是 {self.report_interval_seconds}"
            )
        # 喵~防御：上报间隔不能小于采样间隔，否则每次上报都是空数据喵
        if self.report_interval_seconds < self.sample_interval_seconds:
            raise ConfigError("report_interval_seconds 不能小于 sample_interval_seconds")
        # 喵~防御：超时时间过短会导致内网抖动时频繁失败喵
        if self.request_timeout_seconds < 1:
            raise ConfigError("request_timeout_seconds 不能小于 1 秒")
        # 喵~防御：角色只能是工作站或服务器，写错会让门控失效喵
        if self.role not in ALLOWED_ROLES:
            raise ConfigError(f"role 只能是 {' 或 '.join(ALLOWED_ROLES)}，实际是 {self.role!r}")
        # 喵~防御：AFK 阈值太小时鼠标停顿一下就断档，太大则把挂机时间算进使用时长喵
        if not 60 <= self.afk_threshold_seconds <= 7200:
            raise ConfigError("afk_threshold_seconds 必须在 60–7200 秒之间")


def _parse_sample_interval(value: Any) -> int:
    """解析采集频率喵。

    输入：配置或命令行里的原始值，可能是 int、float、字符串。
    输出：1 到 60 之间的整数秒。
    边界：小数、布尔、非数字文本、越界值都抛 ConfigError 喵。
    """
    # 喵~防御：bool 是 int 的子类，不拦住的话 true 会变成 1 秒喵
    if isinstance(value, bool):
        raise ConfigError("sample_interval_seconds 必须是 1–60 的整数秒，不能是布尔值")
    # 整数直接走范围检查喵
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, float):
        # 喵~防御：5.5 这种小数说明用户理解成浮点了，直接报错而不是悄悄取整喵
        if not value.is_integer():
            raise ConfigError(f"sample_interval_seconds 必须是整数秒，实际是 {value}")
        seconds = int(value)
    elif isinstance(value, str):
        # 喵~防御：文本里必须全是数字喵
        text = value.strip()
        if not text.lstrip("+-").isdigit():
            raise ConfigError(f"sample_interval_seconds 必须是整数秒，实际是 {value!r}")
        seconds = int(text)
    else:
        # 喵~防御：列表、字典之类的类型直接拒绝喵
        raise ConfigError(f"sample_interval_seconds 必须是整数秒，实际是 {type(value).__name__}")
    # 范围检查喵
    if not MIN_SAMPLE_INTERVAL_SECONDS <= seconds <= MAX_SAMPLE_INTERVAL_SECONDS:
        raise ConfigError(
            f"sample_interval_seconds 必须在 {MIN_SAMPLE_INTERVAL_SECONDS}–{MAX_SAMPLE_INTERVAL_SECONDS} 秒之间，实际是 {seconds}"
        )
    return seconds


def _parse_mirror_names(value: Any) -> tuple[str, ...]:
    """解析投屏工具进程名列表喵。

    输入：配置里的原始值，可能是 None、列表。
    输出：进程名元组；None 时返回默认值。
    边界：不是列表、元素不是字符串时抛 ConfigError 喵。
    """
    # 喵~防御：没写这一项时用默认的 scrcpy 喵
    if value is None:
        return DEFAULT_MIRROR_PROCESS_NAMES
    # 喵~防御：写成单个字符串时容易误会，要求改成列表喵
    if not isinstance(value, list):
        raise ConfigError("mirror_process_names 必须是字符串列表，例如 [\"scrcpy.exe\"]")
    # 逐个清洗喵
    cleaned: list[str] = []
    for index, item in enumerate(value):
        # 喵~防御：进程名必须是字符串喵
        if not isinstance(item, str):
            raise ConfigError(f"mirror_process_names[{index}] 必须是字符串")
        # 去掉首尾空白喵
        text = item.strip()
        # 空字符串跳过喵
        if text:
            cleaned.append(text)
    # 返回元组，保持不可变喵
    return tuple(cleaned)


def default_config_path() -> Path:
    """返回默认配置文件路径喵。

    输出：源码运行时是 client-windows 目录；PyInstaller 打包后是 exe 所在目录。
    边界：打包模式下 __file__ 指向临时解压目录，不能用来定位配置喵。
    """
    # 喵~防御：PyInstaller 会把代码解压到临时目录，配置必须跟着 exe 走，否则每次运行都丢配置喵
    if getattr(sys, "frozen", False):
        # 用 exe 自身所在目录喵
        return Path(sys.executable).resolve().parent / DEFAULT_CONFIG_FILENAME
    # 放在 client-windows 目录下，与 agent 包同级喵
    return Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_FILENAME


def load_config(path: Path | None = None) -> AgentConfig:
    """读取配置文件，不存在时返回带默认值的空配置喵。

    输入：可选配置文件路径。
    输出：AgentConfig；文件不存在时返回默认实例（server_url 与 token 为空）。
    边界：JSON 语法错误、字段类型错误、未知字段都会抛 ConfigError 喵。
    """
    # 决定读取哪个文件喵
    resolved_path = path or default_config_path()
    # 喵~防御：文件不存在属于首次运行，返回默认配置让上层用命令行参数补全喵
    if not resolved_path.exists():
        return AgentConfig()
    try:
        # 以 UTF-8 读取，避免中文设备名乱码喵
        raw_text = resolved_path.read_text(encoding="utf-8")
    except OSError as read_error:
        # 喵~防御：权限不足或文件被占用时给出明确提示喵
        raise ConfigError(f"无法读取配置文件 {resolved_path}：{read_error}") from read_error
    try:
        # 解析 JSON 喵
        raw_config = json.loads(raw_text)
    except json.JSONDecodeError as json_error:
        # 喵~防御：JSON 写错时指出位置，方便主人修喵
        raise ConfigError(f"配置文件 {resolved_path} 不是合法 JSON：{json_error}") from json_error
    # 交给 from_dict 做字段校验喵
    return AgentConfig.from_dict(raw_config)


def save_config(config: AgentConfig, path: Path | None = None) -> None:
    """把配置写回文件，用于持久化自动生成的设备 ID 喵。"""
    # 决定写入哪个文件喵
    resolved_path = path or default_config_path()
    # 喵~防御：父目录不存在时先创建喵
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    # 以 UTF-8 写入并保留中文喵
    resolved_path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
