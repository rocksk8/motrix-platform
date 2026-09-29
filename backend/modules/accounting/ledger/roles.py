# -*- coding: utf-8 -*-
"""科目屬性（gl_account_meta）與科目角色（gl_account_roles）。設計：proposal-gl/01-accounts.md。

法定科目（account_items.source='statutory'）被 v93 觸發器鎖死不可 UPDATE，所以總帳需要的屬性放獨立表，
以 code 對應；`ensure_meta` 只補缺的列（INSERT OR IGNORE），會計師改過的值不會被覆蓋。
"""
import re

#: 損益類（期末結轉歸零、期間報表只看當年）
PL_TYPES = ("revenue", "cost", "expense", "other_income", "other_expense", "tax", "oci")

_CONTRA_C_NAME = re.compile(r"累計|備抵|未實現利息|未賺得|貼現")
_CONTRA_D = {"2124", "3511", "4113", "4114", "4232"}
_CONTRA_C = {"5123", "5124", "5133", "5134"}
_NONOP_CREDIT = re.compile(r"收入|利益|迴轉")

# 報表列（04-reports.md §3）：依祖先鏈由近到遠找第一個命中的代號。code 級覆寫優先於群組。
_FS_BY_CODE = {"4113": "IS_REV_ALLOW", "4114": "IS_REV_ALLOW", "4232": "IS_REV_ALLOW"}
_FS_BY_GROUP = {
    "111": "BS_CA_CASH", "112": "BS_CA_FIN", "113": "BS_CA_FIN", "114": "BS_CA_FIN", "115": "BS_CA_FIN",
    "117": "BS_CA_FIN", "118": "BS_CA_NOTES", "119": "BS_CA_AR", "120": "BS_CA_AR", "121": "BS_CA_OTHER_AR",
    "122": "BS_CA_TAX", "123-124": "BS_CA_INV", "125": "BS_CA_BIO", "126-127": "BS_CA_PREPAID",
    "128": "BS_CA_OTHER",
    "131": "BS_NCA_FIN", "132": "BS_NCA_FIN", "133": "BS_NCA_FIN", "134": "BS_NCA_FIN", "136": "BS_NCA_FIN",
    "137": "BS_NCA_EQUITY_INV", "138": "BS_NCA_INVPROP", "139": "BS_NCA_PPE", "147": "BS_NCA_MINERAL",
    "148": "BS_NCA_BIO", "149-155": "BS_NCA_INTANGIBLE", "156": "BS_NCA_DTA", "157-158": "BS_NCA_OTHER",
    "211": "BS_CL_STB", "212": "BS_CL_STB", "213": "BS_CL_FIN", "214": "BS_CL_FIN", "215": "BS_CL_FIN",
    "216": "BS_CL_NOTES", "217": "BS_CL_AP", "218": "BS_CL_CONTRACT", "219-220": "BS_CL_OTHER_AP",
    "221": "BS_CL_TAX", "222": "BS_CL_ADV", "223": "BS_CL_LTD_CUR", "224": "BS_CL_PROV", "225": "BS_CL_OTHER",
    "23": "BS_NCL",
    "31": "BS_EQ_CAPITAL", "32": "BS_EQ_CAPSURPLUS", "33": "BS_EQ_RE", "34": "BS_EQ_OTHER", "35": "BS_EQ_TREASURY",
    "41": "IS_REV", "51": "IS_COST", "61": "IS_OPEX", "82": "IS_TAX", "84": "IS_DISCONT", "87": "IS_OCI",
}

#: 預設角色→科目（01-accounts.md §3）。只在該科目存在於 account_items 時才寫入。
DEFAULT_ROLES = {
    "CASH": "1111", "PETTY": "1112", "BANK": "1113", "AR": "1191", "ADV_RCPT": "2221", "OTHER_ADV": "2223",
    "OUTPUT_TAX": "2204", "INPUT_TAX": "1268", "TAX_CARRY": "1269", "TAX_PAYABLE": "2194",
    "INVENTORY": "1231", "AP": "2171", "ACCRUED": "2197", "OTHER_PAYABLE": "2206", "PAYROLL_PAYABLE": "2191",
    "WITHHOLD_TAX": "2252", "WITHHOLD_NHI": "2252",
    "REV_SALES": "4111", "SALES_ALLOW": "4114", "SALES_RETURN": "4113",
    "COGS": "5111", "COST_PROJECT": "5811", "COST_OTHER": "5911", "INV_LOSS": "5111",
    "EXP_LABOR": "6133", "EXP_SALARY": "6111", "EXP_DEPR": "6125", "EXP_BADDEBT": "6124", "EXP_OTHER": "6134",
    "FEE": "7243", "FA_PAYABLE": "2199", "GAIN_DISPOSAL": "7201", "LOSS_DISPOSAL": "7202",
    "INCOME_TAX_EXP": "8211", "INCOME_TAX_PAY": "2211", "PREPAID_TAX": "1222",
    "PL_SUMMARY": "3353", "RETAINED": "3351",
}
_TAX_ROLE_BY_CODE = {"1268": "input_tax", "2204": "output_tax", "2194": "tax_payable", "1269": "tax_carry"}


def _ancestors(code, parents):
    """自己開始往上的代號鏈（含自己）。防環。"""
    seen, out = set(), []
    while code and code not in seen:
        seen.add(code)
        out.append(code)
        code = parents.get(code)
    return out


def derive(code, name, chain, source="statutory", parent_meta=None):
    """回 `(acct_type, normal_side, is_contra, fs_line)`。`chain`＝自己到最上層的代號鏈。
    自訂科目（source='custom'）繼承最近一層有屬性的祖先。"""
    if source == "custom" and parent_meta:
        return (parent_meta["acct_type"], parent_meta["normal_side"], parent_meta["is_contra"],
                parent_meta["fs_line"])
    top = (chain[-1] if chain else code)[:1]
    if top == "1":
        typ, side = "asset", "D"
    elif top == "2":
        typ, side = "liability", "C"
    elif top == "3":
        typ, side = "equity", "C"
    elif top == "4":
        typ, side = "revenue", "C"
    elif top == "5":
        typ, side = "cost", "D"
    elif top == "6":
        typ, side = "expense", "D"
    elif top == "7":
        if _NONOP_CREDIT.search(name or ""):
            typ, side = "other_income", "C"
        else:
            typ, side = "other_expense", "D"
    else:  # 8：綜合損益總額群組
        if code.startswith("82"):
            typ, side = "tax", "D"
        elif code.startswith("87"):
            typ, side = "oci", "C"
        else:
            typ, side = "summary", "D"
    contra = 0
    if typ == "asset" and _CONTRA_C_NAME.search(name or "") or code in _CONTRA_C:
        contra, side = 1, "C"
    if code in _CONTRA_D:
        contra, side = 1, "D"
    fs = _FS_BY_CODE.get(code, "")
    if not fs:
        for c in chain:
            if c in _FS_BY_GROUP:
                fs = _FS_BY_GROUP[c]
                break
    if not fs and typ == "other_income":
        fs = "IS_NONOP_INC"
    if not fs and typ == "other_expense":
        fs = "IS_NONOP_EXP"
    return typ, side, contra, fs


def ensure_meta(conn):
    """補齊 gl_account_meta 缺的列（不覆蓋既有）。回新增筆數。不 commit。"""
    rows = conn.execute("SELECT code, name, parent_code, source FROM account_items").fetchall()
    have = {r[0]: r for r in conn.execute(
        "SELECT code, acct_type, normal_side, is_contra, fs_line FROM gl_account_meta")}
    parents = {r[0]: r[2] for r in rows}
    names = {r[0]: r[1] for r in rows}
    has_kids = {p for p in parents.values() if p}
    added = 0
    for code, name, parent, source in sorted(rows, key=lambda r: (len(r[0]), r[0])):
        if code in have:
            continue
        chain = _ancestors(code, parents)
        parent_meta = None
        if source == "custom":
            for anc in chain[1:]:
                m = have.get(anc)
                if m:
                    parent_meta = {"acct_type": m[1], "normal_side": m[2], "is_contra": m[3], "fs_line": m[4]}
                    break
        typ, side, contra, fs = derive(code, name, chain, source, parent_meta)
        conn.execute(
            "INSERT OR IGNORE INTO gl_account_meta(code, acct_type, normal_side, postable, is_contra, fs_line, tax_role)"
            " VALUES (?,?,?,?,?,?,?)",
            (code, typ, side, 0 if code in has_kids else 1, contra, fs, _TAX_ROLE_BY_CODE.get(code, "")))
        have[code] = (code, typ, side, contra, fs)
        added += 1
    # 後來長出子科目的葉節點：postable 隨之變 0（例：1113 加了銀行子科目）。人工設過的不動：只降不升。
    for code in has_kids:
        conn.execute("UPDATE gl_account_meta SET postable = 0 WHERE code = ? AND postable = 1", (code,))
    del names
    return added


def ensure_default_roles(conn):
    """把預設角色寫入 gl_account_roles（只補缺、只寫存在的科目）。回新增筆數。不 commit。"""
    codes = {r[0] for r in conn.execute("SELECT code FROM account_items")}
    have = {r[0] for r in conn.execute("SELECT role FROM gl_account_roles WHERE scope_type='' AND scope_key=''")}
    added = 0
    for role, code in DEFAULT_ROLES.items():
        if role in have or code not in codes:
            continue
        conn.execute("INSERT OR IGNORE INTO gl_account_roles(role, scope_type, scope_key, account_code, effective_from)"
                     " VALUES (?, '', '', ?, '')", (role, code))
        added += 1
    return added


def resolve_role(conn, role, scope_type="", scope_key="", on_date=""):
    """角色→科目代號。順序：scope 精確命中（生效日 ≤ on_date 取最近）→ 預設；都沒有回 None（呼叫端要說明缺哪個角色，不猜）。"""
    if not on_date:                       # 沒指定日期＝以今天的設定為準（未來才生效的科目不可提前套用）
        import datetime as _dt
        on_date = _dt.date.today().isoformat()

    def _pick(st, sk):
        rows = conn.execute(
            "SELECT account_code, effective_from FROM gl_account_roles WHERE role=? AND scope_type=? AND scope_key=?"
            " ORDER BY effective_from DESC", (role, st, sk)).fetchall()
        for code, eff in rows:
            if not eff or eff <= on_date:
                return code
        return None
    if scope_type:
        hit = _pick(scope_type, scope_key)
        if hit:
            return hit
    return _pick("", "")


def accounts_without_fs_line(conn):
    """守門用：可過帳、非停用、卻沒有報表列的科目（報表會悄悄漏算它們）。"""
    return [r[0] for r in conn.execute(
        "SELECT code FROM gl_account_meta WHERE postable=1 AND is_active=1 AND fs_line='' AND acct_type<>'summary'"
        " ORDER BY code")]
