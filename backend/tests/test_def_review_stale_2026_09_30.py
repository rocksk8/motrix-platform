# -*- coding: utf-8 -*-
"""W3 #3 補：審核政策不變（沒有第二人就直接發布），但「送審中」與「直接發布」不能互相穿透。
  舊漏洞：超級管理員送審 v2 → 關審核（mode=off）→ 直接發布 v3 → 過期的 v2 還能被核可，把舊內容蓋回現行版。
  ① 這份定義有送審中的版本時，直接發布／還原 ⇒ 409（核心入口，寫鎖內判斷）
  ② 核可一份「依據的現行版已經不是它」的送審 ⇒ 409 過期（退回仍可，用來清掉）
  ③ 有送審中的定義時，改審核模式／審核人 ⇒ 409（同值不算變更）；決定完之後可以改
每一條都配「放行的對照組」。突變：各拿掉一道檢查，對應的題必須紅（見檔尾 MUTATIONS 說明）。"""
import pytest

KEY = "b3st"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _body(title="T"):
    return {"name": "過期測試", "permission": "custom." + KEY, "numbering": {"prefix": "ST", "period": "none", "digits": 3},
            "fields": [{"key": "title", "label": title, "type": "text", "required": True, "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}


def _draft(client, h, title="T"):
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body(title)})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text


def _publish(client, h):
    return client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={"note": "n"})


def _cfg(client, h, **kw):
    return client.put("/api/custom-modules/definition-review", headers=h, json=kw)


def _statuses():
    import db
    c = db.get_db()
    try:
        return [(r["version"], r["status"]) for r in c.execute(
            "SELECT version, status FROM ui_definitions WHERE kind='custom_module' AND key=? ORDER BY version", (KEY,)).fetchall()]
    finally:
        c.close()


def _force_settings(mode=None, reviewers=None):
    """繞過 API 直接改設定（模擬舊資料／別的路徑造成的「送審中 + 審核已關」）。"""
    from helpers.settings import _set_setting
    from helpers import custom_def_review as R
    if mode is not None:
        _set_setting(R.SETTING_KEY, True if mode == "on" else (False if mode == "off" else None))
    if reviewers is not None:
        _set_setting(R.REVIEWERS_KEY, reviewers)


@pytest.fixture()
def world(client, make_user):
    boss = _login(client, make_user, "st_boss", role="superadmin")
    appr = _login(client, make_user, "st_appr", role="admin", modules=[])
    assert _cfg(client, boss, reviewers=["st_appr"]).status_code == 200
    _draft(client, boss, "v1")
    r = _publish(client, boss)
    assert r.status_code == 200 and r.json()["pending"] is True          # 送審 v1
    return client, boss, appr


def test_direct_publish_and_restore_are_blocked_while_a_submission_is_open(world):
    client, boss, appr = world
    _force_settings(mode="off")                                          # 審核被關（模擬繞過）⇒ 原本會「直接發布」
    _draft(client, boss, "v2")
    r = _publish(client, boss)
    assert r.status_code == 409 and "送審中" in r.json()["detail"], r.text
    assert _statuses() == [(0, "draft"), (1, "submitted")]               # 沒有新版、送審還在
    r = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r.status_code in (400, 409, 422)                              # v1 還沒發布本來就不能還原；這裡只驗不會穿透
    assert _statuses() == [(0, "draft"), (1, "submitted")]
    # 其他 kind 不受影響（送審只存在於自訂模組定義）：放行的對照組
    from helpers import doc_template as dt
    assert client.put("/api/definitions/output_template/invoice_voucher/draft", headers=boss, json={"body": dt.load_default("invoice_voucher")}).status_code == 200
    assert client.post("/api/definitions/output_template/invoice_voucher/publish", headers=boss, json={}).status_code == 200


def test_restore_is_blocked_while_a_submission_is_open(client, make_user):
    boss = _login(client, make_user, "st_boss2", role="superadmin")
    _draft(client, boss, "a")
    assert _publish(client, boss).status_code == 200                     # 沒有審核人 ⇒ 直接發布 v1
    _draft(client, boss, "b")
    assert _publish(client, boss).status_code == 200                     # v2
    appr = _login(client, make_user, "st_appr2", role="admin", modules=[])
    assert _cfg(client, boss, reviewers=["st_appr2"]).status_code == 200
    _draft(client, boss, "c")
    assert _publish(client, boss).json()["pending"] is True              # 送審 v3
    _force_settings(mode="off")
    r = client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={})
    assert r.status_code == 409 and "送審中" in r.json()["detail"], r.text
    assert [v for v, _s in _statuses()] == [0, 1, 2, 3]
    # 對照：決定（退回）之後就放行
    _force_settings(mode="auto")
    assert client.post("/api/custom-modules/%s/definition/3/reject" % KEY, headers=appr, json={"note": "x"}).status_code == 200
    _force_settings(mode="off")
    assert client.post("/api/definitions/custom_module/%s/restore/1" % KEY, headers=boss, json={}).status_code == 200


def test_stale_submission_cannot_be_approved_but_can_be_rejected(world):
    client, boss, appr = world
    import db
    from core import definitions as D
    c = db.get_db()
    try:                                                                # 模擬「送審中卻多了一版現行版」（舊資料或別的路徑）
        D._insert_published(c, "custom_module", KEY, "company", _body("直接發布的 v2"), "bypass", "st_boss")
        c.commit()
    finally:
        c.close()
    r = client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={"note": "ok"})
    assert r.status_code == 409 and "過期" in r.json()["detail"], r.text
    assert (1, "submitted") in _statuses()                               # 沒有被核可
    cur = client.get("/api/custom/%s/meta" % KEY, headers=boss).json()
    assert "直接發布的 v2" in str(cur)                                    # 現行版沒有被舊內容蓋回
    r = client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "已過期，請重送"})
    assert r.status_code == 200                                          # 退回仍可（清掉過期的送審）


def test_fresh_submission_approves_normally(world):
    client, boss, appr = world
    r = client.post("/api/custom-modules/%s/definition/1/approve" % KEY, headers=appr, json={"note": "ok"})
    assert r.status_code == 200 and r.json()["published"] is True


def test_review_settings_cannot_change_while_a_submission_is_open(world):
    client, boss, appr = world
    r = _cfg(client, boss, mode="off")
    assert r.status_code == 409 and KEY in r.json()["detail"], r.text
    r = _cfg(client, boss, reviewers=["st_boss"])
    assert r.status_code == 409
    assert _cfg(client, boss, mode="auto", reviewers=["st_appr"]).status_code == 200      # 同值不算變更 ⇒ 放行
    assert client.post("/api/custom-modules/%s/definition/1/reject" % KEY, headers=appr, json={"note": "x"}).status_code == 200
    assert _cfg(client, boss, mode="off").status_code == 200                               # 決定完 ⇒ 可以改
