"""WebUI 设置页的配置读写：只改文本里对应的那一行，保留注释与排版喵。

设计要点：
- 白名单式的字段表（`SETTING_FIELDS`），只允许改这些键，避免被当成任意文件写入；
- 改配置走「文本替换」而不是整份 YAML 重新 dump，主人手写的注释不会丢；
- 写盘前先在同目录写临时文件并用 load_config 校验，校验不过就原样回滚喵。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .config import AppConfig, ConfigError, load_config


class SettingsError(ValueError):
    """配置项取值不合法时抛出，路由层转成 400 喵。"""


@dataclass(frozen=True)
class SettingField:
    """一个可在 WebUI 里修改的配置项喵。"""

    # 顶层配置段名，例如 napcat / qqbot / acl 喵
    section: str
    # 段内键名喵
    key: str
    # 取值类型：bool / int / str / secret / str_list / int_list 喵
    kind: str
    # 中文标签，设置页直接显示喵
    label: str
    # 输入框提示，留空表示不需要喵
    hint: str = ""

    @property
    def name(self) -> str:
        """返回 `段.键` 形式的唯一名字喵。"""
        # 路由与前端都用这个名字当 key 喵
        return f"{self.section}.{self.key}"


# 设置页允许修改的字段，顺序即页面上的展示顺序喵
SETTING_FIELDS: tuple[SettingField, ...] = (
    SettingField("napcat", "enabled", "bool", "启用 NapCat 通道", "关闭后不再连 OneBot"),
    SettingField("napcat", "ws_url", "str", "NapCat 正向 WS 地址", "例如 ws://127.0.0.1:7999"),
    SettingField("napcat", "token", "secret", "NapCat 访问口令", "与 NapCat 侧 access token 一致"),
    SettingField("napcat", "self_qq", "str", "机器人 QQ 号", "用来识别消息里是否 @ 了自己"),
    SettingField("napcat", "reconnect_seconds", "int", "断线重连间隔（秒）", "建议 5-30"),
    SettingField("qqbot", "enabled", "bool", "启用官方 QQ Bot 通道", "关闭后不连官方网关"),
    SettingField("qqbot", "app_id", "str", "AppID", "QQ 开放平台机器人 AppID"),
    SettingField("qqbot", "app_secret", "secret", "AppSecret", "只在服务端使用，不会回显明文"),
    SettingField("qqbot", "api_base", "str", "接口根地址", "一般不用改"),
    SettingField("qqbot", "intents", "int", "订阅事件掩码", "群聊消息是 33554432"),
    SettingField("qqbot", "log_openids", "bool", "日志里打印 openid", "排查准入问题时可开"),
    SettingField("qqbot", "free_command_require_prefix", "bool", "免 @ 模式仍要求命令前缀", ""),
    SettingField("qqbot", "free_command_min_role", "str", "免 @ 模式最低角色", "any / admin / owner"),
    SettingField("qqbot", "free_command_group_openids", "str_list", "免 @ 群列表（openid）", "一行一个"),
    SettingField("acl", "whitelist_groups", "int_list", "白名单群号", "一行一个，留空则谁都不响应"),
    SettingField("acl", "blacklist_users", "int_list", "黑名单 QQ 号", "一行一个"),
    SettingField("acl", "whitelist_group_openids", "str_list", "白名单群 openid", "官方通道用"),
    SettingField("acl", "blacklist_member_openids", "str_list", "黑名单成员 openid", "官方通道用"),
    SettingField("acl", "private_user_openids", "str_list", "允许私聊的 user openid", "留空表示私聊不响应"),
)

# 名字到字段定义的映射喵
FIELD_BY_NAME: dict[str, SettingField] = {field.name: field for field in SETTING_FIELDS}

# 密钥类字段在读取时统一替换成这个占位符，前端看到占位符表示「没改」喵
SECRET_PLACEHOLDER = "********"

# 顶层段标题：`section:` 独占一行喵
_SECTION_PATTERN = re.compile(r"^([A-Za-z_][\w-]*):\s*(#.*)?$")

# 段内键：两个空格缩进喵
_KEY_PATTERN = re.compile(r"^(\s+)([A-Za-z_][\w-]*):(.*)$")


def mask_secret(value: str) -> str:
    """把密钥打码成占位符；空值也返回占位符，避免泄露「是否配置过」喵。"""
    # 喵~防御：只要是非空串一律打码，长度也不透露喵
    return SECRET_PLACEHOLDER


def read_settings(config: AppConfig) -> list[dict[str, Any]]:
    """把当前配置按字段表摊平成列表，供设置页渲染喵。"""

    def current(field: SettingField) -> Any:
        """取某个字段当前的值喵。"""
        # 段对象是 dataclass，直接按名字取属性喵
        section = getattr(config, field.section)
        return getattr(section, field.key)

    rows: list[dict[str, Any]] = []
    for field in SETTING_FIELDS:
        value = current(field)
        # 元组统一转成列表，JSON 里更好处理喵
        if isinstance(value, tuple):
            value = list(value)
        # 密钥只回占位符，前端留空表示不修改喵
        if field.kind == "secret":
            value = SECRET_PLACEHOLDER
        rows.append(
            {
                "name": field.name,
                "section": field.section,
                "key": field.key,
                "kind": field.kind,
                "label": field.label,
                "hint": field.hint,
                "value": value,
            }
        )
    return rows


def _render_value(kind: str, value: Any) -> str:
    """把 Python 值渲染成 YAML 行内文本喵。"""
    # 布尔用 YAML 的 true/false 喵
    if kind == "bool":
        return "true" if value else "false"
    # 整数直接写喵
    if kind == "int":
        return str(int(value))
    # 字符串用双引号包起来，转义交给 json 保证合法喵
    if kind in ("str", "secret"):
        return json.dumps(str(value), ensure_ascii=False)
    # 列表用 flow 风格，和配置文件里现有的 [] 写法一致喵
    if kind == "str_list":
        return "[" + ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value) + "]"
    if kind == "int_list":
        return "[" + ", ".join(str(int(item)) for item in value) + "]"
    # 喵~防御：字段表里写了未知类型直接报错，别静默写坏配置喵
    raise SettingsError(f"未知的配置类型：{kind}")


def _split_items(raw: Any) -> list[str]:
    """把前端传来的列表或分隔字符串拆成条目列表喵。"""
    # 已经是列表就逐项转字符串喵
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    # 字符串按逗号、空白、换行都切开，方便主人直接粘贴喵
    if isinstance(raw, str):
        parts = re.split(r"[\s,，]+", raw.strip())
        return [part for part in parts if part]
    # 其它类型（None）当成空列表喵
    if raw is None:
        return []
    # 喵~防御：单值兜底成一项喵
    return [str(raw).strip()]


def _coerce(field: SettingField, raw: Any) -> Any:
    """把前端传来的值转成字段需要的类型喵。"""
    if field.kind == "bool":
        # 复选框传布尔，命令行传字符串，都接受喵
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        raise SettingsError(f"{field.label} 需要是布尔值")
    if field.kind == "int":
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError) as error:
            raise SettingsError(f"{field.label} 需要是整数") from error
    if field.kind in ("str", "secret"):
        return str(raw if raw is not None else "").strip()
    if field.kind == "str_list":
        return _split_items(raw)
    if field.kind == "int_list":
        items: list[int] = []
        for item in _split_items(raw):
            try:
                items.append(int(item))
            except ValueError as error:
                raise SettingsError(f"{field.label} 里出现了非整数：{item}") from error
        return items
    # 喵~防御：未知类型直接报错喵
    raise SettingsError(f"未知的配置类型：{field.kind}")


def _section_bounds(lines: Sequence[str], section: str) -> tuple[int, int] | None:
    """找出某个顶层段的起始行与结束行（不含）喵。"""
    start = -1
    for index, line in enumerate(lines):
        match = _SECTION_PATTERN.match(line.rstrip("\r"))
        if match and match.group(1) == section:
            start = index
            break
    # 没找到这个段喵
    if start < 0:
        return None
    # 往下找到下一个顶层键为止喵
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _SECTION_PATTERN.match(lines[index].rstrip("\r")):
            end = index
            break
    return start, end


def _set_value(text: str, section: str, key: str, rendered: str) -> str:
    """在配置文本里就地替换某个键的值，保留注释喵。"""
    # 先记下换行风格，写回时保持一致喵
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [line.rstrip("\r") for line in text.split("\n")]
    bounds = _section_bounds(lines, section)
    if bounds is None:
        # 段不存在就整体追加到文件末尾喵
        if lines and lines[-1] == "":
            lines.pop()
        lines.extend([f"{section}:", f"  {key}: {rendered}", ""])
        return newline.join(lines)
    start, end = bounds
    # 在段内找这个键喵
    for index in range(start + 1, end):
        match = _KEY_PATTERN.match(lines[index])
        if not match or match.group(2) != key:
            continue
        indent, _, remainder = match.groups()
        # 保留行尾注释喵
        comment = ""
        if "#" in remainder:
            comment = "  " + remainder[remainder.index("#") :].strip()
        lines[index] = f"{indent}{key}: {rendered}{comment}"
        return newline.join(lines)
    # 键不存在就插到段尾（跳过尾部空行）喵
    insert_at = end
    while insert_at - 1 > start and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines.insert(insert_at, f"  {key}: {rendered}")
    return newline.join(lines)


def update_config_text(text: str, changes: Mapping[str, Any]) -> str:
    """按 `段.键 -> 新值` 修改配置文本，返回新文本喵。"""
    result = text
    for name, raw in changes.items():
        field = FIELD_BY_NAME.get(name)
        # 喵~防御：只允许白名单里的键，防止被当成任意写入喵
        if field is None:
            raise SettingsError(f"不认识的配置项：{name}")
        value = _coerce(field, raw)
        result = _set_value(result, field.section, field.key, _render_value(field.kind, value))
    return result


def apply_settings(config_path: Path, changes: Mapping[str, Any]) -> list[str]:
    """把改动写进配置文件，返回真正生效的字段名喵。

    输入：配置文件路径、`段.键 -> 新值` 映射。
    输出：已写入的字段名列表。
    边界：空改动直接返回空列表；新文本校验失败时原文件保持不变并抛 SettingsError喵。
    """
    # 过滤掉「没改」的项：密钥占位符表示主人没动它喵
    effective: dict[str, Any] = {}
    for name, raw in changes.items():
        field = FIELD_BY_NAME.get(name)
        if field is None:
            raise SettingsError(f"不认识的配置项：{name}")
        if field.kind == "secret" and str(raw) == SECRET_PLACEHOLDER:
            continue
        effective[name] = raw
    if not effective:
        return []
    # 读原文本喵
    try:
        original = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SettingsError(f"无法读取配置文件 {config_path}：{error}") from error
    # 就地替换喵
    updated = update_config_text(original, effective)
    if updated == original:
        return []
    # 先写同目录临时文件并校验，校验通过再整体替换喵
    handle, temp_name = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(config_path.parent))
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(updated, encoding="utf-8")
        try:
            # 复用正式加载器做完整校验喵
            load_config(temp_path)
        except ConfigError as error:
            raise SettingsError(f"配置校验失败：{error}") from error
        os.replace(temp_path, config_path)
    finally:
        # 喵~防御：临时文件没被 replace 掉时清理干净喵
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return list(effective.keys())


def load_raw_config(path: Path) -> dict[str, Any]:
    """只做 YAML 解析，返回原始字典（用于测试连接时读盘上的新配置）喵。"""
    # 读文本喵
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SettingsError(f"无法读取配置文件 {path}：{error}") from error
    # 解析喵
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SettingsError(f"配置文件不是合法 YAML：{error}") from error
    return parsed if isinstance(parsed, dict) else {}
