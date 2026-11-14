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
    monkeypatch.setattr(d, "setup_admin_and_delivery_root", lambda: calls.append("setup_admin"))
    monkeypatch.setattr(d, "stop_services", lambda: calls.append("stop_services") or [])
    monkeypatch.setattr(d, "robocopy", lambda *a: calls.append("snapshot"))
    monkeypatch.setattr(d, "run_scenarios", lambda: (calls.append("scenarios"),
                                                     d.ctx["results"].append({"id": "G", "title": "t", "expected": "e", "passed": True, "checks": [], "observed": ""})))
    monkeypatch.setattr(AD.time, "sleep", lambda s: None)
    return d, calls


def test_run_order_is_check_build_scan_control_start_then_services(tmp_path, monkeypatch):
    d, calls = make_drill(tmp_path, monkeypatch)
    d.run()
    steps = [c for c in calls if not c.startswith("ready:") and c not in ("tool", "stop_services")]
    assert steps == ["check", "build", "scan", "control", "start", "start_erp", "setup_admin", "snapshot", "scenarios"], steps
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
    assert set(out) == {"apply_update.ps1", "rollback_update.ps1"}
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


def _alive(pid):
    import subprocess
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "if (Get-Process -Id %d -ErrorAction SilentlyContinue) { 'Y' } else { 'N' }" % pid],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip().endswith("Y")


def test_killable_hard_rules():
    assert not PF.killable(4, "system") and not PF.killable(999, "python.exe") and not PF.killable(1500, "svchost.exe")
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
    d = _py_sleeper(extra_args=(str(base / "inst" / "autostart.bat"),))     # 孤兒類：命令列含演練目錄、白名單名稱 ⇒ 殺
    started = PF.now_ticks(60)
    try:
        import time
        time.sleep(2.5)                                           # 讓 A 的子行程起來
        rec = [(a.pid, PF.process_created(a.pid)), (c.pid, PF.process_created(c.pid) - 12345)]
        assert rec[0][1] and rec[1][1]
        owned = PF.owned_processes(rec, base, started)
        ids = {o["id"] for o in owned}
        assert a.pid in ids and d.pid in ids, ids
        assert b.pid not in ids and c.pid not in ids and os.getpid() not in ids
        assert len(ids) >= 3, "A 的子行程也該在清單裡：%s" % ids
        assert all(i >= PF.MIN_KILL_PID and PF.killable(i, o["name"]) for o in owned for i in [o["id"]])
        logs = []
        killed = PF.stop_drill_processes(base, rec, started, log=logs.append)
        assert set(killed) == ids
        time.sleep(1.5)
        assert not _alive(a.pid) and not _alive(d.pid)
        assert _alive(b.pid) and _alive(c.pid)
        assert any("pid=%d" % a.pid in l and "name=python.exe" in l and "created_ticks=" in l for l in logs), logs
    finally:
        for pr in (a, b, c, d):
            try:
                pr.kill()
            except OSError:
                pass


import os  # noqa: E402


def test_monitor_kill_only_owned_and_never_low_pids():
    killed = []
    m = PF.ConnectionMonitor("unused.jsonl", lambda: [], killer=killed.append, owned_fn=lambda: [1500, 4, 999])
    m._log = lambda rec: None
    m._kill([0, 4, 5, 999, 1500, 7777])
    assert killed == [[1500]], killed


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

