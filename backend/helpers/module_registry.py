# -*- coding: utf-8 -*-
"""權限模組的**唯一來源**（B7，2026-09-24 使用者裁示「整併成一份」）。

在此之前同一份清單抄在好幾個地方，而且已經不同步過（`tender_radar` 只在
sidebar 有徽章、notif.js 與 system.py 沒有 ⇒ 紅點永遠不亮）：

```
users.html         allModules（權限目錄）、ROLE_MODULES（角色樣板）
helpers/auth.py    _SUPERADMIN_MODULES（第一個管理員的模組）
routers/system.py  _MODULE_ACTION_PREFIXES／_MODULE_EXCLUDE_ACTIONS（選單紅點數法）
```
這些現在都引用這一份。**不引用這一份的**，刻意的：

- `db.py` v84 migration：凍結的歷史，不可以呼叫會演進的程式（test_upgrade_path u4）。
- 各 router 的 `require_any_module(...)` 字面值、sidebar.js 的顯示條件：那是**判斷邏輯**，
  保留字面值，由 `test_module_keys_consistency` 驗證每個字面值都在 `MODULE_KEYS` 內。

## 🔴 改這份清單＝改所有帳號看得到的權限畫面

- **新增** key：直接加，權限畫面立刻看得到；已有帳號不會自動獲得（要人勾）。
- **刪除／改名** key：正式機帳號身上的 `modules` JSON 仍然存著舊字串 ⇒
  必須先有 migration 與使用者裁示，不可以只改這裡。
- 值與 2026-09-24 整併前逐項相同，由 `test_module_registry_2026_09_24` 的 golden 題守著。
"""

#: ## 目錄的歷史註記（整併前寫在 users.html 各項上方，逐字搬過來）
#:
#: `project_manage`：
#:   2026-09-13（模組權限稽核）：`project_manage` 補回目錄。它是「專案管理」
#:   時代留下的 key，2026-08-26 專案管理併入案件管理時從這份目錄移除，
#:   但 `routers/material_orders.py` 至今仍拿它擋「修改叫料」——結果是這個
#:   權限只剩 9 個舊帳號靠歷史殘值持有，**任何新建帳號都永遠拿不到、一改
#:   叫料就 403，而且畫面上沒有任何地方勾得到**。key 維持原名不改（改名要
#:   跑 migration，且那 9 個帳號會瞬間失去權限），只把標籤改成它今天實際
#:   在管的事情。
#:
#: `netplan`：
#:   2026-09-14：這個模組原本**只有 edit key、沒有檢視 key**——側欄那一項
#:   是寫死 `|| ad || eng`，所以「誰看得到規劃書」根本不可勾選。比照選型
#:   導覽的 `x_guide` / `x_guide_edit` 兩段式補上檢視 key。
#:
#: `audit_log`：
#:   2026-09-14 使用者裁示「沒有對應模組 key 也建立就沒有這個問題」——
#:   這四頁原本在側欄是寫死 `ad`（admin 以上），沒有任何可勾選的 key，
#:   所以「未開啟的直接不顯示」這條規則對它們無從套用。建了 key 之後
#:   它們跟其他模組一樣逐帳號勾選，不用再改程式碼裡的角色判斷式。
#:
#: (key, 權限畫面的名稱, 分組)。**順序＝權限畫面的順序**（照抄整併前 users.html:793-848）。
MODULES = (
    ("dashboard", "儀表板", "基本"),
    ("dev_crm", "業務開發 CRM", "業務"),
    ("tender_radar", "標案雷達", "業務"),
    ("map", "地圖", "業務"),
    ("quotation", "報價單／簽核佇列", "業務"),
    ("case_manage", "案件管理", "業務"),
    ("project_manage", "案件叫料－修改", "業務"),
    ("customer", "客戶管理", "業務"),
    ("financial_view", "財務金額可視", "財務"),
    ("finance", "應收帳款／銷售訂單", "財務"),
    ("reports", "營運報表", "財務"),
    ("cashier", "出納（標記已匯款/已收款、銀行對帳）", "財務"),
    ("procurement", "供應商／料號／採購", "採購"),
    ("inventory", "庫存管理", "採購"),
    ("equipment", "設備登載／保固", "設備"),
    ("netplan", "網路架構規劃書－檢視", "網路架構規劃書"),
    ("netplan_edit", "網路架構規劃書－新增修改刪除", "網路架構規劃書"),
    ("project_approve_eng", "案件待辦－工程主管確認", "專案"),
    ("project_approve_biz", "案件待辦－業務確認", "專案"),
    ("work_log", "工作日誌", "工作"),
    ("daily_task", "每日工作事項", "工作"),
    ("contractor_list", "外包名冊", "勞務"),
    ("payslip", "勞報單", "勞務"),
    ("env_guide", "場域選型導覽－檢視", "選型資料庫"),
    ("env_guide_edit", "場域選型導覽－新增修改刪除", "選型資料庫"),
    ("netarch_guide", "網路架構選型導覽－檢視", "選型資料庫"),
    ("netarch_guide_edit", "網路架構選型導覽－新增修改刪除", "選型資料庫"),
    ("switch_guide", "交換器選型導覽－檢視", "選型資料庫"),
    ("switch_guide_edit", "交換器選型導覽－新增修改刪除", "選型資料庫"),
    ("monitor_guide", "監控系統選型導覽－檢視", "選型資料庫"),
    ("monitor_guide_edit", "監控系統選型導覽－新增修改刪除", "選型資料庫"),
    ("access_guide", "門禁系統選型導覽－檢視", "選型資料庫"),
    ("access_guide_edit", "門禁系統選型導覽－新增修改刪除", "選型資料庫"),
    ("gateway_guide", "閘道器與控制器選型導覽－檢視", "選型資料庫"),
    ("gateway_guide_edit", "閘道器與控制器選型導覽－新增修改刪除", "選型資料庫"),
    ("automation_guide", "自動化系統選型導覽－檢視", "選型資料庫"),
    ("automation_guide_edit", "自動化系統選型導覽－新增修改刪除", "選型資料庫"),
    ("settings", "系統設定", "系統"),
    ("audit_log", "歷史紀錄（全系統操作軌跡）", "系統"),
    ("shipping_export_log", "出貨單歷史紀錄", "系統"),
    ("module_versions", "版本紀錄", "系統"),
    ("selection_overview", "選型資料庫涵蓋度總覽", "系統"),
)

#: 建立帳號時依角色預帶的模組（照抄整併前 users.html:719-723）。
ROLE_TEMPLATES = {
    "superadmin": ("dashboard", "quotation", "case_manage", "customer", "procurement", "inventory", "equipment", "finance", "reports", "settings", "project_approve_eng", "project_approve_biz", "financial_view", "work_log", "daily_task", "env_guide", "netarch_guide", "switch_guide", "monitor_guide", "access_guide", "gateway_guide", "automation_guide", "cashier", "netplan", "audit_log", "shipping_export_log", "module_versions", "selection_overview",),
    "admin": ("dashboard", "quotation", "case_manage", "customer", "procurement", "inventory", "equipment", "finance", "reports", "project_approve_eng", "project_approve_biz", "financial_view", "work_log", "daily_task", "env_guide", "netarch_guide", "switch_guide", "monitor_guide", "access_guide", "gateway_guide", "automation_guide", "cashier",),
    "sales": ("dashboard", "quotation", "case_manage", "customer", "financial_view", "project_approve_biz", "work_log", "daily_task",),
    "engineer": ("dashboard", "case_manage", "project_approve_eng", "equipment", "work_log", "daily_task",),
    "viewer": ("dashboard",),
}

#: 第一個 superadmin 帳號的模組（`init_default_admin`）。
#: ⚠️ 保留整併前 helpers/auth.py 的**順序**：新安裝時寫進 DB 的 modules JSON 與今天逐字元相同。
#:    集合與 `ROLE_TEMPLATES["superadmin"]` 相同（題守）。
SUPERADMIN_DEFAULT = (
    "dashboard",
    "quotation",
    "case_manage",
    "customer",
    "procurement",
    "inventory",
    "equipment",
    "finance",
    "reports",
    "cashier",
    "settings",
    "project_approve_eng",
    "project_approve_biz",
    "financial_view",
    "work_log",
    "daily_task",
    "env_guide",
    "netarch_guide",
    "switch_guide",
    "monitor_guide",
    "access_guide",
    "gateway_guide",
    "automation_guide",
    "netplan",
    "audit_log",
    "shipping_export_log",
    "module_versions",
    "selection_overview",
)

#: 選單紅色數字：每個模組算哪些 audit action 前綴（照抄整併前 routers/system.py）。
BADGE_PREFIXES = {
    "dev_crm": ("dev_case.", "dev_log."),
    "tender_radar": ("tender_watch.", "tender_radar."),
    "quotation": ("quotation.",),
    "case_manage": ("deal_tag.",),
    "customer": ("customer.",),
    "procurement": ("supplier.", "part.", "vendor."),
    "equipment": ("device.", "warranty."),
    "finance": ("payment.", "sales_order.", "settlement."),
    "work_log": ("work_log.",),
    "daily_task": ("daily_task.",),
}

#: 不算進紅點的 action（例如刪除流程的中間事件）。
BADGE_EXCLUDE = {
    "dev_crm": (
        "dev_case.delete",
        "dev_case.delete_request",
        "dev_case.delete_cancel",
        "dev_case.delete_reject",
    ),
}

MODULE_KEYS = frozenset(k for k, _label, _group in MODULES)


def refuse_unknown_new_keys(new_modules, existing_modules=()) -> None:
    """B7 第三階段（使用者：「要，只驗這次新增的」）：這次**新加入**的 key 必須在目錄內。

    帳號／角色身上**原本就有**的 key（例如已停用的 `sales`）照樣放行 ⇒ 正式機既有資料零影響。
    ☠️ 在此之前後端什麼字串都照存：打錯字的 key 存得進去，而它不會擋也不會放任何東西，
       畫面上卻顯示「已勾選」。
    """
    from fastapi import HTTPException
    keep = set(existing_modules or ())
    bad = sorted({k for k in (new_modules or ()) if k not in MODULE_KEYS and k not in keep})
    if bad:
        raise HTTPException(400, "不認得的權限模組：%s（請重新整理頁面後再試）" % "、".join(bad))


def catalog() -> dict:
    """給權限畫面（users.html）用：目錄＋角色樣板。"""
    return {
        "modules": [{"key": k, "label": label, "group": group} for k, label, group in MODULES],
        "roleTemplates": {role: list(keys) for role, keys in ROLE_TEMPLATES.items()},
    }
