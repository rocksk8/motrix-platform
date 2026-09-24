# -*- coding: utf-8 -*-
"""`JV32` · 傳票金額輸入：`1,000` 不可以被存成 0，小數不可以被靜默截斷。

權威原文：`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` 後半段 `JV32`。

```
接受    "1,000"、全形「１，０００」、前後空白、"1000.00"（小數部分全是 0）
擋下    小數（"12.5"、JSON 的 12.5）⇒ 422「金額以新台幣元為單位，不可有小數」
        同一行借貸都填、負數 ⇒ 422 並指出第幾行
前後端都擋；後端 `int()` 截斷路徑拿掉
```

# 🔴 HEAD 上的兩種壞法，兩種都**不報錯**

```
前端  Number("1,000") = NaN ⇒ `|| 0` ⇒ 送 0      ⇒ 畫面說「已儲存」，金額變 0
後端  int(12.5) = 12                              ⇒ 存進去的是 12，沒有人被告知
```
⚙️ 觀測點是**資料庫裡存進去的數字**（讀回傳票），不是回應碼。
"""
import json

import pytest

VOUCHERS = "/api/vouchers"


def _hdr(client, make_user, username):
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _lines(d1, c1, d2=0, c2=None):
    return [{"account_code": "1113", "debit": d1, "credit": c1},
            {"account_code": "4111", "debit": d2, "credit": d1 if c2 is None else c2}]


def _stored(client, hdr, vid):
    r = client.get("%s/%s" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    return [(ln["debit"], ln["credit"]) for ln in r.json()["lines"]]


def _count():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM vouchers_all").fetchone()["n"]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 接受：千分位、全形、空白、.00
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw", ["1,000", "１，０００", "  1000 ", "1000.00", "１０００"])
def test_jv32_formatted_amounts_are_stored_as_the_number(client, make_user, raw):
    hdr = _hdr(client, make_user, "jv32_ok")
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": "JV32", "lines": _lines(raw, 0, 0, raw)})
    assert r.status_code == 200, "%r 被拒絕：%s %s" % (raw, r.status_code, r.text[:200])
    assert _stored(client, hdr, r.json()["id"]) == [(1000, 0), (0, 1000)], (
        "輸入 %r，存進去的是 %r" % (raw, _stored(client, hdr, r.json()["id"])))


# ══════════════════════════════════════════════════════════════════════
# 擋下：小數、借貸都填、負數——而且什麼都不寫入
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw", ["12.5", 12.5, "1,000.5"])
def test_jv32_a_decimal_amount_is_rejected_not_truncated(client, make_user, raw):
    hdr = _hdr(client, make_user, "jv32_dec")
    before = _count()
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": "JV32", "lines": _lines(raw, 0, 0, 1000)})
    assert r.status_code == 422, (
        "小數 %r 沒有被擋下（%s）：%s" % (raw, r.status_code, r.text[:200]))
    detail = r.json().get("detail", "")
    assert "不可有小數" in detail and "第 1 行" in detail, detail
    assert _count() == before, "被擋下了，傳票卻已經建立"


def test_jv32_a_line_with_both_debit_and_credit_is_rejected_with_its_line_number(
        client, make_user):
    hdr = _hdr(client, make_user, "jv32_both")
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": "JV32", "lines": _lines(1000, 0, 500, 1000)})
    assert r.status_code == 422, "借貸都填沒有被擋下：%s %s" % (r.status_code, r.text[:200])
    assert "第 2 行" in r.json().get("detail", ""), r.json()


def test_jv32_a_negative_amount_is_rejected_with_its_line_number(client, make_user):
    hdr = _hdr(client, make_user, "jv32_neg")
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": "JV32", "lines": _lines(1000, 0, 0, "-1000")})
    assert r.status_code == 422, "負數沒有被擋下：%s %s" % (r.status_code, r.text[:200])
    assert "第 2 行" in r.json().get("detail", ""), r.json()


def test_jv32_editing_an_existing_draft_applies_the_same_rules(client, make_user):
    """PUT（既有草稿改分錄）走同一套：千分位存得進去、小數擋下且原分錄不動。"""
    hdr = _hdr(client, make_user, "jv32_put")
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": "JV32", "lines": _lines(100, 0)})
    assert r.status_code == 200, r.text[:200]
    vid = r.json()["id"]

    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"lines": _lines("12.5", 0, 0, 1000)})
    assert r.status_code == 422, "PUT 小數沒有被擋下：%s %s" % (r.status_code, r.text[:200])
    assert _stored(client, hdr, vid) == [(100, 0), (0, 100)], "被擋下了，分錄卻已經被改掉"

    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr,
                   json={"lines": _lines("2,500", 0)})
    assert r.status_code == 200, r.text[:200]
    assert _stored(client, hdr, vid) == [(2500, 0), (0, 2500)]


# ══════════════════════════════════════════════════════════════════════
# 前端：畫面上打「1,000」存回來是 1000；打「12.5」畫面說出原因、不送出
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402


def _fill_new_voucher(page, base, d1, c2):
    page.goto(base + "/pages/voucher.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]')).lines",
                           timeout=15000)
    # ⚠️ 編輯區（`x-show="editing"`）要按「新增傳票」才出現——第一版漏了這步，
    #    在 HEAD 上紅成「element is not visible」逾時，那是探針壞了不是產品紅。
    page.click('[data-testid="voucher-new"]')
    rows = page.locator("tbody tr:has(input[x-model='l.account_code'])")
    rows.nth(0).locator("input[x-model='l.account_code']").fill("1113")
    rows.nth(0).locator("input[x-model='l.debit']").fill(d1)
    rows.nth(1).locator("input[x-model='l.account_code']").fill("4111")
    rows.nth(1).locator("input[x-model='l.credit']").fill(c2)
    page.click('[data-testid="voucher-save"]')


@pytest.mark.e2e
def test_jv32_on_the_page_typing_1_comma_000_saves_1000(live_server, make_user, e2e_browser):
    u, p = make_user(username="jv32_page", role="superadmin", modules=["cashier"])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _login(page, live_server, u, p)
    token = page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")
    _fill_new_voucher(page, live_server, "1,000", "１，０００")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('[x-data]')).id"
        " || Alpine.$data(document.querySelector('[x-data]')).actionErr",
        timeout=15000)
    st = page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                       " return {id: d.id, err: d.actionErr} }")
    assert st["id"], "畫面沒有存成功：%r" % st
    r = page.request.get("%s/api/vouchers/%s" % (live_server, st["id"]),
                         headers={"Authorization": "Bearer " + token})
    got = [(ln["debit"], ln["credit"]) for ln in r.json()["lines"]]
    print("JV32 頁面實測：輸入 '1,000'／'１，０００' ⇒ 存入", got)
    assert got == [(1000, 0), (0, 1000)], (
        "畫面上打 1,000，資料庫存的是 %r（HEAD：Number('1,000') = NaN ⇒ 0）" % got)


@pytest.mark.e2e
def test_jv32_on_the_page_a_decimal_is_explained_and_nothing_is_saved(live_server, make_user, e2e_browser):
    u, p = make_user(username="jv32_page_dec", role="superadmin", modules=["cashier"])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    posts = []
    page.on("request", lambda req: posts.append(req.url)
            if req.method == "POST" and req.url.endswith("/api/vouchers") else None)
    _login(page, live_server, u, p)
    _fill_new_voucher(page, live_server, "12.5", "12.5")
    err = page.locator(".vc-err").first
    err.wait_for(state="visible", timeout=10000)
    text = err.inner_text()
    print("JV32 頁面實測：輸入 '12.5' ⇒ 畫面訊息", repr(text), "；POST 次數", len(posts))
    assert "不可有小數" in text and "第 1 行" in text, text
    assert posts == [], "前端應該先擋下，不送出：%r" % posts
