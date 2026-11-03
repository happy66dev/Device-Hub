"""看板前端的显示规则测试：合并视图 / 排行始终标设备名，时间轴颜色优先取图标混合色喵。

为什么放在 Python 里测 JS：看板是零依赖的原生 JS，仓库里没有 JS 测试框架，
这里把纯函数源码抽出来交给 node 跑一遍，没装 node 的机器直接跳过喵。
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

# 前端里可以直接跑的纯函数，不碰 DOM 也不碰网络喵
PURE_FUNCTIONS = (
    "laneDeviceSuffix",
    "rankingDeviceSuffix",
    "colorChannel",
    "colorLuminance",
    "rgbToHsl",
    "hslToRgb",
    "relativeLuminance",
    "contrastRatio",
    "readableColor",
    "mixIconPixels",
    "pickAppColor",
    "parseCssColor",
    "deviceShadeRatio",
    "deviceShade",
    "shiftLightness",
    "dedupeLaneColors",
    "rankingListHtml",
    "mergeRankingEntries",
    "rankBarHtml",
    "renderRankings",
    # rankingListHtml 画图标时要用到的几个小函数喵
    "appIconHtml",
    "appColor",
    "iconUrl",
    "formatDuration",
    # 统计页热力图的纯函数喵
    "heatmapLevel",
    "heatmapCellStyle",
    "heatmapCellHtml",
    "heatmapCells",
    "pad2",
    "dateText",
    # 请求竞态的序号纯函数喵
    "nextRequestSeq",
    "isStaleResponse",
    # 日期计算要按服务端时区走，这几个是依赖喵
    "serverNow",
    "inServerZone",
    "localDateText",
    # 30 天折线图的纯函数喵
    "trendDates",
    "trendPoints",
    "trendTickText",
    "monotoneCubicPath",
    # 时间轴日期加减（依赖 el/state/loadTimeline 桩）喵
    "shiftTimelineDate",
    # 近 24 小时柱状图（依赖 state/formatClock/formatDuration）喵
    "utcHourKey",
    "usageChart",
    # usageChart 的 tooltip 依赖 formatClock，formatDuration 上面已列喵
    "formatClock",
)

# 纯函数依赖的模块级常量，抽函数时要一起带上喵
PURE_CONSTANTS = ("DEVICE_SHADE_STEPS", "APP_COLORS", "TREND_DAYS", "HEATMAP_LEVELS")


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
    """
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    parts = [
        "function escapeHtml(value) { return String(value); }",
        # 喵~注意：iconUrl 会读 state.token 拼查询串，这里给个最小桩喵
        # 用 var 声明，测试脚本自己再写一个 state 时也不会撞车喵
        'var state = globalThis.state || { token: "test-token", tzOffsetMinutes: 480, clockOffsetMs: 0 };',
    ]
    for name in PURE_CONSTANTS:
        parts.append(extract_constant(source, name))
    for name in PURE_FUNCTIONS:
        parts.append(extract_function(source, name))
    parts.append(tail)
    return "\n".join(parts)


def parse_rgb(value: str) -> tuple[int, int, int]:
    """把前端返回的 rgb(r, g, b) 拆成三个整数喵。

    输入：纯函数返回的颜色字符串。
    输出：(r, g, b) 三元组。
    边界：格式不对时直接断言失败，避免测试悄悄放过喵。
    """
    # 必须是我们约定的 rgb() 格式喵
    assert isinstance(value, str) and value.startswith("rgb(") and value.endswith(")"), value
    # 去掉前缀后缀再按逗号拆开喵
    parts = [int(part.strip()) for part in value[4:-1].split(",")]
    # 必须正好三个通道喵
    assert len(parts) == 3, value
    return parts[0], parts[1], parts[2]


def luminance(rgb: tuple[int, int, int]) -> float:
    """按前端同一套权重算亮度，用来断言修正后的可读范围喵。"""
    # 权重和 app.js 里的 colorLuminance 保持一致喵
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def test_merged_timeline_always_labels_device() -> None:
    """合并时间轴（组 / 所有设备）里哪怕只有一台设备也要标出设备名喵。"""
    # 合并视图单设备、双设备、四设备、没设备名，以及单设备视图各跑一次喵
    output = run_in_node(
        harness(
            """
const cases = {
  single: laneDeviceSuffix(["本机 Windows"], true),
  pair: laneDeviceSuffix(["本机 Windows", "手机"], true),
  many: laneDeviceSuffix(["A", "B", "C", "D"], true),
  empty: laneDeviceSuffix([], true),
  solo: laneDeviceSuffix(["本机 Windows"], false),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 合并视图里单设备必须标出来，这是这次改的重点喵
    assert "本机 Windows" in cases["single"]
    # 多设备要列全，超过两台才收尾喵
    assert "本机 Windows" in cases["pair"] and "手机" in cases["pair"]
    assert "等 4 台" in cases["many"]
    # 没设备名时不能出现空括号喵
    assert cases["empty"] == ""
    # 单设备视图靠下拉框认设备，泳道标题不重复标喵
    assert cases["solo"] == ""


def test_ranking_always_labels_device() -> None:
    """应用排行里只有一台设备用过时也要标出设备名喵。"""
    output = run_in_node(
        harness(
            """
const cases = {
  one: rankingDeviceSuffix({ devices: ["本机 Windows"] }),
  many: rankingDeviceSuffix({ devices: ["本机 Windows", "手机"] }),
  none: rankingDeviceSuffix({ devices: [] }),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 单设备也要标，否则看不出这个应用是哪台设备用的喵
    assert "本机 Windows" in cases["one"]
    assert "手机" in cases["many"]
    # 拿不到设备名时保持原样喵
    assert cases["none"] == ""


def test_mix_icon_pixels_alpha_weighted() -> None:
    """图标像素按 alpha 加权平均，半透明像素的权重更小喵。"""
    output = run_in_node(
        harness(
            """
const cases = {
  // 两个不透明像素各占一半，混合出紫色喵
  even: mixIconPixels([[255, 0, 0, 255], [0, 0, 255, 255]]),
  // 第二个像素 alpha 只有 64，蓝色只占约五分之一喵
  weighted: mixIconPixels([[255, 0, 0, 255], [0, 0, 255, 64]]),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 权重相同时红色和蓝色各一半，四舍五入后是 128 喵
    assert cases["even"] == "rgb(128, 0, 128)"
    # 权重 255:64 时红色约 204、蓝色约 51，绿色一直是 0 喵
    assert cases["weighted"] == "rgb(204, 0, 51)"


def test_mix_icon_pixels_skips_transparent() -> None:
    """alpha 小于 32 的像素直接跳过，不参与混合喵。"""
    output = run_in_node(
        harness(
            """
const cases = {
  // 半透明白色应该被跳过，只剩不透明的绿色喵
  skipped: mixIconPixels([[255, 255, 255, 10], [0, 128, 0, 255]]),
  // 结构不完整的脏像素也要跳过，不能把整张图算崩喵
  dirty: mixIconPixels([[255, 0, 0, 255], [1, 2], null, "x"]),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 跳过后只剩绿色，绿色亮度适中不会被修正喵
    assert cases["skipped"] == "rgb(0, 128, 0)"
    # 脏像素被忽略后仍然是不透明的红色喵
    assert cases["dirty"] == "rgb(255, 0, 0)"


def test_mix_icon_pixels_skips_black_and_white() -> None:
    """纯黑 / 纯白像素是图标底色和字形，不参与混合喵。"""
    output = run_in_node(
        harness(
            """
const cases = {
  // 白底 + 黑字 + 绿色主色，只剩绿色喵
  mixed: mixIconPixels([[255, 255, 255, 255], [0, 0, 0, 255], [0, 128, 0, 255]]),
  // 只有黑白（例如命令行图标）时没有主色可取，返回 null 喵
  mono: mixIconPixels([[255, 255, 255, 255], [0, 0, 0, 255]]),
  // 阈值边缘的像素也要跳过喵
  edges: mixIconPixels([[235, 235, 235, 255], [24, 24, 24, 255], [0, 128, 0, 255]]),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 黑白都被剔除后只剩绿色喵
    assert cases["mixed"] == "rgb(0, 128, 0)"
    # 纯黑白图标视为取色失败，调用方会退回原配色喵
    assert cases["mono"] is None
    # 阈值边缘的像素同样跳过喵
    assert cases["edges"] == "rgb(0, 128, 0)"


def test_mix_icon_pixels_all_transparent_returns_null() -> None:
    """全透明或没有像素时视为取色失败，返回 null 喵。"""
    output = run_in_node(
        harness(
            """
const cases = {
  // 全部低于 alpha 阈值喵
  transparent: mixIconPixels([[0, 0, 0, 0], [255, 255, 255, 31]]),
  // 空数组喵
  empty: mixIconPixels([]),
  // 不是数组的脏输入喵
  invalid: mixIconPixels(null),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    cases = json.loads(output)
    # 三种失败情况都必须是 null，调用方才能判断要不要退回原配色喵
    assert cases["transparent"] is None
    assert cases["empty"] is None
    assert cases["invalid"] is None


def test_readable_color_enforces_contrast() -> None:
    """太亮 / 太暗的颜色都会被修到对轨道底色 3:1 以上喵。"""
    output = run_in_node(
        harness(
            r"""
const ratioOf = (value) => {
  const parts = value.slice(4, -1).split(",").map((part) => Number(part));
  return contrastRatio(parts, [242, 243, 245]);
};
const cases = {
  // 纯白：必须按对比度压暗喵
  white: readableColor(255, 255, 255),
  // 纯黑：必须先提亮，再保证对比度喵
  black: readableColor(0, 0, 0),
  // 接近白的灰色：同样要压暗喵
  washed: readableColor(235, 235, 235),
  // 偏亮的浅蓝色：压到 3:1，同时保留色相喵
  pale: readableColor(211, 218, 251),
  // 本来就清楚的颜色不能被乱改喵
  normal: readableColor(0, 128, 0),
};
console.log(JSON.stringify({
  cases,
  ratios: {
    white: ratioOf(cases.white),
    black: ratioOf(cases.black),
    washed: ratioOf(cases.washed),
    pale: ratioOf(cases.pale),
    normal: ratioOf(cases.normal),
  },
}));
"""
        )
    )
    cases = json.loads(output)
    # 所有修正后的颜色对轨道底色都必须达到 3:1 喵
    for key in ("white", "black", "washed", "pale", "normal"):
        assert cases["ratios"][key] >= 3.0
    # 纯白会被压暗，纯黑会被提亮喵
    assert cases["cases"]["white"] != "rgb(255, 255, 255)"
    assert cases["cases"]["black"] != "rgb(0, 0, 0)"
    # 浅蓝色保留色相，不能压成一块灰喵
    pale = parse_rgb(cases["cases"]["pale"])
    assert not (pale[0] == pale[1] == pale[2])
    # 本来就够清楚的颜色保持原样喵
    assert cases["cases"]["normal"] == "rgb(0, 128, 0)"


def test_contrast_ratio_formula() -> None:
    """WCAG 黑白对比度是 21:1，同色是 1:1 喵。"""
    output = run_in_node(
        harness(
            """
console.log(JSON.stringify({
  bw: contrastRatio([0, 0, 0], [255, 255, 255]),
  same: contrastRatio([120, 130, 140], [120, 130, 140]),
  track: contrastRatio([0, 0, 0], [242, 243, 245]),
}));
"""
        )
    )
    cases = json.loads(output)
    # 黑白对比度是标准上限 21:1 喵
    assert abs(cases["bw"] - 21.0) < 0.05
    # 同一个颜色对比度是 1:1 喵
    assert abs(cases["same"] - 1.0) < 1e-9
    # 纯黑对轨道底色也要远超 3:1 喵
    assert cases["track"] > 15


def test_readable_color_keeps_hue() -> None:
    """浅色调图标按对比度压暗后仍保留色相，不会变成灰喵。"""
    output = run_in_node(
        harness(
            """
console.log(JSON.stringify({
  // 很浅的橙色，会按对比度压暗但保留色相喵
  pale: readableColor(250, 240, 230),
  // 本来就清楚的中蓝色不应被改动喵
  mid: readableColor(32, 96, 160),
}));
"""
        )
    )
    cases = json.loads(output)
    # 压暗后亮度要落回可读区间喵
    assert luminance(parse_rgb(cases["pale"])) <= 235
    # 补彩度后红绿蓝不能完全相等，否则就成了一块灰喵
    pale = parse_rgb(cases["pale"])
    assert not (pale[0] == pale[1] == pale[2])
    # 本来就清楚的中蓝色只允许四舍五入的误差喵
    mid = parse_rgb(cases["mid"])
    assert abs(mid[0] - 32) <= 1 and abs(mid[1] - 96) <= 1 and abs(mid[2] - 160) <= 1


def test_icon_color_falls_back_to_palette() -> None:
    """取色失败时调用方必须退回原来的配色方案喵。

    说明：真正的兜底是 renderTimeline 里的 buildColorMap / appColor，
    它们依赖 DOM 与模块级色板常量，没法直接塞进 node 脚手架；
    这里测它们前面的纯函数接缝 pickAppColor：null 一定要回落到色板色喵。
    """
    output = run_in_node(
        harness(
            """
const failed = mixIconPixels([[255, 255, 255, 0]]);
const cases = {
  // 全透明图标取色失败，必须用原来的色板颜色喵
  fallback: pickAppColor(failed, "#165dff"),
  // 取色成功时优先用图标混合色喵
  icon: pickAppColor(mixIconPixels([[0, 128, 0, 255]]), "#165dff"),
  // 空字符串也算没取到色喵
  empty: pickAppColor("", "#00b42a"),
  // undefined 同样走兜底喵
  missing: pickAppColor(undefined, "#ff7d00"),
};
console.log(JSON.stringify({ failed, ...cases }));
"""
        )
    )
    cases = json.loads(output)
    # 全透明图标返回 null 喵
    assert cases["failed"] is None
    # null 时回落到原来的色板颜色喵
    assert cases["fallback"] == "#165dff"
    # 取色成功时图标色优先喵
    assert cases["icon"] == "rgb(0, 128, 0)"
    # 空值都走兜底喵
    assert cases["empty"] == "#00b42a"
    assert cases["missing"] == "#ff7d00"

def test_device_shade_keeps_first_device_and_darkens_others() -> None:
    """同一应用多设备共存时按设备序号改深浅，第一台保持原色喵。"""
    output = run_in_node(
        harness(
            """
const base = "rgb(100, 150, 200)";
const cases = {
  first: deviceShade(base, 0),
  second: deviceShade(base, 1),
  third: deviceShade(base, 2),
  hex: deviceShade("#336699", 1),
  unknown: deviceShade("不是颜色", 1),
  dark: deviceShade("rgb(6, 6, 6)", 3),
  ratios: [0, 1, 2, 3, 100].map((index) => deviceShadeRatio(index)),
};
console.log(JSON.stringify(cases));
"""
        )
    )
    payload = json.loads(output)
    base = (100, 150, 200)
    # 第一台设备必须用原色，别把主设备也改掉喵
    assert parse_rgb(payload["first"]) == base
    # 亮色基础色会逐级压深，两台设备必须能分开喵
    second = parse_rgb(payload["second"])
    third = parse_rgb(payload["third"])
    assert luminance(second) < luminance(base)
    assert luminance(third) < luminance(second)
    assert second != third
    # 十六进制色板也要能算出深浅，不能只认 rgb() 喵
    assert payload["hex"].startswith("rgb(")
    # 认不出的颜色原样返回，绝不画出脏色喵
    assert payload["unknown"] == "不是颜色"
    # 极深的基础色要提到看得见的亮度，不能糊成黑块喵
    assert luminance(parse_rgb(payload["dark"])) > 30
    # 渐变比例：第一台 0，之后单调递增，最多到 1 喵
    ratios = payload["ratios"]
    assert ratios[0] == 0
    assert 0 < ratios[1] < ratios[2] < ratios[3] < ratios[4]
    assert ratios[4] == 1


def test_dedupe_lane_colors_breaks_ties_only() -> None:
    """同屏撞色的应用要微调出区别，没撞色的保持原样喵。"""
    output = run_in_node(
        harness(
            """
const palette = {
  same1: "rgb(120, 160, 200)",
  same2: "rgb(120, 160, 200)",
  unique: "rgb(30, 30, 30)",
  hex: "#336699",
  hexSame: "#336699",
};
const colors = dedupeLaneColors(Object.keys(palette), (app) => palette[app]);
console.log(JSON.stringify({
  same1: colors.get("same1"),
  same2: colors.get("same2"),
  unique: colors.get("unique"),
  hex: colors.get("hex"),
  hexSame: colors.get("hexSame"),
}));
"""
        )
    )
    payload = json.loads(output)
    # 第一条用原色，第二条被微调走，不能两条泳道一个颜色喵
    assert payload["same1"] == "rgb(120, 160, 200)"
    assert payload["same2"] != payload["same1"]
    # 没撞色的应用颜色保持原样喵
    assert payload["unique"] == "rgb(30, 30, 30)"
    # 十六进制撞色也要能区分开喵
    assert payload["hexSame"] != payload["hex"]


def test_dedupe_lane_colors_keeps_visible_gap() -> None:
    """同色微调不能只差 1 个色阶，至少要让肉眼分得开喵。"""
    output = run_in_node(
        harness(
            """
const apps = ["a", "b", "c", "d"];
const colors = dedupeLaneColors(apps, () => "rgb(97, 145, 185)");
const parsed = apps.map((app) => parseCssColor(colors.get(app)));
const gaps = [];
for (let i = 0; i < parsed.length; i += 1) {
  for (let j = i + 1; j < parsed.length; j += 1) {
    gaps.push(Math.max(
      Math.abs(parsed[i].r - parsed[j].r),
      Math.abs(parsed[i].g - parsed[j].g),
      Math.abs(parsed[i].b - parsed[j].b),
    ));
  }
}
console.log(JSON.stringify({ colors: apps.map((app) => colors.get(app)), minGap: Math.min(...gaps) }));
"""
        )
    )
    payload = json.loads(output)
    # 四个同色应用必须都调开喵
    assert len(set(payload["colors"])) == 4
    # 任意两色的最大通道差至少 18，避免只差 1 个色阶的假区分喵
    assert payload["minGap"] >= 18


def test_render_rankings_switches_between_flat_and_grouped() -> None:
    """排行页要在总排行与按设备 / 按组之间切换，没分组数据时退回总排行喵。"""
    output = run_in_node(
        harness(
            """
// 桩：排行渲染只用到这几个外部依赖喵
function escapeHtml(value) { return String(value); }
function appIconHtml() { return ""; }
function appColor() { return "rgb(100, 150, 200)"; }
function formatDuration(seconds) { return `${seconds} 秒`; }
// 桩：就绪标记不参与排行断言喵
function markShotReady() {}
// 桩：全局状态与元素喵
// 喵~注意：harness 已经声明了 var state，这里直接改它的字段而不是重新声明喵
state.rankings = [];
state.rankingScope = "all";
state.rankingGroups = [];
const el = { rankingBody: { innerHTML: "" }, rankingSummary: { textContent: "" } };
const entry = (app, seconds) => ({ app, package: `${app}.exe`, seconds, device_count: 1, devices: ["本机 Windows"] });
// 总排行：扁平列表，没有分组小节喵
state.rankings = [entry("Code.exe", 3600), entry("QQ.exe", 600)];
renderRankings();
const flat = { html: el.rankingBody.innerHTML, summary: el.rankingSummary.textContent };
// 按设备：服务端给了两组，要渲染出两个小节喵
state.rankingScope = "device";
state.rankingGroups = [
  { key: "win-1", label: "本机 Windows", kind: "device", seconds: 3600, entries: [entry("Code.exe", 3600)] },
  { key: "and-1", label: "手机", kind: "device", seconds: 600, entries: [entry("QQ.exe", 600)] },
];
renderRankings();
const grouped = { html: el.rankingBody.innerHTML, summary: el.rankingSummary.textContent };
// 选了按组但接口没给分组数据：要退回扁平列表，不能白屏喵
state.rankingScope = "group";
state.rankingGroups = [];
renderRankings();
const fallback = { html: el.rankingBody.innerHTML, summary: el.rankingSummary.textContent };
console.log(JSON.stringify({ flat, grouped, fallback }));
"""
        )
    )
    payload = json.loads(output)
    # 总排行：有排行行、没有分组小节喵
    assert "rank-row" in payload["flat"]["html"]
    assert "rank-group" not in payload["flat"]["html"]
    assert "个应用" in payload["flat"]["summary"]
    # 按设备：两个组各一个小节，组名与组合计都出现喵
    assert payload["grouped"]["html"].count('class="rank-group"') == 2
    assert "本机 Windows" in payload["grouped"]["html"]
    assert "手机" in payload["grouped"]["html"]
    assert "共 2 组" in payload["grouped"]["summary"]
    # 没有分组数据时退回扁平列表喵
    assert "rank-group" not in payload["fallback"]["html"]
    assert "rank-row" in payload["fallback"]["html"]


def test_merge_ranking_entries_merges_same_app_across_devices() -> None:
    """同名应用的多条排行要合并成一行，多设备合并成一条条形喵。"""
    output = run_in_node(
        harness(
            """
// 同一个 QQ 在两端包名不同，服务端会返回两条喵
const entries = [
  { app: "QQ", package: "qq.exe", seconds: 90, device_count: 1, devices: ["本机 Windows"], device_seconds: [{ device: "本机 Windows", seconds: 90 }] },
  { app: "QQ", package: "com.tencent.mobileqq", seconds: 30, device_count: 1, devices: ["手机"], device_seconds: [{ device: "手机", seconds: 30 }] },
  { app: "Code.exe", package: "Code.exe", seconds: 600, device_count: 1, devices: ["本机 Windows"], device_seconds: [{ device: "本机 Windows", seconds: 600 }] },
];
const rows = mergeRankingEntries(entries).map((row) => ({
  app: row.app,
  seconds: row.seconds,
  packages: row.packages,
  devices: row.devices,
  deviceSeconds: [...row.deviceSeconds.entries()],
}));
console.log(JSON.stringify(rows));
"""
        )
    )
    rows = json.loads(output)
    # Code.exe 最长排第一，QQ 合并后 120 秒排第二喵
    assert [row["app"] for row in rows] == ["Code.exe", "QQ"]
    qq = rows[1]
    # 两条 QQ 合成一行，秒数相加喵
    assert qq["seconds"] == 120
    # 两个平台的包名都列出来，副标题要用喵
    assert qq["packages"] == ["qq.exe", "com.tencent.mobileqq"]
    # 两台设备按首次出现排序，标题里的「（A、B）」用它喵
    assert qq["devices"] == ["本机 Windows", "手机"]
    # 每台设备各自的秒数要能取到，条形才能切段喵
    assert qq["deviceSeconds"] == [["本机 Windows", 90], ["手机", 30]]


def test_merge_ranking_entries_keeps_icon_key() -> None:
    """合并排行时必须带走 icon_key，否则排行榜永远只画彩色圆点喵。"""
    output = run_in_node(
        harness(
            """
// 服务端每行都会给 icon_key，合并时不能丢喵
const entries = [
  { app: "QQ", package: "qq.exe", seconds: 90, device_count: 1, devices: ["本机 Windows"], icon_key: "abc123" },
  { app: "QQ", package: "com.tencent.mobileqq", seconds: 30, device_count: 1, devices: ["手机"], icon_key: "def456" },
  { app: "cmd", package: "cmd.exe", seconds: 10, device_count: 1, devices: ["本机 Windows"] },
];
const rows = mergeRankingEntries(entries).map((row) => ({ app: row.app, icon_key: row.icon_key }));
console.log(JSON.stringify(rows));
"""
        )
    )
    rows = json.loads(output)
    by_app = {row["app"]: row["icon_key"] for row in rows}
    # 合并后的 QQ 要保留第一次见到的那个图标键喵
    assert by_app["QQ"] == "abc123"
    # 喵~注意：没有图标时给空串，前端靠它退回彩色圆点喵
    assert by_app["cmd"] == ""


def test_ranking_row_renders_icon_when_icon_key_present() -> None:
    """有 icon_key 时排行榜必须渲染 <img>，不能再退回圆点喵。"""
    output = run_in_node(
        harness(
            """
// 造一条带图标的排行壳喵
const row = { app: "QQ", seconds: 90, devices: ["本机 Windows"], packages: ["qq.exe"], icon_key: "abc123" };
const withIcon = rankingListHtml([row]);
const noIcon = rankingListHtml([{ ...row, icon_key: "" }]);
console.log(JSON.stringify({ withIcon, noIcon }));
"""
        )
    )
    payload = json.loads(output)
    # 有图标键要出 <img class="app-icon"喵
    assert 'class="app-icon"' in payload["withIcon"]
    assert "/api/v1/icons/abc123" in payload["withIcon"]
    # 没有图标键时退回色块喵
    assert "app-icon" not in payload["noIcon"]
    assert "tl-dot" in payload["noIcon"]


def test_heatmap_helpers_cover_edge_cases() -> None:
    """热力图的色阶与格子生成要能处理空数据、未来日期与单日喵。"""
    output = run_in_node(
        harness(
            """
// 色阶：0 秒最浅，达到峰值最深，喵
const levels = [
  heatmapLevel(0, 1000),
  heatmapLevel(100, 1000),
  heatmapLevel(300, 1000),
  heatmapLevel(600, 1000),
  heatmapLevel(1000, 1000),
  heatmapLevel(500, 0),
];
// 格子必须是 7 的整数倍，且最后一天是周六喵
const cells = heatmapCells(30);
console.log(JSON.stringify({
  levels,
  count: cells.length,
  weeks: cells.length % 7,
  blanks: cells.filter((cell) => cell.blank).length,
  hasDate: /^\\d{4}-\\d{2}-\\d{2}$/.test(cells[0].date),
}));
"""
        )
    )
    payload = json.loads(output)
    # 色阶必须是 0→1→2→3→4 单调加深喵
    assert payload["levels"][:5] == [0, 1, 2, 3, 4]
    # 喵~防御：峰值缺失时不能除零，有数据就算一级喵
    assert payload["levels"][5] == 1
    # 网格要铺满整周，否则行列会错位喵
    assert payload["weeks"] == 0
    assert payload["count"] % 7 == 0
    # 日期格式必须是 YYYY-MM-DD喵
    assert payload["hasDate"] is True


def test_web_assets_register_stats_tab() -> None:
    """统计页要真的接线：导航、面板、加载与截图标记都得在喵。"""
    web_dir = Path(__file__).resolve().parents[1] / "app" / "web"
    # 导航与面板喵
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="stats"' in html
    assert 'id="panel-stats"' in html
    assert 'id="heatmap-body"' in html
    # 前端逻辑喵
    app_js = (web_dir / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/stats/heatmap" in app_js
    assert 'if (tab === "stats") loadStats();' in app_js
    assert '"stats"' in app_js
    # 喵~注意：统计页也要置就绪标记，否则截图会一直等到超时喵
    assert 'markShotReady("stats")' in app_js
    # 样式喵
    css = (web_dir / "styles.css").read_text(encoding="utf-8")
    assert ".heatmap-cell" in css
    assert ".heatmap-cells" in css


def test_trend_points_fill_missing_days_with_zero() -> None:
    """折线图必须把没有记录的日子补成 0，不能跳过喵。"""
    output = run_in_node(
        harness(
            """
// 30 天里只有两天有数据，中间的空档必须补 0喵
const points = trendPoints(
  [{ date: "2026-11-01", seconds: 3600 }, { date: "2026-11-02", seconds: 1800 }],
  30
);
console.log(JSON.stringify({
  count: points.length,
  zeros: points.filter((point) => point.seconds === 0).length,
  sums: points.reduce((sum, point) => sum + point.seconds, 0),
  last: points[points.length - 1],
  sorted: points.every((point, index) => index === 0 || points[index - 1].date < point.date),
}));
"""
        )
    )
    payload = json.loads(output)
    # 点数必须恰好等于天数喵
    assert payload["count"] == 30
    # 只有两天有数据，其余 28 天都是 0喵
    assert payload["zeros"] == 28
    # 总秒数不能被补齐操作改变喵
    assert payload["sums"] == 5400
    # 日期必须严格递增，否则横轴会回折喵
    assert payload["sorted"] is True
    # 最后一天是今天喵
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", payload["last"]["date"])


def test_trend_dates_count_and_order() -> None:
    """日期序列长度与顺序要稳定，折线图的横轴靠它喵。"""
    output = run_in_node(
        harness(
            """
const week = trendDates(7);
const sameDay = trendDates(1);
const zero = trendDates(0);
console.log(JSON.stringify({ week, sameDay, zero }));
"""
        )
    )
    payload = json.loads(output)
    assert len(payload["week"]) == 7
    # 严格递增喵
    dates = payload["week"]
    assert all(dates[index] < dates[index + 1] for index in range(len(dates) - 1))
    # 只要一天时就是今天喵
    assert len(payload["sameDay"]) == 1
    assert payload["sameDay"] == [dates[-1]]
    # 喵~防御：天数传 0 或负数时按 1 天处理，不能返回空数组喵
    assert len(payload["zero"]) == 1


def test_trend_tick_text_uses_hours_and_minutes() -> None:
    """刻度文本满一小时说小时，否则说分钟喵。"""
    output = run_in_node(
        harness(
            """
console.log(JSON.stringify([
  trendTickText(0),
  trendTickText(1800),
  trendTickText(3600),
  trendTickText(5400),
  trendTickText(7200),
]));
"""
        )
    )
    ticks = json.loads(output)
    assert ticks[0] == "0 分"
    assert ticks[1] == "30 分"
    # 整小时不带小数喵
    assert ticks[2] == "1 小时"
    # 半点用一位小数喵
    assert ticks[3] == "1.5 小时"
    assert ticks[4] == "2 小时"


def test_web_assets_register_trend_chart() -> None:
    """30 天折线图要真的接线喵。"""
    web_dir = Path(__file__).resolve().parents[1] / "app" / "web"
    # 容器喵
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    assert 'id="trend-body"' in html
    assert 'id="trend-summary"' in html
    # 渲染与接线喵
    app_js = (web_dir / "app.js").read_text(encoding="utf-8")
    assert "function renderTrend(" in app_js
    assert "renderTrend(payload)" in app_js
    # 喵~注意：Y 轴是使用时长，不是次数喵
    assert "每日使用时长" in app_js or "使用时长" in html
    # 样式喵
    css = (web_dir / "styles.css").read_text(encoding="utf-8")
    assert ".trend-line" in css
    assert ".trend-area" in css


def test_monotone_cubic_path_never_overshoots() -> None:
    """平滑曲线不许冲过相邻数据点，否则 0 值那段会画出负值喵。"""
    output = run_in_node(
        harness(
            """
// 关键场景：长时间为 0，突然有一天很高，再掉回 0喵
// 普通平滑会在 0 段下方冲成负值，单调插值必须贴住基线喵
const nodes = [
  { x: 0, y: 200 },
  { x: 10, y: 200 },
  { x: 20, y: 20 },
  { x: 30, y: 200 },
  { x: 40, y: 200 },
];
const path = monotoneCubicPath(nodes);
// 取出路径里所有 y 坐标（M/C 后面的数字对里的第二个）喵
const numbers = path.match(/-?\\d+\\.?\\d*/g).map(Number);
const ys = [];
// M x,y 与 C x1,y1 x2,y2 x,y 的 y 都在奇数位喵
for (let index = 0; index < numbers.length; index += 2) ys.push(numbers[index + 1]);
console.log(JSON.stringify({
  path,
  minY: Math.min(...ys),
  maxY: Math.max(...ys),
  hasCurve: path.includes("C"),
}));
"""
        )
    )
    payload = json.loads(output)
    # 必须有曲线段喵
    assert payload["hasCurve"] is True
    # 喵~防御：y 坐标不能小于数据最小值 20（也就是不能冲到更高处）喵
    assert payload["minY"] >= 20 - 0.5, f"曲线冲过头了：minY={payload['minY']}"
    # y 坐标不能大于基线 200（也就是不能在基线下画负值）喵
    assert payload["maxY"] <= 200 + 0.5, f"曲线越过基线了：maxY={payload['maxY']}"


def test_monotone_cubic_path_handles_short_input() -> None:
    """点数不足时不能崩，要有可预测的退化行为喵。"""
    output = run_in_node(
        harness(
            """
console.log(JSON.stringify({
  empty: monotoneCubicPath([]),
  single: monotoneCubicPath([{ x: 0, y: 10 }]),
  two: monotoneCubicPath([{ x: 0, y: 10 }, { x: 10, y: 20 }]),
}));
"""
        )
    )
    payload = json.loads(output)
    # 空与单点都返回空串喵
    assert payload["empty"] == ""
    assert payload["single"] == ""
    # 两点退化成直线，但必须有 M 和 L喵
    assert payload["two"].startswith("M")
    assert "L" in payload["two"]


def test_monotone_cubic_path_is_smooth() -> None:
    """相邻控制点必须共线于切线，否则曲线会有折角喵。"""
    output = run_in_node(
        harness(
            """
const path = monotoneCubicPath([
  { x: 0, y: 100 },
  { x: 10, y: 50 },
  { x: 20, y: 80 },
]);
console.log(JSON.stringify({ path, segments: (path.match(/C/g) || []).length }));
"""
        )
    )
    payload = json.loads(output)
    # 三个点要出两段三次贝塞尔喵
    assert payload["segments"] == 2


def test_trend_dates_ignore_browser_timezone() -> None:
    """日期轴按服务端时区算，浏览器时区改了不能偏移一天喵。

    喵~注意：这个用例分别在 UTC 与东八区进程时区下跑同一段 JS，
    结果必须完全一致——不一致就说明代码偷用了浏览器本地日期喵。
    """
    script = """
// 时区偏移固定成东八区，模拟服务端口径喵
state.tzOffsetMinutes = 480;
state.clockOffsetMs = 0;
console.log(JSON.stringify({
  dates: trendDates(5),
  cells: heatmapCells(7).slice(0, 3).map((cell) => cell.date),
}));
"""
    outputs = []
    for zone in ("UTC", "Asia/Shanghai"):
        env = dict(**__import__("os").environ)
        env["TZ"] = zone
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            env=env,
        )
        # 喵~防御：没装 node 时跳过喵
        assert completed.returncode == 0, completed.stderr
        outputs.append(json.loads(completed.stdout))
    # 两个时区下的结果必须一模一样喵
    assert outputs[0]["dates"] == outputs[1]["dates"], "浏览器时区影响了日期轴"
    assert outputs[0]["cells"] == outputs[1]["cells"], "浏览器时区影响了热力图起始日"


def test_shift_timeline_date_ignores_browser_timezone() -> None:
    """时间轴「前一天/后一天」必须按服务端时区算，浏览器在 UTC+9 以东不能错一天喵。

    喵~注意：这是真实缺陷。`shiftTimelineDate` 原来用
    `new Date(`${value}T00:00:00`)` + `setDate/getDate`（浏览器本地），
    再交给 `localDateText`（按服务端时区）去读。
    两套时区混用，浏览器在 UTC+9 及以东时**连 days=0 都会错一天**：
    实测 UTC+9/+10/+12 输 2026-11-03、点「前一天」得 2026-11-01（应为 11-02）喵。
    """
    script = """
// 桩：时间轴日期输入框 + 不让它真去发请求喵
globalThis.el = { tlDate: { value: "2026-11-03" } };
globalThis.loadTimeline = function () {};
// 走一次「后退一天」喵
shiftTimelineDate(-1);
console.log(JSON.stringify({
  back: el.tlDate.value,
  stateDate: state.timelineDate,
}));
"""
    outputs = []
    for zone in ("UTC", "Asia/Shanghai", "Asia/Tokyo", "Pacific/Auckland"):
        env = dict(**__import__("os").environ)
        env["TZ"] = zone
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(json.loads(completed.stdout))
    # 每个时区都必须退到 11-02喵
    for zone_output in outputs:
        assert zone_output["back"] == "2026-11-02", f"日期退错：{zone_output}"
        assert zone_output["stateDate"] == "2026-11-02"
    # 四个时区结果必须完全一致，不允许浏览器时区掺进来喵
    assert outputs[0] == outputs[1] == outputs[2] == outputs[3], "浏览器时区影响了时间轴日期"


def test_usage_chart_buckets_align_in_half_hour_timezones() -> None:
    """近 24 小时柱状图的桶要对齐，浏览器在非整小时时区也不能全空喵。

    喵~注意：这是真实缺陷。服务端按 **UTC 整点**切桶
    （`substr(sampled_at,1,13)` + ':00:00Z'），前端原来用
    `moment.getTime()` 精确比毫秒。两者只在浏览器是**整小时偏移**时才碰得上：
    东八区(+8)、UTC、纽约(-5) 都刚好对上，
    但 UTC+5:30（印度）、+8:45（Eucla）这类会整体错开 30/45 分钟
    → 24 根柱子全是 0，界面一片空白而且不报错喵。
    """
    script = """
// 服务端给的桶：24 个 UTC 整点喵
const base = new Date("2026-11-03T05:00:00Z");
const timeline = [];
for (let index = 23; index >= 0; index -= 1) {
  timeline.push({
    bucket_start: new Date(base.getTime() - index * 3600000).toISOString(),
    seconds: 60 * index,
  });
}
// 固定「现在」，避免测试随真实时间漂移喵
const fixedNow = new Date("2026-11-03T05:07:00Z");
const svg = usageChart(timeline, fixedNow);
// 数一下非零柱子（height 不为 0）喵
const heights = [...svg.matchAll(/height="([\\d.]+)"/g)].map((m) => Number(m[1]));
console.log(JSON.stringify({
  bars: heights.length,
  nonZero: heights.filter((value) => value > 0).length,
}));
"""
    outputs = []
    for zone in ("Asia/Shanghai", "UTC", "Asia/Kolkata", "Australia/Eucla", "America/New_York"):
        env = dict(**__import__("os").environ)
        env["TZ"] = zone
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append((zone, json.loads(completed.stdout)))
    # 每个时区都必须画出柱子，不能因为偏移把桶全丢掉喵
    for zone, result in outputs:
        assert result["nonZero"] > 0, f"{zone} 下柱子全空：{result}"
    # 各时区画出的柱子数必须一样，说明桶对齐与浏览器时区无关喵
    counts = {result["nonZero"] for _, result in outputs}
    assert len(counts) == 1, f"不同时区画出的柱子数不一致：{outputs}"


def test_merge_ranking_entries_falls_back_without_breakdown() -> None:
    """服务端没给按设备拆分时，单设备记录整条算给它自己喵。"""
    output = run_in_node(
        harness(
            """
const entries = [
  { app: "QQ", package: "qq.exe", seconds: 90, device_count: 1, devices: ["本机 Windows"] },
  { app: "msedge", package: "msedge.exe", seconds: 10, device_count: 2, devices: ["本机 Windows", "手机"] },
];
const rows = mergeRankingEntries(entries).map((row) => ({ app: row.app, deviceSeconds: [...row.deviceSeconds.entries()] }));
console.log(JSON.stringify(rows));
"""
        )
    )
    rows = json.loads(output)
    # 单设备那条整条算给这台设备喵
    qq = next(row for row in rows if row["app"] == "QQ")
    assert qq["deviceSeconds"] == [["本机 Windows", 90]]
    # 多设备又没有拆分时保持空，前端退回整条单色，不会瞎猜喵
    edge = next(row for row in rows if row["app"] == "msedge")
    assert edge["deviceSeconds"] == []


def test_rank_bar_splits_segments_per_device() -> None:
    """多设备行的条形要按设备切成几段，每段颜色不同、悬停显示设备喵。"""
    output = run_in_node(
        harness(
            """
// 桩：只保留渲染需要的依赖喵
function escapeHtml(value) { return String(value); }
function formatDuration(seconds) { return `${seconds} 秒`; }
const row = {
  app: "QQ",
  seconds: 120,
  devices: ["本机 Windows", "手机"],
  deviceSeconds: new Map([["本机 Windows", 90], ["手机", 30]]),
  packages: ["qq.exe"],
};
const colorOf = () => "rgb(100, 150, 200)";
// 深浅只按这个行自己的设备清单算，不再传本屏设备总数喵
const html = rankBarHtml(row, 120, colorOf);
// 单设备行应该还是原来那种单色填充喵
const single = rankBarHtml(
  { app: "Code.exe", seconds: 60, devices: ["本机 Windows"], deviceSeconds: new Map([["本机 Windows", 60]]) },
  120,
  colorOf,
);
console.log(JSON.stringify({ html, single }));
"""
        )
    )
    payload = json.loads(output)
    html = payload["html"]
    # 两段，各自宽度按 90/30 分喵
    assert html.count("<span ") == 3  # 外层 stack + 两个段喵
    assert "width:75%" in html
    assert "width:25%" in html
    # 悬停要写清设备名与时长喵
    assert "本机 Windows · 90 秒" in html
    assert "手机 · 30 秒" in html
    # 两段颜色必须不同，否则看不出是哪台设备喵
    colors = re.findall(r"background:(rgb\([^)]*\))", html)
    assert len(colors) == 2
    assert colors[0] != colors[1]
    # 单设备行不切段喵
    assert "rank-bar-stack" not in payload["single"]


def test_ranking_row_merges_qq_across_devices() -> None:
    """主人给的例子：QQ 在手机与本机各一条，要合成一行、条形切两段、悬停显示设备喵。"""
    output = run_in_node(
        harness(
            """
// 桩：只保留渲染需要的依赖喵
function escapeHtml(value) { return String(value); }
function appIconHtml() { return ""; }
function appColor() { return "rgb(100, 150, 200)"; }
function formatDuration(seconds) { return `${seconds} 秒`; }
// 服务端会返回的两条 QQ 记录喵
const entries = [
  { app: "QQ", package: "com.tencent.mobileqq", seconds: 30, device_count: 1, devices: ["手机"], device_seconds: [{ device: "手机", seconds: 30 }] },
  { app: "QQ", package: "qq.exe", seconds: 90, device_count: 1, devices: ["本机 Windows"], device_seconds: [{ device: "本机 Windows", seconds: 90 }] },
];
console.log(JSON.stringify({ html: rankingListHtml(entries) }));
"""
        )
    )
    html = json.loads(output)["html"]
    # 只应有一行，不能还是两条喵
    assert html.count('class="rank-row"') == 1
    assert html.count("QQ") >= 1
    # 标题里把两台设备都写出来喵
    assert "手机" in html and "本机 Windows" in html
    # 副标题把两个平台的包名与设备数都列出来喵
    assert "com.tencent.mobileqq · qq.exe · 2 台设备" in html
    # 条形切成两段，悬停各自带设备名喵
    assert "rank-bar-stack" in html
    assert "手机 · 30 秒" in html
    assert "本机 Windows · 90 秒" in html
    # 合计时长是两条相加喵
    assert "120 秒" in html


def test_device_shade_spans_all_devices_when_count_known() -> None:
    """知道本屏设备总数时，两台设备也要落在渐变两端，小色条上才分得清喵。"""
    output = run_in_node(
        harness(
            """
const base = "rgb(35, 93, 255)";
const cases = {
  // 两台设备：序号 0 原色、序号 1 铺到最深处喵
  twoFirst: deviceShade(base, 0, 2),
  twoSecond: deviceShade(base, 1, 2),
  // 三台设备：中间那台应该在倒数第二级，不是最深处喵
  threeSecond: deviceShade(base, 1, 3),
  threeThird: deviceShade(base, 2, 3),
  // 不知道总数时退回档位算法喵
  noTotal: deviceShade(base, 1),
  // 只有一台设备时不换算喵
  single: deviceShade(base, 0, 1),
  ratios: [deviceShadeRatio(1, 2), deviceShadeRatio(1, 3), deviceShadeRatio(2, 3), deviceShadeRatio(1)],
};
console.log(JSON.stringify(cases));
"""
        )
    )
    payload = json.loads(output)
    base = (35, 93, 255)
    # 第一台保持原色喵
    assert parse_rgb(payload["twoFirst"]) == base
    # 两台设备的第二台必须明显比第一台深，否则条形上看不出分界喵
    second = parse_rgb(payload["twoSecond"])
    assert luminance(second) < luminance(base) - 20
    # 三台设备时第二台与第三台也要有区别，且第三台最深喵
    three_second = luminance(parse_rgb(payload["threeSecond"]))
    three_third = luminance(parse_rgb(payload["threeThird"]))
    assert three_third < three_second < luminance(base)
    # 不知道总数时按固定档位算：1/6 档必然比铺满的 1/2 档更接近原色喵
    assert luminance(parse_rgb(payload["noTotal"])) >= three_second
    # 比例：两台设备铺满到 1，三台是 0.5 与 1 喵
    ratios = payload["ratios"]
    assert ratios[0] == 1
    assert abs(ratios[1] - 0.5) < 1e-9 and ratios[2] == 1
    assert 0 < ratios[3] < 1


def test_heatmap_empty_day_differs_from_zero_seconds() -> None:
    """热力图必须把「没有数据」和「0 秒（确实没用）」画成两种东西喵。

    喵~注意：这是真实缺陷。原来的 `heatmapLevel` 用 `if (!seconds || seconds <= 0) return 0`
    把「这一天压根没上报」和「这一天上报了但用了 0 秒」压成同一个色阶 0，
    用户看不出是设备没开机还是真的没用电脑喵。
    """
    output = run_in_node(
        harness(
            """
// 无数据（null）与 0 秒必须给出不同的等级喵
const noData = heatmapLevel(null, 1000);
const zero = heatmapLevel(0, 1000);
// 样式与 HTML 也必须不同喵
const emptyStyle = heatmapCellStyle(noData);
const zeroStyle = heatmapCellStyle(zero);
const cell = { date: "2026-11-01" };
console.log(JSON.stringify({
  noData,
  zero,
  emptyStyle,
  zeroStyle,
  noDataHtml: heatmapCellHtml(cell, null, 1000),
  zeroHtml: heatmapCellHtml(cell, 0, 1000),
  // 有数据的日子不能被这次改动带偏喵
  normal: heatmapLevel(1000, 1000),
}));
"""
        )
    )
    payload = json.loads(output)
    # 无数据不能再落到 0~4 这五个色阶里，必须是单独的标记（这里约定为 null）喵
    assert payload["noData"] is None
    # 0 秒仍然是最浅的实心色阶 0，向后兼容既有断言喵
    assert payload["zero"] == 0
    # 两者的等级必须不相等，这是本用例的核心喵
    assert payload["noData"] != payload["zero"]
    # 样式也必须能区分：无数据空心、0 秒实心最低色阶喵
    assert payload["emptyStyle"] != payload["zeroStyle"]
    assert "transparent" in payload["emptyStyle"]
    assert "transparent" not in payload["zeroStyle"]
    # 渲染出来的格子也必须是两种不同的 HTML喵
    assert payload["noDataHtml"] != payload["zeroHtml"]
    assert "no-data" in payload["noDataHtml"]
    assert "no-data" not in payload["zeroHtml"]
    # 满峰值那天还是最深色阶，原有行为不变喵
    assert payload["normal"] == 4


def test_heatmap_render_marks_missing_day_as_empty() -> None:
    """渲染层不能再用 `|| 0` 把缺的日期压成 0 秒喵。

    直接盯着 renderHeatmap 的源码：它必须用 Map.has 区分「查不到」与「查到 0」，
    并且把秒数交给 heatmapCellHtml 时用 null 表示无数据喵。
    """
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # 喵~注意：定位到 renderHeatmap 函数体，避免误伤别处的 has()喵
    start = app_js.index("function renderHeatmap(")
    body = app_js[start : app_js.index("\n}", start)]
    # 必须用 has() 判断存在性喵
    assert "secondsByDate.has(cell.date)" in body
    # 不能再用「查不到就当 0」的老写法喵
    assert "secondsByDate.get(cell.date) || 0" not in body
    # 无数据必须传 null 给渲染纯函数喵
    assert "heatmapCellHtml(cell, seconds, peak)" in body


def test_request_seq_discards_stale_response() -> None:
    """请求序号：后发的请求领到更大的号，先发的那次回来时必须被判为过期喵。

    喵~注意：这是真实缺陷。`loadTimeline` / `selectDevice` / `loadStats` 原来
    发请求→等回来→直接渲染，没有序号。快速切设备或日期时先发的请求可能后回来，
    用旧数据覆盖新数据，画面就停在上一个设备/日期上喵。
    """
    output = run_in_node(
        harness(
            """
// 清空序号表，从零开始喵
if (!state.requestSeq) state.requestSeq = { timeline: 0, device: 0, stats: 0 };
state.requestSeq.timeline = 0;
state.requestSeq.stats = 0;
// 连发两次，第二次后发喵
const first = nextRequestSeq("timeline");
const second = nextRequestSeq("timeline");
// 第二次发出之后，第一次的响应就该被判过期喵
const firstStale = isStaleResponse("timeline", first);
const secondStale = isStaleResponse("timeline", second);
// 第二次回来之前，第一次还没过期（模拟「还没发新请求」的场景）喵
state.requestSeq.timeline = 1;
const firstBeforeSecond = isStaleResponse("timeline", 1);
console.log(JSON.stringify({
  first,
  second,
  firstStale,
  secondStale,
  firstBeforeSecond,
}));
"""
        )
    )
    payload = json.loads(output)
    # 序号必须严格递增喵
    assert payload["first"] == 1
    assert payload["second"] == 2
    # 先发的那次后回来 → 必须丢弃喵
    assert payload["firstStale"] is True
    # 最新的那次不算过期，要正常渲染喵
    assert payload["secondStale"] is False
    # 没有更新请求时，自己就是最新的喵
    assert payload["firstBeforeSecond"] is False


def test_request_seq_is_per_page() -> None:
    """每个页面的序号各数各的，一个页面刷新不能把另一个页面的响应判成过期喵。

    喵~注意：序号必须在 `loadTimeline` / `loadStats` 里各自领，
    绝不能塞进共用的 `api()` 里做全局计数，否则统计页每拉一次数据，
    时间轴在飞的那次响应就会被无辜丢掉喵。
    """
    output = run_in_node(
        harness(
            """
// 两个页面各自从零开始喵
state.requestSeq = { timeline: 0, device: 0, stats: 0 };
const timelineSeq = nextRequestSeq("timeline");
// 统计页连推三次，时间轴的号不能跟着动喵
const statsSeq1 = nextRequestSeq("stats");
const statsSeq2 = nextRequestSeq("stats");
const statsSeq3 = nextRequestSeq("stats");
console.log(JSON.stringify({
  timelineSeq,
  statsSeq1,
  statsSeq2,
  statsSeq3,
  timelineCounter: state.requestSeq.timeline,
  statsCounter: state.requestSeq.stats,
  // 时间轴手上那张号，在统计页刷新之后依然有效喵
  timelineStillFresh: isStaleResponse("timeline", timelineSeq),
  statsOldStale: isStaleResponse("stats", statsSeq1),
  statsMidStale: isStaleResponse("stats", statsSeq2),
  statsNewestStale: isStaleResponse("stats", statsSeq3),
}));
"""
        )
    )
    payload = json.loads(output)
    # 时间轴只领了一次号，不能因为统计页刷新而增长喵
    assert payload["timelineSeq"] == 1
    assert payload["timelineCounter"] == 1
    # 统计页三次递增互不干扰喵
    assert payload["statsSeq1"] == 1 and payload["statsSeq2"] == 2 and payload["statsSeq3"] == 3
    assert payload["statsCounter"] == 3
    # 时间轴那次响应依然是最新的喵
    assert payload["timelineStillFresh"] is False
    # 统计页自己内部照常判过期：前两次作废、最后一次有效喵
    assert payload["statsOldStale"] is True
    assert payload["statsMidStale"] is True
    assert payload["statsNewestStale"] is False


def test_load_stats_keeps_newest_response_on_out_of_order_arrival() -> None:
    """真正跑一遍 loadStats：旧请求后回来时，画面必须停在新数据上喵。

    喵~注意：光扫源码只能证明「比对写在了该在的位置」，证明不了它真的拦得住。
    这个用例用可控 Promise 让两个请求**乱序返回**，
    先发的（slow）后回来，只要序号机制没接线，它就会把 fast 的数据盖掉喵。
    """
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    script = "\n".join(
        [
            # 最小 DOM / 网络桩：api() 把每次请求挂起，由脚本决定谁先回来喵
            "function escapeHtml(value) { return String(value); }",
            'const state = { requestSeq: { timeline: 0, device: 0, stats: 0 }, statsDays: 90,'
            ' statsDeviceId: "", tzOffsetMinutes: 480, stats: null, statsDeviceList: [] };',
            'const el = { heatmapBody: { innerHTML: "" } };',
            "const pending = [];",
            "function api(path) {",
            "  return new Promise((resolve, reject) => pending.push({ path, resolve, reject }));",
            "}",
            # 渲染只记下这一屏画的是哪份数据喵
            "function renderStats() { globalThis.rendered = state.stats ? state.stats.tag : null; }",
            "function markShotReady() {}",
            "function handleUnauthorized() {}",
            extract_function(source, "nextRequestSeq"),
            extract_function(source, "isStaleResponse"),
            # 喵~注意：extract_function 从 `function` 关键字开始截，
            # loadStats 前面的 async 会丢，这里补回去，否则 await 是语法错误喵
            "async " + extract_function(source, "loadStats"),
            """
(async () => {
  // 先请求 slow，紧接着改成 fast 再请求一次喵
  state.statsDeviceId = "slow";
  const slow = loadStats();
  state.statsDeviceId = "fast";
  const fast = loadStats();
  // 后发的 fast 先回来，正常渲染喵
  pending[1].resolve({ tag: "fast", devices: [] });
  await fast;
  const afterFast = globalThis.rendered;
  // 先发的 slow 后回来，必须被丢掉，不能覆盖已画好的 fast喵
  pending[0].resolve({ tag: "slow", devices: [] });
  await slow;
  console.log(JSON.stringify({
    afterFast,
    rendered: globalThis.rendered,
    stateTag: state.stats.tag,
    calls: pending.length,
  }));
})();
""",
        ]
    )
    payload = json.loads(run_in_node(script))
    # 两次请求都真的发出去了喵
    assert payload["calls"] == 2
    # fast 先回来时正常画上喵
    assert payload["afterFast"] == "fast"
    # slow 后回来不许改动画面，最终必须还是 fast喵
    assert payload["rendered"] == "fast"
    assert payload["stateTag"] == "fast"


def test_request_seq_wired_into_loaders() -> None:
    """三个加载函数都必须真的领号并比对，只写纯函数不接线就等于没修喵。

    喵~注意：这里用「整行精确匹配」而不是子串包含——
    子串匹配会被 `isStaleResponse(...) && false` 这类语义上关掉的写法骗过去，
    也会被 catch 分支里的第二处调用骗过去喵。
    """
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    def body_of(name: str) -> str:
        """按函数名截出函数体，方便逐段断言喵。"""
        start = app_js.index(f"async function {name}(")
        return app_js[start : app_js.index("\n}", start)]

    def assert_guarded_before(func: str, key: str, write_marker: str) -> None:
        """领号 + 独立成行的比对必须都在写 state 之前喵。"""
        body = body_of(func)
        # 必须先领号喵
        assert f'nextRequestSeq("{key}")' in body, f"{func} 没领号"
        # 比对必须是完整独立的一行判断，带 && false 之类的一律不算喵
        guard = re.compile(
            rf'^\s*if \(isStaleResponse\("{key}", seq\)\) return;$', re.MULTILINE
        )
        matches = list(guard.finditer(body))
        # 成功路径与 catch 各要一处喵
        assert len(matches) >= 2, f"{func} 的过期比对不全或写法被改坏"
        # 关键：第一处比对必须在写 state 之前，否则旧数据已经落盘了喵
        assert matches[0].start() < body.index(write_marker), (
            f"{func} 先写了 state 才比对，等于没修"
        )

    # 时间轴 / 设备详情 / 统计各领各的号，且都在写 state 之前拦住旧响应喵
    assert_guarded_before("loadTimeline", "timeline", "state.timeline = body")
    assert_guarded_before("selectDevice", "device", "state.detail = detail")
    assert_guarded_before("loadStats", "stats", "state.stats = body")
    # 喵~注意：共用的 api() 里不许做全局序号，不同页面要互不干扰喵
    api_body = body_of("api")
    assert "requestSeq" not in api_body
    assert "isStaleResponse" not in api_body
