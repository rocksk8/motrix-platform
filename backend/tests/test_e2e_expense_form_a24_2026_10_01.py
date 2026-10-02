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
            if "TRAVEL" in sel.first.evaluate("e => Array.from(e.options).map(o => o.value)"):      # 類別清單是空的時沒有可選項
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
    page.wait_for_selector("#pr-typed-form", state="hidden", timeout=5000)


@pytest.mark.e2e
def test_my_requests_document_buttons(live_server, make_user, new_context, client):
    """我的請款：類型單據才有「預覽單據／PDF」鈕（舊額外支出沒有）；按下去開新分頁、內容是自己的單據；別人的看不到（端點 404、列表不出現）。"""
    _seed()
    adm = make_user(username="a24_doc_adm", role="admin")
    mgr = make_user(username="a24_doc_mgr", role="admin")
    oth = make_user(username="a24_doc_oth", role="sales")
    _join_dept(adm[0], mgr[0])
    ctx = new_context()
    page = ctx.new_page()
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "petty_cash")
    _fill(page)
    page.click("#pr-t-save-draft")
    _wait_done(page)
    row = _q("SELECT id, doc_code FROM case_extra_expenses WHERE kind='petty_cash' ORDER BY id DESC LIMIT 1")[0]
    # 舊流程的一筆（沒有 kind）
    _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, status, created_by, created_by_name,"
       " created_at, updated_at) VALUES ('', '其他', '舊式', 1, '', 10, 10, '草稿', ?, ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
       (adm[0], adm[0]))
    legacy = _q("SELECT id FROM case_extra_expenses WHERE description='舊式'")[0]["id"]

    page.click("#pr-tab-mine")
    page.wait_for_selector("#pr-mine[data-loaded='1']", timeout=15000)
    assert page.locator('[data-doc-html="%d"]' % row["id"]).count() == 1
    assert page.locator('[data-doc-pdf="%d"]' % row["id"]).count() == 1
    assert page.locator('[data-payreq-row="%d"]' % legacy).count() == 1                       # 舊列有列出…
    assert page.locator('[data-doc-actions="%d"]' % legacy).count() == 0                       # …但沒有單據鈕

    with ctx.expect_page() as pop:
        page.click('[data-doc-html="%d"]' % row["id"])
    doc = pop.value
    doc.wait_for_load_state()
    doc.wait_for_function("(c) => document.body && document.body.innerText.includes(c)", arg=row["doc_code"], timeout=15000)
    assert "尚未核可" in doc.inner_text("body")                                                # 草稿：未核可標示
    _shot(doc, "document-petty_cash-draft")
    doc.close()

    with ctx.expect_page() as pop2:
        page.click('[data-doc-pdf="%d"]' % row["id"])
    pdf = pop2.value
    pdf.wait_for_load_state()
    assert not page.locator("#pr-mine-error").is_visible()
    pdf.close()

    # 別人：端點 404、自己的列表看不到
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": oth[0], "password": oth[1]}).json()["token"]}
    assert client.get("/api/quotations/-/extra-expenses/%d/document" % row["id"], headers=h).status_code == 404
    p2 = new_context().new_page()
    inject_login(p2, live_server, oth[0], oth[1])
    p2.goto(live_server + "/pages/payment-request.html?tab=mine")
    p2.wait_for_selector("#pr-mine[data-loaded='1']", timeout=15000)
    assert p2.locator('[data-doc-actions="%d"]' % row["id"]).count() == 0


@pytest.mark.e2e
def test_form_shows_a_published_edit_of_a_default_type(live_server, make_user, new_context, client):
    """超級管理員改預設類型（差旅：加一個欄位）→ 發布 v1 → 請款表單立刻依新定義渲染該欄位；送出的單據釘 v1、欄位值存進 data_json。
    發布前先開的一張單（v0）不受影響。"""
    _seed()
    su = make_user(username="a24_ui_su", role="superadmin")
    emp = make_user(username="a24_ui_emp", role="admin")
    mgr = make_user(username="a24_ui_mgr", role="admin")
    _join_dept(emp[0], mgr[0])

    def tok(u):
        return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    # 發布前：表單沒有這個欄位
    page = new_context().new_page()
    inject_login(page, live_server, emp[0], emp[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "travel")
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    assert page.locator('#pr-df [data-field="trip_purpose"]').count() == 0
    # 超級管理員改定義：加「出差事由」欄位（放進第一組版面）→ 草稿 → 驗證 → 發布
    h = tok(su)
    body = client.get("/api/expense-types/travel", headers=h).json()["definition"]
    body["fields"].insert(len(body["fields"]) - 1, {"key": "trip_purpose", "label": "出差事由（測試新增）", "type": "text", "required": True, "maxLength": 100})
    body["ui"]["form"]["groups"][0]["fields"].append("trip_purpose")
    assert client.post("/api/definitions/expense_type/travel/validate", headers=h, json={"body": body}).json()["problems"] == []
    assert client.put("/api/definitions/expense_type/travel/draft", headers=h, json={"body": body}).status_code == 200
    pub = client.post("/api/definitions/expense_type/travel/publish", headers=h, json={"note": "加出差事由"})
    assert pub.status_code == 200 and pub.json()["version"] == 1, pub.text
    # 發布後：重新選類型 ⇒ 表單依新定義渲染（含必填標示）；不填就送會被前端擋
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "travel")
    page.wait_for_selector('#pr-df [data-field="trip_purpose"]', timeout=15000)
    assert "出差事由（測試新增）" in page.inner_text('#pr-df [data-field="trip_purpose"] label')
    assert page.locator('#pr-df [data-field="trip_purpose"] .req').count() == 1
    _fill(page)                                                   # _fill 會填 trip_purpose（文字欄預設填「測試<key>」）
    page.fill('#pr-df [data-field="trip_purpose"] input', "客戶現場安裝")
    _shot(page, "form-travel-edited-definition")
    page.click("#pr-t-submit")
    _wait_done(page)
    row = _q("SELECT def_version, data_json, status FROM case_extra_expenses WHERE kind='travel' ORDER BY id DESC LIMIT 1")[0]
    assert row["def_version"] == 1 and json.loads(row["data_json"])["trip_purpose"] == "客戶現場安裝"
    # 必填：清空後送審被前端擋下（沒有新增單據）
    n0 = _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='travel'")[0]["n"]
    _fill(page)                                                   # 送出後表單重新渲染成空白 ⇒ 重填，再只清掉必填的新欄位
    page.fill('#pr-df [data-field="trip_purpose"] input', "")
    page.click("#pr-t-save-draft")
    page.wait_for_selector("#pr-t-error", state="visible")
    assert "出差事由" in page.locator("#pr-t-error").text_content()
    assert _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='travel'")[0]["n"] == n0


def _clear_categories():
    _x("DELETE FROM expense_categories")


@pytest.mark.e2e
def test_empty_category_list_means_not_configured_and_does_not_block(live_server, make_user, new_context):
    """使用者裁示（選項 A）：費用類別清單是空的＝「尚未設定」，不擋人——表單顯示一行說明、類別欄不必填，草稿與送審都放行、金額照算；
    後端同樣放行（空清單不驗證）。反向控制見 test_with_categories_the_category_is_required_again。"""
    _seed()
    _clear_categories()
    adm = make_user(username="a24_ec_adm", role="admin")
    mgr = make_user(username="a24_ec_mgr", role="admin")
    _join_dept(adm[0], mgr[0])
    page = new_context().new_page()
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "petty_cash")
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    hint = page.locator("[data-empty-cat-hint]")
    assert hint.count() == 1 and hint.inner_text() == "尚未設定費用類別，入帳將列預設費用科目；請會計主管至「報表設定」新增類別"
    _fill(page)
    shown = int(page.locator("[data-lines-total]").text_content().replace(",", ""))
    assert shown > 0
    _shot(page, "empty-categories-form")
    page.click("#pr-t-save-draft")                                   # 草稿放行
    _wait_done(page)
    d = _q("SELECT status, total_cost, lines_json FROM case_extra_expenses WHERE kind='petty_cash' ORDER BY id DESC LIMIT 1")[0]
    assert d["status"] == "草稿" and int(d["total_cost"]) == shown
    _fill(page)                                                      # 表單送出後重新渲染 ⇒ 再填一張，這次送審
    page.click("#pr-t-submit")
    page.wait_for_function("() => document.getElementById('pr-result').innerText.includes('已送審') || "
                           "(document.getElementById('pr-t-error').offsetParent !== null && document.getElementById('pr-t-error').innerText.trim())",
                           timeout=20000)                        # 上一張草稿的成功訊息還在畫面上 ⇒ 要等「這一次」的結果
    assert not page.locator("#pr-t-error").is_visible(), page.locator("#pr-t-error").text_content()
    s2 = _q("SELECT status, total_cost, lines_json FROM case_extra_expenses WHERE kind='petty_cash' ORDER BY id DESC LIMIT 1")[0]
    assert s2["status"] != "草稿" and int(s2["total_cost"]) == shown, s2          # 送審成功、合計對
    assert [l.get("category", "") for l in json.loads(s2["lines_json"])] == [""]       # 沒有類別就是沒有類別（不編造、不丟列）


@pytest.mark.e2e
def test_with_categories_the_category_is_required_again(live_server, make_user, new_context):
    """反向控制：一有 ≥1 個啟用類別，費用類別恢復必填（前端擋下、沒有說明那一行、不新增單據）。"""
    _seed()
    adm = make_user(username="a24_ec2_adm", role="admin")
    mgr = make_user(username="a24_ec2_mgr", role="admin")
    _join_dept(adm[0], mgr[0])
    page = new_context().new_page()
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "petty_cash")
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    assert page.locator("[data-empty-cat-hint]").count() == 0
    _fill(page)
    n0 = _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='petty_cash'")[0]["n"]
    page.locator('#pr-df [data-table="lines"] tbody tr').first.locator('td[data-col="category"] select').select_option("")
    page.click("#pr-t-save-draft")
    page.wait_for_selector("#pr-t-error", state="visible")
    assert "費用類別必填" in page.locator("#pr-t-error").text_content()
    assert _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE kind='petty_cash'")[0]["n"] == n0


@pytest.mark.e2e
def test_category_list_that_failed_to_load_is_not_treated_as_empty(live_server, make_user, new_context):
    """抓不到類別清單（例如該使用者被擋）≠ 空清單：維持必填（失敗要往嚴格那邊倒）。"""
    _seed()
    adm = make_user(username="a24_ec3_adm", role="admin")
    mgr = make_user(username="a24_ec3_mgr", role="admin")
    _join_dept(adm[0], mgr[0])
    page = new_context().new_page()
    inject_login(page, live_server, adm[0], adm[1])
    page.route("**/api/expense-categories", lambda r: r.fulfill(status=403, body='{"detail":"x"}', content_type="application/json"))
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", "petty_cash")
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    assert page.locator("[data-empty-cat-hint]").count() == 0
    _fill(page)
    page.click("#pr-t-save-draft")
    page.wait_for_selector("#pr-t-error", state="visible")
    assert "費用類別必填" in page.locator("#pr-t-error").text_content()
