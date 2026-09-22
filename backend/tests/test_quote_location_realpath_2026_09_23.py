"""§9 QL7（重寫）· **走真實路徑：綁了據點的單據要印那個據點的抬頭。**

---

# ☠️ 舊版 `QL7` 八題全綠，而功能是零效果的（B 自己抓到）

```
generate_pdf_bytes() 只 SELECT data_json, status, deal_tag
而 location_id 是**欄位**，不是 data_json 的鍵
⇒ 8 支 builder 拿到的 payload 永遠沒有 locationId
⇒ **每一份真實單據都印總公司抬頭，而那八題全綠**
```
🔑 **為什麼全綠：測試自己塞了 `locationId` 進 payload。**

📌 那與 `reminder_stage()` 那次一模一樣：接縫寫得好好的、題目全綠，
☠️ **而產品碼零呼叫者** —— 只是這一次呼叫者有，**傳進去的值是測試自己給的**。

---

# 🔑 A-2 提煉的判準，這一檔整個是照它寫的

> **測試裡「我自己準備的」那一部分，就是生產路徑上「沒有被驗到」的那一段。**

⇒ 寫完一題要問：**「這個值在真實路徑上是誰給的？那個人有被測到嗎？」**

```
樣本**加工錯了**                       ⇒ 驗錯東西    **會紅**
樣本正確，而**繞過了生產路徑上的一段**  ⇒ 功能零效果  **會綠**
```
☠️ **後者更難發現，因為它會綠。**

---

# 📌 所以這一檔的規矩：**我一個 `locationId` 都不塞**

```
我準備的   quotations 那一列（location_id 是**欄位**，照真實寫法寫進去）
生產路徑   generate_*_pdf_bytes() 自己去讀那個欄位、自己組 payload
我觀測的   那一支 builder 真的收到什麼、真的印出什麼
```

⚠️ **怎麼在不跑 Edge 的情況下拿到 HTML**：
把 `_build_*_html` 換成一個**先呼叫真正的那一支拿到 HTML、再丟出哨兵**的替身。
🔑 **HTML 是真的**（真正的 builder 產的），**payload 也是真的**
（生產路徑自己組的），只有「之後那一步 Edge」被攔下來。
☠️ 攔不住的：Edge 真的能把那份 HTML 印成 PDF。那不是這一題的問題。

⚠️ **不釘 `_location_of()` 這個函式名**（A 的指示）——
B 修在那一個地方而不是 14 個呼叫點，理由是「逐點注入的話下一個新增的
單據型別會漏，而漏掉的症狀是它印總公司抬頭，沒有人會報修」。
⇒ 釘的是不變量：**任何一支 builder，綁了據點就印那個據點。**
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 兩個據點的抬頭 —— 值故意寫得**在任何真實資料裡都不會出現**，
#: 🔑 這樣「有印出來」就不可能是巧合命中既有資料。
HQ = {
    "id": "LOC-HQ", "name": "總公司", "isPrimary": True,
    "address": "台中市西屯區台灣大道三段301號",
    "company_name": "QL7總公司抬頭XYZ股份有限公司",
    "company_name_en": "QL7 HQ Corp.",
    "tax_id": "11111111", "phone": "04-1111-1111",
    "email": "hq@ql7.invalid",
    "bank_name": "總行銀行", "bank_branch": "總行分行",
    "bank_account_name": "QL7總公司戶名", "bank_account_number": "1111111111",
}
BRANCH = {
    "id": "LOC-BR", "name": "台北分公司", "isPrimary": False,
    "address": "台北市信義區市府路1號",
    "company_name": "QL7分公司抬頭XYZ股份有限公司",
    "company_name_en": "QL7 Branch Corp.",
    "tax_id": "22222222", "phone": "02-2222-2222",
    "email": "br@ql7.invalid",
    "bank_name": "分行銀行", "bank_branch": "分行分行",
    "bank_account_name": "QL7分公司戶名", "bank_account_number": "2222222222",
}
THIRD = dict(BRANCH, id="LOC-3RD", name="高雄分公司",
             company_name="QL7第三據點抬頭XYZ股份有限公司",
             tax_id="33333333", bank_account_number="3333333333")


class _StopBeforeEdge(Exception):
    """攔在 Edge 之前 —— HTML 已經產好了，我們不需要那個 PDF。"""


@pytest.fixture
def locations(client):
    """把三個據點寫進 `company_profile`，**走設定的真實儲存路徑**。

    ⚠️ 不直接寫 dict 進 `_get_setting` 的替身 ——
    🔑 `_clean_locations()` 那一層（B 2026-09-23 才發現它根本沒存那五欄）
    **正是「我自己準備的那一段」會蓋掉的東西**。
    """
    from helpers.settings import _get_setting, _set_setting
    before = _get_setting("company_profile", {}) or {}
    _set_setting("company_profile",
                 {**before, "locations": [HQ, BRANCH, THIRD]})
    yield
    _set_setting("company_profile", before)


def _seed_quote(quote_no, location_id):
    """一張真實的報價單，`location_id` 寫進**欄位**。

    ⚠️ `data_json` 裡**故意不放 `locationId`** —— 那正是舊版八題
    自己塞進去的那個鍵。**生產路徑必須自己去讀欄位。**
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (quote_no,))
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, data_json, created_at, updated_at, "
            "deal_tag, sales_person, assigned_user_ids, location_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "QL7 客戶", "QL7 專案", 1000, 952,
             json.dumps({"quoteNo": quote_no, "customerName": "QL7 客戶",
                         "items": [], "tot": {}}, ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00",
             "", "", "[]", location_id),
        )
        conn.commit()
    finally:
        conn.close()
    return quote_no


def _set_location(quote_no, location_id):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET location_id=? WHERE quote_no=?",
                     (location_id, quote_no))
        conn.commit()
    finally:
        conn.close()


def _html_from_production(builder, entry, *args, **kwargs):
    """跑真實入口，回傳**真正的 builder 產出的 HTML** 與它收到的 payload。

    📏 這支函式本身要能分辨「builder 沒被呼叫」——
    ☠️ 沒被呼叫時 `entry()` 會一路跑到 Edge，那在測試機上會很慢或失敗，
    🔑 而我們要的是一個**指名的**錯誤訊息，不是一個逾時。

    ## ⚠️ 用**自己的** monkeypatch context，不吃呼叫端那一個

    第一版收 `monkeypatch` 進來，於是同一題呼叫兩次時：
    ```
    第一次   real = 真正的 builder      ✅
    第二次   real = **上一次的替身**     ⇒ 一進去就丟哨兵，html 永遠取不到
    ```
    ☠️ **探針疊在自己身上**，而症狀是「builder 沒被呼叫」——
    🔑 那個訊息指向產品，**而錯的是觀測裝置**。今天第三次同一個方向。
    📌 ⇒ 每一次呼叫開一個獨立 context，用完立刻還原。
    """
    import pdf_gen
    seen = {}

    with pytest.MonkeyPatch.context() as mp:
        real = getattr(pdf_gen, builder)

        def spy(*a, **k):
            seen["payload"] = a[0] if a else None
            seen["html"] = real(*a, **k)
            raise _StopBeforeEdge()

        mp.setattr(pdf_gen, builder, spy)
        with pytest.raises(_StopBeforeEdge):
            entry(*args, **kwargs)

    assert "html" in seen, (
        f"`{builder}` 沒有被呼叫 —— 那支入口改走別的 builder 了？")
    return seen["html"], seen["payload"]


# ══════════════════════════════════════════════════════════════════════
# QL7 · 綁了據點就印那個據點（報價單，真實路徑）
# ══════════════════════════════════════════════════════════════════════

def test_ql7_a_quotation_bound_to_a_branch_prints_the_branch(
        client, locations, monkeypatch):
    """🔴🔴 QL7：**綁分公司的報價單，印分公司的抬頭。**

    ⚠️ **我沒有在 payload 裡塞 `locationId`** —— 它只存在於
    `quotations.location_id` **欄位**，而生產路徑要自己去讀。
    ☠️ 舊版八題就是塞了那個鍵才全綠，**而每一份真實單據都印總公司抬頭**。
    """
    import pdf_gen
    quote_no = _seed_quote("QL7-BR-001", BRANCH["id"])

    html, payload = _html_from_production(
        "_build_quote_html", pdf_gen.generate_pdf_bytes, quote_no)

    assert BRANCH["company_name"] in html, (
        f"綁了 `{BRANCH['id']}` 的報價單印的不是分公司抬頭。\n"
        f"  生產路徑組出來的 payload 的 locationId："
        f"{(payload or {}).get('locationId')!r}\n"
        "☠️ 客戶手上那張紙印的是總公司，而沒有任何地方會報錯。")
    assert HQ["company_name"] not in html, (
        "分公司的報價單上同時出現了總公司抬頭 —— 那比印錯更糟。")


def test_ql7_a_quotation_with_no_location_prints_the_primary(
        client, locations, monkeypatch):
    """⚙️ 反向控制①：**沒綁據點 ⇒ 印主要據點。**

    ☠️ 少了這一題，一個「**永遠印第一個／永遠印分公司**」的實作會讓
    上一題全綠 —— 🔑 而**既有安裝的每一張單都會變成分公司抬頭**。
    """
    import pdf_gen
    quote_no = _seed_quote("QL7-NONE-001", "")

    html, payload = _html_from_production(
        "_build_quote_html", pdf_gen.generate_pdf_bytes, quote_no)

    assert HQ["company_name"] in html, (
        f"沒綁據點的報價單沒有印主要據點的抬頭。\n"
        f"  payload 的 locationId：{(payload or {}).get('locationId')!r}")
    assert BRANCH["company_name"] not in html, (
        "沒綁據點，而印出了分公司抬頭 ——\n"
        "☠️ 那代表實作是「拿清單裡的某一個」而不是「拿主要據點」。")


def test_ql7_rebinding_the_quotation_moves_the_identity(
        client, locations, monkeypatch):
    """⚙️ 反向控制②：**改綁另一個據點 ⇒ 抬頭要跟著變。**

    ☠️ 少了這一題，一個「**只讀一次然後快取**」的實作會讓上面兩題全綠 ——
    🔑 而使用者把案子轉給另一個據點之後，單據還是印舊的。
    📌 而那種錯**只在轉單之後才出現**，第一次開單時完全正常。
    """
    import pdf_gen
    quote_no = _seed_quote("QL7-MOVE-001", BRANCH["id"])

    first, _ = _html_from_production(
        "_build_quote_html", pdf_gen.generate_pdf_bytes, quote_no)
    assert BRANCH["company_name"] in first, "前提不成立：一開始就沒印分公司"

    _set_location(quote_no, THIRD["id"])
    second, payload = _html_from_production(
        "_build_quote_html", pdf_gen.generate_pdf_bytes, quote_no)

    assert THIRD["company_name"] in second, (
        f"改綁 `{THIRD['id']}` 之後抬頭沒有跟著變。\n"
        f"  payload 的 locationId：{(payload or {}).get('locationId')!r}\n"
        "☠️ 案子轉給另一個據點之後，單據還是印舊的那個。")
    assert BRANCH["company_name"] not in second, (
        "改綁之後仍然印得出舊據點的抬頭 —— 那一層有快取沒有失效。")


# ══════════════════════════════════════════════════════════════════════
# QL7 · 下游單據經由 quote_no 繼承（QL1 的設計，走真實路徑驗它）
# ══════════════════════════════════════════════════════════════════════

def test_ql7_a_downstream_document_inherits_through_the_quote_no(
        client, locations, monkeypatch):
    """🔴 QL7：**出貨單沒有自己的據點欄位，它要經由 `quote_no` 繼承。**

    📌 `QL1` 的設計：據點只綁 `quotations`，**每張單各存一次的話，
    同一個案子的兩張單會印不同抬頭**，而那種不一致沒有地方會報錯。

    ⚠️ **我掃過一次而差點報錯一個缺陷**：八支入口有七支是
    `SELECT * FROM <自己的表>`、本文裡沒有 `location_id` ——
    ☠️ 我差一步就報「八支只修了一支」。
    🔑 打開 `_location_of()` 才看到**第二條分支**（`quoteNo` → 查 `quotations`）。
    📌 〈缺欄位≠缺訊號〉：**文字比對答的是「有沒有被提到」，
       不是「有沒有被呼叫」** —— 而這一題正是去問後者。
    """
    import db
    import pdf_gen

    quote_no = _seed_quote("QL7-SHIP-001", BRANCH["id"])
    note_no = "QL7-SN-001"
    conn = db.get_db()
    try:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(shipping_notes)")}
        assert "location_id" not in cols, (
            "`shipping_notes` 有自己的 `location_id` 欄位 ——\n"
            "☠️ `QL1` 明著不要那樣：同一個案子的兩張單會印不同抬頭。")
        conn.execute("DELETE FROM shipping_notes WHERE note_no=?", (note_no,))
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, customer_name, "
            "data_json, created_at) VALUES (?,?,?,?,?)",
            (note_no, quote_no, "QL7 客戶",
             json.dumps({"noteNo": note_no, "quoteNo": quote_no, "items": []},
                        ensure_ascii=False),
             "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    html, payload = _html_from_production(
        "_build_shipping_html",
        pdf_gen.generate_shipping_pdf_bytes, note_no)

    assert BRANCH["company_name"] in html, (
        f"出貨單沒有繼承到報價單的據點。\n"
        f"  payload 的 quoteNo：{(payload or {}).get('quoteNo')!r}\n"
        f"  payload 的 locationId：{(payload or {}).get('locationId')!r}\n"
        "☠️ 同一個案子的報價單印分公司、出貨單印總公司 ——\n"
        "🔑 而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。")


# ══════════════════════════════════════════════════════════════════════
# 📏 量尺：這一檔真的走得到產品那一段嗎
# ══════════════════════════════════════════════════════════════════════

def test_ql7_the_probe_goes_red_when_the_column_is_ignored(
        client, locations, monkeypatch):
    """📏 量尺：**把「讀欄位」那一段拿掉，上面那幾題要紅。**

    ☠️ 少了這一題，`_html_from_production()` 哪天壞掉（攔錯 builder、
    payload 取錯）會讓整檔**一起安靜地綠** ——
    🔑 而這一檔存在的唯一理由就是「舊版八題綠著而功能零效果」。

    ⚠️ **不改 B 的檔**：把 `pdf_gen.location_identity` 暫時換成
    「不管給什麼 id 都回主要據點」，等同於欄位沒被讀到的行為。
    """
    import pdf_gen
    quote_no = _seed_quote("QL7-YARD-001", BRANCH["id"])

    import helpers.company_identity as ci
    monkeypatch.setattr(pdf_gen, "location_identity",
                        lambda *a, **k: ci.location_identity(None))

    html, _ = _html_from_production(
        "_build_quote_html", pdf_gen.generate_pdf_bytes, quote_no)

    assert BRANCH["company_name"] not in html, (
        "把解析換成「永遠回主要據點」之後，分公司抬頭**仍然**印出來了 ——\n"
        "☠️ 那代表上面那幾題量到的不是那一段，\n"
        "🔑 而它們的綠證明不了任何事。")
    assert HQ["company_name"] in html, (
        "量尺本身沒有生效（連主要據點的抬頭都沒印出來）——\n"
        "⇒ 這一題的前提不成立，**不可以當成通過**。")


# ══════════════════════════════════════════════════════════════════════
# QL7（接縫層）· 8 支 builder 都去取值 —— **而它回答不了「有沒有接上」**
# ══════════════════════════════════════════════════════════════════════
#
# 🔴 這八題原本住在 `test_quote_location_rest_2026_09_22.py`，
#    **八題全綠而功能是零效果的**（A 2026-09-23 指名）：
#    測試自己塞 `locationId` 進 payload ⇒ 生產路徑有沒有給那個值，
#    從來沒有被問過。
#
# 🔑 它們**沒有被刪**，理由是它們仍然回答一個真的問題：
#    **「八支 builder 都去取值了嗎」** —— 那是上面那幾題沒有覆蓋的廣度
#    （上面只走得到報價單與出貨單兩條真實路徑）。
#
# ⚠️ **而它們回答不了「有沒有接上」** —— 那是上面那幾題的工作。
# 📌 ⇒ 搬過來與真實路徑的題放在同一個檔裡，**讓讀的人一眼看到
#    這一層的射程到哪裡為止**。分在兩個檔時，
#    「八題全綠」這句話會被單獨引用。

import _pdf_identity as I  # noqa: E402

#: `QL7` 接縫層的 8 支。📌 `payslip` 是第 9 支，走 `QL8` 那條路。
QL7_BUILDERS = tuple(b for b in I.BUILDERS if b != "_build_payslip_html")


@pytest.fixture
def identity(monkeypatch):
    """把 `location_identity` 換成可控的替身，回傳 `{id: 值}` 登記簿。

    ⚠️ **這是接縫層專用的** —— 用它的題**驗不到生產路徑**。
    ☠️ `QL5` 就是誤用了它（拿它去驗逐欄 fallback），
    而那個替身結構上做不出逐欄 fallback ⇒ **假紅燈**。
    """
    import pdf_gen
    fn = getattr(pdf_gen, "location_identity", None)
    assert fn is not None, (
        "`pdf_gen.py` 缺少 `location_identity(location_id)`")
    table = {}
    monkeypatch.setattr(pdf_gen, "location_identity",
                        lambda location_id=None, **kw:
                        table.get(location_id, table.get(None, {})))
    return table


@pytest.mark.parametrize("builder", QL7_BUILDERS)
def test_ql7_every_document_takes_its_identity_from_the_location(
        builder, identity):
    """QL7（接縫層）：**8 種單據的抬頭都要從據點取值。**

    ⚠️ **一次改 8 種**，因為它們是同一個模式的 32 行複製 ——
    ☠️ **只改一部分的話，同一個案子的報價單與請款單會印不同抬頭**，
    🔑 而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。

    ⚠️ **這一題的射程**：它證明「builder 會去用那個值」，
    ☠️ **它不證明生產路徑有把值傳進來** —— 那是本檔上半部的工作，
    🔑 而它們分開之後，這一題的綠曾經被當成整個功能的綠。
    """
    identity[None] = {"company_name": "QL7 測試抬頭股份有限公司",
                      "company_name_en": "QL7 Test Corp.",
                      "tax_id": "99999999"}
    html = I.render(builder)
    assert "QL7 測試抬頭股份有限公司" in html, (
        f"`{builder}` 沒有從 `location_identity()` 取抬頭。\n"
        "☠️ 只改一部分的話，同一個案子的兩張單會印不同抬頭。")
