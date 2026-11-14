# -*- coding: utf-8 -*-
"""案件模組的自訂報表來源登記（T87 B2 S0b）：報價單（quotation）與案件（case，別名）。

[單位] case:report_source    [層] M01    [穩定度] 實驗
[公開介面] register
[不變式] ①欄位與清單端點 `GET /api/quotations` 同一份定義：成交標記、精算狀態、報價日的運算式引用 `modules.case.quotations` 的**同一個常數**（不複製字串）；
    「我」＝清單的「我負責的」（`_CASE_MINE_SQL`，由 api 傳進來，同一個物件），不是名稱相等。
    ②列範圍＝`row_access` 的 `case`（scope=read，與清單同一條）；`quotations` 資料表沒有軟刪除欄、清單也沒有此條件，所以不登記 softDelete。
    ③**進入條件比清單窄**：清單端點只要求登入（再由列範圍過濾）；報表另外要求持有 `quotation` 或 `case_manage` 其中一個模組（兩頁面各自的權限鍵）。刻意取窄（fail-closed）：能力不取代模組存取。
    ④單據類型（報價單／估價單）是可篩選、可分組的欄位，預設不加條件（與清單預設同列）；選項取自 `helpers.doc_type`。
    ⑤「案件」別名沿用報價單的表、列規則、欄位與執行函式；預設篩選＝成交標記為已成案或已結案（案件頁「案件總覽」的母體），使用者可改，不是強制條件。
    ⑥金額與毛利率欄位走欄位目錄（`quotation.*`）；不可見者的處理（拿掉顯示欄／422 拒絕篩選與排序）在 report_runner。
    ⑦`execute`（擁有模組的執行回呼）只轉呼叫 `report_runner.run_owned`，並限定接受自己的來源（quotation／case）。
    ⑧狀態／成交標記／精算狀態的選項取自**呼叫者看得到的列**（同一套列權限）、只讀實體欄位、每人快取 60 秒；沒有使用者 ⇒ 空。
[契約題] backend/tests/platform/test_report_catalog_t87.py
"""
import time

from helpers import doc_type as _DT
from helpers import report_catalog as _RC
from modules.case.quotations import SQL_DEAL_TAG, SQL_QUOTE_DATE, SQL_SETTLE_STATUS

OWNER = "case"
MODULES = ("quotation", "case_manage")
_MINE_PARAMS = ("id", "display_name", "id", "username", "username", "username")


def _doc_type_options(conn=None):
    return [(k, v) for k, v in _DT.LABELS.items()]


_OPT_TTL = 60.0
_OPT_CACHE = {}                                          # (欄位, 使用者 id) -> (時間, 選項)；每人各一份（列範圍不同）


def _distinct_options(column):
    """列舉值取自**呼叫者看得到的列**（套用與報表同一套列權限）：`SELECT DISTINCT <欄位>`，只讀實體欄位（不碰 `data_json`、不做 JSON 運算），
    每人快取 60 秒、最多 200 個值。沒有使用者 ⇒ 空（fail closed）。回傳 [(值, 白話)]；空字串顯示為「（未填）」。
    舊資料若實體欄位是空、值只在 `data_json` 裡，選項看不到（條件仍可手動輸入該值）。"""
    def _opts(conn, user=None):
        if not user:
            return []
        key = (column, user.get("id"))
        hit = _OPT_CACHE.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < _OPT_TTL:
            return list(hit[1])
        from helpers import row_access
        frag, params = row_access.filter_sql("case", user, scope="read")
        frag = frag.strip()
        where = (frag[4:] if frag.upper().startswith("AND ") else frag) if frag else "1=1"
        rows = conn.execute("SELECT DISTINCT %s AS v FROM quotations WHERE %s ORDER BY 1 LIMIT 200" % (column, where), params).fetchall()
        out = [((r[0] or ""), (r[0] or "（未填）")) for r in rows]
        if len(_OPT_CACHE) > 500:
            _OPT_CACHE.clear()
        _OPT_CACHE[key] = (now, out)
        return list(out)
    _opts.labels_are_values = True
    return _opts


def _execute(plan):
    """擁有模組的執行回呼（D6）：只接受 `compile()` 產生、且來源是自己的計畫；唯讀連線與授權器在 `run_owned`。"""
    from helpers import report_runner as RR
    return RR.run_owned(plan, ("quotation", "case"))


def _f(fid, label, typ, **kw):
    d = {"id": fid, "label": label, "type": typ, "kind": "column", "column": fid, "select": True, "filter": False,
         "group": False, "aggregate": (), "sort": False}
    d.update(kw)
    return d


def register(mine_sql) -> list:
    """由 `modules/case/api/quotations.py` 在 `_CASE_MINE_SQL` 定義之後呼叫（傳入同一個物件）。回傳問題清單（空＝已登記）。"""
    deal_sql, settle_sql = SQL_DEAL_TAG, SQL_SETTLE_STATUS          # 函式內區域變數：每個含 json_extract 的常數只引用一次（棘輪逐次計數）
    fields = [
        _f("quote_no", "報價單號", "text", filter=True, sort=True),
        _f("customer_name", "客戶", "text", filter=True, group=True, sort=True),
        _f("project_name", "案件名稱", "text", filter=True),
        _f("status", "狀態", "enum", filter=True, group=True, enum=_distinct_options("status")),
        _f("sales_person", "業務", "text", filter=True, group=True, isMe=True),
        _f("doc_type", "單據類型", "enum", filter=True, group=True, enum=_doc_type_options),
        _f("quote_date", "報價日", "date", kind="expr", expr=SQL_QUOTE_DATE, reads=("quote_date", "created_at"), column=None,
           filter=True, group=True, sort=True, bucket=("month", "quarter", "year"), sortExpr=SQL_QUOTE_DATE),
        _f("deal_tag", "成交標記", "enum", kind="expr", expr=deal_sql, reads=("deal_tag", "data_json"), column=None,
           filter=True, group=True, enum=_distinct_options("deal_tag")),
        _f("settle_status", "精算狀態", "enum", kind="expr", expr=settle_sql, reads=("settle_status", "data_json"), column=None,
           filter=True, group=True, enum=_distinct_options("settle_status")),
        _f("total", "含稅總額", "money", catalogId="quotation.total", filter=True, sort=True, aggregate=("count", "sum", "avg", "min", "max")),
        _f("pretax", "未稅金額", "money", catalogId="quotation.pretax", filter=True, sort=True, aggregate=("count", "sum", "avg", "min", "max")),
        _f("direct_margin_pct", "直接毛利率", "percent", catalogId="quotation.direct_margin_pct", filter=True, sort=True, aggregate=("count", "avg", "min", "max")),
        _f("net_margin_pct", "營業利益率", "percent", catalogId="quotation.net_margin_pct", filter=True, sort=True, aggregate=("count", "avg", "min", "max")),
    ]
    spec = {
        "label": "報價單", "table": "quotations", "modules": list(MODULES),
        "rowAccess": {"kind": "case", "scope": "read"},
        "exprs": (deal_sql, settle_sql, SQL_QUOTE_DATE, mine_sql),
        "mine": {"sql": mine_sql, "params": _MINE_PARAMS, "reads": ("sales_person_id", "sales_person", "assigned_user_ids", "data_json")},
        "execute": _execute,
        "fields": fields,
        "defaults": {"columns": ["quote_no", "customer_name", "project_name", "doc_type", "status", "total"],
                     "sort": {"field": "quote_date", "dir": "desc"}},
    }
    probs = _RC.register_source("quotation", OWNER, spec)
    if probs:
        return probs
    return _RC.register_source("case", OWNER, {
        "extends": "quotation", "label": "案件",
        "defaultFilters": [{"field": "deal_tag", "op": "in", "value": ["已成案", "已結案"]}],
    })
