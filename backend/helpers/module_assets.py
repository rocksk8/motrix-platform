# -*- coding: utf-8 -*-
"""L1 模組自有前端 JS（STAGE-C-DESIGN §3；模組資產 POC）。

[單位] helper:module_assets    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] JsAssetLookup, asset_path, served_assets, undeclared_files
[不變式] 模組自有 JS 的**網址不變**（`/js/<檔名>.js`），只有實體檔住進 `modules/<key>/js/`；只提供
    「模組已載入（registry.loaded()）、在 module.json `assets` 宣告、realpath 落在該模組 `js/` 底下的一般檔」；
    其餘（模組停用／未授權／載入失敗、沒宣告、缺檔、路徑跑出 `js/`）一律不由本模組提供——
    `/js` 掛載退回 `frontend/js`（同一份網址在乾淨的樹上就是 404）。
    宣告了卻缺檔 ⇒ 記 ERROR、該檔不提供、**模組仍 loaded**（不擋載入；擋在出貨前：module_update check）。
    兩個已載入模組宣告同一個檔名 ⇒ 依模組 key 排序，後到的不提供並記 ERROR（同網址只能有一個來源）。
[契約題] tests/platform/test_module_assets_contract_2026_11_08.py

module.json 宣告：
    "assets": [{"path": "js/<檔名>.js"}]        形狀由 core.loader.declared_assets 在 import 之前驗
"""
import logging
import os
import re

from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.js\Z")
_logged = set()          # 同一個問題只記一次 ERROR（/js 每個請求都會查表，不可以洗版）


def _error(key, msg, *args):
    if (key, msg % args) not in _logged:
        _logged.add((key, msg % args))
        logger.error("module %s: " + msg, key, *args)


def _modules_dir():
    from core import loader
    return loader.MODULES_DIR


def _real_file(module_key, rel_path):
    """`modules/<key>/<rel_path>` 的真實路徑；不是 `modules/<key>/js/` 底下的一般檔 ⇒ None。"""
    base = os.path.realpath(os.path.join(_modules_dir(), module_key, "js"))
    path = os.path.realpath(os.path.join(_modules_dir(), module_key, rel_path))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


def served_assets():
    """已載入模組提供的 JS ⇒ {檔名: 實體路徑}（依模組 key 排序；撞名、缺檔、宣告格式不合者不列並記 ERROR）。"""
    from core import loader, registry
    out, owner = {}, {}
    for lm in sorted(registry.loaded(), key=lambda m: m.key):
        try:
            paths = loader.declared_assets(lm.manifest or {})
        except ValueError as e:                      # 載入器已擋過；防禦：registry 被別處塞了壞的 manifest
            _error(lm.key, "invalid assets declaration (%s)", e)
            continue
        for rel_path in paths:
            name = rel_path.split("/", 1)[1]
            if name in out:
                _error(lm.key, "asset %r already provided by module %s (not served)", name, owner[name])
                continue
            real = _real_file(lm.key, rel_path)
            if real is None:
                _error(lm.key, "declared asset %r not found under js/ (not served)", rel_path)
                continue
            out[name] = real
            owner[name] = lm.key
    return out


def asset_path(name):
    """`/js/<name>` ⇒ 已載入模組提供的實體檔；不是 ⇒ None（呼叫端退回 frontend/js）。"""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    return served_assets().get(name)


def undeclared_files(module_key):
    """`modules/<key>/js/` 底下有、但 module.json 沒宣告的 .js 檔名（出貨前檢查與契約測試用；不影響執行期）。"""
    import json
    from core import loader
    folder = os.path.join(_modules_dir(), module_key)
    with open(os.path.join(folder, "module.json"), encoding="utf-8-sig") as f:
        declared = {p.split("/", 1)[1] for p in loader.declared_assets(json.load(f))}
    jd = os.path.join(folder, "js")
    have = {n for n in (os.listdir(jd) if os.path.isdir(jd) else []) if n.endswith(".js")}
    return sorted(have - declared)


class JsAssetLookup(StaticFiles):
    """掛在 `/js`（directory＝frontend/js）：先看已載入模組提供的 JS，沒有才走一般 frontend/js 查找。

    只在檔名完全符合 `^[A-Za-z0-9][A-Za-z0-9_.-]*\\.js$`（單一層、無路徑分隔）時才查模組表；
    實體路徑只來自 served_assets()（已核對在模組 js/ 底下），請求字串從不拼進路徑。
    """

    def lookup_path(self, path):
        real = asset_path(path)
        if real is not None:
            return real, os.stat(real)
        return super().lookup_path(path)
