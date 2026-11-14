# -*- coding: utf-8 -*-
"""設定群組：系統標語（brand.tagline）。

[單位] helper:settings_groups_brand    [層] L1    [穩定度] 實驗
[公開介面] DEFAULT_TAGLINE、brand_tagline
[不變式] 標語＝首頁大標題上方的小字（以及各頁分頁標題的預設字尾由靜態頁面寫死為「MOTRIX PLATFORM」）。
    **預設 `MOTRIX PLATFORM`**（2026-11-13 PM 轉述使用者方針：系統統一叫 MOTRIX-PLATFORM、產品要對外販售；不再寫「專案管理系統」）。
    公司可自訂（1～24 個字，不可含換行與尖括號）；只是顯示字，不影響任何單據或權限。
    讀取一律走 `brand_tagline()`：設定壞掉、空白或不合法 ⇒ 回預設，永不丟例外。
[契約題] tests/test_brand_tagline_2026_11_13.py
"""
import re

DEFAULT_TAGLINE = "MOTRIX PLATFORM"
_MAX = 24
_BAD = re.compile(r"[\x00-\x1f\x7f<>]")


def _cross_check(values):
    t = values.get("tagline")
    if isinstance(t, str):
        s = t.strip()
        if not s:
            return ["標語不可以是空白；要用預設請按「恢復建議值」"]
        if len(s) > _MAX:
            return ["標語最多 %d 個字" % _MAX]
        if _BAD.search(s):
            return ["標語不可以含換行或 < > 符號"]
    return []


def brand_tagline() -> str:
    """目前生效的標語（已 strip；不合法一律回預設）。永不丟例外。"""
    try:
        from helpers import settings_registry as sr
        v = (sr.get_group("brand") or {}).get("tagline")
        if isinstance(v, str):
            s = v.strip()
            if s and len(s) <= _MAX and not _BAD.search(s):
                return s
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_TAGLINE


def _register(S, _register_core):
    _register_core(
        "brand", "系統標語",
        [
            S("tagline", "str", DEFAULT_TAGLINE, risk="none", recommended=DEFAULT_TAGLINE,
              question="首頁標題上方的小字要寫什麼？", label="首頁小標語", when="想讓首頁小標語換成公司自己的系統名稱或口號時。",
              help="顯示在首頁大標題上方。預設是「MOTRIX PLATFORM」；公司可以改成自己的系統名稱或口號。",
              impact="只改畫面上的小字，立即生效；不影響任何單據、權限或信件。可隨時改回建議值。"),
        ],
        sensitive=False, risk="none",
        help="公司自己的系統名稱／口號。只改畫面上的顯示字，不影響資料。",
        cross_check=_cross_check,
    )
    # 登入問候語（2026-11-13 使用者裁示；helpers/login_greeting.py）：新安裝預設「溫和正式」，風格三選一；句子本身另有自訂入口
    _register_core(
        "login_greeting", "登入問候語",
        [
            S("style", "int", 1, min=0, max=2, risk="none", recommended=1,
              question="首頁大標題下面，是否顯示問候語？若顯示，請選擇語氣。", label="首頁問候語的口氣", when="覺得問候語太吵、或想換成更正式或更輕鬆的口氣時。",
              help="登入後，首頁標題下方會有一句依情境變化的話（節慶、久未登入、星期、時段等）。每個人也可以在自己的帳號裡調整為自己偏好的語氣。",
              impact="只改首頁上的一句話，立即生效；不影響任何單據或權限。選「關閉」＝全公司都不顯示（個人亦無法開啟）。",
              choices=[(0, "關閉", "首頁不顯示問候語，只有原本的標題。"),
                       (1, "溫和正式（建議）", "有禮貌、不開玩笑，適合對外展示與較正式的公司。"),
                       (2, "輕鬆幽默", "語氣輕鬆，會開天氣、星期幾、節日的玩笑，但不會拿任何人開玩笑。")]),
        ],
        sensitive=False, risk="none",
        help="登入後首頁那一句問候語的語氣。每個情境的句子可以另外改寫或新增。",
    )
