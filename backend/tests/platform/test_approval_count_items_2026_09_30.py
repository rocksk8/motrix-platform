"""首頁「等我簽核」與簽核佇列連動（使用者 2026-09-30）：`/api/approval-queue/count` 同時給數字與清單，
數字＝角標＝清單來源；首頁不再用 `dashboard/stats` 只算報價單的版本。
"""
import json

import pytest

from core import registry


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _item(doc, approver, t="aql1_doc"):
    from helpers.approval_queue import base_item, tier_fields
    appr = {"requestedBy": "w2_sales", "requestedByDisplay": "業務", "requestedAt": "2026-09-30T09:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}
    return base_item(t, doc, tier_fields(json.dumps(appr)), linkedQuoteNo="", total=5)


def test_count_returns_the_same_items_the_badge_counts(client, make_user, monkeypatch):
    au, ap = make_user("w2_appr", "Conn-Pass-123", role="admin")[:2]
    ou, op = make_user("w2_other", "Conn-Pass-123", role="admin")[:2]
    orig = registry.providers

    def fake(cap):
        got = dict(orig(cap))
        if cap == "approval.queue_items":
            got["w2_doc"] = lambda conn: [_item("W2-1", "w2_appr", "shipping_note"), _item("W2-2", "w2_appr", "payment_request"),
                                          _item("W2-3", "w2_other", "voucher")]
        return got
    monkeypatch.setattr(registry, "providers", fake)
    r = client.get("/api/approval-queue/count", headers=_login(client, au, ap)).json()
    nos = [i["quoteNo"] for i in r["items"] if i["quoteNo"].startswith("W2-")]
    assert "W2-1" in nos and "W2-2" in nos and "W2-3" not in nos, nos     # 只列輪到我的（簽核鏈上別人的不算）
    assert r["count"] >= len(nos) and len(r["items"]) <= 10
    labels = {i["quoteNo"]: i["typeLabel"] for i in r["items"]}
    assert labels["W2-1"] == "出貨單" and labels["W2-2"] == "請款單", labels
    o = client.get("/api/approval-queue/count", headers=_login(client, ou, op)).json()
    assert "W2-3" in [i["quoteNo"] for i in o["items"]] and "W2-1" not in [i["quoteNo"] for i in o["items"]]
