# -*- coding: utf-8 -*-
"""設定群組登錄（L1；第 54 班 Train A）。**預設值＝上線前的程式常數**（部署零行為變更；`settings_deploy_baseline.json` 凍結）。

[單位] helper:settings_groups    [層] L1    [穩定度] 契約
[公開介面] （載入時登錄群組：retention、uploads）
[不變式] 預設值改動＝行為變更，必須同步改凍結基準並走裁示；上下限只寫在這裡；副檔名白名單不在此可調（安全邊界）。
[契約題] backend/tests/platform/test_settings_registry_t54.py
"""
from helpers.settings_registry import SettingDef as S, register_group

# 舊 PATCH /api/settings/backup-retention 的範圍：天數 1–3650、月備份 0–3650（0＝永久）、更新前快照份數 0–100。
# 稽核紀錄保存期限另加法遵下限 365（無上限）；讀取時向上夾到 365（舊庫裡低於 365 的值不會讓稽核被提早清掉）。
register_group(
    "retention", "保存期限",
    [
        S("local_db_keep_days", "int", 30, min=1, max=3650, unit="天", label="本機備份保留天數", legacy="local_db_keep_days", risk="ops",
          help="本機資料庫備份超過這個天數就清除。"),
        S("cloud_daily_keep_days", "int", 60, min=1, max=3650, unit="天", label="雲端每日備份保留天數", legacy="cloud_daily_keep_days", risk="ops",
          help="近期誤刪／誤改的回溯窗口。"),
        S("cloud_weekly_keep_days", "int", 90, min=1, max=3650, unit="天", label="雲端週備份保留天數", legacy="cloud_weekly_keep_days", risk="ops"),
        S("cloud_monthly_keep_days", "int", 0, min=0, max=3650, unit="天", label="雲端月備份保留天數（0＝永久）", legacy="cloud_monthly_keep_days", risk="ops"),
        S("local_pre_update_keep", "int", 5, min=0, max=100, unit="份", label="更新前快照保留份數", legacy="local_pre_update_keep", risk="ops"),
        S("audit_log_keep_days", "int", 1825, min=365, unit="天", label="稽核紀錄保留天數（至少 365）", legacy="audit_log_keep_days", risk="legal", clamp=True,
          help="稽核紀錄是法遵證據，不可低於 365 天；沒有上限。"),
        S("notification_keep_days", "int", 90, min=7, max=3650, unit="天", label="站內通知保留天數", risk="ops",
          help="已讀、未讀都清。"),
        S("request_log_keep_days", "int", 90, min=7, max=3650, unit="天", label="請求紀錄保留天數", risk="ops"),
    ],
    sensitive=True, risk="ops", legacy_key="backup_retention",
    help="備份、稽核紀錄、通知與請求紀錄的保存期限。",
)

register_group(
    "uploads", "上傳容量",
    [
        S("max_file_mb", "int", 20, min=1, max=200, unit="MB", label="單檔大小上限", risk="ops"),
        S("case_extra_expense_max_files", "int", 10, min=1, max=100, unit="個", label="支出申請每張單據附件數上限", risk="ops"),
        S("case_extra_expense_max_request_mb", "int", 50, min=1, max=500, unit="MB", label="支出申請一次送出合計上限", risk="ops"),
    ],
    sensitive=False, risk="ops",
    help="允許的副檔名與檔頭檢查屬安全邊界，不在此調整。",
)
