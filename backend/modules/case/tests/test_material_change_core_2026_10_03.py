# -*- coding: utf-8 -*-
"""33-M2a：材料申請變更申請（覆核表 migration 0006、狀態機、驗證、原子套用）。不經 HTTP（端點是 M2b）；直接呼叫 `modules/case/material_change.py`。
每個「不可以」都驗原材料申請與審核列完全沒變（N3：核准前原版本照常有效）。"""
import json

import pytest

import db
from helpers import tiered_approval as TA
from modules.case import material_approval as MA
from modules.case import material_change as MC
from modules.case import material_payment as MP
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401

ENG = {"username": "mc_eng", "role": "sales", "display_name": "工程師"}
BOSS = {"username": "mc_boss", "role": "sales", "display_name": "主管"}
ADMIN = {"username": "mc_admin", "role": "admin", "display_name": "管理員"}
OTHER = {"username": "mc_other", "role": "sales", "display_name": "路人"}
LINE1 = {"poDocCode": "PO-1", "line": 1, "qty": 2.0, "unit": "台", "amount": 2000.0}
LINE2 = {"poDocCode": "PO-2", "line": 1, "qty": 1.0, "unit": "台", "amount": 1000.0}
IID = "m1"


@pytest.fixture
def reg(monkeypatch):
    """登記 material_change 單據類型（M2a 本身不登記）；測完還原，免得污染同一行程裡別的守門題。"""
    monkeypatch.setattr(MA, "PO_REQUIRED", True)
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", None)
    monkeypatch.setattr(MC, "PROPOSAL_FN", lambda *a, **k: None)                                 # 預設：不重驗（個別題自己設）
    had = MC.DOC_TYPE in TA.APPROVAL_DOC_TYPES
    MC.ensure_registered()
    yield
    if not had:
        TA.APPROVAL_DOC_TYPES.remove(MC.DOC_TYPE)
        TA.DEFAULT_UNIFIED_DOC_TYPES.discard(MC.DOC_TYPE)
        TA.APPROVAL_DOC_TYPE_LABELS.pop(MC.DOC_TYPE, None)


@pytest.fixture
def conn(W, reg):
    c = db.get_db()
    yield c
    c.rollback()
    c.close()


def _flow(tiers):
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


def _one_tier():
    _flow([{"order": 0, "approvers": [{"username": BOSS["username"], "displayName": "主管"}]}])


def _order(**kw):
    o = {"itemId": IID, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "quoteItemId": "a", "notes": "",
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "supplierId": 1, "poDocCode": "PO-1", "poLine": 1}
    o.update(kw)
    return o


def _setup(order=None, status="已核准", created_at="2026-10-05T00:00:00", snap=(LINE1,), received="", version=1, grandfathered=False):
    o = order or _order()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["caseRecord"] = {"materialOrders": [o]}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        appr = {"snapshot": {"poSnapshot": list(snap)}, "history": []}
        if grandfathered:
            appr["grandfathered"] = True
        c.execute("DELETE FROM case_material_approvals WHERE quote_no=?", (NO,))
        c.execute("DELETE FROM case_material_changes WHERE quote_no=?", (NO,))
        c.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, approval_json, content_hash, version, created_at, received_on, received_by)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, o["itemId"], "MO-20261005-0001", status, json.dumps(appr), MA.content_hash(o), version, created_at, received,
                                                   "someone" if received else ""))
        c.commit()
    finally:
        c.close()


def _cp(**after_kw):
    before = {"quantity": 2.0, "unit": "台", "unitPrice": 1000.0, "totalPrice": 2000.0, "poSnapshot": [LINE1], "notes": ""}
    after = dict(before)
    after.update({"quantity": 3.0, "totalPrice": 3000.0, "poSnapshot": [LINE1, LINE2]})
    after.update(after_kw)
    return {"itemId": IID, "before": before, "after": after, "diff": [], "problems": []}


def _order_now(conn):
    d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    return d["caseRecord"]["materialOrders"][0]


def _frozen(conn):
    """原材料申請與審核列的完整快照（比對「什麼都沒變」）。"""
    r = conn.execute("SELECT * FROM case_material_approvals WHERE quote_no=?", (NO,)).fetchone()
    return json.dumps([_order_now(conn), dict(r)], sort_keys=True, ensure_ascii=False)


def _no_change_made(conn, before, fn, status=None, code=None):
    with pytest.raises(MC.MaterialChangeError) as e:
        fn()
    if status:
        assert e.value.status == status
    if code:
        assert e.value.code == code
    assert _frozen(conn) == before
    return e.value


# ── 表與單號 ─────────────────────────────────────────────────────────

def test_migration_is_idempotent_and_one_live_change_is_enforced_by_the_index(conn):
    from importlib import import_module
    m6 = import_module("modules.case.migrations.0006_material_changes")
    m6.up(conn)
    m6.up(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_material_changes)")}
    assert {"id", "quote_no", "item_id", "doc_code", "status", "base_version", "proposal_json", "base_json", "diff_json", "approval_json", "reason", "applied_at"} <= cols
    ins = "INSERT INTO case_material_changes (quote_no, item_id, doc_code, status) VALUES ('Q','i',?,?)"
    conn.execute(ins, ("MC-20261005-0001", "草稿"))
    with pytest.raises(Exception):                                                    # 第二個進行中的（簽核中）：索引擋底
        conn.execute(ins, ("MC-20261005-0002", "簽核中"))
    conn.execute(ins, ("MC-20261005-0003", "已撤回"))                                  # 終態不占位


def test_create_stores_base_proposal_diff_and_a_sequential_doc_code(conn):
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加一台")
    assert ch["status"] == MC.S_DRAFT and ch["doc_code"].startswith("MC-") and ch["doc_code"].endswith("0001") and ch["base_version"] == 1
    assert [d["field"] for d in json.loads(ch["diff_json"])] == ["quantity", "totalPrice", "poSnapshot"]
    assert json.loads(ch["proposal_json"])["quantity"] == 3.0 and json.loads(ch["base_json"])["quantity"] == 2.0
    assert [w for w in ch["warnings"]] and "出貨" in ch["warnings"][0]                    # 沒有出貨提供者 ⇒ 警告而非靜默


def test_create_validations_leave_the_original_untouched(conn):
    _setup()
    f = _frozen(conn)
    _no_change_made(conn, f, lambda: MC.create(conn, NO, IID, ENG, _cp(), "  "), 400, "reason_required")
    bad = _cp()
    bad["problems"] = [{"code": "no_coverage", "message": "沒有涵蓋"}]
    _no_change_made(conn, f, lambda: MC.create(conn, NO, IID, ENG, bad, "原因"), 400, "no_coverage")
    _no_change_made(conn, f, lambda: MC.create(conn, NO, IID, ENG, _cp(quantity=2.0, totalPrice=2000.0, poSnapshot=[LINE1]), "原因"), 400, "no_change")
    _no_change_made(conn, f, lambda: MC.create(conn, NO, IID, ENG, _cp(quantity=0, totalPrice=0), "原因"), 400, "bad_quantity")
    _no_change_made(conn, f, lambda: MC.create(conn, NO, IID, ENG, _cp(unitPrice=5000.0), "原因"), 400, "bad_total")
    assert conn.execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0


def test_only_approved_non_grandfathered_requests_can_have_a_change(conn):
    for kw, code in (({"status": "草稿"}, "not_approved"), ({"status": "待審核"}, "not_approved"), ({"status": "已取消"}, "not_approved"),
                     ({"grandfathered": True}, "use_direct_edit"), ({"created_at": "2026-09-20T00:00:00"}, "use_direct_edit")):
        _setup(**kw)
        _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "原因"), 409, code)
    c = db.get_db()
    c.execute("DELETE FROM case_material_approvals WHERE quote_no=?", (NO,))
    c.commit()
    c.close()
    with pytest.raises(MC.MaterialChangeError) as e:                                   # 舊單（沒有審核列）
        MC.create(conn, NO, IID, ENG, _cp(), "原因")
    assert e.value.code == "use_direct_edit" and e.value.status == 404


def test_one_live_change_per_request_and_a_withdrawn_one_frees_the_slot(conn):
    _setup()
    first = MC.create(conn, NO, IID, ENG, _cp(), "第一張")
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "第二張"), 409, "change_in_progress")
    MC.withdraw(conn, first["id"], ENG)
    assert MC.get(conn, first["id"])["status"] == MC.S_WITHDRAWN
    second = MC.create(conn, NO, IID, ENG, _cp(), "第二張")
    assert second["doc_code"] != first["doc_code"] and second["status"] == MC.S_DRAFT
    _no_change_made(conn, _frozen(conn), lambda: MC.submit(conn, first["id"], ENG), 409, "change_in_progress")        # 已撤回的舊單不能擠掉進行中的


# ── 付款／匯款／出貨 下限 ─────────────────────────────────────────────

def test_paid_in_full_blocks_amount_changes_and_below_paid_blocks_lowering(conn):
    _setup(_order(paidStatus="paid", paidAmount=2000, paidDate="2026-08-01"))
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "追加"), 400, "paid_in_full")
    _setup(_order(paidStatus="partial", paidAmount=1500, paidDate="2026-08-01"))
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(quantity=1.0, totalPrice=1000.0, poSnapshot=[LINE2]), "減少"), 400, "below_paid")
    ch = MC.create(conn, NO, IID, ENG, _cp(), "部分已付改高可以")
    assert ch["status"] == MC.S_DRAFT


def test_change_cannot_drop_below_committed_remittance_room(conn, monkeypatch):
    _setup()
    monkeypatch.setattr(MP, "room_for", lambda c, q, o, exclude_id=None: -500.0)
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "追加"), 409, "change_below_committed")


def test_shipped_lower_bound_uses_the_provider_when_present_and_fails_closed(conn, monkeypatch):
    _setup()
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", lambda c, q, i: 4.0)
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "追加"), 409, "change_below_shipped")        # 3 < 已出貨 4
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", lambda c, q, i: 3.0)
    assert MC.create(conn, NO, IID, ENG, _cp(), "剛好等於已出貨")["status"] == MC.S_DRAFT
    conn.execute("DELETE FROM case_material_changes")

    def boom(*a):
        raise RuntimeError("provider down")
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", boom)
    _no_change_made(conn, _frozen(conn), lambda: MC.create(conn, NO, IID, ENG, _cp(), "追加"), 400, "shipped_unavailable")      # 提供者壞了不放行


# ── 簽核與原子套用 ───────────────────────────────────────────────────

def test_no_tier_submit_auto_approves_and_applies_atomically(conn):
    _flow([])
    _setup(received="2026-10-04")
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    r = MC.submit(conn, ch["id"], ENG)
    assert r["status"] == MC.S_APPROVED and r["autoApproved"] and r["applied"]
    o = _order_now(conn)
    assert (o["quantity"], o["totalPrice"], o["unitPrice"]) == (3.0, 3000.0, 1000.0)                  # 內容換成新版
    row = MA.get(conn, NO, IID)
    appr = json.loads(row["approval_json"])
    assert row["version"] == 2 and row["status"] == MA.S_APPROVED and row["content_hash"] == MA.content_hash(o)
    assert appr["snapshot"]["poSnapshot"] == [LINE1, LINE2]                                           # 涵蓋快照一併換
    assert appr["history"][-1]["action"] == "changed" and ch["doc_code"] in appr["history"][-1]["comment"]
    assert (row["received_on"], row["received_by"]) == ("2026-10-04", "someone")                      # 已確認到貨的不重置
    done = MC.get(conn, ch["id"])
    assert done["status"] == MC.S_APPROVED and done["applied_at"]
    acts = {r[0] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'material_changes.%'")}
    assert {"material_changes.create", "material_changes.submit", "material_changes.apply"} <= acts


def test_original_stays_valid_while_the_change_is_pending_and_nothing_moves_on_reject_or_withdraw(conn):
    _one_tier()
    _setup()
    f = _frozen(conn)
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    assert _frozen(conn) == f                                                                          # 草稿：原版完全不動
    r = MC.submit(conn, ch["id"], ENG)
    assert r["status"] == MC.S_PENDING and r["firstApprovers"] == [BOSS["username"]] and _frozen(conn) == f      # 待審核：原版照常有效（N3）
    _no_change_made(conn, f, lambda: MC.approve(conn, ch["id"], OTHER), 403)                           # 不是當層簽核人
    with pytest.raises(MC.MaterialChangeError):
        MC.reject(conn, ch["id"], BOSS, " ")                                                           # 退回要原因
    MC.reject(conn, ch["id"], BOSS, "數量不對")
    assert MC.get(conn, ch["id"])["status"] == MC.S_RETURNED and _frozen(conn) == f
    ch2 = MC.revise(conn, ch["id"], ENG, _cp(), "改過了")                                                # 已退回 ⇒ 改後回草稿再送
    assert ch2["status"] == MC.S_DRAFT
    MC.submit(conn, ch["id"], ENG)
    MC.withdraw(conn, ch["id"], ENG)
    assert MC.get(conn, ch["id"])["status"] == MC.S_WITHDRAWN and _frozen(conn) == f
    for fn in (lambda: MC.approve(conn, ch["id"], BOSS), lambda: MC.reject(conn, ch["id"], BOSS, "x")):
        with pytest.raises(MC.MaterialChangeError) as e:
            fn()
        assert e.value.status == 409


def test_one_tier_approve_applies_in_the_same_transaction(conn):
    _one_tier()
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    MC.submit(conn, ch["id"], ENG)
    r = MC.approve(conn, ch["id"], BOSS, "同意")
    assert r["done"] and r["applied"] and r["status"] == MC.S_APPROVED
    assert _order_now(conn)["quantity"] == 3.0 and MA.get(conn, NO, IID)["version"] == 2
    assert MC.live_for(conn, NO, IID) is None                                                          # 核准後不再占位，可以再提下一張
    nxt = MC.create(conn, NO, IID, ENG, _cp(quantity=4.0, totalPrice=4000.0), "再追加")
    assert nxt["base_version"] == 2


def test_base_version_race_blocks_the_apply_and_changes_nothing(conn):
    _one_tier()
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    MC.submit(conn, ch["id"], ENG)
    conn.execute("UPDATE case_material_approvals SET version=2 WHERE quote_no=?", (NO,))               # 有人在待審期間動了原版本
    f = _frozen(conn)
    _no_change_made(conn, f, lambda: MC.approve(conn, ch["id"], BOSS), 409, "base_changed")
    assert MC.get(conn, ch["id"])["status"] == MC.S_PENDING                                           # 簽名也沒有留下
    assert json.loads(MC.get(conn, ch["id"])["approval_json"])["currentTier"] == 0


def test_original_cancelled_while_pending_blocks_the_apply(conn):
    _one_tier()
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    MC.submit(conn, ch["id"], ENG)
    conn.execute("UPDATE case_material_approvals SET status='已取消' WHERE quote_no=?", (NO,))
    _no_change_made(conn, _frozen(conn), lambda: MC.approve(conn, ch["id"], BOSS), 409, "base_changed")


def test_stale_proposal_is_rechecked_at_apply_time(conn, monkeypatch):
    _one_tier()
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    MC.submit(conn, ch["id"], ENG)
    f = _frozen(conn)
    monkeypatch.setattr(MC, "PROPOSAL_FN", lambda c, q, i, p: {"before": {}, "after": {}, "diff": [], "problems": [{"code": "coverage_shrinks", "message": "採購單行不再已核准"}]})
    _no_change_made(conn, f, lambda: MC.approve(conn, ch["id"], BOSS), 409, "proposal_stale")
    monkeypatch.setattr(MC, "PROPOSAL_FN", lambda c, q, i, p: {"before": {}, "after": _cp(poSnapshot=[LINE1, LINE2, {**LINE2, "line": 2}])["after"], "diff": [], "problems": []})
    _no_change_made(conn, f, lambda: MC.approve(conn, ch["id"], BOSS), 409, "proposal_stale")          # 目前涵蓋比提案多一行 ⇒ 過期
    seen = {}

    def ok(c, q, i, p):
        seen["p"] = p
        return {"before": {}, "after": _cp()["after"], "diff": [], "problems": []}
    monkeypatch.setattr(MC, "PROPOSAL_FN", ok)
    assert MC.approve(conn, ch["id"], BOSS)["applied"] and seen["p"] == {"quantity": 3.0, "notes": ""}       # 用儲存的數量／備註重驗


def test_apply_failure_rolls_everything_back(conn, monkeypatch):
    _flow([])
    _setup()
    conn.commit()
    f = _frozen(conn)
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    conn.commit()

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(MP, "sync_order_paid", boom)
    with pytest.raises(RuntimeError):
        MC.submit(conn, ch["id"], ENG)
    conn.rollback()                                                                                    # 呼叫端（端點）在例外時回滾整個交易
    assert _frozen(conn) == f and MC.get(conn, ch["id"])["status"] == MC.S_DRAFT


def test_apply_reprojects_paid_status_for_a_partly_paid_request(conn):
    _flow([])
    _setup(_order(paidStatus="partial", paidAmount=1000, paidDate="2026-08-01"))
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    MC.submit(conn, ch["id"], ENG)
    o = _order_now(conn)
    assert o["totalPrice"] == 3000.0 and o["paidStatus"] == "partial" and o["paidAmount"] == 1000     # 付款狀態以新小計重新投影


def test_withdraw_permissions_and_revise_rules(conn):
    _one_tier()
    _setup()
    ch = MC.create(conn, NO, IID, ENG, _cp(), "追加")
    _no_change_made(conn, _frozen(conn), lambda: MC.withdraw(conn, ch["id"], OTHER), 403)
    MC.submit(conn, ch["id"], ENG)
    with pytest.raises(MC.MaterialChangeError) as e:
        MC.revise(conn, ch["id"], ENG, _cp(), "x")                                                     # 簽核中不可改內容
    assert e.value.status == 409
    MC.withdraw(conn, ch["id"], ADMIN)                                                                  # admin 可以撤回別人的
    assert MC.get(conn, ch["id"])["status"] == MC.S_WITHDRAWN
    assert MC.revise(conn, ch["id"], ENG, _cp(quantity=4.0, totalPrice=4000.0), "改成 4")["status"] == MC.S_DRAFT      # 已撤回改完回草稿


def test_compute_diff_normalizes_numbers_and_whitespace():
    a = {"quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "notes": " 備註 ", "poSnapshot": [LINE1]}
    b = {"quantity": 2.0, "unit": "台 ", "unitPrice": 1000.0, "totalPrice": 2000.00001, "notes": "備註", "poSnapshot": [dict(LINE1, qty=2)]}
    assert MC.compute_diff(a, b) == []
    d = MC.compute_diff(a, dict(b, unitPrice=1100))
    assert d == [{"field": "unitPrice", "old": 1000.0, "new": 1100.0, "money": True}]
