"""待上报数据的磁盘持久化。

为什么需要它：使用时长只存在于内存里，采集端一旦被杀、崩溃或重启，
这段时间的数据就永久丢了，群里的"近 24 小时"统计会出现空洞喵。

存储格式：一个很小的 JSON 文件，形如 {"Code.exe": 120, "chrome.exe": 45}，
写在配置文件旁边（usage-state.json），不进版本库喵。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .usage import PendingBatch

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 状态文件名，放在配置文件同目录喵
STATE_FILE_NAME = "usage-state.json"

# 状态文件格式版本喵
#
# 喵~注意：v1 只有 `{"应用名": 秒数}`，没有上报时刻，无法保证服务端幂等；
# v2 起改成 `{"version": 2, "reported_at": ..., "seconds": {...}}` 喵
STATE_VERSION = 2


def _clean_seconds(raw: object) -> dict[str, int]:
    """把任意对象清洗成「应用名 -> 正整数」的字典喵。

    输入：通常是解析出来的 JSON 片段。
    输出：干净的字典；输入不是字典时返回空字典。
    边界：键必须是非空字符串，值必须是正整数（布尔值不算）喵。
    """
    # 喵~防御：不是字典就当没有数据喵
    if not isinstance(raw, dict):
        return {}
    # 收集干净的条目喵
    cleaned: dict[str, int] = {}
    for app_name, seconds in raw.items():
        # 喵~防御：键必须是非空字符串喵
        if not isinstance(app_name, str) or not app_name.strip():
            continue
        # 喵~防御：值必须是正整数，且要排除 bool（bool 是 int 的子类）喵
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            continue
        # 通过校验才留下喵
        cleaned[app_name] = seconds
    return cleaned


def default_state_path(config_path: Path) -> Path:
    """由配置文件路径推出状态文件路径喵。

    输入：配置文件路径。
    输出：同目录下的 usage-state.json 路径。
    """
    # 与配置文件同目录，方便主人一起备份或删除喵
    return config_path.with_name(STATE_FILE_NAME)


class UsageStore:
    """把待上报的使用时长读写到 JSON 文件喵。"""

    def __init__(self, path: Path) -> None:
        # 状态文件路径喵
        self._path = path

    @property
    def path(self) -> Path:
        """返回状态文件路径，便于日志与测试喵。"""
        # 直接返回内部路径喵
        return self._path

    def load(self) -> dict[str, int]:
        """读取上次未上报的数据喵。

        输出：应用名到秒数的字典；文件不存在或损坏时返回空字典。
        边界：任何读取/解析异常都只记日志，绝不影响采集端启动喵。
        """
        # 读原始 JSON 喵
        parsed = self._read_json()
        # 喵~防御：结构不是字典说明文件被改坏了，丢弃喵
        if not isinstance(parsed, dict):
            return {}
        # 喵~注意：新格式把秒数放在 `seconds` 里，老格式是平铺的字典，两种都要认喵
        source = parsed.get("seconds") if parsed.get("version") == STATE_VERSION else parsed
        # 清洗成"字符串 -> 正整数"喵
        return _clean_seconds(source)

    def _read_json(self) -> object:
        """读取并解析状态文件，失败时返回 None喵。

        输出：解析出来的任意 JSON 值；文件不存在或损坏时返回 None。
        边界：任何读取/解析异常都只记日志，绝不向上抛喵。
        """
        # 喵~防御：文件不存在属于首次运行，正常返回 None喵
        if not self._path.exists():
            return None
        try:
            # 读取并解析 JSON 喵
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            # 喵~防御：文件损坏（断电写一半等）时不能让进程起不来，丢弃旧数据喵
            LOGGER.warning("读取使用时长状态失败，已忽略旧数据：%s", error)
            return None

    def _write_json(self, payload: object) -> None:
        """把任意结构原子写入状态文件喵。

        输入：可 JSON 序列化的对象。
        输出：无。
        边界：写盘失败只记日志，不影响采集与上报喵。
        """
        # 喵~防御：目录可能被删掉，先确保存在喵
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件喵
            temp_path = self._path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            # 再原子替换，避免出现半个 JSON 文件喵
            os.replace(temp_path, self._path)
        except OSError as error:
            # 喵~防御：磁盘满或没权限时不要让主循环崩掉喵
            LOGGER.warning("保存使用时长状态失败：%s", error)

    def save(self, items: dict[str, int]) -> None:
        """把待上报数据写入磁盘（原子替换，避免写一半断电）喵。

        输入：应用名到秒数的字典。
        输出：无。
        边界：写盘失败只记日志，不影响采集与上报喵。

        喵~注意：这个方法是给「还没有身份」的临时快照用的。
        真正要跨重启重发的那一批必须走 `save_batch`，因为只有它记得
        这一批的 `reported_at`，缺了那个服务端就会把重发当成新数据喵。
        """
        # 复用同一套原子写入喵
        self._write_json(items)

    def clear(self) -> None:
        """上报成功后删除状态文件喵。

        输出：无。
        """
        # 喵~防御：文件本来就不存在时不算错误喵
        try:
            if self._path.exists():
                self._path.unlink()
        except OSError as error:
            # 喵~防御：删除失败只记日志，下次 save 会覆盖喵
            LOGGER.warning("清理使用时长状态失败：%s", error)

    def save_batch(self, batch: "PendingBatch") -> None:
        """把待重发批次（秒数 + 固定上报时刻）一起落盘喵。

        输入：`PendingBatch` 实例。
        输出：无。
        边界：写盘失败只记日志，不影响采集与上报喵。

        喵~注意：必须把 `reported_at` 一起存下来。服务端用
        `(device_id, reported_at)` 做幂等键，重启后如果重新取当前时刻，
        这一批就被当成新的，秒数会再加一遍喵。
        """
        # 组装成带版本号的结构，方便以后扩展喵
        payload = {
            "version": STATE_VERSION,
            # 喵~注意：这一批固定的上报时刻，重启后原样带回去喵
            "reported_at": batch.reported_at,
            # 秒数字典喵
            "seconds": batch.seconds,
        }
        # 复用同一套原子写入喵
        self._write_json(payload)

    def load_batch(self) -> "PendingBatch | None":
        """读取上次没发出去的批次喵。

        输出：`PendingBatch`；没有或结构不合法时返回 None。
        边界：任何异常都只记日志并返回 None，绝不影响启动喵。

        喵~注意：这里刻意要求 `reported_at` 存在且非空。
        老版本的状态文件只有秒数字典、没有时刻，那种文件无法保证幂等，
        宁可不重发也不要冒着翻倍的风险发出去喵。
        """
        # 读原始 JSON 喵
        raw = self._read_json()
        # 喵~防御：没有文件或不是字典就不是新格式喵
        if not isinstance(raw, dict):
            return None
        # 喵~防御：必须是带 version 的新格式，老格式没有时刻不能用喵
        if raw.get("version") != STATE_VERSION:
            return None
        # 取固定时刻喵
        reported_at = raw.get("reported_at")
        # 喵~防御：时刻缺失或不是字符串就没法保证幂等，直接放弃喵
        if not isinstance(reported_at, str) or not reported_at.strip():
            return None
        # 取秒数字典喵
        seconds = _clean_seconds(raw.get("seconds"))
        # 空批次不必恢复喵
        if not seconds:
            return None
        # 组装成批次对象喵
        return PendingBatch(seconds, reported_at.strip())
