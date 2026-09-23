# -*- coding: utf-8 -*-
"""`JV20` · 傳票不需要「類別」選項。

使用者原話：「傳票不需要有類別的選項」。

# 🔴 動工前查證：A 給的 `③`（T100 匯出仍要有值）**前提查不到**

A 的原始判斷：「拿掉的是畫面上的選項，不是那個欄位」，並指出
`accounting_export.py:441` 的 `row["category"]` 會被寫進 T100 匯出檔，
要求驗收釘「T100 匯出那一欄不可以變空」。

## ⚙️ 動工時追這條線，追不到 `vouchers_all.category` 上

```
accounting_export.py:441 的 row["category"]
  ⇐ _build_t100_voucher_excel(rows, …)
  ⇐ rows = _flatten_events_for_excel(events)
  ⇐ events = _collect_t100_events(start, end)
       —— 這支從**發票收款／承攬商已匯款／已付款進貨**組事件，
          每一行的 category 來自 cfg["voucherCategory"]
          （T100 設定頁的一個**常數**），不是任何一張憑證自己的欄位
grep -c "vouchers_all" routers/accounting_export.py  =>  **0**
```
⇒ `routers/accounting_export.py` 整份檔案**完全沒有引用** `vouchers_all`
（本檔一直在測的手動傳票表）。`voucher.html` 的「類別」`<select>`
寫的是 `vouchers_all.category`，與 T100 匯出裡印出來的「傳票別」欄位
**是兩個不相干的資料來源**——後者今天固定讀 T100 設定的
`voucherCategory`，不管 `vouchers_all.category` 是什麼值都不會變。

⇒ **本檔不寫 `③` 那一題**——它驗的連結今天不存在，寫了也是一句對
不上受測物的空話。已回報 A，A 確認自己的前提錯了（看到 `row["category"]`
這個欄位名就推論它來自 `vouchers_all`，沒有去查它實際來自哪一張表）
並撤回這條驗收；`③`（依分錄自動判斷現收／現付／轉）連帶暫停——
「做一個沒有消費端的東西，等於做一個沒有人會發現它壞掉的東西」。

## 📌 暫停前查過的兩件事，**留著待日後 T100 真的接上手動傳票時用**

```
① 怎麼認「現金／銀行科目」——不能用科目名稱圈（CA1 允許使用者自訂
   科目名稱，名字像「零用金」的自訂科目會被漏掉或誤中）。正確判準是
   **structure**：官方《商業會計項目表》三級「111 現金及約當現金」，
   下轄四級 1111~1115（庫存現金／零用金週轉金／銀行存款／在途現金／
   約當現金）。判準＝「這個 code 沿 `parent_code` 逐層往上走，會不會
   走到 111」——`db.py:4182-4192` 已經警告過 code **前綴**不可信
   （"111".startswith("11-12") 為 False，二級是範圍代號），一定要走
   `parent_code` 欄位，使用者自訂科目掛在 111 底下時會自動涵蓋，
   不必另外處理。
② 借貸兩邊都是現金／銀行科目 **是可達狀態，不是純理論**：開發機當下
   2 張有分錄的傳票裡就有 1 張借貸兩邊都在 111 家族（1111 借／1112
   貸）。⚠️ 但那筆是先前測試留下的資料，只能證明「系統結構上沒有擋
   這件事」，**不能證明使用者真的這樣用過**（例如銀行轉存到另一個
   銀行）——這個區分很重要：日後真的要做自動判斷時，這一格的值
   （算「現付」「現收」還是第三種）仍然要 A 裁，不是查資料庫查得出來。
```

# ⚙️ 其餘四格都查證過，如常寫

```
① voucher.html:224-225 的 <select x-model="category"> 要拿掉，
   不要換成唯讀文字框——使用者說「不需要」，不是「不能改」
② 新建傳票 category 仍寫 '轉'（vouchers.py:202，body.get("category")
   缺席時的預設值，今天已經是這樣——前端不送這個欄位之後不必改任何
   後端邏輯，這一題是**鎖住現有行為**，不是要求新行為）
④ 作廢重開（vouchers.py:698，src.get("category") or "轉"）同一條路
⑤ EDITABLE_FIELDS 若把 "category" 拿掉，送舊 payload（含 category）
   不可以 400——vouchers.py:807 的迴圈本來就是走
   `for field in EDITABLE_FIELDS`，body 裡多餘的鍵**天然被忽略**，
   這一題同樣是鎖住現有行為，等 EDITABLE_FIELDS 真的被改動時當
   迴歸守門
```
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
         {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _row(vid):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                         (vid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 畫面上不可以再有類別選項
# ══════════════════════════════════════════════════════════════════════

def test_jv20_the_category_selector_is_removed_from_the_page():
    """🔴🔴 **核心：`voucher.html` 不可以再有類別的 `<select>`。**

    ⚠️ 也不可以換成唯讀文字框——使用者說的是「不需要有類別的選項」，
    不是「不能讓使用者改」，換成唯讀等於把使用者沒要求的東西留在畫面上。
    """
    html = (ROOT / "frontend" / "pages" / "voucher.html").read_text(
        encoding="utf-8", errors="replace")
    assert 'x-model="category"' not in html, (
        "`voucher.html` 裡還找得到 `x-model=\"category\"` —— "
        "類別欄位還在畫面上。")
    assert "類別" not in html, (
        "`voucher.html` 裡還找得到「類別」這兩個字——\n"
        "☠️ 若只拿掉 `<select>` 而把標籤文字換成別的形式（例如唯讀文字），\n"
          "   那不是使用者要的：他說的是不需要這個選項，不是不能改。")


# ══════════════════════════════════════════════════════════════════════
# ② 新建傳票仍然寫入 '轉'（鎖住現有預設值行為）
# ══════════════════════════════════════════════════════════════════════

def test_jv20_creating_without_category_still_stores_the_default(client,
                                                                  make_user):
    """⚙️ **鎖住現有行為：不送 `category` 時，資料庫仍然存 `'轉'`。**

    ⚠️ 這一題**今天就是綠的**（`vouchers.py:202` 的預設值本來就是這樣）
    ——它的價值在**畫面拿掉選項之後**：前端不會再送這個欄位，這一題
    確保「不送」這個新常態不會意外讓資料庫存進空字串或 `None`。
    """
    _u, hdr = _hdr(client, make_user, "jv20_create")
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "JV20 測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    vid = r.json()["id"]
    row = _row(vid)
    assert row is not None, "建立成功卻讀不到那一列。"
    assert row["category"] == "轉", (
        "新建的傳票 `category` 是 %r，預期 `'轉'`。" % row["category"])


# ══════════════════════════════════════════════════════════════════════
# ④ 作廢重開也走同一條預設值路徑
# ══════════════════════════════════════════════════════════════════════

def test_jv20_void_and_reopen_still_stores_the_default(client, make_user):
    """🔴 **作廢重開（`vouchers.py:698`）是另一條寫入路徑，也要有值。**

    ⚙️ 觀測點：作廢原單，走 `reopen=True`，讀**新單**的 `category`。
    """
    _u, hdr = _hdr(client, make_user, "jv20_reopen")
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "JV20 重開測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    vid = r.json()["id"]

    v = client.post("/api/vouchers/%s/void" % vid, headers=hdr,
                    json={"reason": "測試作廢重開", "reopen": True})
    assert v.status_code == 200, "作廢重開失敗：%s %s" % (v.status_code,
                                                     v.text[:200])
    new_id = v.json().get("new_id")
    assert new_id, "作廢重開成功卻沒有回 `new_id`：%r" % v.json()

    row = _row(new_id)
    assert row is not None, "重開的新單讀不到。"
    assert row["category"] == "轉", (
        "重開的新單 `category` 是 %r，預期 `'轉'`。" % row["category"])


# ══════════════════════════════════════════════════════════════════════
# ⑤ 舊 payload（含 category）仍然可以送，不會 400
# ══════════════════════════════════════════════════════════════════════

def test_jv20_a_stale_payload_with_category_does_not_break_the_put(client,
                                                                    make_user):
    """🔴 **使用者瀏覽器可能還快取著舊的 JS**——送含 `category` 的 PUT 不可以炸。

    ⚙️ 觀測點在**今天**的行為：`vouchers.py:807` 的更新迴圈走
    `for field in EDITABLE_FIELDS`，body 裡多出來的鍵天然被忽略——
    這一題鎖住這個行為，等 `EDITABLE_FIELDS` 真的被改動（拿掉
    `"category"`）時當迴歸守門，不必等到那時候才發現舊前端會把使用者
    卡住。
    """
    _u, hdr = _hdr(client, make_user, "jv20_stale")
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "JV20 舊格式測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    vid = r.json()["id"]

    put = client.put("/api/vouchers/%s" % vid, headers=hdr,
                     json={"summary": "改過的摘要", "category": "收"})
    assert put.status_code == 200, (
        "送舊格式的 PUT（含 `category`）回 %s（預期 200）：%s\n"
        % (put.status_code, put.text[:200])
        + "☠️ 使用者的瀏覽器可能還快取著舊的 `voucher.js`，\n"
          "   若這裡炸掉，他會被卡在一個存不了檔的畫面。")
