# -*- coding: utf-8 -*-
"""`FN2` · 獎金分潤（`docs/windows/SPEC-BONUS.md` 施工圖）。

---

# ⚠️ 弱紅聲明：**獎金模組還不存在**（`routers/` 與 `helpers/` 都沒有 bonus）

⇒ 多題會紅在同一句話上。而**前三題不碰獎金模組**（只讀既有檔案），
   它們**現在就該綠** —— 它們紅表示我引用的那幾行變了，不是 B 沒做。

# 🔴 本檔的重心：**兩條「不報錯的錯」**

```
① 自己重算 netProfit  => **第三份實作**，而三份一定會分岔
② 退回用 grossProfit  => 毛利 > 淨利 => **獎金會發多**，而畫面上每個數字都正常
```
🔑 ② 特別難防：`routers/reports.py:340` **真的有那個 fallback**，而它對報表是合理的。
   ☠️ 照抄它到獎金模組 ⇒ 一個看起來有前例、而後果完全不同的決定。
⚠️ 而 A-2 實查：**開發機 12 張精算全部都有 `netProfit`、0 張舊格式**
   ⇒ **這一條在開發機上永遠不會被觸發** ⇒ 必須用假資料造一筆「只有 grossProfit」的來驗。
"""
import importlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"

_MODULES = ("helpers.bonus", "routers.bonus", "helpers.bonus_award",
            "routers.bonus_awards")

#: `§五` 的基點制（1/10000）。⚠️ 浮點相加不等於 1 是一個沒有錯誤訊息的缺陷。
BP = 10000


def _module():
    for name in _MODULES:
        try:
            return name, importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
    pytest.fail(
        "找不到獎金模組（找過：%s）。\n" % list(_MODULES)
        + "⚠️ 這是**弱紅**：本檔多題會紅在同一句話上。\n"
          "   名字可以換（**退回給我**），而那個接縫必須存在。")


def _seam(mod, where, *names):
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            return fn
    pytest.fail(
        "`%s` 沒有 %s。\n" % (where, " / ".join("`%s`" % n for n in names))
        + "⚠️ 名字可以換（**退回給我**）。")


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 不碰獎金模組的三題 —— **現在就該綠**
# ══════════════════════════════════════════════════════════════════════

def test_the_net_profit_formula_lives_in_exactly_one_place():
    """⚙️ **那兩個係數只寫在一個地方 —— 而獎金模組不可以變成第二份。**

    ```
    settlement.html:946  adminCost       = Math.round(quotedPretax * 0.10)
    settlement.html:947  charityDonation = Math.round(grossProfit * 0.01)
    ```
    🔑 `adminCost` 是**該案報價未稅的 10%** ⇒ 完全是案件本身的函數，
       與公司當期花了多少錢無關（這一點被講錯過一次，所以貼原始碼）。
    ⚙️ 這一題是下面那條禁令的**前提**：若係數本來就散在三個地方，
       「不可以再加一份」這句話就沒有意義了。
    """
    html = (_FRONTEND / "pages" / "settlement.html").read_text(encoding="utf-8")
    # 〔X-VAT，2026-09-26：算式改成 MotrixLegalRound.halfUp(quotedPretax, 0.10)／halfUp(grossProfit, 0.01)
    #   （四捨五入與後端一致；係數仍只在這裡）。原斷言："quotedPretax * 0.10"、"grossProfit * 0.01"〕
    assert "halfUp(quotedPretax, 0.10)" in html and "halfUp(grossProfit, 0.01)" in html, (
        "`settlement.html` 裡找不到那兩個係數 ——\n"
        + "🔑 算式搬家了 ⇒ **本檔引用的行號與禁令都要重寫**。")

    # 後端**不可以**有第二份乘法（它們只讀已存值）。
    hits = []
    for rel in ("pdf_gen.py", "routers/reports.py"):
        src = (_BACKEND / rel).read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            # X-VAT：也抓 round_half_up(x, 0.10) 這種寫法（乘法搬進捨入函式的參數）
            if re.search(r"\*\s*0\.10\b|\*\s*0\.01\b|,\s*0\.10\s*\)|,\s*0\.01\s*\)", line):
                hits.append("%s:%d %s" % (rel, i, line.strip()[:60]))
    assert not hits, (
        "後端已經有第二份係數：\n  " + "\n  ".join(hits)
        + "\n☠️ 那表示「只有一份實作」這個前提已經不成立了。")


def test_the_reports_fallback_to_gross_profit_really_exists():
    """⚙️ **證明「退回用毛利」那個前例是真的** —— 它是 `FN2` 禁令二的理由。

    ```
    routers/reports.py:340
      int(settle.get("netProfit") or settle.get("grossProfit") or 0)
    ```
    ☠️ 少了這一題，禁令二建立在**一段我沒有跑過的描述**上。
    🔑 而它同時說明為什麼那個禁令難守：**那個 fallback 對報表是合理的** ——
       它不是一段爛碼，它是一段**在別的脈絡下正確**的碼。
    📌 〈同一段碼在新脈絡下的風險不同〉。
    """
    src = (_BACKEND / "routers" / "reports.py").read_text(encoding="utf-8")
    assert re.search(r'settle\.get\("netProfit"\)\s*or\s*settle\.get\("grossProfit"\)',
                     src), (
        "`reports.py` 裡找不到 `netProfit or grossProfit` 的 fallback ——\n"
        + "🔑 它被改掉了 ⇒ **禁令二的理由要重寫**（那是好消息）。")


def test_case_stage_assignees_default_to_an_empty_json_array():
    """⚙️ **`case_stages.assigned_to` 的預設是 `'[]'`** —— `§四①` 的前提。

    ```
    db.py:1593  assigned_to TEXT NOT NULL DEFAULT '[]'
    ```
    ☠️ ⇒ 讀到空陣列是**常態不是例外** ⇒ 那個項目必須「拒絕撥付並標**無可發放對象**」，
       **不可以靜默算成 0 筆，也不可以把金額併給別的項目**。
    🔑 靜默算 0 的症狀：某一個獎金項目**從來沒有出現在任何一張獎金單上**，
       而沒有人會發現一個從來不出現的東西。
    """
    src = (_BACKEND / "db.py").read_text(encoding="utf-8")
    n = len(re.findall(r"assigned_to\s+TEXT\s+NOT NULL DEFAULT '\[\]'", src))
    assert n >= 1, (
        "`db.py` 裡 `case_stages.assigned_to` 不再預設 `'[]'` ——\n"
        + "🔑 那條「空陣列要拒絕」的規則的前提變了。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 基數：不可重算、不可退回用毛利
# ══════════════════════════════════════════════════════════════════════

def test_the_bonus_module_never_recomputes_the_coefficients():
    """🔴 **獎金模組裡不可以出現 `0.10` / `0.01` 那兩個係數。**

    ☠️ 第三份實作的症狀不是報錯，是**三份慢慢分岔** ——
       而分岔之後「獎金算出來跟精算頁對不上」會被當成**精算頁的錯**。
    ⚙️ 而這道絆線剝掉註解與字串才比對 —— 寫註解解釋「為什麼不自己乘」的人不該被罰。
    """
    where, mod = _module()
    path = Path(mod.__file__)
    src = path.read_text(encoding="utf-8")
    code = _strip_py_comments(src)
    hits = [(i, l.strip()[:70]) for i, l in enumerate(code.splitlines(), 1)
            if re.search(r"\*\s*0\.10\b|\*\s*0\.01\b|0\.10\s*\*|0\.01\s*\*", l)]
    assert not hits, (
        "`%s` 裡有那兩個係數：\n  " % path.name
        + "\n  ".join("%d: %s" % h for h in hits)
        + "\n☠️ 那是**第三份實作**（`settlement.html` 一份、"
          "`pdf_gen`/`reports` 只讀已存值）——\n"
          "   而三份一定會分岔，**分岔之後會被當成精算頁的錯**。\n"
        + "✅ 一律取 `settlement.summary.netProfit` 的已存值。")


def _strip_py_comments(src):
    """剝掉註解與字串（保留行號與長度）。與 `test_voucher_freeze` 同一支做法。"""
    import io
    import tokenize
    lines = src.splitlines(keepends=True)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
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


def test_a_legacy_settlement_without_net_profit_is_refused_and_says_the_way_out():
    """🔴🔴 **沒有 `netProfit` ⇒ 拒絕產生獎金單，而訊息要講出路。**

    ```
    舊精算（只有 grossProfit）=> 照抄 reports.py 的 fallback
    => 毛利 > 淨利（差 adminCost ＋ charityDonation）=> **獎金發多**
    => 而它不報錯，畫面上每一個數字都正常
    ```
    🔴 而拒絕訊息**必須講出路**，否則副作用是**舊案永遠發不了獎金**：
    > 「這個案件的精算是舊格式（沒有淨利欄位）。
    >  **請重新開啟並儲存一次該案的精算，系統會自動補算。**」
    🔑 與 `RAISE(ABORT)` 那一條同源：**那句話是使用者唯一看得到的東西。**

    ⚠️ **開發機沒有樣本**（A-2 實查：12 張精算全部都有 `netProfit`）
       ⇒ 這一題用**假資料**造一筆只有 `grossProfit` 的精算。
    ⚙️ 正對照：有 `netProfit` 的**必須成功**，否則「一律拒絕」也會讓上半綠。
    """
    where, mod = _module()
    fn = _seam(mod, where, "base_amount_for", "resolve_base", "_base_amount")

    legacy = {"summary": {"grossProfit": 1000000}}
    ok, base, err = _tri(fn(legacy))
    assert not ok, (
        "只有 `grossProfit` 的舊精算**通過了**（base=%r）——\n" % base
        + "☠️ 毛利 > 淨利 ⇒ **獎金發多**，而它不報錯。")
    for word in ("重新", "儲存", "精算"):
        assert word in str(err), (
            "拒絕訊息裡沒有「%s」：%r\n" % (word, err)
            + "☠️ 少了出路，副作用是**舊案永遠發不了獎金**，"
              "而使用者看不出路在哪裡。\n"
            + "📌 施工圖指定的形狀：「請**重新開啟並儲存一次**該案的**精算**，"
              "系統會自動補算。」")

    fresh = {"summary": {"grossProfit": 1000000, "netProfit": 880000}}
    ok2, base2, _e = _tri(fn(fresh))
    assert ok2 and base2 == 880000, (
        "有 `netProfit` 的精算算出 ok=%r base=%r（預期 True / 880000）——\n"
        % (ok2, base2)
        + "⚙️ 這是正對照：少了它，「一律拒絕」也會讓上面那些斷言綠，"
          "**而那樣一張獎金單都開不出來**。")


def test_a_net_profit_of_exactly_zero_is_not_reported_as_legacy_data():
    """🔴 **`netProfit` 是 `0` 與「沒有 `netProfit` 這個鍵」是兩件事。**

    ☠️ 用 `or` 合併的話：
    ```
    淨利真的是 0 的案子  => 收到「請重新開啟並儲存一次該案的精算」
    他照做 => **還是 0、訊息還是一樣** => 他會以為系統壞了
    ```
    🔑 〈null 不等於 0〉：「沒有值」與「值是零」在這裡的**處置完全相反** ——
       一個要他去補資料，另一個要告訴他「這一案沒有可分潤的淨利」。
    📌 **這一格是 B 主動加的**（我原本沒釘）—— 而我把它釘起來，
       是因為下一個改這段的人不會知道那個 `or` 為什麼不能寫。
    """
    where, mod = _module()
    fn = _seam(mod, where, "base_amount_for", "resolve_base", "_base_amount")
    _ok, _base, err = _tri(fn({"summary": {"grossProfit": 1000, "netProfit": 0}}))
    assert "重新" not in str(err), (
        "淨利是 `0` 的案子收到舊格式訊息：%r\n" % (err,)
        + "☠️ 他照著「重新儲存精算」做完 ⇒ **還是 0、訊息還是一樣**"
          " ⇒ 他會以為系統壞了。\n"
        + "🔑 「沒有這個鍵」與「值是 0」要分開判（`is None`，不是 `or`）。")


def _tri(out):
    """回傳形狀沒定版 ⇒ `(ok, base, err)` / `(base, err)` / 例外，都收。"""
    if isinstance(out, tuple) and len(out) == 3:
        return out
    if isinstance(out, tuple) and len(out) == 2:
        a, b = out
        if isinstance(a, bool):
            return a, None, b
        return (a is not None), a, b
    return (out is not None), out, ""


def test_a_negative_net_profit_pays_nothing():
    """🔴 **淨利為負 ⇒ 基數當 0，不發**（使用者裁）。

    ☠️ 不擋的話會算出**負的獎金** —— 而它在傳票上是一筆反向分錄，
       **帳是平的**，沒有人會報修。
    ⚙️ 正對照：`0` 與正數的行為要分得出來。
    """
    where, mod = _module()
    fn = _seam(mod, where, "base_amount_for", "resolve_base", "_base_amount")
    ok, base, _e = _tri(fn({"summary": {"netProfit": -500000}}))
    assert base == 0 or not ok, (
        "淨利 -500000 算出基數 %r ——\n" % base
        + "☠️ 負的獎金在傳票上是一筆反向分錄，**帳是平的**，沒有人會報修。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 基點算術與尾差
# ══════════════════════════════════════════════════════════════════════

def test_the_split_uses_basis_points_and_the_remainder_goes_to_the_company():
    """🔴 **比例用基點（1/10000），而尾差歸公司。**

    ```
    pool   = base × total_pct / 10000
    amount = pool × person_pct / 10000
    尾差   = pool - Σamount   ⇒ **歸公司**，不落在任何一個人身上
    ```
    ⚙️ 用浮點的話「相加不等於 1」是一個**沒有錯誤訊息**的缺陷。
    ⚠️ 而這一題刻意挑一組**除不盡**的數字：三個人各 3333 基點（合計 9999）。
       整除的數字**兩種實作都會綠**。
    """
    where, mod = _module()
    fn = _seam(mod, where, "split_award", "compute_lines", "_split")

    base = 1_000_001
    total_pct = 1000                      # 10%
    people = [("a", 3333), ("b", 3333), ("c", 3334)]
    out = fn(base, total_pct, people)
    amounts = [r["amount"] if isinstance(r, dict) else r[-1] for r in out]

    pool = base * total_pct // BP
    assert all(isinstance(a, int) for a in amounts), (
        "有金額不是整數：%r —— **金額一律用整數**。" % amounts)
    over = sum(amounts) - pool
    assert over <= 0, (
        "各人金額之和 %d **大於** pool %d（多了 %d）——\n"
        % (sum(amounts), pool, over)
        + "☠️ 那表示尾差被分給了某個人 ⇒ 公司付出去的比它決定的多。")
    assert pool - sum(amounts) < len(people), (
        "尾差是 %d，而只有 %d 個人 ——\n" % (pool - sum(amounts), len(people))
        + "☠️ 尾差大於人數表示**不是捨入誤差**，是算式錯了。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 一案一筆有效獎金，而作廢後可以重開
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def fresh_db(tmp_path):
    path = tmp_path / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _award(conn, quote_no="Q-001", voided=""):
    conn.execute(
        "INSERT INTO bonus_awards (quote_no, base_amount, created_by,"
        " created_at, updated_at, voided_at) VALUES (?,?,?,?,?,?)",
        (quote_no, 100000, "C", "2026-09-23T00:00:00",
         "2026-09-23T00:00:00", voided))
    conn.commit()


def test_one_case_has_at_most_one_live_award_but_can_be_reopened(fresh_db):
    """🔴🔴 **部分唯一索引：`WHERE voided_at = ''`。**

    ```
    第二筆未作廢   => IntegrityError
    把第一筆作廢   => 再開一筆 **OK**
    再開第三筆     => IntegrityError
    ⇒ **有效 1 列、歷史留著**
    ```
    ☠️ 寫成完全唯一（沒有 `WHERE`）的後果：**發錯了改不了** ——
       而傳票那邊有完整的作廢重開鏈（使用者親口裁的）
       ⇒ **兩個模組對「錯了怎麼辦」會不一致，而獎金還會開傳票。**
    ⚙️ 而「不做跨案件結算」**不是**靠這個索引 —— 它靠的是
       `quote_no` 是**單一欄位不是清單**。兩件事要分開講。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert "bonus_awards" in have, (
        "我在 `sqlite_master` 裡沒有找到 `bonus_awards`。\n"
        + "⚠️ 它**應該**存在 ⇒ 看 `v97`；`v97` 已完成 ⇒ "
          "**那它是被刪掉或改名了**。\n"
        + "⚠️ 這是**弱紅**。")

    _award(fresh_db)
    with pytest.raises(sqlite3.IntegrityError):
        _award(fresh_db)
    fresh_db.rollback()

    fresh_db.execute(
        "UPDATE bonus_awards SET voided_at='2026-09-23T01:00:00'"
        " WHERE quote_no='Q-001'")
    fresh_db.commit()
    _award(fresh_db)                       # ⚙️ 作廢之後必須開得起來

    with pytest.raises(sqlite3.IntegrityError):
        _award(fresh_db)
    fresh_db.rollback()

    n = fresh_db.execute(
        "SELECT COUNT(*) FROM bonus_awards WHERE quote_no='Q-001'").fetchone()[0]
    assert n == 2, (
        "`Q-001` 只剩 %d 筆（預期 2：一筆作廢、一筆有效）——\n" % n
        + "☠️ 歷史沒有留著 ⇒ **看不出這一案曾經發錯過**。")


def test_the_quote_no_column_is_a_single_case_not_a_list(fresh_db):
    """⚙️ **「不做跨案件結算」靠的是欄位形狀，不是唯一性。**

    📌 施工圖把這兩件事分開講，而它們很容易被當成同一件：
    ```
    不做跨案件結算  => `quote_no` 是**單一欄位**（不是 JSON 清單）
    一案一筆有效    => 部分唯一索引
    ```
    ☠️ 若 `quote_no` 變成 `quote_nos TEXT`（JSON 陣列），上面那題**照樣綠** ——
       而「依案件獨立發放」這句使用者原話就沒有了。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "bonus_awards" not in have:
        pytest.fail("`bonus_awards` 不存在 —— 見上一題。")
    cols = {r[1] for r in fresh_db.execute("PRAGMA table_info(bonus_awards)")}
    assert "quote_no" in cols, (
        "`bonus_awards` 沒有 `quote_no`。現有：%s\n" % sorted(cols)
        + "☠️ 若它變成一個清單欄位，一筆獎金就橫跨得了多案 ——"
          "而使用者明說**依案件獨立發放**。")
    assert not any(c in cols for c in ("quote_nos", "quote_no_json", "cases")), (
        "`bonus_awards` 有清單形狀的案件欄位：%s\n" % sorted(cols)
        + "☠️ 那讓一筆獎金橫跨多案 —— 使用者明說**依案件獨立發放**。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 人員來源與可見性
# ══════════════════════════════════════════════════════════════════════

def test_a_bonus_item_without_a_person_source_cannot_be_saved(fresh_db):
    """🔴 **`person_source` 為空不准儲存**（不是存了再算出 0 人）。

    ☠️ 存得下去的話，那個獎金項目**每次都算出 0 個人** ——
       而畫面上它只是**從來沒有出現在任何一張獎金單上**，
       🔑 **沒有人會發現一個從來不出現的東西。**
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "bonus_items" in have, (
        "我在 `sqlite_master` 裡沒有找到 `bonus_items`。\n"
        "⚠️ 它**應該**存在 ⇒ 看 `v97`；`v97` 已完成 ⇒ "
        "**那它是被刪掉或改名了**。")
    # 🔴 **我第一版多包了一層**（B 抓到）：內層產生器吐 `(欄位名, Row)`，
    #    外層的 `r[1]` 就變成 `Row` ⇒ **鍵是 Row 不是字串**
    #    ⇒ `"person_source" in cols` 恆為 False ⇒ 斷言觸發
    #    ⇒ 而訊息那一行要 `sorted(cols)` ⇒ `TypeError: Row 不能比大小`
    # ☠️ ⇒ 它紅在**訊息那一行**，而訊息說「`bonus_items` 沒有 `person_source`」——
    #    **一句錯的話，而它聽起來像量出來的**（與我 ⑤ 那次「v95 還沒有」同形）。
    cols = {c[1]: c for c in fresh_db.execute("PRAGMA table_info(bonus_items)")}
    assert "person_source" in cols, (
        "`bonus_items` 沒有 `person_source`。現有：%s" % sorted(cols))
    notnull = cols["person_source"][3]
    assert notnull, (
        "`person_source` 可以是 NULL ——\n"
        + "⚠️ `NOT NULL` 擋不住空字串，所以**應用層還要擋一次** ——"
          "而資料層先擋住 NULL 是最便宜的一半。")


def test_an_item_with_no_eligible_people_is_refused_not_silently_zero():
    """🔴 **來源解析出 0 人 ⇒ 拒絕該項目並標「無可發放對象」。**

    ```
    db.py case_stages.assigned_to TEXT NOT NULL DEFAULT '[]'
    ⇒ 空陣列是**常態不是例外**
    ```
    ☠️ 靜默算 0 的兩個後果，第二個更糟：
    ```
    ① 那個項目從來沒出現在任何一張獎金單上（沒有人會發現）
    ② **把金額併給別的項目** => 別人領多了，而總額對得起來
    ```
    """
    where, mod = _module()
    fn = _seam(mod, where, "people_for_item", "resolve_people", "_people_for")
    out = fn({"person_source": "case_stages.assigned_to"},
             {"quote_no": "Q-001", "stages": [{"assigned_to": "[]"}]})
    ok, people, note = _tri(out)
    assert not ok or not people, (
        "來源是空陣列而它算出 %r ——\n" % (people,)
        + "☠️ 那表示它從別的地方補了人。")
    assert "無可發放對象" in str(note) or "無可發放" in str(note), (
        "沒有回報「無可發放對象」，回的是 %r ——\n" % (note,)
        + "☠️ 靜默算 0 的話，那個項目**從來不會出現在任何一張獎金單上**，\n"
          "   而沒有人會發現一個從來不出現的東西。")


def test_a_person_only_sees_their_own_line():
    """🔴 **本人只看得到自己那一列；管理者看得到全部；其他人看不到。**

    ☠️ `§七` 逐字：**現行營運報表的可見範圍不可沿用** ——
       沿用＝**全公司看得到每個人領多少**。
    📌 「本人」是一條**規則**不是一個角色（`§37c`）⇒ 明著授予，不從角色推論。
    ⚙️ 三格都要：少了「其他人看不到」，一個「全部可見」的實作會讓前兩格綠。
    """
    where, mod = _module()
    fn = _seam(mod, where, "visible_lines", "filter_visible", "_visible")
    lines = [{"username": "alice", "amount": 100},
             {"username": "bob", "amount": 200}]
    assert [l["username"] for l in fn(lines, "alice", is_admin=False)] == ["alice"], (
        "alice 看到的不只是自己那一列 ——\n"
        + "☠️ 沿用營運報表的可見範圍＝**全公司看得到每個人領多少**。")
    assert len(fn(lines, "carol", is_admin=False)) == 0, (
        "沒有列的人 carol 也看得到東西 ——\n"
        + "⚙️ 這是第三格：少了它，「全部可見」也會讓上一格綠。")
    assert len(fn(lines, "root", is_admin=True)) == 2, (
        "管理者看不到全部 ——\n"
        + "⚙️ 這是正對照：少了它，「一律回空」也會讓上面兩格綠。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 科目代號不可寫死
# ══════════════════════════════════════════════════════════════════════

def test_the_payable_account_code_is_not_hardcoded():
    """🔴 **「應付獎金」的科目未決 ⇒ 不可以寫死進 DDL 或程式碼。**

    ```
    ✅ 存在設定裡（沿用 T100 六個欄位的形狀），**預設 2191 應付薪資**
    ```
    🔑 預設值的判準不是「哪個比較好」，是「**猜錯時哪個比較好收拾**」：
    ```
    用法定科目   => 日後要拆出來＝新增一個科目 ＋ 改設定
    用自訂科目而會計師說不行 => **已開出的傳票都指向一個不該存在的科目**
    ```
    # 🔴 **B 2026-09-23 指出我第一版守錯了對象**
    # ```
    # 我第一版  絆線找字面值 `"2191"`，而它**剝掉字串**才比對
    #           => 一個 `PAYABLE = "2191"` 然後到處用 `PAYABLE` 的實作，**一個字都看不到**
    #           => 而那正是「寫死」最常見的長相
    # ⚠️ 而 B 差一點為了躲這道守門，把 `"2191"` 寫成 `"2" "191"` 字串拼接
    #    —— 一段清楚的碼被寫成不清楚的，**而那道守門本來就看不到它**
    # ```
    # 🔑 ⇒ 改成守**機制**：科目代號必須**走設定**（`get_setting` 那條路），
    #    常數只能當 fallback。那樣兩種長相都分得出來。
    """
    where, mod = _module()
    path = Path(mod.__file__)
    src = path.read_text(encoding="utf-8")
    code = _strip_py_comments(src)

    fn = getattr(mod, "payable_account_code", None)
    assert callable(fn), (
        "`%s` 沒有 `payable_account_code()` ——\n" % where
        + "⚠️ 名字可以換（**退回給我**），而科目代號要**從一支函式取得**：\n"
          "   散在各處的話，改設定要改的是程式碼。")

    assert re.search(r"get_setting|_setting\(|settings\.", code), (
        "`%s` 沒有任何一處走設定（找過 `get_setting` …）——\n" % path.name
        + "☠️ 那表示科目代號是寫死的，而那個科目**還沒有決定**"
          "（會計師三題之一）。\n"
        + "✅ 存進設定，**常數只能當 fallback**。\n"
        + "📌 而這一題釘的是**機制不是字面值**：守字面值的話，"
          "`PAYABLE = \"2191\"` 再到處用 `PAYABLE` 會一個字都看不到 ——"
          "而那正是「寫死」最常見的長相。（B 2026-09-23 指出）")

    # ⚙️ 而字面值出現在**回傳路徑上**（不是 fallback）仍然要紅。
    bad = [(i, l.strip()[:70]) for i, l in enumerate(code.splitlines(), 1)
           if re.search(r"""return\s+["']2191["']""", l)]
    assert not bad, (
        "`%s` 直接 `return \"2191\"`：\n  " % path.name
        + "\n  ".join("%d: %s" % h for h in bad)
        + "\n☠️ 那不是 fallback，那是寫死。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 可見性：**打 router，不打函式**（A-2 複核提出）
# ══════════════════════════════════════════════════════════════════════

def _auth(client, make_user, role="superadmin", username=None):
    u, p = make_user(role=role, **({"username": username} if username else {}))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_award_with_two_lines(conn, alice, bob):
    # ⚠️ `bonus_award_lines.bonus_item_id REFERENCES bonus_items(id)` ——
    #    我第一版塞 `0` ⇒ `FOREIGN KEY constraint failed`，而訊息指向資料庫。
    #    🔑 又是探針壞掉：種資料要種**完整的那一串**，不是最少的那幾欄。
    conn.execute(
        "INSERT INTO bonus_items (name, person_source, created_by, created_at,"
        " updated_at) VALUES ('業務獎金','sales_person','C',"
        "'2026-09-23T00:00:00','2026-09-23T00:00:00')")
    item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO bonus_awards (quote_no, base_amount, created_by,"
        " created_at, updated_at) VALUES ('Q-VIS',1000000,'C',"
        "'2026-09-23T00:00:00','2026-09-23T00:00:00')")
    aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for who, amount in ((alice, 100), (bob, 200)):
        conn.execute(
            "INSERT INTO bonus_award_lines (award_id, bonus_item_id,"
            " item_name_snapshot, username, person_source_snapshot,"
            " total_pct, person_pct, amount) VALUES (?,?,?,?,?,?,?,?)",
            (aid, item_id, "業務獎金", who, "sales_person", 1000, 5000, amount))
    conn.commit()
    return aid


def test_the_awards_endpoint_actually_filters_by_viewer(client, make_user):
    """🔴🔴 **`GET /api/bonus/awards` 要真的過濾** —— 驗函式不等於驗呼叫端。

    ☠️ A-2 複核指出我原本那題的射程：
    ```
    我的 :473  取到 `visible_lines` 之後**直接呼叫它** ⇒ 函式守得完整 ✅
    而**沒有人驗「router 有沒有叫它」**
    ⇒ 漏叫一次 ⇒ **全公司每個人領多少在 API 回應裡**，而畫面完全正常
    ```
    🔑 〈兩個都對而路不存在〉：函式對、畫面對，**而中間那一段沒有人走過**。

    ⚙️ 三格都要（少一格就被「全部可見」或「一律回空」騙過）：
    ```
    alice   只看得到自己那一列，**而且看不到 base_amount**
    carol   與她無關的單**完全不出現**
    root    看得到全部
    ```
    """
    import db as _db
    _u_root, hdr_root = _auth(client, make_user, "superadmin", "vis_root")
    alice, hdr_alice = _auth(client, make_user, "user", "vis_alice")
    bob, _hdr_bob = _auth(client, make_user, "user", "vis_bob")
    _carol, hdr_carol = _auth(client, make_user, "user", "vis_carol")

    conn = _db.get_db()
    try:
        _seed_award_with_two_lines(conn, alice, bob)
    finally:
        conn.close()

    r = client.get("/api/bonus/awards", headers=hdr_alice)
    assert r.status_code == 200, r.text
    awards = r.json()["awards"]
    assert len(awards) == 1, (
        "alice 看到 %d 張單（預期 1）。\n" % len(awards)
        + "⚙️ 她在那張單上有一列 ⇒ 該看得到那張單"
          "（否則她收到一筆錢而查不到來源）。")
    names = [l["username"] for l in awards[0]["lines"]]
    assert names == [alice], (
        "alice 看到的分錄是 %s ——\n" % names
        + "☠️ **全公司每個人領多少在 API 回應裡**，而畫面完全正常。\n"
        + "🔑 最可能的成因是 router 沒有叫 `visible_lines` ——"
          "而那一支函式**自己是對的**（我另外驗過）。")
    assert "base_amount" not in awards[0], (
        "alice 看得到 `base_amount`（整案淨利 %r）——\n"
        % awards[0].get("base_amount")
        + "☠️ 那等於看得到整張單的規模 ⇒ 反推得出別人領多少。")

    r2 = client.get("/api/bonus/awards", headers=hdr_carol)
    assert r2.json()["awards"] == [], (
        "carol 在那張單上沒有任何一列，而她看得到它：%r\n"
        % r2.json()["awards"]
        + "⚙️ 這是第三格：少了它，「全部可見」也會讓上面兩格綠。")

    r3 = client.get("/api/bonus/awards", headers=hdr_root)
    assert r3.json()["awards"], "管理者看不到任何單 —— 「一律回空」也會讓上面綠。"
    assert len(r3.json()["awards"][0]["lines"]) == 2, (
        "管理者只看到 %d 列（預期 2）——\n"
        % len(r3.json()["awards"][0]["lines"])
        + "⚙️ 正對照：少了它，一個「永遠只回自己那列」的實作也會讓上面綠。")
