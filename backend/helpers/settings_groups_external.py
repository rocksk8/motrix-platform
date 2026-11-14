# -*- coding: utf-8 -*-
"""S5 外部群組（SPEC §15.A，r3.5）：四個「設定值存在別處、操作入口在原頁面」的群組搬進設定中心的待生效／雙人核准／稽核機制。

[單位] helper:settings_groups_external    [層] L1    [穩定度] 實驗
[公開介面] register、T100_DEFAULT_CONFIG、BONUS_SLOTS、raw_get、raw_put、raw_delete、drift_report、GROUPS、T100_ACCOUNT_FIELDS、T100_KEY、TAX_KEY、bonus_cross_check、bonus_read、bonus_write、check_drift、overhead_cross_check、overhead_read、overhead_write、problems_text、t100_cross_check、t100_normalize、t100_read、t100_summarize、t100_write、tax_cross_check、tax_normalize、tax_read、tax_summarize、tax_write
[不變式]
  * 四個群組：`bonus_voucher`（獎金傳票科目 5 欄）、`tax_rules`（法規參數 1 個 json）、`t100_export`（T100 匯出科目 1 個 json）、
    `overhead_basis`（管銷口徑／公益基數 2 欄）。全部 `external=True`：設定中心的一般路由讀寫一律拒絕、不出現在清單，只能走原頁面的舊端點
    （舊端點內部改呼叫 `settings_registry.publish()`）。
  * 這個檔案是這些舊鍵的**唯一寫入點**（工具／migration 除外）：`bonus_case_voucher_*_code`、`tax_rules_versions`、`t100_export_config`、
    `overhead_rule_mode`、`charity_basis_mode`。守門見 `tests/platform/test_settings_external_s5.py`。
  * 轉接器 `read(conn)` 只讀舊鍵、**不得**呼叫登錄表（會遞迴）；`write(conn, values, old=None)` 只用傳入的 conn、冪等、不 commit。
  * 全部欄位 `loosen="both"`：任何實質變更都走確認期間＋第二位最高管理者核准（只有一位時＝原因＋等待期＋警告＋通知）。
  * `cross_check` 只檢查「和目前舊儲存不同」的欄位（舊值本來就在的不重驗），所以對單欄位的部分驗證也成立；
    到期寫入時（materialize）會再驗一次——已生效版本被改、科目已停用等情況會自動撤銷該筆待生效。
[契約題] backend/tests/platform/test_settings_external_s5.py
"""
import copy
import json
from datetime import datetime

from helpers.settings_registry import Adapter

# ── 舊儲存的低階讀寫（只用傳入的 conn；這是舊鍵唯一的寫入點）──────────────────────────

BONUS_SLOTS = {                                  # slot → (舊鍵, 預設科目, 中文名)；modules/payroll/bonus_vouchers.ACCOUNT_SLOTS 與這裡的 `T100_DEFAULT_CONFIG` 必須相同（守門測試比對）
    "expense":     ("bonus_case_voucher_expense_code",     "6111", "費用（薪資支出）"),
    "payable":     ("bonus_case_voucher_payable_code",     "2191", "應付（應付薪資）"),
    "withholding": ("bonus_case_voucher_withholding_code", "2252", "代扣稅款"),
    "nhi":         ("bonus_case_voucher_nhi_code",         "2252", "代收補充保費"),
    "bank":        ("bonus_case_voucher_bank_code",        "1113", "銀行存款"),
}
TAX_KEY = "tax_rules_versions"
T100_KEY = "t100_export_config"
RULE_MODE_KEY, CHARITY_MODE_KEY = "overhead_rule_mode", "charity_basis_mode"
RULE_MARKER_KEY, CHARITY_MARKER_KEY = "overhead_migration_done", "charity_migration_done"      # 標記由遷移工具寫；本檔只在「退回舊口徑」時刪除
RULE_MODES, CHARITY_MODES = ("legacy", "v2"), ("direct", "total")

#: T100 匯出設定的預設（accounting_export 的 `_DEFAULT_T100_CONFIG` 必須與這份相同——守門測試比對；登錄表欄位預設用這份）
T100_DEFAULT_CONFIG = {
    "bankAccounts": [],                  # [{name, acctCode}]
    "defaultBankAccountCode": "",
    "salesRevenueAccount": "",
    "outputTaxAccount": "",
    "contractorExpenseAccount": "",
    "remitFeeAccount": "",
    "receiptFeeAccount": "",
    "inventoryExpenseAccounts": {},      # {料件分類: 科目代號}
    "departmentCode": "",
    "voucherCategory": "轉",
}
T100_ACCOUNT_FIELDS = ("defaultBankAccountCode", "salesRevenueAccount", "outputTaxAccount", "contractorExpenseAccount", "remitFeeAccount", "receiptFeeAccount")


def raw_get(conn, key, default=None):
    """讀 system_settings 一個鍵（解析 JSON）；沒有／壞掉 ⇒ default。"""
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return default


def raw_put(conn, key, value):
    """冪等寫入一個鍵（不 commit）。"""
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                 (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()))


def raw_delete(conn, key):
    conn.execute("DELETE FROM system_settings WHERE key=?", (key,))


# ── 1. 獎金傳票科目 ──────────────────────────────────────────────────────────

def bonus_read(conn):
    """5 個科目代號（沒設定／空白 ⇒ 該欄預設科目；與原 `configured_accounts` 同一判斷）。"""
    out = {}
    for slot, (key, default, _l) in BONUS_SLOTS.items():
        v = raw_get(conn, key)
        out[slot] = v.strip() if isinstance(v, str) and v.strip() else default
    return out


def bonus_write(conn, values, old=None):
    for slot, v in values.items():
        if slot in BONUS_SLOTS:
            raw_put(conn, BONUS_SLOTS[slot][0], str(v).strip())


def _account_check():
    """科目有效性檢查走提供者 `voucher.account_check`（會計模組宣告）；L1 不直接 import L2 模組。"""
    from core import registry
    return registry.single_provider("voucher.account_check")


def _account_problem(check, conn, code):
    """與 `payroll.bonus_vouchers.account_problem` 同義：空 ⇒ 尚未設定；沒有提供者 ⇒ 無法驗證（不當作有效）；否則照提供者回的訊息。"""
    if not (code or "").strip():
        return "尚未設定科目"
    if check is None:
        return "會計模組未安裝，無法驗證科目"
    ok, err = check(conn, code)
    return "" if ok else err


def bonus_cross_check(values, conn):
    """每個**和目前不同**的科目：必須存在且未停用（原 `PUT /cases/voucher-accounts` 的 `account_problem`）。"""
    check = _account_check()
    cur = bonus_read(conn)
    out = []
    for slot, (_k, _d, label) in BONUS_SLOTS.items():
        v = values.get(slot)
        v = v.strip() if isinstance(v, str) else v
        if v == cur[slot]:
            continue
        msg = _account_problem(check, conn, v if isinstance(v, str) else "")
        if msg:
            out.append("%s：%s" % (label, msg))
    return out


# ── 2. 法規參數（扣繳／補充保費版本表）────────────────────────────────────────

def tax_read(conn):
    from helpers import legal_params as lp
    stored = raw_get(conn, TAX_KEY)
    if isinstance(stored, list) and stored:
        return {"versions": [lp._backfill(v) for v in lp.sort_versions(stored)]}
    legacy = raw_get(conn, lp.LEGACY_KEY)
    if isinstance(legacy, dict) and legacy:
        v = copy.deepcopy(legacy)
        v.setdefault("version", "2026")
        v.setdefault("effectiveFrom", lp.LEGACY_EFFECTIVE_FROM)
        if "sources" not in v:
            v["sources"] = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0]["sources"])
        return {"versions": [lp._backfill(v)]}
    return {"versions": lp.sort_versions(lp.DEFAULT_TAX_RULE_VERSIONS)}


def tax_normalize(v):
    from helpers import legal_params as lp
    return lp.sort_versions(v) if isinstance(v, list) else v


def tax_write(conn, values, old=None):
    if "versions" in values:
        raw_put(conn, TAX_KEY, tax_normalize(values["versions"]))


def tax_cross_check(values, conn):
    """結構＋守門（兼職補充保費門檻＝最低工資）＋已生效版本不可改刪。到期寫入時以到期當下的日期再驗一次（兩段式）。"""
    from helpers import legal_params as lp
    new = values.get("versions")
    errs = lp.validate_versions(new)
    if not errs:
        errs = lp.frozen_changes(tax_read(conn)["versions"], new, lp.today())
    return errs


def tax_summarize(old, new):
    from helpers import legal_params as lp

    def idx(vs):
        return {str(v.get("version")): v for v in (vs or []) if isinstance(v, dict)}
    o, n = idx(old), idx(new)
    if old is None:
        return ["共 %d 版：%s" % (len(n), "、".join("%s（%s 起）" % (k, v.get("effectiveFrom", "")) for k, v in n.items()))]
    lines = []
    for name, v in n.items():
        if name not in o:
            lines.append("新增版本「%s」（%s 起生效）" % (name, v.get("effectiveFrom", "")))
        elif lp._comparable(v) != lp._comparable(o[name]):
            lines.append("修改版本「%s」（%s 起生效）的內容" % (name, v.get("effectiveFrom", "")))
    for name, v in o.items():
        if name not in n:
            lines.append("刪除版本「%s」（%s 起生效）" % (name, v.get("effectiveFrom", "")))
    return lines or ["內容沒有實質變更"]


# ── 3. T100 匯出科目 ─────────────────────────────────────────────────────────

def _t100_canon(cfg):
    """標準形：補齊預設鍵、分類科目表丟掉空字串（空＝沒設，畫面會自動補回空白格）、銀行帳戶只留 name／acctCode。"""
    c = {**copy.deepcopy(T100_DEFAULT_CONFIG), **(cfg if isinstance(cfg, dict) else {})}
    inv = c.get("inventoryExpenseAccounts")
    c["inventoryExpenseAccounts"] = {str(k): v for k, v in (inv.items() if isinstance(inv, dict) else []) if isinstance(v, str) and v.strip()}
    banks = c.get("bankAccounts")
    c["bankAccounts"] = [{"name": b.get("name", ""), "acctCode": b.get("acctCode", "")} for b in (banks if isinstance(banks, list) else []) if isinstance(b, dict)]
    return c


def t100_read(conn):
    return {"config": _t100_canon(raw_get(conn, T100_KEY, {}))}


def t100_normalize(v):
    return _t100_canon(v) if isinstance(v, dict) else v


def t100_write(conn, values, old=None):
    if "config" in values:
        raw_put(conn, T100_KEY, t100_normalize(values["config"]))


def _t100_codes(cfg):
    out = [(f, cfg.get(f, "")) for f in T100_ACCOUNT_FIELDS]
    out += [("bankAccounts[%d]" % i, b.get("acctCode", "")) for i, b in enumerate(cfg.get("bankAccounts", []))]
    out += [("inventoryExpenseAccounts[%s]" % k, v) for k, v in cfg.get("inventoryExpenseAccounts", {}).items()]
    return out


def t100_cross_check(values, conn):
    """結構（同原 pydantic 模型）＋新增／變更的科目代號必須存在且未停用（舊值不重驗；停用的舊值由 GET 的 codeIssues 提示）。"""
    cfg = values.get("config")
    if not isinstance(cfg, dict):
        return ["T100 匯出設定格式不對"]
    cfg = t100_normalize(cfg)
    out = []
    if not all(isinstance(cfg.get(f), str) for f in T100_ACCOUNT_FIELDS + ("departmentCode", "voucherCategory")):
        out.append("科目代號、部門別、傳票別都必須是文字")
    if any(not isinstance(b.get("name"), str) or not isinstance(b.get("acctCode"), str) for b in cfg.get("bankAccounts", [])):
        out.append("銀行帳戶的名稱與科目代號都必須是文字")
    if out:
        return out
    cur = dict(_t100_codes(t100_read(conn)["config"]))
    check = _account_check()
    for where, code in _t100_codes(cfg):
        if (code or "").strip() and cur.get(where) != code:
            if check is None:
                out.append("會計模組未安裝，無法驗證科目")
                break
            ok, err = check(conn, code)
            if not ok:
                out.append(err)
    return out


def t100_summarize(old, new):
    names = {"defaultBankAccountCode": "預設銀行科目", "salesRevenueAccount": "銷貨收入科目", "outputTaxAccount": "銷項稅額科目",
             "contractorExpenseAccount": "承攬商費用科目", "remitFeeAccount": "匯款手續費科目", "receiptFeeAccount": "收款手續費科目",
             "departmentCode": "部門別", "voucherCategory": "傳票別"}
    o, n = _t100_canon(old or {}), _t100_canon(new or {})
    lines = ["%s：%s → %s" % (lb, o.get(k) or "（空）", n.get(k) or "（空）") for k, lb in names.items() if o.get(k) != n.get(k)]
    if o["bankAccounts"] != n["bankAccounts"]:
        lines.append("銀行帳戶 %d 個 → %d 個" % (len(o["bankAccounts"]), len(n["bankAccounts"])))
    ch = sorted(k for k in set(o["inventoryExpenseAccounts"]) | set(n["inventoryExpenseAccounts"])
                if o["inventoryExpenseAccounts"].get(k) != n["inventoryExpenseAccounts"].get(k))
    if ch:
        lines.append("料件分類科目變更：%s" % "、".join(ch))
    return lines or ["內容沒有實質變更"]


# ── 4. 管銷口徑／公益基數 ────────────────────────────────────────────────────

def _marker_ok(conn, key):
    m = raw_get(conn, key)
    return isinstance(m, dict) and bool(m.get("doneAt"))


def overhead_read(conn):
    rm, cm = raw_get(conn, RULE_MODE_KEY, "legacy"), raw_get(conn, CHARITY_MODE_KEY, "direct")
    return {"ruleMode": rm if rm in RULE_MODES else "legacy", "charityMode": cm if cm in CHARITY_MODES else "direct"}


def overhead_write(conn, values, old=None):
    """寫兩個模式鍵。退回舊口徑（有 `old` 且是由非 legacy 轉成 legacy）⇒ 管銷遷移完成標記一併移除、公益基數一併退回 direct（同原端點）；
    公益基數由 total 轉成 direct ⇒ 公益遷移標記移除。沒有 `old`（還原等）⇒ 不動標記。"""
    cur = overhead_read(conn)
    rm = values.get("ruleMode", cur["ruleMode"])
    cm = values.get("charityMode", cur["charityMode"])
    if rm == "legacy" and cm != "direct":
        cm = "direct"                                   # 公益基數 total 只在 v2 生效
    if old is not None:
        reverting = rm == "legacy" and old.get("ruleMode") not in (None, "legacy")
        if reverting:                                   # 退回舊口徑：遷移完成標記（管銷＋公益）一併移除，再切 v2 前必須重新跑遷移
            raw_delete(conn, RULE_MARKER_KEY)
            raw_delete(conn, CHARITY_MARKER_KEY)
        elif cm == "direct" and old.get("charityMode") not in (None, "direct"):
            raw_delete(conn, CHARITY_MARKER_KEY)
    if "ruleMode" in values:
        raw_put(conn, RULE_MODE_KEY, rm)
    if "charityMode" in values or cm != cur["charityMode"]:
        raw_put(conn, CHARITY_MODE_KEY, cm)


def overhead_cross_check(values, conn):
    """舊口徑時公益基數只能 direct；要切到 v2 必須管銷遷移完成；要切到 total 必須 v2＋兩個遷移標記都完成。
    欄位值等於預設時視為「沒送」，改用目前舊儲存的值判斷（單欄位的部分驗證也成立）。"""
    cur = overhead_read(conn)
    rm = values.get("ruleMode", "legacy")
    cm = values.get("charityMode", "direct")
    rm_eff = cur["ruleMode"] if rm == "legacy" else rm
    cm_eff = cur["charityMode"] if cm == "direct" else cm
    out = []
    if rm == "v2" and cur["ruleMode"] != "v2" and not _marker_ok(conn, RULE_MARKER_KEY):
        out.append("既有報價單尚未完成遷移（遷移完成後才能切換到新口徑）")
    if cm == "total" and cur["charityMode"] != "total":
        if rm_eff != "v2" or not _marker_ok(conn, RULE_MARKER_KEY):
            out.append("公益基數改為含稅金額，需要管銷口徑已是新口徑且完成遷移")
        elif not _marker_ok(conn, CHARITY_MARKER_KEY):
            out.append("既有報價單尚未完成公益基數遷移")
    if rm_eff == "legacy" and cm_eff == "total":
        out.append("舊口徑下公益基數只能維持原本算法")
    return out


def problems_text(e):
    """`SettingError.problems`（`{path,message}` 或跨欄位檢查回的純字串）→ 一句話；舊端點把它當 400 訊息。"""
    parts = [(p.get("message") if isinstance(p, dict) else str(p)) for p in (getattr(e, "problems", None) or [])]
    return "；".join(x for x in parts if x) or str(e)


# ── 每日對帳：登錄表生效值 vs 舊儲存 ──────────────────────────────────────────

GROUPS = {"bonus_voucher": bonus_read, "tax_rules": tax_read, "t100_export": t100_read, "overhead_basis": overhead_read}


def drift_report(conn):
    """每個外部群組：登錄表目前生效值（嚴格讀取）和舊儲存是否一致。回 `[(群組, 不一致欄位[])]`（只列有分歧的）。
    有分歧代表有人繞過登錄表寫了舊鍵（工具／手改資料庫）；讀取端已經以登錄表為準，不會用到舊鍵的值——要人工確認。"""
    from helpers import settings_registry as sr
    out = []
    for g, raw in GROUPS.items():
        try:
            eff, old = sr.get_group_effective(g, conn=conn), raw(conn)
        except Exception as e:                       # noqa: BLE001
            out.append((g, ["讀取失敗：%s" % str(e)[:80]]))
            continue
        bad = [k for k in old if json.dumps(eff.get(k), sort_keys=True, ensure_ascii=False) != json.dumps(old[k], sort_keys=True, ensure_ascii=False)]
        if bad:
            out.append((g, bad))
    return out


def check_drift(mode="daily"):
    """每日工作：登錄表生效值和舊儲存有分歧 ⇒ 記錯誤紀錄；每日模式另通知其他最高管理者（啟動補跑只記紀錄，避免重複通知）。回分歧清單。"""
    import logging
    from db import get_db
    conn = get_db()
    try:
        rep = drift_report(conn)
        if rep and mode == "daily":
            from helpers import config_ledger as L
            for g, bad in rep:
                L._notify_others(conn, "", "setting:%s" % g, g, "money", "settings-center.html", datetime.now().isoformat(timespec="seconds"),
                                 "設定「%s」的生效值和舊儲存不一致（%s）：可能有人繞過設定機制直接改了資料，請人工確認。" % (g, "、".join(bad)))
            conn.commit()
        for g, bad in rep:
            logging.getLogger("motrix.settings").error("settings: 外部群組 %s 生效值與舊儲存分歧：%s", g, bad)
        return rep
    finally:
        conn.close()


# ── 登錄 ─────────────────────────────────────────────────────────────────────

def _scope(documents, amounts, roles=None):
    return {"documents": documents, "roles": roles or ["最高管理者", "財務"], "amounts": amounts, "reversible": True, "effective": "pending"}


def register(S, _register_core):
    from helpers import legal_params as lp
    slot_q = {
        "expense": ("獎金分潤產生傳票時，「費用」那一行要用哪個科目？", "費用科目", "進入待發放時，借方（費用）用的會計科目代號，預設 6111。"),
        "payable": ("「應付」那一行要用哪個科目？", "應付科目", "進入待發放時貸方、標記已發放時借方的會計科目代號，預設 2191。"),
        "withholding": ("「代扣稅款」那一行要用哪個科目？", "代扣稅款科目", "標記已發放時，貸方代扣所得稅用的會計科目代號，預設 2252。"),
        "nhi": ("「代收補充保費」那一行要用哪個科目？", "代收補充保費科目", "標記已發放時，貸方代收二代健保補充保費用的會計科目代號，預設 2252。"),
        "bank": ("發放時預設從哪個銀行科目支出？", "預設銀行科目", "標記已發放時，出納沒有另外選銀行就用這個科目，預設 1113。"),
    }
    fields = []
    for slot, (_k, default, _lb) in BONUS_SLOTS.items():
        q, label, help_ = slot_q[slot]
        fields.append(S(slot, "str", default, risk="money", loosen="both", recommended=default, question=q, label=label, help=help_,
                        impact="只影響之後新產生的獎金傳票草稿；已經開出的傳票不會改。科目不存在或已停用時系統會拒絕。",
                        risk_text="【高影響】科目改錯會讓獎金傳票的借貸落到錯誤的會計科目，影響財務報表與申報；需第二位最高管理者核准，等待期滿才生效。",
                        impact_scope=_scope(["獎金分潤傳票草稿", "財務報表"], "改變之後新產生的獎金傳票借貸科目；已開出的傳票不改。")))
    _register_core("bonus_voucher", "獎金分潤傳票科目", fields, sensitive=True, risk="money",
                   help="獎金分潤產生傳票草稿時用的五個會計科目。實際操作入口仍在獎金設定頁。",
                   legacy_adapter=Adapter(bonus_read, bonus_write), cross_check=bonus_cross_check, external=True)

    _register_core(
        "tax_rules", "法規參數（扣繳與補充保費）",
        [S("versions", "json", copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS), risk="legal", loosen="both", summarize=tax_summarize,
           question="法規參數（扣繳率、起扣標準、補充保費、最低工資）要新增或修改哪一版？", label="法規參數版本表",
           help="各年度的所得扣繳率、起扣標準、二代健保補充保費與最低工資。實際操作入口仍在法規參數設定頁。",
           impact="勞報單、薪資單與獎金的扣繳、補充保費會依生效日套用對應的版本；已經生效的版本不能修改或刪除，要更正請新增一版。",
           risk_text="【法遵】數字填錯會讓之後開立的勞報單與薪資單扣繳金額錯誤；需第二位最高管理者核准，等待期滿才生效，且生效前會再檢查一次。",
           impact_scope=_scope(["勞報單", "薪資單", "獎金分潤"], "改變之後開立單據的扣繳稅額與補充保費；已開立的單據不改。", ["最高管理者", "財務", "人資"]))],
        sensitive=True, risk="legal", help="扣繳率、起扣標準、補充保費與最低工資的年度版本表。實際操作入口仍在法規參數設定頁。",
        legacy_adapter=Adapter(tax_read, tax_write, tax_normalize), cross_check=tax_cross_check, external=True)

    _register_core(
        "t100_export", "鼎新傳票匯出科目",
        [S("config", "json", copy.deepcopy(T100_DEFAULT_CONFIG), risk="money", loosen="both", summarize=t100_summarize,
           question="匯出給會計師的傳票，各種金額要對應到哪些會計科目？", label="鼎新匯出科目設定",
           help="銷貨收入、銷項稅額、承攬商費用、手續費、銀行帳戶與料件分類對應的科目代號。實際操作入口仍在 鼎新匯出設定頁。",
           impact="只影響之後匯出的 鼎新傳票；已經匯出的檔案不會改。科目代號不存在或已停用時系統會拒絕。",
           risk_text="【高影響】科目代號打錯，匯出的傳票要到會計師匯入時才會發現；需第二位最高管理者核准，等待期滿才生效。",
           impact_scope=_scope(["鼎新傳票匯出檔"], "改變之後匯出傳票的科目對應；已匯出的檔案不改。", ["最高管理者", "財務"]))],
        sensitive=True, risk="money", help="鼎新傳票匯出的會計科目對應。實際操作入口仍在 鼎新匯出設定頁。",
        legacy_adapter=Adapter(t100_read, t100_write, t100_normalize), cross_check=t100_cross_check, external=True)

    _register_core(
        "overhead_basis", "管銷與公益金計算口徑",
        [S("ruleMode", "str", "legacy", risk="money", loosen="both", recommended="legacy",
           choices=[("legacy", "舊口徑", "管銷以稅前金額的固定比例計算（目前的做法）。"),
                    ("v2", "新口徑", "管銷以實際毛利乘上報價單比率計算，會改變所有未精算報價單的營業利益與獎金基數。")],
           question="管銷分攤要用哪一種算法？", label="管銷計算口徑", help="決定管銷分攤的算法。新口徑要先完成既有報價單的遷移才能切換。",
           impact="切換會改變所有未精算報價單的營業利益與獎金基數；已精算的單據不改。退回舊口徑時，遷移完成標記與公益基數設定會一併退回。",
           risk_text="【高影響】切換口徑會讓未精算報價單的營業利益與獎金基數整批改變；需第二位最高管理者核准，等待期滿才生效。",
           impact_scope=_scope(["報價單", "精算", "獎金分潤", "營運報表"], "改變未精算報價單的管銷、營業利益與獎金基數；已精算的單據不改。", ["最高管理者", "財務", "業務"])),
         S("charityMode", "str", "direct", risk="money", loosen="both", recommended="direct",
           choices=[("direct", "直接毛利基數", "公益捐款以直接毛利為基數（目前的做法）。"),
                    ("total", "報價含稅金額", "公益捐款改為報價含稅金額的固定比例；只在新口徑且完成遷移後生效。")],
           question="公益捐款要用哪個金額當基數？", label="公益捐款基數", help="決定公益捐款的計算基數。改為含稅金額要先完成管銷與公益基數的遷移。",
           impact="切換會改變所有未精算報價單的公益捐款、營業利益與獎金基數；已精算的單據不改。",
           risk_text="【高影響】切換基數會讓未精算報價單的公益捐款與營業利益整批改變；需第二位最高管理者核准，等待期滿才生效。",
           impact_scope=_scope(["報價單", "精算", "獎金分潤", "營運報表"], "改變未精算報價單的公益捐款與營業利益；已精算的單據不改。", ["最高管理者", "財務", "業務"]))],
        sensitive=True, risk="money", help="管銷與公益捐款的計算口徑。預設比率另在「管銷分攤比率」設定；實際操作入口仍在精算相關的管銷設定頁。",
        legacy_adapter=Adapter(overhead_read, overhead_write), cross_check=overhead_cross_check, external=True)
