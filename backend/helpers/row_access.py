"""L1 資料列權限（row-level access）：一份宣告，同時產生「單筆判斷」與「SQL 過濾」。

為什麼要有這支（DEPENDENCY-MAP §0-5、§3 #2／#3／#5／#6）：
案件可見性原本有 6 份各自實作（SQL 一份、單筆一份、地圖逐筆一份、搜尋與動態牆各一份…），
而且已經漂移——搜尋與動態牆少了「被指派」與 cashier 兩條。兩種形式各寫各的，
就一定會再漂移；所以這裡**只有一份規則宣告**（`OwnerRule`），`visible()` 與
`filter_sql()` 都從它推導，再由等價測試拿同一批資料比對兩者的結果集合。

用法：
    register("case", OwnerRule(...))                   # 由擁有該表的模組登錄
    visible("case", user, row, scope="read")           # 單筆：True／False
    frag, params = filter_sql("case", user, prefix="q.", scope="read")
    sql += frag; args += params                        # frag 為 "" 或 " AND (...)"

scope：
    "owner"  擁有者規則（admin／本人／舊資料顯示名稱／成員清單／建立者）
    "read"   owner ＋ `read_bypass_modules`（例：cashier 讀得到全部案件，CM14b）

admin 直通收在介面內：呼叫端不必（也不該）再自己判斷 role。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from fastapi import HTTPException

from helpers.auth import user_has_module

ADMIN_ROLES = ("superadmin", "admin")
SCOPES = ("owner", "read")


@dataclass(frozen=True)
class OwnerRule:
    #: 單值擁有者 id 欄位（例：quotations.sales_person_id）
    owner_id_col: str | None = None
    #: owner_id 為 NULL 的舊資料改比對顯示名稱（例：quotations.sales_person）
    legacy_name_col: str | None = None
    #: JSON 陣列欄位，內含成員 user id（例：assigned_user_ids；sales_persons／planners）
    id_list_cols: tuple[str, ...] = ()
    #: 建立者 id 欄位（例：dev_cases.created_by）
    creator_col: str | None = None
    #: True：成員欄位不是合法 JSON ⇒ 視為空（dev_cases 現行行為）
    #: False：不是合法 JSON ⇒ 丟例外（quotations 現行行為：單筆 json.loads、SQL json_each 皆會丟）
    lenient_json: bool = False
    #: scope="read" 時直接放行的模組
    read_bypass_modules: tuple[str, ...] = field(default_factory=tuple)
    #: require() 擋下時的 403 訊息
    deny_message: str = "無權限存取這筆資料"


_REGISTRY: dict[str, OwnerRule] = {}
_log = logging.getLogger(__name__)


def register(kind: str, rule: OwnerRule) -> None:
    if kind in _REGISTRY and _REGISTRY[kind] != rule:
        raise ValueError(f"row_access：{kind!r} 已登錄為不同規則")
    _REGISTRY[kind] = rule


def rule_for(kind: str) -> OwnerRule | None:
    """未登錄 ⇒ None。🔴 呼叫端一律 fail closed：擁有該表的模組不在（被拆掉／沒載入）時，
    只能少看到東西，不可以多看到——所以連 admin 也不直通。"""
    rule = _REGISTRY.get(kind)
    if rule is None:
        _log.warning("row_access：%r 尚未登錄（擁有該表的模組沒有載入？）⇒ 一律不放行", kind)
    return rule


def _bypass(rule: OwnerRule, user: dict, scope: str) -> bool:
    if scope not in SCOPES:
        raise ValueError(f"row_access：scope 必須是 {SCOPES}，收到 {scope!r}")
    if (user or {}).get("role") in ADMIN_ROLES:
        return True
    return scope == "read" and any(user_has_module(user, m) for m in rule.read_bypass_modules)


def _get(row, col):
    """sqlite3.Row／dict 皆可；欄位不存在視同 NULL（沿用舊 `_check_quotation_owner` 的
    `if "x" in row.keys()` 寫法）。"""
    try:
        keys = row.keys()
    except AttributeError:
        return None
    return row[col] if col in keys else None


def _id_list(raw, lenient: bool) -> list:
    """成員欄位 ⇒ 陣列。NULL／空字串 ⇒ []；合法 JSON 但不是陣列 ⇒ []；壞 JSON 依 lenient。"""
    if raw is None or raw == "":
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        if lenient:
            return []
        raise
    return v if isinstance(v, list) else []


def visible(kind: str, user: dict, row, scope: str = "owner") -> bool:
    rule = rule_for(kind)
    if rule is None:
        return False
    if _bypass(rule, user, scope):
        return True
    uid = user["id"]
    if rule.owner_id_col:
        oid = _get(row, rule.owner_id_col)
        if oid is not None and oid == uid:
            return True
        if (rule.legacy_name_col and oid is None
                and _get(row, rule.legacy_name_col) is not None
                and _get(row, rule.legacy_name_col) == user["display_name"]):
            return True
    if rule.creator_col:
        cb = _get(row, rule.creator_col)
        if cb is not None and cb == uid:
            return True
    for col in rule.id_list_cols:
        if uid in _id_list(_get(row, col), rule.lenient_json):
            return True
    return False


def filter_sql(kind: str, user: dict, prefix: str = "", scope: str = "owner") -> tuple[str, list]:
    """回傳 (fragment, params)。直通者回 ("", [])；否則 fragment 以 " AND " 開頭。未登錄 ⇒ 恆假。"""
    rule = rule_for(kind)
    if rule is None:
        return (" AND 0", [])
    if _bypass(rule, user, scope):
        return ("", [])
    p = prefix
    terms, params = [], []
    if rule.owner_id_col:
        terms.append(f"{p}{rule.owner_id_col}=?")
        params.append(user["id"])
        if rule.legacy_name_col:
            terms.append(f"({p}{rule.owner_id_col} IS NULL AND {p}{rule.legacy_name_col}=?)")
            params.append(user["display_name"])
    if rule.creator_col:
        terms.append(f"{p}{rule.creator_col}=?")
        params.append(user["id"])
    for col in rule.id_list_cols:
        c = f"NULLIF({p}{col},'')"
        if rule.lenient_json:
            guard = f"json_valid({c}) AND json_type({c})='array'"
        else:
            guard = f"json_type({c})='array'"          # 壞 JSON ⇒ json_type 丟例外，與單筆 json.loads 一致
        terms.append(f"(CASE WHEN {guard} THEN EXISTS (SELECT 1 FROM json_each({c}) WHERE value=?) ELSE 0 END)")
        params.append(user["id"])
    if not terms:
        return (" AND 0", [])
    return (" AND (" + " OR ".join(terms) + ")", params)


def require(kind: str, user: dict, row, scope: str = "owner") -> None:
    """單筆存取守門：不可見 ⇒ 403（訊息取自登錄的 deny_message）。"""
    if not visible(kind, user, row, scope):
        rule = _REGISTRY.get(kind)
        raise HTTPException(403, rule.deny_message if rule else "無權限存取這筆資料")
