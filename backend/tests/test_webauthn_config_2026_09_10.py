"""2026-09-10：WebAuthn RP ID／Origin 設定端點的驗證。

`f8198e9` 把這兩個值從環境變數改成 system_settings 可動態設定，動機正是
「正式機用 IP 服務時，寫死的 localhost 預設值會讓瀏覽器丟 invalid domain」。
但初版沒有任何格式驗證——填錯照樣存得進去，症狀跟改動前一模一樣（瀏覽器
一句沒有上下文的錯誤），等於把同一個坑從程式碼搬到設定頁。這裡把規則釘死。

另外驗證「改動 RP ID 會讓既有 Passkey 失效」這件事有被回報出來：憑證是被
瀏覽器綁在註冊當下的 RP ID 上，而 webauthn_credentials 沒有存 rp_id 欄位
（db.py _m073），改完之後系統查不出憑證原本屬於哪個 RP，只能事先講清楚。
"""
import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def su(client, make_user):
    username, password = make_user("wa_su", role="superadmin")
    return _login(client, username, password)


def _patch(client, token, rp_id, origin):
    return client.patch("/api/settings/webauthn-config", headers=_auth(token),
                        json={"rp_id": rp_id, "origin": origin})


def test_valid_pair_is_accepted(client, su):
    r = _patch(client, su, "erp.example.local", "https://erp.example.local:666")
    assert r.status_code == 200, r.text
    r = client.get("/api/settings/webauthn-config", headers=_auth(su))
    assert r.json()["rp_id"] == "erp.example.local"
    assert r.json()["origin"] == "https://erp.example.local:666"


def test_subdomain_origin_is_accepted(client, su):
    """Origin 是 RP ID 的子網域是合法的（WebAuthn 規格允許）。"""
    assert _patch(client, su, "example.local", "https://erp.example.local").status_code == 200


def test_localhost_over_http_is_accepted(client, su):
    """localhost 是規格裡唯一允許 http 的例外，開發環境要用得到。"""
    assert _patch(client, su, "localhost", "http://localhost:666").status_code == 200


@pytest.mark.parametrize("rp_id,origin,because", [
    ("https://erp.local", "https://erp.local", "RP ID 不該含 scheme"),
    ("erp.local:666", "https://erp.local:666", "RP ID 不該含連接埠"),
    ("erp_local", "https://erp_local", "底線不是合法網域字元"),
    ("erp.local", "erp.local", "Origin 不是完整來源"),
    ("erp.local", "https://erp.local/path", "Origin 不該含路徑"),
    ("erp.local", "https://other.local", "Origin 主機與 RP ID 無從屬關係"),
    ("erp.local", "http://erp.local", "非 localhost 不得用 http"),
])
def test_invalid_pairs_are_rejected(client, su, rp_id, origin, because):
    r = _patch(client, su, rp_id, origin)
    assert r.status_code == 400, f"{because}：預期 400，實際 {r.status_code} {r.text}"


def test_both_or_neither(client, su):
    assert _patch(client, su, "erp.local", "").status_code == 400
    assert _patch(client, su, "", "https://erp.local").status_code == 400
    # 同時清空是合法的（等於停用 WebAuthn，端點會回 503）
    assert _patch(client, su, "", "").status_code == 200


def test_non_superadmin_cannot_read_or_write(client, make_user):
    username, password = make_user("wa_admin", role="admin")
    token = _login(client, username, password)
    assert client.get("/api/settings/webauthn-config", headers=_auth(token)).status_code == 403
    assert _patch(client, token, "erp.local", "https://erp.local").status_code == 403


def test_changing_rp_id_reports_invalidated_credential_count(client, su):
    """既有 Passkey 會因為 RP ID 變更而全部失效，端點要把張數講出來。"""
    import db
    from datetime import datetime
    assert _patch(client, su, "old.local", "https://old.local").status_code == 200

    conn = db.get_db()
    try:
        for i in range(3):
            conn.execute(
                "INSERT INTO webauthn_credentials (user_id, credential_id, public_key, name, "
                "sign_count, created_at) VALUES (?,?,?,?,?,?)",
                (1, f"cred-{i}".encode(), b"pubkey", f"裝置{i}", 0, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/settings/webauthn-config", headers=_auth(su))
    assert r.json()["credentialCount"] == 3

    r = _patch(client, su, "new.local", "https://new.local")
    assert r.status_code == 200, r.text
    assert r.json()["invalidatedCredentials"] == 3, "改 RP ID 應回報受影響的憑證張數"

    # 同一組值重複存檔不算變更，不該誤報
    r = _patch(client, su, "new.local", "https://new.local")
    assert r.json()["invalidatedCredentials"] == 0
