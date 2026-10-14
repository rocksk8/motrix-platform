# -*- coding: utf-8 -*-
"""案件的『標示規則』紀錄提供者（BP-2 R4；提供者登記名 `("rules.entity", "case")`，由 modules/case/__init__.py 的 ModuleSpec 登記）。

規則引擎（L1 `helpers/rule_catalog.load_records`）不讀任何業務表，所有案件資料都從這裡來——這是 L1 唯一取得案件欄位值的路徑。

[不變式] ①唯讀：只有 SELECT，不寫任何東西；只讀本模組自己擁有的 `quotations` 表；不新增 SQL 欄位；
    ②逐筆讀取權限：用 `row_access.filter_sql("case", user, scope="read")`（與 `case_page_readable` 同一規則：擁有者／協作者、admin+、持 cashier）；
       看不到的案件不會出現在結果裡（看不到＝不存在）；
    ③金額欄位（含稅總額、直接毛利率、營業利益率）只在 `quote_money_visible(user)` 為真時才放進 `values`（縱深防禦：L1 目錄也會再裁一次）；
    ④自訂欄位只讀已存的 JSON（`data_json → caseRecord.customFields`），純量才收，鍵限 `^[A-Za-z][A-Za-z0-9_]{0,39}$`，以 `cf_<鍵>` 出現；
       哪些自訂欄位算數由 L1 目錄決定（已停用或未發布的欄位在目錄裡不存在 ⇒ 被裁掉）；
    ⑤只在旗標 `builder_rules.enabled`（且治理旗標）開啟時，才有規則路由會呼叫本函式；旗標關 ⇒ 完全不被呼叫。
[契約題] backend/modules/case/tests/test_rule_provider_2026_10_14.py
"""
import json
import re

from helpers import row_access
from helpers.financial_mask import quote_money_visible

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_MAX_IDS = 200
_COLS = "id, quote_no, project_name, customer_name, status, total, direct_margin_pct, net_margin_pct, deal_tag, settle_status, data_json"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _custom_fields(raw):
    try:
        d = json.loads(raw or "{}")
        cf = ((d or {}).get("caseRecord") or {}).get("customFields")
    except (TypeError, ValueError, AttributeError):
        return {}
    if not isinstance(cf, dict):
        return {}
    return {"cf_" + k: v for k, v in cf.items()
            if isinstance(k, str) and _KEY.match(k) and (v is None or isinstance(v, (str, int, float, bool)))}


def provide(conn, user, ids, limit):
    """⇒ `[{"id": 案號, "label": 顯示名稱, "values": {欄位代號: 值}}]`，最近更新的在前；`ids` 為 None ⇒ 最近 `limit` 筆。"""
    limit = max(1, min(int(limit), 1000))
    frag, params = row_access.filter_sql("case", user, scope="read")
    sql = "SELECT %s FROM quotations WHERE 1=1%s" % (_COLS, frag)
    args = list(params)
    if ids is not None:
        ids = [str(i) for i in ids][:_MAX_IDS]
        if not ids:
            return []
        sql += " AND quote_no IN (%s)" % ",".join("?" * len(ids))
        args += ids
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(limit)
    money = bool(quote_money_visible(user))
    out = []
    for r in conn.execute(sql, args).fetchall():
        vals = {"status": r["status"], "dealTag": r["deal_tag"], "settleStatus": r["settle_status"]}
        if money:
            vals.update(total=_num(r["total"]), directMarginPct=_num(r["direct_margin_pct"]), netMarginPct=_num(r["net_margin_pct"]))
        vals.update(_custom_fields(r["data_json"]))
        out.append({"id": r["quote_no"], "label": " ".join(x for x in (r["quote_no"], r["project_name"] or r["customer_name"] or "") if x), "values": vals})
    return out
