# -*- coding: utf-8 -*-
"""T86 U5：財務角色在案件頁被拒（正式機 90 天 case.access_denied 44 筆；財務最常開的頁面就是案件管理，約 1060 次）。

不是把案件入口藏起來（會打斷財務實際的工作），而是頁面只送他能用的請求：
  - 靠 cashier 模組唯讀進來的人（`cashierReadOnly`）後端本來就擋寫入；案件沒有任何階段時，頁面會自動 POST 5 個預設階段
    ⇒ 5 次被拒、5 筆稽核。現在唯讀就不送；
  - bootstrap 剛問過原端點、回 403／404 的區段，20 秒內不再為同一個答案多送一個請求（見 test_bootstrap_frontend 的對應題）。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONT / "js" / "case-management-core.js"
NODE = shutil.which("node")

SEED_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const a = src.indexOf('    async _seedDefaultStagesIfEmpty() {')
const body = src.slice(a, src.indexOf('\n    },\n', a) + 7)
const calls = []
global.fetch = async (url, o) => { calls.push([o && o.method, url]); return { ok: true, status: 201, json: async () => ({ id: calls.length }) } }
const o = new Function('return {' + body.replace(/,\s*$/, '') + '}')()
Object.assign(o, { selected: { quote_no: 'MQ-1', cashierReadOnly: inp.ro }, cr: { caseRecord: { stages: inp.stages } }, session: { token: 't' },
  _stFlag: false, _selectLive: () => () => true, caseReadOnly() { return !!this.selected?.cashierReadOnly } })
;(async () => { await o._seedDefaultStagesIfEmpty(); console.log(JSON.stringify({ calls, n: o.cr.caseRecord.stages.length })) })()
"""


def _seed(**kw):
    out = subprocess.run([NODE, "-e", SEED_HARNESS, str(CORE), json.dumps(kw)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_read_only_cashier_access_never_posts_default_stages():
    r = _seed(ro=True, stages=[])
    assert r["calls"] == [] and r["n"] == 0


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_a_member_with_write_access_still_gets_the_five_default_stages():
    r = _seed(ro=False, stages=[])
    assert len(r["calls"]) == 5 and all(c[0] == "POST" and c[1] == "/api/quotations/MQ-1/stages" for c in r["calls"]) and r["n"] == 5


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_a_case_that_already_has_stages_posts_nothing():
    assert _seed(ro=False, stages=[{"id": 1}])["calls"] == []


def test_cashier_read_only_flag_comes_from_the_server_and_is_the_one_the_page_reads():
    s = CORE.read_text(encoding="utf-8")
    assert "caseReadOnly() { return !!this.selected?.cashierReadOnly }" in s
    a = s.index("async _seedDefaultStagesIfEmpty()")
    assert s.index("this.caseReadOnly()", a) < s.index("fetch(`/api/quotations/${this.selected.quote_no}/stages`", a)


# ───────────── 後端：案件整包逐段被拒不留稽核 ─────────────
import time  # noqa: E402

from tests._requires import requires_module  # noqa: E402

needs_m01 = requires_module("case", "本題打 M01（案件）的端點")
NO = "MQ-U5-001"


def _case(make_user):
    import db
    owner = make_user(username="u5_owner", role="sales")
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username=?", (owner[0],)).fetchone()[0]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", oid, "擁有者", "[]"))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _audit_n():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='case.access_denied'").fetchone()[0]
    finally:
        conn.close()


@needs_m01
def test_cashier_only_finance_opening_a_case_leaves_no_denial_audit_for_the_parts_it_cannot_see(client, make_user):
    u = make_user(username="u5_fin", role="finance", modules=["cashier"])
    _case(make_user)
    h = _hdr(client, u)
    r = client.get(f"/api/quotations/{NO}/case-bundle", headers=h)
    assert r.status_code == 200, r.text
    parts = r.json()["parts"]
    blocked = [k for k, v in parts.items() if not v["ok"]]
    assert blocked, "沒有任何一段被擋＝這題沒有測到東西（沙箱實測：dispatches／shippingNotes／completionNotes／updates）"
    time.sleep(0.6)
    assert _audit_n() == 0, "預期內的逐段無權限不該每次開案件寫稽核"


@needs_m01
def test_the_same_endpoint_called_on_its_own_is_still_audited(client, make_user):
    u = make_user(username="u5_fin2", role="finance", modules=["cashier"])
    _case(make_user)
    h = _hdr(client, u)
    for p in ("updates", "close-gates"):
        client.get(f"/api/quotations/{NO}/{p}", headers=h)
    end = time.time() + 5
    while time.time() < end and _audit_n() == 0:
        time.sleep(0.1)
    # updates 對只有 cashier 的人是 owner 規則 ⇒ 單獨呼叫仍是 404＋稽核（抑制只在整包逐段內）
    r = client.get(f"/api/quotations/{NO}/updates", headers=h)
    assert r.status_code == 404 and _audit_n() >= 1


@needs_m01
def test_a_user_who_cannot_see_the_case_at_all_is_still_audited_by_the_bundle(client, make_user):
    u = make_user(username="u5_other", role="sales")
    _case(make_user)
    h = _hdr(client, u)
    assert client.get(f"/api/quotations/{NO}/case-bundle", headers=h).status_code == 404
    end = time.time() + 5
    while time.time() < end and _audit_n() == 0:
        time.sleep(0.1)
    assert _audit_n() >= 1, "案件本體被拒（探測別人的案件）仍要稽核"
