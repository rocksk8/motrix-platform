# -*- coding: utf-8 -*-
"""已知偶發題登記簿（建包的偶發重跑政策；2026-09-30 使用者「安排建包的優化方式，避免非正常情況的失敗」）。

登記簿：tools/platform/known_flakes.json  {"flakes": [{nodeid, first_seen, owner, ticket, expires, note?}]}
- 建包裡一題紅 ⇒ flaky_retry.py 只把紅的題隔離（循序、單程序）重跑，最多 2 次。
  重跑通過 **而且** 在這裡登記、未過期 ⇒ 繼續打包，manifest 與 fail_stream 記 `flaky_retried`。
  重跑通過但**沒登記** ⇒ 照樣擋下，印出登記指令（人看過才登記——登記＝有人做過「這是偶發、不是缺陷」的決定）。
  每次都紅 ⇒ 擋下。
- **過期的條目讓建包直接失敗**（開頭就查）：登記是「暫時容忍、限期查根因」，不是永久豁免。期限最長 MAX_DAYS 天。

用法：
  python tools/platform/known_flakes.py check                 → 列出；有過期或格式錯 ⇒ exit 1
  python tools/platform/known_flakes.py add --nodeid N --owner O --ticket T [--days 14] [--note ...]
      同一 nodeid 再 add＝延期（含 remove 之後再登記）：每次 ≤14 天、要 --reason；第 2 次延期要換原因＋--root-cause-link；
      第 3 次一律拒絕（稽核 W4）。延期紀錄存在條目的 extensions 與檔案的 removed。
  python tools/platform/known_flakes.py remove --nodeid N
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE / "known_flakes.json"
MAX_DAYS = 30
FIELDS = ("nodeid", "first_seen", "owner", "ticket", "expires")


def _date(s):
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def load(path=None):
    """⇒ (entries, problems)。檔案不存在＝空登記簿（沒有問題）；讀不懂＝problems 非空（呼叫端擋下）。"""
    p = Path(path or DEFAULT_PATH)
    if not p.is_file():
        return [], []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return [], ["登記簿讀不懂：%s（%r）" % (p, e)]
    entries = data.get("flakes") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], ["登記簿格式錯：%s 要是 {\"flakes\": [...]}" % p]
    problems = []
    for i, e in enumerate(entries):
        missing = [f for f in FIELDS if not (isinstance(e, dict) and str(e.get(f) or "").strip())]
        if missing:
            problems.append("第 %d 筆缺欄位 %s：%r" % (i + 1, "、".join(missing), e))
            continue
        try:
            _date(e["first_seen"]), _date(e["expires"])
        except ValueError:
            problems.append("第 %d 筆日期不是 YYYY-MM-DD：%s" % (i + 1, e.get("nodeid")))
    return entries, problems


def expired(entries, today):
    out = []
    for e in entries:
        try:
            if _date(e["expires"]) < today:
                out.append(e)
        except (KeyError, ValueError):
            continue
    return out


def check_messages(entries, problems, today):
    """建包開頭的檢查 ⇒ 擋下的訊息清單（空＝通過）。"""
    msgs = list(problems)
    for e in expired(entries, today):
        msgs.append("已過期（%s）：%s（負責 %s、%s）——根因修好就刪掉這一筆；還沒修好要延期，須由負責人重新登記並寫明理由"
                    % (e["expires"], e["nodeid"], e["owner"], e["ticket"]))
    return msgs


def register_command(nodeid, owner="<負責人>", ticket="<RUN-PLAN 編號>"):
    return ('.venv312\\Scripts\\python.exe tools\\platform\\known_flakes.py add --nodeid "%s" --owner "%s" --ticket "%s" --days 14'
            % (nodeid, owner, ticket))


def decide(results, entries, today):
    """重跑結果 × 登記簿 ⇒ (ok, flaky_retried, messages)。純函式。
    results：[{nodeid, attempts:[exit…], passed: bool}]（passed＝某一次重跑 exit 0）。
    - 任何一題每次都紅 ⇒ 擋。
    - 重跑通過但沒登記（或登記過期）⇒ 擋，附登記指令。
    - 全部通過且都有效登記 ⇒ 放行，回 flaky_retried。
    - results 為空 ⇒ 擋（有紅卻認不出是哪一題 ⇒ 不能確認驗過）。"""
    if not results:
        return False, [], ["紅了卻認不出是哪幾題（收集錯誤、行程被殺或輸出被截斷）——無法確認驗過，不出包。"]
    valid = {e["nodeid"]: e for e in entries if e not in expired(entries, today)}
    stale = {e["nodeid"] for e in expired(entries, today)}
    ok, flaky, msgs = True, [], []
    for r in results:
        nid = r["nodeid"]
        if not r.get("passed"):
            ok = False
            msgs.append("每次都紅（重跑 %d 次）：%s ——真的紅，要修" % (len(r.get("attempts") or []), nid))
        elif nid in valid:
            e = valid[nid]
            flaky.append({"nodeid": nid, "attempts": list(r.get("attempts") or []), "owner": e["owner"],
                          "ticket": e["ticket"], "expires": e["expires"]})
        else:
            ok = False
            why = "登記已過期" if nid in stale else "沒有登記在 known_flakes.json"
            msgs.append("重跑通過但%s：%s\n    偶發不等於沒問題；人看過、確定是偶發（並開了追根因的單）才登記：\n    %s"
                        % (why, nid, register_command(nid)))
    return ok, (flaky if ok else []), msgs


#: 延期規則（稽核 W4，2026-09-30）：每次延期最多 EXTEND_MAX_DAYS 天；第 1 次延期要寫原因；
#: 第 2 次（最後一次）要換一個原因＋附根因追蹤連結；再之後一律拒絕——只能修掉根因後 remove。
EXTEND_MAX_DAYS = 14
MAX_EXTENSIONS = 2


def extension_decision(history, days, reason, link, today):
    """同一 nodeid 再登記＝延期 ⇒ (ok, 訊息, 新的 extensions 清單)。純函式。history＝現有條目或 removed 裡的紀錄（沒有＝首次登記）。"""
    if not history:
        return True, "", []
    exts = list(history.get("extensions") or [])
    n = len(exts) + 1
    reason = (reason or "").strip()
    if n > MAX_EXTENSIONS:
        return False, "已延期 %d 次，不再接受延期——修掉根因後 remove" % len(exts), exts
    if days > EXTEND_MAX_DAYS:
        return False, "延期每次最多 %d 天（給了 %d）" % (EXTEND_MAX_DAYS, days), exts
    if not reason:
        return False, "延期要寫 --reason（為什麼還沒修好）", exts
    if n == MAX_EXTENSIONS:
        if any(reason == (e.get("reason") or "").strip() for e in exts):
            return False, "第 %d 次延期必須換一個原因（與前次相同）" % n, exts
        if not (link or "").strip():
            return False, "第 %d 次延期必須附 --root-cause-link（根因追蹤連結）" % n, exts
    rec = {"date": today.isoformat(), "days": days, "reason": reason}
    if (link or "").strip():
        rec["root_cause_link"] = link.strip()
    return True, "", exts + [rec]


def _removed(path=None):
    try:
        data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8-sig"))
        r = data.get("removed") if isinstance(data, dict) else None
        return r if isinstance(r, list) else []
    except (OSError, ValueError):
        return []


def _write(path, entries, removed=None):
    p = Path(path or DEFAULT_PATH)
    body = {"_說明": "建包偶發重跑登記簿；見 tools/platform/known_flakes.py 與 PLAYBOOK §D-建包。過期的條目會讓建包失敗。",
            "flakes": entries}
    if removed:
        body["removed"] = removed
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path")
    ap.add_argument("--today", help="測試用：YYYY-MM-DD")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    ad = sub.add_parser("add")
    ad.add_argument("--nodeid", required=True)
    ad.add_argument("--owner", required=True)
    ad.add_argument("--ticket", required=True)
    ad.add_argument("--days", type=int, default=14)
    ad.add_argument("--note", default="")
    ad.add_argument("--reason", default="", help="延期（同一 nodeid 已登記過）時必填：為什麼還沒修好")
    ad.add_argument("--root-cause-link", default="", help="第 2 次延期必填：根因追蹤的連結（commit／稽核檔／RUN-PLAN 條目）")
    rm = sub.add_parser("remove")
    rm.add_argument("--nodeid", required=True)
    a = ap.parse_args(argv)
    today = _date(a.today) if a.today else date.today()
    entries, problems = load(a.path)
    if a.cmd == "check":
        msgs = check_messages(entries, problems, today)
        for e in entries:
            print("  %s  到期 %s  %s  %s" % (e.get("nodeid"), e.get("expires"), e.get("owner"), e.get("ticket")))
        for m in msgs:
            print("[known_flakes] " + m)
        print("[known_flakes] %d 筆，%s" % (len(entries), "有問題（見上）" if msgs else "全部有效"))
        return 1 if msgs else 0
    if problems:
        print("\n".join("[known_flakes] " + m for m in problems))
        return 1
    removed = _removed(a.path)
    if a.cmd == "add":
        if not 1 <= a.days <= MAX_DAYS:
            print("[known_flakes] --days 要 1～%d（登記是限期查根因，不是永久豁免）" % MAX_DAYS)
            return 2
        prev = [e for e in entries if e.get("nodeid") == a.nodeid]
        # 移除後重新登記也算延期（延期紀錄保留在 removed，不可以用「刪掉再登記」歸零）
        history = prev[0] if prev else next((r for r in reversed(removed) if r.get("nodeid") == a.nodeid), None)
        ok, msg, exts = extension_decision(history, a.days, a.reason, a.root_cause_link, today)
        if not ok:
            print("[known_flakes] 拒絕：" + msg)
            return 2
        entries = [e for e in entries if e.get("nodeid") != a.nodeid]
        first = history["first_seen"] if history and history.get("first_seen") else today.isoformat()   # 延期不改首次出現日
        entry = {"nodeid": a.nodeid, "first_seen": first, "owner": a.owner, "ticket": a.ticket,
                 "expires": (today + timedelta(days=a.days)).isoformat()}
        if a.note:
            entry["note"] = a.note
        if exts:
            entry["extensions"] = exts
        entries.append(entry)
        _write(a.path, entries, removed)
        print("[known_flakes] 已登記 %s（到期 %s%s）" % (a.nodeid, entry["expires"], "，第 %d 次延期" % len(exts) if exts else ""))
        return 0
    left = [e for e in entries if e.get("nodeid") != a.nodeid]
    if len(left) == len(entries):
        print("[known_flakes] 沒有這一筆：%s" % a.nodeid)
        return 1
    gone = [e for e in entries if e.get("nodeid") == a.nodeid][0]
    removed = removed + [{"nodeid": a.nodeid, "first_seen": gone.get("first_seen"), "removed": today.isoformat(),
                          "extensions": gone.get("extensions") or []}]
    _write(a.path, left, removed)
    print("[known_flakes] 已移除 %s" % a.nodeid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
