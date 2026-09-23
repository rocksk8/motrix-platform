# -*- coding: utf-8 -*-
"""這個**行程**載入的是哪一份程式碼（`BR1`）。

# 🔴 它回答的問題與 `/api/system/deployed-version` **不是同一個**

```
deployed-version  **磁碟上**被套用成哪一版（apply_update.ps1 寫 .deployed_commit.json）
本模組            **這個行程啟動當下**載入的是哪一版
```
☠️ 而 2026-09-23 的事故正好證明這兩件必須分開：
```
666 的行程  CreationDate 05:56:02，指令沒有 --reload
載入的樹    dd50d2e（05:54）
磁碟上      已經往前 25 個 commit
⇒ **使用者在瀏覽器上一個都沒看到**，而 git 是對的、全量是綠的、他的畫面是舊的
```
🔑 **「我改好了」與「他看得到」之間有一個沒有人在看的間隔，而兩邊都不會報錯。**

# 🔴 所以真正有用的不是「印出一個 SHA」，是**兩個 SHA 的差**

```
commit       行程啟動當下抓到的（**import 時定住**）
disk_commit  **這次請求當下**再抓一次
stale        兩個都拿得到而不相等 => 磁碟上比較新 => **要重新啟動**
```
☠️ 只印 `commit` 的話，看到的人還是得自己去比對 —— **而那正是今天沒有人做的那一步**。

# ⚠️ 這一支**不可以變成新的失敗理由**

取版本是**診斷**，不是功能。任何一步失敗都回「不可得」，
☠️ 讓一個診斷端點把主功能拖下水，是拿一個小問題換一個大問題。
⇒ 每一條路徑都包在 `try` 裡，而**不吞掉原因**：回傳裡說得出「為什麼不可得」。
"""
import datetime as _dt
import json
import os
import subprocess
import sys

#: 打包時寫進出貨包的 SHA 檔。**出貨包裡沒有 `.git`** ⇒ 正式機只能靠它。
#: ⚠️ 而它**不是** `.deployed_commit.json`：那一份是 `apply_update.ps1` 寫的
#:    「磁碟上被套用成什麼」，這一份是「這份程式碼是從哪個 commit 打包出來的」。
_BUILD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", ".build_commit")

#: `git` 不在 PATH 上是**正常情況不是例外**（正式機很可能就是）。
_GIT_TIMEOUT = 5


def _from_file():
    """讀打包時寫下的 SHA。回 `(sha, 來源說明)`，讀不到回 `(None, 原因)`。"""
    try:
        with open(_BUILD_FILE, encoding="utf-8-sig") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        return None, "沒有 .build_commit（開發機正常）"
    except Exception as exc:                                 # noqa: BLE001
        return None, "讀 .build_commit 失敗：%s" % type(exc).__name__
    # ⚙️ 既接受純 SHA，也接受 JSON —— 打包腳本日後想多寫幾個欄位不必改這裡。
    if raw.startswith("{"):
        try:
            raw = (json.loads(raw) or {}).get("commit") or ""
        except ValueError:
            return None, ".build_commit 不是合法 JSON"
    raw = raw.strip()
    return (raw, ".build_commit") if raw else (None, ".build_commit 是空的")


def _from_git():
    """`git rev-parse HEAD`。回 `(sha, 來源說明)`。

    ⚠️ **用 `git rev-parse` 不要自己讀 `.git/HEAD`** —— 那個檔在 detached、
       packed-ref、worktree 三種情況下各長不一樣，自己解析會在其中一種出錯，
       ☠️ 而出錯的樣子是「回了一個看起來像 SHA 的錯答案」。
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=_GIT_TIMEOUT)
    except FileNotFoundError:
        return None, "git 不在 PATH 上"
    except subprocess.TimeoutExpired:
        return None, "git 逾時"
    except Exception as exc:                                 # noqa: BLE001
        return None, "git 失敗：%s" % type(exc).__name__
    sha = (r.stdout or "").strip()
    if r.returncode != 0 or len(sha) < 7:
        return None, "git 回 %s" % r.returncode
    return sha, "git"


def resolve_commit():
    """現在**磁碟上**是哪一個 commit。回 `(sha 或 None, 來源說明)`。

    順序：出貨包的 `.build_commit` 優先，其次 `git`。
    📌 順序這樣排的理由：正式機**沒有 `.git`**，而開發機兩者都有，
       而開發機上 `git` 才是真的（`.build_commit` 是上一次打包留下的）。
    ⚠️ ⇒ 有 `.git` 的時候 `git` 應該贏 —— 所以先試 `git`，`.build_commit` 當退路。
    """
    sha, why = _from_git()
    if sha:
        return sha, why
    sha2, why2 = _from_file()
    if sha2:
        return sha2, why2
    return None, "%s；%s" % (why, why2)


def _reload_flag():
    """這個行程是不是用 `--reload` 起來的。回 `True`／`False`／`None`（不可得）。

    ## 🔴 `None` 是一個**真的答案**，不是「查不到就算了」

    這裡讀的是**我們自己的 argv**，而 argv **不一定提到這件事**：
    ```
    uvicorn CLI 起的（restart.bat／start_server.ps1／nohup+bash）
        argv 有 "uvicorn" 與那些旗標  => argv **是**答案
    程式裡 uvicorn.run() 起的
        argv **完全不提 reload**      => 回 False 是**編的**
    ```
    ☠️ ⇒ 一個觀測來源，要先問「**它在什麼情況下根本不會提到這件事**」——
       那種情況下的「沒提到」會被讀成「否」。
    🔑 與 `stale` 那一格同一條規則：**不知道的時候不可以給人保證。**
    """
    try:
        argv = list(sys.argv or [])
    except Exception:                                        # noqa: BLE001
        return None
    # ⚙️ 只有當 **uvicorn 本身就是被執行的那個程式**時，argv 才有資格回 False。
    #    ⚠️ 判「argv 裡有沒有 uvicorn 這個字」**太寬**：
    #       `python -c "import uvicorn; uvicorn.run(...)"` 也含那個字，
    #       而那正是 argv **不提 reload** 的那一種 ⇒ 會回一個編的 False。
    #    ⇒ 比對的是**程式名**（`uvicorn` ／ `uvicorn.exe` ／ `-m uvicorn`）。
    prog = os.path.basename(str(argv[0])).lower() if argv else ""
    dash_m = len(argv) >= 3 and str(argv[1]) == "-m" and str(argv[2]) == "uvicorn"
    if prog not in ("uvicorn", "uvicorn.exe") and not dash_m:
        return None
    return "--reload" in [str(a) for a in argv]


# ── 行程啟動當下定住 ─────────────────────────────────────────────────
#
# 🔑 **在 import 時算**，不是每次請求算 —— 這一格要回答的是
#    「這個行程載入的是什麼」，而那在啟動之後就不會再變了
#    （用 `--reload` 的話模組會重新載入 ⇒ 這裡也跟著更新，那是對的）。
_STARTED_AT = _dt.datetime.now()
_START_COMMIT, _START_SOURCE = resolve_commit()
_RELOAD = _reload_flag()


def build_info():
    """給端點與啟動 log 用的一包。**任何一步失敗都不丟例外。**"""
    disk, disk_src = resolve_commit()
    stale = None
    if _START_COMMIT and disk:
        stale = (_START_COMMIT != disk)
    return {
        "commit": _START_COMMIT or "",
        "commit_short": (_START_COMMIT or "")[:7],
        "commit_source": _START_SOURCE,
        "disk_commit": disk or "",
        "disk_commit_short": (disk or "")[:7],
        "disk_commit_source": disk_src,
        # 🔴 `None` ＝ **兩個 SHA 裡至少一個不可得**，不是「沒有過期」。
        #    ☠️ 把它當成 False 的話，畫面會在「不知道」的時候說「是最新的」。
        "stale": stale,
        "started_at": _STARTED_AT.isoformat(timespec="seconds"),
        "reload": _RELOAD,
    }


def startup_line():
    """啟動時印的那一行。**拿不到就寫「不可得」，不要猜。**

    ☠️ 用 mtime 或 `version_manifest.json` 推的話，它會在**最需要它的時候**
       給出一個看起來合理的錯答案 —— 而那比沒有這一行更糟。
    """
    info = build_info()
    return ("MOTRIX 啟動：commit %s（來源 %s）／時間 %s／reload %s%s"
            % (info["commit_short"] or "不可得", info["commit_source"],
               info["started_at"],
               {True: "開", False: "關", None: "不可得"}[info["reload"]],
               ("　⚠️ 磁碟上是 %s —— **這個行程載入的是舊的**"
                % info["disk_commit_short"]) if info["stale"] else ""))
