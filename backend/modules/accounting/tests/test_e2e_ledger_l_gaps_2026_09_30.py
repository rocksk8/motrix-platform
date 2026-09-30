# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：『分錄草稿』頁的來源變動橫幅（L1）。
來源出現新事件 ⇒ 橫幅『N 個來源已變動，草稿待更新』；按『產生分錄草稿』⇒ 橫幅變成『來源與草稿一致』；來源再被改 ⇒
按橫幅的『重新檢查』⇒ 顯示『內容變動 1』。每顆按鈕驗畫面終點文字與資料庫狀態。截圖先存暫存夾，事後複製到 D:\\開發測試檔\\shots\\<分支>\\。"""
import datetime as dt
import os
import subprocess
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402
from core import registry  # noqa: E402
from modules.accounting.ledger import features as F  # noqa: E402


def _shot(page, name):
    try:
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10,
                            cwd=os.path.dirname(__file__)).stdout.strip() or "unknown"
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), br.replace("/", "_"))
        os.makedirs(d, exist_ok=True)
        page.set_viewport_size({"width": 1280, "height": 1100})
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=False)
    except Exception:  # noqa: BLE001
        pass


def _ev(key, date, amount):
    return {"source_type": "contractor_dispatch", "source_key": key, "event_code": "E04", "event_date": date, "doc_no": "ZZ" + key, "case_no": "",
            "party": {"key": "12345678", "name": "甲"}, "tax_code": "IN-5", "mode": "snapshot",
            "lines": [{"role": "COST_PROJECT", "side": "D", "amount": amount}, {"role": "INPUT_TAX", "side": "D", "amount": amount // 20},
                      {"role": "AP", "side": "C", "amount": amount + amount // 20}], "meta": {}}


@pytest.mark.e2e
def test_engine_banner_shows_pending_changes_and_follows_the_run_button(live_server, make_user, e2e_browser, monkeypatch):
    state = {"events": [_ev("E2E-L1-A", dt.date.today().isoformat(), 2000)]}
    fake = lambda s, e, changed_since="": {"events": [x for x in state["events"] if s <= x["event_date"] <= e]}      # noqa: E731
    real = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {"fake": fake} if cap == "gl.events" else real(cap))     # 只換事件來源，其他登記（模組載入狀態）不動
    c = db.get_db()
    try:
        F.set_flag(c, "engine_drafts", True)
        c.commit()
    finally:
        c.close()
    user, pw = make_user(username="e2e_l1_sup", role="superadmin")
    page = e2e_browser.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, live_server, user, pw)
    page.goto("%s/pages/ledger-hub.html" % live_server)
    page.wait_for_selector("[data-testid=hb-tab-engine_drafts]", state="visible", timeout=20000)
    page.locator("[data-testid=hb-tab-engine_drafts]").click()
    page.wait_for_selector("[data-testid=hb-eng-banner-text]", state="visible", timeout=15000)
    txt = page.locator("[data-testid=hb-eng-banner-text]").inner_text()
    assert "1 個來源已變動" in txt and "新增 1" in txt, txt                              # 終點：畫面文字
    _shot(page, "l1_banner_pending")

    today = dt.date.today()
    page.fill("[data-testid=hb-eng-start]", today.replace(day=1).isoformat())
    page.fill("[data-testid=hb-eng-end]", today.isoformat())
    page.locator("[data-testid=hb-eng-run]").click()
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=hb-eng-banner-text]'); return e && e.innerText.includes('來源與草稿一致') }", timeout=20000)
    c = db.get_db()
    try:
        assert c.execute("SELECT status FROM gl_source_events WHERE source_key='E2E-L1-A'").fetchone()[0] == "drafted"          # 終點：資料庫
    finally:
        c.close()
    _shot(page, "l1_banner_in_sync")

    state["events"] = [_ev("E2E-L1-A", today.isoformat(), 4000)]                                # 來源之後被改
    page.locator("[data-testid=hb-eng-banner-refresh]").click()
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=hb-eng-banner-text]'); return e && e.innerText.includes('內容變動 1') }", timeout=15000)
    _shot(page, "l1_banner_changed")
    assert not errs, errs[:3]
    c = db.get_db()
    try:
        F.set_flag(c, "engine_drafts", False)
        c.commit()
    finally:
        c.close()
    page.close()
