# -*- coding: utf-8 -*-
"""`JV34` · 傳票輸入與列印（使用者表單原文：「輸入與列印體驗：科目搜尋選擇、Enter 新增行、
補平差額、附件張數與頁碼、清單搜尋篩選、作廢並重開」）。

權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md` `JV34` ＋ A 2026-09-24 裁示：

```
① 科目：可搜尋選單（代號或名稱，停用的標「（停用）」）；科目名稱欄唯讀
② 最後一行按 Enter ⇒ 新增一行；「補平差額」：目前這一行借貸都空白、差額 ≠ 0 才可按，
   差額填在合計較少的那一側
③ PDF：表頭列「附件 N 張」、頁碼「第 x／y 頁」（只編傳票本體，不蓋在併入的 PDF 附件上）、
   跨頁重印表頭
④ 清單：關鍵字（號碼／摘要）、日期區間、狀態篩選
⑤ 作廢時可勾「作廢並重開」（後端 reopen 早已支援）
```

# ⚠️ 頁碼用 CSS `@page` 頁邊框：Chromium／Edge **131 以上**才支援；
#    舊版的後果是「頁碼不出現」，不會報錯。開發機量測時的 Edge 版本：**153.0.4234.48**
#    （`msedge.exe` ProductVersion，2026-09-24）。正式機版本未知——交付說明要寫。
"""
import io
import json
import re
import unicodedata

import pytest

VOUCHERS = "/api/vouchers"
_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _hdr(client, make_user, username):
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _clear_flow():
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM system_settings WHERE key IN"
                     " ('voucher_approval_flow', 'unified_approval_flow')")
        conn.commit()
    finally:
        conn.close()


def _approved(client, hdr, lines):
    _clear_flow()
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV34", "lines": lines})
    assert r.status_code == 200, r.text[:200]
    vid = r.json()["id"]
    for step in ("submit", "approve", "approve"):
        assert client.post("%s/%s/%s" % (VOUCHERS, vid, step), headers=hdr).status_code == 200
    return vid


def _pdf_pages_text(body):
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(body))
    return [unicodedata.normalize("NFKC", p.extract_text() or "") for p in reader.pages]


# ══════════════════════════════════════════════════════════════════════
# ③ PDF：附件張數、頁碼、跨頁重印表頭
# ══════════════════════════════════════════════════════════════════════

def test_jv34_the_layout_head_shows_the_attachment_count(client, make_user):
    hdr = _hdr(client, make_user, "jv34_att")
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV34", "lines": _LINES})
    vid = r.json()["id"]
    for name in ("a.png", "b.pdf"):
        up = client.post("%s/%s/attachments" % (VOUCHERS, vid), headers=hdr,
                         files={"files": (name, b"x", "application/octet-stream")})
        assert up.status_code == 200, up.text[:200]
    html = client.get("%s/%s/preview" % (VOUCHERS, vid), headers=hdr).text
    head = html[html.find('class="head"'):][:400]
    assert "附件 2 張" in head, "表頭列沒有「附件 N 張」：%s" % head


def test_jv34_a_multi_page_pdf_numbers_its_pages_and_repeats_the_header(client, make_user):
    hdr = _hdr(client, make_user, "jv34_pages")
    lines = []
    for n in range(40):
        lines.append({"account_code": "6111", "debit": 100, "credit": 0,
                      "summary": "第 %d 筆跨頁測試摘要文字" % (n + 1)})
    lines.append({"account_code": "1113", "debit": 0, "credit": 4000})
    vid = _approved(client, hdr, lines)
    r = client.get("%s/%s/pdf-download" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    pages = _pdf_pages_text(r.content)
    n = len(pages)
    print("JV34 PDF 實測：%d 頁；各頁頁碼 %r" % (
        n, [re.findall(r"第\s*\d+\s*/\s*\d+\s*頁", t) for t in pages]))
    assert n >= 2, "量尺：40 行分錄沒有跨頁（%d 頁）——下面量不到跨頁" % n
    for i, t in enumerate(pages, start=1):
        compact = re.sub(r"\s+", "", t)
        assert "第%d/%d頁" % (i, n) in compact, "第 %d 頁沒有「第 %d／%d 頁」：%r" % (i, i, n, t[-120:])
        assert "會計科目" in compact, "第 %d 頁沒有重印表頭" % i


# ══════════════════════════════════════════════════════════════════════
# ①②④⑤ 畫面
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402

_D = "() => Alpine.$data(document.querySelector('[x-data]'))"


def _browser(p_):
    browser = p_   # PERF #5：共用瀏覽器（e2e_browser 外殼）
    return browser, browser.new_page(viewport={"width": 1280, "height": 900})


def _new_voucher(page, base):
    page.goto(base + "/pages/voucher.html")
    page.wait_for_function(_D + ".lines", timeout=15000)
    page.click('[data-testid="voucher-new"]')
    _rendered(page)   # PERF #6：原本固定等 300ms


def _rows(page):
    return page.locator("tbody tr:has(input[x-model='l.account_code'])")


@pytest.mark.e2e
def test_jv34_the_account_picker_searches_code_and_name_and_marks_inactive(
        live_server, client, make_user, e2e_browser):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES (?,?,?,?,'custom',0)", ("9934", 4, "停用的自訂科目", "111"))
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(username="jv34_pick", role="superadmin", modules=["cashier"])
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _browser(p_)
    try:
        _login(page, live_server, u, p)
        _new_voucher(page, live_server)
        code = _rows(page).nth(0).locator("input[x-model='l.account_code']")
        lid = code.get_attribute("list")
        assert lid, "科目代號欄沒有接可搜尋的選單（list 屬性）"
        page.wait_for_function("id => document.querySelectorAll('#' + id + ' option').length > 100",
                               arg=lid, timeout=10000)
        opts = page.eval_on_selector_all("#%s option" % lid,
                                         "os => os.map(o => [o.value, o.label || o.textContent])")
        by = {v: lab for v, lab in opts}
        print("JV34 頁面實測：選單 %d 項；1113 ⇒ %r；9934 ⇒ %r" % (len(opts), by.get("1113"), by.get("9934")))
        assert "銀行存款" in (by.get("1113") or ""), "選項沒有名稱可搜尋：%r" % by.get("1113")
        assert "停用" in (by.get("9934") or ""), "停用科目沒有標示：%r" % by.get("9934")
        name = _rows(page).nth(0).locator("input[x-model='l.account_name']")
        assert name.get_attribute("readonly") is not None, "科目名稱欄應該唯讀"
        code.fill("1113")
        code.dispatch_event("change")
        page.wait_for_function(_D + ".lines[0].account_name === '銀行存款'", timeout=5000)
    finally:
        browser.close()


@pytest.mark.e2e
def test_jv34_enter_on_the_last_line_adds_a_line_and_balance_fills_the_gap(
        live_server, make_user, e2e_browser):
    u, p = make_user(username="jv34_enter", role="superadmin", modules=["cashier"])
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _browser(p_)
    try:
        _login(page, live_server, u, p)
        _new_voucher(page, live_server)
        n0 = page.evaluate(_D + ".lines.length")
        last = _rows(page).nth(n0 - 1).locator("input[x-model='l.credit']")
        last.click()
        last.press("Enter")
        n1 = page.evaluate(_D + ".lines.length")
        assert n1 == n0 + 1, "最後一行按 Enter 沒有新增一行（%d ⇒ %d）" % (n0, n1)

        _rows(page).nth(0).locator("input[x-model='l.debit']").fill("1,500")
        btn = page.locator('[data-testid="voucher-balance"]')
        _rows(page).nth(0).locator("input[x-model='l.debit']").click()
        assert btn.is_disabled(), "目前這一行已有金額，補平差額應該不可按"
        _rows(page).nth(1).locator("input[x-model='l.credit']").click()
        assert btn.is_enabled(), "第 2 行借貸都空白、差額 1500，補平差額應該可按"
        btn.click()
        got = page.evaluate(_D + ".lines[1]")
        print("JV34 頁面實測：補平差額 ⇒ 第 2 行 借 %r 貸 %r" % (got["debit"], got["credit"]))
        assert str(got["credit"]).replace(",", "") == "1500" and not got["debit"], got
        _rows(page).nth(2).locator("input[x-model='l.credit']").click()
        assert btn.is_disabled(), "已平衡（差額 0），補平差額應該不可按"
    finally:
        browser.close()


@pytest.mark.e2e
def test_jv34_the_list_filters_by_keyword_date_and_status(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="jv34_list", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    ids = {}
    for key, date in (("甲蘋果", "2026-09-01"), ("乙香蕉", "2026-09-10"), ("丙櫻桃", "2026-09-20")):
        r = client.post(VOUCHERS, headers=hdr, json={"summary": key, "lines": _LINES,
                                                     "voucher_date": date})
        ids[key] = r.json()["id"]
    assert client.post("%s/%s/submit" % (VOUCHERS, ids["丙櫻桃"]), headers=hdr).status_code == 200
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _browser(p_)
    try:
        _login(page, live_server, u, p)
        page.goto(live_server + "/pages/voucher.html")
        page.wait_for_function(_D + ".listLoaded", timeout=15000)

        def visible():
            _rendered(page)   # PERF #6：原本固定等 200ms（清單篩選是同步反應）
            return sorted(t.strip() for t in page.locator(".vc-row:visible .vc-row__sum").all_inner_texts())

        page.fill('[data-testid="voucher-filter-kw"]', "香蕉")
        kw = visible()
        page.fill('[data-testid="voucher-filter-kw"]', "")
        page.fill('[data-testid="voucher-filter-from"]', "2026-09-05")
        page.fill('[data-testid="voucher-filter-to"]', "2026-09-15")
        dr = visible()
        page.fill('[data-testid="voucher-filter-from"]', "")
        page.fill('[data-testid="voucher-filter-to"]', "")
        page.select_option('[data-testid="voucher-filter-status"]', "待審核")
        st = visible()
        print("JV34 頁面實測：關鍵字 ⇒", kw, "／日期 ⇒", dr, "／狀態 ⇒", st)
        assert kw == ["乙香蕉"], kw
        assert dr == ["乙香蕉"], dr
        assert st == ["丙櫻桃"], st
    finally:
        browser.close()


@pytest.mark.e2e
def test_jv34_void_and_reopen_from_the_page_opens_the_new_draft(live_server, client, make_user, e2e_browser):
    u, p = make_user(username="jv34_void", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "要重開的", "lines": _LINES})
    vid, old_no = r.json()["id"], r.json()["voucher_no"]
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _browser(p_)
    try:
        _login(page, live_server, u, p)
        page.goto(f"{live_server}/pages/voucher.html?id={vid}")
        page.wait_for_function(_D + ".id == %d" % vid, timeout=15000)
        page.click('button:has-text("作廢")')
        page.fill('[data-testid="voucher-reason"]', "科目整張挑錯")
        page.check('[data-testid="voucher-void-reopen"]')
        page.click('[data-testid="voucher-reason-ok"]')
        page.wait_for_function(
            "v => { const d = Alpine.$data(document.querySelector('[x-data]'));"
            " return d.id && d.id != v && d.status === '草稿' }", arg=vid, timeout=10000)
        st = page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                           " return {id: d.id, no: d.voucherNo, status: d.status, voided: d.voidedAt} }")
        print("JV34 頁面實測：作廢並重開 ⇒", st, "（原單", vid, old_no, "）")
        assert st["status"] == "草稿" and not st["voided"], st
        import db
        conn = db.get_db()
        try:
            row = conn.execute("SELECT supersedes_no FROM vouchers_all WHERE id=?",
                               (st["id"],)).fetchone()
        finally:
            conn.close()
        assert row["supersedes_no"] == old_no, row["supersedes_no"]
    finally:
        browser.close()
