"""案件金額欄位遮蔽（CM13，2026-09-24 使用者裁示「要，後端移除金額欄位」）。

沒有 `helpers/auth.py::can_see_financial()` 的帳號，後端不回金額、毛利、單價、成本。
清單欄位換成 None（不是 0：0 是「金額為零」，None 才是「看不到」）；data_json 裡的
金額鍵直接拿掉。都加 `moneyMasked: True` 讓畫面顯示「—」。

⚠ 回寫是這一項最大的風險：遮蔽帳號送回來的資料本來就沒有那些鍵，照單全收就是
「用空值蓋掉真正的金額」。`restore_case_record()` 以資料庫現值補回。
純函式，呼叫端決定要不要套。
"""
import copy

#: quotations 表上的金額欄位（清單、結案檢核、單筆 GET 的頂層）
QUOTATION_MONEY_COLS = ("total", "pretax", "direct_margin_pct", "net_margin_pct")

#: 報價品項
ITEM_MONEY_KEYS = ("cost", "margin", "unitPrice", "amount")
#: 報價單頂層
QUOTE_MONEY_KEYS = ("discount", "freight", "indirectLogistics", "indirectInstallation",
                    "indirectTravel", "indirectWarranty", "indirectOther", "tot")
#: 款項期別（invoicePretax／invoiceTax：發票記載的未稅與稅額，AC1 由 hichan-bf 新增）
PAYMENT_MONEY_KEYS = ("amount", "pct", "actualAmount", "feeAmount", "feeNote", "invoicePretax", "invoiceTax")
#: 叫料品項
MATERIAL_ORDER_MONEY_KEYS = ("unitPrice", "totalPrice", "paidAmount", "totalAmount")
#: 修改紀錄裡的金額欄位（modules/case/api/quotations.py::_TRACKED_QUOTE_FIELDS 的顯示名稱）
HISTORY_MONEY_FIELDS = {"含稅總額", "未稅金額", "直接毛利率", "淨利率"}
#: 需審核原因裡帶金額或毛利的（modules/case/quote_terms.py::compute_approval_reasons）
_REASON_MONEY_MARKS = ("毛利", "NT$", "折讓")
MASKED_REASON = "（涉及金額，無財務檢視權限）"


def money_visible(user: dict) -> bool:
    """CM13 的遮蔽條件：can_see_financial() 或持有 cashier 模組（2026-09-24 使用者裁示 A）。

    出納頁（routers/cashier.py）本來就對 cashier 模組回每期金額；只在案件頁遮蔽他擋不住
    任何資訊，只會擋住他在案件頁登錄收款。不改 can_see_financial() 本身——財務總覽等
    其他用到它的端點維持原規則。
    """
    from helpers.auth import can_see_financial, user_has_module
    return can_see_financial(user) or user_has_module(user, "cashier")


class PaymentStructureChange(Exception):
    """遮蔽帳號新增、刪除或重排款項期別（CM13 D2：不允許）。"""


def mask_row(row: dict, cols=QUOTATION_MONEY_COLS) -> dict:
    """清單列：金額欄位回 None。只改 row 裡確實存在的鍵。"""
    for k in cols:
        if k in row:
            row[k] = None
    row["moneyMasked"] = True
    return row


def _drop(d, keys):
    if isinstance(d, dict):
        for k in keys:
            d.pop(k, None)


def _old_shape_received(pay) -> bool:
    """quotation-form 早期的 caseRecord.payment 形狀：received 是金額（數字）不是布林。"""
    v = pay.get("received") if isinstance(pay, dict) else None
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def mask_case_record(cr: dict) -> dict:
    """就地遮蔽 caseRecord 裡的金額（款項期別、叫料品項）。回傳同一個物件。"""
    if not isinstance(cr, dict):
        return cr
    pay = cr.get("payment")
    if isinstance(pay, dict):
        for it in pay.get("items") or []:
            _drop(it, PAYMENT_MONEY_KEYS)
        if _old_shape_received(pay):
            pay.pop("received", None)
    for mo in cr.get("materialOrders") or []:
        _drop(mo, MATERIAL_ORDER_MONEY_KEYS)
    return cr


def mask_quotation_data(data: dict) -> dict:
    """就地遮蔽整份 data_json。回傳同一個物件。"""
    if not isinstance(data, dict):
        return data
    for it in data.get("items") or []:
        _drop(it, ITEM_MONEY_KEYS)
    _drop(data, QUOTE_MONEY_KEYS)
    st = data.get("settlement")
    if isinstance(st, dict):
        # 精算狀態是清單與按鈕要用的，金額全部不回
        data["settlement"] = {"status": st.get("status")} if "status" in st else {}
    appr = data.get("approval")
    if isinstance(appr, dict) and isinstance(appr.get("reasons"), list):
        appr["reasons"] = [MASKED_REASON if isinstance(r, str) and any(m in r for m in _REASON_MONEY_MARKS) else r
                           for r in appr["reasons"]]
    for h in data.get("editHistory") or []:
        for c in (h.get("changes") or []) if isinstance(h, dict) else []:
            if isinstance(c, dict) and c.get("field") in HISTORY_MONEY_FIELDS:
                c["from"] = "—"
                c["to"] = "—"
    mask_case_record(data.get("caseRecord"))
    data["moneyMasked"] = True
    return data


def _id_list(items):
    return [it.get("id") if isinstance(it, dict) else None for it in items or []]


def restore_case_record(new_cr: dict, db_cr: dict) -> dict:
    """遮蔽帳號送回的 caseRecord：以資料庫現值補回被遮蔽的金額鍵。

    - 款項期別：期別的 id 與順序必須與資料庫相同（新增／刪除／重排 ⇒ PaymentStructureChange）；
      每一期的金額鍵一律取資料庫的值（送回來的即使有值也不採用——他看不到原值，不可能是有意改的）。
      資料庫還沒有款項分段（頁面替它補的預設期別）⇒ 這一段不寫入，維持沒有。
    - 叫料品項：一律維持資料庫的值（案件頁不經由這條路改叫料，專屬端點另有規則）。
    回傳新的 dict，不改動傳入物件。
    """
    out = copy.deepcopy(new_cr or {})
    db_cr = db_cr or {}
    db_pay = db_cr.get("payment")
    if "payment" in out:
        if not isinstance(db_pay, dict):
            out.pop("payment", None)
        else:
            new_pay = out.get("payment") if isinstance(out.get("payment"), dict) else {}
            db_items = db_pay.get("items") or []
            new_items = new_pay.get("items") or []
            if _id_list(new_items) != _id_list(db_items):
                raise PaymentStructureChange()
            for n, o in zip(new_items, db_items):
                for k in PAYMENT_MONEY_KEYS:
                    if k in o:
                        n[k] = copy.deepcopy(o[k])
                    else:
                        n.pop(k, None)
            if _old_shape_received(db_pay):
                new_pay["received"] = db_pay["received"]
            out["payment"] = new_pay
    if "materialOrders" in db_cr:
        out["materialOrders"] = copy.deepcopy(db_cr["materialOrders"])
    else:
        out.pop("materialOrders", None)
    return out
