"""§4 YB · 不完整的 `/api/auth/me` 回應不可以洗掉既有權限。

---

# 🔴 現況（`frontend/static/sidebar.js:888-907`，我逐行讀過）

```js
if (!d) return                                        // :893  只擋 null
stored.modules = d.modules                            // :903  undefined 時把既有值蓋掉
...
mods = Array.isArray(d.modules) ? d.modules : []      // :909  ← 這裡**有**防護
```

## ☠️ 而那個不對稱正是「要載入兩次」的成因

**`:909` 的記憶體路徑有防護，`:903` 寫進 `localStorage` 的那一行沒有**
⇒ 🔑 **當下那一頁會自己恢復（`mods` 被修正了），而存下來的值已經被洗掉**
⇒ **下一次載入才爆**，而那時看起來跟上一次的操作無關。

📌 A 的規格寫「重新載入不會自己好（要載入兩次）」——
**那個「兩次」就是這個不對稱的指紋。**
⚠️ 而它同時說明**為什麼只修 `:903` 不夠**：兩個地方各自判斷同一件事
⇒ 〈修作法不要修結果〉：**要有一個共同的答案**。

---

# 📌 落點：**node，不是 Playwright**

A 查出這台機器有 `node v22.22.3`（我複驗過）
⇒ 把「這個回應可不可以覆寫既有值」抽成**純函式**，用 node 測它
⇒ 🔑 **它落在非 e2e 的桶裡，而那個桶有拒收能力。**

## ⚠️ 而我原本提的第二條路是錯的，A 指出來了

我提過「驗它**沒有**用 `|| []`」——
☠️ **那正是 YB4 明文禁止的「釘實作細節」**：
一個用 `?? []` 的實作會讓它綠，
而一個用 `Array.isArray(x) ? x : []` 的**正確**實作**也可能讓它紅**。
📌 〈判準的寬窄都會騙人〉—— 而這一次兩側同時發生。

---

# ⚠️⚠️ 這個檔**不驗 DOM 有沒有被替換**

它驗的是**那個決定**（「這個回應可不可以覆寫」），
**不是**「`localStorage` 裡的值真的沒變」。
🔑 後者需要真的瀏覽器，而**瀏覽器那一桶目前沒有拒收能力**
⇒ 已由 A 升級成 `YG`（三個委託人：XA6／XA7／YB 的 DOM 那一半）。
📌 **所以 YB4 的字面要求，這個檔只做到了一半，而另一半是寫著的。**
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent.parent
STATIC = REPO / "frontend" / "static"

#: 那支純函式可以住在哪幾個檔 —— **B 決定，我接受任何一個。**
#: ⚠️ `sidebar.js` 現在是 IIFE 且會碰 `document`／`localStorage`
#: ⇒ 直接 `require` 它會 `ReferenceError`
#: ⇒ B 要嘛守住那一段、要嘛把純函式搬到自己的檔。**兩種我都收。**
CANDIDATES = ("session_policy.js", "session-policy.js", "sidebar.js")

#: 🔑 這張表就是 YB1–YB3 的全部內容。
#: 每一列：`(說明, 回應, 應該接受嗎)`
CASES = [
    ("null（連線失敗）",            None,                                False),
    ("整個回應是 undefined",        "__undefined__",                     False),
    ("缺 modules 這個鍵",           {"role": "admin"},                   False),
    ("modules 是 undefined",        {"role": "admin", "modules": None},  False),
    ("modules 不是陣列",            {"role": "admin", "modules": "x"},   False),
    ("缺 role",                     {"modules": []},                     False),
    ("role 是空字串",               {"role": "", "modules": []},         False),
    # 🔴 YB3：**合法的空清單要被接受** —— 權限真的被拿掉了
    ("modules 是合法的空清單",      {"role": "sales", "modules": []},    True),
    ("正常回應",                    {"role": "admin", "modules": ["a"]}, True),
]

_HARNESS = """
const fs = require('fs');
const path = require('path');
const target = process.argv[2];
let fn = null;
let why = [];
try {
  const m = require(target);
  if (m && typeof m.acceptsSessionUpdate === 'function') {
    fn = m.acceptsSessionUpdate;
  } else {
    why.push('require() 成功而沒有匯出 acceptsSessionUpdate');
  }
} catch (e) {
  why.push('require() 丟了：' + e.message);
}
if (!fn && globalThis.MotrixSession
    && typeof globalThis.MotrixSession.acceptsSessionUpdate === 'function') {
  fn = globalThis.MotrixSession.acceptsSessionUpdate;
}
if (!fn) {
  console.log(JSON.stringify({ error: why.join(' / ') || '找不到那支函式' }));
  process.exit(0);
}
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = cases.map(function (c) {
  const arg = (c === '__undefined__') ? undefined : c;
  try { return { ok: fn(arg) === true }; }
  catch (e) { return { threw: e.message }; }
});
console.log(JSON.stringify({ results: out }));
"""


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("這台機器沒有 node —— 這一題需要 JS runtime")
    return exe


def _run_policy(tmp_path, cases):
    """把那幾個回應餵給那支純函式，回 node 印出來的結果。"""
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    payload = tmp_path / "cases.json"
    payload.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")

    tried = []
    for name in CANDIDATES:
        target = STATIC / name
        if not target.exists():
            tried.append(f"{name}（檔案不存在）")
            continue
        proc = subprocess.run(
            [_node(), str(harness), str(target), str(payload)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        if proc.returncode != 0:
            tried.append(f"{name}（node 結束碼 {proc.returncode}："
                         f"{(proc.stderr or '').strip()[:120]}）")
            continue
        try:
            got = json.loads((proc.stdout or "").strip() or "{}")
        except json.JSONDecodeError:
            tried.append(f"{name}（輸出不是 JSON：{proc.stdout[:120]}）")
            continue
        if "results" in got:
            return name, got["results"]
        tried.append(f"{name}（{got.get('error')}）")
    return None, tried


# ══════════════════════════════════════════════════════════════════════
# YB0 · 量尺：先證明 node 與那支函式都到得了
# ══════════════════════════════════════════════════════════════════════

def test_yb0_the_decision_is_reachable_from_node(tmp_path):
    """🔴 YB0 量尺：**那支純函式要能從 node 取得。**

    ⚠️ 沒有這一題，下面那幾題會以「`_run_policy` 回 `None`」的形式紅，
    而失敗訊息會指向**我的 harness**而不是**缺少那支函式**。
    🔑 〈把自己的動作當成對象的性質〉：**「我拿不到它」與「它不存在」是兩件事**，
    而錯誤訊息要說得出是哪一種。

    📌 `sidebar.js` 現在是 IIFE 且會碰 `document` ⇒ 直接 `require` 會丟。
    ⇒ B 要嘛守住那一段（讓 node 也能載入），要嘛把純函式搬到自己的檔。
    **兩種我都收 —— 匯出方式是 B 的決定。**
    """
    found, info = _run_policy(tmp_path, [{"role": "a", "modules": []}])
    assert found, (
        "從 node 取不到 `acceptsSessionUpdate`。試過：\n  "
        + "\n  ".join(info)
        + "\n\n⇒ 請把「這個回應可不可以覆寫既有值」抽成一支**純函式**"
        "（沒有 DOM、沒有 fetch），並讓它在 node 裡取得得到。\n"
        "📌 匯出方式由你決定；檔名放這幾個之一即可："
        + "、".join(CANDIDATES)
    )


# ══════════════════════════════════════════════════════════════════════
# YB1 / YB2 / YB3 · 那個決定本身
# ══════════════════════════════════════════════════════════════════════

def test_yb1_an_incomplete_response_is_refused(tmp_path):
    """🔴🔴 YB1／YB2／YB3：**缺欄位的回應不可以被接受，而合法的空清單要被接受。**

    ## 🔑 YB2 是這一題的核心：`[]` 與 `undefined` 是兩件事

    ```
    modules: []          真的沒有模組（權限被拿掉了）⇒ **要**覆寫
    modules: undefined   這次回應沒帶           ⇒ **不可以**覆寫
    ```
    📌 〈null 不等於 0〉：⚠️ **不可以用真假值判斷** ——
    `if (d.modules)` 會把合法的 `[]` 當成「沒帶」。

    ## ☠️ 而 YB3 的反向控制是這一節的成敗

    沒有它，一個「**只要是空的就不覆寫**」的實作會讓 YB1 綠 ——
    🔑 **而那會讓真正的權限撤銷永遠生效不了**：
    管理員把某人的模組全部拿掉，而那個人的瀏覽器**永遠停在舊權限上**。
    """
    found, results = _run_policy(tmp_path, [c[1] for c in CASES])
    assert found, f"取不到那支函式（見 YB0）：{results}"
    assert len(results) == len(CASES), (
        f"回了 {len(results)} 個結果而有 {len(CASES)} 個案例"
    )

    wrong = []
    for (label, _payload, expect), got in zip(CASES, results):
        if "threw" in got:
            wrong.append(f"{label}：丟了例外 {got['threw']}")
        elif got.get("ok") is not expect:
            wrong.append(f"{label}：回 {got.get('ok')}，應該是 {expect}")

    assert not wrong, (
        f"（從 `{found}` 取得的那支函式）判斷錯了：\n  "
        + "\n  ".join(wrong)
        + "\n\n🔑 `modules: []` 是**合法的**（權限真的被拿掉了）⇒ 要覆寫；"
        "`modules: undefined` 是「這次回應沒帶」⇒ 不可以覆寫。"
    )


def test_yb2_an_undefined_modules_is_not_the_same_as_an_empty_one(tmp_path):
    """🔴🔴 YB2：**不可以用真假值判斷** —— `[]` 與 `undefined` 是兩件事。

    ```
    modules: []          真的沒有模組（權限被拿掉了）
    modules: undefined   這次回應沒帶
    ```
    ☠️ `if (d.modules)` 會把**合法的 `[]`** 當成「沒帶」
    ⇒ 🔑 **真正的權限撤銷永遠生效不了。**
    📌 〈null 不等於 0〉。

    ⚠️ 這一題原本折在 `test_yb1_` 的那張表裡 —— 而 YB2 與 YB3 是**兩條規格**。
    🔑 「寫了但編號對不上」今天第五次，**而它一直是同一個動作：
    我把兩條條件折進一支測試，而守門只看得到其中一條。**
    """
    found, results = _run_policy(
        tmp_path,
        [{"role": "admin", "modules": None},      # undefined ⇒ 不可以覆寫
         {"role": "sales", "modules": []}])       # 合法空清單 ⇒ 要覆寫
    assert found, f"取不到那支函式（見 YB0）：{results}"

    undef, empty = results
    assert undef.get("ok") is False, (
        f"`modules: undefined` 被接受了（回 {undef}）——\n"
        "⇒ 那會把既有權限洗成空的。"
    )
    assert empty.get("ok") is True, (
        f"`modules: []` 被拒絕了（回 {empty}）——\n"
        "☠️ 那是**合法**的回應（權限真的被拿掉了）⇒ 真正的撤銷永遠生效不了。"
    )
    assert undef.get("ok") != empty.get("ok"), (
        "兩者得到同一個答案 —— 那表示判斷用的是真假值，不是 `Array.isArray()`。"
    )


def test_yb3_a_legitimate_revocation_still_takes_effect(tmp_path):
    """🔴 YB3 反向控制：**`modules: []` 的合法回應要被接受。**

    ☠️ 沒有這一題，一個「**只要是空的就不覆寫**」的實作會讓 YB1 綠 ——
    🔑 而那會讓**真正的權限撤銷永遠生效不了**：
    管理員把某人的模組全部拿掉，而那個人的瀏覽器**永遠停在舊權限上**。

    📌 它與 YB2 的差別：YB2 驗「兩者分得開」，
    這一題驗「**分開之後，空清單落在『接受』那一側**」——
    ⚠️ 分得開而落錯邊的實作會讓 YB2 綠。
    """
    found, results = _run_policy(
        tmp_path, [{"role": "sales", "modules": []}])
    assert found, f"取不到那支函式（見 YB0）：{results}"
    assert results[0].get("ok") is True, (
        f"合法的權限撤銷（`modules: []`）被拒絕了：{results[0]}\n"
        "⇒ 那個人的瀏覽器會永遠停在舊權限上。"
    )


def test_yb2b_the_decision_is_a_pure_function(tmp_path):
    """🔴 YB2b：那支函式**不可以有副作用**（同一個輸入問兩次，答案相同）。

    ☠️ 少了這一題，一個「**第一次回 true、之後回 false**」或
    「順手寫了 `localStorage`」的實作會讓 YB1 綠 ——
    🔑 而它在瀏覽器裡的行為會與在 node 裡量到的**不同**，
    ⇒ **那會讓這整個檔的綠燈失去意義。**

    📌 這是把「純函式」這個要求本身寫成題 ——
    〈版本適配：決定邏輯抽純函式才測得到「換一種設定」〉的前提條件。
    """
    twice = [c[1] for c in CASES] + [c[1] for c in CASES]
    found, results = _run_policy(tmp_path, twice)
    assert found, f"取不到那支函式（見 YB0）：{results}"

    half = len(CASES)
    first, second = results[:half], results[half:]
    drift = [CASES[i][0] for i in range(half) if first[i] != second[i]]
    assert not drift, (
        f"同一個輸入問兩次得到不同答案：{drift}\n"
        "⇒ 那支函式不是純的，而它在瀏覽器裡的行為會與這裡量到的不同。"
    )


# ══════════════════════════════════════════════════════════════════════
# YB4 · 寫入那一側要用同一個答案（🟡 靜態，而且我明講它弱）
# ══════════════════════════════════════════════════════════════════════

def test_yb4_the_storage_write_is_guarded_by_the_same_decision():
    """🟡 YB4：寫進 `localStorage` 那一段要**用那個決定**擋著。

    ## ⚠️ 這是靜態檢查，而 YB4 的字面要求我只做到一半

    YB4 要的是「**缺欄位時 `localStorage` 的值不變**」——
    那是**瀏覽器的執行期行為**，需要真的 DOM。
    🔑 而瀏覽器那一桶**目前沒有拒收能力**（已升級成 `YG`）
    ⇒ **另一半是寫著的，不是做到的。**

    ## 📌 而這一題仍然有價值，理由是那個不對稱

    現況 `:909` 的 `mods` **有**防護、`:903` 的 `localStorage` 寫入**沒有**
    ⇒ 🔑 **兩個地方各自判斷同一件事**，而那正是〈修作法不要修結果〉要消滅的。
    ⇒ 這一題釘「**那個決定出現在寫入之前**」（比索引，不比存在）。
    """
    text = (STATIC / "sidebar.js").read_text(encoding="utf-8")
    body = "\n".join(
        "" if line.strip().startswith(("//", "*", "/*")) else line
        for line in text.splitlines())

    write = body.find("localStorage.setItem('motrix_session'")
    if write < 0:
        write = body.find('localStorage.setItem("motrix_session"')
    assert write >= 0, (
        "`sidebar.js` 裡找不到寫回 `motrix_session` 的那一行 —— 結構變了？"
    )

    decide = body.find("acceptsSessionUpdate")
    assert 0 <= decide < write, (
        "`localStorage.setItem('motrix_session', …)` 之前沒有呼叫 "
        "`acceptsSessionUpdate(...)`。\n"
        f"（決定在位置 {decide}，寫入在位置 {write}）\n"
        "☠️ 現況是 `:909` 的 `mods` 有防護、`:903` 的寫入沒有 ⇒ "
        "當下那一頁自己恢復，而存下來的值被洗掉 ⇒ **下一次載入才爆**。"
    )
