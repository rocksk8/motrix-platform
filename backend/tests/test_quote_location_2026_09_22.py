"""§9 QL1–QL15 · 報價單綁據點。

使用者裁示：「**報價單綁據點這件做**」。§5 多據點剛落地，這一節把「據點」
從一張通訊錄變成**一個會印在單據上的身分**。

---

# 🔑 A 實查到的兩件，它們決定了這一節的形狀

## ① 所有單據表都掛在 `quote_no` 上

```
case_action_items / case_change_requests / case_extra_expenses / case_stages /
case_updates / completion_notes / contractor_dispatches /
contractor_payment_vouchers / invoice_vouchers / network_plans /
payment_requests / quotations / shipping_notes / stock_items
```
⇒ **據點綁在 `quotations` 一處就好**（QL1）。
☠️ 每張單各存一次的話，會製造「同一個案子的兩張單印不同抬頭」。
⚠️ 唯一例外 `payslips` —— 它掛 `contractor_id`，**是人事文件不是案件文件**（QL8）。

## ② 公司身分有兩個來源，狀況完全不同

```
抬頭   pdf_gen.py 寫死                  ← 我實測：8 支 builder 各 4 行，共 32 行
銀行   pdf_gen.py:2006 讀 company_profile ← 只有 1 處
```
☠️ **所以「綁據點」不是一件事，是兩件。**

---

# 🔴 我在寫題時查到的三件，A 的條文裡沒有

## ⓐ `_build_payslip_html` **一行公司身分都沒有寫死**

它的抬頭來自**呼叫端傳進來的 dict**：
```python
pdf_gen.py:502   company = d.get('companyName', '')
pdf_gen.py:805   html_content = _build_payslip_html(d)
pdf_gen.py:801   d = json.loads(row["data_json"] or "{}")
```
⇒ 🔴 **那是開單時寫進 `payslips.data_json` 的快照** ——
☠️ **而 QL10 裁的是「讀即時值，不做快照」。**
📌 ⇒ QL8 不是「把寫死的換成據點」，是**把一個既有的快照改成即時讀取**，
而那會改變既有薪資單重印時的內容。**已回報 A。**

## ⓑ `_build_payment_request_html` 比別人多一行

它的「戶　　名」來自 `company_profile` 的銀行欄位（QL9 要改的那一處）。
⇒ `company_profile` 為空時那一行**不出現** ⇒ 下面的基準是在**空設定**下取的。

## ⓒ 🔴 2026-09-23 裁定翻面：`WL7` 停掉「與改版前逐字相同」這個判準本身

`QL6` 原本的驗收條件是「留空 ⇒ 與改版前逐字相同」，而**改版前的逐字
內容就是我們自己的公司抬頭**（允碩整合集創／60575481／info@miactw.com
……）——`WL7`（`SPEC-WL7.md`）明著裁定這是要停掉的行為：客戶拿到一份
抬頭是別家公司的單據，而他自己什麼都沒填錯。使用者原話對照見
`SPEC-WL7.md`「印空白 => 他會發現，而他會去填」。

```
❌ 舊判準  留空時逐字等於改版前（= 逐字等於我們的公司資料）
✅ 新判準  留空時**沒有任何一句舊的硬編碼身分**，而**版面不塌**
          （`<div class="co-name">` 這類版位仍然在，只是內容是空的）
```
🔑 這是〈守門守的對象被搬走〉的鏡像：守門的斷言與字面值都沒變過，
是它守的那個行為本身被裁定是錯的——不是實作被搬走，是**裁示翻面**。
📌 舊的 `GOLDEN` 快照因此**不再是驗收基準**，改當「這些字串不可以再
出現」的歷史紀錄，見下面 `OLD_HARDCODED_IDENTITY` 的說明。
"""
import json
import sys
from pathlib import Path

import pytest

#: 單獨跑一個檔時 `sys.path` 不含 `tests/` —— pytest 的自動插入發生在
#: 收集那一刻，而 `from ... import` 發生在匯入那一刻。
#: 「整批跑得起來」不等於「單獨跑得起來」，而單獨跑正是除錯時的跑法。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pdf_identity as I  # noqa: E402

#: 🔴 2026-09-22 用**改版前**的 `pdf_gen.py` 取得，當時是 `QL6` 的驗收
#: 基準（「留空 ⇒ 逐字相同」）。**2026-09-23 `WL7` 裁定翻面**：這組值本身
#: 就是被停掉的行為（我們自己的公司抬頭），不再是任何一題的期望值，
#: **也沒有任何測試再讀這份 dict**——純粹留著讓下一個人看得到「以前
#: 長什麼樣子」。真正管「這些字不可以再出現」的是
#: `_pdf_identity.IDENTITY_MARKERS`（下面 `test_ql6_a_blank_profile_
#: prints_no_hardcoded_identity` 用的就是它）。改名避免有人以為這裡
#: 還是基準去抄。
OLD_HARDCODED_IDENTITY = {
    "_build_quote_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_shipping_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_contractor_voucher_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_invoice_voucher_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_payment_request_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_case_closing_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "本文件含案件內部財務與成本資訊，僅供內部留存查核使用，不對外提供 ｜ MOTRIX Synergy Integration Corp. 允碩整合集創",
    ),
    "_build_project_execution_report_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "本文件彙整案件執行過程資訊，僅供內部留存查核使用 ｜ MOTRIX Synergy Integration Corp. 允碩整合集創",
    ),
    "_build_completion_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_payslip_html": (
    ),
}


#: ⚠️ `address` 是必填（§5 的驗證：沒有地址的據點會在地圖上變成
#: 「定位不到的據點」，而那與「使用者真的填錯了」長得一樣）。
#: ☠️ 我第一版沒給地址 ⇒ QL3／QL4 紅在 `422 沒有地址` ——
#: **紅在一個與題目無關的理由上，而那種紅會被讀成「功能還沒做」。**
PRIMARY = {
    "id": "L1", "name": "台中總公司",
    "address": "台中市西屯區台灣大道三段301號",
    "company_name": "", "company_name_en": "", "tax_id": "",
    "phone": "", "email": "",
}

BRANCH = {
    "id": "L2", "name": "台北分公司",
    "address": "台北市信義區市府路1號",
    "company_name": "允碩台北分公司",
    "company_name_en": "MOTRIX Taipei Branch",
    "tax_id": "12345678",
    "phone": "02-1234-5678",
    "email": "taipei@example.invalid",
    "bank_name": "台北富邦銀行",
    "bank_branch": "信義分行",
    "bank_account_name": "允碩台北分公司",
    "bank_account_number": "98765432109876",
}


def _need(name):
    import pdf_gen
    fn = getattr(pdf_gen, name, None)
    assert fn is not None, (
        f"`pdf_gen.py` 缺少 `{name}` —— 見本檔〈我釘的接縫〉"
    )
    return fn


@pytest.fixture
def blank_profile(monkeypatch):
    """`company_profile` 為空 —— 既有安裝什麼都沒填的狀態。

    ## 🔴 2026-09-23：這支 fixture 一度**不再清空任何東西**

    它原本只打 `pdf_gen._get_setting`。B 為了 `BR2b` 把解析搬到
    `helpers/company_identity.py` 之後，**真正被讀的是那一支**：
    ```
    斷言沒變、字面值沒變、fixture 也沒報錯
    ⇒ 而決定行為的已經不是它了 ⇒ 真實 DB 的設定漏了進來
    ```
    ☠️ 症狀是 `QL6[_build_payment_request_html]` 紅在一個看起來像
    「B 改壞了」的地方（多印一行「戶　　名」），
    🔑 **而產品碼是對的，錯的是我的觀測裝置。**
    📌 〈守門守的對象被搬走〉——我今天第二次付這個學費。

    ⇒ 所以現在**兩個模組都打**，而且**打完當場驗它真的空了**。
    """
    import pdf_gen
    import helpers.company_identity as ci

    blank = lambda key, default=None: (       # noqa: E731
        {} if key == "company_profile" else default)
    for mod in (pdf_gen, ci):
        monkeypatch.setattr(mod, "_get_setting", blank, raising=False)

    # 📏 **正對照：先證明它真的清空了，才有資格拿它去比對逐字。**
    # ☠️ 少了這三行，下一次解析再搬一次家，這支 fixture 會
    #    **安靜地什麼都不做**，而 8 題會紅在一個與題目無關的理由上 ——
    # 🔑 而那種紅會被讀成「產品壞了」，正是今天發生的事。
    got = pdf_gen.location_identity(None)
    assert got == ci.DEFAULT_IDENTITY, (
        "`blank_profile` 沒有真的清空 —— `location_identity(None)` 回的是：\n"
        f"  {got}\n"
        f"  預期：{ci.DEFAULT_IDENTITY}\n"
        "☠️ 那代表設定是從我沒打到的地方讀進來的（解析又搬家了），\n"
        "🔑 而接下來每一題的紅綠都與題目無關。")


# ══════════════════════════════════════════════════════════════════════
# QL6 · 既有安裝不會壞的保證（逐字）
# ══════════════════════════════════════════════════════════════════════

#: 🔴 2026-09-23 `QL6` 的比對範圍縮成 8 支 —— **`_build_payslip_html` 退出**。
#:
#: 理由**不是**它難測，是 **`QL6` 的判準對它已經是錯的**：
#: ```
#: QL6   空 payload ⇒ 輸出與改版前**逐字相同**（基準：一行身分都沒有）
#: QL17  空 payload ＝ 沒有快照 ⇒ **用即時值並標明** ← A 的裁定
#: ⇒ 同一格，一題要求它不變，另一題要求它變。**其中一題一定會錯。**
#: ```
#: ⚠️ 而「把基準重取」那條路我**明著不走**：`pdf_gen.py` 現在是 ` M`（B 已改），
#: 此刻取到的基準會是**從被測物複製來的** —— 〈假綠燈〉最標準的形狀，
#: ☠️ 而它永遠是綠的，因為它抄的就是答案。
#: 📌 那一格的保護沒有消失，是**換手**：`QL16`（有快照 ⇒ 用快照）
#:    ＋ `QL17`（沒快照 ⇒ 即時值＋標示）現在負責它，
#:    而那兩題的期望值來自**我送進去的輸入**，不是來自輸出。
QL6_BUILDERS = tuple(b for b in I.BUILDERS if b != "_build_payslip_html")


#: `co-name`／`co-sub` 是**版位**（結構），不是身分（內容）——`WL7` 之後
#: 這兩個 class 仍然要印出來，只是裡面沒有字。判準刻意跟
#: `_pdf_identity.IDENTITY_MARKERS`（值）分開：那一組管「印出來的字裡
#: 有沒有舊身分」，這一組管「版位有沒有被連著 DOM 一起拿掉」。
LAYOUT_SLOT_MARKERS = ('class="co-name"', 'class="co-sub"')


@pytest.mark.parametrize("builder", QL6_BUILDERS)
def test_ql6_a_blank_profile_prints_no_hardcoded_identity(
        builder, blank_profile):
    """🔴🔴 `QL6`（`WL7` 翻面後的新判準①）：留空 ⇒ **不可以印出任何一句
    舊的硬編碼公司身分**。

    ☠️ 這是 `WL7` 要停掉的行為：客戶拿到一份抬頭是別家公司（我們自己）
    的單據，而他自己什麼都沒填錯。`identity_lines()` 掃的是
    `IDENTITY_MARKERS`（允碩整合集創／60575481／...）這幾個**值**，
    不是版位——版位在不在由下面那一題另外驗。
    """
    got = I.identity_lines(I.render(builder))
    assert got == [], (
        f"`{builder}` 留空時仍然印出舊的硬編碼公司身分：\n"
        f"  {got}\n"
        "☠️ `WL7` 裁定：什麼都沒填就印空白，不可以印我們自己的公司"
        "（客戶會拿到一份抬頭是別家公司的單據）。"
    )


@pytest.mark.parametrize("builder", QL6_BUILDERS)
def test_ql6_a_blank_profile_keeps_the_layout_slots(builder, blank_profile):
    """🔴 `QL6`（新判準②）：留空 ⇒ **版面不塌**——`co-name`／`co-sub` 這些
    版位仍然要在，只是內容是空的。

    ☠️ 少了這一題，「乾脆把整段 `<div class="co-name">…</div>` 拿掉」
    也會讓上一題綠（`identity_lines()` 找不到任何一句身分，因為整段
    都不見了）——而那不是「印空白」，是把版面挖掉一塊，CSS 排版可能
    因此跑掉（下面的內容會往上貼）。
    """
    html = I.render(builder)
    for marker in LAYOUT_SLOT_MARKERS:
        assert marker in html, (
            f"`{builder}` 留空時連版位 `{marker}` 都不見了——\n"
            "☠️ 「印空白」指的是內容是空的，不是把整段版位拿掉。"
        )


@pytest.mark.parametrize("builder", QL6_BUILDERS)
def test_ql6_filled_identity_values_actually_appear(builder, identity):
    """⚙️ **正對照：填了值時，那些值真的印得出來。**

    ☠️ 少了這一題，「這支 builder 乾脆不印任何身分（不管有沒有填）」
    這種實作，會讓上面①②兩題全綠——空的就是空的，兩題都通過，而它
    對「填了值」這件事完全沒有反應。這裡直接把 `location_identity()`
    換成回傳固定填好值的替身（沿用本檔既有的 `identity` 接縫），驗證
    值真的被印進 HTML 裡。
    """
    filled = {
        "company_name": "QL6測試填值公司",
        "company_name_en": "QL6 Filled Co.",
        "tax_id": "11122233",
        "phone": "00-0000-0000",
        "email": "ql6filled@example.invalid",
        "bank_name": "", "bank_branch": "",
        "bank_account_name": "", "bank_account_number": "",
    }
    identity[None] = filled
    html = I.render(builder)
    assert "QL6測試填值公司" in html, (
        f"`{builder}` 填了 `company_name` 卻沒有印出來——\n"
        "☠️ 若這裡不紅，代表①②兩題可能是靠『builder 對身分完全沒反應』"
        "通過的，不是真的『留空印空白、填了印填的』。"
    )
    assert "11122233" in html, f"`{builder}` 填了 `tax_id` 卻沒有印出來。"




def test_ql6_the_exclusion_list_has_exactly_one_name_on_it():
    """⚙️ 反向控制：**`QL6` 的排除清單只准有 `_build_payslip_html` 一個名字。**

    ☠️ 少了這一題，`QL6` 有一條非常便宜的變綠路徑：
    **哪一支 builder 紅了就把它加進排除清單。**
    🔑 而那與「它本來就不該被這個判準管」在 diff 上長得一模一樣 ——
    差別只在**有沒有人做過決定**，而那正是這一題要驗的東西。
    📌 〈守門要驗有沒有人做過決定〉：排除是一個決定，它要留下名字。
    """
    excluded = sorted(set(I.BUILDERS) - set(QL6_BUILDERS))
    assert excluded == ["_build_payslip_html"], (
        f"`QL6` 現在排除了這些：{excluded}\n"
        "🔑 只有 `_build_payslip_html` 有理由退出（`QL17` 明著要它變）。\n"
        "☠️ 其他任何一支出現在這裡，都是「紅了就排除」。"
    )
    assert len(QL6_BUILDERS) == 8, (
        f"`QL6` 現在只比對 {len(QL6_BUILDERS)} 支 —— 改版前是 8 支。\n"
        "⚠️ 這個數字變小＝既有安裝的保護範圍變小了。"
    )


# ══════════════════════════════════════════════════════════════════════
# 我釘的接縫，以及它為什麼要連「有沒有呼叫者」一起釘
# ══════════════════════════════════════════════════════════════════════
#
# 我釘一支 `pdf_gen.location_identity(location_id) -> dict`：
#     company_name / company_name_en / tax_id / phone / email
#     bank_name / bank_branch / bank_account_name / bank_account_number
#
# 每一欄留空 ⇒ 沿用主要據點的同一欄（QL5）；
# 主要據點也留空 ⇒ 沿用現在寫死的那組值（QL6）。
#
# 🔴 **而這一次我要連「它真的被呼叫」一起釘，理由是今天付過學費：**
# `reminder_stage()` 也是我釘的接縫，寫得好好的、題目全綠，
# ☠️ **而產品碼零呼叫者** —— 那四題在測一支沒有人跑的函式。
# 🔑 ⇒ 所以 QL7 的做法是**換掉這支函式的回傳值，看 8 支 builder 的輸出有沒有變**。
# 📌 那一題同時回答兩件事：「值有沒有被用」與「誰在用它」，
#    而單獨釘函式本身只回答得了前者。


@pytest.fixture
def identity(monkeypatch):
    """把 `location_identity` 換成可控的替身，回傳一個 `{id: 值}` 的登記簿。"""
    import pdf_gen
    fn = getattr(pdf_gen, "location_identity", None)
    if fn is None:
        pytest.fail(
            "`pdf_gen.py` 缺少 `location_identity(location_id)` —— "
            "見本檔〈我釘的接縫〉。8 支單據的抬頭要從這裡取值。")
    table = {}

    def _fake(location_id=None, **kw):
        return table.get(location_id, table.get(None, {}))

    monkeypatch.setattr(pdf_gen, "location_identity", _fake)
    return table


# ══════════════════════════════════════════════════════════════════════
# QL1 / QL2 · 資料模型
# ══════════════════════════════════════════════════════════════════════

def _columns(table):
    import db
    conn = db.get_db()
    try:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_ql2_the_location_is_a_real_column_not_a_json_key(client):
    """QL2：用真的欄位 `location_id TEXT`，不要塞進 `data_json`。

    理由不是效能，是日後營運報表會想「按據點分組」，而 `data_json` 查不動。
    """
    cols = _columns("quotations")
    assert "location_id" in cols, (
        f"`quotations` 沒有 `location_id` 欄位，現有欄位：{sorted(cols)}")


def test_ql2_the_migration_version_moved(client):
    """QL2：新增欄位要一次 migration，`CURRENT_VERSION` 要往前走。

    釘的是「比 89 大」不是「等於 90」—— 等於 90 的話，
    B 與別的視窗同時各加一個 migration 時這一題會紅在一個假的理由上。
    兩人同時加 migration，git 不會衝突、只會在執行時撞版本號。
    """
    import db
    assert db.CURRENT_VERSION > 89, (
        f"`CURRENT_VERSION` 還是 {db.CURRENT_VERSION} —— 沒有加 migration")


def test_ql1_downstream_documents_do_not_each_store_their_own_location(client):
    """QL1：據點只綁在 `quotations`，下游全部經由 `quote_no` 繼承。

    一個案子只屬於一個據點，而所有單據都是那個案子的產物。
    每張單各存一次的話，會製造「同一個案子的兩張單印不同抬頭」——
    而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。

    判準是「哪些表有 `quote_no`」而不是一份手寫的表名清單：
    手寫清單漏掉的永遠是「後來才加的那一張」。
    """
    import db
    conn = db.get_db()
    try:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()

    offenders = []
    for name in tables:
        cols = _columns(name)
        if name == "quotations" or "quote_no" not in cols:
            continue
        if "location_id" in cols:
            offenders.append(name)
    assert not offenders, (
        "這些下游單據表各自存了一份據點：" + "、".join(offenders)
        + "。據點要綁在 quotations，其餘經由 quote_no 繼承。")


# ══════════════════════════════════════════════════════════════════════
# QL3 / QL4 · 既有資料與新建
# ══════════════════════════════════════════════════════════════════════

def _set_locations(client, token, locations):
    r = client.put("/api/settings/company-profile",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"locations": locations})
    assert r.status_code == 200, r.text


def _superadmin(client, make_user, name):
    username, password = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.231"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_ql3_no_quotation_is_left_without_a_location(client, make_user):
    """QL3：既有報價單全部指向主要據點，**不可以留 NULL**。

    一張沒有據點的報價單，PDF 要嘛壞掉、要嘛安靜地退回某個預設，
    而後者就是這一節正在修的那一族。

    這一題查的是**整張表**而不是「我剛建的那一筆」——
    migration 要照顧的正是「我沒有建的那些」。
    """
    import db
    token = _superadmin(client, make_user, "ql3_admin")
    _set_locations(client, token, [dict(PRIMARY)])

    assert "location_id" in _columns("quotations"), (
        "`quotations` 還沒有 `location_id` 欄位（見 QL2）—— "
        "這一題要等那一步，而它現在紅得對：**既有資料還沒有家可以放。**")

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, data_json) VALUES (?,?,?)",
            ("MQ-202601-900", "草稿", "{}"))
        conn.commit()
        bad = conn.execute(
            "SELECT quote_no FROM quotations "
            "WHERE location_id IS NULL OR TRIM(location_id) = ''").fetchall()
    finally:
        conn.close()
    assert not bad, (
        "這些報價單沒有據點："
        + "、".join(r["quote_no"] for r in bad)
        + "。欄位要 NOT NULL 並有預設，或 migration 要把它們補成主要據點。")


def test_ql4_a_new_quotation_defaults_to_the_primary_location(client, make_user):
    """QL4：新建報價單時據點預設為主要據點，**且可改**。

    兩半都要驗：只驗「有預設」的話，一個寫死主要據點、
    完全不看送進來的值的實作會綠 —— 而分公司就永遠開不出自己的單。
    """
    token = _superadmin(client, make_user, "ql4_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "data": {"customerName": "甲"}})
    assert r.status_code == 201, r.text
    no_default = r.json().get("quoteNo") or r.json().get("quote_no")

    r = client.get(f"/api/quotations/{no_default}", headers=auth)
    assert r.status_code == 200, r.text
    got = r.json().get("locationId") or r.json().get("location_id")
    assert got == PRIMARY["id"], (
        f"沒送據點時應該落在主要據點 {PRIMARY['id']}，實際 {got!r}")

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "locationId": BRANCH["id"],
                          "data": {"customerName": "乙"}})
    assert r.status_code == 201, r.text
    no_branch = r.json().get("quoteNo") or r.json().get("quote_no")
    r = client.get(f"/api/quotations/{no_branch}", headers=auth)
    got = r.json().get("locationId") or r.json().get("location_id")
    assert got == BRANCH["id"], (
        f"送了 {BRANCH['id']} 而存成 {got!r} —— 據點改不動，分公司開不出自己的單")
