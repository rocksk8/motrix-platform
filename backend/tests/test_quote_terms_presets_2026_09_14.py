"""報價條款組：付款條件／驗收標準／保固條件可成組自訂並切換（2026-09-14 交辦）。

使用者：「報價單可以增加付款條件的選項，名稱也可以自定義，例如純購料，他有
自己的付款條件、驗收標準、保固條件，可由報價人手動點選方塊做切換，只有超級
管理員可以點選設為預設付款條件的功能跟建立，像是完工單內單據用語這樣的選項」。

**核心設計決定**（測試釘住的就是這幾件）：
  ・讀取不限 superadmin——報價人要靠它切換
  ・寫入限 superadmin
  ・報價單存的是**複製過去的文字**不是 key：改設定不會動到已開出去的單
    （那條在前端，這裡守的是後端不會把單據跟設定綁在一起）
  ・刪掉被設為預設的那一組時，defaultKey 要自我修復，不能指向不存在的 key
"""
import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _preset(name, key="", **over):
    d = {"key": key, "name": name,
         "paymentTerms": f"{name} 的付款條件",
         "deliveryTerms": f"{name} 的交貨條件",
         "acceptanceTerms": f"{name} 的驗收標準",
         "warrantyTerms": f"{name} 的保固條件",
         "afterSales": f"{name} 的售後服務"}
    d.update(over)
    return d


@pytest.fixture
def sa(client, make_user):
    u, p = make_user(username="terms_sa", role="superadmin")
    return _login(client, u, p)


# ── 權限 ────────────────────────────────────────────────────────────────────

def test_unset_returns_empty_not_error(client, sa):
    """沒設定過時回空清單——前端會退回它內建的 DEFAULT_TERMS。
    **後端刻意不種一組預設**：那會變成兩個事實來源，而且分岔時不會有人報錯。"""
    r = client.get("/api/settings/quote-terms-presets", headers=sa)
    assert r.status_code == 200
    assert r.json() == {"presets": [], "defaultKey": ""}


def test_read_is_open_to_any_logged_in_user(client, make_user):
    """報價人要靠它切換條款組，讀取不能限 superadmin——限了等於這個功能
    只有 superadmin 用得到，而它是做給報價人用的。"""
    u, p = make_user(username="terms_sales", role="sales")
    r = client.get("/api/settings/quote-terms-presets", headers=_login(client, u, p))
    assert r.status_code == 200


def test_write_requires_superadmin(client, make_user):
    u, p = make_user(username="terms_adm", role="admin")
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset("純購料")], "defaultKey": ""},
                   headers=_login(client, u, p))
    assert r.status_code == 403


# ── 建立與內容 ──────────────────────────────────────────────────────────────

def test_create_assigns_keys_and_first_becomes_default(client, sa):
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset("標準工程"), _preset("純購料")],
                         "defaultKey": ""},
                   headers=sa)
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [p["key"] for p in body["presets"]]
    assert all(keys) and len(set(keys)) == 2, keys
    assert body["defaultKey"] == keys[0], "沒指定預設時應落在第一組，不能是空的"

    # 真的存進去了（不是只回傳）
    again = client.get("/api/settings/quote-terms-presets", headers=sa).json()
    assert [p["name"] for p in again["presets"]] == ["標準工程", "純購料"]
    assert again["presets"][1]["warrantyTerms"] == "純購料 的保固條件"


def test_all_five_fields_round_trip(client, sa):
    p = _preset("純購料", paymentTerms="貨到付款", acceptanceTerms="點交即驗收",
                warrantyTerms="依原廠保固", deliveryTerms="七日內", afterSales="無")
    client.put("/api/settings/quote-terms-presets",
               json={"presets": [p], "defaultKey": ""}, headers=sa)
    got = client.get("/api/settings/quote-terms-presets", headers=sa).json()["presets"][0]
    for k in ("paymentTerms", "deliveryTerms", "acceptanceTerms",
              "warrantyTerms", "afterSales"):
        assert got[k] == p[k], k


def test_explicit_default_is_honoured(client, sa):
    first = client.put("/api/settings/quote-terms-presets",
                       json={"presets": [_preset("A"), _preset("B")], "defaultKey": ""},
                       headers=sa).json()
    b_key = first["presets"][1]["key"]
    second = client.put("/api/settings/quote-terms-presets",
                        json={"presets": first["presets"], "defaultKey": b_key},
                        headers=sa).json()
    assert second["defaultKey"] == b_key


def test_deleting_the_default_group_self_heals(client, sa):
    """刪掉被設為預設的那一組時，defaultKey 不能留一個指向不存在的 key
    ——那會讓新報價單完全拿不到預設條款，而且畫面上看不出為什麼。"""
    first = client.put("/api/settings/quote-terms-presets",
                       json={"presets": [_preset("A"), _preset("B")], "defaultKey": ""},
                       headers=sa).json()
    a_key = first["presets"][0]["key"]
    assert first["defaultKey"] == a_key

    kept = [first["presets"][1]]
    after = client.put("/api/settings/quote-terms-presets",
                       json={"presets": kept, "defaultKey": a_key}, headers=sa).json()
    assert after["defaultKey"] == kept[0]["key"]
    assert len(after["presets"]) == 1


def test_all_deleted_leaves_empty_default(client, sa):
    client.put("/api/settings/quote-terms-presets",
               json={"presets": [_preset("A")], "defaultKey": ""}, headers=sa)
    after = client.put("/api/settings/quote-terms-presets",
                       json={"presets": [], "defaultKey": ""}, headers=sa).json()
    assert after == {"presets": [], "defaultKey": ""}


# ── 驗證 ────────────────────────────────────────────────────────────────────

def test_blank_name_rejected(client, sa):
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset("   ")], "defaultKey": ""}, headers=sa)
    assert r.status_code == 400


def test_duplicate_key_rejected(client, sa):
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset("A", key="same"), _preset("B", key="same")],
                         "defaultKey": ""}, headers=sa)
    assert r.status_code == 400


def test_over_long_content_rejected(client, sa):
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset("A", paymentTerms="x" * 5001)],
                         "defaultKey": ""}, headers=sa)
    assert r.status_code == 400


def test_too_many_presets_rejected(client, sa):
    r = client.put("/api/settings/quote-terms-presets",
                   json={"presets": [_preset(f"P{i}") for i in range(31)],
                         "defaultKey": ""}, headers=sa)
    assert r.status_code == 400


# ── 不會綁住既有報價單 ──────────────────────────────────────────────────────

def test_changing_presets_does_not_touch_existing_quotations(client, sa):
    """報價單存的是當下複製過去的文字，不是指向設定的連結——已經開出去的單
    不能因為有人事後改了條款組而跟著變。跟同日做的「單據原始版本存檔」同一個判準。"""
    import json as _json
    from db import get_db

    client.put("/api/settings/quote-terms-presets",
               json={"presets": [_preset("原始組")], "defaultKey": ""}, headers=sa)

    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("MQ-202609-888", "已送出", "客戶", "專案",
         _json.dumps({"paymentTerms": "原始組 的付款條件",
                      "termsPresetKey": "whatever"}, ensure_ascii=False),
         "2026-09-01", "2026-09-01"))
    conn.commit()
    conn.close()

    client.put("/api/settings/quote-terms-presets",
               json={"presets": [_preset("改過的組", paymentTerms="完全不同的條件")],
                     "defaultKey": ""}, headers=sa)

    conn = get_db()
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-202609-888'").fetchone()
    conn.close()
    assert _json.loads(row["data_json"])["paymentTerms"] == "原始組 的付款條件"


def test_update_is_audited(client, sa):
    from db import get_db
    client.put("/api/settings/quote-terms-presets",
               json={"presets": [_preset("純購料")], "defaultKey": ""}, headers=sa)
    conn = get_db()
    row = conn.execute(
        "SELECT target_label FROM audit_log "
        "WHERE action='settings.quote_terms_presets.update' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None, "變更公司對外條款沒有留下稽核紀錄"
    assert "純購料" in row["target_label"]
