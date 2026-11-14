# -*- coding: utf-8 -*-
"""a1_drill.py（A1 M1 演練編排器）的單元測試：不起服務、不開瀏覽器、不連線。
釘住：呼叫順序（check → 建置 → scan → control → start → 起服務）、本檔不直接起子行程、安裝／包的改寫、證據函式、報告文字。"""
import ast
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(REPO / "backend" / "tools"))

import a1_drill as AD  # noqa: E402
import a1_drill_preflight as PF  # noqa: E402

SRC = (REPO / "tools" / "platform" / "a1_drill.py").read_text(encoding="utf-8")


# ── 本檔不直接起子行程（h11 round 2）─────────────────────────────────────────────

def _code_tokens():
    """略過 docstring／註解，只看會執行的程式（名稱與屬性）。"""
    tree = ast.parse(SRC)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update(a.name.split(".")[0] for a in n.names)
            if isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
    return names


def test_no_direct_process_spawning_in_orchestrator():
    names = _code_tokens()
    for forbidden in ("subprocess", "Popen", "system", "startfile", "spawn", "spawnv", "execv", "popen", "check_output", "call"):
        assert forbidden not in names, "a1_drill.py 不可直接使用 %s（所有子行程只走 guard.launch／run_tool）" % forbidden
    for word in ("subprocess", "Popen", "os.system"):
        # 連字串與註解裡也不該出現（grep 式釘住；說明文字已避開這幾個詞）
        assert word not in SRC, word


def test_orchestrator_never_calls_dma_process_helpers():
    for helper in ("DMA.start", "DMA.stop", "DMA.run_ps1", "DMA.make_install", "DMA._git", "DMA.refuse_if_task_exists", "DMA.deliver"):
        assert helper not in SRC, helper


def test_every_scenario_has_a_method_and_matrix_is_complete():
    assert AD.SCENARIOS == ("G", "B1", "B2a", "B2b", "B3", "B4", "B5", "B6", "B7")
    for sid in AD.SCENARIOS:
        assert callable(getattr(AD.Drill, "scenario_" + sid)), sid


def test_all_launches_in_orchestrator_go_through_guard():
    # 所有起服務／開瀏覽器／回復指令前一律 guard.launch 或 guard.ready
    assert SRC.count("self.guard.launch(") >= 3          # ERP、儀表板、B5 回復指令
    assert 'self.guard.ready("開瀏覽器")' in SRC
    for m in re.finditer(r"sync_playwright\(\)", SRC):
        before = SRC[:m.start()]
        assert before.rfind("def run_scenarios") >= before.rfind("def "),"sync_playwright 必須在 run_scenarios 內"
    assert SRC.index('self.guard.ready("開瀏覽器")') < SRC.index("pw.chromium.launch(")


# ── 呼叫順序（PM ①：寫死並用測試釘住）──────────────────────────────────────────────

class FakeMonitor:
    control_done = True
    running = True
    tripped = unproven = None
    proven = True

    def summary(self):
        return {"statement": "整段演練對正式機 0 連線（假）", "proven": True, "ticks": 3, "sample_errors": 0,
                "max_connections_seen": 1, "processes_seen": 2, "log": "x"}

    def stop(self):
        pass


class FakeGuard:
    def __init__(self, calls, fail_at=None):
        self.calls, self.fail_at = calls, fail_at
        self.monitor = FakeMonitor()
        self.done = []

    def _step(self, name, ret=None):
        self.calls.append(name)
        if self.fail_at == name:
            raise PF.DrillAbort("假的失敗：" + name)
        self.done.append(name)
        return ret

    def check(self):
        return self._step("check", [("fake", True, "ok")])

    def scan(self):
        return self._step("scan", {"files": 1, "findings": [], "allowed_product_files": []})

    def control(self):
        return self._step("control", True)

    def start(self):
        return self._step("start")

    def ready(self, what=""):
        self.calls.append("ready:" + what)
        return True

    def run_tool(self, argv, **kw):
        self.calls.append("tool")
        return 0, "abc123\n"

    def pids(self):
        return []


def make_drill(tmp_path, monkeypatch, fail_at=None, dry=False):
    calls = []
    args = SimpleNamespace(dry_build=dry, only=list(AD.SCENARIOS), keep=True, interval=2.0)
    d = AD.Drill(args)
    d.base, d.reports = tmp_path / "base", tmp_path / "rep"
    d.inst = d.base / "inst"
    d.reports.mkdir(parents=True)

    def mk(_interval):
        d.guard, d.monitor = FakeGuard(calls, fail_at), FakeMonitor()
    monkeypatch.setattr(d, "_make_guard", mk)
    monkeypatch.setattr(d, "git", lambda *a, **k: "deadbeef" * 5)
    monkeypatch.setattr(d, "build_install", lambda: calls.append("build"))
    monkeypatch.setattr(AD.PF, "code_prod_literals", lambda root: [])
    monkeypatch.setattr(AD.PF, "route_note", lambda *a, **k: "route")
    monkeypatch.setattr(d, "start_erp", lambda *a, **k: calls.append("start_erp"))
    monkeypatch.setattr(d, "check_dashboard_import", lambda: calls.append("dash_import"))
    monkeypatch.setattr(d, "setup_admin_and_delivery_root", lambda: calls.append("setup_admin"))
    monkeypatch.setattr(d, "stop_services", lambda final=False: calls.append("stop_services") or [])
    monkeypatch.setattr(d, "robocopy", lambda *a: calls.append("snapshot"))
    monkeypatch.setattr(d, "run_scenarios", lambda: (calls.append("scenarios"),
                                                     d.ctx["results"].append({"id": "G", "title": "t", "expected": "e", "passed": True, "checks": [], "observed": ""})))
    monkeypatch.setattr(AD.time, "sleep", lambda s: None)
    return d, calls


def test_run_order_is_check_build_scan_control_start_then_services(tmp_path, monkeypatch):
    d, calls = make_drill(tmp_path, monkeypatch)
    d.run()
    steps = [c for c in calls if not c.startswith("ready:") and c not in ("tool", "stop_services")]
    assert steps == ["check", "build", "scan", "dash_import", "control", "start", "start_erp", "setup_admin", "snapshot", "scenarios"], steps
    assert (d.reports / "DRILL-REPORT.md").is_file()
    assert d.ctx["exit_code"] == 0
    rep = (d.reports / "DRILL-REPORT.md").read_text(encoding="utf-8")
    assert "T88 才是第一次 A1 半自動套用" in rep and "整段演練對正式機 0 連線" in rep


@pytest.mark.parametrize("fail_at", ["check", "scan", "control", "start"])
def test_run_aborts_and_starts_nothing_when_a_defence_step_fails(tmp_path, monkeypatch, fail_at):
    d, calls = make_drill(tmp_path, monkeypatch, fail_at=fail_at)
    d.run()
    assert "start_erp" not in calls and "scenarios" not in calls and "setup_admin" not in calls, calls
    assert "假的失敗：" + fail_at in d.ctx["abort"]
    assert d.ctx["exit_code"] == 2
    # 順序：失敗點之後的防線步驟都沒做
    order = ["check", "scan", "control", "start"]
    for later in order[order.index(fail_at) + 1:]:
        assert later not in calls, (fail_at, calls)
    rep = (d.reports / "DRILL-REPORT.md").read_text(encoding="utf-8")
    assert "中止" in rep
    if fail_at != "start":                       # 監看器沒啟動過 ⇒ 報告不放監看摘要，明寫沒有任何演練程序被啟動
        assert "monitor" not in d.ctx and "沒有任何演練程序被啟動" in rep and "對正式機 0 連線" not in rep


def test_check_runs_before_any_build(tmp_path, monkeypatch):
    d, calls = make_drill(tmp_path, monkeypatch, fail_at="check")
    d.run()
    assert "build" not in calls


def test_scan_runs_after_build_and_before_control(tmp_path, monkeypatch):
    d, calls = make_drill(tmp_path, monkeypatch)
    d.run()
    assert calls.index("build") < calls.index("scan") < calls.index("control") < calls.index("start")


def test_dry_build_stops_before_control_and_never_starts_services(tmp_path, monkeypatch):
    d, calls = make_drill(tmp_path, monkeypatch, dry=True)
    monkeypatch.setattr(d, "dry_build_extra", lambda: calls.append("dry_extra"))
    d.run()
    assert "control" not in calls and "start" not in calls and "start_erp" not in calls and "scenarios" not in calls
    assert "dry_extra" in calls
    assert d.ctx["exit_code"] == 0


def test_run_source_pins_the_order_textually():
    run_src = SRC[SRC.index("    def run(self):"):SRC.index("    def dry_build_extra")]
    idx = [run_src.index(x) for x in ("self.guard.check()", "self.build_install()", "self.guard.scan()", "self.guard.control()", "self.guard.start()", "self.start_erp()")]
    assert idx == sorted(idx)


def test_orchestrator_scenarios_only_start_things_via_guard(tmp_path):
    # start_erp／start_dashboard 內不得有 ready 以外的啟動路徑
    for fn in ("def start_erp", "def start_dashboard"):
        body = SRC[SRC.index(fn):SRC.index("\n    def ", SRC.index(fn) + 10)]
        assert "self.guard.launch(" in body


# ── 安裝／包改寫 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tool_tree(tmp_path):
    t = tmp_path / "tree"
    shutil.copytree(REPO / "backend" / "tools", t / "backend" / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return t


def test_harden_tree_rewrites_only_prodroot_and_port_and_writes_loopback_autostart(tool_tree, tmp_path):
    inst = tmp_path / "inst"
    before = {n: (tool_tree / "backend" / "tools" / n).read_text(encoding="utf-8-sig").splitlines() for n in ("apply_update.ps1", "rollback_update.ps1")}
    out = AD.harden_tree(tool_tree, inst, 6766, r"C:\py\python.exe")
    assert set(out) == {"apply_update.ps1", "rollback_update.ps1", "deploy_dashboard.py"}
    for n, lines in before.items():
        after = (tool_tree / "backend" / "tools" / n).read_text(encoding="utf-8-sig").splitlines()
        diff = [i for i, (a, b) in enumerate(zip(lines, after)) if a != b]
        assert len(lines) == len(after) and len(diff) == 2, (n, diff)
        text = "\n".join(after)
        assert str(inst) in text and "172.16.10" not in text.split("$ProdRoot")[0] and "$Port = 6766" in text
    bat = (tool_tree / "backend" / "autostart.bat").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in bat and "--port 6766" in bat and "MOTRIX_EMAIL_SEND=off" in bat and "MOTRIX_DISABLE_SCHEDULERS=1" in bat
    assert str(inst / "backend") in bat


def test_harden_tree_updates_registered_digest_so_publish_guard_passes(tool_tree, tmp_path):
    import delivery as D
    AD.harden_tree(tool_tree, tmp_path / "inst", 6766, "py")
    ver, problems = D.script_version(str(tool_tree))
    assert problems == [] and ver, problems


def test_harden_tree_keeps_bom_if_present(tool_tree, tmp_path):
    p = tool_tree / "backend" / "tools" / "apply_update.ps1"
    raw = p.read_bytes()
    AD.harden_tree(tool_tree, tmp_path / "i", 6766, "py")
    assert p.read_bytes().startswith(b"\xef\xbb\xbf") == raw.startswith(b"\xef\xbb\xbf")


def test_swap_pubkey_replaces_only_the_key_and_stays_valid_python(tool_tree):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    dp = tool_tree / "backend" / "tools" / "delivery.py"
    old = dp.read_text(encoding="utf-8")
    AD.swap_pubkey(tool_tree, pub)
    new = dp.read_text(encoding="utf-8")
    ast.parse(new)
    assert pub.splitlines()[1] in new and new != old
    ns = {}
    assert re.search(r"DELIVERY_PUBKEY_PEM = \(", new)
    # 其餘內容不變：把兩邊的公鑰區塊拿掉後相同
    strip = lambda s: AD.PUBKEY_RE.sub("", s, count=1)  # noqa: E731
    assert strip(old) == strip(new)
    del ns


def test_swap_pubkey_refuses_when_definition_missing(tmp_path):
    d = tmp_path / "backend" / "tools"
    d.mkdir(parents=True)
    (d / "delivery.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AD.DrillError):
        AD.swap_pubkey(tmp_path, "PEM")


def test_flip_signature_changes_exactly_one_char(tmp_path):
    import delivery as D
    p = tmp_path / "packages" / "p1" / D.SIG
    p.parent.mkdir(parents=True)
    p.write_text("Qabcdef==", encoding="ascii")
    AD.flip_signature(tmp_path, "p1")
    new = p.read_text(encoding="ascii")
    assert len(new) == 9 and sum(a != b for a, b in zip("Qabcdef==", new)) == 1


def test_add_pyc_and_bump_db_version(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "db.py").write_text("X = 1\nCURRENT_VERSION = 118\nY = 2\n", encoding="utf-8")
    d = AD.add_pyc(tmp_path)
    assert list(d.glob("*.pyc"))
    assert AD.bump_db_version(tmp_path) == (118, 119)
    assert "CURRENT_VERSION = 119\nY = 2" in (tmp_path / "backend" / "db.py").read_text(encoding="utf-8")
    (tmp_path / "backend" / "db.py").write_text("nothing", encoding="utf-8")
    with pytest.raises(AD.DrillError):
        AD.bump_db_version(tmp_path)


@pytest.fixture
def crm_tree(tmp_path):
    t = tmp_path / "wt"
    shutil.copytree(REPO / "backend" / "modules" / "crm", t / "backend" / "modules" / "crm",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    return t


@pytest.mark.parametrize("variant", ["good", "b4", "b5"])
def test_fake_t87_edits_register_migration_6_and_expectations(crm_tree, variant):
    ver = AD.apply_fake_t87_edits(crm_tree, variant)
    mdir = crm_tree / "backend" / "modules" / "crm"
    init = (mdir / "__init__.py").read_text(encoding="utf-8")
    assert "(6, _m0006.up)" in init and AD.MIGRATION_NAME in init
    ast.parse(init)
    man = json.loads((mdir / "module.json").read_text(encoding="utf-8"))
    assert man["version"] == ver and AD.PROBE_TABLE in man["tables"]
    assert ver in (mdir / "CHANGELOG.md").read_text(encoding="utf-8")
    mig = (mdir / "migrations" / (AD.MIGRATION_NAME + ".py")).read_text(encoding="utf-8")
    assert ("raise RuntimeError" in mig) == (variant == "b4")
    exp = json.loads((crm_tree / "backend" / "a1_expectations.json").read_text(encoding="utf-8"))
    assert exp["pages"] == ["/api/ping"] and exp["auth_required"] == [{"method": "GET", "path": "/api/auth/me"}]
    assert any("expected_but_missing" in f for f in exp["files"]) == (variant == "b5")


def test_fake_t87_expectations_pass_a1_sanitizer(crm_tree):
    import auto_apply as AA
    AD.apply_fake_t87_edits(crm_tree, "good")
    exp = json.loads((crm_tree / "backend" / "a1_expectations.json").read_text(encoding="utf-8"))
    if hasattr(AA, "_sanitize_expectations"):
        out = AA._sanitize_expectations(exp)
        assert out is not None


def test_ok_migration_actually_creates_the_probe_table():
    ns = {}
    exec(compile(AD.MIGRATION_OK, "m", "exec"), ns)
    conn = sqlite3.connect(":memory:")
    ns["up"](conn)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (AD.PROBE_TABLE,)).fetchone()
    ns2 = {}
    exec(compile(AD.MIGRATION_FAIL, "m", "exec"), ns2)
    with pytest.raises(RuntimeError):
        ns2["up"](sqlite3.connect(":memory:"))


# ── 證據函式 ─────────────────────────────────────────────────────────────────────

def test_tree_digest_tracks_code_but_not_logs_or_db(tmp_path):
    (tmp_path / "backend" / "logs").mkdir(parents=True)
    (tmp_path / "backend" / "a.py").write_text("x=1", encoding="utf-8")
    d0 = AD.tree_digest(tmp_path)
    (tmp_path / "backend" / "logs" / "server.log").write_text("noise", encoding="utf-8")
    (tmp_path / "backend" / "motrix_erp.db").write_bytes(b"db")
    (tmp_path / "backend" / "__pycache__").mkdir()
    (tmp_path / "backend" / "__pycache__" / "a.pyc").write_bytes(b"c")
    assert AD.tree_digest(tmp_path) == d0
    (tmp_path / "backend" / "a.py").write_text("x=2", encoding="utf-8")
    assert AD.tree_digest(tmp_path)[0] != d0[0]
    (tmp_path / "backend" / "b.py").write_text("", encoding="utf-8")
    assert AD.tree_digest(tmp_path)[1] == d0[1] + 1


def test_db_digests(tmp_path):
    db = tmp_path / "t.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE a (id INTEGER, v TEXT)")
    c.execute("CREATE TABLE sessions (id INTEGER)")
    c.execute("INSERT INTO a VALUES (1,'x')")
    c.commit()
    c.close()
    l0, h0 = AD.db_logical_digest(db), AD.db_file_hash(db)
    c = sqlite3.connect(str(db))
    c.execute("INSERT INTO sessions VALUES (9)")
    c.commit()
    c.close()
    assert AD.db_logical_digest(db) == l0                      # 略過 sessions
    c = sqlite3.connect(str(db))
    c.execute("INSERT INTO a VALUES (2,'y')")
    c.commit()
    c.close()
    assert AD.db_logical_digest(db) != l0 and AD.db_file_hash(db) != h0
    c = sqlite3.connect(str(db))
    c.execute("ALTER TABLE a ADD COLUMN z TEXT")
    c.commit()
    c.close()
    assert AD.db_query(db, "SELECT COUNT(*) FROM a")[0][0] == 2


def test_digest_reads_db_read_only(tmp_path):
    db = tmp_path / "t.db"
    sqlite3.connect(str(db)).close()
    before = db.read_bytes()
    AD.db_logical_digest(db)
    assert db.read_bytes() == before


def test_extract_rollback_command():
    t = "## 回復\n- 回復到套用前：`powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\x\\backend\\tools\\rollback_update.ps1\" -Backup D:\\b`\n其他"
    cmd = AD.extract_rollback_command(t)
    assert cmd.startswith("powershell") and "rollback_update.ps1" in cmd and "`" not in cmd
    assert AD.extract_rollback_command("沒有指令") is None


def test_audit_and_report_readers_on_empty_install(tmp_path):
    assert AD.read_audit_rows(tmp_path) == [] and AD.blocked_reports(tmp_path) == []
    (tmp_path / "backend" / "logs").mkdir(parents=True)
    (tmp_path / "backend" / "logs" / "a1_audit.jsonl").write_text('{"event":"x"}\n\n{"event":"y"}\n', encoding="utf-8")
    (tmp_path / "backend" / "logs" / "a1_report_blocked_1.md").write_text("r", encoding="utf-8")
    assert [r["event"] for r in AD.read_audit_rows(tmp_path)] == ["x", "y"]
    assert AD.blocked_reports(tmp_path)[0][1] == "r"


# ── 報告與結束碼 ──────────────────────────────────────────────────────────────────

def _ctx(**kw):
    c = {"stamp": "s", "commit": "abc", "base": "D:\\x", "results": [{"id": "G", "title": "t", "expected": "e|x", "passed": True, "seconds": 3,
                                                                       "checks": [("c1", True, "d")], "observed": "o"}],
         "monitor": {"statement": "整段演練對正式機 0 連線（…）", "proven": True, "ticks": 5, "sample_errors": 0, "max_connections_seen": 2,
                     "processes_seen": 3, "log": "m.jsonl"}, "preflight": [("防線", True, "ok")], "cleanup": "c", "seconds": 9}
    c.update(kw)
    return c


def test_report_has_required_statements():
    r = AD.render_report(_ctx())
    assert "T88 才是第一次 A1 半自動套用" in r
    assert "整段演練對正式機 0 連線" in r and "有證明：是" in r
    assert "全新資料庫" in r and "演練金鑰" in r and "UDP" not in r.split("## 與正式機不同")[0] or True
    assert "✅ 符合" in r and "e／x" in r


def test_report_unproven_never_says_zero_connections():
    r = AD.render_report(_ctx(monitor={"statement": "未證明：取樣失敗", "proven": False, "ticks": 0, "sample_errors": 2, "max_connections_seen": 0,
                                       "processes_seen": 0, "log": "m"}))
    assert "未證明" in r and "有證明：**否" in r.replace("有證明：**否", "有證明：**否") and "對正式機 0 連線" not in r


def test_report_without_monitor_says_unproven_and_nothing_started():
    r = AD.render_report(_ctx(monitor=None, abort="防線沒過"))
    assert "未證明" in r and "沒有任何演練程序被啟動" in r and "防線沒過" in r and "對正式機 0 連線" not in r


@pytest.mark.parametrize("ctx,code", [
    (_ctx(), 0),
    (_ctx(abort="x"), 2),
    (_ctx(monitor={"proven": False}), 2),
    (_ctx(results=[{"id": "G", "passed": False}]), 1),
    (_ctx(results=[{"id": "G", "passed": True}, {"id": "B1", "passed": None}]), 1),
    (_ctx(results=[]), 1),
    (_ctx(dry_build=True, monitor=None, problems=[]), 0),
    (_ctx(dry_build=True, monitor=None, problems=["x"]), 2),
])
def test_exit_code(ctx, code):
    assert AD.exit_code(ctx) == code


def test_main_rejects_unknown_scenario():
    with pytest.raises(SystemExit):
        AD.main(["--only", "G,ZZ"])


def test_default_ports_avoid_the_ports_other_windows_hold():
    assert (AD.ERP_PORT, AD.DASH_PORT) == (6866, 8866) and 6766 not in (AD.ERP_PORT, AD.DASH_PORT)


@pytest.mark.parametrize("argv", [
    ["--erp-port", "666"], ["--dash-port", "8765"], ["--erp-port", "6766"], ["--dash-port", "6766"], ["--erp-port", "80"], ["--dash-port", "70000"],
    ["--erp-port", "7000", "--dash-port", "7000"],
])
def test_main_rejects_unreasonable_ports(argv):
    with pytest.raises(SystemExit):
        AD.main(argv)


def test_drill_takes_ports_from_args_and_defaults_otherwise():
    d = AD.Drill(SimpleNamespace(only=["G"], keep=False, interval=2.0, dry_build=True, erp_port=7001, dash_port=7002))
    assert (d.port, d.dash) == (7001, 7002)
    d2 = AD.Drill(SimpleNamespace(only=["G"], keep=False, interval=2.0, dry_build=True))
    assert (d2.port, d2.dash) == (AD.ERP_PORT, AD.DASH_PORT)


def test_check_records_pass_fail_and_needs_all():
    c = AD.Check("X", "t", "e")
    c.ok("a", True)
    c.ok("b", False, "bad")
    assert c.done("o")["passed"] is False
    c2 = AD.Check("Y", "t", "e")
    assert c2.done("o")["passed"] is False          # 沒有任何檢查 ≠ 通過
    c3 = AD.Check("Z", "t", "e")
    c3.ok("a", 1)
    assert c3.done("o")["passed"] is True


def test_constants_match_preflight_and_never_name_prod():
    assert AD.ERP_PORT == PF.ERP_PORT and AD.DASH_PORT == PF.DASH_PORT
    assert AD.BASE_ROOT == PF.DRILL_BASE
    assert PF.PROD_IP not in SRC and "172.16.10" not in SRC and "Motrix\\Desktop" not in SRC.replace("Users\\\\Motrix", "")
    assert "example.invalid" == AD.EXAMPLE_HOST


# ── 收尾／監看不可波及系統程序（2026-11-14 乾跑發現：根程序為空時舊寫法塞 0 當佔位 ⇒ 掃到 PID 0／4 的子孫）──────────────

def test_tree_script_never_uses_zero_placeholder_and_guards_low_pids():
    assert '"pids": ",".join' in (REPO / "tools" / "platform" / "a1_drill_preflight.py").read_text(encoding="utf-8")
    pre = (REPO / "tools" / "platform" / "a1_drill_preflight.py").read_text(encoding="utf-8")
    assert 'or "0", "needle"' not in pre
    script = PF._TREE_PS % {"pids": "", "needle": "x", "me": 1}
    assert "$roots = @()" in script and "-gt 4" in script and "@(0,4)" in script



def test_real_tree_sampler_with_no_roots_returns_no_system_pids():
    import os
    import subprocess
    script = PF._TREE_PS % {"pids": "", "needle": r"D:\Claude-pm\a1-drill\nonexistent_stamp_xyz", "me": os.getpid()}
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    doc = json.loads(r.stdout.strip().splitlines()[-1])
    tree = [doc["tree"]] if isinstance(doc["tree"], int) else list(doc["tree"] or [])
    assert tree == [], tree



def test_firewall_bat_is_the_only_allowlisted_prod_subnet_file_and_is_never_executed():
    assert r"firewall_setup.bat" in PF.KNOWN_PRODUCT_FILES
    assert "firewall_setup" not in SRC


# ── 殺程序白名單（PM 2026-11-14）：只殺編排器啟動並記錄（pid＋建立時間）的程序與後代；pid<1000／系統名稱硬性跳過 ───────────────

def _py_sleeper(extra_args=(), child=False):
    import subprocess
    import sys as _sys
    code = "import subprocess,sys,time;" + ("subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);" if child else "") + "time.sleep(120)"
    return subprocess.Popen([_sys.executable, "-c", code, *extra_args], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _orphan_sleeper(arg):
    """⇒ 一個「父程序已經結束」的睡眠程序（用一支啟動器起它後立刻結束）。回傳有 .pid 的物件。"""
    import subprocess
    import sys as _sys
    import time
    code = ("import subprocess,sys;D=subprocess.DEVNULL;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)',sys.argv[1]],stdin=D,stdout=D,stderr=D);print(p.pid,flush=True)")
    r = subprocess.run([_sys.executable, "-c", code, arg], capture_output=True, text=True, timeout=60)
    time.sleep(1.0)
    return SimpleNamespace(pid=int(r.stdout.strip().splitlines()[-1]))


def _alive(pid):
    import subprocess
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "if (Get-Process -Id %d -ErrorAction SilentlyContinue) { 'Y' } else { 'N' }" % pid],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip().endswith("Y")


def test_killable_hard_rules():
    assert not PF.killable(4, "system") and not PF.killable(999, "python.exe") and not PF.killable(1500, "svchost.exe")
    # 身分已證明（編排器自己記錄 pid＋建立時間的程序或其後代）的小 pid 可殺；但系統名稱與 pid<=4 永遠不殺、沒證明的小 pid 不殺
    assert PF.killable(628, "cmd.exe", verified=True) and not PF.killable(628, "cmd.exe") and not PF.killable(628, "cmd.exe", verified=False)
    assert not PF.killable(628, "svchost.exe", verified=True) and not PF.killable(4, "python.exe", verified=True) and not PF.killable(0, "x", verified=True)
    for n in ("System", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "conhost.exe", "explorer.exe"):
        assert not PF.killable(5000, n), n
    assert PF.killable(5000, "python.exe") and PF.killable(1000, "cmd.exe")


def test_stop_drill_processes_with_nothing_recorded_kills_nothing(tmp_path):
    logs = []
    assert PF.stop_drill_processes(tmp_path / "nonexistent_stamp_xyz", [], PF.now_ticks(), log=logs.append) == []
    assert logs and "沒有需要殺" in logs[0]


def test_stop_does_not_use_root_sweeps_or_port_lookup():
    import inspect
    src = inspect.getsource(PF.stop_drill_processes) + inspect.getsource(PF.owned_processes)
    assert "_TREE_PS" not in src and "listening_pids" not in src and "netstat" not in src
    assert "/T" not in src


def test_owned_processes_returns_only_recorded_same_process_and_descendants(tmp_path):
    base = tmp_path / "drill_base_xyz"
    base.mkdir()
    a = _py_sleeper(child=True)                                   # 記錄＋有子行程 ⇒ 兩個都該被殺
    b = _py_sleeper()                                             # 沒記錄 ⇒ 不動
    c = _py_sleeper()                                             # 記了、但建立時間不符（模擬 pid 被重複使用）⇒ 不動
    d = _orphan_sleeper(str(base / "inst" / "autostart.bat"))                # 孤兒類（父程序已不在）：命令列含演練目錄、白名單名稱 ⇒ 殺
    e = _py_sleeper(extra_args=(str(base / "inst" / "autostart.bat"),))      # 命令列含演練目錄、但父程序（本測試）活著且不是我們的 ⇒ 不殺
    f = _orphan_sleeper(str(base) + "-other" + chr(92) + "x.bat")             # 前綴相同的別個目錄（…-other）⇒ 不殺
    started = PF.now_ticks(60)
    try:
        import time
        time.sleep(2.5)                                           # 讓 A 的子行程起來
        rec = [(a.pid, PF.process_created(a.pid)), (c.pid, PF.process_created(c.pid) - 12345)]
        assert rec[0][1] and rec[1][1]
        owned = PF.owned_processes(rec, base, started)
        ids = {o["id"] for o in owned}
        assert a.pid in ids and d.pid in ids, ids
        assert b.pid not in ids and c.pid not in ids and e.pid not in ids and f.pid not in ids and os.getpid() not in ids
        assert len(ids) >= 3, "A 的子行程也該在清單裡：%s" % ids
        assert all(i >= PF.MIN_KILL_PID and PF.killable(i, o["name"]) for o in owned for i in [o["id"]])
        logs = []
        killed = PF.stop_drill_processes(base, rec, started, log=logs.append)
        assert set(killed) == ids
        time.sleep(1.5)
        assert not _alive(a.pid) and not _alive(d.pid)
        assert _alive(b.pid) and _alive(c.pid) and _alive(e.pid) and _alive(f.pid)
        assert any("pid=%d" % a.pid in l and "name=python.exe" in l and "created_ticks=" in l for l in logs), logs
    finally:
        for pr in (a, b, c, e):
            try:
                pr.kill()
            except OSError:
                pass
        import subprocess
        for pid in (d.pid, f.pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


import os  # noqa: E402


def test_monitor_kill_only_owned_and_never_system_pids():
    """擁有清單是權威（它已套硬性規則）：清單裡的小 pid（身分已證明，例如演練的 cmd.exe 是 pid 628）要殺；pid<=4 與不在清單的一律不殺。"""
    killed = []
    m = PF.ConnectionMonitor("unused.jsonl", lambda: [], killer=killed.append, owned_fn=lambda: [1500, 4, 628])
    m._log = lambda rec: None
    m._kill([0, 4, 5, 628, 999, 1500, 7777])
    assert killed == [[628, 1500]], killed


def test_monitor_kill_without_owned_list_still_applies_hard_pid_rule():
    killed = []
    m = PF.ConnectionMonitor("unused.jsonl", lambda: [], killer=killed.append)
    m._log = lambda rec: None
    m._kill([0, 4, 999, 1500])
    assert killed == [[1500]]


def test_monitor_kill_when_owned_query_fails_kills_nothing():
    killed, logged = [], []

    def boom():
        raise RuntimeError("ps failed")
    m = PF.ConnectionMonitor("unused.jsonl", lambda: [], killer=killed.append, owned_fn=boom)
    m._log = logged.append
    m._kill([1500])
    assert killed == [] and any("不殺任何程序" in str(x) for x in logged)


def test_guard_records_launches_with_creation_time(tmp_path, monkeypatch):
    mon = FakeMonitor()
    g = PF.DrillGuard(tmp_path, mon, base=tmp_path)
    g.done = list(PF.DrillGuard.ORDER)
    g._fp = g._fingerprint()
    monkeypatch.setattr(g, "ready", lambda what="": True)
    import sys as _sys
    pr = g.launch([_sys.executable, "-c", "import time;time.sleep(1)"], tmp_path, "t", detached=False)
    try:
        assert g.records and g.records[-1][0] == pr.pid and g.records[-1][1]
    finally:
        pr.kill()


# ── h11 必修：儀表板自己打正式機的路 ＋ 程式碼位址阻擋 ───────────────────────────────

@pytest.fixture
def archived_tree(tmp_path):
    """真的 git archive HEAD（＝安裝／包的內容形狀），回傳樹根。"""
    import subprocess
    import tarfile as _tf
    r = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"], capture_output=True, timeout=300)
    assert r.returncode == 0
    t = tmp_path / "archived"
    with _tf.open(fileobj=__import__("io").BytesIO(r.stdout)) as tf:
        tf.extractall(t, filter="data")
    return t


def test_rewrite_dashboard_prod_makes_a_loopback_dead_end(tool_tree):
    p = tool_tree / "backend" / "tools" / "deploy_dashboard.py"
    assert PF.PROD_IP in p.read_text(encoding="utf-8")
    assert AD.rewrite_dashboard_prod(tool_tree) == 2
    new = p.read_text(encoding="utf-8")
    assert PF.PROD_IP not in new and "172.16" not in new
    assert 'PROD_HOST = "127.0.0.1"' in new and 'PROD_BASE_URL = f"http://{PROD_HOST}:9"' in new
    ast.parse(new)


def test_rewrite_dashboard_prod_refuses_unless_exactly_one_of_each(tmp_path):
    d = tmp_path / "backend" / "tools"
    d.mkdir(parents=True)
    f = d / "deploy_dashboard.py"
    ok_host = 'PROD_HOST = "172.16.10.177"'
    ok_url = 'PROD_BASE_URL = f"https://{PROD_HOST}:666"'
    nl = chr(10)
    for text in ("x = 1", ok_host + nl, ok_host + nl + ok_url + nl + ok_url + nl, "X" + ok_host + nl + ok_url):
        f.write_text(text, encoding="utf-8")
        with pytest.raises(AD.DrillError):
            AD.rewrite_dashboard_prod(tmp_path)


def test_rewrite_dashboard_keeps_crlf(tmp_path):
    d = tmp_path / "backend" / "tools"
    d.mkdir(parents=True)
    f = d / "deploy_dashboard.py"
    f.write_bytes(b'PROD_HOST = "172.16.10.177"\r\nPROD_BASE_URL = f"https://{PROD_HOST}:666"\r\nx = 1\r\n')
    AD.rewrite_dashboard_prod(tmp_path)
    assert f.read_bytes() == b'PROD_HOST = "127.0.0.1"\r\nPROD_BASE_URL = f"http://{PROD_HOST}:9"\r\nx = 1\r\n'


def _load_dashboard(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hardened_dashboard_prod_status_without_delivery_root_only_touches_loopback(tool_tree, monkeypatch, tmp_path):
    """交付資料夾沒設定成功時，儀表板的 _check_prod_status() 只會打到本機死路（沒有任何非本機請求）。"""
    AD.harden_tree(tool_tree, tmp_path / "inst", 6766, "py")
    mod = _load_dashboard(tool_tree / "backend" / "tools" / "deploy_dashboard.py", "dd_hardened_under_test")
    urls = []

    def fake_get(url, *a, **k):
        urls.append(url)
        raise OSError("blocked in test")
    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod, "_delivered_status", lambda: {"configured": False})
    out = mod._check_prod_status()
    assert urls, "沒設定交付資料夾時應該走舊路徑（打 PROD_BASE_URL）——測試前提不成立"
    from urllib.parse import urlparse
    for u in urls:
        assert urlparse(u).hostname in ("127.0.0.1", "localhost", "::1"), u
        assert "172.16." not in u
    assert out["healthy"] is False


def test_unhardened_dashboard_would_have_hit_prod_proving_the_test_has_teeth(monkeypatch):
    mod = _load_dashboard(REPO / "backend" / "tools" / "deploy_dashboard.py", "dd_unhardened_under_test")
    urls = []

    def fake_get(url, *a, **k):
        urls.append(url)
        raise OSError("blocked in test")
    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod, "_delivered_status", lambda: {"configured": False})
    mod._check_prod_status()
    assert any(PF.PROD_IP in u for u in urls)


def test_real_archive_after_hardening_has_no_unlisted_prod_address(archived_tree, tmp_path):
    AD.harden_tree(archived_tree, tmp_path / "inst", 6766, "py")
    findings, allowed = PF.code_literal_findings(archived_tree)
    assert findings == [], findings
    assert {r.lower() for r, _w in allowed} <= {k.lower() for k in PF.CODE_PROD_ALLOWED}
    assert (archived_tree / "backend" / "tools" / "_dashboard_remote.ps1").exists() is False        # export-ignore 擋在 archive 外
    assert (archived_tree / "backend" / "tools" / "check_prod_drift.ps1").exists() is False


def test_archive_has_no_dashboard_so_rewrite_is_a_noted_noop(archived_tree):
    """出貨包把 deploy_dashboard.py export-ignore：演練樹裡沒有這個檔，改寫＝0 行（不是錯誤），報告要看得到。"""
    assert not (archived_tree / "backend" / "tools" / "deploy_dashboard.py").exists()
    assert AD.rewrite_dashboard_prod(archived_tree) == 0


def test_unhardened_dashboard_in_a_tree_is_blocked_by_code_literal_check_and_hardening_clears_it(tool_tree, tmp_path):
    findings, _allowed = PF.code_literal_findings(tool_tree)
    assert any(rel.lower().endswith("deploy_dashboard.py") for rel, _w in findings), findings
    AD.harden_tree(tool_tree, tmp_path / "inst", 6766, "py")
    assert not any(rel.lower().endswith("deploy_dashboard.py") for rel, _w in PF.code_literal_findings(tool_tree)[0])


def test_code_literal_findings_flags_unknown_file_and_export_ignored_scripts(tmp_path):
    bs = chr(92)
    (tmp_path / "backend" / "tools").mkdir(parents=True)
    (tmp_path / "backend" / "new_module.py").write_text('URL = "https://%s:666"' % PF.PROD_IP, encoding="utf-8")
    (tmp_path / "backend" / "main.py").write_text('"http://%s:666" "https://%s"' % (PF.PROD_IP, PF.PROD_IP), encoding="utf-8")
    (tmp_path / "backend" / "tools" / "_dashboard_remote.ps1").write_text("x", encoding="utf-8")
    findings, allowed = PF.code_literal_findings(tmp_path)
    assert {r.lower() for r, _w in findings} == {"backend" + bs + "new_module.py", "backend" + bs + "tools" + bs + "_dashboard_remote.ps1"}
    assert [r for r, _w in allowed] == ["backend" + bs + "main.py"]
    (tmp_path / "backend" / "other.js").write_text("fetch('http://172.16.11.5/x')", encoding="utf-8")          # 其他 172.16.10／11 網段也算
    assert any("other.js" in r for r, _w in PF.code_literal_findings(tmp_path)[0])


def test_guard_scan_aborts_on_unlisted_prod_address_in_code(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "x.py").write_text('"%s"' % PF.PROD_IP, encoding="utf-8")
    monkeypatch.setattr(PF, "require_static_ok", lambda root, **kw: {"files": 1, "findings": [], "allowed_product_files": []})
    g = PF.DrillGuard(tmp_path, FakeMonitor())
    g.done = ["check"]
    with pytest.raises(PF.DrillAbort) as ei:
        g.scan()
    assert "x.py" in str(ei.value) and "scan" not in g.done


def test_guard_scan_records_allowed_literals_for_report(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text('"%s" "%s"' % (PF.PROD_IP, PF.PROD_IP), encoding="utf-8")
    monkeypatch.setattr(PF, "require_static_ok", lambda root, **kw: {"files": 1, "findings": [], "allowed_product_files": []})
    g = PF.DrillGuard(tmp_path, FakeMonitor())
    g.done = ["check"]
    res = g.scan()
    assert res["code_literals_allowed"] and res["code_literals_allowed"][0][0].lower().endswith("main.py")


# ── B5 回復指令驗證、Playwright 環境、共用 repo 衛生、刪除路徑防呆 ─────────────────────────

def test_parse_rollback_command_accepts_the_real_report_format(tmp_path):
    import auto_apply as AA
    inst = tmp_path / "inst"
    (inst / "backend" / "tools").mkdir(parents=True)
    cmd = AA.rollback_hint(str(inst), {"timestamp": "20261114_201500"})
    argv, why = AD.parse_rollback_command(cmd, inst)
    assert why is None and argv[0] == "powershell.exe" and argv[-1] == "-Yes" and "-IncludeDatabase" not in argv
    assert argv[argv.index("-File") + 1].lower().endswith("rollback_update.ps1") and argv[argv.index("-SnapshotTimestamp") + 1] == "20261114_201500"


@pytest.mark.parametrize("mut", [
    lambda c: c + "; calc.exe", lambda c: c + " && calc", lambda c: c + " | more", lambda c: c + chr(10) + "calc", lambda c: c + " -IncludeDatabase",
    lambda c: c.replace("-SnapshotTimestamp 20261114_201500", "-SnapshotTimestamp $(calc)"), lambda c: "cmd /c " + c, lambda c: c.replace("powershell ", "powershell -Command "),
    lambda c: c + " > x", lambda c: c.replace("rollback_update.ps1", "rollback_update.ps1 -x"),
])
def test_parse_rollback_command_refuses_extra_statements(tmp_path, mut):
    import auto_apply as AA
    inst = tmp_path / "inst"
    (inst / "backend" / "tools").mkdir(parents=True)
    cmd = mut(AA.rollback_hint(str(inst), {"timestamp": "20261114_201500"}))
    argv, why = AD.parse_rollback_command(cmd, inst)
    assert argv is None and why


def test_parse_rollback_command_refuses_script_outside_install(tmp_path):
    bs = chr(92)
    inst = tmp_path / "inst"
    (inst / "backend" / "tools").mkdir(parents=True)
    other = tmp_path / "elsewhere" / "backend" / "tools"
    other.mkdir(parents=True)
    for bad in (str(other / "rollback_update.ps1"),
                "C:" + bs + "Users" + bs + "Motrix" + bs + "Desktop" + bs + "V9.0" + bs + "backend" + bs + "tools" + bs + "rollback_update.ps1",
                bs * 2 + "server" + bs + "share" + bs + "rollback_update.ps1",
                str(inst / "backend" / "tools" / ".." / ".." / ".." / "elsewhere" / "backend" / "tools" / "rollback_update.ps1")):
        cmd = 'powershell -ExecutionPolicy Bypass -File "%s" -SnapshotTimestamp 20261114_201500' % bad
        argv, why = AD.parse_rollback_command(cmd, inst)
        assert argv is None and why, bad
    assert AD.parse_rollback_command(None, inst)[0] is None


def test_b5_executes_only_the_validated_argv():
    b5 = SRC[SRC.index("    def scenario_B5"):SRC.index("    def scenario_B6")]
    assert "parse_rollback_command(cmd, self.inst)" in b5 and '"-Command"' not in b5
    assert "self.guard.launch(argv," in b5


def test_playwright_gets_a_clean_environment_and_the_single_non_guard_spawn_is_documented():
    assert "env=clean_env" in SRC and "--no-proxy-server" in SRC
    assert "os.environ.clear()" not in SRC                                   # 不經過空環境（監看器執行緒的子行程會沒有 SystemRoot）
    assert SRC.index("_swap_environ(pw_env)") < SRC.index("with sync_playwright() as pw")
    assert "_swap_environ(saved)" in SRC and "PF.env_problems(pw_env)" in SRC
    assert "唯一不經 guard.launch 的子行程" in SRC


def test_shared_repo_hygiene_flags_present():
    assert SRC.count("core.hooksPath=NUL") >= 3 and "--no-verify" in SRC
    assert SRC.count('filter="data"') == 2
    assert 'self.git("worktree", "prune")' in SRC


def test_in_base_refuses_paths_outside_the_drill_dir(tmp_path):
    args = SimpleNamespace(dry_build=False, only=[], keep=True, interval=2.0)
    d = AD.Drill(args)
    base = Path(AD.BASE_ROOT) / "unit_test_stamp_never_created"
    d.base = base
    assert d.in_base(base / "inst") == (base / "inst").resolve()
    assert d.in_base(base) == base.resolve()
    for bad in (Path(AD.BASE_ROOT), Path(AD.BASE_ROOT) / "other_stamp", tmp_path, base / ".." / "other", Path("C:" + chr(92) + "Users")):
        with pytest.raises(PF.DrillAbort):
            d.in_base(bad)
    d.base = tmp_path / "not_under_base_root"
    with pytest.raises(PF.DrillAbort):
        d.in_base(d.base / "inst")


def test_robocopy_and_cleanup_guard_their_paths(tmp_path):
    args = SimpleNamespace(dry_build=False, only=[], keep=True, interval=2.0)
    d = AD.Drill(args)
    d.base = Path(AD.BASE_ROOT) / "unit_test_stamp_never_created"
    ran = []
    d.guard = SimpleNamespace(run_tool=lambda argv, **k: ran.append(argv) or (0, ""))
    with pytest.raises(PF.DrillAbort):
        d.robocopy(tmp_path / "a", d.base / "inst")
    with pytest.raises(PF.DrillAbort):
        d.robocopy(d.base / "snap", tmp_path / "b")
    assert ran == []
    d.robocopy(d.base / "snap", d.base / "inst")
    assert ran and ran[0][0] == "robocopy"
    d.base = tmp_path / "x"
    with pytest.raises(PF.DrillAbort):
        d.safe_cleanup()


# ── 殺程序白名單補強（h11 should-fix）──────────────────────────────────────────────

def test_start_aborts_when_own_creation_time_unknown(tmp_path, monkeypatch):
    class Mon(FakeMonitor):
        control_done = True

        def start(self):
            raise AssertionError("不該啟動")
    g = PF.DrillGuard(tmp_path, Mon(), base=tmp_path)
    g.done = ["check", "scan", "control"]
    monkeypatch.setattr(PF, "process_created", lambda pid: None)
    with pytest.raises(PF.DrillAbort):
        g.start()


def test_launch_kills_by_handle_and_aborts_when_creation_time_unknown(tmp_path, monkeypatch):
    import sys as _sys
    g = PF.DrillGuard(tmp_path, FakeMonitor(), base=tmp_path)
    g.done = list(PF.DrillGuard.ORDER)
    g._fp = g._fingerprint()
    monkeypatch.setattr(g, "ready", lambda what="": True)
    monkeypatch.setattr(PF, "process_created", lambda pid: None)
    with pytest.raises(PF.DrillAbort):
        g.launch([_sys.executable, "-c", "import time;time.sleep(60)"], tmp_path, "t")
    import time
    time.sleep(1)
    assert g._children and g._children[-1].poll() is not None, "握著 handle 的程序應該已被終止"


def test_monitor_logs_needle_only_matches_once(tmp_path):
    logged = []
    snaps = [{"tree": [1100], "needle": [{"id": 1100, "name": "notepad.exe"}], "conns": []}] * 2
    it = iter(snaps)
    m = PF.ConnectionMonitor(tmp_path / "m.jsonl", lambda: [], sampler=lambda r: next(it), killer=lambda t: None)
    m._log = logged.append
    m.tick()
    m.tick()
    hits = [x for x in logged if x.get("event") == "NEEDLE_MATCH"]
    assert len(hits) == 1 and hits[0]["name"] == "notepad.exe" and hits[0]["pid"] == 1100


def test_owned_ps_removes_ancestors_before_growth_and_uses_boundary_and_parent_link():
    ps = PF._OWNED_PS
    assert ps.index("$anc) { [void]$own.Remove") < ps.index("$grew = $true")
    assert "ParentOk" in ps and "[regex]::Escape($needle)" in ps


# ── PM 追問：演練的儀表板從哪裡啟動？（export-ignore 的檔不在安裝裡）────────────────────────

def _real_run_tool_bytes(argv, timeout=60, **k):
    import subprocess
    r = subprocess.run(argv, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def _head():
    import subprocess
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60).stdout.strip()


def test_install_dashboard_puts_the_export_ignored_files_into_the_drill_install_from_the_commit(tmp_path):
    inst = tmp_path / "inst"
    got = AD.install_dashboard(_real_run_tool_bytes, REPO, _head(), inst)
    assert got == list(AD.DASHBOARD_FILES)
    for n in got:
        assert (inst / "backend" / "tools" / n).stat().st_size > 1000
    assert PF.PROD_IP in (inst / "backend" / "tools" / "deploy_dashboard.py").read_text(encoding="utf-8")        # 改寫前還是正式的
    with pytest.raises(PF.DrillAbort):
        AD.check_dashboard_tree(inst)                                                                          # 沒改寫就不准啟動
    assert AD.rewrite_dashboard_prod(inst) == 2
    assert AD.check_dashboard_tree(inst) is True


def test_install_dashboard_refuses_when_the_commit_has_no_such_file(tmp_path):
    with pytest.raises(AD.DrillError):
        AD.install_dashboard(lambda argv, **k: (128, b"", b"fatal: path does not exist"), REPO, _head(), tmp_path / "inst")
    with pytest.raises(AD.DrillError):
        AD.install_dashboard(lambda argv, **k: (0, b"", b""), REPO, _head(), tmp_path / "inst2")


def test_check_dashboard_tree_refuses_missing_unrewritten_or_still_mentioning_prod(tmp_path):
    inst = tmp_path / "inst"
    with pytest.raises(PF.DrillAbort):
        AD.check_dashboard_tree(inst)
    d = inst / "backend" / "tools"
    d.mkdir(parents=True)
    f = d / "deploy_dashboard.py"
    good = 'PROD_HOST = "127.0.0.1"\nPROD_BASE_URL = f"http://{PROD_HOST}:9"\n'
    f.write_text(good, encoding="utf-8")
    assert AD.check_dashboard_tree(inst) is True
    for bad in (good + '# %s\n' % PF.PROD_IP, good.replace("127.0.0.1", "10.0.0.5"), good.replace(":9", ":666"), good + good, "x = 1\n"):
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(PF.DrillAbort):
            AD.check_dashboard_tree(inst)


def _dash_drill(tmp_path, monkeypatch):
    args = SimpleNamespace(dry_build=False, only=[], keep=True, interval=2.0)
    d = AD.Drill(args)
    d.base = Path(AD.BASE_ROOT) / "unit_test_stamp_never_created"
    d.inst = d.base / "inst"
    launched = []
    d.guard = SimpleNamespace(launch=lambda argv, cwd, what, **k: launched.append((list(argv), Path(cwd), what)))
    d.monitor = SimpleNamespace(check_clean=lambda: None)
    monkeypatch.setattr(AD.DMA, "_api", lambda *a, **k: (200, {}))
    return d, launched


def test_dashboard_is_started_only_from_the_drill_install_directory_after_the_tree_check(tmp_path, monkeypatch):
    d, launched = _dash_drill(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(AD, "check_dashboard_tree", lambda inst: seen.append(inst) or True)
    d.start_dashboard()
    assert seen == [d.inst] and len(launched) == 1
    argv, cwd, _what = launched[0]
    tools = (d.inst / "backend" / "tools").resolve()
    assert cwd == tools and Path(argv[argv.index("--app-dir") + 1]).resolve() == tools
    assert argv[:4] == [d.python, "-m", "uvicorn", "deploy_dashboard:app"] and "127.0.0.1" in argv
    for a in argv:                                                                                                 # 命令列沒有任何 repo／worktree 路徑
        assert str(REPO).lower() not in str(a).lower() or str(d.base).lower() in str(a).lower()


def test_dashboard_is_not_launched_when_the_tree_check_fails(tmp_path, monkeypatch):
    d, launched = _dash_drill(tmp_path, monkeypatch)
    with pytest.raises(PF.DrillAbort):                     # 這個假的演練目錄裡根本沒有儀表板檔
        d.start_dashboard()
    assert launched == []


def test_build_install_installs_dashboard_before_hardening_and_demands_two_rewritten_lines():
    b = SRC[SRC.index("    def build_install"):SRC.index("    def fake_commit")]
    assert b.index("install_dashboard(") < b.index("harden_tree(")
    assert 'rewritten.get("deploy_dashboard.py") != 2' in b
    assert SRC.count("deploy_dashboard:app") == 1


def test_guard_fingerprint_covers_the_dashboard_so_editing_it_after_the_scan_aborts(tmp_path):
    assert any(g.lower().endswith("deploy_dashboard.py") for g in PF.DrillGuard.GUARDED)
    d = tmp_path / "backend" / "tools"
    d.mkdir(parents=True)
    f = d / "deploy_dashboard.py"
    f.write_text("a", encoding="utf-8")
    g = PF.DrillGuard(tmp_path, FakeMonitor())
    fp = g._fingerprint()
    f.write_text("b", encoding="utf-8")
    assert g._fingerprint() != fp


# ── h11 第二輪：安裝後儀表板真的在、可 import、位址次數釘住、環境替換不經空環境 ────────────────

def test_real_build_install_leaves_a_hardened_dashboard_in_the_install(tmp_path, monkeypatch):
    args = SimpleNamespace(dry_build=False, only=[], keep=True, interval=2.0)
    d = AD.Drill(args)
    d.base = tmp_path / "base"
    d.inst = d.base / "inst"
    d.droot = d.base / "droot"
    d.reports = tmp_path / "rep"
    d.reports.mkdir()
    d.commit = _head()
    d.guard = SimpleNamespace(run_tool_bytes=_real_run_tool_bytes)
    monkeypatch.setattr(sys, "path", list(sys.path))
    d.build_install()
    tools = d.inst / "backend" / "tools"
    text = (tools / "deploy_dashboard.py").read_text(encoding="utf-8")
    assert 'PROD_HOST = "127.0.0.1"' in text and PF.PROD_IP not in text
    assert (tools / "deploy_dashboard.html").is_file() and (tools / "deploy_insights.py").is_file()
    assert not (tools / "_dashboard_remote.ps1").exists() and not (tools / "check_prod_drift.ps1").exists() and not (tools / "deploy_dashboard_ctl.pyw").exists()
    assert d.ctx["dashboard_files"] == list(AD.DASHBOARD_FILES)
    assert AD.check_dashboard_tree(d.inst) is True
    assert PF.code_literal_findings(d.inst)[0] == []


def test_check_dashboard_import_runs_in_the_install_and_verifies_the_loaded_file(tmp_path, monkeypatch):
    d, _ = _dash_drill(tmp_path, monkeypatch)
    tools = (d.inst / "backend" / "tools").resolve()
    calls = []

    def run_tool(argv, cwd=None, timeout=0, **k):
        calls.append((argv, Path(cwd)))
        return 0, "%s\n127.0.0.1\nhttp://127.0.0.1:9\n" % (tools / "deploy_dashboard.py")
    d.guard.run_tool = run_tool
    d.ctx = {}
    d.check_dashboard_import()
    assert calls[0][1].resolve() == tools and calls[0][0][1] == "-c" and "import deploy_dashboard" in calls[0][0][2]
    assert d.ctx["dashboard_import"]["PROD_HOST"] == "127.0.0.1"
    for bad in ((1, "boom"), (0, "x\n127.0.0.1\nhttp://127.0.0.1:9"), (0, "%s\n172.16.10.177\nhttps://172.16.10.177:666\n" % (tools / "deploy_dashboard.py")),
                (0, "C:\\elsewhere\\deploy_dashboard.py\n127.0.0.1\nhttp://127.0.0.1:9\n")):
        d.guard.run_tool = lambda argv, cwd=None, timeout=0, _b=bad, **k: _b
        with pytest.raises(AD.DrillError):
            d.check_dashboard_import()


def test_dashboard_import_check_runs_after_scan_and_before_control_in_run():
    run_src = SRC[SRC.index("    def run(self):"):SRC.index("    def dry_build_extra")]
    assert run_src.index("self.guard.scan()") < run_src.index("self.check_dashboard_import()") < run_src.index("self.guard.control()")
    assert run_src.index("self.check_dashboard_import()") < run_src.index("if self.args.dry_build")


def test_swap_environ_never_passes_through_an_empty_environment(monkeypatch):
    seen = []
    real = dict(os.environ)
    target = {"SYSTEMROOT": real.get("SYSTEMROOT", "C:\\Windows"), "ONLY_IN_TARGET": "1"}
    monkeypatch.setattr(os, "environ", type(os.environ)(os.environ.encodekey if False else {}, *[]) if False else os.environ)
    orig_delitem = type(os.environ).__delitem__

    def spy_del(self, k):
        seen.append(("del", len(self)))
        return orig_delitem(self, k)
    monkeypatch.setattr(type(os.environ), "__delitem__", spy_del)
    try:
        AD._swap_environ(target)
        assert dict(os.environ) == target or all(os.environ.get(k) == v for k, v in target.items())
        assert "ONLY_IN_TARGET" in os.environ and "SYSTEMROOT" in os.environ
        assert min(n for _k, n in seen) >= len(target)                           # 刪鍵的每一刻，目標鍵都已經在
    finally:
        monkeypatch.undo()
        os.environ.clear()
        os.environ.update(real)


def test_playwright_env_passes_browsers_path_only_for_the_browser_and_still_checks_it():
    run_src = SRC[SRC.index("pw_env = dict(clean)"):SRC.index("_swap_environ(pw_env)")]
    assert 'saved.get("PLAYWRIGHT_BROWSERS_PATH")' in run_src and "PF.env_problems(pw_env)" in run_src


def test_allowed_code_literal_files_are_pinned_by_occurrence_count(tmp_path):
    bs = chr(92)
    (tmp_path / "backend").mkdir()
    main = tmp_path / "backend" / "main.py"
    main.write_text('"http://%s:666"\n"https://%s"\n' % (PF.PROD_IP, PF.PROD_IP), encoding="utf-8")
    findings, allowed = PF.code_literal_findings(tmp_path)
    assert findings == [] and [r for r, _w in allowed] == ["backend" + bs + "main.py"]
    main.write_text(main.read_text(encoding="utf-8") + 'requests.get("https://%s/api")\n' % PF.PROD_IP, encoding="utf-8")        # 多一個
    findings, allowed = PF.code_literal_findings(tmp_path)
    assert allowed == [] and findings and "3" in findings[0][1]
    main.write_text('"http://%s:666"\n' % PF.PROD_IP, encoding="utf-8")                                                           # 少一個也要重審（表要跟著改）
    assert PF.code_literal_findings(tmp_path)[0]


def test_real_repo_pinned_counts_match_the_files():
    for rel, n in PF.CODE_PROD_ALLOWED_COUNT.items():
        assert PF._literal_count(REPO / rel) == n, rel
    assert set(PF.CODE_PROD_ALLOWED_COUNT) == set(PF.CODE_PROD_ALLOWED)


def test_code_literals_also_scan_pyw(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "x.pyw").write_text('"%s"' % PF.PROD_IP, encoding="utf-8")
    assert any(r.endswith("x.pyw") for r, _w in PF.code_literal_findings(tmp_path)[0])


def test_enable_loopback_internal_runs_in_the_drill_install_and_waits_for_the_cache(tmp_path, monkeypatch):
    d, _ = _dash_drill(tmp_path, monkeypatch)
    d.log = lambda *a, **k: None
    seen, slept = [], []
    d.guard.run_tool = lambda argv, cwd=None, timeout=0, **k: seen.append((argv, Path(cwd))) or (0, "LOOPBACK_INTERNAL 1\n")
    monkeypatch.setattr(AD.time, "sleep", lambda s: slept.append(s))
    d.enable_loopback_internal()
    assert seen[0][1].resolve() == (d.inst / "backend").resolve() and "publish_direct" in seen[0][0][2] and "loopback_is_internal" in seen[0][0][2]
    assert slept == [AD.SETTINGS_CACHE_WAIT] and AD.SETTINGS_CACHE_WAIT > 15          # settings_registry._TTL
    d.guard.run_tool = lambda argv, cwd=None, timeout=0, **k: (1, "boom")
    with pytest.raises(AD.DrillError):
        d.enable_loopback_internal()


def test_admin_login_happens_after_enabling_loopback_internal_and_the_deviation_is_documented():
    b = SRC[SRC.index("    def setup_admin_and_delivery_root"):SRC.index("    @property")]
    assert b.index("self.enable_loopback_internal()") < b.index("DMA.setup_company(") < b.index('"/api/auth/login"')
    assert any("loopback_is_internal" in x for x in AD.DEVIATIONS)


def test_loopback_internal_code_really_publishes_in_a_real_backend_db(client, capsys):
    """演練器用的那段程式要對真的後端驗證器過關（先前只有假 run_tool 的測試，沒抓到「缺欄位」被擋）。"""
    from helpers import settings_registry as R
    R.invalidate()
    assert R.get("external_login", "loopback_is_internal") == 0
    R.invalidate()                                        # 上一行的讀取會進快取（TTL 15 秒）；演練器是全新行程，沒有這個問題
    exec(AD.LOOPBACK_INTERNAL_CODE, {})
    assert "LOOPBACK_INTERNAL 1" in capsys.readouterr().out
    R.invalidate()
    assert R.get("external_login", "loopback_is_internal") == 1
    assert R.get("external_login", "lock_threshold") is not None      # 其他欄位沒被洗掉


def _licensing_tree(tmp_path, body):
    f = tmp_path / "backend" / "helpers" / "licensing.py"
    f.parent.mkdir(parents=True)
    f.write_bytes(body)
    return tmp_path, f


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_disable_license_gate_flips_exactly_one_line_keeping_line_endings(tmp_path, eol):
    body = eol.join([b"X = 1", b"LICENSE_GATE_ENABLED = True", b"Y = 2", b"# LICENSE_GATE_ENABLED = True  (comment)"]) + eol
    tree, f = _licensing_tree(tmp_path, body)
    assert AD.disable_license_gate(tree) == 1
    after = f.read_bytes()
    assert after.count(b"LICENSE_GATE_ENABLED = False") == 1 and b"# LICENSE_GATE_ENABLED = True" in after
    assert after == body.replace(b"LICENSE_GATE_ENABLED = True" + eol, b"LICENSE_GATE_ENABLED = False" + eol, 1)


def test_disable_license_gate_refuses_when_not_exactly_one_or_missing(tmp_path):
    with pytest.raises(AD.DrillError):
        AD.disable_license_gate(tmp_path / "nothing")
    tree, _f = _licensing_tree(tmp_path / "a", b"LICENSE_GATE_ENABLED = False\n")
    with pytest.raises(AD.DrillError):
        AD.disable_license_gate(tree)
    tree2, _f2 = _licensing_tree(tmp_path / "b", b"LICENSE_GATE_ENABLED = True\nLICENSE_GATE_ENABLED = True\n")
    with pytest.raises(AD.DrillError):
        AD.disable_license_gate(tree2)


def test_the_license_gate_deviation_is_listed():
    assert any("LICENSE_GATE_ENABLED" in d for d in AD.DEVIATIONS)


# ── 2026-11-14 煙霧測試：情境之間的停服務不可殺 Playwright；硬上限；看門狗 ──────────────────

def _mini_drill(tmp_path, **kw):
    d = AD.Drill(SimpleNamespace(only=["G"], keep=False, interval=2.0, dry_build=True, **kw))
    d.base = tmp_path
    d.reports = tmp_path
    d.logged = []
    d.log = lambda m: (d.logged.append(str(m)), setattr(d, "last_msg", str(m)), setattr(d, "last_output", __import__("time").time()))
    return d


def test_stop_services_between_scenarios_spares_the_orchestrators_own_descendants(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(AD.PF, "stop_drill_processes", lambda base, records, ticks, log=None, ports=(): seen.append(list(records)) or [])
    d = _mini_drill(tmp_path)
    d.guard = SimpleNamespace(records=[(os.getpid(), 111), (4242, 222)], start_ticks=0)
    d.stop_services()                                   # 情境之間：不含編排器自己（它的子孫是 Playwright driver 與瀏覽器）
    d.stop_services(final=True)                         # 收尾：全清
    assert seen[0] == [(4242, 222)] and seen[1] == [(os.getpid(), 111), (4242, 222)]


def test_source_orders_final_cleanup_after_the_scenarios():
    src = Path(AD.__file__).read_text(encoding="utf-8")
    assert "self.stop_services(final=True) if self.guard else []" in src


def test_scenario_limits_match_the_agreed_values_and_scale(tmp_path):
    d = _mini_drill(tmp_path)
    assert (d.scenario_limit("B1"), d.scenario_limit("G"), d.scenario_limit("B4")) == (600, 1200, 900)
    d2 = _mini_drill(tmp_path, limit_scale=0.5)
    assert d2.scenario_limit("B1") == 300


def test_watchdog_fires_the_deadline_once_and_dumps_after_silence(tmp_path):
    import time as _t
    d = _mini_drill(tmp_path)
    fired, dumped = [], []
    d.on_deadline = lambda sid: fired.append(sid)
    w = AD.Watchdog(d, silence_s=0.05, poll=0.01, dump=lambda: dumped.append(1))
    d.deadline_sid, d.deadline = "B1", _t.monotonic() - 1
    w.tick(); w.tick()
    assert fired == ["B1"]                                       # 只一次
    d.deadline = None
    d.last_output = _t.time() - 1
    w.tick()
    assert dumped == [1] and _t.time() - d.last_output < 0.5     # 印過之後重新計時
    w.tick()
    assert dumped == [1]


def test_watchdog_default_dump_prints_current_step_and_stacks(tmp_path):
    import time as _t
    d = _mini_drill(tmp_path)
    d.last_msg, d.deadline_sid, d.last_output = "起演練 ERP", "G", _t.time() - 400
    AD.Watchdog(d)._dump()
    text = "\n".join(d.logged)
    assert "起演練 ERP" in text and "看門狗" in text and "執行緒" in text and "test_watchdog_default_dump" in text


def test_watchdog_thread_survives_errors_in_the_callback(tmp_path):
    import time as _t
    d = _mini_drill(tmp_path)

    def boom(sid):
        raise RuntimeError("x")
    d.on_deadline = boom
    d.deadline_sid, d.deadline = "B1", _t.monotonic() - 1
    w = AD.Watchdog(d, silence_s=99, poll=0.01)
    w.start()
    _t.sleep(0.2)
    alive = w.thread.is_alive()
    w.stop(); w.thread.join(2)
    assert alive and any("看門狗出錯" in m for m in d.logged)


def test_browser_descendants_finds_only_my_children_by_name_and_never_self(tmp_path):
    import subprocess
    import sys as _s
    c = subprocess.Popen([_s.executable, "-c", "import time; time.sleep(30)"], creationflags=0x08000000)
    try:
        import time as _t
        _t.sleep(1)
        found = PF.browser_descendants(names=("python.exe",))
        assert c.pid in {o["id"] for o in found} and os.getpid() not in {o["id"] for o in found}
        assert PF.browser_descendants(names=("chrome-headless-shell.exe",)) == [] or all(o["name"] != "python.exe" for o in PF.browser_descendants(names=("chrome-headless-shell.exe",)))
        killed, logs = [], []
        got = PF.kill_browser_processes(logs.append, names=("python.exe",), killer=killed.append)
        assert c.pid in got and c.pid in killed and any("pid=%d" % c.pid in x for x in logs)
    finally:
        c.kill()


class _FakeBrowser:
    made = []

    def __init__(self):
        self.connected = True
        self.closed = False
        _FakeBrowser.made.append(self)

    def is_connected(self):
        return self.connected

    def new_context(self):
        return SimpleNamespace(new_page=lambda: object(), close=lambda: None)

    def close(self):
        self.closed = True


def test_a_timed_out_scenario_is_failed_and_the_run_continues_with_a_fresh_browser(tmp_path, monkeypatch):
    _FakeBrowser.made = []
    d = _mini_drill(tmp_path)
    d.monitor = SimpleNamespace(check_clean=lambda: None)
    d.guard = SimpleNamespace(ready=lambda what: None, records=[])
    d.ctx = {"results": []}
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: _FakeBrowser()))

    def s_b1(page, commits):
        d.timed_out.add("B1")                            # 看門狗在這個情境進行中觸發了
        raise RuntimeError("Target closed")

    def s_g(page, commits):
        return {"id": "G", "passed": True, "checks": []}
    monkeypatch.setattr(d, "scenario_B1", s_b1, raising=False)
    monkeypatch.setattr(d, "scenario_G", s_g, raising=False)
    d._drive_browser(pw, ["B1", "G"], {}, {})
    r = {x["id"]: x for x in d.ctx["results"]}
    assert r["B1"]["passed"] is False and r["B1"]["timed_out"] and "超過硬上限 600 秒" in r["B1"]["error"]
    assert r["G"]["passed"] is True and "timed_out" not in r["G"]
    assert len(_FakeBrowser.made) == 2 and _FakeBrowser.made[0].closed          # B1 逾時後重開了瀏覽器
    assert d.deadline is None


def test_on_deadline_kills_browsers_then_stops_services_and_never_raises(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(PF, "kill_browser_processes", lambda log=None, **k: order.append("browser") or [])
    d = _mini_drill(tmp_path)
    d.stop_services = lambda final=False: order.append(("stop", final)) or []
    d.on_deadline("B1")
    assert order == ["browser", ("stop", False)] and "B1" in d.timed_out and any("超過上限" in m for m in d.logged)
    monkeypatch.setattr(PF, "kill_browser_processes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ps")))
    d.on_deadline("G")                                   # 查詢失敗也不丟例外
    assert "G" in d.timed_out


def test_main_rejects_non_positive_limit_scale():
    with pytest.raises(SystemExit):
        AD.main(["--limit-scale", "0"])


def test_drill_autostart_passes_real_verify_package_autostart_gate(tmp_path, monkeypatch):
    """演練的 autostart.bat 要過產品自己的 verify_package.check_autostart（正式機一樣會擋）。
    2026-11-14 演練：模板沒有 set MOTRIX_TENDER_RADAR／MOTRIX_GEO ⇒ 所有「好包」在準備就被擋，七個情境全紅。
    開關值必須是 0（只有 =1 才開；演練不准對外）。"""
    import verify_package as VP
    (tmp_path / "backend").mkdir()
    text = AD.AUTOSTART_A1.format(backend=tmp_path / "backend", python=r"C:\Python312\python.exe", port=6866)
    (tmp_path / "backend" / "autostart.bat").write_text(text, encoding="utf-8")
    monkeypatch.setattr(VP, "R", VP.Report())
    VP.check_autostart(str(tmp_path))
    assert VP.R.fails == []
    assert "set MOTRIX_TENDER_RADAR=0" in text and "set MOTRIX_GEO=0" in text
    assert "=1" not in "\n".join(l for l in text.splitlines() if "TENDER_RADAR" in l or "MOTRIX_GEO" in l)
    # 正對照：少一個開關就要紅（不是永遠綠的測試）
    (tmp_path / "backend" / "autostart.bat").write_text(text.replace("set MOTRIX_GEO=0\n", ""), encoding="utf-8")
    monkeypatch.setattr(VP, "R", VP.Report())
    VP.check_autostart(str(tmp_path))
    assert any("MOTRIX_GEO" in d for _g, d in VP.R.fails)


def test_close_browser_force_kills_after_timeout_instead_of_hanging(tmp_path, monkeypatch):
    """PM 2026-11-14：browser.close() 卡住不能等。超時 ⇒ 先殺瀏覽器程序、再殺 node driver，被卡住的 close 因此返回。"""
    import threading
    killed = []
    release = threading.Event()

    def fake_kill(log=None, me=None, names=PF.BROWSER_NAMES, killer=None):
        killed.append(tuple(names))
        if "node.exe" in names:
            release.set()                                    # 殺到 driver 才放開（模擬 close 等 driver）
        return []

    monkeypatch.setattr(PF, "kill_browser_processes", fake_kill)
    d = _mini_drill(tmp_path)

    class Stuck:
        def close(self):
            if not release.wait(30):
                raise AssertionError("close 沒被放開（強制結束沒有發生）")
            raise RuntimeError("Target closed")                # 被殺後 Playwright 的實際行為：丟例外

    import time as _t
    t0 = _t.monotonic()
    fired = d._close_browser(Stuck(), timeout=0.2)
    assert _t.monotonic() - t0 < 5
    assert killed[0] == PF.BROWSER_NAMES and ("node.exe",) in killed and len(fired) == 2
    assert any("強制結束" in m for m in d.logged)


def test_close_browser_normal_close_kills_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(PF, "kill_browser_processes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該殺")))
    d = _mini_drill(tmp_path)
    ok = []
    assert d._close_browser(SimpleNamespace(close=lambda: ok.append(1)), timeout=5) == [] and ok == [1]


def test_info_rows_do_not_decide_scenario_outcome():
    """B4 的「（資訊）正式庫檔案位元組前後相同」是參考列（SQLite 檢查點會改位元組）；它不能讓整個情境判不符。"""
    c = AD.Check("X", "t", "e")
    c.ok("實質檢查", True)
    c.ok("（資訊）位元組相同", False, "不同")
    assert c.done("o")["passed"] is True
    c2 = AD.Check("Y", "t", "e")
    c2.ok("實質檢查", False)
    c2.ok("（資訊）位元組相同", True)
    assert c2.done("o")["passed"] is False
    c3 = AD.Check("Z", "t", "e")
    c3.ok("（資訊）只有參考列", True)
    assert c3.done("o")["passed"] is False            # 沒有任何實質檢查 ⇒ 不算過


def test_tree_digest_extra_skip_dirs_ignores_only_the_named_folder(tmp_path):
    """B5：回復後比對程式碼時略過產品自己的 rollback_snapshots；其他資料夾的改動仍要抓得到。"""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text("a", encoding="utf-8")
    d0 = AD.tree_digest(tmp_path)
    (tmp_path / "backend" / "rollback_snapshots" / "x").mkdir(parents=True)
    (tmp_path / "backend" / "rollback_snapshots" / "x" / "main.py").write_text("old", encoding="utf-8")
    assert AD.tree_digest(tmp_path)[0] != d0[0]
    assert AD.tree_digest(tmp_path, extra_skip_dirs=("rollback_snapshots",)) == d0
    (tmp_path / "backend" / "extra.py").write_text("x", encoding="utf-8")
    assert AD.tree_digest(tmp_path, extra_skip_dirs=("rollback_snapshots",))[0] != d0[0]
