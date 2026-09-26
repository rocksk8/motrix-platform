"""M03 的端點與頁面在 L1 共用測試裡的那幾項。

2026-09-26 自 `test_e2e_playwright_2026_09_07`、`test_signed_upload_files`、`test_visual_management_2026_08_28` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
from datetime import datetime

import pytest

from tests.test_e2e_playwright_2026_09_07 import _login as _e2e_login          # (page, base, u, p)
from tests.test_module_no_admin_bypass_2026_09_14 import (
    test_admin_with_module_passes as _admin_with_module_passes,
    test_admin_without_module_is_blocked as _admin_without_module_is_blocked,
    test_superadmin_always_passes as _superadmin_always_passes,
)
from tests.test_signed_upload_files import _auth, _login, _make_quotation, _png_file   # (client, u, p) ⇒ token
from tests.test_visual_management_2026_08_28 import _create_part


@pytest.mark.e2e
def test_inventory_purchase_suggestions_modal_smoke(live_server, make_user, e2e_browser):
    """庫存頁「採購建議」按鈕→開啟 Modal→正確顯示低於安全庫存的料號與建議採購量
    （2026-09-07，架構地圖 §6.6）。後端邏輯已有 test_purchase_suggestions_2026_09_07.py
    完整涵蓋，這裡只驗證前端按鈕/Modal 這條路徑真的能點得通、資料有正確渲染出來
    ——純 API 測試看不出 x-show/Modal 綁定寫錯這類純前端問題。"""
    username, password = make_user(username="e2e_inv_admin", role="admin")

    import db
    conn = db.get_db()
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO parts (part_no, name, brand, unit, cost, category, safety_stock, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        ("E2E-LOWSTOCK", "E2E 測試低庫存料件", "", "台", 100, "其他", 10, now, now),
    )
    conn.commit()
    conn.close()

    browser = e2e_browser
    page = browser.new_page()
    _e2e_login(page, live_server, username, password)

    page.goto(f"{live_server}/pages/inventory.html")
    page.wait_for_selector('button:has-text("採購建議")', timeout=10000)
    page.click('button:has-text("採購建議")')

    # 底下主表格本來就會列出這個料號（未篩選），"E2E-LOWSTOCK" 文字在
    # Modal 開啟前就已經存在於畫面 DOM 裡——必須把查詢範圍限定在
    # 「採購建議」那個 Modal 本身內，不能用整頁的裸文字搜尋，否則會誤判
    # 成模組還沒載入資料就通過。
    modal = page.locator(".modal-box", has_text="採購建議")
    modal.locator("tr", has_text="E2E-LOWSTOCK").wait_for(timeout=10000)
    row_text = modal.locator("tr", has_text="E2E-LOWSTOCK").inner_text()
    assert "15" in row_text, f"應建議補到黃燈門檻 ceil(10*1.5)=15，實際列內容: {row_text!r}"


def _make_shipping_note(note_no, quote_no, status="已核准"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, "
            "items_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (note_no, quote_no, status, "測試客戶", "測試專案", "[]", "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_shipping_note_signed_files_upload(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SIGN-010")
    _make_shipping_note("DN-SIGN-001", "MQ-SIGN-010")

    up = client.post(
        "/api/shipping-notes/DN-SIGN-001/signed-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text

    lst = client.get("/api/shipping-notes", headers=_auth(token)).json()
    row = next(n for n in lst if n["noteNo"] == "DN-SIGN-001")
    assert len(row["signedFiles"]) == 1


def test_parts_summary_stock_level_thresholds(client, make_user):
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    _create_part(client, token, "TESTPART-RED", safety_stock=10)     # 0 在庫 < 10 → red
    _create_part(client, token, "TESTPART-YEL", safety_stock=10)     # 12 在庫 (<15) → yellow
    _create_part(client, token, "TESTPART-GRN", safety_stock=10)     # 20 在庫 → green
    _create_part(client, token, "TESTPART-NOTHRESH", safety_stock=0) # 未設定 → green

    import db
    conn = db.get_db()
    try:
        now = datetime.now().isoformat()
        for pn, qty in [("TESTPART-YEL", 12), ("TESTPART-GRN", 20)]:
            for i in range(qty):
                conn.execute(
                    "INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (pn, f"{pn}-SN{i}", "in_stock", "PO-TEST", 100, now, now),
                )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/inventory/parts-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    by_pn = {it["part_no"]: it for it in r.json()["items"]}
    assert by_pn["TESTPART-RED"]["stockLevel"] == "red"
    assert by_pn["TESTPART-YEL"]["stockLevel"] == "yellow"
    assert by_pn["TESTPART-GRN"]["stockLevel"] == "green"
    assert by_pn["TESTPART-NOTHRESH"]["stockLevel"] == "green"


# ── 模組權限（原 test_module_no_admin_bypass 的出貨單歷史探針、test_module_permission_fixes 的跨模組消費端）──

_PROBE = ("/api/shipping-notes/export-history", "shipping_export_log", "出貨單歷史紀錄")


def test_admin_without_shipping_export_log_is_blocked(client, make_user):
    _admin_without_module_is_blocked(client, make_user, *_PROBE)


def test_admin_with_shipping_export_log_passes(client, make_user):
    _admin_with_module_passes(client, make_user, *_PROBE)


def test_superadmin_passes_shipping_export_log(client, make_user):
    _superadmin_always_passes(client, make_user, *_PROBE)


def test_cross_module_consumers_reach_supply(client, make_user):
    """案件管理要叫料 ⇒ case_manage 也打得開庫存摘要；procurement 打得開供應商（MODULE-AUDIT §5「擋錯人」）。"""
    u, p = make_user(username="mod_case_s", role="engineer", modules=["case_manage"])
    assert client.get("/api/inventory/parts-summary", headers=_auth(_login(client, u, p))).status_code == 200
    u2, p2 = make_user(username="mod_proc_s", role="sales", modules=["procurement"])
    assert client.get("/api/suppliers", headers=_auth(_login(client, u2, p2))).status_code == 200
