"""建包獨佔測試鎖（PLAN-TEST-PERF §3.3，使用者選定）。

☠️ 測試鎖全機 2 格：建包佔一格時，另一個視窗仍可以同時跑一套 `-n`。
   建包裡靠時序的題會因為 CPU 被搶而紅，**而紅的樣子跟真的 bug 一模一樣**——
   要嘛整包重跑，要嘛有人開始懷疑測試、加 retry。
🔑 `MOTRIX_PYTEST_EXCLUSIVE=1`（建包腳本設）：
   - 先登記「我要獨佔」（`<鎖檔>.exclusive`），**之後進來的一般測試不再佔新的格子**（否則建包會一直等不到）；
   - 等目前的持有者跑完，**一次佔滿所有格子**；
   - 結束時全部歸還，連同登記。
   - 登記的行程已死 ⇒ 登記無效（一個解不掉的鎖比沒有鎖更糟）。
"""
import json
import os
import subprocess
import sys
import textwrap
import time

from tests._subproc import run_python, utf8_env

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join("tests", "test_version_manifest_unique_version_2026_09_25.py")


def _run(tmp_path, lock, *args, exclusive=False, wait=0, extra_env=None):
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(lock), MOTRIX_PYTEST_LOCK_WAIT=wait,
                   MOTRIX_PYTEST_LOCK_POLL=0.2, MOTRIX_PYTEST_SLOTS=2,
                   MOTRIX_PYTEST_EXCLUSIVE="1" if exclusive else None, **(extra_env or {}))
    return run_python(["-m", "pytest", TARGET, "--collect-only", "-q",
                       f"--basetemp={tmp_path / 'x-full'}", *args], cwd=BACKEND, env=env, timeout=180)


def _hold(path, pid, age=0):
    path.write_text(json.dumps({"pid": pid, "started_at": time.time() - age, "basetemp": "held-full"}),
                    encoding="utf-8")


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_an_exclusive_run_waits_while_any_slot_is_held(tmp_path):
    """🔴 一格被佔、另一格空著：一般的一輪會拿空的那格；獨佔的一輪必須等。"""
    lock = tmp_path / "lock"
    _hold(lock, os.getpid())
    proc = _run(tmp_path, lock, exclusive=True, wait=0)
    assert proc.returncode == 4, f"獨佔的一輪沒有等其他持有者：{proc.returncode}\n{proc.stdout[-600:]}"
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid(), "動了持有者的鎖"
    assert not (tmp_path / "lock.slot2").exists(), "擋下之後留下了自己佔的格子"
    assert not (tmp_path / "lock.exclusive").exists(), "擋下之後留下了獨佔登記"


def test_an_exclusive_run_holds_every_slot_while_it_runs_and_returns_them(tmp_path):
    """🔴 沒人佔：獨佔的一輪執行期間兩格都是它的；結束後全部歸還。"""
    lock = tmp_path / "lock"
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "slotprobe.py").write_text(textwrap.dedent('''
        import json, os
        def pytest_collection_finish(session):
            lock = os.environ["MOTRIX_PYTEST_LOCK"]
            pids = [json.load(open(p, encoding="utf-8"))["pid"] for p in (lock, lock + ".slot2")
                    if os.path.exists(p)]
            print("SLOTPIDS=%s ME=%s" % (pids, os.getpid()))
    '''), encoding="utf-8")
    proc = _run(tmp_path, lock, "-p", "slotprobe", exclusive=True,
                extra_env={"PYTHONPATH": str(probe)})
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("SLOTPIDS=")]
    assert line, "探針沒有執行\n" + proc.stdout[-600:]
    pids, me = line[0][len("SLOTPIDS="):].split(" ME=")
    assert json.loads(pids) == [int(me), int(me)], "執行期間兩格不都是自己的：" + line[0]
    for f in ("lock", "lock.slot2", "lock.exclusive"):
        assert not (tmp_path / f).exists(), f"結束後沒有歸還 {f}"


def test_a_normal_run_does_not_jump_ahead_of_a_waiting_exclusive_run(tmp_path):
    """🔴 有存活的獨佔登記時，一般的一輪即使看到空格也要排隊（否則建包永遠等不到）。"""
    lock = tmp_path / "lock"
    _hold(tmp_path / "lock.exclusive", os.getpid())
    proc = _run(tmp_path, lock, exclusive=False, wait=0)
    assert proc.returncode == 4, f"一般的一輪插隊到獨佔登記前面：{proc.returncode}\n{proc.stdout[-600:]}"
    assert "獨佔" in proc.stdout + proc.stderr, "被擋時要說明是在等建包獨佔"


def test_a_dead_exclusive_registration_does_not_block_anyone(tmp_path):
    """反向控制：登記的行程已死 ⇒ 不擋，照常跑。"""
    lock = tmp_path / "lock"
    _hold(tmp_path / "lock.exclusive", _dead_pid())
    proc = _run(tmp_path, lock, exclusive=False, wait=0)
    assert proc.returncode == 0, proc.stdout[-800:]


def test_without_exclusive_two_runs_still_share_the_two_slots(tmp_path):
    """反向控制：沒有獨佔時，既有「兩格」行為不變——一格被佔，第二輪照樣進得去。"""
    lock = tmp_path / "lock"
    _hold(lock, os.getpid())
    proc = _run(tmp_path, lock, exclusive=False, wait=0)
    assert proc.returncode == 0, proc.stdout[-800:]


def test_a_build_holds_the_registration_across_its_two_stages(tmp_path):
    """🔴 建包分兩段（非 e2e、e2e）：登記由建包腳本持有（pid＝建包），兩段 pytest 以
    MOTRIX_PYTEST_EXCLUSIVE_OWNER 認得它，照樣佔滿所有格子，結束時**不刪**登記
    （否則兩段之間的空檔會被別的視窗插進來）。"""
    lock = tmp_path / "lock"
    _hold(tmp_path / "lock.exclusive", os.getpid())
    proc = _run(tmp_path, lock, exclusive=True, wait=0,
                extra_env={"MOTRIX_PYTEST_EXCLUSIVE_OWNER": str(os.getpid())})
    assert proc.returncode == 0, f"建包自己的登記擋住了自己：{proc.returncode}\n{proc.stdout[-600:]}"
    assert (tmp_path / "lock.exclusive").exists(), "第一段結束就把建包的登記刪了"
    assert not lock.exists() and not (tmp_path / "lock.slot2").exists(), "格子沒有歸還"
    # 登記還在時，一般的一輪仍要排隊
    proc2 = _run(tmp_path, lock, exclusive=False, wait=0)
    assert proc2.returncode == 4


def test_a_registration_outlives_the_one_hour_slot_age_while_its_owner_is_alive(tmp_path):
    """建包可能超過 60 分鐘：登記不可以用格子的 60 分鐘上限判過期（持有者活著就有效，上限 3 小時）。"""
    lock = tmp_path / "lock"
    _hold(tmp_path / "lock.exclusive", os.getpid(), age=90 * 60)
    proc = _run(tmp_path, lock, exclusive=False, wait=0)
    assert proc.returncode == 4, "90 分鐘的建包登記被當成過期清掉了"


def test_an_exclusive_run_locks_even_without_n_or_full_in_the_name(tmp_path):
    """🔴 建包的 e2e 段是序列、basetemp 也不叫 -full ⇒ 原本不搶鎖；帶了獨佔就要佔滿。"""
    lock = tmp_path / "lock"
    _hold(lock, os.getpid())
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(lock), MOTRIX_PYTEST_LOCK_WAIT=0, MOTRIX_PYTEST_LOCK_POLL=0.2,
                   MOTRIX_PYTEST_SLOTS=2, MOTRIX_PYTEST_EXCLUSIVE="1")
    proc = run_python(["-m", "pytest", TARGET, "--collect-only", "-q", f"--basetemp={tmp_path / 'plain_e2e'}"],
                      cwd=BACKEND, env=env, timeout=180)
    assert proc.returncode == 4, f"序列、非 -full 的獨佔一輪沒有搶鎖：{proc.returncode}\n{proc.stdout[-600:]}"
