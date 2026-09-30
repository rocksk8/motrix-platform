# -*- coding: utf-8 -*-
"""建構器第三輪 S4（2026-09-30）：模組「定義」送審→退回（原因必填）→修改重送（v1→v2…，版號不回收）→核可才發布。
- 預設關閉：發布與過去一樣直接發布（反向控制）；開啟且沒有簽核層、申請人是最高管理者 ⇒ 仍直接發布
- 開啟且有簽核層：送審＝不可變快照（submitted）、簽核佇列出現 custom_module_def、簽核人核可才 published；申請人不能審自己送的
- 退回：保留列與原因、草稿仍在、再送 ⇒ 新版號；送審期間草稿還能改，核可後不會被吃掉
- 審核頁資料只給最高管理者、簽核鏈上的人（含代理）、申請人；還原在開啟時＝放回草稿"""
import json

import pytest

KEY = "b3dr"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


def _setting(key, value):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


def _flow(approver=None, uid=None):
    tiers = [{"order": 0, "approvers": [{"userId": uid, "username": approver, "displayName": "審核人"}]}] if approver else []
    _setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": tiers})


def _body(title="T"):
    return {"name": "送審測試", "permission": "custom." + KEY, "numbering": {"prefix": "DR", "period": "none", "digits": 3},
            "fields": [{"key": "title", "label": title, "type": "text", "required": True, "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}


def _draft(client, h, body):
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": body}).json()
    assert r["problems"] == [], r["problems"]


def _publish(client, h, note=""):
    return client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={"note": note})


def _statuses():
    return [(r["version"], r["status"]) for r in _db("SELECT version, status FROM ui_definitions WHERE kind='custom_module' AND key=? ORDER BY version", (KEY,))]


def _toggle(client, h, on):
    r = client.put("/api/custom-modules/definition-review", headers=h, json={"enabled": on})
    assert r.status_code == 200 and r.json() == {"enabled": on}


@pytest.fixture()
def world(client, make_user):
    boss = _login(client, make_user, "b3d_boss", role="superadmin")
    appr = _login(client, make_user, "b3d_appr", role="admin", modules=[])
    other = _login(client, make_user, "b3d_other", role="user", modules=[])
    uid = _db("SELECT id FROM users WHERE username='b3d_appr'")[0]["id"]
    _flow(None)
    return client, boss, appr, other, uid


def test_default_off_publishes_directly_and_no_snapshot_rows(world):
    client, boss, _a, _o, uid = world
    _flow("b3d_appr", uid)                                                         # 即使設了簽核層，開關沒開 ⇒ 不送審
    _draft(client, boss, _body())
    r = _publish(client, boss)
    assert r.status_code == 200 and r.json()["status"] == "published" and "pending" not in r.json()
    assert _statuses() == [(1, "published")]


def test_on_without_tiers_a_superadmin_still_publishes_directly(world):
    client, boss, _a, _o, _uid = world
    _toggle(client, boss, True)
    _draft(client, boss, _body())
    r = _publish(client, boss)
    assert r.status_code == 200 and r.json()["status"] == "published"
    assert _statuses() == [(1, "published")]


def test_toggle_needs_superadmin_and_a_boolean(world):
    client, boss, appr, _o, _uid = world
    assert client.put("/api/custom-modules/definition-review", headers=appr, json={"enabled": True}).status_code == 403
    assert client.put("/api/custom-modules/definition-review", headers=boss, json={"enabled": "yes"}).status_code == 400


def test_submit_then_tier_approver_approves_and_it_publishes(world):
    client, boss, appr, other, uid = world
    _toggle(client, boss, True)
    _flow("b3d_appr", uid)
    _draft(client, boss, _body())
    r = _publish(client, boss, "第一版")
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["version"] == 1
    assert _statuses() == [(0, "draft"), (1, "submitted")]                         # 草稿保留、快照是新版號
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).status_code == 404   # 還沒發布 ⇒ 沒有現行版
    # 佇列：簽核人看得到，type＝custom_module_def
    q = client.get("/api/approval-queue", headers=appr).json()
    items = q["items"] if isinstance(q, dict) else q
    mine = [i for i in items if i.get("type") == "custom_module_def"]
    assert [(i["moduleKey"], i["definitionVersion"]) for i in mine] == [(KEY, 1)]
    # 審核頁資料：簽核人可讀、無關的人 403、申請人可讀
    v = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=appr)
    assert v.status_code == 200 and v.json()["open"]["version"] == 1 and v.json()["open"]["canDecide"] is True
    assert v.json()["open"]["changes"], "第一次發布：全部是新增"
    assert client.get("/api/custom-modules/%s/definition/review" % KEY, headers=other).status_code == 403
    mine_view = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=boss).json()["open"]
    assert mine_view["canDecide"] is False and "自己送出" in mine_view["whyNot"]
    # 申請人（最高管理者）不能審自己送的；無關的人不能審
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=boss, json={}).status_code == 403
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=other, json={}).status_code == 403
    ok = client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={"note": "OK"})
    assert ok.status_code == 200 and ok.json() == {"status": "published", "version": 1, "published": True}
    assert _statuses() == [(1, "published")]                                       # 草稿與快照相同 ⇒ 草稿一併清掉
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).status_code == 200


def test_reject_needs_a_reason_keeps_the_row_and_the_version_number_is_not_reused(world):
    client, boss, appr, _o, uid = world
    _toggle(client, boss, True)
    _flow("b3d_appr", uid)
    _draft(client, boss, _body())
    assert _publish(client, boss).json()["version"] == 1
    assert client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "  "}).status_code == 400
    rj = client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "欄位名稱不清楚"})
    assert rj.status_code == 200 and rj.json()["status"] == "rejected"
    assert _statuses() == [(0, "draft"), (1, "rejected")]                          # 保留；草稿還在
    dec = json.loads(_db("SELECT decision_json FROM ui_definitions WHERE key=? AND version=1", (KEY,))[0]["decision_json"])
    assert dec["reason"] == "欄位名稱不清楚" and dec["decidedBy"] == "b3d_appr" and dec["result"] == "rejected"
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={}).status_code == 409   # 已結案的不能再決定
    _draft(client, boss, _body("標題（改過）"))                                    # 依原因修改
    r2 = _publish(client, boss)
    assert r2.json()["version"] == 2                                              # v1 不回收
    assert _statuses() == [(0, "draft"), (1, "rejected"), (2, "submitted")]
    hist = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=boss).json()["history"]
    assert [(h["version"], h["status"], h["reason"]) for h in hist] == [(2, "submitted", ""), (1, "rejected", "欄位名稱不清楚")]
    assert client.post("/api/custom-modules/%s/definition/2/approve" % KEY, headers=appr, json={}).json()["published"] is True
    assert _statuses() == [(1, "rejected"), (2, "published")]
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).json()["definition"]["fields"][0]["label"] == "標題（改過）"


def test_only_one_open_submission_and_draft_edits_during_review_survive_approval(world):
    client, boss, appr, _o, uid = world
    _toggle(client, boss, True)
    _flow("b3d_appr", uid)
    _draft(client, boss, _body())
    assert _publish(client, boss).json()["version"] == 1
    again = _publish(client, boss)
    assert again.status_code in (400, 422) and "送審中" in again.text
    _draft(client, boss, _body("送審期間又改了"))                                  # 送審期間繼續改下一版
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={}).json()["published"] is True
    assert (0, "draft") in _statuses()                                            # 草稿與快照不同 ⇒ 保留，不被吃掉
    assert json.loads(_db("SELECT body_json FROM ui_definitions WHERE key=? AND version=0", (KEY,))[0]["body_json"])["fields"][0]["label"] == "送審期間又改了"


def test_invalid_draft_is_not_submitted(world):
    client, boss, _a, _o, uid = world
    _toggle(client, boss, True)
    _flow("b3d_appr", uid)
    bad = _body()
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": bad})
    bad["fields"] = []
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": bad})
    r = _publish(client, boss)
    assert r.status_code == 422 and r.json()["problems"]
    assert [s for _v, s in _statuses()] == ["draft"]


def test_restore_when_on_puts_the_old_body_in_the_draft_instead_of_publishing(world):
    client, boss, _a, _o, _uid = world
    _draft(client, boss, _body("第一版標題"))
    assert _publish(client, boss).status_code == 200                               # 關閉時直接發布 v1
    _draft(client, boss, _body("第二版標題"))
    assert _publish(client, boss).status_code == 200                               # v2
    _toggle(client, boss, True)
    r = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r.status_code == 200 and r.json() == {"restoredToDraft": True, "fromVersion": 1}
    assert _statuses() == [(0, "draft"), (1, "published"), (2, "published")]      # 沒有新版；只是草稿被換成 v1 內容
    assert json.loads(_db("SELECT body_json FROM ui_definitions WHERE key=? AND version=0", (KEY,))[0]["body_json"])["fields"][0]["label"] == "第一版標題"
    _toggle(client, boss, False)
    r2 = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r2.status_code == 200 and r2.json()["version"] == 3                     # 關閉時維持原行為（直接還原成新版）


def test_versions_listing_shows_submitted_and_rejected_with_the_decision(world):
    client, boss, appr, _o, uid = world
    _toggle(client, boss, True)
    _flow("b3d_appr", uid)
    _draft(client, boss, _body())
    _publish(client, boss)
    client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "不行"})
    vs = client.get("/api/definitions/custom_module/%s" % KEY, headers=boss).json()["versions"]
    rj = next(v for v in vs if v["version"] == 1)
    assert rj["status"] == "rejected" and rj["decision"]["reason"] == "不行"
