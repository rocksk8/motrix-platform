# -*- coding: utf-8 -*-
"""tools/platform/final_verify.py（W3 最終系統驗證）本身的測試：合成小樹，每一項各有『過』的正對照與『紅』的反向控制。
全部是純檔案／git 小庫，不起 app、不跑閘門。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import final_verify as F  # noqa: E402


def _git(tmp, *a):
    subprocess.run(["git", "-C", str(tmp), *a], check=True, capture_output=True, text=True, encoding="utf-8")


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _repo(tmp_path):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@x.invalid")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(root, msg="c"):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _tree(root):
    _w(root, "backend/core/registry.py", 'CORE_VERSION = "1.2"\n')
    _w(root, "backend/core/CHANGELOG.md", "# x\n\n## 1.2 — 2026-10-09\n- a\n\n## 1.1 — old\n")
    _w(root, "backend/tests/platform/l1_interface_snapshot.json", json.dumps({"core_version": "1.2", "interface": {}}))
    _w(root, "backend/modules/case/module.json", json.dumps({"key": "case", "version": "1.0.5", "provides": {"api_prefixes": ["/api/quotations"], "probes": ["/api/quotations"]}}))
    _w(root, "backend/modules/case/CHANGELOG.md", "# c\n\n## 1.0.5 — d\n- x\n")
    _w(root, "backend/version_manifest.json", json.dumps([{"module": "m", "version": "2026-10-09b", "date": "d", "time": "t", "content": "c"},
                                                          {"module": "m", "version": "2026-10-06i", "date": "d", "time": "t", "content": "c"}]))
    _w(root, "backend/db.py", "CURRENT_VERSION = 118\nV9_BASELINE = 118\n")
    _w(root, "backend/core/upgrade.py", "V9_BASELINE = 118\n")


def _by(results, id_):
    return [r for r in results if r.id == id_]


# ── V1 ──────────────────────────────────────────────────────────────────────────────────────
def test_versions_pass_on_a_consistent_tree(tmp_path):
    _tree(tmp_path)
    rs = F.check_versions(tmp_path)
    assert [r.status for r in rs] == [F.PASS] * 5, [(r.id, r.status, r.detail) for r in rs]
    assert "2026-10-09b" in _by(rs, "V1.3")[0].detail, "manifest 最新＝版號字串最大（不是檔案最後一筆）"


@pytest.mark.parametrize("edit,rid,needle", [
    (("backend/modules/case/CHANGELOG.md", "## 1.0.5", "## 1.0.4"), "V1.2", "case"),
    (("backend/core/CHANGELOG.md", "## 1.2", "## 1.3"), "V1.1", "最上面"),
    (("backend/tests/platform/l1_interface_snapshot.json", '"1.2"', '"next"'), "V1.1", "快照"),
    (("backend/modules/case/CHANGELOG.md", "## 1.0.5", "## (next) — x\n## 1.0.5"), "V1.5", "CHANGELOG"),
    (("backend/version_manifest.json", "2026-10-06i", "next"), "V1.3", "next"),
    (("backend/core/upgrade.py", "118", "117"), "V1.4", "V9_BASELINE"),
    (("backend/db.py", "CURRENT_VERSION = 118", "CURRENT_VERSION = 100"), "V1.4", "CURRENT_VERSION"),
])
def test_versions_reverse_controls(tmp_path, edit, rid, needle):
    _tree(tmp_path)
    rel, a, b = edit
    p = tmp_path / rel
    p.write_text(p.read_text(encoding="utf-8").replace(a, b, 1), encoding="utf-8", newline="\n")
    rs = F.check_versions(tmp_path)
    bad = _by(rs, rid)
    assert any(r.status == F.FAIL and needle in r.detail for r in bad), [(r.id, r.status, r.detail) for r in rs]


def test_top_heading_version():
    assert F.top_heading_version("# t\n\n## 1.0.3 — a\n## 1.0.2") == "1.0.3"
    assert F.top_heading_version("## (next) — x\n## 1.0.2").startswith("(next")
    assert F.top_heading_version("no heading") is None


# ── V2 ──────────────────────────────────────────────────────────────────────────────────────
def test_dangling_links_found_and_archive_ignored(tmp_path):
    _w(tmp_path, "docs/platform/A.md", "see [ok](B.md) and [bad](MISSING.md#x) and [web](https://x.y) and [anchor](#top) and `docs/platform/B.md` and `docs/platform/GONE.md`\n")
    _w(tmp_path, "docs/platform/B.md", "b\n")
    _w(tmp_path, "docs/platform/archive/old.md", "[dead](nowhere.md)\n")
    _w(tmp_path, "docs/windows/w.md", "[dead](nowhere.md)\n")
    broken, ticks = F.find_dangling_links(tmp_path)
    assert broken == [("docs/platform/A.md", "MISSING.md#x")], broken
    assert ticks == [("docs/platform/A.md", "docs/platform/GONE.md")], ticks


def test_check_links_statuses(tmp_path):
    _w(tmp_path, "docs/platform/A.md", "[bad](MISSING.md)\n")
    rs = F.check_links(tmp_path)
    assert _by(rs, "V2.3a")[0].status == F.FAIL
    _w(tmp_path, "docs/platform/A.md", "[ok](B.md)\n")
    _w(tmp_path, "docs/platform/B.md", "b\n")
    assert _by(F.check_links(tmp_path), "V2.3a")[0].status == F.PASS


def test_cache_index_missing_source_fails_and_stale_warns(tmp_path):
    root = _repo(tmp_path)
    _w(root, "docs/platform/BIG.md", "v1\n")
    sha = _commit(root, "first")
    _w(root, "docs/platform/CACHE-INDEX.md", "- 來源檔：docs/platform/BIG.md｜來源 commit：%s\n" % sha[:10])
    _commit(root, "idx")
    assert F.check_cache_index(root)[0].status == F.PASS
    for i in range(10):
        _w(root, "docs/platform/BIG.md", "v%d\n" % (i + 2))
        _commit(root, "edit %d" % i)
    r = F.check_cache_index(root)[0]
    assert r.status == F.WARN and "BIG.md" in r.detail, (r.status, r.detail)
    _w(root, "docs/platform/CACHE-INDEX.md", "- 來源檔：docs/platform/NOPE.md｜來源 commit：%s\n" % sha[:10])
    assert F.check_cache_index(root)[0].status == F.FAIL


def test_export_ignore_coverage(tmp_path):
    root = _repo(tmp_path)
    _w(root, "docs/windows/a.md", "a\n")
    _w(root, "docs/platform/archive/b.md", "b\n")
    _w(root, ".gitattributes", "docs/windows export-ignore\n")
    _commit(root)
    rs = F.check_export_ignore(root)
    assert [r.status for r in rs] == [F.FAIL, F.FAIL] or rs[0].status == F.FAIL, [(r.item, r.status, r.detail) for r in rs]
    _w(root, ".gitattributes", "docs/windows/** export-ignore\ndocs/platform/archive/** export-ignore\n")
    _commit(root, "attrs")
    assert [r.status for r in F.check_export_ignore(root)] == [F.PASS, F.PASS]


# ── V3 ──────────────────────────────────────────────────────────────────────────────────────
MAIN = '''
_PUBLIC_API_PATHS = {
    "/api/auth/login", "/api/ping",
}

@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_API_PATHS:
        return await call_next(request)
    return None

@app.middleware("http")
async def other(request, call_next):
    return None
'''
ROUTER = '''
from fastapi import APIRouter, Header
router = APIRouter(prefix="/api/things")

@router.get("/list")
def lst(authorization: str = Header(None)):
    _require_user(authorization)
    return []

@router.post("/{tid}/go")
def go(tid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    return {}

@router.get("/open")
def open_():
    return {}
'''


def _api_tree(root):
    _w(root, "backend/main.py", MAIN)
    _w(root, "backend/routers/things.py", ROUTER)
    _w(root, "backend/routers/auth.py", 'from fastapi import APIRouter\nrouter = APIRouter()\n@router.post("/api/auth/login")\ndef login():\n    return {}\n@router.get("/api/ping")\ndef ping():\n    return {}\n')


def test_collect_routes_prefix_and_auth_detection(tmp_path):
    _api_tree(tmp_path)
    rs = {(r["method"], r["path"]): r["authed"] for r in F.collect_routes(tmp_path)}
    assert rs[("GET", "/api/things/list")] is True and rs[("POST", "/api/things/{tid}/go")] is True
    assert rs[("GET", "/api/things/open")] is False, "沒有任何授權檢查的 handler"


def test_route_auth_layers(tmp_path, monkeypatch):
    _api_tree(tmp_path)
    allow = {"public_ok": ["/api/auth/login", "/api/ping"], "auth_ok": []}
    monkeypatch.setattr(F, "load_allow", lambda: allow)
    rs = F.check_route_auth(tmp_path)
    st = {r.id: r.status for r in rs}
    assert st["V3.2a"] == F.PASS and st["V3.2b"] == F.PASS and st["V3.2c"] == F.WARN, st
    assert "/api/things/open" in _by(rs, "V3.2c")[0].detail
    allow["auth_ok"] = ["GET /api/things/open"]
    assert {r.id: r.status for r in F.check_route_auth(tmp_path)}["V3.2c"] == F.PASS
    allow["public_ok"] = ["/api/ping"]                                 # 新增的公開路徑沒登記 ⇒ 紅
    rs = F.check_route_auth(tmp_path)
    assert _by(rs, "V3.2b")[0].status == F.FAIL and "/api/auth/login" in _by(rs, "V3.2b")[0].detail
    _w(tmp_path, "backend/main.py", MAIN.replace("or path in _PUBLIC_API_PATHS", ""))          # 閘門拿掉 ⇒ 紅
    assert _by(F.check_route_auth(tmp_path), "V3.2a")[0].status == F.FAIL


def test_frontend_calls_dangling(tmp_path):
    _api_tree(tmp_path)
    _w(tmp_path, "frontend/pages/p.html",
       "<script>fetch('/api/things/list'); fetch(`/api/things/${id}/go`); fetch('/api/things/' + id + '/go'); fetch(`/api/things/${a}/${b}${qs}`)\n"
       "fetch('/api/nothing/here'); // /api/vouchers/{x}/...\n</script>")
    miss = F.find_dangling_frontend_calls(tmp_path)
    assert list(miss) == ["/api/nothing/here"], miss


def test_probes(tmp_path):
    _api_tree(tmp_path)
    _w(tmp_path, "backend/modules/case/module.json", json.dumps({"key": "case", "version": "1", "provides": {"api_prefixes": ["/api/things"], "probes": ["/api/things/list", "/api/zzz"]}}))
    r = F.check_probes(tmp_path)[0]
    assert r.status == F.FAIL and "/api/zzz" in r.detail and "/api/things/list" not in r.detail.replace("/api/things/list 不在", "")


def test_ip_registry(tmp_path):
    _w(tmp_path, "backend/modules/case/__init__.py", 'providers={("case.access", "case"): X, ("case.nope", "case"): Y}\n')
    _w(tmp_path, "backend/routers/c.py", 'registry.single_provider("case.access")\nregistry.providers("missing.thing")\n')
    _w(tmp_path, "docs/platform/INTEGRATION-POINTS.md", "case.access is documented\n")
    rs = F.check_ip_registry(tmp_path)
    assert _by(rs, "V3.4a")[0].status == F.FAIL and "missing.thing" in _by(rs, "V3.4a")[0].detail
    assert _by(rs, "V3.4b")[0].status == F.WARN and "case.nope" in _by(rs, "V3.4b")[0].detail


# ── V4 ──────────────────────────────────────────────────────────────────────────────────────
def test_tree_hygiene(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _w(root, "README.md", "r\n")
    _w(root, "backend/a.py", "x\n")
    _commit(root)
    monkeypatch.setattr(F, "load_allow", lambda: {"root_files": ["README.md"]})
    assert [r.status for r in F.check_tree_hygiene(root)] == [F.PASS, F.PASS]
    _w(root, "backend/motrix_erp.db", "bin")
    _w(root, "backend/__pycache__/a.pyc", "bin")
    _w(root, "stray.txt", "s")
    _w(root, "notes.bak", "s")
    _commit(root, "bad")
    rs = F.check_tree_hygiene(root)
    assert rs[0].status == F.FAIL and "motrix_erp.db" in rs[0].detail and "a.pyc" in rs[0].detail and "notes.bak" in rs[0].detail
    assert rs[1].status == F.FAIL and "stray.txt" in rs[1].detail


# ── V5 ──────────────────────────────────────────────────────────────────────────────────────
SUMMARY = ("# 第四十八班（48a）套用摘要：成功\n\n::RESULT:: v=2 status=success rolled_back=applied service=up exit=0\n"
           "前後 commit：{old} → {new}\n\n1. 版本：commit 以 abc 開頭；api_version 實際值=2026-10-09b。通過\n")


def test_parse_summary_and_latest_report(tmp_path):
    d = parse = F.parse_summary(SUMMARY.format(old="a" * 40, new="b" * 40))
    assert d["status"] == "success" and d["service"] == "up" and d["exit"] == "0" and d["new_commit"] == "b" * 40 and d["api_version"] == "2026-10-09b"
    _w(tmp_path, "20261008_021000_dc4e2e42_成功/摘要.md", "old")
    _w(tmp_path, "20261009_073500_e526a2ef7_成功/摘要.md", "new")
    _w(tmp_path, "20261009_080000_zzz_已暫存/notes.txt", "no summary here")
    assert F.latest_report(tmp_path).parent.name == "20261009_073500_e526a2ef7_成功"


def test_deployed_parity(tmp_path):
    root = _repo(tmp_path / "tree")
    _w(root, "backend/version_manifest.json", json.dumps([{"module": "m", "version": "2026-10-09b", "date": "d", "time": "t", "content": "c"}]))
    sha = _commit(root)
    rep = tmp_path / "report"
    _w(rep, "20261009_073500_x_成功/摘要.md", SUMMARY.format(old="0" * 40, new=sha))
    rs = F.check_deployed(root, rep, "HEAD")
    assert [r.status for r in rs] == [F.PASS, F.PASS, F.PASS, F.SKIP], [(r.id, r.status, r.detail) for r in rs]
    _w(rep, "20261009_090000_y_成功/摘要.md", SUMMARY.format(old=sha, new="f" * 40))              # 更新的一筆：部署的不是基準
    rs = F.check_deployed(root, rep, "HEAD")
    assert _by(rs, "V5.2")[0].status == F.FAIL
    _w(rep, "20261009_090000_y_成功/摘要.md", SUMMARY.format(old=sha, new=sha).replace("status=success", "status=failed"))
    assert F.check_deployed(root, rep, "HEAD")[0].status == F.FAIL
    assert F.check_deployed(root, None)[0].status == F.SKIP


# ── 總合 ────────────────────────────────────────────────────────────────────────────────────
def test_run_checks_selection_render_and_exit_code(tmp_path, capsys):
    root = _repo(tmp_path)
    _tree(root)
    _w(root, "README.md", "r\n")
    _commit(root)
    rs = F.run_checks(root, only=["V1"])
    assert {r.id for r in rs} == {"V1.1", "V1.2", "V1.3", "V1.4", "V1.5"} and F.verdict(rs) == F.PASS
    assert {r.id for r in F.run_checks(root, only=["V1"], skip=["V1.3"])} == {"V1.1", "V1.2", "V1.4", "V1.5"}, "略過單項：只拿掉那一項"
    assert {r.id for r in F.run_checks(root, only=["V1.2"])} == {"V1.2"}, "只跑單項"
    assert F.run_checks(root, only=["V1"], skip=["V1"]) == []
    assert F.run_checks(root, only=["V4"], skip=["V4"]) == []
    assert "結論：PASS" in F.render_text(rs)
    md = F.render_markdown(rs, root, "T49")
    assert md.startswith("# 最終系統驗證 T49") and "| V1.1 " in md and "**結論：PASS**" in md
    out = tmp_path / "o.md"
    rc = F.main(["--root", str(root), "--only", "V1", "--md", str(out)])
    assert rc == 0 and out.exists()
    (root / "backend/db.py").write_text("CURRENT_VERSION = 1\nV9_BASELINE = 118\n", encoding="utf-8")
    assert F.main(["--root", str(root), "--only", "V1"]) == 1
    capsys.readouterr()


def test_a_check_that_crashes_is_reported_as_fail_not_lost(tmp_path):
    rs = F.run_checks(tmp_path, only=["V1"])                          # 空目錄：檔案不存在 ⇒ 檢查本身出錯
    assert rs and rs[0].status == F.FAIL and "檢查本身出錯" in rs[0].detail


def test_allow_file_is_valid_json_with_the_expected_keys():
    a = json.loads((REPO / "tools" / "platform" / "final_verify_allow.json").read_text(encoding="utf-8"))
    for k in ("root_files", "public_ok", "auth_ok", "dangling_links_ok", "dangling_tick_patterns", "frontend_calls_ok", "ip_ok", "tracked_ok"):
        assert isinstance(a[k], list), k
