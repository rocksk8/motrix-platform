# -*- coding: utf-8 -*-
"""`AC2`：營運報表的認列口徑（權責／現金）與「待補登」標註。

使用者規則（2026-09-24，細部由 hichan-0a 依規則裁）：

```
                 權責（預設，損益）                          現金（實際收付）
收入   成交**未稅** × 階段比例，認列在階段完成月         實收（含稅），依收款日
       沒設比例 ⇒ 全部階段完成月（MAX(done_at)）一次認列
       沒完工 ⇒ 不認列，列「未完工」
       比例合計 ≠ 100% ⇒ 照比例認列、不補差，標註
支出   派工    發票日；沒登錄 ⇒ 驗收日 ⇒ 派工日（暫用，標註）   匯款申請已匯款日（含稅）
       叫料    發票日；沒登錄 ⇒ 付款日（暫用，標註）           付款日、已付金額
       額外支出 發票日；沒登錄 ⇒ 核准日 ⇒ 憑證日（暫用，標註） 付款日；沒登錄 ⇒ 憑證日（標註）
       金額    拆得出稅就用未稅（派工承攬商部分），拆不出用全額並標「未拆稅」
```
⚠️ 日期欄位 '' ＝未登錄：一律用 `== ''` 判斷，不拿 '' 和日期比大小。
⚠️ `ratio_bp` NULL ＝未設、0 ＝這個階段不認列——兩件事。
"""
import json
import logging
from datetime import date

from fastapi import HTTPException

from helpers.quotations import round_half_up, quote_tax_type

_log = logging.getLogger(__name__)

BASES = ("accrual", "cash")
FULL_BP = 10000

#: 待補登標註的種類 → 畫面標題
FLAG_LABELS = {
    "dispatch_no_invoice": "派工未登錄廠商發票（暫用驗收／派工月）",
    "material_no_invoice": "叫料未登錄廠商發票（暫用付款月）",
    "extra_no_invoice":    "額外支出未登錄廠商發票（暫用核准／憑證月）",
    "extra_no_paid_date":  "額外支出未登錄付款日（現金口徑暫用憑證日）",
    "stage_ratio_unset":   "階段比例未設定（全部完工月一次認列）",
    "stage_ratio_not_100": "階段比例合計不等於 100%（照比例認列、不補差）",
    "case_incomplete":     "未完工不認列（尚有階段未完成）",
    "legacy_tax":          "舊 1～4% 稅率單（非法定稅率，請會計確認）",
}

#: 待補登連結開案件頁的哪個分頁（2026-09-24 使用者裁：開對應分頁）＝那筆資料實際登錄的地方。
#: 每個 FLAG_LABELS 的 key 都要在這裡有決定（tests 守門）；None ＝ 不帶分頁。
FLAG_TABS = {
    "dispatch_no_invoice": "dispatch",   # 派工的廠商發票日登在承攬商分頁
    "material_no_invoice": "fin",        # 叫料在財務分頁
    "extra_no_invoice":    "xexp",       # 額外支出分頁
    "extra_no_paid_date":  "xexp",
    "stage_ratio_unset":   "exec",       # 階段比例在執行分頁
    "stage_ratio_not_100": "exec",
    "case_incomplete":     "exec",
    "legacy_tax":          None,         # 稅率在報價單本身，案件頁沒有對應分頁
}

#: 報表頂端的口徑說明（使用者：「數字不同的部分，在營運報表內可註明並且標註」）
BASIS_NOTES = {
    "accrual": ("本報表預設採權責口徑：收入依案件階段完成月認列（未稅），支出依廠商發票月認列"
                "（拆得出稅額的用未稅，拆不出的用全額並標示）；叫料已納入支出。"
                "與舊版報表（收入依收款日、支出依派工日且未含叫料）數字不同屬正常。"
                "尚未補登發票日期或階段比例的單據，會暫用其他日期並列在下方「待補登」清單。"),
    "cash":    ("現金口徑：收入依實際收款日（含稅），支出依實際付款日（含稅）："
                "派工以匯款申請的已匯款日為準，叫料以付款日為準，額外支出以付款日為準"
                "（未登錄者暫用憑證日並標示）。"),
}


def normalize_basis(v):
    v = (v or "accrual").strip()
    if v not in BASES:
        raise HTTPException(400, "basis 只能是 accrual（權責）或 cash（現金）")
    return v


def normalize_date(v, label="日期"):
    """'' ＝未登錄；否則必須是 YYYY-MM-DD 的真實日期。回正規化後的字串。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)
    v = v.strip()
    # 日期欄可能是 datetime 字串以外的東西；只接受整 10 碼的日期
    if v == "":
        return ""
    if len(v) != 10:
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)


def normalize_ratio_bp(v):
    """None／'' ⇒ None（未設）；否則 0～10000 的整數。"""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    if isinstance(v, bool):
        raise HTTPException(400, "階段比例格式不正確")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "階段比例格式不正確")
    if f != int(f) or not (0 <= f <= FULL_BP):
        raise HTTPException(400, "階段比例需為 0～100%（以 0.01% 為單位）")
    return int(f)


# ══════════════════════════════════════════════════════════════════════
# 收入（權責）——純函式
# ══════════════════════════════════════════════════════════════════════

def stage_revenue(pretax, stages):
    """一張案件的權責收入。`stages`：[{label, done, doneAt, ratioBp}]。

    回 `{"entries": [{label, date, amount}], "flags": set, "unrecognized": 金額}`。
    """
    pretax = float(pretax or 0)
    flags = set()
    entries = []
    stages = list(stages or [])
    ratios = [s.get("ratioBp") for s in stages]
    if any(r is not None for r in ratios):
        total_bp = sum(r or 0 for r in ratios)
        if total_bp != FULL_BP:
            flags.add("stage_ratio_not_100")
        recognized = 0.0
        for s in stages:
            bp = s.get("ratioBp")
            if not bp:
                continue
            amt = round_half_up(pretax * bp / FULL_BP)
            done_at = (s.get("doneAt") or "")[:10]
            if s.get("done") and done_at != "":
                entries.append({"label": s.get("label") or "", "date": done_at, "amount": amt})
                recognized += amt
            else:
                flags.add("case_incomplete")
        unrecognized = round_half_up(pretax * total_bp / FULL_BP) - recognized
        return {"entries": entries, "flags": flags, "unrecognized": max(unrecognized, 0)}
    flags.add("stage_ratio_unset")
    done_dates = [(s.get("doneAt") or "")[:10] for s in stages]
    if stages and all(s.get("done") for s in stages) and all(d != "" for d in done_dates):
        entries.append({"label": "全部完工", "date": max(done_dates), "amount": round_half_up(pretax)})
        return {"entries": entries, "flags": flags, "unrecognized": 0}
    flags.add("case_incomplete")
    return {"entries": [], "flags": flags, "unrecognized": round_half_up(pretax)}


def _case_rows(conn, department_id=None):
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id, total, pretax,
               data_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    if department_id:
        dept = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users")}
        rows = [r for r in rows if dept.get(r["sales_person_id"]) == department_id]
    return rows


def _stages_by_quote(conn):
    out = {}
    for r in conn.execute("SELECT quote_no, label, done, done_at, ratio_bp FROM case_stages"
                          " ORDER BY quote_no, sort_order, id"):
        out.setdefault(r["quote_no"], []).append(
            {"label": r["label"], "done": bool(r["done"]), "doneAt": r["done_at"] or "",
             "ratioBp": r["ratio_bp"]})
    return out


def accrual_income_items(conn, d0, d1, department_id=None):
    """權責收入逐筆（形狀比照 `_collect_income_items`，讓既有表格照樣可用）。"""
    stages = _stages_by_quote(conn)
    items = []
    for row in _case_rows(conn, department_id):
        rev = stage_revenue(row["pretax"], stages.get(row["quote_no"], []))
        for e in rev["entries"]:
            if not (d0 <= e["date"] <= d1):
                continue
            items.append({
                "quoteNo": row["quote_no"], "customer": row["customer_name"] or "",
                "project": row["project_name"] or "", "salesPerson": row["sales_person"] or "",
                "type": e["label"], "amount": e["amount"], "receivedAt": e["date"],
                "recognizedAt": e["date"], "actualAmount": None, "feeAmount": 0,
                "netAmount": e["amount"], "invoiceNo": "", "taxNote": "未稅",
            })
    items.sort(key=lambda x: x["receivedAt"], reverse=True)
    return items


# ══════════════════════════════════════════════════════════════════════
# 支出——逐筆（兩種口徑共用同一份讀取，差在日期與金額）
# ══════════════════════════════════════════════════════════════════════

def _approved_at(approval_json):
    """簽核資料裡最後一個 approvedAt（YYYY-MM-DD）；沒有 ⇒ ''。"""
    try:
        appr = json.loads(approval_json or "{}") or {}
    except (TypeError, ValueError):
        return ""
    found = []

    def walk(x):
        if isinstance(x, dict):
            v = x.get("approvedAt")
            if isinstance(v, str) and v.strip():
                found.append(v.strip()[:10])
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(appr)
    return max(found) if found else ""


def dispatch_entries(conn, basis):
    """派工 → [{date, quoteNo, desc, amount, taxNote, provisional, dispatchId, invoiceDate}]。

    應計（accrual）要 M04 的 `dispatch.row` 連接器（INTEGRATION-POINTS.md IP-1）算派工金額；
    M04 不在 ⇒ 回 []（少了派工這一類，其餘收入／支出照常），並記 WARNING。
    現金（cash）讀匯款申請的快照，不需要連接器。
    """
    from core import registry
    out = []
    if basis == "cash":
        for r in conn.execute(
                "SELECT v.dispatch_id, v.quote_no, v.snapshot_json, v.paid_at, v.voucher_no"
                " FROM contractor_payment_vouchers v WHERE v.is_paid = 1"):
            paid = (r["paid_at"] or "")[:10]
            if paid == "":
                continue
            snap = json.loads(r["snapshot_json"] or "{}")
            out.append({"date": paid, "quoteNo": r["quote_no"] or "",
                        "desc": "%s（匯款申請 %s）" % (snap.get("vendorName") or "（外包人員點工）", r["voucher_no"]),
                        "amount": float(snap.get("grandTotal") or 0), "taxNote": "含稅",
                        "provisional": False, "dispatchId": r["dispatch_id"]})
        return out
    dispatch_row = registry.single_provider("dispatch.row")
    if dispatch_row is None:
        _log.warning("dispatch.row 沒有提供者（M04 未載入）⇒ 應計派工成本略過")
        return out
    for r in conn.execute(
            "SELECT cd.*, vc.name AS vendor_name FROM contractor_dispatches cd"
            " LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id WHERE cd.status != 'cancelled'"):
        d = dispatch_row(r)
        inv = (r["invoice_date"] or "")[:10]
        fallback = (d.get("acceptedAt") or "")[:10] or (r["dispatch_date"] or "")[:10]
        use = inv if inv != "" else fallback
        pretax = float(d["totalAmount"] or 0)
        personnel = float(d["personnelTotal"] or 0)
        amount = pretax + personnel
        if not amount:
            continue
        note = "未稅" if not personnel else ("外包人員未拆稅" if not pretax else "承攬商未稅＋外包人員未拆稅")
        out.append({"date": use, "quoteNo": r["quote_no"] or "",
                    "desc": d["vendorName"] or "（外包人員點工）", "amount": amount, "taxNote": note,
                    "provisional": inv == "", "dispatchId": r["id"], "invoiceDate": inv})
    return out


def material_entries(conn, basis, department_id=None):
    """叫料（案件 data_json）→ 逐筆。沒有稅欄位 ⇒ 一律「未拆稅」。"""
    out = []
    for row in _case_rows(conn, department_id):
        try:
            cr = (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
        except (TypeError, ValueError):
            cr = {}
        for mo in cr.get("materialOrders") or []:
            if not isinstance(mo, dict):
                continue
            name = mo.get("itemName") or "叫料"
            paid = (mo.get("paidDate") or "")[:10]
            if basis == "cash":
                if (mo.get("paidStatus") or "pending") == "pending" or paid == "":
                    continue
                amt = float(mo.get("paidAmount") or 0)
                if amt:
                    out.append({"date": paid, "quoteNo": row["quote_no"], "desc": "叫料｜" + name,
                                "amount": amt, "taxNote": "未拆稅", "provisional": False,
                                "itemId": mo.get("itemId") or ""})
                continue
            amt = float(mo.get("totalPrice") or 0)
            if not amt:
                continue
            inv = (mo.get("invoiceDate") or "")[:10]
            out.append({"date": inv if inv != "" else paid, "quoteNo": row["quote_no"],
                        "desc": "叫料｜" + name, "amount": amt, "taxNote": "未拆稅",
                        "provisional": inv == "", "itemId": mo.get("itemId") or "", "invoiceDate": inv})
    return out


def extra_entries(conn, basis):
    """額外支出 → 逐筆。沿用既有規則：金額 0 不列；送審中照樣計入（pending 標示）。"""
    out = []
    for r in conn.execute(
            "SELECT e.id, e.quote_no, e.category, e.description, e.total_cost, e.expense_date,"
            " e.created_at, e.doc_no, e.files_json, e.status, e.approval_json, e.invoice_date,"
            " e.paid_date, q.customer_name FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no ORDER BY e.id"):
        cost = float(r["total_cost"] or 0)
        if not cost:
            continue
        voucher_day = (r["expense_date"] or r["created_at"] or "")[:10]
        inv, paid = (r["invoice_date"] or "")[:10], (r["paid_date"] or "")[:10]
        if basis == "cash":
            use, provisional = (paid, False) if paid != "" else (voucher_day, True)
        else:
            use = inv if inv != "" else (_approved_at(r["approval_json"]) or voucher_day)
            provisional = inv == ""
        desc = r["description"] or r["category"] or ""
        if r["doc_no"]:
            desc = "%s（單號 %s）" % (desc, r["doc_no"])
        try:
            files = json.loads(r["files_json"] or "[]")
        except (TypeError, ValueError):
            files = []
        out.append({"date": use, "quoteNo": r["quote_no"] or "",
                    "desc": "%s｜%s｜%s" % (r["customer_name"] or "", r["category"] or "其他", desc),
                    "amount": cost, "taxNote": "未拆稅", "provisional": provisional,
                    "pending": r["status"] != "已核准", "files": files, "expenseId": r["id"],
                    "category": r["category"] or "其他",
                    "invoiceDate": inv, "paidDate": paid})
    return out


# ══════════════════════════════════════════════════════════════════════
# 待補登標註
# ══════════════════════════════════════════════════════════════════════

def _flag_item(quote_no, customer, doc, desc, amount, day, money_ok, kind):
    tab = FLAG_TABS[kind]
    link = "case-management.html?q=%s" % quote_no + ("&tab=%s" % tab if tab else "")
    return {"quoteNo": quote_no, "customer": customer or "", "doc": doc, "desc": desc,
            "amount": (round_half_up(amount) if amount is not None else None) if money_ok else None,
            "date": day, "link": link}


#: IP-1 缺席時對使用者說的話（稽核 X-1：不可以跟「0 筆」長得一樣）
DISPATCH_UNAVAILABLE = {"category": "contractor",
                        "reason": "外包工班模組未安裝：承攬商派工的應計成本沒有列入（不是 0 筆）"}


def dispatch_unavailable(basis="accrual"):
    """`[]`＝承攬商派工這一類有算進來；否則 `[{category, reason}]`。

    權責口徑經 IP-1 `dispatch.row` 讀派工單；提供者不在 ⇒ 這一類整個缺。
    現金口徑讀匯款申請快照，不受影響 ⇒ 永遠 `[]`。"""
    from core import registry
    if basis == "cash" or registry.single_provider("dispatch.row") is not None:
        return []
    return [dict(DISPATCH_UNAVAILABLE)]


def recognition_flags(conn, year, department_id=None, money_ok=True):
    """`{kind: {label, count, items}}`。支出類只列歸在 `year` 的；案件類不分期別。

    `money_ok=False`（CM13 money_visible 為否）⇒ 金額一律 None。
    """
    y = str(year)
    flags = {k: [] for k in FLAG_LABELS}
    cases = _case_rows(conn, department_id)
    in_scope = {r["quote_no"] for r in cases}
    customer = {r["quote_no"]: r["customer_name"] for r in cases}

    for e in dispatch_entries(conn, "accrual"):
        if e["quoteNo"] in in_scope and e["provisional"] and (e["date"][:4] == y or e["date"] == ""):
            flags["dispatch_no_invoice"].append(_flag_item(
                e["quoteNo"], customer.get(e["quoteNo"]), "派工 #%s" % e["dispatchId"], e["desc"],
                e["amount"], e["date"], money_ok, "dispatch_no_invoice"))
    for e in material_entries(conn, "accrual", department_id):
        if e["provisional"] and (e["date"][:4] == y or e["date"] == ""):
            flags["material_no_invoice"].append(_flag_item(
                e["quoteNo"], customer.get(e["quoteNo"]), "叫料", e["desc"], e["amount"], e["date"], money_ok, "material_no_invoice"))
    for e in extra_entries(conn, "accrual"):
        if e["quoteNo"] not in in_scope:
            continue
        if e["provisional"] and e["date"][:4] == y:
            flags["extra_no_invoice"].append(_flag_item(
                e["quoteNo"], customer.get(e["quoteNo"]), "額外支出 #%s" % e["expenseId"], e["desc"],
                e["amount"], e["date"], money_ok, "extra_no_invoice"))
        if e["paidDate"] == "" and e["date"][:4] == y:
            flags["extra_no_paid_date"].append(_flag_item(
                e["quoteNo"], customer.get(e["quoteNo"]), "額外支出 #%s" % e["expenseId"], e["desc"],
                e["amount"], e["date"], money_ok, "extra_no_paid_date"))

    stages = _stages_by_quote(conn)
    for r in cases:
        rev = stage_revenue(r["pretax"], stages.get(r["quote_no"], []))
        for kind in ("stage_ratio_unset", "stage_ratio_not_100", "case_incomplete"):
            if kind in rev["flags"]:
                amt = rev["unrecognized"] if kind == "case_incomplete" else r["pretax"]
                flags[kind].append(_flag_item(r["quote_no"], r["customer_name"], "案件",
                                              r["project_name"] or "", amt, "", money_ok, kind))
        try:
            data = json.loads(r["data_json"] or "{}") or {}
        except (TypeError, ValueError):
            data = {}
        if quote_tax_type(data) == "legacy":
            flags["legacy_tax"].append(_flag_item(r["quote_no"], r["customer_name"], "報價單",
                                                  "稅率 %s%%" % data.get("taxRate"), r["total"], "", money_ok, "legacy_tax"))
    return {k: {"label": FLAG_LABELS[k], "count": len(v), "items": v} for k, v in flags.items()}
