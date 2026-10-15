# -*- coding: utf-8 -*-
"""T64 F7 S1a：`field_policy.visible()` 等價金標——角色 × 模組勾選 × 財務旗標狀態 × 職責角色授予／扣項 × 目錄全部欄位，
對照**寫在本檔的舊規則表**（不讀目錄、不呼叫被測函式，避免自證）。零出口改動：這一步只證明『新函式＝舊函式』。
"""
import copy
import json

import pytest

from helpers import auth
from helpers import field_catalog as FC
from helpers import field_policy as FP
from helpers import financial_mask as FM

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")
MODULES = ("[]", '["cashier"]', '["financial_view"]', '["cashier","financial_view","finance"]')
MODES = ("off", "shadow", "on")
ALL3 = {"cashier", "finance", "financial_view"}
#: 職責角色授予／個人扣項情境：id → (授予的鍵, 扣項)；id=None ＝沒有 id（只看基礎類別，不查庫）
GRANTS = {None: (set(), set()), 1: ({"finance"}, set()), 2: ({"cashier"}, set()), 3: ({"financial_view"}, set()),
          4: (set(), {"cashier"}), 5: ({"finance"}, {"finance"})}


def _eff(role, uid):
    """生效的財務鍵（舊測試表自己重算，不呼叫 auth.finance_effective_keys）。"""
    if role == "superadmin":
        return set(ALL3)
    base = set(ALL3) if role == "finance" else set()
    if uid is None:
        return base
    g, s = GRANTS[uid]
    return (base | g) - s


def _expected(ceiling, role, mode, uid):
    """舊規則表（2026-10-15，origin/train/t63-int 的 auth／financial_mask 行為，手寫）。"""
    eff = _eff(role, uid)
    if mode == "on":
        duty = role != "superadmin" and "finance" in eff
        finance_money = "financial_view" in eff or "cashier" in eff
        cashier = "cashier" in eff
    else:                                                   # off／shadow：回傳舊規則（只看角色）
        duty = role == "finance"
        finance_money = cashier = role in ("superadmin", "finance")
    quote = role in ("superadmin", "admin", "sales") or duty
    return {"quote_money": quote, "material_money": quote, "finance_money": finance_money, "cashier": cashier}[ceiling]


@pytest.fixture
def finance_env(monkeypatch):
    state = {"mode": "off"}
    monkeypatch.setattr(auth, "_finance_mode", lambda: state["mode"])
    monkeypatch.setattr(auth, "_finance_grants", lambda uid, cache: (set(GRANTS[uid][0]), set(GRANTS[uid][1])))
    monkeypatch.setattr(auth, "_finance_shadow_report", lambda *a, **k: None)      # 影子模式的稽核寫庫在這裡不需要
    return state


def _user(role, modules, uid):
    return {"id": uid, "username": "u%s" % (uid or 0), "role": role, "modules": modules}


def _mismatches(env_state, by_id=None):
    """⇒ 與舊規則表不同的格子清單（空＝逐格相同）。`by_id` 供正對照換掉目錄查詢。"""
    bad = []
    for mode in MODES:
        env_state["mode"] = mode
        for role in ROLES:
            for modules in MODULES:
                for uid in GRANTS:
                    u = _user(role, modules, uid)
                    for f in FC.FIELDS:
                        got = FP.visible(f["id"], u)
                        want = _expected(f["ceiling"], role, mode, uid)
                        if got != want:
                            bad.append((f["id"], role, modules, mode, uid, got, want))
    return bad


def test_visible_equals_the_old_hard_coded_table_for_every_cell(finance_env):
    assert _mismatches(finance_env) == []


def test_positive_control_a_wrong_ceiling_mapping_turns_the_golden_red(finance_env, monkeypatch):
    real = FC.by_id

    def swapped(fid):
        f = real(fid)
        if f and fid == "payment.amount":
            f["ceiling"] = "quote_money"                    # 故意對映錯一格：財務款項被當成報價層級
        return f
    monkeypatch.setattr(FC, "by_id", swapped)
    bad = _mismatches(finance_env)
    assert bad and all(b[0] == "payment.amount" for b in bad)
    assert any(b[1] in ("admin", "sales") for b in bad)     # 業務／管理員會多看到款項金額——正是金標要抓的洩漏


def test_the_expected_table_itself_matches_the_documented_tiers(finance_env):
    """舊規則表自檢：off 模式下的四個層級（避免金標的『期望值』被改錯而一起綠）。"""
    for role in ROLES:
        assert _expected("quote_money", role, "off", None) == (role in ("superadmin", "admin", "sales", "finance"))
        assert _expected("finance_money", role, "off", None) == (role in ("superadmin", "finance"))
        assert _expected("cashier", role, "off", None) == (role in ("superadmin", "finance"))
    assert _expected("quote_money", "sales", "on", 1) is True and _expected("finance_money", "sales", "on", 1) is False
    assert _expected("cashier", "finance", "on", 4) is False and _expected("quote_money", "finance", "on", 5) is False


def test_unknown_field_and_unknown_ceiling_are_hidden(finance_env, monkeypatch):
    u = _user("superadmin", "[]", None)
    assert FP.visible("no.such_field", u) is False
    assert FP.tier_allowed("no_such_tier", u) is False
    monkeypatch.setattr(FC, "by_id", lambda fid: {"id": fid, "ceiling": "no_such_tier"})
    assert FP.visible("quote_item.cost", u) is False


def test_errors_fail_closed_never_open(finance_env, monkeypatch):
    u = _user("superadmin", "[]", None)
    assert FP.visible("quote_item.cost", u) is True

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(FM, "quote_money_visible", boom)
    assert FP.visible("quote_item.cost", u) is False
    assert FP.visible_many(["quote_item.cost", "payment.amount"], u)["quote_item.cost"] is False
    assert FP.mask_flags(u)["keep_quote"] is False
    monkeypatch.setattr(FC, "by_id", boom)
    assert FP.visible("payment.amount", u) is False


def test_visible_many_equals_visible(finance_env):
    ids = [f["id"] for f in FC.FIELDS]
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for uid in (None, 1, 4):
                u = _user(role, "[]", uid)
                assert FP.visible_many(ids, u) == {i: FP.visible(i, u) for i in ids}
    assert FP.visible_many(["no.such"], _user("superadmin", "[]", None)) == {"no.such": False}


def test_mask_flags_equal_the_old_function_results(finance_env):
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for uid in GRANTS:
                u = _user(role, "[]", uid)
                assert FP.mask_flags(u) == {"keep_quote": FM.quote_money_visible(u), "keep_orders": FM.material_money_visible(u),
                                            "money": FM.money_visible(u)}


_SAMPLE = {
    "items": [{"name": "A", "cost": 10, "margin": 5, "unitPrice": 15, "amount": 30}],
    "discount": 1, "freight": 2, "tot": {"x": 1}, "overheadPct": 25,
    "settlement": {"status": "finalized", "actual": 123},
    "approval": {"reasons": ["毛利過低", "客戶需求", "折讓超過"]},
    "editHistory": [{"reason": "含金額的理由", "changes": [{"field": "含稅總額", "from": 1, "to": 2}, {"field": "客戶", "from": "a", "to": "b"}]}],
    "caseRecord": {"payment": {"items": [{"amount": 1, "pct": 50, "actualAmount": 1, "feeAmount": 0, "feeNote": "n",
                                          "invoicePretax": 1, "invoiceTax": 0, "name": "頭期款"}], "received": 500},
                   "materialOrders": [{"unitPrice": 1, "totalPrice": 2, "paidAmount": 0, "totalAmount": 2, "name": "線材"}]},
}


def test_masked_sample_document_is_identical_with_flags_from_the_policy_or_from_the_old_table(finance_env):
    """整份輸出逐位元相等：旗標由 `mask_flags` 產生 vs 旗標由舊規則表手算。"""
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for uid in (None, 1, 2, 4):
                u = _user(role, "[]", uid)
                via_policy = FM.mask_quotation_data(copy.deepcopy(_SAMPLE), keep_orders=FP.mask_flags(u)["keep_orders"],
                                                    keep_quote=FP.mask_flags(u)["keep_quote"])
                via_table = FM.mask_quotation_data(copy.deepcopy(_SAMPLE), keep_orders=_expected("material_money", role, mode, uid),
                                                   keep_quote=_expected("quote_money", role, mode, uid))
                assert json.dumps(via_policy, ensure_ascii=False, sort_keys=True) == json.dumps(via_table, ensure_ascii=False, sort_keys=True)


def test_catalog_gaps_are_registered_without_touching_the_key_lists():
    """S1a 補登記的非『鍵』遮蔽：存在、種類正確、不進 API 鍵清單（S0 金標已證明鍵清單不變）。"""
    want = {"settlement.amounts": "subtree", "payment.received_legacy": "subtree", "edit_history.reason": "text",
            "edit_history.reopen_reason": "text", "edit_history.changes": "text", "approval.reasons": "text", "quote_pdf.internal": "document"}
    for fid, kind in want.items():
        f = FC.by_id(fid)
        assert f and f["kind"] == kind and f["api"] is None, fid
    assert FC.by_id("quote_pdf.internal")["exceptions"] == ("case_approver",)
    assert FC.by_id("edit_history.reopen_reason")["ceiling"] == "finance_money"      # 端點用 money_visible（quotations.py 的歷史端點）
    assert FC.by_id("edit_history.reason")["ceiling"] == "quote_money"               # mask_quotation_data 的 not keep_quote 分支
    assert FC.problems() == []
    assert all(f["kind"] == "key" for f in FC.FIELDS if f["api"])


def test_positive_control_problems_rejects_a_non_key_entry_with_an_api_name(monkeypatch):
    bad = dict(FC.by_id("settlement.amounts"), api=("payment", "amount2"))
    monkeypatch.setattr(FC, "FIELDS", tuple(FC.FIELDS) + (bad,))
    assert any("非 key 種類不可有 API 鍵名" in m for m in FC.problems())


def test_exit_short_circuit_is_not_modelled_by_visible_and_mask_flags_keeps_it(finance_env):
    """出口（quotations.py 讀單）先看 money_visible：為真就整份不遮。持有 cashier 模組的工程師 money=True，
    但 visible('quote_item.cost') 為 False（較窄、fail-closed）。出口遷移必須用 mask_flags()['money'] 保留短路。"""
    finance_env["mode"] = "off"
    u = _user("engineer", '["cashier"]', None)
    assert FM.money_visible(u) is True and FM.quote_money_visible(u) is False
    flags = FP.mask_flags(u)
    assert flags["money"] is True and flags["keep_quote"] is False
    assert FP.visible("quote_item.cost", u) is False


def _exit_masks(flags, doc):
    """出口今天的流程（quotations.py:1357-1360）：money 為真就不遮；否則 mask_quotation_data(keep_orders, keep_quote)。"""
    if not flags["money"]:
        FM.mask_quotation_data(doc, keep_orders=flags["keep_orders"], keep_quote=flags["keep_quote"])
    return doc


def test_exit_level_cells_old_calls_equal_flags_from_the_policy(finance_env):
    """出口層級格子：同一個流程，旗標一邊來自四支舊函式、一邊來自 mask_flags，整份輸出逐位元相同（含 money 短路的帳號）。"""
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for modules in MODULES:
                for uid in GRANTS:
                    u = _user(role, modules, uid)
                    old = {"money": FM.money_visible(u), "keep_orders": FM.material_money_visible(u), "keep_quote": FM.quote_money_visible(u)}
                    a = _exit_masks(old, copy.deepcopy(_SAMPLE))
                    b = _exit_masks(FP.mask_flags(u), copy.deepcopy(_SAMPLE))
                    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
