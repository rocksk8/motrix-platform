# -*- coding: utf-8 -*-
"""T87 B2-S0：自訂報表的四項設定（D3 匯出對象／D4 分享／D5 刪除方式／D7 報價單金額欄範圍）與 D1 欄位目錄登記。

守門的重點：
  ① 四項設定的出廠值＝設計文件的預設；每個選項切換後，後端讀到的行為都跟著變（不是只有畫面）。
  ② 只有最高管理者能讀寫設定（其他角色 403）；每次修改有稽核（舊值→新值）、可復原——共用設定中心的既有機制，這裡只驗『這個群組真的走那條路』。
  ③ D1：`dev_case.expected_amount` 登記在欄位目錄，可見規則＝`auth.can_see_financial`，逐角色相等；與既有的 6 份金額鍵清單互不干擾。
"""
import pytest

from db import get_db
from helpers import auth
from helpers import config_ledger as L
from helpers import field_catalog as FC
from helpers import field_policy as FP
from helpers import financial_mask as FM
from helpers import list_view_prefs as LV
from helpers import report_policy as RP
from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as R

G = "custom_reports"


def _hdr(client, make_user, name, role="superadmin", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    username, password = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


@pytest.fixture()
def conn():
    c = get_db()
    R.invalidate()
    yield c
    c.close()
    R.invalidate()


# ── ① 出廠值與各選項的後端行為 ────────────────────────────────────────────────

def test_factory_defaults_are_the_documented_ones():
    assert {k: R.get(G, k) for k in RP.DEFAULTS} == {"export_scope": 0, "sharing": 0, "recycle_deleted": 0, "quote_money_scope": 0}
    assert RP.DEFAULTS == {"export_scope": RP.EXPORT_SAME_AS_USE, "sharing": 0, "recycle_deleted": 0, "quote_money_scope": 0}


def test_group_is_sensitive_and_has_exactly_the_four_settings():
    meta = R.groups()[G]
    assert meta["sensitive"] is True and meta["owner"] == "core"
    assert [f["key"] for f in meta["fields"]] == ["export_scope", "sharing", "recycle_deleted", "quote_money_scope"]


@pytest.mark.parametrize("value, admin_ok, other_ok", [(0, True, True), (1, True, False), (2, False, False)])
def test_export_scope_switch_changes_who_may_export(conn, value, admin_ok, other_ok):
    if value:
        R.publish(G, {"export_scope": value}, reason="測試", user="sa1", conn=conn)
    assert RP.export_scope(conn) == value
    assert RP.export_allowed({"role": "superadmin"}, conn) is admin_ok
    for role in ("admin", "sales", "engineer", "viewer", "finance"):
        assert RP.export_allowed({"role": role}, conn) is other_ok, role


def test_sharing_and_recycle_switches_are_read_by_the_backend_each_time(conn):
    assert RP.sharing_enabled(conn) is False and RP.recycle_deleted(conn) is False
    R.publish(G, {"sharing": 1, "recycle_deleted": 1}, reason="測試", user="sa1", conn=conn)
    assert RP.sharing_enabled(conn) is True and RP.recycle_deleted(conn) is True
    R.publish(G, {"sharing": 0}, reason="收回", user="sa1", conn=conn)
    assert RP.sharing_enabled(conn) is False and RP.recycle_deleted(conn) is True


def test_wider_quote_money_scope_is_a_loosening_that_waits_for_the_confirm_period(conn):
    out = R.publish(G, {"quote_money_scope": 1}, reason="放寬", user="sa1", conn=conn)
    assert out["pending"], "放寬報價單金額欄範圍必須經等待期與核准，不可立即生效"
    assert RP.quote_money_wide(conn) is False                      # 等待期內仍是較嚴格；後端讀到的是『已生效值』


def test_bad_or_missing_values_fall_back_to_the_strict_factory_value(monkeypatch):
    monkeypatch.setattr(R, "get", lambda g, f, **k: 99)
    assert RP.export_scope() == 0
    assert RP.quote_money_wide() is False and RP.sharing_enabled() is False
    monkeypatch.setattr(R, "get", lambda g, f, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert RP.export_scope() == 0 and RP.recycle_deleted() is False and RP.quote_money_wide() is False


# ── ② 權限、稽核、復原（走共用設定中心）───────────────────────────────────────

@pytest.mark.parametrize("role", ["admin", "sales", "engineer", "viewer", "finance"])
def test_non_superadmin_cannot_read_or_change_the_settings(client, make_user, role):
    h = _hdr(client, make_user, "cr_%s" % role, role=role)
    assert client.get("/api/settings-center/groups/%s" % G, headers=h).status_code == 403
    r = client.post("/api/settings-center/groups/%s" % G, json={"values": {"export_scope": 2}, "reason": "測試"}, headers=h)
    assert r.status_code == 403, r.text
    assert RP.export_scope() == 0                                   # 被擋＝沒有任何改動


def test_superadmin_change_is_audited_and_can_be_restored(client, make_user):
    h = _hdr(client, make_user, "cr_sa")
    url = "/api/settings-center/groups/%s" % G
    assert client.post(url, json={"values": {"export_scope": 1}, "reason": "只讓管理者匯出"}, headers=h).status_code == 200
    assert client.post(url, json={"values": {"export_scope": 2}, "reason": "暫停匯出"}, headers=h).status_code == 200
    assert RP.export_scope() == 2
    c = get_db()
    try:
        hist = L.history(c, "setting:%s" % G, G, limit=10)
    finally:
        c.close()
    assert len(hist) >= 2                                           # 每次修改都有明細（誰、何時、舊值→新值由共用帳本記錄）
    vs = client.get(url + "/versions", headers=h).json()["versions"]
    assert len(vs) >= 2
    oldest = min(v["version"] for v in vs)
    back = client.post(url + "/restore/%s" % oldest, json={"reason": "復原到第一版"}, headers=h)
    assert back.status_code == 200, back.text
    assert RP.export_scope() == 1                                   # 復原到只讓管理者匯出的那一版


def test_group_page_is_registered_so_it_shows_in_the_settings_center():
    from helpers import settings_pages as SP
    cov = SP.coverage()
    assert cov == ([], [], []), cov                                             # 頁面登錄涵蓋的群組集合＝登錄表群組集合（空＝沒有缺漏也沒有多登）
    assert any(G in p.get("groups", []) for p in SP.PAGES)


# ── ③ D1：欄位目錄登記與逐角色等價 ─────────────────────────────────────────────

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")


def test_the_new_ceiling_and_field_are_registered_and_the_catalog_stays_consistent():
    assert "financial_view" in FC.CEILINGS
    f = FC.by_id("dev_case.expected_amount")
    assert f and f["ceiling"] == "financial_view" and f["api"] is None and f["moneyClass"] == "money" and f["label"]
    assert FC.problems() == []


def test_existing_mask_key_tuples_are_untouched_by_the_registration():
    for tup in (FM.QUOTATION_MONEY_COLS, FM.ITEM_MONEY_KEYS, FM.QUOTE_MONEY_KEYS, FM.PAYMENT_MONEY_KEYS, FM.MATERIAL_ORDER_MONEY_KEYS):
        assert "expected_amount" not in tup and "expectedAmount" not in tup
    assert FC.api_keys("quotation_cols")[:2] == ("total", "pretax")


@pytest.fixture
def finance_env(monkeypatch):
    state = {"mode": "off", "grants": (set(), set())}
    monkeypatch.setattr(auth, "_finance_mode", lambda: state["mode"])
    monkeypatch.setattr(auth, "_finance_grants", lambda uid, cache: (set(state["grants"][0]), set(state["grants"][1])))
    monkeypatch.setattr(auth, "_finance_shadow_report", lambda *a, **k: None)
    return state


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_expected_amount_visibility_equals_can_see_financial_for_every_role(finance_env, mode):
    finance_env["mode"] = mode
    for role in ROLES:
        for modules in ("[]", '["cashier"]', '["financial_view"]', '["cashier","financial_view","finance"]'):
            u = {"id": 7, "username": "u7", "role": role, "modules": modules}
            want = bool(auth.can_see_financial(u))
            assert FP.visible("dev_case.expected_amount", u) is want, (role, modules, mode)
            assert FP.tier_allowed("financial_view", u) is want
            assert LV._ceiling_ok("financial_view", u) is want, "兩份天花板對照表必須一致"


def test_cashier_grant_without_financial_view_sees_money_but_not_expected_amount(finance_env):
    """釘住『不得比 CRM 頁面多看』：被授予 cashier 的工程師 money_visible 為真，但 can_see_financial 為假 ⇒ 預估金額不可見。"""
    finance_env["mode"] = "on"
    finance_env["grants"] = ({"cashier"}, set())
    u = {"id": 2, "username": "u2", "role": "engineer", "modules": "[]"}
    assert FM.money_visible(u) is True
    assert FP.visible("dev_case.expected_amount", u) is False and auth.can_see_financial(u) is False
    assert FP.visible("quotation.total", u) is False              # 欄位自己的天花板（比出口短路窄），見 field_policy 不變式⑤


def test_unknown_ceiling_stays_closed_in_both_tables():
    u = {"id": 1, "username": "x", "role": "superadmin", "modules": "[]"}
    assert FP.tier_allowed("no_such_tier", u) is False and LV._ceiling_ok("no_such_tier", u) is False
