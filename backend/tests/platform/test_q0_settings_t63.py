# -*- coding: utf-8 -*-
"""T63 Q0 切片 1：報價單輸出／個資／自訂欄位開放範圍的設定登錄（預設＝今天；放寬走待核准）。
設計：docs/platform/plans/T63-Q0-SETTINGS-SPEC.md。"""
import json

import pytest

from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

NEW = {
    "quote_output": {"hidden_terms_pdf_mode": 0, "hidden_terms_editor_warning": 1},
    "quote_privacy": {"contact_email_hideable": 1, "contact_fax_hideable": 1, "notice_flow_when_hidden": 1},
    "builder_custom_fields": {"quote_enabled": 0, "quote_in_customer_output": 0, "quote_on_finance_docs": 0},
}
LOOSEN = {("quote_output", "hidden_terms_pdf_mode"): "up", ("quote_privacy", "notice_flow_when_hidden"): "down",
          ("builder_custom_fields", "quote_in_customer_output"): "up", ("builder_custom_fields", "quote_on_finance_docs"): "up"}
RISK = {("quote_output", "hidden_terms_pdf_mode"): "legal", ("quote_privacy", "notice_flow_when_hidden"): "legal",
        ("builder_custom_fields", "quote_in_customer_output"): "legal", ("builder_custom_fields", "quote_on_finance_docs"): "money"}


def _fields(group):
    return SR._g(group)["fields"]


@pytest.mark.parametrize("group,defaults", list(NEW.items()))
def test_defaults_are_todays_behavior_and_are_core_owned(group, defaults):
    f = _fields(group)
    for k, v in defaults.items():
        assert f[k].default == v and f[k].type == "int" and (f[k].min, f[k].max) == (0, 1)
    assert SR.groups()[group]["owner"] == "core"


def test_the_master_flag_is_untouched():
    f = _fields("builder_custom_fields")["enabled"]
    assert f.type == "bool" and f.default is False


@pytest.mark.parametrize("key,direction", list(LOOSEN.items()))
def test_loosen_direction_and_risk_match_the_spec(key, direction):
    f = _fields(key[0])[key[1]]
    assert f.loosen == direction and f.risk == RISK[key] and f.impact_scope and f.impact_scope["effective"] == "pending" and f.risk_text


def test_money_option_is_the_only_money_risk_and_has_no_other_loosening_options():
    loose = {(g, k) for g, d in NEW.items() for k in d if _fields(g)[k].loosen}
    assert loose == set(LOOSEN)
    assert {(g, k) for g, d in NEW.items() for k in d if _fields(g)[k].risk == "money"} == {("builder_custom_fields", "quote_on_finance_docs")}


def test_every_new_option_has_plain_chinese_choices_and_no_raw_keys_in_labels():
    for g, d in NEW.items():
        for k in d:
            f = _fields(g)[k]
            assert f.choices and len(f.choices) == 2
            for txt in (f.question, f.label, f.help, f.impact) + tuple(c[1] + c[2] for c in f.choices):
                assert "_" not in txt and k not in txt and "pdfShow" not in txt


def _msgs(group, values):
    return [(x["message"] if isinstance(x, dict) else x) for x in SR.validate_values(group, values, partial=True)]


def test_dependency_check_blocks_unmet_options_with_plain_text(client):
    bad = _msgs("builder_custom_fields", {"quote_enabled": 1})
    assert bad and "內建畫面的自訂欄位" in bad[0]
    assert _msgs("builder_custom_fields", {"quote_enabled": 1, "enabled": True}) == []
    bad2 = _msgs("builder_custom_fields", {"enabled": True, "quote_in_customer_output": 1})
    assert bad2 and "報價單自訂欄位" in bad2[0]
    bad3 = _msgs("builder_custom_fields", {"enabled": True, "quote_on_finance_docs": 1})
    assert bad3 and "報價單自訂欄位" in bad3[0]
    assert _msgs("builder_custom_fields", {}) == []


def test_dependency_check_reads_the_stored_values_for_a_partial_change(client):
    import db
    c = db.get_db()
    try:
        SR.publish("builder_custom_fields", {"enabled": True, "quote_enabled": 1}, reason="t", user="t63", conn=c)
        c.commit()
    finally:
        c.close()
    assert _msgs("builder_custom_fields", {"quote_on_finance_docs": 1}) == [], "已存的總開關與報價單開關算數，只改一個欄位不該被擋"
    assert _msgs("builder_custom_fields", {"quote_in_customer_output": 1}) == []


def test_loosening_is_pending_and_tightening_is_immediate(client):
    import db
    c = db.get_db()
    try:
        r = SR.publish("quote_output", {"hidden_terms_pdf_mode": 1}, reason="t", user="t63", conn=c)
        c.commit()
        assert r["pending"] and SR.get("quote_output", "hidden_terms_pdf_mode", conn=c) == 0, "放寬＝待生效，現值不變"
        r2 = SR.publish("quote_privacy", {"notice_flow_when_hidden": 0}, reason="t", user="t63", conn=c)
        c.commit()
        assert r2["pending"] and SR.get("quote_privacy", "notice_flow_when_hidden", conn=c) == 1
        r3 = SR.publish("quote_privacy", {"contact_email_hideable": 0}, reason="t", user="t63", conn=c)
        c.commit()
        assert not r3["pending"] and SR.get("quote_privacy", "contact_email_hideable", conn=c) == 0, "收緊＝立即"
        r4 = SR.publish("quote_output", {"hidden_terms_editor_warning": 0}, reason="t", user="t63", conn=c)
        c.commit()
        assert not r4["pending"]
    finally:
        c.close()


def test_finance_option_loosening_is_pending_even_when_dependencies_are_met(client):
    import db
    c = db.get_db()
    try:
        SR.publish("builder_custom_fields", {"enabled": True, "quote_enabled": 1}, reason="t", user="t63", conn=c)
        c.commit()
        r = SR.publish("builder_custom_fields", {"quote_on_finance_docs": 1}, reason="t", user="t63", conn=c)
        c.commit()
        assert r["pending"] and SR.get("builder_custom_fields", "quote_on_finance_docs", conn=c) == 0
    finally:
        c.close()


def test_impact_functions_count_quotes_and_never_write(client):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-1", json.dumps({"paymentTerms": "月結", "contactEmail": "a@b.c", "customFields": {"x": "1"}}, ensure_ascii=False)))
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-2", json.dumps({"customerName": "甲"}, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    for g, k, num in (("quote_output", "hidden_terms_pdf_mode", "quotationsWithTerms"), ("quote_privacy", "contact_email_hideable", "quotationsWithContacts"),
                      ("builder_custom_fields", "quote_in_customer_output", "quotationsWithCustomFields"), ("builder_custom_fields", "quote_on_finance_docs", "quotationsWithCustomFields")):
        out = SR.live_impact(g, k, 1)
        assert out["live"] and out["live"]["numbers"][num] >= 1 and "張" in out["live"]["sentence"]
