# -*- coding: utf-8 -*-
"""第 52 班：公益捐款改 報價含稅金額×1% —— 「未精算且已是新管銷口徑（formulaVer 2）的報價單」一次性重算的**凍結**邏輯（只用標準庫，不 import 任何活程式碼）。

凍結的理由同 t48：遷移必須永遠做「2026-10-10 當天定義的那件事」；本檔算式與 profit_rules（公益基數 total）用黃金向量＋隨機種子的『線上 vs 凍結』等值測試對拍
（tests/test_charity_recalc_t52.py）。

規則（使用者 2026-10-10 裁示，設計稿 docs/platform/plans/CHARITY-QUOTE-1PCT-DESIGN-T52.md）：
- 已精算／結案（`settle_status='finalized'` 或 `deal_tag='已結案'`）一律不動。
- 只處理 `tot.formulaVer == 2` 且尚未帶 `tot.charityBasis` 的單；formulaVer < 2 的未結案單 ⇒ `skip_not_v2`（要先做管銷口徑遷移）；已是 total ⇒ `skip_done`。
- 公益捐款 `charityDonation = max(0, 四捨五入(tot.total × 0.01))`（以含稅金額為基；**不看直接毛利、虧損案照扣**；下限 0 只設在含稅金額上）。
  管銷分攤沿用存值 `tot.adminCost`（不重算、比率不動）；`totalIndirect = adminCost + charityDonation`（新口徑不計五項間接成本）；
  `netProfit`／`netMarginPct` 走『線上程式』的雙精度算法：`net_f = float(directProfit) − float(totalIndirect)`；率 ＝ 四捨五入(net_f/pretax×100, 1 位)，與
  `profit_rules.quote_profit` ＋ `profit_guard.server_profit` 逐位相同（含 .x5 平手；第 50 班稽核教訓）。
- 新增戳記：`tot.charityBasis="total"`、`tot._legacyCharity`（遷移前的 charityDonation／totalIndirect／netProfit／netMarginPct／_recalc／欄位 net_margin_pct，回滾依據）、
  `tot._recalc`（口徑更新註記，沿用 t48 的位置）。表單重存會重建 tot 丟掉 `_legacyCharity`，所以舊值**另外**存在
  `system_settings.charity_legacy_snapshot`（含當時寫入值）。價格（pretax／tax／total）完全不變；不碰草稿精算 summary。
- 寫入一律**在 BEGIN IMMEDIATE 之後重讀、重檢查已精算／結案、重算**（不採用較早算出的計畫值）。
"""
import json
from decimal import Decimal, ROUND_HALF_UP

BASIS = "total"
TOT_KEYS = ("charityDonation", "totalIndirect", "netProfit", "netMarginPct")
SNAPSHOT_KEY = "charity_legacy_snapshot"
NEED = ("pretax", "directProfit", "adminCost", "totalIndirect", "total")


def _dec(v) -> Decimal:
    return Decimal(str(v))


def _round(v: Decimal, places: int = 0) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _num(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def is_settled(settle_status, deal_tag) -> bool:
    return (settle_status or "") == "finalized" or (deal_tag or "") == "已結案"


def new_tot_fields(tot: dict) -> dict:
    """要覆寫進 tot 的欄位；資料不足或不一致 ⇒ ValueError(原因)。"""
    for k in NEED:
        if tot.get(k) is None or isinstance(tot.get(k), bool):
            raise ValueError("tot 缺 %s" % k)
    pretax, direct, total = _dec(tot["pretax"]), _dec(tot["directProfit"]), _dec(tot["total"])
    admin = _dec(tot["adminCost"])
    charity = max(Decimal(0), _round(total * Decimal("0.01")))
    total_indirect = admin + charity
    net_f = float(direct) - float(total_indirect)
    net = _dec(net_f)
    net_pct = (int(_round(_dec(net_f / float(pretax) * 100) * 10)) / 10) if pretax > 0 else 0.0
    return {"charityDonation": int(charity), "totalIndirect": _num(total_indirect), "netProfit": int(_round(net)), "netMarginPct": net_pct}


def plan(conn):
    """逐張處理計畫（不寫）：action ＝ recalc｜skip_settled｜skip_done｜skip_not_v2｜skip_nodata。"""
    out = []
    for r in conn.execute("SELECT id, quote_no, settle_status, deal_tag, data_json, net_margin_pct FROM quotations ORDER BY id"):
        base = {"id": r["id"], "quote_no": r["quote_no"], "settle_status": r["settle_status"] or "", "deal_tag": r["deal_tag"] or ""}
        if is_settled(r["settle_status"], r["deal_tag"]):
            out.append(dict(base, action="skip_settled"))
            continue
        try:
            d = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            out.append(dict(base, action="skip_nodata", reason="data_json 不是 JSON"))
            continue
        tot = d.get("tot") if isinstance(d, dict) and isinstance(d.get("tot"), dict) else None
        if tot is None:
            out.append(dict(base, action="skip_nodata", reason="沒有 tot"))
            continue
        if int(tot.get("formulaVer") or 1) < 2:
            out.append(dict(base, action="skip_not_v2", reason="尚未是新管銷口徑（formulaVer<2）"))
            continue
        if tot.get("charityBasis") == BASIS:
            out.append(dict(base, action="skip_done"))
            continue
        try:
            new = new_tot_fields(tot)
        except (ValueError, ArithmeticError) as exc:
            out.append(dict(base, action="skip_nodata", reason=str(exc)))
            continue
        out.append(dict(base, action="recalc", old={k: tot.get(k) for k in TOT_KEYS}, new=new, old_col=r["net_margin_pct"],
                        pretax=tot.get("pretax"), total=tot.get("total"), direct=tot.get("directProfit")))
    return out


def apply_plan(conn, items, stamp, snapshot=None, who="t52-charity-migrate"):
    """把 plan() 裡 action=recalc 的寫進去（呼叫端已在 BEGIN IMMEDIATE 內）。不採用計畫裡的算值：逐張重讀、再檢查已精算／結案、用當下的 tot 重算。
    回傳 (寫入張數, 期間已精算而略過張數)。"""
    n = skipped = 0
    for it in items:
        if it["action"] != "recalc":
            continue
        row = conn.execute("SELECT settle_status, deal_tag, data_json, net_margin_pct FROM quotations WHERE id=?", (it["id"],)).fetchone()
        if row is None:
            continue
        if is_settled(row["settle_status"], row["deal_tag"]):
            skipped += 1
            continue
        d = json.loads(row["data_json"])
        tot = d.get("tot") if isinstance(d.get("tot"), dict) else None
        if tot is None or int(tot.get("formulaVer") or 1) < 2 or tot.get("charityBasis") == BASIS:
            continue
        try:
            new = new_tot_fields(tot)
        except (ValueError, ArithmeticError):
            continue
        legacy = {k: tot.get(k) for k in TOT_KEYS}
        legacy.update(netMarginPctCol=row["net_margin_pct"], had_recalc=("_recalc" in tot), _recalc=tot.get("_recalc"))
        tot["_legacyCharity"] = legacy
        for k in TOT_KEYS:
            tot[k] = new[k]
        tot["charityBasis"] = BASIS
        tot["_recalc"] = {"at": stamp, "by": who, "note": "口徑更新：公益捐款改為報價含稅金額×1%"}
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), new["netMarginPct"], it["id"]))
        if snapshot is not None:
            snapshot[it["quote_no"]] = {"legacy": legacy, "written": {k: new[k] for k in TOT_KEYS}}
        n += 1
    return n, skipped


def plan_rollback(conn, snapshot=None):
    """可還原清單。來源：tot._legacyCharity，或伺服器端 snapshot（表單重存會丟掉 tot._legacyCharity）。
    不還原：遷移後已完結／結案（skip_settled_since）、遷移後又被編輯過（skip_edited_since）、已不是 total 基數（skip_not_total）。"""
    snapshot = snapshot or {}
    out = []
    for r in conn.execute("SELECT id, quote_no, settle_status, deal_tag, data_json FROM quotations ORDER BY id"):
        try:
            d = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            continue
        tot = d.get("tot") if isinstance(d, dict) and isinstance(d.get("tot"), dict) else None
        snap = snapshot.get(r["quote_no"])
        if not tot or ("_legacyCharity" not in tot and snap is None):
            continue
        base = {"id": r["id"], "quote_no": r["quote_no"]}
        legacy = tot.get("_legacyCharity") or (snap or {}).get("legacy")
        written = (snap or {}).get("written")
        if tot.get("charityBasis") != BASIS:
            out.append(dict(base, action="skip_not_total", reason="已不是含稅 1% 基數（舊式表單重存？）"))
        elif is_settled(r["settle_status"], r["deal_tag"]):
            out.append(dict(base, action="skip_settled_since", reason="遷移後已完結／結案，不自動還原（完結值已是新基數）"))
        elif written is not None and any(tot.get(k) != written[k] for k in TOT_KEYS):
            out.append(dict(base, action="skip_edited_since", reason="遷移後又被編輯過，不覆蓋"))
        elif legacy is None:
            out.append(dict(base, action="skip_not_restorable", reason="找不到舊值快照"))
        else:
            out.append(dict(base, action="restore", old=legacy, now={k: tot.get(k) for k in TOT_KEYS}))
    return out


def apply_rollback(conn, items, snapshot=None):
    """呼叫端已在 BEGIN IMMEDIATE 內；逐張重讀並再檢查已精算／結案。回還原張數。"""
    n = 0
    for it in items:
        if it["action"] != "restore":
            continue
        row = conn.execute("SELECT quote_no, settle_status, deal_tag, data_json FROM quotations WHERE id=?", (it["id"],)).fetchone()
        if row is None or is_settled(row["settle_status"], row["deal_tag"]):
            continue
        d = json.loads(row["data_json"])
        tot = d["tot"]
        leg = it["old"]
        tot.pop("_legacyCharity", None)
        for k in TOT_KEYS:
            if leg.get(k) is None:
                tot.pop(k, None)
            else:
                tot[k] = leg[k]
        tot.pop("charityBasis", None)
        if leg.get("had_recalc"):
            tot["_recalc"] = leg.get("_recalc")
        else:
            tot.pop("_recalc", None)
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), leg.get("netMarginPctCol") if leg.get("netMarginPctCol") is not None else 0, it["id"]))
        if snapshot is not None:
            snapshot.pop(row["quote_no"], None)
        n += 1
    return n
