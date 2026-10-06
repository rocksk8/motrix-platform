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

from helpers.dates import normalize_date  # noqa: F401  2026-09-26 下沉 L1（M04 搬遷）；本檔與 M01 呼叫端照舊從這裡取
from modules.case import expense_forms as _EF      # 請購單（purchase_req）不入支出：payable_sql
from modules.case.quotations import round_half_up, quote_tax_type

_log = logging.getLogger(__name__)

# 口徑的純標籤（BASES／BASIS_NOTES／normalize_basis）2026-09-26 下沉 L1 helpers/recognition_basis.py；這裡保留同名別名
from helpers.recognition_basis import BASES, BASIS_NOTES, normalize_basis  # noqa: E402,F401
FULL_BP = 10000

#: 待補登標註的種類 → 畫面標題
FLAG_LABELS = {
    "dispatch_no_invoice": "派工未登錄廠商發票（暫用驗收／派工月）",
    "material_no_invoice": "材料申請未登錄廠商發票（暫用付款月）",
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


def _case_rows(conn, department_id=None, quote_no=None):
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id, total, pretax,
               data_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """ + (" AND quote_no=?" if quote_no else ""), (quote_no,) if quote_no else ()).fetchall()
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


def _snap_tax(snap, actual) -> float:
    """現金口徑承攬商匯款：快照的稅額（`taxAmount`；舊快照沒有就用 `totalWithTax − totalAmount`）；實付≠應付時依實付比例攤。沒有稅額資料 ⇒ 0。"""
    try:
        tax = float(snap.get("taxAmount") if snap.get("taxAmount") is not None else (float(snap.get("totalWithTax") or 0) - float(snap.get("totalAmount") or 0)))
        grand = float(snap.get("grandTotal") or 0)
    except (TypeError, ValueError):
        return 0.0
    if tax <= 0:
        return 0.0
    return tax * (actual / grand) if actual is not None and grand else tax


def dispatch_entries(conn, basis):
    """派工 → [{date, quoteNo, desc, amount, taxNote, provisional, dispatchId, invoiceDate}]。

    應計（accrual）要 M04 的 `dispatch.row` 連接器（INTEGRATION-POINTS.md IP-1）算派工金額；
    M04 不在 ⇒ 回 []（少了派工這一類，其餘收入／支出照常），並記 WARNING。
    現金（cash）讀匯款申請的快照，不需要連接器。
    """
    from core import registry
    out = []
    if basis == "cash":
        # W1：現金口徑用實付金額（remit_actual；舊資料或欄位未建 ⇒ 回退快照應付）；手續費另走 IP-9 expense.entries
        has_actual = any(c[1] == "remit_actual" for c in conn.execute("PRAGMA table_info(contractor_payment_vouchers)"))
        for r in conn.execute(
                "SELECT v.dispatch_id, v.quote_no, v.snapshot_json, v.paid_at, v.voucher_no%s"
                " FROM contractor_payment_vouchers v WHERE v.is_paid = 1" % (", v.remit_actual, v.remit_review" if has_actual else "")):
            paid = (r["paid_at"] or "")[:10]
            if paid == "":
                continue
            snap = json.loads(r["snapshot_json"] or "{}")
            out.append({"date": paid, "quoteNo": r["quote_no"] or "",
                        "desc": "%s（匯款申請 %s）" % (snap.get("vendorName") or "（外包人員點工）", r["voucher_no"]),
                        "amount": float(snap.get("grandTotal") or 0) if not has_actual or r["remit_actual"] is None
                        else float(r["remit_actual"]), "taxNote": "含稅", "tax": _snap_tax(snap, None if not has_actual or r["remit_actual"] is None else float(r["remit_actual"])),
                        "provisional": False, "dispatchId": r["dispatch_id"],
                        # W1：實付≠應付、待管理員核可 ⇒ 照計（已記錄）但報表標「差額待審核」
                        "remitPending": bool(has_actual and r["remit_review"] == "pending")})
        for e in out:
            e["taxKind"] = "exact" if e.get("tax") else ""
        return out
    dispatch_row = registry.single_provider("dispatch.row")
    if dispatch_row is None:
        _log.warning("dispatch.row 沒有提供者（M04 未載入）⇒ 應計派工成本略過")
        return out
    for r in conn.execute(
            "SELECT cd.*, vc.name AS vendor_name FROM contractor_dispatches cd"
            " LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id WHERE cd.status != 'cancelled'"):
        d = dispatch_row(r)
        ap = d.get("approvalStatus") or ""
        if ap in ("草稿", "已退回"):        # 31-A（Q6）：尚未承諾的支出不計入應計成本；待審核／簽核中照計並標示；已核准與舊單（''）照舊
            continue
        inv = (r["invoice_date"] or "")[:10]
        fallback = (d.get("acceptedAt") or "")[:10] or (r["dispatch_date"] or "")[:10]
        use = inv if inv != "" else fallback
        pretax = float(d["totalAmount"] or 0)
        personnel = float(d["personnelTotal"] or 0)
        amount = pretax + personnel
        if not amount:
            continue
        note = "未稅" if not personnel else ("外包人員未拆稅" if not pretax else "承攬商未稅＋外包人員未拆稅")
        tax, kind = 0.0, ""
        if (r["dispatch_date"] or "")[:10] >= DISPATCH_TAXED_FROM:       # 切換日以後的派發：含稅計入成本，稅額＝精確（派發單有稅額）
            tax = float(d["grandTotal"] or 0) - pretax - personnel
            amount, kind = pretax + personnel + tax, "exact"
            note = "含稅" if not personnel else ("外包人員未拆稅（承攬商含稅）" if not pretax else "承攬商含稅＋外包人員未拆稅")
        out.append({"date": use, "quoteNo": r["quote_no"] or "",
                    "desc": d["vendorName"] or "（外包人員點工）", "amount": amount, "taxNote": note,
                    "provisional": inv == "", "dispatchId": r["id"], "invoiceDate": inv,
                    "approvalPending": ap in ("待審核", "簽核中"), "tax": tax, "taxKind": kind})
    return out


def individual_linked_entries(conn, basis):
    """匯款單裡『已關聯勞報單』的個人外包金額 → [{date, dispatchId, amount}]（給『與總帳差異』頁的類別分桶）。

    為什麼要單獨列：營運報表的「承攬商派發」把個人外包（匯款單 personnel）算在承攬商裡；總帳對已關聯勞報單的個人改記勞報單（E06＝勞務費用，歸「其他」，
    見 subcontract/gl_events.py 的 `linked`：同一條規則——姓名非空且帶 payslipNo 者）。這兩邊的類別差就是這個金額。
    日期與 `dispatch_entries` 的報表口徑相同：現金＝匯款已付日（只算已付匯款單）；應計＝派工的認列日（取該派工**已付**匯款單上關聯的個人；
    應計派工本身沒有 payslipNo，關聯只存在匯款單快照）。只增函式，不改任何既有回傳。"""
    def _linked(snap):
        total = 0
        for q in (snap.get("personnel") or []):
            if isinstance(q, dict) and str(q.get("name") or "").strip() and str(q.get("payslipNo") or "").strip():
                total += int(round_half_up(q.get("amount") or 0))
        return total
    rows = conn.execute("SELECT dispatch_id, snapshot_json, paid_at FROM contractor_payment_vouchers WHERE is_paid = 1").fetchall()
    per_dispatch, out = {}, []
    for r in rows:
        try:
            amt = _linked(json.loads(r["snapshot_json"] or "{}"))
        except (TypeError, ValueError):
            continue
        if not amt:
            continue
        per_dispatch[r["dispatch_id"]] = per_dispatch.get(r["dispatch_id"], 0) + amt
        paid = (r["paid_at"] or "")[:10]
        if basis == "cash" and paid:
            out.append({"date": paid, "dispatchId": r["dispatch_id"], "amount": amt})
    if basis == "cash":
        return out
    return [{"date": e["date"], "dispatchId": e["dispatchId"], "amount": per_dispatch[e["dispatchId"]]}
            for e in dispatch_entries(conn, basis) if per_dispatch.get(e["dispatchId"])]


def _material_states(conn) -> dict:
    """叫料審核狀態 `{(quote_no, item_id): status}`（疊加表 `case_material_approvals`）；沒有列＝舊單；表不在（舊庫）⇒ 空。"""
    try:
        return {(r[0], r[1]): r[2] for r in conn.execute("SELECT quote_no, item_id, status FROM case_material_approvals")}
    except Exception:                                                              # noqa: BLE001 — 表還沒建（migration 之前）＝全部視為舊單
        return {}


def _qty_or_none(v):
    """材料申請數量 → float；缺、空、非數字（含 '²' 這類 isdigit() 為真但 float() 會丟錯的字元）→ None，不讓精算／報表端點因一格髒資料 500。"""
    try:
        f = float(v) if v not in (None, "") else None
        return f if f is None or f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def material_money_rows(conn, department_id=None, quote_no=None):
    """材料申請逐筆判定（**不分口徑**；營運報表、總帳 E12／E12b、完結精算共用的唯一原語，33-A1）。

    每筆 `{quoteNo, itemId, key, order, name, state, cost, linked, noPo, total}`：
    - `state`＝審核狀態（疊加表；'' ＝ 舊單）；`cost`＝`material_approval.cost_state`（excluded／pending／counted）。
    - `linked`＝連到**有效**採購單（`purchase_items._link_check`）⇒ 金額由採購單負責（單一歸屬，32-S4c）。
    - `noPo`＝沒連採購單且連結判定為 none（舊單、$0 不標）。`total`＝列上的 `totalPrice`。
    只含「已成案／已結案」案件（`_case_rows`）；`quote_no` 給了只取那一案。口徑（權責／現金）與日期由呼叫端決定。"""
    from modules.case import material_approval as _ma
    from modules.case import purchase_items as _pi
    states = _material_states(conn)
    out = []
    _po_cache = {}

    def po_rows_of(qn):
        if qn not in _po_cache:
            _po_cache[qn] = conn.execute(
                "SELECT id, kind, status, lines_json, doc_code FROM case_extra_expenses WHERE quote_no=? AND kind='purchase_order'", (qn,)).fetchall()
        return _po_cache[qn]
    for row in _case_rows(conn, department_id, quote_no):
        try:
            cr = (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
        except (TypeError, ValueError):
            cr = {}
        for mo in cr.get("materialOrders") or []:
            if not isinstance(mo, dict):
                continue
            qn = row["quote_no"]
            st = states.get((qn, str(mo.get("itemId"))), "")
            prs = po_rows_of(qn)
            linked = _pi._link_check(mo, prs)[0]
            out.append({"quoteNo": qn, "itemId": mo.get("itemId") or "", "key": (qn, str(mo.get("itemId"))), "order": mo,
                        "name": mo.get("itemName") or "材料申請", "quantity": _qty_or_none(mo.get("quantity")), "unit": str(mo.get("unit") or ""), "state": st, "cost": _ma.cost_state(st), "linked": linked,
                        "noPo": (not linked) and _pi.material_link_status(mo, prs, legacy=(st == ""))["state"] == "none",
                        "total": float(mo.get("totalPrice") or 0)})
    return out


#: 精算「全含稅」後營運報表承攬商成本的切換日（使用者 2026-10-06）：**派發單自己的日期欄位 `contractor_dispatches.dispatch_date`** ≥ 這天的派發，
#: 應計成本含稅（未稅承攬費＋稅額＋外包人員）；這天之前的派發照舊（未稅＋外包人員），既有月份的報表數字不變。現金口徑本來就是含稅／實付，不受影響。
DISPATCH_TAXED_FROM = "2026-10-01"


def estimated_tax(amount) -> float:
    """含稅金額、沒有稅額欄位時的推估稅額＝金額 − 金額÷1.05（假設進項稅 5%；標 taxKind＝estimated，不是單據事實）。"""
    a = float(amount or 0)
    return a - round_half_up(a / 1.05) if a > 0 else 0.0


def material_entries(conn, basis, department_id=None):
    """叫料（案件 data_json）→ 逐筆。沒有稅欄位 ⇒ 一律「未拆稅」。

    審核規則（31-C，與承攬商派發同一組）：**權責口徑**——草稿／已退回／已取消**不計**；待審核／簽核中**計入並標 `pending`**；已核准與舊單（沒有審核單
    **現金口徑**——付出去的錢是事實，不因審核狀態排除（只標 `pending`）。每筆帶 `approval`（'' ＝ 舊單）。
    逐筆判定來自 `material_money_rows`（33-A1 抽出；與完結精算共用）。"""
    from modules.case import material_payment as _mp
    pay_lines, pay_legacy = (_mp.lines_by_order(conn), _mp.legacy_by_order(conn)) if basis == "cash" else ({}, {})
    out = []
    no_po = {}                                    # (案件, 叫料 itemId) ⇒ 該叫料是否「未申請採購單」（S4c；只加備註，不改金額）
    for r in material_money_rows(conn, department_id):
        mo, name, st, cs = r["order"], r["name"], r["state"], r["cost"]
        row = {"quote_no": r["quoteNo"]}
        paid = (mo.get("paidDate") or "")[:10]
        if r["linked"]:
            continue        # 32-S4c：連到有效採購單 ⇒ 金額由採購單負責（成本進品項實際成本／額外支出的採購單列），叫料只是已叫／已到追蹤——權責與現金都不重複計
        no_po[r["key"]] = r["noPo"]
        if basis != "cash" and cs == "excluded":
            continue                                                           # 權責：草稿／已退回／已取消不計
        if basis == "cash":
            key = r["key"]
            if key in pay_legacy:                                              # 有匯款申請 ⇒ 讀付款明細（每筆一列）＋舊單歷史已付；不讀 JSON 的 paid*（那是投影）
                la, ld = pay_legacy[key]
                if la and ld:
                    out.append({"date": ld, "quoteNo": row["quote_no"], "desc": "材料申請｜" + name, "amount": la, "taxNote": "未拆稅", "provisional": False,
                                "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending", "lineId": "", "fee": 0.0,
                                "remitPending": False, "payMethod": "", "payAccountCode": ""})
                for ln in pay_lines.get(key, []):
                    if ln["amount"] and ln["paid_at"]:
                        out.append({"date": ln["paid_at"], "quoteNo": row["quote_no"], "desc": "材料申請｜" + name, "amount": ln["amount"], "taxNote": "未拆稅",
                                    "provisional": False, "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending",
                                    "lineId": str(ln["id"]), "fee": ln["fee"], "remitPending": ln["review"] == "pending",
                                    "payMethod": ln["pay_method"], "payAccountCode": ln["pay_account_code"], "paymentCode": ln["doc_code"]})
                continue
            if (mo.get("paidStatus") or "pending") == "pending" or paid == "":
                continue
            amt = float(mo.get("paidAmount") or 0)
            if amt:
                out.append({"date": paid, "quoteNo": row["quote_no"], "desc": "材料申請｜" + name,
                            "amount": amt, "taxNote": "未拆稅", "provisional": False,
                            "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending"})
            continue
        amt = r["total"]
        if not amt:
            continue
        inv = (mo.get("invoiceDate") or "")[:10]
        out.append({"date": inv if inv != "" else paid, "quoteNo": row["quote_no"],
                    "desc": "材料申請｜" + name, "amount": amt, "taxNote": "未拆稅",
                    "provisional": inv == "", "itemId": mo.get("itemId") or "", "invoiceDate": inv,
                    "approval": st, "pending": cs == "pending"})
    for e in out:
        e["noPo"] = bool(no_po.get((e["quoteNo"], str(e.get("itemId") or ""))))
        e["tax"], e["taxKind"] = estimated_tax(e["amount"]), "estimated"        # 材料申請沒有稅額欄位：含稅最終金額 ⇒ 推估稅額
    return out


#: 月支出計入的額外支出狀態（2026-09-27 使用者裁示請款流程）：送審中（待審核／簽核中，標 pending＝待定）與已核准；
#: 草稿與已駁回**不計**（原本「只要填了就算」）。權責與現金兩種口徑都走 extra_entries ⇒ 同一處決定。
COUNTED_EXTRA_STATUSES = ("待審核", "簽核中", "已核准")
#: 連到案件品項的採購單列在營運報表落哪一個支出桶（32-S3；使用者原話「不再額外支出，而是案件的實際支出」）。
#: 報價品項沒有分類（設備／料件）⇒ 一律「料件」；要拆設備需要品項分類欄位（另案）。
ITEM_COST_BUCKET = "material"


def _doc_tax(r, cost) -> float:
    """額外支出單據的稅額（費用單據 `tax` 欄；total_cost 是含稅金額）；現金口徑實付≠應付時依實付比例攤。沒有稅額（0／舊式簡單額外支出）⇒ 0。"""
    try:
        tax, total = float(r["tax"] or 0), float(r["total_cost"] or 0)
    except (TypeError, ValueError, IndexError, KeyError):
        return 0.0
    if tax <= 0 or total <= 0:
        return 0.0
    return tax * (cost / total) if abs(cost - total) > 0.005 else tax


def extra_entries(conn, basis, quote_no=None):
    """額外支出 → 逐筆。金額 0 不列；只計 COUNTED_EXTRA_STATUSES（送審中照樣計入、pending 標示；草稿與已駁回不計）。
    現金口徑：有付款日（出納登錄付款，IP-100）⇒ 用付款日、不是暫用；沒有 ⇒ 憑證日、暫用。"""
    out = []
    _live = {}

    def live_of(quote_no):
        if quote_no not in _live:
            from modules.case import purchase_items as _PI
            _live[quote_no] = _PI.load_live_item_ids(conn, quote_no) if quote_no else set()
        return _live[quote_no]
    for r in conn.execute(
            "SELECT e.id, e.quote_no, e.category, e.description, e.total_cost, e.expense_date,"
            " e.created_at, e.doc_no, e.files_json, e.status, e.approval_json, e.invoice_date,"
            " e.paid_date, e.remit_actual, e.remit_review, e.kind, e.doc_code, e.department_id, e.lines_json, e.tax, q.customer_name FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
            " WHERE e.status IN (%s) AND %s%s ORDER BY e.id" % (",".join("?" * len(COUNTED_EXTRA_STATUSES)), _EF.payable_sql("e"), " AND e.quote_no=?" if quote_no else ""),
            COUNTED_EXTRA_STATUSES + ((quote_no,) if quote_no else ())):
        cost = float(r["total_cost"] or 0)
        if not cost:
            continue
        if basis == "cash" and (r["paid_date"] or "") != "" and r["remit_actual"] is not None:
            cost = float(r["remit_actual"])                      # W1：現金口徑用實付金額
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
        base = {"date": use, "quoteNo": r["quote_no"] or "",
                "desc": "%s｜%s｜%s" % (r["customer_name"] or "", r["category"] or "其他", desc),
                "amount": cost, "taxNote": "未拆稅", "provisional": provisional,
                "pending": r["status"] != "已核准", "files": files, "expenseId": r["id"],
                "category": r["category"] or "其他", "description": r["description"] or "",
                "remitPending": basis == "cash" and paid != "" and r["remit_review"] == "pending",
                "tax": _doc_tax(r, cost), "taxKind": "exact" if _doc_tax(r, cost) else "unsplit",
                "invoiceDate": inv, "paidDate": paid}      # 舊版列不帶 departmentId（缺＝報表依案件推導；與 A2 前相同）；單據列在 _typed_entries 帶
        if not (r["kind"] or ""):
            out.append(base)                                     # 舊版列：一列一筆，**行為不變**
            continue
        out.extend(_typed_entries(r, base, cost, basis, paid, live_of))
    return out


def _typed_entries(r, base, cost, basis, paid, live_of=None) -> list:
    """費用單據（kind≠''）的營運報表列（A2）：依**費用類別逐類**一筆（讓「支出結構」看得出差旅／住宿…）、帶 `departmentId`（費用歸屬單位；
    無案件時部門維度靠它）、`kind`、`docCode`。明細加總對不上單據金額（不該發生）⇒ 退回一列（類別＝單據類別）；
    現金口徑實付≠應付 ⇒ 另加一筆「付款差額」（實付−應付），合計＝實付（與舊版現金口徑一致）。
    下游效應（R1）：營運報表支出＝Σ 這些列；總額仍等於 `total_cost`（現金口徑為實付）。"""
    try:
        lines = json.loads(r["lines_json"] or "[]")
    except (TypeError, ValueError):
        lines = []
    total = float(r["total_cost"] or 0)
    by_cat = {}
    for l in lines if isinstance(lines, list) else []:
        if isinstance(l, dict):
            k = l.get("categoryName") or l.get("category") or "其他"
            # 32-S3：採購單明細連到案件品項的列＝品項實際成本，獨立成列（帶 itemId／linkedItem；金額守恆：Σ 列＝單據金額）
            iid = str(l.get("itemId") or "").strip() if (r["kind"] or "") == "purchase_order" else ""
            if iid and live_of is not None and iid not in live_of(r["quote_no"]):
                iid = ""                                   # 品項已不在報價內 ⇒ 回到一般額外支出（錢不消失）
            by_cat[(k, iid)] = by_cat.get((k, iid), 0) + float(l.get("amount") or 0)
    common = {"departmentId": r["department_id"], "kind": r["kind"], "docCode": r["doc_code"] or ""}
    if not by_cat or abs(sum(by_cat.values()) - total) > 0.005:
        by_cat = {(r["category"] or "其他", ""): total}
    out = []
    for (cat, iid), amt in by_cat.items():
        if not amt:
            continue
        ent = {**base, **common, "amount": amt, "category": cat,
               "desc": "%s｜%s｜%s" % (r["doc_code"] or "", cat, r["description"] or "")}
        if iid:
            ent.update(itemId=iid, linkedItem=True, bucket=ITEM_COST_BUCKET)
        out.append(ent)
    # 稅額是單據層級：有稅額（exact）只放在第一列（Σ 列＝單據稅額，不重複計）；沒有稅額的採購單＝含稅最終金額 ⇒ 每列推估；其餘＝未拆稅（只列金額）
    doc_tax = base.get("tax") or 0
    for n, ent in enumerate(out):
        if doc_tax:
            ent["tax"], ent["taxKind"] = (doc_tax if n == 0 else 0.0), "exact"
        elif (r["kind"] or "") == "purchase_order":
            ent["tax"], ent["taxKind"] = estimated_tax(ent["amount"]), "estimated"
    if basis == "cash" and cost != total:
        out.append({**base, **common, "amount": cost - total, "category": "付款差額", "tax": 0.0, "taxKind": "",
                    "desc": "%s｜付款差額（實付 %g／應付 %g）" % (r["doc_code"] or "", cost, total)})
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
                e["quoteNo"], customer.get(e["quoteNo"]), "材料申請", e["desc"], e["amount"], e["date"], money_ok, "material_no_invoice"))
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
