"""瀏覽器端對端（含截圖）：材料申請「尚未送審」（第 32 班）。

使用者原話：新增後不要先儲存成正式記錄，先顯示「尚未送審」，按「送審」才進簽核。
- 新增→填寫：畫面「尚未送審」；資料庫**沒有**這一列（沒審核單、案件資料沒有）；KPI 不計入並顯示「不含尚未送審 1 項」；離頁會警告（motrixIsDirty）。
- 重新整理：未儲存的列不留（不靜默建草稿）。
- 一鍵「送審」＝先儲存再送審 ⇒ 待審核；簽核佇列出現。
- 手動「儲存」的草稿：仍顯示「尚未送審」、不在簽核佇列、KPI 不計入。
- 守門拒絕（缺供應商）⇒ 不送審、不留殘列。
等每個動作的終點（資料庫／API），不等「提示出現」；等待一律 `page.wait_for_timeout`。需要 playwright，沒裝整檔 skip。
"""
from tests._requires import requires_module  # noqa: E402
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點或讀寫 M01 的資料")

NO = "MQ-UNSENT-E2E"
PANEL = "#fin-material-orders"



@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    """33-M1 後端強制採購單已上線；這個檔的畫面流程（手動新增列）等前端「從採購單帶入」改版時再改寫。規則本身的題在 test_material_po_required_2026_10_03.py。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)

def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), "t32-unsent")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _db(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _orders():
    r = _db("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))
    return (json.loads(r[0]["data_json"]).get("caseRecord") or {}).get("materialOrders") or []


def _approvals():
    return _db("SELECT item_id, status, doc_code FROM case_material_approvals WHERE quote_no=?", (NO,))


def _wait(page, pred, what, timeout_ms=20000):
    for _ in range(timeout_ms // 200):
        if pred():
            return
        page.wait_for_timeout(200)
    raise AssertionError("等不到：" + what + " ｜approvals=" + str(_approvals()) + " ｜page=" + page.inner_text("#fin-material-orders")[:500])


def _status(page, i=0):
    return page.locator(f'{PANEL} [data-testid="mo-ap-status"]').nth(i).inner_text()


def _fill_new(page, name, price="1500"):
    page.click(f'{PANEL} button:has-text("新增項目")')
    page.locator(f'{PANEL} input[placeholder="項目名稱（如：交換器）"]').last.fill(name)
    page.locator(f'{PANEL} input[placeholder="數量"]').last.fill("2")
    page.locator(f'{PANEL} input[placeholder="單價"]').last.fill(price)


def _pick_supplier(page):
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier]').length >= 1 && "
                           "[...document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier]')].every(s => s.options.length >= 2)", timeout=15000)
    page.locator(f'{PANEL} [data-testid="mo-supplier"]').last.select_option(label="S-001 甲供應商")


def _queue_codes(page, base, token):
    r = page.request.get(base + "/api/approval-queue", headers={"Authorization": "Bearer " + token})
    assert r.status == 200, r.text()
    return [i.get("quoteNo") for g in r.json()["queue"] for i in g["items"] if i.get("type") == "material_order"]


@pytest.mark.e2e
def test_new_material_request_stays_unsent_until_submit(live_server, make_user, e2e_browser):
    import db
    adm, ap = make_user(username="e2e_us_adm", role="superadmin")
    boss, bp = make_user(username="e2e_us_boss", role="sales")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "尚未送審客", "尚未送審專", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}],
                                                            "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.execute("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2026-01-01", "2026-01-01"))
        conn.commit()
    finally:
        conn.close()

    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, adm, ap)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_function("() => (document.querySelector('#fin-material-orders')?.innerText || '').includes('尚無材料申請項目')", timeout=20000)
    tok = json.loads(page.evaluate("() => localStorage.getItem('motrix_session')"))["token"]    # 同一帳號再登入會讓第一個 token 失效，所以取頁面現成的

    # 1 新增＋填寫 ⇒ 「尚未送審」，但沒有任何正式記錄
    _fill_new(page, "交換器")
    _pick_supplier(page)
    assert _status(page) == "尚未送審"
    page.wait_for_timeout(2500)                                                      # 給「靜默自動存」時間冒出來；它不該存在
    assert _orders() == [] and _approvals() == [], "新增後不應先存成正式記錄"
    assert page.locator(f'{PANEL} [data-testid="mo-unsent-note"]').inner_text() == "不含尚未送審 1 項"
    assert page.evaluate("() => window.motrixIsDirty === true"), "有未儲存的列，離頁要警告"
    assert page.locator(f'{PANEL} [data-testid="mo-ap-status"]').first.get_attribute("title") == "尚未送審，不計入報表與額度，也不會出現在簽核佇列。"
    assert _queue_codes(page, live_server, tok) == []                                # 簽核佇列的 quoteNo 欄＝審核單號（MO-…），不是案號
    _shot(page, "01-unsent")

    # 2 重新整理 ⇒ 未儲存的列不留（不靜默建草稿）
    page.reload()
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_function("() => (document.querySelector('#fin-material-orders')?.innerText || '').includes('尚無材料申請項目')", timeout=20000)
    assert _orders() == [] and _approvals() == []

    # 3 手動「儲存」⇒ 仍是「尚未送審」（審核單草稿），不在簽核佇列
    _fill_new(page, "路由器", "1000")
    _pick_supplier(page)
    page.click(f'{PANEL} button:has-text("儲存材料申請")')
    _wait(page, lambda: len(_approvals()) == 1, "儲存後建出審核單")
    assert _approvals()[0]["status"] == "草稿"
    page.wait_for_function("() => !(document.querySelector('#fin-material-orders')?.innerText || '').includes('載入中')", timeout=15000)
    assert _status(page) == "尚未送審"
    assert _queue_codes(page, live_server, tok) == []                                # 草稿不在佇列
    assert page.locator(f'{PANEL} [data-testid="mo-unsent-note"]').inner_text() == "不含尚未送審 1 項"
    _shot(page, "02-saved-draft-still-unsent")

    # 4 新增第二列 ⇒ 一鍵「送審」＝先存再送審 ⇒ 待審核；佇列出現
    _fill_new(page, "線材", "100")
    _pick_supplier(page)
    page.locator(f'{PANEL} [data-testid="mo-submit"]').last.click()
    _wait(page, lambda: sorted(a["status"] for a in _approvals()) == ["待審核", "草稿"], "一鍵送審後：另一列待審核")
    assert [o["itemName"] for o in _orders()] == ["路由器", "線材"]
    page.wait_for_function("() => [...document.querySelectorAll('#fin-material-orders [data-testid=mo-ap-status]')].some(e => e.innerText === '待審核')", timeout=15000)
    page.wait_for_selector(f'{PANEL} [data-testid="mo-withdraw"]:visible', timeout=5000)      # 送審後頁籤跟著切到「審核中」，那一列看得到
    submitted = [a["doc_code"] for a in _approvals() if a["status"] == "待審核"]
    assert len(submitted) == 1 and _queue_codes(page, live_server, tok) == submitted      # 只有送審的那張在佇列，草稿不在
    _shot(page, "03-one-click-submit")

    # 5 守門拒絕：缺供應商 ⇒ 不送審、不留殘列
    page.click(f'{PANEL} button:has-text("新增項目")')
    page.locator(f'{PANEL} input[placeholder="項目名稱（如：交換器）"]').last.fill("沒供應商")
    before = (len(_orders()), len(_approvals()))
    page.locator(f'{PANEL} [data-testid="mo-submit"]').last.click()
    page.wait_for_timeout(1500)
    assert (len(_orders()), len(_approvals())) == before, "缺供應商不得留下任何列"
    assert "還沒選供應商" in page.locator(PANEL).inner_text()
    assert not errors, errors
