# -*- coding: utf-8 -*-
"""瀏覽器端對端（含每個按鈕的動作終點狀態＋截圖）：總帳作業頁的『營業稅 401』『扣繳清單』『來源憑證補登』三個頁籤。

使用者規則 R2（2026-09-30）：每個動到的頁面、每顆按鈕都要有 e2e（驗終點狀態，不驗某一趟請求），並留截圖到 D:\\開發測試檔\\shots\\<分支>\\。
旗標直接寫進資料庫（READY 只擋 API 開關，頁籤內容不受影響）；資料用遠期年份（2183）避免撞到共用庫。
"""
import os
import tempfile
import subprocess
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402
from modules.accounting.ledger import features as F  # noqa: E402


def _shots_dir():
    try:
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10,
                                cwd=os.path.dirname(__file__)).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        branch = "unknown"
    d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), branch.replace("/", "_"))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:  # noqa: BLE001
        return None
    return d


def _shot(page, name):
    d = _shots_dir()
    if d:
        try:
            page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
        except Exception:  # noqa: BLE001  截圖失敗不影響驗證
            pass


def _open(page, base, user, pw):
    bad, errs = [], []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, base, user, pw)
    bad.clear()
    page.goto("%s/pages/ledger-hub.html" % base)
    return bad, errs


def _enable(*keys):
    c = db.get_db()
    try:
        for k in keys:
            F.set_flag(c, k, True)
        c.commit()
    finally:
        c.close()


def _voucher(date, lines):
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] + 900
        vid = c.execute("INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
                        " VALUES (?,?, '轉', 'e2e', '已核准', 't','n','n')", ("%s-%d" % (date.replace("-", ""), n), date)).lastrowid
        for i, (code, d, cr, tax) in enumerate(lines, 1):
            c.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit,tax_code) VALUES (?,?,?,?,?,?)", (vid, i, code, d, cr, tax))
        c.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_tax401_tab_query_export_and_settlement_buttons(live_server, make_user, e2e_browser, monkeypatch):
    from modules.accounting.api import ledger_tax as _lt
    monkeypatch.setattr(_lt, "_invoices", lambda: [{"invoiceDate": "2183-01-10", "amountPretax": 10000, "taxAmount": 500}])      # 應收應付的發票明細（與傳票銷項 10000／500 對得上）
    user, pw = make_user(username="e2e_gl_tax", role="superadmin")
    _enable("tax401")
    _voucher("2183-01-10", [("1191", 10500, 0, ""), ("4111", 0, 10000, "OUT-5"), ("2204", 0, 500, "OUT-5")])
    _voucher("2183-02-05", [("5811", 2000, 0, "IN-5"), ("1268", 100, 0, "IN-5"), ("2171", 0, 2100, "")])
    page = e2e_browser.new_page(accept_downloads=True)
    bad, errs = _open(page, live_server, user, pw)
    page.wait_for_selector("[data-testid=hb-tab-tax401]", state="visible")
    page.locator("[data-testid=hb-tab-tax401]").click()
    page.wait_for_selector("[data-testid=hb-tax]", state="visible")
    page.fill("[data-testid=hb-tax-year]", "2183")
    page.select_option("[data-testid=hb-tax-period]", "1")
    page.locator("[data-testid=hb-tax-load]").click()
    page.wait_for_selector("[data-testid=hb-tax-rows] td:has-text('OUT-5')")                      # 終點：彙總表出現銷項列
    calc = page.locator("[data-testid=hb-tax-calc]").inner_text()
    assert "101" in calc and "500" in calc and "111" in calc and "400" in calc, calc               # 銷項 500、進項 100 ⇒ 應實繳 400
    assert "自己補" in page.locator("[data-testid=hb-tax-summary]").inner_text()                     # 兩行白話摘要（預設可見）
    assert page.locator("[data-testid=hb-tax-legal]").is_hidden()                                    # 詳細說明預設收合
    page.locator("[data-testid=hb-tax-details] summary").click()
    assert page.locator("[data-testid=hb-tax-legal]").is_visible() and "附件六" in page.locator("[data-testid=hb-tax-legal]").inner_text()
    unverified = page.locator("[data-testid=hb-tax-unverified]").inner_text()
    assert "代號 115" in unverified and "媒體申報檔" in unverified                                   # 只列未能核實的項目
    page.wait_for_selector("[data-testid=hb-tax-checks] td:has-text('相符')")
    _shot(page, "tax401_query")

    with page.expect_download() as dl:                                                             # 匯出 Excel 工作底稿
        page.locator("[data-testid=hb-tax-export]").click()
    path = dl.value.path()
    assert os.path.getsize(path) > 1000 and open(path, "rb").read(2) == b"PK"

    page.locator("[data-testid=hb-tax-settle]").click()                                            # 產生稅額結轉草稿
    page.wait_for_selector("[data-testid=hb-tax-notice]", state="visible")                        # 終點：訊息要撐過重讀（曾被 taxLoad 清掉）
    assert page.locator("[data-testid=hb-tax-error]").is_hidden(), page.locator("[data-testid=hb-tax-error]").inner_text()
    assert "稅額結轉草稿" in page.locator("[data-testid=hb-tax-notice]").inner_text()
    c = db.get_db()
    try:
        row = c.execute("SELECT payable, carry_new, voucher_id, status FROM gl_tax_settlements WHERE period_start='2183-01-01'").fetchone()
        assert row and (row["payable"], row["carry_new"], row["status"]) == (400, 0, "draft") and row["voucher_id"]
    finally:
        c.close()
    _shot(page, "tax401_settlement")

    page.select_option("[data-testid=hb-tax-period]", "4")                                         # 沒有稅額的期別：仍可按（對帳相符時按鈕可用），後端明說沒有稅額所以不產生
    page.locator("[data-testid=hb-tax-load]").click()
    page.locator("[data-testid=hb-tax-settle]").click()
    page.wait_for_selector("[data-testid=hb-tax-error]", state="visible")
    assert "沒有銷項與進項稅額" in page.locator("[data-testid=hb-tax-error]").inner_text()         # 終點：明說原因
    _shot(page, "tax401_no_tax_period")
    assert not [b for b in bad if b[0] != 400], "請求失敗：%s" % [b for b in bad if b[0] != 400][:4]         # 400 只有『沒有稅額的期別』那次預期的拒絕
    assert not errs, errs[:3]


@pytest.mark.e2e
def test_withholding_tab_remit_and_unremit_buttons(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_wh", role="superadmin")
    _enable("withholding")
    c = db.get_db()
    try:
        for kind, amt in (("income_tax", 1000), ("nhi", 211)):
            c.execute("INSERT OR REPLACE INTO gl_withholding_items(kind, source_type, source_key, party_key, income_type, gross, amount, period_ym, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)", (kind, "payslip", "LB-E2E-WH", "C1", "9A", 10000, amt, "2026-03", "n"))
        c.execute("UPDATE gl_withholding_items SET remitted_at='', remit_voucher_id=NULL WHERE source_key='LB-E2E-WH'")
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw)
    page.wait_for_selector("[data-testid=hb-tab-withholding]", state="visible")
    page.locator("[data-testid=hb-tab-withholding]").click()
    page.fill("[data-testid=hb-wh-ym]", "2026-03")
    page.locator("[data-testid=hb-wh-load]").click()
    page.wait_for_selector("[data-testid=hb-wh-groups] td:has-text('代扣所得稅')")
    assert "待繳庫" in page.locator("[data-testid=hb-wh-groups]").inner_text() or "逾期" in page.locator("[data-testid=hb-wh-groups]").inner_text()
    _shot(page, "withholding_query")

    row = page.locator("[data-testid=hb-wh-items] tr", has_text="LB-E2E-WH").first
    row.locator("input[type=checkbox]").check()
    page.locator("[data-testid=hb-wh-remit]").click()                                              # 沒填繳庫日 ⇒ 明說
    page.wait_for_selector("[data-testid=hb-wh-error]", state="visible")
    assert "繳庫日" in page.locator("[data-testid=hb-wh-error]").inner_text()
    page.fill("[data-testid=hb-wh-date]", "2026-04-08")
    page.locator("[data-testid=hb-wh-remit]").click()
    page.wait_for_selector("[data-testid=hb-wh-notice]", state="visible")                          # 終點：DB 有繳庫日、畫面列出繳庫日
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM gl_withholding_items WHERE source_key='LB-E2E-WH' AND remitted_at='2026-04-08'").fetchone()[0] == 1
    finally:
        c.close()
    page.wait_for_selector("[data-testid=hb-wh-items] td:has-text('2026-04-08')")
    _shot(page, "withholding_remitted")

    page.locator("[data-testid=hb-wh-items] tr", has_text="2026-04-08").locator("button:has-text('取消')").click()      # 沒填原因 ⇒ 擋下並說明
    page.wait_for_selector("[data-testid=hb-wh-error]", state="visible")
    assert "原因" in page.locator("[data-testid=hb-wh-error]").inner_text()
    page.fill("[data-testid=hb-wh-reason]", "登記錯誤")
    page.locator("[data-testid=hb-wh-items] tr", has_text="2026-04-08").locator("button:has-text('取消')").click()
    page.wait_for_function("() => !document.querySelector('[data-testid=hb-wh-items]').innerText.includes('2026-04-08')")
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM gl_withholding_items WHERE source_key='LB-E2E-WH' AND remitted_at<>''").fetchone()[0] == 0
    finally:
        c.close()
    _shot(page, "withholding_unremitted")
    assert not [b for b in bad if b[0] not in (400,)], bad[:4]
    assert not errs, errs[:3]


@pytest.mark.e2e
def test_annotation_tab_save_and_clear_buttons(live_server, make_user, e2e_browser):
    import json
    user, pw = make_user(username="e2e_gl_ann", role="superadmin")
    _enable("source_annotations")
    ev = {"source_type": "contractor_dispatch", "source_key": "E2E-ANN-1", "event_code": "E04", "event_date": "2183-03-10", "doc_no": "ZZ00000099",
          "lines": [{"role": "COST_PROJECT", "side": "D", "amount": 10000}, {"role": "INPUT_TAX", "side": "D", "amount": 500}, {"role": "AP", "side": "C", "amount": 10500}],
          "meta": {"tax_estimated": True}}
    c = db.get_db()
    try:
        c.execute("DELETE FROM gl_source_annotations WHERE source_key='E2E-ANN-1'")
        c.execute("INSERT INTO gl_source_events(source_module, source_type, source_key, event_code, rev, event_date, content_hash, amount, status, payload_json, first_seen, last_seen)"
                  " VALUES ('subcontract','contractor_dispatch','E2E-ANN-1','E04',1,'2183-03-10','h',10500,'drafted',?, 'n','n')", (json.dumps(ev, ensure_ascii=False),))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw)
    page.wait_for_selector("[data-testid=hb-tab-source_annotations]", state="visible")
    page.locator("[data-testid=hb-tab-source_annotations]").click()
    page.wait_for_selector("[data-testid=hb-an-row-E2E-ANN-1]", state="visible")
    assert "稅額為估計" in page.locator("[data-testid=hb-an-row-E2E-ANN-1]").inner_text()
    _shot(page, "annotations_pending")
    page.locator("[data-testid=hb-an-save-E2E-ANN-1]").click()                                     # 兩格都空：不送、不顯示已補登
    page.wait_for_selector("[data-testid=hb-an-error]", state="visible")
    assert "請至少填入" in page.locator("[data-testid=hb-an-error]").inner_text() and page.locator("[data-testid=hb-an-notice]").is_hidden()
    page.fill("[data-testid=hb-an-tax-E2E-ANN-1]", "480")
    page.fill("[data-testid=hb-an-date-E2E-ANN-1]", "2183-03-12")
    page.locator("[data-testid=hb-an-save-E2E-ANN-1]").click()
    page.wait_for_selector("[data-testid=hb-an-notice]", state="visible")
    c = db.get_db()
    try:
        got = {r["field"]: r["value"] for r in c.execute("SELECT field, value FROM gl_source_annotations WHERE source_key='E2E-ANN-1'")}
    finally:
        c.close()
    assert got == {"input_tax": "480", "invoice_date": "2183-03-12"}                               # 終點：DB 有補登值
    page.wait_for_selector("[data-testid=hb-an-clear-E2E-ANN-1]", state="visible")
    _shot(page, "annotations_saved")
    page.locator("[data-testid=hb-an-clear-E2E-ANN-1]").click()
    page.wait_for_selector("[data-testid=hb-an-clear-E2E-ANN-1]", state="hidden")                 # x-show：按鈕還在 DOM 但看不到＝已清除
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM gl_source_annotations WHERE source_key='E2E-ANN-1'").fetchone()[0] == 0
        c.commit()
    finally:
        c.close()
    _shot(page, "annotations_cleared")
    assert not bad, bad[:4]
    assert not errs, errs[:3]
