# -*- coding: utf-8 -*-
"""接線稽核（主持 2026-09-30）：建構器的兩種簽核要接齊信件、鈴鐺、佇列。
① 模組定義送審：信件類型登記（送審→審核人、核可／退回→送審人），與站內通知同時寄；鈴鐺 ref_id `customdef:<key>:<ver>` 點了開審核頁
② 自訂模組單據簽核：提交／下一層／核准／退回 四種信件
③ 最高管理者（申請人以外）決定得了定義審核，佇列與「等我簽核」角標也要看得到（在 provider 補，不改 L1 case_access）
④ 修訂過的單據在佇列卡片帶 -R<n>（id 仍是原單號）
⑤ 信件與通知收件設定頁（/api/mail-types）列得到新類型
觀測點：被記錄的寄信呼叫（主旨）、notifications 表、佇列 API 回應；每項都有放行／反向的對照。"""
import json

import pytest

NEW_KEYS = ("custom_record_submitted", "custom_record_next_tier", "custom_record_approved", "custom_record_returned",
            "custom_def_submitted", "custom_def_approved", "custom_def_returned")


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


@pytest.fixture()
def sent(monkeypatch):
    """記錄所有 `_async_send`（收件人、主旨）；`_lookup_emails` 讓每個帳號都有信箱。"""
    from helpers import email_notify as en
    box = []
    monkeypatch.setattr(en, "_lookup_emails", lambda usernames, event_key=None: ["%s@example.invalid" % u for u in usernames])
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: box.append((tuple(to), subject, html)) or None)
    return box


def _subjects(box):
    return [s for _to, s, _h in box]


def test_new_mail_types_are_registered_and_listed_on_the_settings_page(client, make_user):
    from helpers import mail_types as mt
    for k in NEW_KEYS:
        t = mt.get(k)
        assert t is not None and t.category == "approval" and t.group == "none", k
    boss = _login(client, make_user, "wr_boss0", role="superadmin")
    listed = client.get("/api/mail-types", headers=boss).json()
    keys = {t["key"] for t in listed["items"]}
    assert set(NEW_KEYS) <= keys, sorted(set(NEW_KEYS) - keys)


# ── ① 模組定義送審 ──

KEY = "wrdef"


def _def_body():
    return {"name": "接線測試", "permission": "custom." + KEY, "numbering": {"prefix": "WR", "period": "none", "digits": 3},
            "fields": [{"key": "t", "label": "標題", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "go", "label": "送出", "from": "draft", "to": "done"}]}}


@pytest.fixture()
def defworld(client, make_user, sent):
    boss = _login(client, make_user, "wr_boss", role="superadmin")
    appr = _login(client, make_user, "wr_appr", role="admin", modules=[])
    assert client.put("/api/custom-modules/definition-review", headers=boss, json={"reviewers": ["wr_appr"]}).status_code == 200
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": _def_body()}).status_code == 200
    return client, boss, appr, sent


def _ref_ids():
    import db
    c = db.get_db()
    try:
        return [r["ref_id"] for r in c.execute("SELECT ref_id FROM notifications WHERE type='custom_module_def' ORDER BY id").fetchall()]
    finally:
        c.close()


def test_definition_review_sends_mail_and_a_clickable_bell_notice(defworld):
    client, boss, appr, sent = defworld
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={"note": "n"}).json()["pending"] is True
    assert any("自訂模組定義待審核" in s for s in _subjects(sent)), _subjects(sent)
    assert ("wr_appr@example.invalid",) in [to for to, _s, _h in sent]
    assert _ref_ids() == ["customdef:%s:1" % KEY]                           # 鈴鐺：可解析的 ref_id
    sent.clear()
    assert client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "欄位不夠"}).status_code == 200
    assert any("自訂模組定義已退回" in s for s in _subjects(sent)) and any("欄位不夠" in h for _t, _s, h in sent)
    # 對照：核可 ⇒ 「已核可」信
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={"note": "n"}).status_code == 200
    sent.clear()
    assert client.post("/api/custom-modules/%s/definition/2/approve" % KEY, headers=appr, json={"note": "ok"}).status_code == 200
    assert any("自訂模組定義已核可" in s for s in _subjects(sent))


def test_bell_ref_is_resolved_by_notif_js():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    js = open(os.path.join(here, "..", "..", "frontend", "static", "notif.js"), encoding="utf-8").read()
    assert "customdef:" in js and "custom-def-review.html" in js


# ── ③ 最高管理者在佇列 ──

def test_other_superadmin_sees_and_counts_the_definition_review(defworld, make_user):
    client, boss, appr, sent = defworld
    sa2 = _login(client, make_user, "wr_sa2", role="superadmin")
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={}).json()["pending"] is True
    q = client.get("/api/approval-queue", headers=sa2).json()
    items = [i for g in q["queue"] for i in g["items"] if i.get("type") == "custom_module_def"]
    assert len(items) == 1 and "wr_sa2" in [a["username"] for a in items[0]["currentApprovers"]]
    assert client.get("/api/approval-queue/count", headers=sa2).json().get("count", client.get("/api/approval-queue/count", headers=sa2).json()) not in (0, None)
    # 申請人自己不算「輪到我」
    cnt_boss = client.get("/api/approval-queue/count", headers=boss).json()
    assert (cnt_boss.get("count") if isinstance(cnt_boss, dict) else cnt_boss) in (0, None)
    # 最高管理者真的決定得了
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=sa2, json={"note": "ok"}).status_code == 200


# ── ② ④ 單據簽核 ──

CR = "wrrec"


def _rec_module(a1, a2):
    return {"name": "接線單據", "permission": "custom." + CR, "numbering": {"prefix": "WC", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {"tiers": [{"approvers": [{"username": a1}]}, {"approvers": [{"username": a2}]}],
                                                                  "on_approved": "done", "on_rejected": "draft"}},
                {"key": "done", "label": "完成", "final": True}],
                "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]}}


@pytest.fixture()
def recworld(client, make_user, sent):
    admin = _login(client, make_user, "wr_radmin", role="superadmin")
    u1 = _login(client, make_user, "wr_m1", role="viewer", modules=[])
    u2 = _login(client, make_user, "wr_m2", role="viewer", modules=[])
    user = _login(client, make_user, "wr_ruser", role="viewer", modules=["custom.%s" % CR])
    assert client.put("/api/definitions/custom_module/%s/draft" % CR, headers=admin, json={"body": _rec_module("wr_m1", "wr_m2")}).status_code == 200
    assert client.post("/api/definitions/custom_module/%s/publish" % CR, headers=admin, json={}).status_code == 200
    no = client.post("/api/custom/%s/records" % CR, headers=user, json={"values": {"a": "x"}}).json()["record_no"]
    return client, user, u1, u2, no, sent


def test_custom_record_approval_sends_four_kinds_of_mail(recworld):
    client, user, m1, m2, no, sent = recworld
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (CR, no), headers=user, json={}).status_code == 200
    assert any("待審核" in s and no in s for s in _subjects(sent)) and ("wr_m1@example.invalid",) in [t for t, _s, _h in sent]
    sent.clear()
    assert client.post("/api/custom/%s/records/%s/approve" % (CR, no), headers=m1, json={"note": ""}).status_code == 200
    assert any("審核通知（第 2/2 層）" in s for s in _subjects(sent)) and ("wr_m2@example.invalid",) in [t for t, _s, _h in sent]
    sent.clear()
    assert client.post("/api/custom/%s/records/%s/approve" % (CR, no), headers=m2, json={"note": ""}).status_code == 200
    assert any("已核准" in s for s in _subjects(sent)) and ("wr_ruser@example.invalid",) in [t for t, _s, _h in sent]


def test_custom_record_reject_sends_returned_mail_with_the_reason(recworld):
    client, user, m1, m2, no, sent = recworld
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (CR, no), headers=user, json={}).status_code == 200
    sent.clear()
    assert client.post("/api/custom/%s/records/%s/reject" % (CR, no), headers=m1, json={"note": "數量不對"}).status_code == 200
    assert any("已退回" in s for s in _subjects(sent)) and any("數量不對" in h for _t, _s, h in sent)


def test_queue_card_shows_the_revision_suffix_but_keeps_the_plain_record_no(recworld):
    client, user, m1, m2, no, sent = recworld
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (CR, no), headers=user, json={}).status_code == 200
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE custom_records SET revision=2 WHERE module_key=? AND record_no=?", (CR, no))
        c.commit()
    finally:
        c.close()
    q = client.get("/api/approval-queue", headers=m1).json()
    it = [i for g in q["queue"] for i in g["items"] if i.get("type") == "custom_record"][0]
    assert it["quoteNo"] == no and it["displayNo"] == no + "-R2"
    # 對照：沒修訂過 ⇒ displayNo 等於單號
    c = db.get_db()
    try:
        c.execute("UPDATE custom_records SET revision=0 WHERE module_key=? AND record_no=?", (CR, no))
        c.commit()
    finally:
        c.close()
    it = [i for g in client.get("/api/approval-queue", headers=m1).json()["queue"] for i in g["items"] if i.get("type") == "custom_record"][0]
    assert it["displayNo"] == no
