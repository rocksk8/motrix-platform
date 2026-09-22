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

刻意用守門而不是把 `x-init="init()"` 拿掉——拿掉才是語意正確的作法，但全站 49 頁
一起改動風險大，而且 `x-init` 還有別的頁面拿來做其他事，守門對兩種寫法都有效。

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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
_DECL_RE = re.compile(r'x-data="([^"]+)"[^>]*x-init="([^"]*init\(\)[^"]*)"')


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


def injected_rows():
    """**注入型**母體：宣告點不在任何頁面，而在共用 js 注入的 HTML 上。

    ## ⚠️ 宣告點與定義點是**兩個檔**

    ```
    sidebar.js  x-data="globalSearchStore()" ／ x-data="notifStore()"  <= **宣告點**
    notif.js    那兩支函式的定義                                        <= 定義點
    ```
    ☠️ 掃 `notif.js` 找**宣告**會得到 **0 個** —— 而「0」讀起來像「沒有問題」。
    🔑 ⇒ 要掃的是 `sidebar.js`。
    📌 而這一群**不可以併進頁面母體**：它們是同一份注入 HTML，
       修一次就全部修好，與「53 頁各自要修」不是同一件事。
    """
    out = []
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("sidebar.js",):
        p = os.path.normpath(os.path.join(base, "..", "..",
                                          "frontend", "static", name))
        if not os.path.exists(p):
            continue
        src = _read(p)
        for m in _DECL_RE.finditer(src):
            out.append({"where": name, "component": m.group(1),
                        "guarded": "_initDone" in src})
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
    print("Alpine 雙重初始化掃描：共 %d 頁使用 x-data + x-init=\"init()\"\n" % len(rows))
    print("  %-8s %-44s %s" % ("風險", "頁面", "x-model 欄位數"))
    cur = None
    for r in shown:
        lab = LABEL[r["risk"]]
        if lab != cur:
            print()
            cur = lab
        print("  %-8s %-44s %d" % (lab, r["page"], r["editable"]))
    todo = [r for r in rows if not r["guarded"]]
    print("\n待修 %d 頁／已修 %d 頁" % (len(todo), len(rows) - len(todo)))

    # ── 注入型：**另一個母體，不併進上面的數字** ──────────────────
    inj = injected_rows()
    inj_todo = [r for r in inj if not r["guarded"]]
    print("\n注入型（宣告點在共用 js，不屬於任何一頁）：待修 %d／共 %d"
          % (len(inj_todo), len(inj)))
    for r in inj:
        print("  %-8s %-44s %s"
              % (LABEL[0] if r["guarded"] else LABEL[2], r["component"], r["where"]))

    # ── 自檢：共用檔裡不該有 `_initDone` ──────────────────────────
    # ☠️ 有的話，上面那 53 頁的數字就不可信了 —— 一個共用檔就能讓全部翻綠。
    # 🔑 而它不會報錯：報表會變好看，**而那正是它危險的地方**。
    dirty = sorted(os.path.basename(j) for j in shared_js()
                   if "_initDone" in _read(j))
    print("\n⚙️ 自檢：%d 支共用 js 裡帶 `_initDone` 的 => %s"
          % (len(shared_js()), dirty or "（無）✅"))
    if dirty:
        print("   🔴 上面的「已修」數字**不可信** —— 一個共用檔會讓引用它的頁全部翻綠。")
    print("修法見本檔 docstring。驗證：用瀏覽器開該頁、數它的載入 API 被打幾次，"
          "必須是 1（比照 test_e2e_system_settings_ui_2026_09_11.py::"
          "test_init_runs_exactly_once，那是確定性斷言，不必等競態重現）。")


if __name__ == "__main__":
    main()
