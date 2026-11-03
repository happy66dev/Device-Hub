"""命令名品牌词可配置的行为测试：改 bot.command_brand 等于给整套命令改名喵。

为什么单独开一个文件：命令名原来是写死的「happy」，朋友要用时只能改代码。
现在改成 `{品牌}` 占位符 + 配置注入，涉及 config / commands / router / runner /
simulate 五层，集中放一处方便后人看清边界喵。

喵~注意：这里守的是三件容易改坏的事——
1. `Command.name` 必须保持稳定标识，改名不能动它（出图判断依赖它）；
2. 用户输入必须按「当前配置那张表」匹配，改名后老命令要失效、新命令要生效；
3. 服务端内部按稳定标识取命令（兜底帮助），不能跟着别名一起漂喵。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db
from app.bot import commands, dataset, expr, router
from app.config import BotSection, ConfigError, load_config


# 测试用品牌词，故意用中文以覆盖非 ASCII 的情形喵
BRAND = "小王"


def _config_with_brand(tmp_path: Path, brand: str, group: str = "happy"):
    """造一份把品牌词改成 brand 的配置喵。

    输入：临时目录、品牌词、设备组名。
    输出：load_config 之后的 AppConfig。
    边界：配置文本基于仓库里的真实 config.yaml，改完写进临时目录，不碰原文件喵。
    """
    source = Path(__file__).resolve().parent.parent / "config.yaml"
    text = source.read_text(encoding="utf-8")
    # 喵~注意：happy_group 后面紧跟 command_brand，YAML 缩进要对齐喵
    text = text.replace(
        'happy_group: "happy"',
        f'happy_group: "{group}"\n  command_brand: "{brand}"',
    )
    # 数据库落到临时目录，避免污染真实库喵
    text = text.replace(
        'db_path: "data/device_hub.db"',
        f'db_path: "{(tmp_path / "test.db").as_posix()}"',
    )
    target = tmp_path / "config.yaml"
    target.write_text(text, encoding="utf-8")
    return load_config(target)


def test_brand_defaults_to_happy_and_keeps_old_commands(tmp_path: Path) -> None:
    """不配 command_brand 时必须与老版本逐字一致，老命令照常可用喵。"""
    config = _config_with_brand(tmp_path, "happy")
    # 默认值就是 happy 喵
    assert config.bot.command_brand == "happy"
    # 老命令必须仍然认得喵
    for text in ("/happy设备", "/happy在干嘛", "/看看happy 全部 排行榜"):
        assert router.is_silent_command(text, config) is False, f"{text!r} 被判成未知命令"
    # 默认命令表与常量 COMMANDS 完全一致喵
    assert commands.commands_for_config(config) == commands.COMMANDS


def test_renamed_brand_takes_effect_and_old_name_goes_silent(tmp_path: Path) -> None:
    """改名后新命令要认得、老命令要静默，两者不能同时生效喵。"""
    config = _config_with_brand(tmp_path, BRAND)
    assert config.bot.command_brand == BRAND
    # 新命令认得喵
    for text in (f"/{BRAND}设备", f"/{BRAND}在干嘛", f"/看看{BRAND} 全部 排行榜"):
        assert router.is_silent_command(text, config) is False, f"{text!r} 应该认得"
    # 老命令必须失效，否则改名等于没改喵
    for text in ("/happy设备", "/看看happy 全部 排行榜"):
        assert router.is_silent_command(text, config) is True, f"{text!r} 应该已失效"


def test_command_name_stays_stable_when_brand_changes() -> None:
    """`Command.name` 是稳定标识，绝不能跟着品牌改喵。

    喵~注意：router.build_image 用 `command.name != "看看happy"` 判断要不要出图，
    一旦 name 被替换，改过品牌的人就再也拿不到排行榜图片喵。

    喵~注意：这里必须断言 name 的**具体值**，不能只比较两张表的 name 是否相等。
    只比较相等的话，只要两次都不做替换就一定通过，注入验证会假绿喵。
    """
    renamed_table = commands.build_commands(BRAND)
    # 逐条钉死稳定标识的具体值喵
    actual = [c.name for c in renamed_table]
    assert actual == ["happy帮助", "happy在干嘛", "happy干了什么", "happy设备", "看看happy"]
    # 出图判断依赖的那个名字必须原样存在喵
    assert "看看happy" in actual
    # 别名必须真的变了，否则这条测试对「改名」毫无感知喵
    assert renamed_table[0].aliases == (f"{BRAND}帮助", f"{BRAND}help")
    # 模板正文也必须真的换了品牌喵
    look_command = commands.command_by_key("看看happy", renamed_table)
    assert look_command is not None
    assert BRAND in look_command.template


def test_internal_lookup_by_key_is_brand_independent() -> None:
    """服务端内部按稳定标识取命令，改不改名都取得到喵。"""
    renamed_table = commands.build_commands(BRAND)
    # 按稳定标识查得到喵
    hit = commands.command_by_key("happy帮助", renamed_table)
    assert hit is not None and hit.name == "happy帮助"
    # 但按别名查不到老名字了——这正是需要用 key 的原因喵
    assert commands.command_by_name("happy帮助", renamed_table) is None


def test_renamed_help_text_contains_no_happy(tmp_path: Path) -> None:
    """改名后帮助正文里不能再出现 happy，否则主人照着打会全部失效喵。"""
    config = _config_with_brand(tmp_path, BRAND)
    table = commands.commands_for_config(config)
    help_command = commands.command_by_key("happy帮助", table)
    assert help_command is not None
    # 建一个空库跑渲染喵
    connection = sqlite3.connect(str(tmp_path / "test.db"))
    connection.row_factory = sqlite3.Row
    try:
        context = commands.CommandContext(
            connection=connection,
            config=config,
            name=help_command.name,
            args=(),
            now=db.utc_now(),
            raw_text="",
        )
        scope = help_command.handler(context)
        env = dataset.TemplateEnv(commands.fragment_nodes(), {})
        rendered = expr.render_text(help_command.pick_template(scope), (scope,), env)
    finally:
        connection.close()
    # 帮助里出现的必须是新品牌喵
    assert BRAND in rendered
    assert "happy" not in rendered, f"帮助正文里还有 happy：{rendered[:200]}"


@pytest.mark.parametrize(
    "brand",
    [
        "小王 白",  # 空格会把命令名切成两截喵
        "小王/白",  # 斜杠会与命令前缀混淆喵
        "小王\u200b白",  # 零宽字符肉眼看不见喵
        "一二三四五六七八九十一二三四五六七",  # 超过 16 字符喵
    ],
)
def test_rejects_brand_that_breaks_command_parsing(brand: str) -> None:
    """会破坏命令名的品牌词必须在加载配置时就报错，而不是运行时静默失效喵。"""
    with pytest.raises(ConfigError):
        # 直接测校验函数，避免每个用例都写一遍 YAML 喵
        from app.config import _as_command_brand

        _as_command_brand({"command_brand": brand})


def test_blank_brand_falls_back_to_default() -> None:
    """留空或纯空白要退回默认 happy，不能变成空命令名喵。"""
    from app.config import _as_command_brand

    assert _as_command_brand({"command_brand": ""}) == "happy"
    assert _as_command_brand({"command_brand": "   "}) == "happy"
    # 缺字段同样回默认值喵
    assert _as_command_brand({}) == "happy"


def test_bot_section_without_brand_attribute_is_tolerated() -> None:
    """老配置对象没有 command_brand 字段时，取命令表不能炸喵。"""
    # 模拟一个只有 happy_group 的老 BotSection 喵
    old_section = type("OldBot", (), {"happy_group": "happy"})()
    old_config = type("OldConfig", (), {"bot": old_section})()
    # 要退回默认品牌，而不是抛 AttributeError 喵
    table = commands.commands_for_config(old_config)
    assert [c.name for c in table] == [c.name for c in commands.COMMANDS]


def test_group_missing_error_uses_brand_as_subject(tmp_path: Path) -> None:
    """设备组不存在时报错里的主语必须是当前品牌名喵。

    喵~注意：这段提示是 happy.py 里 raise 的 Python 字符串，不走 `{品牌}`
    模板替换，所以最容易漏改。改过品牌的主人若看到「happy 不知道该看谁」，
    会以为自己配错了地方喵。
    """
    from app.bot import happy

    config = _config_with_brand(tmp_path, BRAND)
    # 组不存在：库里一个设备组都没有喵
    with pytest.raises(happy.HappyError) as error:
        happy.load_happy_devices(sqlite3.connect(":memory:"), config, db.utc_now())
    message = str(error.value)
    # 主语要是新品牌喵
    assert f"{BRAND} 不知道该看谁" in message, f"提示里没用新品牌：{message}"
    # 不能再出现把人说懵的老主语喵
    assert "happy 不知道该看谁" not in message, f"提示里还有 happy：{message}"


def _seed_device(tmp_path: Path, config, device_id: str = "win-test-0001") -> None:
    """往临时库里塞一个设备组和一条上报，供出图用例使用喵。

    输入：临时目录、配置、设备 ID。
    输出：无；数据写进配置指向的临时库。
    边界：组名固定用配置里的 happy_group，与真实用法一致喵。
    """
    from datetime import datetime, timezone

    from app import ingest, people
    from app.bot import happy
    from app.models import ReportPayload

    db_path = config.server.db_path
    group_name = happy.resolve_group_name(config)
    people.save_people(db_path, [people.PersonGroup(name=group_name, devices=(device_id,))])
    # 造一条上报，让设备有名字与硬件信息喵
    payload = ReportPayload(
        device_id=device_id,
        platform="windows",
        reported_at=datetime.now(timezone.utc),
        display_name="测试台式机",
        hardware={"os_version": "Windows 10", "cpu": "Ryzen 7"},
        current_app={"name": "Code.exe", "package": "Code.exe"},
        usage_delta=[{"app": "Code.exe", "seconds": 60}],
        client_version="0.1.0",
    )
    connection = db.connect(db_path)
    try:
        ingest.save_report(connection, payload, datetime.now(timezone.utc))
    finally:
        connection.close()


def _capture_image_params(config, text: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """跑一遍 build_image，抓出传给截图函数的参数喵。

    输入：配置、命令文本、monkeypatch。
    输出：截图参数；没出图时返回空字典。
    边界：截图与可用性检查都被打桩，不会真的去开浏览器喵。
    """
    from app.bot import snapshot

    captured: dict[str, object] = {}

    def fake_capture(base_url: str, token: str, tab: str, params: dict[str, str], **kwargs: object) -> bytes:
        """假的截图函数，只记录参数喵。"""
        captured["tab"] = tab
        captured["params"] = dict(params)
        return b"\x89PNG-fake"

    # 替换截图并放行可用性检查喵
    monkeypatch.setattr(snapshot, "capture_dashboard", fake_capture)
    monkeypatch.setattr(snapshot, "_node_available", lambda: True)

    connection = db.connect(config.server.db_path)
    try:
        image = router.build_image(connection, config, text)
    finally:
        connection.close()
    # 没出图就把空的参数表交回去，让断言能区分「没出图」和「参数不对」喵
    if image is None:
        return {}
    params = captured.get("params")
    assert isinstance(params, dict)
    return params


def test_renamed_brand_still_produces_rank_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改了品牌名之后，排行榜图片必须照样出得来喵。

    喵~注意：这条守的是最隐蔽的坑——build_image 靠 `command.name != "看看happy"`
    判断要不要出图。若 name 跟着品牌一起替换，这里会永远返回 None，
    命令能响应、文字也正常，只有图片悄悄消失，看日志还以为截图失败喵。
    """
    from dataclasses import replace

    config = _config_with_brand(tmp_path, BRAND)
    # 图片默认是关的，这里显式打开喵
    config = replace(config, render=replace(config.render, image_enabled=True))
    db.init_db(config.server.db_path)
    _seed_device(tmp_path, config)
    # 用新品牌名发命令，必须出图喵
    params = _capture_image_params(config, f"看看{BRAND} 全部 排行榜 6小时", monkeypatch)
    assert params, "改了品牌名之后排行榜图片没出图"
    assert params["hours"] == "6"
    # 设备范围也要正确传下去喵
    assert params["devices"] == "win-test-0001"


def test_renamed_brand_still_produces_timeline_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改了品牌名之后，时间轴图片也必须照样出得来喵。"""
    from dataclasses import replace

    config = _config_with_brand(tmp_path, BRAND)
    config = replace(config, render=replace(config.render, image_enabled=True))
    db.init_db(config.server.db_path)
    _seed_device(tmp_path, config)
    params = _capture_image_params(config, f"看看{BRAND} 全部 时间轴", monkeypatch)
    assert params, "改了品牌名之后时间轴图片没出图"
    # 时间轴走的是 from/to 参数，不是 hours 喵
    assert "from" in params and "to" in params


def test_old_brand_no_longer_produces_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改名之后老命令名要彻底失效，连图也不能出喵。

    喵~注意：这条防的是「新旧都生效」——那等于改名没改干净，
    群友还能用老命令拿到数据喵。
    """
    from dataclasses import replace

    config = _config_with_brand(tmp_path, BRAND)
    config = replace(config, render=replace(config.render, image_enabled=True))
    db.init_db(config.server.db_path)
    _seed_device(tmp_path, config)
    # 老命令必须静默且不出图喵
    assert _capture_image_params(config, "看看happy 全部 排行榜 6小时", monkeypatch) == {}
    assert router.is_silent_command("看看happy 全部 排行榜 6小时", config) is True


def test_renamed_non_image_command_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改名后纯文字命令仍然不出图，不能因为 name 乱了而误出喵。"""
    from dataclasses import replace

    config = _config_with_brand(tmp_path, BRAND)
    config = replace(config, render=replace(config.render, image_enabled=True))
    db.init_db(config.server.db_path)
    _seed_device(tmp_path, config)
    # 这两条只该回文字喵
    assert _capture_image_params(config, f"{BRAND}设备", monkeypatch) == {}
    assert _capture_image_params(config, f"{BRAND}在干嘛", monkeypatch) == {}
