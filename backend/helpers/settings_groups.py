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


def _download_name_check(values):
    """文件類型用語：每項 1～10 個字、不含控制字元或換行（設定中心用白話訊息擋下，而不是悄悄忽略）。"""
    problems = []
    for k, v in values.items():
        if k.startswith("label_") and isinstance(v, str):
            s = v.strip()
            if not 1 <= len(s) <= 10:
                problems.append("文件類型用語要 1～10 個字")
            elif any(ord(c) < 32 or ord(c) == 127 for c in v):
                problems.append("文件類型用語不可含換行或控制字元")
    return sorted(set(problems))


# 下載檔名（A7 第一期；設計 DOWNLOAD-FILENAME-CASE-T56.md r6）：預設＝使用者 10-12 的決定。檔名永不含金額（標籤白名單鎖在 helpers/download_name.py）。
# 放寬（顯示客戶名稱、對沒有案件權限的人顯示案件名、勞報單由不顯示改顯示）要另一位最高管理者核准並等確認期間；收緊立即生效。
register_group(
    "download_name", "下載檔名",
    [
        S("name_layout", "int", 0, min=0, max=3, risk="ops", recommended=0,
          question="下載的檔案名稱要由哪些項目組成？", label="檔名組成",
          help="預設把案件編號、案件名、文件類型、單號串在一起，一眼看得出是哪個案件的什麼文件。單號一定會保留。",
          impact="影響範圍：之後下載的案件文件（報價單、完工單、出貨單、請款單、開票申請、承攬商傳票、費用單、獎金分配單、勞報單、會計傳票）的檔名；不影響單據內容、權限與已下載的檔案。檔名不會出現任何金額。",
          choices=[(0, "案件編號＋案件名＋文件類型＋單號（建議）", "依序是案件編號、案件名、文件類型、單號，中間用分隔符號連起來。檔名較長，過長時會先縮短案件名。"),
                   (1, "案件編號＋文件類型＋單號", "不放案件名，檔名較短，也不會在檔名裡洩漏案件名稱。"),
                   (2, "文件類型＋單號", "只看得出是什麼文件與單號，看不出屬於哪個案件。"),
                   (3, "只用單號", "與改版前相同，檔名只有單號。")]),
        S("separator", "int", 0, min=0, max=2, risk="none", recommended=0,
          question="檔名各項目之間用什麼符號隔開？", label="分隔符號", help="只影響檔名的外觀。",
          impact="影響範圍：之後下載的檔名；已下載的檔案不會被改名。",
          choices=[(0, "底線（建議）", "各項目之間用底線連接。"), (1, "減號", "各項目之間用減號連接。"),
                   (2, "空白", "各項目之間用空白連接；有些系統對空白的處理不一致。")]),
        S("case_name_source", "int", 0, min=0, max=2, risk="security", loosen="up", recommended=0,
          question="檔名裡的「案件名」要用哪個名稱？", label="案件名用哪個名稱",
          help="預設用專案名稱。客戶名稱可能是機敏資訊，而且會跟著檔案出現在下載資料夾、雲端同步與信件附件裡。",
          impact="影響範圍：之後下載的案件文件檔名中的案件名；只有讀得到該案件的人才會在檔名看到名稱。改成含客戶名稱後，客戶名稱會寫進檔名並隨檔案擴散，無法收回。",
          risk_text="客戶名稱會出現在檔名裡，並跟著檔案存到下載資料夾、雲端硬碟與郵件附件；檔案一旦外傳，無法再收回名稱。",
          choices=[(0, "專案名稱（建議）", "只放專案名稱。"), (1, "專案名稱加客戶名稱", "兩個名稱都放，檔名更長，客戶名稱會擴散到下載資料夾與信件。"),
                   (2, "客戶名稱", "只放客戶名稱，客戶名稱會擴散到下載資料夾與信件。")]),
        S("no_access", "int", 1, min=0, max=2, risk="security", loosen="up", recommended=1,
          question="沒有該案件權限的人下載文件時，檔名要怎麼處理？", label="沒有案件權限者的檔名",
          help="預設保留案件編號、省略案件名，這樣財務、出納等經手人仍看得出是哪個案件，但看不到案件名稱。",
          impact="影響範圍：能下載該文件、但沒有該案件權限的角色（例如財務、出納、經手人）。改成「顯示案件名」後，這些人會在檔名看到案件名稱，等於放寬了案件名稱的可見範圍。",
          risk_text="沒有案件權限的人也會在檔名看到案件名稱，案件名稱可能含客戶或地點，檔案會被存到下載資料夾與雲端。",
          choices=[(0, "案件編號與案件名都省略（最嚴）", "檔名只剩文件類型與單號。"), (1, "保留案件編號、省略案件名（建議）", "看得出是哪個案件，但看不到案件名稱。"),
                   (2, "顯示案件名", "沒有案件權限的人也會看到案件名稱。")]),
        S("payslip_show_name", "int", 1, min=0, max=1, risk="security", loosen="up", recommended=1,
          question="勞報單的檔名要不要寫出承攬人的姓名？", label="勞報單檔名顯示承攬人姓名",
          help="與改版前相同，預設會寫。只有「有勞報單權限的人」（最高管理者，或被授權使用勞報單的人）才下載得到勞報單。",
          impact="影響範圍：勞報單 PDF 的檔名（只有有勞報單權限的人拿得到）。寫出姓名時，個人資料會出現在檔名裡，並跟著下載資料夾、雲端同步與郵件附件擴散。改成「不寫」是收緊，立即生效；改回「寫」須另一位最高管理者核准。",
          risk_text="承攬人的姓名（個人資料）會寫進檔名，隨檔案存到下載資料夾、雲端硬碟與郵件附件。",
          choices=[(0, "不寫姓名", "檔名只有案件、文件類型與日期或單號。"), (1, "寫出姓名（與改版前相同）", "檔名裡會有承攬人姓名，與改版前相同。")]),
        S("case_name_max_chars", "int", 20, min=5, max=60, unit="字", risk="none", recommended=20, advanced=True,
          question="檔名裡的案件名最多保留幾個字？", label="案件名最多字數", help="太長的案件名會被截短。",
          impact="影響範圍：之後下載的檔名。字數越多越完整，但整個檔名越容易超過系統上限。"),
        S("total_max_chars", "int", 100, min=40, max=150, unit="字", risk="none", recommended=100, advanced=True,
          question="檔名（不含副檔名）最長幾個字？", label="檔名總長上限", help="另外受系統的 255 位元組上限約束；過長時先縮短案件名，單號與副檔名不會被截掉。",
          impact="影響範圍：之後下載的檔名。過長的檔名在某些系統無法儲存或解壓縮。"),
        S("add_date", "int", 0, min=0, max=1, risk="none", recommended=0, advanced=True,
          question="檔名要不要加上日期？", label="檔名加日期", help="預設不加。",
          impact="影響範圍：之後下載、且下載端點有提供日期的文件檔名。",
          choices=[(0, "不加（建議）", "與預設檔名相同。"), (1, "加日期", "在單號前面加上單據日期。")]),
        S("label_quotation", "str", '報價單', risk="none", recommended='報價單', advanced=True,
          question="下載檔名裡「報價單」要寫成什麼字？", label="文件類型用語：報價單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的報價單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_quotation_version", "str", '報價單存檔版本', risk="none", recommended='報價單存檔版本', advanced=True,
          question="下載檔名裡「報價單存檔版本」要寫成什麼字？", label="文件類型用語：報價單存檔版本", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的報價單存檔版本檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_close_report", "str", '結案報表', risk="none", recommended='結案報表', advanced=True,
          question="下載檔名裡「結案報表」要寫成什麼字？", label="文件類型用語：結案報表", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的結案報表檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_execution_report", "str", '專案執行報告', risk="none", recommended='專案執行報告', advanced=True,
          question="下載檔名裡「專案執行報告」要寫成什麼字？", label="文件類型用語：專案執行報告", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的專案執行報告檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_completion", "str", '完工單', risk="none", recommended='完工單', advanced=True,
          question="下載檔名裡「完工單」要寫成什麼字？", label="文件類型用語：完工單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的完工單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_expense_form", "str", '費用單', risk="none", recommended='費用單', advanced=True,
          question="下載檔名裡「費用單」要寫成什麼字？", label="文件類型用語：費用單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的費用單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_shipping", "str", '出貨單', risk="none", recommended='出貨單', advanced=True,
          question="下載檔名裡「出貨單」要寫成什麼字？", label="文件類型用語：出貨單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的出貨單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_payment_request", "str", '請款單', risk="none", recommended='請款單', advanced=True,
          question="下載檔名裡「請款單」要寫成什麼字？", label="文件類型用語：請款單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的請款單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_invoice_voucher", "str", '開票申請', risk="none", recommended='開票申請', advanced=True,
          question="下載檔名裡「開票申請」要寫成什麼字？", label="文件類型用語：開票申請", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的開票申請檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_contractor_voucher", "str", '承攬商傳票', risk="none", recommended='承攬商傳票', advanced=True,
          question="下載檔名裡「承攬商傳票」要寫成什麼字？", label="文件類型用語：承攬商傳票", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的承攬商傳票檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_payslip", "str", '勞報單', risk="none", recommended='勞報單', advanced=True,
          question="下載檔名裡「勞報單」要寫成什麼字？", label="文件類型用語：勞報單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的勞報單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_bonus_award", "str", '獎金分配單', risk="none", recommended='獎金分配單', advanced=True,
          question="下載檔名裡「獎金分配單」要寫成什麼字？", label="文件類型用語：獎金分配單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的獎金分配單檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
        S("label_voucher", "str", '傳票', risk="none", recommended='傳票', advanced=True,
          question="下載檔名裡「傳票」要寫成什麼字？", label="文件類型用語：傳票", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的傳票檔名。已經下載的檔案不會被改名；改回預設隨時可以。"),
    ],
    sensitive=False, risk="security", cross_check=_download_name_check,
    help="下載文件時的檔案名稱怎麼組成、沒有案件權限的人看到什麼。檔名永遠不含金額。",
)
