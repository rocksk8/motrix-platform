"""「待我簽核」佇列在 L1（主持裁示 2026-09-27，c-approval-l1）：M01 只是 `approval.queue_items` 的提供者之一。

① M01 不在 ⇒ 佇列、角標、詳情照常：其他模組的單照列；案件抬頭只有單號、客戶名稱是空字串（沒有 case.summary）
② M01 不在 ⇒ 詳情的每案守門 fail-closed：不是本單簽核人 ⇒ 404（c-case404 規則照舊）；本單簽核人照看
③ 其他模組的提供者拿掉（M06 傳票，`voucher`）⇒ 佇列 200、別的單照列
④ 佇列頁歸 L1：M01 不在也開得到

「M01 不在」以 registry 拿掉 `modules.case` 的所有提供者模擬（載入器不登記＝同一個結果）；本檔在 tests/platform，
core-only／真刪 M01 的反向控制也跑它（那時 M01 真的不在）。不 import M01。
"""
import json

import pytest

from core import registry

DOC = "AQL1-X-1"
QN = "MQ-AQL1-1"


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _appr(approver):
    return {"requestedBy": "aql1_sales", "requestedByDisplay": "業務", "requestedAt": "2026-09-27T09:00:00",
            "currentTier": 0, "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}


def _fake_item(approver):
    from helpers.approval_queue import base_item, tier_fields
    return base_item("aql1_doc", DOC, tier_fields(json.dumps(_appr(approver))), linkedQuoteNo=QN, total=5)


def _fake_detail(approver):
    def detail(conn, doc_no):
        if doc_no != DOC:
            return None
        return {"quoteNo": QN, "approvalRaw": json.dumps({"approval": _appr(approver)}), "title": "測試單 " + DOC,
                "fields": [{"label": "金額", "value": "5"}], "items": [], "files": []}
    return detail


def _patch(monkeypatch, approver, *, drop_case=True, drop_names=()):
    """M01 不在（drop_case）＋一個測試用單據模組 `aql1_doc`；`drop_names`：另外拿掉的提供者名稱。"""
    orig = registry.providers

    def fake(cap):
        got = dict(orig(cap))
        if drop_case:
            got = {k: v for k, v in got.items()
                   if not (getattr(v, "__module__", "") or "").startswith("modules.case")}
        got = {k: v for k, v in got.items() if k not in drop_names}
        if cap == "approval.queue_items":
            got["aql1_doc"] = lambda conn: [_fake_item(approver)]
        elif cap == "approval.detail":
            got["aql1_doc"] = _fake_detail(approver)
        return got
    monkeypatch.setattr(registry, "providers", fake)


@pytest.fixture
def users(client, make_user):
    su, sp = make_user("aql1_super", "Conn-Pass-123", role="superadmin")[:2]
    au, ap = make_user("aql1_appr", "Conn-Pass-123", role="admin")[:2]
    ou, op = make_user("aql1_other", "Conn-Pass-123", role="admin")[:2]
    return _login(client, su, sp), _login(client, au, ap), _login(client, ou, op)


def _items(client, h):
    r = client.get("/api/approval-queue", headers=h)
    assert r.status_code == 200, r.text
    return {it["quoteNo"]: it for g in r.json()["queue"] for it in g["items"]}


def test_case_absent_queue_lists_other_modules(client, users, monkeypatch):
    sh, ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    assert registry.single_provider("case.summary") is None and registry.single_provider("case.access") is None
    got = _items(client, sh)
    assert DOC in got, sorted(got)
    assert got[DOC]["customer"] == "" and got[DOC]["projectName"] == ""       # 沒有 case.summary ⇒ 空字串，不是例外
    assert not [n for n, it in got.items() if it["type"] in ("quotation", "case_change", "completion_note",
                                                              "extra_expense", "extra_expense_change")]
    assert client.get("/api/approval-queue/count", headers=ah).json()["count"] == 1


def test_case_absent_detail_approver_sees_non_approver_404(client, users, monkeypatch):
    _sh, ah, oh = users
    _patch(monkeypatch, "aql1_appr")
    r = client.get("/api/approval-queue/detail", params={"type": "aql1_doc", "id": DOC}, headers=ah)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["case"] == {"quoteNo": QN, "customerName": "", "projectName": "", "dealTag": ""}
    assert d["title"] == "測試單 " + DOC and d["fields"] == [{"label": "金額", "value": "5"}]
    # 不是本單簽核人 ⇒ 走每案守門；M01 不在 ⇒ 404（admin 也一樣，case_access 的 fail-closed）
    r = client.get("/api/approval-queue/detail", params={"type": "aql1_doc", "id": DOC}, headers=oh)
    assert r.status_code == 404, r.text
    r = client.get("/api/approval-queue/detail", params={"type": "quotation", "id": QN}, headers=ah)
    assert r.status_code == 400 and "模組未安裝" in r.json()["detail"], r.text


def test_other_provider_removed_queue_still_200(client, users, monkeypatch):
    """M06 傳票的提供者（`voucher`）拿掉 ⇒ 佇列 200、別的單照列、不給傳票轉簽（M06 真刪待第十二班後補）。"""
    sh, _ah, _oh = users
    _patch(monkeypatch, "aql1_appr", drop_case=False, drop_names=("voucher",))
    assert "voucher" not in registry.providers("approval.queue_items")
    assert DOC in _items(client, sh)
    assert "voucher" not in client.get("/api/approval-queue", headers=sh).json()["reassignTypes"]


def test_a_failing_provider_only_drops_its_own_items(client, users, monkeypatch):
    sh, _ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    orig = registry.providers

    def boom(conn):
        raise RuntimeError("壞掉的提供者")

    monkeypatch.setattr(registry, "providers",
                        lambda cap: {**orig(cap), "aql1_boom": boom} if cap == "approval.queue_items" else orig(cap))
    assert DOC in _items(client, sh)


def test_queue_page_is_l1(client, users, monkeypatch):
    sh, _ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    r = client.get("/pages/approval-queue.html")
    assert r.status_code == 200, r.status_code
    assert "/api/approval-queue" in r.text          # 是那一頁本身，不是回首頁或錯誤頁
