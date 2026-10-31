"""主循环与命令行入口。

用法示例：
    python -m agent --server http://192.168.2.245:8080 --token 你的口令
    python -m agent --once --dry-run     # 只打印一条上报内容，不发送
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from .console import attach_console, show_error
from .collector import (
    ForegroundApp,
    collect_hardware,
    detect_rdp_active,
    exe_path_map,
    rdp_client_info,
    get_foreground_app,
    idle_seconds,
    list_mirror_windows,
    list_open_windows,
    read_battery,
    session_locked,
)
from .config import (
    AgentConfig,
    ConfigError,
    MAX_REPORT_INTERVAL_SECONDS,
    MAX_SAMPLE_INTERVAL_SECONDS,
    MIN_REPORT_INTERVAL_SECONDS,
    MIN_SAMPLE_INTERVAL_SECONDS,
    default_config_path,
    load_config,
    save_config,
)
from .device_id import ensure_device_id
from .icons import IconUploader
from .reporter import Reporter
from .usage import UsageTracker, to_delta_list
from .usage_store import UsageStore, default_state_path

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 硬件信息刷新间隔秒数，硬件很少变化，半小时刷一次足够喵
HARDWARE_REFRESH_SECONDS = 1800

# 每轮上报最多补几个应用图标，避免一次抠几十个 exe 拖慢采样喵
MAX_ICON_UPLOADS_PER_CYCLE = 12

# 远程桌面客户端进程名：前台是它说明人在操作远端机器，本机不该计时喵
RDP_CLIENT_PROCESSES = frozenset({"mstsc.exe", "msrdc.exe", "rdpclip.exe"})

# 前台窗口抓不到时最多沿用上一个应用多久：超过就当成没在计时，避免把空窗算给某个应用喵
FOREGROUND_REUSE_SECONDS = 120.0

# 单轮采样最多补记多久：进程被挂起后不要凭空记上几个小时喵
MAX_SAMPLE_GAP_SECONDS = 15.0

# 喵~注意：上一轮抓不到前台时，这一段间隔允许补记得更长，否则那几十秒直接消失喵
MAX_RECOVER_SECONDS = 60.0


def should_count_sample(
    sampled_app: ForegroundApp | None,
    *,
    is_server: bool,
    rdp_active: bool,
    is_afk: bool,
) -> bool:
    """判断本轮采样要不要计入使用时长喵。

    输入：前台应用、是否服务器角色、RDP 是否活跃、是否 AFK。
    输出：True 表示计入。
    边界：没有前台应用、AFK、服务器未连 RDP，这三种情况都不计入；
          远程桌面客户端在前台时照常计入，由服务端判断目标是不是受监控的设备喵。
    """
    # 喵~防御：没采到前台应用时不计时喵
    if sampled_app is None:
        return False
    # 喵~防御：人离开了就不计时，避免把挂机时间算进去喵
    if is_afk:
        return False
    # 喵~防御：服务器只在 RDP 连接时才计时喵
    if is_server and not rdp_active:
        return False
    # 远程桌面客户端在前台时照常计时，服务端会按目标地址决定要不要停喵
    return True


def rdp_target_address(sampled_app: ForegroundApp | None) -> str:
    """从远程桌面客户端的窗口标题里解析目标地址喵。

    输入：前台应用（可能为 None）。
    输出：目标主机或 IP 文本；不是远程桌面客户端或解析不出时返回空串。
    边界：标题形如「192.168.2.5 - 远程桌面连接」，中英文标题都认喵。
    """
    # 喵~防御：没有前台应用就谈不上远程桌面喵
    if sampled_app is None:
        return ""
    # 喵~防御：不是远程桌面客户端时不做解析喵
    if sampled_app.package.lower() not in RDP_CLIENT_PROCESSES:
        return ""
    # 标题里去掉固定的后缀就是目标地址喵
    title = (sampled_app.title or "").strip()
    for suffix in (" - 远程桌面连接", " - Remote Desktop Connection"):
        # 命中后缀就切掉喵
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    # 认不出后缀时原样返回标题，服务端匹配不上会按未知处理喵
    return title


def is_mirror_foreground(sampled_app: ForegroundApp | None, mirror_names_lower: set[str]) -> bool:
    """判断前台应用是不是投屏窗口喵。

    输入：前台应用、投屏进程名（小写）。
    输出：True 表示投屏窗口在前台。
    """
    # 喵~防御：没有前台应用就谈不上投屏在前台喵
    if sampled_app is None:
        return False
    # 进程名比小写，配置里大小写写错也能对上喵
    return sampled_app.package.lower() in mirror_names_lower


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析命令行参数喵。

    输入：参数列表，None 表示使用 sys.argv。
    输出：argparse 命名空间。
    """
    # 创建解析器，描述里说明用途喵
    parser = argparse.ArgumentParser(
        prog="device-hub-agent",
        description="采集本机硬件信息与前台应用使用时长，并上报到 device-hub 服务端",
    )
    # 服务端地址喵
    parser.add_argument("--server", help="服务端地址，例如 http://192.168.2.245:8080")
    # 上报口令喵
    parser.add_argument("--token", help="与服务端一致的共享上报口令")
    # 设备展示名喵
    parser.add_argument("--name", help="设备展示名，默认使用计算机名")
    # 配置文件路径喵
    parser.add_argument("--config", help="配置文件路径，默认使用 client-windows/config.json")
    # 采集频率覆盖喵
    parser.add_argument(
        "--interval",
        type=int,
        metavar="SECONDS",
        help=f"采集频率（秒），{MIN_SAMPLE_INTERVAL_SECONDS}–{MAX_SAMPLE_INTERVAL_SECONDS} 的整数，默认取配置文件里的值",
    )
    # 只上报一次就退出喵
    parser.add_argument(
        "--report-interval",
        type=float,
        help=f"上报频率（秒），{MIN_REPORT_INTERVAL_SECONDS:g}–{MAX_REPORT_INTERVAL_SECONDS:g}，默认取配置文件里的值",
    )
    parser.add_argument("--once", action="store_true", help="只采集并上报一次后退出")
    # 只打印不上报喵
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不真正发送")
    # 输出调试日志喵
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    # 喵~防御：窗口化 exe 没有控制台，加 --debug 现场开一个窗口看日志喵
    parser.add_argument(
        "--debug",
        action="store_true",
        help="弹出控制台窗口实时显示日志（窗口化 exe 用，等价于 --verbose + 开窗口）",
    )
    # 返回解析结果喵
    return parser.parse_args(argv)


def resolve_config(arguments: argparse.Namespace) -> tuple[AgentConfig, Path]:
    """合并命令行与配置文件，返回最终配置与配置文件路径喵。

    输入：命令行参数。
    输出：(配置对象, 配置文件路径)。
    边界：缺少地址或口令时抛 ConfigError，并提示怎么补喵。
    """
    # 决定配置文件路径喵
    config_path = Path(arguments.config).expanduser().resolve() if arguments.config else default_config_path()
    # 读取现有配置，不存在时得到空配置喵
    config = load_config(config_path)
    # 命令行覆盖配置文件喵
    if arguments.server:
        config.server_url = arguments.server.strip()
    if arguments.token:
        config.ingest_token = arguments.token.strip()
    if arguments.name:
        config.display_name = arguments.name.strip()
    # 喵~防御：--interval 越界时在解析阶段就报错，别等到循环里才卡住喵
    if arguments.interval is not None:
        if not MIN_SAMPLE_INTERVAL_SECONDS <= arguments.interval <= MAX_SAMPLE_INTERVAL_SECONDS:
            raise ConfigError(
                f"--interval 必须在 {MIN_SAMPLE_INTERVAL_SECONDS}–{MAX_SAMPLE_INTERVAL_SECONDS} 秒之间，"
                f"实际是 {arguments.interval}"
            )
        config.sample_interval_seconds = arguments.interval
    # 喵~防御：--report-interval 同样在解析阶段卡住越界值喵
    if arguments.report_interval is not None:
        if not MIN_REPORT_INTERVAL_SECONDS <= arguments.report_interval <= MAX_REPORT_INTERVAL_SECONDS:
            raise ConfigError(
                f"--report-interval 必须在 {MIN_REPORT_INTERVAL_SECONDS:g}–{MAX_REPORT_INTERVAL_SECONDS:g} 秒之间，"
                f"实际是 {arguments.report_interval}"
            )
        config.report_interval_seconds = arguments.report_interval
    # 喵~防御：设备 ID 缺失或非法时自动生成，保证后续上报能被服务端接受喵
    config.device_id = ensure_device_id(config.device_id)
    # 喵~防御：展示名留空时用计算机名，群里看着更直观喵
    if not config.display_name:
        config.display_name = platform.node() or config.device_id
    # 统一校验一次喵
    config.validate()
    # 把可能新生成的设备 ID 写回文件，下次启动保持一致喵
    save_config(config, config_path)
    return config, config_path


def compute_sample_gap(now_monotonic: float, last_sample_at: float, recovering: bool) -> float:
    """算这一轮要计入的秒数喵。

    输入：当前单调时刻、上一次真正计入的时刻、上一轮是不是抓不到前台。
    输出：要计入的秒数，负数按 0 处理。
    边界：抓不到前台时允许补记得更长，但同样有上限，避免把长时间挂机算进去喵。
    """
    # 喵~注意：上一轮抓不到前台时放宽上限，把那段没记的秒数一起补回来喵
    gap_cap = MAX_RECOVER_SECONDS if recovering else MAX_SAMPLE_GAP_SECONDS
    # 夹到 [0, 上限] 之间喵
    return min(max(0.0, now_monotonic - last_sample_at), gap_cap)


# 喵~注意：窗口快照最短这么久扫一次，和上报间隔解耦，10 秒上报也不会把 CPU 拉满喵
WINDOW_SCAN_SECONDS = 30.0


def plan_next_report(
    loop_started_at: float, sample_interval: float, report_interval: float
) -> float:
    """算出下一次上报的时刻，并对齐到采样网格喵。

    输入：本轮循环开始时刻（单调时钟）、采样间隔、上报间隔。
    输出：下一次该上报的单调时钟时刻。
    边界：上报间隔不足一个采样周期时按一个周期算，避免每轮都上报喵。
    """
    # 上报间隔换算成"隔几轮报一次"，四舍五入到最近的整数轮喵
    rounds = max(1, int(round(report_interval / sample_interval)))
    # 对齐到采样网格，否则 15 秒会被推到 20 秒喵
    return loop_started_at + rounds * sample_interval


def should_rescan_windows(now_monotonic: float, last_scan_at: float) -> bool:
    """判断这一轮要不要重新扫一遍窗口列表喵。

    输入：当前单调时钟、上次扫描的时刻。
    输出：True 表示该重扫，False 表示沿用上一次的快照。
    边界：从没扫过（last_scan_at <= 0）时一定重扫喵。
    """
    # 喵~防御：第一次运行必须先扫一遍，否则窗口列表永远是空的喵
    if last_scan_at <= 0.0:
        return True
    # 到点才重扫，中间几轮直接复用快照喵
    return (now_monotonic - last_scan_at) >= WINDOW_SCAN_SECONDS


def compute_afk_tail(afk_since: datetime | None, last_counted_at: datetime | None) -> float:
    """算出离开前还要补给上一个应用的秒数喵。

    输入：停表时刻、上一轮记到的那一秒的时刻。
    输出：需要补记的秒数，0 表示不用补。
    边界：任一时刻缺失或顺序颠倒时返回 0，上限是 MAX_SAMPLE_GAP_SECONDS 喵。
    """
    # 喵~防御：两个时刻缺一个就没法量差值喵
    if afk_since is None or last_counted_at is None:
        return 0.0
    # 停表时刻之前的秒数都算在用喵
    tail = (afk_since - last_counted_at).total_seconds()
    # 喵~防御：补记也设上限，避免把长时间空窗一次算进去喵
    return min(max(0.0, tail), MAX_SAMPLE_GAP_SECONDS)


def clamp_resumed_gap(
    sample_gap: float, resumed: bool, active_since: datetime | None, now: datetime
) -> float:
    """刚从 AFK 回来时，把这一轮的秒数夹到"恢复计时"之后喵。

    输入：原本要记的秒数、本轮是不是刚回来、恢复时刻、当前时刻。
    输出：夹好之后的秒数。
    边界：不是刚回来或恢复时刻缺失时原样返回喵。
    """
    # 喵~注意：挂机那段不该算进使用时长，所以按恢复时刻重新夹一次喵
    if not resumed or active_since is None:
        return sample_gap
    # 只保留恢复之后的秒数喵
    return min(sample_gap, max(0.0, (now - active_since).total_seconds()))


def discard_stale_usage_state(store: UsageStore) -> int:
    """丢弃上次退出时残留的待上报秒数，返回丢掉的秒数喵。

    输入：状态存储器。
    输出：被丢弃的总秒数（没有残留时返回 0）。

    喵~注意：为什么不再恢复它——这份数据只有应用名和秒数、没有时间戳，
    重启后无法知道它们发生在哪段时间里。服务端只能把它们铺在"上一次铺到的
    位置"之后；一旦进程被强杀且中断较久，这堆秒数就会盖到离线时段上，
    让离线期显示出使用色块，而主人要求「离线数据必须绝对真实，空档不那么
    精确没关系」。代价很小：每次上报成功都会 clear()，所以文件里最多只有
    约一个上报周期（默认 60 秒）的残留，丢掉它远好过让离线记录失真喵。
    """
    # 读一次旧文件，没有残留就什么都不做喵
    stale_seconds = store.load()
    if not stale_seconds:
        return 0
    # 丢掉的总秒数，日志要用喵
    total = sum(int(value) for value in stale_seconds.values())
    LOGGER.info(
        "丢弃上次未上报的残留时长：%s 个应用共 %s 秒（无时间戳，不再补报）",
        len(stale_seconds),
        total,
    )
    # 清掉文件，避免下次启动又读到同一份陈旧数据喵
    store.clear()
    return total


def _report_once(
    reporter: Reporter,
    tracker: UsageTracker,
    hardware: dict[str, str],
    current_app: ForegroundApp | None,
    store: UsageStore | None = None,
    rdp_connected: bool | None = None,
    mirror_windows: list[str] | None = None,
    open_windows: list[Any] | None = None,
    mirror_foreground: bool | None = None,
    afk: bool | None = None,
    afk_since: datetime | None = None,
    active_since: datetime | None = None,
    usage_ended_at: datetime | None = None,
    foreground_missing_seconds: int = 0,
    rdp_target: str = "",
    rdp_client_ip: str = "",
    rdp_client_name: str = "",
) -> bool:
    """执行一次上报，失败时把数据还回累加器喵。

    输入：上报器、累加器、硬件信息、当前应用、状态存储器、RDP 状态、投屏窗口、
          AFK 标记与两个精确边界时刻。
    输出：是否成功。
    """
    # 取出待上报数据并清空累加器喵
    pending_seconds = tracker.drain()
    # 喵~注意：从 drain 到 restore 之间任何异常都不能把数据带走，统一在下面兜底喵
    try:
        # 转成协议数组喵
        usage_deltas = to_delta_list(pending_seconds)
        # 读取当前电量喵
        battery_reading = read_battery()
        # 喵~注意：afk 与使用时长可以同时上报——服务端会把这一批秒数照常入库，
        # 空档只从"没有使用的分钟"算起，所以不必再把 afk 压成 false（那会晚一整拍）喵
        afk_flag = bool(afk)
        # 组装上报体喵
        payload = reporter.build_payload(
            hardware,
            battery_reading,
            current_app,
            usage_deltas,
            rdp_connected=rdp_connected,
            mirror_windows=mirror_windows,
            open_windows=open_windows,
            mirror_foreground=mirror_foreground,
            afk=afk_flag,
            # 喵~注意：边界时刻照旧带上，即使这一批因为还有使用量而报了 afk=false 喵
            afk_since=afk_since,
            active_since=active_since,
            usage_ended_at=usage_ended_at,
            foreground_missing_seconds=foreground_missing_seconds,
            rdp_target=rdp_target,
            rdp_client_ip=rdp_client_ip,
            rdp_client_name=rdp_client_name,
        )
        # 发送喵
        succeeded, message = reporter.send(payload)
    except Exception as error:  # 喵~防御：组装或发送炸了也不能丢这一批数据喵
        usage_deltas = []
        succeeded, message = False, f"上报过程异常：{error}"
    # 喵~防御：失败时把数据还回去，等下一次一起发，避免丢数据喵
    if not succeeded:
        tracker.restore(pending_seconds)
        # 喵~防御：还回去之后立刻落盘，防止这期间进程被杀又丢一次喵
        if store is not None:
            store.save(tracker.snapshot())
        # 把缓存了多少说清楚，主人看日志就知道有没有欠账喵
        LOGGER.warning(
            "上报失败，已缓存 %s 秒（%s 个应用）等下次一起补报：%s",
            sum(pending_seconds.values()),
            len(pending_seconds),
            message,
        )
        return False
    # 喵~防御：成功后清掉磁盘上的旧数据，避免下次启动重复上报喵
    if store is not None:
        store.clear()
    # 成功时记录本次上报了多少个应用喵
    LOGGER.info("上报成功：%s 个应用，共 %s 秒", len(usage_deltas), sum(pending_seconds.values()))
    return True


def ensure_icon(
    icon_uploader: Any,
    app_name: str,
    package: str,
    exe_path: str,
    exe_paths: dict[str, str],
) -> None:
    """确保某个应用的图标已上传喵。

    输入：上传器、应用名、包名、exe 路径、进程名到路径的映射。
    输出：无。
    边界：exe 路径为空时按进程名去映射里找，找不到就跳过喵。
    """
    # 喵~防御：空应用名没法归属喵
    if not app_name:
        return
    # 喵~防御：前台应用有时拿不到路径（提权进程），用进程名兜底喵
    resolved = exe_path or exe_paths.get((package or "").lower(), "")
    if not resolved:
        return
    # 交给上传器，内部会跳过已经传过的喵
    icon_uploader.ensure(app_name, resolved, package)


def upload_window_icons(
    icon_uploader: Any,
    windows: Sequence[Any],
    exe_paths: dict[str, str],
) -> None:
    """给所有打开窗口对应的应用补图标喵。

    输入：上传器、窗口快照、进程名到路径的映射。
    输出：无。
    边界：每轮最多补 MAX_ICON_UPLOADS_PER_CYCLE 个，避免拖慢采样喵。
    """
    # 本轮已处理的应用名，避免同一个应用重复查喵
    seen: set[str] = set()
    # 本轮补图标的数量喵
    uploaded = 0
    for window in windows:
        # 喵~防御：达到上限就收手，采样节奏优先喵
        if uploaded >= MAX_ICON_UPLOADS_PER_CYCLE:
            return
        # 取窗口对应的应用名与进程名喵
        app_name = getattr(window, "app", "")
        package = getattr(window, "package", "")
        # 喵~防御：空应用名或已处理过就跳过喵
        if not app_name or app_name in seen:
            continue
        seen.add(app_name)
        # 喵~防御：映射里没有这个进程就跳过喵
        exe_path = exe_paths.get((package or "").lower(), "")
        if not exe_path:
            continue
        # 交给上传器，已传过的会被内部跳过喵
        icon_uploader.ensure(app_name, exe_path, package)
        uploaded += 1


def run_forever(config: AgentConfig, state_path: Path | None = None) -> int:
    """常驻运行：采样前台应用、定时上报喵。

    输入：最终配置、可选的状态文件路径（默认放在配置文件同目录）。
    输出：退出码，正常 Ctrl+C 退出返回 0。
    边界：任何单次采集或上报失败都不会终止主循环喵。
    """
    # 创建上报器喵
    reporter = Reporter(config)
    # 创建图标上传器，同一个应用只传一次喵
    icon_uploader = IconUploader(reporter)
    # 先把服务端已有的图标拉下来，避免每次启动重传喵
    icon_uploader.prime()
    # 创建使用时长累加器喵
    tracker = UsageTracker()
    # 创建状态存储器，用于上报失败时落盘、成功后清空喵
    store = UsageStore(state_path or default_state_path(default_config_path()))
    # 喵~注意：重启后不再恢复旧文件里的残留秒数，只把它清掉喵
    discard_stale_usage_state(store)
    # 启动时采集一次硬件信息喵
    hardware = collect_hardware()
    # 是否为服务器角色：服务器只在 RDP 连接时统计喵
    is_server = config.role == "server"
    # 投屏进程名预先转小写，循环里每 5 秒比一次，别重复构造喵
    mirror_process_names_lower = {name.lower() for name in config.mirror_process_names}
    # 当前前台应用，切换时更新喵
    current_app: ForegroundApp | None = None
    # 上一次采样到的应用名，用于判断是否切换喵
    last_app_name = ""
    # 当前 RDP 是否处于活动连接喵
    rdp_active = False
    # 当前 RDP 客户端身份（IP, 机器名），非服务器角色保持空喵
    rdp_client: tuple[str, str] = ("", "")
    # 当前 scrcpy 投屏窗口标题喵
    mirror_windows: list[str] = []
    # 当前是否处于 AFK 状态喵
    afk = False
    # 进入 AFK 的时刻（停止计时的精确时刻），不在 AFK 时为 None 喵
    afk_since_moment: datetime | None = None
    # 上报用的两个边界时刻，先给默认值，避免退出路径引用未定义变量喵
    afk_since: datetime | None = None
    active_since: datetime | None = None
    # 上一轮采样的时刻，用来按真实流逝时间累计喵
    last_sample_at = time.monotonic()
    # 喵~注意：上一轮是不是"抓不到前台"，决定这一轮要不要补记更长的间隔喵
    foreground_missed = False
    # 累计"抓不到前台"的秒数，随上报带给服务端喵
    missing_seconds = 0.0
    # 最后一次真正计入使用时长的那一刻，上报时给色块落位喵
    last_counted_moment: datetime | None = None
    # 上一轮循环的时刻，用来量"抓不到前台"那段真实流逝喵
    last_round_at = time.monotonic()
    # 上一次判定到的前台应用，窗口抓不到时沿用（限时）喵
    last_known_app: ForegroundApp | None = None
    # 沿用的起点时刻，超过上限就不再沿用，避免把锁屏时间算到某个应用上喵
    reused_since: float | None = None
    # 下一次上报的时间点喵
    next_report_at = time.monotonic() + config.report_interval_seconds
    # 下一次刷新硬件信息的时间点喵
    next_hardware_refresh_at = time.monotonic() + HARDWARE_REFRESH_SECONDS
    # 进程名到 exe 路径的映射，给图标上传用（内部有 2 分钟缓存）喵
    exe_paths = exe_path_map()
    # 上一次扫窗口列表的时刻，0 表示还没扫过喵
    last_window_scan = 0.0
    # 上一次的窗口快照，短间隔上报时直接复用喵
    window_snapshot: list[dict[str, Any]] = []
    # 打印启动摘要喵
    LOGGER.info(
        "采集端启动：设备=%s，角色=%s，服务端=%s，采样=%ss，上报=%ss",
        config.device_id,
        config.role,
        config.server_url,
        config.sample_interval_seconds,
        config.report_interval_seconds,
    )
    try:
        while True:
            # 记录本轮开始时间，用于补偿采样耗时喵
            loop_started_at = time.monotonic()
            # 喵~防御：服务器角色每轮都要刷新 RDP 与投屏状态，工作站不需要喵
            if is_server:
                # 服务器角色顺便记下连进来的是谁，服务端用来确认是自己人喵
                rdp_client = rdp_client_info()
                rdp_active = detect_rdp_active()
                mirror_windows = list_mirror_windows(config.mirror_process_names)
            # 采集当前前台应用喵
            sampled_app = get_foreground_app()
            # 取键鼠空闲秒数，超过阈值就算人离开了喵
            idle_seconds_now = idle_seconds()
            # 喵~注意：锁屏时人肯定不在用，直接算 AFK，别让"锁屏+动鼠标"变成假在线喵
            screen_locked = session_locked()
            # 本轮是否处于 AFK 状态喵
            is_afk = screen_locked or idle_seconds_now >= config.afk_threshold_seconds
            # 喵~注意：上一轮是不是"抓不到前台、也没法沿用"，这一轮要把那段间隔补回来喵
            recover_gap = foreground_missed
            # 喵~注意：前台窗口抓不到但人还在动（UAC 安全桌面、切桌面、窗口重建）时沿用上一个应用喵
            if sampled_app is None and not is_afk and last_known_app is not None:
                # 沿用有上限，超过就不再沿用，避免把长时间的空窗算给某个应用喵
                reused_since = reused_since if reused_since is not None else time.monotonic()
                if time.monotonic() - reused_since <= FOREGROUND_REUSE_SECONDS:
                    sampled_app = last_known_app
                else:
                    # 超时了，清掉沿用状态，这一轮就不计时喵
                    reused_since = None
            else:
                # 抓到了窗口，或者人在离开，沿用状态作废喵
                reused_since = None
            # 记住这次真正采到的应用，供下一次沿用喵
            if sampled_app is not None:
                last_known_app = sampled_app
            # 喵~注意：沿用也救不回来时，这一轮就是"抓不到前台"，秒数要留到下次补喵
            foreground_missed = sampled_app is None and not is_afk
            # 喵~防御：抓不到前台的这段时间单独记账，随上报发给服务端喵
            if foreground_missed:
                missing_seconds += max(0.0, time.monotonic() - last_round_at)
            # 刷新本轮时刻，供下一轮量间隔喵
            last_round_at = time.monotonic()
            # 喵~防御：AFK 状态变化时打一条日志，方便主人核对统计口径喵
            afk_changed = is_afk != afk
            # 本轮时刻，用来算两个边界喵
            now_moment = datetime.now(timezone.utc)
            if afk_changed:
                afk = is_afk
                if is_afk:
                    # 锁屏是立刻停表；空闲则回溯到"空闲满阈值"那一刻喵
                    afk_since_moment = now_moment if screen_locked else now_moment - timedelta(
                        seconds=max(0.0, idle_seconds_now - config.afk_threshold_seconds)
                    )
                else:
                    # 回来了，边界作废喵
                    afk_since_moment = None
                LOGGER.info(
                    "AFK 状态切换为 %s（空闲 %.0f 秒，锁屏=%s）",
                    "离开" if afk else "在用",
                    idle_seconds_now,
                    screen_locked,
                )
            # 本轮是不是刚从 AFK 回到在用喵
            resumed_this_round = afk_changed and not is_afk
            # 喵~注意：AFK 刚开始这一轮，把"还在用、只是还没到阈值"的那几秒补给上一个应用喵
            if afk_changed and is_afk and afk_since_moment is not None and last_known_app is not None:
                # 停表时刻之前都算在用，和上一轮记到哪儿做差喵
                tail_seconds = compute_afk_tail(afk_since_moment, last_counted_moment)
                if tail_seconds >= 1.0:
                    tracker.add_seconds(
                        last_known_app.name, int(round(tail_seconds)), last_known_app.package
                    )
                    last_counted_moment = afk_since_moment
                    store.save(tracker.snapshot())
                    LOGGER.info("离开前补记 %.0f 秒到 %s", tail_seconds, last_known_app.name)
            # 喵~注意：边界时刻只在切换那一刻算一次，之后每轮复用，避免上报之间漂移喵
            afk_since = afk_since_moment if is_afk else None
            # 恢复计时发生在最后一次输入的那一刻喵
            active_since = None if is_afk else now_moment - timedelta(seconds=max(0.0, idle_seconds_now))
            # 喵~防御：服务器在 RDP 未连接时不计时，AFK 时也不计时，避免把挂机时间算进去喵
            # 投屏窗口是否在前台，服务端据此决定本机与手机各自是否计时喵
            mirror_foreground = is_mirror_foreground(sampled_app, mirror_process_names_lower)
            # 本轮是否计入使用时长：AFK、服务器未连 RDP、前台是远程桌面客户端都不计喵
            should_count = should_count_sample(
                sampled_app,
                is_server=is_server,
                rdp_active=rdp_active,
                is_afk=is_afk,
            )
            if should_count and sampled_app is not None:
                # 喵~防御：应用切换时重置 since，避免一直显示首次进入时间喵
                if sampled_app.name != last_app_name:
                    current_app = ForegroundApp(
                        name=sampled_app.name,
                        package=sampled_app.package,
                        title=sampled_app.title,
                        since=datetime.now(timezone.utc),
                    )
                    last_app_name = sampled_app.name
                    LOGGER.debug("前台应用切换为 %s", sampled_app.name)
                # 喵~防御：新出现的应用顺手把图标传上去，同一个应用只传一次喵
                ensure_icon(icon_uploader, sampled_app.name, sampled_app.package, sampled_app.exe_path, exe_paths)
                # 喵~注意：按真实流逝时间累计，循环被拖慢时不会凭空少记喵
                now_monotonic = time.monotonic()
                # 喵~注意：上一轮抓不到前台时放宽上限，把那段没记的秒数一起补回来喵
                sample_gap = compute_sample_gap(now_monotonic, last_sample_at, recover_gap)
                # 喵~注意：刚离开回来时只从"恢复计时那一刻"开始算，别把挂机的秒数算成使用喵
                sample_gap = clamp_resumed_gap(sample_gap, resumed_this_round, active_since, now_moment)
                # 包名一起记下来，服务端才能匹配应用图标与包名喵
                tracker.add_seconds(sampled_app.name, max(1, int(round(sample_gap))), sampled_app.package)
                # 喵~注意：记下"最后一秒"的真实时刻，上报时按它给色块落位喵
                last_counted_moment = now_moment
                # 喵~防御：每次采样后落盘，进程被强杀也能保住这几秒数据喵
                store.save(tracker.snapshot())
            # 喵~注意：只有这一轮真的计入（或明确暂停）才推进采样时刻；
            # 抓不到前台的那一轮先不推进，等下一次计入时一起补喵
            if not foreground_missed:
                last_sample_at = time.monotonic()
            # 到达上报时间点、或者 AFK 状态刚变化时立刻上报一次喵
            if time.monotonic() >= next_report_at or afk_changed:
                # 喵~防御：窗口列表只在要上报时扫一遍，不必每 5 秒扫全桌面喵
                exe_paths = exe_path_map()
                # 喵~注意：上报间隔可能被调到 10 秒，窗口扫描单独节流到 30 秒一次喵
                if should_rescan_windows(time.monotonic(), last_window_scan):
                    window_snapshot = list_open_windows()
                    # 喵~防御：窗口里的应用也要有图标，否则后台常驻的 QQ、v2rayN 永远缺图喵
                    upload_window_icons(icon_uploader, window_snapshot, exe_paths)
                    last_window_scan = time.monotonic()
                # 公共参数只组一次，AFK 切换时要连发两条喵
                report_extras: dict[str, Any] = {
                    "rdp_connected": rdp_active if is_server else None,
                    "mirror_windows": mirror_windows if is_server else None,
                    "mirror_foreground": mirror_foreground if is_server else None,
                    "open_windows": window_snapshot,
                    "rdp_target": rdp_target_address(sampled_app),
                    "rdp_client_ip": rdp_client[0] if is_server else "",
                    "rdp_client_name": rdp_client[1] if is_server else "",
                }
                _report_once(
                    reporter,
                    tracker,
                    hardware,
                    current_app,
                    store,
                    afk=is_afk,
                    afk_since=afk_since,
                    active_since=active_since,
                    usage_ended_at=last_counted_moment,
                    foreground_missing_seconds=int(round(missing_seconds)),
                    **report_extras,
                )
                # 喵~防御：损耗计数上报过就清零，下一次重新统计喵
                missing_seconds = 0.0
                # 喵~注意：按本轮起点对齐采样网格，设 15 秒就真的 15 秒报一次喵
                next_report_at = plan_next_report(
                    loop_started_at,
                    config.sample_interval_seconds,
                    config.report_interval_seconds,
                )
            # 到达刷新时间点时重新采集硬件信息喵
            if time.monotonic() >= next_hardware_refresh_at:
                hardware = collect_hardware()
                next_hardware_refresh_at = time.monotonic() + HARDWARE_REFRESH_SECONDS
                LOGGER.debug("硬件信息已刷新")
            # 计算本轮剩余休眠时间，保证采样节奏稳定喵
            elapsed_seconds = time.monotonic() - loop_started_at
            time.sleep(max(0.0, config.sample_interval_seconds - elapsed_seconds))
    except KeyboardInterrupt:
        # 喵~防御：Ctrl+C 属于正常退出，先把待发数据尝试发一次再走喵
        LOGGER.info("收到退出信号，尝试最后一次上报")
        _report_once(
            reporter,
            tracker,
            hardware,
            current_app,
            store,
            rdp_connected=rdp_active if is_server else None,
            mirror_windows=mirror_windows if is_server else None,
            mirror_foreground=mirror_foreground if is_server else None,
            afk=afk,
            # 喵~注意：收尾上报也带上边界时刻，退出前那一段空档同样能画准喵
            afk_since=afk_since,
            active_since=active_since,
            usage_ended_at=last_counted_moment,
            foreground_missing_seconds=int(round(missing_seconds)),
            open_windows=list_open_windows(),
        )
        return 0
    finally:
        # 关闭 HTTP 连接池喵
        reporter.close()


def configure_logging(level: int, log_path: Path) -> Path | None:
    """配置日志：始终写文件，有控制台时再输出到屏幕喵。

    输入：日志级别、日志文件路径。
    输出：实际使用的日志文件路径，写不了文件时返回 None。
    边界：文件日志失败不影响采集，只保留控制台输出喵。
    """
    # 收集可用的日志处理器喵
    handlers: list[logging.Handler] = []
    # 文件日志喵
    usable_path: Path | None = None
    try:
        # 目录可能不存在，先创建喵
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # 2MB 一个文件、留两份历史，够排查又不会吃满磁盘喵
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        handlers.append(file_handler)
        usable_path = log_path
    except OSError as error:
        # 喵~防御：磁盘满或没权限时不能让采集起不来喵
        print(f"日志文件不可用：{error}", file=sys.stderr if sys.stderr is not None else sys.stdout)
    # 喵~防御：窗口化 exe 里 sys.stderr 是 None，加 StreamHandler 会在写日志时炸掉喵
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    # 统一格式，时间戳便于和上报时间对齐喵
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    return usable_path


def run_once(config: AgentConfig, dry_run: bool) -> int:
    """采集并上报一次，主要用于联调与冒烟测试喵。

    输入：配置、是否只打印不发送。
    输出：退出码，成功 0，失败 1。
    """
    # 创建上报器喵
    reporter = Reporter(config)
    try:
        # 采集硬件信息喵
        hardware = collect_hardware()
        # 采集当前前台应用喵
        current_app = get_foreground_app()
        # 喵~防御：服务器角色单次上报也带上 RDP 与投屏状态，方便主人核对喵
        is_server = config.role == "server"
        # 组装上报体，使用时长留空（单次运行没有累计）喵
        payload = reporter.build_payload(
            hardware,
            read_battery(),
            current_app,
            [],
            rdp_connected=detect_rdp_active() if is_server else None,
            mirror_windows=list_mirror_windows(config.mirror_process_names) if is_server else None,
            mirror_foreground=is_mirror_foreground(current_app, {name.lower() for name in config.mirror_process_names}) if is_server else None,
            # 单次运行也带上窗口列表与 AFK 状态，方便主人核对喵
            open_windows=list_open_windows(),
            afk=idle_seconds() >= config.afk_threshold_seconds,
        )
        # 喵~防御：dry-run 模式下只打印，方便主人核对字段喵
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        # 真正发送喵
        succeeded, message = reporter.send(payload)
        # 打印结果喵
        print(message)
        return 0 if succeeded else 1
    finally:
        # 关闭连接喵
        reporter.close()


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口喵。

    输入：参数列表。
    输出：进程退出码。
    边界：配置错误打印可读提示并返回 2，而不是抛堆栈喵。
    """
    # 解析参数喵
    arguments = parse_arguments(argv)
    # 喵~防御：--debug 必须在配置日志之前接好控制台，否则日志流是 None 喵
    console_ready = False
    if arguments.debug:
        console_ready = attach_console()
    # 日志文件放在配置文件旁边，窗口化运行时也能事后排查喵
    log_base = Path(arguments.config).expanduser() if arguments.config else default_config_path()
    # 配置日志级别与输出喵
    configure_logging(
        logging.DEBUG if (arguments.verbose or arguments.debug) else logging.INFO,
        log_base.with_name("agent.log"),
    )
    # 控制台是否接上只记一行日志，方便主人确认 --debug 生效了喵
    if arguments.debug:
        LOGGER.info("控制台已接入，日志实时显示" if console_ready else "控制台接入失败，日志只写文件")
    try:
        # 合并配置喵
        config, _config_path = resolve_config(arguments)
    except ConfigError as config_error:
        # 喵~防御：配置错误时给出明确中文提示，返回 2 表示参数问题喵
        message = f"配置错误：{config_error}"
        LOGGER.error(message)
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        else:
            # 喵~防御：窗口化 exe 没有控制台，用弹窗告诉主人哪里配错了喵
            show_error("device-hub 采集端启动失败", message)
        return 2
    # 单次模式喵
    if arguments.once or arguments.dry_run:
        return run_once(config, dry_run=arguments.dry_run)
    # 常驻模式喵
    return run_forever(config, default_state_path(_config_path))


if __name__ == "__main__":
    # 作为脚本直接运行时执行入口喵
    sys.exit(main())
