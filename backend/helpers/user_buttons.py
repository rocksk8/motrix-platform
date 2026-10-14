# -*- coding: utf-8 -*-
"""使用者自訂按鈕（T61 S6；設計：docs/platform/plans/T61-S6-ACTION-CATALOG-DESIGN.md）。

[單位] helper:user_buttons    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ACTION_TYPES, BUTTON_EXPORTS, KIND, MAX_PER_SLOT, MAX_SLOTS_PER_PAGE, MAX_TOTAL, SLOTS, catalog, definition_problems, enabled, preview, visible_buttons
[不變式] ①旗標 `builder_actions.enabled` 關閉 ⇒ `visible_buttons()` 一律空、`preview()` 不可用；②按鈕**不授權**：
    開頁＝連結（目標頁面自己的登入／模組權限照舊）、匯出＝用點擊者自己的 token 呼叫模組已登記的 GET 端點（端點自己的權限、遮蔽、稽核照舊）；
    ③動作類型只有 navigate／export（沒有任何會寫資料的動作）；目標只來自目錄（選單上的頁面、module.json 已登記的匯出）；
    ④給前端的端點路徑**來自目錄，不來自使用者存的定義**；⑤逐顆用檢視者的權限過濾（看不到目標＝不出現），過濾不是存取控制，真正擋人的永遠是目標。
[契約題] backend/tests/test_user_buttons_2026_10_14.py

定義存在定義文件庫（kind＝`user_buttons`，key＝`module:<模組鍵>`，scope＝company）：
`{"buttons": [{"key": "b1", "slot": "suppliers.html/toolbar", "label": "…", "action": {"type": "navigate", "page": "x.html"}
              | {"type": "export", "export": "<模組>:<匯出 key>"}}]}`。
插槽表（`SLOTS`）先放在這裡（先導不動 L0）；之後可搬到 module.json 的 `button_slots`（需要核心層的驗證器，另案）。
"""
import re

from core import definitions as D

ACTION_TYPES = ("navigate", "export")
MAX_PER_SLOT = 6
MAX_SLOTS_PER_PAGE = 3
MAX_TOTAL = 30
_MAX_LABEL = 20
KIND = "user_buttons"
_KEY_RE = re.compile(r"^b[0-9]{1,3}$")
_PAGE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\.html$")
_BAD_LABEL = re.compile(r"[<>&\"'`\\\x00-\x1f\x7f‪-‮⁦-⁩]")
_BUTTON_KEYS = {"key", "slot", "label", "action"}
#: 永遠不能當導向目標的頁面（登入、首頁，以及要帶查詢字串才有意義的明細頁）
_NAV_EXCLUDE = frozenset({"login.html", "index.html", "customer-log.html", "supplier-log.html"})

#: 可被按鈕執行的匯出（明確的允許清單）：module.json 登記了 `exports` 不代表可以變成按鈕的目標——未來若有會產生副作用的 GET 匯出，
#: 不會悄悄變成可放的按鈕。要加一個，必須在這裡明列（程式碼審查項目）。
BUTTON_EXPORTS = frozenset({"subcontract:roster"})
_API_PATH = re.compile(r"^/api/[A-Za-z0-9_/.-]+$")

#: 插槽表：(模組鍵, 頁面) ⇒ {插槽鍵: 白話名稱}。頁面 HTML 用 `data-button-slot="<插槽鍵>"` 標出位置（守門測試雙向檢查）。
SLOTS = {
    ("supply", "suppliers.html"): {"toolbar": "工具列"},
}


def enabled(conn=None) -> bool:
    """旗標是否開啟。永不丟例外（讀不到 ⇒ 關閉＝今天的行為）。"""
    try:
        from helpers import settings_registry as _SR
        return bool(_SR.get("builder_actions", "enabled", conn=conn))
    except Exception:                                                                    # noqa: BLE001
        return False


# ── 目錄 ──────────────────────────────────────────────────────────────────
def _loaded_manifests():
    from core import registry
    return {m.key: m.manifest for m in registry.loaded()}


def _nav_pages(modules, superadmin) -> dict:
    """某位使用者（模組清單＋是否最高管理者）在側欄選單上看得到的頁面 ⇒ {頁面檔名: 白話標籤}。
    『可導向的頁面』＝出現在側欄選單上的頁面（先過 core.menu.build 的權限過濾），不含排除清單與帶查詢字串的。"""
    from core import menu as core_menu
    mod_items = core_menu.module_items(_loaded_manifests())
    groups = core_menu.build(core_menu.load_l1(), mod_items, modules, superadmin)
    out = {}
    for g in groups:
        for it in g.get("items") or []:
            href = str(it.get("href") or "")
            if _PAGE_RE.match(href) and href not in _NAV_EXCLUDE:
                out.setdefault(href, it.get("label") or href)
    return out


def _exports() -> dict:
    """模組在 module.json 已登記、且可被按鈕執行的匯出 ⇒ {"<模組>:<key>": {label, endpoint, path, format, perm, module}}。
    條件：方法必須是 GET（不寫資料）。"""
    from core import customization as _cz
    out = {}
    for mkey, man in _loaded_manifests().items():
        for pg in ((man or {}).get("customization") or {}).get("pages") or []:
            for ex in pg.get("exports") or []:
                parts = _cz.endpoint_parts(ex.get("endpoint"))
                if not parts or parts[0] != "GET" or not _API_PATH.match(parts[1]) or ".." in parts[1] or "//" in parts[1]:
                    continue                                                   # 只收『GET 且無參數的 /api/ 單純路徑』
                if "%s:%s" % (mkey, ex.get("key")) not in BUTTON_EXPORTS:
                    continue                                                   # 且必須在允許清單內
                out["%s:%s" % (mkey, ex.get("key"))] = {"label": ex.get("label") or ex.get("key"), "endpoint": ex.get("endpoint"),
                                                         "path": parts[1], "format": ex.get("format"), "perm": ex.get("perm"), "module": mkey}
    return out


def catalog(modules=None, superadmin=True) -> dict:
    """編輯器要的完整目錄（給最高管理者）：可導向的頁面、可執行的匯出、插槽。"""
    return {
        "pages": [{"page": p, "label": l} for p, l in sorted(_nav_pages(modules or [], superadmin).items())],
        "exports": [{"id": k, "label": v["label"], "format": v["format"], "module": v["module"]} for k, v in sorted(_exports().items())],
        "slots": [{"module": m, "page": p, "key": k, "label": l, "id": "%s/%s" % (p, k)}
                  for (m, p), slots in sorted(SLOTS.items()) for k, l in sorted(slots.items())],
    }


# ── 定義驗證 ──────────────────────────────────────────────────────────────
def _module_of_key(key):
    m = re.match(r"^module:([a-z][a-z0-9_]{0,39})$", key or "")
    return m.group(1) if m else None


def _label_problem(label):
    if not isinstance(label, str) or not label.strip():
        return "按鈕文字不可以空白"
    if _BAD_LABEL.search(label):
        return "按鈕文字不可含 < > & 引號、反斜線或控制字元"
    if len(label.strip()) > _MAX_LABEL:
        return "按鈕文字最多 %d 字" % _MAX_LABEL
    return None


def definition_problems(key, body) -> list:
    """發布前驗證 ⇒ `[{path, message}]`（空＝通過）。kind 驗證器（`D.register_kind`）呼叫。"""
    mod = _module_of_key(key)
    if mod is None:
        return [{"path": "", "message": "key 必須是 module:<模組鍵>"}]
    if mod not in _loaded_manifests():
        return [{"path": "", "message": "模組未載入：%s" % mod}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "定義必須是物件"}]
    out = [{"path": k, "message": "不認得的鍵：%s" % k} for k in body if k != "buttons"]
    buttons = body.get("buttons")
    if not isinstance(buttons, list):
        return out + [{"path": "buttons", "message": "buttons 必須是清單"}]
    if len(buttons) > MAX_TOTAL:
        out.append({"path": "buttons", "message": "全公司最多 %d 顆按鈕" % MAX_TOTAL})
    slots = {"%s/%s" % (p, k) for (m, p), ss in SLOTS.items() if m == mod for k in ss}
    nav = _nav_pages([], True)
    exports = _exports()
    seen, per_slot = set(), {}
    for i, b in enumerate(buttons):
        p = "buttons[%d]" % i
        if not isinstance(b, dict):
            out.append({"path": p, "message": "按鈕必須是物件"})
            continue
        for k in b:
            if k not in _BUTTON_KEYS:
                out.append({"path": "%s.%s" % (p, k), "message": "不認得的鍵：%s（按鈕只有 key、slot、label、action）" % k})
        if not isinstance(b.get("key"), str) or not _KEY_RE.match(b["key"]):
            out.append({"path": p + ".key", "message": "按鈕 key 必須是 b 加數字（例 b1）"})
        elif b["key"] in seen:
            out.append({"path": p + ".key", "message": "按鈕 key 重複：%s" % b["key"]})
        seen.add(b.get("key"))
        if b.get("slot") not in slots:
            out.append({"path": p + ".slot", "message": "不是登記的插槽：%r" % (b.get("slot"),)})
        else:
            per_slot[b["slot"]] = per_slot.get(b["slot"], 0) + 1
            if per_slot[b["slot"]] > MAX_PER_SLOT:
                out.append({"path": p + ".slot", "message": "每個插槽最多 %d 顆按鈕" % MAX_PER_SLOT})
        msg = _label_problem(b.get("label"))
        if msg:
            out.append({"path": p + ".label", "message": msg})
        a = b.get("action")
        if not isinstance(a, dict):
            out.append({"path": p + ".action", "message": "action 必須是物件"})
            continue
        t = a.get("type")
        if t not in ACTION_TYPES:
            out.append({"path": p + ".action.type", "message": "動作類型只能是：%s" % "、".join(ACTION_TYPES)})
            continue
        want = {"type", "page"} if t == "navigate" else {"type", "export"}
        for k in a:
            if k not in want:
                out.append({"path": "%s.action.%s" % (p, k), "message": "不認得的鍵：%s（%s 只有 %s）" % (k, t, "、".join(sorted(want)))})
        if t == "navigate":
            if a.get("page") not in nav:
                out.append({"path": p + ".action.page", "message": "不是可開啟的頁面（只能選側欄選單上的頁面）：%r" % (a.get("page"),)})
        elif a.get("export") not in exports:
            out.append({"path": p + ".action.export", "message": "不是已登記的匯出：%r" % (a.get("export"),)})
    pages = {s.split("/")[0] for s in per_slot}
    for pg in pages:
        n = len({s for s in per_slot if s.startswith(pg + "/")})
        if n > MAX_SLOTS_PER_PAGE:
            out.append({"path": "buttons", "message": "每頁最多 %d 個插槽" % MAX_SLOTS_PER_PAGE})
    return out


def _kind_validator(body, key):
    return definition_problems(key, body)


if KIND not in D.kinds():
    D.register_kind(KIND, label="使用者按鈕", validator=_kind_validator)


# ── 執行期：逐顆用檢視者的權限過濾 ────────────────────────────────────────
def _viewer(conn, user):
    """⇒ (modules, superadmin, user_for_has_module)。"""
    from helpers.auth import effective_modules
    modules = effective_modules(user.get("role"), user.get("modules"), user_id=user.get("id"), conn=conn)
    return modules, user.get("role") == "superadmin", user


def _filter(buttons, user, modules, superadmin, module, page):
    nav = _nav_pages(modules, superadmin)
    exports = _exports()
    out, hidden = [], []
    for b in buttons or []:
        if not isinstance(b, dict) or not str(b.get("slot") or "").startswith(page + "/"):
            continue
        a = b.get("action") or {}
        base = {"key": b.get("key"), "label": b.get("label"), "slot": str(b.get("slot")).split("/", 1)[1]}
        if a.get("type") == "navigate":
            if a.get("page") in nav:
                out.append(dict(base, type="navigate", page=a["page"]))
            else:
                hidden.append({"key": b.get("key"), "reason": "這位使用者打不開「%s」" % (a.get("page"),)})
        elif a.get("type") == "export":
            ex = exports.get(a.get("export"))
            if ex and (not ex.get("perm") or superadmin or ex["perm"] in modules):
                out.append(dict(base, type="export", endpoint=ex["path"], format=ex["format"], exportId=a["export"]))
            else:
                hidden.append({"key": b.get("key"), "reason": "這位使用者沒有匯出「%s」的權限" % ((ex or {}).get("label") or a.get("export"),)})
        else:
            hidden.append({"key": b.get("key"), "reason": "動作類型不認得"})
    return out, hidden


def visible_buttons(conn, user, module, page) -> list:
    """某頁、某位使用者看得到的按鈕（已發布定義，逐顆過濾）。旗標關閉／沒有定義 ⇒ []。永不丟例外。"""
    if (module, page) not in SLOTS or not enabled(conn):
        return []
    try:
        r = D.get(conn, KIND, "module:%s" % module, "company")
        buttons = ((r or {}).get("body") or {}).get("buttons") or []
        modules, sa, u = _viewer(conn, user)
        return _filter(buttons, u, modules, sa, module, page)[0]
    except Exception:                                                                    # noqa: BLE001
        return []


def preview(conn, caller, definition, module, page, username=None):
    """草稿預覽（唯讀、不寫任何資料）：以某位使用者（預設＝呼叫者）的真實權限，算出這份草稿在這一頁哪些按鈕會出現、哪些不會與原因。
    ⇒ `{user, role, visible:[…], hidden:[{key, reason}]}`；草稿不合法 ⇒ ValueError(problems)；找不到使用者 ⇒ LookupError。"""
    probs = definition_problems("module:%s" % module, definition)
    if probs:
        raise ValueError(probs)
    from helpers.auth import effective_modules
    if username:
        row = conn.execute("SELECT id, username, role, modules FROM users WHERE username=? AND active=1", (str(username),)).fetchone()
        if not row:
            raise LookupError("找不到這位使用者")
        u = {"id": row["id"], "username": row["username"], "role": row["role"], "modules": row["modules"]}
    else:
        u = caller
    modules = effective_modules(u.get("role"), u.get("modules"), user_id=u.get("id"), conn=conn)
    visible, hidden = _filter(definition.get("buttons"), u, modules, u.get("role") == "superadmin", module, page)
    return {"user": u.get("username"), "role": u.get("role"), "visible": visible, "hidden": hidden}
