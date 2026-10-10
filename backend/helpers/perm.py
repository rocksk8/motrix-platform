# -*- coding: utf-8 -*-
"""權限矩陣的中央檢查（框架 P0；設計 docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md §2–§3、§8）。

[單位] helper:perm    [層] L1    [穩定度] 實作（P0：框架與純計算；矩陣資料來自 permissions 模組的提供者，缺席時用種子）
[公開介面] Matrix, Delegation, load_user, base_can, can, can_via, acting_as, require, effective_caps, seed_from_legacy, compute, set_matrix_source, matrix, invalidate, explain
[不變式] ① **superadmin 永遠通過**（第一行直通，不看矩陣、不被覆寫扣掉）
         ② 計算順序固定（pure `compute`）：個人禁止 → 個人允許（僅可委派者）→ 角色格（種子＋矩陣編輯）→ 模組鍵展開（`user_has_module`）；沒有任何一項為真 ⇒ 否
            禁止永遠優先於允許
         ③ **預設等價**：矩陣來源缺席時用 `seed_from_legacy(all_caps())`——由各能力的 `legacy` 宣告推導，與今天的判斷逐字相同（關卡 A：tests/platform/test_perm_equivalence_gate_a.py）
         ④ 不可委派的能力（`delegable: false`）忽略個人允許與代理；它的角色格與模組展開只來自 legacy 種子
         ⑤ 能力不存在 ⇒ 否（superadmin 例外，仍直通並記 log）；檢查失敗一律 fail-closed
         ⑥ **代理**（IP-PM1）：基礎來源都沒有時，看有效代理——範圍內的能力、且**委派人自己目前就有**（不能憑代理升權）、可委派、不被個人禁止；不可再轉代理；
            只靠代理通過時 `acting_as()` 回委派人（稽核／通知／單據簽核紀錄用「X 代 Y」）
         ⑦ 本檔不寫死任何角色清單、能力清單或預設勾選（使用者 2026-10-10 核心規則）：角色名稱取自 `helpers.auth.VALID_ROLES`，能力取自 `core.capabilities`，矩陣內容由 superadmin 在頁面填
[契約題] tests/platform/test_perm_equivalence_gate_a.py
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, FrozenSet, Optional, Tuple

from fastapi import HTTPException

from core import capabilities as _cap
from helpers import auth as _auth

logger = logging.getLogger(__name__)

_cap.configure(valid_roles=_auth.VALID_ROLES)           # 角色名稱的唯一來源是 auth.VALID_ROLES


@dataclass(frozen=True)
class Delegation:
    """一筆有效代理（只含 `scope_kind` 為 caps／doc_types 者；`approval_slot` 由簽核層的代理讀點處理，不進能力計算）。"""
    id: int
    delegator: str
    delegate: str
    scope_kind: str                                 # caps | doc_types
    caps: FrozenSet[str] = frozenset()
    doc_types: FrozenSet[str] = frozenset()         # "<單位>.<物件>"
    valid_from: str = ""                            # YYYY-MM-DD，空＝不限
    valid_to: str = ""


@dataclass
class Matrix:
    """矩陣內容：`role_grants`＝{角色: {能力鍵}}；`allow`／`deny`＝{user_id: {能力鍵}}（個人覆寫）；`delegations`＝{被代理人（delegate）帳號: (代理…)}。"""
    role_grants: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    allow: Dict[int, FrozenSet[str]] = field(default_factory=dict)
    deny: Dict[int, FrozenSet[str]] = field(default_factory=dict)
    delegations: Dict[str, Tuple[Delegation, ...]] = field(default_factory=dict)


def seed_from_legacy(caps: Optional[Dict[str, "_cap.Capability"]] = None) -> Matrix:
    """預設矩陣：每個能力的 legacy 角色葉子 ⇒ 該角色有此能力。沒有任何個人覆寫、沒有代理。純函式、冪等。"""
    caps = _cap.all_caps() if caps is None else caps
    grants: Dict[str, set] = {}
    for c in caps.values():
        for r in c.roles:
            grants.setdefault(r, set()).add(c.key)
    return Matrix(role_grants={r: frozenset(v) for r, v in grants.items()})


def compute(role: str, uid, has_module: Callable[[str], bool], cap: "_cap.Capability", m: Matrix) -> bool:
    """單一能力的基礎判斷（純函式；不含 superadmin 直通、能力不存在與代理，那些在 `can`）。"""
    if cap.key in m.deny.get(uid, ()):
        return False
    if cap.delegable and cap.key in m.allow.get(uid, ()):
        return True
    if cap.key in m.role_grants.get(role, ()):
        return True
    return any(has_module(k) for k in sorted(cap.modules))


# ── 矩陣來源（優先序：測試注入 → 提供者 `perm.matrix_source`（permissions 模組，資料表）→ 種子）──────────────────
_source: Optional[Callable[[], Matrix]] = None
_seed_cache = {"key": None, "m": None}
_prov_cache = {"at": -1e9, "m": None, "sig": None}
_PROV_TTL = 3.0                                    # 秒；寫入端呼叫 `invalidate()` 立即失效（同程序）


def set_matrix_source(fn: Optional[Callable[[], Matrix]]) -> None:
    global _source
    _source = fn
    invalidate()


def invalidate() -> None:
    _prov_cache.update(at=-1e9, m=None)


def _provider():
    from core import registry
    return registry.single_provider("perm.matrix_source")


def matrix() -> Matrix:
    if _source is not None:
        return _source()
    sig = _cap.signature()
    prov = _provider()
    if prov is not None:
        now = time.monotonic()
        if _prov_cache["m"] is not None and _prov_cache["sig"] == sig and now - _prov_cache["at"] < _PROV_TTL:
            return _prov_cache["m"]
        try:
            m = prov(seed_from_legacy(_cap.all_caps()))
            _prov_cache.update(at=now, m=m, sig=sig)
            return m
        except Exception:                           # noqa: BLE001 — 讀不到資料表 ⇒ 退回種子（= 今天的行為），不因此多給或少給
            logger.exception("perm.matrix_source failed; falling back to the legacy seed")
    if _seed_cache["key"] != sig:
        _seed_cache.update(key=sig, m=seed_from_legacy(_cap.all_caps()))
    return _seed_cache["m"]


def _today() -> str:
    return date.today().isoformat()


def load_user(username: str) -> Optional[dict]:
    """委派人的使用者 dict（含職責角色套用後的模組勾選；與 `_require_user` 同一條路）。找不到／停用 ⇒ None。"""
    try:
        from db import get_db
        from helpers import duty_roles as _dr
        c = get_db()
        try:
            r = c.execute("SELECT id, username, display_name, role, modules FROM users WHERE username=? AND active=1", (username,)).fetchone()
            if r is None:
                return None
            u = dict(r)
            if u["role"] != "superadmin":
                try:
                    raw = json.loads(u["modules"] or "[]")
                except (TypeError, ValueError):
                    raw = None
                if isinstance(raw, list):
                    res = _dr.resolve_raw_modules(c, u["id"], raw)
                    if res is not raw:
                        u["modules"] = json.dumps(res, ensure_ascii=False)
            return u
        finally:
            c.close()
    except Exception:                               # noqa: BLE001
        logger.exception("perm.load_user(%s) failed", username)
        return None


def _in_window(d: Delegation, today: str) -> bool:
    return (not d.valid_from or d.valid_from <= today) and (not d.valid_to or today <= d.valid_to)


def _scope_hit(d: Delegation, cap: "_cap.Capability") -> bool:
    return cap.key in d.caps or ("%s.%s" % (cap.unit, cap.obj)) in d.doc_types


def base_can(user: dict, cap: "_cap.Capability", m: Matrix) -> bool:
    if user.get("role") == "superadmin":
        return True
    return compute(user.get("role"), user.get("id"), lambda k: _auth.user_has_module(user, k), cap, m)


def _via_delegation(user: dict, cap: "_cap.Capability", m: Matrix) -> Optional[str]:
    """沒有基礎權限時：回提供這項能力的第一位委派人帳號；沒有 ⇒ None。"""
    if not cap.delegable or cap.key in m.deny.get(user.get("id"), ()):
        return None
    today = _today()
    for d in m.delegations.get(user.get("username"), ()):
        if not _in_window(d, today) or not _scope_hit(d, cap):
            continue
        delegator = load_user(d.delegator)
        if delegator is not None and base_can(delegator, cap, m):          # 委派人自己要有；代理不可再轉（只看他的基礎權限）
            return d.delegator
    return None


def can(user: Optional[dict], key: str) -> bool:
    """這個人能不能做這件事。`user` 是 `_require_user` 回傳的 dict（要有 role；要個人覆寫／模組勾選／代理時要有 id、username、modules）。"""
    if not user:
        return False
    role = user.get("role")
    cap = _cap.get(key)
    if role == "superadmin":                                       # 不變式 ①
        if cap is None:
            logger.warning("perm.can: unknown capability %r (allowed for superadmin)", key)
        return True
    if cap is None:
        logger.warning("perm.can: unknown capability %r (denied)", key)
        return False
    try:
        m = matrix()
        if base_can(user, cap, m):
            return True
        return _via_delegation(user, cap, m) is not None
    except Exception:                                              # noqa: BLE001 — fail-closed
        logger.exception("perm.can failed for %s; denying", key)
        return False


def can_via(user: Optional[dict], key: str) -> Tuple[bool, str, str]:
    """(通過?, 來源, 委派人)。來源 ∈ superadmin／base／delegation／none／unknown；委派人僅 delegation 時有值。"""
    if not user:
        return False, "none", ""
    if user.get("role") == "superadmin":
        return True, "superadmin", ""
    cap = _cap.get(key)
    if cap is None:
        return False, "unknown", ""
    try:
        m = matrix()
        if base_can(user, cap, m):
            return True, "base", ""
        who = _via_delegation(user, cap, m)
        return (True, "delegation", who) if who else (False, "none", "")
    except Exception:                                              # noqa: BLE001
        logger.exception("perm.can_via failed for %s; denying", key)
        return False, "none", ""


def acting_as(user: Optional[dict], key: str) -> str:
    """這次是否**只靠代理**才通過、代誰（帳號）；自己的基礎權限足夠 ⇒ 空字串。稽核／通知／簽核紀錄用「X 代 Y」。"""
    ok, via, who = can_via(user, key)
    return who if ok and via == "delegation" else ""


def require(user: Optional[dict], key: str) -> None:
    """不能 ⇒ 403，訊息帶缺少的能力（可稽核、可對照權限頁）。"""
    if not can(user, key):
        cap = _cap.get(key)
        raise HTTPException(403, "權限不足：需要「%s」（%s）" % (cap.label if cap else key, key))


def effective_caps(user: Optional[dict]) -> FrozenSet[str]:
    """這個人目前有哪些能力（頁面的生效預覽、登入 payload 給前端用）。"""
    if not user:
        return frozenset()
    return frozenset(k for k in _cap.all_caps() if can(user, k))


def explain(user: dict, key: str) -> Dict[str, object]:
    """為什麼有／沒有這項能力（權限頁「來源」欄）：回 {allowed, via}，via ∈ superadmin／deny／allow／role／module／delegation／none／unknown。"""
    cap = _cap.get(key)
    if (user or {}).get("role") == "superadmin":
        return {"allowed": True, "via": "superadmin"}
    if cap is None:
        return {"allowed": False, "via": "unknown"}
    m, uid, role = matrix(), user.get("id"), user.get("role")
    if key in m.deny.get(uid, ()):
        return {"allowed": False, "via": "deny"}
    if cap.delegable and key in m.allow.get(uid, ()):
        return {"allowed": True, "via": "allow"}
    if key in m.role_grants.get(role, ()):
        return {"allowed": True, "via": "role"}
    for k in sorted(cap.modules):
        if _auth.user_has_module(user, k):
            return {"allowed": True, "via": "module", "module": k}
    who = _via_delegation(user, cap, m)
    if who:
        return {"allowed": True, "via": "delegation", "delegator": who}
    return {"allowed": False, "via": "none"}
