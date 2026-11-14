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
_REAL_VERIFY_SUPERADMIN = dd._verify_superadmin      # env fixture 會換成假的；縱深防禦那題要打真的


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


def test_rehearse_removes_any_new_file_the_run_leaves_not_only_pyc(tmp_path):
    """h11 S5：預演可能經由 get_db 備援在 payload 裡新建庫、logs 之類——全部清掉並記注，不等套用才說「staging 被改過」。"""
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)

    def run(cmd, env):
        migrate(cmd[cmd.index("--db") + 1])
        (staged / "payload" / "backend" / "motrix_erp.db").write_bytes(b"x")
        (staged / "payload" / "backend" / "logs").mkdir()
        (staged / "payload" / "backend" / "logs" / "a.log").write_text("x", encoding="utf-8")
        return 0, "MIGRATE_LIKE_STARTUP_OK"
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "work"), run=run)
    assert rh["ok"] and any("新檔或資料夾" in n for n in rh["notes"])
    assert not (staged / "payload" / "backend" / "motrix_erp.db").exists() and not (staged / "payload" / "backend" / "logs").exists()


def test_rehearse_fails_when_the_staged_package_no_longer_matches_its_manifest(tmp_path):
    """預演後用 verify_fn（儀表板傳 delivery.verify_staged）再驗一次：不符 ⇒ 預演不通過（在這一步失敗）；verify_fn 自己丟例外也不算通過。"""
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "w1"), run=fake_runner(prod_db(root)),
                     verify_fn=lambda: {"ok": False, "problems": ["清單外多出的檔 1 個：x"]})
    assert not rh["ok"] and any("預演之後暫存包與簽章清單不符" in p and "多出的檔" in p for p in rh["problems"])
    root2 = make_prod(tmp_path / "second")

    def boom():
        raise RuntimeError("讀不到")
    rh = AA.rehearse(str(make_staged(tmp_path / "second")), str(root2), str(tmp_path / "w2"), run=fake_runner(prod_db(root2)), verify_fn=boom)
    assert not rh["ok"] and any("無法檢查暫存包完整性" in p for p in rh["problems"])
    root3 = make_prod(tmp_path / "third")                   # 正對照：verify_fn 通過 ⇒ 預演通過
    rh = AA.rehearse(str(make_staged(tmp_path / "third")), str(root3), str(tmp_path / "w3"), run=fake_runner(prod_db(root3)),
                     verify_fn=lambda: {"ok": True, "problems": []})
    assert rh["ok"]


def test_rehearse_records_the_structure_hash_of_the_copy_before_migration(tmp_path):
    root = make_prod(tmp_path)
    staged = make_staged(tmp_path)
    rh = AA.rehearse(str(staged), str(root), str(tmp_path / "w"), run=fake_runner(prod_db(root)))
    assert rh["before_hash"] == AA.structure_hash(AA.capture_state(prod_db(root)))
    migrate(prod_db(root))
    assert rh["before_hash"] != AA.structure_hash(AA.capture_state(prod_db(root))), "結構變了雜湊就變"


def test_structure_hash_ignores_setting_keys_but_not_columns(tmp_path):
    root = make_prod(tmp_path)
    h0 = AA.structure_hash(AA.capture_state(prod_db(root)))
    c = sqlite3.connect(prod_db(root))
    c.execute("INSERT INTO system_settings VALUES ('runtime_written', '1', 't')")
    c.commit()
    c.close()
    assert AA.structure_hash(AA.capture_state(prod_db(root))) == h0, "執行中服務會寫設定，不能因此擋套用"
    c = sqlite3.connect(prod_db(root))
    c.execute("ALTER TABLE cases ADD COLUMN extra TEXT")
    c.commit()
    c.close()
    assert AA.structure_hash(AA.capture_state(prod_db(root))) != h0


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
    ex, notes = AA.load_expectations(str(tmp_path))
    assert ex["pages"] == ["/"] and ex["files"] == [] and notes == []


def test_load_expectations_drops_paths_that_could_leave_the_local_host_or_the_install_dir(tmp_path):
    p = tmp_path / "backend"
    p.mkdir()
    (p / "a1_expectations.json").write_text(json.dumps({
        "pages": ["/ok", "@evil.example/x", "http://evil.example/", "//evil.example/", "/a\\b", "no-slash", "/with space"],
        "auth_required": [{"method": "POST", "path": "/api/x"}, {"method": "GET", "path": "@evil/x"}, "junk"],
        "files": ["backend/a.txt", "..\\outside", "../outside", "C:\\Windows\\x", "/abs/x", "backend/../../y"],
        "log_forbid": ["boom", 5], "watch_settings": ["k", None]}), encoding="utf-8")
    ex, notes = AA.load_expectations(str(tmp_path))
    assert ex["pages"] == ["/ok"]
    assert ex["auth_required"] == [{"method": "POST", "path": "/api/x"}]
    assert ex["files"] == ["backend/a.txt"]
    assert ex["log_forbid"] == ["boom"] and ex["watch_settings"] == ["k"]
    assert sum("格式不合格" in n for n in notes) == 3


def test_is_loopback_url_only_accepts_the_local_host():
    for u in ("https://127.0.0.1:666", "http://localhost:666", "https://[::1]:666/x"):
        assert AA.is_loopback_url(u), u
    for u in ("https://erp.example.com", "http://10.0.0.5:666", "https://127.0.0.1.evil.example", "", "x"):
        assert not AA.is_loopback_url(u), u


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


LOCAL = "https://127.0.0.1:666"


def run_apply(name, staged, root, fn, rh, **kw):
    return AA.apply_with_verification(name, str(staged), str(root), fn, rh, "boss", LOCAL, http_status=ok_http(), poll=0.01, **kw)


def test_apply_with_verification_success_path_writes_report_and_audit_chain_with_head(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    fn = good_apply(root)
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["outcome"] == "succeeded" and rec["verify"]["ok"] and fn.calls == [1]
    AA.finish(rec, str(root))
    assert Path(rec["report"]["md"]).is_file() and Path(rec["report"]["json"]).is_file()
    path = root / "backend" / "logs" / "a1_audit.jsonl"
    assert AA.audit_chain_problems(str(path)) == []
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["event"] for x in lines] == ["apply_start", "apply_end"]
    assert rec["chain_head"] == json.loads(lines[-1])["hash"], "鏈頭＝apply_end 那一筆的雜湊"
    assert AA.summary_for_write_back(rec)["chain_head"] == rec["chain_head"], "鏈頭也寫進 <包名>.a1.json"
    assert AA.audit_chain_problems(str(path), anchors=[rec["chain_head"]]) == []
    assert sqlite3.connect(prod_db(root)).execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0, "儀表板行程不再直接 INSERT 正式庫（改由後端 _audit）"


def test_apply_blocked_when_the_prod_structure_changed_after_the_rehearsal(tmp_path):
    """h11 S1：預演之後正式庫結構變動（模組更新、手動改）⇒ 預演預期不再適用 ⇒ 套用前擋，不等套用完才 verify_failed。"""
    root, staged, rh = _ctx(tmp_path)
    c = sqlite3.connect(prod_db(root))
    c.execute("ALTER TABLE cases ADD COLUMN drifted TEXT")
    c.commit()
    c.close()
    fn = good_apply(root)
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["outcome"] == "failed" and not rec["started"] and fn.calls == []
    assert any("預演之後正式庫結構已變動" in p and "重新預演" in p for p in rec["problems"])
    events = [json.loads(x)["event"] for x in (root / "backend" / "logs" / "a1_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["apply_blocked"]


def test_apply_blocked_when_the_rehearsal_has_no_structure_hash(tmp_path):
    """h11 nit b：有預演卻沒有 before_hash ⇒ 不能確認預演之後沒變動 ⇒ 擋（不是默默略過）。正對照：同一份預演帶著雜湊就能套。"""
    root, staged, rh = _ctx(tmp_path)
    assert rh.get("before_hash")
    fn = good_apply(root)
    rec = run_apply("pkg1", staged, root, fn, dict(rh, before_hash=None))
    assert not rec["started"] and fn.calls == [] and any("結構雜湊" in p and "重新預演" in p for p in rec["problems"])
    fn2 = good_apply(root)
    rec2 = run_apply("pkg1", staged, root, fn2, rh)
    assert rec2["started"] and fn2.calls == [1]


def test_expectations_auth_required_method_is_limited_to_safe_verbs():
    out, notes = AA._sanitize_expectations({"auth_required": [
        {"method": "GET", "path": "/api/a"}, {"path": "/api/b"}, {"method": "post", "path": "/api/c"},
        {"method": "DELETE", "path": "/api/d"}, {"method": "FOO BAR", "path": "/api/e"}]})
    assert [x["path"] for x in out["auth_required"]] == ["/api/a", "/api/b", "/api/c"]
    assert any("auth_required" in n and "2 項" in n for n in notes)


def test_apply_not_blocked_by_settings_written_at_runtime_between_rehearsal_and_apply(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    c = sqlite3.connect(prod_db(root))
    c.execute("INSERT INTO system_settings VALUES ('runtime_written', '1', 't')")
    c.commit()
    c.close()
    fn = good_apply(root)
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["started"] and fn.calls == [1]


def test_apply_blocked_when_the_audit_log_cannot_be_written(tmp_path):
    """h11 S2：稽核寫不進去就不准套用（動正式機的操作沒有紀錄不能做）。把稽核檔所在位置佔成資料夾 ⇒ 寫入必失敗。"""
    root, staged, rh = _ctx(tmp_path)
    (root / "backend" / "logs" / "a1_audit.jsonl").mkdir()
    fn = good_apply(root)
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["outcome"] == "failed" and not rec["started"] and fn.calls == []
    assert any("稽核紀錄" in p and "沒有開始套用" in p for p in rec["problems"])


def test_apply_blocked_when_the_erp_url_is_not_local(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    fn = good_apply(root)
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", "https://erp.example.com", http_status=ok_http(), poll=0.01)
    assert not rec["started"] and fn.calls == [] and any("不是本機" in p for p in rec["problems"])


def test_apply_with_verification_verify_failure_stops_and_never_rolls_back(tmp_path):
    root, staged, rh = _ctx(tmp_path)
    fn = good_apply(root, loaded_version="0.0.1")            # 模組載入版號不對 ⇒ 驗證失敗
    rec = run_apply("pkg1", staged, root, fn, rh)
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
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["outcome"] == "failed" and not rec["started"] and fn.calls == []
    assert any("預檢" in p for p in rec["problems"])


def test_apply_with_verification_script_failure_skips_verification(tmp_path):
    root, staged, rh = _ctx(tmp_path)

    def fn():
        return {"started": True, "outcome": "failed", "problems": ["x"], "lock": None,
                "result": {"status": "unhealthy_rolled_back", "rolled_back": "restored", "service": "up", "exit": 1}}
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["outcome"] == "failed" and rec["verify"] is None


def test_apply_with_verification_succeeded_but_unexpected_rolled_back_value_is_never_recorded_as_success(tmp_path):
    """h11 M2：判定成功、但 rolled_back 不是 applied ⇒ 沒做驗證 ⇒ 不准記成功：outcome＝verify_failed（寫回開發機是 failed、報告有停下來的後續處置、通知是需要處理）。"""
    root, staged, rh = _ctx(tmp_path)

    def fn():
        return {"started": True, "outcome": "succeeded", "problems": [], "lock": None,
                "result": {"status": "success", "rolled_back": "applied_no_restore", "service": "up", "exit": 0, "timestamp": "20261114_120000"}}
    rec = run_apply("pkg1", staged, root, fn, rh)
    assert rec["verify"] is None and rec["outcome"] == "verify_failed"
    assert any("applied_no_restore" in p and "沒有做事後驗證" in p for p in rec["problems"])
    AA.finish(rec, str(root))
    md = Path(rec["report"]["md"]).read_text(encoding="utf-8")
    assert "後續處置" in md and "-SnapshotTimestamp 20261114_120000" in md and "- **結果**：已套用，但事後驗證有項目未通過或沒有完成" in md
    n = AA.build_notice(rec)
    assert n["ok"] is False and "沒有驗證" in n["stopped_at"]


def test_apply_with_verification_state_applied_is_the_only_success_value(tmp_path):
    for bad in ("not_applied", "restoring", "restored", "restored_unhealthy", "applied_no_restore", "", None):
        root, staged, rh = _ctx(tmp_path / ("c%s" % bad))

        def fn(bad=bad):
            return {"started": True, "outcome": "succeeded", "problems": [], "lock": None,
                    "result": {"status": "success", "rolled_back": bad, "service": "up", "exit": 0}}
        assert run_apply("pkg1", staged, root, fn, rh)["outcome"] != "succeeded", bad


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
    rec = AA.apply_with_verification("pkg1", str(staged), str(root), fn, rh, "boss", LOCAL, http_status=http, poll=0.02)
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


def _chain(tmp_path, n=4):
    for i in range(n):
        assert AA.audit_event(str(tmp_path), {"event": "e%d" % i, "by": "boss"})
    path = tmp_path / "backend" / "logs" / "a1_audit.jsonl"
    return path, path.read_text(encoding="utf-8").splitlines()


def test_audit_chain_detects_head_deletion_and_tail_truncation_via_anchor(tmp_path):
    """h11 S3a／b：第一行必須 prev＝""（開頭被刪或換過可偵測）；尾端截斷靠錨點（鏈頭雜湊另存在 audit_log／<包名>.a1.json）。"""
    path, lines = _chain(tmp_path)
    head = json.loads(lines[-1])["hash"]
    path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    assert any("第 1 行" in p and "對不上" in p for p in AA.audit_chain_problems(str(path))), "刪掉第一行"
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert AA.audit_chain_problems(str(path)) == [], "只看鏈本身：截尾看不出來（這是已知限制）"
    assert any("錨點" in p for p in AA.audit_chain_problems(str(path), anchors=[head])), "有錨點就看得出來"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert AA.audit_chain_problems(str(path), anchors=[head, ""]) == []


def test_audit_event_handles_a_huge_last_record_and_a_torn_last_line(tmp_path):
    """h11 S3c：最後一筆超過 4096 位元組、或最後一行寫到一半 ⇒ 不再算出 prev＝unreadable 造成永久斷鏈。"""
    AA.audit_event(str(tmp_path), {"event": "big", "blob": "x" * 20000})
    AA.audit_event(str(tmp_path), {"event": "after_big"})
    path = tmp_path / "backend" / "logs" / "a1_audit.jsonl"
    assert AA.audit_chain_problems(str(path)) == []
    good = path.read_text(encoding="utf-8")
    path.write_text(good + '{"event": "torn", "pre', encoding="utf-8")                    # 沒有換行的殘行
    AA.audit_event(str(tmp_path), {"event": "next"})
    problems = AA.audit_chain_problems(str(path))
    assert len(problems) == 1 and "讀不懂" in problems[0], problems                       # 殘行只報它自己，之後的鏈仍接得上
    AA.audit_event(str(tmp_path), {"event": "next2"})
    assert len(AA.audit_chain_problems(str(path))) == 1


def test_audit_event_returns_none_when_the_file_cannot_be_written(tmp_path):
    (tmp_path / "backend" / "logs" / "a1_audit.jsonl").mkdir(parents=True)
    assert AA.audit_event(str(tmp_path), {"event": "x"}) is None


def test_value_hash_is_salted_per_process_and_stable_within_it():
    assert AA._value_hash("v") == AA._value_hash("v") and AA._value_hash("v") != AA._value_hash("w")
    import hashlib
    assert AA._value_hash("v") != hashlib.sha256(b"v").hexdigest()[:16], "不是無鹽雜湊（字典可反推）"


# ── 通知（最高管理者：Email＋LINE＋站內；成功、驗證未通過、失敗、被擋、中斷都發）─────────────────

def _rec(outcome="succeeded", started=True, **kw):
    r = {"name": "20261114-pkg", "outcome": outcome, "started": started, "by": "boss", "problems": [], "notes": [],
         "install_root": "C:\\prod", "report": {"md": "C:\\prod\\backend\\logs\\a1_report_20261114_120000.md", "json": None},
         "result": {"status": "success", "rolled_back": "applied", "timestamp": "20261114_120000"}, "chain_head": "ab" * 32,
         "verify": {"ok": outcome == "succeeded", "warnings": [], "items": [
             {"id": "ping", "ok": True, "severity": "ok", "title": "t", "detail": "d"},
             {"id": "modules", "ok": outcome == "succeeded", "severity": "ok", "title": "t", "detail": "SECRET-DETAIL"}]}}
    r.update(kw)
    return r


def test_build_notice_contains_only_result_failed_item_ids_and_report_file_name():
    n = AA.build_notice(_rec("verify_failed"))
    flat = json.dumps(n, ensure_ascii=False)
    assert n["failed_items"] == ["modules"] and n["report_name"] == "a1_report_20261114_120000.md"
    assert ("未通過項目", "modules") in n["rows"] and ("報告檔", "a1_report_20261114_120000.md") in n["rows"]
    assert n["ok"] is False and n["stopped_at"].startswith("事後驗證")
    for forbidden in ("rollback_update", "-SnapshotTimestamp", "C:\\prod", "SECRET-DETAIL", "password", "密碼", "token"):
        assert forbidden not in flat, forbidden
    ok = AA.build_notice(_rec("succeeded"))
    assert ok["ok"] is True and ok["failed_items"] == [] and ok["badge_text"] == "更新完成" and "成功" in ok["reason"]


def test_build_notice_covers_all_four_kinds_blocked_failed_crashed_and_unverified():
    blocked = AA.build_notice(_rec("failed", started=False, verify=None, report=None, stopped_at="套用前檢查，沒有開始套用"))
    assert "被擋下" in dict(blocked["rows"])["結果"] and blocked["report_name"] == "" and dict(blocked["rows"])["報告檔"] == "（沒有產生）"
    failed = AA.build_notice(_rec("failed", verify=None, result={"status": "unhealthy_rolled_back", "rolled_back": "restored"}))
    assert failed["stopped_at"] == "套用腳本（結果：restored）" and failed["ok"] is False
    crashed = AA.build_notice(_rec("crashed", verify=None))
    assert "狀態未知" in crashed["stopped_at"] and "人工確認" in crashed["stopped_at"] and dict(crashed["rows"])["結果"] == "程序中斷"
    early = AA.build_notice(_rec("crashed", started=False, verify=None))      # h11 R2：沒記到 started 也不能斷言「開始前出錯」
    assert "狀態未知" in early["stopped_at"] and "開始前" not in early["stopped_at"]
    unverified = AA.build_notice(_rec("verify_failed", verify=None))
    assert "沒有驗證" in unverified["stopped_at"]


def test_notify_result_passes_notice_on_stdin_to_the_installed_backend_and_records_it(tmp_path):
    root = tmp_path / "prod"
    (root / "backend" / "logs").mkdir(parents=True)
    seen = {}

    def run(cmd, env, payload):
        seen.update(cmd=cmd, env=env, payload=json.loads(payload))
        return 0, 'noise\nA1_NOTIFY_RESULT {"audit_log": true, "in_app": {"recipients": 1, "written": 1}, "mail": {"queued": true}}\n'
    rec = _rec("succeeded")
    out = AA.notify_result(rec, str(root), run=run)
    assert out["ok"] and rec["notified"] == out and rec["problems"] == []
    assert seen["cmd"][-1] == str(root / "backend") and seen["cmd"][-2].endswith("a1_notify.py") and "-B" in seen["cmd"]
    assert seen["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and seen["payload"]["name"] == "20261114-pkg"
    ev = [json.loads(x) for x in (root / "backend" / "logs" / "a1_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ev[-1]["event"] == "apply_notified" and ev[-1]["ok"] is True


def test_notify_result_never_raises_and_failure_only_adds_a_problem(tmp_path):
    root = tmp_path / "prod"
    (root / "backend" / "logs").mkdir(parents=True)
    for run in (lambda c, e, p: (2, 'A1_NOTIFY_RESULT {"error": "mail：X"}'), lambda c, e, p: (1, "Traceback ..."),
                lambda c, e, p: (_ for _ in ()).throw(OSError("找不到 python"))):
        rec = _rec("verify_failed")
        out = AA.notify_result(rec, str(root), run=run)
        assert out["ok"] is False and any("通知／ERP 稽核沒有全部完成" in p for p in rec["problems"])
        assert rec["outcome"] == "verify_failed", "通知失敗不改變套用結果"


def test_notify_failure_is_written_into_the_report_with_the_child_output_tail(tmp_path):
    """PM：子程序失敗不能擋住套用、也不能吞掉錯誤——要寫進報告（同一份報告檔補一節「通知」）。"""
    root = make_prod(tmp_path)
    rec = {"name": "p", "outcome": "succeeded", "started": True, "by": "boss", "problems": [], "notes": [], "install_root": str(root),
           "result": {"status": "success", "rolled_back": "applied"}, "verify": {"ok": True, "items": [], "warnings": []}}
    AA.finish(rec, str(root))
    md = Path(rec["report"]["md"])
    assert "## 通知" not in md.read_text(encoding="utf-8"), "通知之前報告沒有這一節"
    AA.notify_result(rec, str(root), run=lambda c, e, p: (1, "Traceback (most recent call last):\nImportError: no module named x"))
    text = md.read_text(encoding="utf-8")
    assert "## 通知" in text and "沒有全部完成" in text and "套用結果不受影響" in text and "ImportError: no module named x" in text
    assert json.loads(Path(rec["report"]["json"]).read_text(encoding="utf-8"))["notified"]["ok"] is False
    assert rec["outcome"] == "succeeded", "通知失敗不改變套用結果"
    ok = {"name": "q", "outcome": "succeeded", "started": True, "by": "boss", "problems": [], "notes": [], "install_root": str(root),
          "result": {"status": "success", "rolled_back": "applied"}, "verify": {"ok": True, "items": [], "warnings": []}}
    AA.finish(ok, str(root))
    AA.notify_result(ok, str(root), run=lambda c, e, p: (0, 'A1_NOTIFY_RESULT {"audit_log": true, "in_app": {"recipients": 1}, "mail": {}}'))
    assert "沒有全部完成" not in Path(ok["report"]["md"]).read_text(encoding="utf-8")


def _run_a1_notify(monkeypatch, tmp_path, audit=True, in_app=None, mail=None):
    sys.path.insert(0, str(TOOLS))
    import a1_notify
    monkeypatch.chdir(tmp_path)                                 # main 會 chdir 到 backend；用 monkeypatch 讓測試結束時還原
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(a1_notify, "_erp_audit", lambda n: audit)
    monkeypatch.setattr(a1_notify, "_in_app", lambda n: in_app if in_app is not None else {"recipients": 1, "written": 1})
    monkeypatch.setattr(a1_notify, "_mail_and_line", lambda n: mail if mail is not None else {"queued": True, "outcome": "sent"})
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
    rc = a1_notify.main(["a1_notify.py", str(tmp_path)], json.dumps({"name": "p"}))
    got = json.loads([x for x in printed if x.startswith("A1_NOTIFY_RESULT ")][-1][len("A1_NOTIFY_RESULT "):])
    return rc, got


def test_check_audit_cli_reports_a_broken_chain_and_a_missing_anchor(tmp_path, capsys):
    """h11 nit c：稽核鏈有操作入口（--check-audit），不是只有測試能呼叫。"""
    root = make_prod(tmp_path)
    head = AA.audit_event(str(root), {"event": "apply_start", "by": "boss"})
    assert AA._main(["x", "--check-audit", str(root), head]) == 0
    assert AA._main(["x", "--check-audit", str(root), "0" * 64]) == 1, "錨點不在鏈裡＝尾端被截斷或換過"
    assert "沒有發現問題" not in capsys.readouterr().out.splitlines()[-1]
    assert AA._main(["x"]) == 2


def test_a1_notify_counts_as_ok_only_when_somebody_was_notified(monkeypatch, tmp_path):
    """h11 R1：收件人 0 人、站內沒寫進任何一則、信件沒排入佇列，都不能回報 ok。正對照：都有人收到 ⇒ 結束碼 0。"""
    rc, got = _run_a1_notify(monkeypatch, tmp_path)
    assert rc == 0 and "error" not in got
    rc, got = _run_a1_notify(monkeypatch, tmp_path, in_app={"recipients": 0, "written": 0})
    assert rc == 2 and "沒有任何收件人" in got["error"]
    rc, got = _run_a1_notify(monkeypatch, tmp_path, in_app={"recipients": 2, "written": 0})
    assert rc == 2 and "站內通知沒有寫進任何一則" in got["error"]
    rc, got = _run_a1_notify(monkeypatch, tmp_path, mail={"queued": False, "outcome": "None"})
    assert rc == 2 and "信件未排入" in got["error"]
    rc, got = _run_a1_notify(monkeypatch, tmp_path, audit=False)
    assert rc == 2


def test_audit_row_label_carries_the_operator_so_the_audit_page_shows_and_finds_it():
    """稽核頁列表顯示 target_label、關鍵字搜尋比對 target_label／username／display_name／target_id，不看 detail。
    username 欄是空的（_audit 只認 session token）⇒ 套用者放進 target_label。"""
    n = AA.build_notice(_rec("verify_failed", by="boss"))
    assert "套用者 boss" in n["audit_label"] and "20261114-pkg" in n["audit_label"]
    assert "套用者 未記錄" in AA.build_notice(_rec("succeeded", by=""))["audit_label"]


def test_finish_crashed_writes_an_apply_end_for_the_open_apply_start(tmp_path):
    """h11 S2：套用中丟例外（例如 apply_staged 找不到腳本）⇒ apply_start 要有對應的 apply_end（crashed）＋報告＋鏈頭。"""
    root = make_prod(tmp_path)
    AA.audit_event(str(root), {"event": "apply_start", "by": "boss"})
    rec = {"name": "p", "outcome": "failed", "started": False, "problems": [], "result": None, "by": "boss", "install_root": str(root)}
    AA.finish_crashed(rec, str(root), RuntimeError("包裡沒有 backend\\tools"))
    events = [json.loads(x) for x in (root / "backend" / "logs" / "a1_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["apply_start", "apply_end"] and events[-1]["outcome"] == "crashed"
    assert rec["outcome"] == "crashed" and rec["chain_head"] == events[-1]["hash"] and Path(rec["report"]["md"]).is_file()
    assert "程序中斷" in Path(rec["report"]["md"]).read_text(encoding="utf-8")


def test_notice_event_is_registered_everywhere_the_mail_registry_guard_needs():
    """a1_notify 寫死的信件類型：登記表、個人通知偏好、LINE 群組都要有（缺哪個，守門或畫面就會出問題）。"""
    sys.path.insert(0, str(TOOLS))
    import a1_notify
    from helpers import line_catalog, mail_types, notification_prefs
    assert a1_notify.EVENT_KEY == "system_update_result"
    t = mail_types.get(a1_notify.EVENT_KEY)
    assert t and t.category == "system" and t.group == "superadmins"
    assert a1_notify.EVENT_KEY in notification_prefs.EVENT_KEYS
    assert a1_notify.EVENT_KEY in repr(line_catalog._GROUP_RULES), "LINE 的「系統告警」群組要列出這個事件，否則 LINE 不會發"


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


def test_gate_external_erp_url_is_refused_before_any_request_so_the_password_never_leaves(env, monkeypatch):
    """h11 R3：MOTRIX_DELIVERY_ERP_URL 指到別的主機 ⇒ 在送出密碼之前就拒絕；requests 一個請求都不能發出。"""
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    sent = []
    monkeypatch.setattr(dd.requests, "post", lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(AssertionError("不該發請求")))
    monkeypatch.setattr(dd.requests, "get", lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(AssertionError("不該發請求")))
    for bad in ("https://evil.example:666", "https://127.0.0.1@evil.example/", "http://10.0.0.5:666"):
        monkeypatch.setenv("MOTRIX_DELIVERY_ERP_URL", bad)
        r = _apply(env, rehearsalDigest=res["digest"])
        assert r.status_code == 409 and "不是本機" in r.json()["detail"], bad
        assert sent == [], bad
        assert dd._delivery_state["rehearsals"].get(env["name"]), "被拒絕時預演不消耗（還沒開始套用）"
    with pytest.raises(ValueError) as ei:                                   # 縱深防禦：直接呼叫 _verify_superadmin 也不送
        _REAL_VERIFY_SUPERADMIN("boss", "right")
    assert "不是本機" in str(ei.value) and sent == []


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


def _wait_idle(env):
    for _ in range(200):
        if not env["c"].get("/api/delivery/status").json()["running"]:
            return
        time.sleep(0.05)
    raise AssertionError("套用沒有結束")


def test_gate_rehearsal_is_one_shot_a_second_apply_with_the_same_digest_is_refused(env, monkeypatch):
    """h11 M1：套用一開始預演就作廢（成功、失敗、還原都一樣）；再按套用要對現在的正式庫重新預演。"""
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    assert _apply(env, rehearsalDigest=res["digest"]).status_code == 200
    _wait_idle(env)
    assert env["c"].get("/api/delivery/rehearse/status", params={"name": env["name"]}).json()["result"] is None, "預演已被消耗"
    r = _apply(env, rehearsalDigest=res["digest"])
    assert r.status_code == 409 and "預演" in r.json()["detail"]


def test_gate_rehearsal_is_consumed_even_when_the_apply_fails(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    monkeypatch.setattr(AA, "apply_with_verification", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("套用腳本炸了")))
    monkeypatch.setattr(AA, "finish_crashed", lambda rec, root, exc: rec.update(outcome="crashed") or rec)
    res = _rehearse_and_wait(env)
    assert _apply(env, rehearsalDigest=res["digest"]).status_code == 200
    _wait_idle(env)
    assert _apply(env, rehearsalDigest=res["digest"]).status_code == 409


def test_gate_extra_file_in_the_staged_package_is_refused_before_asking_for_credentials(env, monkeypatch):
    """PM：預演之後、要求輸入密碼之前先確認暫存包完整；多出來的任何檔案都擋。"""
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    staged = Path(dd._delivery_state["prepared"][env["name"]]["staged"])
    (staged / "payload" / "stray.db").write_bytes(b"x")
    called = []
    monkeypatch.setattr(dd, "_verify_superadmin", lambda *a, **k: called.append(1) or "boss")
    r = _apply(env, rehearsalDigest=res["digest"])
    assert r.status_code == 409 and "多出" in r.json()["detail"] and called == []


def test_prepare_is_refused_while_another_prepare_runs_and_rehearse_or_apply_wait_for_it(env, monkeypatch):
    """h11 N4：stage() 在鎖外跑，另有 preparing 旗標（鎖內設定）：準備進行中，不准第二個準備、預演或套用。"""
    _gate_env(env, monkeypatch)
    dd._delivery_state["preparing"] = True
    assert env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).status_code == 409
    assert env["c"].post("/api/delivery/rehearse", json={"name": env["name"]}).status_code == 409
    dd._delivery_state["preparing"] = False


def test_prepare_clears_the_preparing_flag_even_when_staging_fails(env, monkeypatch):
    monkeypatch.setattr(dd._trusted_delivery(), "stage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("磁碟滿了")))
    with pytest.raises(RuntimeError):
        env["c"].post("/api/delivery/prepare", json={"name": env["name"]})
    assert dd._delivery_state["preparing"] is False and env["name"] not in dd._delivery_state["prepared"]


def test_delivery_run_crash_writes_apply_end_and_still_notifies(env, monkeypatch):
    """h11 S2＋PM：套用程序丟例外 ⇒ 補 apply_end（crashed）、仍然發通知；結果與旗標照常放出。"""
    calls = []
    monkeypatch.setattr(AA, "apply_with_verification", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("找不到腳本")))
    monkeypatch.setattr(AA, "finish_crashed", lambda rec, root, exc: calls.append(("finish_crashed", str(exc))) or rec.update(outcome="crashed") or rec)
    monkeypatch.setattr(AA, "notify_result", lambda rec, root, run=None: calls.append(("notify", rec["outcome"])) or {"ok": True})
    dd._delivery_state["running"] = True
    dd._delivery_run("pkgX", "S", {}, "R", "boss", None)
    assert [c[0] for c in calls] == ["finish_crashed", "notify"] and calls[1][1] == "crashed" and "找不到腳本" in calls[0][1]
    assert dd._delivery_state["last"]["outcome"] == "crashed" and dd._delivery_state["running"] is False


def test_delivery_run_notifies_after_report_and_writeback_for_every_outcome(env, monkeypatch):
    """順序：finish（報告＋鏈頭）→ write_back／a1.json → notify；任何結果（成功、驗證未通過、失敗、被擋）都通知。"""
    for outcome, started in (("succeeded", True), ("verify_failed", True), ("failed", True), ("failed", False)):
        order = []
        rec = {"name": "pkgX", "outcome": outcome, "started": started, "problems": [], "result": None, "by": "boss"}
        monkeypatch.setattr(AA, "apply_with_verification", lambda *a, _r=rec, **k: _r)
        monkeypatch.setattr(AA, "finish", lambda r, root, db_path=None, _o=order: _o.append("finish") or r)
        monkeypatch.setattr(AA, "notify_result", lambda r, root, run=None, _o=order: _o.append("notify") or {"ok": True})
        dd._delivery_state["running"] = True
        dd._delivery_run("pkgX", "S", {}, "R", "boss", None)
        assert order == ["finish", "notify"], (outcome, started, order)
        assert dd._delivery_state["last"] is rec and dd._delivery_state["running"] is False


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


# ── 準備／預演／套用前檢查被擋：白話報告＋apply_blocked 稽核（PM 10 之 ②）──────────

def _audit_rows(root):
    p = Path(root) / "backend" / "logs" / "a1_audit.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _blocked_files(root):
    d = Path(root) / "backend" / "logs"
    return sorted(d.glob("a1_report_blocked_*.md")) if d.exists() else []


def test_write_blocked_report_writes_plain_report_and_a_chained_apply_blocked_audit(tmp_path):
    name = AA.write_blocked_report(str(tmp_path), "pkgX", "預演", ["壞了：" + "長" * 500, "第二個原因"])
    assert name and name.startswith("a1_report_blocked_") and name.endswith(".md")
    text = (tmp_path / "backend" / "logs" / name).read_text(encoding="utf-8")
    assert "沒有開始套用：pkgX" in text and "停在「預演」" in text and "正式系統沒有被改動" in text
    assert "第二個原因" in text and "長" * 301 not in text, "每則原因截 300 字"
    rows = _audit_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["event"] == "apply_blocked" and rows[0]["step"] == "預演" and rows[0]["report"] == name
    assert AA.audit_chain_problems(str(tmp_path / "backend" / "logs" / "a1_audit.jsonl")) == []
    name2 = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["x"])
    assert name2 != name, "同一秒連續兩次也不會互相覆蓋"
    assert len(_blocked_files(tmp_path)) == 2


def test_write_blocked_report_never_raises_and_returns_none_when_it_cannot_write(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert AA.write_blocked_report(str(f), "pkgX", "準備", ["x"]) is None, "安裝目錄是檔案 ⇒ 寫不出來也不丟例外"
    assert AA.write_blocked_report(str(tmp_path), "pkgX", "準備", None) is not None, "沒有原因也寫得出報告"


def test_prepare_failure_writes_a_blocked_report_and_audit_without_notifying(env, monkeypatch):
    notified = []
    monkeypatch.setattr(AA, "notify_result", lambda *a, **k: notified.append(1) or {"ok": True})
    r = env["c"].post("/api/delivery/prepare", json={"name": "沒有這個包"})
    assert r.status_code == 409 and r.json()["report"]
    root = dd.DELIVERY_INSTALL_ROOT
    assert (Path(root) / "backend" / "logs" / r.json()["report"]).exists()
    rows = _audit_rows(root)
    assert rows and rows[-1]["event"] == "apply_blocked" and rows[-1]["step"] == "準備"
    assert notified == [], "準備階段不發通知"


def test_prepare_verification_failure_writes_a_blocked_report(env, monkeypatch):
    monkeypatch.setattr(dd._trusted_delivery(), "verify_staged", lambda *a, **k: {"ok": False, "problems": ["簽章不符"], "notes": []})
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert d["ok"] is False and d["report"]
    text = (Path(dd.DELIVERY_INSTALL_ROOT) / "backend" / "logs" / d["report"]).read_text(encoding="utf-8")
    assert "簽章不符" in text and "停在「準備」" in text


def test_prepare_success_writes_no_blocked_report(env):
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert d["ok"] and d["report"] is None and _blocked_files(dd.DELIVERY_INSTALL_ROOT) == []


def test_rehearse_failure_writes_a_blocked_report_and_the_status_shows_its_name(env, monkeypatch):
    notified = []
    monkeypatch.setattr(AA, "notify_result", lambda *a, **k: notified.append(1) or {"ok": True})
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch, ok=False)
    res = _rehearse_and_wait(env)
    assert not res["ok"] and res["report"]
    assert (Path(dd.DELIVERY_INSTALL_ROOT) / "backend" / "logs" / res["report"]).exists()
    assert _audit_rows(dd.DELIVERY_INSTALL_ROOT)[-1]["step"] == "預演" and notified == []


def test_rehearse_that_crashes_also_writes_a_blocked_report(env, monkeypatch):
    _gate_env(env, monkeypatch)
    monkeypatch.setattr(AA, "rehearse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸了")))
    res = _rehearse_and_wait(env)
    assert not res["ok"] and res["report"] and "預演程序本身出錯" in res["problems"][0]


def test_rehearse_success_writes_no_blocked_report(env, monkeypatch):
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    assert res["ok"] and not res.get("report") and _blocked_files(dd.DELIVERY_INSTALL_ROOT) == []


def test_apply_gate_refusals_after_the_rehearsal_write_blocked_reports(env, monkeypatch):
    """預演之後、套用之前被擋（暫存包多檔、包被換過、系統位址不是本機）：都留報告與 apply_blocked，不發通知，預演不消耗。"""
    notified = []
    monkeypatch.setattr(AA, "notify_result", lambda *a, **k: notified.append(1) or {"ok": True})
    _gate_env(env, monkeypatch)
    _fake_rehearse(monkeypatch)
    res = _rehearse_and_wait(env)
    monkeypatch.setenv("MOTRIX_DELIVERY_ERP_URL", "http://10.0.0.5:666")
    r1 = _apply(env, rehearsalDigest=res["digest"])
    assert r1.status_code == 409 and r1.json()["report"], "4xx 回應要帶回報告檔名，畫面才能顯示（h5 #2）"
    assert "ERP" not in r1.json()["detail"].replace("MOTRIX_DELIVERY_ERP_URL", ""), "白話訊息不用系統名 ERP"
    staged = Path(dd._delivery_state["prepared"][env["name"]]["staged"])
    monkeypatch.delenv("MOTRIX_DELIVERY_ERP_URL")
    (staged / "payload" / "stray.db").write_bytes(b"x")
    r2 = _apply(env, rehearsalDigest=res["digest"])
    assert r2.status_code == 409 and r2.json()["report"] and r2.json()["report"] != r1.json()["report"]
    assert (Path(dd.DELIVERY_INSTALL_ROOT) / "backend" / "logs" / r2.json()["report"]).exists()
    steps = [r["step"] for r in _audit_rows(dd.DELIVERY_INSTALL_ROOT) if r["event"] == "apply_blocked"]
    assert steps == ["套用前檢查（系統位址）", "套用前檢查（暫存包完整性）"], steps
    assert len(_blocked_files(dd.DELIVERY_INSTALL_ROOT)) == 2 and notified == []


def test_blocked_report_failure_never_breaks_prepare(env, monkeypatch):
    monkeypatch.setattr(AA, "write_blocked_report", lambda *a, **k: (_ for _ in ()).throw(OSError("磁碟壞了")))
    r = env["c"].post("/api/delivery/prepare", json={"name": "沒有這個包"})
    assert r.status_code == 409 and r.json()["report"] is None


# ── h11 S1／S2：包名與原因先清乾淨；同一原因不重複寫；報告只留最新 50 份；附加稽核只讀檔尾 ──────────

def test_blocked_report_cleans_hostile_name_and_problems_before_writing(tmp_path):
    evil = "x\n- **結果**：成功\n## 假的一節\r\u2028" + "A" * 5000
    name = AA.write_blocked_report(str(tmp_path), evil, "預演\n偽造步驟", ["原因一\n- **正式系統沒有被改動**：假\x00\x07", "B" * 5000])
    text = (tmp_path / "backend" / "logs" / name).read_text(encoding="utf-8")
    assert "名稱不合法，已省略" in text and "A" * 50 not in text and "假的一節" not in text.split("## 原因")[0].replace("# 沒有開始套用", "")
    heads = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert heads == ["# 沒有開始套用：（名稱不合法，已省略；長度 %d）" % len(evil), "## 原因", "## 接下來"], heads
    lines = text.splitlines()
    assert sum(ln.startswith("- **結果**") for ln in lines) == 1 and sum(ln.startswith("- **正式系統沒有被改動**") for ln in lines) == 1, "壓成一行：不能假造報告行"
    assert "\x00" not in text and "\x07" not in text and "B" * 301 not in text
    row = _audit_rows(tmp_path)[-1]
    assert row["name"].startswith("（名稱不合法") and "\n" not in json.dumps(row["problems"]) and "\n" not in row["step"]
    assert all(len(p) <= 300 for p in row["problems"]) and len(json.dumps(row)) < 3000


def test_blocked_report_normal_package_name_is_kept(tmp_path):
    name = AA.write_blocked_report(str(tmp_path), "20261114_120000_abcd1234_full", "準備", ["x"])
    assert "# 沒有開始套用：20261114_120000_abcd1234_full" in (tmp_path / "backend" / "logs" / name).read_text(encoding="utf-8")


def test_blocked_report_same_refusal_within_the_window_writes_one_file_and_one_audit_row(tmp_path):
    a = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["同一個原因"])
    b = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["同一個原因"])
    assert a and a == b and len(_blocked_files(tmp_path)) == 1 and len(_audit_rows(tmp_path)) == 1
    c = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["另一個原因"])
    d = AA.write_blocked_report(str(tmp_path), "pkgY", "準備", ["同一個原因"])
    e = AA.write_blocked_report(str(tmp_path), "pkgX", "預演", ["同一個原因"])
    assert len({a, c, d, e}) == 4 and len(_blocked_files(tmp_path)) == 4 and len(_audit_rows(tmp_path)) == 4
    other = tmp_path / "other"
    assert AA.write_blocked_report(str(other), "pkgX", "準備", ["同一個原因"]) != a or True
    assert len(_blocked_files(other)) == 1, "不同安裝目錄各自計"


def test_blocked_report_is_written_again_after_the_window_or_when_the_file_was_removed(tmp_path, monkeypatch):
    a = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["原因"])
    (tmp_path / "backend" / "logs" / a).unlink()
    b = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["原因"])
    assert b and b != a and (tmp_path / "backend" / "logs" / b).exists(), "上一份被刪了就重寫，不回不存在的檔名"
    monkeypatch.setattr(AA, "BLOCKED_DEDUPE_SEC", 0)
    c = AA.write_blocked_report(str(tmp_path), "pkgX", "準備", ["原因"])
    assert c != b


def test_blocked_reports_are_pruned_to_the_newest_keep(tmp_path, monkeypatch):
    monkeypatch.setattr(AA, "BLOCKED_KEEP", 5)
    names = [AA.write_blocked_report(str(tmp_path), "pkg%d" % i, "準備", ["原因 %d" % i]) for i in range(9)]
    left = sorted(f.name for f in _blocked_files(tmp_path))
    assert left == sorted(names)[-5:], (left, names)


def test_audit_append_reads_only_the_tail_of_a_large_log(tmp_path, monkeypatch):
    import builtins
    for i in range(3000):
        AA.audit_event(str(tmp_path), {"event": "e", "i": i, "pad": "x" * 200})
    path = tmp_path / "backend" / "logs" / "a1_audit.jsonl"
    total = path.stat().st_size
    assert total > 600_000
    read = []
    real_open = builtins.open

    class Spy:
        def __init__(self, f):
            self.f = f

        def read(self, *a):
            data = self.f.read(*a)
            read.append(len(data))
            return data

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            self.f.__enter__()
            return self

        def __exit__(self, *a):
            return self.f.__exit__(*a)

    def spy_open(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        return Spy(f) if str(file).endswith("a1_audit.jsonl") and "b" in mode else f
    monkeypatch.setattr(builtins, "open", spy_open)
    assert AA.audit_event(str(tmp_path), {"event": "tail-only"})
    monkeypatch.setattr(builtins, "open", real_open)
    assert sum(read) < 20_000 < total, (sum(read), total)
    assert AA.audit_chain_problems(str(path)) == []
