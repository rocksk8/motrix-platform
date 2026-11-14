# -*- coding: utf-8 -*-
"""「我的報表」的儲存（T87 B2-S2）：表 `custom_reports`（＋`custom_report_shares`）的所有讀寫在這裡。

[單位] analytics:report_store    [層] M08    [穩定度] 實驗
[公開介面] MAX_PER_USER, NAME_MAX, MAX_SHARES, StoreError, copy_report, create, delete, etag_of, get_for_run, get_visible, list_mine, list_shared, mark_exported, redact_for_reader, update
[不變式] ①鍵＝擁有者登入帳號：路徑與請求本文都沒有帳號參數，只讀寫呼叫者自己的列；非擁有者（含不存在）一律回**逐字相同**的 404「找不到這份報表。」
    （被分享者例外：只在設定 `custom_reports.sharing` 開啟、且確實被分享時可讀；只能讀與複製，不能改、不能刪、不能再分享）。
    ②儲存的是**設定**，不是結果、不是授權：定義存檔前用 `report_runner.compile`（不執行）完整驗證；執行時一律用執行者當下的權限重新算（A 存、B 跑、降權後都不例外）。
    ③每人上限 `MAX_PER_USER`；同一人名稱不可重複（修剪空白後比對）；etag＝`updated_at`（含微秒；不符 ⇒ 409）；寫入前先拿寫鎖，上限與 etag 檢查與寫入同一個交易。
    ④刪除：設定 `custom_reports.recycle_deleted` 開且資源回收筒模組在 ⇒ 進刪除暫存區（可還原）；否則直接刪（連同分享列）。每一次都由後端當下讀設定決定。
    ⑥分享給別人看的定義一律先經 `redact_for_reader`：讀者沒有權限看的欄位，連同它的篩選門檻、分組、排序、彙總都不回傳，只回 `partiallyHidden` 旗標；
      有篩選／分組／排序被拿掉的報表不能複製（意義會變）。執行永遠用讀者自己的權限重算。
    ⑤分享對象：存在、在職、不是自己、≤ `MAX_SHARES`；分享設定關閉時不接受新的分享（既有列保留但不顯示）。
[契約題] backend/tests/platform/test_custom_reports_store_t87.py
"""
import json
from datetime import datetime

from core.txn import begin_write
from helpers import recycle_bin as RB
from helpers import report_catalog as RC
from helpers import report_policy as RP
from helpers import report_runner as RR

_COLS = "id, username, name, source_id, definition_json, created_at, updated_at, last_exported_at"
MAX_PER_USER = 30
NAME_MAX = 40
MAX_SHARES = 20
NOT_FOUND = "找不到這份報表。"


class StoreError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details or {}


def _now():
    return datetime.now().isoformat()                      # 含微秒（etag 用）


def etag_of(row) -> str:
    return row["updated_at"]


def _clean_name(name) -> str:
    if not isinstance(name, str):
        raise StoreError(422, "請輸入報表名稱。")
    n = " ".join(name.split())
    if not n:
        raise StoreError(422, "請輸入報表名稱。")
    if len(n) > NAME_MAX:
        raise StoreError(422, "報表名稱最多 %d 個字。" % NAME_MAX)
    return n


def _dump(definition) -> str:
    return json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _validated(definition, user, conn):
    """存檔前驗證（不執行）。回 (source_id, 序列化後 JSON)。拒絕 ⇒ RR.ReportError（呼叫端轉 HTTP）。"""
    plan = RR.compile(definition, user, "preview", conn=conn)
    return plan.source_id, _dump(definition)


def _row(conn, rid):
    return conn.execute("SELECT %s FROM custom_reports WHERE id=?" % _COLS, (rid,)).fetchone()


def _shared_with(conn, rid):
    return [r["shared_with"] for r in conn.execute("SELECT shared_with FROM custom_report_shares WHERE report_id=? ORDER BY shared_with", (rid,))]


def _is_shared_to(conn, rid, username) -> bool:
    return conn.execute("SELECT 1 FROM custom_report_shares WHERE report_id=? AND shared_with=?", (rid, username)).fetchone() is not None


def _summary(r, shared_count=0, owner_name=None):
    d = {"id": r["id"], "name": r["name"], "sourceId": r["source_id"], "updatedAt": r["updated_at"], "lastExportedAt": r["last_exported_at"]}
    if owner_name is not None:
        d["ownerName"] = owner_name
    else:
        d["sharedCount"] = shared_count
    return d


def list_mine(conn, user) -> list:
    rows = conn.execute("SELECT %s FROM custom_reports WHERE username=? ORDER BY updated_at DESC, id DESC" % _COLS, (user["username"],)).fetchall()
    counts = {}
    if rows and RP.sharing_enabled(conn):
        counts = {r[0]: r[1] for r in conn.execute(
            "SELECT report_id, COUNT(*) FROM custom_report_shares WHERE report_id IN (%s) GROUP BY report_id" % ",".join("?" * len(rows)),
            [r["id"] for r in rows])}
    return [_summary(r, counts.get(r["id"], 0)) for r in rows]


def list_shared(conn, user) -> list:
    """分享給我的（設定關閉時回空）。"""
    if not RP.sharing_enabled(conn):
        return []
    rows = conn.execute(
        "SELECT r.id, r.username, r.name, r.source_id, r.updated_at, r.last_exported_at, COALESCE(NULLIF(u.display_name,''), r.username) AS owner_name FROM custom_report_shares s "
        "JOIN custom_reports r ON r.id = s.report_id LEFT JOIN users u ON u.username = r.username "
        "WHERE s.shared_with=? ORDER BY r.updated_at DESC, r.id DESC", (user["username"],)).fetchall()
    return [_summary(r, owner_name=r["owner_name"]) for r in rows]


def redact_for_reader(defn, user):
    """分享給別人看的定義：凡是讀者**沒有權限看**的欄位，相關的顯示欄、篩選（含門檻值）、分組、彙總、排序一律在後端移除，
    只回傳「有東西因權限不顯示」的旗標。來源讀者用不到（沒有模組存取）⇒ 只留來源代號。回 `(定義, 移除了什麼)`；
    移除了篩選／分組／排序＝報表意義會改變（`semantic`），顯示欄與彙總欄不影響篩選結果。"""
    if not isinstance(defn, dict):
        return {"version": 1}, {"semantic"}
    sid = defn.get("source")
    if not isinstance(sid, str) or not RC.source_available(sid, user):
        return {"version": 1, "source": sid if isinstance(sid, str) else None}, {"semantic", "display"}
    vis = RC.visible_fields(sid, user)
    removed = set()
    out = dict(defn)

    def keep(items, key, kind, special=None):
        res = []
        for x in items or []:
            fid = x if isinstance(x, str) else (x.get("field") if isinstance(x, dict) else None)
            if special is not None and fid == special or vis.get(fid):
                res.append(x)
            else:
                removed.add(kind)
        return res
    for key, kind, special in (("columns", "display", None), ("filters", "semantic", None), ("groupBy", "semantic", None),
                               ("aggregates", "display", "*"), ("sort", "semantic", None)):
        if defn.get(key) is not None:                         # 沒有的鍵不憑空加（filters 缺＝用來源預設條件）
            out[key] = keep(defn.get(key), key, kind, special)
    return out, removed


def _readable_row(conn, user, rid):
    """擁有者，或（分享開啟且被分享）的人可讀的列；其餘一律 404（與不存在逐字相同）。回 (列, 是否擁有者)。"""
    r = _row(conn, rid)
    if r is None:
        raise StoreError(404, NOT_FOUND)
    mine = r["username"] == user["username"]
    if not mine and not (RP.sharing_enabled(conn) and _is_shared_to(conn, rid, user["username"])):
        raise StoreError(404, NOT_FOUND)
    return r, mine


def get_for_run(conn, user, rid) -> dict:
    """給匯出用：回 `{"id", "name", "sourceId", "definition"（原始、未去識別）, "isOwner"}`。定義**只能**交給 `report_runner.compile`
    （它以執行者自己的權限重新驗證與遮罩），不可回給呼叫端或寫進輸出。"""
    r, mine = _readable_row(conn, user, rid)
    return {"id": r["id"], "name": r["name"], "sourceId": r["source_id"], "definition": json.loads(r["definition_json"]), "isOwner": mine}


def mark_exported(conn, user, rid) -> None:
    """擁有者匯出成功後記下 `last_exported_at`（被分享者匯出不改擁有者的列）。"""
    began = begin_write(conn)
    try:
        conn.execute("UPDATE custom_reports SET last_exported_at=? WHERE id=? AND username=?", (_now(), rid, user["username"]))
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise


def get_visible(conn, user, rid) -> dict:
    """擁有者，或（分享開啟且被分享）的人。其餘一律 404（與不存在逐字相同）。"""
    r, mine = _readable_row(conn, user, rid)
    defn = json.loads(r["definition_json"])
    hidden_part = False
    if not mine:
        defn, removed = redact_for_reader(defn, user)
        hidden_part = bool(removed)
    out = {"id": r["id"], "name": r["name"], "sourceId": r["source_id"], "definition": defn,
           "etag": etag_of(r), "isOwner": mine, "updatedAt": r["updated_at"], "lastExportedAt": r["last_exported_at"]}
    if not mine:
        out["partiallyHidden"] = hidden_part                 # 部分條件或欄位因權限不顯示（讀者自己的權限；執行時照樣用讀者權限重算）
    if mine:
        out["sharedWith"] = _shared_with(conn, rid) if RP.sharing_enabled(conn) else []
    else:
        o = conn.execute("SELECT COALESCE(NULLIF(display_name,''), username) FROM users WHERE username=?", (r["username"],)).fetchone()
        out["ownerName"] = o[0] if o else r["username"]
    return out


def _raw_definition(conn, rid):
    r = _row(conn, rid)
    return json.loads(r["definition_json"]) if r is not None else {}


def _check_targets(conn, user, names) -> list:
    if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
        raise StoreError(422, "分享對象格式不正確。")
    uniq = sorted({x.strip() for x in names if x.strip()})
    if len(uniq) > MAX_SHARES:
        raise StoreError(422, "最多只能分享給 %d 位同事。" % MAX_SHARES)
    if user["username"] in uniq:
        raise StoreError(422, "不需要分享給自己。")
    if uniq:
        ok = {r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND username IN (%s)" % ",".join("?" * len(uniq)), uniq)}
        bad = [x for x in uniq if x not in ok]
        if bad:
            raise StoreError(422, "找不到下列同事，或已停用：%d 位。請重新選擇。" % len(bad), {"count": len(bad)})
    return uniq


def create(conn, user, name, definition) -> dict:
    n = _clean_name(name)
    source_id, dumped = _validated(definition, user, conn)
    began = begin_write(conn)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM custom_reports WHERE username=?", (user["username"],)).fetchone()[0]
        if cnt >= MAX_PER_USER:
            raise StoreError(422, "我的報表最多 %d 份，請先刪除不需要的報表。" % MAX_PER_USER)
        if conn.execute("SELECT 1 FROM custom_reports WHERE username=? AND name=?", (user["username"], n)).fetchone():
            raise StoreError(409, "已有同名的報表，請換一個名稱。", {"reason": "duplicate_name"})
        now = _now()
        cur = conn.execute("INSERT INTO custom_reports (username, name, source_id, definition_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                           (user["username"], n, source_id, dumped, now, now))
        rid = cur.lastrowid
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    return get_visible(conn, user, rid)


def update(conn, user, rid, etag, body) -> dict:
    """擁有者改名稱／定義／分享對象（只送要改的鍵）。etag 不符 ⇒ 409。"""
    if not isinstance(body, dict) or set(body) - {"name", "definition", "sharedWith"} or not body:
        raise StoreError(422, "沒有可以儲存的修改。")
    name = _clean_name(body["name"]) if "name" in body else None
    dumped = source_id = None
    if "definition" in body:
        source_id, dumped = _validated(body["definition"], user, conn)
    began = begin_write(conn)
    try:
        r = _row(conn, rid)
        if r is None or r["username"] != user["username"]:
            raise StoreError(404, NOT_FOUND)
        if (etag or "") != etag_of(r):
            raise StoreError(409, "這份報表已在其他視窗修改，請重新載入。", {"reason": "etag"})
        shares = None
        if "sharedWith" in body:
            if not RP.sharing_enabled(conn):
                if body["sharedWith"]:
                    raise StoreError(403, "公司目前不開放分享報表。", {"reason": "sharing_off"})
            else:
                shares = _check_targets(conn, user, body["sharedWith"])
        if name is not None and name != r["name"] and conn.execute(
                "SELECT 1 FROM custom_reports WHERE username=? AND name=? AND id<>?", (user["username"], name, rid)).fetchone():
            raise StoreError(409, "已有同名的報表，請換一個名稱。", {"reason": "duplicate_name"})
        if shares is not None:
            conn.execute("DELETE FROM custom_report_shares WHERE report_id=?", (rid,))
            now = _now()
            conn.executemany("INSERT INTO custom_report_shares (report_id, shared_with, created_at) VALUES (?,?,?)", [(rid, s, now) for s in shares])
        conn.execute("UPDATE custom_reports SET name=COALESCE(?, name), definition_json=COALESCE(?, definition_json), source_id=COALESCE(?, source_id), "
                     "updated_at=? WHERE id=?", (name, dumped, source_id, _now(), rid))
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    return get_visible(conn, user, rid)


def copy_report(conn, user, rid) -> dict:
    """把自己的或分享給我的報表複製成自己的一份（名稱加「（複本）」，過長截斷、重名加序號）。"""
    src = get_visible(conn, user, rid)
    if src.get("partiallyHidden"):
        _d, removed = redact_for_reader(_raw_definition(conn, rid), user)
        if "semantic" in removed:
            raise StoreError(422, "這份報表有部分條件您沒有權限查看，無法複製。請洽擁有者。", {"reason": "partially_hidden"})
    taken = {r[0] for r in conn.execute("SELECT name FROM custom_reports WHERE username=?", (user["username"],))}
    name = None
    for i in range(1, MAX_PER_USER + 3):
        suffix = "（複本）" if i == 1 else "（複本%d）" % i
        cand = src["name"][:NAME_MAX - len(suffix)] + suffix
        if cand not in taken:
            name = cand
            break
    if name is None:
        raise StoreError(409, "已有太多同名的複本，請先整理我的報表。", {"reason": "duplicate_name"})
    return create(conn, user, name, src["definition"])


def delete(conn, user, rid) -> dict:
    """擁有者刪除。回 `{"deleted": True, "recycled": bool}`；進暫存區時另帶 `after_commit`（呼叫端在 commit 後呼叫）。"""
    began = begin_write(conn)
    try:
        r = _row(conn, rid)
        if r is None or r["username"] != user["username"]:
            raise StoreError(404, NOT_FOUND)
        res = None
        if RP.recycle_deleted(conn):
            try:
                res = RB.delete(conn, "custom_report", rid, user)
            except RB.BinError as e:
                raise StoreError(409, "目前無法刪除這份報表：%s" % e)
        if res is None:                                       # 設定為直接刪除，或回收筒模組不在（照舊硬刪並明說）
            conn.execute("DELETE FROM custom_report_shares WHERE report_id=?", (rid,))
            conn.execute("DELETE FROM custom_reports WHERE id=?", (rid,))
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    out = {"deleted": True, "recycled": res is not None}
    if res is not None and res.get("after_commit"):
        out["after_commit"] = res["after_commit"]
    return out
