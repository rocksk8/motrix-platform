"""e2e 逐題上限（PLAN-TEST-PERF §3.2，建包 e2e 改 -n 4 的前置條件）。

☠️ 一題卡住（例如 page.evaluate 等一個沒人回答的對話框）會拖住一個 worker 直到整輪逾時；
平行之後其他題也被拖著——而最後看到的只有「整輪逾時」，看不出卡在哪一題哪一行。
⇒ conftest 檔尾 `_E2EHardCapPhase`：每一題 e2e 的 setup／call／teardown 各自設上限（MOTRIX_E2E_HARD_CAP，預設 120s），超過就寫下所有
   執行緒的堆疊；xdist worker 裡順便結束那個 worker（xdist 判失敗、換新 worker 接著跑），主控在摘要印出堆疊
   並補一行 `FAILED <題> - Timeout…` 給建包閘門。單程序只寫堆疊、不結束（結束會讓剩下的題全都不跑）。

這一檔在子行程裡跑一支「故意睡過上限」的 e2e，驗：①xdist 下有被中止（不會睡滿）②摘要印出卡住的那一行
③有 `FAILED … Timeout` 那一行 ④單程序不結束、照樣印堆疊 ⑤反向控制：沒超過上限的題照常通過。
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 探針要吃到 backend/conftest.py（2026-09-25 自 tests/ 上移）⇒ 放在 backend/ 底下任何位置都可以；每一題各自一個目錄（-n 下三題同時跑，共用會互刪）。
# O6（2026-09-26）：原本放在 tests/ 底下 ⇒ 別的題的子 pytest 收集時，這個目錄被本題同時刪掉 ⇒ FileNotFoundError（第二班列車全量紅 1 次）。
# 改放 backend/ 根的「.」開頭目錄：pytest 遞迴收集與掃 tests/ 的工具都不會進去；本題以明確路徑指定檔案，照樣收集得到。
PROBE_ROOT = BACKEND
PROBE_PREFIX = ".hardcap_probe_"

SRC = '''import time
import pytest


@pytest.mark.e2e
def test_stuck_here():
    time.sleep(%(sleep)d)   # STUCK-LINE-MARKER


@pytest.mark.e2e
def test_quick():
    assert True
'''


@pytest.fixture
def probe():
    import uuid
    d = os.path.join(PROBE_ROOT, PROBE_PREFIX + uuid.uuid4().hex[:8])
    os.makedirs(d)
    f = os.path.join(d, "test_zz_hardcap_probe.py")

    def _write(sleep):
        open(f, "w", encoding="utf-8").write(SRC % {"sleep": sleep})
        return f
    yield _write
    shutil.rmtree(d, ignore_errors=True)


def _pytest(args, cap, tmp_path, tag):
    # 子 pytest 不可以繼承外層的 xdist／本次執行狀態（這一題自己在 -n 下跑時，外層是 worker）——由 utf8_env 統一剔除
    from tests._subproc import utf8_env
    env = utf8_env(MOTRIX_E2E_HARD_CAP=cap)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "-q", "-rf", "-p", "no:cacheprovider",
                        "--basetemp", str(tmp_path / tag)],
                       cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=180)
    return r, time.time() - t0, r.stdout + r.stderr


def test_under_xdist_a_stuck_e2e_is_stopped_and_says_where(probe, tmp_path):
    f = probe(60)
    r, took, out = _pytest([f, "-n", "1"], 3, tmp_path, "x")
    assert r.returncode != 0, out[-800:]
    assert took < 40, "沒有被中止，睡滿了（%.1fs）" % took
    assert "STUCK-LINE-MARKER" in out or "test_zz_hardcap_probe.py\", line 7" in out, "沒印出卡在哪一行：\n" + out[-1500:]
    assert "test_zz_hardcap_probe.py::test_stuck_here - Timeout: e2e 逐題上限" in out, out[-800:]
    assert "1 passed" in out, "卡住的那題之後，同一輪其他題要照跑：\n" + out[-600:]


def test_single_process_prints_the_stack_but_keeps_going(probe, tmp_path):
    f = probe(6)
    r, took, out = _pytest([f], 2, tmp_path, "s")
    assert r.returncode == 0, "單程序只寫堆疊、不結束（那一題本身睡完就過）：\n" + out[-800:]
    assert "2 passed" in out, out[-600:]
    assert "STUCK-LINE-MARKER" in out or "test_zz_hardcap_probe.py\", line 7" in out, out[-1500:]
    assert "- Timeout: e2e 逐題上限" not in out, "單程序沒有失敗，不可以補 FAILED 行"
    assert "（call 階段逾時）" in out, "堆疊要標明是哪個階段逾時：\n" + out[-800:]


SLOW_SETUP_SRC = '''import time
import pytest


@pytest.fixture
def slow_setup():
    time.sleep(%(setup)d)   # SLOW-SETUP-MARKER
    yield


@pytest.mark.e2e
def test_stuck_after_slow_setup(slow_setup):
    time.sleep(%(sleep)d)   # STUCK-LINE-MARKER
'''


def test_slow_setup_is_labelled_and_the_body_is_still_caught(probe, tmp_path):
    """2026-09-25（CORE-SPEC K5）：setup 慢（模擬滿載下共用伺服器／瀏覽器啟動）⇒ 標成 setup 逾時；
    本體卡住仍然會在自己的計時器裡被抓到那一行。原本 setup＋本體共用一個計時器，堆疊停在 setup、本體那一行消失。"""
    f = probe(0)
    open(f, "w", encoding="utf-8").write(SLOW_SETUP_SRC % {"setup": 4, "sleep": 5})
    r, took, out = _pytest([f], 2, tmp_path, "slow")
    assert r.returncode == 0, out[-800:]
    assert "（setup 階段逾時）" in out, out[-1500:]
    assert "SLOW-SETUP-MARKER" in out or "test_zz_hardcap_probe.py\", line 7" in out, out[-1500:]
    assert "（call 階段逾時）" in out and ("STUCK-LINE-MARKER" in out or "line 13" in out), out[-1500:]


def test_a_quick_e2e_leaves_nothing_behind(probe, tmp_path):
    """反向控制：沒超過上限 ⇒ 沒有摘要段落、沒有殘留的堆疊檔。"""
    f = probe(0)
    r, took, out = _pytest([f, "-n", "1"], 30, tmp_path, "q")
    assert r.returncode == 0 and "2 passed" in out, out[-800:]
    assert "e2e 逐題上限" not in out, out[-800:]


def test_probe_dir_is_outside_collected_trees():
    """O6：探針目錄不可以在會被收集／掃描的 tests/、modules/ 底下，且要「.」開頭（pytest 遞迴收集不進去）。"""
    probe_dir = os.path.join(PROBE_ROOT, PROBE_PREFIX + "x")
    rel = os.path.relpath(probe_dir, BACKEND).replace("\\", "/")
    assert rel.startswith(".") and "/" not in rel, rel
    assert not rel.startswith(("tests/", "modules/")), rel
