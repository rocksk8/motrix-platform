# -*- coding: utf-8 -*-
"""LINE「綁定狀況」與「提醒未綁定的人」（2026-11-13；PM：系統選單改版「開始使用」第 6 步要用）。

[單位] helper:line_binding    [層] L1    [穩定度] 實作
[公開介面] REMIND_MIN_HOURS, REMIND_KEY, remind, status
[契約題] tests/test_line_events_all_2026_11_13.py
[不變式]
  ① **只有最高管理者看得到／按得動**（端點層擋；本檔不認人，呼叫端負責）。
  ② `status()` 只回「在職（active=1）」帳號的 {帳號, 顯示名, 角色, 是否綁定, 綁定時間, 是否有 Email}；**不含 LINE userId、不含 Email 內容**（只回「有沒有」）。
  ③ `remind()` 只提醒「在職且尚未綁定」的人；呼叫端可指定名單，但名單裡已綁定／離職／不存在的帳號會被略過（不會對已綁定的人發提醒）。
     通道＝站內通知＋Email（LINE 對還沒綁定的人推不到）；Email 走既有「使用者額外通知」類型（`user_notice`）：矩陣關閉、本人退訂、沒有 Email ⇒ 只發站內通知，並如實回報人數。
  ④ **同一個人 24 小時內只提醒一次**（`REMIND_MIN_HOURS`；記在 `system_settings.line_bind_remind`），連按兩次按鈕不會洗版；被略過的人數回報給呼叫端。
  ⑤ LINE 登入（綁定用的 channel）還沒設好 ⇒ `ValueError`（人家想綁也綁不了，提醒只會製造困惑）。
  ⑥ 永不寫稽核／不處理授權（端點負責）；信件寄送是背景執行緒，失敗只記 log，不影響站內通知。
"""
import logging
import threading
from datetime import datetime, timedelta

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

#: 同一個人兩次提醒之間至少間隔的小時數
REMIND_MIN_HOURS = 24
#: 已提醒時間的記號鑰匙 `{username: ISO 時間}`
REMIND_KEY = "line_bind_remind"

_NOTICE_KEY = "user_notice"          # Email 借用的信件類型（「使用者額外通知」）
_PAGE = "my-account.html?tab=notify"   # 2026-11-13 使用者裁示：綁定卡片搬到「我的帳號」的「通知」分頁（hichan-1 的頁面）
_TITLE = "請綁定您的 LINE 通知"
_TEXT = ("公司已啟用 LINE 通知。請登入系統，點下方連結，在頁面中找到「LINE 通知」卡片，按「綁定 LINE」，"
         "用手機掃描畫面上的 QR 並按「同意」（約 1 分鐘）。綁定後，簽核、指派等通知也會推播到您的 LINE。")


def _users() -> list:
    from db import get_db
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, username, display_name, role, email, notification_muted, modules FROM users WHERE active=1 ORDER BY role, display_name, username").fetchall()]
    finally:
        conn.close()


def _login_ready() -> bool:
    from . import line_notify as _ln
    cid, sec = _ln.login_credentials()
    return bool(cid and sec and _ln.callback_url())


def status() -> dict:
    """在職人員的綁定狀況（給最高管理者的 LINE 設定頁）。
    ⇒ {available: LINE 登入已設好, total, linked, unlinked, users: [{username, display, role, linked, linkedAt, confirmed, hasEmail, lastReminded}]}"""
    from . import line_notify as _ln
    marks = _get_setting(REMIND_KEY, {}) or {}
    marks = marks if isinstance(marks, dict) else {}
    out = []
    from db import get_db
    from .auth import effective_modules
    _c = get_db()
    try:
        _users_rows = _users()
        _mods = {u["username"]: effective_modules(u["role"], u.get("modules"), user_id=u["id"], conn=_c) for u in _users_rows}
    finally:
        _c.close()
    for u in _users_rows:
        b = _ln.binding_view(u["username"])
        out.append({"username": u["username"], "display": u["display_name"] or u["username"], "role": u["role"],
                    "linked": b["linked"], "linkedAt": b["linkedAt"], "confirmed": b["confirmed"],
                    "hasEmail": bool((u.get("email") or "").strip()), "lastReminded": str(marks.get(u["username"]) or ""),
                    "modules": _mods.get(u["username"], [])})   # 給「誰要發」的人員選單依事件所屬模組過濾（最高管理者專用的頁面；伺服器端 set_audience 仍會再檢查）
    n_linked = sum(1 for x in out if x["linked"])
    return {"available": _login_ready(), "total": len(out), "linked": n_linked, "unlinked": len(out) - n_linked, "users": out}


_remind_lock = threading.Lock()


def remind(usernames=None, now: datetime = None) -> dict:
    """提醒未綁定的人去綁定：每人一則站內通知，並（公司沒關這類信件、本人有 Email 且沒關閉）排入寄信。
    `usernames`＝None ⇒ 所有在職且未綁定的人；給名單 ⇒ 名單內符合條件的人。**同一時間只跑一個**（鎖：連按兩次或兩位管理員同時按，第二個等第一個做完，
    再看記號——不會對同一個人發兩次）；**每個人發完就立刻存「已提醒」記號**（中途例外或程序中斷後重跑，已提醒的人不會再收到）。
    ⇒ {targets: 符合條件的人數, notified: 發了站內通知（本次新發）, emailed: 已排入寄信（非同步，不代表已送達）,
       noEmail: 沒有可寄的 Email（沒填、本人關閉、或排入寄信時失敗）, emailOff: 公司關閉了這類信件（此時 Email 一律不寄、也不計入 noEmail）,
       failed: 站內通知寫入失敗的人數（不記記號、下次會再試）,
       skippedRecent: [`REMIND_MIN_HOURS` 小時內已提醒過的帳號], ignored: [名單內不符合條件（已綁定／離職／不存在）的帳號]}"""
    from . import email_notify as EN
    from . import line_notify as _ln, mail_types as MT, notification_prefs as NP
    from .audit import _notify
    if not _login_ready():
        raise ValueError("還沒設定好 LINE 登入與對外網址，同仁目前無法自行綁定；請先完成上方設定")
    if usernames is not None and (not isinstance(usernames, (list, tuple)) or not all(isinstance(u, str) for u in usernames)):
        raise ValueError("usernames 必須是帳號清單")
    with _remind_lock:
        now = now or datetime.now()
        everyone = {u["username"]: u for u in _users()}
        wanted = list(dict.fromkeys(usernames)) if usernames is not None else list(everyone)
        ignored = [w for w in wanted if w not in everyone or _ln.is_linked(w)]
        targets = [w for w in wanted if w in everyone and not _ln.is_linked(w)]
        marks = _get_setting(REMIND_KEY, {}) or {}                 # 在鎖裡才讀：前一個呼叫剛寫的記號一定看得到
        marks = {k: v for k, v in marks.items() if k in everyone} if isinstance(marks, dict) else {}      # 順手清掉離職／刪除帳號的記號
        cutoff = now - timedelta(hours=REMIND_MIN_HOURS)
        res = {"targets": len(targets), "notified": 0, "emailed": 0, "noEmail": 0, "emailOff": False, "failed": 0,
               "skippedRecent": [], "ignored": ignored}
        mail_off = EN._mail_off(_NOTICE_KEY)
        res["emailOff"] = bool(mail_off)
        link = "%s/pages/%s" % (EN._base_url(), _PAGE)
        for name in targets:
            try:
                last = datetime.fromisoformat(str(marks.get(name))) if marks.get(name) else None
            except ValueError:
                last = None
            if last is not None and last > cutoff:
                res["skippedRecent"].append(name)
                continue
            try:
                _notify(name, "line_binding_reminder", "line-bind", "LINE 通知綁定", _TEXT, link=_PAGE)
            except Exception as exc:                # noqa: BLE001  一個人失敗不影響其他人；沒記號⇒下次會再試
                logger.warning("line_binding.remind: 站內通知失敗：%s", type(exc).__name__)
                res["failed"] += 1
                continue
            res["notified"] += 1
            marks[name] = now.isoformat(timespec="seconds")
            try:
                _set_setting(REMIND_KEY, dict(marks))          # 每人發完就存（中途出事不會重發）
            except Exception as exc:                # noqa: BLE001
                logger.warning("line_binding.remind: 提醒記號寫入失敗：%s", type(exc).__name__)
            if mail_off:
                continue
            u = everyone[name]
            addr = (u.get("email") or "").strip()
            if not addr or not NP.is_enabled(u.get("notification_muted"), _NOTICE_KEY):
                res["noEmail"] += 1
                continue
            try:
                html = EN._build_html(_NOTICE_KEY, _TITLE, "請綁定", "#2563EB", [], "", link, intro=_TEXT, button_text="前往綁定")
                EN._async_send([addr], MT.subject(_NOTICE_KEY, _TITLE), html)
                res["emailed"] += 1
            except Exception as exc:                # 信件失敗不影響站內通知與其他人
                logger.warning("line_binding.remind: 寄信失敗：%s", type(exc).__name__)
                res["noEmail"] += 1
        return res
