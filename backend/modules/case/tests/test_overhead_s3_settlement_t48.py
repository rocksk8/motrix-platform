# -*- coding: utf-8 -*-
"""第 48 班 S3：精算（後端完結比對／補齊）依 `overhead_rule_mode` 走舊（稅前×10%）或新（實際毛利×報價單比率）口徑，v2 完結時蓋 formulaVer／overheadPct。
報價稅前 100000（_set_tot）；比率取報價單 `tot.overheadPct`（沒有＝全域預設 25）。"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import QUOTED_PRETAX, _set_tot, page_payload
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  完結要已成案（autouse）

URL = "/api/quotations/%s/settlement" % NO


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    cn = db.get_db()
    try:
        cn.execute("DELETE FROM system_settings WHERE key='overhead_rule_mode'")
        cn.commit()
    finally:
        cn.close()


def _mode(mode, pct=None):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES ('overhead_rule_mode', ?, '2031-01-01T00:00:00') "
                   "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (json.dumps(mode),))
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        if pct is not None:
            d["tot"]["overheadPct"] = pct
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def _saved_summary():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["summary"]
    finally:
        cn.close()


def _v2_payload(c, h, pct):
    """照新口徑組完結 payload：管銷＝max(實際毛利,0)×比率；公益金／營業利益隨之。"""
    p = page_payload(c, h)
    s = p["summary"]
    gross = s["grossProfit"]
    admin = SA.round_half_up(max(gross, 0), str(pct / 100))
    charity = max(0, SA.round_half_up(gross, 0.01))                # 公益金不為負（第 39 班）
    net = gross - admin - charity
    s.update(adminCost=admin, charityDonation=charity, netProfit=net, netMarginPct=round(net / QUOTED_PRETAX * 100, 1), formulaVer=2, overheadPct=pct)
    return p


def test_v2_finalize_accepts_new_basis_and_stamps_version_and_pct(W):
    c, h = W
    _set_tot()
    _mode("v2", pct=20)
    p = _v2_payload(c, h, 20)
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert s["formulaVer"] == 2 and s["overheadPct"] == 20
    assert s["adminCost"] == SA.round_half_up(max(s["grossProfit"], 0), "0.20") and s["netProfit"] == s["grossProfit"] - s["adminCost"] - s["charityDonation"]


def test_v2_mode_refuses_the_old_10_percent_summary(W):
    c, h = W
    _set_tot()
    _mode("v2", pct=25)
    p = page_payload(c, h)                                        # 舊口徑：管銷＝稅前×10%＝10000，與新口徑（毛利×25%）差很多
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 409 and "管銷分攤" in r.text, r.text


def test_legacy_mode_unchanged_and_no_stamp(W):
    c, h = W
    _set_tot()
    _mode("legacy")
    r = c.put(URL, json={"settlement": page_payload(c, h)}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert "formulaVer" not in s and "overheadPct" not in s
    assert s["adminCost"] == SA.round_half_up(QUOTED_PRETAX, 0.10)


def test_v2_negative_gross_has_zero_admin(W):
    c, h = W
    _set_tot()
    _mode("v2", pct=25)
    from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
    _dispatch(150000, 0)                                           # 總成本遠大於稅前 100000 ⇒ 實際毛利為負
    p = _v2_payload(c, h, 25)
    assert p["summary"]["grossProfit"] < 0 and p["summary"]["adminCost"] == 0
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 200, r.text
    assert _saved_summary()["adminCost"] == 0


def test_reopen_and_refinalize_restamps_with_the_current_basis(W):
    """Q6：已完結案重新開啟再完結 ⇒ 用目前口徑重算並重新蓋戳記（legacy→v2 蓋上、v2→legacy 拿掉）。"""
    c, h = W
    _set_tot()
    _mode("legacy")
    assert c.put(URL, json={"settlement": page_payload(c, h)}, headers=h).status_code == 200
    assert "formulaVer" not in _saved_summary()
    _mode("v2", pct=20)
    r = c.put(URL, json={"settlement": _v2_payload(c, h, 20), "reason": "改用新口徑重算"}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert s["formulaVer"] == 2 and s["overheadPct"] == 20
    _mode("legacy")
    r = c.put(URL, json={"settlement": page_payload(c, h), "reason": "還原舊口徑"}, headers=h)
    assert r.status_code == 200, r.text
    s = _saved_summary()
    assert "formulaVer" not in s and "overheadPct" not in s and s["adminCost"] == SA.round_half_up(QUOTED_PRETAX, 0.10)


def test_server_stamps_even_when_the_page_omits_the_stamp(W):
    """頁面沒送 formulaVer／overheadPct（舊頁面）⇒ 伺服器補齊（fill_downstream），報價單比率取 tot.overheadPct。"""
    c, h = W
    _set_tot()
    _mode("v2", pct=30)
    p = _v2_payload(c, h, 30)
    p["summary"].pop("formulaVer"), p["summary"].pop("overheadPct")
    assert c.put(URL, json={"settlement": p}, headers=h).status_code == 200
    s = _saved_summary()
    assert s["formulaVer"] == 2 and s["overheadPct"] == 30


def test_bonus_row_label_follows_the_stamp_written_at_finalize(W):
    """獎金精算明細表的管銷列標籤（b5 的 bonus.row_label）讀完結時蓋的 formulaVer／overheadPct：legacy 無戳記＝報價稅前 10%；v2＝直接毛利 N%（每案比率）。"""
    from modules.payroll import bonus
    c, h = W
    _set_tot()
    _mode("legacy")
    assert c.put(URL, json={"settlement": page_payload(c, h)}, headers=h).status_code == 200
    legacy = bonus.row_label("adminCost", "管銷分攤", _saved_summary())
    assert "10%" in legacy and "報價稅前" in legacy, legacy
    _mode("v2", pct=30)
    assert c.put(URL, json={"settlement": _v2_payload(c, h, 30), "reason": "新口徑"}, headers=h).status_code == 200
    new = bonus.row_label("adminCost", "管銷分攤", _saved_summary())
    assert "30%" in new and "直接毛利" in new and "報價稅前" not in new, new


def test_original_side_stamp_comes_only_from_the_quotation(W):
    """完結時 summary 同時蓋 formulaVer／overheadPct 與原始側 origFormulaVer／origOverheadPct（報價是新口徑才有）；用戶端偽造的原始側戳記丟掉。"""
    c, h = W
    _set_tot()
    _mode("v2", pct=20)
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["tot"]["formulaVer"] = 2
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    assert c.put(URL, json={"settlement": _v2_payload(c, h, 20)}, headers=h).status_code == 200
    s = _saved_summary()
    assert (s["formulaVer"], s["overheadPct"], s["origFormulaVer"], s["origOverheadPct"]) == (2, 20, 2, 20)
    # 舊口徑報價（沒有 formulaVer）＋用戶端偽造原始側戳記 ⇒ 伺服器拿掉
    cn = db.get_db()
    d["tot"].pop("formulaVer")
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    p = _v2_payload(c, h, 20)
    p["summary"].update(origFormulaVer=2, origOverheadPct=99)
    assert c.put(URL, json={"settlement": p, "reason": "x"}, headers=h).status_code == 200
    s = _saved_summary()
    assert "origFormulaVer" not in s and "origOverheadPct" not in s
