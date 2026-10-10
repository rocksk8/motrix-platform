# -*- coding: utf-8 -*-
"""能力登錄（權限矩陣框架 P0；設計 docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md §2）。

[單位] plat:capabilities    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ACTIONS, HIGH_RISK_ACTIONS, RISKS, KEY_RE, configure, problems, signature, Capability, CapabilityError, parse_legacy, parse_decl, collect, all_caps, get, reset_cache
[不變式] ① 能力只由模組在 `module.json` 的 `capabilities` 宣告（加法）；本檔不寫死任何業務能力清單——寫死的那一份就是第二個來源
         ② 能力鍵＝`<單位>.<物件>.<動作>`，第一段必須等於宣告它的模組鍵；動作只能是固定詞彙 `ACTIONS`
         ③ 每個能力必須帶 `legacy`：今天的判斷式（小型 DSL：role／module／any）。種子（預設矩陣）與等價關卡都從它推導 ⇒ 上線當天零行為變更
         ④ 高風險動作（`HIGH_RISK_ACTIONS`）的 `risk` 一律至少 `high`（宣告得再低也會被拉高）
         ⑤ 模組缺席 ⇒ 它的能力不存在（不是錯誤）；壞掉的宣告只回報問題、不讓載入失敗
[契約題] tests/platform/test_capabilities_registry.py、tests/platform/test_perm_equivalence_gate_a.py

## `legacy` DSL（只有三種葉子與一種組合）
  {"superadmin": true}          只有最高管理者（沒有任何角色／模組葉子；矩陣可另外授予）
  {"role": ["admin", "finance"]}  角色在清單內
  {"module": "payslip"}         持有該模組鍵（`helpers.auth.user_has_module`：勾選＋職責角色＋財務三鍵規則）
  {"any": [葉子, …]}            任一為真
superadmin 在任何情況下都通過（不必寫在 legacy 裡）。
"""
import re
import threading
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

#: 固定動作詞彙（使用者 2026-10-10 裁示：再細分；匯出獨立一格）。單位專屬動作需另行升版此清單。
ACTIONS = ("view", "view_money", "view_sensitive", "create", "edit", "submit", "withdraw", "approve", "reject", "void",
           "pay", "delete", "export", "print", "attach", "comment", "reassign", "config")
#: 使用者裁示的高風險（view_money／approve／pay／delete）＋設計稿建議（view_sensitive、config）：授予要走 24 小時待生效。
HIGH_RISK_ACTIONS = ("view_money", "view_sensitive", "approve", "pay", "delete", "config")
RISKS = ("low", "mid", "high")
#: 角色清單**不在這裡寫死**（使用者 2026-10-10 核心規則：不新增寫死清單）：由 `helpers.perm` 載入時 `configure(valid_roles=auth.VALID_ROLES)` 交進來；
#: 沒設定時只檢查型別（不認得的角色名稱在 helpers.perm 載入後的下一次登錄重算時才會被擋）。
_VALID_ROLES = None


def configure(valid_roles=None) -> None:
    global _VALID_ROLES
    _VALID_ROLES = tuple(valid_roles) if valid_roles else None
    reset_cache()

KEY_RE = re.compile(r"^([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\.([a-z_]+)$")


class CapabilityError(ValueError):
    """能力宣告不合法（訊息可直接給人看）。"""


@dataclass(frozen=True)
class Capability:
    key: str
    unit: str
    obj: str
    action: str
    label: str
    risk: str
    delegable: bool
    reserved: bool                      # 已登錄但還沒有任何端點使用（頁面標「尚未生效」之外再標「保留」）
    roles: FrozenSet[str]               # legacy 的角色葉子（種子據此給角色）
    modules: FrozenSet[str]             # legacy 的模組葉子（以 user_has_module 展開，不進角色種子）
    legacy: Tuple                       # 正規化後的 DSL（供等價關卡與頁面顯示）


def parse_legacy(node, valid_roles=None) -> Tuple[FrozenSet[str], FrozenSet[str], Tuple]:
    """DSL → (角色葉子集合, 模組葉子集合, 正規化樹)。不合法 ⇒ CapabilityError。"""
    if not isinstance(node, dict) or len(node) != 1:
        raise CapabilityError("legacy 必須是只有一個鍵的物件：%r" % (node,))
    (kind, val), = node.items()
    if kind == "superadmin":
        if val is not True:
            raise CapabilityError("legacy.superadmin 只能是 true")
        return frozenset(), frozenset(), ("superadmin",)
    if kind == "role":
        if not isinstance(val, list) or not val:
            raise CapabilityError("legacy.role 必須是非空清單")
        valid_roles = valid_roles or _VALID_ROLES
        bad = [r for r in val if not isinstance(r, str) or (valid_roles is not None and r not in valid_roles)]
        if bad:
            raise CapabilityError("legacy.role 有不認得的角色：%s" % ",".join(map(str, bad)))
        return frozenset(val) - {"superadmin"}, frozenset(), ("role", tuple(sorted(set(val))))
    if kind == "module":
        if not isinstance(val, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", val):
            raise CapabilityError("legacy.module 必須是模組鍵字串")
        return frozenset(), frozenset([val]), ("module", val)
    if kind == "any":
        if not isinstance(val, list) or not val:
            raise CapabilityError("legacy.any 必須是非空清單")
        roles, mods, kids = set(), set(), []
        for kid in val:
            r, m, t = parse_legacy(kid, valid_roles)
            roles |= r
            mods |= m
            kids.append(t)
        return frozenset(roles), frozenset(mods), ("any", tuple(kids))
    raise CapabilityError("legacy 不認得的種類：%s（只有 superadmin／role／module／any）" % kind)


def parse_decl(unit: str, decl: dict, valid_roles=None) -> Capability:
    if not isinstance(decl, dict):
        raise CapabilityError("%s：能力宣告必須是物件" % unit)
    key = str(decl.get("key") or "")
    m = KEY_RE.match(key)
    if not m:
        raise CapabilityError("%s：能力鍵格式應為 <單位>.<物件>.<動作>：%r" % (unit, key))
    if m.group(1) != unit:
        raise CapabilityError("%s：能力鍵 %s 的第一段必須是宣告它的模組鍵" % (unit, key))
    if m.group(3) not in ACTIONS:
        raise CapabilityError("%s：動作「%s」不在固定詞彙內（%s）" % (key, m.group(3), "、".join(ACTIONS)))
    label = str(decl.get("label") or "").strip()
    if not label:
        raise CapabilityError("%s：缺 label" % key)
    risk = decl.get("risk", "low")
    if risk not in RISKS:
        raise CapabilityError("%s：risk 只能是 %s" % (key, "/".join(RISKS)))
    if m.group(3) in HIGH_RISK_ACTIONS:
        risk = "high"                                   # 宣告得再低也拉高（不變式 ④）
    if "legacy" not in decl:
        raise CapabilityError("%s：缺 legacy（今天的判斷式；沒有它就無法證明預設等價）" % key)
    roles, mods, tree = parse_legacy(decl["legacy"], valid_roles)
    return Capability(key=key, unit=unit, obj=m.group(2), action=m.group(3), label=label, risk=risk,
                      delegable=bool(decl.get("delegable", True)), reserved=bool(decl.get("reserved", False)),
                      roles=roles, modules=mods, legacy=tree)


def collect(manifests: Dict[str, dict], valid_roles=None) -> Tuple[Dict[str, Capability], List[str]]:
    """{模組鍵: module.json 內容} → ({能力鍵: Capability}, [問題])。純函式；壞宣告只進問題清單，不丟例外。"""
    caps: Dict[str, Capability] = {}
    problems: List[str] = []
    for unit in sorted(manifests):
        decls = (manifests[unit] or {}).get("capabilities") or []
        if not isinstance(decls, list):
            problems.append("%s：capabilities 必須是清單" % unit)
            continue
        for d in decls:
            try:
                c = parse_decl(unit, d, valid_roles)
            except CapabilityError as e:
                problems.append(str(e))
                continue
            if c.key in caps:
                problems.append("%s：能力鍵重複" % c.key)
                continue
            caps[c.key] = c
    return caps, problems


# ── 目前已載入模組的登錄（快取；模組載入／卸載後 reset_cache）──────────────────────────────
_lock = threading.Lock()
_cache = {"sig": None, "caps": {}, "problems": []}


def _manifests() -> Dict[str, dict]:
    from core import registry
    return {lm.key: lm.manifest for lm in registry.loaded()}


def all_caps() -> Dict[str, Capability]:
    """已載入模組宣告的全部能力。簽名＝（模組鍵、版本）；載入集合變了就重算。"""
    man = _manifests()
    sig = tuple(sorted((k, str((m or {}).get("version") or "")) for k, m in man.items()))
    with _lock:
        if _cache["sig"] != sig:
            caps, problems = collect(man)
            _cache.update(sig=sig, caps=caps, problems=problems)
        return dict(_cache["caps"])


def problems() -> List[str]:
    all_caps()
    with _lock:
        return list(_cache["problems"])


def signature():
    """目前登錄的簽名（載入集合變了就變）；下游快取用。"""
    all_caps()
    with _lock:
        return _cache["sig"]


def get(key: str):
    return all_caps().get(key)


def reset_cache() -> None:
    with _lock:
        _cache.update(sig=None, caps={}, problems=[])
