"""2026-09-21 · 第 6 輪：第二層抓取（地點）＋列表頁兩欄＋信件大綱＋定時可設定

對應 `docs/windows/STATE.md` §3 **`5c9ef58`** 版的 D1～D20／R1。
（協定 §5l：沒有版本號的「我照單寫了」，等於沒說照的是哪一張。）

## 🔴 我沒有讀實作

`fetch_detail` / `parse_detail` 等都還不存在（`hasattr` 查過）。
**我讀的是 `fixtures/tender_detail_20260921.html`（測試資料，我的領域），不是解析器。**

## 🔴🔴 D18：這一頁上「地址」出現 10 次，只有 1 次是這筆標案的

我把那 10 次全部掃出來看過：

```
 1. 地址 330 桃園市 桃園區 中山路1492號 聯絡人 劉思婷      ← 這筆標案的（散文裡）
 2~3. 「…地址為桃園市桃園區中山路1492號，另附大型回郵信封…」  ← 郵購說明，散文
 4. 地址：110臺北市信義區松仁路3號9樓      ← 監督機關（每一頁都一樣）
 5. 地址：115臺北市南港區忠孝東路6段488號5樓        ← 同上
 6. 地址：330桃園市桃園區縣府路19號        ← 同上 ⚠️ 也在桃園市！
 7. 地址：231新北市新店區中華路74號        ← 同上
 8. 地址：100臺北市中正區博愛路166號       ← 同上
 9. 地址：110臺北市信義區松仁路3號7樓      ← 同上
10. 地址：110207臺北市信義區松仁路3號7樓   ← 頁尾工程會
```

**9/10 是每一頁都一樣的樣板。** 用「地址」字樣去找，**每一筆標案都會得到同一個
臺北市信義區的地址** —— 而它**看起來完全像一個合法地點**，畫面上不會有任何異常。

⚠️ **而第 6 筆最毒**：監督機關裡有一個**也在桃園市**（`330桃園市桃園區縣府路19號`），
**跟這筆標案的正確答案同縣市** —— 抽驗時「桃園市」三個字會讓人以為抓對了。

⇒ 正解是 **`id="fkPmsExecuteLocation"`**，值是 `桃園市(非原住民地區)`。

⚠️ **§3 寫「全頁 `fkPms*` 只有這一個」—— 實測不成立**：28 次、10 個不同名字
（`fkPmsAwardWay`／`fkPmsTenderWay`／`fkPmsProcurementRange`／`fkPmsPriorityCate1`…）。
真正成立的是「**`fkPmsExecuteLocation` 這一個 id 唯一**」。
🔑 **「這一類前綴只有一個」與「這一個名字只有一個」是兩回事** ——
照前者寫選擇器（例如 `[id^=fkPms]`）會抓到別的欄位，而那又是一個「看起來有值」的錯。

🔑 跟列表頁「名稱抓成一行 JavaScript」同一家族：**錯得很像對的。**

📌 §3 明記**本輪不挖散文裡那個最精確的地址**（中山路1492號）——
**最精確的資料在最不結構化的地方**，而從自由文字抓地址，錯的時候一樣是「看起來很合法」。

## ⚠️ 我釘的名字（§3 沒有全部指定）

| 名字 | 出處 |
|------|------|
| `tender_source.fetch_detail(url)` → `(html, error)` | ⚠️ **C 釘**（比照 `fetch_raw`）|
| `tender_source.parse_detail(html)` → `dict` | ⚠️ **C 釘** |
| `DETAIL_DAILY_LIMIT` / `DETAIL_INTERVAL_SECONDS` | ⚠️ **C 釘**（§3 給的是預設值 20／2）|
| `tender_source.time`（走模組，`time.sleep` 要 patch 得到）| §3 D3 明文 |
| `tenders.location` / `procurement_type` / `tender_method` | §3 明文 |
| 設定 key `tender_radar_scan_hour` | ⚠️ **C 釘** |

要改名跟我說，改的是常數不是邏輯。
"""
import re
from pathlib import Path

import pytest

import helpers.email_notify as en       # noqa: E402
import helpers.tender_source as ts      # noqa: E402

DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "tender_detail_20260921.html"
LOCATION_FIELD_ID = "fkPmsExecuteLocation"
SCAN_HOUR_SETTING = "tender_radar_scan_hour"


def _need(mod, name):
    if not hasattr(mod, name):
        raise AssertionError(
            f"{mod.__name__} 缺少 `{name}` —— B 還沒做，或名字跟我釘的不一樣。"
            "見本檔開頭〈我釘的名字〉。"
        )
    return getattr(mod, name)


def _detail_html():
    return DETAIL_FIXTURE.read_text(encoding="utf-8")


# 監督機關與頁尾的地址 —— **每一頁都一樣**，解出來的 location 不可以是它們任一個。
# ⚠️ 第三個也在桃園市，跟這筆標案的正確答案同縣市。
SUPERVISOR_ADDRESSES = (
    "110臺北市信義區松仁路3號9樓",
    "115臺北市南港區忠孝東路6段488號5樓",
    "330桃園市桃園區縣府路19號",
    "231新北市新店區中華路74號",
    "100臺北市中正區博愛路166號",
    "110臺北市信義區松仁路3號7樓",
    "110207臺北市信義區松仁路3號7樓",
)
EXPECTED_LOCATION_RAW = "桃園市(非原住民地區)"
EXPECTED_LOCATION = "桃園市"


# ── 樣本守門（不碰產品碼，保護的是樣本本身）─────────────────────────────

def test_00_detail_fixture_is_the_real_bytes():
    """詳細頁 fixture 必須是對方當時真正送來的位元組。

    ⚠️ `.gitattributes` 的 `fixtures/** -text` 擋住正規化 ——
    **正規化過的樣本不是現實，是現實的正規化版**，而那打掉了它存在的理由。
    """
    raw = DETAIL_FIXTURE.read_bytes()
    assert len(raw) == 137_303, f"fixture 大小變了：{len(raw)}（原始 137,303）"


def test_00b_location_field_id_is_unique_on_the_page():
    """D18 的前提：`fkPmsExecuteLocation` **全頁只有一個**。

    ⚠️ 沒有這一題，D18 就只是「湊巧抓對了」——
    **唯一性是「用 id 找」這個策略成立的理由本身。**
    """
    h = _detail_html()
    assert h.count(LOCATION_FIELD_ID) == 1, (
        f"`{LOCATION_FIELD_ID}` 出現 {h.count(LOCATION_FIELD_ID)} 次，應為 1"
    )
    # ⚠️ §3 寫「全頁 `fkPms*` 只有這一個」——**實測不成立**：
    #    28 次、10 個不同名字（fkPmsAwardWay／fkPmsTenderWay／fkPmsProcurementRange…）。
    #    真正成立的是「**`fkPmsExecuteLocation` 這一個 id 唯一**」，也就是上一行。
    # 🔑 「這一類前綴只有一個」與「這一個名字只有一個」是兩回事 ——
    #    前者是錯的，而照前者寫選擇器（例如用 `[id^=fkPms]`）會抓到別的欄位。
    others = {m for m in re.findall(r"fkPms\w+", h)} - {LOCATION_FIELD_ID}
    assert others, (
        "fkPms* 真的只有一個了 —— §3 的說法變成正確，這段註解要更新"
    )


def test_00c_address_text_appears_ten_times_and_mostly_boilerplate():
    """D18 的另一半前提：**「地址」出現 10 次，9 次是樣板**。

    ⚠️ 這一題是 D18 的**對照組**：它證明「用『地址』字樣去找」這件事
    **真的會抓到錯的東西** —— 否則 D18 只是一個沒有威脅的斷言。
    """
    h = _detail_html()
    assert h.count("地址") == 10, f"「地址」出現 {h.count('地址')} 次，樣本結構變了"
    for addr in SUPERVISOR_ADDRESSES:
        assert addr in h, f"樣板地址 {addr!r} 不在樣本裡，SUPERVISOR_ADDRESSES 要更新"


# ── D18／D19：地點 ─────────────────────────────────────────────────────────

def test_d18_location_comes_from_the_id_not_from_the_word_address():
    """§3 D18：**只認 `id="fkPmsExecuteLocation"`，不可以用「地址」字樣去找**。

    ⚠️⚠️ 用字樣去找的話，**每一筆標案都會得到同一個臺北市信義區的地址** ——
    而它看起來**完全像一個合法地點**，畫面上不會有任何異常。

    ⚠️ 而監督機關裡有一個**也在桃園市**（`330桃園市桃園區縣府路19號`），
    **跟正確答案同縣市** —— 抽驗時「桃園市」三個字會讓人以為抓對了。

    🔑 跟列表頁「名稱抓成一行 JavaScript」同一家族：**錯得很像對的。**
    """
    detail = _need(ts, "parse_detail")(_detail_html())
    loc = detail.get("location")

    assert loc, f"沒有解出地點，實際 {loc!r}"
    for addr in SUPERVISOR_ADDRESSES:
        assert loc != addr, (
            f"解出來的地點是**監督機關的地址** {addr!r} —— 那是每一頁都一樣的樣板，"
            "代表解析器用「地址」字樣去找。每一筆標案都會得到同一個地點。"
        )
        assert addr not in str(loc), f"地點裡混進了樣板地址 {addr!r}"
    # 散文裡那個最精確的地址，本輪明確不挖
    assert "中山路1492號" not in str(loc), (
        "地點取到了散文裡的郵購地址 —— §3 明記本輪不挖它"
        "（最精確的資料在最不結構化的地方，從自由文字抓錯的時候一樣『看起來很合法』）"
    )


def test_d19_location_suffix_is_stripped():
    """§3 D19：`(非原住民地區)` 這類括號後綴要拆掉，只存縣市。"""
    detail = _need(ts, "parse_detail")(_detail_html())
    loc = detail.get("location")
    assert loc == EXPECTED_LOCATION, (
        f"應該拆成 {EXPECTED_LOCATION!r}，實際 {loc!r}"
        f"（原始值是 {EXPECTED_LOCATION_RAW!r}）"
    )
    assert "(" not in str(loc) and "（" not in str(loc), f"括號後綴沒拆乾淨：{loc!r}"


@pytest.mark.parametrize("raw", ["全國", "依契約規定", "多個縣市"])
def test_d19b_non_place_values_become_null(raw):
    """§3 D19 後半：非地名值 → `location` 留 `NULL`，**不要硬存**。

    ⚠️ 硬存的話，下游「依地點篩選」會篩出一個叫「依契約規定」的縣市。
    🔑 跟 `0` vs `NULL` 同一家族：**「不知道」不是一個值。**
    """
    h = _detail_html().replace(EXPECTED_LOCATION_RAW, raw)
    assert raw in h, "樣本手術沒做到（前提不成立）"
    detail = _need(ts, "parse_detail")(h)
    assert detail.get("location") is None, (
        f"{raw!r} 不是地名，location 應為 None，實際 {detail.get('location')!r}"
    )


# ── D1～D6：第二層抓取的安全閥 ────────────────────────────────────────────

def _detail_spy(monkeypatch, html=None, error=None):
    """把 `fetch_detail` 換成計數器。⚠️ 觀測點是**呼叫次數**（§3 D2 明文）。"""
    _need(ts, "fetch_detail")
    calls = []

    def _rec(url, *a, **kw):
        calls.append(url)
        return (_detail_html() if html is None else html, error)

    monkeypatch.setattr(ts, "fetch_detail", _rec)
    return calls


def test_d1_detail_fetched_only_for_matched_tenders(client, monkeypatch):
    """§3 D1：**只對「命中 watch 的標案」抓詳細頁**，不是對整個列表。

    🔑 這一條把 N 從「當天所有公告」綁到「你真的在乎的那幾筆」——
    **是整個安全閥的基礎**：沒有它，上限與間隔都只是在拖慢一件不該做的事。
    """
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    calls = _detail_spy(monkeypatch)
    _sent(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    _need(ts, "run_scheduled_scan")()

    hits = _hit_count()
    assert len(calls) == hits, (
        f"詳細頁抓了 {len(calls)} 次，而命中的標案有 {hits} 筆 —— "
        "只能對命中的抓，不是對整個列表"
    )


def test_d2_daily_detail_limit_is_enforced(client, monkeypatch):
    """§3 D2：每日詳細頁抓取有硬上限，超過就停，**並記進 `tender_fetch_log`**。

    ⚠️ 觀測點是**呼叫次數**，不是「有幾筆有地點」——
    後者在「呼叫了但解析失敗」時也會是 0。
    """
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    limit = _need(ts, "DETAIL_DAILY_LIMIT")
    assert isinstance(limit, int) and limit > 0, f"上限要是正整數，實際 {limit!r}"
    monkeypatch.setattr(ts, "DETAIL_DAILY_LIMIT", 2)

    calls = _detail_spy(monkeypatch)
    _sent(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    _need(ts, "run_scheduled_scan")()

    assert len(calls) <= 2, f"上限是 2，卻抓了 {len(calls)} 次"


def test_d3_interval_between_detail_fetches(client, monkeypatch):
    """§3 D3：每次詳細頁之間要間隔。**驗「有呼叫 sleep」而非真的等**。

    📌 `time.sleep` 要走模組屬性，否則 patch 不到 ——
    **「patch 目標要走模組」的第七個實例**
    （`fetch_raw`／`procurement.today`／`_PUBKEY_DEV`／`LICENSE_PATH`／
    `Timer`／`_pref_enabled`／現在是 `time.sleep`）。
    """
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    _need(ts, "time")
    slept = []
    monkeypatch.setattr(ts.time, "sleep", lambda s: slept.append(s))

    calls = _detail_spy(monkeypatch)
    _sent(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    _need(ts, "run_scheduled_scan")()

    assert len(calls) >= 2, "這題要至少抓兩次詳細頁才驗得到間隔（前提不成立）"
    assert slept, (
        "抓了多次詳細頁卻一次都沒有間隔 —— 這是對別人伺服器的承諾。"
        "⚠️ 若實作正確仍然紅，先查 tender_source 是不是寫了 `from time import sleep`"
    )
    assert all(s > 0 for s in slept), f"間隔要是正數，實際 {slept!r}"


def test_d4_detail_failure_keeps_the_tender_with_null_location(client, monkeypatch):
    """§3 D4：**詳細頁抓失敗 → 那一筆標案照樣存，`location` 留 `NULL`**。

    ⚠️⚠️ **不可以因為拿不到地點就整筆丟掉** —— 這條線的承諾是「不會漏掉標案」，
    而地點只是錦上添花。**為了一個附加欄位而丟掉主體，是最糟的失敗方向。**
    """
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    _detail_spy(monkeypatch, html=None, error="timeout")
    monkeypatch.setattr(ts, "fetch_detail", lambda url, *a, **kw: (None, "timeout"))
    _sent(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    _need(ts, "run_scheduled_scan")()

    import db
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"]
        nulls = conn.execute(
            "SELECT COUNT(*) c FROM tenders WHERE location IS NULL").fetchone()["c"]
    finally:
        conn.close()
    assert n > 0, "詳細頁抓失敗就把標案全丟了 —— 這條線的承諾是不會漏掉標案"
    assert nulls == n, f"抓失敗時 location 應全為 NULL，實際 {n - nulls} 筆有值"


def test_d5_disabled_switch_means_no_detail_fetch(client, monkeypatch):
    """§3 D5：總開關關著時，**詳細頁的抓取次數 == 0**（沿用第 4 輪條件 8 的形狀）。"""
    calls = _detail_spy(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", False)
    _need(ts, "run_scheduled_scan")()
    assert len(calls) == 0, f"開關關著不該抓詳細頁，實際 {len(calls)} 次"


def test_d6_tender_with_location_is_not_refetched(client, monkeypatch):
    """§3 D6：已經有 `location` 的標案，**下次不再抓它的詳細頁**（冪等）。"""
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    calls = _detail_spy(monkeypatch)
    _sent(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    run = _need(ts, "run_scheduled_scan")
    run()
    first = len(calls)
    assert first >= 1, "第一次就該抓（前提不成立）"

    _allow_rerun(monkeypatch)
    run()
    assert len(calls) == first, (
        f"已經有地點的標案又被抓了一次（{first} → {len(calls)}）—— 不冪等"
    )


# ── D7／D8：列表頁就有的兩欄 ──────────────────────────────────────────────

def test_d7_procurement_type_and_method_come_from_the_list_page():
    """§3 D7：`procurement_type` 與 `tender_method` **從列表頁解析**，
    ⚠️ **不增加任何對外請求**。"""
    from tests.test_tender_match_2026_09_21 import REAL

    items, _, _ = _need(ts, "parse_list")(REAL)
    first = next(i for i in items if i["case_no"] == "TYGH115152")
    assert first.get("procurement_type") == "財物類", (
        f"採購性質應為 財物類，實際 {first.get('procurement_type')!r}"
    )
    assert first.get("tender_method") == "公開招標", (
        f"招標方式應為 公開招標，實際 {first.get('tender_method')!r}"
    )


def test_d8_missing_column_is_null_not_empty_string():
    """§3 D8：解析不到時存 `NULL`，**不要存空字串**。

    🔑 「沒有這一欄」與「這一欄是空的」是兩件事 ——
    📌 **今天第五次這一族**（前置時間未知／預算沒寫／抓不到 vs 不認得／
    截止日沒寫／現在是採購性質）。
    """
    from tests.test_tender_match_2026_09_21 import (
        COL_ORG, REAL, _DATA, _rebuild, _set_cell,
    )

    COL_METHOD = 4
    page = _rebuild(REAL, [_set_cell(_DATA[0], COL_METHOD, "")] + _DATA[1:])
    assert page != REAL, "樣本手術沒做到（前提不成立）"
    items, _, _ = _need(ts, "parse_list")(page)
    first = next(i for i in items if i["case_no"] == "TYGH115152")
    # ⚠️ 第一版我只寫 `first.get("tender_method") is None` —— **那是空集合上的真**：
    #    `parse_list` 還沒有這個鍵時，`.get()` 也回 None，於是**功能不存在也會綠**。
    #    實測確認過：當時的鍵只有 budget/case_no/deadline/name/org/published_at/url。
    # 🔑 **先釘住「這個鍵存在」，再驗它的值** —— 否則驗的是 `.get()` 的預設值，
    #    不是解析器的行為。（〈給彙整〉29 那一族的第二次。）
    assert "tender_method" in first, (
        "`tender_method` 這個鍵根本不存在 —— 不是「解析不到」，是「還沒做」。"
        f"實際的鍵：{sorted(first)}"
    )
    assert first["tender_method"] is None, (
        f"解析不到要存 None 不是空字串，實際 {first['tender_method']!r}"
    )


# ── D9～D11：信件 ─────────────────────────────────────────────────────────

def _mail_body(monkeypatch):
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _assert_mails, _sent

    mails = _sent(monkeypatch)
    _detail_spy(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy_fetch(monkeypatch, REAL)
    _seed_watch("監視系統", "監視")
    _skip_quiet_period(monkeypatch)
    _need(ts, "run_scheduled_scan")()
    _assert_mails(mails, 1)          # 先釘住「這是一封寄得出去的真信」
    return mails[0][1] + mails[0][2]


def test_d9_every_tender_shows_seven_fields(client, admin_and_watch, monkeypatch):
    """§3 D9：每一筆在信裡都有七個欄位。"""
    body = _mail_body(monkeypatch)
    for label in ("機關", "地點", "採購性質", "招標方式", "預算", "截止"):
        assert label in body, f"信裡沒有「{label}」欄位。實際開頭 200 字：{body[:200]!r}"


def test_d10_null_fields_render_as_dash(client, admin_and_watch, monkeypatch):
    """§3 D10：欄位是 `NULL` 時顯示「—」，**不可以顯示空白或 `None`**。

    ⚠️ 配**肯定式前提**（`_assert_mails` 已在 `_mail_body` 裡做）——
    否則「信是空的」也會通過這個否定式斷言。
    """
    monkeypatch.setattr(ts, "fetch_detail", lambda url, *a, **kw: (None, "timeout"))
    body = _mail_body(monkeypatch)
    assert "None" not in body, (
        f"信裡出現了 Python 的 None。實際片段：{body[max(0, body.find('None') - 60):][:160]!r}"
    )
    assert "—" in body, "地點拿不到時應該顯示「—」，讓收件人知道那是「沒有」不是「漏掉」"


def test_d11_email_starts_with_a_summary(client, admin_and_watch, monkeypatch):
    """§3 D11：**信件開頭要有大綱**（共 N 筆、其中 M 筆七日內截止），不是直接進清單。"""
    body = _mail_body(monkeypatch)
    assert re.search(r"共\s*\d+\s*筆", body), (
        f"信件開頭沒有「共 N 筆」的大綱。實際開頭 200 字：{body[:200]!r}"
    )
    assert "7" in body or "七" in body, "大綱裡沒有「七日內截止」的筆數"


# ── D12～D14：定時可設定 ──────────────────────────────────────────────────

def test_d12_scan_hour_is_stored_in_system_settings(client):
    """§3 D12：設定的時間存 `system_settings`（A 已查證：**有進每日 JSON 備份**）。"""
    from helpers.settings import _get_setting, _set_setting
    _set_setting(SCAN_HOUR_SETTING, 9)
    assert _get_setting(SCAN_HOUR_SETTING) == 9


def test_d13_configured_time_does_not_change_the_daily_cap(client, monkeypatch):
    """§3 D13：**每日一次的硬上限不因設定而改變** —— 只能改「幾點」不能改「幾次」。

    ⚠️ 這題驗：設定過時間之後，**手動觸發兩次仍然只抓一次**。
    🔑 「可設定」最容易滑成「可繞過」—— 而繞過的是我們對別人伺服器的承諾。
    """
    from helpers.settings import _set_setting
    from tests.test_tender_match_2026_09_21 import REAL
    from tests.test_tender_notify_2026_09_21 import _sent

    _set_setting(SCAN_HOUR_SETTING, 9)
    _sent(monkeypatch)
    _detail_spy(monkeypatch)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    fetches = _spy_fetch(monkeypatch, REAL)
    run = _need(ts, "run_scheduled_scan")
    run()
    run()
    assert len(fetches) == 1, (
        f"設定了時間之後變成一天可以抓 {len(fetches)} 次 —— "
        "只能改幾點，不能改幾次"
    )


def test_d14_default_scan_hour_is_testable(client):
    """§3 D14：沒設定過時用預設值，**而預設值要測得到**。

    ⚠️ 「有預設值」跟「預設值是多少」是兩件事 ——
    寫死在函式裡而沒有具名常數的話，**沒有人驗得到它變了**。
    """
    default = _need(ts, "SCAN_HOUR")
    assert isinstance(default, int) and 0 <= default <= 23, (
        f"預設時間要是 0-23 的整數，實際 {default!r}"
    )


# ── 共用 helper ───────────────────────────────────────────────────────────

def _spy_fetch(monkeypatch, page):
    from tests.test_tender_notify_2026_09_21 import _spy
    return _spy(monkeypatch, ts, "fetch_raw", result=(page, None))


def _seed_watch(name, keywords):
    import db
    conn = db.get_db()
    try:
        if not conn.execute("SELECT 1 FROM tender_watches LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
                (name, keywords))
            conn.commit()
    finally:
        conn.close()


def _hit_count():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) c FROM tender_hits").fetchone()["c"]
    finally:
        conn.close()


def _allow_rerun(monkeypatch):
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_fetch_log")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(ts, "_already_fetched_today", lambda conn: False)


def _skip_quiet_period(monkeypatch):
    """跳過純記錄期 —— D9～D11 驗的是信件內容，不是要不要寄。"""
    if hasattr(ts, "_in_quiet_period"):
        monkeypatch.setattr(ts, "_in_quiet_period", lambda: False)


@pytest.fixture()
def admin_and_watch(client):
    """有 email 的 admin ＋ 一筆搜尋條件。

    ⚠️ 缺任一個，「有沒有寄信」或「`tender_hits` 有沒有列」就不可觀測 ——
    見〈給彙整〉29：**斷言寫對、觀測點挑對，而集合是空的，三者都要成立。**
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, "
            "modules, active, created_at, must_change_password, notification_muted) "
            "VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("tender_boss", "x", "收件人", "superadmin", "boss@example.invalid",
             "[]", "2026-01-01T00:00:00", "[]"))
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
            ("監視系統", "監視"))
        conn.commit()
    finally:
        conn.close()
    return "boss@example.invalid"
