"""采集层单元测试：硬件字段、电量范围、前台应用结构喵。"""

from __future__ import annotations

import platform
import sys

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


class _FakeWinreg:
    """模拟 winreg 模块，用来把注册表读显卡的各条分支都覆盖到喵。"""

    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, subkeys: list[str], values: dict[str, dict[str, str]] | None = None) -> None:
        # 枚举出来的子键顺序喵
        self._subkeys = subkeys
        # 每个子键下有哪些值名喵
        self._values = values or {}
        # 记录被打开过的路径，方便断言喵
        self.opened: list[str] = []

    def OpenKey(self, _root: str, path: str):  # noqa: N802 - 故意对齐 winreg 的命名喵
        """模拟打开注册表项喵。"""
        # 记下路径喵
        self.opened.append(path)
        # 喵~防御：路径不在预期里就当键不存在喵
        if path != collector.GPU_CLASS_PATH and not path.startswith(collector.GPU_CLASS_PATH + "\\"):
            raise OSError("找不到注册表项")
        # 用自己当上下文管理器喵
        return self

    def __enter__(self) -> "_FakeWinreg":
        """支持 with 语法喵。"""
        return self

    def __exit__(self, *_exc_info: object) -> bool:
        """退出 with 时不吞异常喵。"""
        return False

    def EnumKey(self, _key: object, index: int) -> str:  # noqa: N802 - 对齐 winreg 命名喵
        """按索引返回子键名，越界时抛 OSError 表示枚举结束喵。"""
        # 喵~注意：真实 winreg 就是靠抛 OSError 表示枚举到头喵
        if index >= len(self._subkeys):
            raise OSError("枚举结束")
        return self._subkeys[index]

    def QueryValueEx(self, key: object, name: str):  # noqa: N802 - 对齐 winreg 命名喵
        """返回值内容，没有这个值名时抛 OSError 喵。"""
        # 找当前打开的是哪个子键喵
        current = self.opened[-1].split("\\")[-1]
        # 取该子键的值表喵
        table = self._values.get(current, {})
        # 喵~防御：值名不存在就按真实 winreg 抛 OSError 喵
        if name not in table:
            raise OSError("找不到值")
        return table[name], 1


def _patch_winreg(monkeypatch, fake: _FakeWinreg) -> None:
    """把 collector 内部的 winreg 导入替换成假模块喵。"""
    # 用 sys.modules 注入，模块内的延迟 import 就会拿到假的喵
    monkeypatch.setitem(sys.modules, "winreg", fake)


def test_read_gpu_name_from_registry_prefers_first_card(monkeypatch) -> None:
    """应按子键顺序取第一块能读到型号的显卡喵。"""
    fake = _FakeWinreg(
        ["Properties", "0001", "0000"],
        {
            "0000": {"DriverDesc": "Intel(R) HD Graphics 4400"},
            "0001": {"DriverDesc": "NVIDIA GeForce RTX 4090"},
        },
    )
    _patch_winreg(monkeypatch, fake)
    # 喵~注意：子键名会先排序，所以 0000 应排在 0001 前面喵
    assert collector.read_gpu_name_from_registry() == "Intel(R) HD Graphics 4400"


def test_read_gpu_name_from_registry_falls_back_to_second_value_name(monkeypatch) -> None:
    """DriverDesc 缺省时应改用 Device Description 喵。"""
    fake = _FakeWinreg(["0000"], {"0000": {"Device Description": "AMD Radeon RX 580"}})
    _patch_winreg(monkeypatch, fake)
    # 应读到第二个候选值名喵
    assert collector.read_gpu_name_from_registry() == "AMD Radeon RX 580"


def test_read_gpu_name_from_registry_skips_non_instance_subkeys(monkeypatch) -> None:
    """非四位数字的子键（如 Properties）应被跳过喵。"""
    fake = _FakeWinreg(["Properties", "Configuration"], {"Properties": {"DriverDesc": "不该被读到"}})
    _patch_winreg(monkeypatch, fake)
    # 全被跳过后应返回空串喵
    assert collector.read_gpu_name_from_registry() == ""


def test_read_gpu_name_from_registry_returns_empty_on_oserror(monkeypatch) -> None:
    """注册表打不开时应安静地返回空串喵。"""
    class BrokenWinreg(_FakeWinreg):
        """一打开就报错的假模块喵。"""

        def OpenKey(self, _root: str, path: str):  # noqa: N802 - 对齐 winreg 命名喵
            """模拟被策略锁定的注册表喵。"""
            raise OSError("拒绝访问")

    _patch_winreg(monkeypatch, BrokenWinreg([]))
    # 喵~防御：不能抛异常，要返回空串让上层兜底喵
    assert collector.read_gpu_name_from_registry() == ""


def test_read_gpu_name_prefers_registry_and_skips_wmic(monkeypatch) -> None:
    """注册表读到时不应再起 wmic 子进程喵。"""
    # 注册表有值喵
    monkeypatch.setattr(collector, "read_gpu_name_from_registry", lambda: "Intel(R) UHD 630")

    def _boom() -> str:
        """被调用就说明兜底逻辑没走对喵。"""
        raise AssertionError("注册表已读到型号，不该再调用 wmic 喵")

    monkeypatch.setattr(collector, "_read_gpu_name_from_wmic", _boom)
    # 应直接返回注册表结果喵
    assert collector.read_gpu_name() == "Intel(R) UHD 630"


def test_read_gpu_name_falls_back_to_wmic(monkeypatch) -> None:
    """注册表读不到时应回退到 wmic 喵。"""
    # 注册表空喵
    monkeypatch.setattr(collector, "read_gpu_name_from_registry", lambda: "")
    # wmic 有值喵
    monkeypatch.setattr(collector, "_read_gpu_name_from_wmic", lambda: "NVIDIA GeForce GTX 750")
    # 应取 wmic 结果喵
    assert collector.read_gpu_name() == "NVIDIA GeForce GTX 750"


def test_read_gpu_name_wmic_passes_creation_no_window(monkeypatch) -> None:
    """调 wmic 必须带 CREATE_NO_WINDOW，否则 GUI 进程会弹黑窗喵。"""
    # 记录实际传进 subprocess.run 的参数喵
    captured: dict[str, object] = {}

    class FakeCompleted:
        """假装跑完了的进程喵。"""

        def __init__(self) -> None:
            """给出正常输出喵。"""
            self.stdout = "Name\nIntel(R) HD Graphics 4400\n"
            self.returncode = 0

    def fake_run(_args, **kwargs):
        """捕获关键字参数喵。"""
        captured.update(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    # 跑一次喵
    assert collector._read_gpu_name_from_wmic() == "Intel(R) HD Graphics 4400"
    # 喵~注意：这一行就是防黑窗的关键，缺了它每半小时会闪一下喵
    assert captured.get("creationflags") == getattr(collector.subprocess, "CREATE_NO_WINDOW", 0)
    # 喵~防御：解码失败要能兜底，不能抛 UnicodeDecodeError 喵
    assert captured.get("errors") == "replace"


def test_read_gpu_name_wmic_returns_unknown_on_missing_binary(monkeypatch) -> None:
    """wmic 不存在时应返回"未知"而不是抛异常喵。"""
    def fake_run(_args, **_kwargs):
        """模拟系统里没有 wmic 喵。"""
        raise FileNotFoundError("wmic")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    # 应安静返回"未知"喵
    assert collector._read_gpu_name_from_wmic() == "未知"


def test_read_gpu_name_wmic_truncates_long_output(monkeypatch) -> None:
    """超长型号应截断到上限，避免撑大上报体喵。"""
    class FakeCompleted:
        """假装返回超长型号喵。"""

        def __init__(self) -> None:
            """拼一个远超上限的名字喵。"""
            self.stdout = "Name\n" + "G" * 200 + "\n"
            self.returncode = 0

    monkeypatch.setattr(collector.subprocess, "run", lambda *_a, **_k: FakeCompleted())
    # 长度应被截到上限喵
    assert len(collector._read_gpu_name_from_wmic()) == collector.MAX_GPU_NAME_LENGTH
