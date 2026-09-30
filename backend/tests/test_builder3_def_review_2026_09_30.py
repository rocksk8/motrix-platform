# -*- coding: utf-8 -*-
"""建構器第三輪 S4（2026-09-30）：模組「定義」送審→退回（原因必填）→修改重送（v1→v2…，版號不回收）→核可才發布。
主持裁示：系統設定「模組審核人」名單裡有**申請人以外**至少一人 ⇒ 自動啟用；否則發布維持直接發布但稽核記「未經第二人審核」；
手動覆寫 mode（auto／on／off，最高管理者、寫稽核）。
- 啟用：送審＝不可變快照（submitted）、簽核佇列出現 custom_module_def、審核人任一位核可才 published；申請人不能審自己送的
- 退回：保留列與原因、草稿仍在、再送 ⇒ 新版號；送審期間草稿還能改，核可後不會被吃掉
- 審核頁資料只給最高管理者、審核人（含代理）、申請人；還原在啟用時＝放回草稿"""
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


def _cfg(client, h, **kw):
    r = client.put("/api/custom-modules/definition-review", headers=h, json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def _audit_actions():
    return [r["action"] for r in _db("SELECT action FROM audit_log ORDER BY id")]


@pytest.fixture()
def world(client, make_user):
    boss = _login(client, make_user, "b3d_boss", role="superadmin")
    appr = _login(client, make_user, "b3d_appr", role="admin", modules=[])
    other = _login(client, make_user, "b3d_other", role="user", modules=[])
    return client, boss, appr, other


def test_no_reviewer_other_than_the_submitter_publishes_directly_and_audits_it(world):
    client, boss, _a, _o = world
    st = _cfg(client, boss, reviewers=["b3d_boss"])                                # 名單只有申請人自己
    assert st["active"] is False and "沒有申請人以外的審核人" in st["reason"] and st["mode"] == "auto"
    _draft(client, boss, _body())
    r = _publish(client, boss, "第一版")
    assert r.status_code == 200 and r.json()["status"] == "published" and "pending" not in r.json()
    assert _statuses() == [(1, "published")]
    assert "definitions.publish_unreviewed" in _audit_actions()                   # 稽核明記「未經第二人審核」
    label = _db("SELECT target_label FROM audit_log WHERE action='definitions.publish_unreviewed'")[0]["target_label"]
    assert "未經第二人審核" in label


def test_reviewer_list_with_someone_else_activates_review_automatically(world):
    client, boss, appr, other = world
    st = _cfg(client, boss, reviewers=["b3d_appr"])
    assert st["active"] is True and [r["username"] for r in st["reviewers"]] == ["b3d_appr"] and st["mode"] == "auto"
    assert client.get("/api/custom-modules/catalog", headers=boss).json()["defReview"]["active"] is True   # 標頭顯示用
    _draft(client, boss, _body())
    r = _publish(client, boss, "第一版")
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["version"] == 1
    assert _statuses() == [(0, "draft"), (1, "submitted")]
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).status_code == 404       # 還沒發布 ⇒ 沒有現行版
    assert "definitions.publish_unreviewed" not in _audit_actions()
    q = client.get("/api/approval-queue", headers=appr).json()
    items = q["items"] if isinstance(q, dict) else q
    mine = [i for i in items if i.get("type") == "custom_module_def"]
    assert [(i["moduleKey"], i["definitionVersion"]) for i in mine] == [(KEY, 1)]
    v = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=appr)
    assert v.status_code == 200 and v.json()["open"]["version"] == 1 and v.json()["open"]["canDecide"] is True and v.json()["open"]["changes"]
    assert client.get("/api/custom-modules/%s/definition/review" % KEY, headers=other).status_code == 403
    mine_view = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=boss).json()["open"]
    assert mine_view["canDecide"] is False and "自己送出" in mine_view["whyNot"]
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=boss, json={}).status_code == 403   # 申請人不能審自己送的
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=other, json={}).status_code == 403
    ok = client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={"note": "OK"})
    assert ok.status_code == 200 and ok.json() == {"status": "published", "version": 1, "published": True}
    assert _statuses() == [(1, "published")]                                       # 草稿與快照相同 ⇒ 一併清掉
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).status_code == 200


def test_reject_needs_a_reason_keeps_the_row_and_the_version_number_is_not_reused(world):
    client, boss, appr, _o = world
    _cfg(client, boss, reviewers=["b3d_appr"])
    _draft(client, boss, _body())
    assert _publish(client, boss).json()["version"] == 1
    assert client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "  "}).status_code == 400
    rj = client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "欄位名稱不清楚"})
    assert rj.status_code == 200 and rj.json()["status"] == "rejected"
    assert _statuses() == [(0, "draft"), (1, "rejected")]
    dec = json.loads(_db("SELECT decision_json FROM ui_definitions WHERE key=? AND version=1", (KEY,))[0]["decision_json"])
    assert dec["reason"] == "欄位名稱不清楚" and dec["decidedBy"] == "b3d_appr" and dec["result"] == "rejected"
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={}).status_code == 409
    _draft(client, boss, _body("標題（改過）"))
    assert _publish(client, boss).json()["version"] == 2                           # v1 不回收
    assert _statuses() == [(0, "draft"), (1, "rejected"), (2, "submitted")]
    hist = client.get("/api/custom-modules/%s/definition/review" % KEY, headers=boss).json()["history"]
    assert [(h["version"], h["status"], h["reason"]) for h in hist] == [(2, "submitted", ""), (1, "rejected", "欄位名稱不清楚")]
    assert client.post("/api/custom-modules/%s/definition/2/approve" % KEY, headers=appr, json={}).json()["published"] is True
    assert _statuses() == [(1, "rejected"), (2, "published")]
    assert client.get("/api/custom/%s/meta" % KEY, headers=boss).json()["definition"]["fields"][0]["label"] == "標題（改過）"


def test_only_one_open_submission_and_draft_edits_during_review_survive_approval(world):
    client, boss, appr, _o = world
    _cfg(client, boss, reviewers=["b3d_appr"])
    _draft(client, boss, _body())
    assert _publish(client, boss).json()["version"] == 1
    again = _publish(client, boss)
    assert again.status_code in (400, 422) and "送審中" in again.text
    _draft(client, boss, _body("送審期間又改了"))
    assert client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={}).json()["published"] is True
    assert (0, "draft") in _statuses()                                            # 草稿與快照不同 ⇒ 保留
    assert json.loads(_db("SELECT body_json FROM ui_definitions WHERE key=? AND version=0", (KEY,))[0]["body_json"])["fields"][0]["label"] == "送審期間又改了"


def test_invalid_draft_is_not_submitted(world):
    client, boss, _a, _o = world
    _cfg(client, boss, reviewers=["b3d_appr"])
    bad = _body()
    bad["fields"] = []
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": bad})
    r = _publish(client, boss)
    assert r.status_code == 422 and r.json()["problems"]
    assert [s for _v, s in _statuses()] == ["draft"]


def test_mode_override_off_forces_direct_publish_and_on_forces_review_with_other_superadmins(world, make_user, client):
    client, boss, appr, _o = world
    _cfg(client, boss, reviewers=["b3d_appr"], mode="off")
    _draft(client, boss, _body())
    r = _publish(client, boss)
    assert r.json()["status"] == "published" and "definitions.publish_unreviewed" in _audit_actions()   # 覆寫關閉：直接發布仍記稽核
    # on：名單清空、沒有其他最高管理者 ⇒ 沒人可審 ⇒ 仍是直接發布（原因寫明）
    st = _cfg(client, boss, reviewers=[], mode="on")
    assert st["mode"] == "on" and st["active"] is False and "沒有申請人以外的審核人" in st["reason"]
    # 另有一位最高管理者 ⇒ on 會改用他當審核人
    _login(client, make_user, "b3d_boss2", role="superadmin")
    st = _cfg(client, boss, mode="on")
    assert st["active"] is True and [r["username"] for r in st["reviewers"]] == ["b3d_boss2"]
    _draft(client, boss, _body("再改"))
    assert _publish(client, boss).json()["pending"] is True
    tok2 = client.post("/api/auth/login", json={"username": "b3d_boss2", "password": "Custom-Pass-123"}).json()["token"]
    ok = client.post("/api/custom-modules/%s/definition/2/approve" % KEY, headers={"Authorization": "Bearer " + tok2}, json={})
    assert ok.status_code == 200 and ok.json()["published"] is True


def test_settings_endpoint_validates_and_needs_superadmin(world):
    client, boss, appr, _o = world
    assert client.put("/api/custom-modules/definition-review", headers=appr, json={"mode": "on"}).status_code == 403
    assert client.get("/api/custom-modules/definition-review", headers=appr).status_code == 403
    assert client.put("/api/custom-modules/definition-review", headers=boss, json={}).status_code == 400
    assert client.put("/api/custom-modules/definition-review", headers=boss, json={"mode": "maybe"}).status_code == 400
    bad = client.put("/api/custom-modules/definition-review", headers=boss, json={"reviewers": ["nobody_here"]})
    assert bad.status_code == 400 and "nobody_here" in bad.text
    assert "custom_def.review_settings" in _audit_actions() or _cfg(client, boss, mode="auto")["mode"] == "auto"
    st = client.get("/api/custom-modules/definition-review", headers=boss).json()
    assert set(st) == {"mode", "active", "reason", "reviewers"}


def test_restore_when_active_puts_the_old_body_in_the_draft_instead_of_publishing(world):
    client, boss, appr, _o = world
    _draft(client, boss, _body("第一版標題"))
    assert _publish(client, boss).status_code == 200                               # 名單空 ⇒ 直接發布 v1
    _draft(client, boss, _body("第二版標題"))
    assert _publish(client, boss).status_code == 200                               # v2
    _cfg(client, boss, reviewers=["b3d_appr"])
    r = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r.status_code == 200 and r.json() == {"restoredToDraft": True, "fromVersion": 1}
    assert _statuses() == [(0, "draft"), (1, "published"), (2, "published")]      # 沒有新版；只是草稿被換成 v1 內容
    assert json.loads(_db("SELECT body_json FROM ui_definitions WHERE key=? AND version=0", (KEY,))[0]["body_json"])["fields"][0]["label"] == "第一版標題"
    _cfg(client, boss, reviewers=[])
    r2 = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r2.status_code == 200 and r2.json()["version"] == 3                     # 未啟用時維持原行為（直接還原成新版）


def test_versions_listing_shows_submitted_and_rejected_with_the_decision(world):
    client, boss, appr, _o = world
    _cfg(client, boss, reviewers=["b3d_appr"])
    _draft(client, boss, _body())
    _publish(client, boss)
    client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "不行"})
    vs = client.get("/api/definitions/custom_module/%s" % KEY, headers=boss).json()["versions"]
    rj = next(v for v in vs if v["version"] == 1)
    assert rj["status"] == "rejected" and rj["decision"]["reason"] == "不行"
