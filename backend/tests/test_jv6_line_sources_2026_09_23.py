# -*- coding: utf-8 -*-
"""`JV6` · 從既有單據帶入分錄（`SPEC-JV6.md`）——紅題先行，B 還沒實作。

# 🔴 這份是七步協定的正確順序：C 先寫紅，B 才寫碼

`JV24` 那一輪反過來了（B 先實作、C 後補題），A 已指出風險：「後寫的
題容易問『它現在做了什麼』，而那種題永遠會通過」。本檔在**任何實作
落地之前**寫成，牙齒是**天然的**——寫完當下就是紅的。每一支測試的
docstring 都明著記下**它現在為什麼紅**（端點不存在？欄位沒寫？），
因為 B 寫完之後若它還是紅，需要分得出是同一個原因還是新的原因。

# ⚙️ 本檔提議的 API 形狀（B 可以照這個做，或提出更好的、回來跟我談）

```
GET /api/vouchers/line-sources?type=<type>&quote_no=<quote_no>
    -> [{"sourceType", "sourceId", "docNo", "summary", "amount"}, …]
    ⚠️ 靜態路徑必須宣告在 /{voucher_id} 之前（JV21 踩過的那個 422 陷阱）

POST /api/vouchers 、 PUT /api/vouchers/{id}
    lines[] 的每一項目**新增兩個可選鍵**：
    {"account_code": "", "summary": "...", "debit": N, "credit": 0,
     "source_type": "invoice_voucher", "source_id": 5}
    ⚠️ `source_amount_snapshot` 不由前端送——後端拿 `source_type`＋
    `source_id` 自己重新解析金額寫入這一欄（同一份判準只有一份，不讓
    前端喊多少就記多少，防止篡改／算錯）。
```

# 🔴 判準：承攬商支出金額只有 `grandTotal` 對，`totalAmount` 會漏錢

```
           id=2（只有人員費）    id=3（只有項目費＋稅）
totalAmount        0.0                12,000.0
personnelTotal   3,500.0                    0
grandTotal       3,500.0 ✅          12,600.0 ✅
```
兩列是**天然對照組**（一列只有人員、一列只有項目），不是我們造的
誘餌——只測其中一列，`totalAmount` 的錯寫法在另一列上會照樣通過。
本檔額外**合成**一筆只有 `personnelTotal` 的假資料當誘餌（不用真實
資料當誘餌，真實資料可能被改掉）。

# ⚠️ 邊界（見 SPEC-JV6.md §1／§3）

```
① voucher_lines.source_type 與 voucher_attachments.source_type 同名
   不同表——本檔全部驗 voucher_lines，不要跟 JV3/JV18/JV24 的附件表搞混
② 本件只讀 case_extra_expenses WHERE category='材料'——JV21 讀全部四類，
   兩者不可以互相參照（本檔驗只有材料類會出現在候選清單）
③ 科目代號留空（使用者裁）——本檔斷言是空字串，不是某個值
④ source_amount_snapshot 是快照：原單金額改了，傳票上的值不跟著動
"""
import json

import pytest

LINE_SOURCES = "/api/vouchers/line-sources"
VOUCHERS = "/api/vouchers"


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name,"
            " project_name, total, pretax, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", "JV6測試客戶", "JV6測試案", 0, 0, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed_invoice_voucher(quote_no, voucher_no, amount):
    """`invoice_vouchers` 的金額在 `snapshot_json.amount`（照
    `routers/invoice_vouchers.py:116` 的既有讀法：
    `amount = float(d.get("amount") or 0)`）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status,"
            " snapshot_json, data_json, created_by, created_at, updated_at)"
            " VALUES (?,?,'single','已核准',?,?,'t','2026-09-01','2026-09-01')",
            (voucher_no, quote_no,
             json.dumps({"amount": amount}, ensure_ascii=False), "{}"))
        conn.commit()
    finally:
        conn.close()


def _seed_contractor_payment_voucher(client, hdr, quote_no, voucher_no,
                                      snapshot):
    """承攬商＋派發用真正的 HTTP 端點建立（FK 是真的），匯款申請本身直接
    SQL 插入並自組 `snapshot_json`——照抄
    `test_case_finance_summary_2026_09_09.py::_make_voucher` 的既有作法。
    """
    import db
    r = client.post("/api/vendor-contractors", headers=hdr,
                     json={"name": "JV6測試廠商" + voucher_no, "data": {}})
    assert r.status_code == 201, r.text
    vendor_id = r.json()["id"]

    r = client.post("/api/contractor-dispatches", headers=hdr, json={
        "quote_no": quote_no, "vendor_id": vendor_id, "status": "completed",
        "items_json": [{"description": "JV6測試品項", "qty": 1, "unit": "式",
                        "unitPrice": 1, "amount": 1}],
    })
    assert r.status_code == 201, r.text
    dispatch_id = r.json()["id"]

    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id,"
            " quote_no, vendor_id, status, snapshot_json, data_json,"
            " created_at, updated_at) VALUES (?,?,?,?,'已核准',?,?,?,?)",
            (voucher_no, dispatch_id, quote_no, vendor_id,
             json.dumps(snapshot, ensure_ascii=False), "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _create_voucher_with_lines(client, hdr, summary, lines):
    r = client.post(VOUCHERS, headers=hdr,
                     json={"summary": summary, "lines": lines})
    return r


def _voucher_lines(voucher_id):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM voucher_lines WHERE voucher_id = ? ORDER BY line_no",
            (voucher_id,))]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① GET /api/vouchers/line-sources：靜態路徑、閘門、三種來源
# ══════════════════════════════════════════════════════════════════════

def test_jv6_line_sources_endpoint_exists_and_is_not_swallowed_by_the_dynamic_route(
        client, make_user):
    """🔴🔴 **端點要存在，且靜態路徑 `/line-sources` 不能被 `/{voucher_id}`
    這條動態路由攔截。**

    🔑 現在為什麼紅：這支端點完全不存在——`JV21` 已經踩過同一個陷阱
    （`STATE.md §29117`）：若宣告順序反過來，`GET /line-sources` 會被
    當成 `voucher_id="line-sources"` 送進動態路由，int 轉換失敗回 422，
    不是乾淨的「端點不存在」404。這題同時驗兩種紅：**先確認不是
    422**（陷阱本身），再確認**不是 404**（端點真的存在）。
    """
    _u, hdr = _hdr(client, make_user, "jv6_exist")
    r = client.get(LINE_SOURCES + "?type=invoice_voucher&quote_no=NONE",
                    headers=hdr)
    assert r.status_code != 422, (
        "回 422——`/line-sources` 被 `/{voucher_id}` 那條動態路由攔截了"
        "（JV21 踩過的同一個陷阱，宣告順序要調整）：%s" % r.text[:200])
    assert r.status_code != 404, (
        "回 404——這支端點還沒有實作：%s" % r.text[:200])
    assert r.status_code == 200, "回 %s：%s" % (r.status_code, r.text[:200])


def test_jv6_line_sources_requires_login(client, make_user):
    """🔴 **閘門要與傳票其餘端點同一道**——沒登入打不進去。

    ⚠️ **這題現在是綠的，而不是因為端點已經對——是巧合**：實測沒登入時
    回 401（不是 404／422），代表有一層全站的 auth middleware 在路由
    比對之前就先擋掉了未認證的請求，跟 `/line-sources` 這條路徑本身
    存不存在無關。這題現在的綠**證明不了**端點已經有閘門，只是先佔住
    這個位置——等端點真的落地後這題才有意義，屆時若變紅要另外查原因，
    不要假設它「本來就綠、不會出問題」。
    """
    r = client.get(LINE_SOURCES + "?type=invoice_voucher&quote_no=NONE")
    assert r.status_code in (401, 403), (
        "沒有登入卻能查詢可帶入的單據（回 %s）——這支會列出案件與客戶名，"
        "放鬆等於從記帳畫面繞過去看客戶清單：%s" % (r.status_code, r.text[:200]))


def test_jv6_invoice_voucher_candidates_report_the_correct_amount(
        client, make_user):
    """🔴🔴 **發票候選清單的金額要對——`snapshot_json.amount`，不是猜的。**

    🔑 現在為什麼紅：端點不存在（見上）。B 寫完之後若這題還是紅，
    要分清楚是「端點還是 404／422」還是「端點在但金額欄位取值邏輯錯」。
    """
    quote_no = "MQ-JV6-INVOICE"
    _seed_case(quote_no)
    _seed_invoice_voucher(quote_no, "IV-JV6-001", 233725)

    _u, hdr = _hdr(client, make_user, "jv6_invoice")
    r = client.get(LINE_SOURCES,
                    params={"type": "invoice_voucher", "quote_no": quote_no},
                    headers=hdr)
    assert r.status_code == 200, r.text[:200]
    items = r.json()
    match = next((x for x in items if x.get("docNo") == "IV-JV6-001"), None)
    assert match is not None, "候選清單裡找不到剛種的發票：%r" % items
    assert match.get("amount") == 233725, (
        "發票金額是 %r，應該是 233725。" % match.get("amount"))


def test_jv6_contractor_payment_voucher_uses_grand_total_not_total_amount(
        client, make_user):
    """🔴🔴 **核心：兩筆天然對照組（只有人員費／只有項目費）都要用
    `grandTotal`，用 `totalAmount` 的話其中一筆會漏記整筆金額。**

    ```
    只有人員費那一列：totalAmount=0      grandTotal=3500   <- 對答案 3500
    只有項目費那一列：totalAmount=12000  grandTotal=12600  <- 對答案 12600
    ```
    ☠️ 只測其中一列的話，`totalAmount` 的錯寫法在另一列上會照樣通過
    ——這正是 `SPEC-JV6.md §6②` 明講的假綠燈來源。

    🔑 現在為什麼紅：端點不存在。
    """
    quote_no = "MQ-JV6-CPV"
    _seed_case(quote_no)
    _u, hdr = _hdr(client, make_user, "jv6_cpv")

    _seed_contractor_payment_voucher(
        client, hdr, quote_no, "PV-JV6-PERSONNEL-ONLY",
        {"totalAmount": 0.0, "taxAmount": 0, "totalWithTax": 0.0,
         "personnelTotal": 3500.0, "grandTotal": 3500.0})
    _seed_contractor_payment_voucher(
        client, hdr, quote_no, "PV-JV6-ITEMS-ONLY",
        {"totalAmount": 12000.0, "taxAmount": 600, "totalWithTax": 12600.0,
         "personnelTotal": 0, "grandTotal": 12600.0})

    r = client.get(LINE_SOURCES, params={
        "type": "contractor_payment_voucher", "quote_no": quote_no},
        headers=hdr)
    assert r.status_code == 200, r.text[:200]
    items = r.json()

    personnel_only = next(
        (x for x in items if x.get("docNo") == "PV-JV6-PERSONNEL-ONLY"), None)
    items_only = next(
        (x for x in items if x.get("docNo") == "PV-JV6-ITEMS-ONLY"), None)
    assert personnel_only is not None and items_only is not None, (
        "候選清單裡找不到剛種的兩筆：%r" % items)
    assert personnel_only.get("amount") == 3500, (
        "只有人員費那一列，金額是 %r，應該是 3500（grandTotal）——\n"
        % personnel_only.get("amount")
        + "☠️ 若是 0，代表取的是 `totalAmount`，人員費用整筆被漏記。")
    assert items_only.get("amount") == 12600, (
        "只有項目費那一列，金額是 %r，應該是 12600。" % items_only.get("amount"))


def test_jv6_scanner_positive_control_a_synthetic_snapshot_with_only_personnel_total(
        client, make_user):
    """⚙️ **誘餌（合成，不用真實資料）：一筆刻意只有 `personnelTotal` 的
    `snapshot_json`，`totalAmount` 明著是 0——讀不到 `grandTotal` 就退回
    `totalAmount` 的實作，必須紅在這一題上。**

    誘餌與受測對象是**同一種寫法**（都放在 `snapshot_json` 裡，不是額外
    的欄位），依 `SPEC-JV6.md §6②` 的要求：不要用真實資料當誘餌
    （id=2/id=3 可能被改掉），這裡自己合成一筆。
    """
    quote_no = "MQ-JV6-BAIT"
    _seed_case(quote_no)
    _u, hdr = _hdr(client, make_user, "jv6_bait")
    _seed_contractor_payment_voucher(
        client, hdr, quote_no, "PV-JV6-BAIT",
        {"totalAmount": 0.0, "personnelTotal": 9999.0, "grandTotal": 9999.0})

    r = client.get(LINE_SOURCES, params={
        "type": "contractor_payment_voucher", "quote_no": quote_no},
        headers=hdr)
    assert r.status_code == 200, r.text[:200]
    match = next((x for x in r.json() if x.get("docNo") == "PV-JV6-BAIT"), None)
    assert match is not None, "誘餌那一筆不在候選清單裡：%r" % r.json()
    assert match.get("amount") == 9999, (
        "誘餌的金額是 %r，應該是 9999（grandTotal）——\n" % match.get("amount")
        + "☠️ 若是 0，代表實作退回讀 `totalAmount`，這正是規格點名要擋的錯法。")


def test_jv6_only_material_category_extra_expenses_are_offered(
        client, make_user, seed_extra_expense):
    """🔴🔴 **`case_extra_expenses` 只有 `category='材料'` 會出現在候選
    清單裡——運費／工時／其他不算「購料發票」。**

    使用者原話只說「購料」，`SPEC-JV6.md §3②` 明裁：運費與工時不是購料，
    `JV21` 才是讀全部四類的那一個，兩者不可以互相參照。
    """
    quote_no = "MQ-JV6-CATEGORY"
    _seed_case(quote_no)
    seed_extra_expense(quote_no, total_cost=1500, category="材料",
                       description="JV6材料費")
    seed_extra_expense(quote_no, total_cost=2750, category="運費",
                       description="JV6運費（不該出現）")
    seed_extra_expense(quote_no, total_cost=1200, category="工時",
                       description="JV6工時（不該出現）")
    seed_extra_expense(quote_no, total_cost=15, category="其他",
                       description="JV6其他（不該出現）")

    _u, hdr = _hdr(client, make_user, "jv6_category")
    r = client.get(LINE_SOURCES, params={
        "type": "extra_expense_material", "quote_no": quote_no},
        headers=hdr)
    assert r.status_code == 200, r.text[:200]
    items = r.json()
    descs = {x.get("summary") for x in items}
    assert "JV6材料費" in descs or any(
        "材料" in (x.get("summary") or "") for x in items), (
        "材料費那一筆不在候選清單裡：%r" % items)
    assert not any("不該出現" in (x.get("summary") or "") for x in items), (
        "運費／工時／其他其中至少一類出現在候選清單裡：%r——\n" % items
        + "☠️ 這正是 `JV21` 的範圍，`JV6` 只帶「材料」這一類。")


# ══════════════════════════════════════════════════════════════════════
# ② 帶入之後：voucher_lines 的 source_* 三欄、科目留空、快照不跟著動
# ══════════════════════════════════════════════════════════════════════

# 🔴🔴 動工前要看：下面三題現在紅在一個比「欄位沒寫」更深的地方
#
# `SPEC-JV6.md §7②` 裁定「科目留空，由使用者自己選」，而
# `routers/vouchers.py::_check_account_codes()`（:106）**今天就會**對空
# `account_code` 回 400「第 N 行還沒有選會計科目」——這不是這支測試檔
# 的問題，是 `voucher_lines.account_code TEXT NOT NULL REFERENCES
# account_items(code)` 這個既有的 schema 約束與「留空」這個裁定正面
# 衝突：`account_items` 沒有 `code=''` 這一列，FK 過不了，不擋的話會是
# 未攔截的 500。⇒ 實作前要先決定：
#   甲 `_check_account_codes()` 對「這一行有 `source_type`／`source_id`
#      （代表這是帶入產生、還沒選科目）」的情況特赦，但**這樣寫進資料庫
#      的 `account_code` 仍然要有一個合法值**（FK 擋著），需要一個
#      「尚未選擇」的哨兵科目代號，或改成允許 `account_code` 真的是空
#      字串（那要嘛拿掉 NOT NULL／FK，要嘛在 `account_items` 種一列
#      `code=''` 當佔位）
#   乙 前端暫存在畫面上，**不送進資料庫**，直到使用者真的選了科目才
#      連同 `POST`／`PUT` 一起送出——那樣「留空」只存在於畫面，不進
#      `voucher_lines`
# 下面三題釘的是**甲的最終行為**（真的能存進資料庫且 account_code 是
# 空字串）；若裁定改成乙，這三題要跟著重寫成「先暫存、選了科目才真的
# 寫入」的形狀，不是這裡的斷言。已回報 A／A-2，這不是我能自己裁的
# 設計決定。

def test_jv6_bringing_in_a_line_writes_source_columns_and_leaves_account_blank(
        client, make_user):
    """🔴🔴 **帶入一張發票 ⇒ `voucher_lines` 出現
    `source_type='invoice_voucher'`／`source_id`＝該單 id／
    `source_amount_snapshot=233725`；`account_code` 留空。**

    🔑 現在為什麼紅：`_check_account_codes()` 對空 `account_code` 回
    400「第 1 行還沒有選會計科目」——見上面那段說明，這是 schema 約束
    與規格裁定的正面衝突，不是「欄位沒寫」那麼單純。
    """
    import db
    quote_no = "MQ-JV6-BRINGIN"
    _seed_case(quote_no)
    _seed_invoice_voucher(quote_no, "IV-JV6-BRINGIN", 233725)
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM invoice_vouchers WHERE voucher_no = ?",
                           ("IV-JV6-BRINGIN",)).fetchone()
        source_id = row["id"]
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv6_bringin")
    r = _create_voucher_with_lines(client, hdr, "JV6帶入測試", [
        {"account_code": "", "summary": "帶入自 IV-JV6-BRINGIN",
         "debit": 233725, "credit": 0,
         "source_type": "invoice_voucher", "source_id": source_id},
        {"account_code": "4111", "summary": "配平", "debit": 0, "credit": 233725},
    ])
    assert r.status_code == 200, "建立失敗：%s %s" % (r.status_code, r.text[:300])
    vid = r.json()["id"]

    lines = _voucher_lines(vid)
    matched = next((l for l in lines if l["source_type"] == "invoice_voucher"), None)
    assert matched is not None, (
        "帶入的那一列 `source_type` 不是 `invoice_voucher`：%r" % lines)
    assert matched["source_id"] == source_id, (
        "`source_id` 是 %r，應該是 %r。" % (matched["source_id"], source_id))
    assert matched["source_amount_snapshot"] == 233725, (
        "`source_amount_snapshot` 是 %r，應該是 233725。"
        % matched["source_amount_snapshot"])
    assert matched["account_code"] == "", (
        "帶入的分錄 `account_code` 是 %r，使用者裁定科目留空、自己選。"
        % matched["account_code"])


def test_jv6_bringing_in_the_two_contractor_payment_voucher_pairs_both_use_grand_total(
        client, make_user):
    """🔴🔴 **下游驗證同一件事：帶入 id=2／id=3 這兩種天然對照組，
    寫進 `voucher_lines.source_amount_snapshot` 的都要是 `grandTotal`。**

    與 ①「查詢清單金額對」分開驗——那題驗的是**查詢端**回什麼，這題驗
    的是**真的寫進資料庫**的是什麼，兩者若用不同邏輯算，可能一個對
    一個錯。

    🔑 現在為什麼紅：與上一題同一個原因（`_check_account_codes()` 擋空
    `account_code`），見上面那段「動工前要看」的說明。
    """
    import db
    quote_no = "MQ-JV6-BRINGIN-CPV"
    _seed_case(quote_no)
    _u, hdr = _hdr(client, make_user, "jv6_bringin_cpv")

    id_personnel = _seed_contractor_payment_voucher(
        client, hdr, quote_no, "PV-JV6-BI-PERSONNEL",
        {"totalAmount": 0.0, "personnelTotal": 3500.0, "grandTotal": 3500.0})
    id_items = _seed_contractor_payment_voucher(
        client, hdr, quote_no, "PV-JV6-BI-ITEMS",
        {"totalAmount": 12000.0, "taxAmount": 600, "totalWithTax": 12600.0,
         "personnelTotal": 0, "grandTotal": 12600.0})

    for source_id, expect_amount, label in (
            (id_personnel, 3500, "只有人員費"),
            (id_items, 12600, "只有項目費")):
        r = _create_voucher_with_lines(client, hdr, "JV6帶入測試-" + label, [
            {"account_code": "", "summary": label,
             "debit": expect_amount, "credit": 0,
             "source_type": "contractor_payment_voucher", "source_id": source_id},
            {"account_code": "4111", "summary": "配平",
             "debit": 0, "credit": expect_amount},
        ])
        assert r.status_code == 200, "建立失敗（%s）：%s %s" % (
            label, r.status_code, r.text[:300])
        vid = r.json()["id"]
        lines = _voucher_lines(vid)
        matched = next(
            (l for l in lines if l["source_type"] == "contractor_payment_voucher"),
            None)
        assert matched is not None, "%s：帶入的那一列找不到 source_type" % label
        assert matched["source_amount_snapshot"] == expect_amount, (
            "%s：`source_amount_snapshot` 是 %r，應該是 %r——\n"
            % (label, matched["source_amount_snapshot"], expect_amount)
            + "☠️ 若是 0（人員費那組）或 12000（項目費那組），代表寫入端"
              "用的是 `totalAmount` 不是 `grandTotal`。")


def test_jv6_the_amount_snapshot_does_not_change_when_the_source_document_changes(
        client, make_user):
    """🔴 **快照不跟著原單動：發票金額之後改了，傳票上記的還是帶入當時
    的數字。**

    依據 `SPEC-JV6.md §4`：沿用 `JV18`／`JV7` 已經裁過的原則——「帶入是
    起點不是終點」，快照就是快照，理由是會計的：傳票一旦過帳，記的就是
    那一刻的事實。

    🔑 現在為什麼紅：與上面兩題同一個原因（`_check_account_codes()`
    擋空 `account_code`），見「動工前要看」的說明。
    """
    import db
    quote_no = "MQ-JV6-SNAPSHOT"
    _seed_case(quote_no)
    _seed_invoice_voucher(quote_no, "IV-JV6-SNAPSHOT", 10000)
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM invoice_vouchers WHERE voucher_no = ?",
                           ("IV-JV6-SNAPSHOT",)).fetchone()
        source_id = row["id"]
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv6_snapshot")
    r = _create_voucher_with_lines(client, hdr, "JV6快照測試", [
        {"account_code": "", "summary": "帶入測試", "debit": 10000, "credit": 0,
         "source_type": "invoice_voucher", "source_id": source_id},
        {"account_code": "4111", "summary": "配平", "debit": 0, "credit": 10000},
    ])
    assert r.status_code == 200, r.text[:300]
    vid = r.json()["id"]

    # 原單金額之後改了（例如發票重開重填）。
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE invoice_vouchers SET snapshot_json = ? WHERE id = ?",
            (json.dumps({"amount": 999999}, ensure_ascii=False), source_id))
        conn.commit()
    finally:
        conn.close()

    lines = _voucher_lines(vid)
    matched = next((l for l in lines if l["source_type"] == "invoice_voucher"), None)
    assert matched is not None
    assert matched["source_amount_snapshot"] == 10000, (
        "原單金額改成 999999 之後，傳票上的快照變成 %r——\n"
        % matched["source_amount_snapshot"]
        + "☠️ 傳票一旦過帳，記的就是那一刻的事實，不該跟著原單即時重算。")
