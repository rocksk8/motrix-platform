# -*- coding: utf-8 -*-
"""營運報表的認列口徑（權責／現金）與「待補登」標註（2026-09-24 使用者規則＋hichan-0a 細部裁示）。

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
    from helpers.recognition import stage_revenue
    return stage_revenue(pretax, stages)


def test_no_ratio_all_done_recognizes_everything_in_the_last_done_month():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": None},
              {"label": "b", "done": True, "doneAt": "2026-04-01", "ratioBp": None}])
    assert [(e["date"], e["amount"]) for e in r["entries"]] == [("2026-04-01", 10000)]
    assert r["flags"] == {"stage_ratio_unset"}


def test_no_ratio_not_all_done_is_not_recognized():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": None},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": None}])
    assert r["entries"] == [] and r["unrecognized"] == 10000
    assert r["flags"] == {"stage_ratio_unset", "case_incomplete"}


def test_ratios_recognize_each_done_stage_in_its_month():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 3000},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": 7000}])
    assert [(e["label"], e["date"], e["amount"]) for e in r["entries"]] == [("a", "2026-02-10", 3000)]
    assert r["flags"] == {"case_incomplete"} and r["unrecognized"] == 7000


def test_ratios_not_adding_to_100_are_flagged_and_not_topped_up():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 3000},
              {"label": "b", "done": True, "doneAt": "2026-03-10", "ratioBp": 6000}])
    assert sum(e["amount"] for e in r["entries"]) == 9000, "不補差"
    assert r["flags"] == {"stage_ratio_not_100"}


def test_zero_ratio_is_set_not_unset():
    """0＝這個階段不認列；None＝未設——兩件事（null≠0）。"""
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 0},
              {"label": "b", "done": True, "doneAt": "2026-03-10", "ratioBp": 10000}])
    assert "stage_ratio_unset" not in r["flags"]
    assert [(e["label"], e["amount"]) for e in r["entries"]] == [("b", 10000)]


def test_all_zero_ratios_recognize_nothing_rather_than_everything():
    """全部設 0：比例「有設」而合計 0% ⇒ 不認列、標 ≠100%；**不可以**退回「未設 ⇒ 完工月一次認列」。"""
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 0}])
    assert r["entries"] == []
    assert r["flags"] == {"stage_ratio_not_100"}


def test_done_without_a_date_is_not_recognized():
    r = _rev([{"label": "a", "done": True, "doneAt": "", "ratioBp": None}])
    assert r["entries"] == [] and "case_incomplete" in r["flags"]


def test_rounding_is_half_up_not_bankers():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 5000},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": 5000}], pretax=5)
    assert r["entries"][0]["amount"] == 3   # 2.5 → 3（round() 會給 2）


# ══════════════════════════════════════════════════════════════════════
# 收入：報表
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 派工
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 叫料
# ══════════════════════════════════════════════════════════════════════

def _mo(invoice=""):
    return {"itemId": "m1", "itemName": "線材", "quantity": 10, "unit": "捲", "unitPrice": 100,
            "totalPrice": 1000, "paidStatus": "paid", "paidAmount": 1000, "paidDate": "2026-03-09",
            "notes": "", "invoiceDate": invoice}


def test_material_invoice_date_is_validated(client, sa):
    _case("MQ-RB-021", data={"caseRecord": {"materialOrders": []}})
    r = client.patch("/api/quotations/MQ-RB-021/material-orders", headers=sa,
                     json={"materialOrders": [_mo("2026-02-30")]})
    assert r.status_code == 400, r.text


# ══════════════════════════════════════════════════════════════════════
# 額外支出
# ══════════════════════════════════════════════════════════════════════


def test_extra_expense_dates_can_be_entered_after_approval_but_not_by_strangers(
        client, sa, make_user, seed_extra_expense):
    _case("MQ-RB-031")
    eid = seed_extra_expense("MQ-RB-031", total_cost=500, expense_date="2026-03-02", status="已核准")
    other = _login(client, *make_user(username="rb_other", role="admin"))
    assert client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=other,
                        json={"paidDate": "2026-03-03"}).status_code == 200, "admin 可以"
    stranger = _login(client, *make_user(username="rb_eng", role="engineer", modules=["case_manage"]))
    r = client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=stranger,
                     json={"paidDate": "2026-03-03"})
    assert r.status_code in (403, 404), r.text
    assert client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=sa,
                        json={"paidDate": "03/03/2026"}).status_code == 400


# ══════════════════════════════════════════════════════════════════════
# 階段比例與完工
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("bad", [10001, -1, 12.5, "abc", True])
def test_stage_ratio_is_validated(client, sa, bad):
    _case("MQ-RB-041")
    sid = _stage("MQ-RB-041", "施工")
    assert client.put("/api/quotations/MQ-RB-041/stages/%s" % sid, headers=sa,
                      json={"ratioBp": bad}).status_code == 400


def test_stage_ratio_can_be_cleared_back_to_unset(client, sa):
    _case("MQ-RB-042")
    sid = _stage("MQ-RB-042", "施工", ratio=10000)
    r = client.put("/api/quotations/MQ-RB-042/stages/%s" % sid, headers=sa, json={"ratioBp": None})
    assert r.status_code == 200 and r.json()["ratioBp"] is None


# ══════════════════════════════════════════════════════════════════════
# 舊稅率單、金額遮蔽
# ══════════════════════════════════════════════════════════════════════


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


def test_material_invoice_date_endpoint_guards(client, sa, make_user):
    _case("MQ-RB-023", data={"caseRecord": {"materialOrders": [_mo()]}})
    assert client.patch(MO_INV % ("MQ-RB-023", "nope"), headers=sa, json={"invoiceDate": "2026-04-20"}).status_code == 404
    assert client.patch(MO_INV % ("MQ-RB-023", "m1"), headers=sa, json={"invoiceDate": "2026-4-2"}).status_code == 400
    eng = _login(client, *make_user(username="rb_mo_eng", role="engineer"))
    assert client.patch(MO_INV % ("MQ-RB-023", "m1"), headers=eng, json={"invoiceDate": "2026-04-20"}).status_code == 403
    cash = _login(client, *make_user(username="rb_mo_cash", role="admin", modules=["cashier"]))
    assert client.patch(MO_INV % ("MQ-RB-023", "m1"), headers=cash, json={"invoiceDate": "2026-04-20"}).status_code == 200
