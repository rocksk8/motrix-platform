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
                    "indirectTravel", "indirectWarranty", "indirectOther", "tot", "overheadPct")
#: 款項期別（invoicePretax／invoiceTax：發票記載的未稅與稅額，AC1 由 hichan-bf 新增）
PAYMENT_MONEY_KEYS = ("amount", "pct", "actualAmount", "feeAmount", "feeNote", "invoicePretax", "invoiceTax")
#: 叫料品項
MATERIAL_ORDER_MONEY_KEYS = ("unitPrice", "totalPrice", "paidAmount", "totalAmount")
#: 修改紀錄裡的金額欄位（modules/case/api/quotations.py::_TRACKED_QUOTE_FIELDS 的顯示名稱）
HISTORY_MONEY_FIELDS = {"含稅總額", "未稅金額", "直接毛利率", "淨利率", "管銷分攤比率"}
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


def quote_money_visible(user: dict) -> bool:
    """報價單層級資料（品項單價／成本／毛利、總額、報價單編輯）的可見／可編輯條件（第42班，使用者裁示「拆開」）：
    superadmin／admin／sales／財務角色（＝舊 `can_see_financial` 的角色集合）。業務與管理員維持**編輯報價單、看報價總額**；
    財務角色專屬的是**精算、收款／付款（款項期別）、財務總覽、報表金額、出納**等——那些仍走 `money_visible`／`can_see_financial`
    （只有 superadmin 與財務角色）。"""
    from helpers.auth import finance_duty_person            # R2 D5：寫死 "finance" 的點改走縫（off／shadow ＝ 原判斷）
    return (user or {}).get("role") in ("superadmin", "admin", "sales") or finance_duty_person(user)


def material_money_visible(user: dict) -> bool:
    """叫料體系（材料申請）的金額可見／可操作條件（第42班，Q6）：superadmin／admin／sales／財務角色（＝舊 `can_see_financial` 的角色集合，材料申請行為不變）。

    財務金額可視（`money_visible`）改成只有財務角色與 superadmin 之後，admin 會連材料申請的日常作業
    （建立／送審／到貨確認）都被擋——但那屬一般管理（使用者已同意的預設 Q6）。所以材料申請自己用這一支：
    維持 admin 可作業，而「取消已核准的材料申請」「改成本單價」仍另外要求財務角色（material_approval／material_guard）。"""
    from helpers.auth import finance_duty_person            # R2 D5：寫死 "finance" 的點改走縫（off／shadow ＝ 原判斷）
    return (user or {}).get("role") in ("superadmin", "admin", "sales") or finance_duty_person(user)


class PaymentStructureChange(Exception):
    """遮蔽帳號新增、刪除或重排款項期別（CM13 D2：不允許）。"""


def strip_history_reasons(history):
    """就地拿掉修改紀錄（editHistory）裡的自由文字理由（例如重新開啟已完結精算的理由，可能寫到金額或對帳細節）；誰／何時／事件保留。
    給沒有財務檢視（`money_visible()` 為否）的帳號用。回傳同一個 list。"""
    for h in history or []:
        if isinstance(h, dict):
            h.pop("reason", None)
    return history


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


def mask_case_record(cr: dict, keep_orders: bool = False) -> dict:
    """就地遮蔽 caseRecord 裡的金額（款項期別、叫料品項）。回傳同一個物件。
    `keep_orders=True`（第42班，Q6）：叫料品項的金額不遮（材料申請日常作業的操作者，見 `material_money_visible`）。"""
    if not isinstance(cr, dict):
        return cr
    pay = cr.get("payment")
    if isinstance(pay, dict):
        for it in pay.get("items") or []:
            _drop(it, PAYMENT_MONEY_KEYS)
        if _old_shape_received(pay):
            pay.pop("received", None)
    for mo in ([] if keep_orders else cr.get("materialOrders") or []):
        _drop(mo, MATERIAL_ORDER_MONEY_KEYS)
    return cr


def mask_quotation_data(data: dict, keep_orders: bool = False, keep_quote: bool = False) -> dict:
    """就地遮蔽整份 data_json。回傳同一個物件。`keep_orders` 見 `mask_case_record`。
    `keep_quote=True`（第42班）：報價單層級的金額（品項單價／成本／毛利、總額、修改紀錄、核准原因）不遮——
    業務／管理員維持編輯報價單；精算、款項期別（收款／付款）、叫料金額（依 keep_orders）照遮。"""
    if not isinstance(data, dict):
        return data
    if not keep_quote:
        for it in data.get("items") or []:
            _drop(it, ITEM_MONEY_KEYS)
        _drop(data, QUOTE_MONEY_KEYS)
    st = data.get("settlement")
    if isinstance(st, dict):
        # 精算狀態是清單與按鈕要用的，金額全部不回
        data["settlement"] = {"status": st.get("status")} if "status" in st else {}
    appr = data.get("approval")
    if not keep_quote and isinstance(appr, dict) and isinstance(appr.get("reasons"), list):
        appr["reasons"] = [MASKED_REASON if isinstance(r, str) and any(m in r for m in _REASON_MONEY_MARKS) else r
                           for r in appr["reasons"]]
    if not keep_quote:
        strip_history_reasons(data.get("editHistory"))
        for h in data.get("editHistory") or []:
            for c in (h.get("changes") or []) if isinstance(h, dict) else []:
                if isinstance(c, dict) and c.get("field") in HISTORY_MONEY_FIELDS:
                    c["from"] = "—"
                    c["to"] = "—"
    mask_case_record(data.get("caseRecord"), keep_orders=keep_orders)
    data["moneyMasked"] = True
    return data


def _id_list(items):
    return [it.get("id") if isinstance(it, dict) else None for it in items or []]


def restore_case_record(new_cr: dict, db_cr: dict, keep_orders: bool = False) -> dict:
    """遮蔽帳號送回的 caseRecord：以資料庫現值補回被遮蔽的金額鍵。

    - 款項期別：期別的 id 與順序必須與資料庫相同（新增／刪除／重排 ⇒ PaymentStructureChange）；
      每一期的金額鍵一律取資料庫的值（送回來的即使有值也不採用——他看不到原值，不可能是有意改的）。
      資料庫還沒有款項分段（頁面替它補的預設期別）⇒ 這一段不寫入，維持沒有。
    - 叫料品項：一律維持資料庫的值（案件頁不經由這條路改叫料，專屬端點另有規則）；`keep_orders=True`（第42班 Q6，材料申請操作者）
      則不覆蓋，交給叫料審核寫入閘（material_guard）處理。
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
    if keep_orders:
        pass
    elif "materialOrders" in db_cr:
        out["materialOrders"] = copy.deepcopy(db_cr["materialOrders"])
    else:
        out.pop("materialOrders", None)
    return out
