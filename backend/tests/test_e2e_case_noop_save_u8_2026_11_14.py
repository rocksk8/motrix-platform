"""U8（2026-11-14）案件頁「儲存」：沒有變動就不送出、說清楚「已是最新」；稽核頁顯示這筆改了哪些分段。
觀測點：網路請求（有沒有 PATCH case-record）、按鈕字樣與提示、稽核頁的「改動：…」行。"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
pytestmark = requires_module("case", "打 M01（案件）的端點或讀寫 M01 的資料")

NO = "MQ-202611-802"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": False, "receivedAt": "", "note": ""}]},
              "stages": []}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _rows():
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE action='case.update' AND target_id=? ORDER BY id", (NO,)).fetchall()]
    finally:
        conn.close()


@pytest.mark.e2e
def test_save_without_changes_sends_nothing_and_says_up_to_date(live_server, make_user, e2e_browser):
    u = make_user(username="u8e2e", role="finance")
    _seed()
    page = e2e_browser.new_context().new_page()
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" and r.url.endswith("/case-record") else None)
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    btn = page.locator(".cm-header .btn-save")
    page.wait_for_function("() => document.querySelector('.cm-header .btn-save').classList.contains('is-clean')", timeout=5000)
    assert btn.inner_text().strip() == "已是最新"
    toast = page.locator("[data-testid=save-toast]")
    for _ in range(3):                                               # 連按三次
        btn.click()
        toast.wait_for(state="visible", timeout=5000)
        assert "已是最新" in toast.inner_text()
        toast.wait_for(state="hidden", timeout=6000)
    assert patches == [], f"沒有變動不該送出 PATCH：{patches}"
    assert _rows() == []
    # 改一個欄位 ⇒ 按鈕回到「儲存」；按下去才送、才留一筆
    page.evaluate(f"() => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].note = '改了'; c.setDirty() }}")
    page.wait_for_function("() => !document.querySelector('.cm-header .btn-save').classList.contains('is-clean')", timeout=3000)
    assert btn.inner_text().strip() == "儲存"
    btn.click()
    page.wait_for_function("() => document.querySelector('.cm-header .btn-save').classList.contains('is-clean')", timeout=10000)
    assert len(patches) == 1
    rows = _rows()
    assert len(rows) == 1 and json.loads(rows[0]["detail"])["segments"] == ["payment"]


@pytest.mark.e2e
def test_audit_page_shows_changed_segments(live_server, make_user, e2e_browser):
    u, p = make_user(username="u8_sa", role="superadmin", modules=[])
    _seed()
    from helpers.audit import _audit
    _audit("", "case.update", "quotation", NO, f"{NO}（客戶／專案）", {"segments": ["contract", "payment", "someNewSeg"], "fields": {"contract": ["terms"]}})
    _audit("", "case.update", "quotation", NO, f"{NO}（客戶／專案）", {"segments": [], "initial": ["roles"]})
    _audit("", "case.update", "quotation", NO, f"{NO}（客戶／專案）")          # 舊紀錄：detail 空 ⇒ 不顯示「改動」行
    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u, p)
    page.goto(live_server + "/pages/audit-log.html")
    page.wait_for_function("() => document.querySelectorAll('.tl-item').length >= 3", timeout=20000)
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=audit-changed]')].some(e => e.offsetParent !== null)", timeout=5000)
    shown = page.evaluate("() => [...document.querySelectorAll('[data-testid=audit-changed]')].filter(e => e.offsetParent !== null).map(e => e.innerText)")
    # 只列分段中文名（欄位名是內部鍵不上畫面；未知分段 ⇒ 「其他欄位」）；補預設值 ⇒ 「初次建立預設內容」
    assert sorted(shown) == sorted(["改動：合約資訊、收款、其他欄位", "初次建立預設內容"]), shown
    assert not errors, errors
