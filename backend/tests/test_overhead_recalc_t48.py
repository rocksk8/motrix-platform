# -*- coding: utf-8 -*-
"""第 48 班 S5：未精算報價單重算遷移（migrations_frozen/t48_overhead25 + tools/overhead_migrate.py）。

① 凍結算式 == profit_rules ver 2（黃金對拍，隨機＋邊界）② 四類資料：未精算／草稿精算／已完結／已結案 ③ 冪等 ④ 回滾逐位還原
⑤ dry-run 不寫（檔案雜湊不變）⑥ 備份檔 ⑦ mode 開關預設 legacy ⑧ 遷移後才完結者回滾不動。
"""
import hashlib
import json
import os
import random
import sqlite3
import subprocess
import sys

import pytest

from helpers import profit_rules as P
from migrations_frozen.t48_overhead25 import recalc as R

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(BACKEND, "tools", "overhead_migrate.py")


def _legacy_tot(pretax, cost, five):
    vat = int(round(cost * 0.05))
    q = P.quote_profit(pretax, cost, vat, five, ver=1)
    q.update(pretax=pretax, netProfit=round(q['netProfit']), netMarginPct=round(q['netMarginPct'], 1), directMarginPct=round(q['directMarginPct'], 1))
    return q


def _mk(path, rows):
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE quotations(id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT, settle_status TEXT DEFAULT '',
                       deal_tag TEXT DEFAULT '', data_json TEXT, net_margin_pct REAL DEFAULT 0, updated_at TEXT DEFAULT '');
                       CREATE TABLE system_settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT DEFAULT '');""")
    for no, tot, st, tag, settlement in rows:
        d = {"tot": tot}
        if settlement:
            d["settlement"] = settlement
        c.execute("INSERT INTO quotations(quote_no, settle_status, deal_tag, data_json, net_margin_pct) VALUES(?,?,?,?,?)",
                  (no, st, tag, json.dumps(d, ensure_ascii=False), tot["netMarginPct"]))
    c.commit()
    c.close()


def _run(*args):
    p = subprocess.run([sys.executable, "-I", TOOL, *args], capture_output=True, text=True, encoding="utf-8", cwd=BACKEND,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode, p.stdout + p.stderr


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _rows(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    out = {r["quote_no"]: (r["data_json"], r["net_margin_pct"]) for r in c.execute("SELECT * FROM quotations")}
    c.close()
    return out


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    five = [1000, 0, 500, 0, 250]
    rows = [("U1", _legacy_tot(1000000, 600000, five), "", "", None),
            ("U2", _legacy_tot(500000, 520000, [0] * 5), "", "已成案", None),                      # 虧損
            ("D1", _legacy_tot(800000, 500000, five), "draft", "", {"status": "draft", "summary": {"netProfit": 1}}),
            ("F1", _legacy_tot(900000, 500000, five), "finalized", "", {"status": "finalized", "summary": {"netProfit": 2}}),
            ("C1", _legacy_tot(700000, 400000, five), "", "已結案", None)]
    _mk(p, rows)
    return p


def test_frozen_equals_profit_rules_ver2():
    rnd = random.Random(48)
    for _ in range(400):
        pretax = rnd.choice([0, 1, 999, 100000, 1234567, rnd.randint(1, 5_000_000)])
        cost = rnd.choice([0, pretax, rnd.randint(0, 6_000_000)])
        five = [rnd.choice([0, rnd.randint(0, 50000)]) for _ in range(5)]
        pct = rnd.choice(["25", "10", "7.1", "0", "100", "33.3"])
        tot = _legacy_tot(pretax, cost, five)
        got = R.new_tot_fields(tot, pct)
        exp = P.quote_profit(pretax, cost, int(round(cost * 0.05)), five, pct, 2)
        assert got["adminCost"] == exp["adminCost"], (pretax, cost, pct)
        assert got["charityDonation"] == exp["charityDonation"]
        assert got["totalIndirect"] == exp["totalIndirect"]
        assert got["netProfit"] == round(exp["netProfit"]) or abs(got["netProfit"] - exp["netProfit"]) <= 0.5
        assert abs(got["netMarginPct"] - exp["netMarginPct"]) <= 0.05 + 1e-9


def test_dry_run_writes_nothing(db):
    h = _sha(db)
    rc, out = _run("--db", db, "report")
    assert rc == 0 and "重算 3 張" in out, out
    rc, out = _run("--db", db, "recalc")                       # 沒有 --apply 也是 dry-run
    assert rc == 0 and "dry-run" in out
    assert _sha(db) == h


def test_apply_touches_only_unsettled_is_idempotent_and_rolls_back_bitwise(db, tmp_path):
    before = _rows(db)
    rc, out = _run("--db", db, "recalc", "--apply")
    assert rc == 0 and "已重算 3 張" in out, out
    assert [f for f in os.listdir(tmp_path) if ".pre_overhead_" in f], "沒有備份檔"
    after = _rows(db)
    for no in ("F1", "C1"):                                     # 已完結／已結案不動
        assert after[no] == before[no]
    for no in ("U1", "U2", "D1"):
        d = json.loads(after[no][0])
        t = d["tot"]
        if no == "D1":
            assert t["formulaVer"] == 2 and d["settlement"]["summary"] == {"netProfit": 1}      # 草稿精算 summary 不動
        else:
            assert t["formulaVer"] == 2 and t["overheadPct"] == 25 and d["overheadPct"] == 25
        assert t["_legacy"]["adminCost"] == json.loads(before[no][0])["tot"]["adminCost"]
        assert t["pretax"] == json.loads(before[no][0])["tot"]["pretax"]                    # 價格不動
        assert after[no][1] == t["netMarginPct"]
    assert json.loads(after["U2"][0])["tot"]["adminCost"] == 0                              # 直毛為負 ⇒ 管銷 0
    snap = _rows(db)
    rc, out = _run("--db", db, "recalc", "--apply")                                         # 冪等
    assert rc == 0 and "已重算 0 張" in out and _rows(db) == snap
    rc, out = _run("--db", db, "rollback", "--apply")
    assert rc == 0 and "已還原 3 張" in out, out
    assert _rows(db) == before                                                              # 逐位還原（含欄位與 JSON 字串）


def test_rollback_skips_cases_finalized_after_migration(db):
    _run("--db", db, "recalc", "--apply")
    c = sqlite3.connect(db)
    c.execute("UPDATE quotations SET settle_status='finalized' WHERE quote_no='U1'")
    c.commit()
    c.close()
    rc, out = _run("--db", db, "rollback", "--apply")
    assert "略過（遷移後已完結／結案）1 張" in out, out
    assert json.loads(_rows(db)["U1"][0])["tot"]["formulaVer"] == 2


def test_mode_defaults_to_legacy_and_needs_apply(db):
    rc, out = _run("--db", db, "mode")
    assert "= legacy" in out
    rc, out = _run("--db", db, "mode", "v2")
    assert "dry-run" in out and "= legacy" in _run("--db", db, "mode")[1]
    _run("--db", db, "mode", "v2", "--apply")
    assert "= v2" in _run("--db", db, "mode")[1]
    rc, out = _run("--db", db, "mode", "bogus")
    assert rc == 2


def test_missing_db_refused_without_creating_file(tmp_path):
    p = str(tmp_path / "nope.db")
    rc, out = _run("--db", p, "report")
    assert rc == 2 and not os.path.exists(p)
