# -*- coding: utf-8 -*-
"""R1 法規參數依生效日版本化（CUSTOMIZATION-SPEC §9.1；BENCHMARK §6.2、§6.3、§7）。

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
    for k in ("resident", "non_resident", "minimum_wage"):
        assert seed[k] == d[k], k
    assert lp.minimum_wage_mismatch(seed) == ""
    # 種子（V9 凍結，不改）沒有後加的 bonus_insured_multiple ⇒ 讀取時補上，讀出來＝預設版
    v = lp.load_versions()[0]
    assert v["nhi"] == d["nhi"] and lp.validate_version(v) == []


def test_bonus_insured_multiple_is_required(client, make_user, frozen_today):
    """U4 獎金分潤：補充保費門檻＝投保金額 × nhi.bonus_insured_multiple（115 年簡表：4 倍）。"""
    assert lp.DEFAULT_TAX_RULE_VERSIONS[0]["nhi"]["bonus_insured_multiple"] == 4
    v = _v2027()
    del v["nhi"]["bonus_insured_multiple"]
    assert any("bonus_insured_multiple" in e for e in lp.validate_version(v))
    v["nhi"]["bonus_insured_multiple"] = 0
    assert any("bonus_insured_multiple" in e for e in lp.validate_version(v))
    h = _hdr(client, make_user, "r1_bonus")
    del v["nhi"]["bonus_insured_multiple"]
    r = _put_versions(client, h, lp.load_versions() + [v])
    assert r.status_code == 400 and "bonus_insured_multiple" in r.json()["detail"], r.text
    v["nhi"]["bonus_insured_multiple"] = 4
    assert _put_versions(client, h, lp.load_versions() + [v]).status_code == 200


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


# ── ② 單據凍結 ──────────────────────────────────────────────────────────────────


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


def test_legal_params_endpoints_are_superadmin_only(client, make_user):
    u, p = make_user(username="r1_admin", role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/api/legal-params/tax-rules", headers=h).status_code == 403
    assert _put_versions(client, h, [_v2027()]).status_code == 403
