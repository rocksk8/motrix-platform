# -*- coding: utf-8 -*-
"""選單模組徽章的三份對照必須一致。

```
sidebar.js  _MOD_BADGES          哪個模組有徽章元素
notif.js    modBadge             數字回來之後要填哪個元素
system.py   _MODULE_ACTION_PREFIXES   後端怎麼數
```
☠️ 少一份的症狀不是錯誤，是**那個模組的紅點永遠不亮**（`tender_radar`
   只在 sidebar 有 ⇒ 元素存在、數字從來不來）。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _js_object_keys(src, name):
    m = re.search(name + r"\s*=\s*\{(.*?)\n\s*\}", src, re.S)
    assert m, name + " 找不到"
    return set(re.findall(r"^\s*([a-z_]+)\s*:", m.group(1), re.M))


def test_sidebar_and_notif_badge_maps_have_the_same_modules():
    side = _js_object_keys((ROOT / "frontend/static/sidebar.js").read_text(encoding="utf-8"), r"var _MOD_BADGES")
    notif = _js_object_keys((ROOT / "frontend/static/notif.js").read_text(encoding="utf-8"), r"var modBadge")
    assert side, "sidebar.js 的 _MOD_BADGES 解析出空集合（正對照）"
    assert "tender_radar" in side
    assert side == notif, {"只在 sidebar": side - notif, "只在 notif": notif - side}


def test_every_badged_module_is_counted_by_the_backend():
    from routers.system import _MODULE_ACTION_PREFIXES
    side = _js_object_keys((ROOT / "frontend/static/sidebar.js").read_text(encoding="utf-8"), r"var _MOD_BADGES")
    missing = side - set(_MODULE_ACTION_PREFIXES)
    assert not missing, "有徽章但後端不數：%s" % sorted(missing)
