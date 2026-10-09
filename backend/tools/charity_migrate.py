# -*- coding: utf-8 -*-
"""第 52 班：公益捐款改 報價含稅金額×1% —— 未精算（且已是新管銷口徑）報價單的一次性重算／回滾／模式開關（離線工具）。

[單位] tool:charity_migrate    [層] 部署工具
用法（預設都只讀；沒有 --apply 一律是 dry-run）：
  python tools/charity_migrate.py --db <庫> report                    # dry-run：逐張計畫＋合計＋『12% 門檻達標件數 舊→新』（可加 --csv 檔）
  python tools/charity_migrate.py --db <庫> recalc --apply --set-total
                                                                      # 真的重算：先自動備份 <庫>.pre_charity_<時間>.bak；單一交易
                                                                      #（BEGIN IMMEDIATE 後才規劃、逐張重讀並再檢查已精算／結案）；同一交易把模式設 total、寫完成標記
  python tools/charity_migrate.py --db <庫> rollback [--apply]        # 依舊值快照還原（遷移後才完結／被編輯／已退回舊基者不動，並列出原因）；成功還原後模式設回 direct、刪標記
  python tools/charity_migrate.py --db <庫> mode [direct|total] [--apply]  # 讀／設 system_settings.charity_basis_mode（缺鍵＝direct＝新行為關）
[前置] 必須已完成管銷口徑遷移：overhead_rule_mode=v2 且 overhead_migration_done 標記存在（recalc --apply／mode total --apply 否則拒絕）。
[不變式] 凍結算式在 migrations_frozen/t52_charity/recalc.py（只用標準庫，不依賴 profit_rules）；已精算／結案不動（前後 SHA256 相同）；冪等
  （tot.charityBasis 已是 total 跳過）；管銷分攤沿用存值、不改價格、不碰草稿精算 summary；--db 必填且檔案必須存在（_dbbind，不建空庫）；
  recalc --apply 在模式不是 total 時拒絕，除非加 --set-total（否則舊式表單重存會悄悄把單退回舊基）。建議在系統停用期間執行。
完成標記：recalc --apply 在同一交易寫 system_settings.charity_migration_done = {doneAt, by, recalculated, skipped}；伺服器沒有它就一律當 direct。
先回滾公益、再回滾管銷：管銷回滾（overhead_migrate rollback）遇到公益已改過的單會視為『遷移後又被編輯過』而不還原。
結束碼：0 完成；2 錯誤／參數／前置條件不符。
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
from migrations_frozen.t52_charity import recalc as R             # noqa: E402

MODE_KEY, LOG_KEY, SNAP_KEY, DONE_KEY = "charity_basis_mode", "charity_recalc_log", R.SNAPSHOT_KEY, "charity_migration_done"
OH_MODE_KEY, OH_DONE_KEY = "overhead_rule_mode", "overhead_migration_done"
TARGET_PCT = 12


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
    dst = "%s.pre_charity_%s.bak" % (path, stamp)
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


def _prereq(conn):
    """管銷口徑已是 v2 且完成遷移；回 (ok, 說明)。"""
    if _get(conn, OH_MODE_KEY, "legacy") != "v2" or not isinstance(_get(conn, OH_DONE_KEY), dict):
        return False, "前置條件不符：公益基數遷移需要管銷口徑已是 v2 且完成遷移（%s=v2 ＋ %s 標記）" % (OH_MODE_KEY, OH_DONE_KEY)
    return True, ""


def _summary(items):
    rc = [i for i in items if i["action"] == "recalc"]
    cnt = {}
    for i in items:
        cnt[i["action"]] = cnt.get(i["action"], 0) + 1
    old = sum(float(i["old"]["netProfit"] or 0) for i in rc)
    new = sum(float(i["new"]["netProfit"]) for i in rc)
    oc = sum(float(i["old"]["charityDonation"] or 0) for i in rc)
    nc = sum(float(i["new"]["charityDonation"]) for i in rc)
    ok_old = sum(1 for i in rc if float(i["old"]["netMarginPct"] or 0) >= TARGET_PCT)
    ok_new = sum(1 for i in rc if float(i["new"]["netMarginPct"]) >= TARGET_PCT)
    return cnt, len(rc), old, new, oc, nc, ok_old, ok_new


def _print_plan(items, a, label):
    cnt, n_rc, old, new, oc, nc, ok_old, ok_new = _summary(items)
    f = "{:,.0f}".format
    print("== %s：筆數 %s" % (label, json.dumps(cnt, ensure_ascii=False)))
    print("  重算 %d 張：公益捐款合計 %s → %s（差額 %s）；營業利益合計 %s → %s（差額 %s）" % (n_rc, f(oc), f(nc), f(nc - oc), f(old), f(new), f(new - old)))
    print("  營業利益率 ≥ %d%% 的達標件數（重算件）：%d → %d" % (TARGET_PCT, ok_old, ok_new))
    movers = sorted([x for x in items if x["action"] == "recalc"],
                    key=lambda x: -abs(float(x["new"]["netProfit"]) - float(x["old"]["netProfit"] or 0)))[:a.top]
    for i in movers:
        print("  %-14s 含稅 %s  公益 %s→%s  營業利益 %s→%s  率 %s→%s" % (i["quote_no"], i.get("total"), i["old"]["charityDonation"], i["new"]["charityDonation"],
                                                                  i["old"]["netProfit"], i["new"]["netProfit"], i["old"]["netMarginPct"], i["new"]["netMarginPct"]))
    for i in [x for x in items if x["action"] == "skip_nodata"][:20]:
        print("  略過(資料不足) %s：%s" % (i["quote_no"], i.get("reason")))
    notv2 = [x for x in items if x["action"] == "skip_not_v2"]
    if notv2:
        print("  ⚠ 未結案但尚未是新管銷口徑（formulaVer<2）%d 張，不在本次範圍：%s" % (len(notv2), "、".join(x["quote_no"] for x in notv2[:10])))


def _write_csv(items, a):
    if os.path.abspath(a.csv) == os.path.abspath(a.db):
        print("--csv 不可與 --db 同檔", file=sys.stderr)
        return 2
    with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["quote_no", "action", "settle_status", "deal_tag", "total", "old_charity", "new_charity", "old_net", "new_net", "old_pct", "new_pct"])
        for i in items:
            o, nw = i.get("old") or {}, i.get("new") or {}
            w.writerow([i["quote_no"], i["action"], i["settle_status"], i["deal_tag"], i.get("total", ""), o.get("charityDonation"), nw.get("charityDonation"),
                        o.get("netProfit"), nw.get("netProfit"), o.get("netMarginPct"), nw.get("netMarginPct")])
    return 0


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
    ap.add_argument("--set-total", action="store_true", help="recalc --apply 時在同一交易把公益基數模式設為 total")
    ap.add_argument("--csv", default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args(argv)
    write = (a.apply and a.cmd in ("recalc", "rollback")) or (a.apply and a.cmd == "mode" and bool(a.value))
    conn = _open(a.db, write)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().isoformat()
    try:
        if a.cmd == "mode":
            cur = _get(conn, MODE_KEY, "direct")
            if not a.value:
                print("charity_basis_mode = %s（缺鍵＝direct＝新行為關）" % cur)
                return 0
            if a.value not in ("direct", "total"):
                print("mode 只能是 direct 或 total", file=sys.stderr)
                return 2
            print("charity_basis_mode: %s → %s%s" % (cur, a.value, "" if a.apply else "（dry-run，加 --apply 才寫）"))
            if a.apply:
                conn.execute("BEGIN IMMEDIATE")
                if a.value == "total":
                    ok, why = _prereq(conn)
                    if not ok or _get(conn, DONE_KEY) is None:
                        conn.execute("ROLLBACK")
                        print("拒絕：%s" % (why or "還沒有公益遷移完成標記（%s）；請用 recalc --apply --set-total（同交易寫標記與模式）。" % DONE_KEY), file=sys.stderr)
                        return 2
                _put(conn, MODE_KEY, a.value, now)
                if a.value == "direct":                             # 與伺服器一致：退回 direct 就刪完成標記 ⇒ 之後再切 total 必須重新 recalc
                    conn.execute("DELETE FROM system_settings WHERE key=?", (DONE_KEY,))
                conn.execute("COMMIT")
            return 0
        if a.cmd == "rollback":
            snap = _get(conn, SNAP_KEY, {}) or {}
            items = R.plan_rollback(conn, snap)
            cnt = {}
            for i in items:
                cnt[i["action"]] = cnt.get(i["action"], 0) + 1
            print("== rollback：%s" % json.dumps(cnt, ensure_ascii=False))
            for i in [x for x in items if x["action"].startswith("skip_")][:10]:
                print("  不還原 %s：%s（%s）" % (i["quote_no"], i["action"], i.get("reason")))
            if not a.apply:
                print("（dry-run；加 --apply 才寫）")
                return 0
            if cnt.get("restore"):
                if not a.no_backup:
                    print("備份：", _backup(a.db, stamp))
                conn.execute("BEGIN IMMEDIATE")
                snap = _get(conn, SNAP_KEY, {}) or {}
                items = R.plan_rollback(conn, snap)                      # 交易內重新規劃
                n = R.apply_rollback(conn, items, snap)
                _put(conn, SNAP_KEY, snap, now)
                if n:
                    _put(conn, MODE_KEY, "direct", now)               # 回到 direct 並移除完成標記（伺服器隨即只認 direct）
                    conn.execute("DELETE FROM system_settings WHERE key=?", (DONE_KEY,))
                _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "rollback", "n": n}], now)
                conn.execute("COMMIT")
                print("已還原 %d 張" % n)
            return 0
        items = R.plan(conn)
        _print_plan(items, a, "recalc" if (a.apply and a.cmd == "recalc") else "dry-run")
        if a.csv:
            rc = _write_csv(items, a)
            if rc:
                return rc
        if a.cmd == "recalc":
            if not a.apply:
                print("（dry-run；加 --apply --set-total 才寫）")
                return 0
            ok, why = _prereq(conn)
            if not ok:
                print("拒絕：" + why, file=sys.stderr)
                return 2
            mode = _get(conn, MODE_KEY, "direct")
            if mode != "total" and not a.set_total:
                print("拒絕：公益基數模式目前是 %s。遷移後若不是 total，舊式表單重存會把單悄悄退回舊基；請加 --set-total（同一交易設定）。" % mode, file=sys.stderr)
                return 2
            if not a.no_backup:
                print("備份：", _backup(a.db, stamp))
            conn.execute("BEGIN IMMEDIATE")
            ok, why = _prereq(conn)                                    # 交易內再確認一次前置條件
            if not ok:
                conn.execute("ROLLBACK")
                print("拒絕：" + why, file=sys.stderr)
                return 2
            items = R.plan(conn)                                       # 交易內重新規劃（取得寫鎖之後的現況）
            snap = _get(conn, SNAP_KEY, {}) or {}
            n, skipped = R.apply_plan(conn, items, stamp, snap)
            _put(conn, SNAP_KEY, snap, now)
            _put(conn, DONE_KEY, {"doneAt": datetime.now().isoformat(), "by": os.environ.get("USERNAME") or "charity_migrate",
                                  "recalculated": n, "skipped": skipped + sum(1 for i in items if i["action"].startswith("skip_"))}, now)
            if a.set_total:
                _put(conn, MODE_KEY, "total", now)
            _cnt, _n, old, new, oc, nc, ok_old, ok_new = _summary(items)
            _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "recalc", "n": n, "skippedSettled": skipped, "oldCharity": oc, "newCharity": nc,
                                                                          "oldNet": old, "newNet": new, "modeTotal": bool(a.set_total)}], now)
            conn.execute("COMMIT")
            print("已重算 %d 張（期間已精算而略過 %d 張）%s" % (n, skipped, "；公益基數模式已設 total" if a.set_total else ""))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
