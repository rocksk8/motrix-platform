# -*- coding: utf-8 -*-
"""設定群組登錄（L1；第 54 班 Train A）。**預設值＝上線前的程式常數**（部署零行為變更；`settings_deploy_baseline.json` 凍結）。

[單位] helper:settings_groups    [層] L1    [穩定度] 契約
[公開介面] 無
[不變式] 載入時登錄群組 change_control、retention、uploads（沒有對外名稱，只有登錄的副作用）；預設值改動＝行為變更，必須同步改凍結基準並走裁示；上下限只寫在這裡；副檔名白名單不在此可調（安全邊界）。
    畫面文字規則（零技術門檻）：問句、標籤、說明、影響說明一律白話繁中，內部鍵不顯示給使用者（守門 test_settings_ui_plain_language）。
[契約題] backend/tests/platform/test_settings_registry_t54.py
"""
from helpers.settings_registry import SettingDef as S, register_group

# 舊 PATCH /api/settings/backup-retention 的範圍：天數 1–3650、月備份 0–3650（0＝永久）、更新前快照份數 0–100。
# 稽核紀錄保存期限另加法遵下限 365（無上限）；讀取時向上夾到 365（舊庫裡低於 365 的值不會讓稽核被提早清掉）。
_BACKUP_IMPACT = "只影響之後的清理：超過天數的舊備份會在下一次例行清理時被刪除，已刪除的備份無法找回；改大則不會補回已刪的。調長立即生效；縮短（會更早刪除）屬放寬，須另一位最高管理者核准，並等「變更確認期間」後才生效。"

register_group(
    "change_control", "變更管制",
    [
        S("confirm_period_days", "int", 7, min=1, max=90, unit="天", risk="legal", loosen="down", recommended=7,
          question="高風險設定的變更，要等幾天才生效？（期間內可以撤銷）", label="變更確認期間（天）",
          help="金額、法遵、安全這類設定改了以後，先等這段時間才真的生效，期間內任何最高管理者都能撤銷。最短 1 天。",
          impact="影響之後送出的高風險變更；已經在等待中的變更仍照原本的生效時間。縮短確認期間等於放寬管制，須另一位最高管理者核准，並等目前的確認期間後才生效。",
          risk_text="縮短後，有人誤改或被盜用帳號時，留給大家發現並撤銷的時間會變少。"),
    ],
    sensitive=True, risk="legal",
    help="高風險設定變更要等多久才生效、是否需要第二位最高管理者核准。",
)

register_group(
    "retention", "保存期限",
    [
        S("local_db_keep_days", "int", 30, min=1, max=3650, unit="天", legacy="local_db_keep_days", risk="ops", loosen="down", recommended=30,
          question="本機的資料庫備份要保留幾天？", label="本機備份保留天數", help="本機電腦上的資料庫備份，超過這個天數就清除。",
          impact=_BACKUP_IMPACT),
        S("cloud_daily_keep_days", "int", 60, min=1, max=3650, unit="天", legacy="cloud_daily_keep_days", risk="ops", loosen="down", recommended=60,
          question="雲端「每日備份」要保留幾天？", label="雲端每日備份保留天數", help="近期誤刪、誤改時用來還原的備份。",
          impact=_BACKUP_IMPACT),
        S("cloud_weekly_keep_days", "int", 90, min=1, max=3650, unit="天", legacy="cloud_weekly_keep_days", risk="ops", loosen="down", recommended=90,
          question="雲端「每週備份」要保留幾天？", label="雲端週備份保留天數", help="每日備份之外，較久遠的中期還原點。",
          impact=_BACKUP_IMPACT, advanced=True),
        S("cloud_monthly_keep_days", "int", 0, min=0, max=3650, unit="天", legacy="cloud_monthly_keep_days", risk="ops", loosen="down", zero_is_max=True, recommended=0,
          question="雲端「每月備份」要保留幾天？（填 0 代表永久保留）", label="雲端月備份保留天數（0＝永久）",
          help="長期法遵與歷史查詢用的備份，建議永久保留。", impact=_BACKUP_IMPACT + "填 0 表示永不清除。", advanced=True),
        S("local_pre_update_keep", "int", 5, min=0, max=100, unit="份", legacy="local_pre_update_keep", risk="ops", loosen="down", zero_is_max=True, recommended=5,
          question="每次系統更新前自動留的快照，要保留幾份？（填 0 代表不清理）", label="更新前快照保留份數",
          help="更新系統之前自動留下的還原點，用來更新失敗時退回。",
          impact="只影響之後的清理：超過份數的舊快照會被刪除。更新失敗時要靠它退回，不建議調太少；調少須另一位最高管理者核准並等確認期間。", advanced=True),
        S("audit_log_keep_days", "int", 1825, min=365, unit="天", legacy="audit_log_keep_days", risk="legal", loosen="down", clamp=True, recommended=1825,
          question="稽核紀錄（誰在何時改了什麼）要保留幾天？至少 365 天，沒有上限。", label="稽核紀錄保留天數（至少 365）",
          help="稽核紀錄是出事時的法遵證據，不可低於 365 天。",
          impact="超過天數的稽核紀錄會被永久刪除，無法找回；只影響之後的清理，已存在的紀錄在到期前不受影響。縮短保存期限會讓較舊的紀錄提早消失，所以縮短須另一位最高管理者核准，並等「變更確認期間」後才生效。",
          risk_text="縮短後，被清掉的稽核紀錄無法復原；若遇到查帳或糾紛，可能找不到當時的操作證據。"),
        S("notification_keep_days", "int", 90, min=7, max=3650, unit="天", risk="ops", loosen="down", recommended=90,
          question="站內通知（畫面右上角的訊息）要保留幾天？", label="站內通知保留天數", help="不論已讀或未讀，超過天數都會清除。",
          impact="只影響之後的清理：超過天數的通知（已讀、未讀都算）會從每個人的通知清單消失，不影響通知所指的單據本身。", advanced=True),
        S("request_log_keep_days", "int", 90, min=7, max=3650, unit="天", risk="ops", loosen="down", recommended=90,
          question="系統操作軌跡（誰在何時開了哪個頁面）要保留幾天？", label="操作軌跡保留天數", help="用來回頭查「上個月那筆資料是誰改的」。",
          impact="只影響之後的清理：超過天數的操作軌跡會被刪除；保留越久，個人行為紀錄累積越多，外洩時的影響也越大。", advanced=True),
    ],
    sensitive=True, risk="ops", legacy_key="backup_retention",
    help="備份、稽核紀錄、通知與操作軌跡要保存多久。",
)

register_group(
    "uploads", "上傳容量",
    [
        S("max_file_mb", "int", 20, min=1, max=200, unit="MB", risk="ops", loosen="up", recommended=20,
          question="每個上傳的檔案最大可以多大？", label="單檔大小上限", help="超過的檔案會被擋下，請使用者壓縮或分開上傳。",
          impact="影響所有上傳附件的畫面（單據附件、發票、簽回檔等），只影響之後的上傳；已上傳的檔案不受影響。調大會占用更多硬碟與備份空間，屬放寬：須另一位最高管理者核准並等確認期間；調小立即生效。"),
        S("case_extra_expense_max_files", "int", 10, min=1, max=100, unit="個", risk="ops", loosen="up", recommended=10,
          question="一張支出申請單最多可以附幾個檔案？", label="支出申請每張單據附件數上限", help="包含正式附件與待核准的新附件。",
          impact="只影響支出申請單之後的上傳；已超過新上限的舊單據不會被刪除，但不能再加附件。調大須另一位最高管理者核准並等確認期間；調小立即生效。"),
        S("case_extra_expense_max_request_mb", "int", 50, min=1, max=500, unit="MB", risk="ops", loosen="up", recommended=50,
          question="支出申請一次送出的附件總共最大可以多大？", label="支出申請一次送出合計上限", help="一次上傳的所有檔案加總的大小上限。",
          impact="只影響之後的上傳；超過時請使用者分批上傳。調大須另一位最高管理者核准並等確認期間；調小立即生效。", advanced=True),
    ],
    sensitive=False, risk="ops",
    help="上傳檔案的大小與數量上限；允許的檔案類型屬安全邊界，不在此調整。",
)

# 系統中心（第 54 班）：『沒有權限的項目要不要列出來』是『放寬可見度』的設定——走設定登錄表（版本、影響說明、稽核同交易、放寬要確認期間與第二人核准）。
register_group(
    "system_hub", "系統中心",
    [
        S("show_denied", "int", 0, min=0, max=1, risk="security", loosen="up", recommended=0,
          question="系統中心要不要列出『你沒有權限使用』的項目？", label="沒有權限的項目",
          help="預設隱藏：每個人只看到自己能用的項目。也可以改成顯示為灰色，並說明為什麼不能用。這項在「設定中心」調整。",
          impact="只影響系統中心的畫面，不會改變任何人實際能使用的功能。改成『顯示為灰色』時，沒有權限的人會看到有哪些管理項目的名稱，但點不進去。",
          risk_text="顯示後，沒有權限的人也能知道系統裡有哪些管理功能（例如備份、權限、稽核）；若不希望外人知道，請維持隱藏。",
          choices=[(0, "隱藏（建議）", "每個人只看到自己能用的項目；沒有權限的人完全看不到其他項目。"),
                   (1, "顯示為灰色並說明原因", "沒有權限的人會看到項目名稱與『需要什麼權限』，但點不進去。")]),
    ],
    sensitive=True, risk="security",
    help="系統中心的顯示方式。要調整請到「系統」裡的「設定中心」。",
)

# 材料申請（第 57 班）：新增材料申請是否一定要先選供應商——預設必填＝上線前的行為（部署零行為變更）。
register_group(
    "material_order", "材料申請",
    [
        S("supplier_required", "int", 1, min=0, max=1, risk="money", loosen="down", recommended=1,
          question="新增材料申請時，一定要先選供應商嗎？", label="新增材料申請要選供應商",
          help="匯款申請要憑供應商帶出收款對象。從已核准採購單帶入的材料申請，採購單上已有廠商收款資料，可以先不選。",
          impact="只影響之後新增的材料申請，已存在的不受影響。選「帶入採購單的免選」時，從採購單帶入的新申請可以不選供應商就儲存、送審；之後開匯款申請時仍必須選好供應商。",
          risk_text="免選供應商後，申請可能在沒有供應商資料的情況下送審，到開匯款申請才發現缺資料而卡住；也比較容易漏選到錯的供應商。",
          choices=[(1, "一定要選（建議）", "沒選供應商的新申請不能儲存，會顯示原因。"),
                   (0, "帶入採購單的免選", "從已核准採購單帶入的新申請可以先不選供應商；手動新增的仍要選。")]),
    ],
    sensitive=False, risk="money",
    help="材料申請的新增規則。目前只有「新增時要不要選供應商」。",
)

# 完工單「從報價單帶入項目」（第 57 班；設計 COMPLETION-NOTE-QUOTE-ITEMS-T56 §5）：預設值＝使用者 2026-10-12 的表單裁示。
# 全部是『之後新建／重新帶入』的行為選項，不改任何既有完工單。金額永遠不進完工單（結構性不變式，不在此調整）。
register_group(
    "completion_note", "完工單",
    [
        S("auto_prefill", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="新建完工單時，要不要自動把報價單的項目帶進來？", label="新建時自動帶入項目",
          help="帶入後每一列都可以修改、刪除；按「儲存」才會寫入。",
          impact="只影響之後新開的完工單畫面；已存的完工單不會改。選「不自動帶入」仍可在草稿上按「從報價單帶入」。",
          choices=[(1, "自動帶入（建議）", "新建時畫面直接出現報價單的項目，不用重打。"),
                   (0, "不自動帶入", "新建時項目是空白的，需要時再按「從報價單帶入」。")]),
        S("prefill_unsigned", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="報價單已送出、但客戶還沒回簽時，可以帶入項目嗎？", label="未回簽的報價單可否帶入",
          help="報價還沒回簽時，項目之後還可能被修改；帶入的內容只是暫時依據。",
          impact="影響所有新建與重新帶入完工單的人（目前限管理員）；已存的完工單不變。選「要回簽後才能帶入」時，現場想先開完工單會被擋下，需先請業務取得客戶回簽。變更立即生效。",
          choices=[(1, "可以，並提示尚未回簽（建議）", "畫面會提醒「報價單尚未回簽，項目可能再變」。"),
                   (0, "要等客戶回簽後才能帶入", "報價單未回簽時不能帶入，避免依據還會變動的項目開單。")]),
        S("qty_mode", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="帶入時，每個項目的數量預設填多少？", label="帶入數量的預設",
          help="分批完工時，若前面的完工單已經完成一部分，預設只填剩下的部分。",
          impact="只影響帶入當下的預設數字，每列都能再改。選「報價全數」時，分批完工的第二張單會重複計入前一張已完成的數量，需要自己減掉。",
          choices=[(0, "只填剩餘未完工的數量（建議）", "已完工的數量（待審核、簽核中、已核准的完工單）會先扣掉；已全數完工的項目預設不帶入。"),
                   (1, "填報價的全部數量", "不扣已完工的數量。")]),
        S("default_status", "int", 0, min=0, max=2, risk="ops", recommended=0,
          question="帶入的項目，完成狀態預設是什麼？", label="帶入項目的預設狀態",
          help="現場只做完一部分時，把該列改成「部分完成」即可。",
          impact="只影響帶入當下的預設，每列都能再改；「部分完成」與「未施作」會出現在完工單的遺留事項提醒。",
          choices=[(0, "完成（建議）", "預設視為已做完，只需修改例外的幾列。"),
                   (1, "部分完成", "預設都標為部分完成，現場逐列確認。"),
                   (2, "未施作", "預設都標為未施作，做完一項再改一項。")]),
        S("include_headers", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="帶入時，要不要一併帶入報價單的分段標題？", label="一併帶入分段標題",
          help="分段標題只是分組用的標題列，沒有數量。",
          impact="只影響帶入當下的畫面。", advanced=True,
          choices=[(1, "一併帶入（建議）", "完工單的項目分組與報價單一致。"), (0, "不帶入標題", "只帶有數量的項目。")]),
        S("brand_prefix", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="帶入時，品名前面要不要加上品牌？", label="品名前加品牌",
          help="例如報價單的品牌「某牌」、品名「攝影機」，帶入後顯示為「某牌 攝影機」。",
          impact="只影響帶入當下的品名文字，之後仍可修改。", advanced=True,
          choices=[(1, "加上品牌（建議）", "品名會是「品牌 品名」。"), (0, "只帶品名", "品牌不帶入。")]),
        S("over_qty", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          question="某個項目的完工數量加總超過報價數量時，要怎麼處理？", label="完工數量超過報價數量",
          help="現場多做、或報價單後來有增補，都是真實會發生的情況。",
          impact="影響之後儲存完工單的人。選「擋下」時，多做的部分要先修改報價單才能儲存；已存的完工單不受影響。",
          choices=[(0, "警示但仍可儲存（建議）", "該列會標黃色並顯示超過多少，仍然可以儲存。"),
                   (1, "擋下，不能儲存", "超過的部分需要先改報價單的數量，或調整完工單的數量。")]),
    ],
    sensitive=False, risk="ops",
    help="完工單從報價單帶入項目時的預設行為。誰能建立或編輯完工單屬權限設定，不在這裡（目前仍限管理員）。",
)
