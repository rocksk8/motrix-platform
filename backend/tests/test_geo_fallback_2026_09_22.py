"""§3o · 地址轉座標：**三個來源都保留，有序退階**。

## 🔴 起因：A 實測證明不是地址寫錯，是圖資查不到

```
台中市梧棲區八德路一段66號12樓之11   FAIL
台中市梧棲區八德路一段66號           FAIL
台中市梧棲區八德路一段               FAIL
台中市梧棲區                        ✅ (24.2549239, 120.5316259)
```
⇒ **Nominatim 認得行政區，認不得台灣的路名與門牌。**
🔴 而現行缺陷是：**查得到「梧棲區」卻整個回報「定位不到」，連退階都沒做。**

## ☠️ 核心：**座標一定要帶著它的精度與來源一起回來**

「門牌精度」與「行政區精度」**在畫面上都是一個圖釘**，而距離可能差好幾公里。

> 🔑 **一個數字不帶它的可信度，就會被當成事實。**

⇒ 所以回傳是一個**具名結構**，不是 tuple：
**tuple 可以被 `coord, *_ = locate(...)` 拆掉，而具名結構逼呼叫端講出它要的是哪一個。**
（同一個理由今晚已經用過一次：`fetch_detail` 的第二個回傳值一值兩用。）

## 📌 我釘的名字（§3o 沒有全部指定，B 要改先講）

| 名字 | 形狀 |
|---|---|
| `geo.locate(address, manual_coord=None)` | 回 `GeoResult` |
| `geo.GeoResult` | 具名結構，欄位 `coord` / `precision` / `source` / `error` |
| `geo.PRECISION_*` | `exact` / `rooftop` / `street` / `district` |
| `geo.SOURCE_*` | `manual` / `google` / `tgos` / `nominatim` / `nominatim_district` |
| `geo._locate_google` / `_locate_tgos` / `_locate_nominatim` | 各階的接縫（**模組層，patch 得到**）|
| `geo.district_of(address)` | 從完整地址取出「縣市＋區」（A4）|
| 設定鍵 `tgos_app_id` | A7 |

⚠️ 每一階都要是**模組層屬性** —— 否則 A3 的「讓前 N 階失敗」做不到，
而那一題會變成「只驗最後有沒有座標」，**那正是 A 明文說不要的那種**。

## ⚠️ TGOS 那一階：**條款尚未查證**（A 在規格裡自己標的）

「免費、註冊拿 AppID」是 A 的**印象**，不是查過的。
⇒ 本檔只釘 **A7（沒有 AppID 就不發請求）**，那一題**不管條款怎麼寫都成立**。
📌 **不釘「TGOS 查得到什麼」** —— 那要等條款讀完。
🔑 **「我記得它是免費的」跟「我查過它是免費的」在單子上長得一樣。**
"""
import pytest

from helpers.settings import _set_setting

try:
    from helpers import geo
except Exception as exc:  # noqa: BLE001
    geo = None
    _GEO_ERR = repr(exc)

FULL_ADDRESS = "台中市梧棲區八德路一段66號12樓之11"
DISTRICT = "台中市梧棲區"
DISTRICT_COORD = (24.2549239, 120.5316259)
ROOFTOP_COORD = (24.2551000, 120.5320000)
MANUAL_COORD = (24.1477, 120.6736)

GOOGLE_KEY_SETTING = "google_maps_api_key"
TGOS_APPID_SETTING = "tgos_app_id"


def _geo(name=None):
    if geo is None:
        raise AssertionError(f"helpers/geo.py import 失敗：{_GEO_ERR}")
    if name and not hasattr(geo, name):
        raise AssertionError(
            f"helpers/geo.py 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉")
    return getattr(geo, name) if name else geo


def _stages(monkeypatch, google=None, tgos=None, nominatim=None):
    """把三個外部階段換成固定結果。`None` ＝ 那一階查不到。

    ⚠️ 換的是**各階的函式**，不是 `locate` —— 換 `locate` 會把
    **退階邏輯本身**一起換掉，而退階邏輯正是這一批要驗的東西。
    （今晚那一族：觀測手段與被測對象共用一段程式碼。）
    """
    for attr, value in (("_locate_google", google),
                        ("_locate_tgos", tgos),
                        ("_locate_nominatim", nominatim)):
        _geo(attr)
        monkeypatch.setattr(_geo(), attr, lambda addr, _v=value, **kw: _v)


def _enable(monkeypatch):
    monkeypatch.setattr(_geo(), "GEO_ENABLED", True)


def _no_outbound(monkeypatch):
    """記錄有沒有真的發出請求。**A6／A7 的觀測點是這個，不是回傳值。**"""
    attempts = []

    def _rec(req, *a, **kw):
        attempts.append(req if isinstance(req, str)
                        else getattr(req, "full_url", repr(req)))
        raise OSError("測試不對外連線")

    monkeypatch.setattr(_geo().urllib.request, "urlopen", _rec)
    return attempts


# ══════════════════════════════════════════════════════════════════════
# A1 · 拿得到座標就一定拿得到精度與來源
# ══════════════════════════════════════════════════════════════════════

def test_a1_a_located_address_always_carries_precision_and_source(monkeypatch):
    """🔴 A1：**拿得到座標，就一定拿得到 `precision` 與 `source`。**

    ☠️ 「門牌精度」與「行政區精度」在畫面上都是一個圖釘，而距離可能差好幾公里。
    🔑 **一個數字不帶它的可信度，就會被當成事實。**
    """
    _enable(monkeypatch)
    _stages(monkeypatch, nominatim=(DISTRICT_COORD, _geo("PRECISION_STREET")))
    result = _geo("locate")(FULL_ADDRESS)

    assert result.coord, f"查得到卻沒有座標：{result}"
    assert result.precision, (
        f"有座標而 `precision` 是 {result.precision!r} —— "
        "那個圖釘會被當成門牌精度"
    )
    assert result.source, (
        f"有座標而 `source` 是 {result.source!r} —— "
        "查不出這個點是誰給的，就沒有辦法判斷它可不可信"
    )


def test_a1b_the_result_is_a_named_structure_not_a_bare_tuple(monkeypatch):
    """A1 的形狀：**回傳要是具名結構，不是裸 tuple。**

    ⚠️ 裸 tuple 可以被 `coord, *_ = locate(...)` 拆掉 ——
    **而那正是「只拿座標、不管精度」的最短寫法。**
    🔑 **具名結構逼呼叫端講出它要的是哪一個。**
    📌 同一個理由今晚用過一次：`fetch_detail` 的第二個回傳值一值兩用，
    而 docstring 說「其中一個必為 None」—— 那是 tuple 允許的那種錯。
    """
    _enable(monkeypatch)
    _stages(monkeypatch, nominatim=(DISTRICT_COORD, _geo("PRECISION_STREET")))
    result = _geo("locate")(FULL_ADDRESS)
    for field in ("coord", "precision", "source", "error"):
        assert hasattr(result, field), (
            f"回傳沒有 `.{field}` —— 它是裸 tuple 嗎？{result!r}"
        )


# ══════════════════════════════════════════════════════════════════════
# A2／A10 · 手動座標
# ══════════════════════════════════════════════════════════════════════

def test_a2_manual_coordinates_skip_every_lookup(monkeypatch):
    """🔴 A2：**填了手動座標就完全不對外查詢。**

    省錢，也精準 —— 使用者自己填的那一個一定比任何服務猜的準。
    ⚠️ 觀測點是「**有沒有發出請求**」，不是「回傳的座標對不對」：
    一個「先查一次再用手動座標蓋掉」的實作**回傳完全正確**，
    **而它每次都在花錢、而且慢。**
    """
    _enable(monkeypatch)
    attempts = _no_outbound(monkeypatch)
    called = []
    for attr in ("_locate_google", "_locate_tgos", "_locate_nominatim"):
        _geo(attr)
        monkeypatch.setattr(_geo(), attr,
                            lambda addr, _a=attr, **kw: called.append(_a))

    result = _geo("locate")(FULL_ADDRESS, manual_coord=MANUAL_COORD)
    assert result.coord == MANUAL_COORD, f"沒有用手動座標：{result}"
    assert result.precision == _geo("PRECISION_EXACT"), (
        f"手動座標的精度應為 exact，實際 {result.precision!r}"
    )
    assert result.source == _geo("SOURCE_MANUAL"), (
        f"來源應為 manual，實際 {result.source!r}"
    )
    assert not called, f"填了手動座標還去查了這幾階：{called}"
    assert not attempts, f"填了手動座標還對外連線了：{attempts}"


@pytest.mark.parametrize("bad", [
    (91.0, 120.0), (-91.0, 120.0), (24.0, 181.0), (24.0, -181.0),
])
def test_a10_out_of_range_manual_coordinates_are_rejected(
        client, make_user, bad):
    """🔴 A10：手動座標超出範圍 ⇒ **422，而且不可以存進去。**

    ⚠️ 斷言**兩件事**：回 422，**而且設定真的沒被改**。
    🔑 「回了錯誤碼」與「沒有存進去」是兩件事 ——
    今晚已經踩過一次同樣的形狀（SL25 的「回了 409 但其實存進去了」）。
    """
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    hdr = {"Authorization": "Bearer " + r.json()["token"]}

    _set_setting("company_profile", {"name": "測試", "address": DISTRICT})
    lat, lon = bad
    r = client.put("/api/settings/company-profile", headers=hdr,
                   json={"office_lat": lat, "office_lon": lon})
    assert r.status_code == 422, (
        f"座標 ({lat}, {lon}) 超出範圍，應該 422，實際 {r.status_code}：{r.text[:200]}"
    )
    from helpers.settings import _get_setting
    stored = _get_setting("company_profile", {}) or {}
    assert stored.get("office_lat") != lat, (
        f"回了 422 而座標已經存進去了：{stored.get('office_lat')!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# A3／A5 · 退階順序
# ══════════════════════════════════════════════════════════════════════

def test_a3_google_wins_when_it_answers(monkeypatch):
    """🔴 A3 第一階：Google 查得到 ⇒ **不再往下走**。"""
    _enable(monkeypatch)
    _set_setting(GOOGLE_KEY_SETTING, "AIza-fake")
    lower = []
    _stages(monkeypatch, google=(ROOFTOP_COORD, _geo("PRECISION_ROOFTOP")))
    for attr in ("_locate_tgos", "_locate_nominatim"):
        monkeypatch.setattr(_geo(), attr,
                            lambda addr, _a=attr, **kw: lower.append(_a))

    result = _geo("locate")(FULL_ADDRESS)
    assert result.source == _geo("SOURCE_GOOGLE"), f"來源不是 google：{result}"
    assert not lower, f"Google 已經查到了，還往下走了：{lower}"


def test_a3b_falls_through_to_nominatim_when_the_upper_stages_fail(monkeypatch):
    """🔴 A3 第二階：Google 與 TGOS 都查不到 ⇒ **走到 Nominatim**。

    ⚠️ 這一題**不是只驗「最後有座標」**（A 明文說不要那種）——
    它驗的是 `source` **真的是 nominatim**，也就是**它真的走過那條路**。
    """
    _enable(monkeypatch)
    _stages(monkeypatch, google=None, tgos=None,
            nominatim=(DISTRICT_COORD, _geo("PRECISION_STREET")))
    result = _geo("locate")(FULL_ADDRESS)
    assert result.coord, f"三階都設好了卻沒有座標：{result}"
    assert result.source == _geo("SOURCE_NOMINATIM"), (
        f"前兩階都查不到，應該走到 nominatim，實際 {result.source!r}"
    )


def test_a5_precision_changes_with_the_stage_actually_reached(monkeypatch):
    """🔴🔴 A5 反向控制：**`precision` 要真的隨走到的那一階改變。**

    ⚠️ 沒有這一題，一個**永遠回 `street`** 的實作會讓 A1／A3 全綠 ——
    **而使用者會把一個行政區中心點當成門牌位置。**
    🔑 「有這個欄位」與「這個欄位是對的」是兩件事（今晚第三次）。
    """
    _enable(monkeypatch)
    _set_setting(GOOGLE_KEY_SETTING, "AIza-fake")

    _stages(monkeypatch, google=(ROOFTOP_COORD, _geo("PRECISION_ROOFTOP")))
    top = _geo("locate")(FULL_ADDRESS)

    _stages(monkeypatch, google=None, tgos=None,
            nominatim=(DISTRICT_COORD, _geo("PRECISION_DISTRICT")))
    bottom = _geo("locate")(FULL_ADDRESS)

    assert top.precision != bottom.precision, (
        f"走到不同階而精度一樣（都是 {top.precision!r}）—— "
        "那個欄位是寫死的，而使用者會把行政區中心點當成門牌位置"
    )
    assert top.precision == _geo("PRECISION_ROOFTOP")
    assert bottom.precision == _geo("PRECISION_DISTRICT")


# ══════════════════════════════════════════════════════════════════════
# A4 · 行政區退階
# ══════════════════════════════════════════════════════════════════════

def test_a4_falls_back_to_the_district_when_the_full_address_fails(monkeypatch):
    """🔴🔴 A4：完整地址查不到 ⇒ **自動只取「縣市＋區」再查一次**。

    這就是起因那件事：**查得到「梧棲區」，而現行實作整個回報失敗。**
    ⇒ 拿到一個「差幾公里但有用」的點，比拿到「定位不到」有用得多 ——
    ⚠️ **前提是畫面上講清楚它只到行政區**（V1／V2，目視驗收）。
    """
    _enable(monkeypatch)
    asked = []

    def _nominatim(address, **kw):
        asked.append(address)
        if address == DISTRICT:
            return (DISTRICT_COORD, _geo("PRECISION_DISTRICT"))
        return None

    _geo("_locate_nominatim")
    monkeypatch.setattr(_geo(), "_locate_nominatim", _nominatim)
    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)

    result = _geo("locate")(FULL_ADDRESS)
    assert len(asked) >= 2, (
        f"完整地址查不到，而它只問了 {asked} —— **沒有做行政區退階**。\n"
        "⇒ 使用者會看到「定位不到」，而系統其實查得到那個區。"
    )
    assert DISTRICT in asked, f"退階查的不是「縣市＋區」：{asked}"
    assert result.coord == DISTRICT_COORD, f"沒有用退階的結果：{result}"
    assert result.precision == _geo("PRECISION_DISTRICT"), (
        f"退階到行政區，精度卻是 {result.precision!r} —— "
        "那會讓使用者以為這是門牌位置"
    )


def test_a4b_the_district_extractor_handles_the_real_address(monkeypatch):
    """A4 的前提：`district_of()` 真的從那個地址切得出「縣市＋區」。

    ⚠️ 沒有這一題，A4 可能因為**切不出來**而永遠走不到退階，
    而 A4 的訊息會說「沒有做行政區退階」—— **指向錯的地方。**
    """
    assert _geo("district_of")(FULL_ADDRESS) == DISTRICT, (
        f"從 {FULL_ADDRESS!r} 切不出 {DISTRICT!r}，"
        f"實際 {_geo('district_of')(FULL_ADDRESS)!r}"
    )


def test_a4c_an_address_with_no_district_does_not_loop(monkeypatch):
    """對照組：切不出行政區時**不可以拿原地址再查一次**。

    ⚠️ 一個 `district_of()` 回原字串的實作會讓 A4 綠，
    **而它等於對每一個查不到的地址都打兩次** —— 那是被封鎖的那一類行為。
    """
    _enable(monkeypatch)
    asked = []

    def _nominatim(address, **kw):
        asked.append(address)
        return None

    monkeypatch.setattr(_geo(), "_locate_nominatim", _nominatim)
    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)

    result = _geo("locate")("沒有行政區的一串字")
    assert result.coord is None, f"查不到卻給了座標：{result}"
    assert len(asked) <= 1, (
        f"切不出行政區，卻查了 {asked} —— 同一個地址被打了兩次"
    )


# ══════════════════════════════════════════════════════════════════════
# A6／A7／A8 · 沒有憑證就不發請求
# ══════════════════════════════════════════════════════════════════════

def test_a6_no_google_key_means_no_google_request(monkeypatch):
    """🔴 A6：沒有 Google 金鑰 ⇒ **根本不發請求**（不是「發了失敗」）。

    ⚠️ 觀測點是「**有沒有發出去**」，不是回傳值 ——
    一個「照打、拿 403、再往下走」的實作**回傳完全正確**，
    **而它每一次都在對 Google 發一個註定失敗的請求。**
    """
    _enable(monkeypatch)
    _set_setting(GOOGLE_KEY_SETTING, "")
    attempts = _no_outbound(monkeypatch)
    _geo("_locate_google")(FULL_ADDRESS)
    google_calls = [u for u in attempts if "google" in u.lower()]
    assert not google_calls, (
        f"沒有金鑰卻還是打了 Google：{google_calls}"
    )


def test_a7_no_tgos_appid_means_no_tgos_request(monkeypatch):
    """🔴 A7：沒有 TGOS AppID ⇒ 同上。

    📌 **這一題不管 TGOS 的條款怎麼寫都成立** ——
    A 在規格裡自己標了「免費／註冊拿 AppID」是印象不是查證。
    ⇒ 本檔只釘這一題，**不釘「TGOS 查得到什麼」**。
    🔑 **「我記得它是免費的」跟「我查過它是免費的」在單子上長得一樣。**
    """
    _enable(monkeypatch)
    _set_setting(TGOS_APPID_SETTING, "")
    attempts = _no_outbound(monkeypatch)
    _geo("_locate_tgos")(FULL_ADDRESS)
    tgos_calls = [u for u in attempts if "tgos" in u.lower()]
    assert not tgos_calls, f"沒有 AppID 卻還是打了 TGOS：{tgos_calls}"


def test_a8_the_master_switch_stops_every_stage(monkeypatch):
    """🔴 A8：`geo_on()` 關著時**一階都不走**。

    ⚠️ 而它要擋的是**所有**外部來源，不只 Nominatim ——
    一個只在 Nominatim 那一階檢查開關的實作，會讓
    **出貨預設關的機器照樣打 Google**（而那是使用者在付錢）。
    """
    monkeypatch.setattr(_geo(), "GEO_ENABLED", False)
    monkeypatch.delenv("MOTRIX_GEO", raising=False)
    assert _geo("geo_on")() is False, "前提不成立"

    _set_setting(GOOGLE_KEY_SETTING, "AIza-fake")
    _set_setting(TGOS_APPID_SETTING, "tgos-fake")
    attempts = _no_outbound(monkeypatch)
    called = []
    for attr in ("_locate_google", "_locate_tgos", "_locate_nominatim"):
        _geo(attr)
        monkeypatch.setattr(_geo(), attr,
                            lambda addr, _a=attr, **kw: called.append(_a))

    result = _geo("locate")(FULL_ADDRESS)
    assert not called, f"總開關關著，卻走了這幾階：{called}"
    assert not attempts, f"總開關關著，卻對外連線了：{attempts}"
    assert result.coord is None, f"總開關關著卻給了座標：{result}"


# ══════════════════════════════════════════════════════════════════════
# A9 · 快取要含來源
# ══════════════════════════════════════════════════════════════════════

def test_a9_the_cache_is_keyed_by_source_too(monkeypatch):
    """🔴 A9：**同一個地址用不同來源查出不同座標，不可以互相覆蓋。**

    ⚠️ 只用地址當鍵的話：Nominatim 先查到行政區中心點並寫進快取
    ⇒ 使用者後來填了 Google 金鑰 ⇒ **快取命中，永遠拿不到門牌精度**。
    🔑 而症狀是**沒有症狀**：地圖上有點、距離有數字，只是一直差幾公里。
    """
    _enable(monkeypatch)
    cached = _geo("locate_cached")

    _stages(monkeypatch, google=None, tgos=None,
            nominatim=(DISTRICT_COORD, _geo("PRECISION_DISTRICT")))
    first = cached(FULL_ADDRESS)
    assert first.source == _geo("SOURCE_NOMINATIM"), f"前提不成立：{first}"

    _set_setting(GOOGLE_KEY_SETTING, "AIza-fake")
    _stages(monkeypatch, google=(ROOFTOP_COORD, _geo("PRECISION_ROOFTOP")))
    second = cached(FULL_ADDRESS)
    assert second.source == _geo("SOURCE_GOOGLE"), (
        f"填了 Google 金鑰之後仍然拿到 {second.source!r} 的舊結果 —— "
        "快取只用地址當鍵。\n"
        "⇒ 使用者付了錢買金鑰，而系統永遠回那個差幾公里的舊點，"
        "**而畫面上完全看不出來。**"
    )
    assert second.precision == _geo("PRECISION_ROOFTOP")


# ══════════════════════════════════════════════════════════════════════
# A11～A14 · 🔴 **快取要存進資料庫** —— 用量不是由使用者決定的
# ══════════════════════════════════════════════════════════════════════
#
# ## A 量給使用者看的數字
#
#     geo.py:118   _CACHE: dict = {}        ← 純記憶體，重啟就空
#     _TW_PLACES   26 個地點 ＋ 1 個辦公室   ⇒ 不重複的地址最多 27 個
#     autostart.bat 是無限迴圈，uvicorn 一退出就重拉
#
# 🔑 **⇒ 用量不是由使用者決定的，是由「重啟幾次」決定的。**
# 存進 DB ⇒ **一輩子 27 次**；不存 ⇒ **每次重啟 27 次**。
# 而 Google 那一階**是要收費的**。
#
# ## 📌 存哪裡：**新表 `geocode_cache`**（A 判斷，我同意）
#
# ⚠️ 塞進 `system_settings` 一筆 JSON 的話：
# **A12 的「兩筆都在」會變成字典裡的兩個鍵，而單筆失效就得讀寫整包。**
# ⇒ 新表才能依（地址, 來源）各自成列、單筆失效、將來能清。
# 🔴 **而那是一個 migration（v89）—— B 要動 `db.py`，請先宣告。**

GEOCODE_CACHE_TABLE = "geocode_cache"


def _cache_rows(address=None):
    import db
    conn = db.get_db()
    try:
        if address is None:
            sql = f"SELECT * FROM {GEOCODE_CACHE_TABLE}"
            return [dict(r) for r in conn.execute(sql).fetchall()]
        sql = f"SELECT * FROM {GEOCODE_CACHE_TABLE} WHERE address=?"
        return [dict(r) for r in conn.execute(sql, (address,)).fetchall()]
    finally:
        conn.close()


def _forget_memory(monkeypatch):
    """把**記憶體**那一層快取清掉，模擬「重啟之後的第一次查詢」。

    ⚠️ 這**不等於**真的重開一個行程 —— 我照實說。
    真的重開行程的話，測試用的暫存資料庫路徑要一起帶過去，
    那會讓這一題變成一個 harness 題而不是快取題。
    ⇒ 所以 A11 用**兩個觀測點**補足：
    **① 那一列真的在資料庫裡**（存得下去）
    **② 記憶體清空之後不再發請求**（讀得回來）
    🔑 兩個都成立，才排除得掉「其實只是記憶體還在」。
    """
    for attr in ("_CACHE", "_GEOCODE_CACHE", "_cache"):
        if hasattr(_geo(), attr) and isinstance(getattr(_geo(), attr), dict):
            monkeypatch.setattr(_geo(), attr, {})
            return attr
    raise AssertionError(
        "找不到記憶體那一層快取（試過 _CACHE／_GEOCODE_CACHE／_cache）—— "
        "名字改了的話這一題要跟著改"
    )


def test_a11_the_cache_survives_a_restart(client, monkeypatch):
    """🔴🔴 A11：**寫進快取之後，記憶體清空仍然命中，而且不再發請求。**

    ☠️ 現在的快取是純記憶體，而 `autostart.bat` 是無限迴圈 ——
    **uvicorn 一退出就重拉** ⇒ 快取每次都空 ⇒ **27 個地址重查一輪**。
    🔑 **用量不是由使用者決定的，是由「重啟幾次」決定的。**
    而 Google 那一階是要收費的。
    """
    _enable(monkeypatch)
    calls = []

    def _nominatim(address, **kw):
        calls.append(address)
        return (DISTRICT_COORD, _geo("PRECISION_DISTRICT"))

    monkeypatch.setattr(_geo(), "_locate_nominatim", _nominatim)
    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)

    first = _geo("locate_cached")(DISTRICT)
    assert first.coord == DISTRICT_COORD, f"第一次就沒查到：{first}"
    assert len(calls) == 1, f"第一次應該查一次，實際 {len(calls)}（前提不成立）"

    # ① 那一列真的在資料庫裡
    rows = _cache_rows(DISTRICT)
    assert rows, (
        f"`{GEOCODE_CACHE_TABLE}` 裡沒有 {DISTRICT!r} 這一列 —— 快取沒有落地。\n"
        "⇒ 重啟之後又要重查一輪，而 Google 那一階是要收費的。"
    )

    # ② 記憶體清空之後仍然命中，而且**不再發請求**
    _forget_memory(monkeypatch)
    second = _geo("locate_cached")(DISTRICT)
    assert second.coord == DISTRICT_COORD, f"從資料庫讀不回來：{second}"
    assert len(calls) == 1, (
        f"記憶體清空之後又查了一次（累計 {len(calls)} 次）—— "
        "資料庫那一層沒有被讀"
    )


def test_a12_two_sources_for_one_address_do_not_overwrite_each_other(
        client, monkeypatch):
    """🔴 A12：同一個地址用兩個來源各查一次 ⇒ **資料庫裡兩筆都在**。

    ⚠️ 這是 A9 的**落地版**：A9 驗的是「記憶體裡分得開」，
    這一題驗的是「**存進去之後還分得開**」。
    📌 而它同時說明了為什麼不用 `system_settings` 一筆 JSON：
    **那會變成字典裡的兩個鍵，而單筆失效就得讀寫整包。**
    """
    _enable(monkeypatch)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)

    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(
        _geo(), "_locate_nominatim",
        lambda addr, **kw: (DISTRICT_COORD, _geo("PRECISION_DISTRICT")))
    _geo("locate_cached")(DISTRICT)

    _set_setting(GOOGLE_KEY_SETTING, "AIza-fake")
    _forget_memory(monkeypatch)
    monkeypatch.setattr(
        _geo(), "_locate_google",
        lambda addr, **kw: (ROOFTOP_COORD, _geo("PRECISION_ROOFTOP")))
    _geo("locate_cached")(DISTRICT)

    rows = _cache_rows(DISTRICT)
    sources = {r.get("source") for r in rows}
    assert len(rows) >= 2, (
        f"同一地址查了兩個來源，而資料庫裡只有 {len(rows)} 列：{rows}\n"
        "⇒ 鍵裡沒有來源，後查的把先查的蓋掉了。"
    )
    assert {_geo("SOURCE_NOMINATIM"), _geo("SOURCE_GOOGLE")} <= sources, (
        f"兩個來源沒有各自成列，實際 source 有：{sources}"
    )


def test_a13_precision_and_source_survive_the_round_trip(client, monkeypatch):
    """🔴🔴 A13：從快取讀回來的 `precision` 與 `source` **必須跟寫進去時一樣**。

    ☠️ **這是這一組的核心。** 只存座標的話，
    **下次讀回來就不知道它是門牌還是行政區** —— 那等於把整個設計繞過去了：
    我們花了一整批題目讓座標帶著可信度一起回來，
    **而快取這一層把可信度丟掉了。**

    🔑 而症狀是**沒有症狀**：地圖上有點、距離有數字，
    只是那個「僅供參考」的標示不見了。
    """
    _enable(monkeypatch)
    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)
    monkeypatch.setattr(
        _geo(), "_locate_nominatim",
        lambda addr, **kw: (DISTRICT_COORD, _geo("PRECISION_DISTRICT")))

    written = _geo("locate_cached")(DISTRICT)
    assert written.precision == _geo("PRECISION_DISTRICT"), "前提不成立"

    _forget_memory(monkeypatch)
    read_back = _geo("locate_cached")(DISTRICT)
    assert read_back.precision == written.precision, (
        f"寫進去時是 {written.precision!r}，讀回來變成 {read_back.precision!r}。\n"
        "⇒ 快取只存了座標。那個點會被當成門牌精度，"
        "而它其實是行政區中心點，可能差好幾公里。"
    )
    assert read_back.source == written.source, (
        f"來源沒有存：寫入 {written.source!r}，讀回 {read_back.source!r}"
    )


def test_a14_failures_are_not_cached_forever(client, monkeypatch):
    """🔴 A14：**查不到不可以被永久快取。**

    ⚠️ 把「查不到」存成永久的話，**一個地址查失敗一次就永遠查不到** ——
    而使用者**改了地址也救不回來**（鍵是舊地址，新地址是另一筆，
    但如果他改回去、或那個服務後來修好了，那一筆仍然是失敗）。

    🔑 這一題的判準刻意寬：**要嘛不存，要嘛分開存並有自己的短 TTL。**
    ⇒ 只驗「**再查一次時它會真的再去問**」，不驗它怎麼實作。
    """
    _enable(monkeypatch)
    calls = []

    def _fail(address, **kw):
        calls.append(address)
        return None

    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_nominatim", _fail)

    first = _geo("locate_cached")("查不到的地址")
    assert first.coord is None, f"前提不成立：{first}"
    assert calls, "第一次就沒有去查（前提不成立）"

    _forget_memory(monkeypatch)
    monkeypatch.setattr(
        _geo(), "_locate_nominatim",
        lambda addr, **kw: (DISTRICT_COORD, _geo("PRECISION_DISTRICT")))
    second = _geo("locate_cached")("查不到的地址")
    assert second.coord == DISTRICT_COORD, (
        "上一次查不到被永久快取了 —— 那個服務後來修好了也沒有用。\n"
        "⇒ 失敗要嘛不存，要嘛分開存並有自己的短 TTL。"
    )


def test_a14b_a_successful_lookup_is_still_cached(client, monkeypatch):
    """A14 的對照組：**成功的那些仍然要被快取。**

    ⚠️ 沒有這一題，一個「乾脆都不存」的實作會讓 A14 全綠 ——
    而那會讓 A11 想解決的問題原封不動地回來。
    🔑 「失敗不留」與「成功要留」是兩件事。
    """
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(_geo(), "_locate_google", lambda addr, **kw: None)
    monkeypatch.setattr(_geo(), "_locate_tgos", lambda addr, **kw: None)
    monkeypatch.setattr(
        _geo(), "_locate_nominatim",
        lambda addr, **kw: (calls.append(addr),
                            (DISTRICT_COORD, _geo("PRECISION_DISTRICT")))[1])

    _geo("locate_cached")(DISTRICT)
    _forget_memory(monkeypatch)
    _geo("locate_cached")(DISTRICT)
    assert len(calls) == 1, (
        f"成功的結果沒有被快取（查了 {len(calls)} 次）—— "
        "那 A11 要解決的問題原封不動"
    )
