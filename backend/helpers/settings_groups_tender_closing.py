# -*- coding: utf-8 -*-
"""T70 設定群組：地圖上標案「即將截止」標記的天數（tender_closing.closing_soon_days）。

[單位] helper:settings_groups_tender_closing    [層] L1    [穩定度] 實驗
[公開介面] （無）
[不變式] 只決定『標案截止日離今天幾天以內（含當天），地圖點位標成「即將截止」』；不改標案資料、不改哪些標案會出現在地圖、不改任何金額或權限。
    預設 7 天（＝上線前寫死的 `routers.map_points.CLOSING_SOON_DAYS`，那個常數保留當後備值）；範圍 1～60。讀不到或不合法 ⇒ 用 7。
[契約題] backend/tests/test_closing_soon_days_t70.py
"""


def _register(S, _register_core):
    _register_core(
        "tender_closing", "地圖：標案即將截止標記",
        [
            S("closing_soon_days", "int", 7, min=1, max=60, unit="天", risk="none", recommended=7,
              question="標案截止日在幾天以內，地圖上要標成「即將截止」？", label="即將截止天數（1～60）",
              help="地圖上的標案點位會依截止日上色：已截止、即將截止、尚未截止。截止日離今天不超過這個天數（含當天）就算「即將截止」。",
              impact="只影響地圖點位的顏色分類與「即將截止」篩選的範圍，不改標案資料、不改哪些標案會出現在地圖；立即生效，可隨時改回。"),
        ],
        sensitive=False, risk="none",
        help="地圖標案點位「即將截止」的判斷天數。標案抓取開關與頻率不在這裡設定。",
    )
