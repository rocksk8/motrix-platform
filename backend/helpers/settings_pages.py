# -*- coding: utf-8 -*-
"""設定中心「外框」的頁面登錄（SPEC §14.5；S2）。**分類只有這一套**；由 `data/shell_groups.json` 轉成執行期可讀的程式資料，
JSON 在 S2 合併後只留給 `gen_seed.py`——要改頁面名稱、分類、合併頁、獨立頁，**改這裡**。

- 設定頁（`PAGES`）：一頁含一到多個登錄群組（`groups`），群組頁由登錄表資料自動產生（S4 的作者寫資料，不寫每頁 HTML）。
- 獨立頁（`register_standalone`）：保留原網址與自己的 HTML／後端，只在外框導覽放連結、全域搜尋找得到頁名（S4 登記）。
- 守門：頁面登錄涵蓋的群組集合＝登錄表群組集合（`external=True` 的不計）——`coverage()` 回缺漏與多登，測試鎖定。
"""
from helpers import settings_registry as sr

CATEGORIES = ("業務", "財務", "系統", "安全")

PAGES = [{'id': 'builder_all',
  'plain': '自訂功能的開關（13 組）',
  'category': '系統',
  'groups': ['builder_status_display',
             'builder_layout',
             'builder_governance',
             'builder_rules',
             'builder_menu',
             'builder_custom_fields',
             'builder_actions',
             'builder_slots',
             'builder_exports',
             'builder_option_lists',
             'builder_notify',
             'builder_stage_templates',
             'builder_custom_modules'],
  'style': 'checkbox'},
 {'id': 'list_download', 'plain': '清單與下載檔名', 'category': '系統', 'groups': ['list_view', 'list_prefs', 'download_name'], 'style': 'checkbox'},
 {'id': 'home_look', 'plain': '首頁外觀、數字與日期', 'category': '系統', 'groups': ['ui_format', 'login_greeting', 'brand'], 'style': 'checkbox'},
 {'id': 'labels_biz',
  'plain': '網路規劃、採購、住宿的狀態名稱',
  'category': '業務',
  'groups': ['netplan_labels', 'procurement_labels', 'lodging_labels'],
  'style': 'checkbox'},
 {'id': 'small_misc', 'plain': '旅宿與標案地圖的小設定', 'category': '業務', 'groups': ['lodging_freshness', 'tender_closing'], 'style': 'checkbox'},
 {'id': 'account_security', 'plain': '登入與密碼規則', 'category': '安全', 'groups': ['account_security'], 'style': 'checkbox'},
 {'id': 'external_login', 'plain': '從外網登入的防護', 'category': '安全', 'groups': ['external_login'], 'style': 'checkbox'},
 {'id': 'change_control', 'plain': '重大設定要等幾天才生效', 'category': '安全', 'groups': ['change_control'], 'style': 'checkbox'},
 {'id': 'retention', 'plain': '資料保存多久', 'category': '安全', 'groups': ['retention'], 'style': 'checkbox'},
 {'id': 'recycle_bin', 'plain': '刪除的單據保留幾天', 'category': '安全', 'groups': ['recycle_bin'], 'style': 'checkbox'},
 {'id': 'quote_privacy', 'plain': '報價單的個人資料欄位（能否隱藏）', 'category': '安全', 'groups': ['quote_privacy'], 'style': 'checkbox'},
 {'id': 'uploads', 'plain': '上傳檔案的大小與數量', 'category': '系統', 'groups': ['uploads'], 'style': 'checkbox'},
 {'id': 'import_wizard', 'plain': '匯入精靈（將舊資料匯入系統）', 'category': '系統', 'groups': ['import_wizard'], 'style': 'checkbox'},
 {'id': 'system_hub', 'plain': '系統中心是否列出您沒有權限的項目', 'category': '系統', 'groups': ['system_hub'], 'style': 'checkbox'},
 {'id': 'monitoring', 'plain': '備份停擺、硬碟空間與暫存堆積的通知門檻', 'category': '系統', 'groups': ['monitoring'], 'style': 'checkbox'},
 {'id': 'material_order', 'plain': '材料申請規則', 'category': '業務', 'groups': ['material_order'], 'style': 'checkbox'},
 {'id': 'material_recognition', 'plain': '誰能把採購單認列到材料卡片', 'category': '業務', 'groups': ['material_recognition'], 'style': 'checkbox'},
 {'id': 'onepipe', 'plain': '物料流程一條龍（逐項開關）', 'category': '業務', 'groups': ['onepipe'], 'style': 'checkbox'},
 {'id': 'quote_alt', 'plain': '報價單的「擇一方案」', 'category': '業務', 'groups': ['quote_alt'], 'style': 'checkbox'},
 {'id': 'quote_approval', 'plain': '報價單什麼時候要送審', 'category': '業務', 'groups': ['quote_approval'], 'style': 'checkbox'},
 {'id': 'quote_output', 'plain': '隱藏的報價條件是否印在 PDF', 'category': '業務', 'groups': ['quote_output'], 'style': 'checkbox'},
 {'id': 'quote_defaults', 'plain': '報價單預設值', 'category': '業務', 'groups': ['quote_defaults'], 'style': 'checkbox'},
 {'id': 'quote_backfill', 'plain': '補登歷史案件', 'category': '業務', 'groups': ['quote_backfill'], 'style': 'checkbox'},
 {'id': 'case_close_gates', 'plain': '案件結案前要先完成什麼', 'category': '業務', 'groups': ['case_close_gates'], 'style': 'checkbox'},
 {'id': 'completion_note', 'plain': '完工單怎麼從報價單帶入', 'category': '業務', 'groups': ['completion_note'], 'style': 'checkbox'},
 {'id': 'alerts', 'plain': '保固與確認檔到期提醒', 'category': '業務', 'groups': ['alerts'], 'style': 'checkbox'},
 {'id': 'project_margin', 'plain': '專案毛利率低於多少要提醒', 'category': '財務', 'groups': ['project_margin'], 'style': 'checkbox'},
 {'id': 'finance_reports', 'plain': '帳齡與未精算提醒', 'category': '財務', 'groups': ['finance_reports'], 'style': 'checkbox'},
 {'id': 'finance_cashier', 'plain': '出納頁與銀行對帳單', 'category': '財務', 'groups': ['finance_cashier'], 'style': 'checkbox'},
 {'id': 'profit_warning', 'plain': '利潤提醒色帶', 'category': '財務', 'groups': ['profit_warning'], 'style': 'checkbox'},
 {'id': 'profit_rules', 'plain': '公益捐款比率', 'category': '財務', 'groups': ['profit_rules'], 'style': 'checkbox'},
 {'id': 'overhead', 'plain': '管銷怎麼分攤', 'category': '財務', 'groups': ['overhead'], 'style': 'checkbox'},
 {'id': 'payslip_dispatch_picker', 'plain': '勞報單「選派發」下拉一次載入幾筆', 'category': '財務', 'groups': ['payslip_dispatch_picker'], 'style': 'checkbox'},
 {'id': 'legal_params_reminder', 'plain': '法規參數跨年提醒', 'category': '財務', 'groups': ['legal_params_reminder'], 'style': 'checkbox'}]


#: 群組的白話名稱、現行名稱（小字）、是否影響隱私（標籤）
GROUPS = {'account_security': {'plain': '登入與密碼規則', 'currentName': '登入與密碼', 'privacy': False},
 'external_login': {'plain': '從外網登入的防護', 'currentName': '外網登入防護', 'privacy': False},
 'change_control': {'plain': '重大設定要等幾天才生效', 'currentName': '變更管制', 'privacy': False},
 'retention': {'plain': '資料保存多久', 'currentName': '保存期限', 'privacy': False},
 'recycle_bin': {'plain': '刪除的單據保留幾天', 'currentName': '資源回收筒', 'privacy': False},
 'quote_privacy': {'plain': '報價單的個人資料欄位（能否隱藏）', 'currentName': '報價單個人資料欄位', 'privacy': True},
 'uploads': {'plain': '上傳檔案的大小與數量', 'currentName': '上傳容量', 'privacy': False},
 'onepipe': {'plain': '物料流程一條龍（逐項開關）', 'currentName': '物料流程一條龍：各批次開關', 'privacy': False},
 'import_wizard': {'plain': '匯入精靈（將舊資料匯入系統）', 'currentName': '匯入精靈', 'privacy': False},
 'system_hub': {'plain': '系統中心是否列出您沒有權限的項目', 'currentName': '系統中心', 'privacy': False},
 'monitoring': {'plain': '備份停擺、硬碟空間與暫存堆積的通知門檻', 'currentName': '備份與監控告警', 'privacy': False},
 'download_name': {'plain': '下載檔案怎麼命名', 'currentName': '下載檔名', 'privacy': True},
 'ui_format': {'plain': '數字與日期怎麼顯示', 'currentName': '數字與日期顯示格式', 'privacy': False},
 'brand': {'plain': '系統標語', 'currentName': '系統標語', 'privacy': False},
 'login_greeting': {'plain': '登入畫面問候語', 'currentName': '登入問候語', 'privacy': False},
 'list_prefs': {'plain': '是否開放個人調整清單', 'currentName': '清單個人偏好', 'privacy': False},
 'list_view': {'plain': '清單各項個人調整', 'currentName': '清單檢視（個人偏好）', 'privacy': False},
 'builder_status_display': {'plain': '自訂狀態的名稱與顏色', 'currentName': '狀態顯示名稱與顏色', 'privacy': False},
 'builder_layout': {'plain': '自訂畫面的版面', 'currentName': '自訂畫面版面', 'privacy': False},
 'builder_governance': {'plain': '自訂功能的版本與發布管控', 'currentName': '建構器治理（版本帳本與發布前影響預覽）', 'privacy': False},
 'builder_rules': {'plain': '自訂規則（標示型）', 'currentName': '規則（標示型）', 'privacy': False},
 'builder_menu': {'plain': '自訂選單', 'currentName': '選單建構器', 'privacy': False},
 'builder_custom_fields': {'plain': '內建畫面的自訂欄位', 'currentName': '自訂欄位（內建畫面）', 'privacy': False},
 'builder_actions': {'plain': '自訂按鈕', 'currentName': '自訂按鈕', 'privacy': False},
 'builder_slots': {'plain': '附件種類與存放位置', 'currentName': '附件種類與儲存位置', 'privacy': False},
 'builder_exports': {'plain': '自訂匯出', 'currentName': '自訂匯出', 'privacy': False},
 'builder_option_lists': {'plain': '自訂下拉選項', 'currentName': '自訂選項清單', 'privacy': False},
 'builder_notify': {'plain': '自訂通知用語', 'currentName': '自訂通知用語', 'privacy': False},
 'builder_stage_templates': {'plain': '自訂案件階段樣板', 'currentName': '自訂案件階段樣板', 'privacy': False},
 'builder_custom_modules': {'plain': '建立自訂模組', 'currentName': '自訂模組引擎（建立新模組）', 'privacy': False},
 'material_order': {'plain': '材料申請規則', 'currentName': '材料申請', 'privacy': False},
 'material_recognition': {'plain': '誰能把採購單認列到材料卡片', 'currentName': '材料卡片認列採購單', 'privacy': False},
 'quote_alt': {'plain': '報價單的「擇一方案」', 'currentName': '擇一方案', 'privacy': False},
 'quote_approval': {'plain': '報價單什麼時候要送審', 'currentName': '報價送審門檻', 'privacy': False},
 'quote_output': {'plain': '隱藏的報價條件是否印在 PDF', 'currentName': '報價單輸出', 'privacy': False},
 'quote_defaults': {'plain': '報價單預設值', 'currentName': '報價單預設值', 'privacy': False},
 'quote_backfill': {'plain': '補登歷史案件', 'currentName': '補登歷史案件', 'privacy': False},
 'case_close_gates': {'plain': '案件結案前要先完成什麼', 'currentName': '結案條件加嚴', 'privacy': False},
 'completion_note': {'plain': '完工單怎麼從報價單帶入', 'currentName': '完工單', 'privacy': False},
 'alerts': {'plain': '保固與確認檔到期提醒', 'currentName': '到期預警', 'privacy': False},
 'netplan_labels': {'plain': '網路規劃：狀態名稱', 'currentName': '網路規劃：狀態名稱', 'privacy': False},
 'procurement_labels': {'plain': '採購建議：狀態名稱', 'currentName': '採購建議：狀態名稱', 'privacy': False},
 'lodging_labels': {'plain': '住宿紀錄：計價單位與詢價管道', 'currentName': '住宿紀錄：計價單位與詢價管道', 'privacy': False},
 'lodging_freshness': {'plain': '附近旅宿：資料新舊提示', 'currentName': '附近旅宿：資料新舊提示', 'privacy': False},
 'tender_closing': {'plain': '地圖：標案即將截止標記', 'currentName': '地圖：標案即將截止標記', 'privacy': False},
 'project_margin': {'plain': '專案毛利率低於多少要提醒', 'currentName': '專案毛利%', 'privacy': False},
 'finance_reports': {'plain': '帳齡與未精算提醒', 'currentName': '財務報表', 'privacy': False},
 'finance_cashier': {'plain': '出納頁與銀行對帳單', 'currentName': '出納', 'privacy': False},
 'profit_warning': {'plain': '利潤提醒色帶', 'currentName': '利潤提醒色帶', 'privacy': False},
 'profit_rules': {'plain': '公益捐款比率', 'currentName': '利潤口徑', 'privacy': False},
 'overhead': {'plain': '管銷怎麼分攤', 'currentName': '管銷分攤比率', 'privacy': False},
 'payslip_dispatch_picker': {'plain': '勞報單「選派發」下拉一次載入幾筆', 'currentName': '勞報單選派發下拉', 'privacy': False},
 'legal_params_reminder': {'plain': '法規參數跨年提醒', 'currentName': '法規參數跨年提醒', 'privacy': False}}


_STANDALONE = []            # 獨立頁：{"id", "plain", "category", "href", "standalone": True, "keywords": [...]}


def register_standalone(page_id, plain, category, href, *, keywords=()):
    """登記一個獨立設定頁（保留原網址）。重複、分類不存在、沒有 href ⇒ ValueError（登錄當下就失敗）。"""
    if category not in CATEGORIES:
        raise ValueError("獨立頁 %r 的分類不存在：%r（只有 %s）" % (page_id, category, "、".join(CATEGORIES)))
    if not plain or not href or not (str(href).split("?")[0].endswith(".html") or "/" in str(href)):
        raise ValueError("獨立頁 %r 需要白話名稱與連結" % (page_id,))
    if page_id in {p["id"] for p in PAGES} or page_id in {p["id"] for p in _STANDALONE}:
        raise ValueError("設定頁代號重複：%r" % (page_id,))
    _STANDALONE.append({"id": page_id, "plain": plain, "category": category, "groups": [], "href": href, "standalone": True,
                        "style": "", "keywords": list(keywords)})


def pages():
    """所有設定頁（群組頁＋獨立頁），依分類順序、再依登錄順序。"""
    allp = [dict(p, standalone=False, href="", keywords=[]) for p in PAGES] + [dict(p) for p in _STANDALONE]
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(allp, key=lambda p: order[p["category"]])          # sorted 穩定：同分類維持登錄順序


def page_of(group):
    """某登錄群組所在的設定頁代號；沒登記 ⇒ None。"""
    for p in PAGES:
        if group in p["groups"]:
            return p["id"]
    return None


def group_plain(group):
    """群組的白話名稱（找不到＝登錄表的名稱）。"""
    m = GROUPS.get(group)
    if m:
        return m["plain"]
    g = sr.groups().get(group)
    return g["label"] if g else group


def privacy_flag(page):
    """頁面是否帶「影響隱私」標籤（任一群組帶就算）。"""
    return any(GROUPS.get(g, {}).get("privacy") for g in page["groups"])


def coverage(registry_groups=None):
    """`(漏登, 多登, 重複)`：登錄表（不含 external）有、頁面沒涵蓋的群組；頁面有、登錄表沒有的群組；被兩頁以上涵蓋的群組。三者皆空才算過。"""
    reg = registry_groups
    if reg is None:
        reg = [g for g, m in sr.groups().items() if not m.get("external")]
    reg = set(reg)
    seen, dup = {}, set()
    for p in PAGES:
        for g in p["groups"]:
            if g in seen:
                dup.add(g)
            seen[g] = p["id"]
    return sorted(reg - set(seen)), sorted(set(seen) - reg), sorted(dup)


# ── 獨立頁登記（保留原網址；只在外框放連結＋讓全域搜尋找得到）──────────────────────────────────
# S6：每個人自己的 Email 通知（我的帳號 → 通知分頁）。這不是管理員設定，但使用者會去「設定」找它。
register_standalone("my_email_prefs", "我要收的 Email 通知（自己的）", "系統", "my-account.html?tab=notify",
                    keywords=["通知", "信件", "Email", "退訂", "不要收"])

# S4b：七個保留原網址的獨立頁（各自有表格／草稿／發布流程，不硬塞進群組矩陣；白話名＋關鍵字讓全域搜尋找得到）。
register_standalone("approval_settings", "簽核流程（誰要簽、簽幾層）", "財務", "approval-settings.html",
                    keywords=["簽核", "核准", "審核", "層級", "簽核人", "單據"])
register_standalone("approval_delegates", "簽核代理人（休假時誰代簽）", "財務", "approval-delegates.html",
                    keywords=["代理人", "代簽", "休假", "請假", "簽核"])
register_standalone("expense_types", "費用類型與填寫欄位", "財務", "expense-types.html",
                    keywords=["費用", "報支", "類型", "欄位", "公式"])
register_standalone("remit_kinds", "付款款別與各階段簽核", "財務", "remit-kinds-settings.html",
                    keywords=["付款", "匯款", "款別", "階段", "出納"])
register_standalone("ledger_settings", "帳務對應與報表科目", "財務", "ledger-settings.html",
                    keywords=["科目", "帳務", "報表", "分類", "歸屬", "對應"])
register_standalone("account_items", "會計科目表", "財務", "account-items.html",
                    keywords=["會計科目", "科目", "停用", "代碼"])
register_standalone("legal_params", "法規參數（稅率、保費、級距）", "財務", "legal-params.html",
                    keywords=["稅率", "扣繳", "補充保費", "二代健保", "勞健保", "級距", "生效日", "法規"])
