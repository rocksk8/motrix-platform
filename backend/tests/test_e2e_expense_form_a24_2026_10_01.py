# -*- coding: utf-8 -*-
"""A2-4：新增請款的「類型」動態表單（static/definition-form.js ＋ payment-request.html）。

四個預設類型（請購／採購／差旅／零用金）各開一張：畫面依定義渲染、明細金額即時算、送審後 DB 的 kind／doc_code／data／lines
都對；另驗「綁案件」與「不綁案件」兩條路、必填擋在前端（不打 API）、鎖定欄位（申請人）唯讀、舊的「一般」流程沒被動到。
觀測點＝畫面（DOM）＋資料庫（case_extra_expenses）。截圖預設寫到暫存目錄，要留存時設 MOTRIX_SHOTS_DIR。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "請款＝M01 額外支出"), requires_module("accounting", "費用類別下拉（W4 G2）")]

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "a24-shots")) / "wip-w1-a2-4"
NO = "MQ-A24-001"
PREFIX = {"purchase_req": "PR", "purchase_order": "PO", "travel": "TE", "petty_cash": "PC"}


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=True)
    except Exception:                                            # noqa: BLE001 — 截圖失敗不影響判定
        pass


def _seed():
    for code, name in (("TRAVEL", "差旅"), ("OFFICE", "辦公用品")):
        _x("INSERT OR IGNORE INTO expense_categories (code, name, default_tax, active, sort, note) VALUES (?,?,?,?,?,?)",
           (code, name, "", 1, 0, ""))
    _x("INSERT OR IGNORE INTO divisions (id, name, sort_order, created_at) VALUES (1, '營運處', 0, '2026-01-01T00:00:00')")
    _x("INSERT OR IGNORE INTO departments (id, division_id, name, sort_order, created_at) VALUES (1, 1, '工程部', 0, '2026-01-01T00:00:00')")
    assert _q("SELECT COUNT(*) AS n FROM departments")[0]["n"] >= 1       # OR IGNORE 也會吞 NOT NULL 違規 ⇒ 證明真的有列


def _join_dept(username, mgr_username):
    """送審的簽核鏈＝部門主管 → 最高管理者：申請人要有部門、部門要有主管。"""
    mid = _q("SELECT id FROM users WHERE username=?", (mgr_username,))[0]["id"]
    _x("UPDATE departments SET manager_user_id=? WHERE id=1", (mid,))
    _x("UPDATE users SET department_id=1 WHERE username=?", (username,))


def _fill(page):
    """依畫面上實際渲染出的欄位填一張最小可送審的單：不寫死某類型的欄位。"""
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    for f in page.locator("#pr-df [data-field]").all():
        key = f.get_attribute("data-field")
        if key == "lines":
            continue
        inp = f.locator("input:not([type=radio]):not([disabled]), select:not([disabled]), textarea:not([disabled])")
        if f.locator("[data-range]").count():
            f.locator("[data-range] input").nth(0).fill("2031-07-01")
            f.locator("[data-range] input").nth(1).fill("2031-07-03")
            continue
        if f.locator("[data-radio]").count():
            if not f.locator("[data-radio] input:checked").count():
                f.locator("[data-radio] input").first.check()
            continue
        if not inp.count():
            continue
        el = inp.first
        tag = el.evaluate("e => e.tagName")
        typ = el.get_attribute("type") or ""
        if tag == "SELECT":
            if not el.input_value():
                vals = el.evaluate("e => Array.from(e.options).map(o => o.value).filter(Boolean)")
                if vals:
                    el.select_option(vals[0])
        elif typ == "date":
            if not el.input_value():
                el.fill("2031-07-03")
        elif typ == "number":
            if not el.input_value():
                el.fill("1")
        elif not el.input_value():
            el.fill("測試" + key)
    row = page.locator('#pr-df [data-table="lines"] tbody tr').first
    for c in row.locator("td[data-col]").all():
        col = c.get_attribute("data-col")
        sel = c.locator("select")
        if sel.count():
            sel.first.select_option("TRAVEL")
        elif col == "qty":
            c.locator("input").fill("3")
        elif col == "unitCost":
            c.locator("input").fill("33.5")
        elif col == "amount" and not c.locator("[data-calc]").count():
            c.locator("input").fill("100")
        elif col in ("summary", "invoiceNo") or c.locator("input[type=text]").count():
            c.locator("input").fill("品項" + col)


def _wait_done(page):
    """等到成功訊息或錯誤訊息其一出現；錯誤出現就把內容放進失敗訊息（不要只看到逾時）。"""
    page.wait_for_function("() => { const r = document.getElementById('pr-result'); const e = document.getElementById('pr-t-error');"
                           " return (r && r.offsetParent !== null) || (e && e.offsetParent !== null && e.textContent.trim()) }", timeout=20000)
    assert not (page.locator("#pr-t-error").is_visible() and page.locator("#pr-t-error").text_content().strip()),         page.locator("#pr-t-error").text_content()


@pytest.mark.e2e
@pytest.mark.parametrize("kind", ["purchase_req", "purchase_order", "travel", "petty_cash"])
def test_typed_form_no_case(live_server, make_user, new_context, kind):
    """不綁案件：管理員開單 ⇒ 前端算的合計＝後端存的 total_cost；單號前綴對；明細保留代碼＋名稱快照。"""
    _seed()
    adm = make_user(username="a24_adm_" + kind, role="admin")
    mgr = make_user(username="a24_mgr_" + kind, role="admin")
    _join_dept(adm[0], mgr[0])
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", kind)
    _fill(page)
    shown = page.locator("[data-lines-total]").text_content().replace(",", "")
    assert int(shown) > 0
    _shot(page, "form-" + kind)

    page.click("#pr-t-submit")
    _wait_done(page)
    row = _q("SELECT * FROM case_extra_expenses WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))[0]
    assert row["quote_no"] == "" and row["doc_code"].startswith(PREFIX[kind] + "-")
    assert int(row["total_cost"]) == int(shown)
    lines = json.loads(row["lines_json"])
    assert lines and lines[0]["categoryCode"] == "TRAVEL" and lines[0]["categoryName"] == "差旅"
    assert json.loads(row["data_json"]).get("applicant") == adm[0]          # 鎖定欄位以登入者預填
    assert row["status"] != "草稿"
    assert not errors, errors


@pytest.mark.e2e
def test_typed_form_with_case_and_front_validation(live_server, make_user, new_context):
    """綁案件（選填）＋必填擋在前端（沒打 API）＋申請人欄位鎖定。"""
    _seed()
    eng = make_user(username="a24_eng", role="sales")
    eng_id = _q("SELECT id FROM users WHERE username=?", (eng[0],))[0]["id"]
    _join_dept(eng[0], make_user(username="a24_mgr2", role="admin")[0])
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "A24客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
    page = new_context().new_page()
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "travel")
    page.wait_for_selector("#pr-df .df-root")
    assert page.locator('#pr-df [data-field="applicant"] select').is_disabled()          # locked
    n0 = _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='travel'")[0]["n"]
    page.click("#pr-t-save-draft")                                                        # 空表單：前端擋
    page.wait_for_selector("#pr-t-error", state="visible")
    assert "必填" in page.locator("#pr-t-error").text_content()
    assert _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='travel'")[0]["n"] == n0
    _shot(page, "validation-travel")

    page.fill("#pr-case-q", "MQ-A24")
    page.click('[data-case-pick="%s"]' % NO)
    _fill(page)
    page.click("#pr-t-save-draft")
    _wait_done(page)
    row = _q("SELECT * FROM case_extra_expenses WHERE kind='travel' ORDER BY id DESC LIMIT 1")[0]
    assert row["quote_no"] == NO and row["status"] == "草稿" and row["created_by"] == eng[0]
    _shot(page, "case-travel-draft")


@pytest.mark.e2e
def test_general_flow_unchanged(live_server, make_user, new_context):
    """選「一般」＝舊流程：舊表單顯示、類型表單隱藏。"""
    _seed()
    eng = make_user(username="a24_gen", role="sales")
    page = new_context().new_page()
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    assert page.input_value("#pr-type") == ""
    assert not page.locator("#pr-typed-form").is_visible()
    page.select_option("#pr-type", "petty_cash")
    page.wait_for_selector("#pr-typed-form", state="visible")
    page.select_option("#pr-type", "")
    assert not page.locator("#pr-typed-form").is_visible()
