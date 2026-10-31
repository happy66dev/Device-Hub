"""待上报数据持久化的单元测试喵。"""

from __future__ import annotations

import json
from pathlib import Path

from agent.usage_store import UsageStore, default_state_path


def test_default_state_path_sits_next_to_config(tmp_path: Path) -> None:
    """状态文件应与配置文件同目录喵。"""
    # 构造配置路径喵
    config_path = tmp_path / "config.json"
    # 断言状态文件位置喵
    assert default_state_path(config_path) == tmp_path / "usage-state.json"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """写入后应能原样读回喵。"""
    # 创建存储器喵
    store = UsageStore(tmp_path / "usage-state.json")
    # 写入数据喵
    store.save({"Code.exe": 120, "chrome.exe": 45})
    # 读回数据喵
    assert store.load() == {"Code.exe": 120, "chrome.exe": 45}


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    """文件不存在时应返回空字典而不是报错喵。"""
    # 创建存储器但不写文件喵
    store = UsageStore(tmp_path / "usage-state.json")
    # 读取应为空喵
    assert store.load() == {}


def test_load_corrupted_file_returns_empty(tmp_path: Path) -> None:
    """文件损坏时应丢弃旧数据并继续启动喵。"""
    # 写入半个 JSON 模拟断电喵
    state_path = tmp_path / "usage-state.json"
    state_path.write_text('{"Code.exe": 12', encoding="utf-8")
    # 读取应为空喵
    assert UsageStore(state_path).load() == {}


def test_load_filters_invalid_entries(tmp_path: Path) -> None:
    """非法键值应被过滤，只保留合法数据喵。"""
    # 写入各种脏数据喵
    state_path = tmp_path / "usage-state.json"
    state_path.write_text(
        json.dumps(
            {
                "Code.exe": 60,
                "": 10,
                "bad_negative": -5,
                "bad_float": 1.5,
                "bad_bool": True,
                "bad_string": "abc",
            }
        ),
        encoding="utf-8",
    )
    # 只应保留合法项喵
    assert UsageStore(state_path).load() == {"Code.exe": 60}


def test_load_ignores_non_dict_json(tmp_path: Path) -> None:
    """顶层不是对象时也应安全返回空喵。"""
    # 写入数组喵
    state_path = tmp_path / "usage-state.json"
    state_path.write_text("[1, 2, 3]", encoding="utf-8")
    # 读取应为空喵
    assert UsageStore(state_path).load() == {}


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    """父目录不存在时应自动创建喵。"""
    # 指向两层不存在的目录喵
    store = UsageStore(tmp_path / "nested" / "usage-state.json")
    # 写入应成功喵
    store.save({"Code.exe": 5})
    # 断言文件存在喵
    assert store.path.exists()


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    """原子写入不应残留 .tmp 文件喵。"""
    # 创建存储器并写入喵
    store = UsageStore(tmp_path / "usage-state.json")
    store.save({"Code.exe": 5})
    # 目录里应只有正式文件喵
    assert [item.name for item in tmp_path.iterdir()] == ["usage-state.json"]


def test_clear_removes_file_and_tolerates_missing(tmp_path: Path) -> None:
    """清空应删除文件，重复清空不报错喵。"""
    # 创建存储器并写入喵
    store = UsageStore(tmp_path / "usage-state.json")
    store.save({"Code.exe": 5})
    # 清空喵
    store.clear()
    # 文件应消失喵
    assert not store.path.exists()
    # 再清一次不应抛异常喵
    store.clear()


def test_save_overwrites_previous_content(tmp_path: Path) -> None:
    """重复写入应覆盖旧内容喵。"""
    # 创建存储器喵
    store = UsageStore(tmp_path / "usage-state.json")
    # 先写一份喵
    store.save({"A": 10})
    # 再写一份喵
    store.save({"B": 20})
    # 只应剩新数据喵
    assert store.load() == {"B": 20}
