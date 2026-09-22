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

# ⚠️ 弱紅聲明

`v95` 與傳票模組都還不存在 => 本檔多題會紅在同一個地方。
=> B 落地後我會跑突變逐題確認它紅在自己的斷言上。
⚙️ 而 `test_the_freeze_scanner_can_see_a_join` 是**儀器自檢**，用合成輸入，
   **現在就該綠** —— 它紅表示我的掃描器壞了，不是產品壞了。
"""
import importlib
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent

CHILD = "voucher_lines"

#: 施工圖 `§2.2` 逐字的凍結欄位。⚠️ 名字要換 **退回給我**。
SNAPSHOT_COLUMNS = (
    "account_name_snapshot",
    "summary",
    "summary_template_id",
    "summary_template_version",
    "source_amount_snapshot",
)

_SEAM_MODULES = ("helpers.voucher", "helpers.vouchers", "routers.vouchers")


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
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert CHILD in have, (
        "`%s` 不存在 —— `v95` 還沒有。\n" % CHILD
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
    """用幾種常見形狀叫它。**全部失敗才報**，而報的時候要附上它真正的簽名。

    ⚠️ 我不自己發明簽名 —— 這裡只是不要為了「參數順序不同」而紅，
       因為那種紅會**指向產品**而壞的是我的呼叫方式（〈探針與被測對象糾纏〉）。
    """
    import inspect
    shapes = (
        lambda: fn(conn, vid),
        lambda: fn(vid, conn=conn),
        lambda: fn(vid),
        lambda: fn(conn=conn, voucher_id=vid),
        lambda: fn(conn, vid, "C"),
    )
    errs = []
    for shape in shapes:
        try:
            return shape()
        except TypeError as e:
            errs.append(str(e))
    try:
        sig = str(inspect.signature(fn))
    except Exception:                                      # noqa: BLE001
        sig = "(讀不到)"
    pytest.fail(
        "`%s` 的 `%s%s` 我叫不動（試過 %d 種形狀）。\n" % (where, label, sig, len(shapes))
        + "⚠️ **壞的可能是我的呼叫方式，不是產品** —— 請 B 把簽名退回給我。\n"
        + "   " + "\n   ".join(errs[:3]))


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
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = {"vouchers", CHILD} - have
    if missing:
        pytest.fail("`v95` 還沒有：缺 %s。⚠️ 這是**弱紅**。" % sorted(missing))

    conn.execute(
        "INSERT INTO account_items (code, name, parent_code, level,"
        " source) VALUES (?,?,?,?, 'custom')", (code, name, "", 4))
    conn.execute(
        "INSERT INTO account_items (code, name, parent_code, level,"
        " source) VALUES (?,?,?,?, 'custom')", ("9902", "銷貨收入", "", 4))
    conn.execute(
        "INSERT INTO vouchers (voucher_no, voucher_date, created_by,"
        " created_at, updated_at, status) VALUES (?,?,?,?,?,?)",
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

    ⚠️ 欄位名沒定版 => 依序找。找不到 => 說出我找過什麼。
    """
    for k in ("account_name", "accountName", "name", "account_name_snapshot"):
        if isinstance(row, dict) and row.get(k):
            return k, row[k]
        if hasattr(row, "keys") and k in row.keys() and row[k]:
            return k, row[k]
    return None, None


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


def _joins_for_name(src):
    """回傳「同時 JOIN account_items 又取它的 name」的行號。

    ⚠️ 兩個條件都要 —— 只看 JOIN 會誤報（查科目樹本來就要 JOIN）。
    """
    hits = []
    for i, line in enumerate(src.splitlines(), 1):
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
    hits = _joins_for_name(bait)
    assert len(hits) >= 2, (
        "掃描器在合成誘餌上只看到 %d 行：%s\n" % (len(hits), hits)
        + "☠️ **儀器壞了** => 下一題回報的「沒有 JOIN」不可信。")

    clean = "SELECT l.debit, l.account_name_snapshot FROM voucher_lines l"
    assert not _joins_for_name(clean), (
        "掃描器在乾淨的輸入上也命中 —— **它會把對的東西報成缺陷**，"
        "而那個方向會讓人去改一段沒壞的碼。")


def test_no_voucher_print_path_joins_account_items_for_the_name():
    """🔴 **傳票的讀取／列印路徑不可以 JOIN `account_items` 取 `name`。**

    📌 這是上面那兩題的**結構補充**，不是替代：
    ```
    行為題  證明「改名之後印出來沒變」      <= 直接，而需要 B 的簽名
    絆線    證明「它根本沒有那條讀取路徑」  <= 現在就跑得動
    ```
    ⚠️ 而絆線單獨不夠：**沒有 JOIN 也可能是它根本沒印名字。**
    """
    cands = [p for p in (_BACKEND / "routers").glob("*.py")
             if p.stem in ("vouchers", "voucher")]
    cands += [p for p in (_BACKEND / "helpers").glob("*.py")
              if p.stem in ("vouchers", "voucher")]
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
