"""「這台機器要不要上傳雲端」的政策開關（2026-09-15 使用者指示）——
`archive.py::cloud_archive_enabled()`。

使用者指示：「開發機的所有檔案不上傳雲端，但正式機需要上傳雲端」。

**為什麼不能只靠既有的所有權標記**（`_archive_owner_ok()`，2026-09-14）：那個是
「防兩台互相覆蓋」的碰撞防護，不是政策開關，而且它有兩條會反過來咬人的路徑——
marker 不存在時會**自動認領**（Drive 同步異常、有人刪掉、重新掛載都可能），
開發機一認領成功就換成正式機被擋住、雲端備份整個停掉；讀 marker 失敗時 fail-open。

所以這裡最重要的一題是 `test_disabled_machine_never_claims_ownership`：
停用狀態下連 marker 都不能碰。

觀測點一律挑「**檔案有沒有真的被寫出去**」，而且每一題都配一個允許上傳時的正向
控制——只斷言「沒寫東西」的話，備份功能整個壞掉也會通過。
"""
import json
import os
from datetime import date, datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _clean_state():
    """所有權檢查有 300 秒 TTL 快取；政策狀態也有一個「變了才寫 log」的記錄。
    每題前後都清掉，否則驗到的是上一題留下的判定。

    ⚠️ **標記檔也要刪**：conftest 把它導到 session 級的暫存目錄，所以前一題建的
    檔案會留給下一題——寫這支測試時就先踩到了（`test_policy_is_not_cached` 紅在
    第一行「預設應該是允許」上，因為前一題剛把它建起來）。
    """
    import archive
    def _reset():
        archive._owner_cache.update({"base": None, "ok": None, "checked_at": 0.0, "reason": ""})
        archive._cloud_policy_state["enabled"] = None
        os.environ.pop("MOTRIX_CLOUD_ARCHIVE", None)
        try:
            os.remove(archive._NO_CLOUD_MARKER_PATH)
        except OSError:
            pass
    _reset()
    yield
    _reset()


def _disable_by_file():
    """比照開發機的真實作法：在（已被 conftest 導到 tmp 的）標記路徑建檔案。"""
    import archive
    with open(archive._NO_CLOUD_MARKER_PATH, "w", encoding="utf-8") as f:
        f.write("測試用\n")


# ── 判斷來源與優先序 ────────────────────────────────────────────────────────

def test_enabled_by_default(client):
    """沒有任何標記 → 允許上傳。**預設必須是允許**：兩個方向的風險不對稱，
    正式機誤停的代價是備份靜靜消失好幾週（2026-08-24 真的發生過）。"""
    import archive
    assert archive.cloud_archive_enabled() is True


def test_marker_file_disables(client):
    import archive
    _disable_by_file()
    assert archive.cloud_archive_enabled() is False


def test_env_var_disables(client):
    import archive
    os.environ["MOTRIX_CLOUD_ARCHIVE"] = "off"
    assert archive.cloud_archive_enabled() is False


def test_env_var_wins_over_marker_file(client):
    """環境變數優先於檔案——想臨時反過來測時不必刪掉開發機的標記檔
    （刪了很容易忘記補回去，那就變成開發機默默開始上傳）。"""
    import archive
    _disable_by_file()
    os.environ["MOTRIX_CLOUD_ARCHIVE"] = "on"
    assert archive.cloud_archive_enabled() is True


def test_policy_is_not_cached(client):
    """改了標記要**立刻**生效，不能要求重啟服務。發現開發機正在污染雲端的那一刻，
    需要重啟才算數的開關等於沒有用。"""
    import archive
    assert archive.cloud_archive_enabled() is True
    _disable_by_file()
    assert archive.cloud_archive_enabled() is False
    os.remove(archive._NO_CLOUD_MARKER_PATH)
    assert archive.cloud_archive_enabled() is True


# ── 停用時真的什麼都不寫 ────────────────────────────────────────────────────

def test_disabled_machine_never_claims_ownership(client, isolated_archive):
    """**這一題是整個功能的重點。**

    停用狀態下對一個「還沒有所有權標記」的存檔目錄做檢查，不可以寫下 marker。
    寫下去的後果不是「開發機多傳了東西」，而是**正式機從此被自己的防呆擋在門外**，
    症狀還是完全靜默的（沒有錯誤，只是沒有備份）。
    """
    import archive
    marker = os.path.join(isolated_archive, ".motrix_archive_owner")
    _disable_by_file()

    assert archive._archive_owner_ok() is False
    assert archive._archive_ok() is False
    assert not os.path.exists(marker), "停用狀態下竟然認領了存檔目錄的所有權"
    assert os.listdir(isolated_archive) == [], os.listdir(isolated_archive)

    # 正向控制：允許上傳時才會認領（證明這題不是因為認領功能整個壞掉才通過）
    os.environ["MOTRIX_CLOUD_ARCHIVE"] = "on"
    archive._owner_cache.update({"base": None, "ok": None, "checked_at": 0.0, "reason": ""})
    assert archive._archive_owner_ok() is True
    assert os.path.isfile(marker)


def test_disabled_machine_writes_nothing_to_the_archive(client, isolated_archive):
    """每日備份整套跑完，雲端存檔目錄要一個檔案都沒有。"""
    import archive
    _disable_by_file()

    archive._daily_backup()

    assert os.listdir(isolated_archive) == [], os.listdir(isolated_archive)

    # 正向控制：允許上傳時同一支函式會寫出東西
    os.environ["MOTRIX_CLOUD_ARCHIVE"] = "on"
    archive._owner_cache.update({"base": None, "ok": None, "checked_at": 0.0, "reason": ""})
    archive._daily_backup()
    assert os.listdir(isolated_archive), "允許上傳時卻什麼都沒寫——這題的正向控制失效了"


def test_local_sqlite_snapshot_still_runs_when_cloud_is_off(client, isolated_archive, tmp_path):
    """停掉的只有「上傳雲端」，本機快照照舊——開發機也還是要有本機備份。"""
    import archive
    _disable_by_file()

    archive._snapshot_sqlite()

    local = archive._LOCAL_DB_BACKUP
    assert os.path.isdir(local), local
    found = [f for _r, _d, fs in os.walk(local) for f in fs if f.endswith(".db")]
    assert found, "本機 SQLite 快照沒有產生"
    assert os.listdir(isolated_archive) == [], "雲端存檔目錄不該有東西"


def test_disabled_machine_clears_stale_backup_alert(client, isolated_archive):
    """不上傳的機器上留著「雲端備份寫不進去」的警示檔是過期資訊，會訓練大家忽略它。"""
    import archive
    os.makedirs(archive._ALERT_DIR, exist_ok=True)
    alert = os.path.join(archive._ALERT_DIR, "BACKUP_ALERT.txt")
    with open(alert, "w", encoding="utf-8") as f:
        f.write("舊的雲端備份警示\n")

    _disable_by_file()
    archive._clear_backup_alert_if_healthy()
    assert not os.path.exists(alert)


# ── 不上傳的機器不該收到「雲端備份過期」的假警報 ────────────────────────────

def test_no_stale_cloud_alert_on_a_machine_that_does_not_upload(client, make_user, monkeypatch):
    """本機快照是新的、雲端那條線從來沒有紀錄 → 不該寄信。

    這是設定造成的「沒有雲端備份」，不是故障；每天寄一封只會讓人學會忽略這封信。
    """
    import archive
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    sent = []
    monkeypatch.setattr(dt, "notify_backup_stale", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(dt.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None, **kw:
                        type("T", (), {"start": lambda self, t=target, a=args, k=kwargs:
                                       t(*a, **(k or {}))})())
    _insert_backup_audit("backup.sqlite_snapshot", datetime.now() - timedelta(hours=1))
    _disable_by_file()

    dt._check_backup_freshness()
    assert sent == [], sent

    # 正向控制：同一份資料，允許上傳的機器就該叫（雲端那條線是空的）
    os.environ["MOTRIX_CLOUD_ARCHIVE"] = "on"
    dt._set_setting("backup_stale_last_notified", "")
    dt._check_backup_freshness()
    assert len(sent) == 1, "允許上傳時雲端那條線缺紀錄卻沒告警"
    assert any("雲端" in str(x) for x in sent[0][0]), sent[0]


def test_local_snapshot_staleness_still_alerts_when_cloud_is_off(client, make_user, monkeypatch):
    """關掉的只有雲端那條線。本機快照停了照樣要叫——那才是「備份程式沒在跑」。"""
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    sent = []
    monkeypatch.setattr(dt, "notify_backup_stale", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(dt.threading, "Thread",
                        lambda target=None, args=(), kwargs=None, daemon=None, **kw:
                        type("T", (), {"start": lambda self, t=target, a=args, k=kwargs:
                                       t(*a, **(k or {}))})())
    _insert_backup_audit("backup.sqlite_snapshot", datetime.now() - timedelta(days=5))
    _disable_by_file()

    dt._check_backup_freshness()
    assert len(sent) == 1, "本機快照過期卻沒告警"
    labels = str(sent[0][0])
    assert "本機" in labels, labels
    assert "雲端" not in labels, "不上傳的機器不該把雲端那條列進告警：%s" % labels


def _insert_backup_audit(action: str, at: datetime):
    from db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (at, username, display_name, action, target_type, "
        "target_id, target_label, detail) VALUES (?,?,?,?,?,?,?,?)",
        (at.isoformat(), "system", "系統自動", action, "system", "", "", "{}"))
    conn.commit()
    conn.close()


# ── 這個標記檔絕對不能被帶到正式機 ──────────────────────────────────────────

def test_marker_file_is_gitignored():
    """打包走 `git archive`（只含已追蹤內容），所以只要它在 .gitignore 裡，就不可能
    跟著部署包跑到正式機。**這是選用「檔案」而不是「設定值」的整個理由**——設定值
    會隨資料庫還原一起搬家，那正是 DR 換機時最不該發生的事（新正式機靜靜不備份）。
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    gitignore = os.path.join(root, ".gitignore")
    with open(gitignore, encoding="utf-8") as f:
        lines = [l.strip() for l in f]
    assert ".no_cloud_archive" in lines, "標記檔沒有被 gitignore，會被帶進部署包"
