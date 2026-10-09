# -*- coding: utf-8 -*-
"""第 52 班：公益捐款改報價含稅 1% 的遷移（migrations_frozen/t52_charity + tools/charity_migrate.py）。

① 凍結算式 == 線上 `profit_guard.server_profit`（total 基數）：隨機種子＋.x5 平手向量（雙精度路徑，第 50 班教訓）② 四類資料：未精算 v2／未精算 v1／草稿精算／已完結／已結案
③ 冪等 ④ 回滾逐位還原（含 _recalc 還原）⑤ dry-run 不寫 ⑥ 備份 ⑦ 前置條件（管銷 v2＋標記）與 --set-total ⑧ 已結案 SHA256 前後相同。
"""
import hashlib
import json
import os
import random
import sqlite3
import subprocess
import sys
from decimal import Decimal

import pytest

from migrations_frozen.t52_charity import recalc as R
from modules.case import profit_guard as PG

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(BACKEND, "tools", "charity_migrate.py")


# ── ① 凍結 vs 線上 ────────────────────────────────────────────────────────────
def _quote(pretax, cost, tax_rate):
    return {"taxRate": tax_rate, "items": [{"type": "item", "qty": 1, "unitPrice": pretax, "amount": pretax, "cost": cost}], "discount": 0, "freight": 0}


def _live_v2_direct_tot(pretax, cost, tax_rate, pct):
    q = _quote(pretax, cost, tax_rate)
    tot = PG.server_totals(q, {})
    tot.update(PG.server_profit(q, pct, 2, pretax=tot["pretax"], total=tot["total"], charity_basis="direct"))
    return q, tot


def _check_equal(pretax, cost, tax_rate, pct):
    q, tot = _live_v2_direct_tot(pretax, cost, tax_rate, pct)
    live = PG.server_profit(q, pct, 2, pretax=tot["pretax"], total=tot["total"], charity_basis="total")
    frozen = R.new_tot_fields(tot)
    for k in ("charityDonation", "totalIndirect", "netProfit", "netMarginPct"):
        assert frozen[k] == live[k], (pretax, cost, tax_rate, pct, k, frozen[k], live[k])
        assert type(frozen[k]) == type(live[k]) or frozen[k] == live[k]
    return frozen, live


def test_frozen_equals_live_seeded():
    rnd = random.Random(20261010)
    n = 0
    for _ in range(3000):
        pretax = rnd.choice([rnd.randint(1, 5000), rnd.randint(1000, 300000), rnd.randint(300000, 8_000_000)])
        cost = rnd.choice([0, rnd.randint(0, pretax), rnd.randint(0, pretax * 2)])
        _check_equal(pretax, cost, rnd.choice([5, 0]), rnd.choice([0, 7.1, 12.5, 25, 33.3, 100, 7.5]))
        n += 1
    assert n == 3000


def _exact_pct_is_tie(pretax, cost, pct):
    """直接毛利／管銷／公益的『精確 Decimal』營業利益率剛好落在 x.x5（四捨五入的平手點）。"""
    q, tot = _live_v2_direct_tot(pretax, cost, 5, pct)
    new = R.new_tot_fields(tot)
    net = Decimal(str(tot["directProfit"])) - Decimal(str(tot["adminCost"])) - Decimal(str(new["charityDonation"]))
    exact = net / Decimal(str(tot["pretax"])) * 100
    return (exact * 10) % 1 == Decimal("0.5")


def test_frozen_equals_live_on_rounding_tie_vectors():
    found = 0
    for pretax in range(1000, 4001, 20):
        for cost in range(0, pretax, 35):
            if _exact_pct_is_tie(pretax, cost, 7.5):
                _check_equal(pretax, cost, 5, 7.5)
                found += 1
        if found >= 25:
            break
    assert found >= 5, "平手向量要找得到，否則這題沒有意義"
    _check_equal(2000, 895, 5, 7.5)                       # 第 50 班稽核的原案例（pretax 2000／成本 895／7.5%）
    _check_equal(2000, 895, 0, 7.5)


def test_charity_is_total_based_has_no_direct_floor_but_a_floor_on_negative_total():
    q, tot = _live_v2_direct_tot(100000, 150000, 5, 25)       # 虧損
    new = R.new_tot_fields(tot)
    assert tot["directProfit"] < 0 and new["charityDonation"] == 1050 and new["netProfit"] == tot["directProfit"] - tot["adminCost"] - 1050
    assert R.new_tot_fields(dict(tot, total=-5000))["charityDonation"] == 0, "含稅金額為負 ⇒ 0（不可變成收入）"
    assert R.new_tot_fields(dict(tot, total=0))["charityDonation"] == 0


def test_new_tot_fields_refuses_missing_inputs():
    _, tot = _live_v2_direct_tot(100000, 60000, 5, 25)
    for k in R.NEED:
        bad = dict(tot)
        bad.pop(k)
        with pytest.raises(ValueError):
            R.new_tot_fields(bad)
    with pytest.raises(ValueError):
        R.new_tot_fields(dict(tot, total=True))


# ── ② 資料庫情境 ───────────────────────────────────────────────────────────────
def _v2_tot(pretax=100000, cost=60000, pct=25):
    q, tot = _live_v2_direct_tot(pretax, cost, 5, pct)
    tot.update(formulaVer=2, overheadPct=pct)
    return tot


def _mk(path, rows, settings=None):
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE quotations(id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT, settle_status TEXT DEFAULT '',
                       deal_tag TEXT DEFAULT '', data_json TEXT, net_margin_pct REAL DEFAULT 0, updated_at TEXT DEFAULT '');
                       CREATE TABLE system_settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT DEFAULT '');""")
    for no, tot, st, tag in rows:
        c.execute("INSERT INTO quotations(quote_no, settle_status, deal_tag, data_json, net_margin_pct) VALUES(?,?,?,?,?)",
                  (no, st, tag, json.dumps({"tot": tot, "overheadPct": tot.get("overheadPct")}, ensure_ascii=False), tot.get("netMarginPct", 0)))
    for k, v in (settings if settings is not None else {"overhead_rule_mode": "v2", "overhead_migration_done": {"doneAt": "2026-10-09"}}).items():
        c.execute("INSERT INTO system_settings(key, value_json) VALUES(?,?)", (k, json.dumps(v)))
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


def _setting(path, key):
    c = sqlite3.connect(path)
    try:
        r = c.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None
    finally:
        c.close()


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    old_recalc = {"at": "20261009_230000", "by": "t48", "note": "口徑更新：管銷分攤改為直接毛利×25%"}
    t1 = _v2_tot(); t1["_recalc"] = old_recalc
    t2 = _v2_tot(200000, 120000, 30)
    t3 = _v2_tot(100000, 150000, 25)                          # 虧損案
    v1 = {"pretax": 100000, "tax": 5000, "total": 105000, "directProfit": 37000, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 10370,
          "netProfit": 26630, "netMarginPct": 26.6}           # 尚未是新管銷口徑
    _mk(p, [("Q-OPEN-1", t1, "", ""), ("Q-OPEN-2", t2, "draft", ""), ("Q-LOSS", t3, "", ""), ("Q-V1", v1, "", ""),
            ("Q-FIN", _v2_tot(), "finalized", ""), ("Q-CLOSED", _v2_tot(300000, 100000, 20), "", "已結案")])
    return p


def test_report_is_read_only_and_counts(db):
    before = _sha(db)
    rc, out = _run("--db", db, "report", "--csv", db + ".csv")
    assert rc == 0, out
    assert _sha(db) == before, "dry-run 不寫庫"
    assert '"recalc": 3' in out and '"skip_settled": 2' in out and '"skip_not_v2": 1' in out, out
    assert "達標件數" in out and "Q-V1" in out
    assert os.path.isfile(db + ".csv")
    rc, out = _run("--db", db, "recalc")
    assert rc == 0 and "dry-run" in out and _sha(db) == before


def test_recalc_requires_overhead_v2_and_marker_and_set_total(db, tmp_path):
    rc, out = _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")
    assert rc == 0, out                                       # fixture 預設已具備前置條件
    p2 = str(tmp_path / "noprereq.db")
    _mk(p2, [("Q1", _v2_tot(), "", "")], settings={})
    before = _sha(p2)
    rc, out = _run("--db", p2, "recalc", "--apply", "--set-total", "--no-backup")
    assert rc == 2 and "前置條件" in out and _sha(p2) == before
    p3 = str(tmp_path / "nomarker.db")
    _mk(p3, [("Q1", _v2_tot(), "", "")], settings={"overhead_rule_mode": "v2"})
    assert _run("--db", p3, "recalc", "--apply", "--set-total", "--no-backup")[0] == 2
    p4 = str(tmp_path / "nosettotal.db")
    _mk(p4, [("Q1", _v2_tot(), "", "")])
    before = _sha(p4)
    rc, out = _run("--db", p4, "recalc", "--apply", "--no-backup")
    assert rc == 2 and "--set-total" in out and _sha(p4) == before
    assert _run("--db", p4, "mode", "total", "--apply")[0] == 2, "沒有公益標記不能直接切 total"


def test_recalc_apply_changes_only_open_v2_quotes_and_leaves_settled_bit_identical(db):
    before = _rows(db)
    rc, out = _run("--db", db, "recalc", "--apply", "--set-total")
    assert rc == 0 and "已重算 3 張" in out and "備份" in out, out
    after = _rows(db)
    for no in ("Q-FIN", "Q-CLOSED", "Q-V1"):
        assert after[no] == before[no], no + " 不可被動到（已結案／已精算 SHA 相同；未是新口徑的也不動）"
    for no in ("Q-OPEN-1", "Q-OPEN-2", "Q-LOSS"):
        b, a = json.loads(before[no][0])["tot"], json.loads(after[no][0])["tot"]
        assert a["charityBasis"] == "total" and a["charityDonation"] == R.new_tot_fields(b)["charityDonation"]
        assert a["_legacyCharity"]["charityDonation"] == b["charityDonation"] and a["_legacyCharity"]["netMarginPctCol"] == before[no][1]
        assert a["pretax"] == b["pretax"] and a["tax"] == b["tax"] and a["total"] == b["total"] and a["adminCost"] == b["adminCost"], "價格與管銷不動"
        assert a["totalIndirect"] == a["adminCost"] + a["charityDonation"]
        assert after[no][1] == a["netMarginPct"]
        assert "公益捐款改為報價含稅" in a["_recalc"]["note"]
    assert json.loads(after["Q-LOSS"][0])["tot"]["charityDonation"] == 1050
    assert _setting(db, "charity_basis_mode") == "total" and _setting(db, "charity_migration_done")["recalculated"] == 3
    assert any(f.startswith("t.db.pre_charity_") and f.endswith(".bak") for f in os.listdir(os.path.dirname(db))), "自動備份"
    assert set(_setting(db, "charity_legacy_snapshot")) == {"Q-OPEN-1", "Q-OPEN-2", "Q-LOSS"}


def test_recalc_is_idempotent(db):
    assert _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")[0] == 0
    once = _rows(db)
    rc, out = _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")
    assert rc == 0 and "已重算 0 張" in out and _rows(db) == once


def test_rollback_restores_bit_identical_and_clears_mode_and_marker(db):
    before = _rows(db)
    assert _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")[0] == 0
    rc, out = _run("--db", db, "rollback")
    assert rc == 0 and '"restore": 3' in out and "dry-run" in out
    rc, out = _run("--db", db, "rollback", "--apply", "--no-backup")
    assert rc == 0 and "已還原 3 張" in out, out
    after = _rows(db)
    for no in before:
        b, a = json.loads(before[no][0]), json.loads(after[no][0])
        assert a["tot"] == b["tot"] and after[no][1] == before[no][1], no
    assert _setting(db, "charity_basis_mode") == "direct" and _setting(db, "charity_migration_done") is None


def test_rollback_does_not_touch_quotes_settled_or_edited_since(db):
    assert _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")[0] == 0
    c = sqlite3.connect(db)
    c.execute("UPDATE quotations SET settle_status='finalized' WHERE quote_no='Q-OPEN-1'")          # 遷移後才完結
    r = c.execute("SELECT data_json FROM quotations WHERE quote_no='Q-OPEN-2'").fetchone()
    d = json.loads(r[0])
    d["tot"]["netProfit"] += 1                                                                      # 遷移後被編輯
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no='Q-OPEN-2'", (json.dumps(d),))
    c.commit()
    c.close()
    rc, out = _run("--db", db, "rollback")
    assert "skip_settled_since" in out and "skip_edited_since" in out and '"restore": 1' in out, out
    snapshot_before = _rows(db)
    assert _run("--db", db, "rollback", "--apply", "--no-backup")[0] == 0
    after = _rows(db)
    assert after["Q-OPEN-1"] == snapshot_before["Q-OPEN-1"] and after["Q-OPEN-2"] == snapshot_before["Q-OPEN-2"]
    assert json.loads(after["Q-LOSS"][0])["tot"].get("charityBasis") is None


def test_mode_command_and_marker_semantics(db):
    rc, out = _run("--db", db, "mode")
    assert rc == 0 and "direct" in out
    assert _run("--db", db, "mode", "total", "--apply")[0] == 2
    assert _run("--db", db, "recalc", "--apply", "--set-total", "--no-backup")[0] == 0
    assert _run("--db", db, "mode", "direct", "--apply")[0] == 0
    assert _setting(db, "charity_basis_mode") == "direct" and _setting(db, "charity_migration_done") is None, "退回 direct 就刪標記"
    assert _run("--db", db, "mode", "total", "--apply")[0] == 2, "標記被刪 ⇒ 要重新 recalc"
    assert _run("--db", db, "mode", "oops")[0] == 2


def test_tool_refuses_a_missing_db_and_never_creates_one(tmp_path):
    ghost = str(tmp_path / "ghost.db")
    rc, _ = _run("--db", ghost, "report")
    assert rc != 0 and not os.path.exists(ghost)
