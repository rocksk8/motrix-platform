# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

A = C.A
HERE = C.HERE
M = os.path.join(HERE, "mock")
OUT = "D:/Claude-pm/h3-matrix/docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/h3"
os.makedirs(OUT + "/shots", exist_ok=True)

g = C.load_groups()
rows = C.rows()
ALT_LOCK = A.ALT_LOCK

# 分區結構
secs = []
sec_of = {}
for top, tlabel, subs in A.SECTIONS:
    secs.append(dict(code=top, label=tlabel, subs=[dict(code=c, label=l, desc=d) for c, l, d in subs]))
    for c, l, d in subs:
        sec_of[c] = (top, l)

D_rows = []
for r in rows:
    f, gk, it = r["f"], r["gk"], r["it"]
    rec = f.get("recommended")
    heavy = f["risk"] in ("money", "legal", "security") or f["requiresPending"] or bool(f["loosen"])
    choices = [dict(value=c["value"], label=C.scrub(c["label"]), impact=C.scrub(c["impact"])) for c in (f.get("choices") or [])]
    help_what = C.scrub((f["question"] + " " + f["help"]).strip())
    impact = C.scrub(f["impact"] + ((" " + f["riskText"]) if f.get("riskText") and heavy else ""))
    rec_txt = ("建議值：" + C.fmt(f, rec) + "。") if rec is not None else ("建議值：維持預設 " + r["default_text"] + "。")
    if choices and rec is not None:
        rec_txt += " 各選項後果：" + "；".join(c["label"] + "＝" + c["impact"] for c in choices)
    D_rows.append(dict(
        id=f"{gk}.{f['key']}", gk=gk, key=f["key"], name=it["name"], desc=C.scrub(it["desc"]),
        type=f["type"], unit=f["unit"], min=f["min"], max=f["max"], **{"def": f["default"]}, rec=rec,
        choices=choices, risk=f["risk"], rp=bool(f["requiresPending"]), loosen=f["loosen"], adv=bool(f["advanced"]),
        elig=bool(r["elig"] and f["type"] != "str"), confirm=bool(r["confirm"]), why=r["why"],
        sec=r["sec"], top=sec_of[r["sec"]][0], secLabel=sec_of[r["sec"]][1], groupLabel=r["G"]["label"],
        heavy=heavy, others=gk in C.AFFECT_OTHERS, ext=C.NEEDS_EXTERNAL.get((gk, f["key"]), ""), cust=bool(it.get("cust")),
        dangerText=r["danger"], riskText=C.scrub(f.get("riskText") or ""),
        helpWhat=help_what, helpWhen=r["when"], helpImpact=impact, helpRec=rec_txt,
        lockRule=(gk == "quote_alt" and f["key"] in ALT_LOCK),
        roles=[x for x in ((f.get("impactScope") or {}).get("roles") or [])]))

ids = {r["id"] for r in D_rows}
dflt = {r["id"]: r["def"] for r in D_rows}
FAKE = {
    "quote_alt.show_unpicked_in_pdf": True, "quote_alt.lock_scope": 2, "quote_defaults.valid_days": 14, "profit_warning.quote_form_low": 15,
    "profit_warning.report_low": 12, "finance_cashier.receivable_grace_days": 3, "finance_reports.custom_aging": 1,
    "finance_reports.aging_day1": 15, "finance_reports.aging_day2": 30, "finance_reports.aging_day3": 60,
    "completion_note.over_qty": 1, "quote_backfill.auto_off_hours": 12, "overhead.default_pct": 30,
    "finance_cashier.custom_bank_aliases": 1, "finance_cashier.bank_alias_date": dflt["finance_cashier.bank_alias_date"] + ",帳務日",
    "alerts.warranty_report_days": dflt["alerts.warranty_report_days"] + 30,
}
FAKE_SRC = {k: dict(by=("王經理" if i % 2 == 0 else "李會計"), at=("10/28" if i % 3 else "11/05")) for i, k in enumerate(FAKE)}
FAKE_PEND = {"quote_approval.max_valid_days": dict(val=45, eff="11/20", need2=True, by="王經理")}
for k in list(FAKE) + list(FAKE_PEND):
    assert k in ids, k

DEPS = C.DEPS
for k, v in DEPS.items():
    assert k in ids and v in ids, (k, v)

P = "profit_warning."
pp = lambda *a: dict(zip([P + x for x in ("quote_form_low", "quote_form_good", "report_low", "report_good", "case_floor", "case_good", "settlement_good")], a))
PRESETS = [dict(name="標準（登錄表預設）", v=pp(12, 20, 10, 20, 0, 20, 20)), dict(name="較嚴（利潤要求高）", v=pp(15, 25, 15, 25, 3, 25, 25)), dict(name="較寬（利潤要求低）", v=pp(8, 15, 8, 15, -5, 15, 15))]
AG = "finance_reports."
AGING = [dict(name="30／60／90（預設）", v={AG + "aging_day1": 30, AG + "aging_day2": 60, AG + "aging_day3": 90}),
         dict(name="15／30／60", v={AG + "aging_day1": 15, AG + "aging_day2": 30, AG + "aging_day3": 60}),
         dict(name="45／90／180", v={AG + "aging_day1": 45, AG + "aging_day2": 90, AG + "aging_day3": 180})]
for p in PRESETS:
    for k, v in p["v"].items():
        f = next(r for r in D_rows if r["id"] == k)
        assert f["min"] is None or v >= f["min"], (k, v)
        assert f["max"] is None or v <= f["max"], (k, v)

SHELL_P = "D:/Claude-pm/h3-matrix/docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/shell_groups.json"
shell_all = json.load(open(SHELL_P, encoding="utf-8"))
shell_all = shell_all.get("groups", shell_all)
order = []
for r in D_rows:
    if r["gk"] not in order:
        order.append(r["gk"])
shell = {k: shell_all[k] for k in order}
for k, v in shell.items():
    for t in (v["plain"], v["currentName"]):
        for w in ("確認期間", "影子", "閘門", "true", "false"):
            assert w not in t, (k, t)
group_help = {k: C.scrub(g[k]["help"]) for k in order}
DATA = dict(shell=shell, groupOrder=order, groupHelp=group_help, sections=secs, rows=D_rows, groups={k: v["label"] for k, v in g.items()}, fake=FAKE, fakeSrc=FAKE_SRC, fakePend=FAKE_PEND,
            ccDays=g["change_control"]["fields"][0]["default"], deps=DEPS,
            pairs=[[P + "quote_form_low", P + "quote_form_good"], [P + "report_low", P + "report_good"], [P + "case_floor", P + "case_good"]],
            chipKeys=["finance_cashier.bank_alias_date", "finance_cashier.bank_alias_amount", "finance_cashier.bank_alias_desc"],
            profitPresets=PRESETS, agingPresets=AGING)

rd = lambda n: open(os.path.join(M, n), encoding="utf-8").read()
html = rd("shell.html")
html = html.replace("/*STYLE*/", rd("style.css")).replace("<!--PAGES-->", rd("pages.html")).replace("<!--OUTSIDE-->", rd("outside.html"))
html = html.replace("/*DATA*/", json.dumps(DATA, ensure_ascii=False)).replace("/*APP*/", rd("app_head.js") + chr(10) + rd("app_tail.js")).replace("/*PAGESJS*/", rd("pages.js"))
open(OUT + "/index.html", "w", encoding="utf-8", newline="\n").write(html)
print("index.html", len(html), "rows", len(D_rows), "elig", sum(1 for r in D_rows if r["elig"]))
