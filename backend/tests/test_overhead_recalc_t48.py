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
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    assert rc == 0 and "已重算 3 張" in out and "模式已設 v2" in out, out
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
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2")                                         # 冪等
    assert rc == 0 and "已重算 0 張" in out and _rows(db) == snap
    rc, out = _run("--db", db, "rollback", "--apply")
    assert rc == 0 and "已還原 3 張" in out, out
    assert _rows(db) == before                                                              # 逐位還原（含欄位與 JSON 字串）


def test_rollback_skips_cases_finalized_after_migration(db):
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    c = sqlite3.connect(db)
    c.execute("UPDATE quotations SET settle_status='finalized' WHERE quote_no='U1'")
    c.commit()
    c.close()
    rc, out = _run("--db", db, "rollback", "--apply")
    assert '"skip_settled_since": 1' in out, out
    assert json.loads(_rows(db)["U1"][0])["tot"]["formulaVer"] == 2


def test_mode_defaults_to_legacy_and_needs_apply(db):
    rc, out = _run("--db", db, "mode")
    assert "= legacy" in out
    rc, out = _run("--db", db, "mode", "v2")
    assert "dry-run" in out and "= legacy" in _run("--db", db, "mode")[1]
    assert _run("--db", db, "mode", "v2", "--apply")[0] == 2               # 沒有標記 ⇒ 拒絕
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    assert "= v2" in _run("--db", db, "mode")[1]
    rc, out = _run("--db", db, "mode", "bogus")
    assert rc == 2


def test_missing_db_refused_without_creating_file(tmp_path):
    p = str(tmp_path / "nope.db")
    rc, out = _run("--db", p, "report")
    assert rc == 2 and not os.path.exists(p)


# ── 獨立稽核 #1 的修補（第 48 班）──────────────────────────────────────────────

def _set_root_pct(path, quote_no, pct):
    c = sqlite3.connect(path)
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()[0])
    d["overheadPct"] = pct
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), quote_no))
    c.commit()
    c.close()


def test_per_quote_custom_pct_is_kept_not_reset_to_default(db):
    _set_root_pct(db, "U1", 30)
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    assert rc == 0, out
    d = json.loads(_rows(db)["U1"][0])
    assert d["overheadPct"] == 30 and d["tot"]["overheadPct"] == 30
    exp = P.quote_profit(1000000, 600000, 30000, [1000, 0, 500, 0, 250], 30, 2)
    assert d["tot"]["adminCost"] == exp["adminCost"] == 111000         # 直毛 370000×30%
    assert json.loads(_rows(db)["U2"][0])["tot"]["overheadPct"] == 25   # 沒自己的百分比 ⇒ 預設
    _run("--db", db, "rollback", "--apply")
    assert json.loads(_rows(db)["U1"][0]).get("overheadPct") == 30       # 回滾後自己的百分比仍在


def test_recalc_refused_unless_mode_v2_or_set_in_same_txn(db):
    h = _sha(db)
    rc, out = _run("--db", db, "recalc", "--apply")
    assert rc == 2 and "拒絕" in out and _sha(db) == h
    rc, out = _run("--db", db, "mode", "v2", "--apply")                  # 沒有完成標記 ⇒ 獨立切 v2 也拒絕
    assert rc == 2 and "完成標記" in out and _sha(db) == h
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    assert rc == 0 and "已重算 3 張" in out


def _setting(path, key):
    c = sqlite3.connect(path)
    r = c.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    c.close()
    return None if r is None else json.loads(r[0])


def test_migration_done_marker_written_in_same_txn_and_removed_by_rollback(db):
    assert _setting(db, "overhead_migration_done") is None
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    m = _setting(db, "overhead_migration_done")
    assert m["recalculated"] == 3 and m["skipped"] == 2 and m["doneAt"] and m["by"], m          # 形狀＝ab 的契約
    assert _setting(db, "overhead_rule_mode") == "v2"
    rc, out = _run("--db", db, "mode", "v2", "--apply")                   # 有標記 ⇒ 允許
    assert rc == 0
    _run("--db", db, "rollback", "--apply")
    assert _setting(db, "overhead_migration_done") is None and _setting(db, "overhead_rule_mode") == "legacy"


@pytest.mark.parametrize("bad", ["abc", "250", "-5", "7.25", "1e2", ""])
def test_pct_is_validated(db, bad):
    if bad == "":
        pytest.skip("空字串＝未給")
    h = _sha(db)
    rc, out = _run("--db", db, "recalc", "--pct", bad, "--apply", "--set-mode-v2")
    assert rc == 2 and _sha(db) == h, out


def test_stale_plan_never_overwrites_a_row_finalized_after_planning(db):
    """計畫在交易外算好 ⇒ U1 被別人完結 ⇒ 套用時不可寫 U1（重檢查已精算），其餘照寫且用當下的值。"""
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    stale = R.plan(c, "25")
    other = sqlite3.connect(db)
    other.execute("UPDATE quotations SET settle_status='finalized' WHERE quote_no='U1'")
    d = json.loads(other.execute("SELECT data_json FROM quotations WHERE quote_no='U2'").fetchone()[0])
    d["tot"]["totalIndirect"] = d["tot"]["totalIndirect"] + 777              # 計畫之後 U2 又被存檔：五項間接成本變了
    other.execute("UPDATE quotations SET data_json=? WHERE quote_no='U2'", (json.dumps(d, ensure_ascii=False),))
    other.commit()
    other.close()
    before_u1 = _rows(db)["U1"]
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    n, skipped = R.apply_plan(c, stale, "25", "t", {})
    c.execute("COMMIT")
    c.close()
    assert skipped == 1 and n == 2
    assert _rows(db)["U1"] == before_u1                                      # 已完結的沒被碰
    u2 = json.loads(_rows(db)["U2"][0])["tot"]
    exp = R.new_tot_fields(dict(json.loads(_rows(db)["U2"][0])["tot"], **u2["_legacy"]), "25")
    assert u2["totalIndirect"] == exp["totalIndirect"] and u2["_legacy"]["totalIndirect"] == d["tot"]["totalIndirect"]   # 用的是『當下』的值


def test_rollback_survives_a_form_resave_that_drops_tot_legacy(db):
    """表單重存會重建 tot（丟掉 _legacy／_recalc）⇒ 回滾改用伺服器端快照；值沒變就能還原。"""
    before = _rows(db)
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    c = sqlite3.connect(db)
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no='U1'").fetchone()[0])
    d["tot"].pop("_legacy"), d["tot"].pop("_recalc")
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no='U1'", (json.dumps(d, ensure_ascii=False),))
    c.commit()
    c.close()
    rc, out = _run("--db", db, "rollback", "--apply")
    assert "已還原 3 張" in out, out
    assert json.loads(_rows(db)["U1"][0])["tot"]["adminCost"] == json.loads(before["U1"][0])["tot"]["adminCost"]


def test_rollback_reports_edited_since_and_not_v2(db):
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    c = sqlite3.connect(db)
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no='U1'").fetchone()[0])
    d["tot"]["netProfit"] += 1                                               # 遷移後有人改了
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no='U1'", (json.dumps(d, ensure_ascii=False),))
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no='U2'").fetchone()[0])
    d["tot"].pop("formulaVer")                                               # 舊式表單重存退回舊基準
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no='U2'", (json.dumps(d, ensure_ascii=False),))
    c.commit()
    c.close()
    rc, out = _run("--db", db, "rollback")
    assert "skip_edited_since" in out and "skip_not_v2" in out and '"restore": 1' in out, out


def test_inconsistent_tot_with_negative_other_indirect_is_skipped_not_written(tmp_path):
    p = str(tmp_path / "n.db")
    bad = _legacy_tot(1000000, 600000, [0] * 5)
    bad["totalIndirect"] = bad["adminCost"] + bad["charityDonation"] - 500       # 五項為負：不一致
    _mk(p, [("B1", bad, "", "", None)])
    h = _sha(p)
    rc, out = _run("--db", p, "recalc", "--apply", "--set-mode-v2")
    assert rc == 0 and "已重算 0 張" in out and "資料不足" in out
    c = sqlite3.connect(p)
    assert c.execute("SELECT value_json FROM system_settings WHERE key='overhead_rule_mode'").fetchone()[0] == '"v2"'   # 模式仍在同交易設定
    c.close()
    assert json.loads(_rows(p)["B1"][0])["tot"] == bad


def test_mode_legacy_deletes_the_marker_so_a_later_v2_needs_a_fresh_recalc(db):
    _run("--db", db, "recalc", "--apply", "--set-mode-v2")
    assert _setting(db, "overhead_migration_done") is not None
    assert _run("--db", db, "mode", "legacy", "--apply")[0] == 0
    assert _setting(db, "overhead_migration_done") is None and _setting(db, "overhead_rule_mode") == "legacy"
    assert _run("--db", db, "mode", "v2", "--apply")[0] == 2                   # 標記被刪 ⇒ 不能直接切回 v2
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2")           # 重新 recalc（冪等：已是新口徑的跳過）才能再切
    assert rc == 0 and _setting(db, "overhead_rule_mode") == "v2" and _setting(db, "overhead_migration_done") is not None


def test_report_lists_unsettled_quotes_with_non_zero_legacy_indirect_costs_and_recalc_drops_them(db, tmp_path):
    """使用者 2026-10-09：五項間接成本不再輸入／計入。report 要列出舊值非零的未精算單；recalc 後 totalIndirect＝管銷＋公益（五項不計），舊值留在 _legacy；已精算／結案不動。"""
    csv_path = str(tmp_path / "r.csv")
    rc, out = _run("--db", db, "report", "--csv", csv_path)
    assert rc == 0, out
    assert "舊『五項間接成本』非零的未精算單 2 張" in out and "舊間接成本 U1" in out and "舊間接成本 D1" in out and "合計 3,500" in out, out
    assert "舊間接成本 U2" not in out and "舊間接成本 F1" not in out and "舊間接成本 C1" not in out, "全 0 的不列；已精算／結案不是遷移對象"
    rows = open(csv_path, encoding="utf-8-sig").read().splitlines()
    assert rows[0].endswith("legacy_indirect")
    u1 = [r for r in rows if r.startswith("U1,")][0].split(",")
    assert u1[-1] == "1750"
    rc, out = _run("--db", db, "recalc", "--apply", "--set-mode-v2", "--no-backup")
    assert rc == 0, out
    d = {no: json.loads(v[0]) for no, v in _rows(db).items()}
    t = d["U1"]["tot"]
    assert t["totalIndirect"] == t["adminCost"] + t["charityDonation"], "新口徑：五項不計"
    assert t["_legacy"]["totalIndirect"] > t["totalIndirect"], "舊值留在 _legacy（回滾用）"
    assert d["F1"]["tot"].get("formulaVer") is None and d["C1"]["tot"].get("formulaVer") is None, "已精算／結案不動"
