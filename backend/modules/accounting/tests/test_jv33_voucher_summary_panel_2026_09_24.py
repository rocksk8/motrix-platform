# -*- coding: utf-8 -*-
"""`JV33` · 點摘要就同時看到「本傳票已上傳檔案」與「支出項」，不用切頁籤。

使用者逐字：「我點傳票的摘要他也能自動帶入已上傳檔案跟支出項，不用每次來回點閱」。
權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md` `JV33` ＋ A 2026-09-24 裁示：

```
① 既有「摘要來源」頁籤區保留；另加「帶入面板」，摘要格 focus 時出現，兩區同時列出
   支出項要先選案件（vouchers.py 既有限制）⇒ 沒選時照既有那句提示
② 面板點一項：摘要空白 ⇒ 填入；非空 ⇒ 以「；」接在後面（只限面板，頁籤區維持覆蓋）
③ 本傳票附件：文字 ⇒ 把檔名接進摘要；縮圖 ⇒ 走 JV28 頁內預覽，不動摘要
④ 「連金額一起帶入」這一輪不做（金額，待確認 N12）
```
📌 更正留著（2026-09-24，`JV36`）：② 的「；接續」依使用者更正改為「選 XXX ⇒ 覆蓋＋連帶 XXX 的已上傳檔案」，
   ④ 併進 JV36（限空白行帶入借方）；兩區同時可見與載入中狀態保留。題見 `test_jv36_*`。
📌 更正留著（2026-09-25，使用者以示意圖確認版型 A）：右側「帶入面板」改成分錄下方的「帶入來源」區塊
   （左案件、右該案已上傳檔案），**常駐**不必 focus；「本傳票已上傳檔案」那一區移到下方附件區
   （每個附件有縮圖、點開同一個預覽窗）。規則不變的部分沿用這裡的題，只換選擇器；新版型的題見
   `test_e2e_voucher_source_block_below_2026_09_25`。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login as _login  # noqa: E402,F401
from modules.accounting.tests.test_jv28_voucher_attachment_preview_2026_09_24 import (  # noqa: E402
    _png_bytes, _upload, _open_page)

QUOTE = "MQ-JV33-001"
PANEL = '[data-testid="src-block"]'
FILES = '.vc-att'   # 2026-09-25：本傳票已上傳檔案 ⇒ 下方附件區
EXPENSES = '[data-testid="summary-panel-expenses"]'
SUMMARY = "textarea[x-model='l.summary']"


def _seed_case():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (QUOTE, "已結案", "JV33客戶", "JV33案", 1000, 952, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _setup(page, live_server, make_user, seed_extra_expense, uname):
    _seed_case()
    seed_extra_expense(QUOTE, total_cost=5000, category="運費", description="吊車運費",
                       expense_date="2026-09-10", doc_no="AB12345678")
    u, p = make_user(username=uname, role="superadmin", modules=["cashier"])
    token = _login(page, live_server, u, p)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    r = page.request.post(f"{live_server}/api/vouchers",
                          headers={"Authorization": "Bearer " + token},
                          data={"summary": "JV33", "lines": [
                              {"account_code": "6111", "debit": 5000, "credit": 0},
                              {"account_code": "1113", "debit": 0, "credit": 5000}]})
    assert r.ok, r.text()
    vid = r.json()["id"]
    _upload(page, live_server, token, vid, "吊車發票.png", "image/png", _png_bytes())
    r = page.request.get(f"{live_server}/api/vouchers/summary-sources?quote_no={QUOTE}",
                         headers={"Authorization": "Bearer " + token})
    exp = [it["summary"] for it in r.json()["tabs"]["支出項"]]
    assert exp, "量尺：案件底下沒有支出項——下面量不到東西：%r" % r.json()
    _open_page(page, live_server, vid)
    # 🔑 選案件走使用者真的會走的那一步：點第 1 行摘要，再點帶入來源區塊的案件（它會覆蓋第 1 行摘要，
    #    所以下面的題都在**第 2 行**上量）。📌 2026-09-25：頁籤區拿掉，改走帶入來源區塊。
    page.locator(SUMMARY).nth(0).click()
    page.click(f'[data-testid="src-case"]:has-text("{QUOTE}")')
    page.wait_for_function(
        "q => Alpine.$data(document.querySelector('[x-data]')).sourceQuote === q", arg=QUOTE,
        timeout=10000)
    return exp[0]


def _wait_expenses(page, exp):
    """等支出項清單**載入完成**（那一筆出現），不用固定秒數。
    📌 更正留著（2026-09-24，hichan-8d 讀碼＋壓力比對）：原本只等 `sourceQuote === q`——
       那是點案件時**同步**設的，`loadSources()` 的 fetch 還沒回來就成立了 ⇒ 負載高時
       支出項區還是空的，`is_visible` 讀到 False（基準 b41f748 壓力下 2/2 紅）。"""
    page.locator('[data-testid="summary-panel-expense"]:has-text("%s")' % exp[:6]).wait_for(
        state="visible", timeout=15000)


def _line2(page):
    return page.locator(SUMMARY).nth(1)


def _summary2(page):
    return page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).lines[1].summary")


@pytest.mark.e2e
def test_jv33_focusing_a_summary_shows_files_and_expenses_together(
        live_server, make_user, seed_extra_expense, e2e_browser):
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    exp = _setup(page, live_server, make_user, seed_extra_expense, "jv33_a")
    _line2(page).click()
    page.wait_for_selector(PANEL, state="visible", timeout=5000)
    _wait_expenses(page, exp)
    files_vis = page.is_visible(FILES + ' :text("吊車發票.png")')
    exp_vis = page.is_visible(EXPENSES + ' :text("%s")' % exp[:6])
    print("JV33 頁面實測：focus 第 2 行摘要 ⇒ 附件區可見", files_vis, "／支出項區可見", exp_vis)
    assert files_vis and exp_vis, "兩區沒有同時出現（附件 %s／支出項 %s）" % (files_vis, exp_vis)


@pytest.mark.e2e
def test_jv33_clicking_a_source_overwrites_the_summary_instead_of_appending(
        live_server, make_user, seed_extra_expense, e2e_browser):
    """📌 **翻面**（2026-09-24，`JV36`）——原本這一題是「空白填入、非空以『；』接在後面」。

    使用者逐字更正：「我說的摘要要能帶動已上傳檔案，是別的意思，不是『帶入到第 1 行摘要，
    點一項：摘要空白就填入，已有文字就用「；」接在後面』，指的是案件已上傳檔案、支出項的
    已上傳檔案內容，例如我的摘要是 XXX，我點選 XXX 的時候它下方能自動連帶 XXX 內有的上傳檔案」
    ⇒ 點支出項／案件：該行摘要**覆蓋**成那一筆的名稱；點本傳票附件的檔名：只預覽，不動摘要。
    """
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    exp = _setup(page, live_server, make_user, seed_extra_expense, "jv33_b")
    _line2(page).click()
    page.wait_for_selector(PANEL, state="visible", timeout=5000)
    _wait_expenses(page, exp)
    page.click('[data-testid="summary-panel-expense"]:has-text("%s")' % exp[:6])
    first = _summary2(page)
    page.click('[data-testid="voucher-att-open"]:has-text("吊車發票.png")')
    page.wait_for_selector('[data-testid="voucher-att-preview"]', state="visible", timeout=10000)
    page.click('[data-testid="voucher-att-close"]')
    after_file = _summary2(page)
    page.click('[data-testid="src-case"]:has-text("%s")' % QUOTE)
    second = _summary2(page)
    print("JV33 頁面實測：點支出項 ⇒", repr(first), "；點附件檔名 ⇒", repr(after_file),
          "；再點案件 ⇒", repr(second))
    assert first == exp, "點支出項，摘要應該是它的名稱：%r" % first
    assert after_file == exp, "點本傳票附件的檔名只預覽，不應該動摘要：%r" % after_file
    assert "；" not in second and exp not in second and QUOTE in second, (
        "再點案件應該**覆蓋**成案件名稱，不是接續：%r" % second)


@pytest.mark.e2e
def test_jv33_the_thumbnail_previews_without_touching_the_summary(
        live_server, make_user, seed_extra_expense, e2e_browser):
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _setup(page, live_server, make_user, seed_extra_expense, "jv33_c")
    _line2(page).click()
    page.wait_for_selector(PANEL, state="visible", timeout=5000)
    thumb = page.locator('[data-testid="voucher-att-thumb"]').first
    thumb.wait_for(state="visible", timeout=10000)
    thumb.click()
    page.wait_for_selector('[data-testid="voucher-att-preview"]', state="visible",
                           timeout=10000)
    assert _summary2(page) == "", "點縮圖不應該動摘要：%r" % _summary2(page)


@pytest.mark.e2e
def test_jv33_the_expense_section_says_loading_while_sources_are_in_flight(
        live_server, make_user, seed_extra_expense, e2e_browser):
    """支出項還在載入時，面板要說「載入中…」，不是一片空白或「沒有支出項」（慢網路時的樣子）。
    ⚙️ 用 `page.route` **扣住**帶案件的 summary-sources 請求，量完「載入中」才放行——
       不用 `time.sleep`：sync Playwright 的 route handler 裡睡覺會卡住整條事件迴圈，
       延遲不會真的發生在瀏覽器那一側。"""
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    held = []
    page.route("**/api/vouchers/summary-sources?quote_no=*", lambda route: held.append(route))
    exp = _setup(page, live_server, make_user, seed_extra_expense, "jv33_d")
    _line2(page).click()
    page.wait_for_selector(PANEL, state="visible", timeout=5000)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "量尺：帶案件的 summary-sources 請求沒有被扣住——量不到載入期間"
    # PERF #5：放行寫在 finally——量「載入期間」那一步若出錯，被扣住的請求也要放掉
    #   （共用伺服器在題末會排空處理中的請求；卡著不放會讓紅燈原因變成排空逾時）
    try:
        during = page.locator(EXPENSES).inner_text()
    finally:
        for r in held:
            r.continue_()
    _wait_expenses(page, exp)
    after = page.locator(EXPENSES).inner_text()
    print("JV33 頁面實測：載入中 ⇒", repr(during[:40]), "；載入後 ⇒", repr(after[:40]))
    assert "載入中" in during, "支出項載入期間沒有說「載入中」：%r" % during
    assert "載入中" not in after, "載入完了還寫著載入中：%r" % after
