"""verify_package 的正對照改用自造誘餌（2026-09-25）：不依賴工作樹裡剛好有的 V9 開發產物。

☠️ 舊版去工作樹找真實的開發庫／私鑰／log ⇒ 乾淨的 worktree 一律「正對照作廢」而 FAIL。
"""
import importlib.util
import os
from pathlib import Path

_VP_PATH = Path(__file__).resolve().parent.parent / "tools" / "verify_package.py"


def _vp():
    spec = importlib.util.spec_from_file_location("_verify_package_decoy", _VP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_decoy_passes_with_the_real_rules():
    vp = _vp()
    assert vp.positive_control_decoy() is True
    assert not vp.R.voided


def test_decoy_is_removed_afterwards(monkeypatch):
    vp = _vp()
    made = []
    real = vp.build_decoy
    monkeypatch.setattr(vp, "build_decoy", lambda: made.append(real()) or made[-1])
    vp.positive_control_decoy()
    assert made and not os.path.exists(made[0])


def test_rc_a_broken_rule_voids_the_report(monkeypatch):
    """比對規則壞掉（抓不到 .db）⇒ 誘餌沒被抓 ⇒ 報告作廢。"""
    vp = _vp()
    broken = [(k, d, (lambda r, n: False) if k == "db-sqlite" else f) for k, d, f in vp.BAD]
    monkeypatch.setattr(vp, "BAD", broken)
    assert vp.positive_control_decoy() is False
    assert vp.R.voided


def test_rc_a_too_wide_rule_voids_the_report(monkeypatch):
    """規則太寬（什麼都抓）⇒ 無害檔也被抓 ⇒ 報告作廢。"""
    vp = _vp()
    wide = [(k, d, (lambda r, n: True) if k == "private_key" else f) for k, d, f in vp.BAD]
    monkeypatch.setattr(vp, "BAD", wide)
    assert vp.positive_control_decoy() is False
    assert vp.R.voided
