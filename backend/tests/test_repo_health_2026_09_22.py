"""§8 HC2a / HC3a · 讓盤點工具讀得懂這個 repo，並且守住它的自我檢查。

---

# 🔑 這兩題守的是**工具**，不是產品

☠️ 而今天最貴的一條教訓就是從這裡來的：
```
死碼掃描 v1  報 462 支   ← 沒排除 FastAPI 裝飾器持有的路由
        v2  報   4 支
        v3  報   3 支   ← is_enabled 是改名匯入的，v2 的假陽性
```
📌 **v2→v3 那次是靠「實際去看那 10 個 grep 提及是什麼」才發現的，
不是工具自己說的。**
⇒ **一個掃描工具要先能讓「已知的那一個」亮起來，才有資格報「沒有其他的」。**
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REQUIREMENTS = BACKEND / "requirements.txt"
CODE_HEALTH = BACKEND / "tools" / "code_health.py"


# ══════════════════════════════════════════════════════════════════════
# HC2a · requirements.txt 要是純 ASCII
# ══════════════════════════════════════════════════════════════════════

def test_hc2a_requirements_is_pure_ascii():
    """🔴 HC2a：`backend/requirements.txt` **不可以有非 ASCII 字元**。

    ## ☠️ 症狀

    ```
    pip_audit  →  UnicodeDecodeError: 'cp932' codec can't decode byte 0xef
    ```
    `pip_audit` 的解析器用**系統語系編碼**讀這個檔，
    而這台機器的語系是 CP932 ⇒ **中文註解讓它整個跑不起來。**
    ⇒ 📌 **相依漏洞目前是一個完全的盲區，而盲區的成因是兩行註解。**

    ## ⚠️ 這一題證明的**不是**「相依沒有漏洞」

    🔑 它證明的是「**那個工具讀得懂這個檔**」——
    ☠️ 兩者的距離就是〈證據的適用範圍〉那一整條。
    📌 「真的跑一次 `pip_audit` 並記下結果」是另一件事，
    它需要網路（測試裡不可以連外，見 NETGUARD），
    ⇒ **進 `PENDING`：誰驗＝B／什麼時候＝下一輪／寫在哪＝STATE.md §8 HC2。**

    ## 📌 為什麼釘「純 ASCII」而不是「用 UTF-8 讀得開」

    ⚠️ 後者**永遠是綠的** —— 這個檔本來就是合法的 UTF-8。
    🔑 而壞掉的原因不是它不合法，是**讀它的人用了別的編碼**，
    而我們改不了 `pip_audit` 怎麼開檔。
    ⇒ 唯一測得到又真的有效的性質是「**每個位元組都小於 128**」。
    """
    raw = REQUIREMENTS.read_bytes()
    offenders = []
    for lineno, line in enumerate(raw.split(b"\n"), 1):
        if any(b > 127 for b in line):
            offenders.append(
                f"  {lineno}: {line.decode('utf-8', 'replace')[:70]}")
    assert not offenders, (
        f"`requirements.txt` 有 {len(offenders)} 行含非 ASCII 字元：\n"
        + "\n".join(offenders)
        + "\n\n⇒ `pip_audit` 在 CP932 語系下會 UnicodeDecodeError，"
          "相依漏洞因此完全查不到。註解改英文即可。"
    )


# ══════════════════════════════════════════════════════════════════════
# HC3a · 盤點工具要先證明自己看得見
# ══════════════════════════════════════════════════════════════════════

def _run_code_health():
    p = subprocess.run(
        [sys.executable, str(CODE_HEALTH)],
        cwd=str(BACKEND), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    assert p.returncode == 0, (
        f"`tools/code_health.py` 跑不起來（exit={p.returncode}）：\n{p.stderr[-800:]}")
    return p.stdout


def test_hc3a_the_health_tool_prints_its_own_controls():
    """🔴 HC3a：**這支工具每次都要印出自己的正反對照。**

    ☠️ 少了這兩行，`dead: 0` 這個數字**沒有任何人可以判斷它是真的還是壞的**。
    🔑 那正是〈指標有階梯≠訊號存在〉：
    **一個掃不到東西的掃描器，跟一個真的乾淨的 repo，輸出一模一樣。**
    """
    out = _run_code_health()
    assert "-- CONTROLS" in out, (
        "`code_health.py` 不再印對照組那一段了：\n" + out[:600])
    assert "positive" in out and "negative" in out, (
        "對照組只剩一半 —— 正反兩側都要印：\n" + out[:600])


def test_hc3a_the_negative_control_stays_clean():
    """🔴 HC3a 負對照：**活著的函式不可以被報成死碼。**

    📌 `locate_cached`／`warm_geocode_cache`／`is_enabled` 三支是活的，
    ⚠️ 而 `is_enabled` 是 `from X import is_enabled as _pref_enabled`
    —— **改名匯入之後原名不再出現**，v2 曾因此誤報它。
    🔑 〈判準的寬窄都會騙人〉的「太寬」那一側：
    **假陽性不會給你綠燈，但它會讓人開始忽略這份輸出。**
    """
    out = _run_code_health()
    assert "negative" in out, "負對照那一行不見了：\n" + out[:600]
    line = [ln for ln in out.splitlines() if "negative" in ln][0]
    assert "CLEAN" in line, (
        f"負對照亮了 —— 有活著的函式被報成死碼：\n{line}\n\n{out[:800]}")


def test_hc3a_the_positive_control_is_lit():
    """🔴🔴 HC3a 正對照：**它必須先照亮一個已知的死碼。**

    ## ☠️ 這一題寫的時候是紅的，而紅的那個狀態值得留著

    我 2026-09-22 動手寫它時，工具的輸出是：
    ```
    positive  reminder_stage (D proved dead) : NOT LIT  <-- tool broken
    -- dead module-level functions: 0
    ```
    🔑 **它一邊說「我壞了」，一邊回報「死碼 0 支」** ——
    ⇒ 而「0」在那個狀態下**證明不了任何事**。

    ## 🔴 成因是一個形狀，而那個形狀比這次的修復重要

    正對照當時釘的是 `reminder_stage`，而 `reminder_stage`
    **正是這支工具自己叫我們刪掉的**（HC5，B 同一輪刪了它）。
    ☠️ **⇒ 修好它報告的問題，就毀掉它證明自己的能力。**

    ```
    一般化：正對照不可以釘在「一個會被修掉的東西」上。
            它要釘在一個**故意留著、只為了被偵測到**的東西上。
    ```
    ✅ 已由 `80eaac5` 修掉，做法正是**合成誘餌**
    （`positive  synthetic dead function : LIT`）——
    🔑 **誘餌的價值就是它永遠不會被修好。**

    ## ⚠️ 所以這一題今天是綠的，而它守的是「不要再退回去」

    📌 退回去的樣子很具體：下一個人覺得「用真的死碼當對照比較有說服力」，
    ⇒ 然後那支死碼被刪掉，這個對照又壞一次，**而輸出照樣是綠的數字。**
    """
    out = _run_code_health()
    line = [ln for ln in out.splitlines() if "positive" in ln][0]
    assert "NOT LIT" not in line and "tool broken" not in line, (
        f"正對照沒有亮：\n{line}\n\n"
        "☠️ 這支工具現在沒有資格宣稱「死碼 0 支」。\n"
        "⇒ 需要一個**永久誘餌**（刻意留著的死碼），不是再釘一支真的死碼 ——\n"
        "   因為真的死碼被刪掉之後，這個對照就又壞了一次。"
    )
    assert "LIT" in line, f"正對照那一行讀不出結果：\n{line}"
