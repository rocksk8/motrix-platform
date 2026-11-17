# -*- coding: utf-8 -*-
"""解鎖編輯期間的規格文件上傳／刪除（使用者裁示 2026-11-17，經 PM 轉達四點）：

① 身分與解鎖相同：只有最高管理者，而且要有解鎖驗證證明（`POST /api/auth/verify-unlock` 寫的稽核列）——不能繞過解鎖流程直接傳到鎖定中的單
② 對外輸出在重新送簽之前不變：解鎖期間的上傳＝**暫存**（不進清單／檔案中心／合併），刪除＝畫面標待刪；PUT（解鎖存檔）才生效並重新送簽
③ 放棄修改能回原狀：暫存檔一起清掉（discard-staged），已生效的檔原封不動
④ 上傳、暫存、套用、放棄都留稽核；套用寫進 editHistory（送簽註記看得到「規格文件」有變更）
"""
import io
import json
import os
from datetime import datetime, timedelta

import pypdf
import pytest

import db
import helpers.uploads as UP
from modules.case.api import quotation_specs as QS
from tests._requires import requires_module

pytestmark = [requires_module("case", "解鎖編輯規格文件暫存屬於 M01（案件）"), pytest.mark.upload_magic]

NO = "MQ-SPU-001"
PW = "Zq9!wX3#kLm2vB"


def _pdf(pages=1):
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _x(sql, args=()):
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _q(sql, args=()):
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _specs_raw(no=NO):
    return json.loads(_q("SELECT spec_files_json FROM quotations WHERE quote_no=?", (no,))[0]["spec_files_json"] or "[]")


def _data(no=NO):
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (no,))[0]["data_json"] or "{}")


def _abs(entry):
    return os.path.join(UP.UPLOADS_ROOT, *entry["path"].split("/"))


def _seed(status="簽核中", no=NO):
    data = {"quoteNo": no, "customerName": "客戶", "projectName": "案",
            "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}],
            "approval": {"requestedBy": "us_req", "requestedByDisplay": "送審人", "requestedAt": "2026-11-12T09:00:00", "currentTier": 1,
                         "tiers": [{"approvers": [{"username": "us_a1", "displayName": "簽核人", "status": "approved",
                                                   "approvedAt": "2026-11-12T10:00:00"}]}]}}
    _x("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at)"
       " VALUES (?,?,?,?,?,?,?,?)", (no, status, "客戶", "案", 100, json.dumps(data, ensure_ascii=False), "2026-11-12", "2026-11-12"))


def _prove(user="us_sa", no=NO, hours_ago=0):
    """等同使用者在這張單通過解鎖密碼驗證：verify-unlock 寫的那一列稽核。"""
    at = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    _x("INSERT INTO audit_log (at, username, action, target_type, target_id) VALUES (?,?,?,?,?)",
       (at, user, "quotation.unlock", "quotation", no))


def _up(client, h, files=(("a.pdf", None),), no=NO):
    return client.post("/api/quotations/%s/spec-files" % no, headers=h,
                       files=[("files", (n, d or _pdf(), "application/pdf")) for n, d in files])


def _put(client, h, changes=None, merge=None, unlock=True, no=NO):
    data = {"customerName": "客戶", "projectName": "案", "items": [{"id": "i1", "description": "品項（改）", "qty": 1, "price": 100}]}
    if unlock:
        data["_isUnlockEdit"] = True
    if changes is not None:
        data["_specChanges"] = changes
    if merge is not None:
        data["mergeFiles"] = merge
    return client.put("/api/quotations/%s" % no, headers=h, json={"status": "待審核", "data": data})


def _flow():
    tiers = [{"approvers": [{"username": "us_a1", "display_name": "us_a1"}]}]
    _x("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
       ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}, ensure_ascii=False), "2026-11-13T00:00:00"))


@pytest.fixture
def world(client, make_user, monkeypatch):
    from modules.case import quote_edit_notify as QEN
    from modules.case.api import quotations as Q
    users = {}
    for name, role in (("us_req", "admin"), ("us_a1", "admin"), ("us_sa", "superadmin"), ("us_sa2", "superadmin"), ("us_adm", "admin")):
        users[name] = make_user(username=name, role=role, modules=["quotation"])
    monkeypatch.setattr(QEN._en, "send_registered", lambda key, **kw: True)

    def fake(target, args=(), kwargs=None, daemon=True):
        if getattr(target, "__module__", "") == "modules.case.quote_edit_notify":
            target(*args, **(kwargs or {}))
        return None
    monkeypatch.setattr(Q, "spawn_bg_thread", fake)
    QS._SWEEP["at"] = 0.0
    _flow()
    _seed()
    return {"sa": _login(client, *users["us_sa"]), "sa2": _login(client, *users["us_sa2"]), "adm": _login(client, *users["us_adm"]),
            "users": users}


def _live_file(client, world):
    """先在「可編輯」狀態放一個已生效的規格檔，再把單鎖起來。回該檔 id。"""
    _seed("草稿")
    r = _up(client, world["sa"], [("live.pdf", None)])
    assert r.status_code == 200 and len(r.json()["specFiles"]) == 1, r.text
    _x("UPDATE quotations SET status='簽核中' WHERE quote_no=?", (NO,))
    return r.json()["specFiles"][0]["id"]


# ── ① 身分與解鎖證明 ───────────────────────────────────────────────────────────

def test_locked_quote_upload_needs_superadmin_and_unlock_proof(client, world):
    assert _up(client, world["adm"]).status_code == 403, "非最高管理者：鎖定狀態不可傳"
    r = _up(client, world["sa"])
    assert r.status_code == 403 and "解鎖" in r.json()["detail"], "最高管理者但沒通過解鎖驗證：不可繞過流程直接傳"
    assert _specs_raw() == []
    _prove("us_sa2")                                           # 別人的證明不算
    assert _up(client, world["sa"]).status_code == 403
    _prove("us_sa", no="MQ-OTHER")                             # 別張單的證明不算
    assert _up(client, world["sa"]).status_code == 403
    _prove("us_sa", hours_ago=13)                              # 過期的證明不算
    assert _up(client, world["sa"]).status_code == 403
    assert _specs_raw() == []


def test_rejected_quote_is_always_403_even_with_proof(client, world):
    _seed("已拒絕")
    _prove()
    assert _up(client, world["sa"]).status_code == 403


def test_proof_comes_from_the_real_verify_unlock_endpoint(client, world):
    uid = world["users"]["us_sa"][2] if len(world["users"]["us_sa"]) > 2 else _q("SELECT id FROM users WHERE username='us_sa'")[0]["id"]
    uid = _q("SELECT id FROM users WHERE username='us_sa'")[0]["id"]
    assert client.patch("/api/users/%d/unlock-password" % uid, headers=world["sa"], json={"unlock_password": PW}).status_code == 200
    assert _up(client, world["sa"]).status_code == 403
    assert client.post("/api/auth/verify-unlock", headers=world["sa"], json={"password": "wrong-password-x", "ref": NO}).status_code == 403
    assert _up(client, world["sa"]).status_code == 403, "密碼錯誤不產生證明"
    assert client.post("/api/auth/verify-unlock", headers=world["sa"], json={"password": PW, "ref": NO}).status_code == 200
    r = _up(client, world["sa"])
    assert r.status_code == 200, r.text
    assert len(r.json()["staged"]) == 1 and r.json()["specFiles"] == []


def test_editable_quote_is_unchanged_immediate_effect(client, world):
    _seed("草稿")
    r = _up(client, world["sa"])
    assert r.status_code == 200 and len(r.json()["specFiles"]) == 1 and r.json()["staged"] == []
    assert not any(f.get("staged") for f in _specs_raw())


# ── ② 暫存：上傳不生效 ─────────────────────────────────────────────────────────

def test_staged_upload_is_invisible_everywhere_until_saved(client, world):
    _prove()
    r = _up(client, world["sa"], [("new.pdf", _pdf(2))])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["specFiles"] == [] and len(j["staged"]) == 1 and j["staged"][0]["pages"] == 2
    assert "path" not in j["staged"][0]
    raw = _specs_raw()
    assert len(raw) == 1 and raw[0]["staged"]["by"] == "us_sa" and os.path.exists(_abs(raw[0]))
    assert client.get("/api/quotations/%s" % NO, headers=world["sa"]).json()["specFiles"] == [], "GET 不含暫存項"
    assert QS.load_spec_files(raw) == [], "合併／驗證／上限都只看已生效的"
    assert QS.validate_merge_files([raw[0]["id"]], raw) == [], "暫存的 id 不能被 mergeFiles 引用"
    body = _pdf(1)
    merged, skipped = QS.merge_for_download({"quote_no": NO, "data_json": json.dumps({"mergeFiles": [raw[0]["id"]]}),
                                             "spec_files_json": json.dumps(raw)}, body)
    assert merged == body and skipped == [], "輸出不可能併進暫存檔"
    from modules.case import attachments as AT
    c = db.get_db()
    try:
        assert AT._read(c, "quotation_spec", NO) == [], "檔案中心不列暫存項"
    finally:
        c.close()


def test_other_users_do_not_see_my_staged_files(client, world):
    _prove()
    _up(client, world["sa"])
    _prove("us_sa2")
    j = _up(client, world["sa2"]).json()
    assert len(j["staged"]) == 1, "只看到自己的暫存"
    assert len(_specs_raw()) == 2


def test_staged_and_live_both_count_toward_the_limit(client, world):
    fid = _live_file(client, world)
    _prove()
    for _ in range(9):
        assert len(_up(client, world["sa"]).json()["staged"]) >= 1
    j = _up(client, world["sa"]).json()
    assert j["rejected"] and j["rejected"][0]["reason"] == "too_many"
    assert fid in [f["id"] for f in _specs_raw()]


def test_delete_live_file_is_refused_in_unlock_mode_but_staged_can_be_dropped(client, world):
    fid = _live_file(client, world)
    _prove()
    r = client.delete("/api/quotations/%s/spec-files/%s" % (NO, fid), headers=world["sa"])
    assert r.status_code == 403 and "待刪" in r.json()["detail"]
    assert fid in [f["id"] for f in _specs_raw()], "已生效的檔不會被這支刪掉"
    sid = _up(client, world["sa"]).json()["staged"][0]["id"]
    ent = next(f for f in _specs_raw() if f["id"] == sid)
    r = client.delete("/api/quotations/%s/spec-files/%s" % (NO, sid), headers=world["sa"])
    assert r.status_code == 200 and r.json()["staged"] == [] and len(r.json()["specFiles"]) == 1
    assert not os.path.exists(_abs(ent)), "暫存檔從沒生效過：直接丟掉、實體檔一併刪"
    assert client.delete("/api/quotations/%s/spec-files/%s" % (NO, sid), headers=world["sa"]).status_code == 404


def test_cannot_delete_another_users_staged_file(client, world):
    _prove("us_sa2")
    sid = _up(client, world["sa2"]).json()["staged"][0]["id"]
    _prove()
    assert client.delete("/api/quotations/%s/spec-files/%s" % (NO, sid), headers=world["sa"]).status_code == 404
    assert len(_specs_raw()) == 1


# ── ② 存檔才生效 ───────────────────────────────────────────────────────────────

def test_save_applies_adds_and_removes_in_one_transaction_and_resubmits(client, world):
    live = _live_file(client, world)
    live_ent = _specs_raw()[0]
    _prove()
    sid = _up(client, world["sa"], [("fresh.pdf", _pdf(3))]).json()["staged"][0]["id"]
    r = _put(client, world["sa"], {"add": [sid], "remove": [live]}, merge=[sid])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "待審核", "照解鎖規則重新送簽"
    raw = _specs_raw()
    assert [f["id"] for f in raw] == [sid] and "staged" not in raw[0], "暫存轉正、待刪移除"
    assert os.path.exists(_abs(raw[0])) and not os.path.exists(_abs(live_ent)), "待刪的實體檔 commit 之後刪"
    d = _data()
    assert d["mergeFiles"] == [sid] and "_specChanges" not in d, "_specChanges 不存進 data_json"
    last = d["editHistory"][-1]
    assert last["type"] == "quote_edit" and last["changes"][0]["field"] == "規格文件"
    assert "fresh.pdf" in last["changes"][0]["to"] and "live.pdf" in last["changes"][0]["to"]
    acts = [a["action"] for a in _q("SELECT action FROM audit_log WHERE target_id=?", (NO,))]
    assert "quotation.stage_spec_files" in acts and "quotation.apply_spec_changes" in acts and "quotation.unlock_edit" in acts
    detail = _q("SELECT detail FROM audit_log WHERE action='quotation.apply_spec_changes' AND target_id=?", (NO,))[0]["detail"]
    assert "fresh.pdf" in detail and "live.pdf" in detail


def test_save_with_only_a_removal(client, world):
    live = _live_file(client, world)
    _prove()
    d0 = _data()
    d0["mergeFiles"] = [live]
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d0, ensure_ascii=False), NO))
    r = _put(client, world["sa"], {"add": [], "remove": [live]}, merge=[live])
    assert r.status_code == 200, r.text
    assert _specs_raw() == [] and "mergeFiles" not in _data(), "被標待刪的 id 不會留在 mergeFiles（沒選＝不存鍵）"


def test_save_without_spec_changes_leaves_files_alone(client, world):
    live = _live_file(client, world)
    _prove()
    assert _put(client, world["sa"], None, merge=[live]).status_code == 200
    assert [f["id"] for f in _specs_raw()] == [live] and _data()["mergeFiles"] == [live]
    assert "changes" not in _data()["editHistory"][-1]


def test_spec_changes_only_with_unlock_edit_by_superadmin(client, world):
    _prove()
    sid = _up(client, world["sa"]).json()["staged"][0]["id"]
    r = _put(client, world["sa"], {"add": [sid], "remove": []}, unlock=False)
    assert r.status_code == 400, r.text
    assert any(f.get("staged") for f in _specs_raw()), "被拒絕時暫存原封不動"
    r = _put(client, world["adm"], {"add": [sid], "remove": []})
    assert r.status_code in (400, 403)


def test_save_with_invalid_add_ids_is_400_and_changes_nothing(client, world):
    live = _live_file(client, world)
    _prove("us_sa2")
    other = _up(client, world["sa2"]).json()["staged"][0]["id"]
    _prove()
    before = _specs_raw()
    status0 = _q("SELECT status FROM quotations WHERE quote_no=?", (NO,))[0]["status"]
    for bad in ("nope", other, live):
        r = _put(client, world["sa"], {"add": [bad], "remove": []})
        assert r.status_code == 400, (bad, r.text)
    assert _specs_raw() == before
    assert _q("SELECT status FROM quotations WHERE quote_no=?", (NO,))[0]["status"] == status0
    assert all(os.path.exists(_abs(f)) for f in before)


def test_apply_requires_unlock_proof_even_if_changes_are_well_formed(client, world):
    live = _live_file(client, world)
    r = _put(client, world["sa"], {"add": [], "remove": [live]})          # 沒有任何解鎖證明
    assert r.status_code == 403, r.text
    assert [f["id"] for f in _specs_raw()] == [live]


def test_apply_failure_rolls_back_the_spec_column_with_the_quote(client, world, monkeypatch):
    live = _live_file(client, world)
    _prove()
    before = _specs_raw()
    from modules.case.api import quotations as Q

    def boom(*a, **k):                                         # 在寫入交易內、套用規格變更「之後」才失敗
        raise RuntimeError("boom")
    monkeypatch.setattr(Q, "require_case", boom)
    with pytest.raises(RuntimeError):
        _put(client, world["sa"], {"add": [], "remove": [live]})
    assert _specs_raw() == before and os.path.exists(_abs(before[0])), "整筆失敗 ⇒ 清單與實體檔都還在"


# ── ③ 放棄修改 ─────────────────────────────────────────────────────────────────

def test_discard_clears_my_staged_files_and_restores_the_original_state(client, world):
    live = _live_file(client, world)
    live_ent = _specs_raw()[0]
    _prove()
    _up(client, world["sa"], [("n1.pdf", None), ("n2.pdf", None)])
    ents = [f for f in _specs_raw() if f.get("staged")]
    assert len(ents) == 2
    _prove("us_sa2")
    other = _up(client, world["sa2"]).json()["staged"][0]["id"]
    r = client.post("/api/quotations/%s/spec-files/discard-staged" % NO, headers=world["sa"])
    assert r.status_code == 200 and r.json()["staged"] == [] and [f["id"] for f in r.json()["specFiles"]] == [live]
    assert all(not os.path.exists(_abs(e)) for e in ents), "暫存檔的實體檔一併清掉"
    assert os.path.exists(_abs(live_ent)), "已生效的檔不動（待刪的恢復＝本來就沒動）"
    assert other in [f["id"] for f in _specs_raw()], "別人的暫存不動"
    assert client.post("/api/quotations/%s/spec-files/discard-staged" % NO, headers=world["sa"]).status_code == 200, "冪等"
    assert any(a["action"] == "quotation.discard_spec_files" for a in _q("SELECT action FROM audit_log WHERE target_id=?", (NO,)))


def test_discard_works_even_after_the_unlock_proof_expired(client, world):
    _prove(hours_ago=0)
    _up(client, world["sa"])
    _x("UPDATE audit_log SET at=? WHERE action='quotation.unlock'", ((datetime.now() - timedelta(hours=20)).isoformat(),))
    r = client.post("/api/quotations/%s/spec-files/discard-staged" % NO, headers=world["sa"])
    assert r.status_code == 200 and not any(f.get("staged") for f in _specs_raw())


def test_discard_on_editable_quote_is_a_harmless_noop(client, world):
    _seed("草稿")
    _up(client, world["sa"])
    r = client.post("/api/quotations/%s/spec-files/discard-staged" % NO, headers=world["sa"])
    assert r.status_code == 200 and len(r.json()["specFiles"]) == 1


# ── TTL ───────────────────────────────────────────────────────────────────────

def test_stale_staged_files_are_swept_and_cannot_be_applied(client, world):
    _prove()
    old = _up(client, world["sa"]).json()["staged"][0]["id"]
    _prove()
    new = _up(client, world["sa"]).json()["staged"][-1]["id"]
    raw = _specs_raw()
    for f in raw:
        if f["id"] == old:
            f["staged"]["at"] = (datetime.now() - timedelta(hours=QS.STAGE_TTL_HOURS + 1)).isoformat()
    _x("UPDATE quotations SET spec_files_json=? WHERE quote_no=?", (json.dumps(raw), NO))
    r = _put(client, world["sa"], {"add": [old], "remove": []})
    assert r.status_code == 400 and "失效" in r.json()["detail"]
    old_ent = next(f for f in raw if f["id"] == old)
    assert QS.sweep_stale_staged() == 1
    assert [f["id"] for f in _specs_raw()] == [new] and not os.path.exists(_abs(old_ent))


def test_expired_entries_are_not_shown_in_my_staged_list(client, world):
    _prove()
    _up(client, world["sa"])
    raw = _specs_raw()
    raw[0]["staged"]["at"] = (datetime.now() - timedelta(hours=30)).isoformat()
    assert QS.public_staged(raw, "us_sa") == []
    raw[0]["staged"] = {"by": "us_sa"}                                 # 沒時間戳＝視為過期
    assert QS.public_staged(raw, "us_sa") == []


def test_lazy_sweep_runs_on_the_next_spec_endpoint_call(client, world):
    _prove()
    sid = _up(client, world["sa"]).json()["staged"][0]["id"]
    raw = _specs_raw()
    raw[0]["staged"]["at"] = (datetime.now() - timedelta(hours=30)).isoformat()
    _x("UPDATE quotations SET spec_files_json=? WHERE quote_no=?", (json.dumps(raw), NO))
    QS._SWEEP["at"] = 0.0
    client.post("/api/quotations/%s/spec-files/discard-staged" % NO, headers=world["sa"])
    assert sid not in [f["id"] for f in _specs_raw()]


# ── 純函式 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["x", [], {"add": "a"}, {"add": [1]}, {"remove": [None, "a"]}, {"add": ["a"], "remove": ["a"]},
                                 {"add": ["x%d" % i for i in range(51)]}])
def test_normalize_spec_changes_rejects_malformed(bad):
    with pytest.raises(Exception) as ei:
        QS.normalize_spec_changes(bad)
    assert getattr(ei.value, "status_code", None) == 400


def test_normalize_spec_changes_empty_means_none_and_dedups():
    assert QS.normalize_spec_changes(None) is None
    assert QS.normalize_spec_changes({}) is None
    assert QS.normalize_spec_changes({"add": [], "remove": []}) is None
    assert QS.normalize_spec_changes({"add": ["a", "a", "b"]}) == {"add": ["a", "b"], "remove": []}


def _ent(i, staged_by=None, size=10, hours_ago=0):
    e = {"id": i, "name": i + ".pdf", "path": "quotation_specs/%s/%s.pdf" % (NO, i), "size": size, "pages": 1, "status": "ok"}
    if staged_by:
        e["staged"] = {"by": staged_by, "at": (datetime.now() - timedelta(hours=hours_ago)).isoformat()}
    return e


def test_plan_keeps_order_and_reports_what_to_unlink():
    allf = [_ent("l1"), _ent("l2"), _ent("s1", "u"), _ent("s2", "u"), _ent("o1", "other")]
    after, promoted, removed, dropped = QS._plan(allf, {"add": ["s1"], "remove": ["l1", "ghost"]}, "u")
    assert [f["id"] for f in after] == ["l2", "s1"] and all("staged" not in f for f in after)
    assert [f["id"] for f in promoted] == ["s1"] and [f["id"] for f in removed] == ["l1"]
    assert [f["id"] for f in dropped] == ["s2"], "本人沒轉正的暫存一起丟；別人的不碰"


def test_plan_enforces_limits_after_apply():
    allf = [_ent("l%d" % i) for i in range(10)] + [_ent("s", "u")]
    with pytest.raises(Exception) as ei:
        QS._plan(allf, {"add": ["s"], "remove": []}, "u")
    assert ei.value.status_code == 400
    after = QS._plan(allf, {"add": ["s"], "remove": ["l0"]}, "u")[0]
    assert len(after) == 10
    big = [_ent("a", size=QS.MAX_SPEC_TOTAL_BYTES), _ent("s", "u", size=1)]
    with pytest.raises(Exception) as ei:
        QS._plan(big, {"add": ["s"], "remove": []}, "u")
    assert ei.value.status_code == 400


def test_spec_files_after_is_read_only_and_matches_plan(client, world):
    live = _live_file(client, world)
    _prove()
    sid = _up(client, world["sa"]).json()["staged"][0]["id"]
    before = _specs_raw()
    u = {"username": "us_sa"}
    assert [f["id"] for f in QS.spec_files_after(NO, None, u)] == [live]
    assert [f["id"] for f in QS.spec_files_after(NO, {"add": [sid], "remove": [live]}, u)] == [sid]
    assert _specs_raw() == before, "唯讀：不寫庫、不刪檔"


def test_gate_tuple_still_identical_to_put_quotation_source():
    src = open(os.path.join(os.path.dirname(QS.__file__), "quotations.py"), encoding="utf-8").read()
    lit = "_LOCKED = (" + ",".join('"%s"' % s for s in QS.EDIT_LOCKED_STATUSES)
    assert lit.replace(" ", "") in src.replace(" ", "")


# ── _specChanges 是解鎖存檔專用鍵：其他寫入路徑不可原樣存進 data_json ─────────────────

_SC = {"add": ["x"], "remove": ["y"]}


def test_create_quotation_does_not_store_spec_changes(client, world):
    r = client.post("/api/quotations", headers=world["sa"], json={"status": "草稿", "data": {
        "customerName": "客戶", "projectName": "新單", "items": [], "_specChanges": _SC}})
    assert r.status_code == 201, r.text
    assert "_specChanges" not in _data(r.json()["quote_no"])


def test_create_historical_quotation_does_not_store_spec_changes(client, world):
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("quote_backfill", {"enabled": 1}, reason="測試", user="us_test", conn=c)
        c.commit()
        SR.invalidate("quote_backfill")
    finally:
        c.close()
    try:
        month = (datetime.now().replace(day=1) - timedelta(days=40)).strftime("%Y-%m-15")
        r = client.post("/api/quotations/historical", headers=world["sa"], json={
            "data": {"customerName": "補登客戶", "projectName": "歷史案件", "quoteDate": month, "items": [], "_specChanges": _SC},
            "reason": "補登舊案件，紙本單據遺失重建"})
        assert r.status_code == 201, r.text
        assert "_specChanges" not in _data(r.json()["quote_no"])
    finally:
        c = db.get_db()
        try:
            SR.publish("quote_backfill", {"enabled": 0}, reason="測試還原", user="us_test", conn=c)
            c.commit()
            SR.invalidate("quote_backfill")
        finally:
            c.close()


def test_review_edit_pops_spec_changes_before_any_validation():
    """review_edit 的控制旗標清單要含 _specChanges，且在驗證／存檔之前（AST 找結構，不靠文字子字串）。"""
    import ast
    import inspect
    import textwrap
    from modules.case.api import quotations as Q
    fn = ast.parse(textwrap.dedent(inspect.getsource(Q.review_edit_quotation))).body[0]
    flag = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value == "_specChanges"]
    check = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_check_extra_notes"]
    assert flag and check and min(flag) < min(check)
