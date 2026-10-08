# -*- coding: utf-8 -*-
"""報價單的管銷分攤比率（`overheadPct`）與利潤欄位的伺服器端把關（第 48 班 S2；設計 docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md §3）。

- 設定（`system_settings`）：`overhead_rule_mode`＝`legacy`（預設）｜`v2`；`overhead_default_pct`（預設 25）；`overhead_migration_done`
  （既有報價單遷移完成的標記，由 `tools/overhead_migrate.py recalc --apply` 寫；沒有它伺服器不准切到 v2）。
  **`legacy` ＝ 新行為關閉**：數字完全不變（S2 可以不改任何金額就上線）；`v2` 才用 25% 口徑重算並蓋 `formulaVer=2`。
- 權限：比率與『存值（新建＝全域預設）』不同 ⇒ 只有最高管理者可以，否則 403（`legacy` 模式也擋，免得開關打開時冒出被偷改的值）。
- 已精算／結案（`settle_status=finalized` 或 `deal_tag=已結案`）：存檔端點不改比率、不重算（歷史不動）。
- **戳記只由伺服器蓋**：`tot.formulaVer`／`tot.overheadPct`／`tot._legacy`／`tot._recalc` 一律不採用用戶端送來的值（防偽造口徑戳記讓遷移跳過、標籤顯示錯誤）；
  `_legacy`／`_recalc`（遷移留下的回滾依據）沿用資料庫現值，不因表單存檔而遺失。
- 伺服器重算（Q9）：`v2` 時以 `helpers.profit_rules` 重算 `tot` 的稅前／稅額／含稅與利潤欄位（不信前端送來的）；`legacy` 時只做影子比對、不一致記 warning，
  不改任何值。
"""
import json
import logging
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from helpers import profit_rules as PR
from helpers.legal_params import round_half_up

_log = logging.getLogger(__name__)

MODE_KEY, DEFAULT_KEY, MIGRATION_KEY = "overhead_rule_mode", "overhead_default_pct", "overhead_migration_done"
MODES = ("legacy", "v2")
INDIRECT_KEYS = ("indirectLogistics", "indirectInstallation", "indirectTravel", "indirectWarranty", "indirectOther")
STAMP_KEYS = ("formulaVer", "overheadPct", "_legacy", "_recalc")
_ONLY_SUPERADMIN = "只有最高管理者可調整管銷分攤比率"


def parse_pct(v):
    """0～100、最多 1 位小數的數字（不收布林、字串、NaN）；整數回 int、否則 float。不合格 ⇒ ValueError。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("管銷分攤比率必須是數字")
    try:
        d = Decimal(repr(v))
    except InvalidOperation:
        raise ValueError("管銷分攤比率必須是數字")
    if not d.is_finite() or d < 0 or d > 100:
        raise ValueError("管銷分攤比率必須介於 0～100")
    if d != d.quantize(Decimal("0.1")):
        raise ValueError("管銷分攤比率最多 1 位小數")
    return int(d) if d == d.to_integral_value() else float(d)


def rule_mode() -> str:
    from helpers.settings import _get_setting
    m = _get_setting(MODE_KEY, "legacy")
    return m if m in MODES else "legacy"


def default_pct():
    from helpers.settings import _get_setting
    try:
        return parse_pct(_get_setting(DEFAULT_KEY, PR.DEFAULT_OVERHEAD_PCT))
    except ValueError:
        return PR.DEFAULT_OVERHEAD_PCT


def migration_done() -> bool:
    """既有報價單的遷移已完成（`overhead_migrate recalc --apply` 寫入標記）。沒有 ⇒ 不准切到 v2。"""
    from helpers.settings import _get_setting
    m = _get_setting(MIGRATION_KEY, None)
    return isinstance(m, dict) and bool(m.get("doneAt"))


def current_ver() -> int:
    return PR.FORMULA_VER if rule_mode() == "v2" else PR.LEGACY_VER


def is_settled(row) -> bool:
    """已精算／結案：`settle_status=finalized` 或 `deal_tag=已結案`（使用者 Q3）。"""
    return (row["settle_status"] or "") == "finalized" or (row["deal_tag"] or "") == "已結案"


def _num(x) -> float:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0


def _clean(v):
    """整數值回 int（JSON 與前端一致：100000 而不是 100000.0）。"""
    return int(v) if float(v) == int(v) else v


def server_totals(q: dict) -> dict:
    """依品項／折讓／運費／稅率重算 小計、稅前、稅額、含稅（與 quotation-form `calcTotals` 同式同進位）。"""
    subtotal = 0.0
    for i in q.get("items") or []:
        if isinstance(i, dict):
            subtotal = subtotal + _num(i.get("amount"))
    pretax = subtotal - _num(q.get("discount")) + _num(q.get("freight"))
    rate = q.get("taxRate")
    rate = 5 if (rate is None or isinstance(rate, bool) or not isinstance(rate, (int, float))) else rate
    tax = round_half_up(pretax, PR.pct_rate(rate)) if 0 <= rate <= 100 else 0
    return {"subtotal": _clean(subtotal), "pretax": _clean(pretax), "tax": tax, "total": _clean(pretax + tax)}


def server_profit(q: dict, pct, ver: int, pretax=None) -> dict:
    """依報價單內容重算利潤欄位（與 quotation-form `calcTotals` 同式同進位）。`pretax` 沒給 ⇒ 沿用 `tot.pretax`（影子比對用）。"""
    tot = q.get("tot") if isinstance(q.get("tot"), dict) else {}
    pretax = _num(tot.get("pretax")) if pretax is None else pretax
    total_cost = 0
    for i in q.get("items") or []:
        if isinstance(i, dict):
            total_cost = total_cost + _num(i.get("qty")) * _num(i.get("cost"))
    input_vat = round_half_up(total_cost, 0.05)
    r = PR.quote_profit(pretax, total_cost, input_vat, [_num(q.get(k)) for k in INDIRECT_KEYS], pct, ver)
    return {"totalCost": total_cost, "inputVat": input_vat, "directProfit": r["directProfit"],
            "directMarginPct": round_half_up(r["directMarginPct"], 10) / 10, "adminCost": r["adminCost"],
            "charityDonation": r["charityDonation"], "totalIndirect": r["totalIndirect"],
            "netProfit": round_half_up(r["netProfit"]), "netMarginPct": round_half_up(r["netMarginPct"], 10) / 10}


def _restore_stamps(tot: dict, old_tot, keys=STAMP_KEYS):
    """戳記欄位一律不採用用戶端的值：先清掉，再把資料庫現值放回（沒有就維持沒有）。"""
    for k in keys:
        tot.pop(k, None)
        if isinstance(old_tot, dict) and k in old_tot:
            tot[k] = old_tot[k]


def prepare(q: dict, user: dict, existing_row=None, quote_no: str = ""):
    """存檔前呼叫（建立／整份存檔；**要在開啟寫入連線、寄任何通知之前**）。就地修改 `q`；回傳比率變更資訊 `{old,new,default}`
    （沒變更 ⇒ None，供呼叫端寫稽核）。不合格的值 ⇒ 422；非最高管理者改比率 ⇒ 403。"""
    is_new = existing_row is None
    old = {}
    if not is_new:
        try:
            old = json.loads(existing_row["data_json"] or "{}") or {}
        except (TypeError, ValueError):
            old = {}
    old_tot = old.get("tot") if isinstance(old.get("tot"), dict) else {}
    if not isinstance(q.get("tot"), dict):
        q["tot"] = {}
    tot = q["tot"]
    default = default_pct()
    stored = None
    if old.get("overheadPct") is not None:
        try:
            stored = parse_pct(old["overheadPct"])
        except ValueError:
            stored = None
    base = stored if stored is not None else default
    if not is_new and is_settled(existing_row):                 # 歷史不動：比率與全部戳記沿用資料庫現值
        if stored is None:
            q.pop("overheadPct", None)
        else:
            q["overheadPct"] = stored
        _restore_stamps(tot, old_tot)
        return None
    incoming = q.get("overheadPct")
    if incoming is None or incoming == "":
        new = base
    else:
        try:
            new = parse_pct(incoming)
        except ValueError as e:
            raise HTTPException(422, str(e))
    changed = Decimal(repr(new)) != Decimal(repr(base))
    if changed and (user or {}).get("role") != "superadmin":
        raise HTTPException(403, _ONLY_SUPERADMIN)
    mode = rule_mode()
    if stored is not None or changed or mode == "v2":           # legacy 模式只在有存值或被最高管理者明確改過時才存比率（資料形狀不憑空變）
        q["overheadPct"] = new
    else:
        q.pop("overheadPct", None)
    _restore_stamps(tot, old_tot, keys=("_legacy", "_recalc"))   # 遷移留下的回滾依據沿用現值
    tot.pop("formulaVer", None)
    tot.pop("overheadPct", None)
    if "overheadPct" in q:
        tot["overheadPct"] = q["overheadPct"]                    # 精算頁／伺服器重算都從 tot 讀比率（單一讀法）
    if mode == "v2":
        tot.update(server_totals(q))
        tot.update(server_profit(q, new, PR.FORMULA_VER, pretax=tot["pretax"]))
        tot["overheadPct"], tot["formulaVer"] = new, PR.FORMULA_VER
    else:
        try:                                                      # 影子比對：重算與前端送來的是否逐位相同（不改任何值）
            mine = server_profit(q, new, PR.LEGACY_VER)
            diff = {k: (tot.get(k), v) for k, v in mine.items()
                    if k in ("adminCost", "charityDonation", "totalIndirect", "netProfit", "netMarginPct")
                    and tot.get(k) is not None and tot.get(k) != v}
            if diff:
                _log.warning("profit_guard shadow mismatch %s: %s", quote_no or "(new)", diff)
        except Exception:                                         # noqa: BLE001 — 影子比對失敗不可影響存檔
            _log.debug("profit_guard shadow compare failed", exc_info=True)
    return {"old": base, "new": new, "default": default} if changed else None
