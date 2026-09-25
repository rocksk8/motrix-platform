# -*- coding: utf-8 -*-
"""逐筆已讀，存伺服器（UR1）。

使用者（2026-09-24）：「點選後紅色未讀沒有即時消失」；表單「逐筆已讀，存在伺服器」。

## 在此之前的三個成因（都在前端，都存 localStorage）

```
選單數字   「看過」在下一頁載入時才寫，用戶端時鐘 vs 伺服器 audit_log.at 字串比
清單標記   以整個清單為單位的一個時間戳 ⇒ 開一筆不會清那一筆；自己改的也亮
換電腦     localStorage 跟著瀏覽器走 ⇒ 換一台就全部重來
```

## 規則

- `read_at` **一律伺服器時間**。唯一收用戶端時間的是 `/batch`（舊 localStorage
  一次性遷移），而它會被夾到「不晚於現在」，且只會把時間往後推、不會往前拉。
- 未讀＝「別人造成的最後一次變動」晚於 max(該筆 read_at, 清單基準)。
- 清單基準（`kind='baseline'`）：第一次查詢時若沒有，就以伺服器當下建立
  ⇒ 上線當天不會整片變成未讀。
- 未讀端點**只回呼叫者看得到的那幾筆**：看不到的那一筆有沒有動態，本身就是資訊。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from routers.dev_crm import _can_access_case
from helpers import row_access
# 直接取唯一來源（DEPENDENCY-MAP §3 #4）：經 routers.system 轉手會讓 item_reads 依賴整支 system
from helpers.module_registry import BADGE_PREFIXES as _MODULE_ACTION_PREFIXES
from helpers.module_registry import BADGE_EXCLUDE as _MODULE_EXCLUDE_ACTIONS

router = APIRouter()

#: 清單的 kind（有逐筆未讀判斷的）。
LIST_KINDS = ("dev_case", "case", "daily_task")
#: 可以被標記的 kind。`baseline` 只由伺服器建立或舊資料遷移。
MARKABLE_KINDS = LIST_KINDS + ("module",)
_MAX_KEY_LEN = 200
_MAX_KEYS = 1000

#: 選單數字：沒有任何「看過」紀錄的模組，往回看幾天（沿用 sidebar.js 原本的種子）。
_MODULE_LOOKBACK_DAYS = 7

#: dev_case 的刪除流程事件不算「有新動態」（同 system.py `_MODULE_EXCLUDE_ACTIONS`）。
_DEV_CASE_IGNORED = ("dev_case.delete", "dev_case.delete_request",
                     "dev_case.delete_cancel", "dev_case.delete_reject")


def _now() -> str:
    return datetime.now().isoformat()


def _norm(ts) -> str:
    """時間字串正規化成可以直接字串比較的形式。

    ⚠️ `case_updates.created_at` 預設是 `datetime('now','localtime')`＝**空白**分隔，
       其他是 `isoformat()`＝`T` 分隔。直接比的話 `' ' < 'T'`，
       同一天之內的動態永遠比已讀時間「早」⇒ 永遠不會亮。
    """
    return (ts or "").replace(" ", "T")


def _clean_key(key) -> str:
    k = str(key if key is not None else "").strip()
    if not k or len(k) > _MAX_KEY_LEN:
        raise HTTPException(400, "項目鍵不正確。")
    return k


def _upsert(conn, username, kind, key, at):
    """只會把時間往後推：已讀之後不會因為一筆較舊的寫入又變回未讀。"""
    conn.execute(
        "INSERT INTO item_reads (username, kind, item_key, read_at) VALUES (?,?,?,?) "
        "ON CONFLICT(username, kind, item_key) DO UPDATE SET "
        "read_at = MAX(item_reads.read_at, excluded.read_at)",
        (username, kind, key, at))


@router.post("/api/reads")
def mark_read(body: dict = Body(...), authorization: str = Header(None)):
    """標記一筆已讀。用戶端送來的任何時間欄位都忽略。"""
    user = _require_user(authorization)
    kind = (body or {}).get("kind")
    if kind not in MARKABLE_KINDS:
        raise HTTPException(400, "不支援的已讀類型。")
    key = _clean_key((body or {}).get("key"))
    conn = get_db()
    try:
        _upsert(conn, user["username"], kind, key, _now())
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/reads")
def list_reads(kind: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT kind, item_key, read_at FROM item_reads WHERE username=? AND kind=? "
            "ORDER BY item_key", (user["username"], kind)).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


def _legacy_time(raw) -> Optional[str]:
    """舊 localStorage 的時間：有的是本地 ISO（無時區），有的是 `toISOString()`（UTC、帶 Z）。"""
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    now = datetime.now()
    return min(dt, now).isoformat()


@router.post("/api/reads/batch")
def migrate_legacy_reads(body: dict = Body(...), authorization: str = Header(None)):
    """舊 localStorage「看過」紀錄的一次性遷移。

    🔴 這是唯一收用戶端時間的路 ⇒ 夾到「不晚於現在」：
       未來時間會讓之後的每一筆變動都被當成已讀，而沒有人看得出來。
    """
    user = _require_user(authorization)
    items = (body or {}).get("items") or []
    if not isinstance(items, list) or len(items) > _MAX_KEYS:
        raise HTTPException(400, "遷移資料格式不正確。")
    conn = get_db()
    n = 0
    try:
        for it in items:
            if not isinstance(it, dict):
                continue
            kind = it.get("kind")
            if kind not in MARKABLE_KINDS + ("baseline",):
                continue
            key = str(it.get("key") or "").strip()
            if not key or len(key) > _MAX_KEY_LEN:
                continue
            if kind == "baseline" and key not in LIST_KINDS:
                continue
            at = _legacy_time(it.get("read_at"))
            if not at:
                continue
            _upsert(conn, user["username"], kind, key, at)
            n += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "migrated": n}


# ── 未讀判斷 ────────────────────────────────────────────────────────────────

def _baseline(conn, username, kind) -> str:
    row = conn.execute(
        "SELECT read_at FROM item_reads WHERE username=? AND kind='baseline' AND item_key=?",
        (username, kind)).fetchone()
    if row:
        return row["read_at"]
    at = _now()
    _upsert(conn, username, "baseline", kind, at)
    conn.commit()
    return at


def _visible_keys(conn, user, kind, keys):
    admin = user["role"] in ("superadmin", "admin")
    if kind == "case":
        if admin:
            return keys
        ph = ",".join("?" * len(keys))
        frag, fparams = row_access.filter_sql("case", user, scope="read")
        rows = conn.execute(
            f"SELECT quote_no FROM quotations WHERE quote_no IN ({ph}){frag}",
            keys + fparams).fetchall()
        return [r["quote_no"] for r in rows]
    if kind == "dev_case":
        ids = [k for k in keys if k.isdigit()]
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, created_by, sales_persons, planners FROM dev_cases WHERE id IN ({ph})",
            ids).fetchall()
        return [str(r["id"]) for r in rows if _can_access_case(user, r)]
    if kind == "daily_task":
        # 每日工作的「有更新」標記原本就只給 admin 以上（daily-tasks.html isNewTask）。
        return keys if admin else []
    return []


def _latest_by_others(conn, user, kind, keys) -> dict:
    """{key: 別人造成的最後一次變動時間（已正規化）}。"""
    ph = ",".join("?" * len(keys))
    me, uid = user["username"], user["id"]
    if kind == "dev_case":
        ign = ",".join("?" * len(_DEV_CASE_IGNORED))
        rows = conn.execute(
            f"SELECT target_id AS k, at AS ts FROM audit_log "
            f"WHERE target_type='dev_case' AND target_id IN ({ph}) AND username != ? "
            f"AND action NOT IN ({ign}) "
            f"UNION ALL "
            f"SELECT CAST(case_id AS TEXT) AS k, created_at AS ts FROM dev_logs "
            f"WHERE CAST(case_id AS TEXT) IN ({ph}) AND COALESCE(created_by, log_by) != ?",
            keys + [me] + list(_DEV_CASE_IGNORED) + keys + [uid]).fetchall()
    elif kind == "case":
        # 與 `quotations.py::case_activity()` 同三個來源，差別在**依作者排除本人**。
        rows = conn.execute(
            f"SELECT quote_no AS k, created_at AS ts FROM case_updates "
            f"WHERE quote_no IN ({ph}) AND author != ? "
            f"UNION ALL "
            f"SELECT case_no AS k, created_at AS ts FROM work_logs "
            f"WHERE case_no IN ({ph}) AND COALESCE(NULLIF(created_by, 0), user_id) != ? "
            f"UNION ALL "
            f"SELECT dt.case_no AS k, dtc.completed_at AS ts "
            f"FROM daily_task_completions dtc JOIN daily_tasks dt ON dt.id = dtc.task_id "
            f"WHERE dt.case_no IN ({ph}) AND dtc.completed_at != '' AND dtc.username != ?",
            keys + [me] + keys + [uid] + keys + [me]).fetchall()
    elif kind == "daily_task":
        rows = conn.execute(
            f"SELECT target_id AS k, at AS ts FROM audit_log "
            f"WHERE target_type='daily_task' AND target_id IN ({ph}) AND username != ?",
            keys + [me]).fetchall()
    else:
        rows = []
    out = {}
    for r in rows:
        ts = _norm(r["ts"])
        k = str(r["k"])
        if ts > out.get(k, ""):
            out[k] = ts
    return out


_CHUNK = 300   # 每批 key 數：_latest_by_others 一批會用到 3 倍參數，舊版 SQLite 上限 999


def unread_keys(conn, user, kind, keys) -> list:
    """呼叫者看得到、且別人在他讀過（或未讀基準）之後動過的那幾筆。分批查，key 數不設上限
    （案件清單的「只看有新動態」要對全部案件判斷，不只已載入的那一頁，CM7）。"""
    base = _norm(_baseline(conn, user["username"], kind))
    out = []
    for i in range(0, len(keys), _CHUNK):
        part = _visible_keys(conn, user, kind, list(keys[i:i + _CHUNK]))
        if not part:
            continue
        ph = ",".join("?" * len(part))
        reads = {r["item_key"]: _norm(r["read_at"]) for r in conn.execute(
            f"SELECT item_key, read_at FROM item_reads WHERE username=? AND kind=? "
            f"AND item_key IN ({ph})", [user["username"], kind] + part)}
        latest = _latest_by_others(conn, user, kind, part)
        out += [k for k, ts in latest.items() if ts > max(reads.get(k, ""), base)]
    return sorted(out)


@router.post("/api/reads/unread")
def unread_items(body: dict = Body(...), authorization: str = Header(None)):
    """回 `{unread: [key...]}`：只含呼叫者看得到、且別人在他讀過之後動過的那幾筆。"""
    user = _require_user(authorization)
    kind = (body or {}).get("kind")
    if kind not in LIST_KINDS:
        raise HTTPException(400, "不支援的清單類型。")
    raw = (body or {}).get("keys") or []
    if not isinstance(raw, list) or len(raw) > _MAX_KEYS:
        raise HTTPException(400, "項目清單格式不正確。")
    keys = sorted({str(k).strip() for k in raw if str(k).strip()})
    conn = get_db()
    try:
        base = _norm(_baseline(conn, user["username"], kind))
        if not keys:
            return {"unread": [], "baseline": base}
        unread = unread_keys(conn, user, kind, keys)
    finally:
        conn.close()
    return {"unread": unread, "baseline": base}


@router.get("/api/reads/module-counts")
def module_counts(authorization: str = Header(None)):
    """選單數字：「看過」時間改讀伺服器（kind='module'）。

    數法與 `system.py::audit_module_counts()` 相同（前綴比對、排除本人、排除
    `_MODULE_EXCLUDE_ACTIONS`、`at > 看過時間`），但**只掃一次 audit_log**：
    原本每個模組各一句 COUNT（10 次），再經那支端點重驗一次 session。
    ⇒ 取「所有模組中最早的看過時間」之後、別人的事件，在記憶體依模組分桶。
    等價由 `test_module_counts_single_scan` 對照原函式守著。
    """
    user = _require_user(authorization)
    default = (datetime.now() - timedelta(days=_MODULE_LOOKBACK_DAYS)).isoformat()
    conn = get_db()
    try:
        seen = {r["item_key"]: r["read_at"] for r in conn.execute(
            "SELECT item_key, read_at FROM item_reads WHERE username=? AND kind='module'",
            (user["username"],))}
        since = {m: seen.get(m, default) for m in _MODULE_ACTION_PREFIXES}
        earliest = min(since.values())
        rows = conn.execute(
            "SELECT action, at FROM audit_log WHERE at > ? AND username != ?",
            (earliest, user["username"])).fetchall()
    finally:
        conn.close()
    counts = {m: 0 for m in _MODULE_ACTION_PREFIXES}
    for r in rows:
        action, at = r["action"] or "", r["at"] or ""
        for mod, prefixes in _MODULE_ACTION_PREFIXES.items():
            if (at > since[mod] and action.startswith(prefixes)
                    and action not in _MODULE_EXCLUDE_ACTIONS.get(mod, ())):
                counts[mod] += 1
    return counts
