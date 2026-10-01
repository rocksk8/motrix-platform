import json, db

def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p}); assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}

def _def(key, status="published"):
    c = db.get_db()
    c.execute("INSERT INTO ui_definitions(kind,key,scope,version,status,body_json) VALUES ('custom_module',?, 'company',1,?, '{}')", (key, status)); c.commit(); c.close()

def test_moddel(client, make_user):
    h = {n: _login(client, *make_user(username=n, role=r, modules=m)) for n, r, m in (("md_sa", "superadmin", None), ("md_admin", "admin", None), ("md_user", "engineer", []))}
    _def("md_a"); _def("md_b"); _def("md_sub", "submitted")
    res = {}
    res["unauth"] = client.delete("/api/definitions/custom_module/md_a").status_code
    res["user"] = client.delete("/api/definitions/custom_module/md_a", headers=h["md_user"]).status_code
    res["admin"] = client.delete("/api/definitions/custom_module/md_a", headers=h["md_admin"]).status_code
    res["sa_ok"] = client.delete("/api/definitions/custom_module/md_a", headers=h["md_sa"]).status_code
    res["sa_again_404"] = client.delete("/api/definitions/custom_module/md_a", headers=h["md_sa"]).status_code
    res["submitted_409"] = client.delete("/api/definitions/custom_module/md_sub", headers=h["md_sa"]).status_code
    c = db.get_db()
    c.execute("INSERT INTO custom_records(module_key,record_no,def_version,status) VALUES ('md_b','R1',1,'草稿')"); c.commit(); c.close()
    r = client.delete("/api/definitions/custom_module/md_b", headers=h["md_sa"]); res["records_409"] = (r.status_code, r.json().get("records"))
    res["with_records_ok"] = client.delete("/api/definitions/custom_module/md_b?with_records=1", headers=h["md_sa"]).status_code
    for k in ("..%2Fx", "a%00b", "x" * 300, "有中文"):
        res["key:" + k[:8]] = client.delete("/api/definitions/custom_module/" + k, headers=h["md_sa"]).status_code
    c = db.get_db()
    res["audit_rows"] = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='definitions.delete_module'").fetchone()[0]
    res["left_defs"] = c.execute("SELECT COUNT(*) FROM ui_definitions WHERE key IN ('md_a','md_b')").fetchone()[0]
    c.close()
    print("MODDEL", json.dumps(res, ensure_ascii=False))
    assert res["unauth"] in (401, 403) and res["user"] == 403 and res["admin"] == 403 and res["sa_ok"] == 200 and res["sa_again_404"] == 404
    assert res["submitted_409"] == 409 and res["records_409"][0] == 409 and res["with_records_ok"] == 200
    assert all(v != 500 for v in res.values() if isinstance(v, int))
