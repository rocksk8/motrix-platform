"""modtest --full 的結果檔（2026-09-26）：依 commit 分檔，儀表板閘門讀「這個 commit 的那一份」。"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
_spec = importlib.util.spec_from_file_location("_modtest_fr", REPO / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MT)

A, B = "a" * 40, "b" * 40


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_clean_run_writes_per_commit_and_latest(tmp_path):
    dest = MT.write_last_full({"commit": A, "dirty": False, "ok": True}, root=tmp_path)
    base = tmp_path / "tools" / "platform"
    assert dest == base / "full_results" / (A + ".json")
    assert _read(dest)["ok"] is True
    assert _read(base / ".last_full.json")["commit"] == A


def test_another_commit_does_not_overwrite(tmp_path):
    """主持回報的情況：別的 worktree（別的 commit）跑出 ok=False，不可以蓋掉這個 commit 的綠燈。"""
    MT.write_last_full({"commit": A, "dirty": False, "ok": True}, root=tmp_path)
    MT.write_last_full({"commit": B, "dirty": False, "ok": False}, root=tmp_path)
    fr = tmp_path / "tools" / "platform" / "full_results"
    assert _read(fr / (A + ".json"))["ok"] is True
    assert _read(fr / (B + ".json"))["ok"] is False


def test_rc_dirty_run_does_not_touch_the_per_commit_record(tmp_path):
    """反向控制：dirty 的全量不代表這個 commit ⇒ 不寫 per-commit 檔（否則會蓋掉同 commit 乾淨的綠燈）；只更新 .last_full.json。"""
    MT.write_last_full({"commit": A, "dirty": False, "ok": True}, root=tmp_path)
    dest = MT.write_last_full({"commit": A, "dirty": True, "ok": False}, root=tmp_path)
    base = tmp_path / "tools" / "platform"
    assert dest == base / ".last_full.json"
    assert _read(base / "full_results" / (A + ".json"))["ok"] is True
    assert _read(base / ".last_full.json")["dirty"] is True


def test_rc_non_sha_commit_is_not_written_per_commit(tmp_path):
    for bad in ("", None, "HEAD", "../x", "a" * 39):
        MT.write_last_full({"commit": bad, "dirty": False, "ok": True}, root=tmp_path)
    fr = tmp_path / "tools" / "platform" / "full_results"
    assert not fr.exists() or list(fr.iterdir()) == []


def test_no_temp_files_left(tmp_path):
    MT.write_last_full({"commit": A, "dirty": False, "ok": True}, root=tmp_path)
    left = [p.name for p in (tmp_path / "tools" / "platform").rglob("*.tmp")]
    assert left == []
