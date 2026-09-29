"""標案清單快取（listing.py；2026-09-29 使用者：載入慢七秒，伺服器端先算好）。

驗：①命中快取不重建 ②每個寫入端點都呼叫 bump ③快取結果與重算逐字相同 ④資料庫簽章兜底、沒有 TTL
⑤背景預算只在啟用後排、去重、跑完後請求直接命中 ⑥請求端永不同步分類：有舊結果就先回舊的（stale-while-revalidate），
只有「從來沒算過」才同步算 ⑦使用者寫入端自己算完才回、快取的是 JSON 位元組。
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
    monkeypatch.setattr(lst, "bump", lambda *a, **k: (n.append(1), real(*a, **k))[1])

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
    assert "_listing.bump(background=True)" in src   # 抓取寫入後背景重算，不在抓取執行緒同步算、也不讓請求端算


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


def test_there_is_no_ttl_rebuild(client, make_user, seeded, lst, monkeypatch):
    """使用者裁示：只有定期抓取／使用者改條件時才計算——時間到了不重算。"""
    assert not hasattr(lst, "TTL_SECONDS")
    hdr = _auth(client, make_user)
    calls = _count_builds(monkeypatch, lst)
    client.get(TENDERS, headers=hdr)
    client.get(TENDERS, headers=hdr)
    assert len(calls) == 1


class _FakeTimer:
    made = []

    def __init__(self, delay, fn):
        self.delay, self.fn, self.daemon = delay, fn, False
        _FakeTimer.made.append(self)

    def start(self):
        pass


@pytest.fixture()
def timers(monkeypatch, lst):
    _FakeTimer.made = []
    monkeypatch.setattr(lst.threading, "Timer", _FakeTimer)
    return _FakeTimer.made


def test_warm_is_off_until_enabled_and_dedupes_when_on(lst, timers):
    lst.bump(background=True)
    assert timers == []                      # 沒啟用（測試／core-only）不背景跑
    lst.enable_warm()
    assert len(timers) == 1                  # 啟動後的第一份
    lst.bump(background=True); lst.bump(background=True)
    assert len(timers) == 1                  # 已有一個排著 ⇒ 不重複排
    timers[0].fn()                           # 跑掉之後可再排
    lst.bump(background=True)
    assert len(timers) == 2


def test_warmed_cache_serves_the_first_user_request(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    lst._warm_once()                         # 背景預算做的事
    calls = _count_builds(monkeypatch, lst)
    client.get(TENDERS, headers=hdr)
    assert calls == []                       # 使用者第一次點進來不再重算


def test_never_computed_is_the_only_case_that_classifies_in_the_request(client, make_user, seeded, lst, timers, monkeypatch):
    hdr = _auth(client, make_user)
    lst.enable_warm()
    calls = _count_builds(monkeypatch, lst)
    assert _cases(client, hdr) == ["LC-1", "LC-2", "LC-3"] and len(calls) == 1
    client.get(TENDERS, headers=hdr)
    assert len(calls) == 1


def test_after_a_scan_bump_requests_get_the_old_result_and_never_classify(client, make_user, seeded, lst, timers, monkeypatch):
    import db
    hdr = _auth(client, make_user)
    lst.enable_warm()
    lst._warm_once()                         # 熱的
    calls = _count_builds(monkeypatch, lst)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, org, name, deadline, fetched_at) VALUES (?,?,?,?,?)",
                     ("LC-9", "新機關", "新標案", "2026-10-09", "2026-09-29T12:00:00"))
        conn.commit()
    finally:
        conn.close()
    lst.bump(background=True)                # 抓取寫入後
    old = _cases(client, hdr)
    assert calls == [], "請求端在有舊結果時不可同步分類"
    assert "LC-9" not in old                 # 先回舊的
    pending = [t for t in timers if t.delay == 0 or t.delay == lst._WARM_DELAY_SECONDS]
    assert pending, "沒有排背景重算"
    pending[-1].fn()                         # 背景重算完成
    assert len(calls) == 1                   # 重算發生在背景
    assert "LC-9" in _cases(client, hdr) and len(calls) == 1


def test_user_write_rebuilds_in_the_write_not_in_the_next_read(client, make_user, seeded, lst, monkeypatch):
    hdr = _auth(client, make_user)
    client.get(TENDERS, headers=hdr)
    calls = _count_builds(monkeypatch, lst)
    client.post(f"{TENDERS}/LC-3/mark", headers=hdr)
    assert len(calls) == 1                   # 寫入端算的
    assert _cases(client, hdr)[0] == "LC-3" and len(calls) == 1   # 重讀不再算


def test_serialized_json_bytes_are_cached(client, make_user, seeded, lst):
    hdr = _auth(client, make_user)
    client.get(TENDERS, headers=hdr)
    conn = __import__("db").get_db()
    try:
        a = lst.respond(conn, None, "台中")
        b = lst.respond(conn, None, "台中")
    finally:
        conn.close()
    assert a is b and isinstance(a, bytes)
