# -*- coding: utf-8 -*-
"""`AS4` · 「匯款申請簽核設定」的獨立入口拿掉，改整合進「簽核設定」
（`STATE.md §259`，A 實查）。

使用者原話：
```
「匯款申請會簽整合進簽核設定，但系統內仍然有一個匯款申請簽核設定的選項」
```

# 🔴 成因（A 實查）

```
側欄 sidebar.js       舊入口
舊頁                   PUT /api/contractor-vouchers/settings/approval-flow
                       -> _set_setting("contractor_voucher_approval_flow")
新頁 approval-settings.html  independent: 'contractor_voucher_approval_flow'
⇒ 兩個入口寫同一把 key，而舊頁不知道「統一／獨立」那個開關存在
   ⇒ 範圍是「統一流程」時，舊頁存的設定永遠不會被用到
```

# ⚙️ 本檔三題對應規格逐字給的三格

```
(a) 側欄不可以再出現那個舊入口
    ⚠️ 釘「那個檔名不出現在 sidebar.js 的導覽項裡」，不要釘中文字串
       （中文標籤會被 WD1／EM1 改）
(b) 舊頁導向新頁 —— 而不可以是 404
    ⚠️ 正對照：直接開那個 .html 要拿得到「已整合」那句話或一個轉址
(c) 稽核紀錄裡的同名選項要留著（audit-log.html）
    ⇒ 反向控制：那一格被順手刪掉要紅
    🔑 它是歷史篩選不是設定入口 —— 歷史發生過就是發生過
```

# 📌 動工前實查：B 這一輪已經把三格都做了

`sidebar.js:805`／`contractor-voucher-approval-settings.html`／
`audit-log.html:300,593` 三處都已經帶著 `AS4` 標記的註解。
⇒ 本檔多數題**今天應該是綠的** —— 它們的價值是**鎖住**這個狀態，
  不是驗出一個還沒做的東西。每題已在 docstring 標「現在應該是綠還是紅」。
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 舊入口的檔名 —— **技術識別碼**，不是中文標籤。
OLD_PAGE = "contractor-voucher-approval-settings.html"
NEW_PAGE = "approval-settings.html"

#: 舊頁與新頁共用的 `system_settings` key，用來釘「同一把 key」這個事實
#: （這是成因，不是本檔要驗的行為，只在 docstring 裡對照，不寫進斷言）。
SHARED_KEY = "contractor_voucher_approval_flow"

#: `(c)`：歷史稽核篩選的技術識別碼 —— **這是寫進過 `audit_log` 表的字串**，
#: 與畫面上的中文標籤不同層級，改了它舊紀錄就篩不出來，所以要釘死。
AUDIT_ACTION = "settings.contractor_voucher_approval_flow.update"


def _read(rel_path):
    p = ROOT / rel_path
    assert p.exists(), "檔案不存在：%s" % rel_path
    return p.read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════
# (a) 側欄不可以再出現舊入口
# ══════════════════════════════════════════════════════════════════════

def test_as4_the_old_entry_is_gone_from_the_sidebar():
    """🟢 **今天應該是綠的**（B 已拿掉，`sidebar.js:805` 有 `AS4` 註解）。

    ⚠️ 釘**檔名**不釘中文標籤 —— 中文標籤會被 `WD1`／`EM1` 這類措辭守門改掉，
       釘了字串會在別人做對的事情時紅。
    """
    # C4：選單宣告不在 sidebar.js 了 ⇒ 兩邊都查（宣告＋前端程式碼）
    from tests._menu_decl import declared_items
    src = _read("frontend/static/sidebar.js") + "\n".join(it["href"] for it in declared_items())
    assert OLD_PAGE not in src, (
        "選單宣告或 `sidebar.js` 裡還找得到 `%s`：\n" % OLD_PAGE
        + "☠️ 舊入口還在 ⇒ 使用者又會走到一個「設了也不一定生效」的頁面。")


def test_as4_the_detector_actually_works_on_a_real_entry():
    """⚙️ **正對照：探測法本身抓得到真的存在的入口。**

    ☠️ 少了它，`sidebar.js` 若被整個清空、或這支測試的路徑指到空檔案，
       上一題會**無條件綠** —— 「找不到」與「檔案讀錯了」分不出來。
    """
    from tests._menu_decl import declared_items
    src = _read("frontend/static/sidebar.js") + "\n".join(it["href"] for it in declared_items())
    assert NEW_PAGE in src, (
        "選單宣告裡找不到 `%s`（新的「簽核設定」入口）。\n" % NEW_PAGE
        + "☠️ 若連這個都找不到，代表讀到的不是真正的 `sidebar.js`，\n"
          "   上一題的『找不到舊入口』就沒有意義。")


# ══════════════════════════════════════════════════════════════════════
# (b) 舊頁導向新頁，而不可以是 404
# ══════════════════════════════════════════════════════════════════════

def test_as4_the_old_page_is_not_a_404(client):
    """🟢 **今天應該是綠的**（B 已把舊頁改成導向頁）。

    ⚠️ **不直接刪檔**：舊書籤還會連到這裡，而 404 說不出「搬到哪裡去了」。
    """
    r = client.get("/pages/%s" % OLD_PAGE)
    assert r.status_code == 200, (
        "舊頁 `%s` 回 %s（預期 200）。\n" % (OLD_PAGE, r.status_code)
        + "☠️ 404 的話，還連著舊書籤的人只會看到「找不到網頁」，\n"
          "   說不出這個設定搬到哪裡去了。")


def test_as4_the_old_page_names_where_it_moved_to(client):
    """🔴🔴 **`(b)` 正對照：舊頁要講得出「搬到哪裡」，不是只回 200。**

    ☠️ 少了它，一個「內容清空但狀態碼是 200」的頁面也會讓上一題綠——
       那與 404 對使用者是同一種體驗：**看不出設定去哪了**。
    ⚙️ 兩個都驗：文字提到「已整合」或「簽核設定」，且有連到新頁的連結
       （轉址或超連結，任一種都算數，不釘死用哪一種手法）。
    """
    r = client.get("/pages/%s" % OLD_PAGE)
    assert r.status_code == 200, "先看上一題。"
    body = r.text
    assert ("已整合" in body) or ("簽核設定" in body), (
        "舊頁的內容裡找不到「已整合」或「簽核設定」這類字樣：\n%s\n"
        % body[:300]
        + "☠️ 使用者打開一個空白或無關的頁面，一樣看不出設定搬去哪了。")
    assert (NEW_PAGE in body), (
        "舊頁的內容裡找不到指向 `%s` 的連結或轉址：\n%s\n" % (NEW_PAGE, body[:300])
        + "☠️ 光說「已整合」而不給路徑，使用者還是要自己去翻側欄找。")


# ══════════════════════════════════════════════════════════════════════
# (c) 稽核紀錄裡的同名選項要留著 —— 反向控制
# ══════════════════════════════════════════════════════════════════════

def test_as4_the_audit_log_filter_option_still_exists():
    """🟢 **今天應該是綠的**（B 沒有動它，`audit-log.html:300,593` 兩處都在）。

    🔑 這是**反向控制**：它存在的理由與 `(a)` 相反 ——
       `(a)` 是入口要拿掉，這裡是**歷史篩選要留著**，兩者長得像但不是同一件事，
       混在一起做的話最容易犯的錯是「看到 `contractor_voucher_approval_flow`
       字樣就一起清掉」。
    """
    src = _read("frontend/pages/audit-log.html")

    option_pattern = r'<option\s+value="%s"' % re.escape(AUDIT_ACTION)
    assert re.search(option_pattern, src), (
        "`audit-log.html` 裡找不到 `<option value=\"%s\">`。\n" % AUDIT_ACTION
        + "☠️ 這是**歷史篩選**，不是設定入口 —— 歷史發生過就是發生過，\n"
          "   拿掉它之後，已經寫進 `audit_log` 表的那些舊紀錄**篩不出來**\n"
          "   （不是紀錄不見了，是使用者再也找不到它）。")

    map_pattern = r"'%s':\s*'[^']+'" % re.escape(AUDIT_ACTION)
    assert re.search(map_pattern, src), (
        "`audit-log.html` 裡找不到 `%s` 對應的中文標籤 map。\n" % AUDIT_ACTION
        + "☠️ `<option>` 還在而標籤 map 被清掉的話，篩選器上會出現一個\n"
          "   讀不出意思的原始字串，使用者看得到但看不懂。")


def test_as4_deleting_the_audit_entry_would_be_caught(tmp_path):
    """⚙️ **`(c)` 反向控制的自我驗證：真的刪掉那一格，上一題要紅。**

    ☠️ 沒有這一題，上一題也可能是「碰巧沒被刪」而不是「刪了會被抓到」——
       正對照要走**同一條偵測路徑**，不是另外開一條。
    """
    real = ROOT / "frontend/pages/audit-log.html"
    src = real.read_text(encoding="utf-8", errors="replace")

    option_pattern = r'<option\s+value="%s"[^>]*>[^<]*</option>\n?' % re.escape(
        AUDIT_ACTION)
    stripped, n = re.subn(option_pattern, "", src)
    assert n == 1, (
        "拿掉 `<option>` 那一行的正則命中 %d 次（預期 1 次）。\n" % n
        + "📌 這是我自己的偵測探針要先驗證的地方 —— 命中數不對，\n"
          "   後面「重跑判準會紅」這件事就沒有意義。")

    fake = tmp_path / "audit-log.html"
    fake.write_text(stripped, encoding="utf-8")

    fake_src = fake.read_text(encoding="utf-8", errors="replace")
    option_pattern_check = r'<option\s+value="%s"' % re.escape(AUDIT_ACTION)
    assert not re.search(option_pattern_check, fake_src), (
        "刪掉那一格之後，偵測條件卻還是命中 —— 合成輸入沒有生效，\n"
        "這支反向控制本身是壞的。")
