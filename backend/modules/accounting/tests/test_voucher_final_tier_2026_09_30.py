# -*- coding: utf-8 -*-
"""會計傳票最終關卡（使用者規則 2026-09-30）：不論流程設定成什麼，送審後最後一層一律是最高管理者（會計主管）；
儲存的流程設定一個字都不改；沒有經過這一層核准的傳票不可能過帳；引擎整批確認遇到這一層時非最高管理者會停下並說明。
"""
import json

import pytest

import db
from helpers import _set_setting
from modules.accounting.api import voucher_providers as VP
from modules.accounting.api.voucher_common import with_final_superadmin_tier

_N = [0]


def _login(client, make_user, name, role="staff", modules=("cashier", "finance")):
    u, p = make_user(username="%s%d" % (name, id(client)), role=role, modules=modules) if role != "superadmin" else make_user(username="%s%d" % (name, id(client)), role="superadmin")
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _draft(client, h):
    r = client.post("/api/vouchers", headers=h, json={"voucher_date": "2184-05-10", "summary": "最終關卡測試", "lines": [
        {"account_code": "1113", "summary": "x", "debit": 1000, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 1000}]})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _appr(vid):
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT approval_json FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0] or "{}")
    finally:
        c.close()


def _status(vid):
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _reset_flow():
    for k in ("voucher_approval_flow", "voucher_auto_approval_flow", "approval_flow_scope"):
        try:
            c = db.get_db()
            c.execute("DELETE FROM system_settings WHERE key=?", (k,))
            c.commit()
            c.close()
        except Exception:  # noqa: BLE001
            pass
    yield


def test_no_flow_configured_keeps_two_builtin_slots_and_the_second_is_superadmin_only(client, make_user):
    _, fin = _login(client, make_user, "ft_fin")
    _, sup = _login(client, make_user, "ft_sup", role="superadmin")
    vid = _draft(client, fin)
    assert client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={}).status_code == 200
    assert (_appr(vid).get("tiers") or []) == []                                                             # 沒設定流程 ⇒ 不寫鏈，維持內建兩層
    assert client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={}).status_code == 200            # 第一層：覆核，出納／財務即可
    assert _status(vid) == "簽核中"
    r = client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={})
    assert r.status_code == 403 and "最高管理者" in r.json()["detail"] and _status(vid) == "簽核中"
    assert client.post("/api/vouchers/%d/post" % vid, headers=fin, json={}).status_code >= 400               # 未核准不能過帳
    assert client.post("/api/vouchers/%d/approve" % vid, headers=sup, json={}).status_code == 200
    assert _status(vid) == "已核准"
    assert client.post("/api/vouchers/%d/post" % vid, headers=fin, json={}).status_code == 200               # 核准後 finance 可以過帳
    assert _status(vid) == "已過帳"


def test_superadmin_can_send_back_with_reason(client, make_user):
    _, fin = _login(client, make_user, "ft_fin3")
    _, sup = _login(client, make_user, "ft_sup3", role="superadmin")
    vid = _draft(client, fin)
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    assert client.post("/api/vouchers/%d/send-back" % vid, headers=sup, json={"reason": "科目要改"}).status_code == 200
    assert _status(vid) == "草稿"


def test_configured_flow_is_kept_and_the_final_tier_is_appended_once(client, make_user):
    fu, fin = _login(client, make_user, "ft_fin4")
    _, sup = _login(client, make_user, "ft_sup4", role="superadmin")
    flow = {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": fu, "displayName": fu}]}]}
    _set_setting("voucher_approval_flow", flow)
    vid = _draft(client, fin)
    assert client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={}).status_code == 200
    tiers = _appr(vid)["tiers"]
    assert [t["approvers"][0]["username"] == fu for t in tiers][0] and len(tiers) == 2 and tiers[1].get("system") is True
    assert client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={}).status_code == 200            # 第一層 finance 核准 ⇒ 進最終層
    assert _status(vid) == "簽核中"
    assert client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={}).status_code == 403
    assert client.post("/api/vouchers/%d/approve" % vid, headers=sup, json={}).status_code == 200
    assert _status(vid) == "已核准"
    c = db.get_db()
    try:
        stored = json.loads(c.execute("SELECT value_json FROM system_settings WHERE key='voucher_approval_flow'").fetchone()[0])
    finally:
        c.close()
    assert stored == flow                                                                                   # 儲存的設定一個字都沒動


def test_flow_already_ending_with_superadmin_is_not_duplicated(client, make_user):
    su, sup = _login(client, make_user, "ft_sup5", role="superadmin")
    _, fin = _login(client, make_user, "ft_fin5")
    _set_setting("voucher_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": su, "displayName": su}]}]})
    vid = _draft(client, fin)
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    tiers = _appr(vid)["tiers"]
    assert len(tiers) == 1 and not tiers[0].get("system")


def test_batch_all_on_engine_drafts_stops_at_the_superadmin_slot_for_non_superadmin(client, make_user):
    _, fin = _login(client, make_user, "ft_fin6")
    _, sup = _login(client, make_user, "ft_sup6", role="superadmin")
    c = db.get_db()
    try:
        v = VP._provide_voucher_draft(c, voucher_date="2184-05-11", summary="引擎", created_by="t", now="2184-05-11T00:00:00",
                                      lines=[{"account_code": "1113", "summary": "x", "debit": 500, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 500}])
        c.execute("UPDATE vouchers_all SET kind='auto' WHERE id=?", (v["id"],))
        c.commit()
    finally:
        c.close()
    from modules.accounting.ledger import features as F
    c = db.get_db()
    F.set_flag(c, "engine_drafts", True)
    c.commit()
    c.close()
    r = client.post("/api/ledger/engine/batch", headers=fin, json={"voucher_ids": [v["id"]], "action": "all"}).json()
    assert r["results"][0]["ok"] is False and "簽核人" in r["results"][0]["error"] and _status(v["id"]) == "簽核中"
    r2 = client.post("/api/ledger/engine/batch", headers=sup, json={"voucher_ids": [v["id"]], "action": "all"}).json()
    assert r2["results"][0]["ok"] is True and _status(v["id"]) == "已過帳"


def test_helper_is_pure_about_existing_tiers_and_tolerates_no_superadmin(client, make_user):
    su, _ = _login(client, make_user, "ft_sup7", role="superadmin")
    c = db.get_db()
    try:
        existing = [{"order": 0, "approvers": [{"username": "someone", "status": "pending"}]}]
        out = with_final_superadmin_tier(c, existing)
        assert len(out) == 2 and out[0] is existing[0] and existing == [{"order": 0, "approvers": [{"username": "someone", "status": "pending"}]}]      # 不改傳入的清單
        c.execute("UPDATE users SET active=0 WHERE role='superadmin'")
        assert with_final_superadmin_tier(c, existing) == existing                                                                                   # 沒有在職最高管理者 ⇒ 不補（不卡死）
        c.rollback()
    finally:
        c.close()
