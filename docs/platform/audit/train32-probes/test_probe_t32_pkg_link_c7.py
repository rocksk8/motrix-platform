# -*- coding: utf-8 -*-
"""第 32 包稽核（c7）獨立探針：材料申請 ↔ 採購單連結（S4a～e）、尚未送審（草稿）、簽核佇列 tags。
只補作者測試（test_material_link_*／test_material_reports_gate_*）沒打的縫；斷言是「應該怎樣」，印出實測值。不隨產品出貨。"""
import json
import threading

import pytest

import db
from modules.case import purchase_items as PI
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_purchase_item_lines_2026_10_02 import (  # noqa: F401
    NO, W, _ln, _login, _mk, _set_tiers, _status, _submit)


def _mo(item, **kw):
    o = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "invoiceDate": "2031-03-10", "notes": ""}
    o.update(kw)
    return o


def _orders():
    cn = db.get_db()
    try:
        return (json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord") or {}).get("materialOrders") or []
    finally:
        cn.close()


def _ap(item):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item)).fetchone()
        return r["status"] if r else None
    finally:
        cn.close()


def _closed():
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET deal_tag='已成案' WHERE quote_no=?", (NO,))
        cn.commit()
    finally:
        cn.close()


def _patch(c, h, orders):
    return c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": orders})


def _po(c, h, qty=3, status=None):
    r = _mk(c, h, "purchase_order", [_ln("a", qty), _ln("a", 1)]).json()
    assert _submit(c, h, r["id"]).status_code == 200
    if status:
        _status(r["id"], status)
    return r


# ── A1 並發：兩筆草稿連到同一採購單列，同時送審 ⇒ 恰一個成功 ───────────────────────────────

def test_a1_concurrent_submits_on_the_same_po_line_only_one_wins(W):
    c, h = W
    po = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("m2", quoteItemId="a", poDocCode=po["docCode"], poLine=1)],
                   {"m1": "草稿", "m2": "草稿"})
    out = []

    def go(item):
        out.append(c.post("/api/quotations/%s/material-orders/%s/submit" % (NO, item), headers=h).status_code)
    ts = [threading.Thread(target=go, args=(i,)) for i in ("m1", "m2")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    live = [i for i in ("m1", "m2") if _ap(i) in ("待審核", "簽核中", "已核准")]
    print("A1 statuses=%s live=%s" % (sorted(out), live))
    assert sorted(out) == [200, 400] and len(live) == 1


def test_a1b_after_the_first_is_withdrawn_the_line_is_free_again(W):
    c, h = W
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_sa", "displayName": "x"}]}])
    po = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("m2", quoteItemId="a", poDocCode=po["docCode"], poLine=1)],
                   {"m1": "草稿", "m2": "草稿"})
    assert c.post("/api/quotations/%s/material-orders/m1/submit" % NO, headers=h).status_code == 200
    assert c.post("/api/quotations/%s/material-orders/m2/submit" % NO, headers=h).status_code == 400
    assert c.post("/api/quotations/%s/material-orders/m1/withdraw" % NO, headers=h).status_code == 200
    r = c.post("/api/quotations/%s/material-orders/m2/submit" % NO, headers=h)
    print("A1b after withdraw:", r.status_code, r.text[:120])
    assert r.status_code == 200


# ── A2 bad_link 面：儲存路徑（專屬端點與 case-record 後門）──────────────────────────────────

@pytest.mark.parametrize("kw", [
    {"poDocCode": "PO-NOPE"}, {"poLine": 1}, {"poDocCode": "@PO", "poLine": 0}, {"poDocCode": "@PO", "poLine": -1},
    {"poDocCode": "@PO", "poLine": 99}, {"poDocCode": "@PO", "poLine": "x"}, {"poDocCode": "@PO", "poLine": 1.5}, {"poDocCode": "@PO", "poLine": 1e30},
    {"quoteItemId": "zzz"}, {"poDocCode": " "}, ])
def test_a2_new_row_with_a_bad_link_is_rejected_by_the_dedicated_endpoint(W, kw):
    c, h = W
    po = _po(c, h)
    kw = {k: (po["docCode"] if v == "@PO" else v) for k, v in kw.items()}
    r = _patch(c, h, [_mo("n1", **kw)])
    saved = _orders()
    print("A2 %r -> %s rejected=%s saved=%s ap=%s" % (kw, r.status_code, r.json().get("rejected") if r.status_code == 200 else r.text[:80], [o["itemId"] for o in saved], _ap("n1")))
    if kw == {"poDocCode": " "} or kw.get("poLine") == 0:
        return        # 空白＝沒填連結；poLine=0 被 `_dump_order` 當「沒填」丟掉（⇒ 連整張採購單）：觀察項，行為見輸出，不在此斷言
    assert r.status_code in (200, 400, 422)
    assert [o for o in saved if o["itemId"] == "n1" and (o.get("poDocCode") or o.get("poLine") not in (None, "")) and o.get("poLine") != 1] == [] or r.status_code != 200 or r.json().get("rejected")


@pytest.mark.parametrize("status", ["草稿", "已駁回", "已作廢"])
def test_a2b_po_in_a_dead_state_cannot_be_linked(W, status):
    c, h = W
    po = _mk(c, h, "purchase_order", [_ln("a", 3)]).json()
    if status != "草稿":
        assert _submit(c, h, po["id"]).status_code == 200
        _status(po["id"], status)
    r = _patch(c, h, [_mo("n1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)])
    print("A2b %s -> %s %s | saved=%s" % (status, r.status_code, r.json().get("rejected"), [o["itemId"] for o in _orders()]))
    assert r.status_code == 200 and [x["code"] for x in r.json()["rejected"]] == ["bad_link"] and _orders() == [] and _ap("n1") is None


def test_a2c_a_po_of_another_case_cannot_be_linked(W):
    c, h = W
    other = _mk(c, h, "purchase_order", [_ln("a", 3)], no="MQ-PL-2").json()
    assert _submit(c, h, other["id"], no="MQ-PL-2").status_code == 200
    r = _patch(c, h, [_mo("n1", quoteItemId="a", poDocCode=other["docCode"], poLine=1)])
    print("A2c ->", r.status_code, r.json().get("rejected"))
    assert [x["code"] for x in r.json()["rejected"]] == ["bad_link"] and _orders() == []


def test_a2d_purchase_req_cannot_be_linked_as_a_po(W):
    c, h = W
    req = _mk(c, h, "purchase_req", [_ln("a", 3)]).json()
    _submit(c, h, req["id"])
    r = _patch(c, h, [_mo("n1", quoteItemId="a", poDocCode=req["docCode"], poLine=1)])
    print("A2d ->", r.status_code, r.json().get("rejected"))
    assert [x["code"] for x in r.json()["rejected"]] == ["bad_link"]


def test_a2e_case_record_whole_body_cannot_write_material_links(W):
    """整包存檔（case-record，body.caseRecord）夾帶 materialOrders（偽造連結）⇒ 偽造內容不可落地、不可建審核列。
    （觀察：整包存檔會把 data_json 的 materialOrders 整個丟掉——在 prod/a5dea50c 同樣，非本包引入；前端走分段存。）"""
    c, h = W
    po = _po(c, h)
    assert _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)]).status_code == 200
    forged = [_mo("m1", quoteItemId="a", poDocCode="PO-FORGED", poLine=7, totalPrice=1), _mo("m2", quoteItemId="zzz", poDocCode="PO-X")]
    r = c.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"caseRecord": {"materialOrders": forged}})
    cn = db.get_db()
    raw = cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]
    cn.close()
    print("A2e whole-body ->", r.status_code, "| forged persisted:", "PO-FORGED" in raw or "PO-X" in raw, "| orders:", [o["itemId"] for o in _orders()], "| m2 ap:", _ap("m2"))
    assert "PO-FORGED" not in raw and "PO-X" not in raw and _ap("m2") is None


def test_a2g_case_record_segments_path_cannot_write_material_links(W):
    """分段存（segments.materialOrders）夾帶偽造連結／狀態 ⇒ 不可落地。"""
    c, h = W
    po = _po(c, h)
    assert _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)]).status_code == 200
    before = json.dumps(_orders(), sort_keys=True)
    forged = [_mo("m1", quoteItemId="a", poDocCode="PO-FORGED", poLine=7, totalPrice=1), _mo("m2", quoteItemId="zzz", poDocCode="PO-X")]
    r = c.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"segments": {"materialOrders": forged}, "base": {}})
    cn = db.get_db()
    raw = cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]
    cn.close()
    print("A2g segments ->", r.status_code, r.text[:140], "| forged persisted:", "PO-FORGED" in raw or "PO-X" in raw, "| unchanged:", before == json.dumps(_orders(), sort_keys=True), "| m2 ap:", _ap("m2"))
    assert "PO-FORGED" not in raw and "PO-X" not in raw and _ap("m2") is None


def test_a2f_po_line_is_stored_as_an_int(W):
    c, h = W
    po = _po(c, h)
    for pl in (1, "1", 2.0):
        _patch(c, h, [_mo("m%s" % pl, quoteItemId="a", poDocCode=po["docCode"], poLine=pl)])
    print("A2f stored:", [(o["itemId"], o.get("poLine"), type(o.get("poLine")).__name__) for o in _orders()])
    assert all(isinstance(o.get("poLine"), int) and not isinstance(o.get("poLine"), bool) for o in _orders() if o.get("poLine") is not None)


# ── A4 連結失效回金額（權責／現金／總帳）──────────────────────────────────────────────────

def _entries(basis):
    from modules.case import recognition as REC
    cn = db.get_db()
    try:
        return REC.material_entries(cn, basis)
    finally:
        cn.close()


def test_a4_linked_order_is_not_counted_and_comes_back_with_nopo_when_the_po_dies(W):
    c, h = W
    _closed()
    po = _po(c, h)
    _put_materials([_mo("L1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("U1", quoteItemId="a", totalPrice=500, unitPrice=250)],
                   {"L1": "已核准", "U1": "已核准"})
    acc = {e["itemId"]: e for e in _entries("accrual")}
    print("A4 linked:", {k: (v["amount"], v.get("noPo")) for k, v in acc.items()})
    assert sorted(acc) == ["U1"] and acc["U1"]["noPo"] is True
    _status(po["id"], "已作廢")
    acc = {e["itemId"]: e for e in _entries("accrual")}
    print("A4 after void:", {k: (v["amount"], v.get("noPo")) for k, v in acc.items()})
    assert sorted(acc) == ["L1", "U1"] and acc["L1"]["noPo"] is True and acc["L1"]["amount"] == 2000


def test_a4b_linked_order_not_in_cash_basis_or_ledger_while_the_po_is_alive(W):
    c, h = W
    from modules.case import gl_events as GE
    _closed()
    po = _po(c, h)
    _put_materials([_mo("L1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("U1", totalPrice=500, unitPrice=250, paidStatus="paid", paidAmount=500, paidDate="2031-04-01")], {"L1": "已核准", "U1": "已核准"})
    cash = [e["itemId"] for e in _entries("cash")]
    gl = GE.gl_events("2031-01-01", "2031-12-31")
    codes = [(e["event_code"], e["source_key"]) for e in gl["events"]]
    print("A4b cash=%s gl=%s all=%s notice=%s" % (cash, codes, [(e["event_code"], e["source_key"]) for e in gl["events"]], gl.get("notice")))
    assert cash == ["U1"] and not [k for _, k in codes if k.endswith("::L1")] and [k for _, k in codes if k.endswith("::U1")], "控制組 U1 要在；連結的 L1 不在"


# ── B 尚未送審（草稿）：簽核佇列、紅點 ────────────────────────────────────────────────────

def _ap_user(make_user, client):
    u, p = make_user(username="pl_ap", role="admin")
    return _login(client, u, p)


def test_b1_draft_is_not_in_the_queue_or_the_dot_and_tags_are_correct(W, make_user):
    c, h = W
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_ap", "displayName": "核"}]}])
    hap = _ap_user(make_user, c)
    po = _po(c, h)
    _put_materials([_mo("S1", quoteItemId="a"), _mo("D1"), _mo("Z0", totalPrice=0, unitPrice=0), _mo("P1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)],
                   {"S1": "草稿", "D1": "草稿", "Z0": "草稿", "P1": "草稿"})
    for i in ("S1", "Z0", "P1"):
        assert c.post("/api/quotations/%s/material-orders/%s/submit" % (NO, i), headers=h).status_code == 200, i
    r = c.get("/api/approval-queue", headers=hap)
    its = [it for g in r.json()["queue"] for it in g["items"] if it["type"] == "material_order"]
    cnt = c.get("/api/approval-queue/count", headers=hap).json().get("count")
    print("B1 queue:", [(i.get("docCode"), i.get("tags")) for i in its], "count=", cnt)
    titles = {i["docCode"]: i for i in its}
    assert len(its) == 3 and cnt >= 3
    assert all(isinstance(i["tags"], list) for i in its)
    warn = [i for i in its if i["tags"]]
    assert len(warn) == 1 and warn[0]["tags"][0]["tone"] == "warn" and warn[0]["tags"][0]["text"] == "該材料申請未申請採購單"
    blob = json.dumps(its, ensure_ascii=False)
    assert "D1" not in [i.get("itemId") for i in its]
    assert all(set(t) == {"text", "tone"} for i in its for t in i["tags"])


def test_b1b_draft_surfaces(W, make_user):
    """草稿：不進權責／現金報表、不能開匯款申請（409）、不入總帳。"""
    c, h = W
    from modules.case import gl_events as GE
    _put_materials([_mo("D1")], {"D1": "草稿"})
    assert _entries("accrual") == []
    gl = GE.gl_events("2031-01-01", "2031-12-31")
    assert [e for e in gl["events"] if e["event_code"] == "E12"] == []
    r = c.post("/api/quotations/%s/material-orders/D1/payments" % NO, headers=h, json={"amount": 100, "supplierId": 1, "payeeNoticeAcked": True,
               "bankCode": "004", "bankName": "x", "bankAccountName": "y", "bankAccountNumber": "123456"})
    print("B1b draft payment ->", r.status_code, r.text[:160])
    assert r.status_code in (400, 403, 409)


# ── F tags 的資料外洩面與容錯 ─────────────────────────────────────────────────────────────

def test_f2_tag_text_never_contains_amounts_or_names(W):
    cn = db.get_db()
    try:
        order = _mo("S1", quoteItemId="a", totalPrice=987654, itemName="機密品名甲")
        tags = PI.queue_tags(cn, NO, order)
    finally:
        cn.close()
    print("F2 tags:", tags)
    assert tags == [{"text": "該材料申請未申請採購單", "tone": "warn"}]
    assert "987654" not in json.dumps(tags, ensure_ascii=False) and "機密" not in json.dumps(tags, ensure_ascii=False)


def test_f4_queue_survives_a_broken_provider_tags_value(W, make_user, monkeypatch):
    """提供者丟壞 tags（None／字串／含 None）：後端佇列 API 是否仍回 200（前端另以靜態讀碼）。"""
    c, h = W
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_ap", "displayName": "核"}]}])
    hap = _ap_user(make_user, c)
    _put_materials([_mo("S1", quoteItemId="a")], {"S1": "草稿"})
    assert c.post("/api/quotations/%s/material-orders/S1/submit" % NO, headers=h).status_code == 200
    for bad in (None, "字串", [None], [{"text": "<img src=x onerror=alert(1)>", "tone": "evil"}]):
        monkeypatch.setattr(PI, "queue_tags", lambda *a, _b=bad, **k: _b)
        r = c.get("/api/approval-queue", headers=hap)
        got = [it.get("tags") for g in r.json()["queue"] for it in g["items"] if it["type"] == "material_order"] if r.status_code == 200 else r.text[:80]
        print("F4 bad=%r -> %s %s" % (bad, r.status_code, got))
        assert r.status_code == 200


# ── A6 權限／遮蔽 ─────────────────────────────────────────────────────────────────────────

def test_a6_endpoints_hide_amounts_without_finance_view_and_404_for_outsiders(W, make_user):
    c, h = W
    po = _po(c, h)
    u_eng, p_eng = make_user(username="pl_eng", role="engineer")
    u_out, p_out = make_user(username="pl_out", role="engineer")
    cn = db.get_db()
    uid = cn.execute("SELECT id FROM users WHERE username='pl_eng'").fetchone()["id"]
    cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
    cn.commit()
    cn.close()
    h_eng, h_out = _login(c, u_eng, p_eng), _login(c, u_out, p_out)
    full = c.get("/api/quotations/%s/material-po-lines" % NO, headers=h).json()["lines"]
    eng = c.get("/api/quotations/%s/material-po-lines" % NO, headers=h_eng)
    out = c.get("/api/quotations/%s/material-po-lines" % NO, headers=h_out)
    st_out = c.get("/api/quotations/%s/material-link-status" % NO, headers=h_out)
    print("A6 sa-lines-keys=%s eng=%s %s out=%s link-status out=%s" % (sorted(full[0]) if full else None, eng.status_code, [sorted(x) for x in eng.json().get("lines", [])][:1], out.status_code, st_out.status_code))
    assert full and "unitCost" in full[0] and "amount" in full[0]
    assert eng.status_code == 200 and all("unitCost" not in x and "amount" not in x for x in eng.json()["lines"])
    assert out.status_code in (403, 404) and st_out.status_code in (403, 404)
    assert c.get("/api/quotations/%s/material-po-lines" % NO).status_code in (401, 403)


# ── A5 剩餘量三處同一份數字（picker／送審上限／purchase-items）──────────────────────────────

def test_a5_remaining_quantity_hand_computed_and_consistent(W):
    """報價品項 a 計畫 10：採購單已核准 3；材料申請 已核准 2、待審核 1、草稿 5、已退回 7、已取消 9（不計）、舊單（無審核列）4 ⇒ 已訂 3+2+1+4=10。"""
    c, h = W
    _po(c, h, qty=2)                                                                       # 該採購單兩列 a：2＋1 ＝ 3
    orders = [_mo("A", quoteItemId="a", quantity=2), _mo("P", quoteItemId="a", quantity=1), _mo("D", quoteItemId="a", quantity=5),
              _mo("R", quoteItemId="a", quantity=7), _mo("C", quoteItemId="a", quantity=9), _mo("L", quoteItemId="a", quantity=4)]
    _put_materials(orders, {"A": "已核准", "P": "待審核", "D": "草稿", "R": "已退回", "C": "已取消"})
    cn = db.get_db()
    try:
        data, rows = PI._case_state(cn, NO)
        po_rows = [r for r in rows if (r["kind"] or "") == PI.ORD]
        extra = PI.material_ordered(PI.load_material_orders(cn, NO, data), po_rows)
        used = PI.usage(rows, extra_ordered=extra).get("a", {}).get("orderedQty")
        res = PI.material_submit_check(cn, NO, _mo("NEW", quoteItemId="a", quantity=1), exclude_item_id="NEW")
    finally:
        cn.close()
    pi = c.get("/api/quotations/%s/purchase-items" % NO, headers=h)
    print("A5 extra=%s used=%s submit-over=%s purchase-items=%s" % (extra, used, res["snapshot"]["overPlanQty"], pi.status_code))
    assert extra.get("a") == 7.0 and used == 10.0, "材料申請貢獻應為 2＋1＋4＝7（已核准／待審核／舊單），採購單 3 ⇒ 已訂 10"
    assert res["snapshot"]["overPlanQty"] == 1 and [p["code"] for p in res["problems"]] == ["over_plan_reason_required"]
    if pi.status_code == 200:
        a = [x for x in (pi.json().get("items") or pi.json().get("purchaseItems") or []) if x.get("itemId") == "a"]
        print("A5 purchase-items a:", a)
        if a:
            assert a[0].get("orderedQty") == 10.0 or a[0].get("ordered") == 10.0
