# -*- coding: utf-8 -*-
"""心跳監控「看守看守者」契約題（2026-11-11）。

背景：正式機心跳壞了兩個多月沒人知道——heartbeat_job 打 http、伺服器早已只講 https，
每 5 分鐘 /fail，healthchecks.io 卡在「已經紅燈」不再寄信，真正的斷電也沒有新告警。

這支測試釘四件事：
① 判斷邏輯（helpers/heartbeat_status.assess）：各狀態 × 新鮮度 ⇒ level／alert；永不丟例外；不洩漏 ping_url。
② 每日檢查（system_checks._check_heartbeat_health）：該寄才寄、同一天一次、失敗不寫旗標、恢復清旗標、開發機不寄。
③ 信件本體（notify_heartbeat_stale）：真的組得出來、不含 ping 網址。
④ **防背離守門**：heartbeat_job 寫死的埠，必須等於 autostart.bat／start.bat 的 `--port`；
   且 job 兩種協定都試（伺服器用哪種是 autostart.bat 依憑證檔決定的，不是 job 決定的）。
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import helpers.email_notify as en
from helpers import heartbeat_status as hs

# conftest 的 _netguard 擋 urlopen；連本機 127.0.0.1 臨時空埠（連線被拒）的題標 allow_outbound，不碰對外網路
loopback_net = pytest.mark.allow_outbound

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 11, 12, 0, 0)
SECRET_URL = "https://hc-ping.com/super-secret-uuid-1234"


def _st(status="ok", since_ago=timedelta(hours=1), seen_ago=timedelta(hours=1), **kw):
    d = {"status": status, "since": (NOW - since_ago).isoformat(timespec="seconds"),
         "seen_at": (NOW - seen_ago).isoformat(timespec="seconds"), "scheme": "https",
         "local_ok_at": "", "ext_ok_at": (NOW - timedelta(hours=1)).isoformat(timespec="seconds")}
    d.update(kw)
    return d


@pytest.fixture
def hb_files(monkeypatch, tmp_path):
    """把 LOGS_DIR／HEARTBEAT_CONFIG 指到暫存；回 (寫狀態檔, 寫設定檔)。"""
    from core import paths
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "heartbeat_config.json"))

    def write_state(d):
        (logs / "heartbeat_state.json").write_text(json.dumps(d), encoding="utf-8")

    def write_cfg(url=SECRET_URL):
        (tmp_path / "heartbeat_config.json").write_text(json.dumps({"ping_url": url}), encoding="utf-8")
    return write_state, write_cfg


# ── ① 判斷邏輯 ─────────────────────────────────────────────────────────────

def test_no_config_no_state_is_na_and_silent(hb_files):
    r = hs.assess(NOW)
    assert (r["level"], r["alert"]) == (hs.LEVEL_NA, False)


def test_config_but_no_state_warns_and_alerts(hb_files):
    hb_files[1]()
    r = hs.assess(NOW)
    assert (r["level"], r["alert"]) == (hs.LEVEL_WARN, True)


def test_ok_fresh_is_ok(hb_files):
    r = hs.assess(NOW, _st("ok", seen_ago=timedelta(hours=20)))
    assert (r["level"], r["alert"], r["problems"]) == (hs.LEVEL_OK, False, [])


def test_ok_but_state_file_stale_means_scheduler_stopped(hb_files):
    r = hs.assess(NOW, _st("ok", seen_ago=timedelta(hours=hs.OK_STALE_HOURS + 1)))
    assert (r["level"], r["alert"]) == (hs.LEVEL_ERROR, True)
    assert "排程" in r["summary"]


@pytest.mark.parametrize("status", ["local_down", "ext_fail"])
def test_bad_status_grace_then_alert(hb_files, status):
    young = hs.assess(NOW, _st(status, since_ago=timedelta(minutes=hs.BAD_GRACE_MINUTES - 5), seen_ago=timedelta(minutes=10)))
    assert (young["level"], young["alert"]) == (hs.LEVEL_WARN, False), "一次網路抖動不該寄信"
    old = hs.assess(NOW, _st(status, since_ago=timedelta(minutes=hs.BAD_GRACE_MINUTES + 5), seen_ago=timedelta(minutes=10)))
    assert (old["level"], old["alert"]) == (hs.LEVEL_ERROR, True)


def test_local_down_while_app_alive_names_the_protocol_suspect(hb_files):
    r = hs.assess(NOW, _st("local_down", since_ago=timedelta(hours=5), seen_ago=timedelta(minutes=30)))
    assert "協定" in r["summary"], "app 活著卻 local_down＝監控誤判，信裡要指到協定／埠"


def test_ext_unset_alerts_only_after_a_day(hb_files):
    assert hs.assess(NOW, _st("ext_unset", since_ago=timedelta(hours=3)))["alert"] is False
    r = hs.assess(NOW, _st("ext_unset", since_ago=timedelta(hours=hs.EXT_UNSET_ALERT_HOURS + 1)))
    assert (r["level"], r["alert"]) == (hs.LEVEL_WARN, True)


def test_bad_status_with_stale_state_file_escalates(hb_files):
    r = hs.assess(NOW, _st("ext_fail", since_ago=timedelta(hours=1), seen_ago=timedelta(hours=5)))
    assert (r["level"], r["alert"]) == (hs.LEVEL_ERROR, True)


@pytest.mark.parametrize("bad", [{}, {"status": "ok"}, {"status": "ok", "seen_at": "garbage"}, {"status": "???", "seen_at": NOW.isoformat()}])
def test_malformed_state_alerts_not_crashes(hb_files, bad):
    r = hs.assess(NOW, bad)
    assert r["alert"] is True and r["level"] in (hs.LEVEL_WARN, hs.LEVEL_ERROR)


def test_corrupt_state_file_on_disk_never_raises(hb_files, tmp_path):
    (tmp_path / "logs" / "heartbeat_state.json").write_text("{not json", encoding="utf-8")
    hb_files[1]()
    r = hs.assess(NOW)
    assert r["alert"] is True


def test_assess_never_exposes_ping_url(hb_files):
    hb_files[1]()
    hb_files[0](_st("ok"))
    r = hs.assess(NOW)
    assert r["ping_url_set"] is True
    assert SECRET_URL not in json.dumps(r, ensure_ascii=False)
    assert "super-secret" not in json.dumps(r, ensure_ascii=False)


# ── ② 每日檢查 ─────────────────────────────────────────────────────────────

GUARD_KEY = "heartbeat_stale_last_notified"


@pytest.fixture
def daily(client, monkeypatch, hb_files):
    """回 (system_checks, 寄出記錄, 寫狀態檔)；背景執行緒改同步。"""
    import helpers.system_checks as sc
    from helpers.settings import _set_setting
    _set_setting(GUARD_KEY, "")
    sent = []
    monkeypatch.setattr(sc, "notify_heartbeat_stale", lambda summary, problems, state=None: sent.append((summary, problems, state)) or True)
    monkeypatch.setattr(sc, "_uptime_seconds", lambda: 10 ** 6)      # 預設「已跑很久」；啟動寬限另有專題
    monkeypatch.setattr(sc.threading, "Thread",
                        lambda target, args=(), kwargs=None, daemon=None: type("T", (), {"start": lambda s: target(*args)})())
    return sc, sent, hb_files[0]


def _stale_state():
    # 以「真實現在」為基準：每日檢查用 assess() 的預設 now
    n = datetime.now()
    return {"status": "local_down", "since": (n - timedelta(hours=6)).isoformat(timespec="seconds"),
            "seen_at": (n - timedelta(minutes=20)).isoformat(timespec="seconds"), "scheme": "",
            "local_ok_at": "", "ext_ok_at": ""}


def test_daily_sends_once_per_day_when_alerting(daily):
    from helpers.settings import _get_setting
    sc, sent, write_state = daily
    write_state(_stale_state())
    sc._check_heartbeat_health()
    sc._check_heartbeat_health()
    assert len(sent) == 1, "同一天只寄一次"
    assert _get_setting(GUARD_KEY)


def test_daily_failed_send_does_not_set_flag(daily, monkeypatch):
    from helpers.settings import _get_setting
    sc, sent, write_state = daily
    write_state(_stale_state())
    monkeypatch.setattr(sc, "notify_heartbeat_stale", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    sc._check_heartbeat_health()
    assert not _get_setting(GUARD_KEY), "寄失敗不能寫『今天寄過了』，否則永遠不會再試"


def test_daily_skips_judging_right_after_app_start(daily, monkeypatch):
    """K 審 S1：斷電／冷開機後 app 一起來時，狀態檔還是停電前的舊資料（心跳排程還沒重新跑）⇒ 不判斷、不寄、不寫旗標。
    過了寬限（3 個心跳週期）才照常判斷。"""
    from helpers.settings import _get_setting
    sc, sent, write_state = daily
    write_state(_stale_state())                       # local_down 已 6 小時
    monkeypatch.setattr(sc, "_uptime_seconds", lambda: 60)
    sc._check_heartbeat_health()
    assert sent == [] and not _get_setting(GUARD_KEY), "啟動後 1 分鐘不該判斷"
    monkeypatch.setattr(sc, "_uptime_seconds", lambda: sc._HEARTBEAT_STARTUP_GRACE_MINUTES * 60 + 60)
    sc._check_heartbeat_health()
    assert len(sent) == 1, "寬限過後同樣的狀態要寄"


def test_daily_startup_grace_also_covers_long_off_machine(daily, monkeypatch):
    """機器關了兩天再開機（ok 但 seen_at 50 小時前）：啟動寬限內不可誤報「排程停了」。"""
    sc, sent, write_state = daily
    n = datetime.now()
    write_state({"status": "ok", "since": (n - timedelta(hours=50)).isoformat(timespec="seconds"),
                 "seen_at": (n - timedelta(hours=50)).isoformat(timespec="seconds"), "scheme": "https",
                 "local_ok_at": "", "ext_ok_at": ""})
    monkeypatch.setattr(sc, "_uptime_seconds", lambda: 120)
    sc._check_heartbeat_health()
    assert sent == []


def test_daily_flag_not_written_when_notify_reports_not_sent(daily, monkeypatch):
    """K 審 L1：寄信函式回 False（沒收件人／暫時失敗）⇒ 不寫旗標，下次重試。"""
    from helpers.settings import _get_setting
    sc, sent, write_state = daily
    write_state(_stale_state())
    monkeypatch.setattr(sc, "notify_heartbeat_stale", lambda *a, **k: False)
    sc._check_heartbeat_health()
    assert not _get_setting(GUARD_KEY)


def test_daily_recovery_clears_flag(daily):
    from helpers.settings import _get_setting, _set_setting
    sc, sent, write_state = daily
    _set_setting(GUARD_KEY, "2026-11-10")
    n = datetime.now()
    write_state({"status": "ok", "since": n.isoformat(timespec="seconds"), "seen_at": n.isoformat(timespec="seconds"),
                 "scheme": "https", "local_ok_at": "", "ext_ok_at": n.isoformat(timespec="seconds")})
    sc._check_heartbeat_health()
    assert not sent and not _get_setting(GUARD_KEY)


def test_daily_dev_machine_without_heartbeat_is_silent(daily):
    sc, sent, _ = daily
    sc._check_heartbeat_health()
    assert sent == []


def test_daily_check_is_wired_into_run_all():
    import inspect
    import helpers.system_checks as sc
    assert "_check_heartbeat_health()" in inspect.getsource(sc.run_all)


# ── ③ 信件本體（本體要真的跑；不 patch 掉 notify_heartbeat_stale）──────────

def test_mail_body_builds_and_has_no_ping_url(monkeypatch):
    sent = []
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: ["x@example.invalid"])
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: sent.append((to, subject, html)) or _fake_handle(en.SEND_SENT))
    en.notify_heartbeat_stale("本機判定沒有回應", ["心跳檢查本機服務已 5 小時判定「沒有回應」"],
                              {"status": "local_down", "since": "2026-11-11T07:00:00", "scheme": "", "ext_ok_at": "", "seen_at": "2026-11-11T11:40:00"})
    assert sent, "信沒有組出來"
    to, subject, html = sent[0]
    assert "心跳" in subject and "healthchecks.io" in html
    assert "hc-ping.com" not in html


def _fake_handle(outcome):
    class H:
        def wait(self):
            return outcome
    return H()


@pytest.mark.parametrize("outcome, may_mark", [
    (en.SEND_SENT, True), (en.SEND_UNKNOWN, True), (en.SEND_PERMANENT_FAIL, True),
    (en.SEND_TRANSIENT_FAIL, False), (en.SEND_SKIPPED, False)])
def test_notify_returns_whether_the_flag_may_be_written(monkeypatch, outcome, may_mark):
    """K 審 L1：旗標要等寄送結果才寫（與 send_registered(wait=True) 同一套對照）。"""
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: ["x@example.invalid"])
    monkeypatch.setattr(en, "_async_send", lambda *a, **k: _fake_handle(outcome))
    assert en.notify_heartbeat_stale("x", ["y"], {}) is may_mark


def test_notify_without_recipients_returns_false(monkeypatch):
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: [])
    assert en.notify_heartbeat_stale("x", ["y"], {}) is False


def test_mail_type_is_registered_and_not_lockable_off():
    from helpers import mail_types, notify_matrix
    assert "heartbeat_stale" in notify_matrix.MAIL_OFF_LOCKED, "監控本身壞了的告警不可被關閉"


# ── ④ 防背離守門：job 的埠與協定 ──────────────────────────────────────────

def _bat_port(name):
    txt = (BACKEND / name).read_text(encoding="utf-8", errors="replace")
    ports = {int(p) for p in re.findall(r"--port\s+(\d+)", txt)}
    return name, ports


@pytest.mark.parametrize("bat", ["autostart.bat", "start.bat"])
def test_job_port_matches_launcher_batch_files(bat, monkeypatch, tmp_path):
    from core import paths
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path / "logs"))        # BK19：重新 import 會在 LOGS_DIR 開 log 檔，必須先導到 tmp
    sys.modules.pop("heartbeat_job", None)
    import heartbeat_job
    name, ports = _bat_port(bat)
    assert ports, f"{name} 找不到 --port；批次檔改版了？這個守門要跟著改"
    assert ports == {heartbeat_job._LOCAL_PORT}, (
        f"{name} 的 --port={ports}，heartbeat_job._LOCAL_PORT={heartbeat_job._LOCAL_PORT}。\n"
        "兩邊各改各的 ⇒ 監控會安靜地全面誤報（2026-09-07 事故同型）。")
    sys.modules.pop("heartbeat_job", None)


def test_job_probes_both_schemes_https_first(monkeypatch, tmp_path):
    from core import paths
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path / "logs"))        # BK19：同上
    sys.modules.pop("heartbeat_job", None)
    import heartbeat_job
    assert heartbeat_job._SCHEMES == ("https", "http")
    urls = heartbeat_job._local_urls()
    assert urls[0].startswith("https://127.0.0.1:") and urls[1].startswith("http://127.0.0.1:")
    sys.modules.pop("heartbeat_job", None)


def test_autostart_still_chooses_scheme_by_cert_files():
    """job 之所以要兩種都試，前提是 autostart.bat 依憑證檔決定協定；這個前提若消失，job 的註解／設計要重評。"""
    txt = (BACKEND / "autostart.bat").read_text(encoding="utf-8", errors="replace").lower()
    assert "cert.pem" in txt and "ssl" in txt


# ── 狀態快照（tools/prod_status_snapshot）──────────────────────────────────

def test_snapshot_heartbeat_block_whitelists_and_hides_ping_url(tmp_path):
    from tools import prod_status_snapshot as snap
    root = tmp_path / "inst"
    (root / "backend" / "logs").mkdir(parents=True)
    st = _st("ok")
    st["ping_url"] = SECRET_URL            # 就算有人誤把網址寫進狀態檔，也不可帶出去
    (root / "backend" / "logs" / "heartbeat_state.json").write_text(json.dumps(st), encoding="utf-8")
    (root / "backend" / "heartbeat_config.json").write_text(json.dumps({"ping_url": SECRET_URL}), encoding="utf-8")
    blk = snap.heartbeat(str(root))
    dumped = json.dumps(blk, ensure_ascii=False)
    assert blk["status"] == "ok" and blk["ping_url_set"] is True
    assert SECRET_URL not in dumped and "ping_url\"" not in dumped.replace("ping_url_set", "")


def test_snapshot_heartbeat_missing_state_is_recorded_as_error_not_crash(tmp_path, monkeypatch):
    from tools import prod_status_snapshot as snap
    monkeypatch.setattr(snap, "http_probe", lambda root, port, timeout: {"base_url": "", "ping": None, "api_version": None, "errors": {}})
    monkeypatch.setattr(snap, "pids_on_port", lambda port: [])
    root = tmp_path / "inst"
    (root / "backend" / "logs").mkdir(parents=True)
    with pytest.raises(Exception):
        snap.heartbeat(str(root))
    res = snap.collect(str(root))
    assert res["heartbeat"] is None and "heartbeat" in res["errors"]


# ── K 審 N1／N2：job 的狀態檔原子寫入、雙協定探測的順序與 log 噪音 ─────────────────────

def _job(monkeypatch, tmp_path):
    from core import paths
    logs = tmp_path / "joblogs"
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "hbj.json"))
    import importlib
    sys.modules.pop("heartbeat_job", None)
    mod = importlib.import_module("heartbeat_job")
    return mod


def test_job_state_write_is_atomic_no_tmp_left(monkeypatch, tmp_path):
    mod = _job(monkeypatch, tmp_path)
    mod._save_state("ok", NOW, {}, "https")
    st = Path(mod._STATE_PATH)
    assert json.loads(st.read_text(encoding="utf-8"))["status"] == "ok"
    assert not Path(mod._STATE_PATH + ".tmp").exists(), "暫存檔必須被 os.replace 取走"
    sys.modules.pop("heartbeat_job", None)


def test_job_tries_last_good_scheme_first_and_stops_at_first_success(monkeypatch, tmp_path):
    mod = _job(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(mod, "_http_get", lambda url: seen.append(url) or url.startswith("http://"))
    assert mod._probe_local("http") == "http"
    assert seen == [mod._local_urls()[1]], "http-only 的機器不該每次先撞一次 https"
    seen.clear()
    assert mod._probe_local(None) == "http" and seen[0].startswith("https://")      # 沒記錄時仍 https 先
    sys.modules.pop("heartbeat_job", None)


@loopback_net
def test_job_failed_loopback_attempt_is_not_a_warning(monkeypatch, tmp_path):
    """http-only 機器每次探測的失敗嘗試只該是 DEBUG：避免每天 ~288 行 WARNING（使用者要求低寫入）。"""
    import socket
    mod = _job(monkeypatch, tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    got = []
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *a, **k: got.append(msg))
    monkeypatch.setattr(mod.logger, "debug", lambda msg, *a, **k: got.append("DEBUG " + msg))
    monkeypatch.setattr(mod, "_TIMEOUT", 2)
    assert mod._http_get("http://127.0.0.1:%d/api/ping" % port) is False
    assert got and all(m.startswith("DEBUG") for m in got), got
    sys.modules.pop("heartbeat_job", None)


def test_job_state_replace_retries_then_gives_up_cleanly_when_destination_is_held_open(monkeypatch, tmp_path):
    """K 審 N1 補充：Windows 上目的檔被別人開著讀 ⇒ os.replace PermissionError。
    重試後成功＝寫入成功；一直失敗＝不拋例外、不留 .tmp、只記 WARNING（沒有 traceback）。"""
    mod = _job(monkeypatch, tmp_path)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    real = mod.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "held open")
        return real(src, dst)
    monkeypatch.setattr(mod.os, "replace", flaky)
    mod._save_state("ok", NOW, {}, "https")
    assert len(calls) == 3 and json.loads(Path(mod._STATE_PATH).read_text(encoding="utf-8"))["status"] == "ok"

    def always(src, dst):
        raise PermissionError(5, "held open")
    monkeypatch.setattr(mod.os, "replace", always)
    warns, excs = [], []
    monkeypatch.setattr(mod.logger, "warning", lambda m, *a, **k: warns.append(m))
    monkeypatch.setattr(mod.logger, "exception", lambda m, *a, **k: excs.append(m))
    mod._save_state("local_down", NOW, {}, "")
    assert warns and not excs, "只記 WARNING、不記 traceback"
    assert not Path(mod._STATE_PATH + ".tmp").exists(), "最後仍失敗要刪暫存檔"
    sys.modules.pop("heartbeat_job", None)
