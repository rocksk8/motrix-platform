# -*- coding: utf-8 -*-
"""共用欄位目錄（T64 切片 D／F7 的 S0：只登記、不改行為）。

[單位] helper:field_catalog    [層] L1    [穩定度] 實驗（唯讀登記；沒有旗標、沒有路由、沒有資料表）
[公開介面] API_GROUPS, CEILINGS, FAMILIES, FIELDS, KINDS, api_keys, by_id, export_problems, fields, history_labels, problems, screen_problems
[不變式] ①純資料＋純函式，只 import 標準函式庫 `types`（`financial_mask` 反過來從這裡取鍵名，不可形成環）。
    ②`financial_mask` 的 6 份金額鍵清單由本目錄衍生，鍵名與順序與切片前逐字相同（守門：tests/platform/test_field_catalog_t64.py 內寫死今天的清單）。
    ③匯出的金額欄位／工作表與版面的欄位點由本目錄登記並與真實登記表互相核對（兩個方向都驗）；S0 只核對，不改它們的登記方式。
    ④`ceiling` 是**登記值**（說明這個欄位今天由哪一種後端遮蔽把關），S0 不用它做任何判斷；S1 才用出口矩陣金標驗證它與實際出口一致。
    ⑤`FIELDS` 是唯讀的：每筆是 `MappingProxyType`、內容全是不可變型別（元組／字串）；`fields()`／`by_id()` 回傳複本。
    ⑥欄位 `id` 發布後不改名（之後的政策會引用它）；改名＝新增一筆＋舊的停用。
設計：docs/platform/plans/T64-F7-FIELD-POLICY-DESIGN.md §2、§8 S0。
[契約題] backend/tests/platform/test_field_catalog_t64.py
"""
from types import MappingProxyType

#: 家族：同一家族一起判斷（成本藏了、毛利露出來＝可以反推成本）。
FAMILIES = ("cost", "margin", "price", "payment", "note")
#: 天花板（後端遮蔽的種類）：quote_money＝報價單層級金額；finance_money＝精算／款項／財務總覽；material_money＝叫料體系；cashier＝出納。
CEILINGS = ("quote_money", "finance_money", "material_money", "cashier")

#: 遮蔽動作的種類：key＝dict 鍵剝除／置空（API_GROUPS 那五組）；subtree＝整段清空；text＝內容式文字替換或剝除；document＝整份輸出（例：內部 PDF）。
KINDS = ("key", "subtree", "text", "document")

#: API 回應裡的鍵名分組（對應 financial_mask 的 6 份清單中的 5 份；第 6 份是修改紀錄的顯示名稱，見 `history`）。
API_GROUPS = ("quotation_cols", "quote_item", "quote_top", "payment", "material_order")


def _f(fid, label, family, ceiling, api=None, history=None, derived_from=(), screen=(), export=None, kind="key", exceptions=()):
    return MappingProxyType({"id": fid, "label": label, "family": family, "moneyClass": "money", "ceiling": ceiling,
                             "api": api, "history": tuple(history or ()), "derivedFrom": tuple(derived_from),
                             "screen": tuple(screen), "export": export, "kind": kind, "exceptions": tuple(exceptions)})


def _sheet(export_id, sheet_id, label, ceiling):
    return _f("sheet.%s.%s" % (export_id.replace(":", "_").replace("-", "_"), sheet_id), label, "payment", ceiling,
              export=(export_id, "sheet:" + sheet_id))


#: 順序有意義：各分組的鍵名順序＝今天 `financial_mask` 的元組順序。
FIELDS = (
    # ── quotations 表頂層欄位（清單、結案檢核、單筆 GET）──
    _f("quotation.total", "含稅總額", "price", "quote_money", api=("quotation_cols", "total"), history=("含稅總額",)),
    _f("quotation.pretax", "未稅金額", "price", "quote_money", api=("quotation_cols", "pretax"), history=("未稅金額",)),
    _f("quotation.direct_margin_pct", "直接毛利率", "margin", "quote_money", api=("quotation_cols", "direct_margin_pct"),
       history=("直接毛利率",), derived_from=("quote_item.cost",)),
    _f("quotation.net_margin_pct", "營業利益率", "margin", "quote_money", api=("quotation_cols", "net_margin_pct"),
       history=("營業利益率", "淨利率"), derived_from=("quote_item.cost",)),
    _f("quotation.project_margin_pct", "專案毛利率", "margin", "quote_money", api=("quotation_cols", "project_margin_pct"),
       derived_from=("quote_item.cost",)),
    # ── 報價品項 ──
    _f("quote_item.cost", "品項成本", "cost", "quote_money", api=("quote_item", "cost")),
    _f("quote_item.margin", "品項毛利", "margin", "quote_money", api=("quote_item", "margin"), derived_from=("quote_item.cost",)),
    _f("quote_item.unitPrice", "品項單價", "price", "quote_money", api=("quote_item", "unitPrice")),
    _f("quote_item.amount", "品項金額", "price", "quote_money", api=("quote_item", "amount")),
    # ── 報價單頂層 ──
    _f("quote.discount", "折讓", "price", "quote_money", api=("quote_top", "discount")),
    _f("quote.freight", "運費", "cost", "quote_money", api=("quote_top", "freight")),
    _f("quote.indirectLogistics", "間接物流費", "cost", "quote_money", api=("quote_top", "indirectLogistics")),
    _f("quote.indirectInstallation", "間接安裝費", "cost", "quote_money", api=("quote_top", "indirectInstallation")),
    _f("quote.indirectTravel", "間接差旅費", "cost", "quote_money", api=("quote_top", "indirectTravel")),
    _f("quote.indirectWarranty", "間接保固費", "cost", "quote_money", api=("quote_top", "indirectWarranty")),
    _f("quote.indirectOther", "其他間接費", "cost", "quote_money", api=("quote_top", "indirectOther")),
    _f("quote.tot", "報價合計與利潤彙總", "margin", "quote_money", api=("quote_top", "tot"), derived_from=("quote_item.cost",)),
    _f("quote.overheadPct", "管銷分攤比率", "margin", "quote_money", api=("quote_top", "overheadPct"), history=("管銷分攤比率",),
       derived_from=("quote_item.cost",)),
    # ── 款項期別 ──
    _f("payment.amount", "款項金額", "payment", "finance_money", api=("payment", "amount")),
    _f("payment.pct", "款項比例", "payment", "finance_money", api=("payment", "pct")),
    _f("payment.actualAmount", "實收／實付金額", "payment", "finance_money", api=("payment", "actualAmount")),
    _f("payment.feeAmount", "手續費", "payment", "finance_money", api=("payment", "feeAmount")),
    _f("payment.feeNote", "手續費備註", "payment", "finance_money", api=("payment", "feeNote")),
    _f("payment.invoicePretax", "發票未稅金額", "payment", "finance_money", api=("payment", "invoicePretax")),
    _f("payment.invoiceTax", "發票稅額", "payment", "finance_money", api=("payment", "invoiceTax")),
    # ── 叫料品項 ──
    _f("material_order.unitPrice", "材料申請單價", "cost", "material_money", api=("material_order", "unitPrice")),
    _f("material_order.totalPrice", "材料申請總價", "cost", "material_money", api=("material_order", "totalPrice")),
    _f("material_order.paidAmount", "材料申請已付金額", "payment", "material_money", api=("material_order", "paidAmount")),
    _f("material_order.totalAmount", "材料申請合計金額", "cost", "material_money", api=("material_order", "totalAmount")),
    # ── 非『鍵』的遮蔽（S1a 補登記：今天寫死在 financial_mask／端點函式裡的規則；行為不變，只是變成目錄上的資料）──
    _f("settlement.amounts", "精算金額（整段，只留狀態）", "payment", "finance_money", kind="subtree"),
    _f("payment.received_legacy", "款項已收金額（舊形狀：數字）", "payment", "finance_money", kind="subtree"),
    _f("edit_history.reason", "修改紀錄的理由（自由文字）", "note", "quote_money", kind="text"),
    _f("edit_history.reopen_reason", "重新開啟精算的理由（自由文字）", "note", "finance_money", kind="text"),
    _f("edit_history.changes", "修改紀錄的金額變動（前後值）", "price", "quote_money", kind="text", history=()),
    _f("approval.reasons", "需審核原因（含毛利／金額／折讓者）", "note", "quote_money", kind="text"),
    _f("quote_pdf.internal", "含成本／毛利的內部報價 PDF", "cost", "quote_money", kind="document", exceptions=("case_approver",)),
    # ── 版面欄位點＋匯出欄位（同一個『金額』欄位在三個地方登記的那一個）──
    _f("case_list.amount", "案件清單金額", "price", "quote_money", screen=(("case", "case", "amount"),), export=("case:case-batch", "amount")),
    _f("quote_list.amount", "報價單清單金額（含稅）", "price", "quote_money", screen=(("case", "quote", "amount"),)),
    # ── 匯出的含金額工作表 ──
    _sheet("arap:cashier-history", "outgoing", "出納匯出：已匯款明細", "cashier"),
    _sheet("arap:cashier-history", "payreq", "出納匯出：支出申請付款明細", "cashier"),
    _sheet("arap:cashier-history", "incoming", "出納匯出：已收款明細", "cashier"),
    _sheet("arap:cashier-history", "bonus", "出納匯出：獎金發放明細", "cashier"),
    _sheet("reports:financial", "summary", "營運報表：執行摘要", "finance_money"),
    _sheet("reports:financial", "targets", "營運報表：目標達成率", "finance_money"),
    _sheet("reports:financial", "payments", "營運報表：本期收款明細", "finance_money"),
    _sheet("reports:financial", "outstanding", "營運報表：未收款清單", "finance_money"),
    _sheet("reports:financial", "month", "營運報表：當月收支", "finance_money"),
    _sheet("reports:financial", "quarter", "營運報表：本季收支", "finance_money"),
    _sheet("reports:financial", "year", "營運報表：今年度收支", "finance_money"),
    _sheet("reports:financial", "cases", "營運報表：案件清單", "finance_money"),
    _sheet("reports:financial", "sales", "營運報表：業務員績效", "finance_money"),
    _sheet("reports:financial", "margin", "營運報表：毛利分析", "finance_money"),
    _sheet("reports:financial", "settle", "營運報表：已結案未精算", "finance_money"),
    _sheet("reports:financial", "aging", "營運報表：帳齡分析", "finance_money"),
)


def fields() -> list:
    """全部欄位（新的 list，每筆是複本；改回傳值不會動目錄）。"""
    return [dict(f) for f in FIELDS]


def by_id(fid):
    for f in FIELDS:
        if f["id"] == fid:
            return dict(f)
    return None


def api_keys(group) -> tuple:
    """API 回應裡某一組金額鍵名（順序＝目錄順序）。`financial_mask` 的元組由這裡衍生。"""
    if group not in API_GROUPS:
        raise KeyError(group)
    return tuple(f["api"][1] for f in FIELDS if f["api"] and f["api"][0] == group)


def history_labels() -> set:
    """修改紀錄裡要遮蔽的顯示名稱（舊紀錄存的是舊名稱，所以一個欄位可以有多個）。"""
    return {lab for f in FIELDS for lab in f["history"]}


def problems() -> list:
    """目錄自己的一致性問題（空＝合格）：代號唯一、家族／天花板在清單內、分組內鍵名唯一、derivedFrom 指向存在的欄位且不指向自己。"""
    out, ids = [], set()
    for f in FIELDS:
        fid = f["id"]
        if fid in ids:
            out.append("欄位代號重複：%s" % fid)
        ids.add(fid)
        if f["kind"] not in KINDS:
            out.append("%s：遮蔽種類不在清單內：%s" % (fid, f["kind"]))
        if f["kind"] != "key" and f["api"]:
            out.append("%s：非 key 種類不可有 API 鍵名" % fid)
        if f["family"] not in FAMILIES:
            out.append("%s：家族不在清單內：%s" % (fid, f["family"]))
        if f["ceiling"] not in CEILINGS:
            out.append("%s：天花板不在清單內：%s" % (fid, f["ceiling"]))
        if not str(f["label"]).strip():
            out.append("%s：沒有白話名稱" % fid)
        if f["api"] and f["api"][0] not in API_GROUPS:
            out.append("%s：API 分組不明：%s" % (fid, f["api"][0]))
    seen = set()
    for f in FIELDS:
        if f["api"]:
            if f["api"] in seen:
                out.append("API 鍵名重複：%s" % (f["api"],))
            seen.add(f["api"])
    for f in FIELDS:
        for d in f["derivedFrom"]:
            if d not in ids:
                out.append("%s：derivedFrom 指向不存在的欄位 %s" % (f["id"], d))
            elif d == f["id"]:
                out.append("%s：derivedFrom 不可指向自己" % f["id"])
    return out


def export_problems(registered) -> list:
    """目錄 ↔ 匯出登記表核對（`export_templates.registered()` 的形狀）。兩個方向：
    ①目錄裡的每個 export 參照，在登記表裡必須存在且是含金額的欄位／工作表；
    ②登記表裡每個含金額的欄位／工作表，目錄必須有對應的一筆。"""
    out, claimed = [], set()
    for f in FIELDS:
        ref = f["export"]
        if not ref:
            continue
        claimed.add(ref)
        spec = (registered or {}).get(ref[0])
        if spec is None:
            out.append("%s：匯出 %s 沒有登記" % (f["id"], ref[0]))
            continue
        if ref[1].startswith("sheet:"):
            hit = [s for s in spec.get("sheets") or [] if s["id"] == ref[1][6:]]
            if not hit:
                out.append("%s：匯出 %s 沒有工作表 %s" % (f["id"], ref[0], ref[1][6:]))
            elif not hit[0].get("money"):
                out.append("%s：工作表 %s 在登記表裡不是含金額" % (f["id"], ref[1][6:]))
        else:
            hit = [c for c in spec.get("columns") or [] if c["id"] == ref[1]]
            if not hit:
                out.append("%s：匯出 %s 沒有欄位 %s" % (f["id"], ref[0], ref[1]))
            elif not hit[0].get("money"):
                out.append("%s：欄位 %s 在登記表裡不是含金額" % (f["id"], ref[1]))
    for eid, spec in (registered or {}).items():
        for c in spec.get("columns") or []:
            if c.get("money") and (eid, c["id"]) not in claimed:
                out.append("匯出 %s 的含金額欄位 %s 沒有登記在欄位目錄" % (eid, c["id"]))
        for s in spec.get("sheets") or []:
            if s.get("money") and (eid, "sheet:" + s["id"]) not in claimed:
                out.append("匯出 %s 的含金額工作表 %s 沒有登記在欄位目錄" % (eid, s["id"]))
    return out


def screen_problems(points) -> list:
    """目錄 ↔ 版面欄位點核對。`points`＝`core.catalog.layout_points(None)` 的結果。
    目錄裡每個 screen 參照 `(擁有模組, entity, 欄位鍵)` 都必須對得到一個 `kind=field` 的點。"""
    out = []
    for f in FIELDS:
        for owner, entity, key in f["screen"]:
            hit = [p for p in points or [] if p.get("kind") == "field" and p.get("entity") == entity and p.get("field") == key
                   and str(p.get("id", "")).startswith(owner + ":")]
            if not hit:
                out.append("%s：版面上找不到欄位點 %s/%s/%s" % (f["id"], owner, entity, key))
    return out
