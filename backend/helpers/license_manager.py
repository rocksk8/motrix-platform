# -*- coding: utf-8 -*-
"""授權匯入與授權頁的邏輯（T83；SYSTEM-MENU-UX-PROPOSAL 批次「授權匯入」）。

[單位] helper:license_manager    [層] L1    [穩定度] 實作
[公開介面] BACKUP_DIR_NAME, BACKUP_KEEP, MAX_UPLOAD_BYTES, PREVIEW_WEIGHT, RATE_GLOBAL_MAX, RATE_MAX, RATE_WINDOW_S, REJECT_MESSAGES, backup_dir, describe_current, modules_view, normalize_upload, rate_allow, recent_activity, reset_for_tests, run_import
[契約題] tests/test_license_import_2026_11_13.py
[不變式]
  ① **驗章、機器綁定、到期判定一律走 `helpers/licensing`**（`verify_license(blob)`＝`_verify_blob`＝`_open_blob`＋機器指紋＋到期）。本檔不碰簽章、不碰公鑰、
     不碰指紋演算法；只決定「驗過之後怎麼替換檔案」與「怎麼用白話說給人聽」。沒有任何下載私鑰／略過驗證的出口。
  ② **只有 `verify_license(blob)` 回 `reason == "ok"` 的授權才會被換上去**（含永久授權「已過維護期」也不收：匯入的目的是讓系統能用）。
     換上去之後**再讀一次檔案複驗**（走 `verify_license()` 讀檔路徑，不是同一個物件）；複驗不過 ⇒ 自動還原成原本的授權檔（或原本沒有檔就刪掉剛寫的）。
  ③ 替換前**一定先備份**舊檔（`<授權檔資料夾>/license_backups/license_<時間>.key`，留最近 `BACKUP_KEEP` 份）；備份失敗 ⇒ 不替換（寧可不換也不要無法還原）。
     寫入是同資料夾的暫存檔 ＋ `os.replace`（原子）；寫到一半失敗，舊檔原封不動。
  ④ **寫進去的是驗過的那一串**：上傳內容先正規化（去 BOM、去所有空白，只准 base64／base64url 字元），**驗的與存的是同一個字串**
     （`base64.b64decode` 預設會悄悄丟掉非字母表字元；不正規化的話「驗過的」與「存下去的」可能不是同一份）。
  ⑤ 大小上限 `MAX_UPLOAD_BYTES`（授權檔只有幾百個字）；超過一律拒絕、不解析。路由層用串流讀、讀到上限就停（不先整包讀進記憶體）。
  ⑥ 頻率限制：**每個帳號**滑動視窗（`RATE_WINDOW_S` 秒內 `RATE_MAX` 點；正式匯入 1 點、預覽 `PREVIEW_WEIGHT` 點）＋較寬的全域上限 `RATE_GLOBAL_MAX`
     （一個被盜的 session 只鎖得住自己，不會把所有最高管理者都鎖在授權頁外面）；不依 IP——X-Forwarded-For 可偽造，與 `line_login` 同一個取捨。
  ⑦ 需要使用者確認才換的情況（客戶名稱不同／功能變少／到期日變早／永久改年費／測試用授權）：**預覽**回 `warnings`；正式匯入沒帶 `confirm` ⇒ 409，不換。
  ⑧ 同時只有一個匯入在換檔（`_IMPORT_LOCK`，拿不到鎖＝回忙碌，不排隊）。
  ⑨ 所有給人看的字都是白話：不出現簽章、指紋、hash、base64、reason 代碼（機器代碼只在「向供應商申請或換發授權」那一格出現，與授權無法使用頁同一個說法）。
"""
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime

from core import registry as _registry
from helpers import licensing as _lic

logger = logging.getLogger(__name__)

#: 授權檔的上限（位元組）。實際一把授權約 400～1500 位元組；模組清單很長也到不了 32 KB。
MAX_UPLOAD_BYTES = 32 * 1024
#: 頻率限制：每個帳號 `RATE_WINDOW_S` 秒內最多 `RATE_MAX` 點（正式匯入 1 點、預覽 `PREVIEW_WEIGHT` 點）；
#: 全域另有較寬的 `RATE_GLOBAL_MAX` 點。
RATE_WINDOW_S = 600
RATE_MAX = 10
RATE_GLOBAL_MAX = 60
PREVIEW_WEIGHT = 0.5
BACKUP_DIR_NAME = "license_backups"
BACKUP_KEEP = 30

_BLOB_CHARS = re.compile(r"^[A-Za-z0-9+/=_-]+$")
_IMPORT_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_rate_hits = {}            # 帳號 → [(time.monotonic(), 點數)]
_global_hits = []          # [(time.monotonic(), 點數)]
_rate_block_noted = set()  # 這個視窗內已經回報過「被擋」的帳號（"*"＝全域）——稽核只寫第一筆，避免被灌爆

#: 拒絕原因 ⇒ 白話說明（`{expires}`／`{customer}` 由 `_reject` 代入）。系統不會因為任何一種原因更換授權。
REJECT_MESSAGES = {
    "empty":            "沒有收到授權內容。請選擇供應商提供的授權檔。",
    "too_big":          "這個檔案太大，不像是授權檔（授權檔只有幾百個字）。請確認選到的是供應商提供的那一個。",
    "malformed":        "這不是有效的授權檔：內容無法辨識，可能被截斷、被改動，或選錯了檔案。請向供應商重新取得。",
    "bad_signature":    "這份授權沒有通過驗證，可能不是供應商簽發的，或內容被改動過。系統沒有更換任何東西。",
    "machine_mismatch": "這份授權是給另一台電腦的，不能用在這一台。如果這台電腦換過主機板或網卡，請聯絡供應商重新簽發。",
    "machine_unreadable": "目前讀不到這台電腦的識別資訊，沒辦法確認這份授權是不是給這一台的。請稍後再試，仍不行請聯絡供應商。",
    "expired":          "這份授權已經過期（到期日 {expires}），不能使用。請向供應商取得新的授權。",
    "same_as_current":  "這份授權和目前使用中的是同一份，不需要更換。",
    "rate_limited":     "短時間內嘗試太多次，請稍後再試。",
    "busy":             "另一個匯入正在進行，請稍後再試。",
    "backup_failed":    "無法備份目前的授權檔，為了安全起見沒有更換。請確認伺服器的磁碟空間與資料夾權限。",
    "write_failed":     "寫入新授權時失敗，目前的授權沒有被更動。請確認伺服器的磁碟空間與資料夾權限，或聯絡供應商。",
    "verify_after_write_failed": "更換後的最後確認沒有通過，系統已自動還原成原本的授權。請聯絡供應商。",
    "demo":             "示範帳號不能查看或更換授權。",
    "dev_license_not_allowed": "這是「測試用」授權，正式使用的系統不能匯入。請向供應商取得正式授權。",
}

#: reason 代碼 ⇒ HTTP 狀態碼（拒絕時）
_REJECT_HTTP = {"too_big": 413, "rate_limited": 429, "busy": 409, "backup_failed": 500, "write_failed": 500,
                "verify_after_write_failed": 500, "demo": 403, "dev_license_not_allowed": 400}


# ── 頻率限制 ─────────────────────────────────────────────────────────────────

def _prune(hits, t):
    hits[:] = [h for h in hits if t - h[0] < RATE_WINDOW_S]
    return sum(h[1] for h in hits)


def rate_allow(account="", weight=1.0, now=None):
    """記一次嘗試。回 `(允許, 幾秒後可再試, 是否為這個視窗第一次被擋)`。

    兩層：**每個帳號** `RATE_WINDOW_S` 秒內最多 `RATE_MAX` 點（一個被盜的 session 只鎖得住自己，鎖不到其他最高管理者）；
    另有**全域**上限 `RATE_GLOBAL_MAX` 點（寬鬆，只擋「很多帳號一起灌」）。預覽計 `PREVIEW_WEIGHT` 點、正式匯入計 1 點（路由分兩次記）。
    兩層都放行才記；任何一層擋住就一點都不記。"""
    t = time.monotonic() if now is None else now
    acct = str(account or "")
    with _RATE_LOCK:
        mine = _rate_hits.setdefault(acct, [])
        used_acct, used_all = _prune(mine, t), _prune(_global_hits, t)
        for k in [k for k, v in _rate_hits.items() if not v and k != acct]:     # 沒有紀錄的帳號不留（字典不無限長大）
            del _rate_hits[k]
        for key, used, cap, hits in ((acct, used_acct, RATE_MAX, mine), ("*", used_all, RATE_GLOBAL_MAX, _global_hits)):
            if used + weight > cap + 1e-9:
                first = key not in _rate_block_noted
                _rate_block_noted.add(key)
                return False, max(1, int(RATE_WINDOW_S - (t - hits[0][0]))) if hits else 1, first
        mine.append((t, weight))
        _global_hits.append((t, weight))
        _rate_block_noted.discard(acct)
        _rate_block_noted.discard("*")
        return True, 0, False


def reset_for_tests():
    with _RATE_LOCK:
        _rate_hits.clear()
        _global_hits.clear()
        _rate_block_noted.clear()


# ── 上傳內容正規化 ───────────────────────────────────────────────────────────

def normalize_upload(raw):
    """上傳內容（字串或位元組）→ `(單行授權字串, None)` 或 `(None, 原因)`。原因 ∈ empty／too_big／malformed。

    去 BOM、去所有空白（base64 常被折行）；只准 base64／base64url 字元；超過 `MAX_UPLOAD_BYTES` 不解析。"""
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_UPLOAD_BYTES:
            return None, "too_big"
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return None, "malformed"
    if not isinstance(raw, str):
        return None, "malformed"
    if len(raw) > MAX_UPLOAD_BYTES:
        return None, "too_big"
    text = "".join(raw.lstrip("﻿").split())
    if not text:
        return None, "empty"
    if len(text) > MAX_UPLOAD_BYTES:
        return None, "too_big"
    if not _BLOB_CHARS.match(text):
        return None, "malformed"
    return text, None


# ── 白話檢視 ─────────────────────────────────────────────────────────────────

_KIND_LABEL = {
    _lic.LICENSE_KIND_SUBSCRIPTION: "年費授權（到期後系統會暫停使用，續約後恢復）",
    _lic.LICENSE_KIND_PERPETUAL: "永久授權（到期日是維護期結束日；到期後仍可繼續使用，但不再提供更新）",
}


def _days_text(days):
    if not isinstance(days, int):
        return ""
    if days > 0:
        return "還有 %d 天" % days
    if days == 0:
        return "今天到期"
    return "已過 %d 天" % -days


def _module_names():
    """授權用的模組鍵 ⇒ 畫面上的模組名稱（只含這個版本裝了的模組）。"""
    out = {}
    try:
        for m in _registry.module_states():
            out[m.get("license_key") or m["key"]] = m.get("name") or m["key"]
    except Exception:  # noqa: BLE001
        logger.exception("license_manager: 讀模組登錄表失敗")
    return out


def modules_view(mods):
    """授權的 `modules` ⇒ `{all, names, unknown}`。`all`＝全部功能；`unknown`＝這個版本沒裝、無法列名稱的項目數。"""
    if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
        return {"all": False, "names": [], "unknown": 0, "invalid": True}
    if "*" in mods:
        return {"all": True, "names": [], "unknown": 0, "invalid": False}
    known = _module_names()
    names = sorted({known[k] for k in mods if k in known})
    return {"all": False, "names": names, "unknown": len({k for k in mods if k not in known}), "invalid": False}


def _license_view(st):
    """驗章通過的狀態 ⇒ 白話欄位（只在簽章驗過之後呼叫；`customer` 等欄位這時才可信）。"""
    kind = st.get("kind") or _lic.LICENSE_KIND_SUBSCRIPTION
    return {
        "customer": st.get("customer"),
        "expires": st.get("expires"),
        "days_left": st.get("days_left"),
        "days_text": _days_text(st.get("days_left")),
        "kind": kind,
        "kind_label": _KIND_LABEL.get(kind, ""),
        "modules": modules_view(st.get("modules")),
        "test_key": st.get("env") == "dev",
    }


def _reject(reason, http=None, st=None, **extra):
    msg = REJECT_MESSAGES.get(reason, "授權檔無法使用。")
    if "{" in msg:
        msg = msg.format(expires=(st or {}).get("expires") or "—", customer=(st or {}).get("customer") or "—")
    out = {"ok": False, "applied": False, "reason": reason, "message": msg,
           "http": http or _REJECT_HTTP.get(reason, 400)}
    out.update(extra)
    return out


# ── 目前授權的概況（授權頁）──────────────────────────────────────────────────

def backup_dir():
    """備份資料夾：與授權檔同一個資料夾。**呼叫時才算**（測試會換 `LICENSE_PATH`）。"""
    return os.path.join(os.path.dirname(os.path.abspath(_lic.LICENSE_PATH)), BACKUP_DIR_NAME)


def _backup_files():
    d = backup_dir()
    try:
        names = [n for n in os.listdir(d) if n.startswith("license_") and n.endswith(".key")]
    except OSError:
        return []
    return sorted(names, reverse=True)           # 檔名帶時間，字串排序＝時間排序


def _emergency_view(em):
    if not em or not em.get("present"):
        return None
    if em.get("active"):
        return {"active": True, "until": em.get("until"),
                "text": "目前靠「緊急放行通行證」暫時運作，到 %s 為止。請盡快向供應商取得正式的新授權並在這一頁匯入。" % (em.get("until") or "—")}
    return {"active": False, "until": em.get("until"), "text": "伺服器上有一張緊急放行通行證，但目前沒有生效。"}


def describe_current(machine_fn):
    """授權頁要的全部資料（白話；**不含任何簽章／雜湊字樣**）。任何狀況都不丟例外。"""
    status = _lic.verify_license()
    reason = status.get("reason")
    kind = status.get("kind")
    gate = bool(_lic.LICENSE_GATE_ENABLED)
    verified = status.get("customer") is not None        # 簽章驗過之後才有的欄位（`_unverified` 全是 None）
    view = _license_view(status) if verified else None

    reminder = _lic.expiry_reminder(status) if gate else None
    if reason == "ok":
        if reminder:
            level = {"notice": "notice", "warning": "warning", "critical": "critical"}.get(reminder["level"], "notice")
            headline = "授權快到期了（%s）" % _days_text(status.get("days_left"))
            detail = "請儘早向供應商取得續約的新授權檔，再到下方匯入。匯入前系統會自動備份現有的授權。"
        else:
            level, headline, detail = "ok", "授權有效", ""
    elif reason == "expired" and kind == _lic.LICENSE_KIND_PERPETUAL:
        level, headline = "notice", "維護期已結束"
        detail = "系統仍可繼續使用，但不再提供更新。需要更新請向供應商取得新的授權檔，再到下方匯入。"
    elif reason == "expired":
        level, headline = "bad", "授權已到期，系統暫停使用"
        detail = "請向供應商續約取得新的授權檔，再到下方匯入。您的資料都還在。"
    elif reason == "machine_mismatch":
        level, headline = "bad", "目前的授權不是給這台電腦的"
        detail = "常見原因是伺服器換過主機板或網卡。請把下方的「機器代碼」提供給供應商重新簽發，拿到新授權檔後在下方匯入。"
    elif reason == "missing":
        level, headline = "bad", "這台電腦還沒有安裝授權"
        detail = "請向供應商取得授權檔（申請時需要下方的「機器代碼」），再到下方匯入。"
    else:                                                   # malformed／bad_signature
        level, headline = "bad", "目前的授權檔無法使用"
        detail = "授權檔可能損毀或被改動。請向供應商重新取得，再到下方匯入。"
    if not gate:
        level, headline, detail = "info", "授權檢查目前沒有啟用", "系統不會因授權而限制使用；下方仍可匯入並檢視授權。"

    if reason in ("ok", "expired"):
        machine_text = "已綁定這台電腦"
    elif reason == "machine_mismatch":
        machine_text = "綁定的不是這台電腦"
    else:
        machine_text = "—"

    try:
        machine = machine_fn()
    except Exception:  # noqa: BLE001
        machine = None
    try:
        em = _emergency_view(_lic.emergency_status(status))
    except Exception:  # noqa: BLE001
        em = None
    try:
        unloaded = [m.get("name") or m["key"] for m in _registry.module_states() if m.get("state") == _registry.STATE_UNLICENSED]
    except Exception:  # noqa: BLE001
        unloaded = []
    backups = _backup_files()
    latest = None
    if backups:
        try:
            latest = datetime.strptime(backups[0][len("license_"):-len(".key")], "%Y%m%d_%H%M%S_%f").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            latest = None

    return {
        "level": level, "headline": headline, "detail": detail, "state": reason,
        "gate_enabled": gate,
        "license": view,
        "machine_text": machine_text,
        "machine_code": machine,
        "emergency": em,
        "reminder": ({"days": reminder["days"], "level": reminder["level"]} if reminder else None),
        "modules_not_loaded": sorted(unloaded),
        "backup_count": len(backups), "backup_latest": latest,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


def recent_activity(conn, limit=5):
    """最近的匯入紀錄（稽核表）⇒ 白話清單。`conn` 由呼叫端開關。"""
    import json
    rows = conn.execute(
        "SELECT at, display_name, action, detail FROM audit_log WHERE action IN ('license.import','license.import_rejected')"
        " ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["detail"] or "{}")
        except ValueError:
            d = {}
        if r["action"] == "license.import":
            what = "匯入新授權成功" + ("（客戶：%s，到期日：%s）" % (d.get("customer") or "—", d.get("expires") or "—"))
        else:
            what = "匯入失敗：" + REJECT_MESSAGES.get(d.get("reason"), "授權檔無法使用").replace("{expires}", d.get("expires") or "—")
        out.append({"at": (r["at"] or "")[:16].replace("T", " "), "who": r["display_name"] or "—", "what": what})
    return out


def _prod_key_installed():
    """正式公鑰是否已經內建（`_PUBKEY_PROD` 非空）。"""
    return bool(getattr(_lic, "_PUBKEY_PROD", b""))


# ── 比對（新授權 vs 目前授權）────────────────────────────────────────────────

def _read_current_text():
    try:
        with open(_lic.LICENSE_PATH, "r", encoding="utf-8") as fh:
            raw = fh.read(MAX_UPLOAD_BYTES * 4 + 1)
    except (OSError, UnicodeDecodeError):
        return None
    text, why = normalize_upload(raw) if len(raw) <= MAX_UPLOAD_BYTES * 4 else (None, "too_big")
    return text if why is None else None


def _module_effects(new_status):
    """新授權換上去、重啟服務之後的模組變化 ⇒ `(會多出來的模組名, 會被停用的模組名)`。
    用載入器同一個判斷（`module_licensed`），不另外比對清單。管理者自己停用的、載入失敗的不在這裡講。"""
    gain, lose = [], []
    try:
        for m in _registry.module_states():
            if m.get("state") not in (_registry.STATE_LOADED, _registry.STATE_UNLICENSED):
                continue
            ok, _why = _lic.module_licensed({"key": m["key"], "license_key": m.get("license_key")}, new_status, True)
            name = m.get("name") or m["key"]
            if m["state"] == _registry.STATE_UNLICENSED and ok:
                gain.append(name)
            elif m["state"] == _registry.STATE_LOADED and not ok:
                lose.append(name)
    except Exception:  # noqa: BLE001
        logger.exception("license_manager: 計算模組變化失敗")
    return sorted(gain), sorted(lose)


def _warnings(cur, new, lose):
    """需要使用者確認的差異（`cur` 是目前授權的狀態；簽章沒驗過〔customer 為 None〕就不比）。"""
    out = []
    if new.get("env") == "dev":
        out.append("這是「測試用」授權（開發用金鑰簽發），不是正式授權。正式使用請向供應商取得正式授權。")
    if cur.get("customer") is None:
        return out
    if cur.get("customer") != new.get("customer"):
        out.append("客戶名稱和目前的授權不同（目前：%s；新的：%s）。" % (cur.get("customer"), new.get("customer")))
    if lose:
        out.append("新授權沒有包含目前正在使用的功能，重啟服務後這些功能會停用：%s。" % "、".join(lose))
    cd, nd = cur.get("days_left"), new.get("days_left")
    if isinstance(cd, int) and isinstance(nd, int) and nd < cd:
        out.append("新授權的到期日（%s）比目前的（%s）還早。" % (new.get("expires"), cur.get("expires")))
    if cur.get("kind") == _lic.LICENSE_KIND_PERPETUAL and new.get("kind") != _lic.LICENSE_KIND_PERPETUAL:
        out.append("目前是永久授權，新授權是年費授權（到期後系統會暫停使用）。")
    return out


# ── 換檔 ─────────────────────────────────────────────────────────────────────

def _clear_caches():
    _lic._LICENSE_FILE_CACHE = None
    _lic._EMERGENCY_CACHE = None


def _prune_backups(d):
    files = _backup_files()
    for n in files[BACKUP_KEEP:]:                      # 新的在前；超過保留份數的舊備份刪掉
        try:
            os.remove(os.path.join(d, n))
        except OSError:
            logger.warning("license_manager: 刪除舊備份失敗：%s", n)


def _backup_current(path):
    """備份現有授權檔 ⇒ 備份檔路徑；沒有現有檔 ⇒ None；失敗丟 OSError。"""
    if not os.path.isfile(path):
        return None
    d = backup_dir()
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "license_%s.key" % datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    shutil.copy2(path, dst)
    if os.path.getsize(dst) != os.path.getsize(path):
        os.remove(dst)
        raise OSError("備份檔大小與原檔不符")
    _prune_backups(d)
    return dst


def _atomic_write(path, text):
    """寫同資料夾暫存檔再 `os.replace`（原子）。Windows 上目標若剛好被讀取中會 PermissionError ⇒ 短暫重試。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".import-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        for i in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 5:
                    raise
                time.sleep(0.1 * (i + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _restore(path, backup):
    """複驗失敗時還原：原本有檔 ⇒ 用備份檔**原樣位元組**換回去；原本沒有 ⇒ 刪掉剛寫的。"""
    try:
        if backup is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            tmp = path + ".restore-tmp"
            shutil.copyfile(backup, tmp)
            os.replace(tmp, path)
    except OSError:
        logger.exception("license_manager: 還原授權檔失敗（%s）——請人工檢查，備份在 %s", path, backup_dir())
    _clear_caches()


def run_import(raw, *, apply, confirm, machine_fn):
    """預覽或匯入一份授權檔。回 dict：`ok`／`applied`／`reason`／`message`／`http`（HTTP 狀態碼）＋明細。**不丟例外。**

    `apply=False` ⇒ 只驗證並回預覽（不寫任何東西）；`apply=True` ⇒ 驗證通過才換（有 `warnings` 又沒 `confirm` ⇒ 409）。
    頻率限制由呼叫端（路由）先做——要在讀上傳內容之前。"""
    try:
        return _run_import(raw, apply=bool(apply), confirm=bool(confirm), machine_fn=machine_fn)
    except Exception:  # noqa: BLE001 — 授權頁不可以因此 500 又不知道原因；換檔的每一步都已各自處理，這裡只是最後一道網
        logger.exception("license_manager: 匯入發生未預期的錯誤")
        return _reject("write_failed")


def _with(info, **fields):
    """結果 dict ＝ 明列的欄位 ＋ 預覽明細（`info` 的欄位在後，同名以明細為準）。"""
    out = dict(fields)
    out.update(info)
    return out


def _run_import(raw, *, apply, confirm, machine_fn):
    text, why = normalize_upload(raw)
    if text is None:
        return _reject(why)

    if apply and not _IMPORT_LOCK.acquire(blocking=False):
        return _reject("busy")
    try:
        new = _lic.verify_license(text)                    # ← 唯一的驗章／機器綁定／到期判定
        reason = new.get("reason")
        if reason != "ok":
            if reason == "machine_mismatch":
                try:
                    unreadable = machine_fn() is None
                except Exception:  # noqa: BLE001
                    unreadable = True
                if unreadable:
                    return _reject("machine_unreadable")
            # 簽章驗過之後的欄位才可信（客戶、到期日）；沒驗過的 `_unverified` 這些都是 None
            return _reject(reason if reason in REJECT_MESSAGES else "malformed", st=new,
                           license=_license_view(new) if new.get("customer") is not None else None)

        if new.get("env") == "dev" and _prod_key_installed():
            # 正式公鑰已經裝上的機器：開發金鑰簽的授權（誰都拿得到開發私鑰）一律不收，也沒有「確認後仍要換」的出口。
            return _reject("dev_license_not_allowed", license=_license_view(new))
        if _read_current_text() == text:
            return _reject("same_as_current", license=_license_view(new))

        cur = _lic.verify_license()
        gain, lose = _module_effects(new)
        warnings = _warnings(cur, new, lose)
        info = {"license": _license_view(new), "warnings": warnings, "modules_after_restart": {"gain": gain, "lose": lose}}

        if not apply:
            return _with(info, ok=True, applied=False, reason="preview", http=200,
                         message="這份授權可以使用。確認內容無誤後，按「確認更換」才會正式換上。")
        if warnings and not confirm:
            return _with(info, ok=False, applied=False, reason="needs_confirm", http=409,
                         message="這份授權和目前的有差異，請確認後再更換。")

        path = _lic.LICENSE_PATH
        try:
            backup = _backup_current(path)
        except OSError:
            logger.exception("license_manager: 備份目前授權失敗")
            return _reject("backup_failed")
        try:
            _atomic_write(path, text)
        except OSError:
            logger.exception("license_manager: 寫入新授權失敗")
            _clear_caches()
            return _reject("write_failed")
        # 從這一行起新檔已經換上去：之後**任何**例外（複驗丟例外、記憶體不足、…）都要先還原再往外丟，
        # 不可以留下「換了一半、沒複驗」的檔案（L2）。
        try:
            _clear_caches()
            after = _lic.verify_license()                  # 讀檔路徑複驗
            if after.get("reason") != "ok" or after.get("customer") != new.get("customer") or after.get("expires") != new.get("expires"):
                logger.error("license_manager: 換檔後複驗不通過（%s），還原", after.get("reason"))
                _restore(path, backup)
                return _reject("verify_after_write_failed")
            restart = bool(gain or lose)
            return _with(info, ok=True, applied=True, reason="applied", http=200,
                         backup=os.path.basename(backup) if backup else None,
                         restart_needed=restart,
                         message="已更換成新的授權。" + ("要讓功能的增減生效，需要重新啟動服務。" if restart else "馬上生效，不需要重新啟動。"))
        except Exception:  # noqa: BLE001
            logger.exception("license_manager: 換檔後的步驟發生未預期的錯誤，還原成原本的授權")
            _restore(path, backup)
            return _reject("verify_after_write_failed")
    finally:
        if apply:
            _IMPORT_LOCK.release()
