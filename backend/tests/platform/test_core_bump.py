"""tools/platform/core_bump.py：合回時依 origin 自動取 CORE 版號（PLAYBOOK §C-7）。純函式，合成 CHANGELOG。"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_core_bump", REPO / "tools" / "platform" / "core_bump.py")
CB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CB)

PRE = "# L0／L1 底層 更新紀錄\n\n> 說明\n\n"
ONTO = PRE + "## 1.9 — 2026-09-26\n> A\n- a\n\n## 1.8 — 2026-09-26\n> X\n- x\n"


def _mine(*sections):
    """sections：[(版號, 標記)] 由上往下，接在 onto 的 1.8 之前（模擬 rebase 前我的分支：基底只到 1.8）。"""
    body = "".join("## %s — 2026-09-26（B-%s）\n- %s\n\n" % (v, tag, tag) for v, tag in sections)
    return PRE + body + "## 1.8 — 2026-09-26\n> X\n- x\n"


def test_my_single_section_takes_the_next_minor():
    """今晚實際發生的：我暫用 1.9，origin 的 1.9 已被 A 用掉 ⇒ 我改 1.10，放在 A 的 1.9 之上。"""
    text, ver, _ = CB.plan(_mine(("1.9", "c1")), ONTO, (1, 9), "minor")
    assert ver == "1.10"
    _, secs = CB.split_sections(text)
    assert [s[1] for s in secs] == [(1, 10), (1, 9), (1, 8)]
    assert secs[0][0].startswith("## 1.10 — 2026-09-26（B-c1）") and "暫用 1.9 → 1.10" in secs[0][0]
    assert secs[1][0] == "## 1.9 — 2026-09-26", "onto 的段落原封不動"


def test_two_sections_are_renumbered_bottom_up():
    text, ver, _ = CB.plan(_mine(("1.11", "c3"), ("1.10", "c1")), ONTO, (1, 9), "minor")
    assert ver == "1.11"
    _, secs = CB.split_sections(text)
    assert [(s[1], "c3" in s[0]) for s in secs[:2]] == [((1, 11), True), ((1, 10), False)]
    assert "暫用" not in secs[0][0] and "暫用" not in secs[1][0], "號碼沒變就不註記"


def test_major_bump_goes_to_the_lowest_of_my_sections():
    text, ver, _ = CB.plan(_mine(("1.10", "b"), ("1.9", "a")), ONTO, (1, 9), "major")
    assert ver == "2.1"
    assert [s[1] for s in CB.split_sections(text)[1][:2]] == [(2, 1), (2, 0)]


def test_behaviour_only_section_still_takes_a_minor():
    """介面沒變（need=None）但我有段落（例：X-9b 1.8「介面不變，只有行為」）⇒ 仍取下一個次版號。"""
    _, ver, _ = CB.plan(_mine(("1.9", "x")), ONTO, (1, 9), None)
    assert ver == "1.10"


def test_nothing_to_do_without_my_sections():
    assert CB.plan(ONTO, ONTO, (1, 9), None)[:2] == (None, None)


def test_rc_interface_change_without_changelog_is_refused():
    """反向控制：介面變了卻沒有自己的段落 ⇒ 不替人寫內容，拒絕。"""
    text, ver, msg = CB.plan(ONTO, ONTO, (1, 9), "minor")
    assert text is None and "先寫 core/CHANGELOG.md" in msg


def test_rc_three_part_headers_are_not_sections():
    """「## 1.4.1」不是 CORE 版號段落（同 _l1_interface.changelog_top_version 的規則）。"""
    _, secs = CB.split_sections(PRE + "## 1.4.1 — x\n- y\n")
    assert secs == []


def test_rc_my_sections_stop_at_the_first_shared_header():
    """我的段落只取最上面、onto 沒有的——onto 也有的那段之後不再往下找（不會把舊段落重編號）。"""
    mine = _mine(("1.9", "c1"))
    assert [s[1] for s in CB.my_sections(mine, ONTO)] == [(1, 9)]


def test_rc_already_merged_section_with_rewritten_header_is_not_mine():
    """2026-09-26 實際發生：C1 以「## 1.13 …〔core_bump：暫用 1.10 → 1.13〕」合回；C3 疊在 C1 上，它的 CHANGELOG
    仍是 C1 的原標題「## 1.10 …」。以標題比對會把 C1 的段落又當成我的（重複成 1.14）。以內文比對 ⇒ 只剩 C3 那一段。"""
    c1_body = "\n- core.pages\n\n"
    onto = PRE + "## 1.13 — 2026-09-26（B）〔core_bump：暫用 1.10 → 1.13〕" + c1_body + "## 1.9 — 2026-09-26\n> A\n- a\n\n## 1.8 — 2026-09-26\n> X\n- x\n"
    mine = PRE + "## 1.11 — 2026-09-26（B-c3）\n- core.menu\n\n" + "## 1.10 — 2026-09-26（B）" + c1_body + "## 1.8 — 2026-09-26\n> X\n- x\n"
    secs = CB.my_sections(mine, onto)
    assert [s[1] for s in secs] == [(1, 11)]
    text, ver, _ = CB.plan(mine, onto, (1, 13), "minor")
    assert ver == "1.14" and text.count("core.pages") == 1
