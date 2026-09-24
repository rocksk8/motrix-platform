"""叫料（材料訂購）管理端點 — 案件財務應付子項目（2026-09-10）。

前端於 2026-09-11 補上：案件管理「財務」分頁的 `#fin-material-orders` 區塊
（`frontend/pages/case-management.html`）＋ `case-management.js` 的
`loadMaterialOrders()`／`moSave()`／`moRecalc()`。端對端測試
`tests/test_e2e_material_orders_2026_09_11.py`（2 題，真實瀏覽器）釘住整條路。

> **這支端點曾經整整一天是「後端好好的、但沒有任何入口」**：2026-09-10 修好
> 四個缺陷、7 題 API 測試全綠，但全 repo 沒有任何前端呼叫得到它，見
> `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` §E-1。純 API 測試對這種缺陷完全
> 無感——這是本專案第二次踩到（第一次是 WebAuthn 設定頁沒部署、端點回 503
> 卻沒有地方能填 RP ID）。

資料落點：`quotations.data_json` 的 `caseRecord.materialOrders`（陣列），
無 schema 異動、沒有獨立資料表——所以「叫料」查不到專屬 migration 是正常的。
"""
import json
from typing import List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db
from helpers import (
    _require_user, _tok, _audit, save_quotation_json, user_has_module,
    _check_quotation_owner, SQL_DEAL_TAG,
)
from helpers.financial_mask import MATERIAL_ORDER_MONEY_KEYS, money_visible

router = APIRouter()


class MaterialOrder(BaseModel):
    """叫料項目結構。"""
    itemId: str                    # UUID
    itemName: str                  # 項目名稱（如「交換器」）
    quantity: float                # 數量
    unit: str                      # 單位（個、套、台等）
    unitPrice: float               # 單價
    totalPrice: float              # 小計 = 數量 × 單價
    paidStatus: str                # 'pending'|'partial'|'paid'
    paidAmount: float              # 已付金額
    paidDate: Optional[str]        # 已付日期（YYYY-MM-DD，paidStatus≠'pending'時）
    notes: Optional[str] = ""      # 備註


class MaterialOrderUpdateIn(BaseModel):
    """叫料更新請求。"""
    materialOrders: List[MaterialOrder]


@router.patch("/api/quotations/{quote_no}/material-orders")
def update_material_orders(quote_no: str,
                           body: MaterialOrderUpdateIn = Body(...),
                           authorization: str = Header(None)):
    """更新案件的叫料清單（案件財務應付子項目）。

    驗證：
    - 用戶有報價單寫入權限，且是這張單的可見範圍內（比照其他單筆端點的 IDOR 防護）
    - 案件未結案（deal_tag ≠ '已結案'）

    流程：
    - 完全覆蓋既有 caseRecord.materialOrders（無增量更新）
    - 驗證每筆叫料的 paidStatus 邏輯
    - 保存到 data_json，同步 updated_at

    2026-09-10：新增功能，支持已付/待付區分供應商催款。
    2026-09-10（同日修復）：初版有四個缺陷，見 §12 同日條目——①漏 conn.commit()
    導致整支端點回 200 但資料庫完全沒寫入②save_quotation_json() 參數錯位，把
    user_id 當成 status、把中文說明當成 updated_at③_audit() 傳錯簽名（第一個
    參數是 token 不是 conn），例外被 audit 內部 try 吞掉、稽核從來沒寫成功
    ④已結案守門讀 data_json 的 'deal_tag'，但那裡的鍵叫 'dealTag'、權威來源
    是資料表欄位，等於守門是死碼。另補上遺漏的擁有者檢查（IDOR）。
    """
    user = _require_user(authorization)
    conn = get_db()

    try:
        # 1. 檢查報價單存在 + 讀出權威的 deal_tag（欄位優先，pre-v6 舊列回退
        #    data_json.dealTag——這正是 SQL_DEAL_TAG 存在的原因，勿改回裸欄位）
        q = conn.execute(
            f"SELECT data_json, sales_person_id, sales_person, assigned_user_ids, "
            f"{SQL_DEAL_TAG} AS deal_tag FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")

        # 2. 擁有者檢查：非 admin+ 不能碰別的業務的案件（quote_no 可列舉）
        _check_quotation_owner(q, user)

        data = json.loads(q["data_json"] or "{}")

        # 3. 權限檢查：只有 admin+ 或有報價單編輯模組的使用者可以修改叫料
        if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "project_manage"):
            raise HTTPException(403, "權限不足：只有管理員或專案經理可以修改叫料")
        if not money_visible(user):
            # CM13（2026-09-24）：這支整份取代叫料清單且單價／小計為必填——看不到金額的人
            # 送不出正確的值，照收就是用猜的數字蓋掉真正的價格（比照 D1 報價單 403）。
            raise HTTPException(403, "此帳號沒有財務檢視權限，不可修改叫料清單")

        # 4. 檢查案件狀態
        if (q["deal_tag"] or "") == "已結案":
            raise HTTPException(400, "已結案案件無法修改叫料")

        # 5. 驗證叫料邏輯
        for mo in body.materialOrders:
            if mo.quantity < 0 or mo.unitPrice < 0 or mo.totalPrice < 0:
                raise HTTPException(400, f"數量、單價、小計不能為負 ({mo.itemName})")

            # 小計驗證（允許浮點數誤差 0.01）
            expected_total = mo.quantity * mo.unitPrice
            if abs(mo.totalPrice - expected_total) > 0.01:
                raise HTTPException(400, f"{mo.itemName} 小計計算錯誤（{mo.quantity}×{mo.unitPrice}≠{mo.totalPrice}）")

            # paidStatus 驗證
            if mo.paidStatus not in ("pending", "partial", "paid"):
                raise HTTPException(400, f"paidStatus 必須是 pending/partial/paid ({mo.itemName})")

            if mo.paidStatus == "pending":
                if mo.paidAmount != 0 or mo.paidDate:
                    raise HTTPException(400, f"待付狀態不能有已付金額或日期 ({mo.itemName})")
            elif mo.paidStatus in ("partial", "paid"):
                if mo.paidAmount < 0 or mo.paidAmount > mo.totalPrice:
                    raise HTTPException(400, f"已付金額必須 0 ~ 小計 ({mo.itemName})")
                if not mo.paidDate:
                    raise HTTPException(400, f"部分/完全已付必須填寫日期 ({mo.itemName})")

        # 6. 保存到 data_json
        if not data.get("caseRecord"):
            data["caseRecord"] = {}

        data["caseRecord"]["materialOrders"] = [mo.model_dump() for mo in body.materialOrders]

        # 7. 寫入 DB —— save_quotation_json() 只組 UPDATE、不 commit，呼叫端
        #    必須自己 commit（比照 routers/quotations.py:1310 附近既有寫法）。
        #    第 4 個位置參數是 status 不是 user_id，這裡刻意只傳三個參數，
        #    不要動到報價單本身的 status 欄位。
        save_quotation_json(conn, quote_no, data)
        conn.commit()

        # 8. 稽核記錄（第一個參數是 token，不是連線）
        _audit(_tok(authorization), 'material_orders.update', 'quotation', quote_no,
               f"更新叫料清單（{len(body.materialOrders)} 項）")

        return {
            "status": "ok",
            "quoteNo": quote_no,
            "materialOrdersCount": len(body.materialOrders)
        }

    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/material-orders")
def get_material_orders(quote_no: str, authorization: str = Header(None)):
    """取得案件的叫料清單。

    權限：登入＋擁有者檢查。2026-09-24（CM13）起 `GET /api/quotations/{quote_no}` 對沒有
    財務檢視權的帳號遮蔽金額，這支同步遮蔽（原本「不另外擋」的理由是兩支拿得到同一份
    資料，只擋一支是假的安全感——現在兩支一起擋）。擁有者檢查不能省。
    """
    user = _require_user(authorization)
    conn = get_db()

    try:
        q = conn.execute(
            "SELECT data_json, sales_person_id, sales_person, assigned_user_ids "
            "FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")
        _check_quotation_owner(q, user)

        data = json.loads(q["data_json"] or "{}")
        orders = data.get("caseRecord", {}).get("materialOrders", [])
        if not money_visible(user):
            # CM13（2026-09-24 使用者裁示）：單價、小計、已付金額不回
            for o in orders:
                for k in MATERIAL_ORDER_MONEY_KEYS:
                    o.pop(k, None)
            return {"quoteNo": quote_no, "materialOrders": orders,
                    "totalAmount": None, "paidAmount": None, "moneyMasked": True}

        # 用 .get() 取值：這份清單是自由格式 JSON，早期資料或人工修過的
        # data_json 不保證每筆都有 totalPrice/paidAmount，直接 o["totalPrice"]
        # 會讓整支查詢端點 500。
        return {
            "quoteNo": quote_no,
            "materialOrders": orders,
            "totalAmount": sum(float(o.get("totalPrice") or 0) for o in orders),
            "paidAmount": sum(float(o.get("paidAmount") or 0) for o in orders),
        }

    finally:
        conn.close()
