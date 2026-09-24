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


def test_notif_reads_the_single_badge_map_from_the_sidebar():
    """2026-09-24（B7）：原本 notif.js 自己抄一份 `modBadge`（`tender_radar` 就是少在那一份）。
    ⇒ 改成只有 sidebar.js 一份、以 `window.MOTRIX_MOD_BADGES` 公開，notif.js 讀它。
    📌 更正留著：這一題原本驗「兩份相同」；兩份變一份之後，改驗「不可以又抄回一份」。"""
    side_src = (ROOT / "frontend/static/sidebar.js").read_text(encoding="utf-8")
    notif_src = (ROOT / "frontend/static/notif.js").read_text(encoding="utf-8")
    side = _js_object_keys(side_src, r"var _MOD_BADGES")
    assert side, "sidebar.js 的 _MOD_BADGES 解析出空集合（正對照）"
    assert "tender_radar" in side
    assert "window.MOTRIX_MOD_BADGES = _MOD_BADGES" in side_src
    assert "window.MOTRIX_MOD_BADGES" in notif_src
    assert not re.search(r"var\s+modBadge\s*=\s*\{", notif_src), "notif.js 又抄回了一份徽章對照表"


def test_every_badged_module_is_counted_by_the_backend():
    from routers.system import _MODULE_ACTION_PREFIXES
    side = _js_object_keys((ROOT / "frontend/static/sidebar.js").read_text(encoding="utf-8"), r"var _MOD_BADGES")
    missing = side - set(_MODULE_ACTION_PREFIXES)
    assert not missing, "有徽章但後端不數：%s" % sorted(missing)
