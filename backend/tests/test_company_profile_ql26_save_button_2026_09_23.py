# -*- coding: utf-8 -*-
"""`QL26` · 公司基本資料卡要有自己的儲存按鈕，且兩張卡各自存得起來（已出貨，補題）。

# 🔴 為什麼是「補題」不是「派工」

使用者原話：「追加公司基本資料的更改後沒有儲存設定的按鈕」——實查
`frontend/pages/company-profile-settings.html`，**修復已經在了**：B 在
「公司基本資料」卡（`公司基本資料` 標題與 `收款帳戶資訊` 標題之間）
補了一顆 `@click="save()"` 的按鈕，與下面那張卡的按鈕呼叫**同一支**
`save()`（避開「兩顆按鈕、兩種儲存行為」——product 碼裡的 `QL26` 註解
自己就寫著這條界線）。但**已出貨而完全沒有題**：`SCOPE.md` 要這一包
全綠，而一個沒有題的編號不可能是綠的，它只是不紅。本檔補上這道守門，
不改任何產品碼。

# 🔴 判準：使用者要的不是「有按鈕」，是「兩張卡各自存得起來」

A 的裁示逐字：「題要釘兩張卡各自存得起來，不是只釘『有按鈕』」——
`save()` 送的是整包 `{...cfg, locations}`，兩顆按鈕在**目前的實作**下
完全等價（都送同一包），所以「按鈕存不存得住」這件事沒辦法在
按鈕層級分辨，只能在**它送出去之後有沒有真的落地**分辨：

```
① 公司基本資料三欄（name／tax_id／contact_info）
   —— 全庫既有測試只驗過 PUT 的 status_code（200/403），
      **沒有一支驗過 GET 讀得回來**（`test_api_integration.py`、
      `test_company_profile_superadmin_only_2026_09_22.py` 皆是）。
② 銀行四欄已經有 round-trip 覆蓋（`test_geo_2026_09_21.py:249-253`
   明確斷言 `stored.get("bank_account_number") == ""`），本檔不重覆。
③ 兩張卡的欄位要能**同時**活著——存基本資料卡的當下不能把銀行欄位
   洗掉（反之亦然），因為兩顆按鈕送的是同一包。
```

# ⚙️ 觀測點

直接打 `PUT /api/settings/company-profile` 再 `GET` 讀回來，不模擬點擊
哪一顆按鈕——兩顆送的東西相同，button-level 的差異只存在於 DOM。DOM
層面另外用靜態文字切片驗證按鈕真的長在「公司基本資料」卡裡（不是只
存在於「收款帳戶資訊」卡）。

# ✅ 牙齒已驗證（方式：突變驗證／live，非常設）

① 結構題：暫時把 `frontend/pages/company-profile-settings.html` 裡
   「公司基本資料」卡的那顆按鈕整段拿掉（保留下面那張卡的按鈕不動，
   對照 `QL26` 修復前的真實狀態），跑本檔的結構題**真的會紅**；改回
   即恢復綠。
② 持久化題：monkeypatch `routers.system._set_setting`，在真的寫入前
   把 `name`／`tax_id`／`contact_info` 三個鍵從 `value` 裡拿掉（模擬
   「這三欄安靜地沒有被存進去」這個真實失效模式），round-trip 那三題
   **各自都會紅**；負對照（銀行欄位不受這個突變影響）**仍然是綠的**，
   證明分得出是哪一組欄位壞了。
"""
import json
import re

import pytest

FRONTEND = None


def _company_profile_html():
    import pathlib
    global FRONTEND
    if FRONTEND is None:
        here = pathlib.Path(__file__).resolve()
        FRONTEND = (here.parents[2] / "frontend" / "pages"
                    / "company-profile-settings.html")
    return FRONTEND.read_text(encoding="utf-8")


def _basic_info_card_html():
    """切出「公司基本資料」卡的 HTML——從它的標題到「收款帳戶資訊」的
    註解為止，不含下一張卡的任何內容（避免驗到別人的按鈕）。"""
    html = _company_profile_html()
    start = html.index('公司基本資料')
    end = html.index('<!-- 收款帳戶資訊 -->')
    assert start < end, "找不到『公司基本資料』到『收款帳戶資訊』這一段——頁面結構可能已經改版。"
    return html[start:end]


def _hdr(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


# ══════════════════════════════════════════════════════════════════════
# ① 結構：公司基本資料卡要有自己的儲存按鈕
# ══════════════════════════════════════════════════════════════════════

def test_ql26_the_basic_info_card_has_its_own_save_button():
    """🔴🔴 **「公司基本資料」卡裡要有一顆呼叫 `save()` 的按鈕。**

    ☠️ 這是使用者的原話：改完這張卡看到的是下一張卡的標題，不知道要
    往下滑才找得到存檔的地方。負對照請看下一題——按鈕必須呼叫同一支
    `save()`，不可以是另一支只存半張表的函式。
    """
    card = _basic_info_card_html()
    clicks = re.findall(r'<button[^>]*@click="([^"]+)"[^>]*>', card)
    assert clicks, (
        "「公司基本資料」卡裡找不到任何按鈕——這正是 QL26 原本回報的缺陷"
        "（使用者找不到儲存這張卡的地方）。")
    # ⚠️ 這張卡裡還有 `removeLocation(i)`／`moveLocationUp(i)` 這些**據點
    # 操作**用的按鈕，`re.search` 只抓第一顆會抓到它們——要在**全部**按鈕
    # 裡找 `save()`，不是斷言「第一顆就是它」。
    assert "save()" in clicks, (
        "「公司基本資料」卡裡的按鈕都不是 save()，抓到的是 %r——\n"
        "⚠️ 兩顆按鈕必須呼叫同一支，否則變成兩種儲存行為（見產品碼裡的"
        " QL26 註解）。" % clicks)


def test_ql26_the_bank_card_button_is_a_separate_element_not_the_same_one_counted_twice(client, make_user):
    """⚙️ **正對照：下面「收款帳戶資訊」卡本來就有一顆按鈕，兩張卡是各自
    獨立的兩顆，不是同一顆被切片邏輯算了兩次。**"""
    html = _company_profile_html()
    basic_end = html.index('<!-- 收款帳戶資訊 -->')
    bank_html = html[basic_end:]
    m = re.search(r'<button[^>]*@click="([^"]+)"[^>]*>', bank_html)
    assert m and m.group(1) == "save()", (
        "「收款帳戶資訊」卡的按鈕不見了或呼叫的函式變了：%r——若這題紅了，"
        "代表壞的不是 QL26 的修復，是這份測試自己的切片。" % (m and m.group(1)))


# ══════════════════════════════════════════════════════════════════════
# ② 持久化：公司基本資料三欄要真的存得住（既有測試只驗過 status_code）
# ══════════════════════════════════════════════════════════════════════

def test_ql26_company_name_actually_round_trips(client, make_user):
    """🔴🔴 **`name` 存了之後，GET 要讀得回來——不是只驗 PUT 回 200。**"""
    _u, hdr = _hdr(client, make_user, "ql26_name")
    r = client.put("/api/settings/company-profile", headers=hdr,
                    json={"name": "QL26測試公司甲"})
    assert r.status_code == 200, r.text[:300]
    r = client.get("/api/settings/company-profile", headers=hdr)
    assert r.status_code == 200, r.text[:300]
    assert r.json().get("name") == "QL26測試公司甲", (
        "存了 `name` 之後讀回來是 %r——PUT 回 200 證明不了真的寫進去了。"
        % r.json().get("name"))


def test_ql26_tax_id_actually_round_trips(client, make_user):
    """🔴🔴 **`tax_id`（統一編號）存了之後，GET 要讀得回來。**"""
    _u, hdr = _hdr(client, make_user, "ql26_taxid")
    r = client.put("/api/settings/company-profile", headers=hdr,
                    json={"tax_id": "12345678"})
    assert r.status_code == 200, r.text[:300]
    r = client.get("/api/settings/company-profile", headers=hdr)
    assert r.status_code == 200, r.text[:300]
    assert r.json().get("tax_id") == "12345678", (
        "存了 `tax_id` 之後讀回來是 %r。" % r.json().get("tax_id"))


def test_ql26_contact_info_actually_round_trips(client, make_user):
    """🔴🔴 **`contact_info`（聯絡方式）存了之後，GET 要讀得回來。**"""
    _u, hdr = _hdr(client, make_user, "ql26_contact")
    r = client.put("/api/settings/company-profile", headers=hdr,
                    json={"contact_info": "Tel: 04-1111-2222"})
    assert r.status_code == 200, r.text[:300]
    r = client.get("/api/settings/company-profile", headers=hdr)
    assert r.status_code == 200, r.text[:300]
    assert r.json().get("contact_info") == "Tel: 04-1111-2222", (
        "存了 `contact_info` 之後讀回來是 %r。" % r.json().get("contact_info"))


def test_ql26_saving_basic_info_does_not_erase_previously_saved_bank_fields(client, make_user):
    """🔴 **兩張卡送的是同一包——存基本資料時，先前存好的銀行欄位不能被洗掉。**

    ⚙️ 模擬真實的兩步操作：先用「收款帳戶資訊」卡存一次銀行欄位（對應
    第一次點下面那顆按鈕），再用「公司基本資料」卡送一次只改名稱（對應
    後來點上面那顆按鈕，但和前端一樣附帶目前的 `cfg` 快照）——銀行欄位
    要原封不動留著。
    """
    _u, hdr = _hdr(client, make_user, "ql26_both")
    r = client.put("/api/settings/company-profile", headers=hdr,
                    json={"bank_name": "QL26銀行", "bank_account_number": "999888777"})
    assert r.status_code == 200, r.text[:300]

    r = client.put("/api/settings/company-profile", headers=hdr,
                    json={"name": "QL26測試公司乙"})
    assert r.status_code == 200, r.text[:300]

    r = client.get("/api/settings/company-profile", headers=hdr)
    body = r.json()
    assert body.get("name") == "QL26測試公司乙", body
    assert body.get("bank_name") == "QL26銀行", (
        "存基本資料卡的名稱之後，銀行名稱變成 %r——兩張卡不是各自獨立"
        "存得起來，後存的把先存的洗掉了。" % body.get("bank_name"))
    assert body.get("bank_account_number") == "999888777", (
        "存基本資料卡的名稱之後，銀行帳號變成 %r。" % body.get("bank_account_number"))
