# -*- coding: utf-8 -*-
"""31-B S3 瀏覽器端對端（一個檔、一個瀏覽器、一題連續流程）：案件頁派發卡片的分期匯款申請。

流程（派發＝已確認、稅前 1000、稅 5%）：
  整筆選項不出現（已確認還不能整筆）→ 開「產生匯款申請」→ 選訂金款、輸入 30% ⇒ 試算顯示稅前 300 稅額 15 → 確認 ⇒ DB 有一張 kind=deposit
  → 卡片顯示「訂金款　第 1 期　稅前 300」與「已申請 稅前 300 ／ 1,000（剩餘 700）」
  → 再開一期：進度款固定金額 800 ⇒ 試算出錯（超過剩餘額度）、確認鈕停用；改 700 ⇒ 最後一期、補到與整筆一致 → 確認
  → 已全部申請完：不再有「新增一期」鈕
  → 兩張都改成待審核（測試直接改列）⇒ 只有最新一張有「作廢」鈕；作廢（原因必填）⇒ DB voided、卡片灰字、額度回復、「新增一期」鈕回來。
  → 第 1 期登錄發票（S4）⇒ 卡片顯示號碼與日期、DB 有值；第 2 期顯示「未登錄發票（尚不認列）」。
終點狀態以後端列為準；每個階段留截圖（logs/e2e-shots/wip-t33-remit-s3-a3）。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-RKS3-1"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t33-remit-s3-a3")


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        c.commit()
        return rows
    finally:
        c.close()


def _seed():
    now = "2026-10-02T00:00:00"
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (NO, "已送出", "分期客", "分期案", 1050, 1000, json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "materials": []}}), now, now, "已成案"))
    _db("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('S3廠商','12345678',?,?)", (now, now))
    vid = _db("SELECT id FROM vendor_contractors WHERE name='S3廠商'")[0]["id"]
    _db("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, tax_rate, items_json, personnel_json, approval_status, created_at, updated_at)"
        " VALUES (?,?,'confirmed',1000,0.05,?,'[]','已核准',?,?)",
        (NO, vid, json.dumps([{"description": "工項", "amount": 1000}], ensure_ascii=False), now, now))
    return _db("SELECT MAX(id) AS i FROM contractor_dispatches")[0]["i"]


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "s3-%s.png" % name), full_page=False)


def _vouchers(did):
    return _db("SELECT voucher_no, kind, seq, pretax_amount, voided_at, void_reason, status FROM contractor_payment_vouchers WHERE dispatch_id=? ORDER BY id", (did,))


def _fill_plan(page, kind_code, mode, value):
    page.select_option('[data-testid="cv-kind-select"]', kind_code)
    page.locator('input[value="%s"]' % mode).check()
    box = page.locator('[data-testid="cv-ratio-input"]' if mode == "ratio" else '[data-testid="cv-amount-input"]')
    box.fill(str(value))


@pytest.mark.e2e
def test_installment_vouchers_create_preview_and_void_in_the_case_page(live_server, make_user, e2e_browser):
    adm = make_user(username="rks3_adm", role="admin")
    did = _seed()
    page = e2e_browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, *adm)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'dispatch' }}")
    page.wait_for_load_state("networkidle")
    page.wait_for_function(f"() => !{DATA_JS}.contractorVouchersLoading && {DATA_JS}.remitKinds.length > 0", timeout=15000)

    # 已確認：能分期、還不能整筆 ⇒ 有「產生匯款申請」鈕；視窗裡沒有「整筆／分期」選項
    btn = page.locator('[data-testid="cv-create-btn"]').first
    btn.wait_for(state="visible", timeout=10000)
    assert "產生匯款申請" in btn.inner_text()
    _shot(page, "1-card")
    btn.click()
    page.wait_for_selector('[data-testid="cv-kind-select"]', state="visible", timeout=10000)
    assert not page.locator('[data-testid="cv-mode-whole"]').is_visible()
    assert page.locator('[data-testid="cv-create-confirm"]').is_disabled()                       # 還沒有有效試算

    # 訂金款 30% ⇒ 試算（後端算）
    _fill_plan(page, "deposit", "ratio", 30)
    page.wait_for_selector('[data-testid="cv-plan-summary"]', state="visible", timeout=8000)
    txt = page.inner_text('[data-testid="cv-plan-summary"]')
    assert "第 1 期" in txt and "稅前 300" in txt and "稅額 15" in txt, txt
    assert page.locator('[data-testid="cv-create-confirm"]').is_enabled()
    _shot(page, "2-preview")
    assert _vouchers(did) == []                                                                   # 試算不寫入
    page.click('[data-testid="cv-create-confirm"]')
    page.wait_for_selector('[data-testid="cv-kind-label"]', state="visible", timeout=10000)
    rows = _vouchers(did)
    assert len(rows) == 1 and rows[0]["kind"] == "deposit" and rows[0]["seq"] == 1 and rows[0]["pretax_amount"] == 300
    assert "訂金款" in page.inner_text('[data-testid="cv-kind-label"]') and "第 1 期" in page.inner_text('[data-testid="cv-kind-label"]')
    assert "已申請 稅前 300" in page.inner_text('[data-testid="cv-progress"]') and "剩餘 700" in page.inner_text('[data-testid="cv-progress"]')
    _shot(page, "3-first-period")

    # 第二期：固定金額 800 超過剩餘 ⇒ 試算出錯、確認鈕停用；改 700 ⇒ 最後一期
    page.locator('[data-testid="cv-create-btn"]').first.click()
    page.wait_for_selector('[data-testid="cv-kind-select"]', state="visible", timeout=10000)
    _fill_plan(page, "progress", "amount", 800)
    page.wait_for_selector('[data-testid="cv-plan-error"]', state="visible", timeout=8000)
    assert "超過剩餘額度" in page.inner_text('[data-testid="cv-plan-error"]')
    assert page.locator('[data-testid="cv-create-confirm"]').is_disabled()
    _shot(page, "4-over-limit")
    _fill_plan(page, "progress", "amount", 700)
    page.wait_for_function("() => document.querySelector('[data-testid=\"cv-plan-summary\"]') && document.querySelector('[data-testid=\"cv-plan-summary\"]').innerText.includes('最後一期')", timeout=8000)
    page.click('[data-testid="cv-create-confirm"]')
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"cv-kind-label\"]').length === 2", timeout=10000)
    rows = _vouchers(did)
    assert [(r["kind"], r["seq"], r["pretax_amount"]) for r in rows] == [("deposit", 1, 300), ("progress", 1, 700)]
    assert "剩餘 0" in page.inner_text('[data-testid="cv-progress"]')
    assert page.locator('[data-testid="cv-create-btn"]').count() == 0                             # 全部申請完：不再能新增
    _shot(page, "5-complete")

    # 發票（S4／D11：可事後補）：第 1 期登錄發票 ⇒ DB 有號碼與日期、卡片顯示；第 2 期還沒有 ⇒ 顯示「未登錄發票」
    assert "未登錄發票" in page.locator('[data-testid="cv-invoice-note"]:visible').nth(0).inner_text()
    page.locator('[data-testid="cv-invoice-btn"]:visible').nth(0).click()
    page.wait_for_selector('[data-testid="ui-dialog-input"]', state="visible", timeout=8000)
    page.fill('[data-testid="ui-dialog-input"]', "AB-12345678")
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_function("() => { const i = document.querySelector('[data-testid=\"ui-dialog-input\"]'); return i && i.offsetParent !== null && i.value === '' }", timeout=8000)
    page.fill('[data-testid="ui-dialog-input"]', "2026-10-05")
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=\"cv-invoice-note\"]')].some(e => e.offsetParent !== null && e.innerText.includes('AB-12345678'))", timeout=10000)
    rows = _db("SELECT kind, inv_no, inv_date FROM contractor_payment_vouchers WHERE dispatch_id=? ORDER BY id", (did,))
    assert [(r["inv_no"], r["inv_date"]) for r in rows] == [("AB-12345678", "2026-10-05"), ("", "")]
    assert "2026-10-05" in page.locator('[data-testid="cv-invoice-note"]:visible').nth(0).inner_text()
    assert "未登錄發票" in page.locator('[data-testid="cv-invoice-note"]:visible').nth(1).inner_text()
    _shot(page, "5b-invoice")

    # 作廢：兩張都送審（直接改列）⇒ 只有最新一張有「作廢」鈕
    _db("UPDATE contractor_payment_vouchers SET status='待審核' WHERE dispatch_id=?", (did,))
    page.evaluate(f"async () => await {DATA_JS}.loadContractorVouchers('{NO}')")
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=\"cv-void-btn\"]')].filter(e => e.offsetParent !== null).length === 1", timeout=10000)
    page.locator('[data-testid="cv-void-btn"]:visible').click()
    page.wait_for_selector('[data-testid="ui-dialog-input"]', state="visible", timeout=8000)
    page.click('[data-testid="ui-dialog-ok"]')                                                    # 沒填原因 ⇒ 擋下重問
    page.wait_for_selector('[data-testid="ui-toast"]', state="visible", timeout=8000)
    assert "作廢要填原因" in page.inner_text('[data-testid="ui-toast"]')
    page.wait_for_function("() => { const i = document.querySelector('[data-testid=\"ui-dialog-input\"]'); return i && i.offsetParent !== null && i.value === '' }", timeout=8000)
    assert [r["voided_at"] for r in _vouchers(did)] == ["", ""]
    page.fill('[data-testid="ui-dialog-input"]', "金額談妥重開")
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_selector('[data-testid="cv-voided-note"]:visible', state="visible", timeout=10000)
    rows = _vouchers(did)
    assert rows[1]["voided_at"] and rows[1]["void_reason"] == "金額談妥重開" and rows[1]["status"] == "已作廢" and rows[0]["voided_at"] == ""
    assert "已作廢：金額談妥重開" in page.inner_text('[data-testid="cv-voided-note"]:visible')
    assert "剩餘 700" in page.inner_text('[data-testid="cv-progress"]')                           # 額度回復
    btn = page.locator('[data-testid="cv-create-btn"]').first
    btn.wait_for(state="visible", timeout=8000)
    assert "新增一期匯款申請" in btn.inner_text()
    assert page.locator('[data-testid="cv-void-btn"]:visible').count() == 1                               # 現在輪到第 1 期是最新一張
    _shot(page, "6-voided")
    assert not errors, errors
