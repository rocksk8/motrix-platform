# -*- coding: utf-8 -*-
"""第 32 包（745f3c2d）獨立探針（2e）：材料申請連結／尚未送審。隔離庫、只對測試庫動作。不是作者測試的複本：全部走 HTTP 端點與報表／GL 的公開函式。"""
import json

import pytest

import db
from modules.case import gl_events as GE
from modules.case import recognition as R
from modules.case.api import material_approvals as MAA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import BASE, NO, W, _body, _ln, _login, _mk, _status, _submit  # noqa: F401

MO = "/api/quotations/%s/material-orders" % NO


@pytest.fixture
def P(W, make_user):
    c, h_sa = W
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["dealTag"] = "已成案"                                    # 存檔會依 data_json.dealTag 重算 deal_tag；只改欄位會被重設（探針自己踩到的假綠燈）
    cn.execute("UPDATE quotations SET deal_tag='已成案', data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1,'甲','S-1','2026-10-02','2026-10-02')")
    cn.commit()
    cn.close()
    eng_u, eng_p = make_user(username="pk_eng", role="engineer", modules=["case_manage", "expense_forms"])
    out_u, out_p = make_user(username="pk_out", role="engineer", modules=["case_manage"])
    h_eng, h_out = _login(c, eng_u, eng_p), _login(c, out_u, out_p)
    cn = db.get_db()
    uid = cn.execute("SELECT id FROM users WHERE username='pk_eng'").fetchone()["id"]
    cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
    cn.commit()
    cn.close()
    return c, h_sa, h_eng, h_out


def _po(c, h, lines):
    r = _mk(c, h, "purchase_order", lines).json()
    assert _submit(c, h, r["id"]).status_code == 200
    return r


def _ord(item_id, qty=1, price=1000, **kw):
    d = {"itemId": item_id, "itemName": "品" + item_id, "quantity": qty, "unit": "台", "unitPrice": price, "totalPrice": qty * price,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "supplierId": 1}
    d.update(kw)
    return d


def _save(c, h, orders):
    return c.patch(MO, headers=h, json={"materialOrders": orders})


def _submit_mo(c, h, item_id):
    return c.post("%s/%s/submit" % (MO, item_id), headers=h, json={})


def _approvals():
    cn = db.get_db()
    try:
        return {r["item_id"]: r["status"] for r in cn.execute("SELECT item_id, status FROM case_material_approvals WHERE quote_no=?", (NO,)).fetchall()}
    finally:
        cn.close()


# ── (1) 材料申請連結 ─────────────────────────────────────────────────────────

def test_import_deduction_counts_live_unlinked_requests_only(P):
    c, sa, _, _ = P
    po = _po(c, sa, [_ln("a", 2, unitCost=1000)])                                              # 採購單 2
    assert _save(c, sa, [_ord("K", 4, quoteItemId="a"), _ord("D", 3, quoteItemId="a"),                     # K 4（要送審）、D 3（草稿）
                         _ord("L", 2, quoteItemId="a", poDocCode=po["docCode"], poLine=1)]).json().get("rejected") in ([], None)
    assert _submit_mo(c, sa, "K").status_code == 200 and _submit_mo(c, sa, "L").status_code == 200
    a = [i for i in c.get(BASE.replace("extra-expenses", "purchase-items"), headers=sa).json()["items"] if i["itemId"] == "a"][0]
    # 已訂＝採購單 2＋K 4（未連採購單、已核准）；D 草稿不佔；L 連到採購單不重複算
    assert (a["orderedQty"], a["remainingQty"]) == (6, 4), a


def test_po_line_taken_and_bad_link_through_the_real_submit_endpoint(P):
    c, sa, _, _ = P
    po = _po(c, sa, [_ln("a", 3, unitCost=1000)])
    draft_po = _mk(c, sa, "purchase_order", [_ln("a", 1)]).json()                              # 草稿採購單
    r = _save(c, sa, [_ord("X1", 3, quoteItemId="a", poDocCode=po["docCode"], poLine=1), _ord("X2", 3, quoteItemId="a", poDocCode=po["docCode"], poLine=1),
                      _ord("B1", 1, quoteItemId="a", poDocCode=draft_po["docCode"], poLine=1), _ord("B2", 1, quoteItemId="a", poDocCode="PO-NOPE")])
    rej = {x["itemId"]: x["code"] for x in (r.json().get("rejected") or [])}
    print("PROBE save rejected:", rej, "| saved approvals:", _approvals())
    assert _submit_mo(c, sa, "X1").status_code == 200
    r2 = _submit_mo(c, sa, "X2")
    assert r2.status_code == 400 and "已對應另一筆" in r2.text, r2.text
    for bad in ("B1", "B2"):
        if bad in _approvals():                                                                # 若存檔放行了壞連結，送審必擋
            rr = _submit_mo(c, sa, bad)
            assert rr.status_code == 400, (bad, rr.text)
        else:
            assert rej.get(bad) in ("bad_link",), (bad, rej)


def test_linked_request_cannot_open_a_remittance_and_paid_request_cannot_gain_a_link(P):
    c, sa, _, _ = P
    po = _po(c, sa, [_ln("a", 3, unitCost=1000)])
    assert _save(c, sa, [_ord("L", 3, quoteItemId="a", poDocCode=po["docCode"], poLine=1)]).status_code == 200
    assert _submit_mo(c, sa, "L").status_code == 200
    r = c.post("%s/L/payments" % MO, headers=sa, json={"payeeNoticeAcked": True})
    assert r.status_code == 409 and "不能另開匯款申請" in r.text, r.text
    # 已有付款紀錄的列：新增連結被擋；既有（沒連結）原樣存回
    paid = _ord("P", 2, quoteItemId="a", paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")
    cn = db.get_db()                                                                           # 舊單（舊「登記已付」）直接入庫
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["caseRecord"]["materialOrders"].append(paid)
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    cur = c.get(MO, headers=sa).json()["materialOrders"]
    assert _save(c, sa, cur).status_code == 200                                                # 原樣存回 OK
    withlink = [dict(o, poDocCode=po["docCode"], poLine=1) if o["itemId"] == "P" else o for o in cur]
    r2 = _save(c, sa, withlink)
    print("PROBE add link to paid order ->", r2.status_code)
    assert r2.status_code == 400 or any(x["itemId"] == "P" for x in (r2.json().get("rejected") or []))


def test_visibility_non_finance_sees_no_money_and_other_cases_are_404(P):
    c, sa, eng, out = P
    po = _po(c, sa, [_ln("a", 3, unitCost=1000)])
    _save(c, sa, [_ord("K", 1, quoteItemId="a")])
    pk = c.get(BASE.replace("extra-expenses", "purchase-items"), headers=eng)
    assert pk.status_code == 200 and "planUnitCost" not in pk.text and "actualAmount" not in pk.text and "3000" not in pk.text
    lines = c.get("/api/quotations/%s/material-po-lines" % NO, headers=eng)
    assert lines.status_code == 200 and lines.json()["lines"], lines.text
    assert "unitCost" not in lines.text and '"amount"' not in lines.text and "3000" not in lines.text, lines.text
    st = c.get("/api/quotations/%s/material-link-status" % NO, headers=eng)
    assert st.status_code == 200 and "3000" not in st.text
    for path in ("/api/quotations/%s/purchase-items", "/api/quotations/%s/material-po-lines", "/api/quotations/%s/material-link-status"):
        assert c.get(path % NO, headers=out).status_code == 404, path


# ── (2) 尚未送審：不進報表／GL／佇列／匯款資格、不佔額度 ──────────────────────────────

def test_draft_material_request_is_invisible_to_report_gl_queue_quota_and_remittance(P):
    c, sa, _, _ = P
    from datetime import date
    inv = date.today().isoformat()
    assert _save(c, sa, [_ord("D", 5, quoteItemId="a", price=1000, invoiceDate=inv), _ord("K", 1, quoteItemId="a", price=700, invoiceDate=inv)]).status_code == 200
    assert _submit_mo(c, sa, "K").status_code == 200                                           # 正對照：已核准的 K 看得到，D（草稿）看不到
    assert _approvals().get("D") == "草稿"
    cn = db.get_db()
    try:
        assert [(e["itemId"], e["amount"]) for e in R.material_entries(cn, "accrual") if e["quoteNo"] == NO] == [("K", 700.0)]
        assert [e for e in R.material_entries(cn, "cash") if e["quoteNo"] == NO] == []          # K 沒付款 ⇒ 現金口徑沒有；D 草稿同樣沒有
        assert [q for q in MAA.queue_items(cn)] == []                                               # K 已核准、D 草稿 ⇒ 佇列空
    finally:
        cn.close()
    ev = [e for e in GE.gl_events("2000-01-01", "2099-12-31")["events"] if e["event_code"] == "E12"]
    assert [e["source_key"] for e in ev] == ["%s::K" % NO]                                      # GL 只有 K，沒有 D
    a = [i for i in c.get(BASE.replace("extra-expenses", "purchase-items"), headers=sa).json()["items"] if i["itemId"] == "a"][0]
    assert a["orderedQty"] == 1 and a["remainingQty"] == 9                                      # 只有 K 的 1 佔額度；D 的 5 不佔
    r = c.post("%s/D/payments" % MO, headers=sa, json={"payeeNoticeAcked": True})
    print("PROBE draft remittance ->", r.status_code, (r.text or "")[:140])
    assert r.status_code >= 400, "草稿（尚未送審）不應能開匯款申請"


def test_observation_request_linked_to_a_voided_po_can_neither_pay_via_po_nor_open_a_remittance(P):
    """觀察探針：連結失效（採購單作廢）後，材料申請的匯款申請仍被『已對應採購單』擋住？（金額已回到材料申請，但付款出口被關）"""
    c, sa, _, _ = P
    po = _po(c, sa, [_ln("a", 3, unitCost=1000)])
    from datetime import date
    assert _save(c, sa, [_ord("L", 3, quoteItemId="a", poDocCode=po["docCode"], poLine=1, invoiceDate=date.today().isoformat())]).status_code == 200      # 權責口徑要有發票日才有認列日期
    assert _submit_mo(c, sa, "L").status_code == 200
    _status(po["id"], "已作廢")
    st = c.get("/api/quotations/%s/material-link-status" % NO, headers=sa).json()["statuses"]["L"]
    cn = db.get_db()
    try:
        money = [e["amount"] for e in R.material_entries(cn, "accrual") if e["quoteNo"] == NO]
    finally:
        cn.close()
    r = c.post("%s/L/payments" % MO, headers=sa, json={"payeeNoticeAcked": True})
    print("PROBE stale-link: state=%s stale=%s accrual_money=%s remittance_status=%s" % (st["state"], st["stale"], money, r.status_code))
    assert st["state"] == "none" and st["stale"] is True and money == [3000.0]            # 金額回到材料申請（錢不消失）
    assert r.status_code in (200, 409)                                                     # 記錄現況（409＝出口被關）
