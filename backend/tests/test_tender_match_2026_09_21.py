"""2026-09-21 · 第 4 輪：標案雷達第 1～3 步（設條件、抓得到、比對得出命中）

對應 `docs/windows/STATE.md` §3 **第二版**（`862d48c`）的 **17 條**驗收條件。

> ⚠️ 第一版我寫完於 13:49，A 於 13:50:53 把 §3 改成第二版（B 開工前審單，
> 八項成立、三處規格是錯的）。**本檔已改照第二版。** 條件 1～4、7、7b、7c、9 未動；
> 條件 5、6 改了，另加 6b／6c／7d／8b／9b／9c。

## 🔴 我沒有讀實作

B 還沒寫任何產品碼（`helpers/tender_source.py`／`helpers/tender_match.py`／
`routers/tender_radar.py` 都不存在），所以「不讀實作」是自然成立的。
**這是正常的②先於④順序，全紅是預期的起點。**

---

## B 要提供的名字

`helpers/tender_source.py`

| 名字 | 形態 | 來源 |
|------|------|------|
| `TENDER_RADAR_ENABLED` | `bool`，**預設 `False`** | §3 |
| `fetch_raw(params)` | 🔴 **`-> (html: str|None, error: str|None)`** | §3 v2（B ①） |
| `parse_list(html)` | `-> (list[dict], dropped:int, recognised:bool)` | §3 |
| `run_scan()` | 每日掃描進入點 | ⚠️ C 取的名字 |
| `suspect_redesign(parsed_count, dropped)` | `-> bool` | ⚠️ C 取的名字 |

`helpers/tender_match.py`：⚠️ `match_watches(tender, watches) -> list[dict]`（C 取的名字）

**欄位一律 snake_case** —— 這些是純函式參數與資料庫欄位，不是 API 回應。
第 3 輪的教訓是 **API 命名空間 ≠ 資料庫命名空間**，所以刻意不套 camelCase。

---

## 這一輪的核心：**三種壞法，三個訊號，不能互相蓋掉**

| 壞法 | 該長什麼樣 | 為什麼容易被合併 |
|---|---|---|
| 今天真的沒標案 | `recognised=True, items=[]` | |
| 對方改版、整頁認不出 | `recognised=False` | **跟上面一樣是 `items=[]`**（7b／7c 必須分開）|
| 網站掛了／403／逾時 | **記成「抓不到」，不是「不認得」** | 拿到空字串 → 也找不到容器 → 也是 `recognised=False`（7d）|
| **欄序被對調** | 該筆丟掉並計入 `dropped` | ⚠️ **三個訊號全綠而每一筆資料都是錯的**（6c）|

前三種是「雷達安靜」，**第四種是雷達報錯的東西而且看起來很正常** —— 最難發現的那種。

## 條件 8／8b：先證明量尺有刻度，再拿它去量

第 8 題只驗「關著時 `fetch_raw` 沒被呼叫」是**假綠**：若 patch 目標寫錯
（呼叫端用 `from ... import` 把副本複製走了），計數器**永遠是 0**，第 8 題**永遠綠**。
⇒ **8b 必須與 8 分開**：開關打開時同一個計數器 ≥ 1。

⚠️ §3 v2 已規定**呼叫端要寫 `tender_source.fetch_raw()` 走模組**，不要 `from ... import`。

---

## ⚠️ HTML 樣本是 C 假定的結構，真實樣本必須取代它

下面的 `HTML_*` 常數是我**照一般政府採購網列表頁的長相假定的** —— §3 禁止連真網站，
總開關也預設關著，我沒有真實樣本。

**樣本與斷言已經分開**：斷言驗的是語意（`recognised` 真假、`dropped` 數字、丟掉哪一筆），
**不依賴任何特定標籤名** ⇒ **真實樣本進來時只要換這幾個常數，測試一行都不用改。**

誰擷取、什麼時候，見〈給彙整〉第 15 點。**在那之前這幾題驗的是
「解析器對我假定的結構的行為」，不是「對真實網站的行為」。**
"""
import sqlite3

import pytest


# ── 契約 ─────────────────────────────────────────────────────────────────────

try:
    from helpers import tender_source as src
except Exception as exc:  # noqa: BLE001
    src = None
    _SRC_ERR = repr(exc)

try:
    from helpers import tender_match as tmatch
except Exception as exc:  # noqa: BLE001
    tmatch = None
    _MATCH_ERR = repr(exc)


def _src(name=None):
    if src is None:
        raise AssertionError(
            f"backend/helpers/tender_source.py 還不存在（或 import 失敗）：{_SRC_ERR}。"
            "需要的名字見本檔開頭的契約表。"
        )
    if name and not hasattr(src, name):
        raise AssertionError(f"helpers/tender_source.py 缺少 `{name}`，見本檔開頭的契約表。")
    return getattr(src, name) if name else src


def _tm(name=None):
    if tmatch is None:
        raise AssertionError(
            f"backend/helpers/tender_match.py 還不存在（或 import 失敗）：{_MATCH_ERR}。"
            "需要的名字見本檔開頭的契約表。"
        )
    if name and not hasattr(tmatch, name):
        raise AssertionError(f"helpers/tender_match.py 缺少 `{name}`，見本檔開頭的契約表。")
    return getattr(tmatch, name) if name else tmatch


# ── HTML 樣本（⚠️ C 假定的結構，見檔頭）────────────────────────────────────

_ROW = ("<tr><td>{case_no}</td><td>{name}</td><td>{org}</td>"
        "<td>{deadline}</td><td>{budget}</td></tr>")

_HEADER = ("<table class='tender_list'>"
           "<tr><th>案號</th><th>標案名稱</th><th>機關</th><th>截止日</th><th>預算金額</th></tr>")


def _page(rows):
    return "<html><body>" + _HEADER + "".join(rows) + "</table></body></html>"


HTML_TWO_ROWS = _page([
    _ROW.format(case_no="A-001", name="網路設備採購案", org="某某市政府",
                deadline="2026-10-15", budget="1200000"),
    _ROW.format(case_no="A-002", name="監視系統建置", org="某某縣政府",
                deadline="2026-10-20", budget="800000"),
])

# 有容器與表頭、零筆資料 ＝「今天真的沒有新標案」
HTML_EMPTY_LIST = _page([])

# 沒有列表容器 ＝「對方改版／我們瞎了」
HTML_NOT_A_LIST = "<html><body><div class='notice'>系統維護中。</div></body></html>"

# 缺「機關」這個必要欄位（§3 v2：必要欄位 ＝ 案號／名稱／機關）
HTML_ONE_MISSING_FIELD = _page([
    _ROW.format(case_no="B-001", name="完整的標案", org="某某市政府",
                deadline="2026-10-15", budget="500000"),
    _ROW.format(case_no="B-002", name="缺機關的標案", org="",
                deadline="2026-10-16", budget="600000"),
])

# 沒有截止日 —— §3 v2 把截止日移出必要欄位，這一筆要**收下**
HTML_NO_DEADLINE = _page([
    _ROW.format(case_no="ND-001", name="沒寫截止日的標案", org="某某市政府",
                deadline="", budget="500000"),
])

# ⚠️ 欄序被對調：案號欄放的是機關、機關欄放的是案號。
# 必要欄位「全都在」、dropped=0、容器也找得到 ⇒ 三個訊號全綠而資料全錯。
HTML_TRANSPOSED = _page([
    _ROW.format(case_no="某某市政府", name="欄位對調的標案", org="D-001",
                deadline="2026-10-15", budget="500000"),
])

# 四筆裡三筆缺必要欄位 → dropped=3 > 4/2，應判定疑似改版
HTML_MOSTLY_DROPPED = _page([
    _ROW.format(case_no="C-001", name="完整的標案", org="某某市政府",
                deadline="2026-10-15", budget="500000"),
    _ROW.format(case_no="", name="缺案號", org="某某市政府",
                deadline="2026-10-16", budget="600000"),
    _ROW.format(case_no="C-003", name="", org="某某市政府",
                deadline="2026-10-17", budget="700000"),
    _ROW.format(case_no="C-004", name="缺機關", org="",
                deadline="2026-10-18", budget="800000"),
])


def _watch(**over):
    w = {"id": 1, "name": "預設條件", "keywords": ["網路"], "excludes": [],
         "org": None, "budget_min": None, "budget_max": None, "enabled": 1}
    w.update(over)
    return w


def _tender(**over):
    t = {"case_no": "A-001", "name": "網路設備採購案", "org": "某某市政府",
         "deadline": "2026-10-15", "budget": 1_200_000,
         "url": "https://example.invalid/t/A-001"}
    t.update(over)
    return t


# ── 條件 1：關鍵字命中 ──────────────────────────────────────────────────────

def test_01_keyword_in_name_matches():
    """§3 條件 1：標案名含關鍵字 → 命中。"""
    hits = _tm("match_watches")(_tender(name="網路設備採購案"), [_watch(keywords=["網路"])])
    assert [h["id"] for h in hits] == [1], f"應該命中，實際 {hits!r}"


def test_01b_keyword_not_in_name_does_not_match():
    """對照組：關鍵字沒中就不可以命中。

    沒有這一題，一個「永遠回全部 watch」的實作會讓條件 1 全綠。
    """
    hits = _tm("match_watches")(_tender(name="辦公家具採購"), [_watch(keywords=["網路"])])
    assert hits == [], f"關鍵字沒中就不該命中，實際 {hits!r}"


def test_01c_multiple_keywords_are_or():
    """§3：關鍵字是 OR，中任何一個就算。"""
    assert len(_tm("match_watches")(
        _tender(name="監視系統建置"), [_watch(keywords=["消防", "監視"])])) == 1


def test_01d_one_tender_can_hit_multiple_watches():
    """§3：一筆標案可命中多個 watch。"""
    hits = _tm("match_watches")(_tender(name="網路設備採購案"),
                                [_watch(id=1, keywords=["網路"]),
                                 _watch(id=2, keywords=["採購"])])
    assert sorted(h["id"] for h in hits) == [1, 2], f"兩個都該中，實際 {hits!r}"


# ── 條件 2：排除詞 ──────────────────────────────────────────────────────────

def test_02_exclude_word_wins_over_keyword():
    """§3 條件 2：排除詞一中就整筆排除，**即使關鍵字也命中**。

    這是反向驗證第 1 題的目標；觀測點必須是 `match_watches` 的回傳值。
    """
    hits = _tm("match_watches")(_tender(name="網路設備維護案"),
                                [_watch(keywords=["網路"], excludes=["維護"])])
    assert hits == [], f"關鍵字中了但排除詞也中了 → 整筆排除，實際 {hits!r}"


def test_02b_exclude_only_applies_when_present():
    """對照組：排除詞沒中不可以誤殺。

    只有上一題的話，「有 excludes 就一律排除」的實作也會全綠。
    """
    assert len(_tm("match_watches")(
        _tender(name="網路設備採購案"), [_watch(keywords=["網路"], excludes=["維護"])])) == 1


# ── 條件 3：機關沒填＝不篩 ─────────────────────────────────────────────────

def test_03_blank_org_means_no_filter():
    """§3 條件 3：機關沒填 → **不篩**，不是「篩出 0 筆」。

    ⚠️ 跟 `0` vs `null` 同一家族：「沒填」被當成「篩選值是空字串」的話，
    結果是安靜地一筆都不回 —— 而那看起來就像「今天沒有符合的標案」。
    """
    hits = _tm("match_watches")(_tender(org="某某市政府"),
                                [_watch(keywords=["網路"], org=None)])
    assert len(hits) == 1, f"機關沒填不該篩掉任何東西，實際 {hits!r}"


def test_03b_org_filter_actually_filters_when_set():
    """對照組：機關有填的時候要真的篩。"""
    w = _watch(keywords=["網路"], org="某某市政府")
    assert len(_tm("match_watches")(_tender(org="某某市政府"), [w])) == 1
    assert _tm("match_watches")(_tender(org="別的縣政府"), [w]) == []


# ── 條件 4：金額上下限 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("bmin, bmax, budget, hit", [
    (1_000_000, None, 1_200_000, True),
    (1_000_000, None,   800_000, False),
    (None, 1_000_000,   800_000, True),
    (None, 1_000_000, 1_200_000, False),
    (None, None,      1_200_000, True),
])
def test_04_budget_bounds_filter_only_the_side_that_is_set(bmin, bmax, budget, hit):
    """§3 條件 4：上下限只填一邊 → 只篩那一邊。

    ⚠️ 最後一格跟條件 3 同一個陷阱：`None` 被當成 `0` 的話，
    「沒填下限」變「下限 0」（剛好無害），但「沒填上限」變「上限 0」
    —— **一筆都不會中，而且安靜**。
    """
    hits = _tm("match_watches")(_tender(budget=budget),
                                [_watch(keywords=["網路"], budget_min=bmin, budget_max=bmax)])
    assert bool(hits) is hit, (
        f"min={bmin} max={bmax} budget={budget} → "
        f"預期{'命中' if hit else '不中'}，實際 {hits!r}"
    )


# ── 條件 5：(機關, 案號) 去重 ──────────────────────────────────────────────

def _cols(table):
    import db
    conn = db.get_db()
    try:
        return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


@pytest.mark.parametrize("table", ["tender_watches", "tenders", "tender_hits",
                                   "tender_fetch_log"])
def test_05_tables_exist(client, table):
    """§3：四張新表要存在（含 9b 的 `tender_fetch_log`）。"""
    assert _cols(table), f"資料表 {table} 不存在（B 的 migration 還沒做）"


def test_05b_same_org_and_case_no_cannot_be_inserted_twice(client):
    """§3 v2 條件 5：**同機關同案號**被抓兩次 → `tenders` 只有一列。

    ⚠️ 驗的是**資料庫唯一鍵**，不是寫入函式有沒有先查再寫：
    「先 SELECT 再 INSERT」在兩次抓取重疊時仍然會插進兩列，
    唯一鍵才是任何情況下都成立的保證。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("DUP-001", "重複的標案", "某某市政府"))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                         ("DUP-001", "重複的標案（第二次抓到）", "某某市政府"))
            conn.commit()
    finally:
        conn.close()


def test_05c_same_case_no_different_org_is_allowed(client):
    """§3 v2 條件 5 的**重點**：案號相同但機關不同 → 兩列都要留下。

    ⚠️ 這題就是把唯一鍵從 `案號` 改成 `(機關, 案號)` 的全部理由（B ④）：
    案號當鍵而兩個機關剛好撞號時，**第二筆會併進第一筆、悄悄消失**
    —— 那就是漏掉標案，而這條線的承諾正好是「不會漏掉標案」。
    `(機關, 案號)` 撞號只是多一列，**看得見**。

    🔑 **不確定的時候往「最壞只是吵」倒，不要往「最壞是靜默遺失」倒。**
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("SAME-001", "甲機關的標案", "某某市政府"))
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("SAME-001", "乙機關的標案", "另一個縣政府"))
        conn.commit()
        n = conn.execute("SELECT COUNT(*) c FROM tenders WHERE case_no=?",
                         ("SAME-001",)).fetchone()["c"]
    finally:
        conn.close()
    assert n == 2, (
        f"同案號不同機關應該是兩筆不同的標案，實際只剩 {n} 筆 —— "
        "唯一鍵若只有 case_no，第二筆會靜默消失"
    )


def test_05d_same_watch_tender_pair_cannot_be_recorded_twice(client):
    """§3 條件 5 後半：`tender_hits` 不重複。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("HIT-001", "標案", "某某市政府"))
        conn.execute("INSERT INTO tender_watches (name, keywords) VALUES (?,?)",
                     ("條件一", "網路"))
        conn.commit()
        tid = conn.execute("SELECT id FROM tenders WHERE case_no=?",
                           ("HIT-001",)).fetchone()["id"]
        wid = conn.execute("SELECT id FROM tender_watches WHERE name=?",
                           ("條件一",)).fetchone()["id"]
        conn.execute("INSERT INTO tender_hits (watch_id, tender_id) VALUES (?,?)", (wid, tid))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tender_hits (watch_id, tender_id) VALUES (?,?)",
                         (wid, tid))
            conn.commit()
    finally:
        conn.close()


# ── 條件 6／6b／6c：解析時該丟什麼、該留什麼 ───────────────────────────────

def test_06_row_missing_required_field_is_dropped_and_counted():
    """§3 v2 條件 6：必要欄位（**案號／名稱／機關**）缺一 → 整筆丟掉，`dropped` +1。

    ⚠️ 觀測點要同時看留下來的筆數**與** `dropped` 的數字：只看 `len(items)` 的話，
    「丟掉了但沒計數」會是綠的 —— 而 `dropped` 正是條件 7 的唯一輸入。
    """
    items, dropped, recognised = _src("parse_list")(HTML_ONE_MISSING_FIELD)
    assert recognised is True, "這一頁有列表容器，應該是認得的"
    assert dropped == 1, f"缺機關那筆要計入 dropped，實際 {dropped}"
    assert [i["case_no"] for i in items] == ["B-001"], (
        f"只有完整那筆該留下，實際 {[i.get('case_no') for i in items]!r}"
    )


def test_06_complete_page_drops_nothing():
    """對照組：完整的頁面不可以丟掉任何一筆。"""
    items, dropped, recognised = _src("parse_list")(HTML_TWO_ROWS)
    assert recognised is True
    assert dropped == 0, f"兩筆都完整，不該丟，實際 dropped={dropped}"
    assert [i["case_no"] for i in items] == ["A-001", "A-002"]


def test_06b_missing_deadline_is_still_accepted_as_none():
    """§3 v2 條件 6b：**沒有截止日的標案仍然收下**，`deadline` 是 `None`。

    ⚠️ 第一版把截止日列為必要欄位，那是錯的（A 自承）：
    「公告沒寫截止日」的標案**解析是成功的**，把它算成解析失敗會
    **污染 `dropped > 一半` 的訊號** —— 那個訊號是用來判斷「對方是不是改版了」的，
    被正常資料灌水之後就會誤報。

    ⚠️ 而且 `deadline` 要是 `None` 不是空字串 —— 跟條件 9 的 `0` vs `NULL` 同一家族。
    """
    items, dropped, recognised = _src("parse_list")(HTML_NO_DEADLINE)
    assert recognised is True
    assert dropped == 0, f"沒有截止日不算解析失敗，實際 dropped={dropped}"
    assert len(items) == 1, f"這一筆要收下，實際 {items!r}"
    assert items[0]["deadline"] is None, (
        f"沒寫截止日要是 None，實際 {items[0]['deadline']!r}"
        "（空字串會讓下游分不出「沒寫」與「寫了空的」）"
    )


def test_06c_transposed_columns_are_dropped_not_silently_accepted():
    """§3 v2 條件 6c：**欄序被對調 → 該筆要被丟掉並計入 `dropped`**。

    ⚠️ **這是第四種壞法，也是最難發現的一種**（B ②）：
    對方把表格欄序換了（案號欄變成機關欄）⇒ 必要欄位**全都在**、`dropped=0`、
    容器也找得到 ⇒ `recognised=True`。

    > **三個訊號全綠，而每一筆資料都是錯的。**
    > 前三種壞法是雷達安靜；**這一種是雷達報錯的東西，而且看起來很正常。**

    這題是反向驗證第 5 題的目標：把形狀驗證拿掉 → 這題必須精準變紅。
    """
    items, dropped, recognised = _src("parse_list")(HTML_TRANSPOSED)
    assert recognised is True, "容器還在，所以不是『認不得』那種壞法"
    assert dropped == 1, (
        f"案號欄放的是機關名、機關欄放的是案號 → 形狀不符，該筆要丟掉，"
        f"實際 dropped={dropped}"
    )
    assert items == [], f"不可以安靜地收下形狀不符的資料，實際 {items!r}"


# ── 條件 7：dropped 過半 → 疑似改版 ────────────────────────────────────────

def test_07_mostly_dropped_raises_suspect_redesign_flag():
    """§3 條件 7：`dropped` 超過當次總數一半 → 回「疑似對方改版」旗標。

    ⚠️ 這一頁**認得出容器**（`recognised=True`），所以跟 7c 是不同的壞法：
    **版面還在，但每一列的欄位都對不上了。** 兩者處置不同，不能合併。
    """
    items, dropped, recognised = _src("parse_list")(HTML_MOSTLY_DROPPED)
    assert recognised is True, "版面還在，應該仍然認得"
    assert dropped == 3, f"四筆裡三筆缺必要欄位，實際 dropped={dropped}"
    assert _src("suspect_redesign")(len(items), dropped) is True, (
        f"4 筆丟了 3 筆（過半）應判定疑似改版，實際 "
        f"suspect_redesign({len(items)}, {dropped})"
    )


def test_07_healthy_page_is_not_flagged_as_redesign():
    """對照組：正常的頁面不可以被判成改版。

    ⚠️ 沒有這題，一個「永遠回 True」的 `suspect_redesign` 會讓上一題全綠，
    後果是**每天都發一次「疑似改版」** —— 狼來了的告警等於沒有告警。
    """
    items, dropped, _ = _src("parse_list")(HTML_TWO_ROWS)
    assert _src("suspect_redesign")(len(items), dropped) is False


# ── 條件 7b／7c：recognised 看結構不看筆數 ─────────────────────────────────

def test_07b_empty_list_with_container_is_recognised():
    """§3 條件 7b：**有容器但零筆** → `recognised=True, items=[]`（今天沒標案）。

    這是反向驗證第 4 題的目標：把 `recognised` 改成用「筆數 > 0」判定 →
    **這題必須精準變紅**（筆數是 0，但結構在）。
    """
    items, dropped, recognised = _src("parse_list")(HTML_EMPTY_LIST)
    assert items == [], f"沒有資料列，items 應為空，實際 {items!r}"
    assert dropped == 0, f"沒有資料列就沒有東西可丟，實際 {dropped}"
    assert recognised is True, (
        "有容器與表頭 → 這是『今天真的沒有新標案』，雷達是好的。"
        "⚠️ 若回 False，代表 recognised 用筆數判定 —— "
        "那樣『沒標案』會被誤報成『它瞎了』，每天發一次假警報。"
    )


def test_07c_page_without_list_container_is_not_recognised():
    """§3 條件 7c：**沒有列表容器** → `recognised=False`（它瞎了）。

    ⚠️ 這條線的價值是「不會漏掉標案」，**瞎掉正好是它唯一不能發生的事**，
    而失敗的那一側完全無聲。**壞掉會被報修，安靜地少做一件事不會。**
    """
    items, dropped, recognised = _src("parse_list")(HTML_NOT_A_LIST)
    assert recognised is False, (
        "沒有列表容器（維護公告頁）應判定為『認不得』。"
        "⚠️ 若回 True，整頁改版不會被發現 —— 雷達會安靜地永遠回 0 筆。"
    )
    assert items == [], f"認不得的頁面不該生出資料，實際 {items!r}"


# ── 條件 7d：抓不到 ≠ 不認得 ───────────────────────────────────────────────

def test_07d_fetch_failure_is_recorded_as_unreachable_not_unrecognised(
    client, monkeypatch
):
    """§3 v2 條件 7d：**抓取失敗（逾時／403／連不上）→ 記成「抓不到」不是「不認得」**。

    ⚠️ **這是我們上一輪才剛分開、結果在上面一層又合併了一次的東西**（B ①）：
    `fetch_raw` 舊簽名 `-> str` **沒有辦法表達「我沒拿到」**。網站掛了回空字串 →
    `parse_list` 同樣找不到容器 → `recognised=False` → **跟「對方改版」一模一樣**。

    **但處置完全相反**：改版要去改解析器，掛掉只要等它好。
    分不出來的話，每次對方維護我們都會跑去改一個沒有壞的解析器。

    契約：抓不到時 `tender_fetch_log.error` 有值、而 `recognised` 是 **NULL**
    （不是 `False`）—— 根本沒走到解析那一步。⚠️ C 釘的，見〈給彙整〉第 16 點。
    """
    mod = _src()
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(mod, "fetch_raw", lambda *a, **kw: (None, "timeout after 15s"))

    _src("run_scan")()

    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT error, recognised FROM tender_fetch_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "抓取失敗也要留下一筆紀錄，否則沒有人知道它失敗過"
    assert row["error"], f"抓不到要記下原因，實際 error={row['error']!r}"
    assert row["recognised"] is None, (
        f"抓不到就沒走到解析，recognised 應為 NULL，實際 {row['recognised']!r}。"
        "⚠️ 記成 False 的話，「網站掛了」會被當成「對方改版」——處置完全相反。"
    )


# ── 條件 8／8b：呼叫次數才是觀測點 ─────────────────────────────────────────

def _fetch_counter(monkeypatch, html=HTML_TWO_ROWS):
    """把 `fetch_raw` 換成計數器，回傳那個計數串列。

    ⚠️ 回傳 **tuple**（§3 v2 的新簽名 `-> (html, error)`）。
    """
    mod = _src()
    calls = []

    def _spy(*a, **kw):
        calls.append(a)
        return (html, None)

    monkeypatch.setattr(mod, "fetch_raw", _spy)
    return calls


def test_08_fetch_is_not_called_when_disabled(client, monkeypatch):
    """§3 v2 條件 8：開關關著 → `fetch_raw` 的**呼叫次數 == 0**。

    ⚠️ 觀測點必須是**呼叫本身**，不可以驗「沒有產生任何標案」——
    那在「呼叫了但抓回空的」時也成立。
    **這正是 middleware 那件事：沒產生資料 ≠ 沒被呼叫。**

    它會對外連線，預設就不該是開的。
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", False)

    _src("run_scan")()
    assert len(calls) == 0, (
        f"開關關著，fetch_raw 不該被呼叫，實際 {len(calls)} 次。"
        "『呼叫了但不做事』不算 —— 那還是會對外連線。"
    )


def test_08b_fetch_is_called_when_enabled(client, monkeypatch):
    """§3 v2 條件 8b：開關打開 → **同一個計數器 ≥ 1**。

    ⚠️ **沒有這題，第 8 題是假綠**：若 patch 目標寫錯（呼叫端用 `from ... import`
    把副本複製走了），計數器**永遠是 0**，第 8 題**永遠綠**。

    🔑 **先證明量尺有刻度，再拿它去量。**

    這題紅的話，第一個要查的不是「開關壞了」，而是
    **「`run_scan` 是不是根本沒走模組屬性」**（§3 v2 規定呼叫端要寫
    `tender_source.fetch_raw()`，不要 `from ... import`）。
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)

    _src("run_scan")()
    assert len(calls) >= 1, (
        "開關開著時 fetch_raw 必須真的被呼叫。這題紅的話，第 8 題什麼都沒證明。"
        "⚠️ 先查呼叫端是不是用了 `from tender_source import fetch_raw` —— "
        "那會複製走一份副本，monkeypatch 永遠打不到。"
    )


def test_08c_switch_ships_off_by_default():
    """§3：總開關**出貨預設 `False`**（比照 `LICENSE_GATE_ENABLED`）。

    ⚠️ 讀的是模組的出貨預設值，不是 monkeypatch 之後的值。
    """
    mod = _src()
    _src("TENDER_RADAR_ENABLED")
    assert mod.TENDER_RADAR_ENABLED is False, (
        f"出貨預設值是 {mod.TENDER_RADAR_ENABLED!r}，必須是 False —— "
        "它會對外連線，預設開著等於一上線就開始連對方的網站。"
    )


# ── 條件 9／9b／9c ─────────────────────────────────────────────────────────

def test_09_zero_budget_and_missing_budget_are_distinguishable(client):
    """§3 條件 9：預算「0 元」與「公告沒寫」在資料層要分得開。

    ⚠️ 斷言刻意用 `is None` 與 `== 0`，**不是 `assert not budget`** ——
    後者對兩者都會通過，等於沒有在分辨。

    為什麼要緊：金額區間篩選（條件 4）吃的就是這個欄位。「沒寫」被存成 `0` 的話，
    任何設了下限的 watch 都會**安靜地漏掉**那些標案。
    """
    import db
    cols = _cols("tenders")
    assert "budget" in cols, f"tenders 沒有 budget 欄位；實際 {sorted(cols)}"
    assert cols["budget"]["notnull"] == 0, (
        "tenders.budget 必須允許 NULL —— 『公告沒寫』要存得進去，不可以被迫填 0"
    )
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, budget) VALUES (?,?,?,?)",
                     ("ZERO-001", "零元標案", "某某市政府", 0))
        conn.execute("INSERT INTO tenders (case_no, name, org, budget) VALUES (?,?,?,?)",
                     ("NULL-001", "沒寫預算的標案", "某某市政府", None))
        conn.commit()
        zero = conn.execute("SELECT budget FROM tenders WHERE case_no=?",
                            ("ZERO-001",)).fetchone()["budget"]
        unset = conn.execute("SELECT budget FROM tenders WHERE case_no=?",
                             ("NULL-001",)).fetchone()["budget"]
    finally:
        conn.close()
    assert zero == 0, f"「0 元」要存得住，實際 {zero!r}"
    assert unset is None, f"「公告沒寫」要是 NULL 不是 0，實際 {unset!r}"


def test_09b_fetch_log_records_time_recognised_and_dropped(client, monkeypatch):
    """§3 v2 條件 9b：跑一次抓取後，`tender_fetch_log` 查得到時間＋認不認得＋`dropped`。

    ⚠️ **沒有這題，其他十幾條全綠而這件事完全可能沒做**（B ⑥）——
    而它是「雷達瞎了沒」**唯一**的判斷依據。
    `recognised` 只存在當次記憶體裡的話，沒有人能回答「它上一次認得嗎」。
    """
    mod = _src()
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    _fetch_counter(monkeypatch, html=HTML_ONE_MISSING_FIELD)

    _src("run_scan")()

    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT fetched_at, recognised, dropped FROM tender_fetch_log "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "跑完一次抓取要留下一筆紀錄"
    assert row["fetched_at"], f"要記下時間，實際 {row['fetched_at']!r}"
    assert row["recognised"] == 1, f"這一頁認得出容器，應記成認得，實際 {row['recognised']!r}"
    assert row["dropped"] == 1, f"這一頁丟了一筆，應記成 1，實際 {row['dropped']!r}"


def test_09c_second_run_same_day_makes_no_external_request(client, monkeypatch):
    """§3 v2 條件 9c：**同一天連呼叫兩次，第二次不發出任何外部請求**。

    ⚠️ **沒人驗它就沒人守它，而這一條是對別人的伺服器的承諾，不是對我們自己的**（B ⑦）。
    每日一次是硬上限（§3）；寫了而沒有測試的上限，等於沒有上限。

    用第 8 題那個計數器驗 —— 第二次跑完，計數器仍然是 1。
    """
    mod = _src()
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    calls = _fetch_counter(monkeypatch)

    _src("run_scan")()
    first = len(calls)
    assert first >= 1, "第一次就該真的抓一次，否則這題的觀測點是壞的"

    _src("run_scan")()
    assert len(calls) == first, (
        f"同一天第二次呼叫不該再發外部請求，實際從 {first} 變成 {len(calls)} 次"
    )


# ── 條件 10 ────────────────────────────────────────────────────────────────
#
# 「既有題數不可少於 **1,129**」是⑥的收斂條件，不是一支測試。
# 📌 數字寫死在 §3 v2（第 3 輪結案時 `--collect-only` 算的）。
# ⚠️ A 在 1,034 vs 1,084 那次踩過：**沒寫下來的基準，比對的時候只能靠記憶。**
