# -*- coding: utf-8 -*-
"""簽核二擇一 S1：內容指紋／核准綁版本（`expectedFp`）／signedFp 蓋章／舊單相容／`rebaseline_fingerprint`。
規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §H1、§H3、§I。**不改任何簽核流向**（S3 才有 reconcile／作廢）。"""
import copy
import json

import pytest

from modules.case import content_fp as C
from tests._requires import requires_module

pytestmark = requires_module("case", "S1 打 M01 的報價單簽核端點")

NO = "MQ-202611-801"


# ── 純函式：指紋 ───────────────────────────────────────────────────────────────────────────
def _doc():
    return {"quoteNo": NO, "customerName": "甲", "items": [{"id": "i1", "qty": 2, "unitPrice": 100.0}],
            "tot": {"total": 210, "pretax": 200}, "caseRecord": {"roles": {"sales": "a"}, "payment": {"paid": 0}},
            "approval": {"tiers": []}, "statusLog": [], "editHistory": [], "status": "待審核"}


def test_fingerprint_shape_and_determinism():
    fp = C.content_fingerprint(_doc())
    assert fp.startswith(C.FP_VERSION + ":") and len(fp) == len(C.FP_VERSION) + 1 + 32
    d2 = {k: _doc()[k] for k in reversed(list(_doc()))}          # 鍵順序不同
    assert C.content_fingerprint(d2) == fp


def test_canonical_form_none_equals_missing_and_whole_floats_equal_ints():
    a, b = _doc(), _doc()
    b["items"][0]["unitPrice"] = 100                              # 100.0 經瀏覽器 JSON 來回變 100
    b["customerNote"] = None                                      # None＝缺鍵
    b["caseRecord"]["payment"]["memo"] = None
    assert C.content_fingerprint(a) == C.content_fingerprint(b)
    b["items"][0]["unitPrice"] = 100.5
    assert C.content_fingerprint(a) != C.content_fingerprint(b)


@pytest.mark.parametrize("key", sorted(C.EXCLUDED_KEYS))
def test_each_excluded_key_does_not_move_the_fingerprint(key):
    a, b = _doc(), _doc()
    b[key] = {"x": 1} if key not in ("status", "updatedAt", "dealWonAt", "altPickedAt", "altPickedBy", "googleCalendarEventId") else "changed"
    assert C.content_fingerprint(a) == C.content_fingerprint(b), key


@pytest.mark.parametrize("mutate", [
    lambda d: d["items"][0].__setitem__("qty", 3),
    lambda d: d["tot"].__setitem__("total", 211),
    lambda d: d["caseRecord"]["payment"].__setitem__("paid", 1),     # 「更寬」：案件記錄／款項也算內容（H0-1）
    lambda d: d.__setitem__("dealTag", "已成案"),                    # I4：dealTag 從嚴算內容
    lambda d: d.__setitem__("rejection", {"by": "x"}),
    lambda d: d.__setitem__("somethingBrandNew", 1),                 # 未知鍵一律算內容
    lambda d: d.__setitem__("altPicks", {"g": "m1"}),                # altPicks 是內容（altPickedAt／By 才是簿記）
])
def test_any_content_or_unknown_key_moves_the_fingerprint(mutate):
    a, b = _doc(), _doc()
    mutate(b)
    assert C.content_fingerprint(a) != C.content_fingerprint(b)


def test_mutation_control_exclusion_list_really_drives_the_result(monkeypatch):
    """突變控制：把 items 搬進排除清單，改 items 就不再動指紋（證明上面的測試不是靠巧合通過）。"""
    a, b = _doc(), _doc()
    b["items"][0]["qty"] = 99
    assert C.content_fingerprint(a) != C.content_fingerprint(b)
    monkeypatch.setattr(C, "EXCLUDED_KEYS", C.EXCLUDED_KEYS | {"items"})
    assert C.content_fingerprint(a) == C.content_fingerprint(b)


def test_input_is_never_mutated_and_non_dict_is_rejected():
    d = _doc()
    snap = copy.deepcopy(d)
    C.content_fingerprint(d); C.key_hashes(d)
    assert d == snap
    with pytest.raises(TypeError):
        C.content_fingerprint([])


def test_key_hashes_and_changed_blocks_use_case_record_second_level():
    a, b = _doc(), _doc()
    b["caseRecord"]["payment"]["paid"] = 5
    ha, hb = C.key_hashes(a), C.key_hashes(b)
    assert "caseRecord.payment" in ha and "caseRecord" not in ha and "approval" not in ha and "status" not in ha
    assert C.changed_blocks(ha, hb) == ["caseRecord.payment"]
    b["items"].append({"id": "i2"})
    assert C.changed_blocks(ha, C.key_hashes(b)) == ["caseRecord.payment", "items"]
    assert C.changed_blocks(None, {}) == []


# ── 純函式：蓋章與推導 ─────────────────────────────────────────────────────────────────────
def _approval(*tiers):
    return {"currentTier": 0, "tiers": [{"approvers": [dict(a) for a in t]} for t in tiers]}


def test_stamp_signed_stamps_only_entries_signed_in_this_call():
    d = _doc()
    d["approval"] = _approval([{"username": "b", "status": "approved", "approvedAt": "t0"}],     # S1 之前簽的舊條目（沒有 signedFp）
                              [{"username": "c", "status": "pending"}, {"username": "e", "status": "pending"}])
    appr = d["approval"]
    was = C.pending_entries(appr)
    assert [a["username"] for a in was] == ["c", "e"]
    appr["tiers"][1]["approvers"][0]["status"] = "approved"                                    # c 這次簽了
    stamped = C.stamp_signed(appr, was, d)
    assert [a["username"] for a in stamped] == ["c"]
    fp = C.content_fingerprint(d)
    c = appr["tiers"][1]["approvers"][0]
    assert c["signedFp"] == fp and c["signedKeyHashes"] == C.key_hashes(d) and appr["contentFp"] == fp
    assert "signedFp" not in appr["tiers"][0]["approvers"][0], "舊條目不得被追認"
    assert "signedFp" not in appr["tiers"][1]["approvers"][1], "還沒簽的不蓋"
    assert C.content_fingerprint(d) == fp, "蓋章只動 approval（排除鍵），內容指紋不變"


def test_stamp_signed_covers_cascade_entries():
    d = _doc()
    d["approval"] = _approval([{"username": "u", "status": "pending"}], [{"username": "u", "status": "pending"}])
    was = C.pending_entries(d["approval"])
    for t in d["approval"]["tiers"]:
        t["approvers"][0]["status"] = "approved"
    assert len(C.stamp_signed(d["approval"], was, d)) == 2


def test_effective_approval_is_pure_and_derives_reconfirm():
    d = _doc()
    d["approval"] = _approval([{"username": "b", "status": "approved", "approvedAt": "t1"}],
                              [{"username": "c", "status": "pending"}])
    d["approval"]["currentTier"] = 1
    C.stamp_signed(d["approval"], [d["approval"]["tiers"][0]["approvers"][0]], d)             # b 簽在目前版本
    snap = copy.deepcopy(d)
    appr, stale = C.effective_approval(d)
    assert not stale and appr == d["approval"]                                                 # 內容沒變 ⇒ 原樣
    d["items"][0]["qty"] = 9                                                                   # C 之類的人改了內容
    snap = copy.deepcopy(d)
    appr, stale = C.effective_approval(d)
    assert stale and d == snap, "推導不得改傳入資料"
    b = appr["tiers"][0]["approvers"][0]
    assert b["status"] == "pending" and b["reconfirm"] is True and b["prevApprovedAt"] == "t1" and "approvedAt" not in b
    assert appr["currentTier"] == 0, "currentTier 退回第一個有未簽條目的層"
    d["status"] = "簽核中"; d["statusLog"] = [{"x": 1}]                                       # 只動簿記 ⇒ 不過期
    d["items"][0]["qty"] = 2
    assert C.effective_approval(d)[1] is False


def test_legacy_entries_without_signed_fp_are_never_stale():
    d = _doc()
    d["approval"] = _approval([{"username": "b", "status": "approved", "approvedAt": "t1"}])
    d["items"][0]["qty"] = 12345
    appr, stale = C.effective_approval(d)
    assert not stale and appr["tiers"][0]["approvers"][0]["status"] == "approved"


# ── HTTP：核准綁版本 ──────────────────────────────────────────────────────────────────────
def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(client, make_user, tiers=1, status="待審核", doc=None):
    import db
    names = []
    hs = []
    for i in range(tiers):
        n, pw = make_user(username="fp_ap%d" % i, role="admin")
        names.append(n); hs.append(_login(client, n, pw))
    req, _ = make_user(username="fp_req", role="admin")
    appr = {"requestedBy": req, "requestedByDisplay": req, "requestedAt": "2026-11-06T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": n, "displayName": n, "status": "pending"}]} for n in names]}
    data = dict(doc or _doc(), approval=appr, quoteNo=NO)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (NO, status, "甲", "專案", 1000, json.dumps(data, ensure_ascii=False), "2026-11-06", "2026-11-06T09:00:00"))
        conn.commit()
    finally:
        conn.close()
    return hs, names


def _row():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json, status, updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        return json.loads(r["data_json"]), r["status"], r["updated_at"]
    finally:
        conn.close()


def _edit_items(qty):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["items"][0]["qty"] = qty
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()


def test_get_exposes_content_fp_outside_data_only_while_pending(client, make_user):
    hs, _ = _seed(client, make_user)
    r = client.get("/api/quotations/" + NO, headers=hs[0]).json()
    assert r["contentFp"] == C.content_fingerprint(_row()[0])
    assert "contentFp" not in r["data"], "放在 data 裡會被前端原樣送回 PUT、存進 data_json 變成內容鍵"
    import db
    conn = db.get_db(); conn.execute("UPDATE quotations SET status='草稿' WHERE quote_no=?", (NO,)); conn.commit(); conn.close()
    assert "contentFp" not in client.get("/api/quotations/" + NO, headers=hs[0]).json(), "非待審核／簽核中的回應不變"


def test_approve_with_matching_fp_succeeds_and_stamps_signed_fp(client, make_user):
    hs, names = _seed(client, make_user)
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp})
    assert r.status_code == 200, r.text
    d, status, _ = _row()
    e = d["approval"]["tiers"][0]["approvers"][0]
    assert e["status"] == "approved" and e["signedFp"] == fp and d["approval"]["contentFp"] == fp
    assert e["signedKeyHashes"] == C.key_hashes(d)
    assert status == "已送出"


def test_approve_with_stale_fp_is_409_and_changes_nothing(client, make_user):
    hs, _ = _seed(client, make_user)
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    _edit_items(7)                                                  # 簽核人開著畫面時有人改了內容
    before = _row()
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp})
    assert r.status_code == 409 and "內容已更新" in r.text, r.text
    assert _row() == before, "409 不得寫入任何東西（含 updated_at、簽核狀態）"
    fp2 = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    assert fp2 != fp
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp2}).status_code == 200


def test_approve_changing_only_bookkeeping_keys_is_not_a_conflict(client, make_user):
    hs, _ = _seed(client, make_user)
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    import db
    conn = db.get_db()
    d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["statusLog"].append({"at": "x"}); d["docVersions"] = [{"seq": 1}]; d["googleCalendarEventId"] = "ev1"
    conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); conn.commit(); conn.close()
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp}).status_code == 200


def test_approve_without_expected_fp_still_works_while_not_required(client, make_user, monkeypatch):
    hs, _ = _seed(client, make_user)
    assert C.EXPECTED_FP_REQUIRED is False
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={}).status_code == 200
    d, _s, _u = _row()
    assert d["approval"]["tiers"][0]["approvers"][0]["signedFp"], "沒帶 expectedFp 也照樣蓋章"


def test_approve_without_expected_fp_is_409_when_required(client, make_user, monkeypatch):
    hs, _ = _seed(client, make_user)
    monkeypatch.setattr(C, "EXPECTED_FP_REQUIRED", True)
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={})
    assert r.status_code == 409, r.text
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp}).status_code == 200


def test_unauthorised_caller_gets_permission_error_not_409(client, make_user):
    """權限檢查在前：沒權限的人不該從 409 得知內容有沒有變。"""
    hs, _ = _seed(client, make_user)
    other, pw = make_user(username="fp_other", role="admin")
    ho = _login(client, other, pw)
    r = client.post("/api/quotations/%s/approve" % NO, headers=ho, json={"expectedFp": "1:wrong"})
    assert r.status_code in (403, 404) and r.status_code != 409, r.text


def test_two_tiers_each_signer_is_stamped_with_the_version_they_saw(client, make_user):
    hs, _ = _seed(client, make_user, tiers=2)
    fp1 = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp1}).status_code == 200
    _edit_items(8)                                                  # 第一層簽完之後內容被改
    fp2 = client.get("/api/quotations/" + NO, headers=hs[1]).json()["contentFp"]
    assert fp2 != fp1
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[1], json={"expectedFp": fp2}).status_code == 200
    d, _s, _u = _row()
    t1, t2 = (t["approvers"][0] for t in d["approval"]["tiers"])
    assert t1["signedFp"] == fp1 and t2["signedFp"] == fp2, "各人蓋的是自己簽那一刻的版本（S3 靠這個判複查）"
    assert C.effective_approval(d)[1] is True and C.effective_approval(d)[0]["tiers"][0]["approvers"][0]["status"] == "pending"


def test_cascade_stamps_every_tier_signed_in_one_call(client, make_user):
    import db
    n, pw = make_user(username="fp_same", role="admin")
    h = _login(client, n, pw)
    req, _ = make_user(username="fp_req2", role="admin")
    appr = {"requestedBy": req, "requestedAt": "2026-11-06T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": n, "displayName": n, "status": "pending"}]} for _ in range(2)]}
    conn = db.get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (NO, "待審核", "甲", "專案", 1, json.dumps(dict(_doc(), approval=appr), ensure_ascii=False), "2026-11-06", "2026-11-06"))
    conn.commit(); conn.close()
    r = client.post("/api/quotations/%s/approve" % NO, headers=h, json={"cascade": True})
    assert r.status_code == 200 and r.json()["signedTiers"] == [1, 2], r.text
    d, status, _ = _row()
    fp = C.content_fingerprint(d)
    assert [t["approvers"][0].get("signedFp") for t in d["approval"]["tiers"]] == [fp, fp] and status == "已送出"


# ── rebaseline_fingerprint ────────────────────────────────────────────────────────────────
def _signed_by_first(client, make_user, tiers=2):
    hs, names = _seed(client, make_user, tiers=tiers)
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp}).status_code == 200
    return hs, fp


def test_rebaseline_resets_signed_entries_to_current_content_and_keeps_updated_at(client, make_user):
    import db
    _signed_by_first(client, make_user)
    _edit_items(5)                                                  # 模擬遷移改了內容鍵
    d0, _s, ua0 = _row()
    assert C.effective_approval(d0)[1] is True                       # 重設之前：第一層會被判過期
    conn = db.get_db()
    try:
        from core import txn
        txn.begin_write(conn)
        assert C.rebaseline_fingerprint(conn, NO, reason="測試遷移") is True
        conn.commit()
        n_audit = conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='quotation.rebaseline_fp' AND target_id=?", (NO,)).fetchone()["c"]
    finally:
        conn.close()
    d1, status, ua1 = _row()
    fp = C.content_fingerprint(d1)
    assert d1["approval"]["contentFp"] == fp and d1["approval"]["tiers"][0]["approvers"][0]["signedFp"] == fp
    assert d1["approval"]["tiers"][0]["approvers"][0]["status"] == "approved"
    assert "signedFp" not in d1["approval"]["tiers"][1]["approvers"][0], "還沒簽的不蓋"
    assert C.effective_approval(d1)[1] is False
    assert ua1 == ua0, "不動 updated_at（PUT 樂觀鎖的版本戳）"
    assert status == "簽核中" and n_audit == 1
    d1["approval"] = d0["approval"]
    assert C.content_fingerprint(d1) == C.content_fingerprint(d0), "只動了 approval（排除鍵），內容不變"


@pytest.mark.parametrize("status", ["草稿", "已送出", "已成案"])
def test_rebaseline_ignores_quotes_outside_pending_states(client, make_user, status):
    import db
    _seed(client, make_user, status=status)
    conn = db.get_db()
    try:
        from core import txn
        txn.begin_write(conn)
        before = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]
        assert C.rebaseline_fingerprint(conn, NO) is False
        assert conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"] == before
        conn.rollback()
    finally:
        conn.close()


def test_rebaseline_missing_quote_or_no_approval_is_a_noop(client, make_user):
    import db
    conn = db.get_db()
    try:
        from core import txn
        txn.begin_write(conn)
        assert C.rebaseline_fingerprint(conn, "MQ-000000-000") is False
        conn.rollback()
    finally:
        conn.close()


def test_superadmin_no_tier_branch_is_also_bound_to_the_version(client, make_user, monkeypatch):
    """沒有簽核層資料的舊單，超管走『無層級後備』核准——這條路也要綁版本。"""
    import db
    from modules.case.api import quotations as qapi
    monkeypatch.setattr(qapi, "_setting_to_active_tiers", lambda *a, **k: [])      # 全域流程沒有層級，後備路徑才放行（否則先回 400/403）
    sa, pw = make_user(username="fp_sa", role="superadmin")
    h = _login(client, sa, pw)
    req, _ = make_user(username="fp_req3", role="admin")
    appr = {"requestedBy": req, "requestedAt": "2026-11-06T01:00:00", "currentTier": 0, "tiers": []}
    conn = db.get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (NO, "待審核", "甲", "專案", 1, json.dumps(dict(_doc(), approval=appr), ensure_ascii=False), "2026-11-06", "2026-11-06"))
    conn.commit(); conn.close()
    r = client.post("/api/quotations/%s/approve" % NO, headers=h, json={"expectedFp": "1:stale"})
    assert r.status_code == 409 and "內容已更新" in r.text, r.text
    assert _row()[1] == "待審核"
    fp = client.get("/api/quotations/" + NO, headers=h).json()["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=h, json={"expectedFp": fp}).status_code == 200


# ── K 審補項：過渡期稽核記 fpBound；rebaseline_fingerprint 不得接使用者端點 ──────────────────────
def _approve_audit_detail():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT detail FROM audit_log WHERE action='quotation.approve' AND target_id=? ORDER BY id DESC LIMIT 1", (NO,)).fetchone()
        return json.loads(r["detail"])
    finally:
        conn.close()


def test_approve_audit_records_whether_the_version_was_bound(client, make_user):
    hs, _ = _seed(client, make_user, tiers=2)
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp}).status_code == 200
    assert _approve_audit_detail()["fpBound"] is True
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[1], json={}).status_code == 200     # 過渡期：沒帶
    assert _approve_audit_detail()["fpBound"] is False


def test_rebaseline_fingerprint_is_not_reachable_from_any_user_facing_endpoint():
    """棘輪例外的條件（K 審）：`rebaseline_fingerprint` 只給開機遷移／系統工具用，**不得**接到 routers／模組 api 的使用者端點。"""
    from pathlib import Path
    backend = Path(__file__).resolve().parents[3]
    hits = []
    for sub in ("routers", "modules"):
        for f in (backend / sub).rglob("*.py"):
            rel = f.relative_to(backend).as_posix()
            if "/tests/" in "/" + rel or rel == "modules/case/content_fp.py":
                continue
            if "rebaseline_fingerprint" in f.read_text(encoding="utf-8", errors="replace") and ("/api" in "/" + rel or rel.startswith("routers/")):
                hits.append(rel)
    assert hits == [], "rebaseline_fingerprint 出現在使用者端點檔：%s" % hits
