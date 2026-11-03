"""设置页配置读写的单元测试：文本替换、类型转换、校验回滚喵。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml

import app.settings as settings_module
from app.settings import (
    SECRET_PLACEHOLDER,
    SettingsError,
    _CONFIG_WRITE_LOCK,
    apply_settings,
    read_settings,
    update_config_text,
)

from app.config import load_config

# 一份带注释的样例配置，用来验证「改值不丢注释」喵
SAMPLE_CONFIG = """\
# 顶部注释不能丢喵
server:
  host: 127.0.0.1
  port: 8080
  db_path: "data/device_hub.db"
  log_level: warning

ingest:
  # 上报口令
  token: "test-token-12345678"
  max_payload_bytes: 4096

napcat:
  enabled: false
  ws_url: "ws://127.0.0.1:7999"
  token: ""
  reconnect_seconds: 10
  self_qq: ""

qqbot:
  enabled: false
  app_id: ""
  app_secret: ""
  api_base: "https://bots.qq.com"
  intents: 33554432

acl:
  whitelist_groups: []
  blacklist_users: [222222]
"""


def _write_sample(tmp_path: Path) -> Path:
    """把样例配置写到临时目录并返回路径喵。"""
    # 写入样例文本喵
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return path


def test_update_config_text_keeps_comments() -> None:
    """改值只动目标行，注释和别的段都要原样保留喵。"""
    # 改一个布尔与一个列表喵
    updated = update_config_text(
        SAMPLE_CONFIG,
        {"napcat.enabled": True, "acl.whitelist_groups": [111111, 333333]},
    )
    # 注释还在喵
    assert "# 顶部注释不能丢喵" in updated
    assert "# 上报口令" in updated
    # 目标行被替换喵
    assert "  enabled: true" in updated
    assert "  whitelist_groups: [111111, 333333]" in updated
    # 其它段没被动过喵
    assert "  port: 8080" in updated
    assert '  ws_url: "ws://127.0.0.1:7999"' in updated


def test_update_config_text_inserts_missing_key() -> None:
    """段里没有这个键时插到段尾，不能插到别的段里喵。"""
    # 删掉 self_qq 那行后重新写入喵
    text = SAMPLE_CONFIG.replace('  self_qq: ""\n', "")
    updated = update_config_text(text, {"napcat.self_qq": "10001"})
    # 新键落在 napcat 段内喵
    assert '  self_qq: "10001"' in updated
    lines = updated.split("\n")
    napcat_index = lines.index("napcat:")
    qqbot_index = lines.index("qqbot:")
    self_index = next(index for index, line in enumerate(lines) if line.startswith("  self_qq:"))
    assert napcat_index < self_index < qqbot_index


def test_update_config_text_appends_missing_section() -> None:
    """整段都不存在时追加到文件末尾喵。"""
    # 去掉 qqbot 段喵
    start = SAMPLE_CONFIG.index("qqbot:")
    end = SAMPLE_CONFIG.index("acl:")
    text = SAMPLE_CONFIG[:start] + SAMPLE_CONFIG[end:]
    updated = update_config_text(text, {"qqbot.enabled": True})
    # 段被追加出来了喵
    assert "qqbot:" in updated
    assert "  enabled: true" in updated


def test_update_config_text_adds_bot_section() -> None:
    """老配置里没有 bot 段时，改 happy_group 应自动建出这一段喵。"""
    # 样例配置里还没有独立的 bot 段喵
    # 喵~注意：不能用 "bot:" in 判断，qqbot: 里也含这个子串，要按整行比喵
    assert "\nbot:" not in SAMPLE_CONFIG
    # 写一个新组名喵
    updated = update_config_text(SAMPLE_CONFIG, {"bot.happy_group": "我的组"})
    # 段与键都出现了喵
    assert "\nbot:" in updated
    assert '  happy_group: "我的组"' in updated
    # 喵~注意：追加的段必须能被配置加载器认出来，否则等于白写喵
    assert "  happy_group:" in updated


def test_update_config_text_changes_existing_happy_group() -> None:
    """已有 bot 段时就地改值，注释要保留喵。"""
    # 手工拼一份带注释的 bot 段喵
    text = SAMPLE_CONFIG + '\n# happy 命令用喵\nbot:\n  # 组名喵\n  happy_group: "happy"\n'
    # 改成新名字喵
    updated = update_config_text(text, {"bot.happy_group": "新组"})
    # 新值生效且注释还在喵
    assert '  happy_group: "新组"' in updated
    assert "# 组名喵" in updated
    assert "# happy 命令用喵" in updated


def test_update_config_text_rejects_unknown_key() -> None:
    """白名单之外的键必须拒绝，防止被当成任意写入喵。"""
    # 不认识的配置项喵
    with pytest.raises(SettingsError):
        update_config_text(SAMPLE_CONFIG, {"server.db_path": "/etc/passwd"})


def test_update_config_text_coerces_lists() -> None:
    """列表可以从换行或逗号分隔的字符串解析喵。"""
    # 字符串形式的列表喵
    updated = update_config_text(SAMPLE_CONFIG, {"acl.blacklist_users": "1\n2，3,4"})
    assert "  blacklist_users: [1, 2, 3, 4]" in updated


def test_update_config_text_rejects_bad_int() -> None:
    """整数项写了非数字要报错喵。"""
    # 非数字喵
    with pytest.raises(SettingsError):
        update_config_text(SAMPLE_CONFIG, {"napcat.reconnect_seconds": "十秒"})


def test_apply_settings_writes_and_reports(tmp_path: Path) -> None:
    """合法改动应落盘并返回改动项喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 改两个值喵
    changed = apply_settings(path, {"napcat.ws_url": "ws://127.0.0.1:7000", "acl.whitelist_groups": [555555]})
    assert set(changed) == {"napcat.ws_url", "acl.whitelist_groups"}
    # 重新加载配置确认生效喵
    config = load_config(path)
    assert config.napcat.ws_url == "ws://127.0.0.1:7000"
    assert config.acl.whitelist_groups == (555555,)
    # 注释仍在喵
    assert "# 顶部注释不能丢喵" in path.read_text(encoding="utf-8")


def test_apply_settings_rolls_back_on_invalid(tmp_path: Path) -> None:
    """校验失败时原文件必须保持不变喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 打开官方通道但不填凭据，加载必然失败喵
    with pytest.raises(SettingsError):
        apply_settings(path, {"qqbot.enabled": True})
    # 文件内容原封不动喵
    assert path.read_text(encoding="utf-8") == SAMPLE_CONFIG


def test_apply_settings_skips_secret_placeholder(tmp_path: Path) -> None:
    """密钥占位符表示没改，不该写进配置喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 只提交占位符喵
    changed = apply_settings(path, {"qqbot.app_secret": SECRET_PLACEHOLDER})
    assert changed == []
    # 文件没变喵
    assert path.read_text(encoding="utf-8") == SAMPLE_CONFIG


def test_read_settings_masks_secrets(tmp_path: Path) -> None:
    """读取配置时密钥只能给占位符喵。"""
    # 准备样例配置并填一个密钥喵
    path = _write_sample(tmp_path)
    path.write_text(SAMPLE_CONFIG.replace('  app_secret: ""', '  app_secret: "top-secret"'), encoding="utf-8")
    # 读出来喵
    fields = read_settings(load_config(path))
    secret = next(item for item in fields if item["name"] == "qqbot.app_secret")
    assert secret["value"] == SECRET_PLACEHOLDER
    # 普通项照常回显喵
    ws_url = next(item for item in fields if item["name"] == "napcat.ws_url")
    assert ws_url["value"] == "ws://127.0.0.1:7999"


def test_apply_settings_preserves_crlf(tmp_path: Path) -> None:
    """原文件是 CRLF 时写回也要是 CRLF喵。"""
    # 转成 CRLF 写入喵
    path = tmp_path / "config.yaml"
    path.write_bytes(SAMPLE_CONFIG.replace("\n", "\r\n").encode("utf-8"))
    # 改一个值喵
    apply_settings(path, {"napcat.ws_url": "ws://127.0.0.1:7000"})
    # 换行风格保持不变喵
    assert b"\r\n" in path.read_bytes()
    assert b'  ws_url: "ws://127.0.0.1:7000"\r\n' in path.read_bytes()


# ==================== 并发保存（任务 1）喵 ====================


def test_config_write_lock_is_module_level_rlock() -> None:
    """写配置用的必须是模块级可重入锁，同一线程可以重复进入喵。"""
    # 同一个线程连续两次 acquire 都必须成功，说明是可重入锁而不是普通 Lock喵
    assert _CONFIG_WRITE_LOCK.acquire(timeout=1.0) is True
    try:
        # 第二次进入：普通 Lock 在这里会卡死，RLock 直接返回 True喵
        assert _CONFIG_WRITE_LOCK.acquire(timeout=1.0) is True
        _CONFIG_WRITE_LOCK.release()
    finally:
        _CONFIG_WRITE_LOCK.release()


def test_concurrent_saves_keep_both_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个线程同时改不同字段，两边的改动都必须保留喵。

    喵~注意：这是「读-改-写」丢更新的回归测试。旧实现没有锁，
    两个线程都先读到旧文本，后写的会把先写的覆盖回原值喵。
    """
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 两个线程用 barrier 保证同时进入写流程喵
    barrier = threading.Barrier(2)
    # 锁内注入一点耗时，把「读完还没写回」的窗口拉长，稳定复现丢更新喵
    # 喵~注意：sleep 放在测试注入的 hook 里，生产代码不背这个延迟喵
    monkeypatch.setattr(settings_module, "_AFTER_READ_HOOK", lambda: time.sleep(0.05))
    # 收集线程异常，避免线程里报错被吞掉变成假绿喵
    errors: list[BaseException] = []

    def worker(name: str, value: object) -> None:
        """等所有线程就位后保存一个字段喵。"""
        try:
            barrier.wait(timeout=5)
            apply_settings(path, {name: value})
        except BaseException as error:  # noqa: BLE001 - 线程里必须自己兜住异常喵
            errors.append(error)

    # 一个线程改 intents，另一个改白名单，字段互不重叠喵
    threads = [
        threading.Thread(target=worker, args=("qqbot.intents", 999)),
        threading.Thread(target=worker, args=("acl.whitelist_groups", [777777])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    # 喵~注意：先断言数据，丢更新才是这个缺陷的主要表现；
    # Windows 上无锁时还可能因 os.replace 撞车抛 PermissionError，放在后面兜底喵
    config = load_config(path)
    assert config.qqbot.intents == 999
    assert config.acl.whitelist_groups == (777777,)
    # 线程都得正常结束喵
    assert not errors, errors


def test_sequential_saves_still_work(tmp_path: Path) -> None:
    """加锁之后串行保存不能退化，连续两次保存都要生效喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 连续改两个不同字段喵
    apply_settings(path, {"qqbot.intents": 111})
    apply_settings(path, {"acl.whitelist_groups": [888888]})
    # 两次改动都得留下喵
    config = load_config(path)
    assert config.qqbot.intents == 111
    assert config.acl.whitelist_groups == (888888,)


# ==================== 含特殊字符的值（任务 2）喵 ====================


# 需要往返验证的「难写」取值：注释符、冒号、引号、空串、换行喵
# 喵~注意：首尾空白不列在这里，因为 `_coerce` 本来就会 strip 字符串字段；
# 空白与纯空格值由下面的 _render_value 用例单独覆盖喵
TRICKY_VALUES = [
    "ws://host/#x",
    "a:b",
    'he said "hi"',
    "",
    "it's",
    "带#号和:冒号\"引号\"的值",
    "第一行\n第二行",
]


@pytest.mark.parametrize("value", TRICKY_VALUES)
def test_apply_settings_roundtrips_tricky_values(tmp_path: Path, value: str) -> None:
    """含 # : " ' 空串 换行的值写进去再读出来必须完全相等喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 写进 ws_url（普通字符串字段）喵
    apply_settings(path, {"napcat.ws_url": value})
    # 读回来必须一字不差喵
    assert load_config(path).napcat.ws_url == value


@pytest.mark.parametrize("value", TRICKY_VALUES)
def test_apply_settings_is_idempotent_for_tricky_values(tmp_path: Path, value: str) -> None:
    """二次保存同一批值不能再改动文本，尤其不能把 # 后面的内容当注释切掉喵。"""
    # 准备样例配置喵
    path = _write_sample(tmp_path)
    # 第一次写入喵
    apply_settings(path, {"napcat.ws_url": value})
    first_text = path.read_text(encoding="utf-8")
    # 第二次写入完全相同的值喵
    apply_settings(path, {"napcat.ws_url": value})
    # 文本一个字节都不该变喵
    assert path.read_text(encoding="utf-8") == first_text
    # 读回来仍然等于原值喵
    assert load_config(path).napcat.ws_url == value


def test_apply_settings_keeps_real_trailing_comment(tmp_path: Path) -> None:
    """真正的行尾注释要保留，不能因为防 # 就把它一起丢掉喵。"""
    # 给 ws_url 那行补一个行尾注释喵
    path = tmp_path / "config.yaml"
    path.write_text(
        SAMPLE_CONFIG.replace(
            '  ws_url: "ws://127.0.0.1:7999"',
            '  ws_url: "ws://127.0.0.1:7999"  # 正向 WS 地址喵',
        ),
        encoding="utf-8",
    )
    # 改值时注释必须还在喵
    apply_settings(path, {"napcat.ws_url": "ws://127.0.0.1:7000"})
    text = path.read_text(encoding="utf-8")
    assert '  ws_url: "ws://127.0.0.1:7000"  # 正向 WS 地址喵' in text
    # 注释只出现一次，没有被复制成两份喵
    assert text.count("# 正向 WS 地址喵") == 1


def test_render_value_quotes_values_needing_quote() -> None:
    """需要引号的值必须加引号，普通值保持逐字节不变喵。"""
    # 含注释符、冒号、双引号、单引号、首尾空格、空串都要被双引号包住喵
    for value in ("ws://h/#x", "a:b", 'say "hi"', "it's", "  空格  ", ""):
        rendered = settings_module._render_value("str", value)
        # 必须整体被双引号包住喵
        assert rendered.startswith('"') and rendered.endswith('"'), (value, rendered)
        # 渲染结果必须能被 YAML 还原成完全相同的值喵
        assert yaml.safe_load(f"k: {rendered}")["k"] == value
    # 普通值沿用既有的「总是加双引号」写法，不能多出转义喵
    assert settings_module._render_value("str", "ws://127.0.0.1:7999") == '"ws://127.0.0.1:7999"'
    assert settings_module._render_value("str", "info") == '"info"'
    assert settings_module._render_value("bool", True) == "true"
    assert settings_module._render_value("int", 8080) == "8080"
    # 内部双引号与反斜杠必须转义，否则写出来是坏 YAML喵
    assert settings_module._render_value("str", 'a"b') == '"a\\"b"'
    assert settings_module._render_value("str", "a\\b") == '"a\\\\b"'
