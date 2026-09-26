# -*- coding: utf-8 -*-
"""`JV24` · 作廢重開不再讓 `JV18` 的已計算標記失效，並補上血緣
（`SPEC-JV24.md`，B 已實作 `abf4b60`）。

使用者原話：「JV24 作廢重開的追溯斷掉（嚴重度已降級，而『**會害你
重複入帳**』那一半仍然是真的）」——那句話裡的不變量就是①：原單帶入過
的憑證，作廢重開之後不可以變回「未使用」，否則同一張發票會被第二張
傳票再用一次。

# 🔴 為什麼要補題

B 沒有帶測試（協定：B 不寫測試，C 才寫）。B 自己的探針
`backend/tests/_zz_probe_jv24.py` 用完即刪，修復本身沒有任何一支
會重跑的題守著。

# ⚙️ 判準三格，刻意分開驗

```
① 作廢重開後，原本帶入過的憑證仍然 used=True（不變量本體）
② supersedes_no 串得起來（新單指得回舊單）
③ 🔴 鏈式兩層（A 作廢成 B、B 又作廢成 C）——兩層都要成立
   ☠️ 只驗一層的題，在「只處理最近一次」的實作上照樣綠
```
三題分開寫，不合成一題——合併的話某一格壞掉時分不出是哪一格。

# ✅ 牙齒已驗證（方式：歷史真碼／常設）

```
①③（used）  monkeypatch routers.vouchers._copy_attachments_to 換成
             abf4b60~1 那個真實的「修復前」版本（改寫 source_type 成
             "voucher"＋舊傳票 id），直接對本檔的 test_jv24_a_used_
             candidate_stays_used_after_void_and_reopen 與 test_jv24_
             a_two_level_void_reopen_chain_stays_correct_at_both_levels
             這兩支真的呼叫一次——兩支都真的紅：used 從 True 變 False，
             與 SPEC-JV24.md §3 描述的症狀完全一致。跑完即還原，不留
             痕跡。
②（supersedes_no）  直接讀 abf4b60 的 diff：舊版 INSERT INTO
             vouchers_all 的欄位清單裡沒有 supersedes_no，新版多了
             一欄且值是 src.get("voucher_no")——這是逐字可比對的 SQL
             文字差異，不需要另外執行去證明「舊版不會寫這一欄」。
```
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest

QUOTE_NO_PREFIX = "MQ-JV24"


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(conn, quote_no):
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name,"
        " project_name, total, pretax, data_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "已結案", "JV24測試客戶", "JV24測試案", 0, 0, "{}",
         "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
    conn.commit()


def _make_file(subfolder, file_id):
    import pathlib
    import helpers.uploads as up
    base = getattr(up, "UPLOADS_ROOT", None)
    assert base, "`helpers/uploads.py` 沒有 `UPLOADS_ROOT`——退回給我。"
    folder = pathlib.Path(str(base)) / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    real = folder / ("%s.pdf" % file_id)
    real.write_bytes(b"%PDF-1.4 jv24")
    return {"id": file_id, "name": "%s.pdf" % file_id,
            "path": "%s/%s" % (subfolder, real.name)}


def _seed_invoice_voucher_candidate(conn, quote_no, file_id):
    f = _make_file("invoice_vouchers", file_id)
    vno = "IV-" + file_id
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
    import helpers.voucher_attachments as va
    conn = db.get_db()
    try:
        return va.case_attachments(conn, quote_no, {"id": 0, "username": "att_test_root", "role": "superadmin", "modules": []})  # 驗清單內容，不是權限（權限見 test_attachments_providers）
    finally:
        conn.close()


def _find(items, source_type, doc_no, file_id):
    for x in items:
        if (x.get("type") == source_type and x.get("docNo") == doc_no
                and x.get("fileId") == file_id):
            return x
    return None


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


def _voucher_row(voucher_id):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        assert row is not None, "找不到傳票 id=%s" % voucher_id
        return dict(row)
    finally:
        conn.close()


def _void_and_reopen(client, hdr, voucher_id, reason="JV24測試作廢重開"):
    r = client.post("/api/vouchers/%s/void" % voucher_id,
                     json={"reason": reason, "reopen": True}, headers=hdr)
    assert r.status_code == 200, "作廢重開失敗：%s %s" % (r.status_code, r.text[:200])
    body = r.json()
    new_id = body.get("new_id")
    assert new_id, "作廢重開沒有回 `new_id`：%r" % body
    return new_id


# ══════════════════════════════════════════════════════════════════════
# ① 核心：作廢重開之後，原本帶入過的憑證仍然 used=True
# ══════════════════════════════════════════════════════════════════════

def test_jv24_a_used_candidate_stays_used_after_void_and_reopen(
        client, make_user):
    """🔴🔴 **核心：傳票 A 帶入憑證 X → 作廢重開成 B → X 仍然
    `used=True`，`usedBy` 指向 B（不是 A）。**

    ☠️ 這正是使用者原話「會害你重複入帳」的可觀測形式：改之前這裡會
    變回 `used=False`，使用者以為沒用過，再帶入一次造成重複入帳。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-CORE"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv24_core")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv24_core")
    vid_a = _create_voucher(client, hdr, "JV24核心測試A")
    _bring_in(client, hdr, vid_a, "invoice_voucher", doc_no, file_id)

    before = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert before.get("used") is True, (
        "帶入之後應該先看到 used=True（前置不對，後面的驗證會失去意義）：%r"
        % before)

    vid_b = _void_and_reopen(client, hdr, vid_a)
    no_b = _voucher_row(vid_b)["voucher_no"]

    after = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert after.get("used") is True, (
        "傳票 A 作廢重開成 B 之後，憑證變回「未使用」：%r\n" % after
        + "☠️ 使用者會以為沒用過，再帶入一次——這就是重複入帳。")
    used_by_nos = {e.get("voucherNo") for e in (after.get("usedBy") or [])}
    assert used_by_nos == {no_b}, (
        "`usedBy` 是 %r，應該只有新單 %r（不是舊的 A，也不能兩張都有）。"
        % (used_by_nos, no_b))


def test_jv24_negative_control_an_unrelated_direct_upload_is_unaffected(
        client, make_user):
    """⚙️ **正對照：作廢重開不會讓一個從沒被帶入過的候選憑證變成已使用。**

    ☠️ 少了它，「複製時一律填某個固定 source_type」這種修法（例如改填
    `COPY_SOURCE_TYPE` 以外的任意值）也可能讓上一題意外綠，卻同時把
    不相干的憑證誤標。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-UNRELATED"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        used_doc, used_fid = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv24_unrelated_used")
        idle_doc, idle_fid = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv24_unrelated_idle")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv24_unrelated")
    vid_a = _create_voucher(client, hdr, "JV24無關測試A")
    _bring_in(client, hdr, vid_a, "invoice_voucher", used_doc, used_fid)
    _void_and_reopen(client, hdr, vid_a)

    idle = _find(_case_attachments(quote_no), "invoice_voucher", idle_doc, idle_fid)
    assert not idle.get("used"), (
        "從沒被帶入過的憑證，在另一筆作廢重開之後被誤標成已使用：%r" % idle)


# ══════════════════════════════════════════════════════════════════════
# ② 血緣：supersedes_no 串得起來
# ══════════════════════════════════════════════════════════════════════

def test_jv24_supersedes_no_points_back_to_the_voided_voucher(
        client, make_user):
    """🔴🔴 **`supersedes_no`：新單要寫舊單的 `voucher_no`。**

    `db.py` 的 schema 註解逐字「本張取代了哪一張」，而這個欄位在
    `JV24` 之前從來沒被寫過——沒有附件的傳票作廢重開之後，新舊兩張單
    在資料庫裡完全找不到任何關聯。
    """
    _u, hdr = _hdr(client, make_user, "jv24_lineage")
    vid_a = _create_voucher(client, hdr, "JV24血緣測試A")
    no_a = _voucher_row(vid_a)["voucher_no"]

    vid_b = _void_and_reopen(client, hdr, vid_a)
    row_b = _voucher_row(vid_b)

    assert row_b.get("supersedes_no") == no_a, (
        "新單 B 的 `supersedes_no` 是 %r，應該是舊單 A 的 voucher_no %r。"
        % (row_b.get("supersedes_no"), no_a))


def test_jv24_negative_control_a_fresh_voucher_has_no_supersedes_no(
        client, make_user):
    """⚙️ **正對照：一張從未被作廢重開過的新傳票，`supersedes_no` 是空的。**"""
    _u, hdr = _hdr(client, make_user, "jv24_lineage_fresh")
    vid = _create_voucher(client, hdr, "JV24血緣測試新單")
    row = _voucher_row(vid)
    assert (row.get("supersedes_no") or "") == "", (
        "從未被取代過的新單，`supersedes_no` 卻不是空的：%r"
        % row.get("supersedes_no"))


# ══════════════════════════════════════════════════════════════════════
# ③ 鏈式兩層：A→B→C，兩層都要成立（與①②分開驗）
# ══════════════════════════════════════════════════════════════════════

def test_jv24_a_two_level_void_reopen_chain_stays_correct_at_both_levels(
        client, make_user):
    """🔴🔴 **鏈式兩層：A 作廢重開成 B，B 再作廢重開成 C——`used` 與
    `supersedes_no` 在兩層都要成立，不是只有第一層。**

    ☠️ 只驗一層（A→B）的題，會在「重開時只處理『原始那一張』，不是
    『上一張』」這種實作上照樣綠——例如硬寫死往回查一層而不是逐層串。
    """
    import db
    quote_no = QUOTE_NO_PREFIX + "-CHAIN"
    conn = db.get_db()
    try:
        _seed_case(conn, quote_no)
        doc_no, file_id = _seed_invoice_voucher_candidate(
            conn, quote_no, "jv24_chain")
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv24_chain")
    vid_a = _create_voucher(client, hdr, "JV24鏈式測試A")
    no_a = _voucher_row(vid_a)["voucher_no"]
    _bring_in(client, hdr, vid_a, "invoice_voucher", doc_no, file_id)

    vid_b = _void_and_reopen(client, hdr, vid_a, reason="鏈式第一節")
    no_b = _voucher_row(vid_b)["voucher_no"]

    vid_c = _void_and_reopen(client, hdr, vid_b, reason="鏈式第二節")
    row_c = _voucher_row(vid_c)
    no_c = row_c["voucher_no"]

    # ── 血緣：兩層都要串起來 ──
    assert row_c.get("supersedes_no") == no_b, (
        "C 的 `supersedes_no` 是 %r，應該是 B 的 voucher_no %r——\n"
        % (row_c.get("supersedes_no"), no_b)
        + "☠️ 若這裡變成 A，代表重開時是往回查『原始那一張』，不是"
          "『上一張』，鏈斷在中間看不出來。")
    row_b = _voucher_row(vid_b)
    assert row_b.get("supersedes_no") == no_a, (
        "B 的 `supersedes_no` 是 %r，應該是 A 的 voucher_no %r。"
        % (row_b.get("supersedes_no"), no_a))

    # ── 已計算標記：兩層之後仍然 used=True，且指向最新那一張 C ──
    final = _find(_case_attachments(quote_no), "invoice_voucher", doc_no, file_id)
    assert final.get("used") is True, (
        "鏈式兩層之後，憑證變回「未使用」：%r" % final)
    used_by_nos = {e.get("voucherNo") for e in (final.get("usedBy") or [])}
    assert used_by_nos == {no_c}, (
        "鏈式兩層之後 `usedBy` 是 %r，應該只有最新那一張 C 的 %r——\n"
        % (used_by_nos, no_c)
        + "☠️ 若含 A 或 B，代表某一層的附件複製把已作廢的舊單也算進去了；\n"
          "   若是空的，代表鏈斷在某一層，退回改之前的判斷。")


# ══════════════════════════════════════════════════════════════════════
# §7 靜態守門：_copy_attachments_to() 不可以把 source_type 改寫成 "voucher"
# ══════════════════════════════════════════════════════════════════════

import ast
import pathlib
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _copy_attachments_source():
    src = (ROOT / "routers" / "vouchers.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_copy_attachments_to"), None)
    assert fn is not None, "找不到 `_copy_attachments_to()`——退回改本題的錨點。"
    lines = src.splitlines()
    return "\n".join(lines[fn.lineno - 1:fn.end_lineno])


def _insert_attachments_calls_use_literal_voucher(src):
    """在原始碼片段裡找 `_insert_attachment(...)` 呼叫，檢查有沒有任何一個
    參數是字面字串 `"voucher"`——用 AST 常數比對，不是 regex 掃字串（避免
    撿到註解裡提到的 "voucher" 這個詞）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name != "_insert_attachment":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == "voucher":
                    return True
    return False


def test_jv24_copy_attachments_never_hardcodes_source_type_voucher():
    """✅ **AST 結構守門：`_copy_attachments_to()` 呼叫 `_insert_attachment()`
    時，任何一個參數都不可以是字面字串 `"voucher"`。**

    🔑 釘「不可以是什麼」不是「應該是什麼」——`SOURCE_TYPES` 現在 9 種，
    會長，釘死一個「應該原樣帶 `att['source_type']`」的形狀反而會在
    合法重構時誤報。
    """
    src = _copy_attachments_source()
    assert not _insert_attachments_calls_use_literal_voucher(src), (
        "`_copy_attachments_to()` 裡的 `_insert_attachment()` 呼叫用了"
        "字面字串 `\"voucher\"`——這正是 `JV24` 修掉的那個 bug："
        "複製附件時把 `source_type` 改寫成指向舊傳票。")


def test_jv24_scanner_positive_control_a_literal_voucher_argument_is_caught():
    """⚙️ **正對照（誘餌 C）：一個直接寫死 `source_type="voucher"` 的呼叫，
    掃描器要抓得到。**"""
    fake_src = (
        "def _copy_attachments_to(conn, old_id, new_id, who, now):\n"
        "    _insert_attachment(conn, new_id, file_id, name, rel,\n"
        "                       size, mime, \"voucher\", str(old_id),\n"
        "                       att[\"source_file_id\"], who, now)\n"
    )
    assert _insert_attachments_calls_use_literal_voucher(fake_src), (
        "誘餌（字面 \"voucher\"）沒有被抓到——掃描器本身壞了。")


def test_jv24_scanner_negative_controls_other_source_types_are_not_flagged():
    """⚙️ **正對照（誘餌 A／B）：原樣帶過去別的來源型別／空字串，
    掃描器不可以誤判成命中。**"""
    fake_src_extra_expense = (
        "def _copy_attachments_to(conn, old_id, new_id, who, now):\n"
        "    _insert_attachment(conn, new_id, file_id, name, rel,\n"
        "                       size, mime, att[\"source_type\"],\n"
        "                       att[\"source_doc_no\"],\n"
        "                       att[\"source_file_id\"], who, now)\n"
    )
    assert not _insert_attachments_calls_use_literal_voucher(fake_src_extra_expense), (
        "原樣帶過去 `att[\"source_type\"]`（不是字面字串）卻被誤判成命中"
        "——判準太寬了。")
