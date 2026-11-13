"""授權相關的告警：log ＋ 系統稽核（audit_log）。

`helpers/licensing.py` 的契約是「完全離線、不進資料庫」，所以寫稽核的部分放這裡。

四種事件（都**不可以悄悄放過去**；這裡只負責「留紀錄」，畫面上的橫幅走 `X-Motrix-License` 標頭，見 notif.js）：
  · `license.emergency_pass`   靠緊急放行通行證撐著（授權金鑰失效、通行證生效）——ERROR log＋稽核，每個通行證每天一次
  · `license.dev_key`          驗章通過但簽發方是**開發金鑰**（env=dev）——WARNING log＋稽核，每天一次
  · `license.startup_blocked`  啟動時授權就不通過（業務 API 會回 402）——ERROR log＋稽核
  · 授權快到期（T83）：不在這裡去重——每日排程 `system_checks._check_license_expiry` 用「到期日|檔位」旗標控制，
    這裡只負責 `expiry_notice`（寄 `license_expiry` 信；LINE 走登記表）。

去重：同一個代碼同一天只寫一次（行程內節流，同 `company_setup.alert` 的做法）。**「今天已寫」是寫成功之後才標記**
（LG-S2）；寫失敗（資料庫忙到逾時）⇒ 只記 log、不丟例外，過 `_RETRY_AFTER_S` 秒後下一個請求會再試一次，直到寫成功為止。
告警本身壞掉不可以讓請求或服務起不來。

為什麼開發金鑰只警告、不拒絕啟動（評估結果）：
  · `_PUBKEY_PROD` 目前是空的，所有實際簽出來的金鑰都是 env=dev——現在拒絕＝所有人起不來。
  · 開發機、測試本來就用開發金鑰。
  · 警告走三條路（log＋稽核＋每頁橫幅＋ /api/license/status 的 env），不是靜默。
  正式公鑰進 `_PUBKEY_PROD` 之後，要不要把「正式機上 env≠prod」升級成擋住，是一個另外的決定
  （需要先有「這台是正式機」的可靠判斷；目前沒有）。
"""
import json
import logging
import threading
import time
from datetime import datetime

from helpers import licensing as _lic

logger = logging.getLogger(__name__)

#: 代碼 → 行程內節流狀態。測試會清它。值有三種：
#:   `"2026-11-13"`（日期字串）＝今天**已經寫進稽核**；
#:   `("pending", t)`＝正在寫（別的請求不要再開一條）；
#:   `("failed", t)`＝上次寫稽核失敗（庫忙到逾時），`_RETRY_AFTER_S` 秒後允許再試一次。
#: T80稽核 LG-S2：以前「今天已警告」是在**寫稽核之前**就標記的，庫忙到逾時那天的稽核紀錄就永遠補不回來。
_ALERTED = {}
_CLAIM_LOCK = threading.Lock()
_RETRY_AFTER_S = 300.0        # 寫稽核失敗後多久可以再試（庫忙時不要每個請求都開一條 30 秒的寫入執行緒）
_PENDING_STALE_S = 120.0      # 「正在寫」超過這麼久視為卡死（SQLite busy timeout 是 30 秒）

#: 背景寫稽核的執行緒（`flush()` 等它們）。
_PENDING = []
_PENDING_LOCK = threading.Lock()


def _audit(action, detail):
    try:
        # 一律寫**正式庫**（不用 get_db()）：get_db() 看目前請求的 demo 旗標，示範帳號碰巧是當天第一個請求時，
        # 授權告警會寫進示範庫（K 審 S1）。授權是整台機器的事，與誰在操作無關。
        import db
        conn = db._connect(db.DB_PATH)
        try:
            conn.execute(
                "INSERT INTO audit_log (at, user_id, username, display_name, action, target_type, target_id,"
                " target_label, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(), None, "system", "系統", action, "settings", "license", "",
                 json.dumps(detail, ensure_ascii=False)))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("license_alerts: 稽核寫入失敗（%s）", action)
        return False


def _write(code, action, detail):
    """寫一筆稽核並**依結果**結算節流狀態：成功 ⇒ 今天不再寫；失敗 ⇒ 稍後可重試（LG-S2）。不丟例外。"""
    ok = False
    try:
        ok = bool(_audit(action, detail))
    finally:
        _settle(code, ok)


def _emit(action, detail, background, code=None):
    """寫稽核。`background=True`（async 中介層用）⇒ 丟到背景執行緒：`audit_log` 是同步 SQLite 寫入，
    有別的連線握著寫鎖時會卡到 busy timeout（30 秒），在事件迴圈裡寫就是全站一起卡（K 審 S1）。
    啟動檢查與測試用同步寫（預設）。`code`＝節流代碼（`_claim` 領到的那個）；寫完才結算。"""
    if not background:
        _write(code, action, detail)
        return
    th = threading.Thread(target=_write, args=(code, action, detail), name="license-audit", daemon=True)
    with _PENDING_LOCK:
        _PENDING[:] = [x for x in _PENDING if x.is_alive()]
        _PENDING.append(th)
    try:
        th.start()
    except Exception:  # noqa: BLE001   連執行緒都開不起來 ⇒ 放掉領到的名額，下次再試
        _settle(code, False)
        logger.exception("license_alerts: 無法啟動背景稽核執行緒（%s）", action)


def flush(timeout=10.0):
    """等背景稽核寫完（測試與關機前用）。"""
    with _PENDING_LOCK:
        pending = list(_PENDING)
    for th in pending:
        th.join(timeout)


def _claim(code):
    """領「今天要寫這一筆」的名額。今天已寫成功、正有人在寫、或上次失敗還沒到重試時間 ⇒ False。
    領到之後**必須**用 `_settle` 結算（`_write` 會做）：不結算＝名額一直被占著（超過 `_PENDING_STALE_S` 視為卡死）。"""
    today = datetime.now().date().isoformat()
    now = time.monotonic()
    with _CLAIM_LOCK:
        cur = _ALERTED.get(code)
        if cur == today:
            return False
        if isinstance(cur, tuple):
            kind, at = cur
            if kind == "pending" and now - at < _PENDING_STALE_S:
                return False
            if kind == "failed" and now - at < _RETRY_AFTER_S:
                return False
        _ALERTED[code] = ("pending", now)
        return True


def _settle(code, ok):
    if code is None:
        return
    with _CLAIM_LOCK:
        _ALERTED[code] = datetime.now().date().isoformat() if ok else ("failed", time.monotonic())


def emergency_in_use(info, background=False):
    """通行證生效中（`licensing.emergency_pass()` 的回傳）。回是否這次有寫（每個通行證每天一次）。"""
    code = "emergency:" + str(info.get("pass_id")) if info else None
    if not info or not _claim(code):
        return False
    detail = {"pass_id": info.get("pass_id"), "until": info.get("until"), "note": info.get("note", ""),
              "env": info.get("env")}
    logger.error("授權金鑰無法通過驗證，系統靠緊急放行通行證運作（通行證 %s，至 %s）：%s",
                 detail["pass_id"], detail["until"], detail["note"])
    _emit("license.emergency_pass", detail, background, code)
    return True


def dev_key_in_use(status, background=False):
    """驗章通過但簽發方是開發金鑰。回是否這次有寫（每天一次）。"""
    if not (isinstance(status, dict) and status.get("valid") and status.get("env") == "dev"):
        return False
    if not _claim("dev_key"):
        return False
    detail = {"customer": status.get("customer"), "expires": status.get("expires")}
    logger.warning("這台伺服器使用的授權金鑰是開發金鑰簽發的（env=dev）——正式機應使用正式金鑰（客戶 %s）",
                   status.get("customer"))
    _emit("license.dev_key", detail, background, "dev_key")
    return True


def startup_check():
    """啟動時檢查一次（main.py）：授權不通過、靠通行證、或是開發金鑰，都要留紀錄。**不丟例外、不擋啟動。**

    閘門關著 ⇒ 什麼都不做（連 verify_license 都不呼叫）。"""
    try:
        if not _lic.LICENSE_GATE_ENABLED:
            return None
        status = _lic.verify_license()
        if _lic.license_blocks_request(status):
            ep = _lic.emergency_pass(status)
            if ep:
                emergency_in_use(ep)
                return "emergency"
            code = "startup_blocked:" + str(status.get("reason"))
            if _claim(code):
                logger.error("授權檢查不通過（%s）：業務 API 將回 402。%s",
                             status.get("reason"), _lic.license_block_message(status))
                _write(code, "license.startup_blocked", {"reason": status.get("reason"),
                                                         "customer": status.get("customer")})
            return "blocked"
        if dev_key_in_use(status):
            return "dev_key"
        return "ok"
    except Exception:  # noqa: BLE001
        logger.exception("license_alerts: 啟動檢查失敗（服務照常啟動）")
        return None


def expiry_notice(rem, status):
    """寄「授權即將到期」給最高管理者（`license_expiry`；T83）。`rem`＝`licensing.expiry_reminder()`、`status`＝`verify_license()`。

    回傳＝呼叫端可以寫「這個檔位已通知」旗標（寄出／結果不明／永久失敗＝True；沒有收件人、暫時失敗＝False，隔天重試）。
    全白話：不放機器代碼、簽章等字樣。LINE 通道由 `send_registered` 附帶（事件開關與重要程度在 LINE 登記表；沒登記就只有信）。"""
    from helpers import email_notify as _en
    days = rem["days"]
    perpetual = rem.get("kind") == _lic.LICENSE_KIND_PERPETUAL
    if rem["level"] == "ended":
        badge, color = "維護期已結束", "#D97706"
        reason = "系統授權的維護期已於 %s 結束（已過 %d 天）。系統仍可繼續使用，但不再提供更新。" % (rem.get("expires"), -days)
    elif days == 0:
        badge, color = "今天到期", "#DC2626"
        reason = "系統授權將於今天（%s）%s。" % (rem.get("expires"), "結束維護期" if perpetual else "到期")
    else:
        badge, color = "剩 %d 天" % days, ("#DC2626" if days <= _lic.EXPIRY_THRESHOLDS[-1] else "#D97706")
        reason = "系統授權將於 %s %s，剩下 %d 天。" % (rem.get("expires"), "結束維護期" if perpetual else "到期", days)
    rows = [("客戶", status.get("customer") or "—"), ("到期日", rem.get("expires") or "—"),
            ("授權種類", "永久授權（到期日為維護期結束日）" if perpetual else "年費授權")]
    note = ("年費授權到期後，系統會暫停使用，所有人都無法登入操作（資料不會遺失）。" if not perpetual
            else "永久授權過了維護期仍可繼續使用，但不再提供更新。") +         "請向供應商取得新的授權檔，再由最高管理者到系統的「授權」頁匯入；匯入前系統會自動備份目前的授權。"
    out = {}
    ok = _en.send_registered("license_expiry", title="系統授權即將到期", rows=rows, to_group=True, reason=reason,
                             badge_text=badge, badge_color=color, note=note, button_text="前往授權頁",
                             link=_en._base_url() + "/pages/license-settings.html", wait=True, out=out)
    if not ok:
        logger.warning("license_alerts.expiry_notice：沒有寄成（%s），明天會再試", out.get("outcome"))
    return ok
