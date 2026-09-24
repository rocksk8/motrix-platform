"""瀏覽器端對端：報價單預覽 modal 顯示的是伺服器版面（2026-09-24，裁示 P2）。

- iframe 的內容就是 /api/quotations/preview-html 回傳的 HTML（前端自畫的版面已移除）
- sandbox 只給 allow-scripts：pdf_gen 內建的 A4 縮放 script 要真的生效（長報價單）
- 切換「對外／內部」會重取；開預覽不可以清掉離頁警告（那支是 POST）
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

QUOTE_NO = "MQ-202609-082"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _seed(n_items):
    import db
    items = [{"id": i + 1, "description": f"品項 {i + 1} " + "說明文字 " * 6, "brand": "B", "qty": 1,
              "unit": "台", "cost": 100, "margin": 0.35, "unitPrice": 160, "amount": 160}
             for i in range(n_items)]
    data = {"quoteNo": QUOTE_NO, "customerName": "預覽客戶", "projectName": "預覽專案", "status": "草稿",
            "items": items, "tot": {"total": 168 * n_items, "pretax": 160 * n_items,
                                    "directMarginPct": 0, "netMarginPct": 0}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "草稿", "預覽客戶", "預覽專案", 168 * n_items, 160 * n_items,
             json.dumps(data, ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()


def _preview_frame(page):
    page.locator("#quote-preview-frame").wait_for(state="visible", timeout=20000)
    for _ in range(100):
        fr = page.locator("#quote-preview-frame").element_handle().content_frame()
        if fr:
            try:
                if fr.evaluate("() => document.readyState === 'complete' && !!document.getElementById('root')"):
                    return fr
            except Exception:
                pass
        time.sleep(0.1)
    pytest.fail("預覽 iframe 沒有載入完成")


@pytest.mark.e2e
def test_preview_shows_server_layout_and_zoom_script_runs(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_pv1", role="superadmin")
    # 長度要落在「超過一頁 A4、但縮放比例仍 >= 0.70」之間，內建 script 才會縮
    # （2026-09-24 實測，iframe 寬 759px：3 項 1506px ⇒ 比例 0.67 不縮；1 項落在可縮範圍）
    _seed(1)
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.body.innerText.includes('預覽客戶')", timeout=20000)
    assert page.locator("#pdf-preview-content").count() == 0, "前端自畫的預覽版面應已移除"

    page.evaluate("() => { window.motrixIsDirty = true }")
    page.evaluate(f"{DATA_JS}.openPreview('external')")
    fr = _preview_frame(page)
    assert page.get_attribute("#quote-preview-frame", "sandbox") == "allow-scripts"

    srcdoc = page.evaluate(f"{DATA_JS}.previewHtml")
    assert srcdoc and "品項 1" in srcdoc and "報價" in srcdoc
    assert page.evaluate("() => window.motrixIsDirty") is True, "開預覽不是存檔，不可以清掉離頁警告"

    # 縮放 script 真的跑了（不是只看到 iframe）
    try:
        fr.wait_for_function("() => /zoom:/.test(document.body.getAttribute('style') || '')", timeout=5000)
    except Exception:
        pass    # 下面的斷言會帶出量到的值
    # ⚠️ 讀 style 屬性，不讀 style.zoom：2026-09-24 實測 Chromium 的 style.zoom 讀出空字串，
    #    而屬性是 "zoom: 0.7328;"（script 有跑）。
    m = fr.evaluate("() => [document.getElementById('root').scrollHeight,"
                    " (document.body.getAttribute('style') || '').match(/zoom:\s*([0-9.]+)/)]")
    # 內建 script：內容高 h > A4 可列印高（1009px）且 1009/h >= 0.70 才縮放
    # m[0] 是縮放「之後」量到的高度，不能拿來反推比例；只驗縮放落在內建規則的範圍
    assert m[1] and 0.70 <= float(m[1][1]) < 1, m
    # 主頁拿到內容回報的高度
    h = page.evaluate(f"{DATA_JS}.previewFrameHeight")
    assert h != 1130 and h > 300, h

    # 切換內部版 ⇒ 重取，內容含成本欄
    page.evaluate(f"{DATA_JS}.previewMode = 'internal'")
    page.wait_for_function(f"() => {DATA_JS}.previewHtml.includes('35.0%')", timeout=20000)
