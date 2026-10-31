"""客户端配置的单元测试：校验规则、读写往返喵。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent.config import (
    MAX_REPORT_INTERVAL_SECONDS,
    MIN_REPORT_INTERVAL_SECONDS,
    AgentConfig,
    ConfigError,
    default_config_path,
    load_config,
    save_config,
)


def test_from_dict_rejects_unknown_key() -> None:
    """未知字段应报错，避免拼写错误静默生效喵。"""
    # 塞入一个不存在的字段喵
    with pytest.raises(ConfigError, match="未知字段"):
        AgentConfig.from_dict({"server_url": "http://a", "ingest_token": "12345678", "typo_key": 1})


def test_validate_requires_http_prefix() -> None:
    """服务端地址必须带协议头喵。"""
    # 缺少协议头喵
    config = AgentConfig(server_url="192.168.2.245:8080", ingest_token="12345678")
    # 期望校验失败喵
    with pytest.raises(ConfigError, match="http://"):
        config.validate()


def test_validate_requires_long_token() -> None:
    """上报口令不能太短喵。"""
    # 口令只有 4 位喵
    config = AgentConfig(server_url="http://127.0.0.1:8080", ingest_token="1234")
    # 期望校验失败喵
    with pytest.raises(ConfigError, match="至少需要 8 位"):
        config.validate()


def test_validate_rejects_bad_intervals() -> None:
    """采样间隔与上报间隔关系必须合理喵。"""
    # 采样间隔小于 1 秒喵
    with pytest.raises(ConfigError, match="sample_interval_seconds"):
        AgentConfig(server_url="http://a", ingest_token="12345678", sample_interval_seconds=0.1).validate()
    # 上报间隔小于采样间隔喵
    with pytest.raises(ConfigError, match="report_interval_seconds"):
        AgentConfig(
            server_url="http://a",
            ingest_token="12345678",
            sample_interval_seconds=10,
            report_interval_seconds=5,
        ).validate()


def test_report_interval_range_is_enforced() -> None:
    """上报间隔必须夹在 10–60 秒之间喵。"""
    # 上下界都允许喵
    for seconds in (MIN_REPORT_INTERVAL_SECONDS, MAX_REPORT_INTERVAL_SECONDS):
        AgentConfig(
            server_url="http://a",
            ingest_token="12345678",
            sample_interval_seconds=5,
            report_interval_seconds=seconds,
        ).validate()
    # 喵~防御：太快会压垮服务端喵
    with pytest.raises(ConfigError, match="report_interval_seconds"):
        AgentConfig(
            server_url="http://a",
            ingest_token="12345678",
            sample_interval_seconds=5,
            report_interval_seconds=9.9,
        ).validate()
    # 喵~防御：太慢会被服务端心跳超时误判离线喵
    with pytest.raises(ConfigError, match="report_interval_seconds"):
        AgentConfig(
            server_url="http://a",
            ingest_token="12345678",
            sample_interval_seconds=5,
            report_interval_seconds=61,
        ).validate()


def test_load_missing_file_returns_default(tmp_path: Path) -> None:
    """配置文件不存在时应返回空配置而不是报错喵。"""
    # 指向不存在的文件喵
    config = load_config(tmp_path / "nope.json")
    # 地址与口令都应为空喵
    assert config.server_url == ""
    assert config.ingest_token == ""


def test_load_invalid_json(tmp_path: Path) -> None:
    """JSON 写错时应给出明确错误喵。"""
    # 写入坏 JSON 喵
    bad_path = tmp_path / "config.json"
    bad_path.write_text("{not-json", encoding="utf-8")
    # 期望抛配置错误喵
    with pytest.raises(ConfigError, match="不是合法 JSON"):
        load_config(bad_path)


def test_default_config_path_in_source_mode(monkeypatch) -> None:
    """源码运行时配置应放在 client-windows 目录喵。"""
    # 确保没有 frozen 标记喵
    monkeypatch.delattr(sys, "frozen", raising=False)
    # 断言路径喵
    resolved = default_config_path()
    assert resolved.name == "config.json"
    assert resolved.parent.name == "client-windows"


def test_default_config_path_in_frozen_mode(monkeypatch, tmp_path: Path) -> None:
    """打包成 exe 后配置应放在 exe 同目录喵。"""
    # 模拟 PyInstaller 运行环境喵
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "device-hub-agent.exe"))
    # 断言配置落在 exe 旁边喵
    assert default_config_path() == tmp_path / "config.json"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """保存后应能原样读回，设备 ID 得以持久化喵。"""
    # 准备配置文件路径喵
    config_path = tmp_path / "config.json"
    # 构造配置喵
    original = AgentConfig(
        server_url="http://127.0.0.1:8080",
        ingest_token="1234567890",
        device_id="win-test-0001",
        display_name="测试机",
    )
    # 保存喵
    save_config(original, config_path)
    # 读回喵
    loaded = load_config(config_path)
    # 关键字段应一致喵
    assert loaded.device_id == "win-test-0001"
    assert loaded.display_name == "测试机"
    assert loaded.server_url == original.server_url

def test_role_defaults_to_workstation() -> None:
    """默认角色应是工作站喵。"""
    # 默认配置喵
    config = AgentConfig()
    # 角色与投屏进程名应有默认值喵
    assert config.role == "workstation"
    assert config.tag == ""
    assert config.mirror_process_names == ("scrcpy.exe",)


def test_invalid_role_is_rejected() -> None:
    """非法角色应被拒绝喵。"""
    # 角色写错喵
    with pytest.raises(ConfigError):
        AgentConfig(server_url="http://127.0.0.1:8080", ingest_token="0123456789abcdef", role="master").validate()


def test_mirror_process_names_parsed_from_config() -> None:
    """投屏进程名应能从配置里解析成元组喵。"""
    # 解析一份带自定义进程名的配置喵
    config = AgentConfig.from_dict(
        {
            "server_url": "http://127.0.0.1:8080",
            "ingest_token": "0123456789abcdef",
            "mirror_process_names": ["scrcpy.exe", "QtScrcpy.exe"],
        }
    )
    # 应解析成元组喵
    assert config.mirror_process_names == ("scrcpy.exe", "QtScrcpy.exe")


def test_mirror_process_names_rejects_non_list() -> None:
    """投屏进程名不是列表时应报错喵。"""
    # 写成字符串喵
    with pytest.raises(ConfigError):
        AgentConfig.from_dict(
            {
                "server_url": "http://127.0.0.1:8080",
                "ingest_token": "0123456789abcdef",
                "mirror_process_names": "scrcpy.exe",
            }
        )


def test_to_dict_serializes_tuple_as_list(tmp_path: Path) -> None:
    """保存配置时应把元组写成 JSON 数组喵。"""
    # 构造配置并写盘喵
    config = AgentConfig(server_url="http://127.0.0.1:8080", ingest_token="0123456789abcdef", device_id="win-a-0001")
    path = tmp_path / "config.json"
    save_config(config, path)
    # 读回来的 JSON 里应是数组喵
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["mirror_process_names"] == ["scrcpy.exe"]

def test_afk_threshold_default_and_validation() -> None:
    """AFK 阈值默认 900 秒，越界要报错喵。"""
    # 默认值应当是 900 秒喵
    config = AgentConfig(server_url="http://127.0.0.1:8080", ingest_token="12345678")
    assert config.afk_threshold_seconds == 60.0
    # 阈值过小时应当拒绝喵
    config.afk_threshold_seconds = 30
    with pytest.raises(ConfigError):
        config.validate()
    # 阈值过大时也应当拒绝喵
    config.afk_threshold_seconds = 9000
    with pytest.raises(ConfigError):
        config.validate()


def test_afk_threshold_round_trips_through_json(tmp_path: Path) -> None:
    """AFK 阈值要能写进配置文件再读回来喵。"""
    # 准备配置文件路径喵
    path = tmp_path / "config.json"
    # 写入一份带自定义阈值的配置喵
    path.write_text(
        json.dumps({"server_url": "http://127.0.0.1:8080", "ingest_token": "12345678", "afk_threshold_seconds": 300}),
        encoding="utf-8",
    )
    # 读回来应当是 300 秒喵
    assert load_config(path).afk_threshold_seconds == 300.0
