# -*- coding: utf-8 -*-
"""設定中心登錄與讀取（L1；第 54 班 Train A／S0）。每個「可調整的數字／開關」在程式裡登錄一次，值存在 `setting_group` 定義（版本、還原、差異共用 L0）。

[單位] helper:settings_registry    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] DEFAULT_CONFIRM_DAYS, DEFAULT_EFFECT, IMPACT_SCOPE_GRANDFATHERED, KIND, RISK_ORDER, SCALAR_LEGACY, SCOPE, SettingConflict, SettingDef, SettingError, apply_profile, banner_of, clamp_value, clear_edition_bounds, confirm_period_days,
    audit_spine_failures, cancel_pending_of_nonopen, field_defs, field_views, generation, get, get_group, group_info, group_stamp, group_status, groups, invalidate, live_impact, materialize_due, owner_groups, plan, profile_preview, profile_skipped, profiles, publish, register_group, set_edition_bounds, show_value, unregister_owner, validate_values
[不變式] ①`get()` **永不丟例外**：資料庫讀不到、值壞掉、型別不對、超出範圍 ⇒ 回程式預設並記 warning（`clamp` 欄位改為夾到範圍內）；
    ②**部署不寫任何定義列**：沒有列＝程式預設＝上線前的行為（`settings_deploy_baseline.json` 凍結）；③上下限**只寫在程式**（資料庫的值只是值）；
    ④寫入口只有 `publish()`：同一交易寫定義新版本＋變更明細（config_ledger）＋稽核＋（有舊鍵時）雙寫舊鍵；⑤讀取走 15 秒行程內快取，
    `publish()` 之後本行程立即失效（多行程以 TTL 為準）；⑥風險欄位（`requires_pending`）的變更不立即生效：寫待生效明細（預設 7 天＝`change_control.confirm_period_days`，下限 1 天，可撤銷），
    讀取時到期即生效（`in_effect`），`materialize_due()` 再把到期值寫進定義版本；⑦環境變數 `MOTRIX_SETTINGS_DEFAULTS_ONLY=1` ⇒ 一律回程式預設（出事時的逃生口）。
[契約題] backend/tests/platform/test_settings_registry_t54.py
"""
import copy
import inspect
import json
import logging
import os
import threading
import time
from collections import namedtuple

from core import definitions as D
from core import registry as _reg
from core import spine as _spine
from db import get_db

logger = logging.getLogger("motrix.settings")

KIND = "setting_group"
SCOPE = "company"
_TTL = 15.0
DEFAULT_CONFIRM_DAYS = 7                       # 變更確認期間預設天數（設定 `change_control.confirm_period_days` 沒有值時用；下限 1 天）
CONFIRM_GROUP, CONFIRM_FIELD = "change_control", "confirm_period_days"
_TYPES = ("int", "float", "bool", "str", "json")
#: 自訂舊儲存轉接器（SPEC §15.A.1）：`read(conn)->{欄位: 值}`（讀舊儲存並經原本的正規化；**不得**呼叫登錄表，否則遞迴）；
#: `write(conn, values, *, old=None)`（**只用傳入的 conn**、同一筆交易內、冪等；不得自開連線 commit）；`normalize(值)->值`（選填，json 欄位 CAS 前先正規化）。
Adapter = namedtuple("Adapter", "read write normalize", defaults=(None,))
JSON_MAX_CHARS = 15000                         # json 欄位序列化後的長度上限（待生效明細層 20000 會截斷，留餘裕；欄位定義可調）


def _canon(v):
    """標準 JSON（sort_keys、無空白、不轉義中文）：json 欄位 CAS／相等比較用。"""
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

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
    global _EDITION_EPOCH
    _EDITION[(group, field)] = (min, max)
    _EDITION_EPOCH += 1


def clear_edition_bounds():
    global _EDITION_EPOCH
    _EDITION.clear()
    _EDITION_EPOCH += 1


#: 欄位的 `legacy` 設成這個值 ⇒ 舊鍵是純量（整個舊鍵就是該欄位的值），不是 dict（T69 管銷預設％：overhead_default_pct）
SCALAR_LEGACY = "="

_UNKNOWN_STAMP = __import__("itertools").count(1)
_EDITION_EPOCH = 0                             # 版本邊界每變一次就加一；納入 group_stamp（邊界會夾住 get_group 的結果）


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


class SettingConflict(Exception):
    """逐欄 CAS 失敗：呼叫端看到的舊值，在送出前已被別人改掉。`keys`＝衝突欄位鍵；`by`／`at`＝最近改的人與時間
    （沒有帳本紀錄 ⇒ by＝「系統預設」或「舊路徑寫入，時間不明」、at＝空字串）。**不是** SettingError（不是 400 的輸入問題）。"""
    def __init__(self, keys, by="", at="", code="conflict"):
        super().__init__("這些設定在你送出前已被別人改動：%s" % "、".join(keys))
        self.keys, self.by, self.at, self.code = list(keys), by, at, code        # code：conflict｜pending_exists（json 欄位已有別人的待生效申請）


def _same_value(a, b):
    """CAS 用的相等：數字不分 int／float（JSON 來回），布林與數字不混。"""
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return isinstance(a, (list, dict)) and isinstance(b, (list, dict)) and _canon(a) == _canon(b)      # 巢狀 True==1、1==1.0 不會假相等
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b       # True == 1 在 Python 成立，這裡不讓它成立
    num = lambda v: isinstance(v, (int, float))                               # noqa: E731
    return (float(a) == float(b)) if (num(a) and num(b)) else a == b


def _conflict_origin(conn, group, g, eff, keys):
    """衝突欄位裡最近一次被改的 (誰, 何時)；都查不到紀錄 ⇒ 預設值＝「系統預設」，否則「舊路徑寫入，時間不明」。"""
    from helpers import config_ledger as L
    best = None
    for k in keys:
        try:
            hit = L.last_effective_change(conn, "setting:%s" % group, group, k)
        except Exception:                                   # noqa: BLE001 — 沒有帳本（極舊庫）⇒ 退路
            hit = None
        if hit and (best is None or hit[1] > best[1]):
            best = hit
    if best:
        return best
    return ("系統預設", "") if all(_same_value(eff[k], g["fields"][k].default) for k in keys) else ("舊路徑寫入，時間不明", "")


def expected_conflict(group, expected, *, conn=None):
    """唯讀預檢（跨群組批次用）：`expected`＝`{欄位鍵: 呼叫端看到的值}`；有任一欄與目前生效值不同 ⇒ 回 `SettingConflict`（**不丟**），否則 `None`。
    只是「先看一眼、別寫到一半才發現」；真正的把關仍是 `publish(expected_values=)` 在寫鎖內的逐欄比對。未知欄位 ⇒ SettingError。"""
    g = _g(group)
    expected = _normalized(group, expected)                        # 與 publish 相同：json 值先過轉接器 normalize 再比
    own = conn is None
    c = conn if conn is not None else get_db()
    try:
        eff = _effective(c, group)
        unknown = [k for k in expected if k not in g["fields"]]
        if unknown:
            raise SettingError("expected_values 含不存在的欄位：%s" % "、".join(map(str, unknown)))
        bad = [k for k, v in expected.items() if not _same_value(eff[k], v)]
        if not bad:
            return None
        by, at = _conflict_origin(c, group, g, eff, bad)
        return SettingConflict(bad, by, at)
    finally:
        if own:
            c.close()


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
        raise ValueError("設定欄位 %r 的 impact_scope.reversible 必須是「是」或「否」" % key)
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
                 "question", "impact", "risk_text", "choices", "recommended", "presets", "advanced", "impact_fn", "effect", "loosen", "zero_is_max", "impact_scope",
                 "when", "external", "summarize", "max_chars")

    def __init__(self, key, type, default, *, question="", label="", help="", impact="", min=None, max=None, unit="", risk="ops",
                 legacy=None, clamp=False, requires_pending=False, risk_text="", choices=None, recommended=None, presets=None,
                 advanced=False, impact_fn=None, effect="", loosen=None, zero_is_max=False, impact_scope=None, when="", external="", summarize=None, max_chars=JSON_MAX_CHARS):
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
        # when＝「？」第二段「什麼時候要改」（選填，沒填就不顯示；不得與 help 一字不差＝防複製貼上）。
        # external＝一句話：這個設定要先在別處做什麼才有用（例「要先到 Google 後台開通」；空字串＝不需要，畫面顯示「要先在外部設定」標籤）。
        self.when, self.external = (when or "").strip(), (external or "").strip()
        if self.when and self.when == (help or "").strip():
            raise ValueError("設定欄位 %r 的 when 不得與 help 完全相同" % (key,))
        self.summarize, self.max_chars = summarize, int(max_chars)       # json 欄位：summarize(old, new)->[白話行]；畫面只顯示摘要，不傾倒原始內容
        if loosen not in (None, "up", "down", "both"):
            raise ValueError("loosen 只能是 up／down／both／None：%r" % (loosen,))
        if loosen in ("up", "down") and type not in ("int", "float"):
            # 方向只對數字有意義；文字／json／選項要管制就用 both（任何變更都算放寬，走第二位最高管理者核准）。
            raise ValueError("設定欄位 %r：loosen 的 up／down 只能用在數字欄位（int／float）；其他型別請用 both" % (key,))
        if type == "json" and summarize is not None and not callable(summarize):
            raise ValueError("設定欄位 %r：summarize 必須是函式" % (key,))
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
                return "必須是「是」或「否」"
            return "不是可選的選項" if (self.choices and v not in [c[0] for c in self.choices]) else ""
        if self.type == "json":
            if not isinstance(v, (list, dict)):
                return "內容格式不對"
            try:
                n = len(_canon(v))
            except (TypeError, ValueError):
                return "內容無法儲存"
            return "這份設定太大，請聯絡工程師" if n > self.max_chars else ""
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
                "presets": self.presets, "advanced": self.advanced, "effect": self.effect, "hasLiveImpact": self.impact_fn is not None, "loosen": self.loosen, "impactScope": self.impact_scope, "when": self.when, "needsExternal": self.external, "hasSummary": self.summarize is not None,
                "choices": [{"value": c[0], "label": c[1], "impact": c[2]} for c in self.choices]}


def register_group(group, label, fields, *, sensitive=False, risk="ops", legacy_key=None, cross_check=None, help="", owner=None,
                   legacy_adapter=None, external=False):
    """登錄一個設定群組。`fields`＝SettingDef 清單；`cross_check(values[, conn])->[問題]`＝跨欄位檢查（函式有第二個參數或叫 conn ⇒ 傳寫入／驗證當下的連線；部分驗證合併的是預設值，每條檢查要對單一欄位也成立）；
    `sensitive`＝只有設定權限者能讀。`legacy_adapter`＝`Adapter(read, write[, normalize])`（有的話忽略 legacy_key）；`external=True`＝登記但不出現在一般群組清單／搜尋，
    一般設定中心路由讀寫一律拒絕（只能走原頁面的舊端點），待生效頁只顯示摘要。重複登錄 ⇒ ValueError。
    `owner`：擁有者（模組鍵）；省略 ⇒ 載入器 import 該模組期間自動帶入（`core.registry.owner_scope`），不在範圍內 ⇒ `core`。"""
    if group in _GROUPS:
        raise ValueError("設定群組已登錄：%r" % group)
    cur = _reg.current_owner()
    if owner is not None and cur is not None and owner != cur:
        # 模組 import 期間只能替自己登記：不准替別人（或 core）登記，否則別人載入失敗時會連帶刪掉不是它的群組
        raise ValueError("設定群組 %r：import 範圍的擁有者是 %r，不能指定 owner=%r" % (group, cur, owner))
    if not _zh(label) or not _zh(help):
        raise ValueError("設定群組 %r 需要繁中的名稱與說明" % group)
    names = [f.key for f in fields]
    if len(set(names)) != len(names):
        raise ValueError("群組 %r 欄位重複" % group)
    _GROUPS[group] = {"label": label, "fields": {f.key: f for f in fields}, "sensitive": bool(sensitive), "risk": risk,
                      "legacy_key": legacy_key, "cross_check": cross_check, "help": help, "adapter": legacy_adapter, "external": bool(external),
                      "owner": owner if owner is not None else (cur or "core")}


def groups():
    return {g: {"label": v["label"], "sensitive": v["sensitive"], "risk": v["risk"], "help": v["help"], "owner": v["owner"], "external": v["external"],
                "fields": [dict(f.meta(), min=_bounds(g, f)[0], max=_bounds(g, f)[1]) for f in v["fields"].values()]} for g, v in list(_GROUPS.items())}


def group_status(group):
    """群組的功能狀態 `open｜planned｜hidden`（脊柱 E-b；`features[].status`）。脊柱未初始化、匯入失敗或任何例外 ⇒ `open`（保守維持今天的行為）。"""
    try:
        return _spine.group_status(group)
    except Exception:                               # noqa: BLE001
        return "open"


def group_info(group):
    """`{status, plannedTrain, feature}`（設定中心畫面用）；脊柱不可用 ⇒ open。"""
    try:
        return _spine.group_info(group)
    except Exception:                               # noqa: BLE001
        return {"status": "open", "plannedTrain": None, "feature": None}


_NOT_OPEN_MSG = {"planned": "這項功能還在開發中，尚未開放調整。", "hidden": "沒有這個設定群組。"}


def cancel_pending_of_nonopen(conn=None):
    """啟動時（`spine.validate_all()` 之後的回呼）：非 open 群組的**所有**待生效項標 `cancelled`（ledger actor＝`system`），已投的核准票隨之作廢、
    之後翻回 open 也不復活。永不丟例外（沒有資料庫、舊庫沒有明細表都只是略過）。回取消筆數。"""
    from helpers import config_ledger as L
    n = 0
    own = conn is None
    c = None
    try:
        c = conn if conn is not None else get_db()
        for g in list(_GROUPS):
            if group_status(g) == "open":
                continue
            for r in L.pending(c, "setting:%s" % g):
                if r["domain"] == "setting:%s" % g and L.cancel(c, r["id"], "system", "功能改為開發中／隱藏，待生效項自動撤銷"):
                    n += 1
            invalidate(g)
        if n:
            c.commit()
    except Exception:                               # noqa: BLE001
        logger.warning("settings: 取消非 open 群組的待生效項失敗", exc_info=True)
        return 0
    finally:
        if own and c is not None:
            c.close()
    return n


def audit_spine_failures(conn=None):
    """啟動時（`spine.validate_all()` 之後的回呼）：驗證失敗的功能各寫一筆稽核 `spine.validation_failed`（actor `system`）。
    **去重**：同一功能、同一組問題只記一次（簽章＝功能代號＋問題文字的雜湊），之後每次重啟不再灌；問題變了才再記。永不丟例外。回新寫的筆數。"""
    import hashlib
    from helpers import config_ledger as L
    items = []
    try:
        rep = _spine.report()
        items = [(f["code"], f["label"], f["owner"], f["problems"]) for f in rep["features"] if f["state"] == "failed"]
        items += [("owner:%s" % o, "擁有者宣告問題", o, p) for o, p in rep["orphans"].items()]
    except Exception:                               # noqa: BLE001
        return 0
    if not items:
        return 0
    n = 0
    own = conn is None
    c = None
    try:
        c = conn if conn is not None else get_db()
        for code, label, owner, problems in items:
            sig = hashlib.sha1((code + "\n" + "\n".join(problems)).encode("utf-8")).hexdigest()[:16]
            seen = False
            for (d,) in c.execute("SELECT detail FROM audit_log WHERE action='spine.validation_failed' AND target_id=?", (code,)).fetchall():
                try:                                # 逐列解析（不用 json_extract：守門棘輪）
                    if (json.loads(d) or {}).get("sig") == sig:
                        seen = True
                        break
                except (TypeError, ValueError, AttributeError):
                    continue
            if seen:
                continue
            L.audit_event(c, "system", "spine.validation_failed", code,
                          {"sig": sig, "owner": owner, "problems": problems}, target_label="功能登錄驗證失敗：%s" % label)
            n += 1
        if n:
            c.commit()
    except Exception:                               # noqa: BLE001
        logger.warning("settings: 寫功能登錄驗證失敗的稽核失敗", exc_info=True)
        return 0
    finally:
        if own and c is not None:
            c.close()
    return n


def owner_groups(owner):
    """擁有者 `owner` 登記的群組代號集合（載入器核對 module.json 宣告用）。"""
    return {g for g, v in list(_GROUPS.items()) if v["owner"] == owner}


def unregister_owner(owner):
    """移除擁有者登記的所有群組（模組載入失敗／卸載時由 `core.registry.on_unload` 呼叫）；`core` 不可移除。回移除的群組數。"""
    if owner == "core":
        return 0
    gone = [g for g, v in _GROUPS.items() if v["owner"] == owner]
    for g in gone:
        _GROUPS.pop(g, None)
        invalidate(g)
    return len(gone)


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
    return {k: (copy.deepcopy(f.default) if f.type == "json" else f.default) for k, f in _g(group)["fields"].items()}


def clamp_value(f, v):
    """讀取時的夾值（`clamp` 欄位）：只往範圍內夾，型別不對仍回預設。"""
    if f.check(v) and not (f.clamp and isinstance(v, (int, float)) and not isinstance(v, bool)):
        return f.default
    if f.min is not None and v < f.min:
        v = f.min
    if f.max is not None and v > f.max:
        v = f.max
    return int(v) if f.type == "int" else v


def _call_cross(fn, merged, conn):
    """跨欄位檢查函式可以只收值，也可以多收連線（第二個位置參數或 conn 參數）。"""
    try:
        ps = inspect.signature(fn).parameters.values()
        takes = any(p.name == "conn" or p.kind == p.VAR_POSITIONAL for p in ps) or \
            sum(1 for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)) >= 2
    except (TypeError, ValueError):
        takes = False
    if not takes:
        return fn(merged)
    if conn is not None:
        return fn(merged, conn)
    c = get_db()                                    # 呼叫端沒給連線（預檢、定義種類驗證器）：開一條唯讀的臨時連線，別把 None 交給要查庫的檢查
    try:
        return fn(merged, c)
    finally:
        c.close()


def validate_values(group, values, *, partial=False, conn=None):
    """逐欄 + 跨欄位檢查（寫入時嚴格，不夾值）。回 `[{path, message}]`。`conn`＝給需要查資料庫的跨欄位檢查用（可為 None）。"""
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
            out += list(_call_cross(g["cross_check"], _merged(_defaults(group), values), conn))
        except Exception as e:                      # noqa: BLE001
            out.append({"path": "", "message": "跨欄位檢查失敗：%s" % e})
    return out


# --- 讀 ---------------------------------------------------------------

def _legacy_values(conn, group, strict=False):
    g = _g(group)
    ad = g.get("adapter")
    if ad is not None:                              # 自訂轉接器（SPEC §15.A.1）：讀舊儲存並經原本的正規化；出錯 ⇒ 當作沒有（strict＝金額／法遵讀取端：丟出去）
        try:
            raw = ad.read(conn)
        except Exception:                           # noqa: BLE001
            if strict:
                raise
            logger.warning("settings: 群組 %s 的舊儲存轉接器讀取失敗", group, exc_info=True)
            return {}
        return {k: v for k, v in raw.items() if k in g["fields"]} if isinstance(raw, dict) else {}
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
        # 純量舊鍵（T69）：欄位的 `legacy` 為 SCALAR_LEGACY ⇒ 舊鍵本身就是這個欄位的值（例：overhead_default_pct＝25）
        return {k: raw for k, f in g["fields"].items() if f.legacy == SCALAR_LEGACY and not isinstance(raw, bool)}
    return {k: raw[f.legacy] for k, f in g["fields"].items() if f.legacy and f.legacy != SCALAR_LEGACY and f.legacy in raw}


def _has_legacy_source(group):
    g = _g(group)
    return g.get("adapter") is not None or bool(g.get("legacy_key"))


def _stored(conn, group, strict=False):
    """資料庫裡的值（定義最新發布版優先，否則舊鍵）；沒有 ⇒ {}。"""
    try:
        row = D.get(conn, KIND, group, SCOPE)
    except Exception:                               # noqa: BLE001 — 定義表還沒建（極舊庫／獨立執行的備份工作）⇒ 只看舊鍵
        if strict and not _has_legacy_source(group):
            raise                                   # 嚴格讀取、又沒有舊儲存可退：讀不到就是讀不到，不能默默當成沒存過（會變預設值）
        row = None
    if row is not None:
        body = row.get("body") or {}
        vals = body.get("values") if isinstance(body, dict) else None
        if isinstance(vals, dict):
            return vals
        logger.warning("settings: 群組 %s 的定義內容格式不對，改用預設", group)
        return {}
    return _legacy_values(conn, group, True) if strict else _legacy_values(conn, group)


def _due_pending(conn, group, now):
    """已到時、尚未被寫進定義的待生效值（依申請先後；同欄位後者蓋前者）。只有群組含 `requires_pending` 欄位才查。
    非 open 群組（功能 planned／hidden）一律回空：即使項目已到時、票數已足，讀取時也不生效——讀到的永遠是已儲存的值。"""
    if group_status(group) != "open":
        return []
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


def _effective(conn, group, now=None, overlay=True, strict=False):
    g = _g(group)
    out = _defaults(group)
    for k, v in (_stored(conn, group, True) if strict else _stored(conn, group)).items():     # 非嚴格時維持舊呼叫形狀（測試會換掉 _stored）
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
            if not validate_values(group, {r["field"]: r["new"]}, partial=True, conn=conn):      # 含版本邊界：邊界收緊後，舊的待生效值不會生效
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


def get_group_effective(group, *, conn=None, now=None):
    """**金額／法遵讀取端用的嚴格版**（SPEC §15.A.6 N2）：永遠讀即時的生效值（含到時的待生效），**忽略 `MOTRIX_SETTINGS_DEFAULTS_ONLY`**、不用行程內快取；
    登錄表讀取失敗 ⇒ 退回轉接器 RAW 舊儲存（＝最後一次生效的值），**絕不退回程式預設**；連 RAW 也讀不到 ⇒ 丟例外（寧可大聲失敗，也不用錯的金額）。"""
    g = _g(group)
    own = conn is None
    c = conn if conn is not None else get_db()
    try:
        try:
            return _effective(c, group, now, strict=True)
        except Exception:                           # noqa: BLE001
            if not _has_legacy_source(group):
                raise                               # 這個群組的值只存在登錄表的定義裡；讀不到就大聲失敗，不退回預設值
            logger.error("settings: 嚴格讀取群組 %s 失敗，退回舊儲存（不用預設）", group, exc_info=True)
            return _merged(_defaults(group), _legacy_values(c, group, strict=True))      # 轉接器讀不到 ⇒ 這裡丟例外（大聲失敗）
    finally:
        if own:
            c.close()


def get(group, field, *, conn=None, now=None):
    vals = get_group(group, conn=conn, now=now)
    if field not in vals:
        raise KeyError("群組 %r 沒有欄位 %r" % (group, field))
    return vals[field]


def _db_id():
    import db
    return str(getattr(db, "DB_PATH", ""))


_generation = 0                                # 每次 invalidate（設定發布／改寫）加一：給「自己再快取一層」的呼叫端判斷快取是否作廢（簽核二擇一 S3b 的 reconfirm_mode）


def generation() -> int:
    """設定快取世代：`invalidate()` 每呼叫一次加一。呼叫端把自己的衍生快取連同世代存起來，世代變了就重讀。"""
    return _generation


def invalidate(group=None):
    global _generation
    with _lock:
        _generation += 1
        if group is None:
            _cache.clear()
        else:
            for k in [k for k in _cache if k[0] == group]:
                del _cache[k]


# --- 寫 ---------------------------------------------------------------

def _write_legacy(conn, group, values, old=None):
    """雙寫舊鍵（一班過渡）：只動有 `legacy` 名的欄位，保留舊 dict 裡其他鍵。有自訂轉接器 ⇒ 交給它（只用傳入的 conn、冪等）。"""
    g = _g(group)
    if g.get("adapter") is not None:
        g["adapter"].write(conn, dict(values), old=old)
        return
    if not g["legacy_key"]:
        return
    from datetime import datetime
    for k, f in g["fields"].items():                  # 純量舊鍵：整個舊鍵就是這個欄位的值（寫純量，不是 dict）
        if f.legacy == SCALAR_LEGACY and k in values:
            conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                         (g["legacy_key"], json.dumps(values[k], ensure_ascii=False), datetime.now().isoformat()))
            return
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (g["legacy_key"],)).fetchone()
    try:
        cur = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    for k, f in g["fields"].items():
        if f.legacy and f.legacy != SCALAR_LEGACY and k in values:
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
        if not (f.loosen == "both" or (f.loosen == "up" and a > b) or (f.loosen == "down" and a < b)):
            return None
    n = int(days or DEFAULT_CONFIRM_DAYS)
    if f.loosen:
        when = "需等 %d 天，並經另一位最高管理者核准後才會生效（只有一位最高管理者時，改為填寫原因、同樣等待期滿後生效）" % n
    elif f.requires_pending:
        when = "需等 %d 天後才會生效，期間內可以撤銷" % n
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


def _help_parts(f):
    """「？」四段（SPEC §6）：這是什麼／什麼時候要改／改了會影響什麼／建議。空段不出現。"""
    p = {"what": "\n".join(x for x in (f.question, f.help) if x),
         "when": f.when,
         "impact": "\n".join(x for x in (f.impact, f.risk_text) if x),
         "recommend": ""}
    if f.recommended is not None:
        p["recommend"] = show_value(f, f.recommended)
    return {k: v for k, v in p.items() if v}


def _sources(group, vals, conn):
    """每欄的來源（C7）：`{欄位鍵: {kind, by, at, reason}}`。kind＝pending（有等待生效的申請）／company（帳本有已生效的變更）／
    default（等於程式預設、沒有紀錄）／legacy（不等於預設、帳本沒有紀錄＝舊位置寫的）。個人層（personal）只給個人偏好頁，設定中心不會有。"""
    from helpers import config_ledger as L
    g = _g(group)
    out = {}
    for k, f in g["fields"].items():
        e, p = L.field_rows(conn, "setting:%s" % group, group, k)               # 依欄位查，不受同群組其他欄位的筆數影響
        r, kind = (p, "pending") if p is not None else (e, "company")
        if r is not None:
            out[k] = {"kind": kind, "by": r.get("actor_display") or r.get("actor") or "", "at": r.get("effective_at") or r.get("at") or "",
                      "reason": r.get("reason") or ""}
        else:
            out[k] = {"kind": "default" if _same_value(vals[k], f.default) else "legacy", "by": "", "at": "", "reason": ""}
    return out


def field_views(group, values=None, *, days=None, conn=None):
    """設定中心畫面用的欄位清單：欄位定義（含版本邊界後的有效範圍）＋目前值、白話值、是否預設、預設的白話值、目前值的橫幅、
    選項型欄位每個選項的橫幅（`choiceBanners`，鍵為代碼字串）。句子與等級一律由這裡（`banner_of`）產生。"""
    g = _g(group)
    vals = values if values is not None else get_group(group)
    n = days if days is not None else confirm_period_days()
    own = conn is None
    src = {}
    try:
        c = conn if conn is not None else get_db()
        try:
            src = _sources(group, vals, c)
        finally:
            if own:
                c.close()
    except Exception:                               # noqa: BLE001 — 來源只是顯示；讀不到就不顯示徽章，不拖垮整頁
        logger.warning("settings: 讀取群組 %s 的來源失敗", group, exc_info=True)
    out = []
    for k, f in g["fields"].items():
        lo, hi = _bounds(group, f)
        cur = vals[k]
        m = dict(f.meta(), min=lo, max=hi)
        m.update(helpParts=_help_parts(f), source=src.get(k))
        m.update(value=cur, valueText=show_value(f, cur), isDefault=(cur == f.default), defaultText=show_value(f, f.default),
                 recommendedText=(show_value(f, f.recommended) if f.recommended is not None else None),
                 banner=banner_of(f, cur, days=n),
                 choiceBanners=({str(c[0]): banner_of(f, c[0], days=n) for c in f.choices} if f.choices else None))
        out.append(m)
    return out


def group_stamp(group, *, conn=None):
    """群組目前『有效值可能改變』的戳記（給規則等下游快取當鍵的一部分）：功能狀態、緊急逃生口、最新發布版本、
    待生效項（全部 id）與其中已生效者（id）、版本邊界世代（set／clear_edition_bounds 會夾住有效值）。任何會改變 `get_group()` 結果的事件都會讓字串改變；讀不到資料庫 ⇒ 回每次都不同的字串（不讓下游快取住未知狀態）。永不丟例外。"""
    import time as _t
    try:
        _g(group)
        own = conn is None
        c = conn if conn is not None else get_db()
        try:
            row = D.get(c, KIND, group, SCOPE)
            ver = row["version"] if row else 0
            pend, eff_ids = [], []
            from datetime import datetime
            from helpers import config_ledger as L
            now = datetime.now().isoformat(timespec="seconds")
            for r in L.pending(c, "setting:%s" % group):
                if r["domain"] == "setting:%s" % group:
                    pend.append(r["id"])
                    if L.in_effect(r, now):
                        eff_ids.append(r["id"])
        finally:
            if own:
                c.close()
        return "%s|%s|v%s|p%s|e%s|ed%d" % (group_status(group), "d" if os.environ.get("MOTRIX_SETTINGS_DEFAULTS_ONLY") == "1" else "-",
                                           ver, ",".join(map(str, sorted(pend))), ",".join(map(str, sorted(eff_ids))), _EDITION_EPOCH)
    except Exception:                                   # noqa: BLE001
        return "unknown:%d" % next(_UNKNOWN_STAMP)         # 遞增計數（Windows 的 monotonic_ns 解析度粗，連續兩次可能相同）


def _split(g, eff, values):
    """把本次送出的欄位分成 (待生效 pend, 立即 imm, 放寬 loose)。`publish()` 與 `plan()`（預覽）共用同一個分類，不得各寫一份。"""
    def _loosens(f, new_v):
        old_v = eff[f.key]
        if f.loosen == "both" and f.type not in ("int", "float"):     # 文字／json／選項：任何實質變更都算放寬（不分方向）
            return not _same_value(new_v, old_v)
        if not (f.loosen and isinstance(new_v, (int, float)) and not isinstance(new_v, bool)):
            return False
        if f.loosen == "both":                          # 兩個方向都算放寬（例：同一門檻被多條規則以不同方向引用）：任何變動都走放寬流程
            return _rank(f, new_v) != _rank(f, old_v)
        a, b = _rank(f, new_v), _rank(f, old_v)
        return (f.loosen == "up" and a > b) or (f.loosen == "down" and a < b)
    pend = {k: v for k, v in values.items() if g["fields"][k].requires_pending or _loosens(g["fields"][k], v)}
    imm = {k: v for k, v in values.items() if k not in pend}
    loose = {k for k, v in pend.items() if _loosens(g["fields"][k], v)}
    return pend, imm, loose


def show_value(f, v):
    """給人看的值（白話）：選項型＝中文標籤；開關＝開／關；json＝摘要（不傾倒原始內容）；其他＝值＋單位。內部代碼不外露。"""
    if f.type == "json":
        if f.summarize is not None:
            try:
                return "；".join(f.summarize(None, v)) or "（空）"
            except Exception:                       # noqa: BLE001
                pass
        return "已設定內容"
    for c in f.choices:
        if c[0] == v:
            return c[1]
    if isinstance(v, bool):
        return "開" if v else "關"
    return "%s%s" % (v, (" " + f.unit) if f.unit else "")


def _summary_of(f, old, new):
    """json 欄位的「改了什麼」白話行（確認視窗、通知、待生效頁用）；沒有 summarize 或出錯 ⇒ 空清單。"""
    if f.type != "json" or f.summarize is None:
        return []
    try:
        return [str(x) for x in f.summarize(old, new)]
    except Exception:                               # noqa: BLE001
        return []


def _normalized(group, values):
    """json 欄位送進來先過轉接器的 normalize（CAS 與驗證兩邊都對正規化後的值算）；沒有 normalize 或出錯 ⇒ 原樣。"""
    g = _g(group)
    ad = g.get("adapter")
    if ad is None or ad.normalize is None or not isinstance(values, dict):
        return values
    out = dict(values)
    for k, v in values.items():
        f = g["fields"].get(k)
        if f is not None and f.type == "json":
            try:
                out[k] = ad.normalize(v)
            except Exception:                       # noqa: BLE001
                pass
    return out


def plan(group, values, *, user="", conn=None):
    """預覽（dry-run）：**不寫入、不 commit**。回逐欄分類與驗證結果，分類與 `publish()` 完全一致（共用 `_split`）。
    `kind`：`immediate`（立即生效）｜`pending`（確認期間後生效）｜`pending_approval`（確認期間後且需另一位最高管理者核准）｜`unchanged`。"""
    from datetime import datetime, timedelta
    g = _g(group)
    values = _normalized(group, values)
    st = group_status(group)
    if st != "open":
        return {"ok": False, "problems": [{"path": "", "message": _NOT_OPEN_MSG.get(st, "這個設定群組目前不可調整。")}], "fields": [], "warnings": [],
                "otherSuperadmins": 0, "confirmDays": DEFAULT_CONFIRM_DAYS, "status": st}
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
        from helpers import config_ledger as _L
        others = len(_L.real_superadmins(c, user))          # 展示帳號不算第二位
        pend, imm, loose = _split(g, eff, values)
        merged = _merged(_merged(base, imm), pend)
        cross = validate_values(group, merged, conn=c)           # 與 publish 相同：整組＋跨欄位檢查（跨欄位檢查可查資料庫）
    finally:
        if own:
            c.close()
    if cross:
        out.update(ok=False, problems=cross)
        return out
    when = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    out.update(otherSuperadmins=others, confirmDays=days)
    for k, v in values.items():
        f = g["fields"][k]
        if k in pend:
            old = eff[k]
            kind = "unchanged" if _same_value(v, old) else ("pending_approval" if (k in loose and others > 0) else "pending")
        else:
            old = base[k]
            kind = "unchanged" if _same_value(v, old) else "immediate"
        approvals = 1 if kind == "pending_approval" else 0
        if kind == "immediate":
            when_text = "立即"
        elif kind == "pending":
            when_text = "%d 天後（%s 起）" % (days, when[:10])
        elif kind == "pending_approval":
            when_text = "另一位最高管理者核准、且 %d 天後（%s 起）" % (days, when[:10])
        else:
            when_text = "不變"
        effect = (f.effect.replace("{名稱}", f.label).replace("{舊}", show_value(f, old)).replace("{新}", show_value(f, v))
                  .replace("{生效時間}", when_text))
        out["fields"].append({"field": k, "label": f.label, "question": f.question, "unit": f.unit, "old": old, "new": v,
                              "oldText": show_value(f, old), "newText": show_value(f, v), "kind": kind,
                              "effectiveAt": when if kind in ("pending", "pending_approval") else None,
                              "approvalsRequired": approvals, "effect": effect, "banner": banner_of(f, v, days=days),
                              "summary": _summary_of(f, old, v) if kind != "unchanged" else []})
    if loose and others == 0 and any(x["kind"] == "pending" and x["field"] in loose for x in out["fields"]):
        out["warnings"].append("目前只有一位最高管理者，沒有第二人可以核准：這項放寬會改為「填寫原因、等 %d 天後生效」，儲存後會留下紀錄。" % days)
    out["recipients"] = plan_recipients(group, out["fields"], user=user)
    return out


def plan_recipients(group, fields, *, user=""):
    """收件人預覽（dry-run；確認視窗用）：`fields`＝`plan()["fields"]`。⇒ `helpers.settings_notify.preview_recipients` 的結果
    （`superadmins`／`others`／`ignoredRoles`／`line`）；沒有實際變更的欄位不算。永不丟例外。"""
    from helpers import settings_notify as _SN
    phase = {"immediate": "updated", "pending": "pending", "pending_approval": "pending_approval"}
    items = [_SN.setting_item(group, x["field"], x["old"], x["new"], phase[x["kind"]], actor=user, effective_at=x.get("effectiveAt") or "") for x in fields if x["kind"] in phase]
    return _SN.preview_recipients(items)


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
    if f.impact_fn is None or f.check(value) or group_status(group) != "open":
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


def _notice_watermark(c):
    """notifications 的水位線（寫鎖內呼叫）：之後新增的列 id 一定 > 回傳值；取不到 ⇒ `None`（呼叫端跳過去重，最壞多發一則通知）。

    平常取自 `sqlite_sequence`（notifications.id 是 AUTOINCREMENT：seq＝曾經用過的最大 id，≥ MAX(id)），不讀 notifications 的列。
    ⚠️ 查不到 seq 列有兩種情況：新庫還沒寫過任何通知，或（不該發生）有人清掉了 sqlite_sequence 而舊通知還在。
    ☠️ 兩者不分、一律當 0 的話，第二種會讓去重的 DELETE 把舊的 `setting:*` 通知一起刪掉；改成「跳過去重」則新庫的第一次存檔會多發一則。
    ⇒ 只在這個罕見分支回退 `SELECT MAX(id) FROM notifications`（通知水位線、只讀 id、無業務資料）；
       這一筆未範圍讀取已登記進 unscoped_reads 基準（PM 核准 +1，原因見 test_unscoped_reads_ratchet 的 MAX_ENTRIES 註解）。
       ⛔ 不在 notifications 寫暫存列來取 id（PM 否決：NOT NULL 欄位、日後 trigger／監聽、會推進 sqlite_sequence、稽核看不懂）。
    任何一步出錯 ⇒ `None`（跳過去重，不讓設定存檔失敗）。"""
    try:
        row = c.execute("SELECT seq FROM sqlite_sequence WHERE name='notifications'").fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return int(c.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0])
    except Exception:   # noqa: BLE001
        logger.exception("settings_registry: 取不到通知水位線，這次略過通知去重")
        return None


def publish(group, values, *, note="", user="", reason="", ip="", conn=None, actor=None, expected_values=None, supersede=False):
    """唯一寫入口。`values`＝要改的欄位（部分即可）。
    一般欄位：合併目前儲存值後整組發布成新版本，同交易寫 `config_changes`＋稽核（`settings.<group>.update`）＋舊鍵雙寫。
    `requires_pending` 欄位與放寬（`loosen`）：不立即生效——寫待生效明細（確認期間後，可撤銷），讀取時到期即生效。
    **本次送出的每個欄位**（不論立即或待生效），同欄位更早的待生效項一律標 superseded（避免舊的放寬事後蓋過新的收緊）。
    回 `{"changed": 一般欄位有無變更, "version"?, "values", "changes", "pending": [待生效項]}`；都沒有變更 ⇒ `{"changed": False, "pending": []}`。
    驗證不過 ⇒ SettingError（帶 problems）；有送審中的版本 ⇒ `core.definitions.DefinitionConflict`。
    `expected_values`（選填，`{欄位鍵: 呼叫端看到的值}`）＝逐欄 CAS：在 `begin_write` 之後、寫入前，逐欄比對目前**生效值**
    （含已到時的待生效覆蓋層）；任一欄不符 ⇒ `SettingConflict(keys, by, at)`，什麼都不寫。只比對有列出的欄位——
    同群組別的欄位被別人改，不會誤拒。復原＝以 `expected_values=套用後的值` 回寫套用前的值。
    json 欄位（整份文件）：同欄位已有**別人**未到期的待生效申請 ⇒ `SettingConflict(code="pending_exists")`，除非 `supersede=True`（畫面確認後才帶）；
    json 值在比對與驗證前先過轉接器的 normalize。"""
    from datetime import datetime, timedelta
    from core.txn import begin_write
    from helpers import config_ledger as L
    from helpers import settings_notify as _SN
    g = _g(group)
    values, expected_values = _normalized(group, values), (_normalized(group, expected_values) if expected_values else expected_values)
    st = group_status(group)
    if st != "open":                                # 功能狀態（脊柱）：開發中／隱藏的群組一律不能寫——引擎層攔截，內部呼叫端（預設組、還原…）一併被擋
        raise SettingError(_NOT_OPEN_MSG.get(st, "這個設定群組目前不可調整。"))
    problems = validate_values(group, values, partial=True)
    if problems:
        raise SettingError("設定未儲存（%d 個問題）" % len(problems), problems)
    own = conn is None
    c = conn if conn is not None else get_db()
    began = False
    try:
        began = begin_write(c)
        _notice_mark = _notice_watermark(c)         # 寫鎖內：之後新增的 config_change 通知都是這次 record 寫的
        _who = user or ((actor.get("username") or "") if isinstance(actor, dict) else str(actor or ""))
        _items = []                                 # 變更通知項目（commit 之後才發；見 helpers/settings_notify）
        base = _effective(c, group, overlay=False)
        eff = _effective(c, group)
        if expected_values:
            unknown = [k for k in expected_values if k not in g["fields"]]
            if unknown:
                raise SettingError("expected_values 含不存在的欄位：%s" % "、".join(map(str, unknown)))
            missing = [k for k in values if k not in expected_values]
            if missing:                                 # 有帶 expected 就要每個要改的欄位都帶（否則那欄是無條件覆寫）
                raise SettingError("每個要改的欄位都要帶 expected_values，缺：%s" % "、".join(map(str, missing)))
            bad = [k for k, v in expected_values.items() if not _same_value(eff[k], v)]
            if bad:
                by, at = _conflict_origin(c, group, g, eff, bad)
                raise SettingConflict(bad, by, at)
        if not supersede:                               # json 欄位＝整份文件：不能無聲蓋掉別人還沒到期的申請（純量沒關係，維持取代）
            me = L._actor(actor if actor is not None else user)[0]
            for r in L.pending(c, "setting:%s" % group):
                f_ = g["fields"].get(r["field"])
                if f_ is not None and f_.type == "json" and r["field"] in values and r["key"] == group and r["actor"] != me:
                    raise SettingConflict([r["field"]], r.get("actor_display") or r["actor"], r.get("at") or "", code="pending_exists")
        pend, imm, loose = _split(g, eff, values)
        new = _merged(base, imm)
        problems = validate_values(group, _merged(new, pend), conn=c)
        if problems:
            raise SettingError("設定未儲存（%d 個問題）" % len(problems), problems)
        changes = [{"field": k, "old": base[k], "new": new[k]} for k in g["fields"] if base[k] != new[k]]
        actor_ = actor if actor is not None else user
        domain = "setting:%s" % group
        result = {"changed": False, "values": eff, "pending": [], "warnings": [], "superseded": 0}
        for r in L.pending(c, domain):                # 本次送出的欄位：舊的待生效項一律被取代（即使這次是立即生效的收緊）
            if r["domain"] == domain and r["key"] == group and r["field"] in values and L.supersede(c, r["id"], actor_, "被較新的申請取代"):
                result["superseded"] += 1
                result.setdefault("supersededRequests", []).append(      # 誰的哪一筆被取代：畫面要說「已取代某某的待生效申請」
                    {"id": r["id"], "field": r["field"], "new": r["new"], "by": r.get("actor_display") or r.get("actor") or "",
                     "at": r.get("at") or ""})
        if changes:
            risk = _risk_of(group, [x["field"] for x in changes])
            out = D.publish_direct(c, KIND, group, SCOPE, {"group": group, "values": new}, note or reason, user, commit=False)
            L.record(c, domain, group, changes, reason or note, actor_, ip=ip, risk=risk, ref_version=out["version"],
                     audit_action="settings.%s.update" % group, target_label=g["label"])
            _write_legacy(c, group, new, old=base)
            _items += [_SN.setting_item(group, x["field"], x["old"], x["new"], "updated", actor=_who, reason=reason or note) for x in changes]
            result.update(changed=True, version=out["version"], values=_merged(eff, new), changes=changes)
        if pend:
            days = confirm_period_days(c)
            when = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
            pchanges = [{"field": k, "old": eff[k], "new": v} for k, v in pend.items() if eff[k] != v]
            if pchanges:
                others = len(L.real_superadmins(c, user))      # 展示帳號不算第二位
                for need in (0, 1):                  # 先寫一般待生效，再寫要雙人核准的（放寬）
                    part = [x for x in pchanges if (x["field"] in loose and others > 0) == bool(need)]
                    if not part:
                        continue
                    risk = _risk_of(group, [x["field"] for x in part])
                    rec = L.record(c, domain, group, part, reason or note, actor_, ip=ip, risk=risk, effective_at=when,
                                   audit_action="settings.%s.pending" % group, target_label=g["label"], approvals_required=need)
                    result["pending"] += [{"id": i, "field": x["field"], "new": x["new"], "effectiveAt": when, "approvalsRequired": need}
                                          for i, x in zip(rec["ids"], part)]
                    _items += [_SN.setting_item(group, x["field"], x["old"], x["new"], "pending_approval" if need else "pending", actor=_who,
                                        reason=reason or note, effective_at=when, required=need) for x in part]
                if loose and others == 0 and any(x["field"] in loose for x in pchanges):
                    result["warnings"].append("目前只有一位最高管理者，沒有第二人可以核准：這項放寬改為「填寫原因、等 %d 天後生效」，並已留下紀錄。" % days)
        if not changes and not pend and not result["superseded"]:
            if began:
                c.rollback()
            return result
        _items = [i for i in _items if i]           # setting_item 失敗會回 None：先濾掉；沒有任何有效項目 ⇒ 不刪帳本的簡短通知（否則誰都沒被通知）
        if _items and _notice_mark is not None:     # 設定中心的通知（commit 後發）取代帳本對高風險變更的簡短通知（同一件事不發兩則）：同交易內刪掉剛寫的那幾列
            c.execute("DELETE FROM notifications WHERE id>? AND type='config_change' AND ref_label LIKE 'setting:%'", (_notice_mark,))
        c.commit()
        invalidate(group)
        _SN.emit(_items)                            # commit 之後、不在任何鎖內；永不丟例外
        return result
    except Exception:
        if began and c.in_transaction:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def materialize_due(conn=None, now=None):
    """把已到時的待生效值寫進定義版本並標 activated（每日工作呼叫；漏跑也不影響效力——讀取時本來就套用到時的待生效值）。回處理的明細列數。
    通知只在**本函式自己 commit 之後**發（自己開連線，或 `begin_write` 由本函式開了交易）；呼叫端傳入的連線已在自己的交易裡（`began` 為 False、由呼叫端稍後 commit）⇒ **不發通知**
    （commit 之前發會通知到還沒落盤的變更；呼叫端要通知請在自己 commit 之後 `settings_notify.emit()`）。每日工作走自己的連線，不受影響。"""
    from datetime import datetime
    from core.txn import begin_write
    from helpers import config_ledger as L
    from helpers import settings_notify as _SN
    now = now or datetime.now().isoformat(timespec="seconds")
    own = conn is None
    c = conn if conn is not None else get_db()
    began, total, failed = False, 0, []
    _items = []                                     # 到期生效的通知項目（commit 之後合併成一則發）
    try:
        began = begin_write(c)
        for group in list(_GROUPS):
            if group_status(group) != "open":
                for r in L.pending(c, "setting:%s" % group):
                    if r["domain"] == "setting:%s" % group:
                        L.cancel(c, r["id"], "system", "功能改為開發中／隱藏，待生效項自動撤銷")
                continue
            due = _due_pending(c, group, now)
            if not due:
                continue
            sp = "mat_%d" % (len(failed) + total + 1)
            c.execute("SAVEPOINT " + sp)                 # 每個群組各一個：轉接器寫入失敗只影響這一群組（SPEC §15.A.5-2）
            loc = []                                     # 這個群組的通知項目：savepoint 成功釋放才併入（失敗回復就丟掉，不通知沒生效的變更）
            try:
                total += _materialize_group(c, group, due, now, loc)
                c.execute("RELEASE " + sp)
                _items += loc
            except Exception as e:                       # noqa: BLE001
                c.execute("ROLLBACK TO " + sp)           # 連同剛寫的定義列一併撤銷：定義列與舊鍵不得分歧
                c.execute("RELEASE " + sp)
                logger.error("settings: 群組 %s 的待生效值寫入失敗，已取消該群組到期的待生效項：%s", group, e, exc_info=True)
                for r in due:
                    L.cancel(c, r["id"], "system", "到期寫入失敗，自動取消（%s）" % str(e)[:80])
                failed.append((group, str(e)[:120]))
                invalidate(group)
        if began or own:
            c.commit()
            _SN.emit(_items)                              # 外層 commit 之後、不在鎖內；永不丟例外
        for group, why in failed:                         # 外層 commit 之後才通知最高管理者（取消與通知各自可失敗，不拖垮每日工作）
            _notify_materialize_failure(group, why)
        return total
    except Exception:
        if began and c.in_transaction:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def _notify_materialize_failure(group, why):
    try:
        from helpers import config_ledger as L
        from datetime import datetime
        conn = get_db()
        try:
            L._notify_others(conn, "", "setting:%s" % group, group, "money", "settings-center.html", datetime.now().isoformat(timespec="seconds"),
                             "設定「%s」到期要生效時寫入失敗，已取消這次待生效的變更，請重新申請：%s" % (_g(group)["label"], why))
            conn.commit()
        finally:
            conn.close()
    except Exception:                               # noqa: BLE001
        logger.warning("settings: 通知待生效寫入失敗時出錯（群組 %s）", group, exc_info=True)


def _materialize_group(c, group, due, now, items=None):
    """把一個群組到期的待生效值寫進定義版本＋舊儲存並標 activated；回處理的明細列數。丟例外 ⇒ 呼叫端回復這個群組的 savepoint。
    `items`（選填 list）：把「已生效」的通知項目放進去（`settings_notify.setting_item(..., "activated")`）；由呼叫端在 savepoint 成功後才取用。"""
    from helpers import config_ledger as L
    base = _effective(c, group, overlay=False)
    new = dict(base)
    for r in list(due):
        if validate_values(group, {r["field"]: r["new"]}, partial=True, conn=c):
            logger.warning("settings: 待生效項 #%s（%s.%s=%r）超出目前的欄位範圍或版本邊界，自動撤銷", r["id"], group, r["field"], r["new"])
            L.cancel(c, r["id"], "system", "超出目前的欄位範圍或版本邊界，到期時自動撤銷")
            due.remove(r)
            continue
        new[r["field"]] = r["new"]
    if not due:
        return 0
    out = D.publish_direct(c, KIND, group, SCOPE, {"group": group, "values": new}, "待生效項到期生效", "system", commit=False)
    _write_legacy(c, group, new, old=base)
    n = len(L.promote_due(c, now, domain="setting:%s" % group))
    if items is not None:
        from helpers import settings_notify as _SN
        items += [_SN.setting_item(group, r["field"], r["old"], r["new"], "activated", reason=r.get("reason") or "") for r in due]
    invalidate(group)
    logger.info("settings: 群組 %s 的 %d 項待生效值已生效（定義 v%s）", group, len(due), out["version"])
    return n


# --- 預設組（政策設定檔；販售時依客戶／版本套用，走同一條 publish 管制）-------------

def profiles():
    """所有欄位 `presets` 裡出現過的預設組名稱 → 涵蓋的欄位數。"""
    out = {}
    for gk, g in list(_GROUPS.items()):
        if group_status(gk) != "open" or g.get("external"):      # 開發中／隱藏／外部的群組不算在預設組裡（外部群組只能走原頁面）
            continue
        for f in g["fields"].values():
            for name in f.presets:
                out[name] = out.get(name, 0) + 1
    return out


def profile_skipped(name):
    """預設組裡因功能狀態被略過的群組：`[{group, groupLabel, status, reason}]`（畫面／API 回報『略過 N 項』，不得說成全部套用）。"""
    out = []
    for gk, g in list(_GROUPS.items()):
        st = group_status(gk)
        if st == "open" or g.get("external"):
            continue
        n = sum(1 for f in g["fields"].values() if name in f.presets)
        if n:
            out.append({"group": gk, "groupLabel": g["label"], "status": st, "fields": n,
                        "reason": "開發中" if st == "planned" else "隱藏"})
    return out


def profile_preview(name, *, conn=None):
    """套用預設組會改哪些欄位（目前值 → 新值）；不寫入。"""
    out = []
    for gk, g in list(_GROUPS.items()):
        if group_status(gk) != "open" or g.get("external"):
            continue
        cur = get_group(gk, conn=conn)
        for k, f in g["fields"].items():
            if name in f.presets and cur[k] != f.presets[name]:
                out.append({"group": gk, "groupLabel": g["label"], "field": k, "label": f.label, "old": cur[k], "new": f.presets[name], "unit": f.unit})
    return out


def apply_profile(name, *, reason="", user="", ip="", conn=None, actor=None):
    """套用預設組：每個群組各走一次 `publish()`（放寬照樣需要雙人核准／24 小時）。回 `{群組: publish 結果}`。"""
    if name not in profiles():
        raise SettingError("沒有這個預設組：%s" % name)
    from helpers import settings_notify as _SN
    by_group = {}
    for ch in profile_preview(name, conn=conn):
        by_group.setdefault(ch["group"], {})[ch["field"]] = ch["new"]
    with _SN.batch():                               # 跨多個群組的各次 publish 只發**一則**通知
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


def _spine_check_settings(feat):
    """脊柱驗證器：功能宣告的設定群組必須已登錄、擁有者相符；**新群組**的 money／legal／security 欄位必須有 impact_scope；選項欄位用整數代碼。"""
    g = (feat.get("settings") or {}).get("group")
    if not g:
        return []
    meta = _GROUPS.get(g)
    if meta is None:
        return ["設定群組 %s 沒有登錄（register_group）" % g]
    out = []
    if meta["owner"] != feat["owner"]:
        out.append("設定群組 %s 的擁有者是 %s，不是本功能所屬的模組 %s" % (g, meta["owner"], feat["owner"]))
    for f in meta["fields"].values():
        if RISK_ORDER.index(f.risk) >= RISK_ORDER.index("money") and f.impact_scope is None and g not in IMPACT_SCOPE_GRANDFATHERED:
            out.append("%s.%s 風險 %s，新登錄的設定必須宣告 impact_scope" % (g, f.key, f.risk))
        if f.choices and f.type != "int":
            out.append("%s.%s 是選項欄位，必須用整數代碼（int）" % (g, f.key))
    return out


def _register_once():
    _reg.on_unload(unregister_owner)                 # 模組失敗／卸載 ⇒ 它登記的群組一併移除（不留孤兒）
    _reg.register_owned("settings", owner_groups)    # 載入器用它核對 module.json 的 settings.groups 宣告
    _spine.register_validator("settings", _spine_check_settings, covers=("settings",))   # features[].settings.group 的跨表檢查
    _spine.on_validated(cancel_pending_of_nonopen)   # 脊柱驗證完 ⇒ 取消非 open 群組的待生效項
    _spine.on_validated(audit_spine_failures)        # 脊柱驗證完 ⇒ 驗證失敗的功能寫稽核（去重）
    _spine.register_kind_gate(KIND, group_info)      # 通用定義路由對 setting_group 的 hidden／planned 閘門
    _spine.register_managed_kind(KIND, "設定要到「系統 > 設定中心」調整：放寬類的變更需要第二位最高管理者核准，並會留下變更明細；這裡不提供直接修改。")
    if KIND not in D.kinds():
        D.register_kind(KIND, label="設定群組", validator=_kind_validator, default=_kind_default)
    from helpers import config_ledger as L
    L.register_domain("setting", snapshot_fn=_snapshot, restore_fn=_restore, label="設定中心")


_register_once()
