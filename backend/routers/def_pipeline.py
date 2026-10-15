# -*- coding: utf-8 -*-
"""定義的放寬分類＋單一發布管線（T60 S2；T57 架構筆記 §3.9／D3）。**不新增資料表**：待核准的版本放在既有的 `ui_definitions`（status='submitted'，自訂模組送審同一套），
核准票與確認期間放在既有的 `config_changes`（domain `def:<kind>`，`approvals_required=1`、`effective_at`＝現在＋`change_control.confirm_period_days`）。

旗標 `builder_governance.enabled` 關 ⇒ 本檔所有路由 404、發布與還原與今天逐位元相同。開啟後，名單內的 kind（`ACTIVE_KINDS`）：
- 發布／還原先用該 kind 的比較函式分類（`loosen`／`tighten`／`neutral`）：**無法判斷＝放寬**；
- 收緊或不變 ⇒ 立即發布（照舊），並在帳本留一筆；
- 放寬 ⇒ 不發布：把草稿凍結成送審版本、寫一筆待生效（需要**另一位**最高管理者核准＋確認期間過後才能套用），通知其他最高管理者；
- 套用（activate）＝核准票夠、確認期間已過 ⇒ 才真的發布；期間內任何最高管理者都能撤銷（cancel）。
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import JSONResponse

from db import get_db
from helpers import _require_user, _tok, _audit
from helpers import config_ledger as L
from helpers import settings_registry as SR
from core import definitions as D

router = APIRouter()

#: 目前受管線管的 kind（有比較函式、而且編輯器已能處理『待核准』回應的）。layout：排版器（3c，wip/t60-s4-r1）與選單編輯器
#: 都已改成遇到 `pending: true` 不說「已發布」——**這個 kind 只能在 3c 的 wip/t60-s4-r1 已在同一列車時才可加入名單**。
ACTIVE_KINDS = ("custom_fields", "layout", "user_buttons", "rule_set", "attachment_slot", "export_template", "option_list", "status_display", "notify_template", "case_stage_template", "notify_action", "list_pref_policy")      # list_pref_policy：T66 L1；user_buttons：T61 S6；rule_set：T62 BP-2；attachment_slot：T62 BP-4 S2；export_template：T61 BP-3；option_list：census #4；該 kind 沒登記時這個項目不起作用

_COSMETIC = {"label", "placeholder", "hint", "help", "description"}     # 只影響顯示文字，不影響誰看得到／填什麼


def enabled(conn=None) -> bool:
    try:
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001  讀不到一律當關
        return False


# ── 比較函式：old_body → new_body ⇒ (class, reasons)；class ∈ loosen／tighten／neutral。無法判斷 ⇒ loosen ─────────────────
def _cmp_custom_fields(old, new):
    of = {f.get("key"): f for f in (old or {}).get("fields", []) if isinstance(f, dict)}
    nf = {f.get("key"): f for f in (new or {}).get("fields", []) if isinstance(f, dict)}
    loosen, tighten = [], []
    for k in nf:
        if k not in of:
            loosen.append("新增欄位 %s" % k)
    for k in of:
        if k not in nf:
            tighten.append("移除欄位 %s" % k)
    for k in nf:
        if k not in of:
            continue
        a, b = of[k], nf[k]
        diff = {x for x in set(a) | set(b) if a.get(x) != b.get(x)} - _COSMETIC
        if not diff:
            continue
        if diff == {"required"}:
            (tighten if b.get("required") else loosen).append("%s 改為%s必填" % (k, "" if b.get("required") else "非"))
        else:
            loosen.append("欄位 %s 的 %s 變了（無法判斷寬嚴，視為放寬）" % (k, "、".join(sorted(diff))))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_layout(old, new):
    def keyed(b):
        return {json.dumps(o, sort_keys=True, ensure_ascii=False): o for o in (b or {}).get("ops", []) if isinstance(o, dict)}
    oo, nn = keyed(old), keyed(new)
    loosen, tighten = [], []
    for k, o in nn.items():
        if k in oo:
            continue
        (tighten if o.get("op") == "hide" else loosen if o.get("op") not in ("relabel", "move") else []).append("新增操作 %s" % o.get("op"))
    for k, o in oo.items():
        if k in nn:
            continue
        (loosen if o.get("op") == "hide" else [] if o.get("op") in ("relabel", "move") else loosen).append("移除操作 %s" % o.get("op"))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


_BTN_KEYS = {"key", "slot", "label", "action"}


def _cmp_user_buttons(old, new):
    """使用者自訂按鈕（T61 S6）：新增／改成『匯出』動作＝放寬（匯出會把資料帶出系統）；新增『開頁』＝不變；拿掉任何按鈕、匯出改成開頁＝收緊；
    只改文字或插槽＝不變；看不懂的結構或多出來的屬性＝放寬。"""
    def parse(body):
        if not isinstance(body, dict) or not isinstance(body.get("buttons", []), list):
            return None
        out = {}
        for b in body.get("buttons", []):
            if not isinstance(b, dict) or not isinstance(b.get("key"), str) or b["key"] in out or not isinstance(b.get("action"), dict):
                return None
            out[b["key"]] = b
        return out
    o, n = parse(old or {}), parse(new)
    if o is None or n is None:
        return "loosen", ["無法解析按鈕定義，視為放寬"]

    def act(b):
        a = b["action"]
        return a.get("type"), (a.get("export") if a.get("type") == "export" else a.get("page"))
    loosen, tighten = [], []
    for k, b in n.items():
        label = b.get("label") or k
        t, target = act(b)
        if set(b) - _BTN_KEYS:
            loosen.append("按鈕「%s」有看不懂的屬性（%s），視為放寬" % (label, "、".join(sorted(set(b) - _BTN_KEYS))))
        if k not in o:
            if t == "export":
                loosen.append("新增匯出按鈕「%s」（匯出 %s）" % (label, target))
            elif t != "navigate":
                loosen.append("新增按鈕「%s」的動作類型 %r 不認得，視為放寬" % (label, t))
            continue
        ot, otarget = act(o[k])
        if t == "export" and (ot != "export" or otarget != target):
            loosen.append("按鈕「%s」改為匯出（匯出 %s）" % (label, target))
        elif t not in ("export", "navigate"):
            loosen.append("按鈕「%s」的動作類型 %r 不認得，視為放寬" % (label, t))
        elif t == "navigate" and ot == "export":
            tighten.append("按鈕「%s」由匯出改為開頁" % label)
    for k, b in o.items():
        if k not in n:
            tighten.append("移除按鈕「%s」" % (b.get("label") or k))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_export_template(old, new):
    """匯出範本：新增欄位 ＝ 匯出檔多給資料 ⇒ 放寬（金額／有權限條件的欄位明寫）；移除欄位、拿掉頁首頁尾浮水印 ⇒ 收緊；
    新增或改變頁首／頁尾／浮水印文字 ⇒ 放寬（輸出檔上的可見文字，一律需核准）；只改欄位標題、順序 ⇒ 中性（純顯示）；格式或其他無法判斷的變動 ⇒ 放寬。"""
    from helpers import export_templates as ET
    old, new = old or {}, new or {}
    oc = [c.get("id") for c in old.get("columns", []) if isinstance(c, dict)]
    nc = [c.get("id") for c in new.get("columns", []) if isinstance(c, dict)]
    loosen, tighten = [], []
    gated = set()
    for meta in ET.registered().values():
        gated |= {c["id"] for c in meta["columns"] if c["money"]}
    for k in nc:
        if k not in oc:
            loosen.append("新增匯出欄位 %s%s" % (k, "（金額／有權限條件的欄位）" if k in gated else ""))
    for k in oc:
        if k not in nc:
            tighten.append("移除匯出欄位 %s" % k)
    if old.get("format") not in (None, new.get("format")):          # 沒有舊版（第一次發布）＝沒有東西可比，格式不算變動
        loosen.append("匯出格式變了（無法判斷寬嚴，視為放寬）")
    if "sheets" in old or "sheets" in new:
        # 工作表型（營運報表）：基準＝舊版選的；沒有舊版 ⇒ 全部工作表（沒有已發布範本＝今天的完整報表）。
        # 關掉工作表＝收緊；加回含金額的工作表＝放寬（第二位最高管理者核准）；加回不含金額的＝中性。
        nset, oset = new.get("sheets"), old.get("sheets")
        cats = [m for m in ET.registered().values() if m.get("sheets")]
        cat = None
        if isinstance(nset, list) and (oset is None or isinstance(oset, list)):
            for m in cats:
                ids = {x["id"] for x in m["sheets"]}
                if set(nset) <= ids and set(oset or []) <= ids:
                    cat = m
                    break
        if cat is None:
            loosen.append("無法解析工作表設定，視為放寬")
        else:
            order = [x["id"] for x in cat["sheets"]]
            label = {x["id"]: x["label"] for x in cat["sheets"]}
            money = {x["id"] for x in cat["sheets"] if x["money"]}
            base = list(oset) if oset is not None else order
            for i in order:
                if i in base and i not in nset:
                    tighten.append("關掉工作表「%s」" % label[i])
                elif i in nset and i not in base and i in money:
                    loosen.append("加回含金額的工作表「%s」（報表多給資料，需核准）" % label[i])
    for k in set(old) | set(new):
        if k in ("columns", "format", "version", "header", "footer", "watermark", "titles", "sheets"):
            continue
        loosen.append("未知設定 %s 變了（視為放寬）" % k)
    ot, nt = old.get("titles") or {}, new.get("titles") or {}
    for k in sorted(set(ot) | set(nt)):                   # 條款標題：新增或更換＝放寬（客戶可見文字）；恢復成預設（拿掉）＝收緊
        if k in nt and nt[k] != ot.get(k):
            loosen.append("條款標題 %s 改為「%s」（客戶可見文字，需核准）" % (k, nt[k]))
        elif k in ot and k not in nt:
            tighten.append("條款標題 %s 恢復預設" % k)
    for part in ("header", "footer", "watermark"):
        name = {"header": "頁首", "footer": "頁尾", "watermark": "浮水印"}[part]
        if part in old and part not in new:
            tighten.append("拿掉%s" % name)
        elif part in new and part not in old:
            loosen.append("新增%s文字（輸出檔多了可見文字）" % name)
        elif part in new and part in old and (old[part] or {}).get("text") != (new[part] or {}).get("text"):
            loosen.append("%s文字改變（輸出檔上的可見文字，需核准）" % name)
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_option_list(old, new):
    """選項清單：新增選項、改顯示名稱、重排、重新啟用 ⇒ 中性（只影響下拉怎麼列）；停用選項 ⇒ 收緊；無法判斷的變動 ⇒ 放寬。
    （已發布的選項不能刪除、不能改字——驗證器擋；這裡不會看到。）"""
    old, new = old or {}, new or {}
    ov = {x.get("value"): x for x in old.get("values", []) if isinstance(x, dict)}
    nv = {x.get("value"): x for x in new.get("values", []) if isinstance(x, dict)}
    loosen, tighten = [], []
    for k in set(old) | set(new):
        if k not in ("values", "version"):
            loosen.append("未知設定 %s 變了（視為放寬）" % k)
    for v in ov:
        if v not in nv:
            loosen.append("選項 %s 被移除（不應發生，視為放寬）" % v)
    for v, x in nv.items():
        o = ov.get(v)
        if o is not None and bool(x.get("disabled")) and not bool(o.get("disabled")):
            tighten.append("停用選項 %s" % v)
        if o is not None and x.get("prefix") != o.get("prefix"):
            loosen.append("選項 %s 的料號前綴變了（視為放寬）" % v)
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_stage_template(old, new):
    """案件階段樣板（S-ST1）：以階段種類鍵配對。
    - 新增階段（沒有比例）＝收緊（新案件結案要多完成一項）；移除階段＝**放寬**（結案關卡變容易，權責比例的分母也變）；
    - 任何階段的建議比例 `ratioBp` 新增、改值或拿掉＝**放寬**（影響收入認列的月份與比例，金流）；新增帶比例的階段也是放寬；
    - 只改樣板名稱、階段名稱、`offsetDays`／`durationDays`、順序、`dependsOn`＝中性（純顯示與日期建議）；
    - 看不懂的結構或多出來的鍵＝放寬。第一次發布（沒有舊版）以『沒有任何階段』為基準：只加階段不帶比例＝收緊。"""
    from helpers import stage_templates as ST
    old, new = old or {}, new or {}
    loosen, tighten = [], []
    for k in set(old) | set(new):
        if k not in ("version", "label", "stages"):
            loosen.append("未知設定 %s 變了（視為放寬）" % k)
    if (old and not isinstance(old.get("stages"), list)) or not isinstance(new.get("stages"), list):
        return "loosen", ["無法解析階段清單，視為放寬"] + loosen
    om, nm = ST.stage_map(old), ST.stage_map(new)
    if len(om) != len(old.get("stages") or []) or len(nm) != len(new["stages"]):
        loosen.append("階段清單有看不懂的項目，視為放寬")
    for k, st in nm.items():
        extra = set(st) - {"key", "label", "offsetDays", "durationDays", "ratioBp", "dependsOn"}
        if extra:
            loosen.append("階段 %s 有看不懂的設定（%s），視為放寬" % (k, "、".join(sorted(extra))))
        if k not in om:
            if st.get("ratioBp") is not None:
                loosen.append("新增階段「%s」並預設收入認列比例（影響認列，需核准）" % (st.get("label") or k))
            else:
                tighten.append("新增階段「%s」（新案件結案要多完成一項）" % (st.get("label") or k))
        elif om[k].get("ratioBp") != st.get("ratioBp"):
            loosen.append("階段「%s」的建議收入認列比例改變（影響認列，需核准）" % (st.get("label") or k))
    for k, st in om.items():
        if k not in nm:
            loosen.append("移除階段「%s」（新案件結案關卡變容易、認列比例的分母改變）" % (st.get("label") or k))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


# ── rule_set（BP-2 R3）：方向由『命中集合變大還是變小』決定，而不是寫死「調高＝放寬」──────────────────────────
#: 標示的醒目程度（降低＝放寬）
_LEVEL_RANK = {"info": 1, "yellow": 2, "red": 3}


def _num_dir(op, a, b):
    """同一欄位、同一類比較，常數由 a 改成 b ⇒ 命中集合 `same`｜`wider`｜`narrower`。lt/le：門檻調高＝更多命中；gt/ge：調低＝更多命中。"""
    if a == b:
        return "same"
    if op in ("lt", "le"):
        return "wider" if b > a else "narrower"
    return "wider" if b < a else "narrower"                            # gt／ge


def _when_dir(a, b):
    """條件 a → b ⇒ same｜wider｜narrower｜unknown。只認得『同一欄位的單一比較』的門檻／範圍／集合調整；其餘一律 unknown（＝放寬）。"""
    if a == b:
        return "same"
    if not (isinstance(a, dict) and isinstance(b, dict)) or a.get("field") != b.get("field") or a.get("op") in ("and", "or", "not") or b.get("op") in ("and", "or", "not"):
        return "unknown"
    oa, ob = a.get("op"), b.get("op")
    fam = {"lt": "up", "le": "up", "gt": "down", "ge": "down"}
    if oa in fam and ob in fam and fam[oa] == fam[ob]:
        d = _num_dir("lt" if fam[oa] == "up" else "gt", a["value"], b["value"])
        if d == "same":                                                # 值相同、只換了 lt↔le／gt↔ge：含邊界者命中較多
            return "wider" if ob in ("le", "ge") else "narrower"
        return d
    if oa == ob == "between":
        if b["min"] <= a["min"] and b["max"] >= a["max"]:
            return "wider"
        if b["min"] >= a["min"] and b["max"] <= a["max"]:
            return "narrower"
        return "unknown"
    if oa == ob == "in":
        sa, sb = set(a["values"]), set(b["values"])
        return "wider" if sb > sa else "narrower" if sb < sa else "unknown"
    return "unknown"


def _cmp_rule_set(old, new):
    def keyed(body):
        out = {}
        for r in (body or {}).get("rules", []) or []:
            if not isinstance(r, dict) or r.get("id") in out:
                raise ValueError("規則集格式不對")
            out[r["id"]] = r
        return out
    o, n = keyed(old), keyed(new)
    loosen, tighten = [], []
    for rid, r in n.items():
        nm = r.get("name") or rid
        if rid not in o:
            if r.get("enabled", True):
                tighten.append("新增規則「%s」" % nm)
            continue
        a = o[rid]
        ea, eb = a.get("enabled", True), r.get("enabled", True)
        if ea and not eb:
            loosen.append("停用規則「%s」" % nm)
        elif eb and not ea:
            tighten.append("啟用規則「%s」" % nm)
        if (a.get("mode"), a.get("on_failure")) != (r.get("mode"), r.get("on_failure")):
            loosen.append("規則「%s」的模式或故障處理變了（無法判斷寬嚴，視為放寬）" % nm)
        ma, mb = a.get("mark") or {}, r.get("mark") or {}
        if (ma.get("target"), ma.get("field")) != (mb.get("target"), mb.get("field")) or sorted(a.get("surfaces") or ["list"]) != sorted(r.get("surfaces") or ["list"]):
            loosen.append("規則「%s」的標示位置變了（無法判斷寬嚴，視為放寬）" % nm)
        elif ma.get("text") != mb.get("text") and ma.get("level") == "red":
            loosen.append("規則「%s」的紅色提示文字改了（提示的意思可能變了，視為放寬）" % nm)
        la, lb = _LEVEL_RANK.get(ma.get("level"), 0), _LEVEL_RANK.get(mb.get("level"), 0)
        if lb < la:
            loosen.append("規則「%s」的標示變得不那麼醒目" % nm)
        elif lb > la:
            tighten.append("規則「%s」的標示變得更醒目" % nm)
        if ea and eb:                                                  # 停用中的規則改條件不影響任何畫面
            d = _when_dir(a.get("when"), r.get("when"))
            if d == "wider":
                tighten.append("規則「%s」的條件放大了（會標示更多紀錄）" % nm)
            elif d in ("narrower", "unknown"):
                loosen.append("規則「%s」的條件縮小了（會標示較少紀錄）" % nm if d == "narrower" else "規則「%s」的條件結構變了（無法判斷寬嚴，視為放寬）" % nm)
    for rid, a in o.items():
        if rid not in n and a.get("enabled", True):
            loosen.append("移除規則「%s」" % (a.get("name") or rid))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_notify_template(old, new):
    """通知用語範本：新增或改變任何欄位的文字 ⇒ 放寬（收件人看到的字，需第二位最高管理者核准）；拿掉欄位（回到系統預設字）⇒ 收緊；
    內容相同 ⇒ 中性；未知的頂層設定變動或看不懂的結構 ⇒ 放寬。"""
    def flat(b):
        if not isinstance(b, dict):
            return None
        out = {}
        for chan in ("inapp", "mail"):
            sec = b.get(chan)
            if sec is None:
                continue
            if not isinstance(sec, dict):
                return None
            for f, v in sec.items():
                out["%s.%s" % (chan, f)] = v
        return out
    o, n = flat(old or {}), flat(new)
    if o is None or n is None:
        return "loosen", ["無法解析通知用語範本，視為放寬"]
    loosen, tighten = [], []
    for k, v in n.items():
        if k not in o:
            loosen.append("新增自訂用語 %s（收件人看到的字，需核准）" % k)
        elif o[k] != v:
            loosen.append("用語 %s 改變（收件人看到的字，需核准）" % k)
    for k in o:
        if k not in n:
            tighten.append("拿掉自訂用語 %s（回到系統預設字）" % k)
    for k in set(old or {}) | set(new or {}):
        if k not in ("inapp", "mail", "version") and (old or {}).get(k) != (new or {}).get(k):
            loosen.append("未知設定 %s 變了（視為放寬）" % k)
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def _cmp_attachment_slot(old, new):
    from helpers import attachment_slots as AS            # 延遲載入（避免 import 循環）
    return AS.compare(old, new)


def _cmp_notify_action(old, new):
    """額外通知動作（BP-4 S4）：比較邏輯在純函式 `helpers/notify_actions.compare`（新增動作／擴大收件人／加信件通道／放寬節流＝放寬；看不懂＝放寬）。"""
    from helpers import notify_actions as _NA
    return _NA.compare(old, new)


def _cmp_status_display(old, new):
    """狀態顯示表（S-X2）：比較邏輯在純函式 `helpers/status_display.compare`（核准／付款類改名改色＝放寬；看不懂＝放寬）。"""
    from helpers import status_display as _SD
    return _SD.compare(old, new)


def _cmp_list_pref_policy(old, new):
    from helpers import list_pref_policy as _LP
    return _LP.compare(old, new)


COMPARATORS = {"custom_fields": _cmp_custom_fields, "layout": _cmp_layout, "user_buttons": _cmp_user_buttons, "rule_set": _cmp_rule_set, "attachment_slot": _cmp_attachment_slot, "export_template": _cmp_export_template, "option_list": _cmp_option_list, "status_display": _cmp_status_display, "notify_template": _cmp_notify_template, "case_stage_template": _cmp_stage_template, "notify_action": _cmp_notify_action, "list_pref_policy": _cmp_list_pref_policy}


def classify(kind, old_body, new_body):
    fn = COMPARATORS.get(kind)
    if fn is None:
        return "loosen", ["這個種類沒有寬嚴比較，視為放寬"]
    try:
        return fn(old_body, new_body)
    except Exception:                                                  # noqa: BLE001  比較壞了 ⇒ 視為放寬（寧可多一道核准）
        return "loosen", ["比較時出錯，視為放寬"]


def _lkey(key):
    return str(key).replace(":", ".")[:60]


def _live_body(conn, kind, key, scope):
    r = D.get(conn, kind, key, scope)
    return (r or {}).get("body") or {}, (r or {}).get("version") or 0


def _record(conn, kind, key, scope, user, old_v, new_v, note, *, risk="none", effective_at=None, approvals_required=0, audit_action=None):
    return L.record(conn, "def:" + kind, _lkey(key), [{"field": "%s|%s" % (scope, key), "old": old_v, "new": new_v}], note or "", user,
                    ref_version=new_v, target_label="%s %s（%s）" % (kind, key, scope), link="settings-center.html",
                    risk=risk, effective_at=effective_at, approvals_required=approvals_required, audit_action=audit_action)


def _submit_pending(conn, kind, key, scope, user, note, reasons, old_v):
    sub = D.submit_draft(conn, kind, key, scope, note, user["username"], decision={"pipeline": {"reasons": reasons, "baseVersion": old_v}})
    days = SR.confirm_period_days(conn)
    eff = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    try:
        rec = _record(conn, kind, key, scope, user, old_v, sub["version"], note, risk="security", effective_at=eff,
                      approvals_required=1, audit_action="definitions.pending_loosen")
        conn.commit()
    except Exception:
        conn.rollback()
        D.decide_submitted(conn, kind, key, scope, sub["version"], False, user["username"], "管線登記失敗，自動退回")
        raise
    return dict(sub, pending=True, changeId=(rec["ids"] or [None])[0], effectiveAt=eff, reasons=reasons,
                message="這次變更放寬了限制，需要另一位最高管理者核准，並在 %d 天確認期間之後才會套用。" % days)


def handle_publish(conn, kind, key, scope, user, note, base_etag, authorization):
    """⇒ None（不適用：旗標關或 kind 不在名單，呼叫端照舊發布）或 dict（已處理：已發布，或待核准 `pending: True`）。"""
    if kind not in ACTIVE_KINDS or not enabled(conn):
        return None
    draft = D.get(conn, kind, key, scope, 0)
    if draft is None:
        return None                                                    # 讓原本的『沒有草稿』錯誤出現
    live_body, old_v = _live_body(conn, kind, key, scope)
    cls, reasons = classify(kind, live_body, draft["body"])
    if cls == "loosen":
        if base_etag is not None and draft.get("etag") != base_etag:
            raise D.DraftConflict("這份草稿在你載入之後被別人改過，未送出", {"etag": draft.get("etag", "")})
        out = _submit_pending(conn, kind, key, scope, user, note, reasons, old_v)
        _audit(_tok(authorization), "definitions.submit", "ui_definition", "%s/%s/%s" % (kind, key, scope),
               "放寬變更待核准 %s 第 %d 版" % (key, out["version"]), {"reasons": reasons})
        return out
    d = D.publish(conn, kind, key, scope, note, user["username"], base_etag=base_etag)
    _record(conn, kind, key, scope, user, old_v, d["version"], note, risk="ops", audit_action="definitions.publish_%s" % cls)
    conn.commit()
    _audit(_tok(authorization), "definitions.publish", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "發布 %s %s（%s）第 %d 版（%s）" % (kind, key, scope, d["version"], cls), {"note": d.get("note", "")})
    return d


def handle_restore(conn, kind, key, scope, version, user, note, authorization):
    """還原的管線入口。⇒ None（照舊還原）或 dict（待核准）。還原到較寬鬆的版本 ⇒ 把那一版放進草稿再走送審；有不同內容的草稿時不覆蓋（409）。"""
    if kind not in ACTIVE_KINDS or not enabled(conn):
        return None
    old = D.get(conn, kind, key, scope, int(version))
    if old is None or old["status"] != "published":
        return None                                                    # 讓原本的錯誤出現
    live_body, live_v = _live_body(conn, kind, key, scope)
    cls, reasons = classify(kind, live_body, old["body"])
    if cls != "loosen":
        return None
    cur = D.get(conn, kind, key, scope, 0)
    if cur is not None and cur["body"] != old["body"]:
        raise D.DefinitionConflict("目前有未發布的草稿，還原到較寬鬆的版本會蓋掉它；請先發布或丟棄草稿")
    if cur is None:
        D.save_draft(conn, kind, key, scope, old["body"], user=user["username"])
    out = _submit_pending(conn, kind, key, scope, user, note or ("還原自第 %s 版" % version), reasons, live_v)
    _audit(_tok(authorization), "definitions.submit", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "還原到較寬鬆的第 %s 版，待核准（第 %d 版）" % (version, out["version"]), {"reasons": reasons})
    return out


# ── 路由：待核准清單、核准、套用、撤銷（旗標關 ⇒ 404）──────────────────────────────────────────────
def _flag_gate():
    """身分已由呼叫端的 `_require_user(..., require_superadmin=True)` 驗過（未登入 ⇒ 401）；這裡只看旗標，關 ⇒ 404；通過回連線（呼叫端關閉）。"""
    conn = get_db()
    if not enabled(conn):
        conn.close()
        raise HTTPException(404, "Not Found")
    return conn


def _change(conn, change_id):
    for r in L.history(conn, "def", None, limit=1000):
        if r["id"] == change_id:
            return r
    return None


def _target(r):
    """⇒ (kind, 定義 key, scope, 送審版本)。帳本的 key 欄為了符合 domain 規則把 ':' 換成 '.'，真正的 key 與 scope 放在 field（`scope|key`）。"""
    scope, key = r["field"].split("|", 1)
    return r["domain"].split(":", 1)[1], key, scope, int(r["ref_version"] or 0)


def _view(r):
    kind, key, scope, ver = _target(r)
    return {"id": r["id"], "kind": kind, "key": key, "scope": scope, "version": ver, "state": r["state"], "by": r["actor"], "at": r["at"],
            "reason": r["reason"], "effectiveAt": r["effective_at"], "approvals": r["approvals"], "approvalsRequired": r["approvals_required"],
            "ready": L.in_effect(r)}


@router.get("/api/def-pipeline/pending")
def pending_changes(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = _flag_gate()
    try:
        return {"items": [_view(r) for r in L.history(conn, "def", None, limit=1000) if r["state"] == "pending"]}
    finally:
        conn.close()


def _pending_row(conn, change_id):
    r = _change(conn, change_id)
    if r is None or not r["domain"].startswith("def:"):
        raise HTTPException(404, "找不到這筆待核准的變更")
    if r["state"] != "pending":
        raise HTTPException(409, "這筆變更已不是待核准狀態")
    return r


@router.post("/api/def-pipeline/changes/{change_id}/approve")
def approve_change(change_id: int, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = _flag_gate()
    try:
        _pending_row(conn, change_id)
        res = L.approve(conn, change_id, u, (payload or {}).get("reason", ""))
        if not res["ok"]:
            raise HTTPException(409, res["why"])
        conn.commit()
        _audit(_tok(authorization), "definitions.approve_loosen", "config_change", str(change_id), "核准放寬變更 #%d" % change_id, {})
        return {"approvals": res["approvals"], "required": res["required"]}
    finally:
        conn.close()


@router.post("/api/def-pipeline/changes/{change_id}/activate")
def activate_change(change_id: int, payload: dict = Body(default={}), authorization: str = Header(None)):
    """核准票夠、確認期間已過 ⇒ 真的發布這個送審版本；任何一項不滿足 ⇒ 409，什麼都不做。"""
    u = _require_user(authorization, require_superadmin=True)
    conn = _flag_gate()
    try:
        r = _pending_row(conn, change_id)
        if len(r["approvals"]) < int(r["approvals_required"] or 0):
            raise HTTPException(409, "還沒有另一位最高管理者核准")
        if not L.in_effect(r):
            raise HTTPException(409, "確認期間還沒過（%s 之後才能套用）" % r["effective_at"])
        kind, key, scope, ver = _target(r)
        try:
            d = D.decide_submitted(conn, kind, key, scope, ver, True, u["username"], (payload or {}).get("note", "") or "管線套用")
        except D.DefinitionError as e:
            return JSONResponse({"detail": str(e), "problems": e.problems}, status_code=422)
        L._append(conn, change_id, "activated", u, "核准且確認期間已過，已發布")
        conn.commit()
        _audit(_tok(authorization), "definitions.publish", "ui_definition", "%s/%s/%s" % (kind, key, scope),
               "套用放寬變更 #%d：發布 %s 第 %d 版" % (change_id, key, d["version"]), {})
        return d
    finally:
        conn.close()


@router.post("/api/def-pipeline/changes/{change_id}/cancel")
def cancel_change(change_id: int, payload: dict = Body(default={}), authorization: str = Header(None)):
    """確認期間內任何最高管理者都能撤銷：待核准的版本標為 rejected（保留、不可變），帳本記撤銷。"""
    u = _require_user(authorization, require_superadmin=True)
    conn = _flag_gate()
    try:
        r = _pending_row(conn, change_id)
        kind, key, scope, ver = _target(r)
        reason = (payload or {}).get("reason", "") or "撤銷"
        try:
            D.decide_submitted(conn, kind, key, scope, ver, False, u["username"], reason)
        except D.DefinitionError as e:
            return JSONResponse({"detail": str(e)}, status_code=409)
        L.cancel(conn, change_id, u, reason)
        conn.commit()
        _audit(_tok(authorization), "definitions.cancel_loosen", "config_change", str(change_id), "撤銷放寬變更 #%d" % change_id, {})
        return {"cancelled": True}
    finally:
        conn.close()
