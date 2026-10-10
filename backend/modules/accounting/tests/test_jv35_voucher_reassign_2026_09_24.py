# -*- coding: utf-8 -*-
"""`JV35` · 傳票加入轉簽（使用者逐字：「我有轉簽的功能能加入」）。

權威原文：`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` 檔尾 `JV35`。

```
POST /api/approval-queue/reassign  type="voucher"、id=傳票號碼
規則沿用既有轉簽：限 superadmin、原因必填、只換當層第一個還沒簽的人、被轉到的人收到通知
傳票的簽核存在 vouchers_all.approval_json（不是 data_json）⇒ 走傳票自己的解析
```

# 🔴 為什麼現在要做

`JV30` 之後，有設定流程的傳票只有當層簽核人（或代理人）按得動；
當層的人不在又沒設代理人 ⇒ **這張傳票卡住**，而使用者說「目前人數不夠」。

# ⚙️ 與 `JV30` 的銜接（三種情況都要驗）

```
轉簽之前，新的人按核准  ⇒ 403
轉簽之後，新的人按核准  ⇒ 200
轉簽之後，原簽核人按核准 ⇒ 403
```
"""
from tests._requires import requires_module  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest

VOUCHERS = "/api/vouchers"
REASSIGN = "/api/approval-queue/reassign"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _login(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return int(conn.execute("SELECT id FROM users WHERE username=?",
                                (username,)).fetchone()["id"])
    finally:
        conn.close()


def _pending_voucher(client, hdr, approver, submitter=None):
    """一張卡在 `approver` 身上的傳票（一層，手動挑人）。回 `(id, voucher_no)`。
    第 54 班：轉簽的操作者不得是送審人 ⇒ 需要驗轉簽成功的題，用 `submitter`（另一位）建單與送審；`hdr` 只設流程。"""
    r = client.put("/api/settings/approval-flow/voucher", headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [{"userId": _user_id(approver), "username": approver,
                                  "displayName": approver}]}]})
    assert r.status_code == 200, r.text[:200]
    sub = submitter or hdr
    r = client.post(VOUCHERS, headers=sub, json={"summary": "JV35", "lines": _LINES})
    assert r.status_code == 200, r.text[:200]
    vid, no = r.json()["id"], r.json()["voucher_no"]
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=sub)
    assert r.status_code == 200, r.text[:200]
    return vid, no


def _appr(vid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT status, approval_json FROM vouchers_all WHERE id=?",
                           (vid,)).fetchone()
        return row["status"], json.loads(row["approval_json"] or "{}")
    finally:
        conn.close()


def _reassign(client, hdr, no, to, reason="原簽核人請假，改由他人簽"):
    return client.post(REASSIGN, headers=hdr,
                       json={"type": "voucher", "id": no, "to_username": to, "reason": reason})


def test_jv35_reassign_hands_the_tier_to_the_new_person_and_takes_it_from_the_old(
        client, make_user):
    su, sh = _login(client, make_user, "jv35a_su")
    old, oh = _login(client, make_user, "jv35a_old")
    new, nh = _login(client, make_user, "jv35a_new")
    _sub, subh = _login(client, make_user, "jv35a_sub")
    vid, no = _pending_voucher(client, sh, old, submitter=subh)

    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=nh)
    assert r.status_code == 403, "轉簽之前，新的人就按得動：%s %s" % (r.status_code, r.text[:200])

    r = _reassign(client, sh, no, new)
    assert r.status_code == 200, "傳票不能轉簽：%s %s" % (r.status_code, r.text[:200])
    a = (_appr(vid)[1].get("tiers") or [{}])[0].get("approvers")[0]
    assert a["username"] == new and a["reassignedFrom"] == old, a
    assert "請假" in a["reassignReason"], a
    assert _appr(vid)[1].get("reassignLog"), "approval_json 沒有記 reassignLog"

    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=oh)
    assert r.status_code == 403, "轉簽之後，原簽核人還按得動：%s %s" % (r.status_code, r.text[:200])
    assert _appr(vid)[0] == "待審核"

    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=nh)
    assert r.status_code == 200, "轉簽之後，新的人按不動：%s %s" % (r.status_code, r.text[:200])
    assert _appr(vid)[0] == "已核准"


def test_jv35_reassign_records_history_and_notifies_the_new_approver(client, make_user):
    import db
    su, sh = _login(client, make_user, "jv35b_su")
    old, _oh = _login(client, make_user, "jv35b_old")
    new, _nh = _login(client, make_user, "jv35b_new")
    _sub, subh = _login(client, make_user, "jv35b_sub")
    vid, no = _pending_voucher(client, sh, old, submitter=subh)
    assert _reassign(client, sh, no, new).status_code == 200

    conn = db.get_db()
    try:
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE action='approval.reassign' AND target_id=?",
            (no,)).fetchall()
        notes = conn.execute("SELECT * FROM notifications WHERE username=?", (new,)).fetchall()
    finally:
        conn.close()
    assert audit, "簽核歷史（audit_log approval.reassign）沒有這一筆"
    assert notes, "被轉到的人沒有收到通知"


def test_jv35_reassign_keeps_the_existing_rules_superadmin_only_and_reason_required(
        client, make_user):
    su, sh = _login(client, make_user, "jv35c_su")
    ad, ah = _login(client, make_user, "jv35c_admin", role="admin")
    old, _oh = _login(client, make_user, "jv35c_old")
    new, _nh = _login(client, make_user, "jv35c_new")
    vid, no = _pending_voucher(client, sh, old)

    r = _reassign(client, ah, no, new)
    assert r.status_code == 403, "非 superadmin 轉簽了傳票：%s" % r.text[:200]
    r = _reassign(client, sh, no, new, reason="  ")
    assert r.status_code == 400, "沒填原因就轉出去了：%s" % r.text[:200]
    assert (_appr(vid)[1].get("tiers") or [{}])[0]["approvers"][0]["username"] == old


def test_jv35_a_voucher_without_a_configured_flow_cannot_be_reassigned(client, make_user):
    """內建兩層（沒有簽核人名單）：沒有人可以被換掉 ⇒ 400，而不是 500 或假裝成功。"""
    import db
    su, sh = _login(client, make_user, "jv35d_su")
    new, _nh = _login(client, make_user, "jv35d_new")
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM system_settings WHERE key IN"
                     " ('voucher_approval_flow', 'unified_approval_flow')")
        conn.commit()
    finally:
        conn.close()
    r = client.post(VOUCHERS, headers=sh, json={"summary": "JV35", "lines": _LINES})
    vid, no = r.json()["id"], r.json()["voucher_no"]
    assert client.post("%s/%s/submit" % (VOUCHERS, vid), headers=sh).status_code == 200
    r = _reassign(client, sh, no, new)
    assert r.status_code == 400, "%s %s" % (r.status_code, r.text[:200])
    # ⚠️ 訊息要是「沒有分層簽核資料」，不是「此類型不支援轉簽」——
    #    後者在 HEAD 上也是 400，只驗狀態碼的話這題在沒實作時就是綠的。
    assert "分層簽核" in r.json().get("detail", ""), r.json()


def test_jv35_an_unreadable_voucher_chain_refuses_reassign_with_its_own_reason(client, make_user):
    """簽核資料讀不出來 ⇒ 400「格式不正確」（fail-closed，稽核 D AP-S1）。

    ⚠️ 要驗訊息：若把讀不出來吞成空鏈（D 的突變 AP3），一樣是 400，只是變成「沒有分層簽核資料」——
    那句話把「資料壞了」說成「沒有設定流程」，只驗狀態碼會照綠。"""
    import db
    su, sh = _login(client, make_user, "jv35u_su")
    new, _nh = _login(client, make_user, "jv35u_new")
    old, _oh = _login(client, make_user, "jv35u_old")
    vid, no = _pending_voucher(client, sh, old)
    conn = db.get_db()
    try:
        conn.execute("UPDATE vouchers_all SET approval_json=? WHERE id=?", ("{壞掉的簽核資料", vid))
        conn.commit()
    finally:
        conn.close()
    r = _reassign(client, sh, no, new)
    assert r.status_code == 400, "%s %s" % (r.status_code, r.text[:200])
    assert "格式不正確" in r.json().get("detail", ""), r.json()
    conn = db.get_db()
    try:
        raw = conn.execute("SELECT approval_json FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        conn.close()
    assert raw == "{壞掉的簽核資料", "擋下來的轉簽不可以改寫簽核資料"


# ══════════════════════════════════════════════════════════════════════
# 畫面：簽核佇列的傳票那一列要有轉簽鈕，按下去資料庫真的換人
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_e2e_approval_reassign_ui_2026_09_14 import _login as _page_login  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


@pytest.mark.e2e
def test_jv35_the_queue_shows_a_reassign_button_on_a_voucher(live_server, client, make_user, e2e_browser):
    su, sp = make_user(username="jv35e_su", role="superadmin", modules=["cashier"])
    make_user(username="jv35e_old", role="superadmin", modules=["cashier"])
    make_user(username="jv35e_new", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": su, "password": sp})
    sh = {"Authorization": "Bearer " + r.json()["token"]}
    su2, sp2 = make_user(username="jv35e_sub", role="superadmin", modules=["cashier"])
    r2 = client.post("/api/auth/login", json={"username": su2, "password": sp2})
    vid, no = _pending_voucher(client, sh, "jv35e_old", submitter={"Authorization": "Bearer " + r2.json()["token"]})

    browser = e2e_browser
    page = browser.new_page()
    _page_login(page, live_server, su, sp)
    page.goto(f"{live_server}/pages/approval-queue.html")
    # ⚠️ 不用 `text={no}`：同一個單號也出現在動態牆（「建立傳票草稿：…」），
    #    第一個命中的是隱藏的那一個 ⇒ 逾時，紅在探針上不是產品上。
    card = page.locator(f".aq-card:visible:has-text('{no}'),"
                        f" .aq-qrow:visible:has-text('{no}')").first
    card.wait_for(state="visible", timeout=15000)
    card.click()
    page.wait_for_function(
        "() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
        " return d.selected && d.selected.type === 'voucher' }", timeout=10000)
    btn = page.locator("#aq-reassign-btn")
    try:   # PERF #6：原本固定等 300ms ⇒ 等轉簽鈕出現（沒出現交給下面有說明的斷言）
        btn.wait_for(state="visible", timeout=5000)
    except Exception:
        pass
    assert btn.is_visible(), "簽核佇列選到傳票，而轉簽鈕沒有出現"
    page.click("#aq-reassign-btn")
    page.wait_for_function(
        "() => document.querySelector('#aq-reassign-to')"
        " && document.querySelector('#aq-reassign-to').options.length > 1",
        timeout=10000)
    page.select_option("#aq-reassign-to", "jv35e_new")
    page.fill("#aq-reassign-reason", "原簽核人出差，傳票改由他人簽")
    page.click("#aq-reassign-confirm")
    for _ in range(50):
        a = (_appr(vid)[1].get("tiers") or [{}])[0].get("approvers")[0]
        if a["username"] == "jv35e_new":
            break
        page.wait_for_timeout(200)
    print("JV35 頁面實測：轉簽後當層簽核人 =", a["username"], "／轉簽自", a.get("reassignedFrom"))
    assert a["username"] == "jv35e_new" and a["reassignedFrom"] == "jv35e_old", a


def test_jv35_old_voucher_without_embedded_requester_still_knows_the_submitter(client, make_user):
    """第 54 班（1d 稽核）：AS3 之前送審的傳票 approval_json 沒嵌 requestedBy ⇒ 送審人要從 `submitted_by` 取，否則轉簽規則對舊單形同虛設。"""
    import db
    su, sh = _login(client, make_user, "jv35g_su")
    old, _oh = _login(client, make_user, "jv35g_old")
    new, _nh = _login(client, make_user, "jv35g_new")
    vid, no = _pending_voucher(client, sh, old)                                       # 送審人＝su（同一個人想轉簽自己送審的傳票）
    conn = db.get_db()
    try:
        a = json.loads(conn.execute("SELECT approval_json FROM vouchers_all WHERE id=?", (vid,)).fetchone()["approval_json"])
        a.pop("requestedBy", None)
        conn.execute("UPDATE vouchers_all SET approval_json=? WHERE id=?", (json.dumps(a, ensure_ascii=False), vid))
        conn.commit()
    finally:
        conn.close()
    r = _reassign(client, sh, no, new)
    assert r.status_code == 403 and "送審人" in r.text                                # submitted_by 後備生效
    conn = db.get_db()
    try:
        conn.execute("UPDATE vouchers_all SET submitted_by='' WHERE id=?", (vid,))
        conn.commit()
    finally:
        conn.close()
    r = _reassign(client, sh, no, new)
    assert r.status_code == 409 and "送審人" in r.text                                # 仍讀不到 ⇒ fail-closed
