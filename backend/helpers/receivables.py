"""L1 薄殼（淘汰中）：收款明細與銷項發票清單——**資料在 M05 應收應付**，這裡只轉呼叫它的 provider。

2026-09-26 M05 搬遷（主持裁示 (a)）：本檔原為 M08 搬遷 ③ 下沉的中繼（ROADMAP A8b），函式本體已收回
`modules/arap/receivables.py`。直接刪除＝L1 刪除公開名稱 ⇒ 要升 CORE 主版號（牽動全部模組的 core 範圍），
所以保留同名函式、改為轉呼叫 provider，**下一個主版號刪除**（ROADMAP、core/CHANGELOG 已登記）：
`collect_income_items`、`collect_tax_invoices`、`round_half_up_invoice`。新程式不要用本檔，直接取 provider。

契約（守門 tests/platform/test_receivables_shim.py）：只准轉呼叫 provider——不 import 任何 `modules.*`、不讀表、沒有 SQL。
M05 不在時（比照 M08 報表的處理）：
- `collect_income_items` ⇒ `[]`（呼叫端要自己說明「現金口徑收入沒有資料來源」，M08 用 `incomeNotice`）
- `collect_tax_invoices` ⇒ 404「應收應付模組未安裝…」（銷項發票清單沒有資料來源，不回空表假裝沒有發票）
"""
from typing import Optional

from fastapi import HTTPException

from core import registry
from helpers.legal_params import round_half_up

__all__ = ["collect_income_items", "collect_tax_invoices", "round_half_up_invoice", "RECEIVABLES_MISSING"]

RECEIVABLES_MISSING = "應收應付模組未安裝：收款與銷項發票資料不提供"


def round_half_up_invoice(n) -> int:
    """四捨五入到元（轉呼叫 L1 `helpers.legal_params.round_half_up`，金額捨入唯一來源）。"""
    return round_half_up(n)


def collect_tax_invoices(year: Optional[int] = None, month: Optional[int] = None) -> list:
    """銷項發票清單 ⇒ M05 provider `receivables.tax_invoices`；M05 不在 ⇒ 404。"""
    p = registry.single_provider("receivables.tax_invoices")
    if p is None:
        raise HTTPException(404, RECEIVABLES_MISSING)
    return p(year, month)


def collect_income_items(d0: str, d1: str, department_id: Optional[int] = None) -> list:
    """收款明細 ⇒ M05 provider `receivables.income_items`；M05 不在 ⇒ `[]`。"""
    p = registry.single_provider("receivables.income_items")
    if p is None:
        return []
    return p(d0, d1, department_id)
