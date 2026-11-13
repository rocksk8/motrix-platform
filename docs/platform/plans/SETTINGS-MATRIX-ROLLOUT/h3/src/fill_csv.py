# -*- coding: utf-8 -*-
import csv, io, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import author_out as O

P = C.CSV_PATH
raw = open(P, "rb").read()
rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
hdr = rows[0]


def col(prefix):
    for i, h in enumerate(hdr):
        if h.startswith(prefix):
            return i
    raise KeyError(prefix)


ix = {h: i for i, h in enumerate(hdr)}
cN, cD, cC, cS, cR, cY, cM = [col("【填】" + p) for p in ("建議白話名稱", "一句說明", "選項白話後果", "目前生效值與來源", "影響別人", "套用樣式", "備註")]
mine = {(r["gk"], r["f"]["key"]): r for r in C.rows()}
done = outdone = 0
for row in rows[1:]:
    k = (row[ix["群組代碼"]], row[ix["欄位代碼"]])
    if k in mine and row[ix["分工"]].startswith("甲"):
        r = mine[k]; it = r["it"]
        row[cN] = it["name"]
        row[cD] = C.scrub(it["desc"])
        row[cC] = C.scrub(it.get("ch") or "（非選項型，不適用）")
        row[cS] = f"預設 {r['default_text']}；列上顯示「目前值＋來源」（預設／公司／等待生效），與預設不同標●並可「重設為預設」"
        row[cR] = r["danger"]
        row[cY] = r["style"]
        sec = next((s[2] for grp in C.A.SECTIONS for s in grp[2] if s[0] == r["sec"]), "")
        batch = ("可批次（套用建議值／預設組合／重設為預設" + ("；營運類要確認視窗" if r["confirm"] else "") + "）") if r["elig"] else "不進批次（影響大或要等 N 天才生效／放寬須核准，須逐項設定）"
        parts = [C.scrub(it["note"]) if it.get("note") else "", batch, "mockup 分區：" + sec]
        if r["when"]:
            parts.append("「什麼時候要改」（SettingDef.when 草稿）：" + r["when"])
        row[cM] = "｜".join(p for p in parts if p)
        done += 1
    elif row[ix["段"]].startswith("四") and row[ix["分工"]].startswith("甲"):
        o = O.OUT[row[ix["現名稱(label)"]]]
        row[cN], row[cD], row[cC], row[cS], row[cR], row[cY], row[cM] = o["name"], o["desc"], o["ch"], o["src"], o["danger"], o["style"], o["note"]
        for p in o["style"].split("、"):
            assert p in C.ALLOWED_STYLES, p
        outdone += 1
assert done == 76 and outdone == 7, (done, outdone)
for row in rows[1:]:
    if row[ix["分工"]].startswith("甲"):
        for c in (cN, cD, cC, cS, cR, cY, cM):
            assert row[c].strip(), (row[ix["欄位代碼"]], row[ix["現名稱(label)"]], c)
buf = io.StringIO(newline="")
csv.writer(buf, lineterminator="\r\n").writerows(rows)
open(P, "wb").write(("﻿" + buf.getvalue()).encode("utf-8"))
print("filled", done, outdone)
