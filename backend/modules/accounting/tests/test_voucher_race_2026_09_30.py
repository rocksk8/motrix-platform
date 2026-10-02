# -*- coding: utf-8 -*-
"""並行安全（W3 交叉驗證 2026-09-30）：同一張傳票同時過帳／核准／退回，只有一個成功，其餘回 400／409，稽核只有一筆。
做法＝每個執行緒各用自己的 TestClient（各自的連線）同時打端點；斷言看終點狀態與稽核筆數，不看某一趟請求。"""
import threading

import pytest
from starlette.testclient import TestClient

import db

N = 6


def _login(client, make_user, name, role="staff"):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = ["cashier", "finance"]
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _draft(client, h, summary):
    r = client.post("/api/vouchers", headers=h, json={"voucher_date": "2188-05-10", "summary": summary, "lines": [
        {"account_code": "1113", "summary": "x", "debit": 10, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 10}]})
    return r.json()["id"]


def _race(app, path, headers, body=None):
    out, gate = [], threading.Barrier(N)

    def go():
        with TestClient(app) as c:
            gate.wait(timeout=20)
            out.append(c.post(path, headers=headers, json=body or {}).status_code)
    ts = [threading.Thread(target=go) for _ in range(N)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    return out


def _audits(action, vid):
    c = db.get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM audit_log WHERE action=? AND target_id=?", (action, str(vid))).fetchone()[0]
    finally:
        c.close()


def _status(vid):
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def ctx(client, make_user):
    fin, sup = _login(client, make_user, "rc_fin"), _login(client, make_user, "rc_sup", role="superadmin")
    return client, fin, sup


def _approved(client, fin, sup, summary):
    vid = _draft(client, fin, summary)
    for who, act in ((fin, "submit"), (fin, "approve"), (sup, "approve")):
        assert client.post("/api/vouchers/%d/%s" % (vid, act), headers=who, json={}).status_code == 200
    assert _status(vid) == "已核准"
    return vid


def test_concurrent_posts_only_one_wins(ctx):
    client, fin, sup = ctx
    vid = _approved(client, fin, sup, "並行過帳")
    codes = _race(client.app, "/api/vouchers/%d/post" % vid, fin)
    assert codes.count(200) == 1 and all(c in (400, 409) for c in codes if c != 200), codes
    assert _status(vid) == "已過帳" and _audits("voucher.post", vid) == 1


def test_concurrent_final_approvals_only_one_wins(ctx):
    client, fin, sup = ctx
    vid = _draft(client, fin, "並行核准")
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={})            # 內建第一層
    codes = _race(client.app, "/api/vouchers/%d/approve" % vid, sup)               # 第二層（最高管理者）同時核准
    assert codes.count(200) == 1 and all(c in (400, 409) for c in codes if c != 200), codes
    assert _status(vid) == "已核准" and _audits("voucher.approve", vid) == 2


def test_concurrent_send_backs_only_one_wins_and_revision_is_bumped_once(ctx):
    client, fin, sup = ctx
    vid = _draft(client, fin, "並行退回")
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    c = db.get_db()
    no0 = c.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    c.close()
    codes = _race(client.app, "/api/vouchers/%d/send-back" % vid, sup, {"reason": "並行"})
    assert codes.count(200) == 1 and all(c in (400, 409) for c in codes if c != 200), codes
    c = db.get_db()
    try:
        no1 = c.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        c.close()
    assert _status(vid) == "草稿" and no1 == no0 + "-R1" and _audits("voucher.send_back", vid) == 1        # 只升版一次（不會 -R1-R1）
