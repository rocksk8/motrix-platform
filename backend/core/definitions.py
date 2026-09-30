# -*- coding: utf-8 -*-
"""定義文件庫：草稿、版本、差異、還原（CUSTOMIZATION-SPEC §3.5）。

[單位] plat:definitions    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] DefinitionConflict, DefinitionError, KINDS, decide_submitted, delete_draft, diff, get, kinds, kinds_meta, list_definitions, open_submission, publish,
    register_default, register_kind, register_validator, resolve, restore, save_decision, save_draft, submit_draft, validate, versions
[不變式] 每個 (kind, key, scope) 最多一份草稿；已發布的版本不可改、不可刪；還原＝把舊版再發布成新的一版；發布前驗證不過就不發布
[契約題] tests/test_definitions_store_2026_09_25.py
[注意] 函式吃呼叫端的連線、不自己開；寫入的函式自己 commit

版面（P5）、輸出版型覆寫（P2）、自訂欄位（P4）、自訂模組（P8）共用這一套；用 `kind` 區分。
- 每個 (kind, key, scope) 最多一份草稿（version 0，可改）；發布產生不可變的新版本（version＋1）。
- 已發布的列不可修改、不可刪除；還原＝把舊版內容再發布成新的一版（歷史不改）。
- 發布前先跑該 kind 登記的驗證器，有任何問題就不發布，並回傳問題（含位置）。
- 所有函式都吃呼叫端的連線、不自行開連線；寫入的函式自己 commit。
"""
import json
import re
from datetime import datetime

#: 內建的四種（固定）；其餘由模組／helper 以 `register_kind()` 登記（資料驅動：新增一種定義不必再改這支 L0 檔）。
KINDS = ("layout", "output_template", "custom_fields", "custom_module")
_EXTRA_KINDS = {}    # kind -> {"label": str}（`register_kind` 登記的；內建四種不在這裡）
_BUILTIN_LABELS = {"layout": "頁面版面", "output_template": "輸出版型", "custom_fields": "自訂欄位", "custom_module": "自訂模組"}
_KEY_RE = re.compile(r"^[a-z][a-z0-9_:.\-]{0,79}$")
_SCOPE_RE = re.compile(r"^(company|role:[A-Za-z0-9_\-]{1,40})$")

_VALIDATORS = {}     # kind -> fn(body, key) -> [ {"path": str|None, "message": str} ]
_DEFAULTS = {}       # kind -> fn(key) -> body|None（程式出貨的預設）


class DefinitionError(ValueError):
    """參數不合法、狀態不對（例：沒有草稿卻要發布）、驗證不通過（`problems` 帶問題清單）。"""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


class DefinitionConflict(DefinitionError):
    """與目前狀態衝突（HTTP 409）：例如這份定義有送審中的版本時，直接發布／還原會讓那份送審變成過期的（W3 #3）。"""


def _open_blocks_direct(conn, kind, key, scope, what):
    sub_ = open_submission(conn, kind, key, scope)
    if sub_ is not None:
        raise DefinitionConflict("這份定義有送審中的第 %s 版，不能直接%s：請先審核（核可／退回）那一版，或請審核人退回後再處理"
                                 % (sub_["version"], what))


def register_validator(kind: str, fn) -> None:
    _VALIDATORS[kind] = fn


def register_kind(kind: str, label: str = "", validator=None, default=None) -> None:
    """登記一種新的定義種類（預留鉤子：A2 的 `expense_type` 是第一個使用者）。
    `kind`＝小寫英數與底線（與 key 同規則）；已登記的種類不可重複登記（兩個登記者在搶 ⇒ ValueError；內建四種也不可覆寫）；
    `validator(body, key) -> [problem]`、`default(key) -> body|None` 與 `register_validator`／`register_default` 同義。
    登記後 `save_draft／publish／…` 與 `GET /api/definition-kinds` 立即認得它；版本、差異、還原、送審機制全部共用。"""
    if not isinstance(kind, str) or not re.match(r"^[a-z][a-z0-9_]{0,39}$", kind):
        raise ValueError("定義種類名稱不合法：%r" % (kind,))
    if kind in KINDS or kind in _EXTRA_KINDS:
        raise ValueError("定義種類已登記：%r" % kind)
    _EXTRA_KINDS[kind] = {"label": label or kind}
    if validator is not None:
        register_validator(kind, validator)
    if default is not None:
        register_default(kind, default)


def kinds() -> tuple:
    """所有可用的定義種類（內建四種＋已登記的）。"""
    return KINDS + tuple(sorted(_EXTRA_KINDS))


def kinds_meta() -> list:
    """`[{kind, label, builtin}]`（編輯畫面的種類清單用）。"""
    return ([{"kind": k, "label": _BUILTIN_LABELS.get(k, k), "builtin": True} for k in KINDS] +
            [{"kind": k, "label": _EXTRA_KINDS[k]["label"], "builtin": False} for k in sorted(_EXTRA_KINDS)])


def register_default(kind: str, fn) -> None:
    _DEFAULTS[kind] = fn


def _check(kind, key, scope):
    if kind not in kinds():
        raise DefinitionError("未知的定義種類：%r（可用：%s）" % (kind, "、".join(kinds())))
    if not _KEY_RE.match(key or ""):
        raise DefinitionError("定義的 key 不合法：%r" % key)
    if not _SCOPE_RE.match(scope or ""):
        raise DefinitionError("scope 只能是 company 或 role:<角色>：%r" % scope)


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["body"] = json.loads(d.pop("body_json") or "{}")
    return d


def validate(kind: str, key: str, body) -> list:
    if not isinstance(body, dict):
        return [{"path": "", "message": "定義必須是 JSON 物件"}]
    fn = _VALIDATORS.get(kind)
    return list(fn(body, key)) if fn else []


def save_draft(conn, kind, key, scope, body, user="") -> dict:
    _check(kind, key, scope)
    if not isinstance(body, dict):
        raise DefinitionError("定義必須是 JSON 物件")
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at) "
        "VALUES (?,?,?,0,'draft',?,?,?) ON CONFLICT(kind, key, scope, version) DO UPDATE SET "
        "body_json=excluded.body_json, created_by=excluded.created_by, created_at=excluded.created_at",
        (kind, key, scope, json.dumps(body, ensure_ascii=False), user, now))
    conn.commit()
    return get(conn, kind, key, scope, 0)


def get(conn, kind, key, scope, version=None):
    """version=None ⇒ 最新發布版；0 ⇒ 草稿。沒有 ⇒ None。"""
    _check(kind, key, scope)
    if version is None:
        r = conn.execute("SELECT * FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND status='published' "
                         "ORDER BY version DESC LIMIT 1", (kind, key, scope)).fetchone()
    else:
        r = conn.execute("SELECT * FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND version=?",
                         (kind, key, scope, int(version))).fetchone()
    return _row(r)


def versions(conn, kind, key, scope) -> list:
    _check(kind, key, scope)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ui_definitions)").fetchall()}
    extra = ", submitted_by, submitted_at, decision_json" if "decision_json" in cols else ""      # core v3 之前的庫（測試只跑 v1）沒有送審欄
    rows = conn.execute("SELECT id, kind, key, scope, version, status, note, created_by, created_at, published_by, "
                        "published_at" + extra + " FROM ui_definitions WHERE kind=? AND key=? AND scope=? "
                        "ORDER BY version DESC", (kind, key, scope)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["decision"] = json.loads(d.pop("decision_json", None) or "{}") or {}
        except (TypeError, ValueError):
            d["decision"] = {}
        out.append(d)
    return out


def list_definitions(conn, kind) -> list:
    """同一 kind 的所有定義（含只有草稿、還沒發布過的）：`[{key, scope, latestVersion, hasDraft, updatedAt}]`。"""
    if kind not in kinds():
        raise DefinitionError("未知的定義種類：%r（可用：%s）" % (kind, "、".join(kinds())))
    rows = conn.execute(
        "SELECT key, scope, MAX(CASE WHEN status='published' THEN version END) AS latest, "
        "MAX(CASE WHEN status='draft' THEN 1 ELSE 0 END) AS has_draft, "
        "MAX(CASE WHEN status='published' THEN published_at ELSE created_at END) AS updated "
        "FROM ui_definitions WHERE kind=? GROUP BY key, scope ORDER BY key, scope", (kind,)).fetchall()
    return [{"key": r["key"], "scope": r["scope"], "latestVersion": r["latest"], "hasDraft": bool(r["has_draft"]),
             "updatedAt": r["updated"] or ""} for r in rows]


def delete_draft(conn, kind, key, scope) -> bool:
    """刪掉草稿（只有草稿可以刪；已發布的版本不可刪）。回有沒有刪到。"""
    _check(kind, key, scope)
    n = conn.execute("DELETE FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND version=0 AND status='draft'",
                     (kind, key, scope)).rowcount
    conn.commit()
    return n > 0


def _next_version(conn, kind, key, scope) -> int:
    r = conn.execute("SELECT MAX(version) FROM ui_definitions WHERE kind=? AND key=? AND scope=?",
                     (kind, key, scope)).fetchone()
    return (r[0] or 0) + 1


# ── 送審流程（建構器第三輪 S4，2026-09-30）：草稿 → 送審（不可變快照，取新版號）→ 核可＝發布／退回＝保留並帶原因 ──
# 版號單調遞增、被退回的版號不回收；已發布版本不可變。`resolve()`／`get(version=None)` 只認 published ⇒ 舊行為不變。

def open_submission(conn, kind, key, scope):
    """目前送審中（status='submitted'）的那一列；沒有 ⇒ None。"""
    _check(kind, key, scope)
    return _row(conn.execute("SELECT * FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND status='submitted' "
                             "ORDER BY version DESC LIMIT 1", (kind, key, scope)).fetchone())


def submit_draft(conn, kind, key, scope, note="", user="", decision=None) -> dict:
    """把草稿凍結成不可變快照（status='submitted'，取 max(version)+1）；草稿保留（送審期間還能繼續改下一版）。
    驗證不過、沒有草稿、已有送審中的 ⇒ DefinitionError。`decision`＝簽核鏈等（寫進 decision_json）。"""
    from core.txn import begin_write
    _check(kind, key, scope)
    began = begin_write(conn)
    try:
        draft = get(conn, kind, key, scope, 0)
        if draft is None:
            raise DefinitionError("沒有草稿可以送審")
        if open_submission(conn, kind, key, scope) is not None:
            raise DefinitionError("已有送審中的版本，請等審核結果（或請審核人退回）再送")
        problems = validate(kind, key, draft["body"])
        if problems:
            raise DefinitionError("驗證不通過，未送審（%d 個問題）" % len(problems), problems)
        now = datetime.now().isoformat(timespec="seconds")
        v = _next_version(conn, kind, key, scope)
        conn.execute(
            "INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, note, created_by, created_at, "
            "submitted_by, submitted_at, decision_json) VALUES (?,?,?,?,'submitted',?,?,?,?,?,?,?)",
            (kind, key, scope, v, json.dumps(draft["body"], ensure_ascii=False), note or "", user, now, user, now,
             json.dumps(decision or {}, ensure_ascii=False)))
        conn.commit()
        return get(conn, kind, key, scope, v)
    except Exception:
        if began:
            conn.rollback()
        raise


def save_decision(conn, kind, key, scope, version, decision) -> None:
    """送審中的列：更新 decision_json（簽核進度）。只准改 submitted 的列。"""
    _check(kind, key, scope)
    n = conn.execute("UPDATE ui_definitions SET decision_json=? WHERE kind=? AND key=? AND scope=? AND version=? AND status='submitted'",
                     (json.dumps(decision, ensure_ascii=False), kind, key, scope, int(version))).rowcount
    if n == 0:
        raise DefinitionError("第 %s 版不是送審中" % version)
    conn.commit()


def decide_submitted(conn, kind, key, scope, version, approve, user="", note="", decision=None) -> dict:
    """送審中的列：核可 ⇒ published（成為現行版本；草稿內容與它相同才刪草稿，否則保留，送審期間的新修改不會被吃掉）；
    退回 ⇒ rejected（保留列與原因，不可變；版號不回收）。`decision`＝要併進 decision_json 的鍵。"""
    from core.txn import begin_write
    _check(kind, key, scope)
    began = begin_write(conn)
    try:
        row = get(conn, kind, key, scope, int(version))
        if row is None or row["status"] != "submitted":
            raise DefinitionError("第 %s 版不是送審中" % version)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            dec = json.loads(row.get("decision_json") or "{}") or {}
        except (TypeError, ValueError):
            dec = {}
        dec.update(decision or {})
        dec.update({"decidedBy": user, "decidedAt": now, "result": "approved" if approve else "rejected", "note": note or ""})
        if approve:
            problems = validate(kind, key, row["body"])
            if problems:
                raise DefinitionError("驗證不通過，未發布（%d 個問題）" % len(problems), problems)
            conn.execute("UPDATE ui_definitions SET status='published', published_by=?, published_at=?, decision_json=? WHERE id=?",
                         (user, now, json.dumps(dec, ensure_ascii=False), row["id"]))
            draft = get(conn, kind, key, scope, 0)
            if draft is not None and draft["body"] == row["body"]:
                conn.execute("DELETE FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND version=0 AND status='draft'", (kind, key, scope))
        else:
            conn.execute("UPDATE ui_definitions SET status='rejected', decision_json=? WHERE id=?",
                         (json.dumps(dec, ensure_ascii=False), row["id"]))
        conn.commit()
        return get(conn, kind, key, scope, int(version))
    except Exception:
        if began:
            conn.rollback()
        raise


def _insert_published(conn, kind, key, scope, body, note, user) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    v = _next_version(conn, kind, key, scope)
    conn.execute(
        "INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, note, created_by, created_at, "
        "published_by, published_at) VALUES (?,?,?,?,'published',?,?,?,?,?,?)",
        (kind, key, scope, v, json.dumps(body, ensure_ascii=False), note or "", user, now, user, now))
    return get(conn, kind, key, scope, v)


def publish(conn, kind, key, scope, note="", user="") -> dict:
    """稽核 D C-S5：讀草稿之前先拿寫鎖 ⇒ 兩人同時發布不會 UNIQUE 衝突、發布時的自動存檔不會被刪掉。"""
    from core.txn import begin_write
    _check(kind, key, scope)
    began = begin_write(conn)
    try:
        return _publish_locked(conn, kind, key, scope, note, user)
    except Exception:
        if began:
            conn.rollback()
        raise


def _publish_locked(conn, kind, key, scope, note, user) -> dict:
    _open_blocks_direct(conn, kind, key, scope, "發布")
    draft = get(conn, kind, key, scope, 0)
    if draft is None:
        raise DefinitionError("沒有草稿可以發布")
    problems = validate(kind, key, draft["body"])
    if problems:
        raise DefinitionError("驗證不通過，未發布（%d 個問題）" % len(problems), problems)
    out = _insert_published(conn, kind, key, scope, draft["body"], note, user)
    conn.execute("DELETE FROM ui_definitions WHERE kind=? AND key=? AND scope=? AND version=0 AND status='draft'",
                 (kind, key, scope))
    conn.commit()
    return out


def restore(conn, kind, key, scope, version, note="", user="") -> dict:
    """把第 `version` 版再發布成新的一版（歷史不改）。也要過驗證器（舊版可能引用已不存在的東西）。"""
    from core.txn import begin_write
    _check(kind, key, scope)
    began = begin_write(conn)
    try:
        return _restore_locked(conn, kind, key, scope, version, note, user)
    except Exception:
        if began:
            conn.rollback()
        raise


def _restore_locked(conn, kind, key, scope, version, note, user) -> dict:
    _open_blocks_direct(conn, kind, key, scope, "還原")
    old = get(conn, kind, key, scope, int(version))
    if old is None or old["status"] != "published":
        raise DefinitionError("找不到第 %s 版（已發布）" % version)
    problems = validate(kind, key, old["body"])
    if problems:
        raise DefinitionError("第 %s 版在目前的環境驗證不通過，無法還原" % version, problems)
    out = _insert_published(conn, kind, key, scope, old["body"], note or ("還原自第 %s 版" % version), user)
    conn.commit()
    # 稽核 D C-O1：還原不動草稿 ⇒ 下一次「發布」會把那份舊草稿蓋在還原的結果上；回應明說，由畫面提示
    out["draftPending"] = get(conn, kind, key, scope, 0) is not None
    return out


def resolve(conn, kind, key, role=None) -> tuple:
    """套用順序：role:<角色> 最新發布 ＞ company 最新發布 ＞ 程式預設。回 `(body, 來源描述)`；都沒有 ⇒ (None, "none")。"""
    if role:
        r = get(conn, kind, key, "role:%s" % role)
        if r:
            return r["body"], "role:%s v%d" % (role, r["version"])
    r = get(conn, kind, key, "company")
    if r:
        return r["body"], "company v%d" % r["version"]
    fn = _DEFAULTS.get(kind)
    body = fn(key) if fn else None
    return (body, "default") if body is not None else (None, "none")


# ── JSON 差異 ────────────────────────────────────────────────────────────

def diff(a, b, path="") -> list:
    """`[{"op": "add"|"remove"|"change", "path": "blocks[5].title", "old": …, "new": …}]`（依路徑順序）。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = "%s.%s" % (path, k) if path else str(k)
            if k not in a:
                out.append({"op": "add", "path": p, "new": b[k]})
            elif k not in b:
                out.append({"op": "remove", "path": p, "old": a[k]})
            else:
                out.extend(diff(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            p = "%s[%d]" % (path, i)
            if i >= len(a):
                out.append({"op": "add", "path": p, "new": b[i]})
            elif i >= len(b):
                out.append({"op": "remove", "path": p, "old": a[i]})
            else:
                out.extend(diff(a[i], b[i], p))
    elif a != b:
        out.append({"op": "change", "path": path, "old": a, "new": b})
    return out
