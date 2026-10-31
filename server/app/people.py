"""设备组（人）的持久化。

自用时一台设备对应一段时间，把多台设备归到一个人名下就能画出一条完整时间轴；
组内顺序就是优先级，时间真的重叠时靠前的设备保留完整时长，靠后的被裁掉喵。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.people")

# 最多允许多少个设备组喵
MAX_GROUPS = 32

# 每组最多多少台设备喵
MAX_DEVICES_PER_GROUP = 32

# 组名最大长度喵
MAX_NAME_LENGTH = 64


class PeopleError(ValueError):
    """设备组数据不合法时抛出喵。"""


@dataclass(frozen=True)
class PersonGroup:
    """一个设备组：人名 + 按优先级排列的设备 ID 喵。"""

    # 人名或组名喵
    name: str
    # 设备 ID 列表，靠前的优先级高喵
    devices: tuple[str, ...] = ()


def people_path(db_path: Path) -> Path:
    """设备组文件的路径，和数据库放在同一个目录喵。"""
    # 与 SQLite 文件同目录，备份时一起带走喵
    return Path(db_path).parent / "people.json"


def load_people(db_path: Path) -> list[PersonGroup]:
    """读取设备组；文件不存在或损坏时返回空列表喵。

    输入：数据库路径，用于定位 people.json。
    输出：PersonGroup 列表。
    边界：文件坏掉只记日志、不抛异常，避免整个看板打不开喵。
    """
    # 拼出文件路径喵
    path = people_path(db_path)
    # 喵~防御：文件不存在属于正常情况（还没配过）喵
    if not path.exists():
        return []
    try:
        # 读文本并解析喵
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_groups(raw)
    except (OSError, json.JSONDecodeError, PeopleError) as error:
        # 喵~防御：坏文件当作没有，顺手记一条日志方便排查喵
        LOGGER.warning("设备组文件读取失败，按空处理：%s", error)
        return []


def save_people(db_path: Path, groups: Sequence[PersonGroup]) -> None:
    """保存设备组，先写临时文件再替换，避免写到一半断电喵。"""
    # 拼出文件路径喵
    path = people_path(db_path)
    # 喵~防御：目录可能还不存在喵
    path.parent.mkdir(parents=True, exist_ok=True)
    # 组装成可写入的字典喵
    payload = {
        "groups": [
            {"name": group.name, "devices": list(group.devices)}
            for group in groups
        ]
    }
    # 先写临时文件喵
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 再原子替换喵
    temporary.replace(path)


def parse_groups(raw: Any) -> list[PersonGroup]:
    """校验并规范化设备组数据喵。

    输入：前端传来的 {"groups": [...]} 或直接的数组。
    输出：PersonGroup 列表。
    边界：字段类型不对、组名空、数量超限时抛 PeopleError。
    """
    # 允许直接传数组，也允许包一层 groups 喵
    if isinstance(raw, dict):
        raw = raw.get("groups", [])
    if not isinstance(raw, list):
        raise PeopleError("groups 必须是数组")
    # 喵~防御：组太多说明前端出了问题，直接拒绝喵
    if len(raw) > MAX_GROUPS:
        raise PeopleError(f"最多 {MAX_GROUPS} 个设备组")
    groups: list[PersonGroup] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PeopleError("每个设备组必须是对象")
        # 组名去掉首尾空白喵
        name = str(item.get("name", "")).strip()
        if not name:
            raise PeopleError("设备组名称不能为空")
        if len(name) > MAX_NAME_LENGTH:
            raise PeopleError(f"设备组名称不能超过 {MAX_NAME_LENGTH} 个字")
        # 设备列表喵
        devices_raw = item.get("devices", [])
        if not isinstance(devices_raw, list):
            raise PeopleError(f"设备组 {name} 的 devices 必须是数组")
        devices: list[str] = []
        for device in devices_raw:
            text = str(device).strip()
            # 喵~防御：空值与重复项都跳过，顺序即优先级所以不能重排喵
            if not text or text in devices:
                continue
            devices.append(text)
        if len(devices) > MAX_DEVICES_PER_GROUP:
            raise PeopleError(f"设备组 {name} 最多 {MAX_DEVICES_PER_GROUP} 台设备")
        groups.append(PersonGroup(name=name, devices=tuple(devices)))
    return groups
