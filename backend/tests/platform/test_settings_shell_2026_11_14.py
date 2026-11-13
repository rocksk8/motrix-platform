# -*- coding: utf-8 -*-
"""S2：設定中心外框的頁面登錄與唯讀資料（settings_pages／settings_shell／overview／recent／index）。"""
import re

import pytest

from db import get_db
from helpers import settings_pages as SP
from helpers import settings_registry as R
from helpers import settings_shell as SH

P = "/api/settings-center"
G = "zz_shell_g"


def _hdr(client, make_user, name="shell_a"):
    username, password = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _real_groups():
    return [g for g, m in R.groups().items() if not m.get("external") and not g.startswith("zz_")]


def test_page_registry_covers_exactly_the_registered_groups(client):
    missing, extra, dup = SP.coverage(_real_groups())
    assert not missing, "登錄表有、頁面沒涵蓋（到 settings_pages.py 登記）：%s" % missing
    assert not extra, "頁面涵蓋了登錄表沒有的群組：%s" % extra
    assert not dup, "群組被兩個頁面涵蓋：%s" % dup


def test_coverage_guard_has_a_positive_control():
    m, e, d = SP.coverage(_real_groups() + ["zz_not_in_pages"])                  # 多一個登錄群組 ⇒ 要被抓到
    assert m == ["zz_not_in_pages"]
    m, e, d = SP.coverage(_real_groups()[1:])                                    # 少一個 ⇒ 頁面多登
    assert e and not m


def test_categories_and_names_are_plain(client):
    assert SP.CATEGORIES == ("業務", "財務", "系統", "安全")
    for p in SP.pages():
        assert p["category"] in SP.CATEGORIES and p["plain"]
    BANNED = re.compile(r"確認期間|影子|閘門|true／false|true/false")
    for p in SP.PAGES:
        assert not BANNED.search(p["plain"]), p
    for g, m in SP.GROUPS.items():
        assert not BANNED.search(m["plain"]), g


def test_register_standalone_validates_and_appears_in_nav(monkeypatch):
    monkeypatch.setattr(SP, "_STANDALONE", [])
    SP.register_standalone("zz_alone", "簽核流程", "財務", "approval-settings.html", keywords=["核准", "簽核"])
    assert [p["id"] for p in SP.pages() if p.get("standalone")] == ["zz_alone"]
    with pytest.raises(ValueError):
        SP.register_standalone("zz_alone", "重複", "財務", "x.html")
    with pytest.raises(ValueError):
        SP.register_standalone("zz_b", "分類不存在", "不存在", "x.html")
    with pytest.raises(ValueError):
        SP.register_standalone("zz_c", "沒有連結", "財務", "")
    assert any(i["kind"] == "page" and "簽核" in i["text"] for i in SH.search_index())


@pytest.fixture()
def grp(client, make_user):
    make_user(username="shell_b", role="superadmin")
    R.invalidate()
    R.register_group(G, "外框測試群組", [
        R.SettingDef("cap", "int", 10, min=1, max=1000, risk="security", loosen="up", question="上限要設多少？", label="上限", when="想放寬時。",
                     help="測試用的上限。", impact="影響之後的操作，調大屬放寬。", risk_text="調大後門檻變低。",
                     choices=None),
        R.SettingDef("days", "int", 5, min=1, max=100, risk="ops", question="提醒幾天前寄？", label="提醒天數", help="測試用。", impact="只影響提醒時間。"),
    ], help="測試用的設定群組。", risk="security")
    c = get_db()
    yield c
    R._GROUPS.pop(G, None)
    c.close()
    R.invalidate()


def _with_page(monkeypatch):
    monkeypatch.setattr(SP, "PAGES", list(SP.PAGES) + [{"id": "zz_shell_page", "plain": "外框測試頁", "category": "系統", "groups": [G], "style": "checkbox"}])
    monkeypatch.setitem(SP.GROUPS, G, {"plain": "外框測試的白話名", "currentName": "外框測試群組", "privacy": True})


def test_overview_counts_differs_pending_and_high_risk(client, make_user, grp, monkeypatch):
    h = _hdr(client, make_user)
    _with_page(monkeypatch)
    R.publish(G, {"days": 9}, reason="r", user="shell_a", conn=grp)                # 立即生效 ⇒ 與預設不同
    R.publish(G, {"cap": 50}, reason="放寬", user="shell_a", conn=grp)             # 調大＝放寬 ⇒ 待生效
    grp.commit()
    d = client.get(P + "/overview", headers=h).json()
    pg = {p["id"]: p for p in d["pages"]}["zz_shell_page"]
    assert pg["differs"] == 1 and pg["pending"] == 1 and pg["highRisk"] is True and pg["privacy"] is True and pg["status"] == "open"
    assert d["categories"] == ["業務", "財務", "系統", "安全"]
    assert d["stats"]["pending"] >= 1 and d["stats"]["differs"] >= 1 and d["stats"]["highRiskGroups"] >= 1
    assert [i["label"] for i in d["differsItems"] if i["group"] == G] == ["提醒天數"]
    assert d["recent"] and len(d["recent"]) <= 5


def test_overview_never_leaks_hidden_groups_and_marks_planned(client, make_user, grp, monkeypatch):
    h = _hdr(client, make_user)
    _with_page(monkeypatch)
    monkeypatch.setattr(R, "group_status", lambda g: "hidden" if g == G else "open")
    d = client.get(P + "/overview", headers=h).json()
    assert "zz_shell_page" not in {p["id"] for p in d["pages"]} and "外框測試" not in str(d)
    assert "外框測試" not in str(client.get(P + "/index", headers=h).json())
    assert "外框測試" not in str(client.get(P + "/recent", headers=h).json())
    monkeypatch.setattr(R, "group_status", lambda g: "planned" if g == G else "open")
    d = client.get(P + "/overview", headers=h).json()
    assert {p["id"]: p for p in d["pages"]}["zz_shell_page"]["status"] == "planned"
    assert not [i for i in client.get(P + "/index", headers=h).json()["items"] if i["kind"] == "field" and i["group"] == G]      # planned：只有名稱，沒有欄位


def test_recent_orders_new_first_filters_high_and_caps_limit(client, make_user, grp, monkeypatch):
    h = _hdr(client, make_user)
    _with_page(monkeypatch)
    R.publish(G, {"days": 9}, reason="先改提醒", user="shell_a", conn=grp)
    R.publish(G, {"cap": 5}, reason="再收緊上限", user="shell_a", conn=grp)         # 調小＝收緊 ⇒ 立即
    grp.commit()
    rows = client.get(P + "/recent", headers=h).json()["changes"]
    mine = [r for r in rows if r["group"] == G]
    assert [r["label"] for r in mine][:2] == ["上限", "提醒天數"] and mine[0]["actor"] == "shell_a" and mine[0]["stateText"] == "已生效"
    assert mine[0]["page"] == "zz_shell_page" and mine[0]["new"] == "5" and mine[0]["reason"] == "再收緊上限"
    hi = client.get(P + "/recent?high=1", headers=h).json()["changes"]
    assert hi and all(r["risk"] in ("money", "legal", "security") for r in hi)
    assert len(client.get(P + "/recent?limit=1", headers=h).json()["changes"]) == 1
    assert len(client.get(P + "/recent?limit=99999", headers=h).json()["changes"]) <= 200


def test_search_index_has_fields_with_text_and_no_values(client, make_user, grp, monkeypatch):
    h = _hdr(client, make_user)
    _with_page(monkeypatch)
    items = client.get(P + "/index", headers=h).json()["items"]
    f = [i for i in items if i["kind"] == "field" and i["group"] == G and i["field"] == "cap"][0]
    assert "想放寬時" in f["text"] and "測試用的上限" in f["text"] and f["pagePlain"] == "外框測試頁" and f["groupPlain"] == "外框測試的白話名"
    assert "value" not in f and "default" not in f
    assert any(i["kind"] == "group" and i["group"] == G and "外框測試群組" in i["text"] for i in items)       # 群組現行名稱也搜得到


def test_external_groups_are_excluded_everywhere(client, make_user, grp, monkeypatch):
    h = _hdr(client, make_user)
    R.register_group("zz_shell_ext", "外部群組", [R.SettingDef("n", "int", 1, min=0, max=9, question="填多少？", label="數量", help="測試用。", impact="影響測試。")],
                     help="測試用群組。", external=True)
    try:
        monkeypatch.setattr(SP, "PAGES", list(SP.PAGES) + [{"id": "zz_ext_page", "plain": "不該出現", "category": "系統", "groups": ["zz_shell_ext"], "style": "checkbox"}])
        d = client.get(P + "/overview", headers=h).json()
        assert "zz_ext_page" not in {p["id"] for p in d["pages"]}
        assert "zz_shell_ext" not in str(client.get(P + "/index", headers=h).json())
        assert SP.coverage(_real_groups())[0] == []                                             # external 不要求登記
    finally:
        R._GROUPS.pop("zz_shell_ext", None)


def test_new_routes_require_superadmin(client, make_user):
    username, password = make_user(username="shell_plain", role="viewer")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    for path in ("/overview", "/recent", "/index"):
        assert client.get(P + path, headers=h).status_code in (401, 403)
        assert client.get(P + path).status_code in (401, 403)
