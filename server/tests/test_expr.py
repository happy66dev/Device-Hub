"""模板引擎的单元测试：解析、求值、条件、片段、查询、格式化器喵。

这些用例全部是纯函数测试，不碰数据库也不碰网络，
所以能在毫秒级覆盖到「占位符写错会怎样」这类边界喵。
"""

from __future__ import annotations

import pytest

from app.bot import expr


class FakeEnv:
    """测试用的渲染环境：片段表与查询结果都由用例直接给定喵。"""

    def __init__(
        self,
        fragments: dict[str, tuple[object, ...]] | None = None,
        query_result: object = None,
        query_error: Exception | None = None,
    ) -> None:
        # 片段名到节点树的映射喵
        self._fragments = fragments or {}
        # 查询要返回的结果喵
        self._query_result = query_result if query_result is not None else []
        # 查询要抛的异常喵
        self._query_error = query_error
        # 记录调用过的查询，方便断言参数喵
        self.calls: list[tuple[str, dict[str, str]]] = []

    def fragment(self, name: str) -> tuple[object, ...] | None:
        """取片段喵。"""
        return self._fragments.get(name)

    def query(self, dataset: str, options: dict[str, str], scopes: object, depth: int) -> object:
        """记录并返回预设的查询结果喵。"""
        # 喵~防御：用例要求报错时照做喵
        if self._query_error is not None:
            raise self._query_error
        self.calls.append((dataset, dict(options)))
        return self._query_result


def _fragment_env(**fragments: str) -> FakeEnv:
    """把片段文本解析成节点树后塞进环境喵。"""
    # 逐条解析喵
    parsed = {name: expr.parse(text).nodes for name, text in fragments.items()}
    return FakeEnv(fragments=parsed)


def test_parse_plain_text_returns_single_node() -> None:
    """纯文本应解析成单个文本节点喵。"""
    # 解析普通文本喵
    template = expr.parse("你好")
    # 只有一个文本节点喵
    assert template.nodes == ("你好",)


def test_render_variable_from_scope() -> None:
    """变量应从作用域取值喵。"""
    # 渲染带变量的模板喵
    text = expr.render_text("名称：{name}", ({"name": "本机"},), FakeEnv())
    # 应替换成实际值喵
    assert text == "名称：本机"


def test_render_chinese_alias_maps_to_english_field() -> None:
    """中文占位符应通过别名表映射到英文字段喵。"""
    # 用中文名取值喵
    text = expr.render_text("{名称}/{平台}", ({"name": "手机", "platform": "Android"},), FakeEnv())
    # 别名应生效喵
    assert text == "手机/Android"


def test_render_missing_variable_becomes_empty() -> None:
    """取不到的变量应渲染成空串而不是报错喵。"""
    # 引用一个不存在的变量喵
    text = expr.render_text("A{not_exist}B", ({"name": "x"},), FakeEnv())
    # 应只剩前后文本喵
    assert text == "AB"


def test_render_nested_mapping_path() -> None:
    """点号路径应能取到嵌套字典喵。"""
    # 嵌套作用域喵
    text = expr.render_text("{device.name}", ({"device": {"name": "台式机"}},), FakeEnv())
    # 应取出嵌套值喵
    assert text == "台式机"


def test_render_index_path() -> None:
    """下标路径应能取到列表元素喵。"""
    # 取列表第一个元素喵
    text = expr.render_text("{apps[0].app}", ({"apps": [{"app": "Code.exe"}]},), FakeEnv())
    # 应取出第一个应用喵
    assert text == "Code.exe"


def test_render_escaped_braces() -> None:
    """双花括号应输出成字面量花括号喵。"""
    # 使用转义写法喵
    text = expr.render_text("{{设备}}", ({},), FakeEnv())
    # 应还原成单层花括号喵
    assert text == "{设备}"


def test_render_bool_uses_chinese() -> None:
    """布尔值应渲染成「是/否」喵。"""
    # 真值与假值喵
    text = expr.render_text("{a}/{b}", ({"a": True, "b": False},), FakeEnv())
    # 应输出中文喵
    assert text == "是/否"


def test_if_block_takes_true_branch() -> None:
    """条件为真时应渲染主体喵。"""
    # 有电量的分支喵
    text = expr.render_text("{若 有电量}有电{否则}无电{/若}", ({"has_battery": True},), FakeEnv())
    # 应走真分支喵
    assert text == "有电"


def test_if_block_takes_false_branch() -> None:
    """条件为假时应渲染否则分支喵。"""
    # 无电量的分支喵
    text = expr.render_text("{若 有电量}有电{否则}无电{/若}", ({"has_battery": False},), FakeEnv())
    # 应走假分支喵
    assert text == "无电"


def test_if_block_without_else_renders_empty() -> None:
    """没有否则分支且条件为假时输出空串喵。"""
    # 只有主体喵
    text = expr.render_text("[{若 暂停说明}暂停中{/若}]", ({"paused_text": ""},), FakeEnv())
    # 应剩下空方括号喵
    assert text == "[]"


def test_if_block_nested() -> None:
    """条件块应支持嵌套喵。"""
    # 外层真、内层真喵
    scope = {"has_entries": True, "has_next": True}
    text = expr.render_text("{若 有排行}{若 有下一页}还有{/若}{/若}", (scope,), FakeEnv())
    # 两层都成立喵
    assert text == "还有"


def test_if_block_missing_terminator_raises() -> None:
    """缺少 {/若} 应报语法错误喵。"""
    # 故意漏掉结束标记喵
    with pytest.raises(expr.TemplateError):
        expr.parse("{若 有电量}有电")


def test_if_block_stray_terminator_raises() -> None:
    """多余的 {/若} 应报语法错误喵。"""
    # 没有对应的 {若}喵
    with pytest.raises(expr.TemplateError):
        expr.parse("文本{/若}")


def test_empty_placeholder_raises() -> None:
    """空占位符应报语法错误喵。"""
    # 空的 {} 喵
    with pytest.raises(expr.TemplateError):
        expr.parse("{}")


def test_unclosed_placeholder_raises() -> None:
    """缺少右花括号应报语法错误喵。"""
    # 只写了左边喵
    with pytest.raises(expr.TemplateError):
        expr.parse("{name")


def test_fragment_reference_renders_shared_scope() -> None:
    """片段应共享外层作用域喵。"""
    # 准备一个引用 {name} 的片段喵
    env = _fragment_env(行="设备：{name}")
    # 渲染片段喵
    text = expr.render_text("{>行}", ({"name": "手机"},), env)
    # 片段能取到外层变量喵
    assert text == "设备：手机"


def test_fragment_reference_missing_raises() -> None:
    """引用不存在的片段应报错喵。"""
    # 引用一个没定义的片段喵
    with pytest.raises(expr.TemplateError):
        expr.render_text("{>不存在}", ({},), FakeEnv())


def test_query_renders_one_line_per_row() -> None:
    """查询应按行片段逐行渲染喵。"""
    # 准备行片段与查询结果喵
    env = _fragment_env(行="{rank}. {name}")
    env._query_result = [{"rank": 1, "name": "甲"}, {"rank": 2, "name": "乙"}]
    # 渲染查询喵
    text = expr.render_text("{查询 设备 行=行}", ({},), env)
    # 两行用换行连接喵
    assert text == "1. 甲\n2. 乙"


def test_query_empty_uses_empty_text() -> None:
    """查询为空时应使用 空= 文案喵。"""
    # 空结果喵
    env = _fragment_env(行="{name}")
    env._query_result = []
    # 渲染喵
    text = expr.render_text("{查询 设备 行=行 空=没有设备}", ({},), env)
    # 应输出空文案喵
    assert text == "没有设备"


def test_query_without_row_fragment_raises() -> None:
    """查询有结果却没写行片段时应报错喵。"""
    # 有结果但没指定行片段喵
    env = FakeEnv(query_result=[{"name": "甲"}])
    # 应报语法错误喵
    with pytest.raises(expr.TemplateError):
        expr.render_text("{查询 设备}", ({},), env)


def test_query_options_parsed_in_order() -> None:
    """查询选项应原样传给数据层喵。"""
    # 带多个选项的查询喵
    env = _fragment_env(行="{name}")
    env._query_result = [{"name": "甲"}]
    # 渲染喵
    expr.render_text("{查询 设备 有使用=1分钟 前=5 行=行}", ({},), env)
    # 选项应完整传递喵
    assert env.calls == [("设备", {"有使用": "1分钟", "前": "5", "行": "行"})]


def test_query_option_value_with_placeholder() -> None:
    """查询选项的值里嵌占位符时，应先渲染再传下去喵。"""
    # 选项值里带变量喵
    env = _fragment_env(行="{name}")
    env._query_result = [{"name": "甲"}]
    # 窗口来自作用域喵
    expr.render_text("{查询 设备 最近={window} 行=行}", ({"window": "5分钟"},), env)
    # 传下去的值应是渲染后的结果喵
    assert env.calls[0][1]["最近"] == "5分钟"


def test_query_aggregate_scalar_is_formatted() -> None:
    """聚合结果是标量时应直接输出喵。"""
    # 查询返回数字喵
    env = FakeEnv(query_result=3)
    # 渲染喵
    text = expr.render_text("{查询 设备 计数}", ({},), env)
    # 应输出数字喵
    assert text == "3"


def test_query_error_propagates() -> None:
    """数据层异常应向上抛出，交给命令层兜底喵。"""
    # 数据层报错喵
    env = FakeEnv(query_error=expr.QueryError("数据集不认识"))
    # 应把异常抛出来喵
    with pytest.raises(expr.QueryError):
        expr.render_text("{查询 未知 行=行}", ({},), env)


def test_formatter_duration() -> None:
    """时长格式化器应输出人话喵。"""
    # 秒、分、小时三种情况喵
    assert expr.render_text("{v|时长}", ({"v": 45},), FakeEnv()) == "45 秒"
    assert expr.render_text("{v|时长}", ({"v": 200},), FakeEnv()) == "3 分 20 秒"
    assert expr.render_text("{v|时长}", ({"v": 3900},), FakeEnv()) == "1 小时 5 分"


def test_formatter_percent_default_one_decimal() -> None:
    """百分比默认保留一位小数喵。"""
    # 一位小数喵
    assert expr.render_text("{v|百分比}", ({"v": 66.666},), FakeEnv()) == "66.7%"


def test_formatter_percent_with_argument() -> None:
    """百分比支持指定位数喵。"""
    # 零位小数喵
    assert expr.render_text("{v|百分比(0)}", ({"v": 66.666},), FakeEnv()) == "67%"


def test_formatter_truncate_adds_ellipsis() -> None:
    """截断格式化器应补省略号喵。"""
    # 截到 5 个字符喵
    text = expr.render_text("{v|截断(5)}", ({"v": "abcdefgh"},), FakeEnv())
    # 应是前四个字符加省略号喵
    assert text == "abcd…"


def test_formatter_truncate_keeps_short_text() -> None:
    """短文本不应被截断喵。"""
    # 三个字符，允许五个喵
    assert expr.render_text("{v|截断(5)}", ({"v": "abc"},), FakeEnv()) == "abc"


def test_formatter_number_drops_trailing_zero() -> None:
    """数字格式化器不应输出 76.0 这种写法喵。"""
    # 整数形式的浮点喵
    assert expr.render_text("{v|数字}", ({"v": 76.0},), FakeEnv()) == "76"


def test_formatter_list_joins_with_dunhao() -> None:
    """列表格式化器应用顿号连接喵。"""
    # 三个元素喵
    text = expr.render_text("{v|列表}", ({"v": ["甲", "乙", "丙"]},), FakeEnv())
    # 顿号连接喵
    assert text == "甲、乙、丙"


def test_formatter_relative_on_datetime() -> None:
    """相对时间格式化器应输出「多久之前」喵。"""
    from datetime import datetime, timedelta, timezone

    # 五分钟前喵
    moment = datetime.now(timezone.utc) - timedelta(minutes=5)
    # 渲染喵
    text = expr.render_text("{v|相对}", ({"v": moment},), FakeEnv())
    # 应是分钟级文案喵
    assert "分钟前" in text


def test_formatter_unknown_is_passthrough() -> None:
    """未知格式化器应按原值输出，不能吞掉内容喵。"""
    # 写一个不存在的格式化器喵
    assert expr.render_text("{v|乱写}", ({"v": "原值"},), FakeEnv()) == "原值"


def test_formatter_on_empty_value_is_empty() -> None:
    """空值不参与格式化，避免出现「0 秒」这种假数据喵。"""
    # 值为 None 喵
    assert expr.render_text("[{v|时长}]", ({"v": None},), FakeEnv()) == "[]"


def test_parse_duration_text_units() -> None:
    """时长文本应支持秒/分/小时/天混合喵。"""
    # 逐个单位喵
    assert expr.parse_duration_text("30秒") == 30
    assert expr.parse_duration_text("1分钟") == 60
    assert expr.parse_duration_text("2小时") == 7200
    assert expr.parse_duration_text("1天") == 86400
    # 混合单位相加喵
    assert expr.parse_duration_text("1小时30分") == 5400


def test_parse_duration_text_invalid_returns_none() -> None:
    """解析不出单位时应返回 None 喵。"""
    # 没有数字或单位喵
    assert expr.parse_duration_text("很久") is None
    assert expr.parse_duration_text("") is None


def test_depth_limit_prevents_infinite_recursion() -> None:
    """片段互相引用时应被深度限制拦住喵。"""
    # 两个互相引用的片段喵
    env = _fragment_env(甲="{>乙}", 乙="{>甲}")
    # 应报深度超限喵
    with pytest.raises(expr.TemplateError):
        expr.render_text("{>甲}", ({},), env)


def test_parse_non_string_raises() -> None:
    """模板不是字符串时应报错喵。"""
    # 传一个数字喵
    with pytest.raises(expr.TemplateError):
        expr.parse(123)  # type: ignore[arg-type]


def test_render_keeps_newlines() -> None:
    """换行应原样保留，QQ 里靠它排版喵。"""
    # 两行文本喵
    text = expr.render_text("第一行\n第二行", ({},), FakeEnv())
    # 换行不丢喵
    assert text == "第一行\n第二行"
