# -*- coding: utf-8 -*-
"""第 48 班：新口徑完整切換流程（離線遷移工具 ↔ 伺服器）——report → recalc --apply --set-mode-v2 → 完成標記存在 → 伺服器認 v2 → 新報價單用新口徑；
反向：有 v2 沒有完成標記 ⇒ 伺服器照 legacy。工具實際以子行程對測試資料庫檔執行（不 import 工具內部）。"""
import json
import os
import subprocess
import sys

import pytest

import db

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(BACKEND, "tools", "overhead_migrate.py")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _quote(**over):
    d = {"customerName": "切換測客", "projectName": "切換測專", "salesPerson": "", "quoteDate": "2026-10-09",
         "items": [{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 60000}],
         "tot": {"subtotal": 100000, "pretax": 100000, "tax": 5000, "total": 105000, "totalCost": 60000, "inputVat": 3000,
                 "directProfit": 37000, "directMarginPct": 37.0, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 10370,
                 "netProfit": 26630, "netMarginPct": 26.6}}
    d.update(over)
    return d


def _tool(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, TOOL, "--db", db.DB_PATH, "--no-backup", *args], capture_output=True, text=True, encoding="utf-8",
                          cwd=BACKEND, env=env, timeout=120)


def _tot(qno):
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])["tot"]
    finally:
        cn.close()


def _setting(key):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else None
    finally:
        cn.close()


def test_full_cutover_sequence_and_the_negative_without_the_marker(client, make_user):
    su, sp = make_user(username="cut_su", role="superadmin")
    ad, ap = make_user(username="cut_adm", role="admin")
    sh, ah = _login(client, su, sp), _login(client, ad, ap)
    old = client.post("/api/quotations", json={"status": "草稿", "data": _quote()}, headers=ah).json()["quote_no"]
    assert _tot(old)["adminCost"] == 10000 and "formulaVer" not in _tot(old), "切換前：舊口徑"
    assert client.get("/api/overhead/settings", headers=ah).json()["ruleMode"] == "legacy"

    r = _tool("report")                                             # dry-run：什麼都不寫
    assert r.returncode == 0, r.stderr + r.stdout
    assert _setting("overhead_migration_done") is None and _setting("overhead_rule_mode") is None

    r = _tool("recalc", "--apply")                                   # 沒有 --set-mode-v2 且模式不是 v2 ⇒ 工具拒絕
    assert r.returncode == 2 and _setting("overhead_migration_done") is None

    r = _tool("recalc", "--apply", "--set-mode-v2")
    assert r.returncode == 0, r.stderr + r.stdout
    marker = _setting("overhead_migration_done")
    assert marker and marker["doneAt"] and marker["recalculated"] >= 1 and _setting("overhead_rule_mode") == "v2"

    st = client.get("/api/overhead/settings", headers=ah).json()
    assert st["ruleMode"] == "v2" and st["migrationDone"] is True and st["ver"] == 2, "有標記＋v2 ⇒ 伺服器認新口徑"
    t = _tot(old)
    assert (t["formulaVer"], t["adminCost"], t["netProfit"]) == (2, 9250, 27380), "既有未精算單已被遷移成新口徑"
    new = client.post("/api/quotations", json={"status": "草稿", "data": _quote()}, headers=ah).json()["quote_no"]
    t = _tot(new)
    assert (t["formulaVer"], t["overheadPct"], t["adminCost"], t["netProfit"]) == (2, 25, 9250, 27380), "新報價單由伺服器用新口徑算"

    cn = db.get_db()                                                 # 反向：模式仍是 v2、但完成標記不見 ⇒ 伺服器當 legacy
    cn.execute("DELETE FROM system_settings WHERE key='overhead_migration_done'")
    cn.commit()
    cn.close()
    assert client.get("/api/overhead/settings", headers=ah).json()["ruleMode"] == "legacy"
    legacy = client.post("/api/quotations", json={"status": "草稿", "data": _quote()}, headers=ah).json()["quote_no"]
    t = _tot(legacy)
    assert t["adminCost"] == 10000 and "formulaVer" not in t
    r = _tool("mode", "v2", "--apply")                               # 工具端也不允許沒有標記就設 v2
    assert r.returncode == 2
