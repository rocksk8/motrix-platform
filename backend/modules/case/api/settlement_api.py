# -*- coding: utf-8 -*-
"""案件精算存取端點（GET／PUT `/api/quotations/{quote_no}/settlement`）——第 40 班起自 `api/quotations.py` 純搬移出來（逐字，零行為變更）。
路由路徑、函式名稱、驗證相依、回應形狀都與搬移前相同；`settlement-actuals`（單一來源計算）在 `api/settlement_actuals.py`。"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from archive import _backup_quotation
from core.txn import write_txn
from db import get_db, spawn_bg_thread
from helpers import _audit, _require_user, _tok, notify_settlement_finalized
from helpers.case_access import require_case
from modules.case.api.quotations import _require_financial_view
from modules.case.quotations import save_quotation_json

router = APIRouter()


# ── Settlement ────────────────────────────────────────────────────────────────

class SettlementIn(BaseModel):
    settlement: dict
    reason: str = ""        # 35c：對已完結的精算再存（重新開啟或再完結）必填；記入編輯歷程與稽核紀錄
    expectedUpdatedAt: Optional[str] = None     # 38：樂觀鎖（選填）——帶 GET /settlement 回的 updatedAt（或上一次 PUT 回的 updated_at）；與現況不同 ⇒ 409，不存檔


@router.get("/api/quotations/{quote_no}/settlement")
def get_settlement(quote_no: str, authorization: str = Header(None)):
    # 2026-09-13（模組權限稽核）：原本只要求登入。`quote_no` 可列舉
    # （MQ-YYYYMM-NNN），等於任何已登入帳號都能讀到**任何**案件的成本、毛利
    # 與精算明細——跟 2026-08-24 修掉的報價單 IDOR 是同一種洞，只是漏在這支。
    # 改用跟同一批資料既有端點一致的擁有者規則（admin+ 直通、否則必須是
    # 該案業務或被指派的協作者），見 modules/case/quotations.py::CASE_ACCESS。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, sales_person_id, sales_person, assigned_user_ids, updated_at "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    require_case(user, row, quote_no)
    _require_financial_view(user)
    data = json.loads(row["data_json"] or "{}")
    return {"settlement": data.get("settlement", None), "items": data.get("items", []), "updatedAt": row["updated_at"],
            "tot": data.get("tot", {}), "customerName": data.get("customerName", ""),
            "projectName": data.get("projectName", "")}


@router.put("/api/quotations/{quote_no}/settlement")
def update_settlement(quote_no: str, body: SettlementIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now  = datetime.now().isoformat()
    conn = get_db()
    with write_txn(conn):   # lost update：讀 data_json 前先拿寫鎖（modules.case.quotations.begin_write）；區塊內任何例外 ⇒ rollback＋關連線（不留寫鎖）
        row = conn.execute(
            "SELECT data_json, customer_name, sales_person_id, sales_person, assigned_user_ids, updated_at, deal_tag "
            "FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(404, f"報價單 {quote_no} 不存在")
        # 2026-09-13（模組權限稽核）：這支原本只要求登入——任何已登入帳號（含 viewer
        # 與 automation 服務帳號）都能覆寫**任何**案件的成本精算，只有 finalized 之後
        # 才收斂成「僅 superadmin」。這是全系統唯一一個「寫入」層級的缺口，補上與
        # GET 相同的擁有者檢查。
        try:
            require_case(user, row, quote_no)
            _require_financial_view(user)
        except HTTPException:
            conn.close()
            raise
        if body.settlement.get("status") == "finalized" and (row["deal_tag"] or "") not in ("已成案", "已結案"):      # 40：沒成案的報價單不能完結精算（已結案＝管理員重新開啟後再完結）
            conn.close()
            raise HTTPException(409, "這張報價單還沒成案（目前：%s），不能完結精算；請先把案件標為已成案" % ((row["deal_tag"] or "") or "未標記"))
        if body.expectedUpdatedAt is not None and (row["updated_at"] or "") != body.expectedUpdatedAt:      # 38：樂觀鎖——兩人（或兩個分頁）同時編輯，後存的不再悄悄蓋掉前存的
            conn.close()
            raise HTTPException(409, "精算（或這張報價單）已被其他人更新，請重新載入後再存")
        data = json.loads(row["data_json"] or "{}")
        existing_settlement = data.get("settlement") or {}
        if existing_settlement.get("status") == "finalized" and user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "精算已完結，僅超級管理員可重新修改")
        was_final = existing_settlement.get("status") == "finalized"
        reopen_reason = (body.reason or "").strip()
        if was_final and not reopen_reason:                    # 35c（使用者裁示）：已完結的精算要重新開啟或修改，必須填理由（留稽核軌跡）
            conn.close()
            raise HTTPException(422, "重新開啟或修改已完結的精算必須填寫理由")
        if len(reopen_reason) > 500:
            conn.close()
            raise HTTPException(422, "理由太長（上限 500 字）")
        bad = None
        if "schemaVersion" in body.settlement:                 # 39：存檔格式標記（整數；v2＝實際成本 0 是真的 0）
            from modules.case import settlement_actuals as _SAv
            bad = _SAv.validate_schema_version(body.settlement)
        if bad:
            conn.close()
            raise HTTPException(422, bad)
        if "items" in body.settlement:                         # 36：品項 actualSource（顯示用標記）的值域
            from modules.case import settlement_actuals as _SAi
            bad = _SAi.validate_item_sources(body.settlement.get("items"))
            if bad:
                conn.close()
                raise HTTPException(422, bad)
        if "offsets" in body.settlement:                       # 33-A4：沖銷對應的驗證（kind／品項存在／單一去處／ref 在未對應清單）
            from modules.case import settlement_actuals as _SA
            bad = _SA.validate_offsets(conn, quote_no, body.settlement.get("offsets"), existing_settlement.get("offsets"))
            if bad:
                conn.close()
                raise HTTPException(422, bad)
        if body.settlement.get("status") == "finalized":       # 38：summary 缺 itemActualTotal ⇒ 伺服器重建（過去無從比對、照存）
            from modules.case import settlement_actuals as _SAr
            _SAr.rebuild_summary_if_missing(conn, quote_no, body.settlement)
        if body.settlement.get("status") == "finalized":       # 33-A5（D10）；35c：已完結再存成完結也比對（要有理由；舊口徑頁面送的含稅數字會被擋 ⇒ 請先重新開啟再完結）
            from modules.case import settlement_actuals as _SA
            diffs = _SA.check_finalize(conn, quote_no, body.settlement)
            if diffs:
                conn.close()
                raise HTTPException(409, "完結前系統重算的數字與畫面不一致（資料在你編輯期間有變動，或精算頁版本過舊）——請重新整理精算頁再完結。差異：" + "；".join(diffs))
        if body.settlement.get("status") == "finalized" and isinstance(body.settlement.get("summary"), dict) and "itemActualTotal" in body.settlement["summary"]:
            from modules.case import settlement_actuals as _SA2
            _SA2.fill_downstream(conn, quote_no, body.settlement)      # 35c F1：沒送的下游欄位由伺服器重算值補齊＋蓋口徑標記（舊完結案沒有標記＝含稅口徑）
        data["settlement"] = body.settlement

        # append edit history entry for settlement saves
        is_finalized = body.settlement.get("status") == "finalized"
        history = data.get("editHistory") or []
        if not isinstance(history, list):
            history = []
        settle_rev = len(history) + 1
        entry = {
            "rev":       settle_rev,
            "at":        now,
            "by":        user["username"],
            "byDisplay": user["display_name"] or user["username"],
            "type":      "settlement_finalized" if is_finalized else "settlement_draft",
            **({"reason": reopen_reason, "from": "finalized"} if was_final else {}),
        }
        if is_finalized:                                       # 38：完結快照——之後有人重新開啟修改時，歷程仍留得住「當時凍結的數字」
            _sm = body.settlement.get("summary") if isinstance(body.settlement.get("summary"), dict) else {}
            entry.update(netProfit=_sm.get("netProfit"), totalActualCost=_sm.get("totalActualCost"), dispatchBasis=_sm.get("dispatchBasis"), frozenAt=now)
        elif not was_final and history and history[-1].get("type") == "settlement_draft" and history[-1].get("by") == entry["by"] and "reason" not in history[-1]:
            settle_rev = history[-1].get("rev", settle_rev)    # 38：同一人連續存草稿＝合併成一筆（自動存檔不再讓歷程無限成長）；理由／完結紀錄永不合併
            history.pop()
            entry["rev"] = settle_rev
        history.append(entry)
        drafts = [i for i, e in enumerate(history) if isinstance(e, dict) and e.get("type") == "settlement_draft" and "reason" not in e]
        for i in reversed(drafts[:-50] if len(drafts) > 50 else []):      # 38：精算草稿紀錄最多留最後 50 筆（舊的先丟；完結／重新開啟／其他類型的紀錄不動）
            del history[i]
        data["editHistory"] = history

        now = save_quotation_json(conn, quote_no, data, updated_at=now)
        conn.commit()
        conn.close()
        cname = row["customer_name"] or ""
        spawn_bg_thread(_backup_quotation, args=(quote_no,))
        _audit(_tok(authorization), 'quotation.settlement', 'quotation', quote_no,
               f"{quote_no}（{cname}）成本精算{'完結' if is_finalized else '更新'}",
               {"rev": settle_rev, **({"reason": reopen_reason, "from": "finalized"} if was_final else {})})
        if is_finalized:
            notify_settlement_finalized(
                quote_no, cname,
                user.get("display_name") or user["username"],
            )
        out = {"ok": True, "updated_at": now}
        if is_finalized:
            out["summary"] = body.settlement.get("summary")      # 38（稽核 S-4）：回傳伺服器覆蓋後凍結的 summary，前端據此更新畫面（不再停在頁面自己算的版本）
        return out


