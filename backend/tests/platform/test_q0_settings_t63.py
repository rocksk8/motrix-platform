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
    "builder_custom_fields": {"quote_enabled": 0, "quote_in_customer_output": 0, "quote_on_finance_docs": 0},
}
LOOSEN = {("quote_output", "hidden_terms_pdf_mode"): "up", ("builder_custom_fields", "quote_in_customer_output"): "up", ("builder_custom_fields", "quote_on_finance_docs"): "up"}
RISK = {("quote_output", "hidden_terms_pdf_mode"): "legal", ("builder_custom_fields", "quote_in_customer_output"): "legal", ("builder_custom_fields", "quote_on_finance_docs"): "money"}
#: 還沒有使用端的選項（切片 3 才登錄）：登錄了卻什麼都不做的設定不准出貨。
NOT_YET = [("quote_output", "hidden_terms_editor_warning"), ("quote_privacy", "notice_flow_when_hidden")]


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
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-1", json.dumps({"paymentTerms": "月結", "contactEmail": "a@b.c", "customFields": {"x": "1"}}, ensure_ascii=False)))
        c.execute("INSERT INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63Q0-2", json.dumps({"customerName": "甲"}, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    for g, k, num in (("quote_output", "hidden_terms_pdf_mode", "quotationsWithTerms"), ("quote_privacy", "contact_email_hideable", "quotationsWithContacts"),
                      ("builder_custom_fields", "quote_in_customer_output", "quotationsWithCustomFields"),
                      ("builder_custom_fields", "quote_on_finance_docs", "quotationsWithCustomFields")):
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


# ── c2：報價單自訂欄位印在報價單上 ────────────────────────────────────────

CF = {"project_code": "A<b>1</b>", "urgent": True, "note": "", "gone": "舊值"}
FIELDS = [{"key": "project_code", "label": "內部案號", "type": "text"}, {"key": "urgent", "label": "急件", "type": "checkbox"},
          {"key": "note", "label": "備註欄", "type": "text"}]


def _cf_env(monkeypatch, master=1, quote=1, out=1, fields=FIELDS, fin=0):
    from helpers import builtin_fields as BF
    real = SR.get
    vals = {("builder_custom_fields", "enabled"): bool(master), ("builder_custom_fields", "quote_enabled"): quote,
            ("builder_custom_fields", "quote_in_customer_output"): out, ("builder_custom_fields", "quote_on_finance_docs"): fin}
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: vals[(g, f)] if (g, f) in vals else real(g, f, **kw))
    monkeypatch.setattr(BF, "public_fields", lambda rt, conn=None: [dict(f) for f in fields] if rt == "quotation" else [])


def test_c2_default_prints_nothing_even_when_the_quote_has_custom_values(client):
    import pdf_gen
    a = pdf_gen._build_quote_html(_quote(), TOT)
    b = pdf_gen._build_quote_html(_quote(customFields=CF), TOT)
    assert a == b and "其他資訊" not in b


@pytest.mark.parametrize("master,quote,out", [(0, 1, 1), (1, 0, 1), (1, 1, 0), (0, 0, 0)])
def test_c2_needs_master_and_quote_switch_and_the_option(client, monkeypatch, master, quote, out):
    import pdf_gen
    _cf_env(monkeypatch, master, quote, out)
    assert "其他資訊" not in pdf_gen._build_quote_html(_quote(customFields=CF), TOT)


def test_c2_all_on_prints_filled_active_fields_escaped_in_pdf_preview_and_internal(client, monkeypatch):
    import pdf_gen
    base = pdf_gen._build_quote_html(_quote(), TOT)
    _cf_env(monkeypatch)
    for html in (pdf_gen._build_quote_html(_quote(customFields=CF), TOT), pdf_gen._build_quote_html(_quote(customFields=CF), TOT, internal=True),
                 pdf_gen.build_quote_preview_html(_quote(customFields=CF, tot=TOT), "草稿", "")):
        assert "其他資訊" in html and "內部案號" in html and "急件" in html and "是" in html
        assert "A<b>1</b>" not in html and "A&lt;b&gt;1&lt;/b&gt;" in html, "值要跳脫"
        assert "備註欄" not in html, "沒填的欄位不印"
        assert "舊值" not in html, "不在已發布定義裡（已移除／停用）的欄位不印"
        assert "NT$ 210" in html, "金額不變"
    assert "其他資訊" not in base


def test_c2_without_any_filled_value_adds_no_block(client, monkeypatch):
    import pdf_gen
    _cf_env(monkeypatch)
    assert "其他資訊" not in pdf_gen._build_quote_html(_quote(customFields={"note": ""}), TOT)
    assert "其他資訊" not in pdf_gen._build_quote_html(_quote(customFields="oops"), TOT)


def test_c2_read_failure_means_no_block(client, monkeypatch):
    import pdf_gen
    _cf_env(monkeypatch)
    from helpers import builtin_fields as BF
    monkeypatch.setattr(BF, "public_fields", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "其他資訊" not in pdf_gen._build_quote_html(_quote(customFields=CF), TOT)


def test_c2_dependency_message_and_pending_loosening(client):
    bad = _msgs("builder_custom_fields", {"quote_in_customer_output": 1})
    assert bad and "報價單自訂欄位" in bad[0]
    _set("builder_custom_fields", {"enabled": True, "quote_enabled": 1})
    import db
    c = db.get_db()
    try:
        r = SR.publish("builder_custom_fields", {"quote_in_customer_output": 1}, reason="t", user="t63", conn=c)
        c.commit()
        assert r["pending"] and SR.get("builder_custom_fields", "quote_in_customer_output", conn=c) == 0
    finally:
        c.close()


# ── c3：財務文件（請款單、開票申請憑據） ──────────────────────────────────

def _seed_quote(quote_no="T63-Q0-FIN", customs=None):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, data_json) VALUES (?,?)", (quote_no, json.dumps({"customFields": customs if customs is not None else CF}, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    return quote_no


def _fin_docs(qn):
    import pdf_gen
    pr = pdf_gen._build_payment_request_html({"requestNo": "PR-1", "status": "已核准", "quoteNo": qn, "amount": 100})
    iv = pdf_gen._build_invoice_voucher_html({"voucherNo": "IV-1", "status": "已核准", "scope": "amount", "amount": 100, "quoteNo": qn,
                                              "approval": {"requestedByDisplay": "", "requestedAt": ""}, "createdBy": "x", "createdAt": ""})
    return pr, iv


def test_c3_default_changes_neither_finance_document(client, monkeypatch):
    qn = _seed_quote()
    base = _fin_docs("NO-SUCH-QUOTE")
    _cf_env(monkeypatch, fin=0)
    pr, iv = _fin_docs(qn)
    assert "其他資訊（報價單）" not in pr and "其他資訊（報價單）" not in iv
    assert pr == base[0].replace("NO-SUCH-QUOTE", qn) and iv == base[1].replace("NO-SUCH-QUOTE", qn)


@pytest.mark.parametrize("master,quote,out,fin", [(0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 1, 0)])
def test_c3_needs_all_three_switches(client, monkeypatch, master, quote, out, fin):
    qn = _seed_quote()
    _cf_env(monkeypatch, master, quote, out, fin=fin)
    pr, iv = _fin_docs(qn)
    assert "其他資訊（報價單）" not in pr and "其他資訊（報價單）" not in iv


def test_c3_all_on_appends_escaped_read_only_rows_and_leaves_money_alone(client, monkeypatch):
    qn = _seed_quote()
    off = _fin_docs(qn)
    _cf_env(monkeypatch, fin=1)
    pr, iv = _fin_docs(qn)
    for html in (pr, iv):
        assert "其他資訊（報價單）" in html and "內部案號" in html and "急件" in html
        assert "A<b>1</b>" not in html and "A&lt;b&gt;1&lt;/b&gt;" in html
        assert "備註欄" not in html and "舊值" not in html
    import re
    for a, b in zip(off, (pr, iv)):
        money_a, money_b = re.findall(r"NT\$ [\d,]+", a), re.findall(r"NT\$ [\d,]+", b)
        assert money_a and money_a == money_b, "金額列逐項不變"


def test_c3_unknown_quote_or_broken_json_or_read_failure_adds_nothing(client, monkeypatch):
    _cf_env(monkeypatch, fin=1)
    assert all("其他資訊（報價單）" not in h for h in _fin_docs("NO-SUCH-QUOTE"))
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, data_json) VALUES (?,?)", ("T63-Q0-BAD", "{not json"))
        c.commit()
    finally:
        c.close()
    assert all("其他資訊（報價單）" not in h for h in _fin_docs("T63-Q0-BAD"))
    from helpers import builtin_fields as BF
    monkeypatch.setattr(BF, "public_fields", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert all("其他資訊（報價單）" not in h for h in _fin_docs(_seed_quote()))


def test_c3_does_not_query_the_database_when_the_option_is_off(client, monkeypatch):
    from helpers import builtin_fields as BF
    _cf_env(monkeypatch, fin=0)
    monkeypatch.setattr(BF, "_open", lambda conn: (_ for _ in ()).throw(AssertionError("選項沒開不該查資料庫")))
    assert BF.finance_rows("ANY") == []


def test_c3_dependency_message_and_money_pending(client):
    bad = _msgs("builder_custom_fields", {"quote_on_finance_docs": 1})
    assert bad and "報價單自訂欄位" in bad[0]
    _set("builder_custom_fields", {"enabled": True, "quote_enabled": 1})
    import db
    c = db.get_db()
    try:
        r = SR.publish("builder_custom_fields", {"quote_on_finance_docs": 1}, reason="t", user="t63", conn=c)
        c.commit()
        assert r["pending"] and SR.get("builder_custom_fields", "quote_on_finance_docs", conn=c) == 0
    finally:
        c.close()
    assert _fields("builder_custom_fields")["quote_on_finance_docs"].risk == "money"
