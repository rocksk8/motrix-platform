# -*- coding: utf-8 -*-
"""管銷分攤 10%×稅前 → 25%×直接毛利 的影響報告（第 48 班；唯讀）。

[單位] tool:overhead_impact_report    [層] 部署工具（離線，只讀）
[用法] python tools/platform/overhead_impact_report.py --db <資料庫檔> [--rate 0.25] [--top 10] [--csv <輸出檔>]
[不變式] 絕不寫入：以 sqlite `file:…?mode=ro` 開檔（寫入會直接失敗）；檔案不存在 ⇒ 拒絕（_dbbind.require_file，不建空庫）；
    不 import db.get_db、不呼叫任何會寫的函式。--csv 只寫到你指定的路徑（不可在 --db 同一個檔）。

每個案件（報價單）一列：
  舊營業利益（＝舊稅後淨利，讀已存值）、新營業利益（新式重算）、差額、已完結旗標（settlement.status=finalized）、
  資料來源（settlement＝精算 summary；quotation＝尚無精算，用報價 tot）。
新式：
  管銷 = round_half_up(max(0, 直接毛利) × rate)          ← 毛利為負時管銷以 0 計（與公益同；此為本工具假設，見影響文件 §6 待裁）
  公益 = 已存值（沒有則 max(0, round_half_up(直接毛利,0.01))）
  營業利益 = 直接毛利 − 管銷 − 公益 −（報價側才有）其他間接成本預留
    精算側：直接毛利＝summary.grossProfit，不扣預留（精算「實際」只認單據）。
    報價側：直接毛利＝tot.directProfit，預留＝tot.totalIndirect − 舊管銷 − 公益。
獎金：
  bonus_case_awards（案件獎金池）：以 award.net_profit 為舊基數；新基數＝該案「新營業利益」（只有精算側有意義）；
    以 bonus_case.allocate 用原本的名單（lines 的 person_bp／平均）重算每人。
  bonus_awards（舊版模板獎金）：每人 floor(floor(基數×total_pct/10000)×person_pct/10000)。
  兩種情境：A＝依需求（已完結沿用舊值 ⇒ 獎金差額 0）；B＝曝險（假設該案被重新開啟並以新式重新完結 ⇒ 獎金按新基數）。
"""
import argparse
import csv
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "backend")
for _p in (_BACKEND, os.path.join(_BACKEND, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _dbbind                                                    # noqa: E402
from helpers.legal_params import round_half_up                    # noqa: E402
from modules.payroll import bonus_case as _bc                     # noqa: E402

BP = 10000


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _open_ro(path):
    _dbbind.require_file(path)
    uri = "file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/").replace("?", "%3F").replace("#", "%23")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _new_admin(gross, rate):
    return round_half_up(max(0, gross), rate)


def _own_rate(d, tot, rate):
    """該案自己存的管銷百分比（data_json.overheadPct／tot.overheadPct，0～1 小數）；沒有才用 --rate。"""
    for v in ((d or {}).get("overheadPct"), (tot or {}).get("overheadPct")):
        try:
            if v is not None and 0 <= float(v) <= 100:
                return float(v) / 100
        except (TypeError, ValueError):
            pass
    return rate


def case_rows(conn, rate):
    out = []
    for r in conn.execute("SELECT quote_no, customer_name, project_name, status, data_json FROM quotations ORDER BY quote_no"):
        try:
            d = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            d = {}
        tot = d.get("tot") if isinstance(d.get("tot"), dict) else {}
        st = d.get("settlement") if isinstance(d.get("settlement"), dict) else {}
        sm = st.get("summary") if isinstance(st.get("summary"), dict) else {}
        finalized = st.get("status") == "finalized"
        if sm.get("netProfit") is not None and sm.get("grossProfit") is not None:
            src, pretax, gross = "settlement", _num(sm.get("quotedPretax")), _num(sm["grossProfit"])
            old_admin, old_net = _num(sm.get("adminCost")), _num(sm["netProfit"])
            charity = _num(sm["charityDonation"]) if sm.get("charityDonation") is not None else max(0, round_half_up(gross, 0.01))
            new_net = gross - _new_admin(gross, _own_rate(d, tot, rate)) - charity
        elif tot.get("netProfit") is not None or tot.get("directProfit") is not None:
            src, pretax = "quotation", _num(tot.get("pretax"))
            gross = _num(tot.get("directProfit"))
            old_admin = _num(tot["adminCost"]) if tot.get("adminCost") is not None else round_half_up(pretax, 0.10)
            charity = max(0, _num(tot["charityDonation"])) if tot.get("charityDonation") is not None else max(0, round_half_up(gross, 0.01))
            old_net = _num(tot["netProfit"]) if tot.get("netProfit") is not None else gross - old_admin - charity
            reserve = _num(tot["totalIndirect"]) - old_admin - charity if tot.get("totalIndirect") is not None else 0.0
            new_net = gross - _new_admin(gross, _own_rate(d, tot, rate)) - charity - reserve
        else:
            continue
        out.append({"quote_no": r["quote_no"], "customer": r["customer_name"] or "", "project": r["project_name"] or "",
                    "source": src, "settled": finalized, "pretax": pretax, "gross": gross, "old_admin": old_admin,
                    "new_admin": _new_admin(gross, _own_rate(d, tot, rate)), "old_net": old_net, "new_net": new_net, "delta": new_net - old_net,
                    "old_pct": (old_net / pretax * 100) if pretax > 0 else 0.0,
                    "new_pct": (new_net / pretax * 100) if pretax > 0 else 0.0})
    return out


def _case_award_people(conn, rate_by_quote):
    out = []
    for a in conn.execute("SELECT * FROM bonus_case_awards ORDER BY quote_no"):
        lines = [dict(x) for x in conn.execute("SELECT * FROM bonus_case_award_lines WHERE award_id=? ORDER BY id", (a["id"],))]
        c = rate_by_quote.get(a["quote_no"])
        new_net = c["new_net"] if (c and c["source"] == "settlement") else None
        members = {k: [] for k in _bc.CATEGORIES}
        for l in lines:
            if l["category"] in members:
                members[l["category"]].append({"username": l["username"], "person_bp": l["person_bp"]})
        newamt = {}
        note = ""
        if new_net is None:
            note = "無精算 summary，無法算新基數"
        elif new_net <= 0:
            note = "新營業利益≤0 ⇒ 不能建立／會被拒"
        else:
            try:
                res = _bc.allocate(new_net, int(a["rate_bp"]), json.loads(a["split_json"] or "{}"), members)
                for cat, cv in res["categories"].items():
                    for ln in cv["lines"]:
                        newamt[(cat, ln["username"])] = ln["amount"]
                new_pool = res["pool"]
            except Exception as exc:                          # noqa: BLE001
                note = "重算失敗：%s" % exc
        for l in lines:
            out.append({"kind": "case", "quote_no": a["quote_no"], "status": a["status"], "user": l["username"], "category": l["category"],
                        "old": l["amount"], "new": newamt.get((l["category"], l["username"])), "note": note,
                        "old_base": _num(a["net_profit"]), "new_base": new_net})
    return out


def _legacy_award_people(conn, rate_by_quote):
    out = []
    for a in conn.execute("SELECT * FROM bonus_awards WHERE voided_at='' ORDER BY quote_no"):
        c = rate_by_quote.get(a["quote_no"])
        new_base = c["new_net"] if (c and c["source"] == "settlement") else None
        for l in conn.execute("SELECT * FROM bonus_award_lines WHERE award_id=?", (a["id"],)):
            new = None
            if new_base is not None and new_base > 0:
                new = (int(new_base) * int(l["total_pct"]) // BP) * int(l["person_pct"]) // BP
            out.append({"kind": "legacy", "quote_no": a["quote_no"], "status": a["status"], "user": l["username"], "category": l["item_name_snapshot"],
                        "old": l["amount"], "new": new, "note": "" if new is not None else "新基數不可用",
                        "old_base": _num(a["base_amount"]), "new_base": new_base})
    return out


def _fmt(n):
    return "{:,.0f}".format(n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True, help="資料庫檔（只讀開啟）")
    ap.add_argument("--rate", type=float, default=0.25, help="新管銷係數（預設 0.25，乘直接毛利）")
    ap.add_argument("--top", type=int, default=10, help="列出差額絕對值最大的幾筆")
    ap.add_argument("--csv", default="", help="另存逐案明細 CSV（不可是 --db 同一個檔）")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                         # noqa: BLE001
        pass
    if a.csv and os.path.abspath(a.csv) == os.path.abspath(a.db):
        print("--csv 不可與 --db 同檔", file=sys.stderr)
        return 2
    conn = _open_ro(a.db)
    try:
        cases = case_rows(conn, a.rate)
        by_q = {c["quote_no"]: c for c in cases}
        people = _case_award_people(conn, by_q) + _legacy_award_people(conn, by_q)
    finally:
        conn.close()

    def grp(rows):
        return len(rows), sum(c["old_net"] for c in rows), sum(c["new_net"] for c in rows)
    print("== 案件（報價單）：共 %d 筆，rate=%.2f×直接毛利" % (len(cases), a.rate))
    for label, rows in (("已完結（沿用舊值，需求）", [c for c in cases if c["settled"]]),
                        ("未完結（重算）", [c for c in cases if not c["settled"]])):
        n, o, nw = grp(rows)
        worse = sum(1 for c in rows if c["delta"] < 0)
        flip = sum(1 for c in rows if c["old_net"] > 0 >= c["new_net"])
        print("  %-14s %4d 筆  舊營業利益合計 %s → 新 %s  差額 %s  （變差 %d 筆；由正轉≤0 %d 筆）" % (label, n, _fmt(o), _fmt(nw), _fmt(nw - o), worse, flip))
    fin = [c for c in cases if c["settled"]]
    n, o, nw = grp(fin)
    print("  [情境B 曝險] 若已完結案被重新開啟並以新式重新完結：差額 %s；12%% 門檻（營業利益率）達標 舊 %d → 新 %d 筆" % (
        _fmt(nw - o), sum(1 for c in cases if c["old_pct"] >= 12), sum(1 for c in cases if c["new_pct"] >= 12)))
    movers = sorted(cases, key=lambda c: -abs(c["delta"]))[:a.top]
    print("== 差額最大 %d 筆" % len(movers))
    for c in movers:
        print("  %-14s %-9s %s 舊 %s → 新 %s（%s；利潤率 %.1f%%→%.1f%%）" % (c["quote_no"], c["source"], "完結" if c["settled"] else "未完結",
              _fmt(c["old_net"]), _fmt(c["new_net"]), _fmt(c["delta"]), c["old_pct"], c["new_pct"]))
    print("== 獎金：%d 位次（案件獎金池 %d、舊版模板 %d）" % (len(people), sum(1 for p in people if p["kind"] == "case"), sum(1 for p in people if p["kind"] == "legacy")))
    done_ = [p for p in people if p["new"] is not None]
    print("  情境A（需求：已完結沿用舊值）獎金差額合計 0；情境B（曝險）：可比 %d 位次，舊合計 %s → 新 %s（差額 %s）" % (
        len(done_), _fmt(sum(p["old"] for p in done_)), _fmt(sum(p["new"] for p in done_)), _fmt(sum(p["new"] - p["old"] for p in done_))))
    for st in sorted({p["status"] for p in people}):
        rows = [p for p in done_ if p["status"] == st]
        if rows:
            print("    狀態「%s」 %d 位次  差額 %s" % (st, len(rows), _fmt(sum(p["new"] - p["old"] for p in rows))))
    print("  不可比／會被拒：%d 位次" % (len(people) - len(done_)))
    for p in sorted(done_, key=lambda p: -abs(p["new"] - p["old"]))[:a.top]:
        print("    %-14s %-8s %-10s 舊 %s → 新 %s" % (p["quote_no"], p["status"], p["user"], _fmt(p["old"]), _fmt(p["new"])))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["quote_no", "source", "settled", "pretax", "gross", "old_admin", "new_admin", "old_net", "new_net", "delta", "old_pct", "new_pct"])
            for c in cases:
                w.writerow([c[k] for k in ("quote_no", "source", "settled", "pretax", "gross", "old_admin", "new_admin", "old_net", "new_net", "delta", "old_pct", "new_pct")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
