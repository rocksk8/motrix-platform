# -*- coding: utf-8 -*-
"""傳票 ④ · **凍結**（科目名稱／摘要／來源金額）。

規格：`docs/windows/SPEC-VOUCHER.md`（施工圖，`5df2f48`）
```
§2.2   account_name_snapshot    -- **過帳時凍結**（版面要印）
       summary                  -- per-line 摘要，**產生當下凍結**
       summary_template_id / summary_template_version   -- 追溯用了哪個範本、哪一版
       source_amount_snapshot   -- 帶入當時的來源金額（**警示比對基準**）
§六(3) 過帳前檢查：寫入 account_name_snapshot（凍結）
§五(1) 來源單據被改 => 比對 source_amount_snapshot vs 來源現值
```

---

# 🔴 **凍結的風險不在「有沒有寫進去」，在「印的時候讀哪一個」**

```
寫入端   post_voucher() 把 account_name_snapshot 寫好      ✅ 很容易做對
讀取端   列印／匯出時**照樣 JOIN account_items 取 name**    ☠️ 而它長得完全正常
```
🔑 ⇒ 快照欄位**寫了但沒人讀** = 一個永遠不會被報修的缺陷：
   畫面是對的（因為大部分科目沒改過名字），**只有改過名字的那幾筆是錯的**。
📌 ⇒ 本檔的重心在**讀取端**，不在欄位存不存在。

# ⚠️ 而 ④ 存在的前提是「科目名稱改得動」

```
⑤ 的 TRIGGER 是 BEFORE UPDATE **OF code** => **改名字是允許的**
=> 所以已過帳的傳票才需要凍結名稱
```
☠️ 若有人日後把 ⑤ 「加強」成連名字都擋，**④ 會靜靜變成一題防著不存在問題的測試**
   （見 `test_voucher_referenced_code_2026_09_23.py` 最後一題）。

---

# ⚠️ 弱紅聲明（2026-09-23 01:3x 更新）

```
出題時   v95 與傳票模組都不存在 => 多題紅在同一個地方
現在     v95 已落地、helpers/voucher.py 已存在
         => 剩**讀取端兩題**紅，等 post_voucher / get_voucher
```
=> B 交接縫後我會跑突變逐題確認它紅在自己的斷言上。
⚙️ 而 `test_the_freeze_scanner_can_see_a_join` 是**儀器自檢**，用合成輸入，
   **現在就該綠** —— 它紅表示我的掃描器壞了，不是產品壞了。
"""
import importlib
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parents[3]

CHILD = "voucher_lines"

#: 施工圖 `§2.2` 逐字的凍結欄位。⚠️ 名字要換 **退回給我**。
SNAPSHOT_COLUMNS = (
    "account_name_snapshot",
    "summary",
    "summary_template_id",
    "summary_template_version",
    "source_amount_snapshot",
)

_SEAM_MODULES = ("modules.accounting.voucher", "helpers.vouchers", "modules.accounting.api.vouchers")


def _voucher_module():
    for name in _SEAM_MODULES:
        try:
            return name, importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
    pytest.fail(
        "找不到傳票模組（找過：%s）。\n" % list(_SEAM_MODULES)
        + "⚠️ 這是**弱紅**：本檔多題會紅在同一句話上。\n"
          "   名字可以換（**退回給我**），而那個接縫必須存在。")


@pytest.fixture()
def fresh_db(tmp_path):
    path = tmp_path / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ══════════════════════════════════════════════════════════════════════
# 資料層：欄位要在
# ══════════════════════════════════════════════════════════════════════

def test_voucher_lines_has_all_five_snapshot_columns(fresh_db):
    """🔴 **五個凍結欄位一個都不能少。**

    ⚠️ 釘的是**清單**不是「有 `account_name_snapshot` 就好」：
    ```
    少 summary_template_version  => 追溯得到「用了哪個範本」，
                                    **而追溯不到用了哪一版**
                                    => 範本改過之後，舊傳票對不回它當初的長相
    少 source_amount_snapshot    => §五(1) 的警示**結構上不可能發生**
    ```
    📌 `§54c` 的形狀：清單要能被數。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert CHILD in have, (
        "我在 `sqlite_master` 裡沒有找到 `%s`。\n" % CHILD
        + "⚠️ 它**應該**存在 ⇒ 看 `v95`；`v95` 已完成 ⇒ "
          "**那它是被刪掉或改名了**。\n"
        + "⚠️ 這是**弱紅**，本檔多題會一起紅在這裡。")

    cols = {r[1] for r in fresh_db.execute("PRAGMA table_info(%s)" % CHILD)}
    missing = [c for c in SNAPSHOT_COLUMNS if c not in cols]
    assert not missing, (
        "`%s` 缺凍結欄位 %s。現有：%s\n" % (CHILD, missing, sorted(cols))
        + "☠️ 少 `source_amount_snapshot` 的後果特別安靜："
          "§五(1) 的「來源單據被改」警示**結構上不可能發生**，"
          "而那一格在畫面上只是**從來沒有亮過**。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 讀取端 —— 本檔的重心
# ══════════════════════════════════════════════════════════════════════

def _seam(mod, where, *names):
    """找一支函式。找不到 => 紅，而訊息要說出我找過什麼。"""
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            return fn
    pytest.fail(
        "`%s` 沒有 %s。\n" % (where, " / ".join("`%s`" % n for n in names))
        + "⚠️ 名字可以換（**退回給我**），而那個接縫必須存在 —— "
          "內嵌在 endpoint 裡的話，**只有走過那條路才驗得到**。")


def _call(fn, conn, vid, where, label):
    """照 **B 2026-09-23 明著給的簽名**叫它，失敗時附上它真正的簽名。

    ```
    get_voucher(conn, voucher_id)          -> dict | None   （含 lines）
    post_voucher(conn, voucher_id, user)   -> (ok, err)
    ```
    ⚠️ 我原本用五種形狀輪流試 —— 而 B 給了名字之後那就是**寬判準**：
       🔑 寬的判準永遠比較好過，它給你綠燈所以你不會回來看它。
    📌 保留 `TypeError` 那一格只是為了**說得出話**：那種紅會指向產品，
       而壞的是我的呼叫方式（〈探針與被測對象糾纏〉）。
    """
    import inspect
    try:
        return fn(conn, vid, "C") if label == "post_voucher" else fn(conn, vid)
    except TypeError as e:
        try:
            sig = str(inspect.signature(fn))
        except Exception:                                  # noqa: BLE001
            sig = "(讀不到)"
        pytest.fail(
            "`%s` 的 `%s%s` 我叫不動：%s\n" % (where, label, sig, e)
            + "⚠️ **壞的可能是我的呼叫方式，不是產品。**\n"
            + "   我照 B 2026-09-23 給的簽名叫：`get_voucher(conn, voucher_id)`／"
              "`post_voucher(conn, voucher_id, user)`。\n"
            + "   簽名改了 **退回給我**。")


def _lines_of(payload):
    """從回傳裡取出分錄列。⚠️ 鍵名沒定版 => 依序找。"""
    if payload is None:
        return []
    for k in ("lines", "voucher_lines", "items", "rows"):
        if isinstance(payload, dict) and payload.get(k):
            return list(payload[k])
        if hasattr(payload, "keys") and k in payload.keys() and payload[k]:
            return list(payload[k])
    if isinstance(payload, (list, tuple)):
        return list(payload)
    return []


def _voucher_table(conn):
    """傳票**實表**的名字。

    🔴 `vouchers` 自 2026-09-23 起是**只露出未作廢的 VIEW**，實表叫 `vouchers_all`。
    ☠️ 而我的探針原本 INSERT 進 `vouchers` => VIEW 插不進去
       ⇒ 三題一起紅，**而我的訊息說「v95 還沒有」** —— 它在，只是換了型別。
    🔑 〈探針與被測對象糾纏〉最貴的一種：**紅燈不但指錯對象，還給了一個自信的錯解釋。**
    """
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if "vouchers_all" in have:
        return "vouchers_all"
    return "vouchers" if "vouchers" in have else None


def _seed_posted(conn, post, code, name, status="已核准"):
    """種一張傳票（一借一貸、平衡），`post` 不是 `None` 就把它過帳。

    ⚠️ 只塞 `NOT NULL` 且沒有 DEFAULT 的欄位 —— DDL 加欄位時這裡不必跟著改。
    🔴 科目代號用 **9901／9902**，不是 1113／4111 ——
       那兩個**是法定 547 筆裡的**，而法定列被 `v93` 的 TRIGGER 擋著不可改名。
    ☠️ 我第一版就是用 1113 ⇒ 改名會被 `account_items_statutory_no_update` 擋下來
       ⇒ 這一題會紅，**而訊息會指向 ⑤ 的 TRIGGER**（一段寫對的碼）。
       〈探針與被測對象糾纏〉：壞的是我的裝置，而訊息的指向是我當初的假設。
    """
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = {"vouchers", CHILD} - have
    if missing:
        pytest.fail(
            "我在 `sqlite_master` 裡沒有找到 %s。\n"
            % sorted(missing)
            + "⚠️ 它們**應該**存在 ⇒ 看 `v95`；`v95` 已完成 ⇒ "
              "**那是被刪掉或改名了**。")

    conn.execute(
        "INSERT INTO account_items (code, name, parent_code, level,"
        " source) VALUES (?,?,?,?, 'custom')", (code, name, "", 4))
    conn.execute(
        "INSERT INTO account_items (code, name, parent_code, level,"
        " source) VALUES (?,?,?,?, 'custom')", ("9902", "銷貨收入", "", 4))
    conn.execute(
        "INSERT INTO %s (voucher_no, voucher_date, created_by,"
        " created_at, updated_at, status) VALUES (?,?,?,?,?,?)"
        % _voucher_table(conn),
        ("20260923-001", "2026-09-23", "C", "2026-09-23T00:00:00",
         "2026-09-23T00:00:00", status))
    vid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for ln, (acct, d, c) in enumerate(
            ((code, 1000, 0), ("9902", 0, 1000)), start=1):
        conn.execute(
            "INSERT INTO %s (voucher_id, line_no, account_code, debit, credit)"
            " VALUES (?,?,?,?,?)" % CHILD, (vid, ln, acct, d, c))
    conn.commit()
    if post is not None:
        _call(post, conn, vid, "post_voucher", "post_voucher")
        conn.commit()
    return vid


def _line_name(row):
    """從一行分錄的回傳裡取出「畫面上會印的科目名稱」。

    ⚠️ 欄位名沒定版 => 依序找。

    🔴 **欄位在而值是空的**，與**欄位根本不存在**，是兩件事：
    ```
    第一版  `if row.get(k):` => 空字串被當成「沒有這個欄位」=> 訊息印 `欄位 None`
    而突變跑出來的樣子  「印出來是 None（欄位 `None`）」<= **它說不出是哪一種**
    ```
    🔑 〈null 不等於 0〉＋〈探針的訊息只能描述我看到什麼〉：
       ⇒ 先看鍵在不在，**在就回那個值**（即使是空字串）。
    """
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    for k in ("account_name", "accountName", "name", "account_name_snapshot"):
        if k in keys:
            return k, row[k]
    return None, "（找不到任何一個名稱欄位，這一行有：%s）" % sorted(keys)[:8]


def test_a_posted_voucher_prints_the_frozen_name_not_the_current_one(fresh_db):
    """🔴🔴 **已過帳的傳票，印出來的科目名稱是「過帳當時」的那一個。**

    ```
    過帳時   1113 = 銀行存款          => account_name_snapshot = '銀行存款'
    之後     使用者把它改成「銀行存款（台銀）」   ✅ ⑤ 允許改名
    再列印   必須還是 **銀行存款**
    ```
    ☠️ 失敗的樣子：**去年的傳票今天印出來不一樣。**
    🔑 而它幾乎不會被發現 —— 大部分科目從來沒改過名字，
       **只有改過名字的那幾筆是錯的**，而那幾筆看起來也很正常。
    📌 這一題釘的是**讀取端**：欄位寫好了而列印照樣 JOIN，一樣算沒做到。

    ⚙️ 正對照在下一題：**草稿**要印**現在**的名字（不可以凍太早）。
    """
    where, mod = _voucher_module()
    post = _seam(mod, where, "post_voucher", "post", "_post_voucher")
    read = _seam(mod, where, "get_voucher", "get_voucher_detail", "_get_voucher")

    vid = _seed_posted(fresh_db, post, code="9901", name="銀行存款")
    fresh_db.execute(
        "UPDATE account_items SET name='銀行存款（台銀）' WHERE code='9901'")
    fresh_db.commit()

    lines = _lines_of(_call(read, fresh_db, vid, where, "get_voucher"))
    assert lines, (
        "`%s` 讀回來的傳票沒有分錄 —— 讀不到就驗不了凍結。" % where)
    key, got = _line_name(lines[0])
    assert got == "銀行存款", (
        "已過帳的傳票印出來是 %r（欄位 `%s`），過帳當時是 '銀行存款'。\n"
        % (got, key)
        + "☠️ **去年的傳票今天印出來不一樣。**\n"
          "🔑 `account_name_snapshot` 寫好了而讀取端照樣 JOIN —— "
          "〈守門守的對象被搬走〉：欄位在、值也對，**而決定畫面的不是它。**")


def test_a_draft_shows_the_current_name_not_a_frozen_one(fresh_db):
    """⚙️ **正對照：草稿要印「現在」的名字。**

    ☠️ 少了它，「建立分錄時就把名字凍起來」也會讓上一題綠 ——
       而症狀是：
    ```
    使用者把科目改名 => 回到自己還沒送審的草稿 => **名字沒變**
    => 他會以為改名沒生效，再改一次
    ```
    🔑 `§2.2` 逐字是「**過帳時**凍結」，不是「建立時凍結」。
    📌 凍太早與凍太晚是同一個軸的兩端，而**只有凍太晚會被報修**。
    """
    where, mod = _voucher_module()
    read = _seam(mod, where, "get_voucher", "get_voucher_detail", "_get_voucher")

    vid = _seed_posted(fresh_db, None, code="9901", name="銀行存款",
                       status="草稿")
    fresh_db.execute(
        "UPDATE account_items SET name='銀行存款（台銀）' WHERE code='9901'")
    fresh_db.commit()

    lines = _lines_of(_call(read, fresh_db, vid, where, "get_voucher"))
    assert lines, "讀回來的草稿沒有分錄。"
    key, got = _line_name(lines[0])
    assert got == "銀行存款（台銀）", (
        "**草稿**印出來是 %r（欄位 `%s`），而現在的名字是 '銀行存款（台銀）'。\n"
        % (got, key)
        + "☠️ 凍太早了：使用者改了科目名稱，回到自己還沒送審的草稿卻沒變 ——\n"
          "   他會以為改名沒生效，**再改一次**。\n"
          "🔑 `§2.2` 逐字是「**過帳時**凍結」。\n"
          "⚙️ 而這一題是上一題的正對照：少了它，「一律凍結」也會讓上一題綠。")


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 結構絆線：列印路徑不可以 JOIN account_items 取名字
# ══════════════════════════════════════════════════════════════════════

_JOIN_RE = re.compile(
    r"join\s+account_items\b", re.IGNORECASE)
_NAME_PICK_RE = re.compile(
    r"\baccount_items\s*\.\s*name\b|\bai\s*\.\s*name\b", re.IGNORECASE)


def _strip_comments(src):
    """把註解與字串以外的部分留下，**行號與長度都不變**（空白填回去）。

    🔴 **B 2026-09-23 抓到的**：第一版直接掃 `src.splitlines()` ⇒
       **任何討論它的註解都會讓它亮**。B 在 `_current_account_names()` 的
       docstring 裡逐字寫出「為什麼不用 JOIN 取 name」，絆線就亮在那段解釋上。
    ☠️ 方向與我設計的相反：**把一段寫對的碼報成缺陷** ——
       而那個方向會讓人去改一段沒壞的東西。
    ⚠️ 而 B 同時指出我的誘餌自檢有盲點：誘餌是**合成字串**，
       它證明得了「掃描器看得見」，**證明不了「掃描器只看程式碼」**。
       ⇒ 下面的自檢補了那一半。
    📌 用 `tokenize` 不用 AST：AST 看得到「已經存在的語法結構」，
       而我要的是「把註解與字串**變不見**」。
    """
    import io
    import tokenize
    lines = src.splitlines(keepends=True)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src                      # 解析不了就原樣回去，寧可誤報也不漏報
    for tok in toks:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for r in range(r1, r2 + 1):
            line = lines[r - 1]
            a = c1 if r == r1 else 0
            b = c2 if r == r2 else len(line.rstrip("\n"))
            lines[r - 1] = line[:a] + " " * (b - a) + line[b:]
    return "".join(lines)


def _joins_for_name(src, strip=True):
    """回傳「JOIN account_items」或「取它的 name」的行號。

    ⚠️ `strip=False` 只給儀器自檢用（合成片段不是合法的 Python）。
    """
    text = _strip_comments(src) if strip else src
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if _JOIN_RE.search(line) or _NAME_PICK_RE.search(line):
            hits.append((i, line.strip()))
    return hits


def test_the_freeze_scanner_can_see_a_join():
    """⚙️ **儀器自檢：現在就該綠。**

    ☠️ 〈探針與被測對象糾纏〉：下一題若回報「沒有 JOIN」，
       它可能是真的沒有，**也可能是我的掃描器看不見**。
    🔑 ⇒ 先讓一個**故意寫壞的合成輸入**亮起來。
    ⚠️ 而這個誘餌是**合成的**，不是 repo 裡真的缺陷 ——
       釘在真缺陷上的正對照會在缺陷修好那天失效。
    """
    bait = "\n".join([
        "SELECT l.debit, ai.name",
        "  FROM voucher_lines l",
        "  JOIN account_items ai ON ai.code = l.account_code",
    ])
    hits = _joins_for_name(bait, strip=False)
    assert len(hits) >= 2, (
        "掃描器在合成誘餌上只看到 %d 行：%s\n" % (len(hits), hits)
        + "☠️ **儀器壞了** => 下一題回報的「沒有 JOIN」不可信。")

    clean = "SELECT l.debit, l.account_name_snapshot FROM voucher_lines l"
    assert not _joins_for_name(clean, strip=False), (
        "掃描器在乾淨的輸入上也命中 —— **它會把對的東西報成缺陷**，"
        "而那個方向會讓人去改一段沒壞的碼。")

    # 🔴 B 2026-09-23 抓到的那一半：**它必須只看程式碼**。
    # ☠️ 少了這一格，任何人寫註解解釋「為什麼不用 JOIN 取 name」都會中 ——
    #    而那正是 B 實際踩到的（他在 docstring 裡逐字寫出那兩個詞）。
    # 🔑 而合成誘餌**證明不了這一格**：它只證明「掃描器看得見」，
    #    不證明「掃描器**只**看程式碼」。兩者是不同的失效。
    in_comment = (
        "def f(conn):\n"
        "    # 這裡刻意不 JOIN account_items 取 ai.name —— 見 §六(3)\n"
        '    """已過帳時不可以 JOIN account_items 拿 ai.name。"""\n'
        "    return conn.execute('SELECT account_name_snapshot FROM voucher_lines')\n"
    )
    assert not _joins_for_name(in_comment), (
        "掃描器亮在**註解／docstring** 上：%s\n" % _joins_for_name(in_comment)
        + "☠️ **寫註解解釋為什麼避開某寫法的人會被報成缺陷** ——\n"
          "   而那個方向會讓人去改一段寫對的碼，甚至刪掉那段解釋。")

    # ⚙️ 而剝不可以把真的那一行也剝掉（剝過頭 => 下一題永遠綠）
    real_code = (
        "def f(conn):\n"
        "    return conn.execute(\n"
        "        'SELECT ai.name FROM voucher_lines l'\n"
        "        ' JOIN account_items ai ON ai.code = l.account_code')\n"
    )
    assert _joins_for_name(real_code, strip=False), (
        "連沒剝的版本都看不到真的 JOIN —— 儀器壞了。")

    # 🔴 **真檔案的誘餌**（A-2 2026-09-23 建議，而我改成這個形式）：
    #    上面三格都是**合成字串**，它們證明不了「剝註解在一個真的 .py 上也成立」。
    # ⇒ 拿**本檔自己**當輸入：它含有下面這行故意留著的誘餌 ——
    #
    #    ⚙️ 誘餌（**不可刪**）：這一行刻意寫著 JOIN account_items 與 ai.name，
    #       它存在的唯一理由是讓「剝註解」這件事在一個真檔案上被證明。
    #
    #    ⇒ 不剝 => 一定命中（誘餌在）／剝了 => 一定不命中（它在註解裡）
    # 🔑 〈正對照要釘在故意留著的誘餌上〉：B 已經改寫了他那段真實的文字，
    #    **真實案例沒有了** —— 所以誘餌要由我自己留著，而且標明不可刪。
    me = Path(__file__).read_text(encoding="utf-8")
    assert _joins_for_name(me, strip=False), (
        "本檔的誘餌不見了 —— **有人刪了那一行註解** ⇒ 下面那個斷言從此沒有意義。")
    assert not _joins_for_name(me), (
        "剝完註解之後，本檔仍然命中：%s\n" % _joins_for_name(me)
        + "☠️ 剝註解在**真檔案**上沒有生效 —— "
          "而上面三格合成輸入都是綠的，它們證明不了這一件事。")


def test_no_voucher_print_path_joins_account_items_for_the_name():
    """🔴 **傳票的讀取／列印路徑不可以 JOIN `account_items` 取 `name`。**

    📌 這是上面那兩題的**結構補充**，不是替代：
    ```
    行為題  證明「改名之後印出來沒變」      <= 直接，而需要 B 的簽名
    絆線    證明「它根本沒有那條讀取路徑」  <= 現在就跑得動
    ```
    ⚠️ 而絆線單獨不夠：**沒有 JOIN 也可能是它根本沒印名字。**

    # 🔴 而 B 2026-09-23 指出它**目前是零資訊的綠燈**

    ```
    B 的實作整支檔都沒有連接查詢（過帳與草稿兩條路都分開查）
    => 這道絆線分不出「過帳路徑乾淨」與「這支檔本來就沒有那個寫法」
    ```
    ✅ 我同意，而我沒有拿掉它：**它的價值在未來的變更上，不在現在的量測上**
       —— 它擋得住「日後有人加一條 JOIN 進去」。

    ## ⚠️ 而那個正當性有一個**依賴**，A-2 要求讓它看得見

    ```
    絆線的正當性  ← 依賴 →  test_a_posted_voucher_prints_the_frozen_name_not_the_current_one
                            test_a_draft_shows_the_current_name_not_a_frozen_one
    ```
    ☠️ 那兩題若被刪或改寫 ⇒ **絆線的正當性沒了，而沒有人會發現** ——
       它會留在檔案裡、永遠綠、而不再有任何理由。
    📌 兩者**刻意放同一個檔**（A-2 提的最便宜做法）：刪的人會同時看到。
    ⚠️ 指名的是**函式名不是行號**：改名時 `grep` 會找不到，
       而那比「指到別的東西」好（〈不要用會動的名字〉）。
    """
    # M06 搬遷（2026-09-26）：傳票的 router／helper 在 modules/accounting/（含 api/）
    cands = [p for p in (_BACKEND / "modules" / "accounting").rglob("*.py")
             if p.stem in ("vouchers", "voucher") and "tests" not in p.parts]
    assert cands, (
        "找不到傳票的 router／helper（找過 `routers/vouchers.py`、"
        "`helpers/voucher.py` …）——\n"
        "⚠️ 這是**弱紅**：檔案還沒有。名字要換 **退回給我**。")

    bad = []
    for p in cands:
        for ln, text in _joins_for_name(p.read_text(encoding="utf-8")):
            bad.append("%s:%d  %s" % (p.name, ln, text[:70]))
    assert not bad, (
        "傳票的讀取路徑碰了 `account_items.name`：\n  " + "\n  ".join(bad)
        + "\n☠️ 那會讓**已過帳的傳票印出今天的名字** —— "
          "而 `account_name_snapshot` 明明已經寫好了。\n"
          "🔑 〈守門守的對象被搬走〉：欄位在、值也對，"
          "**而決定畫面的不是它。**")
