# -*- coding: utf-8 -*-
"""BP-1 治理切片：版本帳本／任兩版差異／發布前影響預覽（只讀既有 ui_definitions，旗標 builder_governance.enabled 預設關）。
- 旗標關：三條新路由對最高管理者一律 404、未登入 401、非最高管理者被拒；發布與還原的行為與回應不變（逐位元組相同的回應鍵）
- 旗標開：帳本標出生效版與可還原版、差異、影響預覽（草稿戳、驗證、其他範圍）；預覽只多一筆稽核
- 正對照：舊版含現行驗證器不接受的內容 ⇒ 既有還原端點拒絕（422），不產生新版本"""
import json

import pytest

import db
from routers import def_governance as G

KEY = "invoice_vouchers"
BASE = "/api/definitions/custom_fields/" + KEY
GOV = "/api/def-governance/custom_fields/" + KEY


def _body(*labels):
    return {"fields": [{"key": "f%d" % i, "label": l, "type": "text"} for i, l in enumerate(labels)]}


@pytest.fixture()
def api(client, make_user):
    u, p = make_user(username="bp1_sa", role="superadmin")
    u2, p2 = make_user(username="bp1_adm", role="admin")

    def login(a, b):
        r = client.post("/api/auth/login", json={"username": a, "password": b})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}
    return client, {"sa": login(u, p), "adm": login(u2, p2)}


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setattr(G, "enabled", lambda conn=None: True)


def _publish(c, h, body, note="n"):
    assert c.put(BASE + "/draft", headers=h["sa"], json={"body": body}).status_code == 200
    r = c.post(BASE + "/publish", headers=h["sa"], json={"note": note})
    assert r.status_code == 200, r.text
    return r.json()


def _audit_count(action):
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,)).fetchone()[0]
    finally:
        conn.close()


def test_flag_default_is_off():
    assert G.enabled() is False


def test_off_every_new_route_is_404_for_superadmin_401_anonymous_and_refused_for_admin(api):
    c, h = api
    for suffix in ("/ledger", "/diff", "/impact"):
        assert c.get(GOV + suffix, headers=h["sa"]).status_code == 404
        assert c.get(GOV + suffix).status_code == 401
        assert c.get(GOV + suffix, headers=h["adm"]).status_code in (401, 403)


def test_off_publish_and_restore_behave_as_before(api):
    c, h = api
    d1 = _publish(c, h, _body("甲"))
    d2 = _publish(c, h, _body("甲", "乙"))
    assert (d1["version"], d2["version"]) == (1, 2)
    r = c.post(BASE + "/restore/1", headers=h["sa"], json={"note": "x"})
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["draftPending"] is False
    assert _audit_count("definitions.previewed") == 0


def test_on_unsupported_kind_is_404(api, flag_on):
    c, h = api
    assert c.get("/api/def-governance/no_such_kind/x/ledger", headers=h["sa"]).status_code == 404


def test_custom_module_impact_counts_records_frozen_on_the_live_version(api, flag_on):
    c, h = api
    conn = db.get_db()
    for v, n in ((1, 3), (2, 2)):
        conn.execute("INSERT INTO ui_definitions (kind,key,scope,version,status,body_json,published_by,published_at) "
                     "VALUES ('custom_module','zz_mod','company',?, 'published', '{}', 'x', '2026-01-01T00:00:00')", (v,))
        for i in range(n):
            conn.execute("INSERT INTO custom_records (module_key,record_no,def_version) VALUES ('zz_mod',?,?)", ("R%d%d" % (v, i), v))
    conn.execute("INSERT INTO ui_definitions (kind,key,scope,version,status,body_json) VALUES ('custom_module','zz_mod','company',0,'draft','{}')")
    conn.commit()
    conn.close()
    j = c.get("/api/def-governance/custom_module/zz_mod/impact", headers=h["sa"]).json()
    assert j["liveVersion"] == 2 and j["frozenRecords"] == 2                       # 只算凍結在目前生效版（第 2 版）的 2 張，不是全部 5 張
    assert c.get("/api/def-governance/custom_module/zz_mod/ledger", headers=h["sa"]).json()["live"] == 2
    assert c.get(GOV + "/impact", headers=h["sa"]).json()["frozenRecords"] is None   # 其他種類＝不適用


def test_remit_kinds_definition_is_readable_through_the_governance_routes(api, flag_on):
    """第三個接上面板的編輯頁（匯款款別設定）用的種類必須是已登錄的：帳本與影響預覽都能讀。"""
    c, h = api
    r = c.get("/api/def-governance/remit_kinds/default/ledger", headers=h["sa"])
    assert r.status_code == 200 and r.json()["kind"] == "remit_kinds" and r.json()["live"] is None
    assert c.get("/api/def-governance/remit_kinds/default/impact", headers=h["sa"]).status_code == 200


def test_ledger_marks_live_and_restorable(api, flag_on):
    c, h = api
    _publish(c, h, _body("甲"), "第一版")
    _publish(c, h, _body("甲", "乙"), "第二版")
    assert c.put(BASE + "/draft", headers=h["sa"], json={"body": _body("丙")}).status_code == 200
    r = c.get(GOV + "/ledger", headers=h["sa"])
    assert r.status_code == 200
    j = r.json()
    assert j["live"] == 2 and j["hasDraft"] is True and j["pendingReview"] is False
    assert [v["version"] for v in j["versions"]] == [2, 1]
    assert [v["isLive"] for v in j["versions"]] == [True, False]
    assert [v["validNow"] for v in j["versions"]] == [None, True]            # 只有可還原的版本才驗
    assert [v["restorable"] for v in j["versions"]] == [False, True]
    assert j["versions"][1]["note"] == "第一版" and j["versions"][1]["by"] == "bp1_sa"


def test_diff_between_any_two_versions_and_live_vs_draft(api, flag_on):
    c, h = api
    _publish(c, h, _body("甲"))
    _publish(c, h, _body("甲", "乙"))
    assert c.put(BASE + "/draft", headers=h["sa"], json={"body": _body("甲", "乙", "丙")}).status_code == 200
    r = c.get(GOV + "/diff", headers=h["sa"], params={"a": "1", "b": "2"})
    assert r.status_code == 200 and r.json()["changes"], r.text
    live_vs_draft = c.get(GOV + "/diff", headers=h["sa"]).json()          # 預設 a=live、b=draft
    assert live_vs_draft["a"] == "live" and live_vs_draft["b"] == "draft" and live_vs_draft["changes"]
    same = c.get(GOV + "/diff", headers=h["sa"], params={"a": "2", "b": "live"}).json()
    assert same["changes"] == []
    assert c.get(GOV + "/diff", headers=h["sa"], params={"a": "9", "b": "live"}).status_code == 400
    assert c.get(GOV + "/diff", headers=h["sa"], params={"a": "x", "b": "live"}).status_code == 400


def test_impact_preview_counts_match_and_writes_only_an_audit_line(api, flag_on):
    c, h = api
    _publish(c, h, _body("甲"))
    draft = _body("甲", "乙")
    assert c.put(BASE + "/draft", headers=h["sa"], json={"body": draft}).status_code == 200
    # 另一個範圍（角色版）已發布 ⇒ 影響預覽要列出
    role = BASE + "/draft"
    assert c.put(role, headers=h["sa"], params={"scope": "role:admin"}, json={"body": _body("角")}).status_code == 200
    assert c.post(BASE + "/publish", headers=h["sa"], params={"scope": "role:admin"}, json={"note": "r"}).status_code == 200
    conn = db.get_db()
    before = conn.execute("SELECT COUNT(*) FROM ui_definitions").fetchone()[0]
    conn.close()
    r = c.get(GOV + "/impact", headers=h["sa"])
    assert r.status_code == 200
    j = r.json()
    assert j["hasDraft"] is True and j["liveVersion"] == 1 and j["nextVersion"] == 2
    assert j["changeCount"] == len(j["changes"]) and j["changeCount"] > 0
    assert j["validation"] == {"ok": True, "problems": []}
    assert j["otherScopes"] == [{"scope": "role:admin", "latestVersion": 1}]
    assert j["declared"]["roleOverridesPresent"] is True and j["frozenRecords"] is None
    conn = db.get_db()
    from core import definitions as D
    assert j["previewHash"] and j["previewHash"] == D.get(conn, "custom_fields", KEY, "company", 0)["etag"]
    conn.close()
    conn = db.get_db()
    after = conn.execute("SELECT COUNT(*) FROM ui_definitions").fetchone()[0]
    conn.close()
    assert after == before and _audit_count("definitions.previewed") == 1


def test_impact_preview_reports_validation_problems_without_publishing(api, flag_on):
    c, h = api
    _publish(c, h, _body("甲"))
    conn = db.get_db()
    conn.execute("INSERT INTO ui_definitions (kind,key,scope,version,status,body_json) VALUES ('custom_fields',?, 'company', 0, 'draft', ?)",
                 (KEY, json.dumps({"fields": [{"key": "Bad Key", "label": "x", "type": "text"}]})))
    conn.commit()
    conn.close()
    j = c.get(GOV + "/impact", headers=h["sa"]).json()
    assert j["validation"]["ok"] is False and j["validation"]["problems"]
    assert c.get(GOV + "/ledger", headers=h["sa"]).json()["live"] == 1


def test_restore_of_an_old_version_with_a_now_invalid_key_is_rejected_by_the_current_validator(api, flag_on):
    """正對照：舊版內容現行驗證器不接受 ⇒ 既有還原端點 422、不產生新版本。"""
    c, h = api
    conn = db.get_db()
    conn.execute("INSERT INTO ui_definitions (kind,key,scope,version,status,body_json,published_by,published_at) "
                 "VALUES ('custom_fields',?, 'company', 1, 'published', ?, 'old', '2026-01-01T00:00:00')",
                 (KEY, json.dumps({"fields": [{"key": "Bad Key", "label": "x", "type": "text"}]})))
    conn.commit()
    conn.close()
    d2 = _publish(c, h, _body("甲"))
    assert d2["version"] == 2
    led = c.get(GOV + "/ledger", headers=h["sa"]).json()
    assert [v["restorable"] for v in led["versions"]] == [False, True]      # 可還原的版本
    assert [v["validNow"] for v in led["versions"]] == [None, False]       # 但帳本提早告知：現行驗證器不接受這一版
    assert led["warnings"] and "放寬" in led["warnings"][0]                # 沒有放寬判斷 ⇒ 明說，不自創
    r = c.post(BASE + "/restore/1", headers=h["sa"], json={})
    assert r.status_code == 422 and r.json()["problems"]
    assert c.get(GOV + "/ledger", headers=h["sa"]).json()["live"] == 2
