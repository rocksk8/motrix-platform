# -*- coding: utf-8 -*-
"""`JV5` · 傳票 PDF 匯出（含附件合併）。`docs/windows/SPEC-JV5-PDF.md §7`。

```
GET /api/vouchers/{id}/pdf-download                      只有本體
GET /api/vouchers/{id}/pdf-download?with_attachments=1   本體 ＋ 附件
```

# 🔴 `§5` 是這一份的核心：**附件的實體檔遺失時，匯出「不拒絕」**

```
JV3 帶入  **寫入** —— 建立「這張傳票有這份憑證」的主張
          部分成功 => 留下一句謊 => **整批拒絕 400 是對的**
JV5 匯出  **唯讀** —— 不改變任何主張，只把既有的印出來
  ❌ 整批拒絕 => 一份法定要保存 5 年的憑證因為一個附件印不出來（商業會計法 §38）
  ❌ 靜默略過 => 使用者拿到一份**看起來完整**的 PDF ⇒ **比印不出來更糟**
  ✅ 把缺口印出來：最後加一頁列出未併入的附件
```
🔑 **一個唯讀動作拒絕執行，擋住的是使用者；靜默略過，騙的是使用者。**
☠️ `§7④` 逐字：**它紅而其他全綠 ＝ 沒做到。**

# ⚠️ ②③ 要**數頁數**，不要只驗「檔案非空」

```
總頁數 == 1 + 圖片附件數 + 各 PDF 附件的頁數合計
```
☠️ 合併失敗最可能的樣子是「**只有本體那一頁**」——
   而它是一份**完全正常的 PDF**：非空、Content-Type 對、打得開。
⇒ 只驗那三件一律會綠。

# ⚠️ 逾時會變成「一份 0 byte 的 PDF」

```
helpers/startup.py  run_edge_pdf **吞掉逾時不丟例外**（docstring 逐字）
⇒ 靠呼叫端緊接的「tmp_pdf 沒產出或 0 byte 就 raise」報錯
⇒ B 若忘了抄那道檢查，**逾時 = 回一份 0 byte 的 PDF**
```
⇒ 所以 ① 一定要驗**位元組數 > 0**。
"""
import io
import pathlib

import pytest

PDF = "/api/vouchers/%s/pdf-download"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]

#: 最小的合法單頁 PDF（用來當「PDF 附件」）。
_ONE_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n")


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr):
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "匯出測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _reached(r, what):
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`%s` 走不到（回 %s）。\n" % (what, r.status_code)
            + "📌 `§166`：未實作端點在這個 repo 有三種臉 —— 404／405／**422**。\n"
            + "⚠️ 路徑是 `§1` 定案的（沿用 `quotations`／`payslips`／"
              "`invoice_vouchers` 六處同一個形狀），改了**退回給我**。")
    assert r.status_code in OK_CODES, (
        "`%s` 回 %s，不在 %s 裡：%s"
        % (what, r.status_code, list(OK_CODES), r.content[:120]))
    return r


def _export(client, hdr, vid, with_attachments=False):
    url = PDF % vid + ("?with_attachments=1" if with_attachments else "")
    return _reached(client.get(url, headers=hdr), "GET " + PDF % "{id}")


def _page_count(body):
    """PDF 頁數。

    ⚠️ 不用 `pypdf` —— **它是 `JV5` 的相依，而這一題不可以相依於受測物的相依**：
       pypdf 沒裝的話這一題會 error，而那與「合併壞了」長得不一樣，
       但兩者都會讓我去看錯的地方。
    🔑 `/Type /Page` 的出現次數是 PDF 結構層的事實，數得出來。
    """
    import re
    return len(re.findall(rb"/Type\s*/Page[^s]", body))


def _attach(client, hdr, vid, name, content):
    r = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                    files={"files": (name, io.BytesIO(content),
                                     "application/pdf" if name.endswith(".pdf")
                                     else "image/png")})
    if r.status_code in (404, 405, 422):
        pytest.fail("附件端點還不存在（回 %s）—— `JV3` 先。" % r.status_code)
    assert r.status_code == 200, "附件上傳失敗：%s %s" % (r.status_code, r.text[:200])
    return r


def _uploads_root():
    import helpers.uploads as up
    base = getattr(up, "UPLOADS_ROOT", None)
    assert base, "`helpers/uploads.py` 沒有 `UPLOADS_ROOT` —— **退回給我**。"
    return pathlib.Path(str(base))


def _rows(vid):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM voucher_attachments WHERE voucher_id = ?"
            " ORDER BY id", (vid,))]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 本體
# ══════════════════════════════════════════════════════════════════════

def test_jv5_exporting_the_body_gives_a_non_empty_pdf(client, make_user):
    """🔴 **`§7①`：回 200、是 PDF、而且**位元組數 > 0**。**

    ⚠️ 「位元組數 > 0」不是湊數的：
    ```
    helpers/startup.py  run_edge_pdf **吞掉逾時不丟例外**（docstring 逐字）
    ⇒ 呼叫端若忘了抄「tmp_pdf 沒產出或 0 byte 就 raise」那道檢查，
      **逾時 = 回一份 0 byte 的 PDF**
    ```
    ☠️ 那份 0 byte 的東西 Content-Type 是對的、狀態碼是 200 ——
       **只有位元組數說得出它是壞的**。
    """
    _u, hdr = _hdr(client, make_user, "jv5_body")
    vid = _create(client, hdr)
    r = _export(client, hdr, vid)

    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code, r.content[:160])
    ctype = r.headers.get("content-type", "")
    assert "application/pdf" in ctype, "Content-Type 是 %r" % ctype
    assert len(r.content) > 0, (
        "回了一份 **0 byte** 的 PDF ——\n"
        + "☠️ 狀態碼 200、Content-Type 正確，**而裡面什麼都沒有**。\n"
        + "🔑 多半是 Edge 逾時：`run_edge_pdf` 吞掉逾時不丟例外，\n"
          "   要靠緊接的「沒產出或 0 byte 就 raise」那道檢查。")
    assert r.content[:5] == b"%PDF-", (
        "開頭不是 `%%PDF-`：%r —— 那不是一份 PDF。" % r.content[:16])
    assert _page_count(r.content) >= 1, "數不到任何一頁。"


def test_jv5_it_is_behind_the_voucher_modules(client, make_user):
    """🔴 **`§7⑦`：沒有 `cashier`／`finance` 的人要被擋，不是回一份空檔。**

    ⚠️ 角色用 `user` —— `superadmin` 會**直通**模組檢查
       （`helpers/auth.py:174`，2026-09-14 使用者裁示）
       ⇒ 拿它去驗這道閘，**它永遠不會紅**。
    ⚙️ 配正對照：帶著 `cashier` 的一般員工要印得出來。
    """
    _u0, owner = _hdr(client, make_user, "jv5_owner")
    vid = _create(client, owner)

    _u1, nomod = _hdr(client, make_user, "jv5_nomod", role="user", modules=())
    r = client.get(PDF % vid, headers=nomod)
    if r.status_code in (404, 405, 422):
        pytest.fail("端點還不存在（回 %s）—— 這一格量不到權限。" % r.status_code)
    assert r.status_code in (401, 403), (
        "沒有模組的一般員工印得出傳票（回 %s）——\n" % r.status_code
        + "☠️ 那是**全公司的會計憑證**。")

    _u2, hasmod = _hdr(client, make_user, "jv5_hasmod", role="user",
                       modules=("cashier",))
    r2 = client.get(PDF % vid, headers=hasmod)
    assert r2.status_code == 200, (
        "帶著 `cashier` 的一般員工被擋掉了（回 %s）——\n" % r2.status_code
        + "☠️ 那道閘擋過頭了，上面那一句就不算數。")


def test_jv5_a_voided_voucher_can_still_be_printed(client, make_user):
    """🔴 **`§7⑤`：已作廢的傳票也要印得出來。**

    ```
    vouchers      VIEW，`WHERE voided_at = ''`  <= **看不到作廢單**
    vouchers_all  實表
    ```
    ☠️ 讀錯表的話：作廢單**印不出來** —— 而作廢單是稽核一定要看的東西
       （《商業會計法》§38 憑證保存 5 年，作廢的那一張也在裡面）。
    🔑 而症狀是 404「找不到這張傳票」，**它讀起來像資料被刪了**。
    """
    _u, hdr = _hdr(client, make_user, "jv5_void")
    vid = _create(client, hdr)
    v = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "打錯了"}, headers=hdr)
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = _export(client, hdr, vid)
    assert r.status_code == 200, (
        "已作廢的傳票印不出來（回 %s）：%s\n" % (r.status_code, r.content[:160])
        + "☠️ 多半是讀了 `vouchers` 那個 VIEW（`WHERE voided_at = ''`）\n"
          "   而不是實表 `vouchers_all` ⇒ 症狀是 404，**讀起來像資料被刪了**。")
    assert len(r.content) > 0 and r.content[:5] == b"%PDF-"


# ══════════════════════════════════════════════════════════════════════
# ② 合併：數頁數
# ══════════════════════════════════════════════════════════════════════

def test_jv5_merging_a_pdf_attachment_adds_its_pages(client, make_user):
    """🔴 **`§7③`：總頁數 == 1 ＋ 各 PDF 附件的頁數合計。**

    ☠️ 合併失敗最可能的樣子是「**只有本體那一頁**」——
       而那是一份**完全正常的 PDF**：非空、Content-Type 對、打得開。
    ⇒ 只驗「非空」「是 PDF」一律會綠。
    ⚙️ 觀測點：**與不帶附件那一次相比，頁數要變多**。
       🔑 用相對比較而不是絕對值，因為本體是幾頁由版面決定，**不是我該釘的**。
    """
    _u, hdr = _hdr(client, make_user, "jv5_merge")
    vid = _create(client, hdr)
    _attach(client, hdr, vid, "憑證.pdf", _ONE_PAGE_PDF)

    plain = _export(client, hdr, vid)
    assert plain.status_code == 200, "本體匯出就失敗了，先看那一題。"
    merged = _export(client, hdr, vid, with_attachments=True)
    assert merged.status_code == 200, (
        "帶附件匯出失敗：%s %s" % (merged.status_code, merged.content[:160]))

    a, b = _page_count(plain.content), _page_count(merged.content)
    assert b > a, (
        "帶附件的輸出頁數 %d，沒有比只印本體的 %d 多 ——\n" % (b, a)
        + "☠️ 合併沒有發生，**而輸出是一份完全正常的 PDF**：\n"
          "   非空、Content-Type 對、打得開。只驗那三件一律會綠。")
    assert b >= a + 1, "PDF 附件是 1 頁，總頁數至少要多 1（%d -> %d）。" % (a, b)


# ══════════════════════════════════════════════════════════════════════
# ③ `§5` 的核心：實體檔遺失時**不要拒絕**
# ══════════════════════════════════════════════════════════════════════

def test_jv5_a_missing_attachment_file_does_not_block_the_export(client,
                                                                 make_user):
    """🔴🔴🔴 **`§7④`：附件的實體檔不見了 ⇒ 仍然回 200，而且把缺口說出來。**

    ```
    ❌ 整批拒絕 => 一份法定要保存 5 年的憑證，因為一個附件印不出來
    ❌ 靜默略過 => 使用者拿到一份**看起來完整**的 PDF ⇒ **比印不出來更糟**
    ✅ 把缺口印出來 ＋ **回應也要說**
    ```
    🔑 **一個唯讀動作拒絕執行，擋住的是使用者；靜默略過，騙的是使用者。**

    ## ⚠️ 這裡與 `JV3` 的裁定**方向相反**，而兩個都對

    ```
    JV3 帶入（**寫入**）  部分成功 => 在 DB 裡留下一句謊 => **整批拒絕**
    JV5 匯出（**唯讀**）  不改變任何主張            => **不要拒絕**
    ```
    ☠️ 照抄 `JV3` 的「整批拒絕」是最自然的錯誤 —— 它看起來一致、看起來嚴謹。

    ⚙️ 三格分別擋不同的失敗：
    ```
    (a) 仍然回 200        擋「照抄 JV3 的整批拒絕」
    (b) 紙上要有那個檔名  擋「靜默略過」
    (c) **回應也要說**    擋「只印在紙上」—— 呼叫端分不出「完整」與「缺了東西」
    ```
    """
    _u, hdr = _hdr(client, make_user, "jv5_gone")
    vid = _create(client, hdr)
    _attach(client, hdr, vid, "不見的憑證.pdf", _ONE_PAGE_PDF)
    _attach(client, hdr, vid, "還在的憑證.pdf", _ONE_PAGE_PDF)

    rows = _rows(vid)
    assert len(rows) == 2, "前置不對：附件有 %d 筆。" % len(rows)
    victim = rows[0]
    gone = _uploads_root() / str(victim["path"]).split("uploads/")[-1]
    if not gone.is_file():
        gone = pathlib.Path(str(victim["path"]))
    assert gone.is_file(), "找不到附件的實體檔：%r" % victim.get("path")
    gone.unlink()
    assert not gone.exists(), "刪不掉那個檔 —— **前置失敗，不是產品的問題**。"

    r = _export(client, hdr, vid, with_attachments=True)
    assert r.status_code == 200, (
        "附件的實體檔不見了，而匯出回 %s ——\n" % r.status_code
        + "☠️ 那是照抄 `JV3` 的「整批拒絕」：它看起來一致、看起來嚴謹，\n"
          "   **而匯出是唯讀的** —— 拒絕執行擋住的是使用者。\n"
        + "📌 一份憑證法定要保存 5 年（商業會計法 §38），"
          "不可以因為一個附件而印不出來。")

    name = victim.get("filename") or ""
    assert name, "附件那一列沒有 `filename`：%r" % victim
    body = r.content
    printed = name.encode("utf-8") in body or name.encode("utf-16-be") in body
    assert printed, (
        "輸出裡找不到那個缺檔的檔名 %r ——\n" % name
        + "☠️ **靜默略過**：使用者拿到一份看起來完整的 PDF，\n"
          "   而少了一張憑證 —— 那比印不出來更糟。\n"
        + "⚠️ PDF 的文字可能被編碼（我試過 utf-8 與 utf-16-be）——\n"
          "   若你用別的編碼，**退回給我**改這個觀測點。")

    said = any("未併入" in str(v) or "未能併入" in str(v) or "missing" in str(k).lower()
               for k, v in r.headers.items())
    assert said, (
        "紙上說了，**而回應沒說**。現有 header：%s\n" % sorted(r.headers)
        + "☠️ 呼叫端（前端／自動化）分不出「完整」與「缺了東西」——\n"
          "   而前端要靠它才能在畫面上提醒（`§7⑩`）。\n"
        + "⚠️ 用 header 或改回 JSON 都可以，**用別的形狀退回給我**。")


# ══════════════════════════════════════════════════════════════════════
# ④ 快照 vs 現值
# ══════════════════════════════════════════════════════════════════════

def test_jv5_a_posted_voucher_prints_the_account_name_it_froze(client,
                                                               make_user):
    """🔴 **`§7⑥`：已過帳印 snapshot，未過帳印現值。**

    ⚙️ 觀測方式是 A-2 寫死的，因為這一題**很容易寫成同義反覆**：
    ```
    不改名字的話，snapshot 與現值**相同** => 那一題永遠綠
    ⇒ 必須**過帳後改掉科目名稱**，再匯出，紙上要是**舊名字**
    ```
    ☠️ 取現值的後果：三年後印出一張舊傳票，上面的科目名稱是**今天的**
       —— 而那張傳票當初簽的是另一個名字。

    ## 🔴 用**自訂**科目，不可以用法定科目（我第一版踩到）

    ```
    account_items_statutory_no_update
        BEFORE UPDATE ON account_items WHEN OLD.source = 'statutory'
    ⇒ 改 `1113` 的 name 會撞 RAISE(ABORT)
    ⇒ 這一題紅在**我的前置**，訊息指向資料層 —— 而受測物根本還沒被碰到
    ```
    📌 而 `account_items_referenced_code_no_update` 擋的是 **`code`**，
       改 `name` 不受它管 ⇒ 自訂科目改名是合法的。
    🔑 今天第二次同族：先前是拿 ⑤ TRIGGER 探針自己種的 `9901` 當法定科目用，
       這次是反過來拿法定科目去改 —— **兩次都是我的前置撞到資料層的守門**。
    """
    _u, hdr = _hdr(client, make_user, "jv5_snap")

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO account_items (code, level, name, name_en,"
            " parent_code, source, is_active) VALUES (?,?,?,?,?,'custom',1)",
            ("9911", 4, "測試用自訂科目", "", None))
        conn.commit()
    finally:
        conn.close()

    r = client.post("/api/vouchers", headers=hdr, json={
        "summary": "快照測試",
        "lines": [{"account_code": "9911", "debit": 1000, "credit": 0},
                  {"account_code": "9911", "debit": 0, "credit": 1000}]})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    vid = r.json()["id"]
    for step in ("submit", "approve", "approve", "post"):
        r = client.post("/api/vouchers/%s/%s" % (vid, step), json={},
                        headers=hdr)
        assert r.status_code == 200, (
            "`%s` 失敗：%s %s" % (step, r.status_code, r.text[:160]))

    conn = db.get_db()
    try:
        old = conn.execute(
            "SELECT account_name_snapshot FROM voucher_lines"
            " WHERE voucher_id = ? ORDER BY line_no", (vid,)).fetchone()
        assert old is not None, "讀不到分錄。"
        old_name = old["account_name_snapshot"]
        assert old_name, (
            "過帳了而 `account_name_snapshot` 是空的 ——\n"
            + "☠️ 那表示凍結那一步沒有發生，這一題後面量不到東西。")
        conn.execute(
            "UPDATE account_items SET name = ? WHERE code = ?",
            (old_name + "（改過的）", "9911"))
        conn.commit()
    finally:
        conn.close()

    r = _export(client, hdr, vid)
    assert r.status_code == 200, "匯出失敗：%s" % r.content[:160]
    assert b"\xef\xbc\x88\xe6\x94\xb9\xe9\x81\x8e\xe7\x9a\x84\xef\xbc\x89" \
        not in r.content, (
        "已過帳的傳票印出了**改過之後**的科目名稱 ——\n"
        + "☠️ 三年後印出一張舊傳票，上面的科目名稱是今天的，\n"
          "   **而那張傳票當初簽的是另一個名字**。\n"
        + "🔑 已過帳 ⇒ 取 `account_name_snapshot`，不是現值。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ `AC1`：畫面那一半
# ══════════════════════════════════════════════════════════════════════

def test_jv5_the_page_has_both_export_actions(client, make_user):
    """🔴 **`§7⑨`：傳票頁要有「匯出 PDF」與「匯出（含附件）」兩個動作。**

    ⚠️ 判準是**會送出的那一個動作**（`AC1`），而匯出是 `GET`
       ⇒ 這裡看的是「有沒有打到那支端點」，不是 `method: 'POST'`。
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    js = (root / "frontend" / "js" / "voucher.js").read_text(
        encoding="utf-8", errors="replace")
    assert "pdf-download" in js, (
        "`voucher.js` 沒有任何地方打 `pdf-download` —— 匯出那條路還沒接。")
    assert "with_attachments" in js, (
        "`voucher.js` 有匯出，而**沒有「含附件」那一個** ——\n"
        + "☠️ 兩個動作只接一個的話，使用者以為印出來的就是全部。")
