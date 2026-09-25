"""CHANGELOG 段落守門（主持 2026-09-26：core_bump 以標題比對時曾把已合回的段落重複編號）。

core/CHANGELOG.md 與 modules/*/CHANGELOG.md：
  ① 不可以有內文重複的段落（同一件事被編了兩個號）
  ② 「## 主.次」段落的版號由上往下嚴格遞減（重編號出錯、兩條線撞號都會打亂順序）
「## 主.次」（core）與「## 主.次.修」（模組）都檢查；內文空白的段落不參與 ①。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

FILES = [REPO / "backend" / "core" / "CHANGELOG.md"] + sorted((REPO / "backend" / "modules").glob("*/CHANGELOG.md"))


HEADER = re.compile(r"^## +(\d+(?:\.\d+)+)(?![\d.])[^\n]*$", re.M)


def sections(text):
    """⇒ [(標題行, 版號 tuple, 內文)]；「## 主.次」與「## 主.次.修」都算（core 用前者、模組用後者）。"""
    ms = list(HEADER.finditer(text))
    return [(m.group(0), tuple(int(x) for x in m.group(1).split(".")),
             text[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(text)]) for i, m in enumerate(ms)]


def problems(text):
    """⇒ 問題清單。"""
    out = []
    secs = sections(text)
    seen = {}
    for h, v, body in secs:
        b = body.strip()
        if b and b in seen:
            out.append("內文重複：%s 與 %s" % (seen[b], h.strip()))
        seen.setdefault(b, h.strip())
    vs = [v for _, v, _ in secs]
    for a, b in zip(vs, vs[1:]):
        if not a > b:
            out.append("版號沒有由上往下遞減：%s 之後是 %s" % (".".join(map(str, a)), ".".join(map(str, b))))
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(REPO).as_posix())
def test_changelog_sections_are_unique_and_descending(path):
    probs = problems(path.read_text(encoding="utf-8"))
    assert not probs, "\n".join(probs)


def test_scanner_sees_sections():
    """正對照：core 的 CHANGELOG 讀得到多段（讀不到時上一題會安靜地綠）。"""
    assert len(sections(FILES[0].read_text(encoding="utf-8"))) >= 5


PRE = "# x\n\n"


def test_rc_duplicate_body_is_caught():
    """今晚實際發生的形狀：同一段內文以 1.14 與 1.13 各出現一次。"""
    t = PRE + "## 1.14 — d〔core_bump：暫用 1.10 → 1.14〕\n- core.pages\n\n## 1.13 — d〔core_bump：暫用 1.10 → 1.13〕\n- core.pages\n"
    assert any("內文重複" in p for p in problems(t))


def test_rc_non_descending_versions_are_caught():
    t = PRE + "## 1.12 — d\n- a\n\n## 1.13 — d\n- b\n"
    assert any("遞減" in p for p in problems(t))


def test_module_semver_changelog_is_checked():
    t = PRE + "## 1.1.0 — d\n- a\n\n## 1.1.0 — d\n- b\n"
    assert any("遞減" in p for p in problems(t))
    assert problems(PRE + "## 1.1.0 — d\n- a\n\n## 1.0.1 — d\n- b\n") == []
