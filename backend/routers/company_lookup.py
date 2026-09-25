"""L1：伺服器時間與政府開放資料（GCIS）統編／公司名稱查詢（2026-09-26 自 routers/dashboard.py 拆出，M08 搬遷 ②）。

為什麼是 L1：純資料查詢、多個模組在用——客戶（L1 customers.html、static/gov-lookup.js）、採購（M03 suppliers）、
外包（M04 vendor-contractors）；`/api/now` 給報表頁取伺服器時間。放在 M08 的 dashboard 時，拿掉 M08 這些頁的
統編查詢就壞掉（主持裁示：純資料、多模組在用 ⇒ 下沉 L1）。

端點路徑、權限、每日額度的設定鍵（gcis_daily_limit／gcis_daily_usage）都不變；以下內容自 dashboard.py 逐字搬來。
"""
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, date

from fastapi import APIRouter, HTTPException, Header, Query

from helpers import _require_user, _get_setting, _set_setting

router = APIRouter()
logger = logging.getLogger(__name__)

_GCIS_UA = "Mozilla/5.0 (compatible; MOTRIX-ERP/1.0)"

# ── GCIS helpers ──────────────────────────────────────────────────────────────

_GCIS_OK   = "ok"
_GCIS_NONE = "not_found"
_GCIS_ERR  = "network_error"

def _gcis_get(url: str) -> tuple:
    """Returns (data_list, status) where status is _GCIS_OK / _GCIS_NONE / _GCIS_ERR."""
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": _GCIS_UA}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            if not raw or not raw.strip():
                return [], _GCIS_NONE
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list) and data:
                return data, _GCIS_OK
            return [], _GCIS_NONE
    except Exception as exc:
        logger.warning("GCIS lookup failed: %s %s", type(exc).__name__, exc)
        return [], _GCIS_ERR


def _normalize(d: dict) -> dict:
    return {
        "name":   d.get("Company_Name")          or d.get("Business_Name")   or "",
        "taxId":  d.get("Business_Accounting_NO") or "",
        "status": d.get("Company_Status")         or d.get("Business_Status") or "",
    }


#: 每天最多讓使用者查幾次公司資料。**可以從設定改。**
#:
#: ## 🔴 理由不是安全，是**我們是別人服務的用戶**
#: 那是政府開放資料的 API，額度算在**我們的 IP** 上。
#: ☠️ 一個寫壞的前端迴圈就能把當天的額度用完，
#: 而畫面上只會是「**查不到這個統編**」—— 🔑 跟「這家公司真的不存在」
#: 長得一模一樣，而使用者會去改他手上那張紙。
#: 📌 與 OSM 圖磚被擋是同一族：**被對方擋下來的樣子，是我們的資料看起來不見了。**
#:
#: ⚠️ **一次呼叫最多送出兩個請求**（公司行號查不到時會再查商業登記）
#: ⇒ 對 GCIS 的實際上限是這個數字的兩倍。**這裡數的是「使用者查了幾次」**，
#: 因為那才是**可以從畫面理解**的單位，而倍率寫在這裡。
GCIS_DAILY_LIMIT_SETTING = "gcis_daily_limit"
GCIS_DAILY_LIMIT_DEFAULT = 300
#: 今天用掉幾次。**存 DB 不存記憶體** —— `autostart.bat` 是無限迴圈，
#: 存記憶體的話上限實際上會變成「每次重啟最多 N」。
GCIS_USAGE_SETTING = "gcis_daily_usage"


def _gcis_daily_limit() -> int:
    """今天的上限。讀不出數字就用預設值。

    ⚠️ **不可以因為設定壞掉就變成無限** —— 那會讓「設定打錯字」
    與「刻意關掉上限」變成同一件事，而前者沒有人會發現。
    """
    raw = _get_setting(GCIS_DAILY_LIMIT_SETTING, GCIS_DAILY_LIMIT_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("gcis_daily_limit 不是數字（%r），改用預設 %d",
                       raw, GCIS_DAILY_LIMIT_DEFAULT)
        return GCIS_DAILY_LIMIT_DEFAULT
    return value if value >= 0 else GCIS_DAILY_LIMIT_DEFAULT


def _gcis_take_quota() -> None:
    """用掉一次額度；超過就 429。

    📌 **跨呼叫累計並存 DB**：寫成函式裡的變數的話，語意會變成
    「每次呼叫最多 N」，而那**在一天只呼叫一次的時候恰好相等**
    —— 🔑 那是巧合不是設計（今天已經在背景暖快取那邊踩過同一個）。
    """
    today = date.today().isoformat()
    state = _get_setting(GCIS_USAGE_SETTING, {}) or {}
    if not isinstance(state, dict) or state.get("date") != today:
        # 跨日歸零。
        state = {"date": today, "used": 0}
    used = int(state.get("used", 0) or 0)
    limit = _gcis_daily_limit()
    if used >= limit:
        # ⚠️ 訊息要說得出**是額度不是查無資料** ——
        # 兩者在畫面上都是「查不到」，而處置完全不同。
        raise HTTPException(
            429,
            f"今天的公司資料查詢次數已達上限（{limit} 次）。"
            "這個上限是為了保護我們對政府開放資料平台的用量，"
            "明天會自動恢復；若需要調整每日上限，請聯絡系統管理員。")
    state["used"] = used + 1
    _set_setting(GCIS_USAGE_SETTING, state)


GCIS_COMPANY  = "https://data.gcis.nat.gov.tw/od/data/api/236EE382-4942-41A9-BD03-CA0709025E7C"
GCIS_BUSINESS = "https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C"


@router.get("/api/now")
def server_now():
    now = datetime.now()
    return {"year": now.year, "month": now.month, "iso": now.isoformat()}


@router.get("/api/company/tax/{tax_id}")
def lookup_by_tax(tax_id: str, authorization: str = Header(None)):
    """統編查公司。**需要登入。**

    ## 🔴 為什麼這一支自己要檢查，而不是靠 middleware
    原本它**連 `authorization` 參數都沒有** ⇒ 完全靠 `main.py` 的
    middleware，而那一層是一張**豁免清單**（`_PUBLIC_API_PATHS`，13 條）。
    ☠️ 把一條路徑加進那張清單是**兩行**的改動，**而再多一條不會有人注意**
    ⇒ 那一刻這支端點就對全世界開放了，而**沒有任何訊號**。
    🔑 一道只有一層、而第二層明著不覆蓋的防線 —— 今天已經為
    `_smtp_send_blocked()` 記過同一件事。
    """
    _require_user(authorization)
    if not tax_id.isdigit() or len(tax_id) != 8:
        raise HTTPException(400, "統一編號須為 8 位數字")
    # ⚠️ **格式檢查在前、扣額度在後**：一個打錯的統編不該吃掉額度，
    # 而它本來就不會送出任何請求。
    _gcis_take_quota()
    flt = urllib.parse.quote(f"Business_Accounting_NO eq {tax_id}")
    data, st = _gcis_get(f"{GCIS_COMPANY}?$format=json&$filter={flt}&$skip=0&$top=1")
    if not data:
        data, st2 = _gcis_get(f"{GCIS_BUSINESS}?$format=json&$filter={flt}&$skip=0&$top=1")
        if st == _GCIS_ERR or st2 == _GCIS_ERR:
            st = _GCIS_ERR
    if not data:
        if st == _GCIS_ERR:
            raise HTTPException(503, "政府資料庫暫時無法連線，請確認伺服器網路或稍後再試")
        raise HTTPException(404, "查無此統一編號")
    return _normalize(data[0])


@router.get("/api/company/search")
def search_by_name(q: str = Query(..., min_length=2),
                   authorization: str = Header(None)):
    """公司名稱模糊查詢。**需要登入 ＋ 吃每日額度**（理由見 `lookup_by_tax`）。"""
    _require_user(authorization)
    _gcis_take_quota()
    q_safe = q.replace("'", "''")
    flt_c  = urllib.parse.quote(f"Company_Name like '%{q_safe}%'", safe='')
    data, st = _gcis_get(f"{GCIS_COMPANY}?$format=json&$filter={flt_c}&$skip=0&$top=15")
    if not data:
        flt_b = urllib.parse.quote(f"Business_Name like '%{q_safe}%'", safe='')
        data, st = _gcis_get(f"{GCIS_BUSINESS}?$format=json&$filter={flt_b}&$skip=0&$top=15")
    if st == _GCIS_ERR and not data:
        raise HTTPException(503, "政府資料庫暫時無法連線，請確認伺服器網路或稍後再試")
    return [_normalize(d) for d in data]
