# -*- coding: utf-8 -*-
"""權限矩陣唯讀狀態探針（1.0.2；D7 final_drill 要求每個模組宣告 provides.probes）。"""
import json
from pathlib import Path

import db
from core.registry import ModuleSpec

URL = "/api/permmatrix/status"
_MOD = Path(__file__).resolve().parents[1]


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_probe_returns_200_with_exactly_the_fixed_body(client, make_user):
    u, p = make_user(username="pm_probe_su", role="superadmin")
    r = client.get(URL, headers=_login(client, u, p))
    assert r.status_code == 200, r.text
    version = json.loads((_MOD / "module.json").read_text(encoding="utf-8"))["version"]
    assert r.json() == {"ok": True, "module": "permmatrix", "version": version}


def test_probe_requires_login(client):
    assert client.get(URL).status_code in (401, 403)


def test_probe_body_does_not_depend_on_perm_tables(client, make_user):
    u, p = make_user(username="pm_probe_su2", role="superadmin")
    h = _login(client, u, p)
    before = client.get(URL, headers=h).json()
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM perm_role_caps")
        conn.commit()
    finally:
        conn.close()
    assert client.get(URL, headers=h).json() == before


def test_module_is_registered_with_router_and_declares_the_probe():
    import modules.permmatrix as PM
    assert isinstance(PM.MODULE, ModuleSpec) and PM.MODULE.key == "permmatrix"
    assert len(PM.MODULE.routers) == 1
    manifest = json.loads((_MOD / "module.json").read_text(encoding="utf-8"))
    assert manifest["provides"]["api_prefixes"] == ["/api/permmatrix"]
    assert manifest["provides"]["probes"] == [URL]
