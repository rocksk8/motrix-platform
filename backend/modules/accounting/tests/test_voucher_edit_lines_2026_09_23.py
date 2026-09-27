# -*- coding: utf-8 -*-
"""`§181` · 改草稿要能**存到分錄**（`PUT /api/vouchers/{id}`）。

```
routers/vouchers.py:81  EDITABLE_FIELDS = ("voucher_date", "category", "summary")
update_voucher() 只 UPDATE `vouchers_all` 的那三欄，**完全沒有碰 voucher_lines**
```
☠️ 接上去的話，使用者改完金額按儲存會**回 200 而分錄原封不動**。
🔑 〈降級之後它還是會動〉：**壞掉會被報修，而「存了但沒存進去」不會** ——
   他下次打開看到舊數字，**會懷疑自己記錯了**。
⚠️ 而它落在最難察覺的位置：**新建那條路是好的**（`POST` 帶 `lines`），
   **只有第二次編輯會掉**。

# 🔴 ② 那一條比 ① 更容易被實作踩到

```
最自然的實作  刪掉舊 lines -> 重寫新的
而「沒帶 lines 的 PUT」若照樣走刪除那一步  =>  **分錄全沒了**
```
⇒ 那是比現在**更糟**的狀態：現在是存不進去，那時是**存進去而且清空**。

# ⚠️ 觀測點一律在下游

```
PUT 的回應      它自己說的話
GET 讀回來的     **成功之後才會被寫入的東西**
```
📌 `§103e`：編寫紀錄要**逐行 diff** —— 同一張被退兩次看不出來是財務不可接受。
"""
import pytest

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0,
           "summary": "原本的第一行"},
          {"account_code": "4111", "debit": 0, "credit": 1000,
           "summary": "原本的第二行"}]

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr, lines=None):
    r = client.post("/api/vouchers", headers=hdr, json={
        "summary": "測試用", "lines": lines or _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _get(client, hdr, vid):
    r = client.get("/api/vouchers/%s" % vid, headers=hdr)
    assert r.status_code == 200, "讀不回來：%s %s" % (r.status_code, r.text[:200])
    return r.json()


def _lines_of(v):
    got = v.get("lines")
    assert got is not None, (
        "讀回來的傳票裡沒有 `lines`：%s\n" % sorted(v)
        + "⚠️ 鍵名換了的話**退回給我**。")
    return got


def _put(client, hdr, vid, **body):
    r = client.put("/api/vouchers/%s" % vid, headers=hdr, json=body)
    if r.status_code in (404, 405, 422):
        pytest.fail("`PUT /api/vouchers/{id}` 走不到（回 %s）。" % r.status_code)
    assert r.status_code in OK_CODES, (
        "回 %s，不在 %s 裡：%s" % (r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _amounts(lines):
    """`[(科目, 借, 貸)]` —— 比對用的最小形狀。"""
    return [(l.get("account_code"), int(l.get("debit") or 0),
             int(l.get("credit") or 0)) for l in lines]


# ══════════════════════════════════════════════════════════════════════
# ① 改得進去
# ══════════════════════════════════════════════════════════════════════

def test_editing_a_draft_line_is_visible_on_the_next_read(client, make_user):
    """🔴 **改完分錄，下次讀回來要是新的。**

    ⚙️ 觀測點在 `GET`，不是 `PUT` 的回應 ——
       一支「回 200 而什麼都沒寫」的端點在回應那一層看不出來。
    ☠️ 而症狀不是錯誤：他下次打開看到舊數字，**會懷疑自己記錯了**。
    """
    _u, hdr = _hdr(client, make_user, "vl_edit")
    vid = _create(client, hdr)

    new = [{"account_code": "1113", "debit": 2500, "credit": 0,
            "summary": "改過的第一行"},
           {"account_code": "4111", "debit": 0, "credit": 2500,
            "summary": "改過的第二行"}]
    _put(client, hdr, vid, lines=new)

    got = _amounts(_lines_of(_get(client, hdr, vid)))
    assert got == _amounts(new), (
        "改完分錄，讀回來的還是舊的：\n  送出 %r\n  讀回 %r\n" % (_amounts(new), got)
        + "☠️ `PUT` 回 200 而 `voucher_lines` 原封不動 ——\n"
          "   **壞掉會被報修，而「存了但沒存進去」不會**。")


def test_a_put_that_does_not_mention_lines_must_not_wipe_them(client,
                                                              make_user):
    """🔴🔴 **只改摘要，分錄不可以被清掉。**

    ```
    最自然的實作   刪掉舊 lines -> 重寫新的
    而沒帶 lines 的 PUT 若照樣走刪除那一步  =>  **分錄全沒了**
    ```
    ⇒ 那比現在的狀態**更糟**：現在是存不進去，那時是**存進去而且清空**。
    ☠️ 而它一樣不報錯：單子還在、狀態還是草稿，**只是內容空了**。
    ⚙️ 這一題是上一題的反向控制：少了它，一個「每次 PUT 都先清空」的實作
       會讓上一題綠（它送了 lines，所以重寫得回來）。
    """
    _u, hdr = _hdr(client, make_user, "vl_keep")
    vid = _create(client, hdr)
    before = _amounts(_lines_of(_get(client, hdr, vid)))
    assert len(before) == 2, "前置就不對：建立時的分錄是 %r" % (before,)

    _put(client, hdr, vid, summary="只改這一行字")

    after = _amounts(_lines_of(_get(client, hdr, vid)))
    assert after == before, (
        "只改了摘要，而分錄變了：\n  改前 %r\n  改後 %r\n" % (before, after)
        + "☠️ 「刪舊寫新」的實作在**沒帶 lines** 時會把分錄清光 ——\n"
          "   單子還在、狀態還是草稿，**只是內容空了**。")


def test_sending_an_empty_line_list_really_clears_them(client, make_user):
    """🔴 **`lines: []` 是「清空」，而「沒提到 lines」是不要動它。**

    ⚙️ 這是上一題的**另一半**。兩題合起來才釘得住那個判斷：
    ```
    "lines" in body（鍵在不在）  => lines:[] 清空 ✅ ／ 沒帶 不動 ✅
    body.get("lines") 的真假值   => lines:[] 被當成「沒帶」 ☠️ **清不掉**
    ```
    ☠️ 少了這一題，一個用真假值判斷的實作會讓上一題綠 ——
       而使用者刪光分錄按儲存，**舊的分錄還在**。
    📌 〈null 不等於 0〉在這裡的形狀：**空清單與「沒有這個鍵」是兩件事**。
    """
    _u, hdr = _hdr(client, make_user, "vl_clear")
    vid = _create(client, hdr)
    assert len(_lines_of(_get(client, hdr, vid))) == 2, "前置不對。"

    _put(client, hdr, vid, lines=[])

    after = _lines_of(_get(client, hdr, vid))
    assert after == [], (
        "送了 `lines: []` 而分錄還在：%r\n" % (_amounts(after),)
        + "☠️ 判斷用了**值的真假**而不是**鍵在不在** ——\n"
          "   使用者刪光分錄按儲存，舊的還在，而畫面沒說任何話。")


def test_the_edit_log_says_which_line_and_which_field_changed(client,
                                                              make_user):
    """🔴 **編寫紀錄要逐行**：哪一行的哪一個欄位，由 A 變 B。（`§103e`）

    ☠️ 整包記一筆的後果：**同一張被退兩次，看不出來第二次改了什麼** ——
       而那在財務上不可接受。
    ⚠️ 我不釘 `changes_json` 的結構，只釘**它答得出那三個問題**：
    ```
    ① 是哪一行      行號／`line_no`／科目代號，三者之一
    ② 是哪一個欄位  `field`（`validate_changes()` 本來就強制）
    ③ 由什麼變什麼  `from` 與 `to`
    ```
    📌 `validate_changes()` 已經強制 ①③ 之中的 `field` 與 `from`
       ⇒ 這一題真正新增的是 **①：那一筆要指得出是哪一行**。
    """
    import json

    _u, hdr = _hdr(client, make_user, "vl_log")
    vid = _create(client, hdr)
    _put(client, hdr, vid, lines=[
        {"account_code": "1113", "debit": 7777, "credit": 0,
         "summary": "原本的第一行"},
        {"account_code": "4111", "debit": 0, "credit": 7777,
         "summary": "原本的第二行"}])

    import db
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM voucher_edit_log WHERE voucher_id = ?"
            " ORDER BY id", (vid,))]
    finally:
        conn.close()

    assert rows, (
        "改了分錄而 `voucher_edit_log` 一列都沒有 ——\n"
        + "☠️ 那張單改過什麼**沒有任何地方答得出來**。")

    blob = " ".join(r.get("changes_json") or "" for r in rows)
    changes = []
    for r in rows:
        try:
            changes += json.loads(r.get("changes_json") or "[]")
        except ValueError:
            pytest.fail("`changes_json` 不是合法的 JSON：%r" % r.get("changes_json"))

    assert any("7777" in str(c) for c in changes), (
        "編寫紀錄裡找不到改成 7777 那一筆：%r\n" % (changes,)
        + "⚠️ 若金額被記成別的形狀（例如分），**退回給我**。")
    assert any(
        ("line" in str(c.get("field", "")).lower()
         or "1113" in str(c)
         or c.get("line_no") is not None
         or c.get("line") is not None)
        for c in changes), (
        "編寫紀錄答不出**是哪一行**：%r\n" % (changes,)
        + "☠️ 整包記一筆的話，同一張被退兩次**看不出來第二次改了什麼**。\n"
        + "📌 找過 `field` 含 line／科目代號出現在內容裡／`line_no`／`line` 四種。\n"
        + "⚠️ 用別的形狀表達「哪一行」的話**退回給我**改這一題。")
    assert "from" in blob or "old" in blob, (
        "編寫紀錄沒有改前值：%r\n" % (changes,)
        + "📌 `validate_changes()` 本來就強制它 —— 這裡是確認那條路真的走到了。")


# ══════════════════════════════════════════════════════════════════════
# ② 界線：不是草稿就不可以改
# ══════════════════════════════════════════════════════════════════════

def test_lines_cannot_be_edited_once_it_left_draft(client, make_user):
    """🔴 **送審之後不可以再改分錄。**

    ⚙️ 這一題擋的是「把 `lines` 加進 `PUT`」時最容易一起鬆掉的那一格：
    ```
    原本  PUT 只改三個欄位，而那三個欄位本來就只有草稿能改
    加了 lines 之後 => **要記得分錄也受同一道狀態閘管**
    ```
    ☠️ 少了它：一張**已核准**的傳票，金額可以被改掉而簽名格還在 ——
       版面上看起來是三個人簽過的那一張。
    """
    _u, hdr = _hdr(client, make_user, "vl_state")
    vid = _create(client, hdr)
    assert client.post("/api/vouchers/%s/submit" % vid,
                       json={}, headers=hdr).status_code == 200

    before = _amounts(_lines_of(_get(client, hdr, vid)))
    r = _put(client, hdr, vid, lines=[
        {"account_code": "1113", "debit": 9, "credit": 0},
        {"account_code": "4111", "debit": 0, "credit": 9}])
    assert r.status_code >= 400, (
        "送審之後還改得動分錄（回 %s）——\n" % r.status_code
        + "☠️ 一張已簽過的傳票，金額被改掉而簽名格還在。")
    after = _amounts(_lines_of(_get(client, hdr, vid)))
    assert after == before, (
        "被擋下來了，而分錄已經被改掉了：\n  改前 %r\n  改後 %r\n" % (before, after)
        + "🔑 拒絕的路徑上不可以留下副作用。")


def test_a_draft_may_still_be_saved_unbalanced(client, make_user):
    """⚙️ **反向控制：草稿仍然可以存成不平衡的。**

    ```
    §六  草稿允許不平衡；借貸平衡是**過帳**那一關的事
    ```
    ☠️ 少了這一題，上面幾題可以靠「PUT 一律要求平衡」變綠 ——
       而那會讓使用者**打到一半存不了檔**（他本來就是打到一半）。
    """
    _u, hdr = _hdr(client, make_user, "vl_unbal")
    vid = _create(client, hdr)

    lopsided = [{"account_code": "1113", "debit": 500, "credit": 0},
                {"account_code": "4111", "debit": 0, "credit": 123}]
    r = _put(client, hdr, vid, lines=lopsided)
    assert r.status_code == 200, (
        "草稿存成不平衡的被擋掉了（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 使用者**打到一半就存不了檔** —— 而他本來就是打到一半。\n"
        + "📌 借貸平衡是**過帳**那一關的事（`§六`）。")
    assert _amounts(_lines_of(_get(client, hdr, vid))) == _amounts(lopsided)


# ══════════════════════════════════════════════════════════════════════
# ③ `AC1`：畫面那一半
# ══════════════════════════════════════════════════════════════════════

def test_the_page_actually_sends_the_lines_when_saving(client, make_user):
    """🔴 **儲存那一段要把 `lines` 送出去。**（`AC1`）

    ☠️ 後端支援了而前端沒送的話，症狀與現在**一模一樣**：
       回 200、單子還在、而分錄沒變 ⇒ 那是換了一個地方的同一個缺陷。
    ⚠️ 判準是「`PUT` 的 body 裡有 `lines`」，不是「檔案裡有 `lines` 這個字」——
       前者是**會送出的那一個動作**（`AC1` 條文）。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[4]
    js = (root / "frontend" / "js" / "voucher.js").read_text(
        encoding="utf-8", errors="replace")

    puts = [m for m in re.finditer(r"method:\s*'PUT'", js)]
    assert puts, (
        "`voucher.js` 裡沒有任何 `PUT` —— 改草稿那條路還沒接。")

    ok = False
    for m in puts:
        chunk = js[m.start():m.start() + 600]
        if re.search(r"\blines\b", chunk):
            ok = True
            break
    assert ok, (
        "`voucher.js` 的 `PUT` **沒有送 `lines`** ——\n"
        + "☠️ 後端支援了而前端沒送的話，症狀與現在一模一樣：\n"
          "   回 200、單子還在、**而分錄沒變**。\n"
        + "⚠️ 我只看 `PUT` 呼叫後面 600 字元內有沒有 `lines`；\n"
          "   body 是另外組出來的話**退回給我**改這一題的觀測點。")


def test_the_page_no_longer_tells_the_user_to_void_and_reopen(client,
                                                              make_user):
    """🔴 **那句「請先作廢再重開」要拿掉。**

    ```
    voucher.js  「分錄的修改目前還不能儲存（後端的修改端點尚未支援分錄）。
                  … 若要改分錄，請先作廢這張單再重開一張。」
    ```
    📌 那句話**現在是誠實的**（後端真的不支援）——
       B 寫它是對的，總比按下去無聲不存好。
    ☠️ 而它留到後端支援之後就變成**一句過期的謊**：功能好了，
       使用者仍然被叫去作廢重開，**而重開會產生一張 `-Rn` 的新單號**。
    ⚙️ 這一題是「暫時性訊息」的到期日 —— 沒有它，那句話會活很久。
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[4]
    js = (root / "frontend" / "js" / "voucher.js").read_text(
        encoding="utf-8", errors="replace")

    assert "尚未支援分錄" not in js, (
        "`voucher.js` 還留著「後端的修改端點尚未支援分錄」那句話 ——\n"
        + "☠️ 後端支援之後它就是一句**過期的謊**：使用者被叫去作廢重開，\n"
          "   **而重開會產生一張 `-Rn` 的新單號**。\n"
        + "📌 若後端還沒支援，這一題紅是**正確的**：它在等那一件事。")
