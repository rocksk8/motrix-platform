"""§12 BK2／BK3／BK5／BK8 · 備份保留：看得見、設得動、缺了會重試。

使用者 2026-09-22：
> 「備份保留天數目前系統**只有顯示天**，**月的部分會保留多久**，
>   **長期哪些會刪哪些不會刪**」

---

# 🔑 三個問題，而它們的成因各自不同

```
「只有顯示天」        BK2  畫面只渲染四個欄位，另外兩個不在上面
「月的會保留多久」     BK1  答案是永久（keep_days = 0），而使用者問得到才叫有答案
「哪些會刪哪些不會」   BK8  畫面上要有一句話答完
```
📌 **判準（BK8）：使用者不應該需要問這個問題。**

---

# ☠️ 而查下去還有兩個他沒問、但更嚴重的

## BK3 · 那兩個欄位**實際上是設不動的**

```python
routers/system.py:1368  value = body.model_dump()        ← 整包覆蓋
routers/system.py:1356  cloud_monthly_keep_days: int = 0 ← 有預設值
```
⇒ 用 `curl` 把它設成 1825 ⇒ 下一個人在設定頁按一次「儲存」
（那個頁面只送四個欄位）⇒ **静静變回 0**。
🔑 **今天無害，因為 0 剛好就是預設值** —— 而那正是它沒有被發現的原因。
⚠️ 〈降級之後它還是會動〉：存檔成功、沒有錯誤、而一個設定被重設了。

## BK5 · `.db` 複製失敗時，`.done` **照樣會寫**

```python
archive.py:1229  summary["db_snapshot"] = False     ← .db 失敗走這裡
archive.py:1240  failed = [k for k, v in summary.items() if v == "error"]
```
☠️ **`False` 不等於 `"error"`** ⇒ 它**不在 `failed` 裡** ⇒ 底下照樣 `_cloud_write_marker`。
⇒ 📌 那個月的永久備份**永遠殘缺**，而 `.done` 在那裡 ⇒ **沒有人會再試一次。**

🔑 而這件事的代價是實的：資料庫 82 張表，JSON 只涵蓋 45 張
⇒ **37 張只靠那份整庫 `.db` 活著**，其中包含選型資料庫七類的 28 張表。

## ⚠️ 觀測點要挑 `.done` 在不在，不是挑告警有沒有寫

程式碼**已經有**告警（`_write_backup_alert(... level="ERROR")`）——
☠️ **告警寫了而 `.done` 也寫了**，於是那份殘缺的備份被標成完成。
🔑 〈假綠燈〉：**「有沒有人被通知」與「這件事會不會再試一次」是兩個問題。**

---

# 📌 `BK9` 不在這個檔，而那是刻意的

`BK9` 要的雙向控制**已經存在**（`test_backup_retention_policy_2026_09_14.py`），
而且觀測點就是 A 指定的那個（目錄還在不在）：
```
keep_days = 0   ⇒ 10 年前的月備份也不動
keep_days = 365 ⇒ 400 天前的被清、當月的留著
```
⇒ 我只把編號掛到那兩題上，**沒有再造一份**。
⚠️ 再造一份的代價不是浪費，是**下一個人會以為有兩個不同的條件**，
而改壞其中一個的時候，另一個還是綠的。
"""
import json
import os
from datetime import date
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "pages" / "company-profile-settings.html")

#: 兩個「使用者看不到」的欄位。BK2 要它們出現在畫面上。
HIDDEN_FIELDS = ("cloud_monthly_keep_days", "local_pre_update_keep")


@pytest.fixture
def arch(isolated_archive):
    import archive
    return archive


def _superadmin(client, make_user, name, ip):
    username, password = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": ip})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ══════════════════════════════════════════════════════════════════════
# BK2 · 兩個欄位要出現在畫面上
# ══════════════════════════════════════════════════════════════════════

def test_bk2_the_settings_page_shows_all_six_retention_fields():
    """🔴 BK2：設定頁只渲染四個欄位，而政策有六個。

    ☠️ 而少的那兩個**恰好是使用者問的那兩件事**：
    ```
    cloud_monthly_keep_days  「月的部分會保留多久」
    local_pre_update_keep    「幾份」—— 它是份數不是天數
    ```
    🔑 使用者說「只有顯示天」是**完全正確的觀察**，
    📌 而他沒辦法知道的是：**那兩個欄位不只是沒顯示，它們還設不動**（見 BK3）。
    """
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    missing = [f for f in HIDDEN_FIELDS if f not in text]
    assert not missing, (
        "設定頁上看不到這些保留政策欄位：" + "、".join(missing) + "\n"
        "⇒ 使用者問「月的部分會保留多久」，而畫面上沒有地方回答他。"
    )


def test_bk8_the_page_says_which_layers_are_never_deleted():
    """🔴 BK8：畫面要講得出來「**長期哪些會刪、哪些不會刪**」。

    📌 判準：**使用者不應該需要問這個問題。**
    ```
    永久保留：月備份（含整庫）・上傳檔案・PDF・即時備份
    會自動清：每日 N 天・週 N 天・本機快照 N 天・稽核紀錄 N 天
    ```
    ⚠️ 我不釘文案（那是設計）—— 只釘「**永久保留的那四層都被提到了**」，
    🔑 因為漏掉其中一層，使用者就還是要問一次。
    """
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    missing = [w for w in ("永久", "上傳檔案", "PDF", "即時備份")
               if w not in text]
    assert not missing, (
        "設定頁沒有說明永久保留的是哪幾層，少了：" + "、".join(missing) + "\n"
        "⇒ 使用者問「長期哪些會刪哪些不會刪」，而畫面上沒有一句話答得完。"
    )


# ══════════════════════════════════════════════════════════════════════
# BK3 · 只送四個欄位，不可以把另外兩個重設掉
# ══════════════════════════════════════════════════════════════════════

def test_bk3_a_partial_patch_does_not_reset_the_other_fields(client, make_user):
    """🔴🔴 BK3：舊 client 只送四個欄位 ⇒ **另外兩個要保持原值**。

    ## ☠️ 現在它會被静静重設

    ```
    用 curl 把 cloud_monthly_keep_days 設成 1825
    → 下一個人在設定頁按一次「儲存」（那頁只送四個欄位）
    → 静静變回 0
    ```
    🔑 **今天無害，因為 0 剛好就是預設值** —— 而那正是它沒被發現的原因。
    ⚠️ 〈降級之後它還是會動〉：**存檔成功、沒有錯誤、而一個設定被重設了。**

    ## 📌 修法要兩個都做（規格裡寫的）

    ① 畫面補上兩個欄位（BK2）—— **有欄位才設得到**
    ② PATCH 改成**合併**而不是覆蓋 —— **擋得住下一個只送四個欄位的 client**
    🔑 只做①的話，下一個用舊腳本的人照樣把它打回去；
    只做②的話，使用者還是看不到也改不了。
    """
    auth = _superadmin(client, make_user, "bk3_admin", "203.0.113.243")

    r = client.get("/api/settings/backup-retention", headers=auth)
    assert r.status_code == 200, r.text
    base = dict(r.json())

    full = dict(base)
    full["cloud_monthly_keep_days"] = 1825
    full["local_pre_update_keep"] = 9
    r = client.patch("/api/settings/backup-retention", headers=auth, json=full)
    assert r.status_code == 200, r.text

    legacy = {k: base[k] for k in ("local_db_keep_days", "cloud_daily_keep_days",
                                   "cloud_weekly_keep_days", "audit_log_keep_days")}
    r = client.patch("/api/settings/backup-retention", headers=auth, json=legacy)
    assert r.status_code == 200, r.text

    r = client.get("/api/settings/backup-retention", headers=auth)
    got = r.json()
    assert got["cloud_monthly_keep_days"] == 1825, (
        f"只送四個欄位之後，`cloud_monthly_keep_days` 從 1825 變成 "
        f"{got['cloud_monthly_keep_days']} —— 一個沒有人送出的值被改掉了。")
    assert got["local_pre_update_keep"] == 9, (
        f"`local_pre_update_keep` 從 9 變成 {got['local_pre_update_keep']}")


def test_bk3_a_full_patch_still_changes_everything(client, make_user):
    """🔴 BK3 正對照：**送齊六個欄位時，六個都要改得動。**

    ☠️ 少了這一題，一個「那兩個欄位一律忽略」的實作會讓上一題全綠 ——
    而那等於把它們做成唯讀，**使用者還是設不動**。
    🔑 〈判準的寬窄都會騙人〉：「永遠不覆寫」是「不要被誤覆寫」的超集。
    """
    auth = _superadmin(client, make_user, "bk3_full", "203.0.113.244")
    r = client.get("/api/settings/backup-retention", headers=auth)
    value = dict(r.json())
    value["cloud_monthly_keep_days"] = 730
    value["local_pre_update_keep"] = 3
    r = client.patch("/api/settings/backup-retention", headers=auth, json=value)
    assert r.status_code == 200, r.text

    got = client.get("/api/settings/backup-retention", headers=auth).json()
    assert got["cloud_monthly_keep_days"] == 730, "送了值卻沒有生效 —— 欄位變成唯讀"
    assert got["local_pre_update_keep"] == 3


# ══════════════════════════════════════════════════════════════════════
# BK5 · 整庫 .db 複製失敗 ⇒ 不可以寫 .done
# ══════════════════════════════════════════════════════════════════════

def test_bk5_a_failed_db_copy_must_not_mark_the_month_done(arch, monkeypatch):
    """🔴🔴 BK5：整庫 `.db` 複製失敗時，`.done` **不可以寫**。

    ## ☠️ 現在它會寫，而成因是一個型別比對

    ```python
    archive.py:1229  summary["db_snapshot"] = False
    archive.py:1240  failed = [k for k, v in summary.items() if v == "error"]
    ```
    **`False` 不等於 `"error"`** ⇒ 它不在 `failed` 裡 ⇒ 底下照樣寫 marker。
    ⇒ 📌 那個月的永久備份**永遠殘缺**，而 `.done` 在那裡 ⇒ **沒有人會再試。**

    ## 🔑 觀測點是 `.done` 在不在，不是告警有沒有寫

    程式碼**已經有**告警（`level="ERROR"`）——
    ☠️ **告警寫了而 `.done` 也寫了**，於是那份殘缺的備份被標成完成。
    📌 〈假綠燈〉：**「有沒有人被通知」與「這件事會不會再試一次」是兩個問題**，
    而只驗前者的話，這個缺陷看起來已經被處理過了。

    ## ⚠️ 代價是實的

    資料庫 **82 張表**，JSON 只涵蓋 **45 張** ⇒ **37 張只靠那份整庫 `.db`**，
    其中包含選型資料庫七類的 28 張表 —— 而那是拆售候選裡最乾淨的一個。
    """
    month = date.today().strftime("%Y-%m")
    base = arch._archive_base()
    marker = os.path.join(arch._monthly_dir(), month, ".done")

    # JSON 那一層全部成功 —— 這一題要隔離的是 `.db` 那一步。
    monkeypatch.setattr(
        arch, "_export_table_json_set",
        lambda conn, d, s3, now: {"quotations": 3, "customers": 5})

    # 當日本機快照存在（`_daily_backup()` 一開頭就會做），但複製會失敗。
    snap_dir = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat())
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, "motrix_erp.db"), "wb") as f:
        f.write(b"fake-sqlite")

    def _boom(*a, **kw):
        raise OSError("雲端磁碟在複製整庫檔案時斷線")

    monkeypatch.setattr(arch, "_cloud_copy_file", _boom)

    arch._monthly_backup()

    assert not os.path.exists(marker), (
        f"整庫 `.db` 複製失敗了，而 `{month}` 仍然被標記成完成（{marker}）。\n"
        "☠️ 那個月的永久備份永遠殘缺，而 `.done` 在那裡 ⇒ 明天不會再試一次。\n"
        "🔑 判準要跟 JSON 失敗同等：`db_snapshot is False` 也算失敗。"
    )
    assert base      # 前提：這一題跑在隔離的存檔根目錄上


def test_bk5_a_complete_month_is_still_marked_done(arch, monkeypatch):
    """🔴 BK5 正對照：**一切正常時 `.done` 仍然要寫。**

    ☠️ 少了這一題，「永遠不寫 `.done`」會讓上一題全綠 ——
    而那個實作會讓月備份**每天重跑一次**（整庫 8.3 MB ＋ 45 張表），
    🔑 而症狀是「雲端硬碟一直在傳東西」，**沒有人會把它連回這次修改**。
    """
    month = date.today().strftime("%Y-%m")
    marker = os.path.join(arch._monthly_dir(), month, ".done")

    monkeypatch.setattr(
        arch, "_export_table_json_set",
        lambda conn, d, s3, now: {"quotations": 3, "customers": 5})
    snap_dir = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat())
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, "motrix_erp.db"), "wb") as f:
        f.write(b"fake-sqlite")

    arch._monthly_backup()

    assert os.path.exists(marker), (
        f"一切正常而 `{month}` 沒有被標記完成 —— 月備份會每天重跑一次。")


def test_bk5_the_summary_records_that_the_db_is_missing(arch, monkeypatch):
    """📏 量尺：`彙總.json` 裡要看得出 `db_snapshot` 是 False。

    ⚠️ 這一題不是 BK5 的本體，它守的是**上面那題的前提** ——
    ☠️ 如果 `_monthly_backup()` 哪天不再記 `db_snapshot`，
    BK5 那題會因為「根本沒有失敗」而變綠，**而它證明不了任何事**。
    """
    month = date.today().strftime("%Y-%m")
    monkeypatch.setattr(
        arch, "_export_table_json_set",
        lambda conn, d, s3, now: {"quotations": 3})
    snap_dir = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat())
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, "motrix_erp.db"), "wb") as f:
        f.write(b"fake-sqlite")
    monkeypatch.setattr(arch, "_cloud_copy_file",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("斷線")))

    arch._monthly_backup()

    summary_path = os.path.join(arch._monthly_dir(), month, "彙總.json")
    assert os.path.isfile(summary_path), (
        f"連彙總都沒有寫（{summary_path}）—— BK5 那題的前提不成立")
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)
    assert summary.get("db_snapshot") is False, (
        f"`彙總.json` 沒有記下整庫複製失敗：{summary}\n"
        "⇒ 事後沒有任何地方看得出那個月缺了什麼。"
    )


# ══════════════════════════════════════════════════════════════════════
# BK1 / BK6 · 兩條「不刪」的政策，各自要有人守
# ══════════════════════════════════════════════════════════════════════

def test_bk1_the_default_monthly_policy_is_keep_forever(arch):
    """BK1：預設 `cloud_monthly_keep_days = 0` ＝ **永久不刪**（使用者 2026-09-14 裁示）。

    ⭐ 這一條就是使用者問題的答案：**月備份不會被刪。**

    📌 它與 `test_bk9_*` 的分工：
    ```
    BK1  預設值**是** 0          ← 這一題（政策本身）
    BK9  0 的時候**真的不刪**     ← 那兩題（政策有沒有被執行）
    ```
    🔑 兩者不可互相取代：**預設值對而清理程式沒跑到**，與
    **清理程式正確而預設值被改掉**，在畫面上完全一樣。
    """
    ret = arch._backup_retention()
    assert ret["cloud_monthly_keep_days"] == 0, (
        f"月備份的預設保留天數變成 {ret['cloud_monthly_keep_days']} 了 —— "
        "使用者裁示的是永久保留（0）。")


def test_bk6_the_three_permanent_mirrors_are_never_pruned(arch):
    """BK6：**即時備份／上傳檔案鏡像／PDF存檔鏡像**永久不清。

    這三層放的是原始憑據（報價單／客戶／供應商的即時快照、照片、簽回單、
    各類單據 PDF），使用者明訂長久保留。

    ## 📌 為什麼要有這一題，而既有那題已經蓋了兩層

    `test_prune_never_touches_upload_and_pdf_mirrors` 蓋的是**上傳與 PDF**，
    ⚠️ **而「即時備份」那一層沒有人守** —— 它跟另外兩層在同一個根目錄下，
    ☠️ 而未來任何人在 `_prune_cloud_backups()` 裡多加一個目錄都可能誤傷它。
    🔑 判準用「連名字看起來像超舊日期的子資料夾都不准消失」——
    **那正是誤傷會長的樣子。**
    """
    base = arch._archive_base()
    ancient = (date.today().replace(year=date.today().year - 8)).isoformat()
    for parent in ("即時備份", "上傳檔案鏡像", "PDF存檔鏡像"):
        d = os.path.join(base, parent, ancient)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "keep.json"), "w", encoding="utf-8") as f:
            f.write("{}")

    arch._prune_cloud_backups(daily_keep_days=1, weekly_keep_days=1,
                              monthly_keep_days=1)

    gone = [p for p in ("即時備份", "上傳檔案鏡像", "PDF存檔鏡像")
            if not os.path.isdir(os.path.join(base, p, ancient))]
    assert not gone, (
        "這幾層永久保留的原始憑據被清掉了：" + "、".join(gone) + "\n"
        "☠️ 它們是照片、簽回單與單據 PDF —— 刪掉之後沒有任何地方補得回來。")


# ══════════════════════════════════════════════════════════════════════
# BK10 / BK12 / BK13 · 備份要驗內容，不只驗存在
# ══════════════════════════════════════════════════════════════════════
#
# ☠️ D 2026-09-22 在雲端硬碟上實測到的：
# ```
# 2026-08-29   6,545,408 bytes   quotations 29  customers 14  users 12   ✅
# 2026-08-30     765,952 bytes   quotations  0  customers  0  users  2   ☠️
# 2026-08-31     765,952 bytes   quotations  0  customers  0  users  2   ☠️
# 2026-09-03     782,336 bytes   quotations  0  customers  0  users  2   ☠️
# ```
# 🔑 **三份都 `PRAGMA quick_check = ok`，表數也對 —— 只是裡面沒有資料。**
# ☠️ 〈降級之後它還是會動〉的標本：**壞掉會被報修，降級不會。**
#
# ⚠️ 而 `_snapshot_sqlite()`（`archive.py:575`）寫完就寫 `.done`：
# **沒有任何人看過那份檔裡面有什麼。**


def _rowcount(path, table):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def test_bk10_a_snapshot_that_lost_its_rows_is_not_marked_done(arch, monkeypatch):
    """🔴🔴 BK10：快照完成後要對**快照檔本身**跑下限檢查，不過就不算成功。

    ## ☠️ 觀測點必須是「快照檔」，不是「來源庫」

    對來源庫做檢查會永遠通過 —— **來源庫從來沒有壞過**，
    🔑 壞的是那一刻被複製出來的東西（另一個實例的空庫）。
    📌 〈假綠燈〉：**斷言驗到自己設的值**的變體 —— 驗來源等於驗一個必然成立的前提。

    ## 📌 這一題怎麼造出「那三天」

    把 `DB_PATH` 指到一個**結構正確而資料是空的**庫
    （`PRAGMA quick_check` 會回 ok，表數也對）——
    ⇒ 和 2026-08-30 那份在**每一個既有檢查上都一模一樣**。
    """
    import sqlite3

    import db

    empty = os.path.join(arch._LOCAL_DB_BACKUP, "fake_source.db")
    os.makedirs(arch._LOCAL_DB_BACKUP, exist_ok=True)
    conn = sqlite3.connect(empty)
    conn.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT)")
    conn.execute("CREATE TABLE customers  (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE users      (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (username) VALUES ('demo'), ('jeff')")
    conn.commit()
    conn.close()

    assert _rowcount(empty, "quotations") == 0, "前提：這份假來源庫要是空的"
    monkeypatch.setattr(arch, "DB_PATH", empty)
    monkeypatch.setattr(db, "DB_PATH", empty, raising=False)

    arch._snapshot_sqlite(also_to_cloud=False)

    marker = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat(), ".done")
    assert not os.path.exists(marker), (
        "快照的內容是空的（quotations 0／customers 0／users 只有 demo 與 jeff），"
        f"而它仍然被標記成完成（{marker}）。\n"
        "☠️ 那正是 2026-08-30／08-31／09-03 三天的樣子 —— "
        "`PRAGMA quick_check = ok`、表數也對、只是裡面沒有資料。\n"
        "🔑 下限檢查要跑在**快照檔**上，不是來源庫上。"
    )


def test_bk10_a_healthy_snapshot_is_still_marked_done(arch):
    """🔴 BK10 正對照：**正常的快照仍然要被標記完成。**

    ☠️ 少了這一題，「一律不寫 `.done`」會讓上一題全綠 ——
    而那個實作會讓每日備份**每次排程都重做一次整庫複製**，
    🔑 而症狀是「雲端硬碟一直在傳東西」，沒有人會把它連回這次修改。
    """
    arch._snapshot_sqlite(also_to_cloud=False)
    marker = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat(), ".done")
    assert os.path.exists(marker), (
        "正常的資料庫快照沒有被標記完成 —— 每日備份會每次重做一次整庫複製。")


def test_bk13_the_alert_can_say_the_backup_is_empty(arch, monkeypatch):
    """🔴 BK13：告警要講得出「**有備份，但它是空的**」。

    ☠️ 目前 `_write_backup_alert()` 只在**例外**時觸發 ——
    **而那三天沒有任何例外。** 檔案寫出來了、大小合理、結構正確。
    🔑 ⇒ 「沒有告警」在今天的意思是「**沒有人丟例外**」，
    **不是「備份是好的」** —— 而畫面上這兩件事長得一樣。
    """
    import sqlite3

    alerts = []
    monkeypatch.setattr(arch, "_write_backup_alert",
                        lambda msg, level="INFO": alerts.append((level, msg)))

    empty = os.path.join(arch._LOCAL_DB_BACKUP, "fake_empty.db")
    os.makedirs(arch._LOCAL_DB_BACKUP, exist_ok=True)
    conn = sqlite3.connect(empty)
    conn.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(arch, "DB_PATH", empty)

    arch._snapshot_sqlite(also_to_cloud=False)

    assert alerts, (
        "快照出來是一份空的資料庫，而一則告警都沒有發。\n"
        "☠️ 那三天就是這樣過去的：沒有例外 ⇒ 沒有告警 ⇒ 沒有人知道。")
    text = " ".join(m for _lvl, m in alerts)
    assert any(w in text for w in ("空", "筆數", "資料")), (
        f"發了告警，而它沒有講出「備份是空的」：{alerts}\n"
        "🔑 一則講不出問題是什麼的告警，讀的人只會把它當雜訊。")


def test_bk12_the_monthly_backup_does_not_copy_an_empty_snapshot(arch, monkeypatch):
    """🔴🔴 BK12：月備份的來源就是那份每日快照 ⇒ **快照是空的，永久備份就永久是空的。**

    ```python
    archive.py:1224  today_snapshot = db_backups/<today>/motrix_erp.db
    archive.py:1227  _cloud_copy_file(today_snapshot, 月備份/.../motrix_erp.db)
    ```
    ☠️ 而 `.done` 照寫 ⇒ **那個月不會再試一次。**

    ✅ 實查：`月備份/2026-09/motrix_erp.db` 這次是正常的
    （quotations 35／customers 18／users 12／audit_log 2965）——
    📌 **這一次是運氣，不是設計**：月備份只跑一次，而它剛好沒有落在那三天。
    ⚠️ 08-30／08-31／09-03 之中任何一天若是「當月第一次跑月備份」的那天，
    **2026-08 的永久備份就會是一份空庫，而它會被標成完成。**
    """
    import sqlite3

    month = date.today().strftime("%Y-%m")
    marker = os.path.join(arch._monthly_dir(), month, ".done")

    monkeypatch.setattr(
        arch, "_export_table_json_set",
        lambda conn, d, s3, now: {"quotations": 0, "customers": 0})

    snap_dir = os.path.join(arch._LOCAL_DB_BACKUP, date.today().isoformat())
    os.makedirs(snap_dir, exist_ok=True)
    snap = os.path.join(snap_dir, "motrix_erp.db")
    conn = sqlite3.connect(snap)
    conn.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE customers  (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    arch._monthly_backup()

    assert not os.path.exists(marker), (
        f"當日快照是一份空庫，而 `{month}` 的永久備份仍然被標記成完成（{marker}）。\n"
        "☠️ 月備份一個月只跑一次 ⇒ 那個月的永久備份永遠是空的，而沒有人會再試。\n"
        "🔑 判準：**複製之前先看那份檔裡面有沒有東西**（BK10 的同一道檢查）。"
    )
