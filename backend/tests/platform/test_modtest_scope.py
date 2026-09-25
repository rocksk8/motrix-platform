"""modtest 選題範圍（PLAYBOOK §C-11a；RUN-PLAN D1b）：介面沒變只到直接依賴、介面有變才遞移；統計落點。合成相依圖。"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
_spec = importlib.util.spec_from_file_location("_modtest_scope", REPO / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MT)

# helper:a ← helper:b ← router:c（遞移兩跳）；core:main 也 import a（彙整點，不可以因此擴散）
GRAPH = {
    "helper:a": {"kind": "helper", "imports": []},
    "helper:b": {"kind": "helper", "imports": ["helper:a"]},
    "router:c": {"kind": "router", "imports": ["helper:b"]},
    "core:main": {"kind": "core", "imports": ["helper:a", "helper:b", "router:c"]},
}
TMAP = {"tests": {
    "backend/tests/test_a.py": {"kind": "unit", "units": ["helper:a"]},
    "backend/tests/test_b.py": {"kind": "unit", "units": ["helper:b"]},
    "backend/tests/test_c.py": {"kind": "api", "units": ["router:c"]},
}}
F = "backend/helpers/a.py"


def _picked(iface):
    picked, rep = MT.select([F], TMAP, GRAPH, iface)
    return {p for p in picked if p.startswith("backend/tests/test_")}, rep


def test_interface_unchanged_stops_at_direct_dependents():
    got, rep = _picked(lambda rel: False)
    assert got == {"backend/tests/test_a.py", "backend/tests/test_b.py"}
    assert rep["iface"]["helper:a"].startswith("介面不變")


def test_rc_interface_changed_spreads_transitively():
    """反向控制：簽名變了 ⇒ 間接使用者（router:c）也要跑。"""
    got, rep = _picked(lambda rel: True)
    assert "backend/tests/test_c.py" in got and rep["iface"]["helper:a"].startswith("介面有變")


def test_legacy_rule_without_checker_is_transitive():
    got, rep = _picked(None)
    assert "backend/tests/test_c.py" in got and rep["rule"] == "transitive"


def test_aggregator_is_not_a_direct_dependent():
    """core:main import 了 a，但它是彙整點：不可以因此把 fixture 隱含的全部 api／e2e 拖進來。"""
    assert "core:main" not in MT.direct_dependents({"helper:a"}, GRAPH)


def test_interface_changed_on_real_files(monkeypatch):
    rel = "backend/core/source_tree.py"
    assert MT.interface_changed(rel, "HEAD", None) is (
        MT._interface_tools().interface_of(MT._show(MT.REPO, "HEAD", rel)) !=
        MT._interface_tools().interface_of((MT.REPO / rel).read_text(encoding="utf-8-sig")))
    assert MT.interface_changed("frontend/static/sidebar.js", "HEAD") is True      # 非 .py ⇒ 保守
    assert MT.interface_changed("backend/nope_not_exist.py", "HEAD") is True       # 讀不到 ⇒ 保守


def test_rc_signature_change_is_detected(monkeypatch):
    old = "def f(a):\n    return a\n"
    monkeypatch.setattr(MT, "_show", lambda repo, ref, rel: old if ref == "OLD" else "def f(a, b):\n    return a\n")
    assert MT.interface_changed("backend/x.py", "OLD", "NEW") is True
    monkeypatch.setattr(MT, "_show", lambda repo, ref, rel: old if ref == "OLD" else "def f(a):\n    return a + 1\n")
    assert MT.interface_changed("backend/x.py", "OLD", "NEW") is False, "只改函式內部 ⇒ 介面不變"


def test_stats_row_is_appended(tmp_path):
    _, rep = _picked(lambda rel: False)
    MT.record_stats([F], ["t1", "t2"], TMAP, rep, 10, 100, 1.23, dry_run=True, root=tmp_path)
    MT.record_stats([F], ["t1"], TMAP, rep, None, None, 2.0, dry_run=False, exit_code=0, root=tmp_path)
    rows = [json.loads(l) for l in tmp_path.joinpath(*MT.STATS_REL).read_text(encoding="utf-8").splitlines()]
    assert [r["items_ratio"] for r in rows] == [0.1, None] and rows[0]["rule"] == "direct+iface"
    assert rows[1]["exit"] == 0 and rows[1]["files"] == 1


# ── §C-11a ③ 名稱層級（整合）──────────────────────────────────────────────

NG = {
    "helper:a": {"kind": "helper", "imports": [], "path": "backend/helpers/a.py"},
    "router:u1": {"kind": "router", "imports": ["helper:a"], "path": "backend/routers/u1.py"},
    "router:u2": {"kind": "router", "imports": ["helper:a"], "path": "backend/routers/u2.py"},
}
NT = {"tests": {
    "backend/tests/test_u1.py": {"kind": "api", "units": ["router:u1"]},
    "backend/tests/test_u2.py": {"kind": "api", "units": ["router:u2"]},
    "backend/tests/test_own_f.py": {"kind": "unit", "units": ["helper:a"]},
    "backend/tests/test_own_g.py": {"kind": "unit", "units": ["helper:a"]},
}}
A_OLD = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
A_NEW = "def f():\n    return 10\n\n\ndef g():\n    return 2\n"


def _name_select(monkeypatch, conftest="import os\n"):
    srcs = {
        ("backend/helpers/a.py", "OLD"): A_OLD, ("backend/helpers/a.py", None): A_NEW,
        ("backend/routers/u1.py", None): "from helpers.a import f\n",
        ("backend/routers/u2.py", None): "from helpers.a import g\n",
        ("backend/tests/test_own_f.py", None): "from helpers.a import f\n",
        ("backend/tests/test_own_g.py", None): "from helpers import a\n\ndef test():\n    assert a.g() == 2\n",
        ("backend/conftest.py", None): conftest,
    }
    monkeypatch.setattr(MT, "_source", lambda rel, ref: srcs.get((rel, ref)))
    chk = lambda rel: False     # noqa: E731
    chk.refs = ("OLD", None)
    picked, rep = MT.select(["backend/helpers/a.py"], NT, NG, chk)
    return {p for p in picked if p.startswith("backend/tests/test_")}, rep


def test_name_level_keeps_only_users_of_the_changed_name(monkeypatch):
    got, rep = _name_select(monkeypatch)
    assert got == {"backend/tests/test_u1.py", "backend/tests/test_own_f.py"}
    assert rep["names"]["helper:a"] == ["f"]


def test_rc_conftest_using_the_changed_name_disables_test_filtering(monkeypatch):
    """反向控制：fixture 經 conftest 用到被改的名稱 ⇒ 所有直接 import 它的測試都要跑（不可以只看測試檔自己）。"""
    got, rep = _name_select(monkeypatch, conftest="from helpers.a import f\n")
    assert "backend/tests/test_own_g.py" in got and "helper:a" in rep.get("names_conftest", {})


# ── 稽核 D S-M1／S-S2／O-2 ─────────────────────────────────────────────────

P_OLD = "def _x():\n    return 1\n\n\ndef b():\n    return _x()\n\n\ndef g():\n    return 2\n"
P_NEW = P_OLD.replace("return 1", "return 99")


def _private_select(monkeypatch, u1_src="from helpers.a import b\n", u2_src="from helpers.a import g\n"):
    srcs = {
        ("backend/helpers/a.py", "OLD"): P_OLD, ("backend/helpers/a.py", None): P_NEW,
        ("backend/routers/u1.py", None): u1_src, ("backend/routers/u2.py", None): u2_src,
        ("backend/tests/test_own_f.py", None): "from helpers.a import b\n",
        ("backend/tests/test_own_g.py", None): "from helpers.a import g\n",
        ("backend/conftest.py", None): "import os\n",
    }
    monkeypatch.setattr(MT, "_source", lambda rel, ref: srcs.get((rel, ref)))
    chk = lambda rel: False     # noqa: E731
    chk.refs = ("OLD", None)
    picked, rep = MT.select(["backend/helpers/a.py"], NT, NG, chk)
    return {p for p in picked if p.startswith("backend/tests/test_")}, rep


def test_rc_private_change_reaches_users_of_its_public_caller(monkeypatch):
    """S-M1：改私有 _x；u1 與 test_own_f 只 import b，而 b 呼叫 _x ⇒ 都要選到。只用 g 的不選。"""
    got, rep = _private_select(monkeypatch)
    assert {"backend/tests/test_u1.py", "backend/tests/test_own_f.py"} <= got
    assert "backend/tests/test_u2.py" not in got and "backend/tests/test_own_g.py" not in got
    assert rep["names_direct"]["helper:a"] == ["_x"] and rep["names"]["helper:a"] == ["_x", "b"]


def test_rc_user_passing_the_module_around_is_kept(monkeypatch):
    """S-S2：使用者把模組物件整個傳出去（ALL）⇒ 判斷不了 ⇒ 保留。"""
    got, _ = _private_select(monkeypatch, u2_src="from helpers import a\n\ndef f(k):\n    return k(a)\n")
    assert "backend/tests/test_u2.py" in got


def test_rc_user_with_unrecognised_import_is_kept(monkeypatch):
    """S-S2：dep_scan 認得它依賴 a，但 AST 找不到 import 方式（例：importlib）⇒ used 是空集合 ⇒ 保留。"""
    got, _ = _private_select(monkeypatch, u2_src="import importlib\nm = importlib.import_module('helpers.a')\n")
    assert "backend/tests/test_u2.py" in got


def test_real_helper_private_change_selects_its_tests(monkeypatch):
    """S-M1 的真實情境（D 的突變）：只改 legal_params._as_date ⇒ test_legal_params_r1 必須被選到
    （D 實測：同一個突變下它有 6 題紅，而閉包前的名稱層級把它拿掉了）。"""
    rel = "backend/helpers/legal_params.py"
    cur = (MT.REPO / rel).read_text(encoding="utf-8-sig")
    old = cur.replace("    return date.fromisoformat(s)", "    return date.fromisoformat(s).replace(year=2026)")
    assert old != cur, "legal_params._as_date 的寫法變了，更新這一題的突變"
    real_source = MT._source
    monkeypatch.setattr(MT, "_source", lambda r, ref: old if (r == rel and ref == "OLD") else real_source(r, ref))
    chk = lambda r: False     # noqa: E731
    chk.refs = ("OLD", None)
    picked, rep = MT.select([rel], MT.load_map(False), MT.load_graph(), chk)
    assert "backend/tests/test_legal_params_r1_2026_09_25.py" in picked
    assert rep["names_direct"]["helper:legal_params"] == ["_as_date"]


def test_rc_cross_boundary_private_signature_change_is_an_interface_change(monkeypatch):
    """O-2：_require_user 這類跨模組在用的底線名稱改簽名 ⇒ 介面有變（與 G1 守門同一個範圍）。"""
    monkeypatch.setattr(MT, "_show", lambda repo, ref, rel: "def _require_user(a):\n    return a\n" if ref == "OLD"
                        else "def _require_user(a, b):\n    return a\n")
    monkeypatch.setattr(MT, "_cross_boundary", lambda: {"helper:auth": {"_require_user"}})
    assert MT.interface_changed("backend/helpers/auth.py", "OLD", "NEW") is True
    monkeypatch.setattr(MT, "_cross_boundary", lambda: {})
    assert MT.interface_changed("backend/helpers/auth.py", "OLD", "NEW") is False, "反向控制：不帶 extra 就看不到"


# ── 稽核 D S-S1：tools/platform/scope_rc.py（真突變反向控制，發版前／每批合回後跑）────────────

def _rc():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("_scope_rc", REPO / "tools" / "platform" / "scope_rc.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_reverse_control_anchor_is_current():
    """清單裡每個突變的原句在目前的程式碼恰好出現一次（有人改了那段就提醒更新清單，不讓檢查安靜地失效）。"""
    for name, rel, old, new, expect, why in _rc().MUTATIONS:
        assert (REPO / rel).read_text(encoding="utf-8").count(old) == 1, name
        assert (REPO / expect).is_file(), name


def test_rc_stale_anchor_is_a_failure_not_a_skip():
    r = _rc().run_one("x", "backend/helpers/legal_params.py", "THIS LINE DOES NOT EXIST", "", "backend/tests/x.py", "")
    assert r["ok"] is False and "清單過期" in r["why"]
