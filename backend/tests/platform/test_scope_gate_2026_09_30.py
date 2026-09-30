"""範圍驗證閘門（tools/platform/scope_gate.py；底層清單 tools/platform/bottom_layer.json；PLAYBOOK §D-1a）。

使用者 2026-09-30：「如果未影響到底層，審核測試上包可由獨立模組，不需要跑全域」。
- (a) 動到底層 ⇒ 範圍驗證紀錄不被接受；(b) 只動模組 ⇒ 接受；(c) 別的 commit／dirty／紅／基準不同／模組集合不同 ⇒ 不接受
- 稽核 W4：M1 全域釘子必選＋掃描；M2 紀錄的規則雜湊、題目 ⊇ 重算、題數與兩段 exit；M3 規則取自 X、判定只在 HEAD＝X 且
  工具路徑乾淨；M4 基準必須等於受信 tag prod/<sha>
- (d) 反向控制：對 scope_gate.py（與 _scope_gate.ps1）的原始碼做真突變（拿掉判定的那一句），對應的題必須轉紅
- 清單本身：必要路徑都在底層、fixture 層與 ship_tier 的完整包路徑都在底層、每一條規則今天都對得到檔、沒有規則符合 ⇒ 底層
- 整合：暫存 git repo 上真的算 P→X（assess／gate）；建包腳本的判定段（PowerShell 實跑，假 scope_gate）
儀表板閘門的題在 test_deploy_dashboard_scope_gate_2026_09_30.py（HC1c：只有 test_deploy_dashboard* 可以 import 儀表板）。
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SG_PATH = REPO / "tools" / "platform" / "scope_gate.py"
CFG_PATH = REPO / "tools" / "platform" / "bottom_layer.json"
PS_GATE = REPO / "backend" / "tools" / "_scope_gate.ps1"
_spec = importlib.util.spec_from_file_location("_scope_gate", SG_PATH)
SG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SG)

PG = SG.pages_rel() + "/"          # 宣告頁面的目錄（core.paths；test_page_paths_centralized）
#: 合成的模組（守門的正對照不綁真的 L2 模組，MODULE-GUIDE §7）
PAGES = {"alpha": {PG + "alpha.html"}, "beta": {PG + "beta.html", PG + "shared.html"}, "gamma": {PG + "shared.html"}}
C, B, CS = "c" * 40, "b" * 40, "f" * 64
T_OK = ["backend/tests/platform/test_x.py", "backend/modules/alpha/tests/test_a.py"]
GLOBAL_SIX = ["test_system_audit_2026_09_14", "test_demo_reset_2026_09_23", "test_module_registry_2026_09_24",
              "test_module_keys_consistency_2026_09_13", "test_edit_log_no_delete_trigger_2026_09_24",
              "test_alpine_double_init_2026_09_23"]

REQUIRED_BOTTOM = [
    "backend/core/registry.py", "backend/core/CHANGELOG.md", "backend/helpers/auth.py", "backend/db.py",
    "backend/main.py", "backend/migrations_frozen/v001.py", "backend/routers/approval_queue.py",
    "backend/conftest.py", "backend/tests/conftest.py", "backend/modules/alpha/tests/conftest.py",
    "backend/pytest.ini", "backend/requirements.txt", "backend/requirements-dev.txt",
    "backend/modules/alpha/migrations/0001_init.py",
    "backend/tools/build_deploy_package.ps1", "backend/tools/_scope_gate.ps1", "backend/tools/deploy_dashboard.py",
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
           "tests": list(T_OK), "config_sha256": CS, "main": {"exit": 0, "passed": 12}, "e2e": {"exit": 5}}
    rec.update(kw)
    return rec


def _judge(mod, rec, d, expected=tuple(T_OK), config_sha=CS):
    return mod.judge(rec, C, B, d, config_sha, None if expected is None else list(expected))


def _mutant(old, new, path=SG_PATH):
    """原始碼的真突變（原句必須恰好出現一次，否則清單過期）。"""
    src = path.read_text(encoding="utf-8")
    assert src.count(old) == 1, "突變原句在 %s 出現 %d 次（要更新這一題）" % (path.name, src.count(old))
    m = types.ModuleType("_scope_gate_mutant")
    m.__file__ = str(path)
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


# ── 題目本體（真實模組與突變模組共用）────────────────────────────────────────────

def case_a_bottom_change_rejected(mod):
    d = mod.decide(["backend/modules/alpha/service.py", "backend/helpers/auth.py"], mod.load_rules(), PAGES)
    ok, detail = _judge(mod, _record(), d)
    return (d["mode"] == "full") and not ok and "backend/helpers/auth.py" in detail


def case_b_module_only_accepted(mod):
    d = mod.decide(SCOPED_OK, mod.load_rules(), PAGES)
    ok, _ = _judge(mod, _record(), d)
    return d["mode"] == "scoped" and d["modules"] == ["alpha"] and ok


def case_c_other_commit_rejected(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    ok, detail = _judge(mod, _record(commit="d" * 40), d)
    return not ok and "dddddddd" in detail


def case_unknown_path_is_bottom(mod):
    rules = mod.load_rules()
    return all(mod.classify_path(f, rules, PAGES)["layer"] == "bottom"
               for f in ("weird/new.txt", ".gitattributes", "backend/tests/_helper.py", "start_server.ps1"))


def case_m1_global_tests_ride_along(mod):
    rules = mod.load_rules()
    for f in ("backend/modules/alpha/api/cashier.py", PG + "alpha.html"):
        extra = mod.decide([f], rules, PAGES)["extra_tests"]
        if not all(any(n in t for t in extra) for n in GLOBAL_SIX):
            return False
    return True


def case_m2_config_hash_must_match(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    ok, detail = _judge(mod, _record(config_sha256="0" * 64), d)
    return not ok and "底層清單" in detail


def case_m2_record_must_cover_recomputed_tests(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    ok, detail = _judge(mod, _record(), d, expected=T_OK + ["backend/tests/test_system_audit_2026_09_14.py"])
    return not ok and "少跑" in detail


def case_m2_main_stage_must_have_passed_tests(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    return not _judge(mod, _record(main={"exit": 0, "passed": 0}), d)[0]


def case_m2_e2e_exit_checked(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    return not _judge(mod, _record(e2e={"exit": 1}), d)[0]


def case_m2_no_recompute_no_accept(mod):
    d = mod.decide(["backend/modules/alpha/service.py"], mod.load_rules(), PAGES)
    return not _judge(mod, _record(), d, expected=None)[0]


# ── (a)(b)(c)：正題 ──────────────────────────────────────────────────────────

def test_bottom_layer_change_rejects_a_scoped_result():
    assert case_a_bottom_change_rejected(SG)


@pytest.mark.parametrize("f", REQUIRED_BOTTOM)
def test_required_paths_are_bottom(f):
    c = SG.classify_path(f, _rules(), PAGES)
    assert c["layer"] == "bottom", (f, c)
    d = SG.decide(["backend/modules/alpha/service.py", f], _rules(), PAGES)
    assert d["mode"] == "full" and [f, c["why"]] in d["bottom"]
    assert not _judge(SG, _record(), d)[0]


def test_module_only_change_accepts_a_scoped_result():
    assert case_b_module_only_accepted(SG)


@pytest.mark.parametrize("f", SCOPED_OK)
def test_scoped_ok_paths_are_not_bottom(f):
    assert SG.classify_path(f, _rules(), PAGES)["layer"] != "bottom", f


def test_two_modules_and_their_pages_are_scoped_with_both_units():
    d = SG.decide(["backend/modules/alpha/a.py", PG + "beta.html"], _rules(), PAGES)
    assert d["mode"] == "scoped" and d["modules"] == ["alpha", "beta"]
    assert not _judge(SG, _record(units=["alpha"]), d)[0]         # 紀錄只驗了 alpha ⇒ 不接受
    assert _judge(SG, _record(units=["beta", "alpha"]), d)[0]


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
    ({"format": 99}, "不是範圍驗證"), ({"config_sha256": None}, "底層清單"), ({"tests": []}, "題目清單"),
    ({"tests": None}, "題目清單"), ({"main": {"exit": 0, "passed": None}}, "非 e2e"), ({"main": {"exit": 1, "passed": 9}}, "非 e2e"),
    ({"main": None}, "非 e2e"), ({"e2e": {"exit": 2}}, "e2e 段"), ({"e2e": None}, "e2e 段"),
])
def test_scoped_result_rejected_when_any_field_disagrees(bad, word):
    d = SG.decide(["backend/modules/alpha/service.py"], _rules(), PAGES)
    ok, detail = _judge(SG, _record(**bad), d)
    assert not ok and word in detail, (bad, detail)


def test_no_record_is_rejected():
    d = SG.decide(["backend/modules/alpha/service.py"], _rules(), PAGES)
    assert _judge(SG, None, d) == (False, "這個 commit 沒有範圍驗證紀錄（scope_gate.py run）")


def test_unknown_paths_fall_back_to_bottom():
    assert case_unknown_path_is_bottom(SG)


# ── M1：全域釘子 ─────────────────────────────────────────────────────────────

def test_m1_global_nails_ride_along_with_every_module_or_page_change():
    assert case_m1_global_tests_ride_along(SG)


def test_m1_global_nails_are_selected_for_a_real_module_file():
    """稽核的實證題：只改 arap 的出納 API ⇒ 選題（含規則附帶）必須含那 6 檔。"""
    d = SG.decide(["backend/modules/arap/api/cashier.py"], _rules(), {})
    picked = set(SG.select_tests(["backend/modules/arap/api/cashier.py"], [], d["extra_tests"])[0])
    missing = [n for n in GLOBAL_SIX if not any(n in t for t in picked)]
    assert missing == [], missing


def test_m1_every_tree_scanning_test_is_listed():
    """掃描：不靠 import、掃整個母體的測試（global_test_candidates）都必須在 global_tests；清單裡的檔都要存在。"""
    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    listed = set(raw["global_tests"])
    found = SG.global_test_candidates()
    assert all(any(n in f for f in found) for n in GLOBAL_SIX), "正對照：稽核點名的 6 檔要被掃描器認出"
    unlisted = sorted(set(found) - listed)
    assert unlisted == [], "這些測試掃整個母體，要加進 bottom_layer.json 的 global_tests：%s" % unlisted
    gone = sorted(t for t in listed if not (REPO / t).is_file())
    assert gone == [], "global_tests 裡的檔不存在（改名／刪除）：%s" % gone


def test_m1_scanner_positive_and_negative_controls(tmp_path):
    t = tmp_path / "backend" / "tests"
    t.mkdir(parents=True)
    (tmp_path / "backend" / "modules" / "zeta" / "tests").mkdir(parents=True)
    (t / "test_scan_db.py").write_text("def test_x(c):\n    c.execute(\"SELECT name FROM sqlite_master\")\n", encoding="utf-8")
    (t / "test_scan_manifest.py").write_text(
        "def test_y(root):\n    for p in root.glob('*/module.json'):\n        pass\n", encoding="utf-8")
    (t / "test_scan_pages.py").write_text("import glob\nF = glob.glob('frontend/pages/*.html')\nG = glob.glob(\"pages\")\n",
                                          encoding="utf-8")
    (t / "test_scan_perm.py").write_text("from helpers.module_registry import MODULES\n", encoding="utf-8")
    (tmp_path / "backend" / "modules" / "zeta" / "tests" / "test_z.py").write_text("Q = 'sqlite_master'\n", encoding="utf-8")
    (t / "test_plain.py").write_text("# sqlite_master 只出現在註解\nimport os\n", encoding="utf-8")
    (t / "platform").mkdir()
    (t / "platform" / "test_contract.py").write_text("Q = 'sqlite_master'\n", encoding="utf-8")
    found = SG.global_test_candidates(tmp_path)
    assert set(found) == {"backend/tests/test_scan_db.py", "backend/tests/test_scan_manifest.py",
                          "backend/tests/test_scan_pages.py", "backend/tests/test_scan_perm.py",
                          "backend/modules/zeta/tests/test_z.py"}, found


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
    """底層清單只在 bottom_layer.json：scope_gate.py 不另寫路徑前綴。"""
    src = SG_PATH.read_text(encoding="utf-8")
    for lit in ('"backend/core', '"backend/helpers', '"frontend/static', '"backend/tools/'):
        assert lit not in src, lit
    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
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


def test_m2_positive_controls():
    for case in (case_m2_config_hash_must_match, case_m2_record_must_cover_recomputed_tests,
                 case_m2_main_stage_must_have_passed_tests, case_m2_e2e_exit_checked, case_m2_no_recompute_no_accept):
        assert case(SG), case.__name__


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
    ("M1 不展開 @global_tests", case_m1_global_tests_ride_along,
     'tests += list(glob_tests) if t == "@global_tests" else [t]', 'tests += [] if t == "@global_tests" else [t]'),
    ("M2 不比對規則雜湊", case_m2_config_hash_must_match,
     '    if not config_sha or record.get("config_sha256") != config_sha:\n', '    if False:\n'),
    ("M2 不要求題目 ⊇ 重算", case_m2_record_must_cover_recomputed_tests,
     '    if missing:\n', '    if False:\n'),
    ("M2 不看非 e2e 段的通過數", case_m2_main_stage_must_have_passed_tests,
     ' or not isinstance(main.get("passed"), int) or main["passed"] <= 0:', ':'),
    ("M2 不看 e2e 段 exit", case_m2_e2e_exit_checked,
     '    if e2e.get("exit") not in (0, 5):\n', '    if False:\n'),
    ("M2 沒重算也接受", case_m2_no_recompute_no_accept,
     '    if expected_tests is None:\n        return False', '    if expected_tests is None:\n        expected_tests = []\n    if False:\n        return False'),
]


@pytest.mark.parametrize("name, case, old, new", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_reverse_control_each_mutation_turns_its_case_red(name, case, old, new):
    assert case(SG), "正對照：真實模組要綠"
    assert not case(_mutant(old, new)), "突變後仍綠 ⇒ 這一題守不住：%s" % name


def test_reverse_control_removing_a_bottom_rule_turns_required_paths_red(tmp_path):
    """清單突變：拿掉 backend/helpers/** ⇒ helpers 的檔掉到 fallback（仍是底層：fail closed 兜住）；
    再把 fallback 改成 doc ⇒ 不再是底層。證明「必要路徑」題真的依賴清單＋fallback。"""
    raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    raw["rules"] = [r for r in raw["rules"] if r["pattern"] != "backend/helpers/**"]
    p = tmp_path / "bottom_layer.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert SG.classify_path("backend/helpers/auth.py", SG.load_rules(p), PAGES)["layer"] == "bottom"
    m = _mutant('return {"layer": "bottom", "key": None, "why": "沒有任何規則符合',
                'return {"layer": "doc", "key": None, "why": "沒有任何規則符合')
    assert m.classify_path("backend/helpers/auth.py", m.load_rules(p), PAGES)["layer"] != "bottom"


# ── 整合：暫存 git repo 上真的算 P→X（M3／M4）──────────────────────────────────

def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "core.autocrlf=false", *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def _w(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(r, msg):
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", msg)
    return _g(r, "rev-parse", "HEAD")


@pytest.fixture
def mini(tmp_path):
    """P（打 prod tag）→ X（只改模組，基準＝P）→ Y（改 L1）；W 另開分支：基準自己移到 X、只改模組（M4 的攻擊）。"""
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
    (r / "tools" / "platform").mkdir(parents=True)
    shutil.copyfile(CFG_PATH, r / SG.CONFIG_REL)
    p = _commit(r, "P")
    _g(r, "tag", "prod/" + p[:8], p)
    _w(r, SG.BASELINE_REL, 'BASELINE = "%s"\n' % p[:8])       # 部署後把基準往後移（bookkeeping，不算底層）
    _w(r, "backend/modules/alpha/service.py", "def f():\n    return 2\n")
    _w(r, PG + "alpha.html", "<html><body></body></html>\n")
    x = _commit(r, "X module only")
    _w(r, "backend/helpers/util.py", "X = 2\n")
    y = _commit(r, "Y touches L1")
    _g(r, "checkout", "-q", "-b", "attack", x)
    _w(r, SG.BASELINE_REL, 'BASELINE = "%s"\n' % x[:8])       # 候選 commit 自己把基準移到 X（沒有 prod tag）
    _w(r, "backend/modules/alpha/service.py", "def f():\n    return 3\n")
    w = _commit(r, "W moves baseline itself")
    _g(r, "checkout", "-q", x)
    return {"repo": r, "p": p, "x": x, "y": y, "w": w, "rdir": tmp_path / "scoped"}


def _put(m, commit, **kw):
    m["rdir"].mkdir(parents=True, exist_ok=True)
    _t, csha = SG.config_at(commit, m["repo"])
    rec = dict(_record(), commit=commit, base=m["p"], units=["alpha"], config_sha256=csha)
    rec.update(kw)
    (m["rdir"] / (commit + ".json")).write_text(json.dumps(rec), encoding="utf-8")


def _sel(files, consumers, extra):
    return list(T_OK)


def case_m3_gate_needs_head_x(mod, m):
    _g(m["repo"], "checkout", "-q", m["y"])
    try:
        return mod.gate(m["x"], repo=m["repo"], rdir=m["rdir"], selector=_sel)["accepted"] is False
    finally:
        _g(m["repo"], "checkout", "-q", m["x"])


def case_m3_gate_needs_clean_tools(mod, m):
    evil = m["repo"] / "tools" / "platform" / "evil.py"
    evil.write_text("# 未 commit 的判定程式\n", encoding="utf-8")
    try:
        return mod.gate(m["x"], repo=m["repo"], rdir=m["rdir"], selector=_sel)["accepted"] is False
    finally:
        evil.unlink()


def case_m3_rules_come_from_x(mod, m):
    """工作樹的清單被改成「helpers 是文件」（未 commit）⇒ Y 仍然要全量（規則讀 X 上的版本）。"""
    cfg = m["repo"] / SG.CONFIG_REL
    orig = cfg.read_text(encoding="utf-8")
    raw = json.loads(orig)
    raw["rules"] = [{"pattern": "backend/helpers/**", "layer": "doc", "why": "偷改"}] + raw["rules"]
    cfg.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    try:
        return mod.assess(m["y"], repo=m["repo"])["decision"]["mode"] == "full"
    finally:
        cfg.write_text(orig, encoding="utf-8")


def case_m4_candidate_cannot_move_the_baseline(mod, m):
    a = mod.assess(m["w"], repo=m["repo"])
    return a["decision"]["mode"] == "full" and a["trusted"] == m["p"] and a["base"] == m["x"]


def test_integration_module_only_commit_is_scoped_and_accepted(mini):
    a = SG.assess(mini["x"], repo=mini["repo"])
    assert a["base"] == mini["p"] == a["trusted"] and a["decision"]["mode"] == "scoped", a["decision"]
    assert a["decision"]["modules"] == ["alpha"]
    assert any("test_system_audit" in t for t in a["decision"]["extra_tests"])        # M1：全域釘子跟著走
    assert SG.gate(mini["x"], repo=mini["repo"], rdir=mini["rdir"], selector=_sel)["accepted"] is False  # 還沒有紀錄
    _put(mini, mini["x"])
    g = SG.gate(mini["x"], repo=mini["repo"], rdir=mini["rdir"], selector=_sel)
    assert g["accepted"] is True and g["mode"] == "scoped" and g["base"] == mini["p"] and len(g["base"]) == 40, g
    # 沒有 selector、repo 不是本工具的 repo ⇒ 沒重算 ⇒ 不接受
    assert SG.gate(mini["x"], repo=mini["repo"], rdir=mini["rdir"])["accepted"] is False


def test_integration_l1_commit_needs_full_even_with_a_green_scoped_record(mini):
    _g(mini["repo"], "checkout", "-q", mini["y"])
    _put(mini, mini["y"])
    g = SG.gate(mini["y"], repo=mini["repo"], rdir=mini["rdir"], selector=_sel)
    assert g["accepted"] is False and "backend/helpers/util.py" in g["detail"], g


def test_integration_record_of_x_does_not_cover_y(mini):
    _put(mini, mini["x"])
    _g(mini["repo"], "checkout", "-q", mini["y"])
    rec = json.loads((mini["rdir"] / (mini["x"] + ".json")).read_text(encoding="utf-8"))
    (mini["rdir"] / (mini["y"] + ".json")).write_text(json.dumps(rec), encoding="utf-8")   # 抄到 Y 的檔名
    assert SG.gate(mini["y"], repo=mini["repo"], rdir=mini["rdir"], selector=_sel)["accepted"] is False


def test_integration_unreadable_baseline_means_full(mini):
    _w(mini["repo"], SG.BASELINE_REL, "BASELINE = None\n")
    z = _commit(mini["repo"], "broken baseline")
    a = SG.assess(z, repo=mini["repo"])
    assert a["decision"]["mode"] == "full" and a["base"] is None


def test_m4_no_prod_tag_means_full(mini):
    _g(mini["repo"], "tag", "-d", "prod/" + mini["p"][:8])
    a = SG.assess(mini["x"], repo=mini["repo"])
    assert a["trusted"] is None and a["decision"]["mode"] == "full" and "prod/" in a["decision"]["bottom"][0][1]


def test_m4_newest_prod_tag_wins(mini):
    """正式機換成 X（打了 prod/<x>）而候選 commit 的基準還寫 P ⇒ 不符 ⇒ 全量（基準要等於**目前**正式機）。"""
    _g(mini["repo"], "tag", "prod/" + mini["x"][:8], mini["x"])
    a = SG.assess(mini["x"], repo=mini["repo"])
    assert a["trusted"] == mini["x"] and a["decision"]["mode"] == "full"


M3M4 = [
    ("M3 不要求 HEAD＝X", case_m3_gate_needs_head_x,
     '    if rev("HEAD", repo) != commit:\n', '    if False:\n'),
    ("M3 不要求工具路徑乾淨", case_m3_gate_needs_clean_tools,
     '    if dirty:\n', '    if False:\n'),
    ("M3 規則改讀工作樹", case_m3_rules_come_from_x,
     '    text, csha = config_at(commit, repo)\n',
     '    text, csha = (Path(repo) / CONFIG_REL).read_text(encoding="utf-8"), "x"\n'),
    ("M4 不比對受信 tag", case_m4_candidate_cannot_move_the_baseline,
     '    if base != trusted:\n', '    if False:\n'),
]


@pytest.mark.parametrize("name, case, old, new", M3M4, ids=[m[0] for m in M3M4])
def test_reverse_control_m3_m4(mini, name, case, old, new):
    _put(mini, mini["x"])
    assert case(SG, mini), "正對照：真實模組要綠"
    assert not case(_mutant(old, new), mini), "突變後仍綠 ⇒ 這一題守不住：%s" % name


# ── 建包腳本：判定段（PowerShell 實跑，假 scope_gate；稽核 W4 S1）──────────────────────

_FAKES = {
    "ok": ("import json,sys\nprint(json.dumps({'accepted': True, 'mode': 'scoped', 'commit': sys.argv[3], "
           "'base': 'a'*40, 'record_present': True, 'detail': 'ok'}))\n"),
    "exit3": ("import json,sys\nprint(json.dumps({'accepted': True, 'mode': 'scoped', 'commit': sys.argv[3], "
              "'base': 'a'*40, 'record_present': True, 'detail': 'x'}))\nsys.exit(3)\n"),
    "garbage": "import sys\nsys.stdout.buffer.write(b'\\xff\\xfe{not json \\x81')\n",
    "raises": "raise RuntimeError('boom')\n",
    "other_commit": ("import json,sys\nprint(json.dumps({'accepted': True, 'mode': 'scoped', 'commit': 'd'*40, "
                     "'base': 'a'*40, 'record_present': True, 'detail': 'ok'}))\n"),
    "short_base": ("import json,sys\nprint(json.dumps({'accepted': True, 'mode': 'scoped', 'commit': sys.argv[3], "
                   "'base': 'abc1234', 'record_present': True, 'detail': 'ok'}))\n"),
    "not_scoped_mode": ("import json,sys\nprint(json.dumps({'accepted': True, 'mode': 'full', 'commit': sys.argv[3], "
                        "'base': 'a'*40, 'record_present': True, 'detail': 'ok'}))\n"),
    "rejected": ("import json,sys\nprint(json.dumps({'accepted': False, 'mode': None, 'commit': sys.argv[3], "
                 "'record_present': True, 'detail': 'bottom'}))\nsys.exit(3)\n"),
}


def _ps_cases(tmp_path, gate_ps1=PS_GATE):
    """一次 PowerShell 跑全部假 scope_gate ⇒ {名稱: "SCOPED"|"FULL"}。$ErrorActionPreference=Stop 同建包。"""
    lines = ["$ErrorActionPreference = 'Stop'", ". '%s'" % gate_ps1, "$r = @{}"]
    for name, src in _FAKES.items():
        f = tmp_path / ("fake_%s.py" % name)
        f.write_text(src, encoding="utf-8")
        lines.append("$x = Get-ScopedGateResult -PyExe '%s' -GateScript '%s' -Commit '%s'; "
                     "$r['%s'] = $(if ($x.Scoped) { 'SCOPED' } else { 'FULL' })" % (sys.executable, f, C, name))
    lines.append("$x = Get-ScopedGateResult -PyExe '%s' -GateScript 'x.py' -Commit '%s'; "
                 "$r['no_python'] = $(if ($x.Scoped) { 'SCOPED' } else { 'FULL' })" % (tmp_path / "nope.exe", C))
    lines.append("ConvertTo-Json -InputObject $r -Compress")
    script = tmp_path / "run.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8"))
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_build_gate_segment_falls_back_to_full_on_anything_odd(tmp_path):
    r = _ps_cases(tmp_path)
    assert r.pop("ok") == "SCOPED", "正對照：正常的接受要放行"
    assert r == {k: "FULL" for k in r}, r


PS_MUTATIONS = [
    ("不看 exit code", "exit3", "    if ($code -ne 0 -or $sg.accepted -ne $true) {", "    if ($sg.accepted -ne $true) {"),
    ("不比對 commit", "other_commit", "    if ($sg.commit -ne $Commit) {", "    if ($false) {"),
    ("不要求完整基準 SHA", "short_base", "    if (-not (\"$($sg.base)\" -match '^[0-9a-f]{40}$')) {", "    if ($false) {"),
    ("不看 mode", "not_scoped_mode", '    if ($sg.mode -ne "scoped") {', "    if ($false) {"),
]


@pytest.mark.parametrize("name, case, old, new", PS_MUTATIONS, ids=[m[0] for m in PS_MUTATIONS])
def test_reverse_control_build_gate_segment(tmp_path, name, case, old, new):
    src = PS_GATE.read_text(encoding="utf-8-sig")
    assert src.count(old) == 1, "突變原句在 _scope_gate.ps1 出現 %d 次" % src.count(old)
    mut = tmp_path / "_scope_gate_mut.ps1"
    mut.write_bytes(b"\xef\xbb\xbf" + src.replace(old, new, 1).encode("utf-8"))
    assert _ps_cases(tmp_path, mut)[case] == "SCOPED", "突變後仍落全量 ⇒ 這一題守不住：%s" % name


def test_build_script_uses_scope_gate_and_records_the_mode():
    s = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    assert '_scope_gate.ps1")' in s and "Get-ScopedGateResult -PyExe $pyExe" in s and "-Commit $commit" in s
    assert "if (-not $reuse -and -not $ForceTests)" in s                     # -ForceTests ⇒ 一律全量
    i_scoped, i_full = s.index("} elseif ($scoped) {"), s.index('Write-Host "`n[測試] 執行 pytest（非 e2e')
    assert i_scoped < i_full                                                   # 全量分支仍在，排在 else
    assert 'mode         = "scoped"' in s and "base         = $scoped.base" in s
    assert "verification         = $Verification" in s
