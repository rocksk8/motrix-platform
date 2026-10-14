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

from helpers import profit_rules as _PR
from helpers import row_access
from helpers.financial_mask import quote_money_visible

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_MAX_IDS = 200
_COLS = "id, quote_no, project_name, customer_name, status, total, pretax, direct_margin_pct, net_margin_pct, deal_tag, settle_status, data_json"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse(raw):
    """data_json ⇒ dict；壞 JSON、過深的 JSON（RecursionError）、不是物件 ⇒ {}（只影響這一列，不可讓整個請求 500）。"""
    try:
        d = json.loads(raw or "{}")
    except Exception:                                                  # noqa: BLE001  含 RecursionError
        return {}
    return d if isinstance(d, dict) else {}


def _custom_fields(d):
    try:
        cf = (d.get("caseRecord") or {}).get("customFields")
    except Exception:                                                  # noqa: BLE001
        return {}
    if not isinstance(cf, dict):
        return {}
    return {"cf_" + k: v for k, v in cf.items()
            if isinstance(k, str) and _KEY.match(k) and (v is None or isinstance(v, (str, int, float, bool)))}


def _text(v):
    return v if isinstance(v, str) else ""


def _legacy_text(col, d, path):
    """與 quotations.SQL_DEAL_TAG／SQL_SETTLE_STATUS 同一個語意：`COALESCE(NULLIF(欄位,''), json_extract(data_json, 路徑), '')`
    （舊資料〔v6 之前〕欄位是空的、值還在 data_json 裡；直接讀欄位會把已結案的舊案件當成未結案）。在 Python 端做，壞 JSON 只影響該列。"""
    if col not in (None, ""):
        return _text(col)
    cur = d
    for k in path:
        cur = cur.get(k) if isinstance(cur, dict) else None
    return _text(cur)


def _project_margin(r, d):
    """專案毛利%：與案件列表（quotations.py 的 project_margin_pct）同一個函式與同一組輸入（pretax 欄＋data_json.tot.totalCost）；算不出 ⇒ None（不是 0）。"""
    try:
        tc = (d.get("tot") or {}).get("totalCost")
        return _PR.project_margin(r["pretax"], tc)["pct"]
    except Exception:                                                  # noqa: BLE001  這一列算不出 ⇒ None（不是 0）
        return None


def provide(conn, user, ids, limit, fields=None):
    """⇒ `[{"id": 案號, "label": 顯示名稱, "values": {欄位代號: 值}}]`，最近更新的在前；`ids` 為 None ⇒ 最近 `limit` 筆。
    `fields`＝呼叫端實際需要的欄位代號集合（None＝全部）：沒有人用到 `cf_` 自訂欄位時不解析自訂欄位；舊資料需要 data_json 才補得出的欄位（結案標籤、精算狀態）仍會解析。"""
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
        try:
            vals = _row_values(r, money, fields)
        except Exception:                                              # noqa: BLE001  單列出任何問題只丟掉該列的值，不影響整個請求
            vals = {"status": _text(r["status"])}
        out.append({"id": r["quote_no"], "label": " ".join(x for x in (r["quote_no"], r["project_name"] or r["customer_name"] or "") if x), "values": vals})
    return out


def _row_values(r, money, fields):
    need_cf = fields is None or any(str(f).startswith("cf_") for f in fields)
    need_pm = money and (fields is None or "projectMarginPct" in fields)
    legacy = r["deal_tag"] in (None, "") or r["settle_status"] in (None, "")
    d = _parse(r["data_json"]) if (need_cf or need_pm or legacy) else {}
    vals = {"status": r["status"], "dealTag": _legacy_text(r["deal_tag"], d, ("dealTag",)),
            "settleStatus": _legacy_text(r["settle_status"], d, ("settlement", "status"))}
    if money:
        vals.update(total=_num(r["total"]), directMarginPct=_num(r["direct_margin_pct"]), netMarginPct=_num(r["net_margin_pct"]))
        if need_pm:
            vals["projectMarginPct"] = _project_margin(r, d)
    if need_cf:
        vals.update(_custom_fields(d))
    return vals
