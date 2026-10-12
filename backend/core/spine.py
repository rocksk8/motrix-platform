# -*- coding: utf-8 -*-
"""L0 脊柱功能登錄（E-b；設計 docs/platform/plans/SPINE-ENGINE-DESIGN-T57.md、FIELD-LAYOUT-FRAMEWORK-T56.md §17）。

[單位] plat:spine    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] STATUSES, drop_owner, feature_enabled, feature_status, group_status, on_validated, parse_feature, parse_features, planned_train,
    register_manifest, register_validator, report, reset, restore, snapshot, validate_all
[不變式] ①只用標準函式庫（載入器在 import 模組之前要驗宣告）；依賴 L1 的驗證（設定、信件…）以**回呼**注入——`register_validator`／`on_validated`，
    L0 不 import L1。②宣告式：功能寫在 `module.json` 的 `features[]`，靜態可掃。③**fail-closed 的方向**：驗證失敗的功能 `feature_enabled`＝False、
    其設定群組視為 `hidden`（不顯示、不可寫）；但**脊柱本身壞掉或尚未初始化一律當 open**（未宣告＝open、`validate_all()` 之前＝open），不拖垮既有行為。
    ④`status`（open／planned／hidden）是**宣告的成熟度**，與驗證結果 `state`（ok／failed／pending_validator）分開。
[契約題] backend/tests/platform/test_spine_e_b.py
"""
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from core import registry

_log = logging.getLogger("motrix.spine")

STATUSES = ("open", "planned", "hidden")
STATE_OK, STATE_FAILED, STATE_PENDING = "ok", "failed", "pending_validator"

_CODE = re.compile(r"^[a-z][a-z0-9_]*$")
_TRAIN = re.compile(r"^MS[1-9][0-9]?$")
_CAP = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")
_FEATURE_KEYS = {"code", "label", "settings", "mail", "catalog", "capabilities", "labels", "status", "planned_train", "notes"}
_DATE_KEYS = {"date", "eta", "deadline", "planned_date", "due", "release_date", "release"}
#: planned 功能的 label／notes 不得出現看起來像日期或時程的文字（使用者要求不承諾日期）
_DATEISH = re.compile(r"\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*[/月]\s*\d{1,2}|(\d+|[一二兩三四五六七八九十百]+)\s*(天|週|周|日|個月|月|年)|[Qq][1-4]|下\s*(週|周|個月)|本月|月底|年底|週內|周內")
_SECTIONS_NEEDING_VALIDATOR = ("catalog", "labels")      # P0 目錄落地前沒有驗證器：宣告了只記 pending_validator，不算失敗

_FEATURES: Dict[str, dict] = {}
_ORPHANS: Dict[str, List[str]] = {}                       # 擁有者 → 無法歸到任何功能的問題（缺 code、代號重複…）
_STATE: Dict[str, dict] = {}
_MANIFEST_CAPS: Dict[str, set] = {}
_VALIDATORS: Dict[str, Tuple[Callable, Tuple[str, ...]]] = {}
_POST_VALIDATE: List[Callable[[], None]] = []
_VALIDATED = False


# ── 解析（純函式）────────────────────────────────────────────────────────────────

def _str_list(v, label, pat=None) -> Tuple[list, List[str]]:
    if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
        return [], ["%s 必須是非空字串的清單" % label]
    if pat is not None:
        bad = [x for x in v if not pat.match(x)]
        if bad:
            return [], ["%s 有格式不合的項目：%s" % (label, "、".join(bad))]
    if len(set(v)) != len(v):
        return [], ["%s 有重複項目" % label]
    return list(v), []


def parse_feature(raw, owner: str, index: int = 0) -> Tuple[Optional[dict], List[str]]:
    """單一功能宣告 → (功能 dict | None, 問題清單)。沒有可用的 code ⇒ None（問題掛在擁有者下）。"""
    where = "%s features[%d]" % (owner, index)
    if not isinstance(raw, dict):
        return None, ["%s 必須是物件" % where]
    problems: List[str] = []
    code = raw.get("code")
    if not isinstance(code, str) or not _CODE.match(code):
        return None, ["%s 的 code 必須是小寫英數底線（以字母開頭）" % where]
    where = "%s（%s）" % (where, code)
    unknown = sorted(set(raw) - _FEATURE_KEYS - _DATE_KEYS)
    if unknown:
        problems.append("%s 有不認得的鍵：%s" % (where, "、".join(unknown)))
    dates = sorted(set(raw) & _DATE_KEYS)
    if dates:
        problems.append("%s 不可宣告日期（%s）：只能寫 planned_train，不承諾日期" % (where, "、".join(dates)))
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        problems.append("%s 缺 label（白話名稱）" % where)
        label = ""
    status = raw.get("status", "open")
    if status not in STATUSES:
        problems.append("%s 的 status 只能是 %s" % (where, "／".join(STATUSES)))
        status = "hidden"                                   # fail-closed：不認得的狀態＝不顯示、不可寫（功能本身也會是 failed）
    train = raw.get("planned_train")
    if status == "planned":
        if not isinstance(train, str) or not _TRAIN.match(train):
            problems.append("%s 是 planned，planned_train 必須是 MS1～MS99（例 MS2）" % where)
            train = None
        for k in ("label", "notes"):
            v = raw.get(k)
            if isinstance(v, str) and _DATEISH.search(v):
                problems.append("%s 是 planned，%s 不得出現日期或時程字樣：%r" % (where, k, v))
    elif train is not None:
        problems.append("%s 不是 planned，不可帶 planned_train" % where)
        train = None
    settings = raw.get("settings")
    group = None
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - {"group"} or not isinstance(settings.get("group"), str) or not _CODE.match(settings["group"]):
            problems.append("%s 的 settings 必須是 {\"group\": 群組代號}" % where)
        else:
            group = settings["group"]
    mail, p = _str_list(raw.get("mail", []), "%s 的 mail" % where, _CODE)
    problems += p
    caps, p = _str_list(raw.get("capabilities", []), "%s 的 capabilities" % where, _CAP)
    problems += p
    labels, p = _str_list(raw.get("labels", []), "%s 的 labels" % where)
    problems += p
    catalog = raw.get("catalog")
    cat = None
    if catalog is not None:
        if not isinstance(catalog, dict) or set(catalog) - {"fields", "surfaces"}:
            problems.append("%s 的 catalog 只能有 fields、surfaces" % where)
        else:
            cat = {}
            for k in ("fields", "surfaces"):
                v, p = _str_list(catalog.get(k, []), "%s 的 catalog.%s" % (where, k))
                problems += p
                cat[k] = v
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("%s 的 notes 必須是文字" % where)
        notes = None
    sections = {k for k in ("settings", "mail", "catalog", "capabilities", "labels") if raw.get(k)}
    return {"code": code, "owner": owner, "label": label, "status": status, "planned_train": train, "group": group,
            "settings": {"group": group} if group else None, "mail": mail, "capabilities": caps, "catalog": cat,
            "labels": labels, "notes": notes, "sections": sorted(sections), "problems": problems}, []


def parse_features(manifest: dict, owner: str) -> Tuple[List[dict], List[str]]:
    """`module.json` 的 `features[]` → (功能清單, 擁有者層級問題)。`features` 不是清單 ⇒ ValueError（整個模組不載入，因為認不出功能）。"""
    raw = (manifest or {}).get("features")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise ValueError("module.json features 必須是清單")
    out, orphan = [], []
    for i, r in enumerate(raw):
        f, pr = parse_feature(r, owner, i)
        orphan += pr
        if f is not None:
            out.append(f)
    return out, orphan


# ── 登錄（載入器呼叫）────────────────────────────────────────────────────────────

def register_manifest(manifest: dict, owner: str) -> List[str]:
    """登錄擁有者的 `features[]`（取代該擁有者先前的登錄）。回問題清單（功能層級問題也在內，載入器只記 log）。
    認不出功能的問題（缺 code、代號重複）記在 `_ORPHANS[owner]`；跨擁有者的 code 重複：後登錄者的那一筆不收。"""
    feats, orphan = parse_features(manifest, owner)
    drop_owner(owner)
    _MANIFEST_CAPS[owner] = {c.get("key") for c in ((manifest or {}).get("capabilities") or [])
                             if isinstance(c, dict) and isinstance(c.get("key"), str)}
    problems = list(orphan)
    seen = set()
    for f in feats:
        if f["code"] in seen:
            msg = "%s：功能代號 %s 在同一份宣告裡重複" % (owner, f["code"])
        elif f["code"] in _FEATURES:
            msg = "%s：功能代號 %s 已被 %s 使用" % (owner, f["code"], _FEATURES[f["code"]]["owner"])
        else:
            seen.add(f["code"])
            _FEATURES[f["code"]] = f
            problems += f["problems"]
            continue
        orphan.append(msg)
        problems.append(msg)
    if orphan:
        _ORPHANS[owner] = orphan
    return problems


def drop_owner(owner: str) -> None:
    """擁有者的功能全部移除（模組失敗／卸載／重登錄）。"""
    for code in [c for c, f in _FEATURES.items() if f["owner"] == owner]:
        _FEATURES.pop(code, None)
        _STATE.pop(code, None)
    _ORPHANS.pop(owner, None)
    _MANIFEST_CAPS.pop(owner, None)


def register_validator(name: str, fn: Callable[[dict], List[str]], covers: Tuple[str, ...] = ()) -> None:
    """L1 登記驗證器：`fn(功能 dict) -> [問題字串]`（不適用時回 []）。`covers`＝它負責驗的宣告區段（`catalog`／`labels` 有人負責才不算 pending_validator）。
    同名重複登記須是同一函式。"""
    if name in _VALIDATORS and _VALIDATORS[name][0] is not fn:
        raise ValueError("spine 驗證器 %r 已登記為另一個函式" % name)
    _VALIDATORS[name] = (fn, tuple(covers))


def on_validated(fn: Callable[[], None]) -> None:
    """L1 登記『驗證完成後要做的事』（例：設定登錄表取消非 open 群組的待生效項）。同一函式只登記一次；回呼丟例外只記 log。"""
    if fn not in _POST_VALIDATE:
        _POST_VALIDATE.append(fn)


# ── 驗證 ──────────────────────────────────────────────────────────────────────────

def validate_all() -> dict:
    """載入結束後呼叫一次（可重複呼叫）：算每個功能的 state，之後 `group_status`／`feature_enabled` 才生效。永不丟例外。"""
    global _VALIDATED
    by_group: Dict[str, List[str]] = {}
    for code in sorted(_FEATURES):
        g = _FEATURES[code]["group"]
        if g:
            by_group.setdefault(g, []).append(code)
    covered = {s for _, (_, cov) in _VALIDATORS.items() for s in cov}
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        problems = list(f["problems"])
        g = f["group"]
        if g and by_group.get(g, [code])[0] != code:
            problems.append("設定群組 %s 同時歸屬功能 %s（一個群組只能歸一個功能）" % (g, "、".join(by_group[g])))
        undeclared = [c for c in f["capabilities"] if c not in _MANIFEST_CAPS.get(f["owner"], set())]
        if undeclared:
            problems.append("宣告的能力不在本模組 module.json 的 capabilities：%s" % "、".join(undeclared))
        for name in sorted(_VALIDATORS):
            fn = _VALIDATORS[name][0]
            try:
                problems += list(fn(dict(f)) or [])
            except Exception as e:                                   # noqa: BLE001  驗證器壞掉 ⇒ 該功能視為失敗（不是通過）
                problems.append("驗證器 %s 失敗：%s" % (name, e))
        pending = [s for s in f["sections"] if s in _SECTIONS_NEEDING_VALIDATOR and s not in covered]
        _STATE[code] = {"state": STATE_FAILED if problems else (STATE_PENDING if pending else STATE_OK),
                        "problems": problems, "pending_sections": pending}
    _VALIDATED = True
    for fn in list(_POST_VALIDATE):
        try:
            fn()
        except Exception:                                            # noqa: BLE001
            _log.warning("spine post-validate 回呼 %r 失敗", fn, exc_info=True)
    return report()


# ── 查詢 ──────────────────────────────────────────────────────────────────────────

def _state(code) -> str:
    return (_STATE.get(code) or {}).get("state", STATE_OK)


def feature_status(code: str) -> str:
    """功能的宣告狀態；未宣告 ⇒ open。"""
    f = _FEATURES.get(code)
    return f["status"] if f else "open"


def planned_train(code: str) -> Optional[str]:
    f = _FEATURES.get(code)
    return f["planned_train"] if f and f["status"] == "planned" else None


def feature_enabled(code: str) -> bool:
    """功能的進入點（路由、按鈕、排程、通知寄送）用：未宣告 ⇒ True；`validate_all()` 之前 ⇒ 只看宣告狀態；失敗或非 open ⇒ False。"""
    f = _FEATURES.get(code)
    if f is None:
        return True
    return f["status"] == "open" and (not _VALIDATED or _state(code) != STATE_FAILED)


def group_status(group: str) -> str:
    """設定群組的狀態（由 `features[].settings.group` 對映）。未歸屬任何功能、或 `validate_all()` 尚未執行 ⇒ open（保守維持今天行為）。
    功能驗證失敗 ⇒ hidden（fail-closed：不顯示、不可寫）。"""
    if not _VALIDATED:
        return "open"
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        if f["group"] == group:
            if _state(code) == STATE_FAILED:
                return "hidden"
            return f["status"]
    return "open"


def report() -> dict:
    """`{features: [{code, owner, label, status, plannedTrain, state, problems, pendingSections}], problems: 數量, orphans: {擁有者: [問題]}}`。"""
    feats = []
    n = 0
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        st = _STATE.get(code) or {"state": STATE_OK, "problems": list(f["problems"]), "pending_sections": []}
        if st["state"] == STATE_FAILED:
            n += 1
        feats.append({"code": code, "owner": f["owner"], "label": f["label"], "status": f["status"],
                      "plannedTrain": f["planned_train"] if f["status"] == "planned" else None,
                      "state": st["state"], "problems": list(st["problems"]), "pendingSections": list(st.get("pending_sections") or [])})
    orphans = {o: list(p) for o, p in _ORPHANS.items() if p}
    return {"features": feats, "problems": n + sum(len(p) for p in orphans.values()), "orphans": orphans, "validated": _VALIDATED}


# ── 測試夾具用 ────────────────────────────────────────────────────────────────────

def snapshot() -> tuple:
    return (dict(_FEATURES), {k: list(v) for k, v in _ORPHANS.items()}, {k: dict(v) for k, v in _STATE.items()},
            {k: set(v) for k, v in _MANIFEST_CAPS.items()}, _VALIDATED)


def restore(snap: tuple) -> None:
    global _VALIDATED
    _FEATURES.clear(); _FEATURES.update(snap[0])
    _ORPHANS.clear(); _ORPHANS.update(snap[1])
    _STATE.clear(); _STATE.update(snap[2])
    _MANIFEST_CAPS.clear(); _MANIFEST_CAPS.update(snap[3])
    _VALIDATED = snap[4]


def reset() -> None:
    """測試用：清空功能登錄與驗證狀態（驗證器與回呼是 import 時登記的，不動）。"""
    restore(({}, {}, {}, {}, False))


registry.on_unload(drop_owner)          # 模組失敗／卸載 ⇒ 它的功能一併移除
