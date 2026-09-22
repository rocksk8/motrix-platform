"""§3u 第一節 · Google 金鑰的輸入位置與遮蔽（UA1–UA4）。

> **使用者回報：想填 Google 金鑰，而畫面上沒有任何地方可以填。**

---

# 🔴 現況（A 查出、我逐項複核過）

```
後端  company_profile.google_maps_api_key   欄位在（system.py:619）、PUT 支援
前端  grep google_maps_api_key frontend/    **0 處**
設定頁 company-profile-settings.html        只有 name／tax_id／contact_info／
                                            address／銀行四欄
而 tender-radar.html:188 寫著：
      「附近廠商：未啟用——這是選用功能，**需要在公司資料設定填入 Google Maps 金鑰**。」
```

☠️ **畫面指向一個不存在的欄位**，而使用者照著去找了。
🔑 跟今晚那條同族：**一句指路，本身不是那條路。**
（`db.py:597` 的「守門見 test_u5c」指向一支不存在的測試，是同一個形狀。）

## ⚠️ 我複核時多找到一個同型的，A 沒提

`map.html:83` 寫著「**可以在公司資料設定直接填經緯度**，那會跳過所有查詢」，
而設定頁**也沒有 `office_lat`／`office_lon` 的輸入框**（grep = 0）。
⇒ **兩句指路都是錯的，不是一句。** 已回報 A。

---

# 🔴 UA2 帶來一個 A 沒寫、而會安靜咬人的互動

遮蔽之後，GET 回的是 `••••••••••••ab12`。
☠️ **設定頁存檔時若把那串遮蔽字送回去，就會用 `••••ab12` 覆蓋掉真金鑰。**

而症狀是：使用者改了**銀行帳號**存檔 ⇒ 幾天後發現「附近廠商」變成未啟用
⇒ **沒有人會把那兩件事連起來。**

⇒ 我加了 **UA3c**：**送回遮蔽字串不可以破壞現有金鑰**。
📌 它是**後端的安全網**，而不是「前端應該不要送」——
🔑 前端會回歸，而**這個缺陷不會有任何錯誤訊息**。
（這一條是我加的，不在 A 的四條裡，理由寫在題目裡。）
"""
import sys
from pathlib import Path

import pytest

#: ⚠️ 單獨跑一個檔時 `sys.path` 不含 `tests/`（pytest 的自動插入發生在收集
#: 那一刻，而 `from ... import` 發生在匯入那一刻）。
#: 🔑 **「整批跑得起來」不等於「單獨跑得起來」，而單獨跑正是除錯時的跑法。**
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mapiso import no_tile_probe  # noqa: E402,F401  （fixture，被 UA4 用到）

PROFILE_PATH = "/api/settings/company-profile"
MAP_PATH = "/api/map/points?sources=tenders"

KEY = "AIzaSyD-TestKeyForUnitTests-ab12"
KEY_TAIL = KEY[-4:]

SETTINGS_PAGE = "company-profile-settings.html"


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _get(client, hdr):
    r = client.get(PROFILE_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, hdr, payload, expect=200):
    r = client.put(PROFILE_PATH, json=payload, headers=hdr)
    assert r.status_code == expect, (
        f"PUT {payload} 預期 {expect}，實際 {r.status_code}：{r.text[:200]}"
    )
    return r


def _stored_key():
    """直接從設定表讀**真正存著的值**（繞過遮蔽）。

    🔑 遮蔽之後，API 回的東西**不能用來判斷金鑰有沒有被破壞** ——
    那正是 UA3c 要驗的事，所以觀測點必須在遮蔽的**下游**。
    """
    from helpers.settings import _get_setting
    return (_get_setting("company_profile", {}) or {}).get("google_maps_api_key")


# ══════════════════════════════════════════════════════════════════════
# UA1 · 設定頁要有那個輸入框
# ══════════════════════════════════════════════════════════════════════

def _page(name):
    from pathlib import Path
    p = (Path(__file__).resolve().parent.parent.parent
         / "frontend" / "pages" / name)
    assert p.exists(), f"找不到 {p}"
    return p.read_text(encoding="utf-8")


def test_ua1_the_settings_page_has_an_input_for_the_key():
    """🟡 UA1：公司資料設定頁要有 `google_maps_api_key` 的輸入框。

    ⚠️ **這是文字比對，弱的** —— 我只能確認那個欄位名被綁上去了，
    **不能確認它渲染得出來、也不能確認它存得進去**（後者由 UA3／UA4 驗）。
    🔑 它答的是「有沒有被寫出來」。
    """
    text = _page(SETTINGS_PAGE)
    assert "google_maps_api_key" in text, (
        f"`{SETTINGS_PAGE}` 裡完全沒有 `google_maps_api_key` ——\n"
        "⇒ 而 `tender-radar.html:188` 叫使用者「在公司資料設定填入 "
        "Google Maps 金鑰」。**畫面指向一個不存在的欄位。**"
    )


def test_ua1b_every_page_that_points_here_points_at_something_that_exists():
    """🔴 UA1b：**指路的那句話，與被指的那個欄位，要對得起來。**

    ☠️ 這一題是 UA1 的真正價值所在，而它比「有沒有那個輸入框」更通用：
    **一句指路本身不是那條路。**

    📌 兩處實例（`tender-radar.html:188` 的金鑰、`map.html:83` 的經緯度），
    ⚠️ 而第二處是我複核 A 的回報時**多找到的** —— A 只說了一句是錯的。
    🔑 〈判準的寬窄都會騙人〉：**報「有一個」之前要先問「我查的範圍是什麼」。**
    """
    settings = _page(SETTINGS_PAGE)
    pointers = [
        ("tender-radar.html", "Google Maps 金鑰", "google_maps_api_key"),
        ("map.html", "直接填經緯度", "office_lat"),
    ]
    broken = []
    for page_name, phrase, field in pointers:
        if phrase not in _page(page_name):
            continue                      # 那句話被改掉了，不再指路
        if field not in settings:
            broken.append(f"{page_name} 說「{phrase}」，"
                          f"而 `{SETTINGS_PAGE}` 沒有 `{field}`")
    assert not broken, (
        "這些指路指向不存在的欄位：\n  " + "\n  ".join(broken)
        + "\n\n⇒ 使用者會照著去找，然後找不到。"
        "**那比「沒做那個功能」更糟** —— 前者他會以為是自己看漏了。"
    )


# ══════════════════════════════════════════════════════════════════════
# UA2 · 遮蔽顯示
# ══════════════════════════════════════════════════════════════════════

def test_ua2_the_stored_key_is_never_returned_in_clear_text(
        client, make_user):
    """🔴 UA2：存過之後，GET **不可以把金鑰明文回傳**，只露末四碼。

    ☠️ 那是一個**付費憑證**，而畫面會被截圖、會被投影、會被肩後看見。
    📌 現況：`get_company_profile` 直接
    `return {**_COMPANY_PROFILE_DEFAULT, **設定}` ⇒ **明文**。

    ⚠️ 判準刻意**不釘遮蔽符號長什麼樣**（`•` 幾個、用 `*` 還是 `●`）——
    那是排版。🔑 釘的是**不變量**：
    **回傳值不等於金鑰、不含金鑰的前段、而末四碼看得到。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": KEY})
    assert _stored_key() == KEY, "前提不成立：金鑰沒有被存進去"

    shown = _get(client, hdr).get("google_maps_api_key")
    assert shown != KEY, (
        "GET 把金鑰明文回傳了。那是付費憑證，而畫面會被截圖／投影／肩後看見。"
    )
    assert KEY[:-4] not in (shown or ""), (
        f"回傳值裡含有金鑰的前段：{shown!r}"
    )
    assert (shown or "").endswith(KEY_TAIL), (
        f"末四碼看不到（`{KEY_TAIL}`），實際 {shown!r} ——\n"
        "⇒ 使用者要分得出「我填的是哪一把」，全遮的話他無從確認。"
    )


def test_ua2b_an_empty_key_is_not_masked_into_looking_set(client, make_user):
    """🔴 UA2b 反向控制：**沒有金鑰時，不可以回一串遮蔽符號。**

    ☠️ 少了這一題，一個「一律回 `••••••••`」的實作會讓 UA2 綠 ——
    而畫面上「**已經設定了**」與「**還沒設定**」會變成同一個樣子，
    🔑 那正好把 UA1 要解決的問題原封不動搬到另一個位置：
    **使用者以為填過了，而「附近廠商」一直沒有出現。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": ""})
    assert not _stored_key(), "前提不成立：金鑰沒有被清掉"

    shown = _get(client, hdr).get("google_maps_api_key")
    assert not shown, (
        f"沒有金鑰時 GET 回了 {shown!r} —— 那看起來像「已經設定了」。"
    )


# ══════════════════════════════════════════════════════════════════════
# UA3 · 「沒送」與「送了空字串」是兩件事
# ══════════════════════════════════════════════════════════════════════

def test_ua3_an_empty_string_clears_the_key(client, make_user):
    """🟢 UA3：**送出空字串 = 明確清除。**

    ⚠️ 不可以寫成「空字串一律忽略」，否則使用者**永遠刪不掉**填錯的金鑰
    —— 而填錯的金鑰不是沒有代價：Google 會計費，或者一直失敗。

    ↩︎ 什麼改動會讓它紅：在 `set_company_profile` 加一句
       「空字串就跳過」的特判。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": KEY})
    assert _stored_key() == KEY, "前提不成立"

    _put(client, hdr, {"google_maps_api_key": ""})
    assert _stored_key() in ("", None), (
        f"送了空字串而金鑰還在：{_stored_key()!r}"
    )


def test_ua3b_a_field_that_was_not_sent_keeps_its_value(client, make_user):
    """🟢 UA3b：**沒送這個欄位 = 保留現值。**

    📌 後端已經做對了（`body.model_dump(include=body.model_fields_set)`），
    而那條路**全庫只有兩處在用**（這裡與 `suppliers.py:106`）。
    ⚠️ `CompanyProfile` 是 **Pydantic 模型不是 dict** ⇒ `key in body` 在這裡
    **不成立**（Pydantic 會先把沒送的欄位填成 `''`），抄 `tender_radar.py`
    的寫法過來會**失效而且安靜**。

    ↩︎ 什麼改動會讓它紅：改回 `body.model_dump()` 整筆覆蓋。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": KEY})
    assert _stored_key() == KEY, "前提不成立"

    _put(client, hdr, {"bank_account_number": "12345678"})
    assert _stored_key() == KEY, (
        f"只送了銀行帳號，而金鑰被動到了：{_stored_key()!r}\n"
        "⇒ 「沒送」與「送了空字串」被壓成同一件事。"
    )


def test_ua3c_sending_the_mask_back_must_not_destroy_the_key(
        client, make_user):
    """🔴🔴 UA3c（**我加的，不在 A 的四條裡**）：
    **把遮蔽字串送回來，不可以覆蓋掉真金鑰。**

    ## ☠️ 這是 UA2 直接帶出來的缺陷，而它完全安靜

    遮蔽之後 GET 回 `••••••••ab12`。設定頁最自然的寫法是
    「載入時填進輸入框、存檔時整包送出」⇒ **那串遮蔽字會被寫進設定**。

    而症狀是：使用者改了**銀行帳號**存檔 ⇒ 幾天後「附近廠商」變成未啟用
    ⇒ 🔑 **沒有人會把那兩件事連起來。**

    ## 📌 為什麼放在後端而不是「前端應該不要送」

    前端**會回歸**（換一個人寫、換一個框架、複製貼上另一頁的存檔函式），
    而這個缺陷**不會有任何錯誤訊息**。
    ⇒ 後端要有安全網：**收到一個「看起來就是遮蔽字」的值時，視為沒送。**
    ⚠️ 而它與 UA3 不衝突：**空字串仍然是明確清除**，遮蔽字不是空字串。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": KEY})
    masked = _get(client, hdr).get("google_maps_api_key")
    assert masked and masked != KEY, (
        f"前提不成立：UA2 還沒做（GET 回的是 {masked!r}）"
    )

    _put(client, hdr, {"google_maps_api_key": masked})
    assert _stored_key() == KEY, (
        f"把遮蔽字 {masked!r} 送回去之後，存著的金鑰變成 "
        f"{_stored_key()!r}。\n"
        "⇒ 使用者下一次存銀行帳號就會把金鑰毀掉，而畫面上不會有任何錯誤。"
    )


# ══════════════════════════════════════════════════════════════════════
# UA4 · 反向控制：存進去的要真的被讀到
# ══════════════════════════════════════════════════════════════════════

def test_ua4_setting_the_key_turns_the_map_flag_on(
        client, make_user, no_tile_probe):
    """🔴 UA4 反向控制：填了金鑰 ⇒ `googleMapsConfigured` 變 `true`；
    清掉 ⇒ 變回 `false`。

    ☠️ 沒有這一題，一個「**存進去但沒有人讀**」的實作會讓 UA1／UA3 全綠 ——
    而使用者填了金鑰、按了儲存、畫面**仍然說未啟用**，
    🔑 那比「沒有輸入框」更難查：**他會以為是金鑰填錯了**，
    然後去 Google Console 繞一圈。

    📌 **兩個方向都驗**：只驗「填了會變 true」的話，
    一個寫死 `true` 的實作會綠。
    """
    hdr = _auth(client, make_user)

    _put(client, hdr, {"google_maps_api_key": ""})
    off = client.get(MAP_PATH, headers=hdr)
    assert off.status_code == 200, off.text
    assert off.json()["googleMapsConfigured"] is False, "前提不成立"

    _put(client, hdr, {"google_maps_api_key": KEY})
    on = client.get(MAP_PATH, headers=hdr)
    assert on.status_code == 200, on.text
    assert on.json()["googleMapsConfigured"] is True, (
        "金鑰存進去了，而 `/api/map/points` 仍然說沒設定 ——\n"
        "⇒ 存得進去但沒有人讀它。"
    )

    _put(client, hdr, {"google_maps_api_key": ""})
    back = client.get(MAP_PATH, headers=hdr)
    assert back.json()["googleMapsConfigured"] is False, (
        "清掉金鑰之後仍然說已設定 —— 那個旗標沒有跟著現值走。"
    )


def test_ua4b_the_key_is_never_written_to_the_audit_trail(client, make_user):
    """🔴 UA4b：存金鑰的那次操作，**稽核紀錄裡不可以有金鑰本身**。

    📌 `set_company_profile` 現在留的是**公司名**不是整包 `value`，
    而那包裡有金鑰 —— 這一題把那個已經做對的決定**釘住**。

    ☠️ 而它與今晚 uvicorn access log 那件是同一族：
    🔑 **資料外洩不需要我們寫入，只需要有人記錄** ——
    `audit_log` 有 2,254 列、**會進每日備份、會上傳雲端**，
    而那份備份沒有人在管憑證。

    ↩︎ 什麼改動會讓它紅：把 `_audit(..., value.get("name",""))`
       改成 `_audit(..., str(value))`（那是很自然的「多留一點資訊」）。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"google_maps_api_key": KEY})

    import db
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT action, target_label, detail FROM audit_log "
            "WHERE action LIKE '%company_profile%'").fetchall()
    finally:
        conn.close()

    assert rows, "一筆稽核都沒有 —— 前提不成立（那個動作沒有被記錄？）"
    leaked = [dict(r) for r in rows
              if KEY in " ".join(str(r[k] or "") for k in r.keys())]
    assert not leaked, (
        f"金鑰出現在 {len(leaked)} 筆稽核紀錄裡：{leaked[0]}\n"
        "⇒ `audit_log` 會進每日備份並上傳雲端，而那裡沒有人在管憑證。"
    )
