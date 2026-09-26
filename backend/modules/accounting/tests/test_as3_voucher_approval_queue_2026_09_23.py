# -*- coding: utf-8 -*-
"""`AS3` · 傳票要跟其餘七種文件類型一樣，正確地出現在通用簽核佇列裡
（`STATE.md §253`，B 已實作 `1a970dc`）。

# 🔴 為什麼要補題

B 的實作沒有帶測試（協定：B 不寫測試，C 才寫）。`AS3` 動到兩支既有
端點（`submit_voucher()`／`approve_voucher()`），本檔直接補上。

# ⚙️ 觀測點

```
POST /api/vouchers/{id}/submit    approval_json 要嵌 requestedBy 等三欄
POST /api/vouchers/{id}/approve   回應要帶 allDone
GET  /api/approval-queue          傳票要以 type="voucher" 出現，
                                   requestedBy／requestedByDisplay 要對
```

# 🔑 判準：`requestedBy` 三欄跟「有沒有設定簽核流程」無關，兩種情況都要寫

`routers/vouchers.py` 的註解逐字：「不要用 `if tiers else '{}'`——沒有
設定流程時 `tiers` 是 `[]`，而 `requestedBy` 這三欄跟『有沒有設定流程』
無關，兩種情況都要寫」。本檔分開驗「沒有設定簽核流程」與「有設定」
兩種情況，避免只驗其中一種、讓另一種的假綠燈漏網。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

VOUCHERS = "/api/vouchers"
QUEUE = "/api/approval-queue"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr, summary="AS3測試傳票"):
    r = client.post(VOUCHERS, headers=hdr,
                    json={"summary": summary, "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _approval_json_of(vid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT approval_json FROM vouchers_all WHERE id = ?",
            (vid,)).fetchone()
        return json.loads(row["approval_json"] or "{}")
    finally:
        conn.close()


def _queue_item(client, hdr, vid):
    """`GET /api/approval-queue` 回的是**按送審人分組**的結構：
    `{"queue": [{"requestedBy":…, "items":[{"type":…, "voucherId":…}, …]}]}`
    ——真正的項目在每一組的 `items` 裡，不是 `queue` 本身那一層。"""
    r = client.get(QUEUE, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    groups = r.json().get("queue", [])
    for group in groups:
        for it in group.get("items") or []:
            if it.get("type") == "voucher" and int(it.get("voucherId") or 0) == int(vid):
                return it
    return None


# ══════════════════════════════════════════════════════════════════════
# ① submit：requestedBy 三欄要寫，不論有沒有設定簽核流程
# ══════════════════════════════════════════════════════════════════════

def test_as3_submit_without_a_configured_flow_still_writes_requested_by(
        client, make_user):
    """🔴🔴 **核心：沒有設定簽核流程時（`tiers=[]`），`requestedBy`／
    `requestedByDisplay`／`requestedAt` 仍然要寫進 `approval_json`。**

    ☠️ 這是規格點名的假綠燈來源：`if tiers else "{}"` 這種寫法會讓沒設定
    流程的傳票整包 `approval_json` 是 `"{}"`，三欄全部消失。
    """
    u, hdr = _hdr(client, make_user, "as3_nochain")
    vid = _create(client, hdr)

    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]

    appr = _approval_json_of(vid)
    assert appr.get("requestedBy") == u, (
        "`requestedBy` 是 %r，應該是 %r。" % (appr.get("requestedBy"), u))
    assert appr.get("requestedByDisplay"), (
        "`requestedByDisplay` 是空的：%r" % appr)
    assert appr.get("requestedAt"), "`requestedAt` 是空的：%r" % appr


def test_as3_submit_with_a_configured_flow_also_writes_requested_by(
        client, make_user):
    """⚙️ **正對照：有設定簽核流程（`tiers` 非空）時，三欄一樣要寫。**

    只驗「沒設定」那一種證明不了「兩種情況都要寫」——一個只在 `tiers`
    非空時才寫的實作會讓這題單獨驗才抓得到。
    """
    u, hdr = _hdr(client, make_user, "as3_chain_owner")
    approver_u, _p = make_user(username="as3_chain_approver",
                               role="superadmin", modules=["cashier"])
    r = client.put("/api/settings/approval-flow/voucher", headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [{"userId": _user_id(approver_u),
                                  "username": approver_u,
                                  "displayName": approver_u}]}]})
    assert r.status_code == 200, "存簽核設定失敗：%s %s" % (r.status_code,
                                                        r.text[:200])

    vid = _create(client, hdr)
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]

    appr = _approval_json_of(vid)
    assert appr.get("tiers"), "設定了一層鏈，`tiers` 卻是空的：%r" % appr
    assert appr.get("requestedBy") == u, (
        "有設定流程時 `requestedBy` 是 %r，應該是 %r——\n" % (appr.get("requestedBy"), u)
        + "☠️ 若只有沒設定流程時才寫這三欄，這裡就會是空的。")


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?",
                          (username,)).fetchone()
        assert row is not None, "找不到使用者 %r" % username
        return int(row["id"])
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ② approve：allDone 要對
# ══════════════════════════════════════════════════════════════════════

def test_as3_approve_reports_all_done_false_until_the_final_tier(
        client, make_user):
    """🔴🔴 **兩層流程（內建覆核＋主管），簽第一層後 `allDone` 要是
    `false`——還沒真的簽完。**"""
    u, hdr = _hdr(client, make_user, "as3_partial")
    vid = _create(client, hdr)
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]

    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("status") == "簽核中", "第一層簽完應該是「簽核中」：%r" % body
    assert body.get("allDone") is False, (
        "簽第一層之後 `allDone` 是 %r，應該是 `False`——\n" % body.get("allDone")
        + "☠️ 若讀到 `undefined`（前端會當假值），畫面反而會顯示「已完成」。")


def test_as3_approve_reports_all_done_true_on_the_final_tier(
        client, make_user):
    """🔴🔴 **簽完最後一層，`allDone` 要是 `true`。**"""
    u, hdr = _hdr(client, make_user, "as3_final")
    vid = _create(client, hdr)
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]

    r = client.post("%s/%s/approve" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("status") == "已核准", "簽完兩層應該是「已核准」：%r" % body
    assert body.get("allDone") is True, (
        "簽完最後一層之後 `allDone` 是 %r，應該是 `True`。" % body.get("allDone"))


# ══════════════════════════════════════════════════════════════════════
# ③ 通用簽核佇列：傳票要以 type="voucher" 正確出現
# ══════════════════════════════════════════════════════════════════════

def test_as3_the_voucher_appears_in_the_shared_approval_queue(
        client, make_user):
    """🔴🔴 **送審後的傳票要出現在 `GET /api/approval-queue`，
    `type=="voucher"`，`requestedBy`／`requestedByDisplay` 對得起來。**"""
    u, hdr = _hdr(client, make_user, "as3_queue")
    vid = _create(client, hdr, summary="AS3佇列測試")
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]

    item = _queue_item(client, hdr, vid)
    assert item is not None, (
        "送審後的傳票沒有出現在 `GET /api/approval-queue` 裡"
        "（type=voucher, id=%s）。" % vid)
    assert item.get("requestedBy") == u, (
        "佇列項目裡的 `requestedBy` 是 %r，應該是 %r：%r" % (item.get("requestedBy"), u, item))


def test_as3_a_draft_voucher_does_not_appear_in_the_queue(client, make_user):
    """⚙️ **負對照：還是草稿的傳票不該出現在簽核佇列裡。**

    ☠️ 少了這題，「佇列回全部傳票不篩狀態」的實作也會讓上一題綠。
    """
    _u, hdr = _hdr(client, make_user, "as3_draft")
    vid = _create(client, hdr, summary="AS3草稿不進佇列")

    item = _queue_item(client, hdr, vid)
    assert item is None, (
        "還沒送審的傳票（草稿）出現在簽核佇列裡：%r" % item)
