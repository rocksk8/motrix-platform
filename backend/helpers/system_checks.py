# -*- coding: utf-8 -*-
"""L1 系統健康的每日檢查（2026-09-26 自 routers/daily_tasks.py 搬出，M12 搬遷前置）。

HTTPS 憑證到期、備份新鮮度、磁碟空間、測試暫存、簽核逾期催辦、請求紀錄清理。這些是系統本身的事，
不屬於每日任務模組：原本寄生在 M12 ⇒ 停用每日任務會連帶停掉備份與磁碟告警。
程式碼逐字搬移；測試 patch 的名字（notify_* 等）是本模組的屬性。
"""
import calendar
import json
import os
import threading
from datetime import date as _date, timedelta as _timedelta, datetime, timezone as _timezone
from typing import Optional, List

from db import get_db, spawn_bg_thread
from helpers import (
    _notify, _purge_notifications,
    notify_daily_task_assigned, notify_daily_task_completed, notify_daily_task_overdue,
    notify_daily_task_overdue_manager,
    notify_daily_task_edited, notify_warranty_expiry, notify_range_task_deadline, _warranty_expiry,
    notify_case_stage_deadline, notify_case_stage_deadline_manager,
    notify_case_project_overdue,
    notify_cert_expiry, notify_backup_stale, notify_disk_space_low,
    notify_module_activity,
    _get_setting, _set_setting, notify_approval_reminder, _workdays_elapsed,
)
from helpers.email_notify import (            # noqa: E402
    SEND_SENT as _SEND_SENT,
    SEND_PERMANENT_FAIL as _SEND_PERMANENT_FAIL,
    SEND_UNKNOWN as _SEND_UNKNOWN,
)

import logging as _log
_logger = _log.getLogger(__name__)


# ── HTTPS 憑證到期檢查（2026-09-11）──────────────────────────────────────────
# 在此之前這件事完全沒有任何監控。目前服務中的是 mkcert 自簽憑證、2028-12-10
# 到期（星期日），而 mkcert 不會自己更新——到期後的第一個上班日，全公司的
# Passkey 會一起失效，而那時候不會有人記得「mkcert」是什麼。
#
# 門檻依「憑證總效期」自動切換，不必有人在換憑證來源時記得回來改常數：
#   mkcert 自簽 ≈ 822 天 → 要手動重產，得早點講
#   Let's Encrypt = 90 天，Posh-ACME 在剩 30 天時就會自動續期
#     → 剩 21 天還沒換掉，代表自動續期已經失敗，那才是真警報。
#       若對 LE 沿用 60 天門檻，每張憑證都會在一切正常的情況下誤報一次，
#       而狼來了的告警等於沒有告警。
from core import paths as _paths
_CERT_PATH = _paths.CERT_PEM
_CERT_LONG_LIVED_DAYS   = 180              # 總效期超過此天數 → 視為手動簽發
_CERT_THRESHOLDS_MANUAL = (0, 7, 21, 60)   # 必須遞增
_CERT_THRESHOLDS_ACME   = (0, 1, 7, 21)


def _read_serving_cert(path: str = None) -> Optional[dict]:
    """讀出目前服務中的憑證資訊；沒有憑證檔（純 HTTP 模式）時回傳 None。

    刻意讀檔而不是對自己開一條 TLS 連線：`start.bat`／`autostart.bat` 載入的
    就是這個檔（`if exist certs\\cert.pem` 才加 --ssl-* 參數），讀檔沒有網路
    依賴、不受服務當下狀態影響，測試也不必真的起一個 TLS server。
    """
    path = path or _CERT_PATH
    if not os.path.exists(path):
        return None
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes as _hashes

        with open(path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())

        # cryptography 42+ 把 not_valid_after 標為 deprecated，改用 *_utc；
        # 舊版沒有那個屬性，兩邊都接以免升級/降級任一方向都會炸。
        not_after = getattr(cert, "not_valid_after_utc", None)
        if not_after is None:
            not_after = cert.not_valid_after.replace(tzinfo=_timezone.utc)
        not_before = getattr(cert, "not_valid_before_utc", None)
        if not_before is None:
            not_before = cert.not_valid_before.replace(tzinfo=_timezone.utc)

        try:
            issuer_cn = cert.issuer.get_attributes_for_oid(
                x509.oid.NameOID.COMMON_NAME)[0].value
        except Exception:
            issuer_cn = ""

        today = datetime.now(_timezone.utc).date()
        return {
            "not_after":   not_after.date().isoformat(),
            "days_left":   (not_after.date() - today).days,
            "total_days":  (not_after.date() - not_before.date()).days,
            "issuer_cn":   issuer_cn,
            "fingerprint": cert.fingerprint(_hashes.SHA256()).hex()[:16],
            "path":        path,
        }
    except Exception as exc:
        _logger.warning("_read_serving_cert(%s) failed: %s", path, exc)
        return None


def _prune_cert_guard_keys(live_keys: set) -> None:
    """只保留本次算出來的 guard key，其餘 `cert_notif.*` 一律刪掉。

    理由同 `_prune_case_project_guard_keys()`：換一張憑證就換一組 fingerprint，
    舊的 key 永遠不會再被查詢；而比當前更早的門檻也不會再被問（剩餘天數只會
    遞減）。不收斂的話這裡會重演 `module_versions` 那種「只寫不刪」的長期累積。
    結果是這個前綴在 system_settings 裡最多只佔 1 列。
    """
    conn = get_db()
    try:
        existing = [r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'cert_notif.%'"
        ).fetchall()]
        stale = [k for k in existing if k not in live_keys]
        if stale:
            conn.executemany(
                "DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
    except Exception as exc:
        _logger.warning("_prune_cert_guard_keys failed: %s", exc)
    finally:
        conn.close()


def _check_cert_expiry() -> None:
    """每日檢查 HTTPS 憑證剩餘天數；每個門檻各寄一次，已過期後每 7 天重寄。"""
    try:
        info = _read_serving_cert()
        if info is None:
            return  # 純 HTTP 模式（或憑證檔讀不到），沒有到期日要顧

        days_left  = info["days_left"]
        is_acme    = info["total_days"] <= _CERT_LONG_LIVED_DAYS
        thresholds = _CERT_THRESHOLDS_ACME if is_acme else _CERT_THRESHOLDS_MANUAL

        if days_left > thresholds[-1]:
            _prune_cert_guard_keys(set())   # 還很遠，順手把舊憑證留下的 key 收掉
            return

        if days_left < 0:
            bucket = f"exp{(-days_left) // 7}"       # 過期後每 7 天重寄一次
        else:
            bucket = next(str(t) for t in thresholds if days_left <= t)

        guard_key = f"cert_notif.{info['fingerprint']}_{bucket}"
        if _get_setting(guard_key):
            _prune_cert_guard_keys({guard_key})
            return

        _set_setting(guard_key, _date.today().isoformat())
        # 同 _check_case_project_timeline_deadline()：排程觸發、不掛在任何 request
        # 上，刻意用 threading.Thread 而非 db.spawn_bg_thread()（§3.5 例外 (a)）。
        threading.Thread(
            target=notify_cert_expiry,
            args=(days_left, info["not_after"], info["issuer_cn"], info["path"], is_acme),
            daemon=True,
        ).start()
        _logger.warning(
            "HTTPS cert expiring: %s days left (expires %s, issuer=%s)",
            days_left, info["not_after"], info["issuer_cn"],
        )
        _prune_cert_guard_keys({guard_key})
    except Exception as exc:
        _logger.warning("_check_cert_expiry failed: %s", exc)


# ── 備份新鮮度與磁碟空間（2026-09-14）──────────────────────────────────────────
#
# 這兩支補的是同一個結構性盲區：**備份系統的所有告警都是備份自己發出來的**。
# archive.py 在雲端碟掉了、某張表匯不出來的時候都會寫 BACKUP_ALERT + 寄信，
# 但「備份根本沒有跑」這件事沒有任何人會講——排程被停用、Timer 執行緒沒起來、
# 兩台機器共用同一個雲端資料夾導致其中一台看到 .done 就早退，症狀全部是
# **一片安靜**：伺服器活著、heartbeat 照打、備份頁面綠燈，只有真的要還原的
# 那天才會發現最後一份是三個月前的。
#
# 磁碟空間同理：滿了之後第一個壞掉的通常是備份（寫不進去）或測試（暫存寫不
# 進去），而這兩者都不會讓人第一時間聯想到磁碟。
#
# 做法比照 _check_cert_expiry()：掛在既有的每日 08:00 排程上，不另起 job；
# 用 system_settings 當「今天寄過了沒」的 guard，一天最多一封。

_BACKUP_STALE_HOURS = 36        # 每日備份的容許間隔（正常 24h，留一天的餘裕）
_DISK_FREE_MIN_PCT  = 10        # 剩餘空間低於此百分比 → 告警
# 2026-09-15：20 → 50 GB。這兩個門檻是 AND（見 _check_disk_space 的說明），所以在
# 1 TB 的碟上百分比那關永遠先滿足，實際的觸發點就是這個絕對值。20 GB 對一台
# 「每跑一次測試就寫 3～4 GB」的開發機來說太晚——剩 20 GB 時只剩五次測試的餘裕，
# 而且備份寫不進去通常會先發作。
_DISK_FREE_MIN_GB   = 50        # 或剩餘絕對量低於此 GB → 告警（大碟用百分比會太晚）

# 測試暫存總量超過這個值就寄信。**這條跟剩餘空間無關**：2026-09-15 實測 84 個
# `motrix-pytest-*` 目錄吃掉 136 GB，而碟上還剩 293 GB——剩餘空間的門檻不管怎麼調
# 都不會響（調到會響的程度就等於天天誤報）。照不到這種事的原因不是門檻太鬆，是
# 「只看剩多少」永遠看不到「有東西在無聲累積」。
_TEMP_BLOAT_MIN_GB  = 20

# 這些前綴是測試／打包留下的暫存，清掉一律安全。`motrix-*` 是帶時間戳或標籤的
# pytest basetemp——名字每次都不一樣，所以沒有任何機制會覆蓋或清除它；
# `pytest-of-*` 是 pytest 自己的預設 basetemp，它會輪替只留最新 3 份。
_TEMP_BLOAT_PREFIXES = ("motrix-pytest", "motrix-bench", "pytest-of-")


def _latest_audit_at(conn, actions: tuple) -> Optional[datetime]:
    """回傳 audit_log 裡這幾個 action 最後一次發生的時間，沒有就 None。"""
    ph = ",".join("?" * len(actions))
    row = conn.execute(
        f"SELECT MAX(at) AS at FROM audit_log WHERE action IN ({ph})", actions).fetchone()
    if not row or not row["at"]:
        return None
    try:
        return datetime.fromisoformat(row["at"])
    except ValueError:
        return None


def _check_backup_freshness() -> None:
    """每日檢查「最後一次成功備份」離現在多久；超過 _BACKUP_STALE_HOURS 就寄信。

    分兩條線各自判斷，因為它們的失效原因完全不同：
      本機 SQLite 快照（`backup.sqlite_snapshot`）——不依賴雲端碟，這條斷掉
        代表備份程式本身沒在跑（排程被關、Timer 執行緒死掉、服務一直沒起來）。
      雲端每日 JSON（`backup.daily_ok` / `backup.daily_partial`）——這條斷掉
        而本機那條還活著，代表雲端目的地出問題，或者**別台機器搶先寫了今天的
        .done 害這台早退**（見 archive.py `_daily_backup()`）。

    `backup.daily_partial` 也算「有跑」：它代表備份確實執行了、只是有表失敗，
    那個情境本來就有自己的告警，這裡不重複叫。

    全新環境（audit_log 一筆備份紀錄都沒有）**不告警**——那是還沒跑過第一次，
    不是壞掉；等第一次跑完之後這支才有意義的基準可以比。
    """
    try:
        conn = get_db()
        try:
            local_at = _latest_audit_at(conn, ("backup.sqlite_snapshot",))
            cloud_at = _latest_audit_at(conn, ("backup.daily_ok", "backup.daily_partial"))
        finally:
            conn.close()

        # 2026-09-15：這台機器刻意不上傳雲端（開發機，見 archive.cloud_archive_enabled）
        # → 雲端那條線本來就不會有紀錄，拿它當故障會變成每天一封假警報。**本機快照
        # 那條照舊檢查**：那才是「備份程式有沒有在跑」的指標，跟雲端政策無關。
        # archive 比照本檔既有慣例在函式內匯入（見 _disk_targets()）。
        try:
            import archive as _archive
            cloud_expected = _archive.cloud_archive_enabled()
        except Exception:
            cloud_expected = True       # 判斷不出來就照原本行為檢查，不要靜默少查一條

        if local_at is None and (cloud_at is None and cloud_expected):
            return          # 從來沒備份過 = 全新環境，不是故障
        if not cloud_expected and local_at is None:
            return          # 同上：不上傳雲端的機器只看本機那條，它也還沒跑過

        now = datetime.now()
        stale = []
        lines = [("本機 SQLite 快照", local_at)]
        if cloud_expected:
            lines.append(("雲端每日備份", cloud_at))
        for label, ts in lines:
            if ts is None:
                stale.append((label, None))
            else:
                hours = (now - ts).total_seconds() / 3600
                if hours > _BACKUP_STALE_HOURS:
                    stale.append((label, ts))

        guard_key = "backup_stale_last_notified"
        if not stale:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")     # 恢復正常 → 清掉，下次再壞會立刻再寄
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return                               # 今天已經寄過

        # 🔴 **旗標在寄信成功之後才寫，不可以先寫。**
        # 原本是先 `_set_setting(guard_key, today)` 再開執行緒 ⇒
        # 通知只要丟例外，今天就**不會再試**；而那個例外是必然的
        # （`notify_backup_stale` 缺 `datetime` import）⇒ **永遠不會寄到**。
        # 🔑 「不要記錄失敗」與「要記得重試」是兩件事，前者做對不代表後者會發生。
        #
        # ⚠️ **例外要在執行緒裡面接，不能靠下面那個 `except`。**
        # 那個 `except` 只包得到「啟動執行緒」這個動作，包不到執行緒裡面發生的事
        # ⇒ 例外被 Python 印掉或吞掉，而 `_logger` 上一個字都沒有。
        # ☠️ **那就是那個 NameError 活到今天的原因：它每天都在發生，而沒有留下過痕跡。**
        # 🔑〈防護的副作用落在盲側〉：背景執行緒讓告警不會拖慢排程，
        # 代價是「**告警自己壞了**」變成不可觀測的——而那正是最需要被觀測的那一種失敗。
        def _send_alert():
            try:
                notify_backup_stale(stale, _BACKUP_STALE_HOURS)
            except Exception:  # noqa: BLE001
                _logger.exception("notify_backup_stale failed —— 旗標不寫，今天仍會重試")
                return
            _set_setting(guard_key, today)

        # 📌 **刻意不用 `spawn_bg_thread`**：C 的題 patch 的是 `dt.threading.Thread`，
        # 換過去 patch 會打不到（`spawn_bg_thread` 在 `db` 模組裡叫 `threading.Thread`）
        # ⇒ 那兩題會失去同步執行而變成靠時序，而 flaky 比不一致貴。
        # 例外可見性已由上面的 wrapper 解決，那才是那三件要的東西。
        # ⚠️ 這裡是**實作的形狀被測試的 patch 點決定的**——正解是「patch 打在對的層級」，
        # 不是「實作遷就 patch」。凍結解除後要回來看這一段。
        threading.Thread(
            target=_send_alert,
            args=(),
            daemon=True,
        ).start()
        _logger.error("備份新鮮度告警：%s",
                      "；".join(f"{l}={'從未執行' if t is None else t.isoformat()}"
                                for l, t in stale))
    except Exception as exc:
        _logger.warning("_check_backup_freshness failed: %s", exc)


def _disk_targets() -> list:
    """要監看的磁碟：資料庫所在的磁碟一定要看；雲端存檔目前若掛得起來也看一份
    （Google Drive 這類同步碟報出來的空間是雲端配額，一樣會滿）。回傳
    [(標籤, 路徑)]，重複的磁碟機代號只留一份。"""
    import db as _db
    targets = [("資料庫與程式碟", os.path.dirname(os.path.abspath(_db.DB_PATH)))]
    try:
        import archive
        # 2026-09-15：不上傳雲端的機器不監看雲端碟。那顆碟滿了不是這台的事，兩台
        # 都監看只會讓同一件事寄兩封信；而且在開發機上它根本不是備份目的地。
        base = archive._archive_base() if archive.cloud_archive_enabled() else ""
        if base:
            targets.append(("雲端存檔碟", base))
    except Exception:
        pass

    seen, out = set(), []
    for label, path in targets:
        try:
            key = os.path.splitdrive(os.path.abspath(path))[0].upper()
        except Exception:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append((label, path))
    return out


def _check_disk_space() -> None:
    """每日檢查磁碟剩餘空間；低於門檻寄信。一天最多一封（同 _check_backup_freshness）。

    兩個門檻取「較寬鬆的那個滿足就算健康」：小碟看百分比、大碟看絕對 GB。
    只看百分比的話，2 TB 的碟剩 10%（200 GB）就叫太早；只看 GB 的話，
    256 GB 的系統碟剩 20 GB 其實已經很緊了卻還不叫。
    """
    try:
        import shutil as _shutil
        problems = []
        for label, path in _disk_targets():
            try:
                usage = _shutil.disk_usage(path)
            except Exception:
                continue        # 碟沒掛上／路徑不可用 → 那是備份告警的守備範圍
            free_gb  = usage.free / (1024 ** 3)
            free_pct = (usage.free / usage.total * 100) if usage.total else 0
            if free_gb < _DISK_FREE_MIN_GB and free_pct < _DISK_FREE_MIN_PCT:
                problems.append({
                    "label": label, "path": path,
                    "free_gb": round(free_gb, 1),
                    "total_gb": round(usage.total / (1024 ** 3), 1),
                    "free_pct": round(free_pct, 1),
                })

        guard_key = "disk_low_last_notified"
        if not problems:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return
        _set_setting(guard_key, today)

        threading.Thread(target=notify_disk_space_low, args=(problems,), daemon=True).start()
        _logger.error("磁碟空間告警：%s",
                      "；".join(f"{p['label']} 剩 {p['free_gb']}GB／{p['free_pct']}%"
                                for p in problems))
    except Exception as exc:
        _logger.warning("_check_disk_space failed: %s", exc)


def _temp_bloat_dirs() -> list:
    """列出 `%TEMP%` 底下的測試／打包暫存目錄與各自大小，大的在前。

    回傳 `[{name, path, gb}]`。掃不到或沒有權限的目錄一律跳過——這是觀測用的
    數字，不該因為某個子目錄讀不到就整支壞掉。
    """
    import tempfile
    base = tempfile.gettempdir()
    out = []
    try:
        entries = list(os.scandir(base))
    except OSError:
        return out
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if not e.name.startswith(_TEMP_BLOAT_PREFIXES):
            continue
        total = 0
        for root, _dirs, files in os.walk(e.path, onerror=lambda _e: None):
            for f in files:
                try:
                    total += os.stat(os.path.join(root, f)).st_size
                except OSError:
                    continue
        out.append({"name": e.name, "path": e.path, "bytes": total,
                    "gb": round(total / (1024 ** 3), 2)})
    # 比大小一律用原始 bytes：`gb` 是顯示用的，先四捨五入再加總會把一堆
    # 小於 5 MB 的目錄全算成 0。
    out.sort(key=lambda x: x["bytes"], reverse=True)
    return out


def _check_temp_bloat() -> None:
    """每日檢查測試暫存是否無聲累積；超過 `_TEMP_BLOAT_MIN_GB` 就寄信。一天一封。

    為什麼要獨立於剩餘空間告警：那支只會在「快滿了」才叫，而這種累積在一顆 1 TB
    的碟上可以吃掉 136 GB 都還離「快滿了」很遠（2026-09-15 實測）。等它把碟吃滿
    才叫，症狀會先表現成「測試跑不起來」或「備份寫不進去」，很難聯想到這裡。
    """
    try:
        dirs = _temp_bloat_dirs()
        total_raw_gb = sum(d["bytes"] for d in dirs) / (1024 ** 3)
        total_gb = round(total_raw_gb, 1)
        guard_key = "temp_bloat_last_notified"
        if total_raw_gb < _TEMP_BLOAT_MIN_GB:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return
        _set_setting(guard_key, today)

        threading.Thread(target=notify_disk_space_low, args=([],),
                         kwargs={"temp_bloat": dirs, "temp_total_gb": total_gb},
                         daemon=True).start()
        _logger.error("測試暫存佔用告警：共 %s GB，%s 個目錄（最大：%s）",
                      total_gb, len(dirs), dirs[0]["name"] if dirs else "-")
    except Exception as exc:
        _logger.warning("_check_temp_bloat failed: %s", exc)


# ── 簽核逾期催辦（2026-08-21）────────────────────────────────────────────────
# 報價單／承攬商匯款申請／開票申請憑據三張表的 approval JSON 形狀完全相同
# （{requestedBy, requestedAt, tiers:[{approvers:[{username,status}]}], currentTier}），
# 但比照這三個 router 各自重複一份 _active_tiers()/_current_tier_idx() 小工具的既有
# 慣例（quotations.py／contractor_vouchers.py／invoice_vouchers.py 皆有一份幾乎逐字
# 相同的版本，刻意不跨 router import 以避免循環依賴），這裡也自己放一份。

def _active_tiers(appr: dict) -> list:
    return appr.get("tiers") or []


def _current_tier_idx(appr: dict) -> int:
    return appr.get("currentTier") or 0


_APPROVAL_REMINDER_SOURCES = [
    {
        "table": "quotations", "no_col": "quote_no", "label": "報價單",
        "select_extra": "customer_name, project_name",
        "desc": lambda row, snap: (row["customer_name"] or "")
                                   + (("｜" + row["project_name"]) if row["project_name"] else ""),
    },
    {
        "table": "contractor_payment_vouchers", "no_col": "voucher_no", "label": "匯款申請",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("vendorName") or "外包人員點工",
    },
    {
        "table": "invoice_vouchers", "no_col": "voucher_no", "label": "開票申請憑據",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("customerName") or "",
    },
    {
        "table": "shipping_notes", "no_col": "note_no", "label": "出貨單",
        "select_extra": "customer_name, project_name",
        "desc": lambda row, snap: (row["customer_name"] or "")
                                   + (("｜" + row["project_name"]) if row["project_name"] else ""),
    },
    {
        "table": "payment_requests", "no_col": "request_no", "label": "請款單",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("customerName") or "",
    },
]


#: 前三階，之後**以五為基準**。使用者原話：
#: 「第三天、第五天、再來第十天以五為基準重新寄信」。
REMINDER_FIRST_STAGES = (1, 3, 5)
REMINDER_STEP_AFTER = 5


def reminder_stages_at_or_below(days):
    """所有**不超過** `days` 的階段，由小到大。

    🔴 它回答的是**另一個問題**：不是「這次寄哪一封」，
    而是「**要把哪幾階記成已寄**」。

    ☠️ 一筆單子從第 2 天停機到第 12 天 ⇒ 只該寄 `d10` **一封**，
    而 `d1`／`d3`／`d5` 要**一併標記成已寄** —— 不標的話下一次排程會補一遍，
    使用者會在同一天收到四封，**而那正是這一節要消滅的東西**。
    🔑 **「補掉欠的」與「補寄欠的」只差一個字，而收件匣裡差四封。**

    ⚠️ 用同一個答案回答兩個問題的話，其中一個一定會錯。
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return []
    out = [f"d{n}" for n in REMINDER_FIRST_STAGES if n <= days]
    n = REMINDER_FIRST_STAGES[-1] + REMINDER_STEP_AFTER
    while n <= days:
        out.append(f"d{n}")
        n += REMINDER_STEP_AFTER
    return out


#: 永久性寄送失敗的落點。
#:
#: 📌〈計數器要有落點〉：「要記錄失敗原因」**先指出記在哪張表**，
#: 否則那句要求**永遠不會被違反，也永遠不會被滿足**。
#: ⚠️ 用 `system_settings` 一列而不是新開一張表：這是**運維紀錄**不是業務資料，
#: 而新增一張表要 migration、要進備份決策、要有人決定保留期
#: ——今天已經為 `geocode_cache` 走過一次那個流程。
REMINDER_FAILURE_SETTING = "approval_reminder_failures"

#: 最多留幾筆。⚠️ 不設上限的話，一個永遠不會被修的收件人
#: 會讓那一列無限成長，而 `system_settings` 會進每日備份。
REMINDER_FAILURE_KEEP = 200


def reminder_send_failures():
    """永久性寄送失敗的紀錄。**最新的在後面。**

    每一筆：文件別／單號／階段／失敗類別／時間／嘗試次數。
    ☠️ **只寫進 log 的話，就是把這條缺陷原封不動換了個位置** ——
    所以它同時有一個端點（`GET /api/settings/reminder-send-failures`）。
    """
    rows = _get_setting(REMINDER_FAILURE_SETTING, []) or []
    return rows if isinstance(rows, list) else []


def _record_reminder_failure(doc_type, doc_no, stage, reason):
    """記一筆永久性失敗。**同一張單子的同一階只留一筆，累加嘗試次數。**

    ⚠️ 每次都追加一筆的話，一張永遠寄不出去的單子會把這張清單灌滿，
    而**真正需要被看到的那幾筆會被擠掉**（`REMINDER_FAILURE_KEEP`）。
    """
    key = f"{doc_type}|{doc_no}|{stage}"
    rows = [dict(r) for r in reminder_send_failures() if isinstance(r, dict)]
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        if row.get("key") == key:
            row["attempts"] = int(row.get("attempts", 0) or 0) + 1
            row["at"] = now
            row["reason"] = reason
            break
    else:
        rows.append({"key": key, "docType": doc_type, "docNo": doc_no,
                     "stage": stage, "reason": reason, "attempts": 1,
                     "at": now})
    _set_setting(REMINDER_FAILURE_SETTING, rows[-REMINDER_FAILURE_KEEP:])


def reminder_dedup_key(stage):
    """某一階的去重鍵。**只吃階段，不吃日期。**

    🔑 **這支函式的簽名本身就是那道防線**：不收日期參數
    ⇒ 「每天一個新鍵」在**結構上**不可能，
    而不是靠下一個人記得不要把 `today_str` 串進去。
    📌 〈修作法不要修結果〉。
    """
    return f"stage.{stage}"


def _check_approval_reminders() -> None:
    """簽核卡在柱列的催辦：**第 1／3／5 個工作日各一封，之後每 5 個工作日一封**
    （10、15、20…），3 天起同步通知全部 superadmin，直到簽核完成或退回為止。
    一律從 approval.requestedAt（原始送審時間）起算工作日，不因換層歸零；
    guard key 帶入 requestedAt，文件退回重新送審後 requestedAt 換新值，催辦
    倒數會自然重新從 0 天起算，不會被舊一輪的 guard 卡住讓新一輪永遠不寄。
    工作日計算只排除週六日，不排除國定假日（見 helpers/dates.py _workdays_elapsed
    docstring，系統目前沒有假日行事曆表可用，屬已知限制）。"""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        superadmins = [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE role='superadmin' AND active=1"
        ).fetchall()]

        for src in _APPROVAL_REMINDER_SOURCES:
            rows = conn.execute(
                f"SELECT {src['no_col']} AS doc_no, {src['select_extra']}, "
                f"json_extract(data_json,'$.approval') AS approval_json "
                f"FROM {src['table']} WHERE status IN ('待審核','簽核中')"
            ).fetchall()
            for row in rows:
                try:
                    appr = json.loads(row["approval_json"] or "{}")
                except Exception:
                    continue
                requested_at = appr.get("requestedAt") or ""
                if not requested_at:
                    continue
                try:
                    start_date = _date.fromisoformat(requested_at[:10])
                except Exception:
                    continue
                days_elapsed = _workdays_elapsed(start_date, today)
                if days_elapsed < 1:
                    continue

                tiers  = _active_tiers(appr)
                ct_idx = _current_tier_idx(appr)
                if tiers and ct_idx < len(tiers):
                    approvers     = tiers[ct_idx].get("approvers") or []
                    first_pending = next((a for a in approvers if a.get("status") != "approved"), None)
                    recipients    = [first_pending["username"]] if first_pending else []
                elif tiers:
                    continue  # 所有層皆已完成但 status 尚未更新 — 暫態，略過
                else:
                    recipients = list(superadmins)
                if not recipients:
                    continue

                snap = {}
                if "snapshot_json" in row.keys():
                    try:
                        snap = json.loads(row["snapshot_json"] or "{}")
                    except Exception:
                        snap = {}
                desc      = src["desc"](row, snap)
                doc_no    = row["doc_no"]
                doc_type  = src["label"]
                guard_base = f"approval_notif.{src['table']}.{doc_no}.{requested_at}"

                def _mark(stage: str) -> None:
                    _set_setting(f"{guard_base}.{reminder_dedup_key(stage)}",
                                 today_str)

                def _sent(stage: str) -> bool:
                    return bool(_get_setting(
                        f"{guard_base}.{reminder_dedup_key(stage)}"))

                # 🔴 **欠的階段一次結清，而只寄最高的那一封。**
                #
                # ⚠️ 判準是「**這個階段寄過沒有**」，不是「今天是不是第 5 天」——
                # 週末與停機會讓門檻被整個跳過，而那時
                # 「今天剛好是第幾天」問不出正確答案。
                owed = [st for st in reminder_stages_at_or_below(days_elapsed)
                        if not _sent(st)]
                if owed:
                    highest = owed[-1]
                    # 3 天門檻起才同步通知 superadmin（維持原本的分界）。
                    also_superadmin = int(highest[1:]) >= 3

                    # 🔴🔴 **先寄，成功才記「已通知」。**
                    #
                    # ☠️ 原本是「先 `_mark()` 再開 daemon 執行緒寄」
                    # ⇒ 信掉了而標記留著 ⇒ **那張單子永遠不會再被提醒**，
                    # 🔑 而它的症狀是**沒有症狀**：畫面正常、log 裡一行
                    # warning，而沒有人在看那一行。
                    #
                    # ⚠️ **同步呼叫不是效率的退讓**：`_check_approval_reminders`
                    # 本來就跑在背景排程裡，**沒有理由再開一層執行緒**——
                    # 而那一層正是「呼叫端拿不到結果」的成因。
                    # 📌 信裡的天數是**實際等了幾天**（12），不是門檻值（10）。
                    outcome = notify_approval_reminder(
                        doc_type, doc_no, desc, days_elapsed, recipients,
                        also_superadmin)

                    if outcome in (_SEND_PERMANENT_FAIL, _SEND_UNKNOWN):
                        # ## 兩種都「不重寄」，而**理由不同、處置也不同**
                        #
                        # `permanent_fail`：**知道**寄不出去（收件人沒有 email）
                        #   ⇒ 處置是「去幫那個人填 email」。
                        #   ☠️ 不標記的話排程每天重試到天荒地老，
                        #   🔑 而「每天重試」與「已經修好了」在 log 上長得一樣。
                        #
                        # `unknown`：**不知道**有沒有寄出去（等不到結果）
                        #   ⇒ 處置是「**去問收件人**」。
                        #   ☠️ 當成失敗而重寄 ⇒ 可能寄出兩封（第一封其實成功了）；
                        #   ☠️ 當成成功而安靜標記 ⇒ 可能一封都沒出去而沒有人知道。
                        #   🔑 兩害相權：**保留標記（不重寄）＋ 記一筆讓人看得見。**
                        #   📌 不確定時選「**會被看見**」的那一側，
                        #      不是選「會自動處理」的那一側。
                        #
                        # ⚠️ **落點裡的類別要分開**（`outcome` 原樣寫進去）——
                        # ☠️ 合併的話，「我不知道這封有沒有出去」會被當成
                        # 「那個人沒填 email」處理，**而那封信的狀態永遠不會被查清**。
                        _record_reminder_failure(doc_type, doc_no, highest,
                                                 outcome)
                    elif outcome != _SEND_SENT:
                        # `transient_fail`（SMTP 抖了）或 `skipped`
                        # （這台機器刻意不寄）⇒ **什麼都不記，明天再試**。
                        # ⚠️ 站內通知也一起延後：它跟標記綁在一起，
                        # 否則重試的每一天都會再產生一則站內通知。
                        continue

                    # ⚠️ **欠的低階段一併標記**（WA6）：不標的話下一次排程
                    # 會把它們補寄一遍，使用者同一天收到四封。
                    for st in owed:
                        _mark(st)
                    notify_targets = (list(set(recipients + superadmins))
                                      if also_superadmin else recipients)
                    for u in notify_targets:
                        _notify(u, "approval_reminder", doc_no, doc_no,
                                f"{doc_type} {doc_no} 已等待簽核 "
                                f"{days_elapsed} 個工作日，敬請儘速處理")
        conn.close()
        _logger.info("Approval reminder check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_approval_reminders failed: %s", exc)


def _prune_request_log(keep_days: int = 90) -> None:
    """清掉 90 天前的操作軌跡（2026-09-14，DB v80）。

    這張表每個人每次操作都寫一列，不設保留期限的話它會變成整個資料庫裡最大的一張，
    備份也跟著變大。90 天的取捨：**足夠回頭查「上個月那筆資料是誰改的」**，又不會
    讓一份本質上是觀測資料的東西無限累積。要調整就改這個參數。

    同時也是隱私上的分寸——逐條行為紀錄留越久，外洩時的代價越大。
    """
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.now() - _td(days=keep_days)).isoformat()
    try:
        conn = get_db()
        cur = conn.execute("DELETE FROM user_request_log WHERE at < ?", (cutoff,))
        conn.commit()
        conn.close()
        if cur.rowcount:
            _logger.info("操作軌跡清理：刪除 %d 筆 %d 天前的紀錄", cur.rowcount, keep_days)
    except Exception as e:
        _logger.warning("_prune_request_log failed: %s", e)



def run_all(prune: bool = False) -> None:
    """每日系統檢查（順序同搬移前）。prune：08:00 那一輪另清理請求紀錄（啟動補跑不清）。"""
    _check_approval_reminders()
    _check_cert_expiry()
    _check_backup_freshness()
    _check_disk_space()
    _check_temp_bloat()
    if prune:
        _prune_request_log()
