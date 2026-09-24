# -*- coding: utf-8 -*-
"""`JV31` · 傳票簽章加「記帳」；畫面簽章格依實際層數顯示（商業會計法 §35）。

權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md` `JV31`。

```
過帳記錄 posted_by／posted_at（欄位早已存在，`post_voucher()` 早已寫入）
PDF 與畫面簽章欄加「記帳」
畫面簽章欄依實際層數顯示，不固定 3 格
```
§35：記帳憑證應由負責人、經理人、主辦及經辦會計人員簽名或蓋章 ⇒ 過帳的人要在憑證上。

# 🔴 HEAD 上的現況

`signatures_of()` 只回「製票＋各層」，沒有記帳那一格 ⇒ PDF 上沒有過帳的人；
畫面寫死「製票／覆核／主管」三格 ⇒ 設定四層時第三、四層的簽名**畫面上看不到**。
"""
import pytest

VOUCHERS = "/api/vouchers"
_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _login(client, make_user, username, display=None):
    import db
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    if display:
        conn = db.get_db()
        try:
            conn.execute("UPDATE users SET display_name=? WHERE username=?", (display, u))
            conn.commit()
        finally:
            conn.close()
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _clear_flow():
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM system_settings WHERE key IN"
                     " ('voucher_approval_flow', 'unified_approval_flow')")
        conn.commit()
    finally:
        conn.close()


def _approved_voucher(client, hdr):
    """內建兩層：建立、送審、簽兩次 ⇒ 已核准。"""
    _clear_flow()
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV31", "lines": _LINES})
    assert r.status_code == 200, r.text[:200]
    vid = r.json()["id"]
    for step in ("submit", "approve", "approve"):
        r = client.post("%s/%s/%s" % (VOUCHERS, vid, step), headers=hdr)
        assert r.status_code == 200, (step, r.text[:200])
    return vid


def _sigs(client, hdr, vid):
    r = client.get("%s/%s" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    return r.json().get("signatures") or {}


def test_jv31_a_posted_voucher_carries_the_bookkeeper_signature(client, make_user):
    u, hdr = _login(client, make_user, "jv31_poster", display="記帳王小明")
    vid = _approved_voucher(client, hdr)

    before = _sigs(client, hdr, vid)
    assert "記帳" in before, "簽章沒有「記帳」這一格：%r" % list(before)
    assert before["記帳"]["by"] == "", "還沒過帳，記帳那一格就有人：%r" % before["記帳"]
    assert list(before)[-1] == "記帳", "「記帳」要在最後一格：%r" % list(before)

    r = client.post("%s/%s/post" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    after = _sigs(client, hdr, vid)
    assert after["記帳"]["by"] == "記帳王小明", "過帳後記帳格是 %r" % after["記帳"]
    assert after["記帳"]["at"], "記帳格沒有時間"

    html = client.get("%s/%s/preview" % (VOUCHERS, vid), headers=hdr).text
    assert "記帳" in html and "記帳王小明" in html, "PDF 版面上沒有記帳人"


# ══════════════════════════════════════════════════════════════════════
# 畫面：簽章格依實際層數（四層 ⇒ 製票＋4 層＋記帳 ＝ 6 格）
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login as _page_login  # noqa: E402


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return int(conn.execute("SELECT id FROM users WHERE username=?",
                                (username,)).fetchone()["id"])
    finally:
        conn.close()


def _labels_on_page(page, base, vid):
    page.goto(f"{base}/pages/voucher.html?id={vid}")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('[x-data]')).id == %d" % vid, timeout=15000)
    _rendered(page)   # PERF #6：原本固定等 300ms
    return page.eval_on_selector_all(
        '[data-testid="voucher-signs"] > div > span', "els => els.map(e => e.innerText.trim())")


@pytest.mark.e2e
def test_jv31_the_page_shows_one_sign_cell_per_tier_plus_maker_and_bookkeeper(
        live_server, client, make_user, e2e_browser):
    su, sp = make_user(username="jv31_page", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": su, "password": sp})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    approvers = []
    for n in range(4):
        u, _p = make_user(username="jv31_t%d" % n, role="superadmin", modules=["cashier"])
        approvers.append({"userId": _user_id(u), "username": u, "displayName": u})
    r = client.put("/api/settings/approval-flow/voucher", headers=hdr, json={
        "includeSubmitterManagerTier": False, "tiers": [{"approvers": [a]} for a in approvers]})
    assert r.status_code == 200, r.text[:200]
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV31", "lines": _LINES})
    four = r.json()["id"]
    assert client.post("%s/%s/submit" % (VOUCHERS, four), headers=hdr).status_code == 200

    _clear_flow()
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV31", "lines": _LINES})
    builtin = r.json()["id"]

    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _page_login(page, live_server, su, sp)
    got4 = _labels_on_page(page, live_server, four)
    got2 = _labels_on_page(page, live_server, builtin)
    print("JV31 頁面實測：四層 ⇒", got4, "／內建兩層 ⇒", got2)
    assert len(got4) == 6 and got4[0] == "製票" and got4[-1] == "記帳", got4
    assert got2 == ["製票", "覆核", "主管", "記帳"], got2
