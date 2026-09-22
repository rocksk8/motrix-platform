"""掃出「Alpine init() 會跑兩遍」的頁面，並依風險排序（2026-09-11 新增）。

**問題本身**：`<body x-data="foo()" x-init="init()">` —— Alpine 3 本來就會自動
呼叫資料物件的 `init()`，`x-init` 再寫一次就剛好跑兩遍，**完全沒有警告**。
後果不只是 API 發兩次：第二次載入的回應晚一步抵達，會把使用者這段期間改過的
欄位用伺服器上的舊值**無聲蓋回去**。

已經因此踩過兩次：
  - 2026-09-11 第三輪 `case-management.js`（新增可編輯的叫料清單才逼出來）
  - 2026-09-11 第四輪 `company-profile-settings.html`（系統技術設定被蓋回舊值，
    同時是那支 e2e 偶發紅的根因）

**修法**（兩行，沿用既有慣例）：

    _initDone: false,

    async init() {
      if (this._initDone) return
      this._initDone = true
      ...

刻意用守門而不是把 `x-init="init()"` 拿掉——拿掉才是語意正確的作法，但**全部母體頁**
一起改動風險大（⚠️ 這裡刻意不寫頁數：母體會長大，寫死的數字一個月就過期），而且 `x-init` 還有別的頁面拿來做其他事，守門對兩種寫法都有效。

**風險分級**：`x-model` 欄位數只是「使用者可編輯面積」的粗略代理，會低估用
`:value` / `@change` 綁定的頁面（例如 `settlement.html` 實際上是重編輯頁，卻只
數到 4）。**排序拿來決定先後就好，不要當成「低風險就不用修」。**

用法：
    cd backend && python tools/check_double_init.py
    python tools/check_double_init.py --todo     # 只列還沒修的
"""
import glob
import io
import os
import re
import sys

# 🔴 `(a-1)`：這支腳本會 `print` emoji，而這台機器的主控台是 **cp932**
#    ⇒ 不做這一行它會 `UnicodeEncodeError` **整支崩潰**，一個字都印不出來。
# ⚠️ 而**不要為此把 emoji 拿掉** —— 拿掉報表就沒有可讀性，
#    而下一個人會再加回來 ⇒ **那是修結果**。
# 📌 這台機器上**任何 print emoji 的腳本都會**踩到，不只這一支。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    # ⚠️ stdout 不一定 reconfigure 得動（被包過、被換掉、不是 TextIO）。
    #    ⇒ 失敗**不可以讓這支死掉** —— 真正的保險在下面的 `say()`。
    pass


def say(line=""):
    """印一行；印不出去就**降級**，不要死。

    ## 🔴 為什麼不是「把 emoji 換成 ASCII」

    A 裁定過：拿掉 emoji 報表就沒有可讀性，而下一個人會再加回來 ⇒ **那是修結果**。
    ⇒ 這裡保留 emoji，而**印不出去時自動換成 ASCII** ——
      主控台看得懂就給好看的，看不懂就給看得懂的，**兩邊都不會死**。

    ## ☠️ 而「死」的樣子特別壞

    `UnicodeEncodeError` 發生在**印到一半** ⇒ 前面幾行出來了、待修清單沒有
    ⇒ **看起來像跑完了**。
    🔑 〈Windows 查驗陷阱〉：這台機器上的失敗常常長成「少了一段輸出」。

    ⚠️ `sys.stdout.reconfigure()` 擋不住這件事：它在 **import 當下**作用在
       當時那個 stdout 上；之後被換掉的（測試替身、包裝過的管線）它管不到。
    """
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))

PAGES_GLOB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "frontend", "pages", "*.html")


def _read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def _linked_js(page_src, page_path):
    """頁面自己 include 的專案 js——init() 常常寫在那裡而不是頁面內。
    漏掉這一步會把 case-management.html 誤判成未修（它的守門在 js 檔裡）。"""
    out = []
    for m in re.finditer(r'<script[^>]+src="([^"]+\.js)"', page_src):
        src = m.group(1)
        if "vendor" in src or src.startswith("http"):
            continue
        cand = os.path.normpath(os.path.join(os.path.dirname(page_path), src))
        if os.path.exists(cand):
            out.append(cand)
    return out


#: 同時宣告 `x-data` 與明著呼叫初始化的那個屬性 —— 那就是會跑兩遍的形狀。
#: ⚠️ 兩種引號都吃。📌 而今天單引號的寫法實算 **0**
#:    —— 那是「今天乾淨」，**不是「regex 夠寬」**。0 不是證據。
_DECL_RE = re.compile(
    r"x-data=(?P<q1>[\"'])(?P<data>(?:(?!(?P=q1)).)*)(?P=q1)"
    r"[^>]*?x-init=(?P<q2>[\"'])"
    r"(?P<init>(?:(?!(?P=q2)).)*init\(\)(?:(?!(?P=q2)).)*)(?P=q2)")


def shared_js():
    """被**超過一頁** script-link 的 js。**算出來，不手列。**

    ## 🔴 `(a-2)`：這份清單是判準的一半，而它原本不存在

    舊判準是「頁面 ＋ **所有** linked js 裡有沒有 `_initDone`」。
    ☠️ 而 `auth-guard.js`／`notif.js`／`sidebar.js` **各被 57 頁引用**
       ⇒ `_initDone` 寫進其中任何一個，**53 頁會一起翻成「已修」**
       ⇒ 而那 53 頁**一頁都沒有真的修過**。
    🔑 最毒的是：要修的那兩個 store 就在 `notif.js`
       ⇒ **修法本身就是引信。**

    ⚠️ 手列清單會腐爛（有人新增共用檔就漏掉）⇒ 這裡即時算。
    ⚙️ 今天實算是 7 支；那個數字**不寫死**，只拿來對照。
    """
    count = {}
    for p in sorted(glob.glob(PAGES_GLOB)):
        for j in _linked_js(_read(p), p):
            count[j] = count.get(j, 0) + 1
    return {j for j, n in count.items() if n > 1}


#: 共用 js 的掃描範圍。**一個模組層常數**，不是寫死在函式裡的檔名。
#: 🔴 `§174c`：排除清單與共用母體**一律算出來，不要寫死 `sidebar.js`**。
#:    今天只有它有宣告，所以兩種寫法同分 —— 差別在**另外 6 支任何一支
#:    被加上 `x-data + x-init` 的那天**：寫死版會**靜默漏掉**。
#: ⚠️ 範圍是 `frontend/**/*.js`（遞迴），**與 `shared_js()` 的來源同源** ——
#:    `shared_js()` 從實際 `<script src>` 算 ⇒ 涵蓋 `frontend/js` 與
#:    `frontend/static` **兩個**目錄；這裡只吃其中一個的話，另一個目錄的
#:    注入型宣告會**被排除得到、而數不到** ⇒ 靜默無守衛、無回報。
STATIC_GLOB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "frontend", "**", "*.js")


def _js_files(pattern=None):
    """共用 js 的取檔。**與 `shared_js()` 的來源同源。**

    ## 🔴 兩個集合的範圍不對稱，母體就會少一個目錄

    ```
    排除集合 shared_js()    從**實際 <script src>** 算 ⇒ 涵蓋 frontend/js ＋ frontend/static
    共用母體 舊 scan_shared() glob 只吃 frontend/static/*.js
    ⇒ 從 frontend/js 注入的宣告：**排除得到，而數不到**
    ```
    ☠️ 那是 `AL1` 原本的缺陷**換一個目錄重演** ——
       兩個都是**靠一份寫死的範圍在決定誰被看見**。
    ✅ 今天 `frontend/js` 的注入型宣告實算 **0**，所以現況不受影響。

    ⚠️ `vendor` 要排掉，而**比對的是路徑「片段」不是子字串**：
       `pages/vendor-contractors.html` 這種名字不可以被順手掃掉。
    """
    out = []
    for p in sorted(glob.glob(pattern or STATIC_GLOB, recursive=True)):
        parts = os.path.normpath(p).replace("\\", "/").split("/")
        if "vendor" in parts:
            continue
        out.append(p)
    return out


def _def_body(name):
    """`function name() { … }` 的本體。回 `(檔名, 本體)`，找不到回 `(None, None)`。

    ## ☠️ 切點用「下一個頂層 function」，而那**會安靜長大**

    ```
    notifStore 真正結束於       行 395
    「下一個頂層 function」在    行 401     ⇒ 多切 6 行
    ```
    今天多出來的是一個 `}` 與一段註解 ⇒ 無害。
    ⚠️ 而有人在兩個 store 之間加一段**不是頂層 function 的頂層程式碼**
       （`const x = …`／IIFE／`addEventListener`）⇒ 那整段就算進前一個 store
       ⇒ **`_initDone` 寫在那裡會被判成已修**。

    ## 🔴 所以自檢要驗「切太長」，而 `"init(" in body` **驗不到**

    ```
    切太短／找不到  init( 不在 body   => 抓得到  ✅
    切太長          init( **仍然在**   => 永遠通過 ❌  <= 而要防的正是這個
    ```
    ☠️ 正確的本體裡本來就有 `init(`，**再往後接多少東西它都還是有**。
    🔑 而我原本在這段 docstring 裡宣告它防的正是切太長 ——
      **一段寫得很有說服力的解釋，會讓下一個人不去驗那個自檢**。
    ⇒ 真正的自檢是**大括號配對**：切到的結尾必須就是本體的結尾。
    """
    for p in _js_files():
        src = _read(p)
        m = re.search(r"^function\s+%s\s*\(" % re.escape(name), src, re.M)
        if not m:
            continue
        rest = src[m.end():]
        end = _balanced_end(rest)
        if end is None:
            # ⚠️ 配不起來（字串／註解裡的大括號、或檔案被截斷）
            #    ⇒ **不猜**，回 None 讓上層一律報未修。
            return os.path.basename(p), None
        return os.path.basename(p), rest[:end]
    return None, None


def _balanced_end(text):
    """從 `text` 起算，第一個 `{` 的配對 `}` 之後的位置。配不起來回 `None`。

    ⚠️ 這是**近似**的：字串字面值與註解裡的大括號會被算進去。
    🔑 而它比「下一個頂層 function」好的地方是**方向對** ——
      它的誤差會讓本體變短（提早收），不會把隔壁的東西吸進來。
    """
    depth = 0
    started = False
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return i + 1
    return None


def scan_shared():
    """**注入型**母體：宣告點不在任何頁面，而在共用 js 注入的 HTML 上。

    ## ☠️ 宣告點與定義點是**兩個檔**（`§174c`，A-2 攔下來的）

    ```
    sidebar.js  x-data="globalSearchStore()" ／ x-data="notifStore()"  <= **宣告點**
    notif.js    那兩支函式的本體（`_initDone` 要寫進去的地方）          <= **定義點**
    ```
    ☠️ 掃 `notif.js` 找**宣告**會得到 **0 個** —— 而「0」讀起來像「沒有問題」。
    🔑 ⇒ **數**的是宣告點，**改**的是定義點，而它們不是同一個檔。
    📌 而這一群**不可以併進頁面母體**：頁面母體是「某些頁」，
       這一群是注入的 ⇒ **所有頁都中**，修一次全部修好。
    """
    out = []
    for p in _js_files():
        src = _read(p)
        for m in _DECL_RE.finditer(src):
            store = m.group("data")
            fn = re.match(r"\s*(\w+)", store)
            where, body = _def_body(fn.group(1)) if fn else (None, None)
            # ⚙️ 自檢：本體裡必須有 `init(`。⚠️ 它只抓得到「切太短／切錯」
            #    ——「切太長」由 `_balanced_end()` 擋（見 `_def_body`）。
            ok = bool(body) and "init(" in body
            out.append({"where": os.path.basename(p), "store": store,
                        "defined_in": where or "（找不到定義）",
                        "guarded": ok and "_initDone" in body})
    return out


def scan():
    rows = []
    shared = shared_js()
    for p in sorted(glob.glob(PAGES_GLOB)):
        s = _read(p)
        if not _DECL_RE.search(s):
            continue
        # 🔴 `(a-2)`：只看**這一頁自己的** js —— 共用檔排除（見 `shared_js()`）。
        own = [j for j in _linked_js(s, p) if j not in shared]
        blob = "\n".join([s] + [_read(j) for j in own])
        guarded = "_initDone" in blob
        editable = len(re.findall(r'x-model="', s))
        if guarded:
            risk = 0          # 已修
        elif editable >= 25:
            risk = 1          # 高
        elif editable >= 5:
            risk = 2          # 中
        else:
            risk = 3          # 低
        rows.append({"page": os.path.basename(p), "guarded": guarded,
                     "editable": editable, "risk": risk})
    rows.sort(key=lambda r: (r["risk"] if r["risk"] else 9, -r["editable"]))
    return rows


LABEL = {0: "✅ 已修", 1: "🔴 高", 2: "🟠 中", 3: "🟢 低"}


def main():
    todo_only = "--todo" in sys.argv
    rows = scan()
    shown = [r for r in rows if not r["guarded"]] if todo_only else rows
    say("Alpine 雙重初始化掃描：共 %d 頁使用 x-data + x-init=\"init()\"\n" % len(rows))
    say("  %-8s %-44s %s" % ("風險", "頁面", "x-model 欄位數"))
    cur = None
    for r in shown:
        lab = LABEL[r["risk"]]
        if lab != cur:
            say()
            cur = lab
        say("  %-8s %-44s %d" % (lab, r["page"], r["editable"]))
    todo = [r for r in rows if not r["guarded"]]
    say("\n待修 %d 頁／已修 %d 頁" % (len(todo), len(rows) - len(todo)))

    # ── 注入型：**另一個母體，不併進上面的數字** ──────────────────
    inj = scan_shared()
    inj_todo = [r for r in inj if not r["guarded"]]
    say("\n注入型（宣告點在共用 js，不屬於任何一頁）：待修 %d／共 %d"
          % (len(inj_todo), len(inj)))
    for r in inj:
        say("  %-8s %-44s %s"
              % (LABEL[0] if r["guarded"] else LABEL[2], r["store"],
             "%s -> %s" % (r["where"], r["defined_in"])))

    # ── 自檢：共用檔裡不該有 `_initDone` ──────────────────────────
    # ☠️ 有的話，上面那 53 頁的數字就不可信了 —— 一個共用檔就能讓全部翻綠。
    # 🔑 而它不會報錯：報表會變好看，**而那正是它危險的地方**。
    dirty = sorted(os.path.basename(j) for j in shared_js()
                   if "_initDone" in _read(j))
    say("\n⚙️ 自檢：%d 支共用 js 裡帶 `_initDone` 的 => %s"
          % (len(shared_js()), dirty or "（無）✅"))
    if dirty:
        say("   🔴 上面的「已修」數字**不可信** —— 一個共用檔會讓引用它的頁全部翻綠。")
    say("修法見本檔 docstring。驗證：用瀏覽器開該頁、數它的載入 API 被打幾次，"
          "必須是 1（比照 test_e2e_system_settings_ui_2026_09_11.py::"
          "test_init_runs_exactly_once，那是確定性斷言，不必等競態重現）。")


if __name__ == "__main__":
    main()
