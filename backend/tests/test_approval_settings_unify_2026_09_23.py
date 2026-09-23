# -*- coding: utf-8 -*-
"""`AS1`／`AS2`／`JV8` · 簽核設定合併、傳票納入、新增才出現編輯畫面。

規格：`docs/windows/SPEC-AS1-AS2-JV8.md`（A-2）。

# 🔴 `§5⑥` 是 `AS2` 的全部，而它**很容易寫成同義反覆**

```
⑥ 傳票送審讀的是 resolve_active_flow_setting("voucher")，**不是寫死的兩層**
⚙️ 觀測方式：**把設定改成三層**，再送審 => 簽核鏈必須是三層
☠️ 只驗「兩層時能過」的話，**寫死與讀設定的結果一模一樣** => 那一題永遠綠
```

# ⚠️ 而三層以上在這個 repo **從來沒有被跑過**

A-2 實讀四把 key（`99ea423`）：
```
approval_flow／contractor_voucher_／invoice_voucher_   都是 **2 層**
unified_approval_flow                                 **0 層**
```
⇒ `tiered_approval` 的推進邏輯對三層以上**沒有人驗過**。
🔑 ⇒ 我那題若紅，**紅的可能是既有的推進邏輯，不是 `AS2` 的新碼**
  ⇒ 回報前先分辨（下面那一題的訊息裡寫了怎麼分）。

# ☠️ `AS1` 的核心：一個會改掉業務規則而**不報錯**的動作

```
contractor_voucher_approval_flow   corbin -> queena（兩層具名）← 匯款申請現在走這個
unified_approval_flow              **0 層** ＋ includeSubmitterManagerTier
⇒ 切進 unified 的那一刻，「**誰核准匯款**」被改掉，**沒有任何錯誤訊息**
```

# ⚠️ `§5⑩` 是一條**「不要寫的題」**

```
⑩ **不可以**斷言「內容佔頁高 31.8%」—— 那是**三格版的實測值**，不是版面規則
```
📌 A-2 明著把它列進驗收，因為 `SPEC-JV5-PDF §2` 裡有那個數字，
   **而它讀起來像一個可以拿來斷言的常數**。
⇒ 本檔**沒有**任何一題碰那個百分比，而這段話是那件事的載體。

# ⚠️ 五項待裁我**沒有**寫題

（`voucher` 進不進 `DEFAULT_UNIFIED`／`contractor_voucher` 預不預設切／
`AS2` 欄位改不改成明細表／`JV8` 先建草稿還是填完才建／超過一頁的分頁規則）
☠️ 替未裁的決定寫題，會把它變成既成事實。
"""
import pytest

SETTINGS = "/api/settings/%s"

#: `system.py:189/:200` —— 獨立設定專用的那兩支。
FLOW = "/api/settings/approval-flow/%s"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)

#: `AS2`：傳票要成為**第八個** doc type。
VOUCHER_DOC_TYPE = "voucher"

#: ☠️ 三個都叫 voucher，而它們是**三種不同的單據** ⇒ 標籤要分得出來。
THREE_VOUCHERS = ("invoice_voucher", "contractor_voucher", VOUCHER_DOC_TYPE)

#: `§1`：孤兒 key —— 設定頁**不可以顯示**它。
ORPHAN_KEY = "approval_flow"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_id(username):
    """`approvers` 要 `userId` —— 從測試 DB 撈回來。"""
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        assert row is not None, "找不到使用者 %r" % username
        return int(row["id"])
    finally:
        conn.close()


def _ta():
    import helpers.tiered_approval as ta
    return ta


# ══════════════════════════════════════════════════════════════════════
# AS2 ①：傳票要成為第八個 doc type
# ══════════════════════════════════════════════════════════════════════

def test_as2_voucher_is_a_declared_doc_type():
    """🔴 **`§5⑤`：`voucher` 要進 `APPROVAL_DOC_TYPES`。**

    ⚠️ 這一題**不碰** `DEFAULT_UNIFIED_DOC_TYPES` —— 那是**待裁 ①**。
    🔑 「這個類型存在」與「它預設跟大家同一條流程」是兩件事，
      而只有前者是規格裡已經決定的。
    """
    ta = _ta()
    assert VOUCHER_DOC_TYPE in ta.APPROVAL_DOC_TYPES, (
        "`APPROVAL_DOC_TYPES` 裡沒有 `%s`：%r\n"
        % (VOUCHER_DOC_TYPE, ta.APPROVAL_DOC_TYPES)
        + "📌 `AS2`：傳票要成為**第八個** doc type。")


def test_as2_the_three_vouchers_are_told_apart_by_their_labels():
    """🔴 **`§5⑦`：三個 `*voucher*` 的標籤要分得出來。**

    ```
    invoice_voucher     發票開立簽核單
    contractor_voucher  承攬商匯款申請
    voucher             **會計傳票**
    ```
    ☠️ 三個都叫 voucher，而它們是三種不同的單據 ——
       標籤若只寫「傳票」，設定頁上會出現三個看起來很像的項目，
       **而改錯一個不會報錯**：它只是讓另一種單據換了簽核鏈。
    ⚙️ 判準是**兩兩不同**，不是「等於某個字串」——
       文案是 A 的事，我釘的是「分得出來」。
    """
    ta = _ta()
    labels = {}
    for dt in THREE_VOUCHERS:
        lab = ta.APPROVAL_DOC_TYPE_LABELS.get(dt)
        assert lab, (
            "`%s` 沒有標籤：%r" % (dt, sorted(ta.APPROVAL_DOC_TYPE_LABELS)))
        labels[dt] = lab
    assert len(set(labels.values())) == 3, (
        "三個 voucher 類型的標籤有重複：%r\n" % labels
        + "☠️ 設定頁上會出現看起來很像的項目，**而改錯一個不會報錯** ——\n"
          "   它只是讓另一種單據換了簽核鏈。")
    assert labels[VOUCHER_DOC_TYPE] != "傳票", (
        "`%s` 的標籤是「傳票」—— 太模糊。\n" % VOUCHER_DOC_TYPE
        + "📌 A-2 建議「傳票（會計）」：三個裡只有它是**會計傳票**。")


# ══════════════════════════════════════════════════════════════════════
# AS2 ②：核心 —— 讀設定，不是寫死的兩層
# ══════════════════════════════════════════════════════════════════════

def test_as2_submitting_a_voucher_follows_the_configured_tiers(client,
                                                               make_user):
    """🔴🔴🔴 **`§5⑥`：把設定改成三層，簽核鏈就要是三層。**

    ```
    只驗「兩層時能過」  =>  **寫死與讀設定的結果一模一樣**  =>  永遠綠
    改成三層再送審      =>  只有真的讀設定才會變
    ```
    ☠️ `§5` 逐字：**其他全綠而它紅 ＝ 只是把一個新標籤畫在設定頁上。**

    ## ⚠️ 紅了要先分辨是誰紅的

    A-2 實讀四把 key（`99ea423`）：**現存的全部都是 2 層或 0 層**
    ⇒ `tiered_approval` 的推進邏輯對**三層以上沒有人驗過**。
    ```
    紅在「簽核鏈只有兩層」        => AS2 沒接上設定（**本題要抓的**）
    紅在推進到第三層時炸掉／卡住   => **既有的推進邏輯**，不是 AS2 的新碼
    ```
    🔑 ⇒ 回報前先看紅的是哪一種 —— 兩者的下一步不同。
    """
    ta = _ta()
    if VOUCHER_DOC_TYPE not in ta.APPROVAL_DOC_TYPES:
        pytest.fail(
            "`voucher` 還不是一個 doc type —— 先看上面那一題。\n"
            + "⚠️ 這一題刻意 **fail 不 skip**：skip 會讓它永久略過"
              "（`GC6` 那個形狀）。")

    _u, hdr = _hdr(client, make_user, "as2_flow")

    # 🔴 **三個坑，三個我都踩過或被 B 退回**（他實跑，我複查 `system.py:28-42`）
    #
    # ① 端點不是 `PUT /api/settings/{key}` —— 是
    #    **`PUT /api/settings/approval-flow/{doc_type}`**（`system.py:200`）
    #    ⇒ 我第一版打的那支不存在 => **405**（`§166` 的第二種臉）
    # ② `approvers` 的項目**不是字串是物件**，而手動挑人要
    #    **`userId`／`username`／`displayName` 三個都給**
    #    （`ApprovalFlowApprover._check_shape`）
    # ③ `includeSubmitterManagerTier` **缺鍵時視為 True**
    #    ⇒ 它會在最前面插一層「送審人的部門主管」⇒ 測試帳號沒有部門
    #    ⇒ 送審 400「申請人尚未歸屬任何部門」，**而實際是四層不是三層**
    #    🔑 ⇒ 要釘「三層」就**必須明著給 False** —— 否則我量的不是我以為的東西。
    approvers = []
    for name in ("as2_t1", "as2_t2", "as2_t3"):
        u, _h = _hdr(client, make_user, name)
        approvers.append({"userId": _user_id(u), "username": u,
                          "displayName": u})

    three = {"includeSubmitterManagerTier": False,
             "tiers": [{"approvers": [approvers[0]]},
                       {"approvers": [approvers[1]]},
                       {"approvers": [approvers[2]]}]}
    r = client.put(FLOW % VOUCHER_DOC_TYPE, headers=hdr, json=three)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "存不了傳票的簽核流程（回 %s）：%s\n" % (r.status_code, r.text[:200])
            + "📌 端點是 `PUT /api/settings/approval-flow/{doc_type}`"
              "（`system.py:200`）。\n"
            + "⚠️ 422 的話多半是 `approvers` 的形狀 —— 手動挑人要\n"
              "   `userId`／`username`／`displayName` **三個都給**。")
    assert r.status_code == 200, "存設定失敗：%s %s" % (r.status_code, r.text[:200])

    got = ta.resolve_active_flow_setting(VOUCHER_DOC_TYPE)
    assert len(ta.active_tiers(got)) == 3, (
        "存了三層，而 `resolve_active_flow_setting(\"%s\")` 讀回 %d 層：%r\n"
        % (VOUCHER_DOC_TYPE, len(ta.active_tiers(got)), got)
        + "⚠️ **這一格是設定本身**，還沒到送審 —— 先修它。")

    vr = client.post("/api/vouchers", headers=hdr, json={
        "summary": "三層測試",
        "lines": [{"account_code": "1113", "debit": 1000, "credit": 0},
                  {"account_code": "4111", "debit": 0, "credit": 1000}]})
    assert vr.status_code == 200, "建不起來：%s %s" % (vr.status_code, vr.text[:200])
    vid = vr.json()["id"]

    sr = client.post("/api/vouchers/%s/submit" % vid, json={}, headers=hdr)
    assert sr.status_code in OK_CODES, (
        "送審回 %s：%s" % (sr.status_code, sr.text[:200]))
    assert sr.status_code == 200, "送審失敗：%s" % sr.text[:200]

    v = client.get("/api/vouchers/%s" % vid, headers=hdr).json()
    tiers = (v.get("approval") or {}).get("tiers") or v.get("tiers")
    assert tiers is not None, (
        "讀回來的傳票沒有簽核鏈（找過 `approval.tiers`／`tiers`）。\n"
        + "現有鍵：%s\n" % sorted(v)
        + "☠️ 那表示送審**仍然走寫死的兩層** —— `AS2` 只是把一個新標籤\n"
          "   畫在設定頁上。\n"
        + "⚠️ 鍵名不同的話**退回給我**。")
    assert len(tiers) == 3, (
        "設定是三層，而這張單的簽核鏈有 %d 層：%r\n" % (len(tiers), tiers)
        + "☠️ **寫死的兩層**。而只驗「兩層時能過」的話，\n"
          "   寫死與讀設定的結果一模一樣 ⇒ 那一題永遠綠。")


def test_as2_a_company_that_never_configured_a_flow_is_unaffected(client,
                                                                  make_user):
    """⚙️🔴 **反向控制：**沒有設定過**簽核流程時，現況不可以改變。**

    ## ☠️ 這一題抓到 B 一個真的 bug，而它一次弄紅四支既有測試

    ```
    B 第一版  無條件呼叫 setting_to_active_tiers()
    而 includeSubmitterManagerTier **缺鍵時視為 True**
    ⇒ 它在最前面插一層「送審人的部門主管」
    ⇒ **一個沒有設定過簽核流程的公司連送審都送不出去**
      （400「申請人尚未歸屬任何部門」）
    ```
    🔑 成因是〈null 不等於 0〉：`resolve_active_flow_setting()` 對**缺鍵**
      回 `{"tiers": []}`，**與一份存成空的設定一模一樣**
      ⇒ 要判的是**鍵在不在**（`_get_setting(key, None)`），不是值是不是空的。

    ## 📌 而這一題釘的不是「兩層」，是**不可以替使用者做決定**

    ```
    自動核准    我們替他決定「這張不必簽」
    送不出去    我們替他決定「這張一定要簽」
    ⇒ **兩種都是替他決定了**
    ```
    ⇒ 沒設定 ⇒ 維持既有行為（送審 -> 待審核，簽兩次 -> 已核准）。
    ⚠️ 本題**刻意不存任何設定** —— 它跑在一個乾淨的 DB 上。
    """
    _u, hdr = _hdr(client, make_user, "as2_nocfg")

    vr = client.post("/api/vouchers", headers=hdr, json={
        "summary": "沒設定流程",
        "lines": [{"account_code": "1113", "debit": 1000, "credit": 0},
                  {"account_code": "4111", "debit": 0, "credit": 1000}]})
    assert vr.status_code == 200, "建不起來：%s %s" % (vr.status_code, vr.text[:200])
    vid = vr.json()["id"]

    sr = client.post("/api/vouchers/%s/submit" % vid, json={}, headers=hdr)
    assert sr.status_code == 200, (
        "**沒有設定過**簽核流程，而送審被擋掉了（%s）：%s\n"
        % (sr.status_code, sr.text[:200])
        + "☠️ 那是「缺鍵被當成一份空設定」的樣子 ——\n"
          "   `includeSubmitterManagerTier` 缺鍵視為 `True` ⇒ 插一層部門主管\n"
          "   ⇒ **一個沒有設定過簽核流程的公司連送審都送不出去**。\n"
        + "🔑 要判的是**鍵在不在**，不是值是不是空的。")

    for _ in range(2):
        ar = client.post("/api/vouchers/%s/approve" % vid, json={},
                         headers=hdr)
        assert ar.status_code == 200, (
            "簽核失敗：%s %s" % (ar.status_code, ar.text[:200]))
    status = client.get("/api/vouchers/%s" % vid, headers=hdr).json().get(
        "status")
    assert status == "已核准", (
        "沒有設定過流程而簽兩次之後是 %r，既有行為是「已核准」——\n" % status
        + "☠️ 我們替使用者做了決定：**不管是自動核准還是送不出去，"
          "兩種都是替他決定了**。")


# ══════════════════════════════════════════════════════════════════════
# AS1：切換 scope 之前要先說會變成什麼
# ══════════════════════════════════════════════════════════════════════

def test_as1_the_settings_page_shows_both_sides_before_switching():
    """🔴 **`§5②`：切換 scope **之前**，畫面要顯示兩邊現有的層與人。**

    ```
    contractor_voucher_approval_flow   corbin -> queena（兩層具名）← 現況
    unified_approval_flow              **0 層** ＋ includeSubmitterManagerTier
    ⇒ 切過去的那一刻，「**誰核准匯款**」被改掉，**沒有任何錯誤訊息**
    ```
    ⚙️ A-2 的觀測點：**不要只驗「有一個確認對話框」** ——
       對話框寫「確定要切換嗎？」也是一個對話框，而它什麼都沒說。
    ⇒ 畫面上要同時說得出**現在是誰**與**切過去會變成什麼**。
    ⚠️ 我釘的是「那兩件事都被讀出來並顯示」，不釘文案。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    page = root / "frontend" / "pages" / "approval-settings.html"
    js_dir = root / "frontend" / "js"
    assert page.is_file(), "`approval-settings.html` 不見了 —— **退回給我**。"

    blob = page.read_text(encoding="utf-8", errors="replace")
    for extra in ("approval-settings.js",):
        p = js_dir / extra
        if p.is_file():
            blob += "\n" + p.read_text(encoding="utf-8", errors="replace")
    blob = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), blob,
                  flags=re.S)

    assert "contractor_voucher" in blob, (
        "簽核設定頁看不到 `contractor_voucher` ——\n"
        + "📌 `§5①`：匯款申請那一類要出現在這一頁上。")
    both = ("unified_approval_flow" in blob
            and "contractor_voucher_approval_flow" in blob)
    assert both, (
        "頁面沒有同時讀到**兩邊**的設定 ——\n"
        + "☠️ 切過去的那一刻「誰核准匯款」被改掉，**沒有任何錯誤訊息**。\n"
        + "⚙️ 要顯示的是**現在是誰**與**切過去會變成什麼**，\n"
          "   而不是一個寫著「確定要切換嗎？」的對話框。")


def test_as1_the_orphan_key_is_not_offered_while_the_real_one_is():
    """🔴 **`§5③`：設定頁**不顯示** `approval_flow` 這把孤兒 key。**

    ```
    approval_flow  全 repo 只有 db.py:2806 一段講歷史的 docstring 提到它
                   **沒有活的讀取端** ⇒ 改它不會有任何效果
    ```
    ☠️ 顯示它的後果：使用者去改那一把，**而什麼都不會發生** ——
       他會以為系統壞了，或以為自己改對了。

    ## ⚙️ 而「不可以出現」型的斷言要配一個「必須出現」的

    ☠️ 少了後半：畫面整個壞掉（什麼都沒有）時，前半**照樣綠**。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    page = root / "frontend" / "pages" / "approval-settings.html"
    blob = page.read_text(encoding="utf-8", errors="replace")
    blob = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), blob,
                  flags=re.S)

    # ⚙️ 必須出現的那一半（先驗它，否則下面那句在空畫面上也會綠）
    assert "contractor_voucher" in blob, (
        "頁面上連 `contractor_voucher` 都沒有 —— **量測裝置量到一個空畫面**，\n"
        + "下面那句「孤兒 key 不可以出現」在這種情況下**無條件成立**。")

    # 🔴 不可以出現的那一半：整個字 `approval_flow`，而不是
    #    `contractor_voucher_approval_flow` 這種**以它結尾**的。
    orphan = re.findall(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % ORPHAN_KEY,
                        blob)
    assert not orphan, (
        "設定頁出現了孤兒 key `%s`（%d 次）——\n" % (ORPHAN_KEY, len(orphan))
        + "☠️ 它**沒有活的讀取端** ⇒ 使用者去改它，**什麼都不會發生**。\n"
        + "⚠️ 我用的是整字比對 ⇒ `contractor_voucher_approval_flow`"
          "**不會**被誤判。")


# ══════════════════════════════════════════════════════════════════════
# JV8：新增之後才出現編輯畫面
# ══════════════════════════════════════════════════════════════════════

def test_jv8_the_page_does_not_open_straight_into_a_blank_form():
    """🔴 **`§5⑪`：直接開 `voucher.html` 看不到空白編輯畫面。**

    ☠️ 現況是一進來就有三行空白分錄 ⇒ 使用者以為自己已經在建一張單，
       打了一半離開，**而什麼都沒有被建出來**。
    ⚙️ 判準：編輯區要被一個**條件**包起來（`x-if`／`x-show` 綁到「有沒有選單」），
       而不是無條件渲染。
    ⚠️ 我釘的是「那個條件存在」，不釘它叫什麼 —— 機制由 B 決定。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "pages" / "voucher.html").read_text(
        encoding="utf-8", errors="replace")
    html = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)

    m = re.search(r'<input[^>]*x-model="l\.account_code"', html)
    assert m, (
        "找不到分錄的科目輸入框 —— **退回給我**改觀測點。")

    before = html[:m.start()]
    guarded = re.search(r'x-(?:if|show)="[^"]*\b(id|editing|current|selected)\b',
                        before)
    assert guarded, (
        "分錄編輯區**沒有被任何條件包起來** ——\n"
        + "☠️ 一進來就是空白表單：使用者以為自己在建一張單，打了一半離開，\n"
          "   **而什麼都沒有被建出來**。\n"
        + "📌 `§5⑪`：直接開頁面不可以看到空白編輯畫面。\n"
        + "⚠️ 我找的是 `x-if`／`x-show` 綁到 `id`／`editing`／`current`／"
          "`selected` 其中一個 —— 用別的名字**退回給我**。")
