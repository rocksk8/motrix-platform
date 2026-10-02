# -*- coding: utf-8 -*-
"""A2-0 底層預留 #3：定義種類登記（`core.definitions.register_kind`）。
新增一種可編輯定義（A2 的 `expense_type`、之後任何種類）只要登記，不必再改 L0 的固定 `KINDS`：
登記後草稿／發布／版本／還原／差異／送審全部共用；沒登記的種類照舊被拒；內建四種不可覆寫；兩個登記者搶同一名稱 ⇒ 報錯。
反向控制：把 `_check` 改回只認靜態 KINDS ⇒ 「登記後能存草稿」那一題必須紅（見檔尾說明）。"""
import sqlite3

import pytest

from core import definitions as D


@pytest.fixture()
def conn(tmp_path):
    from core import migrations
    c = sqlite3.connect(str(tmp_path / "defs.db"))
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL DEFAULT '')")
    migrations._core_v1_ui_definitions(c)
    yield c
    c.close()


@pytest.fixture()
def clean_registry(monkeypatch):
    """登記表／驗證器／預設換成拷貝（不污染真的登記）。"""
    monkeypatch.setattr(D, "_EXTRA_KINDS", {})
    monkeypatch.setattr(D, "_VALIDATORS", dict(D._VALIDATORS))
    monkeypatch.setattr(D, "_DEFAULTS", dict(D._DEFAULTS))


def _validator(body, key):
    return [] if isinstance(body.get("fields"), list) else [{"path": "fields", "message": "fields 必須是清單"}]


def test_registered_kind_behaves_like_the_builtin_ones(conn, clean_registry):
    D.register_kind("expense_type", label="請款類型", validator=_validator, default=lambda key: {"fields": [], "from": "default"} if key == "travel" else None)
    assert "expense_type" in D.kinds() and D.KINDS == ("layout", "output_template", "custom_fields", "custom_module")   # 內建四種不變
    D.save_draft(conn, "expense_type", "travel", "company", {"fields": [{"key": "a"}]}, "u")
    assert D.validate("expense_type", "travel", {"fields": "x"})                       # 驗證器生效
    D.save_draft(conn, "expense_type", "travel", "company", {"fields": "x"}, "u")
    with pytest.raises(D.DefinitionError) as e:
        D.publish(conn, "expense_type", "travel", "company", "", "u")                   # 發布前驗證器擋下
    assert e.value.problems
    D.save_draft(conn, "expense_type", "travel", "company", {"fields": [{"key": "a"}]}, "u")
    v1 = D.publish(conn, "expense_type", "travel", "company", "第一版", "u")
    D.save_draft(conn, "expense_type", "travel", "company", {"fields": [{"key": "a"}, {"key": "b"}]}, "u")
    v2 = D.publish(conn, "expense_type", "travel", "company", "第二版", "u")
    assert (v1["version"], v2["version"]) == (1, 2)
    assert [x["version"] for x in D.versions(conn, "expense_type", "travel", "company") if x["status"] == "published"] == [2, 1]
    assert D.restore(conn, "expense_type", "travel", "company", 1, "", "u")["version"] == 3           # 還原＝再發布舊版
    assert D.resolve(conn, "expense_type", "travel")[0]["fields"] == [{"key": "a"}]
    assert [r["key"] for r in D.list_definitions(conn, "expense_type")] == ["travel"]
    assert D.get(conn, "custom_module", "travel", "company") is None                          # 不會跑到別的種類


def test_unregistered_kind_is_still_rejected(conn, clean_registry):
    with pytest.raises(D.DefinitionError, match="未知的定義種類"):
        D.save_draft(conn, "expense_type", "travel", "company", {}, "u")
    with pytest.raises(D.DefinitionError, match="未知的定義種類"):
        D.list_definitions(conn, "expense_type")


def test_duplicate_builtin_and_bad_names_are_refused(clean_registry):
    D.register_kind("kind_a")
    with pytest.raises(ValueError, match="已登記"):
        D.register_kind("kind_a", label="別人")                                         # 兩個登記者搶同一名稱
    for builtin in D.KINDS:
        with pytest.raises(ValueError, match="已登記"):
            D.register_kind(builtin)                                                   # 內建不可覆寫
    for bad in ("", "Bad", "1x", "a-b", "a" * 41, None, 5):
        with pytest.raises(ValueError, match="不合法"):
            D.register_kind(bad)


def test_kinds_meta_lists_builtin_and_registered(clean_registry):
    D.register_kind("zeta", label="乙"); D.register_kind("alpha", label="甲")
    meta = D.kinds_meta()
    assert [m["kind"] for m in meta[:4]] == list(D.KINDS) and all(m["builtin"] for m in meta[:4])
    assert [(m["kind"], m["label"], m["builtin"]) for m in meta[4:]] == [("alpha", "甲", False), ("zeta", "乙", False)]   # 已登記的依名稱排序


def test_definition_kinds_endpoint_is_superadmin_only(client, make_user, clean_registry):
    D.register_kind("expense_type", label="請款類型")
    boss = make_user(username="dk_boss", role="superadmin")
    user = make_user(username="dk_user", role="admin")
    tok = lambda u: {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}  # noqa: E731
    r = client.get("/api/definition-kinds", headers=tok(boss))
    assert r.status_code == 200 and {"kind": "expense_type", "label": "請款類型", "builtin": False} in r.json()["kinds"]
    assert client.get("/api/definition-kinds", headers=tok(user)).status_code == 403
    # 既有的依種類路由照舊、也認得新種類
    assert client.get("/api/definitions/expense_type", headers=tok(boss)).status_code == 200
    assert client.get("/api/definitions/not_registered", headers=tok(boss)).status_code in (400, 404)


def test_validate_route_knows_registered_kinds(client, make_user, clean_registry):
    """W3 回報：`POST /api/definitions/{kind}/{key}/validate` 用內建 KINDS ⇒ 登記的種類 400；改用 `kinds()` 後要是 200。"""
    D.register_kind("expense_type", label="請款類型", validator=_validator)
    boss = make_user(username="vk_boss", role="superadmin")
    tok = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]}
    r = client.post("/api/definitions/expense_type/travel/validate", headers=tok, json={"body": {"fields": "x"}})
    assert r.status_code == 200 and r.json()["problems"], r.text               # 驗證器生效（fields 不是清單）
    assert client.post("/api/definitions/not_registered/travel/validate", headers=tok, json={"body": {}}).status_code == 400
