"""起一個 Python 子行程來測東西時，**唯一**的入口。

## 這支的由來：**一份綠燈只在量它的那個人的殼裡成立**

2026-09-21：我報「L0 綠／L1 紅／L2 綠」，B 在同一棵樹上跑到**三題全紅**。
差別只有一個 —— **我每次下指令都前置了 `PYTHONIOENCODING=utf-8`，而 B 沒有。**

```
python -m pytest tests/test_tender_startup_log_...py    → 3 failed
PYTHONUTF8=1 python -m pytest （同一棵樹、同一個指令）   → 3 passed
```

🔑 **`subprocess.run(..., encoding="utf-8")` 設的是「父行程怎麼解碼」。
子行程的 `sys.stdout` 編碼由「子行程自己的環境」決定。** 兩者完全無關，
而它們的名字讓人以為是同一件事。

⇒ 在 ANSI code page 不是 UTF-8 的機器上（這台是 cp932），子行程一旦印出中文，
`print` 當場丟 `UnicodeEncodeError`、結束碼 1，而**父行程看到的是「子行程失敗了」**。

## ⚠️ 而我的診斷訊息自己就是引爆點

真正炸掉的**不是** `import main`，是我為了讓失敗訊息好讀而寫的
`json.dumps(..., ensure_ascii=False)` 那一行 —— 它印的是收集到的中文 log。
（`TOTAL=`／`HITS=` 兩行純 ASCII 都印出來了，證明 `import main` 完整跑完。）

> ☠️ **一個只在失敗時才會執行的診斷輸出，自己把成功變成了失敗。**
> 而它的錯誤訊息指向 `UnicodeEncodeError`，看起來像是被測對象的問題。

⇒ 兩道獨立的防線，**刻意不只做一道**：

1. **`utf8_env()`** —— 子行程的編碼**明著設**，不從跑測試的人那裡繼承。
2. **跨行程的資料一律 ASCII**（`ensure_ascii=True`，也就是預設）——
   **就算第 1 道哪天失效，診斷輸出也不會是引爆點。**
   🔑 **傳輸用 ASCII，顯示是讀的人的事**：父行程解回來之後怎麼呈現，
   由父行程自己的編碼決定，而那是 pytest 的問題不是我們的。

## 📌 為什麼要有這個「家」

我上一輪才把 21 個 e2e 檔各自挑埠的邏輯收進 `_ports.py`，理由是
**「bug 的家從 21 個變成 1 個」**。而同一天我又寫了四個各自 spawn 子行程的
harness，**沒有一個設環境** —— 只有一個（`test_pytest_guards`）碰巧設了。
⇒ **修好一個實例不等於認得那個模式**；這一支就是把模式收起來。
"""
import os
import subprocess
import sys

#: 子行程一律用 UTF-8，兩個變數都給。
#: `PYTHONUTF8=1` 開 UTF-8 模式（stdio ＋ 檔名編碼）；
#: `PYTHONIOENCODING` 只管 stdio —— 舊版 Python 沒有前者，後者是保險。
_FORCE_UTF8 = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def utf8_env(**extra):
    """回一份子行程用的環境：繼承目前的，再**明著**壓上 UTF-8 設定。

    `extra` 裡的值優先（要刪掉某個變數請傳 `None`）。
    """
    env = {**os.environ, **_FORCE_UTF8}
    for key, value in extra.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def run_python(args, *, cwd, timeout=240, env=None, **extra_env):
    """跑 `python <args>`，回 `CompletedProcess`。

    ⚠️ `encoding="utf-8"` 與 `env` 裡的 `PYTHONUTF8` **兩個都要**，
    它們管的是相反的方向：前者是父行程怎麼**解碼**，後者是子行程怎麼**編碼**。
    只設前者就是這一支存在的原因。
    """
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=env if env is not None else utf8_env(**extra_env),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout,
    )
