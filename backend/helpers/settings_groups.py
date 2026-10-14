# -*- coding: utf-8 -*-
"""設定群組登錄（L1；第 54 班 Train A）。**預設值＝上線前的程式常數**（部署零行為變更；`settings_deploy_baseline.json` 凍結）。

[單位] helper:settings_groups    [層] L1    [穩定度] 契約
[公開介面] UNAVAILABLE_ALT_CHOICES
[不變式] 載入時登錄群組 change_control、retention、uploads（沒有對外名稱，只有登錄的副作用）；預設值改動＝行為變更，必須同步改凍結基準並走裁示；上下限只寫在這裡；副檔名白名單不在此可調（安全邊界）。
    畫面文字規則（零技術門檻）：問句、標籤、說明、影響說明一律白話繁中，內部鍵不顯示給使用者（守門 test_settings_ui_plain_language）。
[契約題] backend/tests/platform/test_settings_registry_t54.py
"""
from core import registry as _reg
from helpers.settings_registry import SettingDef as S
from helpers.settings_registry import register_group as _register_group


def _register_core(group, label, fields, *, sensitive=False, risk="ops", legacy_key=None, cross_check=None, help="", owner=None):
    """本檔的群組一律屬於 core：本檔可能在某個模組的 import 範圍內被第一次 import（例如模組 import 了本檔），
    不蓋 core 章的話那個模組就成了核心群組的擁有者（它載入失敗時 `unregister_owner` 會把核心群組一併刪掉）。"""
    with _reg.owner_scope("core"):
        return _register_group(group, label, fields, sensitive=sensitive, risk=risk, legacy_key=legacy_key,
                               cross_check=cross_check, help=help, owner=owner)


#: 合併安全：其他分支（M3 擇一方案、完工單、材料申請、下載檔名、專案毛利…）會在本檔追加區塊並呼叫 `register_group(`——
#: 名稱必須還在，而且它們的群組同樣屬於 core。（本檔不再 import 註冊函式本名，這個別名接住那些區塊。）
register_group = _register_core

# 舊 PATCH /api/settings/backup-retention 的範圍：天數 1–3650、月備份 0–3650（0＝永久）、更新前快照份數 0–100。
# 稽核紀錄保存期限另加法遵下限 365（無上限）；讀取時向上夾到 365（舊庫裡低於 365 的值不會讓稽核被提早清掉）。
_BACKUP_IMPACT = "只影響之後的清理：超過天數的舊備份會在下一次例行清理時被刪除，已刪除的備份無法找回；改大則不會補回已刪的。調長立即生效；縮短（會更早刪除）屬放寬，須另一位最高管理者核准，並等「變更確認期間」後才生效。"

_register_core(
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

_register_core(
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

_register_core(
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
_register_core(
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



# 材料卡片認列已核准採購單（T57；MATERIAL-LINK-BUG-T57）：預設＝使用者 10-13 的話「非超級管理員自動帶入要取消、寄信通知管理員」。
# 放寬（讓有案件權限的人也能認列、關閉通知、提高寄信上限）要另一位最高管理者核准並等確認期間；收緊立即生效。收件人在「信件與通知收件設定」維護（只有一個來源）。
register_group(
    "material_recognition", "材料卡片認列採購單",
    [
        S("who_may", "int", 1, min=1, max=2, risk="security", loosen="up", recommended=1, requires_pending=True,
          question="誰可以把已核准的採購單「認列」到材料卡片（讓卡片能勾已申購／已到料）？", label="誰可以認列採購單",
          help="認列不經過材料申請的審核流程，所以預設只有最高管理者可以。其他人按下「帶入並連結」時，系統會取消這次動作。",
          impact="影響範圍：案件管理的材料卡片。放寬後，管理員與專案經理也能認列，認列後即可勾已申購與已到料（已到料會影響庫存序號）。已認列的卡片不受影響。",
          risk_text="【高影響】放寬後，沒有走審核的人也能讓材料卡片標示為已申購、已到料，並認領庫存序號。",
          impact_scope={"documents": ["案件材料卡片的已申購／已到料旗標", "庫存序號認領"], "roles": ["管理員", "有財務檢視權的專案經理"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          choices=[(1, "只有最高管理者（建議）", "其他人嘗試時取消，並依下一題通知管理員。"),
                   (2, "管理員與專案經理也可以", "能編輯材料申請的人（管理員以上，或有財務檢視權的專案經理）可以認列，不需要最高管理者核准；仍會留下稽核記錄。其他角色仍不行。")]),
        S("on_denied", "int", 1, min=1, max=2, risk="security", loosen="up", recommended=1,
          question="有人沒有權限卻嘗試認列時，要怎麼處理？", label="被拒時要不要通知管理員",
          help="不論選哪個，這次認列都會被取消，而且一定留下稽核記錄。",
          impact="影響範圍：被拒時是否寄信給管理員（收件人在「信件與通知收件設定」）。信內不含金額與採購單明細。",
          risk_text="選「只取消」後，管理員不會收到信，只能事後翻稽核記錄才知道有人嘗試。",
          impact_scope={"documents": ["認列被拒的通知信"], "roles": ["管理員"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          choices=[(1, "取消並寄信通知管理員（建議）", "寄給管理員：案件、材料卡片、嘗試的帳號與時間。同一人同一案件同一張採購單在時間窗內只寄一次。"),
                   (2, "只取消，不寄信", "只留稽核記錄。")]),
        S("mail_window_minutes", "int", 60, min=1, max=1440, unit="分鐘", risk="ops", loosen="down", recommended=60, advanced=True,
          question="同一個人對同一案件、同一張採購單重複嘗試時，隔多久才再寄一次通知？", label="重複通知的間隔",
          help="避免有人反覆按而洗版。", impact="影響範圍：只影響通知信的頻率，不影響取消與稽核記錄。調短會讓管理員收到更多信。"),
        S("mail_cap", "int", 10, min=1, max=200, unit="封", risk="ops", loosen="up", recommended=10, advanced=True,
          question="上面那段時間內，這類通知信最多寄幾封？", label="通知信上限",
          help="達到上限後不再寄信，但每次嘗試仍會留稽核記錄。", impact="影響範圍：只影響通知信的數量，不影響取消與稽核記錄。"),
    ],
    sensitive=True, risk="security",
    help="材料卡片「帶入並連結」（認列已核准的採購單）的權限，以及被拒時的通知方式。",
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
          impact_scope={"documents": ["案件文件的下載檔名"], "roles": ["讀得到該案件的人"], "amounts": "不涉及金額，只改檔名裡的名稱。", "reversible": False, "effective": "pending"},
          choices=[(0, "專案名稱（建議）", "只放專案名稱。"), (1, "專案名稱加客戶名稱", "兩個名稱都放，檔名更長，客戶名稱會擴散到下載資料夾與信件。"),
                   (2, "客戶名稱", "只放客戶名稱，客戶名稱會擴散到下載資料夾與信件。")]),
        S("no_access", "int", 1, min=0, max=2, risk="security", loosen="up", recommended=1,
          question="沒有該案件權限的人下載文件時，檔名要怎麼處理？", label="沒有案件權限者的檔名",
          help="預設保留案件編號、省略案件名，這樣財務、出納等經手人仍看得出是哪個案件，但看不到案件名稱。",
          impact="影響範圍：能下載該文件、但沒有該案件權限的角色（例如財務、出納、經手人）。改成「顯示案件名」後，這些人會在檔名看到案件名稱，等於放寬了案件名稱的可見範圍。",
          risk_text="沒有案件權限的人也會在檔名看到案件名稱，案件名稱可能含客戶或地點，檔案會被存到下載資料夾與雲端。",
          impact_scope={"documents": ["案件文件的下載檔名"], "roles": ["財務", "出納", "經手人等沒有該案件權限但能下載文件的人"], "amounts": "不涉及金額，只改檔名是否出現案件編號與案件名。", "reversible": False, "effective": "pending"},
          choices=[(0, "案件編號與案件名都省略（最嚴）", "檔名只剩文件類型與單號。"), (1, "保留案件編號、省略案件名（建議）", "看得出是哪個案件，但看不到案件名稱。"),
                   (2, "顯示案件名", "沒有案件權限的人也會看到案件名稱。")]),
        S("payslip_show_name", "int", 1, min=0, max=1, risk="security", loosen="up", recommended=1,
          question="勞報單的檔名要不要寫出承攬人的姓名？", label="勞報單檔名顯示承攬人姓名",
          help="與改版前相同，預設會寫。只有「有勞報單權限的人」（最高管理者，或被授權使用勞報單的人）才下載得到勞報單。",
          impact="影響範圍：勞報單 PDF 的檔名（只有有勞報單權限的人拿得到）。寫出姓名時，個人資料會出現在檔名裡，並跟著下載資料夾、雲端同步與郵件附件擴散。改成「不寫」是收緊，立即生效；改回「寫」須另一位最高管理者核准。",
          risk_text="承攬人的姓名（個人資料）會寫進檔名，隨檔案存到下載資料夾、雲端硬碟與郵件附件。",
          impact_scope={"documents": ["勞報單 PDF 的下載檔名"], "roles": ["有勞報單權限的人"], "amounts": "不涉及金額，只改檔名是否寫出承攬人姓名。", "reversible": False, "effective": "pending"},
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


# ── BP-1（建構器 第一刀）：各畫面是否啟用「管理者自訂版面」（欄位顯示／順序／標籤）。預設全關＝上線前的畫面（部署零行為變更）。 ──
# 一個畫面一個欄位（builder.layout.<畫面>）；啟用後該畫面才會讀版面定義（公司／角色），超級管理員才看得到「編輯版面」。
register_group(
    "builder_layout", "自訂畫面版面",
    [
        S("suppliers", "bool", False, risk="ops", recommended=False,
          question="供應商管理頁，要開放管理者自訂欄位的顯示、順序與名稱嗎？", label="供應商管理頁可自訂版面",
          help="開啟後，最高管理者可以在供應商管理頁按「編輯版面」，調整列表欄位的顯示、順序與名稱，並可預覽、發布與還原。",
          impact="只影響供應商管理頁的列表欄位顯示。關閉時畫面與現在完全相同；開啟後，已發布的版面才會套用給對應角色。金額與權限的限制不會因版面而放寬，核心欄位不能隱藏。可隨時關閉。",
          choices=[(False, "不開放（建議）", "供應商管理頁維持目前的欄位與順序。"),
                   (True, "開放自訂版面", "最高管理者可編輯並發布版面，發布後所有人依角色套用。")]),
        S("case_management", "bool", False, risk="ops", recommended=False,
          question="案件管理頁的案件清單，要開放管理者自訂卡片欄位的顯示與順序嗎？", label="案件管理頁可自訂版面",
          help="開啟後，最高管理者可以在案件管理頁的清單上按「編輯版面」，調整案件卡片上各項資訊的顯示、順序與名稱，並可預覽、發布與還原。",
          impact="只影響案件管理頁左側案件清單（卡片）的顯示。關閉時畫面與現在完全相同；開啟後，已發布的版面才會套用給對應角色。金額與權限的限制不會因版面而放寬（看不到金額的人，版面顯示金額欄也只會看到「—」），案號與狀態不能隱藏。可隨時關閉。",
          choices=[(False, "不開放（建議）", "案件清單維持目前的卡片內容與順序。"),
                   (True, "開放自訂版面", "最高管理者可編輯並發布版面，發布後所有人依角色套用。")]),
        S("procurement", "bool", False, risk="ops", recommended=False,
          question="採購管理頁（材料到料清單），要開放管理者自訂欄位的顯示、順序與名稱嗎？", label="採購管理頁可自訂版面",
          help="開啟後，最高管理者可以在採購管理頁按「編輯版面」，調整列表欄位的顯示、順序與名稱，並可預覽、發布與還原。",
          impact="只影響採購管理頁的列表欄位顯示。關閉時畫面與現在完全相同；開啟後，已發布的版面才會套用給對應角色。權限的限制不會因版面而放寬，核心欄位不能隱藏。可隨時關閉。",
          choices=[(False, "不開放（建議）", "採購管理頁維持目前的欄位與順序。"),
                   (True, "開放自訂版面", "最高管理者可編輯並發布版面，發布後所有人依角色套用。")]),
        S("devices", "bool", False, risk="ops", recommended=False,
          question="設備登載頁（設備清單），要開放管理者自訂欄位的顯示、順序與名稱嗎？", label="設備登載頁可自訂版面",
          help="開啟後，最高管理者可以在設備登載頁按「編輯版面」，調整列表欄位的顯示、順序與名稱，並可預覽、發布與還原。",
          impact="只影響設備登載頁的列表欄位顯示。關閉時畫面與現在完全相同；開啟後，已發布的版面才會套用給對應角色。權限的限制不會因版面而放寬，核心欄位不能隱藏。可隨時關閉。",
          choices=[(False, "不開放（建議）", "設備登載頁維持目前的欄位與順序。"),
                   (True, "開放自訂版面", "最高管理者可編輯並發布版面，發布後所有人依角色套用。")]),
        S("vendor_contractors", "bool", False, risk="ops", recommended=False,
          question="承攬商管理頁（承攬商清單），要開放管理者自訂欄位的顯示、順序與名稱嗎？", label="承攬商管理頁可自訂版面",
          help="開啟後，最高管理者可以在承攬商管理頁按「編輯版面」，調整列表欄位的顯示、順序與名稱，並可預覽、發布與還原。",
          impact="只影響承攬商管理頁的列表欄位顯示。關閉時畫面與現在完全相同；開啟後，已發布的版面才會套用給對應角色。權限的限制不會因版面而放寬，核心欄位不能隱藏。可隨時關閉。",
          choices=[(False, "不開放（建議）", "承攬商管理頁維持目前的欄位與順序。"),
                   (True, "開放自訂版面", "最高管理者可編輯並發布版面，發布後所有人依角色套用。")]),
    ],
    sensitive=False, risk="ops",
    help="決定哪些畫面開放管理者自訂版面：供應商管理頁、案件管理頁的案件清單與表單、採購管理頁、設備登載頁、承攬商管理頁。",
)


# 建構器治理（BP-1，t59）：版本帳本／任兩版差異／發布前影響預覽。預設關（＝今天的行為，新路由一律 404、畫面不出現）；不碰資料庫結構。
register_group(
    "builder_governance", "建構器治理（版本帳本與發布前影響預覽）",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="要不要開啟定義的版本帳本與發布前影響預覽？", label="版本帳本與影響預覽",
          help="開啟後，版面、輸出版型、自訂欄位的編輯畫面會多出「版本帳本」（列出每一版、比較任兩版、一鍵還原）與發布前的「影響預覽」。",
          impact="只增加檢視與預覽，不改變任何已發布的定義，也不改變發布與還原本身的行為。預覽只留一筆『看過預覽』的稽核。",
          choices=[(0, "關閉（預設）", "畫面與今天完全一樣。"), (1, "開啟", "編輯畫面多出版本帳本與影響預覽。")]),
        S("enforce_layout", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["版面與選單的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="版面（含選單）發布前，要不要強制先看過同一份草稿的影響預覽？", label="版面發布前強制預覽",
          help="建議同時開啟上面的「版本帳本與影響預覽」；即使之後把總開關關掉，已開啟的強制仍然有效（要解除只能關掉這個開關，且屬放寬、需第二位核准）。開啟後，版面與選單的發布若沒有帶著『看過的預覽』就會被擋下（沒有例外）。",
          impact="只在發布當下多一道檢查。選單編輯器會自動帶上預覽；版面編輯器若尚未接上，開啟後就無法發布版面，請先確認編輯器已更新。關閉強制屬於放寬，需經確認期間與另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與今天相同。"), (1, "強制", "沒看過預覽就不能發布版面。")]),
        S("enforce_custom_fields", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["自訂欄位集的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="自訂欄位發布前，要不要強制先看過影響預覽？", label="自訂欄位發布前強制預覽",
          help="同上，對象是自訂欄位集。建議同時開啟「版本帳本與影響預覽」；關掉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；欄位編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需經確認期間與另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與今天相同。"), (1, "強制", "沒看過預覽就不能發布自訂欄位。")]),
        S("enforce_user_buttons", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["使用者自訂按鈕的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="自訂按鈕發布前，要不要強制先看過影響預覽？", label="自訂按鈕發布前強制預覽",
          help="同上，對象是使用者自訂按鈕。建議同時開啟「版本帳本與影響預覽」；關掉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；按鈕編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需經確認期間與另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與今天相同。"), (1, "強制", "沒看過預覽就不能發布自訂按鈕。")]),
        S("enforce_output_template", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["輸出版型（列印／PDF）的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="輸出版型（列印／PDF）發布前，要不要強制先看過影響預覽？", label="輸出版型發布前強制預覽",
          help="同上，對象是輸出版型。建議同時開啟「版本帳本與影響預覽」；關掉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；版型編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需經確認期間與另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與今天相同。"), (1, "強制", "沒看過預覽就不能發布輸出版型。")]),
        S("enforce_rule_set", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=1,
          impact_scope={"documents": ["規則集（標示規則）的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="規則集發布前，要不要強制先看過影響預覽？", label="規則發布前強制預覽",
          help="建議開啟：規則頁一律會送出預覽，開了之後沒看過預覽就不能發布規則。關掉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；規則頁已內建預覽，建議在規則功能上線時就開啟。關閉強制屬於放寬，需經確認期間與另一位最高管理者核准才生效。",
          choices=[(0, "不強制", "發布行為與其他定義相同。"), (1, "強制（建議）", "沒看過預覽就不能發布規則集。")]),
    ],
    sensitive=False, risk="ops",
    help="定義（版面、輸出版型、自訂欄位）的版本帳本與發布前影響預覽的開關。",
)


# 規則引擎（標示型；BP-2，t62）：條件 → 標紅／提醒。預設關＝所有畫面與回應與今天逐位元相同（規則路由 404、不載入任何前端）。
# 只有『標示』：不寫欄位值、不改狀態、不擋存檔、不發通知。門檻在系統內可改，發布走治理層（預覽、版本帳本、放寬需第二位核准）。
register_group(
    "builder_rules", "規則（標示型）",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="要不要開放最高管理者設定『條件成立就標紅／提醒』的規則？", label="開放標示規則",
          help="開啟後，最高管理者可以在規則頁用下拉選單設定條件（例如毛利低於多少就標紅），發布前可預覽現有紀錄有哪些會被標示。",
          impact="規則只標示、不阻擋：不會改任何資料、不會擋住存檔，也不會發通知。看不到來源欄位的人（例如沒有成本權限者）不會看到由該欄位產生的標示。規則故障時只會暫停該條規則並提醒管理員。可隨時關閉。",
          choices=[(0, "關閉（預設）", "畫面與今天完全一樣。"), (1, "開啟", "規則頁可用，已發布的規則會在宣告了規則插槽的畫面上標示。")]),
        S("k01_seed", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="要不要把報價單的『專案毛利提醒門檻』改由規則管理？", label="專案毛利提醒改由規則管理",
          help="開啟後，規則頁會多一個「匯入現有利潤警示」：把目前的門檻（設定中心的專案毛利提醒門檻）轉成一條規則。規則發布後，報價單的提醒門檻就以該規則為準，之後在規則頁調整（可預覽、有版本、調低門檻需第二位最高管理者核准）；規則發布之前，行為完全不變。",
          impact="報價單內部損益區的提醒畫面與今天相同（只在專案毛利低於門檻時用警示色標出，不阻擋存檔、送審）；只有看得到成本與毛利的人會看到。需先開啟『開放標示規則』。可隨時關閉，關閉後門檻回到設定中心的值。",
          choices=[(0, "不使用（預設）", "門檻仍由設定中心的數字決定。"), (1, "使用", "門檻改由規則決定（發布規則後生效）。")]),
    ],
    sensitive=False, risk="ops",
    help="標示型規則是否開放。需要先開啟「建構器治理」才有版本帳本與影響預覽。",
)


# 選單建構器（BP-1；設計 PLATFORM-BUILDER-ARCHITECTURE-T57 §2.1 積木 5）：預設關＝今天的側欄逐字不變。
# 開啟後最高管理者可以在側欄上改項目名稱、換到另一個既有群組，並在發布前預覽整份選單；只改顯示，不改任何人的權限。
register_group(
    "builder_menu", "選單建構器",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="要不要讓最高管理者自行調整側欄選單的名稱與分組？", label="開放調整選單名稱與分組",
          help="開啟後，最高管理者可以改側欄項目的顯示名稱、把項目移到另一個既有群組，並在發布前預覽整份選單。",
          impact="只影響側欄怎麼顯示，不改任何人的權限：沒有權限的項目仍然不會出現，改名與換群組也不會讓人多看到任何東西。關閉後，已發布的改名與換群組會停止套用（資料保留），側欄回到原本的名稱與分組。立即生效。",
          choices=[(0, "不開放（建議）", "側欄維持系統預設的名稱與分組。"),
                   (1, "開放", "最高管理者可以在排版時改側欄項目名稱、換分組，並預覽整份選單。")]),
    ],
    sensitive=False, risk="ops",
    help="側欄選單的名稱與分組是否開放給最高管理者調整；預設關閉。",
)
