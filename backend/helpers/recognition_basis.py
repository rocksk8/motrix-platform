"""權責／現金口徑的純標籤（L1；2026-09-26 自 M01 modules/case/recognition.py 下沉，M01-PLAN §3-6）。

為什麼在 L1：M08 營運報表要解析 `basis` 參數、印口徑說明——M01 不在時也要（那時權責口徑的收入沒有資料來源，
要說出原因，而不是 400）。本檔不讀表、不 import M01。計算（認列、支出歸月、待補登）仍在 M01，經 `case.recognition`。
"""
from fastapi import HTTPException

BASES = ("accrual", "cash")

#: 報表頂端的口徑說明（使用者：「數字不同的部分，在營運報表內可註明並且標註」）
BASIS_NOTES = {
    "accrual": ("本報表預設採權責口徑：收入依案件階段完成月認列（未稅），支出依廠商發票月認列"
                "（拆得出稅額的用未稅，拆不出的用全額並標示）；叫料已納入支出。"
                "與舊版報表（收入依收款日、支出依派工日且未含叫料）數字不同屬正常。"
                "尚未補登發票日期或階段比例的單據，會暫用其他日期並列在下方「待補登」清單。"),
    "cash":    ("現金口徑：收入依實際收款日（含稅），支出依實際付款日（含稅）："
                "派工以匯款申請的已匯款日為準，叫料以付款日為準，額外支出以付款日為準"
                "（未登錄者暫用憑證日並標示）。"),
}


def normalize_basis(v):
    v = (v or "accrual").strip()
    if v not in BASES:
        raise HTTPException(400, "basis 只能是 accrual（權責）或 cash（現金）")
    return v
