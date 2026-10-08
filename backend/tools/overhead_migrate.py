# -*- coding: utf-8 -*-
"""第 48 班 S5：管銷分攤改 直接毛利×pct% —— 未精算報價單一次性重算／回滾／模式開關（離線工具）。

[單位] tool:overhead_migrate    [層] 部署工具
用法（預設都只讀；沒有 --apply 一律是 dry-run）：
  python tools/overhead_migrate.py --db <庫> report                    # dry-run：逐張計畫＋合計（可加 --csv 檔）
  python tools/overhead_migrate.py --db <庫> recalc --apply            # 真的重算（先自動備份 <庫>.pre_overhead_<時間>.bak；單一交易）
  python tools/overhead_migrate.py --db <庫> rollback [--apply]        # 依 tot._legacy 還原（遷移後才完結／結案者不動）
  python tools/overhead_migrate.py --db <庫> mode [legacy|v2] [--apply] # 讀／設 system_settings.overhead_rule_mode（缺鍵＝legacy＝新行為關）
選項：--pct <數字>（預設＝system_settings.overhead_default_pct，缺則 25）。
[不變式] 凍結算式在 migrations_frozen/t48_overhead25/recalc.py（只用標準庫，不依賴 profit_rules／ACTIVE_VER）；
  已精算／結案不動；冪等（formulaVer>=2 跳過）；不改價格；不碰草稿精算 summary；--db 必填且檔案必須存在（_dbbind，不建空庫）。
結束碼：0 完成；2 錯誤／參數。
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_HERE), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import _dbbind                                                    # noqa: E402
from migrations_frozen.t48_overhead25 import recalc as R          # noqa: E402

MODE_KEY, PCT_KEY, LOG_KEY = "overhead_rule_mode", "overhead_default_pct", "overhead_recalc_log"


def _get(conn, key, default=None):
    r = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["value_json"])
    except (TypeError, ValueError):
        return default


def _put(conn, key, value, now):
    conn.execute("INSERT INTO system_settings(key, value_json, updated_at) VALUES(?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                 (key, json.dumps(value, ensure_ascii=False), now))


def _open(path, write):
    _dbbind.require_file(path)
    if write:
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)       # 手動 BEGIN IMMEDIATE
    else:
        conn = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _backup(path, stamp):
    dst = "%s.pre_overhead_%s.bak" % (path, stamp)
    src = sqlite3.connect(path)
    try:
        out = sqlite3.connect(dst)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dst


def _summary(items):
    rc = [i for i in items if i["action"] == "recalc"]
    cnt = {}
    for i in items:
        cnt[i["action"]] = cnt.get(i["action"], 0) + 1
    old = sum(float(i["old"]["netProfit"] or 0) for i in rc)
    new = sum(float(i["new"]["netProfit"]) for i in rc)
    return cnt, len(rc), old, new


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("cmd", choices=["report", "recalc", "rollback", "mode"])
    ap.add_argument("value", nargs="?", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pct", default="")
    ap.add_argument("--csv", default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args(argv)
    write = a.apply and a.cmd in ("recalc", "rollback") or (a.apply and a.cmd == "mode" and bool(a.value))
    conn = _open(a.db, write)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if a.cmd == "mode":
            cur = _get(conn, MODE_KEY, "legacy")
            if not a.value:
                print("overhead_rule_mode = %s（缺鍵＝legacy＝新行為關）" % cur)
                return 0
            if a.value not in ("legacy", "v2"):
                print("mode 只能是 legacy 或 v2", file=sys.stderr)
                return 2
            print("overhead_rule_mode: %s → %s%s" % (cur, a.value, "" if a.apply else "（dry-run，加 --apply 才寫）"))
            if a.apply:
                conn.execute("BEGIN IMMEDIATE")
                _put(conn, MODE_KEY, a.value, datetime.now().isoformat())
                conn.execute("COMMIT")
            return 0
        pct = a.pct or str(_get(conn, PCT_KEY, R.DEFAULT_PCT))
        if a.cmd == "rollback":
            items = R.plan_rollback(conn)
            rs = [i for i in items if i["action"] == "restore"]
            print("== rollback：可還原 %d 張；略過（遷移後已完結／結案）%d 張" % (len(rs), len(items) - len(rs)))
            if a.apply and rs:
                if not a.no_backup:
                    print("備份：", _backup(a.db, stamp))
                conn.execute("BEGIN IMMEDIATE")
                n = R.apply_rollback(conn, items)
                _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "rollback", "n": n}], datetime.now().isoformat())
                conn.execute("COMMIT")
                print("已還原 %d 張" % n)
            elif not a.apply:
                print("（dry-run；加 --apply 才寫）")
            return 0
        items = R.plan(conn, pct)
        cnt, n_rc, old, new = _summary(items)
        print("== %s：pct=%s%%；筆數 %s" % ("recalc" if (a.apply and a.cmd == "recalc") else "dry-run", pct, json.dumps(cnt, ensure_ascii=False)))
        print("  重算 %d 張：舊營業利益合計 %s → 新 %s（差額 %s）" % (n_rc, "{:,.0f}".format(old), "{:,.0f}".format(new), "{:,.0f}".format(new - old)))
        movers = sorted([x for x in items if x["action"] == "recalc"],
                        key=lambda x: -abs(float(x["new"]["netProfit"]) - float(x["old"]["netProfit"] or 0)))[:a.top]
        for i in movers:
            print("  %-14s 管銷 %s→%s  營業利益 %s→%s  率 %s→%s" % (i["quote_no"], i["old"]["adminCost"], i["new"]["adminCost"], i["old"]["netProfit"],
                                                               i["new"]["netProfit"], i["old"]["netMarginPct"], i["new"]["netMarginPct"]))
        for i in [x for x in items if x["action"] == "skip_nodata"][:5]:
            print("  略過(資料不足) %s：%s" % (i["quote_no"], i.get("reason")))
        if a.csv:
            if os.path.abspath(a.csv) == os.path.abspath(a.db):
                print("--csv 不可與 --db 同檔", file=sys.stderr)
                return 2
            with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["quote_no", "action", "settle_status", "deal_tag", "old_admin", "new_admin", "old_net", "new_net", "old_pct", "new_pct"])
                for i in items:
                    o, nw = i.get("old") or {}, i.get("new") or {}
                    w.writerow([i["quote_no"], i["action"], i["settle_status"], i["deal_tag"], o.get("adminCost"), nw.get("adminCost"),
                                o.get("netProfit"), nw.get("netProfit"), o.get("netMarginPct"), nw.get("netMarginPct")])
        if a.cmd == "recalc":
            if not a.apply:
                print("（dry-run；加 --apply 才寫）")
                return 0
            if not a.no_backup:
                print("備份：", _backup(a.db, stamp))
            conn.execute("BEGIN IMMEDIATE")
            n = R.apply_plan(conn, items, pct, stamp)
            _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "recalc", "n": n, "pct": pct, "oldSum": old, "newSum": new}],
                 datetime.now().isoformat())
            conn.execute("COMMIT")
            print("已重算 %d 張（舊值在 tot._legacy；模式開關另用 mode 子命令，本命令不改 overhead_rule_mode）" % n)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
