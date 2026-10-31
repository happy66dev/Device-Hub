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

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.agent")

# 状态文件名，放在配置文件同目录喵
STATE_FILE_NAME = "usage-state.json"


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
        # 喵~防御：文件不存在属于首次运行，正常返回空喵
        if not self._path.exists():
            return {}
        try:
            # 读取并解析 JSON 喵
            raw_text = self._path.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
        except (OSError, ValueError) as error:
            # 喵~防御：文件损坏（断电写一半等）时不能让进程起不来，丢弃旧数据喵
            LOGGER.warning("读取使用时长状态失败，已忽略旧数据：%s", error)
            return {}
        # 喵~防御：结构不是字典说明文件被改坏了，丢弃喵
        if not isinstance(parsed, dict):
            LOGGER.warning("使用时长状态格式异常，已忽略")
            return {}
        # 逐项过滤成"字符串 -> 正整数"喵
        cleaned: dict[str, int] = {}
        for app_name, seconds in parsed.items():
            # 喵~防御：键必须是非空字符串，值必须是正整数喵
            if not isinstance(app_name, str) or not app_name.strip():
                continue
            if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
                continue
            cleaned[app_name] = seconds
        return cleaned

    def save(self, items: dict[str, int]) -> None:
        """把待上报数据写入磁盘（原子替换，避免写一半断电）喵。

        输入：应用名到秒数的字典。
        输出：无。
        边界：写盘失败只记日志，不影响采集与上报喵。
        """
        # 喵~防御：目录可能被删掉，先确保存在喵
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件喵
            temp_path = self._path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(items, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            # 再原子替换，避免出现半个 JSON 文件喵
            os.replace(temp_path, self._path)
        except OSError as error:
            # 喵~防御：磁盘满或没权限时不要让主循环崩掉喵
            LOGGER.warning("保存使用时长状态失败：%s", error)

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
