# T86 文字專業化——前後對照表

範圍：中文顯示字串的修改（畫面文字、通知文字、說明文件；測試檔不收；PDF、匯出、列印相關檔不在範圍）。比對區間：`c21e502d6..1580c8c1b`。

共 1085 組不同的改動（相同的改前／改後只列一次）。

## 後端訊息／通知（499 組）

| 改前 | 改後 | 位置 |
|---|---|---|
| …\n⚠ 這則告警的通知信寄不出去（%s）—— 請直接處理… | …\n⚠ 這則告警的通知信無法寄出（%s）—— 請直接處理… | archive.py |
| …  "menu": ("看得到選單", "導覽列與系統… | …  "menu": ("可檢視選單", "導覽列與系統… | capabilities.py |
| …: ("查看", "可以打開並閱讀這類資料"),… | …: ("查看", "可以開啟並閱讀這類資料"),… | capabilities.py |
| …("查看金額", "可以看到成本、毛利、報價與付款金… | …("查看金額", "可以檢視成本、毛利、報價與付款金… | capabilities.py |
| …("查看個資", "可以看到銀行帳號、身分證字號、電… | …("查看個資", "可以檢視銀行帳號、身分證字號、電… | capabilities.py |
| …群組不存在，或這位使用者看不到該群組"})… | …群組不存在，或這位使用者無法檢視該群組"})… | menu.py |
| …限", "sub": "誰能進系統、能看什麼、能做什麼"},… | …限", "sub": "帳號、存取範圍與操作權限"},… | system_hub.py |
| …程", "sub": "誰簽什麼、單據類型與款別"},… | …程", "sub": "簽核人、單據類型與款別"},… | system_hub.py |
| …件", "sub": "什麼事通知誰、怎麼通知"},… | …件", "sub": "通知事件、對象與方式"},… | system_hub.py |
| …錄", "sub": "誰在什麼時候做了什麼"},… | …錄", "sub": "操作人員、時間與內容"},… | system_hub.py |
| …dden": "找不到或看不到", "conflict… | …dden": "找不到或無法檢視", "conflict… | audit.py |
| …有人申請把對外心跳監控換到另一個主機，等待另一位最高管理… | …有人申請把對外心跳監控換至另一台主機，等待另一位最高管理… | backup_monitor.py |
| …se "對外心跳監控已換到另一個主機",… | …se "對外心跳監控已換至另一台主機",… | backup_monitor.py |
| …刪除；請改為在選單隱藏（誰看得到＝無人）", recor… | …刪除；請改為在選單隱藏（可檢視對象＝無人）", recor… | custom_module_delete.py |
| …, "前綴只能用大寫英文與數字、英文開頭，最長 6 字"))… | …, "前綴只能用大寫英文字母與數字、英文字母開頭，最長 6 字（不能… | custom_modules.py |
| …、英文開頭，最長 6 字"))… | …文字母開頭，最長 6 字（不能有空白、符號或中文），例如 EL"))… | custom_modules.py |
| …號字首（含曾經用過的），請換一組" % n["prefi… | …號字首（含曾經用過的），單號會被誤認成案件單號。請換一組，例如在後面加一個字母" % n["prefi… | custom_modules.py |
| …te", "日期格式只能是 YYYYMMDD、YYY… | …te", "日期格式只能選「年月日」、「年月」或不含日期（YYYYMMDD、YYY… | custom_modules.py |
| …D、YYYYMM 或空白"))… | …D、YYYYMM 或空白）"))… | custom_modules.py |
| …流水號位數必須是 3～8"))… | …流水號位數必須是 3～8 的整數，例如 4 代表 0001"))… | custom_modules.py |
| …": "至少要有一個欄位"}], status=… | …": "至少要有一個欄位：請到「欄位」步驟新增，填上顯示名稱與 key"}], status=… | custom_modules.py |
| …影響範圍：%s只換畫面上看到的名稱，不改任何資料、狀… | …影響範圍：%s只換畫面上顯示的名稱，不改任何資料、狀… | display_labels.py |
| …狀態在畫面上的名稱。只改看到的字；狀態順序（規劃中→… | …狀態在畫面上的名稱。只改顯示的字；狀態順序（規劃中→… | display_labels.py |
| …狀態在畫面上的名稱。只改看到的字；三個狀態必須依序經… | …狀態在畫面上的名稱。只改顯示的字；三個狀態必須依序經… | display_labels.py |
| …管道在畫面上的名稱。只改看到的字；已存的報價資料不變… | …管道在畫面上的名稱。只改顯示的字；已存的報價資料不變… | display_labels.py |
| …    """業務開發案件刪除申請 → 通知所有最… | …    """商機刪除申請 → 通知所有最… | email_notify.py |
| …rue, title="業務開發案件刪除申請", rows=… | …rue, title="商機刪除申請", rows=… | email_notify.py |
| …請", rows=[("案件名稱", case_na… | …請", rows=[("商機名稱", case_na… | email_notify.py 等 2 處 |
| …  rows = [("案件名稱", case_na… | …  rows = [("商機名稱", case_na… | email_notify.py 等 3 處 |
| …        "業務開發案件刪除申請", "請盡速簽… | …        "商機刪除申請", "請盡速簽… | email_notify.py |
| …isplay} 申請刪除業務開發案件，請最高管理者登入系統簽… | …isplay} 申請刪除商機，請最高管理者登入系統簽… | email_notify.py |
| …request", f"業務開發案件刪除申請：{case_n… | …request", f"商機刪除申請：{case_n… | email_notify.py |
| …    """業務開發案件報價單連結異動申請（改連… | …    """商機報價單連結異動申請（改連… | email_notify.py |
| …rue, title="業務開發案件連結異動申請", row… | …rue, title="商機連結異動申請", row… | email_notify.py |
| …        "業務開發案件報價單／估價單連結異動申… | …        "商機報價單／估價單連結異動申… | email_notify.py |
| …isplay} 申請異動業務開發案件的報價單／估價單連結，請… | …isplay} 申請異動商機的報價單／估價單連結，請… | email_notify.py |
| …request", f"業務開發案件連結異動申請：{case… | …request", f"商機連結異動申請：{case… | email_notify.py |
| …    """業務開發案件洽談中超過 30 天未更… | …    """商機洽談中超過 30 天未更… | email_notify.py |
| …mes, title="業務開發案件逾期未跟進", rows… | …mes, title="商機逾期未跟進", rows… | email_notify.py |
| …進", rows=[("案件名稱", case_na… | …進", rows=[("商機名稱", case_na… | email_notify.py |
| …        "業務開發案件逾期未跟進", f"{d… | …        "商機逾期未跟進", f"{d… | email_notify.py |
| …        [("案件名稱", case_na… | …        [("商機名稱", case_na… | email_notify.py 等 3 處 |
| …    intro=f"案件「{case_name}… | …    intro=f"商機「{case_name}… | email_notify.py 等 2 處 |
| …e_stale", f"業務開發案件逾期提醒：{case_n… | …e_stale", f"商機逾期提醒：{case_n… | email_notify.py |
| …    """業務開發案件指派 → 通知被指派人（… | …    """商機指派 → 通知被指派人（… | email_notify.py |
| …me], title="業務開發案件指派", rows=[(… | …me], title="商機指派", rows=[(… | email_notify.py |
| …派", rows=[("案件名稱", case_na… | …派", rows=[("商機名稱", case_na… | email_notify.py |
| …        "業務開發案件指派通知", "請於期限… | …        "商機指派通知", "請於期限… | email_notify.py |
| …or '管理員'} 已將業務開發案件「{case_name}… | …or '管理員'} 已將商機「{case_name}… | email_notify.py |
| …ssigned", f"業務開發案件指派通知：{case_n… | …ssigned", f"商機指派通知：{case_n… | email_notify.py |
| …    """業務開發案件回覆期限已過、被指派人自… | …    """商機回覆期限已過、被指派人自… | email_notify.py |
| …mes, title="業務開發案件回覆期限已過", row… | …mes, title="商機回覆期限已過", row… | email_notify.py |
| …過", rows=[("案件名稱", case_na… | …過", rows=[("商機名稱", case_na… | email_notify.py |
| …        "業務開發案件回覆期限已過", f"逾… | …        "商機回覆期限已過", f"逾… | email_notify.py |
| …overdue", f"業務開發案件回覆期限已過：{case… | …overdue", f"商機回覆期限已過：{case… | email_notify.py |
| …示", rows=[("案件名稱", case_na… | …示", rows=[("商機名稱", case_na… | email_notify.py |
| … or '管理員'} 對業務開發案件「{case_name}… | … or '管理員'} 對商機「{case_name}… | email_notify.py |
| …由專屬事件負責（例如指派案件＝`dev_case_a… | …由專屬事件負責（例如指派商機＝`dev_case_a… | email_notify.py |
| …  "<br><br>修好並看到下一次回報成功後，請到 … | …  "<br><br>修復並確認下一次回報成功後，請到 … | email_notify.py |
| …hy": "報價單是客戶第一眼看到的內容：抬頭、條款與收款… | …hy": "報價單是客戶最先接觸的內容：抬頭、條款與收款… | getting_started.py |
| …il、所屬部門）", "每個部門的主管是誰"],… | …il、所屬部門）", "各部門主管設定"],… | getting_started.py |
| …onverted", "業務開發案件轉建報價單／估價單", … | …onverted", "商機轉建報價單／估價單", … | google_calendar.py |
| …", "業務開發", "業務開發案件轉建為報價單／估價單當天… | …", "業務開發", "商機轉建為報價單／估價單當天… | google_calendar.py |
| …tale",     "業務開發案件停滯提醒",   "業務… | …tale",     "商機停滯提醒",   "業務… | google_calendar.py |
| …pdate",    "業務開發案件更新",       "… | …pdate",    "商機更新",       "… | google_calendar.py |
| …增開發（拜訪）紀錄；同一案件同一天合併為一個「○○案… | …增開發（拜訪）紀錄；同一商機同一天合併為一個「○○商… | google_calendar.py |
| …件同一天合併為一個「○○案件更新」事件", Fals… | …機同一天合併為一個「○○商機更新」事件", Fals… | google_calendar.py |
| …DT.relabel("業務開發案件轉建報價單 — {cas… | …DT.relabel("商機轉建報價單 — {cas… | google_calendar.py |
| …DT.relabel("業務開發案件「{case}」已轉建為… | …DT.relabel("商機「{case}」已轉建為… | google_calendar.py |
| …          f"業務開發案件停滯提醒 — {case… | …          f"商機停滯提醒 — {case… | google_calendar.py |
| …          f"業務開發案件「{case_name}… | …          f"商機「{case_name}… | google_calendar.py |
| …formal": ["今天沒有需要您處理的事項。", "目前沒有待辦事… | …formal": ["今日待辦事項為 0 件。", "目前待辦事項為… | greeting_phrases.py |
| …處理的事項。", "目前沒有待辦事項。"],… | …為 0 件。", "目前待辦事項為零，可安排其他工作。"],… | greeting_phrases.py |
| … 發會耗額度，額度滿時也發不出去；維持 Email",… | … 發會耗額度，額度滿時也無法發送；維持 Email",… | line_catalog.py |
| …: {"name": "業務開發案件被取消指派（前任負責人）… | …: {"name": "商機被取消指派（前任負責人）… | line_catalog.py |
| …: {"name": "業務開發案件回覆期限被調整（被指派人… | …: {"name": "商機回覆期限被調整（被指派人… | line_catalog.py |
| …e": "業務開發：新增案件", "group": … | …e": "業務開發：新增商機", "group": … | line_catalog.py |
| …ame": "業務開發：案件狀態（階段）變更", "… | …ame": "業務開發：商機狀態（階段）變更", "… | line_catalog.py |
| …ame": "業務開發：案件進度回報（量大）", "… | …ame": "業務開發：商機進度回報（量大）", "… | line_catalog.py |
| …ame": "業務開發：案件轉建報價單／估價單", … | …ame": "業務開發：商機轉建報價單／估價單", … | line_catalog.py |
| …_created": "案件相關人員（業務負責人與主… | …_created": "商機相關人員（業務負責人與主… | line_catalog.py |
| …e_status": "案件相關人員（業務負責人與主… | …e_status": "商機相關人員（業務負責人與主… | line_catalog.py |
| …progress": "案件相關人員（業務負責人與主… | …progress": "商機相關人員（業務負責人與主… | line_catalog.py |
| …t_logged": "案件相關人員（業務負責人與主… | …t_logged": "商機相關人員（業務負責人與主… | line_catalog.py |
| …approved": "案件相關人員（業務負責人與主… | …approved": "商機相關人員（業務負責人與主… | line_catalog.py |
| …onverted": "案件相關人員（業務負責人與主… | …onverted": "商機相關人員（業務負責人與主… | line_catalog.py |
| …eError("對外網址只能是 https://… | …eError("對外網址格式不正確：只能是 https://… | line_notify.py |
| … https://網域（可含埠號 1～65535… | … https://網域（例如 https://erp.example.com，可含埠號 1～65535… | line_notify.py |
| …，不可含路徑、查詢或帳號")… | …，不可含路徑、查詢或帳號，也不能用 http://")… | line_notify.py |
| …, "error": "尚未設定 channel acces… | …, "error": "還沒有儲存 Channel acces… | line_notify.py |
| …access token"}… | …access token，無法驗證。請先貼上 token 並按「儲存 LINE 設定」，再按驗證"}… | line_notify.py |
| …, "error": "channel acces… | …, "error": "已儲存的 Channel acces… | line_notify.py |
| …ken 格式不正確（只能是英數與 + / = . … | …ken 格式不正確（只能有英數與 + / = . … | line_notify.py |
| …-，20～512 字元），請重新貼上"}… | …-，20～512 字元）。請重新貼上正確的 token 並儲存"}… | line_notify.py |
| …, "error": "token 無效或已過期（LINE 回 %s）" % status}… | …, "error": "LINE 拒絕了這個 token（回應 %s）：token 可能貼錯、已被重新發行或已撤銷。請到 LINE Developers → Messaging API 分頁重新發行 token，貼上並儲存後再驗證" % status}… | line_notify.py |
| …r": "LINE 回應 %s" % status}… | …r": "LINE 回應了非預期的狀態 %s，不是 token 的問題。可能是 LINE 暫時異常，請稍後再試；持續發生請通知管理員" % status}… | line_notify.py |
| …, "error": "連不到 LINE（%s）… | …, "error": "這台主機連不到 LINE（%s）… | line_notify.py |
| …連不到 LINE（%s）" % type(exc… | …連不到 LINE（%s）。請確認主機可以連外網，防火牆或 Proxy 有放行 api.line.me，稍後再試" % type(exc… | line_notify.py |
| …rror("額度告警門檻必須是 1～%d 個 1～10… | …rror("額度告警門檻不正確：請填 1～%d 個 1～10… | line_quota.py |
| …1～100 的整數百分比（不可重複）" % MAX_THRE… | …1～100 的整數百分比，不可重複，例如 80,100" % MAX_THRE… | line_quota.py |
| …預設欄位內（排序欄位必須看得到）" % (list_i… | …預設欄位內（排序欄位必須為顯示中的欄位）" % (list_i… | list_catalog.py |
| …g.N.gz`、`app.log.N.gz`、舊… | …g.N.gz`、`app.log.N.gz`、`request_timing.log.N.gz`、舊… | log_setup.py |
| …nder", "簽核逾期催辦", _A, "supe… | …nder", "簽核逾期提醒", _A, "supe… | mail_types.py |
| …_request", "業務開發案件刪除申請", _A, "… | …_request", "商機刪除申請", _A, "… | mail_types.py |
| …         "案件在核准或駁回之前維持待刪… | …         "商機在核准或駁回之前維持待刪… | mail_types.py |
| …_request", "業務開發案件連結異動申請", _A,… | …_request", "商機連結異動申請", _A,… | mail_types.py |
| …         "案件與報價單／估價單的連結在… | …         "商機與報價單／估價單的連結在… | mail_types.py |
| …se_stale", "業務開發案件逾期未跟進", _B, … | …se_stale", "商機逾期未跟進", _B, … | mail_types.py |
| …         "業務開發案件已超過規定天數沒有新的開… | …         "商機已超過規定天數沒有新的開… | mail_types.py |
| …assigned", "業務開發案件指派", _B, "no… | …assigned", "商機指派", _B, "no… | mail_types.py |
| … "被指派人尚未留意前，案件可能逾期沒有人跟進。",… | … "被指派人尚未留意前，商機可能逾期沒有人跟進。",… | mail_types.py |
| …。", "請登入系統查看案件內容，於回覆期限前更新進… | …。", "請登入系統查看商機內容，於回覆期限前更新進… | mail_types.py |
| …_overdue", "業務開發案件回覆期限已過未回報", … | …_overdue", "商機回覆期限已過未回報", … | mail_types.py |
| …回覆期限前沒有回報進度，案件可能無人跟進。", "請… | …回覆期限前沒有回報進度，商機可能無人跟進。", "請… | mail_types.py |
| … → 備份與監控」頁可以看到每種備份最近的結果與硬碟… | … → 備份與監控」頁可以查看每種備份最近的結果與硬碟… | mail_types.py |
| …nder", "簽核逾期催辦提醒（工作日 1/3/5… | …nder", "簽核逾期提醒（工作日 1/3/5… | notification_prefs.py |
| …ale",      "業務開發案件逾期未跟進"),… | …ale",      "商機逾期未跟進"),… | notification_prefs.py |
| …signed",   "業務開發案件指派通知"),… | …signed",   "商機指派通知"),… | notification_prefs.py |
| …_overdue", "業務開發案件回覆期限已過未回報（每個… | …_overdue", "商機回覆期限已過未回報（每個… | notification_prefs.py |
| …回覆期限已過未回報（每個案件、每個期限只寄一次）")… | …回覆期限已過未回報（每個商機、每個期限只寄一次）")… | notification_prefs.py |
| …_request", "業務開發案件刪除申請"),… | …_request", "商機刪除申請"),… | notification_prefs.py |
| …_request", "業務開發案件連結異動申請"),… | …_request", "商機連結異動申請"),… | notification_prefs.py |
| …else "未檢查：試跑只看人數與文字",… | …else "未檢查：試跑僅顯示人數與文字",… | notify_actions.py |
| …  "title": "目前沒有人擔任「財務」職務",… | …  "title": "尚無人擔任「財務」職務",… | org_gaps.py |
| …", "今天日期", "打開表單的那一天。", "2… | …", "今天日期", "開啟表單的那一天。", "2… | prefill_sources.py |
| …現在的日期與時間", "打開表單的那一刻（欄位要設成… | …現在的日期與時間", "開啟表單的那一刻（欄位要設成… | prefill_sources.py |
| …", label="本機備份保留天數", help="本機電… | …", label="本機資料庫備份保留天數", when="這台電腦的硬碟快滿，或想保留更久以前的本機備份時。", help="本機電… | settings_groups.py |
| …端每日備份保留天數", help="近期誤刪、誤… | …端每日備份保留天數", when="想要能回到更久以前的每日還原點，或雲端空間吃緊時。", help="近期誤刪、誤… | settings_groups.py |
| …", label="雲端週備份保留天數", he… | …", label="雲端每週備份保留天數", wh… | settings_groups.py |
| …l="雲端週備份保留天數", help="每日備… | …="雲端每週備份保留天數", when="中期還原點不夠用，或要縮減雲端占用時（在「進階」）。", help="每日備… | settings_groups.py |
| …", label="雲端月備份保留天數（0＝永久… | …", label="雲端每月備份保留天數（可選永久… | settings_groups.py |
| …="雲端月備份保留天數（0＝永久）",… | …"雲端每月備份保留天數（可選永久）", when="稽核或法規要求保存更久，或決定不再永久保留月備份時。",… | settings_groups.py |
| …理）", label="更新前快照保留份數",… | …理）", label="系統更新前自動備份保留份數", when="更新失敗曾退不回去，或更新頻繁導致備份占用過多儲存空間時。",… | settings_groups.py |
| …el="稽核紀錄保留天數（至少 365）",… | …el="稽核紀錄保留天數", when="法規或稽核對稽核紀錄的保存年限有要求時（預設約 5 年）。",… | settings_groups.py |
| …"站內通知保留天數", help="不論已讀或未… | …"站內通知保留天數", when="同仁覺得通知清單太長，或需要更久之前的通知可回頭看時。", help="不論已讀或未… | settings_groups.py |
| …"操作軌跡保留天數", help="用來回頭查「… | …"操作軌跡保留天數", when="要追查誰在什麼時候做過什麼、需要更久的軌跡，或儲存空間不足而需要縮減時。", help="用來回頭查「… | settings_groups.py |
| …", label="系統日誌保留天數",… | …", label="系統運作日誌保留天數", whe… | settings_groups.py |
| …="系統日誌保留天數",… | …系統運作日誌保留天數", when="出問題要追查超過一個月前的事件，或日誌占用過多儲存空間時。",… | settings_groups.py |
| …？", label="單檔大小上限", help="超過的… | …？", label="單一檔案最大幾 MB", when="同仁常反映無法上傳檔案，或儲存空間與備份空間不足時。", help="超過的… | settings_groups.py |
| …案？", label="支出申請每張單據附件數上限", help="包含正… | …案？", label="一張支出申請最多附幾個檔案", when="同仁常反映無法上傳檔案，或儲存空間與備份空間不足時。", help="包含正… | settings_groups.py |
| …el="支出申請一次送出合計上限", help="一次上… | …el="支出申請一次送出的檔案合計上限（MB）", when="同仁常反映無法上傳檔案，或儲存空間與備份空間不足時。", help="一次上… | settings_groups.py |
| …目？", label="沒有權限的項目",… | …目？", label="系統中心的無權限項目", when="不希望沒有權限的同仁知道系統裡有哪些管理功能，或想讓他們看到「需要什麼權限」時。",… | settings_groups.py |
| …lp="預設隱藏：每個人只看到自己能用的項目。也可以改… | …lp="預設隱藏：每個人僅顯示自己能用的項目。也可以改… | settings_groups.py |
| …。改成『顯示為灰色』時，沒有權限的人會看到有哪些管理項目的名稱，但無法… | …。改成『顯示為灰色』時，畫面會列出這些管理項目的名稱，但沒有… | settings_groups.py |
| …有哪些管理項目的名稱，但無法開啟。",… | …出這些管理項目的名稱，但沒有權限的人無法開啟。",… | settings_groups.py |
| …藏（建議）", "每個人只看到自己能用的項目；沒有權限… | …藏（建議）", "每個人僅顯示自己能用的項目；沒有權限… | settings_groups.py |
| …的項目；沒有權限的人完全看不到其他項目。"),… | …的項目；沒有權限的人完全不顯示其他項目。"),… | settings_groups.py |
| …為灰色並說明原因", "沒有權限的人會看到項目名稱與『需要什麼權限… | …為灰色並說明原因", "畫面會列出項目名稱與『需要什麼權限… | settings_groups.py |
| …稱與『需要什麼權限』，但無法開啟。")]),… | …稱與『需要什麼權限』，但沒有權限的人無法開啟。")]),… | settings_groups.py |
| …    help="客戶看到的報價單，在尚未選定方案… | …    help="客戶所見的報價單，在尚未選定方案… | settings_groups.py |
| …字（存檔時會記下）。客戶看得到這段文字。",… | …字（存檔時會記下）。客戶可檢視這段文字。",… | settings_groups.py |
| …價單沿用當時的句子。客戶看得到這句話。",… | …價單沿用當時的句子。客戶可檢視這句話。",… | settings_groups.py |
| …響內部成本比較畫面（客戶看不到）。超過的組合只顯示總數… | …響內部成本比較畫面（客戶無法檢視）。超過的組合只顯示總數… | settings_groups.py |
| …影響任何金額、列印或客戶看到的內容。"),… | …影響任何金額、列印或客戶所見的內容。",… | settings_groups.py |
| …ext="【高影響】選『只看計入金額的品項』時，未被… | …ext="【高影響】選『僅檢查計入金額的品項』時，未被… | settings_groups.py |
| …       (2, "只看計入金額的品項" + _… | …       (2, "僅檢查計入金額的品項" + _… | settings_groups.py |
| …不再列入審核原因。")]),… | …不再列入審核原因。")],… | settings_groups.py |
| …）？", label="誰可以認列採購單",… | …）？", label="採購單認列授權對象",… | settings_groups.py |
| …成？", label="檔名組成",… | …成？", label="下載檔名組成方式", when="同仁反映下載的檔案名稱不易查找，或想把案件編號、客戶放進檔名時。",… | settings_groups.py |
| …文件類型＋單號", "只看得出是什麼文件與單號，看不出… | …文件類型＋單號", "只可辨識是什麼文件與單號，無從辨… | settings_groups.py |
| …看得出是什麼文件與單號，看不出屬於哪個案件。"),… | …可辨識是什麼文件與單號，無從辨識屬於哪個案件。"),… | settings_groups.py |
| …開？", label="分隔符號", help="只影響… | …開？", label="檔名各部分之間的符號", when="檔名在別的系統或雲端硬碟裡顯示不順（例如空白造成問題）時。", help="只影響… | settings_groups.py |
| …稱？", label="案件名用哪個名稱",… | …稱？", label="檔名中的案件名來源", when="檔名裡的案件名太長，或想用客戶名稱方便辨識時。",… | settings_groups.py |
| …得到該案件的人才會在檔名看到名稱。改成含客戶名稱後，… | …得到該案件的人才會在檔名顯示名稱。改成含客戶名稱後，… | settings_groups.py |
| …沒有案件權限者的檔名",… | …沒有案件權限者的檔名", when="擔心沒有案件權限的人（例如出納）從檔名看到案件或客戶資訊時。",… | settings_groups.py |
| …這樣財務、出納等經手人仍看得出是哪個案件，但看不到案件… | …這樣財務、出納等經手人仍可辨識是哪個案件，但無法檢視案… | settings_groups.py |
| …人仍看得出是哪個案件，但看不到案件名稱。",… | …人仍可辨識是哪個案件，但無法檢視案件名稱。",… | settings_groups.py |
| …件名」後，這些人會在檔名看到案件名稱，等於放寬了案件… | …件名」後，這些人會在檔名顯示案件名稱，等於放寬了案件… | settings_groups.py |
| …有案件權限的人也會在檔名看到案件名稱，案件名稱可能含… | …有案件權限的人也會在檔名顯示案件名稱，案件名稱可能含… | settings_groups.py |
| …略案件名（建議）", "看得出是哪個案件，但看不到案件… | …略案件名（建議）", "可辨識是哪個案件，但無法檢視案… | settings_groups.py |
| … "看得出是哪個案件，但看不到案件名稱。"),… | … "可辨識是哪個案件，但無法檢視案件名稱。"),… | settings_groups.py |
| …, "顯示案件名", "沒有案件權限的人也會看到… | …, "顯示案件名", "檔名會含案件名稱，沒有案件權限的人也可檢視… | settings_groups.py |
| …, "沒有案件權限的人也會看到案件名稱。")]),… | …名稱，沒有案件權限的人也可檢視。")]),… | settings_groups.py |
| …label="勞報單檔名顯示承攬人姓名",… | …label="勞報單檔名是否寫出承攬人姓名", when… | settings_groups.py |
| …單檔名顯示承攬人姓名",… | …名是否寫出承攬人姓名", when="勞報單檔案會外傳或存雲端，擔心檔名洩漏承攬人姓名時。",… | settings_groups.py |
| …字？", label="案件名最多字數", help="太長的… | …字？", label="檔名案件名字數上限", when="檔名太長被截斷，或在手機與雲端硬碟顯示不完整時。", help="太長的… | settings_groups.py |
| … label="檔名總長上限", help="另外受… | … label="檔名總長度上限", when="存到或同步到有路徑長度限制的地方（雲端硬碟、舊系統）出錯時。", help="另外受… | settings_groups.py |
| …, label="檔名加日期", help="預設不… | …, label="檔名加上日期", when="同一份文件常下載多次，想從檔名看出是哪一天的版本時。", help="預設不… | settings_groups.py |
| …字？", label="文件類型用語：報價單", help="1～1… | …字？", label="檔名用語：報價單", when="公司習慣不叫「報價單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：報價單存檔版本",… | …字？", label="檔名用語：報價單存檔版本",… | settings_groups.py |
| …類型用語：報價單存檔版本", help="1～1… | …檔名用語：報價單存檔版本", when="公司習慣不叫「報價單存檔版本」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …件類型用語：估價單", help="1～10 個… | …件類型用語：估價單", when="公司習慣不叫「估價單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～10 個… | settings_groups.py |
| …語：估價單存檔版本", help="1～10 個… | …語：估價單存檔版本", when="公司習慣不叫「估價單存檔版本」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～10 個… | settings_groups.py |
| …字？", label="文件類型用語：結案報表", he… | …字？", label="檔名用語：結案報表", wh… | settings_groups.py |
| …"文件類型用語：結案報表", help="1～1… | …l="檔名用語：結案報表", when="公司習慣不叫「結案報表」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：專案執行報告", … | …字？", label="檔名用語：專案執行報告", … | settings_groups.py |
| …件類型用語：專案執行報告", help="1～1… | …"檔名用語：專案執行報告", when="公司習慣不叫「專案執行報告」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：完工單", help="1～1… | …字？", label="檔名用語：完工單", when="公司習慣不叫「完工單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：費用單", help="1～1… | …字？", label="檔名用語：費用單", when="公司習慣不叫「費用單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：出貨單", help="1～1… | …字？", label="檔名用語：出貨單", when="公司習慣不叫「出貨單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：請款單", help="1～1… | …字？", label="檔名用語：請款單", when="公司習慣不叫「請款單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：開票申請", he… | …字？", label="檔名用語：開票申請", wh… | settings_groups.py |
| …"文件類型用語：開票申請", help="1～1… | …l="檔名用語：開票申請", when="公司習慣不叫「開票申請」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：承攬商傳票", h… | …字？", label="檔名用語：承攬商傳票", w… | settings_groups.py |
| …文件類型用語：承攬商傳票", help="1～1… | …="檔名用語：承攬商傳票", when="公司習慣不叫「承攬商傳票」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：勞報單", help="1～1… | …字？", label="檔名用語：勞報單", when="公司習慣不叫「勞報單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：獎金分配單", h… | …字？", label="檔名用語：獎金分配單", w… | settings_groups.py |
| …文件類型用語：獎金分配單", help="1～1… | …="檔名用語：獎金分配單", when="公司習慣不叫「獎金分配單」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …字？", label="文件類型用語：傳票", help="1～1… | …字？", label="檔名用語：傳票", when="公司習慣不叫「傳票」，想改成貴公司習慣的說法時（檔名會跟著變）。", help="1～1… | settings_groups.py |
| …麼組成、沒有案件權限的人看到什麼。檔名永遠不含金額。… | …麼組成、沒有案件權限的人可檢視什麼。檔名永遠不含金額。… | settings_groups.py |
| …響存檔、送審與審核；只有看得到成本與毛利的人會看到。立… | …響存檔、送審與審核；只有可檢視成本與毛利的人才會顯示。… | settings_groups.py |
| …只有看得到成本與毛利的人會看到。立即生效。"),… | …只有可檢視成本與毛利的人才會顯示。立即生效。",… | settings_groups.py |
| …的人會看到。立即生效。"),… | …人才會顯示。立即生效。",… | settings_groups.py |
| …；不改任何金額，也不改誰看得到這份報表。立即生效。",… | …；不改任何金額，也不改誰可檢視這份報表。立即生效。",… | settings_groups.py |
| …放自訂狀態名稱與顏色",… | …放自訂狀態名稱與顏色", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …mpact="只改畫面上看到的字與色，不改任何狀態值… | …mpact="只改畫面上顯示的字與色，不改任何狀態值… | settings_groups.py |
| …放自訂數字與日期顯示",… | …放自訂數字與日期顯示", when="公司習慣的數字、日期寫法和預設不同時（例如不要千分位、要顯示小數）。",… | settings_groups.py |
| …號？", label="千分位",… | …號？", label="數字加千分位逗號", when="公司習慣的數字、日期寫法和預設不同時（例如不要千分位、要顯示小數）。",… | settings_groups.py |
| …數？", label="小數位數",… | …數？", label="金額顯示幾位小數", when="公司習慣的數字、日期寫法和預設不同時（例如不要千分位、要顯示小數）。",… | settings_groups.py |
| …abel="日期寫法",… | …abel="日期寫法", when="公司習慣的數字、日期寫法和預設不同時（例如不要千分位、要顯示小數）。",… | settings_groups.py |
| …覽？", label="版本帳本與影響預覽",… | …覽？", label="改版前先預覽，並保留歷史版本", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …label="版面發布前強制預覽",… | …label="版面發布前一定要先看預覽", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …bel="自訂欄位發布前強制預覽",… | …bel="自訂欄位發布前一定要先看預覽", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …bel="自訂按鈕發布前強制預覽",… | …bel="自訂按鈕發布前一定要先看預覽", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …覽？", label="輸出版型發布前強制預覽",… | …覽？", label="列印版型發布前一定要先看預覽", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …覽？", label="規則發布前強制預覽",… | …覽？", label="提醒規則發布前一定要先看預覽", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …", label="開放標示規則",… | …", label="開放「條件成立就標紅」提醒規則", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …阻擋存檔，也不會發通知。看不到來源欄位的人（例如沒有成… | …阻擋存檔，也不會發通知。無法檢視來源欄位的人（例如沒有成… | settings_groups.py |
| …abel="專案毛利提醒改由規則管理",… | …abel="專案毛利提醒門檻改由提醒規則管理", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …不阻擋存檔、送審）；只有看得到成本與毛利的人會看到。需… | …不阻擋存檔、送審）；只有可檢視成本與毛利的人才會顯示。… | settings_groups.py |
| …只有看得到成本與毛利的人會看到。需先開啟『開放標示規則… | …只有可檢視成本與毛利的人才會顯示。需先開啟『開放標示規則… | settings_groups.py |
| … label="開放調整選單名稱與分組",… | … label="開放調整側欄選單名稱與分組", wh… | settings_groups.py |
| …放調整選單名稱與分組",… | …整側欄選單名稱與分組", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …出現，改名與換群組也不會讓人多看到任何東西。關閉後，已發布的改名與… | …出現，改名與換群組也不會擴大任何人的檢視範圍。關閉後，已發布的改名與… | settings_groups.py |
| …", label="開放內建畫面的自訂欄位",… | …", label="開放自訂欄位（案件資訊、供應商）", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …後所有內部人員在對應畫面看得到並可填寫。")]),… | …後所有內部人員在對應畫面可檢視並可填寫。")]),… | settings_groups.py |
| …", label="開放報價單自訂欄位",… | …", label="開放自訂欄位（報價單）", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …，填錯或不該公開的內容會被客戶看到。",… | …，填錯或不該公開的內容會呈現給客戶。",… | settings_groups.py |
| …上？", label="報價單自訂欄位可印在報價單上",… | …上？", label="自訂欄位印在報價單上（客戶可檢視）", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …載那張請款單或憑據的人都會看到，即使他的角色沒有權限開… | …載那張請款單或憑據的人都可檢視，即使他的角色沒有權限開… | settings_groups.py |
| …上？", label="報價單自訂欄位可附在財務文件上",… | …上？", label="自訂欄位附在請款單與開票憑據上", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …下載該請款單或憑據的人都看得到這些內容，就算他的角色不… | …下載該請款單或憑據的人都可檢視這些內容，就算他的角色不… | settings_groups.py |
| …abel="開放自訂按鈕",… | …abel="開放自訂按鈕（供應商管理頁）", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …鈕只是入口，不會讓任何人看到或匯出其原本無權檢視或匯… | …鈕只是入口，不會讓任何人檢視或匯出其原本無權檢視或匯… | settings_groups.py |
| …按鈕才會出現，而且每個人只看得到自己有權限的那幾顆。按鈕… | …按鈕才會出現，而且每個人僅顯示自己有權限的那幾顆。按鈕… | settings_groups.py |
| …el="開放自訂附件種類",… | …el="開放自訂附件種類與存放位置", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …abel="開放自訂匯出",… | …abel="開放自訂匯出欄位與標題", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| … label="開放自訂選項清單",… | … label="開放自訂下拉選單選項", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …", label="開放清單個人偏好",… | …", label="開放每個人自訂清單（欄位、排序、每頁筆數）", when="同仁想自己決定清單看哪些欄位、開頁停在哪個頁籤時。",… | settings_groups.py |
| …ct="只影響每個人自己看到的清單外觀：資料與權限不… | …ct="只影響每個人自己的清單外觀：資料與權限不… | settings_groups.py |
| …現與統計：天數調短，報表看到的預警會變少（設備與保固… | …現與統計：天數調短，報表顯示的預警會變少（設備與保固… | settings_groups.py |
| …才生效，調長立即生效。"),… | …才生效，調長立即生效。",… | settings_groups.py |
| …", label="密碼最短長度",… | …", label="密碼至少要幾碼", when="公司資安規範要求更長的密碼、或要縮短登入有效期時。",… | settings_groups.py |
| …法得知現有密碼多長，所以看不到有多少人低於新的長度。調… | …法得知現有密碼多長，所以無法得知有多少人低於新的長度。調… | settings_groups.py |
| …", label="登入有效天數",… | …", label="登入後多久要重新登入", when="公司資安規範要求更長的密碼、或要縮短登入有效期時。",… | settings_groups.py |
| …帳號密碼外洩時，外人就能看到客戶、報價與財務資料。"… | …帳號密碼外洩時，外人就能檢視客戶、報價與財務資料。"… | settings_groups.py |
| …」？", label="外網強制兩步驟驗證（總開關）… | …」？", label="從外網登入時強制兩步驟驗證（總開關）… | settings_groups.py |
| …兩步驟驗證（總開關）",… | …兩步驟驗證（總開關）", when="想讓外網登入更安全，或發現有人從外面試密碼時，先確認這個總開關是開的。",… | settings_groups.py |
| …號？", label="帳號鎖定的失敗次數",… | …號？", label="密碼輸錯幾次就鎖住帳號", when="有人報告帳號被亂試密碼，或同仁常因手滑被鎖住時，調整容忍次數。",… | settings_groups.py |
| …計？", label="帳號鎖定的計算時間窗",… | …計？", label="輸錯次數的計算時間（分鐘）", when="想讓「輸錯幾次」的計算更嚴（拉長時間）或更寬鬆（縮短時間）時。",… | settings_groups.py |
| …, label="帳號鎖定的時間",… | …, label="帳號鎖住多久", when="被鎖住的同仁抱怨等太久，或擔心有人持續試密碼時，調整鎖定長度。",… | settings_groups.py |
| …", label="帳號鎖定的範圍",… | …", label="帳號被鎖住時，公司內網也擋嗎", when="有人故意在內網輸錯密碼把別人鎖住，或想連內網一起擋時。",… | settings_groups.py |
| …隔）", label="外網網域",… | …隔）", label="視為外網的網域", when="公司換了對外網域、或外網連進來的網址變了時（通常由安裝人員設定）。",… | settings_groups.py |
| …網？", label="本機直連算內網",… | …網？", label="在伺服器本機開網頁算公司內網嗎", when="在伺服器本機開網頁測試，卻被當成外網要求驗證時（一般不用改）。",… | settings_groups.py |
| …隔）", label="內網網段",… | …隔）", label="公司內網的網段", when="公司換了網路、或新增分公司網段時；請先向網路管理者確認。",… | settings_groups.py |
| … label="開放自訂通知用語",… | … label="開放自訂簽核通知文字", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| … label="開放自訂階段樣板",… | … label="開放自訂案件階段樣板", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …", label="開放建立自訂模組",… | …", label="開放自行建立新表單（自訂模組）", when="公司想自己調整畫面、欄位、通知文字，又不想每次都洽原開發廠商處理；平常不需要，預設全部關閉。",… | settings_groups.py |
| …麼？", label="系統標語（1～24 個字）",… | …麼？", label="首頁小標語", when="想讓首頁小標語換成公司自己的系統名稱或口號時。",… | settings_groups_brand.py |
| …氣。", label="問候語風格",… | …氣。", label="首頁問候語的口氣", when="覺得問候語太吵、或想換成更正式或更輕鬆的口氣時。",… | settings_groups_brand.py |
| …NOTE = "只改自己看到的清單如何排序、顯示哪些… | …NOTE = "只改自己的清單如何排序、顯示哪些… | settings_groups_list_view.py |
| …ns", "報價單清單：個人可隱藏／調整欄位順序"… | …ns", "報價單清單：每人可隱藏／調整欄位",… | settings_groups_list_view.py |
| …單：個人可隱藏／調整欄位順序",… | …單：每人可隱藏／調整欄位",… | settings_groups_list_view.py |
| …調順序，沒有金額權限的人看到的仍是「—」。"),… | …調順序，沒有金額權限的人仍顯示「—」。"),… | settings_groups_list_view.py |
| …ab", "報價單清單：個人可設預設頁籤",… | …ab", "報價單清單：每人可設預設頁籤",… | settings_groups_list_view.py |
| …ze", "報價單清單：個人可設每頁筆數",… | …ze", "報價單清單：每人可選每頁筆數",… | settings_groups_list_view.py |
| …tab", "案件清單：個人可設預設頁籤",… | …tab", "案件清單：每人可設預設頁籤",… | settings_groups_list_view.py |
| …ize", "案件清單：個人可設每次載入筆數",… | …ize", "案件清單：每人可選每次載入筆數",… | settings_groups_list_view.py |
| …重複的「已成案」頁籤",… | …重複的「已成案」頁籤", when="想要把兩個頁籤分開顯示時，改回「兩個都保留」。",… | settings_groups_list_view.py |
| …      help="目前兩個頁籤查詢內容與筆數完… | …      help="兩個頁籤查詢內容與筆數完… | settings_groups_list_view.py |
| …籤查詢內容與筆數完全相同。選「只留進行中」後，「已成案」頁籤不再顯示；需要先在「自訂畫面版面」開啟案件管理。",… | …籤查詢內容與筆數完全相同，所以預設合併：只顯示「進行中」「已結案」「待精算」。想要分開顯示的公司，可以在這裡改回「兩個都保留」。",… | settings_groups_list_view.py |
| …=[(0, "兩個都保留（預設）", "與目前完全一樣。"), (1, "只留… | …=[(0, "兩個都保留", "分開顯示「進行中」與「已成案」兩個頁籤（內容相同）。"), (1, "只留… | settings_groups_list_view.py |
| …(1, "只留「進行中」", "隱藏重複的「已成… | …(1, "只留「進行中」（預設）", "隱藏重複的「已成… | settings_groups_list_view.py |
| …」？", label="資料過舊提示天數（7～365）",… | …」？", label="旅宿資料多久沒更新就提醒（天）", when="覺得旅宿資料提醒太早或太晚出現時。",… | settings_groups_lodging_freshness.py |
| …新就提示過舊。資料來源與抓取開關不在這裡設定。",… | …新就提示過舊。資料來源與擷取開關不在這裡設定。",… | settings_groups_lodging_freshness.py |
| …有權看的案件；日誌本身誰看得到、誰能改，與現在完全相同… | …有權看的案件；日誌本身誰可檢視、誰能改，與現在完全相同… | settings_groups_onepipe.py |
| …權限、簽核或資料；每個人看得到的案件與單據與目前完全相… | …權限、簽核或資料；每個人可檢視的案件與單據與目前完全相… | settings_groups_onepipe.py |
| …顯示現在算得出來的部分；看得到哪些案件、金額看不看得到… | …顯示現在算得出來的部分；可檢視哪些案件、金額可否檢視，… | settings_groups_onepipe.py |
| …分；看得到哪些案件、金額看不看得到，都跟現在的權限一樣。"… | …分；可檢視哪些案件、金額可否檢視，都跟現在的權限一樣。"… | settings_groups_onepipe.py |
| …權限；沒有金額檢視權的人看不到金額。關閉後入口消失，畫… | …權限；沒有金額檢視權的人無法檢視金額。關閉後入口消失，畫… | settings_groups_onepipe.py |
| …項，但限定：須關聯至自己看得到的案件、只能指派給自己、… | …項，但限定：須關聯至自己可檢視的案件、只能指派給自己、… | settings_groups_onepipe.py |
| …     "事項只有本人看得到（與目前被指派的事項相同… | …     "事項只有本人可檢視（與目前被指派的事項相同… | settings_groups_onepipe.py |
| …上；不改既有事項、不改誰看得到事項。關閉後同仁又不能新… | …上；不改既有事項、不改誰可檢視事項。關閉後同仁又不能新… | settings_groups_onepipe.py |
| …通知持有「採購」模組、且看得到該案件的同仁，請開立請購… | …通知持有「採購」模組、且可檢視該案件的同仁，請開立請購… | settings_groups_onepipe.py |
| …通知持有「庫存」模組、且看得到該案件的同仁，請準備收貨… | …通知持有「庫存」模組、且可檢視該案件的同仁，請準備收貨… | settings_groups_onepipe.py |
| …改任何單據、權限或簽核；看不到案件的人不會收到。關閉後… | …改任何單據、權限或簽核；無法檢視案件的人不會收到。關閉後… | settings_groups_onepipe.py |
| …後，不是管理員的採購同仁會看到供應商名單，並能對自己看… | …後，不是管理員的採購同仁可檢視供應商名單，並能對自己可… | settings_groups_onepipe.py |
| …到供應商名單，並能對自己看得到的案件開請購單；放寬的是… | …視供應商名單，並能對自己可檢視的案件開請購單；放寬的是… | settings_groups_onepipe.py |
| …管理員的同仁，在供應商頁看得到唯讀名單（只有公司名稱、… | …管理員的同仁，在供應商頁可檢視唯讀名單（只有公司名稱、… | settings_groups_onepipe.py |
| …細）；②同仁可以對「自己看得到的案件」建立、修改、送審… | …細）；②同仁可以對「自己可檢視的案件」建立、修改、送審… | settings_groups_onepipe.py |
| …ct="開啟後，採購同仁看得到供應商名單的基本欄位，並… | …ct="開啟後，採購同仁可檢視供應商名單的基本欄位，並… | settings_groups_onepipe.py |
| …看供應商唯讀名單、對自己看得到的案件開請購單（放寬權限… | …看供應商唯讀名單、對自己可檢視的案件開請購單（放寬權限… | settings_groups_onepipe.py |
| …庫存與保固日期，也不改誰看得到案件。關閉後畫面與通知方… | …庫存與保固日期，也不改誰可檢視案件。關閉後畫面與通知方… | settings_groups_onepipe.py |
| …清單一次載入幾筆；不改誰看得到哪些派發、搜尋範圍、金額… | …清單一次載入幾筆；不改誰可檢視哪些派發、搜尋範圍、金額… | settings_groups_payslip_picker.py |
| …清單一次載入幾筆，不改誰看得到哪些派發，也不改任何勞報… | …清單一次載入幾筆，不改誰可檢視哪些派發，也不改任何勞報… | settings_groups_payslip_picker.py |
| …大可能讓清單載入稍慢。"),… | …大可能讓清單載入稍慢。",… | settings_groups_payslip_picker.py |
| …立的估價單的單號；已經開出去的估價單單號不變、仍可正… | …立的估價單的單號；已經開立的估價單單號不變、仍可正… | settings_groups_profit.py |
| …價單的單號。立即生效。"),… | …價單的單號。立即生效。",… | settings_groups_profit.py |
| …報價單 PDF 上，客戶看不到這些條件，之後可能因為條… | …報價單 PDF 上，客戶無法檢視這些條件，之後可能因為條… | settings_groups_q0.py |
| …bel="資源回收筒保留天數（7～365）",… | …bel="資源回收筒保留幾天", when="誤刪單據後來不及找回，或想縮短回收筒占用空間時。",… | settings_groups_recycle_bin.py |
| …」？", label="即將截止天數（1～60）",… | …」？", label="標案幾天內截止算「即將截止」", when="想調整地圖上「即將截止」的標案範圍時。",… | settings_groups_tender_closing.py |
| …將截止」的判斷天數。標案抓取開關與頻率不在這裡設定… | …將截止」的判斷天數。標案擷取開關與頻率不在這裡設定… | settings_groups_tender_closing.py |
| …項。完整明細：變更紀錄（點此開啟）" % (len(… | …項。完整明細：變更紀錄（請按一下開啟）" % (len(… | settings_notify.py |
| …lain': '重大設定要等幾天才生效', 'category… | …lain': '重大設定生效等待期', 'category… | settings_pages.py |
| …lain': '資料保存多久', 'category… | …lain': '資料保存期限', 'category… | settings_pages.py |
| …, 'plain': '刪除的單據保留幾天', 'category… | …, 'plain': '已刪除單據保留天數', 'category… | settings_pages.py |
| …lain': '系統中心是否列出您沒有權限的項目', 'catego… | …lain': '系統中心的無權限項目', 'catego… | settings_pages.py |
| …, 'plain': '誰能把採購單認列到材料卡片', 'category… | …, 'plain': '採購單認列至材料卡片的授權', 'category… | settings_pages.py |
| …plain': '報價單什麼時候要送審', 'category… | …plain': '報價單送審條件', 'category… | settings_pages.py |
| …ain': '案件結案前要先完成什麼', 'category… | …ain': '案件結案前置條件', 'category… | settings_pages.py |
| …plain': '完工單怎麼從報價單帶入', 'category… | …plain': '完工單帶入報價單設定', 'category… | settings_pages.py |
| …'plain': '管銷怎麼分攤', 'category… | …'plain': '管銷分攤方式', 'category… | settings_pages.py |
| … '勞報單「選派發」下拉一次載入幾筆', 'category… | … '勞報單「選派發」下拉選單載入筆數', 'category… | settings_pages.py |
| …lain': '重大設定要等幾天才生效', 'currentN… | …lain': '重大設定生效等待期', 'currentN… | settings_pages.py |
| …lain': '資料保存多久', 'currentN… | …lain': '資料保存期限', 'currentN… | settings_pages.py |
| … {'plain': '刪除的單據保留幾天', 'currentN… | … {'plain': '已刪除單據保留天數', 'currentN… | settings_pages.py |
| …lain': '系統中心是否列出您沒有權限的項目', 'curren… | …lain': '系統中心的無權限項目', 'curren… | settings_pages.py |
| …lain': '下載檔案怎麼命名', 'currentN… | …lain': '下載檔案命名規則', 'currentN… | settings_pages.py |
| …ain': '數字與日期怎麼顯示', 'currentN… | …ain': '數字與日期顯示格式', 'currentN… | settings_pages.py |
| … {'plain': '誰能把採購單認列到材料卡片', 'currentN… | … {'plain': '採購單認列至材料卡片的授權', 'currentN… | settings_pages.py |
| …plain': '報價單什麼時候要送審', 'currentN… | …plain': '報價單送審條件', 'currentN… | settings_pages.py |
| …ain': '案件結案前要先完成什麼', 'currentN… | …ain': '案件結案前置條件', 'currentN… | settings_pages.py |
| …plain': '完工單怎麼從報價單帶入', 'currentN… | …plain': '完工單帶入報價單設定', 'currentN… | settings_pages.py |
| …'plain': '管銷怎麼分攤', 'currentN… | …'plain': '管銷分攤方式', 'currentN… | settings_pages.py |
| … '勞報單「選派發」下拉一次載入幾筆', 'currentN… | … '勞報單「選派發」下拉選單載入筆數', 'currentN… | settings_pages.py |
| …nned": "這項功能還在開發中，尚未開放調整。"… | …nned": "這項功能開發中，尚未開放調整。"… | settings_registry.py |
| …n(409, "這項功能還在開發中，這一版尚未提供，… | …n(409, "這項功能開發中，這一版尚未提供，… | ledger_settings.py |
| …開發中，這一版尚未提供，不能開啟。")… | …開發中，這一版尚未提供，無法開啟。")… | ledger_settings.py |
| …= "請先選一個案件，才看得到它底下可以帶入的憑證。"… | …= "請先選一個案件，才會列出它底下可以帶入的憑證。"… | vouchers.py |
| … = "案件「%s」底下目前沒有可帶入的憑證。" % p… | … = "案件「%s」底下尚無可帶入的憑證。" % p… | vouchers.py |
| …= "請先選一個案件，才看得到它底下的支出項。"… | …= "請先選一個案件，才會列出它底下的支出項。"… | vouchers.py |
| …se "案件「%s」底下目前沒有支出項。" % pick… | …se "案件「%s」底下尚無支出項。" % pick… | vouchers.py |
| …    """業務開發案件停滯（洽談中 30 天無… | …    """商機停滯（洽談中 30 天無… | dashboard.py |
| …reate":  "新增業務開發案件",… | …reate":  "新增商機",… | dashboard.py |
| ….status":  "案件狀態異動",… | ….status":  "商機狀態異動",… | dashboard.py |
| …以未列入；不設日期條件即可看到。")… | …以未列入；不設日期條件即會列入。")… | report_templates.py 等 2 處 |
| …最高管理者與出納；管理員只看到遮罩"… | …最高管理者與出納；管理員僅顯示遮罩"… | cashier.py |
| …refLabel": "看我的案件", "ite… | …refLabel": "查看我的案件", "ite… | dashboard_groups.py |
| …  "empty": "目前沒有進行中的案件"})… | …  "empty": "尚無進行中的案件"})… | dashboard_groups.py |
| …refLabel": "去追款", "items": … | …refLabel": "前往收款追蹤", "items": … | dashboard_groups.py |
| …  "empty": "沒有逾期未收的款項"})… | …  "empty": "尚無逾期未收的款項"})… | dashboard_groups.py |
| … {"label": "第幾張申請", "value": … | … {"label": "申請序號", "value": … | material_payments.py |
| …{ph}) AND dtc.completed_… | …{ph}) AND dt.is_deleted = 0 AND dtc.completed_… | quotations.py |
| …ted_at != ''… | …ted_at != ''   -- 撤回（軟刪）的任務不算動態：撤銷階段勾選後別人不該亮「有新動態」… | quotations.py |
| …ILABLE = "採購・庫存・出貨模組未安裝：沒有出貨單資… | …ILABLE = "採購與庫存模組未安裝：沒有出貨單資… | quotations.py |
| …設備序號未同步庫存：採購・庫存・出貨模組未安裝"… | …設備序號未同步庫存：採購與庫存模組未安裝"… | quotations.py |
| …業務開發模組未安裝：若有業務開發案件轉建自這張報價單，它們的… | …業務開發模組未安裝：若有商機轉建自這張報價單，它們的… | quotations.py |
| …    """無案件單據的佇列項目補欄位（W1 A2-0 佇列契… | …    - 無案件（W1 A2-0 佇列契… | quotations.py |
| …`typeLabel`、各動作 URL（哨兵路徑… | …`typeLabel`、`docCode`、各動作 URL（哨兵路徑… | quotations.py |
| …L（哨兵路徑 `-`）。有案件 ⇒ 空。"""… | …L（哨兵路徑 `-`）。… | quotations.py |
| …uest/reject"),… | …uest/reject", change=True, suffix="改"),… | quotations.py |
| …ion(400, "內容沒有任何變動；若要維持原內容… | …ion(400, "內容無任何變動；若要維持原內容… | quotations.py |
| … LABEL = "案件"… | … LABEL = "案件管理"… | attachments.py |
| …module": "案件"},… | …module": "案件管理"},… | attachments.py 等 7 處 |
| …  "call": ("去送材料申請", "case… | …  "call": ("送出材料申請", "case… | material_flow.py |
| …"arrive": ("去確認到貨", "case… | …"arrive": ("確認到貨", "case… | material_flow.py |
| …  "ship": ("去開出貨單", "case-… | …  "ship": ("開立出貨單", "case-… | material_flow.py |
| …"device": ("去登載設備", "case… | …"device": ("登載設備", "case… | material_flow.py |
| …arranty": ("去填保固起始日", "cas… | …arranty": ("填寫保固起始日", "cas… | material_flow.py |
| …入庫", "na", "目前沒有這個案件的入庫紀錄")… | …入庫", "na", "尚無這個案件的入庫紀錄")… | material_flow.py |
| …入庫", "na", "目前沒有這個案件的序號；已入庫但… | …入庫", "na", "尚無這個案件的序號；已入庫但… | material_flow.py |
| … "name": "案件",… | … "name": "案件管理",… | module.json |
| …m_unlink": "業務開發案件的轉建連結不會自動恢復"… | …m_unlink": "商機的轉建連結不會自動恢復"… | recycle_adapter.py |
| … "notes": ["業務開發案件的轉建連結沒有自動恢復（… | … "notes": ["商機的轉建連結沒有自動恢復（… | recycle_adapter.py |
| …務開發 CRM — 前期案件追蹤 + 開發記錄 (p… | …務開發 CRM — 前期商機追蹤 + 開發記錄 (p… | api.py |
| …sage="無權限存取此業務開發案",… | …sage="無權限存取此商機",… | api.py |
| …    """案件相關人的帳號（LINE … | …    """商機相關人的帳號（LINE … | api.py |
| …access` 的「這個案件誰有權限」同一組人；管理… | …access` 的「這個商機誰有權限」同一組人；管理… | api.py |
| …on 未完成）⇒ 回空，案件清單不能因此 500。"… | …on 未完成）⇒ 回空，商機清單不能因此 500。"… | api.py |
| …    """單筆案件回傳（含目前進度與逾期天… | …    """單筆商機回傳（含目前進度與逾期天… | api.py |
| …含目前進度與逾期天數）。"""… | …含目前進度與逾期天數）。`user`＝呼叫者；沒帶 ⇒ 不回預估金額（fail closed）。"""… | api.py |
| … "業務開發", "新增案件",… | … "業務開發", "新增商機",… | api.py |
| …ption(404, "案件不存在")… | …ption(404, "商機不存在")… | api.py 等 17 處 |
| …403, "無權限查看此案件")… | …403, "無權限查看此商機")… | api.py 等 4 處 |
| …403, "無權限修改此案件")… | …403, "無權限修改此商機")… | api.py 等 3 處 |
| …ption(409, "案件資料已被其他人更新，請重… | …ption(409, "商機資料已被其他人更新，請重… | api.py |
| …"Admin+ 申請刪除案件 → 送交最高管理者審核… | …"Admin+ 申請刪除商機 → 送交最高管理者審核… | api.py |
| …, "僅管理員可申請刪除案件")… | …, "僅管理員可申請刪除商機")… | api.py |
| …tion(409, "此案件已有待審核的刪除申請")… | …tion(409, "此商機已有待審核的刪除申請")… | api.py |
| …tion(409, "此案件無待審核的刪除申請")… | …tion(409, "此商機無待審核的刪除申請")… | api.py 等 2 處 |
| …    """管理員指派業務開發案件給成員，並可設定回覆期限… | …    """管理員指派商機給成員，並可設定回覆期限… | api.py |
| …03, "僅管理員可指派業務開發案件")… | …03, "僅管理員可指派商機")… | api.py |
| …r_display} 將業務開發案件「{row['case_… | …r_display} 將商機「{row['case_… | api.py 等 2 處 |
| …_display} 已將業務開發案件「{row['case_… | …_display} 已將商機「{row['case_… | api.py |
| …) + "，您不再負責此案件。",… | …) + "，您不再負責此商機。",… | api.py |
| …     title="業務開發案件已不由您負責", row… | …     title="商機已不由您負責", row… | api.py |
| …責", rows=[("案件名稱", row["ca… | …責", rows=[("商機名稱", row["ca… | api.py |
| …     title="業務開發案件回覆期限已調整", ro… | …     title="商機回覆期限已調整", ro… | api.py |
| …整", rows=[("案件名稱", row["ca… | …整", rows=[("商機名稱", row["ca… | api.py |
| …("業務開發", "指派案件" if assigne… | …("業務開發", "指派商機" if assigne… | api.py |
| …史（新到舊）。看得到這個案件的人都看得到（含管理員）… | …史（新到舊）。看得到這個商機的人都看得到（含管理員）… | api.py |
| …tion(409, "此案件已連結報價單，如需異動或… | …tion(409, "此商機已連結報價單，如需異動或… | api.py |
| …空即申請「解除連結」——業務案件因報價單被取消等原因需要… | …空即申請「解除連結」——商機因報價單被取消等原因需要… | api.py |
| …tion(400, "此案件尚未連結報價單，請使用「… | …tion(400, "此商機尚未連結報價單，請使用「… | api.py |
| …tion(409, "此案件已有待審核的連結異動申請… | …tion(409, "此商機已有待審核的連結異動申請… | api.py |
| …tion(409, "此案件無待審核的連結異動申請"… | …tion(409, "此商機無待審核的連結異動申請"… | api.py 等 2 處 |
| …清空（解除連結）核准後，案件狀態一併退回「洽談中」—… | …清空（解除連結）核准後，商機狀態一併退回「洽談中」—… | api.py |
| …繼續掛著會誤導其他人以為案件仍有成立中的報價單。""… | …繼續掛著會誤導其他人以為商機仍有成立中的報價單。""… | api.py |
| …    """跨案件每週／每日接洽成效統計：… | …    """跨商機每週／每日接洽成效統計：… | api.py |
| …或被列為業務/規劃人員的案件）。"""… | …或被列為業務/規劃人員的商機）。"""… | api.py |
| …me"] or "未命名案件") for r in … | …me"] or "未命名商機") for r in … | api.py |
| …e_id"], "未命名案件")… | …e_id"], "未命名商機")… | api.py |
| …(403, "無權限在此案件新增記錄")… | …(403, "無權限在此商機新增記錄")… | api.py |
| …    """行事曆「業務開發案件更新」事件的內容（pus… | …    """行事曆「商機更新」事件的內容（pus… | api.py |
| …e 的參數）：標題「○○案件更新」，… | …e 的參數）：標題「○○商機更新」，… | api.py |
| …錄；merge_key＝案件 id ⇒ 同一天的紀錄… | …錄；merge_key＝商機 id ⇒ 同一天的紀錄… | api.py |
| …"{case_name}案件更新" + (f"（{c… | …"{case_name}商機更新" + (f"（{c… | api.py |
| …未完成）⇒ 回空，不能讓案件頁 500。"""… | …未完成）⇒ 回空，不能讓商機頁 500。"""… | api.py |
| …ment` ＋ 看得到此案件。… | …ment` ＋ 看得到此商機。… | api.py |
| …限（或管理員）、看得到此案件，否則 400 並列出名… | …限（或管理員）、看得到此商機，否則 400 並列出名… | api.py |
| …開發記錄不存在或不屬於此案件")… | …開發記錄不存在或不屬於此商機")… | api.py 等 2 處 |
| ….append("%s（看不到此案件）" % name)… | ….append("%s（無法檢視此商機）" % name)… | api.py |
| …       "%s 對業務開發案件「%s」的開發記錄下了批… | …       "%s 對商機「%s」的開發記錄下了批… | api.py |
| …    rows=[("案件名稱", case_ro… | …    rows=[("商機名稱", case_ro… | api.py |
| …     "%s 回覆了業務開發案件「%s」的批示：%s" … | …     "%s 回覆了商機「%s」的批示：%s" … | api.py |
| …覆", rows=[("案件名稱", case_ro… | …覆", rows=[("商機名稱", case_ro… | api.py |
| …    """洽談中案件超過 30 天未更新 →… | …    """洽談中商機超過 30 天未更新 →… | api.py |
| …每 14 天重複提醒直到案件狀態改變或有新開發記錄（… | …每 14 天重複提醒直到商機狀態改變或有新開發記錄（… | api.py |
| …          f"案件「{row['case_… | …          f"商機「{row['case_… | api.py 等 2 處 |
| …後一筆進度都沒寫的洽談中案件 ⇒ 提醒一次（站內＋信… | …後一筆進度都沒寫的洽談中商機 ⇒ 提醒一次（站內＋信… | api.py |
| …入 guard key＝案件＋期限＋被指派人：換人或… | …入 guard key＝商機＋期限＋被指派人：換人或… | api.py |
| …    """暫擱置案件超過 180 天未更新 … | …    """暫擱置商機超過 180 天未更新 … | api.py |
| …→ 自動轉為未成案，避免案件無限期卡在暫擱置、… | …→ 自動轉為未成案，避免商機無限期卡在暫擱置、… | api.py |
| …除 ⇒ 轉建連結指到它的業務開發案件解除連結、退回「洽談中」… | …除 ⇒ 轉建連結指到它的商機解除連結、退回「洽談中」… | api.py |
| …    回傳被解除的案件 `[{"id", "c… | …    回傳被解除的商機 `[{"id", "c… | api.py |
| …ective.py 新增",… | …ective.py 新增；dev_cases.expected_amount／expected_close_date（預估金額、預計成交日）由 migrations/0005_dev_case_expected.py 新增",… | module.json |
| …"desc": "可以對業務開發案件裡的某一筆開發記錄下批示… | …"desc": "可以對商機裡的某一筆開發記錄下批示… | module.json |
| …限者，可對自己有權檢視的案件下批示；批示只有下批示的… | …限者，可對自己有權檢視的商機下批示；批示只有下批示的… | module.json |
| …人、被指定的成員和管理員看得到。被指定的成員仍須有業務… | …人、被指定的成員和管理員可檢視。被指定的成員仍須有業務… | module.json |
| …有業務開發模組權限、而且看得到該案件才能被指定。被指定的成員… | …有業務開發模組權限、而且可檢視該商機才能被指定。被指定的成員… | module.json |
| …{"case": "案件", "supply":… | …{"case": "案件管理", "supply":… | api.py |
| …supply": "採購・庫存・出貨", "arap": "… | …supply": "採購與庫存", "arap": "… | api.py |
| …    """目前設定的科目代號（沒設定 ⇒ 預設值）。讀同一個連線，不另開… | …    登錄表讀不到 ⇒ 退回舊儲存（不用程式預設）。讀同一個連線，不另開… | bonus_vouchers.py |
| …這個角色（或這個人）可以看到勞報單的內容與金額；原本… | …這個角色（或這個人）可以檢視勞報單的內容與金額；原本… | module.json |
| …「勞報單」功能勾選的人也會看得到。",… | …「勞報單」功能勾選的人也可檢視。",… | module.json |
| …eText": "可隨時一鍵復原",… | …eText": "可隨時復原",… | service.py |
| …failed: 稽核紀錄寫不進去，未清除：%s" % e… | …failed: 稽核紀錄無法寫入，未清除：%s" % e… | service.py |
| …}}（沒有紀錄的不列）。"""… | …}}（沒有紀錄的不列）。管理員看完整紀錄；非管理員只看 `{at}`（已告知與日期）。"""… | suppliers.py |
| …"""M03 採購・庫存・出貨的附件目錄提供者（`at… | …"""M03 採購與庫存的附件目錄提供者（`at… | attachments.py |
| …module": "採購・庫存・出貨"},… | …module": "採購與庫存"},… | attachments.py |
| …_module_off`；同列帶庫存序號 ⇒ `ship_link_serial_exclusive`。… | …_module_off`。… | material_link.py |
| …de, qty))]`；同列帶庫存序號 ⇒ LinkError… | …de, qty))]`；形狀不對 ⇒ LinkError… | material_link.py |
| …⇒ LinkError。"""… | …⇒ LinkError。並存列的序號筆數不得多於連結數量（T86）。"""… | material_link.py |
| …link_serial_exclusive", "第 %d 列同時… | …link_serial_qty", "第 %d 列的序… | material_link.py |
| …ve", "第 %d 列同時帶庫存序號與材料申請連結：庫存出貨與材料申請出貨請分成不同列" % (i + 1))… | …ty", "第 %d 列的序號有 %d 筆，多於連結的材料申請數量 %s" % (i + 1, … | material_link.py |
| …同列" % (i + 1))… | …%s" % (i + 1, len(sers), _fmt(lk[2])))… | material_link.py |
| … "name": "採購・庫存・出貨",… | … "name": "採購與庫存",… | module.json |
| …這個角色（或這個人）可以看到所有供應商的資料與聯絡人… | …這個角色（或這個人）可以檢視所有供應商的資料與聯絡人… | module.json |
| …購／庫存」功能勾選的人也會看得到。",… | …購／庫存」功能勾選的人也可檢視。",… | module.json |
| …資料全公司有權查看的人都看得到。",… | …資料全公司有權查看的人都可檢視。",… | module.json |
| …"來源網站格式異動：上次抓取成功解析 %s 筆、解… | …"來源網站格式異動：上次擷取成功解析 %s 筆、解… | api.py |
| …會嘗試破解驗證碼，已停止抓取詳細頁。"})… | …會嘗試破解驗證碼，已停止擷取詳細頁。"})… | api.py |
| … "text": "上次抓取：來源網站回報當日沒有… | … "text": "上次擷取：來源網站回報當日沒有… | api.py |
| …寄信日（%s）：系統照常抓取，新標案的通知信會順延… | …寄信日（%s）：系統照常擷取，新標案的通知信會順延… | api.py |
| …           "抓取時段", confir… | …           "擷取時段", confir… | api.py |
| … "", f"清掉今天的抓取紀錄 {removed… | … "", f"清掉今天的擷取紀錄 {removed… | api.py |
| …會嘗試破解驗證碼，已停止抓取詳細頁；請通知系統維護… | …會嘗試破解驗證碼，已停止擷取詳細頁；請通知系統維護… | notify.py |
| …     "系統照常每日抓取並記錄。"… | …     "系統照常每日擷取並記錄。"… | notify.py |
| …系統不會嘗試破解，已停止抓取詳細頁（隔天才會試一次… | …系統不會嘗試破解，已停止擷取詳細頁（隔天才會試一次… | notify.py |
| …細頁無法自動讀取；已停止抓取詳細頁"… | …細頁無法自動讀取；已停止擷取詳細頁"… | source.py |
| …CAN_HOURS, "抓取時段")… | …CAN_HOURS, "擷取時段")… | source.py |
| …on(400, "請選擇要轉給誰")… | …on(400, "請選擇轉交對象")… | approval_queue.py |
| …el}」仍有關聯資料（如業務開發案件、報價單業務歸屬、部門／… | …el}」仍有關聯資料（如商機、報價單業務歸屬、部門／… | auth.py |
| …）。純函式，守門直接用。"""… | …）。純函式，守門直接用。`page` 不認得 ⇒ 只有全站區段。"""… | bootstrap.py |
| …    return "卡在：%s，%s" % (bloc… | …    return "待%s處理，%s" % (bloc… | dashboard_mine.py |
| …href_label="看全部", kind="… | …href_label="查看全部", kind="… | dashboard_mine.py |
| …"sub": "%s 送來，已 %d 天" % (… | …"sub": "%s 送審，已 %d 天" % (… | dashboard_mine.py |
| …href_label="去簽核", order=1… | …href_label="前往簽核", order=1… | dashboard_mine.py |
| …     empty="目前沒有等您簽的單"))… | …     empty="尚無待您簽核的單據"))… | dashboard_mine.py |
| …ted", "我送出的單",… | …ted", "我送出的單據",… | dashboard_mine.py |
| …href_label="看進度", order=… | …href_label="查看進度", order=… | dashboard_mine.py |
| …  "stuck", "停滯的單（2 天以上）",… | …  "stuck", "待處理已滿 2 天的單據",… | dashboard_mine.py |
| …href_label="去催件", order=30)… | …href_label="前往跟進", order=30)… | dashboard_mine.py |
| …Label") or "看全部"), "item… | …Label") or "查看全部"), "item… | dashboard_mine.py |
| …能選的範圍；金額欄位是否看得到仍由欄位可見政策決定）"… | …能選的範圍；金額欄位是否可檢視仍由欄位可見政策決定）"… | def_governance.py |
| …態的顯示名稱與顏色（只改看到的字與色，不改任何狀態值… | …態的顯示名稱與顏色（只改顯示的字與色，不改任何狀態值… | def_governance.py |
| …息與通知信的文字（收件人看到的字）", "custo… | …息與通知信的文字（收件人所見的字）", "custo… | def_governance.py |
| …的文字 ⇒ 放寬（收件人看到的字，需第二位最高管理者… | …的文字 ⇒ 放寬（收件人所見的字，需第二位最高管理者… | def_pipeline.py |
| …增自訂用語 %s（收件人看到的字，需核准）" % k… | …增自訂用語 %s（收件人所見的字，需核准）" % k… | def_pipeline.py |
| …用語 %s 改變（收件人看到的字，需核准）" % k… | …用語 %s 改變（收件人所見的字，需核准）" % k… | def_pipeline.py |
| …_MSG = "這項功能還在開發中，尚未開放調整。"… | …_MSG = "這項功能開發中，尚未開放調整。"… | definitions.py 等 2 處 |
| …全部紀錄）；只列您本來就看得到的紀錄與欄位。" % l… | …全部紀錄）；只列您本來就可檢視的紀錄與欄位。" % l… | rules.py |
| …跨客戶/供應商/報價單/業務開發案/料號，供 topbar… | …跨客戶/供應商/報價單/商機/料號，供 topbar… | search.py |
| …ption(400, "include_link… | …ption(400, "「LINE 訊息帶連結」的值不正確（必須是開或關）。請重新整理頁面後再操作；若是自己寫程式呼叫，include_link… | system.py |
| …nks 必須是 true／false")… | …nks 必須是 true 或 false")… | system.py |
| …ption(400, "channel acces… | …ption(400, "Channel acces… | system.py |
| …ken 格式不正確：只能是英數與 + / = . _ … | …ken 格式不正確：只能有英文字母、數字與 + / = . _ … | system.py |
| … -，長度 20～512，請從 LINE Develo… | … -，長度 20～512 個字元（中間不能有空白或換行）。請回到 LINE Develo… | system.py |
| … Developers 重新複製")… | … Developers → Messaging API 分頁重新複製整串 token 再貼上")… | system.py |
| …nel ID 格式不正確（應為純數字，請從 LINE Develo… | …nel ID 格式不正確：應為 6～20 位數字。請到 LINE Develo… | system.py |
| … Developers 的 Basic setti… | … Developers → LINE Login channel → Basic setti… | system.py |
| …ic settings 複製）")… | …ic settings 最上方複製")… | system.py |
| …secret 格式不正確（應為 32 位英數字，請從 LINE Developers 重新複製）")… | …secret 格式不正確：必須剛好 32 個英數字（0-9、a-f 或 A-F）。請到 Basic settings 的 Channel secret 重新複製")… | system.py |
| …ption(400, "啟用 LINE 通知前請… | …ption(400, "要啟用 LINE 通知，必… | system.py |
| … "啟用 LINE 通知前請先填寫 channel acces… | …"要啟用 LINE 通知，必須先填寫 Channel acces… | system.py |
| …access token")… | …access token（token）。請到 LINE Developers → Messaging API 分頁發行並複製 token，貼上並儲存後再啟用")… | system.py |
| …ption(400, "訊息要帶連結，必須先設定對外網… | …ption(400, "要讓 LINE 訊息帶連結，必須先設定對外網… | system.py |
| …連結，必須先設定對外網址（public_base_url）")… | …連結，必須先設定對外網址。沒有對外網址的話，請關閉「LINE 訊息帶連結」")… | system.py |
| …           "業務開發案",… | …           "商機",… | trail.py |

## 前端畫面（579 組）

| 改前 | 改後 | 位置 |
|---|---|---|
| …== 0"><span>目前沒有待您簽核的項目。</span></te… | …== 0"><span>尚無待您簽核的單據。</span></te… | index.html |
| …，下面的數字可能不完整；稍後重新整理看看。</p>… | …，下面的數字可能不完整；請稍後重新整理。</p>… | index.html |
| …         <p>目前沒有需要您處理的事。</p>… | …         <p>尚無需要您處理的事項。</p… | index.html |
| …>目前沒有需要您處理的事。</p>… | …<p>尚無需要您處理的事項。</p>… | index.html |
| …s="h-ghost">看今日工作事項</a>… | …s="h-ghost">查看今日工作事項</a>… | index.html |
| …nQuotation">去報價單</a>… | …nQuotation">前往報價單</a>… | index.html 等 2 處 |
| …g.empty \|\| '目前沒有需要處理的項目'"></… | …g.empty \|\| '尚無需要處理的項目'"></… | index.html |
| …動往下一層送。' : '目前沒有待您簽核的單據。')">… | …動往下一層送。' : '尚無待您簽核的單據。')">… | index.html |
| …未收到回應。') : '沒有需要追蹤的報價單。')"… | …未收到回應。') : '尚無需要追蹤的報價單。')"… | index.html |
| …rranty + ' 台已過保。') : '沒有已過保… | …rranty + ' 台保固已到期。') : '尚無保固已… | index.html |
| … 台已過保。') : '沒有已過保的設備。')"></p>… | …保固已到期。') : '尚無保固已到期的設備。')"></p>… | index.html |
| …aria-label="先收起上手清單（之後可從右… | …aria-label="暫時收起上手清單（之後可從右… | index.html |
| …（之後可從右上角「？」再打開）">先收起來</button>… | …（之後可從右上角「？」再開啟）">暫時收起</button>… | index.html |
| …         出貨單卡簽核… | …         出貨單簽核逾期… | index.html |
| …dding:24px">清單是空的：沒有輪到您的簽核單</td>… | …dding:24px">尚無待您簽核的單據</td>… | index.html |
| …dding:24px">目前無待收款項</td>… | …dding:24px">尚無待收款項</td>… | index.html |
| …rdue + ' 台設備已過保，先確認是否續約或更換。'… | …rdue + ' 台設備保固已到期，請確認是否續約或更換。'… | index.html |
| …'畫面上的數字暫時不準。重新整理可以再試一次。'… | …'畫面上的數字暫時不準。請重新整理後再試。'… | index.html |
| …    return '沒有需要您立刻處理的事項。'… | …    return '尚無需要您處理的事項。'… | index.html |
| …筆客戶', cta: '去建立', href: '… | …筆客戶', cta: '前往建立', href: '… | index.html |
| …報價單', cta: '去開立', href: '… | …報價單', cta: '前往開立', href: '… | index.html |
| …el: '確認簽核流程（誰要簽什麼）', cta: '去看… | …el: '確認簽核流程（簽核人與簽核項目）', cta: '前往… | index.html |
| …什麼）', cta: '去看看', href: 'p… | …項目）', cta: '前往查看', href: 'p… | index.html |
| …事加入', cta: '去新增帳號', href:… | …事加入', cta: '前往新增帳號', href:… | index.html |
| … + ' 筆') : '沒有符合的科目'… | … + ' 筆') : '查無符合條件的科目'… | account-items.js |
| … this.msg = r.ok ? '已儲存傳票科目' : ('傳票科目儲存失敗：… | … this.msg = !r.ok ? ('傳票科目儲存失敗：… | bonus.js |
| ….toast('報價單上沒有可帶入的欄位，或案件這邊… | ….toast('報價單上尚無可帶入的欄位，或案件已全… | case-management-biz.js |
| …沒有可帶入的欄位，或案件這邊都已經有值了。', {kind: '… | …尚無可帶入的欄位，或案件已全部有值。', {kind: '… | case-management-biz.js |
| …) return '按下去不會新增任何階段。'… | …) return '按下後不會新增任何階段。'… | case-management-exec.js |
| …this.toast('目前沒有可匯出的甘特圖'); r… | …this.toast('尚無可匯出的甘特圖'); r… | case-management-exec.js |
| …')  return '已過保'… | …')  return '保固已到期'… | case-management-exec.js |
| …      if (row.blockedCount === 1) return '差 … | …      if (miss.length) return '缺：… | case-management-list.js |
| … 1) return '差 ' + row.blockedLabels[0]… | …th) return '缺：' + miss.join('、')… | case-management-list.js |
| …, mergeWon: false },… | …, mergeWon: true },      // T86 案件UX #8：預設合併（設定中心 cases_merge_won_tab 預設 1）；公司明確存了 0 才分開… | case-management-list.js |
| …     alert('目前沒有可確認的事件，請先預覽'… | …     alert('尚無可確認的事件，請先預覽'… | cashier.js |
| …ss="dg-dim">目前沒有待核准的放寬變更。</d… | …ss="dg-dim">尚無待核准的放寬變更。</d… | def-governance.js |
| …ss="dg-dim">目前沒有草稿，沒有要發布的內容。</div>… | …ss="dg-dim">尚無草稿，無可發布的內容。</div>… | def-governance.js |
| …sible ? '（客戶看得到的輸出）' : '') … | …sible ? '（客戶可檢視的輸出）' : '') … | def-governance.js |
| …這些角色若有自己的版本，看到的不一定會跟著改。' : … | …這些角色若有自己的版本，顯示的內容不一定會跟著改。' : … | def-governance.js |
| … '費用歸屬部門', '這筆錢算在哪個部門', 'dept',… | … '費用歸屬部門', '所屬部門', 'dept',… | expense-types-designer.js |
| …s.msg = '草稿已丟棄，回到已發布版' } … | …s.msg = '草稿已捨棄，回到已發布版' } … | expense-types.js |
| …tableTo' ? '看得到的人都改得到' : '所… | …tableTo' ? '可檢視的人都改得到' : '所… | module-builder-elements.js |
| …有人（有這個模組權限的都看得到）'… | …有人（有這個模組權限的都可檢視）'… | module-builder-elements.js |
| …op:6px">樣本（您看得到的前 10 筆）</di… | …op:6px">樣本（您可檢視的前 10 筆）</di… | rules-builder.js |
| …會改資料、不會阻擋儲存。看不到來源欄位的人（例如沒有成… | …會改資料、不會阻擋儲存。無法檢視來源欄位的人（例如沒有成… | rules-builder.js |
| …例如沒有成本權限者）不會看到由該欄位產生的標示。</… | …例如沒有成本權限者）不會顯示由該欄位產生的標示。</… | rules-builder.js |
| …, devcase: '開發案件（CRM）' }… | …, devcase: '商機（業務開發）' }… | status-display-editor.js |
| …e-dim">只改畫面上看到的字與色；狀態的值（資料… | …e-dim">只改畫面上顯示的字與色；狀態的值（資料… | status-display-editor.js |
| … + n + ' 個附件沒有併進去'… | … + n + ' 個附件未併入'… | voucher.js |
| …xpandTo(1)">只看一級</button>… | …xpandTo(1)">僅顯示一級</button>… | account-items.html |
| …q.trim() ? '沒有符合的科目。' : '目前沒… | …q.trim() ? '查無符合條件的科目。' : '尚無會… | account-items.html |
| …有符合的科目。' : '目前沒有會計科目。'"></di… | …合條件的科目。' : '尚無會計科目。'"></di… | account-items.html |
| …mpty-state">目前沒有代理設定</div>… | …mpty-state">尚無代理設定</div>… | approval-delegates.html |
| …       佇列是空的時候不該有半個畫面在寫「… | …       尚無待處理項目時候不該有半個畫面在寫「… | approval-queue.html |
| …(isAdmin ? '目前沒有待簽核項目'… | …(isAdmin ? '尚無待簽核項目'… | approval-queue.html |
| … ' 件已逾時' : '沒有逾時項目'"></sma… | … ' 件已逾時' : '尚無逾時項目'"></sma… | approval-queue.html |
| …"isAdmin ? '目前沒有待簽核的單' : '您送… | …"isAdmin ? '尚無待簽核的單' : '您送… | approval-queue.html |
| …ost btn-sm">看今日工作事項</a>… | …ost btn-sm">查看今日工作事項</a>… | approval-queue.html |
| …    <strong>沒有輪到您的項目</stro… | …    <strong>尚無輪到您的項目</stro… | approval-queue.html |
| …在等其他簽核人' : '佇列是空的'"></span>… | …在等其他簽核人' : '尚無待處理項目'"></span>… | approval-queue.html |
| … - 2) + ' 項，點開看'"></span>… | … - 2) + ' 項，展開查看'"></span>… | approval-queue.html |
| …同一層有人排在您前面，請點開看詳情</span>… | …同一層有人排在您前面，請展開查看詳情</span>… | approval-queue.html |
| …ng>：送回申請人修改，改好可以重新送簽。… | …ng>：送回申請人修改，修改後可重新送簽。… | approval-queue.html |
| …    return '卡在：' + this.blo… | …    return '待' + this.blo… | approval-queue.html |
| ….display + '，' + (d === … | ….display + '處理，' + (d === … | approval-queue.html |
| …Error = '請選擇要轉給誰'; return }… | …Error = '請選擇轉交對象'; return }… | approval-queue.html |
| …          目前卡在… | …          目前待… | approval-queue.html |
| …          身上。轉簽只會換掉<b>當層… | …          處理。轉簽只會換掉<b>當層… | approval-queue.html |
| …ottom:4px">轉給誰 *</label>… | …ottom:4px">轉交對象 *</label>… | approval-queue.html |
| …用獨立流程。按「調整」可看到切換後誰會核准（儲存前不… | …用獨立流程。按「調整」可查看切換後誰會核准（儲存前不… | approval-settings.html |
| …     \|\| '（目前沒有任何文件類型套用統一流程）'… | …     \|\| '（目前尚無文件類型套用統一流程）'… | approval-settings.html |
| …in('／') : '（這一層沒有指定簽核人）')… | …in('／') : '（此層尚未指定簽核人）')… | approval-settings.html |
| …e.create">新增開發案件</option>… | …e.create">新增商機</option>… | audit-log.html |
| …e.update">更新開發案件</option>… | …e.update">更新商機</option>… | audit-log.html |
| …ase.status">案件狀態變更</option… | …ase.status">商機狀態變更</option… | audit-log.html |
| …lyFilter()">只看失敗</button>… | …lyFilter()">僅顯示失敗</button>… | audit-log.html |
| …         '新增開發案件',… | …         '新增商機',… | audit-log.html |
| …         '更新開發案件',… | …         '更新商機',… | audit-log.html |
| …           '案件狀態變更',… | …           '商機狀態變更',… | audit-log.html |
| …aria-label="這是什麼" @click="to… | …aria-label="說明" @click="to… | backup-monitor.html 等 7 處 |
| …'change' ? '把監控換到另一個主機（' + s.hea… | …'change' ? '將監控移轉至另一台主機（' + s.hea… | backup-monitor.html |
| … ? '告警' : '信寄不出去')"></span>… | … ? '告警' : '信無法寄出')"></span>… | backup-monitor.html |
| …s="sec-t">保留多久、什麼時候通知</h2>… | …s="sec-t">保留期限與通知時機</h2>… | backup-monitor.html |
| …ink-mail">設定誰收到備份告警信</a>… | …ink-mail">設定備份告警收件對象</a>… | backup-monitor.html |
| …'change' ? '把監控換到另一個主機' : '停用對外回… | …'change' ? '將監控移轉至另一台主機' : '停用對外回… | backup-monitor.html |
| …。萬一斷電或系統異常，就沒有人會收到通知。有多位最高… | …。萬一斷電或系統異常，就無人會收到通知。有多位最高… | backup-monitor.html |
| …；萬一斷電或系統異常，就沒有人會收到通知。請確認原因… | …；萬一斷電或系統異常，就無人會收到通知。請確認原因… | backup-monitor.html |
| … = '這會把外部監控換到另一個主機（' + nh + … | … = '這會把外部監控換至另一台主機（' + nh + … | backup-monitor.html |
| …查看完整帳號；其他人僅能看到末四碼。</span>… | …查看完整帳號；其他人僅能檢視末四碼。</span>… | bank-account.html |
| …="bc-empty">沒有更正單</div>… | …="bc-empty">尚無更正單</div>… | bonus-corrections.html |
| …"isSuper ? '沒有符合條件的案件' : '… | …"isSuper ? '查無符合條件的案件' : '… | bonus.html |
| …符合條件的案件' : '目前沒有您的獎金分潤資料'" d… | …符合條件的案件' : '尚無您的獎金分潤資料'" d… | bonus.html |
| …rt='stuck'">卡最久</button>… | …rt='stuck'">逾期最久</button>… | case-management.html |
| …-left:10px">只看</span>… | …-left:10px">僅顯示</span>… | case-management.html |
| …mtx__empty">沒有符合條件的案件</td>… | …mtx__empty">查無符合條件的案件</td>… | case-management.html |
| …holder="搜尋單號或客戶…"… | …holder="搜尋單號、客戶或專案…"… | case-management.html |
| …tTab==='已結案'}" @click="s… | …tTab==='已結案', 'cm-list__tab--zero': caseCounts && !summaryClosed() && listTab!=='已結案'}" @click="s… | case-management.html |
| …tTab==='待精算'}" @click="s… | …tTab==='待精算', 'cm-list__tab--zero': caseCounts && !summarySettling() && listTab!=='待精算'}" @click="s… | case-management.html |
| …'顯示全部 →' : '只看有新動態 →'"></s… | …'顯示全部 →' : '僅顯示有新動態 →'"></s… | case-management.html |
| …kAllRead()">一鍵已讀</button>… | …kAllRead()">全部標示已讀</button>… | case-management.html 等 2 處 |
| …      <span>沒有符合的案件</span>… | …      <span>查無符合條件的案件</span>… | case-management.html |
| …="search ? '嘗試調整搜尋關鍵字' : (… | …="search ? '請調整搜尋關鍵字' : (… | case-management.html |
| …pUrl()">在地圖上看</a>… | …pUrl()">在地圖上查看</a>… | case-management.html |
| …            </template>… | …                 placeholder="階段名稱" aria-label="階段名稱">… | case-management.html |
| …="fi fi--sm">… | …="fi fi--sm" aria-label="前往日期">… | case-management.html |
| …aceholder="人" class="fi … | …aceholder="人次" aria-label="人次" class="fi … | case-management.html |
| …容、施工項目、備註…" class="fi fi… | …容、施工項目、備註…" aria-label="工作內容／備註" class="fi fi… | case-management.html |
| …aterials')" style="paddi… | …aterials')" :title="caseReadOnly() ? '您不是本案成員，無法匯入品項' : ''" data-testid="mtl-import-quote" style="paddi… | case-management.html |
| …sToDevices()" style="pad… | …sToDevices()" :title="caseReadOnly() ? '您不是本案成員，無法同步至設備登錄' : ''" data-testid="mtl-sync-devices" style="pad… | case-management.html |
| …      <span style="color… | …      <span class="cm-section-title" style="margi… | case-management.html |
| …span style="color:var(--text-dim)">對應材料申請</span>… | …tle" style="margin-bottom:0">物料時間軸</span>… | case-management.html |
| …      <span x-text="mlRe… | …      <span class="mtl-name" x-text="mat.… | case-management.html |
| …an x-text="mlRecognizedText(mat)"></span>… | …e" x-text="mat.name \|\| '（未命名）'"></span>… | case-management.html |
| …ut class="fi fi--sm fi--mono" type="text… | …ut class="fi" type="text… | case-management.html |
| …laceholder="SN 序號" x-model="m… | …laceholder="品名" x-model="m… | case-management.html |
| …" x-model="md.sn" @input="au… | …" x-model="mat.name" @input="se… | case-management.html |
| …sn" @input="autoSyncDevice(mat, mi)">… | …me" @input="setDirty()" style="flex:1;min-width:0">… | case-management.html |
| …     <input class="fi fi… | …     <input data-saved-field class="fi" t… | case-management.html |
| …ut class="fi fi--sm fi--mono" type="text… | …ld class="fi" type="text… | case-management.html |
| …laceholder="MAC 位址" x-model="m… | …laceholder="廠牌/型號" x-model="m… | case-management.html |
| …" x-model="md.mac" @input="au… | …" x-model="mat.model" @input="se… | case-management.html |
| …ac" @input="autoSyncDevice(mat, mi)">… | …el" @input="setDirty()" style="width:110px;font-size:12px;flex-shrink:0">… | case-management.html |
| …             x-model="ma… | …            <input class="fi" type="number" placeholder="數量" x-model.num… | case-management.html |
| …     x-model="mat.supplier" @input="se… | …"數量" x-model.number="mat.qty" min="1" @input="se… | case-management.html |
| …"setDirty()"… | …"setDirty()" style="width:52px;flex-shrink:0">… | case-management.html |
| …ut class="fi fi--sm" type="text… | …ut class="fi" type="text… | case-management.html |
| …laceholder="廠商名稱"… | …laceholder="單位" x-model="mat.unit" @input="setDirty()" style="width:44px;font-size:12px;flex-shrink:0">… | case-management.html |
| …          x-model="mat.expectedDate" @input="setDirty()"… | …          x-text="mat.arrived ? '到料' : mat.ordered ? '材料申請中' : '待材料申請'"></span>… | case-management.html |
| …           </template>… | …           <span style="color:var(--text-dim)">對應材料申請</span>… | case-management.html |
| …           <input class="fi … | …           <select class="fi … | case-management.html |
| …"fi fi--sm" type="text" placeholder="備註" x-model="m… | …"fi fi--sm" style="min-width:220px" x-model="m… | case-management.html |
| …-model="mat.note" @input="setDirty()" style="width:100%;margin-top:6px">… | …-model="mat.orderItemId" @change="mlOnLinkChange(mat)" data-testid="mat-order-link" x-show="!(mat.poLink && mat.poLink.key)">… | case-management.html |
| …           </template>… | …           <option value="">（未連結）</option>… | case-management.html |
| …           <span style="font… | …           <div style="font… | case-management.html |
| …nt-size:12px;color:var(-… | …nt-size:12px;font-family:LINE Seed TW_OTF, sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(-… | case-management.html |
| …t-dim);font-family:var(--font-zh)">附件（到貨憑證/包裝清單…）</span>… | …t-dim);font-weight:600;margin-bottom:6px">設備序號 / MAC</div>… | case-management.html |
| …            ＋ 上傳附件… | …                  </div>… | case-management.html |
| …-text-dim)">沒有紀錄（開啟入庫紀錄之前的… | …-text-dim)">尚無紀錄（開啟入庫紀錄之前的… | case-management.html |
| …ace:nowrap">一鍵同步保固</span>… | …ace:nowrap">同步保固</span>… | case-management.html |
| …員可以在案件清單/詳情頁看到這張案件（即使不是這張案… | …員可以在案件清單/詳情頁檢視這張案件（即使不是這張案… | case-management.html |
| …屬人），並會在其個人視角看到相關任務與資訊… | …屬人），並會在其個人視角顯示相關任務與資訊… | case-management.html |
| …限，款項金額不顯示（—）；可編輯預計收款日、發票與… | …限，款項金額不顯示（—）。可編輯預計收款日、收款日… | case-management.html |
| …—）；可編輯預計收款日、發票與備註。</div>… | …—）。可編輯預計收款日、收款日期、備註與發票資料；收款狀態只供查看。已收款的期別除發票資料外不能修改。</div>… | case-management.html |
| …           <label class="fi-l… | …           <span class="fi-l… | case-management.html |
| …s="fi-label" :for="'pay-' + item.id + '-invno'">發票號碼</label>… | …s="fi-label">收款日期</span>… | case-management.html |
| …           </span>… | …           <span>發票資料</span>… | case-management.html |
| …      <span style="font-size:12px;color:var(--text-dim);font-family:var(--font-zh)">發票附件</span>… | …      <span class="pay-detail__sum" x-text="payDetailSummary(item, idx)"></span>… | case-management.html |
| …            ＋ 上傳發票… | …              <div>… | case-management.html |
| …           <template x-for="f in (item.invoiceFiles\|\|[])" :key="f.id">… | …           <label class="fi-label" :for="'pay-' + item.id + '-invno'">發票號碼</label>… | case-management.html |
| …        <div style="font… | …        <div data-testid="pay-rounding-note" style="font… | case-management.html |
| …olor:var(--tone-orange-fg);margin-top… | …olor:var(--text-secondary);margin-top… | case-management.html |
| …font-family:LINE Seed TW_OTF, sans-serif">↩ 第一筆自動吸收四捨五入差額，確… | …font-family:var(--font-zh)">說明：第一筆會自動吸收四捨五入的差額，… | case-management.html |
| … 第一筆自動吸收四捨五入差額，確保各期合計 100%</div>… | …第一筆會自動吸收四捨五入的差額，使各期合計維持 100%。</div>… | case-management.html |
| …-text-dim)">沒有可帶入的採購單明細（只有… | …-text-dim)">尚無可帶入的採購單明細（只有… | case-management.html |
| …            尚未建立任何出貨單… | …            <div>尚未建立任何出貨單。</… | case-management.html |
| …   尚未建立任何出貨單… | …iv>尚未建立任何出貨單。</div>… | case-management.html |
| … n.id)">在地圖上看</a>… | … n.id)">在地圖上查看</a>… | case-management.html |
| …lesErr">這個案件沒有您看得到的上傳檔案。</div>… | …lesErr">這個案件尚無您可檢視的上傳檔案。</div>… | case-management.html |
| …mpose__box" placeholder="記錄聯繫情況、案件進展、備忘…（填了執行時數/聯絡事項或附上照片即記為工作日誌）" x-model="newComment" rows="2"></textarea>… | …mpose__box" x-show="composeKind()!=='task'"… | case-management.html |
| …"feed-empty">這天沒有動態紀錄</div>… | …"feed-empty" x-text="feedCalSelDate ? '這天尚無動態紀錄' : '尚無一般動態；系統自動記錄已摺疊，可按上方「顯示」查看。'"></div>… | case-management.html |
| …ex-shrink:0">前往</button>… | …ex-shrink:0" x-text="settleGateLinks(g) ? '前往精算頁' : '前往'">前往</button>… | case-management.html |
| …-text-dim)">沒有可帶入的材料申請</di… | …-text-dim)">尚無可帶入的材料申請</di… | case-management.html |
| … :title="it.materialLink ? '這一列已連結材料申請，不能同時選庫存序號' : (it.part_no ? (i… | … :title="it.part_no ? (i… | case-management.html |
| …_no + '：' + it.serials.j… | …_no + '：' + (it.serials \|… | case-management.html |
| …+ it.serials.join('、')) … | … (it.serials \|\| []).join('、')) … | case-management.html |
| …s.join('、')) : '選擇庫存料號/序… | …).join('、')) : (it.materialLink ? '選擇庫存料號/序號（選填；序號必須是這筆材料申請入庫的、筆數不能多於出貨數量，送審時檢查）' : '選擇庫存料號/序… | case-management.html |
| …派發紀錄，之後在派發清單也看得到；未填則沿用派發原本設定… | …派發紀錄，之後在派發清單中也會顯示；未填則沿用派發原本設定… | case-management.html |
| …     <button @click="sho… | …     <button type="button" class="imp-btn" @click="sho… | case-management.html |
| …Modal=false"… | …Modal=false">取消</button>… | case-management.html |
| …                :disabled="… | …        <button type="button" class="imp-btn imp-btn--primary" @click="doImport()" :disabled="… | case-management.html |
| …me(Boolean)"… | …me(Boolean)" data-testid="import-confirm">匯入選取項目</button>… | case-management.html |
| … !onlyMine">只看我的</button>… | … !onlyMine">僅顯示我的</button>… | case-stage-board.html |
| …      目前沒有進行中的案件執行階段（僅… | …      尚無進行中的案件執行階段（僅… | case-stage-board.html |
| …oard-empty">目前沒有進行中的案件執行階段</… | …oard-empty">尚無進行中的案件執行階段</… | case-stage-board.html |
| …oard-empty">目前沒有任何指派紀錄</div>… | …oard-empty">尚無任何指派紀錄</div>… | case-stage-board.html |
| …mpty-state">目前沒有待匯款的申請</div>… | …mpty-state">尚無待匯款的申請</div>… | cashier.html |
| …mpty-state">目前沒有已簽回待付款的勞報單</… | …mpty-state">尚無已簽回待付款的勞報單</… | cashier.html |
| …mpty-state">目前沒有待發放的獎金分潤</di… | …mpty-state">尚無待發放的獎金分潤</di… | cashier.html |
| …-text-dim)">目前沒有待付款的申請</div>… | …-text-dim)">尚無待付款的申請</div>… | cashier.html |
| …mpty-state">沒有符合條件的款項</div… | …mpty-state">查無符合條件的款項</div… | cashier.html |
| …-text-dim)">目前沒有待簽核的匯款差額</di… | …-text-dim)">尚無待簽核的匯款差額</di… | cashier.html |
| …頁面下次開啟標記視窗即可看到最新清單；但不會回頭改到… | …頁面下次開啟標記視窗即可取得最新清單；但不會回頭改到… | cashier.html |
| …/strong> —— 用多少算多少。… | …/strong> —— 依實際用量計。… | company-profile-settings.html |
| …回免費，<strong>用多少算多少</strong>。… | …回免費，<strong>依實際用量計</strong>。… | company-profile-settings.html |
| …e Cloud 主控台上看到的數字 ——… | …e Cloud 主控台上顯示的數字 ——… | company-profile-settings.html |
| …strong>不設上限，超用多少算多少</strong>。… | …strong>不設上限，依實際用量計</strong>。… | company-profile-settings.html |
| …dge。<strong>正常情況下不用填</strong>——系… | …dge。<strong>一般情況下無須填寫</strong>——系… | company-profile-settings.html |
| …境變數，<strong>沒設好的話備份會靜默失敗</strong>，… | …境變數，<strong>未設定完成時，備份失敗將不會通知</strong>，… | company-profile-settings.html |
| …    切換後請確認隔天的備份告警沒有跳出來。… | …    切換後請確認隔天未出現備份告警。… | company-profile-settings.html |
| …laceholder="這次做了什麼、範圍到哪裡"></textarea… | …laceholder="本次作業內容與範圍"></textarea… | completion-note-form.html |
| ….msg = '已套用，記得按儲存'… | ….msg = '已套用，請記得按「儲存」'… | completion-note-form.html |
| …('有未儲存的變更，預覽看到的會是已儲存的版本。仍要… | …('有未儲存的變更，預覽顯示的會是已儲存的版本。仍要… | completion-note-form.html |
| …or.id)">在地圖上看</a>… | …or.id)">在地圖上查看</a>… | contractors.html 等 2 處 |
| …ss="dr-sub">目前沒有送審中的定義。</div… | …ss="dr-sub">尚無送審中的定義。</div… | custom-def-review.html |
| …rds.length">沒有單據</div>… | …rds.length">尚無單據</div>… | custom-records.html |
| …      <span>沒有符合的紀錄</span>… | …      <span>查無符合條件的紀錄</span>… | customer-log.html 等 2 處 |
| …是草稿，發布之後其他人才看得到。</div>… | …是草稿，發布之後其他人才可檢視。</div>… | customers.html 等 6 處 |
| …pty__title">沒有符合條件的客戶</div… | …pty__title">查無符合條件的客戶</div… | customers.html 等 2 處 |
| …er.id)">在地圖上看</a>… | …er.id)">在地圖上查看</a>… | customers.html 等 2 處 |
| …      尚無拜訪紀錄 · 點此開始記錄… | …      尚無拜訪紀錄，請按「新增」開始記錄… | customers.html |
| …件、指派給您自己；只有您看得到。建立後如要修改或刪除，… | …件、指派給您自己；只有您可檢視。建立後如要修改或刪除，… | daily-tasks.html |
| …th ? '' : '您目前沒有可關聯的進行中案件（只列… | …th ? '' : '您尚無可關聯的進行中案件（只列… | daily-tasks.html |
| …tice = '這項功能目前沒有開放，或案件模組未安裝；… | …tice = '這項功能尚未開放，或案件模組未安裝；… | daily-tasks.html |
| …/span><small>已連結報價單／估價單</… | …/span><small data-testid="dc-won-sub" x-text="wonUnlinkedCount > 0 ? wonUnlinkedCount + ' 件尚未連結單據' : '都已連結報價單／估價單'"… | dev-crm.html |
| …l>已連結報價單／估價單</small></sp… | …'都已連結報價單／估價單'"></small></sp… | dev-crm.html |
| …          新增案件… | …          新增商機… | dev-crm.html |
| …ceholder="搜尋案件、客戶或介紹人…"… | …ceholder="搜尋商機、客戶或介紹人…"… | dev-crm.html |
| …ue="__me__">只看我負責的</option… | …ue="__me__">僅顯示我負責的</option… | dev-crm.html |
| …alue="name">案件名稱</option>… | …alue="name">商機名稱</option>… | dev-crm.html |
| … 'asc' ? '最久沒動的排最前面' : ''"… | … 'asc' ? '最久未更新者排在最前' : ''"… | dev-crm.html |
| …dCount + ' 筆案件有更新未讀'"></sp… | …dCount + ' 筆商機有更新未讀'"></sp… | dev-crm.html |
| …'顯示全部 →' : '只看未讀 →'"></spa… | …'顯示全部 →' : '僅顯示未讀 →'"></spa… | dev-crm.html |
| …eCount + ' 筆案件洽談中超過 30 天未更… | …eCount + ' 筆商機洽談中超過 30 天未更… | dev-crm.html |
| …'顯示全部 →' : '只看逾期 →'"></spa… | …'顯示全部 →' : '僅顯示逾期 →'"></spa… | dev-crm.html |
| …;font-size:12px;color:var… | …;font-size:13px;color:var… | dev-crm.html |
| …--text-dim)">無符合案件</div>… | …--text-dim)" data-testid="dc-empty-list">… | dev-crm.html |
| …dash__sub">跨案件彙整，僅計入已核准的開發… | …dash__sub">跨商機彙整，僅計入已核准的開發… | dev-crm.html |
| …ash__title">案件責任分布</div>… | …ash__title">商機責任分布</div>… | dev-crm.html |
| …__sub">依目前全部業務開發案件統計（含各狀態）</di… | …__sub">依目前全部商機統計（含各狀態）</di… | dev-crm.html |
| …on-title">人員業務開發案件數</div>… | …on-title">人員負責商機數</div>… | dev-crm.html |
| …-title">專案負責案件數</div>… | …-title">專案負責商機數</div>… | dev-crm.html |
| …        <p>從案件列表選取案件，或新增第一筆業務開發案… | …        <p>從商機列表選取商機，或新增第一筆商機</p… | dev-crm.html |
| …表選取案件，或新增第一筆業務開發案件</p>… | …表選取商機，或新增第一筆商機</p>… | dev-crm.html |
| …e = null">← 案件列表</button>… | …e = null">← 商機列表</button>… | dev-crm.html |
| …          編輯案件… | …          編輯商機… | dev-crm.html |
| …ss="dc-lbl">案件狀態快照（選填）</sp… | …ss="dc-lbl">商機狀態快照（選填）</sp… | dev-crm.html |
| …CaseId ? '編輯案件' : '新增業務開發案… | …CaseId ? '編輯商機' : '新增商機'">… | dev-crm.html |
| …'編輯案件' : '新增業務開發案件'"></h3>… | …'編輯商機' : '新增商機'"></h3>… | dev-crm.html |
| …     <label>案件名稱 <span sty… | …     <label>商機名稱 <span sty… | dev-crm.html |
| …m:4px">此客戶過去案件</div>… | …m:4px">此客戶過去商機</div>… | dev-crm.html |
| …     <label>案件狀態</label>… | …     <label>商機狀態</label>… | dev-crm.html |
| …'儲存變更' : '建立案件'"></span>… | …'儲存變更' : '建立商機'"></span>… | dev-crm.html |
| …啟報價單／估價單表單，並預填以下資訊。… | …啟報價單／估價單表單，並帶入以下資訊；第一次儲存後會自動連結到這個商機。… | dev-crm.html |
| …    <div><b>案件名稱：</b><span… | …    <div><b>商機名稱：</b><span… | dev-crm.html |
| …tn-primary" @click="doCo… | …tn-primary" data-testid="dc-convert-go" @click="doCo… | dev-crm.html |
| …doConvert()">開啟報價單／估價單表單</button>… | …doConvert()"… | dev-crm.html |
| …r="輸入單號，留空表示案件變更需取消連結">… | …r="輸入單號，留空表示商機變更需取消連結">… | dev-crm.html |
| …：報價單／估價單已取消，案件需求變更…"></tex… | …：報價單／估價單已取消，商機需求變更…"></tex… | dev-crm.html |
| …t:600">解除連結（案件將退回洽談中）</spa… | …t:600">解除連結（商機將退回洽談中）</spa… | dev-crm.html |
| …    <h3>申請刪除案件</h3>… | …    <h3>申請刪除商機</h3>… | dev-crm.html |
| …高管理者審核，審核通過後案件資料將於系統備存後移除。… | …高管理者審核，審核通過後商機資料將於系統備存後移除。… | dev-crm.html |
| …            案件：<b x-text="… | …            商機：<b x-text="… | dev-crm.html |
| …         <b>案件：</b><span x… | …         <b>商機：</b><span x… | dev-crm.html |
| …  <span>批准後，案件及所有開發記錄將軟刪除並… | …  <span>批准後，商機及所有開發記錄將軟刪除並… | dev-crm.html |
| …敗不擋主畫面；目前進度在案件資料裡 */ }… | …敗不擋主畫面；目前進度在商機資料裡 */ }… | dev-crm.html |
| …oast('已將目前所有案件標記為已讀')… | …oast('已將目前所有商機標記為已讀')… | dev-crm.html |
| …ottom:8px">您目前沒有「業務開發」的使用權限<… | …ottom:8px">您尚無「業務開發」的使用權限<… | dev-crm.html |
| …Error = '請填寫案件名稱'; return … | …Error = '請填寫商機名稱'; return … | dev-crm.html |
| …       this._toast('案件已儲存')… | …       this.loadExpectedSummary()… | dev-crm.html |
| …        this._toast('狀態已更新：' + status)… | …      if (!needAsk) { this.changeStatus(status); ret… | dev-crm.html |
| …：' + status)… | …atus(status); return }… | dev-crm.html |
| …his._toast('案件已刪除並備存')… | …his._toast('商機已刪除並備存')… | dev-crm.html |
| …人填寫，已送主管審核）')… | …人填寫，已送主管審核）' + (keepOpen ? '。可接著寫下一筆。' : ''))… | dev-crm.html |
| …this._toast('記錄已儲存')… | …this._toast(keepOpen ? '記錄已儲存，可接著寫下一筆。' : '記錄已儲存')… | dev-crm.html |
| …      <span>沒有符合的設備</span>… | …      <span>查無符合條件的設備</span>… | devices.html |
| …in-top:10px">權限（點選切換；框線＝高敏感，財務三鍵可放進角色但不會讓持有者取得財務／出納能力）</div>… | …in-top:10px" x-show="!form.id">新角色建立後尚無任何權限。請在上方權限矩陣勾選該角色的欄位，再按「儲存」。</div>… | duty-roles.html |
| …lictHold()">先不處理</button>… | …lictHold()">暫不處理</button>… | expense-types.html 等 2 處 |
| …oGroup()">全部放一組</button>… | …oGroup()">全部歸為同一組</button>… | expense-types.html |
| …ardDraft()">丟棄草稿</button>… | …ardDraft()">捨棄草稿</button>… | expense-types.html 等 2 處 |
| …ems.length">沒有符合條件的檔案（只列出您… | …ems.length">查無符合條件的檔案（只列出您… | file-center.html |
| …件的檔案（只列出您有權限打開的）。</div>… | …件的檔案（只列出您有權限開啟的）。</div>… | file-center.html |
| …   row(dl, '怎麼確認完成', s.confirm… | …   row(dl, '完成確認方式', s.confirm… | getting-started.html |
| …-text-dim)">(目前關閉)</span>… | …-text-dim)">（目前關閉）</span>… | google-calendar-settings.html |
| …weight:600">(已啟用)</span>… | …weight:600">（已啟用）</span>… | google-calendar-settings.html |
| … 登入完成授權，避免連到別的 Gmail 帳號。</… | … 登入完成授權，避免連到其他 Gmail 帳號。</… | google-calendar-settings.html |
| … 行事曆整合」開關後儲存',… | … 行事曆整合」開關後儲存。',… | google-calendar-settings.html |
| …h Client 並填入',… | …h Client 並填入。',… | google-calendar-settings.html |
| …auth.py 完成授權',… | …auth.py 完成授權。',… | google-calendar-settings.html |
| …msg = '設定已儲存'; this.isEr… | …msg = '設定已儲存。'; this.isEr… | google-calendar-settings.html |
| …ail \|\| '儲存失敗'; this.isEr… | …ail \|\| '儲存失敗，請稍後再試。'; this.isEr… | google-calendar-settings.html |
| …件已建立，請至行事曆確認'; this.isEr… | …件已建立，請至行事曆確認。'; this.isEr… | google-calendar-settings.html |
| …敗，請確認設定與授權狀態'; this.isEr… | …敗，請確認設定與授權狀態。'; this.isEr… | google-calendar-settings.html |
| …     <b>匯入精靈目前沒有開放。</b><br>請… | …     <b>匯入精靈尚未開放。</b><br>請… | import-wizard.html |
| …         <p>要匯入哪一種資料？<b>建議順序：員工 →… | …         <p>選擇匯入資料類型<b>建議順序：員工 →… | import-wizard.html |
| …"reset()">取消，重新來</button>… | …"reset()">取消並重新開始</button>… | import-wizard.html |
| …ngth === 0">目前沒有低於水位的料號，暫無採購… | …ngth === 0">尚無低於水位的料號，暫無採購… | inventory.html |
| …in('\n') : '沒有紀錄'))… | …in('\n') : '尚無紀錄'))… | inventory.html |
| …b-an-empty">目前沒有需要補登的事件（稅額估計… | …b-an-empty">尚無需要補登的事件（稅額估計… | ledger-hub.html |
| …b-wh-empty">目前沒有扣繳項目。勞報單簽回後，… | …b-wh-empty">尚無扣繳項目。勞報單簽回後，… | ledger-hub.html |
| …hb-eng-all">一鍵確認到過帳</button>… | …hb-eng-all">確認至過帳</button>… | ledger-hub.html |
| …-eng-empty">目前沒有事件。按「產生分錄草稿」… | …-eng-empty">尚無事件。按「產生分錄草稿」… | ledger-hub.html |
| …d="hb-none">目前沒有已開啟的功能。</div… | …d="hb-none">尚無已開啟的功能。</div… | ledger-hub.html |
| …-problems"> 只看有問題的</label>… | …-problems"> 僅顯示待處理項目</label>… | ledger-settings.html |
| …個事件是否發送、發給誰。點格子立即生效；您的點選與批次動作都只是… | …個事件是否發送、發給誰。您的點選與批次動作都只是… | line-events.html |
| … <span>整欄開關：點欄頭的方塊，一次設定目前列出的所有列… | … <span>整欄開關：按一下欄頭的方塊，可一次設定目前列出的所有列… | mail-settings.html |
| …有列（已鎖定的列會略過）</span>… | …有列（已鎖定的列會略過）。</span>… | mail-settings.html |
| …bleReason: '只有行事曆、沒有收件人設… | …bleReason: '此項目只有行事曆、沒有收件人設… | mail-settings.html |
| …有行事曆、沒有收件人設定：請用「行事曆」欄頭整欄勾選，… | …有行事曆、沒有收件人設定，請以「行事曆」欄頭整欄勾選，… | mail-settings.html |
| …曆」欄頭整欄勾選，或逐列點選',… | …曆」欄頭整欄勾選，或逐列選取。',… | mail-settings.html |
| …s="mx-mute">沒有可指定的帳號</span… | …s="mx-mute">尚無可指定的帳號</span… | mail-settings.html |
| …關人員之外另外寄送；本人自行退訂、沒有 email 的人不會收… | …關人員之外另外寄送；本人已自行退訂或未設定 email 的使用者不… | mail-settings.html |
| …訂、沒有 email 的人不會收到。</div>'… | …或未設定 email 的使用者不會收到。</div>'… | mail-settings.html |
| …(--danger)">沒指定任何人</span>… | …(--danger)">尚未指定任何人</span>… | mail-settings.html |
| …一批的套用紀錄，無法復原'))… | …一批的套用紀錄，無法復原。'))… | mail-settings.html |
| … Error('這些修改和目前的設定一樣，沒有要儲存的')… | … Error('這些修改與目前的設定相同，無需儲存。')… | mail-settings.html |
| …y', label: '沒人會收到', title: '目… | …y', label: '無人收件', title: '目… | mail-settings.html |
| …, title: '目前沒有任何人會收到這類信（最高管理… | …, title: '目前無人會收到這類信件（最高管… | mail-settings.html |
| …前沒有任何人會收到這類信（最高管理者都退訂了，或沒有人設定 email）', … | … '目前無人會收到這類信件（最高管理者皆已退訂，或皆未設定 email）。',… | mail-settings.html |
| …沒有人設定 email）', test: fun… | …或皆未設定 email）。', test: fun… | mail-settings.html |
| …sh({ text: '沒人會收到', tone: 'ba… | …sh({ text: '無人收件', tone: 'ba… | mail-settings.html |
| …）；完成後重新開啟地圖即可看到，無須操作。… | …）；完成後重新開啟地圖即會顯示，無須操作。… | map.html |
| …secondary)">沒有地點資訊</div>… | …secondary)">尚無地點資訊</div>… | map.html 等 2 處 |
| …            目前沒有可定位的資料，原因請見上… | …            尚無可定位的資料，原因請見上… | map.html |
| …的材料申請、採購、到貨、出貨、設備與保固目前進度… | …的材料申請、採購、到貨、入庫、出貨、設備與保固進度摘要… | material-flow.html |
| …、到貨、出貨、設備與保固目前進度。僅顯示目前可計算的部分；本畫面僅供檢視、不可修… | …、入庫、出貨、設備與保固進度摘要。逐項操作請至案件內的物料時間軸；本畫面僅供檢視、不可修… | material-flow.html |
| …next"><span>目前沒有需要接著處理的項目。</… | …next"><span>尚無需要接著處理的項目。</… | material-flow.html |
| …trong><span>從沒有欄位的空白表單開始</span… | …trong><span>自空白表單開始</span… | module-builder.html |
| …本的選單項目仍然保留）。看得到頁籤的人＝有這個模組權限… | …本的選單項目仍然保留）。可檢視頁籤的人＝有這個模組權限… | module-builder.html |
| …的人＝有這個模組權限、且看得到那一頁的人；<b>隱藏頁… | …的人＝有這個模組權限、且可檢視那一頁的人；<b>隱藏頁… | module-builder.html |
| …     <label>誰看得到</label>… | …     <label>可檢視對象</label>… | module-builder.html 等 2 處 |
| …權限裡有這個 key 才看得到；簽核人不需要。預設 c… | …權限裡有這個 key 才可檢視；簽核人不需要。預設 c… | module-builder.html |
| …s().length">沒有符合的元件</div>… | …s().length">查無符合條件的元件</div>… | module-builder.html |
| …=== 'edit'">把左邊的元件拖到這裡</div>… | …=== 'edit'">將左側元件拖曳至此</div>… | module-builder.html |
| …aria-label="這個區塊一列幾欄"… | …aria-label="此區塊每列欄數"… | module-builder.html |
| …=== 'edit'">把元件拖到這個區塊</div>… | …=== 'edit'">將元件拖曳至此區塊</div>… | module-builder.html |
| …     <label>誰改得到</label>… | …     <label>可修改對象</label>… | module-builder.html |
| …== 'bad' ? '版型有問題' : '')"></s… | …== 'bad' ? '暫時無法預覽，原因見下方' : '')"></s… | module-builder.html |
| …PDF 產生失敗' : '')"></span>… | …PDF 產生失敗' : (pdfState === 'blocked' ? '暫時無法預覽，原因見下方' : ''))"></span>… | module-builder.html |
| …laceholder="這一版改了什麼">… | …laceholder="本版變更內容">… | module-builder.html |
| …不同的列會標示「待重啟」。… | …不同的列會標示「待重啟」（即篩選鈕「尚未生效」所列的模組）。… | module-settings.html |
| …）：所有模組一律可載入，沒有檢查授權金鑰。… | …）：所有模組一律可載入，未檢查授權金鑰。… | module-settings.html |
| …重啟後</th><th></th></tr>… | …重啟後</th><th>重啟後要啟用</th></tr>… | module-settings.html |
| …e-' + m.key"… | …e-' + m.key" :aria-label="'重啟後要啟用 ' + m.name">… | module-settings.html |
| …"ms-reason">這個安裝包裡沒有可選配的模組。</td>… | …"ms-reason">此安裝包內尚無可選配的模組。</td>… | module-settings.html |
| …        if (!r.ok) { this.isError = true; this.msg = d.detail \|\| … | …        if (res.ok) n += 1; else failed.push(it.name + '：' + (res.d.detail \|\| … | module-settings.html |
| …('操作失敗（' + r.status + '）… | …('操作失敗（' + res.status + '）… | module-settings.html |
| …tatus + '）'); return }… | …tatus + '）')))… | module-settings.html |
| … this.msg = '已' + (enable ? '啟用' : '停用') + '「' + m.name + '」，' +… | … this.msg = (n ? '已復原這一批（' + n + ' 項），重新啟動服務後生效。' : '') +… | module-settings.html |
| …<div style="font-size:13px;font-weight:600;margin-bott… | …<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bott… | my-account.html |
| …bottom:6px">我要收的 LINE 通知</div>… | …bottom:6px">… | my-account.html |
| …(--text-dim);margin-bottom:2px" x-text="g.… | …(--text-dim)" x-text="g.… | my-account.html |
| …text="g.name"></div>… | …text="g.name + '（收 ' + g.events.filter(e => e.enabled).length + '／' + g.events.length + '）'"></div>… | my-account.html |
| …in-top:6px">取消勾選後，這類通知不再推播到您的 LINE（… | …in-top:6px">勾選或按一下按鈕後立即生效，不需另外儲存。取消勾選的通知不會再推播到您的 LINE，… | my-account.html |
| …不再推播到您的 LINE（Email 不受影響）。… | …會再推播到您的 LINE，Email 不受影響。目… | my-account.html |
| …E（Email 不受影響）。</div>… | …E，Email 不受影響。目前列出的通知預設都收。</div>… | my-account.html |
| …b">LINE 通知目前沒有開放。管理者開啟 LIN… | …b">LINE 通知目前尚未開放。管理者開啟 LIN… | my-account.html |
| …d-sub">只改您自己看到的頭像圓圈顏色，不會出現… | …d-sub">只改您自己畫面上的頭像圓圈顏色，不會出現… | my-account.html |
| …-sub">只影響您自己看到的畫面，儲存於伺服器，更… | …-sub">只影響您自己的畫面，儲存於伺服器，更… | my-account.html |
| …eme: '僅影響您自己看到的配色。右上角的切換鈕是… | …eme: '僅影響您自己的配色。右上角的切換鈕是… | my-account.html |
| …page: '每次登入後第一個看到的頁面（只有您的權限看得到的頁面才會生效）。',… | …page: '每次登入後首先顯示的頁面（僅限您的權限可檢視的頁面才會生效）。',… | my-account.html |
| … new Error('這些修改和目前的設定一樣，沒有要儲存的')… | … new Error('所做修改與目前設定相同，無需儲存')… | my-account.html 等 2 處 |
| …top:12px">目前沒有會寄給您的 Email … | …top:12px">目前尚無會寄給您的 Email … | my-account.html |
| …y', label: '被哪些規則引用' },… | …y', label: '引用此項目的規則' },… | network-plan-form.html |
| …        : '沒有偵測到可用的資料列'… | …        : '未偵測到可用的資料列'… | network-plan-form.html 等 2 處 |
| …            無符合案件，或已成案/已結案案… | …            查無符合條件的案件，或已成案／已結案案… | network-plans.html |
| …  無符合案件，或已成案/已結案案件皆已建立過規劃… | …符合條件的案件，或已成案／已結案案件皆已建立過規劃… | network-plans.html |
| …目前讀不到用量：' + quota.error)… | …目前讀不到用量：' + (quota.error … | notification-settings.html |
| … quota.error) : '讀取中…'"><… | …(quota.error \|\| '尚無資料')) : (quotaTried ? '尚無用量資料' : '讀取中…')">… | notification-settings.html |
| …or) : '讀取中…'"></div>… | …資料' : '讀取中…')"></div>… | notification-settings.html |
| …（LINE 綁定回調用；沒有就留空）</label>… | …（LINE 綁定回調用；無則留空）</label>… | notification-settings.html |
| …已綁定、誰尚未綁定，並可一鍵以 Email 與系統內… | …已綁定、誰尚未綁定，並可以 Email 與系統內… | notification-settings.html |
| …>要發 LINE 的通知（依模組分組）</label>… | …>要發 LINE 的通知</label>… | notification-settings.html |
| …通知、沒有 Email，勾選後才會推 LINE（不會… | …通知、沒有 Email，開啟後才會推 LINE（不會… | notification-settings.html |
| …<div class="ns-toggle" style="margin:2px 0;flex-wrap:wrap">… | …<div class="le-legend" aria-label="圖例">… | notification-settings.html |
| …                            <button type… | …            <span><button type… | notification-settings.html |
| …ton" class="btn btn-ghost" style="padding:4px 12px;font-size:13px" @click="toggleAudEditor(e)">取消</button>… | …ton" class="mx-rc on a" tabindex="-1" aria-hidden="true">✓</button>綠＝指… | notification-settings.html |
| …>取消</button>… | …">✓</button>綠＝指定發給這些角色</span>… | notification-settings.html |
| …in-top:4px">勾選後立即生效。獎金、薪資、勞報單類通知… | …in-top:4px">獎金、薪資、勞報單類通知… | notification-settings.html |
| …-title">簽核提醒寄不出去的單據</div>… | …-title">簽核提醒無法寄出的單據</div>… | notification-settings.html |
| …系統已放棄自動重寄的簽核催辦信會列在這裡，最新的在最… | …系統已放棄自動重寄的簽核逾期提醒信會列在這裡，最新的在最… | notification-settings.html |
| …ight:600">目前沒有寄不出去的提醒。</div>… | …ight:600">目前無寄送失敗的提醒。</div>… | notification-settings.html |
| …；' : '') + '沒有寄 Email：' + … | …；' : '') + '未寄 Email：' + … | notification-settings.html |
| …       if (parts.some(p => !/^[0-9]+$/.test(p))) { this.sav… | …       if (problem) { this.sav… | notification-settings.html |
| …; this._say('告警門檻只能填整數百分比，例如 80,100', true); re… | …; this._say(problem + '（尚未儲存）', true, 150… | notification-settings.html |
| …0,100', true); return }… | …尚未儲存）', true, 15000); return }… | notification-settings.html |
| …ail \|\| '驗證失敗（請先儲存 token）', true, 800… | …ail \|\| '驗證失敗：沒有收到說明。請稍後再按一次驗證；仍失敗請確認 token 是否正確。', true, 120… | notification-settings.html |
| …en）', true, 8000)… | …正確。', true, 12000)… | notification-settings.html |
| …件人沒有 Email，信寄不出去'… | …件人沒有 Email，信無法寄出'… | notification-settings.html |
| …-text-dim)">目前沒有人在線</span>… | …-text-dim)">尚無人員在線</span>… | online-stats.html |
| …        <th>做了什麼</th>… | …        <th>操作內容</th>… | online-stats.html |
| …idth:140px">在哪一頁</th>… | …idth:140px">所在頁面</th>… | online-stats.html |
| … 這份資料只有最高管理者看得到。… | … 這份資料只有最高管理者可檢視。… | online-stats.html |
| …<h3 x-text="typeCode ? '… | …<h3 x-text="picked ? '案件' : (typeCode ? '… | payment-request.html |
| …）' : '① 挑案件'"></h3>… | …）' : '① 挑案件')"></h3>… | payment-request.html |
| ….length">找不到看得到的案件（只列您是業務或被… | ….length">找不到可檢視的案件（只列您是業務或被… | payment-request.html |
| …laceholder="沒填就用上面的廠商名稱"></labe… | …laceholder="未填寫時沿用上方廠商名稱"></labe… | payment-request.html |
| …iv x-text="'⚠ ' + d.text">… | …iv x-text="'注意：' + d.text">… | payment-request.html |
| …id) > 0 ? '　⚠ 超出報價計畫量 ' + … | …id) > 0 ? '　（超出報價計畫量 ' + … | payment-request.html |
| … overOf(id) : '')"></lab… | … overOf(id) + '）' : '')"></lab… | payment-request.html |
| …order' ? '超出報價計畫量時必填（送審時伺服器會檢查）' : '超出報價計畫量… | …order' ? '超出計畫量時必填' : '超出計畫量的原… | payment-request.html |
| …器會檢查）' : '超出報價計畫量的原因（請購單只提… | …畫量時必填' : '超出計畫量的原因（選填）'"… | payment-request.html |
| …'超出報價計畫量的原因（請購單只提示，可不填）'">… | …: '超出計畫量的原因（選填）'">… | payment-request.html |
| …atus, id: id, text: (sub… | …atus, id: id, no: no, text: (sub… | payment-request.html |
| … #' + id + '，可以在「我的申請」看進度' }… | … #' + id + '。' }… | payment-request.html |
| …          if (problems.length) { this.err = … | …            this.err = … | payment-request.html |
| … this.err = problems[0].message + (problems.len… | … this.err = '尚有 ' + problems.len… | payment-request.html |
| …lems.length > 1 ? '（還有 ' + (problems.length - 1… | …lems.length + ' 項需要修正：' + names.slice(0, 6).join('、') + (names.length > 6… | payment-request.html |
| …lems.length - 1) + ' 項）' : ''); ret… | …ames.length > 6 ? '…' : '') + '。… | payment-request.html |
| … ' 項）' : ''); return }… | … ? '…' : '') + '。欄位已標示紅色。'… | payment-request.html |
| …' + id)) + '，可以在「我的申請」看進度'… | …' + id)) + '。'… | payment-request.html |
| …t-dim)">這位人員目前沒有被排進任何派工。</div>… | …t-dim)">這位人員尚未排入任何派工。</div>… | payslip-form.html |
| …oin('、') : '沒有可帶入的空欄位') + … | …oin('、') : '尚無可帶入的空欄位') + … | payslip-form.html |
| …review-note">待簽核：由簽核人簽核；退回後回到草稿，可修改後重新送審</div>… | …review-note"… | payslips.html |
| …存；高風險放寬要填原因、等確認期間、需第二位最高管理者核准… | …存；高風險放寬要填原因、走等待期、需第二位最高管理者核准… | permission-matrix.html |
| …僅最高管理者可查看。勾選前會先說明會發生什麼事，確認後才會… | …僅最高管理者可查看。勾選的格子會先暫存在畫面上（尚未儲存）；勾好一批後按「預覽並套用」，一次看完會發生什麼事，確認後才會… | permission-matrix.html |
| …，確認後才會儲存，可隨時一鍵復原。</p>… | …，確認後才會儲存，可隨時復原。</p>… | permission-matrix.html |
| …v class="pm-chg" x-show="c… | …v class="pm-stg" x-show="i… | permission-matrix.html |
| …hg" x-show="c.cells[r.role].changed">已調整</div>… | …tg" x-show="isStaged(c, r)" :data-testid="'pm-staged-' + c.key + '-' + r.role">待套用</div>… | permission-matrix.html |
| …不能做</th><th>為什麼</th></tr></… | …不能做</th><th>原因</th></tr></… | permission-matrix.html |
| …verrides()">沒有任何個人調整。</div>… | …verrides()">尚無個人調整。</div>… | permission-matrix.html |
| …ing.length">目前沒有待生效的變更。</div… | …ing.length">尚無待生效的變更。</div… | permission-matrix.html |
| …"askUndo()">一鍵復原上一次調整</but… | …"askUndo()">復原上一次調整</but… | permission-matrix.html |
| …ding ? '已送出：要等確認期間後才會生效' + (r.… | …ding ? '已送出：需等待期後才會生效' + (r.… | permission-matrix.html |
| …== false ? '沒有變更（已經是這個狀態）。' : '已儲存… | …== false ? '無變更（目前已是此狀態）。' : '已儲存… | permission-matrix.html |
| …       if (!pv.changed) { this.msg = '沒有變更（已經是這個狀態）。'; return }… | …       if (!d \|\| this.busy) return… | permission-matrix.html |
| …態）。'; return }… | …busy) return… | permission-matrix.html |
| …            this._open('確認調整：' + r.label + '／' + c.label, pv, (reason) => this._post(… | …            const r = await this._post(… | permission-matrix.html |
| …rix/role-cap', Object.as… | …rix/role-cap/batch', Object.as… | permission-matrix.html |
| …ject.assign({ reason }, … | …ject.assign(this.stageBody(), { reason: th… | permission-matrix.html |
| …ign({ reason }, body)))… | …(), { reason: this.reason.trim(), planHash: d.planHash }))… | permission-matrix.html |
| …leText: '可隨時一鍵復原' },… | …leText: '可隨時復原' },… | permission-matrix.html 等 2 處 |
| … (ap ? '核准後，確認期間一到就會生效。' : '… | … (ap ? '核准後，等待期一到就會生效。' : '… | permission-matrix.html |
| …this._open('一鍵復原', { sente… | …this._open('復原', { sente… | permission-matrix.html |
| …態；放寬高風險項目仍要走確認期間與核准。', rever… | …態；放寬高風險項目仍要走等待期與核准。', rever… | permission-matrix.html |
| …:1px 6px">目前卡在這一步</span>… | …:1px 6px">目前處於此步驟</span>… | quotation-form.html |
| …()" x-show="(q.status !== '已送出' \|\| unlocked) && !hb.on … | …()" x-show="!isStatusLocked() && !hb.on … | quotation-form.html |
| …is-locked': q.status === '已送出' && !unlocked, 'approver-… | …is-locked': isStatusLocked(), 'approver-… | quotation-form.html |
| …生效，自動存檔已暫停。請先載入最新版，再重新進行您要修改的部分。</span>… | …生效，自動存檔已暫停。請選擇「載入最新版，保留我的修改」，或「載入最新版」並放棄未存的修改。</span>… | quotation-form.html |
| …<b>不會動到任何已經開出去的報價單</b>——報價… | …<b>不會動到任何已經開立的報價單</b>——報價… | quotation-form.html |
| …——報價單存的是當下複製過去的文字，… | …——報價單存的是當下複製的文字，… | quotation-form.html |
| …s._saveError… | …s._saveError + (this._failHow(this._saveCode) ? '\n處理方式：' + this._failHow(this._saveCode) : '')… | quotation-form.html |
| …命名）'}」？\n已經開出去的報價單不受影響。`))… | …命名）'}」？\n已經開立的報價單不受影響。`))… | quotation-form.html |
| …的修改，這次儲存未生效。請重新載入頁面後再繼續編輯。')… | …的修改，這次儲存未生效。\n請按畫面上方橫幅的「載入最新版，保留我的修改」（只換掉您沒改過的欄位），確認後再儲存。')… | quotation-form.html |
| …t('PDF 已下載完成')… | …t('PDF 已下載完成（檔名 ' + this.q.quoteNo + '.pdf，在瀏覽器的「下載」）')… | quotation-form.html |
| … { alert('內容沒有任何變動；若要維持原內容… | … { alert('內容無任何變動；若要維持原內容… | quotation-form.html |
| …您負責的報價單裡：草稿、被退回待修改的、已核准尚未送給客戶的"… | …您負責的報價單裡：草稿、已退回待修改、已核准尚未送給客戶的"… | quotations.html |
| …l-sum__lbl">要我處理</span>… | …l-sum__lbl">待我處理</span>… | quotations.html |
| …ineOk ? '草稿、被退回、已核准待寄客戶' … | …ineOk ? '草稿、已退回、已核准待寄客戶' … | quotations.html |
| …選擇）；關閉＝預設列出您看得到的全部">… | …選擇）；關閉＝預設列出您可檢視的全部">… | quotations.html |
| …owAll) ? '✓ 只看我負責的' : '只看我… | …owAll) ? '✓ 僅顯示我負責的' : '僅顯示… | quotations.html |
| … 只看我負責的' : '只看我負責的'"></spa… | …僅顯示我負責的' : '僅顯示我負責的'"></spa… | quotations.html |
| …" title="這張單現在卡在誰身上、還要等多久"><span x-… | …" title="這張單目前待誰處理、已等待多久"><span x-… | quotations.html |
| …pty__title">沒有符合條件的報價單</di… | …pty__title">查無符合條件的報價單</di… | quotations.html |
| …// 記住的選擇（只有「只看我負責的」開關會改寫它）… | …// 記住的選擇（只有「僅顯示我負責的」開關會改寫它）… | quotations.html |
| …e === 0 ? '您目前沒有負責的報價，先顯示全部'… | …e === 0 ? '您尚無負責的報價，先顯示全部'… | quotations.html |
| … = { todo: '要我處理', waitin… | … = { todo: '待我處理', waitin… | quotations.html |
| …rn { text: '被退回，請修改後重新送簽'… | …rn { text: '已退回，請修改後重新送審'… | quotations.html |
| …'被退回，請修改後重新送簽', tone: 'ac… | …'已退回，請修改後重新送審', tone: 'ac… | quotations.html |
| …   - 只有最高管理者看得到（選單 perm=sup… | …   - 只有最高管理者可檢視（選單 perm=sup… | recycle-bin.html |
| …永久清除。只有最高管理者看得到。</p>… | …永久清除。只有最高管理者可檢視。</p>… | recycle-bin.html |
| …="rb-empty">沒有符合的項目。</td></t… | …="rb-empty">查無符合條件的項目。</td></t… | recycle-bin.html |
| …b-no-types">目前沒有任何單據類型開放（由各擁… | …b-no-types">尚無任何單據類型開放（由各擁… | recycle-bin.html |
| …act.length">沒有已知的下游影響。</li… | …act.length">尚無已知的下游影響。</li… | recycle-bin.html |
| …>名稱</b>：開申請時看到的字，例：「訂金款」。… | …>名稱</b>：開申請時顯示的字，例：「訂金款」。… | remit-kinds-settings.html |
| …="rt-empty">沒有符合這些條件的資料。放寬條件（例… | …="rt-empty">查無符合條件的資料。放寬條件（例… | report-templates.html |
| …     <b>您的帳號目前沒有可看的報表</b>… | …     <b>您的帳號尚無可檢視的報表</b>… | reports-hub.html |
| …b>，上方任何一個期間都看不到它們。… | …b>，上方任何一個期間都不會顯示它們。… | reports.html |
| …"showAll ? '只看最近 10 筆' : '… | …"showAll ? '僅顯示最近 10 筆' : '… | schema-status.html |
| …="sc-empty">沒有符合的設定頁。</div>'… | …="sc-empty">查無符合條件的設定頁。</div>'… | settings-center.html |
| …      { id: 'sel', type: 'select', label: '選擇', show: function (… | …        disabled: function (… | settings-center.html |
| …rn r.f.type !== 'bool' &&… | …rn r.f.type === 'bool' ? … | settings-center.html |
| … !== 'bool' && r.f.type !== 'json' && !!(r.f.choices && r.f.choices.length) },… | … === 'bool' ? lockWhy(r) : false },… | settings-center.html |
| … t += '。一般同仁只會看到「設定已變更、由誰操作」… | … t += '。一般同仁僅會顯示「設定已變更、由誰操作」… | settings-center.html |
| …設定已變更、由誰操作」，看不到數值與原因'… | …設定已變更、由誰操作」，不顯示數值與原因'… | settings-center.html |
| …r) { return rangeText(r.… | …r) { return lockWhy(r) \|\| rangeText(r.… | settings-center.html |
| …nit \|\| '' },… | …nit \|\| '' },        // 鎖住的原因直接寫在名稱下面（手機、鍵盤、讀屏都看得到，不只靠 tooltip）… | settings-center.html |
| …ding-empty">目前沒有等待生效的變更。</di… | …ding-empty">尚無等待生效的變更。</di… | settings-center.html |
| …="sc-empty">目前沒有可用的預設組。</div… | …="sc-empty">尚無可用的預設組。</div… | settings-center.html |
| …rd = false">先保留我的編輯</butt… | …rd = false">保留我的編輯</butt… | settlement.html |
| …可按「前往」直接跳到該列；門檻集中在 STL_CONFIG</div></div>… | …可按「前往」直接跳到該列</div></div>… | settlement.html |
| …--text-dim)">—</span>… | …--text-dim)" x-text="itemShippedNoPerm ? '無檢視權限' : '—'">—</span>… | settlement.html |
| …secondary)">目前沒有未對應的項目。</div… | …secondary)">尚無未對應的項目。</div… | settlement.html |
| …      尚無往來紀錄 · 點此開始記錄… | …      尚無往來紀錄，請按「新增」開始記錄… | suppliers.html |
| …x">純文字備註，系統不拿它算日期</div>… | …x">純文字備註，系統不據以計算日期</div>… | suppliers.html |
| …資料與稽核皆由此進入；您看得到的項目依權限顯示</di… | …資料與稽核皆由此進入；您可檢視的項目依權限顯示</di… | system-hub.html |
| …abel="我知道了，不用再顯示">我知道了</b… | …abel="我知道了，不再顯示">我知道了</b… | system-hub.html 等 2 處 |
| …denied">這項功能還在開發中，目前還不能開啟。</div>… | …denied">這項功能開發中，目前尚不能開啟。</div>… | system-hub.html 等 2 處 |
| …h" x-text="'沒有符合「' + q.tri… | …h" x-text="'查無符合「' + q.tri… | system-hub.html |
| …hub-empty">您目前沒有可用的系統功能。</di… | …hub-empty">您尚無可用的系統功能。</di… | system-hub.html |
| …    <span>上次抓取 <span x-te… | …    <span>上次擷取 <span x-te… | tender-radar.html |
| …           ・丟棄 <span x-te… | …           ・捨棄 <span x-te… | tender-radar.html |
| …地點資訊尚未取得（每日有抓取上限，後續時段會補上）… | …地點資訊尚未取得（每日有擷取上限，後續時段會補上）… | tender-radar.html |
| …="fi-label">抓取時段（逗號分隔，0-2… | …="fi-label">擷取時段（逗號分隔，0-2… | tender-radar.html |
| …          抓取與寄信是<strong… | …          擷取與寄信是<strong… | tender-radar.html |
| …同一個時段內重複觸發只會抓一次。<br>… | …同一個時段內重複觸發只會擷取一次。<br>… | tender-radar.html |
| …secondary)">只看</span>… | …secondary)">僅顯示</span>… | tender-radar.html |
| …  目前<strong>一個搜尋條件都沒有</strong>，所以… | …  目前<strong>尚未設定任何搜尋條件</strong>，所以… | tender-radar.html |
| …條件，但<strong>目前的標案一筆都沒命中</strong>——… | …條件，但<strong>查無符合條件的標案</strong>——… | tender-radar.html |
| …是條件本身，不是再等一次抓取。… | …是條件本身，不是再等一次擷取。… | tender-radar.html |
| …        目前的篩選條件沒有符合的標案（共 <span … | …        查無符合條件的標案（共 <span … | tender-radar.html |
| …eMsg = `已儲存：抓取 ${d.scanHo… | …eMsg = `已儲存：擷取 ${d.scanHo… | tender-radar.html |
| …Hours \|\| '（不抓）'}／寄信 ${d.n… | …Hours \|\| '（不擷取）'}／寄信 ${d.n… | tender-radar.html |
| … alert('今天已經抓過了。抓取頻率硬上限是每日一次 … | … alert('今天已經擷取過了。擷取頻率硬上限是每日一次 … | tender-radar.html |
| …          沒有符合搜尋條件的使用者… | …          查無符合條件的使用者… | users.html |
| …-text-dim)">沒有未對應的案件角色。</d… | …-text-dim)">尚無未對應的案件角色。</d… | users.html |
| …       <span style="font… | …       <span x-show="pkUser.isHigh(mod.key)" style="font… | users.html |
| …color:var(--text-dim);font-weight:400"… | …color:var(--danger)" title="高敏感權限">★</span>… | users.html 等 2 處 |
| …text-dim)">（沒有可扣的角色權限）</sp… | …text-dim)">（尚無可扣的角色權限）</sp… | users.html |
| …size:12px">（取消勾選＝不寄該類信件給此帳號）</… | …size:12px">（關閉後不會寄該類信件給此帳號；按下… | users.html |
| …選＝不寄該類信件給此帳號）</span></la… | …後不會寄該類信件給此帳號；按下方的儲存按鈕後才會寫入。）</span></la… | users.html |
| …-text-dim)">沒有需要變更的項目</div>… | …-text-dim)">無需變更的項目</div>… | users.html |
| …            <span x-text="crForm.modules.includes(mod.key) ? … | …                 :data-testid="'cr-chip-' + mod.key" :title="pkCr.isInert(mod.key) ? … | users.html |
| …mod.key) ? '✓ ' : ''"></sp… | …mod.key) ? '財務／出納權限改由「財務」角色決定，此勾選已失效（資料保留，不刪除）' : ''">… | users.html |
| … '✓ ' : ''"></span>… | …不刪除）' : ''">… | users.html |
| …       <span style="font… | …       <span x-show="pkCr.isHigh(mod.key)" style="font… | users.html |
| …      尚無往來紀錄 · 點下方新增… | …      尚無往來紀錄，請按下方「新增」… | vendor-contractors.html |
| …            沒有符合篩選條件的傳票。… | …            查無符合條件的傳票。… | voucher.html |
| …   :title="'把差額填進第 ' + (curLi… | …   :title="'將差額填入第 ' + (curLi… | voucher.html |
| …s().length">目前沒有可選的案件。</div>… | …s().length">尚無可選的案件。</div>… | voucher.html |
| …eNote() \|\| '目前沒有可帶入的支出項。'"><… | …eNote() \|\| '尚無可帶入的支出項。'"><… | voucher.html |
| …尚無附件，沒有東西可以併進去'"… | …尚無附件，沒有東西可以併入'"… | voucher.html |
| …{ title: '客戶要把錢匯到哪裡', why: '請款單… | …{ title: '客戶匯款帳戶', why: '請款單… | company-wizard.js |
| … 步）') + '。請先回去補上。')… | … 步）') + '。請先返回補填。')… | company-wizard.js |
| …有內部人員在這個畫面就會看到這些欄位。確定要發布嗎？… | …有內部人員在這個畫面就會顯示這些欄位。確定要發布嗎？… | custom-fields.js |
| …howRoster: '只看這位受領人的派發',… | …howRoster: '僅顯示這位受領人的派發',… | dispatch-picker.js |
| …    empty: '沒有符合的派發',… | …    empty: '查無符合條件的派發',… | dispatch-picker.js |
| …wz.sending">沒收到，重寄一次</button>',… | …wz.sending">未收到，重新寄送</button>',… | email-setup.js |
| …essage: '尚未選要算什麼。', key: f.k… | …essage: '尚未選擇計算方式。', key: f.k… | form-designer-model.js |
| …天日期', why: '打開表單的那一天。', ex… | …天日期', why: '開啟表單的那一天。', ex… | form-designer.js |
| …和時間', why: '打開表單的那一刻。', ex… | …和時間', why: '開啟表單的那一刻。', ex… | form-designer.js |
| …('done') + '目前沒有要改的地方</span>') +… | …('done') + '尚無需要修改之處</span>') +… | form-designer.js |
| … return '尚未選要算什麼'… | … return '尚未選擇計算方式'… | form-designer.js |
| …al ? '這就是使用者會看到的樣子。' : '中間就… | …al ? '這就是使用者端顯示的樣子。' : '中間就… | form-designer.js |
| …' : '中間就是使用者會看到的表單。點任何一個欄位，… | …' : '中間就是使用者端顯示的表單。點任何一個欄位，… | form-designer.js |
| …進任何區塊的欄位，使用者會在「其他」看到。拖到上面的區塊就會歸位… | …進任何區塊的欄位，使用者端會顯示在「其他」。拖到上面的區塊就會歸位… | form-designer.js |
| …><h3>選項（使用者可以選哪些）</h3>' + th… | …><h3>選項（使用者可選內容）</h3>' + th… | form-designer.js |
| …ierOk ? '其他人看得到，但不能填；只有出納可以… | …ierOk ? '其他人可檢視，但不能填；只有出納可以… | form-designer.js |
| …', '「付款日」：業務只看得到，出納才能填。', !c… | …', '「付款日」：業務僅可檢視，出納才能填。', !c… | form-designer.js |
| …lk.ok ? '使用者看得到這一格，但不能自己改掉。… | …lk.ok ? '使用者可檢視這一格，但不能自己改掉。… | form-designer.js |
| …進階設定（只有最高管理者看得到）</summary><… | …進階設定（只有最高管理者可檢視）</summary><… | form-designer.js |
| …始是空的。<br>使用者會看到：（空白）'… | …始是空的。<br>使用者端顯示：（空白）'… | form-designer.js |
| …) + '<br>使用者會看到：' + esc(reg… | …) + '<br>使用者端顯示：' + esc(reg… | form-designer.js |
| … info = '使用者會看到您預先填好的內容。'… | … info = '使用者端會顯示您預先填好的內容。'… | form-designer.js |
| …   ['選項（使用者可以選哪些）', '一格一個；En… | …   ['選項（使用者可選內容）', '一格一個；En… | form-designer.js |
| …'自動帶入', '使用者打開表單時，這一格已經填好什… | …'自動帶入', '使用者開啟表單時，這一格已經填好什… | form-designer.js |
| … '自動帶入的內容使用者看得到但不能自己改。', '「… | … '自動帶入的內容使用者可檢視但不能自己改。', '「… | form-designer.js |
| …出納能修改', '其他人看得到，但不能填；只有出納可以… | …出納能修改', '其他人可檢視，但不能填；只有出納可以… | form-designer.js |
| …    ['看成品', '隱藏編輯用的… | …    ['預覽成品', '隱藏編輯用的… | form-designer.js |
| …, '隱藏編輯用的框線，看使用者實際看到的樣子。', '—'],… | …, '隱藏編輯用的框線，查看使用者端實際顯示的樣子。', '—'],… | form-designer.js |
| … = el('a', '看完整清單 →')… | … = el('a', '查看完整清單 →')… | getting-started-card.js |
| … [['what', '這是什麼'], ['when',… | … [['what', '說明'], ['when',… | hint-popover.js |
| …, ['when', '什麼時候要改'], ['impact… | …, ['when', '調整時機'], ['impact… | hint-popover.js |
| …['impact', '改了會影響什麼'], ['sugges… | …['impact', '影響範圍'], ['sugges… | hint-popover.js |
| …，編輯已鎖定；請關閉後再打開'… | …，編輯已鎖定；請關閉後再開啟'… | layout-editor.js |
| …結果不明：請關閉排版器再打開、看版本清單確認') }… | …結果不明：請關閉排版器再開啟、看版本清單確認') }… | layout-editor.js |
| …結果不明：請關閉排版器再打開確認') },… | …結果不明：請關閉排版器再開啟確認') },… | layout-editor.js |
| …le) + ' 發布後會看到這個樣子'… | …le) + ' 發布後會顯示成這個樣子'… | layout-editor.js |
| …使用者不適用（沒有權限或看不到目的群組），已略過。' … | …使用者不適用（沒有權限或無法檢視目的群組），已略過。' … | menu-editor.js |
| …版面）。重新整理頁面即可看到新的側欄。'… | …版面）。重新整理頁面即可顯示新的側欄。'… | menu-editor.js |
| …的使用者重新整理頁面後即可看到；其他角色不受影響。'… | …的使用者重新整理頁面後即會顯示；其他角色不受影響。'… | menu-editor.js |
| …'）在有角色層的模組不會看到這裡的調整；請至該角色的… | …'）在有角色層的模組不會套用這裡的調整；請至該角色的… | menu-editor.js |
| …oin('、') : '目前沒有要發布的調整。' }))… | …oin('、') : '尚無要發布的調整。' }))… | menu-editor.js |
| …跨客戶/供應商/報價單/業務開發案/料號快速查找；後端 G… | …跨客戶/供應商/報價單/商機/料號快速查找；後端 G… | notif.js |
| …   業務開發案/料號）點擊後導向該模組… | …   商機/料號）點擊後導向該模組… | notif.js |
| …hild(field('什麼事發生時要通知？', evSel, ev… | …hild(field('通知觸發事件', evSel, ev… | notify-action-editor.js |
| …hild(field('這個通知叫什麼名字？（只給管理者看）', el('inpu… | …hild(field('通知名稱（僅管理者可見）', el('inpu… | notify-action-editor.js |
| …hild(field('要通知誰？（最多 8 項）', e… | …hild(field('通知對象（最多 8 項）', e… | notify-action-editor.js |
| …件位址。收件人必須有權限看到那張單據才會收到。'))… | …件位址。收件人必須有權限檢視那張單據才會收到。'))… | notify-action-editor.js |
| …hild(field('用什麼方式通知？', el('div',… | …hild(field('通知方式', el('div',… | notify-action-editor.js |
| …', text: '試跑看看', disabled:… | …', text: '試跑', disabled:… | notify-action-editor.js |
| …t: '站內訊息（簽核人看到）', style: '… | …t: '站內訊息（簽核人可見）', style: '… | notify-editor.js |
| … '沒有財務權限的簽核人看到（金額會被遮蔽）', s… | … '沒有財務權限的簽核人可見（金額會被遮蔽）', s… | notify-editor.js |
| …ilterAria: '只看某個群組', expan… | …ilterAria: '僅顯示某個群組', expan… | settings-matrix.js |
| …目', empty: '沒有符合條件的項目',… | …目', empty: '查無符合條件的項目',… | settings-matrix.js |
| … helpWhat: '這是什麼', helpWhen:… | … helpWhat: '說明', helpWhen:… | settings-matrix.js |
| … helpWhen: '什麼時候要改', helpImpac… | … helpWhen: '調整時機', helpImpac… | settings-matrix.js |
| …elpImpact: '改了會影響什麼', helpRecom… | …elpImpact: '影響範圍', helpRecom… | settings-matrix.js |
| …搜尋客戶／報價單／案件／料號…"… | …搜尋客戶／報價單／案件／商機／料號…"… | sidebar.js |
| …weight:600">業務開發案</div>… | …weight:600">商機</div>… | sidebar.js |
| …-text-dim)">目前沒有其他人在線</div>'… | …-text-dim)">尚無其他人員在線</div>'… | sidebar.js |
| …-text-dim)">目前沒有通知</div>'… | …-text-dim)">尚無通知</div>'… | sidebar.js |
| …lse" title="這一頁怎麼用" aria-label… | …lse" title="本頁使用說明" aria-label… | sidebar.js |
| …aria-label="這一頁怎麼用" style="col… | …aria-label="本頁使用說明" style="col… | sidebar.js |
| … '?') + ' 之後多了 ' + n… | … '?') + ' 之後新增 ' + n… | sidebar.js |
| …      '這一頁需要對應的模組… | …      (superOnly ? '這一頁僅限最高管理者使用。<br>' : '這一頁需要對應的模組… | sidebar.js |
| …管理」中開通。<br>' +… | …管理」中開通。<br>') +… | sidebar.js |
| …僅作為入口，不會讓任何人看到或匯出其原本無權存取的內… | …僅作為入口，不會讓任何人檢視或匯出其原本無權存取的內… | user-buttons.js |
| …本無權存取的內容：每個人只看得到自己有權限的按鈕；目標頁… | …本無權存取的內容：每個人僅可檢視自己有權限的按鈕；目標頁… | user-buttons.js |
| …己」的身分執行，無權限者看不到此按鈕，也無法匯出。</… | …己」的身分執行，無權限者不會顯示此按鈕，也無法匯出。</… | user-buttons.js |
| …i x-text="\'看得到：\' + v.labe… | …i x-text="\'可檢視：\' + v.labe… | user-buttons.js |
| …i x-text="\'看不到：\' + h.labe… | …i x-text="\'無法檢視：\' + h.labe… | user-buttons.js |
| …，所有使用者在此畫面都會看到這些按鈕（每個人只看得到… | …，所有使用者在此畫面都會顯示這些按鈕（每個人僅可檢視… | user-buttons.js |
| …都會看到這些按鈕（每個人只看得到自己有權限的）。確定要發… | …都會顯示這些按鈕（每個人僅可檢視自己有權限的）。確定要發… | user-buttons.js |
| …依比例分攤至每個案件，才看得出扣掉這些之後是否仍有獲利… | …依比例分攤至每個案件，才能判斷扣掉這些之後是否仍有獲利… | ux-help.js |
| …['左欄「待我簽核」逐筆點開看內容。', '核准、退… | …['左欄「待我簽核」逐筆展開查看內容。', '核准、退… | ux-help.js |
| …    '看不懂的名詞，可以在下方「名詞解釋」查。'… | …    '不熟悉的名詞，可在下方「名詞解釋」查詢。… | ux-help.js |
| …可以在下方「名詞解釋」查。',… | …，可在下方「名詞解釋」查詢。',… | ux-help.js |
| …a-ux="more">看說明</button>… | …a-ux="more">查看說明</button>… | ux-help.js |
| …hecklist">重新打開上手清單</button… | …hecklist">重新開啟上手清單</button… | ux-help.js |

## 說明文件（7 組）

| 改前 | 改後 | 位置 |
|---|---|---|
| …**「業務開發」類通知（案件新增、階段變更、進度、拜… | …**「業務開發」類通知（商機新增、階段變更、進度、拜… | LINE-NOTIFY-USER-GUIDE.md |
| …轉報價單）的預設收件人（案件的業務負責人與主管）也要… | …轉報價單）的預設收件人（商機的業務負責人與主管）也要… | LINE-NOTIFY-USER-GUIDE.md |
| …- 想讓管理員也收到「業務開發案件更新」之類預設只給案件相… | …- 想讓管理員也收到「商機更新」之類預設只給商機相… | LINE-NOTIFY-USER-GUIDE.md |
| …發案件更新」之類預設只給案件相關人的通知，就選「再加… | …「商機更新」之類預設只給商機相關人的通知，就選「再加… | LINE-NOTIFY-USER-GUIDE.md |
| …\| 業務開發 \| 案件指派、取消指派、回覆期限… | …\| 業務開發 \| 商機指派、取消指派、回覆期限… | LINE-NOTIFY-USER-GUIDE.md |
| …業務開發更新」細項（新增案件、狀態變更、進度回報、拜… | …業務開發更新」細項（新增商機、狀態變更、進度回報、拜… | LINE-NOTIFY-USER-GUIDE.md |
| …發更新」細項預設只給**案件相關人**（業務＋企劃＋… | …發更新」細項預設只給**商機相關人**（業務＋企劃＋… | LINE-NOTIFY-USER-GUIDE.md |

