"""2026-09-21 · 第 4 輪：標案雷達第 1～3 步（設條件、抓得到、比對得出命中）

對應 `docs/windows/STATE.md` §3 **`5a866e4`** 版的 **34 條**驗收條件。
（照協定 §5l 記下 SHA —— 沒有版本號的「我照單寫了」，等於沒說照的是哪一張。）

## 🔴 我沒有讀解析器

B 還沒寫任何產品碼（`helpers/tender_source.py`／`helpers/tender_match.py`／
`routers/tender_radar.py` 都不存在），所以「不讀實作」自然成立。
**我讀的是 `fixtures/tender_list_20260921.html`（測試資料，我的領域），不是解析器。**

## 🔴 所有 HTML 樣本都是從真實 fixture 切出來的，不是手寫的

第一版我手寫了假定結構的 HTML。真實樣本到位之後全部改成**對 fixture 做外科手術**
（挖掉資料列、清空某一格、把兩格對調…），每一個手術都有 `assert` 守門：
**`str.replace` 對不上是靜默無效的，而「樣本沒被改到」跟「解析器沒問題」長得一模一樣。**

⚠️ 手寫樣本的問題不是「不像」，是**它會把我對結構的誤解變成測試的前提** ——
然後解析器照著我的誤解寫，兩邊一致而且全綠，直到上正式機。

## 這個網站真實的四件事（我掃 fixture 得到的，已寫進 §3）

| 事實 | 為什麼要緊 |
|---|---|
| `截止投標`／`預算金額` 在原始 HTML 出現 **0 次** | 被標籤與 `&emsp;` 切開。`recognised` 要先 strip tags → unescape → **去掉所有空白**再比 |
| **標案名稱是 `<script>` 裡 `pageCode2Img("…")` 的引數** | naive strip tags 會得到一行 JavaScript，**而真名是它的子字串** ⇒ 關鍵字照樣命中、條件 1 照樣綠 |
| 查詢表單 `tb_03c` **也含**「機關名稱」「標案案號」 | 所以要**四個字樣同時**出現才算認得（表單頁沒有後兩個） |
| 結果表 `id="tpam"` 共 6 個 `<tr>` ＝ 1 表頭 ＋ **5 筆資料** | 全頁 29 個 `<tr>`，解析器不可以掃全部 `<tr>` |

## 三種（其實四種）壞法不能互相蓋掉

| 壞法 | 該長什麼樣 | 為什麼容易被合併 |
|---|---|---|
| 今天真的沒標案 | `recognised=True, items=[]` | |
| 對方改版整頁認不出 | `recognised=False` | **跟上面一樣是 `items=[]`** |
| 網站掛了／403／逾時 | 記成「抓不到」 | 空字串 → 也找不到容器 → 也是 `recognised=False` |
| **欄序對調／名稱是 JS** | 該筆丟掉或正確拆出 | ⚠️ **每個訊號都綠而資料全錯** |

前三種是「雷達安靜」，**後一種是雷達報錯的東西而且看起來很正常。**
"""
import html as _html
import re
import sqlite3
from pathlib import Path

import pytest

from tests._timefreeze import freeze_slot


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
            f"backend/helpers/tender_source.py 還不存在（或 import 失敗）：{_SRC_ERR}"
        )
    if name and not hasattr(src, name):
        raise AssertionError(f"helpers/tender_source.py 缺少 `{name}`")
    return getattr(src, name) if name else src


def _tm(name=None):
    if tmatch is None:
        raise AssertionError(
            f"backend/helpers/tender_match.py 還不存在（或 import 失敗）：{_MATCH_ERR}"
        )
    if name and not hasattr(tmatch, name):
        raise AssertionError(f"helpers/tender_match.py 缺少 `{name}`")
    return getattr(tmatch, name) if name else tmatch


# ── 從真實 fixture 切樣本（每一刀都有 assert 守門）──────────────────────────

FIXTURE = Path(__file__).parent / "fixtures" / "tender_list_20260921.html"

_RESULT_TABLE = re.compile(r'<table[^>]*id="tpam"[^>]*>.*?</table\s*>', re.S | re.I)
_TR = re.compile(r"<tr.*?</tr\s*>", re.S | re.I)
_TD = re.compile(r"<td[^>]*>(.*?)</td\s*>", re.S | re.I)

# 結果表的欄位順序（我從 fixture 的表頭讀出來的，不是猜的）
COL_SEQ, COL_ORG, COL_CASE_NAME = 0, 1, 2
COL_PUBLISHED, COL_DEADLINE, COL_BUDGET = 6, 7, 8
N_COLS = 10
N_DATA_ROWS = 5


def _real_html():
    return FIXTURE.read_text(encoding="utf-8")


def _split_results(page, expect_rows=None):
    """回 (table_match, header_row, data_rows)。對不上就當場爆掉。

    ⚠️ `expect_rows` 只在切原始 fixture 時給 —— 這支函式也會被用在
    「已經動過手術」的樣本上，那些樣本的列數本來就不是 5。
    """
    m = _RESULT_TABLE.search(page)
    assert m, "fixture 裡找不到結果表 id='tpam' —— 樣本換過了，這份測試要跟著更新"
    rows = _TR.findall(m.group())
    if expect_rows is not None:
        assert len(rows) == expect_rows, (
            f"結果表應為 {expect_rows} 列，實際 {len(rows)} 列"
        )
    return m, rows[0], rows[1:]


def _rebuild(page, rows):
    """把結果表的列換成 `rows`，其餘頁面原封不動。"""
    m, header, data = _split_results(page)
    tbl = m.group()
    first, last = data[0], data[-1]
    head = tbl[: tbl.index(first)]
    tail = tbl[tbl.rindex(last) + len(last):]
    return page[: m.start()] + head + "".join(rows) + tail + page[m.end():]


def _set_cell(row, idx, inner):
    """把某一格的內容換掉。格數對不上就爆掉。"""
    tds = list(_TD.finditer(row))
    assert len(tds) == N_COLS, f"資料列應有 {N_COLS} 格，實際 {len(tds)}"
    t = tds[idx]
    return row[: t.start(1)] + inner + row[t.end(1):]


def _get_cell(row, idx):
    tds = list(_TD.finditer(row))
    assert len(tds) == N_COLS, f"資料列應有 {N_COLS} 格，實際 {len(tds)}"
    return tds[idx].group(1)


def _swap_cells(row, i, j):
    a, b = _get_cell(row, i), _get_cell(row, j)
    assert a != b, "要對調的兩格內容一樣，這個手術等於沒做"
    return _set_cell(_set_cell(row, i, b), j, a)


REAL = _real_html()
_M, _HEADER, _DATA = _split_results(REAL, expect_rows=1 + N_DATA_ROWS)
ROW0 = _DATA[0]

# 條件 7b：有容器、零筆資料 ＝「今天真的沒有新標案」
HTML_EMPTY_RESULTS = _rebuild(REAL, [])

# 條件 7e：查詢表單頁（保留表單，砍掉整張結果表）—— 它**也有 `<table>`**
HTML_FORM_ONLY = REAL[: _M.start()] + "</body></html>"

# 條件 7c：完全不同的頁面（連表單都沒有）
HTML_NOT_A_LIST = "<html><body><div class='notice'>系統維護中。</div></body></html>"

# 只留第一筆（乾淨的基準）
HTML_ONE_GOOD = _rebuild(REAL, [ROW0])

# 條件 6：缺機關
HTML_MISSING_ORG = _rebuild(REAL, [_set_cell(ROW0, COL_ORG, "")] + _DATA[1:])
# 條件 6f：案號與名稱那一格整格空掉
HTML_MISSING_CASE_NAME = _rebuild(
    REAL, [_set_cell(ROW0, COL_CASE_NAME, "")] + _DATA[1:])
# 條件 6b：沒有截止日 —— 仍然要收下
HTML_NO_DEADLINE = _rebuild(REAL, [_set_cell(ROW0, COL_DEADLINE, "")] + _DATA[1:])
# 條件 6g：預算空白 → None（不是 0）
HTML_NO_BUDGET = _rebuild(REAL, [_set_cell(ROW0, COL_BUDGET, "")] + _DATA[1:])
# 條件 6c：形狀驗證**是三道獨立檢查**（我在第 4 輪⑤除錯突變時黑箱探測出來的），
# 所以 R2（第 5 輪結轉）把它拆成三個樣本、三題，各破壞一道。
#
# ⚠️ 原本一題涵蓋三道，**那是⑤自己的假綠燈**：下一個人合併掉兩道時，
# 第 5 個突變仍然會紅（還剩一道），看起來完全正常。
# 一道也是紅、三道也是紅，**中間少掉兩道沒有任何訊號**。
HTML_ORG_NOT_CJK = _rebuild(           # ① 機關那格要含中文
    REAL, [_set_cell(ROW0, COL_ORG, "ABC Agency")] + _DATA[1:])
HTML_ORG_LOOKS_LIKE_DATE = _rebuild(   # ② 機關那格不可以長得像日期
    REAL, [_set_cell(ROW0, COL_ORG, "115/09/30")] + _DATA[1:])
HTML_DEADLINE_NOT_A_DATE = _rebuild(   # ③ 截止日非空時要解得出日期
    REAL, [_set_cell(ROW0, COL_DEADLINE, "衛生福利部桃園醫院")] + _DATA[1:])
# 真實情境（兩欄對調）會同時撞到 ②③——留著當整合樣本，但斷言由上面三題各自負責
HTML_TRANSPOSED = _rebuild(
    REAL, [_swap_cells(ROW0, COL_ORG, COL_DEADLINE)] + _DATA[1:])
# 條件 6e：截止日早於公告日（公告 115/09/21，截止設成 105/01/01）
HTML_DEADLINE_BEFORE_PUBLISHED = _rebuild(
    REAL, [_set_cell(ROW0, COL_DEADLINE, "105/01/01")] + _DATA[1:])
# 條件 6e：距今超過 ±5 年
HTML_DEADLINE_FAR_FUTURE = _rebuild(
    REAL, [_set_cell(ROW0, COL_DEADLINE, "199/12/31")] + _DATA[1:])
# 條件 7：5 筆裡 3 筆缺機關 → dropped 3 > 2.5
HTML_MOSTLY_DROPPED = _rebuild(REAL, [
    _DATA[0],
    _set_cell(_DATA[1], COL_ORG, ""),
    _set_cell(_DATA[2], COL_ORG, ""),
    _set_cell(_DATA[3], COL_ORG, ""),
    _DATA[4],
])


def _expected_name(row):
    """從 fixture 直接讀出那一筆的真名（`pageCode2Img("…")` 的引數）。

    ⚠️ 這是**測試自己**從樣本讀的，跟解析器無關 —— 我沒有讀解析器。
    """
    m = re.search(r'pageCode2Img\("([^"]+)"\)', row)
    assert m, "這一列的名稱不是用 pageCode2Img 產生的，樣本結構變了"
    return _html.unescape(m.group(1))


EXPECTED_NAME_0 = _expected_name(ROW0)


def _watch(**over):
    w = {"id": 1, "name": "預設條件", "keywords": ["監視"], "excludes": [],
         "org": None, "budget_min": None, "budget_max": None, "enabled": 1}
    w.update(over)
    return w


def _tender(**over):
    t = {"case_no": "TYGH115152", "name": EXPECTED_NAME_0,
         "org": "衛生福利部桃園醫院", "deadline": "2026-09-30",
         "budget": 2_433_600, "url": "https://example.invalid/t/1"}
    t.update(over)
    return t


# ── 樣本本身的守門（這幾題不碰產品碼，它們保護的是上面那些手術）─────────────

def test_00_fixture_is_the_real_bytes():
    """fixture 必須是對方網站當時真正送來的位元組。

    ⚠️ `.gitattributes` 的 `*.html text eol=lf` 會把它正規化（90,207 → 88,622 bytes、
    CRLF 1,585 → 0）。`fixtures/** -text` 擋住了這件事，這題是那條規則的迴歸鎖。
    **正規化過的樣本不是現實，是現實的正規化版** —— 而那正好打掉它存在的理由。
    """
    raw = FIXTURE.read_bytes()
    crlf = raw.count(b"\r\n")
    assert len(raw) == 90_207, f"fixture 大小變了：{len(raw)}（原始 90,207）"
    assert crlf == 1_585, (
        f"fixture 的 CRLF 剩 {crlf} 處（原始 1,585）—— "
        "被正規化了，檢查 .gitattributes 的 fixtures/** -text"
    )


def test_00b_surgery_actually_changes_the_sample():
    """對照組：確認那些「手術」真的改到了東西。

    ⚠️ **沒有這題，所有切出來的樣本都可能跟原樣一模一樣** ——
    而「樣本沒被改到」跟「解析器把它處理對了」長得一模一樣。
    """
    assert HTML_EMPTY_RESULTS != REAL
    assert HTML_MISSING_ORG != REAL
    assert HTML_TRANSPOSED != REAL
    assert len(_TR.findall(_RESULT_TABLE.search(HTML_EMPTY_RESULTS).group())) == 1, (
        "挖空之後結果表應該只剩表頭"
    )
    missing_rows = _split_results(HTML_MISSING_ORG)[2]
    assert len(missing_rows) == N_DATA_ROWS, (
        f"清空一格不該改變列數，實際 {len(missing_rows)} 列 —— "
        "手術把其餘幾列一起砍掉了"
    )
    assert "衛生福利部桃園醫院" not in _get_cell(missing_rows[0], COL_ORG), (
        "機關那一格沒有被清空"
    )


def test_00c_form_page_still_contains_a_table():
    """條件 7e 的前提：查詢表單頁**確實有 `<table>`**，所以「找得到 table」判不出東西。"""
    assert re.search(r"<table", HTML_FORM_ONLY, re.I), (
        "表單頁沒有 table 的話，7e 就驗不到它要驗的東西了"
    )
    assert "機關名稱" in HTML_FORM_ONLY, "表單頁應該含『機關名稱』（欄位標籤）"
    assert 'id="tpam"' not in HTML_FORM_ONLY, "表單頁不該含結果表"


# ── 條件 1～4：比對純函式 ───────────────────────────────────────────────────

def test_01_keyword_in_name_matches():
    """§3 條件 1：標案名含關鍵字 → 命中。"""
    hits = _tm("match_watches")(_tender(), [_watch(keywords=["監視"])])
    assert [h["id"] for h in hits] == [1], f"應該命中，實際 {hits!r}"


def test_01b_keyword_not_in_name_does_not_match():
    """對照組：關鍵字沒中就不可以命中（否則「永遠回全部」也會綠）。"""
    assert _tm("match_watches")(_tender(name="辦公家具採購"),
                                [_watch(keywords=["監視"])]) == []


def test_01c_multiple_keywords_are_or():
    """§3：關鍵字是 OR。"""
    assert len(_tm("match_watches")(_tender(), [_watch(keywords=["消防", "監視"])])) == 1


def test_01d_one_tender_can_hit_multiple_watches():
    """§3：一筆標案可命中多個 watch。"""
    hits = _tm("match_watches")(_tender(), [_watch(id=1, keywords=["監視"]),
                                            _watch(id=2, keywords=["麻醉"])])
    assert sorted(h["id"] for h in hits) == [1, 2], f"兩個都該中，實際 {hits!r}"


def test_02_exclude_word_wins_over_keyword():
    """§3 條件 2：排除詞一中就整筆排除，**即使關鍵字也命中**。"""
    hits = _tm("match_watches")(_tender(name="監視系統維護案"),
                                [_watch(keywords=["監視"], excludes=["維護"])])
    assert hits == [], f"排除詞中了就整筆排除，實際 {hits!r}"


def test_02b_exclude_only_applies_when_present():
    """對照組：排除詞沒中不可以誤殺。"""
    assert len(_tm("match_watches")(
        _tender(), [_watch(keywords=["監視"], excludes=["維護"])])) == 1


def test_03_blank_org_means_no_filter():
    """§3 條件 3：機關沒填 → **不篩**（不是篩出 0 筆）。"""
    assert len(_tm("match_watches")(_tender(), [_watch(org=None)])) == 1


def test_03b_org_filter_actually_filters_when_set():
    """對照組：機關有填就要真的篩。"""
    w = _watch(org="衛生福利部桃園醫院")
    assert len(_tm("match_watches")(_tender(), [w])) == 1
    assert _tm("match_watches")(_tender(org="別的縣政府"), [w]) == []


@pytest.mark.parametrize("bmin, bmax, budget, hit", [
    (2_000_000, None, 2_433_600, True),
    (3_000_000, None, 2_433_600, False),
    (None, 3_000_000, 2_433_600, True),
    (None, 2_000_000, 2_433_600, False),
    (None, None,      2_433_600, True),
])
def test_04_budget_bounds_filter_only_the_side_that_is_set(bmin, bmax, budget, hit):
    """§3 條件 4：上下限只填一邊 → 只篩那一邊。

    ⚠️ 最後一格：`None` 被當成 `0` 的話，「沒填上限」會變「上限 0」
    —— **一筆都不會中，而且安靜**。
    """
    hits = _tm("match_watches")(_tender(budget=budget),
                                [_watch(budget_min=bmin, budget_max=bmax)])
    assert bool(hits) is hit, f"min={bmin} max={bmax} budget={budget} → 實際 {hits!r}"


# ── 條件 5／5b：去重的兩個方向 ─────────────────────────────────────────────

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
    """§3：四張新表要存在。"""
    assert _cols(table), f"資料表 {table} 不存在（B 的 migration 還沒做）"


def test_05b_same_org_and_case_no_cannot_be_inserted_twice(client):
    """§3 條件 5：**同機關同案號**被抓兩次 → 只有一列。

    ⚠️ 驗的是資料庫唯一鍵，不是「先 SELECT 再 INSERT」——
    後者在兩次抓取重疊時仍然會插進兩列。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("DUP-001", "重複的標案", "某某市政府"))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                         ("DUP-001", "第二次抓到", "某某市政府"))
            conn.commit()
    finally:
        conn.close()


def test_05c_same_case_no_different_org_is_allowed(client):
    """§3 條件 5b：案號相同但**機關不同** → 兩列都要留下。

    ⚠️ 只驗上一題的話，一個「唯一鍵只有 `case_no`」的實作會**完整通過**
    —— 那正是要被防掉的那個實作。
    🔑 **驗去重要兩個方向：該併的有併、該分的有分。**
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
    assert n == 2, f"同案號不同機關是兩筆不同的標案，實際只剩 {n} 筆"


def test_05d_same_watch_tender_pair_cannot_be_recorded_twice(client):
    """§3 條件 5 後半：`tender_hits` 不重複。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
                     ("HIT-001", "標案", "某某市政府"))
        conn.execute("INSERT INTO tender_watches (name, keywords) VALUES (?,?)",
                     ("條件一", "監視"))
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


# ── 解析：真實樣本 ─────────────────────────────────────────────────────────

def test_06_real_sample_parses_five_rows_cleanly():
    """真實樣本應該解出 **5 筆**、`dropped=0`、`recognised=True`。

    ⚠️ 全頁有 **29** 個 `<tr>`，結果表只有 6 個（1 表頭 ＋ 5 資料）——
    掃全部 `<tr>` 的解析器會把查詢表單的列也當成標案。
    """
    items, dropped, recognised = _src("parse_list")(REAL)
    assert recognised is True, "真實結果頁必須認得"
    assert dropped == 0, f"真實樣本每一筆都完整，不該丟，實際 dropped={dropped}"
    assert len(items) == N_DATA_ROWS, (
        f"應解出 {N_DATA_ROWS} 筆，實際 {len(items)} 筆 —— "
        "多於 5 筆多半是掃了查詢表單的 <tr>"
    )


def test_06b_missing_required_field_is_dropped_and_counted():
    """§3 條件 6：必要欄位（案號／名稱／**機關**）缺一 → 整筆丟掉且 `dropped` +1。"""
    items, dropped, recognised = _src("parse_list")(HTML_MISSING_ORG)
    assert recognised is True
    assert dropped == 1, f"缺機關那筆要計入 dropped，實際 {dropped}"
    assert len(items) == N_DATA_ROWS - 1, f"應少一筆，實際 {len(items)}"


def test_06c_missing_case_and_name_cell_is_dropped():
    """§3 條件 6f：案號與名稱在同一格，任一為空 → 整筆丟掉。"""
    items, dropped, _ = _src("parse_list")(HTML_MISSING_CASE_NAME)
    assert dropped == 1, f"案號與名稱那格空了，該筆要丟掉，實際 dropped={dropped}"
    assert len(items) == N_DATA_ROWS - 1


def test_06d_missing_deadline_is_accepted_as_none():
    """§3 條件 6b：**沒有截止日仍然收下**，`deadline` 是 `None`。

    ⚠️ 把它算成解析失敗會**污染 `dropped > 一半` 的訊號** ——
    那個訊號是用來判斷「對方是不是改版了」的，被正常資料灌水之後會誤報，
    而誤報的告警很快會被當成雜訊。**一個壞掉的欄位定義，會讓一個跟它無關的告警失效。**
    """
    items, dropped, _ = _src("parse_list")(HTML_NO_DEADLINE)
    assert dropped == 0, f"沒有截止日不算解析失敗，實際 dropped={dropped}"
    assert len(items) == N_DATA_ROWS
    first = items[0]
    assert first["deadline"] is None, (
        f"沒寫截止日要是 None，實際 {first['deadline']!r}（空字串會讓下游分不出）"
    )


def test_06e_roc_date_is_converted_to_western():
    """§3 條件 6d：民國年 `115/09/30` → `2026-09-30`。

    ⚠️ B 查證過：`date(115, 9, 30)` 是**合法物件、不丟例外**，距今約 -697,970 天，
    會被「早就截止」的篩選**安靜濾掉** —— 整批標案消失，而
    `dropped=0`／`recognised=True`／每個訊號都綠。
    """
    items, _, _ = _src("parse_list")(REAL)
    first = next(i for i in items if i["case_no"] == "TYGH115152")
    assert first["deadline"] == "2026-09-30", (
        f"115/09/30 應轉成 2026-09-30，實際 {first['deadline']!r}"
    )
    assert first["published_at"] == "2026-09-21", (
        f"115/09/21 應轉成 2026-09-21，實際 {first.get('published_at')!r}"
    )
    # ⚠️ R1（第 5 輪結轉）：鍵名從 `published` 改成 `published_at`。
    # 三種拼法橫跨三層——解析 dict／DB 欄／API 與前端。DB 是 `published_at`，
    # 而解析 dict 跟 DB insert 在相鄰兩行、中間沒有轉換層，所以兩邊要一致；
    # API 那層的 `publishedAt` 保留（跨邊界用 camelCase，leadTimeDays 那次已定案）。
    assert "published" not in first, (
        "舊鍵 `published` 還在——兩個鍵並存的話，下游讀到哪一個是看運氣"
    )


@pytest.mark.parametrize("label", ["deadline_before_published", "far_out_of_range"])
def test_06f_out_of_range_dates_are_dropped(label):
    """§3 條件 6e：**上界檢查** —— 截止日早於公告日、或距今超過 ±5 年 → 丟掉。

    🔑 這個上界是**這一類錯誤的通用網子，不只接民國年**：
    任何把日期算歪的 bug（時區、世紀、格式）都會掉進來。
    """
    page = {"deadline_before_published": HTML_DEADLINE_BEFORE_PUBLISHED,
            "far_out_of_range": HTML_DEADLINE_FAR_FUTURE}[label]
    items, dropped, _ = _src("parse_list")(page)
    assert dropped == 1, f"[{label}] 該筆要當解析失敗丟掉，實際 dropped={dropped}"
    assert len(items) == N_DATA_ROWS - 1


def test_06g_budget_thousands_separator_is_parsed():
    """§3 條件 6g：`2,433,600` → `2433600`。"""
    items, _, _ = _src("parse_list")(REAL)
    first = next(i for i in items if i["case_no"] == "TYGH115152")
    assert first["budget"] == 2_433_600, (
        f"千分位逗號要去掉並轉成整數，實際 {first['budget']!r}"
    )


def test_06h_blank_budget_is_none_not_zero():
    """§3 條件 6g 後半：預算空白 → `None` **不是 `0`**。

    ⚠️ 金額區間篩選吃的就是這個欄位。「沒寫」存成 `0` 的話，
    任何設了下限的 watch 都會**安靜地漏掉**那些標案。
    """
    items, dropped, _ = _src("parse_list")(HTML_NO_BUDGET)
    assert dropped == 0, "沒寫預算不算解析失敗"
    first = items[0]
    assert first["budget"] is None, f"空白預算要是 None，實際 {first['budget']!r}"
    assert first["budget"] != 0


def test_06i_name_is_the_javascript_argument_not_the_script_text():
    """§3 條件 6h：`name` 要**等於** `pageCode2Img("…")` 的引數。

    ⚠️⚠️ **這題是本檔最容易被誤以為已經通過的一題。**
    標案名稱不是文字節點，是 `<script>` 裡一個函式呼叫的字串引數：

        <script>var hw = Geps3.CNS.pageCode2Img("麻醉部-麻醉深度監視系統傳感器採購案");…</script>

    naive strip tags 會得到整行 JavaScript，**而真名是那串垃圾的子字串** ⇒
    - 條件 1（關鍵字「監視」命中）**照樣綠**
    - 「案號與名稱都非空」**照樣綠**
    - **而資料庫裡每一筆標案名稱都是一行 JavaScript**

    所以這裡驗的是**相等**，不是「包含」，並且明確否定那三個 JS 字樣。
    """
    items, _, _ = _src("parse_list")(REAL)
    first = next(i for i in items if i["case_no"] == "TYGH115152")
    name = first["name"]

    for bad in ("Geps3", "var hw", "pageCode2Img", "$(", "</script>"):
        assert bad not in name, (
            f"name 裡出現 `{bad}` —— 解析器是直接 strip tags 的。"
            f"實際 name={name[:90]!r}"
        )
    assert name == EXPECTED_NAME_0, (
        f"name 應等於 pageCode2Img 的引數 {EXPECTED_NAME_0!r}，實際 {name!r}"
    )
    assert first["case_no"] == "TYGH115152", (
        f"案號要從同一格拆出來，實際 {first['case_no']!r}"
    )


# ⚠️ 只用短 label 當參數，**不要把 HTML 當參數** —— pytest 會把整頁塞進測試 ID，
# 輸出會變成幾百 KB。這個檔今天已經踩過一次（`test_06f`），這裡是第二次。
_SHAPE_CASES = {
    "org_not_cjk":       ("① 機關要含中文",            lambda: HTML_ORG_NOT_CJK),
    "org_looks_like_date": ("② 機關不可以長得像日期",  lambda: HTML_ORG_LOOKS_LIKE_DATE),
    "deadline_not_a_date": ("③ 截止日非空要解得出日期", lambda: HTML_DEADLINE_NOT_A_DATE),
}


@pytest.mark.parametrize("label", list(_SHAPE_CASES))
def test_06j_each_shape_check_drops_its_own_row(label):
    """§3 條件 6c（R2 拆成三題）：形狀驗證的**每一道**都要各自擋得住。

    ⚠️⚠️ **原本這是一題涵蓋三道，那是⑤自己的假綠燈**（視窗 B 指出）：
    下一個人若覺得三行重複而合併掉兩道，**⑤的第 5 個突變仍然會紅（還剩一道），
    看起來完全正常**。一道也是紅、三道也是紅，**中間少掉兩道沒有任何訊號**。

    🔑 三道檢查正是我在第 4 輪⑤除錯突變時黑箱探測出來的 ——
    我把發現寫成了知識，卻沒有當場把它變成守門。這三題就是那個補救。
    """
    which, page_of = _SHAPE_CASES[label]
    items, dropped, recognised = _src("parse_list")(page_of())
    assert recognised is True, f"[{label}] 容器還在，不是『認不得』那種壞法"
    assert dropped == 1, (
        f"[{label}] 形狀檢查「{which}」該擋下這一列，實際 dropped={dropped}"
    )
    assert len(items) == N_DATA_ROWS - 1


def test_06j_transposed_row_is_dropped():
    """真實情境：兩欄對調。它**同時**撞到 ②③，所以只驗「有被丟掉」。

    ⚠️ 必要欄位**全都在**、容器也找得到 —— **每個訊號都綠而資料全錯**。
    逐道的斷言由上面那三題負責；這一題只確認真實情境不會漏網。
    """
    items, dropped, recognised = _src("parse_list")(HTML_TRANSPOSED)
    assert recognised is True
    assert dropped == 1, f"欄序對調的那一列要被丟掉，實際 dropped={dropped}"
    assert len(items) == N_DATA_ROWS - 1


# ── 條件 7 系列：四種訊號 ──────────────────────────────────────────────────

def test_07_mostly_dropped_raises_suspect_redesign_flag():
    """§3 條件 7：`dropped` 超過一半 → 疑似改版旗標。"""
    items, dropped, recognised = _src("parse_list")(HTML_MOSTLY_DROPPED)
    assert recognised is True, "版面還在，應該仍然認得"
    assert dropped == 3, f"5 筆裡 3 筆缺機關，實際 dropped={dropped}"
    assert _src("suspect_redesign")(len(items), dropped) is True


def test_07b_healthy_page_is_not_flagged():
    """對照組：正常頁不可以被判成改版。

    ⚠️ 沒有這題，「永遠回 True」的實作會讓上一題全綠，
    後果是**每天發一次假警報** —— 狼來了的告警等於沒有告警。
    """
    items, dropped, _ = _src("parse_list")(REAL)
    assert _src("suspect_redesign")(len(items), dropped) is False


def test_07c_empty_results_with_container_is_recognised():
    """§3 條件 7b：**有容器但零筆** → `recognised=True`（今天沒標案）。

    反向驗證第 4 題的目標：把 `recognised` 改成用「筆數 > 0」判定 → 這題必須變紅。
    """
    items, dropped, recognised = _src("parse_list")(HTML_EMPTY_RESULTS)
    assert items == [], f"沒有資料列，實際 {items!r}"
    assert dropped == 0
    assert recognised is True, (
        "表頭（機關名稱／標案案號／截止投標／預算金額）都在 → 這是『今天沒標案』。"
        "⚠️ 回 False 代表用筆數判定 —— 那樣每天都會發一次假警報。"
    )


def test_07d_page_without_any_list_is_not_recognised():
    """§3 條件 7c：**完全不同的頁面** → `recognised=False`（它瞎了）。"""
    items, _, recognised = _src("parse_list")(HTML_NOT_A_LIST)
    assert recognised is False, "維護公告頁應判定為認不得"
    assert items == []


def test_07e_search_form_page_is_not_recognised():
    """§3 條件 7e：**查詢表單頁**（有 `<table>`、有「機關名稱」）→ `recognised=False`。

    ⚠️ **這題專門擋「用『找得到 table』或『第幾個 table』判定」那種實作。**
    表單頁 `tb_03c` **也含**「機關名稱」與「標案案號」（那是欄位標籤），
    所以必須**四個字樣同時**出現才算認得 —— 表單頁沒有「截止投標」「預算金額」。

    ⚠️ 而且四個字樣在原始 HTML 裡是被 `<br>`／`&emsp;` 切開的
    （`截止投標` 全頁出現 **0** 次），要先 strip tags → unescape → **去掉所有空白**再比。
    照字面寫成 `'截止投標' in html` 的話，`recognised` **永遠是 False**。
    """
    items, _, recognised = _src("parse_list")(HTML_FORM_ONLY)
    assert recognised is False, (
        "查詢表單頁沒有結果表，應判定為認不得。"
        "⚠️ 回 True 代表判定條件太寬（例如只看有沒有 <table>）"
    )
    assert items == []


def test_07f_fetch_failure_is_unreachable_not_unrecognised(client, monkeypatch):
    """§3 條件 7d：**抓取失敗 → 記成「抓不到」不是「不認得」**。

    ⚠️ 這是我們上一輪才剛分開、結果在上面一層又合併了一次的東西：
    `fetch_raw` 舊簽名 `-> str` 沒有辦法表達「我沒拿到」。
    **處置完全相反**：改版要改解析器，掛掉只要等它好。

    契約：`tender_fetch_log.error` 有值、`recognised` 是 **NULL**（不是 `False`）
    —— 根本沒走到解析那一步。⚠️ C 釘的，見〈給彙整〉。
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
    assert row is not None, "抓取失敗也要留紀錄，否則沒有人知道它失敗過"
    assert row["error"], f"要記下原因，實際 {row['error']!r}"
    assert row["recognised"] is None, (
        f"抓不到就沒走到解析，recognised 應為 NULL，實際 {row['recognised']!r}。"
        "記成 False 的話，「網站掛了」會被當成「對方改版」——處置完全相反。"
    )


# ── 條件 8 系列：呼叫次數才是觀測點 ───────────────────────────────────────

def _fetch_counter(monkeypatch, page=None):
    """把 `fetch_raw` 換成計數器。⚠️ 回 **tuple**（`(html, error)`）。"""
    mod = _src()
    calls = []

    def _spy(*a, **kw):
        calls.append(a)
        return (REAL if page is None else page, None)

    monkeypatch.setattr(mod, "fetch_raw", _spy)
    return calls


def test_08_fetch_not_called_when_disabled(client, monkeypatch):
    """§3 條件 8：開關關著 → `fetch_raw` 呼叫次數 == 0。

    ⚠️ 觀測點必須是**呼叫本身**，不可以驗「沒有產生標案」——
    那在「呼叫了但抓回空的」時也成立。**沒產生資料 ≠ 沒被呼叫。**
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", False)
    _src("run_scan")()
    assert len(calls) == 0, f"開關關著不該呼叫 fetch_raw，實際 {len(calls)} 次"


def test_08b_fetch_is_called_when_enabled(client, monkeypatch):
    """§3 條件 8b：開關打開 → **同一個計數器 ≥ 1**。

    ⚠️ **沒有這題，第 8 題是假綠**：若呼叫端用 `from ... import fetch_raw`
    複製走副本，計數器**永遠是 0**，第 8 題**永遠綠**。
    🔑 **先證明量尺有刻度，再拿它去量。**
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    _src("run_scan")()
    assert len(calls) >= 1, (
        "開關開著時 fetch_raw 必須真的被呼叫，否則第 8 題什麼都沒證明。"
        "⚠️ 先查呼叫端是不是用了 `from tender_source import fetch_raw`。"
    )


def test_08c_switch_ships_off_by_default():
    """§3：總開關**出貨預設 `False`**（它會對外連線）。"""
    mod = _src()
    _src("TENDER_RADAR_ENABLED")
    assert mod.TENDER_RADAR_ENABLED is False, (
        f"出貨預設值是 {mod.TENDER_RADAR_ENABLED!r}，必須是 False"
    )


# ── 條件 9 系列 ────────────────────────────────────────────────────────────

def test_09_zero_budget_and_missing_budget_are_distinguishable(client):
    """§3 條件 9：預算「0 元」與「公告沒寫」在資料層要分得開。

    ⚠️ 斷言用 `is None` 與 `== 0`，**不是 `assert not budget`** ——
    後者對兩者都會通過，等於沒有在分辨。
    """
    import db
    cols = _cols("tenders")
    assert "budget" in cols, f"tenders 沒有 budget 欄位；實際 {sorted(cols)}"
    assert cols["budget"]["notnull"] == 0, "tenders.budget 必須允許 NULL"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, budget) VALUES (?,?,?,?)",
                     ("ZERO-001", "零元標案", "某某市政府", 0))
        conn.execute("INSERT INTO tenders (case_no, name, org, budget) VALUES (?,?,?,?)",
                     ("NULL-001", "沒寫預算", "某某市政府", None))
        conn.commit()
        zero = conn.execute("SELECT budget FROM tenders WHERE case_no=?",
                            ("ZERO-001",)).fetchone()["budget"]
        unset = conn.execute("SELECT budget FROM tenders WHERE case_no=?",
                             ("NULL-001",)).fetchone()["budget"]
    finally:
        conn.close()
    assert zero == 0, f"「0 元」要存得住，實際 {zero!r}"
    assert unset is None, f"「沒寫」要是 NULL 不是 0，實際 {unset!r}"


def test_09b_fetch_log_records_time_recognised_and_dropped(client, monkeypatch):
    """§3 條件 9b：跑一次後 `tender_fetch_log` 查得到時間＋認不認得＋`dropped`。

    ⚠️ **沒有這題，其他三十幾條全綠而這件事完全可能沒做** ——
    而它是「雷達瞎了沒」**唯一**的判斷依據。
    `recognised` 只活在當次記憶體裡的話，沒有人能回答「它上一次認得嗎」。
    """
    mod = _src()
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    _fetch_counter(monkeypatch, page=HTML_MISSING_ORG)
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
    assert row["recognised"] == 1, f"這一頁認得，實際 {row['recognised']!r}"
    assert row["dropped"] == 1, f"這一頁丟了一筆，實際 {row['dropped']!r}"


def test_09c_second_run_same_slot_makes_no_external_request(client, monkeypatch):
    """§3 條件 9c：**同一個時段內第二次呼叫不發出任何外部請求**。

    ⚠️ **沒人驗它就沒人守它，而這一條是對別人的伺服器的承諾，不是對我們自己的。**
    寫了而沒有測試的上限，等於沒有上限。

    ## 🔴 2026-09-21 §3j：這一條原本宣稱的是「**每日**一次」，而那個上限被拆掉了

    使用者裁示「我要可調整」⇒ 抓取改成一天多個時段（預設 9,12,15,18）。
    ⚠️ **斷言的數字沒有變**（連續呼叫兩次仍然只該抓一次），
    **而它宣稱的東西變了** —— 從「今天抓過就不再抓」變成「**這個時段**抓過就不再抓」。

    ☠️ 而如果只改描述不加時間控制，它會變成**偶爾紅的綠燈**：
    測試若剛好在 8:59 跑第一次、9:00 跑第二次（或 11:59/12:00、14:59/15:00、
    17:59/18:00）⇒ 跨時段 ⇒ 抓兩次 ⇒ 紅。
    🔴 **一天四個這種邊界，而且全部落在上班時間。**
    🔑 **那比紅燈貴**：紅燈會被修，偶爾紅的綠燈會被重跑一次然後忘掉。

    ⇒ 所以把時間釘住。`now_dt()` 由 §3j 的 B 提供（形狀比照 `today()`），
    **在它出現之前這一題是紅的，那是刻意的。**
    """
    mod = _src()
    freeze_slot(monkeypatch, mod)      # 兩次呼叫必須落在同一個時段裡
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", True)
    calls = _fetch_counter(monkeypatch)
    _src("run_scan")()
    first = len(calls)
    assert first >= 1, "第一次就該真的抓一次，否則這題的觀測點是壞的"
    _src("run_scan")()
    assert len(calls) == first, (
        f"同一個時段內第二次不該再發外部請求，實際從 {first} 變成 {len(calls)} 次"
    )


# ── 條件 10 ────────────────────────────────────────────────────────────────
#
# 「既有題數不可少於 **1,129**」是⑥的收斂條件，不是一支測試。
# 📌 數字寫死在 §3（第 3 輪結案時 `--collect-only` 算的）。


# ── 條件 8d～8g：總開關多了一層間接（`radar_on()`）───────────────────────
#
# 🔴 **這四題存在的理由，是 `test_08c` 即將守不到它原本守的東西。**
#
# A 裁示把實測開關做成 `radar_on()`：字面值 `TENDER_RADAR_ENABLED = False`
# 留著不動，環境變數放在**讀的那一端**。
#
#     def radar_on():
#         return TENDER_RADAR_ENABLED or os.getenv("MOTRIX_TENDER_RADAR") == "1"
#
# 這個形狀是對的（字面值留著 ⇒ 出貨預設仍然看得見、`test_08c` 在任何機器上都綠）。
# ⚠️ **但它會讓 `test_08c` 守的東西從腳底下被搬走**：
# 決定會不會對外連線的從此是 `radar_on()`，而 `test_08c` 釘的仍是那個字面值。
# 有人把 `radar_on()` 寫成 `return True`，**`test_08c` 照樣全綠**。
#
# 🔑 **守門沒有被拿掉，是它守的對象被搬走了 —— 而綠燈還在原地。**
# 這比守門被刪更難發現，因為**兩邊都沒有變**：測試沒變、字面值沒變，
# 變的是**它們之間的那條線**，而 diff 只看得到檔案。
#
# ⇒ 通則：**每引入一層間接（函式／設定／環境變數），就去問一次
#    「原本守著這個行為的那道門，現在指著的還是決定行為的那個東西嗎」。**
#
# 📌 `test_08d` 從此是主的、`test_08c` 是副的：
#    08d 釘的是**不變量**（決定連外網的東西出貨預設是關的），
#    08c 釘的是**實作細節**（08d 所讀的那個值）。兩題都留。

def _radar_on():
    fn = getattr(_src(), "radar_on", None)
    if fn is None:
        raise AssertionError(
            "helpers/tender_source.py 缺少 `radar_on()` —— "
            "實測開關要走函式，不可以把 `TENDER_RADAR_ENABLED` 的字面值改成 True："
            "那等於每一個客戶的安裝一裝好就開始連政府網站，而沒有人按過任何按鈕。"
        )
    return fn


def test_08d_effective_switch_ships_off(monkeypatch):
    """🔑 **不變量：決定會不會對外連線的那個東西，出貨預設是關的。**

    ⚠️ 這一題刻意 `delenv` ＋ 明寫字面值，**所以它與跑測試那台機器的設定無關**。
    少了 `delenv`，它會在一台「環境變數設得完全正確」的測試機上變紅，
    而錯誤訊息會說「出貨預設是開的」—— **出貨預設沒有變，變的是那台機器。
    一個把人導向錯方向的紅燈，比綠燈還貴。**
    """
    monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    monkeypatch.setattr(_src(), "TENDER_RADAR_ENABLED", False)
    assert _radar_on()() is False, "沒有環境變數、字面值是 False 時，實測開關必須是關的"


def test_08e_effective_switch_opens_with_env(monkeypatch):
    """對照組：**環境變數是 `"1"` 時要真的打開。**

    ⚠️ 沒有這一題，一個 `def radar_on(): return False` 會讓 08d 全綠 ——
    而那會讓使用者在測試機上**怎麼設都開不起來**，然後去改原始碼的字面值，
    也就是我們花了一小時擋下來的那個動作。
    🔑 「不該開的時候不開」與「該開的時候要開」是兩件事。
    """
    monkeypatch.setattr(_src(), "TENDER_RADAR_ENABLED", False)
    monkeypatch.setenv("MOTRIX_TENDER_RADAR", "1")
    assert _radar_on()() is True, "環境變數 MOTRIX_TENDER_RADAR=1 時實測開關要打開"


@pytest.mark.parametrize("value", ["0", "", "false", "no", "true", "yes", "1 "])
def test_08f_only_the_exact_value_opens_it(monkeypatch, value):
    """⚠️ **`MOTRIX_TENDER_RADAR=0` 不可以打開它。**

    寫成 `if os.getenv("MOTRIX_TENDER_RADAR"):` 的話，**`"0"` 是個非空字串 ⇒ 為真**，
    於是「我明確把它設成 0」會把雷達**打開**。
    🔑 跟 `0` vs `NULL` 同一族：**字串 `"0"` 的真假值與它的意思相反。**
    而這個錯誤的方向是**往開的那一邊**，也就是會真的連出去的那一邊。

    📌 `"true"`／`"yes"` 也釘成**不開**，是刻意的：判定就是 `== "1"`，
    跟隔壁 `MOTRIX_DISABLE_SCHEDULERS` 同一家。**不要長出一張「哪些字算真」的
    對照表** —— 那種表最會腐爛，而且兩邊會慢慢長得不一樣。
    ⚠️ `"1 "`（後面一個空格）也不開：有人從設定檔複製貼上時很容易帶到，
    而「我明明設了」跟「它沒生效」之間沒有任何訊號。
    """
    monkeypatch.setattr(_src(), "TENDER_RADAR_ENABLED", False)
    monkeypatch.setenv("MOTRIX_TENDER_RADAR", value)
    assert _radar_on()() is False, (
        f"MOTRIX_TENDER_RADAR={value!r} 把雷達打開了 —— "
        "判定要用 `== \"1\"`，不要用真假值"
    )


def test_08g_the_scan_guard_actually_reads_the_effective_switch(client, monkeypatch):
    """🔴 **這一題才是把 08d 接上真實行為的那一題。**

    08d／08e 只證明 `radar_on()` 自己算得對。**它們不證明有人在用它。**
    ⚠️ 若 `run_scan` 的守衛仍然直接讀 `TENDER_RADAR_ENABLED`，
    08d～08f 三題**全部都是綠的**，而環境變數對實際行為**一點作用都沒有** ——
    使用者會在測試機上設好環境變數、看著畫面顯示「開著」、按下去什麼也沒發生。

    🔑 **「算得對」與「被接上」是兩個問題**（見〈給彙整〉：找得到 ≠ 生效了）。
    觀測點沿用條件 8 那個計數器：**呼叫次數**，不是「有沒有產生標案」。
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", False)   # 字面值維持出貨預設
    monkeypatch.setenv("MOTRIX_TENDER_RADAR", "1")            # 只靠環境變數開
    _src("run_scan")()
    assert len(calls) >= 1, (
        "字面值關著、環境變數開著時 `run_scan` 沒有抓 —— "
        "守衛還在直接讀 `TENDER_RADAR_ENABLED`，`radar_on()` 沒有被接上。"
        "⇒ 這種狀態下 08d～08f 會全綠，而環境變數對行為毫無作用。"
    )


def test_08h_scan_stays_shut_with_no_env_and_false_literal(client, monkeypatch):
    """08g 的對照組：**兩個都關的時候，一次都不可以抓。**

    ⚠️ 沒有這一題，一個「守衛整個被拿掉」的實作會讓 08g 全綠 ——
    而那是這條線上最貴的那個失敗：**出貨的安裝會自己連出去。**
    """
    mod = _src()
    calls = _fetch_counter(monkeypatch)
    monkeypatch.setattr(mod, "TENDER_RADAR_ENABLED", False)
    monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    _src("run_scan")()
    assert len(calls) == 0, (
        f"字面值關著、也沒有環境變數，卻抓了 {len(calls)} 次 —— 守衛沒有生效"
    )
