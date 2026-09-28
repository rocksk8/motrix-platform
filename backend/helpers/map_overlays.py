# -*- coding: utf-8 -*-
"""L1 地圖覆蓋層（串接點 IP-101 `map.overlay`；docs/platform/LODGING-NEARBY.md §3.6.1，D 稽核 LG-M1／LG2-S1～S3）。

[單位] helper:map_overlays    [層] L1
[公開介面] OVERLAY_KEY_RE, SCRIPT_NAME_RE, URL_PREFIX, declared_overlays, script_path
[不變式] 覆蓋層腳本網址只由 L1 依**已載入**模組 module.json 的 `map_overlays` 宣告組出（同源 `/map-overlays/<模組>/<檔名>`）；
    提供者不回傳任何網址；宣告不合格式、檔案不在模組的 `pages/` 底下 ⇒ 不列、記 ERROR；模組未載入 ⇒ 不列、腳本 404
[契約題] tests/test_map_overlay_contract_2026_09_28.py, tests/test_e2e_map_overlay_contract_2026_09_28.py

module.json 宣告：
    "map_overlays": [{"key": "<覆蓋層 key>", "label": "<按鈕文字>", "script": "<檔名>.js"}]
    - key：`^[a-z][a-z0-9_-]{0,39}$`，全系統唯一（撞名 ⇒ 後到的不列）
    - script：只能是檔名 `^[a-z0-9][a-z0-9-]*\\.js$`，實體檔在 `modules/<模組>/pages/<檔名>`
前端契約（L2 腳本只准用這些）：`frontend/static/map-overlay.js` 的 `window.MotrixMapOverlay.register(key, {mount(api), unmount()})`。
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

OVERLAY_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
SCRIPT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.js$")
_LABEL_MAX = 20
URL_PREFIX = "/map-overlays/"


def _modules_dir():
    from core import loader
    return loader.MODULES_DIR


def _file_of(module_key, script):
    base = os.path.realpath(os.path.join(_modules_dir(), module_key, "pages"))
    path = os.path.realpath(os.path.join(base, script))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


def declared_overlays():
    """已載入模組宣告的覆蓋層 ⇒ [{key, label, module, scriptUrl}]（依模組 key、宣告順序）。"""
    from core import registry
    out, seen = [], set()
    for lm in sorted(registry.loaded(), key=lambda m: m.key):
        decl = (lm.manifest or {}).get("map_overlays")
        if decl is None:
            continue
        if not isinstance(decl, list):
            logger.error("module %s: map_overlays must be a list", lm.key)
            continue
        for d in decl:
            key = d.get("key") if isinstance(d, dict) else None
            label = d.get("label") if isinstance(d, dict) else None
            script = d.get("script") if isinstance(d, dict) else None
            if not (isinstance(key, str) and OVERLAY_KEY_RE.match(key)
                    and isinstance(label, str) and 0 < len(label.strip()) <= _LABEL_MAX
                    and isinstance(script, str) and SCRIPT_NAME_RE.match(script)):
                logger.error("module %s: invalid map_overlays entry %r (not listed)", lm.key, d)
                continue
            if key in seen:
                logger.error("module %s: map overlay key %r already used (not listed)", lm.key, key)
                continue
            if _file_of(lm.key, script) is None:
                logger.error("module %s: map overlay script %r not found under pages/ (not listed)", lm.key, script)
                continue
            seen.add(key)
            out.append({"key": key, "label": label.strip(), "module": lm.key,
                        "scriptUrl": "%s%s/%s" % (URL_PREFIX, lm.key, script)})
    return out


def script_path(module_key, script):
    """`/map-overlays/<模組>/<檔名>` ⇒ 實體檔；不是已宣告、已載入、存在的覆蓋層腳本 ⇒ None（呼叫端回 404）。"""
    for o in declared_overlays():
        if o["module"] == module_key and o["scriptUrl"] == "%s%s/%s" % (URL_PREFIX, module_key, script):
            return _file_of(module_key, script)
    return None
