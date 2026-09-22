"""§9 QL1–QL15 · 報價單綁據點。

使用者裁示：「**報價單綁據點這件做**」。§5 多據點剛落地，這一節把「據點」
從一張通訊錄變成**一個會印在單據上的身分**。

---

# 🔑 A 實查到的兩件，它們決定了這一節的形狀

## ① 所有單據表都掛在 `quote_no` 上

```
case_action_items / case_change_requests / case_extra_expenses / case_stages /
case_updates / completion_notes / contractor_dispatches /
contractor_payment_vouchers / invoice_vouchers / network_plans /
payment_requests / quotations / shipping_notes / stock_items
```
⇒ **據點綁在 `quotations` 一處就好**（QL1）。
☠️ 每張單各存一次的話，會製造「同一個案子的兩張單印不同抬頭」。
⚠️ 唯一例外 `payslips` —— 它掛 `contractor_id`，**是人事文件不是案件文件**（QL8）。

## ② 公司身分有兩個來源，狀況完全不同

```
抬頭   pdf_gen.py 寫死                  ← 我實測：8 支 builder 各 4 行，共 32 行
銀行   pdf_gen.py:2006 讀 company_profile ← 只有 1 處
```
☠️ **所以「綁據點」不是一件事，是兩件。**

---

# 🔴 我在寫題時查到的三件，A 的條文裡沒有

## ⓐ `_build_payslip_html` **一行公司身分都沒有寫死**

它的抬頭來自**呼叫端傳進來的 dict**：
```python
pdf_gen.py:502   company = d.get('companyName', '')
pdf_gen.py:805   html_content = _build_payslip_html(d)
pdf_gen.py:801   d = json.loads(row["data_json"] or "{}")
```
⇒ 🔴 **那是開單時寫進 `payslips.data_json` 的快照** ——
☠️ **而 QL10 裁的是「讀即時值，不做快照」。**
📌 ⇒ QL8 不是「把寫死的換成據點」，是**把一個既有的快照改成即時讀取**，
而那會改變既有薪資單重印時的內容。**已回報 A。**

## ⓑ `_build_payment_request_html` 比別人多一行

它的「戶　　名」來自 `company_profile` 的銀行欄位（QL9 要改的那一處）。
⇒ `company_profile` 為空時那一行**不出現** ⇒ 下面的基準是在**空設定**下取的。

## ⓒ 基準（`GOLDEN`）是 2026-09-22 用**還沒改過的** `pdf_gen.py` 跑出來的

🔑 `QL6` 的驗收條件是**逐字相同**，而「改版前」這個基準
**只有在 B 動手之前取得才算數**。
⚠️ 〈把今天的實作釘成不變量〉我踩過五次 —— 這一次它是對的，
理由很窄：**規格明著把「與改版前逐字相同」寫成驗收條件。**
📌 而釘的範圍**剛好是身分那幾行**，不是整份文件（日期、金額本來就該變）。
"""
import json
import sys
from pathlib import Path

import pytest

#: 單獨跑一個檔時 `sys.path` 不含 `tests/` —— pytest 的自動插入發生在
#: 收集那一刻，而 `from ... import` 發生在匯入那一刻。
#: 「整批跑得起來」不等於「單獨跑得起來」，而單獨跑正是除錯時的跑法。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pdf_identity as I  # noqa: E402

#: 🔴 2026-09-22 的基準 —— **B 改 `pdf_gen.py` 之前**跑出來的身分行。
#: 📌 在 `company_profile` 為空（既有安裝什麼都沒填）的條件下取得。
GOLDEN = {
    "_build_quote_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_shipping_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_contractor_voucher_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_invoice_voucher_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_payment_request_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_case_closing_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "本文件含案件內部財務與成本資訊，僅供內部留存查核使用，不對外提供 ｜ MOTRIX Synergy Integration Corp. 允碩整合集創",
    ),
    "_build_project_execution_report_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "本文件彙整案件執行過程資訊，僅供內部留存查核使用 ｜ MOTRIX Synergy Integration Corp. 允碩整合集創",
    ),
    "_build_completion_html": (
        "<div class=\"co-name\">允碩整合集創股份有限公司</div>",
        "<div class=\"co-sub\">MOTRIX Synergy Integration Corp.</div>",
        "<div class=\"co-sub\" style=\"margin-top:4px\">統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com</div>",
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481",
    ),
    "_build_payslip_html": (
    ),
}


#: ⚠️ `address` 是必填（§5 的驗證：沒有地址的據點會在地圖上變成
#: 「定位不到的據點」，而那與「使用者真的填錯了」長得一樣）。
#: ☠️ 我第一版沒給地址 ⇒ QL3／QL4 紅在 `422 沒有地址` ——
#: **紅在一個與題目無關的理由上，而那種紅會被讀成「功能還沒做」。**
PRIMARY = {
    "id": "L1", "name": "台中總公司",
    "address": "台中市西屯區台灣大道三段301號",
    "company_name": "", "company_name_en": "", "tax_id": "",
    "phone": "", "email": "",
}

BRANCH = {
    "id": "L2", "name": "台北分公司",
    "address": "台北市信義區市府路1號",
    "company_name": "允碩台北分公司",
    "company_name_en": "MOTRIX Taipei Branch",
    "tax_id": "12345678",
    "phone": "02-1234-5678",
    "email": "taipei@example.invalid",
    "bank_name": "台北富邦銀行",
    "bank_branch": "信義分行",
    "bank_account_name": "允碩台北分公司",
    "bank_account_number": "98765432109876",
}


def _need(name):
    import pdf_gen
    fn = getattr(pdf_gen, name, None)
    assert fn is not None, (
        f"`pdf_gen.py` 缺少 `{name}` —— 見本檔〈我釘的接縫〉"
    )
    return fn


@pytest.fixture
def blank_profile(monkeypatch):
    """`company_profile` 為空 —— 既有安裝什麼都沒填的狀態。"""
    import pdf_gen
    monkeypatch.setattr(
        pdf_gen, "_get_setting",
        lambda key, default=None: {} if key == "company_profile" else default,
        raising=False)


# ══════════════════════════════════════════════════════════════════════
# QL6 · 既有安裝不會壞的保證（逐字）
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("builder", I.BUILDERS)
def test_ql6_a_blank_profile_prints_exactly_what_it_prints_today(
        builder, blank_profile):
    """QL6：所有據點的抬頭欄位留空 ⇒ **與改版前逐字相同**。

    這是「既有安裝不會壞」的保證：使用者什麼都不填，PDF 跟今天一模一樣。
    沒有它，B 一改那 32 行，所有既有使用者的單據都可能變樣而沒有人發現。

    基準是 2026-09-22 用還沒改過的 `pdf_gen.py` 跑出來的（見檔頭 ⓒ）。
    比對前把連續半形空白壓成一個 —— 排版改動不該讓這一題紅，
    而全形空白不壓（它是那行內容的一部分）。
    """
    got = I.normalise(I.identity_lines(I.render(builder)))
    want = list(GOLDEN[builder])
    assert got == want, (
        f"`{builder}` 印出來的公司身分跟改版前不一樣：\n"
        f"  現在：{got}\n"
        f"  改版前：{want}\n"
        "既有安裝什麼都沒填時，PDF 必須逐字不變。"
    )


def test_ql6_the_baseline_is_not_empty():
    """量尺：基準本身要有東西，否則上面那 9 題是在比對兩個空清單。

    `_build_payslip_html` 是唯一合法的空的一支 —— 它一行公司身分都沒有寫死
    （抬頭來自呼叫端傳進來的 dict，見檔頭 ⓐ）。
    """
    empty = [k for k, v in GOLDEN.items() if not v]
    assert empty == ["_build_payslip_html"], (
        f"基準裡有非預期的空項目：{empty}\n"
        "一個比對兩個空清單的斷言，永遠是綠的。"
    )
    assert sum(len(v) for v in GOLDEN.values()) >= 30, (
        f"基準只有 {sum(len(v) for v in GOLDEN.values())} 行 —— 抓取八成失效了"
    )


# ══════════════════════════════════════════════════════════════════════
# 我釘的接縫，以及它為什麼要連「有沒有呼叫者」一起釘
# ══════════════════════════════════════════════════════════════════════
#
# 我釘一支 `pdf_gen.location_identity(location_id) -> dict`：
#     company_name / company_name_en / tax_id / phone / email
#     bank_name / bank_branch / bank_account_name / bank_account_number
#
# 每一欄留空 ⇒ 沿用主要據點的同一欄（QL5）；
# 主要據點也留空 ⇒ 沿用現在寫死的那組值（QL6）。
#
# 🔴 **而這一次我要連「它真的被呼叫」一起釘，理由是今天付過學費：**
# `reminder_stage()` 也是我釘的接縫，寫得好好的、題目全綠，
# ☠️ **而產品碼零呼叫者** —— 那四題在測一支沒有人跑的函式。
# 🔑 ⇒ 所以 QL7 的做法是**換掉這支函式的回傳值，看 8 支 builder 的輸出有沒有變**。
# 📌 那一題同時回答兩件事：「值有沒有被用」與「誰在用它」，
#    而單獨釘函式本身只回答得了前者。


@pytest.fixture
def identity(monkeypatch):
    """把 `location_identity` 換成可控的替身，回傳一個 `{id: 值}` 的登記簿。"""
    import pdf_gen
    fn = getattr(pdf_gen, "location_identity", None)
    if fn is None:
        pytest.fail(
            "`pdf_gen.py` 缺少 `location_identity(location_id)` —— "
            "見本檔〈我釘的接縫〉。8 支單據的抬頭要從這裡取值。")
    table = {}

    def _fake(location_id=None, **kw):
        return table.get(location_id, table.get(None, {}))

    monkeypatch.setattr(pdf_gen, "location_identity", _fake)
    return table


# ══════════════════════════════════════════════════════════════════════
# QL1 / QL2 · 資料模型
# ══════════════════════════════════════════════════════════════════════

def _columns(table):
    import db
    conn = db.get_db()
    try:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_ql2_the_location_is_a_real_column_not_a_json_key(client):
    """QL2：用真的欄位 `location_id TEXT`，不要塞進 `data_json`。

    理由不是效能，是日後營運報表會想「按據點分組」，而 `data_json` 查不動。
    """
    cols = _columns("quotations")
    assert "location_id" in cols, (
        f"`quotations` 沒有 `location_id` 欄位，現有欄位：{sorted(cols)}")


def test_ql2_the_migration_version_moved(client):
    """QL2：新增欄位要一次 migration，`CURRENT_VERSION` 要往前走。

    釘的是「比 89 大」不是「等於 90」—— 等於 90 的話，
    B 與別的視窗同時各加一個 migration 時這一題會紅在一個假的理由上。
    兩人同時加 migration，git 不會衝突、只會在執行時撞版本號。
    """
    import db
    assert db.CURRENT_VERSION > 89, (
        f"`CURRENT_VERSION` 還是 {db.CURRENT_VERSION} —— 沒有加 migration")


def test_ql1_downstream_documents_do_not_each_store_their_own_location(client):
    """QL1：據點只綁在 `quotations`，下游全部經由 `quote_no` 繼承。

    一個案子只屬於一個據點，而所有單據都是那個案子的產物。
    每張單各存一次的話，會製造「同一個案子的兩張單印不同抬頭」——
    而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。

    判準是「哪些表有 `quote_no`」而不是一份手寫的表名清單：
    手寫清單漏掉的永遠是「後來才加的那一張」。
    """
    import db
    conn = db.get_db()
    try:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()

    offenders = []
    for name in tables:
        cols = _columns(name)
        if name == "quotations" or "quote_no" not in cols:
            continue
        if "location_id" in cols:
            offenders.append(name)
    assert not offenders, (
        "這些下游單據表各自存了一份據點：" + "、".join(offenders)
        + "。據點要綁在 quotations，其餘經由 quote_no 繼承。")


# ══════════════════════════════════════════════════════════════════════
# QL3 / QL4 · 既有資料與新建
# ══════════════════════════════════════════════════════════════════════

def _set_locations(client, token, locations):
    r = client.put("/api/settings/company-profile",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"locations": locations})
    assert r.status_code == 200, r.text


def _superadmin(client, make_user, name):
    username, password = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.231"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_ql3_no_quotation_is_left_without_a_location(client, make_user):
    """QL3：既有報價單全部指向主要據點，**不可以留 NULL**。

    一張沒有據點的報價單，PDF 要嘛壞掉、要嘛安靜地退回某個預設，
    而後者就是這一節正在修的那一族。

    這一題查的是**整張表**而不是「我剛建的那一筆」——
    migration 要照顧的正是「我沒有建的那些」。
    """
    import db
    token = _superadmin(client, make_user, "ql3_admin")
    _set_locations(client, token, [dict(PRIMARY)])

    assert "location_id" in _columns("quotations"), (
        "`quotations` 還沒有 `location_id` 欄位（見 QL2）—— "
        "這一題要等那一步，而它現在紅得對：**既有資料還沒有家可以放。**")

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, data_json) VALUES (?,?,?)",
            ("MQ-202601-900", "草稿", "{}"))
        conn.commit()
        bad = conn.execute(
            "SELECT quote_no FROM quotations "
            "WHERE location_id IS NULL OR TRIM(location_id) = ''").fetchall()
    finally:
        conn.close()
    assert not bad, (
        "這些報價單沒有據點："
        + "、".join(r["quote_no"] for r in bad)
        + "。欄位要 NOT NULL 並有預設，或 migration 要把它們補成主要據點。")


def test_ql4_a_new_quotation_defaults_to_the_primary_location(client, make_user):
    """QL4：新建報價單時據點預設為主要據點，**且可改**。

    兩半都要驗：只驗「有預設」的話，一個寫死主要據點、
    完全不看送進來的值的實作會綠 —— 而分公司就永遠開不出自己的單。
    """
    token = _superadmin(client, make_user, "ql4_admin")
    auth = {"Authorization": f"Bearer {token}"}
    _set_locations(client, token, [dict(PRIMARY), dict(BRANCH)])

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "data": {"customerName": "甲"}})
    assert r.status_code == 201, r.text
    no_default = r.json().get("quoteNo") or r.json().get("quote_no")

    r = client.get(f"/api/quotations/{no_default}", headers=auth)
    assert r.status_code == 200, r.text
    got = r.json().get("locationId") or r.json().get("location_id")
    assert got == PRIMARY["id"], (
        f"沒送據點時應該落在主要據點 {PRIMARY['id']}，實際 {got!r}")

    r = client.post("/api/quotations", headers=auth,
                    json={"status": "草稿", "locationId": BRANCH["id"],
                          "data": {"customerName": "乙"}})
    assert r.status_code == 201, r.text
    no_branch = r.json().get("quoteNo") or r.json().get("quote_no")
    r = client.get(f"/api/quotations/{no_branch}", headers=auth)
    got = r.json().get("locationId") or r.json().get("location_id")
    assert got == BRANCH["id"], (
        f"送了 {BRANCH['id']} 而存成 {got!r} —— 據點改不動，分公司開不出自己的單")
