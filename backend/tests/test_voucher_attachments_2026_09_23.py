# -*- coding: utf-8 -*-
"""`JV3` · 傳票附件（`docs/windows/SPEC-JV3-ATTACHMENTS.md §8` 的十題驗收）。

```
POST   /api/vouchers/{voucher_id}/attachments            上傳／帶入
DELETE /api/vouchers/{voucher_id}/attachments/{file_id}  軟刪（僅草稿）
```

# ☠️ `§8` 逐字：**②③⑤⑥ 是這份規格的核心。其他題綠了而它們紅 ＝ 沒做到。**

```
② 退回升版後（單號變 -R1）**同一批附件仍讀得到**   <= 附件綁 voucher_id 不綁單號
③ 草稿 DELETE -> deleted_at 非空、清單不列它，**而實體檔仍在**
⑤ 帶入後刪掉**來源**附件 -> 傳票這邊**仍讀得到**   <= 帶入是複製不是引用
⑥ 作廢重開 -> 新單附件筆數 == 原單未刪筆數，
   且新舊 file_id **不相同**、實體檔是**兩份**
```

# 🔴 ③ 的觀測點在**磁碟上**，不是清單上

```
helpers/uploads.py:100  delete_document_file()  會 os.remove()
```
⚠️ 它的**名字正好、簽章也接近** ⇒ 很容易被直接拿來用 ⇒ **bytes 沒了**，
   而「清單不再列出它」照樣綠。
🔑 ⇒ 這一題一定要去看**檔案還在不在**。

# ⚠️ `§166`：不存在的路由回 **405**，不是 404

```
assert r.status_code != 404   ⇒ **擋不到**（405 != 404）
```
⇒ 本檔一律先斷言 `status_code in (200, 400, 403)`，再去看內容。
📌 而 `DELETE`／`POST` 那幾題**在 B 接上端點之前一定要先確認它們是紅的**，
   且紅的原因不可以是 405。
"""
import io
import json
import pathlib

import pytest

ATT = "/api/vouchers/%s/attachments"
ATT_ONE = "/api/vouchers/%s/attachments/%s"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)

#: `§3` 的九類來源 ＋ 第 10 個（作廢重開複製產生）。⚠️ 少一個、多一個都要紅。
SOURCE_TYPES = ("quotation", "case_update", "payment_item", "material",
                "material_invoice", "extra_expense", "invoice_voucher",
                "contractor_dispatch", "contractor_invoice")
COPY_SOURCE_TYPE = "voucher"

#: `§3` 明著排除的兩處 —— **不可以出現在來源清單裡**。
EXCLUDED = ("completion_note", "shipping_note", "dev_log", "pending_case_change")

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr):
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "附件測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _reached(r, what):
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`%s` 走不到（回 %s）。\n" % (what, r.status_code)
            + "📌 `§166`：這個 repo 的 catch-all StaticFiles 只處理 GET/HEAD\n"
              "   ⇒ **POST／DELETE 打未實作端點回 405**，`!= 404` 擋不到。\n"
            + "⚠️ 路徑是 `§160` 定案的，改了**退回給我**。")
    assert r.status_code in OK_CODES, (
        "`%s` 回 %s，不在 %s 裡：%s"
        % (what, r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _upload(client, hdr, vid, name="憑證.pdf", content=b"%PDF-1.4 fake"):
    r = client.post(ATT % vid, headers=hdr,
                    files={"files": (name, io.BytesIO(content),
                                     "application/pdf")})
    return _reached(r, "POST /api/vouchers/{id}/attachments")


def _list(client, hdr, vid):
    """附件清單。⚠️ 掛在哪裡還沒定 —— 先找 `GET /{id}` 裡的 `attachments`。"""
    r = client.get("/api/vouchers/%s" % vid, headers=hdr)
    assert r.status_code == 200, "讀不回來：%s" % r.text[:200]
    v = r.json()
    got = v.get("attachments")
    assert got is not None, (
        "`GET /api/vouchers/{id}` 沒有回 `attachments`：%s\n" % sorted(v)
        + "⚠️ 附件清單若改成獨立端點，**退回給我**改 `_list()`。")
    return got


def _rows(vid=None):
    import db
    conn = db.get_db()
    try:
        sql = "SELECT * FROM voucher_attachments"
        args = ()
        if vid is not None:
            sql += " WHERE voucher_id = ?"
            args = (vid,)
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]
    except Exception as e:                       # noqa: BLE001
        pytest.fail(
            "查 `voucher_attachments` 失敗：%s\n" % e
            + "📌 `§2` 的 migration 還沒做。⚠️ 版本號**不要照規格寫死** ——\n"
              "   規格刻意不寫號碼，動手當下取（`grep -n '^CURRENT_VERSION' db.py`）。")
    finally:
        conn.close()


def _abs(path):
    """把 `uploads/` 相對路徑換成這一輪測試的實際檔案位置。"""
    import helpers.uploads as up
    base = getattr(up, "UPLOAD_DIR", None) or getattr(up, "UPLOADS_DIR", None)
    assert base, (
        "`helpers/uploads.py` 找不到上傳根目錄常數（試過 `UPLOAD_DIR`／"
        "`UPLOADS_DIR`）—— **退回給我**。")
    p = pathlib.Path(str(path))
    if p.is_absolute():
        return p
    rel = p.as_posix()
    for prefix in ("uploads/", "./uploads/"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return pathlib.Path(str(base)) / rel


# ══════════════════════════════════════════════════════════════════════
# ① 上傳落地，而路徑不可以含單號
# ══════════════════════════════════════════════════════════════════════

def test_jv3_uploading_puts_a_real_file_on_disk_and_a_row_in_the_table(
        client, make_user):
    """🔴 **`§8①`：檔案要真的落地，表裡要有一列，而 `path` 不含 `voucher_no`。**

    ☠️ 路徑含單號的後果：**退回升版**（單號變 `-R1`）之後那個路徑
       指向一個**不存在的資料夾** —— 而它不報錯，只是附件消失。
    ⚙️ 三個觀測點缺一不可：
    ```
    回應說成功    它自己說的話
    表裡有一列    後端記得
    **磁碟上有檔** <= 只有這一個證明 bytes 真的存下來了
    ```
    """
    _u, hdr = _hdr(client, make_user, "jv3_up")
    vid = _create(client, hdr)
    r = _upload(client, hdr, vid)
    assert r.status_code == 200, "上傳失敗：%s %s" % (r.status_code, r.text[:200])

    rows = _rows(vid)
    assert len(rows) == 1, "表裡有 %d 列，應該是 1：%r" % (len(rows), rows)
    row = rows[0]

    vno = row.get("voucher_no")
    del vno
    import db
    conn = db.get_db()
    try:
        real_no = conn.execute(
            "SELECT voucher_no FROM vouchers_all WHERE id = ?",
            (vid,)).fetchone()["voucher_no"]
    finally:
        conn.close()
    assert real_no and real_no not in (row.get("path") or ""), (
        "附件路徑裡含單號 `%s`：%r\n" % (real_no, row.get("path"))
        + "☠️ 退回升版之後單號變 `-R1`，那個路徑會指向一個**不存在的資料夾**\n"
          "   —— 而它不報錯，只是附件消失。")

    f = _abs(row.get("path"))
    assert f.is_file(), (
        "表裡有一列，而**磁碟上沒有檔**：%s\n" % f
        + "☠️ 「上傳成功」是一句話，而 bytes 沒有存下來。")
    assert f.stat().st_size > 0, "檔案是空的：%s" % f


def test_jv3_attachments_survive_a_send_back_that_bumps_the_number(
        client, make_user):
    """🔴🔴 **`§8②` 核心：退回升版之後，同一批附件仍讀得到。**

    ```
    附件綁 voucher_id（不變）  ✅
    附件綁 voucher_no（會變成 -R1）  ☠️ **跟丟**
    ```
    ⚠️ 而跟丟的樣子不是錯誤：清單是空的，看起來像「這張單本來就沒有附件」。
    """
    _u, hdr = _hdr(client, make_user, "jv3_bump")
    vid = _create(client, hdr)
    _upload(client, hdr, vid, name="退回前.pdf")
    before = [a.get("file_id") for a in _list(client, hdr, vid)]
    assert before, "上傳之後清單是空的 —— 先看 `§8①` 那一題。"

    assert client.post("/api/vouchers/%s/submit" % vid, json={},
                       headers=hdr).status_code == 200
    sb = client.post("/api/vouchers/%s/send-back" % vid,
                     json={"reason": "金額要改"}, headers=hdr)
    assert sb.status_code == 200, "退回失敗：%s %s" % (sb.status_code, sb.text[:200])

    after = [a.get("file_id") for a in _list(client, hdr, vid)]
    assert after == before, (
        "退回升版之後附件對不起來：\n  升版前 %r\n  升版後 %r\n" % (before, after)
        + "☠️ 附件綁的是**單號**而不是 `voucher_id` ⇒ 單號變 `-R1` 就跟丟。\n"
        + "🔑 而跟丟的樣子不是錯誤：清單是空的，"
          "**看起來像這張單本來就沒有附件**。")


# ══════════════════════════════════════════════════════════════════════
# ② 刪除：軟刪，bytes 留著
# ══════════════════════════════════════════════════════════════════════

def test_jv3_deleting_a_draft_attachment_keeps_the_bytes_on_disk(client,
                                                                 make_user):
    """🔴🔴 **`§8③` 核心：軟刪 —— 清單不列它，而實體檔仍在。**

    ☠️ `helpers/uploads.py:100 delete_document_file()` 會 `os.remove()`，
       而它的**名字正好、簽章也接近** ⇒ 很容易被直接拿來用 ⇒ **bytes 沒了**，
       而「清單不再列出它」照樣綠。
    ⇒ 這一題的觀測點在**磁碟上**，不是清單上。
    🔑 為什麼 bytes 要留：稽核要答得出「那張單曾經附過什麼」——
       一個被刪掉的憑證與一個從來不存在的憑證，在紀錄上必須分得開。
    """
    _u, hdr = _hdr(client, make_user, "jv3_del")
    vid = _create(client, hdr)
    _upload(client, hdr, vid, name="要刪的.pdf")
    row = _rows(vid)[0]
    f = _abs(row.get("path"))
    assert f.is_file(), "前置不對：上傳之後磁碟上沒有檔 %s" % f

    r = client.delete(ATT_ONE % (vid, row.get("file_id")), headers=hdr)
    _reached(r, "DELETE /api/vouchers/{id}/attachments/{file_id}")
    assert r.status_code == 200, "草稿刪不掉：%s %s" % (r.status_code, r.text[:200])

    after = _rows(vid)[0]
    assert (after.get("deleted_at") or "") != "", (
        "刪了而 `deleted_at` 還是空的：%r" % after)
    assert not any(a.get("file_id") == row.get("file_id")
                   for a in _list(client, hdr, vid)), (
        "清單裡還列著已刪的那一筆。")
    assert f.is_file(), (
        "**實體檔被刪掉了**：%s\n" % f
        + "☠️ 多半是直接用了 `delete_document_file()` —— 它會 `os.remove()`。\n"
        + "🔑 `§5` 裁定 ②：軟刪，**bytes 留著**；\n"
          "   一個被刪掉的憑證與一個從來不存在的憑證，在紀錄上必須分得開。")


def test_jv3_a_non_draft_attachment_cannot_be_deleted_at_all(client,
                                                             make_user):
    """🔴 **`§8④`：離開草稿之後刪不掉，而且要看它「真的沒動到資料」。**

    ⚙️ 反向控制的形狀：**不是只看回應碼**。
    ```
    回 403 而 deleted_at 被寫進去了  => 清單上它消失了，而回應說「不准」
    ```
    ☠️ 那種狀態最難發現：使用者看到錯誤訊息，**而東西真的不見了**。
    """
    _u, hdr = _hdr(client, make_user, "jv3_locked")
    vid = _create(client, hdr)
    _upload(client, hdr, vid, name="送審後.pdf")
    row = _rows(vid)[0]
    assert client.post("/api/vouchers/%s/submit" % vid, json={},
                       headers=hdr).status_code == 200

    r = client.delete(ATT_ONE % (vid, row.get("file_id")), headers=hdr)
    _reached(r, "DELETE /api/vouchers/{id}/attachments/{file_id}")
    assert r.status_code in (400, 403), (
        "非草稿的附件被刪掉了（回 %s）：%s" % (r.status_code, r.text[:200]))
    assert (_rows(vid)[0].get("deleted_at") or "") == "", (
        "回應說不准，**而 `deleted_at` 已經被寫進去了** ——\n"
        + "☠️ 使用者看到錯誤訊息，而東西真的不見了。\n"
        + "🔑 拒絕的路徑上不可以留下副作用。")


# ══════════════════════════════════════════════════════════════════════
# ③ 帶入：複製不是引用
# ══════════════════════════════════════════════════════════════════════

def test_jv3_an_unknown_source_type_is_refused_with_400(client, make_user):
    """🔴 **`§8⑦`：`picks` 傳一個不在九類裡的 `type` ⇒ 400。**

    ☠️ 不是 403（那是權限）、不是 500（那是它炸了）。
    ⚠️ 而 `§4` 逐字：**帶入不可以讓前端傳路徑進來** ——
       那等於開一個**任意檔案讀取**。⇒ 只收 `(type, docNo, fileId)`。
    ⚙️ 這一題順便釘住那件事：白名單之外一律拒絕。
    """
    _u, hdr = _hdr(client, make_user, "jv3_badtype")
    vid = _create(client, hdr)

    r = client.post(ATT % vid, headers=hdr, json={"picks": [
        {"type": "completion_note", "docNo": "X", "fileId": "Y"}]})
    _reached(r, "POST /api/vouchers/{id}/attachments (picks)")
    assert r.status_code == 400, (
        "不在九類裡的來源型別被接受了（回 %s）：%s\n"
        % (r.status_code, r.text[:200])
        + "📌 `completion_note` 是 `§3` **明著排除**的（不是會計憑證）。")


def _seed_quotation_with_file(quote_no="MQ-JV3-001", name="來源憑證.pdf"):
    """種一張報價單 ＋ 一個已上傳的附件（`§3` 第 1 類 `quotation`）。

    回 `(file_id, 實體檔路徑)`。
    """
    import db
    import helpers.uploads as up

    base = getattr(up, "UPLOAD_DIR", None) or getattr(up, "UPLOADS_DIR", None)
    assert base, "`helpers/uploads.py` 找不到上傳根目錄常數 —— **退回給我**。"
    folder = pathlib.Path(str(base)) / "quotations"
    folder.mkdir(parents=True, exist_ok=True)
    file_id = "jv3src001"
    real = folder / ("%s_%s" % (file_id, name))
    real.write_bytes(b"%PDF-1.4 source")

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", "測試客戶", "測試案", 0, 0, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(quotations)")}
        assert "files_json" in cols, (
            "`quotations` 沒有 `files_json` 欄 —— `§3` 第 1 類的 metadata 位置\n"
            "與我讀的不一樣，**退回給我**。")
        conn.execute(
            "UPDATE quotations SET files_json = ? WHERE quote_no = ?",
            (json.dumps([{"id": file_id, "name": name,
                          "path": "quotations/%s" % real.name}]), quote_no))
        conn.commit()
    finally:
        conn.close()
    return quote_no, file_id, real


def test_jv3_bringing_in_copies_the_file_so_the_source_can_be_deleted(
        client, make_user):
    """🔴🔴 **`§8⑤` 核心：帶入是**複製**，刪掉來源之後傳票這邊仍讀得到。**

    ```
    引用（只存路徑）  别人刪掉來源附件 => **一張已過帳傳票的憑證消失**
    複製             來源怎麼動都不影響
    ```
    ☠️ 而引用的失敗**不在帶入的那一刻** —— 它在幾個月後別人清檔案的那一天，
       那時沒有人會把兩件事連起來。
    ⚙️ 觀測點：把**來源的實體檔刪掉**，再去讀傳票的附件 —— 它要還在。
    """
    _u, hdr = _hdr(client, make_user, "jv3_copy")
    vid = _create(client, hdr)
    quote_no, src_id, src_file = _seed_quotation_with_file()

    r = client.post(ATT % vid, headers=hdr, json={"picks": [
        {"type": "quotation", "docNo": quote_no, "fileId": src_id}]})
    _reached(r, "POST /api/vouchers/{id}/attachments (picks)")
    assert r.status_code == 200, "帶入失敗：%s %s" % (r.status_code, r.text[:200])

    rows = _rows(vid)
    assert len(rows) == 1, "帶入之後表裡有 %d 列：%r" % (len(rows), rows)
    row = rows[0]
    assert row.get("source_type") == "quotation", (
        "來源型別沒記下來：%r —— `§2` 的三個來源欄是**決定性連結**，"
        "不是一段描述文字。" % row)
    assert row.get("file_id") != src_id, (
        "帶入之後 `file_id` 與來源相同（%r）——\n" % src_id
        + "☠️ 那表示它是**引用**不是複製：來源被刪，傳票的憑證跟著消失。")

    copied = _abs(row.get("path"))
    assert copied.is_file(), "複製出來的檔不存在：%s" % copied
    assert copied.resolve() != src_file.resolve(), (
        "傳票的附件與來源是**同一個檔**：%s\n" % copied
        + "☠️ 那是引用不是複製。")

    # ⚙️ 真正的考驗：把來源刪掉
    src_file.unlink()
    assert copied.is_file(), (
        "刪掉來源的實體檔之後，傳票的附件也不見了：%s\n" % copied
        + "☠️ **一張已過帳傳票的憑證消失** —— 而它在幾個月後才會被發現。")
    assert _list(client, hdr, vid), "來源刪掉之後傳票的附件清單空了。"


def test_jv3_voiding_and_reopening_copies_the_attachments(client, make_user):
    """🔴🔴 **`§8⑥` 核心：作廢重開 ⇒ 新單要有自己的一份附件。**

    ```
    新單附件筆數 == 原單**未刪**筆數
    新舊 file_id **不相同**
    實體檔是**兩份**
    ```
    ☠️ 不複製的話：使用者作廢重開（那是**正常流程**不是邊緣情境），
       新單上一個憑證都沒有 —— 而他以為附件跟著走了。
    ⚠️ 而「共用同一個 file_id」比沒複製更糟：
       在新單上刪掉一個附件，**原單的憑證也跟著不見** ——
       而原單是已經作廢的歷史，稽核要看得到它當時附了什麼。
    """
    _u, hdr = _hdr(client, make_user, "jv3_void")
    vid = _create(client, hdr)
    _upload(client, hdr, vid, name="留著的.pdf")
    _upload(client, hdr, vid, name="要刪的.pdf")
    rows = _rows(vid)
    assert len(rows) == 2, "前置不對：上傳兩個而表裡有 %d 列。" % len(rows)

    # 刪掉其中一個（草稿階段） ⇒ 它**不應該**被複製到新單
    d = client.delete(ATT_ONE % (vid, rows[1].get("file_id")), headers=hdr)
    _reached(d, "DELETE /api/vouchers/{id}/attachments/{file_id}")
    assert d.status_code == 200, "草稿刪不掉：%s" % d.text[:200]

    r = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "打錯了", "reopen": True}, headers=hdr)
    _reached(r, "POST /api/vouchers/{id}/void")
    assert r.status_code == 200, "作廢失敗：%s %s" % (r.status_code, r.text[:200])
    new_id = (r.json() or {}).get("new_id") or (r.json() or {}).get("id")
    assert new_id and int(new_id) != int(vid), (
        "作廢的回應沒有給出重開的新單 id：%r\n" % r.json()
        + "⚠️ 鍵名不是 `new_id`／`id` 的話**退回給我**。")

    new_rows = _rows(int(new_id))
    old_live = [r_ for r_ in _rows(vid) if not (r_.get("deleted_at") or "")]
    assert len(new_rows) == len(old_live) == 1, (
        "新單附件 %d 筆、原單未刪 %d 筆，兩個都應該是 1。\n"
        % (len(new_rows), len(old_live))
        + "☠️ 已刪的那一筆**不可以**被複製過去 —— 使用者刪掉它是有意的。")
    assert new_rows[0].get("file_id") != old_live[0].get("file_id"), (
        "新舊單共用同一個 `file_id` —— \n"
        + "☠️ 在新單上刪掉一個附件，**原單的憑證也跟著不見**，\n"
          "   而原單是已作廢的歷史，稽核要看得到它當時附了什麼。")
    a, b = _abs(old_live[0].get("path")), _abs(new_rows[0].get("path"))
    assert a.is_file() and b.is_file(), "兩份實體檔不是都在：%s ／ %s" % (a, b)
    assert a.resolve() != b.resolve(), (
        "新舊單指向**同一個實體檔**：%s\n" % a
        + "📌 `§1` 裁定 ①：作廢重開**要複製附件**。")


def test_jv3_the_source_type_list_is_exactly_the_nine_plus_the_copy_one():
    """⚙️ **可數完備：九類 ＋ 一個複製用的，少一個多一個都要紅。**

    ```
    少一個  使用者少一個帶得進來的來源，**而畫面看起來正常**
    多一個  有人加了一個來源而**沒有人決定它的實體路徑與 metadata 位置**
    ```
    ☠️ `§3` 逐字警告的那一格：「購料」**不在** `material_orders`
       ⇒ 找錯地方會做出一個**永遠是空的清單，而它不會報錯**。
    ⚠️ 常數叫什麼由 B 決定 —— 找不到就明說要哪一個名字。
    """
    import importlib

    mod = None
    for name in ("helpers.voucher_attachments", "helpers.voucher",
                 "routers.vouchers"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        for attr in ("SOURCE_TYPES", "ATTACHMENT_SOURCES", "PICK_SOURCES"):
            got = getattr(mod, attr, None)
            if got:
                names = set(got) if not isinstance(got, dict) else set(got)
                assert names == set(SOURCE_TYPES) | {COPY_SOURCE_TYPE} \
                    or names == set(SOURCE_TYPES), (
                    "`%s.%s` 是 %s\n" % (name, attr, sorted(names))
                    + "而 `§3` 的九類是 %s（＋作廢重開用的 `%s`）。\n"
                    % (sorted(SOURCE_TYPES), COPY_SOURCE_TYPE)
                    + "☠️ 少一個 ⇒ 那一類的附件**永遠帶不進來，而畫面看起來正常**。")
                for bad in EXCLUDED:
                    assert bad not in names, (
                        "`%s` 出現在來源清單裡 —— `§3` 明著排除它。\n" % bad
                        + "☠️ `pending_case_change` 是**待核准的暫存附件**：\n"
                          "   帶進傳票 = 讓一個還沒核准的東西變成憑證。")
                return
    pytest.fail(
        "找不到來源型別的白名單常數。\n"
        + "📌 我找過 `helpers.voucher_attachments`／`helpers.voucher`／\n"
          "   `routers.vouchers` 裡的 `SOURCE_TYPES`／`ATTACHMENT_SOURCES`／\n"
          "   `PICK_SOURCES`。**用別的名字退回給我。**\n"
        + "⚠️ 而它必須是**一份可以數的清單**，不可以散在 if/elif 裡 ——\n"
          "   散著的話「少一類」永遠不會有人發現。")


# ══════════════════════════════════════════════════════════════════════
# ④ 稽核：新表要進每日備份
# ══════════════════════════════════════════════════════════════════════

def test_jv3_the_new_table_is_in_the_daily_backup(client, make_user):
    """🔴 **`§8⑧`：`voucher_attachments` 要進每日備份。**

    ☠️ 漏掉的樣子：備份跑得好好的、每天都有檔，**而還原回來的系統
       少了一整張表** —— 而那要到真的還原那天才會發現。
    """
    import archive

    fn = getattr(archive, "_daily_backup_tables", None)
    assert callable(fn), (
        "`archive._daily_backup_tables()` 不見了 —— **退回給我**改觀測點。\n"
        + "📌 我第一版去 `helpers.archive` 找，而它在 **`backend/archive.py`**：\n"
          "   探針找不到東西時報的是「找不到」，而那與「產品缺了它」長得一樣。")

    listed = fn()
    assert len(listed) > 30, (
        "每日備份只列了 %d 張表 —— **尺量不到東西**，下面的斷言不算數。"
        % len(listed))
    assert "voucher_attachments" in set(listed), (
        "`voucher_attachments` 不在每日備份的 %d 張表裡。\n" % len(listed)
        + "☠️ 備份每天都有檔，**而還原回來少了一整張表** ——\n"
          "   那要到真的還原那天才會發現。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ `AC1`：畫面那一半
# ══════════════════════════════════════════════════════════════════════

def test_jv3_the_page_can_upload_bring_in_and_delete(client, make_user):
    """🔴 **`§8⑨`：上傳／帶入／刪除三個動作都要打得到 API。**（`AC1`）

    ⚠️ 判準是**會送出的那一個動作**，不是數 `<button>`。
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    js = (root / "frontend" / "js" / "voucher.js").read_text(
        encoding="utf-8", errors="replace")

    assert "attachments" in js, (
        "`voucher.js` 完全沒有提到 `attachments` —— 附件那一段還沒接。")
    assert "method: 'POST'" in js or 'method: "POST"' in js, (
        "`voucher.js` 沒有 `POST` —— 上傳／帶入那條路還沒接。")
    assert "method: 'DELETE'" in js or 'method: "DELETE"' in js, (
        "`voucher.js` 沒有 `DELETE` —— 刪除那條路還沒接。\n"
        + "☠️ 只有上傳而不能刪 ⇒ 使用者附錯檔案之後只能作廢整張單。")


def test_jv3_the_delete_button_is_absent_not_disabled_when_locked():
    """🔴 **`§8⑩`：非草稿時刪除鈕要「不存在」，不是 `disabled`。**

    ```
    disabled  元素**仍然在 DOM 裡** ⇒ 使用者看得到一個按不下去的按鈕
    x-if      **整個不存在**
    ```
    ☠️ 看得到而按不下去的按鈕，使用者會一直按 —— 而畫面不會說為什麼。
    ⚠️ 我釘的是「那個刪除鈕的顯示條件用 `x-if`」，不釘它叫什麼。
    ⚙️ 而 B 的傳票按鈕目前用 `x-show`（元素留在 DOM）——
       那對**其他按鈕**沒問題，對這一個不行。
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "pages" / "voucher.html").read_text(
        encoding="utf-8", errors="replace")
    import re
    html = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)

    assert re.search(r"attach", html, re.I), (
        "`voucher.html` 上看不到任何附件區塊 —— 頁面那一半還沒做。")
    m = re.search(r"<template[^>]*x-if=\"[^\"]*\"[^>]*>\s*<[^>]*"
                  r"(?:data-testid=\"voucher-att-delete\"|刪除)", html, re.S)
    assert m, (
        "附件的刪除鈕不是用 `<template x-if>` 包起來的。\n"
        + "☠️ `x-show`／`disabled` 會讓它**留在 DOM 裡** ——\n"
          "   使用者看得到一個按不下去的按鈕，而畫面不會說為什麼。\n"
        + "📌 `§8⑩` 逐字：非草稿時刪除鈕**不存在**（不是 disabled）。\n"
        + "⚠️ 掛鉤名我定成 `data-testid=\"voucher-att-delete\"`，"
          "要換**退回給我**。")
