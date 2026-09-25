# -*- coding: utf-8 -*-
"""`BN6` · 獎金分潤單的明細表 ＋ 可預覽（`docs/windows/SPEC-BN6-BN7.md`）。

使用者原話（逐字）：
```
「獎金單需要詳細有張表格，像是精算頁面一樣，報價多少、成本多少、衍生成本、
  比例最後總利潤多少，再用這個利潤去拆發比例，可預覽、可匯出pdf」
```

# 🔴 `BN6` 一個數字都不要算

10%／1% 只寫在 `settlement.html`；再算一次就是**第三份實作**
（`modules/payroll/bonus.py` 模組 docstring 已寫死這條）。本檔的每一題釘的都是
「有沒有把既有的值原樣帶出來」，不是「數字對不對」。

# ⚠️ 本檔只涵蓋 `§6` 後端 ①～⑤（`BN6`）

`BN7`（PDF／用印欄）**不寫題** —— A 2026-09-23 裁：它被 `BN8` 擋著
（用印欄列數要讀簽核鏈，而獎金單的簽核流程還沒做完）。

# ⚙️ `POST /awards/plan/{quote_no}` 是**既有路徑多一個動詞**，不是新端點

`GET` 那條已經存在（`test_bonus_award_plan_2026_09_23.py` 20 題全綠），
`SPEC-BN6-BN7.md §2` 逐字：「同一個路徑、同一個 body 形狀」⇒ 這裡**不用**
`openapi.json` 動態找（那是給還沒定案的端點名字用的，`mark-paid` 那種）——
這裡的路徑已經被 `GET` 釘死了，只是多驗一個方法。

# 📌 `lines` 與 `remainder` 的回應形狀是本檔宣告的（規格沒有定死鍵名）

```
lines 每筆   {bonus_item_id, username, person_source_snapshot,
              total_pct, person_pct, amount}
             <= 逐字比照 bonus_award_lines 的欄名，因為 §6④ 驗收釘的
                就是「與 bonus_award_lines 逐筆相等」
remainder    單一項目分配時 == remainder_of(base, total_pct, lines) 的值
             ⚠️ 多項目時怎麼加總，規格沒有定義 —— 本檔只驗單一項目，
                不替多項目的情況發明一條規則
```
⚠️ 若 B 選用不同鍵名，**退回給我改本檔的欄位對照表**，
   不要為了配合欄位名去改產品的回應格式（那會把契約倒過來定）。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn6_preview_lines_match_the_award_exactly
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import json

import pytest

from modules.payroll.bonus import LEGACY_SETTLEMENT_MESSAGE, remainder_of, split_award

PLAN = "/api/bonus/awards/plan/%s"

#: `§166`：這個 repo 裡「端點不存在」有三種臉，都不算「正常回應」。
OK_CODES = (200, 400, 403)

#: `SPEC-BN6-BN7.md §1`：逐字抄 `settlement.html` 的十二格鍵名。
#: ⚠️ 改動任何一個字要回 `frontend/pages/settlement.html` 對照過。
SETTLEMENT_FIELDS = (
    "quotedPretax", "quotedTotal",
    "itemActualTotal", "extraTotal", "dispatchTotal", "totalActualCost",
    "grossProfit", "grossMarginPct", "adminCost", "charityDonation",
    "netProfit", "netMarginPct",
)

#: 一組**內部自洽**的完整精算摘要（十二格都有值）。數字本身不重要——
#: `BN6` 不重算，這裡只是拿一組固定值去驗「有沒有原樣帶出來」。
FULL_SUMMARY = {
    "quotedPretax": 1000000, "quotedTotal": 1050000,
    "itemActualTotal": 400000, "extraTotal": 50000, "dispatchTotal": 100000,
    "totalActualCost": 550000,
    "grossProfit": 450000, "grossMarginPct": 45.0,
    "adminCost": 45000, "charityDonation": 4500,
    "netProfit": 400500, "netMarginPct": 40.05,
}

#: `LINE_FIELDS`：本檔宣告的 `lines` 逐筆欄位（見檔頭「回應形狀」）。
LINE_FIELDS = ("bonus_item_id", "username", "person_source_snapshot",
              "total_pct", "person_pct", "amount")


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no, summary, sales_person="alice", deal_tag="已結案",
              settle_status="finalized"):
    """種一個帶精算摘要的案件。`summary` 直接塞進 `data_json.settlement.summary`
    ——**不補齊、不驗證**，缺什麼欄位由呼叫端決定（測「缺欄位」就是要缺）。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, sales_person, deal_tag, "
            "data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試案", 0, 0, sales_person,
             deal_tag,
             json.dumps({"settlement": {"status": settle_status,
                                        "summary": summary}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed_item(name="業務獎金", person_source="sales_person", is_active=1):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, "
            "is_active, created_by, created_at, updated_at) "
            "VALUES (?,?,0,?,'seed','2026-09-01','2026-09-01')",
            (name, person_source, is_active))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _plan_get(client, hdr, quote_no):
    r = client.get(PLAN % quote_no, headers=hdr)
    assert r.status_code in OK_CODES, (
        "`GET plan` 回 %s：%s" % (r.status_code, r.text[:200]))
    return r


def _plan_post(client, hdr, quote_no, allocations):
    """`§2`：既有路徑多一個動詞，**不是新端點** —— 直接打，不繞 openapi 探測。"""
    r = client.post(PLAN % quote_no, headers=hdr,
                    json={"allocations": allocations})
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`POST %s` 回 %s —— 這一支動詞還沒接上。\n"
            % (PLAN % quote_no, r.status_code)
            + "📌 `SPEC-BN6-BN7.md §2`：這是 `GET` 那條既有路徑多一個動詞，\n"
              "   同一個 body 形狀（與 `POST /awards` 的 `allocations` 相同）。")
    assert r.status_code in OK_CODES, (
        "`POST plan` 回 %s：%s" % (r.status_code, r.text[:200]))
    return r


def _settlement_of(payload):
    """從回應裡取出十二格精算摘要 —— **本檔宣告它就是 `settlement` 那一格本身**
    （見檔頭「回應形狀」）。找不到就講清楚看到了什麼鍵，不要空手回報。
    """
    s = payload.get("settlement")
    if s is None:
        pytest.fail(
            "回應裡沒有 `settlement` 這一格。現有鍵：%r\n" % sorted(payload)
            + "📌 `SPEC-BN6-BN7.md §2`：plan 要多回一格 `settlement`，\n"
              "   把 `summary` 原樣帶出來。")
    return s


def _award_lines_of(quote_no):
    """走 API 拿不到逐行明細（`GET /awards` 只回有效單的可見列），
    直接讀資料庫 —— **這是驗收的下游觀測點**，不是我的前置。
    """
    import db
    conn = db.get_db()
    try:
        aid = conn.execute(
            "SELECT id FROM bonus_awards WHERE quote_no = ? AND voided_at = ''",
            (quote_no,)).fetchone()
        assert aid is not None, "案件「%s」沒有任何有效獎金單。" % quote_no
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_lines WHERE award_id = ?"
            " ORDER BY id", (aid["id"],))]
        return rows
    finally:
        conn.close()


def _line_key(row_or_dict):
    """`(bonus_item_id, username)` —— 在單一項目的測試場景裡足以識別一筆。"""
    return (int(row_or_dict.get("bonus_item_id") or 0),
           row_or_dict.get("username"))


def _extract_preview_lines(payload):
    lines = payload.get("lines")
    if lines is None:
        pytest.fail(
            "`POST plan` 的回應裡沒有 `lines`。現有鍵：%r\n" % sorted(payload)
            + "📌 `SPEC-BN6-BN7.md §2`：回 `{settlement, base, lines, remainder}`。")
    return lines


# ══════════════════════════════════════════════════════════════════════
# ① settlement 鍵名逐字相同
# ══════════════════════════════════════════════════════════════════════

def test_bn6_plan_echoes_the_full_settlement_summary_verbatim(client,
                                                              make_user):
    """🔴 **`§6①`：`GET /plan` 回的 `settlement` 與 `settlement.summary` 逐字相同。**

    ⚙️ 十二格的**值**逐一比對，不是只比對存不存在 ——
       半桶水的原樣帶出（例如只挑幾格）與完全沒做，對使用者是同一件事。
    """
    _u, hdr = _hdr(client, make_user, "bn6_echo")
    _seed_case("MQ-BN6-ECHO", FULL_SUMMARY)
    r = _plan_get(client, hdr, "MQ-BN6-ECHO")
    settlement = _settlement_of(r.json())
    for k in SETTLEMENT_FIELDS:
        assert settlement.get(k) == FULL_SUMMARY[k], (
            "`settlement.%s` 是 %r，案件存的是 %r。\n"
            % (k, settlement.get(k), FULL_SUMMARY[k])
            + "☠️ 原樣帶出來的意思是**一個字都不改**——\n"
              "   對不上的話下一個人要維護兩套對照表。")


def test_bn6_plan_does_not_recompute_the_ten_percent(client, make_user):
    """⚙️ **正對照：10%／1% 不是 `BN6` 自己算的。**

    ☠️ 少了它，一個「plan 自己拿 `grossProfit * 0.1` 算 `adminCost`」的實作
       在**這一筆**數字剛好對得上時也會讓上一題綠 —— 而下一筆案件換了比例，
       兩邊就會分岔。
    ⚙️ 手法：`adminCost` 故意存一個**不符合 10% 公式**的值，
       驗 `settlement.adminCost` 讀到的是**存的那個值**，不是重算出來的。
    """
    weird = dict(FULL_SUMMARY)
    weird["adminCost"] = 1  # grossProfit 的 10% 應該是 45000，這裡故意存 1
    _u, hdr = _hdr(client, make_user, "bn6_norecompute")
    _seed_case("MQ-BN6-NORECOMP", weird)
    r = _plan_get(client, hdr, "MQ-BN6-NORECOMP")
    settlement = _settlement_of(r.json())
    assert settlement.get("adminCost") == 1, (
        "存的 `adminCost` 是 1（刻意不符合 10% 公式），\n"
        "回應卻是 %r。\n" % settlement.get("adminCost")
        + "☠️ 這代表 `plan` 自己重算了管銷分攤，而不是原樣帶出 `settlement` 的值\n"
          "   —— `modules/payroll/bonus.py` 模組 docstring 明著禁止**第三份實作**。")


# ══════════════════════════════════════════════════════════════════════
# ② 缺欄位回 null，不是 0
# ══════════════════════════════════════════════════════════════════════

def test_bn6_a_missing_field_comes_back_null_not_zero(client, make_user):
    """🔴 **`§6②`：缺 `dispatchTotal` 的案件，那一格回 `null`，不是 `0`。**

    ```
    dispatchTotal 不存在 = 這個案件沒有派過承攬商（今天 13 筆裡 6 筆是這樣）
    印 0                = 「派了而金額為零」——**兩件事**（〈null 不等於 0〉）
    ```
    ⚠️ 而**回應裡要有這把鍵**（值是 `None`），不是整把鍵都不見 ——
       否則前端 `summary.dispatchTotal` 讀到的是 `undefined`，
       跟「派發成本是 0」在畫面上**分不出來**，與缺欄位分不出來也是同一族問題。
    """
    no_dispatch = {k: v for k, v in FULL_SUMMARY.items() if k != "dispatchTotal"}
    _u, hdr = _hdr(client, make_user, "bn6_missing")
    _seed_case("MQ-BN6-MISSING", no_dispatch)
    r = _plan_get(client, hdr, "MQ-BN6-MISSING")
    payload = r.json()
    settlement = _settlement_of(payload)
    assert "dispatchTotal" in settlement, (
        "回應裡整把 `dispatchTotal` 都不見了，現有鍵：%r\n" % sorted(settlement)
        + "☠️ 前端讀到 `undefined`，跟『派發成本是 0』分不出來 ——\n"
          "   缺欄位與「值是 0」必須是**不同的可觀測狀態**。")
    assert settlement.get("dispatchTotal") is None, (
        "沒有派發承攬商的案件，`dispatchTotal` 回的是 %r（型別 %s）。\n"
        % (settlement.get("dispatchTotal"), type(settlement.get("dispatchTotal")))
        + "☠️ 印 0 的話畫面上會顯示「派了而金額為零」，\n"
          "   而事實是**這個案件從來沒有派過承攬商**。")
    # 正對照：其餘十一格不受影響。
    for k in SETTLEMENT_FIELDS:
        if k == "dispatchTotal":
            continue
        assert settlement.get(k) == FULL_SUMMARY[k], (
            "缺 `dispatchTotal` 卻連帶影響了 `%s`：%r（預期 %r）。\n"
            % (k, settlement.get(k), FULL_SUMMARY[k]))


# ══════════════════════════════════════════════════════════════════════
# ③ summary 空的案件：十二格全 null，講得出出路
# ══════════════════════════════════════════════════════════════════════

def test_bn6_an_empty_summary_case_gets_all_nulls_and_the_real_error(
        client, make_user):
    """🔴 **`§3`／`§6③`：`summary == {}` 的案件（`MQ-EXPFILE-001` 那種）。**

    ```
    表格   十二格全部印「—」            <= settlement 十二格全 null
    基數   base_amount_for 的原話       <= 舊格式訊息，**必須講出路**
    出路   重新開啟並儲存一次該案的精算
    ```
    ⚙️ `base.error` 直接 `import` `LEGACY_SETTLEMENT_MESSAGE` 比對，
       不手動抄一份文字 —— 訊息改了這裡自動跟著改，不會分岔成兩份。
    """
    _u, hdr = _hdr(client, make_user, "bn6_empty")
    _seed_case("MQ-BN6-EMPTY", {})
    r = _plan_get(client, hdr, "MQ-BN6-EMPTY")
    payload = r.json()
    settlement = _settlement_of(payload)
    for k in SETTLEMENT_FIELDS:
        assert settlement.get(k) is None, (
            "`summary` 是空的，而 `settlement.%s` 回 %r（預期 `None`）。\n"
            % (k, settlement.get(k)))
    base = payload.get("base") or {}
    assert base.get("ok") is False, (
        "`summary` 是空的，而 `base.ok` 是 %r（預期 `False`）。" % base.get("ok"))
    assert base.get("error") == LEGACY_SETTLEMENT_MESSAGE, (
        "`base.error` 是 %r，\n" % base.get("error")
        + "而 `base_amount_for()` 的原話是 %r。\n" % LEGACY_SETTLEMENT_MESSAGE
        + "🔑 這句話是使用者唯一看得到的東西，**改寫過的版本可能講不出出路**。")


# ══════════════════════════════════════════════════════════════════════
# ④ 核心：預覽的 lines 與產生後 bonus_award_lines 逐筆相等
# ══════════════════════════════════════════════════════════════════════

def test_bn6_preview_does_not_write_anything(client, make_user):
    """⚙️ **正對照：`POST /plan` 只是算給你看，不寫進資料庫。**

    ☠️ 少了它，上一題「兩邊一致」也可能是因為**兩個端點是同一支**、
       預覽本身就已經把單建出來了 —— 那樣「一致」是必然的，不是被驗出來的。
    """
    _u, hdr = _hdr(client, make_user, "bn6_noeffect")
    _seed_case("MQ-BN6-NOEFFECT", FULL_SUMMARY, sales_person="bn6_noeffect")
    item_id = _seed_item()
    allocations = [{"bonus_item_id": item_id, "total_pct": 5000,
                    "person_pct": {"bn6_noeffect": 10000}}]

    _plan_post(client, hdr, "MQ-BN6-NOEFFECT", allocations)

    import db
    conn = db.get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM bonus_awards WHERE quote_no = ?",
            ("MQ-BN6-NOEFFECT",)).fetchone()["n"]
    finally:
        conn.close()
    assert n == 0, (
        "打完 `POST /plan` 之後，`bonus_awards` 裡多了 %d 筆「MQ-BN6-NOEFFECT」。\n"
        % n
        + "☠️ 預覽端點寫進了資料庫 —— 使用者按「預覽」看一眼，\n"
          "   單就已經產生了，而他可能根本沒打算發。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ remainder 與 remainder_of() 一致
# ══════════════════════════════════════════════════════════════════════

def test_bn6_preview_remainder_matches_remainder_of(client, make_user):
    """🔴 **`§6⑤`：預覽回的 `remainder` == `remainder_of()` 的值。**

    ⚠️ 只驗**單一項目**分配的情況 —— 多項目時 remainder 怎麼加總，
       `SPEC-BN6-BN7.md` 沒有定義，本檔不替它發明一條規則。

    ☠️ 不印 remainder 的後果（規格逐字）：使用者自己加總，
       發現「加起來不等於淨利」，**而他不知道那是設計**（尾差歸公司）。
    """
    _u, hdr = _hdr(client, make_user, "bn6_remainder")
    # 刻意選一個除不盡的 base，讓 remainder 非零，正對照才有意義。
    summary = dict(FULL_SUMMARY)
    summary["netProfit"] = 100003
    _seed_case("MQ-BN6-REMAINDER", summary, sales_person="bn6_remainder")
    item_id = _seed_item()
    # 🔴 **我第一版的數字讓正對照的前提不成立**：`person_pct=10000`（100%）
    #    時，一個人拿走整個 `pool`，`Σamount == pool` **必然**成立，
    #    remainder 恆為 0，不管 base 選得多不整除都一樣。
    #    ⇒ 要故意**少發**（`person_pct < 10000`）才會有尾差可驗。
    #    已實跑：`base=100003, total_pct=10000, person_pct=9999` -> remainder=11。
    total_pct = 10000
    person_pct = {"bn6_remainder": 9999}
    allocations = [{"bonus_item_id": item_id, "total_pct": total_pct,
                    "person_pct": person_pct}]

    preview = _plan_post(client, hdr, "MQ-BN6-REMAINDER", allocations)
    payload = preview.json()
    remainder = payload.get("remainder")
    assert remainder is not None, (
        "回應裡沒有 `remainder`（現有鍵：%r）。\n" % sorted(payload)
        + "☠️ 使用者會自己加總，發現「加起來不等於淨利」，\n"
          "   而他不知道那是設計（尾差歸公司）。")

    base = payload.get("base") or {}
    lines = split_award(base.get("amount"), total_pct,
                        list(person_pct.items()))
    expected = remainder_of(base.get("amount"), total_pct, lines)
    assert expected != 0, (
        "正對照本身的前提不成立：這組數字算出來的 remainder 是 0，\n"
        "驗不出「有沒有真的回傳」與「回傳 0」的差別。換一組除不盡的數字。")
    assert remainder == expected, (
        "預覽回的 `remainder` 是 %r，`remainder_of()` 算出來是 %r。\n"
        % (remainder, expected)
        + "☠️ 兩邊對不上，表上印出來的尾差跟實際入帳的不一致。")
