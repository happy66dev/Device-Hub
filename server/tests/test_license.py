"""开源许可证的回归测试喵。

主人的要求是「增加 MIT 开源许可证」，那就必须保证：
1. 仓库根目录确实有 LICENSE 文件；
2. 正文就是标准 MIT，没有被改写或截断；
3. 版权行和 README 里的说明对得上喵。
"""

from __future__ import annotations

from pathlib import Path

# 仓库根目录：当前文件在 server/tests/ 下，往上三级喵
REPO_ROOT = Path(__file__).resolve().parents[2]


def _license_text() -> str:
    """读出 LICENSE 正文，换行统一成 LF 方便比对喵。"""
    path = REPO_ROOT / "LICENSE"
    assert path.is_file(), "仓库根目录应有 LICENSE 文件"
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_license_file_exists() -> None:
    """LICENSE 必须在仓库根目录喵。"""
    # 直接判断存在性喵
    assert (REPO_ROOT / "LICENSE").is_file()


def test_license_is_mit() -> None:
    """正文必须是标准 MIT 许可证喵。"""
    text = _license_text()
    # 这些是 MIT 的骨架句，少一句就说明被改写过喵
    for marker in (
        "MIT License",
        "Permission is hereby granted, free of charge",
        'THE SOFTWARE IS PROVIDED "AS IS"',
        "WITHOUT WARRANTY OF ANY KIND",
        "copies or substantial portions of the Software",
    ):
        assert marker in text, f"MIT 正文缺少关键句：{marker}"


def test_license_has_copyright_line() -> None:
    """版权行要写明年份与作者喵。"""
    text = _license_text()
    # 喵~防御：年份跟着首次提交走，作者用仓库提交者喵
    assert "Copyright (c) 2026 happy" in text


def test_license_is_not_truncated() -> None:
    """MIT 正文末尾的免责段不能被截断喵。"""
    text = _license_text().strip()
    # 标准 MIT 以这句收尾喵
    assert text.endswith("SOFTWARE."), "LICENSE 末尾不完整"
    # 去掉空行后应当有 21 行左右，太少说明被删过喵
    assert len([line for line in text.split("\n") if line.strip()]) >= 15


def test_readme_links_to_license() -> None:
    """README 里要有指向 LICENSE 的许可证说明喵。"""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # 章节标题与链接都要在喵
    assert "## 许可证" in readme
    assert "(LICENSE)" in readme
    # 明确写出 MIT 喵
    assert "MIT" in readme
