"""每個 Excel 匯出都有 PDF 按鈕、按下去真的下載 PDF、而且 Excel／PDF 各留一筆稽核（使用者規則 2026-09-30，第 27 班）。

觀測點：下載檔（Excel 可被 openpyxl 讀、PDF 以 `%PDF-` 開頭且大於 1KB）、資料庫 `audit_log` 的 `export.xlsx`／`export.pdf` 列
（target_id＝匯出名稱、detail 有 module／filters／rows、沒有個資值）。截圖存 `D:\\開發測試檔\\shots\\wip-w3-export-pdf\\`。
PDF 用真的 Edge headless（不換假的）；這台沒有 Edge 時 PDF 端點回 503，本檔的題會紅——不 skip（skip 會遮蔽「PDF 其實出不來」）。
"""
from tests._requires import requires_module  # noqa: E402
import io
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

# 預設寫到暫存目錄（BK19：寫入護欄只准 repo／tmp）；要留在共用截圖資料夾時設 MOTRIX_SHOTS_DIR（並過護欄旗標）
SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "aet27-shots")) / "wip-w3-export-pdf"


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=False)
    except Exception:                                            # noqa: BLE001 — 截圖失敗不影響判定
        pass


def _audit(action, target_id):
    import db
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT action, target_type, target_id, detail FROM audit_log WHERE action=? AND target_id=? ORDER BY id",
                            (action, target_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _assert_download_pair(page, xlsx_btn, pdf_btn, target_id, shot, expect_rows_min=1):
    """按 Excel、再按 PDF（中間清冷卻）：兩個都要下載得到、兩個都要有稽核列。"""
    from openpyxl import load_workbook
    import helpers.xlsx_out as X
    with page.expect_download(timeout=30000) as dl:
        page.click(xlsx_btn)
    assert dl.value.suggested_filename.lower().endswith(".xlsx"), dl.value.suggested_filename
    load_workbook(io.BytesIO(Path(dl.value.path()).read_bytes()))
    X._export_times.clear()
    with page.expect_download(timeout=90000) as dl2:
        page.click(pdf_btn)
    assert dl2.value.suggested_filename.lower().endswith(".pdf"), dl2.value.suggested_filename
    pdf = Path(dl2.value.path()).read_bytes()
    assert pdf.startswith(b"%PDF-") and len(pdf) > 1024, "PDF 檔頭不對或太小（%d bytes）" % len(pdf)
    _shot(page, shot)
    xr, pr = _audit("export.xlsx", target_id), _audit("export.pdf", target_id)
    assert len(xr) == 1 and len(pr) == 1, (xr, pr)
    for r in (xr[0], pr[0]):
        d = json.loads(r["detail"])
        assert r["target_type"] == "export" and d["module"] and "filters" in d
    assert (json.loads(xr[0]["detail"]).get("rows") or 0) >= expect_rows_min
    return xr[0], pr[0]


def _case(no):
    import db
    now = "2026-01-01T00:00:00"
    cr = {"roles": {"filler": "", "sales": "", "executor": ""}, "payment": {"items": []}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "王大明科技", "專案甲", 1000, 952, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01", ""))
        conn.commit()
    finally:
        conn.close()


DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


@pytest.mark.e2e
@requires_module("case", "案件批次匯出屬於 case 模組")
def test_case_batch_export_has_a_pdf_button_and_both_are_logged(live_server, make_user, e2e_browser):
    u = make_user(username="ex_admin", role="admin")
    for no in ("MQ-EX-1", "MQ-EX-2"):
        _case(no)
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token && !{DATA_JS}.loading", timeout=20000)
    page.click("[data-testid=batch-toggle]")
    for no in ("MQ-EX-1", "MQ-EX-2"):
        page.locator(f".cm-card[data-quote-no='{no}'] [data-testid=batch-check]").click()
    page.locator("[data-testid=batch-export-pdf]").wait_for(state="visible", timeout=5000)
    x, p = _assert_download_pair(page, "[data-testid=batch-export]", "[data-testid=batch-export-pdf]", "case-batch", "case-batch")
    d = json.loads(p["detail"])
    assert d["filters"].get("body.quote_nos") == "<list:2>", d
    assert "王大明" not in p["detail"] and "MQ-EX" not in p["detail"], "稽核不可含客戶名與單號清單"


@pytest.mark.e2e
def test_contractors_export_has_a_pdf_button_and_both_are_logged(live_server, make_user, e2e_browser):
    u = make_user(username="ex_super", role="superadmin")
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/contractors.html")
    page.locator("[data-testid=ct-export-pdf]").wait_for(state="visible", timeout=20000)
    _assert_download_pair(page, "[data-testid=ct-export]", "[data-testid=ct-export-pdf]", "contractors", "contractors", expect_rows_min=1)


def _open(page, live_server, user, path, ready):
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, user[0], user[1])
    page.goto(f"{live_server}/pages/{path}")
    page.wait_for_function(f"() => {DATA_JS} && 'activeTab' in {DATA_JS}", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=20000)
    page.evaluate(f"() => {{ const d = {DATA_JS}; {ready} }}")


@pytest.mark.e2e
def test_cashier_history_and_t100_exports_have_pdf_and_are_logged(live_server, make_user, e2e_browser):
    u = make_user(username="ex_cash", role="superadmin")
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    _open(page, live_server, u, "cashier.html", "d.activeTab = 'recv'; d.cashierSub = 'history';")
    page.locator("[data-testid=export-pdf-cashier-history]").wait_for(state="visible", timeout=10000)
    _assert_download_pair(page, "[data-testid=export-xlsx-cashier-history]", "[data-testid=export-pdf-cashier-history]",
                          "cashier-history", "cashier-history", expect_rows_min=0)
    page.evaluate(f"() => {{ const d = {DATA_JS}; d.showT100Sub(); }}")
    page.locator("[data-testid=export-pdf-t100]").wait_for(state="visible", timeout=10000)
    _assert_download_pair(page, "[data-testid=export-xlsx-t100]", "[data-testid=export-pdf-t100]", "t100-vouchers", "t100-vouchers", expect_rows_min=0)


@pytest.mark.e2e
def test_reports_tax_export_has_pdf_and_is_logged(live_server, make_user, e2e_browser):
    u = make_user(username="ex_rep", role="superadmin")
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    _open(page, live_server, u, "reports.html", "d.showCashPosTab();")
    page.locator("[data-testid=export-pdf-tax-export]").scroll_into_view_if_needed(timeout=10000)
    _assert_download_pair(page, "[data-testid=export-xlsx-tax-export]", "[data-testid=export-pdf-tax-export]",
                          "tax-export", "tax-export", expect_rows_min=0)
