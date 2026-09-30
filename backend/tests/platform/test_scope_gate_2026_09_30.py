"""範圍驗證閘門（tools/platform/scope_gate.py；底層清單 tools/platform/bottom_layer.json；PLAYBOOK §D-1a）。

使用者 2026-09-30：「如果未影響到底層，審核測試上包可由獨立模組，不需要跑全域」。
- (a) 動到底層 ⇒ 範圍驗證紀錄不被接受；(b) 只動模組 ⇒ 接受；(c) 別的 commit／dirty／紅／基準不同／模組集合不同 ⇒ 不接受
- (d) 反向控制：對 scope_gate.py 的原始碼做真突變（拿掉判定的那一句），對應的題必須轉紅
- 清單本身：必要路徑都在底層、fixture 層與 ship_tier 的完整包路徑都在底層、每一條規則今天都對得到檔（不是過期規則）、
  沒有規則符合 ⇒ 底層（fail closed）
- 整合：暫存 git repo 上真的算 P→X（assess／gate）；部署儀表板閘門；建包腳本的分支與 manifest 欄位
"""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SG_PATH = REPO / "tools" / "platform" / "scope_gate.py"
_spec = importlib.util.spec_from_file_location("_scope_gate", SG_PATH)
SG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SG)

PG = SG.pages_rel() + "/"          # 宣告頁面的目錄（core.paths；test_page_paths_centralized）
#: 合成的模組（守門的正對照不綁真的 L2 模組，MODULE-GUIDE §7）
PAGES = {"alpha": {PG + "alpha.html"}, "beta": {PG + "beta.html", PG + "shared.html"}, "gamma": {PG + "shared.html"}}
C, B = "c" * 40, "b" * 40

REQUIRED_BOTTOM = [
    "backend/core/registry.py", "backend/core/CHANGELOG.md", "backend/helpers/auth.py", "backend/db.py",
    "backend/main.py", "backend/migrations_frozen/v001.py", "backend/routers/approval_queue.py",
    "backend/conftest.py", "backend/tests/conftest.py", "backend/modules/alpha/tests/conftest.py",
    "backend/pytest.ini", "backend/requirements.txt", "backend/requirements-dev.txt",
    "backend/modules/alpha/migrations/0001_init.py",
    "backend/tools/build_deploy_package.ps1", "backend/tools/deploy_dashboard.py",
    "tools/platform/modtest.py", "tools/platform/scope_gate.py", "tools/platform/bottom_layer.json",
    "frontend/static/auth-guard.js", "frontend/js/voucher.js", "frontend/css/app.css", "frontend/fonts/x.ttf",
    "frontend/index.html", "product/full.json", "backend/backup_job.py", "backend/start.bat",
    "backend/tests/platform/child_module_gate.py",           # 測試共用工具（不是 test_*.py）
    PG + "shared.html", PG + "nobody.html",                  # 兩個模組／沒有模組宣告 ⇒ 共用頁
]
SCOPED_OK = ["backend/modules/alpha/service.py", "backend/modules/alpha/module.json", "backend/modules/alpha/CHANGELOG.md",
             "backend/modules/alpha/tests/test_service.py", PG + "alpha.html", "backend/tests/test_something_2026_09_30.py",
             "docs/platform/RUN-PLAN.md", "README-X.md", "backend/version_manifest.json", "backend/tests/_prod_baseline.py"]


def _rules(mod=SG):
    return mod.load_rules()


def _record(**kw):
    rec = {"kind": "scoped", "format": SG.FORMAT, "commit": C, "base": B, "dirty": False, "ok": True, "units": ["alpha"],
           "tests": ["backend/tests/platform/test_x.py"]}
    rec.update(kw)
    return rec


def _mutant(old, new):
    """scope_gate.py 的真突變（原句必須恰好出現一次，否則清單過期）。"""
    src = SG_PATH.read_text(encoding="utf-8")
    assert src.count(old) == 1, "突變原句在 scope_gate.py 出現 %d 次（要更新這一題）" % src.count(old)
    m = types.ModuleType("_scope_gate_mutant")
    m.__file__ = str(SG_PATH)
    exec(compile(src.replace(old, new, 1), str(SG_PATH), "exec"), m.__dict__)
    return m


# ── 題目本體（真實模組與突變模組共用）────────────────────────────────────────────

def case_a_bottom_change_rejected(mod):
    d = mod.decide(["backend/modules/alpha/service.py", "backend/helpers/auth.py"], mod.load_rules(), PAGES)
    ok, detail = mod.judge(_record(), C, B, d)
    return (d["mode"] == "full") and not ok and "backend/helpers/auth.py" in detail


def case_b_module_only_accepted(mod):
    d = mod.decide(SCOPED_OK, mod.load_rules(), PAGES)
    ok, _ = mod.judge(_record(), C, B, d)
    return d["mode"] == "scoped" and d["modules"] == ["alpha"] and ok


def case_c_other_commit_rejected(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    ok, detail = mod.judge(_record(commit="d" * 40), C, B, d)
    return not ok and "dddddddd" in detail


def case_unknown_path_is_bottom(mod):
    rules = mod.load_rules()
    return all(mod.classify_path(f, rules, PAGES)["layer"] == "bottom"
               for f in ("weird/new.txt", ".gitattributes", "backend/tests/_helper.py", "start_server.ps1"))


# ── (a)(b)(c)：正題 ──────────────────────────────────────────────────────────

def test_bottom_layer_change_rejects_a_scoped_result():
    assert case_a_bottom_change_rejected(SG)


@pytest.mark.parametrize("f", REQUIRED_BOTTOM)
def test_required_paths_are_bottom(f):
    c = SG.classify_path(f, _rules(), PAGES)
    assert c["layer"] == "bottom", (f, c)
    d = SG.decide(["backend/modules/alpha/service.py", f], _rules(), PAGES)
    assert d["mode"] == "full" and [f, c["why"]] in d["bottom"]
    assert not SG.judge(_record(), C, B, d)[0]


def test_module_only_change_accepts_a_scoped_result():
    assert case_b_module_only_accepted(SG)


@pytest.mark.parametrize("f", SCOPED_OK)
def test_scoped_ok_paths_are_not_bottom(f):
    assert SG.classify_path(f, _rules(), PAGES)["layer"] != "bottom", f


def test_two_modules_and_their_pages_are_scoped_with_both_units():
    d = SG.decide(["backend/modules/alpha/a.py", PG + "beta.html"], _rules(), PAGES)
    assert d["mode"] == "scoped" and d["modules"] == ["alpha", "beta"]
    assert not SG.judge(_record(units=["alpha"]), C, B, d)[0]         # 紀錄只驗了 alpha ⇒ 不接受
    assert SG.judge(_record(units=["beta", "alpha"]), C, B, d)[0]


def test_bookkeeping_rules_bring_their_guard_tests():
    d = SG.decide(["backend/version_manifest.json"], _rules(), PAGES)
    assert d["mode"] == "scoped" and d["modules"] == []
    assert any("test_version_manifest" in t for t in d["extra_tests"])
    for t in d["extra_tests"]:
        assert (REPO / t).is_file(), "規則附帶的題不存在（改名了？）：%s" % t


def test_scoped_result_for_another_commit_is_rejected():
    assert case_c_other_commit_rejected(SG)


@pytest.mark.parametrize("bad, word", [
    ({"dirty": True}, "未 commit"), ({"dirty": None}, "未 commit"), ({"ok": False}, "沒有全綠"),
    ({"base": "e" * 40}, "基準"), ({"units": []}, "不一致"), ({"kind": "unreadable"}, "不是範圍驗證"),
    ({"format": 99}, "不是範圍驗證"),
])
def test_scoped_result_rejected_when_any_field_disagrees(bad, word):
    d = SG.decide(["backend/modules/alpha/service.py"], _rules(), PAGES)
    ok, detail = SG.judge(_record(**bad), C, B, d)
    assert not ok and word in detail, (bad, detail)


def test_no_record_is_rejected():
    d = SG.decide(["backend/modules/alpha/service.py"], _rules(), PAGES)
    assert SG.judge(None, C, B, d) == (False, "這個 commit 沒有範圍驗證紀錄（scope_gate.py run）")


def test_unknown_paths_fall_back_to_bottom():
    assert case_unknown_path_is_bottom(SG)


# ── 清單本身 ────────────────────────────────────────────────────────────────

def test_fixture_layer_and_ship_tier_full_paths_are_bottom():
    """modtest 的 fixture 層、ship_tier 的「一定完整包」前綴都必須在底層（三份清單不可以各說各話）。"""
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    import modtest
    import ship_tier
    rules = _rules()
    for f in modtest.FIXTURE_LAYER:
        assert SG.classify_path(f, rules, PAGES)["layer"] == "bottom", f
    for p in ship_tier.FULL_PREFIXES:
        assert SG.classify_path(p + "x.py", rules, PAGES)["layer"] == "bottom", p


def test_every_rule_still_matches_a_tracked_file():
    """正對照：每一條規則今天都對得到至少一個已追蹤的檔（規則沒有過期；改名後舊規則會靜默失效）。"""
    files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, encoding="utf-8",
                           check=True).stdout.splitlines()
    assert len(files) > 500
    dead = [r["pattern"] for r in _rules() if not any(r["re"].match(f) for f in files)]
    assert dead == [], "這些規則對不到任何檔（過期）：%s" % dead


def test_config_is_the_single_source():
    """底層清單只在 bottom_layer.json：scope_gate.py 不另寫路徑前綴（除了讀基準檔與模組目錄的樣式）。"""
    src = SG_PATH.read_text(encoding="utf-8")
    for lit in ('"backend/core', '"backend/helpers', '"frontend/static', '"backend/tools'):
        assert lit not in src, lit
    raw = json.loads((REPO / "tools" / "platform" / "bottom_layer.json").read_text(encoding="utf-8"))
    assert raw["rules"][0]["layer"] == "bottom"


def test_malformed_config_is_refused(tmp_path):
    p = tmp_path / "b.json"
    for bad in ({"format": 2, "rules": [{"pattern": "x", "layer": "bottom", "why": "y"}]},
                {"format": 1, "rules": []},
                {"format": 1, "rules": [{"pattern": "x", "layer": "wat", "why": "y"}]},
                {"format": 1, "rules": [{"pattern": "x", "layer": "bottom"}]}):
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            SG.load_rules(p)


def test_run_ok_needs_both_stages_and_the_train_guards():
    import modtest
    g = set(modtest.TRAIN_GUARDS)
    assert SG.run_ok(0, "", 0, g)[0]
    assert SG.run_ok(0, "", 5, g)[0]                                # 沒選到 e2e 題
    assert not SG.run_ok(1, "", 0, g)[0]
    assert not SG.run_ok(0, "", 1, g)[0]
    assert not SG.run_ok(5, "", 0, g)[0]                            # 非 e2e 段沒收集到 ⇒ 不算綠
    assert not SG.run_ok(0, "SKIPPED [1] x: needs MOTRIX_TRAIN", 0, g)[0]
    assert not SG.run_ok(0, "", 0, set())[0]


# ── (d) 反向控制：真突變 ⇒ 對應的題轉紅 ─────────────────────────────────────────

MUTATIONS = [
    ("(a) 底層檔不再讓判定變成全量", case_a_bottom_change_rejected,
     'return {"mode": "full" if bottom else "scoped"', 'return {"mode": "scoped"'),
    ("(a') 閘門不看判定的 mode", case_a_bottom_change_rejected,
     '    if decision.get("mode") != "scoped":\n', '    if False:\n'),
    ("(b) 模組沒有記進單位", case_b_module_only_accepted,
     '        elif c["key"]:\n            mods.add(c["key"])\n', '        elif c["key"]:\n            pass\n'),
    ("(c) 不比對紀錄的 commit", case_c_other_commit_rejected,
     '    if (record.get("commit") or "") != commit:\n', '    if False:\n'),
    ("fail closed：沒有規則符合 ⇒ 不再是底層", case_unknown_path_is_bottom,
     'return {"layer": "bottom", "key": None, "why": "沒有任何規則符合', 'return {"layer": "doc", "key": None, "why": "沒有任何規則符合'),
]


@pytest.mark.parametrize("name, case, old, new", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_reverse_control_each_mutation_turns_its_case_red(name, case, old, new):
    assert case(SG), "正對照：真實模組要綠"
    assert not case(_mutant(old, new)), "突變後仍綠 ⇒ 這一題守不住：%s" % name


def test_reverse_control_removing_a_bottom_rule_turns_required_paths_red(monkeypatch, tmp_path):
    """清單突變：拿掉 backend/helpers/** ⇒ helpers 的檔掉到 fallback（仍是底層：fail closed 兜住）；
    再把 fallback 改成 doc ⇒ 必要路徑題轉紅。證明「必要路徑」題真的依賴清單＋fallback。"""
    raw = json.loads((REPO / "tools" / "platform" / "bottom_layer.json").read_text(encoding="utf-8"))
    raw["rules"] = [r for r in raw["rules"] if r["pattern"] != "backend/helpers/**"]
    p = tmp_path / "bottom_layer.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    rules = SG.load_rules(p)
    assert SG.classify_path("backend/helpers/auth.py", rules, PAGES)["layer"] == "bottom"
    m = _mutant('return {"layer": "bottom", "key": None, "why": "沒有任何規則符合',
                'return {"layer": "doc", "key": None, "why": "沒有任何規則符合')
    assert m.classify_path("backend/helpers/auth.py", m.load_rules(p), PAGES)["layer"] != "bottom"


# ── 整合：暫存 git repo 上真的算 P→X ─────────────────────────────────────────────

def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "core.autocrlf=false", *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def _w(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def mini(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _g(r, "init", "-q")
    _w(r, "backend/core/registry.py", '"""\n[公開介面] CORE_VERSION, single_provider\n"""\nCORE_VERSION = "1.0"\n\n\n'
                                      "def single_provider(capability):\n    return None\n")
    _w(r, "backend/helpers/util.py", "X = 1\n")
    _w(r, "backend/modules/alpha/__init__.py", "")
    _w(r, "backend/modules/alpha/service.py", "def f():\n    return 1\n")
    _w(r, "backend/modules/alpha/module.json", json.dumps({"key": "alpha", "version": "1.0.0",
                                                            "pages": [{"path": "alpha.html"}]}))
    _w(r, PG + "alpha.html", "<html></html>\n")
    _w(r, SG.BASELINE_REL, 'BASELINE = "0000000"\n')
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "P")
    p = _g(r, "rev-parse", "HEAD")
    _w(r, SG.BASELINE_REL, 'BASELINE = "%s"\n' % p[:8])       # 部署後把基準往後移（bookkeeping，不算底層）
    _w(r, "backend/modules/alpha/service.py", "def f():\n    return 2\n")
    _w(r, PG + "alpha.html", "<html><body></body></html>\n")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "X module only")
    x = _g(r, "rev-parse", "HEAD")
    _w(r, "backend/helpers/util.py", "X = 2\n")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "Y touches L1")
    y = _g(r, "rev-parse", "HEAD")
    return {"repo": r, "p": p, "x": x, "y": y, "rdir": tmp_path / "scoped"}


def _put(rdir, commit, **kw):
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / (commit + ".json")).write_text(json.dumps(dict(_record(), commit=commit, **kw)), encoding="utf-8")


def test_integration_module_only_commit_is_scoped_and_accepted(mini):
    a = SG.assess(mini["x"], repo=mini["repo"])
    assert a["base"] == mini["p"] and a["decision"]["mode"] == "scoped", a["decision"]
    assert a["decision"]["modules"] == ["alpha"]
    assert SG.gate(mini["x"], repo=mini["repo"], rdir=mini["rdir"])["accepted"] is False     # 還沒有紀錄
    _put(mini["rdir"], mini["x"], base=mini["p"], units=["alpha"])
    g = SG.gate(mini["x"], repo=mini["repo"], rdir=mini["rdir"])
    assert g["accepted"] is True and g["mode"] == "scoped", g


def test_integration_l1_commit_needs_full_even_with_a_green_scoped_record(mini):
    _put(mini["rdir"], mini["y"], base=mini["p"], units=["alpha"])
    g = SG.gate(mini["y"], repo=mini["repo"], rdir=mini["rdir"])
    assert g["accepted"] is False and "backend/helpers/util.py" in g["detail"], g


def test_integration_record_of_x_does_not_cover_y(mini):
    _put(mini["rdir"], mini["x"], base=mini["p"], units=["alpha"])
    rec = json.loads((mini["rdir"] / (mini["x"] + ".json")).read_text(encoding="utf-8"))
    (mini["rdir"] / (mini["y"] + ".json")).write_text(json.dumps(rec), encoding="utf-8")   # 抄到 Y 的檔名
    g = SG.gate(mini["y"], repo=mini["repo"], rdir=mini["rdir"])
    assert g["accepted"] is False


def test_integration_unreadable_baseline_means_full(mini):
    _w(mini["repo"], SG.BASELINE_REL, "BASELINE = None\n")
    _g(mini["repo"], "add", "-A")
    _g(mini["repo"], "commit", "-q", "-m", "broken baseline")
    z = _g(mini["repo"], "rev-parse", "HEAD")
    a = SG.assess(z, repo=mini["repo"])
    assert a["decision"]["mode"] == "full" and a["base"] is None


# ── 建包腳本（儀表板閘門的題在 test_deploy_dashboard_scope_gate_2026_09_30.py：
#    只有 test_deploy_dashboard* 檔可以 import 部署儀表板，HC1c）─────────────────────────

def test_build_script_uses_scope_gate_and_records_the_mode():
    s = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    assert 'scope_gate.py") gate --commit $commit --json' in s
    assert "if (-not $reuse -and -not $ForceTests)" in s                     # -ForceTests ⇒ 一律全量
    assert "$sg.accepted -eq $true -and $sg.commit -eq $commit" in s         # 只接受這個 commit 的判定
    i_scoped, i_full = s.index("} elseif ($scoped) {"), s.index('Write-Host "`n[測試] 執行 pytest（非 e2e')
    assert i_scoped < i_full                                                   # 全量分支仍在，排在 else
    assert 'mode         = "scoped"' in s and "verification         = $Verification" in s
