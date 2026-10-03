# -*- coding: utf-8 -*-
"""35c 重新存已完結精算的護欄（使用者裁示；0c 稽核 (a)(b)）：對「已完結」的案件再 PUT（超級管理員的重新開啟路徑）

- 一律要填非空白的理由（重新開啟成草稿、或再存一次完結都一樣），理由寫進編輯歷程與稽核紀錄；
- 再存成「完結」時跑和第一次完結相同的後端重算比對（偽造的數字不能靠『已完結再存』繞過），並補蓋口徑標記；
- 舊的已完結案不重驗、不改寫（讀取照舊回凍結值）。
紅燈探針先 commit：舊程式沒有理由欄位、已完結再存完全不驗證也不蓋標記。
"""
import json

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _put_settlement
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import URL, _status, case, page_payload  # noqa: F401


def _put_r(c, h, st, reason=None):
    body = {"settlement": st}
    if reason is not None:
        body["reason"] = reason
    return c.put(URL, json=body, headers=h)


def _saved():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        cn.close()


def _audit_rows():
    cn = db.get_db()
    try:
        return [json.loads(r["detail"] or "{}") for r in cn.execute("SELECT detail FROM audit_log WHERE action='quotation.settlement' AND target_id=? ORDER BY id", (NO,)).fetchall()]
    finally:
        cn.close()


def _finalize_honest(c, h):
    r = _put_r(c, h, page_payload(c, h))
    assert r.status_code == 200, r.text[:200]
    assert _status() == "finalized"


def test_resaving_a_finalized_case_without_a_reason_is_refused(case):
    c, h = case
    _finalize_honest(c, h)
    for reason in (None, "", "   "):
        r = _put_r(c, h, page_payload(c, h), reason)
        assert r.status_code == 422 and "理由" in r.json()["detail"], (reason, r.status_code, r.text[:160])
    draft = page_payload(c, h)
    draft["status"] = "draft"
    r = _put_r(c, h, draft)                                         # 重新開啟成草稿也要理由
    assert r.status_code == 422 and "理由" in r.json()["detail"], r.text[:160]
    assert _status() == "finalized", "被拒絕的重新開啟不可以改到存檔"


def test_resaving_as_finalized_runs_the_same_recompute_as_the_first_finalize(case):
    c, h = case
    _finalize_honest(c, h)
    before = _saved()["settlement"]["summary"]["netProfit"]
    r = _put_r(c, h, page_payload(c, h, netProfit=888888), "改備註")
    assert r.status_code == 409, "已完結再存沒有重算比對：%s %s" % (r.status_code, r.text[:200])
    assert _saved()["settlement"]["summary"]["netProfit"] == before, "被拒絕的再存不可以改到存檔"


def test_resaving_a_legacy_finalized_case_stamps_the_basis_and_records_the_reason(case):
    c, h = case
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 99, "netProfit": 5}})
    p = page_payload(c, h)
    p["summary"].pop("dispatchBasis")
    r = _put_r(c, h, p, "補上漏記的備註")
    assert r.status_code == 200, r.text[:200]
    s = _saved()
    assert s["settlement"]["summary"]["dispatchBasis"] == "pretax", "再存沒有蓋口徑標記"
    assert s["editHistory"][-1].get("reason") == "補上漏記的備註"
    assert any(a.get("reason") == "補上漏記的備註" for a in _audit_rows()), "理由沒有進稽核紀錄：%s" % _audit_rows()


def test_reopening_to_draft_with_a_reason_works_and_the_reason_is_kept(case):
    c, h = case
    _finalize_honest(c, h)
    draft = page_payload(c, h)
    draft["status"] = "draft"
    r = _put_r(c, h, draft, "承攬商發票補開，需重算")
    assert r.status_code == 200, r.text[:200]
    assert _status() == "draft"
    assert _saved()["editHistory"][-1].get("reason") == "承攬商發票補開，需重算"
    assert any(a.get("reason") == "承攬商發票補開，需重算" for a in _audit_rows())


def test_the_reason_is_not_asked_for_when_the_case_is_not_finalized(case):
    c, h = case
    draft = page_payload(c, h)
    draft["status"] = "draft"
    assert _put_r(c, h, draft).status_code == 200                    # 草稿存草稿：照舊不需要理由
    assert _put_r(c, h, page_payload(c, h)).status_code == 200      # 第一次完結：照舊不需要理由


def test_old_frozen_cases_are_still_read_unchanged_after_a_refused_resave(case):
    c, h = case
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": 4550, "netProfit": 888888}})
    assert _put_r(c, h, page_payload(c, h)).status_code == 422
    d = _get(c, h)
    assert d["frozen"] is True and d["savedSummary"]["netProfit"] == 888888 and d["totals"]["dispatchTotal"] == 0
