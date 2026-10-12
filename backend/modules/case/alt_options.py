# -*- coding: utf-8 -*-
"""擇一方案的內部比較（M3 T4；T57）：`plan_view` 純函式——假設各組的選擇，重算金額、成本、毛利、管銷、公益金、營業利益。
- 與 `profit_guard.server_totals／server_profit` 共用 `counted_items`（不另寫第二套算式）；**不寫庫、不寫稽核、不改傳入的報價單**。
- 只給內部畫面用（成本權限者）。**輸出路徑（PDF／Excel／列印預覽／回簽頁）禁止引用這支**（含成本與毛利）。
- 已精算／結案：口徑與比率沿用單上戳記（唯讀、不重算戳記）；其餘依目前口徑與預設比率。
- 組合列表有硬頂（`COMBO_HARD_CAP`，同設定 `combo_view_max` 的上限）：超過只回組合總數，不展開。燈號顏色由前端依毛利率著色（單一來源 static/margin-tone.js）。"""
import itertools

from helpers import profit_rules as PR
from modules.case import profit_guard as PG

COMBO_HARD_CAP = 200            # 安全上限（與設定 combo_view_max 的最大值相同）；超過不展開，避免乘積爆炸

FIGURE_KEYS = ("subtotal", "pretax", "tax", "total", "totalCost", "inputVat", "directProfit", "directMarginPct",
               "adminCost", "charityDonation", "netProfit", "netMarginPct")


def stamps(q: dict, settled: bool = False):
    """(管銷比率, 口徑版本, 公益基數)：已精算／結案 ⇒ 單上戳記（舊單沒有戳記 ⇒ 舊口徑）；其餘 ⇒ 目前口徑。"""
    tot = q.get("tot") if isinstance(q.get("tot"), dict) else {}
    if settled:
        ver = tot.get("formulaVer") or PR.LEGACY_VER
        basis = PR.CHARITY_TOTAL if tot.get("charityBasis") == PR.CHARITY_TOTAL else PR.CHARITY_DIRECT
        pct = tot.get("overheadPct", q.get("overheadPct"))
    else:
        ver = PG.current_ver()
        basis = PG.charity_basis()
        pct = q.get("overheadPct")
    if pct in (None, ""):
        pct = PG.default_pct()
    return pct, ver, basis


def _figures(q: dict, picks: dict, st) -> dict:
    pct, ver, basis = st
    qq = dict(q, altPicks=picks, totalsByAlt=True)          # 比較視圖永遠假設『依方案選擇』已開（單據本身沒開時它只是試算）
    t = PG.server_totals(qq, q.get("tot") if isinstance(q.get("tot"), dict) else None)
    p = PG.server_profit(dict(qq, tot=t), pct, ver, pretax=t["pretax"], total=t["total"], charity_basis=basis)
    out = dict(t)
    out.update(p)
    return {k: out[k] for k in FIGURE_KEYS}


def _figures_actual(q: dict, st) -> dict:
    """單據目前實際的數字（總開關沒開 ⇒ 全部品項；開了 ⇒ 依已存選定）。"""
    pct, ver, basis = st
    t = PG.server_totals(q, q.get("tot") if isinstance(q.get("tot"), dict) else None)
    p = PG.server_profit(dict(q, tot=t), pct, ver, pretax=t["pretax"], total=t["total"], charity_basis=basis)
    out = dict(t)
    out.update(p)
    return {k: out[k] for k in FIGURE_KEYS}


def _label(i: dict) -> str:
    for k in ("description", "name", "brand"):
        v = i.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(i.get("id"))


def plan_view(q: dict, selection=None, *, settled: bool = False, combos: bool = False, combo_max: int = 24) -> dict:
    """`selection`＝`{組名: 品項id}` 的基準（其他組取這個；沒給或對不上 ⇒ 該組第一個選項）。回傳：
    `groups`（每組各選項與『其他組取基準』時的金額）、`baseline`、`current`（目前已存選定的暫估／確定值）、`unpicked`（尚未選定的組數）、
    `combos`（只有 `combos=True` 才計算：`total` 組合數、`rows`（依直接毛利率高→低、最多 `combo_max` 種）、`truncated`）。"""
    groups = PG.alt_groups(q)
    st = stamps(q, settled)
    sel = {str(k).strip(): str(v) for k, v in (selection or {}).items()} if isinstance(selection, dict) else {}
    baseline = {}
    for g, members in groups.items():
        ids = [str(m.get("id")) for m in members]
        baseline[g] = sel[g] if sel.get(g) in ids else ids[0]
    stored = q.get("altPicks") if isinstance(q.get("altPicks"), dict) else {}
    active = PG.alt_active(q)
    out = {
        "groups": [], "baseline": baseline, "active": active,
        "unpicked": sum(1 for g in groups if str(stored.get(g, "")) == "") if active else 0,
        "current": _figures_actual(q, st), "formulaVer": st[1], "overheadPct": st[0], "settled": bool(settled),
    }
    for g, members in groups.items():
        opts = []
        for m in members:
            picks = dict(baseline, **{g: str(m.get("id"))})
            opts.append(dict(_figures(q, picks, st), id=str(m.get("id")), label=_label(m)))
        out["groups"].append({"group": g, "options": opts})
    if combos:
        counts = [len(m) for m in groups.values()]
        total = 1
        for n in counts:
            total *= n
        cap = max(1, min(int(combo_max), COMBO_HARD_CAP))
        if not groups:
            total = 0
        c = {"total": total, "rows": [], "truncated": False, "expanded": 0 < total <= COMBO_HARD_CAP}
        if c["expanded"]:
            names = list(groups)
            rows = []
            for combo in itertools.product(*[[str(m.get("id")) for m in groups[g]] for g in names]):
                picks = dict(zip(names, combo))
                rows.append({"picks": picks, "figures": _figures(q, picks, st)})
            rows.sort(key=lambda r: (-r["figures"]["directMarginPct"], -r["figures"]["directProfit"]))
            c["truncated"] = len(rows) > cap
            c["rows"] = rows[:cap]
        else:
            c["truncated"] = total > 0
        out["combos"] = c
    return out
