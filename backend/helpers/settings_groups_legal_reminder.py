# -*- coding: utf-8 -*-
"""T68 設定群組：法規參數「跨年提醒」起算日（legal_params_reminder）。

[單位] helper:settings_groups_legal_reminder    [層] L1    [穩定度] 實驗
[公開介面] （無；載入時由 settings_groups 檔尾的一行 import 觸發登錄）
[不變式] 只決定『從幾月幾日起開始提醒：下一年度的法規參數還沒設定』；提醒的內容、下一年度＝今年＋1、最低工資與補充保費門檻的對照檢查都是法規決定，不在這裡調整。
    預設 10 月 1 日（使用者 2026-10 裁示；原本寫死 12 月）；只影響提示文字與旗標，不影響任何稅額計算。讀不到設定 ⇒ 後備 10／1。
[契約題] backend/tests/test_legal_params_reminder_t68.py
"""

from helpers.settings_groups import S, _register_core  # noqa: E402  settings_groups 檔尾 import 本檔時，這兩個名稱已定義

_register_core(
    "legal_params_reminder", "法規參數跨年提醒",
    [
        S("start_month", "int", 10, min=1, max=12, unit="月", risk="ops", loosen="up", recommended=10,
          question="每年從幾月起，開始提醒「下一年度的法規參數還沒設定」？", label="提醒起算（月）",
          help="到了這一天，如果下一年度還沒有新增法規參數版本，「法規參數設定」頁與勞報單頁就會顯示提醒；提醒會一直顯示到新增為止。",
          impact="只影響提醒什麼時候開始出現，不改任何稅額、扣繳或勞報單內容。往後延會更晚才提醒，須另一位最高管理者核准並等確認期間；提前則立即生效。"),
        S("start_day", "int", 1, min=1, max=28, unit="日", risk="ops", loosen="up", recommended=1,
          question="提醒從那個月的幾號開始？", label="提醒起算（日）",
          help="與上面的月份合起來就是提醒的起算日；日數最多選到 28，避免遇到沒有 29～31 日的月份。",
          impact="只影響提醒什麼時候開始出現，不改任何稅額、扣繳或勞報單內容。往後延會更晚才提醒，須另一位最高管理者核准並等確認期間；提前則立即生效。"),
    ],
    sensitive=False, risk="ops",
    help="法規參數「下一年度還沒設定」提醒的起算日；提醒的內容與法規檢查不在這裡調整。",
)
