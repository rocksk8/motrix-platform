"""操作軌跡（`user_request_log`）的共用設定，以及把路徑翻成人話的對照表。

2026-09-15 使用者要求：「在更直覺的語言，在線時數統計的操作軌跡，要能篩選每個
使用者」。原本軌跡表把 `GET /api/quotations/MQ-202607-047/finance-summary` 跟
HTTP 狀態碼 `403` 直接攤在畫面上——那是寫程式的人看的東西，不是要看「誰做了
什麼」的人看的東西。

**為什麼獨立成一個模組**：寫入端（`main.py` 的中介層）跟讀取端
（`routers/system.py` 的軌跡端點）必須共用同一份「什麼不該記」的清單。放在
main.py 會讓 router 反過來 import main（循環匯入）；各自複製一份則遲早不同步
——那一刻讀取端就會把寫入端早就決定要藏的東西露出來。

**翻譯原則沿用 2026-09-14 的決定：不猜。** 對不到的模組或路徑段一律原樣顯示
原始字串，不用相近的字硬湊——猜錯的標籤比看得懂的原始路徑更誤導人。
"""
import re


# ── 一、不記進軌跡的端點 ─────────────────────────────────────────────────
#
# 判斷標準是「**前端會自動打、不是人按的**」，不是「不重要」。
SKIP_PREFIXES = (
    # 輪詢與守門（2026-09-14 原有清單）
    "/api/ping",
    "/api/auth/me",
    "/api/notifications",
    "/api/audit-log/module-counts",
    "/api/online-users",
    "/api/system/version",
    "/api/system/deployed-version",
    "/api/now",
    "/api/uploads/",          # 圖片／附件載入，一頁可能幾十個
    "/api/photo-token",
    # 2026-09-15 補上。實測正式資料 1577 筆軌跡裡，這三支加上 `/selectable`
    # 共 485 筆（31%）——全是頁面自己打的，人一次都沒按過：
    "/api/edit-presence",            # 同時編輯心跳，每 30 秒一次（95 筆）
    "/api/approval-queue/count",     # 側欄簽核紅點的數字（77 筆）
    "/api/list-prefs",               # 清單欄位／篩選偏好，開頁自動讀寫（196 筆）
    # 這支是「POST 當查詢用」：案件管理清單開頁時一次問完所有案件有沒有新動態
    # （quotations.py::case_activity）。它是 POST 但沒有改任何東西，留著只會在
    # 軌跡上長出一排「新增案件動態」——說的還是反的（34 筆）。
    "/api/quotations/case-activity",
)

# 結尾是這些的路徑也不記：下拉選單的資料來源，開頁就自動撈（117 筆）。
SKIP_SUFFIXES = ("/selectable",)

# 同一個人對同一個目標的連續請求，這個秒數內只記一次。
DEDUPE_SECONDS = 30


def should_skip(path: str) -> bool:
    """這條請求該不該被丟掉（寫入端與讀取端共用，舊資料也一併藏起來）。"""
    p = (path or "").split("?")[0]
    return p.startswith(SKIP_PREFIXES) or p.endswith(SKIP_SUFFIXES)


# ── 二、模組名（路徑第一段）────────────────────────────────────────────
#
# 這份表涵蓋目前所有 `/api/<第一段>`（用 routers 的 decorator 掃出來的，不是憑
# 印象列的）。新增模組沒補進來也不會壞：對不到就原樣顯示 `/api/<第一段>`。
MODULE_LABELS = {
    "access-guide":         "門禁系統選型導覽",
    "approval-delegates":   "簽核代理人",
    "approval-history":     "簽核歷史",
    "approval-queue":       "簽核佇列",
    "audit-log":            "歷史紀錄",
    "auth":                 "帳號安全",
    "automation-guide":     "自動化系統選型導覽",
    "case-changes":         "案件變更申請",
    "cashier":              "出納",
    "company":              "公司資料",
    "completion-notes":     "完工單",
    "contractor-dispatches": "外包派工",
    "contractor-vouchers":  "承攬商匯款申請",
    "contractors":          "外包人員",
    "customers":            "客戶",
    "daily-tasks":          "每日工作事項",
    "dashboard":            "營運儀表板",
    "dev-cases":            "業務開發案",
    "dev-crm":              "業務開發",
    "dev-logs":             "業務開發紀錄",
    "devices":              "設備",
    "edit-presence":        "同時編輯狀態",
    "env-guide":            "場域選型導覽",
    "gateway-guide":        "閘道器與控制器選型導覽",
    "inventory":            "庫存",
    "invoice-vouchers":     "開票申請",
    "legal-params":         "法規參數",
    "list-prefs":           "清單欄位偏好",
    "materials-summary":    "材料彙總",
    "module-versions":      "版本紀錄",
    "monitor-guide":        "監控系統選型導覽",
    "netarch-guide":        "網路架構選型導覽",
    "network-plans":        "網路架構規劃書",
    "network-plans-quick":  "快速拓樸圖",
    "next-quote-no":        "下一個報價單號",
    "next-slip-no":         "下一個單號",
    "notifications":        "通知",
    "now":                  "伺服器時間",
    "online-users":         "在線名單",
    "org":                  "組織架構",
    "parts":                "料號",
    "payment-requests":     "請款單",
    "payslips":             "勞報單",
    "quotations":           "報價單／案件",
    "reports":              "營運報表",
    "sales-orders":         "銷售訂單",
    "search":               "全站搜尋",
    "settings":             "系統設定",
    "shipping-notes":       "出貨單",
    "suppliers":            "供應商",
    "switch-guide":         "網路交換器選型導覽",
    "system":               "系統",
    "tax-rules":            "稅務規則",
    "uploads":              "附件",
    "user-activity":        "在線時數統計",
    "users":                "使用者",
    "vendor-contractors":   "承攬商",
    "work-logs":            "工作日誌",
}

# 這些模組不是「一批資料」而是「一個畫面／一份設定」，列表請求不加「清單」二字
# ——「查看營運儀表板清單」是不存在的東西。
SINGLETON_MODULES = {
    "approval-history", "approval-queue", "audit-log", "auth", "cashier", "company",
    "dashboard", "dev-crm", "inventory", "materials-summary", "module-versions",
    "network-plans-quick", "next-quote-no", "next-slip-no", "now", "online-users",
    "org", "reports", "search", "settings", "system", "tax-rules", "legal-params", "user-activity",
    "access-guide", "automation-guide", "env-guide", "gateway-guide", "monitor-guide",
    "netarch-guide", "switch-guide",
}


# ── 三、路徑段 → 人話（名詞）─────────────────────────────────────────────
SEGMENT_LABELS = {
    "action-items":      "待辦事項",
    "active":            "啟用狀態",
    "activity-stats":    "活動統計",
    "approval-flow":     "簽核流程",
    "archive":           "封存",
    "assigned-users":    "負責人",
    "assignees":         "負責人",
    "batches":           "進貨批次",
    "case-activity":     "案件動態",
    "case-lock":         "案件鎖定",
    "case-record":       "案件紀錄",
    "case-unlock":       "案件解鎖",
    "categories":        "分類",
    "change-request":    "變更申請",
    "closing-report-pdf": "結案報告 PDF",
    "credentials":       "實體金鑰",
    "custom-roles":      "自訂角色",
    "customer-history":  "客戶歷史",
    "daily-task-password": "每日工作密碼",
    "deal-tag":          "成交標記",
    "departments":       "部門",
    "depends-on":        "前置關係",
    "detail":            "明細",
    "divisions":         "事業處",
    "edit-log":          "編輯紀錄",
    "environments":      "場域",
    "expenses-monthly":  "月支出",
    "extra-expenses":    "額外支出",
    "families":          "產品系列",
    "files":             "附件",
    "finance-summary":   "財務彙總",
    "financial":         "財務報表",
    "fit":               "適配建議",
    "gate-matrix":       "關卡矩陣",
    "generations":       "產品世代",
    "history":           "歷史",
    "id-card":           "身分證影像",
    "invoice-files":     "發票附件",
    "issued-files":      "開票附件",
    "links":             "關聯",
    "login":             "登入",
    "logs":              "紀錄",
    "material-orders":   "材料採購",
    "materials":         "材料",
    "network-plan":      "網路架構規劃書",
    "parts-summary":     "料號彙總",
    "passbook":          "存摺影像",
    "payable-queue":     "應付佇列",
    "payment":           "收付款",
    "payment-terms":     "付款條件",
    "pending":           "待處理",
    "photos":            "照片",
    "products":          "產品",
    "project-report-pdf": "專案報告 PDF",
    "qr-info":           "掃碼登入",
    "qr-status":         "掃碼登入狀態",
    "receivable-queue":  "應收佇列",
    "receivables-monthly": "月應收",
    "recommendations":   "選型建議",
    "recovery-codes":    "備援碼",
    "role-labels":       "角色名稱",
    "scenarios":         "情境",
    "signed-files":      "回簽附件",
    "stage-board":       "案件執行看板",
    "stages":            "案件階段",
    "status":            "狀態",
    "stock-items":       "庫存品項",
    "t100-export":       "T100 匯出",
    "topology-preview":  "拓樸預覽",
    "totp":              "兩步驟驗證",
    "trail":             "操作軌跡",
    "tree":              "組織架構",
    "updates":           "更新記錄",
    "versions":          "版本",
    "visits":            "拜訪紀錄",
    "vouchers":          "憑證",
    "webauthn":          "實體金鑰",
}


# ── 四、路徑最後一段是「動作」時，整句用它當動詞 ─────────────────────────
#
# `{}` 是受詞要擺的位置。**中文的動賓順序不是每個動作都一樣**，全部用「動詞＋
# 受詞」硬拼會拼出「解鎖密碼使用者 #9」「轉為案件業務開發案 #90」這種句子。
# 沒有 `{}` 的是本身就講完了的動作（例：修改密碼）。
ACTION_LABELS = {
    "accept":               "接受{}",
    "adjust":               "調整{}",
    "approve":              "核准{}",
    "approve-delete":       "核准刪除{}",
    "approve-relink-quote": "核准{}重新連結報價單",
    "approve-writeoff":     "核准{}的沖帳",
    "begin":                "開始{}",
    "cancel-delete":        "取消{}的刪除申請",
    "cancel-relink-quote":  "取消{}重新連結報價單",
    "cancel-writeoff":      "取消{}的沖帳",
    "change-password":      "修改密碼",
    "complete":             "把{}標記完成",
    "confirm":              "確認{}",
    "convert":              "將{}轉為案件",
    "deactivate":           "停用{}",
    "disable":              "停用{}",
    "enable":               "啟用{}",
    "download":             "下載{}",
    "export":               "匯出{}",
    "import-to-quote":      "把{}匯入報價單",
    "paid-toggle":          "切換{}的付款狀態",
    "pdf-download":         "下載{}的 PDF",
    "preview":              "預覽{}",
    "qr-approve":           "核准掃碼登入",
    "read":                 "把{}標記已讀",
    "recall":               "抽回{}",
    "regenerate":           "重新產生{}",
    "reject":               "駁回{}",
    "reject-final":         "最終駁回{}",
    "reorder":              "重新排序{}",
    "request-delete":       "申請刪除{}",
    "request-relink-quote": "申請{}重新連結報價單",
    "request-writeoff":     "為{}申請沖帳",
    "revoke-approval":      "撤回{}的核准",
    "setup":                "設定{}",
    "signed-toggle":        "切換{}的回簽狀態",
    "submit":               "送審{}",
    "test":                 "測試{}",
    "unconfirm":            "取消確認{}",
    "unlock-password":      "解鎖{}的密碼",
}

# 最後兩段合起來才是一個動作的（單看 `excel` 會翻成莫名其妙的句子）。
ACTION_PAIRS = {
    ("export", "excel"):   "把{}匯出成 Excel",
    ("export", "pdf"):     "把{}匯出成 PDF",
    ("import", "excel"):   "從 Excel 匯入{}",
    ("history", "export"): "匯出{}的歷史",
}

# 最後兩段合起來才是一個完整名詞的（分開翻會變成「實體金鑰／實體金鑰」）。
NOUN_PAIRS = {
    ("totp", "status"):          "兩步驟驗證狀態",
    ("totp", "recovery-codes"):  "兩步驟驗證備援碼",
    ("webauthn", "credentials"): "實體金鑰",
}

# 這些段的名稱本身就說完了要說的事，前面再掛模組名只是變長：
# 「查看報價單／案件的案件執行看板」→「查看案件執行看板」。
NO_MODULE_SEGMENTS = {"stage-board"}

# 歸類用：畫面要靠顏色分辨「只是看看」還是「動了資料」。
_APPROVAL_ACTIONS = {
    "submit", "approve", "reject", "reject-final", "revoke-approval", "recall",
    "request-delete", "approve-delete", "cancel-delete", "request-writeoff",
    "approve-writeoff", "cancel-writeoff", "request-relink-quote",
    "approve-relink-quote", "cancel-relink-quote", "qr-approve",
}
_EXPORT_ACTIONS = {"download", "export", "pdf-download", "preview",
                   "export-excel", "export-pdf", "history-export"}

KIND_LABELS = {
    "view":    "檢視",
    "change":  "變更",
    "delete":  "刪除",
    "approve": "簽核",
    "export":  "匯出",
}

_VERBS = {"GET": "查看", "POST": "新增", "PUT": "修改", "PATCH": "修改", "DELETE": "刪除"}


# 看起來像「編號」的路徑段：純數字、MQ-202607-047 這類單號、或檔案的 hex id。
# 認不出來就當成「名稱段」處理——寧可把 stage-board 當名稱，也不要把它當成
# 某張報價單的編號印在畫面上。
_ID_RE = re.compile(r"^(?:[0-9]+|[A-Z]{1,4}-[0-9]{4,8}-[0-9]{1,6}|[0-9a-f]{8,})$")
_RECORD_RE = re.compile(r"^/api/([a-z0-9-]+)/([^/?]+)(/.*)?$")


def looks_like_id(seg: str) -> bool:
    return bool(_ID_RE.match(seg or ""))


def pretty_id(seg: str) -> str:
    return "#" + seg if (seg or "").isdigit() else seg


def module_label(key: str) -> str:
    return MODULE_LABELS.get(key, "/api/" + key)


def segment_label(seg: str) -> str:
    return SEGMENT_LABELS.get(seg, seg)


def _cjk(ch: str) -> bool:
    """這個字元是不是中文（含全角標點）——決定要不要補空格。"""
    return bool(ch) and ord(ch[0]) >= 0x2E80


def _cat(*parts) -> str:
    """把幾段文字接起來，中文與英數字的交界補一個空格。

    不補的話會出現「#90的紀錄」「查看/api/foo清單」這種黏在一起的句子；中文之間
    則不能補，「查看 報價單」讀起來像斷句。
    """
    out = ""
    for part in parts:
        if not part:
            continue
        if out and (_cjk(out[-1]) != _cjk(part[0])):
            out += " "
        out += part
    return out


# ── 五、一次點擊打出一串 GET → 收斂成一列 ───────────────────────────────
#
# 既有的 30 秒去重擋的是「同一支端點被連打」，擋不掉「一個動作打好幾支**不同**
# 端點」：開一張案件會同時撈 finance-summary / material-orders / extra-expenses /
# updates…，一次點擊在軌跡上留六列長得幾乎一樣的紀錄。那是同一件事，不是六件。
#
# 兩個限制，都是為了「寧可多留一列，也不要把真的動作藏起來」：
# 1. **只收斂 GET**：開頁的連鎖請求一定是 GET，而 POST／PUT／DELETE 每一筆都是
#    真的動作（例如刪掉一筆額外支出），少記一筆就是稽核漏洞。
# 2. **子路徑用白名單而不是黑名單**：白名單漏掉一項，結果只是多幾列重複的紀錄；
#    黑名單漏掉一項，就會把「查看某人的身分證影像」這種事藏進「開啟外包人員 #3」
#    裡面——後者是不能接受的失敗方式。
_FANOUT_GROUPS = (
    # 開頁一次撈完的 widget。路徑逐一列出而不用前綴：日後多一支
    # /api/dashboard/export 這種真的動作時，不會被一起吞掉。
    ("/api/dashboard", "開啟營運儀表板", (
        "/api/dashboard/stats", "/api/dashboard/monthly",
        "/api/dashboard/expenses-monthly", "/api/dashboard/ops-alerts",
        "/api/dashboard/funnel", "/api/dashboard/activity-feed",
    )),
    ("/api/reports", "查看營運報表", (
        "/api/reports/financial", "/api/reports/receivables-monthly",
        "/api/reports/expenses-monthly",
    )),
)

# 開一筆單據時，頁面會順手撈的子資源。
_FANOUT_SUBS = {
    "finance-summary", "material-orders", "extra-expenses", "updates", "action-items",
    "logs", "stages", "assignees", "assigned-users", "visits", "case-record",
}


def collapse_group(method, path):
    """回傳 `(群組基準路徑, 群組說明)`，不屬於任何群組就回 None。

    基準路徑給寫入端拿去比對「這個群組最近是不是剛記過」，條件要寫成
    「path 等於基準，或 path 以基準加一條斜線開頭」兩段——**不能只用
    LIKE 基準+百分號**，那會讓 `/api/dev-cases/1` 的樣式吃掉
    `/api/dev-cases/12/logs`，變成開了 12 號卻被算進 1 號的群組。
    """
    if (method or "").upper() != "GET":
        return None
    p = (path or "").split("?")[0]
    for base, summary, members in _FANOUT_GROUPS:
        if p in members:
            return base, summary
    m = _RECORD_RE.match(p)
    if not m or not looks_like_id(m.group(2)):
        return None
    sub = [s for s in (m.group(3) or "").split("/") if s]
    if sub and sub[0] not in _FANOUT_SUBS:
        return None
    if any(s in ACTION_LABELS for s in sub):
        return None
    base = "/api/%s/%s" % (m.group(1), m.group(2))
    return base, _cat("開啟", module_label(m.group(1)), pretty_id(m.group(2)))


# ── 六、一句話說明這筆軌跡 ───────────────────────────────────────────────

def describe(method: str, path: str) -> dict:
    """把 `method + path` 翻成一句人看得懂的話。

    回傳 `summary`（一句話）、`module`（模組名，沿用舊欄位 `label` 的內容）、
    `kind`／`kindLabel`（檢視／變更／刪除／簽核／匯出，畫面用來上色）。
    """
    method = (method or "").upper()
    p = (path or "").split("?")[0]
    segs = [s for s in p.split("/") if s]

    # 不是 /api/... 開頭（理論上不會發生）→ 原樣顯示，不硬翻。
    if len(segs) < 2 or segs[0] != "api":
        kind = "view" if method == "GET" else "change"
        return {"module": "", "summary": _cat(_VERBS.get(method, method), p),
                "kind": kind, "kindLabel": KIND_LABELS[kind], "grouped": False}

    mod_key = segs[1]
    module = module_label(mod_key)
    rest = segs[2:]

    group = collapse_group(method, p)
    if group:
        return {"module": module, "summary": group[1], "kind": "view",
                "kindLabel": KIND_LABELS["view"], "grouped": True}

    # 尾端的動作段先抽掉，剩下的才是受詞。
    action, action_key = None, ""
    if len(rest) >= 2 and (rest[-2], rest[-1]) in ACTION_PAIRS:
        action = ACTION_PAIRS[(rest[-2], rest[-1])]
        action_key = rest[-2] + "-" + rest[-1]
        rest = rest[:-2]
    elif rest and rest[-1] in ACTION_LABELS:
        action = ACTION_LABELS[rest[-1]]
        action_key = rest[-1]
        rest = rest[:-1]

    if len(rest) >= 2 and (rest[-2], rest[-1]) in NOUN_PAIRS:
        rest = rest[:-2] + [NOUN_PAIRS[(rest[-2], rest[-1])]]

    # 受詞照路徑順序組：編號掛在它前面那個名詞上，不是一律掛給模組。
    # `/api/inventory/stock-items/5/adjust` 的 5 是庫存品項的編號，不是庫存的。
    drop_module = any(s in NO_MODULE_SEGMENTS for s in rest)
    nodes = [] if drop_module else [[module, ""]]
    for seg in rest:
        if looks_like_id(seg):
            if nodes and not nodes[-1][1]:
                nodes[-1][1] = pretty_id(seg)
            else:
                nodes.append(["", pretty_id(seg)])
        else:
            nodes.append([segment_label(seg), ""])

    # 相鄰兩段翻出來一樣就只留一個：`/api/org/tree` 兩段都是「組織架構」。
    merged = []
    for name, num in nodes:
        if merged and name and name == merged[-1][0]:
            merged[-1][1] = merged[-1][1] or num
            continue
        merged.append([name, num])

    text = ""
    for i, (name, num) in enumerate(merged):
        piece = _cat(name, num) if (name and num) else (name or num)
        text = piece if i == 0 else _cat(text, "的", piece)

    if not rest and not action and method == "GET" and mod_key not in SINGLETON_MODULES:
        text = _cat(text, "清單")

    if action is None:
        summary = _cat(_VERBS.get(method, method), text)
    elif "{}" in action:
        head, _, tail = action.partition("{}")
        summary = _cat(head, text, tail)
    else:
        summary = _cat(action, text)

    if method == "DELETE":
        kind = "delete"
    elif action_key in _APPROVAL_ACTIONS:
        kind = "approve"
    elif action_key in _EXPORT_ACTIONS:
        kind = "export"
    elif method == "GET":
        kind = "view"
    else:
        kind = "change"

    return {"module": module, "summary": summary, "kind": kind,
            "kindLabel": KIND_LABELS[kind], "grouped": False}


# ── 七、HTTP 狀態碼 → 人話 ───────────────────────────────────────────────
STATUS_LABELS = {
    200: "成功", 201: "已建立", 204: "成功",
    304: "沒有變更",
    400: "資料有誤", 401: "需要重新登入", 403: "沒有權限（被擋下）",
    404: "找不到資料", 409: "有人剛改過（衝突）", 413: "檔案太大",
    422: "資料格式有誤", 429: "操作太頻繁",
}


def status_label(status) -> str:
    try:
        s = int(status or 0)
    except (TypeError, ValueError):
        return ""
    if s in STATUS_LABELS:
        return STATUS_LABELS[s]
    if 200 <= s < 300:
        return "成功"
    if 300 <= s < 400:
        return "轉向"
    if s >= 500:
        return "系統錯誤"
    if s >= 400:
        return "失敗（%d）" % s
    return ""


def status_ok(status) -> bool:
    try:
        return 200 <= int(status or 0) < 400
    except (TypeError, ValueError):
        return False


# ── 八、頁面檔名 → 頁名 ─────────────────────────────────────────────────
#
# 軌跡的 `page` 欄位來自 Referer，存的是檔名。這份表是從各頁 `<title>` 抓出來的
# ——對不到就原樣顯示檔名，新增頁面忘了補這裡不會壞掉，只是少一點可讀性。
PAGE_LABELS = {
    "access-guide.html": "門禁系統選型導覽",
    "approval-delegates.html": "簽核代理人",
    "approval-history.html": "簽核歷史",
    "approval-queue.html": "簽核佇列",
    "approval-settings.html": "簽核設定",
    "audit-log.html": "歷史紀錄",
    "automation-guide.html": "自動化系統選型導覽",
    "case-management.html": "案件管理",
    "case-stage-board.html": "案件執行看板",
    "cashier.html": "出納",
    "change-password.html": "修改密碼",
    "company-profile-settings.html": "公司資料設定",
    "completion-note-form.html": "完工單",
    "contractor-voucher-approval-settings.html": "承攬商匯款申請簽核設定",
    "contractors.html": "外包名冊",
    "customer-log.html": "客戶日誌",
    "customers.html": "客戶管理",
    "daily-tasks.html": "每日工作事項",
    "dev-crm.html": "業務開發",
    "devices.html": "設備登載",
    "env-guide.html": "場域選型導覽",
    "gateway-guide.html": "閘道器與控制器選型導覽",
    "google-calendar-settings.html": "Google 行事曆設定",
    "index.html": "營運儀表板",
    "inventory.html": "庫存管理",
    "login-qr-approve.html": "核准登入",
    "login.html": "登入",
    "module-versions.html": "版本紀錄",
    "monitor-guide.html": "監控系統選型導覽",
    "netarch-guide.html": "網路架構選型導覽",
    "network-plan-form.html": "網路架構規劃書",
    "network-plans.html": "網路架構規劃書",
    "notification-settings.html": "通知設定",
    "online-stats.html": "在線時數統計",
    "org-structure.html": "組織架構設定",
    "parts.html": "料號主檔",
    "payment-request-form.html": "請款單開立",
    "payslip-form.html": "勞報單開立",
    "payslips.html": "勞報單",
    "procurement.html": "採購管理",
    "quotation-form.html": "報價單",
    "quotations.html": "報價單管理",
    "receivables.html": "應收帳款",
    "reports.html": "營運報表",
    "sales-orders.html": "銷售訂單",
    "schema-status.html": "Schema 狀態",
    "selection-db-overview.html": "選型資料庫涵蓋度總覽",
    "settlement.html": "成本精算",
    "shipping-export-history.html": "出貨單歷史紀錄",
    "supplier-log.html": "供應商日誌",
    "suppliers.html": "供應商管理",
    "switch-guide.html": "網路交換器選型導覽",
    "topology-quick.html": "快速拓樸圖產生器",
    "users.html": "使用者管理",
    "vendor-contractors.html": "承攬商管理",
    "warranty.html": "保固追蹤",
    "work-log.html": "工作日誌",
}


def page_label(page: str) -> str:
    p = (page or "").strip()
    if not p:
        return ""
    return PAGE_LABELS.get(p, p)
