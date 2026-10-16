# -*- coding: utf-8 -*-
"""T70 設定群組：附近旅宿資料「多久算過舊」（lodging_freshness.stale_days）。

[單位] helper:settings_groups_lodging_freshness    [層] L1    [穩定度] 實驗
[公開介面] （無）
[不變式] 只決定『旅宿資料日期超過幾天，頁面就提示「資料可能過舊」』；不會自動去抓資料、不改任何查詢結果、價格或排序。
    預設 30 天（＝上線前寫死的 `modules.lodging.source.STALE_DAYS`，那個常數保留當後備值）；範圍 7～365。讀不到或不合法 ⇒ 用 30。
[契約題] backend/modules/lodging/tests/test_lodging_stale_days_t70.py
"""


def _register(S, _register_core):
    _register_core(
        "lodging_freshness", "附近旅宿：資料新舊提示",
        [
            S("stale_days", "int", 30, min=7, max=365, unit="天", risk="none", recommended=30,
              question="附近旅宿的資料日期超過幾天，要提示「資料可能過舊」？", label="資料過舊提示天數（7～365）",
              help="觀光署旅宿資料每次更新都會記下資料日期；超過這個天數沒有更新，「附近旅宿」與住宿紀錄頁會顯示「資料日期已超過 N 天，內容可能過舊」。",
              impact="只影響這行提示何時出現，不會自動去抓資料，也不改任何查詢結果、價格或排序；立即生效，可隨時改回。"),
        ],
        sensitive=False, risk="none",
        help="附近旅宿資料多久沒更新就提示過舊。資料來源與抓取開關不在這裡設定。",
    )
