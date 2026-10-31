"""服务端配置加载模块。

设计原则：
1. 关键安全字段（上报 token、NapCat token）缺失时直接报错，绝不静默使用空口令喵。
2. 其余字段缺失时使用保守默认值，保证配置写得粗糙也能启动喵。
3. 配置里出现未知字段时报错，避免主人拼错键名却以为已经生效喵。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 模块日志器，用于输出不影响启动的配置提醒喵
LOGGER = logging.getLogger("device_hub")

# 允许通过环境变量指定配置文件路径，方便以后做多环境部署喵
CONFIG_ENV_NAME = "DEVICE_HUB_CONFIG"


class ConfigError(RuntimeError):
    """配置不合法时抛出，消息里带字段路径，方便主人一眼定位喵。"""


@dataclass(frozen=True)
class ServerSection:
    """HTTP 服务监听参数喵。"""

    # 监听地址，0.0.0.0 表示局域网和 Tailscale 都能访问喵
    host: str = "0.0.0.0"
    # 监听端口喵
    port: int = 8080
    # SQLite 数据库文件绝对路径，加载配置时已按配置文件目录解析成绝对路径喵
    db_path: Path = Path("data/device_hub.db")
    # 日志级别字符串喵
    log_level: str = "info"


@dataclass(frozen=True)
class IngestSection:
    """客户端上报相关参数喵。"""

    # 上报共享口令，客户端必须在请求头里带上它喵
    token: str = ""
    # 单个请求体允许的最大字节数喵
    max_payload_bytes: int = 262144


@dataclass(frozen=True)
class RetentionSection:
    """数据保留策略喵。"""

    # 原始上报记录保留天数喵
    detail_days: int = 7
    # 使用时长与电量聚合数据保留天数喵
    aggregate_days: int = 30


@dataclass(frozen=True)
class NapCatSection:
    """QQ 机器人（OneBot 11）连接参数喵。"""

    # 是否随服务端启动机器人喵
    enabled: bool = True
    # NapCat 正向 WebSocket 地址喵
    ws_url: str = "ws://127.0.0.1:7999"
    # 与 NapCat 侧一致的访问口令喵
    token: str = ""
    # 断线重连间隔秒数喵
    reconnect_seconds: int = 10
    # 机器人自己的 QQ 号，用于识别消息里是否 @ 了自己喵
    self_qq: str = ""


@dataclass(frozen=True)
class AclSection:
    """访问控制：白名单群 + 黑名单用户喵。

    NapCat 与官方 QQ Bot 是两套命名空间：前者是整数群号 / QQ 号，
    后者是 openid 字符串，混用会静默失效，所以分开放喵。
    """

    # 允许响应的群号元组，空元组表示任何群都不响应喵
    whitelist_groups: tuple[int, ...] = ()
    # 禁止使用命令的 QQ 号元组喵
    blacklist_users: tuple[int, ...] = ()
    # 官方通道允许响应的 group_openid 元组喵
    whitelist_group_openids: tuple[str, ...] = ()
    # 官方通道禁止使用的 member_openid 元组喵
    blacklist_member_openids: tuple[str, ...] = ()
    # 官方通道允许私聊的 user_openid 元组，留空表示私聊一律不响应喵
    private_user_openids: tuple[str, ...] = ()

    def for_channel(self, channel: str) -> "AclView":
        """取某个通道生效的访问控制，统一成字符串比较喵。"""
        # 官方通道用 openid 命名空间喵
        if channel == "qqbot":
            return AclView(
                whitelist_groups=self.whitelist_group_openids,
                blacklist_users=self.blacklist_member_openids,
                private_users=self.private_user_openids,
            )
        # 其余按 NapCat 的整数命名空间转字符串喵
        return AclView(
            whitelist_groups=tuple(str(group_id) for group_id in self.whitelist_groups),
            blacklist_users=tuple(str(user_id) for user_id in self.blacklist_users),
            private_users=(),
        )


@dataclass(frozen=True)
class AclView:
    """某个通道视角下的访问控制，全部是字符串喵。"""

    # 允许的群会话标识喵
    whitelist_groups: tuple[str, ...] = ()
    # 禁止的用户标识喵
    blacklist_users: tuple[str, ...] = ()
    # 允许私聊的用户标识喵
    private_users: tuple[str, ...] = ()


@dataclass(frozen=True)
class QQBotSection:
    """官方 QQ Bot（api.bot.qq.com）连接参数喵。"""

    # 是否启用官方通道，默认关闭，避免没填凭据时报错喵
    enabled: bool = False
    # 开放平台 AppID 喵
    app_id: str = ""
    # 开放平台 AppSecret 喵
    app_secret: str = ""
    # 业务接口根地址，沙箱环境可换成 sandbox.api.sgroup.qq.com 喵
    api_base: str = "https://api.bot.qq.com"
    # 订阅的事件位，默认只要群 + 单聊事件喵
    intents: int = 33554432
    # access_token 提前刷新窗口秒数喵
    token_refresh_margin_seconds: int = 60
    # 心跳提前量秒数，避免卡在边界上喵
    heartbeat_slack_seconds: int = 5
    # 单次 HTTP 请求超时秒数喵
    request_timeout_seconds: float = 10.0
    # 断线重连间隔秒数喵
    reconnect_seconds: int = 10
    # 是否把收到的 openid 打进日志，用于采集白名单喵
    log_openids: bool = True
    # 允许免 @ 触发的群 openid，留空表示所有群都要求 @ 喵
    free_command_group_openids: tuple[str, ...] = ()
    # 免 @ 时是否仍要求命令前缀喵
    free_command_require_prefix: bool = True
    # 免 @ 时的最低角色：any / admin / owner 喵
    free_command_min_role: str = "any"
    # 是否把收到的原始事件与准入结论打进日志，排查「@ 了却不回复」用喵
    debug_events: bool = False


@dataclass(frozen=True)
class RenderSection:
    """命令结果渲染参数喵。"""

    # 设备详情最多展示的硬件条目数喵
    max_hardware_fields: int = 8
    # 是否允许把命令结果渲染成图片喵
    image_enabled: bool = True


@dataclass(frozen=True)
class RolesSection:
    """设备角色标记，服务器端配置优先于客户端自报喵。"""

    # 强制标记为服务器的设备 ID 元组喵
    servers: tuple[str, ...] = ()
    # 强制标记为工作站的设备 ID 元组（可用来纠正客户端自报）喵
    workstations: tuple[str, ...] = ()


@dataclass(frozen=True)
class GatingSection:
    """统计门控参数喵。"""

    # 是否启用门控喵
    enabled: bool = True
    # RDP 状态有效期秒数，超过后视为状态不可信喵
    rdp_stale_seconds: int = 180
    # 是否启用远程桌面目标校验：连到自己人就由那台设备计时喵
    rdp_require_known_client: bool = True
    # 手动放行的目标地址 / 机器名，按自己人处理喵
    rdp_allowed_clients: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClockSection:
    """授时参数：默认走阿里云 NTP 喵。"""

    # 是否启用授时，关掉就用本机时钟喵
    enabled: bool = True
    # 授时服务器列表，按顺序尝试喵
    servers: tuple[str, ...] = ()
    # 对齐间隔秒数喵
    sync_interval_seconds: int = 1800
    # 单次握手超时秒数喵
    timeout_seconds: float = 2.0

@dataclass(frozen=True)
class AppConfig:
    """整个服务端的配置集合喵。"""

    # HTTP 服务参数喵
    server: ServerSection
    # 上报参数喵
    ingest: IngestSection
    # 数据保留策略喵
    retention: RetentionSection
    # 机器人连接参数喵
    napcat: NapCatSection
    # 访问控制喵
    acl: AclSection
    # 渲染参数喵
    render: RenderSection
    # 设备角色标记喵
    roles: RolesSection
    # 统计门控参数喵
    gating: GatingSection
    # 配置文件所在目录，用于解析相对路径喵
    base_dir: Path
    # 授时参数（带默认值，方便测试只传关心的字段）喵
    clock: ClockSection = field(default_factory=ClockSection)
    # 官方 QQ Bot 通道参数（带默认值，默认关闭）喵
    qqbot: QQBotSection = field(default_factory=QQBotSection)

    def gating_settings(self) -> "GatingSettings":
        """把配置转成门控模块需要的设置对象喵。"""
        # 局部导入，避免配置模块与门控模块互相 import 造成循环喵
        from .gating import GatingSettings

        # 逐字段映射喵
        return GatingSettings(
            enabled=self.gating.enabled,
            rdp_stale_seconds=self.gating.rdp_stale_seconds,
            servers=self.roles.servers,
            workstations=self.roles.workstations,
            rdp_require_known_client=self.gating.rdp_require_known_client,
            rdp_allowed_clients=self.gating.rdp_allowed_clients,
        )


def _read_section(raw_config: dict[str, Any], section_name: str, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    """取出配置里的某一节，并检查字段名是否拼错喵。

    输入：整个 YAML 字典、节名、该节允许出现的键。
    输出：该节的键值对字典，缺省时返回空字典。
    边界：该节不是字典、出现未知键时抛 ConfigError。
    """
    # 没写这一节时返回空字典，让上层用默认值兜底喵
    section_raw = raw_config.get(section_name, {})
    # 喵~防御：整节被写成字符串或列表，说明 YAML 缩进错了，必须报错而不是静默忽略喵
    if section_raw is None:
        # YAML 里写了 `server:` 但没写任何子项时会得到 None，按空配置处理喵
        return {}
    if not isinstance(section_raw, dict):
        # 喵~防御：类型完全不对，直接指出实际类型喵
        raise ConfigError(f"配置节 {section_name} 必须是键值对，实际是 {type(section_raw).__name__}")
    # 收集写错的键名喵
    unknown_keys = sorted(key for key in section_raw if key not in allowed_keys)
    if unknown_keys:
        # 喵~防御：拼错的键会被静默忽略，这里主动报错提醒主人喵
        raise ConfigError(f"配置节 {section_name} 存在未知字段：{', '.join(unknown_keys)}，请检查拼写")
    return section_raw


def _as_str(section: dict[str, Any], section_name: str, key: str, default: str) -> str:
    """读取字符串字段，缺省时用默认值喵。"""
    # 取不到就用默认值喵
    value = section.get(key, default)
    # 喵~防御：YAML 里写成数字或布尔值时类型不对，直接报错喵
    if not isinstance(value, str):
        # 报错信息带上完整字段路径喵
        raise ConfigError(f"{section_name}.{key} 必须是字符串，实际是 {type(value).__name__}")
    return value


def _as_int(
    section: dict[str, Any],
    section_name: str,
    key: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """读取整数字段并做范围校验喵。"""
    # 取不到就用默认值喵
    value = section.get(key, default)
    # 喵~防御：Python 里 True 是 int 的子类，必须单独挡掉，否则 true 会被当成 1 喵
    if isinstance(value, bool) or not isinstance(value, int):
        # 类型不对直接报错喵
        raise ConfigError(f"{section_name}.{key} 必须是整数，实际是 {type(value).__name__}")
    # 下限校验喵
    if minimum is not None and value < minimum:
        # 喵~防御：端口、天数这类字段小于下限会让服务端行为异常喵
        raise ConfigError(f"{section_name}.{key} 不能小于 {minimum}，实际是 {value}")
    # 上限校验喵
    if maximum is not None and value > maximum:
        # 喵~防御：超过上限通常意味着填错了单位（例如把秒当分钟）喵
        raise ConfigError(f"{section_name}.{key} 不能大于 {maximum}，实际是 {value}")
    return value


def _as_float(
    section: dict[str, Any],
    section_name: str,
    key: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """读取浮点字段并做范围校验喵。"""
    # 取不到就用默认值喵
    value = section.get(key, default)
    # 喵~防御：布尔值会被当成 0/1，先挡掉再判类型喵
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # 类型不对直接报错喵
        raise ConfigError(f"{section_name}.{key} 必须是数字，实际是 {type(value).__name__}")
    # 统一转成浮点喵
    number = float(value)
    # 下限校验喵
    if minimum is not None and number < minimum:
        # 喵~防御：超时给 0 会让授时永远失败喵
        raise ConfigError(f"{section_name}.{key} 不能小于 {minimum}，实际是 {number}")
    # 上限校验喵
    if maximum is not None and number > maximum:
        # 喵~防御：超时太大等于把上报线程挂死喵
        raise ConfigError(f"{section_name}.{key} 不能大于 {maximum}，实际是 {number}")
    return number


def _as_bool(section: dict[str, Any], section_name: str, key: str, default: bool) -> bool:
    """读取布尔字段，缺省时用默认值喵。"""
    # 取不到就用默认值喵
    value = section.get(key, default)
    # 喵~防御：写成 "true" 字符串时严格报错，避免出现"以为关了其实没关"的情况喵
    if not isinstance(value, bool):
        # 类型不对直接报错喵
        raise ConfigError(f"{section_name}.{key} 必须是 true 或 false，实际是 {type(value).__name__}")
    return value


def _as_int_tuple(section: dict[str, Any], section_name: str, key: str) -> tuple[int, ...]:
    """读取 QQ 号/群号列表，逐个校验为正整数喵。"""
    # 取不到就用空列表，表示不限制也不放行喵
    value = section.get(key, [])
    # 喵~防御：写成单个数字而不是列表时容易误会，直接报错要求改成列表喵
    if not isinstance(value, list):
        # 报错信息提示正确写法喵
        raise ConfigError(f"{section_name}.{key} 必须是列表，例如 [123456]，实际是 {type(value).__name__}")
    # 逐个元素校验后收集喵
    collected: list[int] = []
    for index, item in enumerate(value):
        # 喵~防御：QQ 号必须是正整数，字符串 "123" 或 0 都属于配置错误喵
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            # 报错信息带上出错的下标喵
            raise ConfigError(f"{section_name}.{key}[{index}] 必须是正整数 QQ 号或群号，实际是 {item!r}")
        # 校验通过后加入结果喵
        collected.append(item)
    return tuple(collected)


def _as_device_id_tuple(section: dict[str, Any], section_name: str, key: str) -> tuple[str, ...]:
    """读取设备 ID 列表并做基本校验喵。"""
    # 取不到就用空列表喵
    value = section.get(key, [])
    # 喵~防御：写成单个字符串时容易误会，要求改成列表喵
    if not isinstance(value, list):
        raise ConfigError(f"{section_name}.{key} 必须是列表，例如 [win-abc-1234]，实际是 {type(value).__name__}")
    # 逐个元素校验喵
    collected: list[str] = []
    for index, item in enumerate(value):
        # 喵~防御：设备 ID 必须是字符串喵
        if not isinstance(item, str):
            raise ConfigError(f"{section_name}.{key}[{index}] 必须是字符串设备 ID，实际是 {type(item).__name__}")
        # 统一小写并去空白，与服务端设备 ID 规范一致喵
        cleaned = item.strip().lower()
        # 喵~防御：空 ID 或超长 ID 都无法匹配到设备喵
        if not cleaned or len(cleaned) > 64:
            raise ConfigError(f"{section_name}.{key}[{index}] 长度必须在 1 到 64 个字符之间")
        # 校验通过后收集喵
        collected.append(cleaned)
    return tuple(collected)


def _as_str_tuple(section: dict[str, Any], section_name: str, key: str) -> tuple[str, ...]:
    """读取字符串列表（例如放行的客户端 IP / 机器名）喵。"""
    # 取不到就用空列表喵
    value = section.get(key, [])
    # 喵~防御：写成单个字符串时容易误会，要求改成列表喵
    if not isinstance(value, list):
        raise ConfigError(f"{section_name}.{key} 必须是列表，例如 [\"192.168.2.10\"]，实际是 {type(value).__name__}")
    # 逐个元素校验喵
    collected: list[str] = []
    for index, item in enumerate(value):
        # 喵~防御：每一项都必须是字符串喵
        if not isinstance(item, str):
            raise ConfigError(f"{section_name}.{key}[{index}] 必须是字符串，实际是 {type(item).__name__}")
        # 去掉首尾空白喵
        cleaned = item.strip()
        # 空字符串跳过喵
        if cleaned:
            collected.append(cleaned)
    return tuple(collected)


def _resolve_config_path(config_path: str | Path | None) -> Path:
    """决定本次加载哪个配置文件喵。

    优先级：显式传入 > 环境变量 DEVICE_HUB_CONFIG > 包目录上一级的 config.yaml。
    """
    # 显式传入时直接使用喵
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    # 环境变量次之，便于部署时切换配置喵
    env_value = os.environ.get(CONFIG_ENV_NAME)
    if env_value:
        # 环境变量同样支持 ~ 展开喵
        return Path(env_value).expanduser().resolve()
    # 默认取 server/config.yaml，即本文件所在 app 目录的上一级喵
    return (Path(__file__).resolve().parent.parent / "config.yaml").resolve()


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """对外暴露的配置路径解析，供设置页显示与写回配置喵。

    输入：可选的显式路径。
    输出：绝对路径。
    边界：与 load_config 用的是同一套优先级，保证「读的」和「写的」是同一个文件喵。
    """
    # 直接复用内部实现，避免两处规则漂移喵
    return _resolve_config_path(config_path)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """读取并校验配置文件，返回不可变的配置对象喵。

    输入：可选的配置文件路径。
    输出：AppConfig 实例。
    边界：文件不存在、YAML 语法错误、字段类型错误、安全字段缺失都会抛 ConfigError。
    """
    # 先确定配置文件位置喵
    resolved_path = _resolve_config_path(config_path)
    try:
        # 喵~防御：文件不存在或没有读权限时抛 OSError，这里统一转成配置错误喵
        raw_text = resolved_path.read_text(encoding="utf-8")
    except OSError as read_error:
        # 报错信息带上完整路径，方便主人确认是不是路径写错喵
        raise ConfigError(f"无法读取配置文件 {resolved_path}：{read_error}") from read_error
    try:
        # 用 safe_load 只解析基础类型，避免执行任意 Python 对象构造喵
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as yaml_error:
        # 喵~防御：YAML 缩进错误是最常见的配置事故，必须明确指出喵
        raise ConfigError(f"配置文件 {resolved_path} 不是合法 YAML：{yaml_error}") from yaml_error
    # 喵~防御：空文件会被解析成 None，这里当成空字典处理喵
    raw_config: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
    if parsed is not None and not isinstance(parsed, dict):
        # 顶层不是键值对说明结构完全错了喵
        raise ConfigError(f"配置文件 {resolved_path} 顶层必须是键值对")

    # 逐节读取并校验喵
    server_raw = _read_section(raw_config, "server", ("host", "port", "db_path", "log_level"))
    ingest_raw = _read_section(raw_config, "ingest", ("token", "max_payload_bytes"))
    retention_raw = _read_section(raw_config, "retention", ("detail_days", "aggregate_days"))
    napcat_raw = _read_section(raw_config, "napcat", ("enabled", "ws_url", "token", "reconnect_seconds", "self_qq"))
    acl_raw = _read_section(raw_config, "acl", ("whitelist_groups", "blacklist_users", "whitelist_group_openids", "blacklist_member_openids", "private_user_openids"))
    qqbot_raw = _read_section(raw_config, "qqbot", ("enabled", "app_id", "app_secret", "api_base", "intents", "token_refresh_margin_seconds", "heartbeat_slack_seconds", "request_timeout_seconds", "reconnect_seconds", "log_openids", "free_command_group_openids", "free_command_require_prefix", "free_command_min_role", "debug_events"))
    render_raw = _read_section(raw_config, "render", ("max_hardware_fields", "image_enabled"))
    roles_raw = _read_section(raw_config, "roles", ("servers", "workstations"))
    gating_raw = _read_section(raw_config, "gating", ("enabled", "rdp_stale_seconds", "rdp_require_known_client", "rdp_allowed_clients"))
    clock_raw = _read_section(raw_config, "clock", ("enabled", "servers", "sync_interval_seconds", "timeout_seconds"))

    # 数据库路径按配置文件所在目录解析，保证从任何工作目录启动都指向同一个库喵
    raw_db_path = _as_str(server_raw, "server", "db_path", "data/device_hub.db")
    db_path_candidate = Path(raw_db_path).expanduser()
    if not db_path_candidate.is_absolute():
        # 相对路径一律相对于配置文件目录喵
        db_path_candidate = (resolved_path.parent / db_path_candidate).resolve()
    # 组装 HTTP 服务配置喵
    server_section = ServerSection(
        host=_as_str(server_raw, "server", "host", "0.0.0.0"),
        port=_as_int(server_raw, "server", "port", 8080, minimum=1, maximum=65535),
        db_path=db_path_candidate,
        log_level=_as_str(server_raw, "server", "log_level", "info"),
    )
    # 组装上报配置喵
    ingest_section = IngestSection(
        token=_as_str(ingest_raw, "ingest", "token", ""),
        max_payload_bytes=_as_int(ingest_raw, "ingest", "max_payload_bytes", 262144, minimum=1024, maximum=16 * 1024 * 1024),
    )
    # 组装保留策略喵
    retention_section = RetentionSection(
        detail_days=_as_int(retention_raw, "retention", "detail_days", 7, minimum=1, maximum=365),
        aggregate_days=_as_int(retention_raw, "retention", "aggregate_days", 30, minimum=1, maximum=3650),
    )
    # 组装机器人连接配置喵
    napcat_section = NapCatSection(
        enabled=_as_bool(napcat_raw, "napcat", "enabled", True),
        ws_url=_as_str(napcat_raw, "napcat", "ws_url", "ws://127.0.0.1:7999"),
        token=_as_str(napcat_raw, "napcat", "token", ""),
        reconnect_seconds=_as_int(napcat_raw, "napcat", "reconnect_seconds", 10, minimum=1, maximum=600),
        self_qq=_as_str(napcat_raw, "napcat", "self_qq", ""),
    )
    # 组装访问控制配置喵
    acl_section = AclSection(
        whitelist_groups=_as_int_tuple(acl_raw, "acl", "whitelist_groups"),
        blacklist_users=_as_int_tuple(acl_raw, "acl", "blacklist_users"),
        whitelist_group_openids=_as_str_tuple(acl_raw, "acl", "whitelist_group_openids"),
        blacklist_member_openids=_as_str_tuple(acl_raw, "acl", "blacklist_member_openids"),
        private_user_openids=_as_str_tuple(acl_raw, "acl", "private_user_openids"),
    )
    # 组装官方 QQ Bot 配置喵
    qqbot_section = QQBotSection(
        enabled=_as_bool(qqbot_raw, "qqbot", "enabled", False),
        app_id=_as_str(qqbot_raw, "qqbot", "app_id", ""),
        app_secret=_as_str(qqbot_raw, "qqbot", "app_secret", ""),
        api_base=_as_str(qqbot_raw, "qqbot", "api_base", "https://api.bot.qq.com"),
        intents=_as_int(qqbot_raw, "qqbot", "intents", 33554432, minimum=1, maximum=2**53),
        token_refresh_margin_seconds=_as_int(qqbot_raw, "qqbot", "token_refresh_margin_seconds", 60, minimum=0, maximum=600),
        heartbeat_slack_seconds=_as_int(qqbot_raw, "qqbot", "heartbeat_slack_seconds", 5, minimum=0, maximum=60),
        request_timeout_seconds=_as_float(qqbot_raw, "qqbot", "request_timeout_seconds", 10.0, minimum=1.0, maximum=120.0),
        reconnect_seconds=_as_int(qqbot_raw, "qqbot", "reconnect_seconds", 10, minimum=1, maximum=600),
        log_openids=_as_bool(qqbot_raw, "qqbot", "log_openids", True),
        free_command_group_openids=_as_str_tuple(qqbot_raw, "qqbot", "free_command_group_openids"),
        free_command_require_prefix=_as_bool(qqbot_raw, "qqbot", "free_command_require_prefix", True),
        free_command_min_role=_as_str(qqbot_raw, "qqbot", "free_command_min_role", "any"),
        debug_events=_as_bool(qqbot_raw, "qqbot", "debug_events", False),
    )
    # 组装渲染配置喵
    render_section = RenderSection(
        max_hardware_fields=_as_int(render_raw, "render", "max_hardware_fields", 8, minimum=1, maximum=32),
        image_enabled=_as_bool(render_raw, "render", "image_enabled", True),
    )
    # 组装设备角色配置喵
    roles_section = RolesSection(
        servers=_as_device_id_tuple(roles_raw, "roles", "servers"),
        workstations=_as_device_id_tuple(roles_raw, "roles", "workstations"),
    )
    # 组装门控配置喵
    gating_section = GatingSection(
        enabled=_as_bool(gating_raw, "gating", "enabled", True),
        rdp_stale_seconds=_as_int(gating_raw, "gating", "rdp_stale_seconds", 180, minimum=30, maximum=3600),
        rdp_require_known_client=_as_bool(gating_raw, "gating", "rdp_require_known_client", True),
        rdp_allowed_clients=_as_str_tuple(gating_raw, "gating", "rdp_allowed_clients"),
    )

    # 授时默认走阿里云公共 NTP，服务器列表为空时用模块内置清单喵
    clock_section = ClockSection(
        enabled=_as_bool(clock_raw, "clock", "enabled", True),
        servers=_as_str_tuple(clock_raw, "clock", "servers"),
        sync_interval_seconds=_as_int(clock_raw, "clock", "sync_interval_seconds", 1800, minimum=60, maximum=86400),
        timeout_seconds=_as_float(clock_raw, "clock", "timeout_seconds", 2.0, minimum=0.2, maximum=10.0),
    )

    # 喵~防御：上报口令太短等于没有口令，白名单群之外任何人都能伪造数据喵
    if len(ingest_section.token) < 8:
        # 提示主人改成随机长串喵
        raise ConfigError("ingest.token 至少需要 8 位字符，请在 config.yaml 里改成随机长串")
    # 喵~防御：机器人开着却没有 token，NapCat 会直接拒绝连接，与其运行时报错不如启动时报错喵
    if napcat_section.enabled and not napcat_section.token:
        # 提示补 token 或关掉机器人喵
        raise ConfigError("napcat.enabled 为 true 时必须配置 napcat.token，或把它设为 false 暂时不启用机器人")
    # 喵~防御：白名单为空时机器人不会响应任何群，属于常见"没反应"原因，这里只提示不报错喵
    if not acl_section.whitelist_groups:
        # 用警告日志而不是异常，允许主人先启动服务端再补群号；对外文案保持中性喵
        LOGGER.warning("acl.whitelist_groups 为空，机器人不会在任何群响应命令")
    # 喵~防御：官方通道开着却没有凭据，连网关都取不到，启动时就该拦下喵
    if qqbot_section.enabled and not (qqbot_section.app_id and qqbot_section.app_secret):
        # 提示补 AppID / AppSecret 或关掉官方通道喵
        raise ConfigError("qqbot.enabled 为 true 时必须配置 qqbot.app_id 与 qqbot.app_secret，或把它设为 false")
    # 喵~防御：免 @ 角色门槛只认三个值，写错了会静默失效喵
    if qqbot_section.free_command_min_role not in ("any", "admin", "owner"):
        # 明确报错，别让主人对着配置猜喵
        raise ConfigError("qqbot.free_command_min_role 只能是 any / admin / owner")
    # 喵~防御：官方通道的白名单是 openid，为空时群里 @ 机器人也不会响应喵
    if qqbot_section.enabled and not (acl_section.whitelist_group_openids or acl_section.private_user_openids):
        # 只告警不报错，允许先启动再从日志里抄 openid 喵
        LOGGER.warning("acl.whitelist_group_openids 为空，官方 QQ Bot 不会在任何群响应命令（可从日志里抄 group_openid）")
    # 喵~防御：intents 里没有群事件位时永远收不到群消息，属于典型配置事故喵
    if qqbot_section.enabled and not qqbot_section.intents & (1 << 25):
        # 只告警，留出主人自选事件位的空间喵
        LOGGER.warning("qqbot.intents 未包含 1<<25（GROUP_AND_C2C_EVENT），群里 @ 机器人不会有任何事件")

    # 返回不可变配置对象喵
    return AppConfig(
        server=server_section,
        ingest=ingest_section,
        retention=retention_section,
        napcat=napcat_section,
        acl=acl_section,
        render=render_section,
        roles=roles_section,
        gating=gating_section,
        clock=clock_section,
        qqbot=qqbot_section,
        base_dir=resolved_path.parent,
    )
