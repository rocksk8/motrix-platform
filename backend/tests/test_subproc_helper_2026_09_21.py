"""`tests/_subproc.py` 自己的守門。

## 為什麼這支必須存在

2026-09-21 我把四個各自 spawn 子行程的 harness 收進**一個**入口，
理由跟 `_ports.py` 那次一樣：**bug 的家從四個變成一個**。

> 🔑 **而唯一的那個家需要一道守門。**
> 少了它，這次的修正會變成一個沒有人守著的單點 ——
> 而它壞掉的樣子是**「別人跑到全紅、我跑到全綠」**，
> 也就是**最不像 bug 的那一種**：兩邊各自看都很正常。

⚠️ 更直接的理由：**同一個形狀我今天犯了兩次**。
上午把 21 個 e2e 檔的挑埠邏輯收進 `_ports.py`，
下午又寫了四個各自 spawn 子行程的 harness，**沒有一個設環境**。
**修好一個實例，不等於認得那個模式。**
"""
import subprocess
import sys

import pytest

from tests._subproc import run_python, utf8_env

BACKEND = __import__("pathlib").Path(__file__).resolve().parent.parent

_PRINT_ENCODING = "import sys;print(sys.stdout.encoding)"
_PRINT_CHINESE = "print('中文測試：值')"


def test_child_stdout_is_utf8_even_when_the_parent_has_nothing_set(monkeypatch):
    """🔴 核心不變量：**子行程的編碼不由跑測試的人的環境決定。**

    先把父行程的兩個變數**刪掉**，再問子行程「你的 stdout 是什麼編碼」。
    ⚠️ 不刪的話，這一題會在「我的殼剛好設了」的情況下綠 ——
    **而那正是這整件事的成因**：我量到的綠燈只在我的殼裡成立。
    """
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    proc = run_python(["-c", _PRINT_ENCODING], cwd=BACKEND, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.strip().lower().replace("-", "") == "utf8", (
        f"子行程的 stdout 編碼是 {proc.stdout.strip()!r}，不是 utf-8 —— "
        "它會隨著跑測試那台機器的 ANSI code page 變，而那正是要消除的變數"
    )


def test_child_can_print_chinese_without_the_parent_env(monkeypatch):
    """端到端：子行程印中文**不可以炸**。

    ⚠️ 上一題驗的是「編碼設對了」，這一題驗的是「**它真的沒事**」。
    🔑 「設定看起來對」與「拿它去做那件事會成功」是兩個問題 ——
    而實際咬到我們的是後者（`print` 當場丟 `UnicodeEncodeError`、結束碼 1，
    父行程看到的是「子行程失敗了」，訊息指向被測對象）。
    """
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    proc = run_python(["-c", _PRINT_CHINESE], cwd=BACKEND, timeout=60)
    assert proc.returncode == 0, (
        f"子行程印中文就死了（returncode={proc.returncode}）：\n{proc.stderr[-600:]}"
    )
    assert "中文測試：值" in proc.stdout, f"收到的是 {proc.stdout!r}"


def test_without_the_helper_this_machine_really_would_break(monkeypatch):
    """對照組：**不走這個入口的話，在這台機器上真的會壞。**

    ⚠️ 沒有這一題，上面兩題可能只是在驗一件本來就成立的事 ——
    若這台機器的 ANSI code page 本來就是 UTF-8，那兩題**永遠綠而什麼都沒守**，
    而下一個人會覺得 `_subproc.py` 是多餘的、順手拿掉它。

    📌 在已經是 UTF-8 的機器上這一題會 `skip`，**而 skip 本身就是訊息**：
    它說的是「這台機器示範不出那個危險」，不是「那個危險不存在」。
    """
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    import os
    plain = subprocess.run(
        [sys.executable, "-c", _PRINT_ENCODING],
        cwd=str(BACKEND), env=dict(os.environ),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    enc = plain.stdout.strip().lower().replace("-", "")
    if enc == "utf8":
        pytest.skip(
            "這台機器不帶環境變數時子行程就已經是 UTF-8 了 —— "
            "示範不出那個危險，但它在 cp932／cp950 的機器上仍然存在"
        )
    assert enc != "utf8"   # 走到這裡就代表對照組成立：不走入口會拿到別的編碼


def test_utf8_env_can_delete_a_variable():
    """`utf8_env(X=None)` 要**刪掉**那個變數，不是設成字串 `"None"`。

    ⚠️ 守門測試用它來製造「父行程什麼都沒設」的情境，
    而 `env["X"] = "None"` 與 `del env["X"]` 在下游的行為完全不同 ——
    前者是「設了一個叫 None 的值」。🔑 又是 `null` vs `"null"` 那一族。
    """
    env = utf8_env(MOTRIX_PYTEST_LOCK="abc")
    assert env["MOTRIX_PYTEST_LOCK"] == "abc"
    env2 = utf8_env(MOTRIX_PYTEST_LOCK=None)
    assert "MOTRIX_PYTEST_LOCK" not in env2, (
        f"傳 None 沒有刪掉那個變數，拿到 {env2.get('MOTRIX_PYTEST_LOCK')!r}"
    )


def test_utf8_env_overrides_a_hostile_parent(monkeypatch):
    """父行程**設了錯的值**時也要壓過去，不是只處理「沒設」。

    ⚠️ 「沒設」與「設錯」是兩個情境。只用 `setdefault` 的實作會過第一題
    而在第二題失效 —— 而第二題才是真實世界的樣子（有人為了別的原因
    在使用者層級設了 `PYTHONIOENCODING=cp950`）。
    """
    monkeypatch.setenv("PYTHONIOENCODING", "cp950")
    monkeypatch.setenv("PYTHONUTF8", "0")
    env = utf8_env()
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
