# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_report_recognition_basis_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
營運報表的認列口徑（權責／現金）與「待補登」標註（2026-09-24 使用者規則＋hichan-0a 細部裁示）。

```
權責（預設）  收入＝成交未稅 × 階段比例，認列在階段完成月；沒設比例 ⇒ 全部完工月；沒完工 ⇒ 不認列
              支出＝廠商發票月；沒登錄 ⇒ 暫用核准／完工月並標註；拆得出稅用未稅
現金          收入＝收款日（含稅）；派工＝匯款申請已匯款日；叫料＝付款日；額外支出＝付款日→憑證日
標註          每一種：有狀況 ⇒ 出現；補登後 ⇒ 消失
```
"""
import json

import pytest

URL = "/api/reports/expenses-monthly"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def sa(client, make_user):
    return _login(client, *make_user(username="rb_sa", role="superadmin"))


def _db():
    import db
    return db.get_db()


def _case(no, pretax=10000, total=10500, data=None, deal="已成案"):
    data = dict(data or {})
    data.setdefault("dealTag", deal)
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "認列客戶", "認列專案", total, pretax, json.dumps(data, ensure_ascii=False),
             "2026-01-01", "2026-01-01", deal))
        conn.commit()
    finally:
        conn.close()


def _stage(no, label, done=False, done_at="", ratio=None, order=0):
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, start_date, due_date,"
            " assigned_to, depends_on, created_at, updated_at, ratio_bp) VALUES (?,?,?,?,?,'','','[]','[]','t','t',?)",
            (no, label, order, 1 if done else 0, done_at, ratio))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _dispatch(no, total=10000, dispatch_date="2026-03-15", invoice_date="", accepted_at=""):
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO vendor_contractors (name, active, created_at) VALUES ('認列承攬商',1,'t')")
        vid = conn.execute("SELECT id FROM vendor_contractors WHERE name='認列承攬商'").fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount,"
            " status, created_at, updated_at, invoice_date, accepted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, vid, dispatch_date, "s", "[]", total, "confirmed", "t", "t", invoice_date, accepted_at))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _report(client, hdr, basis=None, month="2026-03", year=2026):
    q = "%s?year=%s&month=%s" % (URL, year, month) + ("&basis=%s" % basis if basis else "")
    r = client.get(q, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def _month(body, mo, key):
    return next(m for m in body["expenses"]["monthly"] if m["month"] == mo)[key]


def _flag_quotes(body, kind):
    return [i["quoteNo"] for i in body["recognitionFlags"][kind]["items"]]


# ══════════════════════════════════════════════════════════════════════
# 收入：純函式
# ══════════════════════════════════════════════════════════════════════

def _rev(stages, pretax=10000):
    from modules.case.recognition import stage_revenue
    return stage_revenue(pretax, stages)


# ══════════════════════════════════════════════════════════════════════
# 收入：報表
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 派工
# ══════════════════════════════════════════════════════════════════════


def test_dispatch_invoice_date_is_validated(client, sa):
    _case("MQ-RB-012")
    did = _dispatch("MQ-RB-012")
    for bad in ("2026-13-01", "2026/03/01", "20260301"):
        r = client.patch("/api/contractor-dispatches/%s/invoice-date" % did, headers=sa, json={"invoiceDate": bad})
        assert r.status_code == 400, bad


# ══════════════════════════════════════════════════════════════════════
# 叫料
# ══════════════════════════════════════════════════════════════════════

def _mo(invoice=""):
    return {"itemId": "m1", "itemName": "線材", "quantity": 10, "unit": "捲", "unitPrice": 100,
            "totalPrice": 1000, "paidStatus": "paid", "paidAmount": 1000, "paidDate": "2026-03-09",
            "notes": "", "invoiceDate": invoice}


# ══════════════════════════════════════════════════════════════════════
# 額外支出
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 階段比例與完工
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 舊稅率單、金額遮蔽
# ══════════════════════════════════════════════════════════════════════


def test_a_dispatch_put_without_the_invoice_date_key_keeps_it(client, sa):
    """其他頁面的 PUT 沒帶 invoice_date ⇒ 保留原值（不可以被清成未登錄）。"""
    _case("MQ-RB-014")
    did = _dispatch("MQ-RB-014", invoice_date="2026-05-03")
    body = {"quote_no": "MQ-RB-014", "vendor_id": None, "personnel_json": [{"name": "甲", "amount": 100}],
            "dispatch_date": "2026-03-15"}
    assert client.put("/api/contractor-dispatches/%s" % did, headers=sa, json=body).status_code == 200
    conn = _db()
    try:
        assert conn.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == "2026-05-03"
    finally:
        conn.close()
    body["invoice_date"] = ""
    assert client.put("/api/contractor-dispatches/%s" % did, headers=sa, json=body).status_code == 200
    conn = _db()
    try:
        assert conn.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == ""
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 叫料發票日期專用端點（已結案也可登）、首頁月支出與報表同一份計算
# ══════════════════════════════════════════════════════════════════════

MO_INV = "/api/quotations/%s/material-orders/%s/invoice-date"


def _one_json(no):
    conn = _db()
    try:
        return conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0]
    finally:
        conn.close()
