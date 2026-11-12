# -*- coding: utf-8 -*-
"""外勤手機用的窄唯讀案件端點（T80c S2）：`GET /api/field/cases`、`GET /api/field/cases/{quote_no}`。

## 為什麼另開一組，而不是讓手機直接打 `GET /api/quotations`

現有案件列表每列都帶 `total`、`direct_margin_pct`、`net_margin_pct`（沒有財務檢視權的帳號由 `_mask_money_row` 遮掉，但那是「送出去再遮」的遮蔽）。
個人手機沒有 MDM、可能遺失；外勤要看的只有「去哪、找誰、做到哪」。這裡**只回白名單欄位**（逐欄寫出來，不是 `dict(row)` 再刪鍵；
欄位值只放行字串／數字，巢狀物件一律丟掉）：**金額、毛利、付款、簽核內部資訊根本不下發**，不是靠畫面藏、也不靠遮蔽函式。
要加欄位就是改這支檔（過 K 審），不會被別處的欄位新增順手帶出去。回應帶 `Cache-Control: private, no-store`（含客戶電話／地址，不留在手機或代理的快取）。

## 權限＝案件成員（CM14），列表與單件同一份

這支新增曝露「客戶聯絡人、電話、地址」，比階段／動態（執行面）敏感，所以**不沿用** `case_manage` 模組放行（持該模組者可開任何案件，案號 `MQ-YYYYMM-NNN` 可列舉）。
可見＝案件成員，與 `_is_case_member`（CM14）逐項同義：admin／superadmin；業務（id／無 id 時的顯示名）；`assigned_user_ids`；
`caseRecord.roles` 的 filler／sales／executor（物件比 username、舊字串比顯示名）；階段負責人。看不到＝查無（同一個 404）。
列表與單件用同一個 `_is_member`，所以「現場工程師只是 roles.executor」也列得出來、點得進去，別人的案件兩邊都是 404。
（持 `cashier` 的財務不在內：scope="read" 的財務可見性是為金額頁設計的，外勤這支不含金額，也就不需要。）

SQL 只做粗篩（不寫 json_extract，壞 JSON 不能讓整個查詢丟例外）：業務欄位、`instr(...)` 子字串、階段表 `instr`，是「成員」的**超集**；
最後一律在 Python 逐筆用 `_is_member` 判定。

## 「我的案件」與「已成案」在 Python 裡判斷

非 admin：看得到的就是與我有關的，`mine` 不再縮小。admin／superadmin：`mine=1`（預設）＝與案件列表 `_CASE_MINE_SQL` 逐項對照的「我的」
（業務 id／無 id 時業務名＝我的顯示名／協作者名單含我／合約角色帳號是我），`mine=0` ＝全部。已成案與 `SQL_DEAL_TAG` 同義：欄位優先，空才看 data_json。

## 分頁：游標（不是 offset）

回 `has_more` 與 `next_before_id`；下一頁帶 `before_id=<next_before_id>`。掃描有上限（`_MAX_SCAN`），湊不滿一頁就停：這時回已湊到的（可能是空頁）、
`has_more=True`、`next_before_id`＝最後掃到的 id——client 照 `next_before_id` 繼續就會掃到更舊的案件，不會永遠停在同一段。
頁滿時 `next_before_id`＝這頁最後一筆的 id。不回總數（要數完全部才知道）。

## 回應大小

列表每頁 ≤ `MAX_LIMIT`（50）筆、每列約 300 bytes；單件的階段最多 `MAX_STAGES` 個。弱訊號下一頁就是一個小 JSON。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Header, Response

from db import get_db
from helpers import _require_user, row_access
from helpers.case_access import deny_case
from helpers.case_roles import ROLE_KEYS, role_username

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_LIMIT = 50
DEFAULT_LIMIT = 20
MAX_STAGES = 60
#: 外勤預設只看「已成案」的案件（報價階段、已結案的不是外勤作業對象）；`scope=all` 才放寬
_ACTIVE_TAG = "已成案"
#: 列表分批掃描的批量
_CHUNK = 100
#: 掃描上限（保護：湊不滿一頁也不會無限掃；到了 ⇒ 回已湊到的並 has_more=True＋next_before_id 讓 client 續掃）
_MAX_SCAN = 5000
_NO_STORE = "private, no-store"
#: `before_id` 的上限（SQLite INTEGER 是 64 位元有號；夾在 2**62，之上的值語意都是「全部」）
_MAX_ID = 2 ** 62
#: 壞 JSON 只在行程內第一次記 ERROR（手機輪詢不會持續噴），之後降為 DEBUG
_LOGGED = set()
_LOGGED_MAX = 2000


def _s(v):
    """白名單欄位值：字串原樣、數字轉字串，其餘（dict／list／bool／None）一律 None——巢狀物件不會被 str() 後流出去。"""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return None


def _parse_json(text, what, ident):
    """壞 JSON ⇒ None（只影響這一筆）；每個 (案號, 欄位) 在行程內只記一次 ERROR，之後 DEBUG；不丟例外。"""
    try:
        v = json.loads(text or "{}")
    except (TypeError, ValueError, RecursionError):
        key = (ident, what)
        if key not in _LOGGED:
            if len(_LOGGED) >= _LOGGED_MAX:
                _LOGGED.clear()
            _LOGGED.add(key)
            logger.error("field_cases: %s 的 %s 不是合法 JSON，這一筆當作沒有資料（同一筆之後只記 DEBUG）", ident, what)
        else:
            logger.debug("field_cases: %s 的 %s 仍不是合法 JSON", ident, what)
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


def _address(data):
    """服務地點：合約交貨地址優先，其次報價單交貨地點（與 `case_delivery_address` 同義）；只收字串，其他型別當沒有（不 str() 後流出）。"""
    if not isinstance(data, dict):
        return None
    contract = (data.get("caseRecord") or {}).get("contract") if isinstance(data.get("caseRecord"), dict) else None
    for v in ((contract or {}).get("deliveryAddress") if isinstance(contract, dict) else None, data.get("deliveryLocation")):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _is_admin(user):
    return user["role"] in ("superadmin", "admin")


def _stage_assigned(conn, quote_no, username):
    """階段負責人（與 `_is_case_member` 的 json_each(assigned_to) 同義，但逐筆在 Python 解析：壞的一筆不影響其他）。"""
    unames = sorted(_needles(username))
    for e in conn.execute("SELECT assigned_to FROM case_stages WHERE quote_no=? AND ("
                          + " OR ".join("instr(assigned_to, ?)>0" for _ in unames) + ")", [quote_no] + unames):
        lst = _parse_json(e["assigned_to"], "case_stages.assigned_to", quote_no)
        if isinstance(lst, list) and any(v == username for v in lst):
            return True
    return False


def _roles_of(data):
    if isinstance(data, dict) and isinstance(data.get("caseRecord"), dict):
        roles = data["caseRecord"].get("roles")
        return roles if isinstance(roles, dict) else {}
    return {}


def _is_member(conn, row, data, user):
    """案件成員（CM14），與 `modules.case.api.quotations._is_case_member` 逐項同義；列表與單件共用這一支。"""
    if _is_admin(user):
        return True
    try:
        if row_access.visible("case", user, row):            # 業務 id／無 id 時的顯示名、assigned_user_ids
            return True
    except (ValueError, TypeError):                           # assigned_user_ids 壞 JSON：只讓這條路不通
        logger.error("field_cases: %s 的 assigned_user_ids 不是合法 JSON", row["quote_no"])
    roles = _roles_of(data)
    me = user["display_name"] or ""
    for k in ROLE_KEYS:
        v = roles.get(k)
        uname = role_username(v)
        if uname is not None:
            if uname == user["username"]:
                return True
        elif me and isinstance(v, str) and v.strip() == me:
            return True
    return _stage_assigned(conn, row["quote_no"], user["username"])


def _is_mine(row, data, user):
    """admin 的「我的」，與 `_CASE_MINE_SQL` 逐項同義。"""
    uid = user["id"]
    if row["sales_person_id"] is not None and row["sales_person_id"] == uid:
        return True
    name = user["display_name"]
    if row["sales_person_id"] is None and row["sales_person"] and row["sales_person"] == name:
        return True
    assigned = _parse_json(row["assigned_user_ids"] or "[]", "assigned_user_ids", row["quote_no"])
    if isinstance(assigned, list) and any(v == uid for v in assigned):
        return True
    roles = _roles_of(data)
    for k in ROLE_KEYS:
        r = roles.get(k)
        if isinstance(r, dict) and r.get("username") == user["username"]:
            return True
    return False


def _needles(v):
    """粗篩 instr 要找的字串：JSON 內容可能是 ensure_ascii=True（非 ASCII 存成 u 加四位十六進位的跳脫）或 False（原文）寫入，
    且雙引號、反斜線在兩種寫法下都會被跳脫——三種形式（原文、ASCII 跳脫、原文＋只跳脫特殊字元）都比，才不會漏（假陰性＝工程師列表又空）。"""
    return {v, json.dumps(v, ensure_ascii=True)[1:-1], json.dumps(v, ensure_ascii=False)[1:-1]}


def _coarse_member_sql(user):
    """非 admin 的 SQL 粗篩片段（＝成員的超集，不含任何 json 函式）；精確判定在 Python `_is_member`。"""
    terms = ["sales_person_id=?", "instr(COALESCE(assigned_user_ids,''), ?)>0"]
    params = [user["id"], str(user["id"])]
    name = user["display_name"] or ""
    if name:
        terms.append("(sales_person_id IS NULL AND sales_person=?)")
        params.append(name)
    needles = _needles(user["username"]) | (_needles(name) if name else set())
    for n in sorted(needles):
        terms.append("instr(data_json, ?)>0")
        params.append(n)
    unames = sorted(_needles(user["username"]))
    terms.append("EXISTS (SELECT 1 FROM case_stages cs WHERE cs.quote_no=quotations.quote_no AND ("
                 + " OR ".join("instr(cs.assigned_to, ?)>0" for _ in unames) + "))")
    params.extend(unames)
    return " AND (" + " OR ".join(terms) + ")", params


@router.get("/api/field/cases")
def list_field_cases(response: Response, q: str = "", mine: int = 1, scope: str = "active",
                     limit: int = DEFAULT_LIMIT, before_id: int = 0,
                     authorization: str = Header(None)):
    """外勤案件列表（唯讀、無金額）。可見＝案件成員（見檔頭）；`mine` 只對 admin 有差別；`scope=active`（預設）＝已成案，`scope=all` 不分。
    搜尋 `q` 比對案號／客戶／案名。每頁最多 50 筆；游標分頁：回 `has_more`／`next_before_id`，下一頁帶 `before_id`。"""
    user = _require_user(authorization)
    response.headers["Cache-Control"] = _NO_STORE
    limit = max(1, min(int(limit), MAX_LIMIT))
    admin = _is_admin(user)
    conn = get_db()
    try:
        where, args = "", []
        if not admin:
            where, args = _coarse_member_sql(user)
        if q and q.strip():
            kw = f"%{q.strip()}%"
            where += " AND (quote_no LIKE ? COLLATE NOCASE OR customer_name LIKE ? COLLATE NOCASE OR project_name LIKE ? COLLATE NOCASE)"
            args.extend([kw, kw, kw])
        last_id = min(int(before_id), _MAX_ID) if before_id and int(before_id) > 0 else None     # 上限夾住：超過 SQLite INTEGER 會 OverflowError（500）
        picked, scanned, truncated, last_scanned = [], 0, False, None
        tags = {}
        done = False
        while not done:
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
                last_id = last_scanned = r["id"]
                scanned += 1
                data = None
                if not admin or mine or (r["deal_tag"] or "") == "":
                    data = _parse_json(r["data_json"], "data_json", r["quote_no"])
                tag = _deal_tag(r, data)
                if scope != "all" and tag != _ACTIVE_TAG:
                    continue
                if not _is_member(conn, r, data, user):
                    continue
                if admin and mine and not _is_mine(r, data, user):
                    continue
                tags[r["id"]] = tag
                picked.append(r)
                if len(picked) > limit:                    # 多湊一筆，用來判斷 has_more
                    done = True
                    break
            if not done and scanned >= _MAX_SCAN:
                truncated = True
                break
        if len(picked) > limit:
            page, has_more, next_id = picked[:limit], True, picked[limit - 1]["id"]
        elif truncated:
            page, has_more, next_id = picked, True, last_scanned
        else:
            page, has_more, next_id = picked, False, None
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
            "deal_tag": _s(tags.get(r["id"])),
            "sales_person": _s(r["sales_person"]),
            "current_stage": _s(e["current_stage"]) if e else None,
            "stage_done": (e["stage_done"] or 0) if e else 0,
            "stage_total": (e["stage_total"] or 0) if e else 0,
            "last_update_at": _s(e["last_update_at"]) if e else None,
            "updated_at": _s(r["updated_at"]),
        })
    return {"limit": limit, "has_more": has_more, "next_before_id": next_id, "items": items}


@router.get("/api/field/cases/{quote_no}")
def get_field_case(quote_no: str, response: Response, authorization: str = Header(None)):
    """外勤案件摘要（唯讀、無金額）：案號、客戶、案名、階段、業務、服務地點、聯絡人／電話、階段清單（只有名稱、完成與否、預計日）。
    可見＝案件成員（與列表同一份）；看不到＝查無（404）。"""
    user = _require_user(authorization)
    response.headers["Cache-Control"] = _NO_STORE
    conn = get_db()
    try:
        r = conn.execute(
            "SELECT id, quote_no, customer_name, project_name, status, deal_tag, sales_person, sales_person_id, assigned_user_ids, "
            "quote_date, updated_at, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not r:
            deny_case(conn, quote_no, user, "not_found")      # 關連線＋audit＋404
        data = _parse_json(r["data_json"], "data_json", quote_no)       # 壞資料只讓聯絡／地址／標記留空，不讓整支 500
        if not _is_member(conn, r, data, user):
            deny_case(conn, quote_no, user, "denied")         # 看不到＝不存在（同一個 404）
        stages = conn.execute(
            "SELECT id, label, done, due_date FROM case_stages WHERE quote_no=? ORDER BY sort_order, id LIMIT ?",
            (quote_no, MAX_STAGES)).fetchall()
        last = conn.execute("SELECT MAX(created_at) FROM case_updates WHERE quote_no=?", (quote_no,)).fetchone()[0]
    finally:
        conn.close()
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
        "address": _address(data),
        "contact_person": contact_person,
        "contact_phone": contact_phone,
        "current_stage": _s(cur),
        "stages": [{"id": s["id"], "label": _s(s["label"]), "done": bool(s["done"]), "due_date": _s(s["due_date"]) or None}
                   for s in stages],
        "last_update_at": _s(last),
        "updated_at": _s(r["updated_at"]),
        "server_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
