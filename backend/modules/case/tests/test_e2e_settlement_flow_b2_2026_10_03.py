# -*- coding: utf-8 -*-
"""33-B2 精算 e2e（c7；同時是對 2e 的 B1 頁面的獨立覆核）：連續流程＋歷史不變＋完結凍結。
- 連續流程（真的在畫面操作）：請購→採購單核准（API）＋材料申請（連採購單／連品項／沒連）＋額外支出 → 精算頁數字＝後端單一來源 →
  未對應材料申請沖銷到品項 → 存草稿 → 完結 → 資料庫、營運報表、總帳的採購類金額在完結前後逐位相同（完結不產生任何金額）
- 完結凍結：完結後新核准一張採購單 ⇒ 重新開頁，數字仍是完結當時的、儲存的精算資料原樣不動、頁面沒有存檔／完結按鈕
- 完結重算 409：頁面開著時採購單被核准（頁面數字過期）⇒ 按完結被後端擋下、不存檔、畫面仍是草稿；重新整理後可完結
- 歷史案件：舊格式已完結精算（沒有 offsets／adoptSystem）開頁不改任何資料、數字＝儲存的品項實際成本
headless；等待一律等終點（資料庫狀態／頁面狀態），不用 sleep。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-B2-1"
ITEMS = [{"id": "a", "description": "交換器", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
         {"id": "b", "description": "線材", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5}]
S = "Alpine.$data(document.body)"
FINALIZE_BTN = '[data-testid="stl-finalize"]'


def _order(item_id, total, **kw):
    d = {"itemId": item_id, "itemName": "料" + item_id, "quantity": 1, "unit": "批", "unitPrice": total, "totalPrice": total,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "invoiceDate": "2026-10-02"}
    d.update(kw)
    return d


def _seed_case(orders=(), approvals=("已核准",), extra=700, settlement=None, quote_no=NO):
    import db
    c = db.get_db()
    try:
        data = {"items": ITEMS, "dealTag": "已成案", "caseRecord": {"materialOrders": list(orders)}}
        if settlement is not None:
            data["settlement"] = settlement
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (quote_no, "已送出", "客", "案", 21000, 21000, json.dumps(data), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "b2_sa"))
        for o in orders:
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (quote_no, o["itemId"], approvals[0]))
        if extra:
            c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                      "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                      (quote_no, "其他", "雜支", 1, "式", extra, extra, "", "2026-10-02", "", "b2_sa", "b2_sa", "b2_sa", "b2_sa",
                       "2026-10-02T00:00:00", "2026-10-02T00:00:00", "b2_sa", "已核准"))
        c.commit()
    finally:
        c.close()


def _approved_po(page, base, qty, cost, item_id="a", quote_no=NO):
    """用 API 開一張採購單並送審（flow 沒設簽核層＝送審即核准）。回 docCode。"""
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    sess = json.loads(page.evaluate("() => localStorage.getItem('motrix_session')"))
    h = {"Authorization": "Bearer " + sess["token"]}
    r = page.context.request.post("%s/api/quotations/%s/extra-expenses" % (base, quote_no), headers=h, data={
        "kind": "purchase_order", "lines": [{"category": "雜項", "summary": "採購單品項", "qty": qty, "unit": "台", "unitCost": cost, "itemId": item_id}],
        "payeeName": "某人", "payeeType": "employee", "data": {"applicant": "b2_sa"}})
    assert r.status == 201, r.text()
    s = page.context.request.post("%s/api/quotations/%s/extra-expenses/%s/submit" % (base, quote_no, r.json()["id"]), headers=h)
    assert s.status == 200, s.text()
    return r.json()["docCode"]


def _api_totals(page, base, quote_no=NO):
    sess = json.loads(page.evaluate("() => localStorage.getItem('motrix_session')"))
    r = page.context.request.get("%s/api/quotations/%s/settlement-actuals" % (base, quote_no), headers={"Authorization": "Bearer " + sess["token"]})
    assert r.status == 200, r.text()
    return r.json()["totals"]


def _settlement_raw(quote_no=NO):
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()["data_json"]).get("settlement")
    finally:
        c.close()


def _money(quote_no=NO):
    """營運報表（材料申請＋額外支出）與總帳（E11＋E12 應付貸方）的採購類金額——完結前後必須逐位相同。"""
    import db
    from modules.case import gl_events as GE
    from modules.case import recognition as R
    cn = db.get_db()
    try:
        rep = sum(e["amount"] for e in R.material_entries(cn, "accrual") if e["quoteNo"] == quote_no) \
            + sum(e["amount"] for e in R.extra_entries(cn, "accrual") if e["quoteNo"] == quote_no)
    finally:
        cn.close()
    gl = 0
    for e in GE.gl_events("2000-01-01", "2099-12-31")["events"]:
        if e["event_code"] in ("E11", "E12") and e["case_no"] == quote_no:
            gl += sum(l["amount"] for l in e["lines"] if l["role"] == "AP" and l["side"] == "C")
    return rep, gl


def _open(live_server, make_user, new_context, quote_no=NO):
    sa = make_user(username="b2_sa", role="superadmin")
    page = new_context(viewport={"width": 1400, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, *sa)
    page.errors = errors
    return page


def _goto(page, live_server, quote_no=NO, wait='[data-testid="stl-unassigned"]'):
    page.goto("%s/pages/settlement.html?no=%s" % (live_server, quote_no))
    page.locator(wait).wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => !%s.loading" % S, timeout=20000)


def _finalize_via_ui(page):
    page.locator(FINALIZE_BTN).click()
    page.locator('button:has-text("確認完結")').click()


@pytest.mark.e2e
def test_continuous_flow_page_equals_backend_offsets_save_finalize_money_unchanged_then_frozen(live_server, make_user, new_context):
    _seed_case([_order("X", 250), _order("N", 800, quoteItemId="b")], approvals=("已核准",))
    page = _open(live_server, make_user, new_context)
    _goto(page, live_server)                                                                  # 先進頁面取得登入，再用 API 開採購單
    doc = _approved_po(page, live_server, 3, 1000)
    page.reload()
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)

    # 1 頁面數字＝後端單一來源（採購單核准＋連品項材料申請＋未對應材料申請與額外支出）
    api = _api_totals(page, live_server)
    summ = page.evaluate("() => ({...%s.summary})" % S)
    assert summ["itemActualTotal"] == api["itemActualTotal"] and summ["purchasedTotal"] == api["purchasedTotal"], (summ, api)
    assert summ["extraTotal"] == api["extraTotal"] + api["materialUnassignedTotal"], (summ, api)
    assert "已採用" in page.locator('[data-testid="stl-po-a"]').inner_text(), doc
    rep0, gl0 = _money()
    assert api["purchasedTotal"] == rep0, "精算 ≠ 營運報表"

    # 2 沖銷：未對應材料申請 X 對應到品項 a ⇒ 採購類總額不變（錢只是從未對應搬到品項）
    page.locator('[data-testid="stl-offset-material-X"]').select_option("a")
    page.wait_for_function("() => %s.summary.extraTotal === %d" % (S, summ["extraTotal"] - 250), timeout=10000)
    assert page.evaluate("() => %s.summary.purchasedTotal" % S) == summ["purchasedTotal"]
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function("() => !%s.saving" % S, timeout=15000)
    assert _settlement_raw()["offsets"] == [{"kind": "material", "ref": "X", "itemId": "a"}]

    # 3 完結：資料庫標完結、完結的摘要＝頁面數字；報表與總帳完結前後逐位相同
    shown = page.evaluate("() => ({...%s.summary})" % S)
    _finalize_via_ui(page)
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.saving" % (S, S), timeout=20000)
    saved = _settlement_raw()
    assert saved["status"] == "finalized" and saved["summary"]["itemActualTotal"] == shown["itemActualTotal"], (saved["summary"], shown)
    assert _money() == (rep0, gl0), "完結不得產生或改變任何金額（報表／總帳）"

    # 4 凍結：完結後又核准一張採購單 ⇒ 重新開頁，數字仍是完結當時的；儲存的精算資料原樣；沒有存檔／完結按鈕
    frozen_raw = json.dumps(_settlement_raw(), sort_keys=True)
    _approved_po(page, live_server, 1, 500)
    page.reload()
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.loading" % (S, S), timeout=20000)
    assert page.evaluate("() => %s.summary.itemActualTotal" % S) == saved["summary"]["itemActualTotal"]
    assert json.dumps(_settlement_raw(), sort_keys=True) == frozen_raw, "開頁不得改動已完結的精算資料"
    assert page.locator('.badge-finalized').is_visible()
    assert page.locator(FINALIZE_BTN).count() == 0 and page.locator('[data-testid="stl-save-draft"]').count() == 0
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_finalize_with_stale_page_numbers_is_refused_then_succeeds_after_reload(live_server, make_user, new_context):
    _seed_case([_order("N", 800, quoteItemId="b")], extra=0)
    page = _open(live_server, make_user, new_context)
    _goto(page, live_server, wait='[data-testid="stl-po-b"]')
    before = page.evaluate("() => ({...%s.summary})" % S)
    _approved_po(page, live_server, 3, 1000)                                                   # 頁面開著時，採購單被核准 ⇒ 頁面數字過期
    _finalize_via_ui(page)
    page.locator('text=完結失敗').first.wait_for(state="visible", timeout=15000)                # 後端 409：不存檔
    page.wait_for_function("() => !%s.saving" % S, timeout=10000)
    assert _settlement_raw() is None
    assert page.evaluate("() => %s.settlement.status" % S) == "draft" and page.locator('.badge-draft').is_visible()
    assert page.evaluate("() => %s.summary.itemActualTotal" % S) == before["itemActualTotal"]   # 畫面沒有被悄悄改
    page.reload()                                                                              # 重新整理 ⇒ 帶入新核准的採購單
    page.wait_for_function("() => !%s.loading" % S, timeout=20000)
    assert page.evaluate("() => %s.summary.itemActualTotal" % S) != before["itemActualTotal"]
    _finalize_via_ui(page)
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.saving" % (S, S), timeout=20000)
    assert _settlement_raw()["status"] == "finalized"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_legacy_finalized_settlement_opens_unchanged_and_nothing_is_written(live_server, make_user, new_context):
    legacy = {"status": "finalized", "finalizedAt": "2026-09-01T00:00:00", "finalizedBy": "舊人員",
              "items": [{"id": "a", "actualTotalCost": 9000}, {"id": "b", "actualTotalCost": 400}],
              "summary": {"itemActualTotal": 9400, "extraTotal": 0}}
    _seed_case([], extra=0, settlement=legacy)
    page = _open(live_server, make_user, new_context)
    _goto(page, live_server, wait='.badge-finalized')
    raw0 = json.dumps(_settlement_raw(), sort_keys=True)
    _approved_po(page, live_server, 3, 1000)                                                   # 之後才核准的採購單不得動到歷史案件
    page.reload()
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.loading" % (S, S), timeout=20000)
    assert page.evaluate("() => %s.summary.itemActualTotal" % S) == 9400                       # 歷史數字＝儲存的品項實際成本
    assert json.dumps(_settlement_raw(), sort_keys=True) == raw0, "開頁不得改動歷史精算資料"
    assert "offsets" not in _settlement_raw()
    assert not page.errors, page.errors
