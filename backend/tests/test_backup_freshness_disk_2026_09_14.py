"""備份新鮮度與磁碟空間告警（2026-09-14）——`routers/daily_tasks.py` 的
`_check_backup_freshness()` / `_check_disk_space()`。

補的是「備份系統的所有告警都由備份自己發出」這個結構性盲區：備份**沒跑**時
現況完全安靜（伺服器活著、heartbeat 照打、備份頁面綠燈），只有真的要還原那天
才會發現最後一份是三個月前的。

觀測點一律挑「有沒有真的觸發那封信」——用 monkeypatch 換掉 notify 函式並記錄
呼叫參數，而不是驗 _get_setting 讀回自己剛寫的值（那證明不了信會不會寄出）。
"""
import os
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def sent(monkeypatch):
    """攔截兩支通知函式，回傳收集到的呼叫清單。

    ⚠️ 一定要 patch `routers.daily_tasks` 模組上的名字，不是
    `helpers.email_notify` 上的——daily_tasks 是 `from helpers import notify_...`
    把函式綁成自己的模組屬性，patch 原始出處不會影響它已經綁好的那份參照。
    """
    import routers.daily_tasks as dt
    calls = {"backup": [], "disk": []}
    monkeypatch.setattr(dt, "notify_backup_stale",
                        lambda *a, **k: calls["backup"].append((a, k)))
    monkeypatch.setattr(dt, "notify_disk_space_low",
                        lambda *a, **k: calls["disk"].append((a, k)))
    # 兩支檢查都用 threading.Thread 送信（比照 _check_cert_expiry），測試裡
    # 改成同步執行，否則斷言會跟執行緒賽跑。
    monkeypatch.setattr(dt.threading, "Thread",
                        lambda target=None, args=(), daemon=None, **kw:
                        type("T", (), {"start": lambda self, t=target, a=args: t(*a)})())
    return calls


def _insert_backup_audit(action: str, at: datetime):
    from db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (at, username, display_name, action, target_type, "
        "target_id, target_label, detail) VALUES (?,?,?,?,?,?,?,?)",
        (at.isoformat(), "system", "系統自動", action, "system", "", "", "{}"))
    conn.commit()
    conn.close()


# ── 備份新鮮度 ──────────────────────────────────────────────────────────────

def test_no_backup_history_at_all_does_not_alert(client, sent):
    """全新環境（一筆備份紀錄都沒有）不是故障，是還沒跑過第一次。
    這裡誤報會讓人第一天就學會忽略這封信。"""
    import routers.daily_tasks as dt
    dt._check_backup_freshness()
    assert sent["backup"] == []


def test_fresh_backup_does_not_alert(client, sent):
    import routers.daily_tasks as dt
    now = datetime.now()
    _insert_backup_audit("backup.sqlite_snapshot", now - timedelta(hours=3))
    _insert_backup_audit("backup.daily_ok", now - timedelta(hours=3))
    dt._check_backup_freshness()
    assert sent["backup"] == []


def test_stale_backup_alerts_with_both_layers(client, sent):
    import routers.daily_tasks as dt
    old = datetime.now() - timedelta(hours=50)
    _insert_backup_audit("backup.sqlite_snapshot", old)
    _insert_backup_audit("backup.daily_ok", old)

    dt._check_backup_freshness()

    assert len(sent["backup"]) == 1, "超過 36 小時應該要寄信"
    stale_list = sent["backup"][0][0][0]
    labels = [lbl for lbl, _ in stale_list]
    assert "本機 SQLite 快照" in labels and "雲端每日備份" in labels


def test_cloud_stale_but_local_fresh_reports_only_cloud(client, sent):
    """本機快照還活著、只有雲端那層斷掉——這正是「另一台機器搶先寫了 .done
    害正式機早退」的症狀。信裡要指名是哪一層，不能只講「備份有問題」。"""
    import routers.daily_tasks as dt
    _insert_backup_audit("backup.sqlite_snapshot", datetime.now() - timedelta(hours=2))
    _insert_backup_audit("backup.daily_ok", datetime.now() - timedelta(hours=72))

    dt._check_backup_freshness()

    assert len(sent["backup"]) == 1
    labels = [lbl for lbl, _ in sent["backup"][0][0][0]]
    assert labels == ["雲端每日備份"]


def test_partial_backup_counts_as_having_run(client, sent):
    """`backup.daily_partial` 代表備份確實跑了、只是有表失敗——那個情境有自己的
    告警，這支不該重複叫。"""
    import routers.daily_tasks as dt
    _insert_backup_audit("backup.sqlite_snapshot", datetime.now() - timedelta(hours=2))
    _insert_backup_audit("backup.daily_partial", datetime.now() - timedelta(hours=2))
    dt._check_backup_freshness()
    assert sent["backup"] == []


def test_alerts_at_most_once_per_day(client, sent):
    import routers.daily_tasks as dt
    old = datetime.now() - timedelta(hours=50)
    _insert_backup_audit("backup.sqlite_snapshot", old)
    _insert_backup_audit("backup.daily_ok", old)

    dt._check_backup_freshness()
    dt._check_backup_freshness()
    dt._check_backup_freshness()

    assert len(sent["backup"]) == 1, "一天最多一封"


def test_guard_clears_when_backup_recovers(client, sent):
    """壞了寄一封 → 修好 → 再壞應該要能**立刻再寄**，而不是被昨天的 guard 擋住。"""
    import routers.daily_tasks as dt
    from helpers import _get_setting

    old = datetime.now() - timedelta(hours=50)
    _insert_backup_audit("backup.sqlite_snapshot", old)
    _insert_backup_audit("backup.daily_ok", old)
    dt._check_backup_freshness()
    assert len(sent["backup"]) == 1

    # 備份恢復
    _insert_backup_audit("backup.sqlite_snapshot", datetime.now())
    _insert_backup_audit("backup.daily_ok", datetime.now())
    dt._check_backup_freshness()
    assert _get_setting("backup_stale_last_notified") in ("", None), \
        "恢復正常時要清掉 guard，否則同一天再壞就叫不出來"


# ── 磁碟空間 ────────────────────────────────────────────────────────────────

def test_healthy_disk_does_not_alert(client, sent, monkeypatch):
    import routers.daily_tasks as dt
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 1000 * 1024 ** 3,
                                 "used": 400 * 1024 ** 3,
                                 "free": 600 * 1024 ** 3})())
    dt._check_disk_space()
    assert sent["disk"] == []


def test_low_disk_alerts(client, sent, monkeypatch):
    """同時低於 10% 與 20 GB 才叫——兩個門檻取「較寬鬆的滿足就算健康」。"""
    import routers.daily_tasks as dt
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 100 * 1024 ** 3,
                                 "used": 95 * 1024 ** 3,
                                 "free": 5 * 1024 ** 3})())
    dt._check_disk_space()

    assert len(sent["disk"]) == 1
    problems = sent["disk"][0][0][0]
    assert problems and problems[0]["free_gb"] == 5.0


def test_big_disk_with_low_pct_but_plenty_of_gb_is_fine(client, sent, monkeypatch):
    """2 TB 的碟剩 8%（164 GB）不該叫——只看百分比會太早吵。"""
    import routers.daily_tasks as dt
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 2048 * 1024 ** 3,
                                 "used": 1884 * 1024 ** 3,
                                 "free": 164 * 1024 ** 3})())
    dt._check_disk_space()
    assert sent["disk"] == []


def test_small_disk_with_enough_pct_is_fine(client, sent, monkeypatch):
    """256 GB 的碟剩 15%（38 GB）也不該叫——只看絕對 GB 會太晚。"""
    import routers.daily_tasks as dt
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 256 * 1024 ** 3,
                                 "used": 218 * 1024 ** 3,
                                 "free": 38 * 1024 ** 3})())
    dt._check_disk_space()
    assert sent["disk"] == []


def test_disk_targets_dedupe_same_drive(client):
    """資料庫碟跟雲端存檔碟在測試環境下都在同一顆暫存碟——同一個磁碟機代號
    只該回報一次，否則信裡會出現兩列一模一樣的內容。"""
    import routers.daily_tasks as dt
    targets = dt._disk_targets()
    drives = [os.path.splitdrive(os.path.abspath(p))[0].upper() for _, p in targets]
    assert len(drives) == len(set(drives))


# ── 接線：確認真的掛進每日排程，不是寫了沒人呼叫 ─────────────────────────────

def test_checks_are_wired_into_daily_schedule():
    """這兩支的價值完全來自「每天真的會跑」。只驗函式本身正確、沒驗有沒有被
    排程呼叫，就是典型的假綠燈——2026-09-10 `case_project_overdue` 那個
    notification key 漏註冊就是同一類。"""
    import inspect
    import routers.daily_tasks as dt

    src = inspect.getsource(dt.schedule_overdue_check)
    assert src.count("_check_backup_freshness()") >= 3, \
        "每日排程／首次啟動／補跑三條路徑都要呼叫"
    assert src.count("_check_disk_space()") >= 3


def test_notification_keys_registered():
    """event key 沒註冊不會報錯，只是使用者在「通知偏好」永遠看不到、關不掉。"""
    from helpers.notification_prefs import EVENT_KEYS
    assert "backup_stale" in EVENT_KEYS
    assert "disk_space_low" in EVENT_KEYS
