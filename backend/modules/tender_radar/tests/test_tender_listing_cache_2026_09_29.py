"""標案清單快取（listing.py；2026-09-29 使用者：載入慢七秒，伺服器端先算好）。

驗：①命中快取不重建 ②每個寫入端點都呼叫 bump ③快取結果與重算逐字相同 ④資料庫簽章與 TTL 兜底
⑤背景預算只在啟用後排、去重、跑完後請求直接命中。
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

TENDERS = "/api/tender-radar/tenders"
WATCHES = "/api/tender-radar/watches"


def _auth(client, make_user):
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def lst():
    from modules.tender_radar import listing
    listing.reset()
    yield listing
    listing._WARM.update(enabled=False, pending=False)
    listing.reset()


@pytest.fixture()
def seeded(client, lst):
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no LIKE 'LC-%'")
        for i, (org, name) in enumerate([("臺中市政府", "監視系統建置"), ("乙機關", "網路設備採購"),
                                         ("丙機關", "門禁系統更新")], 1):
            conn.execute("INSERT INTO tenders (case_no, org, name, deadline, fetched_at) VALUES (?,?,?,?,?)",
                         (f"LC-{i}", org, name, f"2026-10-0{i}", "2026-09-29T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    lst.reset()
    yield
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no LIKE 'LC-%'")
        conn.commit()
    finally:
        conn.close()


def _count_builds(monkeypatch, lst):
    calls = []
    real = lst._build

    def counting(conn):
        calls.append(1)
        return real(conn)
    monkeypatch.setattr(lst, "_build", counting)
    return calls


def _cases(client, hdr, q=""):
    r = client.get(TENDERS + q, headers=hdr)
    assert r.status_code == 200, r.text
    return [x["caseNo"] for x in r.json()["items"] if x["caseNo"].startswith("LC-")]


def test_second_request_hits_the_cache(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    calls = _count_builds(monkeypatch, lst)
    a = client.get(TENDERS, headers=hdr).json()
    b = client.get(TENDERS + "?q=%E7%9B%A3%E8%A6%96", headers=hdr).json()   # 帶 q 也走同一份
    assert len(calls) == 1
    assert [x["caseNo"] for x in b["items"] if x["caseNo"].startswith("LC-")] == ["LC-1"]
    assert len(a["items"]) >= 3


def test_variant_character_search_still_works_from_cache(client, make_user, seeded, lst):
    hdr = _auth(client, make_user)
    # 資料是「臺中市政府」，使用者打「台中」（異體字表在後端）
    assert _cases(client, hdr, "?q=%E5%8F%B0%E4%B8%AD") == ["LC-1"]


def test_cached_result_equals_a_fresh_rebuild(client, make_user, seeded, lst):
    hdr = _auth(client, make_user)
    client.post(WATCHES, headers=hdr, json={"name": "監視", "keywords": ["監視"]})
    first = client.get(TENDERS, headers=hdr).json()
    warm = copy.deepcopy(first)
    lst.reset()
    assert client.get(TENDERS, headers=hdr).json() == warm
    assert any(x["matchedWatches"] for x in first["items"] if x["caseNo"] == "LC-1")


def test_every_write_endpoint_bumps(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    n = []
    real = lst.bump
    monkeypatch.setattr(lst, "bump", lambda: (n.append(1), real())[1])

    def bumped(fn):
        before = len(n)
        r = fn()
        assert r.status_code in (200, 201, 204), r.text
        assert len(n) > before, "這個寫入端點沒有呼叫 listing.bump()"
        return r

    wid = bumped(lambda: client.post(WATCHES, headers=hdr, json={"name": "w", "keywords": ["x"]})).json()["id"]
    bumped(lambda: client.put(f"{WATCHES}/{wid}", headers=hdr, json={"name": "w2", "keywords": ["y"]}))
    bumped(lambda: client.post(f"{TENDERS}/LC-1/mark", headers=hdr))
    bumped(lambda: client.delete(f"{TENDERS}/LC-1/mark", headers=hdr))
    bumped(lambda: client.delete(f"{WATCHES}/{wid}", headers=hdr))


def test_run_scan_bumps_after_a_recognised_fetch():
    import inspect
    from modules.tender_radar import source
    src = inspect.getsource(source.run_scan)
    assert "_listing.bump()" in src


def test_mark_and_unmark_show_up_immediately(client, make_user, seeded, lst):
    hdr = _auth(client, make_user)
    assert _cases(client, hdr)[0] == "LC-1"
    client.post(f"{TENDERS}/LC-3/mark", headers=hdr)
    assert _cases(client, hdr)[0] == "LC-3"
    client.delete(f"{TENDERS}/LC-3/mark", headers=hdr)
    assert _cases(client, hdr)[0] == "LC-1"


def test_direct_sql_insert_is_seen_via_signature(client, make_user, seeded, lst):
    import db
    hdr = _auth(client, make_user)
    assert "LC-9" not in _cases(client, hdr)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, org, name, deadline, fetched_at) VALUES (?,?,?,?,?)",
                     ("LC-9", "新機關", "新標案", "2026-10-09", "2026-09-29T12:00:00"))
        conn.commit()
    finally:
        conn.close()
    assert "LC-9" in _cases(client, hdr)


def test_ttl_forces_a_rebuild(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    calls = _count_builds(monkeypatch, lst)
    client.get(TENDERS, headers=hdr)
    monkeypatch.setattr(lst, "TTL_SECONDS", 0)
    client.get(TENDERS, headers=hdr)
    assert len(calls) == 2


def test_warm_is_off_until_enabled_and_dedupes_when_on(monkeypatch, lst):
    timers = []

    class FakeTimer:
        def __init__(self, delay, fn):
            timers.append((delay, fn))
            self.daemon = False

        def start(self):
            pass
    monkeypatch.setattr(lst.threading, "Timer", FakeTimer)
    lst.bump()
    assert timers == []                      # 沒啟用（測試／core-only）不背景跑
    lst.enable_warm()
    n0 = len(timers)
    assert n0 == 1                           # 啟動後的第一份
    lst.bump(); lst.bump(); lst.bump()
    assert len(timers) == n0                 # 已有一個排著 ⇒ 不重複排
    timers[0][1]()                           # 跑掉之後可再排
    lst.bump()
    assert len(timers) == n0 + 1


def test_warmed_cache_serves_the_first_user_request(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    lst._warm_once()                         # 背景預算做的事
    calls = _count_builds(monkeypatch, lst)
    client.get(TENDERS, headers=hdr)
    assert calls == []                       # 使用者第一次點進來不再重算
