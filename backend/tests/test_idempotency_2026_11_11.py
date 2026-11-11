"""請求冪等鍵（T80c 外勤手機，S1）：helpers/idempotency.py 與四個端點的接線。

釘住的事（弱訊號「回應掉了、伺服器其實已存好」時重送不會產生第二份）：
- 同 key＋同內容重送 ⇒ 重播第一次的回應；**只有一列資料、一個檔案、一次通知**。
- 沒帶標頭 ⇒ 行為與沒有這個機制時相同（兩次請求兩列）。
- 同 key 不同內容 ⇒ 422；處理中 ⇒ 409；處理失敗（4xx）⇒ 不留列，修正後可同 key 重送；陳舊的處理中 ⇒ 可接手。
- key 只在同一個使用者內唯一。
- 補檔案端點（形狀 B）：作者／admin+ 才能補；geo 只進檔案 metadata；拿鎖重讀追加。
"""
from tests._requires import requires_module  # noqa: E402
import json
import os
from datetime import datetime, timedelta

import pytest

pytestmark = requires_module("case", '端點測試打 M01（案件）的端點')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token, key=None):
    h = {"Authorization": "Bearer " + token}
    if key is not None:
        h["Idempotency-Key"] = key
    return h


def _png():
    return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _seed_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, status, deal_tag, total, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "客戶", "案件", "已送出", "已成案", 1000, json.dumps({"dealTag": "已成案"}),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return quote_no


def _count(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _migrated_db(client):
    """helper 單元題也要有已遷移的庫（idempotency_keys 是 core migration 建的）。"""
    yield


@pytest.fixture
def notified(monkeypatch):
    """計算 notify_module_activity 被呼叫幾次（案件端點與工作日誌端點各自 import 了一份）。"""
    calls = []
    from modules.case.api import quotations as Q
    from routers import system as S
    monkeypatch.setattr(Q, "notify_module_activity", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(S, "notify_module_activity", lambda *a, **k: calls.append(a))
    return calls


# ───────────────────────────── helper 單元 ─────────────────────────────

def test_parse_key():
    from fastapi import HTTPException
    from helpers import idempotency as I
    assert I.parse_key(None) is None
    assert I.parse_key("   ") is None
    assert I.parse_key("abcd1234-EFGH_5678") == "abcd1234-EFGH_5678"
    for bad in ("short", "has space in it", "x" * 129, "中文金鑰12345678", "a/b/c/d/e/f/g/h"):
        with pytest.raises(HTTPException) as e:
            I.parse_key(bad)
        assert e.value.status_code == 400


def test_new_then_replay_then_mismatch():
    from fastapi import HTTPException
    from helpers import idempotency as I
    h = I.request_hash("a", [("x.png", 10)])
    c1 = I.begin("u1", "key-00000001", "EP", h)
    assert c1 is not None and c1.replay is None
    c1.finish(201, {"id": 7, "n": "中文"})
    c2 = I.begin("u1", "key-00000001", "EP", h)
    assert c2.replay == {"status": 201, "body": {"id": 7, "n": "中文"}}
    resp = I.replay_response(c2)
    assert resp.status_code == 201 and resp.headers["Idempotent-Replay"] == "true"
    assert json.loads(resp.body)["n"] == "中文"
    with pytest.raises(HTTPException) as e:      # 內容不同
        I.begin("u1", "key-00000001", "EP", I.request_hash("b"))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:      # 端點不同
        I.begin("u1", "key-00000001", "OTHER", h)
    assert e.value.status_code == 422


def test_in_progress_409_then_stale_takeover():
    from fastapi import HTTPException
    import db
    from helpers import idempotency as I
    h = I.request_hash("a")
    I.begin("u2", "key-00000002", "EP", h)
    with pytest.raises(HTTPException) as e:
        I.begin("u2", "key-00000002", "EP", h)
    assert e.value.status_code == 409 and e.value.headers.get("Retry-After")
    old = (datetime.now() - timedelta(seconds=I.STALE_SECONDS + 5)).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE idempotency_keys SET created_at=? WHERE username='u2' AND key='key-00000002'", (old,))
    conn.commit()
    conn.close()
    c = I.begin("u2", "key-00000002", "EP", h)          # 陳舊 ⇒ 接手
    assert c is not None and c.replay is None
    with pytest.raises(HTTPException) as e:              # 接手後 created_at 更新 ⇒ 又是處理中
        I.begin("u2", "key-00000002", "EP", h)
    assert e.value.status_code == 409


def test_abort_frees_the_key_and_guard_aborts_on_exception():
    from helpers import idempotency as I
    h = I.request_hash("a")
    c = I.begin("u3", "key-00000003", "EP", h)
    c.abort()
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='key-00000003'") == 0
    c = I.begin("u3", "key-00000003", "EP", h)
    with pytest.raises(ValueError):
        with c.guard():
            raise ValueError("boom")
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='key-00000003'") == 0


def test_cancel_is_not_failure_row_stays_in_progress():
    """取消（CancelledError 是 BaseException）結果不明 ⇒ 不 abort，留給 stale 接手（不要在可能已寫入時放行重做）。"""
    import asyncio
    from helpers import idempotency as I
    c = I.begin("u4", "key-00000004", "EP", I.request_hash("a"))
    with pytest.raises(asyncio.CancelledError):
        with c.guard():
            raise asyncio.CancelledError()
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='key-00000004'") == 1


def _backdate(username, key, seconds):
    import db
    from helpers import idempotency as I
    old = (datetime.now() - timedelta(seconds=seconds)).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE idempotency_keys SET created_at=? WHERE username=? AND key=?", (old, username, key))
    conn.commit()
    conn.close()


def test_fencing_a_superseded_request_cannot_abort_the_takeovers_row():
    """K 審 M1／P1：c1 被 c2 接手（stale）後 c1 才失敗 abort ⇒ 不可以刪掉 c2 的 in_progress 列（否則第三次重送會與仍在跑的 c2 並行）。"""
    from fastapi import HTTPException
    from helpers import idempotency as I
    h = I.request_hash("a")
    c1 = I.begin("fence1", "fence-key-0001", "EP", h)
    _backdate("fence1", "fence-key-0001", I.STALE_SECONDS + 5)
    c2 = I.begin("fence1", "fence-key-0001", "EP", h)          # 接手
    assert c2.stamp != c1.stamp
    c1.abort()                                                    # 被取代者失敗 ⇒ no-op
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE username='fence1' AND key='fence-key-0001'") == 1
    with pytest.raises(HTTPException) as e:                       # 第三次重送：仍是「處理中」，不是全新請求
        I.begin("fence1", "fence-key-0001", "EP", h)
    assert e.value.status_code == 409
    c2.abort()                                                    # 接手者自己 abort 才真的釋放
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE username='fence1'") == 0


def test_fencing_a_superseded_request_cannot_overwrite_the_takeovers_response():
    """K 審 M1／P2：c2.finish 之後 c1.finish 不可以後蓋前；重播回的是接手者（c2）的回應。"""
    from helpers import idempotency as I
    h = I.request_hash("a")
    c1 = I.begin("fence2", "fence-key-0002", "EP", h)
    _backdate("fence2", "fence-key-0002", I.STALE_SECONDS + 5)
    c2 = I.begin("fence2", "fence-key-0002", "EP", h)
    c2.finish(201, {"id": 2})
    c1.finish(201, {"id": 1})                                     # 被取代者：no-op
    assert I.begin("fence2", "fence-key-0002", "EP", h).replay == {"status": 201, "body": {"id": 2}}


def test_fencing_a_superseded_request_finishing_first_does_not_complete_the_takeovers_row():
    from fastapi import HTTPException
    from helpers import idempotency as I
    h = I.request_hash("a")
    c1 = I.begin("fence3", "fence-key-0003", "EP", h)
    _backdate("fence3", "fence-key-0003", I.STALE_SECONDS + 5)
    c2 = I.begin("fence3", "fence-key-0003", "EP", h)
    c1.finish(201, {"id": 1})                                     # 被取代者先跑完：不可以把接手者的列標成 done
    with pytest.raises(HTTPException) as e:
        I.begin("fence3", "fence-key-0003", "EP", h)
    assert e.value.status_code == 409                             # 還是 in_progress（c2 還在跑）
    c2.finish(201, {"id": 2})
    assert I.begin("fence3", "fence-key-0003", "EP", h).replay["body"] == {"id": 2}


def test_run_wrapper_new_replay_and_failure_release():
    import asyncio
    from helpers import idempotency as I

    async def go():
        calls = []

        async def handler():
            calls.append(1)
            return {"n": len(calls)}
        h = I.request_hash("x")
        r1 = await I.run("runner1", "run-key-00001", "EP", h, handler, 201)
        r2 = await I.run("runner1", "run-key-00001", "EP", h, handler, 201)
        assert r1 == {"n": 1} and calls == [1]
        assert r2.status_code == 201 and json.loads(r2.body) == {"n": 1}      # 重播：handler 沒再跑
        assert await I.run("runner1", None, "EP", h, handler) == {"n": 2}       # 沒帶 key ⇒ 直接跑

        async def boom():
            raise ValueError("x")
        with pytest.raises(ValueError):
            await I.run("runner1", "run-key-00002", "EP", h, boom)
        assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='run-key-00002'") == 0
    asyncio.run(go())


def test_run_on_cancel_keeps_the_row_by_default_and_releases_it_when_asked():
    import asyncio
    from helpers import idempotency as I

    async def cancelled():
        raise asyncio.CancelledError()

    async def go():
        h = I.request_hash("c")
        with pytest.raises(asyncio.CancelledError):
            await I.run("runner2", "cancel-key-001", "EP", h, cancelled)
        with pytest.raises(asyncio.CancelledError):
            await I.run("runner2", "cancel-key-002", "EP", h, cancelled, abort_on_cancel=True)
    asyncio.run(go())
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='cancel-key-001'") == 1, "預設：結果不明 ⇒ 留著等 stale"
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='cancel-key-002'") == 0, "abort_on_cancel ⇒ 釋放"


def test_run_does_not_run_the_sync_db_work_on_the_event_loop_thread(monkeypatch):
    """K 審 N1：begin／finish 是同步 SQLite，必須離開事件迴圈執行緒。"""
    import asyncio
    import threading
    from helpers import idempotency as I
    seen = []
    real_begin, real_finish = I.begin, I.Call.finish

    def spy_begin(*a, **k):
        seen.append(("begin", threading.get_ident()))
        return real_begin(*a, **k)

    def spy_finish(self, *a, **k):
        seen.append(("finish", threading.get_ident()))
        return real_finish(self, *a, **k)
    monkeypatch.setattr(I, "begin", spy_begin)
    monkeypatch.setattr(I.Call, "finish", spy_finish)

    async def go():
        loop_thread = threading.get_ident()

        async def handler():
            return {"ok": True}
        await I.run("runner3", "thread-key-001", "EP", I.request_hash("t"), handler)
        return loop_thread
    loop_thread = asyncio.run(go())
    assert [n for n, _t in seen] == ["begin", "finish"]
    assert all(t != loop_thread for _n, t in seen), "同步 SQLite 不可以跑在事件迴圈執行緒上"


def test_keys_are_per_user():
    from helpers import idempotency as I
    h = I.request_hash("a")
    ca = I.begin("alice0", "shared-key-0001", "EP", h)
    ca.finish(200, {"who": "alice"})
    cb = I.begin("bob000", "shared-key-0001", "EP", h)   # 別人的同名 key ⇒ 全新，看不到 alice 的回應
    assert cb.replay is None


def test_purge_old_rows_on_write():
    import db
    from helpers import idempotency as I
    conn = db.get_db()
    old = (datetime.now() - timedelta(days=I.RETENTION_DAYS + 1)).isoformat()
    conn.execute("INSERT INTO idempotency_keys (username,key,endpoint,req_hash,state,created_at) "
                 "VALUES ('u5','old-key-000001','EP','h','done',?)", (old,))
    conn.commit()
    conn.close()
    I.begin("u5", "new-key-000001", "EP", I.request_hash("x"))
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='old-key-000001'") == 0


def test_finish_failure_does_not_raise(monkeypatch):
    from helpers import idempotency as I
    c = I.begin("u6", "key-00000006", "EP", I.request_hash("a"))
    monkeypatch.setattr(I, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    c.finish(200, {"ok": True})        # 不可丟例外


def test_migration_table_shape():
    import db
    conn = db.get_db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(idempotency_keys)").fetchall()}
    finally:
        conn.close()
    assert {"username", "key", "endpoint", "req_hash", "state", "status_code", "response_json",
            "created_at", "owner_unit_id"} <= cols


# ───────────────────────────── 案件留言 ─────────────────────────────

def test_case_update_duplicate_key_creates_one_row_one_file_one_notification(client, make_user, notified):
    u, p = make_user(username="idem_a", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-A")
    key = "case-post-0001"
    body = dict(data={"content": "現場"}, files=[("files", ("s.png", _png(), "image/png"))])
    r1 = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, key), **body)
    assert r1.status_code == 201, r1.text
    n_notified = len(notified)
    assert n_notified >= 1, "正對照：第一次請求要真的發了通知，否則下面的『重播不再通知』是空斷言"
    r2 = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, key), **body)
    assert r2.status_code == 201
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert r2.json() == r1.json()
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 1
    assert len(notified) == n_notified, "重播不可以再發通知"
    files = r1.json()["files"]
    folder = os.path.dirname(_abs(files[0]["path"]))
    assert len(os.listdir(folder)) == 1, "重播不可以再存一份檔案"


def _abs(rel):
    import helpers.uploads as up
    return os.path.join(up.UPLOADS_ROOT, rel)


def test_case_update_without_key_behaves_as_before(client, make_user, notified):
    u, p = make_user(username="idem_b", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-B")
    for _ in range(2):
        r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t), data={"content": "同一句"})
        assert r.status_code == 201 and "Idempotent-Replay" not in r.headers
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 2
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE username='idem_b'") == 0


def test_case_update_same_key_different_content_is_422(client, make_user):
    u, p = make_user(username="idem_c", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-C")
    assert client.post(f"/api/quotations/{q}/updates", headers=_auth(t, "case-post-0003"),
                       data={"content": "甲"}).status_code == 201
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, "case-post-0003"), data={"content": "乙"})
    assert r.status_code == 422
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 1


def test_case_update_failure_releases_key_so_fixed_request_can_reuse_it(client, make_user):
    u, p = make_user(username="idem_d", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-D")
    key = "case-post-0004"
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, key), data={"content": ""})   # 400：沒內容
    assert r.status_code == 400
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key=?", (key,)) == 0
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, key), data={"content": "補上內容"})
    assert r.status_code == 201


def test_case_update_bad_key_format_is_400(client, make_user):
    u, p = make_user(username="idem_e", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-E")
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, "bad key"), data={"content": "x"})
    assert r.status_code == 400
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 0


def test_key_does_not_leak_between_users(client, make_user):
    ua, pa = make_user(username="idem_f1", role="superadmin")
    ub, pb = make_user(username="idem_f2", role="superadmin")
    ta, tb = _login(client, ua, pa), _login(client, ub, pb)
    q = _seed_case("MQ-IDEM-F")
    same = "shared-key-0006"
    assert client.post(f"/api/quotations/{q}/updates", headers=_auth(ta, same), data={"content": "A"}).status_code == 201
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(tb, same), data={"content": "B"})
    assert r.status_code == 201 and "Idempotent-Replay" not in r.headers
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 2


def test_in_progress_request_gets_409(client, make_user):
    from helpers import idempotency as I
    u, p = make_user(username="idem_g", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-G")
    key = "case-post-0007"
    h = I.request_hash("同", "", [])
    I.begin("idem_g", key, f"POST case_update:{q}", h)       # 模擬另一個請求還在處理
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t, key), data={"content": "同"})
    assert r.status_code == 409 and r.headers.get("Retry-After")
    assert _count("SELECT COUNT(*) FROM case_updates WHERE quote_no=?", (q,)) == 0


# ───────────────────────────── 補檔案（形狀 B） ─────────────────────────────

def _post_text(client, t, q, text="先存文字"):
    r = client.post(f"/api/quotations/{q}/updates", headers=_auth(t), data={"content": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_add_files_appends_with_geo_and_replays(client, make_user, notified):
    u, p = make_user(username="idem_h", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-H")
    uid = _post_text(client, t, q)
    key = "files-add-0008"
    kw = dict(headers=_auth(t, key), data={"geo": "25.0330, 121.5654, 12.5"},
              files=[("files", ("a.png", _png(), "image/png"))])
    r1 = client.post(f"/api/quotations/{q}/updates/{uid}/files", **kw)
    assert r1.status_code == 201, r1.text
    assert r1.json()["added"] == 1
    assert r1.json()["files"][0]["geo"] == {"lat": 25.033, "lng": 121.5654, "acc": 12.5}
    n = len(notified)
    assert n >= 1, "正對照：第一次請求要真的發了通知"
    r2 = client.post(f"/api/quotations/{q}/updates/{uid}/files", **kw)
    assert r2.status_code == 201 and r2.headers.get("Idempotent-Replay") == "true"
    assert len(notified) == n
    stored = json.loads(_one("SELECT files_json FROM case_updates WHERE id=?", (uid,)))
    assert len(stored) == 1, "重播不可以再追加一次"
    # 第二張（新的 key）接在後面，不蓋掉第一張
    r3 = client.post(f"/api/quotations/{q}/updates/{uid}/files", headers=_auth(t, "files-add-0009"),
                     files=[("files", ("b.png", _png(), "image/png"))])
    assert r3.status_code == 201
    stored = json.loads(_one("SELECT files_json FROM case_updates WHERE id=?", (uid,)))
    assert [f["filename"] for f in stored] == ["a.png", "b.png"]
    assert "geo" not in stored[1]


def _one(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("geo", ["", "abc", "91,0", "0,181", "1", "1,2,3,4", "nan,1", "25.0,121.5,-1"])
def test_add_files_bad_geo_is_ignored_not_rejected(client, make_user, geo):
    u, p = make_user(username="idem_i", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-I-" + str(abs(hash(geo)) % 10000))
    uid = _post_text(client, t, q)
    r = client.post(f"/api/quotations/{q}/updates/{uid}/files", headers=_auth(t),
                    data={"geo": geo}, files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    if geo == "25.0,121.5,-1":
        assert f["geo"] == {"lat": 25.0, "lng": 121.5}      # 負的精度只丟精度
    else:
        assert "geo" not in f


def test_add_files_only_author_or_admin(client, make_user):
    ua, pa = make_user(username="idem_j1", role="superadmin")
    ta = _login(client, ua, pa)
    q = _seed_case("MQ-IDEM-J")
    uid = _post_text(client, ta, q)
    ub, pb = make_user(username="idem_j2", role="user", modules=["case_manage"])
    tb = _login(client, ub, pb)
    r = client.post(f"/api/quotations/{q}/updates/{uid}/files", headers=_auth(tb),
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code in (403, 404), r.text            # 非作者：403（或案件看不到＝404）
    assert json.loads(_one("SELECT files_json FROM case_updates WHERE id=?", (uid,))) == []


def test_add_files_unknown_update_404_and_failure_releases_key(client, make_user):
    u, p = make_user(username="idem_k", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-K")
    key = "files-add-0011"
    r = client.post(f"/api/quotations/{q}/updates/999999/files", headers=_auth(t, key),
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 404
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key=?", (key,)) == 0


def test_add_files_bad_extension_rejected_and_leaves_update_unchanged(client, make_user):
    u, p = make_user(username="idem_l", role="superadmin")
    t = _login(client, u, p)
    q = _seed_case("MQ-IDEM-L")
    uid = _post_text(client, t, q)
    r = client.post(f"/api/quotations/{q}/updates/{uid}/files", headers=_auth(t, "files-add-0012"),
                    files=[("files", ("evil.exe", b"MZ....", "application/octet-stream"))])
    assert r.status_code == 400
    assert json.loads(_one("SELECT files_json FROM case_updates WHERE id=?", (uid,))) == []
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key='files-add-0012'") == 0


# ───────────────────────────── 工作日誌 ─────────────────────────────

def _uid(username):
    return _one("SELECT id FROM users WHERE username=?", (username,))


def test_work_log_duplicate_key_creates_one_row(client, make_user, notified):
    u, p = make_user(username="idem_m", role="superadmin")
    t = _login(client, u, p)
    body = {"log_date": "2026-11-11", "user_id": _uid(u), "content": "巡檢", "hours": 2}
    r1 = client.post("/api/work-logs", headers=_auth(t, "work-log-0013"), json=body)
    assert r1.status_code in (200, 201), r1.text
    n = len(notified)
    assert n >= 1, "正對照：第一次請求要真的發了通知"
    r2 = client.post("/api/work-logs", headers=_auth(t, "work-log-0013"), json=body)
    assert r2.status_code == r1.status_code and r2.json() == r1.json()
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert len(notified) == n
    assert _count("SELECT COUNT(*) FROM work_logs WHERE content='巡檢'") == 1
    r3 = client.post("/api/work-logs", headers=_auth(t), json=body)          # 沒帶 key ⇒ 照舊再建一筆
    assert r3.status_code == r1.status_code
    assert _count("SELECT COUNT(*) FROM work_logs WHERE content='巡檢'") == 2


def test_work_log_validation_error_releases_key(client, make_user):
    u, p = make_user(username="idem_n", role="superadmin")
    t = _login(client, u, p)
    key = "work-log-0014"
    r = client.post("/api/work-logs", headers=_auth(t, key), json={"log_date": "", "user_id": _uid(u), "content": "x"})
    assert r.status_code == 400
    assert _count("SELECT COUNT(*) FROM idempotency_keys WHERE key=?", (key,)) == 0


def test_work_log_photos_duplicate_key_adds_once(client, make_user, notified):
    u, p = make_user(username="idem_o", role="superadmin")
    t = _login(client, u, p)
    r = client.post("/api/work-logs", headers=_auth(t),
                    json={"log_date": "2026-11-11", "user_id": _uid(u), "content": "拍照", "hours": 1})
    wid = r.json()["id"]
    kw = dict(headers=_auth(t, "work-photo-0015"), files=[("files", ("a.png", _png(), "image/png"))])
    r1 = client.post(f"/api/work-logs/{wid}/photos", **kw)
    assert r1.status_code == 201, r1.text
    n = len(notified)
    assert n >= 1, "正對照：第一次請求要真的發了通知"
    r2 = client.post(f"/api/work-logs/{wid}/photos", **kw)
    assert r2.status_code == 201 and r2.headers.get("Idempotent-Replay") == "true" and r2.json() == r1.json()
    assert len(notified) == n
    assert len(json.loads(_one("SELECT photos FROM work_logs WHERE id=?", (wid,)))) == 1
