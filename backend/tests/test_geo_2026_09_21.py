"""§3l · 辦公室地址欄位 ＋ 免金鑰地圖（Leaflet/OSM）＋ 距離。

對應 `docs/windows/STATE.md` §3l（`ff8adfe` 之後、含 A 兩次更正的版本）。

## 🔴 我沒有讀實作

`helpers/geo.py` 還不存在（`import` 查過）。`system.py` 那兩題我**讀了**
`_COMPANY_PROFILE_DEFAULT` 與 `set_company_profile`，因為 M1／M2 驗的正是它們
現在的行為 —— **那不是「讀實作來寫測試」，是「被測對象就是那幾行」。**

## 🔑 這一批裡最毒的一件：**兩個成因、同一個畫面、相反的處置**

| 成因 | 畫面 | 該怎麼辦 |
|---|---|---|
| **M6** 標案 `location` 是 NULL | 地圖上少幾個點 | **要講出「有 N 筆沒有地點資訊」** |
| **M13** Google 金鑰是空的 | 那一塊一個點都沒有 | **整塊不要渲染** |

☠️ 兩者在畫面上**長得一模一樣**（一張乾淨、看起來完全正常的地圖），
**而使用者看到的只有那個畫面。** 少幾個點跟「那些標案不存在」也長得一樣，
**而且沒有人會報修。**

## 📌 我釘的名字（§3l 沒有全部指定，B 若要改請先講）

| 名字 | 形狀 |
|---|---|
| `helpers/geo.py` | 新模組 |
| `geo.GEO_ENABLED` | 字面值 `False`（出貨預設關）|
| `geo.geo_on()` | `GEO_ENABLED or os.getenv("MOTRIX_GEO") == "1"` |
| `geo.geocode(address)` | 回 `(coord, error)`，其一為 `None`；`coord` 是 `(lat, lon)` |
| `geo.haversine_km(a, b)` | 純函式，兩個 `(lat, lon)` 進、公里出 |
| `geo.USER_AGENT` / `FETCH_TIMEOUT_SECONDS` / `GEOCODE_INTERVAL_SECONDS` | 四道護欄（M8）|
| `GET /api/tender-radar/map` | 地圖資料端點（見 `MAP_KEYS`）|
| 設定鍵 `google_maps_api_key` | M12 |

⚠️ `geocode` **必須走模組屬性**（`geo.geocode(...)`，不可以 `from geo import geocode`），
否則 monkeypatch 打不到 —— 這是今天第八次遇到同一件事。
"""
import json

import pytest

from helpers.settings import _get_setting, _set_setting

try:
    from helpers import geo
except Exception as exc:  # noqa: BLE001
    geo = None
    _GEO_ERR = repr(exc)

MAP_PATH = "/api/tender-radar/map"
KEY_SETTING = "google_maps_api_key"

#: 地圖端點回應必須有的鍵。**名字是我釘的**，形狀的理由見各題。
MAP_KEYS = ("office", "officeMissing", "points", "withoutLocation",
            "googleMapsConfigured")

#: 七個既有欄位 —— M2 要證明它們不會被一次只送 address 的 PUT 清掉。
LEGACY_PROFILE = {
    "name": "允碩整合集創股份有限公司",
    "tax_id": "60575481",
    "contact_info": "Tel: 04-3610-6566｜info@miactw.com",
    "bank_name": "玉山銀行",
    "bank_branch": "台中分行",
    "bank_account_name": "允碩整合集創股份有限公司",
    "bank_account_number": "1234567890",
}

TAIPEI = (25.0330, 121.5654)
TAOYUAN = (24.9937, 121.3010)


def _geo(name=None):
    if geo is None:
        raise AssertionError(
            f"backend/helpers/geo.py 還不存在（或 import 失敗）：{_GEO_ERR}"
        )
    if name and not hasattr(geo, name):
        raise AssertionError(f"helpers/geo.py 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉")
    return getattr(geo, name) if name else geo


def _auth(client, make_user, role="superadmin"):
    username, password = make_user(role=role)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed_legacy_profile():
    """把 `company_profile` 種成**舊 shape**（七個鍵，沒有 address）。

    ⚠️ 這才是「既有安裝」的樣子。用 `_seed_setting` 是種不出來的 ——
    它是 `ON CONFLICT DO NOTHING`，對已經存在的那一列**一個字都不會改**。
    """
    _set_setting("company_profile", dict(LEGACY_PROFILE))
    stored = _get_setting("company_profile", {})
    assert set(stored) == set(LEGACY_PROFILE), (
        f"前提沒種好：{sorted(stored)}"
    )
    assert "address" not in stored, "前提沒種好：舊 shape 不該有 address"


# ══════════════════════════════════════════════════════════════════════
# M1／M2 · 辦公室地址欄位（被測對象是 routers/system.py）
# ══════════════════════════════════════════════════════════════════════

def test_m1_existing_database_reads_address_as_empty_string(client, make_user):
    """🔴 M1：**既有資料庫**讀得到 `address`，值是**空字串**。

    不是 `KeyError`、不是 `None` —— 前端才不用每個欄位自己防 `undefined`。

    ## 🔴 讓這件事成立的不是 `_seed_setting`

    `db.py` 的 seed 是 `ON CONFLICT(key) DO NOTHING` ⇒ **既有那一列不會被更新**。
    真正讓既有安裝讀得到的是讀取端的預設合併：

        system.py:623
        return {**_COMPANY_PROFILE_DEFAULT, **(_get_setting("company_profile", {}) or {})}

    ⇒ **要改的是 `_COMPANY_PROFILE_DEFAULT`**（`system.py:612`）。
    📌 銀行那四欄 2026-08-24 就走過這條路，那行註解寫的就是同一件事。
    ⚠️ 只改 `db.py` 的話這題會紅，**而紅的原因看起來像「migration 沒跑」**。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    r = client.get("/api/settings/company-profile", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "address" in body, (
        f"既有資料庫讀不到 address 這個鍵。實際：{sorted(body)}\n"
        "⇒ 八成只加進了 db.py 的 seed，而 seed 是 ON CONFLICT DO NOTHING，"
        "既有那一列一個字都不會變。要加的是 _COMPANY_PROFILE_DEFAULT。"
    )
    assert body["address"] == "", (
        f"address 是 {body['address']!r}，應為空字串 —— "
        "`None` 會讓前端每個用到它的地方都要防 undefined"
    )


def test_m1b_legacy_seven_fields_survive_the_read(client, make_user):
    """M1 的前提：讀出來時**既有七欄的值還在**。

    ⚠️ 沒有這一題，一個「讀的時候直接回預設」的實作會讓 M1 全綠 ——
    而那代表每一家客戶的抬頭、統編、銀行帳號在畫面上**全部變空**。
    🔑 合併方向是 `{**預設, **存的}`，**存的永遠贏**；寫反就是上面那個災難。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    body = client.get("/api/settings/company-profile", headers=hdr).json()
    for key, value in LEGACY_PROFILE.items():
        assert body.get(key) == value, (
            f"{key} 讀出來是 {body.get(key)!r}，存的是 {value!r} —— "
            "合併方向寫反了（`{**存的, **預設}`）：這會把每一家客戶的公司抬頭、"
            "統編、銀行帳號全部清成空字串，而畫面上是「欄位都在、只是空的」，"
            "跟「新裝的機器還沒填」長得一模一樣。"
        )


def test_m2_saving_only_the_address_keeps_the_other_seven(client, make_user):
    """🔴🔴 M2：只送 `{"address": ...}` 的 PUT，**其餘七欄必須原值不動**。

    ## ⚠️ 這裡不能用 `key in body`，因為收的是 Pydantic 模型不是 dict

    `set_company_profile(body: CompanyProfile, ...)` ⇒ **Pydantic 會先把沒送的
    欄位填成 `''`** ⇒ 進到 handler 時「沒送」與「送了空字串」**已經被壓成同一個值**。
    （`tender-radar` 那邊是 `body: dict = Body(...)`，所以那邊 `key in body` 成立
    —— **兩邊不一樣，抄過來會失效而且安靜。**）

    ## ☠️ 而這個專案早就有標準答案，連註解都寫好了

        suppliers.py:101
        # 只有「這次真的送了 lead_time_days」才動它。沒送就保持原值——
        # 不知道有這個欄位的舊前端，不應該因為存了一次供應商就把它清掉。
        suppliers.py:106   if "lead_time_days" in body.model_fields_set:

    **全庫只有那一處在用 `model_fields_set`。**
    🔑 坑踩過了、修好了、註解留著了，**而慣例沒有被推廣** —— 所以今天被重新發現一次。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    r = client.put("/api/settings/company-profile", headers=hdr,
                   json={"address": "台中市西屯區文心路二段201號"})
    assert r.status_code == 200, r.text

    stored = _get_setting("company_profile", {})
    assert stored.get("address") == "台中市西屯區文心路二段201號", (
        f"address 沒存進去：{stored.get('address')!r}"
    )
    wiped = {k: v for k, v in LEGACY_PROFILE.items() if stored.get(k) != v}
    assert not wiped, (
        f"只送了 address，而這幾欄被清掉了：{ {k: stored.get(k) for k in wiped} }\n"
        "⇒ Pydantic 把沒送的欄位填成 '' 了。要用 `body.model_fields_set` 判斷"
        "「這次真的送了哪幾個」——形狀照 suppliers.py:106。"
    )


def test_m2b_explicitly_clearing_a_field_still_works(client, make_user):
    """M2 的對照組：**明確送空字串時要真的清掉**。

    ⚠️ 沒有這一題，一個「空字串一律忽略」的實作會讓 M2 全綠 ——
    而那會讓使用者**永遠刪不掉**填錯的銀行帳號。
    🔑 「沒送」與「送了空字串」是兩件事，**而 Pydantic 預設會把它們壓成一件**。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    r = client.put("/api/settings/company-profile", headers=hdr,
                   json={"bank_account_number": ""})
    assert r.status_code == 200, r.text
    stored = _get_setting("company_profile", {})
    assert stored.get("bank_account_number") == "", (
        f"明確送了空字串卻沒有被清掉：{stored.get('bank_account_number')!r} —— "
        "使用者刪不掉填錯的帳號"
    )
    assert stored.get("name") == LEGACY_PROFILE["name"], "其他欄位被波及了"


def test_m12_google_maps_key_is_readable_on_an_existing_database(client, make_user):
    """M12：設定頁的 **Google Maps 金鑰**欄位，既有資料庫也要拿得到。

    📌 跟 `address` 同一個坑（M1）。不需要擋 git —— 它在資料庫裡，不在程式碼裡。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    r = client.get("/api/settings/company-profile", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert KEY_SETTING in body or "googleMapsApiKey" in body, (
        f"讀不到 Google Maps 金鑰欄位。實際：{sorted(body)}\n"
        f"（我釘的鍵是 `{KEY_SETTING}`，要改名請先講）"
    )


def test_m14_the_api_key_never_reaches_the_logs(client, make_user, caplog):
    """⚠️ M14：金鑰**不可以寫進任何 log**。

    📌 它會被送到前端 —— 那是 Maps JS API 的正常用法，**不是洩漏**。
    但伺服器記錄是另一個**保存期限完全不同**的地方：
    log 會被打包、被寄出、被放進備份，而那些地方沒有人在管金鑰。

    ## 🔴 這一題的第一版是空集合假綠燈（我自己抓到的）

    第一版只寫「log 裡不可以有這個字串」。**它必然綠** ——
    金鑰那時根本存不進去（`CompanyProfile` 沒有那個欄位，Pydantic 直接忽略），
    **而一個從來沒有被處理過的秘密當然不會外洩。**

    🔑 **「沒有洩漏」與「沒有東西可以洩漏」在斷言上長得一模一樣。**
    ⇒ 先釘住「它真的被存起來了」，再驗「而它沒有進 log」。
    （今天第三次：`tender_hits` 空表、`.get()` 對不存在的鍵、這一次。）
    """
    secret = "AIzaSyD-THIS-IS-A-FAKE-KEY-FOR-TESTS-0000"
    hdr = _auth(client, make_user)
    with caplog.at_level(0):
        r = client.put("/api/settings/company-profile", headers=hdr,
                       json={KEY_SETTING: secret})
        assert r.status_code == 200, r.text
        client.get("/api/settings/company-profile", headers=hdr)

    stored = _get_setting("company_profile", {}) or {}
    assert stored.get(KEY_SETTING) == secret, (
        f"前提不成立：金鑰根本沒有被存起來（{stored.get(KEY_SETTING)!r}）——"
        "這題會在「沒有東西可以洩漏」的情況下變成必然綠"
    )
    leaked = [r.getMessage() for r in caplog.records if secret in r.getMessage()]
    assert not leaked, f"金鑰出現在 log 裡：{leaked}"


# ══════════════════════════════════════════════════════════════════════
# M7 · 距離是純函式
# ══════════════════════════════════════════════════════════════════════

def test_m7_haversine_is_a_pure_function():
    """M7：兩個座標進、公里出。**不碰網路、不碰 DB。**

    `TAIPEI`（信義區一帶）↔ `TAOYUAN`（桃園市區）直線 **約 27 km**。

    ## 🔴 第一版我把容忍範圍寫成 29–35，而那是**行車距離**（B 抓到）

    ☠️ **而這一題的 docstring 自己就寫著「這是直線距離不是行車距離」** ——
    我一邊提醒別人不要搞混，一邊拿行車距離當這一題的基準。

    我自己用兩個獨立公式複驗過 B 的數字（沒有照抄他的）：

    | 算法 | 結果 |
    |---|---|
    | haversine | **27.00 km** |
    | 球面餘弦（完全獨立的公式）| **27.00 km** |
    | 對照：赤道一度經度 | 111.20 km（已知 111.32，差在地球半徑取值）|

    📌 **而座標本身也不是我以為的東西**：我寫「台北車站↔桃園車站」，
    但 `TAIPEI` 比較接近市政府／信義區，**而真正的車站對車站是 21.48 km**。
    ⇒ 描述改成「信義區↔桃園市區」，免得下一個人照著「車站」去查，
    **查到 21.5 又把這個範圍推翻一次。**

    ⚠️ **這是直線距離不是行車距離**，畫面上也要寫（M11）。
    """
    haversine_km = _geo("haversine_km")
    d = haversine_km(TAIPEI, TAOYUAN)
    assert 25 <= d <= 29, (
        f"信義區→桃園市區的直線距離算成 {d} km，應約 27 km。\n"
        "⚠️ 若你拿到的是 30 以上，先確認那不是行車距離 —— "
        "這一題的第一版就是那樣寫錯的。"
    )


def test_m7b_haversine_is_symmetric_and_zero_on_itself():
    """對照組：**同一點是 0、兩個方向一樣**。

    ⚠️ 沒有這一題，一個「永遠回 32」的實作會讓 M7 全綠。
    🔑 先證明量尺有刻度，再拿它去量。
    """
    haversine_km = _geo("haversine_km")
    assert haversine_km(TAIPEI, TAIPEI) == pytest.approx(0, abs=0.01)
    assert haversine_km(TAIPEI, TAOYUAN) == pytest.approx(
        haversine_km(TAOYUAN, TAIPEI), abs=0.01)


# ══════════════════════════════════════════════════════════════════════
# M9 · 總開關（比照 radar_on 的形狀）
# ══════════════════════════════════════════════════════════════════════

def test_m9_geo_ships_off_by_default(monkeypatch):
    """🔴 M9：**出貨預設關**（它會對外連線 OSM／Nominatim）。

    ⚠️ 比照 `radar_on()`：**字面值留著、環境變數放在讀的那一端**。
    反過來（環境變數放初始值）會讓這道守門從「永遠綠除非改原始碼」
    變成「**取決於周圍環境**」—— 有人 `export` 之後跑全回歸就紅，而那不是缺陷。
    """
    monkeypatch.delenv("MOTRIX_GEO", raising=False)
    monkeypatch.setattr(_geo(), "GEO_ENABLED", False)
    assert _geo("geo_on")() is False, "沒有環境變數時，地理查詢必須是關的"


def test_m9b_geo_opens_with_the_env_var(monkeypatch):
    """對照組：`MOTRIX_GEO=1` 要真的打開，否則實測機怎麼設都開不起來。"""
    monkeypatch.setattr(_geo(), "GEO_ENABLED", False)
    monkeypatch.setenv("MOTRIX_GEO", "1")
    assert _geo("geo_on")() is True


@pytest.mark.parametrize("value", ["0", "", "false", "true", "yes", "1 "])
def test_m9c_only_the_exact_value_opens_it(monkeypatch, value):
    """🔴 **`MOTRIX_GEO=0` 不可以打開它。**

    寫成 `if os.getenv("MOTRIX_GEO"):` 的話，**`"0"` 是非空字串 ⇒ 為真** ——
    「我明確設成 0」會把它**打開**。而錯的方向是**往會真的連出去的那一邊**。
    """
    monkeypatch.setattr(_geo(), "GEO_ENABLED", False)
    monkeypatch.setenv("MOTRIX_GEO", value)
    assert _geo("geo_on")() is False, (
        f"MOTRIX_GEO={value!r} 把地理查詢打開了 —— 判定要用 `== \"1\"`"
    )


# ══════════════════════════════════════════════════════════════════════
# M8 · 對外連線四道護欄（比照標案雷達）
# ══════════════════════════════════════════════════════════════════════

def test_m8_outbound_guardrails_exist():
    """M8：User-Agent、超時、間隔 —— 三個常數要在，而且值要合理。

    🔑 Nominatim 的使用政策明文要求可識別的 User-Agent 與請求間隔。
    ⚠️ 這不只是禮貌：**被對方封鎖時，症狀是「地圖上沒有點」**，
    而那跟 M6（標案沒有地點）、M13（沒有金鑰）在畫面上是同一個樣子。
    """
    ua = _geo("USER_AGENT")
    assert ua and "MOTRIX" in ua.upper(), (
        f"User-Agent 是 {ua!r} —— Nominatim 政策要求可識別的來源，"
        "被封鎖時的症狀是「地圖上沒有點」，跟另外兩個成因長得一樣"
    )
    timeout = _geo("FETCH_TIMEOUT_SECONDS")
    assert 0 < timeout <= 30, f"超時 {timeout} 秒不合理"
    interval = _geo("GEOCODE_INTERVAL_SECONDS")
    assert interval >= 1, (
        f"兩次 geocode 間隔 {interval} 秒 —— Nominatim 政策是每秒最多一次"
    )


def test_m8b_geocode_goes_through_the_module_attribute():
    """`geocode` 必須是**模組屬性**，這樣 monkeypatch 打得到。

    ⚠️ 呼叫端若寫成 `from geo import geocode`，**拿到的是副本**，
    測試 patch 模組屬性完全沒有作用 ⇒ **所有 geocode 相關的題目都會安靜地失效**。
    🔑 這是今天第八次遇到同一件事（`fetch_raw`／`time.sleep`／`_PUBKEY_DEV`…）。
    """
    assert callable(_geo("geocode"))


# ══════════════════════════════════════════════════════════════════════
# M3～M6 · 地圖端點
# ══════════════════════════════════════════════════════════════════════

def _map(client, hdr):
    r = client.get(MAP_PATH, headers=hdr)
    assert r.status_code == 200, f"{MAP_PATH} 回 {r.status_code}：{r.text[:300]}"
    body = r.json()
    missing = [k for k in MAP_KEYS if k not in body]
    assert not missing, f"地圖端點少了這些鍵：{missing}（實際 {sorted(body)}）"
    return body


def test_m3_empty_office_address_is_reported_not_silently_skipped(client, make_user):
    """🔴 M3：辦公室地址是空的 → **明白說出來**，不可以安靜地不顯示距離。

    ⚠️ 靜默的話，使用者看到的是「距離欄位都空著」——
    他會以為**功能壞了**，而不是**他還沒填地址**。
    🔑 兩者的下一步完全不同：一個是報修，一個是去設定頁填一行字。
    """
    _seed_legacy_profile()          # 七欄，沒有 address
    hdr = _auth(client, make_user)
    body = _map(client, hdr)
    assert body["officeMissing"] is True, (
        "辦公室地址是空的，而地圖端點沒有說 —— 使用者會以為功能壞了"
    )


def test_m6_tenders_without_location_are_counted_not_dropped(client, make_user):
    """🔴🔴 M6：`location` 是 NULL 的標案 —— **不在地圖上，但要被數出來**。

    ☠️ **地圖上少幾個點，看起來跟「那些標案不存在」一模一樣，而且沒有人會報修。**
    這是〈降級之後它還是會動〉：功能正常、畫面正常、**而資訊少了一塊**。

    ⚠️ 而它跟 M13（沒有金鑰）**在畫面上是同一個樣子，處置卻相反** ——
    所以**兩邊都必須有各自的訊號**，不能靠使用者看圖分辨。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location) VALUES (?,?,?,?)",
            ("GEO-001", "有地點的標案", "桃園市政府", "桃園市"))
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location) VALUES (?,?,?,NULL)",
            ("GEO-002", "沒有地點的標案", "某某機關"))
        conn.commit()
    finally:
        conn.close()

    hdr = _auth(client, make_user)
    body = _map(client, hdr)
    assert body["withoutLocation"] >= 1, (
        "有標案的 location 是 NULL，而地圖端點回報「沒有地點的有 0 筆」—— "
        "那些標案會從畫面上消失，而消失跟「不存在」長得一模一樣"
    )
    on_map = {p.get("caseNo") for p in body["points"]}
    assert "GEO-002" not in on_map, "沒有地點的標案不該出現在地圖上"


def test_m13_google_block_is_absent_when_the_key_is_empty(client, make_user):
    """🔴🔴 M13：金鑰是空的 → 那一塊**明白地不存在**，不是按了會壞的按鈕。

    🔑 判準照 B 那句：**403 會說「這裡有東西，只是你不能用」，404 什麼都不說。**

    ⚠️ 兩種錯法都要擋，而**第二種更安靜**：
    ① 載入 Google 腳本但金鑰是空字串 ⇒ 地圖蓋灰色浮水印（**壞掉的樣子**）
    ② 金鑰空 ⇒ 回空結果 ⇒ **一張乾淨、看起來完全正常、一個點都沒有的地圖**

    ☠️ ② 跟 M6 在畫面上完全一樣，**而兩者的處置相反**。
    ⇒ 所以要擋在更前面：**沒有金鑰時整塊不渲染**，
    就是 B 在 `reset-today` 用的那個作法 —— **不存在，不是存在但不能用。**
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    body = _map(client, hdr)
    assert body["googleMapsConfigured"] is False, (
        "沒有填金鑰，而端點說 Google 那一塊是設定好的 —— "
        "前端會渲染一塊「看起來正常、其實永遠是空的」的區域"
    )


def test_m13b_google_block_is_present_once_a_key_is_set(client, make_user):
    """M13 的對照組：**填了金鑰就要真的長出來**。

    ⚠️ 沒有這一題，一個「永遠回 False」的實作會讓 M13 全綠 ——
    而使用者填了金鑰之後那一塊**永遠不會出現**，他也不知道為什麼。
    """
    _seed_legacy_profile()
    hdr = _auth(client, make_user)
    client.put("/api/settings/company-profile", headers=hdr,
               json={KEY_SETTING: "AIzaSyD-FAKE"})
    body = _map(client, hdr)
    assert body["googleMapsConfigured"] is True, (
        "填了金鑰，那一塊還是不出現"
    )


# ══════════════════════════════════════════════════════════════════════
# M4／M5 · 快取與部分失敗
# ══════════════════════════════════════════════════════════════════════

def _geocode_spy(monkeypatch, results=None):
    """把 `geo.geocode` 換成計數器。⚠️ 觀測點是**呼叫次數**（M4 明文）。"""
    calls = []

    def _rec(address, *a, **kw):
        calls.append(address)
        if results is not None and address in results:
            return results[address]
        return ((24.9937, 121.3010), None)

    monkeypatch.setattr(_geo(), "geocode", _rec)
    return calls


def test_m4_geocode_result_is_cached(client, make_user, monkeypatch):
    """🔴 M4：同一個地址**第二次不再發出請求**。

    🔑 這既是 Nominatim 使用政策的要求，也跟 D1／D6 同一族：
    **把 N 綁在「你真的需要的那幾筆」上。**
    ⚠️ 觀測點是**呼叫次數**，不是「有沒有拿到座標」——
    後者在「每次都重新查」時也成立。
    """
    _set_setting("company_profile",
                 {**LEGACY_PROFILE, "address": "台中市西屯區文心路二段201號"})
    calls = _geocode_spy(monkeypatch)
    hdr = _auth(client, make_user)
    _map(client, hdr)
    first = len(calls)
    assert first >= 1, "第一次就沒有查 —— 這題的前提不成立"
    _map(client, hdr)
    assert len(calls) == first, (
        f"第二次又查了 {len(calls) - first} 次 —— 結果沒有存下來。"
        "每開一次畫面就打一次 Nominatim，會被對方封鎖，"
        "而被封鎖的症狀是「地圖上沒有點」"
    )


def test_m5_one_failure_does_not_empty_the_whole_map(client, make_user, monkeypatch):
    """🔴 M5：**一筆 geocode 失敗 → 其他筆照常顯示。**

    ⚠️ 一筆失敗讓整張地圖空白的話，症狀又是「一張乾淨的空地圖」——
    **今天第三個會長成那個樣子的成因。**
    """
    import db
    conn = db.get_db()
    try:
        for case_no, place in (("GEO-A", "桃園市"), ("GEO-B", "台北市"),
                               ("GEO-C", "台中市")):
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, location) VALUES (?,?,?,?)",
                (case_no, f"{place}的標案", "某機關", place))
        conn.commit()
    finally:
        conn.close()
    _set_setting("company_profile",
                 {**LEGACY_PROFILE, "address": "台中市西屯區文心路二段201號"})

    def _rec(address, *a, **kw):
        if "台北" in address:
            return (None, "HTTPError: 503")
        return ((24.9937, 121.3010), None)

    monkeypatch.setattr(_geo(), "geocode", _rec)
    hdr = _auth(client, make_user)
    body = _map(client, hdr)
    assert len(body["points"]) >= 2, (
        f"一筆失敗就只剩 {len(body['points'])} 個點 —— "
        "其他筆不該被一筆失敗拖下水"
    )
