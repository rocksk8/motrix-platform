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


def scan():
    rows = []
    for p in sorted(glob.glob(PAGES_GLOB)):
        s = _read(p)
        if not re.search(r'x-data="([^"]+)"[^>]*x-init="([^"]*init\(\)[^"]*)"', s):
            continue
        blob = "\n".join([s] + [_read(j) for j in _linked_js(s, p)])
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
    print("修法見本檔 docstring。驗證：用瀏覽器開該頁、數它的載入 API 被打幾次，"
          "必須是 1（比照 test_e2e_system_settings_ui_2026_09_11.py::"
          "test_init_runs_exactly_once，那是確定性斷言，不必等競態重現）。")


if __name__ == "__main__":
    main()
