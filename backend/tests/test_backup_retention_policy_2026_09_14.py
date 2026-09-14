"""備份保留政策改版與月備份永久保留層（2026-09-14 使用者裁示）。

政策：
  每日備份 60 天 → 過期清除
  週備份   90 天 → 過期清除
  月備份   永久保留（新增的一層；cloud_monthly_keep_days = 0 代表永不清除）
  上傳檔案鏡像／PDF存檔鏡像 → **任何情況都不清除**（使用者明訂長久保留）
  backend/db_backups/pre_update_* → 按份數保留最新 5 份（原本完全沒清過）

這裡的斷言刻意都挑「函式跑完之後檔案系統的真實狀態」當觀測點，而不是回傳值或
呼叫次數——這批邏輯的價值就在於「該刪的刪了、不該刪的還在」，讀回自己設的
參數不能證明任何事。
"""
import os
from datetime import date, timedelta

import pytest


# ── 共用：在假的雲端存檔目錄底下造出各層的日期資料夾 ─────────────────────────

def _mkdir_with_file(root, *parts):
    """建一個資料夾並在裡面放一個檔案——空資料夾在某些檔案系統/同步工具下
    行為特殊，放一個檔案才能真的驗證「整個資料夾連內容一起被刪掉」。"""
    d = os.path.join(root, *parts)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "彙總.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    return d


@pytest.fixture
def arch(isolated_archive):
    """`isolated_archive`（見 conftest）給這一題一個全新的存檔根目錄——
    `_app` 建的那個是 session 級共用，不隔離的話各題造的日期資料夾會互相干擾。"""
    import archive
    return archive


# ── 每日 60 天 / 週 90 天 ───────────────────────────────────────────────────

def test_daily_pruned_at_60_days_weekly_at_90(arch):
    base = arch._archive_base()
    today = date.today()

    keep_daily = (today - timedelta(days=59)).isoformat()
    drop_daily = (today - timedelta(days=61)).isoformat()
    _mkdir_with_file(base, "每日備份", keep_daily)
    _mkdir_with_file(base, "每日備份", drop_daily)

    keep_weekly = (today - timedelta(days=80)).strftime("%Y-W%W")
    drop_weekly = (today - timedelta(days=200)).strftime("%Y-W%W")
    _mkdir_with_file(base, "週備份", keep_weekly)
    _mkdir_with_file(base, "週備份", drop_weekly)

    ret = arch._backup_retention()
    arch._prune_cloud_backups(daily_keep_days=ret["cloud_daily_keep_days"],
                              weekly_keep_days=ret["cloud_weekly_keep_days"],
                              monthly_keep_days=ret["cloud_monthly_keep_days"])

    assert os.path.isdir(os.path.join(base, "每日備份", keep_daily))
    assert not os.path.exists(os.path.join(base, "每日備份", drop_daily))
    assert os.path.isdir(os.path.join(base, "週備份", keep_weekly))
    assert not os.path.exists(os.path.join(base, "週備份", drop_weekly))


# ── 月備份永久保留 ──────────────────────────────────────────────────────────

def test_monthly_never_pruned_by_default(arch):
    """預設 cloud_monthly_keep_days=0 → 連 10 年前的月備份都不能被刪掉。
    這是「長久只留月備份」這條政策的核心，壞掉等於長期備份無聲消失。"""
    base = arch._archive_base()
    ancient = (date.today() - timedelta(days=3650)).strftime("%Y-%m")
    _mkdir_with_file(base, "月備份", ancient)

    ret = arch._backup_retention()
    assert ret["cloud_monthly_keep_days"] == 0
    arch._prune_cloud_backups(daily_keep_days=ret["cloud_daily_keep_days"],
                              weekly_keep_days=ret["cloud_weekly_keep_days"],
                              monthly_keep_days=ret["cloud_monthly_keep_days"])

    assert os.path.isdir(os.path.join(base, "月備份", ancient)), \
        "月備份是永久保留層，預設設定下不得被清除"


def test_monthly_pruned_only_when_explicitly_configured(arch):
    """把 cloud_monthly_keep_days 設成正數時才會清——確認那條分支真的接得上，
    不是寫了一段永遠不會執行的死碼。"""
    base = arch._archive_base()
    old = (date.today() - timedelta(days=400)).strftime("%Y-%m")
    recent = date.today().strftime("%Y-%m")
    _mkdir_with_file(base, "月備份", old)
    _mkdir_with_file(base, "月備份", recent)

    arch._prune_cloud_backups(daily_keep_days=60, weekly_keep_days=90,
                              monthly_keep_days=365)

    assert not os.path.exists(os.path.join(base, "月備份", old))
    assert os.path.isdir(os.path.join(base, "月備份", recent))


# ── 鏡像目錄永不被清（使用者明訂長久保留） ───────────────────────────────────

def test_prune_never_touches_upload_and_pdf_mirrors(arch):
    """上傳檔案鏡像／PDF存檔鏡像裡放的是照片、簽回單、各類單據 PDF 的原始憑據，
    使用者明訂長久保留。它們在存檔根目錄下跟每日/週/月備份是平行的兄弟目錄，
    未來只要有人在 _prune_cloud_backups() 裡多加一個目錄就可能誤傷——這一題
    用「連名字看起來像超舊日期的子資料夾都不准消失」把那條路封起來。"""
    base = arch._archive_base()
    ancient = (date.today() - timedelta(days=3000)).isoformat()
    _mkdir_with_file(base, "上傳檔案鏡像", "quotations", "MQ-202001-001")
    _mkdir_with_file(base, "上傳檔案鏡像", ancient)
    _mkdir_with_file(base, "PDF存檔鏡像", "報價單", ancient)

    arch._prune_cloud_backups(daily_keep_days=1, weekly_keep_days=1,
                              monthly_keep_days=1)

    assert os.path.isdir(os.path.join(base, "上傳檔案鏡像", "quotations", "MQ-202001-001"))
    assert os.path.isdir(os.path.join(base, "上傳檔案鏡像", ancient))
    assert os.path.isdir(os.path.join(base, "PDF存檔鏡像", "報價單", ancient))


def test_prune_ignores_unparseable_folder_names(arch):
    """沿用既有安全機制：名稱 parse 不出日期的一律不動（人手放進去的東西、
    其他工具建的資料夾）。"""
    base = arch._archive_base()
    for layer, name in (("每日備份", "手動匯出_請勿刪除"),
                        ("週備份", "readme"),
                        ("月備份", "2026-13")):        # 13 月，parse 不出來
        _mkdir_with_file(base, layer, name)

    arch._prune_cloud_backups(daily_keep_days=1, weekly_keep_days=1,
                              monthly_keep_days=1)

    assert os.path.isdir(os.path.join(base, "每日備份", "手動匯出_請勿刪除"))
    assert os.path.isdir(os.path.join(base, "週備份", "readme"))
    assert os.path.isdir(os.path.join(base, "月備份", "2026-13"))


# ── pre_update_* 按份數保留 ─────────────────────────────────────────────────

def test_pre_update_snapshots_keep_latest_n(arch, tmp_path):
    """apply_update.ps1 每次套用都留一份整庫快照，原本永遠不會被清
    （_prune_local_db_backups 只處理 parse 得出日期的資料夾名）。"""
    local = str(tmp_path / "db_backups")
    os.makedirs(local)
    arch._LOCAL_DB_BACKUP = local

    names = [f"pre_update_2026091{i}_120000" for i in range(1, 9)]   # 8 份
    for n in names:
        os.makedirs(os.path.join(local, n))
        with open(os.path.join(local, n, "motrix_erp.db"), "w") as f:
            f.write("x")

    arch._prune_pre_update_snapshots(keep=5)

    remaining = sorted(n for n in os.listdir(local) if n.startswith("pre_update_"))
    assert remaining == names[-5:], "應只保留時間戳最新的 5 份"


def test_pre_update_keep_zero_is_noop_not_delete_everything(arch, tmp_path):
    """keep<=0 的安全行為是「什麼都不做」，不是「全部刪掉」——設定值被寫成 0
    或空字串時，不該一次刪光所有部署退路。"""
    local = str(tmp_path / "db_backups2")
    os.makedirs(local)
    arch._LOCAL_DB_BACKUP = local
    os.makedirs(os.path.join(local, "pre_update_20260914_120000"))

    arch._prune_pre_update_snapshots(keep=0)

    assert os.path.isdir(os.path.join(local, "pre_update_20260914_120000"))


def test_prune_local_keeps_pre_update_out_of_date_based_rule(arch, tmp_path):
    """同一支 _prune_local_db_backups() 裡兩種規則不能互相干擾：日期資料夾照
    天數刪、pre_update_* 照份數刪，且 pre_update_* 不會因為「名字 parse 不出
    日期」就被日期那段誤刪。"""
    local = str(tmp_path / "db_backups3")
    os.makedirs(local)
    arch._LOCAL_DB_BACKUP = local

    old_day = (date.today() - timedelta(days=90)).isoformat()
    new_day = date.today().isoformat()
    for n in (old_day, new_day, "pre_update_20260101_000000", "pre_update_20260914_000000"):
        os.makedirs(os.path.join(local, n))

    arch._prune_local_db_backups(keep_days=30, pre_update_keep=1)

    assert not os.path.exists(os.path.join(local, old_day))
    assert os.path.isdir(os.path.join(local, new_day))
    assert not os.path.exists(os.path.join(local, "pre_update_20260101_000000"))
    assert os.path.isdir(os.path.join(local, "pre_update_20260914_000000"))
