# -*- coding: utf-8 -*-
"""瀏覽器層級：案件「執行管理 › 材料申請」的物料時間軸（T86 第 3 項）。

每個材料一列、申請→採購→到貨（＋入庫／出貨，讀得到時）；目前這一關有就地按鈕；明細欄位仍在下方；手機寬度不橫向捲動。
截圖存到 MOTRIX_SHOTS_DIR（預設系統暫存）。
"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁")

NO = "MQ-MTL-T86"


def _case():
    import db
    data = {"dealTag": "已成案", "caseRecord": {"materials": [
        {"id": "ma", "name": "壁掛機櫃", "model": "9U", "qty": 1, "unit": "座", "ordered": False, "arrived": False},
        {"id": "mb", "name": "網路交換器", "model": "SG350", "qty": 4, "unit": "台", "ordered": True, "arrived": True,
         "poLink": {"key": "g:sw", "docCodes": ["PO-2611-014"], "arrivedOn": "2026-11-10"}},
    ]}}
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "時間軸客戶", "時間軸工程", 1000, 952, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _shot(page, name):
    d = os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "t86-mtl")
    try:
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001 — 截圖只是附件；BK19 不允許寫到 repo／暫存以外時略過
        pass


def _open(live_server, make_user, e2e_browser, name, width):
    u, p = make_user(username=name, role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": width, "height": 1000})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    page.get_by_role("button", name="材料申請").first.click()
    page.locator('[data-testid="mtl-row-ma"]').wait_for(state="visible", timeout=15000)
    page.locator('[data-testid="mtl-st-mb-ship"]').wait_for(state="attached", timeout=15000)       # 物料流程摘要讀到後才有入庫／出貨關
    page.wait_for_function("() => !document.querySelector('.mtl').innerText.includes('載入中')", timeout=15000)
    return page


@pytest.mark.e2e
def test_timeline_rows_states_and_inline_actions(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "mtl_t86a", 1440)
    st = lambda m, k: page.locator(f'[data-testid="mtl-st-{m}-{k}"]')          # noqa: E731
    # 機櫃：還沒申請 ⇒ 申請是目前這一關，按鈕開請購單（案件已帶好）
    assert st("ma", "req").get_attribute("data-state") == "cur"
    assert st("ma", "po").get_attribute("data-state") == "todo"
    href = page.get_attribute('[data-testid="mtl-act-ma-req"]', "href")
    assert href == f"payment-request.html?case={NO}&type=purchase_req", href
    # 交換器：採購單已認列且已到貨 ⇒ 前三關完成、沒有按鈕
    for k in ("req", "po", "arrive"):
        assert st("mb", k).get_attribute("data-state") == "done", k
    assert "PO-2611-014" in st("mb", "po").inner_text() and "2026-11-10" in st("mb", "arrive").inner_text()
    for k in ("req", "po", "arrive"):
        assert page.locator(f'[data-testid="mtl-act-mb-{k}"]').count() == 0, k       # 已完成的關卡沒有按鈕
    assert st("mb", "stock").get_attribute("data-state") == "cur" and "尚無入庫紀錄" in st("mb", "stock").inner_text()
    assert st("mb", "ship").get_attribute("data-state") == "todo"                 # 已到貨、尚無出貨單：出貨關可直接開單
    assert page.locator('[data-testid="mtl-act-mb-ship"]').inner_text() == "開出貨單"
    assert "已到貨 1" in page.locator('[data-testid="mtl-sum"]').inner_text()
    # 明細欄位仍在（原本的材料卡）
    assert page.locator('[data-testid="mat-ordered"]').count() == 2
    _shot(page, "desktop")


@pytest.mark.e2e
def test_timeline_phone_width_has_no_horizontal_scroll(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "mtl_t86b", 390)
    assert page.locator('[data-testid="mtl-st-ma-req"]').is_visible()
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "mobile390")


@pytest.mark.e2e
def test_material_flow_page_is_a_summary_that_points_back_into_the_case(live_server, make_user, e2e_browser):
    u, p = make_user(username="mtl_t86c", role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/material-flow.html?q={NO}")
    page.locator('[data-testid="mf-cell-call"]').wait_for(state="visible", timeout=15000)
    assert page.get_attribute('[data-testid="mf-open-case"]', "href") == f"case-management.html?q={NO}&tab=exec&sub=materials"
    assert page.locator(".mf-go").count() == 0, "各格不再各自帶往不同的相關頁面"
