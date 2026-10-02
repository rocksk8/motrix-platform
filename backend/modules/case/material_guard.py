# -*- coding: utf-8 -*-
"""叫料審核的寫入閘（31-C S3）：**所有**寫 `caseRecord.materialOrders[]`／`caseRecord.materials[]` 物流旗標的路徑都過這一支。

[單位] case:material_guard    [層] L2（M01）
**為什麼要有**：叫料沒有資料表，整包存在 `quotations.data_json`；除了專屬端點，`PATCH /case-record`、報價單整份存檔、已結案變更核准
都會整包覆蓋 `caseRecord`——不閘就等於審核形同虛設（設計 §1.1）。

**兩層**：
1. 端點先呼叫 `enforce(conn, quote_no, data, actor)`，把被拒的項目收進 `rejected[]` 回給使用者（**只拒有問題的項目，其餘照存**）；
2. **後盾**：唯一的寫入漏斗 `modules/case/quotations.py::save_quotation_json` 也呼叫同一個函式（冪等：已過閘的資料再過一次不會有任何改動），
   所以沒有人呼叫端點層也繞不過去。`actor=None`（系統／已結案變更核准套用）＝不做「誰能改」的權限檢查，但**不變式照樣強制**。
**規則（以資料庫現值為準）**：
- 新叫料列 ⇒ 建審核單（草稿）；`PAID_VIA_REMITTANCE_ONLY` 為真時，已付欄位只能由匯款流程寫（新列強制 pending/0/空；既有列已付欄位的改動被拒）；
- 既有列的**實質欄位**變更 ⇒ 依 `material_approval.on_substantive_change`（舊單→草稿；已核准→草稿重送審；審核中／已取消 ⇒ 該列變更被拒）；
- 刪除叫料列：只有舊單／草稿／已退回可刪；審核中／已核准／已取消 ⇒ 被拒（請撤回或取消）；
- 誰能新增／修改／刪除叫料列：admin 以上或 `project_manage` 模組，且有財務檢視權（`actor` 有給才檢查，同專屬端點）；
- 物流旗標：`ordered`／`arrived` 由 false→true 必須有 `orderItemId` 指到**已核准**的叫料單；`arrived` 另要該單已**記錄到貨確認**（日期＋確認人）；
  否則該旗標被拒（維持原值），連帶這一項的 `devices`（序號）也維持原值——不讓序號在沒核准的情況下認領庫存。
- 回傳 `rejected`：`[{itemId, field, code, message}]`。
"""
import json

from helpers.auth import user_has_module
from helpers.dates import normalize_date
from helpers.financial_mask import money_visible
from modules.case import material_approval as MA
from modules.case import material_payment as MP

# 已付欄位（付款只能經匯款申請寫入）
_PAID_KEYS = ("paidStatus", "paidAmount", "paidDate")
_FLAGS = ("ordered", "arrived")


def _num(v):
    try:
        return round(float(v or 0), 4)
    except (TypeError, ValueError):
        return v


def _canon(v):
    """比較用正規形：整數值的浮點數視為整數、None 與缺鍵視為相同。"""
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _same(key, new, old) -> bool:
    """欄位值相同？已付欄位把 None／空字串／0 視為同一個「沒有」（前端未付款時送 null，資料庫存 ''）。"""
    if key in _PAID_KEYS and new in (None, "", 0) and old in (None, "", 0):
        return True
    if key == "paidStatus" and new in (None, "", "pending") and old in (None, "", "pending"):
        return True
    return _canon(new) == _canon(old)


def can_edit_orders(actor) -> bool:
    """同專屬端點（`material_orders.py`）：admin 以上或 `project_manage`，且有財務檢視權（CM13）。"""
    if actor is None:
        return True
    return (actor.get("role") in ("superadmin", "admin") or user_has_module(actor, "project_manage")) and money_visible(actor)


def _rej(out, item_id, field, code, message):
    out.append({"itemId": str(item_id), "field": field, "code": code, "message": message})


def _valid_supplier_id(v) -> bool:
    """供應商 id＝正整數（存在與否在開匯款申請時才查——供應商主檔是別的模組維護的）。"""
    if isinstance(v, bool) or v in (None, ""):
        return False
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False


def _valid_order(o: dict):
    """基本驗證（與專屬端點同一組）；回 None＝合法，否則回錯誤訊息。"""
    name = o.get("itemName") or o.get("itemId")
    try:
        q, p, t = float(o.get("quantity") or 0), float(o.get("unitPrice") or 0), float(o.get("totalPrice") or 0)
    except (TypeError, ValueError):
        return "數量、單價、小計必須是數字（%s）" % name
    if q < 0 or p < 0 or t < 0:
        return "數量、單價、小計不能為負（%s）" % name
    if abs(t - q * p) > 0.01:
        return "%s 小計計算錯誤（%s×%s≠%s）" % (name, q, p, t)
    st = o.get("paidStatus") or "pending"
    if st not in ("pending", "partial", "paid"):
        return "paidStatus 必須是 pending/partial/paid（%s）" % name
    paid = float(o.get("paidAmount") or 0)
    if st == "pending" and (paid != 0 or o.get("paidDate")):
        return "待付狀態不能有已付金額或日期（%s）" % name
    if st != "pending" and (paid < 0 or paid > t or not o.get("paidDate")):
        return "已付金額必須 0 ~ 小計且要填日期（%s）" % name
    try:
        normalize_date(o.get("invoiceDate") or "", "發票日期（%s）" % name)
        normalize_date(o.get("paidDate") or "", "已付日期（%s）" % name)
    except Exception as e:                                                          # noqa: BLE001 — HTTPException
        return getattr(e, "detail", None) or str(e)
    return None


def _load_old(conn, quote_no: str):
    r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not r:
        return [], []
    try:                                                                              # 逐筆在 Python 解析（不用 json_extract：壞的一筆不可讓整個查詢丟例外；§G5 #2）
        cr = (json.loads(r["data_json"] or "{}") or {}).get("caseRecord") or {}
    except (TypeError, ValueError, AttributeError):
        cr = {}
    cr = cr if isinstance(cr, dict) else {}

    def _j(v):
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    return _j(cr.get("materialOrders")), _j(cr.get("materials"))


def enforce(conn, quote_no: str, data: dict, actor=None) -> list:
    """就地修正 `data["caseRecord"]` 的叫料與物流旗標，使其符合審核規則；回 `rejected[]`。冪等。**不 commit**。"""
    cr = data.get("caseRecord") if isinstance(data, dict) else None
    if not isinstance(cr, dict):
        return []
    has_orders, has_mats = "materialOrders" in cr, "materials" in cr
    if not (has_orders or has_mats):
        return []
    old_orders, old_mats = _load_old(conn, quote_no)
    rejected = []
    if has_orders:
        cr["materialOrders"] = _gate_orders(conn, quote_no, old_orders, cr.get("materialOrders"), actor, rejected)
    result_orders = cr.get("materialOrders") if has_orders else old_orders
    if has_mats:
        cr["materials"] = _gate_materials(conn, quote_no, old_mats, cr.get("materials"), [o for o in (result_orders or []) if isinstance(o, dict)], rejected)
    return rejected


def _gate_orders(conn, quote_no, old_list, new_list, actor, rejected):
    paid_only = MA.PAID_VIA_REMITTANCE_ONLY                                           # 讀模組屬性（測試以 monkeypatch 改它）
    allow = can_edit_orders(actor)
    user = actor or {"username": "system", "role": "system", "display_name": "系統"}
    old_by = {str(o.get("itemId")): o for o in old_list}
    out, seen = [], set()
    for no in (new_list if isinstance(new_list, list) else []):
        if not isinstance(no, dict) or not str(no.get("itemId") or ""):
            _rej(rejected, "", "itemId", "invalid", "叫料列缺少 itemId，已忽略")
            continue
        iid = str(no["itemId"])
        seen.add(iid)
        old = old_by.get(iid)
        if old is None:                                                                  # ── 新列
            if not allow:
                _rej(rejected, iid, "*", "no_permission", "只有管理員或專案經理（且有財務檢視權）可以新增叫料")
                continue
            msg = _valid_order(no)
            if msg:
                _rej(rejected, iid, "*", "invalid", msg)
                continue
            if MA.SUPPLIER_REQUIRED_ON_NEW and actor is not None and not _valid_supplier_id(no.get("supplierId")):
                _rej(rejected, iid, "supplierId", "supplier_required", "新增叫料必須選擇供應商")
                continue
            row = dict(no)
            if paid_only and ((row.get("paidStatus") or "pending") != "pending" or float(row.get("paidAmount") or 0) or row.get("paidDate")):
                row.update({"paidStatus": "pending", "paidAmount": 0, "paidDate": ""})
                _rej(rejected, iid, "paidStatus", "paid_via_remittance", "已付款只能經匯款申請登錄，已改為待付")
            MA.create_draft(conn, quote_no, iid, user, "新增叫料")
            out.append(row)
            continue
        merged = dict(old)                                                               # ── 既有列：以現值為底
        diff = {k: v for k, v in no.items() if not _same(k, v, old.get(k))}
        if not diff:
            out.append(merged)
            continue
        if not allow:
            _rej(rejected, iid, "*", "no_permission", "只有管理員或專案經理（且有財務檢視權）可以修改叫料")
            out.append(merged)
            continue
        st = MA.status_of(conn, quote_no, iid)
        cand = dict(old)
        cand.update(no)
        msg = _valid_order(cand)
        if msg:
            _rej(rejected, iid, "*", "invalid", msg)
            out.append(merged)
            continue
        if MA.substantive_changed(old, cand):
            if MP.has_live_payments(conn, quote_no, iid):                                # 已有匯款申請：金額／品名等變動會讓申請與額度對不上
                _rej(rejected, iid, "*", "has_payments", "這張叫料單已有匯款申請，請先作廢申請再修改內容")
                out.append(merged)
                continue
            r = MA.on_substantive_change(conn, quote_no, iid, user)
            if not r["allowed"]:
                _rej(rejected, iid, "*", r["reason"], "「%s」狀態的叫料單不可修改內容（請先撤回，或已取消的單不可再改）" % st if r["reason"] == "in_approval" else "已取消的叫料單不可修改")
                out.append(merged)
                continue
            for k in MA.SUBSTANTIVE_KEYS:
                if k in no:
                    merged[k] = no[k]
        for k, v in diff.items():
            if k in MA.SUBSTANTIVE_KEYS:
                continue
            if k in _PAID_KEYS and paid_only:
                _rej(rejected, iid, k, "paid_via_remittance", "已付款只能經匯款申請登錄")
                continue
            if k == "invoiceDate" and st in MA.IN_FLIGHT:
                _rej(rejected, iid, k, "in_approval", "審核中的叫料單不可改發票日期")
                continue
            merged[k] = v
        out.append(merged)
    for iid, old in old_by.items():                                                      # ── 被刪掉的列
        if iid in seen:
            continue
        st = MA.status_of(conn, quote_no, iid)
        if not allow:
            _rej(rejected, iid, "*", "no_permission", "只有管理員或專案經理（且有財務檢視權）可以刪除叫料")
            out.append(old)
        elif MP.has_any_payments(conn, quote_no, iid):
            _rej(rejected, iid, "*", "delete_blocked", "這張叫料單有匯款申請紀錄，不可刪除")
            out.append(old)
        elif st in MA.IN_FLIGHT or st in (MA.S_APPROVED, MA.S_CANCELLED):
            _rej(rejected, iid, "*", "delete_blocked", "審核中或已核准的叫料單不可刪除（請先撤回，或改用取消）")
            out.append(old)
        elif st:                                                                         # 草稿／已退回：連審核單一起刪
            conn.execute("DELETE FROM case_material_approvals WHERE quote_no=? AND item_id=?", (quote_no, iid))
    return out


def _gate_materials(conn, quote_no, old_list, new_list, orders, rejected):
    rows = MA.rows_for_case(conn, quote_no)
    order_ids = {str(o.get("itemId")) for o in orders}
    old_by = {str(m.get("id")): m for m in old_list}
    out = []
    for nm in (new_list if isinstance(new_list, list) else []):
        if not isinstance(nm, dict):
            continue
        mid = str(nm.get("id"))
        om = old_by.get(mid)
        m = dict(nm)
        link_new = str(m.get("orderItemId") or "")
        link_old = str((om or {}).get("orderItemId") or "")
        if link_new != link_old and link_new and link_new not in order_ids:
            _rej(rejected, mid, "orderItemId", "bad_link", "連結的叫料單不存在")
            m["orderItemId"] = (om or {}).get("orderItemId") or ""
            link_new = link_old
        link = link_new or link_old
        reverted_arrival = False
        for flag in _FLAGS:
            want, had = bool(m.get(flag)), bool((om or {}).get(flag))
            if not want or had:
                continue
            row = rows.get(link) if link else None
            if not link or row is None or row["status"] != MA.S_APPROVED:
                _rej(rejected, mid, flag, "order_not_approved", "必須先連結一張已核准的叫料單，才能標記%s" % ("已叫料" if flag == "ordered" else "已到料"))
            elif flag == "arrived" and not row["received_on"]:
                _rej(rejected, mid, flag, "receipt_missing", "請先在叫料單上確認到貨（日期與確認人），才能標記已到料")
            else:
                continue
            m[flag] = had
            if flag == "arrived":
                reverted_arrival = True
        if reverted_arrival and "devices" in m:
            m["devices"] = (om or {}).get("devices") or []                       # 序號不隨被拒的到料進來（庫存認領的前一道）
        out.append(m)
    return out
