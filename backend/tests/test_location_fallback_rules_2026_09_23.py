"""§9 QL20-QL23 · **據點的抬頭沒填時印什麼 —— 使用者剛講的規則。**

---

# 🔑 這一節與 `QL19` 是兩件事，而它們很容易被講成同一件

```
QL19        那五格**從來沒有被存下來**        ⇒ 一個**缺陷**，已修
QL20~QL23   存下來之後**沒填的怎麼辦**        ⇒ 一條**規則**，使用者剛講
```
☠️ 而在 `QL21` 落地之前，**沒填的據點會印什麼是未定義的** ——
📌 **未定義的行為在 PDF 上看起來永遠像一個決定。**

---

# ⭐ 使用者 2026-09-23 的原話（A 轉述，逐字）

> 「假設三個據點，**預設都填寫總公司**，**只有有額外填寫分據點的，才使用分據點**」

🔑 **「額外填寫」這四個字同時定了兩件事**：
```
QL21  沒填 ⇒ 用總公司（不是印空白，也不是擋存檔）
QL22  「額外填的」是**逐欄**判斷 ——
      填了名稱沒填統編 ⇒ 名稱用據點的，統編用總公司的
```

---

# ⚠️ `QL22` 為什麼不能整組退階

據點只填了「公司名稱」而沒填統編：
```
逐欄   名稱用據點的、統編用總公司的        ← 使用者要的
整組   統編缺 ⇒ 整組退回總公司            ← ☠️
```
☠️ 整組退階的話，**使用者填了名稱，卻看到總公司的名稱** ——
🔑 **而他不知道為什麼**：他明明填了，畫面上也存住了，紙上就是沒有。

---

# 📌 `QL23` 的射程：**只套用在有據點綁定選項的單據型別上**

⇒ 沒有那個選項的單據，行為與改版前**完全相同**。
⚙️ 反向控制寫在 `QL6`（既有安裝逐字不變），這裡只驗**綁定這一側**。
"""
import copy

import pytest

#: 五個抬頭欄位 ＋ 四個銀行欄位 —— `location_identity()` 的完整形狀。
IDENTITY_FIELDS = ("company_name", "company_name_en", "tax_id",
                   "phone", "email")
BANK_FIELDS = ("bank_name", "bank_branch",
               "bank_account_name", "bank_account_number")

#: 值故意寫得**在任何真實資料裡都不會出現**。
PRIMARY = {
    "id": "QL2X-HQ", "name": "總公司", "isPrimary": True,
    "address": "台中市西屯區台灣大道三段301號",
    "company_name": "QL2X總公司ZZZ股份有限公司",
    "company_name_en": "QL2X HQ Corp.",
    "tax_id": "10000001", "phone": "04-1000-0001",
    "email": "hq@ql2x.invalid",
    "bank_name": "總行銀行", "bank_branch": "總行分行",
    "bank_account_name": "QL2X總公司戶名", "bank_account_number": "1000000001",
}

#: 「只 key 一個」的那個合法狀態 —— **九欄全空**。
BLANK_BRANCH = {
    "id": "QL2X-BLANK", "name": "什麼都沒填的分據點", "isPrimary": False,
    "address": "台北市信義區市府路1號",
}

#: 「額外填寫」了**一部分**的那個據點 —— `QL22` 的主角。
PARTIAL_BRANCH = {
    "id": "QL2X-PARTIAL", "name": "只填了名稱的分據點", "isPrimary": False,
    "address": "高雄市前金區中正四路211號",
    "company_name": "QL2X分公司ZZZ股份有限公司",
    # ⚠️ `tax_id`／`phone`／`email`／銀行欄位**故意留空**。
}


def _token(client, make_user, username):
    u, p = make_user(username=username, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p},
                    headers={"X-Forwarded-For": "203.0.113.238"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def three_locations(client, make_user):
    """三個據點 —— 一個總公司、一個全空、一個只填了名稱。**走真實端點存。**

    🔑 不用替身：`QL19` 剛證明「那幾欄會在儲存那一層被丟掉」，
    ☠️ 而一個直接塞 dict 的 fixture **看不到那一層**。
    """
    token = _token(client, make_user, "ql2x_admin")
    head = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/settings/company-profile", headers=head)
    assert r.status_code == 200, r.text
    before = copy.deepcopy(r.json())

    body = {"locations": [dict(PRIMARY), dict(BLANK_BRANCH),
                          dict(PARTIAL_BRANCH)]}
    r = client.put("/api/settings/company-profile", json=body, headers=head)
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    yield head
    client.put("/api/settings/company-profile",
               json=before.get("profile", before), headers=head)


def _identity(location_id):
    import pdf_gen
    return pdf_gen.location_identity(location_id)


# ══════════════════════════════════════════════════════════════════════
# QL20 · 每一格都是選填
# ══════════════════════════════════════════════════════════════════════

def test_ql20_a_location_with_no_identity_fields_at_all_can_be_saved(
        client, make_user):
    """⭐ QL20：**九欄全空的據點要存得進去。**

    ☠️ 不可以要求使用者把每一個據點都填滿才能用 ——
    🔑 他明著講了「**有三個地點但只 key 一個**」是合法狀態。
    📌 ⇒ 設定頁不可以把那幾格設成必填，**也不可以在沒填時擋存檔**。
    """
    token = _token(client, make_user, "ql20_admin")
    head = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/settings/company-profile", headers=head)
    before = copy.deepcopy(r.json())
    try:
        r = client.put("/api/settings/company-profile",
                       json={"locations": [dict(PRIMARY),
                                           dict(BLANK_BRANCH)]},
                       headers=head)
        assert r.status_code in (200, 204), (
            f"存一個什麼都沒填的據點被擋下來了：{r.status_code} {r.text[:300]}\n"
            "☠️ 使用者明著講了「有三個地點但只 key 一個」是合法的。\n"
            "🔑 擋存檔＝逼他把每一個據點都填滿，而他不想填。")

        got = client.get("/api/settings/company-profile", headers=head).json()
        locs = got.get("locations") or (got.get("profile") or {}).get(
            "locations") or []
        assert any(l.get("id") == BLANK_BRANCH["id"] for l in locs), (
            f"那個全空的據點沒有存下來：{[l.get('id') for l in locs]}\n"
            "⚠️ 回了 200 而沒有存 —— 那比擋下來更糟，**因為他以為存好了**。")
    finally:
        client.put("/api/settings/company-profile",
                   json=before.get("profile", before), headers=head)


# ══════════════════════════════════════════════════════════════════════
# QL21 · 沒填 ⇒ 用總公司
# ══════════════════════════════════════════════════════════════════════

def test_ql21_a_blank_location_falls_back_to_the_primary(three_locations):
    """🔴🔴 QL21：**那個據點沒填 ⇒ 用總公司的，九欄都是。**

    ⭐ 使用者原話：「**預設都填寫總公司，只有有額外填寫分據點的，
    才使用分據點**」。
    ☠️ 不是印空白 —— 一張抬頭空白的報價單寄給客戶，比印錯更糟。
    """
    got = _identity(BLANK_BRANCH["id"])
    wrong = {f: got.get(f) for f in IDENTITY_FIELDS + BANK_FIELDS
             if got.get(f) != PRIMARY[f]}
    assert not wrong, (
        "什麼都沒填的據點，這幾欄沒有退到總公司：\n"
        + "\n".join(f"  {f}：拿到 {v!r}，預期 {PRIMARY[f]!r}"
                    for f, v in sorted(wrong.items()))
        + "\n☠️ 印空白的話，那張紙上沒有人知道是誰開的。")


def test_ql21_the_primary_itself_is_unchanged(three_locations):
    """⚙️ 反向控制：**總公司自己不受影響。**

    ☠️ 少了這一題，一個「**所有據點都回總公司**」的實作會讓上一題全綠 ——
    🔑 而那正是 `QL22` 要擋的整組退階，**只是從另一個方向進來**。
    """
    got = _identity(PRIMARY["id"])
    for f in IDENTITY_FIELDS:
        assert got.get(f) == PRIMARY[f], (
            f"總公司自己的 `{f}` 變成了 {got.get(f)!r}")


# ══════════════════════════════════════════════════════════════════════
# QL22 · 退階要逐欄，不是整組
# ══════════════════════════════════════════════════════════════════════

def test_ql22_a_partially_filled_location_falls_back_field_by_field(
        three_locations):
    """🔴🔴 QL22：**填了名稱沒填統編 ⇒ 名稱用據點的、統編用總公司的。**

    ☠️ 整組退階的話，**使用者填了名稱卻看到總公司的名稱** ——
    🔑 而他不知道為什麼：他明明填了，設定頁也存住了，**紙上就是沒有**。
    📌 使用者的「**額外填寫**」四個字定的就是這件事：
    **有填的那一欄是額外的，沒填的那一欄不是。**
    """
    got = _identity(PARTIAL_BRANCH["id"])

    assert got.get("company_name") == PARTIAL_BRANCH["company_name"], (
        f"有填的欄位沒有用自己的：`company_name` 拿到 "
        f"{got.get('company_name')!r}\n"
        "☠️ 那是整組退階 —— 使用者填了卻看不到。")

    fell_back = {f: got.get(f) for f in ("tax_id", "phone", "email")
                 if got.get(f) != PRIMARY[f]}
    assert not fell_back, (
        "沒填的欄位沒有退到總公司：\n"
        + "\n".join(f"  {f}：拿到 {v!r}，預期 {PRIMARY[f]!r}"
                    for f, v in sorted(fell_back.items()))
        + "\n☠️ 印一個空統編的報價單，客戶開不了發票。")


def test_ql22_the_bank_fields_fall_back_field_by_field_too(three_locations):
    """🔴 QL22：**銀行欄位同樣逐欄。**

    ☠️ 這一組比抬頭更嚴重：**客戶會照著那串數字匯款。**
    🔑 半組退階（銀行名稱用據點的、帳號用總公司的）會生出一個
    **在真實世界不存在的帳戶** —— 而它印在紙上看起來完全正常。
    📌 ⇒ 這一題釘的是：沒填 ⇒ 四欄**整齊地**都來自總公司。
    """
    got = _identity(PARTIAL_BRANCH["id"])
    wrong = {f: got.get(f) for f in BANK_FIELDS if got.get(f) != PRIMARY[f]}
    assert not wrong, (
        "銀行欄位沒有退到總公司：\n"
        + "\n".join(f"  {f}：拿到 {v!r}，預期 {PRIMARY[f]!r}"
                    for f, v in sorted(wrong.items()))
        + "\n☠️ 客戶會照著那串數字匯款。")


def test_ql22_an_empty_string_counts_as_not_filled(three_locations, client,
                                                   make_user):
    """⚠️ QL22：**存進去的空字串，與「那一欄不存在」要一樣。**

    ☠️ 前端送 `""` 是最常見的「沒填」形狀（輸入框清空後送出），
    🔑 而 `dict.get(f) or fallback` 與 `f in dict` 在這裡會分岔 ——
    📌 〈null 不等於 0〉的同族：**「空字串」與「沒有這個鍵」是兩件事，
       而使用者的意思兩者都是「我沒填」。**
    """
    token = _token(client, make_user, "ql22_empty")
    head = {"Authorization": f"Bearer {token}"}
    explicit = dict(PARTIAL_BRANCH, id="QL2X-EMPTY",
                    tax_id="", phone="", email="", bank_account_number="")
    r = client.put("/api/settings/company-profile",
                   json={"locations": [dict(PRIMARY), explicit]}, headers=head)
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    got = _identity("QL2X-EMPTY")
    assert got.get("tax_id") == PRIMARY["tax_id"], (
        f"明著送了 `tax_id: \"\"`，而它沒有退到總公司：{got.get('tax_id')!r}\n"
        "☠️ 那張單會印一個空統編，而使用者的意思是「我沒填」。")
    assert got.get("bank_account_number") == PRIMARY["bank_account_number"], (
        f"明著送了空帳號，而它沒有退到總公司："
        f"{got.get('bank_account_number')!r}")


# ══════════════════════════════════════════════════════════════════════
# QL23 · 射程：只套用在有綁定選項的單據型別上
# ══════════════════════════════════════════════════════════════════════

def test_ql23_a_document_type_with_no_location_binding_is_untouched(
        three_locations):
    """⚠️ QL23：**沒有據點綁定選項的單據，行為與改版前完全相同。**

    📌 這一整套只套用在**有據點綁定選項**的單據型別上。
    🔑 而 `payslips` 就是那一個 —— 它掛 `contractor_id`，
    **是人事文件不是案件文件**，沒有所屬據點（`QL8`）。
    ⇒ 它走的是 `location_identity(None)` ＝ 主要據點，**不吃退階規則**。

    ⚠️ 逐字不變那一半由 `QL6` 守（`test_quote_location_2026_09_22.py`），
    這裡只驗**它確實落在主要據點**這一格。
    """
    got = _identity(None)
    for f in IDENTITY_FIELDS:
        assert got.get(f) == PRIMARY[f], (
            f"不給據點時 `{f}` 不是主要據點的值：{got.get(f)!r}\n"
            "☠️ 沒有綁定選項的單據型別會跟著變，而 `QL23` 明著排除它們。")


def test_ql23_an_unknown_location_id_does_not_blank_the_document(
        three_locations):
    """🔴 QL23：**給一個不存在的據點 id ⇒ 退到總公司，不是印空白。**

    ☠️ 那會發生：據點被刪掉，而綁著它的舊單據還在。
    🔑 而「印空白」與「印總公司」的差別是 ——
    **一張沒有抬頭的紙不知道是誰開的**，而那是要寄給客戶的。
    📌 〈降級之後它還是會動〉：**壞掉會被報修，降級不會。**
    """
    got = _identity("QL2X-這個據點不存在")
    assert got.get("company_name") == PRIMARY["company_name"], (
        f"不存在的據點 id 讓抬頭變成 {got.get('company_name')!r}\n"
        "☠️ 據點被刪掉之後，綁著它的舊單據會印出一張沒有抬頭的紙。")
