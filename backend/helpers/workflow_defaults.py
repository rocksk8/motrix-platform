# -*- coding: utf-8 -*-
"""內建流程定義 v1（BP-5 P1）：完工單與出貨單的『現行流程』原樣登記（設計 BP5-WORKFLOW-BUILDER-DESIGN-T62.md §4）。

[單位] helper:workflow_defaults    [層] L0（純資料）    [穩定度] 實驗（端點尚未呼叫流程引擎；旗標 builder_workflow 關＝今天的行為）
[不變式] ①每個值對應盤點 BP5-FLOW-INVENTORY-T62.md §2.1 讀到的字面值（狀態名稱、誰可、守門、回呼）；改這裡＝改『基準』，必須同時改黃金重放；
    ②內建版是唯讀基準：`builtin()` 每次回傳深拷貝，呼叫端改不到模組內的資料；
    ③只有 plain 類單據有內建流程定義；金額類在第一期不登記（唯讀基準另案）。
[契約題] backend/tests/test_workflow_grammar_2026_10_14.py
"""
import copy

_STATES = [
    {"id": "draft", "label": "草稿", "tone": "gray", "semantic": "draft"},
    {"id": "pending", "label": "待審核", "tone": "amber", "semantic": "pending"},
    {"id": "in_approval", "label": "簽核中", "tone": "blue", "semantic": "pending"},
    {"id": "approved", "label": "已核准", "tone": "green", "semantic": "approved"},
]


def _t(tid, frm, to, who, reason, guards=(), callbacks=(), log="basic", tier_role=None):
    t = {"id": tid, "from": list(frm), "to": to, "who": who, "reason": reason, "log": log,
         "guards": list(guards), "callbacks": list(callbacks)}
    if tier_role:
        t["tierRole"] = tier_role
    return t


def _standard(doc_type, submit_guards, approve_guards, approve_cbs, revoke_cbs):
    return {
        "docType": doc_type, "origin": "builtin", "version": 1,
        "states": copy.deepcopy(_STATES),
        "transitions": [
            _t("submit", ["draft"], "pending", "admin", "none", submit_guards, ["notify_first_tier", "notify_org_chain"], log="basic"),
            _t("advance", ["pending", "in_approval"], "in_approval", "tier", "optional", [], ["notify_next_tier"], tier_role="step"),
            _t("approve", ["pending", "in_approval"], "approved", "tier", "optional", approve_guards, approve_cbs, tier_role="final"),
            _t("reject", ["pending", "in_approval"], "draft", "tier", "required", [], ["notify_requester"], tier_role="return"),
            _t("revoke", ["approved"], "draft", "admin", "required", ["not_customer_signed"], revoke_cbs),
            _t("signed_toggle", ["approved"], "approved", "admin", "none", ["status_is_approved"], ["notify_module_activity"], log="basic"),
        ],
        "approval": {"required": True, "exemption": None},
        "editLock": {"editableIn": ["draft"]},
        "returnLog": "basic",
    }


_BUILTIN = {
    "completion": _standard("completion", ["has_items", "completion_date_required"], ["no_self_approval"],
                            ["notify_requester", "fire_expense_notify", "notify_module_activity"], ["notify_requester"]),
    "shipping": _standard("shipping", ["has_items", "material_link_check"], ["no_self_approval", "material_link_check", "serials_in_stock"],
                          ["stock_deduct", "gen_pdf", "calendar_push", "notify_requester"], ["stock_return", "notify_requester"]),
}


def doc_types() -> tuple:
    return tuple(_BUILTIN)


def builtin(doc_type):
    """⇒ 內建 v1 流程定義（深拷貝）；沒有內建版 ⇒ None。"""
    d = _BUILTIN.get(doc_type)
    return copy.deepcopy(d) if d is not None else None
