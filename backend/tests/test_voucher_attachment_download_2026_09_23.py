# -*- coding: utf-8 -*-
"""`JV16` · 傳票附件要看得到（單一附件下載端點）。

使用者原話：
```
「傳票部分，上傳檔案在預覽中要顯示」
```

A 實查根因（比使用者講的更深）：
```
POST   /{id}/attachments           上傳 ✅
DELETE /{id}/attachments/{file_id} 刪除 ✅
GET    /{id}/pdf-download          併進 PDF ✅
❌ 沒有任何一支端點可以取出單一附件檔案
而 voucher.html 的附件列是 <span x-text="a.filename">，不是連結
```
⇒ 附件上傳得進去、列得出來、刪得掉、能併進 PDF —— 就是**看不到**。

# 🔴 本檔只寫①（後端取檔端點）。②（預覽 modal 內列出附件）是前端 UI，
# 見同批的 `test_jv16_attachment_list_in_modal_2026_09_23.py`。

# ⚙️ 路徑是本檔宣告的（規格沒有定死），照抄既有兩支的形狀

```
GET /api/vouchers/{voucher_id}/attachments/{file_id}
```
與 `POST .../attachments`、`DELETE .../attachments/{file_id}` 同一個
資源路徑，只是換方法——不是新資源。若 B 換路徑，退回改本檔常數。

# 🔴 這一份的核心是使用者拿不到的三格

```
③ 憑證只能是**唯讀端點常見的最省力寫法**才會犯的錯：
   把權限查詢放寬成「登入即可」，忘了同一份還要問「看得到這張傳票嗎」
④ file_id 若沒有同時核對 voucher_id，換一個 voucher_id 打同一個
   file_id 就變成跨傳票枚舉
⑤ 🔴🔴 最貴的一格：**token 放進 query string**
   ⇒ uvicorn access log 會把整串網址寫進 logs/server.log（已有先例
     實測過，`routers/uploads.py` 的 `?token=` 就是同一個問題被拿掉
     留下的教訓——那裡换成了 `?pt=` 短效簽章，這裡不需要：
     A 明確要求前端一律 fetch 帶 header，端點**不必**支援任何形式的
     query-string 憑證）
```
⚠️ **正對照要看得到 `routers/uploads.py` 的教訓**：那支端點的 docstring
逐字記著「2026-09-22 拿掉了 `?token=`」——這裡不是重蹈覆轍的問題，是
**這支端點打從一開始就不應該支援它**，比「拿掉」更便宜的是「沒加過」。
"""
import io

import pytest

DOWNLOAD = "/api/vouchers/%s/attachments/%s"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 401, 403, 404)

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]

#: 最小合法 1×1 PNG。
_ONE_PX_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}, r.json()["token"]


def _create(client, hdr):
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "JV16 附件下載測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _attach(client, hdr, vid, name="收據.png", content=_ONE_PX_PNG):
    r = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                    files={"files": (name, io.BytesIO(content), "image/png")})
    if r.status_code in (404, 405, 422):
        pytest.fail("附件端點還不存在（回 %s）—— `JV3` 先。" % r.status_code)
    assert r.status_code == 200, "附件上傳失敗：%s %s" % (r.status_code, r.text[:200])
    atts = r.json().get("attachments") or []
    assert atts, "上傳成功卻沒有回傳附件清單：%r" % r.json()
    return atts[-1]["file_id"]


def _reached(r):
    """`§166` 在這一支路徑上多一種臉：**FastAPI 自己的泛用 404**。

    ⚠️ **這支是全新的路徑＋方法組合**（不像 `pdf-download` 那種會被既有
    路由部分攔截），路徑完全不存在時 FastAPI 路由器連 405 都不會給——
    直接是它自己的 `{"detail": "Not Found"}`，**不是我們任何一處手寫的
    404**（我們的 404 一律是中文說明句）。用回應字面值分辨兩者，而不是
    把「405」當唯一的未實作信號——這支端點今天的真實現況就是走不到 405
    那條規則。
    """
    if r.status_code == 405:
        pytest.fail("`GET %s` 走不到（回 405）——這一支動詞還沒接上。"
                    % (DOWNLOAD % ("{id}", "{file_id}")))
    if r.status_code == 404:
        try:
            body = r.json()
        except Exception:                                       # noqa: BLE001
            body = {}
        if body.get("detail") == "Not Found":
            pytest.fail(
                "`GET %s` 走不到 —— FastAPI 自己的泛用 404\n"
                % (DOWNLOAD % ("{id}", "{file_id}"))
                + "（`{\"detail\": \"Not Found\"}`，不是我們手寫的中文 404，\n"
                  "   代表這條路徑＋方法組合根本沒有註冊）。")
    return r


# ══════════════════════════════════════════════════════════════════════
# ① 下得到、下對內容
# ══════════════════════════════════════════════════════════════════════

def test_jv16_downloading_an_attachment_returns_its_bytes(client, make_user):
    """🔴🔴 **核心：有權限的人打這支端點，拿回的是那個檔案本身。**"""
    _u, hdr, _tok = _hdr(client, make_user, "jv16_dl")
    vid = _create(client, hdr)
    file_id = _attach(client, hdr, vid)

    r = _reached(client.get(DOWNLOAD % (vid, file_id), headers=hdr))
    assert r.status_code == 200, (
        "下載失敗：%s %s" % (r.status_code, r.content[:200]))
    assert r.content == _ONE_PX_PNG, (
        "回來的位元組與上傳的不同（長度 %d vs %d）——\n"
        % (len(r.content), len(_ONE_PX_PNG))
        + "☠️ 那代表拿到的不是這個檔案，可能是路徑組錯了。")
    ctype = r.headers.get("content-type", "")
    assert "image" in ctype or "png" in ctype, (
        "Content-Type 是 %r，看不出是圖片。" % ctype)


# ══════════════════════════════════════════════════════════════════════
# ③ 權限：與傳票本身同一道閘門
# ══════════════════════════════════════════════════════════════════════

def test_jv16_requires_authorization_header(client, make_user):
    """🔴 **完全不帶 `Authorization` ⇒ 401，不是回檔案。**

    ⚠️ 同下一題查到的：今天這一格是 `main.py::auth_middleware` 對所有
    `/api/` 路徑的通則在擋，不是這支端點自己的判斷——端點今天還不存在，
    路由連走都走不到。這裡先不拿掉：它仍然驗到「這條路徑沒有被加進
    `auth_middleware` 的例外清單」，而那正是要一直保持的狀態。
    """
    _u, hdr, _tok = _hdr(client, make_user, "jv16_noauth")
    vid = _create(client, hdr)
    file_id = _attach(client, hdr, vid)

    r = _reached(client.get(DOWNLOAD % (vid, file_id)))
    assert r.status_code == 401, (
        "沒帶任何憑證卻回 %s（預期 401）：%s" % (r.status_code, r.content[:200]))


def test_jv16_a_token_in_the_query_string_is_not_accepted(client, make_user):
    """🔴🔴 **`⑤` 核心：把有效 token 塞進 query string，端點不可以買帳。**

    ```
    routers/uploads.py 的 docstring 逐字：
      「2026-09-22 拿掉了 ?token=」—— 完整 session token 放 query string，
      寫進 uvicorn access log（永久追加），也進瀏覽器歷史、Referer。
    ```
    🔑 這支端點**沒有加過**這個口子，比「拿掉」更便宜——這一題釘的是
    「沒有退路」，不是「補一個修補」。只驗**不帶** header 時擋下來不夠：
    一個「header 沒有就退回看 query string」的實作，正對照那題一樣會綠。

    ## 🔴 動工時查證發現：這一題今天的綠**不是**這支端點給的

    ```
    main.py::auth_middleware  對**所有** /api/ 路徑（除了明著列出的
    /api/uploads/?pt= 那個例外）一律要求 Authorization header ——
    連路徑根本不存在時，也是這支 middleware 先回 401，路由**永遠不會
    走到**我們自己的 handler。
    ```
    ⚙️ 實測過（打一個完全不存在的隨機路徑＋`?token=`，一樣回 401）。
    ⇒ 這一題證明的是**「這條路徑今天不在 `auth_middleware` 的例外清單
    裡」**，不是「這支端點自己拒絕了 query string」——這支端點今天
    根本還不存在。🔑 而這仍然是一個**值得留著的迴歸測試**：它擋的是
    未來有人比照 `/api/uploads/` 的 `?pt=` 做法，替這個路徑也加一個
    query-string 例外（那正是使用者原話擔心的事會重新打開的唯一方式）。
    """
    _u, hdr, tok = _hdr(client, make_user, "jv16_qstoken")
    vid = _create(client, hdr)
    file_id = _attach(client, hdr, vid)

    r = _reached(client.get(
        "%s?token=%s" % (DOWNLOAD % (vid, file_id), tok)))
    assert r.status_code in (401, 403), (
        "query string 帶 `?token=` 卻拿到 %s：%s\n" % (r.status_code,
                                                     r.content[:200])
        + "☠️ 這代表端點認 query string 裡的憑證 —— 那條路徑會被 uvicorn\n"
          "   access log 永久記錄在 `logs/server.log`，撿到記錄檔的人\n"
          "   等於撿到那個帳號的存取權。")


def test_jv16_a_user_without_voucher_access_is_refused(client, make_user):
    """🔴 **`③`：沒有 `cashier`／`finance` 模組的人 ⇒ 403，不是回檔案。**

    ⚠️ 角色用 `user` —— `superadmin` 會直通模組檢查（`helpers/auth.py:174`），
       拿它驗這道閘會**永遠不紅**。
    """
    owner, ohdr, _t = _hdr(client, make_user, "jv16_owner")
    vid = _create(client, ohdr)
    file_id = _attach(client, ohdr, vid)

    _u, nomod, _t2 = _hdr(client, make_user, "jv16_nomod", role="user",
                          modules=())
    r = _reached(client.get(DOWNLOAD % (vid, file_id), headers=nomod))
    assert r.status_code == 403, (
        "沒有傳票模組的人下載到附件了（回 %s）：%s\n"
        % (r.status_code, r.content[:200])
        + "☠️ 附件裡可能是銀行對帳單、身分證這類個資／財務憑證。")


def test_jv16_a_user_with_voucher_access_still_succeeds(client, make_user):
    """⚙️ **正對照：`③` 的另一半 —— 帶著 `cashier` 的一般員工要下得到。**

    ☠️ 少了它，一個「整支端點只放行 superadmin」的實作也會讓上一題綠，
       而那樣一般會計人員（帶 `cashier` 模組）自己也叫不出附件。
    """
    owner, ohdr, _t = _hdr(client, make_user, "jv16_owner2")
    vid = _create(client, ohdr)
    file_id = _attach(client, ohdr, vid)

    _u, hasmod, _t2 = _hdr(client, make_user, "jv16_hasmod", role="user",
                          modules=("cashier",))
    r = _reached(client.get(DOWNLOAD % (vid, file_id), headers=hasmod))
    assert r.status_code == 200, (
        "帶著 `cashier` 的一般員工被擋掉了（回 %s）：%s"
        % (r.status_code, r.content[:200]))


# ══════════════════════════════════════════════════════════════════════
# ④ file_id 要核對 voucher_id，不能跨傳票枚舉
# ══════════════════════════════════════════════════════════════════════

def test_jv16_a_file_id_from_a_different_voucher_is_refused(client, make_user):
    """🔴🔴 **`④`：拿別張傳票的 `file_id`，換一個 `voucher_id` 打，要 404。**

    ☠️ 若查詢只憑 `file_id`（不核對它是不是**這一張**傳票的附件），
       任何看得到自己傳票的人，只要**猜得到**別人的 `file_id`，
       就能下載到不屬於自己那張單的附件 —— 那是一種枚舉。
    """
    _u, hdr, _t = _hdr(client, make_user, "jv16_cross")
    v1 = _create(client, hdr)
    v2 = _create(client, hdr)
    file_id = _attach(client, hdr, v1)

    r = _reached(client.get(DOWNLOAD % (v2, file_id), headers=hdr))
    assert r.status_code == 404, (
        "用另一張傳票的 id 配這個 `file_id` 拿到 %s（預期 404）：%s\n"
        % (r.status_code, r.content[:200])
        + "☠️ 查詢沒有核對 `file_id` 是不是屬於這一張 `voucher_id`。")


def test_jv16_an_unknown_file_id_is_404(client, make_user):
    """⚙️ 正對照：不存在的 `file_id` 本來就該 404（確認判準不是永遠 404）。"""
    _u, hdr, _t = _hdr(client, make_user, "jv16_unknown")
    vid = _create(client, hdr)
    _attach(client, hdr, vid)  # 前置：這張單至少有一筆真的附件

    r = _reached(client.get(DOWNLOAD % (vid, "not-a-real-file-id"),
                            headers=hdr))
    assert r.status_code == 404, (
        "不存在的 `file_id` 拿到 %s（預期 404）：%s"
        % (r.status_code, r.content[:200]))


def test_jv16_a_deleted_attachment_cannot_be_downloaded(client, make_user):
    """🔴 **軟刪的附件不可以再下載得到。**

    `_attachments_of()` 的既有裁定是「已刪的仍留在表裡也留在備份裡」——
    這裡驗的是**這支新端點跟上同一條規則**，不是重新決定它。
    """
    _u, hdr, _t = _hdr(client, make_user, "jv16_deleted")
    vid = _create(client, hdr)
    file_id = _attach(client, hdr, vid)

    d = client.delete("/api/vouchers/%s/attachments/%s" % (vid, file_id),
                      headers=hdr)
    assert d.status_code == 200, "刪除失敗：%s %s" % (d.status_code, d.text[:200])

    r = _reached(client.get(DOWNLOAD % (vid, file_id), headers=hdr))
    assert r.status_code == 404, (
        "已經刪除的附件仍然下載得到（回 %s）：%s\n"
        % (r.status_code, r.content[:200])
        + "☠️ 使用者移除了一份憑證，而它其實還在——那與『刪除』的承諾不符。")
