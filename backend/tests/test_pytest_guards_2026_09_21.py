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

from tests._subproc import run_python, utf8_env

BACKEND = Path(__file__).resolve().parent.parent
TARGET = "tests/test_ports_helper_2026_09_21.py"   # 小、快、不碰 DB


def _run_pytest(*args, lock=None, timeout=180, wait=0, poll=None, slots=1):
    """在子行程跑 pytest。**必須是子行程** —— `pytest_configure` 只在啟動時跑一次，
    在同一個行程裡是重現不出來的。

    📌 2026-09-24 起搶不到鎖改成排隊（使用者裁示「全機同時只准一套」）。這裡預設 `wait=0`
    ＝不排隊、立刻擋下，讓 T3／T5b／G1 仍然量得到「被擋」這件事；排隊行為見檔尾的排隊題。
    📌 同日使用者改為「開放兩個同時跑」（預設 2 格）。這裡預設 `slots=1`，讓既有的
    「被擋／排隊」題照舊量單格語意；2 格的行為見檔尾的兩格題。
    """
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(lock) if lock is not None else None,
                   MOTRIX_PYTEST_LOCK_WAIT=wait,
                   MOTRIX_PYTEST_LOCK_POLL=poll,
                   MOTRIX_PYTEST_SLOTS=slots)
    return run_python(["-m", "pytest", TARGET, "--collect-only", "-q", *args],
                      cwd=BACKEND, env=env, timeout=timeout)


def test_fx6a_netguard_blocks_a_real_smtp_connection(tmp_path):
    """🔴 FX6a：**NETGUARD 要涵蓋 `smtplib.SMTP`** —— 附實跑證據，不是只有綠燈。

    ## 📌 這一題是 §4 FX8a 要求的那個證據

    FX8a：「**新增的守門必須附『紅燈那一條路的實跑證據』**，不是只有綠燈。」
    ⇒ 我 2026-09-22 把 `smtplib` 加進 NETGUARD，而
    🔑 **「我加了一道守門」與「那道守門擋得住」是兩件事** ——
    今天已經在 `db.py:597` 的「守門見 test_u5c」上看過一次
    （那句話指向一支不存在的測試）。

    ## ⚠️ 必須在子行程裡跑，理由與 T1–T5 相同

    NETGUARD 的斷言在 **teardown**，所以在同一個行程裡「證明它會紅」
    就等於「讓這一題自己紅」。
    ⇒ 寫一個一次性的測試檔、在子行程跑它、**看它紅的理由對不對**。

    📌 而理由要對：`returncode != 0` 還不夠 ——
    ☠️ **一個 import 失敗也會給非零結束碼**，而那證明不了守門有作用
    （〈突變測試的假陽性〉：結束碼非 0 也可能是突變本身寫壞了）。
    ⇒ 要在輸出裡看到 **NETGUARD 自己的那句話**。
    """
    # 檔名刻意不符 `test_*.py`：放在 tests/ 底下才吃得到 conftest 的 NETGUARD，
    # 而 -n 並行時其他題（spec_coverage 等）會 glob tests/test_*.py 再逐檔讀 ——
    # 列到之後、讀之前被這裡刪掉 ⇒ FileNotFoundError（2026-09-24 全量偶發）。
    # 命令列明指的檔案 pytest 一律收集，不受 python_files 樣式限制。
    probe = BACKEND / "tests" / "_ng1_probe_tmp.py"
    probe.write_text(
        "import smtplib\n"
        "def test_probe():\n"
        "    try:\n"
        "        smtplib.SMTP('smtp.example.invalid', 587, timeout=1)\n"
        "    except Exception:\n"
        "        pass          # 模擬產品碼把例外吞掉\n",
        encoding="utf-8")
    try:
        proc = run_python(
            ["-m", "pytest", str(probe), "-q", "-p", "no:randomly",
             "--basetemp", str(tmp_path / "bt")],
            cwd=BACKEND, env=utf8_env(MOTRIX_PYTEST_LOCK=str(tmp_path / "lk")),
            timeout=180)
    finally:
        probe.unlink(missing_ok=True)

    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "那一題連了 SMTP 而測試通過了 —— NETGUARD 沒有攔到。\n"
        f"{out[-700:]}"
    )
    assert "NETGUARD" in out, (
        "它紅了，**而不是因為 NETGUARD** —— 那證明不了守門有作用。\n"
        f"{out[-700:]}"
    )
    assert "smtp" in out.lower(), (
        f"NETGUARD 的訊息裡沒有提到 smtp：\n{out[-700:]}"
    )


def _really_gone(pid):
    """這個 pid 真的不在了嗎 —— **用與受測對象無關的來源判斷**。

    🔴 **刻意不呼叫 `conftest._pid_alive()`**：那是 T4 唯一要驗的東西，
    拿它來挑測試資料等於用受測對象證明受測對象。
    （而且 `pid_always_alive` 那個突變一下去，這支會永遠找不到死的 pid，
    T4 就會變成「**錯誤**」而不是「**紅**」—— 而錯誤的訊息會指向重試邏輯，
    指不到 `_pid_alive`。）
    """
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        return False
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                         capture_output=True, text=True, timeout=60)
    return str(pid) not in out.stdout


def _dead_pid(tries=8):
    """拿一個**確定已死、而且沒有人握著 handle** 的 pid。

    ⚠️ 不可以用 `subprocess.Popen` 再 `wait()`：`Popen` 物件**還握著 handle**，
    那個 pid 在 `OpenProcess` 眼中仍然開得起來 —— 我第一次寫的時候就被這個騙了，
    而症狀是「T4 判成還活著」，看起來完全像守門邏輯寫錯。
    🔑 **「查得到」與「還活著」是兩件事。**
    `subprocess.run` 回來之後物件就沒了，handle 跟著關掉。

    ## ⚠️ 為什麼要重試：**Windows 會重用剛釋放的 pid**

    剛結束的行程留下的號碼很快就會被別人拿走。被重用的話這一題會紅，
    ☠️ **而它紅起來的訊息是「持有者已經死了還擋著 —— 這個鎖解不掉」，
    看起來完全像實作壞了。** 一個偶發、而且指向錯方向的紅燈。
    ⇒ 拿到號碼之後**獨立確認它真的不在了**，被重用就換一個。
    """
    for _ in range(tries):
        out = subprocess.run([sys.executable, "-c", "import os;print(os.getpid())"],
                             capture_output=True, text=True, timeout=60)
        pid = int(out.stdout.strip())
        if _really_gone(pid):
            return pid
    raise AssertionError(
        "試了 %d 次都拿不到一個確定已死的 pid —— 這台機器的 pid 重用特別快，"
        "T4 需要換一種取得方式（不是守門壞了）" % tries
    )


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


# ── G1／G2：A 的四項裁定裡屬於測試的兩項 ─────────────────────────────────

def test_g1_refusal_message_does_not_offer_deleting_the_lock_as_the_cure(tmp_path):
    """🟡 G1：拒絕訊息**不可以**把「刪掉鎖檔」寫成「持有者已經死了」的解法。

    🔴 **因為在 T4 有效的前提下，那個情況根本不會讓你被擋到。**
    持有者死了 → T4 放行；鎖過期 → T4b 放行。
    ⇒ 你會被擋，代表那個行程**很可能真的還在跑** ——
    這時候刪掉鎖檔，就是去踩掉一個正在跑的 24 分鐘回歸。

    唯一該手動刪的情形是 **pid 被重用**（一個無關的新行程剛好拿到同一個號碼），
    而你不想等到年紀上限。

    ## ⚠️ 這一題的斷言是脆的，我照實說

    改個說法就繞過去了。但判準不是「它擋不擋得住所有寫法」，是
    **「什麼改動會讓它紅」＝有人把那個錯的適用情境寫回來**。
    ⇒ 所以寫成**條件式**而不是字串比對：
    **訊息可以提刪檔，但提了就必須同時說出「重用」這個前提。**
    講出正確前提的寫法都過得去，漏掉前提的寫法才紅。

    📌 這條的來歷值得留著：B 承諾「被擋到不自己刪、會回報」，
    而它讀到的訊息叫它「若確定已經死了就刪」。
    **B 的承諾比訊息正確。**
    ⚠️ 一句錯的建議，被一個讀不到它的人用更嚴的原則擋掉了 —— **那不是設計，是運氣。**
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 4, "前提不成立：這一輪應該被擋下來"
    msg = proc.stdout + proc.stderr
    if "刪" in msg:
        assert "重用" in msg, (
            "拒絕訊息叫人刪鎖檔，卻沒有說出唯一適用的前提（pid 被重用）。\n"
            "⚠️ 在 T4 有效的前提下，『持有者已經死了』不會讓人被擋到 —— "
            "會被擋就代表它很可能還在跑，這時候刪檔是去踩掉一個正在跑的回歸。\n"
            f"實際訊息：{msg[-600:]}"
        )


def test_g2_a_corrupt_lock_file_lets_everyone_through(tmp_path):
    """🔴 G2：鎖檔內容壞掉（JSON 合法、欄位不是數字）→ **放行**，不可以崩掉。

    `float(held["started_at"])` / `int(held["pid"])` 對 `"x"` 會丟 `ValueError`，
    而它發生在 `pytest_configure` 裡 ⇒ **整個 pytest 起不來** ⇒
    **每一個人的每一支測試都被擋住**，方向與「壞掉的鎖應該放行」完全相反。

    ⚠️ 觸發條件是「有人手動改過鎖檔」，聽起來很罕見 ——
    🔑 **但 G1 那句錯的訊息正在叫人去手動動那個檔，而手動動過的鎖檔
    正是唯一能讓守門崩掉的東西。** 兩個各自都不嚴重的缺陷互相加成。

    ⇒ 一個**不可信的鎖**要當成**沒有鎖**，不是當成「拒絕所有人」。
    """
    lock = tmp_path / "lock"
    lock.write_text(json.dumps({"pid": "不是數字", "started_at": "也不是",
                                "basetemp": "壞掉的"}), encoding="utf-8")
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 0, (
        f"壞掉的鎖檔把所有人擋在外面了（{proc.returncode}）—— "
        "不可信的鎖要當成沒有鎖\n" + (proc.stdout + proc.stderr)[-900:]
    )


def test_g2b_a_lock_file_that_is_not_json_lets_everyone_through(tmp_path):
    """G2 的第二條路：鎖檔**根本不是 JSON**（寫到一半、被編輯器塞了 BOM…）。

    ⚠️ 跟 G2 分開寫是因為它們走的是**不同的例外**：
    這一條在 `json.loads` 就炸（已經被 `_read_lock` 接住），
    G2 那一條活過了解析、炸在**取值**上 —— 而那一層原本沒有人接。
    🔑 **「格式壞掉」與「格式對而值壞掉」是兩個不同的失敗。**
    """
    lock = tmp_path / "lock"
    lock.write_text("這不是 JSON {{{", encoding="utf-8")
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock)
    assert proc.returncode == 0, (
        f"不是 JSON 的鎖檔把所有人擋在外面了（{proc.returncode}）\n"
        + (proc.stdout + proc.stderr)[-900:]
    )
def test_the_politeness_delay_is_zero_in_tests():
    """⚙️ `_no_politeness_delay` 的**生效那一側**。

    ☠️ 少了這一題，那支 fixture 哪天失效（常數改名、模組搬家）
    會讓整個 suite **安靜地慢回去** —— 而慢不會讓任何一題紅。
    🔑 而「設回去真的會 sleep」那一側由
    `test_tender_detail_2026_09_21.py::test_d3_…` 守 —— **兩題成對。**

    ## ☠️ 而這一題原本寫在 `conftest.py` 裡，**pytest 根本不收集它**

    ```
    $ pytest tests/ --collect-only -k politeness
      no tests collected (1939 deselected)
    ```
    🔑 **一個不會被收集的「對照組」，與沒有對照組完全相同** ——
    而它在 `conftest.py` 裡看起來像一題（有 `def test_`、有斷言、有 docstring）。
    📌 是我跑 `--collect-only -k` 去查才發現的，**不是它報錯**。
    ⇒ 寫完一個新的對照組，**第一件事是確認它真的被收集到**。
    """
    from modules.tender_radar import source as tender_source
    assert tender_source.DETAIL_INTERVAL_SECONDS == 0, (
        f"測試裡的 `DETAIL_INTERVAL_SECONDS` 是 "
        f"{tender_source.DETAIL_INTERVAL_SECONDS}，預期 0 ——\n"
        "☠️ `_no_politeness_delay` 沒有生效（常數改名？模組搬家？），\n"
        "🔑 而它失效的症狀只有「整個 suite 慢回去」，**沒有任何一題會紅**。")




# ── 排隊題：全機同時只准一套（2026-09-24 使用者裁示）——排隊而不是擋下 ────────────

def _holder_for(seconds):
    """起一個活著 `seconds` 秒的行程當鎖的持有者（它結束 ＝ 持有者跑完）。"""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%s)" % seconds])


def test_a_queued_run_starts_once_the_holder_finishes(tmp_path):
    """🔴 持有者還在跑 ⇒ 排隊；持有者結束 ⇒ 輪到我、接手鎖、照常跑完。

    ⚠️ 這是新規則的核心：以前這裡回 4（擋下），使用者要的是「其他視窗排隊」。
    """
    lock = tmp_path / "lock"
    holder = _holder_for(3)
    try:
        _write_lock(lock, holder.pid)
        t0 = time.time()
        proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock, wait=60, poll=0.2)
        waited = time.time() - t0
    finally:
        holder.kill()
        holder.wait()
    assert proc.returncode == 0, f"持有者結束後沒有輪到我：{proc.returncode}\n{proc.stdout[-800:]}"
    assert "排隊中" in proc.stdout, "排隊時要說出來（否則看起來像卡住）\n" + proc.stdout[-600:]
    assert waited >= 2, f"沒有等持有者就跑了（只等了 {waited:.1f} 秒）"
    assert not lock.exists(), "跑完了鎖還在"


def test_the_queue_gives_up_after_the_wait_limit(tmp_path):
    """等到上限仍未輪到 ⇒ 擋下（回 4），訊息說明排了多久、誰在跑；不動持有者的鎖。"""
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock, wait=1, poll=0.2)
    assert proc.returncode == 4, f"等到上限應該擋下，實際 {proc.returncode}\n{proc.stdout[-800:]}"
    assert str(os.getpid()) in (proc.stdout + proc.stderr)
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid(), "排隊失敗的人動了持有者的鎖"


def test_a_parallel_run_also_queues_even_without_full_in_the_name(tmp_path):
    """🔴 `-n` 平行（例如平行跑 e2e）也吃滿 CPU ⇒ 也要搶同一把鎖。
    反向控制是 T5：不平行、不叫 -full 的單檔臨時跑不搶鎖。"""
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest("-n", "2", "-p", "xdist", f"--basetemp={tmp_path / 'plain-adhoc'}", lock=lock, wait=0)
    assert proc.returncode == 4, f"-n 2 的一輪沒有被鎖管到：{proc.returncode}\n{proc.stdout[-800:]}"


# ── 兩格：「開放兩個同時跑」（2026-09-24 使用者裁示）────────────────────────────

def test_with_two_slots_a_second_heavy_run_proceeds_while_one_is_held(tmp_path):
    """🔴 第 1 格被活著的行程佔住 ⇒ 第二套拿第 2 格照常跑，跑完只還第 2 格。

    反向控制在下一題：兩格都佔住 ⇒ 第三套被擋。沒有那一題，「永遠放行」的實作也會讓這題綠。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock, slots=2)
    assert proc.returncode == 0, f"第 2 格空著卻沒放行：{proc.returncode}\n{proc.stdout[-800:]}"
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid(), "第二套動了第 1 格持有者的鎖"
    assert not lock.with_name(lock.name + ".slot2").exists(), "跑完了第 2 格的鎖還在"


def test_with_two_slots_a_third_heavy_run_is_held_back(tmp_path):
    """兩格都被活著的行程佔住 ⇒ 第三套排不到（wait=0 ⇒ 擋下回 4），兩格都不被動到。"""
    lock = tmp_path / "lock"
    slot2 = lock.with_name(lock.name + ".slot2")
    _write_lock(lock, os.getpid())
    _write_lock(slot2, os.getpid())
    proc = _run_pytest(f"--basetemp={tmp_path / 'x-full'}", lock=lock, slots=2)
    assert proc.returncode == 4, f"兩格都滿了卻放行：{proc.returncode}\n{proc.stdout[-800:]}"
    assert lock.exists() and slot2.exists(), "被擋的人動了持有者的鎖"


def test_queue_message_does_not_crash_when_stdout_is_not_utf8(tmp_path):
    """🔴 輸出導到檔案、stdout 編碼是 cp932 時，排隊訊息不可以讓整輪 INTERNALERROR。

    ☠️ 2026-09-24 實際發生：`pytest ... > run.txt` 在排隊時印中文 ⇒ UnicodeEncodeError
    ⇒ 回 3（INTERNALERROR），看起來像鎖壞了。正確是照常排隊，等到上限回 4。
    """
    lock = tmp_path / "lock"
    _write_lock(lock, os.getpid())
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(lock), MOTRIX_PYTEST_LOCK_WAIT=1,
                   MOTRIX_PYTEST_LOCK_POLL=0.2, MOTRIX_PYTEST_SLOTS=1,
                   PYTHONUTF8="0", PYTHONIOENCODING="cp932")
    proc = run_python(["-m", "pytest", TARGET, "--collect-only", "-q",
                       f"--basetemp={tmp_path / 'x-full'}"], cwd=BACKEND, env=env, timeout=180)
    out = proc.stdout + proc.stderr
    assert "INTERNALERROR" not in out, out[-800:]
    assert proc.returncode == 4, f"應排隊到上限後擋下（4），實際 {proc.returncode}\n{out[-800:]}"


# ── 暫存資料夾用完即刪（2026-09-24 使用者：核心規則）─────────────────────────────

def test_a_finished_run_deletes_its_own_basetemp(tmp_path):
    """🔴 一輪跑完就刪掉自己的 basetemp；旁邊別人的目錄不動（不可以用萬用字元整批刪）。"""
    bt = tmp_path / "motrix-pytest-x-adhoc"
    neighbour = tmp_path / "motrix-pytest-someone-else"
    neighbour.mkdir()
    (neighbour / "in_use.db").write_text("x", encoding="utf-8")
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"), MOTRIX_PYTEST_KEEP_BASETEMP=None)
    proc = run_python(["-m", "pytest", TARGET, "-q", "-p", "no:randomly", f"--basetemp={bt}"],
                      cwd=BACKEND, env=env, timeout=180)
    assert proc.returncode == 0, proc.stdout[-600:]
    assert not bt.exists(), "跑完了 basetemp 還在 ⇒ 每輪留 1~2GB"
    assert (neighbour / "in_use.db").exists(), "刪到了別人的目錄"


def test_keep_flag_leaves_basetemp_for_debugging(tmp_path):
    """反向控制：設 MOTRIX_PYTEST_KEEP_BASETEMP=1 時保留（查紅燈用）。"""
    bt = tmp_path / "motrix-pytest-keep-adhoc"
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"), MOTRIX_PYTEST_KEEP_BASETEMP="1")
    proc = run_python(["-m", "pytest", TARGET, "-q", "-p", "no:randomly", f"--basetemp={bt}"],
                      cwd=BACKEND, env=env, timeout=180)
    assert proc.returncode == 0, proc.stdout[-600:]
    assert bt.exists(), "設了保留旗標卻被刪掉"
