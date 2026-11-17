# -*- coding: utf-8 -*-
"""擇一方案報價的『客戶版輸出』資料（M3 T7／T8；T57）：PDF、列印預覽（與之後的回簽頁）共用同一份，經提供者 `case.alt_view` 給 L1 `pdf_gen`。
- **只含客戶看得到的東西**：哪些品項要印、標記字、合計格文字、自動備註句、各方案金額（`plans`，T88：未選完時取代合計框）。**不含成本、毛利、管銷、內部方案比較**（那些只在 `alt_options.plan_view`，輸出路徑禁引用；`plans` 只用 `server_totals`／`item_amount`）。
- 文字範本取單上快照 `altTexts`（存檔時記下；沒有快照的舊單才回頭讀目前設定）；代入一律用 `re.sub` 單趟取代，**不用 `str.format`**
  （組名是使用者輸入，不能讓它含的大括號被當成範本）；輸出端（PDF／Excel）必須自行跳脫。"""
import itertools
import logging
import re

from modules.case import alt_policy
from modules.case import profit_guard as PG

TAG_PICKED = "擇一"          # 本班固定一種客戶版標記（PLAN §7 Q7：下班再框架化）
TAG_UNPICKED = "未選"
_PLACEHOLDER = re.compile(r"\{(items|group)\}")
logger = logging.getLogger(__name__)
PLAN_HINT ="請擇一方案，回簽時勾選"       # 方案表標題下的說明（接在設定中心 total_text 後面）
_CN_NUM = "一二三四五六七八九十"
_NAME_MAX = 16                              # 方案名稱裡每個品名最多幾個字
_COMBO_FALLBACK = 24                        # 設定 combo_view_max 讀不到時的後備（＝設定預設）
_COMBO_HARD_CAP = 200                       # 與設定 combo_view_max 的上限相同


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


def _adj(q: dict, key: str) -> float:
    v = q.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _short_name(i: dict) -> str:
    """方案名稱用的品名：說明（沒有就品牌）第一行，超過 _NAME_MAX 字截斷。"""
    for k in ("description", "brand"):
        v = i.get(k)
        if isinstance(v, str) and v.strip():
            line = v.strip().splitlines()[0].strip()
            return line if len(line) <= _NAME_MAX else line[:_NAME_MAX] + "…"
    return ""


def _combo_limit() -> int:
    try:
        n = int(alt_policy.setting("combo_view_max"))
    except Exception:
        n = _COMBO_FALLBACK
    return max(1, min(n, _COMBO_HARD_CAP))


def _plan_no(n: int) -> str:
    return "方案" + (_CN_NUM[n - 1] if 1 <= n <= len(_CN_NUM) else str(n))


def plans(q: dict, groups: dict, picks: dict, numbers: dict) -> dict:
    """**客戶版**『各方案金額』（只在還有未選定的組時有；全選定 ⇒ 呼叫端不呼叫）。**只用 `PG.server_totals`／`item_amount`，不碰成本、毛利**
    （輸出路徑禁引用內部方案比較）。已選定的組視為共同品項；只對尚未選定的組展開：
    - 組合數 ≤ 設定 `combo_view_max`（預設 24，硬頂 200）⇒ `mode="combos"`：每種搭配一列，金額用同一支 `server_totals` 算
      （＝回簽選定後的金額，折讓／運費／稅別規則完全相同）；
    - 超過 ⇒ `mode="groups"`：每組每個選項只列自己的未稅金額，另附共同品項。
    `common`＝`{"amount", "numbers"}`（沒有共同品項 ⇒ None）。"""
    unpicked = [g for g in groups if g not in picks]
    base = {g: picks[g] for g in picks}
    common_items = [i for i in PG.counted_items(q, base) if i.get("type") != "header"]
    common = ({"amount": sum(PG.item_amount(i) for i in common_items),
               "numbers": [numbers[str(i.get("id"))] for i in common_items if str(i.get("id")) in numbers]}
              if common_items else None)
    out = {"hint": PLAN_HINT, "common": common, "freight": PG._clean(_adj(q, "freight")), "discount": PG._clean(_adj(q, "discount")),
           "show_pretax": bool(_adj(q, "freight") or _adj(q, "discount"))}
    count = 1
    for g in unpicked:
        count *= len(groups[g])
    stored = q.get("tot") if isinstance(q.get("tot"), dict) else None
    if count <= _combo_limit():
        rows = []
        for n, combo in enumerate(itertools.product(*[groups[g] for g in unpicked]), 1):
            p = dict(base)                          # 守門禁用 `**` 傳參數：逐組明列
            for g, m in zip(unpicked, combo):
                p[g] = str(m.get("id"))
            t = PG.server_totals(dict(q, altPicks=p), stored)
            nums = "＋".join(str(numbers[str(m.get("id"))]) for m in combo if str(m.get("id")) in numbers)
            names = "＋".join(x for x in (_short_name(m) for m in combo) if x)
            rows.append({"no": _plan_no(n), "numbers": nums, "name": names,
                         "subtotal": t["subtotal"], "pretax": t["pretax"], "tax": t["tax"], "total": t["total"]})
        out.update(mode="combos", rows=rows)
    else:
        out.update(mode="groups", groups=[
            {"group": g, "options": [{"number": numbers.get(str(m.get("id"))), "name": _short_name(m), "amount": PG.item_amount(m)}
                                     for m in groups[g]]} for g in unpicked])
    return out


def _safe_plans(q: dict, groups: dict, picks: dict, numbers: dict):
    """各方案金額算不出來（資料怪、設定讀取出錯…）不能讓整份 PDF／預覽壞掉：記一筆 log、回 None ⇒ pdf_gen 退回原合計框。"""
    try:
        return plans(q, groups, picks, numbers)
    except Exception:
        logger.exception("alt_view.plans failed; falling back to the plain totals box")
        return None


def view(q: dict) -> dict:
    """沒有任何擇一品項 ⇒ `{"has_alt": False}`（輸出與今天完全相同）。否則：
    `rows`：`{品項id: {"group", "state": picked｜pending｜dropped, "hidden": bool, "tag": 標記字}}`（只含擇一品項）；
    `numbers`：`{品項id: 項次}`（只含會印出的非標題品項，與 pdf_gen 的逐列編號相同）；
    `total_text`：合計兩格要顯示的文字（總開關有開、且仍有未選定的組才有，否則 None）；`notes`：每組一句自動備註；
    `plans`：未選完時的各方案金額（見 `plans()`；pdf_gen 用它取代合計框），全選定 ⇒ None。"""
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
            "unpicked_groups": len(unpicked),
            "plans": _safe_plans(q, groups, picks, numbers) if unpicked else None}
