# -*- coding: utf-8 -*-
"""共用：載入 groups.json＋author.py＋r2 盤點表，算出每欄的衍生資訊（CSV 與 HTML 共用，確保一致）。
可批次的判定一律取自 r2 盤點表的「可批次?」欄（h4 產生器依 SPEC §4 算出），不自己另算。"""
import csv, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import author as A
import author_help as H

CSV_PATH = "D:/Claude-pm/h3-matrix/docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/settings-center-items.csv"
RISK_ZH = {"none": "無", "ops": "營運", "security": "資安", "money": "金額", "legal": "法規"}
# SPEC §11 套用樣式詞彙
ALLOWED_STYLES = ["矩陣", "勾選批次", "群組全開全關", "搜尋篩選", "預設組合", "套用前確認＋復原這一批", "手機卡片", "單項表單", "逐列編輯＋預覽", "精靈"]
CONFIRM = "套用前確認＋復原這一批"
AFFECT_OTHERS = {"quote_approval", "quote_alt", "material_recognition", "case_close_gates", "alerts", "material_order", "completion_note"}
NEEDS_EXTERNAL = {("alerts", "cert_warn_days"): "到期前要到開發者端換發簽章確認檔"}
LOOSEN_ZH = {"up": "往大調", "down": "往小調"}
# 用語表禁用詞：登錄表原文若含這些，mockup 顯示時改寫（並在設計說明列出「來源要改」）
SCRUB = [("影子（只記錄）", "先試跑（只記錄）"), ("影子", "先試跑"), ("確認期間", "等待期"), ("閘門", "檢查")]


DEPS = {}
for _k in ("total_text", "note_template", "show_unpicked_in_pdf", "alt_groups_max", "combo_view_max", "combo_view_default_open"):
    DEPS["quote_alt." + _k] = "quote_alt.alt_enabled"
for _k in ("due_soon_payable_days", "due_soon_planned_days"):
    DEPS["finance_cashier." + _k] = "finance_cashier.custom_due_soon"
for _k in ("bank_alias_date", "bank_alias_amount", "bank_alias_desc"):
    DEPS["finance_cashier." + _k] = "finance_cashier.custom_bank_aliases"
for _k in ("aging_day1", "aging_day2", "aging_day3"):
    DEPS["finance_reports." + _k] = "finance_reports.custom_aging"
for _k in ("require_stages", "require_payment_items", "require_settlement", "count_unfinished_extra_expenses"):
    DEPS["case_close_gates." + _k] = "case_close_gates.enabled"
for _k in ("prefill_unsigned", "qty_mode", "default_status", "include_headers", "brand_prefix"):
    DEPS["completion_note." + _k] = "completion_note.auto_prefill"


def compose_when(gk, f, g):
    w = H.WHEN.get(f"{gk}.{f['key']}", "")
    if not w:
        return w
    dep = DEPS.get(f"{gk}.{f['key']}")
    if dep:
        dg, dk = dep.split(".")
        dn = next(x["label"] for x in g[dg]["fields"] if x["key"] == dk)
        w = f"要先開啟「{dn}」才有作用。" + w
    if f["loosen"] and "尚未提供" not in w:
        w += f"若要往放寬方向調整（{LOOSEN_ZH[f['loosen']]}），需第二位最高管理者核准並等待 N 天才生效。"
    return w


def scrub(t):
    if not isinstance(t, str):
        return t
    for a, b in SCRUB:
        t = t.replace(a, b)
    return t


def load_groups():
    with open(os.path.join(HERE, "groups.json"), encoding="utf-8") as fh:
        return json.load(fh)


def load_csv_batch():
    raw = open(CSV_PATH, "rb").read().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw, newline="")))
    ix = {h: i for i, h in enumerate(rows[0])}
    m = {}
    for r in rows[1:]:
        if r[ix["群組代碼"]]:
            m[(r[ix["群組代碼"]], r[ix["欄位代碼"]])] = (r[ix["可批次?"]], r[ix["群組風險標示(內含高風險項目?)"]])
    return m


def fmt(f, v):
    ch = f.get("choices") or []
    if ch:
        for c in ch:
            if c["value"] == v:
                return scrub(c["label"])
    if f["type"] == "bool":
        return "開啟" if v else "關閉"
    if f["type"] in ("int", "float"):
        s = f"{v:,}" if isinstance(v, int) else str(v)
        return f"{s} {f['unit']}".strip()
    if f["type"] == "str":
        return "（空白）" if v in ("", None) else f"「{v}」"
    return str(v)


def style_of(gk, f, elig):
    ch = bool(f.get("choices"))
    if f["type"] == "str":
        parts = ["逐列編輯＋預覽", "手機卡片"]
    elif gk == "quote_alt" and f["key"] in A.ALT_LOCK:
        parts = ["矩陣", "單項表單", "手機卡片"]
    elif gk == "profit_warning":
        parts = ["矩陣", "勾選批次", "預設組合", CONFIRM, "手機卡片"]
    elif gk == "finance_reports" and f["key"].startswith("aging_day"):
        parts = ["預設組合", "勾選批次", CONFIRM, "手機卡片"]
    elif gk == "quote_approval":
        parts = ["單項表單", "搜尋篩選", "手機卡片"]
    else:
        parts = ["單項表單", "手機卡片"]
    if elig and f["type"] != "str":
        for need in ("勾選批次", CONFIRM):
            if need not in parts:
                parts.insert(len(parts) - 1, need)
    else:
        parts = [p for p in parts if p not in ("勾選批次", CONFIRM)]
    for p in parts:
        assert p in ALLOWED_STYLES, p
    return "、".join(parts)


def danger_text(gk, G, f):
    tags = []
    heavy = f["risk"] in ("money", "legal", "security") or f["requiresPending"] or bool(f["loosen"])
    if heavy:
        tags.append("影響大")
    parts = []
    if heavy and f.get("riskText"):
        parts.append(scrub(f["riskText"]))
    if f["requiresPending"]:
        parts.append("改了要等 N 天才生效（天數見「變更管制」）")
    if f["loosen"]:
        parts.append(f"{LOOSEN_ZH[f['loosen']]}＝放寬，須第二位最高管理者核准")
    if A.ITEMS[(gk, f["key"])].get("cust"):
        tags.append("客戶看得到")
    if (gk, f["key"]) in NEEDS_EXTERNAL:
        tags.append("需外部設定")
        parts.append("需外部動作：" + NEEDS_EXTERNAL[(gk, f["key"])])
    if gk in AFFECT_OTHERS:
        tags.append("影響別人")
    if f["advanced"]:
        tags.append("進階")
    head = "、".join(tags) if tags else "無"
    return head + ("｜" + "；".join(parts) if parts else "")


def rows():
    g = load_groups()
    bm = load_csv_batch()
    out = []
    for gk in A.GROUP_SEC:
        G = g[gk]
        for f in G["fields"]:
            it = A.ITEMS[(gk, f["key"])]
            btxt, gflag = bm[(gk, f["key"])]
            confirm = "需確認" in btxt
            # 以 SPEC §4.1 為準：敏感群組與文字欄位一律不可批次（盤點表該欄的產生器漏了敏感檢查，h4 修後會跟上）
            if f["type"] == "str":
                elig, why = False, "文字欄位：逐列編輯＋預覽，不畫勾選格、不批次"
            elif G["sensitive"]:
                elig, why = False, "敏感群組（" + G["label"] + "）：一律逐項設定"
            elif gk == "change_control":
                elig, why = False, "變更管制本身：永遠逐項設定"
            elif f["risk"] in ("money", "legal", "security"):
                elig, why = False, f"影響大（風險：{RISK_ZH.get(f['risk'])}）：永遠逐項設定"
            elif f["requiresPending"]:
                elig, why = False, "要等 N 天才生效：須逐項設定"
            elif f["loosen"]:
                elig, why = False, "放寬方向須第二位最高管理者核准：須逐項設定"
            else:
                elig, why = True, ""
            if not elig:
                confirm = False
            sec = it.get("sec") or A.GROUP_SEC[gk]
            out.append(dict(gk=gk, G=G, f=f, it=it, elig=elig, confirm=confirm, why=why, sec=sec, gflag=gflag,
                            default_text=fmt(f, f["default"]), style=style_of(gk, f, elig), danger=danger_text(gk, G, f),
                            when=compose_when(gk, f, g)))
    return out


if __name__ == "__main__":
    r = rows()
    print(len(r), sum(1 for x in r if x["elig"]), sum(1 for x in r if x["confirm"]))
