"""雲端存檔所有權守門（2026-09-14）——`archive.py::_archive_owner_ok()`。

擋的情境：**第二台機器掛著同一顆雲端碟也在跑這份程式碼**（開發機、備援機、
DR 還原出來的機器）。原本兩個後果都是完全靜默的：

  ① 先跑的那台寫下當日 `.done`，正式機看到就早退——而且早退那條路徑還會
     `_clear_backup_alert_if_healthy()`，順手把警示清掉。當天沒備份、綠燈。
  ② `_snapshot_sqlite()` 的雲端複製不看 marker，第二台會直接覆蓋當天的
     `每日備份/{date}/motrix_erp.db`，也就是還原優先序的第二層。

所以這裡的斷言都挑「檔案有沒有真的被寫出去／被覆蓋」，不是回傳值。
"""
import json
import os
from datetime import date

import pytest


def _marker(base):
    return os.path.join(base, ".motrix_archive_owner")


def _reset_owner_cache():
    """所有權檢查有 300 秒 TTL 快取（避免每次即時備份都讀檔），測試裡每次
    改完 marker 都要清掉，否則驗到的是上一題留下的判定。"""
    import archive
    archive._owner_cache.update({"ok": None, "checked_at": 0.0, "reason": ""})


@pytest.fixture(autouse=True)
def _clean_cache():
    _reset_owner_cache()
    yield
    _reset_owner_cache()


def test_claims_ownership_on_first_use(isolated_archive):
    """空的存檔目錄第一次使用時自動認領——這是正式機的正常升級路徑，
    不該需要任何人工步驟。"""
    import archive

    assert archive._archive_ok() is True
    assert os.path.isfile(_marker(isolated_archive))

    owner = json.load(open(_marker(isolated_archive), encoding="utf-8"))
    assert owner["instance_id"] == archive._archive_instance_id()
    assert "claimed_at" in owner


def test_same_instance_passes_on_subsequent_runs(isolated_archive):
    import archive

    assert archive._archive_ok() is True
    _reset_owner_cache()
    assert archive._archive_ok() is True


def test_foreign_owner_blocks_cloud_writes(isolated_archive):
    """marker 屬於另一套系統 → 整個雲端備份停寫。"""
    import archive

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        json.dump({"instance_id": "別台機器的識別碼",
                   "machine": "OTHER-PC", "claimed_at": "2026-01-01T00:00:00"}, f)
    _reset_owner_cache()

    assert archive._archive_ok() is False


def test_foreign_owner_does_not_overwrite_existing_daily_db_snapshot(isolated_archive):
    """這一題才是真正要守的東西：別人的當日整庫備份**不可以被蓋掉**。
    （原本 _snapshot_sqlite() 的雲端複製連 .done 都不看，無條件 copy2。）"""
    import archive

    today = date.today().isoformat()
    other_day_dir = os.path.join(archive._daily_dir(), today)
    os.makedirs(other_day_dir, exist_ok=True)
    victim = os.path.join(other_day_dir, "motrix_erp.db")
    with open(victim, "w", encoding="utf-8") as f:
        f.write("正式機的備份，不可以被開發機蓋掉")

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        json.dump({"instance_id": "正式機", "machine": "PROD", "claimed_at": "2026-01-01"}, f)
    _reset_owner_cache()

    archive._snapshot_sqlite(also_to_cloud=True)

    assert open(victim, encoding="utf-8").read() == "正式機的備份，不可以被開發機蓋掉"


def test_foreign_owner_still_keeps_local_snapshot(isolated_archive):
    """雲端停寫，但**本機 SQLite 快照照做**——本機那層不依賴雲端碟，
    停掉它等於為了防一個問題製造另一個更大的問題。"""
    import archive

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        json.dump({"instance_id": "別台", "machine": "OTHER", "claimed_at": "2026-01-01"}, f)
    _reset_owner_cache()

    path = archive._snapshot_sqlite(also_to_cloud=True)

    assert path and os.path.isfile(path), "本機快照不該因為雲端所有權不符而停掉"


def test_foreign_owner_writes_specific_alert_not_generic_mount_error(isolated_archive):
    """告警訊息要講**真正的原因**。原本 _ensure_archive_dirs() 對所有
    `_archive_ok()==False` 一律報「路徑不存在或未掛載」——碟明明好好的，
    用那個理由去查會整個查錯方向。"""
    import archive

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        json.dump({"instance_id": "別台", "machine": "DEV-PC", "claimed_at": "2026-01-01"}, f)
    _reset_owner_cache()

    archive._ensure_archive_dirs()

    alert = os.path.join(archive._ALERT_DIR, "BACKUP_ALERT.txt")
    assert os.path.isfile(alert)
    text = open(alert, encoding="utf-8").read()
    assert "另一套系統" in text
    assert "DEV-PC" in text
    assert "未掛載" not in text, "不該用『碟沒掛上』這個錯誤的理由蓋掉真正的原因"


def test_deleting_marker_allows_takeover(isolated_archive):
    """刻意留的轉移所有權途徑：刪掉 marker 就能重新認領。DR 換機、或確定要
    讓另一台接手時用得到，而且訊息裡就寫著這一步。"""
    import archive

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        json.dump({"instance_id": "舊機器", "machine": "OLD", "claimed_at": "2026-01-01"}, f)
    _reset_owner_cache()
    assert archive._archive_ok() is False

    os.remove(_marker(isolated_archive))
    _reset_owner_cache()

    assert archive._archive_ok() is True
    owner = json.load(open(_marker(isolated_archive), encoding="utf-8"))
    assert owner["instance_id"] == archive._archive_instance_id()


def test_unreadable_marker_fails_open(isolated_archive):
    """marker 壞掉（被同步工具寫壞、編碼錯）時 fail-open——這層是針對罕見
    情境的防呆，不該因為一次 IO 異常就把每天的備份整個停掉。"""
    import archive

    with open(_marker(isolated_archive), "w", encoding="utf-8") as f:
        f.write("{ 這不是合法 JSON")
    _reset_owner_cache()

    assert archive._archive_ok() is True


def test_instance_id_is_stable_across_calls(isolated_archive):
    """識別碼綁在資料庫上（system_settings），不是每次呼叫重產——不然每次
    檢查都會跟自己對不上。"""
    import archive

    a = archive._archive_instance_id()
    b = archive._archive_instance_id()
    assert a == b and len(a) == 32
