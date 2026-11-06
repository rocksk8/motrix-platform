"""案件頁「報價人」vs「業績歸屬」標示與提示（2026-11-06，產品負責人裁示選項 A，零資料風險）。

背景：`quotations.sales_person`（報價單的報價人，業務獎金依它）與 `caseRecord.roles.sales`（業績歸屬，營運報表依它）
是兩個獨立欄位、設計如此（docs/platform/plans/SALES-PERSON-VS-ROLES-SALES-ANALYSIS.md）。
這次只改文字與提示顯示：清單卡片／詳情頭「業務」→「報價人」；角色下拉「業務負責」→「業績歸屬（業務負責）」＋一句說明；
兩邊都有值且顯示名不同時，角色區下方顯示一條中性提示。不改任何欄位的讀寫。

題目：
1. 頁面靜態：標籤、說明、提示條都在；舊的「業務」卡片標籤與「負責業務」頭部標籤不再出現；提示條不用錯誤／警告色。
2. 行為（node 實跑 case-management-biz.js 的 getter）：相同／不同／未填／舊字串形狀／報價人空，以及 getter 不改動資料。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
from core import source_tree   # noqa: E402  頁面路徑一律經 source_tree（守門 test_page_paths_centralized）
PAGE = source_tree.page_file("case-management.html")
BIZ_JS = ROOT / "frontend" / "js" / "case-management-biz.js"
CSS = ROOT / "frontend" / "css" / "case-management.css"
NODE = shutil.which("node")


def _page():
    return PAGE.read_text(encoding="utf-8")


# ── 1. 頁面靜態 ────────────────────────────────────────────────────────────────
def test_card_and_header_say_quoter_not_sales():
    h = _page()
    assert "lLabel('sales', '報價人')" in h
    assert "lLabel('sales', '業務')" not in h          # 舊預設標籤
    assert '<span class="cm-meta__lbl">報價人</span>' in h
    assert '<span class="cm-meta__lbl">負責業務</span>' not in h


def test_role_select_label_hint_and_note_present():
    h = _page()
    assert 'for="cm-role-sales">業績歸屬（業務負責）</label>' in h
    assert 'data-testid="cm-role-sales-hint">業務獎金依報價人計算，與此欄位無關<' in h
    assert 'data-testid="cm-sales-diff-note"' in h and 'x-text="salesRoleDiffNote"' in h
    # 下拉仍綁同一個 roleSel.sales（只改文字，不改讀寫）
    assert 'x-model="roleSel.sales"' in h


def test_note_and_hint_are_neutral_not_error_or_warning_colour():
    css = CSS.read_text(encoding="utf-8")
    for cls in (".cm-role-hint", ".cm-role-note"):
        rule = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", css)
        assert rule, cls
        assert "danger" not in rule.group(1) and "warning" not in rule.group(1), (cls, rule.group(1))
    h = _page()
    i = h.index('data-testid="cm-sales-diff-note"')
    tag = h[h.rindex("<div", 0, i):h.index(">", i)]
    assert "danger" not in tag and "warning" not in tag and "red" not in tag.lower()


def test_biz_part_does_not_write_sales_person():
    """提示邏輯只讀：getter 內不出現對 sales_person／roles 的指派。"""
    src = BIZ_JS.read_text(encoding="utf-8")
    i = src.index("get salesRoleDiffNote()")
    body = src[i:src.index("get roleSel()", i)]
    assert not re.search(r"this\.[\w.]+\s*=[^=]", body)         # 沒有任何 this.xxx = 指派
    assert not re.search(r"\.(sales_person|sales)\s*=[^=]", body)


# ── 2. 行為（node）────────────────────────────────────────────────────────────
_HARNESS = r"""
global.window = global
window.CM_PARTS = []
eval(%(code)s)
const o = Object.defineProperties({}, Object.getOwnPropertyDescriptors(window.CM_PARTS[0]()))
const cases = %(cases)s
const out = cases.map(c => {
  o.selected = c.selected
  o.cr = c.cr
  const before = JSON.stringify([o.selected, o.cr])
  const note = o.salesRoleDiffNote
  return { note, untouched: before === JSON.stringify([o.selected, o.cr]) }
})
console.log(JSON.stringify(out))
"""


def _run(cases):
    js = _HARNESS % {"code": json.dumps(BIZ_JS.read_text(encoding="utf-8")), "cases": json.dumps(cases, ensure_ascii=False)}
    p = subprocess.run([NODE, "-e", js], capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(p.stdout.decode("utf-8"))


def _case(sales_person, sales):
    return {"selected": {"sales_person": sales_person}, "cr": {"caseRecord": {"roles": {"filler": "", "sales": sales, "executor": ""}}}}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_note_shown_only_when_both_present_and_different():
    r = _run([
        _case("黃玉龍", {"username": "huang", "display": "黃玉龍"}),     # 0 相同 ⇒ 無提示
        _case("黃玉龍", {"username": "kao", "display": "高晟耀"}),       # 1 不同 ⇒ 提示
        _case("黃玉龍", ""),                                              # 2 業績歸屬未填（報表退回報價人）⇒ 無提示
        _case("黃玉龍", "高晟耀"),                                        # 3 舊字串形狀、不同 ⇒ 提示
        _case("黃玉龍", "黃玉龍"),                                        # 4 舊字串形狀、相同 ⇒ 無提示
        _case("", {"username": "kao", "display": "高晟耀"}),             # 5 沒有報價人 ⇒ 無提示
        _case(" 黃玉龍 ", {"username": "huang", "display": "黃玉龍 "}),  # 6 前後空白不算不同
        _case("黃玉龍", {"username": "kao"}),                             # 7 只有帳號、沒有 display ⇒ 用帳號比
        {"selected": None, "cr": None},                                   # 8 尚未載入 ⇒ 不丟例外
    ])
    notes = [x["note"] for x in r]
    assert notes[0] == "" and notes[2] == "" and notes[4] == "" and notes[5] == "" and notes[6] == "" and notes[8] == ""
    assert "黃玉龍" in notes[1] and "高晟耀" in notes[1] and notes[1].startswith("報價人（黃玉龍）與業績歸屬（高晟耀）不是同一人")
    assert "業務獎金依報價人" in notes[1]
    assert "高晟耀" in notes[3]
    assert "kao" in notes[7]
    assert all(x["untouched"] for x in r)                                # 只讀：不改 selected／cr
