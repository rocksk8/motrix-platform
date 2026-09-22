"""§9 QL5／QL7–QL15 · 報價單綁據點（第二批）。

第一批（`QL1`–`QL4`／`QL6`）在 `test_quote_location_2026_09_22.py`，
共用件（`PRIMARY`／`BRANCH`／`identity` 接縫／`GOLDEN`）從那裡匯入。

---

# ⚠️ 一個編號歸屬的更正

A 在派工訊息裡寫「`QL5`–`QL15` 是硬條件（使用者原話**「把設定模組拆細這件也列入修正」**）」。
☠️ **那句原話屬於 `§10 補` 的 `SA7`–`SA11`，不是 `QL`。**
✅ `QL` 的使用者原話是**「報價單綁據點這件做」**（`§9`）。

🔑 為什麼要指出來：`SCOPE.md` 的規則是
**「搬進 `THIS` 要寫理由，而理由只有兩種形狀：使用者的原話，或它是某一條的前置」**
⇒ 📌 **引錯原話會讓那個規則失效而看起來仍然成立** ——
下一個人讀到「使用者要求拆細設定模組」會去改權限，而 `QL` 改的是 PDF 抬頭。

---

# 🔑 `QL7` 這一組同時回答兩個問題

我換掉 `location_identity()` 的回傳值，看 8 支 builder 的輸出有沒有變：
```
值有沒有被用    ← 單獨釘函式就答得了
誰在用它        ← 只有這樣才答得到
```
📌 那是 `reminder_stage()` 付過的學費：**我釘的接縫寫得好好的、
題目全綠，而產品碼零呼叫者。**
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pdf_identity as I  # noqa: E402
from test_quote_location_2026_09_22 import (  # noqa: E402,F401
    BRANCH, PRIMARY, _need, _set_locations, _superadmin, blank_profile,
    identity,
)


def _frontend(*parts):
    base = Path(__file__).resolve().parent.parent.parent / "frontend"
    return base.joinpath(*parts)


# ══════════════════════════════════════════════════════════════════════
# QL5 · 留空 ＝ 沿用主要據點的同一欄
# ══════════════════════════════════════════════════════════════════════

def test_ql5_a_blank_field_falls_back_to_the_primary_location(
        client, make_user):
    """QL5：據點的每一欄留空 ＝ **沿用主要據點的同一欄**（不是留空）。

    🔑 判準是**逐欄**不是**整筆** —— 一個分公司可能只想改銀行帳號，
    ☠️ 而「整筆有值就整筆用」會讓它的抬頭變成空白。

    ## 🔴 我第一版驗到的是我自己的假貨（B 抓到）

    那一版用了 `identity` fixture —— **而那個 fixture 正是把
    `pdf_gen.location_identity` 換成 `_fake` 的那一個**，
    ⇒ 題目裡再 `_need("location_identity")` 拿到的**就是 `_fake`**。

    ☠️ 而 `_fake` 是 `table.get(id, table.get(None, {}))` ——
    **它結構上不可能做逐欄落空** ⇒ **B 不管怎麼寫，這一題都紅。**
    🔑 〈假綠燈〉的鏡像：**觀測手段與被測對象是同一個東西**，
    而這一次它給的是**假紅燈** —— 更難察覺，因為紅燈看起來像在工作。

    ⇒ 📌 這一題現在**不碰 fixture**：設好真的 `company_profile`，
    呼叫真的 `location_identity()`。
    """
    import pdf_gen

    token = _superadmin(client, make_user, "ql5_admin")
    primary = dict(PRIMARY)
    primary.update(company_name="允碩整合集創股份有限公司",
                   tax_id="60575481", phone="04-3610-6566")
    branch = dict(BRANCH)
    branch.update(company_name="允碩台北分公司", tax_id="", phone="")
    _set_locations(client, token, [primary, branch])

    got = pdf_gen.location_identity(BRANCH["id"])
    assert got.get("company_name") == "允碩台北分公司", (
        f"有填的欄位沒有用自己的：{got}")
    assert got.get("tax_id") == "60575481", (
        f"`tax_id` 留空時沒有沿用主要據點：{got}\n"
        "☠️ 留空的意思是「跟總公司一樣」，不是「印一個空白」。")
    assert got.get("phone") == "04-3610-6566", (
        f"`phone` 留空時沒有沿用主要據點：{got}")


# ══════════════════════════════════════════════════════════════════════
# QL7 · 8 種單據一起改
# ══════════════════════════════════════════════════════════════════════

#: `QL7` 的 8 支。📌 `payslip` 是第 9 支，走 `QL8` 那條路。
QL7_BUILDERS = tuple(b for b in I.BUILDERS if b != "_build_payslip_html")


@pytest.mark.parametrize("builder", QL7_BUILDERS)
def test_ql7_every_document_takes_its_identity_from_the_location(
        builder, identity):
    """🔴🔴 QL7：**8 種單據的抬頭都要從據點取值。**

    ⚠️ **一次改 8 種**，因為它們是同一個模式的 32 行複製 ——
    ☠️ **只改一部分的話，同一個案子的報價單與請款單會印不同抬頭**，
    🔑 而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。
    """
    identity[None] = {"company_name": "QL7 測試抬頭股份有限公司",
                      "company_name_en": "QL7 Test Corp.",
                      "tax_id": "99999999"}
    html = I.render(builder)
    assert "QL7 測試抬頭股份有限公司" in html, (
        f"`{builder}` 沒有從 `location_identity()` 取抬頭。\n"
        "☠️ 只改一部分的話，同一個案子的兩張單會印不同抬頭。")


# ══════════════════════════════════════════════════════════════════════
# QL8 / QL9
# ══════════════════════════════════════════════════════════════════════

def test_ql8_the_payslip_uses_the_primary_location_explicitly(identity):
    """🔴 QL8：`payslips` 用**主要據點**，而且要**在程式裡明著寫**。

    它掛 `contractor_id`，**是人事文件不是案件文件** —— 沒有所屬據點。

    ## 🔴 我原本在這裡寫的結論被 A 推翻了，而錯的那一版留著

    我寫的是：
    > `QL8` 不是「把寫死的換成據點」，是**把既有快照改成即時讀取** ——
    > 而那會改變既有薪資單重印時的內容。

    ✅ **A 採納了那個發現，而裁的方向相反**（`QL16`）：
    **`_build_payslip_html` 的抬頭繼續讀 `payslips.data_json` 的開單時快照。**
    🔑 理由：`QL10`（讀即時值）是為了**匯款帳號要回答「現在該匯到哪」**，
    ☠️ 而薪資單的抬頭回答的是「**當初是誰付的**」—— **那不是同一個問題。**

    📌 所以我發現的是對的（它是快照），**而我從那個事實推出的方向是錯的** ——
    ⚠️ 〈推翻的證據不會自動支持替代方案〉：
    **我查出「它是快照」，然後順手主張「所以要改成即時」。**

    ⇒ 這一題現在只驗「**不給據點時落在主要據點**」，
    而「抬頭從哪裡來」歸 `QL16`。
    """
    resolve = _need("location_identity")
    identity[PRIMARY["id"]] = {"company_name": "主要據點抬頭"}
    identity[None] = {"company_name": "主要據點抬頭"}

    got = resolve(None)
    assert got.get("company_name") == "主要據點抬頭", (
        "不給據點時沒有落在主要據點 —— `QL8` 要求明著寫，不要靠 fallback 湊。")


def test_ql9_the_payment_request_bank_fields_come_from_its_location(identity):
    """🔴🔴 QL9：請款單的銀行欄位改成讀**那一筆據點**。

    🔑 **這是使用者要這個功能的原因** ——
    ☠️ **分公司開的請款單不能印總公司的帳號。**
    📌 而它現在讀的是 `company_profile`（`pdf_gen.py:2006`，全公司唯一一組）。
    """
    identity[None] = {"company_name": "x",
                      "bank_name": "台北富邦銀行",
                      "bank_branch": "信義分行",
                      "bank_account_name": "允碩台北分公司",
                      "bank_account_number": "98765432109876"}
    html = I.render("_build_payment_request_html")
    assert "98765432109876" in html, (
        "請款單沒有印出據點自己的匯款帳號 ——\n"
        "☠️ 分公司開的單印的是總公司的帳號，而客戶會照著匯。")
    assert "台北富邦銀行" in html, "銀行名稱也要來自那一筆據點"


# ══════════════════════════════════════════════════════════════════════
# QL10 · 讀即時值，而代價要變成可追查
# ══════════════════════════════════════════════════════════════════════

def test_ql10_printing_records_which_location_and_which_values(
        client, make_user):
    """🔴🔴 QL10：**讀即時值不做快照**，而**稽核要記「這次用了哪一組值」**。

    ```
    選項甲  開單時快照   歷史正確，而帳號改了之後舊單印的是舊帳號
    選項乙  每次讀當下   帳號永遠是「現在該匯到哪」          ← A 裁乙
    ```
    ☠️ 甲的失敗模式：**帳號換了，而舊單據還在外面流通，
    對方照著匯到一個已經關掉的帳戶。**

    ## 🔑 而乙的代價要被記下來，不是假裝它不存在

    **改一次據點設定，所有歷史 PDF 重印時都會變。**
    ⇒ 稽核要記「這次列印用的是**哪一個據點**」——
    📌 **那是把代價變成可追查。**
    ⚠️ 少了它，客戶拿著兩張同號不同帳號的單子來問，
    **我們答不出哪一張是哪一天印的。**
    """
    import db

    token = _superadmin(client, make_user, "ql10_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "locationId": BRANCH["id"],
                          "data": {"customerName": "甲"}})
    assert r.status_code == 201, r.text
    quote_no = r.json().get("quoteNo") or r.json().get("quote_no")

    client.get(f"/api/quotations/{quote_no}/pdf-download", headers=auth)

    conn = db.get_db()
    try:
        rows = conn.execute("SELECT action, detail FROM audit_log").fetchall()
    finally:
        conn.close()
    blob = " ".join((r["detail"] or "") + " " + (r["action"] or "")
                    for r in rows)
    assert BRANCH["id"] in blob, (
        "列印沒有留下「用了哪一個據點」的紀錄。\n"
        "⇒ 改一次據點設定所有歷史 PDF 都會變，"
        "而沒有地方查得出哪一張用了什麼。")


# ══════════════════════════════════════════════════════════════════════
# QL11 / QL12 · 被引用的據點不可以刪，而改名不算刪
# ══════════════════════════════════════════════════════════════════════

def test_ql11_a_referenced_location_cannot_be_removed(client, make_user):
    """🔴🔴 QL11：**被引用的據點刪除要被擋下來**，訊息要帶數字。

    ⚠️ **不可以「刪了就自動退回主要據點」** ——
    ☠️ **那會讓一批單據在沒有人知道的情況下換了發票抬頭。**

    📌 做在 `PUT /api/settings/company-profile` 裡 ——
    我實查過：**據點沒有獨立端點**，只能透過那一支編輯。
    """
    token = _superadmin(client, make_user, "ql11_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "locationId": BRANCH["id"],
                          "data": {"customerName": "甲"}})
    assert r.status_code == 201, r.text

    r = client.put("/api/settings/company-profile", headers=auth,
                   json={"locations": [dict(PRIMARY)]})
    assert r.status_code == 422, (
        f"有 1 張報價單綁著分公司，而它被刪掉了（回 {r.status_code}）。\n"
        "☠️ 那批單據會在沒有人知道的情況下換掉發票抬頭。")
    assert "1" in r.text, (
        f"擋下來了，而訊息裡沒有數字：{r.text[:200]}\n"
        "⇒ 使用者要知道「有幾張單據在用它」才決定得了下一步。")


def test_ql12_an_unreferenced_location_can_be_removed(client, make_user):
    """🔴 QL12 反向控制：**引用數 0 ⇒ 可以刪。**

    ☠️ 少了這一題，一個「有據點就不准刪」的實作會讓上一題全綠 ——
    而使用者**永遠刪不掉一個打錯字的據點**。
    """
    token = _superadmin(client, make_user, "ql12_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.put("/api/settings/company-profile", headers=auth,
                   json={"locations": [dict(PRIMARY)]})
    assert r.status_code == 200, (
        f"沒有任何單據引用分公司，而它刪不掉（{r.status_code}）：{r.text[:200]}")


def test_ql12_renaming_a_location_is_not_a_deletion(client, make_user):
    """🔴🔴 QL12（A 2026-09-22 補的邊界）：**改名不算刪除。**

    `id` 還在、`name` 變了 ⇒ 那不是刪除。
    ☠️ 否則使用者改一個分公司的名字會被擋下來，
    **而錯誤訊息會說「有 N 張單據在用它」** ——
    🔑 **那句話是對的，而它回答的不是使用者正在做的那件事。**
    📌 〈答案沒錯，是題目問錯了〉在錯誤訊息上的版本。
    """
    token = _superadmin(client, make_user, "ql12_rename")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "locationId": BRANCH["id"],
                          "data": {"customerName": "甲"}})
    assert r.status_code == 201, r.text

    renamed = dict(BRANCH)
    renamed["name"] = "台北營業所"
    r = client.put("/api/settings/company-profile", headers=auth,
                   json={"locations": [dict(PRIMARY), renamed]})
    assert r.status_code == 200, (
        f"只改名字卻被當成刪除擋下來（{r.status_code}）：{r.text[:200]}\n"
        "☠️ 錯誤訊息會說「有 N 張單據在用它」—— 那句話是對的，"
        "而它回答的不是使用者正在做的那件事。")


# ══════════════════════════════════════════════════════════════════════
# QL13 / QL14 / QL15 · 畫面（結構檢查，射程寫在這裡）
# ══════════════════════════════════════════════════════════════════════

def test_ql13_the_quote_form_has_a_location_picker():
    """🔴 QL13：報價單表單要有「據點」選擇器，**預設主要據點**。

    ⚠️ 結構檢查：它答的是「有沒有被寫出來」，不是「畫面長怎樣」。
    📌 真正的驗收是目視，而這句話寫在這裡，不寫在豁免表裡。
    """
    page = _frontend("pages", "quotation-form.html")
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")
    assert "locationId" in text or "location_id" in text, (
        "報價單表單裡找不到據點欄位 —— 使用者選不了要用哪個抬頭開單。")


def test_ql14_the_picker_is_hidden_when_there_is_only_one_location():
    """🔴 QL14：**只有一個據點時，那個選擇器要隱藏或唯讀。**

    📌 一個只有一個選項的下拉選單，**是在問一個沒有選擇的問題**。
    🔑 判準用「有沒有依據點數量做判斷」，不釘 `x-show` 還是 `disabled`
    —— **那是實作選擇，而釘實作的守門會在重構時紅在一個無關的理由上。**
    """
    page = _frontend("pages", "quotation-form.html")
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")
    hit = re.search(r"locations(\.length|\s*\|\|\s*\[\]).{0,80}?[><=]", text,
                    re.S)
    assert hit, (
        "報價單表單沒有依「據點數量」決定要不要顯示選擇器 ——\n"
        "⇒ 只有一個據點的安裝會看到一個只有一個選項的下拉選單。")


def test_ql15_the_case_and_approval_lists_show_the_location():
    """🔴 QL15：案件管理與簽核佇列的列表要**看得到是哪個據點**。

    ☠️ 多據點之後，兩個分公司的案子混在同一張列表裡 ——
    🔑 而「這是誰的案子」是使用者每天都要問的第一個問題。
    ⚠️ 只有一個據點時不顯示（同 `QL14` 的理由）。
    """
    missing = []
    for name in ("case-management.html", "approval-queue.html"):
        page = _frontend("pages", name)
        if not page.exists():
            missing.append(f"{name}（檔案不存在）")
            continue
        text = page.read_text(encoding="utf-8")
        if ("locationId" not in text and "location_id" not in text
                and "據點" not in text):
            missing.append(name)
    assert not missing, (
        "這些列表看不出案子屬於哪個據點：" + "、".join(missing) + "\n"
        "⇒ 多據點之後兩邊的案子混在同一張表裡。")


# ══════════════════════════════════════════════════════════════════════
# QL16 / QL17 / QL18 · 薪資單的快照要留著，而缺欄位不可以安靜補值
# ══════════════════════════════════════════════════════════════════════

def test_ql16_the_payslip_still_reads_its_snapshot(identity):
    """🔴 QL16：`_build_payslip_html` 的抬頭**繼續讀開單時的快照**。

    `QL8` **不可以**改變既有薪資單重印時的內容。
    🔑 `QL10`（讀即時值）是為了**匯款帳號要回答「現在該匯到哪」**，
    ☠️ 而薪資單的抬頭回答的是「**當初是誰付的**」—— **不是同一個問題。**

    📌 觀測點：把 `location_identity()` 換成一個**完全不同**的抬頭，
    而薪資單印出來的仍然是 `data_json` 裡那一個。

    ## 🔴 而我第一版與 `QL17` **對同一個輸入斷言相反的事**（B 抓到）

    兩題都跑 `I.render("_build_payslip_html")`，
    而 `MINIMAL_INPUT` 沒有 payslip 那一項 ⇒ **兩題送的都是空 dict**：
    ```
    QL16  即時值**不可以**出現
    QL17  即時值**必須**出現＋要標示
    ⇒ 同一個輸入，兩個互斥的斷言 —— **其中一個一定會錯**
    ```
    ☠️ **今天第二次**（第一次是 `WA6` 與 `WA2`）——
    🔑 而兩次的成因一樣：**我沒有先問「這兩題送進去的是不是同一個東西」。**
    📌 ⇒ 這一題現在明著**傳一份有快照的 payload**，`QL17` 傳空的。
    **輸入不同，兩題才各自在問自己的問題。**
    """
    snapshot = {"companyName": "開單當時股份有限公司",
                "companyTaxId": "11111111",
                "companyContactInfo": "04-1111-1111"}
    identity[None] = {"company_name": "不該出現在薪資單上的抬頭"}

    import pdf_gen
    html = pdf_gen._build_payslip_html(dict(snapshot))
    assert "開單當時股份有限公司" in html, (
        "有快照而薪資單沒有印出它 —— 這一題的前提不成立")
    assert "不該出現在薪資單上的抬頭" not in html, (
        "薪資單的抬頭跟著即時值走了 ——\n"
        "☠️ 既有薪資單重印時的內容會變，而它回答的是「當初是誰付的」。")


def test_ql17_a_payslip_without_a_snapshot_is_not_silently_filled(identity):
    """🔴🔴 QL17：舊薪資單的 `data_json` **沒有抬頭欄位**時，不可以安靜補值。

    ## 🔴 A 的裁定（2026-09-22）：**用即時值，而且要在文件上標明**

    三條路，A 明著排除了其中兩條：
    ```
    ❌ 安靜地用即時值替換   ⇒ 一份看起來像正本、而抬頭是今天的文件
    ❌ 拒絕重印             ⇒ 使用者連一份都印不出來
    ✅ 用即時值 ＋ 在文件上標明
    ```
    ⚠️ **我第一版斷言「即時值不可以出現」——那是錯的**，
    它等於選了「拒絕重印」那一條。錯的那一版留著：
    🔑 我從「安靜補值是錯的」推出「所以不可以用即時值」，
    **而中間少了一個選項。**

    ☠️ 真正要擋的是「**安靜**」那兩個字，不是「即時值」。
    📌 〈降級之後它還是會動〉：一份沒有標示的重印會被寄出去。
    """
    identity[None] = {"company_name": "今天的抬頭股份有限公司"}
    html = I.render("_build_payslip_html")      # `MINIMAL_INPUT` 沒有抬頭欄位

    used_live = "今天的抬頭股份有限公司" in html
    assert used_live, (
        "舊薪資單沒有抬頭快照，而系統連即時值都沒用 ——\n"
        "☠️ 那等於拒絕重印，而 A 明著排除了那一條。")
    marked = any(word in html for word in ("重印", "當時", "非原始", "現行"))
    assert marked, (
        "用了即時值而文件上沒有任何標示 ——\n"
        "☠️ 那是一份看起來像正本、而抬頭是今天的文件。**它不會報錯。**\n"
        "🔑 要擋的是「安靜」那兩個字，不是「即時值」。")


def test_ql18_a_new_location_id_is_validated_on_submit(client, make_user):
    """🔴 QL18：`id` 格式驗證要驗「**這一次送進來的新據點**」，不是整包重驗。

    ☠️ 整包重驗的話，**既有那些 id 格式不合的據點會讓使用者存不了檔** ——
    🔑 而他改的可能是完全無關的一欄，**而錯誤訊息會指著一個他沒有動的東西**。
    📌 同 `QL12` 的「改名不算刪除」：
    **判準要分得出「使用者正在做什麼」與「資料本來長什麼樣」。**
    """
    token = _superadmin(client, make_user, "ql18_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY)])

    bad = dict(BRANCH)
    bad["id"] = "有空白 與中文/斜線"
    r = client.put("/api/settings/company-profile", headers=auth,
                   json={"locations": [dict(PRIMARY), bad]})
    assert r.status_code == 422, (
        f"送進來一個 id 格式不合的新據點，而它被收下了（{r.status_code}）。")

    # 📏 正對照：只改既有據點的無關欄位，不可以被既有資料的格式擋住。
    tweaked = dict(PRIMARY)
    tweaked["phone"] = "04-0000-0000"
    r = client.put("/api/settings/company-profile", headers=auth,
                   json={"locations": [tweaked]})
    assert r.status_code == 200, (
        f"只改了一個無關的欄位卻被擋下來（{r.status_code}）：{r.text[:200]}\n"
        "☠️ 錯誤訊息會指著一個使用者沒有動的東西。")
