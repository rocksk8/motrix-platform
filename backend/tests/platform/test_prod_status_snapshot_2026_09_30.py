"""prod_status_snapshot（PROD-DEV-CHANNEL §3）：假安裝目錄上的欄位齊全、各來源缺席、ping 失敗、
唯讀保證（整棵樹 mtime＋sha256 前後比對）、--out 原子寫入、輸出不含機敏欄位；各附反向控制。"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "prod_status_snapshot.py"
sys.path.insert(0, str(TOOL.parent))
import prod_status_snapshot as PS  # noqa: E402

COMMIT = "c" * 40
DONE_AT = datetime(2026, 9, 30, 2, 0, 0).timestamp()


# ── 假安裝目錄與假服務 ──────────────────────────────────────────────────────────
def _w(p, text, bom=False):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(("﻿" if bom else "") + text, encoding="utf-8")


def _build(tmp_path):
    root = tmp_path / "inst"
    be = root / "backend"
    _w(be / ".deployed_commit.json", json.dumps({"commit": COMMIT, "commit_short": COMMIT[:8], "branch": "platform",
                                                 "applied_at": "2026-09-29 10:00:00", "built_at": "2026-09-29 09:00:00",
                                                 "token": "tok-SHOULD-NOT-LEAK"}), bom=True)
    _w(be / "logs" / "module_states.json", json.dumps({"pid": 1, "started_at": "2026-09-29T10:01:00", "modules": [
        {"key": "case", "state": "loaded", "version": "1.2.0", "reason": ""},
        {"key": "tender", "state": "failed", "version": "0.3.0", "reason": "password=hunter2 in traceback"}]}))
    for ts, st in (("20260928_010000", "success"), ("20260929_100000", "unhealthy_rolled_back")):
        _w(be / "logs" / ("apply_update_%s.result.json" % ts), json.dumps(
            {"protocol": 2, "status": st, "rolled_back": "restored", "service": "up", "exit": 1, "timestamp": ts}))
    _w(be / "logs" / "apply_module_update_20991231_000000.result.json", "{}")          # 不同工具的結果檔不算
    _w(be / "db_backups" / "2026-09-28" / ".done", "")
    _w(be / "db_backups" / "2026-09-29" / ".done", "")
    _w(be / "motrix_erp.db", "not really sqlite")
    _w(root / "backup_alerts" / "2026-09-30.log",
       "2026-09-30T01:00:00\tWARN\tbefore done\n2026-09-30T03:00:00\tERROR\tuploads/ 雲端鏡像失敗，詳見 server.log\n")
    _w(root / "backup_alerts" / "BACKUP_ALERT.txt", "[ERROR] x\n")
    (be / "tools").mkdir(parents=True)
    shutil.copy2(TOOL, be / "tools" / TOOL.name)                                          # 從安裝目錄內執行 ⇒ 驗預設 --root
    cloud = tmp_path / "cloud" / "系統存檔"
    _w(cloud / "每日備份" / "2026-09-29" / ".done", "")
    os.utime(cloud / "每日備份" / "2026-09-29" / ".done", (DONE_AT, DONE_AT))
    (cloud / "每日備份" / "2026-09-30").mkdir()                                            # 今天還沒完成（無 .done）
    return root, cloud


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"/api/ping": {"ok": True}, "/api/system/version": {"version": "2026-09-30g", "date": "2026-09-30"}}.get(self.path)
        self.send_response(200 if body else 404)
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    s = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        yield s.server_address[1]
    finally:
        s.shutdown()
        s.server_close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(tool, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, str(tool), *args], capture_output=True, timeout=60, env=env)
    return r.returncode, json.loads(r.stdout.decode("utf-8"))


def _tree(root):
    """整棵樹：相對路徑 ⇒ (mtime_ns, sha256)；目錄記 None。"""
    out = {}
    for dp, dns, fns in os.walk(root):
        for d in dns:
            out[os.path.relpath(os.path.join(dp, d), root)] = None
        for f in fns:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = (os.stat(p).st_mtime_ns, hashlib.sha256(Path(p).read_bytes()).hexdigest())
    return out


# ── 機敏字詞檢查（獨立於工具的白名單）──────────────────────────────────────────────
_DENY_KEY = re.compile(r"(?i)passw|secret|token|api[_-]?key|credential|private|authorization|cookie|license|smtp|e-?mail|session")
_DENY_VAL = re.compile(r"(?i)passw|hunter2|tok-|-----BEGIN|bearer\s|[\w.+-]+@[\w-]+\.[\w.]+")


def _violations(obj, path=""):
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _DENY_KEY.search(str(k)):
                bad.append("key " + path + "/" + str(k))
            bad += _violations(v, path + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += _violations(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str) and _DENY_VAL.search(obj):
        bad.append("value " + path)
    return bad


# ── 題目 ─────────────────────────────────────────────────────────────────────
def test_all_fields_present(tmp_path, server):
    root, cloud = _build(tmp_path)
    code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(server), "--archive-root", str(cloud))
    assert code == 0 and s["errors"] == {}, s["errors"]
    assert s["install_root"] == str(root) and s["hostname"] == socket.gethostname()
    assert s["deployed_commit"] == COMMIT and s["deployed"]["branch"] == "platform"
    assert s["ping"] == 200 and s["api_version"] == "2026-09-30g" and s["api_base_url"].startswith("http://")
    assert s["modules"] == [{"key": "case", "version": "1.2.0", "state": "loaded"},
                            {"key": "tender", "version": "0.3.0", "state": "failed"}]
    assert s["last_apply"] == {"timestamp": "20260929_100000", "status": "unhealthy_rolled_back", "rolled_back": "restored",
                               "service": "up", "exit": 1, "result_file": "apply_update_20260929_100000.result.json"}
    b = s["backups"]
    assert b["archive_root_source"] == "arg" and b["daily_done_latest"] == {"date": "2026-09-29", "done_at": "2026-09-30T02:00:00"}
    assert b["local_snapshot_done_latest"]["date"] == "2026-09-29"
    assert b["alerts_since"]["timestamp"] == "2026-09-30T03:00:00" and b["alerts_since"]["level"] == "ERROR"
    assert b["sticky_alert_file"] is True
    assert isinstance(s["disk_free_gb"], float) and s["disk_free_gb"] > 0
    if os.name == "nt":
        assert os.getpid() in s["service_pids_on_666"]                                   # 本題的假服務就在本行程


@pytest.mark.parametrize("remove, field", [
    ("backend/.deployed_commit.json", "deployed_commit"),
    ("backend/logs/module_states.json", "modules"),
    ("backend/logs/apply_update_*.result.json", "last_apply"),
    ("CLOUD", "backups.daily_done_latest"),
    ("backend/db_backups", "backups.local_snapshot_done_latest"),
])
def test_each_source_missing_is_null_with_reason(tmp_path, server, remove, field):
    root, cloud = _build(tmp_path)
    if remove == "CLOUD":
        shutil.rmtree(cloud)
    else:
        for p in root.glob(remove):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(server), "--archive-root", str(cloud))
    assert code == 0 and set(s["errors"]) - {"backups.alerts_since"} == {field}, s["errors"]
    node = s
    for part in field.split("."):
        node = node[part]
    assert node is None
    assert s["ping"] == 200                                                               # 其他來源照常


def test_nonexistent_root_never_crashes(tmp_path):
    code, s = _run(TOOL, "--root", str(tmp_path / "nope"), "--port", str(_free_port()),
                   "--archive-root", str(tmp_path / "nocloud"), "--timeout", "1")
    assert code == 0 and "install_root" in s["errors"] and s["deployed_commit"] is None and s["modules"] is None


def test_ping_failure_recorded(tmp_path):
    root, cloud = _build(tmp_path)
    code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(_free_port()), "--archive-root", str(cloud),
                   "--timeout", "1")
    assert code == 0 and s["ping"] is None and s["api_version"] is None
    assert s["errors"]["ping"] and s["errors"]["api_version"] and s["deployed_commit"] == COMMIT


def test_https_chosen_when_cert_present(tmp_path):
    root, cloud = _build(tmp_path)
    _w(root / "backend" / "certs" / "cert.pem", "x")
    _code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(_free_port()), "--archive-root", str(cloud),
                    "--timeout", "1")
    assert s["api_base_url"].startswith("https://127.0.0.1:")


def test_read_only_install_and_archive_trees_unchanged(tmp_path, server):
    root, cloud = _build(tmp_path)
    before, cbefore = _tree(root), _tree(cloud)
    _run(root / "backend" / "tools" / TOOL.name, "--port", str(server), "--archive-root", str(cloud),
         "--out", str(tmp_path / "report" / "status" / "latest.json"))
    assert _tree(root) == before and _tree(cloud) == cbefore


def test_read_only_reverse_control_mutant_that_writes_is_caught(tmp_path, server):
    """反向控制：把工具改成在安裝目錄內寫一個檔 ⇒ 上一題的比對必須轉紅。"""
    root, cloud = _build(tmp_path)
    tool = root / "backend" / "tools" / TOOL.name
    src = tool.read_text(encoding="utf-8")
    anchor = "    return snap\n\n\ndef _inside"
    assert src.count(anchor) == 1
    tool.write_text(src.replace(anchor, "    open(os.path.join(root, 'backend', 'logs', 'x.tmp'), 'w').close()\n" + anchor),
                    encoding="utf-8")
    before = _tree(root)
    _run(tool, "--port", str(server), "--archive-root", str(cloud))
    assert _tree(root) != before


def test_out_atomic_write_and_refusals(tmp_path, server):
    root, cloud = _build(tmp_path)
    out = tmp_path / "report" / "status" / "latest.json"
    out.parent.parent.mkdir()
    code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(server), "--archive-root", str(cloud), "--out", str(out))
    assert code == 0 and s["written_to"] == str(out)
    assert json.loads(out.read_text(encoding="utf-8")) == s and not list(out.parent.glob("*.tmp"))
    # 覆寫：寫入中途失敗 ⇒ 舊檔原封不動（先 .tmp 再 os.replace）
    old = out.read_bytes()

    class Boom(dict):
        def items(self):
            raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        PS.write_out(Boom(a=1), str(out), str(root))
    assert out.read_bytes() == old and not list(out.parent.glob("*.tmp"))
    # 拒絕：安裝目錄內／上兩層不存在
    inside = root / "backend" / "logs" / "latest.json"
    code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(_free_port()), "--archive-root", str(cloud),
                   "--timeout", "1", "--out", str(inside))
    assert code == 2 and "out" in s["errors"] and not inside.exists()
    with pytest.raises(ValueError):
        PS.write_out({}, str(tmp_path / "no" / "such" / "latest.json"), str(root))


def test_output_has_no_secrets(tmp_path, server):
    root, cloud = _build(tmp_path)
    _code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(server), "--archive-root", str(cloud))
    assert _violations(s) == []


@pytest.mark.parametrize("inject", [
    {"api_token": "x"}, {"deployed": {"password": "x"}}, {"modules": [{"key": "a", "reason": "password=hunter2"}]},
    {"contact": "someone@example.com"},
])
def test_secret_denylist_reverse_control(tmp_path, inject):
    """反向控制：工具輸出多了一個機敏欄位／值 ⇒ 上一題的檢查必須轉紅。"""
    root, cloud = _build(tmp_path)
    _code, s = _run(root / "backend" / "tools" / TOOL.name, "--port", str(_free_port()), "--archive-root", str(cloud),
                    "--timeout", "1")
    assert _violations(s) == []
    s.update(inject)
    assert _violations(s) != []
