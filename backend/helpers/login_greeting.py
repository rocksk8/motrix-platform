# -*- coding: utf-8 -*-
"""登入問候語（首頁大標題下的一句話）：登入紀錄、風格、情境挑選、句庫自訂。

[單位] helper:login_greeting    [層] L1    [穩定度] 實驗
[公開介面] record_login(user_id)、build_greeting(...)、greeting_for_user(...)、company_style()、effective_style(...)、
          set_personal_style(user_id, v)、get_custom()、set_custom(cat, style, lines)、phrases_table()、taipei_now()
[不變式] 設計見 docs/platform/plans/UX-BUSINESS-PAGES-PROPOSAL.md §3.1.2（使用者 2026-11-13 已裁示）。
    1. **所有判斷在伺服器端**，單一端點（GET /api/auth/greeting）回「標題＋問候句＋離開期間摘要＋待辦句」；前端只顯示。
       時間一律台北時間（Asia/Taipei；環境沒有時區資料庫時退回固定 UTC+8——台灣沒有夏令時間，兩者相同）。
    2. **優先順序（高→低）**：第一次登入 > 節慶 > 久未登入 > 星期 > 月初／月底 > 季節（梅雨、夏、冬）> 時段。
       同類別有多句時「同一人同一天固定、隔天輪替」（不用純隨機：重新整理不會換句，測試也穩）。
    3. **久未登入**＝「本次登入前的上一次」距今天數：3～6／7～13／14～29／30～89／90 以上五級；**同一天第二次登入不觸發**；
       資料用伺服器記錄（system_settings 的 `login_state.<使用者編號>`，不用 localStorage）。
       只有「**登入當天**」才出現（session 最長 30 天，不能因為隔天開首頁就說他久未登入）。
       3～6 天這一級要真的**漏了上班日**才算（週五到週一是正常節奏，不顯示；連假後第一個上班日用專用句 post_holiday）。
       **兩種風格都附「離開期間摘要」**（待簽核幾張；最高管理者另附新增報價單幾張）——這是真正有用的資訊。
    4. **第一次登入**＝該帳號的第一筆登入紀錄；歡迎句＋「開始使用」按鈕（hichan-1 的我的帳號頁）。
       舊帳號沒有本檔的紀錄時，用稽核紀錄 `auth.login` 的最後一筆回填上一次登入——升版不會讓所有人都變成「第一次登入」。
    5. **風格**：公司設定（設定中心「登入問候語」）關閉／溫和正式（新安裝預設）／輕鬆幽默；公司選「關閉」＝全公司都關；
       公司開著時，個人可自選「跟隨公司／溫和正式／輕鬆幽默／關閉」（存在自己的登入紀錄裡）。
    6. **全部可自訂**：每個類別＋風格可由最高管理者改寫或新增（整組取代該類別該風格的內建句；清空＝回內建）。
       自訂句與內建句**同一個內容守則**（greeting_phrases.check_phrase）。
    7. 登入紀錄寫入**永不讓登入失敗**（例外只記 log）。
[契約題] tests/test_login_greeting_2026_11_13.py
"""
import json
import logging
import random
from datetime import date, datetime, timedelta, timezone

from helpers import greeting_phrases as GP
from helpers import greeting_calendar as GC

log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Taipei")
except Exception:  # noqa: BLE001  Windows 沒裝 tzdata 時
    TZ = timezone(timedelta(hours=8))

STYLE_OFF, STYLE_FORMAL, STYLE_HUMOR = 0, 1, 2
PERSONAL_STYLES = ("follow", "formal", "humor", "off")
STATE_PREFIX = "login_state."
CUSTOM_KEY = "login_greeting.phrases"
#: 第一次登入的「開始使用」去處（hichan-1 的我的帳號頁；頁面隨選單 UX 批次上線）
START_HREF = "pages/my-account.html?tab=security"
START_LABEL = "開始使用"


def taipei_now() -> datetime:
    return datetime.now(TZ)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _parse(s):
    try:
        return _aware(datetime.fromisoformat(str(s)))
    except Exception:  # noqa: BLE001
        return None


# ── 登入紀錄 ────────────────────────────────────────────────────────────────
def _get(key, default=None):
    from helpers.settings import _get_setting
    return _get_setting(key, default)


def _set(key, value):
    from helpers.settings import _set_setting
    _set_setting(key, value)


def get_state(user_id) -> dict:
    st = _get(STATE_PREFIX + str(user_id), None)
    return st if isinstance(st, dict) else {}


def _last_audit_login(user_id):
    """舊帳號回填：稽核紀錄裡這個人最後一次 `auth.login`（找不到回 None）。"""
    try:
        from db import get_db
        conn = get_db()
        try:
            row = conn.execute("SELECT at FROM audit_log WHERE action='auth.login' AND user_id=? ORDER BY id DESC LIMIT 1",
                               (user_id,)).fetchone()
        finally:
            conn.close()
        return _parse(row["at"]) if row else None
    except Exception:  # noqa: BLE001
        return None


def record_login(user_id, now=None) -> None:
    """登入成功時呼叫（`_issue_session`，在寫稽核之前）。永不丟例外。"""
    try:
        now = _aware(now) if now else taipei_now()
        st = get_state(user_id)
        if not st:
            back = _last_audit_login(user_id)
            st = {"last": back.isoformat() if back else None, "n": 1 if back else 0}
        new = {"prev": st.get("last"), "last": now.isoformat(), "n": int(st.get("n") or 0) + 1}
        _set(STATE_PREFIX + str(user_id), new)
    except Exception:  # noqa: BLE001
        log.warning("login_greeting.record_login failed (user %s)", user_id, exc_info=True)


#: 個人偏好值（helpers/user_prefs 的 login_greeting；hichan-1 的「我的帳號」偏好頁負責畫面與寫入）→ 這裡的風格名
_PREF_MAP = {"follow_company": "follow", "formal": "formal", "humor": "humor", "off": "off"}


def personal_pref(user_id) -> str:
    """個人自選：'follow'（跟隨公司）／'formal'／'humor'／'off'。user_prefs 不在或讀不到 ⇒ 'follow'（問候語是加值，不可因此壞掉）。"""
    try:
        from helpers import user_prefs
        return _PREF_MAP.get(user_prefs.get(int(user_id), "login_greeting"), "follow")
    except Exception:  # noqa: BLE001
        return "follow"


# ── 風格 ───────────────────────────────────────────────────────────────────
def company_style() -> int:
    try:
        from helpers import settings_registry as sr
        v = (sr.get_group("login_greeting") or {}).get("style")
        if v in (STYLE_OFF, STYLE_FORMAL, STYLE_HUMOR) and not isinstance(v, bool):
            return int(v)
    except Exception:  # noqa: BLE001
        pass
    return STYLE_FORMAL


def effective_style(company: int, pref) -> str:
    """'formal' | 'humor' | 'off'。公司關閉＝全關；否則個人自選優先。"""
    if company == STYLE_OFF:
        return "off"
    base = "humor" if company == STYLE_HUMOR else "formal"
    return pref if pref in ("formal", "humor", "off") else base


# ── 句庫（內建＋自訂） ──────────────────────────────────────────────────────
def get_custom() -> dict:
    v = _get(CUSTOM_KEY, {})
    return v if isinstance(v, dict) else {}


def _lines(custom: dict, cat: str, style: str) -> list:
    """自訂優先（只收通過內容守則的句子；整組都不合格就回內建）。"""
    row = custom.get(cat) if isinstance(custom, dict) else None
    mine = row.get(style) if isinstance(row, dict) else None
    if isinstance(mine, list):
        good = [t.strip() for t in mine if isinstance(t, str) and not GP.check_phrase(t)]
        if good:
            return good
    return list(GP.BUILTIN.get(cat, {}).get(style) or [])


def set_custom(cat: str, style: str, lines: list) -> list:
    """存某類別某風格的自訂句；`lines` 空＝回內建。不合法 ⇒ ValueError（白話）。"""
    if cat not in GP.BUILTIN:
        raise ValueError("沒有這個類別")
    if style not in ("formal", "humor"):
        raise ValueError("風格只能是 溫和正式（formal）或 輕鬆幽默（humor）")
    if not isinstance(lines, list):
        raise ValueError("句子要用清單")
    clean = [t.strip() for t in lines if isinstance(t, str) and t.strip()]
    if len(clean) > GP.MAX_LINES:
        raise ValueError("每個類別最多 %d 句" % GP.MAX_LINES)
    for t in clean:
        msg = GP.check_phrase(t)
        if msg:
            raise ValueError("「%s」：%s" % (t[:20], msg))
    cur = dict(get_custom())
    row = dict(cur.get(cat) or {})
    if clean:
        row[style] = clean
    else:
        row.pop(style, None)
    if row:
        cur[cat] = row
    else:
        cur.pop(cat, None)
    _set(CUSTOM_KEY, cur)
    return clean


def phrases_table() -> list:
    """給設定畫面：每個類別的名稱、內建句、目前自訂句。"""
    cur = get_custom()
    out = []
    for cat, v in GP.BUILTIN.items():
        out.append({"category": cat, "label": GP.CATEGORY_LABELS.get(cat, cat),
                    "formal": {"builtin": v.get("formal", []), "custom": (cur.get(cat) or {}).get("formal") or []},
                    "humor": {"builtin": v.get("humor", []), "custom": (cur.get(cat) or {}).get("humor") or []}})
    return out


# ── 情境挑選（純函式）──────────────────────────────────────────────────────
def _months_last_day(d: date) -> int:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def away_category(prev_date, today: date):
    """依「上一次登入日」到今天的天數回類別鍵；沒有要顯示的回 None（見檔頭第 3 點）。"""
    if prev_date is None:
        return None
    gap = (today - prev_date).days
    if gap >= 90:
        return "away_90"
    if gap >= 30:
        return "away_30"
    if gap >= 14:
        return "away_14"
    if gap >= 7:
        return "away_7"
    if gap < 3:
        return None
    from helpers.business_days import is_working_day
    between = [prev_date + timedelta(days=i) for i in range(1, gap)]
    if any(is_working_day(x) for x in between):
        return "away_3"                                  # 真的漏了上班日
    # 中間全是非上班日（週末／連假）：只有「連假後第一個上班日」才說話；單純的週末不算久未登入
    holiday_between = any(x.weekday() < 5 for x in between)
    return "post_holiday" if (holiday_between and is_working_day(today)) else None


def season_category(d: date):
    md = (d.month, d.day)
    if (5, 15) <= md <= (6, 15):
        return "plum_rain"
    if (6, 16) <= md <= (8, 31):
        return "summer"
    if d.month in (12, 1, 2):
        return "winter"
    return None


def time_category(hour: int) -> str:
    if 5 <= hour < 11:
        return "time_morning"
    if 11 <= hour < 13:
        return "time_noon"
    if 13 <= hour < 18:
        return "time_afternoon"
    if 18 <= hour < 22:
        return "time_evening"
    return "time_late"


def title_category(hour: int) -> str:
    """與首頁原本一致：5～11 早安、11～18 午安，其餘（含凌晨）晚安。"""
    return "title_morning" if 5 <= hour < 11 else ("title_afternoon" if 11 <= hour < 18 else "title_evening")


def choose_category(now: datetime, *, first: bool, logged_today: bool, prev_date) -> tuple:
    """回 (kind, 類別鍵)。優先順序見檔頭第 2 點。"""
    d = now.date()
    if first and logged_today:
        return "first_login", "first_login"
    fest = GC.festival_keys_on(d)
    if fest:
        return "festival", fest[0]
    if logged_today:
        a = away_category(prev_date, d)
        if a:
            return ("post_holiday" if a == "post_holiday" else "away"), a
    wd = {0: "weekday_mon", 4: "weekday_fri", 5: "weekday_sat", 6: "weekday_sun"}.get(d.weekday())
    if wd:
        return "weekday", wd
    if d.day <= 3:
        return "month_start", "month_start"
    if d.day >= _months_last_day(d) - 1:
        return "month_end", "month_end"
    s = season_category(d)
    if s:
        return "season", s
    return "time", time_category(now.hour)


def _pick(lines: list, seed: str) -> str:
    return random.Random(seed).choice(lines) if lines else ""


def _fill(text: str, name: str, pending, days) -> str:
    return (text.replace("{name}", name or "").replace("{pending}", str(pending if pending is not None else 0))
            .replace("{days}", str(days if days is not None else 0)))


def away_line(pending, new_quotes) -> str:
    parts = []
    if new_quotes:
        parts.append("新增 %d 張報價單" % new_quotes)
    if pending:
        parts.append("%d 張單據等您簽核" % pending)
    return ("離開期間：" + "；".join(parts) + "。") if parts else "離開期間沒有需要您補辦的事項。"


def build_greeting(*, now: datetime, user_id, name: str, style: str, state: dict, custom: dict = None,
                   todo=None, pending=None, new_quotes=None) -> dict:
    """純函式（不碰資料庫）：回單一端點要給前端的內容。`state` 是 get_state() 的結果（含 prev／last／n）。"""
    now = _aware(now).astimezone(TZ)
    base = {"style": style, "kind": "", "category": "", "title": "", "line": "", "awayLine": "", "todoLine": "", "action": None}
    if style == "off":
        base["kind"] = "off"
        return base
    custom = custom or {}
    last = _parse(state.get("last"))
    prev = _parse(state.get("prev"))
    logged_today = bool(last and last.astimezone(TZ).date() == now.date())
    prev_date = prev.astimezone(TZ).date() if prev else None
    first = int(state.get("n") or 0) == 1
    kind, cat = choose_category(now, first=first, logged_today=logged_today, prev_date=prev_date)
    days = (now.date() - prev_date).days if prev_date else 0
    day_seed = "%s|%s" % (user_id, now.date().isoformat())

    tcat = title_category(now.hour)
    resolved = {}

    def val(key, src):                       # pending／new_quotes 可以給數字或函式；函式只在真的用到時才呼叫（省查詢）
        if key not in resolved:
            try:
                resolved[key] = src() if callable(src) else src
            except Exception:  # noqa: BLE001
                log.warning("login_greeting: %s 讀取失敗", key, exc_info=True)
                resolved[key] = None
        return resolved[key]

    def fill(raw):
        return _fill(raw, name, val("pending", pending) if "{pending}" in raw else None, days)

    base["title"] = fill(_pick(_lines(custom, tcat, style), day_seed + tcat))
    base["kind"], base["category"] = kind, cat
    base["line"] = fill(_pick(_lines(custom, cat, style), day_seed + cat))
    if kind == "first_login":
        base["action"] = {"label": START_LABEL, "href": START_HREF}
    if kind in ("away", "post_holiday"):
        base["awayLine"] = away_line(val("pending", pending), val("new_quotes", new_quotes))
    if isinstance(todo, int) and not isinstance(todo, bool):
        tk = "todo_zero" if todo == 0 else ("todo_many" if todo > 10 else "")
        if tk:
            base["todoLine"] = fill(_pick(_lines(custom, tk, style), day_seed + tk))
    return base


def greeting_for_user(user: dict, *, todo=None, pending=None, new_quotes=None, now: datetime = None) -> dict:
    """端點用：讀登入紀錄、公司風格、自訂句庫，然後 build_greeting。"""
    state = get_state(user["id"])
    pref = personal_pref(user["id"])
    style = effective_style(company_style(), pref)
    name = (user.get("display_name") or user.get("username") or "").strip()
    out = build_greeting(now=now or taipei_now(), user_id=user["id"], name=name, style=style, state=state,
                         custom=get_custom(), todo=todo, pending=pending, new_quotes=new_quotes)
    out["pref"] = pref
    out["companyStyle"] = company_style()
    return out
