"""运行时访问控制名单的持久化（黑名单）。

为什么不放在 config.yaml 里：配置文件是主人手写的，带注释、要重启才生效，
而拉黑是一次性的应急动作，必须改完立刻生效、且不能把配置写脏。
所以名单单独落一个 acl.json，和 people.json 放在同一个目录，备份时一起带走喵。

喵~注意：这里存的是「生效名单」，config.yaml 里的 acl.blacklist_* 是它的初始值，
两者取并集，配置里写死的那几个永远保持有效，WebUI 只能增删自己加的部分喵。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.acl")

# 名单里最多多少条，防止被前端刷爆喵
MAX_ENTRIES = 512

# 单条标识最大长度，openid 一般 32 位左右，留足余量喵
MAX_KEY_LENGTH = 128

# 备注最大长度喵
MAX_NOTE_LENGTH = 64


class AclError(ValueError):
    """名单数据不合法时抛出喵。"""


# 文件快照缓存：路径 -> (mtime_ns, (napcat 名单, qqbot 名单)) 喵
# 喵~注意：机器人每条消息都会查一次黑名单，不缓存的话每条消息都要读盘解析 JSON 喵
_CACHE: dict[str, tuple[int, tuple[tuple[str, ...], tuple[str, ...]]]] = {}


@dataclass(frozen=True)
class BlockEntry:
    """一条黑名单记录喵。"""

    # 通道名：napcat 用 QQ 号，qqbot 用 member_openid 喵
    channel: str
    # 该通道下的用户标识喵
    target: str
    # 备注，方便主人日后想起来为什么拉黑喵
    note: str = ""
    # 拉黑时刻（UTC ISO 文本），空串表示老数据没记喵
    created_at: str = ""


def acl_path(db_path: Path) -> Path:
    """名单文件路径，和数据库放在同一个目录喵。"""
    # 与 SQLite 文件同目录，备份时一起带走喵
    return Path(db_path).parent / "acl.json"


def load_blocklist(db_path: Path) -> list[BlockEntry]:
    """读取黑名单；文件不存在或损坏时返回空列表喵。

    输入：数据库路径，用于定位 acl.json。
    输出：BlockEntry 列表，顺序即文件里的顺序。
    边界：文件坏掉只记日志、不抛异常，避免整个看板打不开喵。
    """
    # 拼出文件路径喵
    path = acl_path(db_path)
    # 喵~防御：文件不存在属于正常情况（还没拉黑过任何人）喵
    if not path.exists():
        return []
    try:
        # 读文本并解析喵
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_blocklist(raw)
    except (OSError, json.JSONDecodeError, AclError) as error:
        # 喵~防御：坏文件当作没有，顺手记一条日志方便排查喵
        LOGGER.warning("黑名单文件读取失败，按空处理：%s", error)
        return []


def save_blocklist(db_path: Path, entries: Sequence[BlockEntry]) -> None:
    """保存黑名单，先写临时文件再替换，避免写到一半断电喵。"""
    # 拼出文件路径喵
    path = acl_path(db_path)
    # 喵~防御：目录可能还不存在喵
    path.parent.mkdir(parents=True, exist_ok=True)
    # 组装成可写入的字典喵
    payload = {
        "entries": [
            {
                "channel": entry.channel,
                "target": entry.target,
                "note": entry.note,
                "created_at": entry.created_at,
            }
            for entry in entries
        ]
    }
    # 先写临时文件喵
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 再原子替换喵
    temporary.replace(path)


def parse_blocklist(raw: Any) -> list[BlockEntry]:
    """校验并规范化黑名单数据喵。

    输入：前端传来的 {"entries": [...]} 或直接数组。
    输出：BlockEntry 列表。
    边界：字段类型不对、标识空、数量超限时抛 AclError。
    """
    # 允许直接传数组，也允许包一层 entries 喵
    if isinstance(raw, dict):
        raw = raw.get("entries", [])
    if not isinstance(raw, list):
        raise AclError("entries 必须是数组")
    # 喵~防御：条数太多说明前端出了问题，直接拒绝喵
    if len(raw) > MAX_ENTRIES:
        raise AclError(f"黑名单最多 {MAX_ENTRIES} 条")
    entries: list[BlockEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AclError("每条黑名单必须是对象")
        # 通道名只认两种喵
        channel = str(item.get("channel", "napcat")).strip().lower()
        if channel not in ("napcat", "qqbot"):
            raise AclError(f"通道只能是 napcat 或 qqbot，实际是 {channel}")
        # 标识去空白喵
        target = str(item.get("target", "")).strip()
        if not target:
            raise AclError("黑名单标识不能为空")
        if len(target) > MAX_KEY_LENGTH:
            raise AclError(f"黑名单标识不能超过 {MAX_KEY_LENGTH} 个字符")
        # 喵~防御：同一通道下重复的标识只保留第一条，避免删除时删不干净喵
        if any(existing.channel == channel and existing.target == target for existing in entries):
            continue
        # 备注截断，别让它把界面撑爆喵
        note = str(item.get("note", "")).strip()[:MAX_NOTE_LENGTH]
        # 拉黑时刻，缺省时补当前时间喵
        created_at = str(item.get("created_at", "")).strip()
        if not created_at:
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries.append(BlockEntry(channel=channel, target=target, note=note, created_at=created_at))
    return entries


def add_entry(db_path: Path, channel: str, target: str, note: str = "") -> bool:
    """拉黑一个人，返回是否新增了记录喵。

    输入：数据库路径、通道、标识、备注。
    输出：新增成功返回 True；已经存在返回 False。
    边界：标识为空或通道不认识时抛 AclError。
    """
    # 复用校验逻辑，保证写入的数据与 parse 规则一致喵
    candidate = parse_blocklist([{"channel": channel, "target": target, "note": note}])[0]
    # 读现有名单喵
    entries = load_blocklist(db_path)
    # 喵~防御：已经在里面就不重复写，避免同一人多条记录喵
    if any(entry.channel == candidate.channel and entry.target == candidate.target for entry in entries):
        return False
    # 追到末尾并保存喵
    entries.append(candidate)
    save_blocklist(db_path, entries)
    return True


def remove_entry(db_path: Path, channel: str, target: str) -> bool:
    """解除拉黑，返回是否真的删掉了记录喵。

    输入：数据库路径、通道、标识。
    输出：删掉了返回 True；本来就没有返回 False。
    """
    # 读现有名单喵
    entries = load_blocklist(db_path)
    # 过滤掉命中的那条喵
    kept = [
        entry
        for entry in entries
        if not (entry.channel == channel and entry.target == target)
    ]
    # 喵~防御：什么都没删就别写文件，免得无谓地改动 mtime 喵
    if len(kept) == len(entries):
        return False
    save_blocklist(db_path, kept)
    return True


def cached_blocklist(db_path: Path) -> tuple[tuple[str, ...], ...]:
    """按文件 mtime 缓存读取结果，避免每条群消息都去碰磁盘喵。

    输入：数据库路径。
    输出：不可变快照，按通道分组。
    边界：文件 mtime 变化时自动重读，删掉文件也会重读成空喵。
    """
    # 拼出文件路径喵
    path = acl_path(db_path)
    # 喵~防御：文件不存在时直接给空快照，不用走缓存逻辑喵
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        _CACHE.pop(str(path), None)
        return ((), ())
    # 缓存键用绝对路径，值里带 mtime 便于判断是否过期喵
    key = str(path)
    cached = _CACHE.get(key)
    # 喵~注意：mtime 没变就直接复用，省掉 JSON 解析喵
    if cached is not None and cached[0] == stamp:
        return cached[1]
    # 重新读一次喵
    entries = load_blocklist(db_path)
    # 按通道拆开，顺序无关所以都用 frozenset 的元组形式喵
    napcat = tuple(sorted(entry.target for entry in entries if entry.channel == "napcat"))
    qqbot = tuple(sorted(entry.target for entry in entries if entry.channel == "qqbot"))
    snapshot = (napcat, qqbot)
    _CACHE[key] = (stamp, snapshot)
    return snapshot


def effective_blacklist(config: Any, channel: str) -> tuple[str, ...]:
    """算出某通道最终生效的黑名单：配置里写死的 + WebUI 加的喵。

    输入：服务端配置、通道名。
    输出：字符串标识元组，调用方直接做 `in` 判断。
    边界：任一来源为空都不影响另一个生效喵。
    """
    # 配置里的名单喵
    from_config = config.acl.for_channel(channel).blacklist_users
    # 运行时名单喵
    napcat_targets, qqbot_targets = cached_blocklist(config.server.db_path)
    runtime = qqbot_targets if channel == "qqbot" else napcat_targets
    # 喵~注意：两边可能都写了同一个人，用 dict 去重同时保持稳定顺序喵
    merged: dict[str, None] = {}
    for item in from_config:
        merged[str(item)] = None
    for item in runtime:
        merged[str(item)] = None
    return tuple(merged)
