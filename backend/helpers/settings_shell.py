# -*- coding: utf-8 -*-
"""設定中心外框的唯讀資料（S2；SPEC §14）：總覽首頁、最近變更、全域搜尋索引。**只讀**——寫入仍走 `settings_registry.publish()`。

- `overview(conn)`：頁面清單（分類／白話名／與預設不同 N／待生效 N／內含高風險）＋三張統計卡＋最近 5 筆＋「與預設不同」跨群組清單。
- `recent(conn, limit, high_only)`：最近變更（`config_ledger`）；整份文件（json）與 external 群組只給摘要，不給原始內容。
- `search_index()`：欄位級搜尋用的靜態資料（中文名稱、小字代碼、說明、選項標籤、群組名）；前端比對，不含任何目前值。
hidden 群組一律不出現（連名稱都不洩漏）；planned 群組只有名稱＋狀態；external 群組不計入。
"""
from helpers import config_ledger as ledger
from helpers import settings_pages as sp
from helpers import settings_registry as sr

_HIGH = ("money", "legal", "security")
_STATE_TEXT = {"immediate": "已生效", "activated": "已生效", "pending": "等待生效", "cancelled": "已撤銷", "superseded": "被取代"}


def _visible(page, regs):
    """頁面裡看得見的群組 `[(group, status)]`：未登錄／external／hidden 排除。"""
    out = []
    for g in page["groups"]:
        m = regs.get(g)
        if m is None or m.get("external"):
            continue
        st = sr.group_status(g)
        if st != "hidden":
            out.append((g, st))
    return out


def _is_high(defs):
    return any(f.risk in _HIGH for f in defs.values())


def _shown(f, v):
    return sr.show_value(f, v)


def overview(conn):
    regs = sr.groups()
    pend_by_group = {}
    for r in ledger.pending(conn, "setting"):
        if r["key"] in regs and sr.group_status(r["key"]) == "open" and not regs[r["key"]].get("external"):
            pend_by_group[r["key"]] = pend_by_group.get(r["key"], 0) + 1
    pages, diff_items, high_groups = [], [], 0
    for p in sp.pages():
        if p.get("standalone"):
            pages.append({"id": p["id"], "plain": p["plain"], "category": p["category"], "groups": [], "standalone": True, "href": p["href"],
                          "status": "open", "differs": 0, "pending": 0, "highRisk": False, "privacy": False})
            continue
        vis = _visible(p, regs)
        if not vis:
            continue                                                              # 全 hidden：整頁不存在
        differs = pending = 0
        high = False
        for g, st in vis:
            if st != "open":
                continue
            defs = sr.field_defs(g)
            vals = sr.get_group(g, conn=conn)
            pending += pend_by_group.get(g, 0)
            if _is_high(defs):
                high = True
                high_groups += 1
            for k, f in defs.items():
                if not sr._same_value(vals[k], f.default):
                    differs += 1
                    diff_items.append({"page": p["id"], "group": g, "groupPlain": sp.group_plain(g), "field": k, "label": f.label,
                                       "value": _shown(f, vals[k]), "default": _shown(f, f.default), "risk": f.risk})
        status = "open" if any(st == "open" for _g, st in vis) else "planned"
        pages.append({"id": p["id"], "plain": p["plain"], "category": p["category"], "groups": [g for g, _s in vis], "standalone": False, "href": "",
                      "status": status, "differs": differs, "pending": pending, "highRisk": high, "privacy": sp.privacy_flag(p)})
    return {"categories": list(sp.CATEGORIES), "pages": pages,
            "stats": {"differs": len(diff_items), "pending": sum(pend_by_group.values()), "highRiskGroups": high_groups},
            "differsItems": diff_items, "recent": recent(conn, 5)}


def recent(conn, limit=50, high_only=False):
    """最近變更（新→舊）。`high_only`＝只看 money／legal／security 欄位。帳本裡欄位已不存在的舊紀錄、hidden／planned 群組的紀錄會被略過；
    掃描上限是帳本最近 1000 筆，被略過的很多時，可見筆數可能少於 limit。"""
    regs = sr.groups()
    limit = max(1, min(int(limit), 200))
    out = []
    for r in ledger.history(conn, "setting", None, limit=1000):
        g = r["key"]
        m = regs.get(g)
        if m is None or sr.group_status(g) != "open":                             # hidden 不洩漏；planned 沒有變更可言
            continue
        defs = sr.field_defs(g)
        f = defs.get(r["field"])
        if f is None:
            continue
        if high_only and f.risk not in _HIGH:
            continue
        hide = bool(m.get("external") or f.type == "json")
        out.append({"id": r["id"], "at": r["at"], "actor": r.get("actor_display") or r["actor"], "group": g, "groupPlain": sp.group_plain(g),
                    "page": sp.page_of(g), "field": r["field"], "label": f.label, "reason": r.get("reason") or "", "risk": f.risk,
                    "state": r["state"], "stateText": _STATE_TEXT.get(r["state"], r["state"]), "effectiveAt": r.get("effective_at") or "",
                    "old": None if hide else _shown(f, r["old"]) if r["old"] is not None else "", "new": None if hide else _shown(f, r["new"]),
                    "summary": sr._summary_of(f, r["old"], r["new"]) if hide else []})
        if len(out) >= limit:
            break
    return out


def search_index():
    """欄位級搜尋索引（不含任何值）。獨立頁以頁名＋關鍵字出現一筆。"""
    regs = sr.groups()
    items = []
    for p in sp.pages():
        if p.get("standalone"):
            items.append({"kind": "page", "page": p["id"], "pagePlain": p["plain"], "category": p["category"], "href": p["href"],
                          "text": " ".join([p["plain"]] + list(p.get("keywords") or []))})
            continue
        for g, st in _visible(p, regs):
            m = regs[g]
            meta = sp.GROUPS.get(g, {})
            items.append({"kind": "group", "page": p["id"], "pagePlain": p["plain"], "category": p["category"], "group": g,
                          "groupPlain": sp.group_plain(g), "text": " ".join(x for x in (sp.group_plain(g), meta.get("currentName", ""), m["label"], p["plain"]) if x)})
            if st != "open":
                continue
            for k, f in sr.field_defs(g).items():
                items.append({"kind": "field", "page": p["id"], "pagePlain": p["plain"], "category": p["category"], "group": g,
                              "groupPlain": sp.group_plain(g), "field": k, "label": f.label, "question": f.question,
                              "text": " ".join(x for x in [f.label, f.question, f.help, f.when, k] + [c[1] for c in f.choices] if x)})
    return items
