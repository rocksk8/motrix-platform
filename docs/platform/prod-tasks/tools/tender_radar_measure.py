#!/usr/bin/env python3
"""標案雷達載入量測（唯讀）——對應 20260929-tender-radar-measure.md 第 0／1／3／4 節。

只讀：以 sqlite ro 模式開庫、只讀 log 與 .deployed_commit.json；不 import main、不寫安裝目錄、不呼叫 API。
第 2 節（瀏覽器 F12）請用 --ttfb 等參數帶入，或事後手填摘要.md。

用法（正式機 cmd／PowerShell）：
  python tender_radar_measure.py --install-dir "C:\\Users\\Motrix\\Desktop\\V9.0" ^
      --applied-22 no ^
      [--ttfb 6.8s --download 0.2s --size "1.2MB/8MB" --status-time 40ms --watches-time 35ms ^
       --felt 7 --q-time 300ms]
不給 --report-root 則寫到 repo 的 docs/platform/prod-reports/（之後需自行 git add/commit/push）；給 --report-root 可改寫別處。
"""
import argparse, json, re, sqlite3, sys
from datetime import datetime, timedelta
from pathlib import Path

TS = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def commit8(root: Path) -> str:
    p = root / "backend" / ".deployed_commit.json"
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("commit", ""))[:8] or "unknown"
    except Exception as e:  # 讀不到就照實回報
        return f"unknown({type(e).__name__})"


def counts(db: Path) -> list[str]:
    uri = "file:" + db.resolve().as_posix() + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    q = lambda s: c.execute(s).fetchone()
    out = [
        f"- tenders：{q('select count(*) from tenders')[0]}",
        "- watches（總數／啟用）：%s／%s" % q("select count(*), coalesce(sum(enabled),0) from tender_watches"),
        f"- marked：{q('select count(*) from tenders where marked_at is not null')[0]}",
        f"- hits：{q('select count(*) from tender_hits')[0]}",
    ]
    cols = [r[1] for r in c.execute("pragma table_info(tender_fetch_log)")]
    n = q("select count(*) from tender_fetch_log")[0]
    keep = [k for k in cols if re.search(r"time|_at$|status|ok|count|error", k, re.I)]
    last = c.execute(f"select {','.join(keep) or '*'} from tender_fetch_log order by rowid desc limit 1").fetchone()
    summ = {k: (str(v)[:60]) for k, v in zip(keep, last or [])}
    out.append(f"- fetch_log：共 {n} 筆；最近一筆摘要 {summ}")
    c.close()
    return out


def log_section(root: Path, at: datetime) -> tuple[list[str], str]:
    p = root / "backend" / "logs" / "server.log"
    if not p.exists():
        return [f"- 找不到 {p}"], "無 log 可判讀"
    lo, hi = at - timedelta(minutes=5), at + timedelta(minutes=5)
    hits = []
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = TS.search(line)
        if not m or not re.search(r"WARNING|ERROR", line):
            continue
        t = datetime.fromisoformat(m.group(1).replace("T", " "))
        if lo <= t <= hi:
            hits.append(f"L{i}: {line.strip()[:160]}")
    fetch_hour = at.hour in (9, 12, 15, 18)
    lines = [f"- 量測時間 {at:%Y-%m-%d %H:%M}，{'落在' if fetch_hour else '不在'}抓取時段（9／12／15／18 點，以預設為準）",
             f"- ±5 分鐘 WARNING／ERROR：{len(hits)} 行"] + [f"  - {h}" for h in hits[:5]]
    return lines, ("量測時可能與抓取（寫鎖）重疊，數字需複測" if fetch_hour else "無抓取重疊") + f"；log 異常 {len(hits)} 行"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--install-dir", required=True)
    a.add_argument("--report-root", default=str(Path(__file__).resolve().parents[2] / "prod-reports"))
    a.add_argument("--applied-22", choices=["yes", "no"], default="no")
    a.add_argument("--at", help="量測時間 YYYY-MM-DD HH:MM，預設現在")
    for k in ("ttfb", "download", "size", "status-time", "watches-time", "felt", "q-time"):
        a.add_argument("--" + k, default="（待填）")
    o = a.parse_args()

    root = Path(o.install_dir)
    at = datetime.strptime(o.at, "%Y-%m-%d %H:%M") if o.at else datetime.now()
    c8 = commit8(root)
    db_lines = counts(root / "backend" / "motrix_erp.db")
    log_lines, verdict = log_section(root, at)

    md = "\n".join([
        "# 標案雷達載入量測摘要", "",
        "## 0. 版本", f"- commit：{c8}", f"- 量測時間：{at:%Y-%m-%d %H:%M}",
        f"- 已套用第二十二班：{'是' if o.applied_22 == 'yes' else '否（基準值）'}", "",
        "## 1. 資料量", *db_lines, "",
        "## 2. 請求耗時（瀏覽器 F12）",
        f"- /tenders TTFB：{o.ttfb}", f"- Content Download：{o.download}", f"- Size（傳輸／實際）：{o.size}",
        f"- /status Time：{o.status_time}；/watches Time：{o.watches_time}",
        f"- 體感秒數：{o.felt}", f"- tenders?q= Time：{o.q_time}", "",
        "## 3. 同時段狀況", *log_lines, "", f"結論：{verdict}", ""])
    print(md)
    if o.report_root:
        d = Path(o.report_root) / f"{at:%Y%m%d_%H%M}_{c8}_標案量測"
        d.mkdir(parents=True, exist_ok=True)
        (d / "摘要.md").write_text(md, encoding="utf-8")
        print(f"\n已寫入：{d / '摘要.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
