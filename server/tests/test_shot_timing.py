"""截图时序测试：确认截图是等数据画完之后才拍的喵。

为什么用静态断言而不是真跑浏览器：跑一次真截图要起 Edge/Chrome、导航、
等接口，单次要好几秒还依赖机器上装了浏览器。这里守住的是「等待策略还在」——
真正容易退化的不是像素，而是有人把 waitForShotReady 换回一句 sleep 喵。

喵~注意：这个文件同时盯前端和后端两侧。就绪标记是前端置的、后端等的，
只有两边都在才有效，所以任何一边被改掉都要让这里失败喵。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# 服务端目录喵
SERVER_DIR = Path(__file__).resolve().parents[1]

# 看板前端脚本喵
APP_JS = SERVER_DIR / "app" / "web" / "app.js"

# 截图脚本喵
SHOT_JS = SERVER_DIR / "scripts" / "shot_dashboard.js"


def _read(path: Path) -> str:
    """读一个源文件，读不到就跳过喵。"""
    # 喵~防御：文件不在时让用例跳过，不要报一个看不懂的错喵
    if not path.exists():
        pytest.skip(f"{path} 不存在")
    return path.read_text(encoding="utf-8")


# ==================== 前端：就绪标记 ====================


def test_frontend_sets_shot_ready_marker() -> None:
    """前端必须在渲染完成后置上就绪标记喵。"""
    source = _read(APP_JS)
    # 标记挂在 body.dataset 上，无头浏览器才读得到喵
    assert "shotReady" in source, "app.js 里没有 shotReady 标记，后端无从等待"
    assert "dataset.shotReady" in source


def test_frontend_marker_is_set_after_render() -> None:
    """置位必须出现在渲染函数里，不能只在加载前设一次喵。"""
    source = _read(APP_JS)
    # 时间轴与排行榜是仅有的两个出图页喵
    for function_name in ("renderTimeline", "renderRankings"):
        # 找出函数体再检查里面有没有置位喵
        start = source.find(f"function {function_name}(")
        assert start >= 0, f"找不到 {function_name}"
        # 粗略取到下一个顶层函数声明为止，够用来限定范围喵
        end = source.find("\nfunction ", start + 1)
        body = source[start : end if end > 0 else len(source)]
        # 置位函数名叫 markShotReady，大小写敏感，这里统一转小写再比对喵
        assert "markshotready" in body.lower(), f"{function_name} 里没有置就绪标记"


def test_frontend_marker_carries_tab_name() -> None:
    """标记值要带页签名，后端才能确认截的是对的那一页喵。"""
    source = _read(APP_JS)
    # 至少要能看出标记值取自 state.tab 或页签变量喵
    index = source.find("dataset.shotReady")
    assert index >= 0
    # 往后取一小段，看看赋的值长什么样喵
    window = source[index : index + 200]
    assert "tab" in window, "就绪标记没有带上页签名"


def test_frontend_clears_marker_when_content_changes() -> None:
    """换页签或换日期这类改变截图内容的操作要清掉标记喵。"""
    source = _read(APP_JS)
    # 清位写法通常是把标记删掉或置空喵
    assert ("delete document.body.dataset.shotReady" in source) or (
        'dataset.shotReady = ""' in source
    ), "找不到清就绪标记的代码，换页后可能读到上一轮的旧标记"


# ==================== 后端：等就绪而不是盲等 ====================


def test_backend_waits_for_shot_ready() -> None:
    """截图脚本必须轮询等就绪标记喵。"""
    source = _read(SHOT_JS)
    assert "waitForShotReady" in source, "shot_dashboard.js 里没有等就绪的函数"
    # 必须真的去读那个标记喵
    assert "dataset.shotReady" in source


def test_backend_polls_instead_of_single_sleep() -> None:
    """等就绪必须是循环轮询，不能只是一句固定 sleep 喵。"""
    source = _read(SHOT_JS)
    # 找到函数体喵
    start = source.find("async function waitForShotReady(")
    assert start >= 0
    end = source.find("\nasync function ", start + 1)
    body = source[start : end if end > 0 else len(source)]
    # 循环 + 睡眠轮询 = 真正的等待喵
    assert "while (" in body, "等就绪没有循环，等于没等"
    assert "sleep(" in body, "等就绪没有轮询间隔"
    # 必须按页签名比对，不能只要标记存在就过喵
    assert "tab" in body


def test_backend_has_fallback_when_marker_missing() -> None:
    """前端万一没置上标记，后端要退回固定等待而不是直接失败喵。"""
    source = _read(SHOT_JS)
    # 找到调用点附近喵
    index = source.find("await waitForShotReady(")
    assert index >= 0
    # 往后看一段，要有处理「没等到」的分支喵
    window = source[index : index + 700]
    assert "else" in window, "等就绪没有兜底分支"
    assert "sleep(waitMs)" in window, "没等到标记时没有退回固定等待"


# ==================== 后端：内容自检 ====================


def test_backend_checks_rendered_content() -> None:
    """截图前要确认页面真的画出了内容喵。"""
    source = _read(SHOT_JS)
    assert "assertRendered" in source, "没有内容自检，可能把空白图发到群里"
    # 时间轴要认「加载中」这个渲染前占位喵
    assert "加载中" in source
    # 排行榜要认空态文案，区分「真没数据」和「数据没到」喵
    assert "rank-row" in source


def test_backend_content_check_runs_before_screenshot() -> None:
    """内容自检必须在截屏之前执行喵。"""
    source = _read(SHOT_JS)
    check_index = source.find("await assertRendered(")
    shot_index = source.find("Page.captureScreenshot")
    assert check_index >= 0 and shot_index >= 0
    # 喵~防御：顺序反了就等于没检查喵
    assert check_index < shot_index, "内容自检排在截图之后了，等于没检查"


def test_backend_content_check_allows_legit_empty_state() -> None:
    """真的没有数据时不该抛错，空态文案是合法结果喵。"""
    source = _read(SHOT_JS)
    # 找到自检函数体喵
    start = source.find("async function assertRendered(")
    assert start >= 0
    end = source.find("\nasync function ", start + 1)
    body = source[start : end if end > 0 else len(source)]
    # 空态是 querySelector(".empty") 这种「有文案就算画出内容」的判断喵
    assert ".empty" in body, "自检没有认空态文案，真没数据时会被误判成失败"


# ==================== 后端：命令行参数接线 ====================


def test_snapshot_passes_ready_timeout_env() -> None:
    """超时常量要能从 Python 侧传下去，别写死在 JS 里喵。"""
    snapshot = _read(SERVER_DIR / "app" / "bot" / "snapshot.py")
    # JS 侧读的是这两个环境变量喵
    assert "SHOT_WAIT" in snapshot
