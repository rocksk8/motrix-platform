# -*- coding: utf-8 -*-
"""物料流程「一條龍」各批次的開關（群組 `onepipe`；提案 docs/platform/plans/PROCUREMENT-FLOW-ONEPIPE-PROPOSAL-v3.md §2.4）。

[單位] helper:settings_groups_onepipe    [層] L1    [穩定度] 實驗
[公開介面] （無；讀值走 `helpers.settings_registry.get("onepipe", <欄位>)`）
[不變式] 每個欄位都是 0／1，**預設 0（關）＝該批次上線前後與今天逐位元相同**；開關只決定新行為出不出現，
    不動權限、不動簽核、不改資料結構。各批次共用同一個群組（一個群組一份設定頁），由各批次的班次各自加欄位：
      worklog_case            P0b 工作日誌可選案件（本檔）
      warranty_closed_notify  P0d 保固到期通知納入已結案案件（本檔）
      links／ship_install_ok／timeline  P0a／P0c／P1'（hichan-1 的班次接著加在下面的清單裡）
[契約題] backend/tests/test_onepipe_worklog_case_2026_11_13.py、backend/tests/test_onepipe_warranty_closed_2026_11_13.py
"""


def _register(S, _register_core):
    _register_core(
        "onepipe", "物料流程一條龍：各批次開關",
        [
            S("worklog_case", "int", 0, min=0, max=1, risk="none", recommended=0,
              question="要讓工程師寫工作日誌時，可以選這筆日誌屬於哪個案件嗎？", label="工作日誌可選案件",
              help="開啟後，「工作日誌」的新增與編輯畫面多一個「關聯案件（選填）」，選了案件的日誌會出現在該案件的「動態」與專案報告裡。"
                   "只能選自己有權看的案件；日誌本身誰看得到、誰能改，與現在完全相同。",
              impact="只影響新增或編輯日誌時多一個選填欄位；已經寫好的日誌不會被改動。關閉後，畫面回到今天的樣子，已選過案件的日誌仍留在該案件動態裡。立即生效，可隨時改回。",
              choices=[(0, "關閉（預設）", "工作日誌畫面與今天完全相同。"), (1, "開啟", "日誌可選填關聯案件，並出現在該案的動態與專案報告。")]),
            S("warranty_closed_notify", "int", 0, min=0, max=1, risk="ops", recommended=0,
              question="已結案的案件，設備保固快到期時，也要寄保固到期通知嗎？", label="保固到期通知納入已結案案件",
              help="目前只有「已成案」（進行中）的案件會寄保固到期通知。開啟後，「已結案」案件的設備保固也會在到期前通知（同樣的天數、同樣的收件人）。"
                   "為避免一開啟就把過去所有舊案的通知一次寄出，系統會在開啟後的第一次每日檢查「靜默建立基準」：當下已經在提醒期間內的設備只做記號、不寄信；"
                   "已經過期的設備不會通知；之後新進入提醒期間的設備才會寄。",
              impact="會多寄信：之後每一台已結案案件的設備進入保固提醒期間時，收件人（案件業務與保固通知群組）會多收到一封保固到期信。開啟當下不會寄出任何歷史通知。"
                     "關閉後立即停止；之後再開啟會重新建立基準（關閉期間錯過的不補寄）。",
              choices=[(0, "關閉（預設）", "只有已成案的案件寄保固通知，與今天完全相同。"), (1, "開啟", "已結案案件的保固到期也寄通知；開啟當下不補寄歷史通知。")]),
        ],
        sensitive=False, risk="ops",
        help="物料流程一條龍各批次的開關；預設全部關閉，關閉就和今天完全相同。",
    )
