"""2026-09-21 · 第 3 輪（暖身輪）：供應商前置時間 ＋ 採購建議 ETA／狀態

對應 `docs/windows/STATE.md` §3 的 **11 條**驗收條件（1～9 ＋ 8b ＋ 8c）。
8c 不在這一份——A 指定「延伸既有的比對，不要新建一套」，所以它寫在
`test_system_audit_2026_09_14.py::test_every_backup_query_actually_runs` 裡。

---

## 🔴 我沒有讀實作

**這份測試是只讀 `STATE.md` §3 的開發單寫出來的。
我沒有開過 `backend/helpers/procurement.py`，也沒有開過 `backend/routers/inventory.py`。**

這一輪 ②（C 先寫紅測試）先於 ④（B 寫碼）的順序被打破了——B 的產品碼在我動手
之前就寫完了（A 承認是他沒先看 C 的位置就叫 B 開工）。紅燈順序的保證因此不存在，
**「我沒有讀實作」這句話是這一輪唯一剩下的憑據**，所以它必須是真的。

我是這樣在不讀實作的前提下取得契約的：
- 端點與回應欄位 ← `STATE.md` §3 明文規定
- 既有行為（燈號門檻 `ceil(safety_stock × 1.5)`、`items[]` 的欄位長相）
  ← **我自己的**既有測試 `test_purchase_suggestions_2026_09_07.py`
- 狀態轉移的端點路徑 ← FastAPI 的 route table（那是介面，不是實作）

**綠不代表對。** B 已經寫完了，綠是預期的。**紅才是資訊**——紅代表我跟 B 對 §3
的理解不一致，那是規格有歧義，要回報給 A，**不是改測試去遷就實作**。

---

## 這一份裡最容易變成假綠燈的三題

1. **條件 3（兩邊都沒填 → `null`）**。`0` 與 `null` 在畫面上**都會顯示成「今天到貨」**，
   是一個看起來很正常的錯誤答案。所以這題明確斷言 `is None`，
   而且**同時否定 `0`**——`assert x is None` 對 `x == 0` 會過不了，但寫成
   `assert not x` 就會兩個都放行。
2. **條件 7c（新一輪的 `orderedAt` 要是空的）**。只驗 `status` 的話，
   12 條驗收條件可以全綠而 bug 還在：「這一輪還沒下單，但下單時間是 3 天前」。
   **狀態欄對、時間欄對，合起來錯。**
3. **條件 8（開關關著時不擋）**。`grep -rn "LICENSE_GATE_ENABLED" backend/tests/`
   在本輪之前是**零命中**，而 middleware 第一行就是 `if not ...: return`——
   代表 `main.py` 那段守門主體從來沒有被任何測試執行過。這題是它的第一個涵蓋。
"""
import math
import uuid
from datetime import date, datetime, timedelta

import pytest


# ── 共用 helper（沿用 test_purchase_suggestions_2026_09_07.py 的既有樣板）────

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _admin(client, make_user):
    username, password = make_user(role="admin")
    return _auth(_login(client, username, password))


def _create_part(client, hdr, part_no, safety_stock, cost=100):
    r = client.post("/api/parts", headers=hdr, json={
        "partNo": part_no, "name": f"{part_no} 測試料件", "category": "其他",
        "safetyStock": safety_stock, "cost": cost,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_stock(part_no, qty, status="in_stock"):
    import db
    conn = db.get_db()
    now = datetime.now().isoformat()
    try:
        for _ in range(qty):
            conn.execute(
                "INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (part_no, f"{part_no}-{uuid.uuid4().hex[:8]}", status, "PO-TEST", 100, now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _remove_stock(part_no, qty):
    """把庫存「用掉」——改成 shipped，既有測試已釘住 shipped 不算在庫。"""
    import db
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM stock_items WHERE part_no=? AND status='in_stock' LIMIT ?",
            (part_no, qty),
        ).fetchall()
        assert len(rows) == qty, f"想扣 {qty} 件，但在庫只有 {len(rows)} 件"
        for row in rows:
            conn.execute("UPDATE stock_items SET status='shipped' WHERE id=?", (row["id"],))
        conn.commit()
    finally:
        conn.close()


def _add_supplier(name, lead_time_days=None):
    """直接寫 DB：避免猜 `POST /api/suppliers` 的欄位名。

    前置時間的 API 欄位名 §3 沒有規定（只規定了 DB 欄位 `lead_time_days` 與
    回應欄位 `lead_time_days`／`eta`），猜錯會紅在一個跟受測行為無關的地方。
    """
    import db
    conn = db.get_db()
    now = datetime.now().isoformat()
    try:
        cur = conn.execute(
            "INSERT INTO suppliers (name, lead_time_days, created_at, updated_at) "
            "VALUES (?,?,?,?)", (name, lead_time_days, now, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _set_part_lead_time(part_no, days):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE parts SET lead_time_days=? WHERE part_no=?", (days, part_no))
        conn.commit()
    finally:
        conn.close()


def _add_batch(part_no, batch_no, supplier_id, supplier_name, created_at):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (batch_no, part_no, supplier_id, supplier_name, created_at, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _suggestions(client, hdr):
    r = client.get("/api/inventory/purchase-suggestions", headers=hdr)
    assert r.status_code == 200, r.text
    return {i["part_no"]: i for i in r.json()["items"]}


# §3 明文寫的欄位名是 `lead_time_days`；B 實作回的是 `leadTimeDays`。
# **這個紅是刻意留著的**——A 的指示是「紅代表你和 B 對開發單理解不一致 ⇒
# 那是規格有歧義，回報給我，不要改測試去遷就實作」。
_LEAD_FIELD = "lead_time_days"
_LEAD_FIELD_ALT = "leadTimeDays"


def _lead(item):
    """讀前置時間欄位。名字對不上時，讓紅燈自己說清楚是哪一種不一致。"""
    if _LEAD_FIELD in item:
        return item[_LEAD_FIELD]
    if _LEAD_FIELD_ALT in item:
        raise AssertionError(
            f"§3 規定的欄位名是 `{_LEAD_FIELD}`，實際回的是 "
            f"`{_LEAD_FIELD_ALT}`（值 {item[_LEAD_FIELD_ALT]!r}）。"
            " 這不是功能沒做，是規格與實作對欄位命名不一致："
            "§3 寫的是資料庫欄位名（snake_case），"
            "而這支端點的既有欄位是 camelCase"
            "（safetyStock／inStockCount／stockLevel／orderedAt），B 跟了既有慣例。"
            " ⚠️ 不要把這一行改成 camelCase 來讓它變綠——那是改測試遷就實作。"
            "要改的是 §3 或實作，由 A 裁決（已寫進 C.md〈給彙整〉）。"
        )
    raise AssertionError(f"回應裡找不到前置時間欄位；實際 keys={sorted(item)}")


def _set_status(client, hdr, part_no, status):
    return client.post(
        f"/api/inventory/purchase-suggestions/{part_no}/status",
        headers=hdr, json={"status": status},
    )


def _columns(table):
    import db
    conn = db.get_db()
    try:
        return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


# ── 條件 1：欄位存在且預設 NULL ─────────────────────────────────────────────

@pytest.mark.parametrize("table", ["suppliers", "parts"])
def test_01_lead_time_column_exists_and_defaults_to_null(client, table):
    """§3 條件 1：`suppliers` 與 `parts` 都有 `lead_time_days`，**預設 NULL**。

    預設值是這題的重點，不是欄位存不存在：預設 `0` 會讓「沒填」在下游變成
    「前置時間 0 天」＝「今天到貨」，而那是一個看起來很正常的錯誤答案。
    """
    cols = _columns(table)
    assert "lead_time_days" in cols, f"{table} 沒有 lead_time_days 欄位；實際 {sorted(cols)}"
    assert cols["lead_time_days"]["dflt_value"] is None, (
        f"{table}.lead_time_days 的預設值是 {cols['lead_time_days']['dflt_value']!r}，"
        "應該是 NULL（沒填 ＝ 未知，不是 0）"
    )


def test_01b_new_row_really_gets_null_not_zero(client, make_user):
    """條件 1 的行為面：新建一筆真的拿到 NULL。

    `dflt_value` 是宣告，這一題驗的是**實際插進去的值**——有人在 INSERT 時
    補 `0` 的話，宣告仍然是 NULL 而資料是 0，上一題會綠、這一題會紅。
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "NULLPART", safety_stock=10)
    sid = _add_supplier("未填前置時間的供應商")

    import db
    conn = db.get_db()
    try:
        part = conn.execute(
            "SELECT lead_time_days FROM parts WHERE part_no=?", ("NULLPART",)).fetchone()
        sup = conn.execute(
            "SELECT lead_time_days FROM suppliers WHERE id=?", (sid,)).fetchone()
    finally:
        conn.close()

    assert part["lead_time_days"] is None, f"新料號拿到 {part['lead_time_days']!r}，應為 None"
    assert sup["lead_time_days"] is None, f"新供應商拿到 {sup['lead_time_days']!r}，應為 None"


# ── 條件 2：料號覆寫供應商 ──────────────────────────────────────────────────

def test_02_part_level_overrides_supplier_level(client, make_user):
    """§3 條件 2：料號有填 → 用料號的；料號沒填、供應商有填 → 用供應商的。

    兩個數字刻意取 7 與 30（差很遠且都不是 0），弄反了一眼就看得出來。
    """
    hdr = _admin(client, make_user)
    sid = _add_supplier("有前置時間的供應商", lead_time_days=30)

    # A：料號 7 天、供應商 30 天 → 該用 7
    _create_part(client, hdr, "OVERRIDE-PART", safety_stock=10)
    _add_stock("OVERRIDE-PART", 3)
    _add_batch("OVERRIDE-PART", "B-OV", sid, "有前置時間的供應商", "2026-09-01T00:00:00")
    _set_part_lead_time("OVERRIDE-PART", 7)

    # B：料號沒填、供應商 30 天 → 該用 30
    _create_part(client, hdr, "FALLBACK-PART", safety_stock=10)
    _add_stock("FALLBACK-PART", 3)
    _add_batch("FALLBACK-PART", "B-FB", sid, "有前置時間的供應商", "2026-09-01T00:00:00")

    items = _suggestions(client, hdr)
    assert _lead(items["OVERRIDE-PART"]) == 7, (
        f"料號填了 7、供應商填了 30，應該用料號的 7，實際 {_lead(items['OVERRIDE-PART'])!r}"
    )
    assert _lead(items["FALLBACK-PART"]) == 30, (
        f"料號沒填、供應商填了 30，應該退回供應商的 30，實際 {_lead(items['FALLBACK-PART'])!r}"
    )


# ── 條件 3：兩邊都沒填 → null（本檔最重要的一題）────────────────────────────

def test_03_unknown_lead_time_is_null_not_zero(client, make_user):
    """§3 條件 3：兩邊都沒填 → `lead_time_days` 與 `eta` 都是 `null`，**不是 0、不是今天**。

    ⚠️ 斷言刻意寫成 `is None` 而不是 `not x`：
    `assert not x` 對 `0`、`""`、`None` 全部都會通過，那就等於沒有在分辨
    「未知」與「0 天」——而這兩者在畫面上都會顯示成「今天到貨」。
    """
    hdr = _admin(client, make_user)
    sid = _add_supplier("沒填前置時間的供應商")  # 供應商也沒填
    _create_part(client, hdr, "UNKNOWN-PART", safety_stock=10)
    _add_stock("UNKNOWN-PART", 3)
    _add_batch("UNKNOWN-PART", "B-UNK", sid, "沒填前置時間的供應商", "2026-09-01T00:00:00")

    item = _suggestions(client, hdr)["UNKNOWN-PART"]

    assert _lead(item) is None, (
        f"兩邊都沒填，前置時間應該是 None，實際 {_lead(item)!r}"
        "（0 代表「今天到貨」，那是猜一個數字出來，不是承認算不出來）"
    )
    assert item["eta"] is None, (
        f"前置時間未知時 eta 應該是 None，實際 {item['eta']!r}"
    )
    # 把「看起來很正常的錯誤答案」逐一點名否定
    assert _lead(item) != 0
    assert item["eta"] != date.today().isoformat()
    assert item["eta"] != ""


# ── 條件 4：eta ＝ 今天 ＋ 前置時間 ─────────────────────────────────────────

@pytest.mark.parametrize("lead", [7, 30])
def test_04_eta_is_today_plus_lead_time(client, make_user, lead):
    """§3 條件 4：`eta` ＝ 今天 ＋ 前置時間。

    §3 要求「用固定日期測，不要用 `date.today()` 當預期值」。
    ⚠️ **這一點我只做到一半，已回報給 A**：這台機器沒有 `freezegun`，而要 monkeypatch
    實作取「今天」的來源就必須先知道它從哪裡取——那要讀實作，這一輪禁止。

    改用兩個差很遠的前置時間（7 與 30）跑同一條路徑：
    寫死成常數、或把 `eta` 直接填成今天，都會在其中一格露出來。
    仍然擋不住「實作與測試用同一個錯的今天」（例如都用 UTC 而正確答案是本地時間）。
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, f"ETA-{lead}", safety_stock=10)
    _add_stock(f"ETA-{lead}", 3)
    _set_part_lead_time(f"ETA-{lead}", lead)

    item = _suggestions(client, hdr)[f"ETA-{lead}"]
    assert _lead(item) == lead

    eta = item["eta"]
    assert isinstance(eta, str) and eta, f"eta 應該是日期字串，實際 {eta!r}"
    parsed = date.fromisoformat(eta)           # 格式不對就在這裡爆
    assert (parsed - date.today()).days == lead, (
        f"前置時間 {lead} 天，eta={eta}，距今 {(parsed - date.today()).days} 天"
    )
    assert parsed != date.today(), "eta 不可以是今天——那是前置時間未知時的錯誤答案"


# ── 條件 5／6：狀態轉移 ─────────────────────────────────────────────────────

def test_05_status_flows_suggested_to_ordered_to_received(client, make_user):
    """§3 條件 5：`suggested → ordered → received` 走得通，**每一步都記下時間**。"""
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "FLOW-PART", safety_stock=10)
    _add_stock("FLOW-PART", 3)

    item = _suggestions(client, hdr)["FLOW-PART"]
    assert item["status"] == "suggested", f"預設狀態應為 suggested，實際 {item['status']!r}"

    r = _set_status(client, hdr, "FLOW-PART", "ordered")
    assert r.status_code == 200, r.text
    item = _suggestions(client, hdr)["FLOW-PART"]
    assert item["status"] == "ordered"
    assert item.get("orderedAt"), f"轉成 ordered 要記下時間，實際 orderedAt={item.get('orderedAt')!r}"

    r = _set_status(client, hdr, "FLOW-PART", "received")
    assert r.status_code == 200, r.text


def test_06_skipping_middle_state_is_rejected(client, make_user):
    """§3 條件 6：跳過中間狀態（`suggested → received`）要被**拒絕**，不是靜默接受。

    「靜默接受」是這題真正在防的東西：回 200 但狀態沒變，看起來像成功了。
    所以這題同時驗「回非 2xx」**與**「狀態真的沒有被改掉」。
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "SKIP-PART", safety_stock=10)
    _add_stock("SKIP-PART", 3)
    assert _suggestions(client, hdr)["SKIP-PART"]["status"] == "suggested"

    r = _set_status(client, hdr, "SKIP-PART", "received")
    assert r.status_code >= 400, (
        f"suggested 直接跳 received 應該被拒絕，實際回 {r.status_code}：{r.text}"
    )
    assert _suggestions(client, hdr)["SKIP-PART"]["status"] == "suggested", (
        "被拒絕之後狀態不可以被改掉——回了錯誤碼但狀態還是變了，等於沒擋住"
    )


# ── 條件 7：received 之後 ───────────────────────────────────────────────────

def _advance_to_received(client, hdr, part_no):
    assert _set_status(client, hdr, part_no, "ordered").status_code == 200
    assert _set_status(client, hdr, part_no, "received").status_code == 200


def test_07a_received_and_restocked_disappears_from_list(client, make_user):
    """§3 條件 7a：`received` ＋ 庫存回到水位之上 → 不出現在清單。

    ⚠️ §3 明寫「**這是庫存算出來的，不是狀態抑制的**」，所以這題把庫存**真的**補上去，
    而不是只把狀態設成 received。
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "DONE-PART", safety_stock=10)
    _add_stock("DONE-PART", 3)
    _advance_to_received(client, hdr, "DONE-PART")

    _add_stock("DONE-PART", 17)          # 3 + 17 = 20 >= ceil(10*1.5)=15 → 綠燈
    assert "DONE-PART" not in _suggestions(client, hdr), (
        "庫存已補到黃燈門檻之上，不應再出現在採購建議清單"
    )


def test_07b_received_but_still_low_starts_a_new_round(client, make_user):
    """§3 條件 7b：`received` 但庫存仍低於水位 → **要再次出現，而且是新的一輪**。

    這題防的是「一個料號只能被採購一次」：半年後再度跌破水位時**安靜地不再被建議**。
    安靜地不做事是最難發現的那種壞法——沒有錯誤訊息、沒有紅燈，只是東西沒被買。
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "AGAIN-PART", safety_stock=10)
    _add_stock("AGAIN-PART", 3)
    _advance_to_received(client, hdr, "AGAIN-PART")

    _add_stock("AGAIN-PART", 4)          # 3 + 4 = 7，仍然 < 10 → 還是紅燈
    items = _suggestions(client, hdr)
    assert "AGAIN-PART" in items, (
        "收貨了但庫存仍低於安全水位，必須再次出現——否則這個料號等於只能被採購一次"
    )
    assert items["AGAIN-PART"]["status"] == "suggested", (
        f"新的一輪狀態應該回到 suggested，實際 {items['AGAIN-PART']['status']!r}"
    )


def test_07c_new_round_has_empty_ordered_at(client, make_user):
    """§3 條件 7c：新的一輪，`orderedAt` 必須是空的。

    ⚠️ **這題是整份裡最容易被漏掉的**：只驗 `status` 的話，其餘條件可以全綠而 bug 還在
    ——「這一輪還沒下單，但下單時間是 3 天前」。**狀態欄對、時間欄對，合起來錯。**
    （B 自我驗證時真的寫出過這個 bug，見 STATE §3 條件 7c。）
    """
    hdr = _admin(client, make_user)
    _create_part(client, hdr, "ROUND2-PART", safety_stock=10)
    _add_stock("ROUND2-PART", 3)

    _advance_to_received(client, hdr, "ROUND2-PART")
    _add_stock("ROUND2-PART", 4)         # 7 < 10，開新的一輪

    item = _suggestions(client, hdr)["ROUND2-PART"]
    assert item["status"] == "suggested"
    assert not item.get("orderedAt"), (
        f"新的一輪還沒下單，orderedAt 必須是空的，實際 {item.get('orderedAt')!r}"
        "（上一輪的下單時間留著 ＝ 狀態欄對、時間欄對，合起來說謊）"
    )


# ── 條件 8：授權開關關著時不擋（凍結期的安全保證）──────────────────────────

def test_08_license_gate_disabled_means_no_key_still_200(client, make_user, monkeypatch, tmp_path):
    """§3 條件 8：`LICENSE_GATE_ENABLED = False` 時，**沒有金鑰也照樣 200**。

    這是正式機現況的安全保證：`git archive` 只打包已追蹤內容 ⇒ 正式機**沒有**
    `license.key`。開關若不小心被打開，正式機會全站 402。

    ⚠️ 本輪之前 `grep -rn "LICENSE_GATE_ENABLED" backend/tests/` 是**零命中**，
    而 middleware 第一行就是 `if not ...: return` —— 代表守門主體從未被任何測試
    執行過。這題是它的第一個涵蓋。
    """
    from helpers import licensing as lic

    assert lic.LICENSE_GATE_ENABLED is False, (
        f"LICENSE_GATE_ENABLED 的出貨預設值是 {lic.LICENSE_GATE_ENABLED!r}，必須是 False。"
        "正式機沒有 license.key，開關預設開著會讓全站 402。"
    )
    # 保證真的處在「沒有金鑰」的狀態，不要靠開發機上剛好沒有那個檔
    monkeypatch.setattr(lic, "LICENSE_PATH", str(tmp_path / "no_such_dir" / "license.key"))
    assert lic.verify_license()["reason"] == "missing"

    hdr = _admin(client, make_user)
    r = client.get("/api/customers", headers=hdr)
    assert r.status_code == 200, (
        f"開關關著、又沒有金鑰，業務 API 仍必須是 200，實際 {r.status_code}：{r.text}"
    )


# ── 條件 8b：三個呼叫點在邊界值上燈號一致 ──────────────────────────────────

# safety_stock = 10 → 黃燈門檻 ceil(10 * 1.5) = 15
#   9 → red（紅／黃邊界的下緣）   10 → yellow（下緣）
#  14 → yellow（黃／綠邊界下緣）  15 → green（下緣）
_BOUNDARY = [(9, "red"), (10, "yellow"), (14, "yellow"), (15, "green")]


def _lights_from_every_endpoint(client, hdr, part_no):
    """把「所有會回燈號的端點」對這個料號算出的燈號收集起來。

    ⚠️ §3 明寫「**驗行為不要驗結構**」——所以這裡不去數原始碼裡有幾個 `1.5`，
    而是**問每一支會回燈號的端點**。B 之後多加一個呼叫點，這裡會自動把它算進來；
    寫成「檔案裡只能出現一次 1.5」那種測試，換個寫法就失效了。
    """
    lights = {}

    r = client.get("/api/inventory/parts-summary", headers=hdr)
    assert r.status_code == 200, r.text
    rows = r.json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    for row in rows:
        if row.get("part_no") == part_no and "stockLevel" in row:
            lights["parts-summary"] = row["stockLevel"]

    r = client.get("/api/inventory/purchase-suggestions", headers=hdr)
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if row.get("part_no") == part_no and "stockLevel" in row:
            lights["purchase-suggestions"] = row["stockLevel"]

    return lights


@pytest.mark.parametrize("qty, expected", _BOUNDARY)
def test_08b_all_call_sites_agree_on_the_light_at_boundaries(client, make_user, qty, expected):
    """§3 條件 8b：三個呼叫點在**邊界值**上算出的燈號必須一致。

    邊界值才是重點：`>` 寫成 `>=`、`ceil` 寫成 `int()`，在 12 與 20 這種中間值上
    三處會一致地算對，只有在 9/10/14/15 這四個點上才會分岔。

    ⚠️ 綠燈的料號不會出現在採購建議清單裡（既有行為），所以「一致」的定義是
    **有回答的端點彼此一致**，而不是每一支都必須回答。
    """
    hdr = _admin(client, make_user)
    part_no = f"BOUND-{qty}"
    _create_part(client, hdr, part_no, safety_stock=10)
    _add_stock(part_no, qty)

    assert math.ceil(10 * 1.5) == 15, "這份測試的邊界值是照 ceil(safety*1.5)=15 挑的"

    lights = _lights_from_every_endpoint(client, hdr, part_no)
    assert lights, f"沒有任何端點回報 {part_no} 的燈號，這題等於沒驗到東西"

    distinct = set(lights.values())
    assert len(distinct) == 1, f"庫存 {qty} 時各呼叫點燈號不一致：{lights}"
    assert distinct.pop() == expected, f"庫存 {qty} 應為 {expected}，實際 {lights}"


# ── 條件 9：題數不可少於上一輪 ─────────────────────────────────────────────
#
# 這一條不是一支測試，是⑥全量回歸的收斂條件（上一輪 1,111）。
# 結果寫在 docs/windows/C.md〈全量回歸結果〉，用 `pytest --collect-only` 對數字。
