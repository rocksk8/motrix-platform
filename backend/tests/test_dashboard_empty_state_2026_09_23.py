"""§8 FX33 · **讀不到資料時，畫面不可以說「你沒有資料」。**

---

# ☠️ 缺陷的形狀（A-2 開交付版截圖時抓到的）

```js
if (r.ok) this.stats = { ...this.stats, ...(await r.json()) }
// r.ok 為 false ⇒ 什麼都不做 ⇒ stats 保持初始全 0
```
⇒ 畫面上三句話同時成立：
```
index.html:473   「目前沒有待您簽核的項目。」
index.html:587   「系統目前尚無資料，建議從以下步驟開始：」＋整張新手引導卡片
index.html:918   「系統目前還沒有資料，從建立第一筆客戶與報價單開始。」
```
☠️ **一個有幾百筆資料的老使用者，會看到全新安裝的新手引導。**
🔑 而他**不會報修** —— 那看起來就是一個正常的空狀態。

不需要「API 缺鍵」才會發生：**逾時、500、離線、後端重啟中**，任何一次都會。
📌 而**後端重啟中正是這一包的已知風險**（`DEPLOY.md` 🔴🔴 那一步沒做時）。

---

# ⚠️ 責任要講準：`FX31` 沒有製造它，**它消除了唯一會暴露它的訊號**

```
FX31 之前   API 失敗 → 保持初始 0 → 說「沒有資料」      ← 問題本來就在
            回應缺鍵 → undefined                       ← 🔑 唯一看得出不對勁的訊號
FX31 之後   兩種情況都 → 0 件 → 說「沒有資料」
```
🔑 **`undefined` 很醜，而它的醜正是它的價值：它會被報修。**
📌 〈降級之後它還是會動〉＋〈null 不等於 0〉：
   **「沒拿到值」與「值是 0」現在長得一模一樣。**

⚠️ 而 `FX31` 那三題抓不到它，**不是那三題寫壞了**：
它們驗的是「合併不掉鍵」，而它**正確地**不掉鍵 ——
掉的是「這個 0 是哪來的」那個資訊。**兩題問的是不同的問題。**

---

# 🔴 範圍（A 的裁定，寫死，不驗超出的）

```
✅ 驗   r.ok = false ⇒ 「還沒有資料」「尚無資料」「建立第一筆」這組文案不可以出現
⚙️ 反向控制① 成功而且真的是空 ⇒ 那組文案**要出現**
              （少了它，「永遠不顯示引導」也會綠，而新使用者就沒有引導了）
⚙️ 反向控制② 成功而且有資料   ⇒ 不出現
❌ 不驗 初始值是不是 null（A 明著排除 ⇒ 那是 FX34，在 NEXT）
❌ 不驗 那兩格數字的顯示（「0 件」留著）
❌ 不驗 其他頁的空狀態
```

⚠️ **不釘實作**（B 大概會用一個旗標）：這裡釘的是
**「讀不到時不可以說沒有資料」**這個不變量，日後換寫法要照樣綠。

🔴 **2026-09-23 A 把範圍擴了**：`:473`「目前沒有待您簽核的**項目**。」
與 `:502`「目前沒有待您簽核的**單據**。」同樣要吃同一個判斷。
📌 A 的理由：**「它們更貼身 —— 一個等著簽的人被告知沒東西要簽。」**
⚠️ 我原本把它們寫成「留在範圍外、交給 A 判」，**理由是它們由
`waitingForMe` 決定，而 A 排除了那兩格數字的顯示** ——
🔑 而 A 的裁定把那條界線畫在別的地方：**排除的是「0 件」那個數字，
不是「根據那個數字講出來的那句話」。**兩者差在有沒有斷言語氣。

---

# 📌 我怎麼在沒有瀏覽器的情況下驗它

把 `index.html` 裡**真正決定那組文案出不出現**的三段東西抽出來，
用 **node** 組成一個最小的元件，真的跑一次 `loadStats()`：
```
① async loadStats()            ← B 會改的那一支，原封不動搬過來跑
② 引導卡片的 x-show 運算式      ← 決定卡片出不出現
③ get heroSummary()            ← 決定副標說哪一句
```
把 `fetch` 換成三種回應，看 ②③ 的輸出。
⚠️ `this` 用 Proxy 包起來（`has` 永遠真）**模擬 Alpine 的作用域**：
運算式裡寫的是 `stats.totalQuotes` 不是 `this.stats.totalQuotes`。

☠️ 擋得住：失敗時仍然宣稱沒有資料。
☠️ **擋不住**：Alpine 真的把那個結果渲染出來（那是 DOM 行為）、
   以及文案被搬到第四個地方而三個觀測點都沒看到它。
🔑 真正的驗收是**使用者目視**，而這句話寫在這裡，不寫在豁免表裡。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "index.html")

#: A 點名的那一組新手引導文案。📌 **這是判準，不是實作細節** ——
#: 它們是使用者真的會讀到的字，而這一題問的就是「他會不會讀到」。
ONBOARDING_CARD_COPY = "尚無資料"
ONBOARDING_HERO_COPY = "系統目前還沒有資料"
ONBOARDING_HERO_CTA = "建立第一筆"

#: 🔴 2026-09-23 A 把範圍擴到這兩句 —— `:473` 標題與 `:502` 副標。
#: 📌 A 的話：**「它們更貼身 —— 一個等著簽的人被告知沒東西要簽。」**
#: ⚠️ 我上一版把它們寫在「明著留在範圍外、交給 A 判」那一段，
#:    ⇒ 現在 A 判了要做。**留在範圍外的理由消失了，那一段跟著改掉。**
TITLE_COPY = "目前沒有待您簽核的項目"
BAND_COPY = "目前沒有待您簽核的單據"

#: 引導卡片的錨點：那一行註解。用它找卡片，不用行號 ——
#: ☠️ 行號會因為 B 在上面插一行就失效，而失效的樣子是「找不到 ⇒ 略過 ⇒ 綠」。
_CARD_ANCHOR = "ONBOARDING"


def _page():
    assert PAGE.exists(), f"找不到 {PAGE}"
    return PAGE.read_text(encoding="utf-8")


def _match_braces(text, start):
    """從 `text[start]` 的 `{` 開始，回傳含大括號的整段（含巢狀）。"""
    assert text[start] == "{", f"位置 {start} 不是 `{{`"
    depth, i, n = 0, start, len(text)
    in_s, quote, esc = False, "", False
    while i < n:
        c = text[i]
        if in_s:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_s = False
        elif c in "\"'`":
            in_s, quote = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise AssertionError("大括號沒有配對完 —— 抽取範圍八成抓錯了")


def _member(text, header):
    """抽出一個物件成員（`async loadStats() {…}` / `get heroSummary() {…}`）。

    回傳的是**可以直接放進物件字面值的原文** —— 不重寫、不改寫，
    🔑 因為這一題要跑的就是 B 寫的那一段本身。
    """
    at = text.find(header)
    assert at >= 0, (
        f"`index.html` 裡找不到 `{header}` ——\n"
        "⇒ 這一題的前提不成立（那一段的寫法變了）。\n"
        "☠️ 一個找不到受測物的測試不可以略過，它必須紅。")
    brace = text.index("{", at + len(header) - 1)
    return header + " " + _match_braces(text, brace)


def _card_gate(text):
    """引導卡片的 `x-show` 運算式（Alpine 作用域，沒有 `this.`）。"""
    at = text.find(_CARD_ANCHOR)
    assert at >= 0, (
        f"`index.html` 裡找不到錨點 `{_CARD_ANCHOR}` ——\n"
        "⇒ 引導卡片被搬走或改名了，這一題量不到它。")
    m = re.search(r'x-show="([^"]+)"', text[at:at + 4000])
    assert m, (
        "錨點之後 4000 字內找不到 `x-show=\"…\"` ——\n"
        "⚠️ 若 B 改用 `x-if` 或別的屬性，這裡要跟著改，"
        "**而不是讓它找不到就算了**。")
    expr = m.group(1)
    # 📏 正對照：那個 x-show 真的管得到 A 點名的文案嗎？
    card = text[at:at + 4000]
    assert ONBOARDING_CARD_COPY in card, (
        f"錨點之後 4000 字內沒有「{ONBOARDING_CARD_COPY}」——\n"
        "☠️ 那代表我抽到的 `x-show` 控制的**不是**那張卡片，\n"
        "🔑 而這一題的每一個綠燈都因此證明不了任何事。")
    return expr


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
#: 只剝「整行都是註解」的 JS 行註解 —— ☠️ 貪心一點就會把 `https://` 切掉。
_JS_LINE_COMMENT = re.compile(r"^[ \t]*//[^\n]*$", re.M)


def _without_comments(text):
    """剝掉 HTML 註解與整行 JS 行註解。

    🔑 **註解不是一個使用者讀得到的出口。**
    """
    return _JS_LINE_COMMENT.sub("", _HTML_COMMENT.sub("", text))


_ATTRS = ("x-if", "x-show", "x-text")


def _expr_behind(text, needle):
    """找出**決定那句文案出不出現**的那個 Alpine 運算式。

    回傳 `(屬性名, 運算式)`。做法是從文案往回找最近的
    `x-if=` / `x-show=` / `x-text=` ——
    📌 `:502` 那句在 `x-text` 的三元運算式**裡面**，
       `:473` 那句在 `x-if` 控制的 `<span>` **後面**，
    🔑 而「往回找最近的那一個」同時答得出這兩種形狀。
    """
    at = text.find(needle)
    assert at >= 0, (
        f"`index.html` 裡找不到「{needle}」——\n"
        "⇒ 這一題的前提不成立：那句文案被改寫或搬走了。\n"
        "☠️ **找不到不可以略過**，它必須紅 —— 否則文案一改，"
        "這一題就永遠是綠的而什麼都沒在看。")
    best = None
    for attr in _ATTRS:
        cut = text.rfind(attr + '="', 0, at)
        if cut >= 0 and (best is None or cut > best[0]):
            best = (cut, attr)
    assert best, f"「{needle}」前面找不到任何 {_ATTRS} 屬性"
    cut, attr = best
    start = cut + len(attr) + 2
    end = text.index('"', start)
    return attr, text[start:end]


def _stats_initial(text):
    """從 `index.html` **當場抽**初始 `stats` 宣告，不手寫。

    ☠️ 手寫一份的話，B 新增一個欄位時這裡不會跟著動，
    🔑 而模擬器與真頁面的落差**不會有任何症狀** —— 它只是悄悄量錯。
    """
    at = text.find("stats: {")
    assert at >= 0, "`index.html` 裡找不到 `stats: {` 的初始宣告"
    return "stats: " + _match_braces(text, text.index("{", at))


def _run_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
    out = subprocess.run([node, "-e", script], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, (
        f"node 跑不起來（exit={out.returncode}）：{out.stderr[-600:]}")
    return json.loads(out.stdout)


def _observe(text, response):
    """跑一次 `loadStats()`，回傳 `{card, hero, stats}`。

    `response` 是 `None` ⇒ `r.ok = false`（讀不到）；
    是一個 dict ⇒ `r.ok = true` 而 body 就是它。
    """
    load = _member(text, "async loadStats()")
    hero = _member(text, "get heroSummary()")
    overdue = _member(text, "get overdueWarranty()")
    gate = _card_gate(text)
    title_attr, title_expr = _expr_behind(text, TITLE_COPY)
    band_attr, band_expr = _expr_behind(text, BAND_COPY)

    script = """
const RESP = __RESP__;
const API = '';
globalThis.fetch = async () => (RESP === null
  ? { ok: false, status: 500, json: async () => { throw new Error('no body') } }
  : { ok: true,  status: 200, json: async () => RESP });

const PROTO = {
  __LOAD__,
  __HERO__,
  __OVERDUE__,
};

const raw = Object.create(PROTO);
Object.assign(raw, {
  // 📌 初始 stats 從 `index.html` **當場抽**，不手寫
  //    ——**而這一題不驗它是什麼**（A 明著排除 ⇒ 那是 FX34）。
  __STATS__,
  session: { token: 't', username: 'repro', display_name: 'repro' },
  departmentId: '',
  onboardingDismissed: false,
  followUpQuotes: [],
  loading: true,
});

// ⚠️ Alpine 的作用域：運算式裡寫 `stats.totalQuotes` 而不是 `this.stats…`。
//    `has` 永遠回真 ⇒ `with` 一律往這個物件找，找不到就是 undefined，
//    🔑 而那正是 Alpine 對「元件上沒有的欄位」的行為。
const self = new Proxy(raw, {
  has: () => true,
  get: (t, k) => Reflect.get(t, k, t),
  set: (t, k, v) => Reflect.set(t, k, v, t),
});

const scoped = (src) => (new Function('with (this) { return (' + src + ') }'));

(async () => {
  await self.loadStats();
  // 載入結束 —— 真的元件在 init() 尾巴把它關掉。
  self.loading = false;
  let card, hero, title, band, err = null;
  try {
    card = !!scoped(__GATE__).call(self);
    hero = String(self.heroSummary);
    // `:473` 是一個閘（x-if）⇒ 真＝那句話出現。
    title = !!scoped(__TITLE__).call(self);
    // `:502` 是一個產生式（x-text）⇒ 它回傳的就是畫面上那行字。
    band = String(scoped(__BAND__).call(self));
  } catch (e) { err = String(e && e.message || e); }
  console.log(JSON.stringify({
    card: card === undefined ? null : card,
    hero: hero === undefined ? null : hero,
    title: title === undefined ? null : title,
    band: band === undefined ? null : band,
    err,
    stats: { totalQuotes: raw.stats.totalQuotes,
             activeCases: raw.stats.activeCases,
             waitingForMe: raw.stats.waitingForMe },
    fields: Object.keys(raw).sort(),
  }));
})();
"""
    script = (script
              .replace("__RESP__", json.dumps(response, ensure_ascii=False))
              .replace("__LOAD__", load)
              .replace("__HERO__", hero)
              .replace("__OVERDUE__", overdue)
              .replace("__STATS__", _stats_initial(text))
              .replace("__GATE__", json.dumps(gate, ensure_ascii=False))
              .replace("__TITLE__", json.dumps(title_expr, ensure_ascii=False))
              .replace("__BAND__", json.dumps(band_expr, ensure_ascii=False)))
    got = _run_node(script)
    assert got["err"] is None, (
        f"評估那幾個觀測點時炸了：{got['err']}\n"
        "⇒ 這一題的前提不成立（抽取或作用域模擬壞了），**不是缺陷**。")

    # 📏 **模擬器自己的量尺**：運算式讀到的每一個欄位，
    #    我的模擬元件上都要真的有。
    # ☠️ 少了這一段，B 用了一個我沒種進去的欄位時，
    #    `with` 會讀到 `undefined` ⇒ 判斷式靜靜地走錯分支，
    # 🔑 **而結果看起來完全正常** —— 那是〈假綠燈〉最貴的一種。
    unseeded = _unseeded_fields([gate, title_expr, band_expr], got["fields"])
    assert not unseeded, (
        "這些欄位出現在判斷式裡，而我的模擬元件上沒有：" + "、".join(unseeded) + "\n"
        f"  已種的：{got['fields']}\n"
        "☠️ `with` 會把它們讀成 `undefined`，判斷式因此走錯分支，\n"
        "🔑 而這一題的每一個綠燈都因此證明不了任何事。\n"
        "📌 修法：把它種進 `Object.assign(raw, …)`，**不是把斷言放寬**。")
    return got


#: JS 關鍵字與字面值 —— 它們不是元件欄位。
_NOT_A_FIELD = {
    "true", "false", "null", "undefined", "typeof", "new", "in", "of",
    "this", "void", "instanceof", "return", "String", "Number", "Boolean",
    "Object", "Array", "Math", "JSON", "length",
}
_IDENT = re.compile(r"(?<![.\w$'\"])([A-Za-z_$][\w$]*)")


def _unseeded_fields(exprs, fields):
    """判斷式讀到、而模擬元件上沒有的欄位名。"""
    have = set(fields)
    seen = set()
    for e in exprs:
        for name in _IDENT.findall(e):
            if name in _NOT_A_FIELD or name in have:
                continue
            seen.add(name)
    return sorted(seen)


@pytest.fixture(scope="module")
def page():
    return _page()


# ══════════════════════════════════════════════════════════════════════
# FX33 · 讀不到 ⇒ 不可以說「你沒有資料」
# ══════════════════════════════════════════════════════════════════════

def test_fx33_a_failed_load_must_not_claim_there_is_no_data(page):
    """🔴🔴 FX33：`r.ok = false` ⇒ **新手引導那一組文案不可以出現。**

    ☠️ 那是一個**確定會發生**的情境（逾時／500／離線／後端重啟中），
    而後端重啟中正是這一包 `DEPLOY.md` 🔴🔴 那一步沒做時的樣子。
    🔑 使用者看到的是「系統目前還沒有資料」，而他有幾百筆 ——
    **他不會報修，因為那看起來就是一個正常的空狀態。**
    """
    got = _observe(page, None)

    assert got["card"] is False, (
        "讀不到資料，而新手引導卡片照樣顯示 ——\n"
        f"  卡片的判斷式：{_card_gate(page)}\n"
        f"  載入後的 stats：{got['stats']}\n"
        "☠️ 老使用者會看到「1. 建立客戶資料　2. 開立第一張報價單」。\n"
        "🔑 不變量是**讀不到時不可以說沒有資料**，怎麼實作不拘。")

    assert ONBOARDING_HERO_COPY not in got["hero"], (
        f"讀不到資料，而副標說：{got['hero']!r}\n"
        "☠️ 那句話在對使用者陳述一件我們**根本不知道**的事。\n"
        "📌 〈null 不等於 0〉：「沒拿到值」與「值是 0」不可以長得一樣。")
    assert ONBOARDING_HERO_CTA not in got["hero"], (
        f"讀不到資料，而副標叫使用者去建立第一筆：{got['hero']!r}")

    # 🔴 A 2026-09-23 擴進來的兩句 —— **它們更貼身**。
    assert got["title"] is False, (
        f"讀不到資料，而標題照樣說「{TITLE_COPY}」——\n"
        f"  那一句的判斷式：{_expr_behind(page, TITLE_COPY)[1]}\n"
        "☠️ **一個等著簽的人被告知沒東西要簽，而他會就這樣走開。**\n"
        "🔑 那不是「顯示 0」，那是**對他斷言了一件我們不知道的事**。")
    assert BAND_COPY not in got["band"], (
        f"讀不到資料，而副標那一行是：{got['band']!r}\n"
        f"  那一行的判斷式：{_expr_behind(page, BAND_COPY)[1]}\n"
        "☠️ 同一句謊話的同一個成因，只是換了一個位置說。")


def test_fx33_a_genuinely_empty_system_still_gets_its_onboarding(page):
    """⚙️ 反向控制①：**成功而且真的是空 ⇒ 那組文案要出現。**

    ☠️ 少了這一題，一個「**永遠不顯示引導**」的實作會讓上一題全綠 ——
    🔑 而全新安裝的使用者會打開一個什麼提示都沒有的空儀表板。
    📌 〈判準的寬窄都會騙人〉：「永遠不說」是「不要在讀不到時說」的超集，
       **而超集永遠比較好過。**
    """
    empty = {"totalQuotes": 0, "activeCases": 0, "waitingForMe": 0,
             "customerCount": 0, "closedCases": 0}
    got = _observe(page, empty)

    assert got["card"] is True, (
        "系統真的是空的，而新手引導沒有出現 ——\n"
        f"  卡片的判斷式：{_card_gate(page)}\n"
        f"  載入後的 stats：{got['stats']}\n"
        "☠️ 全新安裝的使用者會打開一個什麼提示都沒有的空儀表板。")
    assert ONBOARDING_HERO_COPY in got["hero"], (
        f"系統真的是空的，而副標說的是：{got['hero']!r}\n"
        "⇒ 那句「還沒有資料」現在連真的沒有資料時都不說了。")

    # ⚙️ 那兩句 `簽核` 的反向控制：**拿到了、而真的是 0 ⇒ 它們要說。**
    # ☠️ 少了這一段，「永遠不說那兩句」也會讓上一題綠，
    # 🔑 而一個真的沒事要簽的人會看到一個**沒有任何說明的空白**。
    assert got["title"] is True, (
        f"拿到了、而且真的沒有待簽，標題卻不說「{TITLE_COPY}」：{got['stats']}")
    assert BAND_COPY in got["band"], (
        f"拿到了、而且真的沒有待簽，副標那一行卻是：{got['band']!r}")


def test_fx33_a_system_with_data_shows_neither(page):
    """⚙️ 反向控制②：**成功而且有資料 ⇒ 那組文案不出現。**

    📌 這一題與上一題合起來，才把判準的兩端都釘住：
    ```
    讀不到   不說     ← 主題
    真的空   要說     ← 反向控制①
    有資料   不說     ← 反向控制②（本題）
    ```
    🔑 只有三種狀態都釘住，「**這句話跟著『有沒有拿到』走，不是跟著 0 走**」
       才是唯一能同時通過的實作。
    """
    loaded = {"totalQuotes": 128, "activeCases": 9, "waitingForMe": 0,
              "customerCount": 41, "closedCases": 60}
    got = _observe(page, loaded)

    assert got["card"] is False, (
        f"系統有 128 張報價單、9 件進行中案件，而新手引導照樣顯示：{got['stats']}")
    assert ONBOARDING_HERO_COPY not in got["hero"], (
        f"系統有資料，而副標說：{got['hero']!r}")
    # 📌 而「沒有待您簽核」在這裡是**真的** —— 它要說。
    #    ⚠️ 這一格與上一題一起，把那兩句釘成
    #    **跟著「有沒有拿到」走，不是跟著「有沒有資料」走**。
    assert got["title"] is True, (
        f"有資料、而待簽真的是 0，標題卻不說「{TITLE_COPY}」：{got['stats']}\n"
        "☠️ 修過頭了：那兩句現在連在該說的時候都不說。")


def test_fx33_the_probe_reaches_the_two_places_that_say_it(page):
    """📏 量尺：**那組文案真的在我量的那兩個地方。**

    ☠️ 少了這一題，文案被搬到第三個地方之後，
    上面三題會**一起安靜地綠** —— 因為它們量的那兩處都不再說那句話了，
    🔑 而使用者照樣讀得到它。

    ⚠️ 這一題擋得住「搬家」，**擋不住「新增一個第四處」** ——
    那一格只有目視填得起來。
    """
    text = page
    card_at = text.find(_CARD_ANCHOR)
    card = text[card_at:card_at + 4000]
    assert ONBOARDING_CARD_COPY in card, (
        f"引導卡片裡沒有「{ONBOARDING_CARD_COPY}」了 —— 文案搬家了？")

    hero = _member(text, "get heroSummary()")
    assert ONBOARDING_HERO_COPY in hero, (
        f"`heroSummary` 裡沒有「{ONBOARDING_HERO_COPY}」了 —— 文案搬家了？")
    assert ONBOARDING_HERO_CTA in hero, (
        f"`heroSummary` 裡沒有「{ONBOARDING_HERO_CTA}」了 —— 文案搬家了？")

    # 📌 而整份 `index.html` 裡，那兩句各只准出現在自己那一處。
    #    ☠️ 出現第二次 ＝ 有一個我沒在量的出口。
    # ⚠️ **數的是「會被使用者讀到的地方」，不是「字串出現過幾次」。**
    # ☠️ 我第一版直接 `text.count()` ⇒ 紅在 `:1064`，
    #    而那一行是 **B 寫的註解**，裡面**引用**了那句文案。
    # 🔑 那是〈判準的寬窄都會騙人〉的「太寬」那一側：
    #    超集（所有出現）比目標（所有出口）好數，而它給的是假紅燈。
    # 📌 ⇒ 註解先剝掉再數。
    visible = _without_comments(text)
    for needle, where in ((ONBOARDING_HERO_COPY, "heroSummary"),
                          (ONBOARDING_CARD_COPY, "引導卡片"),
                          (TITLE_COPY, ":473 標題"),
                          (BAND_COPY, ":502 副標")):
        n = visible.count(needle)
        assert n == 1, (
            f"「{needle}」在 `index.html` 的**非註解**部分出現 {n} 次，"
            f"而我只量得到 {where} 那一處。\n"
            "☠️ 多出來的那一處會在讀不到資料時照樣說出口，而沒有人在看它。")


def test_fx33_the_probe_goes_red_on_the_version_before_the_fix():
    """📏 **量尺：同一支探針餵進修正前的那一版，要紅。**

    ☠️ 少了這一題，上面四題的綠證明不了任何事 ——
    一支**永遠說沒問題**的探針，在修好的程式上也是全綠的。
    🔑 而這一題問的是：**它分辨得出「修了」與「沒修」嗎？**

    ⚠️ 基準版本釘死在 `c89e9d9`（`1016b18` 的前一個，B 動手之前），
    **不是 `HEAD~1`** —— 共用工作目錄裡會動的名字會指到別人的東西。
    📌 而這一題**不釘 `statsLoaded` 這個旗標名**：它比較的是兩個版本的
    **行為**，所以 B 日後改用別的寫法，這一題照樣有效。
    """
    import subprocess as sp
    repo = PAGE.parent.parent
    old = sp.run(["git", "show", "c89e9d9:frontend/index.html"],
                 cwd=str(repo), capture_output=True, timeout=60)
    assert old.returncode == 0, (
        f"取不到 `c89e9d9` 的 `index.html`：{old.stderr[-300:]!r}\n"
        "⇒ 這一題量不到東西，**不可以當成通過**。")
    before = old.stdout.decode("utf-8")

    got = _observe(before, None)  # 讀不到資料
    lied = []
    if got["card"]:
        lied.append("引導卡片")
    if ONBOARDING_HERO_COPY in got["hero"]:
        lied.append("heroSummary")
    if got["title"]:
        lied.append(":473 標題")
    if BAND_COPY in got["band"]:
        lied.append(":502 副標")

    assert len(lied) == 4, (
        f"修正前那一版，只有 {lied} 這幾處說了謊（預期四處全中）。\n"
        "☠️ 那代表這支探針看不見其中幾處，\n"
        "🔑 而它在**修正後**的版本上照樣全綠 —— 綠得沒有意義。")
