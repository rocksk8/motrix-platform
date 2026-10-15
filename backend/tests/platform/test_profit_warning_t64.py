# -*- coding: utf-8 -*-
"""T64 A：利潤顏色門檻（profit_warning）與新報價單預設有效天數（quote_defaults）。預設＝各畫面原本寫死的數字（部署零行為變更）。"""
import json
import pathlib
import re

import pytest

from helpers import profit_warning as PW
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

#: 各畫面上線前寫死的數字（來源：quotation-form 1992-1997、reports 1566／2208、case-management 2852／2893／2813、settlement 1021、pdf_gen 結算表）
LEGACY = {"quote_form_low": 12, "quote_form_good": 20, "report_low": 10, "report_good": 20, "case_floor": 0, "case_good": 20, "settlement_good": 20}
FRONT = pathlib.Path(__file__).resolve().parents[3] / "frontend"
BACK = pathlib.Path(__file__).resolve().parents[2]


def _f(g):
    return SR._g(g)["fields"]


def test_settings_defaults_equal_legacy():
    f = _f("profit_warning")
    assert set(f) == set(LEGACY)
    for k, v in LEGACY.items():
        assert f[k].default == v and f[k].type == "float" and f[k].risk == "none" and not f[k].loosen
    assert PW.DEFAULTS == {k: float(v) for k, v in LEGACY.items()}
    assert _f("quote_defaults")["valid_days"].default == PW.DEFAULT_VALID_DAYS == 30
    assert SR.groups()["profit_warning"]["owner"] == "core" and SR.groups()["quote_defaults"]["owner"] == "core"


def test_valid_days_impact_text_warns_about_a_lower_cap_and_the_cap_text_warns_back():
    assert "上限" in _f("quote_defaults")["valid_days"].impact and "有效期限過長" in _f("quote_defaults")["valid_days"].impact
    assert "新報價單預設有效天數" in _f("quote_approval")["max_valid_days"].impact


def test_valid_days_default_does_not_exceed_the_approval_cap_default():
    assert _f("quote_defaults")["valid_days"].default <= _f("quote_approval")["max_valid_days"].default


def test_labels_are_plain_chinese_and_say_display_only():
    for k, f in _f("profit_warning").items():
        for txt in (f.question, f.label, f.help, f.impact):
            assert "_" not in txt and k not in txt
        assert "不影響存檔" in f.impact and "立即生效" in f.impact


def test_js_defaults_match_python_defaults():
    src = (FRONT / "static" / "profit-warning.js").read_text(encoding="utf-8")
    body = re.search(r"const DEF = \{([^}]*)\}", src).group(1)
    js = {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)", body)}
    assert js == PW.DEFAULTS


def _msgs(group, values):
    return [(x["message"] if isinstance(x, dict) else x) for x in SR.validate_values(group, values, partial=True)]


@pytest.mark.parametrize("lo,hi", [("quote_form_low", "quote_form_good"), ("report_low", "report_good"), ("case_floor", "case_good")])
def test_low_must_not_exceed_good(lo, hi):
    assert _msgs("profit_warning", {lo: 25, hi: 20})
    assert not _msgs("profit_warning", {lo: 5, hi: 20})


def test_cross_check_reads_the_stored_partner_when_only_one_side_is_sent(monkeypatch):
    from helpers import settings_groups_profit as G
    monkeypatch.setattr(SR, "get_group", lambda g, **kw: dict(PW.DEFAULTS, quote_form_good=15.0))
    assert G._profit_cross_check({"quote_form_low": 18})
    assert not G._profit_cross_check({"quote_form_low": 14})


def test_valid_days_cross_check_against_the_stored_cap(monkeypatch):
    from helpers import settings_groups_profit as G
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 20)
    assert G._valid_days_cross_check({"valid_days": 30})
    assert not G._valid_days_cross_check({"valid_days": 20})
    assert not G._valid_days_cross_check({})


def test_bands_fall_back_to_todays_numbers_as_a_whole(monkeypatch):
    bad = [dict(PW.DEFAULTS, quote_form_low=30.0, quote_form_good=20.0), dict(PW.DEFAULTS, report_low=float("nan")),
           dict(PW.DEFAULTS, case_floor=500), dict(PW.DEFAULTS, case_good=True), {}]
    for vals in bad:
        monkeypatch.setattr(SR, "get_group", lambda g, _v=vals, **kw: dict(_v))
        assert PW.bands() == PW.DEFAULTS
    monkeypatch.setattr(SR, "get_group", lambda g, **kw: (_ for _ in ()).throw(RuntimeError("db locked")))
    assert PW.bands() == PW.DEFAULTS


def test_bands_use_stored_values_when_valid(monkeypatch):
    monkeypatch.setattr(SR, "get_group", lambda g, **kw: dict(PW.DEFAULTS, quote_form_low=15.0, case_floor=-5.0))
    b = PW.bands()
    assert b["quote_form_low"] == 15.0 and b["case_floor"] == -5.0 and b["report_low"] == 10.0


def test_default_valid_days_fallbacks(monkeypatch):
    for bad in (0, 366, True, "30", None, float("inf")):
        monkeypatch.setattr(SR, "get", lambda g, f, _b=bad, **kw: _b)
        assert PW.default_valid_days() == 30
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 14)
    assert PW.default_valid_days() == 14
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: (_ for _ in ()).throw(RuntimeError))
    assert PW.default_valid_days() == 30


def test_quotations_fallback_uses_the_setting_not_a_literal():
    src = (BACK / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    assert 'q.get("validDays", 30)' not in src and src.count('q.get("validDays", _pw.default_valid_days())') == 2


def test_no_hardcoded_margin_thresholds_remain_in_the_pages():
    pat = re.compile(r"(?:netMarginPct|NetMarginPct)[^\n]{0,40}?(?:<|>=)\s*(?:12|20|10|0)\b(?!\.)")
    for p in ("pages/quotation-form.html", "pages/reports.html", "pages/case-management.html", "pages/settlement.html"):
        txt = (FRONT / p).read_text(encoding="utf-8")
        hits = [m.group(0) for m in pat.finditer(txt) if "pw." not in m.group(0) and "||0))>=0" not in m.group(0) and "netProfit" not in m.group(0)]       # 「實際 − 預估 ≥ 0」是差額正負，不是門檻
        assert not hits, (p, hits)
    pdf = (BACK / "pdf_gen.py").read_text(encoding="utf-8")
    assert "get('netMarginPct',0) or 0)>=20" not in pdf and "_pw_b['case_good']" in pdf and "_pw_b['case_floor']" in pdf


def test_pages_load_the_shared_script_before_their_app():
    for p in ("pages/quotation-form.html", "pages/reports.html", "pages/case-management.html", "pages/settlement.html"):
        assert "../static/profit-warning.js" in (FRONT / p).read_text(encoding="utf-8"), p


def test_settlement_pdf_colours_follow_the_settings():
    import pdf_gen
    src = pathlib.Path(pdf_gen.__file__).read_text(encoding="utf-8")
    assert "from helpers import profit_warning as _pw" in src


def test_config_endpoint_is_registered_with_the_same_gate():
    src = (BACK / "modules" / "case" / "api" / "project_margin.py").read_text(encoding="utf-8")
    assert '"/api/profit-warning/config"' in src and src.count("quote_money_visible(user)") == 2 and "raise HTTPException(403" not in src.split("def get_profit_warning_config")[1].split("@router")[0]
