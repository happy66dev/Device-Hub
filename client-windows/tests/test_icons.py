"""应用图标采集的单元测试喵。"""

from __future__ import annotations

import struct
import zlib
import os
import sys
import tempfile

import pytest
from pathlib import Path

from agent.icons import (
    IconUploader,
    bgra_to_rgba,
    content_hash,
    encode_png,
    encode_png_base64,
    extract_icon_png,
)

from agent import icons, main as main_module
from agent.collector import exe_path_map, reset_exe_path_cache


def _decode_png(png_bytes: bytes) -> tuple[int, int, bytes]:
    """解出 PNG 的宽高与原始像素，用来验证编码正确喵。"""
    # 喵~防御：先确认文件头喵
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    # 逐块解析喵
    offset = 8
    width = height = 0
    idat = b""
    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        tag = png_bytes[offset + 4 : offset + 8]
        data = png_bytes[offset + 8 : offset + 8 + length]
        if tag == b"IHDR":
            width, height = struct.unpack(">II", data[:8])
        elif tag == b"IDAT":
            idat += data
        offset += 12 + length
    return width, height, zlib.decompress(idat)


def test_encode_png_writes_valid_header() -> None:
    """编码结果应该是合法 PNG，且宽高正确喵。"""
    # 造一张 3x2 的纯红图喵
    pixels = bytes([255, 0, 0, 255]) * 6
    png_bytes = encode_png(3, 2, pixels)
    # 解析回来核对喵
    width, height, raw = _decode_png(png_bytes)
    assert (width, height) == (3, 2)
    # 每行前面应有一个过滤字节 0 喵
    assert len(raw) == 2 * (1 + 3 * 4)


def test_encode_png_rejects_wrong_length() -> None:
    """像素长度不对时要报错，而不是编出一张坏图喵。"""
    # 少给一个像素喵
    try:
        encode_png(2, 2, bytes([0, 0, 0, 255]) * 3)
    except ValueError as error:
        assert "像素长度" in str(error)
    else:
        raise AssertionError("应当抛出 ValueError")


def test_bgra_to_rgba_swaps_channels() -> None:
    """Win32 的 BGRA 要换成 RGBA，否则颜色会偏喵。"""
    # 一个蓝色像素（BGRA = 255,0,0,255）喵
    assert bgra_to_rgba(bytes([255, 0, 0, 255])) == bytes([0, 0, 255, 255])


def test_encode_png_base64_round_trip() -> None:
    """base64 只是包装，长度应当按 4/3 放大喵。"""
    # 编一张 1x1 图喵
    png_bytes = encode_png(1, 1, bytes([1, 2, 3, 255]))
    text = encode_png_base64(png_bytes)
    # base64 长度应当是 4 的倍数喵
    assert len(text) % 4 == 0
    assert text.startswith("iVBORw0KGgo")


def test_extract_icon_returns_none_for_missing_file() -> None:
    """文件不存在时要安全返回 None，不能抛异常喵。"""
    # 指向一个肯定不存在的路径喵
    assert extract_icon_png(str(Path("C:/definitely/not/here.exe"))) is None


def test_extract_icon_returns_none_for_empty_path() -> None:
    """空路径直接返回 None 喵。"""
    assert extract_icon_png("") is None


class _FakeReporter:
    """记录上传调用的假上报器喵。"""

    def __init__(self, existing: list[dict[str, str]] | None = None, ok: bool = True) -> None:
        # 预置的图标列表喵
        self.existing = existing or []
        # 上传是否成功喵
        self.ok = ok
        # 记录每次上传喵
        self.uploads: list[tuple[str, str]] = []

    def list_icons(self) -> list[dict[str, str]]:
        """返回预置列表喵。"""
        return self.existing

    def upload_icon(self, app: str, package: str, png_bytes: bytes) -> tuple[bool, str]:
        """记录一次上传喵。"""
        self.uploads.append((app, package))
        return self.ok, "ok"


def test_icon_uploader_skips_known_apps(monkeypatch) -> None:
    """服务端哈希与本地一致时不该重复上传喵。"""
    # 造一份固定 PNG 当抠图结果喵
    png_bytes = encode_png(32, 32, bytes([9, 200, 90, 255]) * 1024)
    # 预置服务端已有同一个应用，哈希就是这份 PNG 的哈希喵
    reporter = _FakeReporter(
        existing=[{"app": "Code", "package": "Code.exe", "content_hash": content_hash(png_bytes)}]
    )
    uploader = IconUploader(reporter)
    uploader.prime()
    # 抠图直接返回同一份 PNG 喵
    monkeypatch.setattr(icons, "extract_icon_png", lambda path, size=32: png_bytes)
    # 对已知应用调用 ensure 应该什么都不做喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert reporter.uploads == []


def test_icon_uploader_reuploads_when_icon_changed(monkeypatch) -> None:
    """喵~注意：本地换了图标，哈希对不上就必须重传，这是本次修复的核心喵。"""
    # 本地新图标喵
    png_bytes = encode_png(32, 32, bytes([9, 200, 90, 255]) * 1024)
    # 服务端记的是旧图标的哈希喵
    reporter = _FakeReporter(
        existing=[{"app": "Code", "package": "Code.exe", "content_hash": "0000000000000000"}]
    )
    uploader = IconUploader(reporter)
    uploader.prime()
    # 抠图返回本地新图标喵
    monkeypatch.setattr(icons, "extract_icon_png", lambda path, size=32: png_bytes)
    # 哈希不同，应当上传一次喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert reporter.uploads == [("Code", "Code.exe")]
    # 传过之后再调就不该重复传了喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert len(reporter.uploads) == 1


def test_icon_uploader_uploads_when_server_has_no_record(monkeypatch) -> None:
    """服务端没有记录时首次必须上传喵。"""
    # 空列表喵
    reporter = _FakeReporter()
    uploader = IconUploader(reporter)
    uploader.prime()
    # 抠图给一份 PNG 喵
    png_bytes = encode_png(32, 32, bytes([1, 2, 3, 255]) * 1024)
    monkeypatch.setattr(icons, "extract_icon_png", lambda path, size=32: png_bytes)
    # 应当上传一次喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert reporter.uploads == [("Code", "Code.exe")]


def test_icon_uploader_retries_after_failure(monkeypatch) -> None:
    """一次上传失败不能永久放弃，换图标后仍要允许重试喵。"""
    # 第一次失败、第二次成功喵
    class _FlakyReporter(_FakeReporter):
        """头一次上传失败、之后成功的假上报器喵。"""

        def upload_icon(self, app: str, package: str, png_bytes: bytes) -> tuple[bool, str]:
            """先记一次调用，再按预设结果返回喵。"""
            self.uploads.append((app, package))
            return (len(self.uploads) > 1), "ok"

    reporter = _FlakyReporter()
    uploader = IconUploader(reporter)
    # 抠图给一份 PNG 喵
    png_bytes = encode_png(32, 32, bytes([5, 6, 7, 255]) * 1024)
    monkeypatch.setattr(icons, "extract_icon_png", lambda path, size=32: png_bytes)
    # 第一次失败喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert len(reporter.uploads) == 1
    # 第二次应当重试并成功喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert len(reporter.uploads) == 2


def test_icon_uploader_skips_unreadable_exe(monkeypatch) -> None:
    """抠不到图标的应用要限制重试次数，别每轮都试喵。"""
    # 数一下抠图被调了几次喵
    calls: list[str] = []

    # 抠图永远失败喵
    def _never(path: str, size: int = 32) -> None:
        """记录一次调用并返回 None 喵。"""
        calls.append(path)
        return None

    # 假上报器喵
    reporter = _FakeReporter()
    uploader = IconUploader(reporter)
    # 装桩喵
    monkeypatch.setattr(icons, "extract_icon_png", _never)
    # 路径不存在，应当静默跳过喵
    uploader.ensure("Ghost", "C:/nope/ghost.exe")
    assert reporter.uploads == []
    # 再调多次，超过上限后就不该继续抠图了喵
    for _ in range(IconUploader.MAX_FAILURES + 3):
        uploader.ensure("Ghost", "C:/nope/ghost.exe")
    # 调用次数被上限卡住，不是每轮都试喵
    assert len(calls) == IconUploader.MAX_FAILURES
    # 全程没上传喵
    assert reporter.uploads == []


def test_icon_uploader_retries_extraction_failure(monkeypatch) -> None:
    """抠图失败一次不能永久放弃，换图标后仍要能补上喵。"""
    # 第一次抠图失败、之后成功喵
    state = {"calls": 0}
    png_bytes = encode_png(32, 32, bytes([7, 8, 9, 255]) * 1024)

    def _flaky(path: str, size: int = 32) -> bytes | None:
        """头一次返回 None，之后返回真 PNG 喵。"""
        state["calls"] += 1
        return None if state["calls"] == 1 else png_bytes

    # 装桩喵
    reporter = _FakeReporter()
    uploader = IconUploader(reporter)
    monkeypatch.setattr(icons, "extract_icon_png", _flaky)
    # 第一次失败，不上传喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert reporter.uploads == []
    # 第二次成功，应当补传喵
    uploader.ensure("Code", "C:/fake/Code.exe", "Code.exe")
    assert reporter.uploads == [("Code", "Code.exe")]


def test_extract_icon_from_real_exe() -> None:
    """真机上从系统 exe 里应该能抠出一张 PNG 喵。"""
    # 喵~防御：非 Windows 平台没有图标可抠喵
    if sys.platform != "win32":
        pytest.skip("只有 Windows 才有 exe 图标")
    # 记事本一定存在喵
    png = extract_icon_png(str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"))
    # 抠到就校验 PNG 头喵
    assert png is not None
    assert png.startswith(b"\x89PNG")


def test_extract_icon_falls_back_to_shell(monkeypatch) -> None:
    """ExtractIconEx 抠不到时应该继续尝试别的方式喵。"""
    # 喵~防御：非 Windows 平台跳过喵
    if sys.platform != "win32":
        pytest.skip("只有 Windows 才有 exe 图标")
    # 把第一种方式打桩成永远抠不到喵
    monkeypatch.setattr(icons, "_icons_from_extract_ex", lambda api, path: [])
    # 后两种方式仍然能兜住喵
    png = extract_icon_png(str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"))
    assert png is not None


def test_exe_path_map_uses_lowercase_keys() -> None:
    """进程名映射的键必须是小写，方便和上报的包名对齐喵。"""
    # 清掉缓存再取一次喵
    reset_exe_path_cache()
    mapping = exe_path_map()
    # 键全部小写喵
    assert all(key == key.lower() for key in mapping)


def test_ensure_icon_falls_back_to_process_map() -> None:
    """前台应用拿不到 exe 路径时按进程名兜底喵。"""
    # 假上报器喵
    reporter = _FakeReporter()
    uploader = IconUploader(reporter)
    # 喵~防御：用临时文件当 exe，避免依赖真机进程喵
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
        fake_exe = handle.name
    try:
        # 前台应用 exe 路径为空，靠映射兜底喵
        main_module.ensure_icon(uploader, "Fake", "fake.exe", "", {"fake.exe": fake_exe})
    finally:
        # 清理临时文件喵
        Path(fake_exe).unlink(missing_ok=True)
    # 映射兜底成功，图标会走外壳默认图标上传一次喵
    assert reporter.uploads == [('Fake', 'fake.exe')]


def test_upload_window_icons_respects_cycle_limit() -> None:
    """每轮补图标数量要有上限，避免拖慢采样喵。"""
    # 造一个记录调用的假上传器喵
    class _CountingUploader:
        """只数调用次数的假上传器喵。"""

        def __init__(self) -> None:
            self.calls: list[str] = []

        def ensure(self, app_name: str, exe_path: str, package: str = "") -> None:
            """记录一次调用喵。"""
            self.calls.append(app_name)

    # 造比上限更多的窗口喵
    class _Window:
        """最小窗口替身喵。"""

        def __init__(self, app: str) -> None:
            self.app = app
            self.package = f"{app}.exe"

    windows = [_Window(f"app{index}") for index in range(main_module.MAX_ICON_UPLOADS_PER_CYCLE + 5)]
    # 每个进程都能查到路径喵
    paths = {f"app{index}.exe": f"C:/fake/app{index}.exe" for index in range(len(windows))}
    uploader = _CountingUploader()
    main_module.upload_window_icons(uploader, windows, paths)
    # 调用次数不超过上限喵
    assert len(uploader.calls) == main_module.MAX_ICON_UPLOADS_PER_CYCLE
