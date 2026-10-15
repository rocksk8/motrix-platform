# -*- coding: utf-8 -*-
"""清單檢視偏好（T66 L2）：每人每清單的「每頁筆數」，以及公司政策＋欄位可見（F7）對版面引擎輸出的限制。設計：docs/platform/plans/T66-LIST-PREFS-DESIGN.md §1.3、§3、§5。

[單位] helper:list_view_prefs    [層] L1    [穩定度] 實驗（旗標 `list_prefs.enabled` 預設關；表 `user_list_view_prefs`）
[公開介面] MAX_BYTES, TABLE, ViewError, clamp_columns, clamp_sort, column_visible, constraints, enabled, etag_of, list_summaries, reset, save_page_size
[不變式] ①單一來源：個人的欄位顯示／順序與排序仍由版面引擎（`user_list_prefs`、`/api/list-prefs`）負責；本檔**只存每頁筆數**，不複製欄位或排序。
    ②本檔對版面引擎輸出只做『限制』：欄位必須通過欄位可見（F7）∩ 公司政策允許；金額欄只能隱藏／重排、**不可加回**（預設就不顯示的金額欄根本不列出）；排序欄位必須是看得到、允許排序的欄位。
    ③每次讀取都重算（不存授權）：政策收緊或權限變動立即生效；存的值只是偏好，超出現行範圍時讀取回到預設，不報錯。
    ④旗標關（或建構器治理沒開）⇒ `enabled()` 為 False，路由 404、不讀寫表。⑤寫入：存檔不合法 ⇒ ViewError(422)（不靜默夾值）；etag 不符 ⇒ ViewError(409)；公司不開放個人設定 ⇒ ViewError(403)。
    ⑥讀不到表／壞資料 ⇒ 當作沒有個人設定（回預設），不丟 500。⑦只讀寫呼叫者自己的列（鍵＝登入帳號，路徑沒有帳號參數）。
[契約題] backend/tests/platform/test_list_view_prefs_t66.py
"""
import hashlib
import json
import logging
from datetime import datetime

from helpers import field_catalog as _FC
from helpers import list_catalog as LC
from helpers import list_pref_policy as LP

logger = logging.getLogger("motrix.list_view_prefs")

TABLE = "user_list_view_prefs"
MAX_BYTES = 2048
_KEYS = {"pageSize"}


class ViewError(Exception):
    """`status`：403 公司不開放；404 沒有這份清單；409 etag 不符；422 內容不合法（`problems`＝白話原因清單）。"""

    def __init__(self, status, message, problems=None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


def enabled(conn=None) -> bool:
    return LP.enabled(conn)


def etag_of(prefs_json) -> str:
    return hashlib.sha256(str(prefs_json).encode("utf-8")).hexdigest()[:16] if prefs_json else ""


# ── 欄位可見（F7）：S0 用欄位目錄登記的天花板函式；F7 S1 之後換成 field_policy.visible，只改這一處 ──
def _ceiling_ok(ceiling, user) -> bool:
    try:
        from helpers import financial_mask as FM
        from helpers import auth
        fn = {"quote_money": FM.quote_money_visible, "finance_money": FM.money_visible,
              "material_money": FM.material_money_visible, "cashier": auth.has_cashier_access}.get(ceiling)
        return bool(fn(user)) if fn else False               # 不認得的天花板 ⇒ 不可見（fail closed）
    except Exception:                                        # noqa: BLE001
        logger.warning("天花板判斷失敗：%s", ceiling, exc_info=True)
        return False


def column_visible(col, user, _depth=0) -> bool:
    """沒有 `catalogId` ⇒ 一般欄位（可見）；有 ⇒ 欄位目錄的天花板與其 `derivedFrom`（成本藏起來，毛利也不可見）都要過。"""
    cat = (col or {}).get("catalogId")
    if cat is None:
        return True
    f = _FC.by_id(cat)
    if f is None or _depth > 5:
        return False
    if not _ceiling_ok(f["ceiling"], user):
        return False
    return all(column_visible({"catalogId": d}, user, _depth + 1) for d in f["derivedFrom"])


def _load(conn, username, list_id):
    try:
        r = conn.execute("SELECT prefs_json FROM user_list_view_prefs WHERE username=? AND list_id=?", (username, list_id)).fetchone()
        return r[0] if r else None
    except Exception:                                        # noqa: BLE001  表不存在／壞掉 ⇒ 當作沒有個人設定
        logger.warning("讀取清單檢視偏好失敗：%s", list_id, exc_info=True)
        return None


def _parse(raw) -> dict:
    try:
        d = json.loads(raw) if raw else {}
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def constraints(conn, user, list_id):
    """⇒ 這位使用者在這份清單上的限制與每頁筆數（見模組說明）；沒有這份清單 ⇒ None。永不丟例外（資料庫讀不到 ⇒ 回預設）。"""
    spec = LC.by_id(list_id)
    if spec is None:
        return None
    policy = LP.policy_for(conn, list_id, (user or {}).get("role")) or {}
    allow = bool(policy.get("allowUserPrefs", LP.DEFAULT_ALLOW_USER_PREFS))
    cc = policy.get("columns") or {}
    cols = [c for c in spec["columns"] if column_visible(c, user)]
    if "allowed" in cc:
        cols = [c for c in cols if c["id"] in set(cc["allowed"])]
    pinned, hidden, dflt = set(cc.get("pinned", [])), set(cc.get("defaultHidden", [])), set(spec["defaults"]["columns"])
    out_cols = []
    for c in cols:
        forced = c["id"] in pinned or c["required"]
        dv = forced or (c["id"] in dflt and c["id"] not in hidden)
        if c["money"] and not dv:
            continue                                         # 預設就不顯示的金額欄：根本不列出（不確認它存在，也不能加回）
        out_cols.append({"id": c["id"], "label": c["label"], "money": c["money"], "pinned": forced, "required": c["required"],
                         "defaultVisible": dv, "canShow": (not c["money"]) or dv})
    listed = {c["id"] for c in out_cols}
    default_visible = {c["id"] for c in out_cols if c["defaultVisible"]}
    sc = policy.get("sort") or {}
    sortable = [c["id"] for c in spec["columns"] if c["sortable"] and c["id"] in listed and ("allowed" not in sc or c["id"] in sc["allowed"])]
    sd = sc.get("default") or spec["defaults"].get("sort")
    sort_default = {"col": sd["col"], "dir": sd["dir"]} if sd and sd.get("col") in sortable and sd["col"] in default_visible else None
    # 每頁筆數
    ps_pol = policy.get("pageSize") or {}
    options = [x for x in spec["pageSizeMenu"] if x <= spec["pageSizeCeiling"] and ("allowed" not in ps_pol or x in ps_pol["allowed"])]
    d = ps_pol.get("default", spec["defaults"]["pageSize"])
    default_size = d if d in options else (spec["defaults"]["pageSize"] if spec["defaults"]["pageSize"] in options else options[0])
    source = "policy" if ps_pol else "default"
    raw = _load(conn, (user or {}).get("username", ""), list_id)
    value = default_size
    if allow:
        mine = _parse(raw).get("pageSize")
        if isinstance(mine, int) and not isinstance(mine, bool) and mine in options:
            value, source = mine, "user"
    else:
        options = [default_size]
    return {"listId": list_id, "label": spec["label"], "enabled": True, "allowUserPrefs": allow, "columns": out_cols,
            "sort": {"allowed": sortable, "default": sort_default},
            "pageSize": {"value": value, "source": source, "options": options},
            "custom": raw is not None, "etag": etag_of(raw)}


def list_summaries(conn, user) -> list:
    """登入者看得到的清單摘要（只有代號、名稱、是否有個人設定）。"""
    out = []
    for e in LC.lists():
        out.append({"id": e["id"], "label": e["label"], "hasCustom": _load(conn, (user or {}).get("username", ""), e["id"]) is not None})
    return out


def save_page_size(conn, user, list_id, body, if_match=None) -> dict:
    """存自己的每頁筆數。回新的限制與設定；不合法 ⇒ ViewError。"""
    view = constraints(conn, user, list_id)
    if view is None:
        raise ViewError(404, "沒有這份清單")
    if not view["allowUserPrefs"]:
        raise ViewError(403, "公司政策不開放這份清單的個人設定")
    if not isinstance(body, dict):
        raise ViewError(422, "內容必須是物件", ["內容必須是物件"])
    problems = ["不認得的設定：%s" % k for k in sorted(set(body) - _KEYS)]
    ps = body.get("pageSize")
    if "pageSize" not in body:
        problems.append("缺少 pageSize")
    elif not isinstance(ps, int) or isinstance(ps, bool) or ps not in view["pageSize"]["options"]:
        problems.append("每頁筆數必須是下列其中一個：%s" % "、".join(str(x) for x in view["pageSize"]["options"]))
    if problems:
        raise ViewError(422, "內容不合法", problems)
    new_json = json.dumps({"v": 1, "pageSize": ps}, ensure_ascii=False, sort_keys=True)
    if len(new_json.encode("utf-8")) > MAX_BYTES:
        raise ViewError(422, "內容太大", ["內容太大"])
    username = user["username"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = _load(conn, username, list_id)
        if etag_of(cur) != (if_match or ""):
            conn.rollback()
            raise ViewError(409, "設定在你開啟之後被改過（可能在另一個視窗），請重新載入")
        conn.execute("INSERT INTO user_list_view_prefs (username, list_id, prefs_json, updated_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(username, list_id) DO UPDATE SET prefs_json=excluded.prefs_json, updated_at=excluded.updated_at",
                     (username, list_id, new_json, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    except ViewError:
        raise
    except Exception:
        conn.rollback()
        raise
    return constraints(conn, user, list_id)


def reset(conn, user, list_id) -> dict:
    """回到公司預設（刪掉自己的那一列）。"""
    if LC.by_id(list_id) is None:
        raise ViewError(404, "沒有這份清單")
    conn.execute("DELETE FROM user_list_view_prefs WHERE username=? AND list_id=?", (user["username"], list_id))
    conn.commit()
    return constraints(conn, user, list_id)


# ── 對版面引擎輸出的限制（純函式；前端與之後的伺服器端呼叫端共用同一套規則） ──
def clamp_columns(view, columns) -> list:
    """`columns`＝版面引擎套完個人層的欄位 `[{field|id, visible, …}]`。回新的清單：不在 `view.columns` 的（無權限／政策不允許）移除；
    固定／必留欄位強制顯示；金額欄不可加回（`canShow` 為 False 的永遠不顯示）。順序不變。"""
    by = {c["id"]: c for c in view["columns"]}
    out = []
    for c in columns or []:
        cid = c.get("id", c.get("field"))
        spec = by.get(cid)
        if spec is None:
            continue
        n = dict(c)
        vis = bool(c.get("visible", True))
        n["visible"] = True if spec["pinned"] else (vis and spec["canShow"])
        out.append(n)
    return out


def clamp_sort(view, col, direction):
    """個人排序（來自版面引擎）必須是看得到、允許排序的欄位且方向合法，否則回政策預設（可能是 None）。"""
    if col in view["sort"]["allowed"] and direction in ("asc", "desc") and any(c["id"] == col for c in view["columns"]):
        return {"col": col, "dir": direction}
    return view["sort"]["default"]
