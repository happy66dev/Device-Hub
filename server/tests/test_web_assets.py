"""看板前端资源测试：时间轴深浅只按「这个应用出现在几台设备上」算喵。

为什么放在 Python 里测 JS：看板是零依赖的原生 JS，仓库里没有 JS 测试框架，
这里把纯函数与渲染函数源码抽出来交给 node 跑一遍，没装 node 的机器直接跳过喵。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# 看板前端目录喵
WEB_DIR = Path(__file__).resolve().parents[1] / "app" / "web"

# app.js 本体路径，多个用例都要读它喵
APP_JS = WEB_DIR / "app.js"

# 本轮改动涉及的纯函数：深浅测算 / 色块渲染 / 整页时间轴渲染喵
PURE_FUNCTIONS = (
    "appDeviceShadeSpot",
    "tipShadeColor",
    "visualBlockHtml",
    "buildVisualBlocks",
    "renderTimeline",
    "deviceShade",
    "deviceShadeRatio",
    "parseCssColor",
    "colorChannel",
    "rgbToHsl",
    "hslToRgb",
)

# 抽函数时要一起带上的模块级常量喵
PURE_CONSTANTS = ("DEVICE_SHADE_STEPS", "DAY_MINUTES", "DAY_SECONDS")

# 测试里给所有应用用的同一个基础色，方便断言「是不是原色」喵
LANE_COLOR = "rgb(35, 93, 255)"

# 渲染函数依赖的一大堆外部函数，全部打成桩，只留被测逻辑是真的喵
STUBS = """
// 桩：转义直接原样返回，断言只看颜色和结构喵
function escapeHtml(value) { return String(value == null ? "" : value); }
// 桩：时长格式化成「N 秒」，断言好写喵
function formatDuration(seconds) { return `${seconds} 秒`; }
// 桩：时钟按 UTC 取时分，测试数据都是 UTC 写的喵
function formatClock(value) {
  const moment = value instanceof Date ? value : new Date(value);
  const pad = (number) => String(number).padStart(2, "0");
  return `${pad(moment.getUTCHours())}:${pad(moment.getUTCMinutes())}`;
}
// 桩：一天中的分钟按 UTC 算，和上面 formatClock 同一口径喵
function minutesOfDay(value) {
  const moment = value instanceof Date ? value : new Date(value);
  return moment.getUTCHours() * 60 + moment.getUTCMinutes() + moment.getUTCSeconds() / 60;
}
// 桩：固定 1 倍缩放，色块宽度才是整段喵
function timelineZoom() { return 1; }
// 桩：刻度与「现在」竖线不参与断言喵
function renderTimelineAxis() {}
function updateTimelineNowLine() {}
// 桩：整天都可画，避免用例受本机时钟影响喵
function timelineNowRatio() { return 1; }
// 桩：没有离线 / 空档区间，只留应用色块喵
function buildStateBlocks() { return []; }
// 桩：汇总行与状态图例不参与断言喵
function timelineSummaryText() { return ""; }
function stateLegendHtml() { return ""; }
// 桩：图标与泳道后缀不参与断言喵
function appIconHtml() { return ""; }
function laneDeviceSuffix() { return ""; }
// 桩：取色是异步的，这里不触发喵
function ensureIconColors() {}
// 桩：就绪标记与截图定位不参与渲染断言喵
function markShotReady() {}
function applyPendingShotFocus() {}
function iconColorKey() { return ""; }
// 桩：图标色缓存，空表表示一个图标色都没取到喵
const iconColorCache = new Map();
// 桩：图标色一律回落到底色，颜色完全可控喵
function pickAppColor(iconColor, fallbackColor) { return fallbackColor || "rgb(0, 0, 0)"; }
// 桩：所有应用共用一个基础色，深浅差异只可能来自 deviceShade 喵
function appColor() { return "__LANE__"; }
// 桩：色板把所有应用都指到同一个颜色喵
function buildColorMap(apps) { return new Map(apps.map((app) => [app, "__LANE__"])); }
// 桩：撞色微调原样透传，别干扰深浅断言喵
function dedupeLaneColors(apps, colorOf) { return new Map(apps.map((app) => [app, colorOf(app)])); }
// 桩：页面状态，字段和 app.js 里的同名喵
const state = {
  timelineZoom: 1,
  timelineTitles: [],
  timelineColors: new Map(),
  timelineAppDevices: new Map(),
  timelineBlocks: [],
  timelineMerged: true,
};
// 桩：页面元素，innerHTML / textContent 都是普通对象属性喵
const el = {
  tlInner: { style: {} },
  tlZoomLabel: {},
  tlScroll: { classList: { toggle() {} }, clientWidth: 900, scrollLeft: 0 },
  tlTrack: { innerHTML: "" },
  tlLanes: { innerHTML: "" },
  tlLegend: { innerHTML: "" },
  tlSummary: { textContent: "" },
}
""".replace("__LANE__", LANE_COLOR)


def extract_function(source: str, name: str) -> str:
    """从 app.js 里按大括号配对抽出整个函数喵。

    输入：app.js 全文、函数名。
    输出：函数源码（含 function 关键字）。
    边界：找不到函数或大括号不配对时抛 AssertionError 喵。
    """
    # 先定位函数头，带上左括号避免抽到同前缀的别的函数喵
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


def extract_constant(source: str, name: str) -> str:
    """从 app.js 里抽出一个模块级常量（数组或标量都行）喵。

    输入：app.js 全文、常量名。
    输出：常量声明源码（含 const 关键字和结尾分号）。
    边界：找不到声明或分号时抛 AssertionError 喵。
    """
    # 先定位声明头喵
    start = source.index(f"const {name} = ")
    # 常量声明以分号结尾，找到第一个分号就够喵
    end = source.index(";", start)
    return source[start : end + 1]


def app_source() -> str:
    """读 app.js 全文，统一用 UTF-8 并保留原始换行喵。"""
    # 用 bytes 解码，换行符不会被 Python 自动转换喵
    return APP_JS.read_bytes().decode("utf-8")


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
    # 喵~注意：node 非零退出多半是语法或桩对不上，必须把 stderr 带出来喵
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def harness(tail: str) -> str:
    """拼出「桩 + 被测函数 + 断言脚本」的完整 JS 喵。

    输入：结尾那段打印结果的脚本。
    输出：可直接交给 node 的源码。
    """
    source = app_source()
    parts = [STUBS]
    for name in PURE_CONSTANTS:
        parts.append(extract_constant(source, name))
    for name in PURE_FUNCTIONS:
        parts.append(extract_function(source, name))
    parts.append(tail)
    return "\n".join(parts)


def segment(app: str, start: str, end: str, seconds: int, device: str) -> dict[str, object]:
    """造一条时间轴使用段，字段名与服务端 /api/v1/timeline 完全一致喵。

    输入：应用名、起止时刻、秒数、设备展示名。
    输出：可以直接塞进 body.segments 的字典。
    边界：只给 device_name，segment 里本来就没有 device_id 喵。
    """
    # 起止时刻用 ISO 字符串，和接口返回的格式一致喵
    return {
        "app": app,
        "package": f"{app}.exe",
        "icon_key": "",
        "start": start,
        "end": end,
        "seconds": seconds,
        "device_name": device,
    }


def build_body(segments: list[dict[str, object]]) -> dict[str, object]:
    """把若干段包成一份完整的时间轴响应体喵。"""
    # 字段和服务端保持一致，缺字段渲染函数会自己兜底喵
    return {
        "date": "2026-11-01",
        "segments": segments,
        "states": [],
        "title_spans": [],
        "total_seconds": sum(int(item["seconds"]) for item in segments),
    }


# 两台设备：cmd 只有 Windows、微信只有手机、QQ 两边都有喵
MIXED_BODY_JS = """
// 一屏两台设备，其中只有 QQ 真的跨了设备喵
const mixedBody = %(body)s;
// 同一批数据去掉 QQ 的 Windows 段，就变成「一个多设备应用都没有」喵
const singleBody = %(single)s;
// 渲染一次并把三块 HTML 都取出来喵
function capture(target) {
  state.timelineMerged = true;
  renderTimeline(target);
  return {
    track: el.tlTrack.innerHTML,
    lanes: el.tlLanes.innerHTML,
    legend: el.tlLegend.innerHTML,
  };
}
const payload = {
  base: %(lane)s,
  // 两台设备里第二台的深浅，和被渲染的色块必须完全一致喵
  second: deviceShade(%(lane)s, 1, 2),
  mixed: capture(mixedBody),
  single: capture(singleBody),
  // 单设备应用查不到序号时也要拿原色喵
  spotSingle: appDeviceShadeSpot("cmd", "本机 Windows", new Map([["cmd", ["本机 Windows"]]])),
  spotMulti: appDeviceShadeSpot("QQ", "本机 Windows", new Map([["QQ", ["手机", "本机 Windows"]]])),
  spotUnknown: appDeviceShadeSpot("cmd", "本机 Windows", new Map()),
};
console.log(JSON.stringify(payload));
"""


def mixed_payload() -> dict[str, object]:
    """跑一次混合设备场景，返回渲染结果与关键颜色喵。"""
    # 混合数据：cmd 单设备、微信单设备、QQ 双设备喵
    mixed = [
        segment("cmd", "2026-11-01T01:00:00Z", "2026-11-01T02:00:00Z", 3600, "本机 Windows"),
        segment("微信", "2026-11-01T03:00:00Z", "2026-11-01T03:30:00Z", 1800, "手机"),
        segment("QQ", "2026-11-01T04:00:00Z", "2026-11-01T04:30:00Z", 1800, "手机"),
        segment("QQ", "2026-11-01T05:00:00Z", "2026-11-01T05:30:00Z", 1800, "本机 Windows"),
    ]
    # 同一屏去掉 QQ 的第二台设备，就只剩单设备应用喵
    single = [item for item in mixed if not (item["app"] == "QQ" and item["device_name"] == "本机 Windows")]
    # 两个 json 字面量直接拼进 JS，省得再写一遍结构喵
    tail = MIXED_BODY_JS % {
        "body": json.dumps(build_body(mixed), ensure_ascii=False),
        "single": json.dumps(build_body(single), ensure_ascii=False),
        "lane": json.dumps(LANE_COLOR),
    }
    return json.loads(run_in_node(harness(tail)))


def backgrounds(html: str) -> list[str]:
    """把一段 HTML 里所有 background:rgb(...) 按出现顺序取出来喵。"""
    # 颜色都是内联样式里我们自己的 rgb()，正则足够喵
    return re.findall(r"background:(rgb\([^)]*\))", html)


def test_single_device_app_keeps_original_color() -> None:
    """单设备应用必须用原始图标色，不管这一屏有几台设备喵。"""
    payload = mixed_payload()
    # 顶层色块按时间顺序：cmd、微信、QQ 手机、QQ Windows 喵
    track = backgrounds(payload["mixed"]["track"])
    assert len(track) == 4, track
    # cmd 只在一台设备上出现，必须原色喵
    assert track[0] == payload["base"]
    # 微信同样只在一台设备上出现，也必须原色喵
    assert track[1] == payload["base"]
    # 喵~注意：微信是第二台设备的独占应用，旧口径会把它压成全局第 2 档深浅，
    # 这里专门排除那个值，才算真的钉住了「单设备应用不加深」喵
    assert track[1] != payload["second"]
    # 泳道里同样只有单设备应用时不能出现任何深浅色喵
    single_lanes = backgrounds(payload["single"]["lanes"])
    assert single_lanes, "泳道没渲染出色块"
    # 一个多设备应用都没有时，全部色块都必须是原色喵
    assert set(single_lanes) == {payload["base"]}, single_lanes
    # 顶层色块也一样，不能因为本屏有两台设备就被压暗喵
    assert set(backgrounds(payload["single"]["track"])) == {payload["base"]}


def test_multi_device_app_still_shaded() -> None:
    """真正跨设备的应用仍然按自己的设备序位分深浅喵。"""
    payload = mixed_payload()
    # 顶层色块里第 4 块是 QQ 在第二台设备上的段喵
    track = backgrounds(payload["mixed"]["track"])
    # 第一台设备（手机）在 QQ 自己的清单里排第 0，用原色喵
    assert track[2] == payload["base"]
    # 第二台设备排第 1，必须比原色深，和 deviceShade(base, 1, 2) 一致喵
    assert track[3] == payload["second"]
    # 两段颜色必须不同，否则泳道里分不出是哪台设备喵
    assert track[2] != track[3]
    # 泳道里 QQ 的两段也要一新一深，不能都塌成原色喵
    assert payload["second"] in backgrounds(payload["mixed"]["lanes"])


def test_device_legend_only_when_multi_device_app_exists() -> None:
    """图例的设备深浅说明只在确实有多设备应用时出现，且色点与色块同色喵。"""
    payload = mixed_payload()
    legend = payload["mixed"]["legend"]
    # 有 QQ 这个跨设备应用时，说明行必须在喵
    assert "tl-legend-device" in legend
    # 说明里的两个色点要用 QQ 自己的设备清单取色喵
    chips = backgrounds(legend)
    assert payload["base"] in chips
    assert payload["second"] in chips
    # 说明里两台设备都要点名，顺序和 QQ 自己的设备清单一致喵
    assert legend.index("手机") < legend.index("本机 Windows")
    # 一个多设备应用都没有时，这一行说明必须隐藏喵
    assert "tl-legend-device" not in payload["single"]["legend"]


def test_device_legend_lists_every_multi_device_app() -> None:
    """同屏有多个跨设备应用时，图例要逐个列出而不是只示意一个喵。"""
    # 两个应用都跨了同一组设备喵
    both = [
        segment("QQ", "2026-11-01T04:00:00Z", "2026-11-01T04:30:00Z", 1800, "手机"),
        segment("QQ", "2026-11-01T05:00:00Z", "2026-11-01T05:30:00Z", 1800, "本机 Windows"),
        segment("微信", "2026-11-01T06:00:00Z", "2026-11-01T06:30:00Z", 1800, "手机"),
        segment("微信", "2026-11-01T07:00:00Z", "2026-11-01T07:30:00Z", 1800, "本机 Windows"),
    ]
    # 渲染一次，只看图例喵
    tail = """
const body = %(body)s;
state.timelineMerged = true;
renderTimeline(body);
console.log(JSON.stringify({ legend: el.tlLegend.innerHTML }));
""" % {"body": json.dumps(build_body(both), ensure_ascii=False)}
    legend = json.loads(run_in_node(harness(tail)))["legend"]
    # 两个多设备应用各占一组说明喵
    assert legend.count("tl-legend-device") == 2, legend
    # 多个应用并存时要带应用名，否则分不清哪组色点属于哪个应用喵
    assert "QQ：" in legend
    assert "微信：" in legend
    # 只取设备说明段里的色点，前面还有泳道本身的图例色点喵
    device_part = legend[legend.index("tl-legend-device") :]
    chips = backgrounds(device_part)
    # 两个应用各两台设备，一共四个色点喵
    assert len(chips) == 4, chips
    # 同一个应用的两台设备必须是两种深浅，两个应用各自取色相喵
    assert chips[0] != chips[1], chips
    assert chips[2] != chips[3], chips


def test_device_legend_lists_all_without_truncation() -> None:
    """多设备应用再多也要全部列出，不截断喵。"""
    # 四个应用各跨两台设备喵
    apps = ["QQ", "微信", "哔哩哔哩", "淘宝"]
    many = []
    for i, app in enumerate(apps):
        # 每个应用各给手机与 Windows 一段喵
        many.append(segment(app, f"2026-11-01T0{i}:00:00Z", f"2026-11-01T0{i}:30:00Z", 1800, "手机"))
        many.append(segment(app, f"2026-11-01T1{i}:00:00Z", f"2026-11-01T1{i}:30:00Z", 1800, "本机 Windows"))
    # 渲染一次，只看图例喵
    tail = """
const body = %(body)s;
state.timelineMerged = true;
renderTimeline(body);
console.log(JSON.stringify({ legend: el.tlLegend.innerHTML }));
""" % {"body": json.dumps(build_body(many), ensure_ascii=False)}
    legend = json.loads(run_in_node(harness(tail)))["legend"]
    # 四个应用一个不少喵
    assert legend.count("tl-legend-device") == len(apps), legend
    # 每个应用名都要出现喵
    for app in apps:
        assert f"{app}：" in legend, app


def test_device_spot_falls_back_to_original_color() -> None:
    """算不出应用设备清单时按单设备处理，宁可原色也不无端压暗喵。"""
    payload = mixed_payload()
    # 单设备应用的序号恒为 0、台数为 1 喵
    assert payload["spotSingle"] == {"index": 0, "total": 1}
    # 多设备应用按设备在自己清单里的位置给序号喵
    assert payload["spotMulti"] == {"index": 1, "total": 2}
    # 清单拿不到时按空清单处理，序号 0 台数 0，取色仍是原色喵
    assert payload["spotUnknown"] == {"index": 0, "total": 0}
    # 原文里找不到这个用例的桩函数时也不该崩，这里只是再确认一次类型喵
    assert isinstance(payload["second"], str)


def test_tip_color_matches_block_color() -> None:
    """悬浮色点与色块用同一套口径，单设备应用必然是原色喵。"""
    output = run_in_node(
        harness(
            """
// 桩：这一屏的颜色表与应用设备清单喵
const colors = new Map([["cmd", %(lane)s], ["QQ", %(lane)s]]);
const appDevices = new Map([["cmd", ["本机 Windows"]], ["QQ", ["手机", "本机 Windows"]]]);
const payload = {
  // 单设备应用：不管指针落在哪台设备上都是原色喵
  single: tipShadeColor("cmd", "本机 Windows", colors, appDevices),
  // 多设备应用：第二台设备要和色块同一个深浅喵
  multiFirst: tipShadeColor("QQ", "手机", colors, appDevices),
  multiSecond: tipShadeColor("QQ", "本机 Windows", colors, appDevices),
  // 没有应用色（空档 / 离线）时不画色点喵
  missing: tipShadeColor("", "", colors, appDevices),
  // 清单缺失时退回原色，不能被算成深色喵
  noList: tipShadeColor("cmd", "本机 Windows", colors, new Map()),
  expectedSecond: deviceShade(%(lane)s, 1, 2),
};
console.log(JSON.stringify(payload));
"""
            % {"lane": json.dumps(LANE_COLOR)}
        )
    )
    payload = json.loads(output)
    # 单设备应用的色点必须和它的色块完全同色喵
    assert payload["single"] == LANE_COLOR
    # 多设备应用第一台是原色、第二台是深色喵
    assert payload["multiFirst"] == LANE_COLOR
    assert payload["multiSecond"] == payload["expectedSecond"]
    # 没有应用色时不画色点喵
    assert payload["missing"] == ""
    # 清单缺失时宁可原色，也不要凭空压暗喵
    assert payload["noList"] == LANE_COLOR


def strip_js_comments(source: str) -> list[str]:
    """把 JS 源码里的 // 与 /* */ 注释全部抹掉，只留会执行的代码喵。

    输入：app.js 全文。
    输出：逐行的「纯代码」文本，行号与原文一一对应。
    边界：字符串里的 // 不特殊处理，这里只用来扫「喵」，够用就行喵。
    """
    # 逐行处理，保留行号方便报错喵
    lines = []
    in_block = False
    for line in source.splitlines():
        code = []
        index = 0
        while index < len(line):
            # 喵~注意：块注释里的一切都不算代码，跨行也要接着吞掉喵
            if in_block:
                end = line.find("*/", index)
                if end < 0:
                    index = len(line)
                else:
                    in_block = False
                    index = end + 2
                continue
            # 行注释一出现，这一行后面的内容都不用看喵
            if line.startswith("//", index):
                break
            # 块注释起点同理，切进块注释状态喵
            if line.startswith("/*", index):
                in_block = True
                index += 2
                continue
            code.append(line[index])
            index += 1
        lines.append("".join(code))
    return lines


def test_ui_text_has_no_cat_noise() -> None:
    """喵只能出现在注释里，任何会显示给用户的文案都不许带喵喵。"""
    source = app_source()
    offenders = []
    # 逐行比对：注释抹掉之后还残留喵，就说明它进了文案或代码喵
    for number, code in enumerate(strip_js_comments(source), 1):
        if "喵" in code:
            offenders.append((number, code.strip()[:80]))
    assert not offenders, offenders
    # 整页渲染出来的三块 HTML 也不许出现喵喵
    payload = mixed_payload()
    for key in ("track", "lanes", "legend"):
        assert "喵" not in payload["mixed"][key]
        assert "喵" not in payload["single"][key]


def test_app_js_keeps_crlf() -> None:
    """app.js 是 CRLF 换行，改完不能留下裸 LF 喵。"""
    raw = APP_JS.read_bytes().decode("utf-8")
    # 裸 LF = 全部 LF 减去 CRLF 的数量喵
    bare = raw.count("\n") - raw.count("\r\n")
    assert bare == 0, f"app.js 里有 {bare} 个裸 LF"
    # 两种统计必须相等，否则说明换行被混着写进去了喵
    assert raw.count("\n") == raw.count("\r\n")
