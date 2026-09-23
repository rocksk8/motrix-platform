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

# 🟢 2026-09-23 `JV27` 已修（B，`a40504e`）——下面兩段是最終落地的形狀

寫題時發現的真缺陷（`GET /api/vouchers/{id}` 曾經被 `_appr_of()` 搶先
擋死整個回應）已由 B 修好，方法是把**讀**與**簽核**兩個呼叫端徹底拆開，
而不是讓其中一個借用另一個：

```
helpers/voucher.py::parse_approval_json()   共用的解析（唯一一份 json.loads）

routers/vouchers.py::_appr_of()             簽核動作專用，疊在 parse_approval_json
  用於 approve_voucher()                    上——解析失敗 raise HTTPException(400)
                                             （fail-closed：讀不出鏈就不可以放行）

read_voucher() 自己接 parse_approval_json() 讀取專用——解析失敗時退回
  的 VoucherChainUnreadable，不借      _UNREADABLE_APPR（fail-open：
  _appr_of()                          版面壞掉不該讓整張單讀不出來），
                                       塞進回應的 `approval` 欄位
```
🔑 **同一份資料，兩個呼叫端要的失效方向相反**：讀是 fail-open（分錄、
附件、`signatures` 裡的「簽核資料無法讀取」照樣要看得到），簽核是
fail-closed（讀不出鏈就必須擋下來，不能猜著簽）。那支「重複實作」
不是純粹的冗餘——它存在是因為兩個呼叫端本來就要不同的行為，原本的
錯是**讀的那一側錯借了簽核那一側的函式**。

⇒ 本檔下面：
```
① 匯出閘門（approval_done()）  fail-closed，已驗證（見上面兩題）
② 版面（read_voucher()）       fail-open，已驗證（見下面兩題，xfail 已拿掉）
③ 簽核動作（approve_voucher()）fail-closed，**新補**——JV27 把讀寫拆開後
   這一格是新產生的必要守門：若有人「順手」把簽核那側也改成 fail-open，
   ②會照樣綠，而那是一個放行未簽核傳票的洞，比①②都更值得優先守。
```
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

def test_em5_the_detail_view_shows_the_chain_is_unreadable_not_the_builtin_two_tiers(
        client, make_user):
    """🔴🔴 **`GET /api/vouchers/{id}` 在鏈解析失敗時要 fail-open：狀態碼
    200、分錄與附件照樣讀得到、`signatures` 印出「簽核資料無法讀取」、
    `approval.unreadable` 為 `True`。**

    ☠️ 退回內建兩格的話，畫面看起來像「這張單沒設定簽核流程」——而它其實
    是「設定過，但讀不出來」，兩者對使用者的意義完全不同。

    🟢 `JV27`（B，`a40504e`）修好之後這題不再是 `xfail`：`read_voucher()`
    改接 `parse_approval_json()` 自己處理 `VoucherChainUnreadable`，不再
    借用簽核動作專用、fail-closed 的 `_appr_of()`。
    """
    _u, hdr = _hdr(client, make_user, "em5_detail_bad")
    vid = _create(client, hdr)
    _set_approval_json(vid, "{not valid json")

    r = client.get(DETAIL % vid, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("lines"), (
        "簽核鏈解析失敗，連分錄都讀不到了：%r——\n" % body
        + "☠️ 這正是修好之前的真缺陷：讀取端不該因為一筆壞掉的簽核資料"
          "連帶讀不到分錄與附件。")
    sigs = body.get("signatures") or {}
    assert "簽核資料無法讀取" in sigs, (
        "簽核鏈解析失敗，但 `signatures` 是 %r——沒有那一格，畫面上會"
        "看起來像一張正常沒設定流程的單。" % sigs)
    approval = body.get("approval") or {}
    assert approval.get("unreadable") is True, (
        "`approval.unreadable` 是 %r，應該是 `True`。" % approval.get("unreadable"))


def test_em5_detail_negative_control_no_chain_shows_the_builtin_two_tiers(
        client, make_user):
    """⚙️ **正對照：完全沒有 `approval_json` 時，`signatures` 走內建
    覆核／主管兩格——那是正確行為，不要被上一題誤導成「一律要印讀不出來」。**
    """
    _u, hdr = _hdr(client, make_user, "em5_detail_nochain")
    vid = _create(client, hdr)

    r = client.get(DETAIL % vid, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    sigs = body.get("signatures") or {}
    assert "簽核資料無法讀取" not in sigs, (
        "沒有簽核鏈的單，`signatures` 卻出現『簽核資料無法讀取』：%r。" % sigs)
    assert "覆核" in sigs and "主管" in sigs, (
        "沒有簽核鏈時應該看到內建的覆核／主管兩格，實際是 %r。" % sigs)
    assert not (body.get("approval") or {}).get("unreadable"), (
        "沒有簽核鏈的單，`approval.unreadable` 卻是真值：%r。"
        % body.get("approval"))


# ══════════════════════════════════════════════════════════════════════
# ③ 簽核動作：approve_voucher() 解析失敗要 fail-closed（JV27 新產生的守門）
# ══════════════════════════════════════════════════════════════════════

def test_em5_approving_is_blocked_when_the_chain_is_unreadable(
        client, make_user):
    """🔴🔴 **`POST /api/vouchers/{id}/approve` 在鏈解析失敗時必須拒絕
    （fail-closed），不可以猜著放行。**

    🔑 `JV27` 把讀與簽核兩個呼叫端拆開之後，這一格是**新產生**的必要
    守門：`read_voucher()` 現在正確地 fail-open 了，若有人「順手」把
    `approve_voucher()` 也改成一樣寬鬆，這裡才是唯一擋得住「放行一張
    未簽核完成的傳票」的地方——比①②都更值得優先看住。

    ⚙️ 前置：先送審（此時 `approval_json` 還是合法的），再弄壞它，
    確保 400 是因為「讀不出鏈」，不是因為「傳票不在簽核流程裡」那個
    更早的狀態檢查（草稿直接 approve 本來就會 400，但理由不一樣）。
    """
    _u, hdr = _hdr(client, make_user, "em5_approve_bad")
    vid = _create(client, hdr)
    r = client.post("/api/vouchers/%s/submit" % vid, headers=hdr)
    assert r.status_code == 200, "送審失敗，前置不成立：%s" % r.text[:200]
    _set_approval_json(vid, "{not valid json")

    r = client.post("/api/vouchers/%s/approve" % vid, headers=hdr)
    assert r.status_code == 400, (
        "簽核鏈解析失敗的傳票，簽核動作回 %s，不是 400：%s"
        % (r.status_code, r.text[:200]))
    assert "不在簽核流程裡" not in r.text, (
        "訊息是 %r——落到了『狀態不在流程裡』那個分支，代表這筆請求"
        "根本沒有走到簽核鏈解析那一步，前置沒有真的成立。" % r.text[:200])


def test_em5_approve_negative_control_a_readable_chain_can_still_be_approved(
        client, make_user):
    """⚙️ **正對照：簽核鏈讀得出來時，簽核動作照樣放行——不要被上一題
    誤導成「approve 一律擋」。**"""
    _u, hdr = _hdr(client, make_user, "em5_approve_ok")
    vid = _create(client, hdr)
    r = client.post("/api/vouchers/%s/submit" % vid, headers=hdr)
    assert r.status_code == 200, r.text[:200]

    r = client.post("/api/vouchers/%s/approve" % vid, headers=hdr)
    assert r.status_code == 200, (
        "簽核鏈讀得出來（沒有損壞）的傳票，簽核卻被拒絕：%s %s"
        % (r.status_code, r.text[:200]))
