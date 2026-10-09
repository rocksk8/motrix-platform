# -*- coding: utf-8 -*-
"""管銷分攤設定端點（第 48 班 S2）：登入者可讀目前口徑與全域預設；只有最高管理者可改（每次稽核）。"""
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import write_txn
from db import get_db
from helpers import _audit, _require_user, _tok
from helpers.settings import _set_setting
from modules.case import profit_guard as PG

router = APIRouter()


@router.get("/api/overhead/settings")
def get_overhead_settings(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "ver": PG.current_ver(), "migrationDone": PG.migration_done(),
            "charityBasis": PG.charity_basis(), "charityMode": PG.charity_mode(), "charityMigrationDone": PG.charity_migration_done()}


def _delete_setting(key):
    c = get_db()
    try:
        c.execute("DELETE FROM system_settings WHERE key=?", (key,))
        c.commit()
    finally:
        c.close()


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
    _require_user(authorization, require_superadmin=True)
    changes, detail = [], {}
    if "defaultPct" in body:
        try:
            new = PG.parse_pct(body["defaultPct"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        old = PG.default_pct()
        if new != old:
            _set_setting(PG.DEFAULT_KEY, new)
            detail["defaultPct"] = {"old": old, "new": new}
            changes.append("預設比率 %s%% → %s%%" % (old, new))
    if "ruleMode" in body:
        if body["ruleMode"] not in PG.MODES:
            raise HTTPException(422, "ruleMode 只能是 legacy 或 v2")
        old = PG.rule_mode()
        if body["ruleMode"] == "v2" and old != "v2":                 # 切到新口徑：要明確確認，且既有報價單的遷移必須已完成（防止新舊口徑的單混在一起）
            if body.get("confirm") is not True:
                raise HTTPException(422, "切換到新口徑會改變所有未精算報價單的營業利益與獎金基數，請帶 confirm=true 明確確認")
            if not PG.migration_done():
                raise HTTPException(409, "既有報價單尚未完成遷移（tools/overhead_migrate.py recalc --apply 會寫入完成標記），不能切換到新口徑")
        if body["ruleMode"] != old:
            if body["ruleMode"] == "legacy":                          # 退回舊口徑：遷移完成標記一併移除（legacy 期間存檔的單是舊口徑；再切 v2 前必須重新跑 recalc）
                _delete_setting(PG.MIGRATION_KEY)
                detail["migrationMarker"] = "removed"
                if PG.charity_mode() != "direct" or PG.charity_migration_done():     # 公益基數 total 只在 v2 生效：管銷退回 legacy ⇒ 公益基數一併退回 direct（標記一併移除）
                    _set_setting(PG.CHARITY_MODE_KEY, "direct")
                    _delete_setting(PG.CHARITY_MIGRATION_KEY)
                    detail["charityMode"] = {"old": "total", "new": "direct", "forcedBy": "ruleMode=legacy"}
                    changes.append("公益基數 → direct（隨管銷口徑退回）")
            _set_setting(PG.MODE_KEY, body["ruleMode"])
            detail["ruleMode"] = {"old": old, "new": body["ruleMode"]}
            changes.append("口徑 %s → %s" % (old, body["ruleMode"]))
    if "charityMode" in body:
        want = body["charityMode"]
        if want not in PG.CHARITY_MODES:
            raise HTTPException(422, "charityMode 只能是 direct 或 total")
        old = PG.charity_mode()
        if want == "total" and old != "total":                         # 切到含稅 1%：要確認，且必須 v2＋管銷遷移完成＋公益遷移完成
            if body.get("confirm") is not True:
                raise HTTPException(422, "切換公益基數會改變所有未精算報價單的營業利益與獎金基數，請帶 confirm=true 明確確認")
            if PG.rule_mode() != "v2" or not PG.migration_done():
                raise HTTPException(409, "公益基數 total 需要管銷口徑已是 v2 且完成遷移")
            if not PG.charity_migration_done():
                raise HTTPException(409, "既有報價單尚未完成公益基數遷移（tools/overhead_migrate.py charity recalc --apply 會寫入完成標記）")
        if want != old:
            if want == "direct":                                       # 退回舊基：完成標記一併移除（再切 total 前必須重新跑 charity recalc）
                _delete_setting(PG.CHARITY_MIGRATION_KEY)
                detail["charityMigrationMarker"] = "removed"
            _set_setting(PG.CHARITY_MODE_KEY, want)
            detail["charityMode"] = {"old": old, "new": want}
            changes.append("公益基數 %s → %s" % (old, want))
    if changes:
        _audit(_tok(authorization), "settings.overhead.update", "settings", "overhead", "；".join(changes), detail)
    return {"ok": True, "ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "charityBasis": PG.charity_basis(), "charityMode": PG.charity_mode()}
