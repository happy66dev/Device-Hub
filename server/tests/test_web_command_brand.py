"""看板命令快捷按钮的品牌词测试：改了 bot.command_brand 后按钮要跟着变喵。

为什么放在 Python 里测 JS：看板是零依赖的原生 JS，仓库里没有 JS 测试框架，
这里把纯函数源码抽出来交给 node 跑一遍，没装 node 的机器直接跳过喵。

喵~注意：这条测试守的是「看板与机器人口径一致」——
命令名可以按配置改名，如果看板按钮还写死 happy，
主人点一下就会发出一条未知命令，机器人那边是完全静默的，看起来像坏了喵。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# 看板前端目录喵
WEB_DIR = Path(__file__).resolve().parents[1] / "app" / "web"

# app.js 本体路径喵
APP_JS = WEB_DIR / "app.js"


def extract_function(source: str, name: str) -> str:
    """从 app.js 里按大括号配对抽出整个函数喵。

    输入：app.js 全文、函数名。
    输出：函数源码（含 function 关键字）。
    边界：找不到函数或大括号不配对时抛 AssertionError 喵。
    """
    # 先定位函数头喵
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            # 回到 0 说明函数体结束喵
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"没找到 {name} 的函数结尾")


# 跑测试用的桩：只保留被断言的逻辑，其余全部打桩喵
HARNESS = """
// 桩：转义原样返回，断言只看文本喵
function escapeHtml(value) { return String(value == null ? "" : value); }
// 桩：命令按钮区，只需要 innerHTML 一个属性喵
const el = { botChips: { innerHTML: "" } };
__STATE__
__FUNCTIONS__
// 渲染一遍并取回按钮文本喵
renderBotChips();
// 喵~注意：node 不会自动打印最后一条表达式，必须显式 console.log 喵
console.log(JSON.stringify({
  html: el.botChips.innerHTML,
  texts: Array.from(el.botChips.innerHTML.matchAll(/data-text="([^"]*)"/g)).map((m) => m[1]),
}));
"""


def run_in_node(tmp_dir: Path, script: str) -> dict:
    """把脚本写进临时文件交给 node 跑，返回解析后的 JSON 喵。

    输入：临时目录、脚本全文。
    输出：脚本最后表达式的 JSON 结果。
    边界：没装 node 时由调用方跳过；node 报错时把 stderr 带进断言信息喵。
    """
    script_path = tmp_dir / "harness.mjs"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    # node 跑挂了要把 stderr 带出来，否则只能看到一个空断言语义喵
    assert completed.returncode == 0, f"node 执行失败：{completed.stderr}"
    return json.loads(completed.stdout)


def test_chips_follow_command_brand(tmp_path: Path) -> None:
    """配置里的品牌词变了，看板按钮必须跟着变喵。"""
    # 没装 node 就跳过，和同目录的 test_web_assets 口径一致喵
    if shutil.which("node") is None:
        pytest.skip("没有 node，跳过前端行为测试")
    source = APP_JS.read_text(encoding="utf-8")
    functions = "\n".join(
        extract_function(source, name) for name in ("commandBrand", "renderBotChips")
    )
    # 造一份配置，品牌词是「小王」喵
    state = (
        'const state = { configFields: '
        '[{ section: "bot", key: "command_brand", value: "小王" }] };'
    )
    script = HARNESS.replace("__STATE__", state).replace("__FUNCTIONS__", functions)
    result = run_in_node(tmp_path, script)
    texts = result["texts"]
    # 每条命令都要带上新品牌，且不能再出现 happy 喵
    assert any("小王设备" in text for text in texts), f"按钮里没有新品牌：{texts}"
    assert all("happy" not in text for text in texts), f"按钮里还有 happy：{texts}"


def test_chips_fall_back_to_happy_without_config(tmp_path: Path) -> None:
    """拿不到配置时按钮要退回 happy，不能渲染出空命令名喵。"""
    if shutil.which("node") is None:
        pytest.skip("没有 node，跳过前端行为测试")
    source = APP_JS.read_text(encoding="utf-8")
    functions = "\n".join(
        extract_function(source, name) for name in ("commandBrand", "renderBotChips")
    )
    # 配置还没加载完的场景喵
    state = "const state = { configFields: [] };"
    script = HARNESS.replace("__STATE__", state).replace("__FUNCTIONS__", functions)
    result = run_in_node(tmp_path, script)
    texts = result["texts"]
    # 退回 happy，而且绝不能出现空品牌导致的「/设备」这种残废命令喵
    assert any("happy设备" in text for text in texts), f"没有退回默认品牌：{texts}"
    assert all(not text.startswith("/设备") for text in texts), f"出现空品牌命令：{texts}"


def test_chips_ignore_blank_brand(tmp_path: Path) -> None:
    """配置里品牌词是空白串时同样退回 happy，不能渲染出空命令名喵。"""
    if shutil.which("node") is None:
        pytest.skip("没有 node，跳过前端行为测试")
    source = APP_JS.read_text(encoding="utf-8")
    functions = "\n".join(
        extract_function(source, name) for name in ("commandBrand", "renderBotChips")
    )
    # 主人把输入框清空但还没保存的场景喵
    state = (
        'const state = { configFields: '
        '[{ section: "bot", key: "command_brand", value: "   " }] };'
    )
    script = HARNESS.replace("__STATE__", state).replace("__FUNCTIONS__", functions)
    result = run_in_node(tmp_path, script)
    texts = result["texts"]
    assert any("happy设备" in text for text in texts), f"空白品牌没退回默认值：{texts}"
