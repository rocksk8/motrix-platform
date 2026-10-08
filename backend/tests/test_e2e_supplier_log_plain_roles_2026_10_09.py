# -*- coding: utf-8 -*-
"""供應商紀錄頁（supplier-log.html）一般角色（業務／工程師）開啟不得有 JS 例外（第 48 班小項 #1）。
先前會丟 `Cannot read properties of undefined (reading 'length')`；第 47 班的 e2e 因此把該頁這一條濾掉。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["sales", "engineer"])
@pytest.mark.parametrize("with_id", [True, False])
def test_supplier_log_has_no_js_error_for_plain_roles(live_server, client, make_user, new_context, role, with_id):
    u = make_user(username="sl_" + role, role=role)
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO suppliers (name) VALUES ('SL供應商')")
        c.commit()
        sid = c.execute("SELECT id FROM suppliers WHERE name='SL供應商'").fetchone()[0]
    finally:
        c.close()
    pg = new_context(viewport={"width": 1366, "height": 900}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append("%s | %s" % (e, getattr(e, "stack", ""))))
    inject_login(pg, live_server, u[0], u[1])
    pg.goto("%s/pages/supplier-log.html%s" % (live_server, "?id=%s" % sid if with_id else ""))
    pg.wait_for_load_state("domcontentloaded")
    pg.wait_for_timeout(2500)
    assert not errors, errors
