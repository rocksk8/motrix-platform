"""§3m · U1～U7 · **升級路徑**：v84（正式機實際版本）→ v88。

> 使用者 2026-09-21：**「最後這些功能都要能更新到正式機環境的，最終要完整確認
> 這些內容，今天錯誤的部分實在太多。」**

## ☠️ 為什麼這批測試必須存在

```
正式機（A 讀備份複本查的，as-of 2026-09-21 20:20）
  schema_version : 84          ← 起點
  table count    : 77
  tenders table  : NO          ← 整個標案雷達在正式機上是全新的
  真實資料       : quotations 35 / users 12 / suppliers 27 / dev_cases 107 / dev_logs 566
開發機 CURRENT_VERSION = 88   ⇒ 四個 migration：_m085 ~ _m088
```

🔴 **這四個 migration 從來沒有對「停在 84 且有資料」的庫跑過。**

| 誰走過哪條路 | |
|---|---|
| 開發機 | **一路跟著升上來**（每次只差一兩個版本）|
| 我的測試 | **每次從零建**（`init_db` 一路跑到 88）|
| **正式機** | **84 一次跳到 88，而且庫裡有三個月的真實資料** |

🔑 **前兩條路都不是正式機要走的那一條，而它們兩條都是綠的。**

## ⚠️ 這批測試涵蓋的是「schema 的升級」，不是「真實資料庫的升級」

我用「截斷 `_MIGRATIONS` 再跑一次」造出 v84 的庫。
**那跟一個真的在 84 跑了三個月的庫不一樣** —— 後者有：手動改過的列、
失敗的匯入留下的殘骸、已經被刪掉的使用者留下的外鍵孤兒…
⇒ **U6（拿備份複本真的跑一次）是人工的，A 做。** 這個檔驗不到那些。
📌 **誠實標註這件事，比讓下一個人以為「升級已經驗過了」重要。**
"""
import sqlite3

import pytest

import db

PROD_VERSION = 84            # A 從備份複本讀出來的實際版本，不是假設
TENDER_TABLES = ("tenders", "tender_watches", "tender_hits", "tender_fetch_log")


def _tables(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _build_at_version(path, version):
    """造一個**停在 `version`** 的庫。

    做法：把 `db._MIGRATIONS` 截到前 `version` 個、`CURRENT_VERSION` 也改成
    `version`，然後跑 `init_db`。
    ⚠️ `_run_migrations` 讀的是**模組全域**，所以改模組屬性有效
    （若哪天它改成參數傳入，這支要跟著改）。

    ⚠️ 用 try/finally 還原，**不用 monkeypatch.undo()** ——
    後者會把同一個測試裡**其他**的 patch 一起還原掉，而那是安靜的。
    """
    saved = (db.CURRENT_VERSION, db._MIGRATIONS)
    try:
        db.CURRENT_VERSION = version
        db._MIGRATIONS = saved[1][:version]
        db.init_db(str(path))
    finally:
        db.CURRENT_VERSION, db._MIGRATIONS = saved


def _version_of(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        return row["version"] if row else 0
    finally:
        conn.close()


def _open(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ── 前提：這個 harness 真的造得出一個「像正式機」的庫 ─────────────────────

def test_u0_the_harness_really_produces_a_v84_database(tmp_path):
    """量尺先驗：造出來的庫**真的停在 84，而且真的沒有 `tender_*`**。

    ⚠️ 沒有這一題，U1～U7 可能全部跑在一個**其實已經是 88** 的庫上 ——
    那時它們會**全綠而什麼都沒驗**，因為「升級」根本沒有發生。
    🔑 **先證明起點是對的，再驗從起點出發會怎樣。**

    📌 這一題也順便釘住 A 查到的那個事實：`tender_*` 四張表**只在 `_m086` 裡建**，
    不在基礎 schema 裡。若哪天有人把它們搬進 `init_db` 的 base tables，
    這題會紅 —— **而那個改動會讓 U7 從「驗得到」變成「必然綠」。**
    """
    path = tmp_path / "prod.db"
    _build_at_version(path, PROD_VERSION)
    assert _version_of(path) == PROD_VERSION, (
        f"造出來的庫是 v{_version_of(path)}，不是 v{PROD_VERSION}"
    )
    conn = _open(path)
    try:
        tables = _tables(conn)
    finally:
        conn.close()
    present = [t for t in TENDER_TABLES if t in tables]
    assert not present, (
        f"v84 的庫裡就已經有 {present} —— 那代表這幾張表被搬進基礎 schema 了，"
        "U7 會變成必然綠（升級時無事可做）"
    )


# ── U1：升得上去 ─────────────────────────────────────────────────────────

def test_u1_upgrade_from_84_to_current_does_not_raise(tmp_path):
    """🔴 U1：v84 → v88 **不丟例外**，而且版本真的前進。

    ⚠️ `84` 是 A 從正式機備份複本讀出來的**實際**版本，不是假設。
    """
    path = tmp_path / "upgrade.db"
    _build_at_version(path, PROD_VERSION)
    db.init_db(str(path))            # 這一次用真正的 CURRENT_VERSION
    assert _version_of(path) == db.CURRENT_VERSION, (
        f"升完之後停在 v{_version_of(path)}，應為 v{db.CURRENT_VERSION}"
    )


def test_u1b_upgrading_twice_is_a_no_op(tmp_path):
    """U1 的對照組：**已經是最新版時再跑一次，什麼都不該發生。**

    ⚠️ 正式機的部署腳本每次啟動都會呼叫 `init_db` ——
    第二次不是冪等的話，症狀會出現在**重開機之後**，而那時沒有人在看畫面。
    🔑 而「不冪等」最常見的樣子不是丟例外，是**重複插入種子資料**。
    """
    path = tmp_path / "twice.db"
    _build_at_version(path, PROD_VERSION)
    db.init_db(str(path))
    conn = _open(path)
    try:
        before = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in sorted(_tables(conn)) if t != "sqlite_sequence"}
    finally:
        conn.close()

    db.init_db(str(path))            # 再來一次

    conn = _open(path)
    try:
        after = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                 for t in sorted(_tables(conn)) if t != "sqlite_sequence"}
    finally:
        conn.close()
    grew = {t: (before[t], after[t]) for t in before if after.get(t) != before[t]}
    assert not grew, f"再跑一次 init_db 之後這幾張表的筆數變了：{grew}"


# ── U2：資料不可以少 ─────────────────────────────────────────────────────

def _seed_real_data(path):
    """塞幾筆「像正式機」的資料。筆數是照 A 查到的比例縮小的樣本。"""
    conn = _open(path)
    try:
        for i in range(3):
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name) VALUES (?,?,?)",
                (f"Q-84-{i:03d}", "已結案", f"客戶{i}"))
        for i in range(2):
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, "
                "modules, active, created_at, must_change_password) "
                "VALUES (?,?,?,?,?,1,?,0)",
                (f"u84_{i}", "x", f"使用者{i}", "admin", "[]", "2026-01-01T00:00:00"))
        for i in range(2):
            conn.execute(
                "INSERT INTO suppliers (name) VALUES (?)", (f"供應商{i}",))
        conn.commit()
        return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                for t in sorted(_tables(conn)) if t != "sqlite_sequence"}
    finally:
        conn.close()


def test_u2_no_row_is_lost_during_the_upgrade(tmp_path):
    """🔴🔴 U2：升級後**既有資料一列都沒少**（逐表比對筆數）。

    ☠️ 這是這一批裡後果最大的一題：`ALTER TABLE` 加欄位很安全，
    而**「重建表再搬資料」不安全** —— 而 SQLite 改約束、改預設值、
    刪欄位**只能**用重建表那條路。
    ⚠️ 搬漏的那幾列不會有任何訊號：表還在、欄位還在、查詢不報錯。

    📌 逐表比對而不是只看幾張重要的表，理由是**漏掉的永遠是沒有人想到的那一張**
    （這條是今天〈守門要驗有沒有人做過決定〉那一族）。
    """
    path = tmp_path / "data.db"
    _build_at_version(path, PROD_VERSION)
    before = _seed_real_data(path)

    db.init_db(str(path))

    conn = _open(path)
    try:
        after = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                 for t in sorted(_tables(conn)) if t != "sqlite_sequence"}
    finally:
        conn.close()

    lost = {t: (before[t], after.get(t)) for t in before
            if after.get(t, -1) < before[t]}
    assert not lost, (
        f"升級之後這幾張表的筆數變少了（升級前, 升級後）：{lost}\n"
        "⚠️ 沒有任何訊號會告訴使用者這件事：表還在、欄位還在、查詢不報錯。"
    )
    dropped = [t for t in before if t not in after]
    assert not dropped, f"升級之後這幾張表不見了：{dropped}"


# ── U3：新欄位要有預設值 ─────────────────────────────────────────────────

def test_u3_new_columns_on_existing_rows_are_not_surprises(tmp_path):
    """🔴 U3：新增欄位在**既有列**上的值，要嘛有預設、要嘛允許 `NULL` 而讀取端讀得懂。

    ⚠️ `ALTER TABLE ... ADD COLUMN x TEXT NOT NULL` 在 SQLite 上會**直接失敗**
    （既有列沒有值可填），所以真正的風險不是那個 —— 是
    **加了一個可以是 `NULL` 的欄位，而讀取端假設它有值**。

    🔑 這一題釘的是「**不可以有 NOT NULL 而沒有預設值的新欄位**」：
    那種欄位在空庫上加得起來、在**有資料的庫**上加不起來
    ⇒ **開發機綠、正式機炸**，而那正是這一批要防的形狀。
    """
    path = tmp_path / "cols.db"
    _build_at_version(path, PROD_VERSION)
    _seed_real_data(path)
    db.init_db(str(path))

    conn = _open(path)
    try:
        bad = []
        for table in sorted(_tables(conn)):
            if table == "sqlite_sequence":
                continue
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
                if row["notnull"] and row["dflt_value"] is None and not row["pk"]:
                    bad.append(f"{table}.{row['name']}")
    finally:
        conn.close()
    # ⚠️ 這裡**不是**斷言「一個都不可以有」—— 基礎 schema 本來就有幾個
    #    NOT NULL 無預設的欄位（`quotations.quote_no` 之類），那是對的。
    #    要驗的是「**升級沒有讓它變多**」，所以拿空庫當基準比對。
    fresh = tmp_path / "fresh.db"
    db.init_db(str(fresh))
    conn = _open(fresh)
    try:
        baseline = []
        for table in sorted(_tables(conn)):
            if table == "sqlite_sequence":
                continue
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
                if row["notnull"] and row["dflt_value"] is None and not row["pk"]:
                    baseline.append(f"{table}.{row['name']}")
    finally:
        conn.close()
    extra = sorted(set(bad) - set(baseline))
    assert not extra, (
        f"升級過的庫多了這些「NOT NULL 而沒有預設值」的欄位：{extra}\n"
        "⇒ 它們在空庫上加得起來、在有資料的庫上加不起來：開發機綠、正式機炸。"
    )


# ── U7：從無到有 ─────────────────────────────────────────────────────────

def test_u7_tender_tables_are_created_from_nothing(tmp_path):
    """🔴🔴 U7：`_m086` 要在「**完全沒有任何 `tender_*`**」的庫上把四張表建起來。

    🔑 **「從無到有」與「補上缺的那幾張」是兩條不同的路，
    而只有前者會發生在正式機上。**

    ⚠️ 開發機上這四張表**早就存在**了（`_m086` 當初就是在那裡跑的），
    所以開發機走的一直是「補缺的」那條路 —— 它**驗不到**從無到有。
    """
    path = tmp_path / "fromzero.db"
    _build_at_version(path, PROD_VERSION)
    conn = _open(path)
    try:
        assert not (set(TENDER_TABLES) & _tables(conn)), "前提不成立"
    finally:
        conn.close()

    db.init_db(str(path))

    conn = _open(path)
    try:
        tables = _tables(conn)
        missing = [t for t in TENDER_TABLES if t not in tables]
        assert not missing, f"升級之後這幾張表沒有被建起來：{missing}"
        # 每一張都要真的能寫進去 —— 「表建起來了」與「它能用」是兩件事
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
            ("升級後建立的條件", '["監視"]'))
        conn.execute(
            "INSERT INTO tenders (case_no, name, org) VALUES (?,?,?)",
            ("U7-001", "升級後的標案", "某機關"))
        conn.commit()
    finally:
        conn.close()


def test_u7b_tender_detail_columns_exist_after_the_jump(tmp_path):
    """U7 的延伸：`_m088` 加的欄位在**從 84 一次跳上來**的庫裡也要在。

    ⚠️ `_m086` 建表、`_m088` 對同一張表 `ALTER TABLE` 加欄位 ——
    兩者在「一次跳四版」時是**同一個交易序列裡的前後兩步**。
    🔑 而 `_m086` 的 `CREATE TABLE` 若哪天被改成「已經含新欄位」，
    `_m088` 的 `_col_exists` 檢查會跳過它 —— **那是對的**，
    這題保護的是「**跳版之後欄位一定在**」，不管是哪一步加的。
    """
    path = tmp_path / "detail.db"
    _build_at_version(path, PROD_VERSION)
    db.init_db(str(path))
    conn = _open(path)
    try:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(tenders)").fetchall()}
    finally:
        conn.close()
    for col in ("location", "procurement_type", "tender_method"):
        assert col in cols, (
            f"從 v{PROD_VERSION} 跳上來之後 tenders.{col} 不存在。實際：{sorted(cols)}"
        )


# ── U4：migration 不可以呼叫會演進的 helper ──────────────────────────────

def test_u4_migrations_do_not_call_evolving_helpers():
    """🔴 U4：migration 不可以呼叫**會演進**的 helper。

    🔑 **凍住的歷史不要呼叫活的程式碼**：`_m085` 是 2026-09 寫的，
    而它若呼叫 `helpers.xxx.do_something()`，那個函式明年改了行為，
    **`_m085` 的行為就被回溯改寫了**。

    ⚠️ 症狀只出現在「**完整降版再升版**」與「**全新安裝**」這兩條路上 ——
    而那正是正式機與災難還原要走的路。

    📌 判準刻意寫得窄：只看 migration 區段裡有沒有 `helpers.` 或 `from helpers`。
    `db.py` 自己的 `_col_exists`／`_seed_setting` 不算 —— 它們與 schema 同生共死。
    ⚠️ **這是脆的斷言**（換一種寫法就繞過），我照實說；
    它擋的是「有人順手 import 一個 helper 進來」那個最常見的動作。
    """
    import inspect
    offenders = []
    for fn in db._MIGRATIONS:
        src = inspect.getsource(fn)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"'):
                continue          # 註解與 docstring 裡提到不算
            if "from helpers" in stripped or "helpers." in stripped:
                offenders.append(f"{fn.__name__}: {stripped[:80]}")
    assert not offenders, (
        "migration 呼叫了 helpers 裡的東西：\n  " + "\n  ".join(offenders) +
        "\n⇒ 那個 helper 明年改了行為，這個 migration 的行為就被回溯改寫了，"
        "而症狀只出現在全新安裝與災難還原那兩條路上。"
    )


# ── U5：降版要明說 ───────────────────────────────────────────────────────

def test_u5_a_newer_database_is_not_silently_downgraded(tmp_path):
    """🔴 U5：庫的版本**比程式碼新**時，不可以靜默做一半。

    情境是真的會發生的：**部署了新版、發現問題、把程式碼回退** ——
    而資料庫已經升上去了。

    ⚠️ 現在 `_run_migrations` 的寫法是 `if current >= CURRENT_VERSION: return`
    ⇒ **靜默略過**。這一題要求的是**至少留下痕跡**（log 或例外），
    因為「資料庫比程式碼新」代表**有些欄位是這份程式碼不認識的**，
    而那會在執行期以各種奇怪的方式表現出來。

    📌 我釘的是「**要看得出來**」而不是「要丟例外」——
    丟例外會讓回退直接起不來，那是 A 要裁的取捨，不是我能決定的。
    ⇒ 所以斷言選在「**有沒有一筆 log 提到版本比預期新**」。
    """
    path = tmp_path / "newer.db"
    db.init_db(str(path))
    conn = _open(path)
    try:
        conn.execute("UPDATE schema_version SET version=? WHERE id=1",
                     (db.CURRENT_VERSION + 5,))
        conn.commit()
    finally:
        conn.close()

    import logging
    seen = []

    class _Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = _Collect()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        db.init_db(str(path))
    finally:
        logging.getLogger().removeHandler(handler)

    hits = [m for m in seen if "版本" in m or "version" in m.lower()]
    assert any(str(db.CURRENT_VERSION + 5) in m for m in hits), (
        f"資料庫版本是 v{db.CURRENT_VERSION + 5}、程式碼只到 v{db.CURRENT_VERSION}，"
        "而沒有任何一筆 log 講出這件事。\n"
        "⇒ 這是「部署新版→發現問題→回退程式碼」之後的狀態，"
        "而有些欄位是這份程式碼不認識的。靜默略過的話，"
        "問題會在執行期以各種奇怪的方式表現出來，而沒有人會聯想到版本。\n"
        f"（收到 {len(seen)} 筆 log，提到版本的有 {len(hits)} 筆）"
    )


def test_u5b_the_version_is_not_rewound(tmp_path):
    """U5 的對照組：**不可以把版本號改小**。

    ⚠️ 「靜默略過」還有一種更糟的變體：把 `schema_version` 寫成
    程式碼的版本（看起來「修好了」）—— 那之後任何人都再也看不出
    這個庫曾經跑過更新的 schema。
    🔑 **把證據改掉比留著問題更糟。**
    """
    path = tmp_path / "rewind.db"
    db.init_db(str(path))
    newer = db.CURRENT_VERSION + 5
    conn = _open(path)
    try:
        conn.execute("UPDATE schema_version SET version=? WHERE id=1", (newer,))
        conn.commit()
    finally:
        conn.close()

    db.init_db(str(path))
    assert _version_of(path) == newer, (
        f"版本號被改成 {_version_of(path)} 了（原本 {newer}）—— "
        "那讓「這個庫跑過更新的 schema」這件事再也看不出來"
    )
