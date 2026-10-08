# -*- coding: utf-8 -*-
"""第 48 班 S5：管銷分攤改 直接毛利×pct% ——「未精算報價單」一次性重算的**凍結**邏輯（只用標準庫，不 import 任何活程式碼）。

凍結的理由（凍住的歷史不呼叫活的程式碼）：`helpers/profit_rules.py` 之後還會演進（ACTIVE_VER、預設百分比…），遷移必須永遠做
「2026-10-09 當天定義的那件事」。本檔的算式與 profit_rules ver 2 用黃金向量對拍（tests/test_overhead_recalc_t48.py）。

規則（使用者 2026-10-09 裁示，設計稿 §11）：
- 已精算／結案（`settle_status='finalized'` 或 `deal_tag='已結案'`）一律不動。
- 其餘（含草稿精算、已核准／已送出）重算：`adminCost = 四捨五入(max(directProfit,0) × pct/100)`；公益金照舊式
  `max(0, 四捨五入(directProfit × 0.01))`；其他五項間接成本（運輸物流…其他）＝舊 `totalIndirect − adminCost − charityDonation`
  （存值，不從品項重推）；`netProfit = directProfit − (新 adminCost + 公益金 + 五項)`；`netMarginPct` 一位小數。
- 內部鍵不改；新增 `overheadPct`（data_json 根與 tot）、`tot.formulaVer=2`、`tot._legacy`（舊值快照，回滾用）、`tot._recalc`（口徑更新註記）。
- 冪等：`tot.formulaVer>=2` 的單不再動。價格（pretax／total）完全不變。草稿精算的 summary 不改（精算頁載入時依規則重算）。
"""
import json
from decimal import Decimal, ROUND_HALF_UP

NEW_VER = 2
DEFAULT_PCT = "25"
TOT_KEYS = ("adminCost", "charityDonation", "totalIndirect", "netProfit", "netMarginPct")


def _dec(v) -> Decimal:
    return Decimal(str(v))


def _round(v: Decimal, places: int = 0) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def is_settled(settle_status, deal_tag) -> bool:
    return (settle_status or "") == "finalized" or (deal_tag or "") == "已結案"


def new_tot_fields(tot: dict, pct) -> dict:
    """回傳要覆寫進 tot 的四個欄位（adminCost／totalIndirect／netProfit／netMarginPct）；資料不足 ⇒ 丟 ValueError(原因)。"""
    for k in ("pretax", "directProfit", "adminCost", "totalIndirect"):
        if tot.get(k) is None:
            raise ValueError("tot 缺 %s" % k)
    pretax, direct = _dec(tot["pretax"]), _dec(tot["directProfit"])
    old_admin, old_ti = _dec(tot["adminCost"]), _dec(tot["totalIndirect"])
    old_charity = _dec(tot["charityDonation"]) if tot.get("charityDonation") is not None else Decimal(0)
    five = old_ti - old_admin - old_charity                           # 其他五項間接成本（存值）
    rate = _dec(pct).scaleb(-2)
    admin = _round(max(direct, Decimal(0)) * rate)
    charity = max(Decimal(0), _round(direct * Decimal("0.01")))
    total_indirect = admin + charity + five
    net = direct - total_indirect
    net_pct = float(_round(net / pretax * 100, 1)) if pretax > 0 else 0.0
    return {"adminCost": int(admin), "totalIndirect": _num(total_indirect), "netProfit": int(_round(net)),
            "netMarginPct": net_pct, "charityDonation": int(charity)}


def _num(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def plan(conn, pct, default_pct=None):
    """逐張報價單的處理計畫（不寫）。每筆 dict：quote_no／action（recalc|skip_settled|skip_done|skip_nodata）／原因／前後值。"""
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
        if int(tot.get("formulaVer") or 1) >= NEW_VER:
            out.append(dict(base, action="skip_done"))
            continue
        try:
            new = new_tot_fields(tot, pct)
        except (ValueError, ArithmeticError) as exc:
            out.append(dict(base, action="skip_nodata", reason=str(exc)))
            continue
        out.append(dict(base, action="recalc", old={k: tot.get(k) for k in TOT_KEYS}, new=new, old_col=r["net_margin_pct"],
                        pretax=tot.get("pretax")))
    return out


def apply_plan(conn, items, pct, stamp, who="t48-overhead-migrate"):
    """把 plan() 裡 action=recalc 的寫進去（呼叫端負責交易）。回寫入張數。"""
    n = 0
    for it in items:
        if it["action"] != "recalc":
            continue
        row = conn.execute("SELECT data_json FROM quotations WHERE id=?", (it["id"],)).fetchone()
        d = json.loads(row["data_json"])
        tot = d["tot"]
        if int(tot.get("formulaVer") or 1) >= NEW_VER:
            continue                                                   # 計畫與寫入之間被改過（冪等）
        tot["_legacy"] = {k: tot.get(k) for k in TOT_KEYS}
        tot["_legacy"].update(formulaVer=tot.get("formulaVer"), netMarginPctCol=it["old_col"], had_overheadPct=("overheadPct" in d))
        for k in TOT_KEYS:
            tot[k] = it["new"][k]
        tot["formulaVer"] = NEW_VER
        tot["overheadPct"] = float(_dec(pct)) if _dec(pct) % 1 else int(_dec(pct))
        tot["_recalc"] = {"at": stamp, "by": who, "note": "口徑更新：管銷分攤改為直接毛利×%s%%" % pct}
        d["overheadPct"] = tot["overheadPct"]
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), it["new"]["netMarginPct"], it["id"]))
        n += 1
    return n


def plan_rollback(conn):
    out = []
    for r in conn.execute("SELECT id, quote_no, settle_status, deal_tag, data_json FROM quotations ORDER BY id"):
        try:
            d = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            continue
        tot = d.get("tot") if isinstance(d, dict) and isinstance(d.get("tot"), dict) else None
        if not tot or "_legacy" not in tot or int(tot.get("formulaVer") or 1) < NEW_VER:
            continue
        base = {"id": r["id"], "quote_no": r["quote_no"]}
        if is_settled(r["settle_status"], r["deal_tag"]):
            out.append(dict(base, action="skip_settled_since", reason="遷移後已完結／結案，不自動還原（完結值已是新口徑）"))
        else:
            out.append(dict(base, action="restore", old=tot["_legacy"], now={k: tot.get(k) for k in TOT_KEYS}))
    return out


def apply_rollback(conn, items):
    n = 0
    for it in items:
        if it["action"] != "restore":
            continue
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE id=?", (it["id"],)).fetchone()["data_json"])
        tot = d["tot"]
        leg = tot.pop("_legacy")
        for k in TOT_KEYS:
            if leg.get(k) is None:
                tot.pop(k, None)
            else:
                tot[k] = leg[k]
        if leg.get("formulaVer") is None:
            tot.pop("formulaVer", None)
        else:
            tot["formulaVer"] = leg["formulaVer"]
        tot.pop("overheadPct", None)
        tot.pop("_recalc", None)
        if not leg.get("had_overheadPct"):
            d.pop("overheadPct", None)
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), leg.get("netMarginPctCol") if leg.get("netMarginPctCol") is not None else 0, it["id"]))
        n += 1
    return n
