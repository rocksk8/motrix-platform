# -*- coding: utf-8 -*-
"""套用案件階段樣板（S-ST2）的純計算：樣板 ＋ 基準日 ＋ 這個案件現有的階段 ⇒ 要建立的階段清單（不碰資料庫、不寫入）。

[單位] case:stage_apply    [層] L1    [穩定度] 實作
[公開介面] MODES, plan
[不變式] 套用＝複製（凍結）：產生的階段是這個案件自己的 `case_stages` 列，樣板之後改了不影響它。
    起日＝基準日＋offsetDays；迄日＝起日＋durationDays（只加天數，不排除週末；v1）。
    建議比例 `ratioBp`（金流）**只在這個案件原本沒有任何階段時帶入**；附加模式（案件已有階段）一律不帶，並在 notes 說明——
    否則合計會對不上 100%。本檔不碰認列公式。
    附加模式只補上「這個案件還沒有的種類」（以 stage_key 比對）；已存在的階段不改、不刪、不碰完成狀態。
    前置階段以種類鍵表示：指到本案已存在的同種類階段 ⇒ 換成它的 id；指到這次新建的 ⇒ 建立後換成新 id。
"""
from datetime import date, timedelta

MODES = ("new", "append")      # new：案件目前沒有任何階段才可用；append：補上缺少的種類


class PlanError(ValueError):
    pass


def _d(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise PlanError("基準日格式必須是 YYYY-MM-DD")


def plan(body, base_date, mode, existing):
    """body：已發布的樣板內容；existing：`[{id, stage_key}]`（本案現有階段）。
    ⇒ `{"stages": [{key,label,startDate,dueDate,ratioBp,dependsOn:[key…],existingDeps:[id…]}], "notes": [str], "skipped": [key…]}`。
    不合法 ⇒ PlanError（訊息可直接給使用者看）。"""
    if mode not in MODES:
        raise PlanError("mode 必須是 new 或 append")
    stages = (body or {}).get("stages")
    if not isinstance(stages, list) or not stages:
        raise PlanError("樣板沒有階段")
    base = _d(base_date)
    have = {e["stage_key"]: e["id"] for e in existing if e.get("stage_key")}
    if mode == "new" and existing:
        raise PlanError("這個案件已經有階段了；要補上缺少的階段請選「附加」")
    ratios = [s.get("ratioBp") for s in stages]
    has_ratio = any(r is not None for r in ratios)
    use_ratio = has_ratio and not existing
    notes, skipped, out = [], [], []
    if has_ratio and existing:
        notes.append("這個案件已經有階段，樣板的建議收入認列比例不會帶入（避免合計不是 100%）；需要的話請在階段上自行設定比例")
    for s in stages:
        k = s["key"]
        if k in have:
            skipped.append(k)
            continue
        try:
            start = base + timedelta(days=int(s["offsetDays"]))
            due = start + timedelta(days=int(s["durationDays"]))
        except OverflowError:
            raise PlanError("日期超出範圍")
        out.append({
            "key": k, "label": s["label"].strip(),
            "startDate": start.isoformat(), "dueDate": due.isoformat(),
            "ratioBp": s.get("ratioBp") if use_ratio else None,
            "dependsOn": [d for d in (s.get("dependsOn") or []) if d not in have],
            "existingDeps": [have[d] for d in (s.get("dependsOn") or []) if d in have],
        })
    if skipped:
        notes.append("本案已有的階段種類不會重複建立：" + "、".join(skipped))
    if not out:
        notes.append("沒有需要補上的階段")
    return {"stages": out, "notes": notes, "skipped": skipped}
