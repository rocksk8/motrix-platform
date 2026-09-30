# -*- coding: utf-8 -*-
"""財務報表：資產負債表、綜合損益表（B2）。設計：proposal-gl/04-reports.md §2–§4。

資料來源＝已過帳傳票＋期初（`reports.trial_balance`）；列的歸屬與名稱取自 `gl_account_meta.fs_line` × `gl_fs_lines`。
- 資產負債表：`include_closing=True`（結轉傳票搬到 3353／3351 後，損益科目歸零、保留盈餘含已結轉數）；尚未結轉的本年度損益與
  以前年度損益列在權益下，使「資產＝負債＋權益」在結轉前後都成立。任何一個有餘額卻沒有報表列的科目都列入 `unmapped`（報表不平衡的
  第一嫌疑），不會被悄悄吸收。
- 綜合損益表：`include_closing=False`（結轉傳票不進損益表）；本期與年初至今兩欄；計算列（毛利、營業淨利…）由前列相加減。
"""
from modules.accounting.ledger import fs_lines as _fs
from modules.accounting.ledger import reports as _reports
from modules.accounting.ledger import roles as _roles

PL_TYPES = _roles.PL_TYPES


def _lines(conn, statement):
    _roles.ensure_meta(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM gl_fs_lines WHERE statement=? AND is_active=1 ORDER BY sort, code", (statement,))]


def _meta(conn):
    return {r["code"]: dict(r) for r in conn.execute("SELECT code, acct_type, fs_line FROM gl_account_meta")}


def _net(row, side):
    """科目在期末的淨額，依呈現方向取正：D＝借−貸、C＝貸−借。"""
    d = row["closing_debit"] - row["closing_credit"]
    return d if side == "D" else -d


def balance_sheet(conn, as_of, include_drafts=False, show_zero=False):
    """資產負債表（截至 as_of，含當日）。回 `{sections, totals, checks, unmapped, ...}`。"""
    fy_start = _reports._fy_start(conn, as_of)
    tb = _reports.trial_balance(conn, fy_start, as_of, include_drafts=include_drafts, include_closing=True, include_zero=True)
    meta = _meta(conn)
    lines = _lines(conn, "BS")
    by_line, unmapped = {}, []
    cur_pl = 0                       # 本年度尚未結轉的損益（貸方為正＝獲利）
    cur_oci = 0                      # 其中屬其他綜合損益者（權益變動表歸其他權益欄）
    prior_pl = 0                     # 以前年度尚未結轉的損益
    equity_lines = {}                # 權益各列的貸方淨額（貸方為正；庫藏股為負）——權益變動表用
    for r in tb["rows"]:
        if not r["code"]:            # 以前年度損益（尚未結轉）補列
            prior_pl = -(r["closing_debit"] - r["closing_credit"])
            continue
        m = meta.get(r["code"]) or {}
        if m.get("acct_type") in PL_TYPES:
            cur_pl += r["closing_credit"] - r["closing_debit"]
            if m.get("acct_type") == "oci":
                cur_oci += r["closing_credit"] - r["closing_debit"]
            continue
        net = r["closing_debit"] - r["closing_credit"]
        if (m.get("fs_line") or "").startswith("BS_EQ_"):
            equity_lines[m["fs_line"]] = equity_lines.get(m["fs_line"], 0) - net
        if net == 0 and not show_zero:
            continue
        fs = m.get("fs_line") or ""
        if not fs or not any(l["code"] == fs for l in lines):
            if net:
                unmapped.append({"code": r["code"], "name": r["name"], "net": net})
            continue
        by_line.setdefault(fs, []).append(r)

    def section(prefix_list, title):
        items, total = [], 0
        for l in lines:
            if not any(l["code"].startswith(p) for p in prefix_list):
                continue
            accts = by_line.get(l["code"], [])
            amt = sum(_net(a, l["side"]) for a in accts)
            if amt == 0 and not show_zero:
                continue
            items.append({"code": l["code"], "label": l["label"], "amount": amt,
                          "accounts": [{"code": a["code"], "name": a["name"], "amount": _net(a, l["side"])} for a in accts]})
            total += amt
        return {"title": title, "items": items, "total": total}
    ca, nca = section(["BS_CA_"], "流動資產"), section(["BS_NCA_"], "非流動資產")
    cl, ncl = section(["BS_CL_"], "流動負債"), section(["BS_NCL"], "非流動負債")
    eq = section(["BS_EQ_"], "權益")
    extra = []
    if prior_pl:
        extra.append({"code": "", "label": "以前年度損益（尚未結轉）", "amount": prior_pl, "accounts": []})
    if cur_pl:
        extra.append({"code": "", "label": "本期損益（尚未結轉）", "amount": cur_pl, "accounts": []})
    eq["items"] += extra
    eq["total"] += sum(e["amount"] for e in extra)
    assets, liabilities, equity = ca["total"] + nca["total"], cl["total"] + ncl["total"], eq["total"]
    diff = assets - liabilities - equity
    return {
        "as_of": as_of, "include_drafts": include_drafts,
        "sections": {"current_assets": ca, "noncurrent_assets": nca, "current_liabilities": cl,
                     "noncurrent_liabilities": ncl, "equity": eq},
        "totals": {"assets": assets, "liabilities": liabilities, "equity": equity, "liabilities_and_equity": liabilities + equity},
        "current_pl": cur_pl, "current_oci": cur_oci, "prior_pl": prior_pl, "equity_lines": equity_lines, "unmapped": unmapped,
        "checks": {"balanced": diff == 0 and tb["balanced"] and not unmapped, "diff": diff, "trial_balance_balanced": tb["balanced"]},
    }


def income_statement(conn, start, end, include_drafts=False, show_zero=False):
    """綜合損益表：期間 start～end（不可跨會計年度）；`period` 為本期、`ytd` 為年初至 end。"""
    tb = _reports.trial_balance(conn, start, end, include_drafts=include_drafts, include_closing=False, include_zero=True)
    meta = _meta(conn)
    lines = _lines(conn, "IS")
    period, ytd, accounts = {}, {}, {}
    unmapped = []
    for r in tb["rows"]:
        if not r["code"]:
            continue
        m = meta.get(r["code"]) or {}
        if m.get("acct_type") not in PL_TYPES:
            continue
        p_net = r["period_credit"] - r["period_debit"]                       # 貸方為正
        y_net = -(r["closing_debit"] - r["closing_credit"])
        if p_net == 0 and y_net == 0:
            continue
        fs = m.get("fs_line") or ""
        if not fs or not any(l["code"] == fs for l in lines):
            unmapped.append({"code": r["code"], "name": r["name"], "period": p_net, "ytd": y_net})
            continue
        period[fs] = period.get(fs, 0) + p_net
        ytd[fs] = ytd.get(fs, 0) + y_net
        accounts.setdefault(fs, []).append({"code": r["code"], "name": r["name"], "period": p_net, "ytd": y_net})

    def val(d, code, side):
        v = d.get(code, 0)
        return v if side == "C" else -v          # 費用／成本／減項以正數呈現（借方為正）

    def compute(d):
        g = lambda c: val(d, c, next(l["side"] for l in lines if l["code"] == c))
        rev, allow, cost = g("IS_REV"), g("IS_REV_ALLOW"), g("IS_COST")
        gp = rev - allow - cost
        op = gp - g("IS_OPEX")
        pbt = op + g("IS_NONOP_INC") - g("IS_NONOP_EXP")
        ni = pbt - g("IS_TAX") + g("IS_DISCONT")
        return {"IS_GP": gp, "IS_OP": op, "IS_PBT": pbt, "IS_NI": ni, "IS_TCI": ni + g("IS_OCI")}
    cp, cy = compute(period), compute(ytd)
    out = []
    for l in lines:
        if l["kind"] == "computed":
            a, y = cp[l["code"]], cy[l["code"]]
        else:
            a, y = val(period, l["code"], l["side"]), val(ytd, l["code"], l["side"])
        if l["kind"] == "line" and a == 0 and y == 0 and not show_zero:
            continue
        out.append({"code": l["code"], "label": l["label"], "kind": l["kind"], "period": a, "ytd": y,
                    "accounts": [{"code": x["code"], "name": x["name"], "period": val({"_": x["period"]}, "_", l["side"]),
                                  "ytd": val({"_": x["ytd"]}, "_", l["side"])} for x in accounts.get(l["code"], [])]})
    pl_ytd_all = sum(ytd.values()) + sum(u["ytd"] for u in unmapped)          # 試算表損益類淨額（貸方為正）
    ni_ok = cy["IS_TCI"] == pl_ytd_all
    return {"start": start, "end": end, "include_drafts": include_drafts, "lines": out,
            "net_income": {"period": cp["IS_NI"], "ytd": cy["IS_NI"], "tci_period": cp["IS_TCI"], "tci_ytd": cy["IS_TCI"]},
            "unmapped": unmapped,
            "checks": {"ni_equals_trial_balance": ni_ok, "trial_balance_balanced": tb["balanced"],
                       "balanced": ni_ok and tb["balanced"] and not unmapped}}


def check_consistency(conn, as_of, include_drafts=False):
    """兩張表互相對帳（同一日期、同一會計年度）：
    ①資產負債表平衡 ②損益表淨利等於試算表損益類淨額 ③資產負債表的「本期損益（尚未結轉）」＝損益表年初至今綜合損益；
    若該年度已有結轉傳票（kind='closing'），損益已搬進保留盈餘，③改為「尚未結轉＝0」。"""
    bs = balance_sheet(conn, as_of, include_drafts)
    fy = _reports._fy_start(conn, as_of)
    inc = income_statement(conn, fy, as_of, include_drafts)
    closed = conn.execute(
        "SELECT 1 FROM vouchers_all WHERE kind='closing' AND voided_at='' AND status='已過帳' AND substr(voucher_date,1,10) BETWEEN ? AND ? LIMIT 1",
        (fy, as_of)).fetchone() is not None
    expected = 0 if closed else inc["net_income"]["tci_ytd"]
    return {"bs_balanced": bs["checks"]["balanced"], "is_balanced": inc["checks"]["balanced"],
            "current_pl_matches": bs["current_pl"] == expected, "closed_in_year": closed}
