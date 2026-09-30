"""底層慣例發現（GL-BASE-HOOKS A5，2026-10-01）：新增模組檔／全域釘子不必再回來改清單。
① `dep_scan.load_groups(units=…)`：`backend/modules/<key>/` 底下沒列在任何群組的 `mod:` 單位 ⇒ 預設歸屬 key＝資料夾名的模組（列了的照列）。
② `scope_gate.load_rules()`：掃描器認出的全域釘子自動算進規則的 tests（指定 path 時不加，手列的保留、去重）。
（`modules/*/notify.py` 自動入掃描的題在 test_wording_guards_2026_09_23.py。）"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan as D  # noqa: E402

_spec = importlib.util.spec_from_file_location("_scope_gate_conv", REPO / "tools" / "platform" / "scope_gate.py")
SG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SG)


def _modules_json(tmp_path):
    p = tmp_path / "modules.json"
    p.write_text(json.dumps({"L1": {"units": ["helper:a"]},
                             "modules": {"M1": {"key": "alpha", "units": ["mod:alpha/listed"]},
                                         "M2": {"key": "beta", "units": ["mod:beta/listed"]}}}), encoding="utf-8")
    return p


def test_unlisted_module_unit_defaults_to_its_folders_module(tmp_path):
    p = _modules_json(tmp_path)
    units = {"mod:alpha/listed": {"kind": "mod", "module_key": "alpha"},
             "mod:alpha/new_file": {"kind": "mod", "module_key": "alpha"},
             "mod:beta/new_file": {"kind": "mod", "module_key": "beta"},
             "mod:gamma/new_file": {"kind": "mod", "module_key": "gamma"},          # modules.json 沒有這個 key ⇒ 仍然沒人認領（資料夾檢查會報）
             "helper:unlisted": {"kind": "helper"}}                                # 非 mod 單位不套用預設
    u2g, _, _ = D.load_groups(p, units)
    assert u2g["mod:alpha/listed"] == ["M1"]                                       # 列了的照列
    assert u2g["mod:alpha/new_file"] == ["M1"] and u2g["mod:beta/new_file"] == ["M2"]
    assert not u2g.get("mod:gamma/new_file") and not u2g.get("helper:unlisted")
    u2g0, _, _ = D.load_groups(p)                                                   # 反向控制：不給 units ⇒ 與過去完全相同（沒有預設歸屬）
    assert not u2g0.get("mod:alpha/new_file")


def test_listed_elsewhere_is_never_overridden(tmp_path):
    p = _modules_json(tmp_path)
    m = json.loads(p.read_text(encoding="utf-8"))
    m["L1"]["units"].append("mod:alpha/moved_to_l1")
    p.write_text(json.dumps(m), encoding="utf-8")
    u2g, _, _ = D.load_groups(p, {"mod:alpha/moved_to_l1": {"kind": "mod", "module_key": "alpha"}})
    assert u2g["mod:alpha/moved_to_l1"] == ["L1"]                                   # 明列優先，不會變成重複歸屬


def test_real_tree_has_no_ownership_errors_with_default_owner():
    g = D.build()
    errors, _ = D.check_modules(g)
    assert errors == [], errors


def test_scanner_found_global_tests_are_rolled_into_rules(monkeypatch):
    monkeypatch.setattr(SG, "global_test_candidates", lambda *a, **k: {"backend/tests/test_zz_probe_global.py": ["sqlite_master"]})
    rules = SG.load_rules()
    mod_rule = [r for r in rules if r["layer"] == "module"][0]
    assert "backend/tests/test_zz_probe_global.py" in mod_rule["tests"]
    assert len(mod_rule["tests"]) == len(set(mod_rule["tests"]))                     # 去重
    explicit = SG.load_rules(path=REPO / "tools" / "platform" / "bottom_layer.json")   # 指定 path ⇒ 不加（反向控制）
    assert "backend/tests/test_zz_probe_global.py" not in [t for r in explicit for t in r["tests"]]
