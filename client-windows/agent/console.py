"""控制台与错误弹窗：让窗口化 exe 也能按需看日志喵。

打包成 `--noconsole` 的 exe 后，双击运行时没有黑窗口，日志只写文件；
加上 `--debug` 时调用 `attach_console()` 现场分配一个控制台，
把标准输出接过去，日志就能实时滚在窗口里喵。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 控制台窗口标题喵
CONSOLE_TITLE = "device-hub 采集端日志"

# MessageBox 的图标与按钮：只有"确定"按钮 + 错误图标喵
MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_SETFOREGROUND = 0x00010000


def has_console() -> bool:
    """判断当前进程是否已经挂了控制台喵。"""
    # 喵~防御：非 Windows 平台没有这个概念喵
    if sys.platform != "win32":
        return False
    try:
        # 取内核库句柄喵
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 返回窗口句柄，0 表示没有控制台喵
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        return bool(kernel32.GetConsoleWindow())
    except (OSError, AttributeError):
        # 喵~防御：拿不到就按"没有控制台"处理，不影响采集喵
        return False


def attach_console(title: str = CONSOLE_TITLE) -> bool:
    """确保进程有一个可写的控制台窗口喵。

    输入：窗口标题。
    输出：True 表示控制台可用。
    边界：命令行里本来就有控制台时不重复创建；创建失败返回 False 且不影响采集喵。
    """
    # 喵~防御：非 Windows 平台直接返回喵
    if sys.platform != "win32":
        return False
    try:
        # 取内核库句柄喵
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 声明返回值类型，避免 64 位下被截断喵
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        kernel32.AllocConsole.restype = wintypes.BOOL
        # 已经有控制台时只把标准流接好喵
        if not kernel32.GetConsoleWindow():
            # 喵~防御：分配失败（例如已被重定向）就放弃，采集继续跑喵
            if not kernel32.AllocConsole():
                LOGGER.debug("分配控制台失败，错误码 %s", ctypes.get_last_error())
                return False
            # 设置标题，方便任务栏里认出来喵
            kernel32.SetConsoleTitleW(title)
        # 把标准流接到新控制台喵
        _rebind_streams()
        return True
    except (OSError, AttributeError) as error:
        # 喵~防御：控制台只是辅助功能，出问题不能拖垮采集喵
        LOGGER.debug("创建控制台失败：%s", error)
        return False


def _rebind_streams() -> None:
    """把 sys.stdout / sys.stderr 重新指向控制台喵。"""
    try:
        # 打开控制台输出设备喵
        console_out = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - 进程生命周期内常驻喵
        # 输出与错误都指向它喵
        sys.stdout = console_out
        sys.stderr = console_out
    except OSError as error:
        # 喵~防御：拿不到控制台输出时保留原样喵
        LOGGER.debug("重定向控制台输出失败：%s", error)


def show_error(title: str, text: str) -> None:
    """没有控制台时用系统弹窗显示错误喵。

    输入：标题、正文。
    输出：无。
    边界：弹窗失败只记日志，绝不抛异常喵。
    """
    # 喵~防御：非 Windows 平台没有弹窗喵
    if sys.platform != "win32":
        return
    try:
        # 取用户库句柄喵
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # 声明参数类型，避免中文被截断喵
        user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        user32.MessageBoxW.restype = ctypes.c_int
        # 弹出模态提示喵
        user32.MessageBoxW(None, text, title, MB_OK | MB_ICONERROR | MB_SETFOREGROUND)
    except (OSError, AttributeError) as error:
        # 喵~防御：弹窗失败时至少写进日志文件喵
        LOGGER.warning("弹窗失败：%s（原文：%s）", error, text)
