"""「待我簽核」佇列在 L1（主持裁示 2026-09-27，c-approval-l1）：M01 只是 `approval.queue_items` 的提供者之一。

① M01 不在 ⇒ 佇列、角標、詳情照常：其他模組的單照列；案件抬頭只有單號、客戶名稱是空字串（沒有 case.summary）
② M01 不在 ⇒ 詳情的每案守門 fail-closed：不是本單簽核人 ⇒ 404（c-case404 規則照舊）；本單簽核人照看
③ 其他模組的提供者拿掉（M06 傳票，`voucher`）⇒ 佇列 200、別的單照列
④ 佇列頁歸 L1：M01 不在也開得到
⑤ 詳情的「查無」與「看不到」同一句 404、不帶關聯案件單號；audit 記真正原因（稽核 D AL-S1）
⑥ 佇列列出 ⇔ 詳情守門放行（主持裁示 2026-09-27，AL-O3）：M01 不在 ⇒ 掛在案件上的單只列給簽核鏈上的人與送審人；
   逐格比對「有列 ⇔ 詳情不是 404」

「M01 不在」以 registry 拿掉 `modules.case` 的所有提供者模擬（載入器不登記＝同一個結果）；本檔在 tests/platform，
core-only／真刪 M01 的反向控制也跑它（那時 M01 真的不在）。不 import M01。
"""
import json

import pytest

from core import registry

DOC = "AQL1-X-1"
QN = "MQ-AQL1-1"
DOC_UNLINKED = "AQL1-X-2"      # 沒掛案件（quote_no 空；例：不掛案件的請款單）——稽核 D AL2-M1
DOC_ORPHAN = "AQL1-X-3"        # 孤兒單：掛的案件已不存在（稽核 D 建議、主持採納）
QN_GONE = "MQ-AQL1-GONE"
_LINK = {DOC: QN, DOC_UNLINKED: "", DOC_ORPHAN: QN_GONE}


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _appr(approver):
    return {"requestedBy": "aql1_sales", "requestedByDisplay": "業務", "requestedAt": "2026-09-27T09:00:00",
            "currentTier": 0, "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}


def _fake_item(approver, doc=DOC):
    from helpers.approval_queue import base_item, tier_fields
    return base_item("aql1_doc", doc, tier_fields(json.dumps(_appr(approver))), linkedQuoteNo=_LINK[doc], total=5)


def _fake_detail(approver):
    def detail(conn, doc_no):
        if doc_no not in _LINK:
            return None
        return {"quoteNo": _LINK[doc_no], "approvalRaw": json.dumps({"approval": _appr(approver)}), "title": "測試單 " + DOC,
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
            got["aql1_doc"] = lambda conn: [_fake_item(approver), _fake_item(approver, DOC_UNLINKED),
                                            _fake_item(approver, DOC_ORPHAN)]
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
    got = _items(client, ah)                                   # 簽核人照列（superadmin 見 ⑥）
    assert DOC in got, sorted(got)
    assert got[DOC]["customer"] == "" and got[DOC]["projectName"] == ""       # 沒有 case.summary ⇒ 空字串，不是例外
    assert not [n for n, it in got.items() if it["type"] in ("quotation", "case_change", "completion_note",
                                                              "extra_expense", "extra_expense_change")]
    assert client.get("/api/approval-queue/count", headers=ah).json()["count"] == 3      # 掛案件、沒掛案件、孤兒各一張，都輪到他


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
    sh, ah, _oh = users
    _patch(monkeypatch, "aql1_appr", drop_case=False, drop_names=("voucher",))
    assert "voucher" not in registry.providers("approval.queue_items")
    assert DOC in _items(client, ah)
    assert "voucher" not in client.get("/api/approval-queue", headers=sh).json()["reassignTypes"]


def test_a_failing_provider_only_drops_its_own_items(client, users, monkeypatch):
    _sh, _ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    orig = registry.providers

    def boom(conn):
        raise RuntimeError("壞掉的提供者")

    monkeypatch.setattr(registry, "providers",
                        lambda cap: {**orig(cap), "aql1_boom": boom} if cap == "approval.queue_items" else orig(cap))
    assert DOC in _items(client, _ah)


def test_queue_page_is_l1(client, users, monkeypatch):
    sh, _ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    r = client.get("/pages/approval-queue.html")
    assert r.status_code == 200, r.status_code
    assert "/api/approval-queue" in r.text          # 是那一頁本身，不是回首頁或錯誤頁


# ── ⑤ 查無與看不到同一句（AL-S1）────────────────────────────────────────────

def _detail_denials(doc_id, n=1, timeout=5.0):
    """audit 在背景執行緒寫 ⇒ 等它落地。"""
    import time
    import db
    from routers.approval_queue import DETAIL_DENIAL_AUDIT
    end = time.time() + timeout
    while True:
        conn = db.get_db()
        try:
            got = [json.loads(r["detail"])["reason"] for r in conn.execute(
                "SELECT detail FROM audit_log WHERE action=? AND target_id=? ORDER BY id", (DETAIL_DENIAL_AUDIT, doc_id))]
        finally:
            conn.close()
        if len(got) >= n or time.time() > end:
            return got
        time.sleep(0.05)


def test_detail_not_found_and_denied_look_the_same(client, users, monkeypatch):
    from routers.approval_queue import detail_not_found_message
    _sh, _ah, oh = users
    _patch(monkeypatch, "aql1_appr")
    missing = client.get("/api/approval-queue/detail", params={"type": "aql1_doc", "id": "AQL1-NOPE"}, headers=oh)
    denied = client.get("/api/approval-queue/detail", params={"type": "aql1_doc", "id": DOC}, headers=oh)
    assert (missing.status_code, denied.status_code) == (404, 404), (missing.text, denied.text)
    assert missing.json() == {"detail": detail_not_found_message("AQL1-NOPE")}
    assert denied.json() == {"detail": detail_not_found_message(DOC)}      # 與查無同一句，只差被查的單號本身
    assert QN not in denied.text                                           # 不洩漏這張單掛在哪一案
    assert _detail_denials("AQL1-NOPE") == ["not_found"] and _detail_denials(DOC) == ["denied"]


def test_provider_own_404_message_is_replaced(client, users, monkeypatch):
    """提供者自己丟的 404（例：M01「完工單不存在」）也換成同一句。"""
    from fastapi import HTTPException
    from routers.approval_queue import detail_not_found_message
    _sh, ah, _oh = users
    _patch(monkeypatch, "aql1_appr")
    orig = registry.providers

    def raising(conn, doc_no):
        raise HTTPException(404, "某某單不存在")
    monkeypatch.setattr(registry, "providers",
                        lambda cap: {**orig(cap), "aql1_raise": raising} if cap == "approval.detail" else orig(cap))
    r = client.get("/api/approval-queue/detail", params={"type": "aql1_raise", "id": "X-1"}, headers=ah)
    assert r.status_code == 404 and r.json() == {"detail": detail_not_found_message("X-1")}, r.text


# ── ⑥ 佇列列出 ⇔ 詳情放行（AL-O3）─────────────────────────────────────────────

def test_case_absent_superadmin_off_chain_is_not_listed(client, users, monkeypatch):
    sh, ah, oh = users
    _patch(monkeypatch, "aql1_appr")
    assert DOC not in _items(client, sh) and DOC not in _items(client, oh)
    assert DOC in _items(client, ah)
    assert client.get("/api/approval-queue/count", headers=sh).json()["count"] == 0   # 列不出來的不算進角標


def _seed_case_row():
    """M01 在時，詳情守門要有真的案件列（admin+ 經 row_access 放行）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)", (QN, "成交", "客", "案", "{}", "2026-09-27", "2026-09-27"))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("case_present", [False, True])
def test_listed_iff_detail_opens(client, users, monkeypatch, case_present):
    """同一組身分 × 同一張單：佇列有列 ⇔ 詳情不是 404（逐格）。M01 在的那一格要 M01 真的在。"""
    from core import source_tree
    if case_present and not source_tree.module_installed("modules/case/"):
        pytest.skip("M01 不在這個安裝包：只驗 M01 不在的那一格")
    if case_present:
        _seed_case_row()
    sh, ah, oh = users
    _patch(monkeypatch, "aql1_appr", drop_case=not case_present)
    grid = {}
    for doc in (DOC, DOC_UNLINKED, DOC_ORPHAN):
        for name, h in (("super", sh), ("approver", ah), ("other_admin", oh)):
            listed = doc in _items(client, h)
            code = client.get("/api/approval-queue/detail", params={"type": "aql1_doc", "id": doc}, headers=h).status_code
            grid[(doc, name)] = (listed, code)
            assert listed == (code != 404), grid
    linked = ({"super": True, "approver": True, "other_admin": True} if case_present
              else {"super": False, "approver": True, "other_admin": False})
    # 沒掛案件的單：每案守門一律查無 ⇒ 只列給簽核鏈上的人（M01 在不在都一樣；AL2-M1）
    unlinked = {"super": False, "approver": True, "other_admin": False}
    assert {k[1]: v[0] for k, v in grid.items() if k[0] == DOC} == linked, grid
    assert {k[1]: v[0] for k, v in grid.items() if k[0] == DOC_UNLINKED} == unlinked, grid
    # 孤兒單（掛的案件已不存在）：每案守門查無 ⇒ 同沒掛案件（M01 在時也一樣；§G5 #13）
    assert {k[1]: v[0] for k, v in grid.items() if k[0] == DOC_ORPHAN} == unlinked, grid
