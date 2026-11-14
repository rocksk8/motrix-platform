# -*- coding: utf-8 -*-
"""T87 A1 M1：正式機半自動套用（backend/tools/auto_apply.py＋儀表板預演閘門）。

不起 PowerShell、不連服務：套用動作、HTTP 探測、預演的遷移工具都用假的；資料庫、安裝目錄全是 tmp 的真檔案。
涵蓋：狀態擷取與差異、預演（不留 pyc、副本一定刪、-B）、預期差異比對、事後驗證各項（含反向控制）、
套用串接（預檢擋、驗證失敗不回滾、rolled_back 值域）、稽核雜湊鏈、報告、儀表板預演閘門。
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import auto_apply as AA  # noqa: E402

from tests.platform.test_deploy_dashboard_delivery_2026_09_28 import D, dd, env  # noqa: E402,F401  （env 是 fixture）

COMMIT = "c" * 40


# ── 假的正式機 ───────────────────────────────────────────────────────────

def make_prod(tmp, module_version="1.0.0"):
    root = tmp / "prod"
    backend = root / "backend"
    (backend / "logs").mkdir(parents=True)
    (backend / "modules" / "alpha").mkdir(parents=True)
    (backend / "modules" / "alpha" / "module.json").write_text(json.dumps({"key": "alpha", "version": module_version}), encoding="utf-8")
    conn = sqlite3.connect(backend / "motrix_erp.db")
    conn.executescript("""
        CREATE TABLE schema_version(id INTEGER PRIMARY KEY, version INTEGER);
        INSERT INTO schema_version VALUES (1, 10);
        CREATE TABLE module_schema_versions(module TEXT PRIMARY KEY, version INTEGER, applied_at TEXT);
        INSERT INTO module_schema_versions VALUES ('alpha', 1, 't');
        CREATE TABLE system_settings(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
        INSERT INTO system_settings VALUES ('company_name', '"X"', 't');
        INSERT INTO system_settings VALUES ('secret_like', '"hunter2"', 't');
        CREATE TABLE audit_log(id INTEGER PRIMARY KEY, at TEXT, user_id INTEGER, username TEXT, display_name TEXT,
                               action TEXT, target_type TEXT, target_id TEXT, target_label TEXT, detail TEXT);
        CREATE TABLE cases(id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO cases VALUES (1, '案件甲');
    """)
    conn.commit()
    conn.close()
    return root


def prod_db(root):
    return str(root / "backend" / "motrix_erp.db")


def migrate(db, add_column=True, add_setting=None, bump_module=True):
    """假的遷移：與真遷移同形——加欄位、升模組版號、可選多寫一個設定鍵。"""
    conn = sqlite3.connect(db)
    if add_column:
        conn.execute("ALTER TABLE cases ADD COLUMN stage TEXT DEFAULT ''")
    if bump_module:
        conn.execute("UPDATE module_schema_versions SET version=2 WHERE module='alpha'")
    conn.execute("UPDATE schema_version SET version=11 WHERE id=1")
    if add_setting:
        conn.execute("INSERT INTO system_settings VALUES (?, '1', 't')", (add_setting,))
    conn.commit()
    conn.close()


def make_staged(tmp, with_tool=True):
    staged = tmp / "staged"
    (staged / "payload" / "backend" / "tools").mkdir(parents=True)
    if with_tool:
        (staged / "payload" / "backend" / "tools" / "migrate_like_startup.py").write_text("# fake\n", encoding="utf-8")
    (staged / "package.sha256").write_text("deadbeef  payload/x\n", encoding="utf-8")
    (staged / "delivery.json").write_text(json.dumps({"commit": COMMIT}), encoding="utf-8")
    return staged


def fake_runner(real_db, **migrate_kw):
    """預演用的假執行器：只准動 `--db` 指到的副本；記下收到的 cmd／env。"""
    seen = {}

    def run(cmd, env):
        seen["cmd"], seen["env"] = cmd, env
        db = cmd[cmd.index("--db") + 1]
        assert os.path.abspath(db) != os.path.abspath(real_db), "預演不可以直接動正式庫"
        migrate(db, **migrate_kw)
        return 0, "modules=like_startup\nMIGRATE_LIKE_STARTUP_OK\n"
    run.seen = seen
    return run


def ok_http(status_by_path=None):
    table = status_by_path or {}

    def f(url, method="GET", timeout=8):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1] if "/" in url.split("://", 1)[1] else "/"
        return table.get((method, path), table.get(path, 200))
    return f


def write_runtime_files(root, module_version="1.0.0", state="loaded", loaded_version=None, log_text="MOTRIX ERP starting\nok\n",
                        commit=COMMIT, started_at=None):
    logs = root / "backend" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "module_states.json").write_text(json.dumps({
        "pid": 1, "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
        "modules": [{"key": "alpha", "state": state, "version": loaded_version or module_version, "reason": ""}]}), encoding="utf-8")
    (logs / "server.log").write_text(log_text, encoding="utf-8")
    (root / "backend" / ".deployed_commit.json").write_text(json.dumps({"commit": commit}), encoding="utf-8")


def rehearsed(tmp, root, **kw):
    staged = make_staged(tmp)
    rh = AA.rehearse(str(staged), str(root), str(tmp / "work"), run=fake_runner(prod_db(root), **kw))
    assert rh["ok"], rh
    return staged, rh


# ── 狀態擷取／差異 ───────────────────────────────────────────────────────

def test_capture_state_has_structure_but_no_row_data_or_setting_values(tmp_path):
    root = make_prod(tmp_path)
    st = AA.capture_state(prod_db(root), watch_keys=("company_name",))
    blob = json.dumps(st, ensure_ascii=False)
    assert st["schema_version"] == 10 and st["modules"] == {"alpha": 1}
    assert "cases" in st["columns"] and "name" in st["columns"]["cases"]
    assert "company_name" in st["settings_keys"]
    assert "案件甲" not in blob and "hunter2" not in blob and '"X"' not in blob, "只存結構與鍵名，不存資料列與設定值"
    assert st["watch"]["company_name"] and st["watch"]["company_name"] != '"X"', "被監看的鍵只存雜湊"


def test_capture_state_is_read_only_and_raises_when_db_missing(tmp_path):
    root = make_prod(tmp_path)
    before = Path(prod_db(root)).read_bytes()
    AA.capture_state(prod_db(root))
    assert Path(prod_db(root)).read_bytes() == before
    with pytest.raises(Exception):
        AA.capture_state(str(tmp_path / "nope.db"))        # 讀不到＝丟例外，不吞成空狀態


def test_diff_state_reports_added_column_module_bump_and_schema_version(tmp_path):
    root = make_prod(tmp_path)
    b = AA.capture_state(prod_db(root))
    migrate(prod_db(root), add_setting="migration_x_done")
    d = AA.diff_state(b, AA.capture_state(prod_db(root)))
    assert d["schema_version"] == [10, 11]
    assert d["modules"]["changed"] == {"alpha": [1, 2]}
    assert d["columns"]["cases"]["added"] == ["stage"]
    assert d["settings"]["added"] == ["migration_x_done"]
    lines = AA.summarize_diff(d)
    assert any("schema_version" in x for x in lines) and any("stage" in x for x in lines)
    assert not AA.diff_is_empty(d)
    assert AA.diff_is_empty(AA.diff_state(b, b))


def test_integrity_check_ok_and_detects_garbage(tmp_path):
    root = make_prod(tmp_path)
    assert AA.integrity_check(prod_db(root)) == "ok"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite file" * 200)
    with pytest.raises(Exception):
        AA.integrity_check(str(bad))


# ── 預演 ────────────────────────────────────────────────────────────────

def test_rehearse_runs_on_a_copy_gets_expected_diff_and_cleans_up(tmp_path):
    root = make_prod(tmp_path)
    before_bytes = Path(prod_db(root)).read_bytes()
    run = fake_runner(prod_db(root))
    staged = make_staged(tmp_path)
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "work"), run=run)
    assert rh["ok"] and rh["expected_diff"]["columns"]["cases"]["added"] == ["stage"]
    assert rh["summary"] and rh["digest"] and rh["pkg_digest"] == AA.package_digest(str(staged))
    assert Path(prod_db(root)).read_bytes() == before_bytes, "預演不動正式庫"
    assert not (tmp_path / "work").exists() or not any((tmp_path / "work").iterdir()), "副本與暫存一定刪"
    assert "-B" in run.seen["cmd"] and run.seen["env"]["PYTHONDONTWRITEBYTECODE"] == "1", "不得在暫存包留下 .pyc"
    assert "--license" not in run.seen["cmd"], "沒有 license.key 就不帶 --license"


def test_rehearse_removes_pyc_left_in_the_staged_payload_and_says_so(tmp_path):
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)

    def run(cmd, env):
        migrate(cmd[cmd.index("--db") + 1])
        pc = staged / "payload" / "backend" / "tools" / "__pycache__"
        pc.mkdir()
        (pc / "x.cpython-312.pyc").write_bytes(b"\0")
        return 0, "MIGRATE_LIKE_STARTUP_OK"
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "work"), run=run)
    assert rh["ok"] and any("pyc" in n for n in rh["notes"])
    assert not (staged / "payload" / "backend" / "tools" / "__pycache__").exists()


def test_rehearse_failure_is_not_ok_and_still_cleans_the_copy(tmp_path):
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)

    def run(cmd, env):
        return 2, "boom\nMIGRATE_LIKE_STARTUP_FAIL 1\n" + "x" * 1000
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "work"), run=run)
    assert not rh["ok"] and rh["digest"] is None and any("預演失敗" in p for p in rh["problems"])
    assert len(rh["tool_tail"]) <= 400
    assert not any((tmp_path / "work").glob("**/*.db")) if (tmp_path / "work").exists() else True


def test_rehearse_rc_exit_zero_without_the_ok_marker_is_not_a_pass(tmp_path):
    """反向控制：結束碼 0 但沒印 MIGRATE_LIKE_STARTUP_OK（例如工具被換成空殼）⇒ 不放行。"""
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "work"), run=lambda cmd, env: (0, "nothing"))
    assert not rh["ok"]


def test_rehearse_refuses_when_package_has_no_tool_or_no_db(tmp_path):
    root = make_prod(tmp_path)
    (tmp_path / "a").mkdir()
    no_tool = make_staged(tmp_path / "a", with_tool=False)
    rh = AA.rehearse(str(no_tool), str(root), str(tmp_path / "w"))
    assert not rh["ok"] and any("migrate_like_startup" in p for p in rh["problems"])
    (tmp_path / "b").mkdir()
    staged = make_staged(tmp_path / "b")
    empty = tmp_path / "empty"
    (empty / "backend").mkdir(parents=True)
    rh = AA.rehearse(str(staged), str(empty), str(tmp_path / "w"))
    assert not rh["ok"] and any("找不到正式庫" in p for p in rh["problems"])


def test_consent_digest_changes_with_package_or_expected_diff(tmp_path):
    d1 = {"a": 1}
    base = AA.consent_digest("p1", d1)
    assert base == AA.consent_digest("p1", {"a": 1})
    assert base != AA.consent_digest("p2", d1) and base != AA.consent_digest("p1", {"a": 2})


def test_package_digest_changes_when_signed_files_change(tmp_path):
    staged = make_staged(tmp_path)
    a = AA.package_digest(str(staged))
    (staged / "package.sha256").write_text("other\n", encoding="utf-8")
    b = AA.package_digest(str(staged))
    (staged / "delivery.json").write_text("{}", encoding="utf-8")
    c = AA.package_digest(str(staged))
    assert len({a, b, c}) == 3


# ── 預期差異比對 ─────────────────────────────────────────────────────────

def _diffs(tmp_path, **kw):
    root = make_prod(tmp_path)
    before = AA.capture_state(prod_db(root))
    copy = tmp_path / "copy.db"
    AA._online_backup(prod_db(root), str(copy))
    migrate(str(copy), **kw)
    expected = AA.diff_state(before, AA.capture_state(str(copy)))
    return root, before, expected


def test_compare_diffs_identical_change_is_clean(tmp_path):
    root, before, expected = _diffs(tmp_path)
    migrate(prod_db(root))
    fails, warns = AA.compare_diffs(expected, AA.diff_state(before, AA.capture_state(prod_db(root))))
    assert fails == [] and warns == []


def test_compare_diffs_expected_change_that_did_not_happen_fails(tmp_path):
    root, before, expected = _diffs(tmp_path)
    migrate(prod_db(root), add_column=False)              # 正式機少了欄位
    fails, _ = AA.compare_diffs(expected, AA.diff_state(before, AA.capture_state(prod_db(root))))
    assert any("stage" in f for f in fails)


def test_compare_diffs_unexpected_extra_change_fails_and_migration_mark_fails_other_setting_warns(tmp_path):
    root, before, expected = _diffs(tmp_path)
    migrate(prod_db(root), add_setting="migration_surprise_done")
    fails, _ = AA.compare_diffs(expected, AA.diff_state(before, AA.capture_state(prod_db(root))))
    assert any("migration_surprise_done" in f for f in fails)
    root2, before2, expected2 = _diffs(tmp_path / "second")
    migrate(prod_db(root2), add_setting="ordinary_runtime_key")
    fails2, warns2 = AA.compare_diffs(expected2, AA.diff_state(before2, AA.capture_state(prod_db(root2))))
    assert fails2 == [] and any("ordinary_runtime_key" in w for w in warns2)


def test_compare_diffs_watched_setting_changed_by_apply_fails(tmp_path):
    root = make_prod(tmp_path)
    before = AA.capture_state(prod_db(root), ("company_name",))
    expected = AA.diff_state(before, before)
    conn = sqlite3.connect(prod_db(root))
    conn.execute("UPDATE system_settings SET value_json='\"Y\"' WHERE key='company_name'")
    conn.commit()
    conn.close()
    fails, _ = AA.compare_diffs(expected, AA.diff_state(before, AA.capture_state(prod_db(root), ("company_name",))))
    assert any("company_name" in f for f in fails)


# ── 預檢、停機估計、預期檔 ───────────────────────────────────────────────

def test_precheck_passes_and_blocks_on_low_disk_missing_db_and_corrupt_db(tmp_path):
    root = make_prod(tmp_path)
    assert AA.precheck(str(root)) == []
    class U:                                            # noqa: E306
        free = 10
    assert any("磁碟" in p for p in AA.precheck(str(root), disk_usage=lambda p: U))
    assert AA.precheck(str(tmp_path / "nowhere"))[0].startswith("找不到正式庫")
    bad = make_prod(tmp_path / "bad")
    Path(prod_db(bad)).write_bytes(b"garbage" * 4000)
    assert any("integrity_check" in p for p in AA.precheck(str(bad)))


def test_estimate_downtime_uses_only_successful_runs(tmp_path):
    root = make_prod(tmp_path)
    logs = root / "backend" / "logs"
    for i, (st, a, b) in enumerate([("success", "2026-11-10 10:00:00", "2026-11-10 10:05:00"),
                                    ("failed", "2026-11-11 10:00:00", "2026-11-11 11:00:00"),
                                    ("success", "2026-11-12 10:00:00", "2026-11-12 10:09:00")]):
        (logs / ("apply_update_2026111%d_100000.result.json" % i)).write_text(
            json.dumps({"status": st, "started_at": a, "finished_at": b}), encoding="utf-8")
    est = AA.estimate_downtime(str(root))
    assert est["samples"] == 2 and est["max"] == 540 and est["typical"] in (300, 540)
    assert AA.estimate_downtime(str(tmp_path / "none"))["samples"] == 0


def test_load_expectations_missing_and_unreadable_are_noted_not_passed_silently(tmp_path):
    ex, notes = AA.load_expectations(str(tmp_path))
    assert ex == {} and any("沒有附 a1_expectations.json" in n for n in notes)
    p = tmp_path / "backend"
    p.mkdir()
    (p / "a1_expectations.json").write_text("{not json", encoding="utf-8")
    ex, notes = AA.load_expectations(str(tmp_path))
    assert ex == {} and any("讀不懂" in n for n in notes)
    (p / "a1_expectations.json").write_text(json.dumps({"pages": ["/"]}), encoding="utf-8")
    assert AA.load_expectations(str(tmp_path)) == ({"pages": ["/"]}, [])


# ── 事後驗證 ────────────────────────────────────────────────────────────

def _since():
    """套用開始時間：往前 30 秒，避免 module_states.json 的 started_at（只到秒）剛好落在秒邊界上被判成「更早」。"""
    return datetime.now() - timedelta(seconds=30)


def _verify(tmp_path, mutate=None, expectations=None, http=None, **rt):
    root = make_prod(tmp_path)
    before = AA.capture_state(prod_db(root))
    copy = tmp_path / "copy.db"
    AA._online_backup(prod_db(root), str(copy))
    migrate(str(copy))
    expected = AA.diff_state(before, AA.capture_state(str(copy)))
    migrate(prod_db(root))
    write_runtime_files(root, **rt)
    if mutate:
        mutate(root)
    return AA.verify_after(str(root), "https://127.0.0.1:666", before, expected, expectations or {}, {"commit": COMMIT},
                           http_status=http or ok_http(), apply_started=_since())


def test_verify_after_all_good(tmp_path):
    v = _verify(tmp_path)
    assert v["ok"], v["items"]
    assert {i["id"] for i in v["items"]} >= {"ping", "integrity", "db_diff", "modules", "logs", "deployed_commit"}


def test_verify_after_ping_failure_fails(tmp_path):
    v = _verify(tmp_path, http=ok_http({"/api/ping": 500}))
    assert not v["ok"] and not next(i for i in v["items"] if i["id"] == "ping")["ok"]


def test_verify_after_module_version_mismatch_and_failed_module_fail(tmp_path):
    v = _verify(tmp_path, loaded_version="0.9.0")
    assert not next(i for i in v["items"] if i["id"] == "modules")["ok"]
    v = _verify(tmp_path / "f", state="failed")
    assert not next(i for i in v["items"] if i["id"] == "modules")["ok"]


def test_verify_after_stale_module_states_is_not_this_start(tmp_path):
    """module_states.json 的時間早於套用開始 ⇒ 不是這次啟動寫的（服務沒重啟成功）⇒ 失敗。"""
    v = _verify(tmp_path, started_at="2020-01-01T00:00:00")
    assert not next(i for i in v["items"] if i["id"] == "modules")["ok"]


def test_verify_after_traceback_in_log_after_last_start_fails_but_before_it_does_not(tmp_path):
    v = _verify(tmp_path, log_text="MOTRIX ERP starting\nTraceback (most recent call last):\n  boom\n")
    assert not next(i for i in v["items"] if i["id"] == "logs")["ok"]
    v = _verify(tmp_path / "ok", log_text="Traceback (most recent call last):\nold\nMOTRIX ERP starting\nfine\n")
    assert next(i for i in v["items"] if i["id"] == "logs")["ok"], "啟動標記之前的舊 Traceback 不算"


def test_verify_after_deployed_commit_mismatch_fails(tmp_path):
    v = _verify(tmp_path, commit="d" * 40)
    assert not next(i for i in v["items"] if i["id"] == "deployed_commit")["ok"]


def test_verify_after_package_specific_expectations(tmp_path):
    ex = {"pages": ["/ok", "/missing"], "auth_required": [{"method": "GET", "path": "/api/x"}, {"method": "POST", "path": "/api/y"}],
          "files": ["backend/modules/alpha/module.json", "backend/nope.txt"], "log_forbid": ["FATAL"]}
    v = _verify(tmp_path, expectations=ex, http=ok_http({"/missing": 404, ("GET", "/api/x"): 401, ("POST", "/api/y"): 200}),
                log_text="MOTRIX ERP starting\nFATAL x\n")
    by = {i["id"]: i["ok"] for i in v["items"]}
    assert by["page:/ok"] is True and by["page:/missing"] is False
    assert by["auth:GET /api/x"] is True and by["auth:POST /api/y"] is False, "未登入的受保護端點回 200 ⇒ 失敗（反向控制）"
    assert by["file:backend/modules/alpha/module.json"] is True and by["file:backend/nope.txt"] is False
    assert by["logs"] is False
    assert not v["ok"]


def test_verify_after_db_that_does_not_match_the_rehearsal_fails(tmp_path):
    root = make_prod(tmp_path)
    before = AA.capture_state(prod_db(root))
    copy = tmp_path / "copy.db"
    AA._online_backup(prod_db(root), str(copy))
    migrate(str(copy))
    expected = AA.diff_state(before, AA.capture_state(str(copy)))
    migrate(prod_db(root), add_column=False)               # 正式機這次沒加欄位
    write_runtime_files(root)
    v = AA.verify_after(str(root), "https://x", before, expected, {}, {"commit": COMMIT}, http_status=ok_http(),
                        apply_started=_since())
    assert not next(i for i in v["items"] if i["id"] == "db_diff")["ok"]


def test_verify_after_without_rehearsal_says_not_compared_instead_of_passing_silently(tmp_path):
    root = make_prod(tmp_path)
    before = AA.capture_state(prod_db(root))
    write_runtime_files(root)
    v = AA.verify_after(str(root), "https://x", before, None, {}, {"commit": COMMIT}, http_status=ok_http(),
                        apply_started=_since())
    it = next(i for i in v["items"] if i["id"] == "db_diff")
    assert it["severity"] == "warn" and any("未與預期比對" in w for w in v["warnings"])


# ── 套用串接 ────────────────────────────────────────────────────────────

def _ctx(tmp_path):
    root = make_prod(tmp_path)
    staged, rh = rehearsed(tmp_path, root)
    return root, staged, rh


def good_apply(root, **rt):
    calls = []

    def apply_fn():
        calls.append(1)
        migrate(prod_db(root))
        write_runtime_files(root, **rt)
        return {"started": True, "outcome": "succeeded", "problems": [], "lock": None,
                "result": {"status": "success", "rolled_back": "applied", "service": "up", "exit": 0, "commit": COMMIT,
                           "timestamp": "20261114_120000", "started_at": "2026-11-14 12:00:00", "finished_at": "2026-11-14 12:05:00"}}
    apply_fn.calls = calls
    return apply_fn


def test_apply_with_verification_success_path_writes_report_audit_and_erp_audit_row(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    fn = good_apply(root)
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=ok_http(), poll=0.01)
    assert rec["outcome"] == "succeeded" and rec["verify"]["ok"] and fn.calls == [1]
    AA.finish(rec, str(root))
    assert Path(rec["report"]["md"]).is_file() and Path(rec["report"]["json"]).is_file()
    assert AA.audit_chain_problems(str(root / "backend" / "logs" / "a1_audit.jsonl")) == []
    lines = (root / "backend" / "logs" / "a1_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["event"] for x in lines] == ["apply_start", "apply_end"]
    row = sqlite3.connect(prod_db(root)).execute("SELECT username, action, target_type FROM audit_log").fetchall()
    assert row == [("boss", "system_update_apply", "system_update")]


def test_apply_with_verification_verify_failure_stops_and_never_rolls_back(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    fn = good_apply(root, loaded_version="0.0.1")            # 模組載入版號不對 ⇒ 驗證失敗
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=ok_http(), poll=0.01)
    assert rec["outcome"] == "verify_failed" and not rec["verify"]["ok"]
    assert fn.calls == [1], "只套用一次，沒有任何回滾／重試"
    AA.finish(rec, str(root))
    md = Path(rec["report"]["md"]).read_text(encoding="utf-8")
    assert "rollback_update.ps1" in md and "-SnapshotTimestamp 20261114_120000" in md
    assert "-IncludeDatabase" not in md and "不會" in md
    assert "hunter2" not in md and "案件甲" not in md


def test_apply_with_verification_precheck_failure_blocks_before_applying(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    Path(prod_db(root)).write_bytes(b"garbage" * 5000)
    fn = good_apply(root)
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=ok_http(), poll=0.01)
    assert rec["outcome"] == "failed" and not rec["started"] and fn.calls == []
    assert any("預檢" in p for p in rec["problems"])


def test_apply_with_verification_script_failure_skips_verification(tmp_path):
    root, staged, rh = _ctx(tmp_path)

    def fn():
        return {"started": True, "outcome": "failed", "problems": ["x"], "lock": None,
                "result": {"status": "unhealthy_rolled_back", "rolled_back": "restored", "service": "up", "exit": 1}}
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=ok_http(), poll=0.01)
    assert rec["outcome"] == "failed" and rec["verify"] is None


def test_apply_with_verification_succeeded_but_unexpected_rolled_back_value_is_not_verified_and_noted(tmp_path):
    root, staged, rh = _ctx(tmp_path)

    def fn():
        return {"started": True, "outcome": "succeeded", "problems": [], "lock": None,
                "result": {"status": "success", "rolled_back": "applied_no_restore", "service": "up", "exit": 0}}
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=ok_http(), poll=0.01)
    assert rec["verify"] is None and any("applied_no_restore" in n for n in rec["notes"])


def test_apply_with_verification_measures_downtime_from_ping(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    t0 = time.time()
    state = {"down": True}

    def http(url, method="GET", timeout=8):
        if url.endswith("/api/ping"):
            return 200 if not state["down"] else None
        return 200

    def fn():
        time.sleep(0.15)                     # 服務「恢復」前：ping 不通
        state["down"] = False
        time.sleep(0.1)
        return good_apply(root)()
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://x", http_status=http, poll=0.02)
    assert rec["downtime_seconds"] is not None and rec["downtime_seconds"] >= 0 and time.time() - t0 < 30


# ── 稽核與報告 ──────────────────────────────────────────────────────────

def test_audit_chain_detects_edit_and_deletion(tmp_path):
    for i in range(4):
        assert AA.audit_event(str(tmp_path), {"event": "e%d" % i, "by": "boss"})
    path = tmp_path / "backend" / "logs" / "a1_audit.jsonl"
    assert AA.audit_chain_problems(str(path)) == []
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[1].replace('"e1"', '"eX"'), lines[2], lines[3]]) + "\n", encoding="utf-8")
    assert any("雜湊不符" in p for p in AA.audit_chain_problems(str(path)))
    path.write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n", encoding="utf-8")
    assert any("對不上" in p for p in AA.audit_chain_problems(str(path)))


def test_erp_audit_failure_is_swallowed(tmp_path):
    assert AA.erp_audit(str(tmp_path / "missing_dir" / "x.db"), "boss", "a", "l", {}) is False


def test_report_never_contains_secrets_and_shows_verify_table():
    rec = {"name": "p", "outcome": "verify_failed", "by": "boss", "install_root": "C:\\prod",
           "result": {"status": "success", "rolled_back": "applied", "service": "up", "exit": 0, "commit": COMMIT,
                      "timestamp": "20261114_120000"},
           "verify": {"ok": False, "items": [{"id": "ping", "ok": False, "severity": "fail", "title": "健康檢查", "detail": "HTTP 500"}],
                      "warnings": ["注意"]},
           "downtime_seconds": 42, "rehearsal": {"seconds": 3.0, "db_mb": 1.5}, "problems": [], "notes": []}
    md = AA.render_report(rec)
    assert "未通過" in md and "HTTP 500" in md and "42 秒" in md and "-SnapshotTimestamp 20261114_120000" in md
    summ = AA.summary_for_write_back(rec)
    assert summ["failed_items"] == ["ping"] and "install_root" not in summ and "result" not in summ


def test_write_summary_next_to_result_json_only(tmp_path):
    res = tmp_path / "p.result.json"
    res.write_text("{}", encoding="utf-8")
    out = AA.write_summary_next_to(str(res), {"name": "p", "outcome": "succeeded"})
    assert out.endswith("p.a1.json") and json.loads(Path(out).read_text(encoding="utf-8"))["outcome"] == "succeeded"
    assert AA.write_summary_next_to(str(tmp_path / "other.txt"), {}) is None


def test_python_exe_swaps_fake_pythonw(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_bytes(b"")
    (tmp_path / "python.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert AA.python_exe() == str(tmp_path / "python.exe")


# ── 儀表板預演閘門 ───────────────────────────────────────────────────────

def _gate_env(env, monkeypatch):
    monkeypatch.setattr(dd, "REQUIRE_REHEARSAL", True)
    assert env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()["ok"]


def _apply(env, **over):
    body = {"name": env["name"], "username": "boss", "password": "right", "confirm": True}
    body.update(over)
    return env["c"].post("/api/delivery/apply", json=body)


def _fake_rehearse(monkeypatch, ok=True, summary=("資料庫新增：x",)):
    def fake(staged, install_root, work_root, **k):
        pd = AA.package_digest(staged)
        return {"ok": ok, "problems": [] if ok else ["壞了"], "notes": [], "seconds": 1.0, "db_mb": 1.0, "expected_diff": {"x": 1},
                "summary": list(summary), "pkg_digest": pd, "digest": AA.consent_digest(pd, {"x": 1}) if ok else None,
                "at": time.time(), "tool_tail": ""}
    monkeypatch.setattr(AA, "rehearse", fake)


def _rehearse_and_wait(env):
    assert env["c"].post("/api/delivery/rehearse", json={"name": env["name"]}).status_code == 200
    for _ in range(100):
        s = env["c"].get("/api/delivery/rehearse/status", params={"name": env["name"]}).json()
        if not s["rehearsing"] and s["result"]:
            return s["result"]
        time.sleep(0.05)
    raise AssertionError("預演沒有結束")


def test_gate_apply_without_rehearsal_is_refused_before_asking_for_credentials(env, monkeypatch):
    _gate_env(env, monkeypatch)
    called = []
    monkeypatch.setattr(dd, "_verify_superadmin", lambda *a, **k: called.append(1) or "boss")
    r = _apply(env)
    assert r.status_code == 409 and "預演" in r.json()["detail"] and called == [], "沒預演就不必輸入密碼"


def test_gate_full_flow_rehearse_then_apply_with_the_shown_digest(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    assert res["ok"] and res["summary"] == ["資料庫新增：x"] and res["digest"] and res["empty"] is False
    assert set(res) >= {"seconds", "db_mb", "digest", "notes"}
    assert _apply(env, rehearsalDigest="not-the-digest").status_code == 409
    assert _apply(env).status_code == 409, "沒帶畫面上看到的綁定值 ⇒ 拒絕"
    r = _apply(env, rehearsalDigest=res["digest"])
    assert r.status_code == 200 and r.json()["by"] == "boss"
    for _ in range(100):                                    # 等背景套用結束，免得執行緒跨到下一題
        if not env["c"].get("/api/delivery/status").json()["running"]:
            break
        time.sleep(0.05)


def test_gate_failed_rehearsal_blocks_apply(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch, ok=False)
    res = _rehearse_and_wait(env)
    assert not res["ok"]
    r = _apply(env, rehearsalDigest=res["digest"] or "x")
    assert r.status_code == 409 and "預演" in r.json()["detail"]


def test_gate_stale_rehearsal_is_refused(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    dd._delivery_state["rehearsals"][env["name"]]["at"] = time.time() - AA.REHEARSAL_MAX_AGE_SEC - 5
    r = _apply(env, rehearsalDigest=res["digest"])
    assert r.status_code == 409 and "12 小時" in r.json()["detail"]


def test_gate_staged_package_swapped_after_rehearsal_is_refused(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    staged = Path(dd._delivery_state["prepared"][env["name"]]["staged"])
    sha = staged / "package.sha256"
    original = sha.read_bytes()
    monkeypatch.setattr(dd._trusted_delivery(), "verify_staged", lambda *a, **k: {"ok": True, "problems": [], "notes": []})
    sha.write_bytes(original + b"\n")                       # 簽章內容被換 ⇒ 綁定的包摘要不同
    r = _apply(env, rehearsalDigest=res["digest"])
    assert r.status_code == 409 and "被換過" in r.json()["detail"]


def test_gate_prepare_again_discards_the_rehearsal(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    env["c"].post("/api/delivery/prepare", json={"name": env["name"]})
    assert env["c"].get("/api/delivery/rehearse/status", params={"name": env["name"]}).json()["result"] is None
    assert _apply(env, rehearsalDigest=res["digest"]).status_code == 409


def test_gate_rehearse_requires_a_prepared_package_and_is_single_flight(env, monkeypatch):
    monkeypatch.setattr(dd, "REQUIRE_REHEARSAL", True)
    assert env["c"].post("/api/delivery/rehearse", json={"name": env["name"]}).status_code == 409      # 還沒準備
    assert env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()["ok"]
    dd._delivery_state["rehearsing"] = "other"
    assert env["c"].post("/api/delivery/rehearse", json={"name": env["name"]}).status_code == 409
    assert env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).status_code == 409, "預演中不可重新暫存"
    dd._delivery_state["rehearsing"] = None


def test_prepare_returns_downtime_estimate_and_require_flag(env, monkeypatch):
    monkeypatch.setattr(dd, "REQUIRE_REHEARSAL", True)
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert d["requireRehearsal"] is True and d["downtime"]["samples"] == 0


def test_dashboard_refuses_an_untrusted_auto_apply_module(env, monkeypatch, tmp_path):
    """與 delivery 同理：auto_apply 必須是已安裝（儀表板同目錄）的那一份。"""
    import shutil
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    shutil.copyfile(dd.TOOLS_DIR / "auto_apply.py", shadow / "auto_apply.py")
    monkeypatch.delitem(sys.modules, "auto_apply")
    monkeypatch.syspath_prepend(str(shadow))
    with pytest.raises(dd.DeliveryModuleUntrusted):
        dd._trusted_auto_apply()
