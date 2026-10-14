# -*- coding: utf-8 -*-
"""T60 S1（D4）：伺服端強制『發布前一定先看過同一份草稿的預覽』（旗標 builder_governance.enabled；名單內的 kind；沒有後門）。
- 旗標關（預設）：發布不帶雜湊照常成功、回應與今天相同
- 旗標開、名單內的 kind：沒帶 ⇒ 409 preview_required；帶了但草稿之後被改 ⇒ 409 preview_stale；帶了正確的戳但沒有真的預覽過 ⇒ 409；
  別人的預覽不算；先預覽、再用同一個戳發布 ⇒ 成功
- 不在名單的 kind（排版器尚未送雜湊）：開著也照舊；沒有草稿 ⇒ 仍是原本的『沒有草稿』錯誤"""
import json
from pathlib import Path

import pytest

import db
from routers import def_governance as G
from routers import definitions as R

KIND, KEY = "expense_type", "travel"
BASE = "/api/definitions/%s/%s" % (KIND, KEY)
GOV = "/api/def-governance/%s/%s/impact" % (KIND, KEY)


def _shipped():
    return json.loads((Path(db.__file__).parent / "helpers" / "expense_type_defs" / "travel.json").read_text(encoding="utf-8"))


@pytest.fixture()
def api(client, make_user):
    out = {}
    for name in ("t60s1_a", "t60s1_b"):
        u, p = make_user(username=name, role="superadmin")
        r = client.post("/api/auth/login", json={"username": u, "password": p})
        assert r.status_code == 200, r.text
        out[name[-1]] = {"Authorization": "Bearer " + r.json()["token"]}
    return client, out


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setattr(R, "_governance_enabled", lambda conn=None: True)
    monkeypatch.setattr(G, "enabled", lambda conn=None: True)


def _draft(c, h, name="甲"):
    body = _shipped()
    body["name"] = name
    r = c.put(BASE + "/draft", headers=h, json={"body": body})
    assert r.status_code == 200, r.text
    return r.json()


def _versions(c, h):
    return c.get(BASE, headers=h).json().get("versions") or []


def test_flag_off_publish_without_hash_works_as_before(api):
    c, h = api
    _draft(c, h["a"])
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n"})
    assert r.status_code == 200 and r.json()["version"] == 1


def test_on_publish_without_hash_is_refused_and_nothing_is_published(api, flag_on):
    c, h = api
    _draft(c, h["a"])
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    assert not [v for v in _versions(c, h["a"]) if v["status"] == "published"]


def test_on_preview_then_publish_with_the_same_hash_succeeds(api, flag_on):
    c, h = api
    _draft(c, h["a"])
    j = c.get(GOV, headers=h["a"]).json()
    assert j["previewHash"]
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n", "preview_hash": j["previewHash"]})
    assert r.status_code == 200 and r.json()["version"] == 1


def test_on_draft_changed_after_the_preview_is_stale(api, flag_on):
    c, h = api
    _draft(c, h["a"], "甲")
    seen = c.get(GOV, headers=h["a"]).json()["previewHash"]
    _draft(c, h["a"], "乙")
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n", "preview_hash": seen})
    assert r.status_code == 409 and r.json()["code"] == "preview_stale"
    assert not [v for v in _versions(c, h["a"]) if v["status"] == "published"]


def test_on_the_right_hash_without_ever_previewing_is_refused(api, flag_on):
    """只知道草稿戳（例如從存草稿的回應拿到）不算『看過』：稽核裡要有這個人對這個戳的預覽紀錄。"""
    c, h = api
    etag = _draft(c, h["a"])["etag"]
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n", "preview_hash": etag})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"


def test_on_someone_elses_preview_does_not_count(api, flag_on):
    c, h = api
    _draft(c, h["a"])
    seen_by_b = c.get(GOV, headers=h["b"]).json()["previewHash"]
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n", "preview_hash": seen_by_b})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"


def test_on_kind_outside_the_list_and_missing_draft_behave_as_before(api, flag_on):
    c, h = api
    r = c.post(BASE + "/publish", headers=h["a"], json={"note": "n"})              # 沒有草稿 ⇒ 原本的錯誤，不是 preview_required
    assert r.status_code == 400 and "草稿" in r.json()["detail"]
    assert "layout" not in R._PREVIEW_ENFORCED_KINDS and "custom_fields" not in R._PREVIEW_ENFORCED_KINDS
    cf = "/api/definitions/custom_fields/invoice_vouchers"
    assert c.put(cf + "/draft", headers=h["a"], json={"body": {"fields": [{"key": "f0", "label": "甲", "type": "text"}]}}).status_code == 200
    assert c.post(cf + "/publish", headers=h["a"], json={"note": "n"}).status_code == 200


def test_the_audit_line_carries_the_hash_in_a_structured_field(api, flag_on):
    c, h = api
    _draft(c, h["a"])
    seen = c.get(GOV, headers=h["a"]).json()["previewHash"]
    conn = db.get_db()
    try:
        d = conn.execute("SELECT detail FROM audit_log WHERE action='definitions.previewed' ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(d) == {"previewHash": seen}
