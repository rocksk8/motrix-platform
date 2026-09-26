"""「待我簽核」佇列與轉簽的共用形狀（L1；M01-PLAN §3-7，2026-09-26）。

佇列（`/api/approval-queue`、`/count`）與轉簽（`/api/approval-queue/reassign`）是 M01 的彙整端點，但單據是各模組的：
- `approval.queue_items`（IP-10）：每個單據模組提供 `fn(conn) -> [item, …]`，只列自己「待審核／簽核中」的單。
  item 形狀見 `base_item()`；M01 只彙整、過濾可見性、分組。
- `approval.reassign`（新 IP，列車定號）：provider 名稱＝單據類型（`type`），物件有兩個方法——
  `load(conn, doc_no) -> dict | None`：{"docNo", "quoteNo", "status", "approval"}；找不到 ⇒ None；
      簽核資料讀不出來 ⇒ raise `ApprovalUnreadable`（fail-closed：不可以吞成空鏈，那與「沒設定流程」一樣）
  `save(conn, doc, approval, now)`：`doc` 是 `load` 的回傳值；寫回整個 approval。
- `approval.detail`（新 IP，列車定號）：provider 名稱＝單據類型，`fn(conn, doc_no) -> dict | None`：
  {"quoteNo", "approvalRaw"（含 approval 的原始 JSON，給 M01 判斷可見性與金額遮蔽）, "title"（可省）, "fields", "items", "files"}；
  找不到 ⇒ None。每案權限、案件抬頭、金額遮蔽都在 M01（`/api/approval-queue/detail`）。
  權限、原因必填、換人規則、audit、通知都在 M01；擁有者只負責「讀出簽核鏈、寫回簽核鏈」。
  沒有提供者的類型 ⇒ 不給轉簽（佇列回 `reassignTypes`，前端據此顯示按鈕）。

本檔不讀任何模組的表：表名由擁有者傳進 `DataJsonApproval`。
"""
import json


#: 「還在簽」的單據狀態（各單據表共用的兩個字）
ACTIVE_STATUSES = ("待審核", "簽核中")


def active_tiers(appr: dict) -> list:
    """簽核鏈的層級；舊資料只有 `steps`（單人循序）⇒ 轉成單人層（2026-09-26 自 M01 `routers/quotations._active_tiers` 下沉，
    M01 保留同名別名）。⚠️ 與 `helpers.tiered_approval.active_tiers` 不同：那支不做 steps 相容。
    系統設定讀取端 `routers/system._normalize_flow()` 有平行的相容邏輯，改 tiers 結構時兩邊一起改。"""
    tiers = appr.get("tiers") or []
    if tiers:
        return tiers
    steps = appr.get("steps") or []
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId"),
                "username":    s["username"],
                "displayName": s.get("displayName", s["username"]),
                "status":      s.get("status", "pending"),
                "approvedAt":  s.get("approvedAt"),
            }],
        }
        for i, s in enumerate(steps)
    ]


def current_tier_idx(appr: dict) -> int:
    ct = appr.get("currentTier")
    if ct is None:
        ct = appr.get("currentStep", 0)
    return ct


class ApprovalUnreadable(Exception):
    """簽核資料格式不正確（轉簽要擋，不可以當成空鏈）。"""


def tier_fields(approval_json_raw) -> dict:
    """approval JSON（字串或 None）⇒ 佇列項目要的簽核欄位。各單據的 approval 形狀相同（tiers／currentTier）。"""
    try:
        appr = json.loads(approval_json_raw or "{}")
    except Exception:
        appr = {}
    if not isinstance(appr, dict):
        appr = {}
    tiers = active_tiers(appr)
    ct_idx = current_tier_idx(appr)
    cur = (tiers[ct_idx].get("approvers") or []) if tiers and ct_idx < len(tiers) else []
    return {
        "appr":               appr,
        "requestedBy":        appr.get("requestedBy") or "",
        "requestedByDisplay": appr.get("requestedByDisplay") or appr.get("requestedBy") or "",
        "requestedAt":        appr.get("requestedAt") or "",
        "tiers":              tiers,
        "currentTier":        ct_idx,
        "tierCount":          len(tiers),
        "currentApprovers":   cur,
    }


def base_item(type_: str, doc_no: str, f: dict, **fields) -> dict:
    """佇列項目的共同欄位（沿用報價單的欄位名稱承載各類型資料，前端列表不必分流）；`fields` 覆寫或追加。
    `customer`／`projectName` 不給 ⇒ 不放進項目，有 `linkedQuoteNo` 時由 M01 彙整端補案件的客戶與名稱
    （單據模組不讀 M01 的案件表）。"""
    item = {
        "type":               type_,
        "quoteNo":            doc_no,
        "total":              0,
        "quoteDate":          "",
        "salesPerson":        "",
        "requestedBy":        f["requestedBy"],
        "requestedByDisplay": f["requestedByDisplay"],
        "requestedAt":        f["requestedAt"],
        "isEditApproval":     False,
        "reasons":            [],
        "tiers":              f["tiers"],
        "currentTier":        f["currentTier"],
        "tierCount":          f["tierCount"],
        "currentApprovers":   f["currentApprovers"],
    }
    item.update(fields)
    return item


class DataJsonApproval:
    """`approval.reassign` 提供者：簽核鏈存在 `<table>.data_json` 的 `$.approval`、以 `<key>` 欄為單號的單據
    （承攬商匯款申請、開票申請、請款單、出貨單、完工單）。表名由擁有模組傳入。"""

    def __init__(self, table: str, key: str):
        self.table, self.key = table, key

    def load(self, conn, doc_no):
        row = conn.execute("SELECT " + self.key + " AS doc_no, quote_no, status, data_json FROM " + self.table
                           + " WHERE " + self.key + "=?", (doc_no,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["data_json"] or "{}")
        except (TypeError, ValueError):
            raise ApprovalUnreadable(doc_no)
        if not isinstance(data, dict) or not isinstance(data.get("approval") or {}, dict):
            raise ApprovalUnreadable(doc_no)
        return {"docNo": row["doc_no"], "quoteNo": row["quote_no"], "status": row["status"],
                "approval": data.get("approval") or {}, "_data": data}

    def save(self, conn, doc, approval, now):
        data = doc["_data"]
        data["approval"] = approval
        conn.execute("UPDATE " + self.table + " SET data_json=?, updated_at=? WHERE " + self.key + "=?",
                     (json.dumps(data, ensure_ascii=False), now, doc["docNo"]))


def file_entries(raw) -> list:
    """把各表存的檔案 JSON 正規化成前端可預覽的格式（2026-09-26 自 M01 `routers/quotations._file_entries` 逐字下沉）。

    各模組的檔案結構不完全一樣（有的 `filename` 有的 `name`，路徑鍵也不同），
    這裡統一成 `{name, path, kind}`；`kind` 讓前端決定是直接內嵌預覽（圖片）、
    開新分頁（PDF）還是只給下載連結。
    """
    try:
        arr = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for f in arr:
        if not isinstance(f, dict):
            continue
        name = f.get("filename") or f.get("name") or ""
        path = f.get("path") or f.get("filePath") or ""
        if not path:
            continue
        low = (name or path).lower()
        kind = ("image" if low.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                else "pdf" if low.endswith(".pdf") else "file")
        out.append({"id": f.get("id") or path, "name": name or path.split("/")[-1],
                    "path": path, "kind": kind,
                    "uploadedBy": f.get("uploadedBy") or f.get("by") or "",
                    "uploadedAt": f.get("uploadedAt") or f.get("at") or ""})
    return out


def snapshot_doc_detail(r) -> dict:
    """憑快照建立的付款／開票類單據（承攬商匯款申請、開票申請、請款單）共用的詳情內容：`r` 是該表 `SELECT *` 的一列。
    （2026-09-26 自 M01 `approval_queue_detail` 三表共用段逐字下沉；欄位有沒有依 `r.keys()` 判斷。）"""
    keys = r.keys()
    try:
        snap = json.loads(r["snapshot_json"] or "{}")
    except Exception:
        snap = {}
    amount = r["amount"] if "amount" in keys and r["amount"] is not None else (snap.get("grandTotal") or 0)
    fields = [
        {"label": "金額", "value": format(amount or 0, ",.0f")},
        {"label": "範圍", "value": (r["scope"] if "scope" in keys else "") or "—"},
        {"label": "建立者", "value": r["created_by"] or "—"},
        {"label": "建立時間", "value": r["created_at"] or "—"},
    ]
    if "stage" in keys and r["stage"]:
        fields.append({"label": "請款範圍", "value": r["stage"]})
    if snap.get("vendorName"):
        fields.insert(0, {"label": "承攬商", "value": snap["vendorName"]})
    files = []
    if "issued_files_json" in keys:
        files += file_entries(r["issued_files_json"])
    files += file_entries(json.dumps(snap.get("invoiceFiles") or []))
    passbook = snap.get("bankPassbookImage") or ""
    # 只接受 data:image/ ——這個欄位是建立單據時由前端送進來的字串，
    # 若混進 `javascript:` 之類的 scheme，簽核人點下去就是在本站原點執行腳本
    # （2026-09-14 自動安全掃描 finding #2；前端也擋一次，兩邊都擋）
    if isinstance(passbook, str) and passbook.lower().startswith("data:image/"):
        files.append({"id": "passbook", "name": "存簿封面", "kind": "image",
                      "path": "", "dataUrl": passbook,
                      "uploadedBy": "", "uploadedAt": ""})
    return {"quoteNo": r["quote_no"], "approvalRaw": r["data_json"] if "data_json" in keys else None,
            "fields": fields, "items": snap.get("items") or [], "files": files}
