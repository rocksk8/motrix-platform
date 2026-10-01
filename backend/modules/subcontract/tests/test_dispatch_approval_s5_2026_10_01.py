# -*- coding: utf-8 -*-
"""31-A S5：簽核佇列（兩種 type）、詳情、轉簽、信件類型。"""
import json

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _login, _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s4_2026_10_01 import _acc  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _queue(c, h, who):
    r = c.get("/api/approval-queue", headers=h[who])
    assert r.status_code == 200, r.text
    return [it for g in r.json()["queue"] for it in g["items"] if it["type"].startswith("contractor_dispatch")]


def test_pending_stage1_in_queue_with_contract_fields(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    c.post("/api/contractor-dispatches/%d/submit" % did, json={}, headers=h["da_a"])
    its = _queue(c, h, "da_u1")
    assert len(its) == 1
    it = its[0]
    code = _row(did)["doc_code"]
    assert it["type"] == "contractor_dispatch" and it["typeLabel"] == "承攬商派發" and it["quoteNo"] == code and it["docCode"] == code
    assert it["approveUrl"] == "/api/contractor-dispatches/%d/approve" % did and it["rejectUrl"].endswith("/reject")
    assert it["rejectField"] == "reason" and it["openUrl"].startswith("case-management.html?q=MQ-DA-1")
    assert it["linkedQuoteNo"] == "MQ-DA-1" and it["total"] == 1000 * 1.05 + 100
    assert [a["username"] for a in it["currentApprovers"]] == ["da_u1"]


def test_stage2_item_separate_type_and_urls(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h["da_a"])
    its = _queue(c, h, "da_u1")
    assert [i["type"] for i in its] == ["contractor_dispatch_completion"]
    assert its[0]["typeLabel"] == "承攬商派發完工" and its[0]["approveUrl"].endswith("/completion/approve")


def test_not_listed_when_draft_returned_approved_or_legacy(S):
    c, h = S
    _tiers(["da_u1"])
    for ap in (F.DRAFT, F.RETURNED, F.APPROVED, ""):
        _mk(approval=ap)
    _mk(status="accepted", approval=F.APPROVED, completion=F.RETURNED)
    assert _queue(c, h, "da_sa") == []


def test_malformed_approval_json_skips_only_that_row(S):
    c, h = S
    _tiers(["da_u1"])
    bad, good = _mk(approval=F.PENDING), _mk(approval=F.PENDING)
    cn = db.get_db()
    cn.execute("UPDATE contractor_dispatches SET approval_json='{oops' WHERE id=?", (bad,))
    cn.execute("UPDATE contractor_dispatches SET approval_json=? WHERE id=?",
               (json.dumps({"requestedBy": "da_a", "requestedByDisplay": "a", "requestedAt": "2026-10-01T10:00:00", "tiers": [], "currentTier": 0}), good))
    cn.commit()
    cn.close()
    assert [i["quoteNo"] for i in _queue(c, h, "da_sa")] == [_row(good)["doc_code"]]


def test_detail_by_doc_code_for_both_types(S):
    c, h = S
    _tiers(["da_u1"])
    d1 = _mk()
    c.post("/api/contractor-dispatches/%d/submit" % d1, json={}, headers=h["da_a"])
    code = _row(d1)["doc_code"]
    r = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch", "id": code}, headers=h["da_u1"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["case"]["quoteNo"] == "MQ-DA-1" and any(f["label"] == "派發單號" and f["value"] == code for f in j["fields"])
    assert not any("銀行" in f["label"] or "帳" in f["label"] for f in j["fields"])
    d2 = _acc()
    c.post("/api/contractor-dispatches/%d/completion/request" % d2, json={}, headers=h["da_a"])
    code2 = _row(d2)["doc_code"]
    r = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch_completion", "id": code2}, headers=h["da_u1"])
    assert r.status_code == 200 and any(f["label"] == "驗收人" for f in r.json()["fields"])
    r = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch", "id": "DP-NOPE"}, headers=h["da_u1"])
    assert r.status_code == 404


def test_reassign_rewrites_current_approver_of_the_right_stage(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h["da_a"])
    code = _row(did)["doc_code"]
    r = c.post("/api/approval-queue/reassign", headers=h["da_sa"],
               json={"type": "contractor_dispatch_completion", "id": code, "to_username": "da_u2", "reason": "出差"})
    assert r.status_code == 200, r.text
    comp = json.loads(_row(did)["completion_approval_json"])
    assert comp["tiers"][0]["approvers"][0]["username"] == "da_u2"
    assert json.loads(_row(did)["approval_json"]).get("tiers") in (None, [])            # 第一段不動
    assert c.post("/api/contractor-dispatches/%d/completion/approve" % did, json={}, headers=h["da_u2"]).status_code == 200
    assert _row(did)["status"] == "completed"


def test_reassign_unreadable_json_fails_closed(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk(approval=F.PENDING)
    cn = db.get_db()
    cn.execute("UPDATE contractor_dispatches SET approval_json='{oops' WHERE id=?", (did,))
    cn.commit()
    cn.close()
    r = c.post("/api/approval-queue/reassign", headers=h["da_sa"],
               json={"type": "contractor_dispatch", "id": _row(did)["doc_code"], "to_username": "da_u2", "reason": "x"})
    assert r.status_code >= 400 and _row(did)["approval_json"] == "{oops"


def test_providers_registered_for_both_types():
    from core import registry
    assert {"contractor_dispatch", "contractor_dispatch_completion"} <= set(registry.providers("approval.reassign"))
    assert {"contractor_dispatch", "contractor_dispatch_completion"} <= set(registry.providers("approval.detail"))


# ── 信件 ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mails(monkeypatch):
    from helpers import email_notify as en
    sent = []
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: sent.append((key, kw)) or True)
    return sent


def test_eight_mail_types_registered_with_owner():
    from helpers import mail_types as mt
    keys = ["dispatch_submitted", "dispatch_next_tier", "dispatch_approved", "dispatch_returned",
            "dispatch_completion_submitted", "dispatch_completion_next_tier", "dispatch_completion_approved",
            "dispatch_completion_returned"]
    for k in keys:
        assert mt.get(k) is not None and mt.get(k).owner == "subcontract", k


def test_stage1_mail_sequence_and_no_amount(S, mails):
    c, h = S
    _tiers(["da_u1"], ["da_u2"])
    did = _mk()
    c.post("/api/contractor-dispatches/%d/submit" % did, json={}, headers=h["da_a"])
    c.post("/api/contractor-dispatches/%d/approve" % did, json={}, headers=h["da_u1"])
    c.post("/api/contractor-dispatches/%d/approve" % did, json={}, headers=h["da_u2"])
    c.post("/api/contractor-dispatches/%d/reject" % did, json={"reason": "x"}, headers=h["da_u2"])        # 已核准：不在簽核中 → 409，不寄
    assert [k for k, _ in mails] == ["dispatch_submitted", "dispatch_next_tier", "dispatch_approved"]
    assert mails[0][1]["usernames"] == ["da_u1"] and mails[1][1]["usernames"] == ["da_u2"] and mails[2][1]["usernames"] == ["da_a"]
    blob = json.dumps([kw.get("rows") for _, kw in mails] + [kw.get("note") for _, kw in mails], ensure_ascii=False)
    assert "1050" not in blob and "1,050" not in blob and "NT$" not in blob


def test_stage2_mail_keys_and_returned_carries_reason(S, mails):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h["da_a"])
    c.post("/api/contractor-dispatches/%d/completion/reject" % did, json={"reason": "缺照片"}, headers=h["da_u1"])
    c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h["da_a"])
    c.post("/api/contractor-dispatches/%d/completion/approve" % did, json={}, headers=h["da_u1"])
    assert [k for k, _ in mails] == ["dispatch_completion_submitted", "dispatch_completion_returned",
                                      "dispatch_completion_submitted", "dispatch_completion_approved"]
    assert ("退回原因", "缺照片") in mails[1][1]["rows"]


def test_auto_approve_mails_requester_and_mail_failure_never_breaks_approval(S, monkeypatch):
    c, h = S
    from helpers import email_notify as en, _set_setting
    sent = []
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: sent.append(key) or True)
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    c.post("/api/contractor-dispatches/%d/submit" % _mk(), json={}, headers=h["da_a"])
    assert sent == ["dispatch_approved"]

    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(en, "send_registered", boom)
    _tiers(["da_u1"])
    did = _mk()
    assert c.post("/api/contractor-dispatches/%d/submit" % did, json={}, headers=h["da_a"]).status_code == 200
    assert c.post("/api/contractor-dispatches/%d/approve" % did, json={}, headers=h["da_u1"]).status_code == 200
    assert _row(did)["approval_status"] == F.APPROVED
