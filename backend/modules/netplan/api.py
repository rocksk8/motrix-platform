"""網路架構規劃書：工程師在系統內填寫一份客戶網路建置案的完整技術規劃文件
（WAN／設備清單／VLAN／IP位址配置／PortProfile定義／交換器Port對應／防火牆
規則／IP-Port群組／無線SSID／線路幹線／修訂紀錄），之後可匯出 Excel／PDF 給
客戶。完整設計依據見專案根目錄 `NETWORK-PLAN-MODULE-DESIGN.md`。

含整份文件層級的 CRUD、Excel/PDF 匯出、Excel 匯入（現場離線填寫後整批帶回）。

quote_no 選填：可綁定案件（quotations.quote_no），也可獨立建立（售前評估/
巡檢等還沒有案件的場景）。一案最多一份規劃書，由 db.py `_m064_network_plans`
的 partial unique index 擋重複，這裡違反時轉成 409 而不是讓 sqlite
IntegrityError 直接炸穿。

版本管理採「單一文件＋修訂紀錄」：`data_json.revisionLog` 由前端決定何時
push 一筆新紀錄（例如使用者按下「記錄本次修訂」），後端 PUT 只負責整份存檔＋
樂觀鎖（`_expectedUpdatedAt`，比照 quotations.py::update_case_record 的作法），
不強制介入。

編輯權限：superadmin/admin 或具 `netplan_edit` 模組者（檢視／編輯分成兩把 key，
讓 admin 之後可以個別授權給特定工程師帳號）；
檢視為任何登入者皆可。刪除限定 superadmin，且只有「規劃中」狀態可刪。
"""
import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header, UploadFile, File
from fastapi.responses import Response

from db import get_db, next_entity_code
from helpers import (_require_user, _tok, _audit, notify_module_activity,
                     require_any_module)
from core import registry as _registry

#: M01 不在時對使用者說的話（IP-12 `case.access`；不可以默默略過）
CASE_MISSING = "案件模組未安裝"


def _case_access():
    """IP-12 `case.access`（M01 提供）；None ⇒ 案件模組未安裝。"""
    return _registry.single_provider("case.access")

# 讀取端點的模組聯集（2026-09-14）：規劃書自己三頁（netplan／netplan_edit）＋
# 案件管理（`js/case-management.js` 也會打這組 API）。只認 netplan 會把案件管理
# 那條路徑打死——那正是 MODULE-AUDIT §5 說的「擋錯人」失敗模式。
_VIEW_MODULES = ('netplan', 'netplan_edit', 'case_manage')
from modules.netplan.export import build_plan_excel, build_plan_pdf_bytes, parse_plan_excel
from modules.netplan.topology import build_topology_svg
from helpers.errors import trace_id

router = APIRouter()
logger = logging.getLogger(__name__)

_EDIT_MODULE = "netplan_edit"
_STATUSES = ("規劃中", "已確認", "已交付")


def _plan_public(row) -> dict:
    d = dict(row)
    return {
        "id":           d["id"],
        "planNo":       d["plan_no"],
        "quoteNo":      d.get("quote_no") or "",
        "siteName":     d.get("site_name") or "",
        "contactName":  d.get("contact_name") or "",
        "contactPhone": d.get("contact_phone") or "",
        "status":       d.get("status") or "規劃中",
        "createdBy":    d.get("created_by") or "",
        "updatedBy":    d.get("updated_by") or "",
        "createdAt":    d.get("created_at") or "",
        "updatedAt":    d.get("updated_at") or "",
        "data":         json.loads(d.get("data_json") or "{}"),
    }


@router.get("/api/network-plans")
def list_network_plans(quote_no: Optional[str] = None, status: Optional[str] = None,
                        q: Optional[str] = None, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, _VIEW_MODULES, "網路架構規劃書")
    conn = get_db()
    sql = "SELECT * FROM network_plans WHERE 1=1"
    params = []
    if quote_no:
        sql += " AND quote_no=?"
        params.append(quote_no)
    if status:
        sql += " AND status=?"
        params.append(status)
    if q:
        sql += " AND (plan_no LIKE ? OR site_name LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY updated_at DESC LIMIT 300"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_plan_public(r) for r in rows]


@router.get("/api/network-plans/{plan_id}")
def get_network_plan(plan_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, _VIEW_MODULES, "網路架構規劃書")
    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    return _plan_public(row)


@router.get("/api/quotations/{quote_no}/network-plan")
def get_network_plan_by_case(quote_no: str, authorization: str = Header(None)):
    """供案件詳情頁查詢是否已有綁定的規劃書；查無資料回 404（前端據此顯示
    「建立規劃書」而非「開啟規劃書」按鈕）。"""
    # 2026-09-13（模組權限稽核）：`quote_no` 可列舉，先前只要求登入。
    user = _require_user(authorization)
    ca = _case_access()
    if ca is None:
        raise HTTPException(404, CASE_MISSING + "：無法依案件查詢網路架構規劃書")
    conn = get_db()
    ca.guard(conn, quote_no, user, allow_module="case_manage")
    row = conn.execute("SELECT * FROM network_plans WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "此案件尚無網路架構規劃書")
    return _plan_public(row)


@router.post("/api/network-plans", status_code=201)
def create_network_plan(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    quote_no = (body.get("quoteNo") or "").strip() or None
    site_name = (body.get("siteName") or "").strip()

    quote_row = None
    if quote_no and _case_access() is None:
        raise HTTPException(400, CASE_MISSING + "：規劃書無法綁定案件（不填案件單號即可建立獨立的規劃書）")
    conn = get_db()
    if quote_no:
        quote_row = _case_access().summary(conn, quote_no)
        if not quote_row:
            conn.close()
            raise HTTPException(404, f"找不到案件 {quote_no}")
        if conn.execute("SELECT 1 FROM network_plans WHERE quote_no=?", (quote_no,)).fetchone():
            conn.close()
            raise HTTPException(409, "此案件已建立過網路架構規劃書")
        if not site_name:
            site_name = quote_row["customer"] or quote_row["project"] or ""

    now = datetime.now().isoformat()
    plan_no = next_entity_code(conn, "network_plans", "NP", code_col="plan_no")
    data = {
        "wanLines": [], "devices": [], "vlans": [], "ipAllocations": [],
        "portProfiles": [], "switchPorts": [], "firewallRules": [], "ipPortGroups": [],
        "wifiSsids": [], "cabling": [],
        "revisionLog": [{"version": 1, "date": now, "editor": user["username"], "note": "初版建立"}],
    }
    try:
        cur = conn.execute(
            "INSERT INTO network_plans "
            "(plan_no, quote_no, site_name, contact_name, contact_phone, status, "
            "created_by, updated_by, created_at, updated_at, data_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (plan_no, quote_no, site_name, (body.get("contactName") or "").strip(),
             (body.get("contactPhone") or "").strip(), "規劃中",
             user["username"], user["username"], now, now, json.dumps(data, ensure_ascii=False))
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "此案件已建立過網路架構規劃書")
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "network_plan.create", "network_plan", plan_no,
           f"{plan_no}（{site_name}）")
    notify_module_activity("網路架構規劃書", "建立", user.get("display_name") or user["username"],
                            f"{plan_no}（{site_name}）", "network-plans.html")
    return {"id": plan_id, "planNo": plan_no, "createdAt": now}


@router.put("/api/network-plans/{plan_id}")
def update_network_plan(plan_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "規劃書不存在")

    expected = body.get("_expectedUpdatedAt")
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "此規劃書已被其他人更新，請重新載入後再存")

    now = datetime.now().isoformat()
    site_name     = body.get("siteName", row["site_name"]) or ""
    contact_name  = body.get("contactName", row["contact_name"]) or ""
    contact_phone = body.get("contactPhone", row["contact_phone"]) or ""
    data = body.get("data")
    data_json = json.dumps(data, ensure_ascii=False) if data is not None else row["data_json"]

    conn.execute(
        "UPDATE network_plans SET site_name=?, contact_name=?, contact_phone=?, "
        "data_json=?, updated_by=?, updated_at=? WHERE id=?",
        (site_name, contact_name, contact_phone, data_json, user["username"], now, plan_id)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "network_plan.update", "network_plan", row["plan_no"],
           f"{row['plan_no']}（{site_name}）")
    return {"ok": True, "updatedAt": now}


@router.patch("/api/network-plans/{plan_id}/status")
def update_network_plan_status(plan_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    new_status = body.get("status")
    if new_status not in _STATUSES:
        raise HTTPException(400, f"status 必須為 {'/'.join(_STATUSES)} 其中之一")
    note = (body.get("note") or "").strip()

    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "規劃書不存在")

    data = json.loads(row["data_json"] or "{}")
    log = data.get("revisionLog") or []
    now = datetime.now().isoformat()
    log.append({
        "version": len(log) + 1, "date": now, "editor": user["username"],
        "note": f"狀態變更：{row['status']} → {new_status}" + (f"（{note}）" if note else ""),
    })
    data["revisionLog"] = log

    conn.execute(
        "UPDATE network_plans SET status=?, data_json=?, updated_by=?, updated_at=? WHERE id=?",
        (new_status, json.dumps(data, ensure_ascii=False), user["username"], now, plan_id)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "network_plan.status_change", "network_plan", row["plan_no"],
           f"{row['plan_no']}：{row['status']} → {new_status}")
    return {"ok": True, "status": new_status}


@router.delete("/api/network-plans/{plan_id}")
def delete_network_plan(plan_id: int, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT plan_no, status, site_name FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "規劃書不存在")
    if row["status"] != "規劃中":
        conn.close()
        raise HTTPException(409, "僅「規劃中」狀態可刪除")
    conn.execute("DELETE FROM network_plans WHERE id=?", (plan_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "network_plan.delete", "network_plan", row["plan_no"],
           f"{row['plan_no']}（{row['site_name']}）")
    notify_module_activity("網路架構規劃書", "刪除", user.get("display_name") or user["username"],
                            f"{row['plan_no']}（{row['site_name']}）", "network-plans.html")
    return {"ok": True}


@router.post("/api/network-plans/{plan_id}/topology-preview")
def preview_network_plan_topology(plan_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """即時預覽用：不落地存檔，直接把前端目前（含尚未儲存）的 data 拿去畫拓樸圖，
    供「拓樸圖」分頁按下「重新產生預覽」時呼叫。"""
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT id FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    data = body.get("data") or {}
    try:
        result = build_topology_svg(data)
    except Exception as e:
        tid = trace_id()
        logger.exception("network_plan topology failed trace=%s", tid)
        raise HTTPException(400, f"拓樸圖產生失敗（代碼 {tid}）")
    return {"svg": result.get("html"), "warnings": result.get("warnings") or []}


# ── 匯出（§10 步驟 8/9） ──────────────────────────────────────────────────────

@router.get("/api/network-plans/{plan_id}/export/excel")
def export_network_plan_excel(plan_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    plan = _plan_public(row)
    xlsx_bytes = build_plan_excel(plan)
    filename = urlquote(f"{plan['planNo']}_{plan['siteName']}_網路架構規劃表.xlsx")
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/api/network-plans/{plan_id}/export/pdf")
def export_network_plan_pdf(plan_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    plan = _plan_public(row)
    try:
        pdf_bytes = build_plan_pdf_bytes(plan)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(500, str(e))
    filename = urlquote(f"{plan['planNo']}_{plan['siteName']}_網路架構規劃書.pdf")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/api/network-plans/{plan_id}/import/excel")
async def import_network_plan_excel(plan_id: int, file: UploadFile = File(...),
                                     authorization: str = Header(None)):
    """現場填寫版 Excel 匯入：工程師把匯出的範本帶到現場離線填寫，回來後整份
    上傳，直接覆蓋對應分頁在系統裡的明細，不用逐欄位重新輸入一次。

    比對用分頁名稱／欄位表頭文字（見 network_plan_export.py::parse_plan_excel），
    未辨識的分頁/欄位直接略過並回傳 warnings，不會讓整次匯入失敗；找不到任何
    可辨識分頁才視為錯誤。有辨識到的分頁**整批覆蓋**該分頁在 data_json 裡的
    陣列（不是逐列合併），符合「這份 Excel 現在的內容就是最新狀態」的直覺——
    使用者若只想改少數幾筆，得先匯出最新版本再離線編輯，避免用舊版蓋新資料。
    案場資訊（siteName/quoteNo/status 等識別欄位）不受匯入影響，只動明細。"""
    user = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT * FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "規劃書不存在")

    content = await file.read()
    try:
        result = parse_plan_excel(content)
    except Exception as e:
        conn.close()
        tid = trace_id()
        logger.exception("network_plan excel parse failed trace=%s", tid)
        raise HTTPException(
            400, f"檔案解析失敗，請確認上傳的是本系統匯出的 Excel 範本（代碼 {tid}）")

    sections = result["sections"]
    if not sections:
        conn.close()
        raise HTTPException(400, "；".join(result["warnings"]) or "找不到任何可辨識的分頁")

    data = json.loads(row["data_json"] or "{}")
    for key, rows_ in sections.items():
        data[key] = rows_

    now = datetime.now().isoformat()
    log = data.get("revisionLog") or []
    log.append({
        "version": len(log) + 1, "date": now, "editor": user["username"],
        "note": f"透過 Excel 匯入更新：{'、'.join(sections.keys())}",
    })
    data["revisionLog"] = log

    conn.execute(
        "UPDATE network_plans SET data_json=?, updated_by=?, updated_at=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), user["username"], now, plan_id)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "network_plan.import_excel", "network_plan", row["plan_no"],
           f"{row['plan_no']}：匯入 {'、'.join(sections.keys())}")
    return {"ok": True, "updatedSections": list(sections.keys()), "warnings": result["warnings"]}


# ── 個資蒐集告知（CUSTOMIZATION-SPEC §9.3；2026-09-26 主持裁示：單據上手動輸入的聯絡人也是蒐集個資）──
# 紀錄存在 L1 設定鍵 `privacy_notice_acks`，鍵＝`network_plan_contact:<單據>:<聯絡人姓名>`（換了聯絡人＝另一個人，要重新告知）。
# 伺服器只接受「已存檔的那位聯絡人」；時間、人員、告知文字雜湊由伺服器蓋，已記錄的不覆蓋。沒有紀錄不擋存檔。

@router.get("/api/network-plans/{plan_id}/privacy-notice")
def get_network_plan_privacy_acks(plan_id: int, authorization: str = Header(None)):
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, _VIEW_MODULES, "網路架構規劃書")
    conn = get_db()
    row = conn.execute("SELECT id FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    return {"acks": _pn.acks_with_prefix("network_plan_contact", plan_id)}


@router.post("/api/network-plans/{plan_id}/privacy-notice/ack")
def ack_network_plan_privacy_notice(plan_id: int, body: dict = Body(...), authorization: str = Header(None)):
    from helpers import privacy_notice as _pn
    user = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    subject = str((body or {}).get("subject") or "").strip()
    conn = get_db()
    row = conn.execute("SELECT plan_no, contact_name FROM network_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "規劃書不存在")
    if not subject or subject != (row["contact_name"] or "").strip():
        raise HTTPException(409, "聯絡人與已儲存的不同，請先儲存規劃書再勾選")
    rec, created = _pn.record_purpose_ack("network_plan_contact", f"{plan_id}:{subject}", user, "contact")
    if created:
        _audit(_tok(authorization), "network_plan.privacy_notice_ack", "network_plan", row["plan_no"],
               f"{row['plan_no']}／{subject}", {"noticeHash": rec.get("noticeHash")})
    return {"ack": rec, "created": created}


# ══ 快速拓樸圖（2026-09-26 自 routers/network_plans_quick.py 併入；模組保持單層，守門的端點掃描收得到）══
#
# 快速拓樸圖產生器：對應使用者原本個案腳本（B1F 拓樸圖產生器 b1f_topology.py）
# 的使用情境——只是想單純畫一張交換器埠位拓樸圖，不需要建立一份完整的網路架構
# 規劃書（不用填 WAN／VLAN／IP／防火牆…等其餘 9 個分頁）。
#
# 刻意設計成完全無狀態、不落地存檔：前端把 devices／switchPorts 資料整包放在
# 瀏覽器 localStorage（見快速拓樸頁 topology-quick.html），這裡只負責把
# 收到的資料畫成 SVG 預覽或轉出 PDF，不寫進 network_plans 資料表，也不建立任何
# 規劃書紀錄——用完即丟，不需要走完整規劃書的建立/刪除/狀態流程。
#
# 路徑刻意用獨立的 /api/network-plans-quick 前綴（不是 /api/network-plans/xxx），
# 避免跟 network_plans.py 既有的 /api/network-plans/{plan_id} 參數化路由撞在一起。
from modules.netplan.export import build_topology_only_pdf_bytes  # noqa: E402

# 與規劃書共用同一支 router：路徑前綴 /api/network-plans-quick 與 /api/network-plans/{plan_id} 不相撞，
# 而且守門的端點掃描（寫入稽核、例外訊息外洩…）只認 `router` 這個名字。

# 2026-09-13（模組權限稽核第二輪）：這支 router 的兩個端點**刻意不套模組檢查**。
# 它們是無狀態的繪圖工具（吃前端傳來的 JSON、回 SVG/PDF，不讀也不寫任何資料表），
# 擋它不會保護到任何資料，只會擋掉使用者畫圖。模組檢查的目的是資料可見性，
# 不是「凡是端點都要掛一道」。見 MODULE-AUDIT-2026-09-13.md §3.8 ④。


@router.post("/api/network-plans-quick/preview")
def preview_quick_topology(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    data = body.get("data") or {}
    try:
        result = build_topology_svg(data)
    except Exception as e:
        tid = trace_id()
        logger.exception("network_plan_quick topology failed trace=%s", tid)
        raise HTTPException(400, f"拓樸圖產生失敗（代碼 {tid}）")
    return {"svg": result.get("html"), "warnings": result.get("warnings") or []}


@router.post("/api/network-plans-quick/pdf")
def export_quick_topology_pdf(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    data = body.get("data") or {}
    title = (body.get("title") or "").strip()
    floor_tag = (body.get("floorTag") or "").strip()
    footer = (body.get("footer") or "").strip()
    try:
        pdf_bytes = build_topology_only_pdf_bytes(data, title, floor_tag, footer)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(500, str(e))
    filename = (title or "拓樸圖") + ".pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urlquote(filename)}"},
    )
