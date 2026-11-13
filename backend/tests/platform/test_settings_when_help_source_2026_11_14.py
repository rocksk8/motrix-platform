# -*- coding: utf-8 -*-
"""S1c：`SettingDef.when`／`external`、`field_views` 的 `helpParts`（「？」四段）與 `source`（來源徽章）。"""
import pytest

from db import get_db
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

G = "zz_hsrc_s1c"


@pytest.fixture()
def grp(client, make_user):
    make_user(username="hs_b", role="superadmin")
    c = get_db()
    R.invalidate()
    R.register_group(G, "說明與來源測試群組", [
        R.SettingDef("cap", "int", 10, min=1, max=1000, risk="security", loosen="up", question="上限要設多少？", label="上限",
                     help="測試用的上限。", when="想讓更多人一次操作時。", impact="影響之後的操作，調大屬放寬。", risk_text="調大後門檻變低。",
                     recommended=10, external="要先在外部系統開通"),
        R.SettingDef("days", "int", 5, min=1, max=100, question="提醒幾天前寄？", label="提醒天數", help="測試用。", impact="只影響提醒時間。"),
    ], help="測試用的設定群組。", risk="security")
    yield c
    R._GROUPS.pop(G, None)
    R.clear_edition_bounds()
    c.close()
    R.invalidate()


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_when_must_not_equal_help():
    ok = dict(question="這項要設多少？", label="測試項目", impact="影響測試用的畫面。")
    with pytest.raises(ValueError, match="when"):                                      # 必須是 when 規則擋下，不是別的必填欄位缺漏
        R.SettingDef("x", "int", 1, help="一樣的話。", when="一樣的話。", **ok)
    assert R.SettingDef("x", "int", 1, help="這個。", when="那個。", **ok).when == "那個。"


def test_help_parts_have_four_sections_and_omit_the_empty_ones(grp):
    v = _by_key(R.field_views(G, conn=grp))
    p = v["cap"]["helpParts"]
    assert set(p) == {"what", "when", "impact", "recommend"}
    assert "上限要設多少" in p["what"] and "測試用的上限" in p["what"] and p["when"] == "想讓更多人一次操作時。"
    assert "調大後門檻變低" in p["impact"] and p["recommend"]
    assert set(v["days"]["helpParts"]) == {"what", "impact"}                                  # 沒 when、沒建議值 ⇒ 兩段不出現
    assert v["cap"]["when"] == "想讓更多人一次操作時。" and v["cap"]["needsExternal"] == "要先在外部系統開通" and v["days"]["needsExternal"] == ""
    assert isinstance(v["cap"]["help"], str)                                                  # 既有的 help 字串欄位不變


def test_source_kinds_default_company_pending(grp):
    v = _by_key(R.field_views(G, conn=grp))
    assert v["cap"]["source"]["kind"] == "default" and v["days"]["source"]["kind"] == "default"
    R.publish(G, {"days": 8}, reason="公司改的", user="hs_a", conn=grp)
    R.publish(G, {"cap": 50}, reason="放寬等生效", user="hs_a", conn=grp)                    # 放寬 ⇒ 待生效
    v = _by_key(R.field_views(G, conn=grp))
    assert v["days"]["source"] == {"kind": "company", "by": "hs_a", "at": v["days"]["source"]["at"], "reason": "公司改的"} and v["days"]["source"]["at"]
    assert v["cap"]["source"]["kind"] == "pending" and v["cap"]["source"]["reason"] == "放寬等生效"


def test_source_failure_never_breaks_the_page(grp, monkeypatch):
    monkeypatch.setattr(R, "_sources", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    v = _by_key(R.field_views(G, conn=grp))
    assert v["cap"]["source"] is None and v["cap"]["helpParts"]


def test_source_is_found_even_when_a_sibling_field_has_over_1000_rows(grp):
    from helpers import config_ledger as L
    domain = "setting:" + G
    L.record(grp, domain, G, [{"field": "days", "old": 5, "new": 6}], "很久以前改的", "hs_old")
    for i in range(1100):
        L.record(grp, domain, G, [{"field": "cap", "old": i, "new": i + 1}], "雜訊", "hs_noise")
    grp.commit()
    v = _by_key(R.field_views(G, conn=grp))
    assert v["days"]["source"]["kind"] == "company" and v["days"]["source"]["by"] == "hs_old"
