# -*- coding: utf-8 -*-
"""角色層首發的治理基準擴到所有『執行期真的依角色讀不同層』的種類（T78 BP1 後續；K 審 base_of 的延伸）。

執行期 `D.resolve(conn, kind, key, role)`：角色層整份取代公司層。list_pref_policy 的 `policy_for(..., role)` 就是這樣讀的，
所以『公司層限縮、角色層首發放寬』若拿空基準比，會被看成『改為限定範圍＝收緊』而直接生效、繞過第二位最高管理者核准。
"""
import re
from pathlib import Path

import pytest

from helpers import list_pref_policy as LP
import modules.supply.api.suppliers  # noqa: F401  登記先導清單

LID = "supply:suppliers"
_ROOT = Path(__file__).resolve().parents[2]


def _body(cols=("name",), sorts=("name",), sizes=(20,)):
    # 不帶 pageSize.default：『預設筆數』第一次出現本來就算放寬（與本題無關）
    return {"version": 1, "allowUserPrefs": True,
            "columns": {"allowed": list(cols), "pinned": ["name"], "defaultHidden": []},
            "sort": {"allowed": list(sorts), "default": {"col": "name", "dir": "asc"}},
            "pageSize": {"allowed": list(sizes)}}


LOOSE = dict(cols=("name", "alias", "taxId", "phone"), sorts=("name", "taxId"), sizes=(20, 50, 100))


def _sa(client, make_user, name="lppb_sa"):
    u, pw = make_user(username=name, role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _publish(client, h, scope, body, key=LID):
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


def test_role_first_publish_looser_than_company_policy_needs_second_approval(client, make_user, on):
    h = _sa(client, make_user)
    assert _publish(client, h, "company", _body()).get("status") == "published", "公司層收緊（首發）⇒ 直接發布"
    r = _publish(client, h, "role:sales", _body(**LOOSE))
    assert r.get("status") == "submitted" and r.get("version") == 1, "角色層首發比公司層寬 ⇒ 待核准，不能直接生效"


def test_pending_role_layer_does_not_take_effect_and_company_policy_still_applies(client, make_user, on):
    """待核准的角色層不生效：sales 解析到的仍是公司層。（不經 policy_for：它對全域鍵 `*` 目前會丟例外而回 None——另案。）"""
    from core import definitions as D
    from db import get_db
    h = _sa(client, make_user, "lppb_sa2")
    _publish(client, h, "company", _body())
    _publish(client, h, "role:sales", _body(**LOOSE))
    conn = get_db()
    try:
        body, source = D.resolve(conn, LP.KIND, LID, "sales")
    finally:
        conn.close()
    assert source.startswith("company") and body["columns"]["allowed"] == ["name"]


def test_role_first_publish_copy_of_company_or_tighter_is_direct(client, make_user, on):
    h = _sa(client, make_user, "lppb_sa3")
    _publish(client, h, "company", _body(cols=("name", "alias"), sorts=("name",), sizes=(20, 50)))
    r = _publish(client, h, "role:sales", _body(cols=("name", "alias"), sorts=("name",), sizes=(20, 50)))
    assert r.get("status") == "published", "原樣複製公司層 ⇒ 不變 ⇒ 直接發布"
    r = _publish(client, h, "role:viewer", _body(cols=("name",), sorts=("name",), sizes=(20,)))
    assert r.get("status") == "published", "比公司層更窄 ⇒ 收緊 ⇒ 直接發布"


def test_existing_role_layer_compares_with_itself_and_no_company_layer_keeps_old_behaviour(client, make_user, on):
    h = _sa(client, make_user, "lppb_sa4")
    # 沒有公司層 ⇒ 基準＝空（與過去相同）：角色層首發限縮 ⇒ 直接發布
    assert _publish(client, h, "role:engineer", _body()).get("status") == "published"
    # 已有角色層 ⇒ 跟自己的上一版比：放寬 ⇒ 待核准
    assert _publish(client, h, "role:engineer", _body(**LOOSE)).get("status") == "submitted"
    # 公司層首發不受影響
    assert _publish(client, h, "company", _body()).get("status") == "published"


def test_impact_marks_company_as_the_baseline_for_first_role_layer(client, make_user, on, monkeypatch):
    from routers import def_governance as G
    monkeypatch.setattr(G, "enabled", lambda conn=None: True)
    h = _sa(client, make_user, "lppb_sa5")
    _publish(client, h, "company", _body())
    url = "/api/definitions/list_pref_policy/%s/draft?scope=role:admin" % LID
    assert client.put(url, json={"body": _body(**LOOSE)}, headers=h).status_code == 200
    d = client.get("/api/def-governance/list_pref_policy/%s/impact?scope=role%%3Aadmin" % LID, headers=h).json()
    assert d.get("changesBase") == "company"


def test_role_aware_kinds_cover_every_runtime_reader_that_passes_a_role():
    """守門：有『帶角色』的 D.resolve 呼叫端的檔案只有這三個（目錄=layout、清單偏好政策、診斷端點）。
    出現新的檔案 ⇒ 該種類執行期開始依角色讀取 ⇒ 要判斷是否加進 def_governance.ROLE_AWARE_KINDS，再更新這份名單。"""
    from routers import def_governance as G
    assert {"layout", "list_pref_policy"} <= set(G.ROLE_AWARE_KINDS)
    pat = re.compile(r"\bD\.resolve\(\s*conn\s*,\s*[^,()]+,\s*[^,()]+,\s*[^()]+\)")
    found = set()
    for p in _ROOT.rglob("*.py"):
        rel = p.relative_to(_ROOT).as_posix()
        if rel.startswith(("tests/", ".venv", "venv")) or "/tests/" in rel:
            continue
        if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            found.add(rel)
    assert found == {"core/catalog.py", "helpers/list_pref_policy.py", "routers/definitions.py"}, found
