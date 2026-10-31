"""控制台与日志输出的单元测试：--debug 开关、日志落盘、窗口化兼容喵。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from agent import console as console_module
from agent import main as main_module


def test_attach_console_returns_bool() -> None:
    """接控制台要么成功要么返回 False，绝不能抛异常喵。"""
    # 直接调用，返回值必须是布尔值喵
    result = console_module.attach_console()
    assert isinstance(result, bool)


def test_has_console_returns_bool() -> None:
    """检测控制台是否存在时同样不能抛异常喵。"""
    # 直接调用喵
    assert isinstance(console_module.has_console(), bool)


def test_show_error_never_raises(monkeypatch) -> None:
    """弹窗失败时只记日志，不能把采集端带崩喵。"""
    # 把 user32 换成一个必定失败的假对象喵
    def boom(*_args, **_kwargs):
        raise OSError("模拟弹窗失败")

    monkeypatch.setattr(console_module.ctypes, "WinDLL", boom)
    # 调用不应抛异常喵
    console_module.show_error("标题", "正文")


def test_configure_logging_writes_file(tmp_path: Path) -> None:
    """日志必须写进文件，窗口化运行时才能事后排查喵。"""
    # 目标日志文件喵
    log_path = tmp_path / "agent.log"
    # 配置日志喵
    usable = main_module.configure_logging(logging.INFO, log_path)
    # 写一条日志喵
    main_module.LOGGER.info("测试日志内容")
    # 刷盘喵
    logging.shutdown()
    # 路径应可用且内容已落盘喵
    assert usable == log_path
    assert "测试日志内容" in log_path.read_text(encoding="utf-8")


def test_configure_logging_tolerates_missing_stderr(tmp_path: Path, monkeypatch) -> None:
    """窗口化 exe 里 sys.stderr 是 None，配置日志不能因此崩掉喵。"""
    # 模拟窗口化环境喵
    monkeypatch.setattr(sys, "stderr", None)
    # 配置日志喵
    usable = main_module.configure_logging(logging.INFO, tmp_path / "agent.log")
    # 文件日志仍然可用喵
    assert usable is not None
    # 写一条日志确认不会因为 stderr 为 None 而报错喵
    main_module.LOGGER.warning("窗口化模式日志")
    logging.shutdown()
    assert "窗口化模式日志" in (tmp_path / "agent.log").read_text(encoding="utf-8")


def test_debug_flag_is_parsed() -> None:
    """--debug 要能被参数解析器识别喵。"""
    # 解析参数喵
    arguments = main_module.parse_arguments(["--debug"])
    # 开关应为真喵
    assert arguments.debug is True
    # 默认不带时为假喵
    assert main_module.parse_arguments([]).debug is False
