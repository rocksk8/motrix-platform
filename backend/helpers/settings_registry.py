# -*- coding: utf-8 -*-
"""設定中心登錄與讀取（L1；第 54 班 Train A／S0）。每個「可調整的數字／開關」在程式裡登錄一次，值存在 `setting_group` 定義（版本、還原、差異共用 L0）。

[單位] helper:settings_registry    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] DEFAULT_CONFIRM_DAYS, DEFAULT_EFFECT, IMPACT_SCOPE_GRANDFATHERED, KIND, RISK_ORDER, SCOPE, SettingDef, SettingError, apply_profile, banner_of, clamp_value, clear_edition_bounds, confirm_period_days,
    field_defs, field_views, get, get_group, groups, invalidate, live_impact, materialize_due, plan, profile_preview, profiles, publish, register_group, set_edition_bounds, show_value, validate_values
[不變式] ①`get()` **永不丟例外**：資料庫讀不到、值壞掉、型別不對、超出範圍 ⇒ 回程式預設並記 warning（`clamp` 欄位改為夾到範圍內）；
    ②**部署不寫任何定義列**：沒有列＝程式預設＝上線前的行為（`settings_deploy_baseline.json` 凍結）；③上下限**只寫在程式**（資料庫的值只是值）；
    ④寫入口只有 `publish()`：同一交易寫定義新版本＋變更明細（config_ledger）＋稽核＋（有舊鍵時）雙寫舊鍵；⑤讀取走 15 秒行程內快取，
    `publish()` 之後本行程立即失效（多行程以 TTL 為準）；⑥風險欄位（`requires_pending`）的變更不立即生效：寫待生效明細（預設 7 天＝`change_control.confirm_period_days`，下限 1 天，可撤銷），
    讀取時到期即生效（`in_effect`），`materialize_due()` 再把到期值寫進定義版本；⑦環境變數 `MOTRIX_SETTINGS_DEFAULTS_ONLY=1` ⇒ 一律回程式預設（出事時的逃生口）。
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
DEFAULT_CONFIRM_DAYS = 7                       # 變更確認期間預設天數（設定 `change_control.confirm_period_days` 沒有值時用；下限 1 天）
CONFIRM_GROUP, CONFIRM_FIELD = "change_control", "confirm_period_days"
_TYPES = ("int", "float", "bool", "str")
DEFAULT_EFFECT = "你即將把「{名稱}」從 {舊} 改成 {新}，{生效時間}生效"
RISK_ORDER = ("none", "ops", "money", "legal", "security")
#: 結構化影響範圍（脊柱 E-e；欄位版面框架 §16.6／§17）：documents／roles＝白話清單；amounts＝一句話；reversible＝可否復原；effective＝immediate｜pending（須與欄位旗標一致）。
_IMPACT_SCOPE_KEYS = ("documents", "roles", "amounts", "reversible", "effective")
#: E-e 之前就已登錄的群組：風險 ≥ money 的欄位暫免 `impact_scope`（下次被修改時補上，不追溯變紅）。**新群組不得加入此名單**；
#: 守門見 `tests/platform/test_settings_editor_s1.py::test_new_groups_with_high_risk_fields_declare_impact_scope`。
IMPACT_SCOPE_GRANDFATHERED = frozenset({"change_control", "retention", "uploads", "system_hub", "completion_note", "quote_alt", "material_order"})


def _zh(v):
    """有實質的繁中文字（至少 2 個中日韓字元）。"""
    return isinstance(v, str) and sum(1 for ch in v if "一" <= ch <= "鿿") >= 2

_EDITION = {}                                  # (group, field) -> (min, max)：版本／授權邊界，只由程式或授權載入器設定，客戶不可改


def set_edition_bounds(group, field, *, min=None, max=None):
    """設定販售版本的欄位邊界（與欄位自己的上下限取交集）。給授權／版本載入器呼叫；沒有任何 API 讓客戶改它。"""
    _EDITION[(group, field)] = (min, max)


def clear_edition_bounds():
    _EDITION.clear()


def _bounds(group, f):
    lo, hi = f.min, f.max
    elo, ehi = _EDITION.get((group, f.key), (None, None))
    if elo is not None:
        lo = elo if lo is None else max(lo, elo)
    if ehi is not None:
        hi = ehi if hi is None else min(hi, ehi)
    return lo, hi


_GROUPS = {}                                   # group -> {"label", "fields": {name: SettingDef}, "sensitive", "risk", "legacy_key", "cross_check", "help"}
_cache = {}                                    # group -> (monotonic, values)
_lock = threading.Lock()


class SettingError(ValueError):
    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


def _check_impact_scope(key, s, *, pending):
    """`impact_scope` 的結構驗證（None 合法＝尚未宣告）。`effective` 必須與欄位旗標一致（有 `requires_pending`／`loosen` ⇒ pending）。"""
    if s is None:
        return None
    if not isinstance(s, dict) or set(s) != set(_IMPACT_SCOPE_KEYS):
        raise ValueError("設定欄位 %r 的 impact_scope 必須剛好有這些鍵：%s" % (key, "、".join(_IMPACT_SCOPE_KEYS)))
    for k in ("documents", "roles"):
        v = s[k]
        if not isinstance(v, (list, tuple)) or any(not _zh(x) for x in v):
            raise ValueError("設定欄位 %r 的 impact_scope.%s 必須是繁中白話名稱的清單" % (key, k))
    if not _zh(s["amounts"]):
        raise ValueError("設定欄位 %r 的 impact_scope.amounts 需要一句繁中白話" % key)
    if not isinstance(s["reversible"], bool):
        raise ValueError("設定欄位 %r 的 impact_scope.reversible 必須是 true／false" % key)
    if s["effective"] not in ("immediate", "pending"):
        raise ValueError("設定欄位 %r 的 impact_scope.effective 只能是 immediate／pending" % key)
    if (s["effective"] == "pending") != bool(pending):
        raise ValueError("設定欄位 %r 的 impact_scope.effective 與欄位的 requires_pending／loosen 旗標不一致" % key)
    return {"documents": list(s["documents"]), "roles": list(s["roles"]), "amounts": s["amounts"],
            "reversible": s["reversible"], "effective": s["effective"]}


class SettingDef:
    """一個設定欄位。畫面規則（使用者 2026-10-10，CORE-SPEC 零技術門檻）：問白話問題、少量選項、標示建議、說明影響；內部鍵 `key` 不顯示。
    **必填**：`question`（白話問句）、`label`、`help`、`impact`（影響說明：對象／既有或之後／可否復原／何時生效）；`risk` 屬 money／legal／security 或
    `requires_pending` ⇒ 另需 `risk_text`（白話風險提示）；`choices=[(值, 中文標籤, 影響說明)]`（選項型；三項皆必填）。缺必填 ⇒ ValueError（登錄當下就失敗）。
    選填：`recommended`（建議值）、`presets={預設組名: 值}`、`advanced`（收進「進階」）、`impact_fn(conn, 新值)->{"numbers":…, "sentence":…}`（唯讀即時影響，失敗只顯示靜態說明）、
    `effect`（儲存前確認句型，預設見 `DEFAULT_EFFECT`）。`legacy`＝舊儲存位置；`clamp`＝讀取時夾到 [min, ...]；`requires_pending`＝變更經過「確認期間」（`confirm_period_days`，預設 7 天）後才生效。
    `loosen`＝放寬方向：往該方向調整的變更視同風險變更——確認期間後才生效，且需要另一位最高管理者核准（只有一位時改為原因＋確認期間＋警告＋通知）；
    收緊（反方向）立即生效。販售版本的邊界（`set_edition_bounds`）寫在程式／授權，客戶不能改。"""
    __slots__ = ("key", "type", "default", "min", "max", "unit", "label", "help", "risk", "legacy", "clamp", "requires_pending",
                 "question", "impact", "risk_text", "choices", "recommended", "presets", "advanced", "impact_fn", "effect", "loosen", "zero_is_max", "impact_scope")

    def __init__(self, key, type, default, *, question="", label="", help="", impact="", min=None, max=None, unit="", risk="ops",
                 legacy=None, clamp=False, requires_pending=False, risk_text="", choices=None, recommended=None, presets=None,
                 advanced=False, impact_fn=None, effect="", loosen=None, zero_is_max=False, impact_scope=None):
        if type not in _TYPES:
            raise ValueError("型別不合法：%r" % (type,))
        self.key, self.type, self.default = key, type, default
        self.min, self.max, self.unit = min, max, unit
        self.label, self.help, self.question, self.impact = label, help, question, impact
        self.risk, self.legacy, self.clamp = risk, legacy, bool(clamp)
        self.requires_pending = bool(requires_pending)
        self.risk_text, self.recommended, self.advanced = risk_text, recommended, bool(advanced)
        self.choices = [tuple(c) for c in (choices or [])]
        self.presets = dict(presets or {})
        self.impact_fn, self.effect = impact_fn, effect or DEFAULT_EFFECT
        if loosen not in (None, "up", "down"):
            raise ValueError("loosen 只能是 up／down／None：%r" % (loosen,))
        if loosen and type not in ("int", "float"):
            # 放寬判定只認數字（publish()._loosens）：bool／str 設了 loosen 不會觸發待生效，等於沒管制。選項欄位請用整數代碼（0/1、1..n）。
            raise ValueError("設定欄位 %r：loosen 只能用在數字欄位（int／float）；選項請用整數代碼" % (key,))
        self.zero_is_max = bool(zero_is_max)   # 0 代表「不限／永久」（比任何正數都寬鬆）：判斷放寬方向時 0 視為無限大
        self.loosen = loosen          # 數值往哪個方向變是「放寬」（up＝調大算放寬，如允許更大的檔案；down＝調小算放寬，如更短的密碼長度）；放寬要雙人核准
        miss = [n for n, v in (("question", question), ("label", label), ("help", help), ("impact", impact)) if not _zh(v)]
        if (risk in ("money", "legal", "security") or self.requires_pending) and not _zh(risk_text):
            miss.append("risk_text")
        for c in self.choices:
            if len(c) != 3 or not _zh(c[1]) or not _zh(c[2]):
                miss.append("choices（每個選項要有 值／中文標籤／影響說明）")
                break
        if miss:
            raise ValueError("設定欄位 %r 缺少必填的繁中文字：%s" % (key, "、".join(miss)))
        self.impact_scope = _check_impact_scope(key, impact_scope, pending=bool(self.requires_pending or self.loosen))
        if self.check(default):
            raise ValueError("預設值自己就不合法：%s=%r（%s）" % (key, default, self.check(default)))
        if recommended is not None and self.check(recommended):
            raise ValueError("建議值不合法：%s=%r（%s）" % (key, recommended, self.check(recommended)))

    def check(self, v):
        """回問題描述字串；合法回 ''."""
        if self.type == "bool":
            if not isinstance(v, bool):
                return "必須是 true／false"
            return "不是可選的選項" if (self.choices and v not in [c[0] for c in self.choices]) else ""
        if self.type == "str":
            if not isinstance(v, str):
                return "必須是文字"
            return "不是可選的選項" if (self.choices and v not in [c[0] for c in self.choices]) else ""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "必須是數字"
        if self.type == "int" and not (isinstance(v, int) or float(v).is_integer()):
            return "必須是整數"
        if self.min is not None and v < self.min:
            return "不可小於 %s" % self.min
        if self.max is not None and v > self.max:
            return "不可大於 %s" % self.max
        if self.choices and v not in [c[0] for c in self.choices]:
            return "不是可選的選項"                                   # E-f：有 choices 就必須是其中之一（寫入被拒；讀取視為不合法而回預設）
        return ""

    def meta(self):
        return {"key": self.key, "type": self.type, "default": self.default, "min": self.min, "max": self.max, "unit": self.unit,
                "question": self.question, "label": self.label, "help": self.help, "impact": self.impact, "riskText": self.risk_text,
                "risk": self.risk, "clamp": self.clamp, "requiresPending": self.requires_pending, "recommended": self.recommended,
                "presets": self.presets, "advanced": self.advanced, "effect": self.effect, "hasLiveImpact": self.impact_fn is not None, "loosen": self.loosen, "impactScope": self.impact_scope,
                "choices": [{"value": c[0], "label": c[1], "impact": c[2]} for c in self.choices]}


def register_group(group, label, fields, *, sensitive=False, risk="ops", legacy_key=None, cross_check=None, help=""):
    """登錄一個設定群組。`fields`＝SettingDef 清單；`cross_check(values)->[問題]`＝跨欄位檢查；`sensitive`＝只有設定權限者能讀。重複登錄 ⇒ ValueError。"""
    if group in _GROUPS:
        raise ValueError("設定群組已登錄：%r" % group)
    if not _zh(label) or not _zh(help):
        raise ValueError("設定群組 %r 需要繁中的名稱與說明" % group)
    names = [f.key for f in fields]
    if len(set(names)) != len(names):
        raise ValueError("群組 %r 欄位重複" % group)
    _GROUPS[group] = {"label": label, "fields": {f.key: f for f in fields}, "sensitive": bool(sensitive), "risk": risk,
                      "legacy_key": legacy_key, "cross_check": cross_check, "help": help}


def groups():
    return {g: {"label": v["label"], "sensitive": v["sensitive"], "risk": v["risk"], "help": v["help"],
                "fields": [dict(f.meta(), min=_bounds(g, f)[0], max=_bounds(g, f)[1]) for f in v["fields"].values()]} for g, v in _GROUPS.items()}


def _g(group):
    if group not in _GROUPS:
        raise KeyError("未登錄的設定群組：%r" % (group,))
    return _GROUPS[group]


def _merged(base, over):
    """新字典＝base 加上 over 的鍵（over 蓋 base）；不用 `**` 展開（守門：禁止非字面值的 ** 傳參）。"""
    out = dict(base)
    out.update(over)
    return out


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
        if not msg and f.type in ("int", "float"):
            lo, hi = _bounds(group, f)
            if lo is not None and v < lo:
                msg = "這個版本不可小於 %s" % lo
            elif hi is not None and v > hi:
                msg = "這個版本不可大於 %s" % hi
        if msg:
            out.append({"path": k, "message": "%s：%s" % (f.label, msg)})
    if not partial:
        for k in g["fields"]:
            if k not in values:
                out.append({"path": k, "message": "缺少欄位"})
    if not out and g["cross_check"]:
        try:
            out += list(g["cross_check"](_merged(_defaults(group), values)))
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


def _due_pending(conn, group, now):
    """已到時、尚未被寫進定義的待生效值（依申請先後；同欄位後者蓋前者）。只有群組含 `requires_pending` 欄位才查。"""
    g = _g(group)
    if not any(f.requires_pending or f.loosen for f in g["fields"].values()):
        return []
    from helpers import config_ledger as L
    try:
        rows = L.pending(conn, "setting:%s" % group)
    except Exception:                               # noqa: BLE001 — 沒有明細表（極舊庫）⇒ 沒有待生效
        return []
    due = [r for r in rows if r["domain"] == "setting:%s" % group and r["field"] in g["fields"] and L.in_effect(r, now)]
    due.sort(key=lambda r: r["id"])
    return due


def _effective(conn, group, now=None, overlay=True):
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
    if overlay:
        from datetime import datetime
        for r in _due_pending(conn, group, now or datetime.now().isoformat(timespec="seconds")):
            if not validate_values(group, {r["field"]: r["new"]}, partial=True):      # 含版本邊界：邊界收緊後，舊的待生效值不會生效
                out[r["field"]] = r["new"]
    return out


def get_group(group, *, conn=None, now=None):
    """整組的有效值（程式預設 ＋ 已儲存的值 ＋ 已到時的待生效值）。永不丟例外。`now`（ISO 字串）只給測試／預覽「某時間點」用，不走快取。"""
    _g(group)                                       # 未登錄 ⇒ KeyError（程式錯誤，不吞）
    if os.environ.get("MOTRIX_SETTINGS_DEFAULTS_ONLY") == "1":
        return _defaults(group)
    tick = time.monotonic()
    ck = (group, _db_id())
    hit = _cache.get(ck)
    if conn is None and now is None and hit and tick - hit[0] < _TTL:
        return dict(hit[1])
    own = conn is None
    try:
        c = conn if conn is not None else get_db()
        try:
            vals = _effective(c, group, now)
        finally:
            if own:
                c.close()
    except Exception:                               # noqa: BLE001 — 設定讀取不可拖垮呼叫端
        logger.warning("settings: 讀取群組 %s 失敗，改用快取或預設", group, exc_info=True)
        return dict(hit[1]) if hit else _defaults(group)
    if own and now is None:
        with _lock:
            _cache[ck] = (tick, vals)
    return dict(vals)


def get(group, field, *, conn=None, now=None):
    vals = get_group(group, conn=conn, now=now)
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


def confirm_period_days(conn=None):
    """變更確認期間（天）：`change_control.confirm_period_days`，預設 7、下限 1（程式下限，設定與授權邊界都不能低於）。永不丟例外。"""
    own = conn is None
    try:
        c = conn if conn is not None else get_db()
        try:
            v = _effective(c, CONFIRM_GROUP)[CONFIRM_FIELD]
        finally:
            if own:
                c.close()
        return max(1, int(v))
    except Exception:                               # noqa: BLE001 — 群組沒登錄或讀不到 ⇒ 預設
        return DEFAULT_CONFIRM_DAYS


def _rank(f, v):
    return float("inf") if (f.zero_is_max and v == 0) else v


def banner_of(f, value, *, default=None, days=None):
    """畫面橫幅（欄位版面框架 §16.6）：回 None（不顯示）或 `{"level": "amber"|"red", "lines": [三行白話], "fallback": bool}`。
    只在『風險 ≥ money、值不是預設、且（有 `loosen` 的數值欄位）往放寬方向』時出現。等級：風險 legal／security 或不可復原 ⇒ 紅，其餘（money）⇒ 琥珀。
    有 `impact_scope` ⇒ 依結構產生三行（單據／人／金額與後果＋可否復原＋何時生效）；沒有（E-e 之前登錄的欄位）⇒ 降級為『影響說明＋風險提示＋何時生效』。
    句子一律由這裡產生，畫面只負責呈現。`days`＝目前的變更確認期間（天），省略用預設。"""
    base = f.default if default is None else default
    if value == base or RISK_ORDER.index(f.risk) < RISK_ORDER.index("money"):
        return None
    if f.loosen and isinstance(value, (int, float)) and not isinstance(value, bool):
        a, b = _rank(f, value), _rank(f, base)
        if not ((f.loosen == "up" and a > b) or (f.loosen == "down" and a < b)):
            return None
    n = int(days or DEFAULT_CONFIRM_DAYS)
    if f.loosen:
        when = "需等 %d 天確認期間，並經另一位最高管理者核准後才會生效（只有一位最高管理者時，改為填寫原因、等確認期間後生效）" % n
    elif f.requires_pending:
        when = "需等 %d 天確認期間後才會生效，期間內可以撤銷" % n
    else:
        when = "儲存後立即生效"
    s = f.impact_scope
    if s is None:
        lines = [f.impact]
        if f.risk_text:
            lines.append("注意：" + f.risk_text)
        lines.append(when)
        return {"level": "red" if f.risk in ("legal", "security") else "amber", "lines": lines, "fallback": True}
    docs = "、".join(s["documents"]) if s["documents"] else "不影響既有單據"
    roles = "、".join(s["roles"]) if s["roles"] else "不影響特定角色"
    return {"level": "red" if (f.risk in ("legal", "security") or not s["reversible"]) else "amber",
            "lines": ["會影響這些單據：" + docs, "會影響這些人：" + roles,
                      "%s。%s；%s。" % (s["amounts"].rstrip("。"), "可以復原" if s["reversible"] else "無法復原", when)],
            "fallback": False}


def field_defs(group):
    """群組的欄位定義 `{欄位鍵: SettingDef}`（唯讀複本；給設定中心的差異／白話顯示用）。"""
    return dict(_g(group)["fields"])


def field_views(group, values=None, *, days=None):
    """設定中心畫面用的欄位清單：欄位定義（含版本邊界後的有效範圍）＋目前值、白話值、是否預設、預設的白話值、目前值的橫幅、
    選項型欄位每個選項的橫幅（`choiceBanners`，鍵為代碼字串）。句子與等級一律由這裡（`banner_of`）產生。"""
    g = _g(group)
    vals = values if values is not None else get_group(group)
    n = days if days is not None else confirm_period_days()
    out = []
    for k, f in g["fields"].items():
        lo, hi = _bounds(group, f)
        cur = vals[k]
        m = dict(f.meta(), min=lo, max=hi)
        m.update(value=cur, valueText=show_value(f, cur), isDefault=(cur == f.default), defaultText=show_value(f, f.default),
                 recommendedText=(show_value(f, f.recommended) if f.recommended is not None else None),
                 banner=banner_of(f, cur, days=n),
                 choiceBanners=({str(c[0]): banner_of(f, c[0], days=n) for c in f.choices} if f.choices else None))
        out.append(m)
    return out


def _split(g, eff, values):
    """把本次送出的欄位分成 (待生效 pend, 立即 imm, 放寬 loose)。`publish()` 與 `plan()`（預覽）共用同一個分類，不得各寫一份。"""
    def _loosens(f, new_v):
        old_v = eff[f.key]
        if not (f.loosen and isinstance(new_v, (int, float)) and not isinstance(new_v, bool)):
            return False
        a, b = _rank(f, new_v), _rank(f, old_v)
        return (f.loosen == "up" and a > b) or (f.loosen == "down" and a < b)
    pend = {k: v for k, v in values.items() if g["fields"][k].requires_pending or _loosens(g["fields"][k], v)}
    imm = {k: v for k, v in values.items() if k not in pend}
    loose = {k for k, v in pend.items() if _loosens(g["fields"][k], v)}
    return pend, imm, loose


def show_value(f, v):
    """給人看的值（白話）：選項型＝中文標籤；開關＝開／關；其他＝值＋單位。內部代碼不外露。"""
    for c in f.choices:
        if c[0] == v:
            return c[1]
    if isinstance(v, bool):
        return "開" if v else "關"
    return "%s%s" % (v, (" " + f.unit) if f.unit else "")


def plan(group, values, *, user="", conn=None):
    """預覽（dry-run）：**不寫入、不 commit**。回逐欄分類與驗證結果，分類與 `publish()` 完全一致（共用 `_split`）。
    `kind`：`immediate`（立即生效）｜`pending`（確認期間後生效）｜`pending_approval`（確認期間後且需另一位最高管理者核准）｜`unchanged`。"""
    from datetime import datetime, timedelta
    g = _g(group)
    problems = validate_values(group, values, partial=True)
    out = {"ok": not problems, "problems": problems, "fields": [], "warnings": [], "otherSuperadmins": 0, "confirmDays": DEFAULT_CONFIRM_DAYS}
    if problems:
        return out
    own = conn is None
    c = conn if conn is not None else get_db()
    try:
        base = _effective(c, group, overlay=False)
        eff = _effective(c, group)
        days = confirm_period_days(c)
        others = c.execute("SELECT COUNT(*) FROM users WHERE active=1 AND role='superadmin' AND username<>?", (user or "",)).fetchone()[0]
    finally:
        if own:
            c.close()
    pend, imm, loose = _split(g, eff, values)
    merged = _merged(_merged(base, imm), pend)
    cross = validate_values(group, merged)                       # 與 publish 相同：整組＋跨欄位檢查
    if cross:
        out.update(ok=False, problems=cross)
        return out
    when = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    out.update(otherSuperadmins=others, confirmDays=days)
    for k, v in values.items():
        f = g["fields"][k]
        if k in pend:
            old = eff[k]
            kind = "unchanged" if v == old else ("pending_approval" if (k in loose and others > 0) else "pending")
        else:
            old = base[k]
            kind = "unchanged" if v == old else "immediate"
        approvals = 1 if kind == "pending_approval" else 0
        if kind == "immediate":
            when_text = "立即"
        elif kind == "pending":
            when_text = "%d 天確認期間後（%s 起）" % (days, when[:10])
        elif kind == "pending_approval":
            when_text = "另一位最高管理者核准、且 %d 天確認期間後（%s 起）" % (days, when[:10])
        else:
            when_text = "不變"
        effect = (f.effect.replace("{名稱}", f.label).replace("{舊}", show_value(f, old)).replace("{新}", show_value(f, v))
                  .replace("{生效時間}", when_text))
        out["fields"].append({"field": k, "label": f.label, "question": f.question, "unit": f.unit, "old": old, "new": v,
                              "oldText": show_value(f, old), "newText": show_value(f, v), "kind": kind,
                              "effectiveAt": when if kind in ("pending", "pending_approval") else None,
                              "approvalsRequired": approvals, "effect": effect, "banner": banner_of(f, v, days=days)})
    if loose and others == 0 and any(x["kind"] == "pending" and x["field"] in loose for x in out["fields"]):
        out["warnings"].append("目前只有一位最高管理者，沒有第二人可以核准：這項放寬會改為「填寫原因、等 %d 天確認期間後生效」，儲存後會留下紀錄。" % days)
    return out


_IMPACT_CACHE = {}          # (db, group, field, 值) -> (monotonic, 結果)
_IMPACT_TTL = 60.0
_IMPACT_TIMEOUT = 1.5
_IMPACT_CACHE_MAX = 256


def live_impact(group, field, value, *, timeout=None):
    """即時影響（唯讀）：呼叫欄位的 `impact_fn(conn, 新值)`。唯讀連線（`PRAGMA query_only`）、逾時 1.5 秒、結果快取 60 秒；
    沒有 `impact_fn`、值不合法、逾時或丟例外 ⇒ `live=None`，只回靜態 `impact`（永不丟例外）。
    ⚠ 逾時只是「不再等」：計算用的 daemon 執行緒會繼續跑到 `impact_fn` 結束（結果丟棄、不寫快取），所以 `impact_fn` 自己必須有成本上限（查詢要有索引／LIMIT）。回 `{"live": {numbers, sentence}|None, "static": impact}`。"""
    import json as _json
    g = _g(group)
    f = g["fields"].get(field)
    if f is None:
        raise KeyError("群組 %r 沒有欄位 %r" % (group, field))
    res = {"live": None, "static": f.impact}
    if f.impact_fn is None or f.check(value):
        return res
    ck = (_db_id(), group, field, _json.dumps(value, sort_keys=True, default=str))
    hit = _IMPACT_CACHE.get(ck)
    if hit and time.monotonic() - hit[0] < _IMPACT_TTL:
        return {"live": hit[1], "static": f.impact}
    box = {}

    def _run():
        c = None
        try:
            c = get_db()
            c.execute("PRAGMA query_only = ON")                    # 唯讀：impact_fn 想寫就會失敗
            box["v"] = f.impact_fn(c, value)
        except Exception:                                           # noqa: BLE001
            logger.warning("settings: %s.%s 的即時影響計算失敗，改顯示靜態說明", group, field, exc_info=True)
        finally:
            if c is not None:
                c.close()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout if timeout is not None else _IMPACT_TIMEOUT)
    v = box.get("v")
    if isinstance(v, dict) and v.get("sentence"):
        live = {"numbers": v.get("numbers"), "sentence": str(v["sentence"])}
        with _lock:
            while len(_IMPACT_CACHE) >= _IMPACT_CACHE_MAX:             # 有上限：不讓不同值的請求把快取撐大
                _IMPACT_CACHE.pop(next(iter(_IMPACT_CACHE)))
            _IMPACT_CACHE[ck] = (time.monotonic(), live)
        res["live"] = live
    return res


def publish(group, values, *, note="", user="", reason="", ip="", conn=None, actor=None):
    """唯一寫入口。`values`＝要改的欄位（部分即可）。
    一般欄位：合併目前儲存值後整組發布成新版本，同交易寫 `config_changes`＋稽核（`settings.<group>.update`）＋舊鍵雙寫。
    `requires_pending` 欄位與放寬（`loosen`）：不立即生效——寫待生效明細（確認期間後，可撤銷），讀取時到期即生效。
    **本次送出的每個欄位**（不論立即或待生效），同欄位更早的待生效項一律標 superseded（避免舊的放寬事後蓋過新的收緊）。
    回 `{"changed": 一般欄位有無變更, "version"?, "values", "changes", "pending": [待生效項]}`；都沒有變更 ⇒ `{"changed": False, "pending": []}`。
    驗證不過 ⇒ SettingError（帶 problems）；有送審中的版本 ⇒ `core.definitions.DefinitionConflict`。"""
    from datetime import datetime, timedelta
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
        base = _effective(c, group, overlay=False)
        eff = _effective(c, group)
        pend, imm, loose = _split(g, eff, values)
        new = _merged(base, imm)
        problems = validate_values(group, _merged(new, pend))
        if problems:
            raise SettingError("設定未儲存（%d 個問題）" % len(problems), problems)
        changes = [{"field": k, "old": base[k], "new": new[k]} for k in g["fields"] if base[k] != new[k]]
        actor_ = actor if actor is not None else user
        domain = "setting:%s" % group
        result = {"changed": False, "values": eff, "pending": [], "warnings": [], "superseded": 0}
        for r in L.pending(c, domain):                # 本次送出的欄位：舊的待生效項一律被取代（即使這次是立即生效的收緊）
            if r["domain"] == domain and r["key"] == group and r["field"] in values and L.supersede(c, r["id"], actor_, "被較新的申請取代"):
                result["superseded"] += 1
        if changes:
            risk = _risk_of(group, [x["field"] for x in changes])
            out = D.publish_direct(c, KIND, group, SCOPE, {"group": group, "values": new}, note or reason, user, commit=False)
            L.record(c, domain, group, changes, reason or note, actor_, ip=ip, risk=risk, ref_version=out["version"],
                     audit_action="settings.%s.update" % group, target_label=g["label"])
            _write_legacy(c, group, new)
            result.update(changed=True, version=out["version"], values=_merged(eff, new), changes=changes)
        if pend:
            days = confirm_period_days(c)
            when = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
            pchanges = [{"field": k, "old": eff[k], "new": v} for k, v in pend.items() if eff[k] != v]
            if pchanges:
                others = c.execute("SELECT COUNT(*) FROM users WHERE active=1 AND role='superadmin' AND username<>?", (user or "",)).fetchone()[0]
                for need in (0, 1):                  # 先寫一般待生效，再寫要雙人核准的（放寬）
                    part = [x for x in pchanges if (x["field"] in loose and others > 0) == bool(need)]
                    if not part:
                        continue
                    risk = _risk_of(group, [x["field"] for x in part])
                    rec = L.record(c, domain, group, part, reason or note, actor_, ip=ip, risk=risk, effective_at=when,
                                   audit_action="settings.%s.pending" % group, target_label=g["label"], approvals_required=need)
                    result["pending"] += [{"id": i, "field": x["field"], "new": x["new"], "effectiveAt": when, "approvalsRequired": need}
                                          for i, x in zip(rec["ids"], part)]
                if loose and others == 0 and any(x["field"] in loose for x in pchanges):
                    result["warnings"].append("目前只有一位最高管理者，沒有第二人可以核准：這項放寬改為「填寫原因、等 %d 天確認期間後生效」，並已留下紀錄。" % days)
        if not changes and not pend and not result["superseded"]:
            if began:
                c.rollback()
            return result
        c.commit()
        invalidate(group)
        return result
    except Exception:
        if began and c.in_transaction:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def materialize_due(conn=None, now=None):
    """把已到時的待生效值寫進定義版本並標 activated（每日工作呼叫；漏跑也不影響效力——讀取時本來就套用到時的待生效值）。回處理的明細列數。"""
    from datetime import datetime
    from core.txn import begin_write
    from helpers import config_ledger as L
    now = now or datetime.now().isoformat(timespec="seconds")
    own = conn is None
    c = conn if conn is not None else get_db()
    began, total = False, 0
    try:
        began = begin_write(c)
        for group in list(_GROUPS):
            due = _due_pending(c, group, now)
            if not due:
                continue
            base = _effective(c, group, overlay=False)
            new = dict(base)
            for r in list(due):
                if validate_values(group, {r["field"]: r["new"]}, partial=True):
                    logger.warning("settings: 待生效項 #%s（%s.%s=%r）超出目前的欄位範圍或版本邊界，自動撤銷", r["id"], group, r["field"], r["new"])
                    L.cancel(c, r["id"], "system", "超出目前的欄位範圍或版本邊界，到期時自動撤銷")
                    due.remove(r)
                    continue
                new[r["field"]] = r["new"]
            if not due:
                continue
            out = D.publish_direct(c, KIND, group, SCOPE, {"group": group, "values": new}, "待生效項到期生效", "system", commit=False)
            _write_legacy(c, group, new)
            total += len(L.promote_due(c, now, domain="setting:%s" % group))
            invalidate(group)
            logger.info("settings: 群組 %s 的 %d 項待生效值已生效（定義 v%s）", group, len(due), out["version"])
        if began or own:
            c.commit()
        return total
    except Exception:
        if began and c.in_transaction:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# --- 預設組（政策設定檔；販售時依客戶／版本套用，走同一條 publish 管制）-------------

def profiles():
    """所有欄位 `presets` 裡出現過的預設組名稱 → 涵蓋的欄位數。"""
    out = {}
    for g in _GROUPS.values():
        for f in g["fields"].values():
            for name in f.presets:
                out[name] = out.get(name, 0) + 1
    return out


def profile_preview(name, *, conn=None):
    """套用預設組會改哪些欄位（目前值 → 新值）；不寫入。"""
    out = []
    for gk, g in _GROUPS.items():
        cur = get_group(gk, conn=conn)
        for k, f in g["fields"].items():
            if name in f.presets and cur[k] != f.presets[name]:
                out.append({"group": gk, "groupLabel": g["label"], "field": k, "label": f.label, "old": cur[k], "new": f.presets[name], "unit": f.unit})
    return out


def apply_profile(name, *, reason="", user="", ip="", conn=None, actor=None):
    """套用預設組：每個群組各走一次 `publish()`（放寬照樣需要雙人核准／24 小時）。回 `{群組: publish 結果}`。"""
    if name not in profiles():
        raise SettingError("沒有這個預設組：%s" % name)
    by_group = {}
    for ch in profile_preview(name, conn=conn):
        by_group.setdefault(ch["group"], {})[ch["field"]] = ch["new"]
    return {gk: publish(gk, vals, note="套用預設組「%s」" % name, user=user, reason=reason or "套用預設組「%s」" % name, ip=ip, conn=conn, actor=actor)
            for gk, vals in by_group.items()}


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
