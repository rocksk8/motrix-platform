"""`conftest.py` 兩道守門的守門（視窗 A 派工 T1～T5）。

## 為什麼這兩道守門要存在

`--basetemp` 的規則**早就寫在 `MULTIWIN-PROTOCOL.md:226-243`**，全量回歸互斥
寫在 §5-5。**而 2026-09-21 這一天，兩個視窗各踩了一次。**

> 🔑 **結論不是「加規則」，是「規則沒有到達」** —— 而「再寫一次」最沒用。

B 自己畫出了規則的極限，那句話是這兩道守門真正的理由：

> 「§5-5 的理由我讀得懂也同意，但我當時是『在等 C，**順手**把回歸跑掉』——
> **我沒有在「要不要跑」這個決策點上把它當成一個決策。**」

⇒ **凡是「等待期間的填充動作」都在文件的射程外**，只能用結構擋。

## ⚠️ 兩道守門防的是不同的東西，理由不可以互相代用

| 守門 | 防什麼 | 什麼時候適用 |
|---|---|---|
| `--basetemp` | **檔案**互刪 | **永遠** —— 跟機器忙不忙無關 |
| 全量回歸互斥 | **CPU** 競爭 | 只有全量回歸之間 |

🔑 **規則決定「做什麼」，理由決定「什麼時候適用」。**
我自己就照 §5-5 的「CPU 也是共用資源」推出過「機器閒著就可以一起跑」——
**而刪檔跟 CPU 忙不忙一點關係都沒有。**

## 📌 T2／T5 現在必然是綠的，它們仍然有用

判準不是「現在紅不紅」，是「**什麼改動會讓它紅**」：
hook 的條件寫反、或 `-full` 的判斷寫錯，它們就紅。
⚠️ **守門失效時最容易發生的事是把它刪掉，而它其實只是不夠了。**
看到必綠的題目請不要當成廢題。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TARGET = "tests/test_ports_helper_2026_09_21.py"   # 小、快、不碰 DB


def _run_pytest(*args, lock=None, timeout=180):
    """在子行程跑 pytest。**必須是子行程** —— `pytest_configure` 只在啟動時跑一次，
    在同一個行程裡是重現不出來的。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if lock is not None:
        env["MOTRIX_PYTEST_LOCK"] = str(lock)
    return subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "--collect-only", "-q", *args],
        cwd=str(BACKEND), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _dead_pid():
    """拿一個**確定已死、而且沒有人握著 handle** 的 pid。

    ⚠️ 不可以用 `subprocess.Popen` 再 `wait()`：`Popen` 物件**還握著 handle**，
    那個 pid 在 `OpenProcess` 眼中仍然開得起來 —— 我第一次寫的時候就被這個騙了，
    而症狀是「T4 判成還活著」，看起來完全像守門邏輯寫錯。
    🔑 **「查得到」與「還活著」是兩件事。**
    `subprocess.run` 回來之後物件就沒了，handle 跟著關掉。
    """
    out = subprocess.run([sys.executable, "-c", "import os;print(os.getpid())"],
                         capture_output=True, text=True, timeout=60)
    return int(out.stdout.strip())


def _write_lock(path, pid, age_seconds=0):
    path.write_text(json.dumps({
        "pid": pid,
        "started_at": time.time() - age_seconds,
        "basetemp": "假的-full",
    }), encoding="utf-8")


# ── T1／T2：--basetemp ────────────────────────────────────────────────────

def test_t1_missing_basetemp_is_refused_before_any_test_runs(tmp_path):
    """🔴 T1：不帶 `--basetemp` → `UsageError`，**而且在任何測試跑起來之前**。

    ⚠️ 「在任何測試跑起來之前」不是修辭：傷害發生在**第一支用到 `tmp_path`
    的測試**（pytest 那時才把 basetemp 整個刪掉重建）。擋在 fixture 裡就太晚了。
    """
    proc = _run_pytest(lock=tmp_path / "lock")
    assert proc.returncode == 4, (
        f"不帶 --basetemp 應該回 UsageError(4)，實際 {proc.returncode}\n"
        f"{proc.stdout[-800:]}"
    )
    out = proc.stdout + proc.stderr
    assert "--basetemp" in out, f"錯誤訊息沒講到 --basetemp：{out[-500:]}"
    assert "collected" not in out, (
        "已經收集了測試 —— 守門掛得太晚，要掛在 pytest_configure"
    )


def test_t2_with_basetemp_runs_normally(tmp_path):
    """T2：帶了就照常跑。**現在必然綠，判準是「hook 條件寫反就紅」。**"""
    proc = _run_pytest(f"--basetemp={tmp_path / 'bt'}", lock=tmp_path / "lock")
    assert proc.returncode == 0, f"{proc.returncode}\n{proc.stdout[-800:]}"


# ── T3～T5：全量回歸互斥鎖 ────────────────────────────────────────────────

def test_t3_second_full_regression_is_refused(tmp_path):
    """🔴 T3：鎖被一個**還活著**的行程持有 → 第二個全量回歸被擋下來。

    持有者用**這個測試自己的 pid** —— 它必然活著，不必去製造一個活行程，
    也就沒有「我以為它活著」的空間。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 4, (
        f"另一個全量回歸正在跑，應該被擋，實際 {proc.returncode}\n{proc.stdout[-800:]}"
    )
    assert str(os.getpid()) in (proc.stdout + proc.stderr), (
        "錯誤訊息沒講出持有者是誰 —— 被擋的人要有辦法判斷「那個行程還在不在」"
    )


def test_t4_dead_holder_does_not_block(tmp_path):
    """🔴🔴 T4：持有者**已經死了** → 放行（並接手）。

    > **一個解不掉的鎖比沒有鎖更糟** —— 它會把每個人訓練成「遇到鎖就先刪檔」，
    > 而那個習慣一旦養成，鎖就**永遠**失效了，包括它該生效的那些時候。

    ⚠️ 這才是這一組裡真正的守門。T3 擋得住是容易的，**T4 才決定它能不能活下去**。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, _dead_pid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 0, (
        f"持有者已經死了還擋著 —— 這個鎖解不掉。實際 {proc.returncode}\n"
        f"{proc.stdout[-800:]}"
    )


def test_t4b_expired_lock_does_not_block(tmp_path):
    """T4 的第二條路：持有者**還活著**但鎖已經過期 → 也要放行。

    ⚠️ 單靠 pid 是不夠的，而理由我在實作裡標註過：**pid 會被重用** ——
    一個無關的新行程剛好拿到同一個號碼，就會讓鎖永遠解不掉。
    時間上限是那個風險的兜底。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid(), age_seconds=99 * 60 * 60)
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 0, (
        f"鎖已經過期還擋著，實際 {proc.returncode}\n{proc.stdout[-800:]}"
    )


def test_t5_non_full_run_is_not_blocked_by_the_lock(tmp_path):
    """T5：basetemp 不是 `-full` 結尾 → **不碰鎖，也不被鎖擋**。

    ⚠️ 沒有這一題，一個「每次都搶鎖」的實作會讓 T3／T4 全綠 ——
    而那會讓**臨時跑一支單檔測試**擋住別人的全量回歸，
    然後大家就會開始刪鎖檔（見 T4）。

    ## 🔴 這一題的第一版是假綠燈，而⑤抓到了

    第一版寫的是「跑完之後 `lock` 不存在」。**它永遠綠** ——
    因為 `pytest_unconfigure` 本來就會把鎖釋放掉，
    所以「有搶鎖但還回去了」跟「從頭到尾沒搶」**在子行程結束之後長得一模一樣**。
    突變 `always_take_lock` 是這樣被放過的。

    🔑 **觀測點落在「事後」，而要觀測的行為只存在於「事中」。**
    ⇒ 改成讓鎖**先被一個活著的行程持有**：真的去搶就會被擋（回 4），
    觀測點從「跑完的狀態」換成「這一輪准不准跑」，那是事中才決定的事。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())          # 有人正在跑全量回歸
    proc = _run_pytest(f"--basetemp={tmp_path / 'plain-adhoc'}", lock=lock)
    assert proc.returncode == 0, (
        f"臨時單檔跑被全量回歸的鎖擋住了（{proc.returncode}）—— "
        "那會讓大家開始刪鎖檔\n" + proc.stdout[-600:]
    )
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid(), (
        "臨時單檔跑把別人的全量回歸鎖改寫了"
    )


def test_t5b_a_refused_run_must_not_delete_the_holders_lock(tmp_path):
    """🔴 T5b：**被擋下來的那個行程，結束時不可以把持有者的鎖刪掉。**

    ⚠️ 這是 `pytest_unconfigure` 最容易寫錯的地方：無條件刪檔看起來很對
    （「收尾就是要清乾淨」），而它會讓這道守門**只對第一個人有效**——
    第二個人被擋下、順手把鎖刪了，第三個人就暢行無阻。
    🔑 **釋放資源的前提是「我拿到過它」，不是「我要結束了」。**

    📌 ⑤ 查出來的一件事，寫在這裡免得下一個人拿掉錯的那一道：
    **真正守住這一題的是 `pid == os.getpid()` 那道比對**，不是 `_lock_taken_by_me`。
    只拿掉旗標時這題**照樣綠**（pid 比對接住了），兩道一起拿掉才紅。
    ⇒ 旗標是第二道防線、不是第一道。**要拿掉哪一道，先看是哪一道在擋。**
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 4, "前提不成立：這一輪應該要被擋下來"
    assert lock.exists(), "被擋下來的行程把持有者的鎖刪掉了"
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid(), (
        "鎖檔被改寫了 —— 沒搶到鎖的人不可以動它"
    )


def test_t5c_lock_is_released_when_the_run_finishes(tmp_path):
    """T5c：全量回歸跑完 → 鎖要**還回去**。

    ⚠️ 沒有這一題，T3 會在「鎖永遠不釋放」的實作下全綠，
    而那正是 T4 要解決的那個病的來源。
    """
    lock = tmp_path / "lock"
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 0, proc.stdout[-500:]
    assert not lock.exists(), "跑完了鎖還在 —— 下一個人會被一個沒有人持有的鎖擋住"
