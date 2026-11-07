# -*- coding: utf-8 -*-
"""T66 L1 補洞：全域預設鍵過去寫成 `*`，但定義文件庫的 key 格式（`core.definitions._KEY_RE`）不收 `*` ⇒
存不進去、`policy_for()` 讀它時丟 DefinitionError 被 except 吞掉 ⇒ 旗標開了也永遠回 None。現改 `global.default`。
這份測試**不 monkeypatch `D.resolve`**：走真的 HTTP 存檔／發布、真的讀回，T66 L1 原本的測試是 monkeypatch 才綠。
另測：清單專屬政策『第一版』的寬嚴基準＝繼承來的有效政策（全域預設），不是空的。
"""
import logging

import pytest

from core import definitions as D
from helpers import list_catalog as LC
from helpers import list_pref_policy as LP
import modules.supply.api.suppliers  # noqa: F401  登記先導清單

LID = "supply:suppliers"


def _own(cols=("name",), sizes=None, **extra):
    b = {"version": 1, "columns": {"allowed": list(cols), "pinned": ["name"], "defaultHidden": []},
         "sort": {"allowed": ["name"], "default": {"col": "name", "dir": "asc"}}}
    if sizes is not None:
        b["pageSize"] = {"allowed": list(sizes)}
    b.update(extra)
    return b


def _glob(sizes=(20,), allow=True):
    return {"version": 1, "allowUserPrefs": allow, "pageSize": {"allowed": list(sizes)}}


def _sa(client, make_user, name):
    u, pw = make_user(username=name, role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _publish(client, h, key, scope, body):
    url = "/api/definitions/list_pref_policy/%s" % key
    r = client.put(url + "/draft?scope=" + scope, json={"body": body}, headers=h)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    r2 = client.post(url + "/publish?scope=" + scope, json={"note": "t", "base_etag": r.json()["etag"]}, headers=h)
    assert r2.status_code == 200, r2.text
    return r2.json()


@pytest.fixture
def on(monkeypatch):
    from routers import def_pipeline as P
    monkeypatch.setattr(LP, "enabled", lambda conn=None: True)
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    LP.ensure_kind()


def _policy(role=None, list_id=LID):
    from db import get_db
    conn = get_db()
    try:
        return LP.policy_for(conn, list_id, role)
    finally:
        conn.close()


def test_global_key_is_a_valid_definition_key_and_cannot_collide_with_a_list_id():
    assert D._KEY_RE.match(LP.GLOBAL_KEY), "全域預設鍵必須能存進定義文件庫"
    assert LC._ID_RE.match(LP.GLOBAL_KEY) is None, "不能是合法的清單代號（否則清單專屬政策會撞名）"


def test_global_default_is_stored_and_policy_for_really_returns_it(client, make_user, on, caplog):
    """旗標開、全域預設存進去、policy_for 真的拿到值（不靠 monkeypatch），而且沒有『讀取失敗』警告被吞。"""
    h = _sa(client, make_user, "gk_sa1")
    assert _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20, 50), allow=False)).get("status") == "published"
    with caplog.at_level(logging.WARNING, logger="motrix.list_pref_policy"):
        p = _policy()
    assert p == _glob((20, 50), allow=False), p
    assert not [r for r in caplog.records if "讀取清單偏好政策失敗" in r.getMessage()], "不能再靠吞例外回 None"


def test_list_specific_policy_overrides_global_and_role_layer_overrides_company(client, make_user, on):
    h = _sa(client, make_user, "gk_sa2")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20, 50)))
    _publish(client, h, LID, "company", _own(("name", "alias"), sizes=(20,)))
    p = _policy()
    assert p["columns"]["allowed"] == ["name", "alias"] and p["pageSize"]["allowed"] == [20]
    assert _policy("sales")["columns"]["allowed"] == ["name", "alias"], "沒有角色層 ⇒ 公司層"
    _publish(client, h, LID, "role:sales", _own(("name",), sizes=(20,)))
    assert _policy("sales")["columns"]["allowed"] == ["name"], "角色層整份取代公司層"
    assert _policy("viewer")["columns"]["allowed"] == ["name", "alias"]
    assert _policy("sales", "no:such") is None


def test_flag_off_still_returns_none_even_with_rows(client, make_user, on, monkeypatch):
    h = _sa(client, make_user, "gk_sa3")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob())
    assert _policy() is not None
    monkeypatch.setattr(LP, "enabled", lambda conn=None: False)
    assert _policy() is None


def test_unreadable_global_row_means_no_policy_not_a_crash(client, make_user, on, monkeypatch):
    h = _sa(client, make_user, "gk_sa4")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob())
    real = D.get
    monkeypatch.setattr(D, "get", lambda conn, kind, key, scope="company", version=None: dict(real(conn, kind, key, scope, version) or {}, body={"version": 9})
                        if kind == LP.KIND and real(conn, kind, key, scope, version) else real(conn, kind, key, scope, version))
    assert _policy() is None


# ── 清單專屬政策第一版的寬嚴基準＝繼承來的有效政策 ──

def test_first_list_policy_wider_than_global_default_needs_second_approval(client, make_user, on):
    h = _sa(client, make_user, "gk_sa5")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20,)))
    r = _publish(client, h, LID, "company", _own(("name", "alias"), sizes=(20, 50, 100)))
    assert r.get("status") == "submitted", "每頁筆數比全域預設寬 ⇒ 待核准"
    assert _policy()["pageSize"]["allowed"] == [20], "待核准不生效：仍是全域預設"


def test_first_list_policy_not_wider_than_global_default_is_direct(client, make_user, on):
    """只寫欄位（沒寫 pageSize）：執行期 pageSize 由全域預設補上 ⇒ 沒有放寬 ⇒ 直接發布；寫相同或更窄的 pageSize 也是。"""
    h = _sa(client, make_user, "gk_sa6")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20, 50)))
    assert _publish(client, h, LID, "company", _own(("name",))).get("status") == "published"
    assert _publish(client, h, "supply:suppliers", "role:sales", _own(("name",), sizes=(20,))).get("status") == "published"


def test_allow_user_prefs_cannot_be_reopened_by_a_first_list_policy(client, make_user, on):
    h = _sa(client, make_user, "gk_sa7")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20,), allow=False))
    r = _publish(client, h, LID, "company", _own(("name",), allowUserPrefs=True))
    assert r.get("status") == "submitted", "全域預設不開放個人設定，清單專屬政策想開放 ⇒ 放寬"


def test_without_a_global_default_the_baseline_stays_empty(client, make_user, on):
    h = _sa(client, make_user, "gk_sa8")
    assert _publish(client, h, LID, "company", _own(("name",), sizes=(20,))).get("status") == "published"


def test_inherited_baseline_is_company_list_policy_plus_global_for_a_role_first_publish(client, make_user, on):
    h = _sa(client, make_user, "gk_sa9")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20,)))
    _publish(client, h, LID, "company", _own(("name",)))                 # 公司層清單政策沒寫 pageSize ⇒ 有效值＝全域的 [20]
    r = _publish(client, h, LID, "role:sales", _own(("name",), sizes=(20, 50)))
    assert r.get("status") == "submitted", "角色層首發的 pageSize 比有效政策（全域 [20]）寬 ⇒ 待核准"


def test_impact_preview_diffs_against_the_inherited_policy(client, make_user, on, monkeypatch):
    from routers import def_governance as G
    monkeypatch.setattr(G, "enabled", lambda conn=None: True)
    h = _sa(client, make_user, "gk_sa10")
    _publish(client, h, LP.GLOBAL_KEY, "company", _glob((20,)))
    url = "/api/definitions/list_pref_policy/%s/draft?scope=company" % LID
    assert client.put(url, json={"body": _own(("name",), sizes=(20,))}, headers=h).status_code == 200
    d = client.get("/api/def-governance/list_pref_policy/%s/impact?scope=company" % LID, headers=h).json()
    assert d.get("changesBase") == LP.GLOBAL_KEY
    paths = [c["path"] for c in d["changes"]]
    assert not any(p.startswith("pageSize") for p in paths), "pageSize 跟繼承來的一樣 ⇒ 不是變更"
    assert any(p.startswith("columns") for p in paths)
