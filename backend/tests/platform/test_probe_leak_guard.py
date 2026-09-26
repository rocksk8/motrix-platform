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
