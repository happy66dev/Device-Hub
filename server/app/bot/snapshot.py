"""用无头浏览器截取看板，把命令结果渲染成 PNG 图片。

为什么不在服务端自己画：主人要的是「跟 webui 一模一样」的图，
自己画等于把时间轴、排行、配色的逻辑抄一遍，两边迟早跑偏。
这里直接让 Edge/Chrome 打开对应的看板页签，截内容区就行喵。

注意：图片上的文字同样属于最终用户可见文案，必须中性专业，不能卖萌喵。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot")

# 仓库根目录：本文件在 server/app/bot/ 下，往上三层就是仓库根喵
REPO_ROOT = Path(__file__).resolve().parents[3]

# 截图脚本路径喵
SHOT_SCRIPT = REPO_ROOT / "server" / "scripts" / "shot_dashboard.js"

# Node 可执行文件名，交给 PATH 去找喵
NODE_COMMAND = "node"

# 单次截图的超时秒数，卡住时宁可失败也不要挂着喵
SHOT_TIMEOUT_SECONDS = 60

# 截图宽高：宽度够放排行长名字，高度给足再靠内容区自动撑开喵
SHOT_WIDTH = 1100
SHOT_HEIGHT = 900

# 页面等待毫秒数，等接口回来并画完喵
SHOT_WAIT_MS = 3500


class ShotError(RuntimeError):
    """截图失败，消息本身写给日志看喵。"""


def _node_available() -> bool:
    """检查截图脚本与 node 是否都在位喵。

    输入：无。
    输出：可用时返回 True。
    边界：脚本缺失或 node 不在 PATH 上都返回 False，由调用方退回文本喵。
    """
    # 喵~防御：脚本没部署时直接放弃喵
    if not SHOT_SCRIPT.is_file():
        LOGGER.warning("截图脚本不存在：%s", SHOT_SCRIPT)
        return False
    # node 找不到时也没法截喵
    if shutil.which(NODE_COMMAND) is None:
        LOGGER.warning("找不到 node，无法截图")
        return False
    return True


def shot_url(base_url: str, params: dict[str, str]) -> str:
    """拼出要截的看板地址（不含页签 hash）喵。

    输入：服务端根地址、查询参数。
    输出：带查询串的完整 URL，页签由脚本另外拼到 hash 上喵。
    边界：参数值为空串时直接丢掉，前端会当成「没指定」处理喵。
    """
    # 去掉末尾斜杠，避免拼出双斜杠喵
    root = base_url.rstrip("/")
    # 只保留非空的参数，空值没有意义喵
    cleaned = {key: value for key, value in params.items() if value not in ("", None)}
    # 拼查询串喵
    query = urlencode(cleaned)
    return f"{root}/{'?' + query if query else ''}"


def capture_dashboard(
    base_url: str,
    token: str,
    tab: str,
    params: dict[str, str],
    *,
    selector: str = "",
) -> bytes:
    """打开看板某个页签并截图，返回 PNG 字节喵。

    输入：服务端根地址、上报口令、页签名、查询参数、可选裁剪选择器。
    输出：PNG 字节流。
    边界：node 不可用、超时、脚本报错、产出为空时都抛 ShotError喵。
    """
    # 喵~防御：环境不具备截图条件时明确失败喵
    if not _node_available():
        raise ShotError("截图环境不完整（缺少 node 或脚本）")
    # 临时输出文件，读完就删喵
    handle, raw_path = tempfile.mkstemp(prefix="devicehub-shot-", suffix=".png")
    # 关掉句柄，留给子进程写喵
    os.close(handle)
    out_path = Path(raw_path)
    # 组装子进程环境喵
    env = dict(os.environ)
    env.update(
        {
            # 要截的地址（查询串带截图参数，页签靠 SHOT_HASH）喵
            "SHOT_URL": shot_url(base_url, params),
            # 页签，脚本会把它拼到 hash 上喵
            "SHOT_HASH": f"#/{tab}",
            # 口令，脚本会写进 localStorage 喵
            "SHOT_TOKEN": token,
            # 输出文件喵
            "SHOT_OUT": str(out_path),
            # 视口与等待时间喵
            "SHOT_WIDTH": str(SHOT_WIDTH),
            "SHOT_HEIGHT": str(SHOT_HEIGHT),
            "SHOT_WAIT": str(SHOT_WAIT_MS),
            # 中文输出别乱码喵
            "PYTHONIOENCODING": "utf-8",
        }
    )
    # 只在调用方明确要求时覆盖裁剪区域喵
    if selector:
        env["SHOT_SELECTOR"] = selector
    try:
        # 跑脚本喵
        completed = subprocess.run(
            [NODE_COMMAND, str(SHOT_SCRIPT)],
            env=env,
            capture_output=True,
            timeout=SHOT_TIMEOUT_SECONDS,
            check=False,
            # 喵~防御：Windows 上不弹黑框喵
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # 喵~防御：脚本非零退出时把 stderr 记下来喵
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise ShotError(f"截图脚本失败（{completed.returncode}）：{detail}")
        # 读回 PNG 喵
        data = out_path.read_bytes()
        # 喵~防御：空文件说明脚本没写成功喵
        if not data:
            raise ShotError("截图脚本没有产出文件")
        return data
    except subprocess.TimeoutExpired as error:
        raise ShotError(f"截图超时（{SHOT_TIMEOUT_SECONDS} 秒）") from error
    finally:
        # 清理临时文件喵
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            # 喵~注意：删不掉不影响结果，系统临时目录会回收喵
            pass
