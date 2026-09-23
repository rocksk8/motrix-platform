"""Server startup checks: admin seed, weak-password scan, session cleanup, Edge path."""
import json
import os
import logging
import secrets
import subprocess
import threading
from datetime import datetime, date

from db import get_db
from .auth import (
    _hash_pw, _SUPERADMIN_MODULES, _LEGACY_WEAK_PASSWORDS,
    _verify_pw, _write_initial_credentials,
)
from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)


# ── Edge executable resolution ────────────────────────────────────────────────

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _get_edge_path() -> str:
    """Return the Edge executable path.

    Checks system_settings['edge_path'] first; if empty or the path doesn't
    exist, falls back to known install locations.
    Raises RuntimeError if Edge cannot be found anywhere.
    """
    configured = (_get_setting("edge_path") or "").strip()
    if configured and os.path.exists(configured):
        return configured
    for candidate in _EDGE_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        "找不到 Microsoft Edge 執行檔。"
        "請至「系統設定 → Edge 瀏覽器路徑」手動指定完整路徑。"
    )


# ── PDF 產生並發限制（2026-09-07，架構地圖建議事項）─────────────────────────
#
# 每一份 PDF 匯出（報價單／出貨單／承攬商匯款申請／發票開立簽核單／請款單／
# 案件結案報表／網路架構規劃書）都會各自 spawn 一個 `msedge.exe --headless`
# 子行程（見 pdf_gen.py 與 network_plan_export.py::_render_pdf_via_edge()）。
# 正式機是單一 Windows 主機、沒有任何行程池限制——如果短時間內多人同時觸發
# 簽核完成（背景執行緒各自產 PDF）或匯出動作，理論上可能同時開出一堆 Edge
# 行程，把單機 CPU/記憶體吃滿，拖垮正在跑的 uvicorn 本身。用一個全域
# BoundedSemaphore 限制同時執行的 Edge headless 行程數量，超過上限的呼叫方
# 排隊等待輪到自己即可，不會真的失敗，只是慢一點。
EDGE_PDF_MAX_CONCURRENCY = 3
EDGE_PDF_SEMAPHORE = threading.BoundedSemaphore(EDGE_PDF_MAX_CONCURRENCY)

# 單次 Edge headless 渲染的時間上限（2026-09-15）。
#
# 原本是散在 pdf_gen.py（15 處）與 network_plan_export.py（1 處）的字面值 40，
# 十六份幾乎一字不差的複製。改成一個具名常數，順便讓機器忙的時候能用環境變數
# 拉高而不必改程式碼。
#
# **為什麼從 40 拉到 120**：40 秒是「Edge 正常啟動＋渲染」的好幾倍，單看一次匯出
# 綽綽有餘——但它量的是**牆鐘時間**，機器被別的東西吃滿時，光是 Edge 冷啟動就
# 可能耗掉大半。2026-09-15 打包時 `test_export_excel_and_pdf` 就是這樣倒的：
# 那一題單獨跑 6 秒過，在 8 個 pytest-xdist worker 一起跑的情況下 40 秒不夠。
# 正式機同樣會遇到（每日備份／多人同時匯出時），而使用者看到的是一個沒有訊息的
# 500。拉到 120 秒換到的是「忙的時候慢一點」而不是「忙的時候直接失敗」。
EDGE_PDF_TIMEOUT_SECONDS = int(os.environ.get("MOTRIX_EDGE_PDF_TIMEOUT", "120"))


def run_edge_pdf(cmd: list) -> None:
    """跑一次 Edge headless 產 PDF：拿 semaphore、限時、逾時不往外丟例外。

    **逾時為什麼是吞掉而不是 raise**：十六個呼叫端在這一行之後全都緊接著同一道
    檢查——「tmp_pdf 沒產出或是 0 byte 就 raise ValueError」。逾時的結果正是
    「沒產出」，讓那道既有的檢查去報錯，錯誤路徑只有一條、呼叫端一行都不用改。

    在此之前 `subprocess.TimeoutExpired` 沒有任何一處接（全 repo 搜不到），會一路
    竄到全域 exception handler 變成「伺服器發生內部錯誤，請聯絡管理員」＋一份
    traceback，使用者與 log 都看不出是渲染逾時。現在 log 裡會有明確的一行。
    """
    with EDGE_PDF_SEMAPHORE:
        try:
            subprocess.run(
                cmd, timeout=EDGE_PDF_TIMEOUT_SECONDS, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Edge PDF 渲染逾時（%d 秒）——機器負載過高或該份文件過大；"
                "可用環境變數 MOTRIX_EDGE_PDF_TIMEOUT 調整上限",
                EDGE_PDF_TIMEOUT_SECONDS,
            )


# ── Startup routines ──────────────────────────────────────────────────────────

def init_default_admin() -> None:
    """Ensure the superadmin account exists; new installs get a random temp password."""
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM users WHERE username='jeff'").fetchone():
            temp_pw = secrets.token_urlsafe(14)
            conn.execute(
                "INSERT INTO users "
                "(username, password_hash, display_name, role, email, modules, active, "
                "created_at, must_change_password) "
                "VALUES ('jeff', ?, '黃玉龍', 'superadmin', 'jeff@miactw.com', ?, 1, ?, 1)",
                (
                    _hash_pw(temp_pw),
                    json.dumps(_SUPERADMIN_MODULES),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            path = _write_initial_credentials("jeff", temp_pw)
            logger.warning(
                "已建立預設 superadmin（jeff）。臨時密碼已寫入 %s — 請立即登入並修改密碼。", path
            )
        else:
            conn.execute(
                "UPDATE users SET display_name='黃玉龍' WHERE username='jeff' "
                "AND display_name IN ('Jeff 管理員','Jeff','jeff','jeff超級管理員','')"
            )
            conn.execute(
                "UPDATE users SET email='jeff@miactw.com' WHERE username='jeff' "
                "AND (email='' OR email IS NULL)"
            )
            conn.commit()
    finally:
        conn.close()


#: `IA2` §3①：展示帳號**出貨預設不建立**。
#:
#: 🔴 改版前 `init_demo_account()` 無條件呼叫、密碼寫死是公司統一編號
#: （公司統一編號，同一個數字印在我們自己匯出的 PDF 頁尾上）、
#: `must_change_password=0`、且明文密碼進 `logs/server.log`——
#: 每一個賣出去的安裝都有一個密碼公開、不能關掉的 superadmin。
#: ✅ 資料隔離本身是真的（`reset_demo_db()` ＋ `DEMO_TOKEN_PREFIX`，
#: middleware 把 demo 的每個請求路由到隔離庫）——問題不是它能做什麼，
#: 是**它不該在那裡**：一個不存在的帳號不需要任何隔離。
#: ⚠️ 字面值留著（守門釘「出貨預設關」無條件綠），環境變數放在
#: `demo_account_on()` 裡讀——同 `helpers/tender_source.py::radar_on()`
#: 的理由：寫進這裡的初始值會讓守門的結果取決於周圍環境。
DEMO_ACCOUNT_ENABLED = False

#: demo 帳號的臨時密碼寫到**自己的檔案**，不跟 jeff 共用
#: `_CREDENTIALS_FILE`——那個檔是覆寫不是附加，兩支 init 在同一次啟動
#: 都會跑，共用檔案的話後寫的會把先寫的蓋掉。
_DEMO_CREDENTIALS_FILE = os.path.join(
    os.path.dirname(__file__), "..", ".initial_demo_credentials.txt")


def demo_account_on():
    """展示帳號的建立開關現在開著沒。**只有 `MOTRIX_DEMO_ACCOUNT=1` 才開。**

    ⚠️ 判準是 `== "1"` 不是真假值：`"0"` 是非空字串，用真假值判會變成開著。
    """
    return DEMO_ACCOUNT_ENABLED or os.getenv("MOTRIX_DEMO_ACCOUNT") == "1"


def init_demo_account() -> None:
    """Ensure the 'demo' showcase account exists in the real DB (gatekeeper row
    used only to authenticate the login POST). All actual browsing after login
    happens against the isolated demo DB — see db.reset_demo_db() /
    routers/auth.py auth_login().

    `IA2` §3①：**只管「要不要建立」**，只在這一列還不存在、而且
    `demo_account_on()` 開著時才建。既有安裝已經有這一列的話**這支不動
    它**——那一列的 `active` 狀態由 `db.py` 的一次性 migration
    （`IA2` §3③）決定，不是每次開機都在這裡重判一次
    （不然有人想手動重新開啟展示模式，會被這裡每次開機打回 0）。
    """
    if not demo_account_on():
        return
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM users WHERE username='demo'").fetchone():
            temp_pw = secrets.token_urlsafe(14)
            conn.execute(
                "INSERT INTO users "
                "(username, password_hash, display_name, role, modules, active, "
                "created_at, must_change_password) "
                "VALUES ('demo', ?, '展示帳號', 'superadmin', ?, 1, ?, 1)",
                (
                    _hash_pw(temp_pw),
                    json.dumps(_SUPERADMIN_MODULES),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            path = _write_initial_credentials(
                "demo", temp_pw, path=_DEMO_CREDENTIALS_FILE)
            logger.warning(
                "已建立展示帳號（demo）。臨時密碼已寫入 %s — 請立即登入並修改密碼。", path
            )
    finally:
        conn.close()


def flag_weak_passwords() -> None:
    """Mark accounts still using known weak/legacy passwords for forced rotation.

    Throttled to once per calendar day to avoid repeated PBKDF2 work on every restart.
    """
    today = date.today().isoformat()
    if _get_setting("security.last_weak_pw_scan") == today:
        return
    conn = get_db()
    try:
        try:
            rows = conn.execute(
                "SELECT id, username, password_hash, must_change_password FROM users WHERE active=1"
            ).fetchall()
        except Exception:
            return
        flagged = 0
        for r in rows:
            if r["must_change_password"]:
                continue
            stored = r["password_hash"] or ""
            for pw in _LEGACY_WEAK_PASSWORDS:
                try:
                    if _verify_pw(pw, stored):
                        conn.execute(
                            "UPDATE users SET must_change_password=1 WHERE id=?", (r["id"],)
                        )
                        flagged += 1
                        logger.warning("使用者 %s 仍使用弱/預設密碼，已標記 must_change_password", r["username"])
                        break
                except Exception:
                    continue
        if flagged:
            conn.commit()
            try:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        datetime.now().isoformat(), None, "system", "系統",
                        "security.flag_weak_password", "user", "",
                        f"{flagged} 個帳號",
                        json.dumps({"count": flagged}, ensure_ascii=False),
                    ),
                )
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("flag_weak_passwords failed: %s", e)
    finally:
        conn.close()
    try:
        _set_setting("security.last_weak_pw_scan", today)
    except Exception:
        pass


def init_unlock_passwords() -> None:
    """Clear any unlock-password hashes that still match historical defaults.

    Throttled to once per calendar day.
    """
    today = date.today().isoformat()
    if _get_setting("security.last_unlock_pw_scan") == today:
        return
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, unlock_password_hash FROM users WHERE role='superadmin'"
        ).fetchall()
        cleared = 0
        for r in rows:
            stored = (r["unlock_password_hash"] or "").strip()
            if not stored:
                continue
            for pw in _LEGACY_WEAK_PASSWORDS:
                try:
                    if _verify_pw(pw, stored):
                        conn.execute(
                            "UPDATE users SET unlock_password_hash='' WHERE id=?", (r["id"],)
                        )
                        cleared += 1
                        logger.warning(
                            "已清除 superadmin %s 的預設/弱解鎖密碼，請至使用者管理重新設定",
                            r["username"],
                        )
                        break
                except Exception:
                    continue
        if cleared:
            conn.commit()
            try:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        datetime.now().isoformat(), None, "system", "系統",
                        "security.clear_default_unlock", "user", "",
                        f"{cleared} 個帳號",
                        json.dumps({"count": cleared}, ensure_ascii=False),
                    ),
                )
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("init_unlock_passwords failed: %s", e)
    finally:
        conn.close()
    try:
        _set_setting("security.last_unlock_pw_scan", today)
    except Exception:
        pass


def _cleanup_sessions() -> None:
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at IS NOT NULL AND expires_at < ?",
            (datetime.now().isoformat(),),
        )
        conn.commit()
    except Exception:
        logger.exception("_cleanup_sessions failed")
    finally:
        conn.close()


def _version_to_updated_at(date_str: str, version: str, time_str: str = "") -> str:
    """Convert manifest date/time/version fields to an ISO datetime string.

    Priority:
      1. Explicit ``time`` field (HH:MM or HH:MM:SS) — most accurate.
      2. Version suffix letter (a→01:00, b→02:00, …) — ordering fallback.
      3. Midnight (T00:00:00) — last resort for no-suffix versions.
    """
    import re as _re
    if len(date_str) != 10:      # already a full datetime string
        return date_str
    if time_str:
        t = time_str.strip()
        if t.count(":") == 1:
            t += ":00"
        return f"{date_str}T{t}"
    m = _re.search(r'([a-z])$', version)
    if m:
        hour = ord(m.group(1)) - ord('a') + 1
        return f"{date_str}T{hour:02d}:00:00"
    return date_str + "T00:00:00"


_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "version_manifest.json")


def _manifest_entries() -> list:
    """`version_manifest.json` 的內容。讀不到就回空清單。

    ⚠️ `utf-8-sig`：容忍 BOM。這個檔目前沒有 BOM，但只要有人用 PowerShell 重寫它
    （PS 5.1 的 `Set-Content -Encoding UTF8` 會加），純 `utf-8` 會在第一個字元
    就 `JSONDecodeError`，而整個模組版本同步會**靜默停擺**（`1c8f2e8` 踩過一次）。
    """
    if not os.path.exists(_MANIFEST_PATH):
        return []
    try:
        with open(_MANIFEST_PATH, encoding="utf-8-sig") as f:
            entries = json.load(f)
    except Exception:
        logger.exception("_manifest_entries: failed to load version_manifest.json")
        return []
    return entries if isinstance(entries, list) else []


def drift_between(entries, db_keys) -> dict:
    """純函式版的雙向比對：`entries` 是 manifest 的內容，`db_keys` 是
    `{(module, version)}`。

    🔑 抽出來是為了**讓兩個呼叫端共用同一個判準**：
    伺服器內（`manifest_drift()`）與打包流程（`tools/check_version_sync.py`，
    它可以用 `--db` 指到另一份資料庫）。
    ☠️ 兩份各自實作的話，「守門說同步了」與「實際同步了」會在某一天不是同一件事，
    而那一天不會有人發現。
    """
    manifest_keys, duplicates = set(), []
    for e in entries or []:
        key = ((e.get("module") or "").strip(), (e.get("version") or "").strip())
        if not key[0] or not key[1]:
            continue
        if key in manifest_keys:
            duplicates.append("%s / %s" % key)
        manifest_keys.add(key)

    normalized = {(str(m).strip(), str(v).strip()) for m, v in (db_keys or set())}
    db_only = sorted("%s / %s" % k for k in (normalized - manifest_keys))
    manifest_only = sorted("%s / %s" % k for k in (manifest_keys - normalized))
    return {
        # 🔑 `ok` 只看 `db_only` 與 `duplicates`：`manifest_only` 是等待重啟的
        #    正常狀態，不是缺陷（`VR9`）。
        "ok": not db_only and not duplicates,
        "db_only": db_only,
        "manifest_only": manifest_only,
        "duplicates": duplicates,
    }


def manifest_drift() -> dict:
    """`version_manifest.json` 與 `module_versions` 資料表的**兩個方向**。

    ```
    manifest_only   manifest 有、DB 沒有   ✅ 正常 —— 服務還沒重啟，下次開機會同步
    db_only         DB 有、manifest 沒有   🔴 重建資料庫就永久消失
    duplicates      manifest 裡重複的鍵     🔴 資料表有 UNIQUE ⇒ 永遠進不去
    ```

    🔑 **兩個方向要分開回報，不可以合成一個「差 N 列」的數字**（`VR9`）：
    ☠️ 兩邊都是「對不上」，**而處置相反** —— 一個混起來的指標會讓人去修錯的那一邊，
    📌 而「修錯的那一邊」在這裡具體是什麼：把 `manifest_only` 當缺陷，
    會導出一個「啟動時強制同步」的修法，**而那正是 `_m035` 修掉的東西**
    （加 `UNIQUE(module, version)` 之前，每次啟動整份重插，兩天內長出 62 萬列）。

    `ok` 只看 `db_only` 與 `duplicates`。
    """
    db_keys = set()
    conn = get_db()
    try:
        for row in conn.execute(
                "SELECT module, version FROM module_versions"):
            db_keys.add(((row["module"] or "").strip(),
                         (row["version"] or "").strip()))
    except Exception:
        logger.exception("manifest_drift: failed to read module_versions")
        # ☠️ 讀不到資料表**不是通過**：那會讓這道守門在最需要它的時候消失。
        return {"ok": False, "db_only": [], "manifest_only": [],
                "duplicates": [], "error": "module_versions 讀不到"}
    finally:
        conn.close()

    return drift_between(_manifest_entries(), db_keys)


def _sync_module_versions() -> None:
    """Upsert version_manifest.json entries into module_versions table.

    ⚠️ **有人在用這個函式的副作用當重啟計數器**（`VR10`，2026-09-22）。
    下面那個 `INSERT OR IGNORE` 每次啟動都對整份 manifest 跑一遍，而
    `module_versions` 是 `AUTOINCREMENT` ⇒ 撞 `UNIQUE` 時 `sqlite_sequence`
    仍然會推進一整批。比較兩份每日備份的 `sqlite_sequence(module_versions)`
    就看得出中間重啟過幾次 —— 那是 `DEPLOY.md` 那個 🔴🔴 步驟
    （部署後要把排程工作結束再執行）目前**唯一**的純命令列驗證方式。
    🔑 前提是它**每次啟動無條件執行**。
    ☠️ 若哪天改成有條件（加快取、加早退、只在版本變了才跑），
    那個計數器會失效**而不會有人發現** —— `sqlite_sequence` 照樣在動，
    只是它量的已經不是那件事（〈守門守的對象被搬走〉）。
    ⇒ 要改成有條件執行的話，請同時去 `DEPLOY.md` 把那個驗證方式撤掉。

    Key rules:
    - (module, version) is the natural unique key.
    - First run: inserts all historical records.
    - Subsequent runs: INSERT OR IGNORE skips existing rows, then UPDATE
      corrects updated_at / content for system-synced rows so manifest
      edits (e.g. adding a "time" field) take effect on next restart.
    - User-created entries (updated_by != 'system') are never modified.
    """
    # 🔑 跟 `manifest_drift()` 共用同一個讀取函式：兩份讀法會分岔，
    #    而分岔之後「守門說同步了」與「實際同步了」就不是同一件事。
    entries = _manifest_entries()
    if not entries:
        return

    conn = get_db()
    try:
        inserted = updated = 0
        for e in entries:
            module   = (e.get("module")  or "").strip()
            version  = (e.get("version") or "").strip()
            content  = (e.get("content") or "").strip()
            date_str = (e.get("date") or e.get("updated_at") or "").strip()
            time_str = (e.get("time") or "").strip()
            if not module or not version:
                continue

            updated_at = _version_to_updated_at(date_str, version, time_str)

            cur = conn.execute(
                "INSERT OR IGNORE INTO module_versions "
                "(module, version, updated_at, content, updated_by) VALUES (?,?,?,?,?)",
                (module, version, updated_at, content, "system"),
            )
            inserted += cur.rowcount

            # Sync: update timestamp / content on existing system-synced rows
            rv = conn.execute(
                "UPDATE module_versions SET updated_at=?, content=? "
                "WHERE module=? AND version=? AND updated_by='system' "
                "  AND (updated_at!=? OR content!=?)",
                (updated_at, content, module, version, updated_at, content),
            )
            updated += rv.rowcount

        conn.commit()
        if inserted:
            logger.info("_sync_module_versions: inserted %d new entries from manifest", inserted)
        if updated:
            logger.info("_sync_module_versions: synced %d existing rows from manifest", updated)
    except Exception:
        logger.exception("_sync_module_versions failed")
    finally:
        conn.close()
