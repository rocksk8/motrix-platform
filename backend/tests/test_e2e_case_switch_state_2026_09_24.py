"""切換案件後的狀態＝直接開那一件的狀態（CM12 P2，2026-09-24）。

selectCase 的案件層級重設集中到各模組的 _reset_<模組>(phase, data) 之後，守的是「沒有漏重設」：
先開 A（有資料的案件）、動一些檢視狀態，再切到 B；與「新開頁面直接開 B」相比，
頁面資料物件上所有非函式的欄位必須相同（清單／工作階段等與案件無關的欄位除外）。
漏重設的欄位會帶著 A 的值出現在差異裡。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

A = "MQ-SW-A"
B = "MQ-SW-B"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"

# 與「目前開哪一件案件」無關的欄位：清單、工作階段、計時器與序號、全域設定
GLOBAL_KEYS = {
    "isMobileView", "session", "loading", "cases", "filteredCases", "caseSortPref", "listTab", "caseViewMode",
    "gateMatrix", "gmLoaded", "gmSort", "gmFilter", "gmDue", "today", "gateHeads", "locations", "stageBoardItems",
    "search", "unreadOnly", "readAt", "caseActivity", "selectableUsers", "vendors", "contractorRoster",
    "casePageSize", "caseQuick", "quickFilterDefs", "caseTotal", "caseCounts", "caseLoadingMore", "batchMode",
    "batchSel", "batchExec", "batchMember", "batchBusy", "batchMsg", "t100BankAccounts", "t100DefaultBankAcctCode",
    "_casesSeq", "_searchTimer", "_selectSeq", "_autoSaveTimer", "_saveToastTimer", "_initDone", "_readAtLocal",
    "_caseSortable", "_subSortables", "_ptCache", "_partsOptions", "saveToast", "savedFlash", "_pendingUrlTab",
    "_saveRun", "_saveAgain", "headerMoreOpen", "_moReqFor", "_xeReqFor", "_cnReqFor", "feedCalYear",
    "feedCalMonth", "newCommentLogDate", "newCommentUserId", "_SVG_STYLE_PROPS", "ganttView",
}

SNAP_JS = f"""() => {{
  // ⚠ Alpine.$data 回的是合併代理：Object.keys／getOwnPropertyDescriptors 在它上面都是空的
  //    （快照永遠是空的、題永遠綠）⇒ 讀資料堆疊本體（反應式物件本身）
  const c = document.querySelector('[x-data]')._x_dataStack[0], out = {{}}
  for (const k of Object.keys(c)) {{
    if (k.startsWith('$')) continue
    let v
    try {{ v = c[k] }} catch (e) {{ continue }}
    if (typeof v === 'function') continue
    try {{ out[k] = JSON.parse(JSON.stringify(v ?? null)) }} catch (e) {{ out[k] = '<unserializable>' }}
  }}
  return out
}}"""


def _seed():
    import db
    conn = db.get_db()
    try:
        for no, cust, with_data in ((A, "甲客戶", True), (B, "乙客戶", False)):
            sid = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?)", (no, "施工", 0, 0, T0, T0)).lastrowid
            cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": False, "note": ""}]},
                  "stages": [{"id": sid, "label": "施工", "done": False}]}
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", cust, "專案", 1000, 952,
                 json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), T0, T0, "已成案",
                 "2026-03-01"))
            if with_data:
                conn.execute(
                    "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    ("SN-SW-A", no, "草稿", cust, "[]", "{}", T0, T0))
                conn.execute("INSERT INTO case_updates (quote_no, author, content, type, created_at) VALUES (?,?,?,?,?)",
                             (no, "別人", "A 的動態", "comment", "2026-03-02 10:00:00"))
                conn.execute(
                    "INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, status,"
                    " expense_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (no, "運費", "A 的支出", 100, "待審核", "2026-03-02", T0, T0))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user):
    page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token && !{DATA_JS}.loading",
                           timeout=20000)
    return page


def _select(page, no):
    page.evaluate(f"async () => {{ await {DATA_JS}.selectCase('{no}') }}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{no}'", timeout=10000)
    page.wait_for_timeout(1500)          # 背景子載入（出貨／動態／額外支出…）回來


@pytest.mark.e2e
def test_state_after_switching_equals_state_after_fresh_open(live_server, make_user, e2e_browser):
    u = make_user(username="sw_admin", role="admin")
    _seed()
    browser = e2e_browser
    fresh = _open(browser, live_server, u)
    _select(fresh, B)
    want = fresh.evaluate(SNAP_JS)

    page = _open(browser, live_server, u)
    _select(page, A)
    # 在 A 上動一些案件層級的檢視狀態
    for tab in ("exec", "shipping", "feed", "fin", "xexp"):
        page.evaluate(f"() => {{ const c = {DATA_JS}; c.activeTab = '{tab}'; c.ensureTabData && c.ensureTabData('{tab}') }}")
        page.wait_for_timeout(300)
    page.evaluate(f"""() => {{ const c = {DATA_JS}; c.execSubTab = 'devices'; c.stageView = 'timeline';
        c.showLog = true; c.finShowRecvDetail = true; c.finShowPayDetail = true; c.newComment = '打到一半';
        c._openDevGroups = {{ x: true }}; c._shippingLogOpen = {{ y: true }} }}""")
    _select(page, B)
    got = page.evaluate(SNAP_JS)
    assert len(want) > 150 and len(got) > 150, (len(want), len(got))   # 快照不可以是空的
    keys = (set(want) | set(got)) - GLOBAL_KEYS
    diff = {k: (got.get(k), want.get(k)) for k in sorted(keys) if got.get(k) != want.get(k)}
    assert not diff, "切換後殘留前一件的狀態（切換後, 直接開）：" + json.dumps(diff, ensure_ascii=False)[:3000]
