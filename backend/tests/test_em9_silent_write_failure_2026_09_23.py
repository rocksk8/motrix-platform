# -*- coding: utf-8 -*-
"""`EM9` · 寫入失敗不可以是靜默的（`docs/windows/SPEC-EM9-SILENT-FAILURE.md`）。

```
判準  使用者按下按鈕之後，失敗與成功長得一不一樣
      一支函式裡有寫入型 fetch，而整支函式裡失敗分支不存在
      （沒有 !x.ok、沒有 } else、catch 是空的或沒有 catch）
```

# 🔴 動工前照 A 的要求獨立複量了一次母體，而**不是 42**

規格寫的「39＋3＝42」在 2026-09-23 當天已經**部分過期**：

```
獨立實作一支不同的掃描器（不是抄 A-2 的 v4，函式邊界用另一種正則、
失敗分支偵測用另一組規則）跑一次，RAW HITS = **69**——與 v4 的 69
獨立收斂，是好的交叉驗證。

而規格 §4b 列的「真命中 3 處」，逐一打開檔案核對後：
  quotation-form.html:2910（dealTag 樂觀更新）  ✅ 已修——`EM11` 註解＋
      .catch(() => null) ＋ if (!pr || !pr.ok) { 退回 oldTag, toast(...) }
  quotation-form.html:3180 一帶（exportCount）   ✅ 已修——同樣是 `EM11`，
      現在還多修了一處規格沒提到的第三個位置（directExport()，3097 行，
      同一個「樂觀更新＋靜默失敗」形狀，也在 EM11 底下一起處理了）
  vendor-contractors.html:779（存摺 PUT）        ✅ 已修——`EM12`
      （本會話今天稍早的產出，commit b349ee7）
⇒ 規格點名的「真命中 3 處」**今天全部已修**，是被另一張工單（EM11）
  與稍早的 EM12 处理掉的，不是 EM9 自己修的。
```

⚠️ **本檔不對 39／42 這兩個數字下斷言**——那兩個數字對應的具體項目
清單今天已經有變動，而完整重新逐項核對規格列的全部 39 條不在這次的
時間範圍內。⇒ 本檔改成**分兩層**：
```
① 對已知仍然壞著的少數幾個函式，寫紅的迴歸測試（釘住「這裡還沒修」）
② 對已知剛修好的幾個函式，寫正對照（釘住「這裡不會退回去靜默失敗」）
```
這比對一個會過期的總數斷言更耐用——數字之後不管怎麼變，
①②各自量的是**具體的、有名字的函式**，不是母體筆數。

# ⚙️ 觀測方式：**讀原始碼裡那一支函式的精確片段**，不是跑整份檔案掃描

動工時我自己的掃描器踩到規格 `§4b` 描述的同一個坑（外擴停在 `if`／
`for` 上，把控制流誤判成函式邊界）——用**指名函式**＋逐一核對取出的
片段，而不是自動掃全檔，避開這個坑。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _extract_method(text, name, start_hint=0):
    """從 `text` 裡找 `name(...) {` 這個方法定義（`async` 可有可無），
    回傳它的完整原始碼片段（含大括號）。找不到就 `None`。

    ⚠️ 只用第一個匹配（從 `start_hint` 開始找）——若一個檔案裡同名方法
    出現不只一次，呼叫端要自己傳更精確的 `start_hint`（例如上一個同名
    方法結尾的位置）來取到正確的那一個。
    """
    pat = re.compile(r"(?:async\s+)?%s\s*\([^)]*\)\s*\{" % re.escape(name))
    m = pat.search(text, start_hint)
    if not m:
        return None
    depth = 1
    i = m.end()
    n = len(text)
    while i < n and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[m.start():i]


def _has_failure_handling(snippet):
    """`snippet`（一支函式的完整原始碼）裡有沒有偵測得到的失敗分支。

    收四種形狀（照抄規格 §1／§3 的判準，不用「有沒有 alert」這種詞彙表）：
      !x.ok 形式的檢查 ／ `.ok) {...} else` ／ `if (d) {...} else {...}`
      （derived-value 檢查，不直接查 `.ok`）／ 非空的 catch
      （`try{}catch{}` **或** Promise 鏈的 `.catch(cb)`）

    ## 🔴 動工時發現第一版漏了一種形狀：Promise 鏈的 `.catch(callback)`

    我原本的 `catch\\s*(\\([^)]*\\))?\\s*\\{` 只認得傳統 `try { } catch (e) { }`
    的語法（`catch` 後面直接接 `{`）。而這個 repo 大量使用
    `fetch(...).then(...).catch(err => { ... })` 這種 Promise 鏈寫法——
    `catch` 後面先是 `(callback) =>`，隔了一段才接 `{`，原本的正則
    完全比對不到，會把**一支明明有 `.catch()` 錯誤處理的函式**判成
    「沒有失敗分支」。已補上這個形狀。
    """
    if re.search(r"!\s*[A-Za-z_$][\w$.]*\s*(?:\|\|[^)]*)?\.ok\b", snippet):
        return True
    if re.search(r"\.ok\s*\)\s*\{[^}]*\}\s*else\b", snippet, re.S):
        return True
    if re.search(r"if\s*\([A-Za-z_$][\w$]*\)\s*\{[^}]*\}\s*else\s*\{[^}]*\}",
                snippet, re.S):
        return True
    for cm in re.finditer(r"\.catch\s*\(", snippet):
        # 找這個 `.catch(` 呼叫的完整參數（可能是箭頭函式／具名函式／
        # 甚至單一表達式 `.catch(() => null)`），只要參數本身不是空的
        # 就算數——它是不是「有效處理」是措辭層的事（`EM1` 的範圍），
        # 這裡只驗「有沒有人想過失敗這件事」。
        depth = 1
        i = cm.end()
        n = len(snippet)
        while i < n and depth > 0:
            if snippet[i] == "(":
                depth += 1
            elif snippet[i] == ")":
                depth -= 1
            i += 1
        args = snippet[cm.end():i - 1].strip()
        if args and args not in ("()", "() => {}", "()=>{}"):
            return True
    for cm in re.finditer(r"(?<!\.)catch\s*(\([^)]*\))?\s*\{", snippet):
        depth = 1
        i = cm.end()
        n = len(snippet)
        while i < n and depth > 0:
            if snippet[i] == "{":
                depth += 1
            elif snippet[i] == "}":
                depth -= 1
            i += 1
        if snippet[cm.end():i - 1].strip():
            return True
    return False


# ══════════════════════════════════════════════════════════════════════
# ① 仍然靜默的（今天實測還沒修）—— 驗收條件是「應該要有失敗分支」，
#   所以這幾題**今天是紅的**，B 補上失敗分支之後才會變綠
#   （照 MULTIWIN-PROTOCOL 的慣例：C 寫紅的驗收題，不是寫「現況快照」）
# ══════════════════════════════════════════════════════════════════════

def test_em9_inventory_adjust_item_must_report_failure():
    """🔴🔴 **這一支是整份規格的起點**（`§2b` 逐字引用的那一支）。

    使用者按「報廢」／「退回庫存」、按「確認」，失敗時**畫面什麼都不做**：
    `if (r.ok) {...}` 沒有 `else`，`catch {}` 是空的。
    """
    src = _read("frontend/pages/inventory.html")
    snippet = _extract_method(src, "adjustItem")
    assert snippet is not None, "找不到 `adjustItem`——退回改本檔的擷取法。"
    assert _has_failure_handling(snippet), (
        "`inventory.html::adjustItem` 仍然沒有失敗分支：\n%s\n" % snippet[:400]
        + "☠️ 使用者按「報廢」／「退回庫存」，失敗時畫面什麼都不做。")


def test_em9_inventory_delete_item_must_report_failure():
    """🔴 `inventory.html::deleteItem`，與上一題同一份檔案、同一種形狀。"""
    src = _read("frontend/pages/inventory.html")
    snippet = _extract_method(src, "deleteItem")
    assert snippet is not None, "找不到 `deleteItem`——退回改本檔的擷取法。"
    assert _has_failure_handling(snippet), (
        "`inventory.html::deleteItem` 仍然沒有失敗分支：\n%s" % snippet[:400])


def test_em9_contractors_toggle_active_must_report_failure():
    """🔴 `contractors.html::toggleActive`——停用／啟用外包人員，失敗不吭聲。"""
    src = _read("frontend/pages/contractors.html")
    snippet = _extract_method(src, "toggleActive")
    assert snippet is not None, "找不到 `toggleActive`——退回改本檔的擷取法。"
    assert _has_failure_handling(snippet), (
        "`contractors.html::toggleActive` 仍然沒有失敗分支：\n%s"
        % snippet[:400])


def test_em9_contractors_toggle_active_from_pane_must_report_failure():
    """🔴 `contractors.html::toggleActiveFromPane`——同一份檔案的第二個入口。

    ⚙️ 與上一題**故意分開驗**：同一種缺陷在同一個檔案出現兩次，
    只驗一次的話，修好其中一個會被誤判成整個問題已解決。
    """
    src = _read("frontend/pages/contractors.html")
    snippet = _extract_method(src, "toggleActiveFromPane")
    assert snippet is not None, (
        "找不到 `toggleActiveFromPane`——退回改本檔的擷取法。")
    assert _has_failure_handling(snippet), (
        "`contractors.html::toggleActiveFromPane` 現在**有**失敗分支了：\n%s"
        % snippet[:400])


# ══════════════════════════════════════════════════════════════════════
# ② 已經修好的（`EM11`／`EM12`）—— 正對照，鎖住不會退回去
# ══════════════════════════════════════════════════════════════════════

def test_em9_quotation_deal_tag_change_has_failure_handling():
    """⚙️ **正對照：`quotation-form.html::onDealTagChange`，`EM11` 已修。**

    ☠️ 少了這一題，`①` 那幾題的判準（`_has_failure_handling`）若壞成
    「永遠回 True」，`①` 會全部**假綠**——這一題確認判準對「已知確定
    有保護」的程式碼會正確回報「有」。

    🔴 **第一版釘在 `EM11` 那段註解的字面片語上**（`src.find("EM11：
    dealTag 是")`）——B 回報：他重寫註解時字面片語跟著換掉，這一題就紅
    了，而程式碼本身沒有壞。已改成釘**函式名稱** `onDealTagChange`
    （行為／結構層，不是散文）——函式名字比註解措辭穩定，改名字是
    刻意的重構，不會是「順手潤飾文件」的副作用。
    """
    src = _read("frontend/pages/quotation-form.html")
    snippet = _extract_method(src, "onDealTagChange")
    assert snippet is not None, (
        "找不到 `onDealTagChange`——退回改本檔的擷取法。")
    assert _has_failure_handling(snippet), (
        "`quotation-form.html::onDealTagChange` **沒有**被判定成有失敗分支——\n"
        + "要嘛探針的判準太窄，要嘛這段保護被拿掉了。片段：\n%s"
          % snippet[:500])


def test_em9_quotation_export_count_has_failure_handling():
    """⚙️ 正對照：`quotation-form.html` 的 `exportPDF`／`directExport`，
    兩處 `exportCount` 樂觀更新都在 `EM11` 修過，兩處都要有失敗分支。

    🔴 **第一版用固定視窗（900 字元）從註解錨點往後切，兩個問題疊在一起**：
    ```
    ① 錨點釘在註解字面片語上（同上一題的問題）
    ② 固定字元視窗會被「墊長註解」推出視窗——B 重寫註解時新註解變長，
       把真正的 `.catch(` 推到 900 字元之外，判準回報「沒有失敗分支」
       而實際上有。**這比①更嚴重**：它不是錨點失效報不到人，
       是**距離型的尺對長度敏感**，換一段更長的解釋文字就會假陽性。
    ```
    ⇒ 改成：用函式名稱定位（`exportPDF`／`directExport`），
    再用**括號平衡**取到函式的真正結尾——不管中間夾了多長的註解、
    多長的 `.then()/.catch()` 鏈，只要還在同一個函式的大括號範圍內，
    括號平衡都找得到，不像固定視窗那樣受註解長度影響。
    """
    src = _read("frontend/pages/quotation-form.html")
    for name in ("exportPDF", "directExport"):
        snippet = _extract_method(src, name)
        assert snippet is not None, (
            "找不到 `%s`——退回改本檔的擷取法。" % name)
        assert _has_failure_handling(snippet), (
            "`quotation-form.html::%s` 的 exportCount 更新**沒有**"
            "失敗分支：\n%s" % (name, snippet[:500]))


def test_em9_vendor_passbook_put_has_failure_handling():
    """⚙️ 正對照：`vendor-contractors.html` 的存摺 PUT，`EM12` 已修
    （本會話今天稍早的產出，commit `b349ee7`）——鎖住它不會退回去。

    🔴 第一版釘 `src.find("EM12")` 註解錨點——同一族問題，已改成釘
    函式名稱 `save`，並用 `_extract_method()` 取代 ad-hoc 括號比對。
    """
    src = _read("frontend/pages/vendor-contractors.html")
    snippet = _extract_method(src, "save")
    assert snippet is not None, "找不到 `save`——退回改本檔的擷取法。"
    assert "bankPassbookPreview" in snippet, (
        "取出的片段裡沒有 `bankPassbookPreview`——擷取範圍可能不對。")
    # 🔑 這裡不能直接套用 `_has_failure_handling()`：`save()` 整支函式
    #    前段（廠商本體 PUT）本來就有 `!r.ok`，用它驗會把「前一支保護」
    #    誤判成「這一支也有保護」（正是 `§4b` 記錄的那個誤判方向）。
    #    改成**只看存摺 PUT 那一段之後**的程式碼有沒有失敗分支。
    passbook_pos = snippet.index("bankPassbookPreview")
    after = snippet[passbook_pos:]
    assert _has_failure_handling(after), (
        "存摺 PUT 那一段之後找不到失敗分支：\n%s" % after[:500])


# ══════════════════════════════════════════════════════════════════════
# 排除清單的反向控制（`§6`）
# ══════════════════════════════════════════════════════════════════════

def test_em9_the_probe_catches_a_synthetic_silent_write():
    """⚙️ **誘餌：自己留一支合成的靜默寫入函式，確認判準本身有效。**

    ⚠️ 不用規格 39 條裡的任何一條當誘餌——它們修好那天誘餌就跟著失效。
    """
    synthetic = """
    async doTheThing() {
      const r = await fetch('/api/whatever', { method: 'POST' })
      if (r.ok) { this.load() }
    }
    """
    assert not _has_failure_handling(synthetic), (
        "判準對一支明顯靜默的合成函式回報『有失敗分支』——太寬，\n"
        "上面 `①` 那幾題會變成永遠通過而量不到任何東西。")


def test_em9_the_probe_does_not_flag_a_synthetic_handled_write():
    """⚙️ 負對照：合成一支**有處理**失敗的函式，判準不可以誤報。"""
    synthetic = """
    async doTheThing() {
      const r = await fetch('/api/whatever', { method: 'POST' })
      if (!r.ok) { this.toast('失敗了'); return }
      this.load()
    }
    """
    assert _has_failure_handling(synthetic), (
        "判準對一支明顯有處理失敗的合成函式回報『沒有失敗分支』——太窄，\n"
        "會誤把正確的實作判成缺陷。")


def test_em9_a_long_comment_before_catch_does_not_cause_a_false_negative():
    """⚙️ **迴歸誘餌：`.catch(` 前面墊一段極長的註解，判準不可以誤報「沒有」。**

    這一題直接對應 A 回報的那個真實 bug——舊版判準用**固定字元視窗**
    （從錨點往後切 900 字元）找失敗分支，B 重寫附近的註解把它變長，
    真正的 `.catch(` 被推出 900 字元之外，判準因此誤報「沒有失敗分支」。

    ⚙️ 合成一段結構相同的輸入：函式體裡先塞一段刻意超過 900 字元的
    註解，隔了很久才出現 `.catch(...)`——若判準（`_has_failure_handling`
    ＋ `_extract_method` 的括號平衡擷取）走的是**結構**而不是距離，
    這一題必須是綠的；若哪天有人把判準改回距離型視窗，這一題會先紅，
    不必等到真正的產品碼被墊長註解才發現。
    """
    long_comment = "// " + ("這是一段刻意拉長的註解用來把後面的程式碼推遠　" * 40)
    assert len(long_comment) > 900, (
        "誘餌註解只有 %d 字元，沒有超過舊版判準的 900 字元視窗，\n"
        "這一題就驗不到當初那個 bug。" % len(long_comment))
    synthetic = (
        "async doTheThing() {\n"
        + long_comment + "\n"
        + "  fetch('/api/whatever', { method: 'POST' })\n"
        + "    .then(r => { if (r.ok) { this.load() } })\n"
        + "    .catch(() => { this.toast('失敗了') })\n"
        + "}"
    )
    snippet = _extract_method(synthetic, "doTheThing")
    assert snippet is not None, (
        "連合成輸入都取不到函式片段——`_extract_method` 本身壞了。")
    assert _has_failure_handling(snippet), (
        "`.catch(...)` 前面墊了 %d 字元的註解，判準卻回報『沒有失敗分支』"
        "——退回成距離型視窗了。" % len(long_comment))
