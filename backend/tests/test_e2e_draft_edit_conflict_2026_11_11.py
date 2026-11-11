# -*- coding: utf-8 -*-
"""瀏覽器層級（真的 Chromium）：兩個人同時編輯同一張「草稿」報價單——樂觀鎖衝突（2026-11-11，多人同時編輯保護）。

後端 `PUT /api/quotations/{no}` 早就對草稿做 `_expectedUpdatedAt` 比對（不符回 409）；這支補的是**使用者看得到**：
- 手動「儲存草稿」撞 409：有 alert、頂端出現持續橫幅、資料庫仍是對方的內容（沒被蓋）。
- 「載入最新版」鈕：載入對方的內容、橫幅消失，接著再改再存就成功（兩人的修改都在）。
- 自動存檔（60 秒計時，這裡直接呼叫 autoSave()）撞 409：以前是**無聲失敗**；現在出橫幅、且暫停自動存檔（不再重打必敗的 PUT）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單頁")

NO = "MQ-DRFT-001"
D = "Alpine.$data(document.querySelector('[x-data]'))"
NOPRESENCE = "setInterval(() => { const m = document.getElementById('motrix-presence-modal'); if (m) m.remove() }, 50)"


def _seed_draft():
    import db
    data = {"quoteNo": NO, "customerName": "原客戶", "projectName": "原專案",
            "items": [{"id": "i1", "name": "A", "qty": 1, "cost": 50.0, "unitPrice": 100.0, "price": 100.0}],
            "tot": {"total": 105, "pretax": 100}}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                  "created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, "草稿", "原客戶", "原專案", 105, 100, json.dumps(data, ensure_ascii=False),
                   "2026-11-11T08:00:00", "2026-11-11T08:00:00", "", "業務X", "[]"))
        c.commit()
    finally:
        c.close()


def _row():
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        c.close()
    d = json.loads(r["data_json"])
    return d, r["updated_at"]


def _open(e2e_browser, live_server, user, pw, dialogs):
    page = e2e_browser.new_page()
    page.add_init_script(NOPRESENCE)
    inject_login(page, live_server, user, pw)
    page.on("dialog", lambda dlg: (dialogs.append(dlg.message), dlg.accept()))
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('input[x-model="q.projectName"]', state="visible", timeout=15000)
    page.wait_for_function(f"() => {D}._lastUpdatedAt", timeout=10000)
    return page


def _type(page, selector, text):
    page.fill(selector, text)
    page.press(selector, "Tab")           # @change → setDirty


def _save_draft(page):
    page.get_by_role("button", name="儲存草稿").click()


PROJECT = 'input[x-model="q.projectName"]'
CUSTOMER = 'input[x-model="q.customerName"]'


@pytest.mark.e2e
def test_second_editor_gets_a_visible_conflict_on_save_and_can_reload_then_save(live_server, make_user, e2e_browser):
    a, pa = make_user(username="drft_a", role="admin", modules=["quotation"])
    b, pb = make_user(username="drft_b", role="admin", modules=["quotation"])
    _seed_draft()
    da, db_ = [], []
    page_a = _open(e2e_browser, live_server, a, pa, da)
    page_b = _open(e2e_browser, live_server, b, pb, db_)

    # B 先存
    _type(page_b, PROJECT, "B改的專案")
    _save_draft(page_b)
    page_b.wait_for_function(f"() => !{D}.isDirty", timeout=10000)
    assert _row()[0]["projectName"] == "B改的專案"
    assert not page_b.is_visible('[data-testid="qf-save-conflict"]')

    # A 手上是舊版（載入時間在 B 存檔之前）→ 存檔必須被擋、且看得見
    _type(page_a, CUSTOMER, "A改的客戶")
    assert not page_a.is_visible('[data-testid="qf-save-conflict"]'), "撞到之前不該有橫幅"
    puts = []
    page_a.on("response", lambda rs: puts.append(rs.status) if rs.request.method == "PUT" else None)
    _save_draft(page_a)
    page_a.wait_for_selector('[data-testid="qf-save-conflict"]', state="visible", timeout=10000)
    assert puts == [409], puts
    assert any("已被其他人更新" in m for m in da), da                         # 手動存檔的 alert 還在
    d, _ = _row()
    assert d["projectName"] == "B改的專案" and d["customerName"] == "原客戶", "A 的存檔不能蓋掉 B，也不能存進一半"
    banner = page_a.inner_text('[data-testid="qf-save-conflict"]')
    assert "有人在你之後也改過" in banner and "載入最新版" in banner, banner

    # 載入最新版：看到 B 的內容、橫幅消失；再改再存成功，兩人的修改都在
    page_a.click('[data-testid="qf-save-conflict-reload"]')
    page_a.wait_for_function(f"() => !{D}.saveConflictBanner && {D}.q.projectName === 'B改的專案'", timeout=10000)
    assert not page_a.is_visible('[data-testid="qf-save-conflict"]')
    assert page_a.input_value(PROJECT) == "B改的專案"
    _type(page_a, CUSTOMER, "A改的客戶")
    _save_draft(page_a)
    page_a.wait_for_function(f"() => !{D}.isDirty", timeout=10000)
    d, _ = _row()
    assert d["projectName"] == "B改的專案" and d["customerName"] == "A改的客戶", d
    assert not page_a.is_visible('[data-testid="qf-save-conflict"]')


@pytest.mark.e2e
def test_autosave_conflict_is_no_longer_silent_and_pauses_autosave(live_server, make_user, e2e_browser):
    """以前：60 秒自動存檔撞 409 → apiSave 回 false、什麼都沒顯示，使用者一直以為有存。"""
    a, pa = make_user(username="drft_a2", role="admin", modules=["quotation"])
    b, pb = make_user(username="drft_b2", role="admin", modules=["quotation"])
    _seed_draft()
    da, db_ = [], []
    page_a = _open(e2e_browser, live_server, a, pa, da)
    page_b = _open(e2e_browser, live_server, b, pb, db_)
    _type(page_b, PROJECT, "B先改")
    _save_draft(page_b)
    page_b.wait_for_function(f"() => !{D}.isDirty", timeout=10000)

    _type(page_a, CUSTOMER, "A的修改")
    puts = []
    page_a.on("response", lambda rs: puts.append(rs.status) if rs.request.method == "PUT" else None)
    page_a.evaluate(f"() => {D}.autoSave()")
    page_a.wait_for_selector('[data-testid="qf-save-conflict"]', state="visible", timeout=10000)
    assert puts == [409], puts
    assert da == [], "自動存檔不該彈 alert 打斷打字（橫幅就是它的提示）：%s" % da
    assert _row()[0]["projectName"] == "B先改" and _row()[0]["customerName"] == "原客戶"

    # 已知衝突 ⇒ 自動存檔暫停：再呼叫 / 再打字都不重打 PUT
    page_a.evaluate(f"() => {D}.autoSave()")
    _type(page_a, CUSTOMER, "A又改")
    page_a.evaluate(f"() => {D}.autoSave()")
    page_a.wait_for_timeout(500)
    assert puts == [409], "衝突後不該再打 PUT：%s" % puts
