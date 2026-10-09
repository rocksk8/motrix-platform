# -*- coding: utf-8 -*-
"""第 48 班 S5：管銷分攤改 直接毛利×pct% ——「未精算報價單」一次性重算的**凍結**邏輯（只用標準庫，不 import 任何活程式碼）。

凍結的理由（凍住的歷史不呼叫活的程式碼）：`helpers/profit_rules.py` 之後還會演進（ACTIVE_VER、預設百分比…），遷移必須永遠做
「2026-10-09 當天定義的那件事」。本檔的算式與 profit_rules ver 2 用黃金向量對拍（tests/test_overhead_recalc_t48.py）。

規則（使用者 2026-10-09 裁示，設計稿 §11）：
- 已精算／結案（`settle_status='finalized'` 或 `deal_tag='已結案'`）一律不動。
- 其餘（含草稿精算、已核准／已送出）重算：`adminCost = 四捨五入(max(directProfit,0) × pct/100)`；公益金照舊式
  `max(0, 四捨五入(directProfit × 0.01))`；其他五項間接成本（運輸物流…其他）＝舊 `totalIndirect − adminCost − charityDonation`
  （存值，不從品項重推）；`netProfit = directProfit − (新 adminCost + 公益金 + 五項)`；`netMarginPct` 一位小數。
- **每張單用自己存的百分比**（data_json.overheadPct，再 tot.overheadPct；superadmin 在 legacy 模式下可能已設過），沒有才用預設。
- 內部鍵不改；新增 `overheadPct`（data_json 根與 tot）、`tot.formulaVer=2`、`tot._legacy`（舊值快照）、`tot._recalc`（口徑更新註記）。
  表單重存會重建 tot、丟掉 `_legacy`，所以舊值**另外**存在伺服器端 `system_settings.overhead_legacy_snapshot`（含當時寫入值，回滾用）。
- 冪等：`tot.formulaVer>=2` 的單不再動。價格（pretax／total）完全不變。草稿精算的 summary 不改（精算頁載入時依規則重算）。
- 寫入一律**在 BEGIN IMMEDIATE 之後重讀、重檢查已精算／結案、重算**（不採用較早算出的計畫值）。
"""
import json
import re
from decimal import Decimal, ROUND_HALF_UP

NEW_VER = 2
DEFAULT_PCT = "25"
TOT_KEYS = ("adminCost", "charityDonation", "totalIndirect", "netProfit", "netMarginPct")
SNAPSHOT_KEY = "overhead_legacy_snapshot"


def _dec(v) -> Decimal:
    return Decimal(str(v))


def _round(v: Decimal, places: int = 0) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _num(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def is_settled(settle_status, deal_tag) -> bool:
    return (settle_status or "") == "finalized" or (deal_tag or "") == "已結案"


def valid_pct(v):
    """0–100、最多 1 位小數；合法回 Decimal，否則 None。"""
    if isinstance(v, bool) or not re.fullmatch(r"\d{1,3}(\.\d)?", str(v).strip()):
        return None
    d = _dec(str(v).strip())
    return d if d <= 100 else None


def quote_pct(d, tot, default_pct) -> str:
    """這張單該用的百分比：自己存的優先（根再 tot），沒有或不合法才用預設。"""
    for v in ((d or {}).get("overheadPct"), (tot or {}).get("overheadPct")):
        if v is not None:
            ok = valid_pct(v)
            if ok is not None:
                return format(ok, "f")
    return str(default_pct)


def new_tot_fields(tot: dict, pct) -> dict:
    """回傳要覆寫進 tot 的欄位；資料不足或不一致 ⇒ 丟 ValueError(原因)。"""
    for k in ("pretax", "directProfit", "adminCost", "totalIndirect"):
        if tot.get(k) is None:
            raise ValueError("tot 缺 %s" % k)
    pretax, direct = _dec(tot["pretax"]), _dec(tot["directProfit"])
    old_admin, old_ti = _dec(tot["adminCost"]), _dec(tot["totalIndirect"])
    old_charity = _dec(tot["charityDonation"]) if tot.get("charityDonation") is not None else Decimal(0)
    five = old_ti - old_admin - old_charity                           # 其他五項間接成本（存值）
    if five < 0:
        raise ValueError("tot 不一致（totalIndirect < 管銷＋公益）")
    rate = _dec(pct).scaleb(-2)
    admin = _round(max(direct, Decimal(0)) * rate)
    charity = max(Decimal(0), _round(direct * Decimal("0.01")))
    total_indirect = admin + charity                                  # 新口徑不再計入五項間接成本（舊值留在 tot._legacy／data_json，供回滾與稽核）
    # 營業利益與營業利益率：照「線上程式」的二進位浮點算法（profit_rules.quote_profit 的雙精度減法／除法，再以最短表示的
    # 十進位字串四捨五入——helpers.legal_params.round_half_up(x, 10)/10；伺服器重存、前端顯示都是這個值）。
    # 🔴 第 50 班稽核：以前這裡用精確 Decimal 比值，於「剛好 .x5」的平手差 0.1 個百分點（pretax 2000／成本 895／7.5% ⇒ 精確 48.45 → 48.5，
    # 線上浮點 48.449999999999996 → 48.4）⇒ 遷移寫的值與該單第一次重存的值不同。這裡只用標準庫重寫同一算法，不 import 線上程式。
    net_f = float(direct) - float(total_indirect)
    net = _dec(net_f)
    net_pct = (int(_round(_dec(net_f / float(pretax) * 100) * 10)) / 10) if pretax > 0 else 0.0
    return {"adminCost": int(admin), "totalIndirect": _num(total_indirect), "netProfit": int(_round(net)),
            "netMarginPct": net_pct, "charityDonation": int(charity), "legacyIndirect": _num(five)}


def _numpct(p):
    p = _dec(p)
    return float(p) if p % 1 else int(p)


def plan(conn, default_pct):
    """逐張報價單的處理計畫（不寫）。每筆 dict：quote_no／action（recalc|skip_settled|skip_done|skip_nodata）／原因／前後值。
    ⚠️ 要寫的時候必須在 BEGIN IMMEDIATE 之內重新呼叫（或直接呼叫 apply_plan：它逐張重讀、重檢查、重算）。"""
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
        pct = quote_pct(d, tot, default_pct)
        try:
            new = new_tot_fields(tot, pct)
        except (ValueError, ArithmeticError) as exc:
            out.append(dict(base, action="skip_nodata", reason=str(exc)))
            continue
        out.append(dict(base, action="recalc", old={k: tot.get(k) for k in TOT_KEYS}, new=new, old_col=r["net_margin_pct"],
                        pretax=tot.get("pretax"), pct=pct, legacy_indirect=new.get("legacyIndirect") or 0))
    return out


def apply_plan(conn, items, default_pct, stamp, snapshot=None, who="t48-overhead-migrate"):
    """把 plan() 裡 action=recalc 的寫進去（呼叫端已在 BEGIN IMMEDIATE 內）。**不採用計畫裡的算值**：逐張重讀、
    再檢查已精算／結案、用當下的 tot 與該單自己的百分比重算——計畫與寫入之間有人存檔或完結，都不會被舊值蓋掉。
    snapshot：dict，寫入 {quote_no: {legacy, written}}（呼叫端存進 system_settings）。回傳 (寫入張數, 期間已精算而略過張數)。"""
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
        if tot is None or int(tot.get("formulaVer") or 1) >= NEW_VER:
            continue
        pct = quote_pct(d, tot, default_pct)
        try:
            new = new_tot_fields(tot, pct)
        except (ValueError, ArithmeticError):
            continue
        legacy = {k: tot.get(k) for k in TOT_KEYS}
        legacy.update(formulaVer=tot.get("formulaVer"), netMarginPctCol=row["net_margin_pct"], had_overheadPct=("overheadPct" in d), tot_overheadPct=tot.get("overheadPct"))
        tot["_legacy"] = legacy
        for k in TOT_KEYS:
            tot[k] = new[k]
        tot["formulaVer"] = NEW_VER
        tot["overheadPct"] = _numpct(pct)
        tot["_recalc"] = {"at": stamp, "by": who, "note": "口徑更新：管銷分攤改為直接毛利×%s%%" % pct}
        d["overheadPct"] = tot["overheadPct"]
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), new["netMarginPct"], it["id"]))
        if snapshot is not None:
            snapshot[it["quote_no"]] = {"legacy": legacy, "written": {k: new[k] for k in TOT_KEYS}}
        n += 1
    return n, skipped


def plan_rollback(conn, snapshot=None):
    """可還原清單。來源：tot._legacy，或伺服器端 snapshot（表單重存會丟掉 tot._legacy）。
    不還原：遷移後已完結／結案（skip_settled_since）、遷移後又被編輯過（skip_edited_since：目前值 ≠ 當時寫入值）、
    已不是新口徑（skip_not_v2：例如 legacy 模式的表單重存已退回 10% 基準）。"""
    snapshot = snapshot or {}
    out = []
    for r in conn.execute("SELECT id, quote_no, settle_status, deal_tag, data_json FROM quotations ORDER BY id"):
        try:
            d = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            continue
        tot = d.get("tot") if isinstance(d, dict) and isinstance(d.get("tot"), dict) else None
        snap = snapshot.get(r["quote_no"])
        if not tot or ("_legacy" not in tot and snap is None):
            continue
        base = {"id": r["id"], "quote_no": r["quote_no"]}
        legacy = tot.get("_legacy") or (snap or {}).get("legacy")
        written = (snap or {}).get("written")
        if int(tot.get("formulaVer") or 1) < NEW_VER:
            out.append(dict(base, action="skip_not_v2", reason="已不是新口徑（舊式表單重存？）"))
        elif is_settled(r["settle_status"], r["deal_tag"]):
            out.append(dict(base, action="skip_settled_since", reason="遷移後已完結／結案，不自動還原（完結值已是新口徑）"))
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
        tot.pop("_legacy", None)
        for k in TOT_KEYS:
            if leg.get(k) is None:
                tot.pop(k, None)
            else:
                tot[k] = leg[k]
        if leg.get("formulaVer") is None:
            tot.pop("formulaVer", None)
        else:
            tot["formulaVer"] = leg["formulaVer"]
        if leg.get("tot_overheadPct") is None:
            tot.pop("overheadPct", None)
        else:
            tot["overheadPct"] = leg["tot_overheadPct"]
        tot.pop("_recalc", None)
        if not leg.get("had_overheadPct"):
            d.pop("overheadPct", None)
        conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=? WHERE id=?",
                     (json.dumps(d, ensure_ascii=False), leg.get("netMarginPctCol") if leg.get("netMarginPctCol") is not None else 0, it["id"]))
        if snapshot is not None:
            snapshot.pop(row["quote_no"], None)
        n += 1
    return n
