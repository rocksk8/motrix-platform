# -*- coding: utf-8 -*-
"""R1 法規參數：勞報單依日期選版、存快照、編輯沿用版本（需要本模組）。

（2026-09-26 自 tests/test_legal_params_r1_2026_09_25.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
R1 法規參數依生效日版本化（CUSTOMIZATION-SPEC §9.1；BENCHMARK §6.2、§6.3、§7）。

守住的規則：
① 依單據日期挑版本；日期早於最早一版 ⇒ 拒絕（不猜）。
② 單據凍結：修改舊單沿用建立時的快照；只有 `recalcTaxRules: true` 才依日期重挑；前端送來的快照不採用。
③ 守門：每一版「兼職薪資補充保費門檻＝當年最低工資」（預設值、db.py 種子、PUT 驗證）。
④ 已生效的版本不能改、不能刪；未生效的可以。
⑤ 跨年提示：12 月且下一年沒有任何版本 ⇒ nextYearMissing。
⑥ 116 年（2027）不預設（最低工資尚待行政院核定）。

⚠️ 本檔的 2027 版是**測試資料**（30,900 為勞動部審議數字，尚未核定），不是產品預設。
"""
import copy
from datetime import date

import pytest

from helpers import legal_params as lp

FROZEN_TODAY = date(2026, 9, 25)


def _v2027():
    v = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    v.update(version="2027", effectiveFrom="2027-01-01", sources=["測試資料"])
    v["minimum_wage"]["monthly"] = 30900
    v["nhi"]["thresholds"]["50"] = 30900
    return v


def _hdr(client, make_user, name="r1_su"):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def frozen_today(monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: FROZEN_TODAY)


def _put_versions(client, h, versions):
    return client.put("/api/legal-params/tax-rules", json={"versions": versions}, headers=h)


def _add_2027(client, h):
    r = _put_versions(client, h, lp.load_versions() + [_v2027()])
    assert r.status_code == 200, r.text


def _slip(gross=30000, itype="50", date_="2026-12-20", **kw):
    d = {"contractorName": "測試承攬人", "incomeType": itype, "grossAmount": gross,
         "contractorNationality": "本國籍", "contractorHasUnionInsurance": False,
         "serviceContent": "測試", "slipDate": date_}
    d.update(kw)
    return {"data": d}


# ── ③ 守門：門檻＝最低工資 ──────────────────────────────────────────────────────


# ── ① 依日期挑版本 ──────────────────────────────────────────────────────────────


def test_a_slip_dated_before_the_first_version_is_refused(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/payslips", json=_slip(date_="2025-12-31"), headers=h)
    assert r.status_code == 400, r.text
    assert "法規參數" in r.json()["detail"]


def test_new_slip_uses_the_version_of_its_date_and_stores_it(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    _add_2027(client, h)
    a = client.post("/api/payslips", json=_slip(date_="2026-12-20"), headers=h)
    b = client.post("/api/payslips", json=_slip(date_="2027-01-05"), headers=h)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    # 兼職薪資 30,000：2026 門檻 29,500 ⇒ 要扣 633；2027 門檻 30,900 ⇒ 不扣
    assert a.json()["calc"]["nhiSupplement"] == 633
    assert b.json()["calc"]["nhiSupplement"] == 0
    assert (a.json()["taxRulesVersion"], b.json()["taxRulesVersion"]) == ("2026", "2027")
    row = client.get("/api/payslips/" + b.json()["slip_no"], headers=h).json()
    assert row["tax_rules_version"] == "2027"
    assert row["data"]["taxRulesSnapshot"]["minimum_wage"]["monthly"] == 30900


def test_tax_rules_endpoint_answers_by_date_and_by_version(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    _add_2027(client, h)
    assert client.get("/api/tax-rules?date=2027-02-01", headers=h).json()["version"] == "2027"
    assert client.get("/api/tax-rules?version=2026", headers=h).json()["version"] == "2026"
    assert client.get("/api/tax-rules?version=1999", headers=h).status_code == 404
    assert client.get("/api/tax-rules?date=2025-01-01", headers=h).status_code == 400


# ── ② 單據凍結 ──────────────────────────────────────────────────────────────────

def test_editing_an_old_slip_keeps_its_version_unless_recalc_is_chosen(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    _add_2027(client, h)
    no = client.post("/api/payslips", json=_slip(date_="2026-12-20"), headers=h).json()["slip_no"]
    # 改日期到 2027，但沒有選重算 ⇒ 沿用建立時的 2026
    r = client.put("/api/payslips/" + no, json=_slip(date_="2027-01-05"), headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["taxRulesVersion"], r.json()["calc"]["nhiSupplement"]) == ("2026", 633)
    # 明確選重算 ⇒ 依日期挑 2027
    r = client.put("/api/payslips/" + no, json=_slip(date_="2027-01-05", recalcTaxRules=True), headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["taxRulesVersion"], r.json()["calc"]["nhiSupplement"]) == ("2027", 0)


def test_a_snapshot_sent_by_the_client_is_ignored(client, make_user):
    h = _hdr(client, make_user)
    no = client.post("/api/payslips", json=_slip(date_="2026-10-01"), headers=h).json()["slip_no"]
    fake = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    fake["nhi"]["rate"] = 0.0
    r = client.put("/api/payslips/" + no, json=_slip(date_="2026-10-01", taxRulesSnapshot=fake), headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["calc"]["nhiSupplement"] == 633


def test_editing_a_legacy_slip_without_snapshot_uses_its_version_number(client, make_user):
    """本功能之前建立的舊單只有版本號 ⇒ 依版本號查。"""
    import db
    import json
    h = _hdr(client, make_user)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO payslips (slip_no, contractor_name, income_type, gross_amount, tax_withheld, "
            "nhi_supplement, net_amount, slip_date, status, tax_rules_version, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("PS-202609-901", "舊", "50", 30000, 0, 633, 29367, "2026-09-01", "草稿", "2026",
             json.dumps({"slipNo": "PS-202609-901"}), "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.execute(
            "INSERT INTO payslips (slip_no, contractor_name, income_type, gross_amount, tax_withheld, "
            "nhi_supplement, net_amount, slip_date, status, tax_rules_version, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("PS-202609-902", "舊", "50", 30000, 0, 633, 29367, "2026-09-01", "草稿", "1999",
             json.dumps({"slipNo": "PS-202609-902"}), "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    r = client.put("/api/payslips/PS-202609-901", json=_slip(date_="2026-09-01"), headers=h)
    assert r.status_code == 200 and r.json()["taxRulesVersion"] == "2026", r.text
    r = client.put("/api/payslips/PS-202609-902", json=_slip(date_="2026-09-01"), headers=h)
    assert r.status_code == 409, r.text
    assert "重新套用" in r.json()["detail"]
    r = client.put("/api/payslips/PS-202609-902", json=_slip(date_="2026-09-01", recalcTaxRules=True), headers=h)
    assert r.status_code == 200 and r.json()["taxRulesVersion"] == "2026", r.text


# ── ④ 已生效的版本不能改 ────────────────────────────────────────────────────────


# ── ⑤ 跨年提示 ──────────────────────────────────────────────────────────────────


def test_status_endpoint_reports_next_year_missing_in_december(client, make_user, monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: date(2026, 12, 2))
    h = _hdr(client, make_user)
    st = client.get("/api/legal-params/tax-rules", headers=h).json()["status"]
    assert st["nextYearMissing"] is True
    # 勞報單頁用的單一版端點也帶同一份提示
    st2 = client.get("/api/tax-rules", headers=h).json()["status"]
    assert st2["nextYearMissing"] is True
