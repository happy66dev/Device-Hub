"""使用时长累加器的单元测试：累加、取空、归还、截断喵。"""

from __future__ import annotations

from agent.usage import MAX_APPS_PER_REPORT, UsageTracker, make_key, split_key


def test_add_and_drain() -> None:
    """累加的秒数应能在取空时一次性拿到喵。"""
    # 创建累加器喵
    tracker = UsageTracker()
    # 同一应用累加两次喵
    tracker.add_seconds("Code.exe", 5)
    tracker.add_seconds("Code.exe", 5)
    # 另一个应用累加一次喵
    tracker.add_seconds("Edge.exe", 10)
    # 取空喵
    drained = tracker.drain()
    # 秒数应被正确累加喵
    assert drained[make_key("Code.exe", "")] == 10
    assert drained[make_key("Edge.exe", "")] == 10
    # 取空后内部应为空喵
    assert tracker.pending_total_seconds() == 0


def test_drain_returns_copy() -> None:
    """取空返回的字典被修改时不应影响内部状态喵。"""
    # 累加一次喵
    tracker = UsageTracker()
    tracker.add_seconds("Code.exe", 5)
    # 取空并篡改返回值喵
    drained = tracker.drain()
    drained[make_key("Code.exe", "")] = 999
    # 内部应为空而不是 999 喵
    assert tracker.pending_total_seconds() == 0


def test_add_ignores_invalid_input() -> None:
    """空应用名与非正数秒数应被忽略喵。"""
    # 创建累加器喵
    tracker = UsageTracker()
    # 各种非法输入喵
    tracker.add_seconds("", 10)
    tracker.add_seconds("   ", 10)
    tracker.add_seconds("Code.exe", 0)
    tracker.add_seconds("Code.exe", -5)
    # 内部应仍为空喵
    assert tracker.pending_total_seconds() == 0


def test_restore_merges_back() -> None:
    """上报失败归还的数据应与后续数据合并喵。"""
    # 创建累加器并累加喵
    tracker = UsageTracker()
    tracker.add_seconds("Code.exe", 10)
    # 取空后归还喵
    pending = tracker.drain()
    tracker.restore(pending)
    # 再累加一次喵
    tracker.add_seconds("Code.exe", 5)
    # 再取空应得到合并后的 15 秒喵
    assert tracker.drain()[make_key("Code.exe", "")] == 15


def test_restore_empty_is_safe() -> None:
    """归还空字典不应报错喵。"""
    # 创建累加器喵
    tracker = UsageTracker()
    # 归还空数据喵
    tracker.restore({})
    # 内部仍为空喵
    assert tracker.pending_total_seconds() == 0


def test_seconds_are_capped_per_app() -> None:
    """单应用累计秒数应被截断到一天以内喵。"""
    # 创建累加器并累加两天喵
    tracker = UsageTracker()
    tracker.add_seconds("Code.exe", 90000)
    tracker.add_seconds("Code.exe", 90000)
    # 取空后应不超过 86400 秒喵
    assert tracker.drain()[make_key("Code.exe", "")] == 86400


def test_to_delta_list_sorted_and_limited() -> None:
    """转数组时应按时长倒序，并限制条数喵。"""
    # 创建累加器喵
    tracker = UsageTracker()
    # 塞入超过上限的应用数喵
    for index in range(MAX_APPS_PER_REPORT + 20):
        tracker.add_seconds(f"app{index}.exe", index + 1)
    # 转数组喵
    delta_list = tracker.to_delta_list()
    # 条数应被限制喵
    assert len(delta_list) == MAX_APPS_PER_REPORT
    # 第一条应是秒数最多的那个喵
    assert delta_list[0]["seconds"] == MAX_APPS_PER_REPORT + 20
    # 每条都应包含 app、package 与 seconds 三个键喵
    assert set(delta_list[0].keys()) == {"app", "package", "seconds"}


def test_snapshot_keeps_pending_data() -> None:
    """快照应能拿到数据，但不影响内部累计喵。"""
    # 创建累加器并累加喵
    tracker = UsageTracker()
    tracker.add_seconds("Code.exe", 30)
    # 取快照喵
    snapshot = tracker.snapshot()
    # 快照内容应正确喵
    assert snapshot == {make_key("Code.exe", ""): 30}
    # 内部累计不应被清空喵
    assert tracker.pending_total_seconds() == 30
    # 篡改快照不应影响内部状态喵
    snapshot[make_key("Code.exe", "")] = 999
    assert tracker.snapshot()[make_key("Code.exe", "")] == 30


def test_package_is_tracked_separately() -> None:
    """同名应用不同包名要分开累计，包名也要随上报带出去喵。"""
    # 两个不同 exe 但显示名相同喵
    tracker = UsageTracker()
    tracker.add_seconds("Chrome", 10, "chrome.exe")
    tracker.add_seconds("Chrome", 20, "msedge.exe")
    # 拆出来应当有两条喵
    deltas = tracker.to_delta_list()
    assert len(deltas) == 2
    packages = {item["package"] for item in deltas}
    assert packages == {"chrome.exe", "msedge.exe"}


def test_package_is_normalized_to_lowercase() -> None:
    """包名大小写不同应合并成一条喵。"""
    # 大小写不同的同一个 exe 喵
    tracker = UsageTracker()
    tracker.add_seconds("Chrome", 10, "Chrome.exe")
    tracker.add_seconds("Chrome", 20, "chrome.exe")
    # 应当合并成 30 秒喵
    deltas = tracker.to_delta_list()
    assert len(deltas) == 1
    assert deltas[0]["seconds"] == 30
    assert deltas[0]["package"] == "chrome.exe"


def test_split_key_accepts_legacy_format() -> None:
    """旧版本只有应用名的键也要能拆开喵。"""
    # 旧格式没有分隔符喵
    assert split_key("Code.exe") == ("Code.exe", "")
    # 新格式喵
    assert split_key(make_key("Code.exe", "code.exe")) == ("Code.exe", "code.exe")