"""命令行入口单元测试：参数解析、配置合并、干跑输出喵。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent import main as main_module
from agent.collector import ForegroundApp
from agent.config import AgentConfig, ConfigError, load_config
from agent.main import main, parse_arguments, resolve_config


def test_parse_arguments_defaults() -> None:
    """不带参数时各开关应为默认值喵。"""
    # 解析空参数喵
    arguments = parse_arguments([])
    # 默认不是单次模式、不是干跑喵
    assert arguments.once is False
    assert arguments.dry_run is False
    # 服务端与口令未指定喵
    assert arguments.server is None
    assert arguments.token is None


def test_resolve_config_merges_cli_and_persists(tmp_path: Path) -> None:
    """命令行参数应覆盖配置并持久化自动生成的设备 ID 喵。"""
    # 指向临时配置文件喵
    config_path = tmp_path / "config.json"
    # 解析参数喵
    arguments = parse_arguments(
        [
            "--config",
            str(config_path),
            "--server",
            "http://192.168.2.245:8080",
            "--token",
            "0123456789abcdef",
            "--name",
            "测试台式机",
        ]
    )
    # 合并配置喵
    config, resolved_path = resolve_config(arguments)
    # 路径应一致喵
    assert resolved_path == config_path.resolve()
    # 关键字段应来自命令行喵
    assert config.server_url == "http://192.168.2.245:8080"
    assert config.display_name == "测试台式机"
    # 设备 ID 应被自动生成喵
    assert config.device_id.startswith("win-")
    # 配置文件应已落盘，且能读回同一个设备 ID 喵
    saved_config = load_config(config_path)
    assert saved_config.device_id == config.device_id


def test_resolve_config_applies_interval_override(tmp_path: Path) -> None:
    """--interval 应覆盖配置文件里的采集频率喵。"""
    # 指向临时配置文件喵
    config_path = tmp_path / "config.json"
    # 写入一个 5 秒的配置喵
    config_path.write_text(
        json.dumps({"server_url": "http://127.0.0.1:8080", "ingest_token": "0123456789abcdef", "sample_interval_seconds": 5}),
        encoding="utf-8",
    )
    # 命令行要求改成 2 秒喵
    arguments = parse_arguments(["--config", str(config_path), "--interval", "2"])
    # 合并配置喵
    config, _ = resolve_config(arguments)
    # 生效值应是命令行给的喵
    assert config.sample_interval_seconds == 2


def test_resolve_config_applies_report_interval_override(tmp_path: Path) -> None:
    """--report-interval 应覆盖配置文件里的上报频率喵。"""
    # 指向临时配置文件喵
    config_path = tmp_path / "config.json"
    # 写入一个默认 60 秒的配置喵
    config_path.write_text(
        json.dumps({"server_url": "http://127.0.0.1:8080", "ingest_token": "0123456789abcdef", "sample_interval_seconds": 5}),
        encoding="utf-8",
    )
    # 命令行要求改成 15 秒喵
    arguments = parse_arguments(["--config", str(config_path), "--report-interval", "15"])
    # 合并配置喵
    config, _ = resolve_config(arguments)
    # 生效值应是命令行给的喵
    assert config.report_interval_seconds == 15.0


def test_resolve_config_rejects_out_of_range_report_interval(tmp_path: Path) -> None:
    """--report-interval 越界时应直接报错喵。"""
    # 指向临时配置文件喵
    config_path = tmp_path / "config.json"
    # 5 秒比下限还快喵
    arguments = parse_arguments(
        [
            "--config",
            str(config_path),
            "--server",
            "http://127.0.0.1:8080",
            "--token",
            "0123456789abcdef",
            "--report-interval",
            "5",
        ]
    )
    # 喵~防御：越界要报错，别静默跑起来喵
    with pytest.raises(ConfigError):
        resolve_config(arguments)


def test_plan_next_report_snaps_to_sample_grid() -> None:
    """上报时刻要对齐采样网格，设 15 秒不能被推成 20 秒喵。"""
    # 5 秒采样、15 秒上报 = 隔 3 轮报一次喵
    assert main_module.plan_next_report(1000.0, 5.0, 15.0) == 1015.0
    # 10 秒上报 = 隔 2 轮喵
    assert main_module.plan_next_report(1000.0, 5.0, 10.0) == 1010.0
    # 60 秒上报 = 隔 12 轮喵
    assert main_module.plan_next_report(1000.0, 5.0, 60.0) == 1060.0
    # 喵~防御：上报间隔比采样还短时至少隔一轮，不能每轮都报喵
    assert main_module.plan_next_report(1000.0, 5.0, 1.0) == 1005.0
    # 除不尽时按最近的一轮算喵
    assert main_module.plan_next_report(1000.0, 7.0, 15.0) == 1014.0


def test_should_rescan_windows_throttles_scans() -> None:
    """窗口快照最短 30 秒扫一次，短间隔上报时复用旧快照喵。"""
    # 第一次运行一定扫喵
    assert main_module.should_rescan_windows(1000.0, 0.0) is True
    # 30 秒内不重复扫喵
    assert main_module.should_rescan_windows(1020.0, 1000.0) is False
    # 到 30 秒就重扫喵
    assert main_module.should_rescan_windows(1030.0, 1000.0) is True


def test_resolve_config_rejects_out_of_range_interval(tmp_path: Path) -> None:
    """--interval 越界时应直接报错，不要静默跑起来喵。"""
    # 指向临时配置文件喵
    config_path = tmp_path / "config.json"
    # 90 秒明显超范围喵
    arguments = parse_arguments(
        [
            "--config",
            str(config_path),
            "--server",
            "http://127.0.0.1:8080",
            "--token",
            "0123456789abcdef",
            "--interval",
            "90",
        ]
    )
    # 期望抛配置错误喵
    with pytest.raises(ConfigError, match="--interval"):
        resolve_config(arguments)


def test_run_once_dry_run_prints_json(tmp_path: Path, capsys) -> None:
    """干跑模式应打印一条合法上报 JSON 且不发送喵。"""
    # 准备配置文件路径喵
    config_path = tmp_path / "config.json"
    # 组装命令行参数喵
    argv = [
        "--config",
        str(config_path),
        "--server",
        "http://127.0.0.1:8080",
        "--token",
        "0123456789abcdef",
        "--dry-run",
    ]
    # 执行主入口喵
    exit_code = main(argv)
    # 干跑应成功退出喵
    assert exit_code == 0
    # 捕获标准输出喵
    captured_output = capsys.readouterr().out
    # 输出应是合法 JSON 喵
    payload = json.loads(captured_output)
    # 关键字段应齐全喵
    assert payload["platform"] == "windows"
    assert payload["device_id"].startswith("win-")
    assert "hardware" in payload
    assert "usage_delta" in payload


def test_main_returns_error_on_bad_config(tmp_path: Path, capsys) -> None:
    """缺少口令时应返回 2 并打印中文提示喵。"""
    # 只给地址不给口令喵
    argv = ["--config", str(tmp_path / "config.json"), "--server", "http://127.0.0.1:8080"]
    # 执行主入口喵
    exit_code = main(argv)
    # 应返回参数错误码喵
    assert exit_code == 2
    # 错误信息应提到配置错误喵
    assert "配置错误" in capsys.readouterr().err


def test_run_forever_persists_samples_and_drops_stale(tmp_path: Path, monkeypatch) -> None:
    """常驻模式应把采样落盘，但重启后不再补报上次遗留的无时间戳数据喵。"""
    # 构造一个只需要最小字段的配置喵
    config = AgentConfig(
        server_url="http://127.0.0.1:8080",
        ingest_token="0123456789abcdef",
        device_id="win-test-0001",
        display_name="测试机",
        sample_interval_seconds=1.0,
        report_interval_seconds=1.0,
    )
    # 假前台应用喵
    fake_app = ForegroundApp(
        name="Code.exe",
        package="Code.exe",
        title="main.py",
        since=datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc),
    )
    # 替换采集函数，避免依赖真实桌面喵
    monkeypatch.setattr(main_module, "get_foreground_app", lambda: fake_app)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    # 喵~防御：把空闲时间固定成 0，测试不该受真实键鼠状态影响喵
    monkeypatch.setattr(main_module, "idle_seconds", lambda: 0.0)

    # 记录每次上报传入的使用时长喵
    reported_usage: list[list[dict[str, object]]] = []

    class FakeReporter:
        """假上报器：不联网，只记录调用喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            # 配置用不到，保留签名一致喵
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录使用时长并返回占位负载喵。"""
            reported_usage.append(list(usage_deltas))
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    # 替换上报器喵
    monkeypatch.setattr(main_module, "Reporter", FakeReporter)

    # 预置上次未上报的数据，模拟"上次被强杀"喵
    state_path = tmp_path / "usage-state.json"
    state_path.write_text(json.dumps({"Old.exe": 100}), encoding="utf-8")
    # 记录采样期间状态文件是否真的落盘喵
    seen_state_files: list[bool] = []
    # 让 sleep 在第三次调用时抛 KeyboardInterrupt，结束主循环喵
    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float) -> None:
        """模拟休眠，并在采样几轮后触发退出喵。"""
        seen_state_files.append(state_path.exists())
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)

    # 运行常驻模式喵
    exit_code = main_module.run_forever(config, state_path)

    # 正常退出喵
    assert exit_code == 0
    # 采样期间应已把数据落盘喵
    assert any(seen_state_files)
    # 至少发生一次上报喵
    assert reported_usage
    # 上报内容里不该再出现上次遗留的数据——那段秒数没有时间戳，
    # 补报会盖到可能离线的时段上，主人要求离线记录绝对真实喵
    last_usage = {item["app"]: item["seconds"] for item in reported_usage[-1]}
    assert last_usage.get("Old.exe", 0) == 0
    # 本次采样照常上报喵
    assert last_usage.get("Code.exe", 0) >= 1
    # 上报成功后状态文件应被清掉喵
    assert not state_path.exists()

def test_server_role_skips_sampling_without_rdp(tmp_path: Path, monkeypatch) -> None:
    """服务器角色在 RDP 未连接时应只发心跳，不累计使用时长喵。"""
    # 构造服务器角色配置喵
    config = AgentConfig(
        server_url="http://127.0.0.1:8080",
        ingest_token="0123456789abcdef",
        device_id="win-srv-0001",
        sample_interval_seconds=1.0,
        report_interval_seconds=1.0,
        role="server",
    )
    # 假前台应用喵
    fake_app = ForegroundApp(
        name="Code.exe",
        package="Code.exe",
        title="main.py",
        since=datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc),
    )
    # 替换采集与门控函数喵
    monkeypatch.setattr(main_module, "get_foreground_app", lambda: fake_app)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    # 喵~防御：把空闲时间固定成 0，测试不该受真实键鼠状态影响喵
    monkeypatch.setattr(main_module, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(main_module, "detect_rdp_active", lambda: False)
    monkeypatch.setattr(main_module, "list_mirror_windows", lambda _names: ["23113RKC6C"])

    # 记录每次上报的负载喵
    captured: list[dict] = []

    class FakeReporter:
        """假上报器，记录门控字段喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            # 配置用不到喵
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录使用时长与门控字段喵。"""
            captured.append({"usage": list(usage_deltas), **extra})
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    # 替换上报器喵
    monkeypatch.setattr(main_module, "Reporter", FakeReporter)

    # 采样两轮后退出喵
    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float) -> None:
        """模拟休眠并在第三轮抛出退出信号喵。"""
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)

    # 运行常驻模式喵
    exit_code = main_module.run_forever(config, tmp_path / "usage-state.json")

    # 正常退出喵
    assert exit_code == 0
    # 至少上报一次喵
    assert captured
    # 所有上报的使用时长都应为空喵
    assert all(item["usage"] == [] for item in captured)
    # 应带上 RDP 未连接与投屏窗口信息喵
    assert captured[-1]["rdp_connected"] is False
    assert captured[-1]["mirror_windows"] == ["23113RKC6C"]
    # 没有累计就不该产生状态文件喵
    assert not (tmp_path / "usage-state.json").exists()


def test_server_role_counts_when_rdp_active(tmp_path: Path, monkeypatch) -> None:
    """服务器角色在 RDP 连接时应正常累计使用时长喵。"""
    # 构造服务器角色配置喵
    config = AgentConfig(
        server_url="http://127.0.0.1:8080",
        ingest_token="0123456789abcdef",
        device_id="win-srv-0002",
        sample_interval_seconds=1.0,
        report_interval_seconds=1.0,
        role="server",
    )
    # 假前台应用喵
    fake_app = ForegroundApp(
        name="Code.exe",
        package="Code.exe",
        title="main.py",
        since=datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc),
    )
    # RDP 处于活动状态喵
    monkeypatch.setattr(main_module, "get_foreground_app", lambda: fake_app)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    # 喵~防御：把空闲时间固定成 0，测试不该受真实键鼠状态影响喵
    monkeypatch.setattr(main_module, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(main_module, "detect_rdp_active", lambda: True)
    monkeypatch.setattr(main_module, "list_mirror_windows", lambda _names: [])

    # 记录上报负载喵
    captured: list[dict] = []

    class FakeReporter:
        """假上报器喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录使用时长喵。"""
            captured.append({"usage": list(usage_deltas), **extra})
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    monkeypatch.setattr(main_module, "Reporter", FakeReporter)

    # 采样两轮后退出喵
    sleep_calls = {"count": 0}

    def fake_sleep(_seconds: float) -> None:
        """模拟休眠并在第三轮抛出退出信号喵。"""
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)

    # 运行常驻模式喵
    exit_code = main_module.run_forever(config, tmp_path / "usage-state.json")

    # 正常退出喵
    assert exit_code == 0
    # 应累计到 Code.exe 的时长喵
    final_usage = {item["app"]: item["seconds"] for item in captured[-1]["usage"]}
    assert final_usage.get("Code.exe", 0) >= 1
    # 应上报 RDP 已连接喵
    assert captured[-1]["rdp_connected"] is True


class _StubReporter:
    """只记录上报体、不发请求的假上报器喵。"""

    def __init__(self) -> None:
        # 收集每次组装出来的上报体喵
        self.payloads: list[dict[str, object]] = []

    def build_payload(
        self,
        hardware: dict[str, str],
        battery: object,
        current_app: object,
        usage_deltas: list[dict[str, object]],
        **kwargs: object,
    ) -> dict[str, object]:
        """把关键字参数原样收进上报体，方便断言喵。"""
        payload: dict[str, object] = {"usage_delta": usage_deltas, **kwargs}
        self.payloads.append(payload)
        return payload

    def send(self, _payload: dict[str, object]) -> tuple[bool, str]:
        """固定返回成功喵。"""
        return True, "ok"


class _StubTracker:
    """只吐一次待上报数据的假累加器喵。"""

    def __init__(self, pending: dict[str, int]) -> None:
        # 待上报的秒数表喵
        self._pending = dict(pending)
        # 还回来的数据喵
        self.restored: dict[str, int] = {}

    def drain(self) -> dict[str, int]:
        """取出待上报数据并清空喵。"""
        drained = dict(self._pending)
        self._pending = {}
        return drained

    def snapshot(self) -> dict[str, int]:
        """返回剩余数据喵。"""
        return dict(self._pending)

    def restore(self, pending: dict[str, int]) -> None:
        """记录被还回来的数据，同时放回待上报里（真实累加器就是这样）喵。"""
        # 记一份方便断言喵
        self.restored.update(pending)
        # 喵~注意：真实累加器会把数据放回待上报，落盘才不是空字典喵
        for key, seconds in pending.items():
            self._pending[key] = self._pending.get(key, 0) + seconds


def test_report_once_keeps_afk_with_usage_pending() -> None:
    """进入 AFK 的那一批要同时带上 afk=true 与攒下的时长，服务端才能立刻画出空档喵。"""
    # 准备假的依赖喵
    reporter = _StubReporter()
    tracker = _StubTracker({"Code.exe": 60})
    # 本轮虽然是 AFK，但攒着 60 秒使用时长喵
    main_module._report_once(reporter, tracker, {}, None, None, afk=True)
    # afk 必须如实上报，服务端只把"没有使用的分钟"算成空档喵
    assert reporter.payloads[-1]["afk"] is True
    # 使用时长照常带上喵
    assert reporter.payloads[-1]["usage_delta"] == [{"app": "Code.exe", "seconds": 60, "package": ""}]


def test_report_once_keeps_afk_when_nothing_pending() -> None:
    """没有待上报数据时 AFK 要如实上报，服务端才能画成空档喵。"""
    # 准备空的累加器喵
    reporter = _StubReporter()
    tracker = _StubTracker({})
    # 本轮 AFK 且没有使用时长喵
    main_module._report_once(reporter, tracker, {}, None, None, afk=True)
    # 上报体里必须是 afk=True 喵
    assert reporter.payloads[-1]["afk"] is True
    # 使用时长是空数组喵
    assert reporter.payloads[-1]["usage_delta"] == []


def _loop_config(**overrides) -> AgentConfig:
    """构造一个跑得快、上报间隔很长的常驻配置喵。"""
    # 默认值够用，测试可以按需覆盖喵
    params = {
        "server_url": "http://127.0.0.1:8080",
        "ingest_token": "0123456789abcdef",
        "device_id": "win-loop-0001",
        "display_name": "循环测试机",
        "sample_interval_seconds": 1.0,
        "report_interval_seconds": 3600.0,
    }
    params.update(overrides)
    return AgentConfig(**params)


def _fake_app() -> ForegroundApp:
    """造一个假前台应用喵。"""
    return ForegroundApp(
        name="Code.exe",
        package="Code.exe",
        title="main.py",
        since=datetime(2026, 10, 29, 9, 0, 0, tzinfo=timezone.utc),
    )


def test_afk_change_triggers_immediate_report(tmp_path: Path, monkeypatch) -> None:
    """AFK 状态一变就立刻上报，不必等下一个上报周期喵。"""
    # 上报间隔设成 1 小时，唯一的上报只可能来自状态切换喵
    config = _loop_config()
    app = _fake_app()
    # 采集函数全部替身化喵
    monkeypatch.setattr(main_module, "get_foreground_app", lambda: app)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    monkeypatch.setattr(main_module, "session_locked", lambda: False)
    monkeypatch.setattr(main_module, "list_open_windows", lambda: [])
    # 第一轮不 AFK，第二轮起空闲 120 秒喵
    idle_values = iter([0.0, 120.0] + [120.0] * 20)
    monkeypatch.setattr(main_module, "idle_seconds", lambda: next(idle_values))
    # 记录每次上报的 afk 标记与边界喵
    captured: list[dict[str, object]] = []

    class FakeReporter:
        """假上报器：只记录调用喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            # 配置用不到喵
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录关键字段喵。"""
            captured.append(
                {
                    "afk": extra.get("afk"),
                    "afk_since": extra.get("afk_since"),
                    "usage": len(usage_deltas),
                }
            )
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    monkeypatch.setattr(main_module, "Reporter", FakeReporter)
    # 跑四轮就退出喵
    counter = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        """模拟休眠并在几轮后退出喵。"""
        counter["n"] += 1
        if counter["n"] >= 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)
    # 跑起来喵
    assert main_module.run_forever(config, tmp_path / "state.json") == 0
    # 状态切换时立刻上报一条：afk=true 与"刚记下的使用时长"一起送出去，
    # 服务端会把这段秒数照常入库，并把空档起点回溯到真正停表的那一刻喵
    flip_reports = [item for item in captured if item["afk_since"] is not None]
    assert flip_reports
    assert flip_reports[0]["afk"] is True
    assert flip_reports[0]["usage"] > 0


def test_lock_screen_counts_as_afk(tmp_path: Path, monkeypatch) -> None:
    """锁屏时即使键鼠在动也要算 AFK，避免假在线喵。"""
    # 上报间隔很长，靠状态切换触发上报喵
    config = _loop_config()
    app = _fake_app()
    monkeypatch.setattr(main_module, "get_foreground_app", lambda: app)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    # 空闲 0 秒但已锁屏喵
    monkeypatch.setattr(main_module, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(main_module, "session_locked", lambda: True)
    monkeypatch.setattr(main_module, "list_open_windows", lambda: [])
    captured: list[dict[str, object]] = []

    class FakeReporter:
        """假上报器喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            # 配置用不到喵
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录 afk 与边界喵。"""
            captured.append({"afk": extra.get("afk"), "afk_since": extra.get("afk_since")})
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    monkeypatch.setattr(main_module, "Reporter", FakeReporter)
    counter = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        """跑两轮就退出喵。"""
        counter["n"] += 1
        if counter["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)
    # 跑起来喵
    assert main_module.run_forever(config, tmp_path / "state.json") == 0
    # 锁屏直接判成 AFK，并带上边界时刻喵
    assert captured
    assert captured[0]["afk"] is True
    assert captured[0]["afk_since"] is not None


def test_foreground_reuse_keeps_counting(tmp_path: Path, monkeypatch) -> None:
    """抓不到前台窗口时沿用上一个应用，别把这段时间丢成空白喵。"""
    # 上报间隔很长，靠退出时的收尾上报观察结果喵
    config = _loop_config()
    app = _fake_app()
    # 第一次能抓到，之后都抓不到（UAC / 切桌面 / 窗口重建）喵
    calls = {"n": 0}

    def fake_foreground() -> ForegroundApp | None:
        """首次返回应用，之后返回 None 喵。"""
        calls["n"] += 1
        return app if calls["n"] == 1 else None

    monkeypatch.setattr(main_module, "get_foreground_app", fake_foreground)
    monkeypatch.setattr(main_module, "collect_hardware", lambda: {"hostname": "test"})
    monkeypatch.setattr(main_module, "read_battery", lambda: None)
    monkeypatch.setattr(main_module, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(main_module, "session_locked", lambda: False)
    monkeypatch.setattr(main_module, "list_open_windows", lambda: [])
    reported: list[list[dict[str, object]]] = []

    class FakeReporter:
        """假上报器喵。"""

        def __init__(self, _config: AgentConfig) -> None:
            # 配置用不到喵
            self._config = _config

        def build_payload(self, hardware, battery, current_app, usage_deltas, **extra):
            """记录使用时长喵。"""
            reported.append(list(usage_deltas))
            return {"ok": True}

        def send(self, _payload):
            """永远成功喵。"""
            return True, "ok"

        def close(self) -> None:
            """无需关闭喵。"""
            return None

    monkeypatch.setattr(main_module, "Reporter", FakeReporter)
    counter = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        """跑四轮就退出喵。"""
        counter["n"] += 1
        if counter["n"] >= 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_module.time, "sleep", fake_sleep)
    # 跑起来喵
    assert main_module.run_forever(config, tmp_path / "state.json") == 0
    # 四轮里只有第一轮抓到窗口，其余靠沿用，Code.exe 应该累计到 3 秒以上喵
    assert reported
    totals = {item["app"]: item["seconds"] for item in reported[-1]}
    assert totals.get("Code.exe", 0) >= 3

def test_compute_sample_gap_caps_short_rounds() -> None:
    """普通轮次最多补 15 秒，抓不到前台的轮次最多补 60 秒喵。"""
    # 正常 5 秒一轮喵
    assert main_module.compute_sample_gap(100.0, 95.0, False) == 5.0
    # 循环被拖慢时按上限截断喵
    assert main_module.compute_sample_gap(200.0, 100.0, False) == main_module.MAX_SAMPLE_GAP_SECONDS
    # 上一轮抓不到前台时上限放宽喵
    assert main_module.compute_sample_gap(200.0, 100.0, True) == main_module.MAX_RECOVER_SECONDS
    # 喵~防御：时钟回拨不能算出负数喵
    assert main_module.compute_sample_gap(90.0, 95.0, False) == 0.0


def test_compute_afk_tail_credits_seconds_before_stop() -> None:
    """离开前那几秒要补给上一个应用，否则时间轴上会留一条白缝喵。"""
    # 上一轮记到 21:50:09，21:50:12 才判定为离开喵
    last = datetime(2026, 10, 31, 12, 50, 9, tzinfo=timezone.utc)
    stop = datetime(2026, 10, 31, 12, 50, 12, tzinfo=timezone.utc)
    assert main_module.compute_afk_tail(stop, last) == 3.0


def test_compute_afk_tail_ignores_missing_or_reversed() -> None:
    """缺时刻、顺序颠倒、间隔过大时都不补记喵。"""
    moment = datetime(2026, 10, 31, 12, 50, 12, tzinfo=timezone.utc)
    # 喵~防御：任一时刻缺失就返回 0喵
    assert main_module.compute_afk_tail(None, moment) == 0.0
    assert main_module.compute_afk_tail(moment, None) == 0.0
    # 顺序颠倒（时钟回拨）也返回 0喵
    assert main_module.compute_afk_tail(moment, moment + timedelta(seconds=5)) == 0.0
    # 补记上限是 MAX_SAMPLE_GAP_SECONDS喵
    assert main_module.compute_afk_tail(moment, moment - timedelta(seconds=600)) == main_module.MAX_SAMPLE_GAP_SECONDS


def test_clamp_resumed_gap_starts_at_resume_instant() -> None:
    """刚从 AFK 回来时只记恢复之后的秒数，别把挂机算成使用喵。"""
    now = datetime(2026, 10, 31, 12, 0, 35, tzinfo=timezone.utc)
    active = datetime(2026, 10, 31, 12, 0, 34, tzinfo=timezone.utc)
    # 15 秒的间隔里只有 1 秒是恢复之后的喵
    assert main_module.clamp_resumed_gap(15.0, True, active, now) == 1.0
    # 不是刚回来就原样返回喵
    assert main_module.clamp_resumed_gap(15.0, False, active, now) == 15.0
    # 恢复时刻缺失时也原样返回喵
    assert main_module.clamp_resumed_gap(15.0, True, None, now) == 15.0


def test_report_once_forwards_anchor_and_missing_seconds() -> None:
    """上报体要带上使用段落位时刻与"抓不到前台"的秒数喵。"""
    # 准备假的依赖喵
    reporter = _StubReporter()
    tracker = _StubTracker({"Code.exe": 65})
    ended_at = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    # 执行一次上报喵
    assert main_module._report_once(
        reporter,
        tracker,
        {"hostname": "test"},
        None,
        usage_ended_at=ended_at,
        foreground_missing_seconds=17,
    )
    # 两个字段都要原样传进上报体喵
    payload = reporter.payloads[0]
    assert payload["usage_ended_at"] == ended_at
    assert payload["foreground_missing_seconds"] == 17


class _ExplodingReporter(_StubReporter):
    """组装或发送时抛异常的假上报器，用来验证失败时数据不会丢喵。"""

    def __init__(self, explode_in: str) -> None:
        """记住要在哪一步炸喵。"""
        super().__init__()
        # build 表示组装时炸，send 表示发送时炸喵
        self.explode_in = explode_in

    def build_payload(self, *args: object, **kwargs: object) -> dict[str, object]:
        """按配置在组装阶段抛异常喵。"""
        # 喵~防御：模拟 to_delta_list / 序列化这类意料之外的异常喵
        if self.explode_in == "build":
            raise RuntimeError("组装炸了")
        return super().build_payload(*args, **kwargs)

    def send(self, _payload: dict[str, object]) -> tuple[bool, str]:
        """按配置在发送阶段抛异常喵。"""
        # 模拟上报器没兜住、直接抛给主循环的情况喵
        raise RuntimeError("发送炸了")


def test_report_once_keeps_data_when_send_raises(tmp_path: Path) -> None:
    """发送抛异常时这一批数据要还回累加器并立刻落盘，等下次补报喵。"""
    # 假上报器在发送阶段炸喵
    reporter = _ExplodingReporter("send")
    tracker = _StubTracker({"Code.exe": 42})
    store = main_module.UsageStore(tmp_path / "usage-state.json")
    # 这次上报必须返回失败，而不是把异常抛给主循环喵
    assert main_module._report_once(reporter, tracker, {}, None, store) is False
    # 数据要原样还回累加器喵
    assert tracker.restored == {"Code.exe": 42}
    # 磁盘上也要留一份，进程被杀也不会丢喵
    assert store.load() == {"Code.exe": 42}


def test_report_once_keeps_data_when_payload_build_raises(tmp_path: Path) -> None:
    """组装上报体抛异常时同样不能丢数据喵。"""
    # 假上报器在组装阶段炸喵
    reporter = _ExplodingReporter("build")
    tracker = _StubTracker({"Code.exe": 17, "QQ.exe": 3})
    store = main_module.UsageStore(tmp_path / "usage-state.json")
    # 上报失败但不抛异常喵
    assert main_module._report_once(reporter, tracker, {}, None, store) is False
    # 两个应用的秒数都要留着喵
    assert tracker.restored == {"Code.exe": 17, "QQ.exe": 3}
    assert store.load() == {"Code.exe": 17, "QQ.exe": 3}


def test_discard_stale_usage_state_clears_leftovers(tmp_path: Path) -> None:
    """重启时残留的待上报秒数要被丢弃，不能补报到可能离线的时段上喵。"""
    # 造一份上次退出时的残留文件喵
    store = main_module.UsageStore(tmp_path / "usage-state.json")
    store.save({"DeepSeek Harness\u0000deepseek harness.exe": 360, "QQ.exe\u0000": 40})
    # 丢弃后应当返回被丢掉的秒数总和喵
    assert main_module.discard_stale_usage_state(store) == 400
    # 文件要被清空，下次启动不再读到同一份陈旧数据喵
    assert store.load() == {}


def test_discard_stale_usage_state_is_noop_when_clean(tmp_path: Path) -> None:
    """没有残留文件时什么也不做，返回值是 0 喵。"""
    # 全新目录，文件根本不存在喵
    store = main_module.UsageStore(tmp_path / "usage-state.json")
    assert main_module.discard_stale_usage_state(store) == 0
    # 调用之后也不该凭空造出文件喵
    assert not (tmp_path / "usage-state.json").exists()


def test_discard_stale_usage_state_clears_empty_file(tmp_path: Path) -> None:
    """文件存在但内容为空时同样返回 0，并且不报错喵。"""
    # 先写一个空字典喵
    store = main_module.UsageStore(tmp_path / "usage-state.json")
    store.save({})
    assert main_module.discard_stale_usage_state(store) == 0
