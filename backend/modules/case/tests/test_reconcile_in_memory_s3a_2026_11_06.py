# -*- coding: utf-8 -*-
"""簽核二擇一 S3a：`content_fp.reconcile_in_memory`／`reconfirm_enabled`（純函式；沒有呼叫端、不碰資料庫）。
規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §K2。"""
import copy

import pytest

from modules.case import content_fp as C

NOW = "2026-11-06T23:00:00"
L = C.REVIEW_ROUNDS_LIMIT


def _rc(data, now, actor, source, **kw):
    """測試用：預設 status＝資料庫列狀態「待審核」；`enabled` 必傳（沿用 C.reconcile_in_memory 的簽名）。"""
    kw.setdefault("status", "待審核")
    return C.reconcile_in_memory(data, now, actor, source, **kw)


def _doc(tiers=(("b",), ("c",), ("d",)), signed=0, status="待審核", requested_by="a"):
    """報價單：前 `signed` 層已簽（用 S1 的 stamp_signed 蓋章）。"""
    data = {"quoteNo": "MQ-1", "customerName": "甲", "items": [{"id": "i1", "qty": 1, "unitPrice": 1000}],
            "tot": {"total": 1050}, "caseRecord": {"payment": {"paid": 0}}, "status": status}
    appr = {"status": "pending", "requestedBy": requested_by, "currentTier": 0,
            "tiers": [{"approvers": [{"username": u, "displayName": u.upper(), "status": "pending"} for u in t]} for t in tiers]}
    data["approval"] = appr
    _rc(data, NOW, "system", "submit", enabled=True)          # 送審建立基準
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
@pytest.mark.parametrize("status", ["草稿", "已核准", "已拒絕", "已作廢", "", None])
def test_not_pending_status_is_untouched(status):
    d = _doc(signed=1)
    _edit(d)
    before = copy.deepcopy(d)
    assert C.reconcile_in_memory(d, NOW, "c", "put", status=status, enabled=True) == (False, [])
    assert d == before


def test_no_tiers_or_no_approval_is_untouched():
    for d in ({"items": []}, {"approval": None}, {"approval": {"tiers": []}}, {"approval": "x"}, None):
        before = copy.deepcopy(d)
        assert _rc(d, NOW, "c", "put", enabled=True) == (False, [])
        assert d == before


def test_status_is_fail_closed_stale_data_status_is_never_trusted():
    """K 審 1：沒傳 status ⇒ 不動，不去猜 data["status"]／approval.status（單已核准、data_json 卻還寫著待審核）。"""
    d = _doc(signed=1)
    _edit(d)
    assert d["status"] == "待審核" and d["approval"]["status"] == "pending"          # 兩處都「像」待審核
    before = copy.deepcopy(d)
    assert C.reconcile_in_memory(d, NOW, "c", "put", enabled=True) == (False, [])    # 沒傳 status
    assert d == before and _entry(d, "b")["status"] == "approved"
    assert C.reconcile_in_memory(d, NOW, "c", "put", status="已核准", enabled=True) == (False, [])   # 資料庫列說已核准
    assert d == before
    assert C.reconcile_in_memory(copy.deepcopy(d), NOW, "c", "put", status="簽核中", enabled=True)[0] is True


@pytest.mark.parametrize("appr_status", ["approved", "rejected"])
def test_approval_status_final_is_noop_even_if_status_says_pending(appr_status):
    """K 審 1 雙保險：approval.status 是 approved／rejected 時，不管傳進來的 status 是什麼都不動。"""
    d = _doc(signed=1)
    _edit(d)
    d["approval"]["status"] = appr_status
    before = copy.deepcopy(d)
    assert _rc(d, NOW, "c", "put", enabled=True) == (False, [])
    assert d == before


def test_enabled_is_required_keyword():
    d = _doc(signed=1)
    with pytest.raises(TypeError):
        C.reconcile_in_memory(d, NOW, "c", "put", status="待審核")
    with pytest.raises(TypeError):
        C.reconcile_in_memory(d, NOW, "c", "put", "待審核", True)                      # 也不能用位置參數


# ── 舊單／剛送審：靜默設基準 ───────────────────────────────────────────────
def test_missing_contentfp_sets_baseline_silently_even_with_signed_entries():
    d = _doc(signed=2)
    d["approval"].pop("contentFp"), d["approval"].pop("keyHashes"), d["approval"].pop("baselineSetBy")
    for u in ("b", "c"):                                                       # 真正的舊單：S1 上線前簽的，條目也沒有 signedFp（stamp_signed 一定同時設 contentFp，不會只缺基準）
        _entry(d, u).pop("signedFp"), _entry(d, u).pop("signedKeyHashes")
    _edit(d)                                                                   # 舊單：沒基準時內容已經跟簽的時候不同，也不算異動
    ch, notices = _rc(d, NOW, "c", "approve", enabled=True)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["contentFp"] == C.content_fingerprint(d) and a["keyHashes"] == C.key_hashes(d) and a["baselineSetBy"] == "approve"
    assert _entry(d, "b")["status"] == "approved" and "reconfirm" not in _entry(d, "b")
    assert not a.get("contentRev") and not a.get("changeLog") and not a.get("reviewRounds")
    assert _rc(d, NOW, "c", "approve", enabled=True) == (False, [])


def test_submit_baseline_is_set_by_source():
    d = _doc()
    assert d["approval"]["baselineSetBy"] == "submit" and d["approval"]["contentFp"] == C.content_fingerprint(d)


# ── 冪等 ───────────────────────────────────────────────────────────────────
def test_same_fingerprint_is_noop_and_idempotent_after_invalidation():
    d = _doc(signed=2)
    assert _rc(d, NOW, "x", "put", enabled=True) == (False, [])
    _edit(d)
    assert _rc(d, NOW, "c", "put", enabled=True)[0] is True
    snap = copy.deepcopy(d)
    for _ in range(3):
        assert _rc(d, NOW, "c", "put", enabled=True) == (False, [])
    assert d == snap


def test_excluded_keys_do_not_trigger():
    d = _doc(signed=1)
    d["statusLog"] = [{"x": 1}]
    d["editHistory"] = [{"y": 1}]
    d["approval"]["reasons"] = ["x"]
    assert _rc(d, NOW, "x", "put", enabled=True) == (False, [])
    assert _entry(d, "b")["status"] == "approved"


# ── 旗標開：作廢 ───────────────────────────────────────────────────────────
def test_invalidate_signed_entry_and_all_bookkeeping():
    d = _doc(signed=1)                                                         # B 已簽，輪到 C
    old_fp = d["approval"]["contentFp"]
    _edit(d)                                                                   # C 編輯
    ch, notices = _rc(d, NOW, {"username": "c", "display_name": "小C"}, "put", enabled=True)
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
    ch, notices = _rc(d, NOW, "d", "put", enabled=True)
    assert ch and _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"
    assert _entry(d, "b")["reconfirm"] and _entry(d, "c")["reconfirm"]
    assert d["approval"]["currentTier"] == 0 and d["approval"]["reviewRounds"] == 1, "兩層一起作廢只算 1 輪"
    assert next(n for n in notices if n["type"] == "approval_reconfirm")["to"] == ["b", "c"]


def test_entries_without_signedfp_are_never_invalidated():
    d = _doc(signed=2)
    for u in ("b", "c"):
        _entry(d, u).pop("signedFp"), _entry(d, u).pop("signedKeyHashes")       # S1 上線前簽的舊條目
    _edit(d)
    ch, notices = _rc(d, NOW, "d", "put", enabled=True)
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
    ch, notices = _rc(d, NOW, "c", "put", enabled=True)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["contentFp"] == C.content_fingerprint(d) != old_fp, "基準追上最新內容"
    assert not a.get("reviewRounds"), "不是複查輪次"
    assert a["contentRev"] == 1 and a["changeLog"][0]["invalidated"] == []
    assert _rc(d, NOW, "c", "put", enabled=True) == (False, [])


# ── 影子模式 ───────────────────────────────────────────────────────────────
def test_shadow_mode_only_logs_and_never_touches_entries():
    d = _doc(signed=2)
    _edit(d)
    entries_before = copy.deepcopy(d["approval"]["tiers"])
    cur_before, tier_before = d["approval"]["currentTier"], d["approval"]["currentTier"]
    ch, notices = _rc(d, NOW, {"username": "d"}, "material", enabled=False)
    a = d["approval"]
    assert ch is True and notices == []
    assert a["tiers"] == entries_before and a["currentTier"] == tier_before == cur_before
    assert a["shadowLog"] == [{"at": NOW, "blocks": ["items"], "by": "d", "source": "material", "fp": C.content_fingerprint(d), "wouldInvalidate": ["b", "c"]}]
    assert not a.get("contentRev") and not a.get("changeLog") and not a.get("reviewRounds")
    assert a["contentFp"] == C.content_fingerprint(d)
    assert _rc(d, NOW, "d", "material", enabled=False) == (False, []), "冪等：不重複記"
    assert len(a["shadowLog"]) == 1


def test_shadow_with_nobody_signed_logs_empty_would_invalidate():
    d = _doc(signed=0)
    _edit(d)
    _rc(d, NOW, "c", "put", enabled=False)
    assert d["approval"]["shadowLog"][0]["wouldInvalidate"] == []


# ── 需求 5：影子 N 次後切到開，一次補追只算 1 輪 ───────────────────────────
def test_shadow_then_on_catches_up_all_stale_entries_as_one_round():
    d = _doc(signed=2)
    for price in (1100, 1200, 1300):                                           # 影子期間內容被改 3 次
        d["items"][0]["unitPrice"] = price
        _rc(d, NOW, "x", "put", enabled=False)
    a = d["approval"]
    assert len(a["shadowLog"]) == 3 and _entry(d, "b")["status"] == "approved" and not a.get("reviewRounds")
    assert _rc(copy.deepcopy(d), NOW, "x", "put", enabled=False) == (False, []), "旗標仍關：過期條目不動、不重複記"
    # 旗標切到開；內容沒有再變——下一次 reconcile 就要補追
    ch, notices = _rc(d, NOW, "sys", "approve", enabled=True)
    assert ch is True
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"
    assert a["reviewRounds"] == 1, "只 +1，不是補記 3 輪"
    assert a["contentRev"] == 1 and a["currentTier"] == 0
    log = a["changeLog"][-1]
    assert log["catchUp"] is True and log["invalidated"] == ["b", "c"] and log["blocks"] == ["items"]
    assert any(n["type"] == "approval_reconfirm" and n["to"] == ["b", "c"] for n in notices)
    assert _rc(d, NOW, "sys", "approve", enabled=True) == (False, []), "補追之後冪等"


def test_shadow_then_on_with_a_new_change_is_also_one_round():
    d = _doc(signed=2)
    for price in (1100, 1200):
        d["items"][0]["unitPrice"] = price
        _rc(d, NOW, "x", "put", enabled=False)
    d["items"][0]["unitPrice"] = 1300
    _rc(d, NOW, "x", "put", enabled=True)
    assert d["approval"]["reviewRounds"] == 1 and _entry(d, "b")["status"] == "pending" and _entry(d, "c")["status"] == "pending"


# ── 輪次上限 ───────────────────────────────────────────────────────────────
def test_round_limit_suspends_instead_of_invalidating_and_notifies_superadmin_once():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = _rc(d, NOW, "c", "put", enabled=True)
    a = d["approval"]
    assert ch and a["reconfirmSuspended"] is True and a["reviewRounds"] == L
    assert _entry(d, "b")["status"] == "approved" and "reconfirm" not in _entry(d, "b"), "不作廢"
    assert [n["type"] for n in notices] == ["approval_reconfirm_suspended"] and notices[0]["to"] == [{"role": "superadmin"}] and "最高管理者" in notices[0]["text"]
    assert a["changeLog"][-1]["suspended"] is True and a["contentFp"] == C.content_fingerprint(d)
    d["items"][0]["unitPrice"] = 3000                                          # 之後再改：仍不作廢、不再重複通知
    ch, notices = _rc(d, NOW, "c", "put", enabled=True)
    assert ch and notices == [] and _entry(d, "b")["status"] == "approved"


def test_round_limit_boundary_limit_minus_one_still_invalidates():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L - 1
    _edit(d)
    _rc(d, NOW, "c", "put", enabled=True)
    assert d["approval"]["reviewRounds"] == L and _entry(d, "b")["status"] == "pending" and not d["approval"].get("reconfirmSuspended")


def test_limit_does_not_apply_in_shadow_mode():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L
    _edit(d)
    _rc(d, NOW, "c", "put", enabled=False)
    assert not d["approval"].get("reconfirmSuspended") and d["approval"]["shadowLog"]


def test_five_real_rounds_then_sixth_is_suspended():
    d = _doc(signed=1)
    for n in range(L):
        d["items"][0]["unitPrice"] = 2000 + n
        _rc(d, NOW, "c", "put", enabled=True)
        e = _entry(d, "b")                                                     # B 複查後再簽（S1 蓋章），輪到 C
        was = C.pending_entries(d["approval"])
        e["status"], e["approvedAt"] = "approved", NOW
        C.stamp_signed(d["approval"], was, d)
        d["approval"]["currentTier"] = 1
    assert d["approval"]["reviewRounds"] == L
    d["items"][0]["unitPrice"] = 9999
    _rc(d, NOW, "c", "put", enabled=True)
    assert d["approval"]["reconfirmSuspended"] is True and _entry(d, "b")["status"] == "approved"


# ── review-edit：複查者編輯後的簽視為新版（H9-①）─────────────────────────
def test_review_edit_by_reconfirming_signer_resigns_new_version_and_others_pending():
    d = _doc(signed=2)                                                         # B、C 已簽，D 待簽
    _edit(d, price=1500)
    _rc(d, NOW, "d", "put", enabled=True)                    # D 改了 ⇒ B、C 都 pending＋reconfirm
    assert _entry(d, "b")["reconfirm"] and _entry(d, "c")["reconfirm"]
    d["items"][0]["unitPrice"] = 1600                                          # B 複查時自己也改（review-edit）
    ch, notices = _rc(d, NOW, {"username": "b", "display_name": "B"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    b, c = _entry(d, "b"), _entry(d, "c")
    assert ch and b["status"] == "approved" and b["signedFp"] == C.content_fingerprint(d) and "reconfirm" not in b and b["approvedAt"] == NOW
    assert c["status"] == "pending" and c["reconfirm"] is True
    assert d["approval"]["currentTier"] == 1, "第一個未簽層＝C"
    assert d["approval"]["changeLog"][-1]["resigned"] == ["b"]


def test_review_edit_by_stale_approved_entry_is_resigned_not_invalidated():
    d = _doc(signed=1)
    _edit(d)
    ch, notices = _rc(d, NOW, {"username": "b"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    assert _entry(d, "b")["status"] == "approved" and _entry(d, "b")["signedFp"] == C.content_fingerprint(d)
    assert not d["approval"].get("reviewRounds"), "沒有人被作廢 ⇒ 不算一輪"
    assert not [n for n in notices if n["type"] == "approval_reconfirm"]


def test_review_edit_by_first_time_pending_signer_is_not_auto_signed():
    d = _doc(signed=1)                                                         # B 已簽，C 首次待簽
    _edit(d)
    _rc(d, NOW, {"username": "c"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    c = _entry(d, "c")
    assert c["status"] == "pending" and "signedFp" not in c, "C 仍須自己再按一次核准"
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "b")["reconfirm"]


def test_non_review_edit_source_never_resigns_the_actor():
    d = _doc(signed=1)
    _edit(d)
    _rc(d, NOW, {"username": "b"}, "put", enabled=True)
    assert _entry(d, "b")["status"] == "pending" and _entry(d, "b")["reconfirm"]


# ── 區塊名、記錄上限、其他 ────────────────────────────────────────────────
def test_changed_blocks_include_case_record_second_level_and_unknown_when_no_old_hashes():
    d = _doc(signed=1)
    d["caseRecord"]["payment"]["paid"] = 500
    _rc(d, NOW, "f", "payment", enabled=True)
    assert d["approval"]["changeLog"][0]["blocks"] == ["caseRecord.payment"]
    d2 = _doc(signed=1)
    d2["approval"].pop("keyHashes")
    for a in d2["approval"]["tiers"][0]["approvers"]:
        a.pop("signedKeyHashes")
    _edit(d2)
    _rc(d2, NOW, "f", "put", enabled=True)
    log = d2["approval"]["changeLog"][0]
    assert log["blocks"] == [] and log["blocksUnknown"] is True


def test_logs_are_capped():
    d = _doc(signed=0)
    for n in range(C.LOG_CAP + 7):
        d["items"][0]["unitPrice"] = 5000 + n
        _rc(d, NOW, "c", "put", enabled=True)
    assert len(d["approval"]["changeLog"]) == C.LOG_CAP and d["approval"]["contentRev"] == C.LOG_CAP + 7
    assert d["approval"]["changeLog"][-1]["rev"] == C.LOG_CAP + 7


def test_actor_forms_and_only_approval_is_mutated():
    for actor, want in (({"username": "u", "display_name": "名字"}, "名字"), ({"username": "u"}, "u"), ("zed", "zed"), (None, "system")):
        d = _doc(signed=1)
        _edit(d)
        rest_before = {k: copy.deepcopy(v) for k, v in d.items() if k != "approval"}
        _rc(d, NOW, actor, "put", enabled=True)
        assert d["approval"]["changeLog"][0]["by"] == want
        assert {k: v for k, v in d.items() if k != "approval"} == rest_before, "只改 approval"


# ── 三態旗標 reconfirm_mode：讀不到取 on ───────────────────────────────────
class _Conn:
    def close(self):
        pass


def _patch_mode(monkeypatch, value=None, exc=None):
    import helpers.settings_strict as SS

    def fake(conn, group, field):
        assert (group, field) == (C.MODE_GROUP, C.MODE_FIELD) == ("quote_approval", "reconfirm_mode")
        if exc:
            raise exc
        return value
    monkeypatch.setattr(SS, "strict_value", fake)


@pytest.mark.parametrize("value,want", [("off", "off"), ("shadow", "shadow"), ("on", "on"), (" Shadow ", "shadow"), ("OFF", "off")])
def test_mode_values(monkeypatch, value, want):
    _patch_mode(monkeypatch, value)
    assert C.reconfirm_mode(_Conn()) == want


@pytest.mark.parametrize("value", [None, 3, -1, 1.5, 2.5, True, False, "yes", "", "true", [], {}, "0"])      # S3b：設定值是整數代碼 0／1／2，其餘一律是垃圾
def test_mode_garbage_means_on(monkeypatch, value):
    """S3b 改動：0／1 不再是垃圾（設定中心的整數代碼 0＝off、1＝shadow、2＝on）；超出範圍、小數、布林、字串數字仍取 on。"""
    _patch_mode(monkeypatch, value)
    assert C.reconfirm_mode(_Conn()) == "on"


@pytest.mark.parametrize("value,want", [(0, "off"), (1, "shadow"), (2, "on"), (0.0, "off"), (1.0, "shadow"), (2.0, "on")])
def test_mode_int_codes_from_the_settings_center(monkeypatch, value, want):
    _patch_mode(monkeypatch, value)
    assert C.reconfirm_mode(_Conn()) == want


@pytest.mark.parametrize("exc", [RuntimeError("db"), KeyError("reconfirm_mode"), ValueError("格式"), OSError("locked")])
def test_mode_unreadable_means_on(monkeypatch, exc):
    _patch_mode(monkeypatch, exc=exc)
    assert C.reconfirm_mode(_Conn()) == "on"


def test_mode_field_not_registered_yet_means_on_with_a_real_failing_connection():
    assert C.reconfirm_mode(object()) == "on"


def test_old_boolean_flag_name_is_gone():
    assert not hasattr(C, "reconfirm_enabled") and not hasattr(C, "FLAG_FIELD")


def test_reconcile_is_pure_never_reads_settings_or_db(monkeypatch):
    """K 審小項：純函式裡不藏資料庫存取；reconfirm_mode 只給外層呼叫。"""
    import db

    def boom(*a, **k):
        raise AssertionError("reconcile 不可讀旗標／開連線")
    monkeypatch.setattr(C, "reconfirm_mode", boom)
    monkeypatch.setattr(db, "get_db", boom)
    d = _doc(signed=2)
    _edit(d)
    assert _rc(d, NOW, "c", "put", enabled=True)[0] is True
    d2 = _doc(signed=2)
    _edit(d2)
    assert _rc(d2, NOW, "c", "put", enabled=False)[0] is True


# ── K 審必修 2：輪次上限只在「有可作廢條目」時才暫停 ─────────────────────────
def test_at_limit_but_nothing_to_invalidate_does_not_suspend_or_notify():
    d = _doc(signed=0)                                                         # 還沒人簽
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = _rc(d, NOW, "c", "put", enabled=True)
    a = d["approval"]
    assert ch is True and notices == [] and not a.get("reconfirmSuspended")
    assert a["reviewRounds"] == L and a["contentRev"] == 1 and a["contentFp"] == C.content_fingerprint(d)


def test_at_limit_old_entries_without_signedfp_do_not_suspend():
    d = _doc(signed=1)
    _entry(d, "b").pop("signedFp"), _entry(d, "b").pop("signedKeyHashes")
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = _rc(d, NOW, "c", "put", enabled=True)
    assert ch and notices == [] and not d["approval"].get("reconfirmSuspended") and _entry(d, "b")["status"] == "approved"


def test_at_limit_review_edit_resigning_only_stale_entry_is_not_suspended():
    d = _doc(signed=1)                                                         # 只有 B 過期，B 自己編輯重簽 ⇒ 沒有別人要作廢
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = _rc(d, NOW, {"username": "b"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    assert ch and notices == [] and not d["approval"].get("reconfirmSuspended")
    assert _entry(d, "b")["status"] == "approved" and _entry(d, "b")["signedFp"] == C.content_fingerprint(d)


def test_at_limit_with_others_to_invalidate_suspends_and_does_not_resign_actor():
    d = _doc(signed=2)                                                         # B、C 都過期；B 編輯重簽，但 C 要作廢而輪次已滿
    d["approval"]["reviewRounds"] = L
    _edit(d)
    ch, notices = _rc(d, NOW, {"username": "b"}, C.SOURCE_REVIEW_EDIT, enabled=True)
    assert ch and d["approval"]["reconfirmSuspended"] is True
    assert [n["type"] for n in notices] == ["approval_reconfirm_suspended"]
    assert _entry(d, "b")["status"] == "approved" and _entry(d, "b")["signedFp"] != C.content_fingerprint(d), "暫停時不動任何條目（含編輯者）"
    assert _entry(d, "c")["status"] == "approved"


# ── K 審必修 3：effective_approval 看模式與暫停 ─────────────────────────────
def test_effective_approval_respects_mode_and_suspension():
    d = _doc(signed=2)
    _edit(d)
    appr, stale = C.effective_approval(d, enabled=True)
    assert stale is True and appr["tiers"][0]["approvers"][0]["status"] == "pending" and appr["currentTier"] == 0
    appr, stale = C.effective_approval(d, enabled=False)                        # 影子：不推導
    assert stale is False and appr["tiers"][0]["approvers"][0]["status"] == "approved"
    d["approval"]["reconfirmSuspended"] = True                                  # 暫停（欄位）：不推導
    assert C.effective_approval(d, enabled=True)[1] is False
    assert C.effective_approval(d, enabled=True, suspended=False)[1] is True, "明確傳 suspended 優先"
    d["approval"]["reconfirmSuspended"] = False
    assert C.effective_approval(d, enabled=True, suspended=True)[1] is False
    assert d["approval"]["tiers"][0]["approvers"][0]["status"] == "approved", "純推導：不改傳入的資料"


def test_effective_approval_requires_enabled_keyword():
    with pytest.raises(TypeError):
        C.effective_approval(_doc(signed=1))


# ── 小項：stamp_signed 寫 approval.keyHashes ───────────────────────────────
def test_stamp_signed_writes_approval_key_hashes_so_old_changes_are_not_reported_again():
    d = _doc(signed=1)                                                         # B 簽在 v1
    d["approval"].pop("keyHashes")                                              # 舊資料：approval 層沒有 keyHashes，只有條目上有 signedKeyHashes（v1）
    d["tot"]["total"] = 2100                                                    # v2：tot 變了（先不 reconcile，直接讓 C 簽）
    was = C.pending_entries(d["approval"])
    _entry(d, "c")["status"] = "approved"
    C.stamp_signed(d["approval"], was, d)
    assert d["approval"]["keyHashes"] == C.key_hashes(d), "stamp_signed 要更新 approval.keyHashes"
    d["items"][0]["unitPrice"] = 5000                                           # v3：只動 items
    _rc(d, NOW, "d", "put", enabled=True)
    assert d["approval"]["changeLog"][-1]["blocks"] == ["items"], "不重複報 v1→v2 的 tot"


# ── 小項：notices 型別一致、actor 為 None 的措辭 ────────────────────────────
def test_notices_to_is_always_a_list_with_str_or_role_dict():
    d = _doc(signed=1)
    d["approval"]["reviewRounds"] = L - 1
    _edit(d)
    _, n1 = _rc(d, NOW, "c", "put", enabled=True)                               # 第 L 輪：作廢 B
    was = C.pending_entries(d["approval"])                                      # B 複查再簽
    _entry(d, "b")["status"] = "approved"
    C.stamp_signed(d["approval"], was, d)
    d["items"][0]["unitPrice"] = 8888                                           # 再改：輪次已滿 ⇒ 暫停
    _, n2 = _rc(d, NOW, "c", "put", enabled=True)
    assert n1 and n2 and all(isinstance(n["to"], list) and n["to"] for n in n1 + n2)
    assert all(isinstance(x, str) for n in n1 for x in n["to"])
    assert n2[0]["type"] == "approval_reconfirm_suspended" and n2[0]["to"] == [{"role": "superadmin"}]


@pytest.mark.parametrize("source,label", [("put", "儲存報價單"), ("material", "材料申請"), ("something-new", "something-new")])
def test_system_actor_text(source, label):
    d = _doc(signed=1)
    _edit(d)
    ch, notices = _rc(d, NOW, None, source, enabled=True)
    txt = next(n for n in notices if n["type"] == "approval_reconfirm")["text"]
    assert f"系統（{label}）" in txt and "system" not in txt
    assert d["approval"]["changeLog"][-1]["by"] == "system"


def test_no_call_sites_in_s3a():
    """S3b 接線之後：`reconcile_in_memory` 只准 `content_fp.reconcile_txn` 一處呼叫（其他檔不得 import／呼叫；測試檔不算）。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if "reconcile_in_memory" in p.read_text(encoding="utf-8", errors="ignore")
            and p.name != "content_fp.py" and "tests" not in p.relative_to(root).parts and "__pycache__" not in str(p)]
    assert hits == [], hits
    import ast
    tree = ast.parse((root / "case" / "content_fp.py").read_text(encoding="utf-8"))
    callers = sorted(f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                     for n in ast.walk(f) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "reconcile_in_memory")
    assert callers == ["reconcile_txn"], callers
