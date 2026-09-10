"""2026-09-10：WebAuthn 的 base64url 解碼——Passkey 註冊與登入從來沒成功過的原因。

`routers/auth.py` 的註冊／登入完成端點原本用 `base64.b64decode()` 解 `rawId`。
那是**標準** base64 解碼器：不認得 base64url 的 `-` 和 `_`（預設把非字母字元
丟掉），又要求 padding 長度正確。而前端 `_uint8ArrayToB64()` 產出的正是
「base64url 且把 `=` 全部去掉」的格式，於是每一次都丟

    binascii.Error: Incorrect padding

錯誤被上層的 `except Exception` 收斂成一句籠統的「認證器驗證失敗」，畫面上
完全看不出真正原因——是靠正式機 `server.log` 裡的
`WebAuthn registration failed: Incorrect padding` 才定位到的。

這批測試釘住三件事：
  ① 解碼器吃得下前端**實際**產出的格式（用 JS 那段轉換的等價 Python 重現）
  ② 也吃得下標準 base64（login.html 一度送這種，避免日後換寫法又踩）
  ③ 端點不會再因為 padding 而失敗（會因為別的原因失敗，但不是這個）
"""
import base64

import pytest


def _js_uint8array_to_b64(raw: bytes) -> str:
    """前端 _uint8ArrayToB64() 的等價實作：

        btoa(binary).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=/g,'')

    也就是 base64url、且把 padding 全部去掉。
    """
    return (base64.b64encode(raw).decode()
            .replace("+", "-").replace("/", "_").replace("=", ""))


@pytest.mark.parametrize("size", [1, 2, 3, 16, 20, 32, 64, 65])
def test_decodes_exactly_what_the_frontend_produces(size):
    """任何長度都要能原樣解回——padding 需求隨長度 mod 3 變化，
    只測一種長度會漏掉真正會出事的那些。"""
    from routers.auth import _b64url_decode

    raw = bytes(range(256))[:size] if size <= 256 else bytes(size)
    encoded = _js_uint8array_to_b64(raw)
    assert "=" not in encoded, "前端格式本來就不該有 padding，測試前提錯了"
    assert _b64url_decode(encoded) == raw


def test_old_implementation_really_did_fail():
    """釘住「舊寫法真的會壞」——避免有人看到修正覺得多此一舉又改回去。"""
    raw = bytes(range(20))          # 20 bytes → base64 需要 1 個 '='
    encoded = _js_uint8array_to_b64(raw)
    with pytest.raises(Exception) as ei:
        base64.b64decode(encoded)
    assert "padding" in str(ei.value).lower(), f"預期 padding 錯誤，實際 {ei.value}"


def test_also_accepts_standard_base64():
    """login.html 一度送標準 base64（含 padding、用 +/）。後端要能容忍，
    否則換前端寫法就會再壞一次。"""
    from routers.auth import _b64url_decode

    raw = bytes([251, 255, 254, 190, 63, 62]) * 4   # 刻意產生會用到 + 和 / 的位元組
    std = base64.b64encode(raw).decode()
    assert "+" in std or "/" in std, "測試資料沒有涵蓋 +/ 字元，換一組"
    assert _b64url_decode(std) == raw


def test_register_complete_no_longer_fails_on_padding(client, make_user, caplog):
    """端點層級：送前端格式的 rawId，不該再出現 padding 錯誤。

    完整註冊需要真實認證器的簽章，這裡不可能偽造，所以只驗證「失敗原因不是
    padding」——也就是至少走過了解碼那一關。
    """
    import json
    import logging

    import db

    # 這題要驗的是解碼那一關，所以得先讓端點過得了「RP ID 已設定」的守門。
    # 直接種進 system_settings（值是 JSON 字串，見 helpers 的 _get_setting）。
    conn = db.get_db()
    try:
        for k, v in (("webauthn_rp_id", "motrix.internal"),
                     ("webauthn_origin", "https://motrix.internal:666")):
            conn.execute(
                "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (k, json.dumps(v), "2026-09-10T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    username, password = make_user(username="wa_user", role="admin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    begin = client.post("/api/auth/webauthn/register/begin", headers=headers)
    assert begin.status_code == 200, (
        f"種了 RP ID 之後 register/begin 仍失敗：{begin.status_code} {begin.text}")
    challenge_token = begin.json()["challengeToken"]

    with caplog.at_level(logging.ERROR):
        resp = client.post("/api/auth/webauthn/register/complete", headers=headers, json={
            "challengeToken": challenge_token,
            "id": "dummy",
            "type": "public-key",
            "rawId": _js_uint8array_to_b64(bytes(range(32))),
            "response": {
                "clientDataJSON": _js_uint8array_to_b64(b'{"type":"webauthn.create"}'),
                "attestationObject": _js_uint8array_to_b64(b"not-a-real-attestation"),
            },
        })

    assert resp.status_code == 400, resp.text   # 假的簽章本來就該被拒

    # 這裡不能只驗「不是 padding 錯誤」——那樣太寬鬆，2026-09-10 就是因此讓
    # 下一關（缺 `type` 欄位）漏掉：padding 修好之後測試照樣綠，使用者卻還是
    # 拿到「認證器驗證失敗」。改成把**已知的結構性錯誤**全部列為不允許，
    # 只有「真的走到密碼學驗證才失敗」才算通過。
    STRUCTURAL = [
        "padding",                    # base64 解碼（_b64url_decode）
        "unexpected type",            # 缺 type 欄位
        "missing required",           # 缺 id / rawId / response / clientDataJSON…
        "not a json object",
        "unable to decode credential",
    ]
    low = caplog.text.lower()
    hit = [k for k in STRUCTURAL if k in low]
    assert not hit, (
        f"credential 結構沒送對，卡在 {hit} 而不是密碼學驗證：\n" + caplog.text[-600:]
    )


def test_type_defaults_when_client_omits_it(client, make_user):
    """前端沒送 `type` 時，後端模型的預設值要補上 "public-key"。

    py_webauthn 會驗這個欄位，缺了就丟 InvalidJSONStructure。前端現在已經補送，
    但舊版前端（瀏覽器快取、或還沒重新整理的分頁）仍可能不送——那種情況不該
    再讓整條路壞掉。
    """
    from routers.auth import WebauthnRegisterCompleteIn, WebauthnLoginCompleteIn

    reg = WebauthnRegisterCompleteIn(
        challengeToken="t", id="i", rawId="r", response={})
    assert reg.type == "public-key"
    assert "type" in reg.dict(), "type 沒有進 dict()，等於沒傳給 py_webauthn"

    log = WebauthnLoginCompleteIn(
        challengeToken="t", username="u", id="i", rawId="r", response={})
    assert log.type == "public-key"
    assert "type" in log.dict()
