"""配置页「最近活跃」列的跨天显示测试喵。

为什么单独一个文件：这是一个跨零点的显示 bug，不是逻辑 bug——
时间戳本身存得对（UTC），接口返回也对，坏在前端只用时分渲染，
所以修法和测法都在前端这一层喵。

喵~注意：本文件里的 `now` 一律显式注入，绝不取真实系统时间。
跨天 bug 只在「零点前后」这几个小时里露头，如果测试跟着墙上时钟走，
那它一年里有 99% 的时间都在空转，等于没测喵。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# 看板前端目录喵
WEB_DIR = Path(__file__).resolve().parents[1] / "app" / "web"

# 被测函数依赖的工具函数，抽函数时要一起带上喵
HELPER_FUNCTIONS = ("pad2", "inServerZone", "localDateText")


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


def run_in_node(body: str) -> str:
    """把一段 JS 交给 node 执行并取回标准输出喵。

    输入：完整的 JS 源码（自己负责打印结果）。
    输出：标准输出文本。
    边界：本机没有 node 时跳过用例；node 返回非零时把错误信息带出来喵。
    """
    node = shutil.which("node")
    # 喵~防御：没装 node 就跳过，别让前端用例在裸机上红喵
    if node is None:
        pytest.skip("本机没有 node，跳过看板前端行为检查")
    completed = subprocess.run(
        [node, "-e", body],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def harness(tail: str) -> str:
    """拼出「桩 + 被测函数 + 断言脚本」的完整 JS 喵。

    输入：结尾那段打印结果的脚本。
    输出：可直接交给 node 的源码。
    边界：`serverNow` 与 `el` 用最小桩替换，测试不走真实时钟、不碰 DOM喵。
    """
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    parts = [
        # 喵~注意：state 用 var 声明，测试脚本自己再写一个也不会撞车喵
        'var state = { tzOffsetMinutes: 480, clockOffsetMs: 0, timelineZoom: 0 };',
        "function escapeHtml(value) { return String(value == null ? '' : value); }",
        # 喵~注意：真正的 serverNow 读 Date.now()，这里换掉才测得出跨天喵
        'function serverNow() { return new Date("2026-11-02T00:10:00+08:00"); }',
        # 渲染函数要往里写 innerHTML，给个最小的假容器喵
        'var el = { seenUsersList: { innerHTML: "" } };',
    ]
    for name in HELPER_FUNCTIONS:
        parts.append(extract_function(source, name))
    parts.append(extract_function(source, "formatRecentTime"))
    parts.append(extract_function(source, "renderSeenUsers"))
    parts.append(tail)
    return "\n".join(parts)


def test_format_recent_time_marks_yesterday() -> None:
    """跨过零点后，昨天的时间必须和今天的时间长得不一样喵。"""
    output = run_in_node(
        harness(
            """
// 基准：东八区 2026-11-02 00:10，刚过零点十分钟喵
const now = new Date("2026-11-02T00:10:00+08:00");
// 昨天 23:50 执行过命令（UTC 是 11-01T15:50Z）喵
const yesterdayLate = new Date("2026-11-01T15:50:00Z");
// 今天晚上 23:50，也就是同一钟点喵
const todayLate = new Date("2026-11-02T15:50:00Z");
console.log(JSON.stringify({
  now: now.toISOString(),
  yesterday: formatRecentTime(yesterdayLate, now),
  today: formatRecentTime(todayLate, now),
}));
"""
        )
    )
    payload = json.loads(output)
    # 昨天要带「昨天」，不然看不出是哪天喵
    assert payload["yesterday"] == "昨天 23:50"
    # 今天只写时分就够喵
    assert payload["today"] == "23:50"
    # 喵~注意：这就是原 bug——两者以前都是「23:50」，完全分不出来喵
    assert payload["yesterday"] != payload["today"]


def test_format_recent_time_never_shows_future_looking_clock() -> None:
    """零点刚过时，昨天那条不能显示成比现在还晚的钟点喵。

    输入：基准 00:10，记录为昨天 23:50。
    输出：文本里必须出现「昨天」。
    边界：旧实现给「23:50」，看上去像今晚的未来时间喵。
    """
    output = run_in_node(
        harness(
            """
const now = new Date("2026-11-02T00:10:00+08:00");
const justBeforeMidnight = new Date("2026-11-01T15:50:00Z");
console.log(JSON.stringify(formatRecentTime(justBeforeMidnight, now)));
"""
        )
    )
    text = json.loads(output)
    # 必须标明是昨天喵
    assert text.startswith("昨天")
    # 时分照旧保留，方便对日志喵
    assert text.endswith("23:50")


def test_format_recent_time_uses_date_for_older_days() -> None:
    """更早的日子写「月-日」，跨年才写完整年份喵。"""
    output = run_in_node(
        harness(
            """
// 基准固定在东八区 2026-11-02 09:10喵
const now = new Date("2026-11-02T09:10:00+08:00");
console.log(JSON.stringify({
  // 三天前，同年喵
  threeDaysAgo: formatRecentTime(new Date("2026-10-30T14:30:00Z"), now),
  // 去年最后一天喵
  lastYear: formatRecentTime(new Date("2025-12-31T14:30:00Z"), now),
  // 恰好一小时前，还是今天喵
  earlierToday: formatRecentTime(new Date("2026-11-02T00:10:00Z"), now),
}));
"""
        )
    )
    payload = json.loads(output)
    # 同年只写月日，省得每行都重复年份喵
    assert payload["threeDaysAgo"] == "10-30 22:30"
    # 跨年必须写年份，否则和今年同月同日分不清喵
    assert payload["lastYear"] == "2025-12-31 22:30"
    # 今天之内只给时分喵
    assert payload["earlierToday"] == "08:10"


def test_format_recent_time_handles_bad_input() -> None:
    """空值和坏时间要给占位符，不能渲染出 Invalid Date喵。"""
    output = run_in_node(
        harness(
            """
const now = new Date("2026-11-02T09:10:00+08:00");
console.log(JSON.stringify([
  formatRecentTime("", now),
  formatRecentTime(null, now),
  formatRecentTime("这不是时间", now),
]));
"""
        )
    )
    values = json.loads(output)
    # 三种坏输入都必须是同一个占位符喵
    assert values == ["—", "—", "—"]


def test_seen_users_table_distinguishes_yesterday_from_today() -> None:
    """最近发言表格里，昨天和今天同一钟点必须渲染成不同文本喵。

    输入：两个用户，分别是昨天 23:50 与今天 23:50（服务端口径）。
    输出：两行的「最近活跃」单元格文本不同，且昨天那行带「昨天」。
    边界：这正是跨天 bug 的现场——旧实现两行都是「23:50」喵。
    """
    output = run_in_node(
        harness(
            """
// 基准：东八区 2026-11-02 23:55，今天快过完了喵
const now = new Date("2026-11-02T23:55:00+08:00");
const users = [
  // 排在前面的是「昨天 23:50」，比今天这条更早，但钟点更大（看起来更晚）喵
  { channel: "napcat", user_key: "111", display_name: "昨天那位",
    label: "昨天那位", command_count: 3,
    last_seen_at: "2026-11-01T15:50:00Z" },
  { channel: "napcat", user_key: "222", display_name: "今天那位",
    label: "今天那位", command_count: 1,
    last_seen_at: "2026-11-02T15:50:00Z" },
];
renderSeenUsers(users, now);
console.log(JSON.stringify(el.seenUsersList.innerHTML));
"""
        )
    )
    html = json.loads(output)
    # 昨天那行要写「昨天 23:50」喵
    assert "昨天 23:50" in html
    # 今天那行只写「23:50」，且不能带「昨天」喵
    assert ">23:50<" in html
    # 喵~注意：两行不能都渲染成裸「23:50」，那就是原来的 bug喵
    assert html.count(">23:50<") == 1


def test_seen_users_table_passes_server_now() -> None:
    """渲染时必须把「现在」传进去，不能各自去读浏览器时钟喵。

    输入：app.js 源码。
    输出：无。
    边界：`renderSeenUsers` 的调用点要带上基准时刻，否则零点附近会算错天喵。
    """
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # 渲染时要把服务端口径的现在传下去喵
    assert "formatRecentTime(user.last_seen_at, now)" in source
    # 喵~注意：加载函数要把基准时刻传进渲染函数喵
    assert "renderSeenUsers(body.users || [], serverNow())" in source
    # 拉黑时间同样要带日期，不能退回只写时分喵
    assert "formatRecentTime(entry.created_at)" in source
