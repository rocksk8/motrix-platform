# -*- coding: utf-8 -*-
"""T68 設定群組：勞報單「選派發」下拉（payslip_dispatch_picker）。**預設＝上線前的程式常數（一次 30 筆）。**

[單位] helper:settings_groups_payslip_picker    [層] L1    [穩定度] 實驗
[公開介面] （無；載入時由 settings_groups 呼叫）
[不變式] 只改清單一次載入幾筆；不改誰看得到哪些派發、搜尋範圍、金額（下拉不含金額）。讀不到設定 ⇒ 提供者退回後備值 30。
[契約題] backend/modules/payroll/tests/test_payslip_dispatch_dropdown_t55.py
"""


def _register(S, _register_core):
    _register_core(
        "payslip_dispatch_picker", "勞報單選派發下拉",
        [
            S("page_size", "int", 30, min=10, max=100, unit="筆", risk="ops", recommended=30,
              question="勞報單的「選派發」下拉，一次要載入幾筆？", label="下拉每次載入筆數",
              help="在勞報單選派發時，清單一次顯示這麼多筆，往下按「載入更多」再接著看。",
              impact="只影響清單一次載入幾筆，不改誰看得到哪些派發，也不改任何勞報單或派發資料；調大可能讓清單載入稍慢。"),
        ],
        sensitive=False, risk="ops",
        help="勞報單選派發下拉清單的載入筆數；搜尋範圍與權限不在這裡調整。",
    )
