# -*- coding: utf-8 -*-
"""瀏覽器層級（真的 Chromium）：報價單表單「資訊密度」（UX 提案 C1～C3，FORM_VERSION V3.40，2026-11-11）。

C1 成本區預設收合：右側只有一行「內部利潤：—」摘要，按「展開成本分析」才出現 INTERNAL 面板＋成本欄；展開狀態記在這台瀏覽器；沒有任何金額時不出警示色／「低於目標」。
C2 品項表：收合時只有 7 個資料欄（#／品名／廠牌／數量／單位／售價／金額）＋刪除鈕；備註改成列下「＋備註」，有內容就直接展開；展開成本區後成本欄回來。
C3 客戶區：每欄「顯示／隱藏」改小眼睛（資料 pdfShow 不變）、個資告知預設收合但狀態仍在標題列、統編 placeholder 是範例格式。
設 UXQF_SHOTS=<目錄> 會把各狀態截圖存到該目錄（人工驗收用，不是斷言）。
"""
import json
import os
import pathlib

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單頁")

NO = "MQ-DENS-001"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"
SHOTS = os.environ.get("UXQF_SHOTS")


def _shot(page, name):
    if SHOTS and pathlib.Path(SHOTS).is_dir():      # 目錄由人先建好（BK19 守門不允許測試自己 makedirs 到 repo／tmp 之外）
        page.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"), full_page=True)


def _seed():
    import db
    items = [{"id": 1, "description": "Catalyst 24埠交換器", "brand": "Cisco C9200", "qty": 2, "unit": "台", "cost": 8000.0,
              "margin": 0.3, "unitPrice": 12857.0, "amount": 25714.0, "notes": "含 3 年原廠保固"},
             {"id": 2, "description": "網路線材", "brand": "", "qty": 10, "unit": "條", "cost": 50.0,
              "margin": 0.3, "unitPrice": 75.0, "amount": 750.0, "notes": ""}]
    data = {"quoteNo": NO, "customerName": "密度客戶", "projectName": "密度專案", "status": "草稿", "items": items,
            "tot": {"total": 27741, "pretax": 26464}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "草稿", "密度客戶", "密度專案", 27741, 26464, json.dumps(data, ensure_ascii=False),
                      "2026-11-11T08:00:00", "2026-11-11T08:00:00", "", "業務X", "[]"))
        conn.commit()
    finally:
        conn.close()


def _login(page, live_server, make_user, name="dens_u"):
    u, p = make_user(username=name, role="superadmin")
    inject_login(page, live_server, u, p)
    return u


def _visible_th(page):
    return page.evaluate("() => [...document.querySelectorAll('table.items-table thead th')].filter(e => e.offsetParent).map(e => e.innerText.trim().replace(/\\s+/g, ' '))")


@pytest.mark.e2e
def test_new_empty_form_is_collapsed_calm_and_has_no_warning_color(live_server, make_user, e2e_browser):
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    _login(page, live_server, make_user)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector('[data-testid="qf-cost-strip"]', state="visible", timeout=20000)
    assert not page.locator(".cost-panel").first.is_visible(), "INTERNAL 面板預設收合"
    txt = page.inner_text('[data-testid="qf-cost-strip"]')
    assert "內部利潤" in txt and "—" in txt and "展開成本分析" in txt, txt
    body = page.inner_text("body")
    assert "低於目標" not in body, "空白表單不可以出現「低於目標」警示"
    ths = _visible_th(page)
    assert not any("成本單價" in t or "毛利率" in t or "單項毛利" in t or t.startswith("備註") for t in ths), ths
    assert len([t for t in ths if t]) == 7, ths                        # # 品名 廠牌 數量 單位 售價 金額（刪除鈕那欄沒有字）
    assert page.get_attribute('input[x-model="q.customerTaxId"]', "placeholder") == "8 碼，例 12345678"
    assert page.locator('[data-testid^="qf-pdfshow-"]').count() == 6
    assert not page.locator('[data-testid="qf-pn-body"]').is_visible(), "個資告知內文預設收合"
    _shot(page, "01-new-collapsed-1440")
    # 展開後：面板與成本欄出現，仍然沒有警示（沒有金額）
    page.click('[data-testid="qf-cost-expand"]')
    page.wait_for_selector(".cost-panel", state="visible")
    assert "低於目標" not in page.inner_text("body")
    assert any("成本單價" in t for t in _visible_th(page))
    _shot(page, "02-new-expanded-1440")


@pytest.mark.e2e
def test_expanded_state_is_remembered_and_warning_appears_only_with_amounts(live_server, make_user, e2e_browser):
    _seed()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    _login(page, live_server, make_user)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_function("() => document.body.innerText.includes('密度客戶')", timeout=20000)
    page.wait_for_selector('[data-testid="qf-cost-strip"]', state="visible")
    s = page.inner_text('[data-testid="qf-cost-strip-text"]')
    assert "營業利益率" in s and "NT$" in s, s                          # 有金額 ⇒ 摘要有數字
    _shot(page, "03-seeded-collapsed-1440")
    page.click('[data-testid="qf-cost-expand"]')
    page.wait_for_selector(".cost-panel", state="visible")
    assert page.evaluate("() => localStorage.getItem('motrix.qf.showCostCols')") == "1"
    _shot(page, "04-seeded-expanded-1440")
    page.reload()
    page.wait_for_function("() => document.body.innerText.includes('密度客戶')", timeout=20000)
    page.wait_for_selector(".cost-panel", state="visible", timeout=15000)       # 重新整理後維持展開
    assert not page.locator('[data-testid="qf-cost-strip"]').is_visible()
    # 再收合：用既有的「隱藏成本欄」總開關
    page.click('button:has-text("隱藏成本欄")')
    page.wait_for_selector('[data-testid="qf-cost-strip"]', state="visible")
    assert page.evaluate("() => localStorage.getItem('motrix.qf.showCostCols')") == "0"
    # K 審 N1：全部品項售價 0（贈品）但有成本 ⇒ 要照算（顯示虧損），不可當成「尚未填」
    page.evaluate(f"() => {{ {DATA}.q.items.forEach(i => {{ i.amount = 0; i.unitPrice = 0 }}) }}")
    page.wait_for_timeout(300)
    assert page.evaluate(f"{DATA}.hasAmounts()") is True
    assert "營業利益率" in page.inner_text('[data-testid="qf-cost-strip-text"]')


@pytest.mark.e2e
def test_notes_move_below_the_row_and_open_on_demand(live_server, make_user, e2e_browser):
    _seed()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    _login(page, live_server, make_user)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_function("() => document.body.innerText.includes('密度客戶')", timeout=20000)
    page.wait_for_selector("table.items-table tbody tr", state="attached")
    notes = page.locator('[data-testid="qf-item-note"]')
    assert notes.count() == 1 and notes.first.input_value() == "含 3 年原廠保固", "有內容的備註直接展開"
    assert page.locator('[data-testid="qf-add-note"]:visible').count() == 1, "沒內容的那一列只有「＋備註」"
    page.locator('[data-testid="qf-add-note"]:visible').first.click()
    page.wait_for_function("() => document.querySelectorAll('[data-testid=qf-item-note]').length === 2")
    box = page.locator('[data-testid="qf-item-note"]').nth(1)
    box.fill("到貨後三日內安裝")
    assert page.evaluate(f"{DATA}.q.items[1].notes") == "到貨後三日內安裝"
    assert page.evaluate(f"{DATA}.q.items[1]._notesOpen") is None, "展開狀態不可寫進品項資料（會改內容指紋）"
    # K 審 M2：載入既有單時就有內容的備註，清空後輸入框不可消失（否則邊改邊刪最後一個字就沒框、焦點掉到 BODY）
    first = page.locator('[data-testid="qf-item-note"]').first
    first.fill("")
    page.wait_for_timeout(300)
    assert page.locator('[data-testid="qf-item-note"]').count() == 2, "備註清空後輸入框仍在"
    first.type("改")
    assert page.evaluate(f"{DATA}.q.items[0].notes") == "改"
    # 沒有橫向捲動：收合時表格寬度不超過容器
    over = page.evaluate("() => { const t = document.querySelector('table.items-table'); return t.parentElement.scrollWidth - t.parentElement.clientWidth }")
    assert over <= 1, f"1440 寬收合時品項表不該橫向溢出（溢出 {over}px）"
    _shot(page, "05-notes-1440")


@pytest.mark.e2e
def test_privacy_notice_folds_but_keeps_status_visible_and_pdf_eye_toggles_data(live_server, make_user, e2e_browser):
    _seed()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    _login(page, live_server, make_user)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_function("() => document.body.innerText.includes('密度客戶')", timeout=20000)
    page.fill('input[x-model="q.contactName"]', "王小明")
    page.wait_for_selector("[data-privacy-missing]", state="visible", timeout=20000)    # 狀態不必展開就看得到
    assert not page.locator('[data-testid="qf-pn-body"]').is_visible()
    page.click('[data-testid="qf-pn-toggle"]')
    page.wait_for_selector('[data-testid="qf-pn-body"]', state="visible")
    assert page.locator("input[data-privacy-ack]").is_visible() and page.locator("[data-print-notice]").is_visible()
    # 眼睛鈕仍然操作同一份 pdfShow 資料
    before = page.evaluate(f"{DATA}.q.pdfShow.contactPhone")
    page.click('[data-testid="qf-pdfshow-contactPhone"]')
    assert page.evaluate(f"{DATA}.q.pdfShow.contactPhone") is (not before)
    assert page.get_attribute('[data-testid="qf-pdfshow-contactPhone"]', "aria-pressed") == ("true" if not before else "false")
    _shot(page, "06-customer-section-1440")


@pytest.mark.e2e
def test_390px_phone_width_form_body_and_items_table_stay_inside_the_viewport(live_server, make_user, e2e_browser):
    _seed()
    page = e2e_browser.new_page(viewport={"width": 390, "height": 844})
    _login(page, live_server, make_user)
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_function("() => document.body.innerText.includes('密度客戶')", timeout=20000)
    # 頁頭導覽列在手機寬度本來就會橫向溢出（既有問題，UX 提案 F 另案）；這裡只量表單主體
    assert page.evaluate("() => { const r = document.querySelector('.form-layout').getBoundingClientRect(); return r.right - window.innerWidth }") <= 1
    assert page.evaluate("() => { const t = document.querySelector('table.items-table'); return t.parentElement.getBoundingClientRect().right - window.innerWidth }") <= 1, "品項表要在自己的捲動容器內捲，不推寬整頁"
    _shot(page, "07-seeded-390")
