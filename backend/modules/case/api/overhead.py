# -*- coding: utf-8 -*-
"""管銷分攤設定端點（第 48 班 S2）：登入者可讀目前口徑與全域預設；只有最高管理者可改（每次稽核）。"""
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import write_txn
from db import get_db
from helpers import _audit, _require_user, _tok
from helpers import profit_warning as _pw
from modules.case import profit_guard as PG

router = APIRouter()


@router.get("/api/overhead/settings")
def get_overhead_settings(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "ver": PG.current_ver(), "migrationDone": PG.migration_done(),
            "charityBasis": PG.charity_basis(), "charityMode": PG.charity_mode(), "charityMigrationDone": PG.charity_migration_done(),
            **_pw.rules_config()}          # T68 Q1：charityRatePct／targetMarginPct（連同既有 defaultPct，前端 MotrixProfitRules.configure 吃這三個）


@router.put("/api/quotations/{quote_no}/overhead-pct")
def put_quotation_overhead_pct(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """精算頁／案件頁調整**這張**報價單的管銷比率（第 52 班）。只有最高管理者；已精算／結案 409；與報價單表單同一把關
    （`profit_guard.change_pct`：比率 0～100／1 位小數、偏離預設要 `confirm:true`、只重算利潤欄位）。
    寫入在同一個 BEGIN IMMEDIATE 交易內並更新 `updated_at`（開著舊表單的人儲存時會因樂觀鎖得到 409『已被其他人更新』）。"""
    user = _require_user(authorization, require_superadmin=True)
    if "pct" not in body:
        raise HTTPException(422, "缺少 pct")
    conn = get_db()
    with write_txn(conn):                       # 讀 data_json 前先拿寫鎖；區塊內任何例外 ⇒ rollback 並關連線
        now = datetime.now().isoformat()
        res = PG.change_pct(conn, quote_no, body["pct"], user, body.get("confirm"), now)
        conn.commit()
    conn.close()
    if res["old"] != res["new"]:
        _audit(_tok(authorization), 'quotation.overhead_pct_change', 'quotation', quote_no,
               "%s 管銷分攤比率 %s%% → %s%%（預設 %s%%；精算頁）" % (quote_no, res["old"], res["new"], res["default"]),
               {"old": res["old"], "new": res["new"], "default": res["default"], "source": "settlement"})
    t = res["tot"]
    return {"ok": True, "overheadPct": res["new"], "default": res["default"], "updatedAt": now,
            "tot": {k: t.get(k) for k in ("adminCost", "charityDonation", "totalIndirect", "netProfit", "netMarginPct", "overheadPct", "formulaVer", "charityBasis")}}


@router.put("/api/overhead/settings")
def put_overhead_settings(body: dict = Body(...), authorization: str = Header(None)):
    """全域預設比率與口徑開關（回滾用）。只有最高管理者；只影響『之後新建』的報價單與口徑開關，不回改既有單。"""
    user = _require_user(authorization, require_superadmin=True)
    pending, warnings = [], []
    want_default = None
    if "defaultPct" in body:
        try:
            new = PG.parse_pct(body["defaultPct"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        want_default = new          # T69：先驗證；實際發布排到其他欄位都驗證完之後（publish 會立刻提交，後面欄位 422 時不留下半套）
    # S5：口徑（ruleMode／charityMode）不再直接寫舊鍵——改走設定群組 `overhead_basis` 的 `publish()`（確認期間＋第二位最高管理者核准＋稽核），
    # 只送「和目前不同」的欄位；輸入驗證與確認／遷移前置條件的錯誤碼維持原樣（422／409），發布排在所有驗證之後。
    sent, old_rule, old_charity = {}, PG.rule_mode(), PG.charity_mode()
    if "ruleMode" in body:
        if body["ruleMode"] not in PG.MODES:
            raise HTTPException(422, "ruleMode 只能是 legacy 或 v2")
        if body["ruleMode"] == "v2" and old_rule != "v2":            # 切到新口徑：要明確確認，且既有報價單的遷移必須已完成（防止新舊口徑的單混在一起）
            if body.get("confirm") is not True:
                raise HTTPException(422, "切換到新口徑會改變所有未精算報價單的營業利益與獎金基數，請帶 confirm=true 明確確認")
            if not PG.migration_done():
                raise HTTPException(409, "既有報價單尚未完成遷移（tools/overhead_migrate.py recalc --apply 會寫入完成標記），不能切換到新口徑")
        if body["ruleMode"] != old_rule:
            sent["ruleMode"] = body["ruleMode"]
            if body["ruleMode"] == "legacy" and old_charity != "direct":     # 公益基數 total 只在 v2 生效：管銷退回 legacy ⇒ 公益基數一併退回 direct
                sent["charityMode"] = "direct"
    if "charityMode" in body:
        want = body["charityMode"]
        if want not in PG.CHARITY_MODES:
            raise HTTPException(422, "charityMode 只能是 direct 或 total")
        if want == "total" and old_charity != "total":                 # 切到含稅 1%：要確認，且必須 v2＋管銷遷移完成＋公益遷移完成
            if body.get("confirm") is not True:
                raise HTTPException(422, "切換公益基數會改變所有未精算報價單的營業利益與獎金基數，請帶 confirm=true 明確確認")
            if PG.rule_mode() != "v2" or not PG.migration_done():
                raise HTTPException(409, "公益基數 total 需要管銷口徑已是 v2 且完成遷移")
            if not PG.charity_migration_done():
                raise HTTPException(409, "既有報價單尚未完成公益基數遷移（tools/charity_migrate.py recalc --apply --set-total 會寫入完成標記）")
        if want != old_charity:
            sent["charityMode"] = want
    if sent:
        from helpers import settings_registry as _SR
        from helpers.settings_groups_external import problems_text
        from core.definitions import DefinitionConflict
        raw = PG.basis_effective()                                   # CAS 期望值要用登錄表存的原始值；`old_rule` 是失效安全後的值（v2 缺遷移標記會顯示 legacy），拿來比會誤報 409
        cur = {"ruleMode": raw.get("ruleMode"), "charityMode": raw.get("charityMode")}
        try:
            res = _SR.publish("overhead_basis", sent, user=user["username"], actor=user,
                              reason=str(body.get("reason") or "").strip() or "管銷口徑調整（管銷設定入口）", ip="",
                              expected_values={k: cur[k] for k in sent}, supersede=body.get("supersede") is True)
        except _SR.SettingConflict as e:
            raise HTTPException(409, {"code": e.code, "keys": e.keys, "by": e.by, "at": e.at})
        except _SR.SettingError as e:
            raise HTTPException(409, problems_text(e))
        except DefinitionConflict as e:
            raise HTTPException(409, str(e))
        pending, warnings = list(res.get("pending") or []), list(res.get("warnings") or [])
    if want_default is not None:
        old = PG.default_pct()
        if want_default != old:
            # T69：預設比率是設定中心的 `overhead.default_pct`；舊入口也走同一條 publish（調低＝放寬 ⇒ 待核准＋確認期間；調高立即生效；舊鍵同步雙寫），
            # 不可繞過第二位最高管理者核准（D-K1）。publish 自己寫稽核（settings.overhead.update／.pending），這裡不再重複記。
            from helpers import settings_registry as _SR
            from core.definitions import DefinitionConflict
            try:
                res = _SR.publish("overhead", {"default_pct": want_default}, user=user["username"], actor=user,
                                  reason=str(body.get("reason") or "").strip() or "管銷預設比率調整（管銷設定入口）", ip="")
            except _SR.SettingError as e:
                raise HTTPException(422, str(e))
            except DefinitionConflict as e:
                raise HTTPException(409, str(e))
            pending, warnings = pending + list(res.get("pending") or []), warnings + list(res.get("warnings") or [])
    return {"ok": True, "ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "charityBasis": PG.charity_basis(), "charityMode": PG.charity_mode(),
            "pending": pending, "warnings": warnings}
