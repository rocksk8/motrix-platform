# -*- coding: utf-8 -*-
"""頁面對照與提供（階段 C／C1，docs/platform/STAGE-C-DESIGN.md §3）：`/pages/<檔名>` ⇒ 實體檔、提示頁或 404。

[單位] plat:pages    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] L1_PAGES_FILE, NOTICE, PAGE_NAME, PageConflict, build_page_map, check_and_register, collect, load_l1_pages,
    lookup, notice_html, notice_kind, page_response, read_manifests, resolve, valid_name
[不變式] 對外 URL 一律 /pages/x.html；模組沒載入 ⇒ 404＋提示頁，頁面本體不送出；頁名比對不分大小寫；撞名或宣告 L1 頁面 ⇒ 該模組 failed
[契約題] tests/platform/test_core_pages.py
[注意] 在 mount_modules 之前 check_and_register、在 StaticFiles 之前註冊 /pages 路由（順序有守門）

對外 URL 一律 `/pages/x.html`（裁示 D1）；實體檔可以在
  - `frontend/pages/`（L1 頁面，以及還沒搬家的模組頁面）
  - `modules/<key>/pages/`（已搬家的模組頁面）
模組頁面以 module.json `pages[].path` 宣告，屬於哪個模組由宣告決定，不由實體位置決定。

提供規則（page_response）：
  - 屬於某模組、該模組已載入 ⇒ 實體檔
  - 屬於某模組、沒有載入 ⇒ **HTTP 404＋伺服器產生的提示頁**（停用／未授權／載入失敗／未安裝；裁示 D2 採選項 A，
    與 STATES-PLATFORM P-FE-03 並存：HTTP 層與端點一致，使用者看到的是原因而不是「網址錯誤」）
  - 不屬於任何模組 ⇒ `frontend/pages/` 有這個檔就提供，否則 None（呼叫端回一般 404）

頁面衝突（collect）比照 STATES-PLATFORM P-LD-07 路由衝突：依 key 排序先到先得，後到的模組**整個**拒絕
（check_and_register 把它標成 failed、不掛），記 ERROR；其他模組照常。不讓整台起不來（可販售產品）。
"""
import html
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: 只接受單層檔名：擋 `..`、子目錄、反斜線與磁碟代號
PAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.html$")

#: 沒有載入的模組的提示（與 frontend/static/sidebar.js `_MODULE_NOTICE` 同一組文案；前端那份只在伺服器沒接手時當後備）
NOTICE = {
    "disabled":   ("此模組目前已停用", "請洽最高管理者於「系統 → 模組管理」啟用，重新啟動服務後生效。"),
    "unlicensed": ("此模組未授權", "目前的授權不包含這個模組，請聯絡供應商取得包含此模組的授權。"),
    "failed":     ("此模組載入失敗", "請洽系統管理者於「系統 → 模組管理」查看原因。"),
    "missing":    ("此模組未安裝", "這個安裝包沒有包含這個模組。"),
}


class PageConflict(Exception):
    """頁面衝突（嚴格模式 build_page_map 用；開發樹與守門測試要直接紅）。"""


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(PAGE_NAME.match(name)) and ".." not in name


#: L1 頁面清單（模組不可以宣告；稽核 D P-M1）。與 docs/platform/modules.json 的 L1 頁面單位一致（守門 test_core_pages）。
L1_PAGES_FILE = Path(__file__).with_name("l1_pages.json")


def load_l1_pages(path=None):
    """L1 頁面檔名集合（小寫）；讀不到 ⇒ 空集合（呼叫端的守門題會紅，產品不因此起不來）。"""
    try:
        return {n.lower() for n in json.loads(Path(path or L1_PAGES_FILE).read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        logger.error("讀不到 L1 頁面清單 %s ⇒ 模組宣告 L1 頁面將無法擋下", path or L1_PAGES_FILE)
        return set()


def collect(manifests, l1_dir, l1_pages=None):
    """{模組key: (manifest, 模組資料夾)} ⇒ (page_map {檔名: (模組key, 實體路徑)}, refused {模組key: 原因}, missing {模組key: [檔名]})。

    **衝突**（比照 P-LD-07）⇒ 整個模組列進 refused：
    - 宣告了 L1 頁面（l1_pages；None ⇒ 讀 core/l1_pages.json）——稽核 D P-M1：模組把 login.html 宣告成自己的，
      停用那個模組登入頁就 404
    - 宣告的檔名不合 PAGE_NAME
    - 檔名（不分大小寫）已被先到的模組宣告
    - 模組資料夾與 frontend/pages 各有一份（兩份會漂移）
    被拒模組的其他頁面仍記在它名下（它沒有載入 ⇒ 回提示頁），不可以因為被拒就落到 frontend/pages 以 200 提供。
    **宣告了卻兩處都沒有** ⇒ 只列進 missing（不是衝突：沒有東西會被錯誤地提供；該頁一般 404），不拒絕模組。
    〔2026-09-26 更正：原本列為衝突而拒絕整個模組 ⇒ 只宣告頁面、不建檔的合成模組（child_module_gate）被改記 failed，
     蓋掉了它應有的 disabled／unlicensed 狀態（全量抓到）〕
    """
    l1_dir = Path(l1_dir)
    l1 = load_l1_pages() if l1_pages is None else {n.lower() for n in l1_pages}
    out, refused, missing = {}, {}, {}
    for key in sorted(manifests):
        manifest, mod_dir = manifests[key]
        problems, mine = [], []
        for p in (manifest or {}).get("pages") or []:
            name = p.get("path") if isinstance(p, dict) else None
            if not valid_name(name):
                problems.append("宣告的頁面檔名不合法：%r" % (name,))
                continue
            if name.lower() in l1:
                problems.append("頁面 %s 是 L1 頁面，模組不可以宣告" % name)
                continue
            same = [n for n in out if n.lower() == name.lower()]
            if same:
                problems.append("頁面 %s 已由模組 %s 提供" % (name, out[same[0]][0]))
                continue
            moved = Path(mod_dir) / "pages" / name
            legacy = l1_dir / name
            if moved.is_file() and legacy.is_file():
                problems.append("頁面 %s 有兩份：%s 與 %s（搬家後要刪舊的）" % (name, moved, legacy))
                mine.append((name, moved))
            elif moved.is_file():
                mine.append((name, moved))
            elif legacy.is_file():
                mine.append((name, legacy))
            else:
                missing.setdefault(key, []).append(name)
        for name, path in mine:
            out[name] = (key, path)
        if problems:
            refused[key] = "頁面衝突：" + "；".join(problems)
    return out, refused, missing


def build_page_map(manifests, l1_dir):
    """嚴格版：有任何衝突或宣告了不存在的頁面 ⇒ PageConflict（開發樹、守門測試、`source_tree.page_file` 用）。"""
    pm, refused, missing = collect(manifests, l1_dir)
    probs = ["模組 %s：%s" % kv for kv in sorted(refused.items())]
    probs += ["模組 %s 宣告的頁面不存在：%s" % (k, v) for k, v in sorted(missing.items())]
    if probs:
        raise PageConflict("；".join(probs))
    return pm


def lookup(name, page_map):
    """檔名 ⇒ (模組key, 實體路徑) 或 None。
    ☠️ 不分大小寫比對：Windows 檔案系統不分大小寫 ⇒ 請求 `Tender-Radar.html` 若只做精確比對，
       會落到 frontend/pages 分支而讀到沒有載入的模組的舊檔。"""
    return next((v for k, v in page_map.items() if k.lower() == name.lower()), None)


def resolve(name, page_map, enabled, l1_dir):
    """檔名 ⇒ 要提供的實體路徑；不提供 ⇒ None。enabled：已載入的模組 key 集合（或支援 `in` 的物件）。"""
    if not valid_name(name):
        return None
    hit = lookup(name, page_map)
    if hit is not None:
        key, path = hit
        return path if key in enabled else None
    legacy = Path(l1_dir) / name
    return legacy if legacy.is_file() else None


def notice_kind(state):
    """狀態表的一筆（或 None＝不在狀態表＝不在安裝包）⇒ NOTICE 的鍵。"""
    if not state:
        return "missing"
    kind = state.get("state")
    return kind if kind in NOTICE and kind != "missing" else "failed"


def notice_html(module_name, kind):
    title, body = NOTICE.get(kind) or NOTICE["failed"]
    return ('<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title></head><body style="font-family:sans-serif;background:#F9FAFB;margin:0">'
            '<div data-testid="module-unavailable" data-state="%s" style="max-width:640px;margin:48px auto;'
            'padding:24px 28px;border:1px solid #E5E7EB;border-radius:10px;background:#fff;line-height:1.7">'
            '<div style="font-size:12px;color:#6B7280">%s</div>'
            '<h2 style="margin:4px 0 8px;font-size:20px">%s</h2>'
            '<p style="margin:0 0 16px;color:#4B5563">%s</p>'
            '<a class="btn" href="/">回首頁</a></div></body></html>'
            % (html.escape(title), html.escape(kind), html.escape(module_name), html.escape(title), html.escape(body)))


def page_response(name, page_map, l1_dir, is_loaded, state_of):
    """`/pages/<name>` 要回什麼（每個請求現查模組狀態）：
    ("file", 路徑) ／ ("notice", html, kind) ／ None（一般 404）。
    is_loaded(key) -> bool；state_of(key) -> 狀態表的一筆或 None。"""
    if not valid_name(name):
        return None
    hit = lookup(name, page_map)
    if hit is None:
        legacy = Path(l1_dir) / name
        return ("file", legacy) if legacy.is_file() else None
    key, path = hit
    if is_loaded(key):
        return ("file", path)
    st = state_of(key)
    kind = notice_kind(st)
    return ("notice", notice_html((st or {}).get("name") or key, kind), kind)


def read_manifests(modules_dir):
    """安裝目錄裡每個有 module.json 的資料夾 ⇒ {key: (manifest, 資料夾)}；讀不出來的略過（loader 已把它標成 failed）。"""
    out = {}
    if not modules_dir or not os.path.isdir(modules_dir):
        return out
    for name in sorted(os.listdir(modules_dir)):
        folder = Path(modules_dir) / name
        try:
            out[name] = (json.loads((folder / "module.json").read_text(encoding="utf-8")), folder)
        except (OSError, ValueError):
            continue
    return out


def check_and_register(modules_dir, l1_dir):
    """啟動時（mount_modules **之前**）：收集頁面；**已載入**的衝突模組比照 P-LD-07 改記 failed、不掛。回傳 page_map。

    沒有載入的（停用／未授權／失敗）維持原狀態、只記 ERROR：它本來就不掛，改記 failed 會蓋掉管理者看得到的
    停用／未授權原因（〔2026-09-26 更正：原本一律改記 failed，全量的 child_module_gate 抓到〕）。
    宣告了不存在的頁面 ⇒ 記 WARNING，不動模組狀態。"""
    from core import registry
    manifests = read_manifests(modules_dir)
    pm, refused, missing = collect(manifests, l1_dir)
    for key, reason in refused.items():
        if registry.is_loaded(key):
            registry.unload(key, reason)
            logger.error("模組 %s 未載入：%s", key, reason)
        else:
            logger.error("模組 %s（目前未載入）%s", key, reason)
    for key, names in missing.items():
        logger.warning("模組 %s 宣告的頁面不存在：%s", key, "、".join(names))
    return pm
