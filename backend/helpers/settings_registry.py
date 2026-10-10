# -*- coding: utf-8 -*-
"""設定中心登錄與讀取（L1；第 54 班 Train A／S0）。每個「可調整的數字／開關」在程式裡登錄一次，值存在 `setting_group` 定義（版本、還原、差異共用 L0）。

[單位] helper:settings_registry    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] SettingDef, SettingError, clamp_value, get, get_group, groups, invalidate, publish, register_group, validate_values
[不變式] ①`get()` **永不丟例外**：資料庫讀不到、值壞掉、型別不對、超出範圍 ⇒ 回程式預設並記 warning（`clamp` 欄位改為夾到範圍內）；
    ②**部署不寫任何定義列**：沒有列＝程式預設＝上線前的行為（`settings_deploy_baseline.json` 凍結）；③上下限**只寫在程式**（資料庫的值只是值）；
    ④寫入口只有 `publish()`：同一交易寫定義新版本＋變更明細（config_ledger）＋稽核＋（有舊鍵時）雙寫舊鍵；⑤讀取走 15 秒行程內快取，
    `publish()` 之後本行程立即失效（多行程以 TTL 為準）；⑥環境變數 `MOTRIX_SETTINGS_DEFAULTS_ONLY=1` ⇒ 一律回程式預設（出事時的逃生口）。
[契約題] backend/tests/platform/test_settings_registry_t54.py
"""
import json
import logging
import os
import threading
import time

from core import definitions as D
from db import get_db

logger = logging.getLogger("motrix.settings")

KIND = "setting_group"
SCOPE = "company"
_TTL = 15.0
_TYPES = ("int", "float", "bool", "str")

_GROUPS = {}                                   # group -> {"label", "fields": {name: SettingDef}, "sensitive", "risk", "legacy_key", "cross_check", "help"}
_cache = {}                                    # group -> (monotonic, values)
_lock = threading.Lock()


class SettingError(ValueError):
    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


class SettingDef:
    """一個設定欄位。`legacy`＝舊儲存位置（舊鍵 dict 裡的欄位名）；`clamp`＝讀取時夾到 [min, ...]（稽核保存期限那種「不可低於」）；
    `risk`＝none|ops|money|legal|security（高風險變更會通知其他最高管理者）。"""
    __slots__ = ("key", "type", "default", "min", "max", "unit", "label", "help", "risk", "legacy", "clamp")

    def __init__(self, key, type, default, *, min=None, max=None, unit="", label="", help="", risk="ops", legacy=None, clamp=False):
        if type not in _TYPES:
            raise ValueError("型別不合法：%r" % (type,))
        self.key, self.type, self.default = key, type, default
        self.min, self.max, self.unit, self.label, self.help = min, max, unit, label or key, help
        self.risk, self.legacy, self.clamp = risk, legacy, bool(clamp)
        if self.check(default):
            raise ValueError("預設值自己就不合法：%s=%r（%s）" % (key, default, self.check(default)))

    def check(self, v):
        """回問題描述字串；合法回 ''."""
        if self.type == "bool":
            return "" if isinstance(v, bool) else "必須是 true／false"
        if self.type == "str":
            return "" if isinstance(v, str) else "必須是文字"
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "必須是數字"
        if self.type == "int" and not (isinstance(v, int) or float(v).is_integer()):
            return "必須是整數"
        if self.min is not None and v < self.min:
            return "不可小於 %s" % self.min
        if self.max is not None and v > self.max:
            return "不可大於 %s" % self.max
        return ""

    def meta(self):
        return {"key": self.key, "type": self.type, "default": self.default, "min": self.min, "max": self.max, "unit": self.unit,
                "label": self.label, "help": self.help, "risk": self.risk, "clamp": self.clamp}


def register_group(group, label, fields, *, sensitive=False, risk="ops", legacy_key=None, cross_check=None, help=""):
    """登錄一個設定群組。`fields`＝SettingDef 清單；`cross_check(values)->[問題]`＝跨欄位檢查；`sensitive`＝只有設定權限者能讀。重複登錄 ⇒ ValueError。"""
    if group in _GROUPS:
        raise ValueError("設定群組已登錄：%r" % group)
    names = [f.key for f in fields]
    if len(set(names)) != len(names):
        raise ValueError("群組 %r 欄位重複" % group)
    _GROUPS[group] = {"label": label, "fields": {f.key: f for f in fields}, "sensitive": bool(sensitive), "risk": risk,
                      "legacy_key": legacy_key, "cross_check": cross_check, "help": help}


def groups():
    return {g: {"label": v["label"], "sensitive": v["sensitive"], "risk": v["risk"], "help": v["help"],
                "fields": [f.meta() for f in v["fields"].values()]} for g, v in _GROUPS.items()}


def _g(group):
    if group not in _GROUPS:
        raise KeyError("未登錄的設定群組：%r" % (group,))
    return _GROUPS[group]


def _defaults(group):
    return {k: f.default for k, f in _g(group)["fields"].items()}


def clamp_value(f, v):
    """讀取時的夾值（`clamp` 欄位）：只往範圍內夾，型別不對仍回預設。"""
    if f.check(v) and not (f.clamp and isinstance(v, (int, float)) and not isinstance(v, bool)):
        return f.default
    if f.min is not None and v < f.min:
        v = f.min
    if f.max is not None and v > f.max:
        v = f.max
    return int(v) if f.type == "int" else v


def validate_values(group, values, *, partial=False):
    """逐欄 + 跨欄位檢查（寫入時嚴格，不夾值）。回 `[{path, message}]`。"""
    g = _g(group)
    if not isinstance(values, dict):
        return [{"path": "", "message": "values 必須是物件"}]
    out = []
    for k, v in values.items():
        f = g["fields"].get(k)
        if f is None:
            out.append({"path": k, "message": "未知的設定欄位"})
            continue
        msg = f.check(v)
        if msg:
            out.append({"path": k, "message": "%s：%s" % (f.label, msg)})
    if not partial:
        for k in g["fields"]:
            if k not in values:
                out.append({"path": k, "message": "缺少欄位"})
    if not out and g["cross_check"]:
        try:
            out += list(g["cross_check"](dict(_defaults(group), **values)))
        except Exception as e:                      # noqa: BLE001
            out.append({"path": "", "message": "跨欄位檢查失敗：%s" % e})
    return out


# --- 讀 ---------------------------------------------------------------

def _legacy_values(conn, group):
    g = _g(group)
    if not g["legacy_key"]:
        return {}
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (g["legacy_key"],)).fetchone()
    if not row:
        return {}
    try:
        raw = json.loads(row[0])
    except (TypeError, ValueError):
        logger.warning("settings: 舊鍵 %s 不是合法 JSON，忽略", g["legacy_key"])
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: raw[f.legacy] for k, f in g["fields"].items() if f.legacy and f.legacy in raw}


def _stored(conn, group):
    """資料庫裡的值（定義最新發布版優先，否則舊鍵）；沒有 ⇒ {}。"""
    try:
        row = D.get(conn, KIND, group, SCOPE)
    except Exception:                               # noqa: BLE001 — 定義表還沒建（極舊庫／獨立執行的備份工作）⇒ 只看舊鍵
        row = None
    if row is not None:
        body = row.get("body") or {}
        vals = body.get("values") if isinstance(body, dict) else None
        if isinstance(vals, dict):
            return vals
        logger.warning("settings: 群組 %s 的定義內容格式不對，改用預設", group)
        return {}
    return _legacy_values(conn, group)


def _effective(conn, group):
    g = _g(group)
    out = _defaults(group)
    for k, v in _stored(conn, group).items():
        f = g["fields"].get(k)
        if f is None:
            continue
        numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
        if f.clamp and numeric and f.type in ("int", "float"):
            out[k] = clamp_value(f, v)
        elif f.check(v):
            logger.warning("settings: %s.%s 的值 %r 不合法（%s），改用預設 %r", group, k, v, f.check(v), f.default)
        else:
            out[k] = int(v) if f.type == "int" else v
    return out


def get_group(group, *, conn=None):
    """整組的有效值（程式預設 ＋ 已儲存的值）。永不丟例外。"""
    try:
        _g(group)
    except KeyError:
        raise
    if os.environ.get("MOTRIX_SETTINGS_DEFAULTS_ONLY") == "1":
        return _defaults(group)
    now = time.monotonic()
    ck = (group, _db_id())
    hit = _cache.get(ck)
    if conn is None and hit and now - hit[0] < _TTL:
        return dict(hit[1])
    own = conn is None
    try:
        c = conn if conn is not None else get_db()
        try:
            vals = _effective(c, group)
        finally:
            if own:
                c.close()
    except Exception:                               # noqa: BLE001 — 設定讀取不可拖垮呼叫端
        logger.warning("settings: 讀取群組 %s 失敗，改用快取或預設", group, exc_info=True)
        return dict(hit[1]) if hit else _defaults(group)
    if own:
        with _lock:
            _cache[ck] = (now, vals)
    return dict(vals)


def get(group, field, *, conn=None):
    vals = get_group(group, conn=conn)
    if field not in vals:
        raise KeyError("群組 %r 沒有欄位 %r" % (group, field))
    return vals[field]


def _db_id():
    import db
    return str(getattr(db, "DB_PATH", ""))


def invalidate(group=None):
    with _lock:
        if group is None:
            _cache.clear()
        else:
            for k in [k for k in _cache if k[0] == group]:
                del _cache[k]


# --- 寫 ---------------------------------------------------------------

def _write_legacy(conn, group, values):
    """雙寫舊鍵（一班過渡）：只動有 `legacy` 名的欄位，保留舊 dict 裡其他鍵。"""
    g = _g(group)
    if not g["legacy_key"]:
        return
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (g["legacy_key"],)).fetchone()
    try:
        cur = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    for k, f in g["fields"].items():
        if f.legacy and k in values:
            cur[f.legacy] = values[k]
    from datetime import datetime
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                 (g["legacy_key"], json.dumps(cur, ensure_ascii=False), datetime.now().isoformat()))


def _risk_of(group, changed):
    order = ("none", "ops", "money", "legal", "security")
    g = _g(group)
    top = g["risk"]
    for k in changed:
        r = g["fields"][k].risk
        if order.index(r) > order.index(top):
            top = r
    return top


def publish(group, values, *, note="", user="", reason="", ip="", conn=None, actor=None):
    """唯一寫入口。`values`＝要改的欄位（部分即可）；合併目前有效值後整組發布成新版本。
    同交易：定義新版本＋`config_changes`＋稽核（`settings.<group>.update`）＋舊鍵雙寫；沒有實質變更 ⇒ 不產生新版本（回 `{"changed": False}`）。
    驗證不過 ⇒ SettingError（帶 problems）；有送審中的版本 ⇒ `core.definitions.DefinitionConflict`。"""
    from core.txn import begin_write
    from helpers import config_ledger as L
    g = _g(group)
    problems = validate_values(group, values, partial=True)
    if problems:
        raise SettingError("設定未儲存（%d 個問題）" % len(problems), problems)
    own = conn is None
    c = conn if conn is not None else get_db()
    began = False
    try:
        began = begin_write(c)
        cur = _effective(c, group)
        new = dict(cur, **values)
        problems = validate_values(group, new)
        if problems:
            raise SettingError("設定未儲存（%d 個問題）" % len(problems), problems)
        changes = [{"field": k, "old": cur[k], "new": new[k]} for k in g["fields"] if cur[k] != new[k]]
        if not changes:
            if began:
                c.rollback()
            return {"changed": False, "values": cur}
        risk = _risk_of(group, [x["field"] for x in changes])
        out = D.publish_direct(c, KIND, group, SCOPE, {"group": group, "values": new}, note or reason, user, commit=False)
        L.record(c, "setting:%s" % group, group, changes, reason or note, actor if actor is not None else user, ip=ip, risk=risk,
                 ref_version=out["version"], audit_action="settings.%s.update" % group, target_label=g["label"])
        _write_legacy(c, group, new)
        c.commit()
        invalidate(group)
        return {"changed": True, "version": out["version"], "values": new, "changes": changes}
    except Exception:
        if began and c.in_transaction:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# --- 定義種類／版本 adapter ----------------------------------------------

def _kind_validator(body, key):
    if key not in _GROUPS:
        return [{"path": "", "message": "未登錄的設定群組：%s" % key}]
    vals = body.get("values") if isinstance(body, dict) else None
    if not isinstance(vals, dict):
        return [{"path": "values", "message": "缺少 values 物件"}]
    return validate_values(key, vals)


def _kind_default(key):
    return {"group": key, "values": _defaults(key)} if key in _GROUPS else None


def _snapshot(conn, key, version=None):
    row = D.get(conn, KIND, key, SCOPE, version)
    return None if row is None else {"version": row["version"], "values": (row.get("body") or {}).get("values", {})}


def _restore(conn, key, version, actor, reason):
    old = D.get(conn, KIND, key, SCOPE, int(version))
    if old is None or old["status"] != "published":
        raise D.DefinitionError("找不到第 %s 版（已發布）" % version)
    return publish(key, (old.get("body") or {}).get("values", {}), note="還原自第 %s 版" % version, user=str(actor or ""), reason=reason, conn=conn)


def _register_once():
    if KIND not in D.kinds():
        D.register_kind(KIND, label="設定群組", validator=_kind_validator, default=_kind_default)
    from helpers import config_ledger as L
    L.register_domain("setting", snapshot_fn=_snapshot, restore_fn=_restore, label="設定中心")


_register_once()
