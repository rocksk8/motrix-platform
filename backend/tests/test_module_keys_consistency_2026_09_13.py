"""模組 key 的三方一致性（2026-09-13 模組權限稽核新增）。

「模組」這個機制同時活在三個地方，而**沒有任何東西在確保它們對得起來**：

1. `frontend/pages/users.html` 的權限目錄——決定管理員**勾得到**哪些 key
2. `frontend/static/sidebar.js`——決定側欄**看得到**哪些項目
3. `backend/routers/*.py`——決定 API **擋不擋得住**

2026-09-13 盤點時，三邊對不齊的地方一共七項，而且每一項都是**無聲**的：

- `project_manage`：後端 `material_orders.py` 拿它擋「修改叫料」，但 2026-08-26
  專案管理併入案件管理時把它從目錄拿掉了 → 新帳號永遠拿不到這個權限、一改叫料
  就 403，畫面上卻沒有任何地方勾得到它。
- `reports`／`finance`：目錄裡有、側欄會依它顯示營運報表，但後端 11 支報表端點
  只認 `admin+` → 勾了等於沒勾，點進去整頁 403。
- `sales`：只存在於角色樣板與 `_SUPERADMIN_MODULES`，全系統沒有任何地方讀它。
- `_SUPERADMIN_MODULES` 與 users.html 的 superadmin 樣板長期不同步。

這支測試把上面每一種漂移都變成會紅的斷言。新增模組時三邊各補一次很煩，但比
「側欄有、後端沒有」這種只有使用者踩到才會知道的狀態好。要刻意破例，就在下面
的白名單裡補一筆並寫明原因——跟 `test_router_registration_2026_09_10.py` 的
`RETIRED_ROUTERS` 同一個作法。
"""
import glob
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USERS_HTML = os.path.join(ROOT, "frontend", "pages", "users.html")
SIDEBAR_JS = os.path.join(ROOT, "frontend", "static", "sidebar.js")
AUTH_PY = os.path.join(ROOT, "backend", "helpers", "auth.py")

# 目錄裡有、但刻意沒有任何地方讀的 key：{key: 原因}
# 空的就是好事——每一筆都代表使用者勾得到一個不會發生任何事情的核取方塊。
UNREAD_BY_DESIGN = {}

# 後端會擋、但刻意不出現在權限目錄的 key：{key: 原因}
ENFORCED_BUT_NOT_GRANTABLE = {}


def _read(path):
    return io.open(path, encoding="utf-8").read()


def catalogue_keys():
    """users.html 權限目錄（不含同一頁下方那份通知偏好清單）。"""
    src = _read(USERS_HTML)
    start = src.index("{key:'dashboard'")
    end = src.index("{key:'approval_request'")   # 通知偏好清單的第一筆
    return [m.group(1) for m in re.finditer(r"\{key:'([a-z_]+)'", src[start:end])]


def role_templates():
    src = _read(USERS_HTML)
    block = src[src.index("const ROLE_MODULES"):src.index("function buildOrgRows")]
    return {m.group(1): re.findall(r"'([a-z_]+)'", m.group(2))
            for m in re.finditer(r"^\s*(superadmin|admin|sales|engineer|viewer):\s*\[([^\]]*)\]",
                                 block, re.M)}


def sidebar_keys():
    return set(re.findall(r"mods\.indexOf\('([a-z_]+)'\)", _read(SIDEBAR_JS)))


def frontend_other_keys():
    """側欄以外的前端判斷（頁面 inline script、frontend/js/*.js）。"""
    files = (glob.glob(os.path.join(ROOT, "frontend", "pages", "*.html"))
             + glob.glob(os.path.join(ROOT, "frontend", "js", "*.js"))
             + [os.path.join(ROOT, "frontend", "index.html")])
    src = "\n".join(_read(f) for f in files)
    return set(re.findall(r"(?:modules|mods|m)\.(?:includes|indexOf)\(\s*'([a-z_]+)'", src))


def backend_keys():
    """後端真的會拿來擋的 key。"""
    files = [f for f in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if "tests" not in f and "rollback_snapshots" not in f]
    src = "\n".join(_read(f) for f in files)
    keys = set(re.findall(r"user_has_module\([^,]+,\s*['\"]([a-z_]+)['\"]", src))
    keys |= set(re.findall(r"module=['\"]([a-z_]+)['\"]", src))
    keys |= set(re.findall(r"['\"]([a-z_]+)['\"]\s+in\s+(?:mods|modules|user_mods)\b", src))
    keys |= set(re.findall(r"_(?:EDIT_)?MODULE\s*=\s*['\"]([a-z_]+)['\"]", src))
    return keys


def superadmin_modules_py():
    src = _read(AUTH_PY)
    block = src[src.index("_SUPERADMIN_MODULES = ["):]
    block = block[:block.index("]")]
    return set(re.findall(r'"([a-z_]+)"', block))


def test_backend_enforced_keys_are_grantable():
    """後端擋得住的 key，管理員必須勾得到——否則權限只剩歷史殘值決定。"""
    missing = sorted(backend_keys() - set(catalogue_keys()) - set(ENFORCED_BUT_NOT_GRANTABLE))
    assert not missing, (
        f"這些 key 後端會拿來擋，但 users.html 的權限目錄裡沒有，管理員永遠勾不到"
        f"（新帳號＝永久 403，舊帳號靠歷史殘值才有）：{missing}\n"
        f"請在目錄補上，或改用一個目錄裡已經有的 key；刻意如此請在本檔 "
        f"ENFORCED_BUT_NOT_GRANTABLE 補一筆並寫明原因。"
    )


def test_sidebar_keys_are_grantable():
    """側欄拿來決定顯示的 key，也必須是勾得到的。"""
    missing = sorted(sidebar_keys() - set(catalogue_keys()))
    assert not missing, (
        f"側欄用這些 key 決定要不要顯示項目，但權限目錄裡沒有：{missing}"
    )


def test_every_catalogue_key_is_read_somewhere():
    """目錄裡的每個 key 至少要有一邊會讀，否則就是一個不會發生任何事的核取方塊。"""
    read = sidebar_keys() | backend_keys() | frontend_other_keys()
    dead = sorted(k for k in catalogue_keys() if k not in read and k not in UNREAD_BY_DESIGN)
    assert not dead, (
        f"這些模組 key 目錄裡有，但側欄／後端／其他前端都沒有任何地方讀它，"
        f"勾了不會發生任何事：{dead}\n"
        f"請刪除，或補上實際的用途；刻意保留請在本檔 UNREAD_BY_DESIGN 補一筆。"
    )


def test_role_template_keys_are_in_catalogue():
    """角色樣板不能塞目錄裡沒有的 key（`sales` 當初就是這樣活了很久）。"""
    cat = set(catalogue_keys())
    bad = {role: sorted(set(ms) - cat) for role, ms in role_templates().items()
           if set(ms) - cat}
    assert not bad, f"角色樣板含有目錄裡不存在的 key：{bad}"


def test_backend_default_superadmin_modules_match_frontend_template():
    """`_SUPERADMIN_MODULES`（首次安裝建立的管理員）必須等於前端 superadmin 樣板。

    兩邊本來就該是同一份清單；不同步時症狀是「第一個管理員的模組跟後來建的不一樣」
    ——superadmin 幾乎都走角色直通，所以不會有人發現，只會誤導下一個讀程式的人。
    """
    fe = set(role_templates()["superadmin"])
    be = superadmin_modules_py()
    assert fe == be, (
        f"兩邊不同步：\n  只在 users.html 樣板：{sorted(fe - be)}"
        f"\n  只在 helpers/auth.py：{sorted(be - fe)}"
    )


# ── 模組檢查「擋錯人」的守門（2026-09-13 第三輪加入）────────────────────────
#
# 模組檢查最危險的失敗模式不是「該擋沒擋」，而是**擋錯人**：某個模組的頁面呼叫到
# 一支不接受該模組的 API，畫面上就是一片 403，而後端測試全綠（因為測試多半用
# admin 帳號，admin 直通所有模組檢查）。
#
# 實際發生過兩次，都是在這支測試寫出來的當天被它抓到的：
#   - 簽核佇列（模組 `quotation`）呼叫完工單／出貨單／三種憑證的清單端點，而那些
#     端點當時只收 `case_manage`／財務類模組 → 非管理員的簽核人會開不了簽核佇列
#   - `/api/materials-summary` 被設成只收 `equipment`（複製 `/api/devices` 的設定），
#     但呼叫它的是採購管理頁
#
# 作法：掃前端每個頁面實際呼叫的 API，對照 `sidebar.js::_FILE_MODULE` 的頁面→模組
# 表，再對照後端 `require_any_module()` 宣告的允收集合，三者必須相容。

def _router_module_requirements():
    """{API 前綴: 允收模組集合}，從 `require_any_module(user, (...))` 解析。"""
    out = {}
    for f in glob.glob(os.path.join(ROOT, "backend", "routers", "*.py")):
        src = _read(f)
        for part in re.split(r"\n(?=@router\.)", src)[1:]:
            m = re.match(r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)', part)
            if not m:
                continue
            body = part.split("\n@router.")[0]
            km = re.search(r"require_any_module\(\s*user,\s*\(([^)]*)\)", body)
            if not km:
                continue
            prefix = "/" + "/".join([x for x in m.group(2).split("/") if x][:2])
            out.setdefault(prefix, set()).update(re.findall(r"'([a-z_]+)'", km.group(1)))
    return out


def _page_modules():
    """`sidebar.js::_FILE_MODULE` 的頁面→模組對照（專案自己維護的那一份）。"""
    block = re.search(r"var _FILE_MODULE = \{(.*?)\n  \}", _read(SIDEBAR_JS), re.S).group(1)
    return dict(re.findall(r"'([^']+\.html)':\s*'([a-z_]+)'", block))


def _apis_called_by(path):
    src = _read(path)
    out = set()
    for m in re.finditer(r"""['"`](?:\$\{API\})?(/api/[A-Za-z0-9_\-/{}$.]*)""", src):
        seg = [x for x in m.group(1).split("/") if x][:2]
        if len(seg) >= 2:
            out.add("/" + "/".join(seg))
    for m in re.finditer(r"\$\{API\}/([A-Za-z0-9_\-]+)", src):
        out.add("/api/" + m.group(1))
    return out


def test_module_checks_do_not_block_their_own_pages():
    """每個頁面呼叫的 API，都必須接受該頁所屬的模組。"""
    reqs = _router_module_requirements()
    pages = _page_modules()
    offenders = []
    for f in (glob.glob(os.path.join(ROOT, "frontend", "pages", "*.html"))
              + glob.glob(os.path.join(ROOT, "frontend", "js", "*.js"))):
        base = os.path.basename(f).replace(".js", ".html")
        mod = pages.get(base)
        if not mod:
            continue
        for api in sorted(_apis_called_by(f)):
            keys = reqs.get(api)
            if keys and mod not in keys:
                offenders.append(f"{base}（模組 {mod}）呼叫 {api}，該 API 只收 {sorted(keys)}")
    assert not offenders, (
        "這些頁面會被自己模組的權限檢查擋在門外（畫面一片 403，而後端測試多半用 "
        "admin 帳號所以全綠）：\n  "
        + ("\n  ".join(offenders))
        + "\n修法：把該頁的模組加進那支 API 的允收集合（允收集合的定義是"
        "『所有消費頁面所屬模組的聯集』），而不是把頁面的模組改掉。"
    )

def _sidebar_nav_modules():
    """頁面 →「側欄用哪個模組把它顯示出來」。

    這與 `_FILE_MODULE`（頁面→模組，用於已讀標記）**不是同一份對照**，而且會不一樣：
    例如 `inventory.html` 在 `_FILE_MODULE` 裡對到 `procurement`，但側欄是用
    `cInv = mods.indexOf('inventory')` 決定要不要顯示「庫存管理」。使用者看到的承諾
    是後者——勾了「庫存管理」就該打得開庫存管理頁。
    """
    src = _read(SIDEBAR_JS)
    var_key = dict(re.findall(r"var (c\w+)\s*=\s*mods\.indexOf\('([a-z_]+)'\)", src))
    out = {}
    for href, _label, alts, cond in re.findall(
            r"ni\(\s*pg\('([^']+)'\)\s*,\s*'[^']*'\s*,\s*'([^']*)'\s*,\s*\[([^\]]*)\]\s*,\s*([^,)]+)", src):
        keys = {var_key[v] for v in re.findall(r"c\w+", cond) if v in var_key}
        for page in [href] + re.findall(r"'([^']+)'", alts):
            out.setdefault(page, set()).update(keys)
    return out


def test_sidebar_promise_matches_backend_module_checks():
    """側欄用某個模組把頁面顯示出來，該頁的 API 就必須接受那個模組。

    否則就是「勾了沒用」——使用者看得到選單、點進去整頁 403。`reports` 模組在
    2026-09-13 之前就是這個狀態，只是當時後端**完全沒有**模組檢查所以看不出來；
    補上檢查之後，這種錯配會變成沉默的權限黑洞，必須有測試盯著。
    """
    reqs = _router_module_requirements()
    nav = _sidebar_nav_modules()
    offenders = []
    for f in (glob.glob(os.path.join(ROOT, "frontend", "pages", "*.html"))
              + glob.glob(os.path.join(ROOT, "frontend", "js", "*.js"))):
        base = os.path.basename(f).replace(".js", ".html")
        keys = nav.get(base)
        if not keys:
            continue
        for api in sorted(_apis_called_by(f)):
            need = reqs.get(api)
            if need and not (keys & need):
                offenders.append(
                    f"{base}：側欄用 {sorted(keys)} 顯示它，但 {api} 只收 {sorted(need)}")
    assert not offenders, (
        "側欄承諾的模組打不開該頁要用的 API（勾了沒用）：\n  "
        + ("\n  ".join(offenders))
        + "\n修法：把側欄用的模組加進那支 API 的允收集合。"
    )
