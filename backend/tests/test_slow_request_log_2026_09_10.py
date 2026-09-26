"""2026-09-10：慢請求記錄（`main.py::slow_request_log`）。

背景：`db.py::_connect()` 用 `sqlite3.connect(path, timeout=30)`，任何一次寫入
在鎖被佔住時最多會等 **30 秒**。追 flaky e2e 時逐段計時證實：卡住的是主
INSERT/commit 本身（SQLite 單一寫入者的本質），不是 commit 之後那幾筆
notification／audit 寫入。

把可能長時間佔鎖的地方查過一輪後確認正式路徑沒有這種東西（`reset_demo_db()`
的 VACUUM 只動 demo 獨立檔案、另一個 VACUUM 在 migration、三處 BEGIN IMMEDIATE
都是刻意的短交易），所以**沒有**對寫入路徑動刀。但真的發生時完全看不見——
使用者只覺得「這次存檔特別久」，不會回報也沒有紀錄。這條 middleware 就是那道
保險：超過門檻寫一行 log，不改變任何行為。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import logging
import sqlite3
import threading
import time
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_fast_request_is_not_logged(client, make_user, caplog):
    """一般速度的請求不該產生任何 SLOW REQUEST——這條 log 要是天天出現就沒有訊號價值。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    with caplog.at_level(logging.WARNING):
        r = client.get("/api/next-quote-no", headers=_auth(token))
    assert r.status_code == 200
    assert "SLOW REQUEST" not in caplog.text


def test_slow_request_is_logged(client, make_user, caplog, monkeypatch):
    """超過門檻的請求要留下一行含耗時、方法、路徑的紀錄。
    用把門檻調到 0 的方式觸發，不需要真的讓請求變慢（那會拖慢整個測試套件）。"""
    import main

    username, password = make_user(username="slow_user", role="admin")
    token = _login(client, username, password)

    monkeypatch.setattr(main, "_SLOW_REQUEST_SECONDS", 0.0)
    with caplog.at_level(logging.WARNING):
        r = client.get("/api/next-quote-no", headers=_auth(token))
    assert r.status_code == 200
    assert "SLOW REQUEST" in caplog.text, caplog.text[-500:]
    assert "/api/next-quote-no" in caplog.text
    assert "GET" in caplog.text


def test_non_api_paths_are_not_logged(client, make_user, monkeypatch, caplog):
    """靜態檔案不列入——它們慢通常是磁碟/網路，不是資料庫鎖，混進來只會稀釋訊號。"""
    import main

    monkeypatch.setattr(main, "_SLOW_REQUEST_SECONDS", 0.0)
    with caplog.at_level(logging.WARNING):
        client.get("/pages/login.html")
    assert "SLOW REQUEST" not in caplog.text


def test_write_lock_contention_is_what_this_catches(client, make_user, caplog, monkeypatch):
    """端到端釘住這條 log 真正要抓的情境：另一條連線握著寫入鎖時，建立報價單的
    請求會被拖住（db.py 的 timeout=30 上限），而且會被記下來。

    只握 1.5 秒、門檻設 1 秒——證明機制成立即可，不必真的等 30 秒。
    """
    import db
    import main

    username, password = make_user(username="lock_user", role="admin")
    token = _login(client, username, password)

    ready = threading.Event()
    hold_seconds = 1.5

    def _hold_writer():
        conn = sqlite3.connect(db.DB_PATH, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO audit_log (at, action, target_type, target_id, "
                "target_label, detail) VALUES (?,?,?,?,?,?)",
                ("2026-09-10T00:00:00", "lock.test", "x", "x", "x", "{}"))
            ready.set()
            time.sleep(hold_seconds)
            conn.rollback()
        finally:
            conn.close()

    t = threading.Thread(target=_hold_writer, daemon=True)
    t.start()
    assert ready.wait(5), "測試用的持鎖執行緒沒有起來"

    monkeypatch.setattr(main, "_SLOW_REQUEST_SECONDS", 1.0)
    payload = {
        "status": "草稿",
        "data": {"customerName": "鎖測客", "projectName": "鎖測專",
                 "quoteDate": "2026-09-10",
                 "tot": {"total": 1000, "pretax": 952,
                         "directMarginPct": 0, "netMarginPct": 0}},
    }
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/quotations", json=payload, headers=_auth(token))
    elapsed = time.monotonic() - started
    t.join(timeout=10)

    # 請求本身仍然成功——鎖等待只是慢，不是失敗
    assert r.status_code == 201, r.text
    assert elapsed >= hold_seconds * 0.6, (
        f"請求只花了 {elapsed:.2f}s，沒有真的被鎖拖住，這題的前提不成立")
    assert "SLOW REQUEST" in caplog.text, caplog.text[-500:]
    assert "/api/quotations" in caplog.text
