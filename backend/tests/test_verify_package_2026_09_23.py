# -*- coding: utf-8 -*-
"""`backend/tools/verify_package.py`：打包守門自己的守門。

## ⚠️ 編號：**`VP1`–`VP4`（`§50c`），而它們一開始是沒有編號的**

D 一開始在訊息裡發了 `RC1~RC4` 這組編號，**他自己先認了那是缺陷**
（`docs/windows/STATE.md:53` 寫著 D「不裁決、不派工」，而發編號離派工只差一步），
改成只給**事實與接縫**，編號等 A 落進 `SCOPE.md`／`STATE.md`。
⇒ A 已於 `§50c` 發號 **`VP1`–`VP4`**（D 交的內容、A 編號），本檔已改標。
📌 而 A 同時記下：**只有能寫進權威檔的人可以發編號，因為編號是規格的形狀**
   —— 一則帶編號的訊息，**比不帶編號的更容易被誤當成已下達**。
🔑 〈要求寫在訊息裡等於沒下達〉：`grep -rn "RC1\\|RC4" docs/ backend/tests/` 實查 **0 筆**
   ——那四條在 repo 裡一個字都沒有，只存在於一則訊息裡。

## 本檔只寫「接縫存在」的那一項

```
VP1  期望版本必填              ✅ 接縫在（check_db_version :247／argparse :303）⇒ 本檔
VP2  降級要出現在**摘要**      ⚠️ `--allow-unverified-version` **不存在**（grep ⇒ 0）
VP3  髒目錄不髒了 ⇒ 報告作廢   ⚠️ 自我檢驗**整段不存在**
VP4  自測要驗到結束碼路徑      ⚠️ 同上
```
⇒ VP2／VP3／VP4 要的產品面整段不存在 ⇒ 替它們寫題**等於我在替產品訂規格**。
📌 而〈已知的代價 vs 要修的東西〉要求我把這件事寫在檔案裡，不是寫在訊息裡
   ——否則它看起來會像被處理過了。**本檔只有 `VP1`（＋`VP4` 的可寫部分），其餘是欠帳。**

## ⚠️ 兩個會讓這一類題假綠的地雷（D 說今天都真的發生過）

```
1. 測結束碼**不可以接管線** —— `… | tail -8; echo EXIT=$?` 印的是 tail 的結束碼
   ☠️ 方向最壞：它會讓人去修一個**已經好的**東西
2. 斷言要落在**具名的 gate** 上（`R.fail(gate, …)` 的第一個引數）
   ——不要只落在 exit 1（現有 gate 名稱至少 10 種，任何一個存在它都綠），
     也不要落在逐字訊息。**訊息會被潤稿，gate 名稱是結構**（§50d）。
   📌 A 原本在 `§34d` 轉述成「釘逐字訊息」，D 自己更正了，A 已改（錯的那列留著）。
   ⚠️ 而本檔 `VP1` 用的是**差分**不是指名 gate —— 因為那個 gate **還不存在**
      （名字是 B 的）。差分不必先知道它叫什麼，而一樣落在 gate 這一層。
```
"""
import importlib.util
import io
import os
from pathlib import Path

import pytest

_VP_PATH = Path(__file__).resolve().parent.parent / "tools" / "verify_package.py"


def _vp():
    """載入 `verify_package.py`（`main()` 有 `__name__` 守門，import 無副作用）。"""
    assert _VP_PATH.exists(), "找不到 %s" % _VP_PATH
    spec = importlib.util.spec_from_file_location("_verify_package_probe", _VP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: 一份**三源一致**的假 `db.py`：`CURRENT_VERSION` ／ `len(_MIGRATIONS)` ／
#: 最後一筆的 `_mNNN_` 前綴都是 2。
_FAKE_DB = """CURRENT_VERSION = 2

_MIGRATIONS = [
    _m001_first,
    _m002_second,
]
"""

#: 刻意**不一致**的一份（`CURRENT_VERSION` 說 9，而只有 2 筆）——
#: ⚙️ 它是我的 fixture 的**正對照**：證明這個裝置製造得出 FAIL，
#:    而不是「不管餵什麼都 0 個 FAIL」。
_FAKE_DB_INCONSISTENT = _FAKE_DB.replace("CURRENT_VERSION = 2", "CURRENT_VERSION = 9")


def _make_pkg(root, db_src=_FAKE_DB):
    backend = os.path.join(str(root), "backend")
    os.makedirs(backend, exist_ok=True)
    with io.open(os.path.join(backend, "db.py"), "w", encoding="utf-8") as fh:
        fh.write(db_src)
    return str(root)


def _gates(mod, pkg, expect):
    """用一份**乾淨的** `Report` 跑 `check_db_version`，回傳 gate 名稱清單。

    ⚠️ `R` 是模組層的單例 ⇒ 不換掉的話，**前一個案例的 FAIL 會留到下一個**
       （〈假綠燈：測試間共用計數器〉的反面：它會製造假紅燈）。
    """
    old = mod.R
    mod.R = mod.Report()
    try:
        mod.check_db_version(pkg, expect)
        return [g for g, _ in mod.R.fails]
    finally:
        mod.R = old


def test_vp1_a_missing_expected_version_is_a_failure(tmp_path):
    """🔴🔴 `VP1`：**沒有指定「該是哪個版本」時，驗包不可以回 0。**

    ```
    有人驗一個包而忘了帶 --expect-db-version
    ⇒ 報告印「⚠️ 未給 --expect-db-version」
    ⇒ 摘要印「✅ 全部通過」
    ⇒ **EXIT 0**
    ```
    ☠️ **而包裡的 `db.py` 可能是任何版本，沒有人知道。**

    ⚠️ **v1 這裡寫的是「打包腳本呼叫」，那是錯的**（A-2 抓到，那一列留著）：
    ```
    實查   grep verify_package backend/tools/build_deploy_package.ps1   ⇒ 0 處
           A-2 再擴大到全 repo（排除 rollback_snapshots／deploy_packages）
           ⇒ 命中全落在測試檔／它自己的 docstring／docs
           ⇒ **沒有任何流程呼叫它，它是人工執行的**
    ```
    🔑 而缺陷的嚴重度**沒有因此降低，可能更高**：
       自動呼叫寫一次就固定了，**人工每次都要記得帶那個參數**。
    🔴 **但要分清楚**：修好這個 fail-open 讓這道守門**判得對**，
       它不會讓任何東西變安全 —— 因為擋關生效還需要第二個條件：
       **有人跑它**。而「要不要接進打包流程」不在 `VP1`–`VP4` 裡，
       已請 A 發編號。⇒ **看到 `VP1` 已修，不要以為驗包這件事有人在守。**
    🔑 警告是**文字**，而自動化讀的是**結束碼** ——
       〈散文對工具是隱形的〉在這裡是字面上的：那行 `print` 對呼叫端不存在。

    📌 現況（`verify_package.py:268`）：`if expect is None:` 只 `print`，**沒有 `R.fail`**。
    ⚠️ 這是 fail-open，而它與 `P0-00` 是同一個形狀：
       **「新增一條路徑而忘記回報」是預設會發生的事，不是例外。**

    ⚙️ 兩個正對照都在下一題，**而它們必須存在**：
    少了它們，一個「無論如何都 FAIL」的實作會讓這一題全綠，
    而那會讓**每一次打包**都失敗。

    ## ⚠️ 這一題的 v1 **綠得不對**，那一列留著

    ```
    ❌ v1  assert gates                  ← 「有沒有任何 FAIL」
           合成的假包對不上工作樹（假包 v2／工作樹 v92）
           ⇒ `包 vs 工作樹` 這個**無關的 gate 永遠會亮**
           ⇒ 缺陷完全沒修，這一題照樣綠
    ✅ v2  assert without - with_expect   ← 差分
           「不給期望值」比「給了期望值」**多出來的**那些 FAIL
           ⇒ 環境噪音在兩邊都出現，相減之後只剩下缺期望值造成的
    ```
    ☠️ **而 D 在同一則訊息裡就警告過這個地雷**（「斷言要落在具名的 gate 上，
    不要只落在 exit 1 —— 同一支有 8 種以上的 FAIL 來源」），我還是踩進去了。
    🔑 差分比「指名 gate」更適合這裡：**那個 gate 還不存在**（名字是 B 的），
       而差分不必先知道它叫什麼。
    """
    mod = _vp()
    pkg = _make_pkg(tmp_path / "pkg")

    # 🔴 **差分，不是「有沒有 FAIL」** —— 見本題 docstring 末段。
    with_expect = set(_gates(mod, pkg, 2))
    without = set(_gates(mod, pkg, None))
    assert without - with_expect, (
        "沒給 `--expect-db-version`，而它比「給了」多出來的 FAIL 是 0 個 ——\n"
        "☠️ 摘要會印「✅ 全部通過」、結束碼 0、打包全綠出貨，\n"
        "   而包裡的 `db.py` 是哪一版沒有人驗過。\n"
        "🔑 那行 `⚠️ 未給 --expect-db-version` 是**文字**，"
        "而自動化讀的是**結束碼**。\n"
        "📌 接縫：`verify_package.py:268` 的 `if expect is None:` 分支要 `R.fail`。\n"
        "（不給期望值：%s／給了之後：%s）" % (sorted(without), sorted(with_expect)))


def test_vp1_the_version_gate_still_passes_and_still_catches(tmp_path):
    """⚙️ 上一題的**兩個正對照** —— 少了它們，「一律 FAIL」會讓上一題全綠。

    ```
    expect == 包內版本   ⇒ 0 個 FAIL   ← 每一次正常打包都要過
    expect != 包內版本   ⇒ 有 FAIL     ← 它真的在比，不是裝飾
    三源不一致           ⇒ 有 FAIL     ← 我的 fixture 製造得出 FAIL
    ```
    🔑 第三條驗的是**我的觀測裝置**不是產品：
    少了它，一個「`check_db_version` 永遠不 fail」的世界裡，
    上一題會紅（看起來像抓到缺陷），**而紅的原因是它什麼都抓不到**。
    ⚠️ 〈探針與被測對象糾纏〉：測試紅了、訊息指向產品，而壞的是我的裝置。
    """
    mod = _vp()
    pkg = _make_pkg(tmp_path / "ok")

    # ⚠️ **不可以斷言「0 個 FAIL」**：合成的假包對不上工作樹（v2 vs v92）
    #    ⇒ `包 vs 工作樹` 必定亮。要指名到**版本那一格**。
    #    🔑 這就是上一題 v1 綠得不對的同一個來源。
    ok_gates = _gates(mod, pkg, 2)
    assert "db 版本 == 期望值" not in ok_gates, (
        "包內版本 2、期望 2，而版本那一格仍然 FAIL —— "
        "每一次正常的打包都會失敗。（本次 gate：%s）" % sorted(ok_gates))
    assert "db 版本三源一致" not in ok_gates, (
        "三源刻意寫成一致（2／2／`_m002_`）而仍然 FAIL —— **儀器失效**，"
        "這個 fixture 的 FAIL 不能被解讀成缺陷。（本次 gate：%s）" % sorted(ok_gates))

    assert "db 版本 == 期望值" in _gates(mod, pkg, 1), (
        "包內版本 2、期望 1，而沒有 FAIL —— **那個比較沒有在比**。")

    bad = _make_pkg(tmp_path / "bad", _FAKE_DB_INCONSISTENT)
    assert "db 版本三源一致" in _gates(mod, bad, 9), (
        "三源刻意不一致（CURRENT_VERSION=9 而只有 2 筆 migration）而沒有 FAIL ——\n"
        "🔑 **儀器失效**：這個 fixture 製造不出 FAIL，"
        "那上一題的紅就不能被解讀成「抓到缺陷」。")


def test_vp4_the_exit_code_path_is_alive():
    """🔴 `VP4` 的**可寫部分**（主體要等 `VP3` 的自測落地）：`FAIL 收集 → 結束碼 1` 那條路要是活的。

    ⚠️ **這一題是綠著出生的變更偵測，不是今天抓到了什麼。**
    D 給的理由值得留著：
    > 「這正是 `rg6.py` 原版的缺陷（整支沒有 `sys.exit`），
    >   而它在**同一支腳本裡已經復活過一次**（`VP1`）。」

    ```
    掃描器看得見 ＋ FAIL 印在畫面上 ＋ **結束碼 0**  ⇒ 打包照樣過
    ```
    ☠️ 三件事有兩件是對的，而**唯一被自動化讀到的那一件**是錯的。

    📌 自我檢驗那一段（`VP3`／`VP4` 的主體）**整段不存在** ⇒ 那部分是欠帳，
       本題只守「結束碼路徑」本身，**不宣稱守到偵測能力**。
    """
    mod = _vp()

    clean = mod.Report()
    assert clean.finish() == 0, "沒有 FAIL 而結束碼不是 0 ⇒ 每一次打包都會失敗。"

    dirty = mod.Report()
    dirty.fail("測試用 gate", "測試用 detail")
    assert dirty.finish() == 1, (
        "有 FAIL 而 `finish()` 回 0 ——\n"
        "☠️ FAIL 印在畫面上、結束碼是 0 ⇒ **打包照樣過**。\n"
        "🔑 三件事有兩件對，而唯一被自動化讀到的那一件是錯的。")


def test_vp4_the_exit_code_is_actually_the_gate_result():
    """🔴 `VP4` 的另一半：**`finish()` 的回傳值要真的走進 `sys.exit`。**

    ☠️ 上一題證明 `finish()` 算得對，**而算得對與被用到是兩件事**：
    ```
    sys.exit(R.finish())   ✅ 結束碼 ＝ 守門的結論
    R.finish(); sys.exit(0) ☠️ 守門跑了、印了、而結論被丟掉
    ```
    🔑 〈一支接縫寫好了而沒有人呼叫，跟沒有寫是一樣的〉。

    📌 用 AST 不用字串比對：`finish` 在檔裡扮演多種角色
       （定義／呼叫／docstring）⇒ 〈這個字串在檔裡扮演幾種角色？
       答案大於一就不能用 `find`〉。
    """
    import ast as _ast

    tree = _ast.parse(_VP_PATH.read_text(encoding="utf-8"))
    main = next((n for n in _ast.walk(tree)
                 if isinstance(n, _ast.FunctionDef) and n.name == "main"), None)
    assert main is not None, (
        "`verify_package.py` 裡找不到 `main` —— **儀器失效**，不是「路徑正確」。")

    exits = [n for n in _ast.walk(main)
             if isinstance(n, _ast.Call)
             and isinstance(n.func, _ast.Attribute) and n.func.attr == "exit"]
    assert exits, (
        "`main()` 裡一個 `sys.exit` 都沒有 ——\n"
        "☠️ 那正是 `rg6.py` 原版的缺陷：守門跑完、印完，**結束碼永遠是 0**。")

    def uses_finish(call):
        return any(isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                   and n.func.attr == "finish"
                   for a in call.args for n in _ast.walk(a))

    assert any(uses_finish(c) for c in exits), (
        "`main()` 的 `sys.exit` 沒有一個用到 `finish()` 的回傳值 ——\n"
        "☠️ 守門跑了、FAIL 印出來了，**而結論沒有走進結束碼**。\n"
        "🔑 算得對與被用到是兩件事。")


@pytest.mark.parametrize("missing", ["allow_unverified", "self_test"])
def test_vp2_vp3_the_unwritten_items_are_named_not_forgotten(missing):
    """📌 **`VP2`／`VP3`／`VP4` 的主體寫不出來，而我把「為什麼」留成一個會說話的形狀。**

    ⚠️ 這一題**不驗產品**，它驗的是「那三項的接縫仍然不存在」。
    ```
    接縫出現的那一天 ⇒ 這一題會紅 ⇒ 有人被迫回來看那三項欠帳
    ```
    🔑 〈計數器要有落點〉：「日後記得回來補」沒有落點，**這一題就是落點**。
    ☠️ 而它與〈防著不存在問題的測試永遠是綠的〉的差別在方向：
       它不是在防一個不存在的問題，**它是在等一個已知的缺席被填上**。

    ⚠️ 它守不到的：接縫**用別的名字**出現（那一天它不會紅）。
       ⇒ 這是提醒，不是保證。A 發編號之後這一題要換成真的題目。

    ## ⚠️ v2：**比對之前先剝掉註解與字串**

    B 實際踩到了 v1 的假陽性，而且踩了兩次：
    ```
    第一次  它順手把 VP2 的旗標也做了      ⇒ 紅（**正確**，它做過頭了）
    第二次  撤掉之後**還是紅** —— 因為它寫了一段註解解釋
            「那個旗標刻意不做」，而**註解裡寫了那個旗標的名字**
    ```
    ☠️ 字面比對**分不出「實作」與「解釋它不存在的註解」** ——
    🔑 而那正是〈一個寫得好的註解讓一個粗糙的比對產生假陽性〉，
       這次假陽性的受害者是**寫註解的人自己**。

    ⇒ v2 用 `tokenize` 剝掉 `COMMENT` 與 `STRING`，只留下**程式碼識別字**。
    📌 真的做出來時它仍然抓得到：`argparse` 的 `--allow-unverified-version`
       會被讀成 `args.allow_unverified_version`（識別字，不是字串）。
    ⚠️ **不用「除外清單」** —— 那會變成
       〈守門要配反向控制，否則可以靠把東西寫進排除清單變綠〉。
    ⚙️ 而剝完要有**正對照**：一個確定存在的識別字必須還在，
       否則「剝過頭 ⇒ 什麼都找不到 ⇒ 這一題永遠綠」。

    ### 📏 v2 的三種輸入**實跑過**（不是推的）
    ```
    ① 註解裡提到那個名字（B 踩到的假陽性）  ⇒ 不命中  ✅ 這就是 v2 要修的
    ② 真的實作（讀 args.allow_unverified_…）⇒ 命中    ✅ 沒有漏掉真的
    ③ 只加了 argparse 旗標而**沒有人讀它**  ⇒ 不命中  ⚠️ **已知限制**
    ```
    ⚠️ ③ 是刻意寫出來的：一個加了而沒有人讀的旗標，對使用者**沒有任何效果**
       —— 我判斷它不算「接縫做出來了」，而**那是我的判斷不是量出來的事實**。
       ⇒ 若 A 認為③也該紅，退回給我。
    """
    import io as _io
    import tokenize as _tok

    raw = _VP_PATH.read_text(encoding="utf-8")
    kept = []
    with _io.open(str(_VP_PATH), "rb") as fh:
        for t in _tok.tokenize(fh.readline):
            if t.type in (_tok.COMMENT, _tok.STRING):
                continue
            kept.append(t.string)
    src = " ".join(kept)

    # ⚙️ 正對照：剝完之後，確定存在的識別字必須還在。
    assert "check_db_version" in src, (
        "剝掉註解與字串之後連 `check_db_version` 都找不到了 ——\n"
        "🔑 **剝過頭**，這一題會因為什麼都找不到而永遠綠（儀器失效）。")

    assert missing not in src, (
        "`verify_package.py` 裡出現了 `%s` —— 接縫可能已經做出來了。\n"
        "⇒ 回頭看本檔檔頭那張表，把對應的那一項寫成真的題目"
        "（並請 A 發編號）：\n"
        "   allow_unverified ⇒ `VP2` 降級要出現在**摘要**，不只出現在中段\n"
        "   self_test        ⇒ `VP3` 髒目錄不髒了要**作廢**不是通過\n"
        "                      `VP4` 自測要驗到**結束碼路徑**\n"
        "🔑 這一題是那三項欠帳的**落點** —— 它紅了表示欠帳可以還了。"
        % missing)
