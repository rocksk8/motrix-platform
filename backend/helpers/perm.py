# -*- coding: utf-8 -*-
"""權限矩陣的中央檢查（框架 P0；設計 docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md §2–§3）。

[單位] helper:perm    [層] L1    [穩定度] 實作（P0：框架與純計算；矩陣資料表與端點遷移在後續里程碑）
[公開介面] Matrix, can, require, effective_caps, seed_from_legacy, compute, set_matrix_source, matrix, explain
[不變式] ① **superadmin 永遠通過**（第一行直通，不看矩陣、不被覆寫扣掉）
         ② 計算順序固定（pure `compute`）：個人禁止 → 個人允許（僅可委派者）→ 角色格（種子＋矩陣編輯）→ 模組鍵展開（`user_has_module`）；沒有任何一項為真 ⇒ 否
            禁止永遠優先於允許
         ③ **預設等價**：矩陣來源缺席時用 `seed_from_legacy(all_caps())`——由各能力的 `legacy` 宣告推導，與今天的判斷逐字相同（關卡 A：tests/platform/test_perm_equivalence_gate_a.py）
         ④ 不可委派的能力（`delegable: false`）忽略個人允許；它的角色格與模組展開只來自 legacy 種子
         ⑤ 能力不存在 ⇒ 否（superadmin 例外，仍直通並記 log）；檢查失敗一律 fail-closed
         ⑥ 本檔不寫死任何角色清單、能力清單或預設勾選（使用者 2026-10-10 核心規則）：角色名稱取自 `helpers.auth.VALID_ROLES`，能力取自 `core.capabilities`，矩陣內容由 superadmin 在頁面填
[契約題] tests/platform/test_perm_equivalence_gate_a.py
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Iterable, Optional

from fastapi import HTTPException

from core import capabilities as _cap
from helpers import auth as _auth

logger = logging.getLogger(__name__)

_cap.configure(valid_roles=_auth.VALID_ROLES)           # 角色名稱的唯一來源是 auth.VALID_ROLES


@dataclass
class Matrix:
    """矩陣內容：`role_grants`＝{角色: {能力鍵}}；`allow`／`deny`＝{user_id: {能力鍵}}（個人覆寫）。"""
    role_grants: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    allow: Dict[int, FrozenSet[str]] = field(default_factory=dict)
    deny: Dict[int, FrozenSet[str]] = field(default_factory=dict)


def seed_from_legacy(caps: Optional[Dict[str, "_cap.Capability"]] = None) -> Matrix:
    """預設矩陣：每個能力的 legacy 角色葉子 ⇒ 該角色有此能力。沒有任何個人覆寫。純函式、冪等。"""
    caps = _cap.all_caps() if caps is None else caps
    grants: Dict[str, set] = {}
    for c in caps.values():
        for r in c.roles:
            grants.setdefault(r, set()).add(c.key)
    return Matrix(role_grants={r: frozenset(v) for r, v in grants.items()})


def compute(role: str, uid, has_module: Callable[[str], bool], cap: "_cap.Capability", m: Matrix) -> bool:
    """單一能力的判斷（純函式；不含 superadmin 直通與能力不存在，那兩條在 `can`）。"""
    if cap.key in m.deny.get(uid, ()):
        return False
    if cap.delegable and cap.key in m.allow.get(uid, ()):
        return True
    if cap.key in m.role_grants.get(role, ()):
        return True
    return any(has_module(k) for k in sorted(cap.modules))


# ── 矩陣來源（P0：預設＝種子；之後換成資料表來源，介面不變）──────────────────────────────────
_source: Optional[Callable[[], Matrix]] = None
_seed_cache = {"key": None, "m": None}


def set_matrix_source(fn: Optional[Callable[[], Matrix]]) -> None:
    global _source
    _source = fn


def matrix() -> Matrix:
    if _source is not None:
        return _source()
    sig = _cap.signature()
    if _seed_cache["key"] != sig:
        _seed_cache.update(key=sig, m=seed_from_legacy(_cap.all_caps()))
    return _seed_cache["m"]


def can(user: Optional[dict], key: str) -> bool:
    """這個人能不能做這件事。`user` 是 `_require_user` 回傳的 dict（要有 role；要個人覆寫／模組勾選時要有 id、modules）。"""
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
        return compute(role, user.get("id"), lambda k: _auth.user_has_module(user, k), cap, matrix())
    except Exception:                                              # noqa: BLE001 — fail-closed
        logger.exception("perm.can failed for %s; denying", key)
        return False


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
    """為什麼有／沒有這項能力（權限頁「來源」欄）：回 {allowed, via} 其中 via ∈ superadmin／deny／allow／role／module／none／unknown。"""
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
    return {"allowed": False, "via": "none"}
