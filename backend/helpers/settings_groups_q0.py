# -*- coding: utf-8 -*-
"""T63 Q0 設定群組：報價單輸出（quote_output）與報價單個資（quote_privacy）。**預設值＝上線前的行為**（部署零行為變更）。

[單位] helper:settings_groups_q0    [層] L1    [穩定度] 實驗
[公開介面] quote_cf_scan, register
[不變式] ①預設值與今天的報價單 PDF／表單完全相同；②放寬方向（印得更少、少一道告知）走『待核准＋第二位最高管理者＋確認期間』（沿用 settings_registry）；
    ③設定讀不到時（引擎退回快取或預設）：條款照印、個資欄位維持可隱藏（今天的行為）；使用端另外要求總開關與報價單開關都開才算開（見 builtin_fields.type_enabled）。
設計：docs/platform/plans/T63-Q0-SETTINGS-SPEC.md。
[契約題] backend/tests/platform/test_q0_settings_t63.py
"""
import json as _json

from helpers.case_access import case_data_json_rows
from helpers import quote_privacy as _quote_privacy  # noqa: F401  載入時向 core.catalog 登記『個資欄位不可隱藏』提供者

_TERMS = ("paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales")


_CAP = 5000


def _terms_scan(conn):
    """唯讀：(有填任何條款文字的報價單張數, 是否只掃了上限內的列)；失敗 ⇒ None。"""
    try:
        n = 0
        rows = case_data_json_rows(conn, _CAP)
        for r in rows:
            try:
                q = _json.loads(r or "{}") or {}
            except (TypeError, ValueError):
                continue
            if isinstance(q, dict) and any(str(q.get(k) or "").strip() for k in _TERMS):
                n += 1
        return n, len(rows) >= _CAP
    except Exception:                                                                    # noqa: BLE001
        return None


def _contacts_scan(conn):
    """唯讀：(填了電子郵件或傳真的報價單張數, 是否只掃了上限內的列)；失敗 ⇒ None。"""
    try:
        n = 0
        rows = case_data_json_rows(conn, _CAP)
        for r in rows:
            try:
                q = _json.loads(r or "{}") or {}
            except (TypeError, ValueError):
                continue
            if isinstance(q, dict) and (str(q.get("contactEmail") or "").strip() or str(q.get("contactFax") or "").strip()):
                n += 1
        return n, len(rows) >= _CAP
    except Exception:                                                                    # noqa: BLE001
        return None


def quote_cf_scan(conn):
    """唯讀：(有自訂欄位值的報價單張數, 是否只掃了上限內的列)；失敗 ⇒ None。只掃 JSON 裡出現 customFields 的列。"""
    try:
        n = 0
        rows = case_data_json_rows(conn, _CAP, customfields_only=True)
        for r in rows:
            try:
                cf = (_json.loads(r or "{}") or {}).get("customFields")
            except (TypeError, ValueError):
                continue
            if isinstance(cf, dict) and cf:
                n += 1
        return n, len(rows) >= _CAP
    except Exception:                                                                    # noqa: BLE001
        return None


def _terms_impact(conn, new_value):
    r = _terms_scan(conn)
    if r is None:
        raise RuntimeError("count failed")
    n, capped = r
    return {"numbers": {"quotationsWithTerms": n, "atLeast": capped},
            "sentence": ("目前有%s %d 張報價單填了報價條件。%s" % ("至少" if capped else "", n, "改成不印後，被隱藏的條件欄位不會出現在這些報價單的 PDF 與預覽。" if new_value
                                                             else "維持照印：隱藏欄位只是不顯示輸入框，已存的條件仍印在 PDF。"))}


def _contacts_impact(conn, new_value):
    r = _contacts_scan(conn)
    if r is None:
        raise RuntimeError("count failed")
    n, capped = r
    return {"numbers": {"quotationsWithContacts": n, "atLeast": capped},
            "sentence": "目前有%s %d 張報價單填了電子郵件或傳真。隱藏只影響表單上是否顯示輸入框，已存的內容不會被刪除。" % ("至少" if capped else "", n)}


def register(S, _register_core):
    """由 `helpers.settings_groups` 在每次載入時呼叫（那個模組被重新載入時，核心群組要跟著重新登錄）。"""
    _register_core(
        "quote_output", "報價單輸出",
        [
            S("hidden_terms_pdf_mode", "int", 0, min=0, max=1, risk="legal", loosen="up", recommended=0,
              risk_text="【高影響】選「不印」後，被管理者隱藏的報價條件（付款、交貨、驗收、保固、售後）不會印在報價單 PDF 上，客戶看不到這些條件，之後可能因為條件沒寫而起爭議。",
              impact_scope={"documents": ["報價單 PDF", "報價單預覽"], "roles": ["業務", "客戶"], "amounts": "不改任何金額；只決定被隱藏的報價條件文字會不會印在客戶版文件上。", "reversible": True, "effective": "pending"},
              question="報價單上被隱藏的報價條件欄位，PDF 還要照印嗎？", label="隱藏的報價條件是否印在 PDF",
              help="管理者可以在表單上隱藏某個報價條件欄位。預設照印：隱藏只是不顯示輸入框，已存的條件（含範本預設文字）仍印在 PDF。改成不印後，被隱藏的欄位不會印出。",
              impact="只影響之後產生或重新開啟的報價單 PDF 與預覽；已寄出的文件不會改，也不會刪掉任何已存的內容。改成不印屬於放寬，需要第二位最高管理者核准並經確認期間；改回照印立即生效。",
              choices=[(0, "照印（建議）", "隱藏欄位只是不顯示輸入框，已存的條件仍印在 PDF。"),
                       (1, "不印被隱藏的條件", "被隱藏的條件欄位不會出現在 PDF 與預覽。")],
              impact_fn=_terms_impact),
        ],
        sensitive=False, risk="legal",
        help="報價單 PDF 與預覽如何處理被管理者隱藏的報價條件；金額與稅務不在這裡調整。",
    )

    _register_core(
        "quote_privacy", "報價單個人資料欄位",
        [
            S("contact_email_hideable", "int", 1, min=0, max=1, risk="legal", recommended=1,
              risk_text="改成不可隱藏後，管理者不能再把客戶電子郵件欄位從報價單表單隱藏；已經隱藏的會恢復顯示。",
              impact_scope={"documents": ["報價單表單"], "roles": ["業務", "最高管理者"], "amounts": "不改任何金額；只決定客戶電子郵件欄位能不能被隱藏。", "reversible": True, "effective": "immediate"},
              question="客戶電子郵件欄位可以讓管理者從報價單表單隱藏嗎？", label="客戶電子郵件可隱藏",
              help="電子郵件屬於個人資料。預設可以隱藏；隱藏只是不顯示輸入框，不會刪掉已存的內容，個資告知流程也不變。",
              impact="只影響報價單表單與排版器；不改已存的內容、PDF 或任何金額。改成不可隱藏立即生效（收緊）：先前被隱藏的欄位會立刻對所有人重新顯示，資料不變；改回可隱藏後，原本的隱藏設定會恢復。",
              choices=[(1, "可隱藏（目前做法）", "管理者可以在排版器隱藏這個欄位。"), (0, "不可隱藏", "這個欄位固定顯示。")],
              impact_fn=_contacts_impact),
            S("contact_fax_hideable", "int", 1, min=0, max=1, risk="legal", recommended=1,
              risk_text="改成不可隱藏後，管理者不能再把客戶傳真欄位從報價單表單隱藏；已經隱藏的會恢復顯示。",
              impact_scope={"documents": ["報價單表單"], "roles": ["業務", "最高管理者"], "amounts": "不改任何金額；只決定客戶傳真欄位能不能被隱藏。", "reversible": True, "effective": "immediate"},
              question="客戶傳真欄位可以讓管理者從報價單表單隱藏嗎？", label="客戶傳真可隱藏",
              help="預設可以隱藏；隱藏只是不顯示輸入框，不會刪掉已存的內容，個資告知流程也不變。",
              impact="只影響報價單表單與排版器；不改已存的內容、PDF 或任何金額。改成不可隱藏立即生效（收緊）：先前被隱藏的欄位會立刻對所有人重新顯示，資料不變；改回可隱藏後，原本的隱藏設定會恢復。",
              choices=[(1, "可隱藏（目前做法）", "管理者可以在排版器隱藏這個欄位。"), (0, "不可隱藏", "這個欄位固定顯示。")],
              impact_fn=_contacts_impact),
        ],
        sensitive=False, risk="legal",
        help="報價單上客戶個人資料欄位（電子郵件、傳真）能不能被管理者隱藏。",
    )
