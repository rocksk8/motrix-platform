"""§10 SA1–SA4 · 公司身分與金錢欄位只有最高管理員可以改。

使用者原話：
> 「像匯款帳號\\公司名稱\\帳戶\\很多都要能改，**只有超級管理員可以修改**」

---

# ☠️ 現在不是。而它看起來像是。

```python
routers/system.py:1001
_require_user(authorization, require_superadmin=True, module='settings')
```
`helpers/auth.py:202` 的 docstring 逐字寫著：
> **superadmin OR users with that module key in their modules list**

🔑 **`require_superadmin=True` 這個參數名說的不是它做的事** ——
📌 它真正的意思是「superadmin **或**持有那個模組的人」。
⚠️ 而 A 在正式資料庫裡查到真的有這種人：
```
automation    role=viewer    modules 含 settings    ← 一個 viewer 改得動匯款帳號
```

## ☠️ 而稽核抓不到它

```python
routers/system.py:1039
_audit(_tok(authorization), "settings.company_profile.update", "settings",
       "company_profile", value.get("name", ""))
                          ^^^^^^^^^^^^^^^^^^^^ 這是 target_label，不是 detail
```
`_audit()` 的 `detail` 參數**沒有被傳** ⇒ `audit_log` 裡歷來 4 筆 detail 全是 `{}`。
🔑 **一個 viewer 把帳號換成自己的，紀錄裡只有一行「有人更新了公司資料」** ——
**沒有哪些欄位變了、沒有前後值。**
📌 〈降級之後它還是會動〉：**成功了，而且降低了安全強度。**

---

# 🔴 這一檔寫的時候，SA1／SA2／SA3 全是紅的

⚠️ 那是刻意的 —— 這幾題描述的是**要變成什麼樣**，不是現況。
🔑 而 SA1 的反向控制是這一節的本體：
☠️ **沒有那一題，一個「照樣放行」的實作會全綠 —— 而目前就是那個狀態。**

## 📌 SA4 的兩題相反：它們現在就是綠的

讀取維持「登入即可」（A 裁：匯款帳號本來就印在寄給客戶的請款單上，**它不是秘密**），
而 Google 金鑰照舊遮蔽（**那個才是秘密**）。
⇒ 它們是**回歸守門**：防的是「把門關緊」時順手把讀取也關掉。
"""
import json

import pytest

MONEY_FIELDS = ("bank_account_number", "bank_name", "bank_branch",
                "bank_account_name", "company_name", "tax_id")


def _login(client, username, password):
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _audit_rows(action="settings.company_profile.update"):
    import db
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT username, detail FROM audit_log WHERE action=? ORDER BY id",
            (action,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        raw = r["detail"]
        try:
            parsed = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            parsed = {"__unparsable__": raw}
        out.append((r["username"], parsed))
    return out


# ══════════════════════════════════════════════════════════════════════
# SA1 · 只有 superadmin 改得動
# ══════════════════════════════════════════════════════════════════════

def test_sa1_a_viewer_holding_the_settings_module_is_refused(client, make_user):
    """🔴🔴 SA1 反向控制：**`role=viewer` ＋ `modules` 含 `settings` ⇒ 403。**

    ☠️ **這一題就是那個缺陷本身。** 目前的實作會回 200。
    🔑 而它之所以到今天才被看見，是因為
    `require_superadmin=True` 這個參數名**讀起來已經像是關緊了**。
    📌 〈把自己的動作當成對象的性質〉的近親：
    **一個參數名不是一個保證。**

    ⚠️ 正式機上真的有這種帳號（`automation`）——
    **這不是一個理論上的組合。**
    """
    username, password = make_user(username="sa1_viewer", role="viewer",
                                   modules=["settings"])
    token = _login(client, username, password)

    r = client.put("/api/settings/company-profile",
                   headers=_auth(token),
                   json={"bank_account_number": "9999999999"})
    assert r.status_code == 403, (
        f"一個 role=viewer（只是持有 `settings` 模組）改得動匯款帳號"
        f"（回 {r.status_code}）。\n"
        "☠️ `require_superadmin=True, module='settings'` 的真正意思是"
        "「superadmin **或** 持有那個模組的人」。\n"
        "⇒ 拿掉 `module='settings'`。"
    )


def test_sa1_an_admin_without_the_module_is_refused(client, make_user):
    """🔴 SA1：連 `admin` 都不行 —— 判準是**角色**不是模組。

    📌 這一題與上面那題分開的理由：
    ⚠️ 只驗 viewer 的話，一個「把判準從模組換成 `role != 'viewer'`」的實作會綠，
    🔑 而那不是使用者要的（他說的是「**只有超級管理員**」）。
    """
    username, password = make_user(username="sa1_admin", role="admin",
                                   modules=["settings"])
    token = _login(client, username, password)

    r = client.put("/api/settings/company-profile",
                   headers=_auth(token), json={"tax_id": "00000000"})
    assert r.status_code == 403, (
        f"`role=admin` 改得動公司身分欄位（回 {r.status_code}）—— "
        "使用者說的是「只有超級管理員」。"
    )


def test_sa1_a_superadmin_can_still_update(client, make_user):
    """🔴 SA1 正對照：**superadmin 仍然改得動。**

    ☠️ 少了這一題，「一律 403」會讓上面兩題全綠，
    **而那個實作讓公司資料永遠改不了。**
    🔑 〈判準的寬窄都會騙人〉：**拒絕全部是「拒絕該拒絕的」的超集。**
    """
    username, password = make_user(username="sa1_super", role="superadmin")
    token = _login(client, username, password)

    r = client.put("/api/settings/company-profile",
                   headers=_auth(token),
                   json={"bank_account_name": "摩特銳斯股份有限公司"})
    assert r.status_code == 200, (
        f"superadmin 被擋掉了（{r.status_code}）：{r.text[:200]}\n"
        "⇒ 這個設定頁現在沒有人改得了。"
    )


# ══════════════════════════════════════════════════════════════════════
# SA3 · `locations` 的銀行與抬頭欄位同樣只有 superadmin
# ══════════════════════════════════════════════════════════════════════

def test_sa3_the_location_bank_fields_are_superadmin_only(client, make_user):
    """🔴 SA3：**據點裡的銀行／抬頭欄位同樣鎖 superadmin。**

    ## 📌 為什麼要單獨寫一題，即使 SA1 現在就蓋住它

    `locations` 走的是**同一個端點** ⇒ SA1 一改就涵蓋了。
    ☠️ **而下一個人把 `locations` 拆成獨立端點時，那道保護不會自動跟過去。**
    🔑 〈守門守的對象被搬走〉的**預防版**：
    **先把不變量釘在「那個欄位」上，而不是釘在「那條路由」上。**

    ⚠️ 那不是假設性的：§5 多據點才剛落地，而 §9（報價單綁據點）
    已經在規格裡 —— **據點的編輯介面遲早會長成自己的一支。**
    """
    username, password = make_user(username="sa3_viewer", role="viewer",
                                   modules=["settings"])
    token = _login(client, username, password)

    r = client.put(
        "/api/settings/company-profile",
        headers=_auth(token),
        json={"locations": [{"id": "L1", "name": "台中分公司",
                             "bank_account_number": "9999999999"}]})
    assert r.status_code == 403, (
        f"一個 viewer 改得動據點的匯款帳號（回 {r.status_code}）。\n"
        "☠️ 請款單上印的就是這個號碼。"
    )


# ══════════════════════════════════════════════════════════════════════
# SA2 · 稽核要記「哪些欄位變了」
# ══════════════════════════════════════════════════════════════════════

def test_sa2_the_audit_records_which_fields_changed(client, make_user):
    """🔴🔴 SA2：**稽核要記下變更的欄位名清單。**

    ## 🔑 判準：事後要能回答「是誰、在什麼時候、把帳號從什麼改成什麼」

    ☠️ 現在記的是**公司名**（`value.get("name","")`，而且進的是
    `target_label` 不是 `detail`）——
    **它回答不了那個問題，而它看起來像有稽核。**

    📌 `_audit()` 有一個 `detail: dict` 參數，**而呼叫端從來沒有傳過它**
    ⇒ `audit_log` 歷來 4 筆的 `detail` 全是 `{}`。
    ⚠️ 〈缺欄位≠缺訊號〉的反面：**欄位在，只是從來沒有人往裡面放東西。**
    """
    username, password = make_user(username="sa2_super", role="superadmin")
    token = _login(client, username, password)

    before = len(_audit_rows())
    r = client.put("/api/settings/company-profile",
                   headers=_auth(token),
                   json={"bank_account_number": "12345678901234",
                         "bank_branch": "台中分行"})
    assert r.status_code == 200, r.text

    rows = _audit_rows()
    assert len(rows) == before + 1, (
        f"這一次更新沒有留下稽核紀錄（{before} → {len(rows)}）。")
    _user, detail = rows[-1]

    changed = detail.get("changed") or detail.get("fields") or []
    assert changed, (
        f"稽核的 `detail` 裡沒有「變更了哪些欄位」：{detail!r}\n"
        "⇒ 需要一個欄位名清單（鍵名建議 `changed`）。"
    )
    assert set(changed) >= {"bank_account_number", "bank_branch"}, (
        f"變更清單漏了欄位：{changed}\n"
        "⇒ 這次送出的是 `bank_account_number` 與 `bank_branch`。"
    )
    assert "name" not in changed, (
        f"沒有送出的欄位被記成「變更了」：{changed}\n"
        "☠️ 一份把沒改的也列進去的清單，等於沒有清單。"
    )


def test_sa2_money_fields_keep_before_and_after_but_masked(client, make_user):
    """🔴🔴 SA2：**金錢／身分欄位要記前後值，而帳號中間遮蔽（只留末四碼）。**

    ```
    記         事後要回答「從什麼改成什麼」
    遮蔽       稽核紀錄本身會被匯出、被截圖 ⇒ 它不可以變成第二個洩漏點
    ```
    🔑 兩件事同時成立才有用：**只記「變了」回答不了問題，
    而記全碼會讓 `audit_log` 變成一張帳號清單。**
    """
    username, password = make_user(username="sa2_money", role="superadmin")
    token = _login(client, username, password)

    old = "11112222333344"
    new = "55556666777788"
    r = client.put("/api/settings/company-profile",
                   headers=_auth(token), json={"bank_account_number": old})
    assert r.status_code == 200, r.text
    r = client.put("/api/settings/company-profile",
                   headers=_auth(token), json={"bank_account_number": new})
    assert r.status_code == 200, r.text

    _user, detail = _audit_rows()[-1]
    blob = json.dumps(detail, ensure_ascii=False)

    assert old not in blob and new not in blob, (
        f"稽核紀錄裡有完整的帳號：{blob[:300]}\n"
        "☠️ `audit_log` 會被匯出，它不可以變成第二個洩漏點。"
    )
    assert old[-4:] in blob and new[-4:] in blob, (
        f"稽核紀錄裡找不到前後值的末四碼：{blob[:300]}\n"
        "⇒ 事後要回答「從什麼改成什麼」，只記「變了」回答不了。"
    )


def test_sa2_the_google_key_value_is_never_recorded(client, make_user):
    """🔴🔴 SA2：**Google 金鑰只記「有沒有變」，不記值 —— 連末四碼都不記。**

    ☠️ 它跟銀行帳號**不是同一類**：
    ```
    匯款帳號   本來就印在寄給客戶的請款單上  ⇒ 不是秘密，末四碼可以留
    Google 金鑰 一個付費憑證                ⇒ 撿到就能刷我們的帳
    ```
    🔑 **而一個「一律遮成末四碼」的實作會讓上一題全綠，同時洩漏這一把。**
    📌 〈判準的寬窄都會騙人〉：一個統一的規則對其中一類來說太寬。
    """
    username, password = make_user(username="sa2_key", role="superadmin")
    token = _login(client, username, password)

    key = "AIzaSyTESTKEY0123456789abcdefXYZ"
    r = client.put("/api/settings/company-profile",
                   headers=_auth(token), json={"google_maps_api_key": key})
    assert r.status_code == 200, r.text

    _user, detail = _audit_rows()[-1]
    blob = json.dumps(detail, ensure_ascii=False)

    assert key not in blob, f"稽核紀錄裡有完整的 Google 金鑰：{blob[:300]}"
    assert key[-4:] not in blob, (
        f"稽核紀錄裡有 Google 金鑰的末四碼：{blob[:300]}\n"
        "☠️ 這一把跟匯款帳號不同類 —— **連末四碼都不要留。**"
    )
    changed = detail.get("changed") or detail.get("fields") or []
    assert "google_maps_api_key" in changed, (
        f"金鑰變了而稽核沒有記下「它變了」：{detail!r}\n"
        "🔑 不記值，**但一定要記它變過** —— 否則換金鑰這件事完全無跡可循。"
    )


# ══════════════════════════════════════════════════════════════════════
# SA4 · 讀取維持「登入即可」（這兩題現在就是綠的，它們防的是順手關太緊）
# ══════════════════════════════════════════════════════════════════════

def test_sa4_reading_stays_open_to_any_logged_in_user(client, make_user):
    """🔴 SA4（A 裁）：**讀取維持「登入即可」。**

    🔑 理由：**匯款帳號本來就印在寄給客戶的請款單上，它不是秘密。**
    ⚠️ 這一題是**回歸守門** —— 它防的是「SA1 把門關緊」時順手把讀取也關掉，
    ☠️ 而那會讓一般使用者的請款單頁面整個壞掉，**而症狀離成因很遠**。
    """
    username, password = make_user(username="sa4_viewer", role="viewer",
                                   modules=[])
    token = _login(client, username, password)

    r = client.get("/api/settings/company-profile", headers=_auth(token))
    assert r.status_code == 200, (
        f"一般登入使用者讀不到公司資料（{r.status_code}）—— "
        "請款單要印它，而它不是秘密。"
    )


def test_sa4_the_google_key_is_still_masked_on_read(client, make_user):
    """🔴 SA4：**而 Google 金鑰照舊遮蔽（已實作，這裡釘住它）。**

    📌 這個畫面會被截圖、被投影、被肩後看見，而 superadmin 不只一個人。
    """
    username, password = make_user(username="sa4_super", role="superadmin")
    token = _login(client, username, password)

    key = "AIzaSyREADMASK0123456789abcdefXY"
    r = client.put("/api/settings/company-profile",
                   headers=_auth(token), json={"google_maps_api_key": key})
    if r.status_code != 200:
        pytest.skip(f"寫不進去（{r.status_code}）—— SA1 尚未落地時這題無從驗起")

    r = client.get("/api/settings/company-profile", headers=_auth(token))
    assert r.status_code == 200, r.text
    got = r.json().get("google_maps_api_key", "")
    assert key not in got, f"讀回來的是明文金鑰：{got!r}"
    assert got.endswith(key[-4:]), (
        f"遮蔽後看不出是哪一把（{got!r}）—— 使用者要分得出他填的是哪一組。"
    )
