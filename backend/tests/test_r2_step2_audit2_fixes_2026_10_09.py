# -*- coding: utf-8 -*-
"""R2 第 2 步稽核 #2（hichan-1d，2026-10-09）三個 SHOULD-FIX：
① users-duty.js：被勾選的模組若同時在個人扣項裡，畫面要能解除（候選仍列出）＋存檔前自動解除，避免舊 PUT 400；
② preview_whatif 對 superadmin 回『全部鍵』（與真實判斷 user_has_module→True 一致），不是原始勾選＋財務三鍵；
③ audit_account_permissions：生效清單讀不出來而退回原始勾選的列，basis 如實標 raw。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import db
from helpers import duty_roles as DR

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

ROOT = pathlib.Path(__file__).resolve().parents[2]
NODE = shutil.which("node")


def test_preview_for_superadmin_is_every_key(client, make_user):
    make_user(username="r2f_sa", role="superadmin", modules=["dashboard"])
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='r2f_sa'").fetchone()["id"]
        out = DR.preview_whatif(conn, uid, ["dashboard"], [], [])
    finally:
        conn.close()
    assert set(out["effective"]) == DR.known_keys() and len(out["effective"]) > 3
    assert {"cashier", "finance", "financial_view"} <= set(out["effective"])


def test_audit_row_basis_is_honest_when_the_effective_list_cannot_be_read(client, make_user, monkeypatch):
    import audit_account_permissions as AAP
    from helpers import auth
    make_user(username="r2f_adm", role="admin", modules=["dashboard"])
    real = auth.effective_modules

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(auth, "effective_modules", boom)
    rows = [r for r in AAP._audit() if r["username"] == "r2f_adm"]
    assert rows and rows[0]["basis"] == "raw" and rows[0]["modules"] == ["dashboard"], "讀不出生效清單 ⇒ 退回原始勾選，basis 必須如實標 raw"
    monkeypatch.setattr(auth, "effective_modules", real)
    rows = [r for r in AAP._audit() if r["username"] == "r2f_adm"]
    assert rows[0]["basis"] == "effective"
    assert all(r["basis"] == "raw" for r in AAP._audit(raw=True))


_JS = r"""
const fs = require('fs'); global.window = {}
eval(fs.readFileSync(process.argv[2], 'utf8'))
const o = window.usersDutyMixin()
o.form = { modules: ['case_manage', 'dashboard'] }
const posted = []
o._dutyPost = async (path, body) => { posted.push([path, body.key]); return '' }
o.dutyKeyLabel = (k) => k
Object.assign(o.duty, { visible: true, loaded: true, _userId: 7, roles: [{ id: 1, permissions: ['case_manage'] }], roleIds: [1], origRoleIds: [1],
                        subs: ['case_manage'], origSubs: ['case_manage'], keys: [] })
const cand = o.dutySubCandidates()
o.dutyBefore().then(ok => {
  console.log(JSON.stringify({ cand, ok, posted, subsAfter: o.duty.subs, done: o.duty.doneBeforePut }))
})
"""


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_ticked_module_stays_listed_and_its_subtract_is_dropped_before_the_put(tmp_path):
    f = tmp_path / "t.js"
    f.write_text(_JS, encoding="utf-8")
    r = subprocess.run([NODE, str(f), str(ROOT / "frontend" / "static" / "users-duty.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert "case_manage" in got["cand"], "被勾選但仍在扣項裡的鍵必須繼續列出（否則無法在畫面上解除）"
    assert got["ok"] is True and got["posted"] == [["/subtracts/remove", "case_manage"]] and got["subsAfter"] == []
    assert got["done"] == ["解除扣項 case_manage"]
