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
import re as _re
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


#: 每個接縫**各自**的成因說明。
#: ⚠️ 原本 `_need()` 對所有接縫印同一句「它內嵌在 job runner（`:179-189`）」——
#:    那句話對 `decide_outcome` 為真，對 `describe_rolled_back` **是假的**
#:    （它的實情是 `:321` 解析出來就丟掉）。
#: 🔑 〈訊息的指向是我當初的假設，不是這次的證據〉：
#:    一句共用的訊息會把**第一個**接縫的成因，講成**每一個**接縫的成因。
_SEAM_WHY = {
    "decide_outcome":
        "判定要抽成一支可以單獨呼叫的函式；"
        "現在它內嵌在 job runner（`:179-189`），沒有地方測得到。",
    "used_legacy_protocol":
        "畫面要標「本次以舊版協定判定」，就需要一個**可以問**的地方。",
    "describe_rolled_back":
        "`:321` 把 `rolled_back` 解析出來就丟掉（`_rolled_back`）⇒ "
        "這個欄位一路走到畫面之前**沒有任何地方把它變成人話**，"
        "而 §41a 要的正是「同一個機器值、依 `action` 算出不同的人話」。",
}


def _need(name):
    mod = _dash()
    fn = getattr(mod, name, None)
    assert fn is not None, (
        f"`tools/deploy_dashboard.py` 缺少 `{name}` —— 見本檔〈我釘的接縫〉。\n"
        "🔑 " + _SEAM_WHY.get(name, "見規格。")
        + "\n⚠️ 名字可以換（**退回給我**，不要自己改題），"
          "而那個接縫必須存在。")
    return fn


def _result_line(status, rolled_back="not_applied", *,
                 service="unknown", exit_code=0, v=2):
    """`::RESULT::` 那一行 —— **整個檔只有這裡知道它長什麼樣**。

    B `af1d56f` 定版、`§34c` 加 `service`：
    `::RESULT:: v=2 status=<s> rolled_back=<r> service=<up|down|unknown> exit=<n>`
    一行、無前後空白、大小寫固定、欄位順序固定。
    ⇒ 格式再改**只改這一支**，下面每一個案例一行都不用動。

    ✅ **這一支存在的理由，今天被 `§34c` 實測了一次**：
    加一個欄位 ⇒ 37 題裡 4 題紅 ⇒ **改這 8 行，33 題一行都沒動。**

    ⚠️ **而它差一點沒守住**：`service` 插在 `exit_code` 前面，
    而十個呼叫點**全部**用位置引數傳 `exit_code`
    ⇒ 那個 `0` 會餵進 `service`，變成 `service=0`。
    ☠️ 失敗的樣子是「值域題紅了」，而壞的是**題目檔**不是產品。
    🔑 B 只點出其中一處（`:613`）—— 一處是對的，而**十處才是實情**：
       〈判準的寬窄都會騙人〉的同一個形狀，**照收一個更正也要自己數一次。**
    ⇒ 所以 `service` 之後**全部具名**（`*`）：
       日後再插欄位，位置引數會當場 `TypeError`，不會靜默餵錯格。
    """
    return (f"::RESULT:: v={v} status={status} rolled_back={rolled_back}"
            f" service={service} exit={exit_code}")


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
    out = f"（{line} 那條出口的輸出）\n" + _result_line(status, rolled, exit_code=rc)
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
           + _result_line("unhealthy_not_rolled_back", "applied", exit_code=0))
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
               + _result_line(status, "applied_no_restore", exit_code=1))
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
    out = "更新完成\n" + _result_line("success", "applied", exit_code=0, v=1)
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
        out = "看起來很正常\n" + _result_line(bad, "applied", exit_code=0)
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
        _result_line("success", "applied", exit_code=0),          # ← 子行程印的
        "回到主流程",
        "健康檢查沒有通過",
        _result_line("unhealthy_not_rolled_back", "applied", exit_code=0),   # ← 真正的
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
    out = "看起來很正常\n" + _result_line("success", "applied", exit_code=0)
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
    out = "更新完成\n" + _result_line("success", "applied", exit_code=0)
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


# ══════════════════════════════════════════════════════════════════════
# §34a · `rollback` 的 fail-closed **必須經過握手**（A 2026-09-22 裁定）
# ══════════════════════════════════════════════════════════════════════
#
# 🔴 兩個動作的判定條件**不一樣，而那是有理由的不對稱**：
#
# ```
# deploy    _dashboard_remote.ps1:98-104 先把套件裡的 tools 複製過去
#           ⇒ **跑的保證是新的那一份** ⇒ 無條件 fail-closed
# rollback  :150-170 直接跑 $Root\backend\tools\rollback_update.ps1
#           ⇒ **沒有預先複製** ⇒ 新腳本只能靠一次成功的部署才上得去
# ```
# ☠️ 而危險的順序正是最可能發生的那一條：
# ```
# 部署失敗 ⇒ 自動回滾用套用前快照蓋回去 ⇒ **正式機的 tools 退回舊版**
# ⇒ 使用者手動回滾 ⇒ 舊腳本不印 ::RESULT::
# ⇒ 🔴 無條件 fail-closed ⇒ 記成「回滾失敗」
# ⇒ 而那一刻使用者最需要知道的正是「回滾到底成功了沒」
# ```
# 🔑 ⇒ 握手：收到 `::PROTOCOL:: v=2` 才啟用 fail-closed；
#    沒收到 ⇒ 退回結束碼＋關鍵字，**並在畫面標「本次以舊版協定判定」**。
#
# ⚠️ **我釘的接縫**：`decide_outcome(returncode, output, action="deploy")`
#    📌 `action` 預設 `"deploy"`（**嚴格的那一邊**）——
#    🔑 與 `_PROTOCOL_EXEMPT` 同一個方向：**豁免要舉手，不是預設。**
#    ⇒ 上面那 15＋8 題不傳 `action`，它們釘的仍然是嚴格判定。

_PROTOCOL_LINE = "::PROTOCOL:: v=2"


def test_p0_00_rollback_without_the_handshake_falls_back_to_the_old_judgement():
    """🔴🔴 §34a：**`rollback` 沒收到握手 ⇒ 退回舊判定，不可以無條件判失敗。**

    ☠️ 無條件 fail-closed 的話，「**部署失敗→自動回滾→tools 退回舊版→
    使用者手動回滾**」這條最可能發生的路徑上，
    每一次回滾都會被記成失敗 —— 🔑 **而那一刻使用者最需要的正是
    「回滾到底成功了沒」。**

    ⚙️ **這一題同時是 A 要的那支反向題**：
    把 `rollback` 也改成無條件 fail-closed ⇒ **這一題會紅**。
    📌 有人日後「統一」掉那個不對稱時，紅的是這裡，而訊息說得出為什麼。
    """
    decide = _need("decide_outcome")
    out = "回滾完成\n正式機已還原到上一版"
    assert decide(0, out, action="rollback") == "succeeded", (
        "`rollback` 沒有收到 `::PROTOCOL:: v=2`，而判定是失敗 ——\n"
        "☠️ 那是無條件 fail-closed，而 rollback 的腳本**沒有被預先複製** ⇒\n"
        "   正式機上那一份可能是舊的（部署失敗自動回滾之後就是）⇒\n"
        "   **每一次手動回滾都會被記成失敗**。\n"
        "🔑 §34a：收到握手才啟用 fail-closed，沒收到就退回結束碼＋關鍵字。")


def test_p0_00_deploy_without_a_result_line_still_fails():
    """⚙️ **不對稱的另一側：同樣沒有結果行，`deploy` 仍然判失敗。**

    ☠️ 少了這一題，一個「**乾脆兩邊都退回舊判定**」的實作會讓上一題全綠 ——
    🔑 而那會把 `P0-00` 整個解除掉：`unhealthy_not_rolled_back` 的 `exit=0`
    會再一次被記成成功。
    📌 **兩題成對**：一題守「不要對 rollback 太嚴」，一題守「不要對 deploy 太鬆」。
    """
    decide = _need("decide_outcome")
    out = "更新完成\n一切正常"
    assert decide(0, out, action="deploy") == "failed", (
        "`deploy` 沒有結果行而判成成功 —— 那是 fail-open。\n"
        "☠️ `deploy` 的 tools **有**預先複製，跑的保證是新的那一份 ⇒\n"
        "   它沒有理由退回舊判定。")


def test_p0_00_rollback_with_the_handshake_is_fail_closed():
    """🔴 §34a：**`rollback` 收到握手 ⇒ fail-closed 啟用。**

    🔑 握手的意思是「**那一份腳本會印結果行**」⇒ 它沒印就是出事了。
    ☠️ 少了這一題，握手會變成一個**沒有後果的宣告**：
    收到也好沒收到也好，都退回舊判定 ⇒ 那條協定等於不存在。
    """
    decide = _need("decide_outcome")
    out = _PROTOCOL_LINE + "\n回滾完成"      # 宣告了會印，而沒有印
    assert decide(0, out, action="rollback") == "failed", (
        "`rollback` 收到了 `::PROTOCOL:: v=2`（＝那份腳本宣告它會印結果行），\n"
        "而輸出裡沒有結果行，判定卻是成功 ——\n"
        "☠️ 那讓握手變成一個沒有後果的宣告：收到與沒收到的行為一樣。")


def test_p0_00_rollback_with_the_handshake_and_a_result_line_is_judged_by_it():
    """⚙️ 握手那一側的正對照：**有握手也有結果行 ⇒ 照結果行判。**

    ☠️ 少了這一題，一個「收到握手就一律判失敗」的實作會讓上一題全綠 ——
    🔑 而那會讓**每一次正常的回滾**都被記成失敗。
    """
    decide = _need("decide_outcome")
    out = (_PROTOCOL_LINE + "\n回滾完成\n"
           + _result_line("success", "restored", exit_code=0))
    assert decide(0, out, action="rollback") == "succeeded", (
        "有握手、也有結果行說成功，而判定是失敗 ——\n"
        "☠️ 每一次正常的回滾都會被記成失敗。")


def test_p0_00_a_legacy_rollback_is_marked_as_such():
    """🔴 §34a：**退回舊判定時，畫面要說得出「本次以舊版協定判定」。**

    ☠️ 不標的話，使用者看到的「成功」與一個**經過 fail-closed 驗證**的成功
    長得一模一樣 —— 🔑 而它們的可信度差很多：
    ```
    有握手的成功   結果行說 success，而那一份腳本保證會印
    舊判定的成功   結束碼是 0，而**我們不知道它有沒有真的做完**
    ```
    📌 而使用者正是在「剛出事、正在回滾」的時候看它 ——
    **那是最不該讓他誤以為事情已經確認好的時刻。**

    ⚠️ **我釘的是「那個事實被記下來了」，不是欄位叫什麼名字** ——
    這裡用 `legacy_protocol`，B 要改名**退回給我**，不要自己改題。
    """
    mod = _dash()
    fn = getattr(mod, "used_legacy_protocol", None)
    assert fn is not None, (
        "`deploy_dashboard.py` 缺少 `used_legacy_protocol(output, action)` ——\n"
        "🔑 畫面要標「本次以舊版協定判定」，就需要一個**可以問**的地方。\n"
        "⚠️ 名字可以換（退回給我），而那個事實必須記得下來。")
    assert fn("回滾完成", "rollback") is True, (
        "`rollback` 沒收到握手而 `used_legacy_protocol` 回 False ——\n"
        "☠️ 那一次是用舊判定做的，而畫面會把它顯示成一個確認過的成功。")
    assert fn(_PROTOCOL_LINE + "\n回滾完成", "rollback") is False, (
        "收到握手了而仍然標成舊判定 —— 那個標記會變成雜訊，\n"
        "🔑 而一個每次都出現的警告，與沒有警告是同一件事。")
    assert fn("更新完成", "deploy") is False, (
        "`deploy` 被標成舊判定 —— 它有預先複製，不走那條退路。")


# ══════════════════════════════════════════════════════════════════════
# §34a · rollback_update.ps1 的 6 條出口
# ══════════════════════════════════════════════════════════════════════

ROLLBACK_PS1 = (Path(__file__).resolve().parent.parent / "tools"
                / "rollback_update.ps1")


def test_p0_00_the_rollback_script_announces_the_protocol():
    """🔴 §34a：**`rollback_update.ps1` 要印握手行。**

    🔑 沒有它，dashboard 永遠走舊判定 ⇒ 那 6 條出口印不印結果行都沒有差別。
    """
    assert ROLLBACK_PS1.exists(), f"找不到 {ROLLBACK_PS1}"
    src = ROLLBACK_PS1.read_text(encoding="utf-8", errors="replace")
    assert "::PROTOCOL:: v=2" in src, (
        "`rollback_update.ps1` 沒有印 `::PROTOCOL:: v=2` ——\n"
        "☠️ dashboard 會永遠走舊判定，而那 6 條出口的結果行等於白印。")


def test_p0_00_the_rollback_script_emits_one_result_per_exit():
    """🔴 §34a：**6 條出口每一條都要印結果行，而格式只有一個地方知道。**

    📌 判準與 `apply_update.ps1` 那兩題**同一個形狀**：
    ```
    輸出點恰好 1 處        ← 格式不複製
    每條出口一個狀態值     ← 而不是數 `::RESULT::` 出現幾次
    ```
    ⚠️ 狀態值域由 B 定（6 個），**我這裡只釘「不是 0 也不是共用」**：
    🔑 逐一釘值的那一半，等 B 的值域表到了再補 —— **而我明著說它還沒釘。**
    """
    assert ROLLBACK_PS1.exists(), f"找不到 {ROLLBACK_PS1}"
    src = ROLLBACK_PS1.read_text(encoding="utf-8", errors="replace")
    emitters = [ln for ln in src.splitlines()
                if "::RESULT::" in ln and not ln.strip().startswith("#")]
    assert len(emitters) == 1, (
        f"`::RESULT::` 的**輸出點**有 {len(emitters)} 處，預期 1 處：\n  "
        + "\n  ".join(e.strip()[:90] for e in emitters)
        + "\n☠️ 格式散在多處 ⇒ 改格式要改多個地方，而漏掉一個會被 fail-closed\n"
          "   接住 ⇒ **看起來像「那次回滾失敗了」。**")


# ══════════════════════════════════════════════════════════════════════
# §34c · `service` —— 它生出來是為了 `:358`，而原本沒有一題在守那件事
# ══════════════════════════════════════════════════════════════════════

APPLY_PS1 = (Path(__file__).resolve().parent.parent / "tools"
             / "apply_update.ps1")

#: 「寫進正式機」那一行的語意錨。
#: ⚠️ **不可以錨在 `robocopy` 這個字**：兩支腳本裡它都扮演兩種角色
#:    （把正式機複製到快照／把快照複製回正式機），而只有後者是破壞性的。
#:    〈錨點要錨在語意上〉的可操作判準：
#:    **「這個字串在檔裡扮演幾種角色？」答案大於一就不能用它當錨。**
#: ⇒ 所以錨在**目的地**上：`... $BackendDir` 才是寫進正式機。
_WRITES_INTO_PROD = _re.compile(
    r'^\s*(?:\$\w+\s*=\s*)?robocopy\s+\(Join-Path\s+\$\w+\s+"backend"\)\s+\$BackendDir\b')


@pytest.mark.parametrize("ps1", [APPLY_PS1, ROLLBACK_PS1],
                         ids=["apply_update", "rollback_update"])
def test_p0_00_service_goes_down_before_the_first_write_into_prod(ps1):
    """🔴🔴 §34c 的**本尊案例**：`service=down` 要在第一次寫進正式機**之前**設。

    §34c 逐字：
    > ☠️ 而「服務停著」正是 `:358` 那條出口（已停服＋半複製＋`Fail()` 不做回滾）
    > 最需要說出口的那一件 —— **它決定使用者要不要現在衝去開機。**

    ⚠️ **而原本沒有一題在守它。** `_EXITS` 那 15 題連 `service` 都沒傳，
    §34c 的整個理由**一題都沒落地** ——
    🔑 〈缺欄位≠缺訊號〉的反面：**欄位加了，而沒有人檢查它說得對不對。**

    ```
    設在動作之前  ⇒ robocopy 中途失敗 ⇒ service=down    ✅ 使用者知道要去開機
    設在動作之後  ⇒ 同一次失敗         ⇒ service=unknown ☠️ 「可能還活著吧」
    ```
    📌 與 B 在 `§30a` 記下的 `$script:ProdState` **同一條紀律**：
    **危險值在動作之前就設** —— 而那條紀律當時只寫進 `STATE.md`，
    〈散文對工具是隱形的〉⇒ 這一題是它的可執行形式。

    ⚠️ **這一題的錨點自檢在第一次實跑就抓到我自己**，那一列留著：
    ```
    ❌ v1  assert len(writes) == 1   ⇒ apply_update 紅：命中 2 行
           :422  robocopy $PackagePath/backend  → $BackendDir   套用新版
           :632  robocopy $rollbackDir/backend  → $BackendDir   自動回滾的還原
    ✅ v2  assert writes            ⇒ 兩行都真的是寫進正式機，
                                      而不變量是「在**第一次**寫之前」
    ```
    🔑 〈判準的寬窄都會騙人〉兩側今天都出現了：`== 1` 太**窄**（假陰性），
       而放寬到 `assert writes` **仍然擋得住唯一會給假綠燈的那一種** —— 命中 0 行。
    ⇒ 可操作的順序：**放寬之前先把命中的內容印出來看，不要只數數量。**
    """
    assert ps1.exists(), "找不到 %s" % ps1
    lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()

    downs = [i for i, ln in enumerate(lines)
             if ln.strip().startswith("$script:ServiceState")
             and '"down"' in ln]
    writes = [i for i, ln in enumerate(lines) if _WRITES_INTO_PROD.match(ln)]

    # ⚙️ 錨點自檢 —— 〈盤點工具的正對照〉：
    #    先證明「已知的那一個亮得起來」，才有資格拿它去比大小。
    # ⚠️ **刻意放寬**：這裡不守「寫入正式機的地方有幾處」，只守「量得到」。
    #    原本的 `== 1` 抓得到「有人新增了第三處寫入」，放寬後抓不到 ——
    #    那不是錯，是**交換**，寫在這裡讓下一個人看得出它是被拿掉的，
    #    不是從來沒有過（A-2 提）。
    assert writes, (
        "`%s`：「寫進正式機」的錨點**一行都沒命中** ——\n"
        "☠️ 那會讓這一題**因為量不到而綠**，而那與「順序是對的」長得一模一樣。\n"
        "🔑 錨在目的地 `$BackendDir`，不是錨在 `robocopy`（它扮演兩種角色）。"
        % ps1.name)

    assert len(downs) == 1, (
        "`%s`：`$script:ServiceState = down` 有 %d 處，預期 1 處。\n"
        "🔑 兩處以上 ⇒ 順序這件事變成「每一處都要對」，"
        "而這一題只驗得到最早那一處。" % (ps1.name, len(downs)))

    assert downs[0] < writes[0], (
        "`%s`：`service=down` 設在 :%d，而第一次寫進正式機在 :%d —— **順序反了**。\n"
        "☠️ 複製到一半失敗時會報 `service=unknown`，"
        "而實際上是**我們自己把它停掉的**。\n"
        "🔑 那個差別決定使用者要不要現在衝去開機（§34c 逐字）。"
        % (ps1.name, downs[0] + 1, writes[0] + 1))


def test_p0_00_the_service_value_domain_is_exactly_what_the_spec_says():
    """🔴 §34c 逐字 `service=up|down|unknown` —— **兩支腳本都不可以多出第四個值**。

    ☠️ 多一個值（`restarting`／`degraded`／`partial`…）而 dashboard 不認得
    ⇒ 值域檢查把它判成失敗 ⇒ **一次成功的部署被記成失敗**。
    🔑 fail-closed 的方向是對的，而**代價是使用者不再相信那個畫面**。

    ⚙️ 反向控制：初始值必須是 `unknown`（最安全的那一個）——
    少了這一條，「把初始值改成 `up`」會讓值域題照樣全綠，
    而那會讓**還沒檢查過**的服務被畫面說成「活著」。
    """
    allowed = {"up", "down", "unknown"}
    assign = _re.compile(r'^\s*\$script:ServiceState\s*=\s*"([^"]*)"')
    for ps1 in (APPLY_PS1, ROLLBACK_PS1):
        assert ps1.exists(), "找不到 %s" % ps1
        lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = []
        for ln in lines:
            m = assign.match(ln)
            if m:
                hits.append(m.group(1))
        assert hits, (
            "`%s` 裡一個 `$script:ServiceState =` 指派都沒抓到 ——\n"
            "☠️ 那不是「值域乾淨」，是**儀器失效**"
            "（〈沒抓到要被解釋成儀器失效，不可以被解釋成乾淨〉）。" % ps1.name)
        bad = set(hits) - allowed
        assert not bad, (
            "`%s` 的 `service` 出現規格以外的值：%s\n"
            "§34c 逐字只有 %s。\n"
            "☠️ dashboard 的值域檢查會把它判成失敗 ⇒ 一次成功的部署被記成失敗。"
            % (ps1.name, sorted(bad), sorted(allowed)))
        assert hits[0] == "unknown", (
            "`%s` 的 `service` 初始值是 %r，應該是 `unknown`。\n"
            "☠️ 初始值是 `up` 的話，**還沒檢查過**的服務會被畫面說成活著。\n"
            "🔑 `up` 只能從一次觀察到的事實來（ping 成功），不可以是預設。"
            % (ps1.name, hits[0]))


def test_p0_00_a_result_line_whose_service_is_unusable_is_fail_closed():
    """⚙️ **`service` 缺席／亂值 ⇒ fail-closed。**

    ⚠️ **這一題不是紅題，是我在 B 交付之後補的守門。**
    B 說「缺 `service` ⇒ fail-closed」，我自己把四種輸入都實跑過才寫 ——
    🔑 〈標出來源不等於查證了來源〉：**照收一個前提與照收一個派工是同一種毛病。**
    ⇒ 它守的是**日後**有人「順手放寬」時會紅，不是今天抓到了什麼。

    ☠️ 特別是 `service=0`：那是**位置引數踩進 `service` 那一格**的樣子
    （今天十個呼叫點全部踩得到）—— 它必須是失敗，
    否則一個**格式壞掉的**結果行會被當成一次成功的部署。
    """
    decide = _need("decide_outcome")
    base = "::RESULT:: v=2 status=success rolled_back=applied"
    for tail, why in (
            (" exit=0",                  "整個 service 欄位缺席"),
            (" service=banana exit=0",   "service 是值域外的字串"),
            (" service=0 exit=0",        "service=0（位置引數餵錯格的樣子）"),
            (" service= exit=0",         "service 是空字串"),
    ):
        out = "更新完成\n" + base + tail
        assert decide(0, out) == "failed", (
            "%s ⇒ 判定是成功。\n"
            "☠️ 一個**格式壞掉**的結果行被當成一次確認過的部署。\n"
            "🔑 fail-closed 的方向：讀不出來要拒絕那一筆，不要送一個空值過去。" % why)


# ══════════════════════════════════════════════════════════════════════
# §34a · rollback 的 6 條出口 —— 值域表到了，把當初明著欠的那一半補上
# ══════════════════════════════════════════════════════════════════════
#
# 📌 上面 `..._emits_one_result_per_exit` 的 docstring 寫著：
#    「逐一釘值的那一半，等 B 的值域表到了再補 —— **而我明著說它還沒釘。**」
#    ⇒ 表到了，這一節就是那一半。
#    🔑 〈已知的代價 vs 要修的東西〉：當初寫成註解，**現在要把它結掉**，
#       否則那行註解會變成「它看起來被處理過了」。

#: `(status, rolled_back, service, exit, 期望判定)`
_ROLLBACK_EXITS = [
    # ⚠️ 這四條的 `rolled_back` **本表寫 `not_applied`（§41b 裁示），
    #    而 `rollback_update.ps1:85` 現在還是 `unknown`** ——
    #    表寫的是規格的真相，不是現況的程式碼。守那件事的是
    #    `..._starts_from_a_true_statement`（現在是紅的，等 B 改）。
    ("rollback_not_prod_machine",    "not_applied",        "unknown", 1, "failed"),
    ("rollback_snapshot_missing",    "not_applied",        "unknown", 1, "failed"),
    ("rollback_db_snapshot_missing", "not_applied",        "unknown", 1, "failed"),
    ("rollback_user_cancelled",      "not_applied",        "unknown", 1, "failed"),
    ("rollback_ok",                  "restored",           "up",      0, "succeeded"),
    ("rollback_failed",              "restored_unhealthy", "down",    1, "failed"),
]


@pytest.mark.parametrize("status,rolled,service,rc,expected", _ROLLBACK_EXITS,
                         ids=[e[0] for e in _ROLLBACK_EXITS])
def test_p0_00_every_rollback_exit_is_judged_as_what_it_actually_was(
        status, rolled, service, rc, expected):
    """🔴 §34a：**rollback 的 6 條出口也要被判定成它實際的結果。**

    ⚠️ 有握手才走這條 —— 沒握手的那一側是
    `..._rollback_without_the_handshake_falls_back_to_the_old_judgement`，
    兩題**方向相反而缺一不可**。

    ☠️ `rollback_failed` 最值得單獨看一眼：
    ```
    rolled_back=restored_unhealthy   還原**動作做完了**（快照已經套回去）
    service=down                     而它**現在沒在服務**
    ```
    🔑 合成一句「回滾失敗」會讓人以為快照沒被套用，**而去做第二次回滾** ——
       那是在一台已經不健康的機器上再蓋一次。
    """
    decide = _need("decide_outcome")
    out = (_PROTOCOL_LINE + "\n（%s 那條出口的輸出）\n" % status
           + _result_line(status, rolled, service=service, exit_code=rc))
    got = decide(rc, out, action="rollback")
    assert got == expected, (
        "rollback 出口 `%s`（rolled_back=%s, service=%s, exit=%d）"
        "判成 %r，應該是 %r。" % (status, rolled, service, rc, got, expected))


def test_p0_00_the_rollback_status_values_are_one_to_one_with_its_exits():
    """🔴 §34a：**6 個狀態值，每一個恰好出現一次，且必為 `Fail`／`Emit-Result` 的引數。**

    📌 判準與 `apply_update.ps1` 那一題**同一個形狀**，而形狀本身是 B 退回我換來的：
    ```
    ❌ 我的 v1   f"status={s}" in src   ⇒ 逼 ps1 把格式複製 6 份
    ✅ B 的      數「引數」出現幾次      ⇒ 格式仍然只有一個地方知道
    ```
    🔑 `== 1` 而不是 `in`：`in` 只擋得住「漏掉」，
       `== 1` 還擋得住**兩條出口共用同一個值**（而 1:1 正是這裡的不變量）。

    ⚙️ 反向控制：`unknown` **不可以**是任何一條出口的狀態值。
    它是 `Fail($msg, $status = "unknown")` 的預設，
    存在的理由是「日後新增 `Fail` 忘了給狀態 ⇒ 被記成失敗」——
    ☠️ 而它一旦被當成某條出口的**正式**值，那道保險就失效了
       （忘記給值與刻意給值再也分不出來）。
    """
    assert ROLLBACK_PS1.exists(), "找不到 %s" % ROLLBACK_PS1
    src = ROLLBACK_PS1.read_text(encoding="utf-8", errors="replace")

    def as_argument(v):
        #: 只認「被當成引數傳進去」的那一種出現方式 —— 註解與訊息文字不算。
        return len(_re.findall(
            r'(?:Fail\s+.*?|Emit-Result\s+)"' + _re.escape(v) + r'"', src))

    for row in _ROLLBACK_EXITS:
        status = row[0]
        n = as_argument(status)
        assert n == 1, (
            "`%s` 在 `rollback_update.ps1` 裡以引數出現 %d 次，預期恰好 1 次。\n"
            "☠️ 0 次 ⇒ 那條出口印不出自己是誰；"
            "2 次以上 ⇒ 兩條出口共用一個值，而畫面分不出它們。\n"
            "🔑 值與出口 1:1 是刻意的：新增出口時沒有現成的值可借"
            "⇒ 作者必須加新值 ⇒ **而加新值會被這一題看到。**" % (status, n))

    assert as_argument("unknown") == 0, (
        "`unknown` 被當成某一條出口的正式狀態值了 ——\n"
        "☠️ 它是 `Fail` 的**預設**，用來接住「日後新增出口而忘了給狀態」。\n"
        "🔑 一旦某條出口刻意用它，忘記給值與刻意給值就再也分不出來了。")


# ══════════════════════════════════════════════════════════════════════
# §41d · `service` 的**理由**要有題守（A 指派）
# ══════════════════════════════════════════════════════════════════════
#
# A 的派工逐字：
#   「`:358` / `:361` 那兩條出口**必須報 `service=down`**，
#     且 `:355` robocopy 之前的出口不可以報 `down`。
#     ⚙️ 反向控制：把 `:358` 改成報 `up` ⇒ 必須紅。」
#
# ⚠️ **A 給的行號是舊的**（檔案長大了）。現況實測：
# ```
#   141  ServiceState=unknown          405  ServiceState=down      ← 唯一一處，欄位 0
#   179  not_prod_machine              421  robocopy → $BackendDir ← 第一次寫進正式機
#   188  ServiceState=up  (ping 成功)  425  copy_failed_backend    ← A 說的 :358
#   189  checkonly_ok                  428  copy_failed_frontend   ← A 說的 :361
#   193  checkonly_failed              620  unhealthy_not_rolled_back
#   199  bad_args                      707  unhealthy_rolled_back
#   202  package_missing               712  ServiceState=up
#   206  package_invalid               740  success
#   223  duplicate_version
#   279  backup_failed
#   327  migration_dryrun_failed
#   362  user_cancelled
# ```
# ⇒ **這裡一律用 status 值定位，不用行號**：行號會變，值不會
#    （值與出口 1:1 已經有題在守）。
#
# 🔑 **為什麼行號順序在這裡是「可以推論」的**（而一般情況不行）：
#    PowerShell 有分支，行號順序 ≠ 執行順序。
#    而這兩件事讓推論在**這一題**成立：
#      ① `= "down"` 全檔**只有一處**（已有題在守）
#         ⇒ 行號小於它的出口，**執行時不可能**是 down
#      ② 它在**欄位 0**（頂層，不在任何 if/try 裡）
#         ⇒ 行號大於它而中間沒有別的指派的出口，**執行時必定**是 down
#    ⚠️ 兩個前提**都寫成斷言**，不是寫成註解 —— 前提失效時要紅，不是要靜默。

_SERVICE_ASSIGN = _re.compile(r'^(\s*)\$script:ServiceState\s*=\s*"([^"]*)"')
_EXIT_SITE = _re.compile(r'(?:Fail\s+.*?|Emit-Result\s+)"([a-z_]+)"')


def _service_layout(ps1):
    """`(指派清單, 出口 → 行號)`，行號都是 1-based。"""
    lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()
    assigns, exits = [], {}
    for i, ln in enumerate(lines, 1):
        m = _SERVICE_ASSIGN.match(ln)
        if m:
            assigns.append((i, m.group(2), len(m.group(1))))
        for s in _EXIT_SITE.findall(ln):
            exits.setdefault(s, []).append(i)
    return assigns, exits


def test_p0_00_the_half_copied_exits_report_that_the_service_is_down():
    """🔴🔴 §41d：**已停服＋半複製的那兩條出口，必須報 `service=down`。**

    A 的派工理由逐字：
    > 「`:358` 是『已停服＋半複製＋`Fail()` 不做回滾』，
    >   而『服務停著』決定使用者要不要現在衝去開機。
    >   **沒有這一題，`service` 只是一個格式正確的欄位。**」

    ```
    報 down     ✅ 使用者知道要現在去開機
    報 unknown  ☠️ 「可能還活著吧」—— 而是我們自己把它停掉的
    報 up       ☠️☠️ 畫面說它活著，而它躺在那裡，磁碟還是半套用的
    ```
    ⚙️ **反向控制（A 指定的那一個）**：在這兩條出口之前塞一個
    `$script:ServiceState = "up"` ⇒ 這一題必須紅。
    ⇒ 所以斷言不是「`down` 在前面」，是「`down` 在前面**而中間沒有別的指派**」。

    ⚙️ **正對照**：`success` 那一條必須報 `up`。
    少了它，「把 `:712` 刪掉」會讓這一題照樣全綠，
    而**每一次成功的部署都會說服務停著** —— 那個方向一樣會讓人白跑一趟。
    """
    assigns, exits = _service_layout(APPLY_PS1)

    downs = [(ln, col) for ln, val, col in assigns if val == "down"]
    assert len(downs) == 1, (
        "`apply_update.ps1` 的 `= down` 有 %d 處，預期 1 處 —— "
        "**這一題的靜態推論以它為前提**。" % len(downs))
    down_ln, down_col = downs[0]
    assert down_col == 0, (
        "`= down` 縮排 %d 格 ⇒ 它在某個 `if`／`try` 裡面 ——\n"
        "☠️ 那表示它**可能不會被執行到**，而這一題卻據此斷言「必定是 down」。\n"
        "🔑 前提要寫成斷言，不是寫成註解：前提失效時要紅，不是要靜默。"
        % down_col)

    for status in ("copy_failed_backend", "copy_failed_frontend"):
        at = exits.get(status, [])
        assert len(at) == 1, (
            "`%s` 的出口有 %d 處，預期 1 處。" % (status, len(at)))
        exit_ln = at[0]
        assert down_ln < exit_ln, (
            "`%s` 在 :%d，而 `service=down` 設在 :%d —— **它報不出服務停著**。\n"
            "☠️ 已停服＋半複製＋`Fail()` 不做回滾，而畫面說 `unknown`。\n"
            "🔑 那個差別決定使用者要不要現在衝去開機（§34c／§41d）。"
            % (status, exit_ln, down_ln))
        between = [(ln, v) for ln, v, _ in assigns if down_ln < ln < exit_ln]
        assert not between, (
            "`%s`（:%d）與 `service=down`（:%d）之間又有指派：%s\n"
            "☠️ 那條出口報的會是後面那個值，而不是 `down`。\n"
            "⚙️ 這正是 A 指定的反向控制：把它改成報 `up` ⇒ 這一題要紅。"
            % (status, exit_ln, down_ln,
               ", ".join(":%d=%s" % b for b in between)))

    # ⚙️ 正對照 —— 成功那一條要報 `up`，否則刪掉 `:712` 也照樣全綠。
    ok_at = exits.get("success", [])
    assert len(ok_at) == 1, "`success` 出口有 %d 處，預期 1 處。" % len(ok_at)
    before_ok = [(ln, v) for ln, v, _ in assigns if ln < ok_at[0]]
    assert before_ok and before_ok[-1][1] == "up", (
        "`success`（:%d）之前最後一個 `service` 指派是 %s ——\n"
        "☠️ 一次**成功**的部署會說服務停著 ⇒ 使用者一樣白跑一趟去開機。\n"
        "🔑 這是正對照：少了它，「把最後那個 `= up` 刪掉」不會被任何題看到。"
        % (ok_at[0], (":%d=%s" % before_ok[-1]) if before_ok else "（一個都沒有）"))


def test_p0_00_no_exit_before_the_copy_can_claim_the_service_is_down():
    """🔴 §41d 的另一半：**robocopy 之前的出口不可以報 `down`。**

    ☠️ 對稱的那個錯：`= "down"` 被搬到 Step 0／Step 1
    ⇒ `not_prod_machine`／`package_missing`／`user_cancelled` 這些
    **什麼都還沒碰**的出口會說「服務停著」——
    🔑 而伺服器**好端端跑著**，使用者白跑一趟去開機。

    📌 與 §41a 同一個病：**一個比實際嚴重的狀態，代價是使用者不再相信那個畫面。**
    ⚠️ 而它與「報得比實際安全」不一樣 —— 後者會害人不去開機（§41d 上一題），
    兩個方向**都要有題守**，因為修其中一個很容易把另一個推過頭。
    """
    assigns, exits = _service_layout(APPLY_PS1)
    lines = APPLY_PS1.read_text(encoding="utf-8", errors="replace").splitlines()

    writes = [i for i, ln in enumerate(lines, 1) if _WRITES_INTO_PROD.match(ln)]
    assert writes, (
        "「寫進正式機」的錨點一行都沒命中 —— **儀器失效**，"
        "這一題會因為量不到而綠。")
    first_write = writes[0]

    down_lns = [ln for ln, val, _ in assigns if val == "down"]
    early = sorted((ln, s) for s, lns in exits.items() for ln in lns
                   if ln < first_write)
    assert early, (
        "第一次寫進正式機（:%d）之前一條出口都沒抓到 —— **儀器失效**。\n"
        "🔑 〈沒抓到要被解釋成儀器失效，不可以被解釋成乾淨〉。" % first_write)

    bad = [(ln, s) for ln, s in early if any(d < ln for d in down_lns)]
    assert not bad, (
        "這些出口在第一次寫進正式機（:%d）**之前**，卻會報 `service=down`：\n  "
        % first_write
        + "\n  ".join(":%d %s" % b for b in bad)
        + "\n☠️ 那時候伺服器還好端端跑著 —— 畫面叫使用者去開一台沒停的機器。\n"
          "🔑 `= down` 只能設在**我們自己把它停掉之後**。")


# ══════════════════════════════════════════════════════════════════════
# §41a／§41b · `rolled_back`：一份值域，**而文案由 `action` 決定**
# ══════════════════════════════════════════════════════════════════════
#
# A 的裁示逐字（`§41a`）：
#   「值域統一成 `not_applied`（一份值域，避免分岔），
#     而畫面的文案由 `action` 決定：
#       action=deploy    not_applied ⇒ 「正式機沒有被碰過」
#       action=rollback  not_applied ⇒ 「還原沒有開始，正式機維持在你按回滾之前的樣子」
#     ⚙️ 守門：兩個 action 的文案相同 ⇒ 紅（那表示有人把它「統一」掉了）」
#
# 🔴 **為什麼這一層存在**（A 指出，B 與我都沒看到）：兩支腳本的**參考點不同**。
# ```
#   apply 的 not_applied     ＝ 正式機**完全沒被碰過**
#   rollback 的同一種情境    ＝ 還原沒開始，正式機維持在**你按回滾之前**的樣子
#                               ⚠️ 而那個樣子通常是「一次失敗的部署剛動過它」
# ```
# ☠️ 直接共用而不處理這一層 ⇒ 畫面會說「正式機沒有被碰過」，
#    而它剛剛才被一次失敗的部署動過。
#
# ⚠️ **我釘的接縫**：`describe_rolled_back(value, action) -> str`
#    現況 `deploy_dashboard.py:321` 把它解析出來就丟掉（`_rolled_back`）
#    ⇒ 這個欄位一路走到畫面之前**沒有任何地方把它變成人話**。
#    名字要改**退回給我**，不要自己改題。

#: 🔴 `§53` 定版**六個名字**（不是「維持 6 個」—— 先前也是 6，而組成不同）。
#: ```
#:   unknown    刪除   它在 :98 改成 not_applied 之後沒有任何產生路徑
#:   restoring  新增   一次 deploy 執行有**兩個寫入階段**（套用／自動回滾），
#:                     一個值表達不了兩個
#: ```
#: ⚠️ **這個常數就是裁示的落點。** A 記進 §6：
#:    allowlist 型的守門，**值域縮小時不會自己紅**（超集永遠比較好過）
#:    ⇒ 裁示要寫出那個數字落在哪一個識別字上，不能只寫「去掉某個值」。
#: 📌 所以下面那一題直接釘這六個名字 —— 讓「安靜地放寬」在 diff 上藏不住。
_ROLLED_BACK_DOMAIN = (
    "not_applied", "applied", "applied_no_restore",
    "restoring", "restored", "restored_unhealthy",
)


def test_53_the_value_domain_constant_is_exactly_the_six_names():
    """⚙️ **值域常數本身的變更偵測** —— 它是 `§53` 裁示的落點。

    ☠️ allowlist 型的守門**值域縮小時不會自己紅**：
    清單留 6 而規格定 5 ⇒ 超集檢查照樣全綠，**而你不會回來看它**。
    🔑 ⇒ 這一題不驗產品，它驗**我自己的清單有沒有被安靜地改動**。
    ⚠️ 它擋不到「連這一題一起改」—— 那是刻意的：那一改在 diff 上藏不住，
       而「安靜地多放行一個值」不會。
    """
    assert _ROLLED_BACK_DOMAIN == (
        "not_applied", "applied", "applied_no_restore",
        "restoring", "restored", "restored_unhealthy",
    ), "`_ROLLED_BACK_DOMAIN` 與 `§53` 定版的六個名字不一致：%s" % (
        list(_ROLLED_BACK_DOMAIN),)


def _is_fallback(describe, value, action):
    """`describe_rolled_back` 對這個值回的是**退路**（而不是一句真的文案）嗎。

    🔑 為什麼需要它：退路是一句**非空、而且不等於任何真文案**的字串
    ⇒ 「非空」「與別的值不同」這兩種斷言**都會被它騙過去**。
    ⚠️ 今天真的騙過去一次：`restoring` 還沒有文案，
       而 `..._does_not_borrow_a_sentence_that_means_the_opposite` 照樣綠。

    做法：拿一個**確定不存在**的值去量退路的形狀，再把值代換回來比對。
    """
    bogus = "__c_probe_not_a_real_value__"
    shape = describe(bogus, action)
    return describe(value, action) == shape.replace(bogus, value)


def test_p0_00_the_rolled_back_wording_depends_on_the_action():
    """🔴🔴 §41a 守門：**同一個機器值，兩個 action 要講出不同的人話。**

    ☠️ 文案相同 ⇒ 有人把它「統一」掉了 ⇒ 回滾前的畫面會說
    **「正式機沒有被碰過」**，而它剛剛才被一次失敗的部署動過。
    🔑 而使用者正是在**剛出事、正在回滾**的時候看它。

    ⚙️ **反向控制（擋一種會讓上面那條全綠的作弊）**：
    ```
    ❌ return 基本文案 + "（回滾）"      ⇒ 兩個 action 不同了，而意思沒變
    ```
    ⇒ 所以還要求**兩句話互不為對方的子字串** ——
    A 給的那兩句（「正式機沒有被碰過」／「還原沒有開始，正式機維持在你按回滾之前的樣子」）
    本來就滿足它。
    📌 這不是在釘 A 那兩句的**字面**（B 要怎麼寫由 B 決定），
       是在釘「它們得是兩句真的不同的話」。

    ⚠️ 同時要求：6 個值**每一個**在兩個 action 下都給得出非空的人話，
    而且不可以把機器值原樣吐回去（`not_applied` 不是人話）。
    """
    describe = _need("describe_rolled_back")

    for value in _ROLLED_BACK_DOMAIN:
        for action in ("deploy", "rollback"):
            text = describe(value, action)
            assert isinstance(text, str) and text.strip(), (
                "`describe_rolled_back(%r, %r)` 回傳 %r ——\n"
                "☠️ 畫面上會是一片空白，而使用者看不出它是「沒有資料」"
                "還是「狀態正常」。" % (value, action, text))
            assert not _is_fallback(describe, value, action), (
                "`describe_rolled_back(%r, %r)` 回的是**退路**不是文案 ——" % (value, action)
                + chr(10) +
                "☠️ 退路是一句非空、而且不等於任何真文案的字串 ⇒ "
                "「非空」與「與別的值不同」這兩種斷言**都騙得過去**。" + chr(10) +
                "🔑 笛卡兒積那一題會指出缺的是哪一格（§54c）。")
            assert text.strip() != value, (
                "`describe_rolled_back(%r, %r)` 把機器值原樣吐回去了 ——\n"
                "🔑 `%s` 不是人話，而這支函式存在的唯一理由就是把它變成人話。"
                % (value, action, value))

    d = describe("not_applied", "deploy")
    r = describe("not_applied", "rollback")
    assert d != r, (
        "`not_applied` 在 `deploy` 與 `rollback` 下的文案**一樣**：%r\n"
        "☠️ 那表示有人把它「統一」掉了 ⇒ 回滾前的畫面會說「正式機沒有被碰過」，\n"
        "   而它剛剛才被一次失敗的部署動過（§41a 逐字）。\n"
        "🔑 參考點不同：deploy 的 `not_applied` 是「完全沒被碰過」，\n"
        "   rollback 的是「還原沒開始，維持在你按回滾之前的樣子」。" % d)
    assert d not in r and r not in d, (
        "兩個 action 的文案是**包含關係**：\n"
        "  deploy   %r\n  rollback %r\n"
        "☠️ 那是在同一句話後面加個標籤，意思沒有變 ——\n"
        "🔑 而 §41a 要的是兩句**參考點不同**的話，不是一句話加後綴。" % (d, r))


def test_p0_00_the_rollback_script_starts_from_a_true_statement():
    """🔴 §41b：**`rollback_update.ps1` 的 `ProdState` 初始值要是 `not_applied`。**

    A 的裁示逐字：
    > 「初始值必須是**對當下狀態為真的陳述**，
    >   `rollback_update.ps1:85` 要從 `unknown` 改成 `not_applied`。」

    ```
    unknown 在畫面上的意思   「去現場看一眼」
    那四條早退出口的實情      我知道，而且答案是「還原沒有開始」
    ```
    ☠️ 用 `unknown` 表達一個**已知**的事實 ＝ 叫人去查一件已經有答案的事。
    🔑 而這個方向**安全**（不宣稱超過它知道的）⇒ 不會壞、不會被報修 ——
       〈降級之後它還是會動〉：**代價全部落在使用者的時間上，而那一格沒有人在量。**

    ⚠️ **這一題會讓 `rolled_back=unknown` 變成沒有任何路徑產生得出來**
    （兩支腳本掃過：`unknown` 只出現在這一個初始值）。
    A 裁定值域仍保留它，當「真的不知道」時的誠實答案。
    📌 **而我刻意不替它寫題** ——〈防著不存在問題的測試永遠是綠的〉。
    ⇒ 哪天有人讓它產生得出來，要發編號，不是順手補一題。
    """
    assert ROLLBACK_PS1.exists(), "找不到 %s" % ROLLBACK_PS1
    lines = ROLLBACK_PS1.read_text(encoding="utf-8", errors="replace").splitlines()
    assign = _re.compile(r'^\s*\$script:ProdState\s*=')
    firsts = [(i, ln) for i, ln in enumerate(lines, 1) if assign.match(ln)]
    assert firsts, (
        "`rollback_update.ps1` 裡一個 `$script:ProdState =` 都沒抓到 ——\n"
        "🔑 **儀器失效**，不是「初始值正確」。")

    ln_no, first = firsts[0]
    vals = _re.findall(r'"([a-z_]+)"', first)
    assert vals, "第一個 `ProdState` 指派（:%d）抓不到值：%s" % (ln_no, first.strip())
    assert vals[0] == "not_applied", (
        "`rollback_update.ps1:%d` 的 `ProdState` 初始值是 `%s`，"
        "§41b 裁定要是 `not_applied`。\n"
        "☠️ 四條「什麼都還沒碰」的早退出口會報 `unknown`，"
        "而畫面上 `unknown` 的意思是「去現場看一眼」——\n"
        "🔑 那四條恰恰是**不必去看**的那幾條。使用者白跑一趟。"
        % (ln_no, vals[0]))


@pytest.mark.parametrize("ps1", [APPLY_PS1, ROLLBACK_PS1],
                         ids=["apply_update", "rollback_update"])
def test_p0_00_the_rolled_back_value_domain_is_the_six(ps1):
    """🔴 §41b→§53：**`rolled_back` 值域定版六個名字，不可以多出第七個。**

    ⚠️ `§53` 換過組成（`unknown` 刪、`restoring` 新增）而**數量仍是 6** ——
    🔑 「6 個」這個數字本身**不帶資訊**，要看的是上面那六個名字。

    ⚠️ 這一題的錨點要抓得到**三元運算式**那一種寫法：
    ```
    $script:ProdState = if ($rolledBackHealthy) { "restored" } else { "restored_unhealthy" }
    ```
    🔑 只比對 `= "值"` 的正則**看不到這一行** ——
       〈查詢的形狀決定了答案的可能集合〉。
    ⇒ 改成：先認出「這是一行 `ProdState` 指派」，再把那一行**所有**引號值都收進來。
    """
    assert ps1.exists(), "找不到 %s" % ps1
    lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()
    assign = _re.compile(r'^\s*\$script:ProdState\s*=')
    seen = {}
    for i, ln in enumerate(lines, 1):
        if assign.match(ln):
            for v in _re.findall(r'"([a-z_]+)"', ln):
                seen.setdefault(v, i)
    assert seen, (
        "`%s` 裡一個 `$script:ProdState =` 都沒抓到 —— **儀器失效**，不是乾淨。"
        % ps1.name)

    bad = {v: i for v, i in seen.items() if v not in _ROLLED_BACK_DOMAIN}
    assert not bad, (
        "`%s` 的 `rolled_back` 出現值域外的值：%s\n"
        "§41b 定版 6 個：%s\n"
        "☠️ dashboard 的值域檢查會把它判成失敗 ⇒ 一次成功的動作被記成失敗。"
        % (ps1.name,
           ", ".join(":%d=%s" % (i, v) for v, i in sorted(bad.items())),
           ", ".join(_ROLLED_BACK_DOMAIN)))


# ══════════════════════════════════════════════════════════════════════
# §42 · `unknown` 當金絲雀 ／ §42b · 讓遺漏不可能
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ps1", [APPLY_PS1, ROLLBACK_PS1],
                         ids=["apply_update", "rollback_update"])
def test_p0_00_no_explicit_exit_can_emit_rolled_back_unknown(ps1):
    """🔴 §42 守門：**任何顯式出口都不可以印出 `rolled_back=unknown`。**

    A 的定版逐字：
    > 「`unknown` 留在值域，但它的角色是**金絲雀不是狀態**」

    ⚠️ **而我要把這一題守得到與守不到的分開寫**，否則下一個人會高估它：
    ```
    ✅ 它守得到   有人把 `$script:ProdState = "unknown"` 加回來
                  （`:85` 現在就是，這一題因此是**紅的**，與 §41b 同一個修）
    ❌ 它守不到   「新增一條出口而漏設值」
    ```
    🔑 **守不到的理由在 §42 自己的段落裡**：
    > 「而『忘記設值』本來就安全：B 的設計把危險值設在動作之前
    >   ⇒ 任何 robocopy 之後的出口都繼承 `applied_no_restore`」

    ⇒ 漏設值的出口**繼承前一個值**，不會變成 `unknown`。
    📌 §42 另一句「具體來源：B 的 `Fail($msg, $status="unknown")` 那個預設」
       **講的是另一個欄位**：那個預設餵進 `$status` ⇒ 印在 `status=` 那一格，
       而 `rolled_back=` 印的是 `$script:ProdState`。
       ⇒ `status=unknown` 的金絲雀是**活的**（`_STATUS_ALL` 不含它 ⇒ fail-closed，
         且本檔 `..._one_to_one_with_its_exits` 已經在守）；
         `rolled_back=unknown` 在 `:85` 改掉之後**沒有任何產生路徑**。
    ⚠️ 所以這一題是**對一個刻意的缺席做變更偵測**，不是「金絲雀在響」。
       寫清楚是為了不讓人以為漏設值有東西在接。
    """
    assert ps1.exists(), "找不到 %s" % ps1
    lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()
    assign = _re.compile(r'^\s*\$script:ProdState\s*=')
    hits = [(i, ln.strip()[:80]) for i, ln in enumerate(lines, 1)
            if assign.match(ln) and "unknown" in ln]
    assert not hits, (
        "`%s` 有 `rolled_back` 被設成 `unknown` 的地方：\n  " % ps1.name
        + "\n  ".join(":%d %s" % h for h in hits)
        + "\n☠️ `unknown` 在畫面上的意思是「去現場看一眼」，"
          "而這些出口**知道**答案。\n"
          "🔑 §42：它的角色是**金絲雀不是狀態** —— 不可以有人拿它當一個正常值用。")


def test_p0_00_an_unknown_action_blows_up_instead_of_guessing():
    """🔴 §42b：**`decide_outcome` 對非 `deploy`／`rollback` 的 `action` 要拋錯。**

    A-2 提、A 採用，理由是〈計數器要有落點〉的變體：
    > 「`build` 哪天真的接進 dashboard，**誰會記得回來加**？
    >   靠『以後記得』＝沒有落點。」

    ⇒ 拋錯讓那一天**當場爆**，不需要任何人記得 ——
    🔑 而它同時讓「不加 `build ⇒ False` 那個案例」這個決定變成**安全的**：
       遺漏變成不可能，不是靠一題去守。〈修作法不要修結果〉。

    ⚠️ **不釘例外的型別與訊息字面**（B 決定），只釘三件事：
    ```
    ① 沒見過的 action ⇒ 一定要拋，不可以**回傳**一個判定
    ② 例外訊息裡要有那個 action 的名字 —— 否則排錯的人得去讀碼
    ③ ⚙️ 正對照：deploy／rollback **照常運作**
       少了它，`raise` 寫在函式第一行也會讓上面兩條全綠
    ```
    """
    decide = _need("decide_outcome")
    good = "更新完成\n" + _result_line("success", "applied", service="up")

    for action in ("build", "", "Deploy", "deploy ", "restore", None):
        try:
            got = decide(0, good, action=action)
        except Exception as exc:                      # noqa: BLE001 —— 型別由 B 定
            assert str(action) in str(exc), (
                "action=%r 有拋錯，而訊息裡沒有那個名字：%s\n"
                "🔑 排錯的人拿到的第一份線索就是這句話。" % (action, exc))
        else:
            pytest.fail(
                "`decide_outcome(action=%r)` **回傳了** %r 而不是拋錯。\n"
                "☠️ 一個沒見過的動作拿到了一個判定 —— 那個判定是猜的。\n"
                "🔑 §42b：拋錯讓「以後記得回來加」變成不需要記得。" % (action, got))

    # ⚙️ 正對照 —— 少了它，`raise` 寫在第一行也會讓上面全綠。
    assert decide(0, good, action="deploy") == "succeeded"
    assert decide(0, _PROTOCOL_LINE + "\n回滾完成\n"
                  + _result_line("rollback_ok", "restored", service="up"),
                  action="rollback") == "succeeded"


def test_p0_00_the_exempt_branch_never_reaches_decide_outcome():
    """🔴 §42b 的**前提**要有題守：`build` 不可以走進 `decide_outcome`。

    A 寫：「⚠️ 前提是 `build` 走 `_PROTOCOL_EXEMPT` 確實不會進到 `decide_outcome`
    —— C 已經有一題釘住豁免集合只有 `build` 一個名字，**那一題同時保住了這個前提**。」

    ⚠️ **那一題只釘住集合的內容，沒有釘住順序。** 兩件事：
    ```
    已經有題守  _PROTOCOL_EXEMPT == {"build"}        ← 誰在豁免名單裡
    沒有題守    豁免分支裡不會呼叫 decide_outcome     ← 豁免到底有沒有生效
    ```
    ☠️ 少了這一題，`§42b` 的拋錯落地那天，**每一次打包都會拋例外** ——
    而症狀是「打包壞了」，沒有人會想到是一個為了防呆而加的 `raise`。
    🔑 〈防護的副作用落在盲側〉：加防護時要問
       「**它擋不到的那一側**會不會更難看見」。

    📌 用 AST 不用字串比對：`decide_outcome` 這個名字在檔裡扮演多種角色
       （定義／呼叫／docstring／註解）⇒ 〈這個字串在檔裡扮演幾種角色？
       答案大於一就不能用 `find`〉。
    """
    import ast as _ast

    path = Path(_dash().__file__)
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    fn = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.FunctionDef) and n.name == "_run_job"), None)
    assert fn is not None, (
        "`deploy_dashboard.py` 裡找不到 `_run_job` —— **前提不成立**，"
        "不是「順序正確」。")

    def mentions_exempt(node):
        return any(isinstance(n, _ast.Name) and n.id == "_PROTOCOL_EXEMPT"
                   for n in _ast.walk(node))

    branches = [n for n in _ast.walk(fn)
                if isinstance(n, _ast.If) and mentions_exempt(n.test)]
    assert len(branches) == 1, (
        "`_run_job` 裡以 `_PROTOCOL_EXEMPT` 為條件的分支有 %d 個，預期 1 個 ——\n"
        "🔑 0 個 ⇒ **儀器失效**（豁免機制改寫了，這一題量不到）。" % len(branches))

    def calls_decide(nodes):
        out = []
        for node in nodes:
            for n in _ast.walk(node):
                if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                        and n.func.id == "decide_outcome"):
                    out.append(n.lineno)
        return out

    bad = calls_decide(branches[0].body)
    assert not bad, (
        "豁免分支（`if action in _PROTOCOL_EXEMPT`）裡呼叫了 `decide_outcome`，"
        "在 :%s ——\n"
        "☠️ `§42b` 的拋錯一落地，**每一次打包都會拋例外**，\n"
        "   而症狀是「打包壞了」，沒有人會想到是一個防呆用的 `raise`。\n"
        "🔑 豁免要在**呼叫之前**生效，不是在裡面被特判。"
        % ", ".join(str(b) for b in bad))

    # ⚙️ 正對照：另一側**必須**呼叫它 —— 否則「兩邊都不呼叫」也會讓上面全綠，
    #    而那表示 `decide_outcome` 根本沒有被接上（`reminder_stage()` 那個形狀）。
    other = calls_decide(branches[0].orelse)
    assert other, (
        "非豁免分支裡**沒有**呼叫 `decide_outcome` ——\n"
        "☠️ 一支接縫寫好了而沒有人呼叫，跟沒有寫是一樣的。\n"
        "🔑 這是正對照：少了它，「兩邊都不呼叫」會讓這一題全綠。")


# ══════════════════════════════════════════════════════════════════════
# §54c · 🔴 根治的是守門不是補文案：**值域 × action 的笛卡兒積要完整**
# ══════════════════════════════════════════════════════════════════════
#
# A 的裁示逐字：
#   「自動回滾這個缺口的成因，就是**deploy 那張表少了一個表達還原階段的值**
#     —— 完整性守門會當場抓到它。而它比逐條補文案強：
#     **下一個新增的值，忘記補另一張表時會立刻紅。**」
#
# 🔑 〈修作法不要修結果〉：判準是「這個修法會不會讓下一次不可能發生」。
#    逐條補文案答「會少一點」；笛卡兒積守門答「會」。
#
# ⚠️ **我釘的接縫**：`_ROLLED_BACK_TEXT`（B 已存在的模組層常數）。
#    名字要改**退回給我**。與本檔釘 `_PROTOCOL_EXEMPT` 同一個形狀。


def test_54c_every_value_has_wording_in_every_action_table():
    """🔴🔴 §54c：**值域 × action 的笛卡兒積完整 —— 缺一格就紅。**

    ```
    值域 6 個 × action 2 個 = 12 格，**每一格都要有非空的人話**
    ```
    ☠️ 缺一格的後果不是「畫面空白」，是**靜默退回一句意思相反的話**：
       自動回滾走的 `action` 是 `deploy`，而 deploy 表原本沒有
       「正在還原」這個值 ⇒ 最接近的是 `applied_no_restore`＝
       「新版只寫了一半就中斷，**而且沒有還原**」——**方向相反**。

    ⚙️ 多出來的格子也要紅（不只驗「缺」）：
       一個**有文案而不在值域裡**的值，表示有人只改了一邊。
       📌 現況會抓到 `unknown`（`§53` 已把它從值域刪掉，而文案還留著）。
    """
    mod = _dash()
    table = getattr(mod, "_ROLLED_BACK_TEXT", None)
    assert table is not None, (
        "`deploy_dashboard.py` 缺少 `_ROLLED_BACK_TEXT` ——" + chr(10) +
        "🔑 笛卡兒積完整性要有一個**可以數**的地方；"
        "散在 `if/elif` 裡的話數不出「缺哪一格」。" + chr(10) +
        "⚠️ 名字可以換（**退回給我**，不要自己改題）。")

    want = set(_ROLLED_BACK_DOMAIN)
    problems = []
    for action, sub in sorted(table.items()):
        have = set(sub)
        for v in sorted(want - have):
            problems.append("缺　%-10s × %-18s" % (action, v))
        for v in sorted(have - want):
            problems.append("多　%-10s × %-18s（不在值域裡）" % (action, v))
        for v in sorted(want & have):
            if not (isinstance(sub[v], str) and sub[v].strip()):
                problems.append("空　%-10s × %-18s = %r" % (action, v, sub[v]))
    assert not problems, (
        "值域 × action 的笛卡兒積不完整（值域 %d 個 × action %d 個 = %d 格）："
        % (len(want), len(table), len(want) * len(table)) + chr(10) + "  "
        + (chr(10) + "  ").join(problems) + chr(10) +
        "☠️ 缺一格不是畫面空白 —— 是**靜默退回一句意思相反的話**。" + chr(10) +
        "🔑 §54c：根治的是這道守門，不是逐條補文案。")


def test_54c_the_two_actions_never_share_a_sentence():
    """🔴 §54c 的另一半：**同一個值，兩個 action 的文案不可以相同。**

    🔑 值域共用一份、而**語意隨 `action` 變**，A 裁定那是**刻意的**：
    > 「機器值記的是『這一次執行**寫到哪一步**』，
    >   而那一步的意義取決於**它當時在寫什麼**。」

    ☠️ 兩句相同 ⇒ 那個「刻意」被還原成一句通用的話 ⇒
       回滾前的畫面會說「正式機沒有被碰過」，而它剛剛才被一次失敗的部署動過。

    ⚙️ 而它同時擋住 `§41a` 那個作弊（`基本文案 + "（回滾）"`）：
       本題只要求**不相同**，`§41a` 那題再加一層「互不為對方的子字串」。
    """
    mod = _dash()
    table = getattr(mod, "_ROLLED_BACK_TEXT", None)
    assert table is not None, "缺少 `_ROLLED_BACK_TEXT` —— 見上一題。"
    actions = sorted(table)
    assert len(actions) >= 2, (
        "文案表只有 %d 個 action —— **儀器失效**，這一題比不出東西。" % len(actions))

    same = []
    for v in sorted(set(_ROLLED_BACK_DOMAIN)):
        seen = {}
        for a in actions:
            t = table[a].get(v)
            if t is None:
                continue
            if t in seen:
                same.append("%-18s %s 與 %s 同一句：%r" % (v, seen[t], a, t))
            seen[t] = a
    assert not same, (
        "有值在兩個 action 下是同一句話：" + chr(10) + "  "
        + (chr(10) + "  ").join(same) + chr(10) +
        "☠️ 參考點不同這件事被抹平了 ——" + chr(10) +
        "   deploy 的 `not_applied`＝正式機完全沒被碰過；" + chr(10) +
        "   rollback 的＝還原沒開始，而它通常剛被一次失敗的部署動過。")


# ══════════════════════════════════════════════════════════════════════
# §53 · `RP1`–`RP3`：復原路徑上的每一個複製都要說得出自己失敗了
# ══════════════════════════════════════════════════════════════════════
#
# 盤點（兩支檔案**所有**的 robocopy，不是只看 A-2 指的那一段）：
# ```
#   apply_update.ps1    :338 :339   製作快照（正式機 → 快照）    🔴 無檢查  RP1
#   apply_update.ps1    :422 :427   套用新版（包   → 正式機）    ✅ 有檢查
#   apply_update.ps1    :632 :633   自動回滾（快照 → 正式機）    🔴 無檢查  RP2
#   rollback_update.ps1 :179 :180   手動回滾（快照 → 正式機）    🔴 無檢查  RP3
# ```
# 🔑 **唯一有檢查的那一對，是「套用新版」那一對。**
#    A 升成 §6：檢查做在**前進路徑**而沒做在**復原路徑**是一種常見的不對稱 ——
#    因為前進路徑天天在跑、錯了馬上看得到；
#    **復原路徑很少跑，而它跑的時候你已經在處理另一個問題了。**
#
# ☠️ 而 `RP1` 是三個裡最嚴重的：那兩行做的是**快照本身**。
#    靜默失敗 ⇒ 快照殘缺 ⇒ **沒有人知道，直到有一天要用它回滾。**
#    📌 A 的判準：「這東西是**平常用的**，還是**出事才用的**」——
#       後者一定要在製作當下就擋，因為那一刻沒有第二次機會。
#
# ⚠️ **錨點錨在「來源→目的地」的方向上，不錨在 `robocopy` 這個字**：
#    同一支檔案裡它扮演兩種角色（做快照／還原快照），而方向相反。
#    📌 B 自陳第一次用 `robocopy\b` 掃抓到 11 行，其中 3 行是**註解**
#       —— 它把命中逐行印出來才看到。

#: 正式機 → 快照（`RP1`：做快照）
_ROBO_TO_SNAPSHOT = _re.compile(
    r'^\s*robocopy\s+\$(?:Backend|Frontend)Dir\s+\(Join-Path\s+\$rollbackDir\b')
#: 快照 → 正式機（`RP2`／`RP3`：還原）
_ROBO_TO_PROD = _re.compile(
    r'^\s*robocopy\s+\(Join-Path\s+\$rollbackDir\s+"(?:backend|frontend)"\)'
    r'\s+\$(?:Backend|Frontend)Dir\b')


def _guarded(lines, idx, window=3):
    """第 `idx` 行（0-based）之後 `window` 行內，有沒有一個檢查結束碼並 `Fail` 的守門。

    ⚠️ 同時要求 `$LASTEXITCODE` **與** `Fail` —— 只檢查不中止等於沒檢查。
    """
    for ln in lines[idx: idx + 1 + window]:
        if "$LASTEXITCODE" in ln and _re.search(r'\bFail\b', ln):
            return ln.strip()
    return None


def _robo_rows(ps1, pattern):
    lines = ps1.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines, [i for i, ln in enumerate(lines)
                   if pattern.match(ln) and not ln.strip().startswith("#")]


def test_rp1_the_snapshot_copies_say_when_they_failed():
    """🔴🔴 `RP1`：**做快照的那兩個 robocopy 要檢查結束碼。**

    ```
    :338 robocopy $BackendDir  → 快照/backend    | Out-Null    ← 失敗沒有人知道
    :339 robocopy $FrontendDir → 快照/frontend   | Out-Null
    ```
    ☠️ **靜默失敗 ⇒ 快照殘缺 ⇒ 而它沒有任何症狀**，直到有一天真的要用它回滾。
    🔑 **那一天正是最不能出事的一天**，而那一刻沒有第二次機會。

    📌 對照組就在同一支檔案裡（`:422`／`:427` 套用新版**有**檢查）——
       ⇒ 這一題不是「加一個沒人做過的東西」，是**把已有的紀律補到漏掉的那一半**。

    ⚙️ 斷言要求 `$LASTEXITCODE` **與** `Fail` 同時出現：
       只檢查而不中止等於沒檢查（照樣走下去，快照照樣殘缺）。
    """
    lines, rows = _robo_rows(APPLY_PS1, _ROBO_TO_SNAPSHOT)
    assert len(rows) == 2, (
        "「正式機 → 快照」的 robocopy 抓到 %d 行，預期 2 行（backend／frontend）——\n"
        "🔑 0 行 ⇒ **儀器失效**，這一題會因為量不到而綠。" % len(rows)
        + "".join("\n  :%d %s" % (i + 1, lines[i].strip()[:80]) for i in rows))

    bad = [i for i in rows if _guarded(lines, i) is None]
    assert not bad, (
        "做快照的 robocopy 沒有檢查結束碼：\n  "
        + "\n  ".join(":%d %s" % (i + 1, lines[i].strip()[:80]) for i in bad)
        + "\n☠️ 失敗了不會有人知道 ⇒ 快照殘缺 ⇒ **而它沒有任何症狀**，\n"
          "   直到有一天真的要用它回滾 —— 那一天沒有第二次機會。\n"
          "📌 同一支檔案的 `:422`／`:427` 就是對照：`-ge 8 ⇒ Fail`。")


def test_rp1_each_snapshot_failure_has_its_own_status():
    """🔴 `RP1` 的值：`snapshot_failed_backend` ／ `snapshot_failed_frontend`，**各一次**。

    ⚙️ `== 1` 不是 `in`：`in` 只擋得住「漏掉」，
       `== 1` 還擋得住**兩條出口共用一個值**（而值與出口 1:1 是這裡的不變量）。

    🔑 **而 B 補的第三條就是這件事**：
    ```
    做快照失敗   ⇒ 正式機**還沒被碰**    ⇒ 重跑就好
    還原到一半   ⇒ 正式機**半還原**      ⇒ 要人去看
    ☠️ 共用一個 status 的話，這兩件事長得一樣。
    ```
    """
    src = APPLY_PS1.read_text(encoding="utf-8", errors="replace")
    for status in ("snapshot_failed_backend", "snapshot_failed_frontend"):
        n = len(_re.findall(
            r'(?:Fail\s+.*?|Emit-Result\s+)"' + _re.escape(status) + r'"', src))
        assert n == 1, (
            "`%s` 以引數出現 %d 次，預期恰好 1 次。\n"
            "☠️ 0 次 ⇒ 那條出口印不出自己是誰；2 次以上 ⇒ 兩條出口共用一個值。\n"
            "🔑 「做快照失敗」與「還原到一半」共用一個值的話，"
            "前者該重跑、後者該叫人，而畫面分不出來。" % (status, n))


def test_rp1_a_failed_snapshot_says_prod_was_not_touched():
    """🔴 `RP1` 的 `rolled_back`：做快照失敗時，正式機**一個檔都沒被動**。

    A 裁定那兩條出口的 `rolled_back` 是 `not_applied`。
    靜態上它成立的條件是：**從初始值到快照那兩行之間，沒有別的 `ProdState` 指派。**
    ⚠️ 而那個條件要**驗**，不是假設 —— 日後有人在 Step 1/2 加一個指派，
       這兩條出口會開始報一個比實際嚴重的狀態，而**沒有東西會紅**。

    ☠️ 報得比實際嚴重的代價：使用者以為正式機被動過，去做一次不必要的回滾
    —— **在一台其實沒事的機器上**。
    """
    lines, rows = _robo_rows(APPLY_PS1, _ROBO_TO_SNAPSHOT)
    assert rows, "「正式機 → 快照」的錨點一行都沒命中 —— **儀器失效**。"
    first = rows[0]

    assign = _re.compile(r'^\s*\$script:ProdState\s*=')
    before = [(i + 1, lines[i].strip()[:70]) for i in range(first)
              if assign.match(lines[i])]
    assert len(before) == 1, (
        "做快照之前的 `ProdState` 指派有 %d 個，預期 1 個（初始值）：\n  "
        % len(before) + "\n  ".join(":%d %s" % b for b in before)
        + "\n🔑 多一個 ⇒ 快照出口報的不再是 `not_applied`，而沒有東西會紅。")
    assert '"not_applied"' in lines[before[0][0] - 1], (
        "做快照之前唯一的 `ProdState` 指派不是 `not_applied`：:%d %s\n"
        "☠️ 那兩條出口會報一個**比實際嚴重**的狀態 ⇒ "
        "使用者在一台其實沒事的機器上做一次不必要的回滾。" % before[0])


#: `(檔, status 前綴, 編號)` —— `rollback_update.ps1` 沿用它自己的 `rollback_` 前綴。
_RESTORE_SITES = [
    (None, "restore_copy_failed", "RP2"),      # apply_update.ps1（自動回滾）
    (None, "rollback_copy_failed", "RP3"),     # rollback_update.ps1（手動回滾）
]


@pytest.mark.parametrize("ps1,prefix,rp", [
    (APPLY_PS1, "restore_copy_failed", "RP2"),
    (ROLLBACK_PS1, "rollback_copy_failed", "RP3"),
], ids=["RP2_auto_rollback", "RP3_manual_rollback"])
def test_rp2_rp3_the_restore_copies_say_when_they_failed(ps1, prefix, rp):
    """🔴🔴 `RP2`／`RP3`：**把快照寫回正式機的 robocopy 也要檢查結束碼。**

    ☠️ `:632`／`:633` 失敗**不中止**，直接流進 `:701` 的健康檢查 ——
    健康檢查若碰巧過了（半還原的 backend 也可能回得出 `/health`）
    ⇒ 報 **`restored`＝「已還原到套用前的版本」**，
    🔑 **而磁碟上是還原到一半的殘骸。**

    ⚙️ 值域 1:1 照舊：`%s_backend`／`%s_frontend` 各一次。
    """
    lines, rows = _robo_rows(ps1, _ROBO_TO_PROD)
    assert len(rows) == 2, (
        "`%s`：「快照 → 正式機」的 robocopy 抓到 %d 行，預期 2 行 ——\n"
        "🔑 0 行 ⇒ **儀器失效**。" % (ps1.name, len(rows))
        + "".join("\n  :%d %s" % (i + 1, lines[i].strip()[:80]) for i in rows))

    bad = [i for i in rows if _guarded(lines, i) is None]
    assert not bad, (
        "`%s`（%s）：還原用的 robocopy 沒有檢查結束碼：\n  " % (ps1.name, rp)
        + "\n  ".join(":%d %s" % (i + 1, lines[i].strip()[:80]) for i in bad)
        + "\n☠️ 失敗不中止 ⇒ 流進健康檢查 ⇒ 碰巧過了就報「已還原」，\n"
          "   **而磁碟上是還原到一半的殘骸。**")

    src = ps1.read_text(encoding="utf-8", errors="replace")
    for suffix in ("backend", "frontend"):
        status = "%s_%s" % (prefix, suffix)
        n = len(_re.findall(
            r'(?:Fail\s+.*?|Emit-Result\s+)"' + _re.escape(status) + r'"', src))
        assert n == 1, (
            "`%s` 在 `%s` 裡以引數出現 %d 次，預期 1 次。" % (status, ps1.name, n))


@pytest.mark.parametrize("ps1", [APPLY_PS1, ROLLBACK_PS1],
                         ids=["apply_update", "rollback_update"])
def test_rp2_rp3_restoring_is_set_before_the_first_restore_write(ps1):
    """🔴🔴 `restoring` 要設在**第一次把快照寫回正式機之前**。

    與 `:420`（`applied_no_restore` 設在 robocopy 之前）**同一條紀律**：
    🔑 **危險值在動作之前設。**

    ☠️ 設在之後的話，`RP2`／`RP3` 那兩條新出口印出來的 `rolled_back` 會是：
    ```
    apply_update     applied             語意「新版**完整**寫進正式機」—— 而它正在還原
    rollback_update  applied_no_restore  語意含「**沒有還原**」—— 而它正在還原
    ```
    ⇒ **兩個都比實際樂觀，而且方向都是錯的。**
    📌 `§53` 明文要求 `RP2`／`RP3` 成對落地：
       **少了結束碼檢查，`restoring` 印不出來（永遠綠的題）；
         少了 `restoring`，結束碼檢查印出來的狀態是錯的。**
    """
    lines, rows = _robo_rows(ps1, _ROBO_TO_PROD)
    assert rows, "`%s`：「快照 → 正式機」的錨點一行都沒命中 —— **儀器失效**。" % ps1.name
    first = rows[0]

    assign = _re.compile(r'^(\s*)\$script:ProdState\s*=\s*"([^"]*)"')
    hits = []
    for i, ln in enumerate(lines):
        m = assign.match(ln)
        if m and m.group(2) == "restoring":
            hits.append((i + 1, len(m.group(1))))
    assert hits, (
        "`%s` 裡沒有 `$script:ProdState = \"restoring\"` ——\n"
        "☠️ 那兩條新出口會報 `applied`／`applied_no_restore`，"
        "而它們的語意**都與「正在還原」相反**。\n"
        "🔑 §53：`restoring` 與結束碼檢查**成對**落地。" % ps1.name)

    ln_no, col = hits[0]
    assert ln_no <= first, (
        "`%s`：`restoring` 設在 :%d，而第一次把快照寫回正式機在 :%d —— **順序反了**。\n"
        "🔑 危險值在動作之前設（與 `:420` 同一條紀律）。" % (ps1.name, ln_no, first + 1))
    between = [(i + 1, assign.match(lines[i]).group(2))
               for i in range(ln_no, first) if assign.match(lines[i])]
    assert not between, (
        "`%s`：`restoring`（:%d）與第一次寫回（:%d）之間又有指派：%s\n"
        "☠️ 那兩條出口報的會是後面那個值，不是 `restoring`。"
        % (ps1.name, ln_no, first + 1,
           ", ".join(":%d=%s" % b for b in between)))


# ══════════════════════════════════════════════════════════════════════
# §53e · `describe_rolled_back` 的兩個 fail-open
# ══════════════════════════════════════════════════════════════════════

def test_56_an_unrecognised_action_blows_up_because_that_one_is_our_bug():
    """🔴 §56：**沒見過的 `action` ⇒ 拋錯。**（`§53e` 的第二版，A 第三次更正同一支函式）

    分界是**誰錯了**：
    ```
    action 不認得  **程式錯誤** —— 它由我們自己的碼從一個封閉集合寫入   ⇒ 拋錯
    value  不認得  **資料錯誤** —— 正式機送上來的                      ⇒ 顯示 ＋ 記告警
    ```
    🔑 `§51b` 的 fail-safe 保護的是「**對面送來的東西**不可以弄垮我們的畫面」，
       它**不保護**「我們自己傳錯參數」—— 那種要**盡早大聲地壞掉**。

    ⚠️ **這一題的 v1 釘的是相反的方向，那一列留著**：
    ```
    v1（§53e）  不可以拋錯，要回「動作無法辨識（%s）」
                依據：A 在 §54 明著寫「A-2 建議的 raise 那一半我不採」
    v2（§56）   要拋錯
                依據：A 自己更正 —— 分界不是「哪一側」，是「誰錯了」
    ```
    ☠️ 而 v1 我是**刻意**寫成 `try/except … pytest.fail` 的，理由是
       「少了它，B 若改成 raise，這一題會以 ERROR 收場而訊息指向例外不是裁示」。
    🔑 **那個理由現在反過來替 v2 服務** —— 形狀沒變，期望的方向變了。
    📌 可記的一條：**一題「不可以做 X」的守門，在裁示翻面時不會自己翻面，
       而它會用一個看起來很有道理的訊息擋住正確的實作。**

    ⚙️ 正對照：`deploy`／`rollback` **不可以**拋 —— 少了它，
       「函式第一行就 raise」會讓上面全綠，而畫面永遠是壞的。
    """
    describe = _need("describe_rolled_back")

    for action in ("rollback ", "Rollback", "restore", "", None):
        try:
            got = describe("not_applied", action)
        except Exception as exc:                      # noqa: BLE001 —— 型別由 B 定
            assert str(action) in str(exc), (
                "`action=%r` 有拋錯，而訊息裡沒有那個值：%s" % (action, exc)
                + chr(10) + "🔑 排錯的人拿到的第一份線索就是這句話。")
        else:
            pytest.fail(
                "`describe_rolled_back(action=%r)` **回傳了** %r 而沒有拋錯。" % (
                    action, got)
                + chr(10) +
                "☠️ 原本的缺陷是**靜默退回 `deploy` 的文案**（畫面說「正式機沒有被碰過」，"
                "而它可能剛剛才被一次失敗的部署動過）——那一半已經修掉了。" + chr(10) +
                "⚠️ 而回一句**具名的**話仍然不夠：`§56` 要的是拋錯。" + chr(10) +
                "🔑 §56：`action` 由**我們自己的碼**從封閉集合寫入 ⇒ "
                "傳錯是**程式錯誤** ⇒ 要盡早大聲地壞掉，不是顯示一句話。")

    # ⚙️ 正對照 —— 少了它，「第一行就 raise」會讓上面全綠。
    for action in ("deploy", "rollback"):
        text = describe("not_applied", action)
        assert isinstance(text, str) and text.strip(), (
            "`action=%r` 是合法的，而它拿不到文案。" % action)


def test_53e_restoring_does_not_borrow_a_sentence_that_means_the_opposite():
    """🔴 A-2 找到的那一層：**自動回滾走的 `action` 是 `deploy`，不是 `rollback`。**

    ```
    自動回滾發生在 apply_update.ps1:632 ⇒ 那一次操作是使用者按的**部署**
    ⇒ dashboard 查的是 deploy 的文案表
    ⇒ 而 deploy 表裡最接近的那一句是
       "applied_no_restore": "新版只寫了一半就中斷，**而且沒有還原**。"
                                                      ↑ 方向相反：它正在還原
    ```
    ⇒ `restoring` 在**兩個** action 的文案表裡都要有，
    🔑 **而 deploy 那一句不可以跟 `applied_no_restore` 是同一句** ——
       否則「正在還原」與「沒有還原」在畫面上長得一樣。

    ⚠️ 而它與 `rollback` 表的 `applied_no_restore`（「還原做到一半就中斷了」）
       **語意重疊**。A-2 指出真正的那一層問題：
       **`rolled_back` 的值域共用一份，而語意隨 `action` 變。**
       📌 那是刻意的還是欠帳，要 A 說 —— 本題只釘「兩句不可以相同」。
    """
    describe = _need("describe_rolled_back")
    for action in ("deploy", "rollback"):
        text = describe("restoring", action)
        assert isinstance(text, str) and text.strip(), (
            "`describe_rolled_back('restoring', %r)` 給不出人話。" % action)
        assert not _is_fallback(describe, "restoring", action), (
            "`restoring` 在 `%s` 下回的是**退路**不是文案：%r" % (action, text)
            + chr(10) +
            "⚠️ 這一題的 v1 因此**綠得不對**：退路本來就不等於 "
            "`applied_no_restore` 的文案 ⇒ 下面那個比較永遠成立。" + chr(10) +
            "🔑 〈假綠燈〉：斷言要挑「**只有做對了才會出現**」的觀測點。")
        other = describe("applied_no_restore", action)
        assert text != other, (
            "`restoring` 與 `applied_no_restore` 在 `%s` 下是**同一句話**：%r\n"
            "☠️ 「正在還原」與「沒有還原」在畫面上長得一樣 ——\n"
            "🔑 而使用者要用它決定「現在能不能再按一次回滾」。" % (action, text))


# ══════════════════════════════════════════════════════════════════════
# §54d · 兩處 `or` 要改成 `in`：**「沒有這個值」與「這個值的文案是空的」是兩件事**
# ══════════════════════════════════════════════════════════════════════

def test_54d_a_blank_wording_is_not_mistaken_for_an_unknown_value(monkeypatch):
    """🔴 §54d：**空字串的文案不可以被當成「不認得這個值」。**

    A-2 找到的第二條 fail-open（第一條是 `action`，我找的）：
    ```python
    return table.get(value) or ("狀態回報看不懂（%s）…" % value)
                          ↑ `or` 對「文案是空字串」也會退回
    ```
    ⚠️ 它**現在打不到**（表裡沒有空字串，而 `§54c` 也禁止），**而它是一顆種子**：
    ☠️ 哪天有人把某個值的文案暫時留空 ⇒ 靜默變成「狀態回報看不懂（applied）」
       —— 🔑 **一個看起來像正確處理的錯誤訊息**，而實情是「有人把文案刪了」。

    ⇒ 兩處都要用 `in` 判斷，不要用 `or`。
    📌 本題**不規定空字串該回什麼**（那是 B 的）——
       只釘「它與『不認得這個值』要分得出來」。
    ⚠️ 而〈null 不等於 0〉是同一條：
       「沒有這個鍵」與「鍵在而值是空的」合併之後，
       **錯誤看起來完全正常，所以沒有人報修。**
    """
    mod = _dash()
    table = getattr(mod, "_ROLLED_BACK_TEXT", None)
    assert table is not None, "缺少 `_ROLLED_BACK_TEXT` —— 見 `§54c` 那一題。"
    assert "deploy" in table and "applied" in table["deploy"], (
        "`deploy` × `applied` 這一格不在表裡 —— **儀器失效**，"
        "這一題要拿它當被注入的對象。")

    patched = dict((a, dict(sub)) for a, sub in table.items())
    patched["deploy"]["applied"] = ""
    monkeypatch.setattr(mod, "_ROLLED_BACK_TEXT", patched)

    blank = mod.describe_rolled_back("applied", "deploy")
    bogus = "__c_probe_not_a_real_value__"
    shape = mod.describe_rolled_back(bogus, "deploy")
    assert blank != shape.replace(bogus, "applied"), (
        "把 `deploy × applied` 的文案改成空字串之後，"
        "`describe_rolled_back` 回的是**「不認得這個值」那一句**：%r" % blank
        + chr(10) +
        "☠️ 而實情是**有人把文案刪了** —— 那是一個看起來像正確處理的錯誤訊息。"
        + chr(10) +
        "🔑 `or` 把「沒有這個鍵」與「鍵在而值是空的」合併了，改用 `in` 判斷。"
        + chr(10) +
        "📌 空字串要回什麼由你定，本題只釘「兩者分得出來」。")
