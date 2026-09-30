# -*- coding: utf-8 -*-
"""會計傳票簽核信（送審／下一層／核准／退回）：收件人對、只在該寄時寄、寄信失敗不擋簽核動作。"""
import json

import pytest

import db
from helpers import _set_setting
from helpers import email_notify as EN
from helpers import mail_types as MT
from modules.accounting import notify as N


def _login(client, make_user, name, role="staff", modules=("cashier", "finance")):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = list(modules)
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    c = db.get_db()
    c.execute("UPDATE users SET email=? WHERE username=?", ("%s@example.com" % u, u))
    c.commit()
    c.close()
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: box.append((sorted(to), subject, html)))
    c = db.get_db()
    c.execute("DELETE FROM system_settings WHERE key IN ('voucher_approval_flow','voucher_auto_approval_flow')")
    c.commit()
    c.close()
    return box


def _draft(client, h):
    r = client.post("/api/vouchers", headers=h, json={"voucher_date": "2186-05-10", "summary": "信件測試", "lines": [
        {"account_code": "1113", "summary": "x", "debit": 100, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 100}]})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_types_are_registered_as_approval_and_visible(client):
    for k in ("voucher_submitted", "voucher_next_tier", "voucher_approved", "voucher_returned",
              "ledger_action_submitted", "ledger_action_approved", "ledger_action_returned"):
        t = MT.get(k)
        assert t and t.category == "approval" and t.owner == "accounting" and t.impact and t.action, k


def test_built_in_two_slots_mail_flow(client, make_user, sent):
    fu, fin = _login(client, make_user, "vm_fin")
    su, sup = _login(client, make_user, "vm_sup", role="superadmin")
    vid = _draft(client, fin)
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    assert sent == []                                                       # 內建兩層沒有指定簽核人 ⇒ 送審不寄
    client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={})
    assert len(sent) == 1 and su + "@example.com" in sent[0][0] and "審核通知（第 2/2 層）" in sent[0][1]
    client.post("/api/vouchers/%d/approve" % vid, headers=sup, json={})
    assert len(sent) == 2 and sent[1][0] == [fu + "@example.com"] and "已核准" in sent[1][1]      # 核准 ⇒ 通知送審人
    assert "影響" in sent[1][2] and "建議處理" in sent[1][2]


def test_configured_flow_submit_next_tier_and_send_back(client, make_user, sent):
    fu, fin = _login(client, make_user, "vm_fin2")
    mu, mgr = _login(client, make_user, "vm_mgr")
    su, sup = _login(client, make_user, "vm_sup2", role="superadmin")
    _set_setting("voucher_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": mu, "displayName": mu}]}]})
    vid = _draft(client, fin)
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    assert len(sent) == 1 and sent[0][0] == [mu + "@example.com"] and "待審核" in sent[0][1]           # 送審 ⇒ 第一層簽核人
    client.post("/api/vouchers/%d/approve" % vid, headers=mgr, json={})
    assert len(sent) == 2 and sent[1][0] == [su + "@example.com"] and "第 2/2 層" in sent[1][1]        # 進最終層 ⇒ 最高管理者
    client.post("/api/vouchers/%d/send-back" % vid, headers=sup, json={"reason": "科目錯"})
    assert len(sent) == 3 and sent[2][0] == [fu + "@example.com"] and "已退回" in sent[2][1] and "科目錯" in sent[2][2]


def test_mail_failure_never_blocks_the_approval(client, make_user, monkeypatch):
    _, fin = _login(client, make_user, "vm_fin3")
    _, sup = _login(client, make_user, "vm_sup3", role="superadmin")
    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(N, "notify_voucher_next_tier", boom)
    monkeypatch.setattr(N, "notify_voucher_approved", boom)
    vid = _draft(client, fin)
    assert client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={}).status_code == 200
    assert client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={}).status_code == 200
    assert client.post("/api/vouchers/%d/approve" % vid, headers=sup, json={}).status_code == 200
