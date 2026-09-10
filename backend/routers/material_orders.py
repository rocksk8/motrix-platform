"""叫料（材料訂購）管理端點 — 案件財務應付子項目（2026-09-10）。"""
import json
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db
from helpers import (
    _require_user, _audit, save_quotation_json, user_has_module,
)

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
    - 用戶有報價單寫入權限
    - 案件未結案（deal_tag ≠ '已結案'）

    流程：
    - 完全覆蓋既有 caseRecord.materialOrders（無增量更新）
    - 驗證每筆叫料的 paidStatus 邏輯
    - 保存到 data_json，同步 updated_at

    2026-09-10：新增功能，支持已付/待付區分供應商催款。
    """
    user = _require_user(authorization)
    conn = get_db()

    try:
        # 1. 檢查報價單存在 + 寫入權限
        q = conn.execute(
            "SELECT data_json FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")

        data = json.loads(q["data_json"] or "{}")

        # 2. 權限檢查：只有 admin+ 或有報價單編輯模組的使用者可以修改叫料
        if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "project_manage"):
            raise HTTPException(403, "權限不足：只有管理員或專案經理可以修改叫料")

        # 3. 檢查案件狀態
        deal_tag = data.get("deal_tag", "")
        if deal_tag == "已結案":
            raise HTTPException(400, "已結案案件無法修改叫料")

        # 4. 驗證叫料邏輯
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

        # 5. 保存到 data_json
        if not data.get("caseRecord"):
            data["caseRecord"] = {}

        data["caseRecord"]["materialOrders"] = [mo.dict() for mo in body.materialOrders]

        # 6. 寫入 DB
        save_quotation_json(
            conn, quote_no, data, user["id"],
            f"更新叫料清單（{len(body.materialOrders)} 項）"
        )

        # 7. 稽核記錄
        _audit(conn, f"quotations/{quote_no}", "material_orders_update",
               user["id"], f"新增/更新 {len(body.materialOrders)} 筆叫料")

        return {
            "status": "ok",
            "quoteNo": quote_no,
            "materialOrdersCount": len(body.materialOrders)
        }

    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/material-orders")
def get_material_orders(quote_no: str, authorization: str = Header(None)):
    """取得案件的叫料清單。"""
    user = _require_user(authorization)
    conn = get_db()

    try:
        q = conn.execute(
            "SELECT data_json FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")

        data = json.loads(q["data_json"] or "{}")
        orders = data.get("caseRecord", {}).get("materialOrders", [])

        return {
            "quoteNo": quote_no,
            "materialOrders": orders,
            "totalAmount": sum(o["totalPrice"] for o in orders) if orders else 0,
            "paidAmount": sum(o["paidAmount"] for o in orders if o.get("paidAmount")) if orders else 0,
        }

    finally:
        conn.close()
