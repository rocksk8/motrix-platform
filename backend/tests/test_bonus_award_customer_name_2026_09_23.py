# -*- coding: utf-8 -*-
"""`BN15` · 獎金單只有案件編號，沒有客戶／案件名稱。

使用者驗 `BN10` 回報：「獎金單的只有編號，沒有案件名稱」。

# 🔴 動工前查證：現況與 A 回報一致

```
GET /api/bonus/awards        SELECT * FROM bonus_awards        <= 只有 quote_no
GET /api/bonus/awards/{id}   同樣沒有

bonus_awards 表本身也沒有 customer_name／project_name 欄位
（db.py:4644 CREATE TABLE 逐一核對過）

而「產生」那一側有：bonus.py:393
    SELECT quote_no, customer_name, project_name, data_json
    FROM quotations WHERE deal_tag = ? AND …
```
⇒ 同一頁上，「要產生的案件」看得到客戶名，「已產生的單」只剩編號——
使用者選案件時看得到，選完存起來卻不見了。

# ⚙️ 落地形狀：**JOIN `quotations`，不要存進 `bonus_awards`**

A 已告知 B：不要在 `bonus_awards` 存一份客戶名快照——那會變成第二份
會漂移的資料（`quotations.customer_name` 改了，`bonus_awards` 裡那份
舊的不會跟著動，稽核時兩邊對不上）。⇒ `③` 直接測這個反面：**造出快照
式的錯誤修法會被抓到**——建立獎金單之後才改 `quotations.customer_name`，
獎金單那邊要跟著變，不是維持建立當下的舊值。

📌 前端欄位是 snake_case（`bonus.html:255-257` 既有的 `c.customer_name`
／`c.quote_no`），本檔沿用同一種命名，不猜 camelCase。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _hdr, _seed_award,
)

QUOTE_NO_PREFIX = "MQ-BN15"


def _seed_quotation(quote_no, customer_name="", project_name=""):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name,"
            " project_name, total, pretax, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", customer_name, project_name, 0, 0, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _update_quotation_customer_name(quote_no, new_name):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET customer_name = ? WHERE quote_no = ?",
                     (new_name, quote_no))
        conn.commit()
    finally:
        conn.close()


def _list_awards(client, hdr):
    r = client.get(AWARDS, headers=hdr)
    assert r.status_code == 200, "讀不到獎金清單：%s" % r.text[:200]
    return r.json().get("awards") or []


def _find(awards, aid):
    for a in awards:
        if int(a.get("id") or 0) == int(aid):
            return a
    pytest.fail("清單裡找不到 id=%s 的獎金單。現有：%r"
               % (aid, [a.get("id") for a in awards]))


def _award_detail(client, hdr, aid):
    r = client.get("%s/%s" % (AWARDS, aid), headers=hdr)
    assert r.status_code == 200, "讀不到獎金單明細：%s" % r.text[:200]
    return r.json()


# ══════════════════════════════════════════════════════════════════════
# ① 清單要看得到客戶名／案件名
# ══════════════════════════════════════════════════════════════════════

def test_bn15_the_award_list_includes_the_customer_and_project_name(
        client, make_user):
    """🔴🔴 **核心：`GET /awards` 每一筆要帶得出客戶名與案件名。**"""
    quote_no = QUOTE_NO_PREFIX + "-LIST"
    _seed_quotation(quote_no, "正達科技股份有限公司", "廠區安控案")
    aid = _seed_award(quote_no, ["someone"])

    _u, hdr = _hdr(client, make_user, "bn15_list")
    a = _find(_list_awards(client, hdr), aid)
    assert a.get("customer_name") == "正達科技股份有限公司", (
        "清單裡這張獎金單的 `customer_name` 是 %r，預期案件的客戶名。"
        % a.get("customer_name"))
    assert a.get("project_name") == "廠區安控案", (
        "清單裡這張獎金單的 `project_name` 是 %r，預期案件的案件名。"
        % a.get("project_name"))


# ══════════════════════════════════════════════════════════════════════
# ② 明細（彈窗）也要看得到——使用者原話涵蓋兩處
# ══════════════════════════════════════════════════════════════════════

def test_bn15_the_award_detail_includes_the_customer_and_project_name(
        client, make_user):
    """🔴🔴 **`GET /awards/{id}` 也要帶得出來——彈窗標題與清單列，
    使用者說的涵蓋兩處，只修清單會漏掉彈窗。**
    """
    quote_no = QUOTE_NO_PREFIX + "-DETAIL"
    _seed_quotation(quote_no, "京城凱悅飯店", "監控系統更新案")
    aid = _seed_award(quote_no, ["someone"])

    _u, hdr = _hdr(client, make_user, "bn15_detail")
    d = _award_detail(client, hdr, aid)
    assert d.get("customer_name") == "京城凱悅飯店", (
        "明細裡的 `customer_name` 是 %r。" % d.get("customer_name"))
    assert d.get("project_name") == "監控系統更新案", (
        "明細裡的 `project_name` 是 %r。" % d.get("project_name"))


# ══════════════════════════════════════════════════════════════════════
# ③ 對照組：不可以變成一份會漂移的快照
# ══════════════════════════════════════════════════════════════════════

def test_bn15_customer_name_tracks_the_live_quotation_not_a_frozen_copy(
        client, make_user):
    """🔴🔴 **反向控制：改 `quotations` 的客戶名，獎金單那邊要跟著變。**

    ☠️ A 已告知 B 不要在 `bonus_awards` 存一份客戶名快照——那會變成
    第二份會漂移的資料。少了這一題，「建立獎金單時把客戶名複製一份
    存進 `bonus_awards`」這種修法也會讓 `①②` 變綠，而稽核時兩邊會
    對不上（案件資料改了，獎金單上還是舊的）。
    """
    quote_no = QUOTE_NO_PREFIX + "-DRIFT"
    _seed_quotation(quote_no, "舊客戶名稱", "案件名")
    aid = _seed_award(quote_no, ["someone"])

    _u, hdr = _hdr(client, make_user, "bn15_drift")
    before = _find(_list_awards(client, hdr), aid)
    assert before.get("customer_name") == "舊客戶名稱", "前置不對：先看①。"

    _update_quotation_customer_name(quote_no, "新客戶名稱")

    after_list = _find(_list_awards(client, hdr), aid)
    assert after_list.get("customer_name") == "新客戶名稱", (
        "案件的客戶名已經改成「新客戶名稱」，清單上這張獎金單卻還是 %r——\n"
        % after_list.get("customer_name")
        + "☠️ 這代表客戶名被複製存進了 `bonus_awards`（快照），\n"
          "   不是即時 JOIN `quotations` 讀出來的。")

    after_detail = _award_detail(client, hdr, aid)
    assert after_detail.get("customer_name") == "新客戶名稱", (
        "明細也一樣：改完之後應該是「新客戶名稱」，實際 %r。"
        % after_detail.get("customer_name"))


# ══════════════════════════════════════════════════════════════════════
# ④ 空值／查無案件時，不可以印出字面上的 None
# ══════════════════════════════════════════════════════════════════════

def test_bn15_a_null_customer_name_does_not_render_as_the_string_none(
        client, make_user):
    """🔴 **`quotations.customer_name` 是 SQL NULL 時，回應不可以是字面
    字串 `"None"`／`"null"`／`"undefined"`。**

    `quotations.customer_name`（`db.py:411`）宣告是 `TEXT`，**沒有
    `NOT NULL DEFAULT ''`**——真的可能是 SQL NULL，不只是空字串。這是
    〈null 不等於 0〉的字串版：`f"{None}"` 會印出字面的 `"None"`。
    """
    quote_no = QUOTE_NO_PREFIX + "-NULLNAME"
    _seed_quotation(quote_no, None, None)
    aid = _seed_award(quote_no, ["someone"])

    _u, hdr = _hdr(client, make_user, "bn15_nullname")
    a = _find(_list_awards(client, hdr), aid)
    assert a.get("customer_name") in (None, ""), (
        "客戶名是 SQL NULL，清單上卻印出：%r" % a.get("customer_name"))
    assert a.get("customer_name") != "None"
    d = _award_detail(client, hdr, aid)
    assert d.get("customer_name") in (None, ""), (
        "客戶名是 SQL NULL，明細上卻印出：%r" % d.get("customer_name"))
    assert d.get("customer_name") != "None"


def test_bn15_an_award_with_no_matching_quotation_does_not_crash_or_leak_none(
        client, make_user):
    """🔴 **案件已經被刪掉（`quote_no` 在 `quotations` 裡查無此案）時，
    端點不可以 500，也不可以印出字面的 `"None"`。**

    ⚙️ 這是比「客戶名是空字串」更邊緣的狀況——整張案件都不存在（例如
    測試資料、或案件被清除過），JOIN 對不到任何一列。落地形狀若用
    `LEFT JOIN`，這種情況下取到的是 SQL NULL，同 `④` 的處置。
    """
    quote_no = QUOTE_NO_PREFIX + "-ORPHAN-NOQUOTE"
    aid = _seed_award(quote_no, ["someone"])  # 故意不種 quotations 那一列

    _u, hdr = _hdr(client, make_user, "bn15_orphan")
    r = client.get(AWARDS, headers=hdr)
    assert r.status_code == 200, "查無案件的獎金單讓清單端點壞掉：%s" % r.text[:300]
    a = _find(r.json().get("awards") or [], aid)
    assert a.get("customer_name") in (None, ""), (
        "查無案件時，`customer_name` 印出：%r" % a.get("customer_name"))
    assert str(a.get("customer_name")) != "None"

    rd = client.get("%s/%s" % (AWARDS, aid), headers=hdr)
    assert rd.status_code == 200, "查無案件的獎金單讓明細端點壞掉：%s" % rd.text[:300]
