"""设备组持久化的单元测试：校验、往返、坏文件兜底喵。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import people
from app.people import PeopleError, PersonGroup


def test_parse_groups_keeps_priority_order() -> None:
    """设备顺序必须原样保留，它就是优先级喵。"""
    # 三台设备按给定顺序喵
    groups = people.parse_groups(
        {"groups": [{"name": " 主人 ", "devices": ["win-1", "and-1", "win-2"]}]}
    )
    # 组名去掉首尾空白喵
    assert groups[0].name == "主人"
    # 顺序不变喵
    assert groups[0].devices == ("win-1", "and-1", "win-2")


def test_parse_groups_drops_duplicates_and_blanks() -> None:
    """重复与空白设备 ID 要自动丢掉喵。"""
    groups = people.parse_groups([{"name": "主人", "devices": ["win-1", "win-1", " ", "and-1"]}])
    assert groups[0].devices == ("win-1", "and-1")


def test_parse_groups_rejects_empty_name() -> None:
    """组名不能为空喵。"""
    with pytest.raises(PeopleError):
        people.parse_groups([{"name": "   ", "devices": ["win-1"]}])


def test_parse_groups_rejects_bad_shape() -> None:
    """顶层不是数组时应当报错喵。"""
    with pytest.raises(PeopleError):
        people.parse_groups({"groups": "nope"})


def test_parse_groups_rejects_too_many_groups() -> None:
    """组数量超限时应当报错喵。"""
    with pytest.raises(PeopleError):
        people.parse_groups([{"name": f"g{index}", "devices": []} for index in range(people.MAX_GROUPS + 1)])


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """写进文件再读回来要一模一样喵。"""
    # 用一个临时数据库路径定位 people.json 喵
    db_path = tmp_path / "device_hub.db"
    groups = [PersonGroup(name="主人", devices=("win-1", "and-1"))]
    # 保存喵
    people.save_people(db_path, groups)
    # 读回来喵
    assert people.load_people(db_path) == groups


def test_load_people_returns_empty_when_missing(tmp_path: Path) -> None:
    """文件不存在时返回空列表喵。"""
    assert people.load_people(tmp_path / "device_hub.db") == []


def test_load_people_ignores_broken_file(tmp_path: Path) -> None:
    """文件坏掉时按空处理，不能让看板打不开喵。"""
    # 写一个坏 JSON 喵
    path = people.people_path(tmp_path / "device_hub.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert people.load_people(tmp_path / "device_hub.db") == []
