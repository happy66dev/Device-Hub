"""应用图标采集。

Windows 上没有跨平台的图标 API，这里用 ctypes 直接调 Win32：
ExtractIconExW 拿 HICON → DrawIconEx 画进 32 位 DIB → 读像素 → 自己编码 PNG。
这样做的好处是不引入 Pillow，采集端仍然只有 psutil + httpx 两个依赖喵。
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import logging
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("device_hub.icons")

# 图标边长，32x32 在网页里显示刚好喵
ICON_SIZE = 32

# 抠出来的图标至少要有这么多百分比的不透明像素，否则当作失败喵
MIN_OPAQUE_PERCENT = 5

# PNG 文件头喵
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# DrawIconEx 的正常绘制标志喵
DI_NORMAL = 0x0003

# BI_RGB：不压缩的 DIB 喵
BI_RGB = 0


class _BitmapInfoHeader(ctypes.Structure):
    """Win32 BITMAPINFOHEADER 结构喵。"""

    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    """Win32 BITMAPINFO 结构喵。"""

    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", ctypes.c_uint32 * 3)]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """拼一个 PNG 数据块（长度 + 标签 + 数据 + CRC）喵。"""
    # 计算 CRC 喵
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    # 按 PNG 规范拼装喵
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """把 RGBA 像素编码成 PNG 字节喵。

    输入：宽、高、按行排列的 RGBA 像素。
    输出：完整的 PNG 文件字节。
    """
    # 喵~防御：像素数据长度必须对得上，否则编码出来的图是坏的喵
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"像素长度应为 {expected}，实际 {len(rgba)}")
    # 每行前面加一个 0 表示「不过滤」喵
    raw = b"".join(
        b"\x00" + rgba[row * width * 4 : (row + 1) * width * 4] for row in range(height)
    )
    # IHDR：宽、高、8 位色深、RGBA、无压缩无过滤无隔行喵
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # 拼成完整文件喵
    return PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(
        b"IDAT", zlib.compress(raw, 9)
    ) + _png_chunk(b"IEND", b"")


def bgra_to_rgba(pixels: bytes) -> bytes:
    """把 Win32 的 BGRA 像素转成 PNG 需要的 RGBA 喵。"""
    # 逐像素换通道喵
    out = bytearray(len(pixels))
    out[0::4] = pixels[2::4]
    out[1::4] = pixels[1::4]
    out[2::4] = pixels[0::4]
    out[3::4] = pixels[3::4]
    return bytes(out)


# SHGetFileInfoW 用到的结构，装的是外壳给的图标句柄喵
class _ShellFileInfo(ctypes.Structure):
    """Win32 SHFILEINFOW 结构喵。"""

    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_uint32),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


# SHGFI_ICON：要图标句柄；SHGFI_LARGEICON：要 32x32 的大图标喵
SHGFI_ICON = 0x00000100
SHGFI_LARGEICON = 0x00000000

# CoInitializeEx 的单元线程模型喵
COINIT_APARTMENTTHREADED = 0x2

# 已声明的 Win32 函数集合，声明一次反复用喵
_API_CACHE: dict[str, Any] | None = None


def _load_api() -> dict[str, Any] | None:
    """加载并声明图标相关的 Win32 函数喵。

    输出：包含各 DLL 与结构的字典；非 Windows 或加载失败时返回 None。
    """
    global _API_CACHE
    # 喵~防御：非 Windows 平台没有这些接口喵
    if sys.platform != "win32":
        return None
    # 命中缓存直接复用喵
    if _API_CACHE is not None:
        return _API_CACHE
    try:
        # 加载需要的 DLL 喵
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        # 喵~防御：ExtractIconExW 在 shell32 里，不在 user32 喵
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        # 外壳图标要先初始化 COM，失败（已初始化过）也不影响喵
        try:
            ctypes.WinDLL("ole32", use_last_error=True).CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        except (OSError, AttributeError):
            pass
        # 声明用到的函数签名喵
        shell32.ExtractIconExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint,
        ]
        shell32.ExtractIconExW.restype = ctypes.c_uint
        # 按目标尺寸直接抠图，比 ExtractIconEx 更能命中多尺寸图标喵
        # 喵~防御：这个导出在 user32 里，老系统上也可能没有，单独兜住喵
        private_extract = None
        for module in (user32, shell32):
            try:
                candidate = module.PrivateExtractIconsW
            except AttributeError:
                continue
            candidate.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_uint),
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            candidate.restype = ctypes.c_uint
            private_extract = candidate
            break
        # 外壳图标兜底喵
        shell32.SHGetFileInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(_ShellFileInfo),
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        shell32.SHGetFileInfoW.restype = ctypes.c_size_t
        user32.GetDC.restype = ctypes.c_void_p
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.DrawIconEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.CreateDIBSection.restype = ctypes.c_void_p
        gdi32.CreateDIBSection.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_BitmapInfo),
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        gdi32.SelectObject.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        # 存起来复用喵
        _API_CACHE = {
            "user32": user32,
            "gdi32": gdi32,
            "shell32": shell32,
            "private_extract": private_extract,
        }
        return _API_CACHE
    except (OSError, AttributeError) as error:
        # 喵~防御：加载失败只记日志，图标功能降级但不影响采集喵
        LOGGER.debug("加载 Win32 图标接口失败：%s", error)
        return None


def _icons_from_extract_ex(api: dict[str, Any], exe_path: str) -> list[int]:
    """方式一：ExtractIconExW 抠出 exe 里第 0 个图标喵。"""
    # 两个句柄都要接住，避免泄漏喵
    large = ctypes.c_void_p()
    small = ctypes.c_void_p()
    extracted = api["shell32"].ExtractIconExW(exe_path, 0, ctypes.byref(large), ctypes.byref(small), 1)
    # 收集非空句柄喵
    handles = [handle.value for handle in (large, small) if handle.value]
    # 喵~防御：一个都没抠到就返回空列表喵
    if extracted == 0:
        return []
    return handles


def _icons_from_private_extract(api: dict[str, Any], exe_path: str, size: int) -> list[int]:
    """方式二：PrivateExtractIconsW 按目标尺寸抠图喵。"""
    # 喵~防御：系统没这个导出就跳过喵
    extract = api.get("private_extract")
    if extract is None:
        return []
    # 目标句柄喵
    handle = ctypes.c_void_p()
    # 图标 ID 输出参数，可以不关心喵
    icon_id = ctypes.c_uint(0)
    count = extract(exe_path, 0, size, size, ctypes.byref(handle), ctypes.byref(icon_id), 1, 0)
    # 喵~防御：抠不到就返回空列表喵
    if count == 0 or not handle.value:
        return []
    return [handle.value]


def _icons_from_shell(api: dict[str, Any], exe_path: str) -> list[int]:
    """方式三：SHGetFileInfoW 走外壳图标，兜住前两种抠不出的应用喵。"""
    # 外壳信息结构喵
    info = _ShellFileInfo()
    # 请求 32x32 大图标喵
    result = api["shell32"].SHGetFileInfoW(
        exe_path, 0, ctypes.byref(info), ctypes.sizeof(_ShellFileInfo), SHGFI_ICON | SHGFI_LARGEICON
    )
    # 喵~防御：外壳也没给图标就返回空列表喵
    if result == 0 or not info.hIcon:
        return []
    return [info.hIcon]


def _hicon_to_png(api: dict[str, Any], handle: int, size: int) -> bytes | None:
    """把一个 HICON 画进 32 位 DIB 并编码成 PNG 喵。

    输入：Win32 函数集合、图标句柄、目标边长。
    输出：PNG 字节；画不出来时返回 None。
    """
    # 取 GDI 句柄喵
    user32 = api["user32"]
    gdi32 = api["gdi32"]
    # 准备内存 DC 与 32 位 DIB 喵
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    info = _BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
    info.bmiHeader.biWidth = size
    # 负数高度表示自上而下存像素，正好对上 PNG 的行序喵
    info.bmiHeader.biHeight = -size
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), BI_RGB, ctypes.byref(bits), None, 0)
    # 喵~防御：DIB 建不出来就清理句柄退出喵
    if not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
        return None
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # 把图标画进 DIB 喵
        user32.DrawIconEx(memory_dc, 0, 0, handle, size, size, 0, None, DI_NORMAL)
        # 读像素喵
        raw = ctypes.string_at(bits, size * size * 4)
    finally:
        # 喵~防御：句柄一律在 finally 释放，避免泄漏喵
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
    # 喵~防御：整块像素全 0 说明根本没画上，放弃喵
    if not any(raw):
        return None
    # 转成 PNG 需要的通道顺序喵
    rgba = bytearray(bgra_to_rgba(raw))
    # 喵~防御：老式图标没有 alpha 通道，画出来 alpha 全是 0，这里统一补成不透明喵
    if not any(rgba[3::4]):
        rgba[3::4] = bytes([255]) * (size * size)
    # 喵~防御：不透明像素太少说明画歪了（比如只有几个杂点），当作抠图失败喵
    opaque = sum(1 for value in rgba[3::4] if value > 0)
    if opaque * 100 < size * size * MIN_OPAQUE_PERCENT:
        return None
    return encode_png(size, size, bytes(rgba))


def extract_icon_png(exe_path: str, size: int = ICON_SIZE) -> bytes | None:
    """从一个可执行文件里抠出图标并转成 PNG 喵。

    输入：exe 绝对路径、目标边长。
    输出：PNG 字节；非 Windows、文件不存在或三种方式都抠不到时返回 None。
    边界：所有 Win32 句柄都会在 finally 里释放，异常不外抛喵。
    """
    # 喵~防御：非 Windows 或文件不在时直接放弃喵
    if sys.platform != "win32" or not exe_path or not Path(exe_path).is_file():
        return None
    # 加载接口喵
    api = _load_api()
    if api is None:
        return None
    # 依次尝试三种抠图方式，先成功先用喵
    attempts = (
        ("ExtractIconEx", lambda: _icons_from_extract_ex(api, exe_path)),
        ("PrivateExtractIcons", lambda: _icons_from_private_extract(api, exe_path, size)),
        ("SHGetFileInfo", lambda: _icons_from_shell(api, exe_path)),
    )
    for name, extract in attempts:
        handles: list[int] = []
        try:
            handles = extract()
        except (OSError, ValueError, AttributeError, ctypes.ArgumentError) as error:
            # 喵~防御：某种方式失败就换下一种，绝不外抛喵
            LOGGER.debug("%s 抠图失败 %s：%s", name, exe_path, error)
            continue
        # 喵~防御：这次没抠到就换下一种喵
        if not handles:
            continue
        try:
            # 用第一个句柄画图喵
            png = _hicon_to_png(api, handles[0], size)
        finally:
            # 所有句柄都要销毁喵
            for handle in handles:
                api["user32"].DestroyIcon(ctypes.c_void_p(handle))
        # 喵~防御：画出来是空的就换下一种喵
        if png is not None:
            return png
        LOGGER.debug("%s 抠到的图标画不出像素 %s", name, exe_path)
    # 三种都不行喵
    return None


def content_hash(png_bytes: bytes) -> str:
    """算图标内容的短哈希喵。

    输入：PNG 字节。
    输出：sha1 十六进制前 16 位，与服务端、安卓端口径完全一致。
    边界：空字节也算出合法值，不抛异常喵。
    """
    # 三端统一口径：对 PNG 原始字节求 sha1，取十六进制前 16 位喵
    return hashlib.sha1(png_bytes).hexdigest()[:16]


def _icon_identity(app_name: str, package: str) -> tuple[str, str]:
    """图标记录的键：包名去空白并小写，避免大小写差异导致重复上传喵。

    输入：应用名、包名（可为空）。
    输出：(应用名原样, 规范化包名)。
    边界：规范化规则必须与服务端 icons.icon_key() 一致，否则会「有记录却查不到」喵。
    """
    # 应用名保持大小写敏感，与服务端一致喵
    # 包名去空白再小写，采集端上报的使用记录里 exe 名本来就是小写喵
    return (str(app_name), str(package or "").strip().lower())


class IconUploader:
    """按内容哈希比对后上传应用图标，图标没变就不重传喵。"""

    # 同一个应用连续失败的次数上限，达到后本轮运行不再试，下次启动重新开始喵
    MAX_FAILURES = 3

    def __init__(self, reporter: Any) -> None:
        # 上报器，复用它的连接池与配置喵
        self._reporter = reporter
        # 服务端已有图标的「(应用名, 包名) → 内容哈希」映射喵
        self._known: dict[tuple[str, str], str] = {}
        # 本次运行里各应用的连续失败次数喵
        # 喵~注意：按 (应用名, 包名) 记而不是只按应用名，同名不同包才能各自重试喵
        self._failed: dict[tuple[str, str], int] = {}

    def prime(self) -> None:
        """启动时把服务端已有图标的内容哈希拉下来，供后续比对喵。"""
        try:
            # 让上报器去查列表喵
            entries = self._reporter.list_icons()
        except Exception as error:  # noqa: BLE001 - 喵~防御：拉列表失败不影响采集喵
            LOGGER.debug("拉取图标列表失败：%s", error)
            return
        # 记进已知映射喵
        for entry in entries:
            # 取服务端算好的内容哈希喵
            server_hash = str(entry.get("content_hash") or "")
            # 喵~防御：老服务端不返回哈希时当作「没有记录」，宁可贵一次重传也不要漏传喵
            if not server_hash:
                continue
            # 用与服务端一致的规范化规则存键喵
            self._known[_icon_identity(entry.get("app", ""), entry.get("package", ""))] = server_hash
        LOGGER.info("服务端已有 %d 张应用图标", len(self._known))

    def ensure(self, app_name: str, exe_path: str, package: str = "") -> None:
        """确保某个应用的图标是最新的喵。

        输入：应用名、exe 路径、包名（Windows 通常为空）。
        输出：无。
        边界：失败只记 debug 日志，绝不影响上报主流程喵。
        """
        # 喵~防御：空应用名直接跳过喵
        if not app_name:
            return
        # 算规范化后的记录键喵
        identity = _icon_identity(app_name, package)
        # 喵~防御：连续失败太多次就先停手，避免每轮都白跑一次 Win32 抠图喵
        if self._failed.get(identity, 0) >= self.MAX_FAILURES:
            return
        # 抠图标喵
        png_bytes = extract_icon_png(exe_path)
        if png_bytes is None:
            # 喵~注意：抠图失败只累加计数，不写进 _known，下次还有机会重试喵
            self._record_failure(identity)
            return
        # 算本地图标的内容哈希喵
        local_hash = content_hash(png_bytes)
        # 喵~注意：这是本次修复的核心——服务端哈希与本地一致才跳过，换了图标就要重传喵
        if self._known.get(identity) == local_hash:
            return
        # 上传喵
        ok, message = self._reporter.upload_icon(app_name, package, png_bytes)
        if ok:
            # 记下新哈希，避免同一张图反复上传喵
            self._known[identity] = local_hash
            # 成功一次就把失败计数清零喵
            self._failed.pop(identity, None)
            LOGGER.info("已上传应用图标：%s（%d 字节）", app_name, len(png_bytes))
        else:
            # 喵~防御：记一次失败，达到上限才停手，避免一次网络抖动就永久放弃喵
            self._record_failure(identity)
            LOGGER.debug("上传图标失败 %s：%s", app_name, message)

    def _record_failure(self, identity: tuple[str, str]) -> None:
        """记一次失败，供下一轮判断是否还要重试喵。

        输入：规范化后的 (应用名, 包名)。
        输出：无。
        边界：只累加计数，不抛出异常喵。
        """
        # 累加连续失败次数喵
        self._failed[identity] = self._failed.get(identity, 0) + 1


def encode_png_base64(png_bytes: bytes) -> str:
    """把 PNG 字节转成 base64 字符串，方便塞进 JSON 喵。"""
    # 标准 base64 编码喵
    return base64.b64encode(png_bytes).decode("ascii")
