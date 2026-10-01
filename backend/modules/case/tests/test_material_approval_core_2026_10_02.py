# -*- coding: utf-8 -*-
"""叫料審核（31-C S1）：疊加表 migration、狀態機、實質欄位雜湊、到貨確認、舊單判定。

不經 HTTP（端點是 S2）；直接呼叫 `modules/case/material_approval.py`。簽核流程用 `unified_approval_flow` 設定：
沒有簽核層 ⇒ 送審即核准；一層（指定簽核人）⇒ 待審核→核准／退回。每個「不可以」都驗狀態沒變。
"""
import json
import re

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

import db  # noqa: E402
from modules.case import material_approval as MA  # noqa: E402

NO = "MQ-MAT-001"
ENG = {"username": "mat_eng", "role": "sales", "display_name": "工程師"}
BOSS = {"username": "mat_boss", "role": "sales", "display_name": "主管"}
ADMIN = {"username": "mat_admin", "role": "admin", "display_name": "管理員"}
OTHER = {"username": "mat_other", "role": "sales", "display_name": "路人"}


def _flow(tiers):
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _one_tier():
    _flow([{"order": 0, "approvers": [{"username": BOSS["username"], "displayName": "主管"}]}])


@pytest.fixture
def conn(client):
    c = db.get_db()
    yield c
    c.rollback()
    c.close()


def _order(item="it-1", **kw):
    o = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1500, "totalPrice": 3000,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    o.update(kw)
    return o


def test_migration_is_idempotent_and_legacy_means_no_row(conn):
    from importlib import import_module
    m4 = import_module("modules.case.migrations.0004_material_approvals")
    m4.up(conn)
    m4.up(conn)                                                                   # 再跑一次不報錯
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_material_approvals)")}
    assert {"quote_no", "item_id", "doc_code", "status", "approval_json", "content_hash", "received_on", "received_by", "received_at",
            "cancel_reason", "version"} <= cols
    assert MA.get(conn, NO, "nope") is None and MA.status_of(conn, NO, "nope") == ""        # 沒有疊加列＝舊單
    assert MA.counts_as_approved("") and MA.counts_as_approved(MA.S_APPROVED) and not MA.counts_as_approved(MA.S_DRAFT)


def test_content_hash_normalizes_numbers_and_ignores_non_substantive_fields():
    a = _order()
    b = _order(quantity=2.0, unitPrice=1500.0, totalPrice=3000.0, itemName=" 交換器 ", notes="備註改了", paidStatus="paid", invoiceDate="2031-01-01")
    assert MA.content_hash(a) == MA.content_hash(b)                                # 30000 vs 30000.0、空白、非實質欄位不影響
    for k, v in (("itemName", "路由器"), ("quantity", 3), ("unit", "個"), ("unitPrice", 1600), ("totalPrice", 3001), ("supplierId", 7)):
        assert MA.content_hash(_order(**{k: v})) != MA.content_hash(a), k           # 每個實質欄位都算


def test_cost_state_table():
    assert [MA.cost_state(s) for s in ("", MA.S_APPROVED)] == ["counted", "counted"]
    assert [MA.cost_state(s) for s in (MA.S_PENDING, MA.S_IN_PROGRESS)] == ["pending", "pending"]
    assert [MA.cost_state(s) for s in (MA.S_DRAFT, MA.S_RETURNED, MA.S_CANCELLED)] == ["excluded"] * 3


def test_draft_gets_a_document_code_and_codes_are_unique(conn):
    d1 = MA.create_draft(conn, NO, "it-1", ENG)
    d2 = MA.create_draft(conn, NO, "it-2", ENG)
    assert re.fullmatch(r"MO-\d{8}-\d{4}", d1["doc_code"]) and d1["doc_code"] != d2["doc_code"]
    assert (d1["doc_code"][-4:], d2["doc_code"][-4:]) == ("0001", "0002") and d1["doc_code"][:-4] == d2["doc_code"][:-4]       # 同一天依序
    assert d1["status"] == MA.S_DRAFT and MA.create_draft(conn, NO, "it-1", ENG)["doc_code"] == d1["doc_code"]       # 重複建立回既有


def test_no_tiers_submit_is_auto_approved_and_stores_the_hash(conn):
    _flow([])
    MA.create_draft(conn, NO, "it-1", ENG)
    r = MA.submit(conn, NO, _order(), ENG)
    assert r["status"] == MA.S_APPROVED and r["autoApproved"] is True
    row = MA.get(conn, NO, "it-1")
    assert row["status"] == MA.S_APPROVED and row["content_hash"] == MA.content_hash(_order()) and row["approved_at"]
    assert json.loads(row["approval_json"])["autoApproved"] is True


def test_one_tier_flow_submit_approve_with_permission_and_history(conn):
    _one_tier()
    MA.create_draft(conn, NO, "it-1", ENG)
    r = MA.submit(conn, NO, _order(), ENG)
    assert r["status"] == MA.S_PENDING and r["firstApprovers"] == [BOSS["username"]] and r["tierCount"] == 1
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.approve(conn, NO, _order(), OTHER)                                        # 不是當層簽核人
    assert e.value.status == 403 and MA.status_of(conn, NO, "it-1") == MA.S_PENDING     # 狀態沒變
    with pytest.raises(MA.MaterialApprovalError) as e2:
        MA.submit(conn, NO, _order(), ENG)                                           # 待審核不可再送
    assert e2.value.status == 409
    r = MA.approve(conn, NO, _order(), BOSS)
    assert r["status"] == MA.S_APPROVED and r["done"] is True and r["requester"] == ENG["username"]
    row = MA.get(conn, NO, "it-1")
    assert row["content_hash"] == MA.content_hash(_order()) and row["approved_at"]
    hist = [h["action"] for h in json.loads(row["approval_json"])["history"]]
    assert hist == ["create", "submit", "approve"]


def test_reject_needs_a_reason_then_resubmit(conn):
    _one_tier()
    MA.create_draft(conn, NO, "it-1", ENG)
    MA.submit(conn, NO, _order(), ENG)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.reject(conn, NO, "it-1", OTHER, "不行")                                   # 非簽核人
    assert e.value.status == 403
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.reject(conn, NO, "it-1", BOSS, "  ")                                      # 原因必填
    assert e.value.status == 400 and MA.status_of(conn, NO, "it-1") == MA.S_PENDING
    r = MA.reject(conn, NO, "it-1", BOSS, "單價太高")
    assert r["status"] == MA.S_RETURNED and MA.status_of(conn, NO, "it-1") == MA.S_RETURNED
    assert json.loads(MA.get(conn, NO, "it-1")["approval_json"])["rejectReason"] == "單價太高"
    assert MA.submit(conn, NO, _order(unitPrice=1400, totalPrice=2800), ENG)["status"] == MA.S_PENDING       # 修改後可重送


def test_withdraw_only_by_requester_or_admin(conn):
    _one_tier()
    MA.create_draft(conn, NO, "it-1", ENG)
    MA.submit(conn, NO, _order(), ENG)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.withdraw(conn, NO, "it-1", OTHER)
    assert e.value.status == 403 and MA.status_of(conn, NO, "it-1") == MA.S_PENDING
    assert MA.withdraw(conn, NO, "it-1", ENG)["status"] == MA.S_DRAFT
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.withdraw(conn, NO, "it-1", ENG)                                           # 草稿不可撤回
    assert e.value.status == 409


def test_substantive_change_matrix(conn):
    _flow([])
    # 舊單（沒有疊加列）被實質編輯 ⇒ 建草稿（要先送審）
    r = MA.on_substantive_change(conn, NO, "legacy-1", ENG)
    assert r == {"allowed": True, "status": MA.S_DRAFT, "reason": "legacy_to_draft"} and MA.status_of(conn, NO, "legacy-1") == MA.S_DRAFT
    # 草稿可編輯；待審核不可（請先撤回）
    assert MA.on_substantive_change(conn, NO, "legacy-1", ENG)["allowed"] is True
    conn.commit()                                                                   # 設定寫入用另一條連線：先放掉本連線的寫鎖
    _one_tier()
    MA.create_draft(conn, NO, "it-1", ENG)
    MA.submit(conn, NO, _order(), ENG)
    r = MA.on_substantive_change(conn, NO, "it-1", ENG)
    assert r["allowed"] is False and r["reason"] == "in_approval" and MA.status_of(conn, NO, "it-1") == MA.S_PENDING
    # 已核准 ⇒ 回草稿、版本 +1、雜湊清掉
    MA.approve(conn, NO, _order(), BOSS)
    before = MA.get(conn, NO, "it-1")
    r = MA.on_substantive_change(conn, NO, "it-1", ENG)
    after = MA.get(conn, NO, "it-1")
    assert r["allowed"] is True and r["reason"] == "approved_to_draft"
    assert after["status"] == MA.S_DRAFT and after["version"] == before["version"] + 1 and after["content_hash"] == "" and after["approved_at"] == ""
    assert json.loads(after["approval_json"])["history"][-1]["action"] == "edit_after_approval"
    # 已取消 ⇒ 不可
    conn.commit()
    _flow([])
    MA.create_draft(conn, NO, "it-9", ENG)
    MA.submit(conn, NO, _order("it-9"), ENG)
    MA.cancel(conn, NO, "it-9", ADMIN, "不要了")
    r = MA.on_substantive_change(conn, NO, "it-9", ENG)
    assert r["allowed"] is False and r["reason"] == "cancelled"


def test_cancel_needs_admin_a_reason_and_an_approved_order(conn):
    _flow([])
    MA.create_draft(conn, NO, "it-1", ENG)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.cancel(conn, NO, "it-1", ADMIN, "x")                                      # 草稿不可取消（沒核准過）
    assert e.value.status == 409
    MA.submit(conn, NO, _order(), ENG)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.cancel(conn, NO, "it-1", ENG, "我想取消")                                 # 非 admin
    assert e.value.status == 403
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.cancel(conn, NO, "it-1", ADMIN, " ")                                      # 沒理由
    assert e.value.status == 400 and MA.status_of(conn, NO, "it-1") == MA.S_APPROVED
    assert MA.cancel(conn, NO, "it-1", ADMIN, "廠商缺貨")["status"] == MA.S_CANCELLED
    row = MA.get(conn, NO, "it-1")
    assert row["cancel_reason"] == "廠商缺貨" and row["cancelled_by"] == ADMIN["username"]


def test_receipt_records_date_and_who_only_for_approved_orders(conn):
    _flow([])
    MA.create_draft(conn, NO, "it-1", ENG)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.record_receipt(conn, NO, "it-1", "2031-03-05", ENG)                       # 草稿不可確認到貨
    assert e.value.status == 409
    MA.submit(conn, NO, _order(), ENG)
    for bad in ("", None, "2031-13-40", "三月五日"):
        with pytest.raises(MA.MaterialApprovalError) as e:
            MA.record_receipt(conn, NO, "it-1", bad, ENG)
        assert e.value.status == 400, bad
        assert MA.get(conn, NO, "it-1")["received_on"] == ""                          # 失敗不留痕
    r = MA.record_receipt(conn, NO, "it-1", "2031-03-05", ENG)                       # 同一人（送審人）可以確認
    row = MA.get(conn, NO, "it-1")
    assert (row["received_on"], row["received_by"]) == ("2031-03-05", ENG["username"]) and row["received_at"] and r["receivedOn"] == "2031-03-05"
    assert MA.undo_receipt(conn, NO, "it-1", OTHER)["undone"] is True and MA.get(conn, NO, "it-1")["received_on"] == ""
    with pytest.raises(MA.MaterialApprovalError):
        MA.undo_receipt(conn, NO, "it-1", OTHER)                                      # 沒有可撤銷的


def test_doc_type_is_registered_and_follows_the_unified_flow():
    from helpers import tiered_approval as TA
    assert MA.DOC_TYPE in TA.APPROVAL_DOC_TYPES and TA.APPROVAL_DOC_TYPE_LABELS[MA.DOC_TYPE] == "叫料"
    assert MA.DOC_TYPE in TA.DEFAULT_UNIFIED_DOC_TYPES
