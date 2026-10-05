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
from helpers.auth import has_finance_access
from helpers.case_access import require_case, require_case_money   # M01-O1：逐案拒絕＝查無（同一個 404）；money 版＝財務角色不受擁有者限制（第42班）
from helpers.auth import has_finance_access, has_cashier_access  # noqa: E402  第42班：財務／出納只認「財務」角色與 superadmin
from helpers import row_access
from core.txn import begin_write
from helpers import (
    _require_user, _tok, _audit, user_has_module,
)
# M01 自己的名稱：CA-O4 起 helpers 不再再匯出（`import helpers` 不載入 M01）
from modules.case.quotations import SQL_DEAL_TAG, save_quotation_json  # noqa: E402
from helpers.financial_mask import MATERIAL_ORDER_MONEY_KEYS, money_visible, material_money_visible
from modules.case.recognition import normalize_date  # `AC2`
from modules.case import material_approval as MA   # 叫料審核（31-C）
from modules.case import material_guard as MG

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
    invoiceDate: Optional[str] = ""  # `AC2`：廠商發票日期（''＝未登錄；權責口徑依它歸月）
    supplierId: Optional[int] = None  # 31-C：供應商主檔 id（叫料審核的實質欄位；匯款申請的收款對象）。整份覆寫的端點：沒帶就會被抹掉，前端要原樣帶回
    quoteItemId: Optional[str] = None   # 32-S4：連到的報價單品項 id（沒帶／空 ⇒ 存檔時略過，舊單形狀不變）
    poDocCode: Optional[str] = None     # 32-S4：連到的採購單單號
    poLine: Optional[int] = None        # 32-S4：採購單明細列序（1 起算）
    overPlanReason: Optional[str] = None  # 32-S4：超出報價計畫量的原因


class MaterialOrderUpdateIn(BaseModel):
    """叫料更新請求。"""
    materialOrders: List[MaterialOrder]


_LINK_KEYS = ("quoteItemId", "poDocCode", "poLine", "overPlanReason")


def _dump_order(mo):
    """model_dump；連結鍵（S4）空值一律不寫入，沒用連結的舊單存檔形狀與以前完全相同。"""
    d = mo.model_dump()
    for k in _LINK_KEYS:
        if d.get(k) in (None, "", 0):
            d.pop(k, None)
    return d


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
        begin_write(conn)   # lost update：讀 data_json 前先拿寫鎖（modules.case.quotations.begin_write）
        q = conn.execute(
            f"SELECT data_json, sales_person_id, sales_person, assigned_user_ids, "
            f"{SQL_DEAL_TAG} AS deal_tag FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")

        # 2. 擁有者檢查：非 admin+ 不能碰別的業務的案件（quote_no 可列舉）
        require_case_money(user, q, quote_no)

        data = json.loads(q["data_json"] or "{}")

        # 3. 權限檢查：只有 admin+ 或有報價單編輯模組的使用者可以修改叫料
        if user["role"] not in ("superadmin", "admin", "finance") and not user_has_module(user, "project_manage"):
            raise HTTPException(403, "權限不足：只有管理員、財務角色或專案經理可以修改材料申請")
        if not material_money_visible(user):          # 第42班（Q6）：材料申請日常作業維持 admin
            # CM13（2026-09-24）：這支整份取代叫料清單且單價／小計為必填——看不到金額的人
            # 送不出正確的值，照收就是用猜的數字蓋掉真正的價格（比照 D1 報價單 403）。
            raise HTTPException(403, "此帳號沒有財務檢視權限，不可修改材料申請清單")

        # 4. 檢查案件狀態
        if (q["deal_tag"] or "") == "已結案":
            raise HTTPException(400, "已結案案件無法修改材料申請")

        # 5. 驗證叫料邏輯
        prior_link = {str(o.get("itemId")): str(o.get("poDocCode") or "") for o in ((data.get("caseRecord") or {}).get("materialOrders") or []) if isinstance(o, dict)}
        for mo in body.materialOrders:
            if (mo.poDocCode or "").strip() and (mo.paidAmount > 0 or mo.paidStatus != "pending") and prior_link.get(str(mo.itemId), "") != mo.poDocCode.strip():
                raise HTTPException(400, f"「{mo.itemName}」已有付款紀錄，不可再對應採購單（付款已記在這筆材料申請上，再對應會重複計算）")
            if mo.quantity < 0 or mo.unitPrice < 0 or mo.totalPrice < 0:
                raise HTTPException(400, f"數量、單價、小計不能為負 ({mo.itemName})")

            # 小計驗證（允許浮點數誤差 0.01）
            expected_total = mo.quantity * mo.unitPrice
            if abs(mo.totalPrice - expected_total) > 0.01:
                raise HTTPException(400, f"{mo.itemName} 小計計算錯誤（{mo.quantity}×{mo.unitPrice}≠{mo.totalPrice}）")

            # `AC2`：發票日期 ''＝未登錄；有填就必須是真實日期
            mo.invoiceDate = normalize_date(mo.invoiceDate, "發票日期（%s）" % mo.itemName)

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

        data["caseRecord"]["materialOrders"] = [_dump_order(mo) for mo in body.materialOrders]
        # 叫料審核（31-C）：整份覆蓋也要過閘（新列建審核單、實質欄位變更依審核狀態處理、被拒的項目維持原值並逐項回報）
        rejected = MG.enforce(conn, quote_no, data, actor=user)

        # 7. 寫入 DB —— save_quotation_json() 只組 UPDATE、不 commit，呼叫端
        #    必須自己 commit（比照 modules/case/api/quotations.py:1310 附近既有寫法）。
        #    第 4 個位置參數是 status 不是 user_id，這裡刻意只傳三個參數，
        #    不要動到報價單本身的 status 欄位。
        save_quotation_json(conn, quote_no, data, actor=user)
        conn.commit()

        # 8. 稽核記錄（第一個參數是 token，不是連線）
        _audit(_tok(authorization), 'material_orders.update', 'quotation', quote_no,
               f"更新材料申請清單（{len(body.materialOrders)} 項）" + (f"；{len(rejected)} 項被審核規則擋下" if rejected else ""))

        out = {
            "status": "ok",
            "quoteNo": quote_no,
            "materialOrdersCount": len(data["caseRecord"]["materialOrders"])
        }
        if rejected:
            out["rejected"] = rejected      # 只拒有問題的項目，其餘已存（itemId／field／code／message）
        return out

    finally:
        conn.close()


@router.patch("/api/quotations/{quote_no}/material-orders/{item_id}/invoice-date")
def set_material_order_invoice_date(quote_no: str, item_id: str, body: dict = Body(...),
                                    authorization: str = Header(None)):
    """`AC2`：只登一筆叫料的廠商發票日期（''＝清除）。hichan-0a 裁示：

    - **任何案件狀態都可以登（含已結案）**：結案後才拿到的發票是常態，而整份覆寫的
      PATCH 在已結案時 400——沒有這一支，那張發票會永遠留在待補登清單。
    - 不動任何金額 ⇒ 不受 CM13 金額遮蔽的限制；只改這一鍵，其他欄位原封不動。
    權限：擁有者檢查＋（admin+、專案經理、出納、財務）。
    """
    user = _require_user(authorization)
    if not has_finance_access(user):          # 第42班（使用者裁示）：材料申請發票日＝財務角色／superadmin
        raise HTTPException(403, "權限不足：只有財務角色可以登錄材料申請發票日期")
    inv = normalize_date((body or {}).get("invoiceDate"), "發票日期")
    conn = get_db()
    try:
        begin_write(conn)   # lost update：讀 data_json 前先拿寫鎖
        q = conn.execute(
            "SELECT data_json, sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?",
            (quote_no,)).fetchone()
        if not q:
            raise HTTPException(404, f"報價單 {quote_no} 不存在")
        require_case_money(user, q, quote_no)
        data = json.loads(q["data_json"] or "{}")
        orders = (data.get("caseRecord") or {}).get("materialOrders") or []
        hit = [mo for mo in orders if isinstance(mo, dict) and str(mo.get("itemId")) == item_id]
        if not hit:
            raise HTTPException(404, "找不到這筆材料申請（請先儲存材料申請清單）")
        if MA.status_of(conn, quote_no, item_id) in MA.IN_FLIGHT:
            raise HTTPException(409, "審核中的材料申請不可改發票日期（請先撤回或等審核完成）")
        before = hit[0].get("invoiceDate") or ""
        hit[0]["invoiceDate"] = inv
        save_quotation_json(conn, quote_no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.invoice_date", "quotation", quote_no,
           "材料申請「%s」發票日期：%s → %s" % (hit[0].get("itemName") or item_id, before or "（未登錄）", inv or "（未登錄）"))
    return {"ok": True, "invoiceDate": inv}


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
        require_case_money(user, q, quote_no)

        data = json.loads(q["data_json"] or "{}")
        orders = data.get("caseRecord", {}).get("materialOrders", [])
        if not material_money_visible(user):
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
