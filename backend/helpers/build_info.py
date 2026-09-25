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
from core import paths as _paths
_BUILD_FILE = _paths.BUILD_COMMIT_FILE

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
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_GIT_TIMEOUT)
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


#: `BR4`（2026-09-23）：`stale` 原本比對兩個 SHA 是否相等，而這個 repo
#: **四個視窗持續在提交**（今天多數是純 `.md`）⇒ 重啟後幾分鐘內 SHA 必然
#: 又不相等 ⇒ 那個判準在這個環境裡**永遠是紅的**，而使用者因此不敢驗證：
#: 「執行中的版本落後」讀起來像「你要驗的東西不在裡面」，
#: 而事實往往是落後的**只有文件**，程式碼跟使用者要驗的一模一樣。
#: ⇒ 判準改成「有沒有 commit **動到 backend/ 或 frontend/**」——
#: 純文件／規格的提交不算落後（前端本來就每次讀磁碟，不受影響）。
#: ⚠️ **`:/` 前綴不可省** —— `cwd` 是 `backend/helpers/`，沒有它的話
#:    `git log` 把路徑當成**相對於 cwd**（`backend/helpers/backend`），
#:    不存在的路徑 ⇒ 靜默回空清單（不是錯誤，是 0 命中），
#:    ☠️ 而那個 0 與「真的沒有異動」看起來一模一樣（實測踩過）。
#:    `:/backend` 是 git pathspec 的「錨在 repo 根目錄」寫法，
#:    不管 cwd 在哪一層都指向同一個地方。
_TRACKED_PATHS = (":/backend", ":/frontend")

#: `git log` 一次最多列幾個標題。**列出來是為了讓使用者自己判斷**
#: 「我要驗的那件事在不在裡面」，不是要他讀完整份異動記錄。
_MAX_TITLES = 8


def _behind_code(old_sha, new_sha):
    """`old_sha..new_sha` 之間，有幾個 commit 動到 `backend/`／`frontend/`，
    以及它們的標題（新到舊）。回 `(count, titles, why_unavailable)`。

    ⚠️ **只回「不可得」不回「假裝算得出來」**——兩個 SHA 有任何一個空、
       或 `git log` 本身失敗（正式機沒有 `.git`、兩者無共同祖先等），
       一律 `(None, [], 原因)`，不要讓呼叫端把 `None` 誤讀成 0。

    ⚠️ **兩個實測踩過的坑，都在寫這一支的當下抓到**：
    ```
    ① pathspec 不加 `:/` 前綴  cwd 在 backend/helpers/，git 把
                              "backend"／"frontend" 當成**相對 cwd**的路徑
                              ⇒ 不存在 ⇒ **靜默回 0 命中**，不是錯誤
                              （見 `_TRACKED_PATHS` 的註解）
    ② subprocess 不給 encoding  Windows 預設用系統 locale（cp932）解碼，
                              commit 標題含中文 ⇒ `UnicodeDecodeError`
                              **在讀取執行緒裡丟出**，不會被這裡的
                              `except Exception` 接住 —— 症狀是 count 回 0
                              而 stderr 印一段執行緒例外，看起來像別的地方壞了
    ```
    兩者都是「回應正常、內容是空的」——與〈會截斷的指令不可以當事實來源〉
    同一個家族：失敗不會報錯，只會讓觀測到的東西比真的少。
    """
    if not old_sha or not new_sha:
        return None, [], "SHA 不可得"
    if old_sha == new_sha:
        return 0, [], None
    try:
        r = subprocess.run(
            ["git", "log", "--format=%s", "%s..%s" % (old_sha, new_sha),
             "--", *_TRACKED_PATHS],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_GIT_TIMEOUT)
    except FileNotFoundError:
        return None, [], "git 不在 PATH 上"
    except subprocess.TimeoutExpired:
        return None, [], "git 逾時"
    except Exception as exc:                                 # noqa: BLE001
        return None, [], "git 失敗：%s" % type(exc).__name__
    if r.returncode != 0:
        # ⚠️ 常見成因：兩個 SHA 不在同一條歷史線上（例如強制推送、或 SHA
        #    其中一個來自 `.build_commit`、不是這個 repo 的祖先）。
        return None, [], "git log 回 %s：%s" % (
            r.returncode, (r.stderr or "").strip()[:120])
    titles = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    return len(titles), titles[:_MAX_TITLES], None


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
    """給端點與啟動 log 用的一包。**任何一步失敗都不丟例外。**

    ## 🔴 `BR4`（2026-09-23）：`stale` 的語意改了

    ```
    原本   commit != disk_commit（HEAD 不相等）
    現在   behind_count > 0（disk_commit 比 commit 多出**動到程式碼**的 commit）
    ```
    這個 repo 四個視窗持續在提交（多數是純 `.md`）⇒ 「HEAD 不相等」在這裡
    幾乎永遠成立，而使用者要問的其實是「**我要驗的那件事在不在我這一版裡**」，
    不是「HEAD 有沒有動過」。純文件／規格的提交不影響這個問題。
    ⚠️ 呼叫端若還在照舊語意讀 `stale`（HEAD 是否相等），**要重讀這一段**——
       兩個 SHA 不同、而 `stale` 是 `False`，是這一版之後**合法且常見**的狀態。
    """
    disk, disk_src = resolve_commit()
    behind_count, behind_titles, behind_why = _behind_code(_START_COMMIT, disk)
    stale = None if behind_count is None else (behind_count > 0)
    return {
        "commit": _START_COMMIT or "",
        "commit_short": (_START_COMMIT or "")[:7],
        "commit_source": _START_SOURCE,
        "disk_commit": disk or "",
        "disk_commit_short": (disk or "")[:7],
        "disk_commit_source": disk_src,
        # 🔴 `None` ＝ **算不出來**（兩個 SHA 有一個不可得、或不在同一條
        #    歷史線上），不是「沒有過期」。
        #    ☠️ 把它當成 False 的話，畫面會在「不知道」的時候說「是最新的」。
        "stale": stale,
        # 🔑 有幾個 commit 動到 `backend/`／`frontend/`（不含純文件／規格），
        #    以及它們的標題（新到舊，最多 8 條）——讓使用者**自己判斷**
        #    「我要驗的東西在不在裡面」，不必來問任何人。
        "behindCount": behind_count,
        "behindTitles": behind_titles,
        "behindUnavailableReason": behind_why,
        "started_at": _STARTED_AT.isoformat(timespec="seconds"),
        "reload": _RELOAD,
    }


def startup_line():
    """啟動時印的那一行。**拿不到就寫「不可得」，不要猜。**

    ☠️ 用 mtime 或 `version_manifest.json` 推的話，它會在**最需要它的時候**
       給出一個看起來合理的錯答案 —— 而那比沒有這一行更糟。
    """
    info = build_info()
    tail = ""
    if info["stale"]:
        tail = ("　⚠️ 磁碟上是 %s，落後 %d 個動到程式碼的 commit"
                % (info["disk_commit_short"], info["behindCount"] or 0))
    return ("MOTRIX 啟動：commit %s（來源 %s）／時間 %s／reload %s%s"
            % (info["commit_short"] or "不可得", info["commit_source"],
               info["started_at"],
               {True: "開", False: "關", None: "不可得"}[info["reload"]],
               tail))
