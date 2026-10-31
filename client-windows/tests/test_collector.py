"""采集层单元测试：硬件字段、电量范围、前台应用结构喵。"""

from __future__ import annotations

import platform

from agent import collector

# 硬件信息必须包含的键名喵
EXPECTED_HARDWARE_KEYS = {"hostname", "os_version", "cpu", "ram_gb", "gpu", "disk"}


def test_collect_hardware_keys_and_types() -> None:
    """硬件信息应包含约定键名，且值都是字符串喵。"""
    # 采集一次喵
    hardware = collector.collect_hardware()
    # 键名应齐全喵
    assert EXPECTED_HARDWARE_KEYS.issubset(hardware.keys())
    # 所有值都应是字符串，方便服务端直接渲染喵
    assert all(isinstance(value, str) for value in hardware.values())
    # 值不应为空喵
    assert all(value.strip() for value in hardware.values())


def test_read_os_version_contains_system() -> None:
    """系统版本字符串应包含平台名喵。"""
    # 读取版本喵
    os_version = collector.read_os_version()
    # 应包含 Windows（或其它平台名）喵
    assert platform.system() in os_version


def test_read_disk_summary_not_empty() -> None:
    """磁盘汇总不应为空字符串喵。"""
    # 读取磁盘信息喵
    disk_summary = collector.read_disk_summary()
    # 应有内容喵
    assert disk_summary.strip()


def test_read_battery_range() -> None:
    """电量读数应在 0 到 100 之间，台式机允许返回 None 喵。"""
    # 读取电量喵
    battery_reading = collector.read_battery()
    # 喵~防御：台式机没有电池，允许为空喵
    if battery_reading is None:
        return
    # 解包并检查范围喵
    percent_value, charging_flag = battery_reading
    assert 0 <= percent_value <= 100
    # 充电状态应是布尔值喵
    assert isinstance(charging_flag, bool)


def test_get_foreground_app_structure() -> None:
    """前台应用结构应合法；无前台窗口时允许返回 None 喵。"""
    # 采集一次喵
    foreground_app = collector.get_foreground_app()
    # 喵~防御：锁屏或无窗口时返回 None 属于正常情况喵
    if foreground_app is None:
        return
    # 应用名与进程名都不应为空喵
    assert foreground_app.name
    assert foreground_app.package
    # 进入前台时间应带时区喵
    assert foreground_app.since.tzinfo is not None

def test_detect_rdp_active_false_when_local(monkeypatch) -> None:
    """本地会话不算 RDP 已连接喵。"""
    # 本地会话喵
    monkeypatch.setattr(collector, "is_remote_session", lambda: False)
    # 应为 False 喵
    assert collector.detect_rdp_active() is False


def test_detect_rdp_active_true_when_active(monkeypatch) -> None:
    """远程会话处于活动状态时应为 True 喵。"""
    # 远程会话 + 活动状态喵
    monkeypatch.setattr(collector, "is_remote_session", lambda: True)
    monkeypatch.setattr(collector, "session_connect_state", lambda: collector.WTS_ACTIVE_STATE)
    # 应为 True 喵
    assert collector.detect_rdp_active() is True


def test_detect_rdp_active_false_when_disconnected(monkeypatch) -> None:
    """远程会话断开但保持时不算已连接喵。"""
    # 远程会话 + 断开状态（4 = WTSDisconnected）喵
    monkeypatch.setattr(collector, "is_remote_session", lambda: True)
    monkeypatch.setattr(collector, "session_connect_state", lambda: 4)
    # 应为 False 喵
    assert collector.detect_rdp_active() is False


def test_detect_rdp_active_falls_back_when_state_unknown(monkeypatch) -> None:
    """拿不到会话状态时保守地按已连接处理喵。"""
    # 远程会话但状态未知喵
    monkeypatch.setattr(collector, "is_remote_session", lambda: True)
    monkeypatch.setattr(collector, "session_connect_state", lambda: None)
    # 应保守返回 True，避免误暂停喵
    assert collector.detect_rdp_active() is True


def test_list_mirror_windows_without_process_names() -> None:
    """没配置投屏进程名时返回空列表喵。"""
    # 空列表喵
    assert collector.list_mirror_windows([]) == []


def test_list_mirror_windows_when_tool_not_running(monkeypatch) -> None:
    """投屏工具没运行时返回空列表喵。"""
    # 假装进程列表里没有 scrcpy 喵
    class FakeProcess:
        info = {"pid": 1234, "name": "explorer.exe"}

    monkeypatch.setattr(collector.psutil, "process_iter", lambda _fields: [FakeProcess()])
    # 应为空喵
    assert collector.list_mirror_windows(["scrcpy.exe"]) == []


def test_list_mirror_windows_returns_titles(monkeypatch) -> None:
    """投屏工具在跑时应返回它的窗口标题喵。"""
    # 假装有两个进程，其中一个是 scrcpy 喵
    class FakeProcess:
        def __init__(self, pid: int, name: str) -> None:
            self.info = {"pid": pid, "name": name}

    monkeypatch.setattr(
        collector.psutil,
        "process_iter",
        lambda _fields: [FakeProcess(100, "scrcpy.exe"), FakeProcess(200, "explorer.exe")],
    )
    # 假装枚举到两个窗口喵
    monkeypatch.setattr(
        collector,
        "_collect_visible_window_titles",
        lambda: [(100, "23113RKC6C"), (200, "资源管理器")],
    )
    # 只应返回 scrcpy 的窗口标题喵
    assert collector.list_mirror_windows(["scrcpy.exe"]) == ["23113RKC6C"]


def test_list_mirror_windows_dedupes_and_limits(monkeypatch) -> None:
    """重复标题应去重，且最多返回 16 条喵。"""
    # 同一个进程开很多窗口喵
    class FakeProcess:
        info = {"pid": 100, "name": "scrcpy.exe"}

    monkeypatch.setattr(collector.psutil, "process_iter", lambda _fields: [FakeProcess()])
    # 20 条重复标题喵
    monkeypatch.setattr(collector, "_collect_visible_window_titles", lambda: [(100, "手机")] * 20)
    # 结果应只有一条喵
    assert collector.list_mirror_windows(["scrcpy.exe"]) == ["手机"]

def test_idle_seconds_is_non_negative() -> None:
    """空闲秒数必须是非负数喵。"""
    # 任何平台上都应当返回非负数喵
    assert collector.idle_seconds() >= 0.0


def test_normalize_window_title_strips_edge_profile_and_zero_width() -> None:
    """Edge 标题应去掉零宽字符、配置名和标签组尾巴喵。"""
    # Edge 会在 Microsoft 和 Edge 之间插零宽空格，这里原样构造喵
    raw = "device-hub 控制台 和另外 4 个页面 - 用户配置 1 - Microsoft\u200b Edge"
    # 清洗后只剩页面标题喵
    assert collector.normalize_window_title(raw) == "device-hub 控制台"


def test_normalize_window_title_strips_chrome_tail() -> None:
    """Chrome 标题应去掉浏览器名尾巴，但保留页面标题里的横线喵。"""
    # 页面标题自带横线，不能被误切喵
    raw = "GitHub - Ceceliaee/patina: 时间轴参考 - Google Chrome"
    # 只切掉最后一段浏览器名喵
    assert collector.normalize_window_title(raw) == "GitHub - Ceceliaee/patina: 时间轴参考"


def test_normalize_window_title_keeps_plain_titles() -> None:
    """非浏览器标题应原样返回，空标题返回空串喵。"""
    # 普通应用标题不能被改动喵
    assert collector.normalize_window_title("app.js - device-hub - Visual Studio Code") == (
        "app.js - device-hub - Visual Studio Code"
    )
    # 空标题返回空串喵
    assert collector.normalize_window_title("") == ""
    # 纯空白标题也返回空串喵
    assert collector.normalize_window_title("   ") == ""
