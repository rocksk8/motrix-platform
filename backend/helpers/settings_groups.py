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

# 擇一方案報價（M3；T57）：文字範本、數量上限，以及回簽政策 P1～P8。政策的選項值為整數代碼（畫面只顯示中文標籤）、依序「由嚴到寬」，第一項＝使用者 2026-10-12 的定案值（預設，管理者可改）。
# 『尚未提供』的選項照樣登錄但不可選：cross_check 擋下儲存、讀取端（modules.case.alt_policy）夾回預設；標籤自動加註『（尚未提供）』。
# 凡是還沒有程式會用到的放寬路徑，一律先列在這裡；由實作該路徑的任務在自己的 commit 把它從表中移除（T9 起陸續開放）。
UNAVAILABLE_ALT_CHOICES = {"cancel_after_deal": (2,), "move_out_of_sent": (2,), "reject_final_keep": (2,),
                           "approval_basis": (2,), "cancel_after_export": (2,),
                           "cancel_after_invoice": (2,), "cancel_after_settle": (2,)}
_NA = "（尚未提供）"
_TEXT_MAX = {"total_text": 40, "note_template": 200}
_PLACEHOLDERS = ("{items}", "{group}")
_ALT_BANNER = "【高影響】選這個之後，已回簽的擇一報價單會有更多方式被改動或取消選定，可能讓報價、開票、請款、精算的金額彼此不一致；每次變更都會記入設定變更明細。"


def _mark_na(key, choices):
    bad = UNAVAILABLE_ALT_CHOICES.get(key, ())
    return [(v, (l + _NA) if (v in bad and _NA not in l) else l, i) for v, l, i in choices]


def _alt_policy(key, question, label, help_, choices, *, risk_text=_ALT_BANNER):
    choices = _mark_na(key, choices)
    return S(key, "int", 1, min=1, max=len(choices), risk="money", loosen="up", recommended=1, requires_pending=True,
             question=question, label=label, help=help_,
             impact="影響已回簽的擇一方案報價單（以及同一案件下游的開票、請款、精算金額）；只影響之後的操作，已存在的單據內容不會被改寫。" + "放寬（往後面的選項）須原因、另一位最高管理者核准並等確認期間；收緊立即生效。",
             risk_text=risk_text, choices=choices)


def _alt_cross_check(values):
    out = []
    for k, mx in _TEXT_MAX.items():
        v = values.get(k)
        if not isinstance(v, str):
            continue
        if len(v) > mx:
            out.append({"path": k, "message": "文字太長，最多 %d 字" % mx})
        elif any(ord(c) < 32 or ord(c) == 127 for c in v):
            out.append({"path": k, "message": "文字不能含換行或控制字元"})
        elif k == "note_template":
            rest = v
            for p in _PLACEHOLDERS:
                rest = rest.replace(p, "")
            if "{" in rest or "}" in rest:
                out.append({"path": k, "message": "大括號只能用在系統提供的兩個代入位置，其他地方請拿掉"})
    for k, bad in UNAVAILABLE_ALT_CHOICES.items():
        if values.get(k) in bad:
            out.append({"path": k, "message": "這個選項尚未提供，請選其他項目"})
    return out


register_group(
    "quote_alt", "擇一方案", [
        S("alt_enabled", "bool", True, risk="ops", recommended=True,
          question="報價單要不要提供「擇一方案」功能？", label="啟用擇一方案",
          help="開啟後，報價單的品項可以標成『擇一』（例如三種方案只能選一種）。關閉只是不顯示相關欄位，已經含擇一的舊單仍照原樣計算與列印。",
          impact="只影響報價單編輯畫面是否顯示擇一欄位；既有含擇一的報價單金額與列印不變。立即生效。"),
        S("total_text", "str", "依方案選擇", risk="legal", recommended="依方案選擇",
          question="報價單尚未選定方案時，稅前合計與總計那兩格要顯示什麼字？", label="合計欄位顯示文字",
          help="客戶看到的報價單，在還沒選定方案之前，稅前合計與總計兩格會改顯示這段文字。",
          impact="只影響之後存檔的報價單；已存檔的報價單沿用當時的文字（存檔時會記下）。客戶看得到這段文字。",
          risk_text="這段文字會印在給客戶的報價單上，請確認措辭不會讓客戶誤解金額。"),
        S("note_template", "str", "項次{items}為{group}擇一方案選擇", risk="legal", recommended="項次{items}為{group}擇一方案選擇",
          question="報價單備註要自動帶哪一句擇一說明？", label="擇一說明句",
          help="每一組擇一方案會自動產生一句說明，接在備註最後。編輯時可從按鈕插入「項次」與「組別名稱」兩個代入位置，存檔時系統會自動換成該組的實際內容。",
          impact="只影響之後存檔的報價單；已存檔的報價單沿用當時的句子。客戶看得到這句話。",
          risk_text="這句話會印在給客戶的報價單上，請確認措辭正確。"),
        S("show_unpicked_in_pdf", "bool", False, risk="ops", recommended=False,
          question="客戶選定方案後，列印的報價單要不要保留沒被選到的項目（灰字標示『未選』）？", label="列印顯示未選項目",
          help="預設不印沒被選到的項目。",
          impact="只影響之後列印／匯出的報價單 PDF 與 Excel，不改變任何金額。"),
        S("alt_groups_max", "int", 10, min=1, max=20, unit="組", risk="ops", loosen="up", recommended=10, advanced=True,
          question="一張報價單最多可以有幾組擇一方案？", label="擇一組數上限",
          help="組數越多，內部比較的組合數會暴增。超過上限的報價單無法存檔。",
          impact="只影響之後存檔的報價單；已超過新上限的舊單不會被刪除，但改動時需先減少組數。"),
        S("combo_view_max", "int", 24, min=1, max=200, unit="種", risk="ops", recommended=24, advanced=True,
          question="內部「方案組合比較」最多列出幾種組合？", label="組合比較列數",
          help="只影響內部成本比較畫面（客戶看不到）。超過的組合只顯示總數。",
          impact="只影響內部畫面，不影響任何金額、列印或客戶看到的內容。"),
        S("combo_view_default_open", "bool", False, risk="ops", recommended=False, advanced=True,
          question="開啟報價單時，內部「方案組合比較」要不要預設展開？", label="組合比較預設展開",
          help="預設收合，要看時再展開，開單比較快。",
          impact="只影響內部畫面的預設狀態。"),
        _alt_policy("lock_scope", "客戶回簽之後，報價單的哪些內容不能再改？", "回簽後鎖定範圍", "決定已回簽的擇一報價單，哪些欄位會被鎖住。要改就先「取消回簽」。",
                    [(1, "鎖定整份報價本文（建議）", "品項、金額、備註與報價附件全部不能改；要改請先取消回簽。"),
                     (2, "只鎖品項與金額", "備註與報價附件仍可編輯，品項、單價、數量、擇一設定不能改。")]),
        _alt_policy("cancel_after_deal", "案件已成案之後，還可以取消回簽嗎？", "成案後取消回簽", "取消回簽會清除客戶選定的方案，金額回到未選定的暫估。",
                    [(1, "不行，需先處理下游（建議）", "已成案的案件不能取消回簽；請先把案件改回未成案。"),
                     (2, "可以，並連動清除下游衍生資料" + _NA, "取消回簽時，同步重算或標記下游依報價金額衍生的資料。"),
                     (3, "可以，只提醒", "照常取消回簽，並提醒『下游金額可能與報價不一致』，不連動修改。")]),
        _alt_policy("move_out_of_sent", "已回簽的擇一單，可以被改成草稿、已取消或已拒絕嗎？", "已回簽單改變狀態", "指「改狀態」「收回」「退回」等會讓單據離開『已送出』的操作。",
                    [(1, "不行（建議）", "一律擋下並提示『請管理員取消回簽』。"),
                     (2, "可以，並自動清除選定", "比照取消回簽：通過下游檢查後同步清除選定，再進入新狀態。")]),
        _alt_policy("reject_final_keep", "已回簽的擇一單被「拒絕結案」時，客戶選定的方案要保留還是清除？", "拒絕結案時的選定", "拒絕結案是終局動作。",
                    [(1, "保留（建議）", "拒絕結案之後選定與金額原樣保留。"),
                     (2, "清除", "比照取消回簽：通過下游檢查後清除選定。")]),
        _alt_policy("unlock_edit_signed", "最高管理者可以對已回簽的擇一單做「解鎖修改」嗎？", "解鎖修改已回簽單", "解鎖修改會讓單據回到待審核狀態。",
                    [(1, "不行（建議）", "一律擋下並提示『請管理員取消回簽』。"),
                     (2, "可以", "允許進入解鎖修改；期間仍受『回簽後鎖定範圍』限制。")]),
        S("approval_basis", "int", 1, min=1, max=2, risk="money", loosen="up", recommended=1, requires_pending=True,
          question="擇一方案的報價單送審時，審核原因用哪個金額來判斷？", label="擇一單送審金額基準",
          help="目前審核原因會逐項檢查所有品項（包含還沒被選到的）。",
          impact="只影響之後送審的擇一方案報價單的審核原因清單。放寬須另一位最高管理者核准並等確認期間。",
          risk_text="【高影響】選『只看計入金額的品項』時，沒被選到的低毛利方案不再列入審核原因，可能讓需要主管看的單子直接通過。",
          choices=[(1, "逐項檢查所有品項（最嚴，建議；目前的做法）", "包含還沒被選到的品項都逐一檢查，較不會漏掉需要審核的單。"),
                   (2, "只看計入金額的品項" + _NA, "只檢查實際計入金額的品項（已選定的方案加上一般品項），沒被選到的方案不再列入審核原因。")]),
        _alt_policy("cancel_after_export", "已經匯出給財務的開票憑據／請款單，還可以取消回簽嗎？", "已匯出單據後取消回簽", "匯出後財務已據以開立文件。",
                    [(1, "不行，永久凍結選定方案（建議）", "請財務先作廢該憑據後才能取消回簽。"),
                     (2, "可以，並通知財務" + _NA, "取消回簽並通知財務；已匯出文件本身不會被修改。")]),
        _alt_policy("cancel_after_invoice", "已開票或已請款、但還沒匯出時，可以取消回簽嗎？", "未匯出單據後取消回簽", "單據已建立但還沒匯出給財務時，取消回簽會讓報價金額與該單據不一致。",
                    [(1, "不行，須先撤回該單據（建議）", "請先撤回開票單或請款單再取消回簽。"),
                     (2, "可以，並提醒財務" + _NA, "取消回簽後單據留著，並通知財務其金額與方案不一致。")]),
        _alt_policy("cancel_after_settle", "案件已精算之後，可以取消回簽嗎？", "精算後取消回簽", "精算完結後，成本與利潤已凍結，取消回簽會讓報價金額與精算不一致。",
                    [(1, "不行，須先重開精算（建議）", "請最高管理者先重新開啟精算再取消回簽。"),
                     (2, "可以，並重算精算基準" + _NA, "取消回簽並重算精算基準。")]),
    ],
    sensitive=True, risk="money", cross_check=_alt_cross_check,
    help="報價單「擇一方案」的文字範本、數量上限，以及客戶回簽後的處理規則。",
)

# 專案毛利%（設計 docs/platform/plans/QUOTE-PROJECT-GROSS-MARGIN-T56.md §4.1）：警示門檻，預設 0＝不提醒（今日行為）。只改畫面提示，不阻擋存檔、送審、回簽。
register_group(
    "project_margin", "專案毛利%",
    [
        S("warn_pct", "float", 0, min=0, max=100, unit="%", risk="none", recommended=0,
          question="專案毛利% 低於多少時，在報價單上提醒業務？（0 代表不提醒）", label="專案毛利提醒門檻",
          help="專案毛利% ＝（未稅營業收入 − 未稅品項成本）÷ 未稅營業收入。設成 0 就不提醒；設成例如 20，專案毛利低於 20% 時，報價單的內部損益區會用警示色標出來。",
          impact="只改畫面提示，不影響存檔、送審與審核；只有看得到成本與毛利的人會看到。立即生效。"),
    ],
    sensitive=False, risk="none",
    help="報價單「專案毛利%」的提醒門檻；算式本身固定，不在此調整。",
)
