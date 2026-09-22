"""§8 FX31 · 儀表板的 `stats` 不可以被不完整的回應洗掉。

---

# ☠️ 缺陷的形狀（D 看截圖時抓到的）

```
index.html:841    stats 初始化有完整預設值（activeCases: 0, waitingForMe: 0, …）
index.html:1045   if (r.ok) this.stats = await r.json()      ← **整個覆蓋**
index.html:486    x-text="stats.waitingForMe + ' 件'"        ← 直接字串相加，沒有防線
⇒ 回應少了哪個鍵，儀表板就印「我的待簽核 undefined 件」給使用者看
```

# 🔑 而它為什麼在這一包要修，理由不是「便宜」

它與這一包的**已知風險有交互作用**：`DEPLOY.md` 的 🔴🔴 那一步
（重跑排程工作）沒做時，**前端是新的、後端還是舊的** ——
📌 而那正是「回應少了某個鍵」最會發生的時刻。
☠️ `DEPLOY.md` 自己寫著那一步沒做的樣子是「**推送成功、服務正常、畫面正常**」。

---

# ⚠️ 觀測點：**餵一個缺鍵的回應**，不是「程式碼裡有沒有防線」

A 明著排除了兩種寫法：
```
❌ grep `|| []` 有沒有出現   ← 驗實作細節，而 B 的修法是展開合併不是加 ||
❌ 斷言 stats 有預設值        ← :841 本來就有，它一直都綠
✅ 餵缺鍵的回應 ⇒ 不可以出現 undefined
⚙️ 反向控制：餵完整回應 ⇒ 數字要真的變成回應裡的那個值
   （少了這一半，「永遠用預設值、忽略回應」也會綠）
```

🔑 **不釘 `{ ...this.stats, ...(await r.json()) }` 那一行的寫法** ——
日後有人改成別的寫法，這一題要照樣綠。

---

# 📌 我怎麼在沒有瀏覽器的情況下驗它

把那一行**合併運算式**從 `index.html` 抽出來，用 **node** 真的跑一次：
```
預設值（:841 那一段）  ＋  一個缺鍵的假回應   ⇒ 結果裡不可以有 undefined
預設值                 ＋  一個完整的假回應   ⇒ 結果要等於回應的值
```
⚠️ **它驗不到 Alpine 真的把那個結果渲染出來** —— 那是 DOM 行為。
☠️ 擋得住：合併邏輯被改回整個覆蓋。
☠️ 擋不住：合併對了而某個 `x-text` 用了一個 `stats` 裡沒有的鍵。
🔑 真正的驗收是目視，而這句話寫在這裡，不寫在豁免表裡。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "index.html")

#: 畫面上真的讀到的 `stats.*` 鍵（從 `index.html` **當場抓**，不手寫）。
#: 🔑 手寫清單漏掉的永遠是「後來才加的那一個」，
#: 而那一個正是下一次印出 `undefined` 的那一個。
_USED_KEY = re.compile(r"stats\.([a-zA-Z_][a-zA-Z0-9_]*)")

#: 把 `this.stats = <運算式>` 的右手邊抽出來。
_ASSIGN = re.compile(r"this\.stats\s*=\s*(.+?)\s*$", re.M)


def _page():
    assert PAGE.exists(), f"找不到 {PAGE}"
    return PAGE.read_text(encoding="utf-8")


def _used_keys(text):
    keys = set(_USED_KEY.findall(text))
    assert len(keys) >= 5, (
        f"只從 `index.html` 抓到 {len(keys)} 個 `stats.*` 鍵 —— 那個抓法八成壞了。\n"
        "☠️ 一個抓不到鍵的檢查會給你它能給的最好結果。")
    return keys


def _merge_expression(text):
    """`this.stats = …` 那一行的右手邊（取**回應指派**那一個）。"""
    hits = [m.group(1).strip() for m in _ASSIGN.finditer(text)]
    assert hits, (
        "`index.html` 裡找不到任何 `this.stats = …`。\n"
        "📌 搜尋範圍：`frontend/index.html` 全文，用的是 "
        "`this\\.stats\\s*=` 這個樣式。")
    # 只要那一個「從回應來的」——它一定提到 `r.json()`。
    from_response = [h for h in hits if "json()" in h]
    assert from_response, (
        f"找得到 `this.stats = …` 而沒有一個是從回應來的：{hits}\n"
        "⇒ 這一題的前提不成立（那支 fetch 的寫法變了）。")
    return from_response[0].rstrip(";")


def _run_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
    out = subprocess.run([node, "-e", script], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, (
        f"node 跑不起來（exit={out.returncode}）：{out.stderr[-400:]}")
    return json.loads(out.stdout)


def _evaluate(expr, defaults, response):
    """把那個合併運算式套在 `defaults` ＋ `response` 上，回傳結果物件。"""
    # ⚠️ `await r.json()` 在這裡換成一個字面物件 —— 我們要驗的是**合併**，
    #    不是 fetch。而換掉它的同時**保留了展開的語意**。
    body = expr.replace("(await r.json())", "RESP").replace("await r.json()",
                                                            "RESP")
    script = (
        "const DEF = " + json.dumps(defaults, ensure_ascii=False) + ";\n"
        "const RESP = " + json.dumps(response, ensure_ascii=False) + ";\n"
        "const self = { stats: DEF };\n"
        "const out = (function () { const this_ = self; "
        "return " + body.replace("this.stats", "this_.stats") + "; })();\n"
        "console.log(JSON.stringify(out));"
    )
    return _run_node(script)


@pytest.fixture(scope="module")
def page():
    return _page()


# ══════════════════════════════════════════════════════════════════════
# FX31 · 缺鍵的回應不可以讓畫面出現 undefined
# ══════════════════════════════════════════════════════════════════════

def test_fx31_a_partial_response_never_leaves_a_key_undefined(page):
    """🔴🔴 FX31：回應**少了鍵**時，畫面用到的每一個 `stats.*` 都不可以是 undefined。

    ☠️ 那個情況最會發生的時刻是**部署後忘了重跑排程工作** ——
    前端是新的、後端還是舊的，而 `DEPLOY.md` 自己寫著那一步沒做的樣子是
    **「推送成功、服務正常、畫面正常」**。
    """
    keys = _used_keys(page)
    defaults = {k: 0 for k in keys}
    # 只回兩個鍵 —— 舊後端的樣子。
    partial = {"totalQuotes": 7, "pendingQuotes": 3}

    merged = _evaluate(_merge_expression(page), defaults, partial)
    missing = sorted(k for k in keys if k not in merged)
    assert not missing, (
        "回應少了這些鍵，而合併之後它們不見了：" + "、".join(missing) + "\n"
        "☠️ 畫面會印「我的待簽核 undefined 件」給使用者看。\n"
        "🔑 不是補那兩個欄位（那是修結果），是合併進既有預設值。")


def test_fx31_a_full_response_actually_replaces_the_defaults(page):
    """🔴 FX31 反向控制：**完整回應時，數字要真的變成回應裡的那個值。**

    ☠️ 少了這一半，一個「**永遠用預設值、忽略回應**」的實作會讓上一題全綠 ——
    🔑 而那個儀表板會永遠顯示 0，**看起來像公司沒有任何案子**。
    📌 〈判準的寬窄都會騙人〉：「永遠不被覆蓋」是「不要被錯誤覆蓋」的超集。
    """
    keys = _used_keys(page)
    defaults = {k: 0 for k in keys}
    full = {k: 42 for k in keys}

    merged = _evaluate(_merge_expression(page), defaults, full)
    stale = sorted(k for k in keys if merged.get(k) != 42)
    assert not stale, (
        "回應給了值，而這些鍵仍然是預設值：" + "、".join(stale) + "\n"
        "☠️ 那個儀表板會永遠顯示 0，看起來像公司沒有任何案子。")


def test_fx31_the_probe_would_notice_a_plain_overwrite(page):
    """📏 量尺：**把那一行換回「整個覆蓋」，上面那一題要紅。**

    ☠️ 少了這一題，`_evaluate()` 哪天壞掉（node 參數變了、抽取樣式改了）
    會讓兩題**一起安靜地綠** ——
    🔑 而「合併」與「覆蓋」的差別正是這一節的全部內容。

    ⚠️ 這裡**不改產品碼**：我把「覆蓋」那個寫法當成字串餵進同一條評估路徑。
    """
    keys = _used_keys(page)
    defaults = {k: 0 for k in keys}
    partial = {"totalQuotes": 7}

    overwritten = _evaluate("(await r.json())", defaults, partial)
    missing = [k for k in keys if k not in overwritten]
    assert missing, (
        "把運算式換成「整個覆蓋」之後，仍然沒有任何鍵不見 ——\n"
        "☠️ 那代表 `_evaluate()` 根本沒有在評估那個運算式，\n"
        "🔑 而上面兩題的綠因此證明不了任何事。")
