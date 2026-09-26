# -*- coding: utf-8 -*-
"""`JV18` · 已被其他傳票用過的憑證要看得出來（`docs/windows/SPEC-JV18.md`）。

使用者原話（兩則）：
「傳票如果**已經被計算過**，要有備註（**紅字＋已計算**），**計算過的內容
須放在最後，依據計算過後的時間由新到舊排序**」／「**計算過是已經被
其他傳票使用的意思**」。

# ✅ 使用者裁定甲（A 2026-09-23 問回來）：**只在「帶入憑證」選單標**

不擴到傳票自己的附件清單或傳票清單頁——規格 `§4` 逐字：那句話講的是
一個「會被排序的候選清單」，系統裡只有「摘要來源→已上傳檔案」頁籤
（`case_attachments()` 的輸出）長這個形狀。

# 🔴 現況：`case_attachments()` 完全沒查 `voucher_attachments`

```python
# helpers/voucher_attachments.py:348
out.append({
    "type": st, "docNo": doc_no, "fileId": …, "filename": name,
    "exists": exists, "reason": reason, "missing": …,
})
```
⇒ 同一張發票可以被兩張傳票各帶入一次，畫面上看不出來——那就是重複入帳。

# ✅ §2c 後果二（作廢重開後 `source_*` 指向舊傳票）**已由 A 裁定另開 `JV24`**

`JV18` 本身不受它影響：作廢的那一張已裁定「不算已使用」，重開的新單
（`source_*` 指向哪裡不影響「新單本身算不算已使用」這件事）算——兩邊
一致，沒有矛盾。本檔**不寫**「作廢重開之後原始憑證仍標著已計算」那一題
——那是 `JV24` 的範圍，不是 `JV18` 的。

# ⚙️ 觀測方式：直接呼叫 `case_attachments()`，帶入走真正的 HTTP 端點

候選憑證用直接 SQL 種（照抄 `test_case_attachments_scope_2026_09_23.py`
的 `_make_file`／`_seed` 形狀）；「被用過」這件事**不**用 SQL 直接塞
`voucher_attachments`，改真的打 `POST /{voucher_id}/attachments`
（`{"picks": [...]}`）——那是唯一真的會產生 `source_*` 三元組的路徑，
自己塞的話等於在驗證我自己造的資料格式對不對，不是驗證真實流程。
"""
import json
import pathlib

import pytest

QUOTE_NO_PREFIX = "MQ-JV18"


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _uploads_root():
    import helpers.uploads as up
    base = getattr(up, "UPLOADS_ROOT", None)
    assert base, "`helpers/uploads.py` 沒有 `UPLOADS_ROOT`——退回給我。"
    return pathlib.Path(str(base))


def _make_file(subfolder, file_id):
    folder = _uploads_root() / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    real = folder / ("%s.pdf" % file_id)
    real.write_bytes(b"%PDF-1.4 jv18")
    return {"id": file_id, "name": "%s.pdf" % file_id,
            "path": "%s/%s" % (subfolder, real.name)}


def _seed_case(conn, quote_no):
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name,"
        " project_name, total, pretax, data_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "已結案", "JV18測試客戶", "JV18測試案", 0, 0, "{}",
         "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
    conn.commit()


def _seed_invoice_voucher_candidate(conn, quote_no, file_id, voucher_no=None):
    """種一筆 `invoice_voucher` 型候選憑證，回 `(doc_no, file_id)`。

    ⚠️ 這裡的 `voucher_no`（`invoice_vouchers` 表自己的單號）與
    `case_attachments()` 回的 `docNo` 是同一個值——`source_files()` 對
    `invoice_voucher` 用的鍵就是 `voucher_no`，不要跟「帶入它的那張
    `vouchers_all` 傳票」搞混，那是兩張完全不同的表。
    """
    f = _make_file("invoice_vouchers", file_id)
    vno = voucher_no or ("IV-" + file_id)
    conn.execute(
        "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status,"
        " snapshot_json, data_json, created_by, created_at, updated_at,"
        " issued_files_json) VALUES (?,?,'single','草稿','{}','{}','t',"
        "'2026-09-01','2026-09-01',?)",
        (vno, quote_no, json.dumps([f])))
    conn.commit()
    return vno, f["id"]


def _case_attachments(quote_no):
    import db
    import modules.accounting.voucher_attachments as va
    conn = db.get_db()
    try:
        return va.case_attachments(conn, quote_no, {"id": 0, "username": "att_test_root", "role": "superadmin", "modules": []})  # 驗清單內容，不是權限（權限見 test_attachments_providers）
    finally:
        conn.close()


def _create_voucher(client, hdr, summary):
    lines = [{"account_code": "1113", "debit": 1000, "credit": 0},
            {"account_code": "4111", "debit": 0, "credit": 1000}]
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": summary, "lines": lines})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _bring_in(client, hdr, voucher_id, source_type, doc_no, file_id):
    r = client.post("/api/vouchers/%s/attachments" % voucher_id, headers=hdr,
                    json={"picks": [
                        {"type": source_type, "docNo": doc_no, "fileId": file_id}]})
    assert r.status_code == 200, "帶入失敗：%s %s" % (r.status_code, r.text[:300])
    return r


def _voucher_no(voucher_id):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT voucher_no FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        return dict(row)["voucher_no"] if row else None
    finally:
        conn.close()


def _find(items, source_type, doc_no, file_id):
    for x in items:
        if (x.get("type") == source_type and x.get("docNo") == doc_no
                and x.get("fileId") == file_id):
            return x
    return None


# ══════════════════════════════════════════════════════════════════════
# ① 核心：候選憑證被帶入過之後，回三個新欄位
# ══════════════════════════════════════════════════════════════════════

def test_jv18_a_candidate_brought_in_by_a_voucher_is_marked_used(client,
                                                                  make_user):
    """🔴🔴 **核心：憑證被帶入一次之後，`case_attachments()` 要回
    `used=True`，`usedBy` 要有那張傳票的單號與時間。**
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-BASIC"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_basic")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_basic")
    before = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert before is not None, "候選憑證種下去卻在清單裡找不到——前置不對。"
    assert before.get("used") is not True, (
        "還沒有任何傳票帶入這筆憑證，`used` 卻已經是 True——前置不對。")

    vid = _create_voucher(client, hdr, "JV18 帶入測試")
    _bring_in(client, hdr, vid, "invoice_voucher", doc_no, file_id)
    vno = _voucher_no(vid)

    after = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert after is not None, "帶入之後，候選清單裡反而找不到這筆了。"
    assert after.get("used") is True, (
        "已經被傳票 %r 帶入，`used` 卻不是 True：%r" % (vno, after))
    used_by = after.get("usedBy") or []
    assert len(used_by) == 1, (
        "`usedBy` 應該有 1 筆，實際 %d 筆：%r" % (len(used_by), used_by))
    entry = used_by[0]
    assert entry.get("voucherNo") == vno, (
        "`usedBy[0].voucherNo` 是 %r，預期 %r。" % (entry.get("voucherNo"), vno))
    assert entry.get("voucherId") == vid, (
        "`usedBy[0].voucherId` 是 %r，預期 %r。" % (entry.get("voucherId"), vid))
    assert entry.get("usedAt"), "`usedBy[0].usedAt` 是空的——使用者要看到什麼時候用的。"
    assert after.get("usedAt") == entry.get("usedAt"), (
        "頂層 `usedAt`（排序用）應該等於 `usedBy` 那一筆的時間。")


def test_jv18_a_candidate_never_brought_in_is_not_used(client, make_user):
    """⚙️ **負對照：從沒被帶入過的候選憑證，`used` 要是 False、`usedBy` 要是空的。**

    ☠️ 少了它，「一律回 `used=True`」也會讓上一題變綠。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-UNUSED"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_unused")
    finally:
        conn.close()

    got = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert got is not None
    assert not got.get("used"), "從沒被帶入過，`used` 卻是真值：%r" % got
    assert not (got.get("usedBy") or []), (
        "從沒被帶入過，`usedBy` 卻不是空的：%r" % got.get("usedBy"))


# ══════════════════════════════════════════════════════════════════════
# ② `usedBy` 要列出**全部**帶入過的傳票，不是只有最近一張（§5／§7ⓓ）
# ══════════════════════════════════════════════════════════════════════

def test_jv18_used_by_more_than_one_voucher_lists_all_of_them(client,
                                                               make_user):
    """🔴🔴 **同一筆憑證被兩張傳票各帶入一次，`usedBy` 要列出兩張。**

    ☠️ 只顯示最近那一張的話，**重複入帳的那一筆正好被藏起來**——
    而重複入帳正是這整個功能要防的事。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-DOUBLE"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_double")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_double")
    vid1 = _create_voucher(client, hdr, "JV18 重複入帳①")
    _bring_in(client, hdr, vid1, "invoice_voucher", doc_no, file_id)
    vid2 = _create_voucher(client, hdr, "JV18 重複入帳②")
    _bring_in(client, hdr, vid2, "invoice_voucher", doc_no, file_id)
    vno1, vno2 = _voucher_no(vid1), _voucher_no(vid2)

    after = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    used_by = after.get("usedBy") or []
    got_nos = {e.get("voucherNo") for e in used_by}
    assert got_nos == {vno1, vno2}, (
        "被兩張傳票帶入，`usedBy` 卻是 %r（預期 %r）——\n" % (got_nos, {vno1, vno2})
        + "☠️ 若只列最近一張，其中一次重複入帳會被藏起來。")


# ══════════════════════════════════════════════════════════════════════
# ③ 排序：已使用排最後，按 usedAt 新到舊（§6b／§7ⓐ）
# ══════════════════════════════════════════════════════════════════════

def test_jv18_used_items_sort_last_by_usedat_descending(client, make_user):
    """🔴🔴 **排序：已使用的排在未使用之後，且已使用的兩筆之間新到舊。**

    ☠️ 只造 1 筆已使用的話，它「本來就在最後」時排序壞掉也會綠——
    ⇒ 造 **2 筆已使用（不同 `usedAt`）＋ 2 筆未使用**，
    已使用兩筆之間再驗一次先後順序。
    """
    import db
    import time
    quote_no = QUOTE_NO_PREFIX + "-SORT"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_a, fid_a = _seed_invoice_voucher_candidate(conn, quote_no, "jv18_sort_a")
        doc_b, fid_b = _seed_invoice_voucher_candidate(conn, quote_no, "jv18_sort_b")
        doc_u1, fid_u1 = _seed_invoice_voucher_candidate(conn, quote_no, "jv18_sort_u1")
        doc_u2, fid_u2 = _seed_invoice_voucher_candidate(conn, quote_no, "jv18_sort_u2")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_sort")
    v_a = _create_voucher(client, hdr, "JV18 排序測試A（先帶入）")
    _bring_in(client, hdr, v_a, "invoice_voucher", doc_a, fid_a)
    time.sleep(1.1)   # 確保 `uploaded_at`（多半是秒級精度）不同
    v_b = _create_voucher(client, hdr, "JV18 排序測試B（後帶入）")
    _bring_in(client, hdr, v_b, "invoice_voucher", doc_b, fid_b)

    items = _case_attachments(quote_no)
    ours = [x for x in items
           if x.get("docNo") in (doc_a, doc_b, doc_u1, doc_u2)
           and x.get("type") == "invoice_voucher"]
    assert len(ours) == 4, "候選憑證少了：%r" % ours

    used_flags = [bool(x.get("used")) for x in ours]
    first_used_idx = used_flags.index(True) if True in used_flags else len(ours)
    assert all(not f for f in used_flags[:first_used_idx]), (
        "已使用的憑證不在清單最後：%r" % ours)
    assert used_flags[first_used_idx:] == [True, True], (
        "應該有連續兩筆已使用的排在最後，實際：%r" % used_flags)

    used_tail = ours[first_used_idx:]
    assert used_tail[0].get("docNo") == doc_b, (
        "已使用那兩筆裡，較晚（`usedAt` 較新）的那筆沒有排在前面：\n%r"
        % used_tail)
    assert used_tail[1].get("docNo") == doc_a


# ══════════════════════════════════════════════════════════════════════
# ④ 已作廢的傳票用過的憑證，不算已使用（§3／§7ⓒ）
# ══════════════════════════════════════════════════════════════════════

def test_jv18_a_used_marker_disappears_after_the_voucher_is_voided(client,
                                                                    make_user):
    """🔴🔴 **傳票 A 帶入憑證 X 之後作廢，X 的「已計算」要消失。**

    🔑 先斷言作廢前**有**紅字，再作廢，再斷言**消失**（同一題兩段）——
    ☠️ 若那個憑證從頭到尾就沒有紅字，「消失」也會綠，那是假的通過。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-VOID"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_void")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_void")
    vid = _create_voucher(client, hdr, "JV18 作廢測試")
    _bring_in(client, hdr, vid, "invoice_voucher", doc_no, file_id)

    before = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert before.get("used") is True, (
        "作廢前應該先看到 `used=True`（前置不對，下面的『消失』會是假的通過）：\n%r"
        % before)

    v = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "JV18 測試作廢"}, headers=hdr)
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    after = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert not after.get("used"), (
        "傳票作廢之後，憑證仍然標著已計算：\n%r\n" % after
        + "☠️ 作廢重開會把附件複製到新單上，若作廢單也算已使用，\n"
          "   每一次作廢重開都會讓憑證被標記兩次，其中一次指向不存在的帳。")
    assert not (after.get("usedBy") or []), (
        "傳票作廢之後，`usedBy` 應該是空的：%r" % after.get("usedBy"))


# ══════════════════════════════════════════════════════════════════════
# ⑤ 直接上傳（`source_*` 全空）不可以互相亮紅字（§2c 後果一／§7ⓕ）
# ══════════════════════════════════════════════════════════════════════

def test_jv18_direct_uploads_with_empty_source_do_not_cross_mark_as_used(
        client, make_user):
    """🔴 **系統裡有多筆「直接上傳」附件（`source_*` 全是空字串）時，
    不可以讓一個從未被帶入的候選憑證被誤標成已使用。**

    ```
    _insert_attachment() 直接上傳那個呼叫點：
        source_type="" source_doc_no="" source_file_id=""
    ```
    ⚠️ 這幾列**互相之間**三個欄位逐一比對都會相等（都是空字串）——
    查詢若沒有排除空值，一種寫法（拿三個欄位分開各自 `IN` 一份清單，
    而不是整個三元組一起比對）會讓它們彼此「互相匹配」，把一個從未
    被帶入的候選憑證誤標成已使用。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-EMPTYSRC"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_emptysrc_candidate")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_emptysrc")
    # 種好幾筆「直接上傳」附件（source_* 全空），分掛在不同的傳票上，
    # 都與上面那個候選憑證**完全無關**。
    for i in range(3):
        vid = _create_voucher(client, hdr, "JV18 直接上傳測試%d" % i)
        upload_r = client.post(
            "/api/vouchers/%s/attachments" % vid, headers=hdr,
            files={"files": ("direct-%d.pdf" % i, b"%PDF-1.4 direct",
                            "application/pdf")})
        assert upload_r.status_code == 200, (
            "直接上傳失敗：%s %s" % (upload_r.status_code, upload_r.text[:200]))

    got = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert got is not None
    assert not got.get("used"), (
        "系統裡有多筆 `source_*` 全空的直接上傳附件，一個從未被帶入的\n"
        "候選憑證卻被標成已使用：\n%r\n" % got
        + "☠️ 這是假的紅字，比沒做還糟——使用者會開始不相信這個標記。")


# ══════════════════════════════════════════════════════════════════════
# ⑥ 已計算的憑證仍然可以再被帶入（只標記不擋住，§6c／§7ⓔ）
# ══════════════════════════════════════════════════════════════════════

def test_jv18_an_already_used_candidate_can_still_be_brought_in_again(
        client, make_user):
    """🔴 **負對照：已計算的憑證再被帶入一次，後端不可以拒絕。**

    使用者要的是「備註（紅字＋已計算）」，不是擋住——他沒有說不可以
    再帶入，而擋住是一個他沒有要求的行為改變，且會把作廢重開那條合法路
    （重開的新單要補帶同一份憑證）擋死。這一題釘的是**後端沒有加一個
    新的拒絕**；前端「不要把 `used` 加進 `:disabled`」是另一半，
    是人工／前端題，本檔管不到。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-REUSE"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv18_reuse")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv18_reuse")
    vid1 = _create_voucher(client, hdr, "JV18 重用測試①")
    _bring_in(client, hdr, vid1, "invoice_voucher", doc_no, file_id)

    vid2 = _create_voucher(client, hdr, "JV18 重用測試②")
    r = client.post("/api/vouchers/%s/attachments" % vid2, headers=hdr,
                    json={"picks": [
                        {"type": "invoice_voucher", "docNo": doc_no,
                         "fileId": file_id}]})
    assert r.status_code == 200, (
        "已計算的憑證再被帶入一次卻被拒絕（回 %s）：%s\n"
        % (r.status_code, r.text[:300])
        + "☠️ 使用者要的是備註不是擋住——擋住會把作廢重開那條合法路踩死。")
