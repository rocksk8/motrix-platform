# -*- coding: utf-8 -*-
"""簽核二擇一 S5（後端半）：「維持／編輯」彈窗要的資料（`approveReview`）＋ `confirmNote` 伺服器端強制。
規格：docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md G1／G2／H2／H3／H7／K3。

驗收字句（H7，逐字進斷言）：
- 「B 複查選「維持」＝簽在目前指紋」
- 「轉簽、代理代簽成立旗標、跳提示；不作廢任何簽。」
- 「旗標關閉時全套行為與今天相同。」
G1：「新增了原因（例如毛利跌破門檻）時，B 選「維持」必須填一句確認（寫進稽核）；不新增則一鍵維持。」
"""
import copy
import json

import pytest

from modules.case import content_fp as C
from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _doc, _login, _row, _seed
from modules.case.tests.test_reconcile_txn_s3b_2026_11_06 import (
    _approve, _audits, _entries, _fresh_mode_cache, _funnel_edit, _qty, _set_mode, _HS)
from modules.case.tests.test_review_edit_s4_2026_11_07 import _approve_raw, _get
from tests._requires import requires_module

pytestmark = requires_module("case", "S5 打 M01 的報價單核准／簽核佇列詳情")

_ = _fresh_mode_cache


def _doc_with_cost(cost=50.0, price=100.0):
    d = _doc()
    d["items"][0].update({"cost": cost, "unitPrice": price})
    return d


def _set_cost(cost):
    def m(d):
        d["items"][0]["cost"] = cost
    return m


def _signed_b_then_reconfirm(client, make_user, mutate, doc=None):
    """兩層；B（ap0）簽過（帶 J1 基準）→ 別人改內容 ⇒ B 回待複查。回 (headers, names)。"""
    hs, names = _seed(client, make_user, tiers=2, doc=doc or _doc_with_cost())
    _HS.clear(); _HS.update(dict(zip(names, hs)))
    _set_mode(2)
    _approve(client, hs[0])
    es, _ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedReasonEntries"] is not None
    _funnel_edit(mutate)
    es, _ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"]
    return hs, names


# ── approve_review 純函式 ──────────────────────────────────────────────────────────────────
def _entry_for(doc, **extra):
    fp, kh = C.content_fingerprint(doc), C.key_hashes(doc)
    e = {"username": "b", "status": "pending", "reconfirm": True, "signedFp": fp, "signedKeyHashes": kh,
         "signedReasonEntries": C.current_reasons_or_none(doc)}
    e.update(extra)
    return e


def test_review_without_flags_is_empty_and_pure():
    doc = _doc_with_cost()
    before = copy.deepcopy(doc)
    entry = {"username": "b", "status": "pending"}
    r = C.approve_review(doc, entry)
    assert r["flags"] == [] and r["flagLabels"] == [] and r["changedBlocks"] == [] and r["newReasons"] == [] and r["needNote"] is False
    assert r["entry"] == "b" and r["contentFp"] == C.content_fingerprint(doc)
    assert doc == before and entry == {"username": "b", "status": "pending"}


def test_review_reassigned_flag_has_no_diff_fields():
    r = C.approve_review(_doc_with_cost(), {"username": "b", "status": "pending", "reassignedFrom": "a"})
    assert r["flags"] == ["reassigned"] and r["flagLabels"] == [C.FLAG_LABELS["reassigned"]] and r["needNote"] is False and r["changedBlocks"] == []


def test_review_reconfirm_lists_changed_blocks_names_only():
    old = _doc_with_cost()
    entry = _entry_for(old)
    new = copy.deepcopy(old)
    new["items"][0]["qty"] = 9
    new["caseRecord"]["payment"]["paid"] = 5
    r = C.approve_review(new, entry)
    assert r["flags"] == ["reconfirm"]
    assert r["changedBlocks"] == ["caseRecord.payment", "items"], "只回區塊名（排序），不含內容"
    assert r["needNote"] is False and r["newReasons"] == []


def test_review_new_low_margin_reason_requires_note_and_lists_text():
    old = _doc_with_cost(cost=50.0)
    entry = _entry_for(old)
    new = copy.deepcopy(old)
    new["items"][0]["cost"] = 90.0                                   # 毛利 1-94.5/100＝5.5% < 30%
    r = C.approve_review(new, entry)
    assert r["needNote"] is True
    assert any("毛利率" in t for t in r["newReasons"]), r["newReasons"]


def test_review_improvement_or_same_reasons_need_no_note():
    old = _doc_with_cost(cost=90.0)                                   # 原本就低毛利（已有原因）
    entry = _entry_for(old)
    better = copy.deepcopy(old)
    better["items"][0]["cost"] = 80.0                                 # 仍低於 30% 但變好
    assert C.approve_review(better, entry)["needNote"] is False
    same = copy.deepcopy(old)
    same["items"][0]["qty"] = 7                                       # 原因集合不變
    assert C.approve_review(same, entry)["needNote"] is False


def test_review_legacy_entry_without_baseline_does_not_require_note():
    """J1：「舊單（沒有 signedReasonEntries）…該次複查不提示「新增原因」。」"""
    old = _doc_with_cost()
    entry = _entry_for(old)
    del entry["signedReasonEntries"]
    new = copy.deepcopy(old)
    new["items"][0]["cost"] = 90.0
    r = C.approve_review(new, entry)
    assert r["needNote"] is False and r["newReasons"] == []
    del entry["signedKeyHashes"]
    assert C.approve_review(new, entry)["changedBlocks"] == [], "沒有雜湊就不亂報區塊"


def test_review_unreadable_current_reasons_fails_closed(monkeypatch):
    """算不出目前的原因 ⇒ 要求填說明（不能當作沒新增）。"""
    old = _doc_with_cost()
    entry = _entry_for(old)
    monkeypatch.setattr(C, "current_reasons_or_none", lambda d: None)
    assert C.approve_review(old, entry)["needNote"] is True


def test_review_diff_error_fails_closed(monkeypatch):
    from modules.case import quote_terms as qt
    old = _doc_with_cost()
    entry = _entry_for(old)
    monkeypatch.setattr(qt, "category_summary", lambda a, b: (_ for _ in ()).throw(RuntimeError("boom")))
    assert C.approve_review(old, entry)["needNote"] is True


# ── 讀路徑：GET／佇列詳情 ───────────────────────────────────────────────────────────────────
def test_get_has_no_approve_review_when_mode_is_off_or_shadow(client, make_user):
    """H7：「旗標關閉時全套行為與今天相同。」回應不多任何鍵。"""
    hs, names = _seed(client, make_user, tiers=1)
    for code in (0, 1):
        _set_mode(code)
        C._reset_mode_cache()
        assert "approveReview" not in _get(client, hs[0])


def test_get_has_approve_review_in_on_mode_only_while_pending(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    g = _get(client, hs[0])
    assert g["approveReview"]["entry"] == names[0] and g["approveReview"]["flags"] == [] and g["approveReview"]["contentFp"] == g["contentFp"]
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET status='已送出' WHERE quote_no=?", (NO,)); c.commit(); c.close()
    g = _get(client, hs[0])
    assert "approveReview" not in g and "contentFp" not in g


def test_get_exposes_reconfirm_review_for_the_pending_entry(client, make_user):
    hs, names = _signed_b_then_reconfirm(client, make_user, _set_cost(90.0))
    rv = _get(client, hs[0])["approveReview"]
    assert rv["entry"] == names[0] and rv["flags"] == ["reconfirm"] and rv["changedBlocks"] == ["items"]
    assert rv["needNote"] is True and rv["newReasons"]


def test_queue_detail_endpoint_carries_approve_review(client, make_user):
    hs, names = _signed_b_then_reconfirm(client, make_user, _set_cost(90.0))
    r = client.get("/api/approval-queue/detail", params={"type": "quotation", "id": NO}, headers=hs[0])
    assert r.status_code == 200, r.text
    rv = r.json()["approveReview"]
    assert rv["flags"] == ["reconfirm"] and rv["needNote"] is True and rv["contentFp"] == r.json()["contentFp"]


def test_queue_detail_has_no_approve_review_in_default_off_mode(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    r = client.get("/api/approval-queue/detail", params={"type": "quotation", "id": NO}, headers=hs[0])
    assert r.status_code == 200 and "approveReview" not in r.json() and r.json()["contentFp"]


# ── approve：confirmNote 強制（G1）──────────────────────────────────────────────────────────
def test_keep_with_new_reason_needs_note_409_then_ok_and_audited(client, make_user):
    hs, names = _signed_b_then_reconfirm(client, make_user, _set_cost(90.0))
    fp = _get(client, hs[0])["contentFp"]
    for note in (None, "", "   "):
        body = {"expectedFp": fp, "choice": "keep"}
        if note is not None:
            body["confirmNote"] = note
        r = _approve_raw(client, hs[0], **body)
        assert r.status_code == 409 and r.headers.get("X-Approve-Need-Note") == "1" and r.headers.get("X-Approve-Flags") == "reconfirm", (note, r.status_code, r.text)
    es, _ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"], "沒簽成：條目維持待複查"
    r = _approve_raw(client, hs[0], expectedFp=fp, choice="keep", confirmNote="毛利掉了，業務說客戶急單，我知道")
    assert r.status_code == 200, r.text
    es, _ap, _st = _entries()
    d, _s, _u = _row()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == C.content_fingerprint(d) == fp, "H7：「B 複查選「維持」＝簽在目前指紋」"
    assert "reconfirm" not in es[0]
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["flags"] == ["reconfirm"] and det["choice"] == "keep" and det["fp"] == fp
    assert det["confirmNote"].startswith("毛利掉了") and det["needNote"] is True and det["changedBlocks"] == ["items"] and det["newReasons"]


def test_keep_without_new_reason_is_one_click(client, make_user):
    """G1：「不新增則一鍵維持。」只改數量：原因集合不變。"""
    hs, names = _signed_b_then_reconfirm(client, make_user, _qty(5))
    fp = _get(client, hs[0])["contentFp"]
    assert _get(client, hs[0])["approveReview"]["needNote"] is False
    r = _approve_raw(client, hs[0], expectedFp=fp, choice="keep")
    assert r.status_code == 200, r.text
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["needNote"] is False and "confirmNote" not in det and det["changedBlocks"] == ["items"]


def test_stale_fp_is_reported_before_the_note_requirement(client, make_user):
    hs, names = _signed_b_then_reconfirm(client, make_user, _set_cost(90.0))
    stale = _get(client, hs[0])["contentFp"]
    _funnel_edit(_qty(11))
    r = _approve_raw(client, hs[0], expectedFp=stale, choice="keep")
    assert r.status_code == 409 and "內容已更新" in r.text and r.headers.get("X-Approve-Need-Note") is None


def test_note_not_required_when_mode_is_off(client, make_user):
    """H7：「旗標關閉時全套行為與今天相同。」預設 off：就算條目帶著 reconfirm、也有新增原因，approve 不要求說明／choice。"""
    hs, names = _seed(client, make_user, tiers=1, doc=_doc_with_cost(cost=90.0))
    d, _s, _u = _row()
    e = d["approval"]["tiers"][0]["approvers"][0]
    e.update({"reconfirm": True, "signedReasonEntries": [], "signedKeyHashes": {}})
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    assert C.approve_review(d, e)["needNote"] is True, "前提：這張單在 on 模式下會要求說明"
    r = _approve_raw(client, hs[0])
    assert r.status_code == 200, r.text


def test_reassigned_and_delegated_never_need_a_note(client, make_user):
    """H7：「轉簽、代理代簽成立旗標、跳提示；不作廢任何簽。」只要選擇（choice），不要求說明；簽核狀態不被作廢。"""
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    d["approval"]["tiers"][0]["approvers"][0]["reassignedFrom"] = "someone"
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    g = _get(client, hs[0])
    assert g["approveReview"]["flags"] == ["reassigned"] and g["approveReview"]["needNote"] is False
    r = _approve_raw(client, hs[0], expectedFp=g["contentFp"], choice="keep")
    assert r.status_code == 200, r.text
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["flags"] == ["reassigned"] and det["choice"] == "keep" and "newReasons" not in det


def test_note_is_truncated_in_audit(client, make_user):
    hs, names = _signed_b_then_reconfirm(client, make_user, _set_cost(90.0))
    fp = _get(client, hs[0])["contentFp"]
    r = _approve_raw(client, hs[0], expectedFp=fp, choice="keep", confirmNote="甲" * 500)
    assert r.status_code == 200, r.text
    assert len(json.loads(_audits("quotation.approve")[-1]["detail"])["confirmNote"]) == C.REVIEW_NOTE_MAX


def test_no_ui_endpoint_added_for_review_context():
    """S5 不新增路由：彈窗資料搭在既有 GET 與佇列詳情上（不動路由登記／棘輪）。"""
    from main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("approve-context" in p or "approve-review" in p for p in paths)
