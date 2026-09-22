"""§21 補 · **TD5~TD8 標註功能** —— 驗收條件（先寫紅）。

> 使用者 2026-09-22 凌晨原話：「增加一個標註的功能，
> **當這個標案被標誌，則顯示於標案的最上方**」
> 十一小時後：「**標註功能要做，時程你安排**」

---

# 🔴 最重要的一題是「標註存活過一次抓取」，而它現在是綠的

```
helpers/tender_source.py  現在是 `INSERT OR IGNORE`
⇒ **現狀安全** —— 而它隨時可能被改成 `INSERT OR REPLACE` 或加一個 UPDATE
```
☠️ **那一天標註會隨著每日抓取全部消失，而沒有任何錯誤訊息。**
使用者看到的是「我標的那幾筆不見了」，而沒有任何日誌會說話。
📌 **這正是 `TD1` 的鏡像**：那一次是 `INSERT` **漏了**兩個欄位（解析出來而沒寫進去），
這一次是 `INSERT` 會**洗掉**兩個欄位。
🔑 ⇒ 所以它**必須配反向控制**（把抓取改成會覆寫那兩欄 ⇒ 必須紅），
否則「現狀安全」與「有人在守它」在報告上長得一模一樣。

---

# ⚠️ 資料層：**一個可為 NULL 的時間戳兼任旗標**

```sql
marked_at  TEXT     -- NULL = 未標註
marked_by  INTEGER  -- users.id
```
☠️ 兩個欄位（`is_marked` ＋ `marked_at`）**會分岔**，而分岔之後沒有任何東西會紅。
⇒ 判定一律 `marked_at IS NOT NULL`，**不可用真假值**（〈null 不等於 0〉）。
⚠️ **而我的斷言也照這個**：不斷言 `is_marked == 1`，那個欄位不存在。

---

# 📌 `TD8`：「整批提前」不是「重新排過」

```
標註的那幾筆   **整批提到最前面**，而它們**內部照既有排序**（不另外排）
未標註的       也照既有排序
```
🔑 ⇒ 斷言要能分辨這兩件事 ——
☠️ **「重新排過」會讓使用者以為排序規則改了**，而那與功能壞掉長得不一樣、
更難察覺：他只會覺得「怎麼順序怪怪的」。

---

# ⚠️ 端點路徑 —— **規格第一版是錯的，留著錯的那一列**

```
❌ §21 補 第一版   POST/DELETE /api/tenders/{case_no}/mark
✅ 更正（740718c） POST/DELETE /api/tender-radar/tenders/{case_no}/mark
```
A 的查證：`grep -rn 'prefix="/api/tenders"' routers/` **零命中** ——
☠️ **那個前綴整個專案不存在。** A 自陳：「我寫了一個『看起來合理』的路徑，
而沒有打開那支 router。」

🔑 **而它差點進去的方式值得留著**：
```
我照條文**逐字**釘題 ⇒ **題目釘得越準，錯的條文就被釘得越穩**
```
📌 攔住它的不是題目寫得好，是**我退回去問了**而不是自己改條文、
也不是為了讓題目綠而遷就一個我覺得不對的位置。
⇒ `§6`：**寫規格時給出一個路徑／欄位名／常數名，要先去看那個檔** ——
「看起來合理」在規格裡與「查過」長得一模一樣，**而下游會把它當成已知事實去釘**。

⚠️ 權限跟著 `tender_radar` 模組走，**不另外發明一個**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

TENDERS_PATH = "/api/tender-radar/tenders"


def _mark_path(case_no):
    return f"/api/tender-radar/tenders/{case_no}/mark"


def _auth(client, make_user, username=None):
    u, p = make_user(username=username, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _items(body):
    if isinstance(body, list):
        return body
    for key in ("tenders", "items", "rows", "data"):
        if isinstance(body.get(key), list):
            return body[key]
    raise AssertionError(f"找不到清單本體，回傳的鍵有：{sorted(body)}")


def _case(item):
    return item.get("case_no") or item.get("caseNo")


def _list(client, hdr, query=""):
    r = client.get(TENDERS_PATH + ("?" + query if query else ""), headers=hdr)
    assert r.status_code == 200, f"?{query} 回 {r.status_code}：{r.text[:220]}"
    return [_case(x) for x in _items(r.json())]


@pytest.fixture()
def seeded(client):
    """五筆標案，**截止日刻意錯開**，讓「既有排序」是可預測的。

    既有排序：`ORDER BY (deadline IS NULL), deadline ASC, id DESC`
    ⇒ 預期順序 `M-01 → M-02 → M-03 → M-04 → M-05`（沒有標註時）。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no LIKE 'M-%'")
        rows = [
            ("M-01", "甲機關", "監控系統建置", "2026-10-01"),
            ("M-02", "乙機關", "網路設備採購", "2026-10-02"),
            ("M-03", "丙機關", "門禁系統更新", "2026-10-03"),
            ("M-04", "丁機關", "監控主機汰換", "2026-10-04"),
            ("M-05", "戊機關", "機房空調工程", "2026-10-05"),
        ]
        for case_no, org, name, deadline in rows:
            conn.execute(
                "INSERT INTO tenders (case_no, org, name, deadline,"
                " fetched_at) VALUES (?,?,?,?,?)",
                (case_no, org, name, deadline, "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    yield [r[0] for r in rows]
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no LIKE 'M-%'")
        conn.commit()
    finally:
        conn.close()


def _marked_row(case_no):
    """直接讀那兩欄 —— **判定用 `IS NOT NULL`，不用真假值。**"""
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT marked_at, marked_by FROM tenders WHERE case_no=?",
            (case_no,)).fetchone()
    finally:
        conn.close()
    assert row is not None, f"`{case_no}` 不存在（前提不成立）"
    return dict(row)


# ══════════════════════════════════════════════════════════════════════
# 資料層 · 一個可為 NULL 的時間戳兼任旗標
# ══════════════════════════════════════════════════════════════════════

def test_td6_the_mark_lives_on_the_tender_not_on_a_user_pair(client):
    """🔴 TD6：**標註是這一筆標案的屬性，不是「誰的清單」。**

    ⭐ 使用者裁示：**共用的** —— 一個人標了，全部的人都看得到。
    🔑 ⇒ 資料結構是 `tenders` 上的欄位，**不是 `(user_id, tender_id)` 一張表**。
    ☠️ 做成後者的話，「這一筆我們要投」會變成每個人各自的便利貼，
    而使用者要的是團隊共用的那一種。
    """
    import db
    conn = db.get_db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tenders)")}
    finally:
        conn.close()
    for need in ("marked_at", "marked_by"):
        assert need in cols, (
            f"`tenders` 沒有 `{need}` 欄位，現有：{sorted(cols)}\n"
            "📌 §21 補：`marked_at TEXT`（NULL = 未標註）＋ `marked_by INTEGER`。")
    assert "is_marked" not in cols, (
        "出現了 `is_marked` —— ☠️ 它與 `marked_at` **會分岔**，\n"
        "而分岔之後沒有任何東西會紅。\n"
        "🔑 §21 補：**用一個可為 NULL 的時間戳兼任旗標。**")


def test_td6_marking_records_who_and_when(client, make_user, seeded):
    """🔴 TD6：**留痕** —— 記誰標的、什麼時候標的。

    ☠️ 共用的東西沒有留痕，**「這是誰標的」就變成一個沒有答案的問題**，
    而標案是會被討論的東西。
    """
    hdr = _auth(client, make_user, "mark_owner")
    r = client.post(_mark_path("M-03"), headers=hdr)
    assert r.status_code in (200, 201, 204), f"{r.status_code} {r.text[:200]}"

    row = _marked_row("M-03")
    assert row["marked_at"] is not None, (
        "標註之後 `marked_at` 仍然是 NULL —— 那就是「沒有標註」。")
    assert row["marked_by"] is not None, (
        "`marked_by` 是 NULL ——\n"
        "☠️ 共用的標記沒有署名，日後會變成「沒有人記得為什麼標它」。")


def test_td6_unmarking_clears_both_columns(client, make_user, seeded):
    """🔴 TD6：**取消就是清掉**，兩欄都回 `NULL`，不留歷史。

    📌 A 的理由：**這是一個工作標記不是簽核紀錄**，留歷史會讓它變成另一種東西。
    ⚠️ 而「只清 `marked_at`、留著 `marked_by`」是最容易發生的半套 ——
    ☠️ 那會讓「誰標的」指向一個**已經不存在的標註**。
    """
    hdr = _auth(client, make_user, "mark_clear")
    client.post(_mark_path("M-02"), headers=hdr)
    assert _marked_row("M-02")["marked_at"] is not None, "前提不成立：沒標上"

    r = client.delete(_mark_path("M-02"), headers=hdr)
    assert r.status_code in (200, 204), f"{r.status_code} {r.text[:200]}"

    row = _marked_row("M-02")
    assert row["marked_at"] is None and row["marked_by"] is None, (
        f"取消之後那兩欄沒有都回到 NULL：{row}\n"
        "☠️ 只清一半的話，「誰標的」會指向一個已經不存在的標註。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 TD5 最重要的一題 · 標註要存活過一次抓取
# ══════════════════════════════════════════════════════════════════════

def test_td5_a_mark_survives_a_fetch(client, make_user, seeded):
    """🔴🔴 **標註一筆 → 跑一次抓取 → 標註仍在。**

    ☠️ `tender_source._store()` 現在是 `INSERT OR IGNORE` ⇒ **現狀安全** ——
    🔑 **而它隨時可能被改成 `INSERT OR REPLACE` 或加一個 UPDATE**，
    而那一天標註會隨著每日抓取全部消失，**沒有任何錯誤訊息**。
    📌 `TD1` 的鏡像：那次是 `INSERT` 漏了兩欄，這次是 `INSERT` 會洗掉兩欄。

    ⚠️ 這一題**綠著出生**（現狀就是安全的）⇒ 它的價值全部在下一題那支反向控制。
    """
    from helpers import tender_source
    import db

    hdr = _auth(client, make_user, "mark_fetch")
    client.post(_mark_path("M-04"), headers=hdr)
    before = _marked_row("M-04")
    assert before["marked_at"] is not None, "前提不成立：沒標上"

    # 同一筆 case_no 再被抓到一次（欄位值有變，模擬來源更新）
    again = [{"case_no": "M-04", "org": "丁機關",
              "name": "監控主機汰換（更新）", "published_at": "2026-09-23",
              "deadline": "2026-10-04", "budget": 999, "url": "",
              "tender_method": "公開招標", "procurement_type": "財物"}]
    conn = db.get_db()
    try:
        tender_source._store(conn, again)
        conn.commit()
    finally:
        conn.close()

    after = _marked_row("M-04")
    assert after["marked_at"] == before["marked_at"], (
        f"跑一次抓取之後標註被洗掉了：{before} → {after}\n"
        "☠️ 使用者看到的是「我標的那幾筆不見了」，"
        "而**沒有任何日誌會說話**。\n"
        "🔑 抓取的寫入路徑不可以碰 `marked_at`／`marked_by`。")
    assert after["marked_by"] == before["marked_by"], (
        f"`marked_by` 被抓取改掉了：{before} → {after}")


def test_td5_the_yardstick_a_fetch_that_overwrites_would_be_caught(
        client, make_user, seeded):
    """📏 **量尺：把抓取改成會覆寫那兩欄 ⇒ 上一題要紅。**

    ☠️ 少了這一題，「現狀安全」與「有人在守它」**在報告上長得一模一樣** ——
    🔑 而上一題是**綠著出生**的：它從寫出來的那一刻就沒有紅過。
    📌 今天付過兩次同樣的學費（`QL7` 八題全綠而功能零效果、
    `a14c` 第一版綠在「那一行沒被執行」）。

    ⚠️ **不改產品碼**：這裡直接模擬那個未來的寫法（`UPDATE … SET marked_at=NULL`），
    然後確認**那個差異是看得見的**。
    """
    import db

    hdr = _auth(client, make_user, "mark_yard")
    client.post(_mark_path("M-05"), headers=hdr)
    before = _marked_row("M-05")
    assert before["marked_at"] is not None, "前提不成立：沒標上"

    # 🔴 模擬「有人把抓取改成 INSERT OR REPLACE／加了一個 UPDATE」
    conn = db.get_db()
    try:
        conn.execute("UPDATE tenders SET marked_at=NULL, marked_by=NULL"
                     " WHERE case_no=?", ("M-05",))
        conn.commit()
    finally:
        conn.close()

    after = _marked_row("M-05")
    assert after["marked_at"] != before["marked_at"], (
        "把那兩欄清掉之後，`_marked_row()` 讀到的仍然一樣 ——\n"
        "☠️ 那代表上一題的觀測點根本沒有在讀那兩欄，\n"
        "🔑 而它的綠證明不了任何事。")


# ══════════════════════════════════════════════════════════════════════
# TD5 / TD7 / TD8 · 排序
# ══════════════════════════════════════════════════════════════════════

def test_td5_marked_tenders_come_first(client, make_user, seeded):
    """🔴 TD5：**被標註的顯示在清單最上方。**

    > 使用者原話：「當這個標案被標誌，**則顯示於標案的最上方**」
    """
    hdr = _auth(client, make_user, "mark_top")
    base = _list(client, hdr)
    assert base[:5] == ["M-01", "M-02", "M-03", "M-04", "M-05"], (
        f"既有排序與預期不同：{base[:5]}\n⇒ 這一題的前提不成立（種子或排序規則變了）。")

    client.post(_mark_path("M-04"), headers=hdr)
    after = _list(client, hdr)
    assert after[0] == "M-04", (
        f"標註之後它沒有排到最上方：{after[:5]}\n"
        "📌 使用者原話：「當這個標案被標誌，則顯示於標案的最上方」。")


def test_td8_marked_ones_keep_the_existing_order_among_themselves(
        client, make_user, seeded):
    """🔴 TD8：**整批提到最前面，而它們內部照既有排序** —— 不是重新排過。

    ☠️ 「重新排過」會讓使用者以為**排序規則改了** ——
    🔑 而那與功能壞掉不一樣，更難察覺：他只會覺得「順序怪怪的」。

    ⚠️ 這一題刻意**先標晚的、再標早的**：
    若實作是「照標註時間排」，順序會是 `M-05, M-03`；
    而條文要的是照既有排序 ⇒ `M-03, M-05`。
    """
    hdr = _auth(client, make_user, "mark_order")
    client.post(_mark_path("M-05"), headers=hdr)   # 先標截止日較晚的
    client.post(_mark_path("M-03"), headers=hdr)   # 後標較早的

    after = _list(client, hdr)
    assert after[:2] == ["M-03", "M-05"], (
        f"標註那兩筆的內部順序是 {after[:2]}，而既有排序要求 ['M-03', 'M-05']。\n"
        "☠️ 看起來是照**標註時間**排的 —— 而條文要的是「整批提前，內部不動」。\n"
        "🔑 重新排過會讓使用者以為排序規則改了。")
    assert after[2:5] == ["M-01", "M-02", "M-04"], (
        f"未標註的那幾筆順序也變了：{after[2:5]}\n"
        "⇒ 預期它們照既有排序（M-01, M-02, M-04）。")


def test_td7_unmarking_returns_it_to_its_original_position(
        client, make_user, seeded):
    """⚙️ TD7 反向控制：**取消標註 ⇒ 回到原本的排序位置，不是留在最上方。**

    ☠️ 少了這一題，一個「標過就永遠在最上面」的實作會讓 `TD5` 全綠 ——
    🔑 而使用者取消之後會發現它還在上面，**而他沒有辦法把它放回去**。
    """
    hdr = _auth(client, make_user, "mark_undo")
    client.post(_mark_path("M-04"), headers=hdr)
    assert _list(client, hdr)[0] == "M-04", "前提不成立：標註沒有讓它排到最前面"

    client.delete(_mark_path("M-04"), headers=hdr)
    after = _list(client, hdr)
    assert after[:5] == ["M-01", "M-02", "M-03", "M-04", "M-05"], (
        f"取消標註之後排序沒有回到原本的樣子：{after[:5]}\n"
        "☠️ 「標過就永遠在最上面」⇒ 使用者沒有辦法把它放回去。")


def test_td5_marking_does_not_break_the_existing_filter(
        client, make_user, seeded):
    """🔴 **排序不可以打破既有的篩選** ——

    「套了篩選之後，標註的仍然在最上方，而**篩選掉的不會因為被標註而冒出來**。」

    ☠️ 最容易寫出來的實作是「先把標註的 UNION 上去，再套篩選」——
    🔑 那會讓一筆**不符合搜尋條件**的標案因為被標註而出現在結果裡，
    📌 而使用者會以為搜尋壞了。
    """
    hdr = _auth(client, make_user, "mark_filter")
    # 先確認 q 篩得動（前提）
    only_monitor = _list(client, hdr, "q=監控")
    assert only_monitor and all(c in ("M-01", "M-04") for c in only_monitor), (
        f"`q=監控` 的結果與預期不同：{only_monitor}\n⇒ 這一題的前提不成立。")

    # 標一筆**不符合**那個關鍵字的
    client.post(_mark_path("M-05"), headers=hdr)          # 機房空調工程
    after = _list(client, hdr, "q=監控")
    assert "M-05" not in after, (
        f"被篩掉的標案因為被標註而冒出來了：{after}\n"
        "☠️ 使用者會以為搜尋壞了 —— 而它其實是排序把篩選吃掉了。")

    # 而符合的那一筆被標註之後要在最上方
    client.post(_mark_path("M-04"), headers=hdr)
    after = _list(client, hdr, "q=監控")
    assert after and after[0] == "M-04", (
        f"套了篩選之後，標註的沒有在最上方：{after}")


# ══════════════════════════════════════════════════════════════════════
# TD6 · 共用性
# ══════════════════════════════════════════════════════════════════════

def test_td6_one_person_marks_and_another_sees_it(client, make_user, seeded):
    """🔴 TD6：**甲標、乙看得到。**（使用者裁示：共用的。）

    ☠️ 做成「每個人自己的清單」的話，這一題會紅 ——
    🔑 而那個實作在**單人測試**下與正確的完全無法分辨。
    """
    a = _auth(client, make_user, "mark_alice")
    b = _auth(client, make_user, "mark_bob")

    client.post(_mark_path("M-02"), headers=a)
    seen_by_b = _list(client, b)
    assert seen_by_b[0] == "M-02", (
        f"甲標註的，乙看到的清單最上方是 {seen_by_b[:3]} ——\n"
        "☠️ 標註做成了「每個人自己的清單」，"
        "而使用者要的是團隊共用的那一種。")


def test_td6_anyone_with_the_module_can_unmark_someone_elses(
        client, make_user, seeded):
    """🔴 TD6：**共用的 ⇒ 任何有該模組的人都可以取消別人的標註。**

    📌 §21 補逐字：「任何有該模組的人都可以取消別人的標註，
    而畫面要讓他看得到是誰標的」。
    ⚠️ 而「只有標的人可以取消」是一個看起來很合理的錯誤實作 ——
    ☠️ 那個人請假的那一天，那一筆就沒有人能動它。
    """
    a = _auth(client, make_user, "mark_carol")
    b = _auth(client, make_user, "mark_dave")

    client.post(_mark_path("M-03"), headers=a)
    r = client.delete(_mark_path("M-03"), headers=b)
    assert r.status_code in (200, 204), (
        f"乙取消甲的標註被拒：{r.status_code} {r.text[:200]}\n"
        "☠️ 「只有標的人可以取消」⇒ 那個人請假時沒有人能動它。")
    assert _marked_row("M-03")["marked_at"] is None, "回了成功而沒有真的取消"


def test_td6_the_mark_endpoint_requires_the_radar_module(client, make_user,
                                                         seeded):
    """⚠️ 權限**跟著 `tender_radar` 模組走**，不另外發明一個。

    🔑 另設一個權限的話，第一個想標的人會被擋住，**而他不知道要找誰開**。
    ⚙️ 而這一題同時是「不要開太大」的反向控制：沒有那個模組的人不可以標。
    """
    u, p = make_user(username="mark_nomod", role="engineer",
                     modules=["dashboard"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    hdr = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.post(_mark_path("M-01"), headers=hdr)
    assert r.status_code == 403, (
        f"沒有 `tender_radar` 模組的人標註回了 {r.status_code}，預期 **403**。\n"
        "🔑 把可能的回應逐一講清楚，免得下一個人讀錯這條紅燈：\n"
        "   404／405 ⇒ **端點還不存在**（紅燈正確，功能還沒做）\n"
        "   401     ⇒ 連認證都沒過 —— 而這一題要驗的是**模組權限**，不是登入\n"
        "   200/204 ⇒ 🔴 **權限開太大**：沒有那個模組的人也標得動\n"
        "📌 §21 補：權限跟著 `tender_radar` 走，**不另外發明一個** ——\n"
        "   另設一個的話，第一個想標的人會被擋住，而他不知道要找誰開。")
