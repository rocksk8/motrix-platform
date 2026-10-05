# -*- coding: utf-8 -*-
"""第 41 班補洞（第 40 班獨立探針 C1–C11）：材料申請變更端點（modules/case/api/material_changes.py）的寫入守門，全部經 HTTP：

- C1–C6：create／revise／submit／approve／reject／withdraw 都要「先 begin_write 再讀案件」（lost update 守門）——
  以 `material_approval.case_row`（每支端點讀案件的第一步）當探針，記下當下這條連線有沒有拿到寫鎖；
- C7／C8／C9：`_guard_write`——沒有案件存取 404、沒有財務檢視 403、已結案 400（create／revise／submit 各驗一次，且什麼都沒寫）；
- C11：approve 之後核准與套用真的 commit（另開連線讀得到）。
"""
import json

import db
from core.txn import lock_state
from modules.case import material_approval as MA
from modules.case.tests.test_material_change_api_2026_10_03 import BASE, _post, fake_proposal  # noqa: F401
from modules.case.tests.test_material_change_core_2026_10_03 import BOSS, IID, NO, W, _flow, _one_tier, _order_now, _setup, reg  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import _login

CH = "/api/quotations/%s/material-changes/%%d/" % NO


def _boss(client, make_user):
    u, p = make_user(username=BOSS["username"], role="sales")
    return _login(client, u, p)


def _n_changes():
    cn = db.get_db()
    try:
        return cn.execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0]
    finally:
        cn.close()


def _status_of(cid):
    cn = db.get_db()
    try:
        return cn.execute("SELECT status FROM case_material_changes WHERE id=?", (cid,)).fetchone()["status"]
    finally:
        cn.close()


# ── C1–C6：寫鎖在讀案件之前 ────────────────────────────────────────────

def test_every_write_endpoint_takes_the_write_lock_before_reading_the_case(W, reg, fake_proposal, make_user, monkeypatch):
    c, h = W
    bh = _boss(c, make_user)
    _one_tier()
    _setup()
    seen = []
    real = MA.case_row

    def spy(conn, *a, **k):
        seen.append(lock_state(conn)[0])
        return real(conn, *a, **k)
    monkeypatch.setattr(MA, "case_row", spy)

    def step(name, h_, path, body=None, expect=200):
        seen.clear()
        r = _post(c, h_, path, body)
        assert r.status_code == expect, (name, r.status_code, r.text[:200])
        assert seen and seen[0] is True, "%s：讀案件時還沒拿到寫鎖（lost update 缺口）：%s" % (name, seen)
        return r.json()

    ch = step("create", h, BASE + "/changes", {"reason": "追加"})["change"]                           # C1
    step("revise", h, CH % ch["id"] + "revise", {"reason": "追加（改）"})                                # C2
    step("submit", h, CH % ch["id"] + "submit")                                                      # C3
    step("approve", bh, CH % ch["id"] + "approve")                                                   # C4
    assert _status_of(ch["id"]) == "已核准"
    _setup()
    ch2 = _post(c, h, BASE + "/changes", {"reason": "再追加"}).json()["change"]
    _post(c, h, CH % ch2["id"] + "submit")
    step("reject", bh, CH % ch2["id"] + "reject", {"reason": "不對"})                                 # C5
    ch3 = _post(c, h, BASE + "/changes", {"reason": "第三張"}).json()["change"]
    step("withdraw", h, CH % ch3["id"] + "withdraw")                                                 # C6


# ── C7／C8／C9：_guard_write ─────────────────────────────────────────

def _draft(c, h):
    r = _post(c, h, BASE + "/changes", {"reason": "追加"})
    assert r.status_code == 200, r.text
    return r.json()["change"]["id"]


def _writes(cid):
    """三支走 `_guard_write` 的端點：[(名稱, path, body)]。"""
    return [("create", BASE + "/changes", {"reason": "x"}), ("revise", CH % cid + "revise", {"reason": "x"}), ("submit", CH % cid + "submit", {})]


def _assign(username):
    cn = db.get_db()
    try:
        uid = cn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
        cn.commit()
    finally:
        cn.close()


def _frozen_state(cid):
    cn = db.get_db()
    try:
        return (json.dumps(dict(cn.execute("SELECT * FROM case_material_changes WHERE id=?", (cid,)).fetchone()), sort_keys=True, default=str),
                json.dumps(_order_now(cn), sort_keys=True))
    finally:
        cn.close()


def test_guard_write_refuses_user_without_case_access_even_when_finance_visible(W, reg, fake_proposal, make_user):
    """C7：有財務檢視（cashier 模組）、沒有案件存取 ⇒ 404（不洩漏案件存在）；寫入一律不發生。"""
    c, h = W
    _flow([])
    _setup()
    cid = _draft(c, h)
    u, p = make_user(username="t41b_cashier", role="sales", modules=["cashier"])
    xh = _login(c, u, p)
    before, n = _frozen_state(cid), _n_changes()
    for name, path, body in _writes(cid):
        r = _post(c, xh, path, body)
        assert r.status_code == 404, (name, r.status_code, r.text[:200])
    assert _post(c, xh, CH % cid + "withdraw").status_code == 404
    assert _frozen_state(cid) == before and _n_changes() == n


def test_guard_write_refuses_case_member_without_finance_view(W, reg, fake_proposal, make_user):
    """C8：有案件存取（被指派）、沒有財務檢視 ⇒ 403；寫入一律不發生。"""
    c, h = W
    _flow([])
    _setup()
    cid = _draft(c, h)
    u, p = make_user(username="t41b_eng", role="engineer", modules=["case_manage"])
    _assign(u)
    eh = _login(c, u, p)
    assert c.get(BASE + "/changes", headers=eh).status_code == 200                                    # 對照：看得到案件
    before, n = _frozen_state(cid), _n_changes()
    for name, path, body in _writes(cid):
        r = _post(c, eh, path, body)
        assert r.status_code == 403 and "財務檢視" in r.json()["detail"], (name, r.status_code, r.text[:200])
    assert _frozen_state(cid) == before and _n_changes() == n


def test_guard_write_refuses_closed_case(W, reg, fake_proposal):
    """C9：已結案案件 ⇒ 400；寫入一律不發生（連 superadmin 也一樣）。"""
    c, h = W
    _flow([])
    _setup()
    cid = _draft(c, h)
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (NO,))
        cn.commit()
    finally:
        cn.close()
    before, n = _frozen_state(cid), _n_changes()
    for name, path, body in _writes(cid):
        r = _post(c, h, path, body)
        assert r.status_code == 400 and "已結案" in r.json()["detail"], (name, r.status_code, r.text[:200])
    assert _frozen_state(cid) == before and _n_changes() == n


# ── C11：approve 之後真的 commit ──────────────────────────────────────

def test_approve_persists_approval_and_apply_for_other_connections(W, reg, fake_proposal, make_user):
    c, h = W
    bh = _boss(c, make_user)
    _one_tier()
    _setup()
    cid = _draft(c, h)
    s = _post(c, h, CH % cid + "submit")
    assert s.status_code == 200 and s.json()["status"] == "待審核", s.text
    r = _post(c, bh, CH % cid + "approve")
    assert r.status_code == 200 and r.json()["applied"], r.text
    cn = db.get_db()                                                                                  # 全新連線：只看得到已 commit 的
    try:
        row = cn.execute("SELECT status, applied_at FROM case_material_changes WHERE id=?", (cid,)).fetchone()
        assert row["status"] == "已核准" and row["applied_at"], dict(row)
        assert _order_now(cn)["quantity"] == 3.0 and MA.get(cn, NO, IID)["version"] == 2
    finally:
        cn.close()
