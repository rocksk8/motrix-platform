# -*- coding: utf-8 -*-
"""案件執行階段樣板（S-ST1；設計 docs/platform/plans/CASE-STAGE-TEMPLATE-INVESTIGATION-T62.md）：宣告式的階段清單（種類鍵、名稱、起迄天數、建議比例、前置階段）。

[單位] helper:stage_templates    [層] L1    [穩定度] 實作（本刀只有定義、驗證、治理分類與旗標；套用端點與案件頁按鈕是 S-ST2）
[公開介面] COMPARE_KEYS, FIELD, GROUP, KIND, MAX_DAYS, MAX_STAGES, OFF_REASON, definition_problems, enabled, ensure_kind, stage_map
[不變式] 設定 `builder_stage_templates.enabled`（預設 0＝關；且必須同時開啟 `builder_governance.enabled`）關著時：kind 不登記、定義路由 404（功能狀態閘門）、
    沒有任何程式讀這個定義——現有的階段新增／編輯／提醒／認列／結案關卡完全不受影響。
    範本只收宣告式資料：階段種類鍵 `key`（小寫英數底線，樣板內唯一，**建立後不可改**——比較函式以鍵配對，改鍵＝移除舊的＋新增新的）、
    顯示名稱（`helpers.safe_text` 同一套白名單）、`offsetDays`／`durationDays`（0～730 的整數；由套用端點推算起訖日）、
    選填 `ratioBp`（建議的收入認列比例，基點）、`dependsOn`（以鍵表示，不可自指、不可循環）。
    **比例是金流**：只要有任何階段設了比例，就**每個階段都要設**（0 也要明寫＝這個階段不認列），且合計必須剛好 10000；
    本檔不碰認列公式（`modules/case/recognition.py` 不動）。
    套用＝複製成該案自己的 `case_stages` 列（凍結）；樣板之後修改不影響已套用的案件。
[契約題] backend/tests/platform/test_stage_templates_t62.py
"""
import re

from core import definitions as D
from core import spine as _spine
from helpers import safe_text as _ST

GROUP = "builder_stage_templates"
FIELD = "enabled"
KIND = "case_stage_template"
OFF_REASON = "自訂階段樣板尚未開放（設定中心：自訂階段樣板）"
MAX_STAGES = 30
MAX_DAYS = 730
LABEL_MAX = 20
NAME_MAX = 30
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
_TOP = {"version", "label", "stages"}
_STAGE = {"key", "label", "offsetDays", "durationDays", "ratioBp", "dependsOn"}
#: 比較函式要看的欄位（其餘鍵＝看不懂＝放寬）
COMPARE_KEYS = ("label", "offsetDays", "durationDays", "ratioBp", "dependsOn")


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。必須同時開啟『建構器治理』（放寬要靠第二位最高管理者核准與發布前預覽雜湊）。"""
    try:
        from helpers import settings_registry as SR
        if not bool(int(SR.get(GROUP, FIELD, conn=conn))):
            return False
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                        # noqa: BLE001
        return False


def _int(v, lo, hi) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _cycle(deps: dict) -> list:
    """⇒ 在循環裡的鍵（空＝沒有循環）。deps：{key: [key…]}。"""
    state, bad = {}, []

    def visit(k, path):
        if state.get(k) == 2:
            return
        if state.get(k) == 1:
            bad.extend(path[path.index(k):] if k in path else [k])
            return
        state[k] = 1
        for d in deps.get(k, ()):
            if d in deps:
                visit(d, path + [k])
        state[k] = 2
    for k in deps:
        visit(k, [])
    return list(dict.fromkeys(bad))


def definition_problems(key, body) -> list:
    """發布前驗證 ⇒ `[{path, message}]`（空＝通過）。`key`＝樣板鍵（小寫英數底線）。"""
    out = []
    if not isinstance(key, str) or not _KEY_RE.match(key):
        out.append({"path": "", "message": "樣板鍵必須是小寫英文字母開頭的英數底線（最多 30 字）"})
    if not isinstance(body, dict):
        return out + [{"path": "", "message": "樣板必須是物件"}]
    for k in body:
        if k not in _TOP:
            out.append({"path": k, "message": "不認得的設定：%s" % k})
    if body.get("version") != 1 or isinstance(body.get("version"), bool):
        out.append({"path": "version", "message": "version 必須是 1"})
    msg = _ST.problem(body.get("label"), NAME_MAX, allow_status=True)
    if msg:
        out.append({"path": "label", "message": "樣板名稱：" + msg})
    stages = body.get("stages")
    if not isinstance(stages, list) or not stages:
        return out + [{"path": "stages", "message": "stages 必須是不空的清單"}]
    if len(stages) > MAX_STAGES:
        out.append({"path": "stages", "message": "最多 %d 個階段" % MAX_STAGES})
    keys, labels, deps, ratios = [], set(), {}, []
    for i, st in enumerate(stages):
        p = "stages[%d]" % i
        if not isinstance(st, dict):
            out.append({"path": p, "message": "階段必須是物件"})
            continue
        for k in st:
            if k not in _STAGE:
                out.append({"path": "%s.%s" % (p, k), "message": "不認得的設定：%s（階段只有 key、label、offsetDays、durationDays、ratioBp、dependsOn）" % k})
        k = st.get("key")
        if not isinstance(k, str) or not _KEY_RE.match(k):
            out.append({"path": p + ".key", "message": "階段種類鍵必須是小寫英文字母開頭的英數底線（最多 30 字）"})
        elif k in keys:
            out.append({"path": p + ".key", "message": "階段種類鍵重複：%s" % k})
        else:
            keys.append(k)
        msg = _ST.problem(st.get("label"), LABEL_MAX, allow_status=True)
        if msg:
            out.append({"path": p + ".label", "message": "階段名稱：" + msg})
        elif st["label"].strip() in labels:
            out.append({"path": p + ".label", "message": "階段名稱重複：%s" % st["label"]})
        else:
            labels.add(st["label"].strip())
        for f in ("offsetDays", "durationDays"):
            if not _int(st.get(f), 0, MAX_DAYS):
                out.append({"path": "%s.%s" % (p, f), "message": "%s 必須是 0～%d 的整數" % (f, MAX_DAYS)})
        rb = st.get("ratioBp")
        if rb is not None and not _int(rb, 0, 10000):
            out.append({"path": p + ".ratioBp", "message": "ratioBp 必須是 0～10000 的整數（基點；留空＝這個樣板不預設比例）"})
        ratios.append(rb)
        dep = st.get("dependsOn", [])
        if not isinstance(dep, list) or not all(isinstance(x, str) for x in dep) or len(set(dep)) != len(dep):
            out.append({"path": p + ".dependsOn", "message": "dependsOn 必須是不重複的階段種類鍵清單"})
        elif isinstance(k, str):
            deps[k] = list(dep)
    for k, dl in deps.items():
        for d in dl:
            if d == k:
                out.append({"path": "stages", "message": "階段 %s 不能以自己為前置階段" % k})
            elif d not in keys:
                out.append({"path": "stages", "message": "階段 %s 的前置階段不存在：%s" % (k, d)})
    cyc = _cycle({k: [d for d in dl if d != k and d in keys] for k, dl in deps.items()})
    if cyc:
        out.append({"path": "stages", "message": "前置階段形成循環：%s" % "、".join(cyc)})
    set_n = sum(1 for r in ratios if r is not None)
    if set_n:
        if set_n != len(ratios):
            out.append({"path": "stages", "message": "有任何階段設了收入認列比例，每個階段都要設（0＝這個階段不認列）"})
        elif all(_int(r, 0, 10000) for r in ratios) and sum(ratios) != 10000:
            out.append({"path": "stages", "message": "收入認列比例合計必須剛好是 10000（100%%）；目前是 %d" % sum(ratios)})
    return out


def stage_map(body) -> dict:
    """⇒ `{key: stage}`（給比較函式與預覽用；看不懂的結構 ⇒ 空 dict）。"""
    out = {}
    for st in (body or {}).get("stages", []) if isinstance(body, dict) else []:
        if isinstance(st, dict) and isinstance(st.get("key"), str):
            out[st["key"]] = st
    return out


def _kind_validator(body, key):
    if not enabled():
        return [{"path": "", "message": OFF_REASON}]
    return definition_problems(key, body)


def _gate(key):
    """通用定義路由的功能狀態閘門（`spine.register_kind_gate`）：旗標或治理關閉 ⇒ hidden（404）。"""
    return "open" if enabled() else "hidden"


_spine.register_kind_gate(KIND, _gate)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="案件階段樣板", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()
