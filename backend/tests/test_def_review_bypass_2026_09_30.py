# -*- coding: utf-8 -*-
"""W3 #3：定義審核繞過。規則（主持裁示 2026-09-30，提案版）：
- 第二人審核只涵蓋「自訂模組定義（company 範圍）」；其他 kind（版面／輸出版型／自訂欄位）由最高管理者直接發布，
  但**每一條直接發布／還原的路徑都寫稽核 `definitions.publish_unreviewed`**（同一個動作名）。
- 自訂模組定義只有 company 範圍：其他範圍一律 400（引擎只讀 company，不留一條不過審核的寫入路徑）。
- 守門：routers/definitions.py 裡每個呼叫 `D.publish`／`D.restore` 的函式，必須同時呼叫 `_audit_unreviewed` 或走送審（`_defr.`）。"""
import ast
import os

import pytest

KEY = "b3bp"


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=[])[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _unreviewed():
    return [r["target_label"] for r in _rows("SELECT target_label FROM audit_log WHERE action='definitions.publish_unreviewed' ORDER BY id")]


def _tpl():
    from helpers import doc_template as dt
    return dt.load_default("invoice_voucher")


def test_direct_publish_of_other_kinds_is_audited_as_unreviewed(client, make_user):
    boss = _login(client, make_user, "b3bp_boss")
    r = client.put("/api/definitions/output_template/invoice_voucher/draft", headers=boss, json={"body": _tpl()})
    assert r.status_code == 200, r.text
    assert _unreviewed() == []
    r = client.post("/api/definitions/output_template/invoice_voucher/publish", headers=boss, json={"note": "n"})
    assert r.status_code == 200, r.text
    got = _unreviewed()
    assert len(got) == 1 and "output_template" in got[0] and "未經第二人審核" in got[0] and "第 %d 版" % r.json()["version"] in got[0]


def test_direct_restore_of_other_kinds_is_audited_as_unreviewed(client, make_user):
    boss = _login(client, make_user, "b3bp_boss2")
    for _ in range(2):
        client.put("/api/definitions/output_template/invoice_voucher/draft", headers=boss, json={"body": _tpl()})
        assert client.post("/api/definitions/output_template/invoice_voucher/publish", headers=boss, json={}).status_code == 200
    n = len(_unreviewed())
    r = client.post("/api/definitions/output_template/invoice_voucher/restore/1", headers=boss, json={})
    assert r.status_code == 200, r.text
    got = _unreviewed()
    assert len(got) == n + 1 and "還原" in got[-1] and "未經第二人審核" in got[-1]


@pytest.mark.parametrize("verb,path,method", [("draft", "draft", "put"), ("publish", "publish", "post"), ("restore", "restore/1", "post")])
def test_custom_module_only_has_company_scope(client, make_user, verb, path, method):
    boss = _login(client, make_user, "b3bp_boss3_" + verb)
    r = getattr(client, method)("/api/definitions/custom_module/%s/%s?scope=role:user" % (KEY, path), headers=boss,
                                json={"body": {}})
    assert r.status_code == 400 and "company" in r.json()["detail"], r.text
    assert _rows("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key=?", (KEY,)) == []


def test_every_direct_publish_or_restore_call_is_audited_or_goes_through_review():
    """守門：之後新增第三條 D.publish／D.restore 路徑而沒寫稽核 ⇒ 紅。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "routers", "definitions.py"), encoding="utf-8").read()
    bad, seen = [], 0
    for fn in [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)]:
        text = ast.get_source_segment(src, fn)
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                 and isinstance(c.func.value, ast.Name) and c.func.value.id == "D" and c.func.attr in ("publish", "restore")]
        if not calls:
            continue
        seen += len(calls)
        if "_audit_unreviewed(" not in text:
            bad.append(fn.name)
    assert seen >= 2, "沒掃到任何 D.publish／D.restore 呼叫 —— **儀器失效**"
    assert not bad, "這些函式直接發布／還原卻沒寫 definitions.publish_unreviewed 稽核：%s" % bad
