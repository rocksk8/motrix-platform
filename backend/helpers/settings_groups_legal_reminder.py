# -*- coding: utf-8 -*-
"""T68 設定群組：法規參數「跨年提醒」起算日（legal_params_reminder）。

[單位] helper:settings_groups_legal_reminder    [層] L1    [穩定度] 實驗
[公開介面] （無）
[不變式] 只決定『從幾月幾日起開始提醒：下一年度的法規參數還沒設定』；提醒的內容、下一年度＝今年＋1、最低工資與補充保費門檻的對照檢查都是法規決定，不在這裡調整。
    預設 10 月 1 日（使用者 2026-10 裁示；原本寫死 12 月）；只影響提示文字與旗標，不影響任何稅額計算。讀不到設定 ⇒ 後備 10／1。
[契約題] backend/tests/test_legal_params_reminder_t68.py
"""

def _register(S, _register_core):
    _register_core(
        "legal_params_reminder", "法規參數跨年提醒",
        [
            S("start_month", "int", 10, min=1, max=12, unit="月", risk="ops", loosen="up", recommended=10,
              risk_text="往後延會讓提醒更晚出現，可能來不及在年底前設定下一年度的最低工資、扣繳起扣標準與補充保費門檻，進而影響明年初開立的勞報單。",
              question="每年從幾月起，開始提醒「下一年度的法規參數還沒設定」？", label="提醒起算（月）",
              help="到了這一天，如果下一年度還沒有新增法規參數版本，「法規參數設定」頁與勞報單頁就會顯示提醒；提醒會一直顯示到新增為止。",
              impact="只影響提醒什麼時候開始出現，不改任何稅額、扣繳或勞報單內容。往後延會更晚才提醒，須另一位最高管理者核准並等確認期間；提前則立即生效。",
              impact_scope={"documents": ["法規參數設定頁與勞報單頁的跨年提醒"], "roles": ["最高管理者", "開立勞報單的人"], "amounts": "不涉及金額；稅額與扣繳不受影響，只影響提醒何時出現。", "reversible": True, "effective": "pending"}),
            S("start_day", "int", 1, min=1, max=28, unit="日", risk="ops", loosen="up", recommended=1,
              risk_text="往後延會讓提醒更晚出現，可能來不及在年底前設定下一年度的最低工資、扣繳起扣標準與補充保費門檻，進而影響明年初開立的勞報單。",
              question="提醒從那個月的幾號開始？", label="提醒起算（日）",
              help="與上面的月份合起來就是提醒的起算日；日數最多選到 28，避免遇到沒有 29～31 日的月份。",
              impact="只影響提醒什麼時候開始出現，不改任何稅額、扣繳或勞報單內容。往後延會更晚才提醒，須另一位最高管理者核准並等確認期間；提前則立即生效。",
              impact_scope={"documents": ["法規參數設定頁與勞報單頁的跨年提醒"], "roles": ["最高管理者", "開立勞報單的人"], "amounts": "不涉及金額；稅額與扣繳不受影響，只影響提醒何時出現。", "reversible": True, "effective": "pending"}),
        ],
        sensitive=False, risk="ops",
        help="法規參數「下一年度還沒設定」提醒的起算日；提醒的內容與法規檢查不在這裡調整。",
    )
