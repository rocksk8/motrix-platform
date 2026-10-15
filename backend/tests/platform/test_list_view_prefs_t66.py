# -*- coding: utf-8 -*-
"""T66 L2：清單檢視偏好（`helpers/list_view_prefs.py`、`routers/list_view_prefs.py`、表 `user_list_view_prefs`）。
重點：①金額欄只能隱藏／重排、不可加回（預設不顯示的金額欄根本不列出）；②F7 可見 ∩ 公司政策 每次讀取重算；③存檔不合法 422、etag 不符 409、公司不開放 403；
④只讀寫自己的列；⑤旗標關 ⇒ 全部 404；⑥版面引擎的欄位／排序仍在既有 `user_list_prefs`（本檔不碰）。"""
import copy
import sqlite3

import pytest

from core import migrations as M
from helpers import list_catalog as LC
from helpers import list_pref_policy as LP
from helpers import list_view_prefs as LV
import modules.supply.api.suppliers  # noqa: F401  登記先導清單

LID = "supply:suppliers"
U1 = {"username": "u1", "role": "admin"}
U2 = {"username": "u2", "role": "admin"}


@pytest.fixture()
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    M._core_next_list_view_prefs(c)
    yield c
    c.close()


@pytest.fixture()
def clean_catalog():
    st = LC.snapshot()
    yield
    LC.restore(st)


@pytest.fixture()
def no_policy(monkeypatch):
    monkeypatch.setattr(LP, "policy_for", lambda conn, list_id, role=None: None)


def _policy(monkeypatch, body):
    monkeypatch.setattr(LP, "policy_for", lambda conn, list_id, role=None: copy.deepcopy(body))


MONEY_SPEC = {"label": "含金額清單",
              "columns": [{"id": "a", "label": "甲", "sortable": True, "required": True},
                          {"id": "b", "label": "乙", "sortable": True},
                          {"id": "tot", "label": "含稅總額", "catalogId": "quotation.total", "sortable": True},
                          {"id": "mar", "label": "直接毛利率", "catalogId": "quotation.direct_margin_pct", "sortable": True}],
              "defaults": {"columns": ["a", "b", "tot", "mar"], "sort": {"col": "tot", "dir": "desc"}, "pageSize": 50},
              "pageSizeCeiling": 200, "pageSizeMenu": [20, 50, 200]}


# ── 表 ──
def test_migration_is_idempotent_and_unit_keyed(db):
    M._core_next_list_view_prefs(db)
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(user_list_view_prefs)")}
    assert list(cols) == ["username", "list_id", "prefs_json", "updated_at", "owner_unit_id"]
    assert cols["owner_unit_id"][2].upper() == "INTEGER" and cols["owner_unit_id"][3] == 1 and str(cols["owner_unit_id"][4]) == "1"
    assert [r[1] for r in db.execute("PRAGMA table_info(user_list_view_prefs)") if r[5]] == ["username", "list_id"]


# ── 預設（沒有政策）──
def test_defaults_without_policy(db, no_policy):
    v = LV.constraints(db, U1, LID)
    assert v["enabled"] and v["allowUserPrefs"] and v["custom"] is False and v["etag"] == ""
    assert [c["id"] for c in v["columns"]] == [c["id"] for c in LC.columns_of(LID)]
    assert all(c["money"] is False and c["canShow"] and c["defaultVisible"] for c in v["columns"])
    assert v["pageSize"] == {"value": 50, "source": "default", "options": [20, 50, 100, 200]}
    assert v["sort"]["default"] == {"col": "name", "dir": "asc"} and "name" in v["sort"]["allowed"] and "phone" not in v["sort"]["allowed"]
    assert next(c for c in v["columns"] if c["id"] == "name")["pinned"] is True      # 必留欄位視為固定
    assert LV.constraints(db, U1, "no:such") is None


# ── 金額欄 ──
def test_money_columns_follow_f7_ceiling(db, no_policy, clean_catalog, monkeypatch):
    LC.register_list("t:money", "test", MONEY_SPEC)
    monkeypatch.setattr(LV, "_ceiling_ok", lambda ceiling, user: True)
    v = LV.constraints(db, U1, "t:money")
    assert [c["id"] for c in v["columns"]] == ["a", "b", "tot", "mar"]
    assert [c["money"] for c in v["columns"]] == [False, False, True, True]
    assert v["sort"]["default"] == {"col": "tot", "dir": "desc"}
    monkeypatch.setattr(LV, "_ceiling_ok", lambda ceiling, user: False)          # 沒有金額權限
    v = LV.constraints(db, U1, "t:money")
    assert [c["id"] for c in v["columns"]] == ["a", "b"]                           # 金額欄整個不列出
    assert "tot" not in v["sort"]["allowed"]
    assert v["sort"]["default"] is None                                            # 預設排序欄位看不到 ⇒ 沒有預設
    assert "含稅總額" not in str(v)                                                # 連名稱都不洩漏


def test_unknown_ceiling_fails_closed(monkeypatch):
    assert LV._ceiling_ok("no_such_ceiling", U1) is False
    from helpers import financial_mask as FM
    monkeypatch.setattr(FM, "quote_money_visible", lambda u: (_ for _ in ()).throw(RuntimeError("x")))
    assert LV._ceiling_ok("quote_money", U1) is False


def test_margin_hidden_when_its_cost_source_is_hidden(db, no_policy, clean_catalog, monkeypatch):
    """成本藏起來，毛利也不可見（derivedFrom 連帶）。"""
    LC.register_list("t:money", "test", MONEY_SPEC)
    real = LV._FC.by_id
    seen = {}

    def ceiling(c, u):
        return c != "cost_only"

    class FC:
        @staticmethod
        def by_id(fid):
            f = real(fid)
            if f is None:
                return None
            f = dict(f)
            if fid == "quote_item.cost":
                f["ceiling"] = "cost_only"
            seen[fid] = f
            return f
    monkeypatch.setattr(LV, "_FC", FC)
    monkeypatch.setattr(LV, "_ceiling_ok", ceiling)
    ids = [c["id"] for c in LV.constraints(db, U1, "t:money")["columns"]]
    assert "tot" in ids and "mar" not in ids                                       # 毛利率 derivedFrom quote_item.cost


def test_policy_default_hidden_money_column_cannot_be_added_back(db, clean_catalog, monkeypatch):
    LC.register_list("t:money", "test", MONEY_SPEC)
    monkeypatch.setattr(LV, "_ceiling_ok", lambda c, u: True)
    _policy(monkeypatch, {"version": 1, "columns": {"defaultHidden": ["tot", "b"]}})
    v = LV.constraints(db, U1, "t:money")
    ids = {c["id"]: c for c in v["columns"]}
    assert "tot" not in ids                                                         # 預設隱藏的金額欄：不列出 ⇒ 使用者無從加回
    assert ids["b"]["canShow"] is True and ids["b"]["defaultVisible"] is False      # 非金額欄可以自己打開
    assert LV.clamp_columns(v, [{"field": "tot", "visible": True}, {"field": "b", "visible": True}]) == [{"field": "b", "visible": True}]


def test_clamp_columns_pinned_forced_and_unlisted_dropped(db, no_policy):
    v = LV.constraints(db, U1, LID)
    out = LV.clamp_columns(v, [{"field": "zzz", "visible": True}, {"field": "name", "visible": False}, {"id": "phone", "visible": False}])
    assert out == [{"field": "name", "visible": True}, {"id": "phone", "visible": False}]          # 不認得的丟掉；必留欄位強制顯示；個人隱藏保留；順序不變


def test_clamp_sort(db, no_policy):
    v = LV.constraints(db, U1, LID)
    assert LV.clamp_sort(v, "taxId", "desc") == {"col": "taxId", "dir": "desc"}
    assert LV.clamp_sort(v, "phone", "asc") == v["sort"]["default"]                # 不可排序的欄位
    assert LV.clamp_sort(v, "name", "sideways") == v["sort"]["default"]


# ── 政策 ──
def test_policy_restricts_columns_sort_and_page_sizes(db, monkeypatch):
    _policy(monkeypatch, {"version": 1, "columns": {"allowed": ["name", "alias", "phone"], "pinned": ["alias"], "defaultHidden": ["phone"]},
                          "sort": {"allowed": ["name"], "default": {"col": "name", "dir": "desc"}},
                          "pageSize": {"allowed": [20, 100], "default": 100}})
    v = LV.constraints(db, U1, LID)
    assert [c["id"] for c in v["columns"]] == ["name", "alias", "phone"]
    by = {c["id"]: c for c in v["columns"]}
    assert by["alias"]["pinned"] and by["phone"]["defaultVisible"] is False and by["phone"]["canShow"] is True
    assert v["sort"] == {"allowed": ["name"], "default": {"col": "name", "dir": "desc"}}
    assert v["pageSize"] == {"value": 100, "source": "policy", "options": [20, 100]}


def test_policy_disallowing_user_prefs(db, monkeypatch):
    _policy(monkeypatch, {"version": 1, "allowUserPrefs": False, "pageSize": {"default": 20}})
    v = LV.constraints(db, U1, LID)
    assert v["allowUserPrefs"] is False and v["pageSize"]["options"] == [20] and v["pageSize"]["value"] == 20
    with pytest.raises(LV.ViewError) as e:
        LV.save_page_size(db, U1, LID, {"pageSize": 20})
    assert e.value.status == 403


# ── 存檔 ──
def test_save_valid_and_reread(db, no_policy):
    v = LV.save_page_size(db, U1, LID, {"pageSize": 100})
    assert v["pageSize"] == {"value": 100, "source": "user", "options": [20, 50, 100, 200]} and v["custom"] and v["etag"]
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 100
    assert db.execute("SELECT COUNT(*) FROM user_list_view_prefs").fetchone()[0] == 1


@pytest.mark.parametrize("body,frag", [
    ({"pageSize": 33}, "下列其中一個"), ({"pageSize": True}, "下列其中一個"), ({"pageSize": "50"}, "下列其中一個"), ({"pageSize": 5000}, "下列其中一個"),
    ({}, "缺少"), ({"pageSize": 50, "columns": ["x"]}, "不認得"), ({"pageSize": 50, "sort": {}}, "不認得"), ("x", "物件"), (None, "物件"),
])
def test_save_rejects_invalid_with_422_and_writes_nothing(db, no_policy, body, frag):
    with pytest.raises(LV.ViewError) as e:
        LV.save_page_size(db, U1, LID, body)
    assert e.value.status == 422 and any(frag in p for p in e.value.problems), e.value.problems
    assert db.execute("SELECT COUNT(*) FROM user_list_view_prefs").fetchone()[0] == 0


def test_unknown_list_is_404(db, no_policy):
    for fn in (lambda: LV.save_page_size(db, U1, "no:such", {"pageSize": 50}), lambda: LV.reset(db, U1, "no:such")):
        with pytest.raises(LV.ViewError) as e:
            fn()
        assert e.value.status == 404


def test_etag_conflict_409(db, no_policy):
    first = LV.save_page_size(db, U1, LID, {"pageSize": 20}, None)               # 沒有列時，不帶 If-Match 可存
    with pytest.raises(LV.ViewError) as e:
        LV.save_page_size(db, U1, LID, {"pageSize": 50}, None)                    # 已有列卻沒帶 etag ⇒ 衝突
    assert e.value.status == 409
    with pytest.raises(LV.ViewError) as e:
        LV.save_page_size(db, U1, LID, {"pageSize": 50}, "deadbeefdeadbeef")
    assert e.value.status == 409
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 20                 # 衝突時沒寫入
    second = LV.save_page_size(db, U1, LID, {"pageSize": 50}, first["etag"])
    assert second["pageSize"]["value"] == 50 and second["etag"] != first["etag"]


def test_reset_returns_to_default_and_is_idempotent(db, no_policy):
    LV.save_page_size(db, U1, LID, {"pageSize": 200})
    v = LV.reset(db, U1, LID)
    assert v["custom"] is False and v["pageSize"]["value"] == 50 and v["etag"] == ""
    assert LV.reset(db, U1, LID)["custom"] is False


def test_rows_are_per_user(db, no_policy):
    LV.save_page_size(db, U1, LID, {"pageSize": 20})
    assert LV.constraints(db, U2, LID)["pageSize"]["value"] == 50
    LV.reset(db, U2, LID)                                                          # 重設別人的（沒有）不影響 U1
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 20
    assert [s["hasCustom"] for s in LV.list_summaries(db, U1) if s["id"] == LID] == [True]
    assert [s["hasCustom"] for s in LV.list_summaries(db, U2) if s["id"] == LID] == [False]


def test_stored_value_outside_current_range_falls_back_without_error(db, monkeypatch):
    _policy(monkeypatch, {"version": 1})
    LV.save_page_size(db, U1, LID, {"pageSize": 200})
    _policy(monkeypatch, {"version": 1, "pageSize": {"allowed": [20, 50], "default": 20}})      # 政策收緊
    v = LV.constraints(db, U1, LID)
    assert v["pageSize"] == {"value": 20, "source": "policy", "options": [20, 50]}


def test_corrupt_or_missing_storage_gives_defaults(db, no_policy):
    db.execute("INSERT INTO user_list_view_prefs (username, list_id, prefs_json) VALUES ('u1', ?, '{not json')", (LID,))
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 50
    db.execute("UPDATE user_list_view_prefs SET prefs_json='[1,2]'")
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 50
    db.execute("DROP TABLE user_list_view_prefs")
    assert LV.constraints(db, U1, LID)["pageSize"]["value"] == 50                    # 表不存在 ⇒ 預設，不丟例外


def test_enabled_requires_flags(monkeypatch):
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: 0)
    assert LV.enabled() is False


# ── 路由（旗標關 ⇒ 404；旗標開 ⇒ 正常）──
@pytest.fixture()
def auth(client, make_user):
    u, p = make_user(username="lv_admin", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_routes_are_404_when_flag_off(client, auth):
    for m, url, kw in (("get", "/api/list-views", {}), ("get", "/api/list-views/" + LID, {}), ("put", "/api/list-views/" + LID, {"json": {"pageSize": 20}}),
                       ("delete", "/api/list-views/" + LID, {})):
        r = getattr(client, m)(url, headers=auth, **kw)
        assert r.status_code == 404, (m, url, r.status_code)


def test_routes_require_login(client):
    for m, url in (("get", "/api/list-views"), ("get", "/api/list-views/" + LID), ("put", "/api/list-views/" + LID), ("delete", "/api/list-views/" + LID)):
        assert getattr(client, m)(url).status_code in (401, 403)


def test_routes_flow_when_flag_on(client, auth):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("builder_governance", {"enabled": 1}, user="t", reason="t", conn=c)
        SR.publish("list_prefs", {"enabled": 1}, user="t", reason="t", conn=c)
        SR.invalidate()
    finally:
        c.close()
    r = client.get("/api/list-views", headers=auth)
    assert r.status_code == 200 and any(x["id"] == LID for x in r.json()["lists"])
    g = client.get("/api/list-views/" + LID, headers=auth)
    assert g.status_code == 200 and g.json()["pageSize"]["value"] == 50
    assert client.get("/api/list-views/no:such", headers=auth).status_code == 404
    bad = client.put("/api/list-views/" + LID, headers=auth, json={"pageSize": 33})
    assert bad.status_code == 422 and bad.json()["detail"]["problems"]
    ok = client.put("/api/list-views/" + LID, headers=auth, json={"pageSize": 20})
    assert ok.status_code == 200 and ok.json()["pageSize"]["value"] == 20
    conflict = client.put("/api/list-views/" + LID, headers=auth, json={"pageSize": 50})
    assert conflict.status_code == 409
    again = client.put("/api/list-views/" + LID, headers={**auth, "If-Match": ok.json()["etag"]}, json={"pageSize": 50})
    assert again.status_code == 200
    d = client.delete("/api/list-views/" + LID, headers=auth)
    assert d.status_code == 200 and d.json()["custom"] is False
