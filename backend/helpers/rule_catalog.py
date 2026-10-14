# -*- coding: utf-8 -*-
"""規則的欄位目錄轉接層（BP-2 R1；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §5）。

[單位] helper:rule_catalog    [層] L1    [穩定度] 實驗（旗標 builder_rules 關閉時沒有任何呼叫端）
[公開介面] entities, all_fields, rule_fields, visible_ids, load_records, stub_in_use, PERMS
[不變式] ①**唯一**對外給『規則能用哪些欄位』的入口；整合 S5 欄位目錄（`helpers/builtin_fields.py`，owner 3c）時**只改本檔的 `_catalog_for`**；
    ②目錄項不得是付款衍生旗標（`derived_from_payment` 或名稱在 `_PAYMENT_DERIVED` 內）——登錄時 ValueError；
    ③金額欄位必須帶權限（`perm`）；`internal`（S5 自訂欄位）＝只有能讀到該紀錄的人看得到；檢視者沒有該權限 ⇒ 欄位不在他的可見集合內（規則引擎據此不評估）；
    ④紀錄來源由各模組以 `("rules.entity", <主題>)` 提供者登記（`registry.providers`），**本檔不讀任何業務表**；
       提供者回傳的值再被本檔裁到只剩檢視者可見的欄位（縱深防禦：提供者多給也不會外洩）。
[契約題] backend/tests/test_rule_catalog_2026_10_14.py

⚠ TEMP：S5 欄位目錄（wip/t61-s5-impl-r4）合併前，`_TEMP_STUB` 只含『案件』一個主題的少數內建欄位，讓 R1～R3 能運作與被測。
合併 S5 後 `test_temp_stub_is_removed_once_s5_lands` 會失敗，強制移除這個 stub、改接 S5 的目錄（見該測試的說明）。
"""
from core import registry as _registry

#: 規則可引用的主題（entity）。key＝規則集的定義 key
ENTITIES = {"case": "案件（報價單）"}

#: 欄位權限代號 ⇒ 檢視者要滿足什麼（None＝能讀到該紀錄就能看）
PERMS = ("quote_money",)

_TYPES = ("number", "text", "enum", "date", "bool")
#: 付款衍生旗標（逾期應收、缺發票…）不得進目錄：它們維持今天的可見度，規則不可拿來推論被隱藏的金額（決策包 #7／U13）
_PAYMENT_DERIVED = frozenset({"overdue", "overdueReceivable", "overdueAmount", "missingInvoice", "invoiceMissing", "unpaid",
                              "paidAmount", "receivable", "payable", "paymentStatus", "paid"})


def _f(fid, label, typ, *, perm=None, unit="", options=None, money=False, internal=False):
    d = {"id": fid, "label": label, "type": typ, "perm": perm, "unit": unit, "money": money, "internal": internal}
    if options:
        d["options"] = list(options)
    return d


# ── TEMP stub（見檔頭）：欄位代號＝紀錄提供者回傳的 values 的鍵 ─────────────────────────────────────────────
_TEMP_STUB = {
    "case": [
        _f("netMarginPct", "營業利益率", "number", perm="quote_money", unit="%", money=True, internal=True),
        _f("directMarginPct", "直接毛利率", "number", perm="quote_money", unit="%", money=True, internal=True),
        _f("total", "含稅總額", "number", perm="quote_money", unit="元", money=True),
        _f("projectMarginPct", "專案毛利%", "number", perm="quote_money", unit="%", money=True, internal=True),     # 未稅收入扣品項成本；與報價單列表／表單同一個算式
        _f("status", "狀態", "text"),
        _f("dealTag", "成案標籤", "text"),
        _f("settleStatus", "精算狀態", "text"),
    ],
}
#: S5 的單據類型鍵 ⇒ 本目錄的主題（S5 自訂欄位以 `cf_<key>` 出現在本目錄）
_S5_RECORD_TYPE = {"case": "case_info"}


def _check_catalog(entity, fields):
    """登錄時的結構檢查；不合 ⇒ ValueError（程式錯誤，不吞）。"""
    seen = set()
    for f in fields:
        fid = f.get("id")
        if not isinstance(fid, str) or not fid or fid in seen:
            raise ValueError("%s：欄位代號缺少或重複：%r" % (entity, fid))
        seen.add(fid)
        if f.get("type") not in _TYPES:
            raise ValueError("%s.%s：型別不在 %s" % (entity, fid, _TYPES))
        if f.get("derived_from_payment") or fid in _PAYMENT_DERIVED:
            raise ValueError("%s.%s：付款衍生旗標不得作為規則輸入" % (entity, fid))
        if f.get("money") and f.get("perm") not in PERMS:
            raise ValueError("%s.%s：金額欄位必須帶權限" % (entity, fid))            # internal 單獨成立時＝能讀到該紀錄的人才看得到（S5 自訂欄位即是）
        if f.get("perm") is not None and f["perm"] not in PERMS:
            raise ValueError("%s.%s：未知的權限代號 %r" % (entity, fid, f["perm"]))
    return fields


def _s5_fields(entity, conn):
    """S5 欄位目錄的自訂欄位（旗標 builder_custom_fields 開啟且有已發布定義時）；S5 不在或任何錯誤 ⇒ []。"""
    rt = _S5_RECORD_TYPE.get(entity)
    if not rt:
        return []
    try:
        from helpers import builtin_fields as BF                      # 不在這條分支 ⇒ ImportError
        pub = BF.public_fields(rt, conn)
    except Exception:                                                  # noqa: BLE001
        return []
    kind = {"text": "text", "date": "date", "select": "enum", "checkbox": "bool"}
    out = []
    for f in pub or []:
        t = kind.get(f.get("type"))
        if t and f.get("key"):
            out.append(_f("cf_" + str(f["key"]), str(f.get("label") or f["key"]), t, options=f.get("options") if t == "enum" else None, internal=True))
    return out


def _catalog_for(entity, conn=None):
    """⇒ 該主題的完整目錄（未依檢視者裁剪）。**整合 S5 時只改這裡。**"""
    if entity not in ENTITIES:
        return []
    return _check_catalog(entity, list(_TEMP_STUB.get(entity, [])) + _s5_fields(entity, conn))


for _e, _fs in _TEMP_STUB.items():                                    # 匯入時就檢查 stub
    _check_catalog(_e, _fs)


def stub_in_use() -> bool:
    return bool(_TEMP_STUB)


def entities() -> list:
    return [{"key": k, "label": v} for k, v in ENTITIES.items()]


def all_fields(entity, conn=None) -> dict:
    """驗證器用：`{欄位代號: 欄位}`（不依檢視者裁剪）。未知主題 ⇒ {}。"""
    return {f["id"]: f for f in _catalog_for(entity, conn)}


def _has_perm(perm, user) -> bool:
    if perm is None:
        return True
    if perm == "quote_money":
        from helpers.financial_mask import quote_money_visible
        return bool(quote_money_visible(user))
    return False                                                       # 不認得的權限 ⇒ 看不到（fail closed）


def visible_ids(entity, user, conn=None) -> frozenset:
    """這位檢視者看得到的欄位代號集合（規則引擎的 `visible`）。"""
    return frozenset(f["id"] for f in _catalog_for(entity, conn) if _has_perm(f.get("perm"), user))


def rule_fields(entity, user, conn=None) -> list:
    """規則編輯器的欄位下拉：只含這位使用者看得到的欄位（含型別、單位、可用的比較方式）。"""
    from helpers.rule_grammar import OPS_BY_TYPE
    vis = visible_ids(entity, user, conn)
    return [dict(f, ops=list(OPS_BY_TYPE[f["type"]])) for f in _catalog_for(entity, conn) if f["id"] in vis]


def load_records(entity, user, conn, *, ids=None, limit=200):
    """從該主題的提供者載入紀錄 ⇒ `[{"id", "label", "values"}]`（已裁到檢視者可見的欄位）；沒有提供者 ⇒ None（呼叫端回『尚未接上資料來源』）。
    提供者契約：`fn(conn, user, ids, limit) -> [{"id": str, "label": str, "values": {欄位代號: 值}}]`，**須自己做逐筆讀取權限過濾**（看不到的紀錄不回），最新的在前。"""
    fn = _registry.providers("rules.entity").get(entity)
    if fn is None:
        return None
    limit = max(1, min(int(limit), 1000))
    rows = fn(conn, user, list(ids) if ids is not None else None, limit) or []
    vis = visible_ids(entity, user, conn)
    out = []
    for r in rows[:limit]:
        if isinstance(r, dict) and "id" in r and isinstance(r.get("values"), dict):
            out.append({"id": r["id"], "label": str(r.get("label") or r["id"]), "values": {k: v for k, v in r["values"].items() if k in vis}})
    return out
