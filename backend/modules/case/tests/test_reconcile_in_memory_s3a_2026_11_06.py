# -*- coding: utf-8 -*-
"""簽核二擇一 S3a：`content_fp.reconcile_in_memory`／`reconfirm_enabled`（純函式；沒有呼叫端、不碰資料庫）。
規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §K2。"""
import copy

import pytest

from modules.case import content_fp as C

NOW = "2026-11-06T23:00:00"
L = C.REVIEW_ROUNDS_LIMIT


def _doc(tiers=(("b",), ("c",), ("d",)), signed=0, status="待審核", requested_by="a"):
    """報價單：前 `signed` 層已簽（用 S1 的 stamp_signed 蓋章）。"""
    data = {"quoteNo": "MQ-1", "customerName": "甲", "items": [{"id": "i1", "qty": 1, "unitPrice": 1000}],
            "tot": {"total": 1050}, "caseRecord": {"payment": {"paid": 0}}, "status": status}
    appr = {"status": "pending", "requestedBy": requested_by, "currentTier": 0,
            "tiers": [{"approvers": [{"username": u, "displayName": u.upper(), "status": "pending"} for u in t]} for t in tiers]}
    data["approval"] = appr
    C.reconcile_in_memory(data, NOW, "system", "submit", enabled=True)          # 送審建立基準
    for i in range(signed):
        was = C.pending_entries(appr)
        for a in appr["tiers"][i]["approvers"]:
            a["status"], a["approvedAt"] = "approved", "2026-11-06T10:0%d:00" % i
        C.stamp_signed(appr, was, data)
        appr["currentTier"] = i + 1
    return data


def _edit(data, **kw):
    data["items"][0]["unitPrice"] = kw.get("price", 2000)


def _entry(data, user):
    return next(a for t in data["approval"]["tiers"] for a in t["approvers"] if a["username"] == user)


# ── 不動的情況 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["草稿", "已核准", "已拒絕", "已作廢"])
def test_not_pending_is_untouched(status):
    d = _doc(signed=1)
    _edit(d)
    d["status"] = status
    before = copy.deepcopy(d)
    assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])
    assert d == before


def test_no_tiers_or_no_approval_is_untouched():
    for d in ({"items": []}, {"approval": None}, {"approval": {"tiers": []}}, {"approval": "x"}, None):
        before = copy.deepcopy(d)
        assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])
        assert d == before


def test_status_arg_overrides_and_fallback_to_approval_status():
    d = _doc(signed=1)
    _edit(d)
    d.pop("status")
    assert C.reconcile_in_memory(copy.deepcopy(d), NOW, "c", "put", status="已核准", enabled=True) == (False, [])
    assert C.reconcile_in_memory(copy.deepcopy(d), NOW, "c", "put", status="簽核中", enabled=True)[0] is True
    assert C.reconcile_in_memory(copy.deepcopy(d), NOW, "c", "put", enabled=True)[0] is True          # 沒給 status ⇒ approval.status=="pending"
    d["approval"]["status"] = "approved"
    assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])


# ── 舊單／剛送審：靜默設基準 ───────────────────────────────────────────────
def test_missing_contentfp_sets_baseline_silently_even_with_signed_entries():
    d = _doc(signed=2)
    d["approval"].pop("contentFp"), d["approval"].pop("keyHashes"), d["approval"].pop("baselineSetBy")
    for u in ("b", "c"):                                                       # 真正的舊單：S1 上線前簽的，條目也沒有 signedFp（stamp_signed 一定同時設 contentFp，不會只缺基準）
        _entry(d, u).pop("signedFp"), _entry(d, u).pop("signedKeyHashes")
    _edit(d)                                                                   # 舊單：沒基準時內容已經跟簽的時候不同，也不算異動
    ch, notices = C.reconcile_in_memory(d, NOW, "c", "approve", enabled=True)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["contentFp"] == C.content_fingerprint(d) and a["keyHashes"] == C.key_hashes(d) and a["baselineSetBy"] == "approve"
    assert _entry(d, "b")["status"] == "approved" and "reconfirm" not in _entry(d, "b")
    assert not a.get("contentRev") and not a.get("changeLog") and not a.get("reviewRounds")
    assert C.reconcile_in_memory(d, NOW, "c", "approve", enabled=True) == (False, [])


def test_submit_baseline_is_set_by_source():
    d = _doc()
    assert d["approval"]["baselineSetBy"] == "submit" and d["approval"]["contentFp"] == C.content_fingerprint(d)


# ── 冪等 ───────────────────────────────────────────────────────────────────
def test_same_fingerprint_is_noop_and_idempotent_after_invalidation():
    d = _doc(signed=2)
    assert C.reconcile_in_memory(d, NOW, "x", "put", enabled=True) == (False, [])
    _edit(d)
    assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)[0] is True
    snap = copy.deepcopy(d)
    for _ in range(3):
        assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])
    assert d == snap


def test_excluded_keys_do_not_trigger():
    d = _doc(signed=1)
    d["statusLog"] = [{"x": 1}]
    d["editHistory"] = [{"y": 1}]
    d["approval"]["reasons"] = ["x"]
    assert C.reconcile_in_memory(d, NOW, "x", "put", enabled=True) == (False, [])
    assert _entry(d, "b")["status"] == "approved"


# ── 旗標開：作廢 ───────────────────────────────────────────────────────────
def test_invalidate_signed_entry_and_all_bookkeeping():
    d = _doc(signed=1)                                                         # B 已簽，輪到 C
    old_fp = d["approval"]["contentFp"]
    _edit(d)                                                                   # C 編輯
    ch, notices = C.reconcile_in_memory(d, NOW, {"username": "c", "display_name": "小C"}, "put", enabled=True)
    a, b = d["approval"], _entry(d, "b")
    assert ch is True
    assert b["status"] == "pending" and b["reconfirm"] is True and b["prevSignedFp"] == old_fp and b["prevApprovedAt"] == "2026-11-06T10:00:00"
    assert "approvedAt" not in b
    assert a["currentTier"] == 0 and a["contentRev"] == 1 and a["reviewRounds"] == 1
    assert a["contentFp"] == C.content_fingerprint(d) != old_fp
    assert a["changeLog"] == [{"at": NOW, "rev": 1, "blocks": ["items"], "by": "小C", "source": "put", "invalidated": ["b"], "resigned": []}]
    assert "shadowLog" not in a
    kinds = {n["type"]: n for n in notices}
    assert kinds["approval_reconfirm"]["to"] == ["b"] and "小C" in kinds["approval_reconfirm"]["text"] and "items" in kinds["approval_reconfirm"]["text"]
    all_to = sorted(u for n in notices if n["type"] == "approval_reconfirm_info" for u in n["to"])
    assert all_to == ["a", "d"], "後續層（D）與送審人（A）收到提示；編輯者 C 自己不收"


def test_three_tier_t1_t2_signed_t3_edits_both_pending_current_tier_zero():
    d = _doc(signed=2)                                                         # T1=B、T2=C 已簽，T3=D 待簽
    _edit(d)
    ch, notices = C.reconcile_in_memory(d, NOW, "d", "put", enabled=True)
    assert ch and _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"
    assert _entry(d, "b")["reconfirm"] and _entry(d, "c")["reconfirm"]
    assert d["approval"]["currentTier"] == 0 and d["approval"]["reviewRounds"] == 1, "兩層一起作廢只算 1 輪"
    assert next(n for n in notices if n["type"] == "approval_reconfirm")["to"] == ["b", "c"]


def test_entries_without_signedfp_are_never_invalidated():
    d = _doc(signed=2)
    for u in ("b", "c"):
        _entry(d, u).pop("signedFp"), _entry(d, u).pop("signedKeyHashes")       # S1 上線前簽的舊條目
    _edit(d)
    ch, notices = C.reconcile_in_memory(d, NOW, "d", "put", enabled=True)
    assert _entry(d, "b")["status"] == "approved" and _entry(d, "c")["status"] == "approved"
    assert d["approval"]["currentTier"] == 2 and not d["approval"].get("reviewRounds")


# ── 需求 4：沒有任何條目需要作廢 ───────────────────────────────────────────
@pytest.mark.parametrize("old_style", [False, True])
def test_no_entry_to_invalidate_still_advances_baseline_without_round_or_notice(old_style):
    d = _doc(signed=0)                                                         # 還沒人簽
    if old_style:                                                              # 或：全是舊的沒有 signedFp 的已簽條目
        d = _doc(signed=1)
        _entry(d, "b").pop("signedFp"), _entry(d, "b").pop("signedKeyHashes")
    _edit(d)
    old_fp = d["approval"]["contentFp"]
    ch, notices = C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["contentFp"] == C.content_fingerprint(d) != old_fp, "基準追上最新內容"
    assert not a.get("reviewRounds"), "不是複查輪次"
    assert a["contentRev"] == 1 and a["changeLog"][0]["invalidated"] == []
    assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])


# ── 影子模式 ───────────────────────────────────────────────────────────────
def test_shadow_mode_only_logs_and_never_touches_entries():
    d = _doc(signed=2)
    _edit(d)
    entries_before = copy.deepcopy(d["approval"]["tiers"])
    cur_before, tier_before = d["approval"]["currentTier"], d["approval"]["currentTier"]
    ch, notices = C.reconcile_in_memory(d, NOW, {"username": "d"}, "material", enabled=False)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["tiers"] == entries_before and a["currentTier"] == tier_before == cur_before
    assert a["shadowLog"] == [{"at": NOW, "blocks": ["items"], "by": "d", "source": "material", "fp": C.content_fingerprint(d), "wouldInvalidate": ["b", "c"]}]
    assert not a.get("contentRev") and not a.get("changeLog") and not a.get("reviewRounds")
    assert a["contentFp"] == C.content_fingerprint(d)
    assert C.reconcile_in_memory(d, NOW, "d", "material", enabled=False) == (False, []), "冪等：不重複記"
    assert len(a["shadowLog"]) == 1


def test_shadow_with_nobody_signed_logs_empty_would_invalidate():
    d = _doc(signed=0)
    _edit(d)
    C.reconcile_in_memory(d, NOW, "c", "put", enabled=False)
    assert d["approval"]["shadowLog"][0]["wouldInvalidate"] == []


# ── 需求 5：影子 N 次後切到開，一次補追只算 1 輪 ───────────────────────────
def test_shadow_then_on_catches_up_all_stale_entries_as_one_round():
    d = _doc(signed=2)
    for price in (1100, 1200, 1300):                                           # 影子期間內容被改 3 次
        d["items"][0]["unitPrice"] = price
        C.reconcile_in_memory(d, NOW, "x", "put", enabled=False)
    a = d["approval"]
    assert len(a["shadowLog"]) == 3 and _entry(d, "b")["status"] == "approved" and not a.get("reviewRounds")
    assert C.reconcile_in_memory(copy.deepcopy(d), NOW, "x", "put", enabled=False) == (False, []), "旗標仍關：過期條目不動、不重複記"
    # 旗標切到開；內容沒有再變——下一次 reconcile 就要補追
    ch, notices = C.reconcile_in_memory(d, NOW, "sys", "approve", enabled=True)
    assert ch is True
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"
    assert a["reviewRounds"] == 1, "只 +1，不是補記 3 輪"
    assert a["contentRev"] == 1 and a["currentTier"] == 0
    log = a["changeLog"][-1]
    assert log["catchUp"] is True and log["invalidated"] == ["b", "c"] and log["blocks"] == ["items"]
    assert any(n["type"] == "approval_reconfirm" and n["to"] == ["b", "c"] for n in notices)
    assert C.reconcile_in_memory(d, NOW, "sys", "approve", enabled=True) == (False, []), "補追之後冪等"


def test_shadow_then_on_with_a_new_change_is_also_one_round():
    d = _doc(signed=2)
    for price in (1100, 1200):
        d["items"][0]["unitPrice"] = price
        C.reconcile_in_memory(d, NOW, "x", "put", enabled=False)
    d["items"][0]["unitPrice"] = 1300
    C.reconcile_in_memory(d, NOW, "x", "put", enabled=True)
    assert d["approval"]["reviewRounds"] == 1 and _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"


# ── 輪次上限 ───────────────────────────────────────────────────────────────
def test_round_limit_suspends_instead_of_invalidating_and_notifies_superadmin_once():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    a = d["approval"]
    assert ch and a["reconfirmSuspended"] is True and a["reviewRounds"] == L
    assert _entry(d, "b")["status"] == "approved" and "reconfirm" not in _entry(d, "b"), "不作廢"
    assert [n["type"] for n in notices] == ["approval_reconfirm_suspended"] and notices[0]["to"] == "superadmin" and "最高管理者" in notices[0]["text"]
    assert a["changeLog"][-1]["suspended"] is True and a["contentFp"] == C.content_fingerprint(d)
    d["items"][0]["unitPrice"] = 3000                                          # 之後再改：仍不作廢、不再重複通知
    ch, notices = C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    assert ch and notices == [] and _entry(d, "b")["status"] == "approved"


def test_round_limit_boundary_limit_minus_one_still_invalidates():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L - 1
    _edit(d)
    C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    assert d["approval"]["reviewRounds"] == L and _entry(d, "b")["status"] == "pending" and not d["approval"].get("reconfirmSuspended")


def test_limit_does_not_apply_in_shadow_mode():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L
    _edit(d)
    C.reconcile_in_memory(d, NOW, "c", "put", enabled=False)
    assert not d["approval"].get("reconfirmSuspended") and d["approval"]["shadowLog"]


def test_five_real_rounds_then_sixth_is_suspended():
    d = _doc(signed=1)
    for n in range(L):
        d["items"][0]["unitPrice"] = 2000 + n
        C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
        e = _entry(d, "b")                                                     # B 複查後再簽（S1 蓋章），輪到 C
        was = C.pending_entries(d["approval"])
        e["status"], e["approvedAt"] = "approved", NOW
        C.stamp_signed(d["approval"], was, d)
        d["approval"]["currentTier"] = 1
    assert d["approval"]["reviewRounds"] == L
    d["items"][0]["unitPrice"] = 9999
    C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    assert d["approval"]["reconfirmSuspended"] is True and _entry(d, "b")["status"] == "approved"


# ── review-edit：複查者編輯後的簽視為新版（H9-①）─────────────────────────
def test_review_edit_by_reconfirming_signer_resigns_new_version_and_others_pending():
    d = _doc(signed=2)                                                         # B、C 已簽，D 待簽
    _edit(d, price=1500)
    C.reconcile_in_memory(d, NOW, "d", "put", enabled=True)                    # D 改了 ⇒ B、C 都 pending＋reconfirm
    assert _entry(d, "b")["reconfirm"] and _entry(d, "c")["reconfirm"]
    d["items"][0]["unitPrice"] = 1600                                          # B 複查時自己也改（review-edit）
    ch, notices = C.reconcile_in_memory(d, NOW, {"username": "b", "display_name": "B"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    b, c = _entry(d, "b"), _entry(d, "c")
    assert ch and b["status"] == "approved" and b["signedFp"] == C.content_fingerprint(d) and "reconfirm" not in b and b["approvedAt"] == NOW
    assert c["status"] == "pending" and c["reconfirm"] is True
    assert d["approval"]["currentTier"] == 1, "第一個未簽層＝C"
    assert d["approval"]["changeLog"][-1]["resigned"] == ["b"]


def test_review_edit_by_stale_approved_entry_is_resigned_not_invalidated():
    d = _doc(signed=1)
    _edit(d)
    ch, notices = C.reconcile_in_memory(d, NOW, {"username": "b"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    assert _entry(d, "b")["status"] == "approved" and _entry(d, "b")["signedFp"] == C.content_fingerprint(d)
    assert not d["approval"].get("reviewRounds"), "沒有人被作廢 ⇒ 不算一輪"
    assert not [n for n in notices if n["type"] == "approval_reconfirm"]


def test_review_edit_by_first_time_pending_signer_is_not_auto_signed():
    d = _doc(signed=1)                                                         # B 已簽，C 首次待簽
    _edit(d)
    C.reconcile_in_memory(d, NOW, {"username": "c"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    c = _entry(d, "c")
    assert c["status"] == "pending" and "signedFp" not in c, "C 仍須自己再按一次核准"
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "b")["reconfirm"]


def test_non_review_edit_source_never_resigns_the_actor():
    d = _doc(signed=1)
    _edit(d)
    C.reconcile_in_memory(d, NOW, {"username": "b"}, "put", enabled=True)
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "b")["reconfirm"]


# ── 區塊名、記錄上限、其他 ────────────────────────────────────────────────
def test_changed_blocks_include_case_record_second_level_and_unknown_when_no_old_hashes():
    d = _doc(signed=1)
    d["caseRecord"]["payment"]["paid"] = 500
    C.reconcile_in_memory(d, NOW, "f", "payment", enabled=True)
    assert d["approval"]["changeLog"][0]["blocks"] == ["caseRecord.payment"]
    d2 = _doc(signed=1)
    d2["approval"].pop("keyHashes")
    for a in d2["approval"]["tiers"][0]["approvers"]:
        a.pop("signedKeyHashes")
    _edit(d2)
    C.reconcile_in_memory(d2, NOW, "f", "put", enabled=True)
    log = d2["approval"]["changeLog"][0]
    assert log["blocks"] == [] and log["blocksUnknown"] is True


def test_logs_are_capped():
    d = _doc(signed=0)
    for n in range(C.LOG_CAP + 7):
        d["items"][0]["unitPrice"] = 5000 + n
        C.reconcile_in_memory(d, NOW, "c", "put", enabled=True)
    assert len(d["approval"]["changeLog"]) == C.LOG_CAP and d["approval"]["contentRev"] == C.LOG_CAP + 7
    assert d["approval"]["changeLog"][-1]["rev"] == C.LOG_CAP + 7


def test_actor_forms_and_only_approval_is_mutated():
    for actor, want in (({"username": "u", "display_name": "名字"}, "名字"), ({"username": "u"}, "u"), ("zed", "zed"), (None, "system")):
        d = _doc(signed=1)
        _edit(d)
        rest_before = {k: copy.deepcopy(v) for k, v in d.items() if k != "approval"}
        C.reconcile_in_memory(d, NOW, actor, "put", enabled=True)
        assert d["approval"]["changeLog"][0]["by"] == want
        assert {k: v for k, v in d.items() if k != "approval"} == rest_before, "只改 approval"


# ── 旗標讀取：讀不到取開 ───────────────────────────────────────────────────
class _Conn:
    def close(self):
        pass


def _patch_flag(monkeypatch, value=None, exc=None):
    import helpers.settings_strict as SS

    def fake(conn, group, field):
        assert (group, field) == (C.FLAG_GROUP, C.FLAG_FIELD)
        if exc:
            raise exc
        return value
    monkeypatch.setattr(SS, "strict_value", fake)


@pytest.mark.parametrize("value,want", [(0, False), (1, True), (False, False), (True, True), ("0", False), ("1", True), (0.0, False)])
def test_flag_values(monkeypatch, value, want):
    _patch_flag(monkeypatch, value)
    assert C.reconfirm_enabled(_Conn()) is want


@pytest.mark.parametrize("value", [None, 2, -1, "yes", "", [], {}, 0.5])
def test_flag_garbage_means_on(monkeypatch, value):
    _patch_flag(monkeypatch, value)
    assert C.reconfirm_enabled(_Conn()) is True


@pytest.mark.parametrize("exc", [RuntimeError("db"), KeyError("reconfirm_on_change"), ValueError("格式"), OSError("locked")])
def test_flag_unreadable_means_on(monkeypatch, exc):
    _patch_flag(monkeypatch, exc=exc)
    assert C.reconfirm_enabled(_Conn()) is True


def test_flag_not_registered_yet_means_on_with_a_real_failing_connection():
    assert C.reconfirm_enabled(object()) is True                               # 欄位未註冊／連線壞 ⇒ 開


def test_reconcile_reads_flag_only_when_needed_and_uses_it(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "reconfirm_enabled", lambda conn=None: calls.append(1) or False)
    d = _doc(signed=1)
    assert C.reconcile_in_memory(d, NOW, "x", "put") == (False, []) and calls == [], "指紋沒變、沒有過期條目 ⇒ 不讀旗標"
    _edit(d)
    C.reconcile_in_memory(d, NOW, "x", "put")
    assert calls == [1] and d["approval"]["shadowLog"] and _entry(d, "b")["status"] == "approved", "旗標關 ⇒ 影子"
    monkeypatch.setattr(C, "reconfirm_enabled", lambda conn=None: True)
    d2 = _doc(signed=1)
    _edit(d2)
    C.reconcile_in_memory(d2, NOW, "x", "put")
    assert _entry(d2, "b")["status"] == "pending"


def test_unreadable_flag_inside_reconcile_defaults_to_invalidate(monkeypatch):
    _patch_flag(monkeypatch, exc=RuntimeError("db down"))
    monkeypatch.setattr("db.get_db", lambda *a, **k: _Conn(), raising=False)
    d = _doc(signed=1)
    _edit(d)
    C.reconcile_in_memory(d, NOW, "c", "put")
    assert _entry(d, "b")["status"] == "pending" and d["approval"]["reviewRounds"] == 1


def test_no_call_sites_in_s3a():
    """S3a 不接線：別的檔不得 import／呼叫 reconcile_in_memory（S3b 才接；接線時請同步改這題）。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if "reconcile_in_memory" in p.read_text(encoding="utf-8", errors="ignore")
            and p.name not in ("content_fp.py", pathlib.Path(__file__).name) and "__pycache__" not in str(p)]
    assert hits == [], hits
