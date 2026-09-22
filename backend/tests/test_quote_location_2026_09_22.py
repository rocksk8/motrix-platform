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

## ⓒ 基準（`GOLDEN`）是 2026-09-22 用**還沒改過的** `pdf_gen.py` 跑出來的

🔑 `QL6` 的驗收條件是**逐字相同**，而「改版前」這個基準
**只有在 B 動手之前取得才算數**。
⚠️ 〈把今天的實作釘成不變量〉我踩過五次 —— 這一次它是對的，
理由很窄：**規格明著把「與改版前逐字相同」寫成驗收條件。**
📌 而釘的範圍**剛好是身分那幾行**，不是整份文件（日期、金額本來就該變）。
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

#: 🔴 2026-09-22 的基準 —— **B 改 `pdf_gen.py` 之前**跑出來的身分行。
#: 📌 在 `company_profile` 為空（既有安裝什麼都沒填）的條件下取得。
GOLDEN = {
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


PRIMARY = {
    "id": "L1", "name": "台中總公司",
    "company_name": "", "company_name_en": "", "tax_id": "",
    "phone": "", "email": "",
}

BRANCH = {
    "id": "L2", "name": "台北分公司",
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
    """`company_profile` 為空 —— 既有安裝什麼都沒填的狀態。"""
    import pdf_gen
    monkeypatch.setattr(
        pdf_gen, "_get_setting",
        lambda key, default=None: {} if key == "company_profile" else default,
        raising=False)


# ══════════════════════════════════════════════════════════════════════
# QL6 · 既有安裝不會壞的保證（逐字）
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("builder", I.BUILDERS)
def test_ql6_a_blank_profile_prints_exactly_what_it_prints_today(
        builder, blank_profile):
    """QL6：所有據點的抬頭欄位留空 ⇒ **與改版前逐字相同**。

    這是「既有安裝不會壞」的保證：使用者什麼都不填，PDF 跟今天一模一樣。
    沒有它，B 一改那 32 行，所有既有使用者的單據都可能變樣而沒有人發現。

    基準是 2026-09-22 用還沒改過的 `pdf_gen.py` 跑出來的（見檔頭 ⓒ）。
    比對前把連續半形空白壓成一個 —— 排版改動不該讓這一題紅，
    而全形空白不壓（它是那行內容的一部分）。
    """
    got = I.normalise(I.identity_lines(I.render(builder)))
    want = list(GOLDEN[builder])
    assert got == want, (
        f"`{builder}` 印出來的公司身分跟改版前不一樣：\n"
        f"  現在：{got}\n"
        f"  改版前：{want}\n"
        "既有安裝什麼都沒填時，PDF 必須逐字不變。"
    )


def test_ql6_the_baseline_is_not_empty():
    """量尺：基準本身要有東西，否則上面那 9 題是在比對兩個空清單。

    `_build_payslip_html` 是唯一合法的空的一支 —— 它一行公司身分都沒有寫死
    （抬頭來自呼叫端傳進來的 dict，見檔頭 ⓐ）。
    """
    empty = [k for k, v in GOLDEN.items() if not v]
    assert empty == ["_build_payslip_html"], (
        f"基準裡有非預期的空項目：{empty}\n"
        "一個比對兩個空清單的斷言，永遠是綠的。"
    )
    assert sum(len(v) for v in GOLDEN.values()) >= 30, (
        f"基準只有 {sum(len(v) for v in GOLDEN.values())} 行 —— 抓取八成失效了"
    )
