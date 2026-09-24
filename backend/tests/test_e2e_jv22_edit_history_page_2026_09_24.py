# -*- coding: utf-8 -*-
"""`JV22` 的**頁面那一半**（`SPEC-JV22.md` §7 ③ ⓐ–ⓓ）：傳票頁看得到「退回與編修」。

```
ⓐ 退回（填原因）-> 改欄位 -> 重新開這張單 => 看得到原因、看得到欄位 from/to
ⓑ 再退回一次再改 => 預設展開最近那一組，舊的收合
ⓒ 作廢之後 => 仍然看得到
ⓓ 那一區的 DOM 裡沒有 input／textarea／contenteditable
```
題名刻意不以 `test_jv22_` 開頭：`JV22` 的信用由 API 那一檔承擔（同號兩檔會被守門判撞名）。
⚙️ 伺服器／登入寫法照抄 `test_e2e_voucher_feedback_2026_09_23.py`（本機 chromium）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._ports import free_safe_port

SECTION = '[data-testid="voucher-edit-history"]'
_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]




def _api(client, hdr, method, path, body=None):
    r = getattr(client, method)(path, headers=hdr, json=body or {})
    assert r.status_code == 200, "%s %s -> %s %s" % (method, path, r.status_code, r.text[:160])
    return r.json()


def _section_state(live_server, u, p, vid, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    page.goto("%s/pages/login.html" % live_server)
    page.fill('input[x-model="username"]', u)
    page.fill('input[x-model="password"]', p)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto("%s/pages/voucher.html?id=%s" % (live_server, vid))
    page.wait_for_selector(SECTION, state="visible", timeout=15000)
    sec = page.locator(SECTION)
    visible_text = sec.inner_text()
    controls = sec.locator("input, textarea, [contenteditable]").count()
    opened = sec.locator("details[open]").count()
    total = sec.locator("details").count()
    return visible_text, controls, opened, total


@pytest.mark.e2e
def test_the_voucher_page_shows_send_back_and_edits_read_only(live_server, client, make_user, e2e_browser):
    u, p = make_user("jv22p_sa", role="superadmin", modules=["cashier"])
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}
    vid = _api(client, hdr, "post", "/api/vouchers", {"summary": "文具", "lines": _LINES})["id"]

    _api(client, hdr, "post", "/api/vouchers/%s/submit" % vid)
    _api(client, hdr, "post", "/api/vouchers/%s/send-back" % vid, {"reason": "第一次：科目選錯"})
    _api(client, hdr, "put", "/api/vouchers/%s" % vid, {"summary": "辦公用品"})
    _api(client, hdr, "post", "/api/vouchers/%s/submit" % vid)
    _api(client, hdr, "post", "/api/vouchers/%s/send-back" % vid, {"reason": "第二次：摘要要寫清楚"})
    _api(client, hdr, "put", "/api/vouchers/%s" % vid, {"summary": "辦公用品（九月）"})

    text, controls, opened, total = _section_state(live_server, u, p, vid, e2e_browser=e2e_browser)
    assert "第二次：摘要要寫清楚" in text, "最近一次退回的原因不在畫面上：%r" % text[:300]
    assert "辦公用品 → 辦公用品（九月）" in text, "最近一次之後的編修沒有 from→to：%r" % text[:300]
    assert (opened, total) == (1, 2), "預期兩組、只展開最近一組；實得 展開 %d／共 %d" % (opened, total)
    assert controls == 0, "「退回與編修」區裡有 %d 個可編輯控制項 —— 這一區必須唯讀" % controls

    _api(client, hdr, "post", "/api/vouchers/%s/void" % vid, {"reason": "重開"})
    text2, _c, _o, total2 = _section_state(live_server, u, p, vid, e2e_browser=e2e_browser)
    assert "第二次：摘要要寫清楚" in text2 and total2 == 2, "作廢之後紀錄不見了：%r" % text2[:300]
