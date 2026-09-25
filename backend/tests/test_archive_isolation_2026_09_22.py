"""§12 BK19 · 測試期間不可以碰到真的雲端硬碟。

---

# ☠️ 這一條的代價落在 repo 之外

`BK11` 結案（`1593d8a`）：2026-08-30／08-31／09-03 三天的雲端每日備份是**空資料庫**。
成因是 `conftest.py` 的雲端隔離**死碼**：

```
patch 釘在五個大寫常數上     _ARCHIVE_BASE / _REALTIME_DIR / _WEEKLY_DIR / …
而 archive.py 早就改成函式   _archive_base() —— 動態掃描磁碟機代號
⇒ patch 什麼都沒隔離到
⇒ pytest 跑的時候 archive.DB_PATH 指向 tmp 空庫，而 _archive_base() 真的掃到 G:
⇒ _snapshot_sqlite() 把那份空庫覆寫進雲端當天的資料夾
```
✅ 已由 `a55fe26`（2026-09-07）修好（改成直接 patch 那個函式本身），
而三個壞掉的日期**全部早於它**。

## 🔑 它跟〈守門守的對象被搬走〉是同一個形狀

**隔離寫了、隔離的對象被搬走了（常數 → 函式）、而測試全綠。**
☠️ 而這一次全綠的同時，它在寫真實的雲端硬碟 ——
📌 **測試套件沒有任何一處會因此變紅，因為受害者不在 repo 裡。**

---

# ⇒ 所以這道守門不是一題，是一個 autouse 的前置檢查

`conftest.py` 的 `_guard_archive_isolation` 在**每一題開始前**問一次：
**`_archive_base()` 現在指到哪裡？**

⚠️ 判準是「**回傳值在不在 tmp 底下**」，**不是「有沒有寫成功」** ——
☠️ 後者要真的去寫一次才知道，而那正是我們要避免的事。

---

# 📌 而下面這幾題守的是「那道守門自己還活著」

一個 autouse 的檢查若被改壞（或被拿掉），**沒有任何東西會紅** ——
🔑 它的失敗方式跟它要防的東西一模一樣：**安靜。**
"""
import os
import sys
from pathlib import Path

import pytest

# 單獨跑這個檔時 `sys.path` 不含 `tests/`，而 `conftest` 要靠它才 import 得到。
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 一眼就知道不是 tmp 的幾種真實存檔路徑（**只當字串用，絕不去存取**）。
REAL_LOOKING = (
    r"G:\我的雲端硬碟\系統存檔",
    r"H:\我的雲端硬碟\系統存檔",
    r"D:\系統存檔",
    "/mnt/gdrive/系統存檔",
)


def _guard():
    """把 `conftest` 的判斷函式取出來，直接餵字串測試它。"""
    import conftest
    fn = getattr(conftest, "archive_path_is_isolated", None)
    assert fn is not None, (
        "`conftest.py` 缺少 `archive_path_is_isolated()` —— "
        "BK19 的判斷要抽成純函式才測得到（不然只能靠真的去寫一次）。")
    return fn


# ══════════════════════════════════════════════════════════════════════
# BK19 · 正向：現在這一刻，存檔根目錄在 tmp 底下
# ══════════════════════════════════════════════════════════════════════

def test_bk19_the_archive_base_is_inside_tmp_right_now(tmp_path):
    """🔴 BK19：測試期間 `_archive_base()` 必須回一個 tmp 底下的路徑。

    📌 這一題與 `conftest` 裡那個 autouse 檢查**問的是同一句話** ——
    ⚠️ 而它存在的理由是：**autouse 檢查被拿掉時，這一題會紅。**
    🔑 一個只靠 autouse 的守門，它的失敗方式是「安靜」。
    """
    import archive
    base = archive._archive_base()
    assert base, (
        "`_archive_base()` 回空字串 —— 隔離沒有生效，"
        "而正式環境下它會去掃磁碟機代號。")
    assert _guard()(base), (
        f"測試期間的存檔根目錄是 {base!r} —— 它不在 tmp 底下。\n"
        "☠️ 那正是 2026-08-30／08-31／09-03 三份空備份的成因：\n"
        "   DB 指向 tmp 空庫，而存檔根目錄指向真的雲端硬碟。"
    )


def test_bk19_every_archive_subdirectory_stays_inside_tmp():
    """🔴 BK19：**每一個**衍生目錄都要跟著在 tmp 底下，不是只有根目錄。

    ☠️ `_realtime_dir()`／`_daily_dir()`／`_weekly_dir()`／`_monthly_dir()`
    各自算自己的路徑。**當年壞掉的就是「只 patch 了其中幾個」。**
    🔑 判準用「全部」不用「我想得到的那幾個」——
    📌 而清單從 `archive` 模組**當場取**，不手寫：
    **手寫清單漏掉的永遠是後來才加的那一個。**
    """
    import archive

    getters = [name for name in dir(archive)
               if name.endswith("_dir") and name.startswith("_")
               and callable(getattr(archive, name))]
    assert getters, "`archive` 裡找不到任何 `_*_dir()` —— 這個檔的結構變了"

    guard = _guard()
    escaped = []
    for name in sorted(getters):
        try:
            value = getattr(archive, name)()
        except TypeError:
            continue                      # 需要參數的（例如 PDF 分類）另計
        if value and not guard(value):
            escaped.append(f"{name}() -> {value}")
    assert not escaped, (
        "這些存檔目錄跑到 tmp 外面了：\n  " + "\n  ".join(escaped)
        + "\n☠️ 測試會把資料寫到那裡，而那裡可能是使用者的雲端硬碟。")


# ══════════════════════════════════════════════════════════════════════
# BK19 反向控制 · 不碰 G:，只餵字串
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", REAL_LOOKING)
def test_bk19_a_real_looking_path_is_rejected(path):
    """🔴🔴 BK19 反向控制：**真實存檔路徑要被判定為「沒有隔離」。**

    ☠️ 少了這一題，一個 `def archive_path_is_isolated(p): return True`
    會讓上面兩題全綠 —— **而那正是當年那個 patch 的狀態：寫了，而沒有作用。**

    ⚠️ 這裡**只把路徑當字串用，絕不去存取它** ——
    🔑 A 的提醒：驗的是「回傳值在不在 tmp 底下」，
    **不是「有沒有寫成功」** —— 後者要真的寫一次才知道，
    而那正是這一節要避免的事。
    """
    assert _guard()(path) is False, (
        f"{path!r} 被判定成「已隔離」—— 這道守門放得過真的雲端硬碟。")


def test_bk19_an_empty_or_missing_path_is_rejected():
    """🔴 BK19：空字串／`None` 也要被拒。

    🔑 〈null 不等於 0〉的鄰居：**「我不知道它指到哪」不可以被當成「它是安全的」。**
    ☠️ 回空字串的情況真的會發生 —— `_archive_base()` 掃不到任何磁碟機時就回 `""`。
    """
    guard = _guard()
    for bad in ("", None):
        assert guard(bad) is False, f"{bad!r} 被判定成已隔離 —— fail open 了。"


def test_bk19_the_guard_actually_runs_before_every_test():
    """📏 量尺：`conftest` 裡那個 autouse 檢查要**存在且是 autouse**。

    ☠️ 它被改成非 autouse（或被刪掉）時，**沒有任何東西會紅** ——
    🔑 它的失敗方式跟它要防的東西一模一樣：**安靜**。
    📌 所以這一題直接讀那個 fixture 的旗標，不靠「它應該有跑吧」。
    """
    import conftest
    fixture = getattr(conftest, "_guard_archive_isolation", None)
    assert fixture is not None, (
        "`conftest.py` 裡沒有 `_guard_archive_isolation` —— BK19 的守門不存在。")
    # ⚠️ 旗標放在哪個屬性上是 **pytest 版本相依**的：
    #    舊版 `_pytestfixturefunction`、目前（9.x）是 `_fixture_function_marker`。
    # ☠️ 只認一個名字的話，pytest 一升版這一題就會紅在一個與題目無關的理由上，
    #    而更糟的是**反過來**：若寫成 `getattr(..., None)` 然後 `if marker:` 略過，
    #    它會在找不到旗標時**安靜地通過** —— 那就是它要防的那種失敗。
    marker = (getattr(fixture, "_fixture_function_marker", None)
              or getattr(fixture, "_pytestfixturefunction", None))
    assert marker is not None, (
        "讀不到 `_guard_archive_isolation` 的 fixture 旗標 —— "
        f"pytest 的屬性名可能變了（現有：{[a for a in dir(fixture) if 'fixture' in a]}）。"
        "☠️ 這一題**不可以因此跳過**：讀不到就等於沒有驗。")
    assert marker.autouse is True, (
        "`_guard_archive_isolation` 不是 autouse —— 它只會在有人記得要用時才跑，"
        "而「記得」正是這一條要消滅的東西。")


def test_bk19_a_tmp_path_is_accepted(tmp_path):
    """📏 正對照：tmp 底下的路徑要被接受。

    ☠️ 少了它，一個「一律回 False」的判斷會讓所有反向控制綠 ——
    而那會讓整個測試套件在 setup 就炸掉，**紅得跟真的出事一樣**。
    """
    assert _guard()(str(tmp_path)) is True, (
        f"{tmp_path} 是 pytest 的 tmp 目錄，卻被判定成沒有隔離。")
    assert _guard()(os.path.join(str(tmp_path), "archive_base", "月備份")) is True


# ══════════════════════════════════════════════════════════════════════
# BK19（第二版）· 斷言對象是「實際寫到哪裡」，不是某個函式的回傳值
# ══════════════════════════════════════════════════════════════════════
#
# D 查證推翻了第一版的形狀：釘 `_archive_base()` 的回傳值只守得住一條，
# 另有三條繞得過去（S3 直傳／`main.py` 模組層建目錄／逐一 patch 的常數）。
# ⇒ `conftest` 改成把 `open`／`os.makedirs`／`shutil.copy*` 包起來，
#   看**實際落點**。

#: 2026-09-22 用 `MOTRIX_BK19_REPORT=1` 實跑 60 題量到的越界寫入。
#: 🔑 **這張表是量出來的，不是想出來的** —— 先量再訂判準。
#: ⚠️ 每一列都是一個真的隔離缺口：測試在**專案目錄裡**建檔。
KNOWN_REPO_WRITES = (
    "uploads/_demo_uploads",
    "_demo_case_closing_pdf_archive",
    "_demo_contractor_voucher_pdf_archive",
    "_demo_invoice_voucher_pdf_archive",
    "_demo_payment_request_pdf_archive",
    "_demo_payslip_archive",
    "_demo_pdf_archive",
    "_demo_shipping_pdf_archive",
    "export_archive",
    ".initial_admin_credentials.txt",
    # 2026-09-25（B）：與上一列同一類（demo 帳號的初始密碼檔，路徑見 core/paths.py INITIAL_DEMO_CREDENTIALS）。
    #   不是新缺口：以前看不到，是因為本檔的 `import conftest` 拿到空的複本（見 test_bk19_the_write_guard_… 的註記）。
    ".initial_demo_credentials.txt",
)

#: pytest／Python 自己的，不算缺口。
BENIGN = ("__pycache__",)


def test_bk19_the_write_guard_catches_a_real_write(tmp_path):
    """🔴🔴 BK19 反向控制：**真的去寫一次 repo 外的路徑，守門要擋下來。**

    ## ⚠️ A 指名的那一點：反向控制要選一支**真的會寫檔**的測試

    ☠️ 拿掉 patch 只有在那支測試**真的觸發一次寫入**時才會紅 ——
    否則反向控制本身永遠綠，**那就變成〈防著不存在問題的測試永遠是綠的〉**。
    ⇒ 📌 所以這一題自己發動一次寫入，不依賴別人剛好有寫。

    ## 🔑 而它寫的是一個**不存在的磁碟機**，不是 G:

    要證明的是「守門會攔」，不是「那個位置寫得進去」。
    ☠️ 拿 `G:` 當目標的話，這一題自己就成了它要防的那件事。
    """
    import os as _os

    target = _os.path.join("Q:\\", "bk19_should_never_be_created", "x")
    with pytest.raises(AssertionError, match="BK19"):
        _os.makedirs(target, exist_ok=True)

    with pytest.raises(AssertionError, match="BK19"):
        open(_os.path.join("Q:\\", "bk19_file.txt"), "w")

    # 📏 正對照：tmp 底下的同樣動作要照常成功。
    ok = tmp_path / "nested" / "dir"
    _os.makedirs(ok, exist_ok=True)
    assert ok.is_dir(), "tmp 底下的 makedirs 被擋掉了 —— 守門太寬，會擋住所有測試"

    # 🧹 這一題故意寫的兩筆是反向控制，不是缺口 ⇒ 驗完從紀錄裡拿掉，免得 test_bk19_nothing_new_… 把它們當成新增。
    # 🔴 2026-09-25（B）：以前不需要這一步，是因為那一題的 `import conftest` 拿到的是**另一份空的複本**
    #    （conftest 在 tests/ 時註冊名是 tests.conftest，`import conftest` 另外載入一份）⇒ 它一直是假綠燈。
    #    conftest 上移到 backend/ 之後拿到的是真正在記錄的那一份，這兩筆才看得見。
    import conftest
    for probe in ("makedirs: " + target, "open: " + _os.path.join("Q:\\", "bk19_file.txt")):
        assert probe in conftest._BK19_WRITES, "守門沒有記下反向控制的寫入：%r" % probe
        conftest._BK19_WRITES.discard(probe)


def test_bk19_nothing_new_was_written_outside_tmp():
    """🔴 BK19：除了已登記的那 10 個缺口，不可以再多出新的 repo 內越界寫入。

    ## 📌 這 10 個是量出來的，而它們是真的缺口

    測試會在**專案目錄裡**建 `_demo_*_archive/`、`export_archive/`
    與 `.initial_admin_credentials.txt`。
    ⚠️ 比 `G:` 那一類輕，**而它們是同一個成因**：
    隔離寫在 `client` fixture 裡，而這些路徑各自算自己的位置。

    ## ⚠️ 這一題是「只擋新增」，不是「把 10 個補完」

    🔑 〈基準推進死結〉：要求零缺口的話，這道守門會每次 FAIL，
    ☠️ 而「只在零 FAIL 才推進」會讓它永遠推不動 —— MSP 踩過。
    📌 ⇒ 存量登記在 `KNOWN_REPO_WRITES`，**新增的才紅**。

    ⚠️ 而它有一個**順序相依**要講清楚：它只看得到「在它之前跑過的題」
    寫了什麼。全量跑時涵蓋得最完整，單獨跑這個檔時幾乎看不到東西 ——
    ☠️ **所以它綠不代表沒有缺口，只代表「目前為止沒有新的」。**
    """
    import conftest

    recorded = getattr(conftest, "_BK19_WRITES", None)
    assert recorded is not None, "`conftest` 裡沒有 `_BK19_WRITES` —— 守門不存在"

    unexpected = []
    for line in sorted(recorded):
        path = line.split(": ", 1)[-1].replace("\\", "/")
        if any(b in path for b in BENIGN):
            continue
        if any(known.replace("\\", "/") in path for known in KNOWN_REPO_WRITES):
            continue
        unexpected.append(line)
    assert not unexpected, (
        "測試寫到了 tmp 之外、而且不在已登記的存量清單裡：\n  "
        + "\n  ".join(unexpected)
        + "\n⇒ 要嘛把那個路徑導進 tmp，要嘛登記進 `KNOWN_REPO_WRITES` 並寫出理由。")


# ══════════════════════════════════════════════════════════════════════
# BK20 · 模組層副作用在 patch 之前就發生了
# ══════════════════════════════════════════════════════════════════════

def test_bk20_main_does_not_create_directories_at_import_time():
    """🔴🔴 BK20：`main.py` 不可以在**模組層**建目錄。

    ```
    main.py:517   _ensure_archive_dirs()      ← 模組層，不在函式內
    ```
    ☠️ 任何在 conftest patch 生效前 `import main` 的路徑，
    **會在真實磁碟上建目錄**。

    ## 🔑 這是 `BK19` 抓不到的那一條，而理由是**時序**

    `BK19` 的守門裝在 fixture 裡 ⇒ 它跑的時候，**損害已經造成**。
    📌 〈防護的副作用落在盲側〉：
    **一道裝在事後的守門，對「事前」那一段完全沒有意見。**

    ## ⚠️ 判準：釘在 **import 邊界**，用 AST 讀而不是真的 import

    ☠️ 真的 `import main` 來驗的話，**這一題自己就會建那些目錄** ——
    🔑 一個為了證明「不該發生」而讓它發生一次的測試。
    ⇒ 用 AST 看「模組層有沒有呼叫它」。
    """
    import ast

    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in tree.body:                      # ⚠️ 只看**模組層**，不 walk
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fn = node.value.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name and ("ensure" in name and "dir" in name.lower()
                         or name == "_ensure_archive_dirs"):
                offenders.append(f"main.py:{node.lineno} {name}()")
    assert not offenders, (
        "這些建目錄的呼叫在 `main.py` 的模組層執行：\n  " + "\n  ".join(offenders)
        + "\n☠️ conftest 的 patch 還沒生效，它們就已經在真實磁碟上建好目錄了。\n"
          "⇒ 改成延遲執行（第一次真的要用的時候），或搬進啟動事件處理器。")
