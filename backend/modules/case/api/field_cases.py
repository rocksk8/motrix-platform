# -*- coding: utf-8 -*-
"""外勤手機用的窄唯讀案件端點（T80c S2）：`GET /api/field/cases`、`GET /api/field/cases/{quote_no}`。

## 為什麼另開一組，而不是讓手機直接打 `GET /api/quotations`

現有案件列表每列都帶 `total`、`direct_margin_pct`、`net_margin_pct`（沒有財務檢視權的帳號由 `_mask_money_row` 遮掉，但那是「送出去再遮」的遮蔽）。
個人手機沒有 MDM、可能遺失；外勤要看的只有「去哪、找誰、做到哪」。這裡**只回白名單欄位**（逐欄寫出來，不是 `dict(row)` 再刪鍵）：
**金額、毛利、付款、簽核內部資訊根本不下發**，不是靠畫面藏、也不靠遮蔽函式。要加欄位就是改這支檔（過 K 審），不會被別處的欄位新增順手帶出去。

## 權限

- 列表：與 `GET /api/quotations` 同一支 `row_access.filter_sql("case", user, scope="read")`（誰看得到哪些案件，規則只有一份）。
- 單件：`_guard_case(allow_module="case_manage")`（與案件執行面〔階段、動態〕同一把：admin 以上直通，否則業務／協作者／持有 `case_manage`）。看不到＝查無（同一個 404）。
- 兩支都登記在 `docs/platform/case_read_scope.json`（單件：`row_access`）。

## 「我的案件」與「已成案」為什麼在 Python 裡判斷（不寫 SQL json_extract）

`json_extract(data_json, …)` 在 SQLite 裡逐列解析，一筆壞 JSON 會讓整個查詢丟例外（§G5 #2：新程式一律逐筆 Python 解析、壞的一筆跳過並記 ERROR）。
所以列表是：SQL 只做 row_access＋搜尋，依 id 由新到舊分批（每批 `_CHUNK` 筆）取回，逐筆在 Python 判斷「我的」「已成案」，湊滿一頁就停。
判定規則與案件列表（`_CASE_MINE_SQL`、`SQL_DEAL_TAG`）**逐項對照**：我的＝業務 id／（無 id 時）業務名＝我的顯示名／協作者名單含我／合約角色（填表人、業務、執行）帳號是我。
代價：不回 `total`（要數完全部才知道），改回 `has_more`；掃描長度＝湊滿一頁所需的案件數（外勤帳號可見的案件本來就少）。

## 回應大小

列表每頁 ≤ `MAX_LIMIT`（50）筆、每列約 300 bytes；單件的階段最多 `MAX_STAGES` 個。弱訊號下一頁就是一個小 JSON。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, row_access
from modules.case.api.quotations import _guard_case
from modules.case.quotations import case_delivery_address

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_LIMIT = 50
DEFAULT_LIMIT = 20
MAX_STAGES = 60
#: 外勤預設只看「已成案」的案件（報價階段、已結案的不是外勤作業對象）；`scope=all` 才放寬
_ACTIVE_TAG = "已成案"
#: 列表分批掃描的批量
_CHUNK = 100
#: 掃描上限（保護：湊不滿一頁也不會無限掃；超過 ⇒ 回已湊到的並 has_more=True）
_MAX_SCAN = 5000
_ROLE_KEYS = ("filler", "sales", "executor")


def _s(v):
    """白名單欄位一律轉成字串／None，不讓非預期的型別（dict、數字）從這裡流出去。"""
    return None if v is None else str(v)


def _parse_json(text, what, ident):
    """壞 JSON ⇒ None（只影響這一筆）並記 ERROR；不丟例外。"""
    try:
        v = json.loads(text or "{}")
    except (TypeError, ValueError, RecursionError):
        logger.error("field_cases: %s 的 %s 不是合法 JSON，這一筆當作沒有資料", ident, what)
        return None
    return v


def _deal_tag(row, data):
    """與 `SQL_DEAL_TAG`（`COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')`）同義：欄位優先，空才看 data_json。"""
    tag = (row["deal_tag"] or "")
    if tag != "":
        return tag
    if isinstance(data, dict):
        return _s(data.get("dealTag")) or ""
    return ""


def _is_mine(row, data, user):
    """與 `_CASE_MINE_SQL` 逐項同義。"""
    uid = user["id"]
    if row["sales_person_id"] is not None and row["sales_person_id"] == uid:
        return True
    name = user["display_name"]
    if row["sales_person_id"] is None and row["sales_person"] and row["sales_person"] == name:
        return True
    assigned = _parse_json(row["assigned_user_ids"] or "[]", "assigned_user_ids", row["quote_no"])
    if isinstance(assigned, list) and any(v == uid for v in assigned):
        return True
    roles = ((data.get("caseRecord") or {}).get("roles") or {}) if isinstance(data, dict) and isinstance(data.get("caseRecord"), dict) else {}
    if isinstance(roles, dict):
        for k in _ROLE_KEYS:
            r = roles.get(k)
            if isinstance(r, dict) and r.get("username") == user["username"]:
                return True
    return False


@router.get("/api/field/cases")
def list_field_cases(q: str = "", mine: int = 1, scope: str = "active",
                     limit: int = DEFAULT_LIMIT, offset: int = 0,
                     authorization: str = Header(None)):
    """外勤案件列表（唯讀、無金額）。`mine=1`（預設）＝我的案件；`scope=active`（預設）＝已成案，`scope=all` 不分。
    搜尋 `q` 比對案號／客戶／案名。每頁最多 50 筆；回 `has_more`（不回總數，見檔頭）。"""
    user = _require_user(authorization)
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    need = offset + limit + 1                       # 多湊一筆，用來判斷 has_more
    conn = get_db()
    try:
        frag, params = row_access.filter_sql("case", user, scope="read")
        where, args = frag, list(params)
        if q and q.strip():
            kw = f"%{q.strip()}%"
            where += " AND (quote_no LIKE ? COLLATE NOCASE OR customer_name LIKE ? COLLATE NOCASE OR project_name LIKE ? COLLATE NOCASE)"
            args.extend([kw, kw, kw])
        picked, last_id, scanned, truncated = [], None, 0, False
        while len(picked) < need:
            cond, a = where, list(args)
            if last_id is not None:
                cond += " AND id < ?"
                a.append(last_id)
            rows = conn.execute(
                "SELECT id, quote_no, customer_name, project_name, status, deal_tag, sales_person, sales_person_id, "
                "assigned_user_ids, data_json, updated_at FROM quotations WHERE 1=1" + cond + " ORDER BY id DESC LIMIT ?",
                a + [_CHUNK]).fetchall()
            if not rows:
                break
            for r in rows:
                last_id = r["id"]
                scanned += 1
                data = None
                if scope != "all" or mine:
                    # 只有「欄位判不出來」才需要 data_json：已成案欄位有值、且不查我的案件時不解析
                    need_json = mine or (r["deal_tag"] or "") == ""
                    data = _parse_json(r["data_json"], "data_json", r["quote_no"]) if need_json else None
                if scope != "all" and _deal_tag(r, data) != _ACTIVE_TAG:
                    continue
                if mine and not _is_mine(r, data, user):
                    continue
                picked.append(r)
                if len(picked) >= need:
                    break
            if scanned >= _MAX_SCAN:
                truncated = True
                break
        page = picked[offset:offset + limit]
        has_more = len(picked) > offset + limit or truncated
        extra = {}
        if page:
            nos = [r["quote_no"] for r in page]
            ph = ",".join("?" * len(nos))
            for e in conn.execute(
                    "SELECT quote_no, "
                    "(SELECT label FROM case_stages WHERE quote_no=quotations.quote_no AND done=0 ORDER BY sort_order LIMIT 1) AS current_stage, "
                    "(SELECT COUNT(*) FROM case_stages WHERE quote_no=quotations.quote_no) AS stage_total, "
                    "(SELECT COUNT(*) FROM case_stages WHERE quote_no=quotations.quote_no AND done=1) AS stage_done, "
                    "(SELECT MAX(created_at) FROM case_updates WHERE quote_no=quotations.quote_no) AS last_update_at "
                    "FROM quotations WHERE quote_no IN (" + ph + ")", nos):
                extra[e["quote_no"]] = e
    finally:
        conn.close()
    items = []
    for r in page:
        e = extra.get(r["quote_no"])
        items.append({
            "quote_no": r["quote_no"],
            "customer_name": _s(r["customer_name"]),
            "project_name": _s(r["project_name"]),
            "status": _s(r["status"]),
            "deal_tag": _s(_deal_tag(r, _parse_json(r["data_json"], "data_json", r["quote_no"]) if (r["deal_tag"] or "") == "" else None)),
            "sales_person": _s(r["sales_person"]),
            "current_stage": _s(e["current_stage"]) if e else None,
            "stage_done": (e["stage_done"] or 0) if e else 0,
            "stage_total": (e["stage_total"] or 0) if e else 0,
            "last_update_at": _s(e["last_update_at"]) if e else None,
            "updated_at": _s(r["updated_at"]),
        })
    return {"limit": limit, "offset": offset, "has_more": has_more, "items": items}


@router.get("/api/field/cases/{quote_no}")
def get_field_case(quote_no: str, authorization: str = Header(None)):
    """外勤案件摘要（唯讀、無金額）：案號、客戶、案名、階段、業務、服務地點、聯絡人／電話、階段清單（只有名稱、完成與否、預計日）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user, allow_module="case_manage")
        r = conn.execute(
            "SELECT quote_no, customer_name, project_name, status, deal_tag, sales_person, "
            "quote_date, updated_at, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not r:
            raise HTTPException(404, "報價單不存在")
        stages = conn.execute(
            "SELECT id, label, done, due_date FROM case_stages WHERE quote_no=? ORDER BY sort_order, id LIMIT ?",
            (quote_no, MAX_STAGES)).fetchall()
        last = conn.execute("SELECT MAX(created_at) FROM case_updates WHERE quote_no=?", (quote_no,)).fetchone()[0]
    finally:
        conn.close()
    data = _parse_json(r["data_json"], "data_json", quote_no)       # 壞資料只讓聯絡／地址／標記留空，不讓整支 500
    contact_person = contact_phone = None
    if isinstance(data, dict) and isinstance(data.get("caseRecord"), dict):
        contract = data["caseRecord"].get("contract")
        if isinstance(contract, dict):
            contact_person, contact_phone = _s(contract.get("contactPerson")) or None, _s(contract.get("contactPhone")) or None
    cur = next((s["label"] for s in stages if not s["done"]), None)
    return {
        "quote_no": r["quote_no"],
        "customer_name": _s(r["customer_name"]),
        "project_name": _s(r["project_name"]),
        "status": _s(r["status"]),
        "deal_tag": _s(_deal_tag(r, data)),
        "sales_person": _s(r["sales_person"]),
        "quote_date": _s(r["quote_date"]),
        "address": case_delivery_address(r["data_json"]) or None,
        "contact_person": contact_person,
        "contact_phone": contact_phone,
        "current_stage": _s(cur),
        "stages": [{"id": s["id"], "label": _s(s["label"]), "done": bool(s["done"]), "due_date": _s(s["due_date"]) or None}
                   for s in stages],
        "last_update_at": _s(last),
        "updated_at": _s(r["updated_at"]),
        "server_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
