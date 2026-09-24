"""§13 VR1–VR5 · 版本紀錄停在 9/15。

使用者 2026-09-22：「**系統內的版本紀錄還停在 9/15**」。

---

# ☠️ 成因：版本紀錄不是算出來的，是一份手寫的 JSON

```
module_versions 資料表          361 列，最新 2026-09-15T19:10:00
backend/version_manifest.json   358 筆，mtime Sep 15 18:48
helpers/startup.py:318          開機時把 manifest 匯進資料表
```
🔑 **而 9/15 之後沒有人寫。** 這七天出貨的東西
（多據點、標案雷達、地圖、授權底座、FX／HC／SA／QL）**在系統裡一筆都沒有。**

📌 〈主持人的記憶是負債〉的標準形狀：**只要靠「記得要更新」，它就一定會停。**
⇒ 所以修法不是「把 9/16~9/22 補上」——**那是修結果**。
**判準：這個修法會不會讓第五次不可能發生？**

---

# ⚠️ 這道守門的代價，我明著寫在這裡

`VR1` 會在**任何一天有人 commit 而沒有寫一行版本紀錄**時變紅。
☠️ **那不是副作用，那就是它的功能** —— 而它的成本是真的：
每一個出貨日都要有人動手寫一行字。

🔑 **而不付這個成本的代價已經量到了：七天、整批遺忘、使用者用眼睛發現。**
📌 〈守門要驗「有沒有人做過決定」〉：
**這道守門不保證內容正確，只保證不會整批遺忘。**
⚠️ 它**擋不住亂填**（`VR2` 也擋不住）—— 守門永遠只能驗「有沒有人動手」。
"""
import json
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MANIFEST = BACKEND / "version_manifest.json"

#: 這一次要補的區間（VR3）。使用者是在 2026-09-22 指出它停在 9/15 的。
GAP_FROM = "2026-09-16"


def _entries():
    # ⚠️ `utf-8-sig`：產品碼就是這樣讀的（PS 5.1 重寫過會帶 BOM），
    #    測試用 `utf-8` 的話，有 BOM 的那天測試會紅在一個跟題目無關的理由上。
    with MANIFEST.open(encoding="utf-8-sig") as f:
        return json.load(f)


def _newest_entry_date():
    dates = [e.get("date", "") for e in _entries() if e.get("date")]
    assert dates, "`version_manifest.json` 裡一筆有日期的紀錄都沒有"
    return max(dates)


def _newest_commit_date():
    """這個 repo 最新一筆 commit 的日期（`YYYY-MM-DD`）。"""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cs"],
        cwd=str(BACKEND.parent), capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, (
        f"`git log` 跑不起來（exit={out.returncode}）：{out.stderr[:200]}\n"
        "☠️ 這一題不可以因此跳過 —— 跳過的話它就從「守門」變成「有時候會看一下」。")
    value = out.stdout.strip()
    assert len(value) == 10 and value[4] == "-", f"git 回了看不懂的日期：{value!r}"
    return value


# ══════════════════════════════════════════════════════════════════════
# VR1 · 打包前，manifest 不可以舊於最新的 commit
# ══════════════════════════════════════════════════════════════════════

def test_vr1_the_manifest_is_not_older_than_the_newest_commit():
    """🔴 VR1：`version_manifest.json` 最新的日期，不可以舊於最新 commit 的日期。

    ## 🔑 它守的是「有沒有人動手」，不是「寫得對不對」

    ☠️ 而現在它是紅的，紅的內容就是使用者看到的那件事：
    **manifest 停在 2026-09-15，而這七天有幾十個 commit。**

    ## ⚠️ 為什麼比「把 9/16~9/22 補上」重要

    補上是**修結果** —— 補完之後，第八天一樣會停。
    📌 〈修作法不要修結果〉的判準：**這個修法會不會讓第五次不可能發生？**
    ⇒ 一道在打包關卡上的守門會；一次補登不會。

    ## 📌 判準刻意只比**日期**，不比時間

    比到時分的話，「先 commit 再寫紀錄」這個**正常的順序**會紅。
    🔑 我們要擋的是「**整批遺忘**」，不是「順序不對」。
    """
    newest_entry = _newest_entry_date()
    newest_commit = _newest_commit_date()
    assert newest_entry >= newest_commit, (
        f"版本紀錄停在 {newest_entry}，而最新的 commit 是 {newest_commit}。\n"
        f"⇒ 中間這段時間出貨的東西，在系統的版本紀錄裡一筆都沒有。\n"
        "📌 補的來源不是記憶，是 `git log --since=<那一天>` 與 "
        "`docs/windows/STATE.md` 這幾天新增的節。"
    )


def test_vr1_the_two_dates_are_actually_comparable():
    """📏 量尺：兩邊都取得到值，而且格式一樣。

    ☠️ 少了這一題，`git log` 壞掉回空字串時 `"" >= ""` 會是**真** ——
    🔑 **一個取不到資料的比較，會給你它能給的最好結果。**
    """
    entry = _newest_entry_date()
    commit = _newest_commit_date()
    for label, value in (("manifest", entry), ("commit", commit)):
        assert len(value) == 10, f"{label} 的日期格式不是 YYYY-MM-DD：{value!r}"
        datetime.strptime(value, "%Y-%m-%d")      # 解不開就丟例外


# ══════════════════════════════════════════════════════════════════════
# VR2 · 反向控制：不可以靠亂填一筆變綠
# ══════════════════════════════════════════════════════════════════════

def test_vr2_the_newest_entries_are_not_placeholders():
    """🔴 VR2 反向控制：最新那一批每一筆都要有 `module`／`version`／`content`，
    而 `content` 長度 > 10。

    ☠️ 沒有這一題，一筆 `{"module": "x", "date": "今天"}` 就能讓 VR1 綠。

    ## ⚠️ 而**這一條本身也擋不住亂填**

    填 11 個字的廢話一樣會過。
    🔑 **守門永遠只能驗「有沒有人動手」** —— 這句話要留在這裡，
    📌 因為下一個讀到「VR1/VR2 都綠」的人，會以為版本紀錄的內容被驗過了。
    """
    newest = _newest_entry_date()
    batch = [e for e in _entries() if e.get("date") == newest]
    assert batch, f"找不到日期是 {newest} 的紀錄 —— 這一題的前提不成立"

    bad = []
    for e in batch:
        for field in ("module", "version", "content"):
            if not str(e.get(field) or "").strip():
                bad.append(f"{e.get('module', '?')}/{e.get('version', '?')}: 缺 {field}")
        if len(str(e.get("content") or "").strip()) <= 10:
            bad.append(f"{e.get('module', '?')}/{e.get('version', '?')}: content 太短")
    assert not bad, "最新這一批版本紀錄有佔位性質的內容：\n  " + "\n  ".join(bad)


# ══════════════════════════════════════════════════════════════════════
# VR3 · 把 9/16 ~ 9/22 補上，而且是一個模組一筆
# ══════════════════════════════════════════════════════════════════════

def test_vr3_the_gap_since_the_sixteenth_is_filled():
    """🔴 VR3：`2026-09-16` 之後要有版本紀錄。

    📌 來源**不是記憶**，是 `git log --since=2026-09-16` 與
    `docs/windows/STATE.md` 這七天新增的節（§8 FX／HC、§9 QL、§10 SA、
    §12 BK、§13 VR、§14 MN、§15 GC）。
    """
    entries = [e for e in _entries() if (e.get("date") or "") >= GAP_FROM]
    assert entries, (
        f"`{GAP_FROM}` 之後一筆版本紀錄都沒有 —— "
        "而那段時間出貨了多據點、標案雷達、地圖、授權底座與一批安全修正。"
    )


def test_vr3_one_entry_per_module_not_one_per_day():
    """🔴 VR3：**一個模組一筆，不是一天一筆。**

    🔑 畫面是依 `module` 分組的（`list_module_versions()` 用 `grouped[module]`），
    ☠️ 一天一筆的話，同一個模組會在七天裡長出七列，
    **而使用者要看的「這個模組最近改了什麼」會被七列流水帳蓋掉。**

    📌 2026-09-25 裁定（hichan-0a；使用者確認正式機＝46dc6ae，2026-09-24 02:46:15 部署）：
       「一包」＝**還沒出貨**的條目（不在正式機基準的 manifest 裡）。已出貨的屬於上一包，
       不算在這一包裡，而且不可以改寫（test_version_manifest_shipped_is_immutable）——
       舊判準把已出貨的也算進來，兩條守門就不可能同時綠（改寫已出貨的才能過 VR3）。
       基準見 `tests/_prod_baseline.py`，**每次部署後要更新**。
    """
    from tests._prod_baseline import BASELINE, baseline_manifest
    entries = [e for e in _entries() if (e.get("date") or "") >= GAP_FROM]
    if not entries:
        pytest.skip("VR3 還沒補 —— 見上一題（它會紅，這一題沒有東西可以驗）")
    dupes = unshipped_module_dupes(entries, baseline_manifest())
    assert not dupes, (
        "這一包（未出貨的條目）裡有模組出現超過一次：\n  " + "\n  ".join(dupes)
        + "\n⇒ 同一個模組這一包的改動要合併成一筆。"
        + "\n⚠️ 若其中較舊的那一筆**已經部署到正式機**，不要合併（已出貨的不可改寫）——"
          "是基準常數過期了：把 tests/_prod_baseline.py 的 BASELINE（目前 %s）改成目前正式機的 commit"
          "（登入後 /api/prod-status 或部署紀錄可查）。" % BASELINE
    )


def unshipped_module_dupes(entries, shipped):
    """同一模組出現一筆以上**未出貨**條目的清單。已出貨＝(module, version) 在正式機基準裡。"""
    shipped_keys = {(e.get("module"), e.get("version")) for e in shipped}
    seen, dupes = {}, []
    for e in entries:
        if (e.get("module"), e.get("version")) in shipped_keys:
            continue
        key = e.get("module")
        if key in seen:
            dupes.append(f"{key}（{seen[key]} 與 {e.get('version')}）")
        seen[key] = e.get("version")
    return dupes


def test_vr3_counts_only_unshipped_entries():
    """正對照：未出貨同模組兩筆 ⇒ 違規；反向控制：已出貨一筆＋未出貨一筆 ⇒ 不違規。"""
    old = {"module": "傳票", "version": "2026-09-23c"}
    new1 = {"module": "傳票", "version": "2026-09-24h"}
    new2 = {"module": "傳票", "version": "2026-09-25a"}
    assert unshipped_module_dupes([new1, new2], shipped=[old]) == ["傳票（2026-09-24h 與 2026-09-25a）"]
    assert unshipped_module_dupes([new1, old], shipped=[old]) == []
    assert len(unshipped_module_dupes([new1, old], shipped=[])) == 1, "基準過期時同樣的資料要紅（訊息指向基準）"


# ══════════════════════════════════════════════════════════════════════
# VR4 · 從畫面新增的那幾列，重裝之後會消失
# ══════════════════════════════════════════════════════════════════════

def test_vr4_entries_created_from_the_ui_are_distinguishable(client, make_user):
    """🔴 VR4：畫面新增的紀錄要標得出來（`updated_by != 'system'`）。

    ## ☠️ 那幾列**不會回寫進 manifest**

    ⚠️ **數字更正（A-2 2026-09-22 對鍵比過，我原本寫的是錯的）**：
    ```
    我寫的      361 vs 358，差「三列」
    實際        manifest 358 筆其中**有 1 組重複鍵**
                （`('每日工作事項','2026-07-22r')` ×2）⇒ 去重 357
                只在 DB、不在 manifest：**4 筆**（不是 3）
                只在 manifest、不在 DB：0 筆（當時）
                ⇒ 357 共有 + 4 = 361；357 + 1 重複 = 358。兩個數字都解釋掉了。
    ```
    🔑 我那個「差三列」是**兩個總數相減**得來的 ——
    ☠️ 而相減算不出「哪幾筆」，它只算得出「差幾個」，
    **而那兩件事在有重複鍵的時候不相等。**

    那四筆是從畫面 API 新增的。
    `_sync_module_versions()` 用的是 `INSERT OR IGNORE`：**只會多不會少**，
    而新資料庫是從 manifest 長出來的
    ⇒ **重裝或災難還原之後，那四列會消失。**

    ## 🔑 這一題不假裝那件事不存在，它把那幾列變成**數得出來的**

    ⚠️ 它**不修**那個缺陷（回寫 manifest 是另一件事，要 A 裁）——
    📌 它保證的是「**要搬家之前，有辦法知道哪幾列只存在於資料庫**」。
    ☠️ 而沒有這個標記的話，那四列會在還原之後安靜消失，
    **而「少了四列版本紀錄」沒有任何人會發現。**
    """
    import db

    username, password = make_user(username="vr4_admin", role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.241"})
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    r = client.post("/api/module-versions", headers=auth,
                    json={"module": "VR4 測試模組", "version": "2026-09-22a",
                          "content": "從畫面新增的一筆，用來驗它標不標得出來。"})
    assert r.status_code == 201, r.text

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT module, updated_by FROM module_versions "
            "WHERE updated_by != 'system'").fetchall()
    finally:
        conn.close()
    assert any(r["module"] == "VR4 測試模組" for r in rows), (
        "從畫面新增的紀錄沒有被標成非 system —— "
        "⇒ 重裝之前沒有辦法把它們挑出來，而還原之後它們會安靜消失。"
    )


# ══════════════════════════════════════════════════════════════════════
# VR5 · 停滯要看得出來
# ══════════════════════════════════════════════════════════════════════

def test_vr5_the_api_exposes_when_the_newest_entry_was(client, make_user):
    """🔴 VR5：畫面要看得出「最後一筆是什麼時候」。

    🔑 **停滯七天與正常運作，目前在畫面上長得一模一樣** ——
    ☠️ 使用者是**用眼睛比對**才發現的，而那不是一個可以依賴的偵測方式。

    ⚠️ 這一題只驗後端**給得出那個資訊**（`latest_updated_at`）；
    「超過 14 天就在頂端顯示一行提示」是 DOM 行為，見下一題（結構檢查）。
    """
    username, password = make_user(username="vr5_admin", role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.242"})
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    r = client.post("/api/module-versions", headers=auth,
                    json={"module": "VR5 測試模組", "version": "2026-09-22a",
                          "content": "用來確認 API 回得出最後更新時間。"})
    assert r.status_code == 201, r.text

    r = client.get("/api/module-versions", headers=auth)
    assert r.status_code == 200, r.text
    groups = r.json()
    assert groups, "版本紀錄 API 回了空清單 —— 這一題沒有東西可以驗"
    stamps = [g.get("latest_updated_at") for g in groups]
    assert any(stamps), (
        f"每一組都沒有 `latest_updated_at`：{groups[0] if groups else None}\n"
        "⇒ 畫面算不出「最後一筆是什麼時候」，停滯就看不出來。"
    )


def test_vr5_the_page_warns_when_the_record_has_gone_stale():
    """🔴 VR5：超過 14 天沒有新紀錄 ⇒ 畫面頂端要有一行提示。

    ⚠️ **結構檢查**：它擋得住「根本沒做」（今天就是這個狀態），
    擋不住「做了但門檻寫錯」或「提示藏在畫面外」。
    📌 真正的驗收是目視，而這句話寫在這裡，不寫在豁免表裡。

    ## ☠️ 我第一版的判準是 `"14" in text`，而它是**假綠燈**

    那一頁裡 `14` 出現 **17 次**，全部是 CSS 與日期：
    ```
    height: 14px;   padding: 4px 14px;   font-size: 14px;
    /* 2026-09-14：這頁的工具列… */      3×14 細條
    ```
    🔑 **一個數字出現在檔案裡，跟那個數字被拿來做判斷，是兩件事。**
    📌 而它**綠得毫無破綻** —— 我是因為「這題怎麼會一次就過」才回去查的。

    ⇒ 判準改成：**`<script>` 裡要有一個針對 14 的比較**。
    ⚠️ 不釘變數名、不釘文案、不釘 class（那些是設計與版面），
    只釘「**有人拿這個門檻做了判斷**」。
    """
    import re as _re

    page = BACKEND.parent / "frontend" / "pages" / "module-versions.html"
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")

    scripts = _re.findall(r"<script\b[^>]*>(.*?)</script>", text,
                          _re.S | _re.I)
    assert scripts, f"{page.name} 裡沒有 <script> 區塊 —— 這個檔的結構變了"
    code = "\n".join(scripts)
    # 允許 `> 14` / `>= 14` / `14 <` / `14 *` （天數換成毫秒那種寫法）
    hit = _re.search(r"(>=?|<=?)\s*14\b|\b14\s*(\*|<|>)", code)
    assert hit, (
        "`module-versions.html` 的 script 裡沒有任何針對 14 天的比較 ——\n"
        "⇒ 版本紀錄停掉的時候，畫面上跟正常運作長得一模一樣。\n"
        "📌 這一頁的 CSS 裡有很多個 `14`，那些不算。"
    )


def test_vr6_is_written_down_not_acted_on():
    """📌 VR6：`module_versions` 是〈只寫不刪〉的原始案例，**這一輪不要動它**。

    `daily_tasks.py:1138` 自己引用它當前身教訓。361 列不算大。
    ⚠️ 這一題**沒有斷言任何行為** —— 它存在的理由是
    **讓「我們決定不動它」這件事出現在測試檔裡，而不是只出現在規格散文裡**。
    🔑 〈散文對工具是隱形的〉：規格裡那一行，沒有任何工具讀得到。
    """
    rows = len(_entries())
    assert rows > 0, "manifest 是空的 —— 那不是「不動它」，那是壞了"
    assert date.today().year >= 2026      # 佔位：這一題不驗行為，見 docstring


# ══════════════════════════════════════════════════════════════════════
# VR7 / VR8 / VR9 · 守門要雙向，而兩個方向的意義完全不同
# ══════════════════════════════════════════════════════════════════════
#
# A-2 查出 `VR1` 只守一個方向。兩個方向：
# ```
# DB 有而 manifest 沒有     ☠️ 缺陷  —— 重建資料庫就永久消失（4 筆，已存在 52 天）
# manifest 有而 DB 沒有     ✅ 正確  —— 那是剛寫進 manifest、還沒重啟同步（9 筆）
# ```
# 🔑 **而把第二個方向寫成缺陷，會導出一個「啟動時強制同步」的修法** ——
# ☠️ **那正是 `_m035` 修掉的東西**（`db.py:2698-2707`）。
# 📌 〈答案沒錯，是題目問錯了〉：兩邊都是「對不上」，而處置相反。


def _drift():
    from helpers import startup
    fn = getattr(startup, "manifest_drift", None)
    assert fn is not None, (
        "`helpers/startup.py` 缺少 `manifest_drift()` —— "
        "VR7 要能分別回報兩個方向，而不是回一個「差幾列」的數字。")
    return fn


def test_vr7_a_row_only_in_the_database_is_reported(client):
    """🔴🔴 VR7：**DB 有而 manifest 沒有的列要被報出來。**

    ☠️ 那四筆已經存在 **52 天**，而 `_sync_module_versions()` 是
    `INSERT OR IGNORE`：**只會多不會少**，新資料庫是從 manifest 長出來的
    ⇒ **重建或災難還原之後它們永久消失，而沒有人會發現少了四列。**

    🔑 `VR1` 看不到這一個方向：它只比「最新日期」。
    📌 一個只守一個方向的守門，**它守不到的那一側不會給你紅燈**。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO module_versions (module, version, updated_at, content, "
            "updated_by) VALUES (?,?,?,?,?)",
            ("VR7 只在資料庫裡的模組", "2026-09-22z", "2026-09-22T00:00:00",
             "用來驗雙向守門的那一側。", "system"))
        conn.commit()
    finally:
        conn.close()

    drift = _drift()()
    db_only = drift.get("db_only") or []
    assert any("VR7" in str(item) for item in db_only), (
        f"DB 裡有一列不在 manifest 裡，而守門沒有報出來：{drift}\n"
        "⇒ 重建資料庫之後它會永久消失。")


def test_vr7_the_guard_goes_green_once_it_is_written_back(client, monkeypatch):
    """🔴 VR7 反向控制：**補進 manifest 之後要綠。**

    ☠️ 少了這一題，一個「永遠報有漂移」的實作會讓上一題全綠 ——
    而那道守門從此沒有人看。
    """
    import db
    from helpers import startup

    extra = {"module": "VR7 補回來的模組", "version": "2026-09-22y",
             "date": "2026-09-22", "time": "00:00",
             "content": "補進 manifest 之後，雙向守門要恢復綠燈。"}
    monkeypatch.setattr(startup, "_manifest_entries",
                        lambda: _entries() + [extra], raising=False)

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO module_versions (module, version, updated_at, content, "
            "updated_by) VALUES (?,?,?,?,?)",
            (extra["module"], extra["version"], "2026-09-22T00:00:00",
             extra["content"], "system"))
        conn.commit()
    finally:
        conn.close()

    drift = _drift()()
    db_only = [str(x) for x in (drift.get("db_only") or [])]
    assert not any("補回來" in x for x in db_only), (
        f"已經補進 manifest 了，守門還是把它報成漂移：{drift}")


def test_vr9_a_row_only_in_the_manifest_is_not_a_defect(client, monkeypatch):
    """🔴🔴 VR9：**`manifest 有而 DB 沒有` 是正確狀態，不可以寫成缺陷。**

    那 9 筆是 B 剛寫的 `VR3`，**開發機沒重啟所以還沒同步** ——
    ☠️ 把它寫成缺陷會導出一個「**啟動時強制同步**」的修法，
    🔑 **而那正是 `_m035`（`db.py:2698-2707`）修掉的東西。**

    📌 〈答案沒錯，是題目問錯了〉：
    兩個方向都是「對不上」，**而處置相反** ——
    ⚠️ 一個把兩者混成「差 N 列」的指標，會讓人去修錯的那一邊。
    """
    drift = _drift()()
    assert "manifest_only" in drift, (
        f"`manifest_drift()` 沒有把兩個方向分開回報：{sorted(drift)}\n"
        "⇒ 一個「差 N 列」的數字會讓人去修錯的那一邊。")
    assert isinstance(drift.get("manifest_only"), list)
    # 🔑 關鍵：它是**資料**不是**錯誤**。守門不可以因為它而判失敗。
    verdict = drift.get("ok")
    assert verdict is not None, (
        f"`manifest_drift()` 沒有給一個明確的成敗判定：{sorted(drift)}")
    if drift["manifest_only"] and not (drift.get("db_only") or []):
        assert verdict is True, (
            "只有「manifest 有而 DB 沒有」時被判定成失敗 —— "
            "那是等待重啟同步的正常狀態，不是缺陷。")
