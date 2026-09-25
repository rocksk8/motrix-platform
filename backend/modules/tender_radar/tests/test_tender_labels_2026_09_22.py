"""§3p 一、二 · **關鍵字從「門檻」變「標籤」＋ 臺/台 異體字**。

> **使用者：「200 筆改成都顯示，我可以打入關鍵字讓他分類，但分類剩的我一樣看得到」**
> **「台中跟臺中這兩個仍要修」**

## 🔴 現況（A 實測）

```
tenders = 200    watches = 3（都啟用）    tender_hits = 0
tender_source.py:538   JOIN tender_hits h ON h.tender_id = t.id   # 只有命中的
watch「台中」 → 0 筆   （政府採購網寫的是「臺中」）
```
⇒ **使用者看不到任何東西，而資料庫裡有 200 筆。**

## ☠️ 這一批最危險的一條是 P4：**通知不可以跟著改**

P1 與 P4 動的是**同一份查詢的兩個消費者**。
🔑 **而「顯示」與「通知」共用一個「命中」概念，正是它們會一起被改掉的原因。**
⚠️ 改錯的話**使用者每天收到 200 筆**，而那封信會讓他關掉整個功能。

## 📌 我釘的名字（§3p 沒有全部指定，B 要改先講）

| 名字 | 形狀 |
|---|---|
| `tender_match.normalize(text)` | 異體字正規化（**只在比對當下用**）|
| `tender_match.VARIANT_MAP` | 模組層常數，**目前只有臺/台**（P11）|
| `/api/tender-radar/tenders` 回應每筆的 `matchedWatches` | `[{id, name}, ...]`，沒命中是**空陣列**（P2）|
| `?watch=<id>` | 可選的篩選參數（P3）|
| `tender_source.rematch_all_tenders(conn)` | 回溯比對既有標案（P5）|
"""
import json

import pytest

import modules.tender_radar.match as tm
import modules.tender_radar.source as ts
from tests._timefreeze import freeze_slot

TENDERS_PATH = "/api/tender-radar/tenders"


def _need(mod, name):
    if not hasattr(mod, name):
        raise AssertionError(
            f"{mod.__name__} 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉")
    return getattr(mod, name)


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(watches=(), tenders=()):
    """直接寫 DB。**不經端點** —— 端點正是受測對象。"""
    import db
    conn = db.get_db()
    try:
        ids = {}
        for name, keywords, excludes in watches:
            cur = conn.execute(
                "INSERT INTO tender_watches (name, keywords, excludes, enabled) "
                "VALUES (?,?,?,1)",
                (name, json.dumps(keywords, ensure_ascii=False),
                 json.dumps(excludes, ensure_ascii=False)))
            ids[name] = cur.lastrowid
        for case_no, org, tname in tenders:
            conn.execute(
                "INSERT INTO tenders (case_no, org, name) VALUES (?,?,?)",
                (case_no, org, tname))
        conn.commit()
        return ids
    finally:
        conn.close()


def _list(client, hdr, **params):
    r = client.get(TENDERS_PATH, headers=hdr, params=params or None)
    assert r.status_code == 200, f"{TENDERS_PATH} 回 {r.status_code}：{r.text[:300]}"
    body = r.json()
    return body.get("items", body if isinstance(body, list) else [])


# ══════════════════════════════════════════════════════════════════════
# P1／P2／P3 · 全顯示 ＋ 標籤
# ══════════════════════════════════════════════════════════════════════

def test_p1_every_tender_is_listed_even_without_a_match(client, make_user):
    """🔴 P1：**沒有命中任何條件的標案也要出現在清單裡。**

    ☠️ 現況是 `JOIN tender_hits` 當門檻 ⇒ 資料庫裡 200 筆、畫面上 0 筆。
    使用者的原話：**「分類剩的我一樣看得到」。**
    """
    _seed(watches=[("監視", ["監視"], [])],
          tenders=[("HIT-001", "臺中市政府", "監視系統採購"),
                   ("MISS-001", "臺北市政府", "園藝維護")])
    hdr = _auth(client, make_user)
    items = _list(client, hdr)
    case_nos = {it.get("caseNo") or it.get("case_no") for it in items}
    assert {"HIT-001", "MISS-001"} <= case_nos, (
        f"沒命中的標案不在清單裡，實際只有 {sorted(case_nos)}\n"
        "⇒ 關鍵字仍然是門檻不是標籤。使用者會看到一張空白的清單，"
        "而資料庫裡有 200 筆。"
    )


def test_p2_matched_watches_is_an_empty_list_not_a_missing_key(client, make_user):
    """🔴 P2：沒命中的那些 `matchedWatches` 是**空陣列**，不是缺鍵、不是 `null`。

    ⚠️ 缺鍵與 `null` 在 JS 裡都會讓 `.map()` 炸掉，
    而前端最順手的寫法是 `t.matchedWatches.map(...)`。
    🔑 **「沒有標籤」是一個值，不是一個缺席。**（又是 `null` ≠ `0` 那一族。）
    """
    _seed(watches=[("監視", ["監視"], [])],
          tenders=[("HIT-001", "臺中市政府", "監視系統採購"),
                   ("MISS-001", "臺北市政府", "園藝維護")])
    hdr = _auth(client, make_user)
    by_case = {(it.get("caseNo") or it.get("case_no")): it
               for it in _list(client, hdr)}

    miss = by_case.get("MISS-001")
    assert miss is not None, "前提不成立：沒命中的那筆不在清單裡（見 P1）"
    assert "matchedWatches" in miss, (
        f"沒命中的那筆缺少 `matchedWatches` 這個鍵：{sorted(miss)}"
    )
    assert miss["matchedWatches"] == [], (
        f"沒命中時 `matchedWatches` 是 {miss['matchedWatches']!r}，應為空陣列"
    )

    hit = by_case.get("HIT-001")
    assert hit and hit["matchedWatches"], "命中的那筆沒有帶標籤（對照組不成立）"
    first = hit["matchedWatches"][0]
    assert "id" in first and "name" in first, (
        f"標籤裡沒有 id／name：{first!r} —— 前端要靠 id 做篩選、靠 name 顯示"
    )


def test_p3_the_watch_filter_is_optional(client, make_user):
    """P3：`?watch=<id>` 是**可選**的 —— 不帶就是全部，帶了才篩。

    ⚠️ 而「帶了才篩」要真的篩得動，否則那個參數是裝飾。
    """
    ids = _seed(watches=[("監視", ["監視"], [])],
                tenders=[("HIT-001", "臺中市政府", "監視系統採購"),
                         ("MISS-001", "臺北市政府", "園藝維護")])
    hdr = _auth(client, make_user)
    assert len(_list(client, hdr)) >= 2, "不帶參數應該是全部（前提不成立）"

    filtered = _list(client, hdr, watch=ids["監視"])
    case_nos = {it.get("caseNo") or it.get("case_no") for it in filtered}
    assert case_nos == {"HIT-001"}, (
        f"帶了 `watch={ids['監視']}` 卻拿到 {sorted(case_nos)} —— 那個參數沒有作用"
    )


def test_p6_disabling_a_watch_removes_its_label(client, make_user):
    """🔴 P6 反向控制：**停用一個條件 ⇒ 它要從所有 `matchedWatches` 裡消失。**

    ⚠️ 沒有這一題，一個「把命中寫死進資料表、再也不重算」的實作會讓 P2 全綠 ——
    而使用者停用了一個條件之後，**那個標籤還掛在畫面上**。
    🔑 **這一題證明那些標籤是算出來的，不是存下來的。**
    """
    ids = _seed(watches=[("監視", ["監視"], [])],
                tenders=[("HIT-001", "臺中市政府", "監視系統採購")])
    hdr = _auth(client, make_user)
    assert _list(client, hdr)[0]["matchedWatches"], "前提不成立：本來就沒有標籤"

    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE tender_watches SET enabled=0 WHERE id=?",
                     (ids["監視"],))
        conn.commit()
    finally:
        conn.close()

    items = _list(client, hdr)
    labels = [w for it in items for w in it.get("matchedWatches", [])]
    assert not labels, (
        f"條件已經停用，而標籤還在：{labels}\n"
        "⇒ 那些標籤是存下來的，不是算出來的。"
    )


# ══════════════════════════════════════════════════════════════════════
# P4 · 🔴 通知不可以跟著改
# ══════════════════════════════════════════════════════════════════════

def test_p4_notifications_still_only_cover_matched_tenders(client, monkeypatch):
    """🔴🔴 P4：**信仍然只寄「有命中的」。**

    ☠️ P1 與 P4 動的是**同一份查詢的兩個消費者**，
    🔑 **而「顯示」與「通知」共用一個「命中」概念，正是它們會一起被改掉的原因。**
    ⚠️ 改錯的話**使用者每天收到 200 筆** —— 而那封信會讓他關掉整個功能。

    📌 觀測點是**信的內容**，不是「有沒有寄」：
    一個「把全部塞進信裡」的實作**照樣只寄一封**。
    """
    import db
    from modules.tender_radar.tests.test_tender_notify_2026_09_21 import _sent

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, "
            "modules, active, created_at, must_change_password, notification_muted) "
            "VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("p4_boss", "x", "收件人", "superadmin", "boss@example.invalid",
             "[]", "2026-01-01T00:00:00", "[]"))
        conn.commit()
    finally:
        conn.close()
    _seed(watches=[("監視", ["監視"], [])])

    from modules.tender_radar.tests.test_tender_match_2026_09_21 import REAL
    mails = _sent(monkeypatch)
    freeze_slot(monkeypatch, ts, 18)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(ts, "fetch_detail",
                        lambda url, *a, **kw: (None, "測試不抓詳細頁"))
    monkeypatch.setattr(ts, "fetch_raw", lambda *a, **kw: (REAL, None))
    _need(ts, "run_scheduled_scan")()

    assert mails, "一封信都沒寄（前提不成立 —— 樣本裡應該有命中的）"
    html = mails[0][2] or ""
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT t.case_no FROM tenders t "
            "LEFT JOIN tender_hits h ON h.tender_id = t.id "
            "WHERE h.id IS NULL").fetchall()
    finally:
        conn.close()
    leaked = [r["case_no"] for r in rows if r["case_no"] and r["case_no"] in html]
    assert not leaked, (
        f"沒有命中任何條件的標案出現在信裡：{leaked}\n"
        "⇒ 通知跟著「全顯示」一起改掉了。使用者每天會收到全部的標案，"
        "而那封信會讓他關掉整個功能。"
    )


# ══════════════════════════════════════════════════════════════════════
# P5 · 新增條件要回溯比對
# ══════════════════════════════════════════════════════════════════════

def test_p5_a_new_watch_is_applied_to_existing_tenders(client, make_user):
    """🔴 P5：**新增搜尋條件之後，既有標案要被重新比對一次。**

    ☠️ 現況：`_record()` 只比對**這一次抓回來的** `items`
    ⇒ **既有 200 筆從來沒有被新增的條件比對過。**
    ⚠️ 而使用者的體驗是：新增條件、按儲存、**畫面一切正常** —— 而那件事沒有發生。

    🔑 那是今晚反覆出現的形狀：**成功的畫面，沒有發生的事。**
    """
    _seed(tenders=[("OLD-001", "臺中市政府", "監視系統採購")])
    hdr = _auth(client, make_user)
    before = _list(client, hdr)
    assert before and not before[0]["matchedWatches"], "前提不成立"

    r = client.post("/api/tender-radar/watches", headers=hdr,
                    json={"name": "監視", "keywords": "監視"})
    assert r.status_code == 201, r.text

    after = {(it.get("caseNo") or it.get("case_no")): it
             for it in _list(client, hdr)}
    labels = after["OLD-001"]["matchedWatches"]
    assert labels, (
        "新增了條件，而既有標案的標籤沒有更新。\n"
        "⇒ 比對只跑「這一次抓回來的」，既有的那些永遠不會被新條件比到。"
        "而使用者按了儲存、畫面一切正常。"
    )


# ══════════════════════════════════════════════════════════════════════
# P7～P11 · 異體字
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("keyword,text", [
    ("台中", "臺中市政府"),          # 使用者打「台」，資料是「臺」
    ("臺中", "台中榮民總醫院"),      # 反過來也要成立
    ("台北", "臺北市政府"),
])
def test_p7_variants_match_in_both_directions(keyword, text):
    """🔴 P7：`台` 與 `臺` **雙向**都要比得到。

    ⚠️ 政府採購網寫「臺中」，而使用者會打「台中」——
    **兩邊都可能是任一種寫法**，所以單向轉換不夠。
    """
    normalize = _need(tm, "normalize")
    assert normalize(keyword) in normalize(text), (
        f"`{keyword}` 比不到 `{text}` —— 正規化沒有雙向生效"
    )


def test_p8_normalization_never_rewrites_the_stored_text(client, make_user):
    """🔴 P8：**正規化只在比對當下發生，不可以改寫存進資料庫的原文。**

    ⚠️ 那是**政府的資料** —— 改了就對不回去：使用者拿案號去政府網站查，
    機關名稱對不上，而他不會知道是我們改的。
    🔑 **正規化是一個比對用的鏡片，不是一個寫入用的轉換。**
    """
    _seed(tenders=[("ORIG-001", "臺中市政府", "監視系統採購")])
    _seed(watches=[("台中", ["台中"], [])])
    hdr = _auth(client, make_user)
    _list(client, hdr)      # 走一次比對

    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT org FROM tenders WHERE case_no=?", ("ORIG-001",)).fetchone()
    finally:
        conn.close()
    assert row["org"] == "臺中市政府", (
        f"資料庫裡的機關名被改寫成 {row['org']!r} —— 原文是「臺中市政府」。\n"
        "⇒ 那是政府的資料，改了就對不回去。"
    )


def test_p9_excludes_are_normalized_too():
    """🔴 P9：**排除字也要套同一套正規化。**

    ⚠️ 不然「排除臺北」擋不掉「台北」——
    **而那個方向是「該排除的沒排掉」**，比「該命中的沒命中」更難發現：
    🔑 多出來的那幾筆看起來就像正常的結果。
    """
    matches = _need(tm, "matches")
    watch = {"id": 1, "name": "測試", "keywords": ["監視"],
             "excludes": ["臺北"], "org": None,
             "budget_min": None, "budget_max": None, "enabled": 1}
    tender = {"case_no": "X-1", "org": "台北市政府", "name": "監視系統採購",
              "deadline": None, "budget": None, "url": ""}
    assert not matches(tender, watch), (
        "排除字寫「臺北」而標案寫「台北」，沒有被排掉。\n"
        "⇒ 排除字沒有套正規化。而多出來的那幾筆看起來就像正常結果。"
    )


@pytest.mark.parametrize("a,b", [
    ("台中", "台南"),
    ("監視", "監控"),
    ("臺北", "新北"),
])
def test_p10_normalization_does_not_make_unrelated_things_equal(a, b):
    """🔴 P10 對照組：**正規化不可以讓無關的東西互相命中。**

    ⚠️ 沒有這一題，一個「把所有中文都正規化成拼音」或
    「把常見字全部映射在一起」的實作會讓 P7 全綠 ——
    **而使用者的每一個關鍵字都會命中全部 200 筆。**
    🔑 「比得到該比到的」與「比不到不該比到的」是兩件事。
    """
    normalize = _need(tm, "normalize")
    assert normalize(a) != normalize(b), (
        f"正規化之後 {a!r} 與 {b!r} 變成同一個東西 —— 那會讓關鍵字失去篩選能力"
    )


def test_p11_the_variant_table_says_what_it_does_not_cover():
    """P11：正規化表要是**模組層常數**，而且**明寫它只處理臺/台**。

    📌 理由：一個叫「異體字正規化」的函式**只處理一組字**，
    **而它的名字會讓下一個人以為全部都處理了。**
    🔑 今晚同一族的第三次：**名字承諾的範圍比實作大。**
    （前兩次：`DETAIL_DAILY_LIMIT` 其實是 per-call、
    `tiles_blocked` 量的是後端而不是瀏覽器。）
    """
    table = _need(tm, "VARIANT_MAP")
    assert isinstance(table, dict) and table, f"VARIANT_MAP 不是非空 dict：{table!r}"
    pairs = {(k, v) for k, v in table.items()}
    assert ("臺", "台") in pairs or ("台", "臺") in pairs, (
        f"VARIANT_MAP 裡沒有臺/台：{table!r}"
    )
    doc = (_need(tm, "normalize").__doc__ or "") + (tm.__doc__ or "")
    assert "臺" in doc and ("只" in doc or "未處理" in doc or "不處理" in doc), (
        "`normalize()` 的說明沒有寫出它**只**處理臺/台。\n"
        "⇒ 一個叫「異體字正規化」的函式只處理一組字，"
        "而它的名字會讓下一個人以為全部都處理了。"
    )
