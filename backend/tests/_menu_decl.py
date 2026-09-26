"""選單宣告的靜態讀法（C4 起 sidebar.js 不再寫死選單；宣告在 core/menu_l1.json 與各模組 module.json pages[].menu）。

測試要問「某個入口在不在、在哪一組、權限是什麼、排在誰後面」時讀這裡——不要再解析 sidebar.js 的原始碼。
讀的是**安裝目錄裡所有模組**的宣告（不看載入狀態）：這是「程式宣告了什麼」，不是「這次啟動載入了什麼」。
"""


def declared_items():
    """⇒ 依渲染順序的扁平清單：每項 {href, label, perm, active, badge, extra_badge, module, group, group_label}。"""
    from core import loader
    from core import menu as M
    from core import pages as P
    manifests = {k: v[0] for k, v in P.read_manifests(loader.MODULES_DIR).items()}
    out = []
    for g in M.declaration(M.load_l1(), M.module_items(manifests)):
        for it in g["items"]:
            out.append(dict(it, group=g["key"], group_label=g["label"]))
    assert len(out) > 30, "正對照：宣告讀出來只有 %d 項（讀法壞了，不是選單少了）" % len(out)
    return out


def item(href):
    """href 的那一項；沒有 ⇒ None。同一個 href 宣告兩次由 core.menu.validate 擋。"""
    return next((it for it in declared_items() if it["href"] == href), None)
