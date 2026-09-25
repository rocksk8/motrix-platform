# -*- coding: utf-8 -*-
"""R1 法規參數依生效日版本化（CUSTOMIZATION-SPEC §7.1；BENCHMARK §6.2、§6.3、§7）。

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

def test_every_default_version_has_part_time_nhi_threshold_equal_to_minimum_wage():
    for v in lp.DEFAULT_TAX_RULE_VERSIONS:
        assert lp.minimum_wage_mismatch(v) == "", v["version"]
        assert lp.validate_version(v) == []


def test_db_seed_matches_the_default_version_and_passes_the_guard(client):
    """db.py 的種子 `tax_rules`（V9 相容的單一設定）就是 2026 那一版。"""
    from helpers.settings import _get_setting
    seed = _get_setting("tax_rules")
    assert seed, "種子 tax_rules 不見了"
    d = lp.DEFAULT_TAX_RULE_VERSIONS[0]
    for k in ("resident", "non_resident", "nhi", "minimum_wage"):
        assert seed[k] == d[k], k
    assert lp.minimum_wage_mismatch(seed) == ""


def test_guard_rejects_a_version_whose_threshold_differs_from_minimum_wage():
    v = _v2027()
    v["nhi"]["thresholds"]["50"] = 29500          # 最低工資改了、門檻忘了改——正是跨年會發生的錯
    errs = lp.validate_version(v)
    assert errs and "不一致" in errs[0]


def test_put_rejects_the_threshold_mismatch(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    v = _v2027()
    v["nhi"]["thresholds"]["50"] = 29500
    r = _put_versions(client, h, lp.load_versions() + [v])
    assert r.status_code == 400, r.text
    assert "最低工資" in r.json()["detail"]
    assert [x["version"] for x in lp.load_versions()] == ["2026"], "被拒的清單不可以寫進去"


def test_2027_is_not_a_default_until_the_minimum_wage_is_approved():
    assert all(not str(v["effectiveFrom"]).startswith("2027") for v in lp.DEFAULT_TAX_RULE_VERSIONS)
    assert all(v["minimum_wage"]["monthly"] != 30900 for v in lp.DEFAULT_TAX_RULE_VERSIONS)
    assert all(v.get("sources") for v in lp.DEFAULT_TAX_RULE_VERSIONS), "預設值要附來源"


# ── ① 依日期挑版本 ──────────────────────────────────────────────────────────────

def test_rules_are_picked_by_effective_date():
    vs = lp.DEFAULT_TAX_RULE_VERSIONS + [_v2027()]
    assert lp.rules_for_date(vs, "2026-12-31")["version"] == "2026"
    assert lp.rules_for_date(vs, "2027-01-01")["version"] == "2027"
    with pytest.raises(lp.NoApplicableRules):
        lp.rules_for_date(vs, "2025-12-31")


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

def test_an_effective_version_cannot_be_changed_or_deleted(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    vs = lp.load_versions()
    vs[0]["resident"]["50"]["tax_threshold"] = 1
    r = _put_versions(client, h, vs)
    assert r.status_code == 409 or r.status_code == 400, r.text
    assert "不能修改" in r.json()["detail"]
    r = _put_versions(client, h, [_v2027()])
    assert r.status_code == 400 and "不能刪除" in r.json()["detail"], r.text


def test_a_future_version_can_be_corrected(client, make_user, frozen_today):
    h = _hdr(client, make_user)
    _add_2027(client, h)
    vs = lp.load_versions()
    vs[1]["resident"]["50"]["tax_threshold"] = 92001
    r = _put_versions(client, h, vs)
    assert r.status_code == 200, r.text
    assert lp.load_versions()[1]["resident"]["50"]["tax_threshold"] == 92001


# ── ⑤ 跨年提示 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("today,extra,missing", [
    (date(2026, 11, 30), [], False),
    (date(2026, 12, 1), [], True),
    (date(2026, 12, 1), [_v2027()], False),
])
def test_next_year_missing_from_december(today, extra, missing):
    st = lp.year_status(lp.DEFAULT_TAX_RULE_VERSIONS + extra, today)
    assert st["nextYearMissing"] is missing
    assert any("2027 年的法規參數" in w for w in st["warnings"]) is missing


def test_new_year_without_a_version_warns_that_last_year_is_reused():
    st = lp.year_status(lp.DEFAULT_TAX_RULE_VERSIONS, date(2027, 1, 3))
    assert st["currentYearMissing"] is True and st["currentVersion"] == "2026"
    assert any("沿用 2026" in w for w in st["warnings"])


def test_status_endpoint_reports_next_year_missing_in_december(client, make_user, monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: date(2026, 12, 2))
    h = _hdr(client, make_user)
    st = client.get("/api/legal-params/tax-rules", headers=h).json()["status"]
    assert st["nextYearMissing"] is True
    # 勞報單頁用的單一版端點也帶同一份提示
    st2 = client.get("/api/tax-rules", headers=h).json()["status"]
    assert st2["nextYearMissing"] is True


def test_legal_params_endpoints_are_superadmin_only(client, make_user):
    u, p = make_user(username="r1_admin", role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/api/legal-params/tax-rules", headers=h).status_code == 403
    assert _put_versions(client, h, [_v2027()]).status_code == 403
