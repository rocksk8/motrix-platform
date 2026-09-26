# -*- coding: utf-8 -*-
"""`JV29` · 傳票類別：依分錄自動判斷收入／支出／轉帳，畫面唯讀顯示、PDF 印傳票名稱。

權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md` `JV29` ＋ A 2026-09-24 夜間裁示：

```
自動判斷＋只顯示，不給選單（JV20 使用者原話「傳票不需要有類別的選項」仍成立）
存檔時伺服器依分錄重算（新存、編輯都算，只限草稿）；既有資料的 '轉' 不回頭重算
現金類＝沿 parent_code 往上走得到 111（現金及約當現金），不用代號前綴
淨額在借方＝收入、在貸方＝支出、0（含沒有現金類）＝轉帳
「手動改」延後（待確認 N6）
```
📌 更正留著：`N6` 已由使用者 2026-09-24 晨間表單裁定「要能手動改」⇒ 草稿有類別選單
（含「恢復自動判斷」），手動過的不再被分錄覆蓋；題在本檔最後一段。
依據：商業會計法 §17（收入／支出／轉帳傳票）、商業會計處理準則 §6（記帳憑證要有傳票名稱）。

# ⚙️ 種子資料裡判定為現金類的完整清單（`data/account_items_112.json`）

```
111  現金及約當現金      1111 庫存現金      1112 零用金／週轉金
1113 銀行存款            1114 在途現金      1115 約當現金
```
"""
import pytest

VOUCHERS = "/api/vouchers"
CASH_FAMILY = {"111", "1111", "1112", "1113", "1114", "1115"}


def _hdr(client, make_user, username):
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _ln(code, d, c):
    return {"account_code": code, "debit": d, "credit": c}


def _category(vid):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT category FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        conn.close()


def _create(client, hdr, lines, **extra):
    r = client.post(VOUCHERS, headers=hdr, json=dict({"summary": "JV29", "lines": lines}, **extra))
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def test_jv29_the_cash_family_is_found_by_walking_parent_codes(client):
    """量尺：現金類清單就是上面那六個——用結構（parent_code）判，不是前綴。"""
    import db
    from modules.accounting.voucher import cash_account_codes
    conn = db.get_db()
    try:
        got = cash_account_codes(conn)
    finally:
        conn.close()
    assert got == CASH_FAMILY, "現金類清單是 %r，應該是 %r" % (sorted(got), sorted(CASH_FAMILY))


@pytest.mark.parametrize("lines,expect", [
    ([_ln("1113", 1000, 0), _ln("4111", 0, 1000)], "收"),
    ([_ln("6111", 1000, 0), _ln("1113", 0, 1000)], "支"),
    ([_ln("6111", 1000, 0), _ln("2111", 0, 1000)], "轉"),
    # 銀行轉存：借貸兩邊都是現金類，淨額 0 ⇒ 轉帳
    ([_ln("1113", 1000, 0), _ln("1111", 0, 1000)], "轉"),
], ids=["cash-in", "cash-out", "no-cash", "cash-to-cash"])
def test_jv29_saving_a_draft_sets_the_category_from_its_lines(client, make_user, lines, expect):
    hdr = _hdr(client, make_user, "jv29_cls")
    vid = _create(client, hdr, lines)
    assert _category(vid) == expect, "分錄 %r ⇒ 類別 %r，應該是 %r" % (lines, _category(vid), expect)


def test_jv29_a_custom_account_under_111_counts_as_cash(client, make_user):
    """自訂科目掛在 111 底下 ⇒ 也是現金類（用前綴判的實作一樣會中，所以用 9 開頭的代號）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES (?,?,?,?,'custom',1)", ("9119", 4, "自訂零用金", "111"))
        conn.commit()
    finally:
        conn.close()
    hdr = _hdr(client, make_user, "jv29_custom")
    vid = _create(client, hdr, [_ln("9119", 500, 0), _ln("4111", 0, 500)])
    assert _category(vid) == "收", _category(vid)


def test_jv29_the_client_cannot_override_the_category(client, make_user):
    """沒有明說要手動（`category_manual`）時，請求帶的 category 不採用，以分錄判斷為準。
    📌 更正留著：原本寫「手動改延後（N6）」；N6 之後手動要明著帶 `category_manual: true`。"""
    hdr = _hdr(client, make_user, "jv29_override")
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)], category="支")
    assert _category(vid) == "收"


def test_jv29_editing_the_lines_of_a_draft_recomputes_the_category(client, make_user):
    hdr = _hdr(client, make_user, "jv29_put")
    vid = _create(client, hdr, [_ln("6111", 1000, 0), _ln("2111", 0, 1000)])
    assert _category(vid) == "轉"
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"lines": [_ln("6111", 1000, 0), _ln("1113", 0, 1000)]})
    assert r.status_code == 200, r.text[:200]
    assert _category(vid) == "支", "改了分錄，類別沒有重算：%r" % _category(vid)


def test_jv29_existing_rows_are_not_recomputed_on_read(client, make_user):
    """既有資料的 '轉' 不回頭重算：讀取（GET）不會改寫類別。"""
    import db
    hdr = _hdr(client, make_user, "jv29_legacy")
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)])
    conn = db.get_db()
    try:
        conn.execute("UPDATE vouchers_all SET category='轉' WHERE id=?", (vid,))
        conn.commit()
    finally:
        conn.close()
    r = client.get("%s/%s" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200
    assert _category(vid) == "轉"


@pytest.mark.parametrize("lines,title", [
    ([_ln("1113", 1000, 0), _ln("4111", 0, 1000)], "收入傳票"),
    ([_ln("6111", 1000, 0), _ln("1113", 0, 1000)], "支出傳票"),
    ([_ln("6111", 1000, 0), _ln("2111", 0, 1000)], "轉帳傳票"),
], ids=["收", "支", "轉"])
def test_jv29_the_pdf_layout_prints_the_voucher_name(client, make_user, lines, title):
    """PDF 與預覽共用 `build_html()` ⇒ 看預覽 HTML 的標題（準則 §6：記帳憑證要有傳票名稱）。"""
    hdr = _hdr(client, make_user, "jv29_pdf")
    vid = _create(client, hdr, lines)
    r = client.get("%s/%s/preview" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    assert '<div class="doc">%s</div>' % title in r.text, (
        "標題不是「%s」：%s" % (title, r.text[r.text.find('class="doc"') - 5:][:60]))


# ══════════════════════════════════════════════════════════════════════
# 畫面：唯讀顯示傳票名稱（不是選單）
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402


@pytest.mark.e2e
def test_jv29_the_page_shows_the_voucher_name_read_only(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="jv29_page", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    vid = _create(client, hdr, [_ln("6111", 1000, 0), _ln("1113", 0, 1000)])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    el = page.locator('[data-testid="voucher-kind"]')
    el.wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "() => (document.querySelector('[data-testid=\"voucher-kind\"]').innerText || '')"
        ".includes('傳票')", timeout=10000)
    text = el.inner_text().strip()
    tag = el.evaluate("e => e.tagName")
    print("JV29 頁面實測：傳票名稱 =", repr(text), "／元素", tag)
    assert text == "支出傳票", text
    assert tag not in ("SELECT", "INPUT"), "傳票名稱要唯讀顯示，不是 %s" % tag


# ══════════════════════════════════════════════════════════════════════
# `N6`：類別可以手動改（使用者 2026-09-24 晨間表單「要能手動改」，推翻 09-23 JV20
#       「傳票不需要有類別的選項」）。手動過的，改分錄不再自動覆蓋；可恢復自動判斷。
# ══════════════════════════════════════════════════════════════════════

def _manual(vid):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT category_manual FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        conn.close()


def test_jv29_a_manual_category_is_kept_and_survives_line_edits(client, make_user):
    hdr = _hdr(client, make_user, "jv29_manual")
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)],
                  category="支", category_manual=True)
    assert (_category(vid), _manual(vid)) == ("支", 1), "手動指定沒有被採用：%r" % (
        (_category(vid), _manual(vid)),)
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"lines": [_ln("6111", 800, 0), _ln("2111", 0, 800)]})
    assert r.status_code == 200, r.text[:200]
    assert (_category(vid), _manual(vid)) == ("支", 1), "手動過的類別被改分錄覆蓋了：%r" % (
        (_category(vid), _manual(vid)),)


def test_jv29_restoring_auto_recomputes_from_the_lines(client, make_user):
    hdr = _hdr(client, make_user, "jv29_restore")
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)],
                  category="轉", category_manual=True)
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr, json={"category_manual": False})
    assert r.status_code == 200, r.text[:200]
    assert (_category(vid), _manual(vid)) == ("收", 0), (_category(vid), _manual(vid))


def test_jv29_switching_to_manual_on_an_existing_draft_and_bad_values(client, make_user):
    hdr = _hdr(client, make_user, "jv29_put_manual")
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)])
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"category": "甲", "category_manual": True})
    assert r.status_code == 422, "不合法的類別沒有擋：%s %s" % (r.status_code, r.text[:200])
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"category": "轉", "category_manual": True})
    assert r.status_code == 200, r.text[:200]
    assert (_category(vid), _manual(vid)) == ("轉", 1)
    assert client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr).status_code == 200
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"category": "支", "category_manual": True})
    assert r.status_code == 400, "送審後還能改類別：%s" % r.status_code
    assert _category(vid) == "轉"


@pytest.mark.e2e
def test_jv29_the_page_lets_a_draft_pick_the_category_by_hand(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="jv29_pick", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    vid = _create(client, hdr, [_ln("1113", 1000, 0), _ln("4111", 0, 1000)])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    sel = page.locator('[data-testid="voucher-kind-select"]')
    sel.wait_for(state="visible", timeout=15000)
    before = sel.input_value()
    sel.select_option("支")
    page.click('[data-testid="voucher-save"]')
    page.wait_for_function(
        "() => (document.querySelector('[data-testid=\"voucher-kind\"]').innerText || '')"
        ".includes('支出傳票') && !Alpine.$data(document.querySelector('[x-data]')).busy",
        timeout=10000)
    page.reload()
    sel.wait_for(state="visible", timeout=15000)
    after = (sel.input_value(), page.locator('[data-testid="voucher-kind"]').inner_text().strip())
    print("N6 頁面實測：選單原本 %r ⇒ 選支出、存檔、重整 ⇒ %r" % (before, after))
    assert before == "auto", before
    assert after == ("支", "支出傳票"), after
    assert (_category(vid), _manual(vid)) == ("支", 1)
