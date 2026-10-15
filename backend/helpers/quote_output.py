# -*- coding: utf-8 -*-
"""報價單輸出的設定使用端（T63 Q0）：被管理者隱藏的報價條件欄位，PDF／預覽要不要照印。

[單位] helper:quote_output    [層] L1    [穩定度] 實驗
[公開介面] TERMS, hidden_terms
[不變式] ①設定 `quote_output.hidden_terms_pdf_mode`＝0（預設）⇒ 回空集合，**完全不讀版面**（今天的行為）；②任何讀取失敗 ⇒ 空集合（照印＝最嚴）；
    ③只看公司層級的版面（不分角色）：PDF 是給客戶的同一份文件，不能因為誰按下列印而不同；④只決定『印不印』，不刪除、不改任何已存的內容。
設計：docs/platform/plans/T63-Q0-SETTINGS-SPEC.md。
"""
import logging

logger = logging.getLogger(__name__)

#: 報價單 PDF「五、報價條件」區的五個欄位（鍵＝報價單物件的屬性名，也是版面可自訂點的欄位鍵）
TERMS = ("paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales")
_ENTITY = "qterms"


def hidden_terms(conn=None) -> frozenset:
    """目前應該從報價單 PDF／預覽拿掉的條件欄位鍵。永不丟例外。"""
    try:
        from helpers import settings_registry as SR
        if int(SR.get("quote_output", "hidden_terms_pdf_mode", conn=conn) or 0) != 1:
            return frozenset()
    except Exception:                                                                    # noqa: BLE001 — 讀不到設定 ⇒ 照印
        return frozenset()
    own = conn is None
    try:
        from core import catalog
        c = conn
        if own:
            from db import get_db
            c = get_db()
        try:
            ops = catalog.effective_layout_ops(c, "case", None)["ops"]
        finally:
            if own:
                c.close()
        ids = {p["id"]: p["field"] for p in catalog.layout_points("case")
               if p.get("kind") == "field" and p.get("entity") == _ENTITY and p.get("field") in TERMS}
        hidden = set()
        for o in ops:                                                  # 依序套用：後面的 show 會蓋掉前面的 hide
            f = ids.get((o or {}).get("target")) if isinstance(o, dict) else None
            if f and o.get("op") == "hide":
                hidden.add(f)
            elif f and o.get("op") == "show":
                hidden.discard(f)
        return frozenset(hidden)
    except Exception:                                                                    # noqa: BLE001
        logger.warning("quote_output: 讀版面失敗，條件照印", exc_info=True)
        return frozenset()
