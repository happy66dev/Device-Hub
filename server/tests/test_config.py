"""配置加载的单元测试，覆盖正常、缺字段、类型错误、未知字段喵。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, load_config


def _write_config(tmp_path: Path, text: str) -> Path:
    """把 YAML 文本写到临时文件并返回路径喵。"""
    # 目标文件路径喵
    config_path = tmp_path / "config.yaml"
    # 以 UTF-8 写入，避免中文注释乱码喵
    config_path.write_text(text, encoding="utf-8")
    return config_path


def test_load_config_ok(tmp_path: Path) -> None:
    """完整配置应能正常加载，相对数据库路径应解析到配置文件同级目录喵。"""
    # 准备一份最小可用配置喵
    config_path = _write_config(
        tmp_path,
        """
server:
  host: "127.0.0.1"
  port: 9090
  db_path: "data/app.db"
ingest:
  token: "0123456789abcdef"
acl:
  whitelist_groups: [123456]
  blacklist_users: [999]
napcat:
  enabled: false
""",
    )
    # 加载配置喵
    config = load_config(config_path)
    # 端口应被读取喵
    assert config.server.port == 9090
    # 相对路径应解析到配置目录下喵
    assert config.server.db_path == (tmp_path / "data" / "app.db").resolve()
    # 白名单群号应被解析成整数元组喵
    assert config.acl.whitelist_groups == (123456,)
    # 机器人关闭时允许 token 为空喵
    assert config.napcat.enabled is False


def test_load_config_missing_token(tmp_path: Path) -> None:
    """上报口令缺失时应报错，避免服务端裸奔喵。"""
    # 故意不写 ingest 节喵
    config_path = _write_config(tmp_path, "server:\n  port: 8080\n")
    # 喵~防御：这里必须抛 ConfigError 而不是用默认空口令喵
    with pytest.raises(ConfigError, match="ingest.token"):
        load_config(config_path)


def test_load_config_short_token(tmp_path: Path) -> None:
    """口令过短同样应报错喵。"""
    # 口令只有 4 位喵
    config_path = _write_config(tmp_path, "ingest:\n  token: \"abcd\"\nnapcat:\n  enabled: false\n")
    # 期望抛出配置错误喵
    with pytest.raises(ConfigError, match="至少需要 8 位"):
        load_config(config_path)


def test_load_config_unknown_field(tmp_path: Path) -> None:
    """拼错的字段名应报错，避免主人以为配置生效了喵。"""
    # 把 port 拼成 prot 喵
    config_path = _write_config(
        tmp_path,
        "server:\n  prot: 8080\ningest:\n  token: \"0123456789abcdef\"\nnapcat:\n  enabled: false\n",
    )
    # 期望提示未知字段喵
    with pytest.raises(ConfigError, match="未知字段"):
        load_config(config_path)


def test_load_config_wrong_type(tmp_path: Path) -> None:
    """端口写成字符串应报错喵。"""
    # 端口用引号包成字符串喵
    config_path = _write_config(
        tmp_path,
        "server:\n  port: \"8080\"\ningest:\n  token: \"0123456789abcdef\"\nnapcat:\n  enabled: false\n",
    )
    # 期望类型错误提示喵
    with pytest.raises(ConfigError, match="必须是整数"):
        load_config(config_path)


def test_load_config_bool_is_not_int(tmp_path: Path) -> None:
    """布尔值不能被当成整数端口，这是 Python 里的经典坑喵。"""
    # 端口写成 true 喵
    config_path = _write_config(
        tmp_path,
        "server:\n  port: true\ningest:\n  token: \"0123456789abcdef\"\nnapcat:\n  enabled: false\n",
    )
    # 期望报类型错误喵
    with pytest.raises(ConfigError, match="必须是整数"):
        load_config(config_path)


def test_load_config_missing_file(tmp_path: Path) -> None:
    """配置文件不存在时应给出带路径的错误提示喵。"""
    # 指向一个不存在的文件喵
    missing_path = tmp_path / "not-exists.yaml"
    # 期望抛配置错误喵
    with pytest.raises(ConfigError, match="无法读取配置文件"):
        load_config(missing_path)


def test_load_config_napcat_requires_token(tmp_path: Path) -> None:
    """启用机器人却没有 token 时应报错喵。"""
    # 机器人开启但 token 为空喵
    config_path = _write_config(
        tmp_path,
        "ingest:\n  token: \"0123456789abcdef\"\nnapcat:\n  enabled: true\n  token: \"\"\n",
    )
    # 期望提示补 token 喵
    with pytest.raises(ConfigError, match="napcat.token"):
        load_config(config_path)


def test_load_config_napcat_disabled_by_default(tmp_path: Path) -> None:
    """不写 napcat 节时应默认关闭机器人，不能因缺 token 直接启动失败喵。"""
    # 只写最少的 ingest 节，完全省略 napcat 喵
    config_path = _write_config(tmp_path, "ingest:\n  token: \"0123456789abcdef\"\n")
    # 喵~注意：默认值必须与 config.example.yaml 的 enabled: false 一致喵
    config = load_config(config_path)
    # 默认可加载且机器人关闭喵
    assert config.napcat.enabled is False
    # 没配 token 也不该有值喵
    assert config.napcat.token == ""

def test_load_config_happy_group_defaults_to_happy(tmp_path: Path) -> None:
    """不写 bot 节时，happy 系列命令应默认绑定 happy 组喵。"""
    # 只写最小配置喵
    config_path = _write_config(tmp_path, "ingest:\n  token: \"0123456789abcdef\"\n")
    # 默认组名喵
    config = load_config(config_path)
    assert config.bot.happy_group == "happy"


def test_load_config_happy_group_can_be_overridden(tmp_path: Path) -> None:
    """配置里写 bot.happy_group 时应生效，方便主人换组名喵。"""
    # 显式指定自定义组名喵
    config_path = _write_config(
        tmp_path,
        "ingest:\n  token: \"0123456789abcdef\"\nbot:\n  happy_group: \"我的组\"\n",
    )
    config = load_config(config_path)
    assert config.bot.happy_group == "我的组"


def test_load_config_happy_group_blank_falls_back(tmp_path: Path) -> None:
    """组名写成空白串时不能真的绑到空组名上，应退回默认值喵。"""
    # 故意写空串喵
    config_path = _write_config(
        tmp_path,
        "ingest:\n  token: \"0123456789abcdef\"\nbot:\n  happy_group: \"   \"\n",
    )
    # 喵~防御：空白组名永远匹配不到任何组，必须兜底喵
    config = load_config(config_path)
    assert config.bot.happy_group == "happy"


def test_load_config_rejects_unknown_bot_key(tmp_path: Path) -> None:
    """bot 节里拼错键名要报错，别让主人以为改生效了喵。"""
    # 把 happy_group 拼成 happy_grop 喵
    config_path = _write_config(
        tmp_path,
        "ingest:\n  token: \"0123456789abcdef\"\nbot:\n  happy_grop: \"happy\"\n",
    )
    with pytest.raises(ConfigError, match="未知字段"):
        load_config(config_path)


# ==================== 示例配置 ====================


def test_example_config_loads(tmp_path: Path) -> None:
    """仓库里的 config.example.yaml 必须能直接加载喵。"""
    # 示例文件在 server 目录下喵
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    assert example.is_file(), "config.example.yaml 应该和 config.yaml 放在一起"
    # 直接加载，字段写错或漏字段都会在这里暴露喵
    config = load_config(example)
    # 敏感项必须是空的，示例不许带真凭据喵
    assert config.qqbot.app_id == ""
    assert config.qqbot.app_secret == ""
    assert config.napcat.token == ""
    assert config.napcat.self_qq == ""
    # 通道默认全关，避免没凭据时一启动就报错喵
    assert config.qqbot.enabled is False
    assert config.napcat.enabled is False
    # 白名单默认全空，不误响应任何群喵
    assert config.acl.whitelist_groups == ()
    assert config.acl.whitelist_group_openids == ()
    assert config.qqbot.free_command_group_openids == ()


def test_example_config_has_no_real_secret(tmp_path: Path) -> None:
    """示例配置里不能出现像样的密钥字符串喵。"""
    # 读原始文本，逐项检查喵
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    text = example.read_text(encoding="utf-8")
    # 喵~注意：这些字段必须是空的引号，不能有内容喵
    for key in ("app_id:", "app_secret:", "self_qq:"):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(key):
                value = stripped.split(":", 1)[1].strip()
                assert value == '""', f"{key} 在示例里应留空，实际是 {value}"
