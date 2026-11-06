"""案件頁「業務」改顯示業務負責（roles.sales，沒填退回報價人）＋業績歸屬說明＋「報價人≠業務負責」提示（2026-11-06）。

背景：`quotations.sales_person`（報價單的報價人）與 `caseRecord.roles.sales`（業務負責／業績歸屬）是兩個獨立欄位，各自存、互不寫入
（docs/platform/plans/SALES-PERSON-VS-ROLES-SALES-ANALYSIS.md）。產品負責人 2026-11-06 裁示：案件管理清單卡片與詳情頭的「業務」
改讀 roles.sales，沒填才退回 sales_person（與營運報表 `_case_sales_owner` 同一個優先序）；兩者不同時角色區下方給一句中性提示。
只改「顯示哪一個」；不改任何欄位的讀寫、獎金、報表、可見度、篩選。

題目：
1. 頁面靜態：卡片／詳情頭走 salesOwnerName／selectedSalesOwner；角色下拉標籤、說明、提示條都在；樣式是中性色。
2. 行為（node 實跑 case-management-biz.js）：顯示優先序與提示條的各種組合，以及 getter／helper 不改動資料。
3. 後端清單端點回 `sales_owner`，`sales_person` 原樣保留；篩選／排序／可見度 SQL 不變。
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
API = HERE.parent / "api" / "quotations.py"
NODE = shutil.which("node")


def _page():
    return PAGE.read_text(encoding="utf-8")


# ── 1. 頁面靜態 ────────────────────────────────────────────────────────────────
def test_card_and_header_show_sales_owner_with_original_labels():
    h = _page()
    assert "x-text=\"lLabel('sales', '業務') + '：' + salesOwnerName(c)\"" in h
    assert "x-show=\"salesOwnerName(c) && lShown('sales')\"" in h
    assert '<span class="cm-meta__lbl">負責業務</span><span class="cm-meta__val" x-text="selectedSalesOwner||\'—\'"></span>' in h
    # 卡片／詳情頭不再直接綁 sales_person（改走 helper，helper 內才有退回報價人的邏輯）
    assert "c.sales_person" not in h and "selected.sales_person" not in h


def test_role_select_label_hint_and_note_present():
    h = _page()
    assert 'for="cm-role-sales">業績歸屬（業務負責）</label>' in h
    assert 'data-testid="cm-role-sales-hint">清單與頭部的「業務」、營運報表的業績與部門依此欄位；沒填時退回報價單的報價人<' in h
    assert 'data-testid="cm-sales-diff-note"' in h and 'x-text="salesRoleDiffNote"' in h
    assert 'x-model="roleSel.sales"' in h                      # 下拉仍綁同一個 roleSel.sales（只改文字，不改讀寫）


def test_hint_does_not_promise_bonus_behaviour():
    """獎金讀哪一欄由另案裁示／施工；畫面文字不先宣稱（避免文字比程式先走）。"""
    h = _page()
    i = h.index('data-testid="cm-role-sales-hint"')
    assert "獎金" not in h[i:i + 120]
    assert "獎金" not in BIZ_JS.read_text(encoding="utf-8")[BIZ_JS.read_text(encoding="utf-8").index("get salesRoleDiffNote()"):]


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


def test_biz_helpers_do_not_write_anything():
    """顯示邏輯只讀：新增的 helper／getter 內沒有任何 this.xxx = 或 .sales_person／.sales 的指派。"""
    src = BIZ_JS.read_text(encoding="utf-8")
    body = src[src.index("_roleSalesDisplay()"):src.index("get roleSel()")]
    assert not re.search(r"this\.[\w.]+\s*=[^=]", body)
    assert not re.search(r"\.(sales_person|sales|sales_owner)\s*=[^=]", body)


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
  o.selectableUsers = c.users
  const before = JSON.stringify([o.selected, o.cr, c.card])
  const r = { note: o.salesRoleDiffNote, header: o.selectedSalesOwner, card: o.salesOwnerName(c.card) }
  r.untouched = before === JSON.stringify([o.selected, o.cr, c.card])
  return r
})
console.log(JSON.stringify(out))
"""


def _run(cases):
    js = _HARNESS % {"code": json.dumps(BIZ_JS.read_text(encoding="utf-8")), "cases": json.dumps(cases, ensure_ascii=False)}
    p = subprocess.run([NODE, "-e", js], capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(p.stdout.decode("utf-8"))


def _case(sales_person, sales, card_owner=""):
    return {"selected": {"sales_person": sales_person}, "cr": {"caseRecord": {"roles": {"filler": "", "sales": sales, "executor": ""}}},
            "card": {"sales_person": sales_person, "sales_owner": card_owner}}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_display_priority_and_note_matrix():
    r = _run([
        _case("黃玉龍", {"username": "huang", "display": "黃玉龍"}, "黃玉龍"),   # 0 相同 ⇒ 顯示該人，無提示
        _case("黃玉龍", {"username": "kao", "display": "高晟耀"}, "高晟耀"),     # 1 不同 ⇒ 顯示業務負責，有提示
        _case("黃玉龍", "", ""),                                                   # 2 業務負責未填 ⇒ 退回報價人，無提示
        _case("黃玉龍", "高晟耀", "高晟耀"),                                       # 3 舊字串形狀、不同 ⇒ 顯示業務負責，有提示
        _case("黃玉龍", "黃玉龍", "黃玉龍"),                                       # 4 舊字串形狀、相同 ⇒ 無提示
        _case("", {"username": "kao", "display": "高晟耀"}, "高晟耀"),            # 5 沒有報價人 ⇒ 顯示業務負責，無提示
        _case(" 黃玉龍 ", {"username": "huang", "display": "黃玉龍 "}, "黃玉龍"),  # 6 前後空白不算不同
        _case("黃玉龍", {"username": "kao"}, "kao"),                               # 7 只有帳號、沒有 display ⇒ 用帳號
        {"selected": None, "cr": None, "card": None},                              # 8 尚未載入 ⇒ 不丟例外
        _case("", "", ""),                                                         # 9 兩邊都空 ⇒ 空
    ])
    note = [x["note"] for x in r]
    header = [x["header"] for x in r]
    card = [x["card"] for x in r]
    assert [note[i] for i in (0, 2, 4, 5, 6, 8, 9)] == [""] * 7
    assert note[1] == "報價人（黃玉龍）與業務負責（高晟耀）不是同一人：清單、營運報表的業績與部門依業務負責。"
    assert "高晟耀" in note[3] and "kao" in note[7]
    assert header == ["黃玉龍", "高晟耀", "黃玉龍", "高晟耀", "黃玉龍", "高晟耀", "黃玉龍", "kao", "", ""]
    assert card == ["黃玉龍", "高晟耀", "黃玉龍", "高晟耀", "黃玉龍", "高晟耀", "黃玉龍", "kao", "", ""]
    assert all(x["untouched"] for x in r)                                # 只讀：不改 selected／cr／card


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_header_uses_current_display_name_of_the_account():
    """roles.sales 存 {username, display}；顯示用帳號「現在」的名稱（改名後與下拉、卡片一致），查不到才用存檔當下的 display。"""
    c1 = _case("黃玉龍", {"username": "kao", "display": "舊名"}, "新名")
    c1["users"] = [{"username": "kao", "display_name": "新名"}]
    c2 = _case("黃玉龍", {"username": "gone", "display": "已停用的人"}, "已停用的人")
    c2["users"] = [{"username": "kao", "display_name": "新名"}]
    r = _run([c1, c2])
    assert [x["header"] for x in r] == ["新名", "已停用的人"]
    assert "（新名）" in r[0]["note"] and "舊名" not in r[0]["note"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_card_falls_back_to_sales_person_when_list_has_no_owner_field():
    """舊版伺服器／欄位缺席（sales_owner 為空或不存在）⇒ 卡片仍顯示報價人，與改版前相同。"""
    r = _run([{"selected": None, "cr": None, "card": {"sales_person": "黃玉龍"}},
              {"selected": None, "cr": None, "card": {"sales_person": "黃玉龍", "sales_owner": ""}}])
    assert [x["card"] for x in r] == ["黃玉龍", "黃玉龍"]


# ── 3. 後端清單：只新增 sales_owner，不動查詢條件 ───────────────────────────
def test_list_endpoint_adds_sales_owner_in_python_not_sql_json_extract():
    src = API.read_text(encoding="utf-8")
    assert 'row["sales_owner"] = _owner_map.get(row["quote_no"], "")' in src
    i = src.index("_owner_map = {}")
    seg = src[i:src.index('row["sales_owner"]', i)]
    assert "json_extract(" not in seg.lower()                  # ratchet：新程式在 Python 端逐筆解析
    assert "sales_person=?" not in seg and "UPDATE" not in seg.upper() and "INSERT" not in seg.upper()
