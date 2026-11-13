# -*- coding: utf-8 -*-
"""「備份與監控」專頁（系統選單提案 v2 批次 4a，2026-11-13）：helpers/backup_monitor.py＋routers/backup_monitor.py。

驗的是「這頁不會說謊、不會洩漏、不會被亂按」：
- 只有最高管理者進得去（未登入 401、一般管理員 403）；
- 狀態四種備份／硬碟／心跳／告警／保留天數／門檻都在，且心跳網址、伺服器路徑永不出現在回應；
- 立即備份：沒確認 400、同時只能一個 409、30 分鐘內不能重複 429、結果寫回；
- 心跳網址：只收 https／http、擋內網與空白與過長、空字串＝停用、其他設定鍵保留、稽核只記主機名；
- 測試心跳：沒確認 400、沒設網址有白話訊息、1 分鐘內不能重複 429、錯誤訊息不含網址；
- 告警門檻在設定中心 `monitoring` 群組，system_checks 真的用它們（不是寫死的 36 小時／50 GB）。
"""
import json
import threading
import time
from datetime import datetime, timedelta

import pytest

_MAKE_USER_DEFAULT_ROLE = "superadmin"

SECRET = "https://hc-ping.example.com/SECRET-UUID-1234"


@pytest.fixture(autouse=True)
def _logs_dir_in_tmp(monkeypatch, tmp_path):
    """立即備份會在 LOGS_DIR 建 backup_run.lock；沒用到 hb_cfg 的題目不能寫進真的 backend/logs（BK19：測試不准寫 repo）。
    autouse 先於明確要求的夾具建立，hb_cfg 之後再換成自己的 logs 時以它為準。"""
    from core import paths
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path / "logs_auto"))


@pytest.fixture()
def hb_cfg(monkeypatch, tmp_path):
    """心跳設定檔／狀態檔換成暫存路徑，不碰真的。"""
    from core import paths
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "heartbeat_config.json"))
    return tmp_path / "heartbeat_config.json"


@pytest.fixture()
def alert_dir(monkeypatch, tmp_path):
    from core import paths
    d = tmp_path / "alertdir"
    d.mkdir()
    monkeypatch.setattr(paths, "BACKUP_ALERT_DIR", str(d))
    return d


@pytest.fixture()
def fresh_limits(monkeypatch):
    """每題都從「沒有測試過／沒有備份過」開始。"""
    from helpers import backup_monitor as bm
    monkeypatch.setitem(bm._hb_last, "at", 0.0)
    monkeypatch.setitem(bm._running, "on", False)
    bm._set_setting(bm._LAST_KEY, "")                  # 同一支測試檔共用資料庫：上一題的時間戳（可能在「未來」，題目會傳假的 now）不能擋這一題
    yield bm
    bm._set_setting(bm._LAST_KEY, "")


@pytest.fixture(autouse=True)
def _fake_dns_and_mail(monkeypatch):
    """網域解析一律回公開位址、寄信一律記下來不寄（這支測試不碰外部網路與 SMTP）。"""
    from core import safe_ping
    import helpers.email_notify as en
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["93.184.216.34"])
    mails = []
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: (mails.append((key, kw)), True)[1])
    return mails


@pytest.fixture()
def mails(_fake_dns_and_mail):
    return _fake_dns_and_mail


def _login(client, make_user, name="bm_sa", role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_row(action, label="", at=None):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO audit_log (at, action, target_label) VALUES (?,?,?)",
                     (at or datetime.now().isoformat(timespec="seconds"), action, label))
        conn.commit()
    finally:
        conn.close()


def _wait_idle(bm, secs=10):
    end = time.time() + secs
    while bm._running["on"] and time.time() < end:
        time.sleep(0.02)
    assert not bm._running["on"], "背景備份沒有結束"


# ── 權限 ──────────────────────────────────────────────────────────────────────

ENDPOINTS = [("get", "/api/system/backup-monitor", None),
             ("post", "/api/system/backup-monitor/backup-now", {"confirm": True}),
             ("put", "/api/system/backup-monitor/heartbeat-url", {"pingUrl": SECRET}),
             ("post", "/api/system/backup-monitor/heartbeat-test", {"confirm": True}),
             ("post", "/api/system/backup-monitor/heartbeat-disable", {"confirm": True, "reason": "不用了"}),
             ("post", "/api/system/backup-monitor/heartbeat-disable/1/approve", {"confirm": True}),
             ("post", "/api/system/backup-monitor/heartbeat-disable/1/cancel", {}),
             ("post", "/api/system/backup-monitor/heartbeat-disable/1/reject", {"confirm": True, "reason": "不認得"})]


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_anonymous_is_401(client, method, url, body):
    r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_non_superadmin_is_403(client, make_user, method, url, body):
    h = _login(client, make_user, "bm_adm", role="admin")
    r = getattr(client, method)(url, headers=h, **({"json": body} if body is not None else {}))
    assert r.status_code == 403


# ── 狀態 ──────────────────────────────────────────────────────────────────────

def test_status_has_every_block_and_never_leaks_url_or_paths(client, make_user, hb_cfg, alert_dir):
    hb_cfg.write_text(json.dumps({"ping_url": SECRET, "other": 1}), encoding="utf-8")
    (alert_dir / "BACKUP_ALERT.txt").write_text("BACKUP ALERT\n" + r"原因: 讀不到 C:\Users\x\Google Drive\系統存檔", encoding="utf-8")
    h = _login(client, make_user)
    r = client.get("/api/system/backup-monitor", headers=h)
    assert r.status_code == 200
    d = r.json()
    for k in ("thresholds", "backups", "cloud", "disks", "heartbeat", "alerts", "retention", "manual"):
        assert k in d, k
    assert [b["key"] for b in d["backups"]] == ["local", "daily", "weekly", "monthly"]
    assert d["heartbeat"]["pingUrlSet"] is True and d["heartbeat"]["pingHost"] == "hc-ping.example.com"
    body = r.text
    assert "SECRET-UUID" not in body and SECRET not in body
    assert "C:\\\\Users" not in body and "Google Drive" not in body
    assert d["alerts"]["current"] and "路徑已隱藏" in d["alerts"]["current"]["reason"]
    assert d["retention"]["log_keep_days"] >= 7
    assert d["thresholds"] == {"backup_stale_hours": 36, "disk_free_min_gb": 50, "disk_free_min_pct": 10}


def test_status_survives_a_broken_block(client, make_user, monkeypatch):
    from helpers import backup_monitor as bm

    def boom(*a, **k):
        raise RuntimeError("secret C:\\path")
    monkeypatch.setattr(bm, "_heartbeat_block", boom)
    h = _login(client, make_user)
    d = client.get("/api/system/backup-monitor", headers=h).json()
    assert d["heartbeat"] == {"error": "這一塊暫時讀不到（詳見系統日誌）。"}
    assert isinstance(d["backups"], list)


def test_backup_rows_reflect_audit_results_and_staleness(client, make_user, monkeypatch):
    from helpers import backup_monitor as bm
    monkeypatch.setattr(bm, "_cloud_expected", lambda: True)
    now = datetime.now()
    _audit_row("backup.sqlite_snapshot", at=(now - timedelta(hours=2)).isoformat(timespec="seconds"))
    _audit_row("backup.daily_partial", at=(now - timedelta(hours=3)).isoformat(timespec="seconds"))
    _audit_row("backup.weekly_ok", at=(now - timedelta(days=40)).isoformat(timespec="seconds"))
    rows = {b["key"]: b for b in bm.status(now)["backups"]}
    assert rows["local"]["level"] == "ok" and rows["local"]["result"] == "ok"
    assert rows["daily"]["level"] == "warn" and rows["daily"]["result"] == "partial"
    assert rows["weekly"]["result"] == "ok"           # 週備份不做「超過 N 小時」判斷
    assert rows["monthly"]["result"] == "never" and rows["monthly"]["level"] == "na"
    # 超過門檻 ⇒ 本機備份轉紅
    later = now + timedelta(hours=40)
    assert {b["key"]: b for b in bm.status(later)["backups"]}["local"]["level"] == "error"


def test_failed_snapshot_is_error_and_cloud_off_is_not_applicable(client, make_user, monkeypatch):
    from helpers import backup_monitor as bm
    monkeypatch.setattr(bm, "_cloud_expected", lambda: False)
    _audit_row("backup.snapshot_rejected")
    d = bm.status()
    rows = {b["key"]: b for b in d["backups"]}
    assert rows["local"]["level"] == "error" and rows["local"]["result"] == "failed"
    assert rows["daily"]["result"] == "skipped" and rows["monthly"]["result"] == "skipped"
    assert d["cloud"]["enabled"] is False and "雲端" in d["cloud"]["note"]


def test_recent_alerts_are_listed_newest_first_and_30_days_only(client, make_user):
    from helpers import backup_monitor as bm
    now = datetime.now()
    _audit_row("backup.alert", "雲端沒掛上", at=(now - timedelta(days=2)).isoformat(timespec="seconds"))
    _audit_row("backup.alert_cleared", "雲端沒掛上", at=(now - timedelta(days=1)).isoformat(timespec="seconds"))
    _audit_row("backup.alert", "太舊", at=(now - timedelta(days=45)).isoformat(timespec="seconds"))
    rec = bm.status(now)["alerts"]["recent"]
    assert [a["kind"] for a in rec] == ["cleared", "alert"]
    assert all(a["text"] != "太舊" for a in rec)


def test_disk_levels_follow_thresholds(monkeypatch):
    import shutil
    from collections import namedtuple
    from helpers import backup_monitor as bm, system_checks as sc
    U = namedtuple("U", "total used free")
    gb = 1024 ** 3
    monkeypatch.setattr(sc, "_disk_targets", lambda: [("系統磁碟", "x")])
    th = {"backup_stale_hours": 36, "disk_free_min_gb": 50, "disk_free_min_pct": 10}
    for total, free, want in ((1000, 500, "ok"), (1000, 80, "warn"), (1000, 40, "error"), (100, 30, "ok")):
        monkeypatch.setattr(shutil, "disk_usage", lambda p, t=total, f=free: U(t * gb, (t - f) * gb, f * gb))
        assert bm._disks_block(th)[0]["level"] == want, (total, free)


# ── scrub_paths ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [r"讀不到 C:\Users\a\b.txt 這個檔", r"G:\我的雲端硬碟\系統存檔", r"\\nas\share\bk", "在 /var/lib/motrix/backups/x 失敗"])
def test_scrub_paths_hides_paths(raw):
    from helpers.backup_monitor import scrub_paths
    out = scrub_paths(raw)
    assert "路徑已隱藏" in out
    for bad in ("Users", "我的雲端硬碟", "nas", "motrix"):
        assert bad not in out


def test_scrub_paths_keeps_ordinary_text():
    from helpers.backup_monitor import scrub_paths
    assert scrub_paths("已經超過 36 小時沒有備份（含 1/2 比例）") == "已經超過 36 小時沒有備份（含 1/2 比例）"
    assert scrub_paths(None) == ""


# ── 立即備份 ──────────────────────────────────────────────────────────────────

def test_backup_now_requires_confirm(client, make_user, fresh_limits):
    h = _login(client, make_user)
    for body in (None, {}, {"confirm": False}, {"confirm": "yes"}):
        r = client.post("/api/system/backup-monitor/backup-now", headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 400, body


def test_backup_now_runs_both_jobs_once_records_result_and_rate_limits(client, make_user, fresh_limits, monkeypatch):
    bm = fresh_limits
    import archive
    calls = []
    monkeypatch.setattr(archive, "_daily_backup", lambda *a, **k: calls.append("daily"))
    monkeypatch.setattr(archive, "_weekly_backup", lambda *a, **k: calls.append("weekly"))
    h = _login(client, make_user)
    r = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is True
    _wait_idle(bm)
    assert calls == ["daily", "weekly"]
    d = client.get("/api/system/backup-monitor", headers=h).json()["manual"]
    assert d["running"] is False and d["lastResult"]["ok"] is True and d["waitSeconds"] > 0
    r2 = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
    assert r2.status_code == 429 and "分鐘" in r2.json()["detail"]
    assert calls == ["daily", "weekly"]                 # 被擋的那次沒有真的跑
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='system.backup_now'").fetchone()[0] == 1
    finally:
        conn.close()


def test_backup_now_allowed_again_after_interval(fresh_limits, monkeypatch):
    bm = fresh_limits
    import archive
    monkeypatch.setattr(archive, "_daily_backup", lambda *a, **k: None)
    monkeypatch.setattr(archive, "_weekly_backup", lambda *a, **k: None)
    t0 = datetime.now()
    bm.run_backup_now(t0)
    _wait_idle(bm)
    with pytest.raises(bm.BackupRateLimited) as ei:
        bm.run_backup_now(t0 + timedelta(minutes=29))
    assert 0 < ei.value.wait_seconds <= 120
    bm.run_backup_now(t0 + timedelta(minutes=31))
    _wait_idle(bm)


def test_backup_now_only_one_at_a_time(client, make_user, fresh_limits, monkeypatch):
    bm = fresh_limits
    import archive
    gate = threading.Event()
    monkeypatch.setattr(archive, "_daily_backup", lambda *a, **k: gate.wait(10))
    monkeypatch.setattr(archive, "_weekly_backup", lambda *a, **k: None)
    h = _login(client, make_user)
    assert client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True}).status_code == 200
    try:
        assert client.get("/api/system/backup-monitor", headers=h).json()["manual"]["running"] is True
        r = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
        assert r.status_code == 409
    finally:
        gate.set()
        _wait_idle(bm)


def test_backup_now_failure_is_recorded_without_exception_details(fresh_limits, monkeypatch):
    bm = fresh_limits
    import archive

    def boom(*a, **k):
        raise OSError(r"C:\secret\place")
    monkeypatch.setattr(archive, "_daily_backup", boom)
    bm.run_backup_now()
    _wait_idle(bm)
    last = bm.status()["manual"]["lastResult"]
    assert last["ok"] is False and "secret" not in last["message"] and "C:\\" not in last["message"]


# ── 心跳網址 ──────────────────────────────────────────────────────────────────

def test_set_ping_url_writes_config_keeps_other_keys_and_never_returns_url(client, make_user, hb_cfg):
    hb_cfg.write_text(json.dumps({"ping_url": "", "keep_me": 7}), encoding="utf-8")
    h = _login(client, make_user)
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": "  " + SECRET + " "})
    assert r.status_code == 200
    assert r.json()["pingUrlSet"] is True and r.json()["pingHost"] == "hc-ping.example.com"
    assert "SECRET-UUID" not in r.text
    cfg = json.loads(hb_cfg.read_text(encoding="utf-8"))
    assert cfg == {"ping_url": SECRET, "keep_me": 7}
    assert not (hb_cfg.parent / "heartbeat_config.json.tmp").exists()
    # 稽核只有主機名
    import db
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT target_label, detail FROM audit_log WHERE action='system.heartbeat_url_set'").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1 and "SECRET-UUID" not in (rows[0][0] + rows[0][1]) and "hc-ping.example.com" in rows[0][0]


def test_set_ping_url_empty_is_refused_here_disable_has_its_own_endpoint(client, make_user, hb_cfg):
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    h = _login(client, make_user)
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": ""})
    assert r.status_code == 422 and "停用" in r.json()["detail"]
    assert json.loads(hb_cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET


def test_set_ping_url_creates_config_when_missing(client, make_user, hb_cfg):
    assert not hb_cfg.exists()
    h = _login(client, make_user)
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200
    assert json.loads(hb_cfg.read_text(encoding="utf-8")) == {"ping_url": SECRET}


@pytest.mark.parametrize("bad", ["hc-ping.com/abc", "ftp://hc-ping.com/abc", "javascript:alert(1)", "https://", "https://a b.com/x",
                                 "https://hc-ping.com/ab\ncd", "http://localhost:8000/x", "https://127.0.0.1/x", "https://192.168.1.5/x",
                                 "https://10.0.0.2/x", "https://169.254.169.254/latest", "https://[::1]/x", "https://nas.local/x",
                                 "https://hc-ping.com/" + "a" * 400])
def test_set_ping_url_rejects_bad_urls_in_plain_chinese(client, make_user, hb_cfg, bad):
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    h = _login(client, make_user)
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": bad})
    assert r.status_code == 422, bad
    msg = r.json()["detail"]
    assert isinstance(msg, str) and any("\u4e00" <= c <= "\u9fff" for c in msg)
    assert json.loads(hb_cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET        # 沒被動到


def test_set_ping_url_rejects_non_string(client, make_user, hb_cfg):
    h = _login(client, make_user)
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": 123}).status_code == 400


# ── 測試心跳 ──────────────────────────────────────────────────────────────────

def test_heartbeat_test_requires_confirm(client, make_user, hb_cfg, fresh_limits):
    h = _login(client, make_user)
    assert client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={}).status_code == 400


def test_heartbeat_test_without_url_says_so_and_does_not_call_out(client, make_user, hb_cfg, fresh_limits, monkeypatch):
    bm = fresh_limits
    monkeypatch.setattr(bm, "_ping", lambda u: pytest.fail("沒設網址不該對外"))
    h = _login(client, make_user)
    r = client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is False and "還沒有設定" in r.json()["message"]


def test_heartbeat_test_ok_then_rate_limited(client, make_user, hb_cfg, fresh_limits, monkeypatch):
    bm = fresh_limits
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    seen = []
    monkeypatch.setattr(bm, "_ping", lambda u: (seen.append(u), (True, "監控服務有收到這次打卡。"))[1])
    h = _login(client, make_user)
    r = client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "message": "監控服務有收到這次打卡。"}
    assert seen == [SECRET]
    r2 = client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={"confirm": True})
    assert r2.status_code == 429 and "秒" in r2.json()["detail"]
    assert len(seen) == 1


@pytest.mark.parametrize("code,needle", [(404, "找不到"), (403, "拒絕"), (429, "頻繁"), (500, "暫時出問題"), (302, "不是成功")])
def test_ping_maps_http_status_to_plain_messages(monkeypatch, code, needle):
    from core import safe_ping
    from helpers import backup_monitor as bm
    monkeypatch.setattr(safe_ping, "get", lambda url, **k: code)
    ok, msg = bm._ping(SECRET)
    assert ok is False and needle in msg and "SECRET-UUID" not in msg and str(code) not in msg


def test_ping_redirect_is_a_failure_with_explanation(monkeypatch):
    from core import safe_ping
    from helpers import backup_monitor as bm

    def fake(url, **k):
        raise safe_ping.RedirectBlocked(302)
    monkeypatch.setattr(safe_ping, "get", fake)
    ok, msg = bm._ping(SECRET)
    assert ok is False and "轉" in msg and "SECRET" not in msg and "302" not in msg


@pytest.mark.parametrize("kind,needle", [("dns", "找不到這個網站"), ("tls", "憑證"), ("timeout", "沒有回應"), ("connect", "連不到"), ("response", "連不到")])
def test_ping_failure_kinds_have_plain_messages_and_hide_exception(monkeypatch, kind, needle):
    from core import safe_ping
    from helpers import backup_monitor as bm

    def fake(url, **k):
        raise safe_ping.PingFailed(kind)
    monkeypatch.setattr(safe_ping, "get", fake)
    ok, msg = bm._ping(SECRET)
    assert ok is False and needle in msg and "SECRET" not in msg


def test_ping_unexpected_error_hides_exception(monkeypatch):
    from core import safe_ping
    from helpers import backup_monitor as bm

    def fake(url, **k):
        raise OSError("getaddrinfo failed for hc-ping.example.com SECRET-UUID")
    monkeypatch.setattr(safe_ping, "get", fake)
    ok, msg = bm._ping(SECRET)
    assert ok is False and "連不到" in msg and "SECRET" not in msg and "getaddrinfo" not in msg


def test_ping_success_uses_the_ten_second_timeout(monkeypatch):
    from core import safe_ping
    from helpers import backup_monitor as bm
    seen = {}
    monkeypatch.setattr(safe_ping, "get", lambda url, timeout=None, **k: (seen.update(t=timeout), 200)[1])
    assert bm._ping(SECRET)[0] is True and seen["t"] == 10


# ── 門檻 ──────────────────────────────────────────────────────────────────────

def test_thresholds_live_in_settings_center_and_are_used_by_checks():
    from helpers import settings_groups, settings_registry as sr, system_checks as sc   # noqa: F401
    assert sc.alert_thresholds() == {"backup_stale_hours": 36, "disk_free_min_gb": 50, "disk_free_min_pct": 10}
    for k, want in (("backup_stale_hours", 36), ("disk_free_min_gb", 50), ("disk_free_min_pct", 10)):
        assert sr.get("monitoring", k) == want


def _stale_alert_count(monkeypatch, hours_ago, stale_hours, now=None):
    """塞兩條 `hours_ago` 小時前的備份紀錄，門檻設 `stale_hours`，回「寄了幾封備份停擺信」。"""
    import helpers.system_checks as sc
    calls = []
    monkeypatch.setattr(sc, "notify_backup_stale", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sc, "alert_thresholds", lambda: {"backup_stale_hours": stale_hours, "disk_free_min_gb": 50, "disk_free_min_pct": 10})
    monkeypatch.setattr(sc.threading, "Thread", lambda target=None, args=(), kwargs=None, daemon=None, **kw:
                        type("T", (), {"start": lambda self, t=target: t()})())
    at = (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    _audit_row("backup.sqlite_snapshot", at=at)
    _audit_row("backup.daily_ok", at=at)
    sc._check_backup_freshness()
    return len(calls)


def test_stale_check_uses_configured_hours(client, monkeypatch):
    assert _stale_alert_count(monkeypatch, 20, 12) == 1        # 門檻調成 12 小時：20 小時前的備份算停擺


def test_stale_check_not_alerting_when_threshold_is_looser(client, monkeypatch):
    assert _stale_alert_count(monkeypatch, 20, 36) == 0        # 預設 36 小時：同一筆紀錄不算停擺


def test_disk_check_uses_configured_thresholds(client, monkeypatch):
    import shutil
    from collections import namedtuple
    import helpers.system_checks as sc
    U = namedtuple("U", "total used free")
    gb = 1024 ** 3
    calls = []
    monkeypatch.setattr(sc, "notify_disk_space_low", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sc.threading, "Thread", lambda target=None, args=(), kwargs=None, daemon=None, **kw:
                        type("T", (), {"start": lambda self, t=target, a=args, k=kwargs: t(*a, **(k or {}))})())
    monkeypatch.setattr(sc, "_disk_targets", lambda: [("系統磁碟", "x")])
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(1000 * gb, 920 * gb, 80 * gb))      # 剩 80 GB、8%
    monkeypatch.setattr(sc, "alert_thresholds", lambda: {"backup_stale_hours": 36, "disk_free_min_gb": 50, "disk_free_min_pct": 10})
    sc._check_disk_space()
    assert calls == []                                          # 剩 80 GB ≥ 預設 50 GB：不叫
    monkeypatch.setattr(sc, "alert_thresholds", lambda: {"backup_stale_hours": 36, "disk_free_min_gb": 100, "disk_free_min_pct": 10})
    sc._check_disk_space()
    assert len(calls) == 1                                      # 門檻調成 100 GB（且 8% < 10%）：同一顆碟就叫了


def test_thresholds_fall_back_when_registry_breaks(monkeypatch):
    from helpers import settings_registry as sr, system_checks as sc

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(sr, "get", boom)
    assert sc.alert_thresholds() == {"backup_stale_hours": 36, "disk_free_min_gb": 50, "disk_free_min_pct": 10}


# ── 寄信文字與頁面註冊 ────────────────────────────────────────────────────────

def test_backup_error_mail_text_shows_no_server_path():
    from helpers import mail_types
    src = open(mail_types.__file__, encoding="utf-8").read()
    i = src.index('register("backup_error"')
    block = src[i:src.index('register("geo_quota_warning"')]
    assert "db_backups" not in block and "backend/" not in block
    assert "備份與監控" in block


def test_page_is_registered_everywhere():
    from pathlib import Path
    from core import source_tree
    backend = Path(__file__).resolve().parents[1]
    page = source_tree.page_file("backup-monitor.html")
    assert page.exists()
    assert "backup-monitor.html" in (backend / "core" / "l1_pages.json").read_text(encoding="utf-8")
    assert "backup-monitor.html" in (backend / "core" / "menu_l1.json").read_text(encoding="utf-8")
    assert "backup-monitor.html" in (backend / "core" / "system_hub_l1.json").read_text(encoding="utf-8")
    html = page.read_text(encoding="utf-8")
    # 畫面規則：只有一個主要按鈕在頁首；不出現 HTTP 狀態碼字樣與伺服器路徑欄位
    head = html[html.index('class="pg__a"'):html.index('data-testid="bm-err"')]
    assert head.count("btn-primary") == 1
    assert "window.confirm" not in html and "alert(" not in html
