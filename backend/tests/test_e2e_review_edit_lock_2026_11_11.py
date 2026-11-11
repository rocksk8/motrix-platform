# -*- coding: utf-8 -*-
"""瀏覽器層級（真的 Chromium）：簽核人檢視待審核報價單——欄位鎖定（文字欄 readonly、其餘 disabled）＋常駐「編輯」鈕（2026-11-11 業主需求）。

業主回報的 bug：簽核人改了報價單內容「存不了」（欄位看起來能打字，但 PUT 在待審核本來就被擋）⇒ 主管只好按退回修改、申請人整張重走。
這支驗：
- 簽核人一進來：品項欄位 disabled（含鍵盤 Tab 進去也打不進去）、「儲存草稿」不見、常駐「編輯」鈕出現（**沒有旗標也出現**——舊版只有旗標單才有編輯入口）；
- 按「編輯」→ 欄位解鎖 → 改數量 → 「儲存複查編輯」（POST /review-edit 200、內容真的存進去）→ 同一個簽核人接著核准過關（不必退回修改）；
- 第 3 層（含）以後編輯：畫面提示「整條回第 1 層」、存檔後 `currentTier=0`、全部回待簽；第 1 層依序重簽到底才送出；
- 報價單頁核准前的彈窗（旗標單）只剩「維持核准」，沒有「編輯內容」（編輯入口只剩那顆常駐鈕）；「維持」＝不改直接核准的語意保留。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單頁與複查編輯端點")

NO = "MQ-RELK-001"


def _set_mode(code):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    from modules.case import content_fp as C
    c = db.get_db()
    try:
        SR.publish("quote_approval", {"reconfirm_mode": code}, reason="t", user="relk", conn=c)
        c.commit()
    finally:
        c.close()
    C._reset_mode_cache()


def _seed(approvers, *, signed=0, reconfirm_first=False, reassigned_first=False, cost=50.0):
    """每層一人；前 `signed` 層已簽（帶 signedFp／signedKeyHashes，符合目前內容）；`currentTier=signed`。"""
    import db
    from modules.case import content_fp as C
    data = {"quoteNo": NO, "customerName": "鎖定客戶", "projectName": "鎖定專案",
            "items": [{"id": "i1", "name": "A", "qty": 1, "cost": cost, "unitPrice": 100.0, "price": 100.0}],
            "tot": {"total": 105, "pretax": 100}}
    fp, hashes = C.content_fingerprint(data), C.key_hashes(data)
    tiers = []
    for i, u in enumerate(approvers):
        e = {"username": u, "displayName": u, "status": "pending"}
        if i < signed:
            e.update(status="approved", approvedAt="2026-11-11T09:00:00", signedFp=fp, signedKeyHashes=hashes)
        tiers.append({"approvers": [e]})
    first = tiers[signed]["approvers"][0]
    if reconfirm_first:
        first.update({"reconfirm": True, "signedFp": "1:old", "signedKeyHashes": {}, "signedReasonEntries": C.current_reasons_or_none(data)})
    if reassigned_first:
        first["reassignedFrom"] = "someone"
    data["approval"] = {"requestedBy": "sales_x", "requestedByDisplay": "業務X", "requestedAt": "2026-11-11T08:00:00",
                        "currentTier": signed, "contentFp": fp, "keyHashes": hashes, "tiers": tiers}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "簽核中" if signed else "待審核", "鎖定客戶", "鎖定專案", 105, 100, json.dumps(data, ensure_ascii=False),
                      "2026-11-11T08:00:00", "2026-11-11T08:00:00", "", "業務X", "[]"))
        conn.commit()
    finally:
        conn.close()
    return fp


def _state():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json, status FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    d = json.loads(r["data_json"])
    return d, d["approval"], r["status"]


def _wait(pred, page, tries=60, ms=200):
    for _ in range(tries):
        if pred():
            return True
        page.wait_for_timeout(ms)
    return pred()


def _open_form(page, live_server):
    page.goto(f"{live_server}/pages/quotation-form.html?id={NO}")
    page.wait_for_selector('[data-testid="qf-approve-open-preview"]', state="visible", timeout=15000)
    page.wait_for_selector('.qty-input', state="attached", timeout=10000)


QTY = ".qty-input"


def _is_locked(page):
    return page.evaluate("() => [...document.querySelectorAll('.form-left input,.form-left textarea,.form-left select')].filter(e => e.type !== 'hidden').every(e => e.disabled || e.readOnly)")


@pytest.mark.e2e
def test_approver_sees_locked_fields_and_a_permanent_edit_button_even_without_flags(live_server, make_user, e2e_browser):
    u, p = make_user(username="relk_ap", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])                                                               # 第一次審核、沒有任何旗標
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert _is_locked(page), "簽核人檢視：所有表單欄位都是 disabled／readonly"
    assert page.get_attribute('.form-left', 'data-approver-locked') == '1'
    assert page.is_visible('[data-testid="qf-review-edit-start"]'), "沒有旗標也要有常駐的編輯鈕（舊版這種情境沒有編輯入口）"
    assert not page.get_by_role("button", name="儲存草稿").is_visible(), "待審核單對簽核人不該有會失敗的「儲存草稿」"
    # 鍵盤也打不進去（舊版只有 pointer-events:none，Tab 進去照樣能打）
    before = page.input_value(QTY)
    page.evaluate("() => document.querySelector('.qty-input').focus()")
    page.keyboard.type("77")
    assert page.input_value(QTY) == before


@pytest.mark.e2e
def test_edit_unlocks_save_persists_and_the_same_approver_can_then_approve_without_returning_it(live_server, make_user, e2e_browser):
    """使用者原本回報的 bug 的反面：改了存得下去、接著核准過關，不必退回修改。"""
    u, p = make_user(username="relk_ap2", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    reviews, approves = [], []
    page.on("response", lambda rs: reviews.append(rs.status) if rs.request.method == "POST" and rs.url.endswith("/review-edit") else None)
    page.on("response", lambda rs: approves.append(rs.status) if rs.request.method == "POST" and rs.url.endswith("/approve") else None)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.click('[data-testid="qf-review-edit-start"]')
    page.wait_for_selector('[data-testid="review-edit-bar"]', timeout=5000)
    page.wait_for_function("() => !document.querySelector('.qty-input').readOnly", timeout=5000)
    assert page.get_attribute('.form-left', 'data-approver-locked') == '0'
    assert not page.is_visible('[data-testid="qf-review-edit-start"]')
    assert "回第 1 層" not in page.inner_text('[data-testid="review-edit-bar"]'), "第 1 層編輯：沒有整條重跑的提示"
    page.click(QTY)
    page.fill(QTY, "7")                                                       # 真的在欄位裡打字（不是改內部資料）
    page.click('[data-testid="review-edit-save"]')
    assert _wait(lambda: reviews == [200], page), reviews
    assert _wait(lambda: _state()[0]["items"][0]["qty"] == 7, page)
    d, appr, status = _state()
    assert appr["tiers"][0]["approvers"][0]["status"] == "pending", "首次待簽的編輯者不自動簽：仍要自己再按核准"
    assert any(e.get("type") == "review_edit" for e in d.get("editHistory", [])), "editHistory 有寫"
    # 存檔後回到鎖定狀態，接著核准（預覽後簽核）
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.click('[data-testid="qf-approve-open-preview"]')
    page.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-from-preview"]')
    assert _wait(lambda: _state()[2] == "已送出", page), (_state()[2], approves)
    assert _wait(lambda: approves[-1:] == [200], page), approves
    assert _state()[0]["items"][0]["qty"] == 7


@pytest.mark.e2e
def test_tier3_edit_warns_resets_chain_and_the_first_tier_reruns_it_to_the_end(live_server, make_user, e2e_browser):
    names = []
    creds = {}
    for i in range(3):
        n, pw = make_user(username="relk3_ap%d" % i, role="admin", modules=["quotation"])
        names.append(n); creds[n] = pw
    _set_mode(2)
    _seed(names, signed=2)                                                   # T1、T2 已簽，輪到 T3
    page = e2e_browser.new_page()
    inject_login(page, live_server, names[2], creds[names[2]])
    page.on("dialog", lambda dlg: dlg.accept())
    reviews = []
    page.on("response", lambda rs: reviews.append(rs) if rs.request.method == "POST" and rs.url.endswith("/review-edit") else None)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.click('[data-testid="qf-review-edit-start"]')
    page.wait_for_selector('[data-testid="review-edit-bar"]', timeout=5000)
    assert "整條簽核會回第 1 層重跑" in page.inner_text('[data-testid="review-edit-bar"]')
    page.fill(QTY, "9")
    page.click('[data-testid="review-edit-save"]')
    assert _wait(lambda: bool(reviews), page)
    assert reviews[-1].status == 200 and reviews[-1].json()["chainReset"] is True
    d, appr, status = _state()
    assert [t["approvers"][0]["status"] for t in appr["tiers"]] == ["pending"] * 3 and appr["currentTier"] == 0 and status == "待審核"
    assert d["items"][0]["qty"] == 9
    # T3 已不是當層待簽人：核准鈕消失
    page.wait_for_function("() => !document.querySelector('[data-testid=qf-approve-open-preview]')", timeout=8000)
    page.close()                                                             # 同一張單同時被兩個人開著會跳「同時檢視」提示窗、擋住點擊 ⇒ 換人前先關
    # 第 1 層重簽（被作廢的人帶「待複查」旗標 ⇒ 彈窗 ⇒ 維持核准），然後第 2、3 層依序簽完
    for i, n in enumerate(names):
        pg = e2e_browser.new_page()
        inject_login(pg, live_server, n, creds[n])
        pg.add_init_script("setInterval(() => { const m = document.getElementById('motrix-presence-modal'); if (m) m.remove() }, 50)")     # 前一位簽核人的「同時檢視」記錄還沒過期 ⇒ 提示窗會擋點擊；這題要驗的不是它
        pg.on("dialog", lambda dlg: dlg.accept())
        _open_form(pg, live_server)
        pg.click('[data-testid="qf-approve-open-preview"]')
        pg.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
        pg.click('[data-testid="qf-approve-from-preview"]')
        if i < 2:                                                            # T1、T2 曾簽過 ⇒ reconfirm 旗標 ⇒ 彈窗
            pg.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=8000)
            assert pg.locator('[data-testid="approve-choice-edit"]').count() == 0
            if pg.is_visible('[data-testid="approve-choice-note"]'):
                pg.fill('[data-testid="approve-choice-note"]', "已重新確認")
            pg.click('[data-testid="approve-choice-keep"]')
        assert _wait(lambda: _state()[1]["tiers"][i]["approvers"][0]["status"] == "approved", pg), (i, _state()[2])      # 以「這一層簽到了」為準（狀態在第 2 層簽之前就已經是簽核中，不能拿狀態等）
        pg.close()
    assert _state()[2] == "已送出" and _state()[1]["status"] == "approved"      # 同一個交易寫（最後一層簽到 ⇒ 狀態已送出）


@pytest.mark.e2e
def test_flagged_dialog_on_form_has_no_edit_option_and_keep_still_approves_unchanged(live_server, make_user, e2e_browser):
    """舊彈窗退場：旗標單核准前的彈窗只剩「維持核准」（＝不改直接核准）；沒有第二個編輯入口。維持＝帶 choice=keep、內容不變。"""
    u, p = make_user(username="relk_ap4", role="admin", modules=["quotation"])
    _set_mode(2)
    fp = _seed([u], reassigned_first=True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    posts = []
    page.on("request", lambda rq: posts.append(rq.post_data_json) if rq.method == "POST" and rq.url.endswith("/approve") else None)
    _open_form(page, live_server)
    assert page.is_visible('[data-testid="qf-review-edit-start"]')
    page.click('[data-testid="qf-approve-open-preview"]')
    page.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-from-preview"]')
    page.wait_for_selector('[data-testid="approve-choice-dialog"]', timeout=5000)
    assert page.locator('[data-testid="approve-choice-edit"]').count() == 0
    assert "編輯" in page.inner_text('[data-testid="approve-choice-noedit"]')
    page.click('[data-testid="approve-choice-keep"]')
    assert _wait(lambda: _state()[2] == "已送出", page)
    assert posts[-1]["choice"] == "keep" and posts[-1]["expectedFp"] == fp
    assert _state()[0]["items"][0]["qty"] == 1, "維持＝內容不變"


@pytest.mark.e2e
def test_superadmin_sees_no_edit_button(live_server, make_user, e2e_browser):
    """超管走既有的解鎖編輯（只對已送出），複查編輯端點也擋超管 ⇒ 不顯示常駐編輯鈕。"""
    u, p = make_user(username="relk_sa", role="superadmin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    assert not page.is_visible('[data-testid="qf-review-edit-start"]')


@pytest.mark.e2e
def test_mode_off_keeps_fields_locked_but_hides_the_edit_button(live_server, make_user, e2e_browser):
    """`reconfirm_mode`＝off（出廠預設）：複查編輯端點不開放（409）⇒ 不顯示常駐編輯鈕；欄位照樣鎖住（PUT 在待審核本來就存不了）。核准流程不受影響。"""
    u, p = make_user(username="relk_off", role="admin", modules=["quotation"])
    _set_mode(0)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.on("dialog", lambda dlg: dlg.accept())
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    assert not page.is_visible('[data-testid="qf-review-edit-start"]')
    page.click('[data-testid="qf-approve-open-preview"]')
    page.wait_for_selector('[data-testid="qf-approve-from-preview"]', state="visible", timeout=15000)
    page.click('[data-testid="qf-approve-from-preview"]')
    assert _wait(lambda: _state()[2] == "已送出", page)


@pytest.mark.e2e
def test_locked_form_keeps_cost_toggle_and_long_text_selectable(live_server, make_user, e2e_browser):
    """K 審（hichan-12）：舊的 .is-locked 會藏掉「顯示／隱藏成本欄」、並讓長欄位不能捲動／選取複製。簽核人要看成本與毛利 ⇒ 切換鈕要留著可按；
    文字區是 readonly（不是 disabled、不是 pointer-events:none）。"""
    u, p = make_user(username="relk_tg", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    tog = page.locator('.form-left .toggle-btn.keep-open')                      # 文字會隨狀態變（顯示／隱藏成本欄）⇒ 用固定選擇器
    assert tog.is_visible() and tog.is_enabled(), "成本欄切換鈕要留著"
    before = tog.inner_text()
    tog.click()
    assert tog.inner_text() != before, "點了有反應（純顯示切換，不改內容）"
    ta = page.evaluate("() => { const t = [...document.querySelectorAll('.form-left textarea')].find(e => e.offsetParent !== null); return t ? {ro: t.readOnly, dis: t.disabled, pe: getComputedStyle(t).pointerEvents} : null }")
    assert ta and ta["ro"] and not ta["dis"] and ta["pe"] != "none", ta


@pytest.mark.e2e
def test_locked_form_blocks_content_mutating_buttons_and_stays_clean(live_server, make_user, e2e_browser):
    """K 審再審（hichan-12）：.approver-locked 一度漏掉 `.form-section button` 的擋點擊規則——鎖住後按「新增區段標題」／pdfShow 顯示開關仍會改內容、
    isDirty 變 true（啟動 60 秒自動存檔 PUT、之後按編輯還會把這些本地改動吃進快照）。鎖住時：這些按鈕 disabled，硬點（含 JS click）也不改內容、不弄髒。"""
    u, p = make_user(username="relk_mb", role="admin", modules=["quotation"])
    _set_mode(2)
    _seed([u])
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    page.wait_for_function("() => document.querySelector('.qty-input').readOnly", timeout=5000)
    page.wait_for_function("() => [...document.querySelectorAll('.form-left .form-section button')].some(b => b.hasAttribute('data-approver-lock'))", timeout=5000)
    res = page.evaluate("""() => {
      const d = Alpine.$data(document.querySelector('[x-data]'));
      const rows0 = d.q.items.length, dirty0 = !!d.isDirty;
      const btns = [...document.querySelectorAll('.form-left .form-section button')].filter(b => !b.classList.contains('keep-open'));
      const live = btns.filter(b => !b.disabled && getComputedStyle(b).pointerEvents !== 'none').map(b => (b.textContent || '').trim().slice(0, 12));
      btns.forEach(b => b.click());                                  // 硬點全部（disabled 的按鈕 JS click 也不會觸發 @click）
      return {rows0, rows1: d.q.items.length, dirty0, dirty1: !!d.isDirty, live, n: btns.length};
    }""")
    assert res["n"] >= 2 and res["live"] == [], res
    assert res["rows1"] == res["rows0"] and res["dirty1"] is False, res
