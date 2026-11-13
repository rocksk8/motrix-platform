"""使用者權限頁的批次授予／取消與範本套用（設定矩陣 S3a；SPEC §4.9、§12；`helpers/user_perm_batch.py`）。

守的規則：
  - 授予／取消不對稱：高敏感鍵與批次拒絕清單（C4 六鍵）授予一律略過；取消可以但要原因（≥4 個不同字）並寫權限變更紀錄；
  - 財務三鍵批次永遠不動；最高管理者不納入；
  - 範本預覽＝套用結果（同一支函式）、`planHash` 不符 ⇒ 409、被略過的項目照實回報；
  - 整批同一個交易（例外 ⇒ 全部不寫）；
  - **四條路徑都過同一個原因檢查點**（PUT／POST create／批次／範本），本檔各一題。
"""
import json
from pathlib import Path

import pytest

from helpers import duty_roles as dr
from helpers import user_perm_batch as upb

BACKEND = Path(__file__).resolve().parent.parent
BATCH = "/api/users/permissions/batch"
REFUSED = list(upb.BATCH_GRANT_REFUSED)


def _login(client, username, password="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _mods(uid):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT modules FROM users WHERE id=?", (uid,)).fetchone()[0] or "[]")
    finally:
        conn.close()


def _changes(uid):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM permission_changes WHERE target_type='user' AND target_id=? ORDER BY id", (uid,)).fetchall()]
    finally:
        conn.close()


def _count(table):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    make_user("root", role="superadmin", modules=[])
    make_user("boss2", role="superadmin", modules=[])
    make_user("amy", role="sales", modules=["dashboard", "customer", "settings", "quotation"])
    make_user("bob", role="sales", modules=["dashboard", "work_log"])
    make_user("cat", role="engineer", modules=["dashboard"])
    h = _login(client, "root")
    return {"h": h, "amy": _uid("amy"), "bob": _uid("bob"), "cat": _uid("cat"), "boss2": _uid("boss2")}


def _post(client, h, body, preview=False):
    return client.post(BATCH + ("/preview" if preview else ""), json=body, headers=h)


def _apply_template(client, h, ids, template, reason=""):
    """範本套用一律先預覽再帶 planHash 套用（沒帶 ⇒ 400；見 test_template_apply_requires_the_plan_hash）。"""
    body = {"userIds": ids, "template": template, "reason": reason}
    pv = _post(client, h, body, preview=True)
    assert pv.status_code == 200, pv.text
    return _post(client, h, {**body, "planHash": pv.json()["planHash"]})


def _person(resp, uid):
    return next(p for p in resp.json()["people"] if p["userId"] == uid)


# ── 1. 清單來自 API ───────────────────────────────────────────────────────
def test_catalog_returns_the_lists_and_the_refused_keys_are_real_keys(client, world):
    r = client.get("/api/modules/catalog", headers=world["h"])
    assert r.status_code == 200
    j = r.json()
    assert j["highSensitiveKeys"] == list(dr.HIGH_SENSITIVITY_KEYS)
    assert j["batchGrantRefused"] == REFUSED and len(REFUSED) == 6
    assert j["financeKeys"] == list(dr.FINANCE_KEYS)
    assert set(REFUSED) <= {m["key"] for m in j["modules"]}, "批次拒絕清單的鍵必須存在於目錄（打錯字＝防護失效）"
    assert not set(REFUSED) & set(dr.HIGH_SENSITIVITY_KEYS), "兩份清單分開列（不改 N2a 的高敏感清單）"


# ── 2. 授予 ───────────────────────────────────────────────────────────────
def test_batch_grant_ordinary_keys_applies_and_leaves_a_record_per_person(client, world):
    h, bob, cat = world["h"], world["bob"], world["cat"]
    r = _post(client, h, {"userIds": [bob, cat], "grant": ["customer", "map"]})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["changed"] == 2 and r.json()["applied"] == [bob, cat]
    assert _mods(bob) == ["dashboard", "work_log", "customer", "map"] and _mods(cat) == ["dashboard", "customer", "map"]
    for uid in (bob, cat):
        ch = _changes(uid)
        assert len(ch) == 1 and (ch[0]["kind"], ch[0]["high_sensitivity"]) == ("user_modules", 0)
        assert json.loads(ch[0]["added"]) == ["customer", "map"] and ch[0]["audit_id"]


@pytest.mark.parametrize("key", list(dr.HIGH_SENSITIVITY_KEYS) + REFUSED)
def test_batch_grant_of_high_or_refused_key_is_skipped_never_written(client, world, key):
    h, bob = world["h"], world["bob"]
    before = _mods(bob)
    r = _post(client, h, {"userIds": [bob], "grant": [key], "reason": "接手業務與系統管理"})
    assert r.status_code == 200, r.text
    p = _person(r, bob)
    assert p["adds"] == [] and p["status"] == "nochange"
    assert [s["key"] for s in p["skipped"]] == [key] and p["skipped"][0]["kind"] == "grant" and p["skipped"][0]["reason"]
    assert _mods(bob) == before and _changes(bob) == [], "略過＝什麼都沒寫（連有帶原因也不能繞過）"
    assert r.json()["summary"]["skippedItems"] == 1


def test_finance_keys_are_never_touched_in_either_direction(client, world):
    h, bob = world["h"], world["bob"]
    for field in ("grant", "revoke"):
        r = _post(client, h, {"userIds": [bob], field: ["cashier", "finance", "financial_view"], "reason": "離職交接作業"})
        p = _person(r, bob)
        assert sorted(s["key"] for s in p["skipped"]) == ["cashier", "finance", "financial_view"]
        assert all("角色決定" in s["reason"] for s in p["skipped"])
    assert _mods(bob) == ["dashboard", "work_log"]


def test_superadmin_is_skipped_and_reported(client, world):
    h, boss2, bob = world["h"], world["boss2"], world["bob"]
    r = _post(client, h, {"userIds": [boss2, bob], "grant": ["customer"]})
    p = _person(r, boss2)
    assert p["status"] == "skipped" and "最高管理者" in p["note"]
    assert r.json()["summary"]["skippedPeople"] == 1 and r.json()["applied"] == [bob]
    assert _changes(boss2) == []


def test_already_has_the_key_is_not_a_change(client, world):
    r = _post(client, world["h"], {"userIds": [world["bob"]], "grant": ["dashboard"]})
    assert r.status_code == 200 and _person(r, world["bob"])["status"] == "nochange" and r.json()["applied"] == []


# ── 3. 取消（可以批次，但要原因）──────────────────────────────────────────
@pytest.mark.parametrize("key", ["settings", "quotation"])
def test_batch_revoke_of_gated_key_needs_a_reason_and_writes_a_record(client, world, key):
    h, amy = world["h"], world["amy"]
    r = _post(client, h, {"userIds": [amy], "revoke": [key]})
    assert r.status_code == 400 and "原因" in r.json()["detail"], r.text
    assert key in _mods(amy) and _changes(amy) == [] and _count("permission_changes") == 0, "沒原因＝什麼都不寫"
    for bad in ("", "離職", "aaaa", "。。。。"):
        assert _post(client, h, {"userIds": [amy], "revoke": [key], "reason": bad}).status_code == 400
    r = _post(client, h, {"userIds": [amy], "revoke": [key], "reason": "人員離職收回權限"})
    assert r.status_code == 200, r.text
    assert key not in _mods(amy)
    ch = _changes(amy)
    assert len(ch) == 1 and ch[0]["high_sensitivity"] == 1 and ch[0]["reason"] == "人員離職收回權限"
    assert json.loads(ch[0]["removed"]) == [key]


def test_preview_says_a_reason_is_needed_and_never_writes(client, world):
    h, amy = world["h"], world["amy"]
    r = _post(client, h, {"userIds": [amy], "revoke": ["settings"]}, preview=True)
    assert r.status_code == 200
    j = r.json()
    assert j["needsReason"] is True and j["gatedKeys"] == ["settings"] and _person(r, amy)["removes"] == ["settings"]
    assert "settings" in _mods(amy) and _count("permission_changes") == 0
    ok = _post(client, h, {"userIds": [world["bob"]], "grant": ["customer"]}, preview=True).json()
    assert ok["needsReason"] is False


def test_unknown_key_and_bad_requests_are_400(client, world):
    h, bob = world["h"], world["bob"]
    assert _post(client, h, {"userIds": [bob], "grant": ["no_such_key"]}).status_code == 400
    assert _post(client, h, {"userIds": [], "grant": ["customer"]}).status_code == 400
    assert _post(client, h, {"userIds": [bob]}).status_code == 400
    assert _post(client, h, {"userIds": [bob], "grant": ["customer"], "revoke": ["customer"]}).status_code == 400
    assert _post(client, h, {"userIds": [bob], "template": "nope"}).status_code == 400
    assert _post(client, h, {"userIds": [bob], "template": "sales", "grant": ["customer"]}).status_code == 400
    assert _post(client, h, {"userIds": list(range(1, upb.MAX_USERS + 2)), "grant": ["customer"]}).status_code == 400
    assert _post(client, h, {"userIds": [bob, 999999], "grant": ["customer"]}).json()["people"][1]["status"] == "skipped"


def test_non_superadmin_is_refused(client, world):
    hb = _login(client, "bob")
    assert _post(client, hb, {"userIds": [world["cat"]], "grant": ["customer"]}).status_code in (401, 403)
    assert _post(client, hb, {"userIds": [world["cat"]], "grant": ["customer"]}, preview=True).status_code in (401, 403)


# ── 4. 職責角色（連動）──────────────────────────────────────────────────────
def _role(client, h, key, perms, reason="建立角色作業"):
    r = client.post("/api/duty-roles", json={"key": key, "name": key, "description": "", "permissions": perms, "reason": reason}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_bind_ordinary_role_in_batch_and_unbind_it(client, world):
    h, bob, cat = world["h"], world["bob"], world["cat"]
    rid = _role(client, h, "viewer_plus", ["customer", "map"])
    r = _post(client, h, {"userIds": [bob, cat], "bindRoleIds": [rid]})
    assert r.status_code == 200 and sorted(r.json()["applied"]) == sorted([bob, cat])
    assert _person(r, bob)["bind"] == [rid] and _person(r, bob)["effectiveAdded"] == ["customer", "map"]
    assert _mods(bob) == ["dashboard", "work_log"], "綁定不改個人勾選（連動）"
    r2 = _post(client, h, {"userIds": [bob], "unbindRoleIds": [rid]})
    assert r2.status_code == 200 and _person(r2, bob)["unbind"] == [rid] and _person(r2, bob)["effectiveRemoved"] == ["customer", "map"]


def test_bind_role_with_gated_key_is_skipped(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "payroll_ops", ["payslip", "customer"])
    r = _post(client, h, {"userIds": [bob], "bindRoleIds": [rid], "reason": "接手薪資作業"})
    p = _person(r, bob)
    assert p["bind"] == [] and p["skipped"][0]["kind"] == "bind" and r.json()["applied"] == []
    rid2 = _role(client, h, "quote_ops", ["quotation"])
    assert _person(_post(client, h, {"userIds": [bob], "bindRoleIds": [rid2]}), bob)["skipped"][0]["kind"] == "bind", "C4 清單的鍵也不能經由角色批次授予"


def test_unbind_role_with_gated_key_needs_a_reason(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "payroll_ops", ["payslip"])
    assert client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": "接手薪資作業"}, headers=h).status_code == 201
    n = _count("permission_changes")
    r = _post(client, h, {"userIds": [bob], "unbindRoleIds": [rid]})
    assert r.status_code == 400 and _count("permission_changes") == n
    r = _post(client, h, {"userIds": [bob], "unbindRoleIds": [rid], "reason": "轉調離開薪資作業"})
    assert r.status_code == 200 and _count("permission_changes") == n + 1


def test_revoking_a_key_that_comes_from_a_role_sets_a_personal_subtract(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "viewer_plus", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    r = _post(client, h, {"userIds": [bob], "revoke": ["customer"]})
    assert r.status_code == 200 and _person(r, bob)["subtractAdds"] == ["customer"]
    import db
    conn = db.get_db()
    try:
        assert [x[0] for x in conn.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (bob,))] == ["customer"]
    finally:
        conn.close()
    again = _post(client, h, {"userIds": [bob], "grant": ["customer"]})
    assert _person(again, bob)["skipped"][0]["key"] == "customer", "被個人扣項扣掉的鍵不批次授予（回報略過）"


# ── 5. 範本：預覽＝套用 ─────────────────────────────────────────────────────
def test_template_preview_equals_the_applied_result_and_plan_hash_guards_staleness(client, world):
    h, amy, bob = world["h"], world["amy"], world["bob"]
    pv = _post(client, h, {"userIds": [amy, bob], "template": "engineer", "reason": "調整為工程範本"}, preview=True)
    assert pv.status_code == 200, pv.text
    tmpl = ["dashboard", "case_manage", "project_approve_eng", "equipment", "work_log", "daily_task"]
    pa, pb = _person(pv, amy), _person(pv, bob)
    assert pa["removes"] == ["customer", "settings", "quotation"] and sorted(pa["adds"]) == ["case_manage", "daily_task", "equipment", "work_log"]
    assert [s["key"] for s in pa["skipped"]] == ["project_approve_eng"], "C4 清單內的鍵：範本也不能批次授予"
    assert pv.json()["needsReason"] is True
    h2 = pv.json()["planHash"]
    ap = _post(client, h, {"userIds": [amy, bob], "template": "engineer", "reason": "調整為工程範本", "planHash": h2})
    assert ap.status_code == 200, ap.text
    assert _person(ap, amy)["adds"] == pa["adds"] and _person(ap, amy)["removes"] == pa["removes"]
    assert set(_mods(amy)) == (set(tmpl) - {"project_approve_eng"}) and set(_mods(bob)) == {"dashboard", "work_log", "case_manage", "equipment", "daily_task"}
    stale = _post(client, h, {"userIds": [amy, bob], "template": "sales", "reason": "調整為業務範本", "planHash": h2})
    assert stale.status_code == 409, "預覽之後內容變了（或 hash 不是這次的）⇒ 不照舊預覽寫入"


def test_template_keeps_personal_subtracts_and_leaves_finance_keys_alone(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "viewer_plus", ["map"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    client.post("/api/duty-roles/subtracts", json={"userId": bob, "key": "map", "reason": ""}, headers=h)
    r = _apply_template(client, h, [bob], "sales", reason="調整為業務範本")
    assert r.status_code == 200, r.text
    p = _person(r, bob)
    assert "map" in [s["key"] for s in p["skipped"] if "扣項" in s["reason"]], "被個人扣項扣掉的鍵不授予，照實回報"
    assert not set(p["adds"]) & set(dr.FINANCE_KEYS) and not set(_mods(bob)) & set(dr.FINANCE_KEYS)
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM user_perm_subtracts WHERE user_id=?", (bob,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM user_duty_roles WHERE user_id=?", (bob,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_template_apply_requires_the_plan_hash(client, world):
    """審查 h11 S1：範本不盲目重新展開——沒帶預覽的 planHash ⇒ 400，且什麼都不寫。"""
    h, bob = world["h"], world["bob"]
    n = _count("permission_changes")
    r = _post(client, h, {"userIds": [bob], "template": "engineer"})
    assert r.status_code == 400 and "planHash" in r.json()["detail"]
    assert _mods(bob) == ["dashboard", "work_log"] and _count("permission_changes") == n


def test_template_never_adds_a_personal_subtract_for_role_given_keys(client, world):
    """審查 h11 M1：範本只換「個人勾選」。角色本來就給的鍵留著（不新增永久個人扣項，之後也不會害授予被略過）。"""
    h, amy = world["h"], world["amy"]
    rid = _role(client, h, "cust_role", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": amy, "roleId": rid, "reason": ""}, headers=h)
    pv = _post(client, h, {"userIds": [amy], "template": "engineer"}, preview=True)
    assert _person(pv, amy)["subtractAdds"] == [] and pv.status_code == 200
    r = _apply_template(client, h, [amy], "engineer", reason="調整為工程範本")
    assert r.status_code == 200, r.text
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM user_perm_subtracts WHERE user_id=?", (amy,)).fetchone()[0] == 0
    finally:
        conn.close()
    assert "customer" not in _mods(amy)
    from helpers.auth import effective_modules
    conn = db.get_db()
    try:
        row = conn.execute("SELECT role, modules FROM users WHERE id=?", (amy,)).fetchone()
        assert "customer" in effective_modules(row["role"], dr.apply_duty(json.loads(row["modules"]), [["customer"]], set(), True)), "角色仍給 customer"
    finally:
        conn.close()
    again = _post(client, h, {"userIds": [amy], "grant": ["customer"]})
    assert again.status_code == 200 and not any("扣項" in s["reason"] for s in _person(again, amy)["skipped"])


def test_unbind_and_revoke_the_same_key_leaves_no_redundant_subtract(client, world):
    """審查 h11 L1：同一請求解除角色又取消它給的鍵 ⇒ 不再寫多餘的個人扣項。"""
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "viewer_plus2", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    r = _post(client, h, {"userIds": [bob], "unbindRoleIds": [rid], "revoke": ["customer"]})
    assert r.status_code == 200, r.text
    p = _person(r, bob)
    assert p["subtractAdds"] == [] and p["unbind"] == [rid]
    assert not any("目前沒有" in s["reason"] for s in p["skipped"]), "沒有「對方沒有這個權限」的誤報；說明的是「來自同時解除的角色」（h10 L1）"


def test_revoke_may_name_a_legacy_key_the_person_still_holds(client, world):
    """審查 h11 L2：取消只要求對方持有，不要求鍵還在目錄裡（已下架的舊鍵可以被清掉）。"""
    import db
    h, bob = world["h"], world["bob"]
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(["dashboard", "old_removed_key"]), bob))
        conn.commit()
    finally:
        conn.close()
    r = _post(client, h, {"userIds": [bob], "revoke": ["old_removed_key"]})
    assert r.status_code == 200, r.text
    assert _mods(bob) == ["dashboard"]
    bad = _post(client, h, {"userIds": [bob], "grant": ["never_existed"]})
    assert bad.status_code == 400, "授予仍只認得目錄裡的鍵"


# ── 6. 整批同一個交易 ───────────────────────────────────────────────────────
def test_an_exception_midway_writes_nothing(client, world, monkeypatch):
    import db
    calls = []
    real = dr.record_user_modules_change

    def boom(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(dr, "record_user_modules_change", boom)
    conn = db.get_db()
    try:
        actor = {"id": _uid("root"), "username": "root", "display_name": "", "role": "superadmin"}
        with pytest.raises(RuntimeError):
            upb.apply(conn, actor, {"userIds": [world["bob"], world["cat"]], "grant": ["customer"]})
    finally:
        conn.close()
    assert len(calls) == 2
    assert _mods(world["bob"]) == ["dashboard", "work_log"] and _mods(world["cat"]) == ["dashboard"]
    assert _count("permission_changes") == 0


# ── 7. 四條路徑都過同一個原因檢查點（SPEC §12-2：各一題）────────────────────────
def test_path_1_put_user_modules_needs_a_reason(client, world):
    r = client.put("/api/users/%d" % world["bob"], json={"modules": ["dashboard", "settings"]}, headers=world["h"])
    assert r.status_code == 400 and "原因" in r.json()["detail"]


def test_path_2_post_create_user_with_high_key_needs_a_reason(client, world):
    r = client.post("/api/users", json={"username": "newbie", "password": "Zx9-strong-Pass!", "display_name": "新人", "role": "sales", "modules": ["dashboard", "payslip"]},
                    headers=world["h"])
    assert r.status_code == 400 and "原因" in r.json()["detail"]


def test_path_3_batch_revoke_needs_a_reason(client, world):
    r = _post(client, world["h"], {"userIds": [world["amy"]], "revoke": ["settings"]})
    assert r.status_code == 400 and "原因" in r.json()["detail"]


def test_path_4_template_apply_that_removes_a_high_key_needs_a_reason(client, world):
    r = _apply_template(client, world["h"], [world["amy"]], "viewer")
    assert r.status_code == 400 and "原因" in r.json()["detail"]
    assert "settings" in _mods(world["amy"])


def test_the_batch_module_has_no_reason_rule_of_its_own():
    src = (BACKEND / "helpers" / "user_perm_batch.py").read_text(encoding="utf-8")
    for banned in ("REASON_MIN", "_is_trivial_reason", "_require_reason_if_sensitive", "len(reason)"):
        assert banned not in src.split('"""', 2)[2], "批次不自帶第二份原因規則：一律 duty_roles.gate_reason（%s）" % banned
    assert src.count("dr.gate_reason(") == 2, "apply 與 undo 各一處，都走同一支"
    assert src.count("dr.record_user_modules_change(") == 1, "寫入只有 _write_people 一處（apply 與 undo 共用）"


# ── 8. 復原這一批（逐人 compare-and-set）──────────────────────────────────────
def _undo(client, h, apply_resp, reason=None):
    changes = [p for p in apply_resp.json()["people"] if p["status"] == "change"]
    body = {"changes": changes}
    if reason is not None:
        body["reason"] = reason
    return client.post(BATCH + "/undo", json=body, headers=h)


def test_undo_restores_the_batch_and_leaves_its_own_records(client, world):
    h, bob, cat = world["h"], world["bob"], world["cat"]
    ap = _post(client, h, {"userIds": [bob, cat], "grant": ["customer", "map"]})
    r = _undo(client, h, ap)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["applied"]) == sorted([bob, cat]) and r.json()["conflicts"] == []
    assert _mods(bob) == ["dashboard", "work_log"] and _mods(cat) == ["dashboard"]
    for uid in (bob, cat):
        ch = _changes(uid)
        assert len(ch) == 2 and json.loads(ch[1]["removed"]) == ["customer", "map"] and ch[1]["reason"] == "復原批次"


def test_undo_refuses_only_the_person_who_was_changed_by_someone_else(client, world):
    h, bob, cat = world["h"], world["bob"], world["cat"]
    ap = _post(client, h, {"userIds": [bob, cat], "grant": ["customer"]})
    other = client.put("/api/users/%d" % bob, json={"modules": ["dashboard", "work_log"]}, headers=h)      # 別人（同權限者）把這一批給的鍵拿掉
    assert other.status_code == 200
    r = _undo(client, h, ap)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == [cat] and [c["userId"] for c in r.json()["conflicts"]] == [bob]
    assert "customer" in r.json()["conflicts"][0]["reason"] and _mods(cat) == ["dashboard"]


def test_undo_of_a_revoke_of_a_gated_key_is_a_grant_and_is_refused(client, world):
    h, amy = world["h"], world["amy"]
    ap = _post(client, h, {"userIds": [amy], "revoke": ["settings", "customer"], "reason": "人員離職收回權限"})
    assert ap.status_code == 200
    r = _undo(client, h, ap)
    assert r.status_code == 200, r.text
    p = _person(r, amy)
    assert [s["key"] for s in p["skipped"]] == ["settings"], "還回高敏感鍵＝授予，不能批次"
    assert "customer" in _mods(amy) and "settings" not in _mods(amy)


def test_undo_of_a_role_derived_revoke_removes_the_personal_subtract(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "viewer_plus", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    ap = _post(client, h, {"userIds": [bob], "revoke": ["customer"]})
    assert _person(ap, bob)["subtractAdds"] == ["customer"]
    r = _undo(client, h, ap)
    assert r.status_code == 200 and r.json()["applied"] == [bob], r.text
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM user_perm_subtracts WHERE user_id=?", (bob,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_undo_of_binding_and_bad_requests(client, world):
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "viewer_plus", ["customer"])
    ap = _post(client, h, {"userIds": [bob], "bindRoleIds": [rid]})
    r = _undo(client, h, ap)
    assert r.status_code == 200 and _person(r, bob)["unbind"] == [rid]
    assert client.post(BATCH + "/undo", json={"changes": []}, headers=h).status_code == 400
    assert client.post(BATCH + "/undo", json={"changes": [{"userId": "x"}]}, headers=h).status_code == 400
    assert client.post(BATCH + "/undo", json={"changes": [{"userId": world["boss2"], "adds": ["customer"]}]}, headers=h).json()["conflicts"][0]["reason"]
    hb = _login(client, "bob")
    assert client.post(BATCH + "/undo", json={"changes": [{"userId": world["cat"]}]}, headers=hb).status_code in (401, 403)


def _subtract_rows(uid):
    import db
    conn = db.get_db()
    try:
        return [r[0] for r in conn.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (uid,))]
    finally:
        conn.close()


def _effective_of(uid):
    from helpers.auth import effective_modules
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT role, modules FROM users WHERE id=?", (uid,)).fetchone()
        st = upb._load_state(conn, [uid])
    finally:
        conn.close()
    return upb._effective(row["role"], json.loads(row["modules"] or "[]"), st["bound"].get(uid, set()), st["roles"], st["subs"].get(uid, set()))


def test_undo_of_a_grant_the_role_already_gave_creates_no_subtract(client, world):
    """審查 h11 M2：授予一個『角色本來就給』的鍵（只寫進個人勾選）→ 復原只還原個人勾選，不能多造個人扣項把角色給的權限扣掉。"""
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "undo_cust", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    before = _effective_of(bob)
    ap = _post(client, h, {"userIds": [bob], "grant": ["customer"]})
    assert ap.status_code == 200 and _person(ap, bob)["adds"] == ["customer"]
    r = client.post(BATCH + "/undo", json={"changes": [p for p in ap.json()["people"] if p["status"] == "change"]}, headers=h)
    assert r.status_code == 200 and r.json()["applied"] == [bob], r.text
    assert _subtract_rows(bob) == [], "復原不造個人扣項"
    assert _mods(bob) == ["dashboard", "work_log"] and _effective_of(bob) == before, "復原後的實際權限＝批次之前"


def test_undo_of_a_revoke_of_a_role_given_key_restores_it(client, world):
    """審查 h11 L5（反向）：取消角色給的鍵（寫個人扣項）→ 復原還回扣項，實際權限回到批次之前。"""
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "undo_cust2", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    before = _effective_of(bob)
    ap = _post(client, h, {"userIds": [bob], "revoke": ["customer"]})
    assert ap.status_code == 200 and _subtract_rows(bob) == ["customer"]
    r = client.post(BATCH + "/undo", json={"changes": [p for p in ap.json()["people"] if p["status"] == "change"]}, headers=h)
    assert r.status_code == 200 and r.json()["applied"] == [bob], r.text
    assert _subtract_rows(bob) == [] and _effective_of(bob) == before


# ── 輸入形狀（審查 h10 S1／S2／L1／L2）──────────────────────────────────────

@pytest.mark.parametrize("bad", [10 ** 30, 0, -1, 1.9, True, "x", None, [1], "1_0", "１２", " 5", "+5"])
def test_user_ids_must_be_real_in_range_integers(client, world, bad):
    r = _post(client, world["h"], {"userIds": [bad], "grant": ["map"]})
    assert r.status_code == 400, (bad, r.status_code, r.text)


@pytest.mark.parametrize("field,val", [("adds", 5), ("removes", "settings"), ("subtractAdds", 7), ("subtractRemoves", {"a": 1}),
                                       ("adds", [3]), ("bind", "12"), ("unbind", [True])])
def test_undo_change_fields_are_shape_checked_not_500(client, world, field, val):
    n = _count("permission_changes")
    r = client.post(BATCH + "/undo", json={"changes": [{"userId": world["bob"], field: val}]}, headers=world["h"])
    assert r.status_code == 400, (field, val, r.status_code, r.text)
    assert _count("permission_changes") == n


@pytest.mark.parametrize("uid", [True, 10 ** 30, 1.5, "abc", None])
def test_undo_user_id_must_be_a_real_integer(client, world, uid):
    r = client.post(BATCH + "/undo", json={"changes": [{"userId": uid, "adds": ["map"]}]}, headers=world["h"])
    assert r.status_code == 400, (uid, r.status_code, r.text)


def test_non_string_reason_is_a_400_in_apply_and_undo(client, world):
    h, bob = world["h"], world["bob"]
    assert _post(client, h, {"userIds": [bob], "grant": ["map"], "reason": 12345}).status_code == 400
    r = client.post(BATCH + "/undo", json={"changes": [{"userId": bob, "adds": ["map"]}], "reason": 12345}, headers=h)
    assert r.status_code == 400


def test_revoking_a_key_only_the_unbound_role_gave_is_reported_as_skipped(client, world):
    """審查 h10 L1：同一請求解除角色、又取消只有那個角色給的鍵 ⇒ 不是靜默無事，要說明（本來就會消失）。"""
    h, bob = world["h"], world["bob"]
    rid = _role(client, h, "gone_role", ["customer"])
    client.post("/api/duty-roles/bindings", json={"userId": bob, "roleId": rid, "reason": ""}, headers=h)
    r = _post(client, h, {"userIds": [bob], "unbindRoleIds": [rid], "revoke": ["customer"]})
    p = _person(r, bob)
    assert [s["key"] for s in p["skipped"]] == ["customer"] and "同時解除" in p["skipped"][0]["reason"] and p["unbind"] == [rid]
