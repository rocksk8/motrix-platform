# -*- coding: utf-8 -*-
"""L0 脊柱功能登錄（E-b；設計 docs/platform/plans/SPINE-ENGINE-DESIGN-T57.md、FIELD-LAYOUT-FRAMEWORK-T56.md §17）。

[單位] plat:spine    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] CORE_FEATURES_FILE, STATUSES, TONE_ORDER, drop_owner, feature_enabled, feature_status, group_info, group_status, has_kind_gate, health_badge, kind_info, kind_status,
    managed_message, on_validated, parse_feature, parse_features, planned_cards, planned_train, register_core_declarations, register_health_source, register_kind_gate,
    register_manifest, register_managed_kind, register_validator, report, reset, restore, snapshot, surface_status, validate_all
[不變式] ①只用標準函式庫（載入器在 import 模組之前要驗宣告）；依賴 L1 的驗證（設定、信件…）以**回呼**注入——`register_validator`／`on_validated`，
    L0 不 import L1。②宣告式：功能寫在 `module.json` 的 `features[]`，靜態可掃。③**fail-closed 的方向**：驗證失敗的功能 `feature_enabled`＝False、
    其設定群組視為 `hidden`（不顯示、不可寫）；但**脊柱本身壞掉或尚未初始化一律當 open**（未宣告＝open、`validate_all()` 之前＝open），不拖垮既有行為。
    ④`status`（open／planned／hidden）是**宣告的成熟度**，與驗證結果 `state`（ok／failed／pending_validator）分開。
[契約題] backend/tests/platform/test_spine_e_b.py
"""
import json
import logging
import re
import time
from pathlib import Path
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

#: core 沒有 module.json：核心功能宣告放在這支 JSON（owner＝core；格式同 module.json 的 `features[]`）。載入器在 `load_all` 一開始讀它。
CORE_FEATURES_FILE = Path(__file__).with_name("features_l1.json")

_FEATURES: Dict[str, dict] = {}
_ORPHANS: Dict[str, List[str]] = {}                       # 擁有者 → 無法歸到任何功能的問題（缺 code、代號重複…）
_STATE: Dict[str, dict] = {}
_MANIFEST_CAPS: Dict[str, set] = {}
_REJECTED_GROUPS: Dict[str, set] = {}                    # 設定群組 → 宣告被拒（代號撞名輸家）的擁有者們：該群組一律 hidden（輸家不能因為宣告被丟掉就變成可寫的 open）
_CLAIMS: Dict[str, set] = {}                              # 功能代號 → 宣告過它的擁有者們（含沒被收下的）；>1 個擁有者＝兩邊都標失敗，與載入順序無關
_VALIDATORS: Dict[str, Tuple[Callable, Tuple[str, ...]]] = {}
_POST_VALIDATE: List[Callable[[], None]] = []
_GATE_LOGGED: Dict[str, float] = {}                        # kind → 上次記錄閘門失敗的 monotonic 時間（限流）
_KIND_GATES: Dict[str, Callable] = {}                   # 定義 kind → fn(key) -> "open"|"planned"|"hidden"｜{"status","plannedTrain"}
_MANAGED: Dict[str, str] = {}                             # 受管 kind → 白話訊息（通用 draft／publish／restore 一律拒絕）
_HEALTH: Dict[str, Callable] = {}                         # 健康來源 → fn() -> None｜{"text","tone","count"?}
#: 徽章色調的嚴重度（由重到輕）；系統中心合法色調見 core.system_hub.TONES
TONE_ORDER = ("bad", "warn", "plan", "info", "ok")
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
            for s in cat["surfaces"]:                                  # 只能宣告自己擁有的表面：否則模組可替別人的畫面蓋上 planned／hidden（誤導／阻斷）
                if not _surface_owned(s, owner):
                    problems.append("%s 的 catalog.surfaces %r 不屬於擁有者 %s（surface_not_owned；格式須為 %s）" % (
                        where, s, owner, "core:<名稱>" if owner == "core" else "module:%s.<名稱>" % owner))
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("%s 的 notes 必須是文字" % where)
        notes = None
    sections = {k for k in ("settings", "mail", "catalog", "capabilities", "labels") if raw.get(k)}
    return {"code": code, "owner": owner, "label": label, "status": status, "planned_train": train, "group": group,
            "settings": {"group": group} if group else None, "mail": mail, "capabilities": caps, "catalog": cat,
            "labels": labels, "notes": notes, "sections": sorted(sections), "problems": problems}, []


_SURF_NAME = r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*"


def _surface_owned(surface: str, owner: str) -> bool:
    """表面鍵的擁有者必須等於宣告它的功能的擁有者：模組 `module:<owner>.<名稱>`；core `core:<名稱>`（core 保留前綴，模組不可用）。"""
    if owner == "core":
        return re.match(r"^core:" + _SURF_NAME + r"$", surface) is not None
    return re.match(r"^module:" + re.escape(owner) + r"\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$", surface) is not None


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
        _CLAIMS.setdefault(f["code"], set()).add(owner)
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
        if f["group"]:
            _REJECTED_GROUPS.setdefault(f["group"], set()).add(owner)
    if orphan:
        _ORPHANS[owner] = orphan
    return problems


def register_core_declarations(path=None) -> List[str]:
    """讀 `core/features_l1.json`（核心功能宣告，owner＝core）並登錄。檔案不存在 ⇒ 沒有核心宣告（[]）；讀不懂 ⇒ 記成 core 的擁有者層級問題（不丟例外、不擋啟動）。"""
    p = Path(path) if path else CORE_FEATURES_FILE
    if not p.exists():
        drop_owner("core")
        return []
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):                       # 最上層不是物件（[1]、"x"、5、null）⇒ 讀不懂，不是例外
            raise ValueError("最上層必須是物件")
        return register_manifest(manifest, "core")
    except Exception as e:                                       # noqa: BLE001  脊柱的問題永遠不擋開機：任何錯誤都只變成 core 的擁有者層級問題
        drop_owner("core")
        msg = "core 功能宣告檔 %s 讀不懂：%s" % (p.name, e)
        _ORPHANS["core"] = [msg]
        return [msg]


def drop_owner(owner: str) -> None:
    """擁有者的功能全部移除（模組失敗／卸載／重登錄）。"""
    for code in [c for c, f in _FEATURES.items() if f["owner"] == owner]:
        _FEATURES.pop(code, None)
        _STATE.pop(code, None)
    _ORPHANS.pop(owner, None)
    _MANIFEST_CAPS.pop(owner, None)
    for code in list(_CLAIMS):
        _CLAIMS[code].discard(owner)
        if not _CLAIMS[code]:
            del _CLAIMS[code]
    for g in list(_REJECTED_GROUPS):
        _REJECTED_GROUPS[g].discard(owner)
        if not _REJECTED_GROUPS[g]:
            del _REJECTED_GROUPS[g]


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
        claimed = sorted(_CLAIMS.get(code, ()))
        if len(claimed) > 1:                                         # 兩個模組宣告同一個功能代號：兩邊都失敗（誰先載入不影響結果）
            problems.append("功能代號 %s 同時被多個模組宣告：%s" % (code, "、".join(claimed)))
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
    if _REJECTED_GROUPS.get(group):                    # 某個被拒絕的宣告（撞名輸家）指名了這個群組 ⇒ hidden，不論贏家是誰
        return "hidden"
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        if f["group"] == group:
            if _state(code) == STATE_FAILED:
                return "hidden"
            return f["status"]
    return "open"


def group_info(group: str) -> dict:
    """設定群組的功能資訊 `{status, plannedTrain, feature}`（畫面用）：未歸屬／尚未驗證 ⇒ `{status: open, plannedTrain: None, feature: None}`；
    功能驗證失敗 ⇒ status＝hidden。`plannedTrain` 只在 planned 時有值。"""
    st = group_status(group)
    code = None
    for c in sorted(_FEATURES):
        if _FEATURES[c]["group"] == group:
            code = c
            break
    return {"status": st, "plannedTrain": planned_train(code) if (code and st == "planned") else None, "feature": code}


# ── 定義 kind 的功能狀態閘門（通用 /api/definitions 路由用）────────────────────────────

def register_kind_gate(kind: str, fn: Callable) -> None:
    """L1 登記：某個定義 kind（例：`setting_group`、`alert_rule`）的每個 key 現在是什麼功能狀態。`fn(key)` 回 `open｜planned｜hidden`
    或 `{"status", "plannedTrain"}`。通用定義路由據此：hidden ⇒ 404、planned ⇒ 409（清單只留名稱與狀態）。同 kind 重複登記須是同一函式。"""
    if not isinstance(kind, str) or not _CODE.match(kind):
        raise ValueError("kind 必須是小寫英數底線：%r" % (kind,))
    if kind in _KIND_GATES and _KIND_GATES[kind] is not fn:
        raise ValueError("kind 閘門 %r 已登記為另一個函式" % kind)
    _KIND_GATES[kind] = fn


def has_kind_gate(kind: str) -> bool:
    return kind in _KIND_GATES


def kind_info(kind: str, key: str) -> dict:
    """`{status, plannedTrain}`。沒有登記閘門 ⇒ open。**閘門函式丟例外或回傳不合法的值 ⇒ hidden（fail-closed：這個閘門專門用來防洩漏）**。"""
    fn = _KIND_GATES.get(kind)
    if fn is None:
        return {"status": "open", "plannedTrain": None}
    try:
        r = fn(key)
    except Exception:                                                  # noqa: BLE001
        now = time.monotonic()
        if now - _GATE_LOGGED.get(kind, -1e9) >= 60:                   # 每個 kind 每分鐘最多記一次（列表路由每個 key 都會呼叫）
            _GATE_LOGGED[kind] = now
            _log.warning("kind 閘門 %s 對 %r 失敗，視為 hidden", kind, key, exc_info=True)
        return {"status": "hidden", "plannedTrain": None}
    st = r.get("status") if isinstance(r, dict) else r
    if st not in STATUSES:
        return {"status": "hidden", "plannedTrain": None}
    train = r.get("plannedTrain") if isinstance(r, dict) else None
    return {"status": st, "plannedTrain": train if st == "planned" else None}


def kind_status(kind: str, key: str) -> str:
    return kind_info(kind, key)["status"]


def register_managed_kind(kind: str, message: str) -> None:
    """L1 登記『受管 kind』：只能經擁有它的 L1 入口寫入；通用 draft／publish／restore／刪草稿一律拒絕並回這句白話訊息。"""
    if not isinstance(kind, str) or not _CODE.match(kind) or not isinstance(message, str) or not message.strip():
        raise ValueError("受管 kind 需要小寫英數底線的 kind 與一句白話訊息")
    if kind in _MANAGED and _MANAGED[kind] != message:
        raise ValueError("受管 kind %r 已登記為另一句訊息" % kind)
    _MANAGED[kind] = message


def managed_message(kind: str) -> Optional[str]:
    return _MANAGED.get(kind)


# ── 健康來源：多個來源共用系統中心『設定中心』卡的單一徽章 ──────────────────────────────

def register_health_source(name: str, fn: Callable) -> None:
    """L1 登記一個健康來源：`fn()` 回 `None`（沒事）或 `{"text", "tone", "count"?}`（`tone` ∈ 系統中心色調）。同名須是同一函式。
    系統中心每張卡只有一個徽章提供者，所以來源不要自己註冊 `system.hub_badge`，而是登記在這裡，由 `health_badge()` 合併。
    **`text` 只可用數量與通用詞（例「2 條規則已降級」）；絕不可出現 hidden／planned 功能、群組或規則的名稱或鍵**（徽章對所有看得到系統中心的人可見）。"""
    if name in _HEALTH and _HEALTH[name] is not fn:
        raise ValueError("健康來源 %r 已登記為另一個函式" % name)
    _HEALTH[name] = fn


def health_badge() -> dict:
    """合併後的徽章 `{text, tone, count?}`：脊柱自己的線（驗證失敗 ⇒ bad；開發中／隱藏 ⇒ plan）＋所有登記的來源。
    色調取最嚴重者（bad＞warn＞plan＞info＞ok）；文字依嚴重度排序、去重、以『・』相連並截到 40 字；`count` 為各來源 count 之和（有才回）。
    都沒事 ⇒ `{"text": "功能登錄正常", "tone": "ok"}`。壞掉的來源（丟例外／格式不對）略過並記 log，不影響其他來源。"""
    lines = []
    rep = report()
    if rep["problems"]:
        lines.append({"text": "%d 項功能登錄未通過驗證" % rep["problems"], "tone": "bad", "count": rep["problems"]})
    else:
        planned = sum(1 for f in rep["features"] if f["status"] == "planned")
        hidden = sum(1 for f in rep["features"] if f["status"] == "hidden")
        if planned or hidden:
            parts = (["開發中 %d 項" % planned] if planned else []) + (["已隱藏 %d 項" % hidden] if hidden else [])
            lines.append({"text": "・".join(parts), "tone": "plan"})
    for name in sorted(_HEALTH):
        try:
            r = _HEALTH[name]()
        except Exception:                                              # noqa: BLE001
            _log.warning("健康來源 %s 失敗，略過", name, exc_info=True)
            continue
        if r is None:
            continue
        if not isinstance(r, dict) or not isinstance(r.get("text"), str) or not r["text"].strip() or r.get("tone") not in TONE_ORDER:
            _log.warning("健康來源 %s 回傳格式不對，略過：%r", name, r)
            continue
        lines.append({"text": r["text"].strip(), "tone": r["tone"], "count": r.get("count")})
    if not lines:
        return {"text": "功能登錄正常", "tone": "ok"}
    lines.sort(key=lambda x: TONE_ORDER.index(x["tone"]))
    texts = []
    for ln in lines:
        if ln["text"] not in texts:
            texts.append(ln["text"])
    out = {"text": "・".join(texts)[:40], "tone": lines[0]["tone"]}
    counts = [ln["count"] for ln in lines if isinstance(ln.get("count"), int) and not isinstance(ln.get("count"), bool)]
    if counts:
        out["count"] = sum(counts)
    return out


# ── 目錄表面的功能狀態（規則發布／還原時檢查）────────────────────────────────────────────

def surface_status(surface: str) -> str:
    """表面鍵（例 `module:case.quotation_list`）→ 宣告它的功能的狀態：`features[].catalog.surfaces` 指名該表面的功能，取最嚴者
    （hidden＞planned＞open）；功能驗證失敗視為 hidden；沒有人宣告 ⇒ open；`validate_all()` 之前 ⇒ open。"""
    if not _VALIDATED:
        return "open"
    rank = {"open": 0, "planned": 1, "hidden": 2}
    worst = "open"
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        if surface in ((f["catalog"] or {}).get("surfaces") or []) and _surface_owned(surface, f["owner"]):     # 非自己擁有的宣告不算（它本身也會驗證失敗）
            st = "hidden" if _state(code) == STATE_FAILED else f["status"]
            if rank[st] > rank[worst]:
                worst = st
    return worst


def planned_cards() -> List[dict]:
    """設定中心的『即將推出』卡片：status＝planned、**沒有設定群組**（有群組的會以灰色群組出現在群組清單裡）、驗證沒失敗的功能。
    只回 `{code, label, plannedTrain}`，依 planned_train 數字、再依代號排序。hidden 永遠不列。"""
    out = []
    for code in sorted(_FEATURES):
        f = _FEATURES[code]
        if f["status"] != "planned" or f["group"] or not f["planned_train"] or _state(code) == STATE_FAILED:
            continue
        out.append({"code": code, "label": f["label"], "plannedTrain": f["planned_train"]})
    return sorted(out, key=lambda c: (int(c["plannedTrain"][2:]), c["code"]))


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
            {k: set(v) for k, v in _MANIFEST_CAPS.items()}, _VALIDATED, {k: set(v) for k, v in _CLAIMS.items()},
            {k: set(v) for k, v in _REJECTED_GROUPS.items()})


def restore(snap: tuple) -> None:
    global _VALIDATED
    _FEATURES.clear(); _FEATURES.update(snap[0])
    _ORPHANS.clear(); _ORPHANS.update(snap[1])
    _STATE.clear(); _STATE.update(snap[2])
    _MANIFEST_CAPS.clear(); _MANIFEST_CAPS.update(snap[3])
    _VALIDATED = snap[4]
    _CLAIMS.clear(); _CLAIMS.update(snap[5] if len(snap) > 5 else {})
    _REJECTED_GROUPS.clear(); _REJECTED_GROUPS.update(snap[6] if len(snap) > 6 else {})


def reset() -> None:
    """測試用：清空功能登錄與驗證狀態（驗證器與回呼是 import 時登記的，不動）。"""
    restore(({}, {}, {}, {}, False, {}, {}))


registry.on_unload(drop_owner)          # 模組失敗／卸載 ⇒ 它的功能一併移除
