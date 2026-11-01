"""硬件信息、电量与前台窗口采集。

Windows 上取"当前前台应用"没有官方 API，标准做法是：
GetForegroundWindow 拿窗口句柄 → GetWindowThreadProcessId 拿进程 ID → psutil 查进程名。
这条链路不需要管理员权限，也不需要安装任何驱动喵。
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import psutil

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 窗口标题最多保留的字符数，避免超长标题把上报体撑大喵
MAX_WINDOW_TITLE_LENGTH = 120

# 浏览器标题里夹的零宽字符，Edge 用它在标题里插 "Microsoft\u200b Edge" 防伪喵
ZERO_WIDTH_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)

# 浏览器标题尾巴：Chrome / Edge 会拼上配置名和浏览器名喵
BROWSER_PROFILE_TAIL = re.compile(r"\s+-\s+(?:用户配置|Profile)\s*\d+\s+-\s+.*$", re.IGNORECASE)

# 浏览器名尾巴，例如 " - Microsoft Edge" / " - Google Chrome" 喵
BROWSER_NAME_TAIL = re.compile(
    r"\s+-\s+(?:Microsoft\s*Edge|Google\s*Chrome|Mozilla\s*Firefox|Brave|Vivaldi|Opera)(?:\s+.*)?$",
    re.IGNORECASE,
)

# 标签组尾巴，例如 "device-hub 控制台 和另外 4 个页面" 喵
BROWSER_TAB_GROUP_TAIL = re.compile(r"\s+(?:和另外|and)\s*\d+\s*(?:个页面|more\s+pages?)\s*$", re.IGNORECASE)


def normalize_window_title(raw: str) -> str:
    """把窗口标题清成干净的页面/文档标题喵。

    输入：GetWindowTextW 拿到的原始标题。
    输出：去掉零宽字符、浏览器配置名、"和另外 N 个页面" 尾巴后的标题。
    边界：非浏览器标题原样返回（只做空白收敛），空标题返回空串喵。
    """
    # 喵~防御：空标题直接返回，别让调用方去猜喵
    if not raw:
        return ""
    # 零宽字符和不换行空格先清掉，否则后面的正则匹配不上喵
    text = raw.translate(ZERO_WIDTH_CHARS).replace("\u00a0", " ")
    # 连续空白收敛成一个空格喵
    text = " ".join(text.split())
    # 先切配置名（它后面还可能跟浏览器名）喵
    text = BROWSER_PROFILE_TAIL.sub("", text)
    # 再切浏览器名尾巴喵
    text = BROWSER_NAME_TAIL.sub("", text)
    # 最后切标签组尾巴喵
    text = BROWSER_TAB_GROUP_TAIL.sub("", text)
    # 截断超长标题喵
    return text.strip()[:MAX_WINDOW_TITLE_LENGTH]

# 取显卡型号时调用 wmic 的超时秒数喵
WMIC_TIMEOUT_SECONDS = 8

# 显示适配器设备类 GUID，所有显卡都挂在这个类下面喵
GPU_CLASS_GUID = "{4d36e968-e325-11ce-bfc1-08002be10318}"

# 显卡型号所在的完整注册表路径喵
GPU_CLASS_PATH = rf"SYSTEM\CurrentControlSet\Control\Class\{GPU_CLASS_GUID}"

# 显卡型号在注册表里的候选值名，不同驱动写的键名不一样喵
GPU_REGISTRY_VALUE_NAMES = ("DriverDesc", "Device Description")

# 注册表里显卡子键的命名规则，形如 0000 / 0001 喵
GPU_SUBKEY_PATTERN = re.compile(r"\d{4}")

# 显卡型号的最大长度，避免个别驱动写超长串把上报体撑大喵
MAX_GPU_NAME_LENGTH = 80

# SM_REMOTESESSION：非 0 表示当前会话是远程桌面会话喵
SM_REMOTESESSION = 0x1000

# WTSConnectState 信息类编号，返回 WTS_CONNECTSTATE_CLASS 枚举喵
WTS_CONNECT_STATE_INFO = 8

# WTS_CONNECTSTATE_CLASS 里"活动"的取值，表示用户正在操作喵
WTS_ACTIVE_STATE = 0

# WTS_CURRENT_SESSION 常量喵
WTS_CURRENT_SESSION = -1

# WTSClientAddress 信息类编号，返回 WTS_CLIENT_ADDRESS 结构体喵
WTS_CLIENT_ADDRESS_INFO = 14

# WTSClientName 信息类编号，返回客户端机器名的宽字符串喵
WTS_CLIENT_NAME_INFO = 10

# WTSSessionInfoEx 信息类编号，返回 WTSINFOEXW 结构体喵
WTS_SESSION_INFO_EX = 25

# 会话标志里"已锁屏"的取值（Win8 起 LOCK=1、UNLOCK=0）喵
WTS_SESSIONSTATE_LOCK = 1

# AF_INET / AF_INET6 地址族取值喵
AF_INET = 2
AF_INET6 = 23


class _WtsClientAddress(ctypes.Structure):
    """对应 Win32 的 WTS_CLIENT_ADDRESS 结构体喵。"""

    # 地址族与 20 字节地址缓冲喵
    _fields_ = [("AddressFamily", ctypes.c_ulong), ("Address", ctypes.c_ubyte * 20)]


class _WtsInfoExHead(ctypes.Structure):
    """对应 Win32 的 WTSINFOEXW 头部，只取到 SessionFlags 就够判断锁屏喵。"""

    # 版本号、会话 ID、连接状态、会话标志喵
    _fields_ = [
        ("Level", ctypes.c_uint32),
        ("SessionId", ctypes.c_uint32),
        ("SessionState", ctypes.c_uint32),
        ("SessionFlags", ctypes.c_int32),
    ]

# 单次上报最多带多少条投屏窗口标题，与服务端协议上限一致喵
MAX_MIRROR_WINDOWS = 16


class _LastInputInfo(ctypes.Structure):
    """对应 Win32 的 LASTINPUTINFO 结构体喵。"""

    # 结构体大小与最后一次输入的系统毫秒时间戳喵
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """返回距离上一次键鼠输入的秒数喵。

    输出：空闲秒数；非 Windows 或调用失败时返回 0.0，表示"当作在用"。
    边界：探测失败一律返回 0，宁可多算也不要因为拿不到空闲时间而丢数据喵。
    """
    # 喵~防御：非 Windows 平台没有这个接口，直接当作在用喵
    if platform.system() != "Windows":
        return 0.0
    try:
        # 组装结构体并填好大小喵
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        # 取最后一次输入的系统时间喵
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # 喵~防御：GetTickCount64 默认按 32 位 int 返回，必须声明成 64 位，否则开机 24 天后会算错喵
        kernel32 = ctypes.windll.kernel32
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        # 相减得到空闲毫秒数喵
        idle_ms = kernel32.GetTickCount64() - info.dwTime
        return max(0.0, idle_ms / 1000.0)
    except (AttributeError, OSError, ValueError):
        # 喵~防御：探测失败就当作用户在用，统计照常喵
        return 0.0


def session_locked() -> bool:
    """判断当前会话是否已锁屏喵。

    输出：true 表示已锁屏（人肯定不在用）；非 Windows 或查询失败时返回 false。
    边界：拿不到会话信息时按"没锁屏"处理，退回原来的空闲判定，绝不影响统计喵。
    """
    # 喵~防御：非 Windows 平台没有这个接口喵
    if platform.system() != "Windows":
        return False
    try:
        # 加载 WTS API 喵
        wts_api = ctypes.windll.wtsapi32
        # 显式声明参数类型，避免 64 位下指针被截断喵
        wts_api.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        wts_api.WTSQuerySessionInformationW.restype = ctypes.c_bool
        wts_api.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        # 接收返回缓冲区喵
        buffer_pointer = ctypes.c_void_p()
        returned_bytes = ctypes.c_ulong()
        # 查询当前会话的扩展信息喵
        succeeded = wts_api.WTSQuerySessionInformationW(
            None,
            WTS_CURRENT_SESSION,
            WTS_SESSION_INFO_EX,
            ctypes.byref(buffer_pointer),
            ctypes.byref(returned_bytes),
        )
        # 喵~防御：查询失败时按"没锁屏"处理，退回空闲判定喵
        if not succeeded or not buffer_pointer:
            return False
        try:
            # 只读结构体头部就够判断锁屏喵
            head = ctypes.cast(buffer_pointer, ctypes.POINTER(_WtsInfoExHead)).contents
            # 喵~防御：Level 不是 1 说明结构体布局不认识，保守按没锁屏处理喵
            if int(head.Level) != 1:
                return False
            return int(head.SessionFlags) == WTS_SESSIONSTATE_LOCK
        finally:
            # 喵~防御：WTS 分配的内存必须释放，否则每次采样都泄漏喵
            wts_api.WTSFreeMemory(buffer_pointer)
    except (AttributeError, OSError):
        # 喵~防御：老系统或权限受限时按没锁屏处理喵
        return False


@dataclass(frozen=True)
class ForegroundApp:
    """当前前台应用快照喵。"""
    # 展示名，通常是去掉 .exe 的进程名喵
    name: str
    # 进程可执行文件名，例如 Code.exe 喵
    package: str
    # 窗口标题，可能为空喵
    title: str
    # 该应用进入前台的时刻喵
    since: datetime
    # 可执行文件完整路径，抠图标时要用；取不到时为空喵
    exe_path: str = ""


def _user32() -> Any | None:
    """返回 user32 句柄，非 Windows 平台返回 None 喵。"""
    # 喵~防御：只有 Windows 才有 windll，其它平台直接放弃采集喵
    if platform.system() != "Windows":
        return None
    try:
        # 加载 user32 动态库喵
        api = ctypes.windll.user32
        # 喵~注意：必须声明原型，否则 64 位窗口句柄会被当成 32 位整数截断，
        # GetWindowThreadProcessId 拿到的 pid 就是 0，前台应用会整段变成"抓不到"喵
        api.GetForegroundWindow.restype = ctypes.c_void_p
        api.GetForegroundWindow.argtypes = []
        api.GetWindowThreadProcessId.restype = ctypes.c_ulong
        api.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        api.GetWindowTextW.restype = ctypes.c_int
        api.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar), ctypes.c_int]
        api.GetWindowTextLengthW.restype = ctypes.c_int
        api.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        api.IsWindowVisible.restype = ctypes.c_int
        api.IsWindowVisible.argtypes = [ctypes.c_void_p]
        api.IsIconic.restype = ctypes.c_int
        api.IsIconic.argtypes = [ctypes.c_void_p]
        api.GetSystemMetrics.restype = ctypes.c_int
        api.GetSystemMetrics.argtypes = [ctypes.c_int]
        # 喵~防御：EnumWindows 的回调类型在下面才定义，这里只声明返回值喵
        api.EnumWindows.restype = ctypes.c_int
        return api
    except (AttributeError, OSError):
        # 喵~防御：极端情况下加载失败时返回 None，让上层按"未知应用"处理喵
        return None


# 系统进程快照缓存：pid → 进程名，给"提权进程读不到名字"兜底喵
_PROCESS_SNAPSHOT: dict[int, str] = {}

# 快照刷新时间戳，避免每次采样都遍历全系统进程喵
_PROCESS_SNAPSHOT_AT = 0.0

# 快照有效期，30 秒足够新又不至于拖慢采样喵
PROCESS_SNAPSHOT_SECONDS = 30.0

# "查不到进程名"日志的节流时间戳，避免刷屏喵
_PROCESS_NAME_WARNED_AT = 0.0


def _process_snapshot() -> dict[int, str]:
    """返回 pid 到进程名的全量快照，带 30 秒缓存喵。

    输入：无。
    输出：pid → 进程名 的字典副本。
    边界：遍历失败时返回上一次的快照（可能是空字典）喵。
    """
    global _PROCESS_SNAPSHOT_AT
    # 缓存还新鲜就直接用喵
    if _PROCESS_SNAPSHOT and time.monotonic() - _PROCESS_SNAPSHOT_AT <= PROCESS_SNAPSHOT_SECONDS:
        return _PROCESS_SNAPSHOT
    # 重新遍历一次系统进程喵
    fresh: dict[int, str] = {}
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            # 喵~防御：单个进程信息缺失就跳过喵
            name = proc.info.get("name") or ""
            if name:
                fresh[proc.info["pid"]] = name
    except (psutil.Error, OSError):
        # 喵~防御：遍历失败就沿用旧快照喵
        return _PROCESS_SNAPSHOT
    # 喵~防御：这次什么都没捞到时不要覆盖旧快照喵
    if fresh:
        _PROCESS_SNAPSHOT.clear()
        _PROCESS_SNAPSHOT.update(fresh)
        _PROCESS_SNAPSHOT_AT = time.monotonic()
    return _PROCESS_SNAPSHOT


def lookup_process_name(process_id: int) -> str:
    """查进程名，直接查失败时退回系统快照喵。

    输入：进程 ID。
    输出：进程名；确实查不到时返回空串。
    边界：提权进程（任务管理器、UAC 安全桌面）直接查会 AccessDenied，
          但系统快照里带着名字，用它兜底就不会整段空白喵。
    """
    # 先走最直接的路径喵
    try:
        return psutil.Process(process_id).name()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        # 喵~防御：进程已经退出，没必要再查快照喵
        return ""
    except (psutil.AccessDenied, OSError):
        # 喵~注意：权限不足时退回系统快照，这条路不需要打开目标进程喵
        name = _process_snapshot().get(process_id, "")
        if name:
            return name
        # 喵~防御：真查不到就记一条节流日志，方便定位空白来源喵
        global _PROCESS_NAME_WARNED_AT
        if time.monotonic() - _PROCESS_NAME_WARNED_AT >= 60.0:
            _PROCESS_NAME_WARNED_AT = time.monotonic()
            LOGGER.warning("前台窗口进程 %s 查不到名字（权限不足），本次跳过计时", process_id)
        return ""


def topmost_window() -> int:
    """按 Z 序找最上面的可见窗口，作为"抓不到前台"时的兜底喵。

    输入：无。
    输出：窗口句柄；一个都没有时返回 0。
    边界：跳过最小化窗口与没有标题的托盘/工具窗口，只要 Z 序第一个喵。
    """
    # 取 user32 句柄喵
    window_api = _user32()
    # 喵~防御：非 Windows 平台没有窗口可枚举喵
    if window_api is None:
        return 0
    # 收集到的句柄，只要第一个喵
    candidates: list[int] = []

    # 枚举回调喵
    def _callback(handle: int, _param: int) -> bool:
        """按 Z 序从最上面开始挑第一个合适的窗口喵。"""
        try:
            # 喵~防御：不可见窗口不算喵
            if not window_api.IsWindowVisible(handle):
                return True
            # 喵~防御：最小化的窗口不是"正在看"的窗口喵
            if window_api.IsIconic(handle):
                return True
            # 喵~防御：没有标题的多半是托盘、提示条、输入法窗口喵
            if window_api.GetWindowTextLengthW(handle) <= 0:
                return True
            # 记下句柄喵
            candidates.append(int(handle))
        except (OSError, ValueError, ctypes.ArgumentError):
            # 喵~防御：单个窗口出错就跳过喵
            pass
        # 已经找到就不再继续枚举喵
        return not candidates

    try:
        # 开始枚举喵
        window_api.EnumWindows(WNDENUMPROC(_callback), 0)
    except (OSError, ValueError, ctypes.ArgumentError):
        # 喵~防御：枚举失败就当没有兜底喵
        return 0
    # 返回最上面那个窗口喵
    return candidates[0] if candidates else 0


def get_foreground_app() -> ForegroundApp | None:
    """获取当前前台应用喵。

    输入：无。
    输出：ForegroundApp；拿不到窗口（例如锁屏、桌面）时返回 None。
    边界：进程已退出、权限不足、句柄为 0 都返回 None 而不是抛异常喵。
    """
    # 取 user32 句柄喵
    window_api = _user32()
    # 喵~防御：非 Windows 平台无法采集喵
    if window_api is None:
        return None
    # 取前台窗口句柄喵
    window_handle = window_api.GetForegroundWindow()
    # 喵~注意：实测这台机器上"没人敲键鼠"时 GetForegroundWindow 会返回 0，
    # 这时候退一步用 Z 序最上面的窗口，否则整段时间都会记成"抓不到前台"喵
    if not window_handle:
        window_handle = topmost_window()
    # 喵~防御：真的一个窗口都没有（锁屏、切桌面）才按未知处理喵
    if not window_handle:
        return None
    # 准备接收进程 ID 的容器喵
    process_id = ctypes.c_ulong()
    # 通过窗口句柄取进程 ID 喵
    window_api.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
    # 喵~防御：拿不到进程 ID 时无法继续喵
    if process_id.value == 0:
        return None
    # 可执行文件路径，取不到就留空喵
    exe_path = ""
    # 喵~注意：进程名走"直接查 + 系统快照兜底"，提权窗口也能采到名字喵
    process_name = lookup_process_name(process_id.value)
    # 喵~防御：连快照都查不到时才按未知处理喵
    if not process_name:
        return None
    try:
        # 顺便取一下完整路径，给抠图标用喵
        exe_path = psutil.Process(process_id.value).exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        # 喵~防御：系统进程不给读路径，图标就跳过喵
        exe_path = ""
    # 读取窗口标题喵
    title_buffer = ctypes.create_unicode_buffer(512)
    window_api.GetWindowTextW(window_handle, title_buffer, 512)
    # 清掉浏览器标题里的零宽字符与配置名尾巴喵
    window_title = normalize_window_title(title_buffer.value)
    # 展示名去掉 .exe 后缀，读起来更像应用名喵
    display_name = process_name[:-4] if process_name.lower().endswith(".exe") else process_name
    # 返回快照，since 由调用方在检测到应用切换时覆盖喵
    return ForegroundApp(
        name=display_name or process_name,
        package=process_name,
        title=window_title,
        since=datetime.now(timezone.utc),
        exe_path=exe_path,
    )


def read_cpu_name() -> str:
    """读取 CPU 型号名称喵。

    输入：无。
    输出：型号字符串，取不到时返回 "未知"。
    边界：注册表被策略锁定或平台不是 Windows 时回退 platform.processor() 喵。
    """
    try:
        # 延迟导入 winreg，非 Windows 平台导入会失败喵
        import winreg

        # 打开 CPU 描述所在注册表项喵
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as cpu_key:
            # 读取型号字符串喵
            cpu_value, _value_type = winreg.QueryValueEx(cpu_key, "ProcessorNameString")
            # 去掉多余空白喵
            cleaned_value = str(cpu_value).strip()
            # 喵~防御：空字符串没有意义，继续往下兜底喵
            if cleaned_value:
                return cleaned_value
    except (ImportError, OSError, FileNotFoundError):
        # 喵~防御：读注册表失败时走平台兜底喵
        LOGGER.debug("读取注册表 CPU 型号失败，改用 platform.processor()")
    # 兜底方案，Windows 上可能返回空串喵
    fallback_value = platform.processor().strip()
    # 喵~防御：兜底也拿不到时返回"未知"，渲染层会原样展示喵
    return fallback_value or "未知"


def read_gpu_name_from_registry() -> str:
    """从注册表读取显卡型号喵。

    输入：无。
    输出：型号字符串，读不到时返回空串（由调用方决定兜底文案）。
    边界：非 Windows、注册表被策略锁定、键不存在都返回空串，不抛异常喵。
    """
    # 喵~防御：非 Windows 平台没有注册表，直接返回空串喵
    if sys.platform != "win32":
        return ""
    try:
        # 延迟导入 winreg，非 Windows 平台导入会失败喵
        import winreg
    except ImportError:
        # 喵~防御：导入失败按读不到处理喵
        return ""
    try:
        # 打开"显示适配器"设备类所在的注册表项喵
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_CLASS_PATH) as class_key:
            # 枚举它的子键，形如 0000 / 0001 的就是一块显卡喵
            subkey_names: list[str] = []
            # 喵~注意：EnumKey 靠索引递增遍历，取不到就抛 OSError 表示到头了喵
            index = 0
            while True:
                try:
                    subkey_names.append(winreg.EnumKey(class_key, index))
                except OSError:
                    break
                index += 1
    except OSError:
        # 喵~防御：注册表读不了属于正常情况，交给上层兜底喵
        LOGGER.debug("打开显卡注册表项失败，改用其它方式取型号")
        return ""
    # 喵~注意：子键名是字典序，这里排一下保证多显卡时取的顺序稳定喵
    for subkey_name in sorted(subkey_names):
        # 只认四位数字的显卡实例键，跳过 Properties 之类的附属键喵
        if not GPU_SUBKEY_PATTERN.fullmatch(subkey_name):
            continue
        # 读这块显卡的型号喵
        gpu_name = _read_gpu_name_from_subkey(subkey_name)
        # 喵~防御：第一块读到了就直接用，和 wmic 只取一块的口径一致喵
        if gpu_name:
            return gpu_name
    # 喵~防御：枚举完一块都没读到，返回空串喵
    return ""


def _read_gpu_name_from_subkey(subkey_name: str) -> str:
    """读取单个显卡子键下的型号值喵。

    输入：形如 "0000" 的子键名。
    输出：型号字符串，读不到返回空串。
    边界：值名不存在或类型不是字符串都返回空串喵。
    """
    try:
        # 延迟导入，与调用方保持一致喵
        import winreg

        # 拼出这块显卡的完整路径喵
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{GPU_CLASS_PATH}\{subkey_name}") as gpu_key:
            # 按候选值名逐个尝试，不同驱动写的键名不一样喵
            for value_name in GPU_REGISTRY_VALUE_NAMES:
                try:
                    raw_value, _value_type = winreg.QueryValueEx(gpu_key, value_name)
                except OSError:
                    # 喵~防御：这个值名没有就试下一个喵
                    continue
                # 清掉空白喵
                cleaned_value = str(raw_value).strip()
                # 喵~防御：空字符串没有意义，继续试下一个值名喵
                if cleaned_value:
                    return cleaned_value[:MAX_GPU_NAME_LENGTH]
    except (OSError, ImportError):
        # 喵~防御：单个子键读失败、或平台没有 winreg，都不影响其它显卡喵
        return ""
    # 喵~防御：候选值名都没有，返回空串喵
    return ""


def read_gpu_name() -> str:
    """读取显卡型号喵。

    输入：无。
    输出：型号字符串，取不到时返回 "未知"。
    边界：优先走注册表（wmic 自 Win11 24H2 起已不在系统里），
    注册表读不到时才回退到 wmic，两者都失败返回 "未知"喵。
    """
    # 喵~注意：注册表优先，既不弹黑窗也不依赖已弃用的 wmic 喵
    registry_name = read_gpu_name_from_registry()
    # 喵~防御：注册表读到了就不必再起子进程喵
    if registry_name:
        return registry_name
    # 喵~防御：注册表没读到（老系统/策略限制）时回退到 wmic 喵
    return _read_gpu_name_from_wmic()


def _read_gpu_name_from_wmic() -> str:
    """用 wmic 读取显卡型号，作为注册表读不到时的兜底喵。

    输入：无。
    输出：型号字符串，取不到时返回 "未知"。
    边界：wmic 不存在、执行超时、解码异常、输出为空都返回 "未知"喵。
    """
    try:
        # 调用 wmic 查询显卡名称喵
        completed_process = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True,
            text=True,
            timeout=WMIC_TIMEOUT_SECONDS,
            check=False,
            # 喵~注意：不加这个 GUI 进程会为 wmic 弹出黑窗口，每半小时闪一下喵
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            # 喵~防御：输出编码不确定时用替换字符兜底，别让 UnicodeDecodeError 掀翻采集循环喵
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        # 喵~防御：新版 Windows 已移除 wmic，属于正常情况喵
        LOGGER.debug("wmic 调用失败，显卡型号未知")
        return "未知"
    # 逐行清洗输出，去掉表头与空行喵
    candidate_lines = [
        line.strip()
        for line in (completed_process.stdout or "").splitlines()
        if line.strip() and line.strip().lower() != "name"
    ]
    # 喵~防御：没有输出时返回"未知"喵
    if not candidate_lines:
        return "未知"
    # 多显卡时只取第一块，避免字符串过长喵
    return candidate_lines[0][:MAX_GPU_NAME_LENGTH]



def read_os_version() -> str:
    """读取操作系统版本喵。"""
    # 拼成 "Windows 10 (10.0.14393)" 这样的形式喵
    return f"{platform.system()} {platform.release()} ({platform.version()})"


def read_disk_summary() -> str:
    """汇总各固定磁盘的可用空间喵。"""
    # 收集形如 "C: 17.4GB 可用" 的片段喵
    disk_parts: list[str] = []
    try:
        # 遍历所有分区喵
        for partition in psutil.disk_partitions(all=False):
            # 喵~防御：部分虚拟分区没有可用空间信息，跳过喵
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (PermissionError, OSError):
                continue
            # 换算成 GB 并保留一位小数喵
            free_gigabytes = usage.free / (1024**3)
            disk_parts.append(f"{partition.mountpoint.rstrip(chr(92))} {free_gigabytes:.1f}GB 可用")
            # 最多统计 3 个分区，避免信息太长喵
            if len(disk_parts) >= 3:
                break
    except (OSError, RuntimeError):
        # 喵~防御：分区枚举失败时返回"未知"喵
        return "未知"
    # 喵~防御：一个分区都没取到时返回"未知"喵
    return "，".join(disk_parts) if disk_parts else "未知"


def collect_hardware() -> dict[str, str]:
    """采集一组硬件信息键值对喵。

    输入：无。
    输出：键名与服务端渲染层约定的中文标签对应的字典喵。
    边界：任何单项采集失败都不会抛异常，只会返回"未知"喵。
    """
    # 内存总量换算成 GB 并保留整数喵
    total_memory_gigabytes = psutil.virtual_memory().total / (1024**3)
    # 返回硬件信息字典喵
    return {
        "hostname": platform.node() or "未知",
        "os_version": read_os_version(),
        "cpu": read_cpu_name(),
        "ram_gb": f"{total_memory_gigabytes:.0f}",
        "gpu": read_gpu_name(),
        "disk": read_disk_summary(),
    }


def read_battery() -> tuple[int, bool] | None:
    """读取电量与充电状态喵。

    输入：无。
    输出：(电量百分比, 是否充电中)；台式机没有电池时返回 None。
    边界：读数越界时夹到 0 到 100 之间喵。
    """
    try:
        # psutil 在没有电池的设备上返回 None 喵
        battery_info = psutil.sensors_battery()
    except (AttributeError, OSError):
        # 喵~防御：某些系统上读取电池会抛异常，按无电池处理喵
        return None
    # 喵~防御：台式机没有电池，直接返回 None 喵
    if battery_info is None:
        return None
    # 电量取整并夹到合法范围喵
    percent_value = int(round(battery_info.percent))
    percent_value = min(100, max(0, percent_value))
    # 返回电量与充电状态喵
    return percent_value, bool(battery_info.power_plugged)


def is_remote_session() -> bool:
    """判断当前会话是不是远程桌面会话喵。

    输出：True 表示跑在 RDP 会话里；非 Windows 或取不到时返回 False。
    """
    # 取 user32 句柄喵
    window_api = _user32()
    # 喵~防御：非 Windows 平台没有这个概念喵
    if window_api is None:
        return False
    try:
        # 喵~防御：GetSystemMetrics 理论上不会失败，但被注入时可能抛异常喵
        return bool(window_api.GetSystemMetrics(SM_REMOTESESSION))
    except (AttributeError, OSError):
        # 喵~防御：取不到就按本地会话处理，宁可多统计也不要漏统计喵
        return False


def session_connect_state() -> int | None:
    """读取当前会话的连接状态喵。

    输出：WTS_CONNECTSTATE_CLASS 数值；取不到时返回 None。
    边界：RDP 断开但会话仍在时通常是 4（WTSDisconnected）喵。
    """
    # 喵~防御：非 Windows 平台直接返回 None 喵
    if platform.system() != "Windows":
        return None
    try:
        # 加载 WTS API 喵
        wts_api = ctypes.windll.wtsapi32
        # 显式声明参数类型，避免 64 位下指针被截断喵
        wts_api.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        wts_api.WTSQuerySessionInformationW.restype = ctypes.c_bool
        wts_api.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        # 接收返回缓冲区喵
        buffer_pointer = ctypes.c_void_p()
        returned_bytes = ctypes.c_ulong()
        # 查询当前会话的连接状态喵
        succeeded = wts_api.WTSQuerySessionInformationW(
            None,
            WTS_CURRENT_SESSION,
            WTS_CONNECT_STATE_INFO,
            ctypes.byref(buffer_pointer),
            ctypes.byref(returned_bytes),
        )
        # 喵~防御：查询失败时返回 None，让上层用保守策略喵
        if not succeeded or not buffer_pointer:
            return None
        try:
            # 缓冲区里是一个 int 枚举喵
            return int(ctypes.cast(buffer_pointer, ctypes.POINTER(ctypes.c_int)).contents.value)
        finally:
            # 喵~防御：WTS 分配的内存必须释放，否则每次调用都泄漏喵
            wts_api.WTSFreeMemory(buffer_pointer)
    except (AttributeError, OSError):
        # 喵~防御：老系统或权限受限时按未知处理喵
        return None


def detect_rdp_active() -> bool:
    """判断 RDP 是否处于"已连接且有人操作"的状态喵。

    规则（主人定的口径）：只有远程会话处于活动状态才算已连接，
    断开但会话保持（disconnected）不算喵。

    输出：True 表示应当统计；False 表示应暂停统计。
    """
    # 不是远程会话时，本地使用不需要门控喵
    if not is_remote_session():
        return False
    # 取会话连接状态喵
    connect_state = session_connect_state()
    # 喵~防御：拿不到状态时保守地按"已连接"处理，避免误暂停喵
    if connect_state is None:
        return True
    # 只有活动状态才算已连接喵
    return connect_state == WTS_ACTIVE_STATE


def _wts_query(session_id: int, info_class: int) -> bytes | None:
    """查询 WTS 会话信息，返回原始字节喵。

    输入：会话 ID（WTS_CURRENT_SESSION 表示当前会话）、信息类编号。
    输出：缓冲区字节；非 Windows 或调用失败时返回 None。
    边界：内部自己释放 WTS 分配的内存，调用方不用管喵。
    """
    # 喵~防御：非 Windows 平台没有 WTS 喵
    if platform.system() != "Windows":
        return None
    try:
        # 加载 WTS API 喵
        wts_api = ctypes.windll.wtsapi32
        # 显式声明参数与返回值类型，避免 64 位下指针被截断喵
        wts_api.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        wts_api.WTSQuerySessionInformationW.restype = ctypes.c_bool
        wts_api.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        # 接收返回缓冲区喵
        buffer_pointer = ctypes.c_void_p()
        returned_bytes = ctypes.c_ulong()
        succeeded = wts_api.WTSQuerySessionInformationW(
            None,
            session_id,
            info_class,
            ctypes.byref(buffer_pointer),
            ctypes.byref(returned_bytes),
        )
        # 喵~防御：查询失败时返回 None，让上层用兜底逻辑喵
        if not succeeded or not buffer_pointer:
            return None
        try:
            # 按返回长度拷出字节喵
            return ctypes.string_at(buffer_pointer, returned_bytes.value)
        finally:
            # 喵~防御：WTS 分配的内存必须释放，否则每次调用都泄漏喵
            wts_api.WTSFreeMemory(buffer_pointer)
    except (AttributeError, OSError):
        # 喵~防御：老系统或权限受限时按未知处理喵
        return None


def rdp_client_info() -> tuple[str, str]:
    """读取连进来的 RDP 客户端 IP 与机器名喵。

    输出：(IP 文本, 机器名)；非远程会话或取不到时对应位置为空串。
    边界：IPv4 与 IPv6 都支持；本机回环地址（frp/tailscale 中转）原样返回喵。
    """
    # 喵~防御：不是远程会话就没有客户端喵
    if not is_remote_session():
        return "", ""
    # 先取地址结构体喵
    raw_address = _wts_query(WTS_CURRENT_SESSION, WTS_CLIENT_ADDRESS_INFO)
    # 机器名喵
    raw_name = _wts_query(WTS_CURRENT_SESSION, WTS_CLIENT_NAME_INFO)
    # 解析 IP 喵
    ip_text = ""
    if raw_address and len(raw_address) >= ctypes.sizeof(_WtsClientAddress):
        address = _WtsClientAddress.from_buffer_copy(raw_address)
        # 前两字节是端口占位，真正的地址从第 2 字节开始喵
        if address.AddressFamily == AF_INET:
            ip_text = ".".join(str(byte) for byte in address.Address[2:6])
        elif address.AddressFamily == AF_INET6:
            # 16 字节按两字节一组转成十六进制喵
            groups = [f"{address.Address[2 + index * 2]:02x}{address.Address[3 + index * 2]:02x}" for index in range(8)]
            ip_text = ":".join(groups)
    # 解析机器名喵
    name_text = ""
    if raw_name:
        # WTS 返回的是以 \0 结尾的 UTF-16LE 字符串喵
        name_text = raw_name.decode("utf-16-le", errors="ignore").split("\x00", 1)[0].strip()
    return ip_text, name_text


def _collect_visible_window_titles() -> list[tuple[int, str]]:
    """枚举所有可见窗口的 (进程 ID, 标题) 喵。

    输出：列表；非 Windows 或枚举失败时返回空列表。
    """
    # 取 user32 句柄喵
    window_api = _user32()
    # 喵~防御：非 Windows 平台直接返回空喵
    if window_api is None:
        return []
    # 收集结果喵
    collected: list[tuple[int, str]] = []

    def _callback(window_handle: int, _lparam: int) -> bool:
        """EnumWindows 回调：只收集可见且有标题的窗口喵。"""
        # 喵~防御：隐藏窗口没有参考价值喵
        if not window_api.IsWindowVisible(window_handle):
            return True
        # 取标题长度喵
        title_length = window_api.GetWindowTextLengthW(window_handle)
        # 喵~防御：空标题窗口跳过喵
        if title_length <= 0:
            return True
        # 读取标题喵
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        window_api.GetWindowTextW(window_handle, title_buffer, title_length + 1)
        # 取窗口所属进程喵
        process_id = ctypes.c_ulong()
        window_api.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
        # 收集结果喵
        collected.append((int(process_id.value), title_buffer.value))
        return True

    try:
        # 声明回调类型喵
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        callback = callback_type(_callback)
        # 枚举顶层窗口喵
        window_api.EnumWindows(callback, 0)
    except (AttributeError, OSError, ValueError):
        # 喵~防御：枚举失败时返回已收集到的部分，不影响主循环喵
        LOGGER.debug("枚举窗口失败，投屏识别结果可能不完整")
    return collected


def list_mirror_windows(process_names: Sequence[str]) -> list[str]:
    """找出投屏工具的窗口标题，供服务端匹配安卓标签喵。

    输入：投屏工具进程名列表，例如 ["scrcpy.exe"]。
    输出：这些进程的可见窗口标题列表，最多 16 条。
    边界：
      - 工具没运行、窗口最小化到托盘、或标题为空时返回空列表；
      - 返回空列表时服务端会认为"没有投屏会话"，安卓设备照常统计喵。
    """
    # 归一化进程名，统一小写比较喵
    target_names = {name.strip().lower() for name in process_names if name and name.strip()}
    # 喵~防御：没配置进程名就没有投屏识别喵
    if not target_names:
        return []
    # 找出目标进程的 PID 喵
    target_pids: set[int] = set()
    try:
        for process in psutil.process_iter(["pid", "name"]):
            # 喵~防御：进程可能刚好退出，取不到名字就跳过喵
            process_name = (process.info.get("name") or "").lower()
            if process_name in target_names:
                target_pids.add(int(process.info["pid"]))
    except (psutil.Error, OSError):
        # 喵~防御：进程枚举失败时按没有投屏处理喵
        LOGGER.debug("枚举投屏进程失败")
        return []
    # 喵~防御：工具没运行就没有投屏会话喵
    if not target_pids:
        return []
    # 收集这些进程的窗口标题喵
    titles: list[str] = []
    for process_id, title in _collect_visible_window_titles():
        # 只保留目标进程的窗口喵
        if process_id not in target_pids:
            continue
        # 去掉首尾空白喵
        cleaned_title = title.strip()
        # 喵~防御：空标题没有匹配价值喵
        if not cleaned_title:
            continue
        # 截断并收集喵
        titles.append(cleaned_title[:MAX_WINDOW_TITLE_LENGTH])
    # 去重并限制条数喵
    unique_titles = list(dict.fromkeys(titles))
    return unique_titles[:MAX_MIRROR_WINDOWS]


# EnumWindows 回调类型：参数是窗口句柄与 lParam 喵
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

# 单次上报最多带多少个窗口喵
MAX_OPEN_WINDOWS = 80

# 不参与统计的窗口标题，都是系统壳层喵
SKIPPED_WINDOW_TITLES = frozenset(
    {
        "Program Manager",
        "Windows 输入体验",
        "Microsoft Text Input Application",
        "Default IME",
        "MSCTFIME UI",
    }
)


@dataclass(frozen=True)
class WindowInfo:
    """一个已打开窗口的快照喵。"""

    # 应用展示名，例如 Chrome 喵
    app: str
    # 进程名，例如 chrome.exe 喵
    package: str
    # 窗口标题喵
    title: str
    # 是否最小化喵
    minimized: bool
    # 是否在前台喵
    foreground: bool


def list_open_windows() -> list[WindowInfo]:
    """枚举当前所有可见的顶层窗口喵。

    输入：无。
    输出：WindowInfo 列表，最多 MAX_OPEN_WINDOWS 条；非 Windows 平台返回空列表。
    边界：单个窗口取信息失败只跳过它，绝不让整轮采集失败喵。
    """
    # 取 user32 句柄喵
    window_api = _user32()
    # 喵~防御：非 Windows 平台没法枚举喵
    if window_api is None:
        return []
    # 前台窗口句柄，用来标记 foreground 喵
    foreground_handle = window_api.GetForegroundWindow()
    # 当前进程 PID，自己的窗口不统计喵
    own_pid = os.getpid()
    # 收集结果喵
    windows: list[WindowInfo] = []
    # 已出现过的 (进程名, 标题)，避免同一个窗口被列两次喵
    seen: set[tuple[str, str]] = set()

    # 枚举回调喵
    def _callback(handle: int, _param: int) -> bool:
        """处理单个窗口，返回 True 继续枚举喵。"""
        try:
            # 喵~防御：不可见窗口不统计喵
            if not window_api.IsWindowVisible(handle):
                return True
            # 取标题长度，0 表示没有标题喵
            title_length = window_api.GetWindowTextLengthW(handle)
            if title_length <= 0:
                return True
            # 读标题喵
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            window_api.GetWindowTextW(handle, title_buffer, title_length + 1)
            # 清掉浏览器标题里的零宽字符与配置名尾巴喵
            title = normalize_window_title(title_buffer.value)
            # 喵~防御：空标题与系统壳层窗口跳过喵
            if not title or title in SKIPPED_WINDOW_TITLES:
                return True
            # 取进程 ID 喵
            process_id = ctypes.c_ulong()
            window_api.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
            if process_id.value == 0 or process_id.value == own_pid:
                return True
            # 查进程名，用字典缓存避免重复查询喵
            process_name = _cached_process_name(process_id.value)
            if not process_name:
                return True
            # 展示名去掉 .exe 后缀喵
            display_name = (
                process_name[:-4] if process_name.lower().endswith(".exe") else process_name
            )
            # 喵~防御：同一个应用的同名窗口只记一次喵
            key = (process_name, title)
            if key in seen:
                return True
            seen.add(key)
            # 是否最小化喵
            minimized = bool(window_api.IsIconic(handle))
            # 追加结果喵
            windows.append(
                WindowInfo(
                    app=display_name or process_name,
                    package=process_name,
                    title=title,
                    minimized=minimized,
                    foreground=bool(foreground_handle) and handle == foreground_handle,
                )
            )
        except (OSError, ValueError, ctypes.ArgumentError):
            # 喵~防御：单个窗口出错就跳过，不影响其它窗口喵
            pass
        # 够数了就停止枚举喵
        return len(windows) < MAX_OPEN_WINDOWS

    try:
        # 开始枚举喵
        window_api.EnumWindows(WNDENUMPROC(_callback), 0)
    except (OSError, ValueError, ctypes.ArgumentError):
        # 喵~防御：枚举失败时返回已经收集到的部分喵
        pass
    # 前台窗口排最前，方便上层直接取第一条喵
    windows.sort(key=lambda item: (not item.foreground, item.app.lower()))
    return windows[:MAX_OPEN_WINDOWS]


# 进程名缓存，避免枚举几十个窗口时反复查 psutil 喵
_PROCESS_NAME_CACHE: dict[int, str] = {}


def _cached_process_name(process_id: int) -> str:
    """带缓存的进程名查询喵。"""
    # 命中缓存直接返回喵
    if process_id in _PROCESS_NAME_CACHE:
        return _PROCESS_NAME_CACHE[process_id]
    # 喵~注意：和前台采集共用同一个兜底逻辑，提权窗口也能拿到名字喵
    name = lookup_process_name(process_id)
    # 喵~防御：查不到就记空串，下次还会重试喵
    if not name:
        return ""
    # 写缓存喵
    _PROCESS_NAME_CACHE[process_id] = name
    return name

# 进程名（小写）到 exe 路径的缓存，给图标上传用喵
_EXE_PATH_CACHE: dict[str, str] = {}

# 缓存刷新时间戳，避免每次采样都遍历全系统进程喵
_EXE_PATH_CACHE_AT: float = 0.0

# 缓存有效期（秒）喵
EXE_PATH_CACHE_SECONDS = 120.0


def exe_path_map(now: float | None = None, max_age: float = EXE_PATH_CACHE_SECONDS) -> dict[str, str]:
    """返回「进程名小写 -> exe 绝对路径」的映射喵。

    输入：可选的当前时间戳、缓存有效期。
    输出：字典副本，拿不到路径的进程不在其中。
    边界：单个进程权限不足只跳过它，绝不抛异常喵。
    """
    global _EXE_PATH_CACHE_AT
    # 当前时间喵
    current = time.monotonic() if now is None else now
    # 喵~防御：缓存还在有效期内就直接复用，别每轮都遍历进程喵
    if _EXE_PATH_CACHE and (current - _EXE_PATH_CACHE_AT) < max_age:
        return dict(_EXE_PATH_CACHE)
    # 重新扫描喵
    fresh: dict[str, str] = {}
    for process in psutil.process_iter(["name", "exe"]):
        try:
            # 取进程名与路径喵
            name = process.info.get("name") or ""
            exe = process.info.get("exe") or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # 喵~防御：进程刚好退出或没权限，跳过喵
            continue
        # 喵~防御：路径为空说明查不到，跳过喵
        if not name or not exe:
            continue
        # 同名进程保留第一个，够用了喵
        fresh.setdefault(name.lower(), exe)
    # 写回缓存喵
    _EXE_PATH_CACHE.clear()
    _EXE_PATH_CACHE.update(fresh)
    _EXE_PATH_CACHE_AT = current
    return dict(_EXE_PATH_CACHE)


def reset_exe_path_cache() -> None:
    """清空 exe 路径缓存，主要给测试用喵。"""
    # 清空字典与时间戳喵
    _EXE_PATH_CACHE.clear()
    globals()["_EXE_PATH_CACHE_AT"] = 0.0
