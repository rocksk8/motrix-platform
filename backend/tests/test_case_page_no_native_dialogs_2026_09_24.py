"""案件管理頁不得再使用瀏覽器原生對話框（CM12 P4，2026-09-24）。

P4 把案件頁 232 處 alert／confirm／prompt 換成 static/ui.js 的 MotrixUI（toast／confirm／prompt）。
原生對話框會卡住整個分頁、樣式不隨深色模式、e2e 只能盲接——換完之後不可以再長回來。
① 靜態：case-management.html＋case-management-*.js（剝註解）沒有 alert( ／confirm( ／prompt(
   （MotrixUI.confirm( 這類「成員呼叫」不算；window.confirm( 算）。附合成樣本正對照。
② e2e：走一趟 A、B 兩包各 3 個「會先問」的操作（刪款項期別、刪執行階段、刪動態／刪材料、刪出貨單、
   刪完工單），全部按取消：不得出現任何原生對話框，而且資料一筆都沒被刪。
P4 A／B 兩包已於 2026-09-24 全部推上 master，xfail 已拿掉。
"""
import json
import pathlib
import re
import threading
import time

import pytest
from tests._e2e_login import inject_login  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "pages" / "case-management.html"
JS_FILES = sorted((ROOT / "frontend" / "js").glob("case-management-*.js"))

# 前面不是「.」或識別字元的 alert／confirm／prompt 呼叫；window.xxx( 另外算
NATIVE = re.compile(r"(?:(?<![\w.$])|(?<=window\.))(alert|confirm|prompt)\s*\(")


def _strip_js_comments(s):
    # 字串內不太會出現 // 或 /*，保守地只剝行尾 // 與區塊註解（與其他掃描題相同的近似）
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in s.split("\n"))


def _native_calls(text, html=False):
    if html:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = _strip_js_comments(text)
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        for m in NATIVE.finditer(line):
            out.append((n, m.group(1), line.strip()[:100]))
    return out


def test_scanner_positive_control():
    sample = (
        "alert('a')\n"                       # 抓
        "if (!confirm('b')) return\n"        # 抓
        "const r = window.prompt('c')\n"     # 抓（window. 也算原生）
        "await MotrixUI.confirm('d')\n"      # 不抓：成員呼叫
        "this._confirmRemoveDevice(x)\n"     # 不抓：識別字的一部分
        "confirmCloseCase()\n"               # 不抓：不同名稱
        "// alert('註解裡的不算')\n"
        "/* confirm('區塊註解也不算') */\n"
    )
    got = [k for _, k, _ in _native_calls(sample)]
    assert got == ["alert", "confirm", "prompt"], got
    html = "<!-- alert('x') --><button @click=\"if (dirty) { alert('y') }\">"
    assert [k for _, k, _ in _native_calls(html, html=True)] == ["alert"]


def test_case_page_source_has_no_native_dialogs():
    bad = []
    for p in [PAGE] + JS_FILES:
        for n, kind, line in _native_calls(p.read_text(encoding="utf-8"), html=p.suffix == ".html"):
            bad.append(f"{p.name}:{n}: {kind}( ｜ {line}")
    assert not bad, f"案件頁仍有 {len(bad)} 處原生對話框：\n" + "\n".join(bad[:40])


# ── e2e ──────────────────────────────────────────────────────────────────
NO = "MQ-NODLG-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"


def _seed(author):
    import db
    conn = db.get_db()
    try:
        stages = []
        for i, label in enumerate(("施工", "驗收")):
            sid = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?)", (NO, label, i, 0, T0, T0)).lastrowid
            stages.append({"id": sid, "label": label, "done": False})
        cr = {"payment": {"items": [{"id": 1, "type": "訂金", "pct": 30, "received": False, "note": ""},
                                    {"id": 2, "type": "尾款", "pct": 70, "received": False, "note": ""}]},
              "materials": [{"id": 11, "name": "交換器", "qty": 1, "unit": "台", "ordered": False, "arrived": False,
                             "model": "", "devices": []}],
              "stages": stages}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), T0, T0, "已成案", "2026-03-01"))
        conn.execute("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                     " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("SN-NODLG-1", NO, "草稿", "客戶", "[]", "{}", T0, T0))
        conn.execute("INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?)", ("CN-NODLG-1", NO, "草稿", "{}", T0, T0))
        conn.execute("INSERT INTO case_updates (quote_no, author, content, type, created_at) VALUES (?,?,?,?,?)",
                     (NO, author, "我自己的動態", "comment", "2026-03-02 10:00:00"))
        conn.commit()
    finally:
        conn.close()


def _counts():
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
        one = lambda sql: conn.execute(sql, (NO,)).fetchone()[0]  # noqa: E731
        return {
            "payment": len(d["caseRecord"]["payment"]["items"]),
            "materials": len(d["caseRecord"]["materials"]),
            "stages": one("SELECT COUNT(*) FROM case_stages WHERE quote_no=?"),
            "shipping": one("SELECT COUNT(*) FROM shipping_notes WHERE quote_no=?"),
            "completion": one("SELECT COUNT(*) FROM completion_notes WHERE quote_no=?"),
            "updates": one("SELECT COUNT(*) FROM case_updates WHERE quote_no=?"),
        }
    finally:
        conn.close()




# （說明, 觸發的 JS）；呼叫不 await——確認框開著時 Promise 不會結束
ACTIONS = [
    ("A 刪款項期別", "c.removePaymentItem(0)"),
    ("A 刪執行階段", "c.removeStage(0)"),
    ("A 刪動態", "c.deleteUpdate(c.caseUpdates[0].id)"),
    ("B 刪材料", "c.removeMaterial(0)"),
    ("B 刪完工單", "c.deleteCompletionNote(c.completionNotes[0])"),
]


def _supply_installed():
    from core import source_tree
    return source_tree.module_installed("modules/supply/api/shipping_notes.py")


def _actions():
    """出貨單屬 M03：模組不在時出貨分頁只有說明、沒有單據可刪 ⇒ 那一步不做，其餘照驗（PLAYBOOK §B-11）。"""
    return ACTIONS + ([("B 刪出貨單", "c.deleteShippingNote(c.shippingNotes[0])")] if _supply_installed() else [])


@pytest.mark.e2e
def test_main_actions_use_no_native_dialogs(live_server, make_user, e2e_browser):
    from tests._ui_dialogs import DIALOG, forbid_native_dialogs
    u = make_user(username="nodlg_admin", role="admin")
    _seed(author="nodlg_admin")
    before = _counts()
    native_by_action = {}
    browser = e2e_browser
    page = browser.new_context().new_page()
    seen = forbid_native_dialogs(page)
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(
        f"() => {{ const c = {DATA_JS}; return c.selected && c.selected.quote_no === '{NO}'"
        f" && c.caseUpdates.length && c.completionNotes.length"
        f"{' && c.shippingNotes.length' if _supply_installed() else ''} }}", timeout=20000)
    for label, js in _actions():
        n0 = len(seen)
        page.evaluate(f"() => {{ const c = {DATA_JS}; {js} }}")
        # 等「原生對話框被記下」或「MotrixUI 確認框出現」其中一個
        end = time.time() + 5
        while time.time() < end:
            if len(seen) > n0:
                native_by_action[label] = seen[n0:]
                break
            dlg = page.locator(DIALOG)
            if dlg.count() and dlg.first.is_visible():
                dlg.first.locator('[data-testid="ui-dialog-cancel"]').click()
                dlg.first.wait_for(state="detached", timeout=5000)
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail(f"「{label}」既沒有原生對話框、也沒有出現確認框——操作沒有先問就執行了？")
        page.wait_for_timeout(300)
    assert _counts() == before, "按了取消，資料卻被刪了"
    assert not native_by_action, "仍有原生對話框：" + json.dumps(native_by_action, ensure_ascii=False)
