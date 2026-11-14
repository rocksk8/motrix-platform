# -*- coding: utf-8 -*-
"""T86（PM 裁示：供應商之外的 `*/privacy-notice` 端點照同一條線處理）：「已告知」紀錄的讀取範圍。

規則（同 `GET /api/suppliers`，不新增權限鍵）：管理員（admin／superadmin）看完整紀錄（時間、記錄人姓名／帳號、告知文字雜湊）；
其他人只看「已告知＋日期」（`{at}`）。寫入的紀錄與稽核仍是完整的，只遮回應。

涵蓋：customers／quotations／completion-notes／network-plans／shipping-notes 的 GET（非管理員讀得到的），
customers／quotations 的 POST ack 回傳（非管理員可呼叫、已記錄過時回既有紀錄＝GET 遮罩的後門，h11 F1 同型）。
material-payments 在該模組自己的測試檔；contractors／vendor-contractors／users 的 GET 本來就只給管理員（本檔釘住不被放寬）。
共用函式 `helpers.privacy_notice.ack_view／acks_view` 的單元題也在這裡。
⚙️ 突變：任一端點拿掉 `acks_view／ack_view` ⇒ 該端點的非管理員題紅；helper 一律遮罩 ⇒ 管理員題紅。
"""
import json

import pytest

from helpers import privacy_notice as pn
from tests._requires import requires_module

needs_m01 = requires_module("case", "本題打 M01（案件）的端點；M01 不在時沒有對象")
needs_netplan = requires_module("netplan", "本題打網路規劃（netplan）的端點；netplan 不在時沒有對象")
needs_supply = requires_module("supply", "本題打出貨單（supply）的端點；supply 不在時沒有對象")

FULL = {"at": "2026-11-14T09:00:00", "by": "記錄人甲", "byUsername": "rec_a", "noticeHash": "0123456789abcdef"}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _staff(client, make_user, suffix, modules):
    u, p = make_user(username="pnm_" + suffix, role="sales", modules=list(modules))
    return _login(client, u, p)


def _root(client, make_user, name="pnm_root"):
    u, p = make_user(username=name, role="superadmin")
    return _login(client, u, p)


def _no_leak(text, full):
    for leaked in (full["by"], full["byUsername"], full["noticeHash"]):
        assert leaked and leaked not in text, "不應外洩：%s" % leaked


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _insert_quote(quote_no, contact="林聯絡", assigned=()):
    """`assigned`＝被指派的使用者名稱（非管理員要被指派到案件才看得到，M01-O1）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "遮罩測試", 1000, 952,
             json.dumps({"dealTag": "已成案", "contactName": contact}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "",
             json.dumps([_uid(u) for u in assigned])))
        conn.commit()
    finally:
        conn.close()


# ── 共用函式 ───────────────────────────────────────────────────────────────────

def test_ack_view_helper_admin_full_others_status_and_date_only():
    for role in ("superadmin", "admin"):
        assert pn.ack_view({"role": role}, FULL) == FULL
    for role in ("sales", "finance", "engineer", ""):
        assert pn.ack_view({"role": role}, FULL) == {"at": FULL["at"]}
    assert pn.ack_view({"role": "sales"}, None) is None, "沒有紀錄原樣回（None＝尚未告知）"
    assert pn.ack_view({"role": "sales"}, {"by": "只有人沒有時間"}) == {"at": ""}
    assert pn.ack_view(None, FULL) == {"at": FULL["at"]}, "沒有使用者＝不是管理員"
    assert pn.acks_view({"role": "sales"}, {"a": FULL, "b": {"at": "x", "by": "y"}}) == {"a": {"at": FULL["at"]}, "b": {"at": "x"}}
    assert pn.acks_view({"role": "admin"}, {"a": FULL}) == {"a": FULL}
    assert pn.acks_view({"role": "sales"}, {}) == {}


# ── customers ─────────────────────────────────────────────────────────────────

def _customer(client, make_user):
    h = _root(client, make_user)
    r = client.post("/api/customers", json={"name": "遮罩客戶", "data": {"contacts": [{"id": 111, "name": "王聯絡", "phone": "0912345678", "email": "w@x.com"}]}}, headers=h)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = client.post(f"/api/customers/{cid}/contacts/111/privacy-notice/ack", headers=h)
    assert r.status_code == 200 and r.json()["created"] is True, r.text
    return cid, h, r.json()["ack"]


def test_customers_get_admin_full_non_admin_masked(client, make_user):
    cid, h, full = _customer(client, make_user)
    assert client.get(f"/api/customers/{cid}/privacy-notice", headers=h).json()["acks"] == {"111": full}
    hb = _staff(client, make_user, "cust", ["customer"])
    r = client.get(f"/api/customers/{cid}/privacy-notice", headers=hb)
    assert r.status_code == 200, r.text
    assert r.json()["acks"] == {"111": {"at": full["at"]}}
    _no_leak(r.text, full)
    for leaked in ("王聯絡", "0912345678", "w@x.com"):
        assert leaked not in r.text


def test_customers_post_ack_echo_is_masked_for_non_admin_but_stored_in_full(client, make_user):
    cid, h, full = _customer(client, make_user)
    hb = _staff(client, make_user, "cust2", ["customer"])
    r = client.post(f"/api/customers/{cid}/contacts/111/privacy-notice/ack", headers=hb)
    assert r.status_code == 200, r.text
    assert r.json() == {"ack": {"at": full["at"]}, "created": False}
    _no_leak(r.text, full)
    assert client.post(f"/api/customers/{cid}/contacts/111/privacy-notice/ack", headers=h).json() == {"ack": full, "created": False}
    # 非管理員第一次記錄：儲存的是完整紀錄，回應只有 at
    r = client.post("/api/customers", json={"name": "第二客戶", "data": {"contacts": [{"id": 7, "name": "乙"}]}}, headers=h)
    cid2 = r.json()["id"]
    r = client.post(f"/api/customers/{cid2}/contacts/7/privacy-notice/ack", headers=hb)
    assert r.status_code == 200 and r.json()["created"] is True
    assert set(r.json()["ack"]) == {"at"}
    stored = pn.get_ack("customer_contact", f"{cid2}:7")
    assert stored["byUsername"] == "pnm_cust2" and stored["noticeHash"]


# ── quotations（POST 非管理員要有案件權；用 case_manage 持有者）──────────────────────

@needs_m01
@pytest.mark.parametrize("role,kind,name", [("contact", "quote_contact", "林聯絡")])
def test_quotations_get_and_post_masked_for_non_admin(client, make_user, role, kind, name):
    h = _root(client, make_user)
    hb = _staff(client, make_user, "quote", ["case_manage"])
    no = "PNM-Q-001"
    _insert_quote(no, assigned=["pnm_quote"])
    base = f"/api/quotations/{no}/privacy-notice"
    r1 = client.post(base + "/ack", json={"role": role, "subject": name}, headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    full = r1.json()["ack"]
    assert client.get(base + "?role=" + role, headers=h).json()["acks"] == {name: full}
    g = client.get(base + "?role=" + role, headers=hb)
    assert g.status_code == 200, g.text
    assert g.json()["acks"] == {name: {"at": full["at"]}}
    _no_leak(g.text, full)
    p = client.post(base + "/ack", json={"role": role, "subject": name}, headers=hb)
    assert p.status_code == 200, p.text
    assert p.json() == {"ack": {"at": full["at"]}, "created": False}
    _no_leak(p.text, full)
    assert client.post(base + "/ack", json={"role": role, "subject": name}, headers=h).json() == {"ack": full, "created": False}


# ── completion-notes（POST 只有管理員；GET 讀得到的人是案件相關人員）─────────────────

@needs_m01
def test_completion_notes_get_masked_for_non_admin(client, make_user):
    h = _root(client, make_user)
    hb = _staff(client, make_user, "cn", ["case_manage"])
    _insert_quote("PNM-CN-001", assigned=["pnm_cn"])
    r = client.post("/api/completion-notes", json={"quote_no": "PNM-CN-001", "recipient": "陳經理"}, headers=h)
    assert r.status_code == 201, r.text
    no = r.json()["note_no"]
    base = f"/api/completion-notes/{no}/privacy-notice"
    full = client.post(base + "/ack", json={"subject": "陳經理"}, headers=h).json()["ack"]
    assert client.get(base, headers=h).json()["acks"] == {"陳經理": full}
    g = client.get(base, headers=hb)
    assert g.status_code == 200, g.text
    assert g.json()["acks"] == {"陳經理": {"at": full["at"]}}
    _no_leak(g.text, full)
    assert client.post(base + "/ack", json={"subject": "陳經理"}, headers=hb).status_code == 403, "POST 仍只給管理員"


# ── network-plans（POST 只有 superadmin）─────────────────────────────────────────

@needs_netplan
def test_network_plans_get_masked_for_non_admin(client, make_user):
    h = _root(client, make_user)
    r = client.post("/api/network-plans", json={"siteName": "遮罩案場", "contactName": "周窗口"}, headers=h)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    base = f"/api/network-plans/{pid}/privacy-notice"
    full = client.post(base + "/ack", json={"subject": "周窗口"}, headers=h).json()["ack"]
    assert client.get(base, headers=h).json()["acks"] == {"周窗口": full}
    hb = _staff(client, make_user, "np", ["netplan"])
    g = client.get(base, headers=hb)
    assert g.status_code == 200, g.text
    assert g.json()["acks"] == {"周窗口": {"at": full["at"]}}
    _no_leak(g.text, full)
    assert client.post(base + "/ack", json={"subject": "周窗口"}, headers=hb).status_code == 403, "只有檢視模組不能 POST"
    # 持有 netplan_edit 的非管理員可以 POST；已記錄過時回傳的既有紀錄同樣只給 {at}
    he = _staff(client, make_user, "npe", ["netplan", "netplan_edit"])
    p = client.post(base + "/ack", json={"subject": "周窗口"}, headers=he)
    assert p.status_code == 200, p.text
    assert p.json() == {"ack": {"at": full["at"]}, "created": False}
    _no_leak(p.text, full)


# ── shipping-notes（POST 只有管理員）────────────────────────────────────────────

@needs_supply
def test_shipping_notes_get_masked_for_non_admin(client, make_user):
    import db
    h = _root(client, make_user)
    hb = _staff(client, make_user, "sn", ["case_manage"])
    _insert_quote("PNM-SN-001", assigned=["pnm_sn"])
    conn = db.get_db()
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(shipping_notes)").fetchall()]
        vals = {"note_no": "SN-PNM-001", "quote_no": "PNM-SN-001", "recipient": "收件陳", "status": "草稿",
                "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}
        use = {k: v for k, v in vals.items() if k in cols}
        conn.execute("INSERT INTO shipping_notes (%s) VALUES (%s)" % (",".join(use), ",".join("?" * len(use))), tuple(use.values()))
        conn.commit()
    finally:
        conn.close()
    base = "/api/shipping-notes/SN-PNM-001/privacy-notice"
    full = client.post(base + "/ack", json={"subject": "收件陳"}, headers=h).json()["ack"]
    assert client.get(base, headers=h).json()["acks"] == {"收件陳": full}
    g = client.get(base, headers=hb)
    assert g.status_code == 200, g.text
    assert g.json()["acks"] == {"收件陳": {"at": full["at"]}}
    _no_leak(g.text, full)
    assert client.post(base + "/ack", json={"subject": "收件陳"}, headers=hb).status_code == 403


# ── contractors：GET／POST 的閘是「superadmin 或持有 contractor_list」＝非管理員讀得到 ────────────────

def test_contractors_get_and_post_masked_for_module_holder(client, make_user):
    h = _root(client, make_user)
    r = client.post("/api/contractors", json={"name": "遮罩承攬人"}, headers=h)
    assert r.status_code in (200, 201), r.text
    cid = r.json().get("id")
    base = f"/api/contractors/{cid}/privacy-notice"
    full = client.post(base + "/ack", headers=h).json()["ack"]
    assert client.get(base, headers=h).json() == {"ack": full}
    hb = _staff(client, make_user, "ctr", ["contractor_list"])
    g = client.get(base, headers=hb)
    assert g.status_code == 200, g.text
    assert g.json() == {"ack": {"at": full["at"]}}
    _no_leak(g.text, full)
    p = client.post(base + "/ack", headers=hb)
    assert p.status_code == 200, p.text
    assert p.json() == {"ack": {"at": full["at"]}, "created": False}
    _no_leak(p.text, full)
    hn = _staff(client, make_user, "ctr_no", ["customer"])
    assert client.get(base, headers=hn).status_code == 403
    assert client.get(base).status_code in (401, 403)


# ── vendor-contractors／users：GET 本來就只給管理員／superadmin，釘住不被放寬 ─────────────────

def test_admin_only_gets_stay_admin_only(client, make_user):
    hb = _staff(client, make_user, "plain", ["customer", "procurement", "case_manage", "contractor_list"])
    assert client.get("/api/vendor-contractors/1/privacy-notice", headers=hb).status_code == 403
    assert client.get("/api/users/1/privacy-notice", headers=hb).status_code == 403
