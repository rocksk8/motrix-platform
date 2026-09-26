"""CM12 P4 B 包（設備、叫料、派工、承攬匯款、出貨、完工、表單關閉）：原生 alert／confirm／prompt → MotrixUI。

- 靜態守門：附錄 A 包 B 列的 51 個方法，本體裡不可以再有原生 alert／confirm／prompt（跳過字串與註解）。
- e2e：代表性的三種（confirm(danger)、prompt、表單關閉的 Esc）走 MotrixUI；頁面上沒有任何原生對話框。
- 既有缺陷（本次一併修）：6 個表單視窗是 x-show，隱藏時 @keydown.escape.window 仍在監聽 ⇒ 在頁面任何
  地方按 Esc 都會連問「表單尚未儲存」。原生 confirm 被 e2e 自動按掉所以一直沒被看見。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "windows" / "SPEC-CM12-P4-UI.md"
JS = sorted((ROOT / "frontend" / "js").glob("case-management-*.js"))


def _b_methods():
    s = SPEC.read_text(encoding="utf-8")
    part = s[s.index("### 包 B"):s.index("### 用 `page.on")]
    return sorted(set(re.findall(r"\|\s*\d+\s*\|\s*`(\w+)`（", part)))


def _strip(src):
    """把字串、樣板字串、註解換成空白（保留長度），只留下程式本體。"""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i); j = n if j < 0 else j
            out[i:j] = " " * (j - i); i = j; continue
        if two == "/*":
            j = src.index("*/", i) + 2
            out[i:j] = [c if c == "\n" else " " for c in src[i:j]]; i = j; continue
        if src[i] in "\"'`":
            q = src[i]; j = i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            out[i + 1:j] = [c if c == "\n" else " " for c in src[i + 1:j]]; i = j + 1; continue
        i += 1
    return "".join(out)


def _method_bodies():
    bodies = {}
    for p in JS:
        src = _strip(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"^    (?:async )?(\w+)\([^)]*\)\s*\{", src, flags=re.M):
            depth, j = 0, m.end() - 1
            while True:
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            bodies.setdefault(m.group(1), src[m.end():j])
    return bodies


def test_b_package_methods_have_no_native_dialogs():
    methods = _b_methods()
    assert len(methods) == 51, "量尺：附錄 A 包 B 應有 51 個方法（112 處）"
    bodies = _method_bodies()
    missing = [m for m in methods if m not in bodies]
    assert not missing, "找不到方法本體：%s" % missing
    bad = [m for m in methods if re.search(r"(?<![\w.$])(alert|confirm|prompt)\s*\(", bodies[m])]
    assert not bad, "包 B 方法仍有原生對話框：%s" % bad


def test_positive_control_scanner_sees_a_package_natives():
    """正對照：A 包（hichan-bf）尚未改完前，掃描器要看得到它們——否則上一題可能是空集合的綠。"""
    bodies = _method_bodies()
    natives = [m for m, b in bodies.items() if re.search(r"(?<![\w.$])(alert|confirm|prompt)\s*\(", b)]
    s = SPEC.read_text(encoding="utf-8")
    a = set(re.findall(r"\|\s*\d+\s*\|\s*`(\w+)`（", s[s.index("### 包 A"):s.index("### 包 B")]))
    if not natives:
        pytest.skip("A 包也已全部改完：正對照改由 forbid_native_dialogs 全頁守門負責")
    assert set(natives) <= a, "有原生對話框的方法不屬於 A 包：%s" % sorted(set(natives) - a)


# ── e2e ──────────────────────────────────────────────────────────────────────

pytest.importorskip("playwright.sync_api")

from tests._ui_dialogs import DIALOG, answer_confirm, answer_prompt, forbid_native_dialogs  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, _login  # noqa: E402,F401
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-P4B-001"


def _seed():
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100, "received": False}]},
          "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "對話框客", "對話框案", 100, 95,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


def _open(browser, base, user):
    page = browser.new_context().new_page()
    natives = forbid_native_dialogs(page)
    _login(page, base, *user)
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page, natives


@pytest.mark.e2e
def test_escape_with_no_form_open_asks_nothing_and_open_form_asks_once(live_server, make_user, e2e_browser):
    u = make_user(username="p4b_admin", role="admin")
    _seed()
    browser = e2e_browser
    page, natives = _open(browser, live_server, u)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert page.locator(DIALOG).count() == 0, "沒有開著的表單，按 Esc 不可以問「表單尚未儲存」"

    page.evaluate(f"() => {DATA_JS}.openNewDispatch()")
    page.wait_for_function(f"() => {DATA_JS}.showDispatchModal", timeout=5000)
    page.keyboard.press("Escape")
    answer_confirm(page, ok=False, expect="表單尚未儲存")
    page.wait_for_timeout(300)
    assert page.locator(DIALOG).count() == 0, "只問一次（其他 5 個隱藏視窗不可以跟著問）"
    assert page.evaluate(f"() => {DATA_JS}.showDispatchModal") is True, "按取消要留在表單"
    page.keyboard.press("Escape")
    answer_confirm(page, ok=True, expect="表單尚未儲存")
    page.wait_for_function(f"() => !{DATA_JS}.showDispatchModal", timeout=5000)
    assert natives == []


@pytest.mark.e2e
def test_danger_confirm_and_prompt_go_through_motrix_ui(live_server, make_user, e2e_browser):
    u = make_user(username="p4b_admin2", role="admin")
    _seed()
    browser = e2e_browser
    page, natives = _open(browser, live_server, u)
    # confirm(danger)：叫料品項刪除——取消不刪、確定才刪
    page.evaluate(f"() => {{ {DATA_JS}.materialOrders = [{{ itemName: '線材' }}] }}")
    page.evaluate(f"() => {{ {DATA_JS}.moRemoveItem(0) }}")
    answer_confirm(page, ok=False, expect="確定要刪除叫料品項「線材」")
    page.wait_for_timeout(200)
    assert page.evaluate(f"() => {DATA_JS}.materialOrders.length") == 1
    page.evaluate(f"() => {{ {DATA_JS}.moRemoveItem(0) }}")
    answer_confirm(page, ok=True, expect="線材")
    page.wait_for_function(f"() => {DATA_JS}.materialOrders.length === 0", timeout=5000)

    # prompt：退回出貨單——取消＝不送出任何請求
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/reject" in r.url else None)
    page.evaluate(f"() => {{ {DATA_JS}.rejectShippingNote({{ noteNo: 'SN-X' }}) }}")
    answer_prompt(page, value=None, expect="退回出貨單「SN-X」")
    page.wait_for_timeout(300)
    assert reqs == [], "取消退回不可以送出請求"
    assert natives == []
