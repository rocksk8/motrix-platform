"""§30a `P0-00` · **每一條出口都要被判定成它實際的結果。**

依 `docs/windows/B.md`（B `af1d56f` 定版）＋ `STATE.md §30a 更正`（A `c049993`）。

---

# ☠️ 缺陷

```
apply_update.ps1:545     健康檢查異常 ＋ -SkipAutoRollback ⇒ **exit 0**
deploy_dashboard.py:179  success = proc.returncode == 0
                  :186   再掃文字 更新失敗|已自動回滾|\\[FAIL\\]
⇒ L545 印的字**一個都不在那個清單裡** ⇒ 判成 succeeded
⇒ 歷史記「成功」，而**正式機跑著一個沒過健康檢查的版本**
```
🔑 它不會有任何症狀：部署完成、畫面正常、歷史一列綠的。

# 🔴 出口是 **15 條**，而 B 自己第一版數成 14

```
B 的正則   ^\\s*Fail\\s+["']        ← **錨在行首**
漏掉的     :358 / :361  寫在 `if ($LASTEXITCODE -ge 8) { Fail "…" }` 裡**同一行**
```
☠️ **而漏掉的那兩條是 15 條裡最壞的**：
```
:316 Step 2  已經停掉正式機的伺服器
:355 Step 3  robocopy 開始覆蓋 backend/
:358         失敗 ⇒ Fail ⇒ exit 1
:114 Fail()  只有兩行：印紅字、exit 1 —— **不做回滾**
             （回滾在 Step 5 的 else 分支 :590+，根本還沒走到）
⇒ 正式機這時是：**已停服 ＋ 半複製 ＋ 沒有人還原**
```
✅ 守門抓得到（`[FAIL]` 命中）⇒ 會被記成失敗，**那一點沒問題**；
🔴 而畫面**說不出**「正式機現在是半套用而且停著」—— 那正是 `P0-0` 要回答的。
📌 〈判準的寬窄都會騙人〉的**錨點**那一種：`^\\s*` 這三個字把兩條出口切掉了。

# 🔴 而 15 條裡只有一條是**判定**缺陷（A 明著限縮）

```
L140  exit 0  -CheckOnly 成功  ⇒ 本來就是成功，且 check-only **不寫 history**
L143  exit 1  -CheckOnly 失敗  ⇒ returncode≠0 第一關就擋下了，且不寫 history
L646  exit 0  正常成功         ⇒ 本來就是成功
🔴 L545  exit 0  健康檢查異常而沒有回滾 ⇒ **這一條才是 P0-00**
```
⚠️ **不要把 `L140`／`L143` 釘成缺陷** —— 它們「守門看不見」而**沒有後果**。

---

# 🔑 我釘的接縫，以及為什麼要連「有沒有呼叫者」一起釘

現在的判定**內嵌在 job runner 裡**（`:179-189`），沒有地方可以單獨測。
⇒ 我釘一支 **`deploy_dashboard.decide_outcome(returncode, output) -> str`**，
回 `"succeeded"` 或 `"failed"`。

🔴 **而我要連「它真的被呼叫」一起釘**：
`reminder_stage()` 也是我釘的接縫，寫得好好的、四題全綠，
☠️ **而產品碼零呼叫者** —— 那四題在測一支沒有人跑的函式。

# ⚠️ B 交代的兩個「不要釘」，我照辦

```
① 不釘那 10 條 Fail 的**訊息字面** —— 那是散文，會被改，而改了不代表行為變了
② 「15 條都要印」**不用數 `::RESULT::` 出現次數**來驗 ——
   有人新增第 16 條而忘了印，總數仍然是 15 ⇒ 那題照樣綠
   ⇒ 改成驗「**走到任何一條出口，都恰好印一行**」（逐條餵，不是數總數）
```
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

DASH = (Path(__file__).resolve().parent.parent / "tools"
        / "deploy_dashboard.py")
PS1 = (Path(__file__).resolve().parent.parent / "tools"
       / "apply_update.ps1")


def _dash():
    import importlib
    import sys as _sys
    tools = str(DASH.parent)
    if tools not in _sys.path:
        _sys.path.insert(0, tools)
    return importlib.import_module("deploy_dashboard")


def _need(name):
    mod = _dash()
    fn = getattr(mod, name, None)
    assert fn is not None, (
        f"`tools/deploy_dashboard.py` 缺少 `{name}` —— 見本檔〈我釘的接縫〉。\n"
        "🔑 判定要抽成一支可以單獨呼叫的函式；"
        "現在它內嵌在 job runner（`:179-189`），沒有地方測得到。")
    return fn


def _result_line(status, rolled_back="not_applied", exit_code=0, v=2):
    """`::RESULT::` 那一行 —— **整個檔只有這裡知道它長什麼樣**。

    B `af1d56f` 定版：`::RESULT:: v=2 status=<s> rolled_back=<r> exit=<n>`
    一行、無前後空白、大小寫固定、欄位順序固定。
    ⇒ 格式再改**只改這一支**，下面每一個案例一行都不用動。
    """
    return f"::RESULT:: v={v} status={status} rolled_back={rolled_back} exit={exit_code}"


#: B 定版的 15 條出口，`status` 與出口 **1:1**。
#: 🔑 1:1 是刻意的：新增出口時沒有現成的值可借 ⇒ 作者必須加新值
#:    ⇒ **而加新值會被值域檢查看到**。
#: `(行, status, rolled_back, exit, 期望判定)`
_EXITS = [
    ("131", "not_prod_machine",          "not_applied",        1, "failed"),
    ("148", "bad_args",                  "not_applied",        1, "failed"),
    ("151", "package_missing",           "not_applied",        1, "failed"),
    ("155", "package_invalid",           "not_applied",        1, "failed"),
    ("172", "duplicate_version",         "not_applied",        1, "failed"),
    ("228", "backup_failed",             "not_applied",        1, "failed"),
    ("276", "migration_dryrun_failed",   "not_applied",        1, "failed"),
    ("311", "user_cancelled",            "not_applied",        1, "failed"),
    ("358", "copy_failed_backend",       "applied_no_restore", 1, "failed"),
    ("361", "copy_failed_frontend",      "applied_no_restore", 1, "failed"),
    ("140", "checkonly_ok",              "not_applied",        0, "succeeded"),
    ("143", "checkonly_failed",          "not_applied",        1, "failed"),
    ("545", "unhealthy_not_rolled_back", "applied",            0, "failed"),
    ("621", "unhealthy_rolled_back",     "restored",           1, "failed"),
    ("646", "success",                   "applied",            0, "succeeded"),
]


# ══════════════════════════════════════════════════════════════════════
# 15 條出口 · 每一條都要被判定成它實際的結果
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("line,status,rolled,rc,expected", _EXITS,
                         ids=[e[0] for e in _EXITS])
def test_p0_00_every_exit_is_judged_as_what_it_actually_was(
        line, status, rolled, rc, expected):
    """🔴🔴 P0-00：**每一條出口都被判定成它實際的結果。**

    ⚠️ 釘的是**結果**，不是關鍵字、不是 `exit` 數字、不是那些出口印的字 ——
    ☠️ 釘字面值的題在守門被換成一層間接之後**照樣全綠**（今天抓到過那個形狀）。
    📌 而 **`exit=0` 不等於成功**：`unhealthy_not_rolled_back` 就是 0。
    """
    decide = _need("decide_outcome")
    out = f"（{line} 那條出口的輸出）\n" + _result_line(status, rolled, rc)
    got = decide(rc, out)
    assert got == expected, (
        f"出口 `:{line}`（status={status}, exit={rc}）判成 {got!r}，"
        f"應該是 {expected!r}。\n"
        "🔑 不變量是**每一條出口都被判定成它實際的結果**，"
        "不是「有沒有出現某個關鍵字」。")


def test_p0_00_the_real_defect_health_check_failed_without_rollback():
    """🔴🔴 **P0-00 本尊，單獨釘一題**（`apply_update.ps1:545`）。

    ```
    健康檢查異常 ＋ -SkipAutoRollback ⇒ exit 0
    而它印的字不在 `更新失敗|已自動回滾|[FAIL]` 裡 ⇒ 舊判定：succeeded
    ⇒ ☠️ **正式機跑著沒過健康檢查的版本，而歷史記著「成功」。**
    ```
    🔑 它與上面那排參數化重疊，**而我刻意單獨留一題** ——
    那一排哪天被整批調整，**這一條仍然自己站著**，而它是整件事的原因。
    """
    decide = _need("decide_outcome")
    out = ("健康檢查沒有通過，因為指定了 -SkipAutoRollback 所以不自動回滾\n"
           + _result_line("unhealthy_not_rolled_back", "applied", 0))
    assert decide(0, out) == "failed", (
        "健康檢查沒過而 `exit 0`，判定仍然是成功 ——\n"
        "☠️ 正式機跑著沒過健康檢查的版本，而儀表板歷史記著「成功」。")


def test_p0_00_the_two_exits_that_leave_prod_half_applied_are_failures():
    """🔴 **`:358`／`:361`：已停服 ＋ 半複製 ＋ 沒有人還原。**

    ☠️ B 第一版的正則 `^\\s*Fail\\s+["']` **錨在行首**，而這兩條寫在
    `if ($LASTEXITCODE -ge 8) { Fail "…" }` 裡**同一行** ⇒ 被數漏了。
    🔑 而它們是 15 條裡**狀態最壞**的：`Fail()` 本體只印紅字然後 `exit 1`，
    **不做回滾**（回滾在 Step 5 的 else 分支，根本還沒走到）。
    📌 判定成失敗本來就對（`[FAIL]` 命中）——
    **這一題釘的是那個 `rolled_back` 狀態說得出「半套用」。**
    """
    decide = _need("decide_outcome")
    for status in ("copy_failed_backend", "copy_failed_frontend"):
        out = ("robocopy 失敗\n"
               + _result_line(status, "applied_no_restore", 1))
        assert decide(1, out) == "failed", f"{status} 沒有被判成失敗"


# ══════════════════════════════════════════════════════════════════════
# 🔴 fail-closed · B 的 dashboard 端六條
# ══════════════════════════════════════════════════════════════════════

def test_p0_00_a_missing_result_line_is_a_failure():
    """🔴🔴 B②：**撈不到結果行 ⇒ 失敗（fail-closed）。**

    ```
    現在   沒比對到任何關鍵字 ＋ returncode 0 ⇒ **成功** ＝ fail-open
    ```
    ☠️ 而「**新增一條出口時忘記印那一行**」是**預設會發生**的事 ——
    🔑 fail-open ⇒ 那條新出口會安靜地全部記成成功；
    fail-closed ⇒ 它在第一次被走到時就紅。
    """
    decide = _need("decide_outcome")
    assert decide(0, "更新完成\n一切正常") == "failed", (
        "輸出裡沒有結果行，而判定是成功 —— 那是 fail-open。\n"
        "☠️ 「忘記印」是預設會發生的事，不是例外。")


def test_p0_00_an_empty_output_is_a_failure():
    """⚙️ fail-closed 的極端值：**完全沒有輸出 ⇒ 失敗。**

    ☠️ 那是「ps1 根本沒跑起來」或「輸出被吞掉」的樣子 ——
    🔑 而它與「跑完了而且成功」在 `returncode == 0` 上完全相同。
    """
    decide = _need("decide_outcome")
    for output in ("", "   ", "\n\n"):
        assert decide(0, output) == "failed", (
            f"輸出是 {output!r} 而判定是成功。")


def test_p0_00_a_wrong_protocol_version_is_a_failure():
    """🔴 B③：**`v` 不是 2 ⇒ 失敗**（跑的不是我送過去那一份）。

    ☠️ 那是「正式機上那一份 ps1 比較舊」的樣子 ——
    🔑 而舊的那一份**不會印新的狀態值** ⇒ 拿它的輸出去判，等於在猜。
    """
    decide = _need("decide_outcome")
    out = "更新完成\n" + _result_line("success", "applied", 0, v=1)
    assert decide(0, out) == "failed", (
        "`v=1` 的結果行被當成有效 ——\n"
        "☠️ 那代表正式機跑的是舊版 ps1，而它印不出新的狀態值。")


def test_p0_00_an_unknown_status_is_a_failure():
    """🔴 B④：**`status` 不在值域 ⇒ 失敗。**

    🔑 值域封閉是刻意的：新增出口時**沒有現成的值可以借**
    ⇒ 作者必須加一個新值 ⇒ **而加新值會被這一題看到**。
    ☠️ 值域開放的話，dashboard 只能再回去猜字串 ＝ **換個地方做關鍵字比對**。
    📌 而 `unknown` 是 ps1 的預設值（忘記給就印它）⇒ 它必須是失敗。
    """
    decide = _need("decide_outcome")
    for bad in ("unknown", "ok", "done", "succeeded", ""):
        out = "看起來很正常\n" + _result_line(bad, "applied", 0)
        assert decide(0, out) == "failed", (
            f"`status={bad!r}` 不在值域，而判定是成功 ——\n"
            "☠️ 值域一旦開放，dashboard 就只能再回去猜字串。")


def test_p0_00_the_last_result_line_wins():
    """🔴 B①：**撈最後一行**（避免子行程輸出干擾）。

    ☠️ `apply_update.ps1` 會呼叫別的腳本，而那些也可能印 `::RESULT::` ——
    🔑 取第一行的話，**子行程的結果會蓋掉真正的那一條出口**。
    """
    decide = _need("decide_outcome")
    out = "\n".join([
        "子行程開始",
        _result_line("success", "applied", 0),          # ← 子行程印的
        "回到主流程",
        "健康檢查沒有通過",
        _result_line("unhealthy_not_rolled_back", "applied", 0),   # ← 真正的
    ])
    assert decide(0, out) == "failed", (
        "撈到的是**第一行**（子行程那一條）而不是最後一行 ——\n"
        "☠️ 子行程的成功蓋掉了主流程的失敗。")


def test_p0_00_a_contradiction_resolves_to_failure():
    """⚠️ B⑥：**兩個訊號矛盾時一律當失敗。**

    現有那道文字防線的註解逐字：「兩者矛盾時一律當失敗處理」。
    ☠️ 反過來的話，一個「印錯結果行」的出口會蓋掉一個真實的非 0 結束碼。
    """
    decide = _need("decide_outcome")
    out = "看起來很正常\n" + _result_line("success", "applied", 0)
    assert decide(1, out) == "failed", (
        "結束碼是 1 而結果行說成功，判定卻是成功 ——\n"
        "🔑 兩個訊號矛盾時要往失敗倒。")


def test_p0_00_a_success_is_still_a_success():
    """⚙️ **反向控制：真正成功的那一條仍然要是成功。**

    ☠️ 少了這一題，一個「**永遠回 failed**」的實作會讓上面每一題全綠 ——
    🔑 而那會讓儀表板把每一次部署都記成失敗，**沒有人會相信那個歷史**。
    📌 〈判準的寬窄都會騙人〉：「永遠失敗」是「fail-closed」的超集。
    """
    decide = _need("decide_outcome")
    out = "更新完成\n" + _result_line("success", "applied", 0)
    assert decide(0, out) == "succeeded", (
        "一條正常成功的出口被判定成失敗 ——\n"
        "☠️ 每一次部署都記成失敗，而沒有人會相信那個歷史。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 ps1 那一側 · 危險值要在動作之前設
# ══════════════════════════════════════════════════════════════════════

def test_p0_00_every_exit_prints_exactly_one_result_line():
    """🔴 **走到任何一條出口，都恰好印一行結果** —— 不是「總數等於 15」。

    ⚠️ B 明著交代：**不要用數 `::RESULT::` 出現次數來驗** ——
    ☠️ 有人新增第 16 條出口而忘了印，**總數仍然是 15 ⇒ 那題照樣綠**。
    🔑 ⇒ 這一題改成逐條比對：**`status` 值域裡的每一個值，
    在 ps1 裡都要找得到恰好一個印出它的地方。**

    ⚠️ 這一題是**靜態的**（讀 ps1 的文字），它擋得住「忘記印」，
    ☠️ 擋不住「印了但印錯值」 —— 那一半由上面那 15 個案例與人工驗收負責。

    ## 🔴 我第一版的判準會逼 B 把格式複製 15 份（B 退回，留著錯的那一版）

    ```
    ❌ 我寫的   f"status={status}" not in src
       它找的是字面 `status=not_prod_machine`
    而 B 把格式集中在**一支** `Emit-Result`，狀態用**參數**傳
       ⇒ ps1 裡 `status=` 只出現 **2 次**（實測：`:133` 那一行 ＋ `:137` 的註解）
       ⇒ 我那個判準 **0/15 命中**
    ☠️ 要它綠，B 得在 15 條出口各自內嵌 `status=xxx` ＝ **把格式複製 15 份**
    🔑 而那正是我在 `_result_line()` 刻意避開的同一件事 ——
       **我要求 B 做一件我自己拒絕做的事。**
    ```

    ## ✅ B 建議的判準，而它比我原本的**強一級**

    ```
    in src   只擋得住「漏掉」
    == 1     還擋得住「**同一個值被兩條出口共用**」
             —— 而值域與出口 1:1 正是這整件事的不變量，共用會讓它**安靜失效**
    ```
    📌 實測（我自己跑的，不是引用 B 的）：15 個值**全部恰好一次**，
    10 個掛在 `Fail`、5 個掛在 `Emit-Result`。
    """
    import re as _re

    assert PS1.exists(), f"找不到 {PS1}"
    src = PS1.read_text(encoding="utf-8", errors="replace")

    wrong = []
    for _l, status, _r, _e, _x in _EXITS:
        hits = _re.findall(
            r'(?:Fail|Emit-Result)[^\n]*"%s"' % _re.escape(status), src)
        if len(hits) != 1:
            wrong.append(f"{status}: {len(hits)} 次")
    assert not wrong, (
        "這些 `status` 值不是**恰好一次**出現在 `Fail`／`Emit-Result` 的引數上：\n  "
        + "\n  ".join(wrong)
        + "\n🔑 值域與出口是 **1:1**：\n"
          "   0 次 ⇒ 那一條出口**沒有印結果行** ⇒ 它會落進 fail-closed\n"
          "         （被記成失敗 —— 比記成成功好，**而它說不出真正發生了什麼**）\n"
          "   ≥2 次 ⇒ **兩條出口共用同一個值** ⇒ 1:1 安靜失效，\n"
          "         而 dashboard 從此分不出那兩條")


def test_p0_00_the_result_format_lives_in_exactly_one_place():
    """🔴 **結果行的格式只准有一個地方知道。**

    ☠️ 複製成 15 份的話，**改格式要改 15 個地方**，而漏掉一個的症狀是
    「那一條出口的結果行版本號不對 ⇒ 被判成失敗」——
    🔑 **一個會被 fail-closed 接住的錯誤，而它看起來像「那次部署失敗了」。**
    📌 這一題與上一題是**一對**：上一題管「每個值都有人印」，
    這一題管「**印的方式只有一種**」。

    ⚠️ 而這正是 B 退回我第一版的理由 —— 我當時的判準會逼它把格式複製 15 份。
    ⇒ 現在把那件事**釘成不變量**，免得日後有人為了「讓某一題好寫」再拆開一次。
    """
    assert PS1.exists(), f"找不到 {PS1}"
    src = PS1.read_text(encoding="utf-8", errors="replace")
    emitters = [ln for ln in src.splitlines()
                if "::RESULT::" in ln and not ln.strip().startswith("#")]
    assert len(emitters) == 1, (
        f"`::RESULT::` 的**輸出點**有 {len(emitters)} 處，預期 1 處：\n  "
        + "\n  ".join(e.strip()[:90] for e in emitters)
        + "\n☠️ 格式散在多處 ⇒ 改格式要改多個地方，而漏掉一個的症狀是\n"
          "   「那一條出口的版本號不對 ⇒ 被判成失敗」——\n"
          "🔑 **一個會被 fail-closed 接住的錯誤，而它看起來像「那次部署失敗了」。**")


def test_p0_00_the_fail_closed_exemption_list_cannot_grow_silently():
    """🔴 **豁免清單只准有 `build` 一個名字。**

    B 實作了 `_PROTOCOL_EXEMPT`：列在裡面的動作**不走結果行**，走舊的
    結束碼＋關鍵字。`build` 在裡面（它不碰正式機，`rolled_back` 對它沒有意義）。

    ☠️ **而那是一條非常便宜的變綠路徑**：哪天 `rollback` 或 `deploy` 沒印結果行
    而被 fail-closed 記成失敗，**最省力的動作是把它加進這個集合** ——
    🔑 而加進去之後，`P0-00` 對那個動作**整個失效**，且沒有任何一題會紅。
    📌 〈守門要驗有沒有人做過決定〉：豁免是一個決定，**它要留下名字**。

    ⚠️ 而 B 明著**沒有**把 `rollback` 列進去（它會碰正式機，本來就該講協定）——
    那個判斷是對的，而這一題是它的守門。
    """
    mod = _dash()
    exempt = getattr(mod, "_PROTOCOL_EXEMPT", None)
    assert exempt is not None, (
        "`deploy_dashboard.py` 缺少 `_PROTOCOL_EXEMPT` ——\n"
        "⇒ 前提不成立（那個機制改名或拿掉了）。")
    assert set(exempt) == {"build"}, (
        f"豁免清單現在是 {sorted(exempt)}，預期只有 `build`。\n"
        "☠️ 多一個名字 ＝ 那個動作從此不走結果行 ⇒ `P0-00` 對它整個失效，\n"
        "🔑 而它是「被 fail-closed 記成失敗」時**最省力的那個動作**。\n"
        "📌 要加名字的話，理由要寫在那個集合旁邊，並且改這一題 —— "
        "**那一改在 diff 上藏不住。**")


def test_p0_00_the_dangerous_state_is_set_before_the_action():
    """🔴 **危險值要在動作之前設**（B 的實作機制，我釘它的不變量）。

    ```
    Step 3 robocopy **之前**先設 $script:ProdState = 'applied_no_restore'
    ```
    ☠️ 之後才設的話，**動作中途失敗會報出一個比實際安全的狀態** ——
    🔑 而「比實際安全」正是這一整件事最貴的那個方向：
    畫面說「沒開始」，而正式機已經停服＋半複製。
    📌 而它有個附帶好處：日後有人在 Step 3 之後新增一個 `Fail`，
    **它會自動報對，不必記得改。**

    ⚙️ 反向控制（B 建議的落點）：把那個設定點往後移一行 ⇒ 這一題必須紅。

    ## 🔴 兩個錨點我第一版都挑錯了（B 退回，留著錯的那一版）

    ```
    ❌ copy_at = src.find("robocopy")
       實測命中 :287 —— 那是**回滾快照**：
       `robocopy $BackendDir (Join-Path $rollbackDir "backend")`
       **來源是正式機、目的地是快照目錄 ⇒ 那一刻正式機一個檔都沒被動。**
       ☠️ 照它做，B 得把危險值設在 :287 之前 ⇒ 而 :311（user_cancelled）
          在 :287 之後 ⇒ **使用者按取消時會報 `applied_no_restore`**，
          而那時正式機完全沒被碰過。
    ❌ set_at = src.find("applied_no_restore")
       ☠️ 那個字串會出現在**兩種角色**上：`$ProdState` 的**指派**、
          以及 `::RESULT::` 的**輸出**。`find` 取第一個 ⇒ 可能比到輸出那一行。
    ```
    🔑 **兩個都是同一個病**：錨點是一個**字串**，而我要的是一個**語意位置**。
    📌 而它與今天 B 自己那個 `^\\s*Fail` 漏掉兩條出口是同一族 ——
    **查詢的形狀決定了答案的可能集合。**

    ⇒ 這一版：
    ```
    copy_at  robocopy (Join-Path $PackagePath "backend") $BackendDir
             ✅ **目的地是 $BackendDir** ＝ 真的在覆蓋正式機；實測唯一命中（:355）
    set_at   對 $ProdState 的**指派**，不是任何一處提到那個字串的地方
    ```
    📌 而 B 明著界定了「不可逆的起點」：**不是 `:316` 停服，是 `:355` 開始寫入**
    （停服之後、覆蓋之前，磁碟上還是舊程式碼，autostart 會把它拉回來 ⇒ 自己會好）。
    ⚠️ 我同意那個界定。**而「服務停著」這件事五態裡沒有任何一個說得出來** ——
    已回報 A，那是條文層級的事，不是這一題的。
    """
    import re as _re

    assert PS1.exists(), f"找不到 {PS1}"
    src = PS1.read_text(encoding="utf-8", errors="replace")

    # 🔑 錨點①：**對 ProdState 的指派**，不是任何一處提到那個字串的地方。
    m = _re.search(r"\$(?:script:)?ProdState\s*=\s*['\"]applied_no_restore['\"]",
                   src)
    assert m, (
        "`apply_update.ps1` 裡找不到**對 `$ProdState` 指派 "
        "`applied_no_restore`** 的地方 ——\n"
        "⚠️ 注意這一題找的是**指派**不是字串出現：\n"
        "   `::RESULT::` 的輸出裡也會有那個字，而那不是設定點。\n"
        "⇒ 那個狀態還沒實作（見 `B.md` 的五態表）。")
    set_at = m.start()

    # 🔑 錨點②：**目的地是 $BackendDir** 的那一次 robocopy ＝ 真的在覆蓋正式機。
    marker = 'robocopy (Join-Path $PackagePath "backend") $BackendDir'
    assert src.count(marker) == 1, (
        f"錨點 {marker!r} 在檔裡出現 {src.count(marker)} 次，預期 1 次 ——\n"
        "⇒ 這一題的錨點不再唯一（那一行被改寫了？）⇒ **前提不成立**。")
    copy_at = src.find(marker)

    assert set_at < copy_at, (
        f"`$ProdState = 'applied_no_restore'` 設在覆蓋正式機**之後**"
        f"（設定 @{set_at}，覆蓋 @{copy_at}）——\n"
        "☠️ 動作中途失敗時會報出一個**比實際安全**的狀態：\n"
        "   畫面說「還沒開始」，而正式機已經半複製而且沒有人還原。\n"
        "🔑 危險值要在動作**之前**設 —— 那樣日後有人在 Step 3 之後新增一個\n"
        "   `Fail`，**它會自動報對，不必記得改。**")


# ══════════════════════════════════════════════════════════════════════
# 🔴 接縫要有真的呼叫者 —— reminder_stage() 那次的學費
# ══════════════════════════════════════════════════════════════════════

def test_p0_00_the_job_runner_actually_uses_the_decision():
    """🔴 **那支函式要真的被 job runner 呼叫，不是寫好放著。**

    ☠️ `reminder_stage()` 也是我釘的接縫，寫得好好的、四題全綠，
    **而產品碼零呼叫者** —— 那四題在測一支沒有人跑的函式。
    ⚠️ 它驗的是「有沒有呼叫」，**不是「呼叫得對不對」**（後者是上面那 15 題）。
    """
    src = DASH.read_text(encoding="utf-8")
    at = src.find('_jobs[job_id]["status"] = ')
    assert at > 0, (
        "找不到 job runner 寫 status 的那一行 ——\n"
        "⇒ 前提不成立（那一段改寫過，抽取樣式要跟著改）。")
    window = src[max(0, at - 1500):at + 200]
    assert "decide_outcome" in window, (
        "job runner 決定 `status` 的那一段**沒有呼叫 `decide_outcome`** ——\n"
        "☠️ 接縫寫好了而沒有人用它 ⇒ 上面那 15 題在測一支沒有人跑的函式。\n"
        f"  那一段目前長這樣：\n{window[-400:]}")


def test_p0_00_the_old_keyword_check_is_kept_as_a_second_layer():
    """⚠️ B⑥：**舊的關鍵字比對要留著當第二道，不要拿掉。**

    🔑 理由不是它準 —— 是**兩道獨立的防線不會同時因為同一個原因失效**。
    ☠️ 而「改用新方法就把舊的刪掉」是最容易發生的動作，
    📌 它讓一個本來有兩層的地方**安靜地變成一層**，而那沒有任何症狀。
    """
    src = DASH.read_text(encoding="utf-8")
    for keyword in ("更新失敗", "已自動回滾", r"\[FAIL\]"):
        assert keyword in src, (
            f"舊的關鍵字比對裡少了 {keyword!r} ——\n"
            "☠️ 改用結果行之後把舊的那道刪掉了 ⇒ 兩層變一層，而它沒有症狀。")
