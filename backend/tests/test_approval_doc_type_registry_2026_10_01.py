# -*- coding: utf-8 -*-
"""A2-0 底層預留 #1：簽核單據類型登記（`helpers.tiered_approval.register_doc_type`）。
登記一次 ⇒ 簽核設定頁的套用範圍／獨立流程、scope API、`/api/settings/approval-flow/{code}` 全部認得它；
不必再改 `routers/system.py` 的固定模型。缺欄／多欄／非布林的 PUT 仍是 422（殘缺 body 不可靜默補預設）。
反向控制：把 `_validated_scope` 的缺欄檢查拿掉 ⇒ 「缺登記類型 ⇒ 422」必須紅。"""
import pytest

from helpers import tiered_approval as ta


@pytest.fixture()
def clean_doc_types():
    """就地還原三份表（register_doc_type 是就地修改，舊 import 名稱指向同一物件）。"""
    types, unified, labels = list(ta.APPROVAL_DOC_TYPES), set(ta.DEFAULT_UNIFIED_DOC_TYPES), dict(ta.APPROVAL_DOC_TYPE_LABELS)
    yield
    ta.APPROVAL_DOC_TYPES[:] = types
    ta.DEFAULT_UNIFIED_DOC_TYPES.clear(); ta.DEFAULT_UNIFIED_DOC_TYPES.update(unified)
    ta.APPROVAL_DOC_TYPE_LABELS.clear(); ta.APPROVAL_DOC_TYPE_LABELS.update(labels)


def _tok(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


def test_register_makes_type_visible_everywhere_in_helper(clean_doc_types):
    before = list(ta.APPROVAL_DOC_TYPES)
    ta.register_doc_type("expense_pr", "請購單")
    ta.register_doc_type("expense_po", "採購單", unified=True)
    assert ta.APPROVAL_DOC_TYPES == before + ["expense_pr", "expense_po"]
    assert ta.APPROVAL_DOC_TYPE_LABELS["expense_pr"] == "請購單"
    assert ta.approval_flow_setting_key("expense_pr", {}) == "expense_pr_approval_flow"          # 預設獨立
    assert ta.approval_flow_setting_key("expense_po", {}) == "unified_approval_flow"             # unified=True 預設統一
    assert ta.approval_flow_setting_key("expense_pr", {"expense_pr": True}) == "unified_approval_flow"
    meta = {m["code"]: m for m in ta.doc_types_meta()}
    assert meta["quotation"]["builtin"] and not meta["expense_pr"]["builtin"] and meta["expense_po"]["defaultUnified"]


def test_duplicates_and_bad_input_refused(clean_doc_types):
    ta.register_doc_type("expense_pr", "請購單")
    with pytest.raises(ValueError, match="已登記"):
        ta.register_doc_type("expense_pr", "別人")
    with pytest.raises(ValueError, match="已登記"):
        ta.register_doc_type("quotation", "覆寫內建")
    for bad in ("", "Bad", "1x", "a-b", None):
        with pytest.raises(ValueError, match="不合法"):
            ta.register_doc_type(bad, "x")
    with pytest.raises(ValueError, match="缺少名稱"):
        ta.register_doc_type("okcode", "  ")
    assert "okcode" not in ta.APPROVAL_DOC_TYPES


def test_scope_api_follows_registry(client, make_user, clean_doc_types):
    boss = make_user(username="dt_boss", role="superadmin")
    h = _tok(client, boss)
    ta.register_doc_type("expense_pr", "請購單")
    got = client.get("/api/settings/approval-flow-scope", headers=h).json()
    assert got["expense_pr"] is False and "quotation" in got                                      # GET 含登記的、預設獨立
    assert {"code": "expense_pr", "label": "請購單", "builtin": False, "defaultUnified": False} in         client.get("/api/settings/approval-doc-types", headers=h).json()["docTypes"]
    full = dict(got, expense_pr=True)
    assert client.put("/api/settings/approval-flow-scope", headers=h, json=full).status_code == 200
    assert client.get("/api/settings/approval-flow-scope", headers=h).json()["expense_pr"] is True
    # 殘缺／多餘／非布林 ⇒ 422（不靜默補預設、不靜默丟欄位）
    miss = {k: v for k, v in full.items() if k != "expense_pr"}
    assert client.put("/api/settings/approval-flow-scope", headers=h, json=miss).status_code == 422
    assert client.put("/api/settings/approval-flow-scope", headers=h, json=dict(full, nope=True)).status_code == 422
    assert client.put("/api/settings/approval-flow-scope", headers=h, json=dict(full, expense_pr="yes")).status_code == 422
    assert client.put("/api/settings/approval-flow-scope", headers=h, json=[1]).status_code == 422


def test_per_type_flow_endpoint_knows_registered_type(client, make_user, clean_doc_types):
    boss = make_user(username="dt_boss2", role="superadmin")
    h = _tok(client, boss)
    assert client.get("/api/settings/approval-flow/expense_pr", headers=h).status_code == 404   # 未登記
    ta.register_doc_type("expense_pr", "請購單")
    assert client.get("/api/settings/approval-flow/expense_pr", headers=h).status_code == 200
    assert client.put("/api/settings/approval-flow/expense_pr", headers=h,
                      json={"tiers": [], "includeSubmitterManagerTier": True}).status_code == 200
