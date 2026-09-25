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

# 🔴 補證：這 5 題寫完的當下就是綠的（B 在同一份工作樹上幾乎同時做完），
# 〈新回歸測試一定要先證明它會紅〉這一步沒有機會發生——用**替身**補一次

不 stash／不碰 B 的未提交異動：monkeypatch `modules.payroll.api.bonus._case_names_for`
讓它一律回空 dict，重跑這 5 題，結果：

```
①②  RED —— 斷言真的打在 customer_name／project_name 的值上，
            有牙齒（今天就驗得到「這個修法把值蓋掉」這件事）
③   RED，而是在**前置斷言**（「先看①」）紅掉，不是在它自己要驗的
    「改 quotations 之後獎金單要跟著變」那一段——這個替身讓 case_names
    永遠是空的，連①的前置都過不了，**沒有真的走到快照那一段邏輯**。
    ⇒ ③ 對「快照式的錯誤修法」是**防未來**，不是防現況：那種修法今天
    不存在，沒有東西可以讓它在今天亮紅燈。
④⑤  第一版仍然是綠的——這兩題驗的是「值缺席時不可以印成字面
    'None'」，而 `case_names_for` 回空 dict 時現有程式碼本來就會落到
    `cn.get(..., "")` 的空字串分支，跟正常時的空值處理路徑相同，這個
    替身**改不出**它們要防的那種錯。
    ⇒ **第二輪改用資料不用空殼替身**：直接讓 `_case_names_for` 內部
    重現真實錯誤（拿掉 `or ''`、對 SQL 回來的 `None` 直接 `str()`），
    而不是整支換成回空 dict——
    ```
    ④  ✅ 牙齒已證實——這題會紅（'None' 出現在回應裡）
    ⑤  ⚠️ 仍未證實，而且原因不是「還沒換替身」：⑤ 的情境是查無
        `quotations` 那一列，`_case_names_for` 的回傳字典裡**根本沒有
        這個 key**，④ 的那個替身動的是「有 key 而值是 None」，完全碰
        不到「key 不存在」這條路。⑤ 真正的防線是呼叫端
        `case_names.get(quote_no) or {}` 的 `or {}`，要驗證得改那一行
        的替身，本檔暫不做第三輪，先記下「④⑤ 共用同一句『不印字面
        None』的描述，而它們其實是兩條不同的防線，各自要各自的證明」。
    ```
```
⇒ 下面把每一題標成**今天驗得到**還是**防未來的修法**，不要看成同一種綠。
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
    """🔴🔴 **核心：`GET /awards` 每一筆要帶得出客戶名與案件名。**

    ✅ **今天驗得到**——替身驗證過（`_case_names_for` 回空 dict 時這一題
    真的紅），不是一句立即通過的空話。
    """
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

    ✅ **今天驗得到**（替身驗證過，`_case_names_for` 回空 dict 時這一題會紅）。
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

    ⚠️ **防未來，不是防現況**——替身測過：讓 `_case_names_for` 回空
    dict，這一題確實會紅，**但紅在它自己的前置斷言**（第一次讀就該有
    的客戶名沒出現），沒有真的走到「改完 `quotations` 之後有沒有跟著
    變」那一段。快照式的錯誤修法今天不存在，這一題現在守的是**日後
    有人這樣改**時會被抓到，不是現況裡已經驗證過這個機制。
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

    ✅ **牙齒已驗證（方式：突變驗證／live，非常設）**——第一版替身讓
    `_case_names_for` 回空 dict 驗不出
    來（那個替身包在已經修好的輸出外層，等於沒動到任何東西）。換成
    直接重現真實的錯誤（`_case_names_for` 內部拿掉 `or ''` 防護、對
    `SELECT` 回來的 `None` 直接 `str()`）：這一題**真的會紅**
    （`assert 'None' in (None, '')` 失敗）。用資料不用空殼替身：
    種一筆 `customer_name IS NULL` 的案件，那條路本來就是這一題要防
    的那一條，不必額外構造。
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

    ⚠️ **牙齒仍未證實，而且與 `④` 不是同一條防線**——`④` 修好之後的
    替身（讓 `_case_names_for` 對 NULL 直接 `str()`）對這一題**依然是
    綠的**：查無案件時 SQL 根本查不到那一列，`_case_names_for` 的
    回傳字典裡**沒有這個 key**，重現 `④` 那個 bug 的替身動的是「有
    這個 key 而值是 None」那條路，完全碰不到「key 不存在」這條路——
    這題真正的防線是呼叫端 `case_names.get(quote_no) or {}` 那個
    `or {}`，要證明牙齒得改動那一行的替身（拿掉 `or {}`，預期會變成
    `AttributeError` 而不是印出字面 `"None"`——那其實是另一種失效，
    這題目前對「不崩潰」那一半有牙齒，對「不印字面 None」那一半在這個
    情境下**驗不到，因為兩者共用同一個防線，防線本身沒有被證明過**）。
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
