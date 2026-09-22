"""§9 QL19 · **據點的抬頭欄位存得進去，也讀得回來。**

---

# ☠️ 缺陷的形狀（B 2026-09-23 自己回頭掃才抓到）

```
_clean_locations()    只留 id／name／address／座標 ＋ 四個銀行欄位
location_identity()   讀的是 company_name／company_name_en／tax_id／phone／email
⇒ 那五個欄位在 PUT 就被丟掉了 —— **從來沒有進過資料庫**
```

🔴 **而那四格在畫面上是可以填的。**
使用者填了、按儲存、**重新整理就不見了**，而**零錯誤訊息**：
```
前端送了   ✅
後端收了   ✅
後端沒存   ← 而這一步沒有任何人會報錯
```
☠️ 他會以為是自己忘了按儲存，**再填一次，最後怪自己，不會報修。**

⚠️ **修正只讓「以後填的會存」，救不回已經填過的** —— 那些值從來沒進過
資料庫。已寫進交付說明的「部署後要做的事」，叫使用者逐一去重填。

---

# 🔑 為什麼所有既有的 `QL` 題都抓不到它

> **測試裡「我自己準備的」那一部分，就是生產路徑上「沒有被驗到」的那一段。**
> ——A-2，2026-09-23

`QL5` 的題自己塞 `identity[BRANCH["id"]] = {...}`
⇒ **「那些欄位有沒有被存下來」從來沒有被任何一題碰到。**

📌 ⇒ 這一檔**只走真實端點**：`PUT` 進去、`GET` 回來，比對值。

---

# ⚠️ 判準：**不是「欄位存在」，是「值相同」**

☠️ 白名單可以留著欄位而清掉內容（`{"company_name": ""}` 照樣是「存在」）——
🔑 而畫面上「填了一個空白」與「沒填」長得一模一樣。
"""
import copy

import pytest

#: B 加的那組。📌 **五個**，不是 A 訊息裡寫的四個 ——
#: `company_name_en` 也在裡面（`pdf_gen` 的 `co-sub` 那一行讀它）。
IDENTITY_FIELDS = ("company_name", "company_name_en", "tax_id",
                   "phone", "email")

#: 值故意寫得**在任何真實資料裡都不會出現**，
#: 🔑 這樣「讀得回來」就不可能是巧合命中既有設定。
SENT = {
    "id": "QL19-LOC", "name": "QL19 測試據點",
    "address": "台北市信義區市府路1號",
    "company_name": "QL19抬頭ZZZ股份有限公司",
    "company_name_en": "QL19 Roundtrip Corp.",
    "tax_id": "87654321",
    "phone": "02-8765-4321",
    "email": "ql19@roundtrip.invalid",
}


def _token(client, make_user, username):
    """超級管理員 —— 抬頭欄位只有他改得動（使用者原話）。"""
    u, p = make_user(username=username, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p},
                    headers={"X-Forwarded-For": "203.0.113.240"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def profile(client, make_user):
    """`PUT`／`GET` 的小包裝，用完把原本的設定放回去。"""
    token = _token(client, make_user, "ql19_admin")
    head = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/settings/company-profile", headers=head)
    assert r.status_code == 200, r.text
    before = copy.deepcopy(r.json())

    class _P:
        def put(self, body):
            return client.put("/api/settings/company-profile",
                              json=body, headers=head)

        def get(self):
            r = client.get("/api/settings/company-profile", headers=head)
            assert r.status_code == 200, r.text
            return r.json()

        def locations(self):
            body = self.get()
            return (body.get("locations")
                    or (body.get("profile") or {}).get("locations") or [])

    yield _P()

    payload = before.get("profile", before)
    client.put("/api/settings/company-profile", json=payload, headers=head)


def _sent_back(locs):
    got = [l for l in locs if l.get("id") == SENT["id"]]
    assert got, (
        f"存進去的據點 `{SENT['id']}` 讀不回來了，現有："
        f"{[l.get('id') for l in locs]}\n"
        "⇒ 這一題的前提不成立（整個據點都沒存進去，不只是那幾欄）。")
    return got[0]


# ══════════════════════════════════════════════════════════════════════
# QL19 · 存取往返
# ══════════════════════════════════════════════════════════════════════

def test_ql19_the_identity_fields_survive_a_save_and_reload(profile):
    """🔴🔴 QL19：**五個抬頭欄位 `PUT` 進去要 `GET` 得回來，而且值相同。**

    ☠️ 它們先前**收了但沒有存** ⇒ 使用者填了、按儲存、重新整理就不見了，
    🔑 而**零錯誤訊息**：前端送了、後端收了、後端沒存。
    📌 他會以為是自己忘了按儲存，再填一次，**最後怪自己，不會報修。**

    ⚠️ 判準是**值相同**不是「欄位存在」——
    白名單可以留著欄位而清掉內容，而畫面上「填了空白」與「沒填」一樣。
    """
    r = profile.put({"locations": [dict(SENT)]})
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    got = _sent_back(profile.locations())
    lost = {f: (SENT[f], got.get(f)) for f in IDENTITY_FIELDS
            if got.get(f) != SENT[f]}
    assert not lost, (
        "這些抬頭欄位沒有原樣存下來：\n"
        + "\n".join(f"  {f}：送了 {s!r}，讀回 {g!r}"
                    for f, (s, g) in sorted(lost.items()))
        + "\n☠️ 使用者填了、按儲存、重新整理就不見了，而沒有任何錯誤訊息。\n"
          "🔑 `_clean_locations()` 的白名單要包含它們 —— "
          "而且要存**值**，不是只留一個空欄位。")


def test_ql19_the_saved_identity_actually_reaches_the_documents(
        client, make_user, profile):
    """🔴 QL19：**存下來之後，單據真的印得出它。**

    ☠️ 少了這一題，「存得進資料庫」與「印得到紙上」之間還有一段沒人驗 ——
    🔑 而那正是這一整節的成因：**每一段各自都對，而中間有一段沒有接上。**
    📌 〈兩個都對而路不存在〉：牴觸讀得出來，**路徑不存在讀不出來**。
    """
    r = profile.put({"locations": [dict(SENT, isPrimary=True)]})
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    import pdf_gen
    ident = pdf_gen.location_identity(SENT["id"])
    for field in IDENTITY_FIELDS:
        assert ident.get(field) == SENT[field], (
            f"存下來了，而 `location_identity()` 讀到的 `{field}` 是 "
            f"{ident.get(field)!r}，不是 {SENT[field]!r}\n"
            "☠️ 設定頁存檔成功，而分公司的單據還是印總公司抬頭 ——\n"
            "🔑 **沒有任何錯誤訊息，因為沒有人做錯事。**")


def test_ql19_an_unknown_field_is_still_dropped(profile):
    """⚙️ 反向控制①：**白名單還在 —— 不是改成「什麼都存」。**

    ☠️ 讓上一題變綠最便宜的做法是把 `_clean_locations()` 整個拿掉，
    🔑 而那條白名單存在是有理由的：**前端送什麼後端就存什麼**
    ⇒ 設定表變成一個沒有結構的垃圾桶，而下一個讀它的人要處理任意鍵。
    📌 〈判準的寬窄都會騙人〉：「全部都存」是「存那五個」的超集。
    """
    r = profile.put({"locations": [dict(SENT, __ql19_junk="不該被存下來")]})
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    got = _sent_back(profile.locations())
    assert "__ql19_junk" not in got, (
        f"任意欄位被存下來了：{sorted(got)}\n"
        "☠️ 白名單被拿掉了 —— 設定表變成沒有結構的垃圾桶。")


def test_ql19_the_probe_goes_red_when_a_field_leaves_the_whitelist(profile,
                                                                   monkeypatch):
    """📏 量尺：**從白名單拿掉一欄，上面那一題要紅。**

    ⚠️ 這一節是**綠著出生的**（B 在我寫之前就加了
    `_LOCATION_IDENTITY_FIELDS`）——
    ☠️ 而一個綠著出生的題目最可能的解釋是**它什麼都沒驗**，
    🔑 今天早上 `QL7` 剛付過這個學費（八題全綠而功能零效果）。

    ⚠️ **不改 B 的檔**：把那個常數換成少一欄的版本，
    等同於「這次收緊白名單時漏掉了它」—— **而那正是這次的成因。**
    """
    from routers import system

    full = tuple(system._LOCATION_IDENTITY_FIELDS)
    assert "tax_id" in full, (
        f"`_LOCATION_IDENTITY_FIELDS` 裡沒有 `tax_id`：{full}\n"
        "⇒ 這個量尺的前提不成立。")
    monkeypatch.setattr(system, "_LOCATION_IDENTITY_FIELDS",
                        tuple(f for f in full if f != "tax_id"))

    r = profile.put({"locations": [dict(SENT)]})
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    got = _sent_back(profile.locations())
    assert got.get("tax_id") != SENT["tax_id"], (
        "把 `tax_id` 從白名單拿掉之後，它**仍然**存下來了 ——\n"
        "☠️ 那代表上面那幾題量到的不是那條白名單，\n"
        "🔑 而它們的綠證明不了任何事。\n"
        "⚠️ 也可能是那個常數不再是決定行為的那個東西（它被搬走了）——\n"
        "📌 〈守門守的對象被搬走〉：今天已經踩過兩次。")
