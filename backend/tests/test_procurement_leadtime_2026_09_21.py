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
from datetime import datetime, timedelta

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


# API 回應的前置時間欄位名。
#
# 沿革（2026-09-21，`8b903eb`）：§3 原本寫 `lead_time_days`，而 B 的實作回
# `leadTimeDays`。這 4 題因此紅過一輪。**當時沒有把它改成 camelCase 讓它變綠**——
# 那會是「改測試遷就實作」，而且 A 就永遠不會知道規格寫錯，
# 錯的規格會留在檔案裡給下一棒照著做下一件事。
#
# 回報之後 A 裁決：**改 §3，不改實作**（那支端點既有欄位全是 camelCase：
# `safetyStock`／`inStockCount`／`stockLevel`／`orderedAt`／`receivedAt`；
# 原本的錯是把**資料庫欄位名**抄進了 **API 回應規格**，那是兩個命名空間）。
#
# ⚠️ 所以下面這一行現在是 camelCase，**理由是 §3 改了，不是因為實作長這樣**。
# ⚠️ **資料庫欄位仍然是 `suppliers.lead_time_days` / `parts.lead_time_days`**
#    （snake_case），條件 1 驗的就是那個，不要一起改。
_LEAD_FIELD = "leadTimeDays"
_LEAD_FIELD_ALT = "lead_time_days"


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


# ── 條件 3：兩邊都沒填 → null（本檔最重要的一題）────────────────────────────


# ── 條件 4：eta ＝ 今天 ＋ 前置時間 ─────────────────────────────────────────


# ── 條件 5／6：狀態轉移 ─────────────────────────────────────────────────────


# ── 條件 7：received 之後 ───────────────────────────────────────────────────


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


# ── 條件 9：題數不可少於上一輪 ─────────────────────────────────────────────
#
# 這一條不是一支測試，是⑥全量回歸的收斂條件（上一輪 1,111）。
# 結果寫在 docs/windows/C.md〈全量回歸結果〉，用 `pytest --collect-only` 對數字。
