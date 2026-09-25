# -*- coding: utf-8 -*-
"""STATES-DATA-OPS 嚴重度「高」、原本缺守門的 5 項（C 的範圍）。

S-CD02 部分損毀的主庫：快照與啟動做 quick_check
S-CC07 時鐘往前跳：清理永遠保留最新 N 份
S-CC06 月備份失敗：同日重試、跨月補告警
S-CN03 告警的告警：管道各自獨立、寄成功才算寄過、寄不出去另留痕
S-CU10 升級預檢：放行損毀主庫

每一項都有正對照（沒壞時照常）與反向控制（壞了一定擋）。
"""
import os
import sqlite3
from datetime import date, timedelta

import pytest


def _full_db(path):
    """新版 init_db 建出的完整庫，外加一張會被弄壞的填充表（不在快照筆數對照的三張表裡）。"""
    import db
    db.init_db(str(path))
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE zz_filler (x TEXT)")
    c.executemany("INSERT INTO zz_filler VALUES (?)", [("y" * 900,)] * 400)
    c.commit()
    c.close()
    return str(path)


def _corrupt_tail(path):
    """弄壞檔尾幾頁（填充表所在）：庫仍讀得開、表名與三張對照表筆數照讀得出來。"""
    sz = os.path.getsize(path)
    with open(path, "r+b") as f:
        f.seek(sz - 4096 * 3)
        f.write(b"\xff" * 3000)


# ── S-CD02 ───────────────────────────────────────────────────────────────

def test_state_cd02_quick_check_ok_on_healthy_db(tmp_path):
    import db
    assert db.quick_check(_full_db(tmp_path / "ok.db")) == "ok"


def test_state_cd02_partially_corrupt_db_still_opens_but_fails_quick_check(tmp_path):
    import db
    p = _full_db(tmp_path / "bad.db")
    _corrupt_tail(p)
    db.init_db(p)                                   # 前提：損毀的庫照樣能「啟動」（這正是危險所在）
    assert db.quick_check(p) != "ok"


def test_state_cd02_snapshot_health_rejects_corrupt_snapshot(tmp_path):
    import archive
    good = _full_db(tmp_path / "good.db")
    assert archive._snapshot_health(good)[0] is True       # 正對照
    _corrupt_tail(good)
    ok, reasons, _c = archive._snapshot_health(good)
    assert ok is False and any("quick_check" in r for r in reasons), reasons


def test_state_cd02_corrupt_main_db_is_not_snapshotted_as_healthy_and_old_snapshots_survive(tmp_path, monkeypatch):
    import archive
    src = _full_db(tmp_path / "main.db")
    _corrupt_tail(src)
    backups = tmp_path / "db_backups"
    old = backups / (date.today() - timedelta(days=40)).isoformat()
    old.mkdir(parents=True)
    (old / "motrix_erp.db").write_bytes(b"old good snapshot")
    (old / ".done").write_text("x")
    monkeypatch.setattr(archive, "DB_PATH", src)
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(backups))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append((level, r)))
    monkeypatch.setattr(archive, "_system_audit", lambda *a, **k: None)
    assert archive._snapshot_sqlite(also_to_cloud=False) is None
    assert not (backups / date.today().isoformat() / ".done").exists(), "損毀的快照被標成完成"
    assert old.exists(), "拿到壞快照時不可以清掉好的舊快照"
    assert alerts and alerts[0][0] == "ERROR"


def test_state_cd02_startup_runs_the_integrity_check():
    """啟動接線：main.py 在模組層級、`init_db(DEMO_DB_PATH)` 之後**呼叫** _startup_integrity_check（import main 有副作用 ⇒ 用 AST）。
    X 稽核 A-2：原本用子字串找 `_startup_integrity_check()`，會比對到 `def _startup_integrity_check():` 自己 ⇒ 刪掉呼叫照綠。"""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8"))

    def _call_name(node):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            return node.value.func.id, node.value.args
        return None, None

    i_demo = i_check = None
    for i, node in enumerate(tree.body):              # 只看模組層級（函式裡的呼叫不算接線）
        name, args = _call_name(node)
        if name == "init_db" and args and isinstance(args[0], ast.Name) and args[0].id == "DEMO_DB_PATH":
            i_demo = i
        elif name == "_startup_integrity_check" and not args:
            i_check = i
    assert i_demo is not None, "找不到模組層級的 init_db(DEMO_DB_PATH)"
    assert i_check is not None, "模組層級沒有呼叫 _startup_integrity_check()"
    assert i_check > i_demo, "_startup_integrity_check() 必須在 init_db(DEMO_DB_PATH) 之後"


# ── S-CC07 ───────────────────────────────────────────────────────────────

def _days(root, today, n):
    for i in range(n):
        (root / (today - timedelta(days=i)).isoformat()).mkdir(parents=True)


def _fake_today(monkeypatch, archive, when):
    class _D(date):
        @classmethod
        def today(cls):
            return when
    monkeypatch.setattr(archive, "date", _D)


def test_state_cc07_normal_clock_prunes_by_date_without_alert(tmp_path, monkeypatch):
    import archive
    real = date.today()
    _days(tmp_path, real, 40)
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    archive._prune_local_db_backups(keep_days=30)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert len(left) == 31 and left[0] == (real - timedelta(days=30)).isoformat()   # 正對照：日期規則照舊
    assert alerts == []


def test_state_cc07_clock_jump_keeps_newest_and_alerts(tmp_path, monkeypatch):
    """反向控制（X 稽核 A-1 的多日模擬）：30 份真實快照、時鐘往前跳 40 天、之後照常每天快照＋清理 40 天。
    原本：跳的當天剩 6 份真實快照、第 7 天剩 0，告警只有第 1 天。應有：這一層暫停清理，而且**每一天**都 ERROR。
    第 3 天起「重新推算」已不成立（前一天那份未來日期的快照不算過期）⇒ 只能靠 `.prune_hold` 標記撐住。"""
    import archive
    real = date.today()
    _days(tmp_path, real, 30)
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    real_names = {p.name for p in tmp_path.iterdir()}
    for day in range(40):
        alerts = []
        monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append((level, r)))
        today = real + timedelta(days=40 + day)
        _fake_today(monkeypatch, archive, today)
        if day:                                               # 第一天在快照之前清理
            (tmp_path / today.isoformat()).mkdir()
        archive._prune_local_db_backups(keep_days=30)
        left = {p.name for p in tmp_path.iterdir()}
        assert real_names <= left, "第 %d 天刪了真實快照" % (day + 1)
        assert alerts and alerts[0][0] == "ERROR" and "暫停清理" in alerts[0][1], "第 %d 天沒有告警" % (day + 1)
    assert (tmp_path / archive._PRUNE_HOLD_NAME).is_file()
    assert len(left - real_names - {archive._PRUNE_HOLD_NAME}) == 39     # 暫停期間一份都不刪


def test_state_cc07_short_gap_prunes_normally_without_alert(tmp_path, monkeypatch):
    """正對照：比保留天數短的停機（10 天沒有快照）⇒ 照日期清理、不告警、不寫標記。"""
    import archive
    real = date.today()
    for i in list(range(0, 20)) + list(range(30, 60)):
        (tmp_path / (real - timedelta(days=i)).isoformat()).mkdir()
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    archive._prune_local_db_backups(keep_days=30)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left[0] == (real - timedelta(days=30)).isoformat() and len(left) == 21
    assert alerts == [] and not (tmp_path / archive._PRUNE_HOLD_NAME).exists()


@pytest.mark.parametrize("jump", [3, 10, 29])
def test_state_cc07_small_clock_jump_holds_pruning_every_day(tmp_path, monkeypatch, jump):
    """N-1（稽核確認）：往前跳、但**小於**保留天數。原本「今天以外全部過期」不成立 ⇒ 真實快照照刪、沒有告警
    （稽核實測 30 份：跳 3／10／29 天 ⇒ 刪 2／9／23 份）。應有：最新一份距今天超過 2 天 ⇒ 暫停、寫標記、每天告警，連跑 10 天。"""
    import archive
    real = date.today()
    _days(tmp_path, real, 30)
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    real_names = {p.name for p in tmp_path.iterdir()}
    for day in range(10):
        alerts = []
        monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append((level, r)))
        today = real + timedelta(days=jump + day)
        _fake_today(monkeypatch, archive, today)
        (tmp_path / today.isoformat()).mkdir()                 # 照常每天快照後清理
        archive._prune_local_db_backups(keep_days=30)
        left = {p.name for p in tmp_path.iterdir()}
        assert real_names <= left, "跳 %d 天、第 %d 天刪了真實快照" % (jump, day + 1)
        assert alerts and alerts[0][0] == "ERROR" and "暫停清理" in alerts[0][1], "跳 %d 天、第 %d 天沒有告警" % (jump, day + 1)
    assert (tmp_path / archive._PRUNE_HOLD_NAME).is_file()


def test_state_cc07_two_day_gap_is_still_normal(tmp_path, monkeypatch):
    """邊界：最新一份是前天（差 2 天）⇒ 還算正常（規則是「超過 2 天」），照日期清理、不告警。"""
    import archive
    real = date.today()
    for i in range(2, 40):
        (tmp_path / (real - timedelta(days=i)).isoformat()).mkdir()
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    archive._prune_local_db_backups(keep_days=30)
    assert alerts == [] and not (tmp_path / archive._PRUNE_HOLD_NAME).exists()
    assert min(p.name for p in tmp_path.iterdir()) == (real - timedelta(days=30)).isoformat()


def test_state_cc07_future_dated_snapshot_holds_pruning(tmp_path, monkeypatch):
    """時鐘往回撥：有份數的日期晚於今天 ⇒ 暫停清理並寫標記。"""
    import archive
    real = date.today()
    _days(tmp_path, real, 40)
    (tmp_path / (real + timedelta(days=3)).isoformat()).mkdir()
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    archive._prune_local_db_backups(keep_days=30)
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 41
    assert alerts and "晚於今天" in alerts[0] and (tmp_path / archive._PRUNE_HOLD_NAME).is_file()


def test_state_cc07_held_segment_is_released_by_a_human_not_by_time(tmp_path, monkeypatch):
    """標記不會因為時間過去而自己解除：有人刪掉標記之後，才恢復清理、才安靜（不靠隔天重新推算）。"""
    import archive
    real = date.today()
    _days(tmp_path, real, 40)
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path))
    (tmp_path / archive._PRUNE_HOLD_NAME).write_text("先前偵測到", encoding="utf-8")
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    archive._prune_local_db_backups(keep_days=30)            # 日期完全正常，但標記還在
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 40
    assert alerts and "尚未有人確認" in alerts[0]
    (tmp_path / archive._PRUNE_HOLD_NAME).unlink()           # 有人確認
    alerts.clear()
    archive._prune_local_db_backups(keep_days=30)
    assert alerts == [] and len([p for p in tmp_path.iterdir() if p.is_dir()]) == 31


def test_state_cc07_unreadable_hold_marker_means_hold(tmp_path, monkeypatch):
    """讀不到標記（雲端後端出錯）⇒ 當成暫停（寧可不刪），不是當成沒有。"""
    import archive
    real = date.today()
    _days(tmp_path, real, 40)
    monkeypatch.setattr(archive, "_write_backup_alert", lambda *a, **k: None)
    def _boom(*a, **k):
        raise OSError("雲端讀不到")
    monkeypatch.setattr(archive, "_cloud_marker_exists", _boom)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert archive._prune_select(names, archive._parse_day, real.toordinal() - 30, "測試層",
                                 str(tmp_path / "x" / archive._PRUNE_HOLD_NAME), "每日備份/.prune_hold") == []


def test_state_cc07_cloud_daily_has_the_same_floor(isolated_archive, monkeypatch):
    import archive
    from pathlib import Path
    real = date.today()
    daily = Path(isolated_archive) / "每日備份"
    _days(daily, real, 10)
    monkeypatch.setattr(archive, "_write_backup_alert", lambda *a, **k: None)
    _fake_today(monkeypatch, archive, real + timedelta(days=90))
    archive._prune_cloud_backups(daily_keep_days=60, weekly_keep_days=90, monthly_keep_days=0)
    assert len([p for p in daily.iterdir() if p.is_dir()]) == 10      # 今天以外全部過期 ⇒ 暫停，一份都不刪
    assert (daily / archive._PRUNE_HOLD_NAME).is_file()


# ── S-CC06 ───────────────────────────────────────────────────────────────

def test_state_cc06_monthly_is_retried_even_when_today_daily_is_already_done(monkeypatch, tmp_path):
    """原本：每日 .done 已在 ⇒ 當天後續各輪提早結束、不重試月備份（月底最後一天失敗 ⇒ 那個月永久缺）。"""
    import archive
    for name in ("_snapshot_sqlite", "_rotate_server_log_if_large", "_mirror_uploads",
                 "_mirror_pdf_archives", "_mirror_pii_archives", "_clear_backup_alert_if_healthy"):
        monkeypatch.setattr(archive, name, lambda *a, **k: None)
    monkeypatch.setattr(archive, "_archive_ok", lambda: True)
    monkeypatch.setattr(archive, "_daily_dir", lambda: str(tmp_path))
    monkeypatch.setattr(archive, "_cloud_marker_exists", lambda *a, **k: True)     # 今天的每日 .done 已在
    calls = []
    monkeypatch.setattr(archive, "_monthly_backup", lambda: calls.append("monthly"))
    monkeypatch.setattr(archive, "_check_previous_month_backup", lambda: calls.append("prev"))
    archive._daily_backup()
    assert calls == ["monthly", "prev"]


def _prev_month():
    return (date.today().replace(day=1) - timedelta(days=1))


def test_state_cc06_missing_previous_month_alerts(tmp_path, monkeypatch):
    import archive
    backups = tmp_path / "db_backups"
    (backups / _prev_month().isoformat()).mkdir(parents=True)          # 上個月系統確實在跑
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(backups))
    monkeypatch.setattr(archive, "_monthly_dir", lambda: str(tmp_path / "月備份"))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append((level, r)))
    assert archive._check_previous_month_backup() is True
    assert alerts[0][0] == "ERROR" and _prev_month().strftime("%Y-%m") in alerts[0][1]


def test_state_cc06_done_previous_month_or_fresh_install_is_quiet(tmp_path, monkeypatch):
    import archive
    backups = tmp_path / "db_backups"
    backups.mkdir()
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(backups))
    monkeypatch.setattr(archive, "_monthly_dir", lambda: str(tmp_path / "月備份"))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append(r))
    assert archive._check_previous_month_backup() is False               # 全新安裝：上個月沒在跑
    (backups / _prev_month().isoformat()).mkdir()
    done = tmp_path / "月備份" / _prev_month().strftime("%Y-%m") / ".done"
    done.parent.mkdir(parents=True)
    done.write_text("x")
    assert archive._check_previous_month_backup() is False               # 上個月已完成
    assert alerts == []


# ── S-CN03 告警的告警 ─────────────────────────────────────────────────────

class _Handle:
    def __init__(self, outcome):
        self.outcome = outcome

    def wait(self, timeout=None):
        return self.outcome


@pytest.fixture()
def alert_env(tmp_path, monkeypatch):
    import archive
    import helpers.email_notify as en
    monkeypatch.setattr(archive, "_ALERT_DIR", str(tmp_path / "backup_alerts"))
    audits, sent = [], []
    monkeypatch.setattr(archive, "_system_audit", lambda action, *a, **k: audits.append(action))
    monkeypatch.setattr(en, "_superadmin_emails", lambda key=None: ["boss@example.invalid"])
    state = {"outcome": en.SEND_SENT}
    threads = []
    real_send = archive._send_backup_error_email

    def _send(to, subject, html):
        sent.append(subject)
        return _Handle(state["outcome"])
    monkeypatch.setattr(en, "_async_send", _send)

    def _spy(reason, ts):
        t = real_send(reason, ts)
        if t is not None:
            threads.append(t)
        return t
    monkeypatch.setattr(archive, "_send_backup_error_email", _spy)

    def join():
        for t in threads:
            t.join(5)
        threads.clear()
    return archive, audits, sent, state, join, tmp_path / "backup_alerts"


def test_state_cn03_success_is_throttled_to_one_email_per_day(alert_env):
    archive, audits, sent, state, join, _d = alert_env
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    assert len(sent) == 1 and audits.count("backup.alert") == 1


def test_state_cn03_failed_email_is_not_throttled_and_leaves_a_trace(alert_env):
    """原本：節流標記在寄信前就寫 ⇒ 寄失敗當天不再寄、也沒有任何痕跡。"""
    archive, audits, sent, state, join, d = alert_env
    import helpers.email_notify as en
    state["outcome"] = en.SEND_TRANSIENT_FAIL
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    assert "backup.alert_email_failed" in audits
    assert "寄不出去" in (d / "BACKUP_ALERT.txt").read_text(encoding="utf-8")
    state["outcome"] = en.SEND_SENT
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")      # 下一輪重寄
    join()
    assert len(sent) == 2



def test_state_cn03_failure_trace_is_rate_limited_per_day(alert_env):
    """X 稽核 B-4：寄不出去的 audit 同原因每天一筆；寄信照樣每輪重試；警示檔每次整檔覆寫，註記每次都在、不會變長。
    「設定成不寄信」要與「寄了但失敗」分開寫。"""
    archive, audits, sent, state, join, d = alert_env
    import helpers.email_notify as en
    state["outcome"] = en.SEND_SKIPPED
    for _ in range(5):
        archive._write_backup_alert("雲端路徑不可用", level="ERROR")
        join()
    assert len(sent) == 5                                           # 寄信照樣每輪重試
    assert audits.count("backup.alert_email_failed") == 1
    txt = (d / "BACKUP_ALERT.txt").read_text(encoding="utf-8")
    assert txt.count("寄不出去") == 1 and "設定成不寄信" in txt
    state["outcome"] = en.SEND_TRANSIENT_FAIL                       # 不同的寄不出去原因 ⇒ 另留一筆
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    assert audits.count("backup.alert_email_failed") == 2

def test_state_cn03_unwritable_alert_dir_still_audits_and_emails(alert_env, monkeypatch, tmp_path):
    """原本：警示目錄寫不進去 ⇒ 同一個 try 裡的 audit 與寄信都不執行。"""
    archive, audits, sent, state, join, _d = alert_env
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("file where the alert dir should be")
    monkeypatch.setattr(archive, "_ALERT_DIR", str(blocker))
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    assert "backup.alert" in audits and len(sent) == 1


def test_state_cn03_no_recipient_is_recorded(alert_env, monkeypatch):
    archive, audits, sent, state, join, _d = alert_env
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_superadmin_emails", lambda key=None: [])
    archive._write_backup_alert("雲端路徑不可用", level="ERROR")
    join()
    assert sent == [] and "backup.alert_email_failed" in audits


def test_state_cn03_warn_level_never_emails(alert_env):
    archive, audits, sent, state, join, _d = alert_env
    archive._write_backup_alert("每日 JSON 有一張表失敗", level="WARN")
    join()
    assert sent == [] and "backup.alert" in audits


# ── S-CU10 ───────────────────────────────────────────────────────────────

def _upgrade_install(tmp_path):
    root = tmp_path / "install"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "db.py").write_text("# v9")
    _full_db(root / "backend" / "motrix_erp.db")
    snap = root / "backend" / "db_backups" / date.today().isoformat()
    snap.mkdir(parents=True)
    (snap / ".done").write_text("x")
    return str(root)


def test_state_cu10_preflight_passes_on_healthy_db(tmp_path):
    from core import upgrade as U
    r = U.preflight(_upgrade_install(tmp_path), v9_port_open=False)
    assert r["ok"], r["problems"]


def test_state_cu10_preflight_blocks_corrupt_db(tmp_path):
    from core import upgrade as U
    root = _upgrade_install(tmp_path)
    _corrupt_tail(os.path.join(root, "backend", "motrix_erp.db"))
    r = U.preflight(root, v9_port_open=False)
    assert not r["ok"] and any("quick_check" in p for p in r["problems"]), r["problems"]
