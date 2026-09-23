# -*- coding: utf-8 -*-
"""`EM5` · 傳票簽核鏈解析失敗要 raise，不是安靜退回 `[]`（已出貨，補題）。

# 🔴 為什麼是「補題」不是「派工」

`helpers/voucher.py::_chain_tiers()` 的 docstring 早就寫明兩條分岔：

```
沒有 approval_json   => 回 []（明確的「沒有設定簽核流程」）
有而解析失敗          => raise VoucherChainUnreadable
```
而全庫**沒有任何一支測試提到 `VoucherChainUnreadable`**（`grep -rl` 零命中）
——這支修復已出貨，卻沒有任何東西守著「解析失敗」這條路徑，只要有人
把 `raise` 改回 `return []`，不會有任何測試變紅。

# 🔴 判準：釘行為，不要釘那段文字

A 的裁示逐字：「釘行為，不要釘那段文字——釘文字的話，今天已經發生兩次
的『守門逼人改註解』會第三次」。這裡不逐字比對錯誤訊息全文，只驗**兩件
可觀測的行為**：

```
① 匯出閘門（`approval_done()`）：解析失敗要**擋下來**（fail-closed）
   —— 訊息裡要看得出「讀不出來」這件事，跟「還沒簽到」是不同原因，
      不能只驗 400（那是〈假綠燈：判準的寬窄都會騙人〉—— 400 本身
      分不出擋下來的是哪一種原因）。
② 版面（`signatures_of()` → GET /api/vouchers/{id}）：解析失敗要在
   `signatures` 裡**印出一格說讀不出來**（fail-open，但要讓看的人知道
   簽核狀態不明），不是安靜退回內建兩格（那會讓一張簽核狀態不明的單
   看起來像正常沒設定流程）。
```
⚠️ 兩支的失敗方向刻意相反（`§418`／`§519` 附近的註解自己就寫著這個
對照），本檔各驗一次，不要合併成一題——合併的話少一段會被另一段稀釋。

# ⚙️ 觀測點：直接打 API，不呼叫 `_chain_tiers()`／`approval_done()` 本身

種一張**真的**傳票（`POST /api/vouchers`），直接把 `approval_json` 改成
壞掉的 JSON 字串，再打對應的既有端點——驗下游，不驗中間。

# ✅ 牙齒已驗證（方式：突變驗證／live，非常設）

monkeypatch `helpers.voucher._chain_tiers`，讓它在解析失敗時回 `[]`
（模擬修復被回退成「解析失敗當沒有簽核鏈」，這是 EM5 描述的真實失效
模式，不是改斷言）：
① 匯出閘門那題從「擋下來、訊息說讀不出來」變成「依內建兩格判斷還差誰
   簽」——訊息不再含「讀不出來」，**真的紅**。
② 版面那題的 `signatures` 不再出現「簽核資料無法讀取」那一格，改成
   內建兩格（覆核／主管），**真的紅**。
正對照（`approval_json` 為 `None`／空字串，本來就该回 `[]`）在同一個
monkeypatch 下**不受影響、仍是綠的**——證明這道守門分辨得出「沒有鏈」
與「鏈讀不出來」是兩種不同的成因，不是被同一次突變一起撞倒。

# 🔴🔴 寫題過程中發現的真缺陷（非測試錯誤，未修，已回報）

`GET /api/vouchers/{id}`（`routers/vouchers.py:400 read_voucher()`）在
同一個請求裡**用了兩套獨立的 `approval_json` 解析**：

```
data = get_voucher(conn, voucher_id)   # 內部呼叫 signatures_of()
                                        # 解析失敗 -> 內部接住，
                                        # data["signatures"] 印出
                                        # 「簽核資料無法讀取」，正常回傳
appr = _appr_of(row)                   # `routers/vouchers.py:153`，
                                        # 一支獨立、沒有共用 `_chain_tiers()`
                                        # 的解析——解析失敗直接
                                        # raise HTTPException(400, ...)
```
`_appr_of()` **晚於** `get_voucher()` 執行，它一 raise，整個 request 連
`data` 都送不出去——`signatures_of()` 精心設計、docstring 裡明講理由
的 fail-open（「版面壞掉不該讓整張單讀不出來」）**被同一支端點裡的另一
支解析器搶先擋死**，使用者連單子的分錄、金額都看不到，只會看到一個
400。

實測：`_set_approval_json(vid, "{not valid json")` 後打
`GET /api/vouchers/{vid}`，回應是
`400 {"detail":"這張傳票的簽核資料格式不正確，無法繼續簽核。"}`（來自
`_appr_of()`），不是 200 帶著 `signatures.簽核資料無法讀取`。已用
monkeypatch 繞過 `_appr_of()` 單獨驗證：拿掉它之後 `signatures_of()`
的 fail-open 行為本身是對的（200、`簽核資料無法讀取` 正確出現）——
壞的只有 `_appr_of()` 這一支擋在前面。

⇒ 下面兩題**照使用者期望的行為（fail-open、印出讀不出來那一格）寫
`xfail(strict=True)`**——這是本檔既有慣例（見 `test_system_audit_
2026_09_14.py:326`）：追蹤一個已知、未修的缺陷，且**不是永久豁免**，
`routers/vouchers.py::_appr_of()` 改成不再擋住整個回應（或改用共用
的 `_chain_tiers()`／`VoucherChainUnreadable`）之後就要拿掉這個標記。
本檔不改 `_appr_of()`——這是產品碼，不是我的範圍，已回報 A／A-2。
"""
import json

import pytest

PDF = "/api/vouchers/%s/pdf-download"
DETAIL = "/api/vouchers/%s"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr):
    r = client.post("/api/vouchers", headers=hdr,
                     json={"summary": "EM5簽核鏈解析失敗測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _set_approval_json(vid, raw):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE vouchers_all SET approval_json = ? WHERE id = ?",
                     (raw, vid))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 匯出閘門：解析失敗要擋下來，且訊息說得出是「讀不出來」不是「還沒簽」
# ══════════════════════════════════════════════════════════════════════

def test_em5_export_is_blocked_when_the_chain_is_unreadable_not_just_unsigned(
        client, make_user):
    """🔴🔴 **`approval_json` 壞掉時，匯出要擋下來，且訊息要說得出是
    「讀不出來」——不能跟「還沒簽到」共用同一句話。**"""
    _u, hdr = _hdr(client, make_user, "em5_export_bad")
    vid = _create(client, hdr)
    _set_approval_json(vid, "{not valid json")

    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 400, (
        "簽核鏈解析失敗的傳票，匯出回 %s，不是 400：%s"
        % (r.status_code, r.text[:200]))
    assert "讀不出來" in r.text, (
        "訊息是 %r——沒有說出『讀不出來』，可能落到了『還沒簽到第幾關』"
        "那個分支，而那是兩種不同的成因。" % r.text[:200])


def test_em5_export_negative_control_no_chain_at_all_is_the_unsigned_message(
        client, make_user):
    """⚙️ **正對照：完全沒有 `approval_json`（沒設定流程）是另一種合法
    狀態——擋下來的訊息是「還沒簽到」，不是「讀不出來」。**

    ⚠️ 兩題的訊息必須不同，否則上一題就算 400 對了，也證明不了它是
    因為「解析失敗」而不是巧合落在同一個分支。
    """
    _u, hdr = _hdr(client, make_user, "em5_export_nochain")
    vid = _create(client, hdr)
    # `POST /api/vouchers` 建出來的新單本來就沒有簽核鏈，不用額外處理。

    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 400, r.text[:200]
    assert "讀不出來" not in r.text, (
        "沒有簽核鏈的單，訊息卻出現『讀不出來』：%r——"
        "跟上一題（真的解析失敗）分不出來了。" % r.text[:200])
    assert "還差" in r.text, (
        "沒有簽核鏈時應該是『還差覆核／主管簽核』那類訊息，實際是 %r。"
        % r.text[:200])


# ══════════════════════════════════════════════════════════════════════
# ② 版面：解析失敗要在 signatures 印出一格「讀不出來」，不是安靜退回內建格
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(
    strict=True,
    reason="真缺陷：routers/vouchers.py::_appr_of() 在 read_voucher() 裡"
           "搶在 signatures_of() 的 fail-open 之前 raise HTTPException(400)，"
           "整個 GET 連分錄都讀不到。見本檔頂端『寫題過程中發現的真缺陷』。"
           "已回報，未修——修好後移除這個標記。")
def test_em5_the_detail_view_shows_the_chain_is_unreadable_not_the_builtin_two_tiers(
        client, make_user):
    """🔴🔴 **`GET /api/vouchers/{id}` 的 `signatures` 在鏈解析失敗時要
    出現「簽核資料無法讀取」這一格，不能安靜退回內建覆核／主管兩格。**

    ☠️ 退回內建兩格的話，畫面看起來像「這張單沒設定簽核流程」——而它其實
    是「設定過，但讀不出來」，兩者對使用者的意義完全不同。

    🔴 目前實際行為：整支端點回 400（見 `_appr_of()`），連這個判斷都
    走不到——這題現在是 `xfail`，釘的是**應該要有**的行為。
    """
    _u, hdr = _hdr(client, make_user, "em5_detail_bad")
    vid = _create(client, hdr)
    _set_approval_json(vid, "{not valid json")

    r = client.get(DETAIL % vid, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    sigs = r.json().get("signatures") or {}
    assert "簽核資料無法讀取" in sigs, (
        "簽核鏈解析失敗，但 `signatures` 是 %r——沒有那一格，畫面上會"
        "看起來像一張正常沒設定流程的單。" % sigs)


def test_em5_detail_negative_control_no_chain_shows_the_builtin_two_tiers(
        client, make_user):
    """⚙️ **正對照：完全沒有 `approval_json` 時，`signatures` 走內建
    覆核／主管兩格——那是正確行為，不要被上一題誤導成「一律要印讀不出來」。**
    """
    _u, hdr = _hdr(client, make_user, "em5_detail_nochain")
    vid = _create(client, hdr)

    r = client.get(DETAIL % vid, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    sigs = r.json().get("signatures") or {}
    assert "簽核資料無法讀取" not in sigs, (
        "沒有簽核鏈的單，`signatures` 卻出現『簽核資料無法讀取』：%r。" % sigs)
    assert "覆核" in sigs and "主管" in sigs, (
        "沒有簽核鏈時應該看到內建的覆核／主管兩格，實際是 %r。" % sigs)
