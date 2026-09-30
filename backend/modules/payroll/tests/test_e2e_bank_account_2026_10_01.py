# -*- coding: utf-8 -*-
"""收款帳號頁（`bank-account.html`）：本人存帳號、遮蔽切換；出納看遮蔽版並「顯示完整」（留稽核）；財務代為維護；沒資格者看不到管理區。
終點狀態＝DOM＋資料庫；截圖（預設暫存目錄；設 MOTRIX_SHOTS_DIR 才寫共用資料夾）：三種身分各一張、窄螢幕一張。"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "aet27-shots")) / "wip-w3-bank-profile"
NUM = "0011223344556"


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=True)
    except Exception:                                            # noqa: BLE001 — 截圖失敗（含 BK19 護欄）不影響判定
        pass


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _open(e2e_browser, base, user, width=1280):
    ctx = e2e_browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/bank-account.html")
    page.wait_for_selector("[data-testid=ba-form]", timeout=20000)
    page.wait_for_function("() => !document.body.innerText.includes('載入中…')", timeout=20000)
    return page


def _fill(page, prefix, code="004", name="臺灣銀行", branch="台中分行", acct_name="王小明", number="0011-2233 44556"):
    for tid, v in (("bank-code", code), ("bank-name", name), ("branch", branch), ("account-name", acct_name), ("account-number", number)):
        page.fill("[data-testid=%s%s]" % (prefix, tid), v)


@pytest.mark.e2e
def test_owner_saves_toggles_mask_and_sees_no_admin_section(live_server, make_user, e2e_browser):
    u = make_user(username="bae_owner", role="viewer", modules=[])
    page = _open(e2e_browser, live_server, u)
    assert page.locator("[data-testid=ba-none]").is_visible()
    assert not page.locator("[data-testid=ba-admin]").is_visible(), "沒資格的人不該看到管理區"
    _shot(page, "1_owner_empty")
    # 不合法 ⇒ 錯誤顯示、沒寫入
    _fill(page, "ba-", number="12ab")
    page.click("[data-testid=ba-save]")
    page.wait_for_selector("[data-testid=ba-err]", state="visible")
    assert "只能是數字" in page.inner_text("[data-testid=ba-err]")
    assert _db("SELECT 1 FROM user_bank_accounts WHERE username='bae_owner'") == []
    # 合法 ⇒ 存檔、畫面顯示遮蔽的目前帳號、DB 有一筆有效列
    _fill(page, "ba-")
    page.click("[data-testid=ba-save]")
    page.wait_for_selector("[data-testid=ba-msg]", state="visible")
    assert "已儲存" in page.inner_text("[data-testid=ba-msg]")
    rows = _db("SELECT active, account_number, bank_code FROM user_bank_accounts WHERE username='bae_owner'")
    assert rows == [{"active": 1, "account_number": NUM, "bank_code": "004"}]
    cur = page.locator("[data-testid=ba-current-number]")
    assert cur.inner_text() == "****4556", "預設遮蔽顯示（防旁人看螢幕）"
    page.click("[data-testid=ba-toggle-show]")
    assert cur.inner_text() == NUM
    page.click("[data-testid=ba-toggle-show]")
    assert cur.inner_text() == "****4556"
    _shot(page, "2_owner_saved_masked")
    # 重新整理後仍在（伺服器端讀回）
    page.reload()
    page.wait_for_selector("[data-testid=ba-current]", timeout=20000)
    assert page.input_value("[data-testid=ba-bank-code]") == "004"


@pytest.mark.e2e
def test_cashier_sees_masked_list_reveals_full_with_an_audit_row_and_cannot_edit(live_server, make_user, e2e_browser):
    owner = make_user(username="bae_o2", role="viewer", modules=[])
    page = _open(e2e_browser, live_server, owner)
    _fill(page, "ba-")
    page.click("[data-testid=ba-save]")
    page.wait_for_selector("[data-testid=ba-msg]", state="visible")
    cash = make_user(username="bae_cash", role="viewer", modules=["cashier"])
    p2 = _open(e2e_browser, live_server, cash)
    p2.wait_for_selector("[data-testid=ba-admin]", state="visible", timeout=20000)
    opt = p2.locator("[data-testid=ba-user-select] option", has_text="bae_o2")
    assert "****4556" in opt.inner_text() and NUM not in p2.content(), "清單只有末四碼"
    p2.select_option("[data-testid=ba-user-select]", label=opt.inner_text())
    p2.wait_for_selector("[data-testid=ba-target-number]", state="visible")
    assert p2.inner_text("[data-testid=ba-target-number]") == "****4556"
    assert not p2.locator("[data-testid=ba-a-save]").is_visible(), "出納只能看、不能改"
    assert _db("SELECT 1 FROM audit_log WHERE action='user.bank_account.reveal'") == []
    _shot(p2, "3_cashier_masked")
    p2.click("[data-testid=ba-reveal]")
    p2.wait_for_function("(n) => document.querySelector('[data-testid=ba-target-number]').innerText === n", arg=NUM, timeout=10000)
    rev = _db("SELECT username, detail FROM audit_log WHERE action='user.bank_account.reveal'")
    assert len(rev) == 1 and rev[0]["username"] == "bae_cash" and json.loads(rev[0]["detail"])["last4"] == "4556"
    assert NUM not in json.dumps(_db("SELECT * FROM audit_log"), ensure_ascii=False), "稽核紀錄不可含全碼"
    _shot(p2, "4_cashier_revealed")


@pytest.mark.e2e
def test_finance_maintains_someone_elses_account_and_history_shows(live_server, make_user, e2e_browser):
    make_user(username="bae_o3", role="viewer", modules=[])
    fin = make_user(username="bae_fin", role="viewer", modules=["finance"])
    page = _open(e2e_browser, live_server, fin)
    page.wait_for_selector("[data-testid=ba-admin]", state="visible", timeout=20000)
    opt = page.locator("[data-testid=ba-user-select] option", has_text="bae_o3")
    page.select_option("[data-testid=ba-user-select]", label=opt.inner_text())
    page.wait_for_selector("[data-testid=ba-a-save]", state="visible")
    assert page.locator("[data-testid=ba-target-none]").is_visible()
    _fill(page, "ba-a-")
    page.click("[data-testid=ba-a-save]")
    page.wait_for_selector("[data-testid=ba-a-msg]", state="visible")
    rows = _db("SELECT active, account_number, created_by FROM user_bank_accounts WHERE username='bae_o3'")
    assert rows == [{"active": 1, "account_number": NUM, "created_by": "bae_fin"}]
    upd = _db("SELECT detail FROM audit_log WHERE action='user.bank_account.update'")
    assert json.loads(upd[-1]["detail"])["byAdmin"] is True
    page.wait_for_selector("[data-testid=ba-history] li", timeout=10000)
    assert "（目前）" in page.inner_text("[data-testid=ba-history]")
    _shot(page, "5_finance_maintained")


@pytest.mark.e2e
def test_page_fits_a_narrow_screen(live_server, make_user, e2e_browser):
    u = make_user(username="bae_narrow", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u, width=390)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "窄螢幕不可橫向捲動"
    _shot(page, "6_narrow")
