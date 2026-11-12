# -*- coding: utf-8 -*-
"""個人偏好（「我的帳號」票，2026-11-13）：每人每鍵一列，存在伺服器端，換裝置也保留。

[單位] helper:user_prefs    [層] L1    [穩定度] 實驗（表 `user_prefs`，core 遷移 13）
[公開介面] SCHEMA, get, get_all, set_many, PrefError
[不變式] ①白名單：只有 SCHEMA 裡的鍵、值域內的值存得進去；不合法 ⇒ PrefError（422，不靜默吞掉）。
    ②只讀寫呼叫者自己的列（鍵＝user_id，路徑與請求內容都沒有別人的 id）。
    ③偏好只影響**自己看到的畫面**，不進報價單、PDF、信件簽名檔；任何會出現在單據上的資料不在這裡。
    ④讀不到表或壞資料 ⇒ 回預設，不丟 500（偏好壞了不該擋住登入後的畫面）。
    ⑤不使用 DELETE：「還原預設」＝存回預設值（刪除暫存區守門不必登記）。
    ⑥hichan-7 的登入問候語讀 `get(uid, "login_greeting")`；公司層設定另在設定中心，有效值＝個人值，`follow_company` 時才看公司。
"""
import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger("motrix.user_prefs")

TABLE = "user_prefs"

#: 每個鍵：values＝允許的值（白名單）、default＝預設、label／options＝給畫面用的白話說明（不含程式字眼）
SCHEMA = {
    "login_greeting": {
        "default": "follow_company",
        "label": "登入問候語",
        "options": [("follow_company", "跟隨公司設定"), ("humor", "輕鬆幽默"), ("formal", "溫和正式"), ("off", "關閉")],
    },
    "font_size": {
        "default": "normal",
        "label": "字級",
        "options": [("small", "小"), ("normal", "標準"), ("large", "大"), ("xlarge", "特大")],
    },
    "theme": {
        "default": "light",
        "label": "外觀",
        "options": [("light", "淺色"), ("dark", "深色")],
    },
    "home_page": {
        "default": "index.html",
        "label": "登入後的首頁",
        "options": [("index.html", "儀表板"), ("case-management.html", "案件管理"), ("quotations.html", "報價單"),
                    ("approval-queue.html", "待我簽核"), ("daily-tasks.html", "每日工作事項")],
    },
    "avatar_color": {
        "default": "auto",
        "label": "頭像顏色",
        "options": [("auto", "自動"), ("blue", "藍"), ("green", "綠"), ("orange", "橘"), ("red", "紅"), ("purple", "紫"), ("teal", "青"), ("gray", "灰")],
    },
}


class PrefError(ValueError):
    """不合法的偏好鍵或值（呼叫端轉 422）。"""


def _allowed(key):
    return [v for v, _ in SCHEMA[key]["options"]]


def defaults() -> dict:
    return {k: s["default"] for k, s in SCHEMA.items()}


def get_all(user_id: int) -> dict:
    """該使用者全部偏好（沒存的用預設；存的值若已不在白名單內也回預設）。"""
    out = defaults()
    try:
        conn = get_db()
        try:
            rows = conn.execute("SELECT key, value_json FROM user_prefs WHERE user_id=?", (int(user_id),)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 偏好壞了不擋畫面
        logger.warning("user_prefs 讀取失敗，回預設", exc_info=True)
        return out
    for r in rows:
        k = r["key"]
        if k not in SCHEMA:
            continue
        try:
            v = json.loads(r["value_json"])
        except (TypeError, ValueError):
            continue
        if v in _allowed(k):
            out[k] = v
    return out


def get(user_id: int, key: str, default=None):
    if key not in SCHEMA:
        raise KeyError(key)
    v = get_all(user_id).get(key)
    return default if v is None else v


def validate(changes: dict) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise PrefError("沒有要儲存的偏好")
    clean = {}
    for k, v in changes.items():
        if k not in SCHEMA:
            raise PrefError("不認得的偏好項目：%s" % (str(k)[:40],))
        if not isinstance(v, str) or v not in _allowed(k):
            raise PrefError("「%s」的選項不正確" % SCHEMA[k]["label"])
        clean[k] = v
    return clean


def set_many(user_id: int, changes: dict) -> dict:
    """驗證後一次寫入（UPSERT，一個交易）；回傳寫入後的全部偏好。"""
    clean = validate(changes)
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    try:
        for k, v in clean.items():
            conn.execute(
                "INSERT INTO user_prefs (user_id, key, value_json, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (int(user_id), k, json.dumps(v, ensure_ascii=False), now))
        conn.commit()
    finally:
        conn.close()
    return get_all(user_id)
