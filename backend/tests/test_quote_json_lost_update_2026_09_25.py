"""「讀 data_json → 改 → 整包 save_quotation_json 寫回」不可以蓋掉空窗內別人寫進去的修改（lost update，2026-09-25 稽核）。

`save_quotation_json` 整包寫回、不比對 updated_at；sqlite3 不為 SELECT 開交易 ⇒ 交易外讀到的是快照，
讀與寫之間別人 commit 的修改會被蓋回（bf ade34b95 修掉的是階段同步那一處；這裡是其餘 22 處）。
探針：在被測端點「讀完、寫回前」（monkeypatch 各模組裡的 save_quotation_json）另開一條連線，
照正確寫法拿寫鎖、讀 data_json、加一個 `_probe` 標記寫回。
  修正前 ⇒ 探針在空窗裡 commit，接著被端點整包蓋掉 ⇒ `_probe` 不見（紅）
  修正後 ⇒ 探針卡在寫鎖上，端點 commit 之後才寫進去 ⇒ `_probe` 在、端點自己的修改也在（綠）
⚠️ 單跑幾乎碰不到（空窗只有幾毫秒）⇒ 這裡在空窗裡**確定地**插入一次寫入。
"""
import io
import json
import threading

import pytest

import routers.material_orders as mo
import routers.quotations as q
import routers.vendor_contractors as vc
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _login, _seed


def _probe_write(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()[0])
        d["_probe"] = "寫在空窗裡"
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), quote_no))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def gap_probe(monkeypatch):
    """被測端點每一次呼叫 save_quotation_json 之前（讀完、寫回前）插入一次探針寫入。"""
    state = {"fired": 0, "threads": [], "quote": NO}
    for mod in (q, mo, vc):
        original = mod.save_quotation_json

        def _wrapped(conn, quote_no, data, *a, _orig=original, **kw):
            if state.get("armed") and state["fired"] == 0:
                state["fired"] += 1
                state["quote"] = quote_no
                t = threading.Thread(target=_probe_write, args=(quote_no,))
                t.start()
                t.join(2)          # 修正後探針會等到端點的寫鎖釋放 ⇒ 不可以無限等
                state["threads"].append(t)
            return _orig(conn, quote_no, data, *a, **kw)
        monkeypatch.setattr(mod, "save_quotation_json", _wrapped)
    return state


def _data(no=NO):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        conn.close()


def _files(name="a.pdf"):
    return [("files", (name, io.BytesIO(b"%PDF-1.4 probe"), "application/pdf"))]


def _upload(client, h, path):
    r = client.post(path, headers=h, files=_files())
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


# 每一案：(準備, 觸發, 檢查端點自己的修改有落地)
def _c_pay_upload(client, h):
    return None, lambda: client.post(f"/api/quotations/{NO}/payment/1/invoice-files", headers=h, files=_files()), \
        lambda d: len(d["caseRecord"]["payment"]["items"][1].get("invoiceFiles") or []) == 1


def _c_pay_delete(client, h):
    fid = _upload(client, h, f"/api/quotations/{NO}/payment/1/invoice-files")
    return None, lambda: client.delete(f"/api/quotations/{NO}/payment/1/invoice-files/{fid}", headers=h), \
        lambda d: not (d["caseRecord"]["payment"]["items"][1].get("invoiceFiles") or [])


def _c_mat_upload(client, h):
    return None, lambda: client.post(f"/api/quotations/{NO}/materials/0/files", headers=h, files=_files()), \
        lambda d: len(d["caseRecord"]["materials"][0].get("files") or []) == 1


def _c_mat_delete(client, h):
    fid = _upload(client, h, f"/api/quotations/{NO}/materials/0/files")
    return None, lambda: client.delete(f"/api/quotations/{NO}/materials/0/files/{fid}", headers=h), \
        lambda d: not (d["caseRecord"]["materials"][0].get("files") or [])


def _c_mat_inv_upload(client, h):
    return None, lambda: client.post(f"/api/quotations/{NO}/materials/0/invoice-files", headers=h, files=_files()), \
        lambda d: len(d["caseRecord"]["materials"][0].get("invoiceFiles") or []) == 1


def _c_mat_inv_delete(client, h):
    fid = _upload(client, h, f"/api/quotations/{NO}/materials/0/invoice-files")
    return None, lambda: client.delete(f"/api/quotations/{NO}/materials/0/invoice-files/{fid}", headers=h), \
        lambda d: not (d["caseRecord"]["materials"][0].get("invoiceFiles") or [])


def _wo(d):
    """沖銷的欄位是款項上平鋪的 writeOff*（writeOffStatus／Reason／RequestedBy…）。"""
    it = d["caseRecord"]["payment"]["items"][1]
    return {k: v for k, v in it.items() if k.startswith("writeOff")}


def _c_wo_request(client, h):
    return None, lambda: client.post(f"/api/quotations/{NO}/payment/1/request-writeoff", headers=h, json={"reason": "壞帳"}), \
        lambda d: bool(_wo(d))


def _c_wo_cancel(client, h):
    r = client.post(f"/api/quotations/{NO}/payment/1/request-writeoff", headers=h, json={"reason": "壞帳"})
    assert r.status_code == 200, r.text
    before = json.dumps(_wo(_data()), sort_keys=True)
    return None, lambda: client.post(f"/api/quotations/{NO}/payment/1/cancel-writeoff", headers=h), \
        lambda d: json.dumps(_wo(d), sort_keys=True) != before


def _c_wo_approve(client, h):
    r = client.post(f"/api/quotations/{NO}/payment/1/request-writeoff", headers=h, json={"reason": "壞帳"})
    assert r.status_code == 200, r.text
    before = json.dumps(_wo(_data()), sort_keys=True)
    return "approver", lambda h2: client.post(f"/api/quotations/{NO}/payment/1/approve-writeoff", headers=h2,
                                               json={"approve": True}), \
        lambda d: json.dumps(_wo(d), sort_keys=True) != before


def _c_settlement(client, h):
    return None, lambda: client.put(f"/api/quotations/{NO}/settlement", headers=h,
                                    json={"settlement": {"status": "未精算", "note": "探針"}}), \
        lambda d: (d.get("settlement") or {}).get("note") == "探針"


def _c_deal_tag(client, h):
    return None, lambda: client.patch(f"/api/quotations/{NO}/deal-tag", headers=h,
                                      json={"deal_tag": "已成案", "log_entry": {"text": "探針"}}), \
        lambda d: d.get("dealTag") == "已成案"


def _saved_orders(client, h):
    """先存一筆合法的叫料（routers/material_orders.py::MaterialOrder 的欄位）。"""
    mos = [{"itemId": "mo-probe", "itemName": "線材", "quantity": 10, "unit": "條", "unitPrice": 100,
            "totalPrice": 1000, "paidStatus": "pending", "paidAmount": 0, "paidDate": None}]
    r = client.patch(f"/api/quotations/{NO}/material-orders", headers=h, json={"materialOrders": mos})
    assert r.status_code == 200, r.text
    return mos


def _c_mat_orders(client, h):
    mos = _saved_orders(client, h)
    mos[0].update(paidAmount=500, paidStatus="partial", paidDate="2026-09-20")
    return None, lambda: client.patch(f"/api/quotations/{NO}/material-orders", headers=h, json={"materialOrders": mos}),         lambda d: d["caseRecord"]["materialOrders"][0].get("paidAmount") == 500


def _c_mat_order_invoice_date(client, h):
    mos = _saved_orders(client, h)
    iid = mos[0]["itemId"]
    return None, lambda: client.patch(f"/api/quotations/{NO}/material-orders/{iid}/invoice-date", headers=h,
                                      json={"invoiceDate": "2026-09-20"}),         lambda d: d["caseRecord"]["materialOrders"][0].get("invoiceDate") == "2026-09-20"


def _c_dispatch_import(client, h):
    from tests.test_dispatch_import_to_quote_persists_2026_09_23 import _insert_draft_quote_and_dispatch
    did = _insert_draft_quote_and_dispatch("MQ-LU-DISP")
    return None, lambda: client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers=h),         lambda d: "配線施工" in [it.get("description") for it in d.get("items") or []]


CASES = {
    "dispatch_import": _c_dispatch_import,
    "payment_invoice_upload": _c_pay_upload, "payment_invoice_delete": _c_pay_delete,
    "material_file_upload": _c_mat_upload, "material_file_delete": _c_mat_delete,
    "material_invoice_upload": _c_mat_inv_upload, "material_invoice_delete": _c_mat_inv_delete,
    "writeoff_request": _c_wo_request, "writeoff_cancel": _c_wo_cancel, "writeoff_approve": _c_wo_approve,
    "settlement": _c_settlement, "deal_tag": _c_deal_tag,
    "material_orders": _c_mat_orders, "material_order_invoice_date": _c_mat_order_invoice_date,
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_write_in_the_gap_is_not_overwritten(client, make_user, gap_probe, case):
    u, pw = make_user(username="lu_" + case[:14], role="superadmin")
    _seed(assigned=[])
    h = _login(client, u, pw)
    who, trigger, landed = CASES[case](client, h)
    if who == "approver":                         # 沖銷由另一位最高管理者核准
        u2, pw2 = make_user(username="lu_appr", role="superadmin")
        h2 = _login(client, u2, pw2)
        call = lambda: trigger(h2)                # noqa: E731
    else:
        call = trigger
    gap_probe["armed"] = True
    r = call()
    assert r.status_code in (200, 201), r.text
    assert gap_probe["fired"] == 1, "探針沒有插進空窗（被測路徑變了）"
    for t in gap_probe["threads"]:
        t.join(40)
    d = _data(gap_probe["quote"])
    assert d.get("_probe") == "寫在空窗裡", "端點用讀到的舊 data_json 整包寫回，蓋掉了空窗裡的寫入"
    assert landed(d), "端點自己的修改沒有落地"
