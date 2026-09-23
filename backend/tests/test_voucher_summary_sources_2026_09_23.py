# -*- coding: utf-8 -*-
"""`JV7` · 摘要來源分頁選單（`GET /api/vouchers/summary-sources`，A `§160`／`§164`）。

使用者原話逐字：
```
(7) 摘要部分也要有分頁選單帶入案件跟哪些已上傳檔案並帶入摘要，
    也可以手動填寫或修改摘要
```

# 🔴 `§166`：這個 repo 裡 `assert status_code != 404` **擋不到端點不存在**

```
main.py:657  app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))
             => 吃掉所有沒被 router 接走的路徑
             => StaticFiles 只處理 GET/HEAD
             => POST/PUT/DELETE 打未實作端點 = **405**（不是 404）
```
⇒ 本檔每一題**先釘狀態碼形狀**（`OK_CODES`），再去看內容。
☠️ 否則「斷言回應內容」的題在端點存在之前**永遠是綠的**。

# 🔴 而 `§164` 的格式**不做成可設定**

依據是使用者那張 PDF 的三行摘要**沒有一行是同一個格式** ⇒ 摘要本來就是人打的，
帶入只是**省打字**，不是產生最終值。
☠️ 三行裡兩行都有的「事由」**沒有來源可以帶** ⇒ 一定要手打
⇒ **帶入後不可以把欄位鎖起來**。

---

# ⚠️ 我在寫這一支之前實查到的三個缺口（已回報 A，尚未裁定）

```
① 「客戶簡稱」這個欄位**不存在**
   db.py 全庫 106 張表：「簡稱」0 處、short_name 0 處、abbr 0 處
   拿得到的只有 quotations.customer_name（**全名**）與 customers.name
② 「已上傳檔案」**沒有任何資料表**（106 張表裡沒有 attachments／uploads／files）
   衍-3 說它與 `JV3` 是同一份清單，而 `JV3` 的表還沒建
   ⇒ 頁籤② 現在**沒有來源**
③ 摘要是**每一行各自一個**（voucher.html:113 `x-model="l.summary"`）
   ⇒ 「帶入到哪一行」規格沒寫
```
📌 ⇒ 本檔**只釘三者都成立時仍然為真的不變量**，不釘欄位名。
"""
import json
import re

import pytest

#: `§160` 定案的路徑。⚠️ 改了 **退回給我**。
ENDPOINT = "/api/vouchers/summary-sources"

#: `§159b` 的兩個頁籤。⚠️ 這是**可數完備**的集合：少一個、多一個都要紅。
TABS = ("案件", "已上傳檔案")

#: `§166`：走到端點才會出現的狀態碼。**405 不在裡面**（那是 StaticFiles 回的）。
OK_CODES = (200, 400, 403)

#: 「取不到的欄位就省略那一段，**不要填空字串佔位**」（`§164`）的破綻長相。
HOLES = ("None", "undefined", "null", "{}", "{", "}", "  ")


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _reached(r, what=ENDPOINT):
    """`§166` 的守門：先確定**走到了那支端點**，再去看內容。"""
    if r.status_code in (404, 405):
        pytest.fail(
            "`GET %s` 還不存在（回 %s）。\n" % (what, r.status_code)
            + "📌 路徑是 `§160` 定案的，改了 **退回給我**。\n"
            + "⚠️ 這裡刻意不是 `!= 404` —— 本 repo 的 catch-all StaticFiles\n"
              "   會讓未實作端點回 **405**（`§166`）。")
    assert r.status_code in OK_CODES, (
        "`%s` 回了 %s，不在 `OK_CODES` %s 裡：%s"
        % (what, r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _get(client, hdr, **params):
    return _reached(client.get(ENDPOINT, params=params or None, headers=hdr))


def _items(payload, tab):
    """把某一個頁籤的清單挖出來。⚠️ 外殼形狀還沒定，兩種都收。"""
    if isinstance(payload, dict):
        if tab in payload:
            return payload[tab]
        tabs = payload.get("tabs") or payload.get("sources")
        if isinstance(tabs, dict):
            return tabs.get(tab)
        if isinstance(tabs, list):
            for t in tabs:
                if isinstance(t, dict) and (t.get("tab") == tab
                                            or t.get("name") == tab
                                            or t.get("label") == tab):
                    return t.get("items") or t.get("rows") or t.get("list")
    return None


def _tab_names(payload):
    """回**這份 payload 自己宣告了哪些頁籤**（不是我期望的那些）。"""
    if not isinstance(payload, dict):
        return None
    tabs = payload.get("tabs") or payload.get("sources")
    if isinstance(tabs, dict):
        return sorted(tabs)
    if isinstance(tabs, list):
        out = []
        for t in tabs:
            if isinstance(t, dict):
                out.append(t.get("tab") or t.get("name") or t.get("label"))
        return sorted(x for x in out if x)
    # 最扁的一種：頁籤名直接當 key
    named = [k for k in payload if k in TABS]
    return sorted(named) if named else None


def _summary_of(item):
    """一筆來源**帶得進去的那個字串**。⚠️ 鍵名沒定，四種都收。"""
    if not isinstance(item, dict):
        return None
    for k in ("summary", "text", "label", "title"):
        if k in item:
            return item[k]
    return None


def _seed_quotation(quote_no, customer_name, project_name="測試案"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", customer_name, project_name, 1000, 952,
             "{}", "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 端點本身
# ══════════════════════════════════════════════════════════════════════

def test_jv7_the_summary_sources_endpoint_is_reachable(client, make_user):
    """🔴 **`GET /api/vouchers/summary-sources` 要走得到。**

    ⚠️ 這一題的價值不在「端點存在」，在**它是本檔其他題的前提** ——
       `§166`：端點不存在時 POST/PUT 回 405、GET 回 StaticFiles 的 404，
       而**斷言內容的題會一路綠下去**。
    """
    _u, hdr = _hdr(client, make_user, "jv7_reach")
    r = _get(client, hdr)
    assert r.status_code == 200, (
        "端點走到了而回 %s：%s\n" % (r.status_code, r.text[:200])
        + "⚠️ 帶著 `cashier` 模組的 superadmin 應該讀得到。")


def test_jv7_it_offers_exactly_the_two_declared_tabs(client, make_user):
    """🔴 **兩個頁籤，一個都不能少、也不可以多。**（`§159b`）

    ```
    頁籤 ① 案件
    頁籤 ② 已上傳檔案
    ```
    ⚙️ 這是**可數完備**的斷言：
    ```
    少一個 => 使用者少一條帶入的路，而頁面看起來正常
    多一個 => 有人加了一個來源而**沒有人決定它的格式**
    ```
    🔑 多出來的那一側才是這一題真正在守的 —— 少一個使用者會報修，
       多一個**不會有人報修**。
    """
    _u, hdr = _hdr(client, make_user, "jv7_tabs")
    payload = _get(client, hdr).json()

    got = _tab_names(payload)
    assert got is not None, (
        "讀不出這份回應宣告了哪些頁籤。收到的鍵：%s\n"
        % (sorted(payload) if isinstance(payload, dict) else type(payload))
        + "⚠️ 找過 `tabs`／`sources`／頁籤名直接當 key 三種。\n"
        + "📌 外殼形狀**由 B 決定** —— 用別的形狀請**退回給我**改 `_tab_names()`。")

    assert got == sorted(TABS), (
        "頁籤是 %s，而 `§159b` 定的是 %s\n" % (got, sorted(TABS))
        + "☠️ 多出來的那一個**沒有人決定過它的格式**（`§164` 只裁了兩種）。")


def test_jv7_the_tab_list_i_pinned_is_the_one_i_actually_check(client,
                                                               make_user):
    """⚙️ **自檢：上面那一題檢查的頁籤，就是 `TABS` 宣告的那些。**

    ☠️ 〈守門要驗有沒有人做過決定〉的反向控制：
       如果我在 `_items()` 裡只查得動「案件」，那「已上傳檔案」
       就算整個不見了也量不到，**而上面那一題照樣綠**。
    """
    assert len(set(TABS)) == 2, "`TABS` 有重複或數目不對：%r" % (TABS,)
    for t in TABS:
        probe = {"tabs": {t: []}}
        assert _tab_names(probe) == [t], (
            "`_tab_names()` 認不出頁籤 %r —— **量測裝置自己有盲點**。" % t)
        assert _items(probe, t) == [], (
            "`_items()` 取不到頁籤 %r 的清單 —— **量測裝置自己有盲點**。" % t)


def test_jv7_it_is_behind_the_voucher_modules(client, make_user):
    """🔴 **沒有傳票模組的人不可以讀到這份來源清單。**

    ☠️ 這支端點會列出**案件**（客戶名、報價單號）——
       那是業務資料，不是傳票資料。沒有出納／財務模組的人看到它，
       等於**從一個記帳畫面繞過去看客戶清單**。
    ⚠️ 判準是「有沒有被擋」，不是「回哪一個碼」：403 與 401 都算擋。

    ## 🔴 我第一版用 `superadmin` ＋ 空模組 —— **它永遠不會紅**（B 退回）

    ```
    helpers/auth.py:174   if user["role"] == "superadmin": return
    ```
    那一行是 **2026-09-14 使用者裁示**（「超級管理者預設全開」），不是疏漏。
    B 實測四種：
    ```
    superadmin  modules=[]          => **放行**
    admin       modules=[]          => 403
    user        modules=[]          => 403
    user        modules=['cashier'] => 放行
    ```
    🔑 值得記的是它的形狀：**「沒有模組」與「不需要模組」在測試裡長得一樣** ——
      我釘的是「有沒有被擋」，而那個帳號**根本不經過那道閘**。
    ⇒ 改用 `role="user"`：它一定會走到模組檢查。
    """
    _u, hdr = _hdr(client, make_user, "jv7_nomod", role="user", modules=())
    r = client.get(ENDPOINT, headers=hdr)
    if r.status_code in (404, 405):
        pytest.fail("端點還不存在（回 %s）—— 這一格量不到權限。" % r.status_code)
    assert r.status_code in (401, 403), (
        "沒有任何模組的帳號讀到了摘要來源（回 %s）：%s\n"
        % (r.status_code, r.text[:200])
        + "☠️ 那份清單裡有**客戶名與報價單號**。")

    # ⚙️ 正對照：同一個角色**帶著模組**要進得去。
    #    ☠️ 少了它，一個「一律 403」的實作會讓上面那句綠 ——
    #       而那會讓有權限的人也讀不到。
    _u2, hdr2 = _hdr(client, make_user, "jv7_hasmod", role="user",
                     modules=("cashier",))
    r2 = client.get(ENDPOINT, headers=hdr2)
    assert r2.status_code == 200, (
        "帶著 `cashier` 模組的一般員工被擋掉了（回 %s）：%s\n"
        % (r2.status_code, r2.text[:200])
        + "☠️ 那道閘擋過頭了 —— 它應該擋的是**沒有模組的人**。")


# ══════════════════════════════════════════════════════════════════════
# ② 帶入的字串：`§164` 寫死一組格式
# ══════════════════════════════════════════════════════════════════════

def test_jv7_a_case_source_carries_a_string_ready_to_paste(client, make_user):
    """🔴 **案件那一筆要直接帶得出一個字串**，不是丟一包欄位給前端自己拼。

    ```
    §164  案件來源 => 「{客戶簡稱}{報價單號}」
                     例：京城凱悅報價單MQ-202608-009
    ```
    🔑 釘「**字串在後端組好**」而不是「格式長什麼樣」的理由：
    ```
    格式寫在 JS   => JV5 的 PDF 匯出讀不到它 => 兩邊會長不一樣
    格式寫在後端  => 兩邊同一個來源
    ```
    ⚠️ 而我**不釘字面格式** —— 只釘「客戶與報價單號兩段都在裡面」。
       `§164` 的範例字面有「報價單」三個字而模板 `{客戶簡稱}{報價單號}`
       裡沒有，**那一段還沒定案**（已問 A）。
    """
    _u, hdr = _hdr(client, make_user, "jv7_case")
    _seed_quotation("MQ-202608-009", "京城凱悅")

    items = _items(_get(client, hdr).json(), "案件")
    assert items, (
        "「案件」頁籤是空的，而我剛種了一筆 `MQ-202608-009`。\n"
        + "⚠️ 若是被狀態過濾掉的（我種的是「已結案」），**退回給我**說要哪些狀態。")

    one = next((i for i in items
                if "MQ-202608-009" in json.dumps(i, ensure_ascii=False)), None)
    assert one is not None, (
        "清單裡找不到 `MQ-202608-009`。實際收到 %d 筆，第一筆：%r"
        % (len(items), items[0]))

    s = _summary_of(one)
    assert isinstance(s, str) and s.strip(), (
        "那一筆**沒有帶得出去的字串**（找過 summary／text／label／title）：%r\n" % one
        + "☠️ 前端只好自己拼 ⇒ 格式會與 `JV5` 的 PDF 長不一樣。")
    assert "京城凱悅" in s, "帶入字串裡沒有客戶：%r" % s
    assert "MQ-202608-009" in s, "帶入字串裡沒有報價單號：%r" % s


def test_jv7_a_missing_piece_is_omitted_not_padded(client, make_user):
    """🔴 **取不到的那一段要省略，不是留一個洞。**（`§164` 逐字）

    ```
    §164  取不到廠商或發票號的欄位就省略那一段，**不要填空字串佔位**
    ```
    ☠️ 填空字串的樣子很具體：
    ```
    「3/30  XV15543058」      <= 兩個空白（廠商是空的）
    「3/30 None XV15543058」  <= Python 的 %s
    「3/30 undefined ...」    <= JS 的樣板字串
    ```
    🔑 而它**不會報錯** —— 使用者只會覺得「怎麼多一個空格」，然後手動刪掉，
       **每一張單都刪一次**。
    """
    _u, hdr = _hdr(client, make_user, "jv7_hole")
    _seed_quotation("MQ-202609-777", "")          # 客戶是空的

    items = _items(_get(client, hdr).json(), "案件") or []
    one = next((i for i in items
                if "MQ-202609-777" in json.dumps(i, ensure_ascii=False)), None)
    assert one is not None, (
        "客戶欄是空的那一筆整個不見了（收到 %d 筆）——\n" % len(items)
        + "⚠️ 若是刻意過濾掉沒有客戶的案件，**退回給我**，那也是一種答案。")

    s = _summary_of(one) or ""
    for bad in HOLES:
        assert bad not in s, (
            "帶入字串裡有佔位的洞 %r：%r\n" % (bad, s)
            + "📌 `§164`：取不到的欄位**就省略那一段**。")
    assert s == s.strip(), "帶入字串前後有空白：%r" % s
    assert "MQ-202609-777" in s, (
        "客戶取不到，而**報價單號那一段也一起不見了**：%r\n" % s
        + "☠️ 省略的是缺的那一段，不是整個字串。")


# ══════════════════════════════════════════════════════════════════════
# ③ 頁面：`§159b` 的「完整」＝後端＋前端＋頁面
# ══════════════════════════════════════════════════════════════════════

def _voucher_page():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    return (root / "frontend" / "pages" / "voucher.html",
            root / "frontend" / "js" / "voucher.js")


def test_jv7_the_page_has_a_two_tab_source_picker(client, make_user):
    """🔴 **頁面上要看得到那兩個頁籤。**（`AC1`／`§159b` (8)）

    ```
    使用者逐字  「確認前後端跟頁面都有完成才算完整」
    ```
    ☠️ 我今天已經有人踩過「後端＋唯讀骨架＝回報完成」兩次。
    ⚠️ 這一題只證明**字在頁面上** —— 證明不了它點得動，
       那一層在 `test_e2e_voucher_summary_2026_09_23.py`。
    """
    html_p, js_p = _voucher_page()
    html = html_p.read_text(encoding="utf-8")
    js = js_p.read_text(encoding="utf-8")
    both = html + "\n" + js

    for tab in TABS:
        assert tab in both, (
            "傳票頁面（`voucher.html` ＋ `voucher.js`）裡找不到頁籤「%s」。\n" % tab
            + "📌 `§159b` (7)：「摘要部分也要有**分頁選單**帶入案件跟哪些已上傳檔案」。")
    assert ENDPOINT in both, (
        "頁面沒有任何地方打 `%s` ——\n" % ENDPOINT
        + "☠️ 頁籤的字印出來了而**沒有人去拿資料** ⇒ 那是骨架不是功能。")


def test_jv7_the_summary_field_is_not_locked_after_a_source_is_applied():
    """🔴 **帶入之後摘要欄仍然要打得動。**（`§164` 逐字）

    ```
    §164  「事由」三行有兩行都有，而它**沒有來源可以帶** => 一定要手打
          => 帶入後游標要停在可續打的位置，**不是把欄位鎖起來**
    ```
    ⚙️ 觀測點挑的是 `voucher.html:113` 那個 `x-model="l.summary"` 的 input：
       它現在的停用條件是 `!canEdit`（草稿以外不可改，那是對的）。
    ☠️ 這一題要擋的是**多一個條件**：
    ```
    :disabled="!canEdit || l.summaryFromSource"   <= 帶入過就鎖住
    readonly                                      <= 直接唯讀
    ```
    🔑 而鎖起來的頁面**看起來完全正常**，使用者只會覺得「這格打不了字」。
    """
    html_p, _js = _voucher_page()
    html = html_p.read_text(encoding="utf-8")

    # 🔴 `JV12`（`9ec2c2d`）把這個欄位從 `<input>` 換成 `<textarea>`
    #    （高度隨文字調整），這裡原本釘死 `<input …>` 從那個 commit 之後
    #    就一直是紅的——〈守門守的對象被搬走〉：斷言沒變、字面值沒變，
    #    指的元素換了型別。改成同時接受兩種標籤。
    m = re.search(r"<(?:input|textarea)[^>]*x-model=\"l\.summary\"[^>]*>",
                 html, re.S)
    assert m, (
        "`voucher.html` 裡找不到 `x-model=\"l.summary\"` 的欄位 ——\n"
        + "⚠️ 摘要欄被搬走了，**退回給我**改這一題的觀測點。")
    tag = m.group(0)

    assert "readonly" not in tag.lower(), (
        "摘要欄是唯讀的：%s\n" % tag
        + "☠️ `§164`：「事由」沒有來源可以帶 ⇒ **一定要手打**。")

    dis = re.search(r":disabled=\"([^\"]*)\"", tag)
    if dis:
        expr = dis.group(1)
        assert expr.strip() == "!canEdit", (
            "摘要欄的停用條件是 %r，而 `§164` 只允許「不可編輯的狀態」這一個理由。\n"
            % expr
            + "☠️ 多出來的條件多半是「帶入過就鎖住」——**那正是要擋的**。\n"
            + "⚠️ 若是為了別的理由加的，**退回給我**。")
