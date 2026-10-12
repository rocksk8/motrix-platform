# -*- coding: utf-8 -*-
"""報價單的管銷分攤比率（`overheadPct`）與利潤欄位的伺服器端把關（第 48 班 S2；設計 docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md §3）。

- 設定（`system_settings`）：`overhead_rule_mode`＝`legacy`（預設）｜`v2`；`overhead_default_pct`（預設 25）；`overhead_migration_done`
  （既有報價單遷移完成的標記，由 `tools/overhead_migrate.py recalc --apply` 寫；沒有它伺服器不准切到 v2）。
  **`legacy` ＝ 新行為關閉**：數字完全不變（S2 可以不改任何金額就上線）；`v2` 才用 25% 口徑重算並蓋 `formulaVer=2`。
- 權限：比率與『存值（新建＝全域預設）』不同 ⇒ 只有最高管理者可以，否則 403（`legacy` 模式也擋，免得開關打開時冒出被偷改的值）。
- 已精算／結案（`settle_status=finalized` 或 `deal_tag=已結案`）：存檔端點不改比率、不重算（歷史不動）。
- **戳記只由伺服器蓋**：`tot.formulaVer`／`tot.overheadPct`／`tot._legacy`／`tot._recalc` 一律不採用用戶端送來的值（防偽造口徑戳記讓遷移跳過、標籤顯示錯誤）；
  `_legacy`／`_recalc`（遷移留下的回滾依據）沿用資料庫現值，不因表單存檔而遺失。
- **公益捐款基數**（第 52 班；設計 docs/platform/plans/CHARITY-QUOTE-1PCT-DESIGN-T52.md）：`charity_basis_mode`（`direct`｜`total`，預設 `direct`）＋
  `charity_migration_done` 標記（`tools/charity_migrate.py recalc --apply --set-total` 寫）。`total` ＝ 公益捐款改為報價含稅金額 × 1%；**只在 v2 口徑生效**，
  要同時滿足 overhead_rule_mode=v2 ＋ overhead_migration_done ＋ charity_migration_done，否則一律當 `direct`（失效安全）。
  戳記 `tot.charityBasis`（`total`；舊基不帶）與 `tot._legacyCharity`（遷移前的公益／合計／營業利益，回滾依據）同樣只由伺服器蓋。
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
CHARITY_MODE_KEY, CHARITY_MIGRATION_KEY = "charity_basis_mode", "charity_migration_done"
CHARITY_MODES = (PR.CHARITY_DIRECT, PR.CHARITY_TOTAL)
# 已精算／結案單沿用資料庫現值的管銷與利潤衍生欄位
SETTLED_PROFIT_KEYS = ("adminCost", "charityDonation", "totalIndirect", "netProfit", "netMarginPct")
STAMP_KEYS = ("formulaVer", "overheadPct", "_legacy", "_recalc", "charityBasis", "_legacyCharity")
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
    if m == "v2" and not migration_done():                        # 失效安全：沒有遷移完成標記就算 legacy（防止新舊口徑的單混在一起）
        _log.warning("overhead_rule_mode=v2 但沒有 %s 標記 ⇒ 視為 legacy", MIGRATION_KEY)
        return "legacy"
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


def charity_migration_done() -> bool:
    """既有報價單的公益基數遷移已完成（`tools/charity_migrate.py recalc --apply --set-total` 寫入標記）。"""
    from helpers.settings import _get_setting
    m = _get_setting(CHARITY_MIGRATION_KEY, None)
    return isinstance(m, dict) and bool(m.get("doneAt"))


def charity_mode() -> str:
    """設定值（不含失效安全判斷）：`direct`｜`total`；缺鍵或不合法＝direct。"""
    from helpers.settings import _get_setting
    m = _get_setting(CHARITY_MODE_KEY, PR.CHARITY_DIRECT)
    return m if m in CHARITY_MODES else PR.CHARITY_DIRECT


def charity_basis() -> str:
    """實際生效的公益基數：只有 overhead v2（含遷移標記）＋ 公益遷移標記＋ 模式 total 三者齊備才是 total，否則 direct。"""
    if charity_mode() == PR.CHARITY_TOTAL and rule_mode() == "v2" and charity_migration_done():
        return PR.CHARITY_TOTAL
    return PR.CHARITY_DIRECT


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


def item_amount(i: dict) -> int:
    """品項金額＝數量 × 單價（四捨五入到元）；標題列（type=header）沒有金額（與 quotation-form `calcItem` 同式）。"""
    if i.get("type") == "header":
        return 0
    return round_half_up(_num(i.get("qty")), _num(i.get("unitPrice")))


ALT_SERVER_KEYS = ("altPicks", "altPickedAt", "altPickedBy")     # 擇一回簽選定：只有回簽路徑（T9）能寫；一般存檔一律由伺服器放回資料庫現值（H6）。另有 altTexts（存檔快照）見 stamp_alt_texts


def alt_group_of(i) -> str:
    """品項的擇一組名（去頭尾空白）；空字串＝非擇一。標題列、非字串一律視為非擇一（驗證另行擋下標題列／非字串）。"""
    if not isinstance(i, dict) or i.get("type") == "header":
        return ""
    g = i.get("altGroup")
    return g.strip() if isinstance(g, str) else ""


def alt_active(q) -> bool:
    """擇一方案的**單據層總開關**＝`totalsByAlt is True`（使用者 2026-10-11：『合計依方案選擇』）。沒開 ⇒ 擇一組別只是惰性資料：
    全部品項照一般報價單計入，沒有標記、沒有未選灰字、沒有合計文字、沒有選定／鎖定規則（與沒有擇一的單逐位元相同）。"""
    return isinstance(q, dict) and q.get("totalsByAlt") is True


def counted_items(q: dict, picks=None) -> list:
    """**計入合計與毛利的品項**（擇一方案的唯一分流點）：總開關（`alt_active`）沒開 ⇒ 全部品項；開了 ⇒ 非擇一項 ＋ 每個擇一組中被選定的那一項（該組沒選 ⇒ 整組不計入）。
    `picks` 預設取 `q.altPicks`（`{組名: 品項id}`）；`plan_view` 傳入假設的選擇。沒有任何 `altGroup` 的單 ⇒ 與全部品項逐項相同（零行為改變）。
    不計入 ≠ 不能存：未選項的單價、成本照存。"""
    items = [i for i in (q.get("items") or []) if isinstance(i, dict)]
    if not alt_active(q):
        return items
    if picks is None:
        picks = q.get("altPicks")
    picks = {str(k).strip(): str(v) for k, v in picks.items() if v not in (None, "")} if isinstance(picks, dict) else {}
    out = []
    for i in items:
        g = alt_group_of(i)
        if not g or (picks.get(g) is not None and picks[g] == str(i.get("id"))):
            out.append(i)
    return out


def alt_groups(q: dict) -> dict:
    """`{組名: [品項, …]}`（依出現順序；只含擇一品項）。"""
    out = {}
    for i in (q.get("items") or []):
        g = alt_group_of(i)
        if g:
            out.setdefault(g, []).append(i)
    return out


def restore_alt_server_fields(q: dict, old: dict) -> None:
    """一般存檔：`altPicks`／`altPickedAt`／`altPickedBy` 不採用用戶端的值，放回資料庫現值（沒有就移除）；
    現值若指向已不存在的組／品項（舊資料旁路）則該組的選定丟掉，保持伺服器自有欄位自洽。"""
    for k in ALT_SERVER_KEYS:
        q.pop(k, None)
        if isinstance(old, dict) and k in old:
            q[k] = old[k]
    picks = q.get("altPicks")
    if isinstance(picks, dict):
        groups = alt_groups(q)
        keep = {g: v for g, v in picks.items() if g in groups and any(str(i.get("id")) == str(v) for i in groups[g])}
        if keep:
            q["altPicks"] = keep
        else:
            q.pop("altPicks", None)
            q.pop("altPickedAt", None)
            q.pop("altPickedBy", None)
    elif "altPicks" in q:
        q.pop("altPicks", None)


def stamp_alt_texts(q: dict, old: dict, freeze: bool) -> None:
    """`altTexts`（合計格文字、說明句範本）是**伺服器自有的存檔快照**：用戶端的值一律不採用。有擇一內容才記；
    已回簽／已精算／已結案（`freeze`）且舊單有快照 ⇒ 沿用舊快照（改設定不改歷史單），其餘存檔時取目前設定中心的值。"""
    q.pop("altTexts", None)
    if not (alt_groups(q) and alt_active(q)):
        return
    prev = old.get("altTexts") if isinstance(old, dict) else None
    if freeze and isinstance(prev, dict) and isinstance(prev.get("total_text"), str) and isinstance(prev.get("note_template"), str):
        q["altTexts"] = {"total_text": prev["total_text"], "note_template": prev["note_template"]}
        return
    from modules.case import alt_policy
    q["altTexts"] = {"total_text": str(alt_policy.setting("total_text")), "note_template": str(alt_policy.setting("note_template"))}


def validate_alt(q: dict, max_groups: int) -> None:
    """擇一欄位驗證（422，白話）：`totalsByAlt` 只收真布林（MODULE-GUIDE §14.1）；`altGroup` 必須是文字、標題列不可擇一；
    每組至少 2 項；組數不超過 `max_groups`（設定中心 `quote_alt.alt_groups_max`）。`altPicks` 由伺服器放回（見 `restore_alt_server_fields`），這裡再核對一次自洽。"""
    if "totalsByAlt" in q and not isinstance(q["totalsByAlt"], bool):
        raise HTTPException(422, "「合計依方案選擇」必須是勾選或不勾選")
    for n, i in enumerate(q.get("items") or [], 1):
        if not isinstance(i, dict) or "altGroup" not in i:
            continue
        g = i["altGroup"]
        if g is None or g == "":
            continue
        if not isinstance(g, str):
            raise HTTPException(422, f"第 {n} 項的擇一組別必須是文字")
        if g.strip() and i.get("type") == "header":
            raise HTTPException(422, f"第 {n} 項是標題列，不能設為擇一方案")
    groups = alt_groups(q)
    if len(groups) > max_groups:
        raise HTTPException(422, f"擇一方案最多 {max_groups} 組，目前有 {len(groups)} 組")
    for g, members in groups.items():
        if len(members) < 2:
            raise HTTPException(422, f"擇一組別「{g}」至少要有 2 個品項")
        ids = [m.get("id") for m in members]
        if any(not isinstance(x, str) or not x.strip() for x in ids):
            raise HTTPException(422, f"擇一組別「{g}」的品項缺少編號，請重新整理頁面後再存")
        if len(set(ids)) != len(ids):
            raise HTTPException(422, f"擇一組別「{g}」內有重複的品項編號，請重新整理頁面後再存")
    picks = q.get("altPicks")
    if picks is not None:
        ok = isinstance(picks, dict) and all(g in groups and any(str(i.get("id")) == str(v) for i in groups[g]) for g, v in picks.items())
        if not ok:
            raise HTTPException(422, "客戶選定的方案與報價單品項不一致")


def _alt_signature(q: dict) -> tuple:
    """已精算／結案單比對用：擇一結構（哪個品項在哪一組）＋『合計依方案選擇』勾選。"""
    return (tuple(sorted((str(i.get("id")), alt_group_of(i)) for i in (q.get("items") or []) if alt_group_of(i))), bool(q.get("totalsByAlt")))


def effective_tax_rate(q: dict, stored_tot=None):
    """這張報價單的營業稅率（%）——**不靜默改舊語意**（稽核 #5）：
    ① 稅別 零稅率／免稅（`taxType` 或稅率 0 的舊單）⇒ 0；② 稅率是數字 ⇒ 那個數字；③ 完全沒有 `taxRate` 這個鍵（新單）⇒ 5；
    ④ 鍵存在但是 null／空字串（舊儲存形狀；舊 `calcTotals` 算 0%）⇒ 以資料庫存的 `tot.tax` 為準：存的是 0 ⇒ 0（維持報價當時顯示的樣子）、否則 5。"""
    from helpers.tax_calc import quote_tax_type
    if quote_tax_type(q) in ("zero", "exempt"):
        return 0
    r = q.get("taxRate")
    if isinstance(r, (int, float)) and not isinstance(r, bool):
        return r
    if "taxRate" not in q:
        return 5
    st = (stored_tot or {}).get("tax")
    return 0 if (isinstance(st, (int, float)) and not isinstance(st, bool) and st == 0) else 5


def server_totals(q: dict, stored_tot=None) -> dict:
    """依品項／折讓／運費／稅率重算 小計、稅前、稅額、含稅（與 quotation-form `calcTotals` 同式同進位）。
    品項金額一律由數量×單價重算（不採用用戶端送的 `amount`）；稅率規則見 `effective_tax_rate`（不改舊語意）。"""
    subtotal = 0.0
    for i in counted_items(q):                      # 擇一方案：只算計入集合（無 altGroup 的單＝全部品項）
        subtotal = subtotal + item_amount(i)
    pretax = subtotal - _num(q.get("discount")) + _num(q.get("freight"))
    rate = effective_tax_rate(q, stored_tot)
    tax = round_half_up(pretax, PR.pct_rate(rate)) if 0 <= rate <= 100 else 0
    return {"subtotal": _clean(subtotal), "pretax": _clean(pretax), "tax": tax, "total": _clean(pretax + tax)}


def server_profit(q: dict, pct, ver: int, pretax=None, total=None, charity_basis=None) -> dict:
    """依報價單內容重算利潤欄位（與 quotation-form `calcTotals` 同式同進位）。`pretax` 沒給 ⇒ 沿用 `tot.pretax`（影子比對用）。"""
    tot = q.get("tot") if isinstance(q.get("tot"), dict) else {}
    pretax = _num(tot.get("pretax")) if pretax is None else pretax
    total_cost = 0
    for i in counted_items(q):                      # 成本與進項稅同樣只算計入集合
        total_cost = total_cost + _num(i.get("qty")) * _num(i.get("cost"))
    input_vat = round_half_up(total_cost, 0.05)
    r = PR.quote_profit(pretax, total_cost, input_vat, [_num(q.get(k)) for k in INDIRECT_KEYS], pct, ver, total, charity_basis)
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
    restore_alt_server_fields(q, old)                           # 擇一選定只有回簽路徑能寫（H6）；一般存檔放回現值
    if not is_new and is_settled(existing_row):
        if _alt_signature(q) != _alt_signature(old):
            raise HTTPException(409, "已精算或已結案的報價單，不能更改擇一方案的設定")
    else:
        from modules.case import alt_policy
        validate_alt(q, alt_policy.setting("alt_groups_max"))
    _signed = False
    if not is_new:
        try:
            _signed = bool(existing_row["is_signed"])
        except (KeyError, IndexError):
            _signed = False
    stamp_alt_texts(q, old, freeze=(not is_new) and (_signed or is_settled(existing_row)))
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
        # 利潤欄位同戳記沿用資料庫現值（解鎖編輯是唯一能走到這裡的路徑，用戶端的值一律不採用）。
        # 已知取捨（PM 2026-10-10 裁示維持）：解鎖編輯改了價格時，利潤欄位在重新簽核、重新精算前仍是舊值。
        tot.update({k: old_tot[k] for k in SETTLED_PROFIT_KEYS if k in old_tot})
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
    _restore_stamps(tot, old_tot, keys=("_legacy", "_recalc", "_legacyCharity"))   # 遷移留下的回滾依據沿用現值
    tot.pop("formulaVer", None)
    tot.pop("charityBasis", None)                                 # 公益基數戳記只由伺服器依目前模式重蓋（用戶端值一律丟棄）
    tot.pop("overheadPct", None)
    if "overheadPct" in q:
        tot["overheadPct"] = q["overheadPct"]                    # 精算頁／伺服器重算都從 tot 讀比率（單一讀法）
    if mode == "v2":
        for i in q.get("items") or []:
            if isinstance(i, dict):
                i["amount"] = item_amount(i)                       # 品項金額由伺服器重算寫回（用戶端送的 amount 不採用）
        tot.update(server_totals(q, old_tot))
        basis = charity_basis()
        tot.update(server_profit(q, new, PR.FORMULA_VER, pretax=tot["pretax"], total=tot["total"], charity_basis=basis))
        tot["overheadPct"], tot["formulaVer"] = new, PR.FORMULA_VER
        if basis == PR.CHARITY_TOTAL:
            tot["charityBasis"] = basis
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


def change_pct(conn, quote_no: str, raw_pct, user: dict, confirm=False, now: str = ""):
    """精算頁／案件頁用的『只改管銷比率』（第 52 班；最高管理者）。呼叫端已在 `BEGIN IMMEDIATE` 內；本函式只改 `conn`，不 commit。
    與報價單表單存檔同一機制：只換比率並以 `server_profit` 重算利潤欄位（價格、稅額、品項一律不動）。
    ⇒ 404 找不到｜409 已精算／結案、不是新口徑（`tot.formulaVer != 2`）、或目前是 legacy 模式｜422 比率不合法、偏離預設卻沒 `confirm=true`｜403 非最高管理者。
    重算用這張單自己戳記的公益基數（`tot.charityBasis`），不看目前模式，避免只改比率卻悄悄換了公益算法。回 `{old,new,default,tot}`。"""
    if (user or {}).get("role") != "superadmin":
        raise HTTPException(403, _ONLY_SUPERADMIN)
    row = conn.execute("SELECT id, status, deal_tag, settle_status, data_json, updated_at FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        raise HTTPException(404, "報價單 %s 不存在" % quote_no)
    if is_settled(row):
        raise HTTPException(409, "已精算／結案的報價單不可調整管銷比率")
    if rule_mode() != "v2":
        raise HTTPException(409, "目前是舊口徑（legacy）模式，不能調整管銷比率")
    try:
        q = json.loads(row["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        raise HTTPException(409, "報價單資料無法解析")
    tot = q.get("tot") if isinstance(q.get("tot"), dict) else {}
    if tot.get("formulaVer") != PR.FORMULA_VER:
        raise HTTPException(409, "這張報價單不是新口徑（formulaVer 2），請先完成管銷口徑遷移")
    try:
        new = parse_pct(raw_pct)
    except ValueError as e:
        raise HTTPException(422, str(e))
    default = default_pct()
    try:
        old = parse_pct(tot.get("overheadPct") if tot.get("overheadPct") is not None else q.get("overheadPct"))
    except ValueError:
        old = default
    if Decimal(repr(new)) != Decimal(repr(default)) and confirm is not True:
        raise HTTPException(422, "管銷比率 %s%% 與預設 %s%% 不同，請帶 confirm=true 明確確認" % (new, default))
    basis = PR.CHARITY_TOTAL if tot.get("charityBasis") == PR.CHARITY_TOTAL else PR.CHARITY_DIRECT
    tot_total = tot.get("total") if tot.get("total") is not None else server_totals(q, tot)["total"]
    q["overheadPct"] = new
    tot["overheadPct"] = new
    tot.update(server_profit(q, new, PR.FORMULA_VER, pretax=tot.get("pretax"), total=tot_total, charity_basis=basis))
    tot["formulaVer"] = PR.FORMULA_VER
    q["tot"] = tot
    conn.execute("UPDATE quotations SET data_json=?, net_margin_pct=?, updated_at=? WHERE quote_no=?",
                 (json.dumps(q, ensure_ascii=False), tot.get("netMarginPct"), now, quote_no))
    return {"old": old, "new": new, "default": default, "tot": tot}
