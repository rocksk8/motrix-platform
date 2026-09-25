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


def missing_helper_imports(src, helpers):
    """這個檔用了哪些共用 helper 卻沒有 import。回**名字**的排序清單。

    ⚙️ 抽成吃「原始碼字串」的函式，是為了讓正對照
    （`test_the_missing_import_check_really_fires`）走**同一條量測路徑** ——
    另外寫一份判斷式的話，量測裝置壞掉時誘餌照樣會亮
    （〈盤點工具的正對照〉：正對照要與受測對象是同一種寫法）。
    """
    import ast

    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update((a.asname or a.name).split(".")[0]
                            for a in node.names)
    own = {n.name for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # 🔴 **裸名呼叫**才算用到：`I.identity_lines(...)` 是屬性存取，
    #    它的 import 是 `import _pdf_identity as I`，沒有漏任何東西。
    #    ⚠️ 而 docstring／註解裡的 `helper()` 根本不是 `ast.Call` ⇒ 自然不會命中。
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return sorted(n for n in called & set(helpers)
                  if n not in imported and n not in own)


def test_every_file_that_uses_a_shared_helper_also_imports_it():
    """🔴 用到 `tests/_*.py` 的東西，就必須在**同一個檔**裡 import 它。

    ## 這一題的來歷：我改了五個檔、只驗了四個

    2026-09-21 我把五個 spawn 點收攏到 `_subproc.py`，
    其中 `test_tender_notify`（S5）**改了呼叫點而沒加 import**。
    ⚠️ **pytest 的 collect 抓不到它** —— `NameError` 在函式主體裡，
    只有那一支測試真的跑起來才會炸。
    ⇒ 它安靜地進了 commit，**在全量回歸跑到第 1278 題時才紅**。

    🔑 而真正的成因不是「忘了一行 import」，是
    **我的驗證範圍是憑記憶列的，不是從改動清單推的** ——
    我改了五個檔，然後跑了「我記得改過的那四個」。

    📌 順帶一個更毒的細節：我先前量過 `test_tender_notify` 在零環境變數下
    「32 passed」，而**那次量測發生在我改它之前**。
    我拿一個舊的綠燈去支持一個新的狀態 —— 就是我半小時前才跟 B 講的
    「**每一個數字都自帶一個會過期的時間戳**」。

    ## ⚠️ 這個檢查很窄，我照實說

    它只比對「`helper(` 這樣的呼叫」與「有沒有 import」。
    換一種寫法（`getattr`、間接呼叫）就繞過去了。
    **但它擋的是那個真的發生過的動作**，而且會隨著共用 helper 變多而一起長。
    （真正的通用解是 pyflakes，而這個環境沒裝，我不為此加相依。）

    ⚠️ **第一版用 regex 找 import，第一跑就誤報**：
    `test_ports_helper` 用的是**跨行的括號 import**，
    而 `import[^\\n]*\\bname\\b` 要求名字跟 `import` 在同一行。
    ⇒ 改成用 `ast` 取 import 名單（那件事 AST 做得精確），
    只有「有沒有被呼叫」還留著用文字找。
    🔑 **兩個子問題不必用同一種工具解** —— 硬要統一的那一邊就是誤報的來源。

    ## 🔴 2026-09-23 更正：**上面那句話是錯的，而誤報就出在留給文字的那一半**

    ```
    regex 掃原始碼 => 命中 test_quote_location_2026_09_22.py:255／:274
                      docstring 裡的 `identity_lines()`
    而真正的呼叫是  I.identity_lines(...)（:259），import 在 :81
    => 報「用了卻沒 import」，而那個檔第 81 行就有 import，單獨跑 30 passed
    ```
    ☠️ 反引號既不是 word char 也不是點 ⇒ `(?<![\w.])` 擋不住它；
    而真正的屬性呼叫反而被正確排除掉了 —— **它把兩邊都判反了**。
    🔑 而最省力的反應是**刪掉那兩行解釋**或補一個用不到的 import ——
      兩種都讓檔案變差，而 `git log` 上看不出來
      （同一天第二次：另一道守門亮在「解釋為什麼不可以藏祖先」的註解上）。
    ⇒ **「程式會做什麼」一律用 `ast`**：呼叫那一半改成數 `ast.Call` 的裸名，
      而不是掃字串。判斷抽成 `missing_helper_imports()`，
      正對照 `test_the_missing_import_check_really_fires` 走**同一條路徑**。
    """
    import re
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    helpers = {}
    for path in sorted(tests_dir.glob("_*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        for name in re.findall(r"^def ([a-z]\w+)", src, re.M):
            helpers[name] = path.name
    assert helpers, "找不到任何共用 helper —— 這個檢查等於沒在檢查"

    problems = []
    for path in sorted(tests_dir.glob("test_*.py")):
        for name in missing_helper_imports(
                path.read_text(encoding="utf-8"), helpers):
            problems.append(
                f"{path.name} 用了 {name}()（來自 {helpers[name]}）卻沒有 import")
    assert not problems, "\n  ".join([""] + problems)


def test_the_missing_import_check_really_fires():
    """⚙️ **正對照：拿一段故意漏 import 的合成來源，它必須亮。**

    🔑 〈盤點工具的正對照〉：要先讓「已知的那一個」亮起來，才有資格說
    「其他檔都沒問題」—— 而上面那一題現在回報 **0 個**。
    ⚠️ 誘餌用**自己寫的合成來源**，不拿別人碼裡的真實案例：
      真實案例修好的那天，正對照就失效了，而**沒有人會發現**。

    ## ☠️ 而第三段是那個誤報的**死亡條件**

    它釘住「只在 docstring／註解裡被提到」**不可以**算成用到 ——
    有人把呼叫偵測換回 regex 掃字串的那一刻，這一題會當場紅。
    🔑 所以它擋的不是今天那一個檔，是**那個寫法**。
    """
    helpers = {"spawn_thing": "_fake.py"}

    # ① 真的漏了 => 要亮
    assert missing_helper_imports(
        "def t():\n    spawn_thing()\n", helpers) == ["spawn_thing"]

    # ② 有 import => 不可以亮
    assert missing_helper_imports(
        "from tests._fake import spawn_thing\n"
        "def t():\n    spawn_thing()\n", helpers) == []

    # ③ 只在 docstring／註解裡被提到 => **不可以亮**（誤報的死亡條件）
    assert missing_helper_imports(
        '"""說明：`spawn_thing()` 掃的是子行程。"""\n'
        "# 另一種寫法是 spawn_thing()\n"
        "def t():\n    pass\n", helpers) == []

    # ④ 透過模組屬性呼叫（`import _fake as F` / `F.spawn_thing()`）=> 不可以亮
    #    這正是 test_quote_location 的形狀。
    assert missing_helper_imports(
        "import _fake as F\n"
        "def t():\n    F.spawn_thing()\n", helpers) == []


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


def test_child_pytest_does_not_inherit_the_build_exclusive_flag(monkeypatch):
    """建包在外層設了獨佔旗標；守門題起的子 pytest 不可繼承（否則只在建包時紅，2026-09-25）。
    題目明著傳入時照樣生效（獨佔鎖的題靠這一點）。"""
    from tests._subproc import utf8_env
    monkeypatch.setenv("MOTRIX_PYTEST_EXCLUSIVE", "1")
    monkeypatch.setenv("MOTRIX_PYTEST_EXCLUSIVE_OWNER", "123")
    env = utf8_env()
    assert "MOTRIX_PYTEST_EXCLUSIVE" not in env and "MOTRIX_PYTEST_EXCLUSIVE_OWNER" not in env
    assert utf8_env(MOTRIX_PYTEST_EXCLUSIVE="1")["MOTRIX_PYTEST_EXCLUSIVE"] == "1"


def test_child_does_not_inherit_the_outer_run_state(monkeypatch):
    """子行程不可以繼承「外層這一次測試執行」的狀態——第三次同一類（2026-09-25）：
    ① 獨佔旗標（8e96f8b0）② PYTEST_XDIST_WORKER（a3044dcc：子 pytest 以為自己是 xdist worker）
    ⇒ 收斂成 utf8_env 預設剔除一整類，不再一個變數一個變數補。題目要測這些時在 extra 明著傳入。"""
    from tests._subproc import utf8_env
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID",
              "PYTEST_CURRENT_TEST", "MOTRIX_E2E_HARDCAP_RUN",
              "MOTRIX_PYTEST_EXCLUSIVE", "MOTRIX_PYTEST_EXCLUSIVE_OWNER"):
        monkeypatch.setenv(k, "x")
    env = utf8_env()
    leaked = sorted(k for k in env if k.startswith("PYTEST_XDIST_") or k in (
        "PYTEST_CURRENT_TEST", "MOTRIX_E2E_HARDCAP_RUN", "MOTRIX_PYTEST_EXCLUSIVE", "MOTRIX_PYTEST_EXCLUSIVE_OWNER"))
    assert not leaked, leaked
    assert utf8_env(PYTEST_XDIST_WORKER="gw9")["PYTEST_XDIST_WORKER"] == "gw9", "明著傳入的要照給"


def _spawns_pytest(tree):
    """AST：有沒有一個呼叫的參數串列裡，連著出現常數 "-m"、"pytest"（真的起子 pytest，不是只在字串裡提到）。"""
    import ast
    for n in ast.walk(tree):
        if isinstance(n, (ast.List, ast.Tuple)):
            vals = [e.value if isinstance(e, ast.Constant) else None for e in n.elts]
            if any(a == "-m" and b == "pytest" for a, b in zip(vals, vals[1:])):
                return True
    return False


def test_every_test_that_spawns_pytest_builds_its_env_with_utf8_env():
    """守門：起子 pytest 的測試一律經過 utf8_env——手拼環境的那一支會各自漏掉下一個新變數。"""
    import ast
    import glob
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for f in sorted(glob.glob(os.path.join(here, "test_*.py"))):
        src = open(f, encoding="utf-8").read()
        if _spawns_pytest(ast.parse(src)) and "utf8_env(" not in src:
            bad.append(os.path.basename(f))
    assert not bad, "這些測試起了子 pytest，但沒有用 tests._subproc.utf8_env 組環境：%s" % bad


def test_the_spawn_detector_sees_what_it_should():
    import ast
    assert _spawns_pytest(ast.parse('subprocess.run([sys.executable, "-m", "pytest", f])'))
    assert _spawns_pytest(ast.parse('run_python(["-m", "pytest", "-q"], cwd=x)'))
    assert not _spawns_pytest(ast.parse('msg = "py -m pytest x -v"'))
