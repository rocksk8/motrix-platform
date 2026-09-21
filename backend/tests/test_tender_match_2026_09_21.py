"""2026-09-21 · 第 4 輪：標案雷達第 1～3 步（設條件、抓得到、比對得出命中）

對應 `docs/windows/STATE.md` §3 的 **10 條**驗收條件（1～7、7b、7c、8、9；
第 10 條是⑥的收斂條件，不是一支測試）。

## 🔴 我沒有讀實作

B 還沒寫任何產品碼（`helpers/tender_source.py`／`helpers/tender_match.py`／
`routers/tender_radar.py` 都不存在），所以這一輪的「不讀實作」是自然成立的。
**這是正常的②先於④順序，全紅是預期的起點。**

---

## B 要提供的名字（這份測試釘住的契約）

`backend/helpers/tender_source.py`

| 名字 | 形態 | 來源 |
|------|------|------|
| `TENDER_RADAR_ENABLED` | `bool`，**預設 `False`** | §3 明文（位置比照 `helpers/licensing.py:94`） |
| `fetch_raw(params)` | `-> str` 只拿 HTML，不解析 | §3 明文 |
| `parse_list(html)` | `-> (list[dict], dropped:int, recognised:bool)` | §3 明文 |
| `run_scan()` | 每日掃描的進入點 | ⚠️ **C 取的名字**，見〈給彙整〉 |
| `suspect_redesign(parsed_count, dropped)` | `-> bool` | ⚠️ **C 取的名字**，見〈給彙整〉 |

`backend/helpers/tender_match.py`

| 名字 | 形態 | 來源 |
|------|------|------|
| `match_watches(tender, watches)` | `-> list[dict]` 回命中的 watch | ⚠️ **C 取的名字**，見〈給彙整〉 |

**欄位名一律 snake_case**（`case_no`／`org`／`deadline`／`budget`／`budget_min`…）。
⚠️ 理由：這些是**行程內的純函式參數與資料庫欄位**，不是 API 回應。
第 3 輪的教訓是 **API 命名空間 ≠ 資料庫命名空間**，所以這裡**刻意不套 camelCase**；
若之後有端點要吐這些欄位，那一層才轉 camelCase。

---

## 這一輪最容易寫成假綠燈的三題

1. **7b／7c 必須分開**（§3 明文）。「今天沒標案」與「對方改版整頁認不出來」
   **兩種情況都回 `items=[]`** —— 合成一題的話那題會綠，而什麼都沒驗到。
   `recognised` 要**看結構**（有沒有列表容器／表頭），不能看筆數：
   **「0 筆」正是兩種情況共用的那個值。**
2. **條件 8 必須有對照組**。只驗「關著時沒被呼叫」的話，一個**什麼都不做的
   `run_scan()`** 會完整通過。所以一定要配一題「**開著時真的有被呼叫**」——
   先證明這支探針分得出差別，再拿它去斷言「沒有發生」。
   ⚠️ 這正是 `main.py` 那個 middleware 的形狀：第一行就 return，
   底下幾百行從來沒被執行過，而測試全綠。
3. **條件 9 的 `0` vs `NULL`**。預算「0 元」與「公告沒寫」在畫面上都可能顯示成
   「0」，所以斷言要用 `is None`／`== 0` 分開驗，**不可以寫 `assert not budget`**
   —— 那對兩者都會通過。

---

## ⚠️ HTML 樣本是 C 假定的結構，真實樣本必須取代它

下面那幾個 `HTML_*` 常數是我**照一般政府採購網列表頁的長相假定的**，
因為擷取真實樣本需要連線，而 §3 明文要求「不要連真網站」、總開關也預設關著。

**設計上已經把「樣本」與「斷言」分開**：斷言驗的是語意
（`recognised` 真假、`dropped` 數字、丟掉哪一筆），**不依賴任何特定標籤名**。
⇒ **真實樣本進來時只要換這幾個常數，下面的測試一行都不用改。**

**誰去擷取真實樣本、什麼時候，是 A 要決定的**——見〈給彙整〉第 15 點。
在那之前，6／7／7b／7c 驗到的是「B 的解析器對這個結構的行為」，
**不是「對真實網站的行為」**。
"""
import sqlite3

import pytest


# ── 契約：B 要提供的模組 ─────────────────────────────────────────────────────

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


# ── HTML 樣本（⚠️ C 假定的結構，真實樣本要取代，見檔頭說明）─────────────────

_ROW = (
    "<tr><td>{case_no}</td><td>{name}</td><td>{org}</td>"
    "<td>{deadline}</td><td>{budget}</td></tr>"
)

_HEADER = (
    "<table class='tender_list'>"
    "<tr><th>案號</th><th>標案名稱</th><th>機關</th><th>截止日</th><th>預算金額</th></tr>"
)


def _page(rows):
    return "<html><body>" + _HEADER + "".join(rows) + "</table></body></html>"


HTML_TWO_ROWS = _page([
    _ROW.format(case_no="A-001", name="網路設備採購案", org="某某市政府",
                deadline="2026-10-15", budget="1200000"),
    _ROW.format(case_no="A-002", name="監視系統建置", org="某某縣政府",
                deadline="2026-10-20", budget="800000"),
])

# 有列表容器與表頭，但一筆資料列都沒有 ＝「今天真的沒有新標案」
HTML_EMPTY_LIST = _page([])

# 完全不同的頁面：沒有列表容器 ＝「對方改版／我們瞎了」
HTML_NOT_A_LIST = (
    "<html><body><div class='notice'>系統維護中，造成不便敬請見諒。</div></body></html>"
)

# 兩筆，其中一筆缺「機關」這個必要欄位 → 丟掉那一筆、dropped=1
HTML_ONE_MISSING_FIELD = _page([
    _ROW.format(case_no="B-001", name="完整的標案", org="某某市政府",
                deadline="2026-10-15", budget="500000"),
    _ROW.format(case_no="B-002", name="缺機關的標案", org="",
                deadline="2026-10-16", budget="600000"),
])

# 四筆，三筆缺必要欄位 → dropped=3 > 4/2，應判定為疑似改版
HTML_MOSTLY_DROPPED = _page([
    _ROW.format(case_no="C-001", name="完整的標案", org="某某市政府",
                deadline="2026-10-15", budget="500000"),
    _ROW.format(case_no="", name="缺案號", org="某某市政府",
                deadline="2026-10-16", budget="600000"),
    _ROW.format(case_no="C-003", name="", org="某某市政府",
                deadline="2026-10-17", budget="700000"),
    _ROW.format(case_no="C-004", name="缺截止日", org="某某市政府",
                deadline="", budget="800000"),
])


# ── watch／tender 樣板 ──────────────────────────────────────────────────────

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
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"])
    hits = match_watches(_tender(name="網路設備採購案"), [w])
    assert [h["id"] for h in hits] == [1], f"應該命中，實際 {hits!r}"


def test_01b_keyword_not_in_name_does_not_match():
    """條件 1 的對照組：關鍵字不在標案名裡就不可以命中。

    沒有這一題的話，一個「永遠回全部 watch」的實作會讓條件 1 全綠。
    """
    match_watches = _tm("match_watches")
    hits = match_watches(_tender(name="辦公家具採購"), [_watch(keywords=["網路"])])
    assert hits == [], f"關鍵字沒中就不該命中，實際 {hits!r}"


def test_01c_multiple_keywords_are_or():
    """§3：關鍵字是 OR —— 中任何一個就算。"""
    match_watches = _tm("match_watches")
    w = _watch(keywords=["消防", "監視"])
    assert len(match_watches(_tender(name="監視系統建置"), [w])) == 1


def test_01d_one_tender_can_hit_multiple_watches():
    """§3：一筆標案可命中多個 watch。"""
    match_watches = _tm("match_watches")
    a = _watch(id=1, keywords=["網路"])
    b = _watch(id=2, keywords=["採購"])
    hits = match_watches(_tender(name="網路設備採購案"), [a, b])
    assert sorted(h["id"] for h in hits) == [1, 2], f"應該兩個都中，實際 {hits!r}"


# ── 條件 2：排除詞一中就整筆排除 ───────────────────────────────────────────

def test_02_exclude_word_wins_over_keyword():
    """§3 條件 2：排除詞一中就整筆排除，**即使關鍵字也命中**。

    這題是反向驗證第 1 題的目標，觀測點必須是 `match_watches` 的回傳值。
    """
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"], excludes=["維護"])
    hits = match_watches(_tender(name="網路設備維護案"), [w])
    assert hits == [], (
        f"關鍵字『網路』中了，但排除詞『維護』也中了 → 整筆排除，實際 {hits!r}"
    )


def test_02b_exclude_only_applies_when_present():
    """對照組：排除詞沒中的時候不可以誤殺。

    只有上一題的話，一個「有 excludes 就一律排除」的實作也會全綠。
    """
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"], excludes=["維護"])
    assert len(match_watches(_tender(name="網路設備採購案"), [w])) == 1


# ── 條件 3：機關沒填 ＝ 不篩 ────────────────────────────────────────────────

def test_03_blank_org_means_no_filter_not_zero_results():
    """§3 條件 3：機關沒填 → **不篩**，不是「篩出 0 筆」。

    ⚠️ 跟 `0` vs `null` 同一家族：「沒填」被當成「篩選值是空字串」的話，
    結果是**安靜地一筆都不回**——而那看起來就像「今天沒有符合的標案」。
    """
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"], org=None)
    hits = match_watches(_tender(org="某某市政府"), [w])
    assert len(hits) == 1, f"機關沒填就不該篩掉任何東西，實際 {hits!r}"


def test_03b_org_filter_actually_filters_when_set():
    """對照組：機關有填的時候要真的篩。"""
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"], org="某某市政府")
    assert len(match_watches(_tender(org="某某市政府"), [w])) == 1
    assert match_watches(_tender(org="別的縣政府"), [w]) == []


# ── 條件 4：金額上下限只填一邊 ─────────────────────────────────────────────

@pytest.mark.parametrize("budget_min, budget_max, budget, should_hit", [
    (1_000_000, None, 1_200_000, True),    # 只有下限，超過 → 中
    (1_000_000, None,   800_000, False),   # 只有下限，不足 → 不中
    (None, 1_000_000,   800_000, True),    # 只有上限，低於 → 中
    (None, 1_000_000, 1_200_000, False),   # 只有上限，超過 → 不中
    (None, None,      1_200_000, True),    # 兩邊都沒填 → 不篩
])
def test_04_budget_bounds_filter_only_the_side_that_is_set(
    budget_min, budget_max, budget, should_hit
):
    """§3 條件 4：金額上下限只填一邊 → 只篩那一邊。

    ⚠️ 最後一格（兩邊都沒填）跟條件 3 是同一個陷阱：
    `None` 被當成 `0` 的話，「沒填下限」會變成「下限 0」（剛好無害），
    但「沒填上限」會變成「上限 0」——**一筆都不會中，而且安靜**。
    """
    match_watches = _tm("match_watches")
    w = _watch(keywords=["網路"], budget_min=budget_min, budget_max=budget_max)
    hits = match_watches(_tender(budget=budget), [w])
    assert bool(hits) is should_hit, (
        f"min={budget_min} max={budget_max} budget={budget} → "
        f"預期{'命中' if should_hit else '不中'}，實際 {hits!r}"
    )


# ── 條件 6：必要欄位缺一 → 整筆丟掉且 dropped +1 ───────────────────────────

def test_06_row_missing_required_field_is_dropped_and_counted():
    """§3 條件 6：必要欄位（案號／名稱／機關／截止日）缺一 → 整筆丟掉，`dropped` +1。

    ⚠️ 觀測點要同時看**兩個**：留下來的筆數、以及 `dropped` 的數字。
    只看 `len(items)` 的話，「丟掉了但沒計數」會是綠的——而 `dropped` 正是
    條件 7「疑似改版」判斷的唯一輸入，它不準的話條件 7 跟著失效。
    """
    parse_list = _src("parse_list")
    items, dropped, recognised = parse_list(HTML_ONE_MISSING_FIELD)

    assert recognised is True, "這一頁有列表容器，應該是認得的"
    assert dropped == 1, f"缺機關的那一筆要計入 dropped，實際 dropped={dropped}"
    assert [i["case_no"] for i in items] == ["B-001"], (
        f"只有完整的那一筆該留下，實際 {[i.get('case_no') for i in items]!r}"
    )


def test_06b_complete_page_drops_nothing():
    """對照組：完整的頁面不可以丟掉任何一筆。

    沒有這一題的話，一個「全部都丟掉」的解析器在上一題會是綠的
    （`dropped` 會是 2 不是 1，所以其實抓得到——但留著這題讓失敗訊息更直接）。
    """
    parse_list = _src("parse_list")
    items, dropped, recognised = parse_list(HTML_TWO_ROWS)
    assert recognised is True
    assert dropped == 0, f"這一頁兩筆都完整，不該丟任何一筆，實際 dropped={dropped}"
    assert [i["case_no"] for i in items] == ["A-001", "A-002"]


# ── 條件 7：dropped 超過一半 → 疑似改版旗標 ────────────────────────────────

def test_07_mostly_dropped_raises_suspect_redesign_flag():
    """§3 條件 7：`dropped` 超過當次總數一半 → 回一個「疑似對方改版」的旗標。

    ⚠️ 這一頁**認得出列表容器**（`recognised=True`），所以 7c 那條路徑不會被觸發——
    它是另一種壞法：**版面還在，但每一列的欄位都對不上了**。
    「整頁認不出來」與「認得出來但內容都解不出」要分開，兩者的處置不同。
    """
    parse_list = _src("parse_list")
    suspect_redesign = _src("suspect_redesign")

    items, dropped, recognised = parse_list(HTML_MOSTLY_DROPPED)
    assert recognised is True, "版面還在，應該仍然認得"
    assert dropped == 3, f"四筆裡三筆缺必要欄位，實際 dropped={dropped}"

    assert suspect_redesign(len(items), dropped) is True, (
        f"4 筆裡丟了 3 筆（超過一半）應判定為疑似改版，"
        f"實際 suspect_redesign({len(items)}, {dropped})"
    )


def test_07b_healthy_page_is_not_flagged_as_redesign():
    """對照組：正常的頁面不可以被判成改版。

    ⚠️ 沒有這一題，一個「永遠回 True」的 `suspect_redesign` 會讓上一題全綠，
    而它的後果是**每天都發一次「疑似改版」**——狼來了的告警等於沒有告警。
    """
    parse_list = _src("parse_list")
    suspect_redesign = _src("suspect_redesign")
    items, dropped, _ = parse_list(HTML_TWO_ROWS)
    assert suspect_redesign(len(items), dropped) is False


# ── 條件 7b／7c：recognised 看結構不看筆數（本檔核心）──────────────────────

def test_07b_empty_list_with_container_is_recognised():
    """§3 條件 7b：**有列表容器但零筆** → `recognised=True, items=[]`（今天沒標案）。

    ⚠️ 這一題與下一題**必須分開**（§3 明文）。兩種情況都回 `items=[]`，
    合成一題的話那題會綠，而**什麼都沒驗到**。

    這題是反向驗證第 4 題的目標：把 `recognised` 改成用「筆數 > 0」判定 →
    **這一題必須精準變紅**（因為筆數是 0，但結構是在的）。
    """
    parse_list = _src("parse_list")
    items, dropped, recognised = parse_list(HTML_EMPTY_LIST)

    assert items == [], f"這一頁沒有資料列，items 應為空，實際 {items!r}"
    assert dropped == 0, f"沒有資料列就沒有東西可丟，實際 dropped={dropped}"
    assert recognised is True, (
        "有列表容器與表頭 → 這是『今天真的沒有新標案』，雷達是好的。"
        "⚠️ 若這裡回 False，代表 recognised 是用筆數判定的——"
        "那樣『沒標案』會被誤報成『它瞎了』，每天都發一次假警報。"
    )


def test_07c_page_without_list_container_is_not_recognised():
    """§3 條件 7c：**完全不同的頁面（沒有列表容器）** → `recognised=False`（它瞎了）。

    ⚠️ 這條線的價值是「不會漏掉標案」，**瞎掉正好是它唯一不能發生的事**。
    而失敗的那一側完全無聲：雷達安靜下來，沒有人知道是因為沒標案還是因為它瞎了。
    **壞掉會被報修，安靜地少做一件事不會。**
    """
    parse_list = _src("parse_list")
    items, dropped, recognised = parse_list(HTML_NOT_A_LIST)

    assert recognised is False, (
        "這一頁沒有列表容器（是維護中的公告頁），應判定為『認不得』。"
        "⚠️ 若這裡回 True，代表整頁改版不會被發現——雷達會安靜地永遠回 0 筆。"
    )
    assert items == [], f"認不得的頁面不該生出任何資料，實際 {items!r}"


# ── 條件 8：總開關關著時，抓取函式不會被呼叫 ───────────────────────────────

def test_08_scan_does_not_call_fetch_when_disabled(monkeypatch):
    """§3 條件 8：`TENDER_RADAR_ENABLED = False` 時，**連呼叫都不該發生**。

    ⚠️ 它會對外連線，預設就不該是開的。

    這題的形狀就是 `main.py` 那個授權 middleware：第一行 `if not ...: return`，
    底下幾百行從來沒有被任何測試執行過，而測試全綠
    （本輪之前 `grep -rn "LICENSE_GATE_ENABLED" backend/tests/` 是零命中）。
    """
    mod = _src()
    run_scan = _src("run_scan")
    _src("fetch_raw")

    calls = []
    monkeypatch.setattr(mod, "fetch_raw", lambda *a, **kw: calls.append(a) or "")
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", False)

    run_scan()
    assert calls == [], (
        f"總開關關著，fetch_raw 不該被呼叫，實際被呼叫 {len(calls)} 次。"
        "『呼叫了但不做事』不算——那還是會對外連線。"
    )


def test_08b_scan_does_call_fetch_when_enabled(monkeypatch):
    """⚠️ **條件 8 的對照組，沒有它上一題毫無意義。**

    只驗「關著時沒被呼叫」的話，一個**什麼都不做的 `run_scan()`** 會完整通過。
    先證明這支探針分得出差別，再拿它去斷言「沒有發生」——
    這跟「驗資料集之前先確認量尺分得出東西」是同一條。
    """
    mod = _src()
    run_scan = _src("run_scan")

    calls = []
    monkeypatch.setattr(mod, "fetch_raw", lambda *a, **kw: calls.append(a) or HTML_TWO_ROWS)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)

    run_scan()
    assert calls, (
        "總開關開著時 fetch_raw 必須真的被呼叫。"
        "這一題紅的話，上一題（關著時沒被呼叫）就什麼都沒證明。"
    )


def test_08c_switch_ships_off_by_default():
    """§3：總開關**預設 `False`**（比照 `LICENSE_GATE_ENABLED`）。

    ⚠️ 讀的是模組的出貨預設值，不是 monkeypatch 之後的值。
    """
    mod = _src()
    _src("TENDER_RADAR_ENABLED")
    assert mod.TENDER_RADAR_ENABLED is False, (
        f"TENDER_RADAR_ENABLED 的出貨預設值是 {mod.TENDER_RADAR_ENABLED!r}，必須是 False。"
        "它會對外連線，預設開著等於一上線就開始連對方的網站。"
    )


# ── 條件 5：同案號去重（資料層）────────────────────────────────────────────

def _table_columns(table):
    import db
    conn = db.get_db()
    try:
        return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


@pytest.mark.parametrize("table", ["tender_watches", "tenders", "tender_hits"])
def test_05_tables_exist(client, table):
    """§3：三張新表要存在。"""
    cols = _table_columns(table)
    assert cols, f"資料表 {table} 不存在（B 的 migration 還沒做）"


def test_05b_same_case_no_cannot_be_inserted_twice(client):
    """§3 條件 5：同一筆標案（同案號）被抓兩次 → `tenders` 只有一列。

    ⚠️ 驗的是**資料庫的唯一鍵**，不是寫入函式有沒有先查再寫：
    「先 SELECT 再 INSERT」在兩次抓取重疊時仍然會插進兩列，
    而唯一鍵是唯一一個在任何情況下都成立的保證。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, deadline) VALUES (?,?,?,?)",
            ("DUP-001", "重複的標案", "某某市政府", "2026-10-15"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, deadline) VALUES (?,?,?,?)",
                ("DUP-001", "重複的標案（第二次抓到）", "某某市政府", "2026-10-15"),
            )
            conn.commit()
    finally:
        conn.close()


def test_05c_same_watch_tender_pair_cannot_be_recorded_twice(client):
    """§3 條件 5 後半：`tender_hits` 不重複（同一個 watch 對同一筆標案只能有一列）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, deadline) VALUES (?,?,?,?)",
            ("HIT-001", "標案", "某某市政府", "2026-10-15"),
        )
        conn.execute(
            "INSERT INTO tender_watches (name, keywords) VALUES (?,?)",
            ("條件一", "網路"),
        )
        conn.commit()
        tid = conn.execute(
            "SELECT id FROM tenders WHERE case_no=?", ("HIT-001",)).fetchone()["id"]
        wid = conn.execute(
            "SELECT id FROM tender_watches WHERE name=?", ("條件一",)).fetchone()["id"]

        conn.execute(
            "INSERT INTO tender_hits (watch_id, tender_id) VALUES (?,?)", (wid, tid))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tender_hits (watch_id, tender_id) VALUES (?,?)", (wid, tid))
            conn.commit()
    finally:
        conn.close()


# ── 條件 9：預算 0 元 vs 公告沒寫 ──────────────────────────────────────────

def test_09_zero_budget_and_missing_budget_are_distinguishable(client):
    """§3 條件 9：預算「0 元」與「公告沒寫」在資料層要分得開。

    ⚠️ 斷言刻意寫成 `is None` 與 `== 0`，**不是 `assert not budget`** ——
    後者對兩者都會通過，等於沒有在分辨。

    為什麼要緊：金額區間篩選（條件 4）吃的就是這個欄位。
    「沒寫」被存成 `0` 的話，任何設了下限的 watch 都會**安靜地漏掉**那些標案，
    而那正是這條線唯一不能發生的事。
    """
    import db
    cols = _table_columns("tenders")
    assert "budget" in cols, f"tenders 沒有 budget 欄位；實際 {sorted(cols)}"
    assert cols["budget"]["notnull"] == 0, (
        "tenders.budget 必須允許 NULL —— 『公告沒寫』要存得進去，"
        "不可以被迫填 0"
    )

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, deadline, budget) VALUES (?,?,?,?,?)",
            ("ZERO-001", "零元標案", "某某市政府", "2026-10-15", 0),
        )
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, deadline, budget) VALUES (?,?,?,?,?)",
            ("NULL-001", "沒寫預算的標案", "某某市政府", "2026-10-15", None),
        )
        conn.commit()
        zero = conn.execute(
            "SELECT budget FROM tenders WHERE case_no=?", ("ZERO-001",)).fetchone()["budget"]
        unset = conn.execute(
            "SELECT budget FROM tenders WHERE case_no=?", ("NULL-001",)).fetchone()["budget"]
    finally:
        conn.close()

    assert zero == 0, f"「0 元」要存得住，實際 {zero!r}"
    assert unset is None, f"「公告沒寫」要是 NULL 不是 0，實際 {unset!r}"
    assert zero is not unset, "0 與 NULL 必須是可分辨的兩個值"


# ── 條件 10 ────────────────────────────────────────────────────────────────
#
# 「既有題數不可少於上一輪」是⑥的收斂條件，不是一支測試。
# 上一輪 1,129，結果寫在 docs/windows/C.md。
