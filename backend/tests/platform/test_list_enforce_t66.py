# -*- coding: utf-8 -*-
"""T66 L3：清單資料端點的伺服器端強制（`list_view_prefs.enforce_query`）。
排序是洩漏管道：看不到金額／毛利的人不能靠 `sort=` 拿到金額大小順序；`limit` 不能超過清單天花板／公司政策允許的最大每頁筆數。
正對照（scanner-positive-control）：同一組情境把檢查換成「原樣回傳」必須亮紅燈（`_leaks`），否則這支測試什麼都沒驗到。"""
import copy
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import migrations as M
from helpers import list_catalog as LC
from helpers import list_pref_policy as LP
from helpers import list_view_prefs as LV

LID = "t:enf"
SPEC = {"label": "強制測試清單", "modules": ["quote"],
        "columns": [{"id": "name", "label": "名稱", "sortable": True, "required": True},
                    {"id": "city", "label": "城市", "sortable": True},
                    {"id": "tot", "label": "含稅總額", "catalogId": "quotation.total", "sortable": True},
                    {"id": "mar", "label": "直接毛利率", "catalogId": "quotation.direct_margin_pct", "sortable": True}],
        "defaults": {"columns": ["name", "city", "tot", "mar"], "sort": {"col": "tot", "dir": "desc"}, "pageSize": 50},
        "pageSizeCeiling": 200, "pageSizeMenu": [20, 50, 100, 200], "sortGuard": True}
# 名稱順序與金額順序刻意相反：依名稱排 a,b,c；依金額由大到小 c,b,a
ROWS = [{"name": "a", "city": "z", "tot": 1, "mar": 30}, {"name": "b", "city": "y", "tot": 2, "mar": 20}, {"name": "c", "city": "x", "tot": 3, "mar": 10}]
SEE = {"username": "boss", "role": "superadmin"}                          # 金額可見
BLIND = {"username": "clerk", "role": "admin", "modules": '["quote"]'}    # 沒有報價金額權限


@pytest.fixture()
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    M._core_next_list_view_prefs(c)
    yield c
    c.close()


@pytest.fixture()
def cat():
    st = LC.snapshot()
    assert LC.register_list(LID, "test", SPEC) == []
    yield
    LC.restore(st)


@pytest.fixture()
def money_visible(monkeypatch):
    """報價金額權限只看角色：superadmin 看得到，其餘看不到（不碰真的授權表）。"""
    monkeypatch.setattr(LV, "_ceiling_ok", lambda ceiling, user: (user or {}).get("role") == "superadmin")


def _flag(monkeypatch, on):
    monkeypatch.setattr(LV, "enabled", lambda conn=None: on)
    monkeypatch.setattr(LP, "enabled", lambda conn=None: on)


def _policy(monkeypatch, body):
    monkeypatch.setattr(LP, "policy_for", lambda conn, list_id, role=None: copy.deepcopy(body) if body else None)


def _serve(db, user, enforce, sort=None, dir_=None, limit=None):
    """玩具端點：和真的清單端點一樣只用 enforce 的回傳值組查詢。"""
    app = FastAPI()

    @app.get("/rows")
    def rows(sort: str = None, dir: str = None, limit: int = None):
        q = enforce(db, user, LID, sort, dir, limit)
        r = list(ROWS)
        if q["sort"]:
            r.sort(key=lambda x: x[q["sort"]], reverse=(q["dir"] == "desc"))
        if q["limit"]:
            r = r[:q["limit"]]
        return {"names": [x["name"] for x in r], "q": q}
    params = {k: v for k, v in (("sort", sort), ("dir", dir_), ("limit", limit)) if v is not None}
    return TestClient(app).get("/rows", params=params).json()


def _passthrough(conn, user, list_id, sort=None, direction=None, limit=None):
    return {"sort": sort, "dir": direction, "limit": limit, "sortIgnored": False, "limitClamped": False}


def _leaks(db, enforce):
    """看不到金額的人要求依金額「由大到小」排序；回傳順序等於金額由大到小（c,b,a）⇒ 洩漏。"""
    return _serve(db, BLIND, enforce, sort="tot", dir_="desc")["names"] == ["c", "b", "a"]


# ── ①遮蔽：旗標關也要擋 ──
@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("col", ["tot", "mar"])
def test_blind_user_money_sort_is_ignored(db, cat, money_visible, monkeypatch, flag, col):
    _flag(monkeypatch, flag)
    _policy(monkeypatch, None)
    r = _serve(db, BLIND, LV.enforce_query, sort=col, dir_="desc")
    assert r["q"]["sortIgnored"] is True
    assert r["q"]["sort"] is None                       # 預設排序（金額）對他也看不到 ⇒ 不排序
    assert r["names"] == ["a", "b", "c"]               # 原始順序，不是金額順序


def test_positive_control_removing_the_check_turns_the_test_red(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, False)
    assert _leaks(db, LV.enforce_query) is False        # 有檢查：沒洩漏
    assert _leaks(db, _passthrough) is True             # 拿掉檢查：同一個情境亮紅燈 ⇒ 測試確實抓得到


def test_user_with_money_ceiling_may_sort_by_money(db, cat, money_visible, monkeypatch):
    for flag in (False, True):
        _flag(monkeypatch, flag)
        _policy(monkeypatch, None)
        r = _serve(db, SEE, LV.enforce_query, sort="tot", dir_="desc")
        assert r["q"]["sortIgnored"] is False and r["names"] == ["c", "b", "a"]


def test_blind_user_non_money_sort_still_works(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, False)
    r = _serve(db, BLIND, LV.enforce_query, sort="city", dir_="asc")
    assert r["q"]["sortIgnored"] is False and r["names"] == ["c", "b", "a"]


def test_unknown_or_bad_direction_ignored(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, False)
    assert _serve(db, SEE, LV.enforce_query, sort="nope", dir_="asc")["q"]["sortIgnored"] is True
    assert _serve(db, SEE, LV.enforce_query, sort="city", dir_="sideways")["q"]["sortIgnored"] is True


def test_margin_follows_cost_visibility(db, cat, monkeypatch):
    """毛利率衍生自成本：成本不可見，毛利排序也要被忽略（F7 衍生欄位規則）。"""
    monkeypatch.setattr(LV, "_ceiling_ok", lambda ceiling, user: ceiling != "material_money")
    _flag(monkeypatch, False)
    expect_visible = LV.column_visible({"catalogId": "quotation.direct_margin_pct"}, SEE)
    r = _serve(db, SEE, LV.enforce_query, sort="mar", dir_="asc")
    assert r["q"]["sortIgnored"] is (not expect_visible)


def test_enforce_never_raises_and_fails_closed(db, cat, monkeypatch):
    def boom(col, user, _depth=0):
        raise RuntimeError("boom")
    monkeypatch.setattr(LV, "column_visible", boom)
    _flag(monkeypatch, False)
    r = LV.enforce_query(db, SEE, LID, "tot", "asc", None)
    assert r["sortIgnored"] is True and r["sort"] is None


def test_unregistered_list_passes_through(db):
    r = LV.enforce_query(db, SEE, "t:nolist", "x", "asc", 99999)
    assert r == {"sort": "x", "dir": "asc", "limit": 99999, "sortIgnored": False, "limitClamped": False}


# ── ②旗標開時：政策排序白名單與 limit 夾限 ──
def test_policy_sort_allowlist_applies_when_enabled(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, True)
    _policy(monkeypatch, {"sort": {"allowed": ["name"]}})
    assert _serve(db, SEE, LV.enforce_query, sort="city", dir_="asc")["q"]["sortIgnored"] is True
    _flag(monkeypatch, False)                            # 旗標關 ⇒ 政策不生效，只剩遮蔽規則
    assert _serve(db, SEE, LV.enforce_query, sort="city", dir_="asc")["q"]["sortIgnored"] is False


def test_limit_clamped_to_ceiling_and_policy(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, True)
    _policy(monkeypatch, None)
    r = _serve(db, SEE, LV.enforce_query, limit=5000)
    assert r["q"]["limit"] == 200 and r["q"]["limitClamped"] is True
    assert _serve(db, SEE, LV.enforce_query, limit=100)["q"]["limitClamped"] is False
    _policy(monkeypatch, {"pageSize": {"allowed": [20, 50]}})
    r = _serve(db, SEE, LV.enforce_query, limit=200)
    assert r["q"]["limit"] == 50 and r["q"]["limitClamped"] is True
    assert _serve(db, SEE, LV.enforce_query)["q"]["limit"] is None       # 沒給 limit ⇒ 不動


def test_limit_zero_or_negative_falls_back_to_default_size(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, True)
    _policy(monkeypatch, None)
    for bad in (0, -5):
        r = _serve(db, SEE, LV.enforce_query, limit=bad)
        assert r["q"]["limit"] == 50 and r["q"]["limitClamped"] is True


def test_limit_untouched_when_flag_off(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, False)
    assert _serve(db, SEE, LV.enforce_query, limit=5000)["q"]["limit"] == 5000   # 旗標關 ⇒ 與今天相同


def test_positive_control_limit_check_matters(db, cat, money_visible, monkeypatch):
    _flag(monkeypatch, True)
    _policy(monkeypatch, None)
    assert _serve(db, SEE, LV.enforce_query, limit=5000)["q"]["limit"] != 5000
    assert _serve(db, SEE, _passthrough, limit=5000)["q"]["limit"] == 5000
