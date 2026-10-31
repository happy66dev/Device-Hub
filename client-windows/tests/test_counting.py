"""采集端计时口径的单元测试：AFK、RDP、远程桌面客户端、投屏前台喵。"""

from __future__ import annotations

from datetime import datetime, timezone

from agent.collector import ForegroundApp
from agent.config import AgentConfig
from agent.main import is_mirror_foreground, rdp_target_address, should_count_sample


def _app(name: str, package: str, title: str = "标题") -> ForegroundApp:
    """构造一个前台应用喵。"""
    # 时间固定，测试不依赖真实时钟喵
    return ForegroundApp(
        name=name,
        package=package,
        title=title,
        since=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc),
    )


def test_afk_stops_counting() -> None:
    """场景 4：AFK 时不采集使用时长喵。"""
    # 前台有应用但人离开了喵
    assert should_count_sample(_app("Code", "Code.exe"), is_server=False, rdp_active=False, is_afk=True) is False


def test_active_keeps_counting() -> None:
    """有人在操作时照常计时喵。"""
    assert should_count_sample(_app("Code", "Code.exe"), is_server=False, rdp_active=False, is_afk=False) is True


def test_no_foreground_app_does_not_count() -> None:
    """采不到前台应用时不计时喵。"""
    assert should_count_sample(None, is_server=False, rdp_active=False, is_afk=False) is False


def test_server_without_rdp_does_not_count() -> None:
    """服务器没连 RDP 时不计时喵。"""
    assert should_count_sample(_app("Code", "Code.exe"), is_server=True, rdp_active=False, is_afk=False) is False


def test_server_with_rdp_counts() -> None:
    """服务器连着 RDP 且有人操作时计时喵。"""
    assert should_count_sample(_app("Code", "Code.exe"), is_server=True, rdp_active=True, is_afk=False) is True


def test_rdp_client_foreground_still_counts_locally() -> None:
    """前台是远程桌面客户端时本机照常计时，由服务端决定要不要停喵。"""
    # mstsc 在前台：服务端会看目标地址，认不出来就当作本机在用 mstsc 喵
    assert should_count_sample(_app("远程桌面连接", "mstsc.exe"), is_server=False, rdp_active=False, is_afk=False) is True
    # 新版远程桌面客户端同样处理喵
    assert should_count_sample(_app("Windows App", "msrdc.exe"), is_server=False, rdp_active=False, is_afk=False) is True


def test_rdp_target_address_parses_window_title() -> None:
    """远程桌面客户端的窗口标题要能解析出目标地址喵。"""
    # 中文标题喵
    assert rdp_target_address(_app("远程桌面连接", "mstsc.exe", "192.168.2.5 - 远程桌面连接")) == "192.168.2.5"
    # 英文标题带端口喵
    assert rdp_target_address(_app("Remote Desktop", "MSTSC.EXE", "10.0.0.9:3389 - Remote Desktop Connection")) == "10.0.0.9:3389"
    # 不是远程桌面客户端时返回空串喵
    assert rdp_target_address(_app("Code", "Code.exe", "main.py - Code")) == ""
    # 没有前台应用时返回空串喵
    assert rdp_target_address(None) == ""


def test_rdp_target_address_falls_back_to_raw_title() -> None:
    """认不出标题后缀时原样返回，交给服务端按未知处理喵。"""
    assert rdp_target_address(_app("远程桌面连接", "mstsc.exe", "某台机器")) == "某台机器"


def test_mirror_foreground_detects_scrcpy() -> None:
    """场景 2：前台是 scrcpy 时算投屏在前台喵。"""
    # 投屏进程名小写集合喵
    names = {"scrcpy.exe"}
    assert is_mirror_foreground(_app("小米14", "scrcpy.exe"), names) is True
    assert is_mirror_foreground(_app("小米14", "SCRCPY.EXE"), names) is True
    # 其它应用不算喵
    assert is_mirror_foreground(_app("Code", "Code.exe"), names) is False
    # 没有前台应用也不算喵
    assert is_mirror_foreground(None, names) is False


def test_default_afk_threshold_is_one_minute() -> None:
    """场景 4：默认 AFK 阈值是 60 秒喵。"""
    # 默认配置喵
    assert AgentConfig().afk_threshold_seconds == 60.0
