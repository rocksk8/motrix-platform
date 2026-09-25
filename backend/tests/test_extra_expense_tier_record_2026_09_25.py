"""額外支出簽核：同一層每一位都要依序簽完才換層；每一格簽核看得出是誰簽的。

☠️ 2026-09-25（hichan-8d 實測，更正了自己先前「把同層其他人也寫 approvedAt」的錯誤描述）：
approve 只寫 approvedAt／approvedByDisplay、**從來不寫 status**，而且第一位一簽就 currentTier+1：
- 這一層已經過了，簽的人自己與同層其他人的 status 永遠是 pending（讀 status 的地方一律當成未簽）；
- check_approve_permission 只准「第一個未簽的人」⇒ 同層第二位以後永遠沒有機會簽。
使用者裁（經 hichan-0a）：**同層每一位都要依序簽完才過層**（與獎金分潤、共用規則 tiered_approval 一致）。
每位簽時寫自己的 status=approved、approvedAt、approvedBy、approvedByDisplay（代理另記 onBehalfOf）。
「同一人連任多層一次簽完」改回預設語意：往下一層只有「剩下未簽的全是他（或他代理的人）」才一起簽，
不可以替同層的別人簽。

兩條路都驗：額外支出本身（approval_json）與變更申請（change_approval_json）。
"""
import json

import pytest

from tests.test_case_extra_expenses_api_2026_09_11 import _login, _auth, _make_case, _base, _payload
from tests._delegates import delegate as _delegate

NO = "MQ-XTR-001"


def _flow(tiers):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"includeSubmitterManagerTier": False, "tiers": [
                      {"order": i, "approvers": [{"username": u, "display_name": u} for u in t]}
                      for i, t in enumerate(tiers)]}), "2026-01-01"))
        c.commit()
    finally:
        c.close()


def _row(eid):
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT status, approval_json, change_status, change_approval_json FROM case_extra_expenses"
                      " WHERE id=?", (eid,)).fetchone()
        return (r["status"], json.loads(r["approval_json"] or "{}"),
                r["change_status"], json.loads(r["change_approval_json"] or "{}"))
    finally:
        c.close()


@pytest.fixture
def toks(client, make_user):
    out = {}
    for u in ("xa", "xb", "xc", "xd", "xe"):
        n, p = make_user(username=u, role="admin")
        out[u] = _login(client, n, p)
    _make_case(NO)
    return out


def _submitted(client, toks):
    r = client.post(_base(NO), headers=_auth(toks["xe"]), json=_payload())
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    assert client.post(_base(NO) + "/%d/submit" % eid, headers=_auth(toks["xe"])).status_code == 200
    return eid


def _approve(client, tok, eid, path="approve", **body):
    return client.post(_base(NO) + "/%d/%s" % (eid, path), headers=_auth(tok), json=body)


def _by_user(tier):
    return {a["username"]: a for a in tier["approvers"]}


# ── 額外支出本身 ──────────────────────────────────────────────────────────────

def test_both_approvers_in_a_tier_must_sign_in_order(client, toks):
    _flow([["xa", "xb"], ["xc"]])
    eid = _submitted(client, toks)
    assert _approve(client, toks["xa"], eid).status_code == 200
    st, appr, _, _ = _row(eid)
    assert appr["currentTier"] == 0 and st == "簽核中", "同層第二位還沒簽，不可以換層"
    t0 = _by_user(appr["tiers"][0])
    assert t0["xa"]["status"] == "approved" and t0["xa"]["approvedAt"] and t0["xa"]["approvedBy"] == "xa"
    assert t0["xa"]["approvedByDisplay"]
    assert t0["xb"].get("status") != "approved" and not t0["xb"].get("approvedAt")
    assert _approve(client, toks["xb"], eid).status_code == 200
    st, appr, _, _ = _row(eid)
    assert appr["currentTier"] == 1
    assert _by_user(appr["tiers"][0])["xb"]["status"] == "approved"
    assert _approve(client, toks["xc"], eid).status_code == 200
    assert _row(eid)[0] == "已核准"


def test_second_approver_cannot_sign_first(client, toks):
    _flow([["xa", "xb"]])
    eid = _submitted(client, toks)
    r = _approve(client, toks["xb"], eid)
    assert r.status_code == 403, r.text
    assert _row(eid)[1]["currentTier"] == 0


def test_a_delegate_signature_records_who_signed_and_for_whom(client, toks):
    _flow([["xa", "xb"]])
    eid = _submitted(client, toks)
    _delegate("xa", "xd")
    assert _approve(client, toks["xd"], eid).status_code == 200
    t0 = _by_user(_row(eid)[1]["tiers"][0])
    assert t0["xa"]["status"] == "approved"
    assert t0["xa"]["approvedBy"] == "xd" and t0["xa"]["onBehalfOf"] == "xa"
    assert t0["xb"].get("status") != "approved"


def test_single_approver_tiers_are_unchanged(client, toks):
    _flow([["xa"], ["xc"]])
    eid = _submitted(client, toks)
    assert _approve(client, toks["xa"], eid).status_code == 200
    assert _row(eid)[1]["currentTier"] == 1
    assert _approve(client, toks["xc"], eid).status_code == 200
    assert _row(eid)[0] == "已核准"


# ── 連簽（同一人連任多層）──────────────────────────────────────────────────────

def test_cascade_does_not_sign_for_someone_else_in_the_next_tier(client, toks):
    _flow([["xa"], ["xa", "xb"]])
    eid = _submitted(client, toks)
    assert _approve(client, toks["xa"], eid, cascade=True).status_code == 200
    st, appr, _, _ = _row(eid)
    assert appr["currentTier"] == 1 and st == "簽核中", "第二層還有 xb 要簽，不可以一起蓋掉"
    t1 = _by_user(appr["tiers"][1])
    assert all(a.get("status") != "approved" for a in t1.values())


def test_cascade_signs_tiers_that_are_only_him_and_records_him(client, toks):
    _flow([["xa"], ["xa"], ["xc"]])
    eid = _submitted(client, toks)
    assert _approve(client, toks["xa"], eid, cascade=True).status_code == 200
    st, appr, _, _ = _row(eid)
    assert appr["currentTier"] == 2 and st == "簽核中"
    t1 = _by_user(appr["tiers"][1])["xa"]
    assert t1["status"] == "approved" and t1["approvedBy"] == "xa" and t1["approvedByDisplay"]
    assert t1["cascadedFrom"] == 0


# ── 變更申請（change_approval_json）───────────────────────────────────────────

def _approved_expense(client, toks):
    _flow([])
    eid = _submitted(client, toks)
    assert _row(eid)[0] == "已核准"
    return eid


def test_change_request_needs_both_approvers_too(client, toks):
    eid = _approved_expense(client, toks)
    cbase = _base(NO) + "/%d/change-request" % eid
    assert client.put(cbase, headers=_auth(toks["xe"]),
                      json=_payload(description="改過的品項", qty=3, unitCost=1500)).status_code == 200
    _flow([["xa", "xb"]])
    assert client.post(cbase + "/submit", headers=_auth(toks["xe"])).status_code == 200
    assert _approve(client, toks["xb"], eid, path="change-request/approve").status_code == 403
    assert _approve(client, toks["xa"], eid, path="change-request/approve").status_code == 200
    _, _, cs, ca = _row(eid)
    assert ca.get("currentTier", 0) == 0 and cs in ("待審核", "簽核中"), (cs, ca.get("currentTier"))
    t0 = _by_user(ca["tiers"][0])
    assert t0["xa"]["status"] == "approved" and t0["xa"]["approvedBy"] == "xa"
    assert _approve(client, toks["xb"], eid, path="change-request/approve").status_code == 200
    _, _, cs, ca = _row(eid)
    assert cs not in ("待審核", "簽核中"), "兩位都簽完 ⇒ 變更生效"
