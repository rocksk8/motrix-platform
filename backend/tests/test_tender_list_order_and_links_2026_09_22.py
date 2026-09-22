"""§3s · 清單排序（SO1–SO6）與可點開公告（SO7–SO10）。

---

# ⚠️ 先講這一節的**驗證覆蓋率**，因為它有一半我驗不到

| | 我能做到的 |
|---|---|
| **SO1／SO2／SO4／SO5／SO6** | ✅ 後端 API，真的驗 |
| **SO3**（命中區內部再分組） | ⚠️ **分組是顯示層** —— 後端給了 `matchedWatches`（含 `id` 與 `name`），前端拿它分組就成立。我只釘「**分得了組所需的資料在**」 |
| **SO7／SO8／SO9／SO10** | 🔴 **它們講的是 DOM**，而我只能對 `tender-radar.html` 做**文字比對** |

## 🔴 SO7–SO10 的驗證缺口，我明講而不是留給別人發現

真正能驗 DOM 的是 e2e（`live_server` ＋ 瀏覽器），而 **e2e 被打包腳本排除**
（`pytest -m "not e2e"`）⇒ **就算寫了 e2e，出貨那一關也不會跑它。**

⇒ 我做兩層，**而且標明哪一層是弱的**：
1. **後端（強）**：每一筆都要帶得出 `url`，而且它**要嘛是非空字串、要嘛是 `None`**
   —— 不可以是 `""`／`"None"`／空白。**那是前端能不能可靠分支的前提。**
2. **樣板（弱）**：`tender-radar.html` 的結構檢查。
   🔑 **它答的是「有沒有被寫出來」，不是「有沒有被渲染成那樣」** ——
   我今天已經因為同一種工具誤報過一次（U5c 把註解裡的 `DROP TABLE` 當真）。

📌 **SO8／SO10 的真正驗收是目視**，已請 A 排進它的清單。
🔑 **一道守門要說得出它守不到什麼，否則它的綠燈會被當成更大的保證。**
"""
import json
from pathlib import Path

import pytest

TENDERS_PATH = "/api/tender-radar/tenders"
PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "pages" / "tender-radar.html")


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _list(client, hdr, query=""):
    r = client.get(TENDERS_PATH + ("?" + query if query else ""), headers=hdr)
    assert r.status_code == 200, f"?{query} 回 {r.status_code}：{r.text[:220]}"
    return r.json()


def _items(body):
    if isinstance(body, list):
        return body
    for key in ("tenders", "items", "rows", "data"):
        if isinstance(body.get(key), list):
            return body[key]
    raise AssertionError(f"找不到清單本體，回傳的鍵有：{sorted(body)}")


def _case(item):
    return item.get("case_no") or item.get("caseNo")


def _matched(item):
    return item.get("matchedWatches") or []


@pytest.fixture()
def seeded(client):
    """六筆標案 ＋ 兩個搜尋條件，**每一筆負責一件事**。

    | | 負責 |
    |---|---|
    | S-01 | 命中「監控」，截止日**最近** |
    | S-02 | 命中「監控」，截止日較遠 |
    | S-03 | **同時**命中兩個條件 ⇒ SO4：只能出現一次 |
    | S-04 | 沒命中，截止日最近 ⇒ SO1：仍然要排在命中的**後面** |
    | S-05 | 沒命中，**沒有截止日** ⇒ SO5：排最後 |
    | S-06 | 沒命中，`url` 是空的 ⇒ SO8／SO10 |
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_watches")
        conn.execute("DELETE FROM tenders")
        rows = [
            ("S-01", "監控系統建置", "甲機關", "2026-10-01", "https://x/1"),
            ("S-02", "監控維護案",   "乙機關", "2026-12-31", "https://x/2"),
            ("S-03", "監控與無人機整合", "丙機關", "2026-11-15", "https://x/3"),
            ("S-04", "完全無關的採購", "丁機關", "2026-09-25", "https://x/4"),
            ("S-05", "沒有截止日的案子", "戊機關", None,        "https://x/5"),
            ("S-06", "沒有網址的案子",   "己機關", "2026-10-15", ""),
        ]
        for case_no, name, org, deadline, url in rows:
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, deadline, url, "
                "fetched_at) VALUES (?,?,?,?,?,?)",
                (case_no, name, org, deadline, url, "2026-09-22T00:00:00"))
        for kw in ("監控", "無人機"):
            conn.execute(
                "INSERT INTO tender_watches (name, keywords, excludes, enabled,"
                " created_at, updated_at) VALUES (?,?,'[]',1,?,?)",
                (kw, json.dumps([kw], ensure_ascii=False),
                 "2026-09-22T00:00:00", "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return 6


def _disable_all_watches():
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE tender_watches SET enabled=0")
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# SO1 / SO2 · 命中的在前，而兩者都在同一份清單裡
# ══════════════════════════════════════════════════════════════════════

def test_so1_matched_tenders_come_first_in_the_same_list(
        client, make_user, seeded):
    """🔴 SO1：命中任一條件的在前、未命中的在後，**兩者都在同一份清單裡**。

    📌 `S-04` 的截止日（09-25）比所有命中的都近 ——
    **如果排序只看截止日，它會排在最前面**，所以這一題分得出來
    「有沒有真的把命中當成第一排序鍵」。
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))
    assert len(items) == seeded, (
        f"清單有 {len(items)} 筆，資料庫有 {seeded} 筆 —— 兩者要在同一份清單裡"
    )

    flags = [bool(_matched(it)) for it in items]
    first_unmatched = flags.index(False) if False in flags else len(flags)
    assert all(not f for f in flags[first_unmatched:]), (
        "命中與未命中交錯了。順序是："
        + str([(_case(it), bool(_matched(it))) for it in items])
        + "\n⇒ 命中的要整段排在前面。"
    )
    assert first_unmatched >= 3, (
        f"只有 {first_unmatched} 筆排在未命中之前，而有三筆命中（S-01/02/03）"
    )


def test_so2_disabling_every_watch_does_not_shorten_the_list(
        client, make_user, seeded):
    """🔴🔴 SO2 反向控制：**停用所有搜尋條件 ⇒ 清單筆數不變。**

    ☠️ **「排在後面」與「看不到」實作起來只差一個 `if`** ——
    而使用者上一輪明確要過「**分類剩的我一樣看得到**」。
    🔑 少了這一題，一個「只回命中的」實作會讓 SO1 全綠
    （命中的確實排在前面……因為後面什麼都沒有）。
    """
    hdr = _auth(client, make_user)
    before = len(_items(_list(client, hdr)))
    assert before == seeded, f"前提不成立：一開始就只有 {before} 筆"

    _disable_all_watches()
    after = _items(_list(client, hdr))
    assert len(after) == seeded, (
        f"停用所有搜尋條件之後，清單從 {before} 筆變成 {len(after)} 筆。\n"
        "⇒ 使用者要的是「分類剩的我一樣看得到」。"
    )
    assert not any(_matched(it) for it in after), (
        "條件都停用了，卻仍然有標案被標成命中"
    )


# ══════════════════════════════════════════════════════════════════════
# SO3 · 分組所需的資料（分組本身是顯示層）
# ══════════════════════════════════════════════════════════════════════

def test_so3_each_match_names_the_watch_that_caused_it(
        client, make_user, seeded):
    """🔴 SO3：每一個命中都要說得出**是哪一個條件**（`id` ＋ `name`）。

    ⚠️ **分組本身是顯示層** —— 後端給得出「哪幾個條件命中」，
    前端就分得了組。我釘的是**分組所需的資料在不在**，不是後端有沒有分好組。
    🔑 釘後端的分組結構＝把一種實作寫成不變量，
    **而一個在前端分組的正確實作會紅**（今晚第 N 次同一個機會）。

    📌 `id` 與 `name` 兩個都要：只有 `name` 的話，兩個同名條件分不開；
    只有 `id` 的話，畫面上印不出人看得懂的字。
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))
    hits = [it for it in items if _matched(it)]
    assert hits, "一筆命中都沒有 —— 前提不成立"

    for it in hits:
        for w in _matched(it):
            assert isinstance(w, dict), (
                f"{_case(it)} 的 matchedWatches 元素不是物件：{w!r}\n"
                "⇒ 只有名字的話，兩個同名條件分不開。"
            )
            assert w.get("id") is not None and str(w.get("name") or "").strip(), (
                f"{_case(it)} 的命中少了 id 或 name：{w!r}"
            )


def test_so4_a_tender_matching_two_watches_appears_once(
        client, make_user, seeded):
    """🔴 SO4：一筆標案命中多個條件時**只出現一次**。

    📌 B 已經在 §3p 修過重複列，**不可以因為分組而退回去** ——
    而「依條件分組」最自然的 SQL 寫法（`JOIN tender_hits`）
    **正好會讓命中兩個條件的那一筆出現兩次**。
    ⚠️ 畫面上那是「同一個標案出現兩行」，使用者會以為有兩個案子。
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))

    cases = [_case(it) for it in items]
    dupes = {c for c in cases if cases.count(c) > 1}
    assert not dupes, f"這幾筆出現了不只一次：{sorted(dupes)}"

    s03 = [it for it in items if _case(it) == "S-03"]
    assert len(s03) == 1, f"S-03 出現了 {len(s03)} 次"
    assert len(_matched(s03[0])) == 2, (
        f"S-03 應該命中兩個條件，實際 {_matched(s03[0])}\n"
        "⇒ 這一題的前提不成立（去重把第二個命中也一起吃掉了？）"
    )


# ══════════════════════════════════════════════════════════════════════
# SO5 / SO6 · 組內次序要可解釋
# ══════════════════════════════════════════════════════════════════════

def _assert_segment_order(client, make_user, want_matched, label):
    """某一段內：截止日近的在前，沒有截止日的排最後。

    ⚠️ **不可以是資料庫的自然順序** —— 那會隨插入順序漂移，
    而漂移的樣子是「**今天的清單跟昨天不一樣，但沒有人改過東西**」。
    🔑 A 的理由：**時間壓力是標案唯一的內建排序依據。**

    📌 `NULL` 在 SQLite 的排序裡最小 ⇒ 不處理的話
    「沒寫截止日」會**插到最急的位置**，那是正好相反的答案。
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))
    seg = [it for it in items if bool(_matched(it)) == want_matched]
    assert len(seg) >= 2, f"`{label}` 這一段只有 {len(seg)} 筆，比不出次序"

    deadlines = [it.get("deadline") for it in seg]
    with_d = [d for d in deadlines if d]
    assert with_d == sorted(with_d), (
        f"`{label}` 段的截止日不是由近到遠：{deadlines}"
    )
    tail = deadlines[len(with_d):]
    assert all(not d for d in tail), (
        f"`{label}` 段裡沒有截止日的那幾筆沒有排在最後：{deadlines}\n"
        "⇒ `NULL` 在 SQLite 裡最小，不處理的話它會插到最急的位置。"
    )


def test_so5_the_matched_segment_is_ordered_by_deadline(
        client, make_user, seeded):
    """🔴 SO5：**命中區**內部，截止日近的在前、沒有截止日的排最後。

    📌 拆成兩支（SO5／SO6）而不是一支參數化 ——
    ⚠️ 參數化的話**函式名只有一個**，而規格覆蓋率守門認的是**函式名**
    ⇒ SO6 會被判定成「規格宣告了而沒有人寫」。
    🔑 **那個守門是我寫的，而我自己第一版就踩了它。**
    """
    _assert_segment_order(client, make_user, True, "matched")


def test_so6_the_unmatched_segment_is_ordered_the_same_way(
        client, make_user, seeded):
    """🔴 SO6：**未命中區**的次序同 SO5。

    ⚠️ 兩段各自排序，而**不是整份排完再分段** ——
    整份排完再分段的話，`S-04`（09-25，沒命中）會被推到最前面，
    那正是 SO1 在擋的事。
    """
    _assert_segment_order(client, make_user, False, "unmatched")


# ══════════════════════════════════════════════════════════════════════
# SO7–SO10 · 可點開公告
# ══════════════════════════════════════════════════════════════════════

def test_so8_the_api_makes_an_empty_url_unambiguous(
        client, make_user, seeded):
    """🔴 SO8（後端這一半，**這是我驗得到的強的那層**）：
    每一筆都要帶得出 `url`，而它**要嘛是非空字串、要嘛是 `None`**。

    ☠️ 回 `""` 的話，前端的分支要寫成 `if (t.url)` 才對，
    而**最自然的寫法 `if (t.url !== undefined)` 會把空字串當成有網址**
    ⇒ 渲染出一個 `href=""` 的死連結。
    🔑 **一個看起來可以點的東西點了沒反應，比一開始就不可點更糟** ——
    前者讓使用者以為是網路壞了，然後再點五次。

    📌 這一題**不驗 DOM**（我驗不到），它驗的是**讓 DOM 能寫對的前提**。
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))
    assert items, "前提不成立：清單是空的"

    for it in items:
        assert "url" in it, f"{_case(it)} 沒有 `url` 這個鍵：{sorted(it)}"
        url = it["url"]
        assert url is None or (isinstance(url, str) and url.strip() == url
                               and url != ""), (
            f"{_case(it)} 的 `url` 是 {url!r} —— 要嘛非空字串、要嘛 None。\n"
            "⇒ `\"\"` 與前後空白會讓前端的分支寫錯，而錯的方向是渲染出死連結。"
        )

    empty = [it for it in items if _case(it) == "S-06"]
    assert empty and empty[0]["url"] is None, (
        f"S-06 的 url 在資料庫裡是空字串，API 應該回 None，"
        f"實際 {empty[0]['url'] if empty else '找不到那一筆'!r}"
    )


def test_so9_the_template_opens_links_with_noopener():
    """🟡 SO9：外開新分頁要帶 `rel="noopener noreferrer"`。

    ⚠️ **這是文字比對，弱的**（見檔頭）。
    🔑 但 `noopener` **不是可選的**：少了它，被開啟的那一頁可以透過
    `window.opener` 改寫我們這一頁的網址 —— 而使用者不會發現分頁被換掉了。
    📌 `noreferrer` 順帶擋掉 referrer 外洩（與 §3m 的 Referrer-Policy 同一件事）。
    """
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    assert 'target="_blank"' in text or "target='_blank'" in text, (
        "`tender-radar.html` 裡沒有任何 `target=\"_blank\"` —— "
        "SO7 的連結還沒做（這一題的前提不成立）"
    )
    for i, chunk in enumerate(text.split('target="_blank"')[1:], start=1):
        window = chunk[:200]
        assert "noopener" in window, (
            f"第 {i} 個 `target=\"_blank\"` 附近沒有 `noopener`：\n{window[:160]}"
        )
        assert "noreferrer" in window, (
            f"第 {i} 個 `target=\"_blank\"` 附近沒有 `noreferrer`"
        )


def test_so10_the_template_guards_the_link_with_a_condition():
    """🟡 SO10：`url` 空的時候 **DOM 裡不存在 `<a>`**。

    ⚠️ **這是文字比對，弱的** —— 我只能確認那個 `<a>` 被一個條件包著，
    **不能確認那個條件判得對**。
    🔑 〈診斷的層級決定覆蓋率〉：它答的是「有沒有被寫出來」。
    📌 真正的驗收是目視（已請 A 排進清單）：找一筆沒有網址的標案，
    確認那裡是純文字、不是一個點不動的連結。

    ⇒ 而**強的那一層在 SO8**：API 保證空網址回 `None`，
    讓前端那個條件**有可能寫對**。
    """
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    assert "t.url" in text or "tender.url" in text, (
        "`tender-radar.html` 裡完全沒有用到標案的 `url`。\n"
        "⚠️ 它**應該**用得到 ⇒ 看 `SO7`；`SO7` 已完成 ⇒ "
        "**那是那一段被改掉或刪掉了**。"
    )
    guarded = ("x-if=" in text and "url" in text) or ("x-show=" in text
                                                      and "url" in text)
    assert guarded, (
        "找不到任何以 `url` 為條件的 `x-if`／`x-show` ——\n"
        "⇒ 那個 `<a>` 沒有被條件包著，空網址會渲染成死連結。"
    )


def test_so7_both_the_tender_name_and_the_organisation_are_clickable():
    """🟡 SO7：**標案名稱**與**機關名稱**都可點，開啟 `tenders.url`。

    ⚠️ **這是文字比對，弱的**（見檔頭）—— 我只能確認兩個欄位都出現在
    連結的標記裡，**不能確認渲染出來真的可以點**。

    📌 為什麼兩個都要：使用者在清單上掃的是**機關名稱**（他認得哪些機關
    常發他做得來的標案），而標案名稱太長、常被截斷。
    🔑 只做一個的話，**他會去點另一個然後以為壞了**。
    """
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")

    links = text.split("<a ")[1:]
    assert links, (
        "`tender-radar.html` 裡一個 `<a>` 都沒有。\n"
        "⚠️ 它**應該**有 ⇒ 看 `SO7`；`SO7` 已完成 ⇒ "
        "**那是連結那一段被改掉或刪掉了**。")

    def _linked(field):
        return any(field in chunk[:400] for chunk in links)

    assert _linked("t.name") or _linked("tender.name"), (
        "沒有任何 `<a>` 裡用到標案名稱"
    )
    assert _linked("t.org") or _linked("tender.org"), (
        "沒有任何 `<a>` 裡用到機關名稱 ——\n"
        "⇒ 使用者在清單上掃的是機關名稱，只做標案名稱的話"
        "他會去點機關名然後以為壞了。"
    )
