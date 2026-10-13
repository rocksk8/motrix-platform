# -*- coding: utf-8 -*-
"""脊柱 E-b 夾具驅動測試（夾具見 _spine_fixtures.py；設計 SPINE-FIXTURES-T57）。含正對照：驅動器本身不會空轉。"""
import copy

import pytest

from core import spine
from tests.platform import _spine_fixtures as F


@pytest.mark.parametrize("c", F.CASES, ids=lambda c: c["id"])
def test_case_gets_the_expected_result(c):
    ok, why = F.run_case(c)
    assert ok, "%s：%s" % (c["id"], why)


@pytest.mark.parametrize("c", F.FUTURE, ids=lambda c: c["id"])
@pytest.mark.xfail(strict=False, reason="設計要求、引擎尚未落地（轉 XPASS ⇒ 把案例搬進 CASES）")
def test_future_checks_the_engine_does_not_do_yet(c):
    ok, why = F.run_case(c)
    assert ok, "%s（需要：%s）：%s" % (c["id"], c["needs"], why)


# ── 正對照：驅動器不是空轉 ───────────────────────────────────────────────────────────

def test_the_case_table_is_not_vacuous():
    ids = [c["id"] for c in F.CASES]
    assert len(ids) == len(set(ids)), "案例編號重複"
    kinds = {c["expect"][0] for c in F.CASES}
    assert kinds == {"ok", "parse", "failed", "pending"}, kinds
    assert sum(1 for c in F.CASES if c["id"].startswith("good_")) >= 8
    assert sum(1 for c in F.CASES if c["id"].startswith("bad_")) >= 25
    assert all(c["id"].startswith(("good_", "bad_")) for c in F.CASES)


def test_runner_rejects_a_good_case_expected_to_fail_and_a_bad_case_expected_to_pass():
    good = next(c for c in F.CASES if c["id"] == "good_minimal")
    assert F.run_case(good)[0] is True
    assert F.run_case(dict(good, expect=("failed", "不存在的片語")))[0] is False
    assert F.run_case(dict(good, expect=("parse", "任何")))[0] is False
    bad = next(c for c in F.CASES if c["id"] == "bad_mail_not_registered")
    assert F.run_case(bad)[0] is True
    assert F.run_case(dict(bad, expect=("ok",)))[0] is False
    assert F.run_case(dict(bad, expect=("failed", "另一句話")))[0] is False


def test_each_bad_case_fails_for_exactly_the_stated_reason_not_for_a_neighbouring_one():
    """一案一規則：把壞案例的『唯一違規點』補正後必須變好——證明它不是被別的原因擋下。"""
    fixes = {
        "bad_group_not_registered": dict(setup="group_ok"),
        "bad_group_owned_by_another_module": dict(setup="group_ok"),
        "bad_new_money_group_without_impact_scope": dict(setup="group_money"),
        "bad_choices_not_integer": dict(setup="group_ok"),
        "bad_mail_not_registered": dict(setup="mail_owned"),
        "bad_mail_registered_by_another_module": dict(setup="mail_owned"),
        "bad_capability_not_in_module_json": dict(caps=[{"key": "zz_fx.obj.view"}]),
    }
    byid = {c["id"]: c for c in F.CASES}
    for cid, patch in fixes.items():
        fixed = dict(copy.deepcopy(byid[cid]), expect=("ok",), **patch)
        ok, why = F.run_case(fixed)
        assert ok, "%s 補正後仍不通過（可能還有第二個違規點）：%s" % (cid, why)


def test_sandbox_leaves_no_trace():
    before = (sorted(F.R._GROUPS), sorted(F.mail_types._REGISTRY), spine.report()["validated"], len(spine.report()["features"]))
    for cid in ("good_group_owned", "good_mail_owned", "bad_group_shared_by_two_features"):
        F.run_case(next(c for c in F.CASES if c["id"] == cid))
    after = (sorted(F.R._GROUPS), sorted(F.mail_types._REGISTRY), spine.report()["validated"], len(spine.report()["features"]))
    assert before == after


# ── 登錄表驅動：真實樹的宣告全部通過 ────────────────────────────────────────────────────

def test_every_real_declaration_validates_and_the_check_is_not_vacuous(client):
    rep = spine.report()
    if not rep["validated"]:
        rep = spine.validate_all()
    assert rep["features"], "真實樹一個功能宣告都沒有——檢查空轉（正對照）"
    failed = [(f["code"], f["problems"]) for f in rep["features"] if f["state"] == "failed"]
    assert failed == [] and rep["orphans"] == {}, "真實宣告有未通過驗證的項目：%r %r" % (failed, rep["orphans"])
    with F.sandbox():                                              # 正對照：同一份驗證邏輯對故意違規的宣告確實回問題
        spine.register_manifest({"features": [F.feat(mail=["zz_fx_never_registered"])]}, F.OWNER)
        assert spine.validate_all()["problems"] >= 1
