"""選題範圍的反向控制（PLAYBOOK §C-11a ⑤；稽核 D S-S1）：真突變 ⇒ 新選題要選到「會紅的那一題」，而那一題真的會紅。

用法（repo 根目錄；會暫時改動工作樹的檔、結束一律還原並核對）：
  python tools/platform/scope_rc.py            全部突變
  python tools/platform/scope_rc.py --list     只列出突變
不必每次跑：列入發版前與每批合回後（§G1）。結果附加到主工作樹 full_results/modtest_stats.jsonl（kind＝reverse_control）。

每一項突變：
  1. 套用（檔案內容以 assert 確認原句存在；對不上 ⇒ 失敗，要更新這份清單，不可以靜默略過）
  2. modtest 的選題（名稱層級，HEAD 對工作樹）必須選到 expect 那一題
  3. 實跑 expect 那一題，必須紅
  4. 還原並核對內容
任何一項不成立 ⇒ exit 1。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modtest as MT  # noqa: E402

#: (名稱, 檔案, 原句, 突變後, 會紅的題, 為什麼是真的會出事的突變)
MUTATIONS = [
    ("legal_params._as_date 回傳年份錯", "backend/helpers/legal_params.py",
     "    return date.fromisoformat(s)", "    return date.fromisoformat(s).replace(year=2026)",
     "backend/tests/test_legal_params_r1_2026_09_25.py",
     "私有函式、公開函式呼叫它（稽核 D S-M1 的實證：閉包前完全漏掉）"),
    ("auth._require_user 回傳少了 modules", "backend/helpers/auth.py",
     "    return dict(row)", "    return {k: v for k, v in dict(row).items() if k != 'modules'}",
     "backend/tests/platform/test_auth_user_contract.py",
     "回傳形狀改變（2026-09-26 反向控制：沒選中的出納 e2e 2 題紅 ⇒ 補的契約題）"),
    ("email_notify._users_emails 不再過濾個人退訂", "backend/helpers/email_notify.py",
     '        return [r["email"] for r in rows if _pref_enabled(r["notification_muted"], event_key)]',
     '        return [r["email"] for r in rows]',
     "backend/tests/test_notification_prefs_coverage.py",
     "私有函式、第二個模組的閉包（稽核 D 關閉確認時的新真突變：選中約 89%，抓得到的題都選到且紅）"),
]


def run_one(name, rel, old, new, expect, why):
    p = MT.REPO / rel
    orig = p.read_text(encoding="utf-8")
    if orig.count(old) != 1:
        return {"name": name, "ok": False, "why": "原句在 %s 出現 %d 次（清單過期，要更新）" % (rel, orig.count(old))}
    p.write_text(orig.replace(old, new, 1), encoding="utf-8", newline="\n")
    t0 = time.monotonic()
    try:
        chk = MT.iface_checker(argparse.Namespace(commit=None, changed_since=None, base=None))
        picked, rep = MT.select([rel], MT.load_map(False), MT.load_graph(), chk)
        selected = expect in picked
        red = None
        if selected:
            bt = MT._new_basetemp("scoperc", full=False)     # modtest 的命名 ⇒ _remove_basetemp 才肯刪
            r = subprocess.run([MT.PYEXE or sys.executable, "-m", "pytest", expect[len("backend/"):], "-q",
                                "-p", "no:cacheprovider", "--tb=no", "--basetemp", str(bt)],
                               cwd=str(MT.BACKEND), capture_output=True, text=True, encoding="utf-8",
                               creationflags=MT._low_priority_flags())
            red = r.returncode != 0
            MT._remove_basetemp(bt)
        return {"name": name, "ok": bool(selected and red), "selected": selected, "red": red,
                "files": len(picked), "names": rep.get("names"), "why": why,
                "seconds": round(time.monotonic() - t0, 1)}
    finally:
        p.write_text(orig, encoding="utf-8", newline="\n")
        assert p.read_text(encoding="utf-8") == orig, "還原失敗：" + rel


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for m in MUTATIONS:
            print("%s ⇒ %s（%s）" % (m[0], m[4], m[5]))
        return 0
    MT.PYEXE = MT.resolve_python(None)
    rows, bad = [], 0
    for m in MUTATIONS:
        r = run_one(*m)
        rows.append(r)
        bad += not r["ok"]
        MT._say("%s %s：選到=%s、紅=%s（選中 %s 檔）%s" % ("✓" if r["ok"] else "✗", r["name"], r.get("selected"),
                                                     r.get("red"), r.get("files"), "" if r["ok"] else "  ⇐ " + r["why"]))
    try:
        dest = Path(MT.main_worktree_root()).joinpath(*MT.STATS_REL)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"at": MT._now(), "kind": "reverse_control", "rows": rows}, ensure_ascii=False) + "\n")
    except OSError as e:
        MT._say("⚠ 統計寫不出來：%r" % e)
    return 1 if bad else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
