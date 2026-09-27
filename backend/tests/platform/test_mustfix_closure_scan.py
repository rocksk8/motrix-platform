# -*- coding: utf-8 -*-
"""稽核必修的關閉紀錄守門（PLAYBOOK §E-6；D 的 d_scan_mustfix.py 移植）。

守的是「有沒有人做過決定」：每一筆宣告的必修，要嘛稽核檔有關閉紀錄，要嘛登記在 docs/platform/mustfix_open.json
（寫明誰在修、修在哪）。兩邊必須完全相同——沒關又沒登記＝被忘了；登記了卻已經關了＝登記過期。
正對照：拿掉標準關閉寫法之後，2026-09-28 D 人工確認過的那 14 筆（BP-M1＋13 筆寫法不一）必須全部亮起。
反向控制：合成的稽核檔——沒關、否定字樣、跨檔、四類寫法、登記表的每一種錯法。
"""
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import mustfix_scan as M  # noqa: E402

#: 2026-09-28 D 的掃描結果（d_scan_mustfix.README）：真的未關 1＋寫法不一的假陽性 13
D_20260928 = {"BP-M1", "B-2a", "B-2b", "M06-M1", "M06-M2", "M06-M3", "AT-M1", "O14-M1", "SM-M1",
              "M4-M1", "M4-M3", "CA3-M1", "CS-M1", "T13R-M1"}


# ── 真實的稽核檔 ─────────────────────────────────────────────────────────────

def test_open_mustfixes_match_the_register():
    texts = M.load_texts()
    problems = M.check(M.open_items(texts), M.load_register())
    assert not problems, "\n".join(problems)


def test_the_scanner_sees_the_audits():
    """正對照（量得到東西）：2026-09-28 宣告 95 筆；少於 90 ⇒ 掃描壞了（路徑、編碼、正規式），不是必修變少了。"""
    assert len(M.declared(M.load_texts())) >= 90


def test_known_open_items_light_up_without_the_canonical_lines():
    """正對照：把標準關閉寫法那幾行拿掉（等於回到 D 掃描當時），D 列出的 14 筆必須全部亮起。
    亮不起來 ⇒ 判準被放寬了（真的沒關的也會被當成關了）。"""
    texts = {f: [ln for ln in lines if not M.CANON.search(ln)] for f, lines in M.load_texts().items()}
    lit = {d for _f, d in M.open_items(texts)}
    assert D_20260928 <= lit, "應亮而沒亮：%s" % sorted(D_20260928 - lit)


# ── 合成的稽核檔：判準 ─────────────────────────────────────────────────────────

def _open(texts):
    return {d for _f, d in M.open_items(texts)}


def test_rc_declared_without_closure_is_open():
    texts = {"A.md": ["**X-M1（必修）　某事不成立", "修法：……"]}
    assert _open(texts) == {"X-M1"}
    texts["A.md"].append("- X-M1 複核：突變紅 ⇒ **關閉**")
    assert _open(texts) == set()


def test_rc_a_negated_line_does_not_close():
    """同一行有「未關」「待驗」「⏳」⇒ 不算關閉（標準寫法也一樣）。"""
    for neg in ("⏳", "未關", "待驗"):
        texts = {"A.md": ["**X-M1（必修）　x", "- ✅ X-M1 關閉（abc1234）%s" % neg]}
        assert _open(texts) == {"X-M1"}, neg


def test_rc_canonical_closure_needs_a_commit():
    """標準寫法要有 commit（7～40 位十六進位）；寫「見上」之類不算標準寫法，只能靠原本的判準（跨檔時多半不採信）。"""
    home = ["**X-M1（必修）　x"]
    assert _open({"A.md": home, "B.md": ["**X-M1 的後續", "✅ X-M1 關閉（見上）"]}) == {"X-M1"}
    assert _open({"A.md": home, "B.md": ["**X-M1 的後續", "✅ X-M1 關閉（abc1234）"]}) == set()


def test_rc_cross_file_rules_still_hold_for_loose_wording():
    """同一個 ID 在兩份檔宣告 ⇒ 散文式的跨檔關閉不採信（分不出關的是哪一份）；標準寫法可以。"""
    texts = {"A.md": ["**X-M1（必修）　a"], "B.md": ["**X-M1（必修）　b"], "C.md": ["X-M1 關閉"]}
    assert _open(texts) == {"X-M1"}
    texts["C.md"].append("✅ X-M1 關閉（abc1234）")
    assert _open(texts) == set()


@pytest.mark.parametrize("name, home, elsewhere", [
    ("①關閉寫在另一份檔的並列句", ["**X-M1（必修）　x"], ["**X-M1** 的複核", "- X-M1、X-M2 關閉"]),
    ("②改號延續", ["**X-M3（必修，新）　x", "⇒ **X-M3 未完全關閉，改列 X-M3b（必修）**", "⇒ **X-M3b 關閉（d8a6068b）**"], []),
    ("③表格 ID 加粗", ["**X-M1（必修）　x", "| **X-M1** | 再真刪一次，只剩允許的紅 | **關閉** |"], []),
    ("④寫成成立／通過", ["**X-M1（必修）　x", "| b22708bd | **X-M1**：改驗缺席行為 | 真刪樹 1 過，突變紅 | **X-M1 成立** |"], []),
])
def test_the_four_loose_wordings_are_open_until_written_canonically(name, home, elsewhere):
    """D 的四類假陽性：原本的判準認不得（亮）⇒ 補一行標準寫法 ⇒ 關。判準不放寬，是寫法統一。"""
    texts = {"A.md": list(home), "B.md": list(elsewhere)}
    d = "X-M3" if "改號" in name else "X-M1"
    assert d in _open(texts), name
    texts["A.md"].append("- ✅ %s 關閉（abc1234）——出處：……" % d)
    assert d not in _open(texts), name


# ── 合成：登記表 ─────────────────────────────────────────────────────────────

_REG = {"audit": "A.md", "owner": "A", "fix": "wip/a-x abc1234", "state": "修正中"}


def test_register_matches_open_items():
    assert M.check([("A.md", "X-M1")], {"X-M1": dict(_REG)}) == []


def test_rc_open_item_not_registered_is_forgotten():
    p = M.check([("A.md", "X-M1")], {})
    assert len(p) == 1 and "被忘了" in p[0]


def test_rc_registered_but_closed_is_stale():
    p = M.check([], {"X-M1": dict(_REG)})
    assert len(p) == 1 and "登記過期" in p[0]


@pytest.mark.parametrize("field", M.REGISTER_FIELDS)
def test_rc_register_entry_without_a_field_is_red(field):
    """登記要寫明在哪一份稽核、誰在修、修在哪、目前狀態——空的登記＝沒有人做過決定。"""
    e = dict(_REG, **{field: ""})
    p = M.check([("A.md", "X-M1")], {"X-M1": e})
    assert p and field in p[0]


def test_rc_register_audit_must_be_the_declaring_file():
    p = M.check([("A.md", "X-M1")], {"X-M1": dict(_REG, audit="B.md")})
    assert p and "不符" in p[0]


def test_rc_register_cannot_absorb_everything():
    """反向控制（〈守門要驗有沒有人做過決定〉）：把所有未關的都寫進登記表可以讓比對一致，但超過上限就紅。"""
    opened = [("A.md", "X-M%d" % i) for i in range(M.MAX_OPEN + 1)]
    reg = {d: dict(_REG) for _f, d in opened}
    p = M.check(opened, reg)
    assert len(p) == 1 and "超過上限" in p[0]
    assert M.check(opened[:-1], {d: dict(_REG) for _f, d in opened[:-1]}) == []


def test_cli_exit_code_follows_the_check(tmp_path, capsys):
    """CLI：一致 ⇒ 0；多一筆沒登記的必修 ⇒ 1，並印出是哪一筆。"""
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "AUDIT-X.md").write_text("**X-M1（必修）　x\n", encoding="utf-8")
    reg = tmp_path / "reg.json"
    reg.write_text('{"open": {"X-M1": {"audit": "AUDIT-X.md", "owner": "A", "fix": "f", "state": "s"}}}', encoding="utf-8")
    assert M.main(["--audit-dir", str(audit), "--register", str(reg)]) == 0
    (audit / "AUDIT-Y.md").write_text("**Y-M1（必修）　y\n", encoding="utf-8")
    assert M.main(["--audit-dir", str(audit), "--register", str(reg)]) == 1
    assert "Y-M1" in capsys.readouterr().out


def test_declaration_forms_follow_d():
    """宣告的三種寫法（D 的判準）：粗體（必修、表格列、必修段落內的粗體行；沒有數字的字不算 ID。"""
    texts = {"A.md": ["**P-M1（必修）　a", "| T-2 | 說明 | 必修 |", "### 必修", "**S-1　c", "**B　不是編號", "## 其他", "**Q-1　不在段落內"]}
    assert Counter(d for _f, d in M.declared(texts)) == Counter({"P-M1": 1, "T-2": 1, "S-1": 1})
