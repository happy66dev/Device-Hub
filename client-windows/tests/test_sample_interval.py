"""采集频率设置（1–60 秒整数）的单元测试喵。"""

from __future__ import annotations

import pytest

from agent.config import (
    AgentConfig,
    ConfigError,
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    MAX_SAMPLE_INTERVAL_SECONDS,
    MIN_SAMPLE_INTERVAL_SECONDS,
)


def test_default_sample_interval_is_five_seconds() -> None:
    """默认采集频率是 5 秒一次喵。"""
    # 默认配置喵
    config = AgentConfig()
    # 默认值必须是 5 喵
    assert config.sample_interval_seconds == DEFAULT_SAMPLE_INTERVAL_SECONDS == 5


def test_from_dict_accepts_any_integer_in_range() -> None:
    """1 到 60 的每个整数都应当被接受喵。"""
    # 逐个边界与中间值试一遍喵
    for seconds in (1, 2, 5, 17, 59, 60):
        config = AgentConfig.from_dict(
            {"server_url": "http://127.0.0.1:8080", "ingest_token": "12345678", "sample_interval_seconds": seconds}
        )
        # 读出来的值应当原样保留喵
        assert config.sample_interval_seconds == seconds


def test_from_dict_accepts_integral_float_and_text() -> None:
    """老配置里的 5.0 和文本 "10" 都应当能兼容喵。"""
    # 浮点整数值喵
    config = AgentConfig.from_dict(
        {"server_url": "http://127.0.0.1:8080", "ingest_token": "12345678", "sample_interval_seconds": 5.0}
    )
    assert config.sample_interval_seconds == 5
    # 文本数字喵
    config = AgentConfig.from_dict(
        {"server_url": "http://127.0.0.1:8080", "ingest_token": "12345678", "sample_interval_seconds": "10"}
    )
    assert config.sample_interval_seconds == 10


@pytest.mark.parametrize("value", [0, -1, 61, 120, 2.5, True, "abc", [5]])
def test_from_dict_rejects_bad_sample_interval(value: object) -> None:
    """越界、小数、布尔、乱码都应当报错喵。"""
    # 期望抛出配置错误喵
    with pytest.raises(ConfigError, match="sample_interval_seconds"):
        AgentConfig.from_dict(
            {"server_url": "http://127.0.0.1:8080", "ingest_token": "12345678", "sample_interval_seconds": value}
        )


def test_validate_rejects_out_of_range_interval() -> None:
    """直接构造越界对象也要被校验拦住喵。"""
    # 手动塞一个越界值喵
    config = AgentConfig(server_url="http://127.0.0.1:8080", ingest_token="12345678", sample_interval_seconds=90)
    # 期望校验失败喵
    with pytest.raises(ConfigError, match="1–60"):
        config.validate()


def test_interval_bounds_are_one_and_sixty() -> None:
    """边界常量与文档口径一致喵。"""
    # 上下限喵
    assert MIN_SAMPLE_INTERVAL_SECONDS == 1
    assert MAX_SAMPLE_INTERVAL_SECONDS == 60
