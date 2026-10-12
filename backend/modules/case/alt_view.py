# -*- coding: utf-8 -*-
"""擇一方案報價的『客戶版輸出』資料（M3 T7／T8；T57）：PDF、列印預覽（與之後的回簽頁）共用同一份，經提供者 `case.alt_view` 給 L1 `pdf_gen`。
- **只含客戶看得到的東西**：哪些品項要印、標記字、合計格文字、自動備註句。**不含成本、毛利、管銷、方案表**（那些只在 `alt_options.plan_view`，輸出路徑禁引用）。
- 文字範本取單上快照 `altTexts`（存檔時記下；沒有快照的舊單才回頭讀目前設定）；代入一律用 `re.sub` 單趟取代，**不用 `str.format`**
  （組名是使用者輸入，不能讓它含的大括號被當成範本）；輸出端（PDF／Excel）必須自行跳脫。"""
import re

from modules.case import alt_policy
from modules.case import profit_guard as PG

TAG_PICKED = "擇一"          # 本班固定一種客戶版標記（PLAN §7 Q7：下班再框架化）
TAG_UNPICKED = "未選"
_PLACEHOLDER = re.compile(r"\{(items|group)\}")


def current_texts(conn=None) -> dict:
    """目前設定中心的兩段文字（存檔快照與無快照舊單的後備）。"""
    return {"total_text": str(alt_policy.setting("total_text", conn=conn)),
            "note_template": str(alt_policy.setting("note_template", conn=conn))}


def render_note(template: str, group: str, numbers) -> str:
    vals = {"items": "、".join(str(n) for n in numbers), "group": group}
    return _PLACEHOLDER.sub(lambda m: vals[m.group(1)], template or "")


def _texts(q: dict) -> dict:
    t = q.get("altTexts")
    if isinstance(t, dict) and isinstance(t.get("total_text"), str) and isinstance(t.get("note_template"), str):
        return t
    return current_texts()


def _valid_picks(q: dict, groups: dict) -> dict:
    picks = q.get("altPicks") if isinstance(q.get("altPicks"), dict) else {}
    out = {}
    for g, members in groups.items():
        v = picks.get(g)
        if v is not None and any(str(m.get("id")) == str(v) for m in members):
            out[g] = str(v)
    return out


def view(q: dict) -> dict:
    """沒有任何擇一品項 ⇒ `{"has_alt": False}`（輸出與今天完全相同）。否則：
    `rows`：`{品項id: {"group", "state": picked｜pending｜dropped, "hidden": bool, "tag": 標記字}}`（只含擇一品項）；
    `numbers`：`{品項id: 項次}`（只含會印出的非標題品項，與 pdf_gen 的逐列編號相同）；
    `total_text`：合計兩格要顯示的文字（總開關有開、且仍有未選定的組才有，否則 None）；`notes`：每組一句自動備註。"""
    groups = PG.alt_groups(q)
    if not groups or not PG.alt_active(q):          # 總開關沒開 ⇒ 惰性：輸出與一般報價單相同
        return {"has_alt": False}
    picks = _valid_picks(q, groups)
    show_unpicked = bool(alt_policy.setting("show_unpicked_in_pdf"))
    texts = _texts(q)
    rows = {}
    for g, members in groups.items():
        for m in members:
            mid = str(m.get("id"))
            if g not in picks:
                state, hidden, tag = "pending", False, TAG_PICKED
            elif picks[g] == mid:
                state, hidden, tag = "picked", False, TAG_PICKED
            else:
                state, hidden, tag = "dropped", (not show_unpicked), TAG_UNPICKED
            rows[mid] = {"group": g, "state": state, "hidden": hidden, "tag": tag}
    numbers, n = {}, 0
    for i in (q.get("items") or []):
        if not isinstance(i, dict) or i.get("type") == "header":
            continue
        if rows.get(str(i.get("id")), {}).get("hidden"):
            continue
        n += 1
        numbers[str(i.get("id"))] = n
    notes = []
    for g, members in groups.items():
        ids = [picks[g]] if g in picks else [str(m.get("id")) for m in members]
        nums = [numbers[i] for i in ids if i in numbers]
        notes.append(render_note(texts["note_template"], g, nums))
    unpicked = [g for g in groups if g not in picks]
    return {"has_alt": True, "rows": rows, "numbers": numbers, "notes": notes,
            "total_text": texts["total_text"] if unpicked else None,
            "unpicked_groups": len(unpicked)}
