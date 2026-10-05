"""A2-0 底層預留 #2：簽核佇列項目契約（新單據類型不必再改 L1 佇列與前端的 type 分支）。
項目可帶 `typeLabel`（標籤）、`openUrl`／`approveUrl`／`rejectUrl`／`rejectField`（前端端點；前端只讀、本檔守後端面）、
`caseless: True`（不掛案件：沒有案件可查 ⇒ 簽核鏈上的人與送審人＋超級管理員可開，其餘 404；項目與詳情同一個判斷）。
內建 type 的標籤不被覆寫；沒給標籤的未知 type 仍退回舊預設「報價單」。
反向控制：`_access_step` 拿掉 caseless 分支 ⇒ 「超級管理員開得了無案件單」必須紅。"""
import json

import pytest

from core import registry
from routers import approval_queue as aq

DOC = "CL-X-1"


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _appr(approver):
    return {"requestedBy": "cl_sales", "requestedByDisplay": "業務", "requestedAt": "2026-10-01T09:00:00",
            "currentTier": 0, "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}


def _patch(monkeypatch, approver):
    from helpers.approval_queue import base_item, tier_fields
    orig = registry.providers

    def item(conn):
        return [base_item("cl_doc", DOC, tier_fields(json.dumps(_appr(approver))), linkedQuoteNo="", caseless=True,
                          typeLabel="請購單", openUrl="expense-form.html?id=1", approveUrl="/api/x/1/approve",
                          rejectUrl="/api/x/1/reject", rejectField="reason", total=5)]

    def detail(conn, doc_no):
        return {"quoteNo": "", "caseless": True, "approvalRaw": json.dumps({"approval": _appr(approver)}),
                "title": "無案件單", "fields": [], "items": [], "files": []} if doc_no == DOC else None

    def fake(cap):
        got = dict(orig(cap))
        if cap == "approval.queue_items":
            got["cl_doc"] = item
        elif cap == "approval.detail":
            got["cl_doc"] = detail
        return got
    monkeypatch.setattr(registry, "providers", fake)


@pytest.fixture
def users(client, make_user):
    su, sp = make_user("cl_super", "Conn-Pass-123", role="superadmin")[:2]
    au, ap = make_user("cl_appr", "Conn-Pass-123", role="admin")[:2]
    ou, op = make_user("cl_other", "Conn-Pass-123", role="admin")[:2]
    return _login(client, su, sp), _login(client, au, ap), _login(client, ou, op)


def _items(client, h):
    r = client.get("/api/approval-queue", headers=h)
    assert r.status_code == 200, r.text
    return {it["quoteNo"]: it for g in r.json()["queue"] for it in g["items"]}


def test_item_type_label_rules():
    assert aq._item_type_label({"type": "extra_expense", "typeLabel": "別的"}) == "案件支出申請"      # 內建不被覆寫
    assert aq._item_type_label({"type": "cl_doc", "typeLabel": "請購單"}) == "請購單"
    assert aq._item_type_label({"type": "cl_doc"}) == "報價單"                                       # 舊預設不變
    assert aq._item_type_label({"type": "custom_record", "moduleName": "模組"}) == "模組"


def test_caseless_item_passthrough_and_visibility(client, users, monkeypatch):
    sh, ah, oh = users
    _patch(monkeypatch, "cl_appr")
    got = _items(client, ah)                                   # 簽核人列得到、契約欄位原樣帶出
    assert DOC in got
    it = got[DOC]
    assert (it["typeLabel"], it["openUrl"], it["approveUrl"], it["rejectUrl"], it["rejectField"]) ==         ("請購單", "expense-form.html?id=1", "/api/x/1/approve", "/api/x/1/reject", "reason")
    assert DOC in _items(client, sh)                           # 超級管理員列得到
    assert DOC not in _items(client, oh)                       # 不相干的 admin 列不到
    cnt = client.get("/api/approval-queue/count", headers=ah).json()
    assert cnt["count"] == 1 and cnt["items"][0]["typeLabel"] == "請購單"


def test_caseless_detail_same_decision_as_queue(client, users, monkeypatch):
    sh, ah, oh = users
    _patch(monkeypatch, "cl_appr")
    q = {"type": "cl_doc", "id": DOC}
    assert client.get("/api/approval-queue/detail", params=q, headers=ah).status_code == 200      # 簽核人
    assert client.get("/api/approval-queue/detail", params=q, headers=sh).status_code == 200      # superadmin（無案件也放行）
    assert client.get("/api/approval-queue/detail", params=q, headers=oh).status_code == 404      # 列不到 ⇔ 404


def test_non_caseless_orphan_behaviour_unchanged(client, users, monkeypatch):
    """沒宣告 caseless 的無案件單（舊行為）：超級管理員不因此被放行——契約是 opt-in。"""
    assert aq._access_step(None, {"role": "superadmin", "username": "x"}, "", "", True) == aq.DENY
    assert aq._access_step(None, {"role": "superadmin", "username": "x"}, "", "", True, caseless=True) == aq.OPEN
