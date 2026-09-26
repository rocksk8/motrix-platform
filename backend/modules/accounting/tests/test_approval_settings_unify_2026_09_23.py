"""AS2／JV8 的傳票部分（M06 搬遷自 tests/ 同名檔；簽核設定頁本身的題留在原檔）。

2026-09-26 自 `backend/tests/test_approval_settings_unify_2026_09_23.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
import pytest
from tests.test_approval_settings_unify_2026_09_23 import (  # noqa: F401
    FLOW, OK_CODES, VOUCHER_DOC_TYPE, _ta,
)
from core import source_tree


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


def _slots(v):
    """簽核格。⚠️ 四種鍵名都收 —— 那個投影層日後可能再改。"""
    got = (v.get("signatures") or v.get("signoffs")
           or v.get("approvals") or v.get("sign_slots"))
    if isinstance(got, dict):
        return list(got)
    if isinstance(got, list):
        return [x.get("slot") or x.get("name") for x in got
                if isinstance(x, dict)]
    return None


def test_as2_three_tiers_can_actually_be_signed_all_the_way(client,
                                                            make_user):
    """🔴🔴 **三層要**走得完**，而版面的格數要跟著層數長。**

    ## 🔑 為什麼這一題比「鏈是三層」值錢

    > **「鏈是三層」只證明我把設定抄進去了，不證明有人走得完它。**

    而 A-2 實讀四把 key：**現存的全部都是 2 層或 0 層**
    ⇒ `tiered_approval` 的推進邏輯對三層以上**從來沒有被跑過**。

    ## ⚙️ 釘的是**不變量**，不是那一次的值

    ```
    ❌ 狀態序列 ['簽核中','簽核中','已核准']  <= 層數一改就跟著變
    ❌ 字面值 '第 3 層'                      <= 那是 B 挑的標籤
    ✅ **簽核格數 == 1 ＋ 層數**（製票不算層）<= 版面**從資料算列數**
    ```
    📌 前兩層沿用「覆核／主管」是刻意的 —— **讓沒設定過的公司版面一個字都不變**。

    ## ⚙️ 而第四次 `approve` 是一個便宜的反向控制

    ☠️ 少了它，一個「`currentTier` 無上限往前加」的實作也會讓三次那一題綠，
       而**第四次會把 `tiers[3]` 撞成 `IndexError`** ⇒ 500。
    """
    ta = _ta()
    if VOUCHER_DOC_TYPE not in ta.APPROVAL_DOC_TYPES:
        pytest.fail("`voucher` 還不是 doc type —— 先看上面那一題。")

    _u, hdr = _hdr(client, make_user, "as2_walk")
    approvers, signer_hdrs = [], []
    for name in ("as2_w1", "as2_w2", "as2_w3"):
        u, _h = _hdr(client, make_user, name)
        signer_hdrs.append(_h)
        approvers.append({"userId": _user_id(u), "username": u,
                          "displayName": u})
    r = client.put(FLOW % VOUCHER_DOC_TYPE, headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [a]} for a in approvers]})
    assert r.status_code == 200, "存設定失敗：%s %s" % (r.status_code, r.text[:200])

    vr = client.post("/api/vouchers", headers=hdr, json={
        "summary": "走完三層",
        "lines": [{"account_code": "1113", "debit": 1000, "credit": 0},
                  {"account_code": "4111", "debit": 0, "credit": 1000}]})
    assert vr.status_code == 200, "建不起來：%s" % vr.text[:200]
    vid = vr.json()["id"]
    assert client.post("/api/vouchers/%s/submit" % vid, json={},
                       headers=hdr).status_code == 200, "送審失敗"

    for n in range(3):
        # `JV30`：有設定流程時每一層要由**那一層的簽核人**按（非當層簽核人 ⇒ 403）
        ar = client.post("/api/vouchers/%s/approve" % vid, json={},
                         headers=signer_hdrs[n])
        assert ar.status_code == 200, (
            "第 %d 次簽核失敗：%s %s\n" % (n + 1, ar.status_code, ar.text[:200])
            + "☠️ 三層以上的**推進邏輯從來沒有被跑過** ——\n"
              "   紅在這裡多半是**既有的推進邏輯**，不是 `AS2` 的新碼。")

    v = client.get("/api/vouchers/%s" % vid, headers=hdr).json()
    assert v.get("status") == "已核准", (
        "簽了三次而狀態是 %r —— 三層沒有走完。" % v.get("status"))

    slots = _slots(v)
    assert slots is not None, (
        "讀不到簽核格（找過四種鍵名）。現有鍵：%s" % sorted(v))
    # 📌 更正留著：原本是 `1 + 3`（製票＋三層）。`JV31`（商業會計法 §35）在最後
    #    加了一格「記帳」（過帳的人）⇒ 不變量改成「1 ＋ 層數 ＋ 1」，並釘最後一格。
    assert len(slots) == 1 + 3 + 1, (
        "設定三層，而簽核格有 %d 格：%r\n" % (len(slots), slots)
        + "☠️ 版面**沒有從資料算列數** —— 第三層的人簽了，\n"
          "   而**紙上沒有他的格子**。\n"
        + "🔑 不變量是「**格數 == 1 ＋ 層數**」（製票不算層），\n"
          "   而不是任何一個字面標籤。")
    assert list(slots)[-1] == "記帳", (
        "最後一格應該是「記帳」（`JV31`），實際是 %r" % list(slots))

    # ⚙️ 反向控制：第四次要被擋，而且**不可以是 500**
    extra = client.post("/api/vouchers/%s/approve" % vid, json={},
                        headers=hdr)
    assert extra.status_code in (400, 403), (
        "**第四次**簽核回 %s：%s\n" % (extra.status_code, extra.text[:200])
        + "☠️ 500 的話多半是 `currentTier` 無上限往前加 ⇒ `tiers[3]`\n"
          "   撞成 `IndexError` —— 而**三次那一題照樣綠**。")


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
    html = source_tree.page_file("voucher.html").read_text(
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
