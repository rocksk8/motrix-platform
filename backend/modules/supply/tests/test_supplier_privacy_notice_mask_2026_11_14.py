# -*- coding: utf-8 -*-
"""T86：`GET /api/suppliers/{sid}/privacy-notice` 的資料範圍與 `GET /api/suppliers` 同一條線。

管理員（admin／superadmin）看完整「已告知」紀錄（時間、記錄人姓名／帳號、告知文字雜湊）；
其他只有供應商檢視權的人只看到「已告知＋日期」（`{at}`），不帶記錄人與雜湊。沒有新增權限鍵。
⚙️ 突變：拿掉遮罩分支 ⇒ 非管理員題紅；一律遮罩 ⇒ 管理員題紅。"""


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _setup(client, make_user, buyer_modules=("procurement",), buyer_role="sales"):
    su, sp = make_user(username="pm_root", role="superadmin")
    h = _login(client, su, sp)
    r = client.post("/api/suppliers", json={"name": "遮罩測試供應商", "data": {"contacts": [{"id": 111, "name": "王聯絡", "phone": "0912345678", "email": "w@x.com"}]}}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.post(f"/api/suppliers/{sid}/contacts/111/privacy-notice/ack", headers=h)
    assert r.status_code == 200 and r.json()["created"] is True, r.text
    full = r.json()["ack"]
    bu, bp = make_user(username="pm_buyer", role=buyer_role, modules=list(buyer_modules))
    return sid, h, _login(client, bu, bp), full


def test_admin_sees_the_full_ack_record(client, make_user):
    sid, h, _hb, full = _setup(client, make_user)
    acks = client.get(f"/api/suppliers/{sid}/privacy-notice", headers=h).json()["acks"]
    assert acks == {"111": full}
    assert set(full) >= {"at", "by", "byUsername", "noticeHash"}


def test_non_admin_with_supplier_view_gets_only_status_and_date(client, make_user):
    sid, _h, hb, full = _setup(client, make_user)
    r = client.get(f"/api/suppliers/{sid}/privacy-notice", headers=hb)
    assert r.status_code == 200, r.text
    acks = r.json()["acks"]
    assert acks == {"111": {"at": full["at"]}}, "只留「已告知」與日期"
    body = r.text
    for leaked in (full["by"], full["byUsername"], full["noticeHash"], "王聯絡", "0912345678", "w@x.com"):
        assert leaked and leaked not in body, "不應外洩：%s" % leaked


def test_non_admin_without_any_ack_gets_empty_and_unknown_supplier_is_404(client, make_user):
    su, sp = make_user(username="pm_root2", role="superadmin")
    h = _login(client, su, sp)
    sid = client.post("/api/suppliers", json={"name": "無紀錄供應商", "data": {"contacts": [{"id": 5, "name": "甲"}]}}, headers=h).json()["id"]
    bu, bp = make_user(username="pm_buyer2", role="sales", modules=["procurement"])
    hb = _login(client, bu, bp)
    assert client.get(f"/api/suppliers/{sid}/privacy-notice", headers=hb).json() == {"acks": {}}
    assert client.get("/api/suppliers/999999/privacy-notice", headers=hb).status_code == 404


def test_without_the_supplier_view_permission_is_still_refused(client, make_user):
    sid, _h, _hb, _full = _setup(client, make_user)
    nu, np_ = make_user(username="pm_nobody", role="sales", modules=[])
    hn = _login(client, nu, np_)
    r = client.get(f"/api/suppliers/{sid}/privacy-notice", headers=hn)
    assert r.status_code == 403, r.text
