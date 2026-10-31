"""设置页配置读写的单元测试：文本替换、类型转换、校验回滚喵。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.settings import (
    SECRET_PLACEHOLDER,
    SettingsError,
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
