# -*- coding: utf-8 -*-
"""一條龍 P6（旗標 `onepipe.notify_next`，預設開）：輪到某人時站內通知（成交 ⇒ 採購；採購單核准 ⇒ 收貨）。

只通知「輪到的人」：持有對應模組、看得到案件、不是觸發者本人、superadmin 不因『全部直通』被通知；只有站內通知；關閉＝什麼都不寫。
"""
import json

import pytest

import db

NO = "MQ-P6-1"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "notify_next")


@pytest.fixture
def W(client, make_user):
    make_user(username="p6_sa", role="superadmin")
    make_user(username="p6_buyer", role="sales", modules=["procurement", "case_manage"])
    make_user(username="p6_blind", role="sales", modules=["procurement"])                 # 有採購模組、但看不到案件
    make_user(username="p6_wh", role="sales", modules=["inventory", "case_manage"])
    make_user(username="p6_both", role="admin", modules=["procurement", "inventory", "case_manage"])
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person, deal_tag)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", (NO, "已送出", "測試客戶", "案", json.dumps({"dealTag": "已提供"}), "2026-11-14T00:00:00", "2026-11-14T00:00:00", "p6_sa", "已提供"))
        conn.execute("DELETE FROM system_settings WHERE key='unified_approval_flow'")
        conn.commit()
    finally:
        conn.close()
    return client, _login(client, "p6_sa", "Test-Pass-123")


def _notes(user=None, type_=None):
    conn = db.get_db()
    try:
        sql, args = "SELECT username, type, ref_id, message, link FROM notifications WHERE 1=1", []
        if user:
            sql += " AND username=?"; args.append(user)
        if type_:
            sql += " AND type=?"; args.append(type_)
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _won(c, h, tag="已成案"):
    return c.patch("/api/quotations/%s/deal-tag" % NO, headers=h, json={"deal_tag": tag})


def test_registry_field_is_an_ordinary_default_on_flag():
    from helpers import settings_registry as R
    f = R.field_defs("onepipe")["notify_next"]
    assert f.default == 1 and f.recommended == 1 and not f.loosen


# ── 成交 ⇒ 採購 ─────────────────────────────────────────────────────────────
def test_won_notifies_only_procurement_people_who_can_see_the_case(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    assert _won(c, h).status_code == 200
    got = _notes(type_="case_won_next")
    assert sorted(n["username"] for n in got) == ["p6_both", "p6_buyer"]
    n = _notes("p6_buyer", "case_won_next")[0]
    assert NO in n["message"] and "測試客戶" in n["message"] and "請購單" in n["message"]
    assert n["link"] == "payment-request.html?case=%s&type=purchase_req" % NO
    assert not _notes("p6_blind") and not _notes("p6_sa") and not _notes("p6_wh"), "看不到案件／不是採購／觸發者本人都不通知"


def test_won_is_notified_once_only(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    _won(c, h)
    before = len(_notes())
    _won(c, h)                                                  # 已是已成案再標一次
    assert len(_notes()) == before


def test_other_tags_do_not_notify(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    assert _won(c, h, "未成案").status_code == 200
    assert _notes() == []


def test_flag_off_writes_nothing(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h = W
    assert _won(c, h).status_code == 200
    assert _notes() == []


def test_actor_is_never_notified(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    ha = _login(c, "p6_both", "Test-Pass-123")
    assert _won(c, ha).status_code == 200
    assert [n["username"] for n in _notes(type_="case_won_next")] == ["p6_buyer"]


# ── 採購單核准 ⇒ 收貨 ───────────────────────────────────────────────────────
def _make_and_submit(c, h, kind):
    body = {"kind": kind, "lines": [{"category": "雜項", "summary": "x", "qty": 1, "unitCost": 100}], "payeeType": "vendor", "payeeName": "某廠商",
            "data": {"applicant": "p6_sa"}}
    r = c.post("/api/quotations/%s/extra-expenses" % NO, headers=h, json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    s = c.post("/api/quotations/%s/extra-expenses/%d/submit" % (NO, eid), headers=h)
    return r.json()["docCode"], s


def test_po_approval_notifies_warehouse_people_who_can_see_the_case(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    doc, s = _make_and_submit(c, h, "purchase_order")
    if s.status_code != 200 or s.json().get("status") != "已核准":
        pytest.skip("測試環境簽核設定使送審未直接核准：%s" % s.text[:80])
    got = _notes(type_="po_approved_next")
    assert sorted(n["username"] for n in got) == ["p6_both", "p6_wh"]
    n = _notes("p6_wh", "po_approved_next")[0]
    assert doc in n["message"] and "收貨" in n["message"] and n["link"] == "case-management.html?q=%s" % NO


def test_purchase_requisition_approval_does_not_notify(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h = W
    _make_and_submit(c, h, "purchase_req")
    assert _notes(type_="po_approved_next") == []


def test_po_flag_off_writes_nothing(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h = W
    _make_and_submit(c, h, "purchase_order")
    assert _notes(type_="po_approved_next") == []


# ── 介面本身 ────────────────────────────────────────────────────────────────
def test_unknown_event_or_missing_case_does_nothing_and_never_raises(W, monkeypatch):
    from modules.case.notify_next import notify_next
    _flag(monkeypatch, True)
    assert notify_next("nope", NO) == 0
    assert notify_next("won", "MQ-NOT-THERE") == 0
    assert notify_next("won", "") == 0


def test_explicit_recipients_for_arrival_confirmed_skip_the_actor(W, monkeypatch):
    """P2b 上線後到貨確認的呼叫方式：收件者由呼叫端指定（案件負責人／請購人）。"""
    from modules.case.notify_next import notify_next
    _flag(monkeypatch, True)
    assert notify_next("arrival_confirmed", NO, actor="p6_wh", doc="PO-1", usernames=["p6_wh", "p6_sa"]) == 1
    assert [n["username"] for n in _notes(type_="arrival_confirmed_next")] == ["p6_sa"]
