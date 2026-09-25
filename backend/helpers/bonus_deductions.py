# -*- coding: utf-8 -*-
"""U4：獎金分潤撥付時的扣繳與二代健保補充保費（CORE-SPEC「使用者裁示」U4，2026-09-25）。

```
扣繳       每人每次給付額 ≥ 起扣標準 ⇒ 給付額 × 扣繳率（元以下捨去，同勞報單）；未達 ⇒ 0
補充保費   全年累計獎金超過「投保金額 × 倍數」的部分 × 費率（單次上限 max_single_payment）
           本次計費基數 = max(0, 累計前 + 本次 − max(門檻, 累計前))；四捨五入到元
```
- **門檻與費率不寫死**：純函式一律由呼叫端傳入 `params`；撥付時讀 L1 法規參數服務
  `helpers.legal_params`（R1，INTEGRATION-POINTS IP-7）依撥付日選版，`params_from_legal_version()` 轉換。
  沒有適用版本或欄位不齊 ⇒ `legal_params_for()` 回 `(None, 原因)`，呼叫端**拒絕撥付**（不以 0 或預設值代替）。
- 單據（`mark_paid` 那一筆編寫紀錄）存當次使用的 `version` 與參數快照。
- **同一人在同一張單出現在多個類別 ⇒ 先合併再算**（起扣標準是「每次給付」）。
- **投保金額沒有設定 ⇒ 不猜**：`missing` 列出來，呼叫端拒絕撥付（不以 0 計算）。
- 投保金額與「MOTRIX 以外發放的全年累計」存在 `system_settings`（`PROFILE_KEY`）。
  ⚠️ 不新增資料表：模組 migration 的執行器還沒有（MODULE-GUIDE §4），V9 基準 v116 凍結。
"""
import json
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from helpers import legal_params as lp

#: 設定鍵：{username: {"insuredAmount": int, "ytdExternal": {"2026": int}}}
PROFILE_KEY = "payroll_insurance_profiles"

#: `params` 必須有的鍵（缺一個就不算）
PARAM_KEYS = ("withholding_rate", "withholding_threshold", "nhi_rate",
              "nhi_bonus_multiple", "nhi_max_single_payment")



class DeductionParamsError(ValueError):
    """參數不齊或不合法（不猜）。"""


def _dec(x):
    return Decimal(str(x))


def _check_params(params):
    if not isinstance(params, dict):
        raise DeductionParamsError("法規參數必須是物件")
    missing = [k for k in PARAM_KEYS if params.get(k) is None]
    if missing:
        raise DeductionParamsError("法規參數缺少：%s" % "、".join(missing))
    for k in PARAM_KEYS:
        v = params[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise DeductionParamsError("法規參數 %s 不合法：%r" % (k, v))
    if params["withholding_rate"] > 1 or params["nhi_rate"] > 1:
        raise DeductionParamsError("費率必須介於 0 與 1 之間")


def withholding_of(gross, params):
    """一人一次給付的扣繳稅額。未達起扣標準 ⇒ 0；否則 給付額 × 稅率，元以下捨去（同勞報單 `math.floor`）。"""
    if gross < params["withholding_threshold"]:
        return 0
    return int((_dec(gross) * _dec(params["withholding_rate"])).to_integral_value(ROUND_FLOOR))


def nhi_base_of(gross, ytd_before, insured, params):
    """本次給付中要計收補充保費的部分。門檻＝投保金額 × 倍數（全年累計）。"""
    cap = _dec(insured) * _dec(params["nhi_bonus_multiple"])
    before = _dec(ytd_before)
    base = before + _dec(gross) - max(cap, before)
    if base <= 0:
        return 0
    return int(min(base, _dec(params["nhi_max_single_payment"])))


def nhi_premium_of(base, params):
    """補充保費＝基數 × 費率，四捨五入到元（ROADMAP R9：官方捨位規則查到前，統一用 round_half_up）。"""
    return int((_dec(base) * _dec(params["nhi_rate"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_bonus_deductions(lines, *, params, insured, ytd_before):
    """純函式（不碰資料庫）。

    lines       [{username, amount, display_name_snapshot?}]（同一人可多列，會先合併）
    params      見 `PARAM_KEYS`（另可帶 `version` 顯示用）
    insured     {username: 投保金額}；沒有或不是正整數 ⇒ 列入 `missing`
    ytd_before  {username: 本次之前的全年累計獎金}

    回 {"version", "params"（快照）, "lines": [{username, displayName, gross, withholding, nhiBase, nhiPremium, net,
         insuredAmount, ytdBefore, ytdAfter}], "totals": {gross, withholding, nhiPremium, net}, "missing": [username]}
    `missing` 非空時該人的扣繳與保費**不計算**（值為 None），呼叫端必須拒絕撥付。
    """
    _check_params(params)
    merged, names = {}, {}
    for ln in lines or ():
        u = ln["username"]
        merged[u] = merged.get(u, 0) + int(ln["amount"])
        names.setdefault(u, ln.get("display_name_snapshot") or u)
    out, missing = [], []
    tot = {"gross": 0, "withholding": 0, "nhiPremium": 0, "net": 0}
    for u, gross in merged.items():
        ins = (insured or {}).get(u)
        before = int((ytd_before or {}).get(u) or 0)
        row = {"username": u, "displayName": names[u], "gross": gross, "insuredAmount": ins,
               "ytdBefore": before, "ytdAfter": before + gross}
        if isinstance(ins, bool) or not isinstance(ins, int) or ins <= 0:
            missing.append(u)
            row.update(withholding=None, nhiBase=None, nhiPremium=None, net=None)
        else:
            w = withholding_of(gross, params)
            base = nhi_base_of(gross, before, ins, params)
            p = nhi_premium_of(base, params)
            row.update(withholding=w, nhiBase=base, nhiPremium=p, net=gross - w - p)
            tot["withholding"] += w
            tot["nhiPremium"] += p
        tot["gross"] += gross
        out.append(row)
    tot["net"] = tot["gross"] - tot["withholding"] - tot["nhiPremium"]
    # 單據存當次使用的版本＋參數快照（R1 規則：舊單沿用建立時的版本）
    return {"version": params.get("version", ""), "params": {k: params[k] for k in PARAM_KEYS},
            "lines": out, "totals": tot, "missing": missing}


def params_from_legal_version(v):
    """R1 法規參數的一版（`helpers.legal_params` 的形狀）→ 本檔的 `params`。

    扣繳用 `resident["50"]`（非每月給付之薪資：5%，起扣標準）；補充保費用 `nhi.rate`、
    `nhi.max_single_payment`，倍數讀 `nhi.bonus_insured_multiple`（R1 目前沒有這個欄位 ⇒ 缺，不猜 4）。
    缺任何一個 ⇒ DeductionParamsError（說明缺哪一個）。"""
    try:
        res = v["resident"]["50"]
        nhi = v["nhi"]
    except (KeyError, TypeError):
        raise DeductionParamsError("法規參數版本缺少 resident.50 或 nhi")
    params = {
        "version": v.get("version", ""),
        "withholding_rate": res.get("tax_rate"),
        "withholding_threshold": res.get("tax_threshold"),
        "nhi_rate": nhi.get("rate"),
        "nhi_bonus_multiple": nhi.get("bonus_insured_multiple"),
        "nhi_max_single_payment": nhi.get("max_single_payment"),
    }
    _check_params(params)
    return params


def legal_params_for(on_date):
    """撥付日適用的參數（IP-7：`lp.rules_for_date(lp.load_versions(), 日期)`）。回 `(params, rules, "")`；
    沒有適用版本（`lp.NoApplicableRules`）或欄位不齊（`DeductionParamsError`）⇒ `(None, None, 具體原因)`。
    `rules` 是那一版的完整內容（IP-7「單據凍結」：存 version 與整份 rules 快照）。"""
    try:
        rules = lp.rules_for_date(lp.load_versions(), on_date)
        return params_from_legal_version(rules), rules, ""
    except (lp.NoApplicableRules, DeductionParamsError) as e:
        return None, None, "無法計算扣繳與補充保費：%s" % e


# ── 投保金額與全年累計（system_settings）────────────────────────────────────

def load_profiles(conn):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key = ?", (PROFILE_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        v = json.loads(row["value_json"])
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def insured_amounts(profiles):
    """{username: 投保金額}（沒有設定的人不在裡面 ⇒ 計算時列入 missing）。"""
    return {u: p.get("insuredAmount") for u, p in profiles.items()
            if isinstance(p, dict) and p.get("insuredAmount") is not None}


def ytd_external(profiles, year):
    """MOTRIX 以外（例如年終由薪資系統發）已發的獎金，全年累計要加進去。"""
    out = {}
    for u, p in profiles.items():
        v = ((p or {}).get("ytdExternal") or {}).get(str(year))
        if isinstance(v, int) and not isinstance(v, bool):
            out[u] = v
    return out


def ytd_in_motrix(conn, year, *, exclude_award_id=None):
    """同一年度（發放日）已發放的獎金分潤合計（每人）。"""
    sql = ("SELECT l.username, COALESCE(SUM(l.amount), 0) AS s FROM bonus_case_award_lines l"
           " JOIN bonus_case_awards a ON a.id = l.award_id"
           " WHERE a.status = '已發放' AND substr(a.paid_at, 1, 4) = ?")
    args = [str(year)]
    if exclude_award_id is not None:
        sql += " AND a.id != ?"
        args.append(exclude_award_id)
    sql += " GROUP BY l.username"
    return {r["username"]: int(r["s"] or 0) for r in conn.execute(sql, args)}


def ytd_before(conn, profiles, year, award_id):
    motrix = ytd_in_motrix(conn, year, exclude_award_id=award_id)
    ext = ytd_external(profiles, year)
    return {u: motrix.get(u, 0) + ext.get(u, 0) for u in set(motrix) | set(ext)}


def deductions_for_award(conn, award, lines, on_date):
    """撥付日 `on_date` 的試算。回 `(result | None, notice)`；參數接不上 ⇒ `(None, 原因)`。"""
    params, rules, why = legal_params_for(on_date)
    if params is None:
        return None, why
    profiles = load_profiles(conn)
    out = compute_bonus_deductions(
        lines, params=params, insured=insured_amounts(profiles),
        ytd_before=ytd_before(conn, profiles, on_date[:4], award["id"]))
    out["rules"] = rules               # 整份法規參數快照（IP-7 單據凍結）
    return out, ""
