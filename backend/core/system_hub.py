# -*- coding: utf-8 -*-
"""系統中心（System Hub）登錄表：『系統』底下所有設定／管理／稽核入口的索引（第 54 班 P1；設計 docs/platform/plans/SYSTEM-HUB-DESIGN-T54.md）。

[單位] plat:system_hub    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] SECTIONS, CARD_KEYS, load_l1_cards, module_cards, validate, visible_cards, build_sections, section_keys
[不變式] 原則（使用者核定）：**框架先行、不寫死決定**——新增一個設定或頁面 ＝ 在擁有它的模組宣告一筆 `system_cards`，**不改 hub**。
         卡片只來自 `core/system_hub_l1.json`（L1 頁面）與已載入模組的 module.json `system_cards`；分組（section）固定在這裡，模組只能選用不能自開。
         卡片的 `perm` 必須與它指向的頁面的選單 `perm` 相同（hub 只是索引，不放寬、不收緊任何頁面的權限）。
[契約題] tests/platform/test_system_hub.py

卡片欄位（`system_cards[]`）：
  id       全站唯一（英數與 -_）            section  分組鍵（SECTIONS 之一）
  title    標題                              desc     一行說明
  impact   『改了會影響什麼』一句白話（必填；例：影響：只影響之後送出的單據，簽核中的不變。）
  href     頁面檔名（可帶 #錨點）            perm     'superadmin' | ["模組鍵",…] | 'any'（同選單語意）
  order    整數（同組內排序）                keywords 搜尋關鍵字（空白分隔，選用）
  icon     圖示鍵（選用，ICONS 之一）        planned  True ⇒ 規劃中（頁面尚未存在，不檢查 href 是否存在，列上標「規劃中」）
即時狀態徽章（選用）由提供者回傳：`ModuleSpec.providers[("system.hub_badge", "<card id>")] = fn(conn, user) -> {"text", "tone", "count"?}`。
"""
import json
import re
from pathlib import Path

L1_CARDS = Path(__file__).with_name("system_hub_l1.json")

#: 分組固定在 L1（模組只能選用）；順序即左欄顯示順序
SECTIONS = (
    {"key": "identity", "title": "帳號與權限", "sub": "誰能進系統、能看什麼、能做什麼"},
    {"key": "workflow", "title": "簽核與流程", "sub": "誰簽什麼、單據類型與款別"},
    {"key": "notify", "title": "通知與信件", "sub": "什麼事通知誰、怎麼通知"},
    {"key": "data", "title": "資料與備份", "sub": "檔案位置、備份、刪除後的暫存區"},
    {"key": "audit", "title": "稽核與紀錄", "sub": "誰在什麼時候做了什麼"},
    {"key": "settings", "title": "公司與參數設定", "sub": "公司資料、法規參數、報表與利潤口徑（設定中心索引）"},
    {"key": "modules", "title": "模組與擴充", "sub": "功能開關與自訂模組"},
    {"key": "status", "title": "系統狀態與版本", "sub": "版本、資料庫結構、使用狀況"},
)
ICONS = ("user", "shield", "flow", "mail", "cal", "disk", "trash", "log", "gear", "build", "ver", "org", "file", "scale")
CARD_KEYS = {"id", "section", "title", "desc", "impact", "href", "perm", "order", "keywords", "icon", "planned"}
TONES = ("ok", "info", "warn", "bad", "plan")


def section_keys():
    return [s["key"] for s in SECTIONS]


def load_l1_cards(path=L1_CARDS):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [dict(c, module="core") for c in d.get("cards") or []]


def module_cards(manifests):
    """{模組key: manifest} ⇒ [card（帶 "module"＝key）]。manifests 只該含**已載入**模組（呼叫端負責）。"""
    out = []
    for key in sorted(manifests):
        for c in (manifests[key] or {}).get("system_cards") or []:
            if isinstance(c, dict):
                out.append(dict(c, module=key))
    return out


def _perm_ok(perm):
    return perm in ("any", "superadmin") or (isinstance(perm, list) and bool(perm) and all(isinstance(k, str) and k for k in perm))


_CJK = re.compile(r"[一-鿿]")
_CODEISH = re.compile(r"\.html|/api/|https?://|[a-z]+_[a-z_]+|module|API|JSON", re.I)


def plain_problem(text):
    """使用者介面文字必須是白話：要有中文、不可出現網址／檔名／底線代碼／module／API 等（使用者核心原則：畫面上不出現程式碼）。"""
    t = str(text or "")
    if not _CJK.search(t):
        return "沒有中文"
    m = _CODEISH.search(t)
    return "含程式碼樣式的字：%r" % m.group(0) if m else ""


def _page_of(href):
    return str(href or "").split("#", 1)[0].lstrip("/")


def validate(cards, pages=None):
    """卡片宣告有問題 ⇒ 問題清單（守門與啟動檢查共用）。pages：已存在的頁面檔名集合（給了才檢查 href；planned 卡片不檢查）。"""
    problems, seen = [], {}
    secs = set(section_keys())
    for c in cards:
        where = "模組 %s" % c.get("module") if c.get("module") not in (None, "core") else "L1"
        cid = c.get("id")
        extra = set(c) - CARD_KEYS - {"module"}
        if extra:
            problems.append("%s 的系統卡片 %s 有不認得的欄位：%s" % (where, cid, sorted(extra)))
        if not cid or not all(ch.isalnum() or ch in "-_" for ch in str(cid)):
            problems.append("%s 有系統卡片 id 空白或含不合法字元：%r" % (where, cid))
        if cid in seen:
            problems.append("系統卡片 id %s 重複（%s 與 %s）" % (cid, seen[cid], where))
        seen[cid] = where
        if c.get("section") not in secs:
            problems.append("%s 的系統卡片 %s 用了不存在的分組 %r（分組只能在 L1 定義：%s）" % (where, cid, c.get("section"), sorted(secs)))
        if not c.get("title") or not c.get("desc") or not c.get("href"):
            problems.append("%s 的系統卡片 %s 缺 title／desc／href" % (where, cid))
        if not str(c.get("impact") or "").strip():
            problems.append("%s 的系統卡片 %s 缺 impact（改了會影響什麼，一句白話；使用者核心原則）" % (where, cid))
        for fld in ("title", "desc", "impact"):
            why = plain_problem(c.get(fld)) if c.get(fld) else ""
            if why:
                problems.append("%s 的系統卡片 %s 的 %s 不是白話（%s）：%r" % (where, cid, fld, why, c.get(fld)))
        if not isinstance(c.get("order"), int):
            problems.append("%s 的系統卡片 %s 缺整數 order" % (where, cid))
        if not _perm_ok(c.get("perm")):
            problems.append("%s 的系統卡片 %s 的 perm 不合法：%r" % (where, cid, c.get("perm")))
        if c.get("icon") is not None and c.get("icon") not in ICONS:
            problems.append("%s 的系統卡片 %s 的 icon 不認得：%r" % (where, cid, c.get("icon")))
        if pages is not None and not c.get("planned") and _page_of(c.get("href")) not in pages:
            problems.append("%s 的系統卡片 %s 指向不存在的頁面 %r（頁面還沒做就標 planned）" % (where, cid, c.get("href")))
    return problems


def visible_cards(cards, modules, superadmin):
    """依使用者權限過濾（規則同 core.menu.visible；hub 不放寬也不收緊任何頁面的權限）。"""
    from core.menu import visible
    mods = set(modules or [])
    return [c for c in cards if visible(c["perm"], mods, superadmin)]


def denied_reason(perm, module_labels=None):
    """沒有權限時顯示給使用者的白話原因（不出現模組鍵）。module_labels：{模組鍵: 中文名稱}。"""
    if perm == "superadmin":
        return "需要最高管理者的權限"
    labels = []
    for k in perm if isinstance(perm, list) else []:
        t = (module_labels or {}).get(k) or ""
        t = t.split("（", 1)[0].strip()
        labels.append("「%s」" % t if t else "相關")
    return "需要%s的使用權限" % ("、".join(labels) if labels else "相關")


def build_sections(cards, denied=(), module_labels=None):
    """已過濾的卡片 ⇒ [{key,title,sub,count,items:[…]}]（只含有項目的分組；組內依 order、再依 id）。
    denied：使用者**沒有權限**的卡片（超級管理員在設定打開『顯示沒有權限的項目』時才給；預設不給）——列出但標 denied＋白話原因，不可點。
    count＝能開的項數（不含 denied）。badge／pending 由呼叫端（routers/system_hub.py）補上。"""
    by = {s["key"]: [] for s in SECTIONS}
    for c in cards:
        if c.get("section") in by:
            by[c["section"]].append((c, False))
    for c in denied:
        if c.get("section") in by:
            by[c["section"]].append((c, True))
    out = []
    for s in SECTIONS:
        items = sorted(by[s["key"]], key=lambda t: (t[1], t[0]["order"], t[0]["id"]))
        if items:
            out.append({"key": s["key"], "title": s["title"], "sub": s["sub"], "count": sum(1 for _c, d in items if not d),
                        "items": [{"id": c["id"], "title": c["title"], "desc": c["desc"], "impact": c.get("impact") or "", "href": c["href"], "icon": c.get("icon") or "gear",
                                   "keywords": c.get("keywords") or "", "module": c.get("module") or "core", "planned": bool(c.get("planned")),
                                   "denied": d, "reason": denied_reason(c["perm"], module_labels) if d else "", "badge": None} for c, d in items]})
    return out
