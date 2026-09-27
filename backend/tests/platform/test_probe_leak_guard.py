# -*- coding: utf-8 -*-
"""探針不可以留在受測樹（wip/b-probe-tmp，主持派工；D 觀察 inflight 探針殘留被別的 worker 收集成紅）。

conftest 的 pytest_probe_leak_sessionstart／pytest_probe_leak_sessionfinish（hook 名稱要 pytest_ 開頭，specname 才生效）：一輪結束時 tests/（含「.」開頭目錄）多出 test_*.py ⇒ 判紅。
這裡用子 pytest（探針在 tmp、經 probe_pytest_args 吃 backend/conftest.py）做反向控制與正對照；監看範圍以
MOTRIX_PROBE_LEAK_ROOTS 指到 tmp 裡的假 tests 目錄，不碰真的受測樹。
"""
from tests._subproc import BACKEND_DIR, probe_pytest_args, run_python

_LEAKS = """
import os
def test_writes_a_probe_into_the_watched_tree():
    d = os.path.join(os.environ["MOTRIX_PROBE_LEAK_ROOTS"], ".sub")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "test_zz_left_behind.py"), "w").write("x = 1\\n")
"""

_CLEAN = """
import os
def test_touches_nothing():
    assert os.path.isdir(os.environ["MOTRIX_PROBE_LEAK_ROOTS"])
"""


def _run(tmp_path, src):
    watched = tmp_path / "fake_tests"
    watched.mkdir()
    (watched / "test_existing.py").write_text("x = 1\n", encoding="utf-8")       # 一開始就在的不算
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    f = probe_dir / "test_probe.py"
    f.write_text(src, encoding="utf-8")
    return run_python(["-m", "pytest", *probe_pytest_args(f), "-q", "-p", "no:cacheprovider",
                       "--basetemp", str(tmp_path / "bt")],
                      cwd=BACKEND_DIR, MOTRIX_PROBE_LEAK_ROOTS=str(watched), timeout=240)


def test_a_probe_left_in_the_tree_turns_the_run_red(tmp_path):
    """反向控制：題目本身綠，但把 test_*.py 留在監看範圍（「.」開頭子目錄）⇒ 這一輪 exit 非 0，訊息列出那個檔。"""
    r = _run(tmp_path, _LEAKS)
    out = r.stdout + r.stderr
    assert "1 passed" in out, out[-1500:]
    assert r.returncode != 0, out[-1500:]
    assert "多出 1 個 test_*.py" in out and "test_zz_left_behind.py" in out, out[-1500:]


def test_a_clean_run_stays_green(tmp_path):
    """正對照：沒留下任何檔（監看範圍裡原本就有的 test_existing.py 不算）⇒ exit 0。"""
    r = _run(tmp_path, _CLEAN)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "多出" not in out, out[-1500:]


def test_default_watch_roots_are_tests_and_every_module_tests(monkeypatch):
    """稽核 D PT-S1：沒有覆寫時，監看範圍＝backend/tests ＋ 每一個 modules/<key>/tests（有的都要在）。
    改成空、或不含 modules ⇒ 紅。"""
    import conftest
    from pathlib import Path
    monkeypatch.delenv("MOTRIX_PROBE_LEAK_ROOTS", raising=False)
    roots = {Path(r).resolve() for r in conftest._probe_leak_roots()}
    backend = Path(BACKEND_DIR).resolve()
    assert backend / "tests" in roots, roots
    module_tests = {d.resolve() for d in (backend / "modules").glob("*/tests") if d.is_dir()}
    assert module_tests, "正對照：repo 裡至少要有一個 modules/<key>/tests"
    assert module_tests <= roots, "漏看的模組測試目錄：%s" % sorted(map(str, module_tests - roots))


def test_utf8_env_drops_the_leak_roots_override(monkeypatch):
    """稽核 D PT-S2：外層帶著 MOTRIX_PROBE_LEAK_ROOTS ⇒ utf8_env 給子行程的環境裡沒有它；題目明著傳入時照給（反向控制用）。"""
    from tests._subproc import utf8_env
    monkeypatch.setenv("MOTRIX_PROBE_LEAK_ROOTS", "C:/somewhere/else")
    assert "MOTRIX_PROBE_LEAK_ROOTS" not in utf8_env()
    assert utf8_env(MOTRIX_PROBE_LEAK_ROOTS="x")["MOTRIX_PROBE_LEAK_ROOTS"] == "x"

