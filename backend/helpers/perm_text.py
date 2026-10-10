# -*- coding: utf-8 -*-
"""權限矩陣的白話文字（使用者核心規則 2026-10-10：畫面上沒有代碼、沒有 allow/deny 這類英文、沒有 id；只有繁體中文名稱、一句話說明與白話風險提示）。

[單位] helper:perm_text    [層] L1    [穩定度] 實作
[公開介面] ROLE_LABELS_DEFAULT, role_label, user_label, module_label, action_label, question, sentence_role_cap, sentence_user_override, sentence_delegation, explain_text, risk_hint
[不變式] ① 輸出只含中文名稱與句子：不得出現能力鍵（`xxx.yyy.zzz`）、`allow`／`deny`、`superadmin` 等代碼；代碼對不到名稱時一律說「（未命名）」而不是露出代碼
         ② 不用「他／她」：句子重複稱呼對象的名字
         ③ 角色名稱＝系統設定 `role_labels`（管理者可改）疊在預設之上
[契約題] tests/platform/test_perm_text.py
"""
from typing import Iterable, Optional

from core import capabilities as _cap
from helpers import perm as _perm

#: 預設角色名稱；與 `routers/system.py::_DEFAULT_ROLE_LABELS` 相同（守門題核對相等，避免漂移）。實際顯示以系統設定 `role_labels` 為準。
ROLE_LABELS_DEFAULT = {
    "superadmin": "超級管理員",
    "admin": "管理員",
    "sales": "業務",
    "engineer": "工程師",
    "finance": "財務",
    "viewer": "檢視者",
}


def role_label(role: str) -> str:
    try:
        from helpers.settings import _get_setting
        stored = _get_setting("role_labels") or {}
    except Exception:                                  # noqa: BLE001
        stored = {}
    return (stored.get(role) if isinstance(stored, dict) else None) or ROLE_LABELS_DEFAULT.get(role) or "（未命名角色）"


def user_label(user: Optional[dict]) -> str:
    return ((user or {}).get("display_name") or (user or {}).get("username") or "（未命名）")


def module_label(key: str) -> str:
    try:
        from helpers import module_registry as mr
        for k, label, _g in mr.MODULES:
            if k == key:
                return label
    except Exception:                                  # noqa: BLE001
        pass
    return "（未命名功能）"


def action_label(action: str) -> str:
    return _cap.ACTION_INFO.get(action, ("（未命名動作）", ""))[0]


def _cap_label(key: str) -> str:
    c = _cap.get(key)
    return c.label if c is not None else "（未命名）"


def question(key: str, who: str) -> str:
    """白話提問，例：「財務可以送出勞報單嗎？」。"""
    c = _cap.get(key)
    return (c.question if c is not None else "{who}可以做這件事嗎？").replace("{who}", who)


def sentence_role_cap(role: str, key: str, granted: bool) -> str:
    return "%s%s%s" % (role_label(role), "可以" if granted else "不能", _cap_label(key))


def sentence_user_override(user_name: str, key: str, allow: bool) -> str:
    return "%s%s%s（只針對這一位）" % (user_name, "特別可以" if allow else "不能", _cap_label(key))


def sentence_delegation(delegator_name: str, delegate_name: str, keys: Iterable[str], valid_to: str = "", pending_hours: int = 0) -> str:
    """送出前的白話摘要：「你即將讓王小明代理李主任：送出勞報單、核准傳票，到 11/30，24 小時後生效」。"""
    what = "、".join(_cap_label(k) for k in keys) or "指定的事項"
    until = ""
    if valid_to:
        mm = valid_to[5:7].lstrip("0") or "?"
        dd = valid_to[8:10].lstrip("0") or "?"
        until = "，到 %s/%s" % (mm, dd)
    when = "，%d 小時後生效" % pending_hours if pending_hours else "，儲存後立即生效"
    return "你即將讓%s代理%s：%s%s%s" % (delegate_name, delegator_name, what, until, when)


def risk_hint(key: str) -> str:
    """白話風險提示；低風險回空字串。"""
    c = _cap.get(key)
    if c is None or c.risk != "high":
        return ""
    return "這是高風險權限（%s）：需要填寫原因，24 小時後才會生效，這段時間內隨時可以撤銷。" % action_label(c.action)


def explain_text(user: dict, key: str) -> str:
    """為什麼這個人（沒）有這項能力——一句白話。"""
    name = user_label(user)
    c = _cap.get(key)
    if c is None:
        return "找不到這項功能。"
    r = _perm.explain(user, key)
    via, ok = r.get("via"), bool(r.get("allowed"))
    if via == "superadmin":
        return "%s是最高管理者，所有事情都可以做。" % name
    if via == "deny":
        return "%s不能%s：管理者特別禁止了這一位。" % (name, c.label)
    if via == "allow":
        return "%s可以%s：管理者特別允許了這一位。" % (name, c.label)
    if via == "role":
        return "%s可以%s：「%s」這個角色有勾選。" % (name, c.label, role_label(user.get("role")))
    if via == "module":
        return "%s可以%s：已開通「%s」功能。" % (name, c.label, module_label(r.get("module") or ""))
    if via == "delegation":
        who = r.get("delegator") or ""
        d = _perm.load_user(who) if who else None
        return "%s可以%s：目前正在代理%s。" % (name, c.label, user_label(d or {"username": who}) if who else "其他人")
    return "%s目前不能%s。" % (name, c.label) if not ok else "%s可以%s。" % (name, c.label)
