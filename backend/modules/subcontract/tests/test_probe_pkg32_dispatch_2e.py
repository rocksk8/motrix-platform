# -*- coding: utf-8 -*-
"""第 32 包（745f3c2d）獨立探針（2e）：派發舊單。不同於作者測試的角度：多筆同日、重送不重新編號、重複送審、遷移冪等且只動卡住列、取消完工階段只關那一段。"""
import importlib
import json
import re

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers, _post  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _queue(c, h, who):
    r = c.get("/api/approval-queue", headers=h[who])
    assert r.status_code == 200, r.text
    return [(it["type"], it["quoteNo"]) for g in r.json()["queue"] for it in g["items"] if it["type"].startswith("contractor_dispatch")]


def _count(c, h, who):
    return c.get("/api/approval-queue/count", headers=h[who]).json()["count"]


def _request(c, h, who, did):
    return c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h[who])


def test_two_legacy_orders_same_day_get_distinct_codes_untouched_legacy_rows_stay_blank_and_resubmit_keeps_the_code(S):
    c, h = S
    _tiers(["da_u1"])
    a, b, quiet = _mk(status="accepted", approval=""), _mk(status="accepted", approval=""), _mk(status="accepted", approval="")
    assert _request(c, h, "da_a", a).status_code == 200 and _request(c, h, "da_a", b).status_code == 200
    ca, cb = _row(a)["doc_code"], _row(b)["doc_code"]
    assert re.fullmatch(r"DP-\d{8}-\d{4}", ca) and re.fullmatch(r"DP-\d{8}-\d{4}", cb) and ca != cb
    assert _row(quiet)["doc_code"] == "" and _row(quiet)["approval_status"] == ""               # 沒申請的舊單不動
    assert sorted(_queue(c, h, "da_u1")) == sorted([("contractor_dispatch_completion", ca), ("contractor_dispatch_completion", cb)])
    assert _count(c, h, "da_u1") == 2
    assert _request(c, h, "da_a", a).status_code == 409                                         # 重複送審：不重複、不改號
    assert _row(a)["doc_code"] == ca
    r = c.post("/api/contractor-dispatches/%d/completion/reject" % a, json={"reason": "再確認"}, headers=h["da_u1"])
    assert r.status_code == 200, r.text
    assert _request(c, h, "da_a", a).status_code == 200 and _row(a)["doc_code"] == ca           # 退回後重送：沿用同一個單號
    assert _row(a)["approval_status"] == "" and _row(b)["approval_status"] == ""                # 第一段（舊單身分）全程不變


def test_backfill_migration_is_idempotent_and_only_touches_stuck_rows(S):
    c, h = S
    stuck = _mk(status="accepted", approval="")
    quiet = _mk(status="accepted", approval="")
    cn = db.get_db()
    cn.execute("UPDATE contractor_dispatches SET completion_status=?, completion_requested_at=? WHERE id=?", (F.PENDING, "2026-09-20T10:00:00", stuck))
    cn.commit()
    before = {r["id"]: dict(r) for r in cn.execute("SELECT * FROM contractor_dispatches").fetchall()}
    mig = importlib.import_module("modules.subcontract.migrations.0004_dispatch_doc_code_backfill")
    assert mig.up(cn) is None
    cn.commit()
    mid = {r["id"]: dict(r) for r in cn.execute("SELECT * FROM contractor_dispatches").fetchall()}
    assert mid[stuck]["doc_code"] == "DP-20260920-0001"                                          # 日期取送審日
    assert mid[quiet]["doc_code"] == ""                                                          # 沒卡住的不動
    changed = {k for k in before[stuck] if before[stuck][k] != mid[stuck][k]}
    assert changed == {"doc_code"}, changed                                                      # 只動單號這一欄
    assert mig.up(cn) is None
    cn.commit()
    again = {r["id"]: dict(r) for r in cn.execute("SELECT * FROM contractor_dispatches").fetchall()}
    cn.close()
    assert again == mid                                                                          # 冪等


def test_legacy_edit_stays_legacy_with_audit_and_approved_edit_still_resets(W):
    c, h = W
    leg = _mk(status="sent", approval="")
    r = c.put("/api/contractor-dispatches/%d" % leg, headers=h["da_a"], json=_body(status="sent", items_json=[{"description": "改", "amount": 5}]))
    assert r.status_code == 200, r.text
    assert _row(leg)["approval_status"] == "" and _row(leg)["doc_code"] == ""
    cn = db.get_db()
    rows = [json.loads(x["detail"] or "{}") for x in cn.execute("SELECT detail FROM audit_log WHERE action='vendor.dispatch.legacy_edit'").fetchall()]
    cn.close()
    assert len(rows) == 1
    appr = _mk(status="sent", approval=F.APPROVED)
    r2 = c.put("/api/contractor-dispatches/%d" % appr, headers=h["da_a"], json=_body(status="sent", items_json=[{"description": "核准後改", "amount": 5}]))
    assert r2.status_code == 200 and _row(appr)["approval_status"] != F.APPROVED               # 控制組：已核准的實質編輯回草稿


def test_cancel_with_completion_pending_closes_only_that_stage_and_clears_queue(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk(status="accepted", approval="")
    assert _request(c, h, "da_a", did).status_code == 200
    code = _row(did)["doc_code"]
    assert _queue(c, h, "da_u1") == [("contractor_dispatch_completion", code)]
    r = c.post("/api/contractor-dispatches/%d/status" % did, json={"target": "cancelled", "reason": "客戶取消"}, headers=h["da_a"])
    assert r.status_code == 200, r.text
    row = _row(did)
    assert row["status"] == "cancelled" and row["approval_status"] == "" and row["completion_status"] != F.PENDING   # 第一段（舊單）不動，只關完工段
    assert _queue(c, h, "da_u1") == [] and _count(c, h, "da_u1") == 0
    assert c.post("/api/contractor-dispatches/%d/completion/approve" % did, json={}, headers=h["da_u1"]).status_code == 409
