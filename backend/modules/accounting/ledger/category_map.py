# -*- coding: utf-8 -*-
"""費用類別 → 會計科目對應（`gl_category_map`）與費用類別清單（`expense_categories`）——G1，2026-10-01。

設計（docs：proposal-expense-forms.md §9、GL-BASE-HOOKS.md）：
- 來源模組（費用單據）只回**費用類別代碼**（事件行的 `category`）、含稅金額、選填稅額 `tax`、憑證種類 `doc_type`；**不知道任何科目**。
- 引擎收集事件時呼叫 `apply_category_map`（比照 `contract.apply_annotations`）：查對應表決定借方科目與可否扣抵進項稅額。
  ① 有對應（`gl_category_map.source='extra_expense'`）⇒ 用對應的角色／科目；② 沒對應 ⇒ 有案件＝專案成本 `COST_PROJECT`、
  **無案件＝其他營業費用 `EXP_OTHER`，絕不用專案成本**，並在 `meta.category_unmapped` 記下代碼（notice 由引擎彙整）。
- 稅額：行有 `tax`（>0）⇒ 費用＝含稅金額−稅額，另列進項稅額 `INPUT_TAX`（稅碼 IN-5，事件稅碼 IN-5，進 401 進項）——**僅當** `doc_type=='invoice'`
  （統一發票）且該類別 `nondeductible=0`；收據、國外憑證、不得扣抵類別 ⇒ 稅額併入費用、不產生進項稅額列、不帶稅碼。沒有 `tax` ⇒ 整筆含稅全額列費用。
- 費用類別代碼發布後不可改（單據存的是代碼）；`expense_categories` 改名只改 `name`，停用用 `active=0`。
所有函式不 commit。
"""
import re

SOURCE_EXPENSE = "extra_expense"
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}$")
_ROLE_INPUT_TAX, _ROLE_COST, _ROLE_OTHER = "INPUT_TAX", "COST_PROJECT", "EXP_OTHER"      # 帳務角色名（常數，非使用者角色）


class CategoryError(ValueError):
    pass


# ── 費用類別清單 ──────────────────────────────────────────────────────

def list_categories(conn, only_active=False):
    q = "SELECT code, name, default_tax, active, sort, note FROM expense_categories"
    if only_active:
        q += " WHERE active=1"
    return [dict(r) for r in conn.execute(q + " ORDER BY sort, code")]


def upsert_category(conn, code, name, default_tax="", sort=0, note="", active=True):
    code = str(code or "").strip()
    if not _CODE.match(code):
        raise CategoryError("費用類別代碼只能用英數字、底線、連字號（最長 40 字），例：travel_fare。")
    name = str(name or "").strip()
    if not name:
        raise CategoryError("費用類別名稱不可空白。")
    if default_tax not in ("", "taxable", "exempt", "none"):
        raise CategoryError("預設稅別只能是：空白、taxable、exempt、none。")
    old = conn.execute("SELECT name FROM expense_categories WHERE code=?", (code,)).fetchone()
    conn.execute("INSERT INTO expense_categories(code, name, default_tax, active, sort, note) VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(code) DO UPDATE SET name=excluded.name, default_tax=excluded.default_tax, active=excluded.active, sort=excluded.sort, note=excluded.note",
                 (code, name, default_tax, 1 if active else 0, int(sort or 0), str(note or "")[:200]))
    return {"code": code, "previous_name": old[0] if old else None}


# ── 對應表 ──────────────────────────────────────────────────────────

def list_map(conn, source=SOURCE_EXPENSE):
    return [dict(r) for r in conn.execute("SELECT source, category, role, account_code, nondeductible, note FROM gl_category_map WHERE source=? ORDER BY category", (source,))]


def upsert_map(conn, category, account_code="", role="", nondeductible=False, note="", source=SOURCE_EXPENSE):
    category = str(category or "").strip()
    if not category:
        raise CategoryError("費用類別代碼不可空白。")
    account_code = str(account_code or "").strip()
    role = str(role or "").strip()
    if not account_code and not role:
        raise CategoryError("要指定會計科目（或帳務角色）。")
    if account_code:
        a = conn.execute("SELECT m.postable, m.is_active FROM gl_account_meta m WHERE m.code=?", (account_code,)).fetchone()
        if a is None:
            raise CategoryError("科目 %s 不存在。" % account_code)
        if not a[0] or not a[1]:
            raise CategoryError("科目 %s 不能入帳（非明細科目或已停用）。" % account_code)
    if role:
        from modules.accounting.ledger.roles import DEFAULT_ROLES
        if role not in DEFAULT_ROLES:
            raise CategoryError("不認得的帳務角色：%s。" % role)
    old = conn.execute("SELECT role, account_code, nondeductible FROM gl_category_map WHERE source=? AND category=?", (source, category)).fetchone()
    conn.execute("INSERT INTO gl_category_map(source, category, role, account_code, nondeductible, note) VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(source, category) DO UPDATE SET role=excluded.role, account_code=excluded.account_code, nondeductible=excluded.nondeductible, note=excluded.note",
                 (source, category, role, account_code, 1 if nondeductible else 0, str(note or "")[:200]))
    return {"previous": dict(old) if old else None}


def delete_map(conn, category, source=SOURCE_EXPENSE):
    old = conn.execute("SELECT role, account_code, nondeductible FROM gl_category_map WHERE source=? AND category=?", (source, category)).fetchone()
    if old is None:
        raise CategoryError("找不到這筆對應。")
    conn.execute("DELETE FROM gl_category_map WHERE source=? AND category=?", (source, category))
    return dict(old)


def coverage(conn):
    """每個啟用中的費用類別是否已有對應 ⇒ `{code, name, mapped, account_code, nondeductible}`（畫面列出『未設定』）。"""
    m = {r["category"]: r for r in list_map(conn)}
    return [{"code": c["code"], "name": c["name"], "mapped": c["code"] in m, "account_code": (m.get(c["code"]) or {}).get("account_code", ""),
             "role": (m.get(c["code"]) or {}).get("role", ""), "nondeductible": bool((m.get(c["code"]) or {}).get("nondeductible"))}
            for c in list_categories(conn, only_active=True)]


# ── 引擎收集時套用（來源模組不知道科目）────────────────────────────────

def apply_category_map(conn, ev):
    """事件行帶 `category`（費用類別代碼）者：決定借方科目與拆稅（規則見模組說明）。沒有任何行帶 category ⇒ 原樣回傳（舊式事件完全不變）。"""
    lines = ev.get("lines") or []
    if not any(ln.get("category") for ln in lines):
        return ev
    cmap = {r["category"]: r for r in list_map(conn)}
    unmapped, out, tax_total = [], [], 0
    for ln in lines:
        cat = ln.get("category")
        if not cat or ln.get("side") != "D":
            out.append(ln)
            continue
        ln = dict(ln)
        m = cmap.get(cat)
        if m:
            if m["account_code"]:
                ln["account_code"] = m["account_code"]
            if m["role"]:
                ln["role"] = m["role"]
        else:
            ln["role"] = _ROLE_COST if (ln.get("case_no") or ev.get("case_no")) else _ROLE_OTHER
            unmapped.append(cat)
        tax = ln.pop("tax", 0) or 0
        doc_type = ln.pop("doc_type", "")
        deductible = bool(tax) and doc_type == "invoice" and not (m and m["nondeductible"])
        if tax and 0 < tax < ln["amount"]:
            if deductible:
                ln["amount"] -= tax
                out.append(ln)
                out.append({"role": _ROLE_INPUT_TAX, "side": "D", "amount": tax, "memo": ln.get("memo", ""), "tax_code": "IN-5"})
                tax_total += tax
                continue
            ev.setdefault("meta", {}).setdefault("tax_folded_into_cost", []).append(cat)      # 稅額併入費用（收據／國外憑證／不得扣抵）
        out.append(ln)
    ev["lines"] = out
    meta = ev.setdefault("meta", {})
    if unmapped:
        meta["category_unmapped"] = sorted(set(unmapped))
    if tax_total:
        ev["tax_code"] = "IN-5"
    return ev
