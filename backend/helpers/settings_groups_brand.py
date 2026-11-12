# -*- coding: utf-8 -*-
"""設定群組：系統標語（brand.tagline）。

[單位] helper:settings_groups_brand    [層] L1    [穩定度] 實驗
[公開介面] （無；群組在 `settings_groups` 結尾 import 後登錄）
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
              question="首頁標題上方的小字要寫什麼？", label="系統標語（1～24 個字）",
              help="顯示在首頁大標題上方。預設是「MOTRIX PLATFORM」；公司可以改成自己的系統名稱或口號。",
              impact="只改畫面上的小字，馬上生效；不影響任何單據、權限或信件。改回建議值隨時可以。"),
        ],
        sensitive=False, risk="none",
        help="公司自己的系統名稱／口號。只改畫面上的顯示字，不影響資料。",
        cross_check=_cross_check,
    )
