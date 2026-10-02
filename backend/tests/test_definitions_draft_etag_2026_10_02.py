# -*- coding: utf-8 -*-
"""K-2：定義草稿的並行保護（內容雜湊 etag＋409；設計 docs/platform/plans/DRAFT-CONCURRENCY-DESIGN.md 選項 C）。

核心（`core.definitions`）：`etag_of`、`save_draft(base_etag, force)`、`publish(base_etag)`、`DraftConflict`。
HTTP（`routers/definitions.py`）：PUT …/draft 帶 `base_etag`／`force`；POST …/publish 帶 `base_etag`；409 回 `code=draft_conflict`＋`current`；
稽核 `definitions.save_draft`（缺 base_etag ⇒ `unguarded:true`）、`definitions.save_draft_override`（記被覆蓋者）。
⚙️ 反向控制：沒帶 base_etag ⇒ 後寫者勝（過渡期行為不變）；兩個執行緒同一 etag ⇒ 恰一個成功。
"""
import json
import sqlite3
import threading

import pytest

from core import definitions as D

K = "k2_test"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    from core import migrations
    monkeypatch.setitem(D._EXTRA_KINDS, K, {"label": "K2"})
    c = sqlite3.connect(str(tmp_path / "k2.db"), isolation_level=None)
    c.isolation_level = ""
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL DEFAULT '')")
    migrations._core_v1_ui_definitions(c)
    yield c
    c.close()


def _etag(c):
    d = D.get(c, K, "a", "company", 0)
    return d["etag"] if d else ""


# ── 核心 ──────────────────────────────────────────────────────────────────

def test_etag_of_is_content_hash_of_the_stored_string_and_empty_for_none():
    assert D.etag_of(None) == "" and D.etag_of("") == ""
    a, b = D.etag_of('{"x": 1}'), D.etag_of('{"x":1}')
    assert len(a) == 16 and a != b                                  # 用原字串，不重新序列化
    assert D.etag_of('{"x": 1}') == a


def test_get_draft_carries_etag_and_published_rows_do_not(conn):
    assert _etag(conn) == ""
    d = D.save_draft(conn, K, "a", "company", {"v": 1}, "u1")
    assert d["etag"] and d["etag"] == _etag(conn)
    D.publish(conn, K, "a", "company", "n", "u1")
    assert "etag" not in D.get(conn, K, "a", "company") and D.get(conn, K, "a", "company", 0) is None


def test_save_without_base_etag_is_last_writer_wins_as_before(conn):
    D.save_draft(conn, K, "a", "company", {"v": 1}, "u1")
    d = D.save_draft(conn, K, "a", "company", {"v": 2}, "u2")                    # 舊呼叫端：不帶就照舊
    assert d["body"] == {"v": 2} and d["created_by"] == "u2" and "overridden" not in d


def test_matching_etag_saves_and_returns_a_new_etag(conn):
    e0 = D.save_draft(conn, K, "a", "company", {"v": 1}, "u1")["etag"]
    d = D.save_draft(conn, K, "a", "company", {"v": 2}, "u1", base_etag=e0)
    assert d["body"] == {"v": 2} and d["etag"] != e0 and d["etag"] == _etag(conn)


def test_stale_etag_raises_draft_conflict_and_writes_nothing(conn):
    e0 = D.save_draft(conn, K, "a", "company", {"v": 1}, "alice")["etag"]
    D.save_draft(conn, K, "a", "company", {"v": 2}, "bob", base_etag=e0)             # bob 先存
    before = D.get(conn, K, "a", "company", 0)
    with pytest.raises(D.DraftConflict) as ei:
        D.save_draft(conn, K, "a", "company", {"v": 99}, "alice", base_etag=e0)       # alice 還拿著舊戳
    assert isinstance(ei.value, D.DefinitionConflict)                                   # 沿用既有 409 對應
    assert ei.value.current["created_by"] == "bob" and ei.value.current["etag"] == before["etag"] and ei.value.current["created_at"]
    assert D.get(conn, K, "a", "company", 0) == before and not conn.in_transaction       # 資料庫不變、沒留開著的交易


def test_empty_base_etag_means_there_was_no_draft(conn):
    d = D.save_draft(conn, K, "a", "company", {"v": 1}, "alice", base_etag="")           # 沒草稿＋"" ⇒ 建立
    assert d["body"] == {"v": 1}
    with pytest.raises(D.DraftConflict):                                                  # 別人剛建了草稿，我還以為沒有
        D.save_draft(conn, K, "a", "company", {"v": 2}, "bob", base_etag="")
    with pytest.raises(D.DraftConflict):                                                  # 反向：以為有草稿、其實沒有（被刪／已發布）
        D.save_draft(conn, K, "zz", "company", {"v": 2}, "bob", base_etag="deadbeefdeadbeef")


def test_force_overwrites_and_reports_who_was_overwritten(conn):
    e0 = D.save_draft(conn, K, "a", "company", {"v": 1}, "alice")["etag"]
    D.save_draft(conn, K, "a", "company", {"v": 2}, "bob", base_etag=e0)
    d = D.save_draft(conn, K, "a", "company", {"v": 3}, "alice", base_etag=e0, force=True)
    assert d["body"] == {"v": 3} and d["overridden"]["created_by"] == "bob" and d["overridden"]["etag"]
    d2 = D.save_draft(conn, K, "a", "company", {"v": 4}, "alice", base_etag=d["etag"], force=True)   # force 但戳本來就對 ⇒ 不算覆蓋
    assert "overridden" not in d2


def test_same_content_saved_by_someone_else_is_not_a_conflict(conn):
    e0 = D.save_draft(conn, K, "a", "company", {"v": 1}, "alice")["etag"]
    D.save_draft(conn, K, "a", "company", {"v": 2}, "bob", base_etag=e0)
    D.save_draft(conn, K, "a", "company", {"v": 1}, "bob", base_etag=_etag(conn))        # 又改回去（ABA）：內容與 alice 載入時相同
    assert D.save_draft(conn, K, "a", "company", {"v": 5}, "alice", base_etag=e0)["body"] == {"v": 5}


@pytest.mark.parametrize("bad", [1, 0, True, ["x"], {"a": 1}])
def test_non_string_base_etag_is_rejected(conn, bad):
    with pytest.raises(D.DefinitionError):
        D.save_draft(conn, K, "a", "company", {"v": 1}, "u", base_etag=bad)
    with pytest.raises(D.DefinitionError):
        D.publish(conn, K, "a", "company", "", "u", base_etag=bad)


def test_publish_with_stale_etag_is_refused_and_current_etag_publishes(conn):
    e0 = D.save_draft(conn, K, "a", "company", {"v": 1}, "alice")["etag"]
    D.save_draft(conn, K, "a", "company", {"v": 2}, "bob", base_etag=e0)
    with pytest.raises(D.DraftConflict):
        D.publish(conn, K, "a", "company", "n", "alice", base_etag=e0)
    assert D.get(conn, K, "a", "company") is None and D.get(conn, K, "a", "company", 0)["body"] == {"v": 2}
    pub = D.publish(conn, K, "a", "company", "n", "alice", base_etag=_etag(conn))
    assert pub["version"] == 1 and pub["body"] == {"v": 2}
    D.save_draft(conn, K, "a", "company", {"v": 3}, "alice")
    assert D.publish(conn, K, "a", "company", "n", "alice")["version"] == 2                # 不帶＝照舊


def test_publish_with_etag_but_no_draft_keeps_the_old_message(conn):
    with pytest.raises(D.DefinitionError) as ei:
        D.publish(conn, K, "a", "company", "", "u", base_etag="")
    assert not isinstance(ei.value, D.DraftConflict) and "沒有草稿" in str(ei.value)


def test_concurrent_saves_with_the_same_base_etag_only_one_wins(tmp_path, monkeypatch):
    """寫鎖內比對（reverse control：若比對在鎖外，兩個都會通過）。兩條連線、兩個執行緒，同一個 base_etag。"""
    from core import migrations
    monkeypatch.setitem(D._EXTRA_KINDS, K, {"label": "K2"})
    path = str(tmp_path / "race.db")
    c0 = sqlite3.connect(path)
    c0.row_factory = sqlite3.Row
    c0.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL DEFAULT '')")
    migrations._core_v1_ui_definitions(c0)
    e0 = D.save_draft(c0, K, "a", "company", {"v": 0}, "seed")["etag"]
    c0.close()
    out, barrier = [], threading.Barrier(2)

    def go(n):
        c = sqlite3.connect(path, timeout=20)
        c.row_factory = sqlite3.Row
        barrier.wait()
        try:
            D.save_draft(c, K, "a", "company", {"v": n}, "u%d" % n, base_etag=e0)
            out.append("ok")
        except D.DraftConflict:
            out.append("conflict")
        finally:
            c.close()
    ts = [threading.Thread(target=go, args=(i,)) for i in (1, 2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == ["conflict", "ok"], out


# ── HTTP ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(client, make_user, monkeypatch):
    monkeypatch.setitem(D._EXTRA_KINDS, K, {"label": "K2"})
    u, p = make_user(username="k2_sa", role="superadmin")
    u2, p2 = make_user(username="k2_sa2", role="superadmin")
    u3, p3 = make_user(username="k2_adm", role="admin")

    def login(a, b):
        r = client.post("/api/auth/login", json={"username": a, "password": b})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}
    return client, {"a": login(u, p), "b": login(u2, p2), "adm": login(u3, p3)}


URL = "/api/definitions/%s/a" % K


def _actions(action):
    import db
    cn = db.get_db()
    try:
        return [json.loads(r["detail"] or "{}") for r in cn.execute("SELECT detail FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        cn.close()


def _put(c, h, body, **kw):
    return c.put(URL + "/draft", headers=h, json=dict({"body": body}, **kw))


def test_http_get_returns_draft_etag_and_put_returns_the_new_one(api):
    c, h = api
    assert c.get(URL, headers=h["a"]).json()["draft"] is None
    r = _put(c, h["a"], {"v": 1}, base_etag="")
    assert r.status_code == 200 and r.json()["etag"] and r.json()["draft"]["etag"] == r.json()["etag"]
    assert c.get(URL, headers=h["a"]).json()["draft"]["etag"] == r.json()["etag"]


def test_http_unguarded_put_still_works_and_is_audited_as_unguarded(api):
    c, h = api
    assert _put(c, h["a"], {"v": 1}).status_code == 200 and _put(c, h["b"], {"v": 2}).status_code == 200
    assert _actions("definitions.save_draft") == [{"unguarded": True}, {"unguarded": True}]
    e = c.get(URL, headers=h["a"]).json()["draft"]["etag"]
    assert _put(c, h["a"], {"v": 3}, base_etag=e).status_code == 200
    assert _actions("definitions.save_draft")[-1] == {}                                     # 帶了 etag ⇒ 不標 unguarded


def test_http_stale_put_is_409_with_code_and_current_and_does_not_write_or_audit(api):
    c, h = api
    e0 = _put(c, h["a"], {"v": 1}, base_etag="").json()["etag"]
    assert _put(c, h["b"], {"v": 2}, base_etag=e0).status_code == 200
    n = len(_actions("definitions.save_draft"))
    r = _put(c, h["a"], {"v": 99}, base_etag=e0)
    j = r.json()
    assert r.status_code == 409 and j["code"] == "draft_conflict" and j["current"]["created_by"] == "k2_sa2" and j["current"]["etag"]
    assert c.get(URL, headers=h["a"]).json()["draft"]["body"] == {"v": 2}
    assert len(_actions("definitions.save_draft")) == n and _actions("definitions.save_draft_override") == []


def test_http_force_overwrites_and_writes_the_override_audit_with_the_overwritten_author(api):
    c, h = api
    e0 = _put(c, h["a"], {"v": 1}, base_etag="").json()["etag"]
    _put(c, h["b"], {"v": 2}, base_etag=e0)
    r = _put(c, h["a"], {"v": 3}, base_etag=e0, force=True)
    assert r.status_code == 200 and c.get(URL, headers=h["a"]).json()["draft"]["body"] == {"v": 3}
    ov = _actions("definitions.save_draft_override")
    assert len(ov) == 1 and ov[0]["overridden"]["created_by"] == "k2_sa2" and ov[0]["overridden"]["etag"]
    assert _put(c, h["a"], {"v": 4}, base_etag=e0, force="yes").status_code == 409                  # 只認布林 true


@pytest.mark.parametrize("bad", [1, True, ["x"], {"a": 1}])
def test_http_non_string_base_etag_is_400(api, bad):
    c, h = api
    assert _put(c, h["a"], {"v": 1}, base_etag=bad).status_code == 400
    assert c.post(URL + "/publish", headers=h["a"], json={"base_etag": bad}).status_code == 400


def test_http_publish_with_stale_etag_is_409_and_with_current_etag_publishes(api):
    c, h = api
    e0 = _put(c, h["a"], {"v": 1}, base_etag="").json()["etag"]
    e1 = _put(c, h["b"], {"v": 2}, base_etag=e0).json()["etag"]
    r = c.post(URL + "/publish", headers=h["a"], json={"note": "n", "base_etag": e0})
    assert r.status_code == 409 and r.json()["code"] == "draft_conflict"
    assert c.get(URL, headers=h["a"]).json()["latest"] is None
    r = c.post(URL + "/publish", headers=h["a"], json={"note": "n", "base_etag": e1})
    assert r.status_code == 200 and r.json()["version"] == 1


def test_http_permissions_unchanged(api):
    c, h = api
    assert c.put(URL + "/draft", headers=h["adm"], json={"body": {"v": 1}, "base_etag": ""}).status_code in (401, 403)
    assert c.put(URL + "/draft", json={"body": {"v": 1}}).status_code in (401, 403)


def test_http_other_scopes_and_keys_have_independent_etags(api):
    c, h = api
    e_a = _put(c, h["a"], {"v": 1}, base_etag="").json()["etag"]
    r = c.put("/api/definitions/%s/b/draft" % K, headers=h["a"], json={"body": {"v": 1}, "base_etag": ""})      # 另一個 key 的草稿不存在 ⇒ "" 正確
    assert r.status_code == 200
    assert _put(c, h["a"], {"v": 2}, base_etag=e_a).status_code == 200
