"""dep_scan 的正對照：在合成樹上驗，不綁任何真實 L2 模組（MODULE-GUIDE 測試規則）。

拿掉任何一個 L2 模組，掃描器都不可以自判「不可信」而讓所有守門停擺。
"""
import inspect
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402


def test_synthetic_controls_pass():
    assert dep_scan.positive_controls() == []


def test_controls_do_not_name_any_real_l2_unit():
    """正對照的原始碼裡不可以出現真實 L2 單位的名稱（出現了＝又綁回特定模組）。"""
    m = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    l2_units = {u for g in m["modules"].values() for u in g["units"]}
    assert l2_units, "modules.json 讀不到任何 L2 單位——這題就什麼都沒驗"      # 正對照
    src = "".join(inspect.getsource(f) for f in (dep_scan.positive_controls, dep_scan._synthetic_checks))
    src += json.dumps(dep_scan.SYNTHETIC_MODULES) + json.dumps(dep_scan.SYNTHETIC_FILES)
    leaked = sorted(u for u in l2_units if u in src)
    assert leaked == []


def test_controls_catch_a_broken_scanner(monkeypatch):
    """反向控制：掃描器壞掉時正對照必須紅（否則「OK」不代表什麼）。"""
    monkeypatch.setattr(dep_scan, "helper_reexports", lambda: {})
    assert dep_scan.positive_controls()
