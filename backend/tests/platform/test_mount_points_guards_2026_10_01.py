# -*- coding: utf-8 -*-
"""建構器方案 B 的機械守門（設計 docs/platform/plans/BUILDER-B-DESIGN.md §7）：

- G-M1 宣告與畫面一致：module.json 宣告的每個掛載點，它的 `page` HTML 必須含 `data-mount-point="<模組key>.<key>"`（宣告了卻沒畫＝
  靜默沒有頁籤）；反之，任何頁面出現的 `data-mount-point` 都必須有宣告（畫了沒宣告＝建構器下拉看不到、使用者以為壞了）。
- G-M2 頁面不得自己呼叫 `/api/platform/mounts`：只能經 `static/mount-tabs.js`（可見性唯一一份在後端 `visible_mounts`，
  頁面自己 fetch 就會長出第二份判斷）。`/api/platform/mount-points`（建構器下拉）只准 `js/module-builder-core.js` 用。
反向控制：兩條規則各以合成輸入驗證「會抓到」（拿掉屬性／多出未宣告的屬性／頁面直接 fetch ⇒ 各自回報）。
"""
import json
import os
import re

from core import paths, source_tree

ATTR = re.compile(r'data-mount-point\s*=\s*"([^"]+)"')
MOUNTS_API = "/api/platform/mounts"
POINTS_API = "/api/platform/mount-points"
#: 允許呼叫掛載 API 的唯一檔案
ALLOWED_MOUNTS_CALLER = "static/mount-tabs.js"
ALLOWED_POINTS_CALLER = "js/module-builder-core.js"


def declared():
    """{點 id: 頁面檔名}（所有已安裝模組的 module.json）。"""
    out = {}
    for d in source_tree.module_dirs():
        mj = os.path.join(d, "module.json")
        if not os.path.isfile(mj):
            continue
        m = json.load(open(mj, encoding="utf-8"))
        for p in m.get("mount_points") or []:
            out["%s.%s" % (m["key"], p["key"])] = p["page"]
    return out


def g_m1_problems(decl, html_of):
    """decl＝{點 id: 頁面檔名}；html_of(頁面檔名)⇒html 或 None；另需 all_pages（頁面檔名⇒html）以找未宣告的屬性。回問題清單。"""
    out = []
    for pid, page in decl.items():
        html = html_of(page)
        if html is None:
            out.append("%s：宣告的頁面 %s 不存在" % (pid, page))
        elif ('data-mount-point="%s"' % pid) not in html:
            out.append("%s：頁面 %s 沒有 data-mount-point=\"%s\"（宣告了卻沒畫）" % (pid, page, pid))
    return out


def g_m1_undeclared(decl, pages):
    out = []
    for name, html in pages.items():
        for pid in ATTR.findall(html):
            if pid not in decl:
                out.append("%s：頁面 %s 畫了 data-mount-point=\"%s\" 但沒有任何 module.json 宣告它" % (pid, name, pid))
    return out


def g_m2_problems(files):
    """files＝{相對路徑: 內容}（頁面與 js）。回違規清單。"""
    out = []
    for rel, text in files.items():
        if MOUNTS_API in text.replace(POINTS_API, "") and not rel.endswith(ALLOWED_MOUNTS_CALLER):
            out.append("%s 直接引用了 %s（只准 %s）" % (rel, MOUNTS_API, ALLOWED_MOUNTS_CALLER))
        if POINTS_API in text and not rel.endswith(ALLOWED_POINTS_CALLER):
            out.append("%s 引用了 %s（只准建構器 %s）" % (rel, POINTS_API, ALLOWED_POINTS_CALLER))
    return out


def _all_pages():
    return {p.name: p.read_text(encoding="utf-8") for p in source_tree.page_files()}


def _frontend_texts():
    root = paths.FRONTEND_DIR
    out = {}
    for sub in ("static", "js"):
        base = os.path.join(root, sub)
        for d, _dirs, fs in os.walk(base):
            if os.sep + "vendor" in d:
                continue
            for f in fs:
                if f.endswith(".js"):
                    p = os.path.join(d, f)
                    out[os.path.relpath(p, root).replace("\\", "/")] = open(p, encoding="utf-8", errors="replace").read()
    for name, html in _all_pages().items():
        out["pages/" + name] = html
    return out


def test_g_m1_every_declared_mount_point_is_drawn_on_its_page_and_every_drawn_one_is_declared():
    decl = declared()
    assert decl, "目前至少要有一個掛載點宣告（daily_tasks.daily-tasks）；沒有 ⇒ 方案 B 沒有首個頁籤"
    pages = _all_pages()
    assert g_m1_problems(decl, lambda n: pages.get(n)) == []
    assert g_m1_undeclared(decl, pages) == []


def test_g_m1_reverse_controls_catch_a_missing_attribute_and_an_undeclared_one():
    decl = {"m.k": "p.html"}
    ok = {"p.html": '<div data-mount-point="m.k"></div>'}
    assert g_m1_problems(decl, ok.get) == [] and g_m1_undeclared(decl, ok) == []                     # 正對照
    assert g_m1_problems(decl, lambda n: '<div></div>') != []                                          # 宣告了沒畫
    assert g_m1_problems(decl, lambda n: None) != []                                                   # 頁面不存在
    assert g_m1_undeclared(decl, {"p.html": '<div data-mount-point="m.other"></div>'}) != []          # 畫了沒宣告


def test_g_m2_pages_never_call_the_mounts_api_directly():
    assert g_m2_problems(_frontend_texts()) == []


def test_g_m2_reverse_controls():
    assert g_m2_problems({"static/mount-tabs.js": "fetch('/api/platform/mounts?point=x')"}) == []      # 正對照：唯一允許的呼叫者
    assert g_m2_problems({"js/module-builder-core.js": "api('GET','/api/platform/mount-points')"}) == []
    assert g_m2_problems({"pages/x.html": "fetch('/api/platform/mounts?point=x')"}) != []              # 頁面自己 fetch
    assert g_m2_problems({"static/other.js": "fetch('/api/platform/mount-points')"}) != []            # 其他檔呼叫建構器端點
    assert g_m2_problems({"pages/y.html": "fetch('/api/platform/mount-points')"}) != []
