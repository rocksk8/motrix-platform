# -*- coding: utf-8 -*-
"""`JV1` · 傳票**建立／清單／不平衡擋下／權限**（A 派工，使用者 04:36 原話）。

> 「像報價單一樣，可填寫可帶入已經上傳的檔案或是補檔最後做成這份，
>   要由出納**獨立作業**還有**送審流程**跟**編號**」

---

# 📏 現況（我實測，不是照收）

```
routers/vouchers.py  只有  GET /{voucher_id} ／ PUT /{voucher_id}
=> **建立、清單、送審、簽核、過帳、附件全部沒有**
helpers/voucher.py   有  check_balance ／ describe_balance ／ post_voucher …
```
🔴 **而 A 說的 `why_cannot_post` 不存在** —— 實際那一支叫 `describe_balance`：
```
describe_balance([(1000,0),(0,900)], status="已核准")
  => 「借貸不平衡，無法過帳：借方 1,000／貸方 900，**貸方少 100**」
```
⇒ 本檔用 `describe_balance` 的**行為**當判準（訊息要說得出差額），
   **而不釘那支函式的名字** —— 端點怎麼取得那句話是 B 的自由。

# ⚠️ 而「不平衡擋下」不可以擋到草稿

```
草稿  允許不平衡  <= 使用者正在打，打到一半本來就不平
過帳  必須平衡    <= 而不平衡要**說得出差額**
```
☠️ 反過來寫的症狀是**使用者打不完第一行就被擋住**
   （已在 `test_voucher_state_machine_2026_09_23.py` 釘過，這裡是它的端點版）。
"""
import json
import re
from datetime import date

import pytest

#: `SPEC-VOUCHER.md §一`：`YYYYMMDD-NNN[-Rn]`。
VOUCHER_NO = re.compile(r"^\d{8}-\d{3}(-R\d+)?$")

#: `routers/vouchers.py:34` 的模組閘。⚠️ 改了 **退回給我**。
VOUCHER_MODULES = ("cashier", "finance")


def _login(client, make_user, role="superadmin", modules=None, username=None):
    """⚠️ `users.modules` 存的是 **JSON 字串**，而 `modules=None` 會套角色樣板
    ⇒ 要驗「沒有模組」必須明著傳 `[]`。"""
    kw = {"role": role}
    if modules is not None:
        kw["modules"] = modules
    if username:
        kw["username"] = username
    u, p = make_user(**kw)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _ok_hdr(client, make_user, username):
    return _login(client, make_user, "superadmin", ["cashier"], username)[1]


def _assert_denied(r, why, role, modules, what):
    """該被擋的那幾格：**分辨「被擋住」與「端點還不存在」**。

    🔴 我第一版直接 `assert r.status_code == 403`，而端點不存在時回 **405**
       ⇒ 訊息印「**建得出傳票**（回 405）」—— **那是一句錯的話**，
          而它聽起來像量出來的（今晚第三次同形）。
    ⇒ 判準只描述我看到什麼：404/405 ＝ 端點還沒有；其餘非 403 ＝ 真的放行了。
    """
    if r.status_code in (404, 405):
        pytest.fail(
            "`%s` 還不存在（回 %s）—— **這一格量不到權限**。\n"
            % (what, r.status_code)
            + "⚠️ 端點**應該**存在 ⇒ 看 `JV1`；已完成 ⇒ 路徑或方法變了"
              "（**退回給我**）。")
    assert r.status_code == 403, (
        "%s（%s／%s）**沒有被擋**（回 %s）\n"
        % (why, role, modules or "無模組", r.status_code)
        + "☠️ 放錯人**沒有症狀** —— 沒有人會來報修"
          "「我做得到我不該做的事」。")


def _assert_allowed(r, why, role, modules, what, ok=(200, 201)):
    """該通過的那幾格 —— 同樣分辨「端點不存在」。"""
    if r.status_code in (404, 405):
        pytest.fail(
            "`%s` 還不存在（回 %s）—— **這一格量不到權限**。" % (what, r.status_code))
    assert r.status_code in ok, (
        "%s（%s／%s）被擋下來了：%s %s\n"
        % (why, role, modules or "無模組", r.status_code, r.text[:160])
        + "⚙️ 這是正對照：少了它，「一律 403」也會讓其餘幾格綠，\n"
          "   **而那樣沒有任何人做得了這件事**。")


_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


# ══════════════════════════════════════════════════════════════════════
# ① 建立草稿
# ══════════════════════════════════════════════════════════════════════

def test_jv1_creating_a_draft_returns_a_voucher_number(client, make_user):
    """🔴 `JV1①` **`POST /api/vouchers` 建立草稿，回**`voucher_no`。

    ```
    SPEC-VOUCHER §一  單號 YYYYMMDD-NNN[-Rn]
    ```
    ⚠️ 觀測點挑**下游欄位**不挑我送進去的值：
    ```
    我送的   lines / summary        <= 回聲，證明不了任何事
    我驗的   **voucher_no**（後端配的）＋ **status 是「草稿」**（後端定的）
             ＋ 再 GET 一次讀得回來（**它真的落地了**）
    ```
    ☠️ 只驗 201/200 的話，一支「什麼都不做只回 200」的端點也會綠。
    """
    hdr = _ok_hdr(client, make_user, "jv1_create")
    r = client.post("/api/vouchers",
                    json={"summary": "測試傳票", "lines": _LINES}, headers=hdr)
    assert r.status_code in (200, 201), (
        "`POST /api/vouchers` 回 %s：%s\n" % (r.status_code, r.text[:200])
        + "⚠️ 端點**應該**存在 ⇒ 看 `JV1`；已完成 ⇒ **那是路徑或方法變了**"
          "（改了 **退回給我**）。")

    body = r.json()
    no = body.get("voucher_no") or body.get("voucherNo")
    assert no, (
        "建立成功而回傳裡沒有 `voucher_no`：%r\n" % body
        + "☠️ 使用者拿不到單號 ⇒ 他無法在清單裡找回這一張。")
    assert VOUCHER_NO.match(no), (
        "單號是 %r，而 `§一` 的格式是 `YYYYMMDD-NNN[-Rn]`。\n" % no
        + "🔑 格式不對的話，退回升版那一支（`next_revision_no`）解析不了它 ——"
          "而它**不會報錯**，只會產生一個錯的單號。")

    vid = body.get("id") or body.get("voucher_id")
    assert vid, "回傳裡沒有 id ⇒ 後續的 GET／PUT 都找不到這一張。"
    got = client.get("/api/vouchers/%s" % vid, headers=hdr)
    assert got.status_code == 200, (
        "建立回 200 而 `GET /api/vouchers/%s` 回 %s ——\n"
        % (vid, got.status_code)
        + "☠️ **它沒有真的落地** ⇒ 一支「只回 200」的端點也會讓上面的斷言綠。")
    assert got.json().get("status") == "草稿", (
        "新建的傳票狀態是 %r，而它應該是「草稿」。\n"
        % got.json().get("status")
        + "🔑 狀態是**後端定的**，不是我送進去的 —— 這一格才證明它走過建立流程。")


def test_jv1_the_date_defaults_to_today_when_omitted(client, make_user):
    """🔴 `JV1①` **日期可選，不給就是今天**（`SPEC-VOUCHER §2.1`，使用者改裁）。

    ```
    舊裁示  「傳票日期由系統發」=> 被讀成「建檔當天且不可改」
    新裁示  **日期可選，預設今天**（月結補登是會計的日常）
    ```
    ⚙️ 而正對照是**給了日期就要用它** —— 少了那一格，
       一支「永遠寫今天」的實作也會讓這一題綠，**而補登就做不到了**。
    """
    hdr = _ok_hdr(client, make_user, "jv1_date")

    r = client.post("/api/vouchers",
                    json={"summary": "沒給日期", "lines": _LINES}, headers=hdr)
    assert r.status_code in (200, 201), r.text[:200]
    vid = r.json().get("id") or r.json().get("voucher_id")
    today = date.today().isoformat()
    got = client.get("/api/vouchers/%s" % vid, headers=hdr).json()
    assert got.get("voucher_date") == today, (
        "沒給日期時存成 %r，而今天是 %s。\n" % (got.get("voucher_date"), today)
        + "☠️ 使用者每開一張都要自己打日期 —— 而 99% 的情況就是今天。")

    r2 = client.post("/api/vouchers",
                     json={"summary": "補登八月", "voucher_date": "2026-08-31",
                           "lines": _LINES}, headers=hdr)
    assert r2.status_code in (200, 201), r2.text[:200]
    vid2 = r2.json().get("id") or r2.json().get("voucher_id")
    got2 = client.get("/api/vouchers/%s" % vid2, headers=hdr).json()
    assert got2.get("voucher_date") == "2026-08-31", (
        "給了 `2026-08-31` 而存成 %r ——\n" % got2.get("voucher_date")
        + "⚙️ 這是正對照：少了它，「永遠寫今天」也會讓上面那一格綠，\n"
          "   **而月結補登就做不到了**（那是使用者改裁的理由）。")


# ══════════════════════════════════════════════════════════════════════
# ② 清單
# ══════════════════════════════════════════════════════════════════════

def test_jv1_the_list_endpoint_returns_what_was_created(client, make_user):
    """🔴 `JV1②` **`GET /api/vouchers` 清單裡找得到剛建的那一張。**

    ⚠️ 觀測點是**剛建立的那個單號**，不是「清單非空」：
    ```
    清單非空  => 別人建的那幾張也會讓它綠
    找得到它  => **這一張真的進了清單**
    ```
    ⚙️ 而作廢那一格已經另外釘過（`vouchers` 是只露出未作廢的 VIEW），本題不重複。
    """
    hdr = _ok_hdr(client, make_user, "jv1_list")
    r = client.post("/api/vouchers",
                    json={"summary": "進清單", "lines": _LINES}, headers=hdr)
    assert r.status_code in (200, 201), r.text[:200]
    no = r.json().get("voucher_no") or r.json().get("voucherNo")

    lst = client.get("/api/vouchers", headers=hdr)
    assert lst.status_code == 200, (
        "`GET /api/vouchers` 回 %s：%s\n" % (lst.status_code, lst.text[:200])
        + "⚠️ 端點**應該**存在 ⇒ 看 `JV1②`。")
    payload = lst.json()
    rows = payload.get("vouchers") or payload.get("items") or payload
    nos = [(x.get("voucher_no") or x.get("voucherNo")) for x in rows]
    assert no in nos, (
        "剛建的 %r 不在清單裡。清單有 %d 張：%s\n" % (no, len(nos), nos[:6])
        + "☠️ 使用者建完之後**找不回那一張** —— 而建立那一步是成功的。")


# ══════════════════════════════════════════════════════════════════════
# ③ 不平衡擋下，而訊息要說得出差額
# ══════════════════════════════════════════════════════════════════════

_UNBALANCED = [{"account_code": "1113", "debit": 1000, "credit": 0},
               {"account_code": "4111", "debit": 0, "credit": 900}]


def _post_action(client, vid, hdr, body=None):
    """過帳那一支。路徑是 `§160` 定案的 `/post`，**不再試探**。

    ## 🔴 我第一版是假綠燈，而那個坑我在**同一個檔**裡寫過（B 抓到）

    ```python
    for suffix in ("/post", "/posting", "/confirm"):
        if r.status_code != 404:      # ← **只跳過 404**
            return suffix, r
    ```
    ```
    實測  /post ／ /posting ／ /confirm 全部回 **405** 不是 404
    成因  main.py 有 catch-all 路由吃掉那個路徑 => 路徑匹配到、方法不匹配
    ⇒ `!= 404` 為真 => **它以為找到過帳端點了**
    ⇒ `test_..._a_balanced_voucher_is_not_refused_by_the_same_path` 斷言
       `"不平衡" not in resp.text`，而 resp.text 是 {"detail":"Method Not Allowed"}
    ⇒ ⇒ **當然不含「不平衡」** => 綠，而過帳端點根本不存在
    ```
    ☠️ 而我在 `_assert_denied` 的 docstring 裡**逐字寫過 405 這件事** ——
       🔑 **我在一個 helper 裡修好了，而另一個沒有跟上。**
       ⇒ 同一輪、同一個檔、同一個坑：修一處不等於修掉那個形狀。
    """
    r = client.post("/api/vouchers/%s/post" % vid, json=body or {}, headers=hdr)
    if r.status_code in (404, 405):
        pytest.fail(
            "`POST /api/vouchers/{id}/post` 還不存在（回 %s）。\n" % r.status_code
            + "⚠️ 路徑是 `§160` 定案的 —— 改了 **退回給我**。\n"
            + "🔑 而**不要靜默回 None** ⇒ 那會讓下游的斷言"
              "拿一句 `{\"detail\":\"Method Not Allowed\"}` 去比對，**然後變綠**。")
    return "/post", r


def test_jv1_posting_an_unbalanced_voucher_is_refused_with_the_difference(
        client, make_user):
    """🔴🔴 `JV1③` **不平衡不可過帳，而訊息要說得出差額。**

    ```
    借 1000 ／ 貸 900  =>  拒絕，**而訊息要含 100**
    ```
    ☠️ 只說「借貸不平衡」的話，使用者要自己把每一行加一次 ——
       🔑 **而那個數字是檢查它的人手上就有的。**
    📌 `helpers/voucher.py` 已經有 `describe_balance()`，它回的是
       「借貸不平衡，無法過帳：借方 1,000／貸方 900，**貸方少 100**」
       ⇒ 端點把那句話帶出來就好，**不必再寫一份**。
    ⚠️ （A 的派工寫 `why_cannot_post`，而那支不存在 —— 我用實際那一支。）

    ⚙️ 而**草稿不可以被擋** —— 見下一題。
    """
    hdr = _ok_hdr(client, make_user, "jv1_bal")
    r = client.post("/api/vouchers",
                    json={"summary": "不平衡", "lines": _UNBALANCED},
                    headers=hdr)
    assert r.status_code in (200, 201), (
        "**建立**一張不平衡的草稿被擋下來了：%s %s\n"
        % (r.status_code, r.text[:160])
        + "☠️ 使用者打到一半本來就不平 ⇒ **他打不完第一行就被擋住**。")
    vid = r.json().get("id") or r.json().get("voucher_id")

    suffix, resp = _post_action(client, vid, hdr)
    assert suffix is not None, (
        "找不到過帳端點（試過 `/post` `/posting` `/confirm`）——\n"
        + "⚠️ 路徑可以換（**退回給我**），而 `JV1③` 要的是"
          "「**過帳時**擋不平衡」，不是建立時擋。")
    assert resp.status_code >= 400, (
        "借 1000／貸 900 的傳票**過帳成功**（回 %s）——\n" % resp.status_code
        + "☠️ 一張不平衡的傳票進了帳，而它之後只能靠人工對帳發現。")
    text = resp.text
    assert "100" in text, (
        "擋下來了，而訊息裡沒有差額 `100`：%s\n" % text[:240]
        + "🔑 不說差額的話，使用者要自己把每一行加一次 ——\n"
          "   **而那個數字是檢查它的人手上就有的**"
          "（`helpers/voucher.py::describe_balance` 已經算好了）。")


def test_jv1_a_balanced_voucher_is_not_refused_by_the_same_path(
        client, make_user):
    """⚙️ **正對照：平衡的那一張不可以被同一條路擋掉。**

    ☠️ 少了它，一支「一律拒絕過帳」的實作也會讓上一題綠 ——
       而症狀是**沒有任何一張傳票過得了帳**。
    ⚠️ 而這一題**不要求它成功** —— 過帳還需要「已核准」（`§六②`），
       而簽核流程不在 `JV1` 範圍裡。
       ⇒ 判準是：**拒絕的理由不可以是「不平衡」**。
    """
    hdr = _ok_hdr(client, make_user, "jv1_bal_ok")
    r = client.post("/api/vouchers",
                    json={"summary": "平衡", "lines": _LINES}, headers=hdr)
    assert r.status_code in (200, 201), r.text[:200]
    vid = r.json().get("id") or r.json().get("voucher_id")

    suffix, resp = _post_action(client, vid, hdr)
    if suffix is None:
        pytest.fail("找不到過帳端點 —— 見上一題。")
    assert "不平衡" not in resp.text, (
        "借 1000／貸 1000 的傳票被判「不平衡」：%s\n" % resp.text[:240]
        + "⚙️ 這是正對照：少了它，「一律拒絕」也會讓上一題綠，\n"
          "   **而那樣沒有任何一張傳票過得了帳**。")


# ══════════════════════════════════════════════════════════════════════
# ④ 權限：非 cashier/finance 一律 403（**含管理者**）
# ══════════════════════════════════════════════════════════════════════

#: `(角色, 模組, 該不該過)`。🔴 **管理者那一格是重點**（使用者 2026-09-14 裁示）。
JV1_ACCESS = (
    ("superadmin", [],           True,  "superadmin 不受模組限制"),
    ("admin",      [],           False, "🔴 **管理者無模組一樣 403** —— 不可直通"),
    ("admin",      ["reports"],  False, "🔴 管理者有**別的**模組也是 403"),
    ("admin",      ["cashier"],  True,  "管理者有 cashier"),
    ("user",       ["finance"],  True,  "一般使用者有 finance"),
    ("user",       ["reports"],  False, "一般使用者有別的模組"),
    ("user",       [],           False, "一般使用者無模組"),
)


@pytest.mark.parametrize("role,modules,allowed,why", JV1_ACCESS,
                         ids=[f"{r}_{'-'.join(m) or 'none'}"
                              for r, m, _a, _w in JV1_ACCESS])
def test_jv1_who_may_create_a_voucher(client, make_user, role, modules,
                                      allowed, why):
    """🔴 `JV1④` **建立傳票的權限七格。**

    ☠️ 傳票是**會計憑證** —— 放錯人進來的症狀是**沒有症狀**：
       帳上多一張單，而它看起來跟其他每一張一樣。
    🔑 而「管理者一樣依據有開權限的內容去顯示」是使用者 2026-09-14 的逐字裁示
       ⇒ **`role in ("superadmin","admin")` 那種寫法在這裡是錯的**。
    ⚙️ 正對照在同一張表裡：該過的三格要過，否則「一律 403」也會讓四格綠。
    """
    hdr = _login(client, make_user, role, modules,
                 "jv1p_%s_%s" % (role, "".join(modules) or "none"))[1]
    r = client.post("/api/vouchers",
                    json={"summary": "權限測試", "lines": _LINES}, headers=hdr)
    what = "POST /api/vouchers"
    if allowed:
        _assert_allowed(r, why, role, modules, what)
    else:
        _assert_denied(r, why, role, modules, what)


@pytest.mark.parametrize("role,modules,allowed,why", JV1_ACCESS,
                         ids=[f"{r}_{'-'.join(m) or 'none'}"
                              for r, m, _a, _w in JV1_ACCESS])
def test_jv1_who_may_list_vouchers(client, make_user, role, modules,
                                   allowed, why):
    """🔴 `JV1④` **清單走同一道閘。**

    ⚠️ 讀與寫用不同判準是最常見的形狀：
    ```
    建立擋住了、清單忘了擋 => 他開不了傳票，**而他看得到全公司的傳票**
    ```
    🔑 而傳票清單上有摘要與金額 —— 那是財務資料。
    """
    hdr = _login(client, make_user, role, modules,
                 "jv1l_%s_%s" % (role, "".join(modules) or "none"))[1]
    r = client.get("/api/vouchers", headers=hdr)
    what = "GET /api/vouchers"
    if allowed:
        _assert_allowed(r, why, role, modules, what, ok=(200,))
    else:
        _assert_denied(r, why, role, modules, what)


# ══════════════════════════════════════════════════════════════════════
# ⚙️ A-2 追加：**規則有沒有被 API 呼叫到**（不是「規則本身對不對」）
# ══════════════════════════════════════════════════════════════════════

def test_jv1_the_api_really_goes_through_the_balance_helper(client, make_user,
                                                            monkeypatch):
    """🔴🔴 **端點要真的走過 `helpers/voucher.py` 的平衡檢查。**

    A-2 指出的那一格：
    > 規則寫對而**沒有人叫它**，測試照樣綠。

    ☠️ 而它有一個很具體的長相：端點自己寫一份
    ```python
    if sum(debit) != sum(credit):        # <= 第二份實作
        raise HTTPException(400, "借貸不平衡")
    ```
    ⇒ 兩份會分岔，而分岔之後**沒有人知道哪一份是真的** ——
      而它**一開始是綠的**（兩份剛寫好時算出同一個答案）。

    ⚙️ 做法：把 `modules.accounting.voucher` 的檢查換成一個**會留下指紋**的替身。
       ```
       替身被呼叫 => 端點的拒絕訊息裡會出現那個指紋
       替身沒被呼叫 => 指紋不在 => **它自己算了一份**
       ```
    🔑 而指紋挑一個**不可能自然出現**的字串 —— 否則「碰巧包含」也會讓它綠。
    """
    import modules.accounting.voucher as hv

    FINGERPRINT = "\u2603JV1-HELPER-WAS-CALLED\u2603"
    called = {"n": 0}
    real = hv.describe_balance

    def _spy(lines, status="草稿"):
        called["n"] += 1
        out = real(lines, status)
        return (out + FINGERPRINT) if out else out

    monkeypatch.setattr(hv, "describe_balance", _spy)
    for mod_name in ("modules.accounting.api.vouchers",):
        try:
            mod = __import__(mod_name, fromlist=["x"])
        except Exception:                                  # noqa: BLE001
            continue
        if hasattr(mod, "describe_balance"):
            monkeypatch.setattr(mod, "describe_balance", _spy)

    hdr = _ok_hdr(client, make_user, "jv1_spy")
    r = client.post("/api/vouchers",
                    json={"summary": "走不走 helper", "lines": _UNBALANCED},
                    headers=hdr)
    if r.status_code in (404, 405):
        pytest.fail(
            "`POST /api/vouchers` 還不存在（回 %s）—— **這一格量不到**。"
            % r.status_code)
    vid = r.json().get("id") or r.json().get("voucher_id")
    assert vid, "建立不平衡的草稿失敗：%s %s" % (r.status_code, r.text[:160])

    suffix, resp = _post_action(client, vid, hdr)
    if suffix is None:
        pytest.fail("找不到過帳端點 —— 見 `JV1③`。")

    assert called["n"] > 0, (
        "過帳被處理了，而 `modules.accounting.voucher.describe_balance` **一次都沒被呼叫**。\n"
        + "☠️ 那表示端點**自己寫了一份**平衡檢查 ⇒ 兩份會分岔，\n"
          "   而分岔之後沒有人知道哪一份是真的 —— **它一開始是綠的**。\n"
        + "✅ 叫 `helpers/voucher.py` 那一支：差額那句話它已經算好了。")
    assert FINGERPRINT in resp.text, (
        "helper 被呼叫了，而它的輸出**沒有進到回應裡**：%s\n" % resp.text[:240]
        + "☠️ 那表示端點叫了它、然後**丟掉結果自己寫了一句** ——\n"
          "   而使用者看到的是那句自己寫的，差額就不見了。")
