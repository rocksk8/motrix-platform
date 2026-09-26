# -*- coding: utf-8 -*-
"""`SP1` · 「選一個案件」要看得到**全部九類**憑證（`§195`／`§198`）。

```
_CASE_SCOPED（doc_no ＝案件編號或 {quote_no}_{idx}）  **5**
不在裡面（doc_no ＝自己的 id／單號）                  **4**
   extra_expense ／ invoice_voucher ／
   contractor_dispatch ／ contractor_invoice
收斂 5 + 4 = SOURCE_TYPES **9**
```
☠️ 那四類現在**選不到** —— 而畫面上看起來只是「這個案件沒有那一類」，
   不像一個缺陷。

# ☠️ `extra_expense` 最會騙人

```
表名 case_extra_expenses  —— **字面上就有 case**
而 source_files 用的是 **id** 不是 quote_no  ⇒ 「選一個案件」一樣看不到它
```
🔑 B 漏掉的正是它（D 複核抓到）。**名字像的東西最不會被複查。**

# 🔴🔴 而有一格只有測試擋得住：**兩類共用同一個 `docNo`**

```
contractor_dispatch  -> contractor_dispatches.id -> files_json          ┐同一張表
contractor_invoice   -> contractor_dispatches.id -> invoice_files_json  ┘同一個 doc_no
```
⇒ **任何只用 `docNo` 當鍵的清單／去重／畫面，會把兩組併成一組，
   而少的那一組不會報錯。**
✅ `resolve_picks()` 用 `(type, docNo, fileId)` 三元組 ⇒ **後端不會撞**。
⚠️ 風險在**清單與畫面**：一張派工單要出現**兩列**（承攬商文件／廠商發票）。
⇒ 本檔那一題釘的是「**同一個 `docNo` 的兩類各自出現**」，**不是「有幾筆」**。

# ⚠️ 那四類的表**全部有 `quote_no` 欄**

（D 逐一列過：`case_extra_expenses` 22 欄／`invoice_vouchers` 13 欄／
`contractor_dispatches` 13 欄）⇒ `case_attachments()` 多一個
`SELECT id/voucher_no FROM <表> WHERE quote_no = ?` 就涵蓋全部九類
⇒ **不需要新的選取介面**。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import pathlib

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

QUOTE_NO = "MQ-SP1-001"

#: `§198`：`doc_no` **不是**案件編號的那四類 —— 現在選不到的就是它們。
NOT_CASE_SCOPED = ("extra_expense", "invoice_voucher",
                   "contractor_dispatch", "contractor_invoice")

#: 共用同一個 `docNo` 的那兩類（同一張表、只有欄位不同）。
SAME_DOC_NO = ("contractor_dispatch", "contractor_invoice")


def _subcontract_installed():
    from core import source_tree
    return source_tree.module_installed("modules/subcontract/")


#: 派工單兩類由外包工班（M04）的 `attachments.for_document` 提供：模組不在時那兩類本來就不列
#: （傳票頁另外明說，見 tests/platform/test_attachments_providers.py），驗它們的題跟著略過（PLAYBOOK §B-11）
_NEEDS_M04 = pytest.mark.skipif(not _subcontract_installed(), reason="外包工班（M04）不在這個安裝包：派工單兩類不提供")


def _helpers():
    import helpers.voucher_attachments as va
    return va


def _uploads_root():
    import helpers.uploads as up
    base = getattr(up, "UPLOADS_ROOT", None)
    assert base, "`helpers/uploads.py` 沒有 `UPLOADS_ROOT` —— **退回給我**。"
    return pathlib.Path(str(base))


def _make_file(subfolder, file_id):
    folder = _uploads_root() / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    real = folder / ("%s.pdf" % file_id)
    real.write_bytes(b"%PDF-1.4 sp1")
    return {"id": file_id, "name": "%s.pdf" % file_id,
            "path": "%s/%s" % (subfolder, real.name)}


def _seed(conn):
    """把那四類各種一筆，全部掛在同一個案件 `QUOTE_NO` 底下。

    ⚠️ 兩個 `contractor_*` **刻意種在同一張派工單上** ——
       那正是 `docNo` 相同的那一格。
    """
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, "
        "project_name, total, pretax, data_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (QUOTE_NO, "已結案", "測試客戶", "測試案", 0, 0, "{}",
         "2026-09-01T00:00:00", "2026-09-01T00:00:00"))

    made = {}

    # ① extra_expense —— doc_no 是它自己的 id
    f = _make_file("case_extra_expense", "sp1_xe")
    cur = conn.execute(
        "INSERT INTO case_extra_expenses (quote_no, category, description,"
        " qty, unit, unit_cost, total_cost, note, expense_date, doc_no,"
        " files_json, created_by, created_by_name, created_by_inferred,"
        " payer_username, payer_name, created_at, updated_at,"
        " updated_by_name, status, approval_json, change_status, change_json)"
        " VALUES (?,?,?,1,'式',100,100,'','2026-09-01','',?,"
        "'t','測試',0,'t','測試','2026-09-01','2026-09-01','測試',"
        "'已核准','{}','',' ')",
        (QUOTE_NO, "材料", "額外支出", json.dumps([f])))
    made["extra_expense"] = (str(cur.lastrowid), f["id"])

    # ② invoice_voucher —— doc_no 是 voucher_no
    f = _make_file("invoice_vouchers", "sp1_iv")
    conn.execute(
        "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status,"
        " snapshot_json, data_json, created_by, created_at, updated_at,"
        " issued_files_json) VALUES (?,?,'single','草稿','{}','{}','t',"
        "'2026-09-01','2026-09-01',?)",
        ("IV-SP1-001", QUOTE_NO, json.dumps([f])))
    made["invoice_voucher"] = ("IV-SP1-001", f["id"])

    # ③④ 兩個 contractor_* —— **同一張派工單**，docNo 相同
    fd = _make_file("contractor_dispatches", "sp1_cd")
    fi = _make_file("contractor_dispatch_invoices", "sp1_ci")
    cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(contractor_dispatches)")}
    assert {"quote_no", "files_json", "invoice_files_json"} <= cols, (
        "`contractor_dispatches` 少了欄位（現有：%s）——\n" % sorted(cols)
        + "📌 `files_json`／`invoice_files_json` 是 `ALTER TABLE` 補的"
          "（`db.py:1873/:2462`），**不在 CREATE TABLE 裡** ⇒ 真的不存在的話\n"
          "   `source_files` 會是 `OperationalError` 不是空清單。")
    need = [c for c in ("quote_no", "files_json", "invoice_files_json")]
    cur = conn.execute(
        "INSERT INTO contractor_dispatches (%s) VALUES (?,?,?)"
        % ", ".join(need),
        (QUOTE_NO, json.dumps([fd]), json.dumps([fi])))
    did = str(cur.lastrowid)
    made["contractor_dispatch"] = (did, fd["id"])
    made["contractor_invoice"] = (did, fi["id"])

    conn.commit()
    return made


@pytest.fixture()
def seeded(client):
    import db
    conn = db.get_db()
    try:
        made = _seed(conn)
    finally:
        conn.close()
    return made


def _listed(seeded_ignored=None):
    import db
    conn = db.get_db()
    try:
        return _helpers().case_attachments(conn, QUOTE_NO, {"id": 0, "username": "att_test_root", "role": "superadmin", "modules": []})  # 驗清單內容，不是權限（權限見 test_attachments_providers）
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 四類都要看得到
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("source_type", [
    t if t not in SAME_DOC_NO else pytest.param(t, marks=_NEEDS_M04) for t in NOT_CASE_SCOPED])
def test_sp1_a_case_scoped_list_includes_the_four_missing_types(
        seeded, source_type):
    """🔴 **選一個案件，那四類憑證要出現在清單裡。**（%s）

    ☠️ 現在選不到，而症狀是「這個案件沒有那一類」—— **看起來不像缺陷**。
    ⚠️ 特別是 `extra_expense`：表名叫 `case_extra_expenses`、
       **字面上就有 case**，而 `source_files` 用的是 `id` 不是 `quote_no`
       ⇒ **名字像的東西最不會被複查**（B 漏的正是它）。
    ⚙️ 觀測點是 `(type, fileId)` —— 只數筆數的話，
       四類少一類而總數還是「有東西」。
    """ % source_type
    doc_no, file_id = seeded[source_type]
    got = _listed()
    hit = [x for x in got
           if x.get("type") == source_type and x.get("fileId") == file_id]
    assert hit, (
        "「%s」沒有出現在案件 `%s` 的憑證清單裡。\n" % (source_type, QUOTE_NO)
        + "清單裡有的型別：%s\n" % sorted({x.get("type") for x in got})
        + "📌 `§198`：那四類的表**都有 `quote_no` 欄** ⇒ `case_attachments()`\n"
          "   多一個 `SELECT … WHERE quote_no = ?` 就涵蓋得到，"
          "**不需要新的選取介面**。")
    assert hit[0].get("docNo") == doc_no, (
        "`docNo` 是 %r，而它的來源鍵是 %r —— 帶入時會對不上。"
        % (hit[0].get("docNo"), doc_no))


def test_sp1_the_list_covers_every_declared_source_type(seeded):
    """🔴 **可數完備：清單涵蓋得到的型別 ＝ `SOURCE_TYPES` 全部九類。**

    ☠️ 少一類的症狀**不是錯誤**：那一類的憑證從來不出現，
       而〈沒有人會發現一個從來不出現的東西〉。
    ⚠️ 這一題釘的是**涵蓋範圍**，不是「我種的那幾筆」——
       所以它用 `SOURCE_TYPES` 當母體，而不是用我的 seed。
    """
    va = _helpers()
    declared = set(va.SOURCE_TYPES)
    scoped = set(getattr(va, "_CASE_SCOPED", ()))
    assert declared, "`SOURCE_TYPES` 是空的 —— **尺量不到東西**。"

    missing = sorted(declared - scoped)
    assert not missing, (
        "`case_attachments()` 涵蓋不到這 %d 類：%s\n" % (len(missing), missing)
        + "☠️ 那幾類的憑證**從來不會出現在任何一張傳票上**，\n"
          "   而畫面上看起來只是「這個案件沒有那一類」。\n"
        + "📌 `§198`：四類的表都有 `quote_no` 欄 ⇒ 一行查詢就涵蓋得到。\n"
        + "⚠️ 若你用別的機制涵蓋（不是加進 `_CASE_SCOPED`），**退回給我**"
          "改這一題的觀測點 —— 而**不要**把這一題刪掉。")


# ══════════════════════════════════════════════════════════════════════
# ② 核心：兩類共用同一個 docNo
# ══════════════════════════════════════════════════════════════════════

@_NEEDS_M04
def test_sp1_two_types_that_share_a_doc_no_both_show_up(seeded):
    """🔴🔴 **同一個 `docNo` 的兩類要**各自出現**，不是併成一列。**

    ```
    contractor_dispatch  -> contractor_dispatches.id -> files_json          ┐同一張表
    contractor_invoice   -> contractor_dispatches.id -> invoice_files_json  ┘同一個 id
    ```
    ⇒ **任何只用 `docNo` 當鍵的清單／去重／畫面，會把兩組併成一組**
      —— 而少的那一組**不會報錯**：清單上那一張派工單還在，只是少了一半。
    ✅ `resolve_picks()` 用 `(type, docNo, fileId)` 三元組 ⇒ 後端不會撞。
    ⚠️ 風險在**這一層**（清單）與畫面。

    ⚙️ 觀測點是 **`(type, docNo)` 兩個都要在**，不是「有幾筆」——
       只數筆數的話，兩筆併成一筆之後還是「有東西」。
    """
    did_a, fid_a = seeded["contractor_dispatch"]
    did_b, fid_b = seeded["contractor_invoice"]
    assert did_a == did_b, (
        "前置不對：我要的是**同一張派工單**，而兩者的 docNo 是 %r／%r。"
        % (did_a, did_b))

    got = _listed()
    by_type = {t: [x for x in got
                   if x.get("type") == t and x.get("docNo") == did_a]
               for t in SAME_DOC_NO}

    for t in SAME_DOC_NO:
        assert by_type[t], (
            "同一張派工單 `%s` 上，「%s」那一組不見了。\n" % (did_a, t)
            + "清單裡這個 docNo 的：%r\n"
            % [(x.get("type"), x.get("fileId")) for x in got
               if x.get("docNo") == did_a]
            + "☠️ **只用 `docNo` 當鍵去重**的話，兩組會併成一組 ——\n"
              "   而少的那一組不會報錯：那張派工單還在，**只是少了一半**。")

    ids = {x.get("fileId") for t in SAME_DOC_NO for x in by_type[t]}
    assert {fid_a, fid_b} <= ids, (
        "兩組的 fileId 對不上：期望 %r，實際 %r\n" % ({fid_a, fid_b}, ids)
        + "⚠️ 兩個欄位（`files_json`／`invoice_files_json`）拿錯一個的話，\n"
          "   **筆數對而內容是另一種單據的附件**（`§193` 的同族）。")


@_NEEDS_M04
def test_sp1_deduping_by_doc_no_alone_would_lose_one(seeded):
    """⚙️ **反向控制：證明「只用 `docNo` 去重」真的會少一組。**

    ☠️ 少了這一題，上面那一題綠可能只是「**今天剛好沒有人去重**」——
       而它要防的是**未來有人加一行去重**。
    🔑 這一題不碰產品：它拿清單自己算一次「若只用 `docNo` 當鍵會剩幾筆」，
      並要求那個數字**比正確的少** ⇒ 證明那個鍵**不足以辨識**。
    ⚠️ 若哪天兩者的 `docNo` 不再相同，這一題會紅 —— **那時它已經沒有意義了，
       請刪掉它**，不要改期望值（characterization test 要自帶死亡條件）。
    """
    did, _f = seeded["contractor_dispatch"]
    got = [x for x in _listed() if x.get("docNo") == did]
    assert len(got) >= 2, (
        "同一個 docNo 上只有 %d 筆 —— 先看上一題。" % len(got))

    by_doc_only = {x.get("docNo") for x in got}
    by_type_doc = {(x.get("type"), x.get("docNo")) for x in got}
    assert len(by_doc_only) < len(by_type_doc), (
        "只用 `docNo` 當鍵與用 `(type, docNo)` 當鍵**得到一樣多的東西** ——\n"
        + "☠️ 那表示這個反向控制**現在證明不了任何事**。\n"
        + "✅ 若兩類的 `docNo` 真的不再相同了，**刪掉這一題**，\n"
          "   不要改期望值 —— 它釘的是一個已經消失的風險。")
