# -*- coding: utf-8 -*-
"""第 48 班 S5：管銷分攤改 直接毛利×pct% —— 未精算報價單一次性重算／回滾／模式開關（離線工具）。

[單位] tool:overhead_migrate    [層] 部署工具
用法（預設都只讀；沒有 --apply 一律是 dry-run）：
  python tools/overhead_migrate.py --db <庫> report                    # dry-run：逐張計畫＋合計（可加 --csv 檔）
  python tools/overhead_migrate.py --db <庫> recalc --apply --set-mode-v2
                                                                       # 真的重算：先自動備份 <庫>.pre_overhead_<時間>.bak；單一交易
                                                                       #（BEGIN IMMEDIATE 後才規劃、逐張重讀並再檢查已精算／結案）；同一交易把模式設 v2
  python tools/overhead_migrate.py --db <庫> rollback [--apply]        # 依舊值快照還原（遷移後才完結／被編輯／已退回舊口徑者不動，並列出原因）
  python tools/overhead_migrate.py --db <庫> mode [legacy|v2] [--apply] # 讀／設 system_settings.overhead_rule_mode（缺鍵＝legacy＝新行為關）
選項：--pct <0–100，最多 1 位小數>（沒有自己百分比的單才用；預設＝system_settings.overhead_default_pct，缺則 25）。
[不變式] 凍結算式在 migrations_frozen/t48_overhead25/recalc.py（只用標準庫，不依賴 profit_rules／ACTIVE_VER）；
  已精算／結案不動；冪等（formulaVer>=2 跳過）；每張單用自己存的百分比；不改價格；不碰草稿精算 summary；
  --db 必填且檔案必須存在（_dbbind，不建空庫）；建議在系統停用期間執行（交易內已重檢查，但仍以停機為準）。
  新口徑遷移後若模式仍是 legacy，舊式表單重存會悄悄把單退回 10% 基準 ⇒ recalc --apply 在模式不是 v2 時拒絕，除非加 --set-mode-v2。
完成標記：recalc --apply 在同一交易寫 system_settings.overhead_migration_done = {doneAt, by, recalculated, skipped}；伺服器沒有它就一律當 legacy，
  獨立 `mode v2 --apply` 沒有標記時拒絕；`mode legacy --apply`（同伺服器 PUT /api/overhead/settings ruleMode=legacy）會刪除標記，
  之後再切 v2 必須重新 recalc；rollback --apply 成功還原後把模式設回 legacy 並刪除標記。
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

MODE_KEY, PCT_KEY, LOG_KEY, SNAP_KEY = "overhead_rule_mode", "overhead_default_pct", "overhead_recalc_log", R.SNAPSHOT_KEY
DONE_KEY = "overhead_migration_done"          # 伺服器（profit_guard.rule_mode）只在這個標記存在時才認 v2；形狀 {doneAt, by, recalculated, skipped}


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


def _force_charity_direct(conn, now):
    """第 52 班：管銷口徑退回 legacy（mode legacy／rollback）時，公益基數 total 一併失效——與伺服器 PUT /api/overhead/settings ruleMode=legacy 同一規則：
    charity_basis_mode 設回 direct、刪 charity_migration_done 標記（否則之後重跑 recalc --set-mode-v2，重遷移的單是未戴戳記的直接毛利基，卻被 charity_basis()=total 當成新基 ⇒ 混基）。
    再次啟用公益新基必須重跑 tools/charity_migrate.py recalc --apply --set-total。"""
    if _get(conn, "charity_basis_mode") is not None:
        _put(conn, "charity_basis_mode", "direct", now)
    conn.execute("DELETE FROM system_settings WHERE key=?", ("charity_migration_done",))


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


def _print_plan(items, a, label):
    cnt, n_rc, old, new = _summary(items)
    print("== %s：筆數 %s" % (label, json.dumps(cnt, ensure_ascii=False)))
    print("  重算 %d 張：舊營業利益合計 %s → 新 %s（差額 %s）" % (n_rc, "{:,.0f}".format(old), "{:,.0f}".format(new), "{:,.0f}".format(new - old)))
    movers = sorted([x for x in items if x["action"] == "recalc"],
                    key=lambda x: -abs(float(x["new"]["netProfit"]) - float(x["old"]["netProfit"] or 0)))[:a.top]
    for i in movers:
        print("  %-14s %s%%  管銷 %s→%s  營業利益 %s→%s  率 %s→%s" % (i["quote_no"], i["pct"], i["old"]["adminCost"], i["new"]["adminCost"],
                                                                 i["old"]["netProfit"], i["new"]["netProfit"], i["old"]["netMarginPct"], i["new"]["netMarginPct"]))
    for i in [x for x in items if x["action"] == "skip_nodata"][:5]:
        print("  略過(資料不足) %s：%s" % (i["quote_no"], i.get("reason")))
    legacy = sorted([x for x in items if x["action"] == "recalc" and float(x.get("legacy_indirect") or 0) != 0], key=lambda x: -abs(float(x["legacy_indirect"])))
    print("  含舊『五項間接成本』非零的未精算單 %d 張（新口徑不再計入；舊值保留在 tot._legacy，合計 %s）" % (len(legacy), "{:,.0f}".format(sum(float(x["legacy_indirect"]) for x in legacy))))
    for i in legacy[:a.top]:
        print("  舊間接成本 %-14s %s（重算後營業利益 %s→%s）" % (i["quote_no"], "{:,.0f}".format(float(i["legacy_indirect"])), i["old"]["netProfit"], i["new"]["netProfit"]))


def _write_csv(items, a):
    if os.path.abspath(a.csv) == os.path.abspath(a.db):
        print("--csv 不可與 --db 同檔", file=sys.stderr)
        return 2
    with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["quote_no", "action", "settle_status", "deal_tag", "pct", "old_admin", "new_admin", "old_net", "new_net", "old_pct", "new_pct", "legacy_indirect"])
        for i in items:
            o, nw = i.get("old") or {}, i.get("new") or {}
            w.writerow([i["quote_no"], i["action"], i["settle_status"], i["deal_tag"], i.get("pct"), o.get("adminCost"), nw.get("adminCost"),
                        o.get("netProfit"), nw.get("netProfit"), o.get("netMarginPct"), nw.get("netMarginPct"), i.get("legacy_indirect", "")])
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
    ap.add_argument("--set-mode-v2", action="store_true", help="recalc --apply 時在同一交易把模式設為 v2")
    ap.add_argument("--pct", default="")
    ap.add_argument("--csv", default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args(argv)
    if a.pct and R.valid_pct(a.pct) is None:
        print("--pct 必須是 0–100 的數字，最多 1 位小數（收到：%r）" % a.pct, file=sys.stderr)
        return 2
    write = (a.apply and a.cmd in ("recalc", "rollback")) or (a.apply and a.cmd == "mode" and bool(a.value))
    conn = _open(a.db, write)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().isoformat()
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
                if a.value == "v2" and _get(conn, DONE_KEY) is None:
                    conn.execute("ROLLBACK")
                    print("拒絕：還沒有遷移完成標記（%s）。伺服器在標記不存在時一律當 legacy；請用 recalc --apply --set-mode-v2（同交易寫標記與模式）。" % DONE_KEY,
                          file=sys.stderr)
                    return 2
                _put(conn, MODE_KEY, a.value, now)
                if a.value == "legacy":                             # 與伺服器一致：退回 legacy 就刪完成標記 ⇒ 之後再切 v2 必須重新 recalc（防止新舊口徑的單混在一起）
                    conn.execute("DELETE FROM system_settings WHERE key=?", (DONE_KEY,))
                    _force_charity_direct(conn, now)
                conn.execute("COMMIT")
            return 0
        default_pct = a.pct or str(_get(conn, PCT_KEY, R.DEFAULT_PCT))
        if R.valid_pct(default_pct) is None:
            print("預設百分比（system_settings.%s=%r）不合法" % (PCT_KEY, default_pct), file=sys.stderr)
            return 2
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
                    _put(conn, MODE_KEY, "legacy", now)               # 回到 legacy 並移除完成標記（伺服器隨即只認 legacy）
                    conn.execute("DELETE FROM system_settings WHERE key=?", (DONE_KEY,))
                    _force_charity_direct(conn, now)                  # 第 52 班：公益新基一併退回 direct（見 _force_charity_direct）
                _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "rollback", "n": n}], now)
                conn.execute("COMMIT")
                print("已還原 %d 張" % n)
            return 0
        items = R.plan(conn, default_pct)
        _print_plan(items, a, "recalc" if (a.apply and a.cmd == "recalc") else "dry-run")
        if a.csv:
            rc = _write_csv(items, a)
            if rc:
                return rc
        if a.cmd == "recalc":
            if not a.apply:
                print("（dry-run；加 --apply --set-mode-v2 才寫）")
                return 0
            mode = _get(conn, MODE_KEY, "legacy")
            if mode != "v2" and not a.set_mode_v2:
                print("拒絕：模式目前是 %s。新口徑遷移後若不是 v2，舊式表單重存會把單悄悄退回 10%% 基準；"
                      "請加 --set-mode-v2（同一交易設定），或先 mode v2 --apply。" % mode, file=sys.stderr)
                return 2
            if not a.no_backup:
                print("備份：", _backup(a.db, stamp))
            conn.execute("BEGIN IMMEDIATE")
            items = R.plan(conn, default_pct)                           # 交易內重新規劃（取得寫鎖之後的現況）
            snap = _get(conn, SNAP_KEY, {}) or {}
            n, skipped = R.apply_plan(conn, items, default_pct, stamp, snap)
            _put(conn, SNAP_KEY, snap, now)
            _put(conn, DONE_KEY, {"doneAt": datetime.now().isoformat(), "by": os.environ.get("USERNAME") or "overhead_migrate",
                                  "recalculated": n, "skipped": skipped + sum(1 for i in items if i["action"].startswith("skip_"))}, now)
            if a.set_mode_v2:
                _put(conn, MODE_KEY, "v2", now)
            _cnt, _n, old, new = _summary(items)
            _put(conn, LOG_KEY, (_get(conn, LOG_KEY, []) or [])[-19:] + [{"at": stamp, "op": "recalc", "n": n, "pct": default_pct, "skippedSettled": skipped,
                                                                          "oldSum": old, "newSum": new, "modeV2": bool(a.set_mode_v2)}], now)
            conn.execute("COMMIT")
            print("已重算 %d 張（期間已精算而略過 %d 張）%s" % (n, skipped, "；模式已設 v2" if a.set_mode_v2 else ""))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
