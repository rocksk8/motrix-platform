# -*- coding: utf-8 -*-
"""T63 Q0 切片 1：報價單輸出／個資／自訂欄位開放範圍的設定登錄（預設＝今天；放寬走待核准）。
設計：docs/platform/plans/T63-Q0-SETTINGS-SPEC.md。"""
import json

import pytest

from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

NEW = {
    "quote_output": {"hidden_terms_pdf_mode": 0},
    "quote_privacy": {"contact_email_hideable": 1, "contact_fax_hideable": 1},
    "builder_custom_fields": {"quote_enabled": 0},
}
LOOSEN = {("quote_output", "hidden_terms_pdf_mode"): "up"}
RISK = {("quote_output", "hidden_terms_pdf_mode"): "legal"}
#: 還沒有使用端的選項（切片 3 才登錄）：登錄了卻什麼都不做的設定不准出貨。
NOT_YET = [("quote_output", "hidden_terms_editor_warning"), ("quote_privacy", "notice_flow_when_hidden"),
           ("builder_custom_fields", "quote_in_customer_output"), ("builder_custom_fields", "quote_on_finance_docs")]


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


def test_only_the_terms_option_loosens_and_options_without_a_consumer_are_not_registered():
    loose = {(g, k) for g, d in NEW.items() for k in d if _fields(g)[k].loosen}
    assert loose == set(LOOSEN)
    for g, k in NOT_YET:
        assert k not in _fields(g), "%s.%s 還沒有使用端，不能先登錄" % (g, k)


def test_every_new_option_has_plain_chinese_choices_and_no_raw_keys_in_labels():
    for g, d in NEW.items():
        for k in d:
            f = _fields(g)[k]
            assert f.choices and len(f.choices) == 2
            for txt in (f.question, f.label, f.help, f.impact) + tuple(c[1] + c[2] for c in f.choices):
                assert "_" not in txt and k not in txt and "pdfShow" not in txt


def _msgs(group, values):
    return [(x["message"] if isinstance(x, dict) else x) for x in SR.validate_values(group, values, partial=True)]


def _msgs(group, values):
    return [(x["message"] if isinstance(x, dict) else x) for x in SR.validate_values(group, values, partial=True)]


def test_dependency_check_blocks_the_quote_switch_without_the_master_switch(client):
    bad = _msgs("builder_custom_fields", {"quote_enabled": 1})
    assert bad and "內建畫面的自訂欄位" in bad[0]
    assert _msgs("builder_custom_fields", {"quote_enabled": 1, "enabled": True}) == []
    assert _msgs("builder_custom_fields", {}) == []


def test_dependency_check_reads_the_stored_master_switch_for_a_partial_change(client):
    import db
    c = db.get_db()
    try:
        SR.publish("builder_custom_fields", {"enabled": True}, reason="t", user="t63", conn=c)
        c.commit()
    finally:
        c.close()
    assert _msgs("builder_custom_fields", {"quote_enabled": 1}) == [], "已存的總開關算數，只改一個欄位不該被擋"


def test_loosening_is_pending_and_tightening_is_immediate(client):
    import db
    c = db.get_db()
    try:
        r = SR.publish("quote_output", {"hidden_terms_pdf_mode": 1}, reason="t", user="t63", conn=c)
        c.commit()
        assert r["pending"] and SR.get("quote_output", "hidden_terms_pdf_mode", conn=c) == 0, "放寬＝待生效，現值不變"
        r3 = SR.publish("quote_privacy", {"contact_email_hideable": 0}, reason="t", user="t63", conn=c)
        c.commit()
        assert not r3["pending"] and SR.get("quote_privacy", "contact_email_hideable", conn=c) == 0, "收緊＝立即"
    finally:
        c.close()


def test_impact_functions_count_quotes_and_never_write(client):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-1", json.dumps({"paymentTerms": "月結", "contactEmail": "a@b.c"}, ensure_ascii=False)))
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-2", json.dumps({"customerName": "甲"}, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    for g, k, num in (("quote_output", "hidden_terms_pdf_mode", "quotationsWithTerms"), ("quote_privacy", "contact_email_hideable", "quotationsWithContacts")):
        out = SR.live_impact(g, k, 1)
        assert out["live"] and out["live"]["numbers"][num] >= 1 and "張" in out["live"]["sentence"]


# ── 切片 2：使用端 ───────────────────────────────────────────────────────

TOT = {"subtotal": 200, "pretax": 200, "tax": 10, "total": 210}


def _quote(**over):
    q = {"quoteNo": "T63-Q0-PDF", "customerName": "甲公司", "projectName": "專案", "status": "草稿", "validDays": 30,
         "items": [{"description": "品項", "brand": "", "unit": "式", "qty": 2, "unitPrice": 100, "amount": 200, "type": "item"}],
         "paymentTerms": "PAYTERM_X", "deliveryTerms": "DELTERM_X", "acceptanceTerms": "ACCTERM_X", "warrantyTerms": "WARTERM_X", "afterSales": "AFTERTERM_X"}
    q.update(over)
    return q


def _mode(monkeypatch, value):
    real = SR.get

    def fake(group, field, **kw):
        if (group, field) == ("quote_output", "hidden_terms_pdf_mode"):
            return value
        return real(group, field, **kw)
    monkeypatch.setattr(SR, "get", fake)


def _layout(monkeypatch, hidden, shown=()):
    from core import catalog
    ids = {p["field"]: p["id"] for p in catalog.layout_points("case") if p.get("kind") == "field" and p.get("entity") == "qterms"}
    ops = [{"op": "hide", "target": ids[f]} for f in hidden] + [{"op": "show", "target": ids[f]} for f in shown]
    monkeypatch.setattr(catalog, "effective_layout_ops", lambda conn, mod, role: {"ops": ops, "dropped": [], "source": "t", "error": None})


def test_default_mode_prints_every_term_and_never_reads_the_layout(client, monkeypatch):
    import pdf_gen
    from core import catalog
    monkeypatch.setattr(catalog, "effective_layout_ops", lambda *a, **k: (_ for _ in ()).throw(AssertionError("預設不該讀版面")))
    html = pdf_gen._build_quote_html(_quote(), TOT)
    for w in ("PAYTERM_X", "DELTERM_X", "ACCTERM_X", "WARTERM_X", "AFTERTERM_X"):
        assert w in html


def test_mode_one_omits_only_the_hidden_terms(client, monkeypatch):
    import pdf_gen
    _mode(monkeypatch, 1)
    _layout(monkeypatch, ["warrantyTerms", "afterSales"])
    html = pdf_gen._build_quote_html(_quote(), TOT)
    assert "WARTERM_X" not in html and "AFTERTERM_X" not in html
    for w in ("PAYTERM_X", "DELTERM_X", "ACCTERM_X"):
        assert w in html
    for internal in (False, True):
        assert "WARTERM_X" not in pdf_gen._build_quote_html(_quote(), TOT, internal=internal)


def test_mode_one_a_later_show_cancels_an_earlier_hide(client, monkeypatch):
    import pdf_gen
    _mode(monkeypatch, 1)
    _layout(monkeypatch, ["paymentTerms"], shown=["paymentTerms"])
    assert "PAYTERM_X" in pdf_gen._build_quote_html(_quote(), TOT)


def test_mode_one_without_a_published_layout_prints_everything(client, monkeypatch):
    import pdf_gen
    _mode(monkeypatch, 1)
    html = pdf_gen._build_quote_html(_quote(), TOT)
    assert all(w in html for w in ("PAYTERM_X", "WARTERM_X", "AFTERTERM_X"))


def test_mode_one_layout_read_failure_prints_everything(client, monkeypatch):
    import pdf_gen
    from core import catalog
    _mode(monkeypatch, 1)
    monkeypatch.setattr(catalog, "effective_layout_ops", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "WARTERM_X" in pdf_gen._build_quote_html(_quote(), TOT)


def test_privacy_default_keeps_contact_fields_hideable_and_zero_changes():
    from core import catalog
    pts = {p["field"]: p for p in catalog.layout_points("case") if p.get("kind") == "field" and p.get("entity") == "qcustomer"}
    assert pts["contactEmail"]["core"] is False and pts["contactEmail"]["ops"] == ["move", "hide", "show", "relabel"]
    assert pts["contactFax"]["core"] is False


def test_privacy_not_hideable_makes_the_point_core_and_blocks_hide(client, monkeypatch):
    from core import catalog
    real = SR.get
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 0 if (g, f) == ("quote_privacy", "contact_email_hideable") else real(g, f, **kw))
    pts = {p["field"]: p for p in catalog.layout_points("case") if p.get("kind") == "field" and p.get("entity") == "qcustomer"}
    assert pts["contactEmail"]["core"] is True and pts["contactEmail"]["ops"] == ["move"]
    assert pts["contactFax"]["core"] is False, "只影響設定指定的欄位"
    assert pts["customerName"]["core"] is True
    problems = catalog.check_layout("case", [{"op": "hide", "target": pts["contactEmail"]["id"]}])
    assert problems, "不可隱藏的欄位，隱藏操作被版面守門擋下"


def test_quote_custom_fields_need_master_and_quote_switch(client):
    from helpers import builtin_fields as BF
    assert BF.type_enabled("quotation") is False and BF.type_enabled("case_info") is False
    _set("builder_custom_fields", {"enabled": True})
    assert BF.type_enabled("quotation") is False, "只開總開關 ⇒ 報價單仍關閉"
    assert BF.type_enabled("case_info") is True and BF.type_enabled("supplier") is True, "其他單據類型維持今天的行為"
    _set("builder_custom_fields", {"quote_enabled": 1})
    assert BF.type_enabled("quotation") is True
    _set("builder_custom_fields", {"enabled": False})
    assert BF.type_enabled("quotation") is False, "總開關關閉 ⇒ 報價單也關閉"


def test_quote_custom_fields_read_failure_means_off(client, monkeypatch):
    from helpers import builtin_fields as BF
    _set("builder_custom_fields", {"enabled": True, "quote_enabled": 1})
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert BF.type_enabled("quotation") is False


def _set(group, values):
    import db
    c = db.get_db()
    try:
        SR.publish(group, values, reason="t", user="t63", conn=c)
        c.commit()
    finally:
        c.close()
    SR.invalidate(group)
