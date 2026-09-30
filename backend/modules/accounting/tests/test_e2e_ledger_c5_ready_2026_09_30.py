# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖，用**真實的** READY，不套用測試的『全部出貨』）：營業稅 401、扣繳清單、來源憑證補登從『開發中』變成可切換。
按鈕：功能清單的『開啟』／『關閉』——開啟後頁籤出現、內容可用（401 仍明列 4 項未能核實）；關閉後頁籤消失；預設全部關閉。
（每個頁籤裡的按鈕另見 test_e2e_ledger_tax_wh_annot_2026_09_30.py。）截圖先存暫存夾，事後複製到 D:\\開發測試檔\\shots\\<分支>\\。"""
import os
import subprocess
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402
from modules.accounting.ledger import features as F  # noqa: E402

KEYS = ("tax401", "withholding", "source_annotations")


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


def _reset():
    c = db.get_db()
    try:
        for k in KEYS:
            F.set_flag(c, k, False)
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_shipped_features_are_switchable_default_off_and_their_tabs_follow_the_switch(live_server, make_user, e2e_browser):
    _reset()
    user, pw = make_user(username="e2e_gl_ready27", role="superadmin")
    page = e2e_browser.new_page()
    errs, bad = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
    inject_login(page, live_server, user, pw)
    page.goto("%s/pages/ledger-hub.html" % live_server)
    page.wait_for_selector("[data-testid=hb-features]", timeout=20000)
    for key in KEYS:
        assert page.locator("[data-testid=hb-status-%s]" % key).inner_text() == "未開啟", key            # 不再是「開發中」，且預設關閉
        assert page.locator("[data-testid=hb-row-%s] [data-testid=hb-toggle]" % key).is_enabled(), key
        assert page.locator("[data-testid=hb-tab-%s]" % key).count() == 0, key                            # 關著：沒有頁籤
    _shot(page, "ready27_1_default_off")

    for key in KEYS:                                                                                     # 每一顆『開啟』
        page.locator("[data-testid=hb-row-%s] [data-testid=hb-toggle]" % key).click()
        page.wait_for_selector("[data-testid=hb-tab-%s]" % key, state="visible")
        assert page.locator("[data-testid=hb-status-%s]" % key).inner_text() == "已開啟", key
    c = db.get_db()
    try:
        assert all(F.flags(c)[k] for k in KEYS)                                                          # 終點：資料庫旗標＝開
    finally:
        c.close()
    _shot(page, "ready27_2_all_on")

    page.locator("[data-testid=hb-tab-tax401]").click()                                                  # 401 頁籤可用，未核實項目仍明列
    page.wait_for_selector("[data-testid=hb-tax]", state="visible")
    page.locator("[data-testid=hb-tax-load]").click()
    page.wait_for_selector("[data-testid=hb-tax-details]", state="visible")                               # 說明預設收合
    page.locator("[data-testid=hb-tax-details] summary").click()
    page.wait_for_selector("[data-testid=hb-tax-unverified]", state="visible")
    assert "代號 115" in page.locator("[data-testid=hb-tax-unverified]").inner_text()
    _shot(page, "ready27_3_tax401_usable")
    page.locator("[data-testid=hb-tab-withholding]").click()
    page.wait_for_selector("[data-testid=hb-wh]", state="visible")
    page.locator("[data-testid=hb-wh-load]").click()
    page.wait_for_selector("[data-testid=hb-wh-empty], [data-testid=hb-wh-groups]", state="attached")
    page.locator("[data-testid=hb-tab-source_annotations]").click()
    page.wait_for_selector("[data-testid=hb-an]", state="visible")
    _shot(page, "ready27_4_annotations_usable")

    for key in KEYS:                                                                                     # 每一顆『關閉』
        page.locator("[data-testid=hb-row-%s] [data-testid=hb-toggle]" % key).click()
        page.wait_for_selector("[data-testid=hb-tab-%s]" % key, state="detached")
        assert page.locator("[data-testid=hb-status-%s]" % key).inner_text() == "未開啟", key
    _shot(page, "ready27_5_off_again")
    assert not errs, errs[:3]
    assert not [b for b in bad if b[0] != 409], bad[:4]
    _reset()
    page.close()
