# -*- coding: utf-8 -*-
"""寫入資料的端點（POST／PUT／PATCH／DELETE）必須寫稽核紀錄。

使用者裁示（2026-09-24 午，N8①）。在此之前沒有任何測試守這一件：
`test_system_audit` 掃的是「有沒有呼叫**權限**守門」，不是有沒有寫稽核；
第一次量出來 364 支寫入端點裡有 43 支成功時不留任何紀錄。

## 規則

- 用 **ast** 掃 `routers/*.py`（不用 regex：字串、註解裡的 `_audit(` 會騙過 regex）。
- 算數的只有：直接呼叫 `_audit`／`_system_audit`，或呼叫 `AUDIT_WRAPPERS` 明列的包裝函式。
- **不做同名函式推論**。☠️ 第一版量尺就是這樣被騙的：案件階段 10 支呼叫
  `_deny_if_case_locked_unsupported()`，而那支**只在拒絕時**寫 audit
  （它的 docstring 寫明「純記錄撞牆」）⇒ 成功路徑一筆都沒有，量尺卻算「有」。
- 不寫業務資料的端點列 `EXEMPT`，每一筆寫原因；另有兩題守這份清單本身
  （端點必須存在、原因不可空泛），避免「全部列成例外」變綠。
"""
import ast
import glob
import os
import re

from core import source_tree

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_CALLS = {"_audit", "_system_audit"}
WRITE_METHODS = {"post", "put", "patch", "delete"}

#: 會在**成功路徑**上寫稽核的包裝函式：名稱 → (定義所在檔, 說明)。
#: 第三題會驗它真的直接呼叫 `_audit`／`_system_audit`。
AUDIT_WRAPPERS = {
    "_issue_session": ("routers/auth.py", "登入成功發 session 時寫 auth.login"),
    # 31-A 承攬商派發審核：兩段審核的八支端點共用這四支（成功才走到最後的 `_audit`；拒絕都在前面 raise）
    "dispatch_review_submit": ("modules/subcontract/api/dispatch_approval.py", "送審成功寫 vendor.dispatch[.completion].submit"),
    "dispatch_review_approve": ("modules/subcontract/api/dispatch_approval.py", "核准成功寫 …approve"),
    "dispatch_review_reject": ("modules/subcontract/api/dispatch_approval.py", "退回成功寫 …reject"),
    "dispatch_review_withdraw": ("modules/subcontract/api/dispatch_approval.py", "撤回成功寫 …withdraw"),
    # `/accept` 與 `/status`：作業狀態改變成功才寫 vendor.dispatch.<target>
    "dispatch_status_audited": ("modules/subcontract/api/vendor_contractors.py", "作業狀態改變成功寫 vendor.dispatch.<target>"),
    # S-ST2 套用階段樣板：實際寫入在 `_apply_stage_template_write`，commit 後寫 case_stage.apply_template（預覽 dryRun 與「沒有可建立的階段」都不寫入、不稽核）
    "_apply_stage_template_write": ("modules/case/api/quotations.py", "套用成功（階段已建立）寫 case_stage.apply_template"),
}

#: 不寫稽核的寫入端點：(檔名, 方法, 路徑) → 原因。
EXEMPT = {
    # ── 通知用語預覽（t62 S-X3）：POST 只為帶草稿範本，不寫任何資料 ──
    ("notify_templates.py", "POST", "/api/notify-templates/{event}/preview"):
        "preview：只在記憶體內驗證草稿範本並以樣本值渲染（NT.preview 不 commit、不寫任何資料）；僅最高管理者、builder_notify 旗標關閉時 404。",
    # ── 標示型規則預覽（t62 BP-2）：POST 只為帶草稿規則，不寫任何業務資料 ──
    ("rules.py", "POST", "/api/rules/preview"):
        "preview：只在記憶體內驗證草稿規則並對最近 N 筆唯讀評估（不 commit、不寫業務資料）；規則故障只走限頻的 rules.degraded 稽核（_note_degraded）；僅最高管理者、builder_rules／builder_governance 旗標關閉時 404。",
    # ── 選項清單預覽（census #4）：POST 只為帶草稿清單，不寫任何資料 ──
    ("option_lists.py", "POST", "/api/option-lists/{list_id}/preview"):
        "preview：只在記憶體內驗證草稿清單並回傳合併結果與用途說明，不開寫入、不 commit；僅最高管理者、設定 builder_option_lists 與建構器治理未同時開啟回 404",
    # ── 自訂按鈕預覽（t61 S6）：POST 只為帶草稿按鈕，不寫任何資料 ──
    ("user_buttons.py", "POST", "/api/user-buttons/{module}/{page}/preview"):
        "preview：只在記憶體內驗證並以指定身分渲染草稿按鈕（UB.preview 不 commit、不寫任何資料）；僅最高管理者、設定 builder_actions.enabled 關閉時 404。",
    # ── 選單建構器預覽（t59 BP-1）：POST 只為帶草稿 ops，不寫任何資料 ──
    ("platform_menu_preview.py", "POST", "/api/platform/menu/preview"):
        "preview：只在記憶體內驗證並渲染草稿 ops（helpers/menu_builder.preview 不開寫入、不 commit），不寫任何資料；僅最高管理者、設定 builder_menu.enabled 關著回 404",
    # ── 匯出範本預覽（BP-3）：POST 只為帶草稿範本，不寫任何資料 ──
    ("export_templates.py", "POST", "/api/export-templates/{export_id}/preview"):
        "preview：只在記憶體內驗證草稿範本並渲染前幾列，不開寫入、不 commit、不計匯出次數、不留 export 稽核；僅最高管理者、設定 builder_exports.enabled 關著回 404",
    # ── 階段樣板預覽（t62 S-ST2）：POST 只為帶草稿樣板，不寫任何資料 ──
    ("modules/case/api/quotations.py", "POST", "/api/quotations/stage-templates/preview"):
        "preview：只在記憶體內驗證草稿樣板（definition_problems）並以純函式 plan() 算出會建立哪些階段，不開寫入、不 commit、不碰任何案件；僅最高管理者、builder_stage_templates 旗標關閉時 404。真正套用的 apply-template 另有稽核。",
    # ── 轉簽（第54班）：稽核與換人同一個交易（直接 INSERT audit_log，寫不進去整個轉簽回滾），掃描器只認 _audit／_system_audit 呼叫 ──
    ("approval_queue.py", "POST", "/api/approval-queue/reassign"):
        "稽核 approval.reassign 在同一個交易內由端點直接寫入 audit_log（第 54 班強制稽核：寫不進去整個轉簽回滾，不再是 commit 之後吞錯誤的 _audit）；detail 上限與欄位推導沿用 _audit 的同一份規則",
    # ── 刪除暫存區（第53班）：稽核與刪除同一個交易，經 service.audit_tx 寫入（掃描器只認 _audit／_system_audit 呼叫）──
    ("modules/recyclebin/api.py", "POST", "/api/recycle-bin/delete-approved"):
        "稽核 recyclebin.delete_approved 在同一個交易內由 service.audit_tx 寫入（寫不進去整筆回滾，附件搬回）；端點本身不再另呼叫 _audit",
    # ── 權限矩陣（T67 PM-S3）：稽核與資料變更同一交易，由服務層寫入（掃描器只認端點本體的 _audit／_system_audit 呼叫）──
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/role-cap/preview"):
        "預覽端點只算影響面、不寫任何資料（服務層 preview_role_cap 唯讀），沒有東西可稽核",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/user-override/preview"):
        "預覽端點只算影響面、不寫任何資料（服務層 preview_user_override 唯讀），沒有東西可稽核",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/role-cap"):
        "稽核 permmatrix.role_cap.set 在同一個交易內由 service._audit_tx 寫入（寫不進去整筆回滾；高風險放寬走待生效時由設定帳本寫 permmatrix.pending.request）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/user-override"):
        "稽核 permmatrix.user_override.set 在同一個交易內由 service._audit_tx 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "DELETE", "/api/permmatrix/user-override"):
        "稽核 permmatrix.user_override.clear 在同一個交易內由 service._audit_tx 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/pending/{pid}/cancel"):
        "稽核 permmatrix.pending.cancel 在同一個交易內由 service 經 L.audit_event 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/pending/{pid}/approve"):
        "稽核 permmatrix.pending.approve 在同一個交易內由 service 經 L.audit_event 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/versions/{version_id}/restore"):
        "稽核 permmatrix.version.restore 在同一個交易內由 service._audit_tx 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    ("modules/permmatrix/api.py", "POST", "/api/permmatrix/undo"):
        "稽核由 service.undo_last_change 回溯到上一版時在同一個交易內經 _audit_tx 寫入（寫不進去整筆回滾）；端點本身不再另呼叫 _audit",
    # ── 職責角色（R2 第2步 8a）：稽核改在 helper 的同一交易內寫入 ──────────
    ("duty_roles.py", "POST", "/api/duty-roles"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "PUT", "/api/duty-roles/{role_id}"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "POST", "/api/duty-roles/bindings"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "POST", "/api/duty-roles/bindings/remove"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "POST", "/api/duty-roles/subtracts"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "POST", "/api/duty-roles/subtracts/remove"):
        "稽核在同一個交易內由 helpers/duty_roles._record→_write_audit 寫入（R2 第2步 8a：audit_log 與 permission_changes 同交易、audit_id 回填），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("duty_roles.py", "POST", "/api/duty-roles/preview"):
        "純試算：生效權限預覽（唯讀、superadmin），不寫任何資料表",
    ("modules/accounting/api/ledger_periods.py", "POST", "/opening/preview"):
        "純試算：期初餘額匯入前的預覽（逐列檢查借貸與科目），不寫任何資料表；建立批次的 POST /opening 有稽核",
    # ── 用 POST 的純查詢／試算（不改任何資料）────────────────────────────
    ("modules/subcontract/api/contractor_vouchers.py", "POST", "/api/contractor-vouchers/preview"):
        "純試算：分期匯款申請的金額試算（31-B），與建立同一支規則但不寫任何資料表；建立的 POST /api/contractor-vouchers 有稽核",
    ("modules/case/api/settlement_actuals.py", "POST", "/api/quotations/{quote_no}/settlement-actuals/preview"):
        "純試算：精算頁沖銷對應（尚未存檔）的預覽，與 GET 同權限同結果、只是對應清單放請求本文（上百筆不受網址長度限制）；不寫任何資料表；存檔的 PUT /settlement 有稽核",
    ("modules/case/api/quotations.py", "POST", "/api/quotations/case-activity"):
        "純查詢：回傳各案件最後動態時間，POST 只是為了帶一長串單號",
    ("modules/case/api/quotations.py", "POST", "/api/quotations/preview-html"):
        "純預覽：用表單內容組出 HTML 給預覽框，不存檔",
    ("modules/lodging/api_records.py", "POST", "/api/lodging/search"):
        "純查詢：只查本機旅宿快照回結果，不存（要存的是 POST /api/lodging/records，有稽核）",
    ("modules/netplan/api.py", "POST", "/api/network-plans/{plan_id}/topology-preview"):
        "純預覽：依送來的參數畫拓樸圖，不存檔",
    ("modules/netplan/api.py", "POST", "/api/network-plans-quick/preview"):
        "純預覽：快速拓樸的畫面預覽，沒有資料表",
    ("modules/payroll/api/bonus.py", "POST", "/cases/{quote_no}/preview"):
        "純試算：獎金分潤改比例／人員時即時重算（BN22），與存檔同一個 allocate()，不寫任何資料表",
    ("modules/netplan/api.py", "POST", "/api/network-plans-quick/pdf"):
        "即時產生 PDF 回傳下載，沒有資料表也不歸檔",
    ("modules/accounting/api/ledger_reports.py", "PUT", "/roles"):
        "T69：稽核在同一個交易內由 helpers/config_ledger.record 寫入（動作 ledger.role.request；變更明細＋稽核＋通知其他最高管理者同交易、寫不進去整筆回滾），端點本身不再另呼叫 _audit；此時尚未動 gl_account_roles",
    ("modules/accounting/api/ledger_reports.py", "POST", "/roles/pending/{pid}/approve"):
        "T69：稽核在同一個交易內由 helpers/config_ledger.audit_event 寫入（核准票 ledger.role.approve＋套用 ledger.role.put 與 gl_account_roles 變更同交易、失敗整筆回滾），端點本身不再另呼叫 _audit",
    ("modules/accounting/api/ledger_reports.py", "POST", "/roles/pending/{pid}/cancel"):
        "T69：稽核在同一個交易內由 helpers/config_ledger.audit_event 寫入（撤銷與 ledger.role.cancel 同交易、失敗整筆回滾），端點本身不再另呼叫 _audit",
    ("settings_center.py", "POST", "/api/settings-center/profiles/{name}/apply"):
        "稽核在同一個交易內由 helpers/config_ledger.record 寫入（每個群組各一次 publish，動作 settings.<group>.update／.pending），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("settings_center.py", "POST", "/api/settings-center/groups/{group}"):
        "稽核在同一個交易內由 helpers/config_ledger.record 寫入（第54班：audit_log＋config_changes＋定義新版本同交易，動作 settings.<group>.update），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("settings_center.py", "POST", "/api/settings-center/pending/{change_id}/cancel"):
        "稽核在同一個交易內由 helpers/config_ledger.audit_event 寫入（第54班：先 begin_write、撤銷與稽核同交易、寫不進去整筆回滾；動作 settings.<group>.pending_cancel），端點本身不再另呼叫 _audit",
    ("settings_center.py", "POST", "/api/settings-center/pending/{change_id}/approve"):
        "稽核在同一個交易內由 helpers/config_ledger.audit_event 寫入（第54班：先 begin_write、核准票與稽核同交易、寫不進去整筆回滾；動作 settings.<group>.approve），端點本身不再另呼叫 _audit",
    ("settings_center.py", "POST", "/api/settings-center/groups/{group}/preview"):
        "S1-4：預覽（dry-run）——只呼叫 settings_registry.plan，不寫任何資料表（測試斷言前後 config_changes／定義列數不變），沒有東西可稽核",
    ("settings_center.py", "POST", "/api/settings-center/groups/{group}/impact"):
        "S1-4：即時影響——唯讀連線（PRAGMA query_only）執行欄位的 impact_fn 並回傳數字，不寫任何資料表（測試斷言 impact_fn 想寫入會失敗）",
    ("settings_center.py", "POST", "/api/settings-center/groups/{group}/restore/{version}"):
        "S1-5：還原到某一版——稽核在同一個交易內由 helpers/config_ledger.audit_event 寫入（動作 settings.<group>.restore），還原本身走 settings_registry.publish（動作 settings.<group>.update／.pending）；端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("settings_center.py", "POST", "/api/settings-center/groups/{group}/reset"):
        "S1-4：還原預設——走 settings_registry.publish（與儲存同一條管制），稽核在同一個交易內由 helpers/config_ledger.record 寫入（動作 settings.<group>.update／.pending），端點本身不再另呼叫 _audit；失敗整筆回滾",
    ("system.py", "PATCH", "/api/settings/backup-retention"):
        "稽核在同一個交易內由 settings_registry.publish 寫入（動作 settings.retention.update／.pending），端點本身不再另呼叫 _audit，避免同一次變更兩列（test_legacy_retention_endpoint_writes_exactly_one_audit_row）",
    ("system.py", "POST", "/api/audit-log/module-counts"):
        "純查詢：選單紅色數字的計數（舊端點，前端已改用 /api/reads/module-counts）",
    ("modules/payroll/api/bonus.py", "POST", "/awards/plan/{quote_no}"):
        "純試算：分潤方案預覽，送審與核准才寫入（那些端點有稽核）",
    ("item_reads.py", "POST", "/api/reads/unread"):
        "純查詢：伺服器判斷哪些項目未讀，POST 只是為了帶一長串鍵",
    ("uploads.py", "POST", "/api/photo-token/batch"):
        "純讀取授權：換附件檢視簽章，不寫任何資料表；POST 只是為了帶一串路徑，同單張的 GET /api/photo-token（不稽核、trail 也略過）；被拒時由簽核詳情守門另記 audit（sec-p0 S1）",
    # ── 使用者自己的畫面偏好／已讀／心跳（不是業務資料）──────────────────
    ("list_prefs.py", "PUT", "/api/list-prefs/{list_key}"):
        "個人清單排序偏好，只影響自己的畫面",
    ("system.py", "PATCH", "/api/notifications/{notif_id}/read"):
        "個人通知的已讀旗標，每點一則一次，記稽核會淹沒紀錄",
    ("system.py", "PATCH", "/api/notifications/read-all"):
        "個人通知全部標為已讀，只影響自己的通知",
    ("item_reads.py", "POST", "/api/reads"):
        "個人逐筆已讀時間（未讀紅點），每點一筆一次，記稽核會淹沒紀錄",
    ("item_reads.py", "POST", "/api/reads/batch"):
        "個人已讀紀錄從瀏覽器一次性遷移到伺服器",
    ("system.py", "POST", "/api/edit-presence"):
        "同時編輯警示的心跳，每數秒一次，資料只在記憶體",
    ("system.py", "DELETE", "/api/edit-presence"):
        "同時編輯警示的釋放，資料只在記憶體",
    # ── 登入流程的暫時 challenge（不落地）────────────────────────────────
    ("auth.py", "POST", "/api/auth/webauthn/register/begin"):
        "只產生暫時 challenge 放在記憶體，不落地；完成註冊的端點才寫入並稽核",
    ("auth.py", "POST", "/api/auth/webauthn/login/begin"):
        "只產生暫時 challenge 放在記憶體，不落地；登入成功由 _issue_session 稽核",
    # ── 2026-09-26 P5／P8 建構器的檢查與預覽（只回結果，不存檔）──────────────
    ("definitions.py", "POST", "/api/definitions/{kind}/{key}/validate"):
        "純檢查：跑驗證器回問題清單，不存檔（存草稿、發布、還原各自稽核）",
    ("definitions.py", "POST", "/api/definitions/output_template/{key}/preview"):
        "純預覽：用樣本資料產生 HTML，不存檔",
    ("custom_records.py", "POST", "/api/custom-modules/formula/check"):
        "純檢查：公式語法檢查回錯誤位置，不存檔",
    ("custom_records.py", "POST", "/api/custom/{key}/compute"):
        "純試算：填單時即時算公式與明細列（與存檔同一套 clean_values），不存檔",
    ("custom_records.py", "POST", "/api/custom-modules/numbering/preview"):
        "純預覽：回編號範例，不佔用流水號、不存檔",
    ("custom_records.py", "POST", "/api/custom-modules/{key}/output/preview"):
        "純預覽：用樣本資料產生 HTML，不存檔",
    ("attachment_slots.py", "POST", "/api/attachment-slots/{doc_type}/simulate"):
        "純模擬（BP-4 S2）：判斷樣本檔收不收、顯示用路徑、誰能讀；不寫檔、不建資料夾、不存任何東西",
}

_VAGUE = {"", "不需要", "例外", "n/a", "na", "todo", "無", "略", "同上", "暫時"}


def _called(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def write_endpoints(source):
    """[(方法, 路徑, 函式節點)]：module 頂層、被 `@router.<寫入方法>(路徑)` 裝飾的函式。"""
    out = []
    for n in ast.parse(source).body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in WRITE_METHODS and isinstance(d.func.value, ast.Name)
                    and d.func.value.id in ("router", "app")
                    and d.args and isinstance(d.args[0], ast.Constant)):
                out.append((d.func.attr.upper(), d.args[0].value, n))
    return out


def is_audited(fn):
    return bool(_called(fn) & (AUDIT_CALLS | set(AUDIT_WRAPPERS)))


def _key(f):
    # routers/ 沿用檔名（EXEMPT 既有鍵）；模組的 api.py 同名，用 modules/<key>/api.py
    r = source_tree.rel(f)
    return r if r.startswith("modules/") else os.path.basename(f)


def _extra_router_files():
    """模組裡 `api.py`／`api/` 以外、卻定義端點的檔（例：lodging 的 api_records.py）——第一版只掃 router_files()，這些端點整個不在守門範圍（W1c 稽核）。"""
    out = []
    for p in source_tree.logic_files():
        if source_tree.rel(p).startswith("modules/") and "@router." in open(p, encoding="utf-8").read():
            out.append(p)
    return out


def _all():
    rows = []
    for f in list(source_tree.router_files()) + _extra_router_files():
        src = open(f, encoding="utf-8").read()
        for method, path, fn in write_endpoints(src):
            rows.append((_key(f), method, path, fn))
    return rows


def test_every_write_endpoint_writes_an_audit_record_or_is_exempt_with_a_reason():
    missing = ["%s:%d %s %s（%s）" % (f, fn.lineno, m, p, fn.name)
               for f, m, p, fn in _all()
               if not is_audited(fn) and (f, m, p) not in EXEMPT]
    assert not missing, (
        "這些寫入端點成功時不寫稽核（`_audit`／`_system_audit`）：\n  " + "\n  ".join(missing)
        + "\n⇒ 補呼叫；真的不寫業務資料的才列 EXEMPT 並寫原因。")


def test_exempt_entries_point_at_endpoints_that_exist():
    live = {(f, m, p) for f, m, p, _ in _all()}
    # 模組資料夾被拿掉（選配／反向控制）時，它的例外條目不算幽靈
    ghosts = sorted(k for k in set(EXEMPT) - live if source_tree.module_installed(k[0]))
    assert not ghosts, "EXEMPT 列了不存在的端點（改名或刪了要一起清）：%s" % ghosts


def test_exempt_entries_that_now_audit_are_removed():
    """列了例外、而它其實已經寫稽核 ⇒ 例外清單在說謊，拿掉。"""
    stale = sorted((f, m, p) for f, m, p, fn in _all() if (f, m, p) in EXEMPT and is_audited(fn))
    assert not stale, "這些端點已經寫稽核，請從 EXEMPT 移除：%s" % stale


def test_exempt_reasons_are_specific():
    vague = sorted(k for k, why in EXEMPT.items()
                   if (why or "").strip().lower() in _VAGUE or len((why or "").strip()) < 12)
    assert not vague, "EXEMPT 的原因太空泛（要寫出「為什麼不是業務資料」）：%s" % vague


def test_audit_wrappers_really_call_audit_directly():
    for name, (rel, _why) in AUDIT_WRAPPERS.items():
        tree = ast.parse(open(os.path.join(BE, rel), encoding="utf-8").read())
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        assert fns, "AUDIT_WRAPPERS 的 %s 在 %s 找不到" % (name, rel)
        assert _called(fns[0]) & AUDIT_CALLS, "%s 沒有直接呼叫 _audit／_system_audit" % name


def test_a_wrapper_that_does_not_call_audit_is_caught_by_the_direct_call_check():
    """反向控制（31-A）：把包裝函式裡的 `_audit` 拿掉 ⇒ 「直接呼叫」檢查必須紅（檢查本身不是空的）。"""
    good = "def dispatch_review_submit(x):\n    do()\n    _audit(t, 'a')\n"
    bad = "def dispatch_review_submit(x):\n    do()\n"
    for src, expect in ((good, True), (bad, False)):
        fn = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)][0]
        assert bool(_called(fn) & AUDIT_CALLS) is expect


def test_refusal_only_audit_helper_does_not_count():
    """`_deny_if_case_locked_unsupported()` 只在**拒絕**時寫 audit ⇒ 不可以列成包裝函式。"""
    assert "_deny_if_case_locked_unsupported" not in AUDIT_WRAPPERS


def test_the_scanner_sees_what_it_should():
    """量尺：真的掃得到端點；認得出有稽核的；認得出沒有稽核的；不被字串騙。"""
    rows = _all()
    # 掃到的寫入端點數對照一個獨立量法（直接數 @router.post/put/patch/delete）——不綁任何一個 L2 模組的端點數
    import re as _re
    from core import source_tree as _st
    n_decorated = sum(len(_re.findall(r"@router\.(post|put|patch|delete)\(", p.read_text(encoding="utf-8")))
                      for p in _st.router_files())
    assert n_decorated > 0 and len(rows) >= 0.95 * n_decorated, (len(rows), n_decorated)
    by = {(f, m, p): fn for f, m, p, fn in rows}
    # 正對照用 L1 端點；M11 自己的那一條在 modules/tender_radar/tests/
    assert is_audited(by[("approval_delegates.py", "POST", "/api/approval-delegates")])
    src = (
        "@router.post('/x')\n"
        "def a():\n"
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "    s = '_audit(token, \"fake\")'  # 字串與註解裡的 _audit( 不算\n"
        "@router.delete('/y')\n"
        "def b():\n"
        "    _audit(tok, 'y.delete')\n"
        "@router.get('/z')\n"
        "def c():\n"
        "    pass\n")
    eps = {p: fn for _m, p, fn in write_endpoints(src)}
    assert set(eps) == {"/x", "/y"}
    assert not is_audited(eps["/x"])
    assert is_audited(eps["/y"])


# ── 行為：補上的呼叫真的寫進 audit_log ───────────────────────────────────

def _hdr(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_rows(action):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        conn.close()


def test_creating_a_work_log_leaves_an_audit_record(client, make_user):
    h = _hdr(client, make_user, "alice")
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
    conn.close()
    r = client.post("/api/work-logs", json={"log_date": "2026-09-24", "user_id": uid,
                                            "content": "巡檢"}, headers=h)
    assert r.status_code == 200, r.text
    rows = _audit_rows("work_log.create")
    assert len(rows) == 1 and rows[0]["username"] == "alice"
    assert rows[0]["target_id"] == str(r.json()["id"])


def test_totp_setup_is_audited_without_the_secret(client, make_user):
    h = _hdr(client, make_user, "alice")
    r = client.post("/api/auth/totp/setup", headers=h)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    rows = _audit_rows("auth.totp_setup")
    assert len(rows) == 1
    assert secret not in (rows[0]["detail"] + rows[0]["target_label"] + rows[0]["target_id"])


def test_no_endpoint_file_escapes_the_scan():
    """守門自己的守門（W1c）：任何產品檔只要有 `@router.<方法>(` 裝飾器，就必須在本守門掃描範圍內，
    否則整個檔案的寫入端點都不受「必須寫稽核」管轄（lodging/api_records.py 曾是這樣漏掉的）。
    已知例外：`helpers/xlsx_out.py`（匯出包裝器，端點由 export_logged 以稽核包裝）、`main.py`（只有 GET 的靜態頁面）。"""
    scanned = {source_tree.rel(p) for p in list(source_tree.router_files()) + _extra_router_files()}
    allowed = {"helpers/xlsx_out.py", "main.py"}
    pat = re.compile(r"^@(?:router|app)\.(?:get|post|put|patch|delete|api_route)\(", re.M)
    stray = []
    for p in source_tree.product_files():
        r = source_tree.rel(p)
        if r in scanned or r in allowed:
            continue
        if pat.search(open(p, encoding="utf-8").read()):
            stray.append(r)
    assert not stray, "這些檔定義了端點卻不在稽核守門的掃描範圍：%s" % sorted(stray)
