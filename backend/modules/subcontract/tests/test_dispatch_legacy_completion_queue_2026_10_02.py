# -*- coding: utf-8 -*-
"""舊單（第 31-A 之前建立，doc_code=''）申請完工 ⇒ 完工審核**進不了簽核佇列**（正式機 2026-10-02 回報：「完工審核簽核佇列沒有顯示」）。

成因：`_queue_for` 對 `not r["doc_code"]` 直接跳過（壞資料略過），而 `dispatch_review_submit` 申請完工時只把 completion_status 改成待審核、
沒有補單號 ⇒ 該筆永遠不顯示；詳情／轉簽也以 doc_code 為鍵，點不開。正式機 11 筆派發全是舊單（7 completed、3 accepted），命中率極高。
修法：①送審當下（持寫鎖）補單號（僅 doc_code 為空者；兩段送審共用）；②「已卡住」的資料（任一段在待審核／簽核中而 doc_code=''）
由 subcontract migration 0004 冪等補單號（只補 doc_code，不動其他欄位）。
本檔：重現（修之前紅）＋流程＋修復＋反向控制。"""
import importlib
import json

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _login, _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _queue(c, h, who):
    r = c.get("/api/approval-queue", headers=h[who])
    assert r.status_code == 200, r.text
    return [it for g in r.json()["queue"] for it in g["items"] if it["type"].startswith("contractor_dispatch")]


def _count(c, h, who):
    r = c.get("/api/approval-queue/count", headers=h[who])
    assert r.status_code == 200, r.text
    return r.json().get("count")


def _legacy_accepted():
    return _mk(status="accepted", approval="")                                  # 舊單：已驗收、approval_status=''、doc_code=''


def _request(c, h, who, did):
    return c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h[who])


# ── ① 重現：舊單申請完工 ⇒ 要進佇列 ──────────────────────────────────────────

def test_legacy_order_requesting_completion_appears_in_the_queue_and_can_be_opened(S):
    c, h = S
    _tiers(["da_u1"])
    did = _legacy_accepted()
    assert _row(did)["doc_code"] == ""                                          # 前提：真的是舊單
    r = _request(c, h, "da_a", did)
    assert r.status_code == 200 and r.json()["approvalStatus"] == F.PENDING, r.text
    row = _row(did)
    assert row["approval_status"] == "" and row["completion_status"] == F.PENDING, "第一段仍是舊單、第二段待審核"
    assert row["doc_code"].startswith("DP-"), "送審當下補單號（原本留空 ⇒ 佇列略過）"
    its = _queue(c, h, "da_u1")
    assert [(i["type"], i["docCode"], i["dispatchId"]) for i in its] == [("contractor_dispatch_completion", row["doc_code"], did)], its
    assert _count(c, h, "da_u1") == 1, "紅點／待簽數"
    det = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch_completion", "id": row["doc_code"]}, headers=h["da_u1"])
    assert det.status_code == 200, det.text                                    # 詳情以 doc_code 為鍵：點得開
    rs = c.post("/api/approval-queue/reassign", headers=h["da_sa"], json={"type": "contractor_dispatch_completion", "id": row["doc_code"], "to_username": "da_u2", "reason": "出差"})
    assert rs.status_code == 200, rs.text                                       # 轉簽以 doc_code 為鍵：能轉


def test_legacy_completion_flows_through_approval_to_completed_and_leaves_the_queue(S):
    c, h = S
    _tiers(["da_u1"])
    did = _legacy_accepted()
    assert _request(c, h, "da_a", did).status_code == 200
    ok = c.post("/api/contractor-dispatches/%d/completion/approve" % did, json={}, headers=h["da_u1"])
    assert ok.status_code == 200, ok.text
    row = _row(did)
    assert row["status"] == "completed" and row["completion_status"] == F.APPROVED and row["approval_status"] == "", "舊單照舊（第一段仍空白）"
    assert _queue(c, h, "da_u1") == [] and _count(c, h, "da_u1") == 0


def test_no_tier_auto_completion_of_a_legacy_order_also_gets_a_code(S):
    c, h = S
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    did = _legacy_accepted()
    r = _request(c, h, "da_a", did)
    row = _row(did)
    assert r.status_code == 200 and row["status"] == "completed" and row["doc_code"].startswith("DP-"), (r.text, dict(row)["doc_code"])


def test_codes_are_unique_and_sequential_for_several_legacy_orders_and_existing_codes_are_kept(S):
    c, h = S
    _tiers(["da_u1"])
    a, b = _legacy_accepted(), _legacy_accepted()
    keep = _mk(status="accepted", approval=F.APPROVED)                          # 新單：已有單號
    before = _row(keep)["doc_code"]
    for d in (a, b, keep):
        assert _request(c, h, "da_a", d).status_code == 200
    codes = [_row(d)["doc_code"] for d in (a, b)]
    assert len(set(codes)) == 2 and all(x.startswith("DP-") for x in codes)
    assert _row(keep)["doc_code"] == before, "已有單號的不重編"
    assert len(_queue(c, h, "da_u1")) == 3


def test_notification_and_audit_use_the_code_not_the_row_id(S):
    c, h = S
    _tiers(["da_u1"])
    did = _legacy_accepted()
    assert _request(c, h, "da_a", did).status_code == 200
    code = _row(did)["doc_code"]
    msgs = [dict(r)["message"] for r in _rows("SELECT message FROM notifications WHERE type='dispatch_completion_request'")]
    assert msgs and all(code in m and "#%d" % did not in m for m in msgs), msgs
    aud = _rows("SELECT detail FROM audit_log WHERE action='vendor.dispatch.completion.submit'")
    assert aud and code in aud[0]["detail"]


def _rows(sql, args=()):
    cn = db.get_db()
    try:
        return cn.execute(sql, args).fetchall()
    finally:
        cn.close()


# ── ② 已卡住的資料：migration 0004 冪等補單號 ──────────────────────────────────

def _mig():
    return importlib.import_module("modules.subcontract.migrations.0004_dispatch_doc_code_backfill")


def _stuck(status="accepted", completion=F.PENDING, approval="", requested="2026-09-20T09:00:00"):
    did = _mk(status=status, approval=approval)
    cn = db.get_db()
    cn.execute("UPDATE contractor_dispatches SET completion_status=?, completion_requested_at=?, completion_approval_json=? WHERE id=?",
               (completion, requested, json.dumps({"requestedBy": "da_a", "tiers": [{"approvers": [{"username": "da_u1", "status": "pending"}]}], "currentTier": 0, "version": 1}), did))
    cn.commit()
    cn.close()
    return did


def _up():
    cn = db.get_db()
    try:
        r = _mig().up(cn)
        cn.commit()
        return r
    finally:
        cn.close()


def test_migration_backfills_only_the_stuck_rows_and_only_the_code(S):
    c, h = S
    _tiers(["da_u1"])
    stuck1, stuck2 = _stuck(), _stuck(completion=F.IN_PROGRESS)
    stuck_stage1 = _stuck(status="draft", completion="", approval=F.PENDING)    # 第一段待審核但單號空（理論上不會，也要補）
    untouched = [_legacy_accepted(), _mk(status="completed", approval=""), _mk(status="draft", approval=F.DRAFT), _mk(status="accepted", approval=F.APPROVED)]
    snap = {d: dict(_row(d)) for d in [stuck1, stuck2, stuck_stage1] + untouched}
    assert _up() is None
    for d in (stuck1, stuck2, stuck_stage1):
        now = dict(_row(d))
        assert now["doc_code"].startswith("DP-"), d
        a, b = dict(snap[d]), dict(now)
        a.pop("doc_code"), b.pop("doc_code")
        assert a == b, "只准補 doc_code，其他欄位逐位不變（%s）" % d
    for d in untouched:                                                         # 沒卡住的不動（舊單 doc_code 維持空）
        assert dict(_row(d)) == snap[d], d
    codes = [_row(d)["doc_code"] for d in (stuck1, stuck2, stuck_stage1)]
    assert len(set(codes)) == 3
    assert [i["dispatchId"] for i in _queue(c, h, "da_u1")] and {i["dispatchId"] for i in _queue(c, h, "da_u1")} >= {stuck1, stuck2}, "修復後出現在佇列"


def test_migration_is_idempotent_and_does_not_renumber(S):
    c, h = S
    _tiers(["da_u1"])
    d = _stuck()
    _up()
    first = dict(_row(d))
    assert _up() is None
    assert dict(_row(d)) == first, "第二次零變更、不重編"


def test_migration_uses_the_request_date_for_the_code_and_survives_unique_collisions(S):
    c, h = S
    d = _stuck(requested="2026-09-20T09:00:00")
    cn = db.get_db()
    cn.execute("INSERT INTO contractor_dispatches (quote_no, status, doc_code, approval_status, created_by, created_at, updated_at) VALUES ('MQ-DA-1','draft','DP-20260920-0001','草稿','x','2026-09-20','2026-09-20')")
    cn.commit()
    cn.close()
    _up()
    code = _row(d)["doc_code"]
    assert code.startswith("DP-20260920-") and code != "DP-20260920-0001", code
