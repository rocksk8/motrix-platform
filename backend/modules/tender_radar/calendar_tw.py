# -*- coding: utf-8 -*-
"""標案雷達的「不寄信日」判定：週六、週日、國定假日。**純函式，不連網、不讀時鐘（日期由呼叫端給）。**

資料：同目錄 `holidays_tw.json`，一次性取自官方「中華民國政府行政機關辦公日曆表」（行政院人事行政總處；來源網址、取得日期、
涵蓋範圍、原檔 sha256 都記在檔內）。repo 內原本沒有任何假日表（helpers/dates.py 只排除週六日，docstring 明說屬已知限制），
所以這是新資料；每年要用新一年的官方 CSV 重轉並更新 `coverage`。

規則：
  補班日（週末但要上班）          ⇒ 可寄信（官方 2026、2027 都沒有補班日；規則仍支援，測試用合成資料驗）
  其餘週六、週日                  ⇒ 不寄信（reason＝週末）
  表內的平日放假日（含補假）        ⇒ 不寄信（reason＝國定假日：<名稱>）
  年份不在涵蓋範圍                ⇒ 只能辨識週末；`covered()` 回 False，頁面與系統檢查要明說「假日表未涵蓋」，不可靜默當成平日
"""
import json
from datetime import date, timedelta
from pathlib import Path

DATA_PATH = Path(__file__).with_name("holidays_tw.json")
_cache = {}


def load(path=None):
    """讀假日表。讀不到／壞檔 ⇒ 回 `None`（呼叫端當成「完全沒有假日表」，仍可辨識週末）。依檔案 mtime 快取。"""
    p = Path(path or DATA_PATH)
    try:
        key = (str(p), p.stat().st_mtime_ns)
        if key in _cache:
            return _cache[key]
        data = json.loads(p.read_text(encoding="utf-8"))
        _cache.clear()
        _cache[key] = data
        return data
    except (OSError, ValueError):
        return None


def _iso(d):
    return d.isoformat() if isinstance(d, date) else str(d)[:10]


def coverage(data=None):
    """⇒ (起日 date, 迄日 date)；沒有表 ⇒ None。"""
    data = load() if data is None else data
    try:
        c = data["coverage"]
        return date.fromisoformat(c["from"]), date.fromisoformat(c["to"])
    except (TypeError, KeyError, ValueError):
        return None


def covered(d, data=None):
    """這一天在假日表的涵蓋範圍內嗎。"""
    cov = coverage(data)
    return bool(cov) and cov[0] <= date.fromisoformat(_iso(d)) <= cov[1]


def days_until_expiry(today_d, data=None):
    """涵蓋範圍最後一天離今天還有幾天（負數＝已過期）；沒有表 ⇒ None。"""
    cov = coverage(data)
    return None if not cov else (cov[1] - date.fromisoformat(_iso(today_d))).days


def no_mail_day(d, data=None):
    """⇒ `(不寄信?, 理由或 None)`。理由字串直接給畫面顯示（用 x-text）。"""
    data = load() if data is None else data
    d = date.fromisoformat(_iso(d))
    iso = d.isoformat()
    years = (data or {}).get("years") or {}
    y = years.get(str(d.year)) or {}
    if iso in (y.get("makeup_workdays") or []):
        return False, None                       # 補班日：週末但要上班
    if d.weekday() >= 5:
        return True, "週末"
    name = (y.get("holidays") or {}).get(iso)
    if name:
        return True, "國定假日：%s" % name
    return False, None


def next_mail_day(d, data=None, limit=30):
    """從 d（含）起往後第一個可寄信日；`limit` 天內找不到 ⇒ None（資料壞掉時不無窮迴圈）。"""
    d = date.fromisoformat(_iso(d))
    for i in range(limit):
        x = d + timedelta(days=i)
        if not no_mail_day(x, data)[0]:
            return x
    return None
