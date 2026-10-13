# -*- coding: utf-8 -*-
"""T60 S2（D3）：定義的放寬分類＋單一發布管線（旗標 builder_governance.enabled；名單內的 kind＝custom_fields）。
- 比較函式：新增欄位／移除欄位／只改顯示文字／必填變動／看不懂的屬性（＝放寬）／沒有比較函式的種類（＝放寬）／比較壞掉（＝放寬）
- 旗標關：發布與今天相同（立即、沒有 pending、帳本沒有 def 列）；新路由 404
- 旗標開：放寬 ⇒ 不發布、待核准（申請人不能核准自己的；要另一位；確認期間未過不能套用；期間內可撤銷）；收緊或不變 ⇒ 立即發布並記帳本
- 還原到較寬鬆的版本 ⇒ 待核准（不蓋掉不同內容的草稿）；還原到較嚴的版本 ⇒ 立即"""
import pytest

import db
from core import definitions as D
from helpers import config_ledger as L
from helpers import settings_registry as SR
from routers import def_pipeline as P

KEY = "invoice_vouchers"
BASE = "/api/definitions/custom_fields/" + KEY


def _body(*keys, **extra):
    return {"fields": [dict({"key": k, "label": k.upper(), "type": "text"}, **extra) for k in keys]}


# ── 比較函式 ────────────────────────────────────────────────────────────────────────
def test_custom_fields_classification():
    c = P.classify
    assert c("custom_fields", _body("a"), _body("a", "b"))[0] == "loosen"                       # 新增欄位
    assert c("custom_fields", _body("a", "b"), _body("a"))[0] == "tighten"                      # 移除欄位
    assert c("custom_fields", _body("a"), dict(_body("a"), fields=[{"key": "a", "label": "改名", "type": "text"}]))[0] == "neutral"   # 只改顯示文字
    assert c("custom_fields", _body("a"), _body("a"))[0] == "neutral"
    assert c("custom_fields", _body("a", required=True), _body("a", required=False))[0] == "loosen"
    assert c("custom_fields", _body("a", required=False), _body("a", required=True))[0] == "tighten"
    assert c("custom_fields", _body("a"), _body("a", maxLength=10))[0] == "loosen"            # 看不懂寬嚴的屬性 ⇒ 放寬
    assert c("custom_fields", _body("a", "b"), _body("a", "c"))[0] == "loosen"                  # 一增一減：只要有放寬就算放寬
    assert c("no_such_kind", {}, {})[0] == "loosen"                                              # 沒有比較函式 ⇒ 放寬
    assert c("custom_fields", None, {"fields": "壞"})[0] in ("loosen", "neutral", "tighten")     # 不丟例外


def test_a_broken_comparator_counts_as_loosen(monkeypatch):
    monkeypatch.setitem(P.COMPARATORS, "custom_fields", lambda a, b: 1 / 0)
    assert P.classify("custom_fields", {}, {})[0] == "loosen"


def test_layout_classification():
    c = P.classify
    hide = {"op": "hide", "target": "x:y/sidebar"}
    rel = {"op": "relabel", "target": "x:y/sidebar", "label": "新"}
    assert c("layout", {"ops": []}, {"ops": [hide]})[0] == "tighten"
    assert c("layout", {"ops": [hide]}, {"ops": []})[0] == "loosen"
    assert c("layout", {"ops": []}, {"ops": [rel]})[0] == "neutral"
    assert c("layout", {"ops": []}, {"ops": [{"op": "weird"}]})[0] == "loosen"
    assert P.ACTIVE_KINDS == ("custom_fields", "layout")


# ── 端點 ────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def api(client, make_user):
    out = {}
    for n in ("a", "b"):
        u, p = make_user(username="t60s2_" + n, role="superadmin")
        r = client.post("/api/auth/login", json={"username": u, "password": p})
        assert r.status_code == 200, r.text
        out[n] = {"Authorization": "Bearer " + r.json()["token"]}
    u, p = make_user(username="t60s2_adm", role="admin")
    out["adm"] = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    return client, out


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)


@pytest.fixture()
def past(monkeypatch):
    """確認期間設成『已過』（真實下限是 1 天；這裡只為了測套用）。"""
    monkeypatch.setattr(SR, "confirm_period_days", lambda conn=None: -1)


def _draft(c, h, body):
    r = c.put(BASE + "/draft", headers=h, json={"body": body})
    assert r.status_code == 200, r.text


def _publish(c, h, note="n"):
    return c.post(BASE + "/publish", headers=h, json={"note": note})


def _published(c, h):
    return [v for v in c.get(BASE, headers=h).json().get("versions", []) if v["status"] == "published"]


def _ledger_rows():
    conn = db.get_db()
    try:
        return L.history(conn, "def", None, limit=100)
    finally:
        conn.close()


def _go_live(c, h, body):
    """用管線走完一次放寬：A 送出、B 核准、套用（確認期間已過）。"""
    _draft(c, h["a"], body)
    r = _publish(c, h["a"])
    assert r.status_code == 200 and r.json()["pending"] is True, r.text
    cid = r.json()["changeId"]
    assert c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={}).status_code == 200
    a = c.post("/api/def-pipeline/changes/%d/activate" % cid, headers=h["a"], json={})
    assert a.status_code == 200, a.text
    return a.json()


def test_off_publish_is_immediate_and_new_routes_are_404(api):
    c, h = api
    _draft(c, h["a"], _body("a"))
    r = _publish(c, h["a"])
    assert r.status_code == 200 and r.json()["version"] == 1 and "pending" not in r.json()
    assert not _ledger_rows()
    assert c.get("/api/def-pipeline/pending", headers=h["a"]).status_code == 404
    assert c.post("/api/def-pipeline/changes/1/approve", headers=h["a"], json={}).status_code == 404
    assert c.get("/api/def-pipeline/pending").status_code == 401


def test_on_non_superadmin_is_refused(api, on):
    c, h = api
    assert c.get("/api/def-pipeline/pending", headers=h["adm"]).status_code in (401, 403)


def test_on_loosening_publish_is_pending_not_published(api, on):
    c, h = api
    _draft(c, h["a"], _body("a"))
    r = _publish(c, h["a"])
    j = r.json()
    assert r.status_code == 200 and j["pending"] is True and j["status"] == "submitted" and j["reasons"] and j["changeId"]
    assert not _published(c, h["a"])                                                           # 沒有發布
    rows = _ledger_rows()
    assert len(rows) == 1 and rows[0]["state"] == "pending" and rows[0]["approvals_required"] == 1 and rows[0]["risk"] == "security"
    assert rows[0]["effective_at"] > rows[0]["at"]                                              # 確認期間在未來（預設 7 天）
    p = c.get("/api/def-pipeline/pending", headers=h["b"]).json()["items"]
    assert len(p) == 1 and p[0]["kind"] == "custom_fields" and p[0]["key"] == KEY and p[0]["scope"] == "company" and p[0]["ready"] is False
    again = _publish(c, h["a"])                                                                  # 已有待核准的版本：不可再送（也不會繞過）
    assert again.status_code in (400, 409)


def test_on_requester_cannot_approve_own_and_activation_needs_approval_and_time(api, on):
    c, h = api
    _draft(c, h["a"], _body("a"))
    cid = _publish(c, h["a"]).json()["changeId"]
    own = c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["a"], json={})
    assert own.status_code == 409 and "自己" in own.json()["detail"]
    assert c.post("/api/def-pipeline/changes/%d/activate" % cid, headers=h["b"], json={}).status_code == 409      # 沒有核准
    assert c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={}).status_code == 200
    assert c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={}).status_code == 409      # 同一人不能投兩次
    early = c.post("/api/def-pipeline/changes/%d/activate" % cid, headers=h["a"], json={})
    assert early.status_code == 409 and "確認期間" in early.json()["detail"]                                      # 核准了，但期間未過
    assert not _published(c, h["a"])


def test_on_approved_and_due_change_is_applied_by_activation(api, on, past):
    c, h = api
    d = _go_live(c, h, _body("a"))
    assert d["status"] == "published" and d["version"] == 1
    assert [v["version"] for v in _published(c, h["a"])] == [1]
    rows = _ledger_rows()
    assert rows[0]["state"] == "activated" and len(rows[0]["approvals"]) == 1
    assert c.get("/api/def-pipeline/pending", headers=h["a"]).json()["items"] == []
    assert c.post("/api/def-pipeline/changes/%d/activate" % rows[0]["id"], headers=h["a"], json={}).status_code == 409   # 不能重複套用


def test_on_cancel_within_the_period_rejects_the_submission(api, on):
    c, h = api
    _draft(c, h["a"], _body("a"))
    cid = _publish(c, h["a"]).json()["changeId"]
    assert c.post("/api/def-pipeline/changes/%d/cancel" % cid, headers=h["b"], json={"reason": "不要"}).status_code == 200
    assert not _published(c, h["a"]) and _ledger_rows()[0]["state"] == "cancelled"
    assert c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={}).status_code == 409        # 已撤銷
    r = _publish(c, h["a"])                                                                                          # 撤銷後可以重送
    assert r.status_code == 200 and r.json()["pending"] is True


def test_on_tightening_and_neutral_changes_publish_immediately_and_are_ledgered(api, on, past):
    c, h = api
    _go_live(c, h, _body("a", "b"))
    _draft(c, h["a"], _body("a"))                                                               # 移除欄位 ＝ 收緊
    r = _publish(c, h["a"])
    assert r.status_code == 200 and r.json()["version"] == 2 and "pending" not in r.json()
    _draft(c, h["a"], {"fields": [{"key": "a", "label": "只改文字", "type": "text"}]})          # 只改顯示文字 ＝ 不變
    r = _publish(c, h["a"])
    assert r.status_code == 200 and r.json()["version"] == 3
    acts = [x["reason"] for x in _ledger_rows()]
    conn = db.get_db()
    try:
        actions = [x[0] for x in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'definitions.publish_%' ORDER BY id").fetchall()]
    finally:
        conn.close()
    assert actions == ["definitions.publish_tighten", "definitions.publish_neutral"] and len(acts) == 3


def test_on_restore_to_a_looser_version_is_pending_and_to_a_stricter_one_is_immediate(api, on, past):
    c, h = api
    _go_live(c, h, _body("a", "b"))                                                              # v1 兩個欄位
    _draft(c, h["a"], _body("a"))
    assert _publish(c, h["a"]).json()["version"] == 2                                            # v2 收緊（立即）
    r = c.post(BASE + "/restore/1", headers=h["a"], json={})                                     # 回到兩個欄位 ＝ 放寬
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["message"]
    assert [v["version"] for v in _published(c, h["a"])] == [2, 1]                               # 沒有新版本被發布
    cid = r.json()["changeId"]
    assert c.post("/api/def-pipeline/changes/%d/cancel" % cid, headers=h["b"], json={}).status_code == 200
    # 有不同內容的草稿 ⇒ 不蓋掉
    _draft(c, h["a"], _body("a", "z"))
    blocked = c.post(BASE + "/restore/1", headers=h["a"], json={})
    assert blocked.status_code == 409 and "草稿" in blocked.json()["detail"]
    assert c.get(BASE, headers=h["a"]).json()["draft"]["body"] == _body("a", "z")
    # 較嚴的版本 ⇒ 立即：先讓 live 是兩欄位（v1 的內容）
    assert c.delete(BASE + "/draft", headers=h["a"]).status_code == 200


def test_on_restore_to_stricter_is_immediate(api, on, past):
    c, h = api
    _go_live(c, h, _body("a"))                                                                    # v1 一個欄位
    _draft(c, h["a"], _body("a", "b"))
    cid = _publish(c, h["a"]).json()["changeId"]
    c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={})
    assert c.post("/api/def-pipeline/changes/%d/activate" % cid, headers=h["a"], json={}).json()["version"] == 2
    r = c.post(BASE + "/restore/1", headers=h["a"], json={})                                      # 回到一個欄位 ＝ 收緊
    assert r.status_code == 200 and r.json()["version"] == 3 and "pending" not in r.json()


def test_kinds_outside_the_active_list_are_untouched(api, on):
    c, h = api
    assert "expense_type" not in P.ACTIVE_KINDS
    import json
    from pathlib import Path
    body = json.loads((Path(db.__file__).parent / "helpers" / "expense_type_defs" / "travel.json").read_text(encoding="utf-8"))
    b = "/api/definitions/expense_type/travel"
    assert c.put(b + "/draft", headers=h["a"], json={"body": body}).status_code == 200
    r = c.post(b + "/publish", headers=h["a"], json={"note": "n"})
    assert r.status_code == 200 and r.json()["version"] == 1 and "pending" not in r.json()


def _layout_target():
    from core import registry
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            if isinstance(p, dict) and p.get("menu"):
                return m.key, "%s:%s/sidebar" % (m.key, p["path"])
    pytest.skip("沒有宣告選單項的模組")


def test_on_layout_publish_goes_through_the_pipeline(api, on, past):
    """版面：新增 hide ＝收緊（立即）；移除 hide ＝放寬（待核准）；改名／搬移不變（立即）。"""
    c, h = api
    mod, tgt = _layout_target()
    url = "/api/definitions/layout/module:%s" % mod
    hide = {"op": "hide", "target": tgt}
    assert c.put(url + "/draft", headers=h["a"], json={"body": {"ops": [hide]}}).status_code == 200
    r = c.post(url + "/publish", headers=h["a"], json={"note": "n"})
    assert r.status_code == 200 and r.json()["version"] == 1 and "pending" not in r.json()            # 收緊 ⇒ 立即
    assert c.put(url + "/draft", headers=h["a"], json={"body": {"ops": []}}).status_code == 200
    r = c.post(url + "/publish", headers=h["a"], json={"note": "n"})
    j = r.json()
    assert r.status_code == 200 and j["pending"] is True and j["version"] == 2 and j["effectiveAt"] and j["reasons"]   # 放寬 ⇒ 待核准（3c 的編輯器用的鍵）
    live = c.get(url, headers=h["a"]).json()
    assert live["latest"]["version"] == 1                                                              # 生效中的還是第 1 版
    cid = j["changeId"]
    assert c.post("/api/def-pipeline/changes/%d/approve" % cid, headers=h["b"], json={}).status_code == 200
    a = c.post("/api/def-pipeline/changes/%d/activate" % cid, headers=h["b"], json={})
    assert a.status_code == 200 and a.json()["version"] == 2
    p = [x for x in _ledger_rows() if x["domain"] == "def:layout"]
    assert p and p[0]["field"] == "company|module:%s" % mod and p[0]["key"] == ("module.%s" % mod)    # 帳本的 key 把 ':' 換成 '.'，真正的 key 在 field

