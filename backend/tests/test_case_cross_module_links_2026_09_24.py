"""案件頁的跨模組連結＋結案後留在案件（2026-09-24 使用者表單）。

- 地圖：有交貨地址 ⇒「在地圖上看」（map.html?focus=cases:<單號>，MP6 的案件圖層）
- 獎金分配：bonus.html?q=<單號>（bonus.js 既有深連結）；最高管理者、模組開著才顯示
- 傳票：分錄來源（voucher_lines.source_type／source_key，JV36）指向這個案件、它的額外支出或
  承攬派工的有效傳票 ⇒ GET /api/vouchers/by-case/{no}，連到 voucher.html?id=
- 結案成功後留在案件頁（原本 800ms 後跳保固頁）
沒有該頁權限的人不顯示連結。觀測點：API 回應、連結 href、頁面網址與資料庫 deal_tag。
"""
import json
import threading
import time

import pytest
from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-XLINK-001"
OTHER = "MQ-XLINK-OTHER"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
_DEBIT = {"account_code": "6111", "debit": 5000, "credit": 0}
_CREDIT = {"account_code": "1113", "debit": 0, "credit": 5000}


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(no=NO, *, closable=False, address="台中市西屯區台灣大道三段99號"):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (no, "施工", 0, 1 if closable else 0, now, now))
        cr = {"contract": {"deliveryAddress": address},
              "payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": closable,
                                     "receivedAt": "2026-09-01" if closable else ""}]},
              "stages": [{"id": cur.lastrowid, "label": "施工", "done": closable}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "連結客戶", "連結專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _voucher(client, hdr, source_type="", source_key=""):
    lines = [dict(_DEBIT, summary="來源", source_type=source_type, source_key=source_key), dict(_CREDIT)]
    r = client.post("/api/vouchers", headers=hdr, json={"summary": "xlink", "lines": lines})
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


# ── API ──────────────────────────────────────────────────────────────────


# ── 頁面 ─────────────────────────────────────────────────────────────────


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


@pytest.mark.e2e
def test_case_page_links_to_map_bonus_and_vouchers(live_server, client, make_user, e2e_browser):
    u = make_user(username="xl_e1", role="superadmin")
    hdr = _hdr(client, make_user, "xl_e1_api", modules=["cashier"])
    _seed_case()
    from core import source_tree
    m06 = source_tree.module_installed("modules/accounting/")      # M06 不在（PLAYBOOK §B-11）⇒ 沒有傳票可開、也不該有傳票連結
    vid = _voucher(client, hdr, "case", NO) if m06 else None
    browser = e2e_browser
    page = _open(browser, live_server, u)
    links = page.locator("[data-testid=case-links]")
    first = "[data-testid=case-link-voucher]" if m06 else "[data-testid=case-link-map]"
    links.locator(first).first.wait_for(state="visible", timeout=10000)
    assert links.locator("[data-testid=case-link-map]").get_attribute("href") \
        == "map.html?focus=" + "cases%3A" + NO
    if (source_tree.BACKEND / "modules" / "payroll" / "module.json").is_file():
        assert links.locator("[data-testid=case-link-bonus]").get_attribute("href") == f"bonus.html?q={NO}"
    else:                                   # M07 不在這個安裝包（PLAYBOOK §B-11）⇒ 獎金那一個連結不出現，其餘照常
        assert links.locator("[data-testid=case-link-bonus]").count() == 0
    if m06:
        assert links.locator("[data-testid=case-link-voucher]").get_attribute("href") == f"voucher.html?id={vid}"
    else:                                   # 案件整包的傳票段 404（IP-22 VOUCHERS_UNAVAILABLE）⇒ 不列傳票連結，其餘照常
        assert links.locator("[data-testid=case-link-voucher]").count() == 0


@pytest.mark.e2e
def test_case_page_hides_links_the_user_cannot_open(live_server, make_user, e2e_browser):
    u = make_user(username="xl_e2", role="admin", modules=["case_manage"])
    _seed_case()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.wait_for_timeout(1500)
    for k in ("map", "bonus", "voucher"):
        assert page.locator(f"[data-testid=case-link-{k}]").count() == 0, k


@pytest.mark.e2e
def test_after_closing_the_case_stays_on_the_case_page(live_server, make_user, e2e_browser):
    import db
    u = make_user(username="xl_e3", role="superadmin")
    _seed_case(closable=True)
    browser = e2e_browser
    page = _open(browser, live_server, u)
    # CU5（2026-09-24）：「完結案」收進標頭「更多」選單
    page.click('[data-testid="cm-more"]')
    page.click("button.btn-close-case:not([data-testid])")
    btn = page.locator("[data-testid=close-check] [data-testid=close-confirm]")
    btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.wait_for_function(f"() => {DATA_JS}.cr.dealTag === '已結案'", timeout=10000)
    page.wait_for_timeout(1500)
    assert "case-management.html" in page.url, page.url
    conn = db.get_db()
    try:
        assert conn.execute("SELECT deal_tag FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0] == "已結案"
    finally:
        conn.close()
