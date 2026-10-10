# -*- coding: utf-8 -*-
"""能力登錄（權限矩陣框架 P0；設計 docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md §2）。

[單位] plat:capabilities    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ACTIONS, ACTION_INFO, HIGH_RISK_ACTIONS, RISKS, KEY_RE, configure, collect_presets, all_presets, problems, signature, Capability, CapabilityError, parse_legacy, parse_decl, collect, all_caps, get, reset_cache
[不變式] ① 能力只由模組在 `module.json` 的 `capabilities` 宣告（加法）；本檔不寫死任何業務能力清單——寫死的那一份就是第二個來源
         ② 能力鍵＝`<單位>.<物件>.<動作>`，第一段必須等於宣告它的模組鍵；動作只能是固定詞彙 `ACTIONS`
         ③ 每個能力必須帶 `legacy`：今天的判斷式（小型 DSL：role／module／any）。種子（預設矩陣）與等價關卡都從它推導 ⇒ 上線當天零行為變更
         ③' 畫面只有白話中文：每個能力必須有 `label`（動作短語）、`desc`（一句話說明）、`impact`（勾選後會影響什麼），且含中文；缺或只有代碼 ⇒ 拒絕
            另可有 `question`（含 {who} 的白話提問）、`recommended`（建議可以做的角色）、`presets`（預設組合下有此能力的角色）、`impact_calc`
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

_CJK = re.compile("[㐀-鿿]")      # 白話中文檢查：至少一個中日韓字元

#: 固定動作詞彙（使用者 2026-10-10 裁示：再細分；匯出獨立一格）。單位專屬動作需另行升版此清單。
ACTIONS = ("menu", "view", "view_money", "view_sensitive", "create", "edit", "submit", "withdraw", "approve", "reject", "void",
           "pay", "delete", "export", "print", "attach", "comment", "reassign", "config")
#: 動作的白話名稱與一句話說明（頁面欄位標題用；使用者不讀程式碼，畫面上只有這些中文）。詞彙固定，所以這張表是框架的一部分、不是業務內容。
ACTION_INFO = {
    "menu": ("看得到選單", "導覽列與系統中樞會不會出現這個入口（只是藏入口，不等於能不能開）"),
    "view": ("查看", "可以打開並閱讀這類資料"),
    "view_money": ("查看金額", "可以看到成本、毛利、報價與付款金額"),
    "view_sensitive": ("查看個資", "可以看到銀行帳號、身分證字號、電話等敏感資料"),
    "create": ("新增填寫", "可以建立新的一筆並填寫內容"),
    "edit": ("修改", "可以修改已存在的內容"),
    "submit": ("送出審核", "可以把單據送去簽核"),
    "withdraw": ("撤回", "可以把已送出的單據收回來"),
    "approve": ("核准", "可以在簽核流程中按下核准（簽核人仍由簽核流程設定決定）"),
    "reject": ("退回", "可以在簽核流程中退回"),
    "void": ("作廢／取消", "可以讓單據作廢或取消"),
    "pay": ("付款", "可以登錄付款、標記已匯款"),
    "delete": ("刪除", "可以刪除（刪除會先進暫存區，三十天內可還原）"),
    "export": ("匯出", "可以下載或匯出成檔案"),
    "print": ("列印", "可以列印或產生 PDF"),
    "attach": ("附件", "可以上傳或刪除附件"),
    "comment": ("備註留言", "可以新增備註、留言"),
    "reassign": ("改負責人", "可以變更負責人或指派對象"),
    "config": ("管理設定", "可以調整這個功能的設定"),
}
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
    desc: str                           # 一句話白話說明（必填、必須含中文）
    impact: str                         # 勾選後會影響什麼（白話；必填、必須含中文）
    question: str                       # 白話提問，含 {who}，例：「{who}可以送出勞報單嗎？」（缺省由 label 產生）
    recommended: FrozenSet[str]         # 建議可以做的角色（缺省＝種子，即今天的行為）
    presets: Dict[str, FrozenSet[str]]  # 預設組合 → 該組合下有此能力的角色
    impact_calc: bool                   # 有提供影響計算（提供者 `perm.impact`，名稱＝單位）
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
    texts = {}
    for f in ("label", "desc", "impact"):
        v = str(decl.get(f) or "").strip()
        if not v:
            raise CapabilityError("%s：缺 %s（畫面只顯示白話中文：名稱、一句話說明、勾選後會影響什麼）" % (key, f))
        if not _CJK.search(v):
            raise CapabilityError("%s：%s 必須是白話中文（不能只是代碼或英文）：%r" % (key, f, v))
        texts[f] = v
    question = str(decl.get("question") or "").strip()
    if question:
        if "{who}" not in question or not _CJK.search(question):
            raise CapabilityError("%s：question 必須是含 {who} 的中文提問" % key)
    else:
        question = "{who}可以%s嗎？" % texts["label"]
    recommended = decl.get("recommended")
    if recommended is not None and (not isinstance(recommended, list) or any(not isinstance(r, str) for r in recommended)):
        raise CapabilityError("%s：recommended 必須是角色清單" % key)
    presets = decl.get("presets") or {}
    if not isinstance(presets, dict) or any(not isinstance(v, list) for v in presets.values()):
        raise CapabilityError("%s：presets 必須是 {組合代號: 角色清單}" % key)
    vr = valid_roles or _VALID_ROLES
    for who in list(recommended or []) + [r for v in presets.values() for r in v]:
        if vr is not None and who not in vr:
            raise CapabilityError("%s：recommended／presets 有不認得的角色：%s" % (key, who))
    risk = decl.get("risk", "low")
    if risk not in RISKS:
        raise CapabilityError("%s：risk 只能是 %s" % (key, "/".join(RISKS)))
    if m.group(3) in HIGH_RISK_ACTIONS:
        risk = "high"                                   # 宣告得再低也拉高（不變式 ④）
    if "legacy" not in decl:
        raise CapabilityError("%s：缺 legacy（今天的判斷式；沒有它就無法證明預設等價）" % key)
    roles, mods, tree = parse_legacy(decl["legacy"], valid_roles)
    return Capability(key=key, unit=unit, obj=m.group(2), action=m.group(3), label=texts["label"], risk=risk,
                      desc=texts["desc"], impact=texts["impact"], question=question,
                      recommended=frozenset(recommended) if recommended is not None else roles,
                      presets={k: frozenset(v) for k, v in presets.items()}, impact_calc=bool(decl.get("impact_calc", False)),
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


def collect_presets(manifests: Dict[str, dict]) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """預設組合的定義：模組在 module.json 的 `capability_presets: [{key, label, desc}]` 宣告（同代號多處宣告要一致）。回 ({代號: (名稱, 說明)}, [問題])。"""
    out: Dict[str, Tuple[str, str]] = {}
    problems: List[str] = []
    for unit in sorted(manifests):
        for d in (manifests[unit] or {}).get("capability_presets") or []:
            k, lab, desc = str((d or {}).get("key") or ""), str((d or {}).get("label") or "").strip(), str((d or {}).get("desc") or "").strip()
            if not re.fullmatch(r"[a-z][a-z0-9_]*", k) or not _CJK.search(lab) or not _CJK.search(desc):
                problems.append("%s：預設組合需要代號、中文名稱與中文說明：%r" % (unit, d))
            elif k in out and out[k] != (lab, desc):
                problems.append("%s：預設組合 %s 與其他模組的宣告不一致" % (unit, k))
            else:
                out[k] = (lab, desc)
    return out, problems


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


def all_presets() -> Dict[str, Tuple[str, str]]:
    """已載入模組宣告的預設組合：{代號: (名稱, 說明)}。"""
    return collect_presets(_manifests())[0]


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
