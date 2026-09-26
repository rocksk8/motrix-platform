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
# ~~改放 backend/ 根的「.」開頭目錄~~〔更正（稽核 D O6-M1）：backend/ 根會被十多道「rglob 整個 backend、排除 tests/」的產品碼掃描看到
# （edge_profile、begin_write、requirements、_l1_interface、dep_scan…；實測 20 次掃描 3 次 FileNotFoundError）〕
# ⇒ 放 backend/tests/ 底下的「.」開頭目錄：產品碼掃描排除 tests/ 碰不到；pytest 遞迴收集不進「.」開頭的目錄；本題以明確路徑指定檔案，照樣收集得到。
PROBE_ROOT = os.path.join(BACKEND, "tests")
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
    _remove_probe(d)


def _remove_probe(d):
    """刪探針目錄：刪不掉（別的行程正在讀）⇒ 記錄並等一下重試一次；仍刪不掉 ⇒ 發 warning 寫出路徑（不靜默忽略，稽核 D O6-M1）。"""
    import warnings
    for attempt in (1, 2):
        try:
            shutil.rmtree(d)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            if attempt == 1:
                print("[hard_cap] 探針目錄刪不掉（%s）：%s ⇒ 1 秒後重試" % (e, d))
                time.sleep(1)
            else:
                warnings.warn("hard_cap 探針目錄重試後仍刪不掉，請手動刪除：%s（%s）" % (d, e))


def _pytest(args, cap, tmp_path, tag, temp_dir=None):
    # 子 pytest 不可以繼承外層的 xdist／本次執行狀態（這一題自己在 -n 下跑時，外層是 worker）——由 utf8_env 統一剔除
    from tests._subproc import utf8_env
    env = utf8_env(MOTRIX_E2E_HARD_CAP=cap)
    if temp_dir is not None:
        # 子行程的暫存目錄指到本題自己的資料夾 ⇒ 逐題上限目錄（tempfile.gettempdir() 底下）看得到、也不會碰到真的 %TEMP%
        env = dict(env, TEMP=str(temp_dir), TMP=str(temp_dir))
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


def test_probe_dir_is_outside_product_scans_and_pytest_collection():
    """O6／O6-M1（靜態守門）：探針目錄在 backend/tests/ 底下、「.」開頭——
    產品碼掃描（core.source_tree 的 product_files／logic_files／router_files，以及「rglob 整個 backend、排除 tests」的守門）碰不到；
    pytest 遞迴收集不進「.」開頭的目錄。
    ⚠ 本題只驗 core.source_tree 的清單；**自己寫 rglob 的掃描**（掃整個 backend 的守門）靠各自排除 tests/ 來保證——
    2026-09-26 稽核 D 逐行查 13 道，12 道有排除、剩下 1 道已修（h-o6s1）；新增這類掃描時要自己排除 tests/（稽核 D O6-S1）。"""
    from core import source_tree
    probe_dir = os.path.join(PROBE_ROOT, PROBE_PREFIX + "x")
    rel = os.path.relpath(probe_dir, BACKEND).replace("\\", "/")
    parts = rel.split("/")
    assert parts[0] == "tests" and len(parts) == 2 and parts[1].startswith("."), rel
    assert "tests" in source_tree._NON_PRODUCT_DIRS          # 產品碼掃描排除的目錄名（單一定義）
    # 實際建一個探針目錄與檔案，產品碼清單裡找不到它
    import uuid
    d = os.path.join(PROBE_ROOT, PROBE_PREFIX + "static_" + uuid.uuid4().hex[:6])
    os.makedirs(d)
    try:
        open(os.path.join(d, "test_zz_hardcap_probe.py"), "w", encoding="utf-8").write("x = 1\n")
        for lister in (source_tree.product_files, source_tree.logic_files, source_tree.router_files):
            hits = [str(f) for f in lister() if PROBE_PREFIX in str(f)]
            assert not hits, (lister.__name__, hits)
    finally:
        _remove_probe(d)


# ── 每次執行的逐題上限目錄要收掉（主持派工 wip/b-hardcap-dir：%TEMP% 累積 1055 個）────────────────────

def _run_dirs(temp_dir):
    return sorted(p for p in os.listdir(temp_dir) if p.startswith("motrix-e2e-hardcap-"))


@pytest.mark.parametrize("xdist", [False, True], ids=["n0", "n1"])
def test_normal_run_leaves_no_run_dir(probe, tmp_path, xdist):
    """沒有逾時 ⇒ 收尾後本次執行的目錄不存在（單程序與 xdist 都是）。反向控制：拿掉 _cleanup_hard_cap_dir 的刪除 ⇒ 紅。"""
    f = probe(0)
    t = tmp_path / "tmp_env"
    t.mkdir()
    r, took, out = _pytest([f] + (["-n", "1"] if xdist else []), 30, tmp_path, "c" + str(int(xdist)), temp_dir=t)
    assert r.returncode == 0 and "2 passed" in out, out[-800:]
    assert _run_dirs(t) == [], "收尾後還留著：%s" % _run_dirs(t)


def test_timeout_keeps_the_run_dir_and_prints_its_path(probe, tmp_path):
    """有逾時 ⇒ 堆疊檔與目錄保留，摘要印出路徑（單程序：只寫堆疊、不結束）。"""
    f = probe(6)
    t = tmp_path / "tmp_env"
    t.mkdir()
    r, took, out = _pytest([f], 2, tmp_path, "k", temp_dir=t)
    dirs = _run_dirs(t)
    assert len(dirs) == 1, (dirs, out[-800:])
    kept = os.path.join(str(t), dirs[0])
    assert any(n.endswith(".txt") for n in os.listdir(kept)), "堆疊檔要留著"
    assert "堆疊檔保留在：" in out and dirs[0] in out, out[-800:]

