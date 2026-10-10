# -*- coding: utf-8 -*-
"""權限矩陣的白話文字：畫面上沒有代碼／英文旗標／id，不用「他／她」，說的是人話（使用者核心規則 2026-10-10）。"""
import json
import re

import pytest

from core import capabilities as C
from helpers import auth as A
from helpers import perm as P
from helpers import perm_text as T

CODE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z_]+|\b(allow|deny|superadmin|delegation|role_grants|pending)\b")


def _d(key, label, legacy, **kw):
    return dict(key=key, label=label, desc=label + "的說明", impact="勾選後可以" + label, legacy=legacy, **kw)


CAPS, PROBLEMS = C.collect({"zz": {"capabilities": [
    _d("zz.slip.submit", "送出勞報單", {"superadmin": True}),
    _d("zz.slip.view", "查看勞報單", {"module": "payslip"}),
    _d("zz.slip.edit", "修改勞報單", {"role": ["admin"]}, question="{who}可以修改勞報單嗎？", recommended=["admin", "finance"]),
    _d("zz.slip.pay", "登錄勞報單付款", {"role": ["finance"]}),
]}}, valid_roles=A.VALID_ROLES)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "text-test")
    monkeypatch.setattr(A, "_finance_mode", lambda: "off")
    monkeypatch.setattr(P, "_source", None)
    monkeypatch.setattr(P, "_provider", lambda: None)
    monkeypatch.setattr(T, "role_label", lambda r: T.ROLE_LABELS_DEFAULT.get(r) or "（未命名角色）")
    P.invalidate()
    yield


def _u(role, modules=(), uid=5, name="王小明", username="xm"):
    return {"id": uid, "username": username, "display_name": name, "role": role, "modules": json.dumps(list(modules))}


def test_default_role_labels_equal_the_ones_the_role_label_settings_page_uses():
    from routers.system import _DEFAULT_ROLE_LABELS
    assert T.ROLE_LABELS_DEFAULT == _DEFAULT_ROLE_LABELS and set(T.ROLE_LABELS_DEFAULT) == set(A.VALID_ROLES)


def test_questions_and_role_sentences_read_like_people_talk():
    assert T.question("zz.slip.submit", "財務") == "財務可以送出勞報單嗎？"
    assert T.question("zz.slip.edit", "管理員") == "管理員可以修改勞報單嗎？"
    assert T.sentence_role_cap("finance", "zz.slip.submit", True) == "財務可以送出勞報單"
    assert T.sentence_role_cap("finance", "zz.slip.submit", False) == "財務不能送出勞報單"
    assert T.sentence_user_override("王小明", "zz.slip.pay", True) == "王小明特別可以登錄勞報單付款（只針對這一位）"
    assert CAPS["zz.slip.edit"].recommended == frozenset({"admin", "finance"}) and CAPS["zz.slip.submit"].recommended == frozenset()


def test_delegation_summary_sentence_matches_the_users_example():
    s = T.sentence_delegation("李主任", "王小明", ["zz.slip.submit", "zz.slip.edit"], "2031-11-30", 24)
    assert s == "你即將讓王小明代理李主任：送出勞報單、修改勞報單，到 11/30，24 小時後生效"
    assert T.sentence_delegation("李主任", "王小明", ["zz.slip.view"], "", 0) == "你即將讓王小明代理李主任：查看勞報單，儲存後立即生效"


def test_explain_text_for_every_source_is_a_plain_sentence():
    assert T.explain_text(_u("superadmin"), "zz.slip.submit") == "王小明是最高管理者，所有事情都可以做。"
    assert T.explain_text(_u("admin"), "zz.slip.edit") == "王小明可以修改勞報單：「管理員」這個角色有勾選。"
    assert T.explain_text(_u("viewer", ["payslip"]), "zz.slip.view") == "王小明可以查看勞報單：已開通「勞報單」功能。"
    assert T.explain_text(_u("viewer"), "zz.slip.submit") == "王小明目前不能送出勞報單。"
    P.set_matrix_source(lambda: P.Matrix(allow={5: frozenset({"zz.slip.edit"})}))
    assert T.explain_text(_u("viewer"), "zz.slip.edit") == "王小明可以修改勞報單：管理者特別允許了這一位。"
    P.set_matrix_source(lambda: P.Matrix(role_grants=P.seed_from_legacy(CAPS).role_grants, deny={5: frozenset({"zz.slip.edit"})}))
    assert T.explain_text(_u("admin"), "zz.slip.edit") == "王小明不能修改勞報單：管理者特別禁止了這一位。"
    assert T.explain_text(_u("viewer"), "zz.nope.view") == "找不到這項功能。"


def test_risk_hint_only_for_high_risk_and_says_the_24h_rule_in_words():
    caps = C.collect({"zz": {"capabilities": [_d("zz.slip.approve", "核准勞報單", {"superadmin": True}), _d("zz.slip.comment", "留言", {"role": ["admin"]})]}}, valid_roles=A.VALID_ROLES)[0]
    CAPS.update(caps)
    h = T.risk_hint("zz.slip.approve")
    assert "高風險" in h and "24 小時" in h and "撤銷" in h and T.risk_hint("zz.slip.comment") == "" and T.risk_hint("zz.nope.x") == ""


def test_render_scan_no_code_no_english_flags_no_pronouns_in_any_output():
    outs = []
    for k in CAPS:
        outs += [T.question(k, "財務"), T.sentence_role_cap("finance", k, True), T.sentence_role_cap("viewer", k, False), T.sentence_user_override("王小明", k, True),
                 T.risk_hint(k), CAPS[k].desc, CAPS[k].impact, CAPS[k].label]
        for role in A.VALID_ROLES:
            outs.append(T.explain_text(_u(role, ["payslip"]), k))
    outs.append(T.sentence_delegation("李主任", "王小明", list(CAPS), "2031-11-30", 24))
    outs += [T.role_label(r) for r in A.VALID_ROLES] + [T.action_label(a) for a in C.ACTIONS]
    for o in outs:
        assert not CODE.search(o), "畫面文字不得露出代碼或英文旗標：%r" % o
        assert "他" not in o and "她" not in o, "不用代名詞：%r" % o
    assert all(T.action_label(a) != "（未命名動作）" for a in C.ACTIONS)
    assert T.role_label("nobody") == "（未命名角色）" and T.module_label("no_such") == "（未命名功能）", "對不到名稱時不露出代碼"
