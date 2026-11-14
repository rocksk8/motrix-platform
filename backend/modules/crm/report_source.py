# -*- coding: utf-8 -*-
"""業務開發模組的自訂報表來源登記（T87 B2 S0b）：商機（dev_case）。

[單位] crm:report_source    [層] M02    [穩定度] 實驗
[公開介面] register
[不變式] ①進入條件＝`GET /api/dev-cases` 的 `_require_dev`：admin／superadmin，或持有 `dev_crm` 模組（來源登記 `modules=["dev_crm"]`＋`adminPass`）。
    ②列範圍＝`row_access` 的 `dev_case`（scope=owner；admin 直通，與清單 `_is_admin` 同）；軟刪除＝`is_deleted`（清單固定帶 `is_deleted = 0`）。
    ③預估金額走欄位目錄 `dev_case.expected_amount`（天花板 `financial_view`＝`auth.can_see_financial`，與 CRM 頁面 `expectedAmountVisible` 同一條）；不受報價單金額欄範圍設定（D7）影響。
    ④商機的「業務」「企劃」是 JSON 成員陣列：v1 不開放分組、不登記為欄位（分組會讓一筆被算進多組）；「我是成員」快捷不在 v1（清單端點沒有此篩選，沒有可對照的列集合）。
    ⑤階段選項取自 CRM 的 `_STATUS_OPTIONS`（由 api 傳進來，同一份），不在這裡另寫一份。
    ⑥`execute` 由 report_runner 切片補上；沒有 `execute` 的來源不會列給使用者。
[契約題] backend/tests/platform/test_report_catalog_t87.py
"""
from helpers import report_catalog as _RC

OWNER = "crm"


def _f(fid, label, typ, **kw):
    d = {"id": fid, "label": label, "type": typ, "kind": "column", "column": fid, "select": True, "filter": False,
         "group": False, "aggregate": (), "sort": False}
    d.update(kw)
    return d


def register(status_options) -> list:
    """由 `modules/crm/api.py` 在 `_STATUS_OPTIONS` 定義之後呼叫。回傳問題清單（空＝已登記）。"""
    opts = tuple((s, s) for s in status_options)
    fields = [
        _f("case_name", "案件名稱", "text", filter=True, sort=True),
        _f("customer_name", "客戶", "text", filter=True, group=True, sort=True),
        _f("status", "階段", "enum", filter=True, group=True, enum=opts),
        _f("referrer", "介紹人", "text", filter=True, group=True),
        _f("expected_close_date", "預計成交日", "date", filter=True, group=True, sort=True, bucket=("month", "quarter")),
        _f("created_at", "建立日", "date", filter=True, sort=True),
        _f("updated_at", "最後更新", "date", filter=True, sort=True),
        _f("expected_amount", "預估金額", "money", catalogId="dev_case.expected_amount", filter=True, sort=True,
           aggregate=("count", "sum", "avg", "min", "max")),
    ]
    return _RC.register_source("dev_case", OWNER, {
        "label": "商機", "table": "dev_cases", "modules": ["dev_crm"], "adminPass": True,
        "rowAccess": {"kind": "dev_case", "scope": "owner"}, "softDelete": "is_deleted",
        "exprs": (), "fields": fields,
        "defaults": {"columns": ["case_name", "customer_name", "status", "expected_close_date", "expected_amount"],
                     "sort": {"field": "updated_at", "dir": "desc"}},
    })
