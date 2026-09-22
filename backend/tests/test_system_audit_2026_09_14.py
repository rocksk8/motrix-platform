"""全系統一致性稽核：模組串接、備份涵蓋、安全守門、組織邏輯（2026-09-14）。

**這支跟其他測試不一樣的地方**：它不驗證任何一個功能「做得對不對」，而是驗證
**跨層的對應關係有沒有漂掉**。這類缺陷的共同特徵是「每一邊單獨看都正確、
合起來才是錯的」，所以逐功能的測試永遠照不到：

  · 後端新增一個模組權限，但使用者管理頁沒有那個勾選項 → 那個權限永遠給不出去
  · 新增一張資料表，但沒人記得加進每日 JSON 備份 → 平常沒事，要用最後手段
    還原時才發現那張表從來沒被匯出過
  · 新增一支端點忘了呼叫守門函式 → 測試全綠，因為沒有人針對「它應該要擋」寫題

專案已經有一批 `tools/check_*.py`（端點沒有前端入口、Alpine 雙 init、正式機漂移、
高權限帳號稽查），但那些是**手動執行**的工具。這支刻意做成 pytest，跟著每次
測試跑，漂掉的當下就會紅。

---

**白名單的意義**：底下幾份「已知且刻意如此」的清單不是為了讓測試變綠，而是為了
**讓下一個新增的項目變紅**。清單裡每一筆都要有理由；看到紅燈時該做的是判斷
「這個新項目應該進清單，還是應該修程式」，不是無腦加進清單。

**寫這支測試的過程本身就證明了它的必要**：初稿用寫死的守門函式名稱掃描，
誤報了 5 支 T100 財務端點（它們有自己的 `_require_t100_admin`）；接著又誤判
`financial_view` 與 `project_approve_eng` 沒有後端檢查（前者有專屬的
`_require_financial_view()`、後者寫成 `"..." in modules` 的直接成員測試）。
三次誤判都是「人掃一遍」會犯的錯，也是為什麼這件事該交給會被執行的測試。
"""
import json
import pathlib
import re

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"


# ══════════════════════════════════════════════════════════════════════
# A. 備份涵蓋度
# ══════════════════════════════════════════════════════════════════════

# archive.py 每日 JSON 匯出的那幾張表。
# **2026-09-14 改成直接 import 呼叫**：原本是用正規表示式解析 _daily_backup()
# 裡的 local dict 原始碼（為了避免「複製一份清單」那種必然漂掉的寫法），
# 但那個 dict 已經抽成模組層級的 archive._daily_backup_tables()，
# 直接呼叫比解析更不可能歪掉——解析式只要人家改個縮排就會靜默失準。
def _json_backup_queries() -> dict:
    import archive
    return archive._daily_backup_tables()


def _json_backup_tables() -> set:
    return {t for sql in _json_backup_queries().values()
            for t in re.findall(r"FROM\s+(\w+)", sql)}


#: `BG1丙`（A 2026-09-23）：**`set` 改 `dict`，理由變成資料。**
#:
#: ☠️ 原本理由寫在**群組註解**裡 ⇒ 「每一張排除的表都要有理由」這件事
#:    **沒有任何東西在守** —— 而下面那道題的 docstring 宣稱它守得住。
#: 🔑 〈散文對工具是隱形的〉：註解裡的理由，守門讀不到。
#: ⚠️ 語意**照抄原註解**，不重寫（A 明著交代）。
SELECT = "選型資料庫七類：內容由 sync_*.py 腳本產生，git 裡有來源"
ENVG = "環境指引：內容由腳本產生，git 裡有來源"

# 刻意不進「每日 JSON 匯出」的表，以及理由。
#
# **2026-09-14 傍晚更新**：這份清單原本有 68 筆（JSON 只涵蓋 8/76 張表），
# 現在剩 36 筆——所有業務資料表都已補進 archive.py 的每日匯出，
# §8.3 的最後手段（JSON 重建）現在真的重建得出一套可用的系統。
# 留在這裡的兩類都是「重建它沒有意義」，不是「忘了做決定」。
_NOT_IN_JSON_BACKUP = {
    # ── 選型資料庫（七類導覽）：內容由 sync_*.py 腳本產生，git 裡有來源 ──
    "switch_categories": SELECT, "switch_products": SELECT,
    "switch_scenarios": SELECT, "switch_fit": SELECT,
    "monitor_categories": SELECT, "monitor_products": SELECT,
    "monitor_scenarios": SELECT, "monitor_fit": SELECT,
    "access_categories": SELECT, "access_products": SELECT,
    "access_scenarios": SELECT, "access_fit": SELECT,
    "gateway_categories": SELECT, "gateway_products": SELECT,
    "gateway_scenarios": SELECT, "gateway_fit": SELECT,
    "automation_categories": SELECT, "automation_products": SELECT,
    "automation_scenarios": SELECT, "automation_fit": SELECT,
    "netarch_families": SELECT, "netarch_generations": SELECT,
    "netarch_products": SELECT,
    "env_guide_environments": ENVG, "env_guide_links": ENVG,
    "env_guide_recommendations": ENVG,
    # ── 執行期狀態／流水號／軌跡：重建即可，或量太大而價值太低 ──
    "sessions": "登入態與鎖，還原後本來就該是空的",
    "login_rate_limit": "登入態與鎖，還原後本來就該是空的",
    "edit_presence": "登入態與鎖，還原後本來就該是空的",
    "schema_version": "由 migration 自己寫，抄舊值反而會讓 migration 不跑",
    "quote_seq": "流水號，整庫還原時跟著單據一起回來；"
                 "走到 JSON 重建那一層時要人工對一次最後號碼（單據 JSON 裡看得到）",
    "payslip_seq": "流水號，同 quote_seq",
    "user_request_log": "操作軌跡，筆數最大、對「把系統救回來」沒有幫助；"
                        "整庫複製那層仍然有",
    "user_activity_daily": "時數統計，同 user_request_log",
    "user_list_prefs": "每個人的排序偏好，重設一次就好",
    "tender_fetch_log":
        "標案雷達的抓取軌跡。它回答的是「雷達瞎了沒」，而還原之後要看的是"
        "「現在會不會動」，下一次抓取就會重新長出來。⚠️ 同一批的 tender_watches／"
        "tenders／tender_hits **都要備份** —— 不要看到 tender_ 開頭就跟著排除："
        "tender_watches 是使用者自己建的搜尋條件，失去它的症狀是"
        "「功能還在，只是不再找到東西」，而且沒有人會發現它不見了",
    # ── 2026-09-22 · geocode_cache：**排除的理由是隱私，不是「它只是快取」** ──
    "geocode_cache":
        "🔴 **隱私**，不是「它只是快取」：這張表裡有 contractors（外包名冊，"
        "自然人）住家地址解析出來的經緯度。那張表有 contractor_list 權限保護，"
        "**而每日 JSON 備份會上傳到雲端硬碟** ⇒ 備份它＝把「某人住家的經緯度」"
        "複製到雲端，而那份資料的權限保護在備份裡不存在",
}



def _all_tables(client) -> set:
    import db
    conn = db.get_db()
    try:
        return {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    finally:
        conn.close()


def test_every_table_is_either_backed_up_or_explicitly_excluded(client):
    """新增資料表時，必須明確決定它要不要進每日 JSON 匯出。

    這一題會紅，代表有人加了新表卻沒有做這個決定——不是叫你把它加進排除清單，
    是叫你想一下：這張表的資料如果要靠 JSON 重建，重建得出來嗎？
    """
    tables = _all_tables(client)
    backed = _json_backup_tables()
    undecided = tables - backed - set(_NOT_IN_JSON_BACKUP)
    assert not undecided, (
        "這些資料表既不在每日 JSON 備份裡，也不在本測試的排除清單裡：\n  "
        + "\n  ".join(sorted(undecided))
        + "\n\n請在 archive.py::_daily_backup() 的 tables 加上它，"
          "或在本檔 _NOT_IN_JSON_BACKUP 註明不需要的理由。"
    )


def test_backup_list_has_no_stale_entries(client):
    """反向控制：備份清單裡不該有已經不存在的表。

    少了這一題，上面那題可以靠「把整個資料庫都寫進排除清單」變綠。
    """
    tables = _all_tables(client)
    backed = _json_backup_tables()
    stale = backed - tables
    assert not stale, (
        f"archive.py 每日備份指名了不存在的資料表：{sorted(stale)}"
        "——每天的備份都會為它記一筆 error。")


def test_every_backup_query_actually_runs(client):
    """每一條匯出查詢都必須真的跑得起來。

    **這題是實際踩到才補的**：`stock_batches` 沒有 `id` 欄位，
    `... ORDER BY id` 寫下去語法完全正確、表也存在，前面兩題都是綠的，
    但真正執行時會 OperationalError。而 `_daily_backup()` 對每張表都包了
    try/except——失敗只會在 log 留一行、在彙總.json 記一個 "error"，
    **備份照樣顯示完成**。等到要還原才發現那張表每天都是空的。

    所以這題不比對字串，直接把每條 SQL 拿去執行。
    """
    import db
    queries = _json_backup_queries()
    conn = db.get_db()
    failed = []
    try:
        for fname, sql in queries.items():
            try:
                conn.execute(sql).fetchall()
            except Exception as e:
                failed.append(f"{fname}: {e}")
    finally:
        conn.close()
    assert not failed, "這些每日備份查詢跑不起來（每天都會靜默記一筆 error）：\n  " + "\n  ".join(failed)


def test_every_backup_export_is_json_serializable(client):
    """每一條匯出查詢的結果，都必須真的序列化得出 JSON。

    **這題是 2026-09-16 實際踩到才補的**，踩的正是上一題守不住的那個縫：
    `webauthn_credentials` 的 credential_id / public_key 是 BLOB，取出來是
    Python bytes。SQL 跑得起來（上一題全綠）、表也存在（前面幾題也全綠），
    但 `_cloud_write_json()` 走到 `json.dumps()` 就 TypeError——於是「通行金鑰」
    每天靜默記一筆 "error"、其餘 40 張照常完成，整件事只在彙總.json 上留一個字。

    上一題的觀測點停在「SQL 執行成功」，離真正的失敗點還差一步。這題把觀測點
    移到下游，照 `_export_table_json_set()` 的實際路徑走完：
    `_strip_inline_images()` → `json.dumps()`。

    ⚠️ 這題只有在表裡剛好有資料時才抓得到（空表沒有 bytes 可以炸），所以它擋不住
    「新增一個 BLOB 欄位」——那是下一題的工作。兩題要一起看。
    """
    import archive
    import db
    conn = db.get_db()
    failed = []
    try:
        for fname, sql in _json_backup_queries().items():
            try:
                rows = [archive._strip_inline_images(dict(r))
                        for r in conn.execute(sql).fetchall()]
                json.dumps({"exported_at": "", "count": len(rows), "data": rows},
                           ensure_ascii=False)
            except Exception as e:
                failed.append(f"{fname}: {type(e).__name__}: {e}")
    finally:
        conn.close()
    assert not failed, ("這些每日備份查詢的結果寫不進 JSON（每天靜默記一筆 error、"
                        "還原時整張表是空的）：\n  " + "\n  ".join(failed))


def test_backup_export_selects_no_blob_columns(client):
    """匯出查詢不得選到任何宣告為 BLOB 的欄位。

    上一題（序列化）依賴表裡剛好有資料——CI 的空庫跑起來是綠的，正式機只要有
    一個人綁了 Passkey 就炸。這題不看資料、只看 schema：把每條查詢實際選到的
    欄位（cursor.description），跟來源表宣告成 BLOB 的欄位對一次。

    BLOB 進不了 JSON，而且幾乎都是憑證素材或二進位內容——真要保留就該靠 §8.3
    前兩層的整庫 .db，不是靠這一層人看得懂的 JSON。
    """
    import db
    conn = db.get_db()
    offenders = []
    try:
        for fname, sql in _json_backup_queries().items():
            blob_cols = set()
            for tbl in re.findall(r"FROM\s+(\w+)", sql):
                for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall():
                    if "BLOB" in (r["type"] or "").upper():
                        blob_cols.add(r["name"])
            if not blob_cols:
                continue
            hit = {d[0] for d in conn.execute(sql).description} & blob_cols
            if hit:
                offenders.append(f"{fname}: {sorted(hit)}")
    finally:
        conn.close()
    assert not offenders, ("這些匯出查詢選到 BLOB 欄位，json.dumps() 會 TypeError——"
                           "請逐欄列出、略過二進位欄位：\n  " + "\n  ".join(offenders))


# ── 2026-09-21 第 3 輪 · STATE §3 條件 8c ───────────────────────────────────
#
# 刻意不進 JSON 備份的欄位。**全部是憑證素材**——從 JSON 還原後本來就要重設密碼、
# 重綁 2FA/Passkey（見上面 test_business_critical_tables_are_in_json_backup 的說明）。
#
# ⚠️ 這份清單就是這道守門的全部價值所在：它把「哪些欄位可以不備份」從
# **散在 SQL 裡的沉默決定**變成**一個要改就會被看見的清單**。
_BACKUP_OMITTED_ON_PURPOSE = {
    "users": {
        "password_hash", "daily_task_pw_hash", "unlock_password_hash",
        "totp_secret", "totp_recovery_codes",
    },
    "webauthn_credentials": {"credential_id", "public_key"},
}


def test_backup_export_covers_every_column(client):
    """每張已備份表的欄位集合，要等於備份查詢實際取出的欄位集合。

    延伸上面 `test_backup_export_selects_no_blob_columns` 的同一個機制
    （`cursor.description` 對 `PRAGMA table_info`），只是把範圍從「BLOB 欄位」
    擴到**整個欄位集合**——A 指定「延伸既有的比對，不要新建一套」。

    **這一輪它會是綠的，價值不在這一輪**：它讓「有人把 `SELECT *` 改成列舉欄位、
    或加了新欄位卻忘了加進列舉」**必須被看見**。漏備份一個欄位不會有任何錯誤訊息，
    只有還原的那一天才會發現——而那天已經太遲了。

    ⚠️ **開發單說「目前全部 `SELECT *`」，實測不是**（2026-09-21 視窗 C）：
    `使用者` 與 `通行金鑰` 兩條查詢本來就是列舉欄位、刻意略過憑證素材。
    所以這題不是「選到的 ＝ 宣告的」，而是
    **「宣告的 － 選到的 ＝ 刻意略過的那幾個」**，一個不多一個不少。
    寫成嚴格相等的話，這題今天就會紅在一個**正確**的行為上。
    """
    import db
    conn = db.get_db()
    offenders = []
    stale = []
    try:
        for fname, sql in _json_backup_queries().items():
            tables = re.findall(r"FROM\s+(\w+)", sql)
            if len(tables) != 1:
                # 多表 JOIN 的查詢對不出「來源表的欄位集合」，跳過但要講出來，
                # 不要讓它靜靜地不被檢查。
                offenders.append(f"{fname}: 不是單表查詢（{tables}），這道守門涵蓋不到")
                continue
            table = tables[0]
            declared = {r["name"] for r in
                        conn.execute(f"PRAGMA table_info({table})").fetchall()}
            selected = {d[0] for d in conn.execute(sql).description}
            allowed = _BACKUP_OMITTED_ON_PURPOSE.get(table, set())

            unexpected = declared - selected - allowed
            if unexpected:
                offenders.append(
                    f"{fname} ({table}): {sorted(unexpected)} 沒有被備份，"
                    "也不在刻意略過清單裡"
                )
            # 清單裡列了、但那個欄位早就不存在 ＝ 守門被悄悄放寬了
            for col in sorted(allowed - declared):
                stale.append(f"{table}.{col}")
    finally:
        conn.close()

    assert not offenders, (
        "這些欄位不會進每日 JSON 備份，而且不是刻意的——還原時那一欄整欄是空的，"
        "且不會有任何錯誤訊息：\n  " + "\n  ".join(offenders) +
        "\n（若確定不該備份，把它加進 _BACKUP_OMITTED_ON_PURPOSE 並寫明理由。）"
    )
    assert not stale, (
        "_BACKUP_OMITTED_ON_PURPOSE 裡這些欄位在表上已經不存在了，"
        "留著會讓守門對同名的新欄位自動放行：\n  " + "\n  ".join(stale)
    )


def test_business_critical_tables_are_in_json_backup(client):
    """§8.3 的最後手段（JSON 重建）必須真的重建得出一套可用的系統。

    **這題原本是 `xfail(strict=True)`**，用來追蹤「JSON 匯出只涵蓋 8/76 張表」
    這個已知落差。2026-09-14 傍晚落差已補（41 張表），XPASS 提醒生效，
    標記照約定拿掉——xfail 是追蹤用的，不是永久豁免。

    `system_settings` 特別要緊：§0 已經記載過「正式機的 webauthn_rp_id /
    webauthn_origin 不在 git 裡，還原舊 db 時這兩個值會整個消失」。

    `users` 在匯出時**刻意略過憑證欄位**（totp_secret／各種 password hash），
    所以從 JSON 還原後所有人都要重設密碼、重綁 2FA/Passkey；
    這一題只管「帳號、角色、模組、部門歸屬救不救得回來」。
    """
    backed = _json_backup_tables()
    critical = {"users", "system_settings", "payslips", "dev_cases", "dev_logs",
                "shipping_notes", "payment_requests", "completion_notes",
                "departments", "divisions", "quotations", "customers",
                "invoice_vouchers", "contractor_payment_vouchers"}
    missing = critical - backed
    assert not missing, f"關鍵業務資料表不在每日 JSON 匯出裡：{sorted(missing)}"


def test_user_export_excludes_credential_columns(client):
    """使用者匯出不可以夾帶憑證欄位。

    totp_secret 與 totp_recovery_codes 是**可以直接拿去產生有效驗證碼的金鑰**，
    寫進人看得懂的 JSON 等於把兩階段驗證抄一份出來放在備份資料夾。
    整庫複製那一層本來就含這些欄位（.db 檔），JSON 這層不需要再抄一份。

    這題守的是「有人為了讓還原更完整，把使用者那行改回 SELECT *」。
    **不比對 SQL 字串、直接執行後看實際欄位**——`SELECT *` 這種寫法裡
    根本不會出現欄位名，比對字串會變成永遠綠的假斷言。
    """
    import db
    sql = _json_backup_queries()["使用者"]
    conn = db.get_db()
    try:
        cols = {d[0] for d in conn.execute(sql).description}
    finally:
        conn.close()
    leaked = cols & {"password_hash", "unlock_password_hash", "daily_task_pw_hash",
                     "totp_secret", "totp_recovery_codes"}
    assert not leaked, (
        f"使用者每日 JSON 匯出夾帶了憑證欄位 {sorted(leaked)}——"
        "備份資料夾會出現可直接使用的認證素材")
    # 正向控制：確定這條查詢真的有撈到東西，不是因為查空的才「沒有洩漏」
    assert "username" in cols and "role" in cols


def _run_daily_backup_with(monkeypatch, tmp_path, tables: dict):
    """把 _daily_backup() 跑在一個完全隔離的環境裡，回傳它對外送出的訊號。

    只擋掉「會寫到磁碟/雲端」與「會清掉別人資料」的部分，
    **控制流程本身完全不動**——這題要驗的就是控制流程。
    """
    import archive
    audits, alerts, cleared = [], [], []

    # _daily_backup() 開頭這兩件事跟 JSON 匯出無關（本機 SQLite 快照、server.log
    # 輪替），但會寫磁碟也會自己發警示，擋掉才不會污染這題的觀測值
    monkeypatch.setattr(archive, "_snapshot_sqlite", lambda **k: None)
    monkeypatch.setattr(archive, "_rotate_server_log_if_large", lambda: None)
    monkeypatch.setattr(archive, "_archive_ok", lambda: True)
    monkeypatch.setattr(archive, "_mirror_uploads", lambda: None)
    monkeypatch.setattr(archive, "_mirror_pdf_archives", lambda: None)
    monkeypatch.setattr(archive, "_daily_dir", lambda: str(tmp_path))
    monkeypatch.setattr(archive, "_cloud_marker_exists", lambda *a, **k: False)
    monkeypatch.setattr(archive, "_cloud_write_json", lambda *a, **k: None)
    monkeypatch.setattr(archive, "_cloud_write_marker", lambda *a, **k: None)
    monkeypatch.setattr(archive, "_prune_audit_log", lambda **k: None)
    monkeypatch.setattr(archive, "_prune_cloud_backups", lambda **k: None)
    # 月備份（永久保留層）有自己的測試檔，這題只驗每日那條控制流程。
    # 不擋的話它會因為上面 `_snapshot_sqlite` 被換成 no-op、找不到當日整庫快照
    # 而發一則 ERROR 警示，污染這題的 `alerts` 觀測值。
    # ⚠️ 2026-09-14：這題在「停用背景排程」之前是綠的——因為 `import main` 時
    # 排程已經先跑過一次真的 _snapshot_sqlite()，檔案剛好存在。**那是靠洩漏的
    # 全域狀態才綠的**，不是這題自己造出來的前提。
    monkeypatch.setattr(archive, "_monthly_backup", lambda: None)
    monkeypatch.setattr(archive, "_daily_backup_tables", lambda: tables)
    monkeypatch.setattr(archive, "_system_audit",
                        lambda action, target, detail=None: audits.append(action))
    monkeypatch.setattr(archive, "_write_backup_alert",
                        lambda reason, level="WARN": alerts.append((level, reason)))
    monkeypatch.setattr(archive, "_clear_backup_alert_if_healthy",
                        lambda: cleared.append(True))

    archive._daily_backup()
    return audits, alerts, cleared


def test_partial_backup_failure_is_not_reported_as_ok(client, monkeypatch, tmp_path):
    """一張表匯出失敗時，不可以還是送出 backup.daily_ok。

    每張表各自包 try/except 是刻意的（一張壞掉不該連累其他 40 張），
    但原本失敗只在 log 留一行、在彙總.json 記一個 "error"，接著照樣寫 .done、
    照樣送 backup.daily_ok——**備份頁面顯示綠燈，那張表卻每天都是空的**，
    要還原才會發現。這是最典型的「備份看起來有在跑」型事故。
    """
    audits, alerts, cleared = _run_daily_backup_with(
        monkeypatch, tmp_path,
        {"好表": "SELECT * FROM users", "壞表": "SELECT * FROM 這張表不存在"})

    assert "backup.daily_ok" not in audits, "有表匯出失敗卻還是報了 daily_ok"
    assert "backup.daily_partial" in audits
    assert alerts, "匯出失敗沒有留下任何警示"
    assert "壞表" in alerts[0][1], "警示內容要指出是哪張表壞了，否則沒辦法處理"
    assert not cleared, "匯出有失敗時不該把既有的備份警示清掉"


def test_clean_backup_still_reports_ok(client, monkeypatch, tmp_path):
    """正向控制：全部成功時仍然要送 backup.daily_ok 並清掉舊警示。

    少了這一題，上面那題可以靠「永遠不送 daily_ok」變綠。
    """
    audits, alerts, cleared = _run_daily_backup_with(
        monkeypatch, tmp_path, {"好表": "SELECT * FROM users"})

    # 2026-09-14 起每日備份成功後會接著跑月備份（永久保留層，
    # archive.py::_monthly_backup()），所以這裡會多一筆 backup.monthly_ok。
    # 用「有沒有 daily_ok」＋「有沒有任何 *_partial」判斷，不再用完全相等比對——
    # 相等比對會讓日後每加一層備份就紅一次，而那些都不是這題要守的東西。
    assert "backup.daily_ok" in audits
    assert not [a for a in audits if a.endswith("_partial")]
    assert not alerts
    assert cleared


# 欄位／設定鍵名長得像祕密的樣子。
_SECRET_NAME = re.compile(r"pass(word)?|secret|token|totp|recovery|api_?key|private|credential", re.I)

# 名字命中但其實不是祕密的，逐筆說明理由。
# 這份清單一樣是「讓下一個新增的變紅」，不是讓測試變綠。
_SECRET_NAME_OK = {
    "must_change_password",   # 布林旗標：要不要強迫改密碼，不是密碼本身
    "totp_enabled",           # 布林旗標：有沒有啟用 2FA，不是金鑰
    "credential_id",          # Passkey 的公開識別碼（規格上就是可公開的）
    "public_key",             # 顧名思義
    "bank_passbook_image",    # 存摺影像欄位，不是密碼；值本身已被
                              # _strip_inline_images() 換成佔位字串，見下方影像那題
}


def test_backup_export_has_no_credential_columns(client):
    """**任何一張表**的匯出都不可以夾帶祕密欄位。

    這是 test_user_export_excludes_credential_columns 的一般化版本：
    不是只盯著 users，而是把 41 條查詢都執行一次、看實際回來的欄位名。
    新加一張含 token/password 欄位的表時會在這裡紅掉。
    """
    import db
    queries = _json_backup_queries()
    conn = db.get_db()
    leaked = []
    try:
        for fname, sql in queries.items():
            cols = [d[0] for d in conn.execute(sql).description]
            for c in cols:
                if _SECRET_NAME.search(c) and c not in _SECRET_NAME_OK:
                    leaked.append(f"{fname}.{c}")
    finally:
        conn.close()
    assert not leaked, (
        "每日 JSON 匯出夾帶了疑似祕密的欄位：" + str(sorted(leaked))
        + "\n備份資料夾（以及雲端鏡像）會出現可直接使用的認證素材。"
          "確定不是祕密的話，請把欄位名加進 _SECRET_NAME_OK 並註明理由。")


def test_settings_export_has_no_live_secrets(client):
    """system_settings 是唯一「祕密藏在值裡面」的表，要往下挖一層。

    smtp_password / client_secret / refresh_token 都住在 value_json 裡，
    欄位名只有 `value_json`，上面那題掃不到。archive.py 用 json_remove()
    把它們挖掉，這題確認真的挖乾淨了，而且**新增的祕密設定也會被抓到**。
    """
    import db, json as _json
    sql = _json_backup_queries()["系統設定"]
    conn = db.get_db()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    assert rows, "系統設定匯出是空的——這題會變成永遠綠的假斷言，先確認查詢是否壞了"

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if _SECRET_NAME.search(k) and k not in _SECRET_NAME_OK:
                    yield f"{path}.{k}"
                yield from walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from walk(v, f"{path}[{i}]")

    leaked = []
    for r in rows:
        key, value_json = r[0], r[1]
        try:
            parsed = _json.loads(value_json) if value_json else None
        except Exception:
            continue
        leaked.extend(walk(parsed, key))

    assert not leaked, (
        "系統設定的每日 JSON 匯出仍帶著祕密：" + str(sorted(leaked))
        + "\n請在 archive.py::_daily_backup_tables() 的「系統設定」那條"
          " json_remove() 加上這個路徑。")


def test_backup_export_has_no_inline_images(client):
    """每日 JSON 匯出裡不可以出現 base64 內嵌影像。

    **這題不是為了省空間**（雖然實測從 5.5 MB 降到 1.4 MB）。
    承攬人員欄位裡放的是**身分證正反面與存摺掃描件**，協力廠商的 data_json、
    承攬付款憑據的 snapshot_json 也各自包了存摺影像。逐表 JSON 每天寫一份、
    鏡像到雲端、保留 30 天——等於把一疊身分證掃描件每天複製到雲端資料夾。
    影像在整庫複製那兩層仍然完整，這裡拿掉的只是「人看得懂那一份」。

    測的是 archive._strip_inline_images() 真的有套上去，而且對三種形態都有效：
    欄位直接存 data:image、JSON 字串欄位裡包一層、JSON 陣列裡再包一層。
    """
    import db, archive
    queries = _json_backup_queries()
    conn = db.get_db()
    offenders = []
    try:
        for fname, sql in queries.items():
            for r in conn.execute(sql).fetchall():
                row = archive._strip_inline_images(dict(r))
                blob = json.dumps(row, ensure_ascii=False)
                if archive._INLINE_IMAGE_PREFIX in blob:
                    offenders.append(fname)
                    break
    finally:
        conn.close()
    assert not offenders, (
        f"這些表的每日 JSON 匯出仍帶著內嵌影像：{sorted(set(offenders))}"
        "——_strip_inline_images() 沒有涵蓋到它的存放形態")


def test_inline_image_stripper_handles_nested_shapes():
    """_strip_inline_images() 的直接單元測試——三種存放形態都要處理到。

    上一題是拿真實資料掃，資料庫裡剛好沒有某種形態時它就照不到；
    這題把三種形態寫死，不依賴資料內容。
    """
    import archive
    img = archive._INLINE_IMAGE_PREFIX + "jpeg;base64,/9j/4AAQSkZJRg"
    out = archive._strip_inline_images({
        "直接放欄位": img,
        "JSON字串欄位": json.dumps({"bankPassbookImage": img, "name": "阿郎"},
                                   ensure_ascii=False),
        "JSON陣列裡": json.dumps({"personnel": [{"bankPassbookImage": img}]},
                                 ensure_ascii=False),
        "不是影像": "data:text/plain;base64,aGVsbG8=",
        "壞掉的JSON": "{不是合法 JSON" + img,
    })
    assert out["直接放欄位"] == archive._IMAGE_PLACEHOLDER
    assert archive._INLINE_IMAGE_PREFIX not in out["JSON字串欄位"]
    assert "阿郎" in out["JSON字串欄位"], "剝影像不可以把同一欄的其他資料也弄掉"
    assert archive._INLINE_IMAGE_PREFIX not in out["JSON陣列裡"]
    # 非影像的 data: URI 不該被動到
    assert out["不是影像"] == "data:text/plain;base64,aGVsbG8="
    # parse 不起來就原樣保留——寧可留著影像，也不要為了清它把資料弄壞
    assert out["壞掉的JSON"].startswith("{不是合法 JSON")


# ══════════════════════════════════════════════════════════════════════
# B. 安全：每一支路由都要有守門
# ══════════════════════════════════════════════════════════════════════

_ROUTE_DEC = re.compile(r'^@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', re.M)
# 偵測**任何**守門呼叫，不寫死名稱——各 router 有自己的守門函式
# （accounting_export.py 的 _require_t100_admin、quotations.py 的
# _require_financial_view / _guard_case…），寫死名單會誤報。
# ⚠️ 反過來說，新的守門函式請沿用 `require_*` / `_require_*` / `_guard_*` 命名。
# 取成 check_admin() 這種名字不會讓測試變紅——會讓那支端點被判定成「沒有守門」
# 而變紅（假警報，你會想把它加進白名單，那才是真正的危險）。
_GUARD_CALL = re.compile(r'\b(_?require_?\w*|_guard_\w*)\s*\(')

# 刻意不需要守門的端點，以及理由。**新增第 17 支就會讓測試紅**，那正是重點。
_PUBLIC_ROUTES = {
    # 登入流程本身：還沒有身分，不可能要求身分
    ("auth.py", "POST", "/api/auth/login/totp"),
    ("auth.py", "GET", "/api/auth/login/qr-info"),
    ("auth.py", "POST", "/api/auth/login/qr-approve"),
    ("auth.py", "GET", "/api/auth/login/qr-status"),
    ("auth.py", "POST", "/api/auth/webauthn/login/begin"),
    ("auth.py", "POST", "/api/auth/webauthn/login/complete"),
    # 登出／查自己：以 token 本身為身分，函式內直接解 token
    ("auth.py", "POST", "/api/auth/logout"),
    ("auth.py", "GET", "/api/auth/me"),
    ("auth.py", "PATCH", "/api/auth/change-password"),
    # 健康檢查與版本：heartbeat_job.py 與部署面板要在沒有 session 的情況下打
    ("auth.py", "GET", "/api/ping"),
    ("auth.py", "GET", "/api/system/version"),
    ("auth.py", "GET", "/api/system/deployed-version"),
    ("system.py", "GET", "/api/system/webauthn-config-status"),
    # 伺服器時間：前端對時用，不含任何公司資料
    ("dashboard.py", "GET", "/api/now"),
    # ⚠️ 2026-09-22 §4 YD：兩支 GCIS 代理（`/api/company/tax/{tax_id}` 與
    #    `/api/company/search`）**已經自己有守門了**，不再是公開路由
    #    ⇒ 它們從這張表移除。
    #
    # 🔑 而抓到這件事的是這張表自己的**反向控制**
    #    （`test_public_route_allowlist_has_no_stale_entries`）——
    #    它報「清單上有東西已經不公開了」。
    # 📌 那正是一張豁免清單該有的第二個方向：
    #    **不只驗「清單外的都有守門」，還要驗「清單上的還需要在清單上」。**
    #    ☠️ 少了它，一張豁免清單只會愈來愈長，
    #    而**每一列都看起來像一個曾經被審查過的決定**。
}


def _scan_routes():
    for f in sorted((_BACKEND / "routers").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        marks = [(m.start(), m.group(1).upper(), m.group(2)) for m in _ROUTE_DEC.finditer(src)]
        for i, (pos, method, path) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            yield f.name, method, path, src[pos:end]


def test_every_route_has_a_guard_or_is_a_known_public_endpoint():
    """新增端點忘了呼叫守門函式，是這套系統踩過好幾次的缺陷類型
    （見 §12 2026-09-13 的「模組權限盤點：七項對接斷點」）。

    這一題不檢查「擋得對不對」——那是各功能測試的事；它只檢查
    「有沒有想過要擋」。
    """
    unguarded = [
        (fname, method, path)
        for fname, method, path, body in _scan_routes()
        if not _GUARD_CALL.search(body)
    ]
    unexpected = [r for r in unguarded if r not in _PUBLIC_ROUTES]
    assert not unexpected, (
        "這些端點沒有呼叫任何守門函式，也不在已知的公開端點清單裡：\n  "
        + "\n  ".join(f"{f}  {m} {p}" for f, m, p in unexpected)
        + "\n\n請加上 _require_user()／require_any_module()／該模組自己的守門函式，"
          "或在本檔 _PUBLIC_ROUTES 註明為什麼它可以公開。"
    )


def test_public_route_allowlist_has_no_stale_entries():
    """反向控制：白名單裡不該有已經不存在或已經補上守門的端點。

    少了這一題，白名單會一路長大、沒有人回頭清，最後變成「全部都在白名單裡」。
    """
    actual_unguarded = {
        (fname, method, path)
        for fname, method, path, body in _scan_routes()
        if not _GUARD_CALL.search(body)
    }
    stale = _PUBLIC_ROUTES - actual_unguarded
    assert not stale, (
        f"這些端點已經不需要留在公開白名單裡（已補守門或已移除）：{sorted(stale)}")


# 以「擁有者」或「資料狀態」把關、而不是以角色把關的刪除端點。
# 每一筆都逐一讀過原始碼確認過，不是為了讓測試變綠才加進來的。
_DELETE_OWNERSHIP_VERIFIED = {
    # 刪自己的 passkey：token 本身就是身分，刪得掉的一定是自己那張
    ("auth.py", "/api/auth/webauthn/credentials/{cred_id}"),
    # 釋放自己的編輯鎖（edit_presence）
    ("system.py", "/api/edit-presence"),
    # 報價單刪除走**狀態**把關而不是角色——§5.1「僅草稿可刪；其他狀態回 403」
    ("quotations.py", "/api/quotations/{quote_no}"),
}


def test_destructive_routes_check_role_or_ownership():
    """DELETE 端點必須檢查角色或擁有者，不能只有「有登入就好」。

    `_require_user(authorization)` 單獨出現代表只驗證了身分，沒有驗證權限。
    """
    weak = []
    for fname, method, path, body in _scan_routes():
        if method != "DELETE":
            continue
        if (fname, path) in _DELETE_OWNERSHIP_VERIFIED:
            continue
        has_role = re.search(r'role.{0,40}(superadmin|admin)|_is_admin|require_superadmin'
                             r'|require_any_module|_guard_|_require_(?!user\b)\w+', body)
        if not has_role:
            weak.append(f"{fname}  {method} {path}")
    assert not weak, (
        "這些刪除端點只驗證了身分、沒有驗證權限：\n  " + "\n  ".join(weak)
        + "\n\n刪除是不可逆的，至少要檢查角色、模組或資料擁有者。"
    )


# ══════════════════════════════════════════════════════════════════════
# C. 模組串接 — 刻意不在這裡重做
# ══════════════════════════════════════════════════════════════════════
#
# 這一塊已經由 `test_module_keys_consistency_2026_09_13.py` 完整覆蓋，而且比
# 這裡原本寫的更周全——除了「目錄／後端／側欄三邊的 key 要對得起來」，它還守著
# 模組檢查最危險的失敗模式：**擋錯人**（某個模組的頁面呼叫到一支不接受該模組的
# API，畫面一片 403，而後端測試全綠，因為測試多半用 admin 帳號、admin 直通）。
#
# 寫這支稽核時我一度在這裡另外寫了三題，其中一題斷言
# `_SUPERADMIN_MODULES` 應該等於 users.html 的 **allModules**，並照著去「修」了
# helpers/auth.py——結果打破了既有測試守著的真正不變量：那份樣板要等於前端的
# **superadmin 角色樣板**，不是全部可授予模組的集合。改動已還原。
#
# 記在這裡是因為這個教訓比那三題有價值：**動手改之前先確認有沒有既有測試在守
# 同一件事**，既有的那份通常比臨時想出來的斷言更清楚為什麼要這樣。

# ══════════════════════════════════════════════════════════════════════
# D. 組織邏輯
# ══════════════════════════════════════════════════════════════════════

_KNOWN_ROLES = {"superadmin", "admin", "sales", "engineer", "viewer"}


def test_no_unknown_role_strings_in_backend():
    """程式裡比對的角色字串一定要是已知角色。

    `role == 'superadmn'` 這種拼錯不會有任何錯誤訊息，只會**永遠不成立**
    ——也就是那道權限檢查靜悄悄地永遠放行或永遠擋下。
    """
    bad = {}
    pat = re.compile(r"role.{0,20}?['\"]([a-z_]{3,20})['\"]")
    for f in list((_BACKEND / "routers").glob("*.py")) + list((_BACKEND / "helpers").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in pat.finditer(src):
            token = m.group(1)
            # 只看真的在跟角色比對的位置，排除欄位名／訊息文字
            if token in _KNOWN_ROLES or "_" in token:
                continue
            ctx = src[max(0, m.start() - 60):m.end() + 20]
            if re.search(r"role\s*(==|!=|in\b|not in\b)", ctx):
                bad.setdefault(f.name, set()).add(token)
    assert not bad, (
        f"疑似拼錯或未知的角色字串：{ {k: sorted(v) for k, v in bad.items()} }\n"
        f"已知角色：{sorted(_KNOWN_ROLES)}")


def test_user_role_column_only_holds_known_roles(client, make_user):
    """資料庫裡實際存在的角色值也要在已知集合內。

    靜態掃描看的是程式碼，這一題看的是資料——兩者都可能單獨漂掉。
    """
    make_user(username="audit_role_probe", role="sales")
    import db
    conn = db.get_db()
    try:
        roles = {r["role"] for r in conn.execute(
            "SELECT DISTINCT role FROM users WHERE role IS NOT NULL AND role != ''").fetchall()}
    finally:
        conn.close()
    assert not (roles - _KNOWN_ROLES), (
        f"users.role 出現未知角色值：{sorted(roles - _KNOWN_ROLES)}\n"
        "——權限檢查全都是拿字串比對，資料庫裡存了不認得的值等於那個人不屬於任何角色。")


def test_department_and_division_references_are_valid(client, make_user):
    """組織階層的外鍵完整性：使用者掛的部門／處必須存在。

    §7 的部門篩選（dashboard、stage-board 的 department_id）是拿
    users.department_id 去比對的——指向不存在的部門會讓那個人從所有
    部門篩選中默默消失，而不是報錯。
    """
    make_user(username="audit_org_probe", role="sales")
    import db
    conn = db.get_db()
    try:
        dept_ids = {r["id"] for r in conn.execute("SELECT id FROM departments").fetchall()}
        div_ids = {r["id"] for r in conn.execute("SELECT id FROM divisions").fetchall()}
        user_ids = {r["id"] for r in conn.execute("SELECT id FROM users").fetchall()}
        users = conn.execute("SELECT username, department_id FROM users").fetchall()
        depts = conn.execute(
            "SELECT id, name, division_id, manager_user_id FROM departments").fetchall()
    finally:
        conn.close()

    # users **沒有** division_id 欄位——處是透過 departments.division_id 連的，
    # 所以組織是 users → departments → divisions 兩段，兩段都要驗，
    # 外加部門主管指向的使用者也要存在（主管簽核會去找那個人）。
    orphans = [
        f"使用者 {r['username']} → 不存在的部門 id={r['department_id']}"
        for r in users if r["department_id"] and r["department_id"] not in dept_ids
    ] + [
        f"部門 {r['name']}(id={r['id']}) → 不存在的處 id={r['division_id']}"
        for r in depts if r["division_id"] and r["division_id"] not in div_ids
    ] + [
        f"部門 {r['name']}(id={r['id']}) 的主管指向不存在的使用者 id={r['manager_user_id']}"
        for r in depts if r["manager_user_id"] and r["manager_user_id"] not in user_ids
    ]
    assert not orphans, (
        "組織階層有指向不存在對象的參照：\n  " + "\n  ".join(orphans)
        + "\n——部門篩選會讓這些人默默消失、主管簽核會找不到人，而不是報錯。")


# ══════════════════════════════════════════════════════════════════════
# BG1 —— 排除清單自己沒有人守（A 2026-09-23，A-2 實跑找到）
# ══════════════════════════════════════════════════════════════════════

def test_bg1_every_excluded_table_still_exists(client):
    """🔴 `BG1甲` **排除清單裡的每一張表，都必須真的存在。**

    ☠️ 指不到東西的那幾列**讓清單看起來很完整**，而它們什麼都沒排除 ——
       ⇒ 下一個人讀到的是「這 37 張都被決定過了」，
         而其中幾張**早就不存在**，那個決定是對一個不存在的東西做的。
    📌 現在就綠 ⇒ **它的價值在未來**：防這張清單爛掉。
    🔑 〈不要用會動的名字〉的表格版：**一列指不到東西的資料，
       讀起來卻像一個決定。**
    """
    tables = _all_tables(client)
    ghost = sorted(set(_NOT_IN_JSON_BACKUP) - tables)
    assert not ghost, (
        "排除清單裡有 %d 張表不存在於資料庫：\n  " % len(ghost)
        + "\n  ".join("%s —— 登記理由：%s"
                      % (t, str(_NOT_IN_JSON_BACKUP[t])[:48]) for t in ghost)
        + "\n☠️ 那幾列**讓清單看起來很完整**，而它們什麼都沒排除。\n"
        + "⇒ 表被改名或刪掉了 ⇒ 把這幾列拿掉。")


def test_bg1_every_excluded_table_has_a_reason(client):
    """🔴 `BG1丙` **每一張排除的表都要有理由，而理由要是資料不是註解。**

    ☠️ 原本那 37 張的理由寫在**群組註解**裡：
    ```
    test_every_table_is_either_backed_up_or_explicitly_excluded 的訊息逐字說
      「或在本檔 _NOT_IN_JSON_BACKUP 註明不需要的理由」
    而 `_NOT_IN_JSON_BACKUP` 是一個 **set** ⇒ **沒有任何東西在守那句話**
    ```
    🔑 〈散文對工具是隱形的〉：註解裡的理由，守門讀不到 ——
       而那道 docstring 宣稱它守得住。
    ⚙️ 而「理由」要有下限：一兩個字的理由等於沒有理由。
    """
    assert isinstance(_NOT_IN_JSON_BACKUP, dict), (
        "`_NOT_IN_JSON_BACKUP` 是 %s，不是 dict ——\n"
        % type(_NOT_IN_JSON_BACKUP).__name__
        + "☠️ set 裝不下理由 ⇒ 「每一張都要有理由」這件事沒有東西在守。")
    thin = sorted(t for t, why in _NOT_IN_JSON_BACKUP.items()
                  if not isinstance(why, str) or len(why.strip()) < 8)
    assert not thin, (
        "這幾張排除的表沒有寫得出來的理由：%s\n" % thin
        + "🔑 判準不是「有沒有填」，是**下一個人讀得出「為什麼重建它沒有意義」**。")


def test_bg1_the_exclusion_list_cannot_swallow_the_whole_database(client):
    """⚙️ `BG1` 的**真正反向控制**：排除清單不可以涵蓋全部的表。

    ☠️ A-2 實跑（記憶體合成，未動檔）：
    ```
    把全部 94 張表塞進排除清單 => undecided=0 ／ stale=0 => **兩題都綠**
    成因：`test_backup_list_has_no_stale_entries` 算的是 `backed - tables`，
          **與排除清單無關** —— 而它的 docstring 說它守得住這件事
    ```
    🔑 **一個不對的防護，配一個聽起來對的描述** ⇒
       沒有人會去補真正的那一道，**因為說明說它有了**。

    ⚠️ 而判準**不可以是一個比例上限**（A 否決乙案）：
    ```
    「排除清單 ≤ 表數的 50%」 => 與 test_spec_coverage 上一版的
       「差集不可以大於 25」同一個形狀 —— **魔術數字會隨規模失效，
       某天變成一道永遠綠的門**
    ```
    ⇒ 改釘一個**不隨規模變動**的不變量：
       **每日備份實際查到的表，必須與排除清單互斥、而且合起來不可以少於全部。**
    """
    tables = _all_tables(client)
    excluded = set(_NOT_IN_JSON_BACKUP)
    backed = _json_backup_tables()

    overlap = sorted(excluded & backed)
    assert not overlap, (
        "這幾張表**同時**在備份清單與排除清單裡：%s\n" % overlap
        + "☠️ 兩邊都有 ⇒ 沒有人知道它到底算不算被決定過，\n"
          "   而「互斥且窮盡」那道分類從此分不出漏掉的那一張。")

    assert excluded != tables, (
        "排除清單涵蓋了**全部** %d 張表 ——\n" % len(tables)
        + "☠️ 那樣 `undecided` 恆為 0 ⇒ 上面那道「每一張表都要做決定」**永遠綠**，\n"
          "   而每日 JSON 備份**一張表都不會有**。\n"
        + "🔑 這一格就是 A-2 實跑出來的那個洞。")

    undecided = tables - backed - excluded
    assert not undecided, (
        "這幾張表兩邊都不在：%s\n" % sorted(undecided)
        + "⚠️ 與上面那道題同一件事 —— 這裡重述是為了讓「互斥」與「窮盡」"
          "在同一題裡讀得出來。")
