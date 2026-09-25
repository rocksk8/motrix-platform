# -*- coding: utf-8 -*-
"""定義文件庫：草稿、版本、差異、還原（CUSTOMIZATION-SPEC §3.5）。

[單位] plat:definitions    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] DefinitionError, KINDS, delete_draft, diff, get, list_definitions, publish, register_default,
    register_validator, resolve, restore, save_draft, validate, versions
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

KINDS = ("layout", "output_template", "custom_fields", "custom_module")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_:.\-]{0,79}$")
_SCOPE_RE = re.compile(r"^(company|role:[A-Za-z0-9_\-]{1,40})$")

_VALIDATORS = {}     # kind -> fn(body, key) -> [ {"path": str|None, "message": str} ]
_DEFAULTS = {}       # kind -> fn(key) -> body|None（程式出貨的預設）


class DefinitionError(ValueError):
    """參數不合法、狀態不對（例：沒有草稿卻要發布）、驗證不通過（`problems` 帶問題清單）。"""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


def register_validator(kind: str, fn) -> None:
    _VALIDATORS[kind] = fn


def register_default(kind: str, fn) -> None:
    _DEFAULTS[kind] = fn


def _check(kind, key, scope):
    if kind not in KINDS:
        raise DefinitionError("未知的定義種類：%r（可用：%s）" % (kind, "、".join(KINDS)))
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
    rows = conn.execute("SELECT id, kind, key, scope, version, status, note, created_by, created_at, published_by, "
                        "published_at FROM ui_definitions WHERE kind=? AND key=? AND scope=? ORDER BY version DESC",
                        (kind, key, scope)).fetchall()
    return [dict(r) for r in rows]


def list_definitions(conn, kind) -> list:
    """同一 kind 的所有定義（含只有草稿、還沒發布過的）：`[{key, scope, latestVersion, hasDraft, updatedAt}]`。"""
    if kind not in KINDS:
        raise DefinitionError("未知的定義種類：%r（可用：%s）" % (kind, "、".join(KINDS)))
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


def _insert_published(conn, kind, key, scope, body, note, user) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    v = _next_version(conn, kind, key, scope)
    conn.execute(
        "INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, note, created_by, created_at, "
        "published_by, published_at) VALUES (?,?,?,?,'published',?,?,?,?,?,?)",
        (kind, key, scope, v, json.dumps(body, ensure_ascii=False), note or "", user, now, user, now))
    return get(conn, kind, key, scope, v)


def publish(conn, kind, key, scope, note="", user="") -> dict:
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
    old = get(conn, kind, key, scope, int(version))
    if old is None or old["status"] != "published":
        raise DefinitionError("找不到第 %s 版（已發布）" % version)
    problems = validate(kind, key, old["body"])
    if problems:
        raise DefinitionError("第 %s 版在目前的環境驗證不通過，無法還原" % version, problems)
    out = _insert_published(conn, kind, key, scope, old["body"], note or ("還原自第 %s 版" % version), user)
    conn.commit()
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
