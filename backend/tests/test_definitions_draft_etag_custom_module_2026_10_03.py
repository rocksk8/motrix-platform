# -*- coding: utf-8 -*-
"""K-2 補強（da 稽核 S1）：custom_module/company 的發布／送審，etag 比對必須在寫鎖內（D.publish／D.submit_draft），
不能只靠路由先擋。重現法：在路由的 mount_cap_problems 之後（＝先擋之後、寫入之前）插入「別人存的新草稿」，再帶舊戳發布／送審
⇒ 必須 409 draft_conflict，且不能把別人的內容發布出去。
⚙️ 反向控制：拿掉 helpers/custom_def_review.submit 轉傳 base_etag ⇒ 兩題紅（HTTP 200，發布的是別人的內容）。"""
import json

import pytest

KEY = "k2cm"
URL = "/api/definitions/custom_module/%s" % KEY


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _body(label="MINE"):
    return {"name": "並行測試", "permission": "custom." + KEY, "numbering": {"prefix": "KC", "period": "none", "digits": 3},
            "fields": [{"key": "title", "label": label, "type": "text", "required": True, "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}


def _rows():
    import db
    c = db.get_db()
    try:
        return [(r["version"], r["status"], json.loads(r["body_json"])["fields"][0]["label"])
                for r in c.execute("SELECT version, status, body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND version>0 ORDER BY version", (KEY,)).fetchall()]
    finally:
        c.close()


@pytest.fixture()
def world(client, make_user, monkeypatch):
    boss = _login(client, make_user, "k2cm_boss", role="superadmin")
    other = _login(client, make_user, "k2cm_other", role="superadmin")
    _login(client, make_user, "k2cm_appr", role="admin", modules=[])

    def inject_others_draft():
        """在 mount_cap_problems 之後，別人存了新草稿（用核心函式直接寫＝模擬另一個請求在窗口內寫入）。"""
        import db
        from core import definitions as D
        from helpers import custom_modules as cm
        real = cm.mount_cap_problems

        def hook(conn, key, body, manifests=None):
            out = real(conn, key, body, manifests)
            c2 = db.get_db()
            try:
                D.save_draft(c2, "custom_module", KEY, "company", _body("OTHERS"), "k2cm_other")
            finally:
                c2.close()
            return out
        monkeypatch.setattr(cm, "mount_cap_problems", hook)
    return client, boss, other, inject_others_draft


def _put(client, h, body, etag):
    r = client.put(URL + "/draft", headers=h, json={"body": body, "base_etag": etag})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    return r.json()["etag"]


def test_direct_publish_conflict_inside_the_window_is_409_and_publishes_nothing(world):
    client, boss, _o, inject = world
    e0 = _put(client, boss, _body("MINE"), "")
    inject()
    r = client.post(URL + "/publish", headers=boss, json={"note": "n", "base_etag": e0})
    assert r.status_code == 409 and r.json()["code"] == "draft_conflict", r.text
    assert _rows() == []                                                       # 別人的內容沒被發布出去


def test_review_enabled_submit_conflict_inside_the_window_is_409_and_submits_nothing(world):
    client, boss, _o, inject = world
    r = client.put("/api/custom-modules/definition-review", headers=boss, json={"reviewers": ["k2cm_appr"]})
    assert r.status_code == 200 and r.json()["active"] is True, r.text
    e0 = _put(client, boss, _body("MINE"), "")
    inject()
    r = client.post(URL + "/publish", headers=boss, json={"note": "n", "base_etag": e0})
    assert r.status_code == 409 and r.json()["code"] == "draft_conflict", r.text
    assert _rows() == []


def test_without_base_etag_the_old_behaviour_stays(world):
    client, boss, _o, _inject = world
    _put(client, boss, _body("MINE"), "")
    r = client.post(URL + "/publish", headers=boss, json={"note": "n"})
    assert r.status_code == 200 and _rows() == [(1, "published", "MINE")]
