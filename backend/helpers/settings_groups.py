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


def _register_core(group, label, fields, *, sensitive=False, risk="ops", legacy_key=None, cross_check=None, help="", owner=None,
                   legacy_adapter=None, external=False):
    """本檔的群組一律屬於 core：本檔可能在某個模組的 import 範圍內被第一次 import（例如模組 import 了本檔），
    不蓋 core 章的話那個模組就成了核心群組的擁有者（它載入失敗時 `unregister_owner` 會把核心群組一併刪掉）。"""
    with _reg.owner_scope("core"):
        return _register_group(group, label, fields, sensitive=sensitive, risk=risk, legacy_key=legacy_key,
                               cross_check=cross_check, help=help, owner=owner, legacy_adapter=legacy_adapter, external=external)


#: 合併安全：其他分支（M3 擇一方案、完工單、材料申請、下載檔名、專案毛利…）會在本檔追加區塊並呼叫 `register_group(`——
#: 名稱必須還在，而且它們的群組同樣屬於 core。（本檔不再 import 註冊函式本名，這個別名接住那些區塊。）
register_group = _register_core

# 舊 PATCH /api/settings/backup-retention 的範圍：天數 1–3650、月備份 0–3650（0＝永久）、更新前快照份數 0–100。
# 稽核紀錄保存期限另加法遵下限 365（無上限）；讀取時向上夾到 365（舊庫裡低於 365 的值不會讓稽核被提早清掉）。
_BACKUP_IMPACT = "只影響之後的清理：超過天數的舊備份會在下一次例行清理時被刪除，已刪除的備份無法復原；改大則不會補回已刪的。調長立即生效；縮短（會更早刪除）屬放寬，須另一位最高管理者核准，並等「變更生效等待天數」後才生效。"

_register_core(
    "change_control", "變更管制",
    [
        S("confirm_period_days", "int", 7, min=1, max=90, unit="天", risk="legal", loosen="down", recommended=7,
          question="高風險設定的變更，要等幾天才生效？（期間內可以撤銷）", label="變更生效等待天數",
          help="金額、法遵、安全這類設定改了以後，先等這段時間才真的生效，期間內任何最高管理者都能撤銷。最短 1 天。",
          impact="影響之後送出的高風險變更；已經在等待中的變更仍照原本的生效時間。縮短等待天數等於放寬管制，須另一位最高管理者核准，並等目前設定的等待天數過後才生效。",
          risk_text="縮短後，有人誤改或被盜用帳號時，留給所有使用者發現並撤銷的時間會變少。",
          when="想讓高風險設定多一點反悔時間，或縮短等待時。"),
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
          impact="只影響之後的清理：超過份數的舊快照會被刪除。更新失敗時要靠它退回，不建議調得過少；調少須另一位最高管理者核准並等待期滿後生效。", advanced=True),
        S("audit_log_keep_days", "int", 1825, min=365, unit="天", legacy="audit_log_keep_days", risk="legal", loosen="down", clamp=True, recommended=1825,
          question="稽核紀錄（誰在何時改了什麼）要保留幾天？至少 365 天，沒有上限。", label="稽核紀錄保留天數（至少 365）",
          help="稽核紀錄是出事時的法遵證據，不可低於 365 天。",
          impact="超過天數的稽核紀錄會被永久刪除，無法復原；只影響之後的清理，已存在的紀錄在到期前不受影響。縮短保存期限會讓較舊的紀錄提早消失，所以縮短須另一位最高管理者核准，並等「變更生效等待天數」後才生效。",
          risk_text="縮短後，被清掉的稽核紀錄無法復原；若遇到查帳或糾紛，可能無法取得當時的操作證據。"),
        S("notification_keep_days", "int", 90, min=7, max=3650, unit="天", risk="ops", loosen="down", recommended=90,
          question="站內通知（畫面右上角的訊息）要保留幾天？", label="站內通知保留天數", help="不論已讀或未讀，超過天數都會清除。",
          impact="只影響之後的清理：超過天數的通知（已讀、未讀都算）會從每個人的通知清單消失，不影響通知所指的單據本身。", advanced=True),
        S("request_log_keep_days", "int", 90, min=7, max=3650, unit="天", risk="ops", loosen="down", recommended=90,
          question="系統操作軌跡（誰在何時開了哪個頁面）要保留幾天？", label="操作軌跡保留天數", help="用來回頭查「上個月那筆資料是誰改的」。",
          impact="只影響之後的清理：超過天數的操作軌跡會被刪除；保留越久，個人行為紀錄累積越多，外洩時的影響也越大。", advanced=True),
        S("log_keep_days", "int", 30, min=7, max=3650, unit="天", risk="ops", loosen="down", recommended=30,
          question="系統日誌（程式運作與連線紀錄的壓縮舊檔）要保留幾天？", label="系統日誌保留天數",
          help="伺服器的運作紀錄與連線紀錄檔各自滿 15 MB 就會自動壓縮成舊檔，超過這個天數的舊檔就刪除；目前正在寫的檔不受影響。",
          impact="只影響之後的清理：超過天數的壓縮舊日誌會被刪除。日誌用於發生問題時查找原因，保留越短越難追查一週前的事件；日誌檔本身有大小上限（單檔 15 MB、最多 10 份），不會無限變大。", advanced=True),
    ],
    sensitive=True, risk="ops", legacy_key="backup_retention",
    help="備份、稽核紀錄、通知、操作軌跡與系統日誌要保存多久。",
)

# 備份與監控的告警門檻（2026-11-13，系統選單提案 v2 批次 4a）：預設值＝原本寫死在 system_checks 的常數（36 小時、50 GB、10%）——部署零行為變更。
# 「放寬」方向都走既有機制（須另一位最高管理者核准並等確認期間）：備份停擺門檻調大、硬碟剩餘空間門檻調小，都讓告警更晚才響。
_register_core(
    "monitoring", "備份與監控告警",
    [
        S("backup_stale_hours", "int", 36, min=12, max=720, unit="小時", risk="ops", loosen="up", recommended=36,
          question="備份超過幾小時沒有成功，就通知最高管理者？", label="備份停擺通知門檻（小時）",
          help="系統每天會自動備份一次；超過這個時數都沒有成功的備份，就寄信通知最高管理者。正常間隔是 24 小時，預設多留 12 小時的餘裕。",
          impact="只影響之後的每日檢查。調大＝要更久沒備份才會被通知，備份故障會更晚被發現，所以屬放寬，須另一位最高管理者核准並等「變更生效等待天數」後才生效；調小立即生效，但低於 24 小時會每日誤報。",
          risk_text="調大後，備份停擺的時間會拖得更久才有人知道；萬一這段時間資料庫損毀，可回復的資料就是更舊的那一份。"),
        S("disk_free_min_gb", "int", 50, min=1, max=10000, unit="GB", risk="ops", loosen="down", recommended=50,
          question="硬碟剩餘空間少於幾 GB，就通知最高管理者？（要同時低於下面的百分比才會通知）", label="硬碟剩餘空間通知門檻（GB）",
          help="資料庫所在的硬碟與雲端存檔碟，剩餘空間低於這個大小，而且比例也低於下面的百分比，就寄信通知。大容量硬碟看這個數字，小容量硬碟看百分比。",
          impact="只影響之後的每日檢查。調小＝硬碟更滿才會被通知，屬放寬，須另一位最高管理者核准並等待期滿後生效；調大立即生效。備份與上傳無法寫入，通常是硬碟已滿。",
          risk_text="調小後，硬碟快滿時不會提早通知；滿了之後備份與上傳會先失敗。"),
        S("disk_free_min_pct", "int", 10, min=1, max=90, unit="%", risk="ops", loosen="down", recommended=10,
          question="硬碟剩餘空間少於百分之幾，就通知最高管理者？（要同時低於上面的 GB 才會通知）", label="硬碟剩餘空間通知比例（%）",
          help="和上面的 GB 門檻搭配：兩個條件都成立才通知。小容量的硬碟看這個比例；容量很大的硬碟，比例會先滿足，實際觸發點就是上面的 GB。",
          impact="只影響之後的每日檢查。調小＝更晚才通知，屬放寬，須另一位最高管理者核准並等待期滿後生效；調大立即生效。",
          risk_text="調小後，硬碟快滿時不會提早通知。", advanced=True),
    ],
    sensitive=False, risk="ops",
    help="備份多久沒成功、硬碟剩多少空間要通知最高管理者。看狀態請到「備份與監控」頁。",
)

_register_core(
    "uploads", "上傳容量",
    [
        S("max_file_mb", "int", 20, min=1, max=200, unit="MB", risk="ops", loosen="up", recommended=20,
          question="每個上傳的檔案最大可以多大？", label="單檔大小上限", help="超過的檔案會被擋下，請使用者壓縮或分開上傳。",
          impact="影響所有上傳附件的畫面（單據附件、發票、簽回檔等），只影響之後的上傳；已上傳的檔案不受影響。調大會占用更多硬碟與備份空間，屬放寬：須另一位最高管理者核准並等待期滿後生效；調小立即生效。"),
        S("case_extra_expense_max_files", "int", 10, min=1, max=100, unit="個", risk="ops", loosen="up", recommended=10,
          question="一張支出申請單最多可以附幾個檔案？", label="支出申請每張單據附件數上限", help="包含正式附件與待核准的新附件。",
          impact="只影響支出申請單之後的上傳；已超過新上限的舊單據不會被刪除，但不能再加附件。調大須另一位最高管理者核准並等待期滿後生效；調小立即生效。"),
        S("case_extra_expense_max_request_mb", "int", 50, min=1, max=500, unit="MB", risk="ops", loosen="up", recommended=50,
          question="支出申請一次送出的附件總共最大可以多大？", label="支出申請一次送出合計上限", help="一次上傳的所有檔案加總的大小上限。",
          impact="只影響之後的上傳；超過時請使用者分批上傳。調大須另一位最高管理者核准並等待期滿後生效；調小立即生效。", advanced=True),
    ],
    sensitive=False, risk="ops",
    help="上傳檔案的大小與數量上限；允許的檔案類型屬安全邊界，不在此調整。",
)

# 系統中心（第 54 班）：『沒有權限的項目要不要列出來』是『放寬可見度』的設定——走設定登錄表（版本、影響說明、稽核同交易、放寬要確認期間與第二人核准）。
_register_core(
    "system_hub", "系統中心",
    [
        S("show_denied", "int", 0, min=0, max=1, risk="security", loosen="up", recommended=0,
          question="系統中心是否列出『您沒有權限使用』的項目？", label="沒有權限的項目",
          help="預設隱藏：每個人只看到自己能用的項目。也可以改成顯示為灰色，並說明為什麼不能用。這項在「設定中心」調整。",
          impact="只影響系統中心的畫面，不會改變任何人實際能使用的功能。改成『顯示為灰色』時，沒有權限的人會看到有哪些管理項目的名稱，但無法開啟。",
          risk_text="顯示後，沒有權限的人也能知道系統裡有哪些管理功能（例如備份、權限、稽核）；若不希望外人知道，請維持隱藏。",
          choices=[(0, "隱藏（建議）", "每個人只看到自己能用的項目；沒有權限的人完全看不到其他項目。"),
                   (1, "顯示為灰色並說明原因", "沒有權限的人會看到項目名稱與『需要什麼權限』，但無法開啟。")]),
    ],
    sensitive=True, risk="security",
    help="系統中心的顯示方式。要調整請到「系統」裡的「設定中心」。",
)

# 材料申請（第 57 班）：新增材料申請是否一定要先選供應商——預設必填＝上線前的行為（部署零行為變更）。
register_group(
    "material_order", "材料申請",
    [
        S("supplier_required", "int", 1, min=0, max=1, risk="money", loosen="down", recommended=1,
          question="新增材料申請時，是否必須先選供應商？", label="新增材料申請要選供應商",
          help="匯款申請要憑供應商帶出收款對象。從已核准採購單帶入的材料申請，採購單上已有廠商收款資料，可以先不選。",
          impact="只影響之後新增的材料申請，已存在的不受影響。選「帶入採購單的免選」時，從採購單帶入的新申請可以不選供應商就儲存、送審；之後開匯款申請時仍必須選好供應商。",
          risk_text="免選供應商後，申請可能在沒有供應商資料的情況下送審，到開匯款申請才發現缺資料而停滯；也比較容易漏選到錯的供應商。",
          choices=[(1, "一定要選（建議）", "沒選供應商的新申請不能儲存，會顯示原因。"),
                   (0, "帶入採購單的免選", "從已核准採購單帶入的新申請可以先不選供應商；手動新增的仍要選。")],
          when="從採購單帶入的材料申請常沒有供應商、被「一定要選」擋住時。放寬後只有帶入的免選，手動新增仍要選；開匯款申請前還是要補選好。"),
    ],
    sensitive=False, risk="money",
    help="材料申請的新增規則。目前只有「新增時是否選供應商」。",
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


def _alt_policy(key, question, label, help_, choices, *, risk_text=_ALT_BANNER, when=""):
    choices = _mark_na(key, choices)
    return S(key, "int", 1, min=1, max=len(choices), risk="money", loosen="up", recommended=1, requires_pending=True,
             question=question, label=label, help=help_, when=when,
             impact="影響已回簽的擇一方案報價單（以及同一案件下游的開票、請款、精算金額）；只影響之後的操作，已存在的單據內容不會被改寫。" + "放寬（往後面的選項）須原因、另一位最高管理者核准並等待期滿後生效；收緊立即生效。",
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
                out.append({"path": k, "message": "大括號只能用在系統提供的兩個代入位置，其他地方請移除"})
    for k, bad in UNAVAILABLE_ALT_CHOICES.items():
        if values.get(k) in bad:
            out.append({"path": k, "message": "這個選項尚未提供，請選其他項目"})
    return out


register_group(
    "quote_alt", "擇一方案", [
        S("alt_enabled", "bool", True, risk="ops", recommended=True,
          question="報價單是否提供「擇一方案」功能？", label="啟用擇一方案",
          help="開啟後，報價單的品項可以標成『擇一』（例如三種方案只能選一種）。關閉只是不顯示相關欄位，已經含擇一的舊單仍照原樣計算與列印。",
          impact="只影響報價單編輯畫面是否顯示擇一欄位；既有含擇一的報價單金額與列印不變。立即生效。",
          when="公司不再使用擇一方案、想把相關欄位從報價單拿掉時，才關閉；關掉只是不顯示欄位，舊單不變。"),
        S("total_text", "str", "依方案選擇", risk="legal", recommended="依方案選擇",
          question="報價單尚未選定方案時，稅前合計與總計那兩格要顯示什麼字？", label="合計欄位顯示文字",
          help="客戶看到的報價單，在尚未選定方案之前，稅前合計與總計兩格會改顯示這段文字。",
          impact="只影響之後存檔的報價單；已存檔的報價單沿用當時的文字（存檔時會記下）。客戶看得到這段文字。",
          risk_text="這段文字會印在給客戶的報價單上，請確認措辭不會讓客戶誤解金額。",
          when="要先開啟「啟用擇一方案」才有作用。客戶反映合計欄的字眼看不懂，或公司想換一句更貼切的說法時。"),
        S("note_template", "str", "項次{items}為{group}擇一方案選擇", risk="legal", recommended="項次{items}為{group}擇一方案選擇",
          question="報價單備註要自動帶哪一句擇一說明？", label="擇一說明句",
          help="每一組擇一方案會自動產生一句說明，接在備註最後。編輯時可從按鈕插入「項次」與「組別名稱」兩個代入位置，存檔時系統會自動換成該組的實際內容。",
          impact="只影響之後存檔的報價單；已存檔的報價單沿用當時的句子。客戶看得到這句話。",
          risk_text="這句話會印在給客戶的報價單上，請確認措辭正確。",
          when="要先開啟「啟用擇一方案」才有作用。想調整客戶看到的擇一備註措辭時；平常不必動。"),
        S("show_unpicked_in_pdf", "bool", False, risk="ops", recommended=False,
          question="客戶選定方案後，列印的報價單是否保留未被選取的項目（灰字標示『未選』）？", label="列印顯示未選項目",
          help="預設不印未被選取的項目。",
          impact="只影響之後列印／匯出的報價單 PDF 與 Excel，不改變任何金額。",
          when="要先開啟「啟用擇一方案」才有作用。客戶要求所有 PDF／Excel 輸出都保留「沒被選到的方案」做留底時。"),
        S("alt_groups_max", "int", 10, min=1, max=20, unit="組", risk="ops", loosen="up", recommended=10, advanced=True,
          question="一張報價單最多可以有幾組擇一方案？", label="擇一組數上限",
          help="組數越多，內部比較的組合數會大幅增加。超過上限的報價單無法存檔。",
          impact="只影響之後存檔的報價單；已超過新上限的舊單不會被刪除，但改動時需先減少組數。",
          when="要先開啟「啟用擇一方案」才有作用。同一張單真的需要超過目前組數的擇一方案時；調大前先確認內部比較畫面還看得懂。"),
        S("combo_view_max", "int", 24, min=1, max=200, unit="種", risk="ops", recommended=24, advanced=True,
          question="內部「方案組合比較」最多列出幾種組合？", label="組合比較列數",
          help="只影響內部成本比較畫面（客戶看不到）。超過的組合只顯示總數。",
          impact="只影響內部畫面，不影響任何金額、列印或客戶看到的內容。",
          when="要先開啟「啟用擇一方案」才有作用。內部比較畫面出現「只顯示前 N 種」而您想查看更多時。"),
        S("combo_view_default_open", "bool", False, risk="ops", recommended=False, advanced=True,
          question="開啟報價單時，內部「方案組合比較」是否預設展開？", label="組合比較預設展開",
          help="預設收合，要看時再展開，開單比較快。",
          impact="只影響內部畫面的預設狀態。",
          when="要先開啟「啟用擇一方案」才有作用。業務習慣一開單就比較各組合成本時。"),
        _alt_policy("lock_scope", "客戶回簽之後，報價單的哪些內容不能再改？", "回簽後鎖定範圍", "決定已回簽的擇一報價單，哪些欄位會被鎖住。如需修改，請先「取消回簽」。",
                    [(1, "鎖定整份報價本文（建議）", "品項、金額、備註與報價附件全部不能改；要改請先取消回簽。"),
                     (2, "只鎖品項與金額", "備註與報價附件仍可編輯，品項、單價、數量、擇一設定不能改。")],
                    when="現場常需要在客戶回簽後補改備註或附件、又不想每次都先取消回簽時，才考慮放寬成「只鎖品項與金額」。"),
        _alt_policy("cancel_after_deal", "案件已成案之後，是否還可以取消回簽？", "成案後取消回簽", "取消回簽會清除客戶選定的方案，金額回到未選定的暫估。",
                    [(1, "不行，需先處理下游（建議）", "已成案的案件不能取消回簽；請先把案件改回未成案。"),
                     (2, "可以，並連動清除下游衍生資料" + _NA, "取消回簽時，同步重算或標記下游依報價金額衍生的資料。"),
                     (3, "可以，只提醒", "照常取消回簽，並提醒『下游金額可能與報價不一致』，不連動修改。")],
                    when="成案後客戶改變主意、需要重選方案時，才評估放寬。"),
        _alt_policy("move_out_of_sent", "已回簽的擇一單，是否可以被改成草稿、已取消或已拒絕？", "已回簽單改變狀態", "指「改狀態」「收回」「退回」等會讓單據離開『已送出』的操作。",
                    [(1, "不行（建議）", "一律擋下並提示『請管理員取消回簽』。"),
                     (2, "可以，並自動清除選定", "比照取消回簽：通過下游檢查後同步清除選定，再進入新狀態。")],
                    when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
        _alt_policy("reject_final_keep", "已回簽的擇一單被「駁回結案」時，客戶選定的方案要保留還是清除？", "駁回結案時的選定", "駁回結案是終局動作。",
                    [(1, "保留（建議）", "駁回結案之後選定與金額原樣保留。"),
                     (2, "清除", "比照取消回簽：通過下游檢查後清除選定。")],
                    when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
        _alt_policy("unlock_edit_signed", "最高管理者是否可以對已回簽的擇一單做「解鎖修改」？", "解鎖修改已回簽單", "解鎖修改會讓單據回到待審核狀態。",
                    [(1, "不行（建議）", "一律擋下並提示『請管理員取消回簽』。"),
                     (2, "可以", "允許進入解鎖修改；期間仍受『回簽後鎖定範圍』限制。")],
                    when="有已回簽單必須由最高管理者修正時，才評估放寬。"),
        S("approval_basis", "int", 1, min=1, max=2, risk="money", loosen="up", recommended=1, requires_pending=True,
          question="擇一方案的報價單送審時，審核原因用哪個金額來判斷？", label="擇一單送審金額基準",
          help="目前審核原因會逐項檢查所有品項（包含尚未被選到的）。",
          impact="只影響之後送審的擇一方案報價單的審核原因清單。放寬須另一位最高管理者核准並等待期滿後生效。",
          risk_text="【高影響】選『僅檢查計入金額的品項』時，未被選取的低毛利方案不再列入審核原因，可能讓需要主管審閱的單據直接通過。",
          choices=[(1, "逐項檢查所有品項（最嚴，建議；目前的做法）", "包含尚未被選到的品項都逐一檢查，較不會漏掉需要審核的單。"),
                   (2, "僅檢查計入金額的品項" + _NA, "只檢查實際計入金額的品項（已選定的方案加上一般品項），沒被選到的方案不再列入審核原因。")],
          when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
        _alt_policy("cancel_after_export", "已經匯出給財務的開票憑據／請款單，是否還可以取消回簽？", "已匯出單據後取消回簽", "匯出後財務已據以開立文件。",
                    [(1, "不行，永久凍結選定方案（建議）", "請財務先作廢該憑據後才能取消回簽。"),
                     (2, "可以，並通知財務" + _NA, "取消回簽並通知財務；已匯出文件本身不會被修改。")],
                    when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
        _alt_policy("cancel_after_invoice", "已開票或已請款、但尚未匯出時，是否可以取消回簽？", "未匯出單據後取消回簽", "單據已建立但尚未匯出給財務時，取消回簽會讓報價金額與該單據不一致。",
                    [(1, "不行，須先撤回該單據（建議）", "請先撤回開票單或請款單再取消回簽。"),
                     (2, "可以，並提醒財務" + _NA, "取消回簽後單據留著，並通知財務其金額與方案不一致。")],
                    when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
        _alt_policy("cancel_after_settle", "案件已精算之後，是否可以取消回簽？", "精算後取消回簽", "精算完結後，成本與利潤已凍結，取消回簽會讓報價金額與精算不一致。",
                    [(1, "不行，須先重開精算（建議）", "請最高管理者先重新開啟精算再取消回簽。"),
                     (2, "可以，並重算精算基準" + _NA, "取消回簽並重算精算基準。")],
                    when="目前只有一個可選項（其他選項尚未提供），所以現在沒有可以改的地方；等系統提供放寬選項後，才需要評估。"),
    ],
    sensitive=True, risk="money", cross_check=_alt_cross_check,
    help="報價單「擇一方案」的文字範本、數量上限，以及客戶回簽後的處理規則。",
)



# 材料卡片認列已核准採購單（T57；MATERIAL-LINK-BUG-T57）：預設＝使用者 10-13 的話「非最高管理者自動帶入要取消、寄信通知管理員」。
# 放寬（讓有案件權限的人也能認列、關閉通知、提高寄信上限）要另一位最高管理者核准並等確認期間；收緊立即生效。收件人在「信件與通知收件設定」維護（只有一個來源）。
register_group(
    "material_recognition", "材料卡片認列採購單",
    [
        S("who_may", "int", 1, min=1, max=2, risk="security", loosen="up", recommended=1, requires_pending=True,
          question="誰可以把已核准的採購單「認列」到材料卡片（讓卡片能勾已申購／已到料）？", label="採購單認列授權對象",
          help="認列不經過材料申請的審核流程，所以預設只有最高管理者可以。其他人按下「帶入並連結」時，系統會取消這次動作。",
          impact="影響範圍：案件管理的材料卡片。放寬後，管理員與專案經理也能認列，認列後即可勾已申購與已到料（已到料會影響庫存序號）。已認列的卡片不受影響。",
          risk_text="【高影響】放寬後，沒有走審核的人也能讓材料卡片標示為已申購、已到料，並認領庫存序號。",
          impact_scope={"documents": ["案件材料卡片的已申購／已到料旗標", "庫存序號認領"], "roles": ["管理員", "有財務檢視權的專案經理"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          choices=[(1, "只有最高管理者（建議）", "其他人嘗試時取消，並依下一題通知管理員。"),
                   (2, "管理員與專案經理也可以", "能編輯材料申請的人（管理員以上，或有財務檢視權的專案經理）可以認列，不需要最高管理者核准；仍會留下稽核記錄。其他角色仍不行。")],
          when="專案經理常需要自己認列採購單，且公司同意由他們負責時。"),
        S("on_denied", "int", 1, min=1, max=2, risk="security", loosen="up", recommended=1,
          question="有人沒有權限卻嘗試認列時，要怎麼處理？", label="被拒時是否通知管理員",
          help="不論選哪個，這次認列都會被取消，而且一定留下稽核記錄。",
          impact="影響範圍：被拒時是否寄信給管理員（收件人在「信件與通知收件設定」）。信內不含金額與採購單明細。",
          risk_text="選「只取消」後，管理員不會收到信，只能事後翻稽核記錄才知道有人嘗試。",
          impact_scope={"documents": ["認列被拒的通知信"], "roles": ["管理員"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          choices=[(1, "取消並寄信通知管理員（建議）", "寄給管理員：案件、材料卡片、嘗試的帳號與時間。同一人同一案件同一張採購單在時間窗內只寄一次。"),
                   (2, "只取消，不寄信", "只留稽核記錄。")],
          when="管理員覺得越權嘗試的通知信太吵，或相反希望第一時間得知時，才改。不論怎麼選，稽核都會留下紀錄。"),
        S("mail_window_minutes", "int", 60, min=1, max=1440, unit="分鐘", risk="ops", loosen="down", recommended=60, advanced=True,
          question="同一個人對同一案件、同一張採購單重複嘗試時，隔多久才再寄一次通知？", label="重複通知的間隔",
          help="避免有人反覆按而洗版。", impact="影響範圍：只影響通知信的頻率，不影響取消與稽核記錄。調短會讓管理員收到更多信。",
            when="管理員抱怨重複通知太多或太少時。"),
        S("mail_cap", "int", 10, min=1, max=200, unit="封", risk="ops", loosen="up", recommended=10, advanced=True,
          question="上面那段時間內，這類通知信最多寄幾封？", label="通知信上限",
          help="達到上限後不再寄信，但每次嘗試仍會留稽核記錄。", impact="影響範圍：只影響通知信的數量，不影響取消與稽核記錄。",
            when="同一段時間內通知信量明顯過多或過少時才調整；平常不用動。"),
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
          help="預設把案件編號、案件名、文件類型、單號串在一起，可立即辨識是哪個案件的何種文件。單號一定會保留。",
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
          question="檔名裡的「案件名」要用哪個名稱？", label="檔名中的案件名來源",
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
          question="勞報單的檔名是否寫出承攬人的姓名？", label="勞報單檔名顯示承攬人姓名",
          help="與改版前相同，預設會寫。只有「有勞報單權限的人」（最高管理者，或被授權使用勞報單的人）才下載得到勞報單。",
          impact="影響範圍：勞報單 PDF 的檔名（只有有勞報單權限的人拿得到）。寫出姓名時，個人資料會出現在檔名裡，並跟著下載資料夾、雲端同步與郵件附件擴散。改成「不寫」是收緊，立即生效；改回「寫」須另一位最高管理者核准。",
          risk_text="承攬人的姓名（個人資料）會寫進檔名，隨檔案存到下載資料夾、雲端硬碟與郵件附件。",
          impact_scope={"documents": ["勞報單 PDF 的下載檔名"], "roles": ["有勞報單權限的人"], "amounts": "不涉及金額，只改檔名是否寫出承攬人姓名。", "reversible": False, "effective": "pending"},
          choices=[(0, "不寫姓名", "檔名只有案件、文件類型與日期或單號。"), (1, "寫出姓名（與改版前相同）", "檔名裡會有承攬人姓名，與改版前相同。")]),
        S("case_name_max_chars", "int", 20, min=5, max=60, unit="字", risk="none", recommended=20, advanced=True,
          question="檔名裡的案件名最多保留幾個字？", label="案件名最多字數", help="太長的案件名會被截短。",
          impact="影響範圍：之後下載的檔名。字數越多越完整，但整體檔名越容易超過系統上限。"),
        S("total_max_chars", "int", 100, min=40, max=150, unit="字", risk="none", recommended=100, advanced=True,
          question="檔名（不含副檔名）最長幾個字？", label="檔名總長上限", help="另外受系統的 255 位元組上限約束；過長時先縮短案件名，單號與副檔名不會被截掉。",
          impact="影響範圍：之後下載的檔名。過長的檔名在某些系統無法儲存或解壓縮。"),
        S("add_date", "int", 0, min=0, max=1, risk="none", recommended=0, advanced=True,
          question="檔名是否加上日期？", label="檔名加日期", help="預設不加。",
          impact="影響範圍：之後下載、且下載端點有提供日期的文件檔名。",
          choices=[(0, "不加（建議）", "與預設檔名相同。"), (1, "加日期", "在單號前面加上單據日期。")]),
        S("label_quotation", "str", '報價單', risk="none", recommended='報價單', advanced=True,
          question="下載檔名裡「報價單」要寫成什麼字？", label="文件類型用語：報價單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的報價單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_quotation_version", "str", '報價單存檔版本', risk="none", recommended='報價單存檔版本', advanced=True,
          question="下載檔名裡「報價單存檔版本」要寫成什麼字？", label="文件類型用語：報價單存檔版本", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的報價單存檔版本檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_estimate", "str", '估價單', risk="none", recommended='估價單', advanced=True,
          question="下載檔名裡「估價單」要寫成什麼字？", label="文件類型用語：估價單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的估價單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_estimate_version", "str", '估價單存檔版本', risk="none", recommended='估價單存檔版本', advanced=True,
          question="下載檔名裡「估價單存檔版本」要寫成什麼字？", label="文件類型用語：估價單存檔版本", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的估價單存檔版本檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_close_report", "str", '結案報表', risk="none", recommended='結案報表', advanced=True,
          question="下載檔名裡「結案報表」要寫成什麼字？", label="文件類型用語：結案報表", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的結案報表檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_execution_report", "str", '專案執行報告', risk="none", recommended='專案執行報告', advanced=True,
          question="下載檔名裡「專案執行報告」要寫成什麼字？", label="文件類型用語：專案執行報告", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的專案執行報告檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_completion", "str", '完工單', risk="none", recommended='完工單', advanced=True,
          question="下載檔名裡「完工單」要寫成什麼字？", label="文件類型用語：完工單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的完工單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_expense_form", "str", '費用單', risk="none", recommended='費用單', advanced=True,
          question="下載檔名裡「費用單」要寫成什麼字？", label="文件類型用語：費用單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的費用單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_shipping", "str", '出貨單', risk="none", recommended='出貨單', advanced=True,
          question="下載檔名裡「出貨單」要寫成什麼字？", label="文件類型用語：出貨單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的出貨單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_payment_request", "str", '請款單', risk="none", recommended='請款單', advanced=True,
          question="下載檔名裡「請款單」要寫成什麼字？", label="文件類型用語：請款單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的請款單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_invoice_voucher", "str", '開票申請', risk="none", recommended='開票申請', advanced=True,
          question="下載檔名裡「開票申請」要寫成什麼字？", label="文件類型用語：開票申請", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的開票申請檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_contractor_voucher", "str", '承攬商傳票', risk="none", recommended='承攬商傳票', advanced=True,
          question="下載檔名裡「承攬商傳票」要寫成什麼字？", label="文件類型用語：承攬商傳票", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的承攬商傳票檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_payslip", "str", '勞報單', risk="none", recommended='勞報單', advanced=True,
          question="下載檔名裡「勞報單」要寫成什麼字？", label="文件類型用語：勞報單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的勞報單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_bonus_award", "str", '獎金分配單', risk="none", recommended='獎金分配單', advanced=True,
          question="下載檔名裡「獎金分配單」要寫成什麼字？", label="文件類型用語：獎金分配單", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的獎金分配單檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
        S("label_voucher", "str", '傳票', risk="none", recommended='傳票', advanced=True,
          question="下載檔名裡「傳票」要寫成什麼字？", label="文件類型用語：傳票", help="1～10 個字，只改檔名上的顯示用語，不影響單據本身。",
          impact="影響範圍：之後下載的傳票檔名。已經下載的檔案不會被改名；可隨時改回預設值。"),
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
          impact="只改畫面提示，不影響存檔、送審與審核；只有看得到成本與毛利的人會看到。立即生效。",
          when="想在業務開單當下就提醒毛利偏低；0 代表不提醒。"),
    ],
    sensitive=False, risk="none",
    help="報價單「專案毛利%」的提醒門檻；算式本身固定，不在此調整。",
)

# 報價送審門檻（BP-2 B；原本寫死 30%）：單項毛利率低於門檻 ⇒ 報價單送審時多一條『需審核』原因。預設 30＝今天的行為。
# 調低門檻＝更少報價單需要審核＝放寬（走確認期間與第二位最高管理者核准）；調高即時生效。只影響『要不要多一條審核原因』，不改簽核層與簽核規則本身。
register_group(
    "quote_approval", "報價送審門檻",
    [
        S("min_item_margin_pct", "float", 30, min=0, max=100, unit="%", risk="money", loosen="down", recommended=30,
          risk_text="【高影響】調低門檻後，毛利偏低的報價單不再被列出『單項毛利率偏低』這條審核原因，可能讓需要主管審閱的單據少了一個提醒。",
          impact_scope={"documents": ["報價單送審"], "roles": ["業務", "簽核人"], "amounts": "不改任何金額；只影響『單項毛利率偏低』是否列為需審核的原因。", "reversible": True, "effective": "pending"},
          question="報價單某一項的毛利率低於多少，送審時要列為『需審核』原因？", label="單項毛利率送審門檻",
          help="報價單任一品項（有成本者）的毛利率低於這個百分比，送審時會多一條「第幾項毛利率偏低（低於門檻）」的審核原因。預設 30。",
          impact="調低＝更少報價單被列出這條原因（放寬，需第二位最高管理者核准並等待期滿後生效）；調高＝更多（立即生效）。不改簽核層與簽核規則，也不改任何金額。",
          when="主管覺得太多或太少低毛利單被標出來時。"),
        S("max_valid_days", "int", 30, min=1, max=365, unit="天", risk="money", loosen="up", recommended=30,
          risk_text="【高影響】調大上限後，有效期限較長的報價單不再被列出『有效期限過長』這條審核原因，可能讓需要主管看的條件沒被注意到。",
          impact_scope={"documents": ["報價單送審"], "roles": ["業務", "簽核人"], "amounts": "不改任何金額；只影響『有效期限過長』是否被列為審核原因", "reversible": True, "effective": "pending"},
          question="報價單的有效期限最多可以幾天，超過就要列為『需審核』原因？", label="報價單有效天數上限",
          help="報價單的有效天數超過這個數字，送審時會多一條「有效期限過長（超過上限天數）」的審核原因。",
          impact="調大＝更少報價單被列出這條原因（放寬，需第二位最高管理者核准並等待期滿後生效）；調小＝更多（立即生效）。不改任何已送出的報價單；只影響之後送審時列出的原因。注意：上限調到低於「新報價單預設有效天數」（報價單預設值）時，每張新報價單一開始就會被列為『有效期限過長』。",
          when="公司的報價有效期政策改變時。調低上限前，先確認「新報價單預設有效天數」沒有超過新上限，否則預設值會存不進去。"),
        S("discount_review_above", "int", 0, min=0, max=100000000, unit="元", risk="money", loosen="up", recommended=0,
          risk_text="【高影響】調高後，金額不大的折讓不再被列出『含折讓』這條審核原因，可能讓需要主管看的折讓沒被注意到。",
          impact_scope={"documents": ["報價單送審"], "roles": ["業務", "簽核人"], "amounts": "不改任何金額；只影響『含折讓』是否被列為審核原因", "reversible": True, "effective": "pending"},
          question="報價單的折讓金額超過多少元，送審時要列為『需審核』原因？（填 0 代表只要有折讓就列出）", label="折讓審核門檻（元）",
          help="報價單有折讓、而且折讓金額大於這個數字，送審時會多一條「含折讓（列出折讓金額）」的審核原因。0 代表任何折讓都列出（目前的做法）。",
          impact="調高＝更少報價單被列出這條原因（放寬，需第二位最高管理者核准並等待期滿後生效）；調低＝更多（立即生效）。不改任何已送出的報價單；只影響之後送審時列出的原因。",
          when="想讓小額折讓免審、或所有折讓都要看時。"),
        # 簽核二擇一 S3b（設計 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-S3-HOOK-DESIGN.md §4；K 審 Q2／Q5）：三態以整數代碼表示（放寬管制只認數字欄位）。
        # 0＝今天的行為（簽核人簽完後內容被改，簽核不受影響）；1＝影子（只記錄「本來會作廢誰」，不改簽核）；2＝開（內容被改 ⇒ 已簽層回到待複查）。
        # 往小調（2→1、2→0、1→0）＝放寬：確認期間＋第二位最高管理者核准。⚠ 與 K 的字面不同處：1→0（影子→關）本來只是停止記錄、不算放寬，
        # 但單一數字欄位表達不了「2→1 要管、1→0 不管」，取較嚴的一邊（影子→關也走放寬流程）；0→1、1→2、0→2 立即生效。
        S("reconfirm_mode", "int", 0, min=0, max=2, risk="money", loosen="down", recommended=0,
          risk_text="【高影響】調小後（開→只記錄、開→關、只記錄→關），簽核人簽核後內容遭修改的單據不再被要求重新複查，已簽的層會沿用舊簽核。",
          impact_scope={"documents": ["報價單簽核"], "roles": ["業務", "簽核人", "最高管理者"], "amounts": "不改任何金額；只影響已簽核的層在內容被修改後是否要重新複查。", "reversible": True, "effective": "pending"},
          question="簽核人簽完之後，報價單內容又被改了，是否請簽核人重新複查？", label="內容被改後重新複查",
          help="預設關閉（簽核人簽完後無論內容如何修改均不受影響）。「只記錄、不生效」此選項只記錄「如果開了會作廢誰」供評估，不改任何簽核；建議建議先以此選項試行一週再開啟。「開」＝已簽的層，內容被改後回到待複查，並通知該簽核人、後續層與送審人。",
          impact="往大調（關→只記錄→開）立即生效；往小調（開→只記錄、開→關、只記錄→關）＝放寬，需第二位最高管理者核准並等待期滿後生效。不改任何金額，也不改簽核流向；只影響『已簽核之後內容被修改』的處理。",
          choices=[(0, "關閉（預設）", "維持目前：簽完後內容被改，簽核不受影響。"),
                   (1, "只記錄、不生效", "只記錄本來會作廢誰，不改任何簽核。"),
                   (2, "開啟", "內容被改後，已簽的層回到待複查。")],
          when="簽完後內容被未經同意修改、而簽核人不知情時；「先試跑」看一週會影響誰，再決定開。"),
    ],
    sensitive=True, risk="money",
    help="報價單送審時，『單項毛利率偏低』『有效期限過長』『含折讓』這幾條審核原因的門檻。",
)


# 財務報表參數（財務盤點第一個切片；設計 docs/platform/plans/FINANCE-FRAMEWORK-INVENTORY-T62.md §4）：
# 應收帳齡的區間切點。預設關＝報表與今天逐位元相同（30／60／90 天）。只改報表怎麼分組與標色，不改任何金額，也不改誰看得到報表。
register_group(
    "finance_reports", "財務報表",
    [
        S("custom_aging", "int", 0, min=0, max=1, risk="none", recommended=0,
          question="應收帳齡是否改用自訂的天數區間？", label="自訂帳齡區間",
          help="關閉時，應收帳齡固定分成 0–30、31–60、61–90、90 天以上四組。開啟後，下面三個天數決定各組的分界。",
          impact="只改帳齡報表（畫面、Excel、PDF）怎麼分組與標色；不改任何金額，也不改誰看得到這份報表。立即生效。",
          choices=[(0, "關閉（預設）", "維持 30／60／90 天。"), (1, "開啟", "採用下面三個天數。")],
          when="公司的帳期習慣不是 30／60／90 天時才打開。"),
        S("aging_day1", "int", 30, min=1, max=3650, unit="天", risk="none", recommended=30,
          question="第一組帳齡到第幾天為止？", label="帳齡第一個分界",
          help="經過天數不超過這個值的款項歸第一組。必須小於第二個分界。只有「自訂帳齡區間」開啟時才採用。",
          impact="三個分界必須由小到大；填得不合理時報表自動退回 30／60／90 天。",
          when="要先開啟「自訂帳齡區間」才有作用。想把最短的帳齡區間改短或改長時。"),
        S("aging_day2", "int", 60, min=1, max=3650, unit="天", risk="none", recommended=60,
          question="第二組帳齡到第幾天為止？", label="帳齡第二個分界",
          help="超過第一個分界、不超過這個值的款項歸第二組；超過這個值的款項在 Excel 與 PDF 以橘字標出。",
          impact="必須大於第一個分界、小於第三個分界。",
          when="要先開啟「自訂帳齡區間」才有作用。想調整「注意」的分界時。"),
        S("aging_day3", "int", 90, min=1, max=3650, unit="天", risk="none", recommended=90,
          question="超過第幾天的款項要列為「逾期很久」？", label="帳齡第三個分界",
          help="超過這個值的款項歸最後一組，並在 Excel 與 PDF 以紅字標出。",
          impact="必須大於第二個分界。",
          when="要先開啟「自訂帳齡區間」才有作用。想調整「逾期很久」的分界時。"),
        S("settle_overdue_days", "int", 0, min=0, max=365, unit="天", risk="money", loosen="up", recommended=0,
          risk_text="【高影響】調大等待天數後，已結案但尚未精算的案件會晚幾天才出現在清單與總覽件數，可能讓該精算的案件較較晚被注意到。",
          impact_scope={"documents": ["營運報表：已結案未精算"], "roles": ["財務", "最高管理者"], "amounts": "不改任何金額或案件資料；只影響案件多久之後才列入「已結案未精算」清單與件數。", "reversible": True, "effective": "pending"},
          question="「已結案但尚未精算」的清單，要等結案幾天之後才列出？（0 代表結案後立即列入）", label="未精算提醒的等待天數",
          help="0 ＝ 目前的做法：案件一結案、精算尚未完結就列入清單與總覽件數。設成例如 14，結案超過 14 天仍未精算才列入。等待天數從案件的「最後更新日」算起，結案後只要又被編輯過，就會重新計算。",
          impact="只影響報表裡「已結案未精算」清單與總覽件數（畫面、Excel、PDF 一致）；不改任何案件或金額。調大＝案件更晚才列入（放寬，需第二位最高管理者核准並等待期滿後生效）；調小＝更早（立即生效）。",
          when="結案後需要多一點時間才完成精算，不想太早被列入「未精算」時。"),
    ],
    sensitive=False, risk="none",
    help="財務報表的顯示參數。金額、稅額與捨入不在這裡調整。",
)

# 出納顯示與對帳參數（財務盤點 F2／F3）：即將到期提醒天數、銀行對帳單欄位別名。各自有開關，預設關＝與今天逐位元相同。
# 都不是金額；只影響出納頁怎麼標色，以及對帳單 CSV 怎麼找欄位（找不到金額欄一樣會被擋下）。
register_group(
    "finance_cashier", "出納",
    [
        S("custom_due_soon", "int", 0, min=0, max=1, risk="none", recommended=0,
          question="出納頁的「即將到期」是否改用自訂天數？", label="自訂即將到期天數",
          help="關閉時，待付款的應付日 7 天內、預定付款日 3 天內會標成「即將到期」。開啟後改用下面兩個天數。",
          impact="只改出納頁的標色與提示文字，不改任何金額或單據狀態。立即生效。",
          choices=[(0, "關閉（預設）", "維持 7 天與 3 天。"), (1, "開啟", "採用下面兩個天數。")],
          when="想讓「即將到期」比 7 天／3 天更早或更晚提醒時。"),
        S("due_soon_payable_days", "int", 7, min=1, max=60, unit="天", risk="none", recommended=7,
          question="應付日幾天內要標成「即將到期」？", label="應付即將到期天數",
          help="待付款與應收清單的日期在今天起這個天數內，會用橘字標示。", impact="只影響顏色。",
            when="要先開啟「自訂即將到期天數」才有作用。出納想更早（或更晚）在待付款與應收清單看到橘字「即將到期」時調整。"),
        S("due_soon_planned_days", "int", 3, min=1, max=60, unit="天", risk="none", recommended=3,
          question="預定付款日幾天內要提示「即將到期」？", label="預定付款日提示天數",
          help="預定付款日在今天起這個天數內，會顯示「幾天內到期」的提示；預定付款日提醒信與站內通知也是預定日的前幾天寄出（預設 3 天）。",
          impact="影響出納頁提示文字，以及提醒信／站內通知提前幾天寄出。縮短天數後，個別預定日可能多收到一封提醒。",
          when="要先開啟「自訂即將到期天數」才有作用。想更早（或更晚）收到預定付款日的提醒信時。"),
        S("receivable_grace_days", "int", 0, min=0, max=90, unit="天", risk="money", loosen="up", recommended=0,
          risk_text="【高影響】調大寬限天數後，逾期的應收款會晚幾天才被標成「逾期」，可能讓該追的款項較較晚被注意到。",
          impact_scope={"documents": ["出納應收清單"], "roles": ["出納", "財務"], "amounts": "不改任何金額或收款資料；只影響應收款「逾期」旗標與紅字出現的時間。", "reversible": True, "effective": "pending"},
          question="預計收款日過了幾天之後，才把應收款標成「逾期」？（0 代表逾期即標示）", label="應收逾期寬限天數",
          help="0 ＝ 目前的做法：預計收款日已過、尚未收就標逾期。設成例如 3，預計收款日之後的第 4 天才開始標逾期（也就是寬限滿 3 天之後）。只影響出納應收清單的逾期標示。",
          impact="只影響出納頁應收款的「逾期」旗標與紅字；不改任何金額或收款資料。調大＝逾期標示更晚出現（放寬，需第二位最高管理者核准並等待期滿後生效）；調小＝更早（立即生效）。",
          when="客戶習慣晚幾天付款、不想太早標逾期時。"),
        S("custom_bank_aliases", "int", 0, min=0, max=1, risk="none", recommended=0,
          question="匯入銀行對帳單時，是否改用自訂的欄位名稱清單？", label="自訂對帳單欄位名稱",
          help="各家銀行匯出的欄位名稱不同。關閉時使用內建清單；開啟後使用下面三欄的清單（用逗號分隔，越前面越優先）。",
          impact="只影響對帳單檔案怎麼找出日期、金額、摘要欄；找不到金額欄時一樣會擋下，不會自行推測。立即生效。",
          choices=[(0, "關閉（預設）", "使用內建清單。"), (1, "開啟", "使用下面的清單；寫得不合理的欄位會退回內建清單。")],
          when="匯入銀行對帳單時，欄位對不上時才打開。"),
        S("bank_alias_date", "str", "交易日期,日期,過帳日,轉帳日期,交易日,date,Date", risk="none", recommended="交易日期,日期,過帳日,轉帳日期,交易日,date,Date",
          question="哪些欄位名稱代表交易日期？", label="對帳單日期欄名稱", help="用逗號分隔，最多 20 個、每個 2 到 30 字。", impact="只影響對帳單匯入。",
            when="要先開啟「自訂對帳單欄位名稱」才有作用。對帳單的日期欄叫別的名字時，加進來。"),
        S("bank_alias_amount", "str", "金額,提出金額,支出金額,轉出金額,付款金額,提款金額,amount,Amount,Debit,withdrawal", risk="none", recommended="金額,提出金額,支出金額,轉出金額,付款金額,提款金額,amount,Amount,Debit,withdrawal",
          question="哪些欄位名稱代表金額？", label="對帳單金額欄名稱", help="用逗號分隔，最多 20 個、每個 2 到 30 字。", impact="只影響對帳單匯入。",
            when="要先開啟「自訂對帳單欄位名稱」才有作用。對帳單的金額欄叫別的名字時，加進來。"),
        S("bank_alias_desc", "str", "摘要,備註,說明,對方戶名,附言,memo,Description,Memo", risk="none", recommended="摘要,備註,說明,對方戶名,附言,memo,Description,Memo",
          question="哪些欄位名稱代表摘要？", label="對帳單摘要欄名稱", help="用逗號分隔，最多 20 個、每個 2 到 30 字。", impact="只影響對帳單匯入。",
            when="要先開啟「自訂對帳單欄位名稱」才有作用。對帳單的摘要欄叫別的名字時，加進來。"),
    ],
    sensitive=False, risk="none",
    help="出納頁的顯示天數與銀行對帳單欄位名稱；金額、權限與單據狀態不在這裡調整。",
)

# 案件結案閘門的『只收緊』選項（財務盤點 S-C1；設計 FINANCE-FRAMEWORK-INVENTORY-T62.md §5）：預設全關＝與今天相同。
# 這裡只能讓更多案件「不能結案」，不能拿掉任何一關；關掉主開關或任一選項都是放寬，要第二位最高管理者核准並經確認期間。
# 收款、單據、精算、額外支出四關永遠存在（結案後案件鎖定，收入與成本必須先確定）。
register_group(
    "case_close_gates", "結案條件加嚴",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["案件結案"], "roles": ["所有按下「結案」的人"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="是否啟用結案條件加嚴？", label="啟用結案條件加嚴",
          help="開啟後，下面勾選的項目會變成結案的必要條件。關閉時結案條件與目前完全相同。",
          impact="只會讓更多案件暫時不能結案，不會改任何資料。關閉屬於放寬，需要另一位最高管理者核准並等待期滿後生效。",
          choices=[(0, "關閉（預設）", "結案條件與目前相同。"), (1, "啟用", "下面勾選的加嚴項目生效。")],
          when="公司想把結案把關從「寬鬆」改成「必須齊全」時。"),
        S("require_stages", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["案件結案"], "roles": ["所有按下「結案」的人"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="沒有建立執行管理階段的案件，是否也禁止結案？", label="結案需有執行階段",
          help="目前沒有任何階段的案件，進度這一關視為「無需檢查」。啟用後，沒有階段就不能結案。", impact="只影響結案檢查。關閉屬於放寬。",
          choices=[(0, "不加嚴（預設）", "沒有階段的案件照舊可結案。"), (1, "加嚴", "沒有階段的案件不能結案。")],
          when="要先開啟「啟用結案條件加嚴」才有作用。常有案件沒建階段就結案、事後難追蹤時。"),
        S("require_payment_items", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["案件結案"], "roles": ["所有按下「結案」的人"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="沒有建立款項明細的案件，是否也禁止結案？", label="結案需有款項明細",
          help="目前沒有任何款項期別的案件，收款這一關視為「無需檢查」。啟用後，沒有款項明細就不能結案。", impact="只影響結案檢查。關閉屬於放寬。",
          choices=[(0, "不加嚴（預設）", "沒有款項明細的案件照舊可結案。"), (1, "加嚴", "沒有款項明細的案件不能結案。")],
          when="要先開啟「啟用結案條件加嚴」才有作用。常有案件沒建款項明細就結案、收款對不起來時。"),
        S("require_settlement", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["案件結案"], "roles": ["所有按下「結案」的人"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="尚未建立成本精算的案件，是否也禁止結案？", label="結案需已建立精算",
          help="目前完全沒有精算資料的案件，精算這一關視為「無需檢查」。啟用後，沒有精算就不能結案。", impact="只影響結案檢查。關閉屬於放寬。",
          choices=[(0, "不加嚴（預設）", "沒有精算資料的案件照舊可結案。"), (1, "加嚴", "沒有精算資料的案件不能結案。")],
          when="要先開啟「啟用結案條件加嚴」才有作用。常有案件沒精算就結案、利潤看不到時。"),
        S("count_unfinished_extra_expenses", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["案件結案"], "roles": ["所有按下「結案」的人"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="額外支出尚未走完簽核（草稿或簽核到一半）時，是否也禁止結案？", label="未完成的額外支出也擋結案",
          help="目前只有剛送出、還在「待審核」的額外支出會擋結案；草稿，以及多層簽核簽到一半（簽核中）的額外支出不會擋。啟用後，這兩種也會擋。", impact="只影響結案檢查。關閉屬於放寬。",
          choices=[(0, "不加嚴（預設）", "維持目前的做法，只擋待審核的額外支出。"), (1, "加嚴", "草稿與簽核中的額外支出也擋結案。")],
          when="要先開啟「啟用結案條件加嚴」才有作用。常有額外支出草稿卡著，結案後成本不完整時。"),
    ],
    sensitive=False, risk="ops",
    help="結案檢查的加嚴選項。只能讓結案更嚴，不能移除收款、單據、精算、額外支出任何一關。",
)


# 狀態顯示名稱與顏色（S-X2；設計 docs/platform/plans/STATUS-DISPLAY-INVENTORY-T62.md）：預設關＝所有畫面與今天逐位元相同。
# 只改畫面上看到的字與色；狀態的鍵（資料庫值）、查詢、權限與流程都不變。核准／付款類狀態改名或改色屬放寬，需要第二位最高管理者核准。
register_group(
    "builder_status_display", "狀態顯示名稱與顏色",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放最高管理者自訂狀態在畫面上的名稱與顏色？", label="開放自訂狀態名稱與顏色",
          help="開啟後，最高管理者可以在狀態設定頁改各個狀態的顯示名稱、各畫面的簡稱與顏色（顏色限用固定的色盤），發布前可預覽。需要先開啟「建構器治理」。",
          impact="只改畫面上看到的字與色，不改任何狀態值、查詢、權限或流程；報價單、案件管理、出納等畫面會跟著顯示。把核准或付款類狀態改名或改色，需要第二位最高管理者核准。",
          choices=[(0, "關閉（預設）", "畫面與目前完全一樣。"), (1, "開啟", "狀態設定頁可用，已發布的名稱與顏色會顯示在各畫面。")]),
    ],
    sensitive=False, risk="ops",
    help="狀態的顯示名稱與顏色是否開放自訂；狀態本身的值與規則不在這裡調整。",
)

# 數字與日期顯示格式（T64 切片 B／D2；前端 static/motrix-format.js）：預設關＝所有畫面與今天逐字相同。
# 只改畫面上數字與日期怎麼印（顯示用）；儲存的金額、法定四捨五入（MotrixLegalRound.halfUp）、PDF 與匯出都不變。百分比、多位小數的單價與變更紀錄的值不套用。
register_group(
    "ui_format", "數字與日期顯示格式",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放自訂畫面上數字與日期的顯示方式？", label="開放自訂數字與日期顯示",
          help="開啟後，下面三項才會生效。關閉時所有畫面照目前的方式顯示。",
          impact="只改報價單、報價單清單、案件管理、出納等畫面上數字與日期如何顯示（僅顯示）；儲存的金額與法定四捨五入都不變，也不改 PDF 或匯出檔。百分比、多位小數的單價與變更紀錄的值不受影響。換頁或重新整理後生效。",
          choices=[(0, "關閉（預設）", "畫面與目前完全一樣。"), (1, "開啟", "下面三項的設定會套用到畫面。")]),
        S("thousands", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="數字是否加千分位逗號？", label="千分位",
          help="只在上面開啟後生效。",
          impact="只改畫面上數字的樣子（例如 1,234,567 或 1234567）；金額本身不變。",
          choices=[(0, "照目前（有逗號）", "維持現在的顯示。"), (1, "不加逗號", "數字連在一起顯示。")]),
        S("decimals", "int", 0, min=0, max=2, risk="ops", recommended=0,
          question="畫面上的金額固定顯示幾位小數？", label="小數位數",
          help="只在上面開啟後生效。僅改畫面顯示，儲存的金額與法定四捨五入不變；單價、差額與百分比不套用。",
          impact="僅畫面顯示；例如選「兩位」時 1,234 會顯示成 1,234.00。儲存的金額與計算結果不變。",
          choices=[(0, "照目前", "維持現在的顯示。"), (1, "整數（不顯示小數）", "小數會依顯示規則進位到整數，僅畫面如此。"),
                   (2, "固定兩位", "一律顯示到小數第二位。")]),
        S("date_style", "int", 0, min=0, max=2, risk="ops", recommended=0,
          question="日期要用哪種寫法顯示？", label="日期寫法",
          help="只在上面開啟後生效；只套用在只有日期的欄位，含時間的欄位維持目前的寫法。",
          impact="只改畫面顯示，不改儲存的日期。",
          choices=[(0, "照目前", "維持現在的顯示。"), (1, "年-月-日（2026-01-05）", "用減號分隔。"), (2, "年/月/日（2026/01/05）", "用斜線分隔。")]),
    ],
    sensitive=False, risk="ops",
    help="畫面上數字與日期的顯示方式（僅顯示）；金額計算與法定四捨五入不在這裡調整。",
)

# 完工單「從報價單帶入項目」（第 57 班；設計 COMPLETION-NOTE-QUOTE-ITEMS-T56 §5）：預設值＝使用者 2026-10-12 的表單裁示。
# 全部是『之後新建／重新帶入』的行為選項，不改任何既有完工單。金額永遠不進完工單（結構性不變式，不在此調整）。
register_group(
    "completion_note", "完工單",
    [
        S("auto_prefill", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="新建完工單時，是否自動把報價單的項目帶進來？", label="新建時自動帶入項目",
          help="帶入後每一列都可以修改、刪除；按「儲存」才會寫入。",
          impact="只影響之後新開的完工單畫面；已存的完工單不會改。選「不自動帶入」仍可在草稿上按「從報價單帶入」。",
          choices=[(1, "自動帶入（建議）", "新建時畫面直接出現報價單的項目，不用重打。"),
                   (0, "不自動帶入", "新建時項目是空白的，需要時再按「從報價單帶入」。")],
          when="現場希望完工單一開始是空白、由人逐項填寫（例如實際完工內容和報價單差很多）時，才關閉自動帶入。"),
        S("prefill_unsigned", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="報價單已送出、但客戶尚未回簽時，是否可以帶入項目？", label="未回簽的報價單可否帶入",
          help="報價尚未回簽時，項目之後還可能被修改；帶入的內容只是暫時依據。",
          impact="影響所有新建與重新帶入完工單的人（目前限管理員）；已存的完工單不變。選「要回簽後才能帶入」時，現場想先開完工單會被擋下，需先請業務取得客戶回簽。變更立即生效。",
          choices=[(1, "可以，並提示尚未回簽（建議）", "畫面會提醒「報價單尚未回簽，項目可能再變」。"),
                   (0, "要等客戶回簽後才能帶入", "報價單未回簽時不能帶入，避免依據還會變動的項目開單。")],
          when="要先開啟「新建時自動帶入項目」才有作用。現場想在客戶回簽前先開完工單，或相反要嚴格等回簽時。"),
        S("qty_mode", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="帶入時，每個項目的數量預設填多少？", label="帶入數量的預設",
          help="分批完工時，若前面的完工單已經完成一部分，預設只填剩下的部分。",
          impact="只影響帶入當下的預設數字，每列都能再改。選「報價全數」時，分批完工的第二張單會重複計入前一張已完成的數量，須自行扣除。",
          choices=[(0, "只填剩餘未完工的數量（建議）", "已完工的數量（待審核、簽核中、已核准的完工單）會先扣掉；已全數完工的項目預設不帶入。"),
                   (1, "填報價的全部數量", "不扣已完工的數量。")],
          when="要先開啟「新建時自動帶入項目」才有作用。不分批完工、想讓每張完工單一律填報價的全部數量時，才改成「填報價的全部數量」；分批完工的案件維持預設較省事。"),
        S("default_status", "int", 0, min=0, max=2, risk="ops", recommended=0,
          question="帶入的項目，完成狀態預設是什麼？", label="帶入項目的預設狀態",
          help="現場只完成一部分時，把該列改成「部分完成」即可。",
          impact="只影響帶入當下的預設，每列都能再改；「部分完成」與「未施作」會出現在完工單的遺留事項提醒。",
          choices=[(0, "完成（建議）", "預設視為已完成，只需修改例外的幾列。"),
                   (1, "部分完成", "預設都標為部分完成，現場逐列確認。"),
                   (2, "未施作", "預設都標為未施作，完成一項再改一項。")],
          when="要先開啟「新建時自動帶入項目」才有作用。大多數項目完工狀態一致時，選最常見的，省去逐列改。"),
        S("include_headers", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="帶入時，是否一併帶入報價單的分段標題？", label="一併帶入分段標題",
          help="分段標題只是分組用的標題列，沒有數量。",
          impact="只影響帶入當下的畫面。", advanced=True,
          choices=[(1, "一併帶入（建議）", "完工單的項目分組與報價單一致。"), (0, "不帶入標題", "只帶有數量的項目。")],
          when="要先開啟「新建時自動帶入項目」才有作用。報價單分段標題對完工單沒意義，或相反要保留分組時。"),
        S("brand_prefix", "int", 1, min=0, max=1, risk="ops", recommended=1,
          question="帶入時，品名前面是否加上品牌？", label="品名前加品牌",
          help="例如報價單的品牌「某牌」、品名「攝影機」，帶入後顯示為「某牌 攝影機」。",
          impact="只影響帶入當下的品名文字，之後仍可修改。", advanced=True,
          choices=[(1, "加上品牌（建議）", "品名會是「品牌 品名」。"), (0, "只帶品名", "品牌不帶入。")],
          when="要先開啟「新建時自動帶入項目」才有作用。完工單的品名欄太長，或客戶不需要看到品牌時，才改成只帶品名。"),
        S("over_qty", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          question="某個項目的完工數量加總超過報價數量時，要怎麼處理？", label="完工數量超過報價數量",
          help="現場多做、或報價單後來有增補，都是真實會發生的情況。",
          impact="影響之後儲存完工單的人。選「擋下」時，多做的部分要先修改報價單才能儲存；已存的完工單不受影響。",
          choices=[(0, "警示但仍可儲存（建議）", "該列會標黃色並顯示超過多少，仍然可以儲存。"),
                   (1, "擋下，不能儲存", "超過的部分需要先改報價單的數量，或調整完工單的數量。")],
          when="現場多做的數量需要被管制，或相反要寬鬆時。"),
    ],
    sensitive=False, risk="ops",
    help="完工單從報價單帶入項目時的預設行為。誰能建立或編輯完工單屬權限設定，不在這裡（目前仍限管理員）。",
)


# ── BP-1（建構器 第一刀）：各畫面是否啟用「管理者自訂版面」（欄位顯示／順序／標籤）。預設全關＝上線前的畫面（部署零行為變更）。 ──
# 一個畫面一個欄位（builder.layout.<畫面>）；啟用後該畫面才會讀版面定義（公司／角色），最高管理者才看得到「編輯版面」。
import json as _json
from core import paths as _paths

# 版面頁面登錄（單一來源）：frontend/static/layout-pages.json。新增一頁＝在該檔加一筆（旗標欄位由此產生），不必改這裡。
with open(_paths.FRONTEND_DIR + "/static/layout-pages.json", encoding="utf-8") as _fh:
    _LAYOUT_PAGES = _json.load(_fh)

register_group(
    "builder_layout", "自訂畫面版面",
    [
        S(_p["flag"], "bool", False, risk="ops", recommended=False,
          question=_p["question"], label=_p["flagLabel"], help=_p["help"], impact=_p["impact"],
          choices=[(False, _p["offLabel"], _p["offText"]), (True, _p["onLabel"], _p["onText"])])
        for _p in _LAYOUT_PAGES
    ],
    sensitive=False, risk="ops",
    help="決定哪些畫面開放管理者自訂版面：供應商管理頁、案件管理頁的案件清單與表單、採購管理頁、設備登載頁、承攬商管理頁。",
)


# 建構器治理（BP-1，t59）：版本帳本／任兩版差異／發布前影響預覽。預設關（＝今天的行為，新路由一律 404、畫面不出現）；不碰資料庫結構。
register_group(
    "builder_governance", "建構器治理（版本帳本與發布前影響預覽）",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開啟定義的版本帳本與發布前影響預覽？", label="版本帳本與影響預覽",
          help="開啟後，版面、輸出版型、自訂欄位的編輯畫面會多出「版本帳本」（列出每一版、比較任兩版、可直接還原）與發布前的「影響預覽」。",
          impact="只增加檢視與預覽，不改變任何已發布的定義，也不改變發布與還原本身的行為。預覽只留一筆『看過預覽』的稽核。",
          choices=[(0, "關閉（預設）", "畫面與目前完全一樣。"), (1, "開啟", "編輯畫面多出版本帳本與影響預覽。")]),
        S("enforce_layout", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["版面與選單的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="版面（含選單）發布前，是否強制先看過同一份草稿的影響預覽？", label="版面發布前強制預覽",
          help="建議同時開啟上面的「版本帳本與影響預覽」；即使之後把總開關關閉，已開啟的強制仍然有效（要解除只能關閉這個開關，且屬放寬、需第二位核准）。開啟後，版面與選單的發布若沒有帶著『看過的預覽』就會被擋下（沒有例外）。",
          impact="只在發布當下多一道檢查。選單編輯器會自動帶上預覽；版面編輯器若尚未接上，開啟後就無法發布版面，請先確認編輯器已更新。關閉強制屬於放寬，需等待期滿後生效並由另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與目前相同。"), (1, "強制", "沒看過預覽就不能發布版面。")]),
        S("enforce_custom_fields", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["自訂欄位集的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="自訂欄位發布前，是否強制先看過影響預覽？", label="自訂欄位發布前強制預覽",
          help="同上，對象是自訂欄位集。建議同時開啟「版本帳本與影響預覽」；關閉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；欄位編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需等待期滿後生效並由另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與目前相同。"), (1, "強制", "沒看過預覽就不能發布自訂欄位。")]),
        S("enforce_user_buttons", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["使用者自訂按鈕的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="自訂按鈕發布前，是否強制先看過影響預覽？", label="自訂按鈕發布前強制預覽",
          help="同上，對象是使用者自訂按鈕。建議同時開啟「版本帳本與影響預覽」；關閉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；按鈕編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需等待期滿後生效並由另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與目前相同。"), (1, "強制", "沒看過預覽就不能發布自訂按鈕。")]),
        S("enforce_output_template", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=0,
          impact_scope={"documents": ["輸出版型（列印／PDF）的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="輸出版型（列印／PDF）發布前，是否強制先看過影響預覽？", label="輸出版型發布前強制預覽",
          help="同上，對象是輸出版型。建議同時開啟「版本帳本與影響預覽」；關閉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；版型編輯器未接上預覽時開啟會無法發布。關閉強制屬於放寬，需等待期滿後生效並由另一位最高管理者核准才生效。",
          choices=[(0, "不強制（預設）", "發布行為與目前相同。"), (1, "強制", "沒看過預覽就不能發布輸出版型。")]),
        S("enforce_rule_set", "int", 0, min=0, max=1, risk="ops", loosen="down", recommended=1,
          impact_scope={"documents": ["規則集（標示規則）的發布與還原"], "roles": ["最高管理者"], "amounts": "不涉及金額。", "reversible": True, "effective": "pending"},
          question="規則集發布前，是否強制先看過影響預覽？", label="規則發布前強制預覽",
          help="建議開啟：規則頁一律會送出預覽，開了之後沒看過預覽就不能發布規則。關閉總開關不會解除這項強制。",
          impact="只在發布當下多一道檢查；規則頁已內建預覽，建議在規則功能上線時就開啟。關閉強制屬於放寬，需等待期滿後生效並由另一位最高管理者核准才生效。",
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
          question="是否開放最高管理者設定『條件成立就標紅／提醒』的規則？", label="開放標示規則",
          help="開啟後，最高管理者可以在規則頁用下拉選單設定條件（例如毛利低於多少就標紅），發布前可預覽現有紀錄有哪些會被標示。",
          impact="規則只標示、不阻擋：不會改任何資料、不會阻擋存檔，也不會發通知。看不到來源欄位的人（例如沒有成本權限者）不會看到由該欄位產生的標示。規則故障時只會暫停該條規則並提醒管理員。可隨時關閉。",
          choices=[(0, "關閉（預設）", "畫面與目前完全一樣。"), (1, "開啟", "規則頁可用，已發布的規則會在宣告了規則插槽的畫面上標示。")]),
        S("k01_seed", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否把報價單的『專案毛利提醒門檻』改由規則管理？", label="專案毛利提醒改由規則管理",
          help="開啟後，規則頁會多一個「匯入現有利潤警示」：把目前的門檻（設定中心的專案毛利提醒門檻）轉成一條規則。規則發布後，報價單的提醒門檻就以該規則為準，之後在規則頁調整（可預覽、有版本、調低門檻需第二位最高管理者核准）；規則發布之前，行為完全不變。",
          impact="報價單內部損益區的提醒畫面與目前相同（只在專案毛利低於門檻時用警示色標出，不阻擋存檔、送審）；只有看得到成本與毛利的人會看到。需先開啟『開放標示規則』。可隨時關閉，關閉後門檻回到設定中心的值。",
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
          question="是否讓最高管理者自行調整側欄選單的名稱與分組？", label="開放調整選單名稱與分組",
          help="開啟後，最高管理者可以改側欄項目的顯示名稱、把項目移到另一個既有群組，並在發布前預覽整份選單。",
          impact="只影響側欄怎麼顯示，不改任何人的權限：沒有權限的項目仍然不會出現，改名與換群組也不會讓人多看到任何東西。關閉後，已發布的改名與換群組會停止套用（資料保留），側欄回到原本的名稱與分組。立即生效。",
          choices=[(0, "不開放（建議）", "側欄維持系統預設的名稱與分組。"),
                   (1, "開放", "最高管理者可以在排版時改側欄項目名稱、換分組，並預覽整份選單。")]),
    ],
    sensitive=False, risk="ops",
    help="側欄選單的名稱與分組是否開放給最高管理者調整；預設關閉。",
)


def _quote_cf_customer_impact(conn, new_value):
    from helpers.settings_groups_q0 import quote_cf_scan
    r = quote_cf_scan(conn)
    if r is None:
        raise RuntimeError("count failed")
    n, capped = r
    return {"numbers": {"quotationsWithCustomFields": n, "atLeast": capped},
            "sentence": "目前有%s %d 張報價單填了自訂欄位；%s" % ("至少" if capped else "", n, "開放後，這些內容會印在它們的報價單 PDF、預覽與內部列印上。" if new_value else "改回只給內部人員後，報價單文件不再出現自訂欄位。")}


def _quote_cf_finance_impact(conn, new_value):
    from helpers.settings_groups_q0 import quote_cf_scan
    r = quote_cf_scan(conn)
    if r is None:
        raise RuntimeError("count failed")
    n, capped = r
    return {"numbers": {"quotationsWithCustomFields": n, "atLeast": capped},
            "sentence": "目前有%s %d 張報價單填了自訂欄位；%s" % ("至少" if capped else "", n, "開放後，這些內容會附在由它們產生的請款單與開票申請憑據上。" if new_value else "改回不附後，財務文件不再出現自訂欄位。")}


def _quote_cf_cross_check(values):
    """報價單自訂欄位的相依：要先開放總開關與『開放報價單自訂欄位』。回問題清單（空＝通過）。
    ⚠ 引擎的第一道檢查是『只帶改動的欄位、其餘補預設』，看不到已存的值——所以相依欄位沒帶時改讀目前已存的設定（讀不到 ⇒ 不擋）。
    這道檢查只是提早講清楚原因；真正的相依由使用端把關（`builtin_fields.quote_enabled`：總開關與報價單開關都開才算開）。"""
    try:
        from helpers import settings_registry as _SR
        stored = _SR.get_group("builder_custom_fields")
    except Exception:                                                                    # noqa: BLE001 — 讀不到已存值 ⇒ 不擋（使用端仍會把關）
        stored = {"enabled": True, "quote_enabled": 1}
    master = bool(values.get("enabled") or stored.get("enabled"))
    quote_on = bool(values.get("quote_enabled") or stored.get("quote_enabled"))
    out = []
    if values.get("quote_enabled") and not master:
        out.append("要先開放「內建畫面的自訂欄位」，報價單才能使用自訂欄位。")
    if values.get("quote_in_customer_output") and not quote_on:
        out.append("要先開放「報價單自訂欄位」，才能設定它印在報價單上。")
    if values.get("quote_on_finance_docs") and not quote_on:
        out.append("要先開放「報價單自訂欄位」，才能設定它附在財務文件上。")
    return out



# ── 內建畫面的自訂欄位（T61 S5）：管理者在內建單據畫面加自己的欄位。預設關閉＝上線前的畫面與資料（部署零行為變更）。 ──
register_group(
    "builder_custom_fields", "自訂欄位（內建畫面）",
    [
        S("enabled", "bool", False, risk="ops", recommended=False,
          question="是否開放管理者在案件資訊與供應商畫面加自己的欄位？", label="開放內建畫面的自訂欄位",
          help="開啟後，最高管理者可以在案件資訊與供應商畫面新增文字、日期、單選、勾選欄位，先預覽再發布，也可以還原。欄位只給內部人員看，不會出現在報價單、客戶版文件或回簽頁。",
          impact="開啟後，畫面多出「自訂欄位」區塊，單據可以多存這些欄位的值；既有欄位、金額與計算完全不變。關閉後，已經存的值仍保留在資料裡，但畫面不再顯示、也不能再改。可隨時關閉。",
          choices=[(False, "不開放（建議）", "畫面與資料維持目前的樣子。"),
                   (True, "開放自訂欄位", "最高管理者可新增並發布自訂欄位，發布後所有內部人員在對應畫面看得到並可填寫。")]),
        # ── T63 Q0：報價單自己的自訂欄位怎麼開放（預設全關＝與今天相同；先要開上面的總開關）。 ──
        S("quote_enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放管理者在報價單表單加自己的欄位？", label="開放報價單自訂欄位",
          help="需要先開放上面的「內建畫面的自訂欄位」。開啟後，最高管理者可以在報價單表單新增文字、日期、單選、勾選欄位；欄位只給能開啟這張報價單的內部人員看。",
          impact="只影響報價單表單多出「自訂欄位」區塊；報價單的既有欄位、金額與計算完全不變。關閉後，已經存的值仍保留在資料裡，但畫面不再顯示、也不能再改。",
          choices=[(0, "不開放（建議）", "報價單表單維持目前的樣子。"),
                   (1, "開放", "最高管理者可以為報價單新增並發布自訂欄位，發布前先預覽。")]),
        S("quote_in_customer_output", "int", 0, min=0, max=1, risk="legal", loosen="up", recommended=0,
          risk_text="【高影響】開放後，報價單自訂欄位的名稱與內容會印在客戶拿到的報價單上，填錯或不該公開的內容會被客戶看到。",
          impact_scope={"documents": ["報價單 PDF", "報價單預覽", "報價單內部列印"], "roles": ["客戶", "業務"], "amounts": "不改任何金額；只決定自訂欄位的文字是否會印在報價單上。", "reversible": True, "effective": "pending"},
          question="報價單的自訂欄位，是否可以印在報價單上？", label="報價單自訂欄位可印在報價單上",
          help="預設只給內部人員在表單上看。開放後，報價單 PDF、畫面預覽與內部列印（三者共用同一份版面）會在報價條件後面多印一個「其他資訊」區，列出有填的自訂欄位。客戶回簽單是客戶簽回的附件，沒有另外的畫面。需要先開放「報價單自訂欄位」。",
          impact="只影響之後產生或重新開啟的報價單文件，內部列印也會一起多印這個區；已經寄出的文件不會改，也不會動到任何已存的內容。開放屬於放寬，需要第二位最高管理者核准並等待期滿後生效；改回只給內部人員立即生效。",
          choices=[(0, "只給內部人員（建議）", "報價單 PDF、預覽與內部列印都不出現自訂欄位。"),
                   (1, "印在報價單上", "報價單 PDF、預覽與內部列印會多印「其他資訊」區。")],
          impact_fn=_quote_cf_customer_impact),
        S("quote_on_finance_docs", "int", 0, min=0, max=1, risk="money", loosen="up", recommended=0,
          risk_text="【高影響】開放後，報價單自訂欄位的名稱與內容會附在請款單與開票申請憑據上；任何有權下載那張請款單或憑據的人都會看到，即使他的角色沒有權限開啟那張報價單。自由輸入的欄位也可能被填進金額。",
          impact_scope={"documents": ["請款單 PDF", "開票申請憑據 PDF"], "roles": ["出納", "財務", "業務"], "amounts": "不改任何金額、稅額、單號或單據狀態；只決定自訂欄位的文字是否會附在財務文件上。", "reversible": True, "effective": "pending"},
          question="報價單的自訂欄位，是否可以附在請款單與開票申請憑據上？", label="報價單自訂欄位可附在財務文件上",
          help="預設不附。開放後，請款單 PDF 與開票申請憑據 PDF 會多一個「其他資訊（報價單）」區，列出該報價單目前有填的自訂欄位；內容是印出當下從報價單讀取，不會複製進財務資料。有權下載該請款單或憑據的人都看得到這些內容，就算他的角色不能開啟那張報價單；自由輸入的文字欄位也可能被填進金額，請先確認欄位用途。應收清單、出納列表、會計傳票與報表不受影響。需要先開放「報價單自訂欄位」。",
          impact="只影響之後產生或重新開啟的請款單與開票申請憑據文件；已經寄出的文件不會改，金額、稅額與單據狀態完全不變。開放屬於放寬，需要第二位最高管理者核准並等待期滿後生效；改回不附立即生效。",
          choices=[(0, "不附（建議）", "請款單與開票申請憑據不出現自訂欄位。"),
                   (1, "附在財務文件上", "請款單與開票申請憑據會多印「其他資訊（報價單）」區。")],
          impact_fn=_quote_cf_finance_impact),
    ],
    sensitive=False, risk="ops", cross_check=_quote_cf_cross_check,
    help="決定內建畫面（案件資訊、供應商）是否開放管理者新增自己的欄位，以及報價單是否開放自訂欄位。",
)


# ── 使用者自訂按鈕（T61 S6）：管理者在登記的位置放「開啟頁面」「執行匯出」按鈕。預設關閉＝上線前的畫面（部署零行為變更）。 ──
register_group(
    "builder_actions", "自訂按鈕",
    [
        S("enabled", "bool", False, risk="ops", recommended=False,
          question="是否開放管理者在供應商管理頁的工具列放自己的按鈕？", label="開放自訂按鈕",
          help="開啟後，最高管理者可以在供應商管理頁的工具列新增按鈕：「開啟某個頁面」或「執行某個已登記的匯出」，先預覽再發布，也可以還原。按鈕只是入口，不會讓任何人看到或匯出其原本無權檢視或匯出的內容。",
          impact="只影響供應商管理頁的工具列。關閉時畫面與現在完全相同；開啟後，已發布的按鈕才會出現，而且每個人只看得到自己有權限的那幾顆。按鈕不會寫入任何資料。可隨時關閉。",
          choices=[(False, "不開放（建議）", "工具列維持目前的樣子。"),
                   (True, "開放自訂按鈕", "最高管理者可新增並發布按鈕；匯出類按鈕的新增在治理開啟時需要第二位最高管理者核准。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放管理者在畫面上放自己的「開頁」「匯出」按鈕（目前只有供應商管理頁的工具列）。",
)


# 儲存／上傳插槽（BP-4 S1；設計 BP4-STORAGE-NOTIFY-DESIGN §3）：預設關＝上傳位置、副檔名、大小上限與今天完全相同（部署零行為變更）。
# 開啟後（S2 起）最高管理者才能為單據宣告附件種類；位置代號與硬白名單仍由程式決定，插槽只能縮小。
register_group(
    "builder_slots", "附件種類與儲存位置",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否讓最高管理者自行宣告單據的附件種類與存放位置？", label="開放自訂附件種類",
          help="開啟後，最高管理者可以為某種單據（例如完工單）新增附件種類，並從系統認可的位置清單挑選存放位置、可收的檔案類型與大小。",
          impact="只影響之後新上傳的檔案；已存的檔案不搬移、讀取權限也不變。檔案類型與大小只能比系統底線更嚴，不能更寬；誰能看檔案仍由原本的單據權限決定。可隨時關閉，關閉後回到目前的上傳規則。",
          choices=[(0, "不開放（建議）", "附件的存放位置與可上傳的檔案類型維持目前的規則。"),
                   (1, "開放", "最高管理者可以新增附件種類並發布；發布前可預覽，放寬需第二位最高管理者核准。")]),
    ],
    sensitive=False, risk="ops",
    help="附件種類與存放位置是否開放自訂；預設關閉。",
)


# ── 自訂匯出（BP-3）：管理者決定匯出檔有哪些欄位、標題、順序（先導：每日任務歷程 CSV）。預設關閉＝上線前的匯出檔（部署零行為變更）。 ──
register_group(
    "builder_exports", "自訂匯出",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放管理者自訂匯出檔的欄位與標題？", label="開放自訂匯出",
          help="開啟後，最高管理者可以在支援的匯出（每日任務歷程、外包名冊 Excel、開票申請憑據 PDF）調整要匯出哪些欄位、標題與順序，或加頁首／頁尾／浮水印（只能從預設文字挑選），先預覽再發布，也可以還原。必須同時開啟「建構器治理」才會生效。",
          impact="只影響匯出檔的欄位、標題與順序：資料仍是原本的查詢結果，沒有權限看的欄位不會出現；沒有發布過範本的匯出完全不變。新增欄位、新增或改變頁首頁尾浮水印文字都屬於放寬，需要第二位最高管理者核准。關閉（或關閉建構器治理）後，已發布的範本不再套用，匯出回到系統預設。可隨時關閉。",
          choices=[(0, "不開放（建議）", "匯出檔維持系統預設的欄位與標題。"),
                   (1, "開放", "最高管理者可以調整支援匯出的欄位、標題與順序，發布前先預覽。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放管理者自訂匯出檔的欄位、標題與順序；預設關閉。",
)


# ── 自訂選項清單（census #4）：管理者決定下拉選單有哪些選項、顯示名稱與順序（客戶類型、供應商類型、料件分類、料件單位）。預設關閉＝上線前的下拉選單。 ──
register_group(
    "builder_option_lists", "自訂選項清單",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放管理者自訂下拉選單的選項？", label="開放自訂選項清單",
          help="開啟後，最高管理者可以新增選項、改顯示名稱、調整順序或停用選項（客戶類型、供應商類型、料件分類、料件單位、案件款項期別名稱、請款單款項類別），先預覽再發布，也可以還原。已經在用的選項不能刪除，只能停用。必須同時開啟「建構器治理」才會生效。",
          impact="只影響下拉選單如何列出：已存的客戶、供應商、料號資料不會被改。停用的選項，舊資料照常顯示、新增或編輯時不能再選。關閉（或關閉建構器治理）後，下拉選單回到系統預設。可隨時關閉。",
          choices=[(0, "不開放（建議）", "下拉選單維持系統預設的選項。"),
                   (1, "開放", "最高管理者可以調整支援的下拉選單，發布前先預覽。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放管理者自訂下拉選單的選項；預設關閉。",
)


# ── 清單個人偏好（T66）：每個人可以自己調整清單的欄位、排序與每頁筆數，範圍由公司政策決定。預設關閉＝上線前的清單。 ──
register_group(
    "list_prefs", "清單個人偏好",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否讓每個人自己調整清單的欄位、排序與每頁筆數？", label="開放清單個人偏好",
          help="開啟後，每個人可以在支援的清單隱藏或重排欄位、選預設排序與每頁筆數；可選的範圍由最高管理者在公司政策裡決定。金額欄位只能隱藏或重排，不會因此多出現。必須同時開啟「建構器治理」才會生效。",
          impact="只影響每個人自己看到的清單外觀：資料與權限不變，沒有權限看的欄位不會出現，匯出與列印不受影響。關閉（或關閉建構器治理）後，所有人回到系統預設的清單；個人的選擇會保留，重新開啟後恢復。可隨時關閉。",
          choices=[(0, "不開放（建議）", "清單維持系統預設的欄位、排序與每頁筆數。"),
                   (1, "開放", "每個人可以在公司允許的範圍內調整支援的清單。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放每個人自己調整清單的欄位、排序與每頁筆數；預設關閉。",
)


# ── 到期預警天數（census #7）：預設＝今天寫死的數字（保固報表 90 天、保固郵件 7／30 天、確認檔到期提醒 30 天） ──
register_group(
    "alerts", "到期預警",
    [
        S("warranty_report_days", "int", 90, min=30, max=365, unit="天", risk="ops", loosen="down", recommended=90,
          question="營運報表的「保固到期預警」要列出幾天內到期的設備？", label="保固報表預警天數",
          help="營運報表裡的保固到期預警，會列出這個天數以內就要到期的設備。",
          impact="只影響報表的呈現與統計：天數調短，報表看到的預警會變少（設備與保固資料本身不變）；調短須另一位最高管理者核准並等待期滿後才生效，調長立即生效。",
          when="想讓營運報表提早（或延後）列出快到期的保固。"),
        S("warranty_mail_early_days", "int", 30, min=8, max=180, unit="天", risk="ops", loosen="down", recommended=30,
          question="保固到期前幾天，要先寄第一封提醒信？", label="保固提醒信（提前）天數",
          help="設備保固到期前這麼多天，系統會寄第一封提醒信給負責人。",
          impact="只影響之後的提醒：每台設備、每個階段只寄一次。調短會較晚提醒，須另一位最高管理者核准並等待期滿後生效；調長立即生效（可能讓已寄過的設備再收到一次新階段的信）。",
          when="業務需要更早排程更換設備時。"),
        S("warranty_mail_urgent_days", "int", 7, min=1, max=30, unit="天", risk="ops", loosen="down", recommended=7,
          question="保固到期前幾天，要再寄一封「緊急」提醒信？", label="保固提醒信（緊急）天數",
          help="設備保固快到期時，系統會再寄一封標示緊急的提醒信；這個天數必定小於「提前」天數。",
          impact="只影響之後的提醒，每台設備只寄一次。調短會較晚發出緊急提醒，須另一位最高管理者核准並等待期滿後生效；調長立即生效。",
          when="想在更接近到期日時再催一次。"),
        S("cert_warn_days", "int", 30, min=7, max=90, unit="天", risk="ops", loosen="down", recommended=30,
          question="開發者簽章確認檔到期前幾天，要開始在系統中心提醒？", label="確認檔到期提醒天數",
          help="確認檔過期後輸出會暫停；到期前這麼多天起，系統中心會出現換發提醒。",
          impact="只影響提醒出現的時間，不影響確認檔本身是否有效。調短會較晚提醒，須另一位最高管理者核准並等待期滿後生效；調長立即生效。",
          when="換發簽章確認檔需要較長前置作業時，提早提醒。"),
    ],
    sensitive=False, risk="ops",
    help="各種「快到期了」提醒的提前天數。",
)


def _pw_impact(conn, new_value):
    """即時影響（唯讀、只給資訊）：目前有多少啟用中的帳號。系統只存密碼雜湊，無法知道既有密碼的長度，所以不會、也不能要求任何人改密碼。"""
    n = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    return {"numbers": {"activeAccounts": n},
            "sentence": "目前有 %d 個啟用中的帳號。調成 %s 碼只影響之後新設或更改密碼；既有密碼的長度系統無法得知，也不會要求任何人改密碼。" % (n, new_value)}


# ── 登入與密碼（census #8）：只准加嚴，不准放寬到預設以下 ──
register_group(
    "account_security", "登入與密碼",
    [
        S("password_min_len", "int", 8, min=8, max=64, unit="碼", risk="security", loosen="down", recommended=8,
          question="密碼最少要幾碼？（最少 8 碼，只能往上調）", label="密碼最短長度",
          help="新設或更改密碼時，長度至少須達此碼數。系統規定最少 8 碼，這裡只能調得更嚴。",
          impact="只影響之後「新設或更改密碼」的長度檢查：已經設好的密碼不受影響，也不會有人被要求改密碼，登入照舊。系統只存密碼的雜湊，無法得知現有密碼多長，所以看不到有多少人低於新的長度。調高立即生效，調回較低的數字須另一位最高管理者核准並等待期滿後生效。",
          risk_text="調低會讓新設的密碼比較容易被猜到；系統規定最少 8 碼，不能再低。",
          impact_scope={"documents": ["帳號密碼"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響之後新設或更改密碼的長度檢查，既有密碼與登入不受影響。", "reversible": True, "effective": "pending"},
          impact_fn=_pw_impact),
        S("login_days", "int", 30, min=1, max=30, unit="天", risk="security", loosen="up", recommended=30,
          question="登入後最久可以不重新登入幾天？（最多 30 天，只能往下調）", label="登入有效天數",
          help="登入之後，超過這個天數就要重新輸入帳號密碼。系統規定最長 30 天，這裡只能縮短。",
          impact="只影響之後新登入的人，已經登入的人維持原來的期限；縮短立即生效，調回較長的天數須另一位最高管理者核准並等待期滿後生效。",
          risk_text="登入有效期越長，電腦被他人使用或遺失時帳號被冒用的時間越長；系統規定最長 30 天。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響之後新登入的有效天數，已登入者不受影響。", "reversible": True, "effective": "pending"}),
        S("company_profile_full_read_superadmin_only", "int", 1, min=0, max=1, risk="security", loosen="down", recommended=1,
          question="完整的公司資料（匯款帳號、電話、地址等；統編與聯絡方式仍會顯示給所有人）是否只讓最高管理者查看？", label="完整公司資料只給最高管理者看",
          help="開啟（預設）：只有最高管理者讀得到完整內容；其他人的畫面只會拿到公司名稱、統編、聯絡方式與據點名稱，單據列印不受影響。關閉：任何登入的人都能讀到完整的公司資料。",
          impact="只影響畫面向系統查詢公司資料的方式：案件、核准、報價單、傳票、勞報單等頁面使用精簡版，照常運作；單據與 PDF 照舊印出匯款帳號等資料。開啟立即生效；關閉（讓所有登入者讀得到完整資料）屬於放寬，須另一位最高管理者核准並等待期滿後生效。",
          risk_text="關閉時，任何登入的帳號（包含權限很低的帳號）都能查到公司的匯款帳號、統編與聯絡資料。",
          impact_scope={"documents": ["公司資料"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響誰能查詢完整的公司資料，單據列印不受影響。", "reversible": True, "effective": "pending"},
          choices=[(0, "不限制", "任何登入的人都能讀到完整的公司資料。"),
                   (1, "只給最高管理者（預設、建議）", "只有最高管理者讀得到完整內容；其他人只拿到名稱、統編、聯絡方式與據點名稱。")]),
    ],
    sensitive=False, risk="security",
    help="登入與密碼的規則：只能調得更嚴，不能放寬到系統規定的底線以下。",
)

# ── 外網登入防護（2026-11-12 外網登入強化票）：外網強制兩步驟驗證（TOTP）＋單一帳號鎖定。預設＝開（保守）；放寬方向（關閉、減少角色、
#    調高門檻、縮短鎖定、改回只鎖外網…）一律走確認期間＋第二位最高管理者核准。判定與規則見 helpers/external_access.py、helpers/account_lock.py。 ──
_EXT_ROLE_LABELS = (("superadmin", "最高管理者", 1), ("admin", "管理員", 1), ("finance", "財務", 1),
                    ("sales", "業務", 0), ("engineer", "工程師", 0), ("viewer", "檢視者", 0))


def _ext_role_field(role, label, default):
    return S("ext_totp_role_" + role, "int", default, min=0, max=1, risk="security", loosen="down", recommended=1 if default else None,
             question="從外網登入時，「%s」是否必須先啟用兩步驟驗證？" % label, label="外網登入強制兩步驟驗證：%s" % label,
             help="開啟後，%s 從外網（經網際網路、不是公司內網）登入時，如果帳號尚未啟用兩步驟驗證就不能登入，要先在公司內網登入並啟用。內網登入不受影響。" % label,
             impact="只影響之後的外網登入，已經登入的人不受影響。調成「不強制」屬於放寬，須另一位最高管理者核准並等待期滿後生效；調成「強制」立即生效。",
             risk_text="不強制的角色，只靠密碼就能從外網登入；帳號密碼外洩時，外人就能看到客戶、報價與財務資料。",
             impact_scope={"documents": ["登入狀態"], "roles": [label], "amounts": "不涉及金額；只影響該角色從外網登入的條件。", "reversible": True, "effective": "pending"},
             choices=[(1, "強制（建議）" if default else "強制", "這個角色從外網登入前必須已啟用兩步驟驗證，沒啟用的人要先在公司內網登入並啟用。"),
                      (0, "不強制", "這個角色從外網登入只需要密碼（有啟用兩步驟驗證的人仍會被要求輸入驗證碼）。")])


register_group(
    "external_login", "外網登入防護",
    [
        S("ext_totp_enabled", "int", 1, min=0, max=1, risk="security", loosen="down", recommended=1,
          question="是否啟用「外網登入強制兩步驟驗證」？", label="外網強制兩步驟驗證（總開關）",
          help="開啟後，下面勾選的角色從外網登入時必須已啟用兩步驟驗證；沒啟用的會被拒絕並提示先在公司內網啟用。關閉＝所有角色在外網都只需密碼。",
          impact="只影響之後的外網登入；內網登入完全不變。關閉屬於放寬，須另一位最高管理者核准並等待期滿後生效；開啟立即生效。",
          risk_text="關閉後，外網登入只靠密碼；帳號密碼外洩時外人可直接進入系統。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響外網登入的條件。", "reversible": True, "effective": "pending"},
          choices=[(1, "開啟（建議）", "指定角色從外網登入必須先啟用兩步驟驗證。"), (0, "關閉", "外網登入不額外要求兩步驟驗證。")]),
    ] + [_ext_role_field(*r) for r in _EXT_ROLE_LABELS] + [
        S("lock_threshold", "int", 10, min=3, max=100, unit="次", risk="security", loosen="up", recommended=10,
          question="同一個帳號在時間窗內輸錯幾次，就暫時鎖住這個帳號？", label="帳號鎖定的失敗次數",
          help="不分來源位址：同一個帳號在「計算時間窗」內累計輸入錯誤達此次數，即暫時鎖定該帳號（預設只擋外網來源，內網照常能登入）。",
          impact="只影響之後的失敗計數。調高（更寬鬆）須另一位最高管理者核准並等待期滿後生效；調低立即生效。",
          risk_text="次數越高，攻擊者可以對同一個帳號猜越多次密碼才會被鎖。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響帳號鎖定的門檻。", "reversible": True, "effective": "pending"}),
        S("lock_window_min", "int", 30, min=5, max=1440, unit="分鐘", risk="security", loosen="down", recommended=30,
          question="帳號輸錯次數要在多長的時間窗內累計？", label="帳號鎖定的計算時間窗",
          help="在這段時間內累計的失敗次數才算數；超過這段時間的舊失敗不計。",
          impact="只影響之後的失敗計數。縮短（更寬鬆）須另一位最高管理者核准並等待期滿後生效；拉長立即生效。",
          risk_text="時間窗越短，攻擊者放慢速度猜密碼就不會被鎖。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響帳號鎖定的計算窗口。", "reversible": True, "effective": "pending"}),
        S("lock_minutes", "int", 30, min=5, max=1440, unit="分鐘", risk="security", loosen="down", recommended=30,
          question="帳號被鎖住之後，要鎖多久才自動解除？", label="帳號鎖定的時間",
          help="鎖住期間，該帳號從外網（或依下面的模式連內網）無法登入；時間到自動解除。最高管理者也可以手動解除，在內網成功登入也會解除。",
          impact="只影響之後新發生的鎖定。縮短（更寬鬆）須另一位最高管理者核准並等待期滿後生效；拉長立即生效。",
          risk_text="鎖定時間越短，攻擊者越快可以繼續猜；越長，帳號本人等待越久（內網登入可立即解除）。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響帳號鎖定的時間長度。", "reversible": True, "effective": "pending"}),
        S("lock_scope", "int", 1, min=1, max=2, risk="security", loosen="down", recommended=1,
          question="帳號被鎖住時，是否連公司內網的登入也一併阻擋？", label="帳號鎖定的範圍",
          help="建議只擋外網：這樣就算有人故意輸入錯誤密碼，帳號本人在公司內網仍然可以登入，也能藉由內網登入解除鎖定。選「全部來源」最嚴，但任何人都能故意輸入錯誤密碼，使其他人無法登入系統。",
          impact="只影響之後的帳號鎖定判斷。從「全部來源」改回「只擋外網」屬於放寬，須另一位最高管理者核准並等待期滿後生效；改成「全部來源」立即生效。",
          risk_text="「全部來源」下，任何人（包含外網的陌生人）故意輸入錯誤就能讓指定帳號在公司內也無法登入，直到鎖定時間結束或最高管理者解鎖。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響帳號鎖定是否也擋內網。", "reversible": True, "effective": "pending"},
          choices=[(1, "只擋外網（建議）", "只有外網來源的失敗會計數、被鎖時只擋外網登入；內網照常登入並可解除鎖定。"),
                   (2, "全部來源", "不分來源計數，被鎖時內網也擋；有被故意輸入錯誤鎖住的風險。")]),
        S("external_hosts", "str", "", risk="security", requires_pending=True, advanced=True,
          question="哪些網域代表「從外網進來」？（多個用逗號分隔）", label="外網網域",
          help="請求的網址網域在這份清單裡，就一律當外網（除此之外，經外網通道進來、或來源位址不在內網網段的請求也都是外網）。",
          impact="只影響之後的外網判定；變更須經等待期滿後才生效。",
          risk_text="漏填網域不會放寬太多（來源位址與外網通道的痕跡仍會判成外網），但請勿移除外網網域。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響哪些請求被當成外網。", "reversible": True, "effective": "pending"}),
        S("loopback_is_internal", "int", 0, min=0, max=1, risk="security", loosen="up", recommended=0, advanced=True,
          question="在伺服器這台電腦上直接開網頁登入，是否視為公司內網？", label="本機直連算內網",
          help="預設不算：在伺服器本機開網頁登入也適用外網規則（被要求兩步驟驗證的角色要先啟用）。因為同一台電腦上的其他程式（轉送程式、代理）也能讓外面的人看起來像是本機直連。只有確定本機沒有任何轉送外網流量的程式時才建議開啟。",
          impact="只影響之後的登入判定。改成「算內網」屬於放寬，須另一位最高管理者核准並等待期滿後生效；改回「不算」立即生效。",
          risk_text="開啟後，只要有程式在同一台電腦上把外網流量轉進來而沒有帶外網通道的標頭，外面的人就會被當成內網，免除兩步驟驗證與帳號鎖定。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響本機直連是否被當成內網。", "reversible": True, "effective": "pending"},
          choices=[(0, "不算內網（建議）", "本機直連也適用外網規則。"), (1, "算內網", "本機直連視為內網，免外網強制兩步驟驗證與帳號鎖定。")]),
        S("internal_networks", "str", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10", risk="security", requires_pending=True, advanced=True,
          question="哪些網段算「公司內網」？（多個用逗號分隔）", label="內網網段",
          help="來源位址在這些網段、且沒有經過代理或外網通道的請求才算內網。只接受私有網段（公司內部使用的位址範圍），填公開網段會被忽略，所以不可能把外網變成內網。",
          impact="只影響之後的內外網判定；變更須經等待期滿後才生效。",
          risk_text="內網網段越大，被當成內網（免強制兩步驟驗證）的來源越多；請只列公司實際使用的網段。",
          impact_scope={"documents": ["登入狀態"], "roles": ["所有使用者"], "amounts": "不涉及金額；只影響哪些來源被當成內網。", "reversible": True, "effective": "pending"}),
    ],
    sensitive=False, risk="security",
    help="從外網（經外網通道、不是公司內網）登入時的額外防護：指定角色必須先啟用兩步驟驗證，以及同一帳號輸入錯誤次數過多即暫時鎖定。內網登入行為不變。",
)

# ── 自訂通知用語（S-X3）：管理者決定簽核事件的站內訊息與通知信文字（先導：報價單送審）。預設關閉＝上線前的文字（部署零行為變更）。 ──
register_group(
    "builder_notify", "自訂通知用語",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放管理者調整簽核通知的用語？", label="開放自訂通知用語",
          help="開啟後，最高管理者可以調整報價單送審時，簽核人收到的站內訊息與通知信的文字（只能放系統提供的單號、對象名稱等占位符，不能放網址或標記），先預覽再發布，也可以還原。必須同時開啟「建構器治理」才會生效。信件主旨前綴與分類、信件版型、收件人與寄送時機都不能改。",
          impact="只影響通知文字：誰收到、何時寄、核准規則都不變；沒有發布過範本的事件完全不變。新增或改變用語都屬於放寬，需要第二位最高管理者核准。關閉（或關閉建構器治理）後，已發布的範本不再套用，通知回到系統預設字。可隨時關閉。",
          choices=[(0, "不開放（建議）", "通知文字維持系統預設。"),
                   (1, "開放", "最高管理者可以調整支援事件的通知文字，發布前先預覽。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放管理者調整簽核通知的文字；預設關閉。",
)


# ── 自訂案件階段樣板（S-ST1）：管理者定義一組常用的執行階段（名稱、日期建議、收入認列比例建議），之後新案件可一鍵套用。預設關閉＝上線前的行為（部署零行為變更）。 ──
register_group(
    "builder_stage_templates", "自訂案件階段樣板",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放管理者定義案件執行階段的樣板？", label="開放自訂階段樣板",
          help="開啟後，最高管理者可以定義一組常用的執行階段（階段名稱、起訖天數、前置階段，以及選填的收入認列比例建議），先預覽再發布，也可以還原。必須同時開啟「建構器治理」才會生效。階段名稱只能用中文、英數字與常用標點（不能含斜線，也不能有像網址的寫法，例如英文名稱裡夾著小數點）。樣板只是新增案件階段時的預填：已經存在的案件不會被改動。",
          impact="本設定只開放定義樣板；案件頁既有的階段新增、編輯、提醒、收入認列與結案關卡完全不變。移除樣板裡的階段或更動收入認列比例屬於放寬，需要第二位最高管理者核准。關閉（或關閉建構器治理）後，已發布的樣板不再被使用，案件頁回到手動新增階段。可隨時關閉。",
          choices=[(0, "不開放（建議）", "案件階段維持手動新增。"),
                   (1, "開放", "最高管理者可以定義階段樣板，發布前先預覽。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放管理者定義案件執行階段的樣板；預設關閉。",
)

# ── 自訂模組引擎總開關（P8，T78）：最高管理者能不能「建立新的」自訂模組。預設關閉＝與其他 builder_* 功能一致（預設關、逐項開）。 ──
register_group(
    "builder_custom_modules", "自訂模組引擎（建立新模組）",
    [
        S("enabled", "int", 0, min=0, max=1, risk="ops", recommended=0,
          question="是否開放最高管理者建立新的自訂模組？", label="開放建立自訂模組",
          help="開啟後，最高管理者可以在「模組建構器」建立新的自訂模組（欄位、版面、流程與簽核、輸出都從系統目錄挑選），存草稿、發布與還原都可以。關閉時不能建立新模組（也不能發布從未發布過的草稿）。",
          impact="關閉不是下架：已發布的自訂模組、它們的單據、查詢與輸出，以及它們自己的草稿／發布／還原完全不受影響；只是不能再建立新的模組。",
          choices=[(0, "不開放（建議）", "模組建構器只能開啟與修改既有的自訂模組。"),
                   (1, "開放", "最高管理者可以建立新的自訂模組。")]),
    ],
    sensitive=False, risk="ops",
    help="決定是否開放建立新的自訂模組；預設關閉。",
)

# T63 Q0：報價單輸出／個資群組（拆檔以免本檔再變大；同樣屬於 core）
from helpers import settings_groups_q0 as _q0  # noqa: E402

_q0.register(S, _register_core)

# T64 A：利潤提醒色帶／報價單預設值（拆檔，同屬 core）
from helpers import settings_groups_profit as _profit  # noqa: E402

_profit.register(S, _register_core)

# T65 C1：清單檢視個人偏好（拆檔，同屬 core）
from helpers import settings_groups_list_view as _list_view  # noqa: E402

_list_view.register(S, _register_core)

# C7：小模組狀態／單位／用語顯示名稱（拆檔，同屬 core）
from helpers import display_labels as _display_labels  # noqa: E402

_display_labels.register(S, _register_core)

# T68 A4：勞報單選派發下拉筆數（拆檔，同屬 core）
from helpers import settings_groups_payslip_picker as _payslip_picker  # noqa: E402

_payslip_picker._register(S, _register_core)

# T68 Y：法規參數跨年提醒起算日（拆檔，同屬 core）
from helpers import settings_groups_legal_reminder as _legal_reminder  # noqa: E402

_legal_reminder._register(S, _register_core)

# T69 SO-S2：資源回收筒保留天數（拆檔，同屬 core）
from helpers import settings_groups_recycle_bin as _recycle_bin  # noqa: E402

_recycle_bin._register(S, _register_core)

# UX P1.5：系統標語（拆檔，同屬 core）
from helpers import settings_groups_brand as _brand  # noqa: E402

_brand._register(S, _register_core)


def _backfill_cross_check(values):
    """earliest_month 必須是合法年月（YYYYMM，月份 01–12）；年份範圍由欄位上下限（2000–2099）管。"""
    m = values.get("earliest_month")
    if isinstance(m, int) and not isinstance(m, bool) and not 1 <= m % 100 <= 12:
        return [{"path": "earliest_month", "message": "最早可補登月份：月份必須是 01 到 12（例如 202001）"}]
    return []


# T69 補登歷史案件 L0（設計 D:/Claude-pm/reports/design-backfill-quote-t69.md §9 裁示 4）：預設關＝今天的行為（沒有任何補登入口）。
# 使用者裁示：開關**立即生效、僅強制稽核**（不經第二位最高管理者核准、不設確認期間），所以不設 `loosen`。
# 真正的限制在『最高管理者專屬、不可委派』的能力 case.quote_backfill.create 與預設關；L0 只登記開關，端點在 L1。
register_group(
    "quote_backfill", "補登歷史案件",
    [
        S("enabled", "int", 0, min=0, max=1, risk="none", recommended=0,
          question="是否開放最高管理者補登過去月份的已成案報價單？", label="開放補登歷史案件",
          help="開啟後，只有最高管理者可以補登過去月份（不含本月）的已成案報價單，單號依該單所屬月份編列（例如補登 7 月的案件，單號就是 7 月的號碼）。補登一定要填原因，並留下稽核紀錄。補登完請記得關閉。",
          impact="只開放最高管理者的補登入口；一般新增報價單的編號與流程完全不變。開啟與關閉立即生效，並留下稽核紀錄。補登的案件不發成案通知、不觸發提醒，利潤與公益金以現行口徑計算並註明。",
          choices=[(0, "關閉（預設）", "沒有補登入口。"), (1, "開啟", "最高管理者可補登過去月份的已成案報價單。")],
          when="只在需要補登過去月份的成案單時打開，補完就關。"),
        S("earliest_month", "int", 202001, min=200001, max=209912, risk="none", recommended=202001,
          question="最早可以補登到哪一個月？（填年月，例如 202001）", label="最早可補登月份",
          help="補登的報價日期不得早於這個月份；也不得是本月或未來。",
          impact="只限制補登時可選的月份範圍，不影響已存在的報價單。",
          when="要補登更早的月份，或想縮小可補登範圍時。"),
        S("auto_off_hours", "int", 24, min=0, max=720, unit="小時", risk="none", recommended=24,
          question="開啟補登後，要在幾小時後自動關閉？（0＝不自動關閉）", label="補登開啟後自動關閉（小時）",
          help="為了減少暴露時間，開啟「補登歷史案件」後超過這個小時數，系統就自動視為關閉（要再補登請重新開啟）。填 0 表示不自動關閉。",
          impact="只影響補登入口的開放時間；已補登的報價單不受影響。調整立即生效並留下稽核紀錄。",
          when="想縮短補登入口開著的時間，避免忘記關。"),
    ],
    sensitive=False, risk="ops",
    help="最高管理者補登過去月份已成案報價單的開關與可補登的最早月份；預設關閉。",
    cross_check=_backfill_cross_check,
)

# T69 管銷分攤預設比率（拆檔，同屬 core）
from helpers import settings_groups_overhead as _overhead  # noqa: E402

_overhead.register(S, _register_core)

# S5：四個外部群組（獎金傳票科目／法規參數／T100 匯出科目／管銷口徑；拆檔，同屬 core；external＝只能走原頁面的舊端點）
from helpers import settings_groups_external as _external  # noqa: E402

_external.register(S, _register_core)

# T70：附近旅宿資料新舊提示天數（拆檔，同屬 core）
from helpers import settings_groups_lodging_freshness as _lodging_freshness  # noqa: E402

_lodging_freshness._register(S, _register_core)

# T70：地圖標案「即將截止」天數（拆檔，同屬 core）
from helpers import settings_groups_tender_closing as _tender_closing  # noqa: E402

_tender_closing._register(S, _register_core)

# 物料流程一條龍各批次的開關（拆檔，同屬 core；P0b／P0d／P0a／P0c／P1' 共用一個群組）
from helpers import settings_groups_onepipe as _onepipe  # noqa: E402

_onepipe._register(S, _register_core)

# T85：匯入精靈開關與上傳大小上限（拆檔，同屬 core）
from helpers import settings_groups_import_wizard as _import_wizard  # noqa: E402

_import_wizard._register(S, _register_core)
